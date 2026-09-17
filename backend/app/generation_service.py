from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .constants import BUILDING_COLOR_BY_AREA, DEFAULT_PALETTES
from .logger import log_step
from .postprocess_service import postprocess_generated_image
from .settings import IMAGES_DIR, OUTPUTS_DIR, SCRIPTS_DIR, is_test_mode


def generate_assets(request_id: str, generation_payload: dict[str, Any]) -> tuple[str, str]:
    """串联 2D 生图与 2D→3D 转换，返回落盘后的绝对路径。"""
    image_path = str((IMAGES_DIR / f"{request_id}.png").resolve())
    html_path = str((OUTPUTS_DIR / f"{request_id}.html").resolve())
    payload_text = json.dumps(generation_payload, ensure_ascii=False)

    convert_script = str((SCRIPTS_DIR / "2D23D.py").resolve())
    target_color = BUILDING_COLOR_BY_AREA.get(
        str(generation_payload.get("area_type") or "").lower(),
        "auto",
    )

    log_step("PIPELINE", f"Request {request_id}: start generation")
    log_step("PIPELINE", f"Image output path: {image_path}")
    log_step("PIPELINE", f"HTML output path: {html_path}")
    log_step("PIPELINE", f"Generation payload: {payload_text}")
    log_step("PIPELINE", f"2D to 3D target color: {target_color}")

    # 测试模式保留真实的转换和分析链路，只替换最耗资源且依赖外部服务的生图阶段。
    if is_test_mode():
        log_step("PIPELINE", "CITY_PLANNER_TEST_MODE enabled; using mock image generation")
        _write_mock_plan_image(Path(image_path), generation_payload)
    else:
        llm_script = str((SCRIPTS_DIR / "llmpicture.py").resolve())
        # SDXL 放在子进程执行：失败时能完整捕获日志，结束后操作系统也会回收模型显存。
        _run_subprocess("llmpicture.py", [sys.executable, llm_script, payload_text, image_path])

    # Postprocess is a CPU-only module shared with the standalone image CLI.
    # The original bytes, masks, regions and unknown heights are kept in a sidecar bundle.
    postprocess_generated_image(image_path)
    _run_subprocess("2D23D.py", [sys.executable, convert_script, image_path, html_path, target_color])

    return image_path, html_path


def _write_mock_plan_image(image_path: Path, generation_payload: dict[str, Any]) -> None:
    from PIL import Image, ImageDraw

    area_type = str(generation_payload.get("area_type") or "residential").lower()
    palette = DEFAULT_PALETTES.get(area_type, DEFAULT_PALETTES["residential"])
    render_preset = generation_payload.get("render_preset") or {}
    width = max(256, min(int(render_preset.get("width", 512)), 512))
    height = max(256, min(int(render_preset.get("height", 512)), 512))

    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    primary = str(palette["primary"])
    secondary = str(palette["secondary"])

    blocks = [
        (0.08, 0.10, 0.24, 0.28, primary),
        (0.30, 0.08, 0.46, 0.22, secondary),
        (0.56, 0.10, 0.78, 0.28, primary),
        (0.14, 0.38, 0.34, 0.58, secondary),
        (0.43, 0.34, 0.60, 0.54, primary),
        (0.68, 0.40, 0.88, 0.62, secondary),
        (0.10, 0.72, 0.28, 0.88, primary),
        (0.38, 0.68, 0.54, 0.84, secondary),
        (0.64, 0.72, 0.86, 0.90, primary),
    ]

    for left, top, right, bottom, color in blocks:
        draw.rounded_rectangle(
            (
                int(width * left),
                int(height * top),
                int(width * right),
                int(height * bottom),
            ),
            radius=max(2, width // 80),
            fill=color,
        )

    image_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(image_path)
    log_step("PIPELINE", f"Mock image saved: {image_path}")


def _run_subprocess(script_name: str, command: list[str]) -> None:
    """以当前虚拟环境运行脚本，并把子进程输出汇入统一后端日志。"""
    log_step("SUBPROCESS", f"Start {script_name}")
    log_step("SUBPROCESS", "Command: " + " ".join(f'"{part}"' for part in command))
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env,
        timeout=1800,
    )
    _relay_output(script_name, result.stdout, result.stderr)
    if result.returncode != 0:
        log_step("ERROR", f"{script_name} failed with exit code {result.returncode}")
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    log_step("SUBPROCESS", f"Finish {script_name}")


def _relay_output(script_name: str, stdout: str | None, stderr: str | None) -> None:
    if stdout:
        for line in stdout.splitlines():
            log_step(script_name, line)
    if stderr:
        for line in stderr.splitlines():
            log_step(f"{script_name}:stderr", line)
