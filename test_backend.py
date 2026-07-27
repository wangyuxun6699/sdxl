from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
HEADERS = {"Content-Type": "application/json"}


def call_api(method: str, path: str, *, timeout: int = 300, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{BASE_URL}{path}",
        headers=HEADERS if method.upper() != "GET" else None,
        timeout=timeout,
        **kwargs,
    )
    try:
        payload = response.json()
    except Exception as exc:
        raise AssertionError(f"{method} {path} returned non-JSON response: {response.text}") from exc

    if not response.ok:
        raise AssertionError(
            f"{method} {path} failed with {response.status_code}: "
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def print_json(title: str, payload: dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    print(f"API_BASE_URL={BASE_URL}")
    if os.getenv("CITY_PLANNER_TEST_MODE"):
        print("CITY_PLANNER_TEST_MODE=1，使用轻量测试链路，不调用外部 LLM 或 SDXL。")

    health = call_api("GET", "/health", timeout=30)
    require(health.get("status") == "ok", "health check failed")
    print_json("health", health)

    chat_payload = call_api(
        "POST",
        "/chat",
        json={"message": "你好，请简要介绍你的工作流。"},
        timeout=60,
    )
    require(chat_payload.get("intent") == "chat", "chat intent routing failed")
    require(chat_payload.get("content"), "chat response content is empty")
    print_json(
        "chat intent",
        {
            "intent": chat_payload.get("intent"),
            "content": chat_payload.get("content"),
        },
    )

    generation_payload = call_api(
        "POST",
        "/chat",
        json={
            "message": "生成一个商业区总平面规划图，蓝色建筑块，白色背景，并完成 2D 转 3D 和日照通风分析。"
        },
        timeout=600,
    )
    require(generation_payload.get("intent") == "generate", "generate intent routing failed")
    result = generation_payload.get("result") or {}
    require(result.get("id"), "missing result id")
    require(result.get("image_url"), "missing image url")
    require(result.get("html_url"), "missing html url")
    require(result.get("image_exists") is True, "image file was not created")
    require(result.get("html_exists") is True, "html file was not created")

    analysis = generation_payload.get("analysis")
    if analysis is None:
        analysis = call_api("GET", f"/results/{result['id']}/analysis", timeout=300)

    require(analysis.get("result_id") == result["id"], "analysis result id mismatch")
    require(analysis.get("sunlight", {}).get("metrics"), "missing sunlight metrics")
    require(analysis.get("wind", {}).get("metrics"), "missing wind metrics")
    print_json(
        "generate pipeline",
        {
            "result_id": result["id"],
            "title": result.get("title"),
            "area_type": result.get("area_type"),
            "image_url": result.get("image_url"),
            "html_url": result.get("html_url"),
            "analysis_ready": bool(analysis),
            "sunlight": analysis.get("sunlight", {}).get("metrics"),
            "wind": analysis.get("wind", {}).get("metrics"),
            "wind_comparison": analysis.get("wind_comparison"),
        },
    )

    results_payload = call_api("GET", "/results", timeout=30)
    require(any(item.get("id") == result["id"] for item in results_payload.get("items", [])), "result is not listed")
    print_json("results", {"count": len(results_payload.get("items", [])), "latest_id": result["id"]})

    print("\n所有后端链路检查通过。")


if __name__ == "__main__":
    main()
