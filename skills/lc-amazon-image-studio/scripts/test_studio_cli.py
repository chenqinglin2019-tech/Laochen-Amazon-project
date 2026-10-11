"""V8 end to end through the CLI with a fake image model; state machine; auth gate; export."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import studio_export
import studio_project as sp
from studio_test_support import basic_plan, cli, fake_model_image, isolated_env, product_photo


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v8-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = isolated_env(self.base)
        self.proj = self.base / "proj"

    def generate(self, reservations, **kwargs):
        items = []
        for reservation in reservations:
            width, height = map(int, reservation["size"].split("x"))
            path = fake_model_image(self.base / f"{reservation['job']}-{reservation['attempt_id']}.png", (width, height), **kwargs)
            items += ["--item", reservation["job"], reservation["attempt_id"], path]
        return items

    def test_photo_main_full_set_with_redo_429_and_not_started(self):
        code, init = cli(self.env, "init", "--project-dir", self.proj, "--project-id", "e2e", "--marketplace", "US",
                         "--language", "en", "--photos", product_photo(self.base / "front.jpg"))
        self.assertEqual(code, 0, init)
        self.assertEqual(init["main_candidate"], "front")
        plan = basic_plan(init["catalog"], init["slots"], skip={"07_problem_solution"})
        (self.proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        code, result = cli(self.env, "plan", "--project", self.proj)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["main"]["route"], "photo")
        wave = result["reservations"]
        self.assertEqual(len(wave), 4)
        first, second = wave[0], wave[1]
        items = self.generate(wave[2:])
        code, result = cli(self.env, "ingest-batch", "--project", self.proj, *items,
                           "--failed", first["job"], first["attempt_id"], "HTTP 429 Too Many Requests, retry after 0 seconds",
                           "--not-started", second["job"], second["attempt_id"])
        self.assertEqual(code, 0, result)
        guard = 0
        while result.get("reservations") or result.get("retry_after_seconds"):
            guard += 1
            self.assertLess(guard, 12)
            if not result.get("reservations"):
                code, result = cli(self.env, "reserve", "--project", self.proj)
                continue
            code, result = cli(self.env, "ingest-batch", "--project", self.proj, *self.generate(result["reservations"]))
            self.assertEqual(code, 0, result)
        code, result = cli(self.env, "ingest-batch", "--project", self.proj, "--redo", "03_primary_use_case",
                           "headline misspelled", "--no-reserve")
        self.assertEqual(code, 0, result)
        code, result = cli(self.env, "reserve", "--project", self.proj)
        self.assertEqual([r["job"] for r in result["reservations"]], ["03_primary_use_case"])
        self.assertIn("Correction - the previous attempt had this problem: headline misspelled", result["reservations"][0]["prompt"])
        code, result = cli(self.env, "ingest-batch", "--project", self.proj, *self.generate(result["reservations"]))
        code, again = cli(self.env, "ingest-batch", "--project", self.proj, "--redo", "03_primary_use_case", "still wrong")
        self.assertEqual(code, 2)
        self.assertIn("REDO_LIMIT_REACHED", json.dumps(again))
        code, delivered = cli(self.env, "deliver", "--project", self.proj)
        self.assertEqual(code, 0, delivered)
        self.assertEqual(delivered["image_count"], 6)
        self.assertTrue(all(Path(path).suffix == ".jpg" for path in delivered["files"]))
        self.assertFalse(list(self.proj.rglob("*.zip")))

    def test_generated_main_on_chosen_backdrop_and_wide_cut_redo(self):
        code, init = cli(self.env, "init", "--project-dir", self.proj, "--project-id", "e2e2", "--marketplace", "US",
                         "--language", "en", "--photos", product_photo(self.base / "scene.jpg", lifestyle=True),
                         "--a-plus-modules", "feature:1464x600")
        self.assertIsNone(init["main_candidate"])
        plan = basic_plan(init["catalog"], init["slots"], skip={s["id"] for s in init["slots"]
                                                                if s["id"] not in {"01_main", "08_a_plus_feature"}})
        (self.proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        code, result = cli(self.env, "plan", "--project", self.proj)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["main"]["route"], "generate")
        main = next(r for r in result["reservations"] if r["job"] == "01_main")
        self.assertIn("Shadows: none at all", main["prompt"])
        wide = next(r for r in result["reservations"] if r["job"] == "08_a_plus_feature")
        width, height = map(int, main["size"].split("x"))
        main_path = fake_model_image(self.base / "main.png", (width, height), backdrop=(255, 255, 255),
                                     product=(40, 90, 160), product_box=(0.25, 0.12, 0.75, 0.88), text=False)
        w2, h2 = map(int, wide["size"].split("x"))
        wide_path = fake_model_image(self.base / "wide.png", (w2, h2), product_box=(0.55, 0.02, 0.9, 0.98))
        code, result = cli(self.env, "ingest-batch", "--project", self.proj, "--item", "01_main", main["attempt_id"], main_path,
                           "--item", "08_a_plus_feature", wide["attempt_id"], wide_path)
        self.assertEqual(code, 0, result)
        statuses = {r["job"]: r for r in result["results"]}
        self.assertEqual(statuses["01_main"]["status"], "done")
        self.assertEqual(statuses["08_a_plus_feature"].get("auto_redo"), "FRAME_CONTENT_CUT")
        final = Image.open(self.proj / "final" / "01_main.jpg").convert("RGB")
        array = np.asarray(final)
        self.assertTrue((array[:8] == 255).all() and (array[-8:] == 255).all())

    def test_auth_gate_blocks_plan_and_deliver_without_touching_the_project(self):
        env = isolated_env(self.base, bypass_auth=False)
        code, init = cli(env, "init", "--project-dir", self.proj, "--project-id", "auth", "--marketplace", "US",
                         "--language", "en", "--no-catalog")
        self.assertEqual(code, 0, init)
        before = (self.proj / "project.json").read_bytes()
        for command in ("plan", "deliver"):
            code, result = cli(env, command, "--project", self.proj)
            self.assertEqual(code, 2)
            self.assertEqual(result.get("code"), "AUTH_PASS_REQUIRED", result)
        self.assertEqual(before, (self.proj / "project.json").read_bytes())

    def test_legacy_v7_project_is_refused(self):
        self.proj.mkdir()
        (self.proj / "project_manifest.json").write_text("{}", encoding="utf-8")
        code, result = cli(self.env, "status", "--project", self.proj)
        self.assertEqual(code, 2)
        self.assertIn("LEGACY_PROJECT_V7", result["error"])


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v8-state-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "p"
        self.project = sp.create(self.dir, "s", "US", "en")
        prompt = self.dir / "prompts" / "02_size_or_components.txt"
        prompt.write_text("prompt", encoding="utf-8")
        self.project["jobs"]["02_size_or_components"] = {"status": "pending", "route": "generate", "attempts": [],
                                                         "prompt_file": "prompts/02_size_or_components.txt",
                                                         "references": [], "size": "1024x1024", "aspect": "1:1"}

    def reserve(self):
        wave = sp.reserve(self.project, self.dir)
        return wave["reservations"][0]["attempt_id"]

    def test_transient_budget_429_and_free_releases(self):
        job = "02_size_or_components"
        for attempt in range(2):          # first try + 2 retries = 3 attempts
            sp.record_failure(self.project, job, self.reserve(), "boom")
        self.assertEqual(self.project["jobs"][job]["status"], "pending")
        sp.record_failure(self.project, job, self.reserve(), "boom")
        self.assertEqual(self.project["jobs"][job]["status"], "failed")
        sp.reset(self.project, job, "user agreed")
        result = sp.record_failure(self.project, job, self.reserve(), "429 rate limit, retry after 5 s")
        self.assertTrue(result["rate_limited"])
        self.assertEqual(self.project["jobs"][job]["transient_failures"], 0)
        self.project["network"]["retry_after_until"] = 0
        for _ in range(2):
            self.assertFalse(sp.release(self.project, job, self.reserve())["charged"])
        self.assertTrue(sp.release(self.project, job, self.reserve())["charged"])

    def test_timeout_reclaims_the_slot(self):
        job = "02_size_or_components"
        self.reserve()
        released = sp.sweep_timeouts(self.project, now=10 ** 10)
        self.assertEqual(released, [job])
        self.assertEqual(self.project["jobs"][job]["status"], "pending")


class ExportTests(unittest.TestCase):
    def test_fit_band_slides_to_keep_a_high_headline_and_flags_two_sided_text(self):
        image = Image.new("RGB", (1536, 1024), (230, 225, 215))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        for x in range(100, 1400, 40):
            draw.rectangle((x, 120, x + 20, 170), fill=(10, 10, 10))   # "text" high in the frame
        fitted, info = studio_export.fit_to_canvas(image, (1464, 600))
        self.assertEqual(fitted.size, (1464, 600))
        self.assertFalse(info["cut"], info)
        for x in range(100, 1400, 40):
            draw.rectangle((x, 900, x + 20, 950), fill=(10, 10, 10))   # and low: cannot keep both
        _, info = studio_export.fit_to_canvas(image, (1464, 600))
        self.assertTrue(info["cut"], info)

    def test_xmp_disclosure_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Image.new("RGB", (400, 300), (200, 100, 50))
            path = Path(temp) / "x.jpg"
            studio_export.export_jpeg(image, path, people=True)
            with Image.open(path) as check:
                self.assertEqual(studio_export.xmp_keywords(check), [studio_export.SYNTHETIC_KEYWORD])
            studio_export.export_jpeg(image, path, people=False)
            with Image.open(path) as check:
                self.assertEqual(studio_export.xmp_keywords(check), [])


if __name__ == "__main__":
    unittest.main()
