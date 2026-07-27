"""本地 SDXL 单文件模型 + 分区 LoRA 的推理入口。

该脚本由 FastAPI 主进程以子进程方式调用；模型和配置均按离线模式读取，
以避免一次请求在运行期间意外下载大文件。
"""

from __future__ import annotations

import gc
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# Hugging Face 缓存和显存分配策略必须在导入 diffusers/transformers 前设置才会生效。
HF_CACHE_DIR = (
    os.getenv("HF_HUB_CACHE")
    or os.getenv("HUGGINGFACE_HUB_CACHE")
    or str(Path.home() / ".cache" / "huggingface" / "hub")
)
os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")
os.environ.setdefault("HF_HUB_CACHE", HF_CACHE_DIR)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", HF_CACHE_DIR)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

import torch
import diffusers.loaders.single_file_utils
from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
from huggingface_hub import snapshot_download


def _dummy_legacy_safety_checker(*args, **kwargs):
    return (None, None)


# 单文件加载器的旧兼容路径可能尝试下载 safety-checker；本项目使用离线模型并显式禁用它。
diffusers.loaders.single_file_utils._legacy_load_safety_checker = _dummy_legacy_safety_checker

SDXL_BASE_MODEL_PATH = os.getenv("SDXL_BASE_MODEL_PATH", "").strip().strip('"')
SDXL_CONFIG_REPO = os.getenv("SDXL_CONFIG_REPO", "stabilityai/stable-diffusion-xl-base-1.0")
SDXL_DIFFUSERS_CONFIG_PATH = os.getenv("SDXL_DIFFUSERS_CONFIG_PATH", "").strip().strip('"')
# LLM 路由得到 model_key 后，在这里选择同一基础模型对应的分区 LoRA。
MODEL_LIBRARY = {
    "residential": {
        "label": "居住区",
        "lora_model_path": os.getenv("SDXL_RESIDENTIAL_LORA_MODEL", "").strip().strip('"'),
        "lora_strength": float(os.getenv("SDXL_RESIDENTIAL_LORA_STRENGTH", "0.9")),
    },
    "industrial": {
        "label": "工业区",
        "lora_model_path": os.getenv("SDXL_INDUSTRIAL_LORA_MODEL", "").strip().strip('"'),
        "lora_strength": float(os.getenv("SDXL_INDUSTRIAL_LORA_STRENGTH", "0.9")),
    },
    "commercial": {
        "label": "商业区",
        "lora_model_path": os.getenv("SDXL_COMMERCIAL_LORA_MODEL", "").strip().strip('"'),
        "lora_strength": float(os.getenv("SDXL_COMMERCIAL_LORA_STRENGTH", "0.9")),
    },
    "public": {
        "label": "公共区",
        "lora_model_path": os.getenv("SDXL_PUBLIC_LORA_MODEL", "").strip().strip('"'),
        "lora_strength": float(os.getenv("SDXL_PUBLIC_LORA_STRENGTH", "0.9")),
    },
}

DEFAULT_PROMPT = """
planmask, 2D top view urban planning masterplan, minimalist flat design,
building height expressed by different shades of one allowed zoning color,
solid filled building blocks only, pure white background, no roads, no text,
clean simple composition, optimized for 2D to 3D conversion
""".strip()

NEGATIVE_PROMPT = """
(worst quality, low quality, blurry, noisy, pixelated, aliasing),
roads, streets, pathways, sidewalks, trees, plants, lawns, green belts, water bodies,
text, numbers, labels, annotations, logos, symbols, shadows, gradients, highlights,
3D render, realistic, perspective, isometric view, furniture, people, cars, vehicles,
messy lines, outlines, borders, frames, irregular shapes, hollow structures,
unmapped colors, non-white background, redundant details, extra elements
""".strip()

GENERATE_CONFIG = {
    "width": 1024,
    "height": 1024,
    "num_inference_steps": 30,
    "guidance_scale": 7.0,
    "num_images_per_prompt": 1,
}
MIN_IMAGE_SIZE = 512


def _log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [llmpicture] {message}", flush=True)


def _clear_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def _log_cuda_memory(prefix: str) -> None:
    if not torch.cuda.is_available():
        return
    free, total = torch.cuda.mem_get_info()
    _log(f"{prefix} CUDA memory free={free // 1024 ** 2}MiB total={total // 1024 ** 2}MiB")


def _is_retryable_cuda_error(error: RuntimeError) -> bool:
    message = str(error)
    return (
        "GET was unable to find an engine" in message
        or "CUDA out of memory" in message
        or "CUDNN_STATUS_NOT_SUPPORTED" in message
    )


def _low_memory_retry_config(config: dict[str, Any]) -> dict[str, Any]:
    """显存不足时把画布限制到 768、步数限制到 24，再自动重试一次。"""
    retry_config = dict(config)
    retry_config["width"] = max(MIN_IMAGE_SIZE, min(int(config.get("width", 1024)), 768))
    retry_config["height"] = max(MIN_IMAGE_SIZE, min(int(config.get("height", 1024)), 768))
    retry_config["num_inference_steps"] = min(int(config.get("num_inference_steps", 30)), 24)
    return retry_config


def _parse_payload(raw_input: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw_input, dict):
        return raw_input
    if not raw_input:
        return {}

    candidate = raw_input.strip()
    if candidate.startswith("{"):
        return json.loads(candidate)
    return {"prompt": candidate}


def resolve_model_config(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    model_key = str(payload.get("model_key") or payload.get("area_type") or "residential").strip().lower()
    if model_key not in MODEL_LIBRARY:
        model_key = "residential"
    return model_key, MODEL_LIBRARY[model_key]


def build_generate_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = dict(GENERATE_CONFIG)
    config.update(payload.get("render_preset") or {})
    config["prompt"] = str(payload.get("prompt") or DEFAULT_PROMPT).strip()
    config["negative_prompt"] = str(payload.get("negative_prompt") or NEGATIVE_PROMPT).strip()
    return config


def resolve_diffusers_config_path() -> str:
    """解析 from_single_file 所需配置；只查本地目录/缓存，不在请求中联网下载。"""
    if SDXL_DIFFUSERS_CONFIG_PATH:
        config_path = Path(SDXL_DIFFUSERS_CONFIG_PATH)
        if not config_path.exists():
            raise FileNotFoundError(f"SDXL diffusers config path not found: {config_path}")
        return str(config_path)

    # local_files_only=True 是部署上的刻意约束：请在上线前预下载配置或显式设置路径。
    return snapshot_download(
        repo_id=SDXL_CONFIG_REPO,
        cache_dir=HF_CACHE_DIR,
        local_files_only=True,
        allow_patterns=[
            "model_index.json",
            "scheduler/*",
            "tokenizer/*",
            "tokenizer_2/*",
            "text_encoder/config.json",
            "text_encoder_2/config.json",
            "unet/config.json",
            "vae/config.json",
        ],
    )


def configure_pipeline(pipe: StableDiffusionXLPipeline, device: str) -> StableDiffusionXLPipeline:
    pipe.set_progress_bar_config(disable=True)
    if device != "cuda":
        return pipe

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = False

    # 切片/平铺用更多计算时间换显存，主要服务于 8–12 GB 显存机器。
    if hasattr(pipe, "enable_attention_slicing"):
        pipe.enable_attention_slicing("max")
    if hasattr(pipe.vae, "enable_slicing"):
        pipe.vae.enable_slicing()
    if hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
    return pipe


def run_pipeline(pipe: StableDiffusionXLPipeline, config: dict[str, Any]):
    """执行推理；仅对显存/算子兼容类错误启用低显存重试。"""
    try:
        with torch.inference_mode():
            return pipe(**config).images
    except RuntimeError as error:
        if not _is_retryable_cuda_error(error):
            raise

        _log(f"Primary generation failed: {error}")
        _clear_cuda()
        retry_config = _low_memory_retry_config(config)
        if retry_config == config:
            raise

        _log(
            "Retrying with low-memory config: "
            f"{retry_config['width']}x{retry_config['height']}, "
            f"steps={retry_config['num_inference_steps']}"
        )
        with torch.inference_mode():
            return pipe(**retry_config).images


def generate_image(payload_input: str | dict[str, Any] | None = None, custom_save_path: str | None = None) -> str:
    """加载指定 SDXL/LoRA，生成第一张图片并保存到调用方给出的路径。"""
    payload = _parse_payload(payload_input)
    model_key, model_config = resolve_model_config(payload)
    config = build_generate_config(payload)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    save_path = custom_save_path or "output_generated.png"

    lora_model_path = model_config["lora_model_path"]
    lora_strength = model_config["lora_strength"]

    _log(f"Using device: {device}")
    _log(f"Using model route: {model_key} ({model_config['label']})")
    _log(f"Base model path: {SDXL_BASE_MODEL_PATH}")
    _log(f"LoRA model path: {lora_model_path}")
    _log(f"Output image path: {save_path}")
    _log(f"Generate config: {json.dumps(config, ensure_ascii=False)}")

    if not SDXL_BASE_MODEL_PATH:
        raise RuntimeError("SDXL_BASE_MODEL_PATH is not configured")
    if not lora_model_path:
        env_name = f"SDXL_{model_key.upper()}_LORA_MODEL"
        raise RuntimeError(f"{env_name} is not configured")
    if not os.path.exists(SDXL_BASE_MODEL_PATH):
        raise FileNotFoundError(f"Base model not found: {SDXL_BASE_MODEL_PATH}")
    if not os.path.exists(lora_model_path):
        raise FileNotFoundError(f"LoRA model not found for route '{model_key}': {lora_model_path}")

    _clear_cuda()
    _log_cuda_memory("Before loading model")
    diffusers_config_path = resolve_diffusers_config_path()
    _log(f"Diffusers config path: {diffusers_config_path}")
    _log("Loading local SDXL base model...")
    # CUDA 使用 FP16；CPU 必须回到 FP32，否则很多算子不可用或更慢。
    pipe = StableDiffusionXLPipeline.from_single_file(
        SDXL_BASE_MODEL_PATH,
        config=diffusers_config_path,
        cache_dir=HF_CACHE_DIR,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        safety_checker=None,
        feature_extractor=None,
        local_files_only=True,
    )
    if device == "cuda":
        _log("Enabling CPU offload for low-VRAM SDXL generation")
        # accelerate 在模块需要计算时才搬到 GPU，可显著降低常驻显存，但需要较大的系统内存。
        pipe.enable_model_cpu_offload()
    else:
        pipe = pipe.to(device)
    pipe = configure_pipeline(pipe, device)

    # 使用 Karras sigma 的 DPM-Solver++，在 20–30 步范围内兼顾速度与规划色块稳定性。
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config,
        algorithm_type="sde-dpmsolver++",
        use_karras_sigmas=True,
    )

    _log("Loading LoRA weights...")
    pipe.load_lora_weights(lora_model_path)
    pipe.fuse_lora(lora_scale=lora_strength)

    _log_cuda_memory("Before generation")
    _log("Generating site-plan image...")
    images = run_pipeline(pipe, config)
    images[0].save(save_path)
    _log(f"Image saved: {save_path}")

    del pipe
    _clear_cuda()
    return save_path


def main(payload_input: str | None = None, custom_save_path: str | None = None) -> None:
    generate_image(payload_input, custom_save_path)


if __name__ == "__main__":
    payload_arg = sys.argv[1] if len(sys.argv) > 1 else None
    save_arg = sys.argv[2] if len(sys.argv) > 2 else None
    main(payload_arg, save_arg)
