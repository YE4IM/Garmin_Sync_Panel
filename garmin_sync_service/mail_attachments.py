from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any


def content_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in {".json", ".csv", ".md", ".txt"}:
        return "text/plain"
    return "application/octet-stream"


def report_attachments(report: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = report.get("attachments") or []
    output: list[dict[str, Any]] = []
    for item in attachments:
        path = Path(str(item.get("path") or ""))
        if not path.exists() or not path.is_file():
            continue
        output.append({
            "path": path,
            "name": str(item.get("name") or path.name),
            "contentType": str(item.get("contentType") or content_type_for(path)),
            "size": path.stat().st_size,
        })
    if output:
        return output

    legacy_path = Path(str(report.get("path") or ""))
    if legacy_path.exists() and legacy_path.is_file():
        return [{
            "path": legacy_path,
            "name": legacy_path.name,
            "contentType": content_type_for(legacy_path),
            "size": legacy_path.stat().st_size,
        }]
    return []


def total_attachment_size(report: dict[str, Any]) -> int:
    return sum(int(item.get("size") or 0) for item in report_attachments(report))
