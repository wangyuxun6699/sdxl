from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .analysis_service import analysis_result_dir, ensure_spatial_analysis
from .generation_service import generate_assets
from .llm_router import route_user_message
from .logger import log_step
from .repository import (
    delete_result_record,
    fetch_result,
    insert_result,
    list_results,
    update_result,
)
from .schemas import AnalysisRequest, ChatRequest, ResultUpdateRequest
from .settings import IMAGES_DIR, OUTPUTS_DIR


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    prompt = request.message.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="消息不能为空")

    selection_range = request.selection_range.model_dump() if request.selection_range else None
    log_step("CHAT", f"Incoming prompt: {prompt}")
    if selection_range:
        log_step("CHAT", f"Selection range: {selection_range}")

    # 路由层把自然语言收敛为稳定的生成参数，后续模块不直接依赖 LLM 的原始文本。
    routed_payload = route_user_message(prompt)
    log_step("CHAT", f"Intent: {routed_payload['intent']}")

    if routed_payload["intent"] == "chat":
        return {"status": "success", "intent": "chat", "content": routed_payload["reply"]}

    # request_id 同时作为数据库主键和所有磁盘产物的命名空间。
    request_id = str(uuid.uuid4())
    try:
        image_path, html_path = generate_assets(request_id, routed_payload)
    except subprocess.CalledProcessError as exc:
        detail = (
            f"Generation pipeline failed: {exc}\n"
            f"STDERR:\n{exc.stderr or ''}\n"
            f"STDOUT:\n{exc.output or ''}"
        )
        log_step("ERROR", detail)
        raise HTTPException(status_code=500, detail=detail) from exc
    except FileNotFoundError as exc:
        log_step("ERROR", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    insert_result(
        result_id=request_id,
        prompt=prompt,
        routed_payload=routed_payload,
        image_path=image_path,
        html_path=html_path,
        selection_range=selection_range,
    )

    # 代理分析失败不回滚已经完成的生图和 3D 结果，前端仍可展示并支持稍后重算。
    analysis: dict[str, Any] | None = None
    analysis_error: str | None = None
    try:
        analysis = ensure_spatial_analysis(request_id)
        log_step("CHAT", f"Analysis completed for request_id: {request_id}")
    except Exception as exc:
        analysis_error = str(exc)
        log_step("ERROR", f"Analysis failed for request_id {request_id}: {analysis_error}")

    result = fetch_result(request_id)
    log_step("CHAT", f"Completed request_id: {request_id}")
    return {
        "status": "success",
        "intent": "generate",
        "request_id": request_id,
        "result": result,
        "image_url": result["image_url"],
        "html_url": result["html_url"],
        "payload": routed_payload,
        "analysis": analysis,
        "analysis_error": analysis_error,
    }


@router.get("/results")
async def get_results() -> dict[str, list[dict[str, Any]]]:
    return {"items": list_results()}


@router.get("/results/{result_id}")
async def get_result(result_id: str) -> dict[str, Any]:
    return fetch_result(result_id)


@router.get("/results/{result_id}/analysis")
async def get_result_analysis(result_id: str) -> dict[str, Any]:
    return ensure_spatial_analysis(result_id)


@router.post("/results/{result_id}/analysis")
async def run_result_analysis(result_id: str, request: AnalysisRequest) -> dict[str, Any]:
    return ensure_spatial_analysis(result_id, force=True, analysis_request=request)


@router.patch("/results/{result_id}")
async def patch_result(result_id: str, request: ResultUpdateRequest) -> dict[str, Any]:
    return update_result(result_id, title=request.title, notes=request.notes)


@router.delete("/results/{result_id}")
async def delete_result(result_id: str) -> dict[str, str]:
    existing = fetch_result(result_id)
    delete_result_record(result_id)

    # 只取数据库 URL 的文件名并拼到受控目录，避免把外部路径当作删除目标。
    for mount_url, base_dir in (
        (existing["image_url"], IMAGES_DIR),
        (existing["html_url"], OUTPUTS_DIR),
    ):
        local_path = base_dir / Path(mount_url or "").name
        if local_path.exists():
            local_path.unlink()

    result_analysis_dir = analysis_result_dir(result_id)
    if result_analysis_dir.exists():
        shutil.rmtree(result_analysis_dir)

    return {"status": "success", "message": "结果已删除"}
