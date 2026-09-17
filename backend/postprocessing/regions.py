"""Adaptive per-component color modes followed by spatial connected regions.

All thresholds use float CIE Lab (L in 0..100). A mode/region is not a height
class or a building instance. Small sharp regions are intentionally retained.
"""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import components


def regularize_shared_boundaries(labels, lab, config):
    """Fit a supported straight interface once, updating its two sides together.
    There is no independent dilation of color regions, hence no seams/overlap.
    Curved/complex interfaces and weak gradient-derived splits are skipped.
    """
    if not config.regularize_color_boundaries or not config.clean_colors:
        return 0
    pairs = {}
    for axis in (0, 1):
        a, b = (labels[:-1], labels[1:]) if axis == 0 else (labels[:, :-1], labels[:, 1:])
        ya, xa = np.nonzero((a > 0) & (b > 0) & (a != b))
        if not len(ya):
            continue
        pair_ids = np.sort(np.column_stack((a[ya, xa], b[ya, xa])), axis=1)
        unique, inv = np.unique(pair_ids, axis=0, return_inverse=True)
        points = np.column_stack((xa + (0.5 if axis == 1 else 0), ya + (0.5 if axis == 0 else 0)))
        contrast = np.linalg.norm(lab[ya, xa] - lab[ya + (axis == 0), xa + (axis == 1)], axis=1)
        for index, pair in enumerate(unique):
            entry = pairs.setdefault(tuple(map(int, pair)), [[], []])
            entry[0].extend(points[inv == index].tolist())
            entry[1].extend(contrast[inv == index].tolist())
    yy, xx = np.indices(labels.shape)
    changed = 0
    kernel = np.ones((3, 3), np.uint8)
    for (a, b), (samples, contrasts) in sorted(pairs.items()):
        if len(samples) < 12 or np.median(contrasts) < max(1.5, config.color_delta * 0.45):
            continue
        ma, mb = labels == a, labels == b
        ca, cb = cv2.erode(ma.astype(np.uint8), kernel), cv2.erode(mb.astype(np.uint8), kernel)
        if min(int(ca.sum()), int(cb.sum())) < 9:
            continue
        points = np.asarray(samples, np.float32)
        vx, vy, px, py = map(float, cv2.fitLine(points, cv2.DIST_HUBER, 0, .01, .01).ravel())
        normal = np.array([-vy, vx])
        offsets = (points - [px, py]) @ normal
        along = (points - [px, py]) @ np.array([vx, vy])
        span = float(np.ptp(along))
        if span < 10 or np.percentile(np.abs(offsets), 95) > 2.0:
            continue
        # Sustained bowing is meaningful geometry, even if a straight line is
        # numerically close over a short span.
        fit = np.polyval(np.polyfit(along / span, offsets, 2), along / span)
        if np.ptp(fit) > 1.6:
            continue
        distance = (xx - px) * normal[0] + (yy - py) * normal[1]
        projection = (xx - px) * vx + (yy - py) * vy
        sign = 1 if np.median(distance[ma]) > np.median(distance[mb]) else -1
        eligible = (ma | mb) & (np.abs(distance) <= 2.1) & (projection > along.min() + 1) & (projection < along.max() - 1)
        proposed = np.where(sign * distance >= 0, a, b)
        moving = eligible & (proposed != labels)
        if not moving.any():
            continue
        na, nb = ma.copy(), mb.copy()
        na[eligible], nb[eligible] = proposed[eligible] == a, proposed[eligible] == b
        if any(np.count_nonzero(old != new) > int(old.sum()) * .08 for old, new in ((ma, na), (mb, nb))):
            continue
        if components(na)[0] != 2 or components(nb)[0] != 2:
            continue
        labels[eligible] = proposed[eligible]
        changed += 1
    return changed


def to_lab(rgb):
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def nearest_modes(values, centers, tolerance):
    result = np.empty(len(values), dtype=np.int32)
    for start in range(0, len(values), 16384):
        distances = ((values[start:start + 16384, None] - centers[None]) ** 2).sum(axis=2)
        # A rare tail mode must not steal ordinary noise pixels from a dominant
        # mode. Accept the first well-supported mode inside the noise radius.
        accepted = distances <= tolerance * tolerance
        result[start:start + 16384] = np.where(accepted.any(axis=1), accepted.argmax(axis=1), distances.argmin(axis=1))
    return result


def find_modes(values, tolerance, limit):
    # Deterministic weighted histogram; no random initialization or fixed K.
    # Include every stable sample so a tiny tower on a large podium is not
    # lost by global subsampling. Packed Lab bins make this a 1D histogram.
    quantized = np.rint(values / 2.0).astype(np.int32)
    packed = (quantized[:, 0] * 129 + quantized[:, 1] + 64) * 129 + quantized[:, 2] + 64
    bins, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    means = np.stack([np.bincount(inverse, weights=values[:, channel]) / counts for channel in range(3)], axis=1)
    remaining = np.ones(len(bins), dtype=bool)
    centers = []
    for index in np.argsort(-counts, kind="stable"):
        if not remaining[index]:
            continue
        close = remaining & (np.linalg.norm(means - means[index], axis=1) <= tolerance)
        centers.append(np.average(means[close], axis=0, weights=counts[close]))
        remaining[close] = False
        if len(centers) > limit:
            return None
    return np.asarray(centers, dtype=np.float32)


def split_regions(rgb, mask, original_mask, config, scale, background_rgb=None):
    lab = to_lab(rgb)
    # Use an edge-preserving discovery image only. Final colors still come from
    # original pixels; strong small color parts are not spatially blurred away.
    discovery = cv2.bilateralFilter(lab, 5, min(3.0, config.color_delta * 0.6), 2.0)
    depth = cv2.distanceTransform(np.pad(original_mask.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    width = max(1.0, float(np.percentile(depth[original_mask], 85)) * 2 - 1) if original_mask.any() else 1.0
    # A fixed two-pixel inset still samples the blurred fringe of thick walls.
    # Scale only the *outer-footprint* inset; internal small color parts retain
    # their samples and are not eroded independently.
    radius = max(2, min(6, round(width * 0.12)))
    inner = depth > radius
    kernel = np.ones((3, 3), np.uint8)
    local_range = np.linalg.norm(cv2.dilate(discovery, kernel) - cv2.erode(discovery, kernel), axis=2)
    stable = inner & (local_range <= config.color_delta)
    sample = stable if stable.sum() >= 8 else (inner if inner.sum() >= 8 else original_mask)
    centers = find_modes(discovery[sample], config.color_delta, config.max_prototypes)
    if centers is None:
        return mask.astype(np.int32), {"complexity_guard": True, "noise_regions_merged": 0, "weak_region_ids": [], "shared_boundaries_regularized": 0}
    classes = np.zeros(mask.shape, dtype=np.int32)
    classes[mask] = nearest_modes(discovery[mask], centers, config.color_delta) + 1
    # Anti-aliased edge mixtures must not become height bands. Transfer only
    # pixels supported as foreground/background mixtures to a nearby interior
    # class; saturated, distinct tiny parts remain independently classified.
    if background_rgb is not None and stable.any():
        trusted = stable & mask
        if trusted.any():
            _, nearest = cv2.distanceTransformWithLabels((~trusted).astype(np.uint8), cv2.DIST_L2, 5,
                                                         labelType=cv2.DIST_LABEL_PIXEL)
            class_table = np.r_[0, classes[trusted]]
            rgb_table = np.vstack((np.zeros((1, 3)), rgb[trusted])).astype(float)
            rim = mask & ~inner
            near_rgb = rgb_table[nearest[rim]]
            values = rgb[rim].astype(float)
            axis = np.asarray(background_rgb, float) - near_rgb
            alpha = np.sum((values - near_rgb) * axis, axis=1) / np.maximum(np.sum(axis * axis, axis=1), 1)
            residual = np.linalg.norm(values - (near_rgb + alpha[:, None] * axis), axis=1)
            near_lab = to_lab(np.clip(near_rgb, 0, 255).astype(np.uint8).reshape(1, -1, 3))[0]
            close = np.linalg.norm(lab[rim] - near_lab, axis=1) <= config.color_delta
            mixture = (alpha > 0.02) & (alpha < 0.98) & (residual < 10)
            values_classes = classes[rim]
            values_classes[close | mixture] = class_table[nearest[rim]][close | mixture]
            classes[rim] = values_classes
            # Use the same decontaminated observation for region statistics;
            # otherwise a reassigned white fringe falsely flags a broad gradient.
            rim_rgb = rgb[rim].copy()
            rim_rgb[mixture] = np.clip(near_rgb[mixture], 0, 255).astype(np.uint8)
            rgb[rim] = rim_rgb
            rim_lab = lab[rim].copy()
            rim_lab[mixture] = near_lab[mixture]
            lab[rim] = rim_lab
    labels = np.zeros(mask.shape, dtype=np.int32)
    next_id = 0
    areas = {}
    for class_id in range(1, len(centers) + 1):
        count, local, stats, _ = components(classes == class_id)
        for i in range(1, count):
            next_id += 1
            labels[local == i] = next_id
            areas[next_id] = int(stats[i, cv2.CC_STAT_AREA])
    # RAG on pixel-scale islands only. Never merge a region because it is a
    # small percentage of a large podium: an intact small tower must survive.
    noise_limit = max(1, round(config.max_noise_region_area * scale * scale)) if config.max_noise_region_area else 0
    merged = 0
    for index, area in areas.items():
        if area > noise_limit:
            continue
        part = labels == index
        if not part.any():
            continue
        border = cv2.dilate(part.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~part
        neighbors = labels[border]
        ids = np.unique(neighbors)
        if len(ids) == 1 and ids[0] != 0 and areas.get(int(ids[0]), 0) >= max(12, area * 8):
            labels[part] = ids[0]
            merged += 1
    # Color clustering can invent bands in a continuous gradient. A split must
    # have a real local edge, otherwise retain the original colors for review.
    float_labels = labels.astype(np.float32)
    region_core = inner & (cv2.erode(float_labels, kernel) == float_labels) & (cv2.dilate(float_labels, kernel) == float_labels)
    core_counts = np.bincount(labels[region_core], minlength=next_id + 1)
    pair_samples = {}
    for a, b, la, lb in ((labels[:, :-1], labels[:, 1:], lab[:, :-1], lab[:, 1:]),
                          (labels[:-1], labels[1:], lab[:-1], lab[1:])):
        edge = (a > 0) & (b > 0) & (a != b)
        pairs = np.sort(np.stack((a[edge], b[edge]), axis=1), axis=1)
        contrasts = np.linalg.norm(la[edge] - lb[edge], axis=1)
        if not len(pairs):
            continue
        unique, inverse = np.unique(pairs, axis=0, return_inverse=True)
        for i, pair in enumerate(unique):
            pair_samples.setdefault(tuple(map(int, pair)), []).extend(contrasts[inverse == i].tolist())
    weak = set()
    supported_split = False
    for pair, contrasts in pair_samples.items():
        if min(core_counts[pair[0]], core_counts[pair[1]]) >= 4 and len(contrasts) >= 4:
            samples_a = lab[region_core & (labels == pair[0])]
            samples_b = lab[region_core & (labels == pair[1])]
            ca, cb = np.median(samples_a, axis=0), np.median(samples_b, axis=0)
            separation = float(np.linalg.norm(ca - cb))
            stable_plateaus = max(float(np.percentile(np.linalg.norm(samples_a - ca, axis=1), 90)),
                                  float(np.percentile(np.linalg.norm(samples_b - cb, axis=1), 90))) <= config.color_delta * 1.5
            # A sharp tiny part or two well separated stable plateaus protects
            # a real split even if it occupies a very small fraction of a podium.
            if stable_plateaus and ((separation >= config.color_delta and np.median(contrasts) >= max(2.5, config.color_delta * .6)) or separation >= config.color_delta * 2):
                supported_split = True
        # A thin antialias/JPEG fringe is not evidence of a broad continuous
        # gradient. Only two regions with genuine interior support can flag it.
        if min(core_counts[pair[0]], core_counts[pair[1]]) >= 8 and len(contrasts) >= 4 and np.median(contrasts) < max(1.5, config.color_delta * 0.45):
            weak.update(pair)
    # Low-amplitude soft color noise with no supported interior discontinuity
    # is a single surface. This avoids manufacturing hundreds of tiny bands
    # from compressed/antialiased solid blocks. A broad continuous gradient
    # fails the spread bound and remains explicitly flagged for review.
    if inner.sum() >= 16 and not supported_split:
        samples = lab[inner]
        spread = float(np.percentile(np.linalg.norm(samples - np.median(samples, axis=0), axis=1), 90))
        if spread <= config.color_delta * 2:
            return mask.astype(np.int32), {"complexity_guard": False, "noise_regions_merged": merged,
                                           "weak_region_ids": [], "shared_boundaries_regularized": 0,
                                           "soft_noise_collapsed": next_id > 1}
    # Assess color-edge evidence at its observed location. If it were assessed
    # after straightening, the newly moved interface could lie inside a flat
    # color and falsely look like an unsupported gradient-derived partition.
    shared = regularize_shared_boundaries(labels, lab, config)
    return labels, {"complexity_guard": False, "noise_regions_merged": merged, "weak_region_ids": sorted(weak),
                    "shared_boundaries_regularized": shared}
