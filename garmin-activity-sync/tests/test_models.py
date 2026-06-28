"""
健康数据模型单元测试
"""
import pytest
from datetime import datetime
from core.models import (
    DailySteps, HeartRateData, HRVData, SleepData, WeightData, SpO2Data
)


class TestDailySteps:
    """步数数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        steps = DailySteps(date="2024-01-15")
        assert steps.date == "2024-01-15"
        assert steps.steps == 0
        assert steps.distance_m == 0.0
        assert steps.calories == 0
        assert steps.floors_climbed == 0
        assert steps.source == "garmin_connect"

    def test_custom_values(self):
        """测试自定义值"""
        now = datetime.now()
        steps = DailySteps(
            date="2024-01-15",
            steps=8500,
            distance_m=6200.5,
            calories=350,
            floors_climbed=12,
            source="garmin_connect",
            created_at=now
        )
        assert steps.steps == 8500
        assert steps.distance_m == 6200.5
        assert steps.calories == 350
        assert steps.floors_climbed == 12
        assert steps.created_at == now

    def test_to_dict(self):
        """测试转换为字典"""
        steps = DailySteps(
            date="2024-01-15",
            steps=8500,
            distance_m=6200.5,
            calories=350,
            floors_climbed=12
        )
        d = steps.to_dict()
        assert d["date"] == "2024-01-15"
        assert d["steps"] == 8500
        assert d["distance_m"] == 6200.5
        assert d["calories"] == 350
        assert d["floors_climbed"] == 12
        assert d["source"] == "garmin_connect"

    def test_to_dict_with_created_at(self):
        """测试带created_at的字典转换"""
        now = datetime(2024, 1, 15, 10, 30, 0)
        steps = DailySteps(date="2024-01-15", created_at=now)
        d = steps.to_dict()
        assert d["created_at"] == "2024-01-15T10:30:00"

    def test_to_dict_without_created_at(self):
        """测试不带created_at的字典转换"""
        steps = DailySteps(date="2024-01-15")
        d = steps.to_dict()
        assert d["created_at"] == ""


class TestHeartRateData:
    """心率数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        hr = HeartRateData(date="2024-01-15")
        assert hr.date == "2024-01-15"
        assert hr.resting_hr == 0
        assert hr.max_hr == 0
        assert hr.min_hr == 0
        assert hr.avg_hr == 0

    def test_custom_values(self):
        """测试自定义值"""
        hr = HeartRateData(
            date="2024-01-15",
            resting_hr=58,
            max_hr=185,
            min_hr=42,
            avg_hr=72
        )
        assert hr.resting_hr == 58
        assert hr.max_hr == 185
        assert hr.min_hr == 42
        assert hr.avg_hr == 72

    def test_to_dict(self):
        """测试转换为字典"""
        hr = HeartRateData(
            date="2024-01-15",
            resting_hr=58,
            max_hr=185,
            min_hr=42,
            avg_hr=72
        )
        d = hr.to_dict()
        assert d["date"] == "2024-01-15"
        assert d["resting_hr"] == 58
        assert d["max_hr"] == 185
        assert d["min_hr"] == 42
        assert d["avg_hr"] == 72


class TestHRVData:
    """HRV数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        hrv = HRVData(date="2024-01-15")
        assert hrv.date == "2024-01-15"
        assert hrv.weekly_avg == 0.0
        assert hrv.last_night_avg == 0.0
        assert hrv.last_night_5min_high == 0.0
        assert hrv.status == ""

    def test_custom_values(self):
        """测试自定义值"""
        hrv = HRVData(
            date="2024-01-15",
            weekly_avg=45.2,
            last_night_avg=48.5,
            last_night_5min_high=65.3,
            status="balanced"
        )
        assert hrv.weekly_avg == 45.2
        assert hrv.last_night_avg == 48.5
        assert hrv.last_night_5min_high == 65.3
        assert hrv.status == "balanced"

    def test_to_dict(self):
        """测试转换为字典"""
        hrv = HRVData(
            date="2024-01-15",
            weekly_avg=45.2,
            last_night_avg=48.5,
            last_night_5min_high=65.3,
            status="balanced"
        )
        d = hrv.to_dict()
        assert d["date"] == "2024-01-15"
        assert d["weekly_avg"] == 45.2
        assert d["last_night_avg"] == 48.5
        assert d["last_night_5min_high"] == 65.3
        assert d["status"] == "balanced"


class TestSleepData:
    """睡眠数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        sleep = SleepData(date="2024-01-15")
        assert sleep.date == "2024-01-15"
        assert sleep.sleep_start is None
        assert sleep.sleep_end is None
        assert sleep.total_sleep_s == 0
        assert sleep.deep_sleep_s == 0
        assert sleep.light_sleep_s == 0
        assert sleep.rem_sleep_s == 0
        assert sleep.awake_s == 0
        assert sleep.sleep_score == 0

    def test_custom_values(self):
        """测试自定义值"""
        start = datetime(2024, 1, 14, 23, 0, 0)
        end = datetime(2024, 1, 15, 7, 30, 0)
        sleep = SleepData(
            date="2024-01-15",
            sleep_start=start,
            sleep_end=end,
            total_sleep_s=28800,
            deep_sleep_s=7200,
            light_sleep_s=14400,
            rem_sleep_s=5400,
            awake_s=1800,
            sleep_score=85
        )
        assert sleep.sleep_start == start
        assert sleep.sleep_end == end
        assert sleep.total_sleep_s == 28800
        assert sleep.deep_sleep_s == 7200
        assert sleep.light_sleep_s == 14400
        assert sleep.rem_sleep_s == 5400
        assert sleep.awake_s == 1800
        assert sleep.sleep_score == 85

    def test_to_dict(self):
        """测试转换为字典"""
        start = datetime(2024, 1, 14, 23, 0, 0)
        end = datetime(2024, 1, 15, 7, 30, 0)
        sleep = SleepData(
            date="2024-01-15",
            sleep_start=start,
            sleep_end=end,
            total_sleep_s=28800,
            deep_sleep_s=7200,
            light_sleep_s=14400,
            rem_sleep_s=5400,
            awake_s=1800,
            sleep_score=85
        )
        d = sleep.to_dict()
        assert d["date"] == "2024-01-15"
        assert d["sleep_start"] == "2024-01-14T23:00:00"
        assert d["sleep_end"] == "2024-01-15T07:30:00"
        assert d["total_sleep_s"] == 28800
        assert d["sleep_score"] == 85

    def test_to_dict_without_times(self):
        """测试不带时间的字典转换"""
        sleep = SleepData(date="2024-01-15")
        d = sleep.to_dict()
        assert d["sleep_start"] == ""
        assert d["sleep_end"] == ""


class TestWeightData:
    """体重数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        weight = WeightData(date="2024-01-15")
        assert weight.date == "2024-01-15"
        assert weight.weight_kg == 0.0
        assert weight.bmi == 0.0
        assert weight.body_fat_pct == 0.0
        assert weight.muscle_mass_kg == 0.0
        assert weight.bone_mass_kg == 0.0
        assert weight.body_water_pct == 0.0

    def test_custom_values(self):
        """测试自定义值"""
        weight = WeightData(
            date="2024-01-15",
            weight_kg=72.5,
            bmi=23.4,
            body_fat_pct=18.5,
            muscle_mass_kg=32.2,
            bone_mass_kg=3.1,
            body_water_pct=58.5
        )
        assert weight.weight_kg == 72.5
        assert weight.bmi == 23.4
        assert weight.body_fat_pct == 18.5
        assert weight.muscle_mass_kg == 32.2
        assert weight.bone_mass_kg == 3.1
        assert weight.body_water_pct == 58.5

    def test_to_dict(self):
        """测试转换为字典"""
        weight = WeightData(
            date="2024-01-15",
            weight_kg=72.5,
            bmi=23.4,
            body_fat_pct=18.5
        )
        d = weight.to_dict()
        assert d["date"] == "2024-01-15"
        assert d["weight_kg"] == 72.5
        assert d["bmi"] == 23.4
        assert d["body_fat_pct"] == 18.5


class TestSpO2Data:
    """SpO2数据模型测试"""

    def test_default_values(self):
        """测试默认值"""
        spo2 = SpO2Data(date="2024-01-15")
        assert spo2.date == "2024-01-15"
        assert spo2.avg_spo2 == 0.0
        assert spo2.min_spo2 == 0.0

    def test_custom_values(self):
        """测试自定义值"""
        spo2 = SpO2Data(
            date="2024-01-15",
            avg_spo2=97.5,
            min_spo2=93.0
        )
        assert spo2.avg_spo2 == 97.5
        assert spo2.min_spo2 == 93.0

    def test_to_dict(self):
        """测试转换为字典"""
        spo2 = SpO2Data(
            date="2024-01-15",
            avg_spo2=97.5,
            min_spo2=93.0
        )
        d = spo2.to_dict()
        assert d["date"] == "2024-01-15"
        assert d["avg_spo2"] == 97.5
        assert d["min_spo2"] == 93.0
