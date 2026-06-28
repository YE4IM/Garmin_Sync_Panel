"""
PiDesk JSON 导出模块
导出运动摘要数据供 PiDesk 桌面中枢读取
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.database import Database
from core.models import Activity
from utils.time_utils import (
    format_datetime,
    format_duration,
    format_pace,
    format_distance,
)

logger = logging.getLogger(__name__)


def export_pidesk_json(db: Database, output_path: str | Path) -> bool:
    """
    导出 PiDesk 格式的运动摘要 JSON

    Args:
        db: 数据库实例
        output_path: 输出文件路径

    Returns:
        是否成功
    """
    try:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 查询最近一次运动
        last_activity = db.get_last_activity()

        # 查询本周统计
        weekly_stats = db.get_weekly_stats()

        # 查询本月统计
        monthly_stats = db.get_monthly_stats()

        # 构建导出数据
        export_data = {
            "last_activity": _format_activity(last_activity) if last_activity else None,
            "weekly_stats": weekly_stats.to_dict(),
            "monthly_stats": monthly_stats.to_dict(),
            "last_sync_time": datetime.now().isoformat(),
            "sync_status": "success",
        }

        # 写入 JSON 文件
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        logger.info(f"PiDesk JSON 已导出: {output_path}")
        return True

    except Exception as e:
        logger.error(f"导出 PiDesk JSON 失败: {e}")
        return False


def _format_activity(activity: dict) -> dict:
    """
    格式化活动数据为 PiDesk 格式

    Args:
        activity: 活动字典

    Returns:
        格式化后的字典
    """
    distance_m = activity.get("distance_m", 0)
    duration_s = activity.get("duration_s", 0)
    avg_pace = activity.get("avg_pace_s_per_km", 0)

    return {
        "name": activity.get("name", ""),
        "sport_type": activity.get("sport_type", ""),
        "start_time": activity.get("start_time", ""),
        "distance_km": round(distance_m / 1000, 2) if distance_m else 0,
        "duration_min": round(duration_s / 60, 1) if duration_s else 0,
        "avg_pace": format_pace(avg_pace),
        "avg_hr": activity.get("avg_hr", 0),
        "max_hr": activity.get("max_hr", 0),
        "calories": activity.get("calories", 0),
        "elevation_gain_m": activity.get("elevation_gain_m", 0),
    }
