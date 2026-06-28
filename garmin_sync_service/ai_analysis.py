from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from typing import Any

import httpx

from .config import Settings
from .one_time_prompt import load_one_time_prompt, mark_one_time_prompt_used
from .preferences import load_personal_profile


def latest_ai_analysis(settings: Settings) -> dict[str, Any]:
    if not settings.ai_analysis_path.exists():
        return {"configured": bool(settings.mimo_api_key), "ok": None, "content": ""}
    try:
        payload = json.loads(settings.ai_analysis_path.read_text(encoding="utf-8"))
    except Exception:
        return {"configured": bool(settings.mimo_api_key), "ok": False, "content": "", "message": "AI 分析缓存不可读"}
    payload["configured"] = bool(settings.mimo_api_key)
    payload["stale"] = _is_stale(settings, payload.get("generatedAt"))
    payload["sections"] = _content_sections(payload.get("content", ""), payload.get("sections"))
    return payload


def _is_stale(settings: Settings, generated_at: str | None) -> bool:
    if not generated_at:
        return True
    try:
        dt = datetime.fromisoformat(generated_at)
    except ValueError:
        return True
    return datetime.now() - dt > timedelta(hours=settings.ai_analysis_cache_hours)


def _analysis_input(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    stats = payload.get("activityStats") or {}
    health = payload.get("healthSummary") or {}
    long_range = payload.get("longRangeContext") or {}
    weight = payload.get("weight") or {}
    activities = payload.get("activities") or []
    one_time = load_one_time_prompt(settings)
    recent_activities = [
        {
            "sportType": item.get("sport_type"),
            "startTime": item.get("start_time"),
            "distanceKm": (item.get("derived") or {}).get("distanceKm"),
            "durationMin": (item.get("derived") or {}).get("durationMin"),
            "paceSecPerKm": (item.get("derived") or {}).get("paceSecPerKm"),
            "avgHr": item.get("avg_hr"),
            "maxHr": item.get("max_hr"),
            "calories": item.get("calories"),
        }
        for item in activities[:8]
    ]
    return {
        "generatedAt": payload.get("generatedAt"),
        "personalProfile": load_personal_profile(settings),
        "oneTimeContext": {
            "prompt": one_time.get("prompt") if one_time.get("active") and not one_time.get("aiUsed") else "",
            "usage": "只用于本次 AI 建议和本次邮件发送，使用后从服务器临时状态删除。",
        },
        "activityStats": {
            "total": stats.get("total"),
            "last7Days": stats.get("last7Days"),
            "last30Days": stats.get("last30Days"),
            "bySport": stats.get("bySport"),
            "dailyDistance": stats.get("dailyDistance"),
        },
        "healthSummary": health,
        "longRangeContext": {
            "days": long_range.get("days"),
            "startDate": long_range.get("startDate"),
            "endDate": long_range.get("endDate"),
            "summary": long_range.get("summary"),
            "activityDaily": (long_range.get("activityDaily") or [])[-120:],
            "activityWeekly": long_range.get("activityWeekly") or [],
            "activityMonthly": long_range.get("activityMonthly") or [],
            "healthDaily": (long_range.get("healthDaily") or [])[-120:],
            "weight": long_range.get("weight") or [],
            "recentActivities": [
                {
                    "sportType": item.get("sportType"),
                    "startTime": item.get("startTime"),
                    "distanceKm": item.get("distanceKm"),
                    "durationMin": item.get("durationMin"),
                    "paceSecPerKm": item.get("paceSecPerKm"),
                    "avgHr": item.get("avgHr"),
                    "maxHr": item.get("maxHr"),
                    "calories": item.get("calories"),
                }
                for item in (long_range.get("recentActivities") or [])[:40]
            ],
        },
        "weight": {
            "records": weight.get("records"),
            "latest": weight.get("latest"),
            "changeKg": weight.get("changeKg"),
            "bodyScale": {
                "latest": (weight.get("bodyScale") or {}).get("latest"),
                "changes": (weight.get("bodyScale") or {}).get("changes"),
                "analysis": (weight.get("bodyScale") or {}).get("analysis"),
                "series": ((weight.get("bodyScale") or {}).get("series") or [])[-120:],
            },
            "recent": (weight.get("recent") or [])[:8],
        },
        "latestActivity": recent_activities[0] if recent_activities else {},
        "recentActivities": recent_activities,
    }


def _fingerprint(compact_payload: dict[str, Any]) -> str:
    raw = json.dumps(compact_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_ai_analysis_if_needed(
    settings: Settings,
    payload: dict[str, Any],
    *,
    source_finished_at: str = "",
    force: bool = False,
) -> dict[str, Any]:
    compact_payload = _analysis_input(settings, payload)
    fingerprint = _fingerprint(compact_payload)
    cached = latest_ai_analysis(settings)
    if (
        not force
        and cached.get("ok") is True
        and cached.get("inputFingerprint") == fingerprint
        and not cached.get("stale")
    ):
        return {**cached, "skipped": True, "reason": "summary unchanged"}
    return generate_ai_analysis(
        settings,
        payload,
        source_finished_at=source_finished_at,
        input_fingerprint=fingerprint,
    )


def generate_ai_analysis(
    settings: Settings,
    payload: dict[str, Any],
    *,
    source_finished_at: str = "",
    input_fingerprint: str = "",
) -> dict[str, Any]:
    if not settings.mimo_api_key:
        return {"configured": False, "ok": False, "message": "MIMO_API_KEY is not configured", "content": ""}

    compact_payload = _analysis_input(settings, payload)
    input_fingerprint = input_fingerprint or _fingerprint(compact_payload)
    body = {
        "model": settings.mimo_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个私人运动健康数据分析助手。只基于用户提供的摘要数据分析，"
                    "结合 personalProfile 中的长期个人背景和 oneTimeContext 中的一次性状态/训练计划，"
                    "但不要臆造医疗诊断。输出中文，简洁、可执行。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请分析下面近 14/30 天摘要，并重点结合 longRangeContext 中近 120 天长期数据；"
                    "体脂秤分析要重点关注体重、肌肉量、体脂率三条趋势。"
                    "只输出 JSON 对象，不要 Markdown，不要代码块。JSON schema："
                    "{\"summary\":\"一句总体结论\",\"sections\":[{\"title\":\"总体状态\","
                    "\"items\":[{\"label\":\"要点名\",\"text\":\"一句具体建议或发现\","
                    "\"tone\":\"good|warn|neutral\"}]}]}。"
                    "固定 5 个 section：总体状态、运动趋势、恢复与健康趋势、本次训练评估、下一步建议。"
                    "本次训练评估必须针对 latestActivity 和 oneTimeContext 给出，不要泛泛而谈。"
                    "每节 1-3 条，优先指出趋势、风险信号和行动建议。\n\n"
                    + json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ],
        "max_completion_tokens": 1600,
        "temperature": 0.3,
        "top_p": 0.9,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    try:
        response = httpx.post(
            settings.mimo_api_url,
            headers={"api-key": settings.mimo_api_key, "Content-Type": "application/json"},
            json=body,
            timeout=settings.request_timeout_seconds,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            return {
                "configured": True,
                "ok": False,
                "message": data.get("error", {}).get("message") or data.get("message") or "MiMo request failed",
                "content": "",
                "generatedAt": datetime.now().isoformat(timespec="seconds"),
                "sourceFinishedAt": source_finished_at,
                "inputFingerprint": input_fingerprint,
            }
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except Exception as exc:
        return {
            "configured": True,
            "ok": False,
            "message": f"AI 分析失败：{exc}",
            "content": "",
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "sourceFinishedAt": source_finished_at,
            "inputFingerprint": input_fingerprint,
        }

    result = {
        "configured": True,
        "ok": True,
        "provider": "xiaomi-mimo",
        "model": settings.mimo_model,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceFinishedAt": source_finished_at,
        "inputFingerprint": input_fingerprint,
        "content": content,
        "sections": _content_sections(content),
        "usage": data.get("usage"),
    }
    settings.ai_analysis_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if (compact_payload.get("oneTimeContext") or {}).get("prompt"):
        mark_one_time_prompt_used(settings, "ai")
    return result


def _clean_json_text(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _strip_markup(value: str) -> str:
    text = str(value or "").strip()
    text = text.lstrip("-*•0123456789.、) ").strip()
    text = text.replace("**", "").replace("__", "").replace("###", "").replace("##", "").replace("#", "")
    return text.strip()


def _sanitize_sections(sections: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if not isinstance(sections, list):
        return output
    for section in sections[:6]:
        if not isinstance(section, dict):
            continue
        title = _strip_markup(section.get("title") or "分析")
        items: list[dict[str, str]] = []
        for item in section.get("items") or []:
            if isinstance(item, str):
                label = ""
                text = _strip_markup(item)
                tone = "neutral"
            elif isinstance(item, dict):
                label = _strip_markup(item.get("label") or "")
                text = _strip_markup(item.get("text") or item.get("content") or "")
                tone = str(item.get("tone") or "neutral").strip().lower()
            else:
                continue
            if tone not in {"good", "warn", "neutral"}:
                tone = "neutral"
            if text:
                items.append({"label": label[:40], "text": text[:260], "tone": tone})
        if title and items:
            output.append({"title": title[:40], "items": items[:4]})
    return output


def _sections_from_markdown(content: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = _strip_markup(line)
            current = {"title": title or "分析", "items": []}
            sections.append(current)
            continue
        if line.startswith(("-", "*", "•")):
            if current is None:
                current = {"title": "AI 建议", "items": []}
                sections.append(current)
            text = _strip_markup(line)
            label = ""
            if "：" in text:
                maybe_label, rest = text.split("：", 1)
                if len(maybe_label) <= 20:
                    label = _strip_markup(maybe_label)
                    text = _strip_markup(rest)
            elif ":" in text:
                maybe_label, rest = text.split(":", 1)
                if len(maybe_label) <= 20:
                    label = _strip_markup(maybe_label)
                    text = _strip_markup(rest)
            tone = "warn" if any(word in text for word in ("下降", "不足", "风险", "注意", "中断")) else "good" if any(word in text for word in ("良好", "提升", "改善", "稳定")) else "neutral"
            if text:
                current["items"].append({"label": label, "text": text, "tone": tone})
        elif current is not None:
            text = _strip_markup(line)
            if text:
                current["items"].append({"label": "", "text": text, "tone": "neutral"})
    return _sanitize_sections(sections)


def _sections_from_json_lines(content: str) -> list[dict[str, Any]]:
    """
    Recover useful cards from a JSON response that was truncated before closing.
    MiMo can stop at max tokens while the completed section/item lines are still valid.
    """
    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_item: dict[str, str] | None = None
    in_item = False

    def quoted_value(line: str) -> str:
        if ":" not in line:
            return ""
        value = line.split(":", 1)[1].strip().rstrip(",")
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            return value[1:-1].replace('\\"', '"').replace("\\n", "\n")
        return ""

    def flush_item() -> None:
        nonlocal current_item, in_item
        if current_section is not None and current_item and current_item.get("text"):
            current_section.setdefault("items", []).append(current_item)
        current_item = None
        in_item = False

    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('"title"'):
            flush_item()
            title = _strip_markup(quoted_value(line))
            if title:
                current_section = {"title": title, "items": []}
                sections.append(current_section)
            continue
        if line == "{" and current_section is not None:
            in_item = True
            current_item = {"label": "", "text": "", "tone": "neutral"}
            continue
        if line.startswith('"label"') and current_section is not None:
            if current_item is None:
                current_item = {"label": "", "text": "", "tone": "neutral"}
            current_item["label"] = _strip_markup(quoted_value(line))[:40]
            in_item = True
            continue
        if line.startswith('"text"') and current_section is not None:
            if current_item is None:
                current_item = {"label": "", "text": "", "tone": "neutral"}
            current_item["text"] = _strip_markup(quoted_value(line))[:260]
            in_item = True
            continue
        if line.startswith('"tone"') and current_item is not None:
            tone = quoted_value(line).strip().lower()
            current_item["tone"] = tone if tone in {"good", "warn", "neutral"} else "neutral"
            continue
        if line.startswith("}") and in_item:
            flush_item()
    flush_item()
    return _sanitize_sections(sections)


def _content_sections(content: str, existing: Any = None) -> list[dict[str, Any]]:
    sections = _sanitize_sections(existing)
    if sections:
        return sections
    text = _clean_json_text(content)
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if isinstance(data, dict):
        sections = _sanitize_sections(data.get("sections"))
        if sections:
            return sections
        summary = _strip_markup(data.get("summary") or "")
        if summary:
            return [{"title": "总体结论", "items": [{"label": "", "text": summary, "tone": "neutral"}]}]
    sections = _sections_from_json_lines(content)
    if sections:
        return sections
    return _sections_from_markdown(content)
