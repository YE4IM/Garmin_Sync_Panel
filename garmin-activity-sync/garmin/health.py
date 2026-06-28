"""
健康数据解析模块
处理从 Garmin Connect 获取的健康数据（步数、心率、HRV、睡眠、体重、SpO2）
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.models import (
    DailySteps, HeartRateData, HRVData, SleepData, WeightData, SpO2Data
)

logger = logging.getLogger(__name__)


def parse_daily_steps(data: List[Dict[str, Any]], source: str = "garmin_connect") -> List[DailySteps]:
    """
    解析每日步数数据

    Args:
        data: API返回的步数数据列表
        source: 数据来源

    Returns:
        DailySteps对象列表
    """
    results = []
    for item in data:
        try:
            steps = DailySteps(
                date=item.get("calendarDate", ""),
                steps=item.get("totalSteps", 0),
                distance_m=item.get("totalDistance", 0),
                calories=item.get("activeKilocalories", 0),
                floors_climbed=item.get("floorsAscended", 0),
                source=source,
                created_at=datetime.now()
            )
            if steps.date:
                results.append(steps)
        except Exception as e:
            logger.warning(f"解析步数数据失败: {e}, data={item}")
    return results


def parse_daily_steps_from_summary(data: Dict[str, Any], cdate: str, source: str = "garmin_daily_summary") -> Optional[DailySteps]:
    """
    从每日汇总接口解析步数数据。
    """
    try:
        if not data:
            return None
        steps = DailySteps(
            date=data.get("calendarDate") or cdate,
            steps=data.get("totalSteps", 0) or 0,
            distance_m=data.get("totalDistanceMeters", 0) or data.get("totalDistance", 0) or 0,
            calories=data.get("activeKilocalories", 0) or 0,
            floors_climbed=data.get("floorsAscended", 0) or 0,
            source=source,
            created_at=datetime.now()
        )
        return steps if steps.date else None
    except Exception as e:
        logger.warning(f"解析每日汇总步数失败: {e}, date={cdate}")
        return None


def parse_heart_rate_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[HeartRateData]:
    """
    解析心率数据

    Args:
        data: API返回的心率数据
        cdate: 日期
        source: 数据来源

    Returns:
        HeartRateData对象
    """
    try:
        if not data:
            return None

        # 计算平均心率：从 heartRateValues 数组过滤 null 后求平均
        avg_hr = 0
        hr_values = data.get("heartRateValues", [])
        if hr_values:
            valid_values = [v[1] for v in hr_values if v and len(v) > 1 and v[1] is not None]
            if valid_values:
                avg_hr = round(sum(valid_values) / len(valid_values))

        hr_data = HeartRateData(
            date=cdate,
            resting_hr=data.get("restingHeartRate", 0),
            max_hr=data.get("maxHeartRate", 0),
            min_hr=data.get("minHeartRate", 0),
            avg_hr=avg_hr,
            source=source,
            created_at=datetime.now()
        )
        return hr_data
    except Exception as e:
        logger.warning(f"解析心率数据失败: {e}, date={cdate}")
        return None


def parse_hrv_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[HRVData]:
    """
    解析HRV数据

    API返回结构：
    {
        "hrvSummary": {
            "weeklyAvg": 55,
            "lastNightAvg": 50,
            "lastNight5MinHigh": 81,
            "status": "BALANCED"
        },
        "hrvReadings": [...]
    }

    Args:
        data: API返回的HRV数据
        cdate: 日期
        source: 数据来源

    Returns:
        HRVData对象
    """
    try:
        if not data:
            return None

        # HRV数据嵌套在 hrvSummary 中
        hrv_summary = data.get("hrvSummary", {})

        hrv_data = HRVData(
            date=cdate,
            weekly_avg=hrv_summary.get("weeklyAvg", 0),
            last_night_avg=hrv_summary.get("lastNightAvg", 0),
            last_night_5min_high=hrv_summary.get("lastNight5MinHigh", 0),
            status=hrv_summary.get("status", ""),
            source=source,
            created_at=datetime.now()
        )
        return hrv_data
    except Exception as e:
        logger.warning(f"解析HRV数据失败: {e}, date={cdate}")
        return None


def parse_sleep_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[SleepData]:
    """
    解析睡眠数据

    API返回结构：
    {
        "dailySleepDTO": {
            "sleepStartTimestampGMT": 1779986205000,
            "sleepEndTimestampGMT": 1780009185000,
            "deepSleepSeconds": 9180,
            "lightSleepSeconds": 10260,
            "remSleepSeconds": 3060,
            "awakeSleepSeconds": 480,
            "sleepScores": {
                "overall": {"value": 75}
            }
        }
    }

    Args:
        data: API返回的睡眠数据
        cdate: 日期
        source: 数据来源

    Returns:
        SleepData对象
    """
    try:
        if not data:
            return None

        # 睡眠数据嵌套在 dailySleepDTO 中
        dto = data.get("dailySleepDTO", {})

        # 解析睡眠时间（GMT毫秒时间戳）
        sleep_start = None
        sleep_end = None
        if dto.get("sleepStartTimestampGMT"):
            try:
                sleep_start = datetime.fromtimestamp(dto["sleepStartTimestampGMT"] / 1000)
            except Exception:
                pass
        if dto.get("sleepEndTimestampGMT"):
            try:
                sleep_end = datetime.fromtimestamp(dto["sleepEndTimestampGMT"] / 1000)
            except Exception:
                pass

        # 各睡眠阶段时长（秒）
        deep_sleep_s = dto.get("deepSleepSeconds", 0) or 0
        light_sleep_s = dto.get("lightSleepSeconds", 0) or 0
        rem_sleep_s = dto.get("remSleepSeconds", 0) or 0
        awake_s = dto.get("awakeSleepSeconds", 0) or 0
        total_sleep_s = deep_sleep_s + light_sleep_s + rem_sleep_s

        # 睡眠得分在 sleepScores.overall.value
        sleep_scores = dto.get("sleepScores", {})
        overall_score = sleep_scores.get("overall", {})
        sleep_score = overall_score.get("value", 0) or 0

        sleep_data = SleepData(
            date=cdate,
            sleep_start=sleep_start,
            sleep_end=sleep_end,
            total_sleep_s=total_sleep_s,
            deep_sleep_s=deep_sleep_s,
            light_sleep_s=light_sleep_s,
            rem_sleep_s=rem_sleep_s,
            awake_s=awake_s,
            sleep_score=sleep_score,
            source=source,
            created_at=datetime.now()
        )
        return sleep_data
    except Exception as e:
        logger.warning(f"解析睡眠数据失败: {e}, date={cdate}")
        return None


def parse_weight_data(data: Dict[str, Any], source: str = "garmin_connect") -> List[WeightData]:
    """
    解析体重数据

    Args:
        data: API返回的体重数据
        source: 数据来源

    Returns:
        WeightData对象列表
    """
    results = []
    try:
        if not data:
            return results

        # 体重数据可能包含多个日期的记录
        date_weight_list = data.get("dateWeightList", [])
        if not date_weight_list:
            return results

        for item in date_weight_list:
            try:
                # 提取日期
                date_str = item.get("date", "")
                if isinstance(date_str, (int, float)) or (isinstance(date_str, str) and date_str.isdigit()):
                    try:
                        date_str = datetime.fromtimestamp(float(date_str) / 1000).strftime("%Y-%m-%d")
                    except Exception:
                        date_str = ""
                if not date_str:
                    # 尝试从GMT时间戳解析
                    gmt_ts = item.get("samplePk", {}).get("gmtTimestamp", 0)
                    if gmt_ts:
                        date_str = datetime.fromtimestamp(gmt_ts / 1000).strftime("%Y-%m-%d")

                weight = WeightData(
                    date=date_str,
                    weight_kg=item.get("weight", 0) / 1000 if item.get("weight") else 0,  # 克转千克
                    bmi=item.get("bmi", 0),
                    body_fat_pct=item.get("percentFat", 0),
                    muscle_mass_kg=item.get("muscleMass", 0) / 1000 if item.get("muscleMass") else 0,
                    bone_mass_kg=item.get("boneMass", 0) / 1000 if item.get("boneMass") else 0,
                    body_water_pct=item.get("percentHydration", 0),
                    source=source,
                    created_at=datetime.now()
                )
                if weight.date:
                    results.append(weight)
            except Exception as e:
                logger.warning(f"解析单个体重记录失败: {e}")
    except Exception as e:
        logger.warning(f"解析体重数据失败: {e}")
    return results


def parse_spo2_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[SpO2Data]:
    """
    解析SpO2数据

    API返回结构：
    {
        "averageSpO2": 96.0,
        "lowestSpO2": 79,
        "latestSpO2": 94
    }

    Args:
        data: API返回的SpO2数据
        cdate: 日期
        source: 数据来源

    Returns:
        SpO2Data对象
    """
    try:
        if not data:
            return None

        spo2_data = SpO2Data(
            date=cdate,
            avg_spo2=data.get("averageSpO2", 0) or 0,
            min_spo2=data.get("lowestSpO2", 0) or 0,
            source=source,
            created_at=datetime.now()
        )
        return spo2_data
    except Exception as e:
        logger.warning(f"解析SpO2数据失败: {e}, date={cdate}")
        return None
