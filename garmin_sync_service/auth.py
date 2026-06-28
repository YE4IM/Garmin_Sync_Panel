from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


class AuthError(Exception):
    def __init__(self, status_code: int, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_local_password(password: str, *, iterations: int = 260_000, salt: str | None = None) -> str:
    salt_bytes = _b64_decode(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)
    return f"pbkdf2_sha256${iterations}${_b64_encode(salt_bytes)}${_b64_encode(digest)}"


def verify_local_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256" or iterations < 100_000:
        return False
    actual = hash_local_password(password, iterations=iterations, salt=salt).split("$", 3)[3]
    return hmac.compare_digest(actual, expected)


class LocalAuthClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _secret(self) -> bytes:
        secret = self.settings.local_auth_session_secret or self.settings.account_client_secret
        if not secret:
            raise AuthError(500, "LOCAL_AUTH_SESSION_SECRET is not configured")
        return secret.encode("utf-8")

    def _token(self, *, token_type: str, expires_in: int) -> str:
        now = int(time.time())
        payload = {
            "sub": self.settings.local_auth_username,
            "provider": "local",
            "type": token_type,
            "iat": now,
            "exp": now + expires_in,
        }
        body = _b64_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        signature = hmac.new(self._secret(), body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64_encode(signature)}"

    def _read_token(self, token: str, *, expected_type: str) -> dict[str, Any]:
        try:
            body, signature = token.split(".", 1)
        except ValueError as exc:
            raise AuthError(401, "登录状态已失效") from exc
        expected_signature = _b64_encode(hmac.new(self._secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected_signature):
            raise AuthError(401, "登录状态已失效")
        try:
            payload = json.loads(_b64_decode(body).decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError(401, "登录状态已失效") from exc
        if payload.get("type") != expected_type or payload.get("provider") != "local":
            raise AuthError(401, "登录状态已失效")
        if int(payload.get("exp") or 0) <= int(time.time()):
            raise AuthError(401, "登录状态已过期")
        return payload

    def _session_payload(self) -> dict[str, Any]:
        access_expires = max(self.settings.local_auth_session_hours, 1) * 3600
        refresh_expires = 30 * 24 * 3600
        return {
            "ok": True,
            "session": {
                "accessToken": self._token(token_type="access", expires_in=access_expires),
                "refreshToken": self._token(token_type="refresh", expires_in=refresh_expires),
                "expiresIn": access_expires,
            },
        }

    async def captcha(self) -> dict[str, Any]:
        raise AuthError(404, "本地登录不需要图形验证码")

    async def send_sms(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AuthError(404, "本地登录不支持短信验证码")

    async def login_password(self, phone: str, password: str) -> dict[str, Any]:
        username = str(phone or "").strip()
        if not self.settings.local_auth_password_hash:
            raise AuthError(500, "LOCAL_AUTH_PASSWORD_HASH is not configured")
        if username != self.settings.local_auth_username:
            raise AuthError(401, "用户名或密码错误")
        if not verify_local_password(password, self.settings.local_auth_password_hash):
            raise AuthError(401, "用户名或密码错误")
        return self._session_payload()

    async def login_sms(self, phone: str, code: str) -> dict[str, Any]:
        raise AuthError(404, "本地登录不支持短信验证码")

    async def register(self, phone: str, code: str, password: str, display_name: str = "") -> dict[str, Any]:
        raise AuthError(404, "本地登录不开放网页注册")

    async def reset_password(self, phone: str, code: str, new_password: str) -> dict[str, Any]:
        raise AuthError(404, "本地登录不开放网页重置密码")

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        self._read_token(refresh_token, expected_type="refresh")
        return self._session_payload()

    async def logout(self, access_token: str) -> None:
        return None

    async def introspect(self, access_token: str) -> dict[str, Any]:
        payload = self._read_token(access_token, expected_type="access")
        return {
            "active": True,
            "tokenType": "local",
            "clientId": "local",
            "user": {
                "username": payload.get("sub"),
                "displayName": payload.get("sub"),
                "provider": "local",
            },
        }

    def session_tokens(self, payload: dict[str, Any]) -> SessionTokens:
        session = payload.get("session") or {}
        return SessionTokens(
            access_token=str(session.get("accessToken") or ""),
            refresh_token=str(session.get("refreshToken") or ""),
            expires_in=int(session.get("expiresIn") or 3600),
        )

    def enforce_allowed_user(self, introspection: dict[str, Any]) -> dict[str, Any]:
        if introspection.get("active") is not True or introspection.get("tokenType") != "local":
            raise AuthError(401, "登录状态已失效")
        user = introspection.get("user") or {}
        if user.get("username") != self.settings.local_auth_username:
            raise AuthError(403, "该账号未授权访问 Garmin Sync")
        return user


class AccountClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token: str = "",
        service_client: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "X-WXY-Client-Id": (
                self.settings.account_service_client_id
                if service_client
                else self.settings.account_web_client_id
            )
        }
        if service_client:
            headers["X-WXY-Client-Secret"] = self.settings.account_client_secret
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{self.settings.account_auth_base_url}{path}"
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.request(method, url, headers=headers, json=json)
        payload = response.json() if response.content else {}
        if response.status_code >= 400 or payload.get("ok") is False:
            error = payload.get("error") or {}
            raise AuthError(response.status_code, error.get("message") or payload.get("message") or "account request failed", payload)
        return payload

    async def captcha(self) -> dict[str, Any]:
        return await self._request("GET", "/captcha")

    async def send_sms(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/sms/send", json=payload)

    async def login_password(self, phone: str, password: str) -> dict[str, Any]:
        return await self._request("POST", "/login/password", json={"phone": phone, "password": password})

    async def login_sms(self, phone: str, code: str) -> dict[str, Any]:
        return await self._request("POST", "/login/sms", json={"phone": phone, "code": code})

    async def register(self, phone: str, code: str, password: str, display_name: str = "") -> dict[str, Any]:
        return await self._request(
            "POST",
            "/register",
            json={
                "phone": phone,
                "code": code,
                "password": password,
                "displayName": display_name,
            },
        )

    async def reset_password(self, phone: str, code: str, new_password: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/password/reset",
            json={"phone": phone, "code": code, "newPassword": new_password},
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._request("POST", "/token/refresh", json={"refreshToken": refresh_token})

    async def logout(self, access_token: str) -> None:
        if access_token:
            await self._request("POST", "/logout", json={}, token=access_token)

    async def introspect(self, access_token: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/introspect",
            json={"token": access_token},
            service_client=True,
        )

    def session_tokens(self, payload: dict[str, Any]) -> SessionTokens:
        session = payload.get("session") or {}
        return SessionTokens(
            access_token=str(session.get("accessToken") or ""),
            refresh_token=str(session.get("refreshToken") or ""),
            expires_in=int(session.get("expiresIn") or 3600),
        )

    def enforce_allowed_user(self, introspection: dict[str, Any]) -> dict[str, Any]:
        user = introspection.get("user") or {}
        active = introspection.get("active") is True
        token_type = introspection.get("tokenType")
        client_id = introspection.get("clientId")
        phone = str(user.get("phone") or "")
        if not active or token_type != "opaque":
            raise AuthError(401, "登录状态已失效")
        if client_id != self.settings.account_web_client_id:
            raise AuthError(403, "登录令牌不是 Garmin Sync 网页端签发")
        if phone != self.settings.account_allowed_phone:
            raise AuthError(403, "该账号未授权访问 Garmin Sync")
        return user


def build_auth_client(settings: Settings):
    if settings.auth_provider == "wxylab":
        return AccountClient(settings)
    if settings.auth_provider == "local":
        return LocalAuthClient(settings)
    raise AuthError(500, f"Unsupported AUTH_PROVIDER: {settings.auth_provider}")
