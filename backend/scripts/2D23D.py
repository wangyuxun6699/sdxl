"""把 SDXL 输出的规划色块图转换成可交互 Plotly 3D HTML。"""

import os
import sys
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.postprocessing.scene import load_scene_fields

import cv2
import numpy as np
import plotly.graph_objects as go


def _log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [2D23D] {message}", flush=True)


def generate_3d_html_preview(image_path, output_html_path, target_color: str | None = None):
    # target_color is retained only for old callers; cleanup no longer uses hue bins.
    _log(f"Input image path: {image_path}")
    scene = load_scene_fields(image_path)
    img_rgb = scene.rgb
    height_map = scene.proxy_height
    for warning in scene.metadata["warnings"]:
        _log(warning)

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

    label = ("形态示意：未映射部分使用统一示意高度" if scene.metadata["unknown_height_pixels"]
             else "形态示意：采用配置中的代表高度；平面坐标为像素")
    fig.add_annotation(text=label, x=0.5, y=0.02, xref="paper", yref="paper", showarrow=False,
                       font=dict(size=12, color="#52525b"), bgcolor="rgba(255,255,255,0.85)")
    Path(output_html_path).parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(output_html_path, auto_open=False)
    _log(f"HTML exported: {output_html_path}")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        color_arg = sys.argv[3] if len(sys.argv) > 3 else None
        generate_3d_html_preview(sys.argv[1], sys.argv[2], color_arg)
    else:
        print("Usage: python 2D23D.py <input_image> <output_html> [green|blue|red|yellow|auto]")
