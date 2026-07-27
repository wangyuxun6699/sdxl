from __future__ import annotations


AREA_META = {
    "residential": {"label": "居住区", "flag": 1, "color": "green"},
    "industrial": {"label": "工业区", "flag": 2, "color": "yellow"},
    "commercial": {"label": "商业区", "flag": 3, "color": "blue"},
    "public": {"label": "公共区", "flag": 4, "color": "red"},
}
AREA_LABELS = {key: value["label"] for key, value in AREA_META.items()}
BUILDING_COLOR_BY_AREA = {key: value["color"] for key, value in AREA_META.items()}
VALID_WIND_DIRECTIONS = ("north", "east", "south", "west")

DEFAULT_RENDER_PRESET = {
    "width": 1024,
    "height": 1024,
    "guidance_scale": 7.0,
    "num_inference_steps": 30,
    "num_images_per_prompt": 1,
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
    "居住",
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

AREA_ALIASES = {
    "住宅": "residential",
    "住宅区": "residential",
    "居住": "residential",
    "居住区": "residential",
    "residential_area": "residential",
    "工业": "industrial",
    "工业区": "industrial",
    "industrial_area": "industrial",
    "商业": "commercial",
    "商业区": "commercial",
    "commercial_area": "commercial",
    "公共": "public",
    "公共区": "public",
    "公共服务": "public",
    "public_area": "public",
}

DEFAULT_PALETTES = {
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
