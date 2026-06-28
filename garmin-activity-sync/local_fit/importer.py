"""
本地 FIT 文件导入模块
扫描目录中的 FIT 文件并导入到 SQLite 数据库
"""
import logging
from pathlib import Path
from typing import List

from core.database import Database
from core.models import SyncResult
from garmin.fit_parser import parse_fit_file

logger = logging.getLogger(__name__)


def scan_fit_files(directory: str | Path) -> List[Path]:
    """
    扫描目录下的所有 FIT 文件

    Args:
        directory: 目录路径

    Returns:
        FIT 文件路径列表
    """
    directory = Path(directory)
    if not directory.exists():
        logger.error(f"目录不存在: {directory}")
        return []

    # 支持 .fit 和 .FIT 两种后缀
    fit_files = []
    for ext in ["*.fit", "*.FIT", "*.Fit"]:
        fit_files.extend(directory.glob(ext))

    # 去重并排序
    fit_files = sorted(set(fit_files), key=lambda f: f.name)
    logger.info(f"在 {directory} 中找到 {len(fit_files)} 个 FIT 文件")
    return fit_files


def import_from_directory(
    directory: str | Path,
    db: Database
) -> SyncResult:
    """
    从目录导入 FIT 文件到数据库

    Args:
        directory: FIT 文件目录
        db: 数据库实例

    Returns:
        同步结果
    """
    result = SyncResult(source="local_fit")

    # 扫描文件
    fit_files = scan_fit_files(directory)
    result.total_files = len(fit_files)

    if not fit_files:
        logger.warning("未找到 FIT 文件")
        return result

    # 逐个解析并导入
    for fit_file in fit_files:
        try:
            parsed = parse_fit_file(fit_file)
            if parsed is None:
                logger.warning(f"无法解析文件: {fit_file.name}")
                result.failed += 1
                continue

            activity, laps = parsed
            is_new = db.insert_activity(activity, laps)

            if is_new:
                result.new_activities += 1
                logger.info(f"导入成功: {fit_file.name} -> {activity.name}")
            else:
                result.skipped += 1
                logger.debug(f"已存在，跳过: {fit_file.name}")

        except Exception as e:
            logger.error(f"导入失败 {fit_file.name}: {e}")
            result.failed += 1

    logger.info(
        f"导入完成: 总计 {result.total_files} 个文件, "
        f"新增 {result.new_activities}, "
        f"跳过 {result.skipped}, "
        f"失败 {result.failed}"
    )
    return result
