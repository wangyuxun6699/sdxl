"""Geometry regression cases with known masks, independent of the user's PNGs."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.postprocessing import PostprocessConfig, process_image


def image(mask, color=(75, 173, 111)):
    rgb = np.full((*mask.shape, 3), 255, np.uint8)
    rgb[mask] = color
    return rgb


def iou(a, b):
    return int((a & b).sum()) / max(int((a | b).sum()), 1)


class RegularizationV2Tests(unittest.TestCase):
    def test_bites_and_spurs_improve_over_v1_geometry(self):
        truth = np.zeros((220, 300), bool)
        truth[60:120, 40:230] = True
        flawed = truth.copy()
        flawed[60:67, 80:99] = False
        flawed[112:120, 170:182] = False
        flawed[120:130, 110:117] = True
        flawed[82:84, 150:152] = False
        v1 = process_image(image(flawed), PostprocessConfig(geometry_mode="local"))
        v2 = process_image(image(flawed))
        self.assertGreater(iou(v2.foreground, truth), iou(v1.foreground, truth) + 0.015)
        self.assertGreater(iou(v2.foreground, truth), 0.995)

    def test_irregular_island_removed_but_small_square_and_strip_preserved(self):
        m = np.zeros((260, 340), bool)
        m[20:100, 20:100] = True
        m[20:100, 140:220] = True
        m[150:154, 20:24] = True  # legitimate 4 x 4 building
        m[150:153, 70:78] = True
        m[153:158, 70:73] = True  # isolated L-shaped 39px residue
        m[190, 30:100] = True  # legitimate thin linear structure
        m[230, 320] = True
        out = process_image(image(m))
        self.assertTrue(out.foreground[150:154, 20:24].all())
        self.assertFalse(out.foreground[150:158, 70:78].any())
        self.assertTrue(out.foreground[190, 30:100].all())
        self.assertFalse(out.foreground[230, 320])

    def test_deep_open_slit_keeps_its_entrance(self):
        m = np.zeros((200, 220), bool)
        m[35:140, 35:180] = True
        m[35:116, 91:94] = False
        out = process_image(image(m))
        self.assertFalse(out.foreground[35:116, 91:94].any())
        self.assertTrue(out.foreground[125, 92])

    def test_coherent_curved_strip_is_not_straightened(self):
        m = np.zeros((220, 280), bool)
        for x in range(30, 250):
            top = round(65 + 0.002 * (x - 140) ** 2)
            m[top:top + 20, x] = True
        out = process_image(image(m))
        self.assertGreater(iou(m, out.foreground), 0.995)
        self.assertEqual(out.report["components"][0]["geometry"]["shape"], "coherent_curve")
        self.assertFalse(out.foreground[70, 35])
        self.assertTrue(out.foreground[70, 140])

    def test_circular_courtyard_stays_circular(self):
        m = np.zeros((230, 230), np.uint8)
        cv2.circle(m, (115, 115), 75, 1, -1)
        cv2.circle(m, (115, 115), 40, 0, -1)
        out = process_image(image(m.astype(bool)))
        self.assertGreater(iou(m.astype(bool), out.foreground), 0.995)
        self.assertFalse(out.foreground[115, 115])
        self.assertTrue(out.foreground[115, 55])

    def test_rotated_building_keeps_its_angle(self):
        m = np.zeros((250, 280), np.uint8)
        points = cv2.boxPoints(((140, 125), (160, 35), 23))
        cv2.fillPoly(m, [np.rint(points).astype(np.int32)], 1)
        out = process_image(image(m.astype(bool)))
        self.assertGreater(iou(m.astype(bool), out.foreground), 0.97)
        self.assertAlmostEqual(out.report["components"][0]["geometry"]["orientation_degrees"], 23, delta=1)

    def test_supported_trapezoid_sides_are_not_forced_square(self):
        m = np.zeros((240, 260), np.uint8)
        cv2.fillPoly(m, [np.array([[70, 45], [180, 45], [200, 175], [50, 175]], np.int32)], 1)
        out = process_image(image(m.astype(bool)))
        self.assertGreater(iou(m.astype(bool), out.foreground), 0.98)

    def test_off_and_explicit_mask_disable_fragment_deletion(self):
        m = np.zeros((180, 180), bool)
        m[20:120, 20:120] = True
        m[21, 60] = False
        m[160, 160] = True
        rgb = image(m)
        for cfg in (PostprocessConfig(geometry_mode="off"), PostprocessConfig(defect_radius=0), PostprocessConfig(repair_geometry=False)):
            out = process_image(rgb, cfg)
            np.testing.assert_array_equal(out.foreground, m)
        out = process_image(rgb, foreground_mask=m)
        np.testing.assert_array_equal(out.foreground, m)

    def test_multiple_height_parts_survive_geometry_reconstruction(self):
        m = np.zeros((220, 240), bool)
        m[50:130, 30:210] = True
        rgb = image(m, (170, 90, 60))
        rgb[50:130, 135:210] = (90, 55, 150)
        rgb[50:55, 70:80] = 255
        out = process_image(rgb)
        np.testing.assert_array_equal(out.cleaned[90, 80], [170, 90, 60])
        np.testing.assert_array_equal(out.cleaned[90, 170], [90, 55, 150])
        self.assertTrue(out.foreground[50:55, 70:80].all())
        self.assertTrue(np.isnan(out.height_m[out.foreground]).all())

    def test_results_and_geometry_diagnostics_are_deterministic(self):
        m = np.zeros((160, 240), bool)
        m[30:80, 40:210] = True
        m[29:31, 90] = True
        a, b = process_image(image(m)), process_image(image(m))
        np.testing.assert_array_equal(a.cleaned, b.cleaned)
        self.assertEqual(a.report["components"], b.report["components"])

    def test_removed_speck_inside_bite_does_not_block_or_undo_refill(self):
        truth = np.zeros((210, 270), bool)
        truth[45:130, 30:230] = True
        flawed = truth.copy()
        flawed[45:53, 88:110] = False
        flawed[48, 98] = True  # disconnected residue inside the missing wall
        out = process_image(image(flawed))
        self.assertEqual(out.report["counts"]["fragments_removed"], 1)
        self.assertTrue(out.foreground[45:53, 88:110].all())
        self.assertGreater(iou(out.foreground, truth), 0.995)

    def test_shared_color_wall_is_straightened_without_a_seam_or_lost_tower(self):
        m = np.zeros((190, 250), bool)
        m[20:170, 20:230] = True
        rgb = image(m, (180, 80, 50))
        for y in range(20, 170):
            boundary = 125 + (1 if (y // 3) % 2 else -1)
            rgb[y, boundary:230] = (65, 50, 155)
        rgb[60:64, 50:54] = (30, 110, 150)
        out = process_image(rgb)
        self.assertGreater(out.report["counts"]["shared_boundaries_regularized"], 0)
        np.testing.assert_array_equal(out.foreground, m)
        np.testing.assert_array_equal(out.cleaned[60:64, 50:54], rgb[60:64, 50:54])
        seam = np.argmax(np.all(out.cleaned[30:160] == [65, 50, 155], axis=2), axis=1)
        self.assertLessEqual(int(np.ptp(seam)), 1)
        self.assertTrue((out.region_ids[m] > 0).all())

    def test_zero_hole_budget_preserves_even_a_single_pixel_opening(self):
        m = np.zeros((200, 230), bool)
        m[25:165, 30:195] = True
        m[80, 90] = False
        out = process_image(image(m), PostprocessConfig(max_hole_area=0))
        self.assertFalse(out.foreground[80, 90])

    def test_blurred_rotated_wall_does_not_acquire_white_fill_pixels(self):
        m = np.zeros((240, 300), np.uint8)
        cv2.fillPoly(m, [np.rint(cv2.boxPoints(((150, 120), (180, 60), 24))).astype(np.int32)], 1)
        flawed = m.astype(bool)
        flawed[95:102, 92:106] = False
        rgb = cv2.GaussianBlur(image(flawed, (65, 120, 180)), (5, 5), 0.8)
        out = process_image(rgb)
        core = cv2.erode(out.foreground.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        self.assertGreater(iou(out.foreground, m.astype(bool)), 0.90)
        self.assertLess(float(np.percentile(out.cleaned[core].mean(axis=1), 99)), 150)

    def test_multiscale_boundary_quality_and_clipped_building_guard(self):
        from backend.scripts.validate_postprocess_v2 import synthetic_benchmark
        with tempfile.TemporaryDirectory() as folder:
            records = synthetic_benchmark(Path(folder))
        self.assertEqual(len(records), 15)
        for row in records:
            with self.subTest(scale=row["scale"], angle=row["angle_deg"]):
                self.assertGreaterEqual(row["v2_boundary_iou"], row["local_boundary_iou"] - 1e-6)
                self.assertGreaterEqual(row["v2_mask_iou"], row["local_mask_iou"] - 1e-6)


if __name__ == "__main__":
    unittest.main()
