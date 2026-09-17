"""Local mask repairs with component, hole and inter-building-gap guards."""
from __future__ import annotations

import cv2
import numpy as np


def components(mask):
    return cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)


def holes(mask):
    count, labels, stats, _ = cv2.connectedComponentsWithStats((~mask).astype(np.uint8), connectivity=4)
    border_ids = set(np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1]))))
    return labels, [(i, int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, count) if i not in border_ids]


def repair_component(mask, forbidden, config, scale, diagnostics=None):
    if config.geometry_mode == "off" or not config.repair_geometry or config.defect_radius == 0:
        return mask.copy(), []
    if config.geometry_mode == "regularize":
        from .regularization import regularize_component
        return regularize_component(mask, forbidden, config, scale, diagnostics)
    return repair_component_local(mask, forbidden, config, scale)


def repair_component_local(mask, forbidden, config, scale):
    original = mask.copy()
    events = []
    if not config.repair_geometry or not mask.any():
        return original, events
    radius = max(1, round(config.defect_radius * scale)) if config.defect_radius else 0
    if not radius:
        return original, events
    # Thin strips must survive: cap the radius by the local interior thickness.
    thickness = float(cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5).max())
    radius = min(radius, int(thickness // 3))
    if radius < 1:
        return original, events
    max_hole = round(config.max_hole_area * scale * scale)
    hole_labels, old_holes = holes(original)
    protected = np.isin(hole_labels, [i for i, area in old_holes if area > max_hole])
    kernel = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    proposed = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)
    proposed = cv2.morphologyEx(proposed.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)
    proposed[protected] = False
    proposed[forbidden & ~original] = False
    change = int(np.count_nonzero(proposed != original))
    if not change:
        return original, events
    if change / int(original.sum()) > config.max_geometry_change_ratio:
        return original, ["geometry_budget_exceeded"]
    if components(proposed)[0] != 2:
        return original, ["geometry_would_split_component"]
    # Do not close an open courtyard entrance or create a new enclosed hole.
    new_labels, new_holes = holes(proposed)
    new_hole_ids = {i for i, _ in new_holes}
    matched = set()
    for old_id, area in old_holes:
        if area <= max_hole:
            continue
        ids = set(np.unique(new_labels[hole_labels == old_id]))
        # A courtyard must remain one enclosed hole, distinct from other holes.
        if len(ids) != 1 or not ids.issubset(new_hole_ids) or matched.intersection(ids):
            return original, ["geometry_would_open_or_merge_courtyard"]
        matched.update(ids)
    for new_id, _ in new_holes:
        if not any(np.any((new_labels == new_id) & (hole_labels == old_id)) for old_id, _ in old_holes):
            return original, ["geometry_would_close_passage"]
    if np.any(proposed & protected):
        return original, ["geometry_would_fill_courtyard"]
    events.append("local_geometry_repair")
    return proposed, events
