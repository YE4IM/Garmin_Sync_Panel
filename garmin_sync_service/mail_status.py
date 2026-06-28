from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .config import Settings


def load_mail_status(settings: Settings) -> dict[str, Any]:
    path = settings.mail_status_path
    if not path.exists():
        return {"lastSentAt": "", "lastProvider": "", "lastTo": "", "lastAttachments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"lastSentAt": "", "lastProvider": "", "lastTo": "", "lastAttachments": []}
    return data if isinstance(data, dict) else {"lastSentAt": "", "lastProvider": "", "lastTo": "", "lastAttachments": []}


def record_mail_sent(
    settings: Settings,
    *,
    provider: str,
    to: str,
    attachments: list[str],
    total_bytes: int,
    subject: str = "",
    correction: bool = False,
) -> dict[str, Any]:
    payload = {
        "lastSentAt": datetime.now().isoformat(timespec="seconds"),
        "lastProvider": provider,
        "lastTo": to,
        "lastAttachments": attachments,
        "lastTotalBytes": total_bytes,
        "lastSubject": subject,
        "lastCorrection": correction,
    }
    settings.mail_status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.mail_status_path.chmod(0o600)
    return payload
