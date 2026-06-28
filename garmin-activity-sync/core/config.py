"""
配置管理模块
读取和验证 config.json 配置文件
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "garmin": {
        "email": "",
        "password": "",
        "domain": "CN"
    },
    "data_dir": "data",
    "log_dir": "logs",
    "fit_download_dir": "data/fit_files",
    "export_dir": "data/exports"
}


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: str = "config.json"):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self._config = None

    def load(self) -> dict:
        """
        加载配置文件

        Returns:
            配置字典

        Raises:
            FileNotFoundError: 配置文件不存在
            json.JSONDecodeError: 配置文件格式错误
        """
        if not self.config_path.exists():
            logger.error(f"配置文件不存在: {self.config_path}")
            raise FileNotFoundError(
                f"配置文件不存在: {self.config_path}\n"
                f"请复制 config.example.json 为 config.json 并填入您的配置"
            )

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info(f"已加载配置文件: {self.config_path}")
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            raise

        # 合并默认配置（填充缺失字段）
        self._config = self._merge_defaults(self._config, DEFAULT_CONFIG)
        return self._config

    def get(self, key: str, default=None):
        """
        获取配置项

        Args:
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        if self._config is None:
            self.load()
        return self._config.get(key, default)

    def get_garmin_config(self) -> dict:
        """
        获取 Garmin 配置

        Returns:
            Garmin 配置字典
        """
        if self._config is None:
            self.load()
        return self._config.get("garmin", {})

    def validate(self) -> bool:
        """
        验证配置是否完整

        Returns:
            配置是否有效
        """
        if self._config is None:
            self.load()

        garmin = self._config.get("garmin", {})
        email = garmin.get("email", "")
        password = garmin.get("password", "")

        if not email or email == "your_garmin_email@example.com":
            logger.error("Garmin 邮箱未配置或使用了示例值")
            return False

        if not password or password == "your_garmin_password":
            logger.error("Garmin 密码未配置或使用了示例值")
            return False

        return True

    def _merge_defaults(self, config: dict, defaults: dict) -> dict:
        """
        合并默认配置（填充缺失字段）

        Args:
            config: 用户配置
            defaults: 默认配置

        Returns:
            合并后的配置
        """
        result = defaults.copy()
        for key, value in config.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_defaults(value, result[key])
            else:
                result[key] = value
        return result


def load_config(config_path: str = "config.json") -> dict:
    """
    快捷函数：加载配置

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典
    """
    manager = ConfigManager(config_path)
    return manager.load()
