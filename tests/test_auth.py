from pathlib import Path
from types import SimpleNamespace
import asyncio

import pytest
from fastapi import Response

from garmin_sync_service.auth import AccountClient, AuthError, LocalAuthClient, hash_local_password
from garmin_sync_service.config import Settings


ALLOWED_PHONE = "15500000000"


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        root_dir=tmp_path,
        activity_project_dir=tmp_path / "garmin-activity-sync",
        weight_project_dir=tmp_path / "garmin-weight-sync",
        runtime_dir=tmp_path / "runtime",
        reports_dir=tmp_path / "runtime" / "reports",
        logs_dir=tmp_path / "runtime" / "logs",
        python_bin="python",
        auth_provider="wxylab",
        local_auth_username="admin",
        local_auth_password_hash="",
        local_auth_session_secret="test-session-secret",
        local_auth_session_hours=12,
        account_auth_base_url="https://wxylab.ltd/api/wxylab/account/v1",
        account_web_client_id="garmin-sync-web",
        account_service_client_id="garmin-sync-service",
        account_client_secret="secret",
        account_allowed_phone=ALLOWED_PHONE,
        cookie_secure=True,
        cookie_name_access="access",
        cookie_name_refresh="refresh",
        public_base_url="",
        sync_activity_days=30,
        sync_health_days=14,
        daily_run_time="06:30",
        enable_scheduler=False,
        smtp_host="",
        smtp_port=465,
        smtp_username="",
        smtp_password="",
        smtp_from="",
        smtp_to="",
        smtp_tls=True,
        smtp_ssl=True,
        mail_attachment_limit_mb=20,
        mail_provider="smtp",
        microsoft_graph_client_id="",
        microsoft_graph_tenant_id="consumers",
        microsoft_graph_scopes="offline_access User.Read Mail.Send",
        request_timeout_seconds=20,
        command_timeout_seconds=1800,
        mimo_api_key="",
        mimo_api_url="https://api.xiaomimimo.com/v1/chat/completions",
        mimo_model="mimo-v2.5-pro",
        ai_analysis_cache_hours=6,
        ai_auto_analyze_after_sync=True,
    )


def local_settings_for(tmp_path: Path) -> Settings:
    settings = settings_for(tmp_path)
    return settings.__class__(**{
        **settings.__dict__,
        "auth_provider": "local",
        "local_auth_username": "admin",
        "local_auth_password_hash": hash_local_password("correct-password"),
        "local_auth_session_secret": "local-test-session-secret",
    })


def test_local_auth_login_refresh_and_introspect(tmp_path):
    client = LocalAuthClient(local_settings_for(tmp_path))
    payload = asyncio.run(client.login_password("admin", "correct-password"))
    tokens = client.session_tokens(payload)

    user = client.enforce_allowed_user(asyncio.run(client.introspect(tokens.access_token)))
    assert user["username"] == "admin"
    assert user["provider"] == "local"

    refreshed = asyncio.run(client.refresh(tokens.refresh_token))
    assert client.session_tokens(refreshed).access_token


def test_local_auth_rejects_bad_password(tmp_path):
    client = LocalAuthClient(local_settings_for(tmp_path))
    with pytest.raises(AuthError):
        asyncio.run(client.login_password("admin", "wrong-password"))


def test_enforce_allowed_user_accepts_only_expected_client_and_phone(tmp_path):
    client = AccountClient(settings_for(tmp_path))
    user = client.enforce_allowed_user({
        "active": True,
        "tokenType": "opaque",
        "clientId": "garmin-sync-web",
        "user": {"phone": ALLOWED_PHONE, "accountId": "acc"},
    })
    assert user["phone"] == ALLOWED_PHONE


@pytest.mark.parametrize(
    "payload",
    [
        {"active": False, "tokenType": "opaque", "clientId": "garmin-sync-web", "user": {"phone": ALLOWED_PHONE}},
        {"active": True, "tokenType": "legacy", "clientId": None, "user": {"phone": ALLOWED_PHONE}},
        {"active": True, "tokenType": "opaque", "clientId": "marathontracker", "user": {"phone": ALLOWED_PHONE}},
        {"active": True, "tokenType": "opaque", "clientId": "garmin-sync-web", "user": {"phone": "13800138000"}},
    ],
)
def test_enforce_allowed_user_rejects_other_tokens(tmp_path, payload):
    client = AccountClient(settings_for(tmp_path))
    with pytest.raises(AuthError):
        client.enforce_allowed_user(payload)


def test_finish_login_sets_cookies_on_returned_response(monkeypatch):
    from garmin_sync_service import web

    class FakeAccount:
        def session_tokens(self, payload):
            return SimpleNamespace(access_token="access-token", refresh_token="refresh-token", expires_in=3600)

        async def introspect(self, token):
            return {"active": True, "tokenType": "opaque", "clientId": "garmin-sync-web", "user": {"phone": ALLOWED_PHONE}}

        def enforce_allowed_user(self, payload):
            return payload["user"]

        async def logout(self, token):
            return None

    monkeypatch.setattr(web, "account", FakeAccount())
    response = asyncio.run(web._finish_login({"session": {}}, Response()))
    set_cookie_headers = [
        value.decode("latin1")
        for key, value in response.raw_headers
        if key.decode("latin1").lower() == "set-cookie"
    ]
    assert any("garmin_sync_access_token=access-token" in header for header in set_cookie_headers)
    assert any("garmin_sync_refresh_token=refresh-token" in header for header in set_cookie_headers)


def test_public_html_does_not_expose_allowed_phone():
    from garmin_sync_service.web import HTML

    assert ALLOWED_PHONE not in HTML
    assert "仅允许账号" not in HTML


def test_local_login_html_contains_username_password_only(monkeypatch, tmp_path):
    from garmin_sync_service import web

    monkeypatch.setattr(web, "settings", local_settings_for(tmp_path))
    login_html = web.render_html("login")
    assert "用户名" in login_html
    assert "密码" in login_html
    assert "图片验证码答案" not in login_html
    assert "发送短信验证码" not in login_html
    assert "注册并登录" not in login_html
    assert "onclick=\"resetPassword()\"" not in login_html

    assert "注册并登录" not in web.render_html("register")
    assert "onclick=\"resetPassword()\"" not in web.render_html("reset")


def test_wxylab_login_html_keeps_phone_register_and_reset(monkeypatch, tmp_path):
    from garmin_sync_service import web

    monkeypatch.setattr(web, "settings", settings_for(tmp_path))
    login_html = web.render_html("login")
    assert "手机号" in login_html
    assert "密码" in login_html
    assert "图片验证码答案" not in login_html
    assert "发送短信验证码" not in login_html
    assert "注册并登录" not in login_html
    assert "onclick=\"resetPassword()\"" not in login_html

    register_html = web.render_html("register")
    reset_html = web.render_html("reset")
    assert "注册并登录" in register_html
    assert "图片验证码答案" in register_html
    assert "onclick=\"resetPassword()\"" in reset_html


def test_dashboard_html_does_not_render_raw_health_json():
    from garmin_sync_service.web import render_html

    html = render_html("login")
    assert "<pre>" not in html
    assert "JSON.stringify(h" not in html
    assert "healthCards" in html
    assert "activity-card" in html


def test_dashboard_html_uses_lightweight_tabbed_layout():
    from garmin_sync_service.web import render_html

    html = render_html("login")
    assert "view-tabs" in html
    assert "chartCards" in html
    assert "tab-system" in html
    assert "tab-settings" in html
    assert "systemCards" in html
    assert "serviceHistory" in html
    assert "settingsCards" in html
    assert "ai-section" in html
    assert "dailyDistanceTrend" in html
    assert "lastMailSentAt" in html
    assert "oneTimePrompt" in html
    assert "chart-point" in html
    assert "chart-axis" in html
    assert "setChartReadout" in html
    assert "periodFilter" in html
    assert "setPeriodRange" in html
    assert "openChartDrilldown" in html
    assert "批量下载" in html
    assert "dailyDistanceBars" not in html
    assert "backdrop-filter" not in html
    assert "blur(" not in html
