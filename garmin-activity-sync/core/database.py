"""
SQLite 数据库操作模块
提供运动数据的存储、查询和统计功能
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .models import (
    Activity, LapData, WeeklyStats, MonthlyStats,
    DailySteps, HeartRateData, HRVData, SleepData, WeightData, SpO2Data
)

logger = logging.getLogger(__name__)

# 建表 SQL
CREATE_ACTIVITIES_TABLE = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    sport_type TEXT DEFAULT '',
    start_time TEXT DEFAULT '',
    distance_m REAL DEFAULT 0,
    duration_s REAL DEFAULT 0,
    moving_duration_s REAL DEFAULT 0,
    avg_pace_s_per_km REAL DEFAULT 0,
    avg_hr INTEGER DEFAULT 0,
    max_hr INTEGER DEFAULT 0,
    avg_cadence INTEGER DEFAULT 0,
    calories INTEGER DEFAULT 0,
    elevation_gain_m REAL DEFAULT 0,
    source TEXT DEFAULT 'local_fit',
    source_file TEXT DEFAULT '',
    sync_status TEXT DEFAULT 'synced',
    created_at TEXT DEFAULT ''
);
"""

CREATE_LAPS_TABLE = """
CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL,
    lap_index INTEGER DEFAULT 0,
    distance_m REAL DEFAULT 0,
    duration_s REAL DEFAULT 0,
    avg_pace_s_per_km REAL DEFAULT 0,
    avg_hr INTEGER DEFAULT 0,
    calories INTEGER DEFAULT 0,
    FOREIGN KEY (activity_id) REFERENCES activities(activity_id)
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_activities_sport_type ON activities(sport_type);
CREATE INDEX IF NOT EXISTS idx_activities_source ON activities(source);
CREATE INDEX IF NOT EXISTS idx_laps_activity_id ON laps(activity_id);
"""

# ==================== 健康数据表 ====================

CREATE_DAILY_STEPS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    steps INTEGER DEFAULT 0,
    distance_m REAL DEFAULT 0,
    calories INTEGER DEFAULT 0,
    floors_climbed INTEGER DEFAULT 0,
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT ''
);
"""

CREATE_HEART_RATE_TABLE = """
CREATE TABLE IF NOT EXISTS heart_rate_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    resting_hr INTEGER DEFAULT 0,
    max_hr INTEGER DEFAULT 0,
    min_hr INTEGER DEFAULT 0,
    avg_hr INTEGER DEFAULT 0,
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT ''
);
"""

CREATE_HRV_TABLE = """
CREATE TABLE IF NOT EXISTS hrv_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    weekly_avg REAL DEFAULT 0,
    last_night_avg REAL DEFAULT 0,
    last_night_5min_high REAL DEFAULT 0,
    status TEXT DEFAULT '',
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT ''
);
"""

CREATE_SLEEP_TABLE = """
CREATE TABLE IF NOT EXISTS sleep_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    sleep_start TEXT DEFAULT '',
    sleep_end TEXT DEFAULT '',
    total_sleep_s INTEGER DEFAULT 0,
    deep_sleep_s INTEGER DEFAULT 0,
    light_sleep_s INTEGER DEFAULT 0,
    rem_sleep_s INTEGER DEFAULT 0,
    awake_s INTEGER DEFAULT 0,
    sleep_score INTEGER DEFAULT 0,
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT ''
);
"""

CREATE_WEIGHT_TABLE = """
CREATE TABLE IF NOT EXISTS weight_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    weight_kg REAL DEFAULT 0,
    bmi REAL DEFAULT 0,
    body_fat_pct REAL DEFAULT 0,
    muscle_mass_kg REAL DEFAULT 0,
    bone_mass_kg REAL DEFAULT 0,
    body_water_pct REAL DEFAULT 0,
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT '',
    UNIQUE(date, source)
);
"""

CREATE_SPO2_TABLE = """
CREATE TABLE IF NOT EXISTS spo2_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    avg_spo2 REAL DEFAULT 0,
    min_spo2 REAL DEFAULT 0,
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT ''
);
"""

CREATE_HEALTH_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_daily_steps_date ON daily_steps(date);
CREATE INDEX IF NOT EXISTS idx_heart_rate_date ON heart_rate_data(date);
CREATE INDEX IF NOT EXISTS idx_hrv_date ON hrv_data(date);
CREATE INDEX IF NOT EXISTS idx_sleep_date ON sleep_data(date);
CREATE INDEX IF NOT EXISTS idx_weight_date ON weight_data(date);
CREATE INDEX IF NOT EXISTS idx_spo2_date ON spo2_data(date);
"""


class Database:
    """SQLite 数据库操作类"""

    def __init__(self, db_path: str | Path):
        """
        初始化数据库连接

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def init_db(self):
        """
        初始化数据库表结构

        创建 activities 和 laps 表以及相关索引
        """
        conn = self._get_conn()
        conn.execute(CREATE_ACTIVITIES_TABLE)
        conn.execute(CREATE_LAPS_TABLE)
        conn.executescript(CREATE_INDEXES)
        
        # 创建健康数据表
        conn.execute(CREATE_DAILY_STEPS_TABLE)
        conn.execute(CREATE_HEART_RATE_TABLE)
        conn.execute(CREATE_HRV_TABLE)
        conn.execute(CREATE_SLEEP_TABLE)
        conn.execute(CREATE_WEIGHT_TABLE)
        conn.execute(CREATE_SPO2_TABLE)
        conn.executescript(CREATE_HEALTH_INDEXES)
        
        conn.commit()
        logger.info(f"数据库初始化完成: {self.db_path}")

    def insert_activity(self, activity: Activity, laps: List[LapData] = None) -> bool:
        """
        插入运动活动记录（按 activity_id 去重）

        Args:
            activity: 活动数据
            laps: 分圈数据列表

        Returns:
            是否为新记录（True=新增，False=已存在被跳过）
        """
        conn = self._get_conn()

        # 检查是否已存在
        cursor = conn.execute(
            "SELECT activity_id FROM activities WHERE activity_id = ?",
            (activity.activity_id,)
        )
        if cursor.fetchone() is not None:
            logger.debug(f"活动已存在，跳过: {activity.activity_id}")
            return False

        try:
            # 使用事务确保活动和分圈数据要么全部成功，要么全部回滚
            conn.execute("BEGIN")

            # 插入活动记录
            conn.execute("""
                INSERT INTO activities (
                    activity_id, name, sport_type, start_time,
                    distance_m, duration_s, moving_duration_s, avg_pace_s_per_km,
                    avg_hr, max_hr, avg_cadence, calories, elevation_gain_m,
                    source, source_file, sync_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                activity.activity_id,
                activity.name,
                activity.sport_type,
                activity.start_time.isoformat() if activity.start_time else "",
                activity.distance_m,
                activity.duration_s,
                activity.moving_duration_s,
                activity.avg_pace_s_per_km,
                activity.avg_hr,
                activity.max_hr,
                activity.avg_cadence,
                activity.calories,
                activity.elevation_gain_m,
                activity.source,
                activity.source_file,
                activity.sync_status,
                activity.created_at.isoformat() if activity.created_at else datetime.now().isoformat(),
            ))

            # 插入分圈数据
            if laps:
                for lap in laps:
                    conn.execute("""
                        INSERT INTO laps (
                            activity_id, lap_index, distance_m, duration_s,
                            avg_pace_s_per_km, avg_hr, calories
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        lap.activity_id,
                        lap.lap_index,
                        lap.distance_m,
                        lap.duration_s,
                        lap.avg_pace_s_per_km,
                        lap.avg_hr,
                        lap.calories,
                    ))

            conn.execute("COMMIT")
            logger.info(f"新增活动: {activity.name} ({activity.activity_id})")
            return True

        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"插入活动失败 {activity.activity_id}: {e}")
            raise

    def get_activities(self, limit: int = 50, offset: int = 0) -> List[dict]:
        """
        查询活动列表（按开始时间倒序）

        Args:
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            活动字典列表
        """
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM activities
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return [dict(row) for row in cursor.fetchall()]

    def get_activity_by_id(self, activity_id: str) -> Optional[dict]:
        """
        根据 ID 查询单个活动

        Args:
            activity_id: 活动 ID

        Returns:
            活动字典或 None
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM activities WHERE activity_id = ?",
            (activity_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_laps_by_activity_id(self, activity_id: str) -> List[dict]:
        """
        根据活动 ID 查询分圈数据

        Args:
            activity_id: 活动 ID

        Returns:
            分圈数据字典列表
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM laps WHERE activity_id = ? ORDER BY lap_index",
            (activity_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def replace_laps(self, activity_id: str, laps: List[LapData]) -> int:
        """
        替换指定活动的分圈数据。

        Args:
            activity_id: 活动 ID
            laps: 分圈数据列表

        Returns:
            写入的分圈数量
        """
        if not laps:
            return 0
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM laps WHERE activity_id = ?", (activity_id,))
            for index, lap in enumerate(laps):
                conn.execute("""
                    INSERT INTO laps (
                        activity_id, lap_index, distance_m, duration_s,
                        avg_pace_s_per_km, avg_hr, calories
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    activity_id,
                    index,
                    lap.distance_m,
                    lap.duration_s,
                    lap.avg_pace_s_per_km,
                    lap.avg_hr,
                    lap.calories,
                ))
            conn.execute("COMMIT")
            return len(laps)
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def get_last_activity(self) -> Optional[dict]:
        """
        查询最近一次运动

        Returns:
            活动字典或 None
        """
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM activities
            ORDER BY start_time DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_weekly_stats(self) -> WeeklyStats:
        """
        查询本周运动统计（从周日开始）

        Returns:
            本周统计数据
        """
        conn = self._get_conn()
        # 获取本周日的日期（周日开始计算）
        # weekday(): 周一=0, 周日=6
        today = datetime.now()
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - timedelta(days=days_since_sunday)
        sunday_str = sunday.strftime("%Y-%m-%d")

        cursor = conn.execute("""
            SELECT
                COUNT(*) as total_activities,
                COALESCE(SUM(distance_m), 0) as total_distance_m,
                COALESCE(SUM(duration_s), 0) as total_duration_s,
                COALESCE(SUM(calories), 0) as total_calories
            FROM activities
            WHERE start_time >= ?
        """, (sunday_str,))

        row = cursor.fetchone()
        if row:
            return WeeklyStats(
                total_activities=row["total_activities"],
                total_distance_m=row["total_distance_m"],
                total_duration_s=row["total_duration_s"],
                total_calories=row["total_calories"],
            )
        return WeeklyStats()

    def get_monthly_stats(self) -> MonthlyStats:
        """
        查询本月运动统计

        Returns:
            本月统计数据
        """
        conn = self._get_conn()
        # 获取本月1号的日期
        today = datetime.now()
        first_day = today.replace(day=1)
        first_day_str = first_day.strftime("%Y-%m-%d")

        cursor = conn.execute("""
            SELECT
                COUNT(*) as total_activities,
                COALESCE(SUM(distance_m), 0) as total_distance_m,
                COALESCE(SUM(duration_s), 0) as total_duration_s,
                COALESCE(SUM(calories), 0) as total_calories
            FROM activities
            WHERE start_time >= ?
        """, (first_day_str,))

        row = cursor.fetchone()
        if row:
            return MonthlyStats(
                total_activities=row["total_activities"],
                total_distance_m=row["total_distance_m"],
                total_duration_s=row["total_duration_s"],
                total_calories=row["total_calories"],
            )
        return MonthlyStats()

    def get_activity_count(self) -> int:
        """
        查询活动总数

        Returns:
            活动总数
        """
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM activities")
        return cursor.fetchone()[0]

    def get_activities_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """
        按日期范围查询活动

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            活动字典列表
        """
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM activities
            WHERE start_time >= ? AND start_time <= ?
            ORDER BY start_time DESC
        """, (start_date, end_date + " 23:59:59"))
        return [dict(row) for row in cursor.fetchall()]

    def get_sport_type_stats(self) -> List[dict]:
        """
        按运动类型统计

        Returns:
            运动类型统计列表
        """
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT
                sport_type,
                COUNT(*) as count,
                COALESCE(SUM(distance_m), 0) as total_distance_m,
                COALESCE(SUM(duration_s), 0) as total_duration_s
            FROM activities
            GROUP BY sport_type
            ORDER BY count DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 健康数据 CRUD ====================

    def insert_daily_steps(self, steps: DailySteps) -> bool:
        """
        插入每日步数数据（按日期去重，存在则更新）

        Args:
            steps: 步数数据

        Returns:
            是否为新记录
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO daily_steps (date, steps, distance_m, calories, floors_climbed, source, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    steps = excluded.steps,
                    distance_m = excluded.distance_m,
                    calories = excluded.calories,
                    floors_climbed = excluded.floors_climbed,
                    synced_at = excluded.synced_at
            """, (
                steps.date,
                steps.steps,
                steps.distance_m,
                steps.calories,
                steps.floors_climbed,
                steps.source,
                steps.created_at.isoformat() if steps.created_at else datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"插入步数数据失败 {steps.date}: {e}")
            return False

    def insert_daily_steps_batch(self, steps_list: List[DailySteps]) -> int:
        """
        批量插入每日步数数据

        Args:
            steps_list: 步数数据列表

        Returns:
            成功插入的数量
        """
        count = 0
        for steps in steps_list:
            if self.insert_daily_steps(steps):
                count += 1
        return count

    def insert_heart_rate(self, hr: HeartRateData) -> bool:
        """
        插入心率数据（按日期去重）

        Args:
            hr: 心率数据

        Returns:
            是否成功
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO heart_rate_data (date, resting_hr, max_hr, min_hr, avg_hr, source, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    resting_hr = excluded.resting_hr,
                    max_hr = excluded.max_hr,
                    min_hr = excluded.min_hr,
                    avg_hr = excluded.avg_hr,
                    synced_at = excluded.synced_at
            """, (
                hr.date,
                hr.resting_hr,
                hr.max_hr,
                hr.min_hr,
                hr.avg_hr,
                hr.source,
                hr.created_at.isoformat() if hr.created_at else datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"插入心率数据失败 {hr.date}: {e}")
            return False

    def insert_hrv(self, hrv: HRVData) -> bool:
        """
        插入HRV数据（按日期去重）

        Args:
            hrv: HRV数据

        Returns:
            是否成功
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO hrv_data (date, weekly_avg, last_night_avg, last_night_5min_high, status, source, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    weekly_avg = excluded.weekly_avg,
                    last_night_avg = excluded.last_night_avg,
                    last_night_5min_high = excluded.last_night_5min_high,
                    status = excluded.status,
                    synced_at = excluded.synced_at
            """, (
                hrv.date,
                hrv.weekly_avg,
                hrv.last_night_avg,
                hrv.last_night_5min_high,
                hrv.status,
                hrv.source,
                hrv.created_at.isoformat() if hrv.created_at else datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"插入HRV数据失败 {hrv.date}: {e}")
            return False

    def insert_sleep(self, sleep: SleepData) -> bool:
        """
        插入睡眠数据（按日期去重）

        Args:
            sleep: 睡眠数据

        Returns:
            是否成功
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO sleep_data (date, sleep_start, sleep_end, total_sleep_s, deep_sleep_s, light_sleep_s, rem_sleep_s, awake_s, sleep_score, source, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    sleep_start = excluded.sleep_start,
                    sleep_end = excluded.sleep_end,
                    total_sleep_s = excluded.total_sleep_s,
                    deep_sleep_s = excluded.deep_sleep_s,
                    light_sleep_s = excluded.light_sleep_s,
                    rem_sleep_s = excluded.rem_sleep_s,
                    awake_s = excluded.awake_s,
                    sleep_score = excluded.sleep_score,
                    synced_at = excluded.synced_at
            """, (
                sleep.date,
                sleep.sleep_start.isoformat() if sleep.sleep_start else "",
                sleep.sleep_end.isoformat() if sleep.sleep_end else "",
                sleep.total_sleep_s,
                sleep.deep_sleep_s,
                sleep.light_sleep_s,
                sleep.rem_sleep_s,
                sleep.awake_s,
                sleep.sleep_score,
                sleep.source,
                sleep.created_at.isoformat() if sleep.created_at else datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"插入睡眠数据失败 {sleep.date}: {e}")
            return False

    def insert_weight(self, weight: WeightData) -> bool:
        """
        插入体重数据（按日期和来源去重）

        Args:
            weight: 体重数据

        Returns:
            是否成功
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO weight_data (date, weight_kg, bmi, body_fat_pct, muscle_mass_kg, bone_mass_kg, body_water_pct, source, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, source) DO UPDATE SET
                    weight_kg = excluded.weight_kg,
                    bmi = excluded.bmi,
                    body_fat_pct = excluded.body_fat_pct,
                    muscle_mass_kg = excluded.muscle_mass_kg,
                    bone_mass_kg = excluded.bone_mass_kg,
                    body_water_pct = excluded.body_water_pct,
                    synced_at = excluded.synced_at
            """, (
                weight.date,
                weight.weight_kg,
                weight.bmi,
                weight.body_fat_pct,
                weight.muscle_mass_kg,
                weight.bone_mass_kg,
                weight.body_water_pct,
                weight.source,
                weight.created_at.isoformat() if weight.created_at else datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"插入体重数据失败 {weight.date}: {e}")
            return False

    def insert_spo2(self, spo2: SpO2Data) -> bool:
        """
        插入SpO2数据（按日期去重）

        Args:
            spo2: SpO2数据

        Returns:
            是否成功
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO spo2_data (date, avg_spo2, min_spo2, source, created_at, synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    avg_spo2 = excluded.avg_spo2,
                    min_spo2 = excluded.min_spo2,
                    synced_at = excluded.synced_at
            """, (
                spo2.date,
                spo2.avg_spo2,
                spo2.min_spo2,
                spo2.source,
                spo2.created_at.isoformat() if spo2.created_at else datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"插入SpO2数据失败 {spo2.date}: {e}")
            return False

    def get_daily_steps_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """按日期范围查询步数数据"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM daily_steps
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def get_heart_rate_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """按日期范围查询心率数据"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM heart_rate_data
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def get_hrv_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """按日期范围查询HRV数据"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM hrv_data
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def get_sleep_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """按日期范围查询睡眠数据"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM sleep_data
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def get_weight_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """按日期范围查询体重数据"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM weight_data
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def get_spo2_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
        """按日期范围查询SpO2数据"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM spo2_data
            WHERE date >= ? AND date <= ?
            ORDER BY date DESC
        """, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def get_latest_health_data(self) -> dict:
        """
        获取最新的健康数据摘要

        Returns:
            包含各健康数据最新值的字典
        """
        conn = self._get_conn()
        result = {}

        # 最新步数
        cursor = conn.execute("SELECT * FROM daily_steps ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result['steps'] = dict(row) if row else None

        # 最新心率
        cursor = conn.execute("SELECT * FROM heart_rate_data ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result['heart_rate'] = dict(row) if row else None

        # 最新HRV
        cursor = conn.execute("SELECT * FROM hrv_data ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result['hrv'] = dict(row) if row else None

        # 最新睡眠
        cursor = conn.execute("SELECT * FROM sleep_data ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result['sleep'] = dict(row) if row else None

        # 最新体重
        cursor = conn.execute("SELECT * FROM weight_data ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result['weight'] = dict(row) if row else None

        # 最新SpO2
        cursor = conn.execute("SELECT * FROM spo2_data ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result['spo2'] = dict(row) if row else None

        return result

    def get_health_data_count(self) -> dict:
        """
        获取各类健康数据的记录数

        Returns:
            各类数据的记录数字典
        """
        conn = self._get_conn()
        result = {}
        
        for table in ['daily_steps', 'heart_rate_data', 'hrv_data', 'sleep_data', 'weight_data', 'spo2_data']:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            result[table] = cursor.fetchone()[0]
        
        return result
