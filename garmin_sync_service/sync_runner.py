from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings


STEP_LABELS = {
    "activity_init": "初始化运动数据",
    "activity_sync": "同步 Garmin 运动",
    "health_sync": "同步 Garmin 健康",
    "activity_export": "刷新网页数据",
    "weight_sync": "同步小米体脂到 Garmin",
}


@dataclass
class CommandResult:
    name: str
    command: list[str]
    cwd: str
    returncode: int
    started_at: str
    finished_at: str
    stdout_tail: str
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SyncRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status = self._initial_status()

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _read_last_run(self) -> dict:
        if not self.settings.last_run_path.exists():
            return {"ok": None, "message": "no sync run recorded"}
        try:
            return json.loads(self.settings.last_run_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": None, "message": f"could not read last sync: {exc}"}

    def _last_run_summary(self, last_run: dict) -> dict:
        results = last_run.get("results") or []
        return {
            "ok": last_run.get("ok"),
            "startedAt": last_run.get("startedAt"),
            "finishedAt": last_run.get("finishedAt"),
            "stepCount": len(results),
            "failedSteps": [
                item.get("name")
                for item in results
                if item.get("returncode") not in (None, 0)
            ],
            "error": last_run.get("error"),
        }

    def _initial_status(self) -> dict:
        last_run = self._read_last_run()
        finished_at = last_run.get("finishedAt")
        ok = last_run.get("ok")
        state = "idle" if ok is None else "success" if ok else "failed"
        message = "等待同步" if ok is None else "上次同步成功" if ok else "上次同步失败"
        return {
            "running": False,
            "state": state,
            "message": message,
            "currentStep": "",
            "currentStepLabel": "",
            "startedAt": None,
            "finishedAt": finished_at,
            "lastSyncAt": finished_at,
            "lastSuccessAt": finished_at if ok else None,
            "lastRunOk": ok,
            "progress": {"completed": 0, "total": 0, "percent": 0},
            "updatedAt": self._now(),
            "lastRun": self._last_run_summary(last_run),
        }

    def _set_status(self, **updates) -> None:
        with self._status_lock:
            self._status.update(updates)
            self._status["updatedAt"] = self._now()

    def status(self) -> dict:
        with self._status_lock:
            status = dict(self._status)
            status["progress"] = dict(status.get("progress") or {})
            status["lastRun"] = dict(status.get("lastRun") or {})
        if not status.get("running"):
            last_run = self._read_last_run()
            finished_at = last_run.get("finishedAt")
            ok = last_run.get("ok")
            if finished_at:
                status["lastSyncAt"] = finished_at
                status["finishedAt"] = finished_at
                status["lastRunOk"] = ok
                if ok:
                    status["lastSuccessAt"] = finished_at
            status["lastRun"] = self._last_run_summary(last_run)
        return status

    def _run(self, name: str, command: list[str], cwd: Path) -> CommandResult:
        started_at = datetime.now().isoformat(timespec="seconds")
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=self.settings.command_timeout_seconds,
            check=False,
        )
        finished_at = datetime.now().isoformat(timespec="seconds")
        return CommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=proc.returncode,
            started_at=started_at,
            finished_at=finished_at,
            stdout_tail=(proc.stdout or "")[-8000:],
            stderr_tail=(proc.stderr or "")[-8000:],
        )

    def run_all(self, steps: set[str] | None = None) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "sync already running", "startedAt": self._now(), "status": self.status()}
        run_started = self._now()
        payload: dict | None = None
        try:
            commands = [
                (
                    "activity_init",
                    [self.settings.python_bin, "main.py", "--config", "config.json", "init"],
                    self.settings.activity_project_dir,
                ),
                (
                    "activity_sync",
                    [
                        self.settings.python_bin,
                        "main.py",
                        "--config",
                        "config.json",
                        "sync",
                        "--days",
                        str(self.settings.sync_activity_days),
                        "--export",
                    ],
                    self.settings.activity_project_dir,
                ),
                (
                    "health_sync",
                    [
                        self.settings.python_bin,
                        "main.py",
                        "--config",
                        "config.json",
                        "sync-health",
                        "--days",
                        str(self.settings.sync_health_days),
                    ],
                    self.settings.activity_project_dir,
                ),
                (
                    "activity_export",
                    [self.settings.python_bin, "main.py", "--config", "config.json", "export"],
                    self.settings.activity_project_dir,
                ),
                (
                    "weight_sync",
                    [
                        self.settings.python_bin,
                        "src/main.py",
                        "--config",
                        "users.json",
                        "--sync",
                        "--output-dir",
                        "data/garmin-fit",
                    ],
                    self.settings.weight_project_dir,
                ),
            ]
            if steps is not None:
                commands = [item for item in commands if item[0] in steps]
            results: list[CommandResult] = []
            total = len(commands)
            self._set_status(
                running=True,
                state="running",
                message="同步已开始",
                currentStep="",
                currentStepLabel="准备同步",
                startedAt=run_started,
                finishedAt=None,
                progress={"completed": 0, "total": total, "percent": 0},
            )
            try:
                for index, (name, command, cwd) in enumerate(commands, start=1):
                    label = STEP_LABELS.get(name, name)
                    self._set_status(
                        currentStep=name,
                        currentStepLabel=label,
                        message=f"{label}中",
                        progress={
                            "completed": index - 1,
                            "total": total,
                            "percent": round(((index - 1) / total) * 100),
                        },
                    )
                    result = self._run(name, command, cwd)
                    results.append(result)
                    self._set_status(
                        message=f"{label}{'完成' if result.ok else '失败'}",
                        progress={
                            "completed": index,
                            "total": total,
                            "percent": round((index / total) * 100),
                        },
                    )
            except Exception as exc:
                payload = {
                    "ok": False,
                    "error": str(exc),
                    "startedAt": run_started,
                    "finishedAt": self._now(),
                    "results": [asdict(item) for item in results],
                }
                self.settings.last_run_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._set_status(
                    running=False,
                    state="failed",
                    message=f"同步失败：{exc}",
                    finishedAt=payload["finishedAt"],
                    lastSyncAt=payload["finishedAt"],
                    lastRunOk=False,
                    lastRun=self._last_run_summary(payload),
                )
                return payload
            payload = {
                "ok": all(item.ok for item in results),
                "startedAt": results[0].started_at if results else datetime.now().isoformat(),
                "finishedAt": datetime.now().isoformat(timespec="seconds"),
                "results": [asdict(item) for item in results],
            }
            self.settings.last_run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            ok = bool(payload["ok"])
            self._set_status(
                running=False,
                state="success" if ok else "failed",
                message="同步完成" if ok else "同步完成，但有步骤失败",
                currentStep="",
                currentStepLabel="",
                finishedAt=payload["finishedAt"],
                lastSyncAt=payload["finishedAt"],
                lastSuccessAt=payload["finishedAt"] if ok else self.status().get("lastSuccessAt"),
                lastRunOk=ok,
                progress={"completed": total, "total": total, "percent": 100},
                lastRun=self._last_run_summary(payload),
            )
            return payload
        finally:
            self._lock.release()

    def last_run(self) -> dict:
        return self._read_last_run()
