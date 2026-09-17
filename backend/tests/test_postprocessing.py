"""Regression tests for preservation and offline use; no model weights needed."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from backend.postprocessing import PostprocessConfig, load_config, process_file, process_image
from backend.postprocessing.files import load_rgb, sha256_file
from backend.postprocessing.scene import load_scene_fields, scene_fingerprint


def canvas(h=180, w=240):
    return np.full((h, w, 3), 255, dtype=np.uint8)


class CoreTests(unittest.TestCase):
    def test_noise_is_reduced_without_new_height(self):
        image = canvas()
        color = np.array([70, 180, 110])
        rng = np.random.default_rng(32)
        image[30:140, 30:200] = np.clip(color + rng.normal(0, 2, (110, 170, 3)), 0, 255).astype(np.uint8)
        result = process_image(image)
        old_error = np.abs(image[40:130, 40:190].astype(float) - color).mean()
        new_error = np.abs(result.cleaned[40:130, 40:190].astype(float) - color).mean()
        self.assertLess(new_error, old_error * 0.7)
        self.assertTrue(np.isnan(result.height_m[result.foreground]).all())

    def test_touching_color_parts_and_small_tower_are_preserved(self):
        image = canvas()
        image[20:160, 20:120] = [80, 200, 120]
        image[20:160, 120:220] = [30, 76, 46]
        image[50:54, 55:59] = [21, 52, 31]  # intact 4x4 tower on a large podium
        result = process_image(image)
        self.assertEqual(result.report["counts"]["components_after"], 1)
        self.assertEqual(result.report["counts"]["color_regions"], 3)
        np.testing.assert_array_equal(result.cleaned, image)

    def test_no_fixed_six_color_limit(self):
        image = canvas(140, 380)
        colors = [(180, 20, 30), (20, 180, 30), (30, 30, 180), (150, 80, 190), (180, 170, 20),
                  (20, 150, 160), (60, 60, 60), (230, 130, 100), (80, 180, 230)]
        for i, color in enumerate(colors):
            image[30:110, 10 + i * 40:50 + i * 40] = color
        result = process_image(image)
        self.assertEqual(result.report["counts"]["color_regions"], 9)
        np.testing.assert_array_equal(result.cleaned, image)

    def test_non_green_and_neutral_foreground(self):
        for color in ((40, 70, 160), (140, 55, 175), (40, 40, 40), (190, 90, 60)):
            with self.subTest(color=color):
                image = canvas()
                image[30:100, 60:140] = color
                result = process_image(image)
                self.assertEqual(int(result.foreground.sum()), 70 * 80)
                np.testing.assert_array_equal(result.cleaned, image)

    def test_gap_courtyard_and_thin_building(self):
        image = canvas()
        image[20:110, 20:90] = [60, 155, 90]
        image[40:75, 40:70] = 255
        image[20:110, 91:150] = [60, 155, 90]  # one-pixel gap
        image[135:136, 30:100] = [60, 155, 90]  # thin valid strip
        result = process_image(image)
        self.assertEqual(result.report["counts"]["components_after"], 3)
        self.assertFalse(result.foreground[40:75, 40:70].any())
        self.assertFalse(result.foreground[20:110, 90].any())
        self.assertTrue(result.foreground[135, 30:100].all())

    def test_local_defects_repaired_with_small_budget(self):
        image = canvas(1024, 1024)
        image[100:200, 100:240] = [70, 180, 110]
        image[100, 150] = 255  # shallow notch
        image[150, 150] = 255  # isolated pinhole
        image[150, 99] = [70, 180, 110]  # one-pixel spur
        result = process_image(image)
        self.assertTrue(result.foreground[100, 150])
        self.assertTrue(result.foreground[150, 150])
        self.assertFalse(result.foreground[150, 99])
        self.assertLessEqual(result.report["counts"]["geometry_changed_px"], 5)

    def test_open_u_and_l_shapes_not_rectangularized(self):
        image = canvas()
        image[30:130, 30:45] = [80, 170, 105]
        image[115:130, 30:115] = [80, 170, 105]
        image[30:130, 100:115] = [80, 170, 105]
        image[30:100, 155:175] = [80, 170, 105]
        image[80:100, 155:215] = [80, 170, 105]
        result = process_image(image)
        np.testing.assert_array_equal(result.cleaned, image)

    def test_thin_courtyard_wall_is_not_opened(self):
        image = canvas(1024, 1024)
        image[80:300, 80:300] = [70, 150, 90]
        image[81:230, 120:220] = 255  # courtyard with a one-pixel top wall
        original = np.any(image != 255, axis=2)
        result = process_image(image)
        self.assertTrue(result.foreground[80, 120:220].all())
        self.assertFalse(result.foreground[81:230, 120:220].any())
        self.assertEqual(cv2.connectedComponents(original.astype(np.uint8))[0],
                         cv2.connectedComponents(result.foreground.astype(np.uint8))[0])

    def test_gradient_is_flagged_instead_of_confident_height_bands(self):
        image = canvas()
        for x in range(25, 215):
            image[30:150, x] = [50, 110 + int((x - 25) * 0.48), 75]
        result = process_image(image)
        self.assertGreater(result.review_mask.sum(), 1000)
        np.testing.assert_array_equal(result.cleaned[result.review_mask], image[result.review_mask])

    def test_explicit_mask_is_authoritative(self):
        image = canvas()
        mask = np.zeros(image.shape[:2], bool)
        mask[30:120, 40:140] = True
        mask[40, 50] = False
        image[mask] = [249, 249, 249]
        result = process_image(image, foreground_mask=mask)
        np.testing.assert_array_equal(result.foreground, mask)

    def test_empty_is_valid_and_deterministic(self):
        image = canvas()
        a, b = process_image(image), process_image(image)
        self.assertEqual(a.report["counts"]["color_regions"], 0)
        np.testing.assert_array_equal(a.cleaned, b.cleaned)
        self.assertEqual(a.report["cleaned_pixel_sha256"], b.report["cleaned_pixel_sha256"])

    def test_invalid_configs_and_shapes(self):
        for values in ({"mode": "palette"}, {"color_delta": float("nan")}, {"defect_radius": -1},
                       {"repair_geometry": "false"}, {"unknown_key": 1}):
            with self.subTest(values=values), self.assertRaises((ValueError, TypeError)):
                load_config(**values)
        with self.assertRaises(ValueError):
            process_image(np.zeros((4, 4), np.uint8))
        with self.assertRaises(ValueError):
            process_image(canvas(), PostprocessConfig(max_pixels=10))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.image = canvas()
        self.image[20:120, 20:110] = [80, 200, 120]
        self.image[20:120, 110:220] = [40, 70, 170]
        self.source = self.directory / "规划输入.png"
        Image.fromarray(self.image).save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_bundle_raw_bytes_labels_and_unknown_heights(self):
        before = sha256_file(self.source)
        out = self.directory / "结果"
        data = process_file(self.source, out)
        self.assertEqual(before, sha256_file(self.source))
        self.assertEqual(before, sha256_file(out / "source.png"))
        self.assertEqual(data["report"]["height_source"], "unknown")
        with np.load(out / "fields.npz", allow_pickle=False) as fields:
            self.assertTrue(np.isnan(fields["height_m"][fields["foreground"]]).all())
            self.assertEqual(set(np.unique(fields["region_ids"])), {0, 1, 2})
        for name in data["report"]["files"]:
            self.assertTrue((out / name).is_file(), name)
        with self.assertRaises(FileExistsError):
            process_file(self.source, out)
        process_file(self.source, out, overwrite=True)

    def test_palette_unknowns_stay_unknown_and_scene_is_explicit(self):
        config = PostprocessConfig(mode="palette", colors=[{"rgb": [80, 200, 120], "height_m": 24}])
        out = self.directory / "palette"
        process_file(self.source, out, config)
        scene = load_scene_fields(out / "cleaned.png")
        self.assertEqual(float(scene.proxy_height[40, 40]), 24)
        self.assertEqual(float(scene.proxy_height[40, 160]), 12)
        self.assertGreater(scene.metadata["unknown_height_pixels"], 0)
        self.assertGreater(len(scene.metadata["warnings"]), 0)
        np.testing.assert_array_equal(load_rgb(out / "cleaned.png")[40, 160], [40, 70, 170])

    def test_stale_sidecar_is_rejected_and_cache_key_changes(self):
        out = self.directory / "bundle"
        process_file(self.source, out)
        cleaned = out / "cleaned.png"
        old = scene_fingerprint(cleaned)
        changed = self.image.copy()
        changed[50, 50] = [22, 22, 22]
        Image.fromarray(changed).save(cleaned)
        self.assertNotEqual(old, scene_fingerprint(cleaned))
        with self.assertRaisesRegex(ValueError, "stale"):
            load_scene_fields(cleaned)

    def test_alpha_grayscale_and_foreground_mask_size(self):
        alpha = np.zeros((40, 40, 4), dtype=np.uint8)
        alpha[10:30, 10:30] = [20, 40, 90, 255]
        transparent = self.directory / "透明.png"
        Image.fromarray(alpha).save(transparent)
        rgb = load_rgb(transparent)
        np.testing.assert_array_equal(rgb[0, 0], [255, 255, 255])
        self.assertEqual(int(process_image(rgb).foreground.sum()), 400)
        gray = self.directory / "gray.png"
        Image.new("L", (20, 20), 128).save(gray)
        self.assertEqual(load_rgb(gray).shape, (20, 20, 3))
        with self.assertRaises(ValueError):
            process_file(self.source, self.directory / "badmask", mask_path=gray)

    def test_cli_batch_collisions_errors_and_nested_output(self):
        source = self.directory / "inputs"
        source.mkdir()
        Image.fromarray(self.image).save(source / "same.png")
        Image.fromarray(self.image).save(source / "same.jpg")
        (source / "broken.png").write_bytes(b"not an image")
        output = source / "results"
        command = [sys.executable, str(ROOT / "scripts/postprocess_image.py"), "--input", str(source),
                   "--output", str(output), "--recursive"]
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertTrue((output / "same.png/cleaned.png").exists())
        self.assertTrue((output / "same.jpg/cleaned.png").exists())
        second = subprocess.run(command + ["--overwrite"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(second.returncode, 1)
        self.assertIn("2 succeeded, 1 failed", second.stdout)


class IntegrationTests(unittest.TestCase):
    def test_generation_stage_publishes_cleaned_and_keeps_source(self):
        from backend.app.postprocess_service import postprocess_generated_image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.png"
            image = canvas()
            image[20:120, 20:180] = [65, 160, 95]
            Image.fromarray(image).save(path)
            before = sha256_file(path)
            with patch.dict(os.environ, {"CITY_POSTPROCESS_CONFIG": ""}):
                bundle = postprocess_generated_image(str(path))
            self.assertEqual(sha256_file(bundle / "source.png"), before)
            scene = load_scene_fields(path)
            self.assertEqual(scene.metadata["source"], "saved_postprocess_bundle")

    @unittest.skipUnless(importlib.util.find_spec("plotly"), "Optional Plotly is needed for preview integration")
    def test_preview_and_analysis_share_saved_fields(self):
        from backend.scripts.spatial_analysis import run_spatial_analysis
        spec = importlib.util.spec_from_file_location("preview_under_test", ROOT / "scripts/2D23D.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "input.png"
            image = canvas(64, 80)
            image[10:50, 10:30] = [80, 200, 120]
            image[10:50, 30:60] = [30, 76, 46]
            image[25:35, 20:40] = 255
            Image.fromarray(image).save(source)
            config = PostprocessConfig(mode="palette", colors=[{"rgb": [80, 200, 120], "height_m": 9},
                                                              {"rgb": [30, 76, 46], "height_m": 30}])
            out = directory / "bundle"
            process_file(source, out, config)
            cleaned = str(out / "cleaned.png")
            scene = load_scene_fields(cleaned)
            module.generate_3d_html_preview(cleaned, str(directory / "preview.html"), "blue")
            summary = run_spatial_analysis(cleaned, str(directory / "analysis"), target_color="red")
            self.assertEqual(summary["postprocess"]["source_fingerprint"], scene.metadata["source_fingerprint"])
            self.assertEqual(summary["inputs"]["building_coverage_ratio"], round(float(scene.foreground.mean()), 4))
            self.assertEqual(float(scene.proxy_height[30, 25]), 0)
            self.assertEqual(float(scene.proxy_height[15, 15]), 9)
            self.assertEqual(float(scene.proxy_height[15, 45]), 30)
            self.assertTrue((directory / "preview.html").is_file())

    @unittest.skipUnless(all(importlib.util.find_spec(p) for p in ("plotly", "fastapi", "httpx")), "Optional web dependencies are needed for API integration")
    def test_mock_chat_cache_static_assets_and_delete(self):
        # All DB and output paths point to a temporary directory. No model or network.
        from backend.app import settings, database, generation_service, serializers, analysis_service, routes
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            paths = {"DB_PATH": Path(directory) / "database.db", "IMAGES_DIR": Path(directory) / "images",
                     "OUTPUTS_DIR": Path(directory) / "outputs", "ANALYSIS_DIR": Path(directory) / "analysis"}
            for module in (settings, database, generation_service, serializers, analysis_service, routes):
                for name, value in paths.items():
                    if hasattr(module, name):
                        stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.dict(os.environ, {"CITY_PLANNER_TEST_MODE": "1", "CITY_POSTPROCESS_CONFIG": ""}))
            from backend import main as main_module
            for name, value in paths.items():
                if hasattr(main_module, name):
                    stack.enter_context(patch.object(main_module, name, value))
            with TestClient(main_module.create_app()) as client:
                response = client.post("/chat", json={"message": "生成住宅区规划"})
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertIsNone(body["analysis_error"])
                record = body["result"]
                for name in ("image_url", "original_image_url", "postprocess_report_url", "postprocess_comparison_url"):
                    self.assertEqual(client.get(record[name]).status_code, 200)
                result_id = record["id"]
                cache = client.get(f"/results/{result_id}/analysis").json()
                self.assertEqual(cache["postprocess"]["source_fingerprint"], body["analysis"]["postprocess"]["source_fingerprint"])
                bundle = paths["IMAGES_DIR"] / f"{result_id}_postprocess"
                report = json.loads((bundle / "report.json").read_text())
                report["review_note"] = "test cache invalidation"
                (bundle / "report.json").write_text(json.dumps(report))
                updated = client.get(f"/results/{result_id}/analysis").json()
                self.assertNotEqual(updated["postprocess"]["source_fingerprint"], cache["postprocess"]["source_fingerprint"])
                self.assertEqual(client.delete(f"/results/{result_id}").status_code, 200)
                self.assertFalse(bundle.exists())
                self.assertFalse((paths["IMAGES_DIR"] / f"{result_id}.png").exists())


if __name__ == "__main__":
    unittest.main()
