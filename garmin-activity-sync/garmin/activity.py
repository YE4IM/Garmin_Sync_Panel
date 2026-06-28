"""
Garmin 活动获取模块
从 Garmin Connect 获取活动列表、下载 FIT 文件并导入数据库
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from core.database import Database
from core.models import SyncResult
from garmin.client import GarminConnectClient
from garmin.fit_parser import parse_fit_file
from garmin.tcx_parser import parse_tcx_laps

logger = logging.getLogger(__name__)


def fetch_and_save_activities(
    client: GarminConnectClient,
    days: int,
    db: Database,
    fit_dir: Path
) -> SyncResult:
    """
    从 Garmin Connect 获取活动并保存到数据库

    Args:
        client: Garmin Connect 客户端
        days: 获取最近多少天的活动
        db: 数据库实例
        fit_dir: FIT 文件保存目录

    Returns:
        同步结果
    """
    result = SyncResult(source="garmin_connect")

    # 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    logger.info(f"从 Garmin Connect 获取活动: {start_str} 至 {end_str}")

    # 获取活动列表
    try:
        activities = client.get_activities_by_date(start_str, end_str)
    except Exception as e:
        logger.error(f"获取活动列表失败: {e}")
        result.error_message = str(e)
        return result

    result.total_files = len(activities)
    logger.info(f"获取到 {len(activities)} 个活动")

    if not activities:
        return result

    # 逐个处理活动
    for activity_data in activities:
        try:
            activity_id = str(activity_data.get("activityId", ""))

            # 检查是否已存在
            existing = db.get_activity_by_id(activity_id)
            if existing:
                if not db.get_laps_by_activity_id(activity_id):
                    repaired = _repair_missing_laps(client, activity_data, existing, db, fit_dir)
                    if repaired:
                        logger.info(f"已修复缺失分段: {activity_id}, laps={repaired}")
                result.skipped += 1
                logger.debug(f"活动已存在，跳过: {activity_id}")
                continue

            # 解析活动数据
            activity = _parse_garmin_activity(activity_data)
            if activity is None:
                result.failed += 1
                continue

            # 下载 FIT 文件
            fit_path = fit_dir / f"{activity_id}.fit"
            if not fit_path.exists():
                success = client.download_activity_fit(
                    int(activity_id), fit_path
                )
                if not success:
                    logger.warning(f"无法下载 FIT 文件，使用 API 数据: {activity_id}")

            laps = _load_activity_laps(client, activity, fit_path, fit_dir)

            # 保存到数据库
            is_new = db.insert_activity(activity, laps)
            if is_new:
                result.new_activities += 1
                logger.info(f"导入成功: {activity.name}")
            else:
                result.skipped += 1

        except Exception as e:
            logger.error(f"处理活动失败: {e}")
            result.failed += 1

    logger.info(
        f"Garmin Connect 同步完成: "
        f"总计 {result.total_files}, "
        f"新增 {result.new_activities}, "
        f"跳过 {result.skipped}, "
        f"失败 {result.failed}"
    )
    return result


def _load_activity_laps(
    client: GarminConnectClient,
    activity,
    fit_path: Path,
    fit_dir: Path,
) -> List:
    activity_id = str(activity.activity_id)
    laps = _parse_fit_laps(fit_path, activity_id) if fit_path.exists() else []
    if laps:
        return laps

    # 自动重试：已有 FIT 可能是旧解析器无法处理或下载不完整，强制重下再解析一次。
    try:
        fit_path.unlink(missing_ok=True)
    except Exception:
        pass
    if client.download_activity_fit(int(activity_id), fit_path):
        laps = _parse_fit_laps(fit_path, activity_id)
        if laps:
            return laps

    tcx_path = fit_dir.parent / "tcx_files" / f"{activity_id}.tcx"
    if client.download_activity_tcx(int(activity_id), tcx_path):
        laps = parse_tcx_laps(tcx_path, activity)
        if laps:
            for lap in laps:
                lap.activity_id = activity_id
            return laps

    return _estimated_laps(activity)


def _parse_fit_laps(fit_path: Path, activity_id: str) -> List:
    parsed = parse_fit_file(fit_path)
    if not parsed:
        return []
    _, laps = parsed
    for lap in laps:
        lap.activity_id = activity_id
    return laps


def _estimated_laps(activity) -> List:
    from core.models import LapData

    distance_m = float(activity.distance_m or 0)
    duration_s = float(activity.duration_s or 0)
    calories = int(activity.calories or 0)
    if distance_m <= 0 or duration_s <= 0:
        return []
    laps = []
    remaining = distance_m
    index = 0
    while remaining > 0:
        lap_distance = min(1000.0, remaining)
        lap_duration = duration_s * (lap_distance / distance_m)
        lap_calories = int(calories * (lap_distance / distance_m)) if calories else 0
        laps.append(LapData(
            activity_id=str(activity.activity_id),
            lap_index=index,
            distance_m=lap_distance,
            duration_s=lap_duration,
            avg_pace_s_per_km=lap_duration / (lap_distance / 1000.0),
            avg_hr=int(activity.avg_hr or 0),
            calories=lap_calories,
        ))
        remaining -= lap_distance
        index += 1
    logger.warning(f"使用活动汇总估算分段: {activity.activity_id}, laps={len(laps)}")
    return laps


def _repair_missing_laps(
    client: GarminConnectClient,
    activity_data: dict,
    existing: dict,
    db: Database,
    fit_dir: Path,
) -> int:
    activity = _parse_garmin_activity(activity_data)
    if activity is None:
        return 0
    activity_id = str(existing.get("activity_id") or activity.activity_id)
    activity.activity_id = activity_id
    fit_path = fit_dir / f"{activity_id}.fit"
    if not fit_path.exists():
        client.download_activity_fit(int(activity_id), fit_path)
    laps = _load_activity_laps(client, activity, fit_path, fit_dir)
    if not laps:
        return 0
    return db.replace_laps(activity_id, laps)


def _parse_garmin_activity(data: dict):
    """
    从 Garmin Connect API 响应解析活动数据

    Args:
        data: Garmin Connect API 返回的活动数据

    Returns:
        Activity 对象，解析失败返回 None
    """
    from core.models import Activity

    try:
        activity_id = str(data.get("activityId", ""))
        if not activity_id:
            return None

        # 活动名称
        name = data.get("activityName", "")

        # 运动类型
        sport_type = data.get("activityType", {}).get("typeKey", "unknown")
        if isinstance(sport_type, str):
            sport_type = sport_type.lower()

        # 开始时间
        start_time_str = data.get("startTimeLocal", "")
        start_time = None
        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str)
            except Exception:
                start_time = datetime.now()
        else:
            start_time = datetime.now()

        # 距离（米）
        distance_m = float(data.get("distance", 0) or 0)

        # 时长（秒）
        duration_s = float(data.get("duration", 0) or 0)
        moving_duration_s = float(data.get("movingDuration", 0) or 0)
        if moving_duration_s <= 0:
            moving_duration_s = duration_s

        # 配速（秒/公里）
        avg_speed = float(data.get("averageSpeed", 0) or 0)
        if avg_speed > 0:
            avg_pace = 1000.0 / avg_speed
        elif distance_m > 0 and duration_s > 0:
            avg_pace = duration_s / (distance_m / 1000)
        else:
            avg_pace = 0.0

        # 心率
        avg_hr = int(data.get("averageHR", 0) or 0)
        max_hr = int(data.get("maxHR", 0) or 0)

        # 步频
        avg_cadence = int(data.get("averageRunningCadenceInStepsPerMinute", 0) or 0)

        # 卡路里
        calories = int(data.get("calories", 0) or 0)

        # 爬升
        elevation_gain_m = float(data.get("elevationGain", 0) or 0)

        return Activity(
            activity_id=activity_id,
            name=name,
            sport_type=sport_type,
            start_time=start_time,
            distance_m=distance_m,
            duration_s=duration_s,
            moving_duration_s=moving_duration_s,
            avg_pace_s_per_km=avg_pace,
            avg_hr=avg_hr,
            max_hr=max_hr,
            avg_cadence=avg_cadence,
            calories=calories,
            elevation_gain_m=elevation_gain_m,
            source="garmin_connect",
            source_file="",
            sync_status="synced",
            created_at=datetime.now(),
        )

    except Exception as e:
        logger.error(f"解析 Garmin 活动数据失败: {e}")
        return None
