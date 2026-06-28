"""
数据模型定义
定义运动活动、分圈数据等数据结构
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Activity:
    """运动活动数据模型"""
    activity_id: str               # Garmin 活动 ID 或本地文件哈希
    name: str                      # 活动名称
    sport_type: str                # 运动类型（running, cycling, walking 等）
    start_time: datetime           # 开始时间
    distance_m: float = 0.0        # 距离（米）
    duration_s: float = 0.0        # 总时长（秒）
    moving_duration_s: float = 0.0 # 移动时长（秒）
    avg_pace_s_per_km: float = 0.0 # 平均配速（秒/公里）
    avg_hr: int = 0                # 平均心率
    max_hr: int = 0                # 最大心率
    avg_cadence: int = 0           # 平均步频
    calories: int = 0              # 卡路里
    elevation_gain_m: float = 0.0  # 爬升（米）
    source: str = "local_fit"      # 数据来源：local_fit / garmin_connect
    source_file: str = ""          # 原始 FIT 文件路径
    sync_status: str = "synced"    # 同步状态
    created_at: Optional[datetime] = None  # 记录创建时间

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "activity_id": self.activity_id,
            "name": self.name,
            "sport_type": self.sport_type,
            "start_time": self.start_time.isoformat() if self.start_time else "",
            "distance_m": self.distance_m,
            "duration_s": self.duration_s,
            "moving_duration_s": self.moving_duration_s,
            "avg_pace_s_per_km": self.avg_pace_s_per_km,
            "avg_hr": self.avg_hr,
            "max_hr": self.max_hr,
            "avg_cadence": self.avg_cadence,
            "calories": self.calories,
            "elevation_gain_m": self.elevation_gain_m,
            "source": self.source,
            "source_file": self.source_file,
            "sync_status": self.sync_status,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class LapData:
    """分圈数据模型"""
    activity_id: str               # 所属活动 ID
    lap_index: int                 # 圈序号
    distance_m: float = 0.0        # 距离（米）
    duration_s: float = 0.0        # 时长（秒）
    avg_pace_s_per_km: float = 0.0 # 平均配速（秒/公里）
    avg_hr: int = 0                # 平均心率
    calories: int = 0              # 卡路里

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "activity_id": self.activity_id,
            "lap_index": self.lap_index,
            "distance_m": self.distance_m,
            "duration_s": self.duration_s,
            "avg_pace_s_per_km": self.avg_pace_s_per_km,
            "avg_hr": self.avg_hr,
            "calories": self.calories,
        }


@dataclass
class WeeklyStats:
    """本周运动统计"""
    total_activities: int = 0      # 活动次数
    total_distance_m: float = 0.0  # 总距离（米）
    total_duration_s: float = 0.0  # 总时长（秒）
    total_calories: int = 0        # 总卡路里

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_activities": self.total_activities,
            "total_distance_km": round(self.total_distance_m / 1000, 2),
            "total_duration_min": round(self.total_duration_s / 60, 1),
            "total_calories": self.total_calories,
        }


@dataclass
class MonthlyStats:
    """本月运动统计"""
    total_activities: int = 0      # 活动次数
    total_distance_m: float = 0.0  # 总距离（米）
    total_duration_s: float = 0.0  # 总时长（秒）
    total_calories: int = 0        # 总卡路里

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_activities": self.total_activities,
            "total_distance_km": round(self.total_distance_m / 1000, 2),
            "total_duration_min": round(self.total_duration_s / 60, 1),
            "total_calories": self.total_calories,
        }


@dataclass
class SyncResult:
    """同步结果"""
    source: str                    # 数据来源
    total_files: int = 0           # 总文件数
    new_activities: int = 0        # 新增活动数
    skipped: int = 0               # 跳过（已存在）数
    failed: int = 0                # 失败数
    error_message: Optional[str] = None  # 错误信息

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "source": self.source,
            "total_files": self.total_files,
            "new_activities": self.new_activities,
            "skipped": self.skipped,
            "failed": self.failed,
            "error_message": self.error_message,
        }


# ==================== 健康数据模型 ====================

@dataclass
class DailySteps:
    """每日步数数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    steps: int = 0                 # 步数
    distance_m: float = 0.0        # 距离（米）
    calories: int = 0              # 活动卡路里
    floors_climbed: int = 0        # 爬楼层数
    source: str = "garmin_connect" # 数据来源
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "steps": self.steps,
            "distance_m": self.distance_m,
            "calories": self.calories,
            "floors_climbed": self.floors_climbed,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class HeartRateData:
    """心率数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    resting_hr: int = 0            # 静息心率
    max_hr: int = 0                # 最大心率
    min_hr: int = 0                # 最小心率
    avg_hr: int = 0                # 平均心率
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "resting_hr": self.resting_hr,
            "max_hr": self.max_hr,
            "min_hr": self.min_hr,
            "avg_hr": self.avg_hr,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class HRVData:
    """HRV（心率变异性）数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    weekly_avg: float = 0.0        # 7天平均HRV（ms）
    last_night_avg: float = 0.0    # 昨晚平均HRV（ms）
    last_night_5min_high: float = 0.0  # 昨晚5分钟最高HRV（ms）
    status: str = ""               # HRV状态（balanced, unbalanced, poor, low）
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "weekly_avg": self.weekly_avg,
            "last_night_avg": self.last_night_avg,
            "last_night_5min_high": self.last_night_5min_high,
            "status": self.status,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class SleepData:
    """睡眠数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    sleep_start: Optional[datetime] = None  # 入睡时间
    sleep_end: Optional[datetime] = None    # 醒来时间
    total_sleep_s: int = 0         # 总睡眠时长（秒）
    deep_sleep_s: int = 0          # 深睡时长（秒）
    light_sleep_s: int = 0         # 浅睡时长（秒）
    rem_sleep_s: int = 0           # REM睡眠时长（秒）
    awake_s: int = 0               # 清醒时长（秒）
    sleep_score: int = 0           # 睡眠得分（0-100）
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "sleep_start": self.sleep_start.isoformat() if self.sleep_start else "",
            "sleep_end": self.sleep_end.isoformat() if self.sleep_end else "",
            "total_sleep_s": self.total_sleep_s,
            "deep_sleep_s": self.deep_sleep_s,
            "light_sleep_s": self.light_sleep_s,
            "rem_sleep_s": self.rem_sleep_s,
            "awake_s": self.awake_s,
            "sleep_score": self.sleep_score,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class WeightData:
    """体重数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    weight_kg: float = 0.0         # 体重（kg）
    bmi: float = 0.0               # BMI
    body_fat_pct: float = 0.0      # 体脂率（%）
    muscle_mass_kg: float = 0.0    # 肌肉量（kg）
    bone_mass_kg: float = 0.0      # 骨量（kg）
    body_water_pct: float = 0.0    # 身体水分率（%）
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "weight_kg": self.weight_kg,
            "bmi": self.bmi,
            "body_fat_pct": self.body_fat_pct,
            "muscle_mass_kg": self.muscle_mass_kg,
            "bone_mass_kg": self.bone_mass_kg,
            "body_water_pct": self.body_water_pct,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class SpO2Data:
    """SpO2（血氧饱和度）数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    avg_spo2: float = 0.0          # 平均血氧（%）
    min_spo2: float = 0.0          # 最低血氧（%）
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "avg_spo2": self.avg_spo2,
            "min_spo2": self.min_spo2,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }
