from __future__ import annotations

import re

from .constants import (
    AREA_ALIASES,
    AREA_META,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_PALETTES,
    DEFAULT_RENDER_PRESET,
    ENFORCED_NEGATIVE_TERMS,
    PROMPT_NOISE_PATTERNS,
)


def normalize_area_type(area_type: str) -> str:
    raw = (area_type or "").strip().lower()
    normalized = AREA_ALIASES.get(raw, raw)
    return normalized if normalized in AREA_META else "residential"


def default_palette(area_type: str) -> dict[str, str]:
    return DEFAULT_PALETTES[area_type]


def area_color_instruction(area_type: str) -> str:
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


def sanitize_generation_prompt(prompt: str) -> str:
    sanitized = prompt or ""
    for pattern in PROMPT_NOISE_PATTERNS:
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+,", ",", sanitized)
    sanitized = re.sub(r",\s*,+", ",", sanitized)
    sanitized = re.sub(r"\b(and|with)\s*,", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r",\s*(and|with)\s*,", ",", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    return sanitized.strip(" ,")


def normalize_generation_prompt(prompt: str, area_type: str) -> str:
    prompt_text = sanitize_generation_prompt(prompt)
    color_instruction = area_color_instruction(area_type)
    if not prompt_text:
        return color_instruction
    return f"{prompt_text}, {color_instruction}"


def normalize_negative_prompt(negative_prompt: str) -> str:
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


def normalize_render_preset(raw_preset: dict | None) -> dict:
    preset = dict(DEFAULT_RENDER_PRESET)
    preset.update(raw_preset or {})
    return preset
