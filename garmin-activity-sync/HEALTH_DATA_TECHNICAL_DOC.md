# Garmin 健康数据获取技术说明文档

## 目录

1. [整体架构](#1-整体架构)
2. [认证机制](#2-认证机制)
3. [API 端点详解](#3-api-端点详解)
4. [数据解析实现](#4-数据解析实现)
5. [数据模型定义](#5-数据模型定义)
6. [数据库存储](#6-数据库存储)
7. [同步流程编排](#7-同步流程编排)
8. [CLI 命令实现](#8-cli-命令实现)
9. [错误处理与重试机制](#9-错误处理与重试机制)
10. [测试策略](#10-测试策略)

---

## 1. 整体架构

### 1.1 数据流架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI 命令层 (main.py)                      │
│    init | sync | sync-health | import-fit | export | status     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     同步服务层 (core/sync_service.py)            │
│              sync_from_garmin() | sync_health_data()            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼───────┐   ┌───────▼───────┐   ┌───────▼───────┐
│  Garmin API   │   │  本地 FIT     │   │   数据库      │
│   客户端      │   │   解析器      │   │   存储层      │
│  (garmin/)    │   │ (local_fit/)  │   │   (core/)     │
└───────┬───────┘   └───────────────┘   └───────────────┘
        │
┌───────▼───────┐
│  Garmin       │
│  Connect      │
│  REST API     │
└───────────────┘
```

### 1.2 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI 层 | `main.py` | 命令行参数解析、用户交互 |
| 同步服务 | `core/sync_service.py` | 同步流程编排、错误处理 |
| API 客户端 | `garmin/client.py` | Garmin Connect 认证、API 调用 |
| 数据解析 | `garmin/health.py` | JSON 响应解析、数据转换 |
| 数据模型 | `core/models.py` | 数据结构定义 |
| 数据库 | `core/database.py` | SQLite CRUD 操作 |

---

## 2. 认证机制

### 2.1 garth 库

项目使用 `garth` 库进行 Garmin Connect 认证。garth 实现了 Garmin 的 SSO/OAuth 流程。

```python
# garmin/client.py:12-13
from garth.http import Client
```

### 2.2 认证流程

```python
# garmin/client.py:46-84
def login(self) -> bool:
    """登录 Garmin Connect"""
    try:
        # 1. 尝试恢复已保存的 session
        if self.session_dir.exists() and any(self.session_dir.iterdir()):
            self._client.load(str(self.session_dir))
            username = self._client.username
            return True
        
        # 2. 重新登录
        domain = "garmin.cn" if self.domain.upper() == "CN" else "garmin.com"
        self._client.configure(domain=domain)
        self._client.login(self.email, self.password)
        
        # 3. 保存 session 供下次使用
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._client.dump(str(self.session_dir))
        return True
    except Exception as e:
        logger.error(f"Garmin 登录失败: {e}")
        return False
```

### 2.3 Session 持久化

Session 数据保存在 `data/.garth/{email}/` 目录，包含 OAuth tokens：

```
data/.garth/your_garmin_email@example.com/
├── garth_user_info     # 用户信息
└── garth_tokens        # OAuth tokens (access_token, refresh_token)
```

### 2.4 API 调用

认证后的 API 调用通过 `garth.Client.connectapi()` 方法：

```python
# garmin/client.py:97-108
def get_activities(self, start: int = 0, limit: int = 20) -> list:
    url = "/activitylist-service/activities/search/activities"
    params = {"start": start, "limit": limit}
    activities = self._client.connectapi(url, params=params)
    return activities or []
```

---

## 3. API 端点详解

### 3.1 步数数据

**端点**: `/usersummary-service/stats/steps/daily/{startDate}/{endDate}`

**实现**: `garmin/client.py:223-245`

```python
def get_daily_steps(self, start_date: str, end_date: str) -> list:
    """获取每日步数数据"""
    try:
        url = f"/usersummary-service/stats/steps/daily/{start_date}/{end_date}"
        data = self._client.connectapi(url)
        return data or []
    except Exception as e:
        logger.error(f"获取步数数据失败: {e}")
        return []
```

**API 响应示例**:
```json
[
    {
        "calendarDate": "2026-05-29",
        "totalSteps": 21440,
        "totalDistance": 18871,
        "activeKilocalories": 0,
        "floorsAscended": 0
    }
]
```

### 3.2 心率数据

**端点**: `/wellness-service/wellness/dailyHeartRate`

**实现**: `garmin/client.py:247-268`

```python
def get_heart_rates(self, cdate: str) -> Optional[dict]:
    """获取指定日期的心率数据"""
    try:
        url = "/wellness-service/wellness/dailyHeartRate"
        params = {"date": cdate}
        data = self._client.connectapi(url, params=params)
        return data
    except Exception as e:
        logger.error(f"获取心率数据失败 {cdate}: {e}")
        return None
```

**API 响应示例**:
```json
{
    "userProfilePK": 12575260,
    "calendarDate": "2026-05-29",
    "restingHeartRate": 54,
    "maxHeartRate": 167,
    "minHeartRate": 50,
    "heartRateValues": [
        [1779985200000, null],
        [1779985320000, 73],
        [1779985440000, 60]
        // ... 每20秒一个采样点
    ]
}
```

**关键字段**:
- `restingHeartRate`: 静息心率
- `maxHeartRate`: 最大心率
- `minHeartRate`: 最小心率
- `heartRateValues`: 心率数组，每个元素为 `[时间戳, 心率值]`，心率值可能为 `null`

### 3.3 HRV 数据

**端点**: `/hrv-service/hrv/{date}`

**实现**: `garmin/client.py:290-305`

```python
def get_hrv_data(self, cdate: str) -> Optional[dict]:
    """获取指定日期的HRV数据"""
    try:
        url = f"/hrv-service/hrv/{cdate}"
        data = self._client.connectapi(url)
        return data
    except Exception as e:
        logger.error(f"获取HRV数据失败 {cdate}: {e}")
        return None
```

**API 响应示例**:
```json
{
    "userProfilePk": 12575260,
    "hrvSummary": {
        "calendarDate": "2026-05-29",
        "weeklyAvg": 55,
        "lastNightAvg": 50,
        "lastNight5MinHigh": 81,
        "baseline": {
            "lowUpper": 36,
            "balancedLow": 39,
            "balancedUpper": 55,
            "markerValue": 0.75
        },
        "status": "BALANCED"
    },
    "hrvReadings": [
        {
            "hrvValue": 30,
            "readingTimeGMT": "2026-05-28T16:41:25.0",
            "readingTimeLocal": "2026-05-29T00:41:25.0"
        }
        // ... 每5分钟一个采样点
    ]
}
```

**关键字段**:
- `hrvSummary.weeklyAvg`: 7天平均 HRV（ms）
- `hrvSummary.lastNightAvg`: 昨晚平均 HRV（ms）
- `hrvSummary.lastNight5MinHigh`: 昨晚5分钟最高 HRV（ms）
- `hrvSummary.status`: 状态（BALANCED/UNBALANCED/POOR/LOW）

### 3.4 睡眠数据

**端点**: `/wellness-service/wellness/dailySleepData`

**实现**: `garmin/client.py:307-325`

```python
def get_sleep_data(self, cdate: str) -> Optional[dict]:
    """获取指定日期的睡眠数据"""
    try:
        url = "/wellness-service/wellness/dailySleepData"
        params = {"date": cdate, "nonSleepBufferMinutes": 60}
        data = self._client.connectapi(url, params=params)
        return data
    except Exception as e:
        logger.error(f"获取睡眠数据失败 {cdate}: {e}")
        return None
```

**API 响应示例**:
```json
{
    "dailySleepDTO": {
        "calendarDate": "2026-05-29",
        "sleepStartTimestampGMT": 1779986205000,
        "sleepEndTimestampGMT": 1780009185000,
        "deepSleepSeconds": 9180,
        "lightSleepSeconds": 10260,
        "remSleepSeconds": 3060,
        "awakeSleepSeconds": 480,
        "sleepScores": {
            "overall": {
                "value": 75,
                "qualifierKey": "FAIR"
            },
            "deepPercentage": {
                "value": 41,
                "qualifierKey": "EXCELLENT"
            }
        }
    },
    "sleepMovement": [...],
    "sleepHeartRate": {...},
    "sleepStress": {...}
}
```

**关键字段**:
- `dailySleepDTO.deepSleepSeconds`: 深睡时长（秒）
- `dailySleepDTO.lightSleepSeconds`: 浅睡时长（秒）
- `dailySleepDTO.remSleepSeconds`: REM 睡眠时长（秒）
- `dailySleepDTO.awakeSleepSeconds`: 清醒时长（秒）
- `dailySleepDTO.sleepScores.overall.value`: 睡眠得分（0-100）

### 3.5 体重数据

**端点**: `/weight-service/weight/dateRange`

**实现**: `garmin/client.py:327-345`

```python
def get_body_composition(self, start_date: str, end_date: str) -> Optional[dict]:
    """获取体重/身体成分数据"""
    try:
        url = "/weight-service/weight/dateRange"
        params = {"startDate": start_date, "endDate": end_date}
        data = self._client.connectapi(url, params=params)
        return data
    except Exception as e:
        logger.error(f"获取身体成分数据失败: {e}")
        return None
```

**API 响应示例**:
```json
{
    "dateWeightList": [
        {
            "date": "2026-05-29",
            "weight": 72500,
            "bmi": 23.4,
            "percentFat": 18.5,
            "muscleMass": 32200,
            "boneMass": 3100,
            "percentHydration": 58.5
        }
    ]
}
```

**注意**: 体重和肌肉量单位为**克**，需要除以 1000 转换为千克。

### 3.6 SpO2 数据

**端点**: `/wellness-service/wellness/daily/spo2/{date}`

**实现**: `garmin/client.py:347-365`

```python
def get_spo2_data(self, cdate: str) -> Optional[dict]:
    """获取指定日期的SpO2数据"""
    try:
        url = f"/wellness-service/wellness/daily/spo2/{cdate}"
        data = self._client.connectapi(url)
        return data
    except Exception as e:
        logger.error(f"获取SpO2数据失败 {cdate}: {e}")
        return None
```

**API 响应示例**:
```json
{
    "calendarDate": "2026-05-29",
    "averageSpO2": 96.0,
    "lowestSpO2": 79,
    "latestSpO2": 94,
    "lastSevenDaysAvgSpO2": 95.57,
    "spO2HourlyAverages": [
        [1779984000000, 88],
        [1779987600000, 96]
    ]
}
```

**关键字段**:
- `averageSpO2`: 平均血氧（%）
- `lowestSpO2`: 最低血氧（%）

---

## 4. 数据解析实现

### 4.1 解析模块

所有解析函数位于 `garmin/health.py`，负责将 API 返回的 JSON 转换为数据模型对象。

### 4.2 步数解析

```python
# garmin/health.py:16-43
def parse_daily_steps(data: List[Dict[str, Any]], source: str = "garmin_connect") -> List[DailySteps]:
    """解析每日步数数据"""
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
```

### 4.3 心率解析（含平均心率计算）

```python
# garmin/health.py:46-87
def parse_heart_rate_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[HeartRateData]:
    """解析心率数据"""
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
```

**关键逻辑**:
- `heartRateValues` 是二维数组，每个元素为 `[timestamp, heart_rate]`
- 需要过滤掉 `heart_rate` 为 `null` 的采样点
- 计算公式：`avg_hr = sum(valid_values) / len(valid_values)`

### 4.4 HRV 解析（嵌套结构处理）

```python
# garmin/health.py:90-128
def parse_hrv_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[HRVData]:
    """解析HRV数据"""
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
```

**关键逻辑**:
- API 返回的数据是嵌套结构，HRV 摘要在 `hrvSummary` 对象中
- `hrvReadings` 包含每5分钟的 HRV 采样数据（当前未使用）

### 4.5 睡眠解析（多层嵌套处理）

```python
# garmin/health.py:131-200
def parse_sleep_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[SleepData]:
    """解析睡眠数据"""
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
```

**关键逻辑**:
- 睡眠数据有三层嵌套：`data` → `dailySleepDTO` → `sleepScores` → `overall`
- 时间戳是 GMT 毫秒级，需要除以 1000 转换为秒
- 总睡眠时长 = 深睡 + 浅睡 + REM（不含清醒时间）

### 4.6 体重解析

```python
# garmin/health.py:203-244
def parse_weight_data(data: Dict[str, Any], source: str = "garmin_connect") -> List[WeightData]:
    """解析体重数据"""
    results = []
    try:
        if not data:
            return results

        date_weight_list = data.get("dateWeightList", [])
        if not date_weight_list:
            return results

        for item in date_weight_list:
            try:
                date_str = item.get("date", "")
                weight = WeightData(
                    date=date_str,
                    weight_kg=item.get("weight", 0) / 1000 if item.get("weight") else 0,
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
```

**关键逻辑**:
- 体重、肌肉量、骨量单位为**克**，需要 `/1000` 转换为千克
- 返回列表是因为一次 API 调用可能返回多天的数据

### 4.7 SpO2 解析

```python
# garmin/health.py:247-280
def parse_spo2_data(data: Dict[str, Any], cdate: str, source: str = "garmin_connect") -> Optional[SpO2Data]:
    """解析SpO2数据"""
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
```

**关键逻辑**:
- 字段名是 `averageSpO2` 和 `lowestSpO2`（不是 `avgSpo2`）
- 使用 `or 0` 处理 `None` 值

---

## 5. 数据模型定义

### 5.1 模型文件

所有数据模型定义在 `core/models.py`，使用 Python `dataclass`。

### 5.2 健康数据模型

```python
# core/models.py:117-230

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

@dataclass
class HRVData:
    """HRV（心率变异性）数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    weekly_avg: float = 0.0        # 7天平均HRV（ms）
    last_night_avg: float = 0.0    # 昨晚平均HRV（ms）
    last_night_5min_high: float = 0.0  # 昨晚5分钟最高HRV（ms）
    status: str = ""               # HRV状态
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None

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

@dataclass
class SpO2Data:
    """SpO2（血氧饱和度）数据模型"""
    date: str                      # 日期（YYYY-MM-DD）
    avg_spo2: float = 0.0          # 平均血氧（%）
    min_spo2: float = 0.0          # 最低血氧（%）
    source: str = "garmin_connect"
    created_at: Optional[datetime] = None
```

### 5.3 模型方法

每个模型都有 `to_dict()` 方法用于序列化：

```python
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
```

---

## 6. 数据库存储

### 6.1 数据库表结构

健康数据表定义在 `core/database.py:59-120`：

```sql
-- 步数表
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

-- 心率表
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

-- HRV表
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

-- 睡眠表
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

-- 体重表
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

-- SpO2表
CREATE TABLE IF NOT EXISTS spo2_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    avg_spo2 REAL DEFAULT 0,
    min_spo2 REAL DEFAULT 0,
    source TEXT DEFAULT 'garmin_connect',
    created_at TEXT DEFAULT '',
    synced_at TEXT DEFAULT ''
);
```

### 6.2 去重更新策略

使用 SQLite 的 `ON CONFLICT DO UPDATE` 实现 upsert：

```python
# core/database.py:370-420
def insert_daily_steps(self, steps: DailySteps) -> bool:
    """插入每日步数数据（按日期去重，存在则更新）"""
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
```

### 6.3 查询方法

```python
# core/database.py:550-650
def get_daily_steps_by_date_range(self, start_date: str, end_date: str) -> List[dict]:
    """按日期范围查询步数数据"""
    conn = self._get_conn()
    cursor = conn.execute("""
        SELECT * FROM daily_steps
        WHERE date >= ? AND date <= ?
        ORDER BY date DESC
    """, (start_date, end_date))
    return [dict(row) for row in cursor.fetchall()]

def get_latest_health_data(self) -> dict:
    """获取最新的健康数据摘要"""
    conn = self._get_conn()
    result = {}

    for table, key in [
        ('daily_steps', 'steps'),
        ('heart_rate_data', 'heart_rate'),
        ('hrv_data', 'hrv'),
        ('sleep_data', 'sleep'),
        ('weight_data', 'weight'),
        ('spo2_data', 'spo2')
    ]:
        cursor = conn.execute(f"SELECT * FROM {table} ORDER BY date DESC LIMIT 1")
        row = cursor.fetchone()
        result[key] = dict(row) if row else None

    return result
```

---

## 7. 同步流程编排

### 7.1 主同步函数

同步逻辑在 `core/sync_service.py:190-320`：

```python
def sync_health_data(
    days: int,
    config: dict,
    data_types: list[str] = None
) -> dict:
    """从 Garmin Connect 同步健康数据"""
    
    # 默认同步所有类型
    if data_types is None:
        data_types = ['steps', 'heart_rate', 'hrv', 'sleep', 'weight', 'spo2']

    # 1. 验证配置
    garmin_config = config.get("garmin", {})
    email = garmin_config.get("email", "")
    password = garmin_config.get("password", "")
    domain = garmin_config.get("domain", "CN")

    # 2. 初始化数据库
    db = Database(db_path)
    db.init_db()

    # 3. 登录 Garmin Connect
    client = GarminConnectClient(email, password, domain)
    client.login()

    # 4. 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    synced = {}

    # 5. 同步各类数据
    if 'steps' in data_types:
        # 步数：一次 API 调用获取整个日期范围
        steps_data = client.get_daily_steps(start_str, end_str)
        steps_list = parse_daily_steps(steps_data)
        count = db.insert_daily_steps_batch(steps_list)
        synced['steps'] = count

    if 'heart_rate' in data_types:
        # 心率：需要逐天获取
        hr_count = 0
        current = start_date
        while current <= end_date:
            cdate = current.strftime("%Y-%m-%d")
            hr_data = client.get_heart_rates(cdate)
            if hr_data:
                hr = parse_heart_rate_data(hr_data, cdate)
                if hr and db.insert_heart_rate(hr):
                    hr_count += 1
            current += timedelta(days=1)
        synced['heart_rate'] = hr_count

    # HRV、睡眠、SpO2 同理，需要逐天获取
    # 体重可以一次获取整个范围

    return {"success": True, "synced": synced}
```

### 7.2 同步策略差异

| 数据类型 | API 调用方式 | 原因 |
|---------|-------------|------|
| 步数 | 一次获取范围 | API 支持日期范围参数 |
| 心率 | 逐天获取 | API 只支持单日参数 |
| HRV | 逐天获取 | API 只支持单日参数 |
| 睡眠 | 逐天获取 | API 只支持单日参数 |
| 体重 | 一次获取范围 | API 支持日期范围参数 |
| SpO2 | 逐天获取 | API 只支持单日参数 |

---

## 8. CLI 命令实现

### 8.1 命令注册

```python
# main.py:209-270
def main():
    parser = argparse.ArgumentParser(description="Garmin 运动数据本地同步工具")
    
    # sync-health 命令
    health_parser = subparsers.add_parser("sync-health", help="从 Garmin Connect 同步健康数据")
    health_parser.add_argument("--days", type=int, default=7, help="同步最近多少天的数据")
    health_parser.add_argument("--types", type=str, help="要同步的数据类型，逗号分隔")

    # status 命令添加 --health 参数
    status_parser = subparsers.add_parser("status", help="查看同步状态")
    status_parser.add_argument("--health", action="store_true", help="显示健康数据状态")
```

### 8.2 同步命令实现

```python
# main.py:190-250
def cmd_sync_health(args):
    """从 Garmin Connect 同步健康数据"""
    config = ConfigManager(args.config).load()
    
    # 解析数据类型
    data_types = None
    if args.types:
        data_types = [t.strip() for t in args.types.split(',')]

    # 执行同步
    result = sync_health_data(args.days, config, data_types)

    # 输出结果
    synced = result.get("synced", {})
    for data_type, count in synced.items():
        print(f"  {data_type}: {count} 条")
```

### 8.3 状态命令实现

```python
# main.py:150-190
def cmd_status(args):
    """显示同步状态"""
    if args.health:
        health_status = get_health_status(config)
        counts = health_status.get("counts", {})
        latest = health_status.get("latest", {})

        print(f"健康数据统计:")
        print(f"  步数记录: {counts.get('daily_steps', 0)} 条")
        print(f"  心率记录: {counts.get('heart_rate_data', 0)} 条")
        # ...
```

---

## 9. 错误处理与重试机制

### 9.1 错误处理策略

```python
# garmin/health.py - 每个解析函数都有 try-except
def parse_hrv_data(data, cdate, source):
    try:
        # 解析逻辑
        return hrv_data
    except Exception as e:
        logger.warning(f"解析HRV数据失败: {e}, date={cdate}")
        return None  # 返回 None 而不是抛出异常
```

### 9.2 同步错误处理

```python
# core/sync_service.py:280-310
errors = []

if 'hrv' in data_types:
    try:
        # 同步逻辑
    except Exception as e:
        errors.append(f"HRV同步失败: {e}")
        synced['hrv'] = 0

return {
    "success": len(errors) == 0,
    "synced": synced,
    "errors": errors if errors else None
}
```

### 9.3 日志记录

```python
import logging
logger = logging.getLogger(__name__)

# 日志配置在 utils/logger.py
# 日志文件：logs/sync.log（按日期滚动）
```

---

## 10. 测试策略

### 10.1 测试文件结构

```
tests/
├── __init__.py
├── test_models.py      # 数据模型测试 (18 tests)
├── test_health.py      # 健康数据解析测试 (32 tests)
└── test_database.py    # 数据库操作测试 (20 tests)
```

### 10.2 解析函数测试示例

```python
# tests/test_health.py:119-135
class TestParseHRVData:
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
        assert result.weekly_avg == 45.2
        assert result.last_night_avg == 48.5
        assert result.status == "BALANCED"

    def test_parse_empty_data(self):
        """测试解析空数据"""
        result = parse_hrv_data({}, "2024-01-15")
        assert result is None
```

### 10.3 数据库测试示例

```python
# tests/test_database.py:25-40
class TestDailyStepsDB:
    def test_insert_and_retrieve(self, db):
        """测试插入和查询步数数据"""
        steps = DailySteps(date="2024-01-15", steps=8500, distance_m=6200.5)
        db.insert_daily_steps(steps)

        data = db.get_daily_steps_by_date_range("2024-01-15", "2024-01-15")
        assert len(data) == 1
        assert data[0]["steps"] == 8500

    def test_insert_duplicate_updates(self, db):
        """测试插入重复日期会更新数据"""
        db.insert_daily_steps(DailySteps(date="2024-01-15", steps=8000))
        db.insert_daily_steps(DailySteps(date="2024-01-15", steps=9000))

        data = db.get_daily_steps_by_date_range("2024-01-15", "2024-01-15")
        assert data[0]["steps"] == 9000  # 应该是更新后的值
```

### 10.4 运行测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行带覆盖率的测试
python -m pytest tests/ -v --cov=. --cov-report=term-missing

# 运行特定测试文件
python -m pytest tests/test_health.py -v
```

---

## 附录 A: 依赖库

| 库 | 版本 | 用途 |
|---|------|------|
| garth | >= 0.5.0 | Garmin Connect 认证 |
| fit-tool | >= 0.1.0 | FIT 文件解析 |
| requests | >= 2.28.0 | HTTP 请求 |
| pytest | >= 7.0.0 | 测试框架 |
| pytest-cov | >= 4.0.0 | 测试覆盖率 |

## 附录 B: 相关资源

- [Garmin Connect API](https://connect.garmin.com/)
- [garth 库文档](https://github.com/cyberjunky/python-garminconnect)
- [GarminDB 项目](https://github.com/tcgoetz/GarminDB)
- [FIT 协议规范](https://developer.garmin.com/fit/protocol/)
