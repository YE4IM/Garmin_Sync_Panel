from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .config import Settings


MAX_PROMPT_LENGTH = 1200


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:MAX_PROMPT_LENGTH]


def _read(settings: Settings) -> dict[str, Any]:
    path = settings.one_time_prompt_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write(settings: Settings, payload: dict[str, Any]) -> None:
    settings.one_time_prompt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.one_time_prompt_path.chmod(0o600)


def load_one_time_prompt(settings: Settings) -> dict[str, Any]:
    payload = _read(settings)
    prompt = _clean(payload.get("prompt"))
    if not prompt:
        return {"active": False, "prompt": "", "aiUsed": False, "mailUsed": False}
    return {
        "active": True,
        "prompt": prompt,
        "createdAt": str(payload.get("createdAt") or ""),
        "aiUsed": bool(payload.get("aiUsed")),
        "mailUsed": bool(payload.get("mailUsed")),
        "aiUsedAt": str(payload.get("aiUsedAt") or ""),
        "mailUsedAt": str(payload.get("mailUsedAt") or ""),
    }


def save_one_time_prompt(settings: Settings, prompt: str) -> dict[str, Any]:
    cleaned = _clean(prompt)
    if not cleaned:
        clear_one_time_prompt(settings)
        return load_one_time_prompt(settings)
    payload = {
        "prompt": cleaned,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "aiUsed": False,
        "mailUsed": False,
    }
    _write(settings, payload)
    return load_one_time_prompt(settings)


def clear_one_time_prompt(settings: Settings) -> None:
    try:
        settings.one_time_prompt_path.unlink()
    except FileNotFoundError:
        pass


def mark_one_time_prompt_used(settings: Settings, channel: str) -> dict[str, Any]:
    payload = _read(settings)
    prompt = _clean(payload.get("prompt"))
    if not prompt:
        clear_one_time_prompt(settings)
        return load_one_time_prompt(settings)
    if channel == "ai":
        payload["aiUsed"] = True
        payload["aiUsedAt"] = datetime.now().isoformat(timespec="seconds")
    elif channel == "mail":
        payload["mailUsed"] = True
        payload["mailUsedAt"] = datetime.now().isoformat(timespec="seconds")
    payload["prompt"] = prompt
    if payload.get("aiUsed") and payload.get("mailUsed"):
        clear_one_time_prompt(settings)
        return {"active": False, "prompt": "", "aiUsed": True, "mailUsed": True, "deleted": True}
    _write(settings, payload)
    return load_one_time_prompt(settings)
