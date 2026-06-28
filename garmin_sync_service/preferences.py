from __future__ import annotations

import json
from typing import Any

from .config import Settings
from .microsoft_graph_mail import token_status
from .one_time_prompt import load_one_time_prompt


PROFILE_FIELDS = {
    "sex": 24,
    "age": 8,
    "heightCm": 8,
    "weightTargetKg": 8,
    "fitnessLevel": 32,
    "trainingGoal": 160,
    "background": 400,
    "healthNotes": 400,
}


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:limit]


def _default_profile() -> dict[str, str]:
    return {field: "" for field in PROFILE_FIELDS}


def load_personal_profile(settings: Settings) -> dict[str, str]:
    if not settings.personal_profile_path.exists():
        return _default_profile()
    try:
        data = json.loads(settings.personal_profile_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_profile()
    if not isinstance(data, dict):
        return _default_profile()
    profile = _default_profile()
    for field, limit in PROFILE_FIELDS.items():
        profile[field] = _clean(data.get(field), limit)
    return profile


def save_personal_profile(settings: Settings, payload: dict[str, Any]) -> dict[str, str]:
    profile = _default_profile()
    for field, limit in PROFILE_FIELDS.items():
        profile[field] = _clean(payload.get(field), limit)
    settings.personal_profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.personal_profile_path.chmod(0o600)
    return profile


def _mask(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" in text:
        name, domain = text.split("@", 1)
        return f"{name[:2]}***@{domain}"
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def settings_overview(settings: Settings) -> dict[str, Any]:
    graph_status = token_status(settings)
    mail_items = {
        "SMTP_HOST": bool(settings.smtp_host),
        "SMTP_PORT": bool(settings.smtp_port),
        "SMTP_USERNAME": bool(settings.smtp_username),
        "SMTP_PASSWORD": bool(settings.smtp_password),
        "SMTP_FROM": bool(settings.smtp_from),
        "SMTP_TO": bool(settings.smtp_to),
    }
    return {
        "profile": load_personal_profile(settings),
        "oneTimePrompt": {
            key: value
            for key, value in load_one_time_prompt(settings).items()
            if key != "prompt"
        },
        "mail": {
            "provider": settings.mail_provider,
            "configured": graph_status["configured"] and graph_status["authorized"]
            if settings.mail_provider in {"microsoft_graph", "graph", "oauth2"}
            else all(mail_items.values()),
            "items": mail_items,
            "graph": graph_status,
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "from": _mask(settings.smtp_from),
            "to": _mask(settings.smtp_to),
            "ssl": settings.smtp_ssl,
            "tls": settings.smtp_tls,
            "attachmentLimitMb": settings.mail_attachment_limit_mb,
        },
        "ai": {
            "configured": bool(settings.mimo_api_key),
            "model": settings.mimo_model,
            "cacheHours": settings.ai_analysis_cache_hours,
            "autoAfterSync": settings.ai_auto_analyze_after_sync,
        },
        "sync": {
            "activityDays": settings.sync_activity_days,
            "healthDays": settings.sync_health_days,
            "dailyRunTime": settings.daily_run_time,
            "schedulerEnabled": settings.enable_scheduler,
        },
    }
