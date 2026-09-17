from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..postprocessing import load_config, process_file
from .logger import log_step
from .settings import BACKEND_DIR


def postprocess_generated_image(image_path: str) -> Path:
    """Preserve original bytes and publish cleaned pixels only after a complete bundle exists."""
    path = Path(image_path)
    configured = os.getenv("CITY_POSTPROCESS_CONFIG", "").strip()
    config_path = Path(configured) if configured else None
    if config_path is not None and not config_path.is_absolute():
        config_path = BACKEND_DIR / config_path
    config = load_config(config_path)
    bundle = path.parent / f"{path.stem}_postprocess"
    result = process_file(path, bundle, config)
    temporary = path.with_name(f".{path.name}.cleaned.tmp")
    try:
        shutil.copyfile(result["cleaned_path"], temporary)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    counts = result["report"]["counts"]
    log_step("POSTPROCESS", f"mode={config.mode}; changed={counts['changed_px']}px; geometry={counts['geometry_changed_px']}px; review={counts['review_px']}px")
    return bundle
