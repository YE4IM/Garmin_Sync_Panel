from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings


def _bytes_from_kb(value: str) -> int:
    try:
        return int(value.split()[0]) * 1024
    except Exception:
        return 0


def _memory_status() -> dict[str, Any]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = _bytes_from_kb(value)
    except Exception:
        return {}
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(total - available, 0)
    return {
        "totalBytes": total,
        "availableBytes": available,
        "usedBytes": used,
        "usedPct": round(used / total * 100, 1) if total else 0,
    }


def _disk_status(path: Path) -> dict[str, Any]:
    try:
        stat = os.statvfs(str(path))
    except Exception:
        return {"path": str(path)}
    total = stat.f_frsize * stat.f_blocks
    free = stat.f_frsize * stat.f_bavail
    used = max(total - free, 0)
    return {
        "path": str(path),
        "totalBytes": total,
        "freeBytes": free,
        "usedBytes": used,
        "usedPct": round(used / total * 100, 1) if total else 0,
    }


def _process_status() -> dict[str, Any]:
    rss = 0
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss = _bytes_from_kb(line.split(":", 1)[1])
                break
    except Exception:
        pass
    return {"pid": os.getpid(), "rssBytes": rss}


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() and path.is_file() else 0
    except Exception:
        return 0


def _dir_size(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except Exception:
        return total
    return total


def _data_status(settings: Settings) -> dict[str, Any]:
    reports = [
        path
        for path in settings.reports_dir.glob("garmin-daily-*")
        if path.is_dir() or path.suffix == ".zip"
    ] if settings.reports_dir.exists() else []
    reports.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    history_path = _history_path(settings)
    return {
        "activityDbExists": settings.activity_db_path.exists(),
        "activityDbBytes": _file_size(settings.activity_db_path),
        "weightDataExists": settings.weight_data_path.exists(),
        "weightDataBytes": _file_size(settings.weight_data_path),
        "runtimeBytes": _dir_size(settings.runtime_dir),
        "reportsBytes": _dir_size(settings.reports_dir),
        "logsBytes": _dir_size(settings.logs_dir),
        "reportsCount": len(reports),
        "latestReport": reports[0].name if reports else "",
        "aiCacheBytes": _file_size(settings.ai_analysis_path),
        "serviceHistoryBytes": _file_size(history_path),
    }


def _uptime_seconds() -> float:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except Exception:
        return 0


def _history_path(settings: Settings) -> Path:
    return settings.runtime_dir / "service_status_history.json"


def _read_history(settings: Settings) -> list[dict[str, Any]]:
    path = _history_path(settings)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_history(settings: Settings, rows: list[dict[str, Any]]) -> None:
    path = _history_path(settings)
    path.write_text(json.dumps(rows[-288:], ensure_ascii=False, indent=2), encoding="utf-8")


def record_service_status(settings: Settings, *, ok: bool = True, message: str = "ok") -> None:
    now = datetime.now()
    history = _read_history(settings)
    if history:
        try:
            last = datetime.fromisoformat(str(history[-1].get("checkedAt")))
            if now - last < timedelta(minutes=5) and history[-1].get("ok") == ok:
                return
        except Exception:
            pass
    history.append({
        "checkedAt": now.isoformat(timespec="seconds"),
        "ok": bool(ok),
        "message": message,
    })
    _write_history(settings, history)


def system_status_payload(settings: Settings) -> dict[str, Any]:
    history = _read_history(settings)
    recent = history[-24:]
    failures = [row for row in recent if row.get("ok") is not True]
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "memory": _memory_status(),
        "disk": _disk_status(settings.root_dir),
        "runtimeDisk": _disk_status(settings.runtime_dir),
        "process": _process_status(),
        "data": _data_status(settings),
        "uptimeSeconds": _uptime_seconds(),
        "history": recent,
        "recentOk": not failures,
        "recentFailures": len(failures),
    }
