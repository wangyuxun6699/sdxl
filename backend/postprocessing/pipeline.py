from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .config import PostprocessConfig, VERSION
from .geometry import components, repair_component
from .regularization import fragment_candidates
from .regions import split_regions, to_lab


@dataclass
class PostprocessResult:
    original: np.ndarray
    cleaned: np.ndarray
    foreground: np.ndarray
    region_ids: np.ndarray
    review_mask: np.ndarray
    height_m: np.ndarray
    report: dict
    geometry_review_mask: np.ndarray
    geometry_added_mask: np.ndarray
    geometry_removed_mask: np.ndarray


def pixel_hash(rgb):
    return hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()


def estimate_background(rgb, config):
    if config.background_rgb is not None:
        return np.array(config.background_rgb, dtype=np.uint8), 1.0
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
    codes = border.astype(np.uint32) // 8
    codes = codes[:, 0] * 1024 + codes[:, 1] * 32 + codes[:, 2]
    code = np.bincount(codes).argmax()
    members = codes == code
    return np.rint(np.median(border[members], axis=0)).astype(np.uint8), float(members.mean())


def process_image(rgb: np.ndarray, config: PostprocessConfig | None = None,
                  foreground_mask: np.ndarray | None = None) -> PostprocessResult:
    started = time.perf_counter()
    config = (config or PostprocessConfig()).validate()
    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("process_image requires an H x W x 3 uint8 RGB array")
    h, w = rgb.shape[:2]
    if min(h, w) < 1 or h * w > config.max_pixels:
        raise ValueError("Image is empty or exceeds max_pixels")
    rgb = np.ascontiguousarray(rgb)
    background, bg_confidence = estimate_background(rgb, config)
    lab = to_lab(rgb)
    bg_lab = to_lab(background.reshape(1, 1, 3))[0, 0]
    if foreground_mask is None:
        foreground = np.linalg.norm(lab - bg_lab, axis=2) > config.background_delta
    else:
        if foreground_mask.shape != (h, w):
            raise ValueError("Foreground mask must match image dimensions after EXIF orientation")
        foreground = np.asarray(foreground_mask) > 0
    count, objects, stats, _ = components(foreground)
    scale = max(0.5, min(h, w) / 1024.0)
    padding = max(6, round(config.defect_radius * scale) * 3 + 2)
    cleaned = rgb.copy()
    if config.clean_colors:
        cleaned[~foreground] = background
    output_mask = foreground.copy()
    region_ids = np.zeros((h, w), dtype=np.int32)
    review_mask = np.zeros((h, w), dtype=bool)
    geometry_review_mask = np.zeros((h, w), dtype=bool)
    height_m = np.full((h, w), np.nan, dtype=np.float32)
    height_m[~foreground] = 0.0
    regions, object_reports = [], []
    total_noise = 0
    total_shared_boundaries = 0
    next_region = 0
    removed_fragments, fragment_reference = fragment_candidates(objects, stats, config, scale) if foreground_mask is None else ({}, {})
    removed_support = np.isin(objects, list(removed_fragments)) if removed_fragments else np.zeros((h, w), bool)
    output_mask[removed_support] = False
    cleaned[removed_support] = background
    palette_rgb = np.array([entry["rgb"] for entry in config.colors], dtype=np.uint8)
    palette_lab = to_lab(palette_rgb.reshape(1, -1, 3))[0] if config.mode == "palette" else None
    for object_id in range(1, count):
        x, y, bw, bh, area = map(int, stats[object_id])
        x0, y0, x1, y1 = max(0, x - padding), max(0, y - padding), min(w, x + bw + padding), min(h, y + bh + padding)
        sl = np.s_[y0:y1, x0:x1]
        original_mask = objects[sl] == object_id
        geometry_info = {}
        if object_id in removed_fragments:
            object_reports.append({"id": object_id, "bbox_xywh": [x, y, bw, bh], "area_before_px": area,
                                   "area_after_px": 0, "region_ids": [], "multiple_color_regions_preserved": False,
                                   "events": ["isolated_fragment_removed"], "geometry": removed_fragments[object_id]})
            continue
        others = (objects[sl] != 0) & ~original_mask & ~removed_support[sl]
        # Both objects keep at least a background pixel between their supports.
        forbidden = cv2.dilate(others.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        local_mask, events = repair_component(original_mask, forbidden, config, scale, geometry_info) if foreground_mask is None else (original_mask.copy(), [])
        # Respect additions already made by an earlier neighboring component.
        added_elsewhere = output_mask[sl] & (~foreground[sl] | removed_support[sl])
        forbidden |= cv2.dilate(added_elsewhere.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        if np.any((local_mask & ~original_mask) & forbidden):
            local_mask = original_mask.copy()
            events = ["geometry_neighbor_guard"]
            geometry_info["review_required"] = True
        if geometry_info.get("review_required"):
            geometry_review_mask[sl][original_mask | local_mask] = True
        local_rgb = rgb[sl].copy()
        added = local_mask & ~original_mask
        if added.any():
            kept = original_mask & local_mask
            depth = cv2.distanceTransform(np.pad(kept.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
            width = max(1.0, float(np.percentile(depth[kept], 85)) * 2 - 1) if kept.any() else 1.0
            color_support = depth > max(2, min(6, round(width * .12)))
            if not color_support.any():
                color_support = original_mask
            _, nearest = cv2.distanceTransformWithLabels((~color_support).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
            table = np.vstack([background, local_rgb[color_support]])
            local_rgb[added] = table[nearest[added]]
        output_mask[sl][original_mask] = False
        output_mask[sl][local_mask] = True
        cleaned[sl][original_mask & ~local_mask] = background
        cleaned[sl][added] = local_rgb[added]
        labels, flags = split_regions(local_rgb, local_mask, original_mask & local_mask, config, scale, background)
        # Edge decontamination has its own foreground/background mixture test.
        # Do not discard that correction merely because a different interior
        # color boundary in the same region needs review.
        edge_corrected = original_mask & local_mask & np.any(local_rgb != rgb[sl], axis=2)
        if config.clean_colors:
            cleaned[sl][edge_corrected] = local_rgb[edge_corrected]
        total_noise += flags["noise_regions_merged"]
        total_shared_boundaries += flags["shared_boundaries_regularized"]
        if flags.get("soft_noise_collapsed"):
            events.append("soft_color_noise_collapsed")
        local_lab = to_lab(local_rgb)
        ids = np.unique(labels[local_mask])
        object_region_ids = []
        for local_id in ids:
            part = labels == local_id
            source = part & original_mask
            interior = cv2.erode(source.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            samples = interior if interior.sum() >= 4 else source
            if not samples.any():
                samples = part
            color = np.rint(np.median(local_rgb[samples], axis=0)).astype(np.uint8)
            center_lab = to_lab(color.reshape(1, 1, 3))[0, 0]
            spread = float(np.percentile(np.linalg.norm(local_lab[samples] - center_lab, axis=1), 90))
            uncertain = flags["complexity_guard"] or local_id in flags["weak_region_ids"] or (spread > config.color_delta * 1.8 and not flags.get("soft_noise_collapsed"))
            entry, palette_distance = None, None
            if config.mode == "palette" and not uncertain:
                distances = np.linalg.norm(palette_lab - center_lab, axis=1)
                order = np.argsort(distances, kind="stable")
                palette_distance = float(distances[order[0]])
                margin = float(distances[order[1]] - distances[order[0]]) if len(order) > 1 else float("inf")
                if palette_distance <= config.palette_delta and margin >= config.palette_margin:
                    entry = config.colors[int(order[0])]
                    color = np.array(entry["rgb"], dtype=np.uint8)
                else:
                    uncertain = True
            if config.clean_colors and not uncertain:
                cleaned[sl][part] = color
            next_region += 1
            object_region_ids.append(next_region)
            region_ids[sl][part] = next_region
            review_mask[sl][part] = (uncertain & ~edge_corrected[part]) if config.clean_colors else uncertain
            if entry is not None and entry["height_m"] is not None:
                height_m[sl][part] = entry["height_m"]
            else:
                height_m[sl][part] = np.nan
            py, px = np.nonzero(part)
            regions.append({"id": next_region, "component_id": object_id, "area_px": int(part.sum()),
                            "bbox_xywh": [int(px.min()) + x0, int(py.min()) + y0, int(px.max() - px.min() + 1), int(py.max() - py.min() + 1)],
                            "representative_rgb": color.tolist(), "spread_delta_e_p90": round(spread, 3),
                            "review_required": bool(uncertain), "palette_name": entry["name"] if entry else None,
                            "height_m": entry["height_m"] if entry else None,
                            "palette_distance": round(palette_distance, 3) if palette_distance is not None else None})
        object_reports.append({"id": object_id, "bbox_xywh": [x, y, bw, bh], "area_before_px": area, "area_after_px": int(local_mask.sum()),
                               "region_ids": object_region_ids, "multiple_color_regions_preserved": len(ids) > 1,
                               "events": events, "geometry": geometry_info})
    height_m[~output_mask] = 0
    changed = np.any(cleaned != rgb, axis=2)
    geometry_changed = foreground != output_mask
    warnings = ["Color regions are not building instances or ordered height classes.",
                "Stable false color splits cannot be distinguished from true height parts using RGB alone."]
    if bg_confidence < 0.55:
        warnings.append("Background estimate has weak border support; set background_rgb or supply a foreground mask.")
    if not foreground.any():
        warnings.append("No foreground detected.")
    if foreground.mean() > 0.8:
        warnings.append("Foreground covers over 80%; check background and whether this is a flat planning diagram.")
    if review_mask.any():
        warnings.append("Uncertain region colors were preserved; inspect review_mask.png.")
    if geometry_review_mask.any():
        warnings.append("Some footprint candidates violated geometry guards; inspect geometry_review_mask.png and component events.")
    known = output_mask & np.isfinite(height_m)
    if np.any(output_mask & ~known):
        warnings.append("Unknown heights are NaN, not zero; no meters are inferred from brightness.")
    report = {"schema_version": 1, "pipeline_version": VERSION, "mode": config.mode,
              "config": config.as_dict(), "config_sha256": hashlib.sha256(json.dumps(config.as_dict(), sort_keys=True).encode()).hexdigest(),
              "input_pixel_sha256": pixel_hash(rgb), "cleaned_pixel_sha256": pixel_hash(cleaned),
              "size": {"width": w, "height": h}, "background_rgb": background.tolist(),
              "background_border_support": round(bg_confidence, 4), "scale_1024": round(scale, 4),
              "geometry_mode": config.geometry_mode, "fragment_reference": fragment_reference,
              "counts": {"components_before": count - 1, "components_after": components(output_mask)[0] - 1,
                         "fragments_removed": len(removed_fragments),
                         "footprints_regularized": sum("footprint_regularized" in obj["events"] for obj in object_reports),
                         "geometry_review_px": int(geometry_review_mask.sum()),
                         "color_regions": next_region, "noise_regions_merged": total_noise,
                         "shared_boundaries_regularized": total_shared_boundaries,
                         "geometry_changed_px": int(geometry_changed.sum()), "changed_px": int(changed.sum()),
                         "geometry_added_px": int((output_mask & ~foreground).sum()),
                         "geometry_removed_px": int((foreground & ~output_mask).sum()),
                         "changed_foreground_px": int((changed & (foreground | output_mask)).sum()),
                         "changed_background_px": int((changed & ~(foreground | output_mask)).sum()),
                         "review_px": int(review_mask.sum()), "foreground_px": int(output_mask.sum()),
                         "known_height_px": int(known.sum())},
              "height_source": "configured_representative_meters" if known.any() else "unknown",
              "elapsed_seconds": round(time.perf_counter() - started, 4),
              "warnings": warnings, "components": object_reports, "regions": regions}
    return PostprocessResult(rgb.copy(), cleaned, output_mask, region_ids, review_mask, height_m, report,
                             geometry_review_mask, output_mask & ~foreground, foreground & ~output_mask)
