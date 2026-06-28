"""
健康数据解析模块单元测试
"""
import pytest
from datetime import datetime
from garmin.health import (
    parse_daily_steps,
    parse_heart_rate_data,
    parse_hrv_data,
    parse_sleep_data,
    parse_weight_data,
    parse_spo2_data,
)


class TestParseDailySteps:
    """步数数据解析测试"""

    def test_parse_valid_data(self):
        """测试解析有效数据"""
        data = [
            {
                "calendarDate": "2024-01-15",
                "totalSteps": 8500,
                "totalDistance": 6200,
                "activeKilocalories": 350,
                "floorsAscended": 12
            },
            {
                "calendarDate": "2024-01-14",
                "totalSteps": 6200,
                "totalDistance": 4500,
                "activeKilocalories": 280,
                "floorsAscended": 8
            }
        ]
        result = parse_daily_steps(data)
        assert len(result) == 2
        assert result[0].date == "2024-01-15"
        assert result[0].steps == 8500
        assert result[0].distance_m == 6200
        assert result[0].calories == 350
        assert result[0].floors_climbed == 12
        assert result[1].date == "2024-01-14"
        assert result[1].steps == 6200

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_daily_steps([])
        assert len(result) == 0

    def test_parse_missing_fields(self):
        """测试解析缺失字段的数据"""
        data = [{"calendarDate": "2024-01-15"}]
        result = parse_daily_steps(data)
        assert len(result) == 1
        assert result[0].steps == 0
        assert result[0].distance_m == 0.0

    def test_parse_invalid_entry(self):
        """测试解析无效条目"""
        data = [
            {"calendarDate": "2024-01-15", "totalSteps": 8500},
            {},  # 无效条目，没有日期
        ]
        result = parse_daily_steps(data)
        assert len(result) == 1  # 只有有效条目被解析

    def test_parse_custom_source(self):
        """测试自定义数据来源"""
        data = [{"calendarDate": "2024-01-15", "totalSteps": 8500}]
        result = parse_daily_steps(data, source="custom_source")
        assert result[0].source == "custom_source"


class TestParseHeartRateData:
    """心率数据解析测试"""

    def test_parse_valid_data(self):
        """测试解析有效数据（包含heartRateValues数组）"""
        data = {
            "restingHeartRate": 58,
            "maxHeartRate": 185,
            "minHeartRate": 42,
            "heartRateValues": [
                [1705273200000, 72],
                [1705273260000, 75],
                [1705273320000, 68],
                [1705273380000, None],  # null值应该被过滤
            ]
        }
        result = parse_heart_rate_data(data, "2024-01-15")
        assert result is not None
        assert result.date == "2024-01-15"
        assert result.resting_hr == 58
        assert result.max_hr == 185
        assert result.min_hr == 42
        assert result.avg_hr == 72  # (72+75+68)/3 = 71.67 -> 72

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_heart_rate_data({}, "2024-01-15")
        assert result is None

    def test_parse_none_data(self):
        """测试解析None数据"""
        result = parse_heart_rate_data(None, "2024-01-15")
        assert result is None

    def test_parse_missing_fields(self):
        """测试解析缺失字段的数据"""
        data = {"restingHeartRate": 58}
        result = parse_heart_rate_data(data, "2024-01-15")
        assert result is not None
        assert result.resting_hr == 58
        assert result.max_hr == 0
        assert result.min_hr == 0
        assert result.avg_hr == 0

    def test_parse_all_null_hr_values(self):
        """测试所有心率值为null的情况"""
        data = {
            "restingHeartRate": 58,
            "heartRateValues": [
                [1705273200000, None],
                [1705273260000, None],
            ]
        }
        result = parse_heart_rate_data(data, "2024-01-15")
        assert result is not None
        assert result.avg_hr == 0


class TestParseHRVData:
    """HRV数据解析测试"""

    def test_parse_valid_data(self):
        """测试解析有效数据（嵌套在hrvSummary中）"""
        data = {
            "hrvSummary": {
                "weeklyAvg": 45.2,
                "lastNightAvg": 48.5,
                "lastNight5MinHigh": 65.3,
                "status": "BALANCED"
            },
            "hrvReadings": []
        }
        result = parse_hrv_data(data, "2024-01-15")
        assert result is not None
        assert result.date == "2024-01-15"
        assert result.weekly_avg == 45.2
        assert result.last_night_avg == 48.5
        assert result.last_night_5min_high == 65.3
        assert result.status == "BALANCED"

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_hrv_data({}, "2024-01-15")
        assert result is None

    def test_parse_none_data(self):
        """测试解析None数据"""
        result = parse_hrv_data(None, "2024-01-15")
        assert result is None

    def test_parse_partial_data(self):
        """测试解析部分数据"""
        data = {
            "hrvSummary": {
                "weeklyAvg": 45.2
            }
        }
        result = parse_hrv_data(data, "2024-01-15")
        assert result is not None
        assert result.weekly_avg == 45.2
        assert result.last_night_avg == 0.0

    def test_parse_no_hrv_summary(self):
        """测试没有hrvSummary的情况"""
        data = {"hrvReadings": []}
        result = parse_hrv_data(data, "2024-01-15")
        assert result is not None
        assert result.weekly_avg == 0.0


class TestParseSleepData:
    """睡眠数据解析测试"""

    def test_parse_valid_data(self):
        """测试解析有效数据（嵌套在dailySleepDTO中）"""
        data = {
            "dailySleepDTO": {
                "sleepStartTimestampGMT": 1705273200000,  # 2024-01-14 23:00:00
                "sleepEndTimestampGMT": 1705303800000,    # 2024-01-15 07:30:00
                "deepSleepSeconds": 7200,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 1800,
                "sleepScores": {
                    "overall": {
                        "value": 85
                    }
                }
            }
        }
        result = parse_sleep_data(data, "2024-01-15")
        assert result is not None
        assert result.date == "2024-01-15"
        assert result.total_sleep_s == 27000  # deep + light + rem
        assert result.deep_sleep_s == 7200
        assert result.light_sleep_s == 14400
        assert result.rem_sleep_s == 5400
        assert result.awake_s == 1800
        assert result.sleep_score == 85

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_sleep_data({}, "2024-01-15")
        assert result is None

    def test_parse_none_data(self):
        """测试解析None数据"""
        result = parse_sleep_data(None, "2024-01-15")
        assert result is None

    def test_parse_missing_seconds(self):
        """测试解析缺失秒数的数据"""
        data = {
            "dailySleepDTO": {
                "sleepScores": {
                    "overall": {"value": 85}
                }
            }
        }
        result = parse_sleep_data(data, "2024-01-15")
        assert result is not None
        assert result.total_sleep_s == 0
        assert result.deep_sleep_s == 0
        assert result.sleep_score == 85

    def test_parse_null_seconds(self):
        """测试解析null秒数的数据"""
        data = {
            "dailySleepDTO": {
                "deepSleepSeconds": None,
                "lightSleepSeconds": None,
                "remSleepSeconds": None,
                "awakeSleepSeconds": None,
                "sleepScores": {
                    "overall": {"value": None}
                }
            }
        }
        result = parse_sleep_data(data, "2024-01-15")
        assert result is not None
        assert result.total_sleep_s == 0
        assert result.sleep_score == 0

    def test_parse_no_daily_sleep_dto(self):
        """测试没有dailySleepDTO的情况"""
        data = {"sleepMovement": []}
        result = parse_sleep_data(data, "2024-01-15")
        assert result is not None
        assert result.total_sleep_s == 0


class TestParseWeightData:
    """体重数据解析测试"""

    def test_parse_valid_data(self):
        """测试解析有效数据"""
        data = {
            "dateWeightList": [
                {
                    "date": "2024-01-15",
                    "weight": 72500,  # 克
                    "bmi": 23.4,
                    "percentFat": 18.5,
                    "muscleMass": 32200,  # 克
                    "boneMass": 3100,  # 克
                    "percentHydration": 58.5
                }
            ]
        }
        result = parse_weight_data(data)
        assert len(result) == 1
        assert result[0].date == "2024-01-15"
        assert result[0].weight_kg == 72.5
        assert result[0].bmi == 23.4
        assert result[0].body_fat_pct == 18.5
        assert result[0].muscle_mass_kg == 32.2
        assert result[0].bone_mass_kg == 3.1
        assert result[0].body_water_pct == 58.5

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_weight_data({})
        assert len(result) == 0

    def test_parse_none_data(self):
        """测试解析None数据"""
        result = parse_weight_data(None)
        assert len(result) == 0

    def test_parse_empty_list(self):
        """测试解析空列表"""
        data = {"dateWeightList": []}
        result = parse_weight_data(data)
        assert len(result) == 0

    def test_parse_multiple_entries(self):
        """测试解析多条记录"""
        data = {
            "dateWeightList": [
                {"date": "2024-01-15", "weight": 72500},
                {"date": "2024-01-14", "weight": 72800}
            ]
        }
        result = parse_weight_data(data)
        assert len(result) == 2

    def test_parse_missing_weight_field(self):
        """测试解析缺失weight字段的数据"""
        data = {
            "dateWeightList": [
                {"date": "2024-01-15"}
            ]
        }
        result = parse_weight_data(data)
        assert len(result) == 1
        assert result[0].weight_kg == 0


class TestParseSpO2Data:
    """SpO2数据解析测试"""

    def test_parse_valid_data(self):
        """测试解析有效数据（使用正确的字段名）"""
        data = {
            "averageSpO2": 97.5,
            "lowestSpO2": 93.0
        }
        result = parse_spo2_data(data, "2024-01-15")
        assert result is not None
        assert result.date == "2024-01-15"
        assert result.avg_spo2 == 97.5
        assert result.min_spo2 == 93.0

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_spo2_data({}, "2024-01-15")
        assert result is None

    def test_parse_none_data(self):
        """测试解析None数据"""
        result = parse_spo2_data(None, "2024-01-15")
        assert result is None

    def test_parse_null_values(self):
        """测试解析null值"""
        data = {"averageSpO2": None, "lowestSpO2": None}
        result = parse_spo2_data(data, "2024-01-15")
        assert result is not None
        assert result.avg_spo2 == 0.0
        assert result.min_spo2 == 0.0

    def test_parse_partial_data(self):
        """测试解析部分数据"""
        data = {"averageSpO2": 97.5}
        result = parse_spo2_data(data, "2024-01-15")
        assert result is not None
        assert result.avg_spo2 == 97.5
        assert result.min_spo2 == 0.0
