"""基于规划色块的轻量日照/通风代理分析。

这里输出的是早期方案对比指标，并非带地理位置和气象边界条件的物理级日照或 CFD 结果。
"""

import json
import math
from pathlib import Path

import cv2
import numpy as np


MAX_HEIGHT = 80.0
VALID_WIND_DIRECTIONS = ("north", "east", "south", "west")
BUILDING_COLOR_RANGES = {
    "red": [
        (np.array([0, 40, 40]), np.array([12, 255, 255])),
        (np.array([168, 40, 40]), np.array([180, 255, 255])),
    ],
    "yellow": [
        (np.array([15, 40, 40]), np.array([38, 255, 255])),
    ],
    "green": [
        (np.array([35, 40, 40]), np.array([90, 255, 255])),
    ],
    "blue": [
        (np.array([90, 40, 40]), np.array([135, 255, 255])),
    ],
}
COLOR_ALIASES = {
    "residential": "green",
    "green": "green",
    "industrial": "yellow",
    "yellow": "yellow",
    "commercial": "blue",
    "blue": "blue",
    "public": "red",
    "red": "red",
    "auto": "auto",
    "all": "auto",
}
SEASON_SUN_ALTITUDES = {
    "winter": 22.0,
    "spring": 44.0,
    "summer": 68.0,
    "autumn": 38.0,
    "custom": 45.0,
}


def _load_image(image_path: str) -> tuple[np.ndarray, np.ndarray]:
    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Unable to read image: {image_path}")

    if len(img.shape) == 3 and img.shape[-1] == 4:
        alpha_channel = img[:, :, 3] / 255.0
        rgb_channels = img[:, :, :3]
        white_background = np.ones_like(rgb_channels, dtype=np.uint8) * 255
        img_bgr = (
            rgb_channels * alpha_channel[:, :, np.newaxis]
            + white_background * (1 - alpha_channel[:, :, np.newaxis])
        ).astype(np.uint8)
    else:
        img_bgr = img

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return img_bgr, img_rgb


def _normalize_target_colors(target_color: str | None = None) -> list[str]:
    normalized = COLOR_ALIASES.get((target_color or "auto").strip().lower(), "auto")
    if normalized == "auto":
        return list(BUILDING_COLOR_RANGES.keys())
    return [normalized]


def _build_colored_building_mask(hsv_image: np.ndarray, target_color: str | None = None) -> np.ndarray:
    building_mask = np.zeros(hsv_image.shape[:2], dtype=np.uint8)
    for color_name in _normalize_target_colors(target_color):
        for lower_bound, upper_bound in BUILDING_COLOR_RANGES[color_name]:
            building_mask = cv2.bitwise_or(
                building_mask,
                cv2.inRange(hsv_image, lower_bound, upper_bound),
            )
    return building_mask


def _is_line_or_border_artifact(contour: np.ndarray, image_width: int, image_height: int) -> bool:
    x, y, width, height = cv2.boundingRect(contour)
    touches_border = (
        x <= 1
        or y <= 1
        or x + width >= image_width - 1
        or y + height >= image_height - 1
    )
    if touches_border and width > image_width * 0.75 and height > image_height * 0.75:
        return True

    short_side = min(width, height)
    long_side = max(width, height)
    return short_side <= 12 and long_side / max(short_side, 1) >= 3


def _extract_height_map(
    img_bgr: np.ndarray,
    target_color: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    v_smooth = cv2.medianBlur(v_channel, 5)

    # 与 2D→3D 使用同一颜色约定，保证分析对象和预览中的建筑轮廓一致。
    building_mask = _build_colored_building_mask(hsv, target_color)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    cleaned_mask = cv2.morphologyEx(building_mask, cv2.MORPH_OPEN, kernel, iterations=2)
    cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height_map = np.zeros_like(v_smooth, dtype=np.float32)
    usable_building_mask = np.zeros_like(cleaned_mask, dtype=np.uint8)

    for cnt in contours:
        if cv2.contourArea(cnt) < 50:
            continue
        if _is_line_or_border_artifact(cnt, cleaned_mask.shape[1], cleaned_mask.shape[0]):
            continue

        single_block_mask = np.zeros_like(cleaned_mask)
        cv2.drawContours(single_block_mask, [cnt], -1, 255, thickness=cv2.FILLED)
        block_pixels = v_smooth[single_block_mask == 255]
        if len(block_pixels) == 0:
            continue

        # 训练约定为“深色高层、浅色低层”，因此亮度与代理高度呈反比。
        median_v = np.median(block_pixels)
        block_height = ((255 - median_v) / 255.0) * MAX_HEIGHT
        height_map[single_block_mask == 255] = block_height
        usable_building_mask[single_block_mask == 255] = 255

    return height_map, usable_building_mask > 0


def _normalize_map(value_map: np.ndarray, valid_mask: np.ndarray | None = None) -> np.ndarray:
    normalized = value_map.astype(np.float32).copy()
    if valid_mask is not None and np.any(valid_mask):
        selected = normalized[valid_mask]
    else:
        selected = normalized

    max_value = float(np.max(selected)) if selected.size else 0.0
    min_value = float(np.min(selected)) if selected.size else 0.0
    if max_value - min_value < 1e-6:
        return np.zeros_like(normalized, dtype=np.float32)

    normalized = (normalized - min_value) / (max_value - min_value)
    return np.clip(normalized, 0.0, 1.0)


def _make_overlay(base_rgb: np.ndarray, metric_map: np.ndarray, building_mask: np.ndarray, colormap: int) -> np.ndarray:
    color_map = cv2.applyColorMap((metric_map * 255).astype(np.uint8), colormap)
    color_map = cv2.cvtColor(color_map, cv2.COLOR_BGR2RGB)
    overlay = cv2.addWeighted(base_rgb, 0.42, color_map, 0.58, 0)

    result = overlay.copy()
    if np.any(building_mask):
        highlighted = cv2.addWeighted(
            base_rgb[building_mask],
            0.72,
            color_map[building_mask],
            0.28,
            0,
        )
        if highlighted is not None:
            result[building_mask] = highlighted
    return result


def _resolve_sun_inputs(season_profile: str, sun_altitude_deg: float | None) -> tuple[str, float]:
    season = (season_profile or "spring").strip().lower()
    if season not in SEASON_SUN_ALTITUDES:
        season = "spring"

    if sun_altitude_deg is None:
        altitude = SEASON_SUN_ALTITUDES[season]
    else:
        altitude = float(sun_altitude_deg)

    altitude = float(np.clip(altitude, 5.0, 85.0))
    return season, altitude


def _simulate_sunlight(
    height_map: np.ndarray,
    building_mask: np.ndarray,
    *,
    season_profile: str = "spring",
    sun_altitude_deg: float | None = None,
) -> tuple[np.ndarray, dict, dict]:
    resolved_season, resolved_altitude = _resolve_sun_inputs(season_profile, sun_altitude_deg)
    altitude_radians = math.radians(resolved_altitude)
    shadow_length_factor = np.clip(1.0 / math.tan(altitude_radians), 0.22, 2.8)

    # 用早/中/晚三组简化投影累计阴影；太阳高度角只控制阴影长度。
    directions = [
        {"name": "morning", "dx": 1, "dy": 1, "scale": 0.70 * shadow_length_factor},
        {"name": "noon", "dx": 0, "dy": 1, "scale": 0.38 * shadow_length_factor},
        {"name": "afternoon", "dx": -1, "dy": 1, "scale": 0.66 * shadow_length_factor},
    ]

    open_mask = ~building_mask
    shadow_accumulator = np.zeros_like(height_map, dtype=np.float32)

    samples = np.argwhere(building_mask)
    for direction in directions:
        shadow_map = np.zeros_like(height_map, dtype=np.float32)
        for y, x in samples:
            steps = max(1, int(height_map[y, x] * direction["scale"] / 3.5))
            for step in range(1, steps + 1):
                target_x = x + direction["dx"] * step
                target_y = y + direction["dy"] * step
                if target_x < 0 or target_x >= height_map.shape[1] or target_y < 0 or target_y >= height_map.shape[0]:
                    break
                decay = 1.0 - (step / (steps + 1))
                shadow_map[target_y, target_x] = max(shadow_map[target_y, target_x], decay)

        shadow_map[building_mask] = 0.0
        shadow_accumulator += shadow_map

    avg_shadow = shadow_accumulator / len(directions)
    sunlight_map = 1.0 - avg_shadow
    sunlight_map[building_mask] = 0.72 + 0.28 * _normalize_map(height_map, building_mask)[building_mask]
    sunlight_map = np.clip(sunlight_map, 0.0, 1.0)

    open_values = sunlight_map[open_mask]
    metrics = {
        "mean_exposure": round(float(np.mean(open_values)) if open_values.size else 0.0, 4),
        "high_exposure_ratio": round(float(np.mean(open_values >= 0.7)) if open_values.size else 0.0, 4),
        "low_exposure_ratio": round(float(np.mean(open_values <= 0.35)) if open_values.size else 0.0, 4),
        "shadow_coverage": round(float(np.mean(avg_shadow[open_mask] >= 0.45)) if open_values.size else 0.0, 4),
    }
    inputs = {
        "season_profile": resolved_season,
        "sun_altitude_deg": round(resolved_altitude, 1),
    }
    return sunlight_map, metrics, inputs


def _rotate_to_wind_frame(array: np.ndarray, direction: str) -> np.ndarray:
    rotations = {
        "west": None,
        "north": cv2.ROTATE_90_CLOCKWISE,
        "east": cv2.ROTATE_180,
        "south": cv2.ROTATE_90_COUNTERCLOCKWISE,
    }
    rotation = rotations.get(direction, None)
    if rotation is None:
        return array.copy()
    return cv2.rotate(array, rotation)


def _rotate_from_wind_frame(array: np.ndarray, direction: str) -> np.ndarray:
    rotations = {
        "west": None,
        "north": cv2.ROTATE_90_COUNTERCLOCKWISE,
        "east": cv2.ROTATE_180,
        "south": cv2.ROTATE_90_CLOCKWISE,
    }
    rotation = rotations.get(direction, None)
    if rotation is None:
        return array.copy()
    return cv2.rotate(array, rotation)


def _normalize_wind_directions(primary_wind_direction: str, wind_directions: list[str] | None) -> tuple[str, list[str]]:
    primary = (primary_wind_direction or "west").strip().lower()
    if primary not in VALID_WIND_DIRECTIONS:
        primary = "west"

    candidates = wind_directions or [primary]
    normalized: list[str] = []
    for direction in candidates:
        value = str(direction).strip().lower()
        if value in VALID_WIND_DIRECTIONS and value not in normalized:
            normalized.append(value)

    if primary not in normalized:
        normalized.insert(0, primary)
    return primary, normalized


def _simulate_wind(
    building_mask: np.ndarray,
    height_map: np.ndarray,
    *,
    direction: str = "west",
) -> tuple[np.ndarray, dict]:
    # 先把任意来风旋转为统一的“从左向右”，只维护一套传播/尾流算法，再旋回原方向。
    rotated_mask = _rotate_to_wind_frame(building_mask.astype(np.uint8), direction) > 0
    rotated_height = _rotate_to_wind_frame(height_map, direction)

    rows, cols = rotated_mask.shape
    flow = np.zeros((rows, cols), dtype=np.float32)

    for y in range(rows):
        if not rotated_mask[y, 0]:
            flow[y, 0] = 1.0

    # 逐列传播近似风速，建筑像素为障碍，邻近行提供少量横向补流。
    for x in range(1, cols):
        for y in range(rows):
            if rotated_mask[y, x]:
                flow[y, x] = 0.0
                continue

            carry = flow[y, x - 1]
            upper = flow[y - 1, x - 1] if y > 0 else carry
            lower = flow[y + 1, x - 1] if y < rows - 1 else carry
            lateral = 0.0
            if y > 0:
                lateral += flow[y - 1, x]
            if y < rows - 1:
                lateral += flow[y + 1, x]

            flow[y, x] = 0.62 * carry + 0.16 * upper + 0.16 * lower + 0.06 * lateral

    # 建筑越高，背风侧的衰减带越长；这是二维尾流代理，不等同于 CFD。
    building_indices = np.argwhere(rotated_mask)
    for y, x in building_indices:
        wake_distance = max(3, int(rotated_height[y, x] / 5))
        for offset in range(1, wake_distance + 1):
            target_x = x + offset
            if target_x >= cols:
                break

            band = max(1, offset // 3)
            attenuation = max(0.1, 1.0 - offset / (wake_distance + 1))
            y0 = max(0, y - band)
            y1 = min(rows, y + band + 1)
            flow[y0:y1, target_x] *= 1.0 - 0.72 * attenuation

    for _ in range(6):
        flow = cv2.GaussianBlur(flow, (0, 0), sigmaX=1.1, sigmaY=1.1)
        flow[rotated_mask] = 0.0

    flow = _normalize_map(flow, ~rotated_mask)
    flow = _rotate_from_wind_frame(flow, direction)

    open_mask = ~building_mask
    open_values = flow[open_mask]
    metrics = {
        "mean_speed": round(float(np.mean(open_values)) if open_values.size else 0.0, 4),
        "high_ventilation_ratio": round(float(np.mean(open_values >= 0.68)) if open_values.size else 0.0, 4),
        "stagnation_ratio": round(float(np.mean(open_values <= 0.22)) if open_values.size else 0.0, 4),
        "wake_impact_ratio": round(float(np.mean((open_values > 0.0) & (open_values <= 0.38))) if open_values.size else 0.0, 4),
    }
    return flow, metrics


def _save_image(path: Path, image_rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))


def _direction_label(direction: str) -> str:
    return {
        "north": "北风",
        "east": "东风",
        "south": "南风",
        "west": "西风",
    }.get(direction, direction)


def run_spatial_analysis(
    image_path: str,
    output_dir: str,
    *,
    target_color: str | None = None,
    primary_wind_direction: str = "west",
    wind_directions: list[str] | None = None,
    season_profile: str = "spring",
    sun_altitude_deg: float | None = None,
) -> dict:
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    img_bgr, img_rgb = _load_image(image_path)
    height_map, building_mask = _extract_height_map(img_bgr, target_color)

    # 同一份高度图分别进入日照和多风向通风计算，确保各项指标可以相互对照。
    sunlight_map, sunlight_metrics, sunlight_inputs = _simulate_sunlight(
        height_map,
        building_mask,
        season_profile=season_profile,
        sun_altitude_deg=sun_altitude_deg,
    )

    primary_direction, direction_batch = _normalize_wind_directions(primary_wind_direction, wind_directions)
    wind_batch: list[dict] = []
    primary_wind_map = None
    primary_wind_metrics = None

    for direction in direction_batch:
        wind_map, wind_metrics = _simulate_wind(
            building_mask,
            height_map,
            direction=direction,
        )
        wind_batch.append(
            {
                "direction": direction,
                "label": _direction_label(direction),
                "metrics": wind_metrics,
            }
        )
        if direction == primary_direction:
            primary_wind_map = wind_map
            primary_wind_metrics = wind_metrics

    if primary_wind_map is None or primary_wind_metrics is None:
        primary_wind_map, primary_wind_metrics = _simulate_wind(building_mask, height_map, direction=primary_direction)

    sunlight_overlay = _make_overlay(img_rgb, sunlight_map, building_mask, cv2.COLORMAP_INFERNO)
    wind_overlay = _make_overlay(img_rgb, primary_wind_map, building_mask, cv2.COLORMAP_TURBO)

    sunlight_path = base_dir / "sunlight_heatmap.png"
    wind_path = base_dir / "ventilation_heatmap.png"
    _save_image(sunlight_path, sunlight_overlay)
    _save_image(wind_path, wind_overlay)

    # 排名用于早期方案选择；mean_speed 是 0–1 归一化代理量，不是 m/s 实测风速。
    ranked_winds = sorted(
        wind_batch,
        key=lambda item: item["metrics"]["mean_speed"],
        reverse=True,
    )
    best_wind = ranked_winds[0] if ranked_winds else None
    worst_wind = ranked_winds[-1] if ranked_winds else None

    summary = {
        "analysis_type": "proxy-spatial-analysis",
        "assumptions": [
            "Lighting uses simplified multi-direction shadow casting based on inferred building heights.",
            "Sun altitude and season alter shadow length rather than running a physically exact solar engine.",
            "Ventilation uses a 2D directional flow proxy and wake attenuation, not full CFD.",
            "Wind rose values are aggregated from batch directional evaluations for early-stage comparison.",
        ],
        "warnings": [],
        "inputs": {
            "image_path": image_path,
            "pixel_width": int(img_rgb.shape[1]),
            "pixel_height": int(img_rgb.shape[0]),
            "building_coverage_ratio": round(float(np.mean(building_mask)), 4),
            "season_profile": sunlight_inputs["season_profile"],
            "sun_altitude_deg": sunlight_inputs["sun_altitude_deg"],
            "primary_wind_direction": primary_direction,
            "primary_wind_label": _direction_label(primary_direction),
            "wind_directions": direction_batch,
        },
        "sunlight": {
            "label": "Sunlight Exposure",
            "image_name": sunlight_path.name,
            "metrics": sunlight_metrics,
        },
        "wind": {
            "label": "Ventilation Flow",
            "image_name": wind_path.name,
            "metrics": primary_wind_metrics,
        },
        "wind_rose": [
            {
                "direction": item["direction"],
                "label": item["label"],
                "mean_speed": item["metrics"]["mean_speed"],
                "high_ventilation_ratio": item["metrics"]["high_ventilation_ratio"],
                "stagnation_ratio": item["metrics"]["stagnation_ratio"],
                "wake_impact_ratio": item["metrics"]["wake_impact_ratio"],
            }
            for item in wind_batch
        ],
        "wind_comparison": {
            "best_direction": best_wind["direction"] if best_wind else None,
            "best_label": best_wind["label"] if best_wind else None,
            "best_mean_speed": best_wind["metrics"]["mean_speed"] if best_wind else None,
            "worst_direction": worst_wind["direction"] if worst_wind else None,
            "worst_label": worst_wind["label"] if worst_wind else None,
            "worst_mean_speed": worst_wind["metrics"]["mean_speed"] if worst_wind else None,
        },
    }

    if not np.any(building_mask):
        summary["warnings"].append(
            "No usable building contours were detected in the generated 2D image. "
            "Analysis results were produced in fallback mode and may be uninformative."
        )

    summary_path = base_dir / "analysis.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
