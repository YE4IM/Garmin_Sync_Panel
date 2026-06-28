"""
路径工具模块
提供路径处理和目录创建功能
"""
from pathlib import Path
import os


def get_project_root() -> Path:
    """
    获取项目根目录

    Returns:
        项目根目录路径
    """
    # 从当前文件向上追溯到项目根目录
    return Path(__file__).parent.parent


def ensure_dir(path: str | Path) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        path: 目录路径

    Returns:
        目录路径对象
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_data_dir(config: dict = None) -> Path:
    """
    获取数据目录路径

    Args:
        config: 配置字典，可选

    Returns:
        数据目录路径
    """
    root = get_project_root()
    data_dir = config.get("data_dir", "data") if config else "data"
    return ensure_dir(root / data_dir)


def get_log_dir(config: dict = None) -> Path:
    """
    获取日志目录路径

    Args:
        config: 配置字典，可选

    Returns:
        日志目录路径
    """
    root = get_project_root()
    log_dir = config.get("log_dir", "logs") if config else "logs"
    return ensure_dir(root / log_dir)


def get_fit_download_dir(config: dict = None) -> Path:
    """
    获取 FIT 文件下载目录路径

    Args:
        config: 配置字典，可选

    Returns:
        FIT 文件下载目录路径
    """
    root = get_project_root()
    fit_dir = config.get("fit_download_dir", "data/fit_files") if config else "data/fit_files"
    return ensure_dir(root / fit_dir)


def get_export_dir(config: dict = None) -> Path:
    """
    获取导出目录路径

    Args:
        config: 配置字典，可选

    Returns:
        导出目录路径
    """
    root = get_project_root()
    export_dir = config.get("export_dir", "data/exports") if config else "data/exports"
    return ensure_dir(root / export_dir)


def get_db_path(config: dict = None) -> Path:
    """
    获取数据库文件路径

    Args:
        config: 配置字典，可选

    Returns:
        数据库文件路径
    """
    data_dir = get_data_dir(config)
    return data_dir / "garmin_activity.db"


def get_session_dir(email: str, config: dict = None) -> Path:
    """
    获取 Garmin session 目录路径

    Args:
        email: Garmin 邮箱
        config: 配置字典，可选

    Returns:
        session 目录路径
    """
    data_dir = get_data_dir(config)
    session_dir = data_dir / ".garth" / email
    return ensure_dir(session_dir)
