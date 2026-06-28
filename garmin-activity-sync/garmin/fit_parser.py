"""
FIT 文件解析模块
解析 Garmin FIT 格式的运动活动文件
兼容字段缺失情况，所有字段解析时做 None 检查
"""
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple, List

from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.lap_message import LapMessage

from core.models import Activity, LapData

logger = logging.getLogger(__name__)

# FIT 时间戳基准：1989-12-31 00:00:00 UTC
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

# 运动类型映射（FIT sport enum -> 字符串）
SPORT_MAP = {
    0: "generic",
    1: "running",
    2: "cycling",
    3: "transition",
    4: "fitness_equipment",
    5: "swimming",
    6: "basketball",
    7: "soccer",
    8: "tennis",
    9: "american_football",
    10: "training",
    11: "walking",
    12: "cross_country_skiing",
    13: "alpine_skiing",
    14: "snowboarding",
    15: "rowing",
    16: "mountaineering",
    17: "hiking",
    18: "multisport",
    19: "paddling",
    20: "flying",
    21: "e_biking",
    22: "motorcycling",
    23: "boating",
    24: "driving",
    25: "golf",
    26: "hang_gliding",
    27: "horseback_riding",
    28: "hunting",
    29: "fishing",
    30: "inline_skating",
    31: "rock_climbing",
    32: "sailing",
    33: "ice_skating",
    34: "sky_diving",
    35: "snowshoeing",
    36: "snowmobiling",
    37: "stand_up_paddleboarding",
    38: "surfing",
    39: "wakeboarding",
    40: "water_skiing",
    41: "kayaking",
    42: "rafting",
    43: "windsurfing",
    44: "kitesurfing",
    45: "tactical",
    46: "jumpmaster",
    47: "boxing",
    48: "floor_climbing",
    53: "diving",
    55: "yoga",
    56: "pilates",
    57: "stretching",
    58: "strength_training",
    59: "cardio",
    61: "hiit",
    62: "rugby",
    64: "boxing",
    65: "mixed_martial_arts",
    254: "all",
}


def _safe_float(value, default: float = 0.0) -> float:
    """安全转换为 float，None 或异常返回默认值"""
    if value is None:
        return default
    try:
        result = float(value)
        return result if not (result != result) else default  # NaN 检查
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """安全转换为 int，None 或异常返回默认值"""
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def _calc_pace(distance_m: float, duration_s: float) -> float:
    """
    计算配速（秒/公里）

    Args:
        distance_m: 距离（米）
        duration_s: 时长（秒）

    Returns:
        配速（秒/公里），无效输入返回 0
    """
    if distance_m <= 0 or duration_s <= 0:
        return 0.0
    km = distance_m / 1000
    return duration_s / km


def _generate_activity_id(file_path: Path, start_time: Optional[datetime]) -> str:
    """
    生成活动 ID（基于文件路径和开始时间的哈希）

    Args:
        file_path: FIT 文件路径
        start_time: 开始时间

    Returns:
        活动 ID 字符串
    """
    key = str(file_path)
    if start_time:
        key += start_time.isoformat()
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _get_sport_name(sport_value) -> str:
    """
    获取运动类型名称

    Args:
        sport_value: FIT sport 值（可能是 int 或 str）

    Returns:
        运动类型字符串
    """
    if sport_value is None:
        return "unknown"
    if isinstance(sport_value, str):
        return sport_value.lower()
    return SPORT_MAP.get(int(sport_value), "unknown")


def parse_fit_file(file_path: str | Path) -> Optional[Tuple[Activity, List[LapData]]]:
    """
    解析 FIT 文件，提取活动和分圈数据

    Args:
        file_path: FIT 文件路径

    Returns:
        (Activity, List[LapData]) 元组，解析失败返回 None
    """
    file_path = Path(file_path)

    if not file_path.exists():
        logger.error(f"FIT 文件不存在: {file_path}")
        return None

    previous_logging_disable = logging.root.manager.disable
    try:
        logging.disable(logging.ERROR)
        fit_file = FitFile.from_file(str(file_path))
    except Exception as e:
        logger.warning(f"fit-tool 无法读取 FIT 文件 {file_path}: {e}，尝试 fitparse fallback")
        return _parse_fit_file_with_fitparse(file_path)
    finally:
        logging.disable(previous_logging_disable)

    # 查找 session 和 lap 消息
    session_msg: Optional[SessionMessage] = None
    lap_msgs: List[LapMessage] = []

    for record in fit_file.records:
        msg = record.message
        if isinstance(msg, SessionMessage):
            session_msg = msg
        elif isinstance(msg, LapMessage):
            lap_msgs.append(msg)

    if session_msg is None:
        logger.warning(f"FIT 文件中未找到 session 数据: {file_path}")
        # 尝试从 lap 数据构建活动
        if lap_msgs:
            return _build_activity_from_laps(file_path, lap_msgs)
        return _parse_fit_file_with_fitparse(file_path)

    # 解析 session 数据
    activity = _parse_session(file_path, session_msg)

    # 解析 lap 数据
    laps = []
    for i, lap_msg in enumerate(lap_msgs):
        lap = _parse_lap(activity.activity_id, i, lap_msg)
        if lap:
            laps.append(lap)

    if not laps:
        fallback = _parse_fit_file_with_fitparse(file_path)
        if fallback and fallback[1]:
            return fallback

    return activity, laps


def _fitparse_value(message, name: str, default=None):
    try:
        value = message.get_value(name)
    except Exception:
        return default
    return default if value is None else value


def _parse_fitparse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None
    return None


def _parse_fitparse_lap(activity_id: str, lap_index: int, message) -> LapData:
    distance_m = _safe_float(_fitparse_value(message, "total_distance"))
    duration_s = _safe_float(
        _fitparse_value(message, "total_elapsed_time")
        or _fitparse_value(message, "total_timer_time")
    )
    avg_speed = _safe_float(_fitparse_value(message, "avg_speed") or _fitparse_value(message, "enhanced_avg_speed"))
    avg_pace = 1000.0 / avg_speed if avg_speed > 0 else _calc_pace(distance_m, duration_s)
    return LapData(
        activity_id=activity_id,
        lap_index=lap_index,
        distance_m=distance_m,
        duration_s=duration_s,
        avg_pace_s_per_km=avg_pace,
        avg_hr=_safe_int(_fitparse_value(message, "avg_heart_rate")),
        calories=_safe_int(_fitparse_value(message, "total_calories")),
    )


def _parse_fit_file_with_fitparse(file_path: Path) -> Optional[Tuple[Activity, List[LapData]]]:
    try:
        from fitparse import FitFile as FitParseFile
        from fitparse.processors import FitFileDataProcessor
    except Exception as exc:
        logger.error(f"fitparse 不可用，无法解析 FIT fallback: {exc}")
        return None

    class LenientProcessor(FitFileDataProcessor):
        def process_type_localtime_into_day(self, field_data):
            return

    try:
        fit_file = FitParseFile(str(file_path), data_processor=LenientProcessor())
        session_msg = None
        lap_msgs = []
        for message in fit_file.get_messages():
            if message.name == "session":
                session_msg = message
            elif message.name == "lap":
                lap_msgs.append(message)
    except Exception as exc:
        logger.error(f"fitparse fallback 解析失败 {file_path}: {exc}")
        return None

    start_time = _parse_fitparse_datetime(_fitparse_value(session_msg, "start_time")) if session_msg else None
    if not start_time and lap_msgs:
        start_time = _parse_fitparse_datetime(_fitparse_value(lap_msgs[0], "start_time"))
    total_distance = _safe_float(_fitparse_value(session_msg, "total_distance")) if session_msg else 0
    total_duration = _safe_float(
        _fitparse_value(session_msg, "total_elapsed_time") or _fitparse_value(session_msg, "total_timer_time")
    ) if session_msg else 0
    if not total_distance:
        total_distance = sum(_safe_float(_fitparse_value(lap, "total_distance")) for lap in lap_msgs)
    if not total_duration:
        total_duration = sum(_safe_float(_fitparse_value(lap, "total_elapsed_time")) for lap in lap_msgs)
    avg_speed = _safe_float(_fitparse_value(session_msg, "avg_speed") or _fitparse_value(session_msg, "enhanced_avg_speed")) if session_msg else 0
    avg_pace = 1000.0 / avg_speed if avg_speed > 0 else _calc_pace(total_distance, total_duration)
    activity_id = _generate_activity_id(file_path, start_time)
    sport_type = _get_sport_name(_fitparse_value(session_msg, "sport")) if session_msg else _infer_sport_from_filename(file_path.name)
    laps = [_parse_fitparse_lap(activity_id, index, lap) for index, lap in enumerate(lap_msgs)]
    activity = Activity(
        activity_id=activity_id,
        name=f"{sport_type.title()} {start_time.strftime('%Y-%m-%d %H:%M') if start_time else ''}",
        sport_type=sport_type,
        start_time=start_time or datetime.now(),
        distance_m=total_distance,
        duration_s=total_duration,
        moving_duration_s=_safe_float(_fitparse_value(session_msg, "total_timer_time")) if session_msg else total_duration,
        avg_pace_s_per_km=avg_pace,
        avg_hr=_safe_int(_fitparse_value(session_msg, "avg_heart_rate")) if session_msg else 0,
        max_hr=_safe_int(_fitparse_value(session_msg, "max_heart_rate")) if session_msg else 0,
        avg_cadence=_safe_int(_fitparse_value(session_msg, "avg_cadence")) if session_msg else 0,
        calories=_safe_int(_fitparse_value(session_msg, "total_calories")) if session_msg else 0,
        elevation_gain_m=_safe_float(_fitparse_value(session_msg, "total_ascent")) if session_msg else 0,
        source="local_fit",
        source_file=str(file_path),
        sync_status="synced",
        created_at=datetime.now(),
    )
    logger.info(f"fitparse fallback 解析成功: {file_path}, laps={len(laps)}")
    return activity, laps


def _parse_session(file_path: Path, session: SessionMessage) -> Activity:
    """
    从 session 消息解析活动数据

    Args:
        file_path: 文件路径
        session: session 消息

    Returns:
        Activity 对象
    """
    # 解析开始时间
    start_time = None
    if hasattr(session, 'start_time') and session.start_time:
        try:
            # fit-tool 的时间可能是 datetime 对象或时间戳
            if isinstance(session.start_time, datetime):
                start_time = session.start_time
            else:
                start_time = datetime.fromtimestamp(float(session.start_time), tz=timezone.utc)
        except Exception:
            pass

    # 解析距离（米）
    distance_m = _safe_float(getattr(session, 'total_distance', None))

    # 解析时长（秒）
    duration_s = _safe_float(getattr(session, 'total_elapsed_time', None))
    moving_duration_s = _safe_float(getattr(session, 'total_timer_time', None))
    if moving_duration_s <= 0:
        moving_duration_s = duration_s

    # 计算配速（秒/公里）
    avg_speed = _safe_float(getattr(session, 'avg_speed', None))
    if avg_speed > 0:
        # avg_speed 单位是 m/s，转换为 秒/公里
        avg_pace = 1000.0 / avg_speed
    else:
        avg_pace = _calc_pace(distance_m, duration_s)

    # 解析心率
    avg_hr = _safe_int(getattr(session, 'avg_heart_rate', None))
    max_hr = _safe_int(getattr(session, 'max_heart_rate', None))

    # 解析步频
    avg_cadence = _safe_int(getattr(session, 'avg_cadence', None))

    # 解析卡路里
    calories = _safe_int(getattr(session, 'total_calories', None))

    # 解析爬升
    elevation_gain_m = _safe_float(getattr(session, 'total_ascent', None))

    # 解析运动类型
    sport_value = getattr(session, 'sport', None)
    sport_type = _get_sport_name(sport_value)

    # 生成活动 ID
    activity_id = _generate_activity_id(file_path, start_time)

    # 活动名称
    name = f"{sport_type.title()} {start_time.strftime('%Y-%m-%d %H:%M') if start_time else ''}"

    return Activity(
        activity_id=activity_id,
        name=name,
        sport_type=sport_type,
        start_time=start_time or datetime.now(),
        distance_m=distance_m,
        duration_s=duration_s,
        moving_duration_s=moving_duration_s,
        avg_pace_s_per_km=avg_pace,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_cadence=avg_cadence,
        calories=calories,
        elevation_gain_m=elevation_gain_m,
        source="local_fit",
        source_file=str(file_path),
        sync_status="synced",
        created_at=datetime.now(),
    )


def _parse_lap(activity_id: str, lap_index: int, lap: LapMessage) -> Optional[LapData]:
    """
    从 lap 消息解析分圈数据

    Args:
        activity_id: 活动 ID
        lap_index: 圈序号
        lap: lap 消息

    Returns:
        LapData 对象
    """
    distance_m = _safe_float(getattr(lap, 'total_distance', None))
    duration_s = _safe_float(getattr(lap, 'total_elapsed_time', None))

    avg_speed = _safe_float(getattr(lap, 'avg_speed', None))
    if avg_speed > 0:
        avg_pace = 1000.0 / avg_speed
    else:
        avg_pace = _calc_pace(distance_m, duration_s)

    avg_hr = _safe_int(getattr(lap, 'avg_heart_rate', None))
    calories = _safe_int(getattr(lap, 'total_calories', None))

    return LapData(
        activity_id=activity_id,
        lap_index=lap_index,
        distance_m=distance_m,
        duration_s=duration_s,
        avg_pace_s_per_km=avg_pace,
        avg_hr=avg_hr,
        calories=calories,
    )


def _build_activity_from_laps(
    file_path: Path, laps: List[LapMessage]
) -> Optional[Tuple[Activity, List[LapData]]]:
    """
    当没有 session 数据时，从 lap 数据构建活动

    Args:
        file_path: 文件路径
        laps: lap 消息列表

    Returns:
        (Activity, List[LapData]) 元组
    """
    if not laps:
        return None

    # 汇总所有 lap 数据
    total_distance = 0.0
    total_duration = 0.0
    total_calories = 0
    max_hr = 0
    hr_sum = 0
    hr_count = 0
    start_time = None

    for lap in laps:
        total_distance += _safe_float(getattr(lap, 'total_distance', None))
        total_duration += _safe_float(getattr(lap, 'total_elapsed_time', None))
        total_calories += _safe_int(getattr(lap, 'total_calories', None))

        lap_max_hr = _safe_int(getattr(lap, 'max_heart_rate', None))
        if lap_max_hr > max_hr:
            max_hr = lap_max_hr

        lap_avg_hr = _safe_int(getattr(lap, 'avg_heart_rate', None))
        if lap_avg_hr > 0:
            hr_sum += lap_avg_hr
            hr_count += 1

        if start_time is None and hasattr(lap, 'start_time') and lap.start_time:
            try:
                if isinstance(lap.start_time, datetime):
                    start_time = lap.start_time
                else:
                    start_time = datetime.fromtimestamp(float(lap.start_time), tz=timezone.utc)
            except Exception:
                pass

    avg_hr = hr_sum // hr_count if hr_count > 0 else 0
    avg_pace = _calc_pace(total_distance, total_duration)

    activity_id = _generate_activity_id(file_path, start_time)

    # 从文件名推断运动类型
    sport_type = _infer_sport_from_filename(file_path.name)

    name = f"{sport_type.title()} {start_time.strftime('%Y-%m-%d %H:%M') if start_time else ''}"

    activity = Activity(
        activity_id=activity_id,
        name=name,
        sport_type=sport_type,
        start_time=start_time or datetime.now(),
        distance_m=total_distance,
        duration_s=total_duration,
        moving_duration_s=total_duration,
        avg_pace_s_per_km=avg_pace,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_cadence=0,
        calories=total_calories,
        elevation_gain_m=0.0,
        source="local_fit",
        source_file=str(file_path),
        sync_status="synced",
        created_at=datetime.now(),
    )

    lap_data_list = []
    for i, lap in enumerate(laps):
        lap_data = _parse_lap(activity_id, i, lap)
        if lap_data:
            lap_data_list.append(lap_data)

    return activity, lap_data_list


def _infer_sport_from_filename(filename: str) -> str:
    """
    从文件名推断运动类型

    Args:
        filename: 文件名

    Returns:
        运动类型字符串
    """
    filename_lower = filename.lower()
    if "run" in filename_lower:
        return "running"
    elif "ride" in filename_lower or "cycl" in filename_lower or "bike" in filename_lower:
        return "cycling"
    elif "walk" in filename_lower:
        return "walking"
    elif "swim" in filename_lower:
        return "swimming"
    elif "hik" in filename_lower:
        return "hiking"
    return "unknown"
