from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .constants import AREA_LABELS
from .settings import ANALYSIS_DIR


def _file_url(path_value: str | None, mount_prefix: str) -> str | None:
    if not path_value:
        return None
    return f"{mount_prefix}/{Path(path_value).name}"


def _loads_json(raw_value: str | None) -> Any:
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return None


def analysis_summary_path(result_id: str) -> Path:
    return ANALYSIS_DIR / result_id / "analysis.json"


def serialize_result(row: sqlite3.Row) -> dict[str, Any]:
    color_palette = _loads_json(row["color_palette"]) or {}
    render_preset = _loads_json(row["render_preset"]) or {}
    selection_range = _loads_json(row["selection_range"])
    image_path = row["image_path"]
    html_path = row["html_path"]
    area_type = row["area_type"]
    title = row["title"] or f"{AREA_LABELS.get(area_type, '规划')}生成任务"

    return {
        "id": row["id"],
        "title": title,
        "prompt": row["prompt"],
        "rewritten_prompt": row["rewritten_prompt"],
        "negative_prompt": row["negative_prompt"],
        "intent": row["intent"],
        "area_type": area_type,
        "area_label": AREA_LABELS.get(area_type, "规划"),
        "area_flag": row["area_flag"],
        "model_key": row["model_key"],
        "color_palette": color_palette,
        "render_preset": render_preset,
        "selection_range": selection_range,
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "image_url": _file_url(image_path, "/images"),
        "html_url": _file_url(html_path, "/outputs"),
        "image_exists": bool(image_path and Path(image_path).exists()),
        "html_exists": bool(html_path and Path(html_path).exists()),
        "analysis_ready": analysis_summary_path(row["id"]).exists(),
        "analysis_url": f"/results/{row['id']}/analysis",
    }
