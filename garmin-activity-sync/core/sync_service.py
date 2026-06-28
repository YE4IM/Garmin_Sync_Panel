"""
同步服务编排模块
协调本地 FIT 导入和 Garmin Connect 同步流程
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.config import ConfigManager
from core.database import Database
from core.exporter import export_pidesk_json
from core.models import SyncResult
from utils.path_utils import (
    get_db_path,
    get_fit_download_dir,
    get_export_dir,
    get_session_dir,
)

logger = logging.getLogger(__name__)


def sync_from_local(
    directory: str | Path,
    config: dict,
    export: bool = False
) -> SyncResult:
    """
    从本地目录导入 FIT 文件

    Args:
        directory: FIT 文件目录
        config: 配置字典
        export: 是否同步后自动导出 JSON

    Returns:
        同步结果
    """
    from local_fit.importer import import_from_directory

    db_path = get_db_path(config)
    db = Database(db_path)
    db.init_db()

    try:
        logger.info(f"开始从本地导入: {directory}")
        result = import_from_directory(directory, db)

        if export and result.new_activities > 0:
            export_path = get_export_dir(config) / "pidesk_activity_summary.json"
            export_pidesk_json(db, export_path)
            logger.info("已自动导出 PiDesk JSON")

        return result

    finally:
        db.close()


def sync_from_garmin(
    days: int,
    config: dict,
    export: bool = False
) -> SyncResult:
    """
    从 Garmin Connect 同步活动

    Args:
        days: 获取最近多少天的活动
        config: 配置字典
        export: 是否同步后自动导出 JSON

    Returns:
        同步结果
    """
    from garmin.client import GarminConnectClient
    from garmin.activity import fetch_and_save_activities

    # 验证配置
    garmin_config = config.get("garmin", {})
    email = garmin_config.get("email", "")
    password = garmin_config.get("password", "")
    domain = garmin_config.get("domain", "CN")

    if not email or not password:
        result = SyncResult(source="garmin_connect")
        result.error_message = "Garmin 账号未配置"
        logger.error(result.error_message)
        return result

    # 初始化数据库
    db_path = get_db_path(config)
    db = Database(db_path)
    db.init_db()

    try:
        # 登录 Garmin Connect
        session_dir = get_session_dir(email, config)
        client = GarminConnectClient(
            email=email,
            password=password,
            domain=domain,
            session_dir=str(session_dir.parent)
        )

        logger.info("正在登录 Garmin Connect...")
        if not client.login():
            result = SyncResult(source="garmin_connect")
            result.error_message = "Garmin Connect 登录失败"
            logger.error(result.error_message)
            return result

        # 获取 FIT 文件保存目录
        fit_dir = get_fit_download_dir(config)

        # 获取并保存活动
        logger.info(f"开始同步最近 {days} 天的活动...")
        result = fetch_and_save_activities(client, days, db, fit_dir)

        # 自动导出
        if export:
            export_path = get_export_dir(config) / "pidesk_activity_summary.json"
            export_pidesk_json(db, export_path)
            logger.info("已自动导出 PiDesk JSON")

        return result

    finally:
        db.close()


def export_json(config: dict) -> bool:
    """
    导出 PiDesk JSON

    Args:
        config: 配置字典

    Returns:
        是否成功
    """
    db_path = get_db_path(config)
    db = Database(db_path)

    try:
        export_path = get_export_dir(config) / "pidesk_activity_summary.json"
        return export_pidesk_json(db, export_path)
    finally:
        db.close()


def get_status(config: dict) -> dict:
    """
    获取同步状态

    Args:
        config: 配置字典

    Returns:
        状态字典
    """
    db_path = get_db_path(config)
    db = Database(db_path)

    try:
        total = db.get_activity_count()
        last = db.get_last_activity()
        weekly = db.get_weekly_stats()
        monthly = db.get_monthly_stats()
        sport_stats = db.get_sport_type_stats()

        return {
            "total_activities": total,
            "last_activity": last,
            "weekly_stats": weekly.to_dict(),
            "monthly_stats": monthly.to_dict(),
            "sport_type_stats": sport_stats,
            "db_path": str(db_path),
        }
    finally:
        db.close()


def sync_health_data(
    days: int,
    config: dict,
    data_types: list[str] = None
) -> dict:
    """
    从 Garmin Connect 同步健康数据

    Args:
        days: 获取最近多少天的数据
        config: 配置字典
        data_types: 要同步的数据类型列表，可选值：
                    ['steps', 'heart_rate', 'hrv', 'sleep', 'weight', 'spo2']
                    默认同步所有类型

    Returns:
        同步结果字典
    """
    from garmin.client import GarminConnectClient
    from garmin.health import (
        parse_daily_steps,
        parse_daily_steps_from_summary,
        parse_heart_rate_data,
        parse_hrv_data,
        parse_sleep_data,
        parse_weight_data,
        parse_spo2_data,
    )

    # 默认同步所有类型
    if data_types is None:
        data_types = ['steps', 'heart_rate', 'hrv', 'sleep', 'weight', 'spo2']

    # 验证配置
    garmin_config = config.get("garmin", {})
    email = garmin_config.get("email", "")
    password = garmin_config.get("password", "")
    domain = garmin_config.get("domain", "CN")

    if not email or not password:
        logger.error("Garmin 账号未配置")
        return {"success": False, "error": "Garmin 账号未配置", "synced": {}}

    # 初始化数据库
    db_path = get_db_path(config)
    db = Database(db_path)
    db.init_db()

    try:
        # 登录 Garmin Connect
        session_dir = get_session_dir(email, config)
        client = GarminConnectClient(
            email=email,
            password=password,
            domain=domain,
            session_dir=str(session_dir.parent)
        )

        logger.info("正在登录 Garmin Connect...")
        if not client.login():
            logger.error("Garmin Connect 登录失败")
            return {"success": False, "error": "Garmin Connect 登录失败", "synced": {}}

        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        synced = {}
        errors = []

        # 同步步数
        if 'steps' in data_types:
            try:
                logger.info(f"同步步数数据: {start_str} ~ {end_str}")
                steps_data = client.get_daily_steps(start_str, end_str)
                if steps_data:
                    steps_list = parse_daily_steps(steps_data)
                    count = db.insert_daily_steps_batch(steps_list)
                    synced['steps'] = count
                    logger.info(f"同步步数完成: {count} 条记录")
                else:
                    logger.warning("步数区间接口无数据，尝试逐日每日汇总接口")
                    steps_count = 0
                    current = start_date
                    while current <= end_date:
                        cdate = current.strftime("%Y-%m-%d")
                        summary = client.get_daily_summary(cdate)
                        steps = parse_daily_steps_from_summary(summary or {}, cdate)
                        if steps and db.insert_daily_steps(steps):
                            steps_count += 1
                        current += timedelta(days=1)
                    synced['steps'] = steps_count
                    logger.info(f"每日汇总步数同步完成: {steps_count} 条记录")
            except Exception as e:
                errors.append(f"步数同步失败: {e}")
                synced['steps'] = 0

        # 同步心率（逐天获取）
        if 'heart_rate' in data_types:
            try:
                logger.info(f"同步心率数据: {days} 天")
                hr_count = 0
                current = start_date
                while current <= end_date:
                    cdate = current.strftime("%Y-%m-%d")
                    hr_data = client.get_heart_rates(cdate)
                    if hr_data:
                        hr = parse_heart_rate_data(hr_data, cdate)
                        if hr and db.insert_heart_rate(hr):
                            hr_count += 1
                    current += timedelta(days=1)
                synced['heart_rate'] = hr_count
                logger.info(f"同步心率完成: {hr_count} 条记录")
            except Exception as e:
                errors.append(f"心率同步失败: {e}")
                synced['heart_rate'] = 0

        # 同步HRV（逐天获取）
        if 'hrv' in data_types:
            try:
                logger.info(f"同步HRV数据: {days} 天")
                hrv_count = 0
                current = start_date
                while current <= end_date:
                    cdate = current.strftime("%Y-%m-%d")
                    hrv_data = client.get_hrv_data(cdate)
                    if hrv_data:
                        hrv = parse_hrv_data(hrv_data, cdate)
                        if hrv and db.insert_hrv(hrv):
                            hrv_count += 1
                    current += timedelta(days=1)
                synced['hrv'] = hrv_count
                logger.info(f"同步HRV完成: {hrv_count} 条记录")
            except Exception as e:
                errors.append(f"HRV同步失败: {e}")
                synced['hrv'] = 0

        # 同步睡眠（逐天获取）
        if 'sleep' in data_types:
            try:
                logger.info(f"同步睡眠数据: {days} 天")
                sleep_count = 0
                current = start_date
                while current <= end_date:
                    cdate = current.strftime("%Y-%m-%d")
                    sleep_data = client.get_sleep_data(cdate)
                    if sleep_data:
                        sleep = parse_sleep_data(sleep_data, cdate)
                        if sleep and db.insert_sleep(sleep):
                            sleep_count += 1
                    current += timedelta(days=1)
                synced['sleep'] = sleep_count
                logger.info(f"同步睡眠完成: {sleep_count} 条记录")
            except Exception as e:
                errors.append(f"睡眠同步失败: {e}")
                synced['sleep'] = 0

        # 同步体重
        if 'weight' in data_types:
            try:
                logger.info(f"同步体重数据: {start_str} ~ {end_str}")
                weight_data = client.get_body_composition(start_str, end_str)
                if weight_data:
                    weight_list = parse_weight_data(weight_data)
                    weight_count = 0
                    for w in weight_list:
                        if db.insert_weight(w):
                            weight_count += 1
                    synced['weight'] = weight_count
                    logger.info(f"同步体重完成: {weight_count} 条记录")
                else:
                    synced['weight'] = 0
            except Exception as e:
                errors.append(f"体重同步失败: {e}")
                synced['weight'] = 0

        # 同步SpO2（逐天获取）
        if 'spo2' in data_types:
            try:
                logger.info(f"同步SpO2数据: {days} 天")
                spo2_count = 0
                current = start_date
                while current <= end_date:
                    cdate = current.strftime("%Y-%m-%d")
                    spo2_data = client.get_spo2_data(cdate)
                    if spo2_data:
                        spo2 = parse_spo2_data(spo2_data, cdate)
                        if spo2 and db.insert_spo2(spo2):
                            spo2_count += 1
                    current += timedelta(days=1)
                synced['spo2'] = spo2_count
                logger.info(f"同步SpO2完成: {spo2_count} 条记录")
            except Exception as e:
                errors.append(f"SpO2同步失败: {e}")
                synced['spo2'] = 0

        success = len(errors) == 0
        result = {
            "success": success,
            "synced": synced,
            "errors": errors if errors else None
        }

        if success:
            logger.info(f"健康数据同步完成: {synced}")
        else:
            logger.warning(f"健康数据同步部分失败: {errors}")

        return result

    finally:
        db.close()


def get_health_status(config: dict) -> dict:
    """
    获取健康数据状态

    Args:
        config: 配置字典

    Returns:
        健康数据状态字典
    """
    db_path = get_db_path(config)
    db = Database(db_path)

    try:
        latest = db.get_latest_health_data()
        counts = db.get_health_data_count()

        return {
            "latest": latest,
            "counts": counts,
            "db_path": str(db_path),
        }
    finally:
        db.close()
