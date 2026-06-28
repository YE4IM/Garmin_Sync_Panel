from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    activity_project_dir: Path
    weight_project_dir: Path
    runtime_dir: Path
    reports_dir: Path
    logs_dir: Path
    python_bin: str

    auth_provider: str
    local_auth_username: str
    local_auth_password_hash: str
    local_auth_session_secret: str
    local_auth_session_hours: int

    account_auth_base_url: str
    account_web_client_id: str
    account_service_client_id: str
    account_client_secret: str
    account_allowed_phone: str

    cookie_secure: bool
    cookie_name_access: str
    cookie_name_refresh: str
    public_base_url: str

    sync_activity_days: int
    sync_health_days: int
    daily_run_time: str
    enable_scheduler: bool

    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_to: str
    smtp_tls: bool
    smtp_ssl: bool
    mail_attachment_limit_mb: int
    mail_provider: str
    microsoft_graph_client_id: str
    microsoft_graph_tenant_id: str
    microsoft_graph_scopes: str

    request_timeout_seconds: int
    command_timeout_seconds: int
    mimo_api_key: str
    mimo_api_url: str
    mimo_model: str
    ai_analysis_cache_hours: int
    ai_auto_analyze_after_sync: bool

    @classmethod
    def load(cls) -> "Settings":
        root_dir = Path(os.environ.get("GARMIN_SYNC_ROOT", Path(__file__).resolve().parents[1]))
        load_dotenv(root_dir / ".env")

        runtime_dir = Path(os.environ.get("GARMIN_SYNC_RUNTIME_DIR", root_dir / "runtime"))
        settings = cls(
            root_dir=root_dir,
            activity_project_dir=Path(os.environ.get("ACTIVITY_PROJECT_DIR", root_dir / "garmin-activity-sync")),
            weight_project_dir=Path(os.environ.get("WEIGHT_PROJECT_DIR", root_dir / "garmin-weight-sync")),
            runtime_dir=runtime_dir,
            reports_dir=Path(os.environ.get("REPORTS_DIR", runtime_dir / "reports")),
            logs_dir=Path(os.environ.get("GARMIN_SYNC_LOG_DIR", runtime_dir / "logs")),
            python_bin=os.environ.get("GARMIN_SYNC_PYTHON", sys.executable),
            auth_provider=os.environ.get("AUTH_PROVIDER", "local").strip().lower(),
            local_auth_username=os.environ.get("LOCAL_AUTH_USERNAME", "admin"),
            local_auth_password_hash=os.environ.get("LOCAL_AUTH_PASSWORD_HASH", ""),
            local_auth_session_secret=os.environ.get("LOCAL_AUTH_SESSION_SECRET", ""),
            local_auth_session_hours=_int(os.environ.get("LOCAL_AUTH_SESSION_HOURS"), 12),
            account_auth_base_url=os.environ.get(
                "ACCOUNT_AUTH_BASE_URL",
                "https://wxylab.ltd/api/wxylab/account/v1",
            ).rstrip("/"),
            account_web_client_id=os.environ.get("ACCOUNT_WEB_CLIENT_ID", "garmin-sync-web"),
            account_service_client_id=os.environ.get("ACCOUNT_SERVICE_CLIENT_ID", "garmin-sync-service"),
            account_client_secret=os.environ.get("ACCOUNT_CLIENT_SECRET", ""),
            account_allowed_phone=os.environ.get("ACCOUNT_ALLOWED_PHONE", ""),
            cookie_secure=_bool(os.environ.get("COOKIE_SECURE"), True),
            cookie_name_access=os.environ.get("COOKIE_NAME_ACCESS", "garmin_sync_access_token"),
            cookie_name_refresh=os.environ.get("COOKIE_NAME_REFRESH", "garmin_sync_refresh_token"),
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "").rstrip("/"),
            sync_activity_days=_int(os.environ.get("SYNC_ACTIVITY_DAYS"), 30),
            sync_health_days=_int(os.environ.get("SYNC_HEALTH_DAYS"), 14),
            daily_run_time=os.environ.get("DAILY_RUN_TIME", "09:40"),
            enable_scheduler=_bool(os.environ.get("ENABLE_SCHEDULER"), True),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=_int(os.environ.get("SMTP_PORT"), 465),
            smtp_username=os.environ.get("SMTP_USERNAME", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("SMTP_FROM", ""),
            smtp_to=os.environ.get("MAIL_TO") or os.environ.get("SMTP_TO", ""),
            smtp_tls=_bool(os.environ.get("SMTP_TLS"), True),
            smtp_ssl=_bool(os.environ.get("SMTP_SSL"), False),
            mail_attachment_limit_mb=_int(os.environ.get("MAIL_ATTACHMENT_LIMIT_MB"), 20),
            mail_provider=os.environ.get("MAIL_PROVIDER", "smtp").strip().lower(),
            microsoft_graph_client_id=os.environ.get("MICROSOFT_GRAPH_CLIENT_ID", ""),
            microsoft_graph_tenant_id=os.environ.get("MICROSOFT_GRAPH_TENANT_ID", "consumers"),
            microsoft_graph_scopes=os.environ.get(
                "MICROSOFT_GRAPH_SCOPES",
                "offline_access User.Read Mail.Send",
            ),
            request_timeout_seconds=_int(os.environ.get("REQUEST_TIMEOUT_SECONDS"), 20),
            command_timeout_seconds=_int(os.environ.get("COMMAND_TIMEOUT_SECONDS"), 1800),
            mimo_api_key=os.environ.get("MIMO_API_KEY", ""),
            mimo_api_url=os.environ.get(
                "MIMO_API_URL",
                "https://api.xiaomimimo.com/v1/chat/completions",
            ),
            mimo_model=os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
            ai_analysis_cache_hours=_int(os.environ.get("AI_ANALYSIS_CACHE_HOURS"), 6),
            ai_auto_analyze_after_sync=_bool(os.environ.get("AI_AUTO_ANALYZE_AFTER_SYNC"), True),
        )
        settings.ensure_dirs()
        return settings

    def ensure_dirs(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def activity_db_path(self) -> Path:
        return self.activity_project_dir / "data" / "garmin_activity.db"

    @property
    def activity_export_path(self) -> Path:
        return self.activity_project_dir / "data" / "exports" / "pidesk_activity_summary.json"

    @property
    def weight_data_path(self) -> Path:
        return self.weight_project_dir / "data" / f"weight_data_{self.account_allowed_phone}.json"

    @property
    def last_run_path(self) -> Path:
        return self.runtime_dir / "last_run.json"

    @property
    def ai_analysis_path(self) -> Path:
        return self.runtime_dir / "ai_analysis.json"

    @property
    def personal_profile_path(self) -> Path:
        return self.runtime_dir / "personal_profile.json"

    @property
    def one_time_prompt_path(self) -> Path:
        return self.runtime_dir / "one_time_prompt.json"

    @property
    def mail_status_path(self) -> Path:
        return self.runtime_dir / "mail_status.json"

    @property
    def microsoft_graph_token_path(self) -> Path:
        return self.runtime_dir / "microsoft_graph_token.json"

    @property
    def microsoft_graph_scope_list(self) -> list[str]:
        return [item for item in self.microsoft_graph_scopes.split() if item]


settings = Settings.load()
