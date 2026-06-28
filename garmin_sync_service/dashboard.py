from __future__ import annotations

import csv
import json
import re
import sqlite3
import zipfile
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from .ai_analysis import latest_ai_analysis
from .config import Settings
from .fit_fallback import parse_fit_laps
from .mail_status import load_mail_status
from .system_status import system_status_payload


def _connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def _one(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def _since(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_file_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "activity")).strip("._") or "activity"


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _activity_derived(activity: dict[str, Any], laps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    laps = laps or []
    distance_m = _to_float(activity.get("distance_m"))
    duration_s = _to_float(activity.get("duration_s"))
    moving_duration_s = _to_float(activity.get("moving_duration_s"))
    pace_s_per_km = _to_float(activity.get("avg_pace_s_per_km"))
    if distance_m > 0 and duration_s > 0:
        pace_s_per_km = duration_s / (distance_m / 1000.0)
    return {
        "distanceKm": round(distance_m / 1000.0, 2),
        "durationMin": round(duration_s / 60.0, 1),
        "movingDurationMin": round(moving_duration_s / 60.0, 1) if moving_duration_s else None,
        "paceSecPerKm": round(pace_s_per_km, 1) if pace_s_per_km else None,
        "lapCount": len(laps),
        "elevationGainM": round(_to_float(activity.get("elevation_gain_m")), 1),
    }


def dashboard_payload(
    settings: Settings,
    *,
    range_type: str | None = None,
    year: int | str | None = None,
    month: int | str | None = None,
    quarter: int | str | None = None,
    week_start: str | None = None,
    include_long_range: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "databaseExists": settings.activity_db_path.exists(),
        "lastRun": _read_json(settings.last_run_path, {"ok": None}),
        "export": _read_json(settings.activity_export_path, {}),
        "activities": [],
        "activityStats": {},
        "health": {},
        "healthSummary": {},
        "weight": latest_weight_payload(settings),
        "aiAnalysis": latest_ai_analysis(settings),
        "systemStatus": system_status_payload(settings),
        "latestReport": latest_report(settings),
        "mailStatus": load_mail_status(settings),
        "schedule": {"dailyRunTime": settings.daily_run_time},
        "periodOptions": {},
        "selectedRange": {},
        "activityRange": {},
        "healthRange": {},
        "drilldowns": {},
    }
    conn = _connect(settings.activity_db_path)
    if not conn:
        return payload
    try:
        period_options = _period_options(conn)
        selected_range = _selected_range(conn, range_type, year, month, quarter, week_start, period_options)
        range_start = _parse_date(selected_range.get("startDate")) or datetime.now().date()
        range_end = _parse_date(selected_range.get("endDate")) or range_start
        activities = _rows(
            conn,
            """
            SELECT *
            FROM activities
            ORDER BY start_time DESC
            LIMIT 20
            """,
        ) if _table_exists(conn, "activities") else []
        payload["activities"] = [
            {**activity, "derived": _activity_derived(activity)}
            for activity in activities
        ]
        selected_activities = _activities_between(conn, range_start, range_end)
        drilldowns = _drilldowns_for_range(conn, range_start, range_end, selected_range)
        payload["activityStats"] = {
            "total": (_one(conn, "SELECT COUNT(*) AS count FROM activities") or {}).get("count", 0)
            if _table_exists(conn, "activities")
            else 0,
            "last7Days": _activity_window(conn, 7),
            "last30Days": _activity_window(conn, 30),
            "rangeSummaries": _activity_range_summaries(conn),
            "rangeSeries": _activity_range_series(conn),
            "bySport": _rows(
                conn,
                """
                SELECT sport_type, COUNT(*) AS count, ROUND(SUM(distance_m) / 1000.0, 2) AS distance_km
                FROM activities
                GROUP BY sport_type
                ORDER BY count DESC
                """,
            ) if _table_exists(conn, "activities") else [],
            "dailyDistance": _daily_distance(conn, 14),
        }
        payload["health"] = latest_health_payload(conn)
        payload["healthSummary"] = health_summary_payload(conn, 14)
        payload["healthSummaryRanges"] = {
            "14": payload["healthSummary"],
            "30": health_summary_payload(conn, 30),
            "90": health_summary_payload(conn, 90),
            "150": health_summary_payload(conn, 150),
            "all": health_summary_payload(conn, None),
        }
        payload["periodOptions"] = period_options
        payload["selectedRange"] = selected_range
        payload["activityRange"] = {
            "summary": _activity_summary_between(conn, range_start, range_end),
            "series": _activity_series_between(conn, range_start, range_end, selected_range.get("grain") or "day"),
            "bySport": _activity_sports_between(conn, range_start, range_end),
            "activities": selected_activities,
        }
        payload["healthRange"] = health_summary_for_range(conn, range_start, range_end, selected_range.get("label") or "")
        payload["drilldowns"] = drilldowns
        if include_long_range:
            payload["longRangeContext"] = long_range_context(settings, days=120, conn=conn)
    finally:
        conn.close()
    return payload


def _parse_int(value: int | str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None


def _month_start_end(year: int, month: int) -> tuple[date, date]:
    month = min(12, max(1, month))
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _quarter_start_end(year: int, quarter: int) -> tuple[date, date]:
    quarter = min(4, max(1, quarter))
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    return start, date(year, end_month, monthrange(year, end_month)[1])


def _week_start(value: date) -> date:
    return value - timedelta(days=(value.weekday() + 1) % 7)


def _date_iter(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _month_iter(start: date, end: date):
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while current <= last:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def _available_dates(conn: sqlite3.Connection) -> list[date]:
    dates: set[date] = set()
    if _table_exists(conn, "activities"):
        for row in _rows(conn, "SELECT substr(start_time, 1, 10) AS date FROM activities WHERE start_time IS NOT NULL"):
            if parsed := _parse_date(row.get("date")):
                dates.add(parsed)
    for table in ["daily_steps", "heart_rate_data", "hrv_data", "sleep_data", "spo2_data", "weight_data"]:
        if not _table_exists(conn, table):
            continue
        for row in _rows(conn, f"SELECT date FROM {table} WHERE date IS NOT NULL"):
            if parsed := _parse_date(row.get("date")):
                dates.add(parsed)
    return sorted(dates)


def _period_options(conn: sqlite3.Connection) -> dict[str, Any]:
    dates = _available_dates(conn)
    today = datetime.now().date()
    latest = dates[-1] if dates else today
    current_month_has_data = any(item.year == today.year and item.month == today.month for item in dates)
    default_anchor = today if current_month_has_data else latest
    months_by_year: dict[str, list[int]] = defaultdict(list)
    quarters_by_year: dict[str, set[int]] = defaultdict(set)
    weeks: dict[str, dict[str, str]] = {}
    for item in dates:
        year_key = str(item.year)
        if item.month not in months_by_year[year_key]:
            months_by_year[year_key].append(item.month)
        quarters_by_year[year_key].add(((item.month - 1) // 3) + 1)
        start = _week_start(item)
        end = start + timedelta(days=6)
        weeks[start.isoformat()] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "label": f"{start.strftime('%m-%d')} 至 {end.strftime('%m-%d')}",
            "year": str(start.year),
        }
    years = sorted({item.year for item in dates}, reverse=True) or [today.year]
    return {
        "years": years,
        "monthsByYear": {year: sorted(months) for year, months in months_by_year.items()},
        "quartersByYear": {year: sorted(values) for year, values in quarters_by_year.items()},
        "weeks": [weeks[key] for key in sorted(weeks.keys(), reverse=True)],
        "defaultSelection": {
            "rangeType": "month",
            "year": default_anchor.year,
            "month": default_anchor.month,
            "label": f"{default_anchor.year}-{default_anchor.month:02d}",
        },
        "minDate": dates[0].isoformat() if dates else today.isoformat(),
        "maxDate": latest.isoformat(),
    }


def _selected_range(
    conn: sqlite3.Connection,
    range_type: str | None,
    year: int | str | None,
    month: int | str | None,
    quarter: int | str | None,
    week_start: str | None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or _period_options(conn)
    default = options.get("defaultSelection") or {}
    selected = str(range_type or default.get("rangeType") or "month").lower()
    if selected not in {"week", "month", "quarter", "year", "all"}:
        selected = "month"
    default_year = _parse_int(default.get("year"), datetime.now().year)
    selected_year = _parse_int(year, default_year)
    if selected == "all":
        start = _parse_date(options.get("minDate")) or datetime.now().date()
        end = _parse_date(options.get("maxDate")) or start
        return {"rangeType": "all", "startDate": start.isoformat(), "endDate": end.isoformat(), "label": "全部数据", "grain": "month"}
    if selected == "year":
        start, end = date(selected_year, 1, 1), date(selected_year, 12, 31)
        return {"rangeType": "year", "year": selected_year, "startDate": start.isoformat(), "endDate": end.isoformat(), "label": f"{selected_year} 年", "grain": "month"}
    if selected == "quarter":
        selected_quarter = _parse_int(quarter, ((datetime.now().month - 1) // 3) + 1)
        start, end = _quarter_start_end(selected_year, selected_quarter)
        return {"rangeType": "quarter", "year": selected_year, "quarter": selected_quarter, "startDate": start.isoformat(), "endDate": end.isoformat(), "label": f"{selected_year} Q{selected_quarter}", "grain": "month"}
    if selected == "week":
        start = _parse_date(week_start) or _week_start(_parse_date(options.get("maxDate")) or datetime.now().date())
        end = start + timedelta(days=6)
        return {"rangeType": "week", "weekStart": start.isoformat(), "startDate": start.isoformat(), "endDate": end.isoformat(), "label": f"{start.strftime('%m-%d')} 至 {end.strftime('%m-%d')}", "grain": "day"}
    selected_month = _parse_int(month, _parse_int(default.get("month"), datetime.now().month))
    start, end = _month_start_end(selected_year, selected_month)
    return {"rangeType": "month", "year": selected_year, "month": selected_month, "startDate": start.isoformat(), "endDate": end.isoformat(), "label": f"{selected_year}-{selected_month:02d}", "grain": "day"}


def _activity_window(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    if not _table_exists(conn, "activities"):
        return {"activities": 0, "distanceKm": 0, "durationMin": 0, "calories": 0}
    row = _one(
        conn,
        """
        SELECT COUNT(*) AS activities,
               ROUND(COALESCE(SUM(distance_m), 0) / 1000.0, 2) AS distanceKm,
               ROUND(COALESCE(SUM(duration_s), 0) / 60.0, 1) AS durationMin,
               COALESCE(SUM(calories), 0) AS calories,
               ROUND(COALESCE(SUM(elevation_gain_m), 0), 1) AS elevationGainM,
               ROUND(COALESCE(AVG(NULLIF(avg_hr, 0)), 0), 0) AS avgHr,
               ROUND(
                   CASE WHEN COALESCE(SUM(distance_m), 0) > 0
                        THEN COALESCE(SUM(duration_s), 0) / (COALESCE(SUM(distance_m), 0) / 1000.0)
                        ELSE 0
                   END,
                   1
               ) AS avgPaceSecPerKm
        FROM activities
        WHERE start_time >= ?
        """,
        (_since(days),),
    )
    return row or {"activities": 0, "distanceKm": 0, "durationMin": 0, "calories": 0}


def _period_start(period: str, today: date | None = None) -> date | None:
    today = today or datetime.now().date()
    if period == "week":
        return today - timedelta(days=(today.weekday() + 1) % 7)
    if period == "month":
        return today.replace(day=1)
    if period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=month, day=1)
    if period == "year":
        return today.replace(month=1, day=1)
    return None


def _activity_range_summaries(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "activities"):
        return {}
    output: dict[str, Any] = {}
    for period in ["week", "month", "quarter", "year", "all"]:
        start = _period_start(period)
        if start:
            row = _one(
                conn,
                """
                SELECT COUNT(*) AS activities,
                       ROUND(COALESCE(SUM(distance_m), 0) / 1000.0, 2) AS distanceKm,
                       ROUND(COALESCE(SUM(duration_s), 0) / 60.0, 1) AS durationMin,
                       COALESCE(SUM(calories), 0) AS calories,
                       ROUND(COALESCE(SUM(elevation_gain_m), 0), 1) AS elevationGainM,
                       ROUND(COALESCE(AVG(NULLIF(avg_hr, 0)), 0), 0) AS avgHr,
                       ROUND(
                           CASE WHEN COALESCE(SUM(distance_m), 0) > 0
                                THEN COALESCE(SUM(duration_s), 0) / (COALESCE(SUM(distance_m), 0) / 1000.0)
                                ELSE 0
                           END,
                           1
                       ) AS avgPaceSecPerKm,
                       MIN(substr(start_time, 1, 10)) AS startDate,
                       MAX(substr(start_time, 1, 10)) AS endDate
                FROM activities
                WHERE date(substr(start_time, 1, 10)) >= date(?)
                """,
                (start.isoformat(),),
            ) or {}
        else:
            row = _one(
                conn,
                """
                SELECT COUNT(*) AS activities,
                       ROUND(COALESCE(SUM(distance_m), 0) / 1000.0, 2) AS distanceKm,
                       ROUND(COALESCE(SUM(duration_s), 0) / 60.0, 1) AS durationMin,
                       COALESCE(SUM(calories), 0) AS calories,
                       ROUND(COALESCE(SUM(elevation_gain_m), 0), 1) AS elevationGainM,
                       ROUND(COALESCE(AVG(NULLIF(avg_hr, 0)), 0), 0) AS avgHr,
                       ROUND(
                           CASE WHEN COALESCE(SUM(distance_m), 0) > 0
                                THEN COALESCE(SUM(duration_s), 0) / (COALESCE(SUM(distance_m), 0) / 1000.0)
                                ELSE 0
                           END,
                           1
                       ) AS avgPaceSecPerKm,
                       MIN(substr(start_time, 1, 10)) AS startDate,
                       MAX(substr(start_time, 1, 10)) AS endDate
                FROM activities
                """,
            ) or {}
        output[period] = {**row, "period": period, "periodStart": start.isoformat() if start else row.get("startDate"), "periodEnd": datetime.now().date().isoformat()}
    return output


def _activity_range_series(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    if not _table_exists(conn, "activities"):
        return {}
    rows = _rows(
        conn,
        """
        SELECT substr(start_time, 1, 10) AS date,
               distance_m,
               duration_s,
               calories
        FROM activities
        ORDER BY start_time ASC
        """,
    )
    return {
        "week": _activity_period_series(rows, "week", 16),
        "month": _activity_period_series(rows, "month", 12),
        "quarter": _activity_period_series(rows, "quarter", 8),
        "year": _activity_period_series(rows, "year", None),
        "all": _activity_period_series(rows, "month", None),
    }


def _activity_period_series(rows: list[dict[str, Any]], period: str, limit: int | None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "activities": 0,
        "distanceKm": 0.0,
        "durationMin": 0.0,
        "calories": 0,
    })
    for row in rows:
        try:
            row_date = datetime.fromisoformat(str(row.get("date"))[:10]).date()
        except (TypeError, ValueError):
            continue
        if period == "week":
            start = row_date - timedelta(days=(row_date.weekday() + 1) % 7)
            end = start + timedelta(days=6)
            key = start.isoformat()
            label = f"{start.strftime('%m-%d')} 至 {end.strftime('%m-%d')}"
        elif period == "quarter":
            quarter = ((row_date.month - 1) // 3) + 1
            key = f"{row_date.year}-Q{quarter}"
            label = f"{row_date.year} Q{quarter}"
        elif period == "year":
            key = str(row_date.year)
            label = key
        else:
            key = f"{row_date.year}-{row_date.month:02d}"
            label = key
        bucket = grouped[key]
        bucket.update({"key": key, "label": label})
        bucket["activities"] += 1
        bucket["distanceKm"] += _to_float(row.get("distance_m")) / 1000.0
        bucket["durationMin"] += _to_float(row.get("duration_s")) / 60.0
        bucket["calories"] += int(_to_float(row.get("calories")))
    series = sorted(grouped.values(), key=lambda item: item.get("key") or "")
    if limit:
        series = series[-limit:]
    return [
        {
            **item,
            "distanceKm": round(item["distanceKm"], 2),
            "durationMin": round(item["durationMin"], 1),
        }
        for item in series
    ]


def _activity_where_between(start: date, end: date) -> tuple[str, tuple[str, str]]:
    return "date(substr(start_time, 1, 10)) BETWEEN date(?) AND date(?)", (start.isoformat(), end.isoformat())


def _activity_summary_between(conn: sqlite3.Connection, start: date, end: date) -> dict[str, Any]:
    if not _table_exists(conn, "activities"):
        return {"activities": 0, "distanceKm": 0, "durationMin": 0, "calories": 0, "periodStart": start.isoformat(), "periodEnd": end.isoformat()}
    where, args = _activity_where_between(start, end)
    row = _one(
        conn,
        f"""
        SELECT COUNT(*) AS activities,
               ROUND(COALESCE(SUM(distance_m), 0) / 1000.0, 2) AS distanceKm,
               ROUND(COALESCE(SUM(duration_s), 0) / 60.0, 1) AS durationMin,
               COALESCE(SUM(calories), 0) AS calories,
               ROUND(COALESCE(SUM(elevation_gain_m), 0), 1) AS elevationGainM,
               ROUND(COALESCE(AVG(NULLIF(avg_hr, 0)), 0), 0) AS avgHr,
               ROUND(
                   CASE WHEN COALESCE(SUM(distance_m), 0) > 0
                        THEN COALESCE(SUM(duration_s), 0) / (COALESCE(SUM(distance_m), 0) / 1000.0)
                        ELSE 0
                   END,
                   1
               ) AS avgPaceSecPerKm
        FROM activities
        WHERE {where}
        """,
        args,
    ) or {}
    return {**row, "periodStart": start.isoformat(), "periodEnd": end.isoformat()}


def _activities_between(conn: sqlite3.Connection, start: date, end: date, limit: int = 120) -> list[dict[str, Any]]:
    if not _table_exists(conn, "activities"):
        return []
    where, args = _activity_where_between(start, end)
    rows = _rows(
        conn,
        f"""
        SELECT *
        FROM activities
        WHERE {where}
        ORDER BY start_time DESC
        LIMIT ?
        """,
        (*args, limit),
    )
    return [{**row, "derived": _activity_derived(row)} for row in rows]


def _activity_sports_between(conn: sqlite3.Connection, start: date, end: date) -> list[dict[str, Any]]:
    if not _table_exists(conn, "activities"):
        return []
    where, args = _activity_where_between(start, end)
    return _rows(
        conn,
        f"""
        SELECT sport_type, COUNT(*) AS count, ROUND(SUM(distance_m) / 1000.0, 2) AS distance_km
        FROM activities
        WHERE {where}
        GROUP BY sport_type
        ORDER BY distance_km DESC, count DESC
        """,
        args,
    )


def _activity_rows_between(conn: sqlite3.Connection, start: date, end: date) -> list[dict[str, Any]]:
    if not _table_exists(conn, "activities"):
        return []
    where, args = _activity_where_between(start, end)
    return _rows(
        conn,
        f"""
        SELECT substr(start_time, 1, 10) AS date,
               activity_id,
               name,
               sport_type,
               start_time,
               distance_m,
               duration_s,
               calories,
               avg_hr,
               max_hr,
               avg_pace_s_per_km,
               elevation_gain_m
        FROM activities
        WHERE {where}
        ORDER BY start_time ASC
        """,
        args,
    )


def _activity_series_between(conn: sqlite3.Connection, start: date, end: date, grain: str = "day") -> list[dict[str, Any]]:
    rows = _activity_rows_between(conn, start, end)
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"activities": 0, "distanceKm": 0.0, "durationMin": 0.0, "calories": 0, "avgHrValues": []})
    for row in rows:
        row_date = _parse_date(row.get("date"))
        if not row_date:
            continue
        if grain == "month":
            key = f"{row_date.year}-{row_date.month:02d}"
            label = key
            drilldown_key = f"month:{key}"
        else:
            key = row_date.isoformat()
            label = row_date.strftime("%m-%d")
            drilldown_key = f"day:{key}"
        bucket = grouped[key]
        bucket.update({"key": key, "date": key, "label": label, "drilldownKey": drilldown_key})
        bucket["activities"] += 1
        bucket["distanceKm"] += _to_float(row.get("distance_m")) / 1000.0
        bucket["durationMin"] += _to_float(row.get("duration_s")) / 60.0
        bucket["calories"] += int(_to_float(row.get("calories")))
        if _to_float(row.get("avg_hr")):
            bucket["avgHrValues"].append(_to_float(row.get("avg_hr")))
    if grain == "month":
        keys = [f"{item.year}-{item.month:02d}" for item in _month_iter(start, end)]
    else:
        keys = [item.isoformat() for item in _date_iter(start, end)]
    output: list[dict[str, Any]] = []
    for key in keys:
        if key in grouped:
            item = grouped[key]
        else:
            item = {
                "key": key,
                "date": key,
                "label": key if grain == "month" else key[5:],
                "drilldownKey": f"{'month' if grain == 'month' else 'day'}:{key}",
                "activities": 0,
                "distanceKm": 0.0,
                "durationMin": 0.0,
                "calories": 0,
                "avgHrValues": [],
            }
        distance = item["distanceKm"]
        duration = item["durationMin"]
        output.append({
            "key": item["key"],
            "date": item["date"],
            "label": item["label"],
            "drilldownKey": item["drilldownKey"],
            "activities": item["activities"],
            "distanceKm": round(distance, 2),
            "durationMin": round(duration, 1),
            "calories": item["calories"],
            "avgHr": round(sum(item["avgHrValues"]) / len(item["avgHrValues"])) if item["avgHrValues"] else 0,
            "avgPaceSecPerKm": round((duration * 60) / distance, 1) if distance else 0,
        })
    return output


def _daily_distance(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "activities"):
        return []
    start_date = (datetime.now() - timedelta(days=days - 1)).date().isoformat()
    rows = _rows(
        conn,
        """
        SELECT substr(start_time, 1, 10) AS date,
               COUNT(*) AS activities,
               ROUND(COALESCE(SUM(distance_m), 0) / 1000.0, 2) AS distanceKm,
               ROUND(COALESCE(SUM(duration_s), 0) / 60.0, 1) AS durationMin
        FROM activities
        WHERE substr(start_time, 1, 10) >= ?
        GROUP BY substr(start_time, 1, 10)
        ORDER BY date ASC
        """,
        (start_date,),
    )
    by_date = {row["date"]: row for row in rows}
    output: list[dict[str, Any]] = []
    for index in range(days):
        date_key = (datetime.now() - timedelta(days=days - 1 - index)).date().isoformat()
        output.append(by_date.get(date_key) or {
            "date": date_key,
            "activities": 0,
            "distanceKm": 0,
            "durationMin": 0,
        })
    return output


def latest_health_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    mapping = {
        "steps": ("daily_steps", "date"),
        "heartRate": ("heart_rate_data", "date"),
        "hrv": ("hrv_data", "date"),
        "sleep": ("sleep_data", "date"),
        "garminWeight": ("weight_data", "date"),
        "spo2": ("spo2_data", "date"),
    }
    output: dict[str, Any] = {}
    for key, (table, order_col) in mapping.items():
        if _table_exists(conn, table):
            output[key] = _one(conn, f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT 1")
    return output


def _date_floor(days: int) -> str:
    return (datetime.now() - timedelta(days=days - 1)).date().isoformat()


def _date_from_row(row: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(str(row.get("date"))[:10]).date()
    except (TypeError, ValueError):
        return None


def _trend_from_rows(rows: list[dict[str, Any]], key: str, days: int | None) -> dict[str, Any]:
    today = datetime.now().date()
    if days is None:
        dated_rows = [row for row in rows if _date_from_row(row)]
        start = min((_date_from_row(row) for row in dated_rows), default=today)
        days = max(1, (today - start).days + 1)
    else:
        start = today - timedelta(days=days - 1)
    split_end = start + timedelta(days=max(0, days // 2 - 1))
    current_start = split_end + timedelta(days=1)
    previous_values: list[float] = []
    current_values: list[float] = []
    for row in rows:
        row_date = _date_from_row(row)
        if not row_date:
            continue
        value = _to_float(row.get(key))
        if not value:
            continue
        if start <= row_date <= split_end:
            previous_values.append(value)
        elif current_start <= row_date <= today:
            current_values.append(value)
    if not previous_values or not current_values:
        return {
            "direction": "flat",
            "change": 0,
            "changePct": 0,
            "firstAvg": 0,
            "lastAvg": 0,
            "previousRange": {"start": start.isoformat(), "end": split_end.isoformat(), "days": 0, "avg": 0},
            "currentRange": {"start": current_start.isoformat(), "end": today.isoformat(), "days": 0, "avg": 0},
            "comparisonLabel": f"{start.isoformat()} 至 {split_end.isoformat()} vs {current_start.isoformat()} 至 {today.isoformat()}",
        }
    first = previous_values
    last = current_values
    first_avg = sum(first) / len(first)
    last_avg = sum(last) / len(last)
    change = last_avg - first_avg
    change_pct = (change / first_avg * 100) if first_avg else 0
    if abs(change_pct) < 3:
        direction = "flat"
    else:
        direction = "up" if change > 0 else "down"
    return {
        "direction": direction,
        "change": round(change, 2),
        "changePct": round(change_pct, 1),
        "firstAvg": round(first_avg, 2),
        "lastAvg": round(last_avg, 2),
        "previousRange": {
            "start": start.isoformat(),
            "end": split_end.isoformat(),
            "days": len(previous_values),
            "avg": round(first_avg, 2),
        },
        "currentRange": {
            "start": current_start.isoformat(),
            "end": today.isoformat(),
            "days": len(current_values),
            "avg": round(last_avg, 2),
        },
        "comparisonLabel": f"{start.isoformat()} 至 {split_end.isoformat()} vs {current_start.isoformat()} 至 {today.isoformat()}",
    }


def _trend_from_period_rows(rows: list[dict[str, Any]], key: str, start: date, end: date) -> dict[str, Any]:
    days = max(1, (end - start).days + 1)
    previous_start = start - timedelta(days=days)
    previous_end = start - timedelta(days=1)
    previous_values: list[float] = []
    current_values: list[float] = []
    for row in rows:
        row_date = _date_from_row(row)
        if not row_date:
            continue
        value = _to_float(row.get(key))
        if not value:
            continue
        if previous_start <= row_date <= previous_end:
            previous_values.append(value)
        elif start <= row_date <= end:
            current_values.append(value)
    previous_avg = sum(previous_values) / len(previous_values) if previous_values else 0
    current_avg = sum(current_values) / len(current_values) if current_values else 0
    change = current_avg - previous_avg
    change_pct = (change / previous_avg * 100) if previous_avg else 0
    direction = "flat"
    if previous_values and current_values and abs(change_pct) >= 3:
        direction = "up" if change > 0 else "down"
    return {
        "direction": direction,
        "change": round(change, 2),
        "changePct": round(change_pct, 1),
        "firstAvg": round(previous_avg, 2),
        "lastAvg": round(current_avg, 2),
        "previousRange": {
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
            "days": len(previous_values),
            "avg": round(previous_avg, 2),
        },
        "currentRange": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": len(current_values),
            "avg": round(current_avg, 2),
        },
        "comparisonLabel": f"{previous_start.isoformat()} 至 {previous_end.isoformat()} vs {start.isoformat()} 至 {end.isoformat()}",
    }


def _avg(rows: list[dict[str, Any]], key: str) -> float:
    values = [_to_float(row.get(key)) for row in rows if _to_float(row.get(key))]
    return round(sum(values) / len(values), 2) if values else 0


def _series(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [
        {"date": row.get("date"), "value": round(_to_float(row.get(key)), 2)}
        for row in rows
        if row.get("date")
    ]


def _recent_rows(conn: sqlite3.Connection, table: str, days: int | None) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    if days is None:
        return _rows(conn, f"SELECT * FROM {table} ORDER BY date ASC")
    return _rows(conn, f"SELECT * FROM {table} WHERE date >= ? ORDER BY date ASC", (_date_floor(days),))


def _range_rows(conn: sqlite3.Connection, table: str, start: date, end: date) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    return _rows(
        conn,
        f"SELECT * FROM {table} WHERE date BETWEEN ? AND ? ORDER BY date ASC",
        (start.isoformat(), end.isoformat()),
    )


def _period_rows_for_trend(conn: sqlite3.Connection, table: str, start: date, end: date) -> list[dict[str, Any]]:
    days = max(1, (end - start).days + 1)
    previous_start = start - timedelta(days=days)
    return _range_rows(conn, table, previous_start, end)


def _health_range(rows_by_key: list[list[dict[str, Any]]], days: int | None) -> tuple[str, str]:
    if days is not None:
        return _date_floor(days), datetime.now().date().isoformat()
    dates: list[date] = []
    for rows in rows_by_key:
        dates.extend([row_date for row in rows if (row_date := _date_from_row(row))])
    if not dates:
        today = datetime.now().date().isoformat()
        return today, today
    return min(dates).isoformat(), max(dates).isoformat()


def health_summary_for_range(conn: sqlite3.Connection, start: date, end: date, label: str = "") -> dict[str, Any]:
    steps = _range_rows(conn, "daily_steps", start, end)
    heart = _range_rows(conn, "heart_rate_data", start, end)
    hrv = _range_rows(conn, "hrv_data", start, end)
    sleep = _range_rows(conn, "sleep_data", start, end)
    spo2 = _range_rows(conn, "spo2_data", start, end)

    steps_series = _series(steps, "steps")
    resting_series = _series(heart, "resting_hr")
    hrv_series = _series(hrv, "last_night_avg")
    sleep_series = _series(sleep, "total_sleep_s")
    sleep_score_series = _series(sleep, "sleep_score")
    spo2_series = _series(spo2, "avg_spo2")

    range_days = max(1, (end - start).days + 1)

    return {
        "rangeDays": range_days,
        "rangeLabel": label,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "steps": {
            "days": len(steps),
            "avgSteps": round(_avg(steps, "steps")),
            "avgDistanceKm": round(_avg(steps, "distance_m") / 1000, 2),
            "avgCalories": round(_avg(steps, "calories")),
            "trend": _trend_from_period_rows(_period_rows_for_trend(conn, "daily_steps", start, end), "steps", start, end),
            "series": steps_series,
        },
        "heartRate": {
            "days": len(heart),
            "avgRestingHr": round(_avg(heart, "resting_hr")),
            "avgHr": round(_avg(heart, "avg_hr")),
            "avgMaxHr": round(_avg(heart, "max_hr")),
            "trend": _trend_from_period_rows(_period_rows_for_trend(conn, "heart_rate_data", start, end), "resting_hr", start, end),
            "series": resting_series,
        },
        "hrv": {
            "days": len(hrv),
            "avgLastNight": round(_avg(hrv, "last_night_avg")),
            "avgWeekly": round(_avg(hrv, "weekly_avg")),
            "trend": _trend_from_period_rows(_period_rows_for_trend(conn, "hrv_data", start, end), "last_night_avg", start, end),
            "series": hrv_series,
        },
        "sleep": {
            "days": len(sleep),
            "avgTotalSleepS": round(_avg(sleep, "total_sleep_s")),
            "avgDeepSleepS": round(_avg(sleep, "deep_sleep_s")),
            "avgRemSleepS": round(_avg(sleep, "rem_sleep_s")),
            "avgSleepScore": round(_avg(sleep, "sleep_score")),
            "trend": _trend_from_period_rows(_period_rows_for_trend(conn, "sleep_data", start, end), "sleep_score", start, end),
            "series": sleep_series,
            "scoreSeries": sleep_score_series,
        },
        "spo2": {
            "days": len(spo2),
            "avgSpo2": round(_avg(spo2, "avg_spo2"), 1),
            "avgMinSpo2": round(_avg(spo2, "min_spo2"), 1),
            "trend": _trend_from_period_rows(_period_rows_for_trend(conn, "spo2_data", start, end), "avg_spo2", start, end),
            "series": spo2_series,
        },
    }


def health_summary_payload(conn: sqlite3.Connection, days: int | None = 14) -> dict[str, Any]:
    if days is None:
        steps = _recent_rows(conn, "daily_steps", None)
        heart = _recent_rows(conn, "heart_rate_data", None)
        hrv = _recent_rows(conn, "hrv_data", None)
        sleep = _recent_rows(conn, "sleep_data", None)
        spo2 = _recent_rows(conn, "spo2_data", None)
        start_date, end_date = _health_range([steps, heart, hrv, sleep, spo2], None)
        start = _parse_date(start_date) or datetime.now().date()
        end = _parse_date(end_date) or start
        summary = health_summary_for_range(conn, start, end, "全部数据")
        summary["rangeDays"] = "all"
        return summary
    start = datetime.now().date() - timedelta(days=days - 1)
    end = datetime.now().date()
    summary = health_summary_for_range(conn, start, end, f"近 {days} 天")
    steps = _recent_rows(conn, "daily_steps", days)
    heart = _recent_rows(conn, "heart_rate_data", days)
    hrv = _recent_rows(conn, "hrv_data", days)
    sleep = _recent_rows(conn, "sleep_data", days)
    spo2 = _recent_rows(conn, "spo2_data", days)
    summary["steps"]["trend"] = _trend_from_rows(steps, "steps", days)
    summary["heartRate"]["trend"] = _trend_from_rows(heart, "resting_hr", days)
    summary["hrv"]["trend"] = _trend_from_rows(hrv, "last_night_avg", days)
    summary["sleep"]["trend"] = _trend_from_rows(sleep, "sleep_score", days)
    summary["spo2"]["trend"] = _trend_from_rows(spo2, "avg_spo2", days)
    return summary


def _health_daily_rows(conn: sqlite3.Connection, start: date, end: date) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {
        item.isoformat(): {"date": item.isoformat()}
        for item in _date_iter(start, end)
    }
    mappings = {
        "daily_steps": {
            "steps": "steps",
            "step_distance_m": "distance_m",
            "step_calories": "calories",
        },
        "heart_rate_data": {
            "resting_hr": "resting_hr",
            "avg_hr": "avg_hr",
            "max_hr": "max_hr",
        },
        "hrv_data": {
            "hrv_last_night_avg": "last_night_avg",
            "hrv_weekly_avg": "weekly_avg",
            "hrv_status": "status",
        },
        "sleep_data": {
            "total_sleep_s": "total_sleep_s",
            "deep_sleep_s": "deep_sleep_s",
            "rem_sleep_s": "rem_sleep_s",
            "sleep_score": "sleep_score",
        },
        "spo2_data": {
            "avg_spo2": "avg_spo2",
            "min_spo2": "min_spo2",
        },
    }
    for table, fields in mappings.items():
        for row in _range_rows(conn, table, start, end):
            key = str(row.get("date") or "")[:10]
            target = by_date.setdefault(key, {"date": key})
            for output_key, source_key in fields.items():
                target[output_key] = row.get(source_key)
    return [by_date[key] for key in sorted(by_date.keys())]


def _activity_weekly_series(conn: sqlite3.Connection, start: date, end: date) -> list[dict[str, Any]]:
    rows = _activity_rows_between(conn, start, end)
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"activities": 0, "distanceKm": 0.0, "durationMin": 0.0, "calories": 0})
    for row in rows:
        row_date = _parse_date(row.get("date"))
        if not row_date:
            continue
        week = _week_start(row_date)
        key = week.isoformat()
        bucket = grouped[key]
        bucket.update({"weekStart": key, "weekEnd": (week + timedelta(days=6)).isoformat(), "label": f"{week.strftime('%m-%d')} 至 {(week + timedelta(days=6)).strftime('%m-%d')}"})
        bucket["activities"] += 1
        bucket["distanceKm"] += _to_float(row.get("distance_m")) / 1000.0
        bucket["durationMin"] += _to_float(row.get("duration_s")) / 60.0
        bucket["calories"] += int(_to_float(row.get("calories")))
    return [
        {**item, "distanceKm": round(item["distanceKm"], 2), "durationMin": round(item["durationMin"], 1)}
        for item in sorted(grouped.values(), key=lambda value: value.get("weekStart") or "")
    ]


def _drilldown_activity_row(activity: dict[str, Any]) -> dict[str, Any]:
    derived = activity.get("derived") or _activity_derived(activity)
    return {
        "activityId": activity.get("activity_id"),
        "name": activity.get("name"),
        "sportType": activity.get("sport_type"),
        "startTime": activity.get("start_time"),
        "distanceKm": derived.get("distanceKm"),
        "durationMin": derived.get("durationMin"),
        "paceSecPerKm": derived.get("paceSecPerKm"),
        "avgHr": activity.get("avg_hr"),
        "maxHr": activity.get("max_hr"),
        "calories": activity.get("calories"),
    }


def _health_for_day(conn: sqlite3.Connection, day: date) -> dict[str, Any]:
    row = (_health_daily_rows(conn, day, day) or [{}])[0]
    return {key: value for key, value in row.items() if value not in (None, "")}


def _drilldowns_for_range(conn: sqlite3.Connection, start: date, end: date, selected_range: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for row in _activity_series_between(conn, start, end, selected_range.get("grain") or "day"):
        key = str(row.get("drilldownKey") or "")
        if not key:
            continue
        if key.startswith("month:"):
            month_start = _parse_date(key.split(":", 1)[1] + "-01")
            if not month_start:
                continue
            month_end = date(month_start.year, month_start.month, monthrange(month_start.year, month_start.month)[1])
            scoped_start, scoped_end = max(start, month_start), min(end, month_end)
            output[key] = {
                "type": "month",
                "title": f"{month_start.year}-{month_start.month:02d}",
                "summary": _activity_summary_between(conn, scoped_start, scoped_end),
                "daily": _activity_series_between(conn, scoped_start, scoped_end, "day"),
                "activities": [_drilldown_activity_row(item) for item in _activities_between(conn, scoped_start, scoped_end, 60)],
            }
        elif key.startswith("day:"):
            day = _parse_date(key.split(":", 1)[1])
            if not day:
                continue
            output[key] = {
                "type": "day",
                "title": day.isoformat(),
                "summary": _activity_summary_between(conn, day, day),
                "health": _health_for_day(conn, day),
                "activities": [_drilldown_activity_row(item) for item in _activities_between(conn, day, day, 20)],
            }
    return output


def long_range_context(settings: Settings, days: int = 120, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    owns_conn = conn is None
    conn = conn or _connect(settings.activity_db_path)
    if not conn:
        return {"days": days, "activityDaily": [], "activityWeekly": [], "activityMonthly": [], "healthDaily": [], "summary": {}}
    try:
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)
        activity_daily = _activity_series_between(conn, start, end, "day")
        activity_weekly = _activity_weekly_series(conn, start, end)
        activity_monthly = _activity_series_between(conn, start, end, "month")
        health_daily = _health_daily_rows(conn, start, end)
        summary = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "days": days,
            "activity": _activity_summary_between(conn, start, end),
            "health": health_summary_for_range(conn, start, end, f"近 {days} 天"),
            "activityRows": len(activity_daily),
            "healthRows": len(health_daily),
        }
        weight_rows = [
            row
            for row in ((latest_weight_payload(settings).get("bodyScale") or {}).get("series") or [])
            if _parse_date(row.get("date")) and start <= _parse_date(row.get("date")) <= end
        ]
        return {
            "days": days,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "summary": summary,
            "activityDaily": activity_daily,
            "activityWeekly": activity_weekly,
            "activityMonthly": activity_monthly,
            "healthDaily": health_daily,
            "weight": weight_rows,
            "recentActivities": [_drilldown_activity_row(item) for item in _activities_between(conn, start, end, 80)],
        }
    finally:
        if owns_conn and conn:
            conn.close()


def latest_weight_payload(settings: Settings) -> dict[str, Any]:
    data = _read_json(settings.weight_data_path, [])
    if not isinstance(data, list) or not data:
        return {"records": 0, "latest": None}
    latest = data[0]
    previous = data[1] if len(data) > 1 else None
    change = None
    if isinstance(latest, dict) and isinstance(previous, dict):
        current_weight = _to_float(latest.get("Weight") or latest.get("weight_kg"))
        previous_weight = _to_float(previous.get("Weight") or previous.get("weight_kg"))
        if current_weight and previous_weight:
            change = round(current_weight - previous_weight, 2)
    body_scale = _body_scale_payload(data)
    return {"records": len(data), "latest": latest, "previous": previous, "changeKg": change, "recent": data[:12], "bodyScale": body_scale}


def _pick_number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        parsed = _to_float(value)
        if parsed:
            return parsed
    return 0.0


def _body_scale_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_date = row.get("Date") or row.get("date") or ""
    return {
        "date": str(raw_date),
        "label": str(raw_date)[:10],
        "weightKg": round(_pick_number(row, "Weight", "weight_kg"), 2),
        "bodyFatPct": round(_pick_number(row, "BodyFat", "body_fat_pct"), 2),
        "muscleMassKg": round(_pick_number(row, "MuscleMass", "Muscle", "muscle_mass_kg", "muscle_kg"), 2),
        "bmi": round(_pick_number(row, "BMI", "bmi"), 2),
        "waterPct": round(_pick_number(row, "BodyWater", "Water", "body_water_pct", "water_pct"), 2),
        "bodyScore": round(_pick_number(row, "BodyScore", "body_score"), 1),
    }


def _metric_change(series: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row for row in series if _to_float(row.get(key))]
    if len(values) < 2:
        return {"latest": values[-1].get(key) if values else 0, "previous": 0, "change": 0, "rangeChange": 0}
    latest = _to_float(values[-1].get(key))
    previous = _to_float(values[-2].get(key))
    first = _to_float(values[0].get(key))
    return {
        "latest": round(latest, 2),
        "previous": round(previous, 2),
        "change": round(latest - previous, 2),
        "rangeChange": round(latest - first, 2),
    }


def _body_scale_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [
        _body_scale_row(row)
        for row in rows
        if _parse_date(row.get("Date") or row.get("date"))
    ]
    normalized = sorted(normalized, key=lambda item: str(item.get("date") or ""))
    series = normalized[-120:]
    changes = {
        "weight": _metric_change(series, "weightKg"),
        "bodyFat": _metric_change(series, "bodyFatPct"),
        "muscleMass": _metric_change(series, "muscleMassKg"),
    }
    latest = series[-1] if series else {}
    analysis = [
        {
            "label": "体重",
            "value": latest.get("weightKg"),
            "unit": "kg",
            "change": changes["weight"].get("rangeChange"),
        },
        {
            "label": "体脂率",
            "value": latest.get("bodyFatPct"),
            "unit": "%",
            "change": changes["bodyFat"].get("rangeChange"),
        },
        {
            "label": "肌肉量",
            "value": latest.get("muscleMassKg"),
            "unit": "kg",
            "change": changes["muscleMass"].get("rangeChange"),
        },
    ]
    return {
        "series": series,
        "latest": latest,
        "changes": changes,
        "analysis": analysis,
        "startDate": series[0].get("date") if series else "",
        "endDate": series[-1].get("date") if series else "",
    }


def activity_detail_payload(settings: Settings, activity_id: str) -> dict[str, Any] | None:
    conn = _connect(settings.activity_db_path)
    if not conn:
        return None
    try:
        if not _table_exists(conn, "activities"):
            return None
        activity = _one(conn, "SELECT * FROM activities WHERE activity_id = ?", (activity_id,))
        if not activity:
            return None
        laps = _rows(
            conn,
            "SELECT * FROM laps WHERE activity_id = ? ORDER BY lap_index ASC, id ASC",
            (activity_id,),
        ) if _table_exists(conn, "laps") else []
    finally:
        conn.close()
    fit_file = _activity_fit_file(settings, activity)
    if not laps and fit_file:
        laps = parse_fit_laps(fit_file, str(activity.get("activity_id") or activity_id))
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "activity": {**activity, "derived": _activity_derived(activity, laps)},
        "laps": [
            {**lap, "derived": _activity_derived(lap)}
            for lap in laps
        ],
        "files": {
            "fitAvailable": bool(fit_file),
            "fitFileName": fit_file.name if fit_file else None,
        },
    }


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


def activity_laps_csv(laps: list[dict[str, Any]]) -> str:
    fieldnames = ["lap_index", "distance_m", "duration_s", "pace_sec_per_km", "avg_hr", "calories"]
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for lap in laps:
        derived = lap.get("derived") or {}
        writer.writerow({
            "lap_index": lap.get("lap_index"),
            "distance_m": lap.get("distance_m"),
            "duration_s": lap.get("duration_s"),
            "pace_sec_per_km": derived.get("paceSecPerKm"),
            "avg_hr": lap.get("avg_hr"),
            "calories": lap.get("calories"),
        })
    return buf.getvalue()


def activity_download_archive(settings: Settings, activity_id: str) -> dict[str, Any] | None:
    detail = activity_detail_payload(settings, activity_id)
    if not detail:
        return None
    activity = detail["activity"]
    safe_id = _safe_file_part(str(activity.get("activity_id") or activity_id))
    build_dir = settings.runtime_dir / "activity-downloads" / safe_id
    build_dir.mkdir(parents=True, exist_ok=True)
    json_path = build_dir / f"activity-{safe_id}.json"
    laps_path = build_dir / f"laps-{safe_id}.csv"
    json_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    laps_path.write_text(activity_laps_csv(detail.get("laps") or []), encoding="utf-8")

    archive = settings.runtime_dir / "activity-downloads" / f"garmin-activity-{safe_id}.zip"
    fit_file = _activity_fit_file(settings, activity)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, arcname=json_path.name)
        zf.write(laps_path, arcname=laps_path.name)
        if fit_file:
            zf.write(fit_file, arcname=f"fit/{fit_file.name}")
    return {
        "path": str(archive),
        "name": archive.name,
        "size": archive.stat().st_size,
        "activityId": activity.get("activity_id"),
        "fitIncluded": bool(fit_file),
    }


def activity_bulk_download_archive(settings: Settings, limit: int = 200) -> dict[str, Any] | None:
    conn = _connect(settings.activity_db_path)
    if not conn:
        return None
    try:
        if not _table_exists(conn, "activities"):
            return None
        rows = _rows(
            conn,
            """
            SELECT activity_id
            FROM activities
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 200), 500)),),
        )
    finally:
        conn.close()
    activity_ids = [str(row.get("activity_id")) for row in rows if row.get("activity_id")]
    if not activity_ids:
        return None

    build_dir = settings.runtime_dir / "activity-downloads" / "bulk"
    build_dir.mkdir(parents=True, exist_ok=True)
    archive = settings.runtime_dir / "activity-downloads" / f"garmin-activities-{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        summary_csv = activities_csv(settings, limit=max(1, min(int(limit or 200), 500)))
        zf.writestr("activities.csv", summary_csv)
        zf.writestr("README.txt", "Garmin Sync batch export. Each activity includes JSON and laps CSV; FIT is included when available.\n")
        included = 0
        fit_count = 0
        for activity_id in activity_ids:
            detail = activity_detail_payload(settings, activity_id)
            if not detail:
                continue
            activity = detail["activity"]
            safe_id = _safe_file_part(str(activity.get("activity_id") or activity_id))
            prefix = f"activities/{safe_id}"
            zf.writestr(f"{prefix}/activity.json", json.dumps(detail, ensure_ascii=False, indent=2))
            zf.writestr(f"{prefix}/laps.csv", activity_laps_csv(detail.get("laps") or []))
            fit_file = _activity_fit_file(settings, activity)
            if fit_file:
                zf.write(fit_file, arcname=f"{prefix}/fit/{fit_file.name}")
                fit_count += 1
            included += 1
    return {
        "path": str(archive),
        "name": archive.name,
        "size": archive.stat().st_size,
        "activityCount": included,
        "fitCount": fit_count,
    }


def activities_csv(settings: Settings, limit: int = 200) -> str:
    conn = _connect(settings.activity_db_path)
    if not conn:
        return ""
    try:
        rows = _rows(
            conn,
            """
            SELECT activity_id, name, sport_type, start_time, distance_m, duration_s,
                   avg_pace_s_per_km, avg_hr, max_hr, calories, elevation_gain_m
            FROM activities
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (limit,),
        )
    finally:
        conn.close()
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["activity_id"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def latest_report(settings: Settings) -> dict[str, Any] | None:
    reports = [
        path
        for path in settings.reports_dir.glob("garmin-daily-*")
        if path.is_dir() or path.suffix == ".zip"
    ] if settings.reports_dir.exists() else []
    reports = sorted(reports, key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return None
    path = reports[0]
    if path.is_dir():
        files = sorted([item for item in path.iterdir() if item.is_file()], key=lambda item: item.name)
        return {
            "name": path.name,
            "type": "directory",
            "size": sum(item.stat().st_size for item in files),
            "fileCount": len(files),
            "files": [{"name": item.name, "size": item.stat().st_size} for item in files],
            "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        }
    return {
        "name": path.name,
        "type": "zip",
        "size": path.stat().st_size,
        "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }
