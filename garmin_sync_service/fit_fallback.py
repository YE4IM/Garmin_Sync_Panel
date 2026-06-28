from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def _fitparse_file(path: Path):
    from fitparse import FitFile
    from fitparse.processors import FitFileDataProcessor

    class LenientProcessor(FitFileDataProcessor):
        def process_type_localtime_into_day(self, field_data):
            return

    return FitFile(str(path), data_processor=LenientProcessor())


def _value(message, name: str, default: Any = None) -> Any:
    try:
        value = message.get_value(name)
    except Exception:
        return default
    return default if value is None else value


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _semicircles_to_degrees(value: Any) -> float | str:
    parsed = _num(value)
    if not parsed:
        return ""
    return round(parsed * (180.0 / 2147483648.0), 7)


def parse_fit_laps(path: Path, activity_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        fit = _fitparse_file(path)
        laps = [message for message in fit.get_messages() if message.name == "lap"]
    except Exception:
        return []
    output = []
    for index, lap in enumerate(laps):
        distance_m = _num(_value(lap, "total_distance"))
        duration_s = _num(_value(lap, "total_elapsed_time") or _value(lap, "total_timer_time"))
        avg_speed = _num(_value(lap, "avg_speed") or _value(lap, "enhanced_avg_speed"))
        pace = (1000.0 / avg_speed) if avg_speed > 0 else (duration_s / (distance_m / 1000.0) if distance_m > 0 and duration_s > 0 else 0)
        if distance_m <= 0 and duration_s <= 0:
            continue
        output.append({
            "id": None,
            "activity_id": activity_id,
            "lap_index": index,
            "distance_m": distance_m,
            "duration_s": duration_s,
            "avg_pace_s_per_km": pace,
            "avg_hr": _int(_value(lap, "avg_heart_rate")),
            "calories": _int(_value(lap, "total_calories")),
            "source": "fitparse_fallback",
        })
    return output


def parse_fit_record_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fieldnames = [
        "timestamp",
        "elapsed_s",
        "distance_m",
        "distance_km",
        "heart_rate",
        "pace_sec_per_km",
        "speed_mps",
        "cadence",
        "power_w",
        "altitude_m",
        "latitude",
        "longitude",
        "temperature_c",
    ]
    if not path.exists():
        return [], {"available": False, "reason": "FIT file not found"}
    rows: list[dict[str, Any]] = []
    try:
        fit = _fitparse_file(path)
        started_at: datetime | None = None
        for message in fit.get_messages("record"):
            timestamp = _value(message, "timestamp")
            if isinstance(timestamp, datetime):
                if started_at is None:
                    started_at = timestamp
                elapsed_s: float | str = round((timestamp - started_at).total_seconds(), 1)
                timestamp_value = timestamp.isoformat()
            else:
                elapsed_s = ""
                timestamp_value = str(timestamp or "")
            distance_m = _num(_value(message, "distance"))
            speed_mps = _num(_value(message, "enhanced_speed") or _value(message, "speed"))
            rows.append({
                "timestamp": timestamp_value,
                "elapsed_s": elapsed_s,
                "distance_m": round(distance_m, 2) if distance_m else "",
                "distance_km": round(distance_m / 1000.0, 3) if distance_m else "",
                "heart_rate": _int(_value(message, "heart_rate")) or "",
                "pace_sec_per_km": round(1000.0 / speed_mps, 1) if speed_mps else "",
                "speed_mps": round(speed_mps, 3) if speed_mps else "",
                "cadence": _int(_value(message, "cadence")) or "",
                "power_w": _int(_value(message, "power")) or "",
                "altitude_m": round(_num(_value(message, "enhanced_altitude") or _value(message, "altitude")), 2) or "",
                "latitude": _semicircles_to_degrees(_value(message, "position_lat")),
                "longitude": _semicircles_to_degrees(_value(message, "position_long")),
                "temperature_c": _int(_value(message, "temperature")) or "",
            })
    except Exception as exc:
        return [], {"available": False, "fitFile": path.name, "reason": f"fitparse fallback failed: {exc}"}
    return rows, {"available": True, "fitFile": path.name, "records": len(rows), "parser": "fitparse"}
