"""One source of masks/height inputs for both preview and proxy analysis."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import VERSION
from .files import load_rgb, sha256_file
from .pipeline import pixel_hash, process_image

UNIFORM_PROXY_HEIGHT = 12.0


@dataclass
class SceneFields:
    rgb: np.ndarray
    foreground: np.ndarray
    proxy_height: np.ndarray
    metadata: dict


def bundle_for_image(image_path):
    image_path = Path(image_path)
    if image_path.name == "cleaned.png" and (image_path.parent / "fields.npz").is_file():
        return image_path.parent
    return image_path.parent / f"{image_path.stem}_postprocess"


def scene_fingerprint(image_path):
    bundle = bundle_for_image(image_path)
    parts = [VERSION, sha256_file(image_path)]
    for name in ("fields.npz", "report.json"):
        if (bundle / name).is_file():
            parts.append(sha256_file(bundle / name))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def load_scene_fields(image_path) -> SceneFields:
    rgb = load_rgb(image_path)
    bundle = bundle_for_image(image_path)
    if (bundle / "report.json").is_file() and (bundle / "fields.npz").is_file():
        report = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
        if report.get("cleaned_pixel_sha256") != pixel_hash(rgb):
            raise ValueError("Postprocess bundle is stale: image changed. Re-run image postprocessing.")
        if report.get("fields_sha256") != sha256_file(bundle / "fields.npz"):
            raise ValueError("Postprocess fields checksum mismatch. Re-run image postprocessing.")
        with np.load(bundle / "fields.npz", allow_pickle=False) as fields:
            if int(fields["schema_version"]) != 1:
                raise ValueError("Unsupported postprocess fields schema")
            mask = fields["foreground"].astype(bool)
            height_m = fields["height_m"].astype(np.float32)
        if mask.shape != rgb.shape[:2] or height_m.shape != mask.shape:
            raise ValueError("Postprocess fields do not match image size")
        if np.isinf(height_m).any() or np.any(height_m[np.isfinite(height_m)] < 0):
            raise ValueError("Invalid postprocess height values")
        source = "saved_postprocess_bundle"
    else:
        result = process_image(rgb)
        rgb, mask, height_m, report = result.cleaned, result.foreground, result.height_m, result.report
        source = "on_demand_auto_segmentation"
    known = mask & np.isfinite(height_m) & (height_m > 0)
    unknown = mask & ~known
    proxy = np.zeros(mask.shape, dtype=np.float32)
    proxy[known] = height_m[known]
    proxy[unknown] = UNIFORM_PROXY_HEIGHT
    warnings = []
    if unknown.any():
        warnings.append("Unmapped buildings use uniform height 12 for schematic preview/proxy analysis only; this is not a measured or inferred height in meters.")
    if known.any():
        warnings.append("Configured representative heights are user-supplied assumptions, not heights recovered exactly from the image.")
    warnings.append("XY coordinates are image pixels; proxy sunlight/wind metrics are not georeferenced physical simulation.")
    metadata = {"pipeline_version": VERSION, "source": source,
                "height_source": "configured_representative_meters" if known.any() else "uniform_schematic_proxy",
                "known_height_pixels": int(known.sum()), "unknown_height_pixels": int(unknown.sum()),
                "uniform_proxy_height": UNIFORM_PROXY_HEIGHT,
                "source_fingerprint": scene_fingerprint(image_path), "warnings": warnings}
    return SceneFields(rgb, mask, proxy, metadata)
