"""V2 layout regressions. The Chromium suite is opt-in and creates only synthetic test rasters."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image, ImageDraw

import lc_layout as layout


class LayoutV2Tests(unittest.TestCase):
    def job(self, *, template: str = "split", canvas: list[int] | None = None) -> dict:
        return {
            "id": "v2",
            "kind": "listing",
            "canvas": canvas or [1464, 600],
            "layout_input": "base.png",
            "output_product_bbox_norm": [.687, .16, .20, .67],
            "layout": {
                "version": 2,
                "template": template,
                "headline": "An Easter\nAccent",
                "body": "A single black rabbit with a checked bow.",
                "items": [],
                "text_group": {"box": [.075, .17, .54, .70], "align": "left", "gap_em": .65},
                "headline_family": "serif",
                "headline_weight": 400,
                "mobile_sizes": {"headline": 26, "body": 12, "label": 12},
                "text_surface": "transparent",
                "text_color": "#29251F",
                "protected_regions": [],
            },
        }

    def test_schema_defaults_variants_and_mobile_floor(self):
        wide = self.job()
        self.assertIsNone(layout.validate_layout_v2(wide["layout"]))
        geometry = layout.layout_geometry(wide)
        self.assertEqual(geometry["version"], 2)
        self.assertEqual(geometry["variant"], "wide")
        self.assertEqual(geometry["text_group"], [.075, .17, .54, .70])
        for canvas, expected in [([2000, 2000], "square"), ([2000, 2600], "portrait")]:
            job = self.job(canvas=canvas)
            job["layout"].pop("text_group")
            self.assertEqual(layout.layout_geometry(job)["variant"], expected)
        self.assertEqual(layout._v2_mobile_sizes({"mobile_sizes": {"headline": 18, "body": 12, "label": 12}}),
                         {"headline": 18.0, "body": 12.0, "label": 12.0})
        invalid = copy.deepcopy(wide["layout"])
        invalid["font_sizes"] = {"headline": 140}
        with self.assertRaises(layout.LayoutError):
            layout.validate_layout_v2(invalid)
        invalid = copy.deepcopy(wide["layout"])
        invalid["mobile_sizes"]["headline"] = 17
        with self.assertRaises(layout.LayoutError):
            layout.validate_layout_v2(invalid)

    def test_faq_and_detail_inset_semantics(self):
        job = self.job(template="detail")
        job["layout"]["faq"] = [
            {"question": "Where?", "answer": "On an indoor shelf."},
            {"question": "Why?", "answer": "The checked bow is visible."},
        ]
        job["layout"]["items"] = [
            {"text": "", "image": "crop.png", "evidence_refs": ["ear"], "target": [.786, .24],
             "image_box": [.105, .32, .145, .44], "image_shape": "circle",
             "leader_waypoints": [[.28, .54], [.28, .275], [.70, .275]]},
            {"text": "Checked bow", "image": "crop.png", "evidence_refs": ["bow"], "target": [.786, .52],
             "image_box": [.38, .32, .17, .44], "text_box": [.335, .81, .26, .13]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            Image.new("RGB", (1464, 600), "#FCF8F0").save(base / "base.png")
            Image.new("RGB", (150, 150), "#171717").save(base / "crop.png")
            prepared = layout._prepare_job({}, base, job)
        self.assertEqual(len(prepared["faq"]), 2)
        self.assertEqual(prepared["items"][0]["text"], "")
        self.assertEqual(prepared["geometry"]["lines"][0]["thin"], True)
        self.assertEqual(prepared["geometry"]["items"][0]["image_shape"], "circle")
        self.assertEqual(prepared["geometry"]["lines"][0]["points"],
                         [[.25, .54], [.28, .54], [.28, .275], [.70, .275], [.786, .24]])
        self.assertEqual(prepared["geometry"]["lines"][0]["source_evidence_id"], "evidence-0")
        changed = copy.deepcopy(job)
        changed["layout"]["items"][0]["leader_waypoints"][-1] = [.69, .275]
        self.assertNotEqual(layout.layout_fingerprint({}, job), layout.layout_fingerprint({}, changed))
        invalid_waypoints = copy.deepcopy(job["layout"])
        invalid_waypoints["items"][0]["leader_waypoints"] *= 2
        with self.assertRaises(layout.LayoutError):
            layout.validate_layout_v2(invalid_waypoints)
        invalid_waypoint_point = copy.deepcopy(job["layout"])
        invalid_waypoint_point["items"][0]["leader_waypoints"] = [[.28, 1.01]]
        with self.assertRaises(layout.LayoutError):
            layout.validate_layout_v2(invalid_waypoint_point)
        invalid_waypoint_type = copy.deepcopy(job["layout"])
        invalid_waypoint_type["items"][0]["leader_waypoints"] = "not-a-point-list"
        with self.assertRaises(layout.LayoutError):
            layout.validate_layout_v2(invalid_waypoint_type)
        with self.assertRaises(layout.LayoutError):
            layout.validate_layout_v2({"version": 2, "faq": [{"question": "q", "answer": "a"}] * 3})

    def test_v2_serif_assets_are_selected_without_touching_v1_face_set(self):
        legacy, _ = layout._font_payload(["Simple"], version=1)
        serif, missing = layout._font_payload(["Simple"], version=2, headline_family="serif")
        self.assertEqual(missing, [])
        self.assertEqual(len(legacy), 6)
        self.assertEqual({face["weight"] for face in serif if face["family"] == "Serif"}, {400, 600})
        self.assertNotIn("Serif", {face["family"] for face in legacy})


@unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1",
                     "set LC_LAYOUT_BROWSER_TEST=1 for the pinned Chromium v2 suite")
class ChromiumLayoutV2Tests(unittest.TestCase):
    job = LayoutV2Tests.job
    def _base_image(self, directory: Path) -> None:
        image = Image.new("RGB", (1464, 600), "#FCF8F0")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1010, 105, 1310, 505), radius=78, fill="#171717")
        image.save(directory / "base.png")
        Image.new("RGB", (180, 180), "#171717").save(directory / "crop.png")

    def _check(self, result: dict, name: str, check: str) -> dict:
        return next(value for value in result[name]["checks"] if value["check"] == check)

    def test_wide_group_surface_overflow_protection_fonts_and_utf8_streaming(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self._base_image(base)
            transparent = self.job()
            transparent["id"] = "wide-transparent"
            solid = copy.deepcopy(transparent)
            solid["id"] = "wide-solid"
            solid["layout"]["text_surface"] = "solid"
            solid["layout"]["headline"] = "Spring Accent"
            solid["layout"]["body"] = "Checked bow."
            gradient = copy.deepcopy(solid)
            gradient["id"] = "wide-gradient"
            gradient["layout"]["text_surface"] = "gradient"
            faq = copy.deepcopy(transparent)
            faq["id"] = "wide-faq"
            faq["layout"].update({"headline": "Display Notes", "body": "",
                                  "faq": [{"question": "Where?", "answer": "On indoor shelves."},
                                          {"question": "What stands out?", "answer": "Upright ears and a checked bow."}]})
            faq["layout"]["mobile_sizes"]["headline"] = 19
            faq["layout"]["text_group"]["gap_em"] = .25
            overflow = copy.deepcopy(transparent)
            overflow["id"] = "wide-overflow"
            overflow["layout"]["headline"] = "A deliberately overlong headline " * 12
            overflow["layout"]["text_group"]["max_height"] = .16
            protected = copy.deepcopy(transparent)
            protected["id"] = "wide-protected"
            protected["layout"]["protected_regions"] = [{"kind": "face", "bbox": [.075, .17, .54, .30]}]
            result = layout.render_batch({}, base, [transparent, solid, gradient, faq, overflow, protected])
            self.assertTrue(result["wide-transparent"]["passed"], result["wide-transparent"]["checks"])
            self.assertTrue(result["wide-solid"]["passed"], result["wide-solid"]["checks"])
            self.assertTrue(result["wide-gradient"]["passed"], result["wide-gradient"]["checks"])
            self.assertTrue(result["wide-faq"]["passed"], result["wide-faq"]["checks"])
            self.assertFalse(result["wide-overflow"]["passed"])
            self.assertFalse(result["wide-protected"]["passed"])
            self.assertEqual([box for box in result["wide-transparent"]["bboxes"] if box["kind"] == "surface"], [])
            surface = next(box for box in result["wide-solid"]["bboxes"] if box["id"] == "surface-text-group")
            self.assertLess(surface["bbox"]["height"], 600 * .70)
            self.assertTrue(self._check(result, "wide-solid", "text_group_surface")["passed"])
            self.assertTrue(self._check(result, "wide-solid", "font_coverage")["passed"])
            self.assertTrue(self._check(result, "wide-gradient", "gradient_fade")["passed"])
            self.assertIn("faq-1-answer", {box["id"] for box in result["wide-faq"]["bboxes"]})

            # Feed a JSON payload in the middle of 春's UTF-8 byte sequence.
            # The renderer must decode it as one character, not replacement glyphs.
            utf_job = copy.deepcopy(transparent)
            utf_job["id"] = "utf8-split"
            utf_job["layout"]["headline"] = "春日\n点缀"
            prepared = layout._prepare_job({}, base, utf_job)
            runtime = layout.doctor()
            self.assertTrue(runtime["passed"], runtime["errors"])
            fonts, missing = layout._font_payload(layout._prepared_texts(prepared), version=2, headline_family="serif")
            self.assertEqual(missing, [])
            output = base / "utf8-render"; output.mkdir()
            payload = {"jobs": [prepared], "fonts": fonts, "icons": layout._json(layout.ASSETS / "icons/icons.json"),
                       "chromium": runtime["chromium"], "playwright": str(Path(runtime["modules"]) / "playwright/index.mjs"),
                       "output_dir": str(output), "versions": runtime["versions"]}
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            split = encoded.index("春".encode("utf-8")) + 1
            process = subprocess.Popen([runtime["node"], str(Path(__file__).with_name("render_layout.mjs"))],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert process.stdin is not None
            process.stdin.write(encoded[:split]); process.stdin.flush()
            process.stdin.write(encoded[split:]); process.stdin.close()
            process.wait(timeout=90)
            stdout = process.stdout.read() if process.stdout else b""
            stderr = process.stderr.read() if process.stderr else b""
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            self.assertEqual(process.returncode, 0, stderr.decode("utf-8", "replace"))
            decoded = json.loads(stdout.decode("utf-8"))
            self.assertTrue(decoded["utf8-split"]["passed"], decoded["utf8-split"]["checks"])

    def test_detail_leader_waypoints_avoid_other_evidence_inset(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self._base_image(base)

            def detail_job(job_id: str, routed: bool) -> dict:
                job = self.job(template="detail")
                job["id"] = job_id
                job["layout"].update({"headline": "Details", "body": "",
                                      "text_group": {"box": [.06, .10, .45, .16], "align": "left", "gap_em": .4},
                                      "mobile_sizes": {"headline": 19, "body": 12, "label": 12},
                                      "items": [
                                          {"text": "", "image": "crop.png", "evidence_refs": ["ear"], "target": [.786, .24],
                                           "image_box": [.105, .32, .145, .44],
                                           **({"leader_waypoints": [[.28, .54], [.28, .275], [.70, .275]]} if routed else {})},
                                          {"text": "", "image": "crop.png", "evidence_refs": ["bow"], "target": [.786, .52],
                                           "image_box": [.38, .32, .17, .44]},
                                      ]})
                return job

            direct = detail_job("detail-direct", False)
            routed = detail_job("detail-routed", True)
            result = layout.render_batch({}, base, [direct, routed])
            self.assertFalse(result["detail-direct"]["passed"], result["detail-direct"]["checks"])
            self.assertTrue(result["detail-routed"]["passed"], result["detail-routed"]["checks"])
            direct_collision = self._check(result, "detail-direct", "leader_evidence_collision")
            self.assertFalse(direct_collision["passed"])
            self.assertEqual(direct_collision["elements"], ["leader-0", "evidence-1"])
            self.assertTrue(self._check(result, "detail-routed", "leader_evidence_collision")["passed"])


if __name__ == "__main__":
    unittest.main()
