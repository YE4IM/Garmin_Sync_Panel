from __future__ import annotations

import json
import logging
import smtplib
import shutil
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .config import Settings
from .dashboard import activities_csv, activity_detail_payload, activity_laps_csv, dashboard_payload
from .fit_fallback import parse_fit_record_rows
from .mail_attachments import report_attachments, total_attachment_size
from .mail_status import load_mail_status, record_mail_sent
from .microsoft_graph_mail import send_report_via_graph
from .one_time_prompt import load_one_time_prompt, mark_one_time_prompt_used


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, content: Any) -> None:
    _write_text(path, json.dumps(content, ensure_ascii=False, indent=2))


def _flatten_activity(activity: dict[str, Any]) -> dict[str, Any]:
    derived = activity.get("derived") or {}
    return {
        "activity_id": activity.get("activity_id"),
        "name": activity.get("name"),
        "sport_type": activity.get("sport_type"),
        "start_time": activity.get("start_time"),
        "distance_km": derived.get("distanceKm"),
        "duration_min": derived.get("durationMin"),
        "pace_sec_per_km": derived.get("paceSecPerKm"),
        "avg_hr": activity.get("avg_hr"),
        "max_hr": activity.get("max_hr"),
        "avg_cadence": activity.get("avg_cadence"),
        "calories": activity.get("calories"),
        "elevation_gain_m": activity.get("elevation_gain_m"),
        "lap_count": derived.get("lapCount"),
    }


def _csv_from_rows(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    import csv
    from io import StringIO

    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buf.getvalue()


def _latest_activity_detail(settings: Settings, payload: dict[str, Any]) -> dict[str, Any] | None:
    latest = (payload.get("activities") or [None])[0] or {}
    activity_id = latest.get("activity_id")
    if not activity_id:
        return None
    return activity_detail_payload(settings, str(activity_id))


def _activity_fit_file(settings: Settings, activity: dict[str, Any]) -> Path | None:
    activity_id = str(activity.get("activity_id") or "")
    candidates: list[Path] = []
    source_file = str(activity.get("source_file") or "")
    if source_file:
        source_path = Path(source_file)
        candidates.append(source_path if source_path.is_absolute() else settings.activity_project_dir / source_path)
    if activity_id:
        candidates.append(settings.activity_project_dir / "data" / "fit_files" / f"{activity_id}.fit")
        candidates.append(settings.activity_project_dir / "data" / "fit_files" / f"{activity_id}.FIT")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _fit_records_csv(settings: Settings, activity: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fieldnames = [
        "timestamp",
        "elapsed_s",
        "distance_m",
        "distance_km",
        "heart_rate",
        "pace_sec_per_km",
        "speed_mps",
        "cadence",
        "power_w",
        "altitude_m",
        "latitude",
        "longitude",
        "temperature_c",
    ]
    fit_file = _activity_fit_file(settings, activity)
    if not fit_file:
        return _csv_from_rows([], fieldnames), {"available": False, "reason": "FIT file not found"}
    try:
        from fit_tool.fit_file import FitFile
        from fit_tool.profile.messages.record_message import RecordMessage
    except Exception as exc:
        return _csv_from_rows([], fieldnames), {"available": False, "fitFile": fit_file.name, "reason": f"FIT parser unavailable: {exc}"}

    rows: list[dict[str, Any]] = []
    previous_logging_disable = logging.root.manager.disable
    try:
        logging.disable(logging.ERROR)
        fit = FitFile.from_file(str(fit_file))
        started_at: datetime | None = None
        for item in fit.records:
            message = item.message
            if not isinstance(message, RecordMessage):
                continue
            timestamp = getattr(message, "timestamp", None)
            if isinstance(timestamp, datetime):
                if started_at is None:
                    started_at = timestamp
                elapsed_s = round((timestamp - started_at).total_seconds(), 1)
                timestamp_value = timestamp.isoformat()
            else:
                elapsed_s = ""
                timestamp_value = str(timestamp or "")
            distance_m = _num(getattr(message, "distance", None))
            speed_mps = _num(getattr(message, "enhanced_speed", None) or getattr(message, "speed", None))
            rows.append({
                "timestamp": timestamp_value,
                "elapsed_s": elapsed_s,
                "distance_m": round(distance_m, 2) if distance_m else "",
                "distance_km": round(distance_m / 1000.0, 3) if distance_m else "",
                "heart_rate": _int_or_blank(getattr(message, "heart_rate", None)),
                "pace_sec_per_km": round(1000.0 / speed_mps, 1) if speed_mps else "",
                "speed_mps": round(speed_mps, 3) if speed_mps else "",
                "cadence": _int_or_blank(getattr(message, "cadence", None)),
                "power_w": _int_or_blank(getattr(message, "power", None)),
                "altitude_m": _blankable_float(getattr(message, "enhanced_altitude", None) or getattr(message, "altitude", None)),
                "latitude": _semicircles_to_degrees(getattr(message, "position_lat", None)),
                "longitude": _semicircles_to_degrees(getattr(message, "position_long", None)),
                "temperature_c": _int_or_blank(getattr(message, "temperature", None)),
            })
    except Exception as exc:
        fallback_rows, fallback_meta = parse_fit_record_rows(fit_file)
        if fallback_rows:
            fallback_meta["primaryError"] = str(exc)
            return _csv_from_rows(fallback_rows, fieldnames), fallback_meta
        return _csv_from_rows([], fieldnames), {"available": False, "fitFile": fit_file.name, "reason": f"FIT parse failed: {exc}; {fallback_meta.get('reason', '')}"}
    finally:
        logging.disable(previous_logging_disable)
    return _csv_from_rows(rows, fieldnames), {"available": True, "fitFile": fit_file.name, "records": len(rows)}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _blankable_float(value: Any) -> float | str:
    parsed = _num(value)
    return round(parsed, 2) if parsed else ""


def _int_or_blank(value: Any) -> int | str:
    parsed = _num(value)
    return int(parsed) if parsed else ""


def _semicircles_to_degrees(value: Any) -> float | str:
    parsed = _num(value)
    if not parsed:
        return ""
    return round(parsed * (180.0 / 2147483648.0), 7)


def _health_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "generatedAt": payload.get("generatedAt"),
        "healthSummary": payload.get("healthSummary") or {},
        "latestHealth": payload.get("health") or {},
        "weight": payload.get("weight") or {},
        "notes": [
            "healthSummary uses recent 14-day averages and comparison windows where available.",
            "latestHealth is included only as a reference point, not as the primary trend basis.",
        ],
    }


def _daily_distance_csv(payload: dict[str, Any]) -> str:
    rows = payload.get("activityStats", {}).get("dailyDistance") or []
    return _csv_from_rows(rows, ["date", "activities", "distanceKm", "durationMin"])


def _long_range_activity_daily_csv(payload: dict[str, Any]) -> str:
    rows = (payload.get("longRangeContext") or {}).get("activityDaily") or []
    return _csv_from_rows(rows, ["date", "label", "activities", "distanceKm", "durationMin", "calories", "avgHr", "avgPaceSecPerKm"])


def _long_range_health_daily_csv(payload: dict[str, Any]) -> str:
    rows = (payload.get("longRangeContext") or {}).get("healthDaily") or []
    return _csv_from_rows(rows, [
        "date",
        "steps",
        "step_distance_m",
        "step_calories",
        "resting_hr",
        "avg_hr",
        "max_hr",
        "hrv_last_night_avg",
        "hrv_weekly_avg",
        "hrv_status",
        "total_sleep_s",
        "deep_sleep_s",
        "rem_sleep_s",
        "sleep_score",
        "avg_spo2",
        "min_spo2",
    ])


def _weight_csv(payload: dict[str, Any]) -> str:
    rows = (payload.get("weight") or {}).get("recent") or []
    if not rows:
        return _csv_from_rows([], ["date", "weight_kg", "body_fat_pct", "bmi", "muscle_kg", "water_pct"])
    normalized = []
    for row in rows:
        normalized.append({
            "date": row.get("Date") or row.get("date"),
            "weight_kg": row.get("Weight") or row.get("weight_kg"),
            "body_fat_pct": row.get("BodyFat") or row.get("body_fat_pct"),
            "bmi": row.get("BMI") or row.get("bmi"),
            "muscle_kg": row.get("MuscleMass") or row.get("Muscle") or row.get("muscle_mass_kg") or row.get("muscle_kg"),
            "water_pct": row.get("BodyWater") or row.get("Water") or row.get("body_water_pct") or row.get("water_pct"),
        })
    return _csv_from_rows(normalized, ["date", "weight_kg", "body_fat_pct", "bmi", "muscle_kg", "water_pct"])


def _attachment_readme(records_meta: dict[str, Any], one_time: dict[str, Any] | None = None, correction: bool = False) -> str:
    one_time = one_time or {}
    return "\n".join([
        "# Garmin Sync 邮件附件说明",
        "",
        f"邮件类型：{'更正/补发。本邮件覆盖今天较早发送的 Garmin Daily 数据。' if correction else '常规日报。'}",
        "",
        "本邮件不再使用 zip 压缩包，所有文件均为 ChatGPT 可直接读取的未压缩附件。",
        "",
        "| 文件 | 作用 | 重要性 |",
        "| --- | --- | --- |",
        "| activity_summary.json | 最新单次运动总览、派生指标、文件状态 | 必须 |",
        "| laps.csv | 最新单次运动的分公里/分段数据 | 必须 |",
        "| records.csv | 最新单次运动从 FIT 解析出的秒级/采样点数据 | 最有价值；若为空请查看解析状态 |",
        "| health_summary.json | 近 14 天睡眠、HRV、静息心率、血氧、体重等趋势摘要 | 很重要 |",
        "| recent_activities.csv | 最近训练记录列表 | 很重要 |",
        "| daily_distance.csv | 近 14 天每日运动距离趋势 | 很重要 |",
        "| long_range_activity_daily.csv | 近 120 天每日运动聚合数据 | 很重要 |",
        "| long_range_health_daily.csv | 近 120 天每日健康聚合数据 | 很重要 |",
        "| long_range_period_summary.json | 近 120 天周/月汇总和总体趋势 | 很重要 |",
        "| weight.csv | 最近体脂称/体重记录 | 可选 |",
        "| sync_result.json | 本次同步任务状态 | 可选 |",
        "| one_time_context.json | 本次个人状态与下次训练计划，仅当你填写临时提示词时存在 | 可选 |",
        "",
        f"records.csv 解析状态：{json.dumps(records_meta, ensure_ascii=False)}",
        f"临时提示词状态：{'已随本次邮件提供' if one_time.get('prompt') else '无'}",
        "",
    ])


def _summary_markdown(payload: dict, sync_result: dict | None, one_time: dict[str, Any] | None = None, correction: bool = False) -> str:
    stats = payload.get("activityStats") or {}
    last7 = stats.get("last7Days") or {}
    last30 = stats.get("last30Days") or {}
    latest_activity = (payload.get("activities") or [None])[0] or {}
    weight = (payload.get("weight") or {}).get("latest") or {}
    health = payload.get("health") or {}
    last_run = sync_result or payload.get("lastRun") or {}
    one_time = one_time or {}
    long_range = payload.get("longRangeContext") or {}
    long_summary = (long_range.get("summary") or {}).get("activity") or {}
    lines = [
        f"# {'更正/补发 ' if correction else ''}Garmin Daily {date.today().isoformat()}",
        "",
    ]
    if correction:
        lines.extend([
            "- Correction: this email supersedes the earlier Garmin Daily email sent today.",
            "- 更正说明：今天已发送过一次，本次邮件包含最新同步和重新生成后的完整附件。",
            "",
        ])
    lines.extend([
        f"- Generated at: {payload.get('generatedAt')}",
        f"- Sync status: {'success' if last_run.get('ok') else 'failed or not recorded'}",
        f"- Total activities: {stats.get('total', 0)}",
        f"- Last 7 days: {last7.get('activities', 0)} activities, {last7.get('distanceKm', 0)} km, {last7.get('durationMin', 0)} min",
        f"- Last 30 days: {last30.get('activities', 0)} activities, {last30.get('distanceKm', 0)} km, {last30.get('durationMin', 0)} min",
        f"- Last 120 days: {long_summary.get('activities', 0)} activities, {long_summary.get('distanceKm', 0)} km, {long_summary.get('durationMin', 0)} min",
        "",
        "## Latest Activity",
        f"- Name: {latest_activity.get('name', '')}",
        f"- Type: {latest_activity.get('sport_type', '')}",
        f"- Start: {latest_activity.get('start_time', '')}",
        f"- Distance: {round(float(latest_activity.get('distance_m') or 0) / 1000, 2)} km",
        f"- Duration: {round(float(latest_activity.get('duration_s') or 0) / 60, 1)} min",
        f"- Average HR: {latest_activity.get('avg_hr', 0)}",
        "",
    ])
    lines.extend([
        "## Latest Weight",
        f"- Date: {weight.get('Date') or weight.get('date') or ''}",
        f"- Weight: {weight.get('Weight') or weight.get('weight_kg') or ''}",
        f"- Body fat: {weight.get('BodyFat') or weight.get('body_fat_pct') or ''}",
        f"- Muscle mass: {weight.get('MuscleMass') or weight.get('muscle_mass_kg') or ''}",
        "",
        "## Latest Health Keys",
        f"- Steps: {bool(health.get('steps'))}",
        f"- Sleep: {bool(health.get('sleep'))}",
        f"- HRV: {bool(health.get('hrv'))}",
        f"- SpO2: {bool(health.get('spo2'))}",
        "",
    ])
    if one_time.get("prompt"):
        lines.extend([
            "## 本次个人状态与下次训练计划",
            one_time["prompt"],
            "",
        ])
    lines.extend([
        "Use the attached uncompressed JSON/CSV files for detailed analysis. There is no zip archive in this email.",
        "",
    ])
    return "\n".join(lines)


def _report_subject(report_date: str, correction: bool = False) -> str:
    prefix = "[Garmin Daily 更正]" if correction else "[Garmin Daily]"
    return f"{prefix} {report_date} 运动与健康数据文件"


def _already_sent_today(settings: Settings, report_date: str) -> bool:
    last_sent = str((load_mail_status(settings) or {}).get("lastSentAt") or "")
    return last_sent[:10] == report_date


def generate_report(settings: Settings, sync_result: dict | None = None) -> dict:
    report_date = date.today().isoformat()
    correction = _already_sent_today(settings, report_date)
    build_dir = settings.reports_dir / f"garmin-daily-{report_date}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    payload = dashboard_payload(settings, include_long_range=True)
    one_time = load_one_time_prompt(settings)
    mail_one_time = one_time if one_time.get("active") and not one_time.get("mailUsed") else {}
    summary = _summary_markdown(payload, sync_result, mail_one_time, correction=correction)
    detail = _latest_activity_detail(settings, payload)
    latest_activity = (detail or {}).get("activity") or ((payload.get("activities") or [None])[0] or {})
    records_csv, records_meta = _fit_records_csv(settings, latest_activity)

    _write_text(build_dir / "summary.md", summary)
    _write_text(build_dir / "README_ATTACHMENTS.md", _attachment_readme(records_meta, mail_one_time, correction=correction))
    _write_json(build_dir / "activity_summary.json", detail or {"activity": latest_activity, "laps": [], "files": {"fitAvailable": False}})
    _write_text(build_dir / "laps.csv", activity_laps_csv((detail or {}).get("laps") or []))
    _write_text(build_dir / "records.csv", records_csv)
    _write_json(build_dir / "health_summary.json", _health_report_payload(payload))
    _write_text(build_dir / "recent_activities.csv", activities_csv(settings))
    _write_text(build_dir / "daily_distance.csv", _daily_distance_csv(payload))
    _write_text(build_dir / "long_range_activity_daily.csv", _long_range_activity_daily_csv(payload))
    _write_text(build_dir / "long_range_health_daily.csv", _long_range_health_daily_csv(payload))
    _write_json(build_dir / "long_range_period_summary.json", {
        "generatedAt": payload.get("generatedAt"),
        "range": {
            "days": (payload.get("longRangeContext") or {}).get("days"),
            "startDate": (payload.get("longRangeContext") or {}).get("startDate"),
            "endDate": (payload.get("longRangeContext") or {}).get("endDate"),
        },
        "summary": (payload.get("longRangeContext") or {}).get("summary") or {},
        "activityWeekly": (payload.get("longRangeContext") or {}).get("activityWeekly") or [],
        "activityMonthly": (payload.get("longRangeContext") or {}).get("activityMonthly") or [],
        "weight": (payload.get("longRangeContext") or {}).get("weight") or [],
    })
    _write_text(build_dir / "weight.csv", _weight_csv(payload))
    _write_json(build_dir / "sync_result.json", sync_result or payload.get("lastRun") or {})
    if mail_one_time.get("prompt"):
        _write_json(build_dir / "one_time_context.json", {
            "prompt": mail_one_time.get("prompt"),
            "createdAt": mail_one_time.get("createdAt"),
            "usage": "本文件来自服务器临时提示词。邮件成功发送并且 AI 已使用后，服务器临时状态会自动删除。",
        })

    attachments = [
        {
            "path": str(path),
            "name": path.name,
            "size": path.stat().st_size,
            "contentType": "application/json" if path.suffix == ".json" else "text/csv" if path.suffix == ".csv" else "text/markdown",
        }
        for path in sorted(build_dir.iterdir())
        if path.is_file()
    ]
    return {
        "ok": True,
        "path": str(build_dir),
        "name": build_dir.name,
        "size": sum(item["size"] for item in attachments),
        "attachments": attachments,
        "attachmentCount": len(attachments),
        "records": records_meta,
        "oneTimePromptIncluded": bool(mail_one_time.get("prompt")),
        "correction": correction,
        "subject": _report_subject(report_date, correction),
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
    }


def send_report_email(settings: Settings, report: dict) -> dict:
    if settings.mail_provider in {"microsoft_graph", "graph", "oauth2"}:
        return send_report_via_graph(settings, report)

    required = [settings.smtp_host, settings.smtp_from, settings.smtp_to]
    if not all(required):
        return {"ok": False, "skipped": True, "reason": "SMTP_HOST, SMTP_FROM, or SMTP_TO is not configured"}
    limit = settings.mail_attachment_limit_mb * 1024 * 1024
    attachments = report_attachments(report)
    if not attachments:
        return {"ok": False, "skipped": True, "reason": "report has no readable attachments"}
    total_size = total_attachment_size(report)
    if total_size > limit:
        return {"ok": False, "skipped": True, "reason": f"attachments exceed {settings.mail_attachment_limit_mb} MB"}

    msg = EmailMessage()
    msg["Subject"] = report.get("subject") or _report_subject(date.today().isoformat(), bool(report.get("correction")))
    msg["From"] = settings.smtp_from
    msg["To"] = settings.smtp_to
    msg.set_content(report.get("summary") or "Garmin daily report attached.", subtype="plain", charset="utf-8")
    for attachment in attachments:
        maintype, subtype = attachment["contentType"].split("/", 1)
        msg.add_attachment(
            attachment["path"].read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment["name"],
        )

    use_ssl = settings.smtp_ssl or settings.smtp_port == 465
    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_tls and not use_ssl:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)
    attachment_names = [item["name"] for item in attachments]
    status = record_mail_sent(
        settings,
        provider="smtp",
        to=settings.smtp_to,
        attachments=attachment_names,
        total_bytes=total_size,
        subject=str(msg["Subject"]),
        correction=bool(report.get("correction")),
    )
    if report.get("oneTimePromptIncluded"):
        mark_one_time_prompt_used(settings, "mail")
    return {"ok": True, "to": settings.smtp_to, "attachments": attachment_names, "totalBytes": total_size, "sentAt": status["lastSentAt"]}
