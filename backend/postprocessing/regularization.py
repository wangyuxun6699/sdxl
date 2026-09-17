"""Palette-independent footprint regularization in pixel coordinates.

Straight-wall hypotheses compete with the observed outline. Curved outlines,
courtyards, narrow passages and neighboring components have explicit guards.
This is a geometry prior, not recovery of an unknown architect's intention.
No image-specific coordinates, training palette or fixed global orientation.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .geometry import components, holes, repair_component_local


def _contour(mask):
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(contours, key=cv2.contourArea)[:, 0].astype(np.float64) if contours else np.empty((0, 2))


def _render(points, shape):
    out = np.zeros(shape, np.uint8)
    if len(points) >= 3 and np.isfinite(points).all():
        # Fixed point drawing avoids prematurely rounding fitted intersections.
        cv2.fillPoly(out, [np.rint(np.asarray(points) * 256).astype(np.int32)], 1, shift=8)
    return out.astype(bool)


def _width(mask):
    # Twice the upper interior distance is a wall/strip scale even for an L/U.
    d = cv2.distanceTransform(np.pad(mask.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    vals = d[mask]
    return max(1.0, float(np.percentile(vals, 85)) * 2.0 - 1.0) if len(vals) else 1.0


def _frame(points):
    contour = points.astype(np.float32).reshape(-1, 1, 2)
    # Estimate orientation above pixel-jitter scale. With a fixed sub-pixel
    # epsilon, a blurred rotated wall degenerates into horizontal stair steps.
    epsilon = max(0.9, min(4.0, cv2.arcLength(contour, True) * 0.006))
    p = cv2.approxPolyDP(contour, epsilon, True)[:, 0]
    edges = np.roll(p, -1, axis=0) - p
    lengths = np.linalg.norm(edges, axis=1)
    angles = np.arctan2(edges[:, 1], edges[:, 0])
    if not len(lengths) or lengths.max() < 1:
        return 0.0, 0.0
    seed = angles[lengths.argmax()]
    deviations = np.abs((angles - seed + np.pi / 4) % (np.pi / 2) - np.pi / 4)
    aligned = deviations < np.deg2rad(13)
    weights = lengths[aligned] ** 2
    theta = math.atan2(float(np.sum(weights * np.sin(4 * angles[aligned]))),
                       float(np.sum(weights * np.cos(4 * angles[aligned])))) / 4
    if abs(theta) < np.deg2rad(0.45):
        theta = 0.0
    coherence = float(lengths[aligned].sum() / max(lengths.sum(), 1))
    return theta, coherence


def _aligned_mask(mask, theta):
    c, s = math.cos(theta), math.sin(theta)
    rot = np.array([[c, s], [-s, c]], np.float64)
    h, w = mask.shape
    corners = np.array([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]]) @ rot.T
    low, high = np.floor(corners.min(axis=0)) - 3, np.ceil(corners.max(axis=0)) + 3
    affine = np.column_stack((rot, -low))
    out = cv2.warpAffine(mask.astype(np.uint8), affine, tuple((high - low + 1).astype(int)), flags=cv2.INTER_NEAREST)
    return out.astype(bool), rot, low


def _profiles(mask):
    columns = np.flatnonzero(mask.any(axis=0))
    rows = np.flatnonzero(mask.any(axis=1))
    if not len(columns) or not len(rows):
        return None
    top = np.argmax(mask[:, columns], axis=0).astype(float)
    bottom = mask.shape[0] - 1 - np.argmax(mask[::-1, columns], axis=0)
    left = np.argmax(mask[rows], axis=1).astype(float)
    right = mask.shape[1] - 1 - np.argmax(mask[rows, ::-1], axis=1)
    return columns, top, bottom.astype(float), rows, left, right.astype(float)


def _middle(values, fraction=0.16):
    n = len(values)
    trim = int(n * fraction)
    return values[trim:n - trim] if trim and n > 2 * trim else values


def _coherent_curve(aligned, points, width):
    """Detect sustained shared bowing, plus well supported ellipse/circle outlines."""
    p = _profiles(aligned)
    if p is None:
        return False
    for axis, a, b in ((p[0], p[1], p[2]), (p[3], p[4], p[5])):
        if len(axis) < max(24, width * 2.5):
            continue
        x, a, b = map(_middle, (axis, a, b))
        x = (x - x.mean()) / max(float(np.ptp(x)), 1)
        fa, fb = np.polyval(np.polyfit(x, a, 2), x), np.polyval(np.polyfit(x, b, 2), x)
        chord_a = np.linspace(fa[0], fa[-1], len(fa))
        chord_b = np.linspace(fb[0], fb[-1], len(fb))
        bow_a, bow_b = fa - chord_a, fb - chord_b
        sag = min(float(np.max(np.abs(bow_a))), float(np.max(np.abs(bow_b))))
        noise = max(float(np.sqrt(np.mean((a - fa) ** 2))), float(np.sqrt(np.mean((b - fb) ** 2))))
        same_bend = float(np.sum(bow_a * bow_b)) > 0
        if sag > max(1.5, width * 0.12) and noise < sag * 0.65 and same_bend:
            return True
    if len(points) >= 20:
        ellipse = cv2.fitEllipse(points.astype(np.float32).reshape(-1, 1, 2))
        ea, eb = ellipse[1]
        if min(ea, eb) >= 8 and max(ea, eb) / min(ea, eb) < 5:
            # Ellipse parameters above are in unaligned coordinates; compare area
            # and normalized contour residual there, not mismatched raster frames.
            angle = math.radians(ellipse[2])
            r = np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]])
            q = (points - ellipse[0]) @ r.T / np.array([ea / 2, eb / 2])
            residual = np.abs(np.linalg.norm(q, axis=1) - 1)
            area_ratio = cv2.contourArea(points.astype(np.float32)) / (math.pi * ea * eb / 4)
            if np.percentile(residual, 90) < 0.045 and 0.93 < area_ratio < 1.07:
                return True
    return False


def _rectangle(aligned, rot, low, shape, source_mask=None):
    p = _profiles(aligned)
    if p is None:
        return np.zeros(shape, bool)
    _, top, bottom, _, left, right = p
    x0, x1 = float(np.median(_middle(left))), float(np.median(_middle(right)))
    y0, y1 = float(np.median(_middle(top))), float(np.median(_middle(bottom)))
    if source_mask is not None:
        # The aligned raster is only an initial hypothesis. Fitting and drawing
        # through a second raster rotation displaces oblique walls by a pixel.
        # Refine on the original contour, then classify original pixel centers.
        points = _contour(source_mask)
        width = _width(source_mask)
        bounds = np.array([x0, y0, x1, y1]) + np.tile(low, 2)
        q = points @ rot.T
        theta = math.atan2(rot[0, 1], rot[0, 0])
        selections, angles, weights = [], [], []
        for axis, index, otherlo, otherhi in ((0, 0, 1, 3), (0, 2, 1, 3), (1, 1, 0, 2), (1, 3, 0, 2)):
            other = 1 - axis
            margin = (bounds[otherhi] - bounds[otherlo]) * .13
            selected = ((np.abs(q[:, axis] - bounds[index]) < max(2, width * .15))
                        & (q[:, other] > bounds[otherlo] + margin)
                        & (q[:, other] < bounds[otherhi] - margin))
            selections.append((axis, index, selected))
            if selected.sum() < 8:
                continue
            vx, vy, _, _ = cv2.fitLine(points[selected].astype(np.float32), cv2.DIST_HUBER, 0, .001, .001).ravel()
            angle = math.atan2(float(vy), float(vx))
            deviation = abs((angle - theta + np.pi / 4) % (np.pi / 2) - np.pi / 4)
            if deviation < np.deg2rad(3):
                angles.append(angle)
                weights.append(float(np.ptp(q[selected, other])) ** 2)
        if angles:
            refined = math.atan2(float(np.sum(np.array(weights) * np.sin(np.array(angles) * 4))),
                                 float(np.sum(np.array(weights) * np.cos(np.array(angles) * 4)))) / 4
            # Keep the same axis family when crossing -45/+45 degrees.
            theta += (refined - theta + np.pi / 4) % (np.pi / 2) - np.pi / 4
        rot = np.array([[math.cos(theta), math.sin(theta)], [-math.sin(theta), math.cos(theta)]])
        q = points @ rot.T
        for axis, index, selected in selections:
            if selected.sum() >= 4:
                bounds[index] = np.median(q[selected, axis])
        yy, xx = np.indices(shape)
        u, v = xx * rot[0, 0] + yy * rot[0, 1], xx * rot[1, 0] + yy * rot[1, 1]
        return (u >= bounds[0] - .5) & (u <= bounds[2] + .5) & (v >= bounds[1] - .5) & (v <= bounds[3] + .5)
    points = (np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) + low) @ rot
    return _render(points, shape)


def _fit_polygon(mask, theta, tolerance):
    points = _contour(mask)
    if len(points) < 4:
        return mask.copy()
    epsilon = max(0.65, tolerance * 0.43)
    poly = cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), epsilon, True)[:, 0].astype(float)
    if not 3 <= len(poly) <= 256:
        return mask.copy()
    # Recover the original contour samples underlying each simplified edge.
    indices = [int(np.argmin(np.sum((points - vertex) ** 2, axis=1))) for vertex in poly]
    lines = []
    for i, start in enumerate(indices):
        end = indices[(i + 1) % len(indices)]
        samples = points[start:end + 1] if end > start else np.concatenate((points[start:], points[:end + 1]))
        if len(samples) < 2:
            continue
        vx, vy, px, py = map(float, cv2.fitLine(samples.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
        direction = math.atan2(vy, vx)
        snapped = theta + round((direction - theta) / (np.pi / 2)) * np.pi / 2
        deviation = abs((direction - snapped + np.pi / 2) % np.pi - np.pi / 2)
        normal_raw = np.array([-vy, vx])
        residual = float(np.sqrt(np.mean(((samples - [px, py]) @ normal_raw) ** 2)))
        supported_diagonal = deviation > np.deg2rad(4) and len(samples) >= max(10, tolerance * 3) and residual < 0.6
        if deviation < np.deg2rad(13) and not supported_diagonal:
            direction = snapped
        normal = np.array([-math.sin(direction), math.cos(direction)])
        # Ignore corner samples; the median is robust to small bites and spurs.
        central = _middle(samples, 0.12)
        offset = float(np.median(central @ normal))
        line = [normal, offset, poly[i], float(len(samples))]
        if lines and abs(float(np.dot(lines[-1][0], normal))) > 0.999:
            previous = lines[-1]
            sign = 1 if np.dot(previous[0], normal) >= 0 else -1
            weight = previous[3] + line[3]
            previous[1] = (previous[1] * previous[3] + sign * offset * line[3]) / weight
            previous[3] = weight
        else:
            lines.append(line)
    if len(lines) > 2 and abs(float(np.dot(lines[-1][0], lines[0][0]))) > 0.999:
        a, b = lines[-1], lines[0]
        sign = 1 if np.dot(a[0], b[0]) >= 0 else -1
        b[1] = (b[1] * b[3] + sign * a[1] * a[3]) / (a[3] + b[3])
        b[2] = a[2]
        lines.pop()
    vertices = []
    for i, line in enumerate(lines):
        prev = lines[i - 1]
        matrix = np.array([prev[0], line[0]])
        if abs(np.linalg.det(matrix)) < 0.08:
            return mask.copy()
        vertex = np.linalg.solve(matrix, [prev[1], line[1]])
        if np.linalg.norm(vertex - line[2]) > max(3, tolerance * 3):
            vertex = line[2]
        vertices.append(vertex)
    return _render(vertices, mask.shape)


def _hole_masks(mask, width, config, scale):
    labels, items = holes(mask)
    pinholes, protected = np.zeros_like(mask), []
    limit = max(round(config.max_hole_area * scale * scale), width * width * 0.008) if config.max_hole_area else 0
    for index, area in items:
        region = labels == index
        ys, xs = np.nonzero(region)
        # Small raster stair-step pockets along an oblique wall are not
        # rectangular courtyards merely because their bounding box is compact.
        regular_small_opening = area >= 9 and area / ((np.ptp(xs) + 1) * (np.ptp(ys) + 1)) > 0.95
        if area <= limit and not regular_small_opening:
            pinholes |= region
        else:
            protected.append(region)
    return pinholes, protected


def _has_diagonal(points, theta, width):
    poly = cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), 0.75, True)[:, 0]
    edges = np.roll(poly, -1, axis=0) - poly
    lengths = np.linalg.norm(edges, axis=1)
    angles = np.arctan2(edges[:, 1], edges[:, 0])
    deviation = np.abs((angles - theta + np.pi / 4) % (np.pi / 2) - np.pi / 4)
    diagonals = (lengths > max(10, width * 0.8)) & (deviation > np.deg2rad(4))
    return bool(np.count_nonzero(diagonals) >= 2 and lengths[diagonals].sum() > lengths.sum() * 0.15)


def _structural_protrusion(mask, rectangle, width):
    """A substantial wing of an L/T is not a removable thin burr."""
    removed = mask & ~rectangle
    n, labels, stats, _ = components(removed)
    for index in range(1, n):
        part = labels == index
        if stats[index, cv2.CC_STAT_AREA] < max(9, width * width * 0.15):
            continue
        distance = cv2.distanceTransform(part.astype(np.uint8), cv2.DIST_L2, 5)
        if distance.max() * 2 - 1 > max(3, width * 0.60):
            return True
    return False


def _structural_voids(mask, width, tolerance):
    """Deep exterior-connected recesses include narrow passages, even when their
    area is small. Unlike pinholes these must not disappear under closing."""
    outline = _contour(mask)
    hull = _render(cv2.convexHull(outline.astype(np.float32))[:, 0], mask.shape)
    depth = cv2.distanceTransform(hull.astype(np.uint8), cv2.DIST_L2, 5)
    n, labels, _, _ = components(hull & ~mask)
    hole_labels, enclosed = holes(mask)
    hole_ids = {i for i, _ in enclosed}
    result = np.zeros_like(mask)
    for index in range(1, n):
        part = labels == index
        if set(np.unique(hole_labels[part])).issubset(hole_ids):
            continue
        if depth[part].max() > max(width * 0.9, 3):
            result |= part
    return result


def _validate(original, proposed, forbidden, protected, tolerance, budget, spur_allowance=1.0):
    area = int(original.sum())
    changes = int(np.count_nonzero(original != proposed))
    if not changes:
        return True, "unchanged"
    if changes / max(area, 1) > budget:
        return False, "change_budget"
    if np.any(proposed & ~original & forbidden):
        return False, "neighbor_gap"
    if components(proposed)[0] != 2:
        return False, "component_connectivity"
    # Maximum support displacement, in addition to total area-change budget.
    da = cv2.distanceTransform((~original).astype(np.uint8), cv2.DIST_L2, 5)
    dr = cv2.distanceTransform((~proposed).astype(np.uint8), cv2.DIST_L2, 5)
    if np.any(da[proposed & ~original] > tolerance + 0.8) or np.any(dr[original & ~proposed] > tolerance * spur_allowance + 0.8):
        return False, "boundary_displacement"
    new_labels, new_holes = holes(proposed)
    hole_ids = {index for index, _ in new_holes}
    seen = set()
    for region in protected:
        overlaps = new_labels[region]
        ids, counts = np.unique(overlaps[overlaps > 0], return_counts=True)
        if not len(ids):
            return False, "courtyard_filled"
        match = int(ids[np.argmax(counts)])
        if match not in hole_ids or match in seen:
            return False, "courtyard_opened_or_merged"
        seen.add(match)
    if len(hole_ids - seen):
        return False, "passage_closed"
    return True, "accepted"


def fragment_candidates(objects, stats, config, scale):
    if not config.remove_fragments or not config.repair_geometry or not config.defect_radius or config.geometry_mode != "regularize":
        return {}, {}
    areas = stats[1:, cv2.CC_STAT_AREA].astype(float)
    reference = areas[areas >= 9]
    if not len(reference):
        return {}, {"reason": "no_reliable_size_reference"}
    # Estimate the ordinary-building scale from the upper half, so a cluster of
    # tiny debris does not itself lower the deletion threshold to almost zero.
    substantial = (areas >= 9) & (areas >= np.median(reference))
    typical_area = float(np.median(areas[substantial]))
    widths = np.minimum(stats[1:, cv2.CC_STAT_WIDTH], stats[1:, cv2.CC_STAT_HEIGHT])[substantial]
    typical_width = float(np.median(widths))
    limit = max(4.0 * scale * scale, 4.0, min(typical_area * config.fragment_area_ratio, typical_width ** 2 * 0.22))
    rejected = {}
    for index in range(1, len(stats)):
        x, y, w, h, area = map(int, stats[index])
        if area > limit:
            continue
        mask = objects[y:y + h, x:x + w] == index
        if area <= max(4, round(4 * scale * scale)):
            rejected[index] = {"reason": "isolated_pixel_speck", "area_px": area}
            continue
        # Long, clean one-pixel strips are not specks. Size alone must not
        # remove small legitimate structures next to a large building.
        if area > 2 and max(w, h) / max(min(w, h), 1) >= 6 and area / (w * h) > 0.85:
            continue
        outline = _contour(mask)
        if len(outline) >= 3:
            _, (rw, rh), _ = cv2.minAreaRect(outline.astype(np.float32))
            fill = area / max((rw + 1) * (rh + 1), 1)
            thinness = min(rw, rh) + 1
            if area >= 9 and (max(rw, rh) + 1) / thinness >= 6 and fill > 0.6:
                continue
            if area >= 4 and fill > 0.82 and thinness >= 2:
                continue
        else:
            fill, thinness = 0.0, 1.0
        irregular = fill < 0.72
        subpixel_speck = area <= max(2, round(2 * scale * scale))
        too_thin = thinness < max(1.5, typical_width * 0.18)
        if subpixel_speck or irregular or too_thin:
            rejected[index] = {"reason": "isolated_fragment", "area_px": area,
                               "rectangle_fill": round(float(fill), 3), "width_px": round(float(thinness), 2)}
    return rejected, {"typical_component_area_px": round(typical_area, 2),
                      "typical_component_width_px": round(typical_width, 2),
                      "fragment_area_limit_px": round(limit, 2)}


def regularize_component(mask, forbidden, config, scale, diagnostics=None):
    info = diagnostics if diagnostics is not None else {}
    points = _contour(mask)
    if len(points) < 4 or mask.sum() < 9:
        info.update(shape="small_preserved", review_required=False)
        return mask.copy(), []
    width = _width(mask)
    theta, coherence = _frame(points)
    tolerance = max(0.8, width * config.boundary_tolerance_ratio * config.defect_radius)
    info.update(shape="polygon", orientation_degrees=round(math.degrees(theta), 3),
                axis_support=round(coherence, 3), wall_width_px=round(width, 2),
                tolerance_px=round(tolerance, 2), review_required=False)
    if width < 2.5:
        info["shape"] = "thin_preserved"
        return mask.copy(), []
    if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
        proposed, events = repair_component_local(mask, forbidden, config, scale)
        info.update(shape="frame_clipped_preserved", review_required=True)
        return proposed, events + ["frame_clipped_geometry_review"]
    pinholes, protected = _hole_masks(mask, width, config, scale)
    passages = _structural_voids(mask, width, tolerance)
    filled = mask.copy()
    for hole in protected:
        filled |= hole
    filled |= pinholes
    aligned, rot, low = _aligned_mask(filled, theta)
    if _coherent_curve(aligned, points, width):
        # A low-radius local pass keeps coherent curved structure. Do not force a
        # noisy curve into either a rectangle or a perfectly circular building.
        proposed, events = repair_component_local(mask, forbidden, config, scale)
        info.update(shape="coherent_curve", review_required=False)
        return proposed, events + ["coherent_curve_preserved"]
    candidates = []
    rectangle = _rectangle(aligned, rot, low, mask.shape, filled)
    union = int((rectangle | filled).sum())
    rect_iou = int((rectangle & filled).sum()) / max(union, 1)
    info["rectangle_iou"] = round(rect_iou, 4)
    diagonal = _has_diagonal(points, theta, width)
    if diagonal:
        # Preserve supported angled walls before any oriented morphology could
        # create short horizontal/vertical steps along those walls.
        candidates.append(("free_angle_polygon", _fit_polygon(filled, theta, min(tolerance, 1.5))))
    wing = _structural_protrusion(mask, rectangle, width)
    info["structural_wing_preserved"] = wing
    supported_rectangle = (coherence > 0.80 and rect_iou >= 0.82) or (coherence > 0.60 and rect_iou >= 0.87)
    if supported_rectangle and not diagonal and not wing:
        candidates.append(("rectangle", rectangle))
    # Mild oriented morphology removes sub-wall-scale burrs before fitting the
    # remaining structural turns. It is always checked against the input mask.
    radius = max(0, min(int(tolerance * 0.5), int(width // 5)))
    base = aligned.astype(np.uint8)
    if radius:
        kernel = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
        base = cv2.morphologyEx(base, cv2.MORPH_CLOSE, kernel)
        base = cv2.morphologyEx(base, cv2.MORPH_OPEN, kernel)
    # Fit in the original coordinate system, retaining arbitrary-angle edges.
    aligned_points = _contour(base.astype(bool))
    smooth_mask = _render((aligned_points + low) @ rot, mask.shape)
    candidates.append(("wall_polygon", _fit_polygon(smooth_mask, theta, tolerance)))
    candidates.append(("wall_polygon_conservative", _fit_polygon(filled, theta, max(0.8, tolerance * 0.45))))
    reasons = []
    for kind, outer in candidates:
        proposed = outer.copy()
        proposed[passages] = False
        for hole in protected:
            # Internal voids keep their identity; fit their walls with a smaller
            # tolerance. Fall back to original voids if topology becomes invalid.
            hole_outline = _contour(hole)
            hole_theta, support = _frame(hole_outline)
            regular_hole = _fit_polygon(hole, hole_theta, min(tolerance * 0.65, _width(hole) * 0.2)) if support > 0.8 else hole
            proposed[regular_hole] = False
        # Four-wall reconstruction can bridge a deeper bite than the local
        # polygon pass, but only with high axis support and >= .82 mask IoU.
        # Deep open passages were restored above, and area/gap guards still apply.
        candidate_tolerance = tolerance * 2 if kind == "rectangle" else tolerance
        spur_allowance = 1.6 if kind == "rectangle" else 1.0
        valid, reason = _validate(mask, proposed, forbidden, protected, candidate_tolerance, config.regularization_max_change_ratio, spur_allowance)
        if not valid and protected:
            proposed = outer.copy()
            proposed[passages] = False
            for hole in protected:
                proposed[hole] = False
            valid, reason = _validate(mask, proposed, forbidden, protected, candidate_tolerance, config.regularization_max_change_ratio, spur_allowance)
        if valid:
            info.update(shape=kind, rejected_candidates=reasons, accepted_tolerance_px=round(candidate_tolerance, 2))
            changed = int(np.count_nonzero(mask != proposed))
            info["changed_area_ratio"] = round(changed / max(int(mask.sum()), 1), 5)
            add_distance = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)
            remove_distance = cv2.distanceTransform((~proposed).astype(np.uint8), cv2.DIST_L2, 5)
            info["max_added_support_distance_px"] = round(float(add_distance[proposed & ~mask].max()), 3) if np.any(proposed & ~mask) else 0.0
            info["max_removed_support_distance_px"] = round(float(remove_distance[mask & ~proposed].max()), 3) if np.any(mask & ~proposed) else 0.0
            events = ["footprint_regularized"] if changed else []
            if pinholes.any() and np.any(proposed & pinholes):
                events.append("pinholes_repaired")
            return proposed, events
        reasons.append({"candidate": kind, "guard": reason})
    proposed, events = repair_component_local(mask, forbidden, config, scale)
    info.update(shape="guarded_original", rejected_candidates=reasons, review_required=True)
    return proposed, events + ["geometry_review_required"]
