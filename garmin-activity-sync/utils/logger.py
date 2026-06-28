"""
日志配置模块
提供统一的日志配置，支持控制台和文件输出
"""
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logger(
    log_dir: str = "logs",
    log_level: int = logging.INFO,
    console_output: bool = True
) -> logging.Logger:
    """
    配置日志系统

    Args:
        log_dir: 日志文件目录
        log_level: 日志级别
        console_output: 是否输出到控制台

    Returns:
        配置好的 logger 实例
    """
    # 确保日志目录存在
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 获取根 logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 清除已有的 handler（避免重复添加）
    logger.handlers.clear()

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 文件 handler（按日期滚动）
    log_file = log_path / "sync.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 控制台 handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 logger

    Args:
        name: logger 名称

    Returns:
        logger 实例
    """
    return logging.getLogger(name)
