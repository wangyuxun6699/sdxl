"""Reproducible PNG validation and original/v1/v2 comparisons, without SDXL.

The optional baseline directory contains actual v1 bundles, not v2's local mode.
Synthetic metrics have known masks; user PNGs have no ground-truth accuracy.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import PIL
from PIL import Image, ImageDraw, ImageFont

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.postprocessing import PostprocessConfig, process_file, process_image
from backend.postprocessing.files import sha256_file
from backend.postprocessing.pipeline import pixel_hash


def panel(images, titles):
    w, h = images[0].size
    out = Image.new("RGB", (w * len(images), h + 36), "#f1f3f5")
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, (im, title) in enumerate(zip(images, titles)):
        out.paste(im, (i * w, 36))
        draw.text((i * w + 12, 8), title, fill="#222222", font=font)
    return out


def boundary_band(mask, pixels):
    # Inner boundary band, with explicit background padding for edge objects.
    padded = np.pad(mask.astype(np.uint8), pixels)
    eroded = cv2.erode(padded, np.ones((3, 3), np.uint8), iterations=pixels)
    return mask & ~eroded[pixels:-pixels, pixels:-pixels].astype(bool)


def mask_iou(a, b):
    return float((a & b).sum()) / max(int((a | b).sum()), 1)


def synthetic_benchmark(output):
    records = []
    for scale in (0.6, 1.0, 1.6):
        for angle in (0, 13, 27, 45, 73):
            truth = np.zeros((300, 360), np.uint8)
            truth[105:165, 70:290] = 1
            flawed = truth.copy()
            flawed[105:112, 125:145] = 0
            flawed[156:165, 235:246] = 0
            flawed[165:174, 185:192] = 1
            rotation = cv2.getRotationMatrix2D((180, 150), angle, scale)
            truth = cv2.warpAffine(truth, rotation, (360, 300), flags=cv2.INTER_NEAREST).astype(bool)
            flawed = cv2.warpAffine(flawed, rotation, (360, 300), flags=cv2.INTER_NEAREST).astype(bool)
            rgb = np.full((300, 360, 3), 255, np.uint8)
            rgb[flawed] = (70, 100, 175)
            # Only geometry is compared here; local is the preserved v1 geometry
            # implementation, not a claim to rerun the entire v1 color pipeline.
            local = process_image(rgb, PostprocessConfig(geometry_mode="local", clean_colors=False))
            regularized = process_image(rgb, PostprocessConfig(clean_colors=False))
            band = max(1, round(2 * scale))
            target_band = boundary_band(truth, band)
            row = {"scale": scale, "angle_deg": angle, "boundary_band_px": band,
                   "touches_frame": bool(truth[0].any() or truth[-1].any() or truth[:, 0].any() or truth[:, -1].any()),
                   "local_mask_iou": mask_iou(truth, local.foreground),
                   "v2_mask_iou": mask_iou(truth, regularized.foreground),
                   "local_boundary_iou": mask_iou(target_band, boundary_band(local.foreground, band)),
                   "v2_boundary_iou": mask_iou(target_band, boundary_band(regularized.foreground, band))}
            records.append({k: round(v, 6) if isinstance(v, float) else v for k, v in row.items()})
    with (output / "synthetic_boundary_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Directory of original PNGs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Directory of actual v1 result bundles")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    source, output = args.input.resolve(), args.output.resolve()
    if not source.is_dir() or source == output or output in source.parents or source in output.parents:
        parser.error("Choose separate, non-nested input and output directories")
    inputs = sorted(source.glob("*.png"))
    if not inputs:
        parser.error("Input directory contains no PNGs")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in inputs:
        target = output / path.name
        info = process_file(path, target, overwrite=args.overwrite)
        report = info["report"]
        assert report["source"]["sha256"] == sha256_file(path) == sha256_file(target / "source.png")
        original = Image.open(target / "original.png").convert("RGB")
        cleaned = Image.open(target / "cleaned.png").convert("RGB")
        assert original.size == cleaned.size
        images, titles = [original], ["ORIGINAL"]
        before = None
        if args.baseline:
            baseline = args.baseline / path.name
            before = json.loads((baseline / "report.json").read_text(encoding="utf-8"))
            if not str(before["pipeline_version"]).startswith("1.") or before["source"]["sha256"] != sha256_file(path):
                raise ValueError(f"Baseline is not the actual v1 result for {path.name}")
            im = Image.open(baseline / "cleaned.png").convert("RGB")
            if pixel_hash(np.array(im)) != before["cleaned_pixel_sha256"]:
                raise ValueError(f"Baseline image checksum mismatch: {path.name}")
            shutil.copyfile(baseline / "cleaned.png", target / "v1_cleaned.png")
            shutil.copyfile(baseline / "report.json", target / "v1_report.json")
            images.append(im)
            titles.append("V1")
        images.append(cleaned)
        titles.append("V2")
        panel(images, titles).save(target / "comparison_v1_v2.png")
        # Geometry-only overlay avoids a nearly solid mask caused by normalizing
        # very slightly off-white backgrounds.
        rgba = np.zeros((cleaned.height, cleaned.width, 4), np.uint8)
        for name, color in (("geometry_added_mask", (0, 130, 255, 210)),
                            ("geometry_removed_mask", (230, 45, 125, 210))):
            m = np.array(Image.open(target / f"{name}.png")) > 0
            rgba[m] = color
        Image.fromarray(rgba).save(target / "geometry_overlay.png")
        merged = Image.alpha_composite(original.convert("RGBA"), Image.fromarray(rgba)).convert("RGB")
        merged.save(target / "geometry_changes.png")
        row = {"filename": path.name, "sha256": sha256_file(path), "size": list(original.size),
               "v1_counts": before["counts"] if before else None,
               "v2_counts": report["counts"], "core_seconds": report["elapsed_seconds"],
               "cleaned_pixel_sha256": report["cleaned_pixel_sha256"]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {"pipeline_version": "2.0.0", "python": platform.python_version(),
               "numpy": np.__version__, "opencv": cv2.__version__, "pillow": PIL.__version__,
               "note": "User PNGs have no ground truth. Counts and changed pixels are not accuracy. CPU timing excludes file I/O.",
               "images": rows, "synthetic_geometry_benchmark": synthetic_benchmark(output)}
    (output / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
