# Garmin Sync Panel

English | [简体中文](README.md)

A self-hosted Garmin sync panel that brings activities, health metrics, weight data, and daily reports together in one place.

## Recent Changes (v0.1.1)

- **Configurable sync steps**: new `AUTO_SYNC_STEPS` environment variable, a comma-separated list selecting which steps the daily scheduled sync runs. Unset, it behaves exactly as before and runs all 5 steps.
- **Fixed Metabolic Age rendering**: FIT files generated from Xiaomi scale data no longer write the MetabolicAge field. Garmin previously rendered its internal millisecond value as "years" (e.g. 24y showed up as `757366224000年`); now Garmin simply hides the metric.

This project started from a very concrete problem: activity and health data live in Garmin Connect, Xiaomi scale data lives in Mi Fitness, and daily reviews are easiest to read in an email report. Keeping those sources separate is cumbersome, so this service puts Garmin activity sync, Xiaomi weight sync, a web panel, and daily report emails into one place.

It is not a mass-market cloud service and does not replace the official Garmin or Xiaomi apps. More precisely, it is a personal data-organizing tool you deploy on your own server: data stays on your machine, and you configure only the third-party capabilities you need.

What it does:

- Syncs activities, sleep, heart rate, HRV, and more from Garmin Connect
- Syncs Xiaomi / Mi Fitness weight data and uploads it to Garmin
- Provides a web panel for recent activity and health status
- Generates a daily Markdown, JSON, and CSV report
- Emails the daily report via SMTP or Microsoft Graph

The public version uses local username/password login by default and does not depend on any external account system.

## Contents

```text
.
├── garmin_sync_service/        # Web panel, login, daily reports, email, scheduler
├── garmin-activity-sync/       # Garmin activity and health data sync
├── garmin-weight-sync/         # Xiaomi weight data synced to Garmin
├── deploy/                     # systemd and nginx examples
├── tests/                      # current service tests
├── .env.example                # configuration template
├── LICENSE                     # MIT License
├── DEPLOYMENT.md               # beginner deployment guide
├── CHANGELOG.md                # version history
├── USAGE_RULES.md              # usage rules, account risks, data notes
└── NOTICE.md                   # additional notices
```

For a first deployment, start with `DEPLOYMENT.md`, which walks through installation, configuration, login, sync, email, AI, autostart, and nginx in order.

Account risks, data storage locations, data transfer paths, and third-party service boundaries are documented separately in `USAGE_RULES.md`. Read it before deploying.

## Releases and Packages

Official releases live on GitHub Releases. Each release ships the auto-generated source archive, with release notes describing the main features and intended use.

GitHub Packages are not published for now. The reason is simple: this project requires a local `.env`, Garmin configuration, Xiaomi configuration, and mail credentials, so self-hosting via the deployment guide fits better. A GHCR image is on the table once the Docker deployment flow stabilizes.

## Runtime Files Ignored by Git

These files usually contain accounts, tokens, databases, reports, or logs and are not tracked by Git by default:

- `.env`, `.env.*`
- `runtime/`
- `garmin-activity-sync/config.json`
- `garmin-activity-sync/data/`
- `garmin-activity-sync/logs/`
- `garmin-weight-sync/users.json`
- `garmin-weight-sync/config/`
- `garmin-weight-sync/data/`
- `.garth/`, `.garminconnect/`
- `.db`, `.fit`, `.tcx`, `.zip`, logs, and Python caches

Before publishing, check with:

```bash
git status --ignored -sb
git grep -n "passToken\|oauth1_token\|oauth2_token\|ACCOUNT_CLIENT_SECRET\|SMTP_PASSWORD" -- .
```

## Installation

```bash
git clone https://github.com/YE4IM/Garmin_Sync_Panel.git
cd Garmin_Sync_Panel

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
```

Then edit `.env`.

## Configuring Login

### Default: local login

`.env.example` defaults to local login:

```env
AUTH_PROVIDER=local
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD_HASH=replace-with-generated-password-hash
LOCAL_AUTH_SESSION_SECRET=replace-with-random-session-secret
LOCAL_AUTH_SESSION_HOURS=12
```

Generate the password hash:

```bash
.venv/bin/python -m garmin_sync_service.cli hash-password
```

Put the output into:

```env
LOCAL_AUTH_PASSWORD_HASH=<the hash you just generated>
```

Then generate a random session secret:

```bash
openssl rand -hex 32
```

Put the output into:

```env
LOCAL_AUTH_SESSION_SECRET=<the random string>
```

The login page uses:

- Username: `LOCAL_AUTH_USERNAME`
- Password: the password you entered when generating the hash

### Optional: WXY LAB Account V1

For private deployments integrating with WXY LAB Account V1:

```env
AUTH_PROVIDER=wxylab
ACCOUNT_AUTH_BASE_URL=https://your-account-service.example.com/api/wxylab/account/v1
ACCOUNT_WEB_CLIENT_ID=garmin-sync-web
ACCOUNT_SERVICE_CLIENT_ID=garmin-sync-service
ACCOUNT_CLIENT_SECRET=your-client-secret
ACCOUNT_ALLOWED_PHONE=your-phone-number
```

This mode uses phone-number login and only allows the account matching `ACCOUNT_ALLOWED_PHONE`.

## Configuring Project Paths

If deployed at `/opt/garmin-sync`, the example paths work as-is:

```env
GARMIN_SYNC_ROOT=/opt/garmin-sync
GARMIN_SYNC_RUNTIME_DIR=/opt/garmin-sync/runtime
GARMIN_SYNC_PYTHON=/opt/garmin-sync/.venv/bin/python
```

Adjust these when deploying elsewhere.

## Configuring Sync Steps (Optional)

The daily scheduled sync runs 5 steps in order by default: `activity_init`, `activity_sync`, `health_sync`, `activity_export`, `weight_sync`.

To run only a subset, set `AUTO_SYNC_STEPS` (comma-separated):

```env
AUTO_SYNC_STEPS=activity_sync,weight_sync
```

Leave it empty or unset to run all steps. Manual syncs triggered from the web panel are unaffected and always run all steps.

## Configuring Garmin Activity Sync

```bash
cp garmin-activity-sync/config.example.json garmin-activity-sync/config.json
```

Example:

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

Common `domain` values:

- `CN`: Garmin China
- `COM`: Garmin international

## Configuring Xiaomi Weight Sync

Uses `garmin-weight-sync/users.json`.

Example:

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

First Xiaomi login:

```bash
cd garmin-weight-sync
../.venv/bin/python src/xiaomi/login.py --config users.json
```

The terminal prompts for a verification code or two-factor authentication. After a successful login, the token is written back to the config file.

## Email Configuration

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

For Outlook / Hotmail, Graph is recommended:

```env
MAIL_PROVIDER=microsoft_graph
MICROSOFT_GRAPH_CLIENT_ID=your-app-client-id
MICROSOFT_GRAPH_TENANT_ID=consumers
MICROSOFT_GRAPH_SCOPES=offline_access User.Read Mail.Send
MAIL_TO=your-inbox@example.com
```

First authorization:

```bash
.venv/bin/python -m garmin_sync_service.cli auth-microsoft
```

Follow the link and verification code in the terminal to log in with your Microsoft account. The token is saved to `runtime/microsoft_graph_token.json`.

## AI Analysis Configuration

AI analysis is optional. Without an API key, the panel and daily reports work fine — they just contain no AI suggestions.

Disable AI:

```env
MIMO_API_KEY=
AI_AUTO_ANALYZE_AFTER_SYNC=false
```

Enable AI:

```env
MIMO_API_KEY=your-ai-api-key
MIMO_API_URL=https://api.xiaomimimo.com/v1/chat/completions
MIMO_MODEL=mimo-v2.5-pro
AI_ANALYSIS_CACHE_HOURS=6
AI_AUTO_ANALYZE_AFTER_SYNC=true
```

Settings:

- `MIMO_API_KEY`: API key for the AI service. Keep it in the local `.env` only; never commit it.
- `MIMO_API_URL`: AI endpoint. Defaults to an OpenAI Chat Completions-compatible API.
- `MIMO_MODEL`: model name.
- `AI_ANALYSIS_CACHE_HOURS`: cache duration for AI results, avoiding repeated requests.
- `AI_AUTO_ANALYZE_AFTER_SYNC`: when `true`, analysis runs automatically after each sync; when `false`, it only runs when triggered manually.

AI requests may include:

- Summaries of recent activities
- Health stats such as sleep, heart rate, HRV, steps, and weight
- Personal background saved in the panel
- Ad-hoc prompts, e.g. "my legs are sore today, want an easy run next"

If you do not want this data sent to an external AI service, leave `MIMO_API_KEY` empty.

## Running

Start the web panel:

```bash
.venv/bin/python -m garmin_sync_service.cli serve
```

Default address:

```text
http://127.0.0.1:3020
```

## Common Commands

Run the full daily report:

```bash
.venv/bin/python -m garmin_sync_service.cli run-daily
```

Sync data only:

```bash
.venv/bin/python -m garmin_sync_service.cli sync
```

Generate and send the report only:

```bash
.venv/bin/python -m garmin_sync_service.cli report
```

Check mail status:

```bash
.venv/bin/python -m garmin_sync_service.cli mail-status
```

## Daily Report Contents

The report directory looks like:

```text
runtime/reports/garmin-daily-2026-06-28/
```

Typical files:

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

The email sends these files individually whenever possible instead of a single archive.

## systemd Deployment

Example files live in `deploy/`, with `/opt/garmin-sync` as the default path.

```bash
sudo cp deploy/garmin-sync.service /etc/systemd/system/
sudo cp deploy/garmin-sync-daily.service /etc/systemd/system/
sudo cp deploy/garmin-sync-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-sync.service
```

To run the daily report via a systemd timer:

```bash
sudo systemctl enable --now garmin-sync-daily.timer
```

Pick either `ENABLE_SCHEDULER=true` or the systemd timer — not both — to avoid duplicate daily reports.

## Testing

```bash
.venv/bin/pytest tests
```

The repository includes vendored subprojects. Running `tests` is generally enough; there is no need to run the full-repo pytest.

## Acknowledgments

- This project is a fork of [wanghy0813-beep/Garmin_Sync_Panel](https://github.com/wanghy0813-beep/Garmin_Sync_Panel) — thanks to the original author for open-sourcing and putting together this self-hosted sync panel.
- Thanks also to the authors of the vendored subprojects `garmin-activity-sync` and `garmin-weight-sync`; see `NOTICE.md` for licensing details.

## License

This repository is released under the MIT License; see `LICENSE`.

In short:

- You may use, copy, modify, and distribute the code
- Keep the license and copyright notice when distributing
- The code is provided "as is", without warranty of any kind

`garmin-activity-sync` and `garmin-weight-sync` are vendored projects, also MIT-licensed per their own READMEs. `NOTICE.md` keeps the relevant notices.

The MIT License covers the code only; it does not license the trademarks, APIs, accounts, or data of Garmin, Xiaomi, Microsoft, or any account service.
