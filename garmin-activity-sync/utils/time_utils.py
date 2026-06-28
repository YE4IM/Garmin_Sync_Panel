"""
时间处理工具模块
提供时间格式化、时区转换等功能
"""
from datetime import datetime, timezone, timedelta


# 中国时区
CHINA_TZ = timezone(timedelta(hours=8))


def now_china() -> datetime:
    """获取当前中国时间"""
    return datetime.now(CHINA_TZ)


def now_utc() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


def format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化日期时间

    Args:
        dt: 日期时间对象
        fmt: 格式化字符串

    Returns:
        格式化后的字符串
    """
    if dt is None:
        return ""
    return dt.strftime(fmt)


def parse_datetime(dt_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    解析日期时间字符串

    Args:
        dt_str: 日期时间字符串
        fmt: 格式化字符串

    Returns:
        datetime 对象
    """
    if not dt_str:
        return None
    return datetime.strptime(dt_str, fmt)


def to_isoformat(dt: datetime) -> str:
    """
    转换为 ISO 格式字符串

    Args:
        dt: 日期时间对象

    Returns:
        ISO 格式字符串
    """
    if dt is None:
        return ""
    return dt.isoformat()


def format_duration(seconds: float) -> str:
    """
    格式化时长

    Args:
        seconds: 秒数

    Returns:
        格式化后的时长字符串，如 "1:23:45" 或 "23:45"
    """
    if seconds is None or seconds <= 0:
        return "0:00"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(seconds_per_km: float) -> str:
    """
    格式化配速

    Args:
        seconds_per_km: 每公里秒数

    Returns:
        格式化后的配速字符串，如 "5:27"
    """
    if seconds_per_km is None or seconds_per_km <= 0:
        return "0:00"

    minutes = int(seconds_per_km // 60)
    seconds = int(seconds_per_km % 60)
    return f"{minutes}:{seconds:02d}"


def format_distance(meters: float) -> str:
    """
    格式化距离

    Args:
        meters: 米数

    Returns:
        格式化后的距离字符串，如 "5.23 km"
    """
    if meters is None or meters <= 0:
        return "0.00 km"

    km = meters / 1000
    return f"{km:.2f} km"
