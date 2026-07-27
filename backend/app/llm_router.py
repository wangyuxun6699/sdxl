from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .constants import (
    AREA_META,
    CHAT_KEYWORDS,
    DEFAULT_NEGATIVE_PROMPT,
    GENERATE_HINTS,
)
from .logger import log_step
from .prompt_tools import (
    default_palette,
    normalize_area_type,
    normalize_generation_prompt,
    normalize_negative_prompt,
    normalize_render_preset,
)
from .settings import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, DASHSCOPE_MODEL, is_test_mode


ROUTER_SYSTEM_PROMPT = """
你是城市规划生成系统的意图路由器。你只能返回一个 JSON 对象，不要输出 Markdown，也不要解释。

当用户只是问候、闲聊、感谢或询问系统能力时，返回：
{"intent":"chat","reply":"简短中文回复"}

当用户要求生成规划图、片区布局、建筑群、2D/3D 效果或设计方案时，返回：
{
  "intent":"generate",
  "prompt":"English SDXL prompt",
  "negative_prompt":"English negative prompt",
  "area_type":"residential|industrial|commercial|public",
  "global_palette":{"primary":"#RRGGBB","secondary":"#RRGGBB","background":"#FFFFFF"},
  "render_preset":{"width":1024,"height":1024,"guidance_scale":7.0,"num_inference_steps":30,"num_images_per_prompt":1},
  "title":"简短中文标题"
}

规则：
- prompt 和 negative_prompt 必须是英文，适配 SDXL。
- 默认生成俯视、干净、纯白背景、用于 2D 转 3D 的城市规划图。
- 居住区只用绿色建筑块；工业区只用黄色建筑块；商业区只用蓝色建筑块；公共区只用红色建筑块。
- 不要生成道路、文字、标注、人物、车辆、公园、草坪、边框或线稿。
- 如果是混合功能片区，选择主导类型，并在 prompt 中加入 mixed-use 特征。
- 最终只返回 JSON 对象。
""".strip()


def _extract_json_block(text: str) -> dict[str, Any]:
    """兼容模型偶尔返回 Markdown 围栏或 JSON 前后附带说明的情况。"""
    candidate = text.strip()
    fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", candidate, re.S)
    if fenced_match:
        candidate = fenced_match.group(1)
    else:
        object_match = re.search(r"(\{.*\})", candidate, re.S)
        if object_match:
            candidate = object_match.group(1)
    return json.loads(candidate)


def _looks_like_generation(prompt: str) -> bool:
    normalized = prompt.strip().lower()
    if normalized in CHAT_KEYWORDS:
        return False
    return any(token in normalized for token in GENERATE_HINTS)


def _infer_area_type(prompt: str) -> str:
    normalized = prompt.strip().lower()
    area_matches = {
        "industrial": ("工业", "厂区", "物流", "仓储", "industrial"),
        "commercial": ("商业", "商办", "办公", "综合体", "commercial"),
        "public": ("公共", "学校", "医院", "文化", "政务", "public"),
        "residential": ("住宅", "居住", "社区", "小区", "residential"),
    }
    for area_type, keywords in area_matches.items():
        if any(keyword in normalized for keyword in keywords):
            return area_type
    return "residential"


@lru_cache(maxsize=1)
def _build_chain():
    # 连接和提示词模板只构造一次，避免每次请求重复初始化 LangChain 客户端。
    if not DASHSCOPE_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    escaped_system_prompt = ROUTER_SYSTEM_PROMPT.replace("{", "{{").replace("}", "}}")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", escaped_system_prompt),
            ("human", "{message}"),
        ]
    )
    model = ChatOpenAI(
        model=DASHSCOPE_MODEL,
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        temperature=0.2,
        max_retries=1,
        timeout=60,
    )
    return prompt | model | StrOutputParser()


def _call_router(prompt: str) -> dict[str, Any]:
    log_step("LANGCHAIN", f"Calling {DASHSCOPE_MODEL} via {DASHSCOPE_BASE_URL}")
    raw_response = _build_chain().invoke({"message": prompt})
    log_step("LANGCHAIN", f"Raw router output: {raw_response}")
    return _extract_json_block(raw_response)


def _fallback_generation_payload(prompt: str) -> dict[str, Any]:
    """外部 LLM 不可用时，仅为明显的生成请求提供可继续执行的保底参数。"""
    area_type = _infer_area_type(prompt)
    return {
        "intent": "generate",
        "prompt": (
            "top view urban planning masterplan, clean zoning composition, "
            "white background, solid building blocks only, suitable for 2D to 3D conversion, "
            f"{prompt}"
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
        "area_type": area_type,
        "title": "规划生成任务",
    }


def _normalize_generation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # 这是 LLM 输出与本地推理之间的边界：统一分区、颜色、负面词和尺寸上限。
    area_type = normalize_area_type(str(payload.get("area_type", "residential")))
    area_meta = AREA_META[area_type]
    render_preset = normalize_render_preset(payload.get("render_preset") or {})

    return {
        "intent": "generate",
        "title": str(payload.get("title") or f"{area_meta['label']}生成任务").strip(),
        "prompt": normalize_generation_prompt(str(payload.get("prompt") or ""), area_type),
        "negative_prompt": normalize_negative_prompt(
            str(payload.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT)
        ),
        "area_type": area_type,
        "area_label": area_meta["label"],
        "area_flag": area_meta["flag"],
        "model_key": area_type,
        "global_palette": payload.get("global_palette") or default_palette(area_type),
        "render_preset": render_preset,
    }


def route_user_message(prompt: str) -> dict[str, Any]:
    log_step("LANGCHAIN", "Routing user message")
    if is_test_mode():
        log_step("LANGCHAIN", "CITY_PLANNER_TEST_MODE enabled; using heuristic router")
        if _looks_like_generation(prompt):
            return _normalize_generation_payload(_fallback_generation_payload(prompt))
        return {
            "intent": "chat",
            "reply": "你好，我可以先识别你的意图；如果是规划生成任务，会继续生图、转 3D 并输出空间分析。",
        }

    try:
        payload = _call_router(prompt)
        log_step("LANGCHAIN", f"Parsed payload: {json.dumps(payload, ensure_ascii=False)}")
    except Exception as exc:
        log_step("LANGCHAIN", f"Router failed, using fallback: {exc}")
        if _looks_like_generation(prompt):
            payload = _fallback_generation_payload(prompt)
        else:
            return {
                "intent": "chat",
                "reply": f"我已经收到你的消息：{prompt}。当前大模型路由暂不可用，错误信息：{exc}",
            }

    intent = str(payload.get("intent", "")).strip().lower()
    if intent == "chat":
        return {
            "intent": "chat",
            "reply": str(payload.get("reply") or "你好，我可以帮你生成城市规划图和 3D 预览。").strip(),
        }
    return _normalize_generation_payload(payload)
