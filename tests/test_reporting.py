import json
import sqlite3
import zipfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from pathlib import Path

from garmin_sync_service import ai_analysis
from garmin_sync_service import microsoft_graph_mail
from garmin_sync_service.one_time_prompt import load_one_time_prompt, save_one_time_prompt
from garmin_sync_service.dashboard import activity_bulk_download_archive, activity_detail_payload, activity_download_archive, dashboard_payload
from garmin_sync_service.preferences import save_personal_profile, settings_overview
from garmin_sync_service.reporting import generate_report, send_report_email
from garmin_sync_service.sync_runner import CommandResult, SyncRunner
from garmin_sync_service.system_status import record_service_status, system_status_payload
from tests.test_auth import settings_for


def init_activity_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE activities (
                activity_id TEXT PRIMARY KEY,
                name TEXT,
                sport_type TEXT,
                start_time TEXT,
                distance_m REAL,
                duration_s REAL,
                avg_pace_s_per_km REAL,
                avg_hr INTEGER,
                max_hr INTEGER,
                calories INTEGER,
                elevation_gain_m REAL
            )
        """)
        conn.execute("""
            INSERT INTO activities VALUES (
                'a1', 'Morning Run', 'running', '2026-06-23T06:30:00',
                5000, 1500, 300, 142, 170, 320, 12
            )
        """)
        conn.execute("""
            CREATE TABLE laps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT NOT NULL,
                lap_index INTEGER,
                distance_m REAL,
                duration_s REAL,
                avg_pace_s_per_km REAL,
                avg_hr INTEGER,
                calories INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO laps (activity_id, lap_index, distance_m, duration_s, avg_pace_s_per_km, avg_hr, calories)
            VALUES ('a1', 0, 1000, 300, 300, 140, 60)
        """)
        recent = (datetime.now() - timedelta(days=1)).date().isoformat()
        older = (datetime.now() - timedelta(days=8)).date().isoformat()
        conn.execute("""
            CREATE TABLE daily_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                steps INTEGER,
                distance_m REAL,
                calories INTEGER,
                floors_climbed INTEGER
            )
        """)
        conn.executemany(
            "INSERT INTO daily_steps (date, steps, distance_m, calories, floors_climbed) VALUES (?, ?, ?, ?, ?)",
            [(older, 8000, 6200, 300, 3), (recent, 12000, 9400, 420, 5)],
        )
        conn.execute("""
            CREATE TABLE heart_rate_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                resting_hr INTEGER,
                max_hr INTEGER,
                min_hr INTEGER,
                avg_hr INTEGER
            )
        """)
        conn.executemany(
            "INSERT INTO heart_rate_data (date, resting_hr, max_hr, min_hr, avg_hr) VALUES (?, ?, ?, ?, ?)",
            [(older, 55, 165, 48, 75), (recent, 50, 160, 45, 70)],
        )
        conn.execute("""
            CREATE TABLE hrv_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                weekly_avg REAL,
                last_night_avg REAL,
                last_night_5min_high REAL,
                status TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO hrv_data (date, weekly_avg, last_night_avg, last_night_5min_high, status) VALUES (?, ?, ?, ?, ?)",
            [(older, 50, 48, 80, "BALANCED"), (recent, 60, 66, 100, "BALANCED")],
        )
        conn.execute("""
            CREATE TABLE sleep_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                sleep_start TEXT,
                sleep_end TEXT,
                total_sleep_s INTEGER,
                deep_sleep_s INTEGER,
                light_sleep_s INTEGER,
                rem_sleep_s INTEGER,
                awake_s INTEGER,
                sleep_score INTEGER
            )
        """)
        conn.executemany(
            """
            INSERT INTO sleep_data (
                date, sleep_start, sleep_end, total_sleep_s, deep_sleep_s,
                light_sleep_s, rem_sleep_s, awake_s, sleep_score
            ) VALUES (?, '', '', ?, ?, ?, ?, ?, ?)
            """,
            [(older, 24000, 5000, 14000, 4000, 1000, 70), (recent, 27000, 6000, 15000, 5000, 900, 82)],
        )
        conn.execute("""
            CREATE TABLE spo2_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                avg_spo2 REAL,
                min_spo2 REAL
            )
        """)
        conn.executemany(
            "INSERT INTO spo2_data (date, avg_spo2, min_spo2) VALUES (?, ?, ?)",
            [(older, 94, 88), (recent, 96, 90)],
        )
        conn.commit()
    finally:
        conn.close()


def test_dashboard_and_report_generation(tmp_path):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    settings.weight_data_path.parent.mkdir(parents=True, exist_ok=True)
    settings.weight_data_path.write_text(
        json.dumps([{"Date": "2026-06-23", "Weight": 70.5, "BodyFat": 15.2, "MuscleMass": 31.4}]),
        encoding="utf-8",
    )

    payload = dashboard_payload(settings)
    assert payload["activityStats"]["total"] == 1
    assert len(payload["activityStats"]["dailyDistance"]) == 14
    assert payload["activityStats"]["dailyDistance"][-1]["date"]
    assert payload["healthSummary"]["steps"]["avgSteps"] == 10000
    assert payload["healthSummary"]["steps"]["trend"]["direction"] == "up"
    assert "comparisonLabel" in payload["healthSummary"]["steps"]["trend"]
    assert payload["healthSummary"]["steps"]["trend"]["previousRange"]["start"]
    assert payload["healthSummary"]["steps"]["trend"]["currentRange"]["end"]
    assert payload["healthSummary"]["sleep"]["avgSleepScore"] == 76
    assert payload["weight"]["latest"]["Weight"] == 70.5
    assert payload["weight"]["bodyScale"]["latest"]["weightKg"] == 70.5
    assert payload["weight"]["bodyScale"]["latest"]["bodyFatPct"] == 15.2
    assert payload["weight"]["bodyScale"]["latest"]["muscleMassKg"] == 31.4
    assert payload["periodOptions"]["years"]
    assert payload["selectedRange"]["rangeType"] == "month"
    assert payload["activityRange"]["summary"]["periodStart"]
    assert payload["healthRange"]["startDate"] == payload["selectedRange"]["startDate"]

    quarter_payload = dashboard_payload(settings, range_type="quarter", year=2026, quarter=2)
    assert quarter_payload["selectedRange"]["label"] == "2026 Q2"
    assert quarter_payload["healthRange"]["endDate"] == quarter_payload["selectedRange"]["endDate"]

    ai_payload = dashboard_payload(settings, include_long_range=True)
    assert ai_payload["longRangeContext"]["days"] == 120
    assert len(ai_payload["longRangeContext"]["activityDaily"]) == 120
    assert len(ai_payload["longRangeContext"]["healthDaily"]) == 120

    report = generate_report(settings, {"ok": True})
    assert report["ok"] is True
    report_path = Path(report["path"])
    assert report_path.exists()
    assert report_path.is_dir()
    attachment_names = {item["name"] for item in report["attachments"]}
    assert {
        "activity_summary.json",
        "laps.csv",
        "records.csv",
        "health_summary.json",
        "recent_activities.csv",
        "daily_distance.csv",
        "long_range_activity_daily.csv",
        "long_range_health_daily.csv",
        "long_range_period_summary.json",
        "README_ATTACHMENTS.md",
    }.issubset(attachment_names)
    assert not any(name.endswith(".zip") for name in attachment_names)


def test_send_report_email_skips_when_smtp_not_configured(tmp_path):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    report = generate_report(settings, {"ok": True})
    result = send_report_email(settings, report)
    assert result["skipped"] is True


def test_send_report_email_attaches_uncompressed_files(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{
        **settings.__dict__,
        "smtp_host": "smtp.example.com",
        "smtp_username": "runner@example.com",
        "smtp_password": "secret",
        "smtp_from": "Garmin Sync <runner@example.com>",
        "smtp_to": "target@example.com",
    })
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    report = generate_report(settings, {"ok": True})
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, username, password):
            sent.append(("login", username, password))

        def send_message(self, message):
            sent.append(("message", message))

    monkeypatch.setattr("garmin_sync_service.reporting.smtplib.SMTP_SSL", FakeSMTP)
    result = send_report_email(settings, report)

    assert result["ok"] is True
    assert result["sentAt"]
    assert "activity_summary.json" in result["attachments"]
    assert settings.mail_status_path.exists()
    message = [item[1] for item in sent if item[0] == "message"][0]
    filenames = [part.get_filename() for part in message.iter_attachments()]
    assert "activity_summary.json" in filenames
    assert "records.csv" in filenames
    assert not any(str(name).endswith(".zip") for name in filenames)


def test_report_marks_correction_when_mail_already_sent_today(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{
        **settings.__dict__,
        "smtp_host": "smtp.example.com",
        "smtp_username": "runner@example.com",
        "smtp_password": "secret",
        "smtp_from": "Garmin Sync <runner@example.com>",
        "smtp_to": "target@example.com",
    })
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    settings.mail_status_path.write_text(
        json.dumps({"lastSentAt": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
    report = generate_report(settings, {"ok": True})
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, username, password):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("garmin_sync_service.reporting.smtplib.SMTP_SSL", FakeSMTP)
    result = send_report_email(settings, report)

    assert report["correction"] is True
    assert "更正" in report["subject"]
    assert "更正/补发" in report["summary"]
    assert result["ok"] is True
    assert "更正" in sent[0]["Subject"]


def test_activity_detail_and_download_archive(tmp_path):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    fit_dir = settings.activity_project_dir / "data" / "fit_files"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / "a1.fit").write_bytes(b"FIT")

    detail = activity_detail_payload(settings, "a1")
    assert detail["activity"]["name"] == "Morning Run"
    assert detail["activity"]["derived"]["distanceKm"] == 5
    assert detail["laps"][0]["derived"]["paceSecPerKm"] == 300

    archive = activity_download_archive(settings, "a1")
    assert archive["fitIncluded"] is True
    with zipfile.ZipFile(archive["path"]) as zf:
        names = set(zf.namelist())
    assert "activity-a1.json" in names
    assert "laps-a1.csv" in names
    assert "fit/a1.fit" in names


def test_activity_bulk_download_archive_includes_activity_files(tmp_path):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    fit_dir = settings.activity_project_dir / "data" / "fit_files"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / "a1.fit").write_bytes(b"FIT")

    archive = activity_bulk_download_archive(settings, limit=20)
    assert archive["activityCount"] == 1
    assert archive["fitCount"] == 1
    with zipfile.ZipFile(archive["path"]) as zf:
        names = set(zf.namelist())
    assert "activities.csv" in names
    assert "activities/a1/activity.json" in names
    assert "activities/a1/laps.csv" in names
    assert "activities/a1/fit/a1.fit" in names


def test_activity_detail_falls_back_to_fit_laps_when_db_laps_missing(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    conn = sqlite3.connect(settings.activity_db_path)
    try:
        conn.execute("DELETE FROM laps WHERE activity_id = 'a1'")
        conn.commit()
    finally:
        conn.close()
    fit_dir = settings.activity_project_dir / "data" / "fit_files"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / "a1.fit").write_bytes(b"FIT")

    monkeypatch.setattr(
        "garmin_sync_service.dashboard.parse_fit_laps",
        lambda path, activity_id: [{
            "id": None,
            "activity_id": activity_id,
            "lap_index": 0,
            "distance_m": 1000,
            "duration_s": 310,
            "avg_pace_s_per_km": 310,
            "avg_hr": 145,
            "calories": 62,
        }],
    )

    detail = activity_detail_payload(settings, "a1")
    assert detail["activity"]["derived"]["lapCount"] == 1
    assert detail["laps"][0]["source"] if "source" in detail["laps"][0] else True
    assert detail["laps"][0]["derived"]["paceSecPerKm"] == 310


def test_records_csv_falls_back_to_fitparse_when_fit_tool_fails(tmp_path, monkeypatch):
    from garmin_sync_service import reporting

    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    fit_dir = settings.activity_project_dir / "data" / "fit_files"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / "a1.fit").write_bytes(b"FIT")

    def fail_primary(path):
        raise UnicodeDecodeError("utf-8", b"\xae", 0, 1, "invalid start byte")

    monkeypatch.setattr("fit_tool.fit_file.FitFile.from_file", fail_primary)
    monkeypatch.setattr(
        reporting,
        "parse_fit_record_rows",
        lambda path: ([
            {
                "timestamp": "2026-06-23T06:30:00",
                "elapsed_s": 0,
                "distance_m": 0,
                "distance_km": 0,
                "heart_rate": 120,
                "pace_sec_per_km": "",
                "speed_mps": "",
                "cadence": 80,
                "power_w": 210,
                "altitude_m": "",
                "latitude": "",
                "longitude": "",
                "temperature_c": "",
            }
        ], {"available": True, "fitFile": "a1.fit", "records": 1, "parser": "fitparse"}),
    )

    csv_text, meta = reporting._fit_records_csv(settings, {"activity_id": "a1"})
    assert meta["available"] is True
    assert meta["parser"] == "fitparse"
    assert "primaryError" in meta
    assert "heart_rate" in csv_text
    assert "120" in csv_text


def test_sync_runner_status_tracks_progress_and_last_sync(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    runner = SyncRunner(settings)

    def fake_run(name, command, cwd):
        now = datetime.now().isoformat(timespec="seconds")
        status = runner.status()
        assert status["running"] is True
        assert status["currentStep"] == name
        return CommandResult(
            name=name,
            command=command,
            cwd=str(cwd),
            returncode=0,
            started_at=now,
            finished_at=now,
            stdout_tail="",
            stderr_tail="",
        )

    monkeypatch.setattr(runner, "_run", fake_run)
    result = runner.run_all()
    status = runner.status()
    assert result["ok"] is True
    assert status["running"] is False
    assert status["state"] == "success"
    assert status["lastSyncAt"] == result["finishedAt"]
    assert status["lastSuccessAt"] == result["finishedAt"]
    assert status["progress"]["percent"] == 100


def test_ai_analysis_cache_deduplicates_and_omits_activity_names(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{**settings.__dict__, "mimo_api_key": "test-key"})
    settings.ensure_dirs()
    save_personal_profile(settings, {"sex": "male", "age": "35", "fitnessLevel": "半马训练期"})
    payload = {
        "generatedAt": "2026-06-24T00:00:00",
        "activityStats": {"total": 1, "last7Days": {}, "last30Days": {}, "bySport": [], "dailyDistance": []},
        "healthSummary": {"steps": {"avgSteps": 10000}},
        "weight": {"latest": {"Weight": 60.1}, "recent": [], "changeKg": -0.9},
        "activities": [{"name": "Sensitive Place Run", "sport_type": "running", "derived": {"distanceKm": 5}}],
    }
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return SimpleNamespace(
            status_code=200,
            content=b"{}",
            json=lambda: {
                "choices": [{
                    "message": {
                        "content": '{"summary":"分析结果","sections":[{"title":"总体结论","items":[{"label":"状态","text":"分析结果","tone":"good"}]}]}'
                    }
                }],
                "usage": {"total_tokens": 10},
            },
        )

    monkeypatch.setattr(ai_analysis.httpx, "post", fake_post)
    first = ai_analysis.generate_ai_analysis_if_needed(settings, payload, source_finished_at="sync-1")
    second = ai_analysis.generate_ai_analysis_if_needed(settings, payload, source_finished_at="sync-2")

    assert first["ok"] is True
    assert second["skipped"] is True
    assert len(calls) == 1
    request_text = calls[0]["messages"][1]["content"]
    assert "Sensitive Place Run" not in request_text
    assert "半马训练期" in request_text
    assert first["sections"][0]["title"] == "总体结论"


def test_ai_analysis_recovers_sections_from_truncated_json():
    content = """
{
  "summary": "近期训练量较高",
  "sections": [
    {
      "title": "总体状态",
      "items": [
        {
          "label": "训练负荷",
          "text": "近7天跑量较高，需要控制恢复。",
          "tone": "warn"
        },
        {
          "label": "恢复",
          "text": "静息心率和HRV稳定。",
          "tone": "good"
        }
      ]
    },
    {
      "title": "运动趋势",
      "items": [
        {
          "label": "跑量"
    """
    sections = ai_analysis._content_sections(content)
    assert sections[0]["title"] == "总体状态"
    assert sections[0]["items"][0]["label"] == "训练负荷"
    assert sections[0]["items"][1]["tone"] == "good"


def test_system_status_payload_tracks_usage_data_and_history(tmp_path):
    settings = settings_for(tmp_path)
    settings.ensure_dirs()
    settings.activity_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.activity_db_path.write_bytes(b"db")
    settings.weight_data_path.parent.mkdir(parents=True, exist_ok=True)
    settings.weight_data_path.write_text("[]", encoding="utf-8")
    (settings.reports_dir / "garmin-daily-2026-06-24.zip").write_bytes(b"zip")

    record_service_status(settings, ok=True, message="test-ok")
    payload = system_status_payload(settings)

    assert payload["memory"]["totalBytes"] >= 0
    assert payload["disk"]["totalBytes"] > 0
    assert payload["data"]["activityDbExists"] is True
    assert payload["data"]["activityDbBytes"] == 2
    assert payload["data"]["reportsCount"] == 1
    assert payload["history"][-1]["ok"] is True


def test_settings_overview_masks_mail_and_persists_profile(tmp_path):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{
        **settings.__dict__,
        "smtp_host": "smtp.example.com",
        "smtp_username": "runner@example.com",
        "smtp_password": "secret",
        "smtp_from": "Garmin Sync <runner@example.com>",
        "smtp_to": "target@example.com",
    })
    settings.ensure_dirs()
    profile = save_personal_profile(settings, {"age": "35", "trainingGoal": "提升 10km 配速"})
    overview = settings_overview(settings)

    assert profile["trainingGoal"] == "提升 10km 配速"
    assert overview["profile"]["age"] == "35"
    assert overview["mail"]["configured"] is True
    assert "secret" not in str(overview)


def test_graph_mail_send_uses_oauth_token_not_smtp_password(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{
        **settings.__dict__,
        "mail_provider": "microsoft_graph",
        "microsoft_graph_client_id": "client-id",
        "smtp_to": "target@example.com",
        "smtp_password": "smtp-secret",
    })
    settings.ensure_dirs()
    settings.microsoft_graph_token_path.write_text(
        json.dumps({"access_token": "access-token", "refresh_token": "refresh-token", "expires_at": 4102444800}),
        encoding="utf-8",
    )
    report_path = settings.reports_dir / "garmin-daily-2026-06-24.zip"
    report_path.write_bytes(b"zip")
    calls = []

    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "json": json, "data": data})
        return SimpleNamespace(status_code=202, content=b"", text="", json=lambda: {})

    monkeypatch.setattr(microsoft_graph_mail.requests, "post", fake_post)
    result = microsoft_graph_mail.send_report_via_graph(settings, {
        "path": str(report_path),
        "summary": "summary",
    })

    assert result["ok"] is True
    assert calls[0]["url"].endswith("/me/sendMail")
    assert calls[0]["headers"]["Authorization"] == "Bearer access-token"
    assert "smtp-secret" not in str(calls[0])
    assert calls[0]["json"]["message"]["toRecipients"][0]["emailAddress"]["address"] == "target@example.com"


def test_graph_mail_send_supports_uncompressed_report_attachments(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{
        **settings.__dict__,
        "mail_provider": "microsoft_graph",
        "microsoft_graph_client_id": "client-id",
        "smtp_to": "target@example.com",
    })
    settings.ensure_dirs()
    settings.microsoft_graph_token_path.write_text(
        json.dumps({"access_token": "access-token", "refresh_token": "refresh-token", "expires_at": 4102444800}),
        encoding="utf-8",
    )
    report_dir = settings.reports_dir / "garmin-daily-2026-06-24"
    report_dir.mkdir(parents=True)
    first = report_dir / "activity_summary.json"
    second = report_dir / "records.csv"
    first.write_text("{}", encoding="utf-8")
    second.write_text("timestamp,heart_rate\n", encoding="utf-8")
    calls = []

    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "json": json, "data": data})
        return SimpleNamespace(status_code=202, content=b"", text="", json=lambda: {})

    monkeypatch.setattr(microsoft_graph_mail.requests, "post", fake_post)
    result = microsoft_graph_mail.send_report_via_graph(settings, {
        "path": str(report_dir),
        "summary": "summary",
        "attachments": [
            {"path": str(first), "name": first.name, "contentType": "application/json", "size": first.stat().st_size},
            {"path": str(second), "name": second.name, "contentType": "text/csv", "size": second.stat().st_size},
        ],
    })

    assert result["ok"] is True
    attachments = calls[0]["json"]["message"]["attachments"]
    assert [item["name"] for item in attachments] == ["activity_summary.json", "records.csv"]
    assert attachments[0]["contentType"] == "application/json"


def test_one_time_prompt_participates_in_ai_and_mail_then_deletes(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    settings = settings.__class__(**{
        **settings.__dict__,
        "mimo_api_key": "test-key",
        "smtp_host": "smtp.example.com",
        "smtp_username": "runner@example.com",
        "smtp_password": "secret",
        "smtp_from": "Garmin Sync <runner@example.com>",
        "smtp_to": "target@example.com",
    })
    settings.ensure_dirs()
    init_activity_db(settings.activity_db_path)
    save_one_time_prompt(settings, "今天小腿酸痛，下次计划 8km 轻松跑。")
    ai_calls = []

    def fake_post(url, headers, json, timeout):
        ai_calls.append(json)
        return SimpleNamespace(
            status_code=200,
            content=b"{}",
            json=lambda: {
                "choices": [{
                    "message": {
                        "content": '{"summary":"分析结果","sections":[{"title":"本次训练评估","items":[{"label":"负荷","text":"轻松跑更合适","tone":"neutral"}]}]}'
                    }
                }],
                "usage": {"total_tokens": 10},
            },
        )

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, username, password):
            pass

        def send_message(self, message):
            pass

    monkeypatch.setattr(ai_analysis.httpx, "post", fake_post)
    monkeypatch.setattr("garmin_sync_service.reporting.smtplib.SMTP_SSL", FakeSMTP)

    payload = dashboard_payload(settings)
    analysis = ai_analysis.generate_ai_analysis_if_needed(settings, payload, force=True)
    assert analysis["ok"] is True
    assert "今天小腿酸痛" in ai_calls[0]["messages"][1]["content"]
    assert load_one_time_prompt(settings)["aiUsed"] is True
    assert settings.one_time_prompt_path.exists()

    report = generate_report(settings, {"ok": True})
    attachment_names = {item["name"] for item in report["attachments"]}
    assert "one_time_context.json" in attachment_names
    mail = send_report_email(settings, report)
    assert mail["ok"] is True
    assert not settings.one_time_prompt_path.exists()
