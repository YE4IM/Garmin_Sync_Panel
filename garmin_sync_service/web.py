from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from .ai_analysis import generate_ai_analysis_if_needed
from .auth import AuthError, build_auth_client
from .config import settings
from .dashboard import activity_bulk_download_archive, activity_detail_payload, activity_download_archive, dashboard_payload, latest_report
from .one_time_prompt import save_one_time_prompt
from .preferences import save_personal_profile, settings_overview
from .reporting import generate_report, send_report_email
from .scheduler import DailyScheduler
from .system_status import record_service_status
from .sync_runner import SyncRunner


app = FastAPI(title="Garmin Sync", version="0.1.0")
account = build_auth_client(settings)
runner = SyncRunner(settings)
scheduler = DailyScheduler(settings, runner)


class PasswordLogin(BaseModel):
    phone: str
    password: str


class SmsSend(BaseModel):
    phone: str
    purpose: str = "login"
    captchaId: str
    captchaAnswer: str


class SmsLogin(BaseModel):
    phone: str
    code: str


class RegisterRequest(BaseModel):
    phone: str
    code: str
    password: str
    displayName: str = ""


class PasswordResetRequest(BaseModel):
    phone: str
    code: str
    newPassword: str


class PersonalProfileRequest(BaseModel):
    sex: str = ""
    age: str = ""
    heightCm: str = ""
    weightTargetKg: str = ""
    fitnessLevel: str = ""
    trainingGoal: str = ""
    background: str = ""
    healthNotes: str = ""


class OneTimePromptRequest(BaseModel):
    prompt: str = ""


def _model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _auth_error(exc: AuthError) -> JSONResponse:
    return JSONResponse({"ok": False, "message": str(exc), "account": exc.payload}, status_code=exc.status_code)


def _enforce_allowed_phone(phone: str) -> None:
    if str(phone or "").strip() != settings.account_allowed_phone:
        raise AuthError(403, "该账号未授权访问 Garmin Sync")


def _set_cookies(response: Response, tokens) -> None:
    secure = settings.cookie_secure
    response.set_cookie(
        settings.cookie_name_access,
        tokens.access_token,
        max_age=max(tokens.expires_in, 60),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.cookie_name_refresh,
        tokens.refresh_token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(settings.cookie_name_access, path="/")
    response.delete_cookie(settings.cookie_name_refresh, path="/")


async def _require_user(request: Request, response: Response) -> dict[str, Any]:
    access = request.cookies.get(settings.cookie_name_access, "")
    refresh = request.cookies.get(settings.cookie_name_refresh, "")
    if access:
        try:
            return account.enforce_allowed_user(await account.introspect(access))
        except AuthError:
            pass
    if refresh:
        try:
            refreshed = await account.refresh(refresh)
            tokens = account.session_tokens(refreshed)
            user = account.enforce_allowed_user(await account.introspect(tokens.access_token))
            _set_cookies(response, tokens)
            return user
        except AuthError:
            _clear_cookies(response)
    raise HTTPException(status_code=401, detail="not logged in")


@app.on_event("startup")
async def _startup() -> None:
    if settings.enable_scheduler:
        scheduler.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    scheduler.stop()


@app.get("/health")
async def health() -> dict[str, Any]:
    record_service_status(settings)
    return {
        "ok": True,
        "service": "garmin-sync",
        "scheduler": settings.enable_scheduler,
        "authProvider": settings.auth_provider,
        "accountClientId": settings.account_web_client_id,
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return render_html("login")


@app.get("/login", response_class=HTMLResponse)
async def login_page() -> str:
    return render_html("login")


@app.get("/register", response_class=HTMLResponse)
async def register_page() -> str:
    return render_html("register")


@app.get("/password-reset", response_class=HTMLResponse)
async def password_reset_page() -> str:
    return render_html("reset")


@app.get("/api/auth/captcha")
async def captcha() -> JSONResponse:
    try:
        return JSONResponse(await account.captcha())
    except AuthError as exc:
        return _auth_error(exc)


@app.post("/api/auth/sms/send")
async def send_sms(body: SmsSend) -> JSONResponse:
    try:
        _enforce_allowed_phone(body.phone)
        return JSONResponse(await account.send_sms(_model_payload(body)))
    except AuthError as exc:
        return _auth_error(exc)


async def _finish_login(payload: dict[str, Any], response: Response) -> JSONResponse:
    tokens = account.session_tokens(payload)
    try:
        user = account.enforce_allowed_user(await account.introspect(tokens.access_token))
    except AuthError as exc:
        await account.logout(tokens.access_token)
        return _auth_error(exc)
    login_response = JSONResponse({"ok": True, "user": user})
    _set_cookies(login_response, tokens)
    return login_response


@app.post("/api/auth/login/password")
async def login_password(body: PasswordLogin, response: Response) -> JSONResponse:
    try:
        payload = await account.login_password(body.phone, body.password)
        return await _finish_login(payload, response)
    except AuthError as exc:
        return _auth_error(exc)


@app.post("/api/auth/login/sms")
async def login_sms(body: SmsLogin, response: Response) -> JSONResponse:
    try:
        payload = await account.login_sms(body.phone, body.code)
        return await _finish_login(payload, response)
    except AuthError as exc:
        return _auth_error(exc)


@app.post("/api/auth/register")
async def register(body: RegisterRequest, response: Response) -> JSONResponse:
    try:
        _enforce_allowed_phone(body.phone)
        payload = await account.register(body.phone, body.code, body.password, body.displayName)
        return await _finish_login(payload, response)
    except AuthError as exc:
        return _auth_error(exc)


@app.post("/api/auth/password/reset")
async def reset_password(body: PasswordResetRequest) -> JSONResponse:
    try:
        _enforce_allowed_phone(body.phone)
        return JSONResponse(await account.reset_password(body.phone, body.code, body.newPassword))
    except AuthError as exc:
        return _auth_error(exc)


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(settings.cookie_name_access, "")
    if token:
        try:
            await account.logout(token)
        except AuthError:
            pass
    _clear_cookies(response)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(request: Request, response: Response) -> dict[str, Any]:
    return {"ok": True, "user": await _require_user(request, response)}


@app.get("/api/dashboard")
async def dashboard(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    record_service_status(settings)
    data = dashboard_payload(
        settings,
        range_type=request.query_params.get("rangeType"),
        year=request.query_params.get("year"),
        month=request.query_params.get("month"),
        quarter=request.query_params.get("quarter"),
        week_start=request.query_params.get("weekStart"),
    )
    data["syncStatus"] = runner.status()
    return {"ok": True, "data": data}


@app.get("/api/sync/status")
async def sync_status(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    return {"ok": True, "status": runner.status()}


@app.post("/api/sync/run")
async def run_sync(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    result = await asyncio.to_thread(runner.run_all)
    ai = None
    if result.get("ok") and settings.ai_auto_analyze_after_sync:
        payload = dashboard_payload(settings, include_long_range=True)
        payload["syncStatus"] = runner.status()
        ai = await asyncio.to_thread(
            generate_ai_analysis_if_needed,
            settings,
            payload,
            source_finished_at=str(result.get("finishedAt") or ""),
        )
    return {"ok": bool(result.get("ok")), "result": result, "ai": ai}


@app.post("/api/reports/generate")
async def report_now(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    report = await asyncio.to_thread(generate_report, settings, runner.last_run())
    mail = await asyncio.to_thread(send_report_email, settings, report)
    return {"ok": True, "report": report, "mail": mail}


@app.post("/api/ai/analyze")
async def ai_analyze(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    payload = dashboard_payload(settings, include_long_range=True)
    payload["syncStatus"] = runner.status()
    source_finished_at = str((payload.get("lastRun") or {}).get("finishedAt") or "")
    analysis = await asyncio.to_thread(
        generate_ai_analysis_if_needed,
        settings,
        payload,
        source_finished_at=source_finished_at,
        force=True,
    )
    return {"ok": bool(analysis.get("ok")), "analysis": analysis}


@app.get("/api/settings")
async def get_settings(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    return {"ok": True, "settings": settings_overview(settings)}


@app.post("/api/settings/profile")
async def update_profile(body: PersonalProfileRequest, request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    profile = save_personal_profile(settings, _model_payload(body))
    return {"ok": True, "profile": profile, "settings": settings_overview(settings)}


@app.post("/api/settings/one-time-prompt")
async def update_one_time_prompt(body: OneTimePromptRequest, request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    prompt = save_one_time_prompt(settings, body.prompt)
    return {"ok": True, "oneTimePrompt": {key: value for key, value in prompt.items() if key != "prompt"}, "settings": settings_overview(settings)}


@app.get("/api/activities/{activity_id}")
async def activity_detail(activity_id: str, request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    detail = activity_detail_payload(settings, activity_id)
    if not detail:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "data": detail}


@app.get("/api/activities/{activity_id}/download")
async def download_activity(activity_id: str, request: Request, response: Response) -> FileResponse:
    await _require_user(request, response)
    archive = activity_download_archive(settings, activity_id)
    if not archive:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(archive["path"], media_type="application/zip", filename=archive["name"])


@app.get("/api/activities/download/bulk")
async def download_activities_bulk(request: Request, response: Response) -> FileResponse:
    await _require_user(request, response)
    try:
        limit = int(request.query_params.get("limit", "200"))
    except ValueError:
        limit = 200
    archive = activity_bulk_download_archive(settings, limit=limit)
    if not archive:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(archive["path"], media_type="application/zip", filename=archive["name"])


@app.get("/api/reports/latest")
async def report_latest(request: Request, response: Response) -> dict[str, Any]:
    await _require_user(request, response)
    return {"ok": True, "report": latest_report(settings)}


@app.get("/reports/{name}")
async def download_report(name: str, request: Request, response: Response) -> FileResponse:
    await _require_user(request, response)
    if "/" in name or "\\" in name or not name.startswith("garmin-daily-"):
        raise HTTPException(status_code=404, detail="not found")
    path = settings.reports_dir / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    if path.is_dir():
        readme = path / "README_ATTACHMENTS.md"
        if not readme.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(readme, media_type="text/markdown", filename=readme.name)
    if path.suffix != ".zip":
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="application/zip", filename=name)


@app.get("/reports/{name}/{file_name}")
async def download_report_file(name: str, file_name: str, request: Request, response: Response) -> FileResponse:
    await _require_user(request, response)
    if "/" in name or "\\" in name or "/" in file_name or "\\" in file_name or not name.startswith("garmin-daily-"):
        raise HTTPException(status_code=404, detail="not found")
    if not file_name.endswith((".json", ".csv", ".md", ".txt")):
        raise HTTPException(status_code=404, detail="not found")
    path = settings.reports_dir / name / file_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type = "application/json" if file_name.endswith(".json") else "text/csv" if file_name.endswith(".csv") else "text/plain"
    return FileResponse(path, media_type=media_type, filename=file_name)


AUTH_FORMS = {
    "login": r"""
    <section id="authPage" class="auth-wrap hidden">
      <div class="panel stack">
        <h2>登录</h2>
        <input id="loginPhone" inputmode="tel" autocomplete="username" placeholder="手机号">
        <input id="loginPassword" type="password" autocomplete="current-password" placeholder="密码">
        <button id="loginBtn" type="button" onclick="loginPassword()">登录</button>
        <div class="link-row"><a href="register">注册账号</a><a href="password-reset">重置密码</a></div>
        <div id="loginMsg" class="msg"></div>
      </div>
    </section>
    """,
    "register": r"""
    <section id="authPage" class="auth-wrap hidden">
      <div class="panel stack">
        <h2>注册</h2>
        <input id="registerPhone" inputmode="tel" autocomplete="username" placeholder="手机号">
        <input id="registerName" placeholder="显示名称（可选）">
        <div class="row"><img id="registerCaptchaImg" class="captcha hidden" alt=""><button class="light" type="button" onclick="loadCaptcha('register')">刷新验证码</button></div>
        <input id="registerCaptchaAnswer" inputmode="numeric" placeholder="图片验证码答案">
        <button class="light" type="button" onclick="sendSms('register')">发送短信验证码</button>
        <input id="registerCode" inputmode="numeric" placeholder="短信验证码">
        <input id="registerPassword" type="password" autocomplete="new-password" placeholder="设置密码（8-64 位）">
        <button type="button" onclick="registerAccount()">注册并登录</button>
        <div class="link-row"><a href="login">返回登录</a><a href="password-reset">重置密码</a></div>
        <div id="registerMsg" class="msg"></div>
      </div>
    </section>
    """,
    "reset": r"""
    <section id="authPage" class="auth-wrap hidden">
      <div class="panel stack">
        <h2>重置密码</h2>
        <input id="resetPhone" inputmode="tel" autocomplete="username" placeholder="手机号">
        <div class="row"><img id="resetCaptchaImg" class="captcha hidden" alt=""><button class="light" type="button" onclick="loadCaptcha('reset')">刷新验证码</button></div>
        <input id="resetCaptchaAnswer" inputmode="numeric" placeholder="图片验证码答案">
        <button class="light" type="button" onclick="sendSms('reset')">发送短信验证码</button>
        <input id="resetCode" inputmode="numeric" placeholder="短信验证码">
        <input id="resetPassword" type="password" autocomplete="new-password" placeholder="新密码（8-64 位）">
        <button type="button" onclick="resetPassword()">重置密码</button>
        <div class="link-row"><a href="login">返回登录</a><a href="register">注册账号</a></div>
        <div id="resetMsg" class="msg"></div>
      </div>
    </section>
    """,
}

LOCAL_AUTH_FORMS = {
    "login": r"""
    <section id="authPage" class="auth-wrap hidden">
      <div class="panel stack">
        <h2>登录</h2>
        <input id="loginIdentity" autocomplete="username" placeholder="用户名">
        <input id="loginPassword" type="password" autocomplete="current-password" placeholder="密码">
        <button id="loginBtn" type="button" onclick="loginPassword()">登录</button>
        <div id="loginMsg" class="msg"></div>
      </div>
    </section>
    """,
}


HTML_SHELL = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Garmin Sync</title>
  <style>
    :root{color-scheme:light;--bg:#fff7ed;--panel:#fff;--ink:#1d1d1f;--muted:#6e6e73;--line:#f0d8bd;--orange:#ff7a1a;--orange-strong:#e85d04;--orange-soft:#fff1df;--blue:#0a84ff;--blue-soft:#e7f1ff;--green:#30a46c;--green-soft:#e9f7ef;--red:#ff3b30;--red-soft:#fff0ee;--violet:#af52de;--cyan:#32ade6;--pink:#ff2d55;--yellow:#ffcc00;--shadow:0 2px 8px rgba(108,74,32,.07)}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    header{height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 22px;background:#fff;color:var(--ink);border-bottom:1px solid var(--line)}
    main{max-width:1280px;margin:0 auto;padding:18px}.brand{font-weight:800;letter-spacing:.2px}.muted{color:var(--muted)}.hidden{display:none!important}
    .auth-wrap{max-width:440px;margin:24px auto}.panel,.summary-card,.health-card,.activity-card,.report-card,.chart-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;box-shadow:var(--shadow)}
    input,button,textarea,select{min-height:40px;border-radius:10px;border:1px solid var(--line);padding:0 10px;font:inherit}textarea{min-height:88px;padding:10px;resize:vertical}input,textarea,select{background:#fff}input:focus,textarea:focus,select:focus{outline:2px solid #ffd3a6;border-color:var(--orange)}button{border:0;background:var(--orange);color:white;font-weight:700;cursor:pointer}button:hover{background:var(--orange-strong)}button.light{background:#fff;color:#a64a00;border:1px solid var(--line)}button.danger{background:var(--red)}button.subtle{height:34px;background:var(--orange-soft);color:#a64a00}
    .stack{display:grid;gap:14px}.row,.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.toolbar{margin-bottom:4px}.msg{min-height:20px}.err{color:var(--red)}.ok{color:var(--green)}img.captcha{height:38px;border:1px solid var(--line);border-radius:7px;background:white}
    a{color:var(--orange-strong);text-decoration:none}.link-row{display:flex;justify-content:space-between;gap:12px;margin-top:2px}.hint{font-size:13px;color:var(--muted)}
    .summary-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}.summary-card{position:relative;overflow:hidden}.summary-card:before,.health-card:before{content:"";display:block;height:4px;border-radius:999px;background:var(--orange);margin:-16px -16px 13px}.summary-card:nth-child(2):before,.health-card:nth-child(2):before{background:var(--blue)}.summary-card:nth-child(3):before,.health-card:nth-child(3):before{background:var(--green)}.summary-card:nth-child(4):before,.health-card:nth-child(4):before{background:var(--violet)}.summary-card:nth-child(5):before,.health-card:nth-child(5):before{background:#ffcc00}.summary-card span,.health-card span{display:block;color:var(--muted);font-size:13px}.summary-card b{display:block;margin-top:6px;font-size:28px;line-height:1.1}.summary-card small{display:block;margin-top:8px;color:var(--muted)}
    .sync-panel{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:grid;gap:10px;box-shadow:var(--shadow)}.sync-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.sync-title{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.sync-title b{font-size:18px}.sync-badge{display:inline-flex;align-items:center;height:26px;border-radius:999px;padding:0 10px;font-size:12px;font-weight:800;background:var(--orange-soft);color:#a64a00}.sync-badge.running{background:var(--blue-soft);color:#0057c2}.sync-badge.success{background:var(--green-soft);color:#137a4b}.sync-badge.failed{background:var(--red-soft);color:#bf2a21}.sync-progress{height:8px;border-radius:999px;background:var(--orange-soft);overflow:hidden}.sync-progress div{height:100%;width:0;background:var(--orange);transition:width .18s ease}.sync-meta{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.sync-meta span{display:block;color:var(--muted);font-size:12px}.sync-meta b{display:block;margin-top:2px;font-size:14px;word-break:break-word}
	    .view-tabs,.range-tabs{display:flex;gap:8px;overflow:auto;padding:4px;background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.view-tabs button,.range-tabs button{height:36px;min-width:88px;border-radius:10px;background:#fff;color:#8a4300;box-shadow:none}.view-tabs button.active,.range-tabs button.active{background:var(--orange);color:#fff}.range-tabs{box-shadow:none;justify-self:start}.view-section{display:grid;gap:14px}
	    .period-filter{display:grid;gap:10px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px;box-shadow:var(--shadow)}.period-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.period-controls select{min-width:116px}.period-label{font-weight:800;color:#8a4300}.period-note{color:var(--muted);font-size:12px}
    .chart-grid{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:12px}.chart-card h3{margin:0 0 12px;font-size:17px}.hbar-list{display:grid;gap:10px}.hbar-row{display:grid;gap:5px}.hbar-top{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}.hbar-track{height:10px;background:#fff8ef;border-radius:999px;overflow:hidden}.hbar-fill{height:100%;background:var(--blue);border-radius:999px}.hbar-axis{display:flex;justify-content:space-between;margin-top:8px;color:var(--muted);font-size:11px}.line-chart{display:grid;gap:10px}.chart-scroll{overflow-x:auto;padding-bottom:3px}.chart-scroll svg{min-width:520px}.line-chart svg,.mini-trend svg{width:100%;display:block}.chart-point{cursor:pointer;outline:none}.chart-point:focus{stroke:#1d1d1f;stroke-width:2px}.chart-gridline{stroke:#f2dfca;stroke-width:1}.chart-axis{stroke:#caa987;stroke-width:1.2}.chart-label{fill:#6e6e73;font-size:11px}.chart-readout{min-height:24px;border-radius:10px;background:#fffaf5;border:1px solid #ffe0bd;padding:6px 8px;color:var(--muted);font-size:13px}.chart-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.chart-metrics div{background:#fff8ef;border:1px solid #ffe0bd;border-radius:10px;padding:8px}.chart-metrics span{display:block;color:var(--muted);font-size:12px}.chart-metrics b{display:block;margin-top:2px}.axis-row{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}.trend-badge{display:inline-flex;align-items:center;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:700;background:var(--orange-soft);color:#a64a00}.trend-badge.up{background:var(--green-soft);color:#137a4b}.trend-badge.down{background:var(--blue-soft);color:#0057c2}.trend-badge.flat{background:#f3f4f6;color:#60646c}.trend-range{margin:8px 0 0;color:var(--muted);font-size:12px}.mini-trend{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}.ai-card{display:grid;gap:10px}.ai-content.empty{color:var(--muted)}.ai-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.ai-section{border:1px solid var(--line);border-radius:12px;background:#fffaf5;padding:14px}.ai-section h3{margin:0 0 10px;font-size:16px}.ai-item{display:grid;gap:4px;border-top:1px solid #f5dfc7;padding-top:10px;margin-top:10px}.ai-item:first-of-type{border-top:0;padding-top:0}.ai-item b{font-size:14px}.ai-tone{display:inline-flex;width:8px;height:8px;border-radius:50%;background:var(--orange);margin-right:6px}.ai-tone.good{background:var(--green)}.ai-tone.warn{background:var(--red)}.ai-meta{color:var(--muted);font-size:12px}
    .dashboard-layout{display:grid;grid-template-columns:minmax(300px,.8fr) minmax(0,1.4fr);gap:18px;align-items:start}.section-title{display:flex;align-items:end;justify-content:space-between;margin:8px 0 10px}.section-title h2{margin:0;font-size:20px}.health-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.health-card b{display:block;margin-top:6px;font-size:24px;line-height:1.15}.metric-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}.metric-row div{border-top:1px solid var(--line);padding-top:8px}.metric-row strong{display:block;font-size:15px}
    .activity-list{display:grid;gap:12px}.activity-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center}.activity-title{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.activity-title h3{margin:0;font-size:18px}.chip{display:inline-flex;align-items:center;height:24px;border-radius:999px;background:var(--orange-soft);color:#a64a00;padding:0 8px;font-size:12px;font-weight:700}.activity-meta{display:grid;grid-template-columns:repeat(6,minmax(80px,1fr));gap:10px;margin-top:12px}.mini-metric{border-radius:10px;padding:8px 10px;background:#fff8ef;border:1px solid #ffe0bd}.mini-metric span{display:block;color:var(--muted);font-size:12px}.mini-metric b{display:block;margin-top:2px;font-size:16px}.mini-metric.distance{background:#fff3e8;border-color:#ffd5a6}.mini-metric.pace{background:#eaf3ff;border-color:#c8defc}.mini-metric.hr{background:#fff0ee;border-color:#ffd1cc}.mini-metric.cadence{background:#f6ecff;border-color:#e8d0fa}.mini-metric.calories{background:#fff9db;border-color:#f8e790}.mini-metric.elevation{background:#e9f7ef;border-color:#c5ead6}.mini-metric.source{background:#f3f4f6;border-color:#e4e6eb}.activity-actions{display:flex;gap:8px;align-items:center}.action-link{display:inline-flex;height:34px;align-items:center;border-radius:10px;background:var(--orange-soft);color:#a64a00;padding:0 10px;font-weight:700}.report-card{display:flex;align-items:center;justify-content:space-between;gap:12px}.system-grid,.settings-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.settings-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.settings-card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px;box-shadow:var(--shadow)}.settings-card h3{margin:0 0 12px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.form-field{display:grid;gap:5px}.form-field.full{grid-column:1/-1}.form-field label{color:var(--muted);font-size:12px}.check-list{display:grid;gap:8px}.check-row{display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--line);padding-top:8px}.check-row:first-child{border-top:0;padding-top:0}.usage-track{height:8px;background:#fff3e8;border-radius:999px;overflow:hidden;margin-top:10px}.usage-fill{height:100%;background:var(--green);border-radius:999px}.usage-fill.warn{background:#ff9f0a}.usage-fill.bad{background:var(--red)}.history-list{display:grid;gap:8px}.history-row{display:flex;align-items:center;justify-content:space-between;border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff}.history-row span:first-child{display:flex;align-items:center;min-width:0}.history-row b{white-space:nowrap}.status-dot{width:10px;height:10px;border-radius:999px;background:var(--green);display:inline-block;margin-right:8px;flex:0 0 auto}.status-dot.bad{background:var(--red)}.empty{color:var(--muted);padding:14px 0}
    dialog{border:1px solid var(--line);border-radius:12px;padding:0;max-width:860px;width:calc(100% - 32px);background:#fff;box-shadow:0 8px 28px rgba(108,74,32,.18)}dialog::backdrop{background:rgba(68,45,18,.24)}.dialog-body{padding:18px}.dialog-head{display:flex;align-items:start;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding:16px 18px;background:#fff8ef}.dialog-head h2{margin:0}.lap-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:12px}.lap-card{border:1px solid var(--line);border-radius:10px;padding:10px;background:#fffaf5}.lap-card b{display:block}.lap-card span{display:block;color:var(--muted);font-size:12px;margin-top:3px}
    @media(max-width:1100px){.summary-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.chart-grid,.dashboard-layout{grid-template-columns:1fr}.health-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.activity-meta{grid-template-columns:repeat(3,minmax(80px,1fr))}.sync-meta{grid-template-columns:repeat(2,minmax(0,1fr))}.system-grid,.settings-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.ai-grid{grid-template-columns:1fr}}
    @media(max-width:720px){header{padding:0 14px}main{padding:12px}.auth-wrap{margin:12px auto}.summary-grid,.health-grid,.system-grid,.settings-grid,.form-grid,.chart-metrics{grid-template-columns:1fr}.activity-card{grid-template-columns:1fr}.activity-actions{justify-content:flex-start}.activity-meta{grid-template-columns:repeat(2,minmax(80px,1fr))}.report-card{align-items:flex-start;flex-direction:column}.sync-meta{grid-template-columns:1fr}.view-tabs button{min-width:72px}}
  </style>
</head>
<body>
  <header><div class="brand">Garmin Sync</div><div id="userLine" class="muted"></div></header>
  <main>
    __AUTH_FORM__

    <section id="app" class="hidden stack">
      <div class="toolbar">
        <button onclick="loadDashboard()">刷新</button>
        <button class="light" onclick="runSync()">立即同步</button>
        <button class="light" onclick="generateReport()">生成并发送邮件</button>
        <button class="danger" onclick="logout()">退出</button>
        <span id="status" class="muted"></span>
      </div>
      <section class="sync-panel">
        <div class="sync-head">
          <div class="sync-title"><span id="syncBadge" class="sync-badge">读取中</span><b id="syncStatusText">同步状态</b></div>
          <span id="syncMessage" class="muted"></span>
        </div>
        <div class="sync-progress"><div id="syncProgressBar"></div></div>
        <div class="sync-meta">
          <div><span>当前步骤</span><b id="syncStep">-</b></div>
          <div><span>上次同步</span><b id="lastSyncAt">-</b></div>
          <div><span>上次成功</span><b id="lastSuccessAt">-</b></div>
          <div><span>上次邮件</span><b id="lastMailSentAt">-</b></div>
          <div><span>每日计划</span><b id="dailyRunTime">-</b></div>
          <div><span>状态更新时间</span><b id="syncUpdatedAt">-</b></div>
        </div>
      </section>
      <nav class="view-tabs" aria-label="数据视图">
        <button id="tab-overview" class="active" type="button" onclick="switchView('overview')">概览</button>
        <button id="tab-health" type="button" onclick="switchView('health')">健康</button>
        <button id="tab-activities" type="button" onclick="switchView('activities')">运动</button>
        <button id="tab-system" type="button" onclick="switchView('system')">系统</button>
	        <button id="tab-settings" type="button" onclick="switchView('settings')">设置</button>
	        <button id="tab-report" type="button" onclick="switchView('report')">报告</button>
	      </nav>
	      <section id="periodFilter" class="period-filter"></section>
	      <section id="view-overview" class="view-section">
	        <div id="summaryCards" class="summary-grid"></div>
	        <div id="activityRangeCards" class="summary-grid"></div>
	        <div id="chartCards" class="chart-grid"></div>
        <section class="chart-card ai-card">
          <div class="section-title"><h2>AI 状态分析</h2><button id="aiBtn" class="light" type="button" onclick="refreshAiAnalysis()">刷新 AI 分析</button></div>
          <div id="aiAnalysis" class="ai-content empty"></div>
        </section>
      </section>
	      <section id="view-health" class="view-section hidden">
	        <div class="section-title"><h2 id="healthTitle">健康趋势</h2><span id="healthDate" class="muted"></span></div>
	        <div id="healthCards" class="health-grid"></div>
	      </section>
      <section id="view-activities" class="view-section hidden">
        <div class="section-title"><h2>最近运动</h2><div class="row"><button class="subtle" type="button" onclick="downloadBulkActivities()">批量下载</button><span id="activityCount" class="muted"></span></div></div>
        <div id="activities" class="activity-list"></div>
      </section>
      <section id="view-system" class="view-section hidden">
        <div class="section-title"><h2>系统状态</h2><span id="systemUpdatedAt" class="muted"></span></div>
        <div id="systemCards" class="system-grid"></div>
        <section class="chart-card"><h3>服务健康历史</h3><div id="serviceHistory" class="history-list"></div></section>
      </section>
      <section id="view-settings" class="view-section hidden">
        <div class="section-title"><h2>设置</h2><span id="settingsMsg" class="muted"></span></div>
        <div id="settingsCards" class="settings-grid"></div>
      </section>
      <section id="view-report" class="view-section hidden">
        <section class="report-card"><div><h3>报告附件</h3><div id="report" class="muted"></div></div></section>
      </section>
    </section>
    <dialog id="activityDialog">
      <div class="dialog-head">
        <div><h2 id="dialogTitle">运动详情</h2><div id="dialogMeta" class="muted"></div></div>
        <button class="subtle" type="button" onclick="closeActivityDialog()">关闭</button>
      </div>
      <div id="dialogBody" class="dialog-body stack"></div>
    </dialog>
  </main>
  <script>
    const $=id=>document.getElementById(id);
    const BASE=location.pathname.startsWith('/garmin-sync')?'/garmin-sync':'';
    const PAGE='__PAGE__';
    const captchaIds={register:'',reset:''};
    let syncTimer=null;
	    let currentData=null;
	    let settingsData=null;
	    let activeView='overview';
	    let periodState={rangeType:'month',year:'',month:'',quarter:'',weekStart:''};
	    const PERIOD_RANGES=[['week','周'],['month','月'],['quarter','季度'],['year','年'],['all','全部']];
    async function req(path, opts={}){const r=await fetch(BASE+path,{headers:{'Content-Type':'application/json'},...opts});const j=await r.json().catch(()=>({ok:false,message:'响应解析失败'}));if(!r.ok||j.ok===false)throw new Error(j.message||j.detail||'请求失败');return j}
    function showApp(){const auth=$('authPage');if(auth)auth.classList.add('hidden');$('app').classList.remove('hidden')}
    function showAuth(){$('app').classList.add('hidden');const auth=$('authPage');if(auth)auth.classList.remove('hidden')}
    function msg(scope,t,cls=''){const el=$(scope+'Msg');if(!el)return;el.textContent=t;el.className='msg '+cls}
    function setBusy(id,busy){const el=$(id);if(el)el.disabled=busy}
    async function boot(){try{await req('/api/auth/me');showApp();$('userLine').textContent='已登录';await loadDashboard()}catch{showAuth();$('userLine').textContent='';if(PAGE==='register'||PAGE==='reset')loadCaptcha(PAGE).catch(()=>{})}}
    async function loadCaptcha(scope){const img=$(scope+'CaptchaImg');const j=await req('/api/auth/captcha');captchaIds[scope]=j.captchaId;if(img){img.src=j.imageDataUrl;img.classList.remove('hidden')}}
    async function loginPassword(){const identity=(($('loginIdentity')?.value||$('loginPhone')?.value||'')+'').trim();setBusy('loginBtn',true);try{await req('/api/auth/login/password',{method:'POST',body:JSON.stringify({phone:identity,password:$('loginPassword')?.value||''})});msg('login','登录成功','ok');await boot()}catch(e){msg('login',e.message,'err')}finally{setBusy('loginBtn',false)}}
    async function sendSms(scope){const purpose=scope==='register'?'register':'reset_password';try{await req('/api/auth/sms/send',{method:'POST',body:JSON.stringify({phone:($(scope+'Phone')?.value||'').trim(),purpose,captchaId:captchaIds[scope],captchaAnswer:($(scope+'CaptchaAnswer')?.value||'').trim()})});msg(scope,'验证码已发送','ok');await loadCaptcha(scope)}catch(e){msg(scope,e.message,'err');loadCaptcha(scope).catch(()=>{})}}
    async function registerAccount(){try{await req('/api/auth/register',{method:'POST',body:JSON.stringify({phone:($('registerPhone')?.value||'').trim(),displayName:($('registerName')?.value||'').trim(),code:($('registerCode')?.value||'').trim(),password:$('registerPassword')?.value||''})});msg('register','注册成功','ok');await boot()}catch(e){msg('register',e.message,'err')}}
    async function resetPassword(){try{await req('/api/auth/password/reset',{method:'POST',body:JSON.stringify({phone:($('resetPhone')?.value||'').trim(),code:($('resetCode')?.value||'').trim(),newPassword:$('resetPassword')?.value||''})});msg('reset','密码已重置，请返回登录','ok')}catch(e){msg('reset',e.message,'err')}}
    async function logout(){await req('/api/auth/logout',{method:'POST',body:'{}'}).catch(()=>{});location.href=BASE+'/login'}
	    async function loadDashboard(){const qs=dashboardQuery();const j=await req('/api/dashboard'+(qs?'?'+qs:''));render(j.data)}
	    function dashboardQuery(){const p=new URLSearchParams();Object.entries(periodState).forEach(([k,v])=>{if(v!==undefined&&v!==null&&v!=='')p.set(k,v)});return p.toString()}
	    function render(d){currentData=d;syncPeriodState(d.selectedRange||{});renderSyncStatus(d.syncStatus||{});renderMailSchedule(d);renderPeriodFilter(d);renderActiveView();$('status').textContent='数据更新于 '+(d.generatedAt||'')}
    function switchView(view){activeView=view;['overview','health','activities','system','settings','report'].forEach(name=>{const panel=$('view-'+name),tab=$('tab-'+name);if(panel)panel.classList.toggle('hidden',name!==view);if(tab)tab.classList.toggle('active',name===view)});renderActiveView()}
	    function renderActiveView(){if(!currentData)return;if(activeView==='overview'){renderSummary(currentData);renderCharts(currentData);renderAiAnalysis(currentData.aiAnalysis||{})}else if(activeView==='health'){renderHealth(currentData)}else if(activeView==='activities'){renderActivities((currentData.activityRange||{}).activities||currentData.activities||[])}else if(activeView==='system'){renderSystem(currentData.systemStatus||{})}else if(activeView==='settings'){renderSettings()}else if(activeView==='report'){renderReport(currentData.latestReport)}}
    async function refreshSyncStatus(){try{const j=await req('/api/sync/status');renderSyncStatus(j.status||{})}catch(e){$('syncMessage').textContent=e.message}}
    function startSyncPolling(){if(syncTimer)return;syncTimer=setInterval(refreshSyncStatus,2000)}
    function stopSyncPolling(){if(!syncTimer)return;clearInterval(syncTimer);syncTimer=null}
    function renderSyncStatus(st){const state=st.state||'idle',running=!!st.running,progress=st.progress||{},pct=Math.max(0,Math.min(100,Number(progress.percent||0)));const badge=$('syncBadge');badge.className='sync-badge '+(running?'running':state);badge.textContent=running?'同步中':state==='success'?'已完成':state==='failed'?'失败':'空闲';$('syncStatusText').textContent=running?'正在同步数据':state==='success'?'最近同步成功':state==='failed'?'最近同步失败':'等待同步';$('syncMessage').textContent=st.message||'';$('syncStep').textContent=st.currentStepLabel||'-';$('lastSyncAt').textContent=formatDateTime(st.lastSyncAt||st.finishedAt);$('lastSuccessAt').textContent=formatDateTime(st.lastSuccessAt);$('syncUpdatedAt').textContent=formatDateTime(st.updatedAt);$('syncProgressBar').style.width=pct+'%';if(running)startSyncPolling();else stopSyncPolling()}
    function renderMailSchedule(d){const mail=d.mailStatus||{},schedule=d.schedule||{};$('lastMailSentAt').textContent=formatDateTime(mail.lastSentAt);$('dailyRunTime').textContent=schedule.dailyRunTime||'-'}
    function renderSummary(d){const s=d.activityStats||{},l7=s.last7Days||{},l30=s.last30Days||{},w=d.weight||{},latest=w.latest||{},weight=pick(latest,'Weight','weight_kg'),change=w.changeKg;const changeText=change===null||change===undefined?'':(change>0?'+':'')+change+' kg';const cards=[
      ['总运动',present(s.total),'运动记录总数'],
      ['7 天距离',kmValue(l7.distanceKm),present(l7.activities)+' 次 · '+durationFromMinutes(l7.durationMin)],
      ['7 天热量',present(l7.calories,'0')+' kcal','爬升 '+present(l7.elevationGainM,'0')+' m'],
      ['30 天距离',kmValue(l30.distanceKm),present(l30.activities)+' 次 · '+durationFromMinutes(l30.durationMin)],
      ['30 天均配速',formatPace(l30.avgPaceSecPerKm),'均心率 '+present(l30.avgHr,'-')+' bpm'],
      ['最新体重',weight?number(weight,1)+' kg':'-',changeText||'体脂称记录 '+present(w.records,'0')+' 条']
    ];$('summaryCards').innerHTML=cards.map(([label,value,hint])=>'<div class="summary-card"><span>'+escapeHtml(label)+'</span><b>'+escapeHtml(value)+'</b><small>'+escapeHtml(hint)+'</small></div>').join('')}
	    function renderRangeTabs(target,ranges,active,fn){const el=$(target);if(!el)return;el.innerHTML=ranges.map(([key,label])=>'<button type="button" data-range="'+escapeHtml(key)+'" class="'+(key===active?'active':'')+'" onclick="'+fn+'(this.dataset.range)">'+escapeHtml(label)+'</button>').join('')}
	    function syncPeriodState(selected){periodState={rangeType:selected.rangeType||periodState.rangeType||'month',year:selected.year||periodState.year||'',month:selected.month||periodState.month||'',quarter:selected.quarter||periodState.quarter||'',weekStart:selected.weekStart||periodState.weekStart||''}}
	    function renderPeriodFilter(d){const el=$('periodFilter');if(!el)return;const opts=d.periodOptions||{},sel=d.selectedRange||{},type=sel.rangeType||periodState.rangeType||'month',years=opts.years||[],year=String(sel.year||periodState.year||years[0]||''),months=(opts.monthsByYear||{})[year]||[],quarters=(opts.quartersByYear||{})[year]||[],weeks=opts.weeks||[];const tabs='<div class="range-tabs" aria-label="统一日期范围">'+PERIOD_RANGES.map(([key,label])=>`<button type="button" class="${key===type?'active':''}" onclick="setPeriodRange('${key}')">${label}</button>`).join('')+'</div>';const yearSelect=years.length?'<select aria-label="年份" onchange="setPeriodYear(this.value)">'+years.map(y=>`<option value="${y}" ${String(y)===year?'selected':''}>${y} 年</option>`).join('')+'</select>':'';let detail='';if(type==='month'){detail='<select aria-label="月份" onchange="setPeriodField(\'month\',this.value)">'+Array.from({length:12},(_,i)=>i+1).map(m=>`<option value="${m}" ${Number(sel.month)===m?'selected':''} ${months.includes(m)?'':'disabled'}>${m} 月${months.includes(m)?'':'（无数据）'}</option>`).join('')+'</select>'}else if(type==='quarter'){detail='<select aria-label="季度" onchange="setPeriodField(\'quarter\',this.value)">'+[1,2,3,4].map(q=>`<option value="${q}" ${Number(sel.quarter)===q?'selected':''} ${quarters.includes(q)?'':'disabled'}>Q${q}${quarters.includes(q)?'':'（无数据）'}</option>`).join('')+'</select>'}else if(type==='week'){detail='<select aria-label="周" onchange="setPeriodField(\'weekStart\',this.value)">'+weeks.map(w=>`<option value="${escapeHtml(w.startDate)}" ${w.startDate===sel.weekStart?'selected':''}>${escapeHtml(w.label)}</option>`).join('')+'</select>'}el.innerHTML=tabs+'<div class="period-controls">'+yearSelect+detail+'<span class="period-label">'+escapeHtml(sel.label||'当前范围')+'</span><span class="period-note">'+escapeHtml(present(sel.startDate,'-'))+' 至 '+escapeHtml(present(sel.endDate,'-'))+'，健康和运动同步筛选</span></div>'}
	    function setPeriodRange(range){periodState={rangeType:range,year:periodState.year,month:'',quarter:'',weekStart:''};loadDashboard()}
	    function setPeriodYear(year){periodState.year=year;periodState.month='';periodState.quarter='';periodState.weekStart='';loadDashboard()}
	    function setPeriodField(field,value){periodState[field]=value;loadDashboard()}
	    function renderCharts(d){const ar=d.activityRange||{},series=ar.series||[],range=ar.summary||{},sports=ar.bySport||[],bodyScale=((d.weight||{}).bodyScale)||{},sel=d.selectedRange||{};renderActivityRangeCards(range,sel);$('chartCards').innerHTML=[
	      statPanel((sel.label||'当前范围')+' 跑量趋势',dailyDistanceTrend(series)),
	      statPanel('运动类型占比',sportBars(sports)),
	      statPanel('体脂秤重点趋势',bodyScaleTrends(bodyScale))
	    ].join('')}
	    function activityRangeTitle(range){return ({week:'周',month:'月',quarter:'季度',year:'年',all:'全部'}[range]||'')+''}
	    function renderActivityRangeCards(range,selected={}){const cards=[
	      ['范围距离',kmValue(range.distanceKm),present(selected.label,'当前范围')+' · '+present(range.periodStart,'-')+' 至 '+present(range.periodEnd,'-')],
	      ['运动次数',present(range.activities,'0')+' 次','总用时 '+durationFromMinutes(range.durationMin)],
	      ['平均配速',formatPace(range.avgPaceSecPerKm),'均心率 '+present(range.avgHr,'-')+' bpm'],
	      ['训练负荷',present(range.calories,'0')+' kcal','爬升 '+present(range.elevationGainM,'0')+' m']
	    ];$('activityRangeCards').innerHTML=cards.map(([label,value,hint])=>'<div class="summary-card"><span>'+escapeHtml(label)+'</span><b>'+escapeHtml(value)+'</b><small>'+escapeHtml(hint)+'</small></div>').join('')}
    function statPanel(title,body){return '<section class="chart-card"><h3>'+escapeHtml(title)+'</h3>'+body+'</section>'}
    function dailyDistanceTrend(rows){if(!rows.length)return '<div class="empty">暂无运动距离数据</div>';const values=rows.map(r=>Number(r.distanceKm||0)),total=values.reduce((a,b)=>a+b,0),active=values.filter(Boolean).length,longest=Math.max(0,...values),avg=rows.length?total/rows.length:0,id='distanceTrend';return '<div class="line-chart">'+lineSvg(rows,'distanceKm',{height:150,color:'#0a84ff',fill:'#e7f1ff',id,unit:' km',decimals:2})+'<div id="'+id+'Readout" class="chart-readout">点击折线点查看具体周期和距离</div><div class="axis-row"><span>'+escapeHtml(rowLabel(rows[0]))+'</span><span>'+escapeHtml(rowLabel(rows[rows.length-1]))+'</span></div><div class="chart-metrics">'+[
      ['总距离',kmValue(total)],
      ['日均',kmValue(avg)],
      ['最长周期',kmValue(longest)],
      ['有运动周期',active+' 个']
    ].map(([k,v])=>'<div><span>'+escapeHtml(k)+'</span><b>'+escapeHtml(v)+'</b></div>').join('')+'</div></div>'}
    function sportBars(rows){if(!rows.length)return '<div class="empty">暂无运动分类数据</div>';const colors=['#0a84ff','#30a46c','#af52de','#ff7a1a','#ff2d55'];const max=Math.max(1,...rows.map(r=>Number(r.distance_km||0)));return '<div class="hbar-list">'+rows.slice(0,5).map((r,i)=>{const w=Math.round((Number(r.distance_km||0)/max)*100);return '<div class="hbar-row"><div class="hbar-top"><span>'+escapeHtml(sportLabel(r.sport_type))+'</span><b>'+kmValue(r.distance_km)+'</b></div><div class="hbar-track"><div class="hbar-fill" style="width:'+w+'%;background:'+colors[i%colors.length]+'"></div></div></div>'}).join('')+'<div class="hbar-axis"><span>0 km</span><span>'+kmValue(max)+'</span></div></div>'}
    function bodyScaleTrends(bodyScale){const rows=bodyScale.series||[];if(!rows.length)return '<div class="empty">暂无体脂秤趋势数据</div>';const metrics=[['体重','weightKg',' kg','#30a46c',1],['体脂率','bodyFatPct','%','#ff2d55',1],['肌肉量','muscleMassKg',' kg','#0a84ff',1]];const summary=(bodyScale.analysis||[]).map(item=>'<div><span>'+escapeHtml(item.label)+'</span><b>'+escapeHtml(number(item.value,1)+item.unit)+'</b><small>'+escapeHtml((Number(item.change||0)>0?'+':'')+number(item.change,1)+item.unit)+'</small></div>').join('');return '<div class="line-chart body-scale-chart">'+metrics.map(([title,key,unit,color,dec])=>{const chartRows=rows.map(r=>({label:shortDate(r.date),date:r.date,value:Number(r[key]||0)})).filter(r=>r.value);if(!chartRows.length)return '';return '<div><div class="axis-row"><b>'+title+'</b><span>'+number(chartRows[0].value,dec)+unit+' → '+number(chartRows[chartRows.length-1].value,dec)+unit+'</span></div>'+lineSvg(chartRows,'value',{height:82,color,fill:'none',unit,decimals:dec})+'</div>'}).join('')+'<div class="chart-metrics">'+summary+'</div></div>'}
	    function lineSvg(rows,key,opts={}){const height=opts.height||150,padL=48,padR=18,padT=16,padB=34,color=opts.color||'#ff7a1a',fill=opts.fill||'none',id=opts.id||'',unit=opts.unit||'',decimals=opts.decimals??0;const values=rows.map(r=>Number(r?.[key]||0));if(!values.length)return '<div class="empty">暂无趋势数据</div>';const width=Math.max(520,(rows.length||1)*52),rawMin=Math.min(...values),rawMax=Math.max(...values),span=Math.max(1,rawMax-rawMin),min=Math.max(0,rawMin-span*.12),max=rawMax+span*.12,range=Math.max(1,max-min),plotW=width-padL-padR,plotH=height-padT-padB;const step=values.length>1?plotW/(values.length-1):0;const points=values.map((v,i)=>{const x=values.length>1?padL+i*step:padL+plotW/2,y=padT+((max-v)/range)*plotH;return [Number(x.toFixed(1)),Number(y.toFixed(1))]});const poly=points.map(p=>p.join(',')).join(' '),baseY=padT+plotH,area=fill==='none'?'':points[0][0]+','+baseY+' '+poly+' '+points[points.length-1][0]+','+baseY;const yTicks=[0,.5,1].map(t=>{const val=max-(range*t),y=padT+(plotH*t);return {y:Number(y.toFixed(1)),label:number(val,decimals)}});const tickLines=yTicks.map(t=>'<line class="chart-gridline" x1="'+padL+'" y1="'+t.y+'" x2="'+(width-padR)+'" y2="'+t.y+'"></line><text class="chart-label" x="'+(padL-8)+'" y="'+(t.y+4)+'" text-anchor="end">'+escapeHtml(t.label)+'</text>').join('');const xTickIndexes=values.length===1?[0]:[0,Math.floor((values.length-1)/2),values.length-1].filter((v,i,a)=>a.indexOf(v)===i);const xTicks=xTickIndexes.map(i=>'<text class="chart-label" x="'+points[i][0]+'" y="'+(height-8)+'" text-anchor="middle">'+escapeHtml(rowLabel(rows[i]))+'</text>').join('');const dots=points.map((p,i)=>{if(!values[i])return '';const label=(rowLabel(rows[i])?rowLabel(rows[i])+' · ':'')+number(values[i],decimals)+unit;const target=id?id+'Readout':'',drill=rows[i]?.drilldownKey||'';const action=drill?'openChartDrilldown(this.dataset.drilldown,this.dataset.label)':'setChartReadout(this.dataset.target,this.dataset.label)';return '<circle class="chart-point" tabindex="0" role="button" aria-label="'+escapeHtml(label)+'" data-target="'+escapeHtml(target)+'" data-label="'+escapeHtml(label)+'" data-drilldown="'+escapeHtml(drill)+'" cx="'+p[0]+'" cy="'+p[1]+'" r="4.5" fill="'+color+'" onclick="'+action+'" onkeydown="if(event.key===\'Enter\')'+action+'"></circle>'}).join('');return '<div class="chart-scroll"><svg viewBox="0 0 '+width+' '+height+'" role="img" aria-label="趋势图">'+tickLines+'<line class="chart-axis" x1="'+padL+'" y1="'+padT+'" x2="'+padL+'" y2="'+baseY+'"></line><line class="chart-axis" x1="'+padL+'" y1="'+baseY+'" x2="'+(width-padR)+'" y2="'+baseY+'"></line>'+(area?'<polygon points="'+area+'" fill="'+fill+'"></polygon>':'')+(values.length>1?'<polyline points="'+poly+'" fill="none" stroke="'+color+'" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>':'')+dots+xTicks+'</svg></div>'}
	    function setChartReadout(id,text){const el=$(id);if(el)el.textContent=text}
	    function openChartDrilldown(key,label){const detail=(currentData?.drilldowns||{})[key];$('dialogTitle').textContent=detail?.title||label||'数据明细';$('dialogMeta').textContent=(currentData?.selectedRange?.label||'')+' · '+(detail?.type==='month'?'月度下钻':'日期下钻');$('dialogBody').innerHTML=detail?chartDrilldownBody(detail):'<div class="empty">暂无可展示的明细</div>';$('activityDialog').showModal()}
	    function chartDrilldownBody(detail){const s=detail.summary||{},health=detail.health||{},activities=detail.activities||[],daily=detail.daily||[];let html='<div class="activity-meta">'+[
	      miniMetric('距离',kmValue(s.distanceKm)),
	      miniMetric('次数',present(s.activities,'0')+' 次'),
	      miniMetric('用时',durationFromMinutes(s.durationMin)),
	      miniMetric('均配',formatPace(s.avgPaceSecPerKm)),
	      miniMetric('均心率',present(s.avgHr,'-')+' bpm'),
	      miniMetric('热量',present(s.calories,'0')+' kcal')
	    ].join('')+'</div>';if(Object.keys(health).length){html+='<section><h3>当天健康</h3><div class="activity-meta">'+[
	      miniMetric('步数',present(health.steps,'-')),
	      miniMetric('静息心率',health.resting_hr?health.resting_hr+' bpm':'-'),
	      miniMetric('HRV',health.hrv_last_night_avg?number(health.hrv_last_night_avg,0)+' ms':'-'),
	      miniMetric('睡眠评分',present(health.sleep_score,'-')),
	      miniMetric('睡眠',health.total_sleep_s?durationFromSeconds(health.total_sleep_s):'-'),
	      miniMetric('血氧',health.avg_spo2?number(health.avg_spo2,1)+'%':'-')
	    ].join('')+'</div></section>'}if(daily.length){html+='<section><h3>每日跑量</h3><div class="lap-grid">'+daily.filter(r=>Number(r.distanceKm||0)>0||Number(r.activities||0)>0).map(r=>'<div class="lap-card"><b>'+escapeHtml(r.label||r.date)+'</b><span>'+kmValue(r.distanceKm)+' · '+present(r.activities,'0')+' 次</span><span>用时 '+durationFromMinutes(r.durationMin)+'</span><span>均配 '+formatPace(r.avgPaceSecPerKm)+'</span></div>').join('')+'</div></section>'}html+='<section><h3>运动记录</h3><div class="activity-list">'+(activities.length?activities.map(a=>'<article class="activity-card"><div><div class="activity-title"><h3>'+escapeHtml(a.name||'未命名运动')+'</h3><span class="chip">'+escapeHtml(sportLabel(a.sportType))+'</span><span class="muted">'+escapeHtml(formatDate(a.startTime))+'</span></div><div class="activity-meta">'+[miniMetric('距离',kmValue(a.distanceKm)),miniMetric('用时',durationFromMinutes(a.durationMin)),miniMetric('配速',formatPace(a.paceSecPerKm)),miniMetric('心率',hrPair(a.avgHr,a.maxHr)),miniMetric('热量',present(a.calories,'0')+' kcal')].join('')+'</div></div><div class="activity-actions"><button class="subtle" type="button" data-id="'+escapeHtml(a.activityId||'')+'" onclick="openActivity(this.dataset.id)">详情</button></div></article>').join(''):'<div class="empty">这个范围没有运动记录</div>')+'</div></section>';return html}
	    function renderAiAnalysis(analysis){const el=$('aiAnalysis');if(!analysis.configured){el.className='ai-content empty';el.textContent='AI 分析未配置。请在设置页检查 MiMo 配置。';return}if(!analysis.ok){el.className='ai-content empty';el.textContent=analysis.message||'暂无 AI 分析缓存';return}const sections=aiSections(analysis);if(!sections.length){el.className='ai-content empty';el.textContent='AI 分析已生成，但没有可展示的结构化建议。';return}el.className='ai-content';const meta=[analysis.model,analysis.generatedAt?'生成时间 '+formatDateTime(analysis.generatedAt):''].filter(Boolean).join(' · ');el.innerHTML='<div class="ai-grid">'+sections.map(aiSectionCard).join('')+'</div>'+(meta?'<div class="ai-meta">'+escapeHtml(meta)+'</div>':'')}
    function aiSectionCard(section){return '<article class="ai-section"><h3>'+escapeHtml(section.title||'分析')+'</h3>'+(section.items||[]).map(item=>'<div class="ai-item"><b><i class="ai-tone '+escapeHtml(item.tone||'neutral')+'"></i>'+escapeHtml(item.label||'建议')+'</b><span>'+escapeHtml(item.text||'')+'</span></div>').join('')+'</article>'}
    function aiSections(analysis){if(Array.isArray(analysis.sections)&&analysis.sections.length)return analysis.sections;return parseAiText(analysis.content||'')}
    function parseAiText(content){const sections=[];let current=null;String(content||'').split(/\\n+/).forEach(line=>{let text=line.trim();if(!text)return;if(text.startsWith('#')){current={title:stripMd(text),items:[]};sections.push(current);return}if(/^[-*•]/.test(text)){if(!current){current={title:'AI 建议',items:[]};sections.push(current)}text=stripMd(text);let label='建议';if(text.includes('：')){const parts=text.split('：');if(parts[0].length<20){label=stripMd(parts.shift());text=parts.join('：')}}current.items.push({label,text,tone:text.includes('下降')||text.includes('风险')||text.includes('不足')?'warn':text.includes('良好')||text.includes('提升')?'good':'neutral'})}});return sections.filter(s=>s.items.length)}
    function stripMd(value){return String(value||'').replace(/^#+/,'').replace(/^[-*•\\s]+/,'').replace(/\\*\\*/g,'').trim()}
    async function refreshAiAnalysis(){const btn=$('aiBtn');if(btn)btn.disabled=true;$('aiAnalysis').className='ai-content empty';$('aiAnalysis').textContent='正在生成 AI 分析...';try{const j=await req('/api/ai/analyze',{method:'POST',body:'{}'});currentData=currentData||{};currentData.aiAnalysis=j.analysis||{};renderAiAnalysis(currentData.aiAnalysis)}catch(e){$('aiAnalysis').textContent=e.message}finally{if(btn)btn.disabled=false}}
	    function renderHealth(d){const h=d.healthRange||d.healthSummary||{},w=d.weight||{},body=w.latest||{},bodyScale=w.bodyScale||{},sel=d.selectedRange||{};$('healthTitle').textContent=(sel.label||'当前范围')+'健康趋势';$('healthDate').textContent='统一范围平均 · '+present(h.startDate,'-')+' 至 '+present(h.endDate,'-');const steps=h.steps||{},heart=h.heartRate||{},hrv=h.hrv||{},sleep=h.sleep||{},spo2=h.spo2||{};const cards=[
      healthCard('平均步数',steps.avgSteps?Number(steps.avgSteps).toLocaleString():'-',steps.trend,[['日均距离',kmValue(steps.avgDistanceKm)],['日均热量',present(steps.avgCalories,'0')+' kcal'],['有效天数',present(steps.days,'0')+' 天']],steps.series,'#ff7a1a'),
      healthCard('静息心率',heart.avgRestingHr?heart.avgRestingHr+' bpm':'-',heart.trend,[['平均心率',bpm(heart.avgHr)],['平均最高',bpm(heart.avgMaxHr)],['有效天数',present(heart.days,'0')+' 天']],heart.series,'#ff2d55'),
      healthCard('HRV',hrv.avgLastNight?number(hrv.avgLastNight,0)+' ms':'-',hrv.trend,[['夜间均值',hrv.avgLastNight?number(hrv.avgLastNight,0)+' ms':'-'],['7天均值',hrv.avgWeekly?number(hrv.avgWeekly,0)+' ms':'-'],['有效天数',present(hrv.days,'0')+' 天']],hrv.series,'#30a46c'),
      healthCard('睡眠',sleep.avgTotalSleepS?durationFromSeconds(sleep.avgTotalSleepS):'-',sleep.trend,[['睡眠评分',present(sleep.avgSleepScore,'-')],['深睡',durationFromSeconds(sleep.avgDeepSleepS)],['REM',durationFromSeconds(sleep.avgRemSleepS)],['有效天数',present(sleep.days,'0')+' 天']],sleep.scoreSeries,'#af52de'),
      healthCard('血氧',spo2.avgSpo2?number(spo2.avgSpo2,1)+'%':'-',spo2.trend,[['平均最低',spo2.avgMinSpo2?number(spo2.avgMinSpo2,1)+'%':'-'],['有效天数',present(spo2.days,'0')+' 天']],spo2.series,'#32ade6'),
      bodyScaleHealthCard(bodyScale,body)
    ];$('healthCards').innerHTML=cards.join('')}
	    function bodyScaleHealthCard(bodyScale,body={}){const latest=bodyScale.latest||{},changes=bodyScale.changes||{},rows=bodyScale.series||[],weight=pick(latest,'weightKg')||pick(body,'Weight','weight_kg'),fat=pick(latest,'bodyFatPct')||pick(body,'BodyFat','body_fat_pct'),muscle=pick(latest,'muscleMassKg')||pick(body,'MuscleMass','muscle_mass_kg');const trend='体重 '+signed(changes.weight?.rangeChange,' kg')+' · 体脂 '+signed(changes.bodyFat?.rangeChange,'%')+' · 肌肉 '+signed(changes.muscleMass?.rangeChange,' kg');return '<article class="health-card"><span>体脂秤重点</span><b>'+escapeHtml(weight?number(weight,1)+' kg':'-')+'</b>'+trendBadge(trend)+'<p class="trend-range">'+escapeHtml(present(bodyScale.startDate,'-'))+' 至 '+escapeHtml(present(bodyScale.endDate,'-'))+'</p>'+(rows.length?'<div class="mini-trend">'+bodyScaleTrends(bodyScale)+'</div>':'')+'<div class="metric-row">'+[['体重',weight?number(weight,1)+' kg':'-'],['体脂率',fat?number(fat,1)+'%':'-'],['肌肉量',muscle?number(muscle,1)+' kg':'-'],['BMI',present(pick(latest,'bmi')||pick(body,'BMI','bmi'),'-')]].map(([k,v])=>'<div><span>'+escapeHtml(k)+'</span><strong>'+escapeHtml(v)+'</strong></div>').join('')+'</div></article>'}
	    function healthCard(title,value,trend,items,series=[],color='#ff7a1a'){const sub=typeof trend==='string'?trend:trendText(trend),range=typeof trend==='string'?'':trendCompareText(trend),chartRows=(series||[]).map(r=>({...r,label:shortDate(r.date),drilldownKey:r.date?'day:'+String(r.date).slice(0,10):''}));return '<article class="health-card"><span>'+escapeHtml(title)+'</span><b>'+escapeHtml(value)+'</b>'+trendBadge(sub)+(range?'<p class="trend-range">'+escapeHtml(range)+'</p>':'')+(chartRows.length?'<div class="mini-trend">'+lineSvg(chartRows,'value',{height:58,color,fill:'none',decimals:0})+'</div>':'')+'<div class="metric-row">'+items.map(([k,v])=>'<div><span>'+escapeHtml(k)+'</span><strong>'+escapeHtml(v)+'</strong></div>').join('')+'</div></article>'}
    function trendText(trend){if(!trend)return '趋势持平';const pct=Number(trend.changePct||0),prefix=trend.direction==='up'?'上升':trend.direction==='down'?'下降':'持平';return prefix+' '+Math.abs(pct).toFixed(1)+'%'}
    function trendCompareText(trend){const p=trend?.previousRange,c=trend?.currentRange;if(!p||!c)return '';return '环比：'+shortDate(p.start)+'-'+shortDate(p.end)+' 平均 '+number(p.avg,1)+' vs '+shortDate(c.start)+'-'+shortDate(c.end)+' 平均 '+number(c.avg,1)}
    function trendBadge(text){const s=String(text||'趋势持平'),cls=s.includes('上升')?'up':s.includes('下降')?'down':'flat';return '<small class="trend-badge '+cls+'">'+escapeHtml(s)+'</small>'}
    function renderActivities(activities){$('activityCount').textContent=activities.length+' 条';$('activities').innerHTML=activities.length?activities.map(activityCard).join(''):'<div class="empty">暂无运动数据</div>'}
    function activityCard(a){const id=String(a.activity_id||''),d=a.derived||{};return '<article class="activity-card"><div><div class="activity-title"><h3>'+escapeHtml(a.name||'未命名运动')+'</h3><span class="chip">'+escapeHtml(sportLabel(a.sport_type))+'</span><span class="muted">'+escapeHtml(formatDate(a.start_time))+'</span></div><div class="activity-meta">'+[
      miniMetric('距离',kmValue(d.distanceKm??metersToKm(a.distance_m)),'distance'),
      miniMetric('用时',durationFromSeconds(a.duration_s),'duration'),
      miniMetric('配速',formatPace(d.paceSecPerKm||paceFrom(a.distance_m,a.duration_s,a.avg_pace_s_per_km)),'pace'),
      miniMetric('心率',hrPair(a.avg_hr,a.max_hr),'hr'),
      miniMetric('步频',a.avg_cadence?number(a.avg_cadence,0)+' spm':'-','cadence'),
      miniMetric('热量',present(a.calories,'0')+' kcal','calories'),
      miniMetric('爬升',present(d.elevationGainM??a.elevation_gain_m,'0')+' m','elevation'),
      miniMetric('来源',sourceLabel(a.source),'source')
    ].join('')+'</div></div><div class="activity-actions"><button class="subtle" type="button" data-id="'+escapeHtml(id)+'" onclick="openActivity(this.dataset.id)">详情</button><a class="action-link" href="'+BASE+'/api/activities/'+encodeURIComponent(id)+'/download">下载数据</a></div></article>'}
    function miniMetric(label,value,type=''){return '<div class="mini-metric '+escapeHtml(type)+'"><span>'+escapeHtml(label)+'</span><b>'+escapeHtml(value)+'</b></div>'}
    async function openActivity(id){$('dialogTitle').textContent='加载中';$('dialogMeta').textContent='';$('dialogBody').innerHTML='<div class="empty">正在读取单次运动数据...</div>';const dialog=$('activityDialog');dialog.showModal();try{const j=await req('/api/activities/'+encodeURIComponent(id));renderActivityDetail(j.data)}catch(e){$('dialogBody').innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>'}}
    function renderActivityDetail(detail){const a=detail.activity||{},laps=detail.laps||[],d=a.derived||{},id=String(a.activity_id||'');$('dialogTitle').textContent=a.name||'运动详情';$('dialogMeta').textContent=[formatDate(a.start_time),sportLabel(a.sport_type),id].filter(Boolean).join(' · ');$('dialogBody').innerHTML='<div class="activity-meta">'+[
      miniMetric('距离',kmValue(d.distanceKm??metersToKm(a.distance_m))),
      miniMetric('总用时',durationFromSeconds(a.duration_s)),
      miniMetric('移动用时',a.moving_duration_s?durationFromSeconds(a.moving_duration_s):'-'),
      miniMetric('平均配速',formatPace(d.paceSecPerKm||paceFrom(a.distance_m,a.duration_s,a.avg_pace_s_per_km))),
      miniMetric('平均/最高心率',hrPair(a.avg_hr,a.max_hr)),
      miniMetric('步频',a.avg_cadence?number(a.avg_cadence,0)+' spm':'-'),
      miniMetric('热量',present(a.calories,'0')+' kcal'),
      miniMetric('爬升',present(d.elevationGainM??a.elevation_gain_m,'0')+' m')
    ].join('')+'</div><div class="section-title"><h2>分段</h2><a class="action-link" href="'+BASE+'/api/activities/'+encodeURIComponent(id)+'/download">下载本次数据</a></div><div class="lap-grid">'+(laps.length?laps.map(lapCard).join(''):'<div class="empty">暂无分段数据</div>')+'</div>'}
    function lapCard(lap){const d=lap.derived||{};return '<div class="lap-card"><b>第 '+(Number(lap.lap_index||0)+1)+' 段</b><span>'+kmFromMeters(lap.distance_m)+' · '+durationFromSeconds(lap.duration_s)+'</span><span>配速 '+formatPace(d.paceSecPerKm||paceFrom(lap.distance_m,lap.duration_s,lap.avg_pace_s_per_km))+'</span><span>心率 '+bpm(lap.avg_hr)+' · '+present(lap.calories,'0')+' kcal</span></div>'}
    function closeActivityDialog(){const dialog=$('activityDialog');if(dialog.open)dialog.close()}
    function renderReport(report){if(!report){$('report').innerHTML='暂无报告';return}const files=report.files||[];const fileLinks=files.length?'<div class="check-list" style="margin-top:10px">'+files.map(f=>'<div class="check-row"><a href="'+BASE+'/reports/'+encodeURIComponent(report.name)+'/'+encodeURIComponent(f.name)+'">'+escapeHtml(f.name)+'</a><span>'+Math.round((f.size||0)/1024)+' KB</span></div>').join('')+'</div>':'';$('report').innerHTML='<a href="'+BASE+'/reports/'+encodeURIComponent(report.name)+'">'+escapeHtml(report.name)+'</a> · '+present(report.fileCount,report.type||'')+' 个文件 · '+Math.round((report.size||0)/1024)+' KB · '+escapeHtml(report.modifiedAt||'')+fileLinks}
    function renderSystem(status){const memory=status.memory||{},disk=status.disk||{},runtimeDisk=status.runtimeDisk||{},proc=status.process||{},data=status.data||{},history=status.history||[];$('systemUpdatedAt').textContent='更新于 '+formatDateTime(status.generatedAt);const cards=[
      systemCard('内存占用',formatBytes(memory.usedBytes)+' / '+formatBytes(memory.totalBytes),formatPercent(memory.usedPct),memory.usedPct),
      systemCard('项目磁盘',formatBytes(disk.usedBytes)+' / '+formatBytes(disk.totalBytes),formatPercent(disk.usedPct),disk.usedPct),
      systemCard('运行目录磁盘',formatBytes(runtimeDisk.usedBytes)+' / '+formatBytes(runtimeDisk.totalBytes),formatPercent(runtimeDisk.usedPct),runtimeDisk.usedPct),
      systemCard('服务进程',formatBytes(proc.rssBytes),'PID '+present(proc.pid,'-'),0),
      systemCard('数据缓存',formatBytes(data.runtimeBytes),'报告 '+present(data.reportsCount,'0')+' 个 · 日志 '+formatBytes(data.logsBytes),0),
      systemCard('运动数据库',data.activityDbExists?formatBytes(data.activityDbBytes):'未生成',data.weightDataExists?'体脂数据 '+formatBytes(data.weightDataBytes):'体脂数据未生成',0),
      systemCard('AI 缓存',data.aiCacheBytes?formatBytes(data.aiCacheBytes):'暂无缓存','服务历史 '+formatBytes(data.serviceHistoryBytes),0),
      systemCard('服务状态',status.recentOk?'最近正常':'最近有异常','近 24 次异常 '+present(status.recentFailures,'0')+' 次 · 系统运行 '+formatUptime(status.uptimeSeconds),status.recentOk?0:90)
    ];$('systemCards').innerHTML=cards.join('');$('serviceHistory').innerHTML=history.length?history.slice().reverse().map(row=>'<div class="history-row"><span><i class="status-dot '+(row.ok?'':'bad')+'"></i><span>'+escapeHtml(row.ok?'正常':'异常')+' · '+escapeHtml(row.message||'')+'</span></span><b>'+escapeHtml(formatDateTime(row.checkedAt))+'</b></div>').join(''):'<div class="empty">暂无历史状态记录</div>'}
    function systemCard(label,value,hint,pct){const percent=Number(pct||0);return '<article class="summary-card"><span>'+escapeHtml(label)+'</span><b>'+escapeHtml(value)+'</b><small>'+escapeHtml(hint||'')+'</small>'+usageBar(percent)+'</article>'}
    function usageBar(pct){if(!pct)return '';const safe=Math.max(1,Math.min(100,Number(pct||0)));const cls=safe>=85?'bad':safe>=70?'warn':'';return '<div class="usage-track"><div class="usage-fill '+cls+'" style="width:'+safe+'%"></div></div>'}
    async function renderSettings(){if(!settingsData){$('settingsCards').innerHTML='<div class="empty">正在读取设置...</div>';await loadSettings()}if(settingsData)drawSettings(settingsData)}
    async function loadSettings(){try{const j=await req('/api/settings');settingsData=j.settings||{};$('settingsMsg').textContent=''}catch(e){$('settingsMsg').textContent=e.message}}
    function drawSettings(data){const profile=data.profile||{},mail=data.mail||{},ai=data.ai||{},sync=data.sync||{},one=data.oneTimePrompt||{};$('settingsCards').innerHTML=[
      '<section class="settings-card"><h3>个人背景</h3><div class="form-grid">'+
      formField('性别','profileSex','select',profile.sex,[['','未填写'],['male','男'],['female','女']])+
      formField('年龄','profileAge','input',profile.age)+
      formField('身高 cm','profileHeightCm','input',profile.heightCm)+
      formField('目标体重 kg','profileWeightTargetKg','input',profile.weightTargetKg)+
      formField('体能状态','profileFitnessLevel','input',profile.fitnessLevel,'如：初跑者 / 半马训练 / 高强度训练期')+
      formField('训练目标','profileTrainingGoal','input',profile.trainingGoal,'如：减脂、提升 10km 配速、备赛')+
      formField('运动背景','profileBackground','textarea',profile.background)+
      formField('健康备注','profileHealthNotes','textarea',profile.healthNotes)+
      '</div><div class="row" style="margin-top:12px"><button type="button" onclick="saveProfile()">保存个人背景</button><span id="profileMsg" class="muted"></span></div></section>',
      '<section class="settings-card"><h3>个人状态 & 下次训练计划</h3>'+statusBadge(one.active?'等待使用':'未设置',one.active?'warn':'flat')+'<div class="check-list">'+oneTimeRow('下一次 AI 建议',one.active,one.aiUsed)+oneTimeRow('下一次邮件发送',one.active,one.mailUsed)+'</div><p class="hint">这里适合填写今天疲劳、疼痛、睡眠主观感受、下一次训练目标等。它不是长期档案；AI 和邮件各使用一次后，服务器会自动删除。</p><textarea id="oneTimePrompt" placeholder="例：昨晚睡眠一般，小腿有轻微酸痛；下次计划 8km 轻松跑，配速控制在 5:50-6:10/km。"></textarea><div class="row" style="margin-top:12px"><button type="button" onclick="saveOneTimePrompt()">保存临时提示词</button><button class="light" type="button" onclick="clearOneTimePrompt()">清空</button><span id="oneTimeMsg" class="muted"></span></div></section>',
      mailSettingsCard(mail),
      '<section class="settings-card"><h3>AI 分析</h3>'+statusBadge(ai.configured?'已配置':'未配置',ai.configured?'good':'warn')+'<div class="check-list">'+checkRow('MIMO_API_KEY',ai.configured)+checkRow('自动同步后分析',ai.autoAfterSync)+checkRow('缓存小时',!!ai.cacheHours)+'</div><p class="hint">模型 '+escapeHtml(ai.model||'-')+' · 缓存 '+present(ai.cacheHours,'-')+' 小时。个人背景保存后会参与下一次 AI 分析，并改变缓存指纹。</p></section>',
      '<section class="settings-card"><h3>同步计划</h3><div class="check-list">'+checkRow('定时任务',sync.schedulerEnabled)+checkRow('运动同步天数 '+present(sync.activityDays,'-'),true)+checkRow('健康同步天数 '+present(sync.healthDays,'-'),true)+checkRow('每日时间 '+present(sync.dailyRunTime,'-'),true)+'</div></section>'
    ].join('')}
    function formField(label,id,type,value,extra){if(type==='select'){return '<div class="form-field"><label for="'+id+'">'+escapeHtml(label)+'</label><select id="'+id+'">'+extra.map(([v,t])=>'<option value="'+escapeHtml(v)+'" '+(value===v?'selected':'')+'>'+escapeHtml(t)+'</option>').join('')+'</select></div>'}if(type==='textarea'){return '<div class="form-field full"><label for="'+id+'">'+escapeHtml(label)+'</label><textarea id="'+id+'">'+escapeHtml(value||'')+'</textarea></div>'}return '<div class="form-field '+(id==='profileFitnessLevel'||id==='profileTrainingGoal'?'full':'')+'"><label for="'+id+'">'+escapeHtml(label)+'</label><input id="'+id+'" value="'+escapeHtml(value||'')+'" placeholder="'+escapeHtml(extra||'')+'"></div>'}
    function mailSettingsCard(mail){const graph=mail.graph||{},isGraph=['microsoft_graph','graph','oauth2'].includes(mail.provider);if(isGraph){return '<section class="settings-card"><h3>邮件配置</h3>'+statusBadge(mail.configured?'Graph 已授权':'Graph 未完成',mail.configured?'good':'warn')+'<div class="check-list">'+checkRow('MAIL_PROVIDER=microsoft_graph',true)+checkRow('MICROSOFT_GRAPH_CLIENT_ID',graph.configured)+checkRow('Outlook OAuth 授权',graph.authorized)+checkRow('MAIL_TO 收件邮箱',!!mail.to)+'</div><p class="hint">服务器不保存 Outlook 密码。首次配置后运行 .venv/bin/python -m garmin_sync_service.cli auth-microsoft，按提示打开 Microsoft 链接并输入设备码授权。</p><p class="hint">收件人 '+escapeHtml(mail.to||'-')+' · token 缓存 '+escapeHtml(graph.cachePath||'-')+' · 附件上限 '+present(mail.attachmentLimitMb,'-')+' MB</p></section>'}return '<section class="settings-card"><h3>邮件配置</h3>'+statusBadge(mail.configured?'SMTP 已配置':'SMTP 未完成',mail.configured?'good':'warn')+'<div class="check-list">'+Object.entries(mail.items||{}).map(([k,v])=>checkRow(k,v)).join('')+'</div><p class="hint">SMTP 模式会用 SMTP_USERNAME/SMTP_PASSWORD 登录邮箱发送。Outlook 推荐改用 MAIL_PROVIDER=microsoft_graph。</p><p class="hint">当前：'+escapeHtml(mail.host||'-')+' · 收件人 '+escapeHtml(mail.to||'-')+' · 附件上限 '+present(mail.attachmentLimitMb,'-')+' MB</p></section>'}
    function statusBadge(text,tone){const cls=tone==='good'?'up':tone==='warn'?'down':'flat';return '<p><small class="trend-badge '+cls+'">'+escapeHtml(text)+'</small></p>'}
    function checkRow(label,ok){return '<div class="check-row"><span>'+escapeHtml(label)+'</span><b class="'+(ok?'ok':'err')+'">'+(ok?'完成':'缺失')+'</b></div>'}
    function oneTimeRow(label,active,used){const text=!active?'未设置':used?'已使用':'待使用',cls=!active?'muted':used?'ok':'err';return '<div class="check-row"><span>'+escapeHtml(label)+'</span><b class="'+cls+'">'+text+'</b></div>'}
    async function saveProfile(){const body={sex:$('profileSex')?.value||'',age:$('profileAge')?.value||'',heightCm:$('profileHeightCm')?.value||'',weightTargetKg:$('profileWeightTargetKg')?.value||'',fitnessLevel:$('profileFitnessLevel')?.value||'',trainingGoal:$('profileTrainingGoal')?.value||'',background:$('profileBackground')?.value||'',healthNotes:$('profileHealthNotes')?.value||''};$('profileMsg').textContent='保存中...';try{const j=await req('/api/settings/profile',{method:'POST',body:JSON.stringify(body)});settingsData=j.settings||settingsData;$('profileMsg').textContent='已保存，下一次 AI 分析会使用这些背景';drawSettings(settingsData)}catch(e){$('profileMsg').textContent=e.message}}
    async function saveOneTimePrompt(){const el=$('oneTimePrompt'),body={prompt:el?.value||''};$('oneTimeMsg').textContent='保存中...';try{const j=await req('/api/settings/one-time-prompt',{method:'POST',body:JSON.stringify(body)});settingsData=j.settings||settingsData;$('oneTimeMsg').textContent=body.prompt?'已保存，将用于下一次 AI 和邮件':'已清空';drawSettings(settingsData)}catch(e){$('oneTimeMsg').textContent=e.message}}
    async function clearOneTimePrompt(){const el=$('oneTimePrompt');if(el)el.value='';await saveOneTimePrompt()}
    function pick(obj,...keys){for(const key of keys){const value=obj?.[key];if(value!==undefined&&value!==null&&value!=='')return value}return null}
    function number(v,d=0){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'-'}
    function present(v,fallback='-'){return v===undefined||v===null||v===''?fallback:String(v)}
    function formatPercent(v){const n=Number(v);return Number.isFinite(n)?n.toFixed(1)+'%':'-'}
    function formatBytes(bytes){const n=Number(bytes||0);if(!n)return '0 B';const units=['B','KB','MB','GB','TB'];let value=n,index=0;while(value>=1024&&index<units.length-1){value/=1024;index++}return (index===0?value.toFixed(0):value.toFixed(value>=10?1:2))+' '+units[index]}
    function formatUptime(sec){sec=Math.max(0,Math.floor(Number(sec||0)));const d=Math.floor(sec/86400),h=Math.floor((sec%86400)/3600),m=Math.floor((sec%3600)/60);return d?d+'天'+h+'小时':h?h+'小时'+m+'分':m+'分'}
    function metersToKm(v){const n=Number(v||0);return n/1000}
    function kmValue(v){const n=Number(v||0);return Number.isFinite(n)?n.toFixed(2)+' km':'-'}
    function kmFromMeters(v){return kmValue(metersToKm(v))}
    function kg(v){return v?number(v,1)+' kg':'-'}
    function percent(v){return v?number(v,1)+'%':'-'}
    function bpm(v){return v?number(v,0)+' bpm':'-'}
    function signed(v,unit=''){const n=Number(v||0);return (n>0?'+':'')+number(n,1)+unit}
    function hrPair(avg,max){return (avg?number(avg,0):'-')+'/'+(max?number(max,0):'-')+' bpm'}
    function paceFrom(distance,duration,stored){const km=Number(distance||0)/1000,sec=Number(duration||0);if(km>0&&sec>0)return sec/km;return Number(stored||0)}
    function formatPace(sec){sec=Number(sec||0);if(!sec)return '-';const m=Math.floor(sec/60),s=Math.round(sec%60);return m+':'+String(s).padStart(2,'0')+' /km'}
    function durationFromSeconds(sec){sec=Math.round(Number(sec||0));if(!sec)return '-';const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;return h? h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0') : m+':'+String(s).padStart(2,'0')}
    function durationFromMinutes(min){min=Number(min||0);return min?durationFromSeconds(min*60):'-'}
    function formatDate(v){return String(v||'').replace('T',' ')}
    function formatDateTime(v){return v?String(v).replace('T',' '):'-'}
    function shortDate(v){const s=String(v||'');return s.length>=10?s.slice(5,10):s}
    function rowLabel(row){return row?.label||shortDate(row?.date)||row?.key||''}
    function sportLabel(v){return ({running:'跑步',cycling:'骑行',walking:'步行',swimming:'游泳'}[v]||v||'运动')}
    function sourceLabel(v){return ({garmin_connect:'Garmin',local_fit:'本地 FIT'}[v]||v||'-')}
    function statusText(v){return ({BALANCED:'均衡',LOW:'偏低',HIGH:'偏高'}[v]||v||'')}
    function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
    async function runSync(){$('status').textContent='同步任务启动中...';startSyncPolling();try{const job=req('/api/sync/run',{method:'POST',body:'{}'});setTimeout(refreshSyncStatus,500);await job;await refreshSyncStatus();await loadDashboard()}catch(e){$('status').textContent=e.message;await refreshSyncStatus().catch(()=>{})}}
    async function generateReport(){$('status').textContent='生成邮件中...';try{await req('/api/reports/generate',{method:'POST',body:'{}'});await loadDashboard()}catch(e){$('status').textContent=e.message}}
    function downloadBulkActivities(){location.href=BASE+'/api/activities/download/bulk?limit=200'}
    boot();
  </script>
</body>
</html>"""


def render_html(page: str) -> str:
    forms = AUTH_FORMS if settings.auth_provider == "wxylab" else LOCAL_AUTH_FORMS
    resolved_page = page if page in forms else "login"
    return HTML_SHELL.replace("__AUTH_FORM__", forms[resolved_page]).replace("__PAGE__", resolved_page)


HTML = render_html("login")
