# Garmin Sync Panel

一个自托管的 Garmin 同步面板，用来把运动、健康、体重和日报整理到一个地方。

这个项目最早是为了解决一个很具体的问题：Garmin Connect 里有运动和健康数据，小米体重秤的数据在 Mi Fitness 里，日常复盘又希望有一份邮件报告可以直接阅读。几个数据源分开看很麻烦，所以这里把 Garmin 运动同步、小米体重同步、Web 面板和日报邮件放到同一个服务里。

它不是一个面向大众的云服务，也不替代 Garmin 或小米官方应用。更准确地说，它是一个可以自己部署在服务器上的个人数据整理工具：数据保存在自己的机器上，需要哪些第三方能力就自己配置哪些。

主要做这些事：

- 同步 Garmin Connect 的运动、睡眠、心率、HRV 等数据
- 同步小米 / Mi Fitness 体重数据，并上传到 Garmin
- 提供一个 Web 面板查看最近运动和健康状态
- 每天生成一份 Markdown、JSON、CSV 报告
- 通过 SMTP 或 Microsoft Graph 把日报发到邮箱

公开版本默认使用本地用户名和密码登录，不依赖外部账号系统。

## 目录

```text
.
├── garmin_sync_service/        # Web 面板、登录、日报、邮件、调度
├── garmin-activity-sync/       # Garmin 运动和健康数据同步
├── garmin-weight-sync/         # 小米体重数据同步到 Garmin
├── deploy/                     # systemd 和 nginx 示例
├── tests/                      # 当前服务测试
├── .env.example                # 配置示例
├── LICENSE                     # MIT License
├── USAGE_RULES.md              # 使用规则、账号风险和数据说明
└── NOTICE.md                   # 额外说明
```

账号风险、数据存储位置、数据传输路径和第三方服务边界，单独写在
`USAGE_RULES.md`。部署前建议先看那一份。

## 仓库默认忽略的运行文件

这些文件通常包含账号、Token、数据库、报告或日志，默认不会被 Git 跟踪：

- `.env`、`.env.*`
- `runtime/`
- `garmin-activity-sync/config.json`
- `garmin-activity-sync/data/`
- `garmin-activity-sync/logs/`
- `garmin-weight-sync/users.json`
- `garmin-weight-sync/config/`
- `garmin-weight-sync/data/`
- `.garth/`、`.garminconnect/`
- `.db`、`.fit`、`.tcx`、`.zip`、日志和 Python 缓存

发布前可以用下面两条命令看一眼：

```bash
git status --ignored -sb
git grep -n "passToken\|oauth1_token\|oauth2_token\|ACCOUNT_CLIENT_SECRET\|SMTP_PASSWORD" -- .
```

## 安装

```bash
git clone https://github.com/wanghy0813-beep/Garmin_Sync_Panel.git
cd Garmin_Sync_Panel

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
```

然后编辑 `.env`。

## 配置登录

### 默认方式：本地登录

`.env.example` 默认就是本地登录：

```env
AUTH_PROVIDER=local
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD_HASH=replace-with-generated-password-hash
LOCAL_AUTH_SESSION_SECRET=replace-with-random-session-secret
LOCAL_AUTH_SESSION_HOURS=12
```

生成密码哈希：

```bash
.venv/bin/python -m garmin_sync_service.cli hash-password
```

把输出填到：

```env
LOCAL_AUTH_PASSWORD_HASH=这里填刚才生成的哈希
```

再生成一个随机 session secret：

```bash
openssl rand -hex 32
```

把输出填到：

```env
LOCAL_AUTH_SESSION_SECRET=这里填随机字符串
```

登录页面使用：

- 用户名：`LOCAL_AUTH_USERNAME`
- 密码：生成哈希时输入的密码

### 可选方式：WXY LAB Account V1

私有部署如果要接入 WXY LAB Account V1，可以改成：

```env
AUTH_PROVIDER=wxylab
ACCOUNT_AUTH_BASE_URL=https://your-account-service.example.com/api/wxylab/account/v1
ACCOUNT_WEB_CLIENT_ID=garmin-sync-web
ACCOUNT_SERVICE_CLIENT_ID=garmin-sync-service
ACCOUNT_CLIENT_SECRET=your-client-secret
ACCOUNT_ALLOWED_PHONE=your-phone-number
```

这种模式会走手机号登录，并且只允许 `ACCOUNT_ALLOWED_PHONE` 对应的账号访问。

## 配置项目路径

如果部署在 `/opt/garmin-sync`，可以保持示例路径：

```env
GARMIN_SYNC_ROOT=/opt/garmin-sync
GARMIN_SYNC_RUNTIME_DIR=/opt/garmin-sync/runtime
GARMIN_SYNC_PYTHON=/opt/garmin-sync/.venv/bin/python
```

放在别的目录时，把这几项改掉。

## 配置 Garmin 运动同步

```bash
cp garmin-activity-sync/config.example.json garmin-activity-sync/config.json
```

示例：

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

`domain` 常见取值：

- `CN`：Garmin 中国区
- `COM`：Garmin 国际区

## 配置小米体重同步

可以使用 `garmin-weight-sync/users.json`。

示例：

```json
{
  "users": [
    {
      "username": "your-xiaomi-phone-or-email",
      "password": "your-xiaomi-password",
      "model": "yunmai.scales.ms103",
      "token": {
        "userId": "",
        "passToken": "",
        "ssecurity": ""
      },
      "garmin": {
        "email": "your_garmin_email@example.com",
        "password": "your_garmin_password",
        "domain": "CN"
      }
    }
  ]
}
```

第一次登录小米账号：

```bash
cd garmin-weight-sync
../.venv/bin/python src/xiaomi/login.py --config users.json
```

终端会提示验证码或二次验证。登录成功后，Token 会写回配置文件。

## 邮件配置

### SMTP

```env
MAIL_PROVIDER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_TLS=true
SMTP_USERNAME=your-smtp-user
SMTP_PASSWORD=your-smtp-app-password
SMTP_FROM=Garmin Sync <your-smtp-user@example.com>
MAIL_TO=your-inbox@example.com
```

### Microsoft Graph

Outlook / Hotmail 更建议用 Graph：

```env
MAIL_PROVIDER=microsoft_graph
MICROSOFT_GRAPH_CLIENT_ID=your-app-client-id
MICROSOFT_GRAPH_TENANT_ID=consumers
MICROSOFT_GRAPH_SCOPES=offline_access User.Read Mail.Send
MAIL_TO=your-inbox@example.com
```

第一次授权：

```bash
.venv/bin/python -m garmin_sync_service.cli auth-microsoft
```

按终端里的链接和验证码登录 Microsoft 账号即可。Token 会保存在
`runtime/microsoft_graph_token.json`。

## AI 分析配置

AI 分析是可选功能。不配置 API Key 时，面板和日报仍然可以正常使用，只是不会生成 AI 建议。

关闭 AI：

```env
MIMO_API_KEY=
AI_AUTO_ANALYZE_AFTER_SYNC=false
```

启用 AI：

```env
MIMO_API_KEY=your-ai-api-key
MIMO_API_URL=https://api.xiaomimimo.com/v1/chat/completions
MIMO_MODEL=mimo-v2.5-pro
AI_ANALYSIS_CACHE_HOURS=6
AI_AUTO_ANALYZE_AFTER_SYNC=true
```

配置说明：

- `MIMO_API_KEY`：AI 服务的 API Key。只写在本机 `.env`，不要提交。
- `MIMO_API_URL`：AI 接口地址。默认使用兼容 OpenAI Chat Completions 风格的接口。
- `MIMO_MODEL`：模型名称。
- `AI_ANALYSIS_CACHE_HOURS`：AI 结果缓存时间，避免频繁重复请求。
- `AI_AUTO_ANALYZE_AFTER_SYNC`：设为 `true` 时，每次同步完成后自动分析；设为 `false` 时，只在手动点击分析时请求。

AI 请求可能包含这些内容：

- 最近运动汇总
- 睡眠、心率、HRV、步数、体重等健康统计
- 面板里保存的个人背景
- 临时提示词，比如“今天腿酸，下次想轻松跑”

如果不希望这些数据发给外部 AI 服务，保持 `MIMO_API_KEY` 为空即可。

## 启动

启动 Web 面板：

```bash
.venv/bin/python -m garmin_sync_service.cli serve
```

默认地址：

```text
http://127.0.0.1:3020
```

## 常用命令

完整跑一次日报：

```bash
.venv/bin/python -m garmin_sync_service.cli run-daily
```

只同步数据：

```bash
.venv/bin/python -m garmin_sync_service.cli sync
```

只生成并发送报告：

```bash
.venv/bin/python -m garmin_sync_service.cli report
```

查看邮件状态：

```bash
.venv/bin/python -m garmin_sync_service.cli mail-status
```

## 日报内容

日报目录类似：

```text
runtime/reports/garmin-daily-2026-06-28/
```

常见文件：

- `summary.md`
- `activity_summary.json`
- `laps.csv`
- `records.csv`
- `health_summary.json`
- `recent_activities.csv`
- `daily_distance.csv`
- `weight.csv`
- `sync_result.json`
- `README_ATTACHMENTS.md`

邮件会尽量把这些文件逐个发出，而不是只发一个压缩包。

## systemd 部署

示例文件在 `deploy/`，默认路径是 `/opt/garmin-sync`。

```bash
sudo cp deploy/garmin-sync.service /etc/systemd/system/
sudo cp deploy/garmin-sync-daily.service /etc/systemd/system/
sudo cp deploy/garmin-sync-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-sync.service
```

如果使用 systemd timer 跑日报：

```bash
sudo systemctl enable --now garmin-sync-daily.timer
```

`ENABLE_SCHEDULER=true` 和 systemd timer 选一个即可，避免重复发送日报。

## 测试

```bash
.venv/bin/pytest tests
```

当前仓库包含导入的子项目。一般先跑 `tests` 就够了，不必直接跑整个仓库的全量 pytest。

## 许可证

本仓库使用 MIT License，内容见 `LICENSE`。

简单说：

- 可以使用、复制、修改和分发代码
- 分发时保留许可证和版权声明
- 代码按原样提供，不承诺适合任何特定用途

`garmin-activity-sync` 和 `garmin-weight-sync` 是导入项目，它们 README 中也写明为 MIT License。`NOTICE.md` 保留了相关说明。

MIT License 只覆盖代码本身，不代表 Garmin、Xiaomi、Microsoft 或任何账号服务的商标、API、账户和数据也被授权。
