from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .config import PostprocessConfig
from .pipeline import process_image

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rgb(path, config=None):
    config = (config or PostprocessConfig()).validate()
    with Image.open(path) as im:
        if im.width * im.height > config.max_pixels:
            raise ValueError(f"Image exceeds max_pixels ({config.max_pixels})")
        im = ImageOps.exif_transpose(im)
        if "A" in im.getbands() or "transparency" in im.info:
            rgba = im.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, tuple(config.background_rgb or (255, 255, 255)) + (255,))
            return np.array(Image.alpha_composite(bg, rgba).convert("RGB"))
        return np.array(im.convert("RGB"))


def _save_result(result, directory, source):
    Image.fromarray(result.original).save(directory / "original.png")
    Image.fromarray(result.cleaned).save(directory / "cleaned.png")
    for name, array in (("foreground_mask", result.foreground), ("review_mask", result.review_mask),
                        ("change_mask", np.any(result.original != result.cleaned, axis=2)),
                        ("geometry_review_mask", result.geometry_review_mask),
                        ("geometry_added_mask", result.geometry_added_mask),
                        ("geometry_removed_mask", result.geometry_removed_mask)):
        Image.fromarray(array.astype(np.uint8) * 255).save(directory / f"{name}.png")
    ids = result.region_ids.astype(np.uint32)
    colored = np.stack(((ids * 73 + 47) % 206 + 30, (ids * 151 + 97) % 206 + 30,
                        (ids * 193 + 13) % 206 + 30), axis=2).astype(np.uint8)
    colored[ids == 0] = 255
    Image.fromarray(colored).save(directory / "regions.png")
    width, height = min(1000, result.original.shape[1]), result.original.shape[0]
    height = max(1, round(height * width / result.original.shape[1]))
    comparison = Image.new("RGB", (width * 2, height + 36), "#f3f4f6")
    draw = ImageDraw.Draw(comparison)
    draw.text((12, 10), "ORIGINAL", fill="#222222")
    draw.text((width + 12, 10), "CLEANED", fill="#222222")
    for x, data in ((0, result.original), (width, result.cleaned)):
        comparison.paste(Image.fromarray(data).resize((width, height), Image.Resampling.NEAREST), (x, 36))
    comparison.save(directory / "comparison.png")
    np.savez_compressed(directory / "fields.npz", schema_version=np.array(1, dtype=np.int32),
                        region_ids=result.region_ids, foreground=result.foreground,
                        review_mask=result.review_mask, height_m=result.height_m)
    report = dict(result.report)
    report["source"] = {"filename": source.name, "sha256": sha256_file(source)}
    report["fields_sha256"] = sha256_file(directory / "fields.npz")
    report["files"] = ["original.png", "cleaned.png", "foreground_mask.png", "regions.png", "fields.npz",
                       "review_mask.png", "change_mask.png", "geometry_review_mask.png", "geometry_added_mask.png",
                       "geometry_removed_mask.png", "comparison.png", "report.json", f"source{source.suffix.lower()}"]
    shutil.copyfile(source, directory / f"source{source.suffix.lower()}")
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def process_file(input_path, output_dir, config=None, *, mask_path=None, overwrite=False):
    """Write an inspectable bundle. Source bytes never change; failures leave no partial bundle."""
    source, target = Path(input_path).resolve(), Path(output_dir).resolve()
    config = (config or PostprocessConfig()).validate()
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image extension: {source.suffix}")
    if target == source or target in source.parents:
        raise ValueError("Output bundle cannot contain or replace the input image")
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"Output exists: {target}; choose another directory or use --overwrite")
        marker = target / "report.json"
        if not marker.is_file() or not (target / "fields.npz").is_file():
            raise ValueError("Refusing to replace a directory that is not a postprocess bundle")
        if "pipeline_version" not in json.loads(marker.read_text(encoding="utf-8")):
            raise ValueError("Unrecognized output bundle")
    rgb = load_rgb(source, config)
    mask = None
    if mask_path:
        with Image.open(mask_path) as image:
            if image.width * image.height > config.max_pixels:
                raise ValueError("Mask exceeds max_pixels")
            mask = np.array(ImageOps.exif_transpose(image).convert("L")) > 127
    result = process_image(rgb, config, mask)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    backup = None
    try:
        report = _save_result(result, temporary, source)
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{target.name}-backup-", dir=target.parent))
            backup.rmdir()
            target.rename(backup)
        try:
            temporary.rename(target)
        except BaseException:
            if backup is not None:
                backup.rename(target)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return {"output_dir": str(target), "cleaned_path": str(target / "cleaned.png"), "report": report}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
