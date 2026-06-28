from __future__ import annotations

import base64
import json
import time
from datetime import date
from typing import Any

import requests

from .config import Settings
from .mail_attachments import report_attachments, total_attachment_size
from .mail_status import record_mail_sent
from .one_time_prompt import mark_one_time_prompt_used


DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
GRAPH_SENDMAIL_URL = "https://graph.microsoft.com/v1.0/me/sendMail"


class MicrosoftGraphAuthError(RuntimeError):
    pass


def _tenant(settings: Settings) -> str:
    return settings.microsoft_graph_tenant_id.strip() or "consumers"


def _device_code_url(settings: Settings) -> str:
    return f"https://login.microsoftonline.com/{_tenant(settings)}/oauth2/v2.0/devicecode"


def _token_url(settings: Settings) -> str:
    return f"https://login.microsoftonline.com/{_tenant(settings)}/oauth2/v2.0/token"


def _read_token(settings: Settings) -> dict[str, Any]:
    path = settings.microsoft_graph_token_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_token(settings: Settings, data: dict[str, Any]) -> None:
    payload = dict(data)
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in:
        payload["expires_at"] = int(time.time()) + max(0, expires_in - 120)
    settings.microsoft_graph_token_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.microsoft_graph_token_path.chmod(0o600)


def token_status(settings: Settings) -> dict[str, Any]:
    token = _read_token(settings)
    expires_at = int(token.get("expires_at") or 0)
    return {
        "configured": bool(settings.microsoft_graph_client_id),
        "authorized": bool(token.get("refresh_token")),
        "hasAccessToken": bool(token.get("access_token")),
        "expiresAt": expires_at,
        "expiresInSeconds": max(0, expires_at - int(time.time())) if expires_at else 0,
        "cachePath": str(settings.microsoft_graph_token_path),
    }


def start_device_authorization(settings: Settings) -> dict[str, Any]:
    if not settings.microsoft_graph_client_id:
        raise MicrosoftGraphAuthError("MICROSOFT_GRAPH_CLIENT_ID is not configured")
    response = requests.post(
        _device_code_url(settings),
        data={
            "client_id": settings.microsoft_graph_client_id,
            "scope": " ".join(settings.microsoft_graph_scope_list),
        },
        timeout=settings.request_timeout_seconds,
    )
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        raise MicrosoftGraphAuthError(payload.get("error_description") or payload.get("error") or "device auth failed")
    return payload


def complete_device_authorization(settings: Settings, flow: dict[str, Any]) -> dict[str, Any]:
    deadline = time.time() + int(flow.get("expires_in") or 900)
    interval = max(2, int(flow.get("interval") or 5))
    while time.time() < deadline:
        response = requests.post(
            _token_url(settings),
            data={
                "grant_type": DEVICE_CODE_GRANT,
                "client_id": settings.microsoft_graph_client_id,
                "device_code": flow.get("device_code"),
            },
            timeout=settings.request_timeout_seconds,
        )
        payload = response.json() if response.content else {}
        if response.status_code < 400 and payload.get("access_token"):
            _write_token(settings, payload)
            return {k: v for k, v in payload.items() if k not in {"access_token", "refresh_token", "id_token"}}
        error = payload.get("error")
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        raise MicrosoftGraphAuthError(payload.get("error_description") or error or "device auth failed")
    raise MicrosoftGraphAuthError("device authorization expired")


def authorize_with_device_code(settings: Settings) -> dict[str, Any]:
    flow = start_device_authorization(settings)
    print(flow.get("message") or f"Open {flow.get('verification_uri')} and enter {flow.get('user_code')}")
    result = complete_device_authorization(settings, flow)
    return {
        "ok": True,
        "message": "Microsoft Graph authorization saved",
        "scope": result.get("scope"),
        "expiresIn": result.get("expires_in"),
        "tokenType": result.get("token_type"),
    }


def _refresh_access_token(settings: Settings, token: dict[str, Any]) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise MicrosoftGraphAuthError("Microsoft Graph is not authorized. Run: python -m garmin_sync_service.cli auth-microsoft")
    response = requests.post(
        _token_url(settings),
        data={
            "grant_type": "refresh_token",
            "client_id": settings.microsoft_graph_client_id,
            "refresh_token": refresh_token,
            "scope": " ".join(settings.microsoft_graph_scope_list),
        },
        timeout=settings.request_timeout_seconds,
    )
    payload = response.json() if response.content else {}
    if response.status_code >= 400 or not payload.get("access_token"):
        raise MicrosoftGraphAuthError(payload.get("error_description") or payload.get("error") or "token refresh failed")
    if not payload.get("refresh_token"):
        payload["refresh_token"] = refresh_token
    _write_token(settings, payload)
    return payload


def access_token(settings: Settings) -> str:
    if not settings.microsoft_graph_client_id:
        raise MicrosoftGraphAuthError("MICROSOFT_GRAPH_CLIENT_ID is not configured")
    token = _read_token(settings)
    expires_at = int(token.get("expires_at") or 0)
    if token.get("access_token") and expires_at > int(time.time()) + 120:
        return str(token["access_token"])
    return str(_refresh_access_token(settings, token)["access_token"])


def _recipient(address: str) -> dict[str, Any]:
    return {"emailAddress": {"address": address.strip()}}


def send_report_via_graph(settings: Settings, report: dict) -> dict[str, Any]:
    if not settings.microsoft_graph_client_id:
        return {"ok": False, "skipped": True, "reason": "MICROSOFT_GRAPH_CLIENT_ID is not configured"}
    status = token_status(settings)
    if not status["authorized"]:
        return {"ok": False, "skipped": True, "reason": "Microsoft Graph is not authorized. Run auth-microsoft first."}
    if not settings.smtp_to:
        return {"ok": False, "skipped": True, "reason": "SMTP_TO is not configured"}
    limit = settings.mail_attachment_limit_mb * 1024 * 1024
    attachments = report_attachments(report)
    if not attachments:
        return {"ok": False, "skipped": True, "reason": "report has no readable attachments"}
    total_size = total_attachment_size(report)
    if total_size > limit:
        return {"ok": False, "skipped": True, "reason": f"attachments exceed {settings.mail_attachment_limit_mb} MB"}

    recipients = [_recipient(item) for item in settings.smtp_to.replace(";", ",").split(",") if item.strip()]
    subject = str(report.get("subject") or f"[Garmin Daily] {date.today().isoformat()} 运动与健康数据文件")
    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": report.get("summary") or "Garmin daily report attached."},
        "toRecipients": recipients,
        "attachments": [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment["name"],
                "contentType": attachment["contentType"],
                "contentBytes": base64.b64encode(attachment["path"].read_bytes()).decode("ascii"),
            }
            for attachment in attachments
        ],
    }
    try:
        token = access_token(settings)
    except MicrosoftGraphAuthError as exc:
        return {"ok": False, "skipped": True, "reason": str(exc)}
    response = requests.post(
        GRAPH_SENDMAIL_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message, "saveToSentItems": True},
        timeout=settings.request_timeout_seconds,
    )
    if response.status_code not in {202, 200}:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return {
            "ok": False,
            "skipped": False,
            "reason": payload.get("error", {}).get("message") or response.text or "Graph sendMail failed",
            "status": response.status_code,
        }
    attachment_names = [item["name"] for item in attachments]
    status = record_mail_sent(
        settings,
        provider="microsoft_graph",
        to=settings.smtp_to,
        attachments=attachment_names,
        total_bytes=total_size,
        subject=subject,
        correction=bool(report.get("correction")),
    )
    if report.get("oneTimePromptIncluded"):
        mark_one_time_prompt_used(settings, "mail")
    return {
        "ok": True,
        "provider": "microsoft_graph",
        "to": settings.smtp_to,
        "attachments": attachment_names,
        "totalBytes": total_size,
        "sentAt": status["lastSentAt"],
    }
