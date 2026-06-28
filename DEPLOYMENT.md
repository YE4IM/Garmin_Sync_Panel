# 部署教程

这份教程写给第一次部署的人。照着做就行，不需要先懂 FastAPI、systemd 或 nginx。

## 先准备什么

你需要一台 Linux 服务器，推荐 Ubuntu 22.04 或更新版本。

服务器上需要：

- Python 3.10+
- Git
- 一个能访问 GitHub 的网络环境
- Garmin Connect 账号
- 小米 / Mi Fitness 账号，可选
- 一个可以发邮件的邮箱，可选

先登录服务器，然后执行：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

## 下载项目

推荐放在 `/opt/garmin-sync`：

```bash
cd /opt
sudo git clone https://github.com/wanghy0813-beep/Garmin_Sync_Panel.git garmin-sync
sudo chown -R "$USER":"$USER" /opt/garmin-sync
cd /opt/garmin-sync
```

如果你没有 `/opt` 权限，也可以放在自己的 home 目录：

```bash
cd ~
git clone https://github.com/wanghy0813-beep/Garmin_Sync_Panel.git garmin-sync
cd garmin-sync
```

后面教程默认项目路径是 `/opt/garmin-sync`。如果你放在别的地方，把命令里的路径换成你的实际路径。

## 安装 Python 依赖

```bash
cd /opt/garmin-sync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

以后运行这个项目，基本都用 `.venv/bin/python`，不要直接用系统 Python。

## 创建主配置文件

复制示例配置：

```bash
cp .env.example .env
```

打开编辑：

```bash
nano .env
```

先确认这几项路径：

```env
GARMIN_SYNC_ROOT=/opt/garmin-sync
GARMIN_SYNC_RUNTIME_DIR=/opt/garmin-sync/runtime
GARMIN_SYNC_PYTHON=/opt/garmin-sync/.venv/bin/python
```

如果你的项目不是放在 `/opt/garmin-sync`，这里要改成实际路径。

## 配置网页登录

公开版本默认使用本地登录。也就是说，打开面板时用你自己设置的用户名和密码登录。

`.env` 里保持：

```env
AUTH_PROVIDER=local
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_SESSION_HOURS=12
```

生成登录密码的哈希：

```bash
cd /opt/garmin-sync
.venv/bin/python -m garmin_sync_service.cli hash-password
```

它会让你输入两次密码。输入时不会显示，这是正常的。

命令输出一长串内容，类似：

```text
pbkdf2_sha256$260000$...
```

把这串内容填到 `.env`：

```env
LOCAL_AUTH_PASSWORD_HASH=这里填刚才生成的那一整串
```

再生成一个 session 密钥：

```bash
openssl rand -hex 32
```

把输出填到 `.env`：

```env
LOCAL_AUTH_SESSION_SECRET=这里填 openssl 输出的随机字符串
```

注意：不要把 `.env` 发给别人，也不要提交到 GitHub。

## 配置 Garmin 运动同步

复制 Garmin 配置示例：

```bash
cp garmin-activity-sync/config.example.json garmin-activity-sync/config.json
```

编辑它：

```bash
nano garmin-activity-sync/config.json
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

`domain` 怎么选：

- 中国区 Garmin 账号一般填 `CN`
- 国际区 Garmin 账号一般填 `COM`

如果登录失败，先确认你能不能在浏览器里正常登录 Garmin Connect。

## 配置小米体重同步

如果你不用小米体重秤，可以先跳过这一节。

创建配置文件：

```bash
nano garmin-weight-sync/users.json
```

填入：

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
cd /opt/garmin-sync/garmin-weight-sync
../.venv/bin/python src/xiaomi/login.py --config users.json
```

按提示输入验证码或二次验证。成功后，程序会把 Token 写回 `users.json`。

## 配置邮件

邮件不是必须的。不配置邮件时，报告仍然会生成在服务器本地，只是不会发出去。

### SMTP 邮箱

适合普通邮箱、企业邮箱或支持 SMTP 的服务。

在 `.env` 里填：

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

很多邮箱不允许直接用登录密码发 SMTP，需要去邮箱设置里创建“应用密码”。

### Outlook / Hotmail

Outlook 更推荐 Microsoft Graph。

`.env` 示例：

```env
MAIL_PROVIDER=microsoft_graph
MICROSOFT_GRAPH_CLIENT_ID=your-app-client-id
MICROSOFT_GRAPH_TENANT_ID=consumers
MICROSOFT_GRAPH_SCOPES=offline_access User.Read Mail.Send
MAIL_TO=your-inbox@example.com
```

然后在服务器上授权一次：

```bash
cd /opt/garmin-sync
.venv/bin/python -m garmin_sync_service.cli auth-microsoft
```

终端会显示一个 Microsoft 链接和验证码。用浏览器打开链接，输入验证码并同意授权。

## 配置 AI 分析

AI 分析也是可选的。不配置就不会调用外部 AI 服务。

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

开启后，AI 请求可能包含运动、睡眠、心率、HRV、体重、个人背景和临时提示词。介意外传这些数据的话，就不要填写 `MIMO_API_KEY`。

## 先试着启动

```bash
cd /opt/garmin-sync
.venv/bin/python -m garmin_sync_service.cli serve
```

看到类似下面的内容就说明服务启动了：

```text
Uvicorn running on http://127.0.0.1:3020
```

在服务器本机可以测试：

```bash
curl http://127.0.0.1:3020/health
```

返回类似：

```json
{"ok": true, "service": "garmin-sync"}
```

如果你是在本地电脑浏览器访问远程服务器，通常还需要配置 nginx 和域名，见后面的章节。

停止手动运行：

```bash
Ctrl + C
```

## 跑一次同步和日报

只同步：

```bash
cd /opt/garmin-sync
.venv/bin/python -m garmin_sync_service.cli sync
```

完整跑一次日报：

```bash
.venv/bin/python -m garmin_sync_service.cli run-daily
```

生成的报告在：

```text
runtime/reports/
```

如果邮件配置好了，日报会发到 `MAIL_TO`。

## 设置开机自启

项目里已经准备了 systemd 示例。

如果项目路径是 `/opt/garmin-sync`，可以直接复制：

```bash
sudo cp deploy/garmin-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-sync.service
```

查看状态：

```bash
systemctl status garmin-sync.service --no-pager
```

看日志：

```bash
journalctl -u garmin-sync.service -f
```

如果你的项目路径不是 `/opt/garmin-sync`，先编辑 `deploy/garmin-sync.service`，把里面的路径改成你的实际路径，再复制。

## 设置每天自动同步

有两种方式，选一种就行。

### 方式一：项目内置调度

`.env`：

```env
ENABLE_SCHEDULER=true
DAILY_RUN_TIME=09:40
```

然后重启服务：

```bash
sudo systemctl restart garmin-sync.service
```

### 方式二：systemd timer

先确保 `.env` 里不要启用内置调度：

```env
ENABLE_SCHEDULER=false
```

复制 timer：

```bash
sudo cp deploy/garmin-sync-daily.service /etc/systemd/system/
sudo cp deploy/garmin-sync-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-sync-daily.timer
```

查看 timer：

```bash
systemctl list-timers | grep garmin-sync
```

不要同时开启内置调度和 systemd timer，否则可能一天跑两次。

## 配置 nginx 和域名

如果你只在服务器本机访问，可以跳过。

如果想通过域名访问，需要 nginx 反向代理到 `127.0.0.1:3020`。

安装 nginx：

```bash
sudo apt install -y nginx
```

参考配置在：

```text
deploy/nginx.conf.example
```

复制后改域名和证书路径：

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/garmin-sync
sudo nano /etc/nginx/sites-available/garmin-sync
sudo ln -s /etc/nginx/sites-available/garmin-sync /etc/nginx/sites-enabled/garmin-sync
sudo nginx -t
sudo systemctl reload nginx
```

证书可以用你自己的证书，也可以用 Certbot 申请 Let's Encrypt 证书。

## 更新项目

以后更新代码：

```bash
cd /opt/garmin-sync
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart garmin-sync.service
```

检查：

```bash
curl http://127.0.0.1:3020/health
```

## 常见问题

### 1. 网页打不开

先看服务是否启动：

```bash
systemctl status garmin-sync.service --no-pager
```

再看本地健康检查：

```bash
curl http://127.0.0.1:3020/health
```

如果本地正常，外网打不开，多半是 nginx、域名、防火墙或安全组问题。

### 2. 登录页面密码不对

重新生成密码哈希：

```bash
.venv/bin/python -m garmin_sync_service.cli hash-password
```

把输出完整复制到 `.env` 的 `LOCAL_AUTH_PASSWORD_HASH`，然后重启：

```bash
sudo systemctl restart garmin-sync.service
```

### 3. Garmin 登录失败

先在浏览器里确认 Garmin Connect 可以正常登录。然后检查：

- 邮箱是否写错
- 密码是否写错
- `domain` 是否应该是 `CN` 或 `COM`
- Garmin 是否要求二次验证或重新授权

### 4. 小米登录失败

重新跑：

```bash
cd /opt/garmin-sync/garmin-weight-sync
../.venv/bin/python src/xiaomi/login.py --config users.json
```

如果频繁失败，先停止重试，避免触发账号风控。

### 5. 邮件发不出去

检查：

```bash
.venv/bin/python -m garmin_sync_service.cli mail-status
```

SMTP 常见问题：

- `SMTP_HOST` 写错
- 端口写错
- 邮箱不允许密码登录
- 应该使用应用密码

Outlook 常见问题：

- 没有运行 `auth-microsoft`
- Microsoft app 没开 `Mail.Send`
- Token 被撤销，需要重新授权

### 6. 磁盘越来越大

主要增长目录：

```text
runtime/
garmin-activity-sync/data/
garmin-activity-sync/logs/
garmin-weight-sync/data/
```

可以定期清理旧报告、旧日志或旧 FIT 文件。清理前先确认自己不需要这些历史数据。

## 最后提醒

`.env`、`config.json`、`users.json`、`runtime/`、`data/` 这些文件都可能包含账号、Token 或健康数据。不要发给别人，也不要提交到 GitHub。

账号使用规则、数据存储位置、数据传输路径和第三方服务边界，见：

```text
USAGE_RULES.md
```
