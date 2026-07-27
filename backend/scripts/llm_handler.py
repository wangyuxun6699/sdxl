import json
import os
import re
from datetime import datetime
from http import HTTPStatus

try:
    import dashscope
    from dashscope import Generation
except ImportError:
    dashscope = None
    Generation = None


DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip().strip('"')
if DASHSCOPE_API_KEY:
    os.environ.setdefault("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY)
if dashscope is not None and DASHSCOPE_API_KEY:
    dashscope.api_key = DASHSCOPE_API_KEY


AREA_TYPE_MAP = {
    "residential": {"label": "住宅区", "flag": 1},
    "industrial": {"label": "工业区", "flag": 2},
    "commercial": {"label": "商业区", "flag": 3},
    "public": {"label": "公共区", "flag": 4},
}

DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, noisy, distorted perspective, photorealistic people, "
    "cars, text, labels, watermark, logo, cluttered layout, broken geometry, "
    "messy roads, dark background, overexposed highlights, unmapped colors, "
    "extra colors, non-white background, gradients, shadows, textures"
)

ENFORCED_NEGATIVE_TERMS = (
    "roads",
    "streets",
    "road networks",
    "pathways",
    "sidewalks",
    "parks",
    "lawns",
    "vegetation",
    "landscape areas",
    "open space markers",
    "colored roads",
    "colored outlines",
    "line-only drawings",
    "hollow blocks",
)

PROMPT_NOISE_PATTERNS = (
    r"\bclear road networks?\b",
    r"\broad networks?\b",
    r"\broads?\b",
    r"\bstreets?\b",
    r"\bpathways?\b",
    r"\bsidewalks?\b",
    r"\bopen spaces?\b",
    r"\bgreenery\b",
    r"\bparks?\b",
    r"\blawns?\b",
    r"\blandscape areas?\b",
)

DEFAULT_RENDER_PRESET = {
    "width": 1024,
    "height": 1024,
    "guidance_scale": 7.0,
    "num_inference_steps": 30,
    "num_images_per_prompt": 1,
}

CHAT_KEYWORDS = {
    "你好",
    "您好",
    "hello",
    "hi",
    "嗨",
    "在吗",
    "谢谢",
    "介绍一下",
}

GENERATE_HINTS = (
    "生成",
    "设计",
    "规划",
    "布局",
    "住宅",
    "工业",
    "商业",
    "公共",
    "园区",
    "街区",
    "鸟瞰",
    "总平",
    "用地",
    "建筑",
    "3d",
    "效果图",
    "地块",
)

ROUTER_PROMPT = """
你是一个城市规划生成系统的路由中枢。你只能返回 JSON，不要输出 Markdown，不要解释。
任务：
1. 如果用户只是闲聊、问候、感谢、解释性提问，返回聊天 JSON：{"intent":"chat","reply":"..."}
2. 如果用户是在请求生成规划图、片区布局、建筑群落、2D/3D 规划效果，则返回生成 JSON：
{
  "intent":"generate",
  "prompt":"English SDXL prompt",
  "negative_prompt":"English negative prompt",
  "area_type":"residential|industrial|commercial|public",
  "area_flag":1|2|3|4,
  "model_key":"residential|industrial|commercial|public",
  "global_palette":{
    "primary":"#RRGGBB",
    "secondary":"#RRGGBB",
    "background":"#RRGGBB"
  },
  "render_preset":{
    "width":1024,
    "height":1024,
    "guidance_scale":7.0,
    "num_inference_steps":30,
    "num_images_per_prompt":1
  },
  "title":"一个简短中文标题"
}


规则：
-   记住负向提示词要要有"low quality, blurry, noisy, distorted perspective, photorealistic people, "
    "cars, text, labels, watermark, logo, cluttered layout, broken geometry, "
    "messy roads, dark background, overexposed highlights"
- 居住区只用绿色表示，商业区只用蓝色，工业区只用黄色，公共区只用红色，请在负向提示词中加入限制条件，只有一种颜色。
- 居住区只用绿色表示，商业区只用蓝色，工业区只用黄色，公共区只用红色，请在负向提示词中加入限制条件，只有一种颜色。
- 提示词中颜色一定对应所选区域尽量详细。
- prompt 和 negative_prompt 必须是英文，适配 SDXL生图模型的提示词。
- 我的想法是生成用于 2D 转 3D 的城市规划图，请你根据这个想法设置提示词。
- area_type 只允许四类之一：residential、industrial、commercial、public。
- 如果用户是混合功能片区，选择主导区域类型，同时在 prompt 中补充 mixed-use 特征。
- global_palette 需要给出适合该区域的主色、辅色和背景色。
- render_preset 保持稳定，不要随意改成奇怪分辨率。
- 如果用户没有明确要求，默认俯视、总平面、干净、用于 2D 转 3D 的城市规划图。
- 最终只返回一个 JSON 对象。
""".strip()


def _log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [llm_handler] {message}", flush=True)


def _call_qwen(prompt: str) -> str:
    if Generation is None or dashscope is None:
        raise RuntimeError("dashscope is not installed")
    api_key = os.getenv("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY).strip().strip('"')
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    dashscope.api_key = api_key
    composed_prompt = f"{ROUTER_PROMPT}\n\n用户输入：{prompt}"
    model_name = "qwen3.7-plus"
    _log(f"Calling DashScope model: {model_name}")
    _log(f"User prompt: {prompt}")
    response = Generation.call(model=model_name, prompt=composed_prompt)
    if response.status_code != HTTPStatus.OK:
        _log(f"DashScope failed: {response.message}")
        raise RuntimeError(response.message)
    _log("DashScope succeeded")
    _log(f"Raw model output: {response.output.text}")
    return response.output.text


def _extract_json_block(text: str) -> dict:
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


def _normalize_area_type(area_type: str) -> str:
    raw = (area_type or "").strip().lower()
    alias_map = {
        "住宅": "residential",
        "住宅区": "residential",
        "residential_area": "residential",
        "工业": "industrial",
        "工业区": "industrial",
        "commercial_area": "commercial",
        "商业": "commercial",
        "商业区": "commercial",
        "public_area": "public",
        "公共": "public",
        "公共区": "public",
    }
    normalized = alias_map.get(raw, raw)
    return normalized if normalized in AREA_TYPE_MAP else "residential"


def _default_palette(area_type: str) -> dict:
    palettes = {
        "residential": {
            "primary": "#1F7A3A",
            "secondary": "#A8D96A",
            "background": "#FFFFFF",
        },
        "industrial": {
            "primary": "#B88400",
            "secondary": "#F4D35E",
            "background": "#FFFFFF",
        },
        "commercial": {
            "primary": "#1F5FBF",
            "secondary": "#8EC5FF",
            "background": "#FFFFFF",
        },
        "public": {
            "primary": "#C7362F",
            "secondary": "#FF9A8A",
            "background": "#FFFFFF",
        },
    }
    return palettes[area_type]


def _area_color_instruction(area_type: str) -> str:
    color_rules = {
        "residential": "Use only green building blocks: dark green for high-rise buildings and light green for low-rise buildings.",
        "industrial": "Use only yellow building blocks: deep yellow or ochre for high-rise buildings and light yellow for low-rise buildings.",
        "commercial": "Use only blue building blocks: dark blue for high-rise buildings and light blue for low-rise buildings.",
        "public": "Use only red building blocks: dark red for high-rise buildings and light red for low-rise buildings.",
    }
    return (
        f"{color_rules[area_type]} Keep a pure white background. "
        "Use a clean flat top-view plan with solid filled blocks only, optimized for 2D to 3D conversion. "
        "Do not draw roads, parcel outlines, parks, lawns, or landscape regions."
    )


def _sanitize_generation_prompt(prompt: str) -> str:
    sanitized = prompt or ""
    for pattern in PROMPT_NOISE_PATTERNS:
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+,", ",", sanitized)
    sanitized = re.sub(r",\s*,+", ",", sanitized)
    sanitized = re.sub(r"\b(and|with)\s*,", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r",\s*(and|with)\s*,", ",", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    return sanitized.strip(" ,")


def _normalize_generation_prompt(prompt: str, area_type: str) -> str:
    prompt_text = _sanitize_generation_prompt(prompt)
    color_instruction = _area_color_instruction(area_type)
    if not prompt_text:
        return color_instruction
    return f"{prompt_text}, {color_instruction}"


def _normalize_negative_prompt(negative_prompt: str) -> str:
    normalized = (negative_prompt or DEFAULT_NEGATIVE_PROMPT).strip()
    replacements = {
        "non-green colors": "unmapped colors",
        "non green colors": "unmapped colors",
        "non-blue colors": "unmapped colors",
        "non blue colors": "unmapped colors",
        "non-red colors": "unmapped colors",
        "non red colors": "unmapped colors",
        "non-yellow colors": "unmapped colors",
        "non yellow colors": "unmapped colors",
    }
    for old_value, new_value in replacements.items():
        normalized = re.sub(re.escape(old_value), new_value, normalized, flags=re.IGNORECASE)

    existing = normalized.lower()
    missing_terms = [term for term in ENFORCED_NEGATIVE_TERMS if term not in existing]
    if missing_terms:
        normalized = f"{normalized}, {', '.join(missing_terms)}"

    normalized = re.sub(r"\s+,", ",", normalized)
    normalized = re.sub(r",\s*,+", ",", normalized)
    return normalized.strip(" ,")


def get_chat_response(prompt: str) -> str:
    try:
        raw_response = _call_qwen(prompt)
        payload = _extract_json_block(raw_response)
        if payload.get("intent") == "chat" and payload.get("reply"):
            return str(payload["reply"]).strip()
        return raw_response.strip()
    except Exception as exc:
        _log(f"Chat fallback triggered: {exc}")
        return f"当前大模型暂时不可用，但我已经收到你的消息：{prompt}。错误信息：{exc}"


def route_user_message(prompt: str) -> dict:
    _log("Routing user message")
    try:
        payload = _extract_json_block(_call_qwen(prompt))
        _log(f"Parsed payload: {json.dumps(payload, ensure_ascii=False)}")
    except Exception as exc:
        _log(f"Router failed, entering fallback path: {exc}")
        if _looks_like_generation(prompt):
            payload = {
                "intent": "generate",
                "prompt": (
                    "top view urban planning masterplan, clean zoning composition, "
                    "white background, building blocks only, suitable for 2D to 3D conversion, "
                    f"{prompt}"
                ),
                "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
                "area_type": "residential",
                "model_key": "residential",
                "title": "规划生成任务",
            }
            _log(f"Fallback generation payload: {json.dumps(payload, ensure_ascii=False)}")
        else:
            return {
                "intent": "chat",
                "reply": get_chat_response(prompt),
            }

    intent = str(payload.get("intent", "")).strip().lower()
    if intent == "chat":
        return {
            "intent": "chat",
            "reply": str(payload.get("reply") or "你好，我可以帮你生成城市规划图和 3D 预览。").strip(),
        }

    area_type = _normalize_area_type(str(payload.get("area_type", "residential")))
    area_meta = AREA_TYPE_MAP[area_type]
    render_preset = dict(DEFAULT_RENDER_PRESET)
    render_preset.update(payload.get("render_preset") or {})

    result = {
        "intent": "generate",
        "title": str(payload.get("title") or f"{area_meta['label']}生成任务").strip(),
        "prompt": _normalize_generation_prompt(str(payload.get("prompt") or ""), area_type),
        "negative_prompt": _normalize_negative_prompt(
            str(payload.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT)
        ),
        "area_type": area_type,
        "area_label": area_meta["label"],
        "area_flag": int(payload.get("area_flag") or area_meta["flag"]),
        "model_key": _normalize_area_type(str(payload.get("model_key") or area_type)),
        "global_palette": payload.get("global_palette") or _default_palette(area_type),
        "render_preset": render_preset,
    }
    _log(f"Final routed payload: {json.dumps(result, ensure_ascii=False)}")
    return result
