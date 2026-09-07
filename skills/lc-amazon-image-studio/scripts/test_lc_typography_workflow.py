"""Opt-in full workflow regressions using explicit synthetic fixtures only.

No model is called and no production review is inferred. Run with
PYTHONDONTWRITEBYTECODE=1 LC_LAYOUT_BROWSER_TEST=1 python -m unittest
test_lc_typography_workflow -v from this directory.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageFilter

import lc_delivery as delivery
import lc_image_pipeline as p
import lc_layout as layout
import lc_title_effects as effects
import lc_typography as typography
import lc_workflow as workflow
from pipeline_test_support import (
    MAIN_ID, SECONDARY_ID, NOTE, create_v3_fixture,
    prepare_fixture, simulate_secondary_output,
)


@unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1", "opt-in pinned browser")
class TypographyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-typography-workflow-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.manifest_path = self.base / "project_manifest.json"
        self.m = create_v3_fixture(self.base)
        self.m.update(delivery_profile={"name": "compact_jpg"}, review_dependency_version=2,
                      style_contract={**typography.default_contract(),
                          "color_roles": {"headline": "#25352A", "body": "#20262C", "accent": "#53684D"},
                          "font_roles": {"headline": {"family": "serif", "weight": 400},
                                         "body": {"family": "sans", "weight": 400}}})
        self.job()["text_mode"] = "local_overlay"
        self.job()["design_brief"] = {"version": 1, "generation": {"composition": "Synthetic product below two local text groups"},
                                      "layout": {"headline_tone": "restrained serif on the fixture wall"}, "reference_ids": []}
        self.job()["layout"] = {"version": 3, "recipe": "photo_overlay", "text_groups": [
            {"id": "title", "headline": "Evening Glow", "box": [.06, .06, .88, .14],
             "color_role": "headline", "font_role": "headline"},
            {"id": "body", "body": "A calm fixture display.", "box": [.06, .22, .88, .09],
             "color_role": "body", "font_role": "body"}]}

    def job(self, identifier=SECONDARY_ID):
        return p.find_by_id(self.m["jobs"], identifier)

    def start_fixture(self, *, effect=False):
        if effect:
            self.job()["layout"]["text_groups"][0]["decorative_effect"] = {
                "kind": "surface_emboss", "purpose": "decorative", "reason": NOTE,
                "surface": "synthetic pale fixture wall", "material_lighting": "small lower-right contact shadow",
                "allowed_bbox_norm": [.045, .05, .91, .16],
                "semantic_review": {"decorative_only": True, "contains_brand": False, "contains_facts": False}}
        prepare_fixture(self.m, self.base)
        simulate_secondary_output(self.m, self.base)

    def packet(self, identifier=SECONDARY_ID, *, force=False):
        job = self.job(identifier)
        annotations = None
        if identifier == SECONDARY_ID:
            annotations = {"raw_product_bbox_norm": job["raw_product_bbox_norm"],
                           "detail_output_bbox_norms": job["fixture_output_detail_boxes"]}
        result = workflow.review_prepare(self.m, self.base, identifier, annotations, force=force)
        return p.read_json(Path(result["packet"]))

    def judged(self, packet, *, title=True):
        self.assertIs(self.m.get("test_fixture"), True, "Never infer production review verdicts")
        packet = copy.deepcopy(packet)
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        if title and "title_effect_review" in packet["reviews"]:
            review = packet["reviews"]["title_effect_review"]
            box = self.job()["title_effect_state"]["guide"]["target_bbox"]
            width, height = self.job()["canvas"]
            review.update(verdict="pass", transcription=self.job()["layout"]["text_groups"][0]["headline"], unexpected_text=[],
                          bbox_norm=[box["x"] / width, box["y"] / height, box["width"] / width, box["height"] / height],
                          observed_surface="synthetic pale fixture wall", notes=NOTE,
                          readable_original=True, readable_360=True, carrier_surface_visible=True,
                          material_perspective_pass=True, lighting_contact_pass=True,
                          product_unchanged=True, other_text_unchanged=True, decorative_only=True)
        return packet

    def submit(self, packet):
        result = workflow.review_submit(self.m, self.base, self.judged(packet))
        self.assertEqual(result["status"], "qa_passed", self.job(packet["job"]))
        return result

    def cli(self, command, *arguments, expect=0):
        p.write_json(self.manifest_path, self.m)
        result = subprocess.run([sys.executable, str(p.SCRIPT_DIR / "lc_image_pipeline.py"), command,
                                 "--manifest", str(self.manifest_path), *map(str, arguments), "--json"],
                                text=True, capture_output=True, timeout=90,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, expect, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ok"], expect == 0, payload)
        self.assertEqual(payload.get("manifest"), str(self.manifest_path), payload)
        self.assertNotIn(".lc-transactions", result.stdout)
        self.m = p.read_json(self.manifest_path)
        self.assertNotIn(".lc-transactions", json.dumps(self.m))
        return payload

    def finish_delivery(self):
        p.quality_assurance(self.m, self.base, update_overviews=True)
        p.create_final_contact_sheet(self.m, self.base)
        self.assertTrue(p.delivery_check(self.m, self.base)["ready"])

    def compact(self):
        return delivery.compact_project(self.m, self.base, manifest_path=self.manifest_path,
            delivery_check_fn=p.delivery_check, qa_fingerprint_fn=p.qa_fingerprint,
            stage_fingerprints_fn=p.current_fingerprints)

    def test_regular_review_export_compact_and_unchanged_run(self):
        self.start_fixture()
        self.submit(self.packet(MAIN_ID))
        self.submit(self.packet())
        job = self.job()
        groups = layout.resolve_layout_defaults(job)["text_groups"]
        self.assertEqual((groups[0]["text_color"], groups[0]["headline_family"]), ("#25352A", "serif"))
        self.assertEqual(groups[1]["text_color"], "#20262C")
        self.assertTrue(job["export_result"]["typography"]["passed"])
        self.assertTrue(job["final_output"].endswith(".jpg"))
        self.finish_delivery()
        hashes = [j["final_sha256"] for j in self.m["jobs"]]
        self.assertGreater(self.compact()["reclaimed_bytes"], 0)
        self.assertTrue(p.delivery_check(self.m, self.base)["ready"])
        with patch("lc_layout.render_batch", side_effect=AssertionError("Unchanged project must not render")):
            p.prepare(self.m, self.base)
            p.aspect_safe_postprocess(self.m, self.base)
            self.finish_delivery()
        self.assertEqual(hashes, [j["final_sha256"] for j in self.m["jobs"]])

    def test_deleted_proof_rebuild_and_copy_edit_rechecks_only_affected_job(self):
        self.start_fixture()
        self.submit(self.packet(MAIN_ID))
        old = self.packet()
        self.submit(old)
        main = copy.deepcopy(self.job(MAIN_ID))
        generation = copy.deepcopy(self.job()["generation_attempts"])
        raw_hash = p.sha256_file(self.base / self.job()["raw_output"])
        for path in typography.proof_paths(self.base, SECONDARY_ID).values():
            path.unlink()
        with patch("lc_layout.render_batch", wraps=layout.render_batch) as render:
            rebuilt = self.packet(force=True)
        self.assertEqual(render.call_count, 1)
        self.assertTrue(typography.proof_current(self.job(), self.base))
        self.submit(rebuilt)
        self.job()["layout"]["text_groups"][1]["body"] = "A new fixture caption."
        changed = self.packet()
        self.assertEqual(self.job()["generation_attempts"], generation)
        self.assertEqual(raw_hash, p.sha256_file(self.base / self.job()["raw_output"]))
        self.assertEqual(main, self.job(MAIN_ID))
        self.assertIsNone(changed["reviews"]["policy_qa_results"]["visual_design"]["verdict"])
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            workflow.review_submit(self.m, self.base, self.judged(old))
        self.submit(changed)
        self.assertEqual(main, self.job(MAIN_ID))
        self.finish_delivery()

    def synthetic_effect_inputs(self):
        state = self.job()["title_effect_state"]
        guide = state["guide"]
        with Image.open(self.base / guide["flat"]["path"]) as image:
            flat = image.convert("RGB")
        with Image.open(self.base / guide["glyph"]["path"]) as image:
            glyph = image.convert("L")
        box = guide["target_bbox"]
        bounds = (round(box["x"]), round(box["y"]), round(box["x"] + box["width"]), round(box["y"] + box["height"]))
        title = Image.new("L", flat.size)
        title.paste(glyph.crop(bounds), bounds[:2])
        shadow = ImageChops.offset(title, 4, 4).filter(ImageFilter.GaussianBlur(1.2))
        shadow = shadow.point(lambda alpha: round(alpha * .25))
        candidate = Image.composite(Image.new("RGB", flat.size, "#25352A"), flat, shadow)
        candidate.paste(flat, mask=title.point(lambda alpha: 255 if alpha else 0))
        mask = title.filter(ImageFilter.MaxFilter(17)).point(lambda alpha: 255 if alpha else 0)
        self.assertIsNotNone(ImageChops.difference(flat, candidate).getbbox(), "Fixture must contain real changed shadow pixels")
        candidate_path = self.base / "fixture-title-candidate.png"
        mask_path = self.base / "fixture-title-mask.png"
        candidate.save(candidate_path)
        mask.save(mask_path)
        return flat, mask, candidate_path, mask_path

    def test_cli_effect_transaction_regular_review_and_protection(self):
        self.start_fixture(effect=True)
        self.submit(self.packet(MAIN_ID))
        flat_packet = self.packet()
        self.submit(flat_packet)
        legacy_qa = {key: copy.deepcopy(self.job().get(key)) for key in
                     ("qa_fingerprint", "qa_final_sha256", "qa_report_fingerprint")}
        self.cli("title-effect-prepare", "--job", SECONDARY_ID)
        flat, mask, artifact, mask_path = self.synthetic_effect_inputs()
        self.cli("title-effect-event", "--job", SECONDARY_ID, "--event", "tool_started", "--attempt-id", "synthetic-title", "--timestamp", 1)
        self.cli("title-effect-event", "--job", SECONDARY_ID, "--event", "tool_returned", "--attempt-id", "synthetic-title", "--timestamp", 2)
        self.cli("title-effect-ingest", "--job", SECONDARY_ID, "--artifact", artifact,
                 "--mask", mask_path, "--attempt-id", "synthetic-title")
        packet = self.packet()
        job = self.job()
        self.assertTrue(job["layout_result"]["title_effect"]["applied"], job["layout_result"])
        self.assertIn("title_effect_review", packet["reviews"])
        fingerprint = layout.layout_fingerprint(self.m, job, self.base)
        with Image.open(self.base / job["layout_result"]["output_path"]) as image:
            applied = image.convert("RGB")
        delta = ImageChops.difference(flat, applied)
        self.assertIsNotNone(delta.getbbox())
        self.assertIsNone(Image.composite(delta, Image.new("RGB", flat.size), ImageChops.invert(mask)).getbbox())
        product = p.normalized_to_pixels(job["output_product_bbox_norm"], *flat.size)
        self.assertEqual(flat.crop(product).tobytes(), applied.crop(product).tobytes())
        missing = self.judged(packet)
        missing["reviews"].pop("title_effect_review")
        with self.assertRaises(p.PipelineError):
            workflow.review_submit(self.m, self.base, missing)
        incomplete = self.judged(packet, title=False)
        with self.assertRaisesRegex(p.PipelineError, "local-title review"):
            workflow.review_submit(self.m, self.base, incomplete)
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            workflow.review_submit(self.m, self.base, self.judged(flat_packet))
        judged_path = self.base / "fixture-effect-review.json"
        p.write_json(judged_path, self.judged(packet))
        result = self.cli("review-submit", "--packet", judged_path)
        self.assertEqual(result["status"], "qa_passed", result)
        self.assertEqual(fingerprint, layout.layout_fingerprint(self.m, self.job(), self.base))
        self.assertEqual(len(self.job()["title_effect_attempts"]), 1)
        self.assertEqual(effects.review_issues(self.job(), self.job()["title_effect_review"]), [])
        records = list((self.base / "title_effects" / SECONDARY_ID).rglob("*"))
        observations = [path for path in records if path.parent.name == "reviews" and path.suffix == ".json"]
        self.assertEqual(len(observations), 1, records)
        self.assertEqual(p.read_json(observations[0])["review"], self.job()["title_effect_review"])
        self.assertTrue(any(path.suffix == ".png" for path in records), records)
        for record in self.job()["title_effect_state"]["guide"].values():
            if not isinstance(record, dict) or "path" not in record:
                continue
            self.assertEqual(p.sha256_file(self.base / record["path"]), record["sha256"])
        with patch("lc_layout.render_batch", side_effect=AssertionError("Adopting/reviewing an effect must not self-invalidate")):
            p.prepare(self.m, self.base, [SECONDARY_ID])
            p.aspect_safe_postprocess(self.m, self.base, job_ids=[SECONDARY_ID])
            p.quality_assurance(self.m, self.base, [SECONDARY_ID], update_overviews=False)
        self.finish_delivery()
        stale = copy.deepcopy(self.m)
        stale_job = p.find_by_id(stale["jobs"], SECONDARY_ID)
        stale_job.update(legacy_qa)
        with self.assertRaises(p.PipelineError):
            p.delivery_check(stale, self.base)
        absent = copy.deepcopy(self.m)
        p.find_by_id(absent["jobs"], SECONDARY_ID).pop("title_effect_review")
        with self.assertRaises(p.PipelineError):
            p.delivery_check(absent, self.base)
        self.compact()
        self.assertTrue(p.delivery_check(self.m, self.base)["ready"])


if __name__ == "__main__":
    unittest.main()
