"""
TCX 分段解析模块
作为 FIT 解析失败时的兜底数据源。
"""
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from core.models import Activity, LapData

logger = logging.getLogger(__name__)


def _text(element, name: str) -> str:
    found = element.find(f".//{{*}}{name}")
    return found.text.strip() if found is not None and found.text else ""


def _float(value: str, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _int(value: str, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _pace(distance_m: float, duration_s: float) -> float:
    return duration_s / (distance_m / 1000.0) if distance_m > 0 and duration_s > 0 else 0.0


def parse_tcx_laps(file_path: str | Path, activity: Activity) -> List[LapData]:
    path = Path(file_path)
    if not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        logger.warning(f"TCX 解析失败 {path}: {exc}")
        return []

    laps = _parse_native_laps(root, activity.activity_id)
    if laps:
        return laps
    return _build_laps_from_trackpoints(root, activity)


def _parse_native_laps(root, activity_id: str) -> List[LapData]:
    output: List[LapData] = []
    for index, lap in enumerate(root.findall(".//{*}Activity/{*}Lap")):
        distance_m = _float(_text(lap, "DistanceMeters"))
        duration_s = _float(_text(lap, "TotalTimeSeconds"))
        if distance_m <= 0 and duration_s <= 0:
            continue
        output.append(LapData(
            activity_id=activity_id,
            lap_index=index,
            distance_m=distance_m,
            duration_s=duration_s,
            avg_pace_s_per_km=_pace(distance_m, duration_s),
            avg_hr=_int(_text(lap, "Value")),
            calories=_int(_text(lap, "Calories")),
        ))
    return output


def _build_laps_from_trackpoints(root, activity: Activity) -> List[LapData]:
    points = []
    for point in root.findall(".//{*}Trackpoint"):
        distance = _float(_text(point, "DistanceMeters"))
        heart_rate = _int(_text(point, "Value"))
        time_text = _text(point, "Time")
        if distance <= 0:
            continue
        points.append({"distance": distance, "heartRate": heart_rate, "time": time_text})
    if not points:
        return []

    output: List[LapData] = []
    previous_distance = 0.0
    previous_elapsed = 0.0
    duration_s = float(activity.duration_s or 0)
    total_distance = float(activity.distance_m or points[-1]["distance"])
    next_split = 1000.0
    for point in points:
        distance = point["distance"]
        if distance < next_split and distance < total_distance:
            continue
        elapsed = (distance / total_distance * duration_s) if total_distance and duration_s else 0
        lap_distance = max(distance - previous_distance, 0)
        lap_duration = max(elapsed - previous_elapsed, 0)
        output.append(LapData(
            activity_id=activity.activity_id,
            lap_index=len(output),
            distance_m=lap_distance,
            duration_s=lap_duration,
            avg_pace_s_per_km=_pace(lap_distance, lap_duration),
            avg_hr=point["heartRate"],
            calories=0,
        ))
        previous_distance = distance
        previous_elapsed = elapsed
        next_split += 1000.0

    if previous_distance < total_distance:
        lap_distance = total_distance - previous_distance
        lap_duration = max(duration_s - previous_elapsed, 0)
        if lap_distance > 50 or not output:
            output.append(LapData(
                activity_id=activity.activity_id,
                lap_index=len(output),
                distance_m=lap_distance,
                duration_s=lap_duration,
                avg_pace_s_per_km=_pace(lap_distance, lap_duration),
                avg_hr=0,
                calories=0,
            ))
    return output
