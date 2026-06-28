# Garmin 运动数据本地同步工具

Garmin 运动数据本地同步工具，用于从 Garmin Connect 或本地 FIT 文件同步运动活动数据和健康数据，解析并存储到 SQLite，导出 JSON 供 PiDesk 桌面中枢使用。

## 功能特性

- 从 Garmin Connect 获取活动列表、活动详情和原始 FIT 文件
- 从本地 Garmin 手表导出的 `GARMIN/ACTIVITY/*.FIT` 文件导入
- 解析运动记录（跑步、骑行、步行等），兼容字段缺失
- **健康数据同步**：步数、心率、HRV、睡眠、体重、SpO2
- 使用 SQLite 保存运动数据，按 activity_id 自动去重
- 导出 PiDesk 可读取的 JSON 摘要文件（最近运动、本周/本月统计）
- 记录同步日志，支持按日期滚动

## 支持的健康数据

| 数据类型 | 说明 | API 端点 |
|---------|------|----------|
| 步数 | 每日步数、距离、卡路里、爬楼 | `/usersummary-service/stats/steps/daily` |
| 心率 | 静息心率、最大/最小心率、平均心率 | `/wellness-service/wellness/dailyHeartRate` |
| HRV | 7天平均、昨晚平均、状态 | `/hrv-service/hrv/{date}` |
| 睡眠 | 总时长、深睡/浅睡/REM、睡眠得分 | `/wellness-service/wellness/dailySleepData` |
| 体重 | 体重、BMI、体脂率、肌肉量 | `/weight-service/weight/dateRange` |
| SpO2 | 平均血氧、最低血氧 | `/wellness-service/wellness/daily/spo2` |

## 项目结构

```
garmin-activity-sync/
├── main.py                        # CLI 入口
├── config.example.json            # 配置示例
├── config.json                    # 真实配置（不提交 Git）
├── requirements.txt               # 依赖
├── core/                          # 核心模块
│   ├── config.py                  # 配置管理
│   ├── models.py                  # 数据模型（含健康数据模型）
│   ├── database.py                # SQLite 操作（含健康数据表）
│   ├── sync_service.py            # 同步编排（含健康数据同步）
│   └── exporter.py                # JSON 导出
├── garmin/                        # Garmin Connect 模块
│   ├── client.py                  # 登录与 API（含健康数据 API）
│   ├── activity.py                # 活动获取
│   ├── health.py                  # 健康数据解析
│   └── fit_parser.py              # FIT 文件解析
├── local_fit/                     # 本地 FIT 导入
│   └── importer.py                # 扫描与导入
├── utils/                         # 工具模块
│   ├── logger.py                  # 日志配置
│   ├── time_utils.py              # 时间工具
│   └── path_utils.py              # 路径工具
├── tests/                         # 单元测试
│   ├── test_models.py             # 数据模型测试
│   ├── test_health.py             # 健康数据解析测试
│   └── test_database.py           # 数据库操作测试
├── data/                          # 数据目录（不提交 Git）
│   ├── garmin_activity.db         # SQLite 数据库
│   ├── fit_files/                 # FIT 文件
│   └── exports/                   # 导出 JSON
└── logs/                          # 日志目录（不提交 Git）
```

## 安装

### 1. 安装 Python

确保已安装 Python 3.10+（推荐 3.12）。

```bash
python --version
```

### 2. 创建虚拟环境

```bash
cd garmin-activity-sync
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

## 配置

复制配置示例并填入您的 Garmin 账号信息：

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "garmin": {
    "email": "your_garmin_email@example.com",
    "password": "your_garmin_password",
    "domain": "CN"
  },
  "data_dir": "data",
  "log_dir": "logs",
  "fit_download_dir": "data/fit_files",
  "export_dir": "data/exports"
}
```

**配置说明：**

| 字段 | 说明 |
|------|------|
| `garmin.email` | Garmin Connect 邮箱 |
| `garmin.password` | Garmin Connect 密码 |
| `garmin.domain` | 服务器区域：`CN`（中国）或 `COM`（国际） |
| `data_dir` | 数据目录路径 |
| `log_dir` | 日志目录路径 |
| `fit_download_dir` | FIT 文件下载目录 |
| `export_dir` | JSON 导出目录 |

## 使用方法

### 初始化

```bash
python main.py init
```

创建数据库和目录结构。

### 本地 FIT 文件导入

从 Garmin 手表导出的 FIT 文件导入：

```bash
python main.py import-fit --dir /path/to/GARMIN/ACTIVITY
```

导入后自动导出 JSON：

```bash
python main.py import-fit --dir /path/to/GARMIN/ACTIVITY --export
```

### Garmin Connect 同步

从 Garmin Connect 同步最近 30 天的活动：

```bash
python main.py sync --days 30
```

同步并自动导出 JSON：

```bash
python main.py sync --days 30 --export
```

### 健康数据同步

从 Garmin Connect 同步健康数据（步数、心率、HRV、睡眠、SpO2）：

```bash
# 同步最近 7 天的所有健康数据
python main.py sync-health --days 7

# 同步最近 30 天的健康数据
python main.py sync-health --days 30

# 只同步指定类型的数据
python main.py sync-health --days 7 --types steps,sleep,hrv

# 支持的数据类型：steps, heart_rate, hrv, sleep, weight, spo2
```

查看健康数据状态：

```bash
python main.py status --health
```

输出示例：
```
健康数据统计:
  步数记录: 8 条
  心率记录: 8 条
  HRV记录: 8 条
  睡眠记录: 8 条
  体重记录: 0 条
  SpO2记录: 8 条

最新步数 (2026-05-30):
  步数: 2397
  距离: 1.9 km

最新心率 (2026-05-30):
  静息心率: 52 bpm
  平均心率: 62 bpm

最新HRV (2026-05-30):
  7天平均: 53.0 ms
  昨晚平均: 52.0 ms
  状态: BALANCED

最新睡眠 (2026-05-30):
  总时长: 6.3 小时
  睡眠得分: 78

最新SpO2 (2026-05-30):
  平均血氧: 97.0%
```

### 导出 PiDesk JSON

```bash
python main.py export
```

导出文件位置：`data/exports/pidesk_activity_summary.json`

### 查看同步状态

```bash
python main.py status
```

显示总活动数、最近运动、本周/本月统计、运动类型分布。

## PiDesk JSON 格式

导出的 JSON 文件格式：

```json
{
  "last_activity": {
    "name": "Running 2026-05-27 07:30",
    "sport_type": "running",
    "start_time": "2026-05-27T07:30:00",
    "distance_km": 5.23,
    "duration_min": 28.5,
    "avg_pace": "5:27",
    "avg_hr": 152,
    "max_hr": 178,
    "calories": 420,
    "elevation_gain_m": 35.0
  },
  "weekly_stats": {
    "total_activities": 3,
    "total_distance_km": 15.6,
    "total_duration_min": 85.2,
    "total_calories": 1260
  },
  "monthly_stats": {
    "total_activities": 12,
    "total_distance_km": 62.4,
    "total_duration_min": 340.8,
    "total_calories": 5040
  },
  "last_sync_time": "2026-05-27T10:00:00",
  "sync_status": "success"
}
```

## 树莓派定时运行

### 使用 crontab

```bash
# 编辑 crontab
crontab -e

# 每天凌晨 2 点同步活动并导出
0 2 * * * cd /path/to/garmin-activity-sync && .venv/bin/python main.py sync --days 7 --export >> logs/cron.log 2>&1

# 每天凌晨 3 点同步健康数据
0 3 * * * cd /path/to/garmin-activity-sync && .venv/bin/python main.py sync-health --days 7 >> logs/cron.log 2>&1
```

### 使用 systemd

创建 `/etc/systemd/system/garmin-sync.service`：

```ini
[Unit]
Description=Garmin Activity Sync
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/garmin-activity-sync
ExecStart=/path/to/garmin-activity-sync/.venv/bin/python main.py sync --days 7 --export
User=pi
Group=pi

[Install]
WantedBy=multi-user.target
```

创建 `/etc/systemd/system/garmin-sync.timer`：

```ini
[Unit]
Description=Run Garmin sync daily

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

启用定时器：

```bash
sudo systemctl enable garmin-sync.timer
sudo systemctl start garmin-sync.timer
```

查看状态：

```bash
sudo systemctl status garmin-sync.timer
journalctl -u garmin-sync.service
```

## SQLite 数据库

数据库文件位于 `data/garmin_activity.db`，包含以下表：

### activities 表

| 字段 | 类型 | 说明 |
|------|------|------|
| activity_id | TEXT | 活动 ID（主键） |
| name | TEXT | 活动名称 |
| sport_type | TEXT | 运动类型 |
| start_time | TEXT | 开始时间 |
| distance_m | REAL | 距离（米） |
| duration_s | REAL | 时长（秒） |
| moving_duration_s | REAL | 移动时长（秒） |
| avg_pace_s_per_km | REAL | 平均配速（秒/公里） |
| avg_hr | INTEGER | 平均心率 |
| max_hr | INTEGER | 最大心率 |
| avg_cadence | INTEGER | 平均步频 |
| calories | INTEGER | 卡路里 |
| elevation_gain_m | REAL | 爬升（米） |
| source | TEXT | 数据来源 |
| source_file | TEXT | 原始文件路径 |

### laps 表

| 字段 | 类型 | 说明 |
|------|------|------|
| activity_id | TEXT | 所属活动 ID |
| lap_index | INTEGER | 圈序号 |
| distance_m | REAL | 距离（米） |
| duration_s | REAL | 时长（秒） |
| avg_pace_s_per_km | REAL | 平均配速（秒/公里） |
| avg_hr | INTEGER | 平均心率 |
| calories | INTEGER | 卡路里 |

### 健康数据表

#### daily_steps 表（步数）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期（主键） |
| steps | INTEGER | 步数 |
| distance_m | REAL | 距离（米） |
| calories | INTEGER | 活动卡路里 |
| floors_climbed | INTEGER | 爬楼层数 |

#### heart_rate_data 表（心率）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期（主键） |
| resting_hr | INTEGER | 静息心率 |
| max_hr | INTEGER | 最大心率 |
| min_hr | INTEGER | 最小心率 |
| avg_hr | INTEGER | 平均心率 |

#### hrv_data 表（心率变异性）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期（主键） |
| weekly_avg | REAL | 7天平均 HRV（ms） |
| last_night_avg | REAL | 昨晚平均 HRV（ms） |
| last_night_5min_high | REAL | 昨晚5分钟最高 HRV（ms） |
| status | TEXT | 状态（BALANCED/UNBALANCED） |

#### sleep_data 表（睡眠）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期（主键） |
| sleep_start | TEXT | 入睡时间 |
| sleep_end | TEXT | 醒来时间 |
| total_sleep_s | INTEGER | 总睡眠时长（秒） |
| deep_sleep_s | INTEGER | 深睡时长（秒） |
| light_sleep_s | INTEGER | 浅睡时长（秒） |
| rem_sleep_s | INTEGER | REM睡眠时长（秒） |
| awake_s | INTEGER | 清醒时长（秒） |
| sleep_score | INTEGER | 睡眠得分（0-100） |

#### weight_data 表（体重）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期 |
| weight_kg | REAL | 体重（kg） |
| bmi | REAL | BMI |
| body_fat_pct | REAL | 体脂率（%） |
| muscle_mass_kg | REAL | 肌肉量（kg） |
| bone_mass_kg | REAL | 骨量（kg） |
| body_water_pct | REAL | 身体水分率（%） |

#### spo2_data 表（血氧）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期（主键） |
| avg_spo2 | REAL | 平均血氧（%） |
| min_spo2 | REAL | 最低血氧（%） |

## 常见问题

### Q: 提示 "配置文件不存在" 怎么办？

A: 复制 `config.example.json` 为 `config.json` 并填入您的 Garmin 账号信息。

### Q: Garmin 登录失败怎么办？

A: 检查邮箱和密码是否正确。如果开启了两步验证，可能需要在浏览器中先登录一次。

### Q: FIT 文件解析失败怎么办？

A: 检查 FIT 文件是否完整。部分第三方设备生成的 FIT 文件可能不完全兼容。

### Q: 如何查看详细日志？

A: 日志文件位于 `logs/sync.log`，按日期滚动保留。

### Q: 健康数据同步失败怎么办？

A: 
1. 确保已先运行 `python main.py init` 初始化数据库
2. 检查 Garmin 账号是否有权限访问健康数据
3. 部分数据（如体重）需要在 Garmin Connect 中手动记录才有数据

### Q: 如何只同步特定类型的健康数据？

A: 使用 `--types` 参数指定，多个类型用逗号分隔：
```bash
python main.py sync-health --days 7 --types steps,sleep,hrv
```

### Q: 如何查看健康数据？

A: 使用以下命令：
```bash
# 查看健康数据概览
python main.py status --health

# 直接查询数据库
sqlite3 data/garmin_activity.db "SELECT * FROM sleep_data ORDER BY date DESC LIMIT 7"
```

## 许可证

MIT License
