"""把 SDXL 输出的规划色块图转换成可交互 Plotly 3D HTML。"""

import os
import sys
from datetime import datetime

import cv2
import numpy as np
import plotly.graph_objects as go


def _log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [2D23D] {message}", flush=True)


BUILDING_COLOR_RANGES = {
    # OpenCV HSV 的红色跨越 0/180，因此需要两段阈值；其余颜色只需一段。
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


def _normalize_target_colors(target_color: str | None = None) -> list[str]:
    aliases = {
        "residential": "green",
        "green": "green",
        "commercial": "blue",
        "blue": "blue",
        "public": "red",
        "red": "red",
        "industrial": "yellow",
        "yellow": "yellow",
        "auto": "auto",
        "all": "auto",
    }
    normalized = aliases.get((target_color or "auto").strip().lower(), "auto")
    if normalized == "auto":
        return list(BUILDING_COLOR_RANGES.keys())
    return [normalized]


def _build_colored_building_mask(
    hsv_image: np.ndarray,
    target_color: str | None = None,
) -> np.ndarray:
    building_mask = np.zeros(hsv_image.shape[:2], dtype=np.uint8)
    target_colors = _normalize_target_colors(target_color)
    _log(f"Target building colors: {', '.join(target_colors)}")

    for color_name in target_colors:
        ranges = BUILDING_COLOR_RANGES[color_name]
        color_mask = np.zeros_like(building_mask)
        for lower_bound, upper_bound in ranges:
            color_mask = cv2.bitwise_or(
                color_mask,
                cv2.inRange(hsv_image, lower_bound, upper_bound),
            )

        pixel_count = int(np.count_nonzero(color_mask))
        _log(f"{color_name.title()} mask pixels: {pixel_count}")
        building_mask = cv2.bitwise_or(building_mask, color_mask)

    _log(f"Combined colored building mask pixels: {int(np.count_nonzero(building_mask))}")
    return building_mask


def _is_line_or_border_artifact(contour: np.ndarray, image_width: int, image_height: int) -> bool:
    x, y, width, height = cv2.boundingRect(contour)
    area = cv2.contourArea(contour)
    bbox_area = width * height
    if bbox_area == 0:
        return True

    touches_border = (
        x <= 1
        or y <= 1
        or x + width >= image_width - 1
        or y + height >= image_height - 1
    )
    covers_most_canvas = width > image_width * 0.75 and height > image_height * 0.75
    if touches_border and covers_most_canvas:
        return True

    short_side = min(width, height)
    long_side = max(width, height)
    if short_side <= 12 and long_side / max(short_side, 1) >= 3:
        return True

    return False


def generate_3d_html_preview(image_path, output_html_path, target_color: str | None = None):
    _log(f"Input image path: {image_path}")
    _log(f"Output html path: {output_html_path}")

    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Unable to read image: {image_path}")
    _log(f"Loaded image shape: {img.shape}")

    if len(img.shape) == 3 and img.shape[-1] == 4:
        _log("Detected alpha channel, compositing onto white background")
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
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    v_smooth = cv2.medianBlur(v_channel, 5)

    height_map = np.zeros_like(v_channel, dtype=np.float32)
    max_height = 80

    # 只提取当前分区允许的建筑色，避免背景或模型生成的杂色被误抬升为建筑。
    building_mask = _build_colored_building_mask(hsv, target_color)

    # 开运算去除孤立噪点；后续轮廓过滤再排除边框和细长线条。
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    cleaned_mask = cv2.morphologyEx(building_mask, cv2.MORPH_OPEN, kernel, iterations=2)
    contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    _log(f"Detected contours: {len(contours)}")

    skipped_artifacts = 0
    kept_contours = 0
    for contour in contours:
        if cv2.contourArea(contour) < 50:
            continue
        if _is_line_or_border_artifact(contour, cleaned_mask.shape[1], cleaned_mask.shape[0]):
            skipped_artifacts += 1
            continue
        kept_contours += 1

        single_block_mask = np.zeros_like(cleaned_mask)
        cv2.drawContours(single_block_mask, [contour], -1, 255, thickness=cv2.FILLED)
        block_pixels = v_smooth[single_block_mask == 255]

        if len(block_pixels) == 0:
            continue

        # 同色系中深色代表高层、浅色代表低层，按 HSV 亮度反推相对高度。
        median_v = np.median(block_pixels)
        block_height = ((255 - median_v) / 255.0) * max_height
        height_map[single_block_mask == 255] = block_height

    _log(f"Usable building contours: {kept_contours}")
    _log(f"Skipped line/border artifacts: {skipped_artifacts}")

    # 网格降采样到 25%，控制 Mesh3d 顶点数和最终 HTML 体积。
    scale_percent = 25
    width = max(1, int(height_map.shape[1] * scale_percent / 100))
    height = max(1, int(height_map.shape[0] * scale_percent / 100))
    dim = (width, height)
    _log(f"Resized mesh dimensions: {width} x {height}")

    resized_height = cv2.resize(height_map, dim, interpolation=cv2.INTER_NEAREST)
    resized_rgb = cv2.resize(img_rgb, dim, interpolation=cv2.INTER_NEAREST)

    bg_mask = resized_height == 0
    resized_rgb[bg_mask] = [255, 255, 255]

    x = np.arange(width)
    y = np.arange(height)
    x_grid, y_grid = np.meshgrid(x, y)

    x_flat = x_grid.flatten()
    y_flat = y_grid.flatten()
    z_flat = resized_height.flatten()

    flat_rgb = resized_rgb.reshape(-1, 3)
    vertex_colors = [f"rgb({r},{g},{b})" for r, g, b in flat_rgb]

    c, r = np.meshgrid(np.arange(width - 1), np.arange(height - 1))
    c = c.flatten()
    r = r.flatten()

    p1 = r * width + c
    p2 = r * width + (c + 1)
    p3 = (r + 1) * width + c
    p4 = (r + 1) * width + (c + 1)

    # 每个网格单元拆成两个三角面，i/j/k 是 Plotly Mesh3d 的顶点索引。
    i_idx = np.concatenate([p1, p2])
    j_idx = np.concatenate([p3, p3])
    k_idx = np.concatenate([p2, p4])

    fig = go.Figure(
        data=[
            go.Mesh3d(
                x=x_flat,
                y=y_flat,
                z=z_flat,
                i=i_idx,
                j=j_idx,
                k=k_idx,
                vertexcolor=vertex_colors,
                flatshading=True,
                hoverinfo="none",
            )
        ]
    )

    fig.update_layout(
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectratio=dict(x=1, y=height / width, z=0.4),
            camera=dict(eye=dict(x=1.2, y=1.2, z=0.8)),
            bgcolor="white",
        ),
        margin=dict(l=0, r=0, b=0, t=0),
        paper_bgcolor="white",
    )

    os.makedirs(os.path.dirname(output_html_path), exist_ok=True)
    fig.write_html(output_html_path, auto_open=False)
    _log(f"HTML exported: {output_html_path}")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        color_arg = sys.argv[3] if len(sys.argv) > 3 else None
        generate_3d_html_preview(sys.argv[1], sys.argv[2], color_arg)
    else:
        print("Usage: python 2D23D.py <input_image> <output_html> [green|blue|red|yellow|auto]")
