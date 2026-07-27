from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .constants import BUILDING_COLOR_BY_AREA, VALID_WIND_DIRECTIONS
from .repository import fetch_result_row
from .schemas import AnalysisRequest
from .serializers import analysis_summary_path
from .settings import ANALYSIS_DIR
from ..scripts.spatial_analysis import run_spatial_analysis


def analysis_result_dir(result_id: str) -> Path:
    return ANALYSIS_DIR / result_id


def ensure_spatial_analysis(
    result_id: str,
    *,
    force: bool = False,
    analysis_request: AnalysisRequest | None = None,
) -> dict[str, Any]:
    row = fetch_result_row(result_id)
    image_path = row["image_path"]
    if not image_path or not Path(image_path).exists():
        raise HTTPException(status_code=404, detail="缺少用于分析的原始图像")

    # GET 优先复用磁盘摘要；POST(force=True) 才按新的日照/风向参数重算并覆盖缓存。
    cached = None if force else load_analysis_summary(result_id)
    if cached is not None:
        return cached

    normalized = normalize_analysis_request(analysis_request)
    target_color = BUILDING_COLOR_BY_AREA.get(str(row["area_type"] or row["model_key"] or "").lower(), "auto")
    summary = run_spatial_analysis(
        image_path=image_path,
        output_dir=str(analysis_result_dir(result_id)),
        target_color=target_color,
        primary_wind_direction=normalized["primary_wind_direction"],
        wind_directions=normalized["wind_directions"],
        season_profile=normalized["season_profile"],
        sun_altitude_deg=normalized["sun_altitude_deg"],
    )
    return serialize_analysis_summary(result_id, summary)


def normalize_analysis_request(payload: AnalysisRequest | None = None) -> dict[str, Any]:
    request = payload or AnalysisRequest()
    primary = (request.primary_wind_direction or "west").strip().lower()
    if primary not in VALID_WIND_DIRECTIONS:
        primary = "west"

    directions: list[str] = []
    for direction in request.wind_directions or [primary]:
        value = str(direction).strip().lower()
        if value in VALID_WIND_DIRECTIONS and value not in directions:
            directions.append(value)
    if primary not in directions:
        directions.insert(0, primary)

    season = (request.season_profile or "spring").strip().lower()
    if season not in {"winter", "spring", "summer", "autumn", "custom"}:
        season = "spring"

    return {
        "season_profile": season,
        "sun_altitude_deg": request.sun_altitude_deg,
        "primary_wind_direction": primary,
        "wind_directions": directions,
    }


def load_analysis_summary(result_id: str) -> dict[str, Any] | None:
    summary_path = analysis_summary_path(result_id)
    if not summary_path.exists():
        return None
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    return serialize_analysis_summary(result_id, payload)


def serialize_analysis_summary(result_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把磁盘文件名转换为 API 可访问的静态资源 URL。"""
    summary = dict(payload)
    sunlight = dict(summary.get("sunlight") or {})
    wind = dict(summary.get("wind") or {})

    if sunlight.get("image_name"):
        sunlight["image_url"] = f"/analysis/{result_id}/{sunlight['image_name']}"
    if wind.get("image_name"):
        wind["image_url"] = f"/analysis/{result_id}/{wind['image_name']}"

    summary["sunlight"] = sunlight
    summary["wind"] = wind
    summary["result_id"] = result_id
    return summary
