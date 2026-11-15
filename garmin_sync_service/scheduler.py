from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime

from .ai_analysis import generate_ai_analysis_if_needed
from .config import Settings
from .dashboard import dashboard_payload
from .reporting import generate_report, send_report_email
from .sync_runner import SyncRunner


class DailyScheduler:
    def __init__(self, settings: Settings, runner: SyncRunner):
        self.settings = settings
        self.runner = runner
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state_path = settings.runtime_dir / "scheduler_state.json"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="garmin-sync-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.now()
                today = date.today().isoformat()
                state = self._state()
                if now.strftime("%H:%M") >= self.settings.daily_run_time and state.get("lastRunDate") != today:
                    sync_result = self.runner.run_all(steps=set(self.settings.auto_sync_steps))
                    ai = None
                    if sync_result.get("ok") and self.settings.ai_auto_analyze_after_sync:
                        payload = dashboard_payload(self.settings, include_long_range=True)
                        payload["syncStatus"] = self.runner.status()
                        ai = generate_ai_analysis_if_needed(
                            self.settings,
                            payload,
                            source_finished_at=str(sync_result.get("finishedAt") or ""),
                        )
                    report = generate_report(self.settings, sync_result)
                    mail = send_report_email(self.settings, report)
                    self._write_state({
                        "lastRunDate": today,
                        "lastRunAt": datetime.now().isoformat(timespec="seconds"),
                        "syncOk": sync_result.get("ok"),
                        "ai": ai,
                        "report": report,
                        "mail": mail,
                    })
            except Exception as exc:
                self._write_state({
                    **self._state(),
                    "lastErrorAt": datetime.now().isoformat(timespec="seconds"),
                    "lastError": str(exc),
                })
            self._stop.wait(60)
