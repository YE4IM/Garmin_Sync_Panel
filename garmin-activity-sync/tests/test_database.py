"""
数据库健康数据操作单元测试
"""
import pytest
import os
import tempfile
from datetime import datetime
from core.database import Database
from core.models import (
    DailySteps, HeartRateData, HRVData, SleepData, WeightData, SpO2Data
)


@pytest.fixture
def db():
    """创建临时数据库fixture"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    database = Database(db_path)
    database.init_db()
    yield database
    database.close()
    
    # 清理临时文件
    if os.path.exists(db_path):
        os.unlink(db_path)


class TestDailyStepsDB:
    """步数数据数据库操作测试"""

    def test_insert_and_retrieve(self, db):
        """测试插入和查询步数数据"""
        steps = DailySteps(
            date="2024-01-15",
            steps=8500,
            distance_m=6200.5,
            calories=350,
            floors_climbed=12
        )
        result = db.insert_daily_steps(steps)
        assert result is True

        # 查询验证
        data = db.get_daily_steps_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["steps"] == 8500
        assert data[0]["distance_m"] == 6200.5

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        steps1 = DailySteps(date="2024-01-15", steps=8000)
        steps2 = DailySteps(date="2024-01-15", steps=9000)
        
        db.insert_daily_steps(steps1)
        db.insert_daily_steps(steps2)
        
        data = db.get_daily_steps_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["steps"] == 9000  # 应该是更新后的值

    def test_insert_batch(self, db):
        """测试批量插入"""
        steps_list = [
            DailySteps(date="2024-01-15", steps=8500),
            DailySteps(date="2024-01-14", steps=7200),
            DailySteps(date="2024-01-13", steps=6800),
        ]
        count = db.insert_daily_steps_batch(steps_list)
        assert count == 3

        data = db.get_daily_steps_by_date_range("2024-01-13", "2024-01-15")
        assert len(data) == 3

    def test_date_range_query(self, db):
        """测试日期范围查询"""
        db.insert_daily_steps(DailySteps(date="2024-01-13", steps=6800))
        db.insert_daily_steps(DailySteps(date="2024-01-14", steps=7200))
        db.insert_daily_steps(DailySteps(date="2024-01-15", steps=8500))
        db.insert_daily_steps(DailySteps(date="2024-01-16", steps=9000))

        # 查询中间范围
        data = db.get_daily_steps_by_date_range("2024-01-14", "2024-01-15")
        assert len(data) == 2


class TestHeartRateDB:
    """心率数据数据库操作测试"""

    def test_insert_and_retrieve(self, db):
        """测试插入和查询心率数据"""
        hr = HeartRateData(
            date="2024-01-15",
            resting_hr=58,
            max_hr=185,
            min_hr=42,
            avg_hr=72
        )
        result = db.insert_heart_rate(hr)
        assert result is True

        data = db.get_heart_rate_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["resting_hr"] == 58
        assert data[0]["max_hr"] == 185

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        hr1 = HeartRateData(date="2024-01-15", resting_hr=58)
        hr2 = HeartRateData(date="2024-01-15", resting_hr=60)
        
        db.insert_heart_rate(hr1)
        db.insert_heart_rate(hr2)
        
        data = db.get_heart_rate_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["resting_hr"] == 60


class TestHRVDB:
    """HRV数据数据库操作测试"""

    def test_insert_and_retrieve(self, db):
        """测试插入和查询HRV数据"""
        hrv = HRVData(
            date="2024-01-15",
            weekly_avg=45.2,
            last_night_avg=48.5,
            last_night_5min_high=65.3,
            status="balanced"
        )
        result = db.insert_hrv(hrv)
        assert result is True

        data = db.get_hrv_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["weekly_avg"] == 45.2
        assert data[0]["status"] == "balanced"

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        hrv1 = HRVData(date="2024-01-15", weekly_avg=45.0, status="balanced")
        hrv2 = HRVData(date="2024-01-15", weekly_avg=46.0, status="unbalanced")
        
        db.insert_hrv(hrv1)
        db.insert_hrv(hrv2)
        
        data = db.get_hrv_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["weekly_avg"] == 46.0
        assert data[0]["status"] == "unbalanced"


class TestSleepDB:
    """睡眠数据数据库操作测试"""

    def test_insert_and_retrieve(self, db):
        """测试插入和查询睡眠数据"""
        sleep = SleepData(
            date="2024-01-15",
            total_sleep_s=28800,
            deep_sleep_s=7200,
            light_sleep_s=14400,
            rem_sleep_s=5400,
            awake_s=1800,
            sleep_score=85
        )
        result = db.insert_sleep(sleep)
        assert result is True

        data = db.get_sleep_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["total_sleep_s"] == 28800
        assert data[0]["sleep_score"] == 85

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        sleep1 = SleepData(date="2024-01-15", sleep_score=80)
        sleep2 = SleepData(date="2024-01-15", sleep_score=90)
        
        db.insert_sleep(sleep1)
        db.insert_sleep(sleep2)
        
        data = db.get_sleep_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["sleep_score"] == 90


class TestWeightDB:
    """体重数据数据库操作测试"""

    def test_insert_and_retrieve(self, db):
        """测试插入和查询体重数据"""
        weight = WeightData(
            date="2024-01-15",
            weight_kg=72.5,
            bmi=23.4,
            body_fat_pct=18.5,
            muscle_mass_kg=32.2,
            bone_mass_kg=3.1,
            body_water_pct=58.5
        )
        result = db.insert_weight(weight)
        assert result is True

        data = db.get_weight_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["weight_kg"] == 72.5
        assert data[0]["bmi"] == 23.4

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        weight1 = WeightData(date="2024-01-15", weight_kg=72.5, source="garmin_connect")
        weight2 = WeightData(date="2024-01-15", weight_kg=72.0, source="garmin_connect")
        
        db.insert_weight(weight1)
        db.insert_weight(weight2)
        
        data = db.get_weight_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["weight_kg"] == 72.0


class TestSpO2DB:
    """SpO2数据数据库操作测试"""

    def test_insert_and_retrieve(self, db):
        """测试插入和查询SpO2数据"""
        spo2 = SpO2Data(
            date="2024-01-15",
            avg_spo2=97.5,
            min_spo2=93.0
        )
        result = db.insert_spo2(spo2)
        assert result is True

        data = db.get_spo2_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["avg_spo2"] == 97.5
        assert data[0]["min_spo2"] == 93.0

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        spo2_1 = SpO2Data(date="2024-01-15", avg_spo2=97.0)
        spo2_2 = SpO2Data(date="2024-01-15", avg_spo2=98.0)
        
        db.insert_spo2(spo2_1)
        db.insert_spo2(spo2_2)
        
        data = db.get_spo2_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["avg_spo2"] == 98.0


class TestLatestHealthData:
    """最新健康数据查询测试"""

    def test_get_latest_health_data_empty(self, db):
        """测试空数据库获取最新健康数据"""
        latest = db.get_latest_health_data()
        assert latest["steps"] is None
        assert latest["heart_rate"] is None
        assert latest["hrv"] is None
        assert latest["sleep"] is None
        assert latest["weight"] is None
        assert latest["spo2"] is None

    def test_get_latest_health_data_with_data(self, db):
        """测试有数据时获取最新健康数据"""
        # 插入测试数据
        db.insert_daily_steps(DailySteps(date="2024-01-15", steps=8500))
        db.insert_daily_steps(DailySteps(date="2024-01-16", steps=9000))
        db.insert_heart_rate(HeartRateData(date="2024-01-16", resting_hr=58))
        
        latest = db.get_latest_health_data()
        assert latest["steps"]["steps"] == 9000  # 应该是最新日期的数据
        assert latest["heart_rate"]["resting_hr"] == 58

    def test_get_health_data_count(self, db):
        """测试获取健康数据记录数"""
        # 插入测试数据
        db.insert_daily_steps(DailySteps(date="2024-01-15", steps=8500))
        db.insert_daily_steps(DailySteps(date="2024-01-16", steps=9000))
        db.insert_heart_rate(HeartRateData(date="2024-01-15", resting_hr=58))
        
        counts = db.get_health_data_count()
        assert counts["daily_steps"] == 2
        assert counts["heart_rate_data"] == 1
        assert counts["hrv_data"] == 0
        assert counts["sleep_data"] == 0
        assert counts["weight_data"] == 0
        assert counts["spo2_data"] == 0
