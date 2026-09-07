"""Synthetic fixtures for local-title lifecycle, safety and real-review binding."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

import lc_title_effects as effects


class TitleEffectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-title-effects-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.size = (200, 200)
        background = Image.new("RGB", self.size, "#403B34")
        draw = ImageDraw.Draw(background)
        draw.rectangle((100, 100, 179, 179), fill="#F8AC37")
        background.save(self.base / "background.png")
        background.save(self.base / "source.png")
        flat = background.copy()
        draw = ImageDraw.Draw(flat)
        draw.rectangle((21, 21, 39, 39), fill="#F7E3BC")
        draw.rectangle((41, 21, 59, 39), fill="#F7E3BC")
        draw.rectangle((20, 60, 79, 65), fill="#DDDDDD")
        draw.rectangle((130, 20, 160, 25), fill="#FFFFFF")
        flat.save(self.base / "flat.png")
        glyph = Image.new("L", self.size)
        draw = ImageDraw.Draw(glyph)
        draw.rectangle((21, 21, 39, 39), fill=255)
        draw.rectangle((41, 21, 59, 39), fill=255)
        draw.rectangle((20, 60, 79, 65), fill=255)
        draw.rectangle((130, 20, 160, 25), fill=255)
        glyph.save(self.base / "glyph.png")
        mask = Image.new("L", self.size)
        ImageDraw.Draw(mask).rectangle((19, 19, 61, 41), fill=255)
        mask.save(self.base / "mask.png")
        candidate = Image.new("RGB", self.size, "#FF0000")
        ImageDraw.Draw(candidate).rectangle((19, 19, 61, 41), fill="#BFA570")
        candidate.save(self.base / "candidate.png")
        self.manifest = {"brand": "Example Brand", "references": [{"id": "real", "path": "source.png"}]}
        self.job = {"id": "scene", "kind": "listing", "text_mode": "local_overlay", "canvas": list(self.size),
                    "source_reference_ids": ["real"], "layout_input": "background.png",
                    "output_product_bbox_norm": [.5, .5, .4, .4],
                    "layout": {"version": 3, "recipe": "photo_overlay", "text_groups": [
                        {"id": "mood", "headline": "Evening Glow", "body": "Exact approved body stays local",
                         "box": [.08, .08, .38, .3], "decorative_effect": {
                             "kind": "surface_emboss", "purpose": "decorative", "reason": "Optional atmosphere title",
                             "surface": "The visible matte wall above the product", "material_lighting": "Warm light from left",
                             "allowed_bbox_norm": [.05, .05, .4, .3],
                             "semantic_review": {"decorative_only": True, "contains_brand": False, "contains_facts": False}}},
                        {"id": "brand", "headline": "Example Brand", "box": [.65, .05, .3, .1]}]}}
        self.bboxes = [{"id": "group-mood-headline", "kind": "text", "bbox": {"x": 20, "y": 20, "width": 41, "height": 21}},
                       {"id": "group-mood-body", "kind": "text", "bbox": {"x": 20, "y": 60, "width": 60, "height": 6}},
                       {"id": "group-brand-headline", "kind": "text", "bbox": {"x": 130, "y": 20, "width": 31, "height": 6}}]

    def prepare(self):
        return effects.prepare(self.manifest, self.base, self.job, flat_path=self.base / "flat.png",
                               background_path=self.base / "background.png", glyph_path=self.base / "glyph.png", bboxes=self.bboxes)

    def start(self, kind="initial", stamp=100, reason=None):
        self.prepare()
        attempt = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", kind=kind, at=stamp, reason=reason)
        effects.attempt_event(self.manifest, self.base, self.job, "tool_returned", attempt_id=attempt["id"], at=stamp + 1)
        return attempt["id"]

    def ingest(self, **kwargs):
        attempt = self.start()
        return effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "mask.png",
                              attempt_id=attempt, **kwargs)

    def composite(self):
        return effects.composite(self.job, self.base, self.base / "flat.png", self.base / "background.png",
                                 self.base / "glyph.png", self.bboxes, manifest=self.manifest)

    def review(self, binding):
        return {"binding": binding, "verdict": "pass", "transcription": "Evening Glow", "unexpected_text": [],
                "bbox_norm": [.095, .095, .215, .115], "observed_surface": "Matte wall above fixture product",
                "notes": "Synthetic test observation; not evidence for real products.",
                **{key: True for key in effects._REVIEW_FLAGS}}

    def test_legacy_no_effect_is_noop_without_state(self):
        self.job["layout"]["text_groups"][0].pop("decorative_effect")
        before = copy.deepcopy(self.job)
        self.assertEqual(effects.prepare(self.manifest, self.base, self.job)["status"], "disabled")
        self.assertFalse(self.composite()["applied"])
        self.assertEqual(self.job, before)
        self.assertEqual(effects.dependencies(self.job, self.base), {})

    def test_prepare_requires_real_render_guide_and_never_consumes_attempt(self):
        self.assertEqual(effects.prepare(self.manifest, self.base, self.job)["status"], "needs_guide")
        with self.assertRaisesRegex(effects.TitleEffectError, "GUIDE_REQUIRED"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started")
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(second["attempt_counts"], {"initial": 0, "quality_repair": 0, "transient_retry": 0})
        self.assertNotIn("title_effect_attempts", self.job)
        self.assertIn('"Evening Glow"', first["prompt"])
        self.assertNotIn("Exact approved body", first["prompt"])

    def test_numbers_brands_facts_and_wrong_routes_are_rejected(self):
        changes = [lambda j: j.update(text_mode="model_native"), lambda j: j.update(kind="main"),
                   lambda j: j["layout"].update(version=2),
                   lambda j: j["layout"]["text_groups"][0].update(headline="Glow for 12 Hours"),
                   lambda j: j["layout"]["text_groups"][0].update(headline="Example Brand"),
                   lambda j: j["layout"]["text_groups"][0].update(headline="Certified Waterproof"),
                   lambda j: j["layout"]["text_groups"][0].update(headline="One two three four five six"),
                   lambda j: j["layout"]["text_groups"][0].update(evidence_refs=["fact-1"]),
                   lambda j: j["layout"]["text_groups"][0]["decorative_effect"]["semantic_review"].update(contains_brand=True)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                job = copy.deepcopy(self.job)
                change(job)
                with self.assertRaises(effects.TitleEffectError):
                    effects.prepare(self.manifest, self.base, job)
                self.assertNotIn("title_effect_attempts", job)

    def test_group_count_and_real_source_provenance_are_bounded(self):
        self.job["layout"]["text_groups"][1]["decorative_effect"] = copy.deepcopy(self.job["layout"]["text_groups"][0]["decorative_effect"])
        with self.assertRaisesRegex(effects.TitleEffectError, "ONE_GROUP"):
            self.prepare()
        self.job["layout"]["text_groups"][1].pop("decorative_effect")
        self.manifest["references"][0]["provenance"] = {"kind": "generated", "qa_verdict": "pass", "source_reference_ids": ["real"]}
        with self.assertRaisesRegex(effects.TitleEffectError, "SOURCE_CYCLE"):
            self.prepare()

    def test_candidate_can_be_reviewed_without_preapproval_and_never_changes_other_pixels(self):
        self.ingest()
        result = self.composite()
        self.assertTrue(result["applied"])
        self.assertTrue(result["review_required"])
        self.assertEqual(self.job["title_effect_state"]["status"], "review_pending")
        with Image.open(result["output_path"]) as output, Image.open(self.base / "flat.png") as flat:
            self.assertEqual(output.getpixel((21, 21)), (191, 165, 112))
            for point in [(50, 63), (145, 22), (140, 140), (10, 190)]:
                self.assertEqual(output.getpixel(point), flat.getpixel(point))
            self.assertEqual(flat.getpixel((21, 21)), (247, 227, 188))
        second = self.composite()
        self.assertEqual(result["output_sha256"], second["output_sha256"])
        self.assertEqual(len(self.job["title_effect_attempts"]), 1)
        self.assertEqual(effects.review_issues(self.job, None), ["TITLE_EFFECT_REVIEW_REQUIRED"])

    def test_mask_cannot_miss_or_blend_original_title_core(self):
        attempt = self.start()
        for value in [0, 128, 254]:
            with self.subTest(value=value):
                with Image.open(self.base / "mask.png") as mask:
                    mask.putpixel((21, 21), value)
                    mask.save(self.base / f"invalid-{value}.png")
                with self.assertRaisesRegex(effects.TitleEffectError, "REPLACE_ALL_TITLE_INK"):
                    effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / f"invalid-{value}.png", attempt_id=attempt)
        self.assertNotIn("candidate", self.job["title_effect_state"])

    def test_mask_cannot_touch_product_or_other_text_even_at_one_pixel_alpha(self):
        for name, point, allowed, expected in [
                ("outside", (9, 15), [.05, .05, .4, .3], "OUTSIDE_ALLOWED"),
                ("product", (100, 100), [0, 0, 1, 1], "TOUCHES_PRODUCT"),
                ("body", (20, 60), [0, 0, 1, 1], "TOUCHES_OTHER_TEXT"),
                ("brand", (130, 20), [0, 0, 1, 1], "TOUCHES_OTHER_TEXT")]:
            with self.subTest(name=name):
                self.job.pop("title_effect_state", None)
                self.job.pop("title_effect_attempts", None)
                self.job["layout"]["text_groups"][0]["decorative_effect"]["allowed_bbox_norm"] = allowed
                attempt = self.start()
                with Image.open(self.base / "mask.png") as mask:
                    mask.putpixel(point, 1)
                    path = self.base / f"{name}.png"
                    mask.save(path)
                with self.assertRaisesRegex(effects.TitleEffectError, expected):
                    effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", path, attempt_id=attempt)

    def test_intake_requires_explicit_return_and_rejects_stale_attempt(self):
        self.prepare()
        attempt = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", at=100)
        with self.assertRaisesRegex(effects.TitleEffectError, "RETURN_EVENT"):
            effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "mask.png", attempt_id=attempt["id"])
        effects.attempt_event(self.manifest, self.base, self.job, "tool_returned", attempt_id=attempt["id"], at=101)
        self.job["layout"]["text_groups"][0]["headline"] = "Quiet Evenings"
        with self.assertRaisesRegex(effects.TitleEffectError, "STALE_ATTEMPT"):
            effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "mask.png", attempt_id=attempt["id"])

    def test_ingest_is_idempotent_but_different_artifact_is_conflict(self):
        first = self.ingest()
        attempt = self.job["title_effect_attempts"][0]["id"]
        second = effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "mask.png", attempt_id=attempt)
        self.assertEqual(first["binding"], second["binding"])
        self.assertTrue(second["cached"])
        Image.new("RGB", self.size, "blue").save(self.base / "different.png")
        with self.assertRaisesRegex(effects.TitleEffectError, "INGEST_CONFLICT"):
            effects.ingest(self.manifest, self.base, self.job, self.base / "different.png", self.base / "mask.png", attempt_id=attempt)

    def test_tampered_candidate_safely_falls_back_and_changes_dependency(self):
        self.ingest()
        self.assertTrue(self.composite()["applied"])
        previous = effects.dependencies(self.job, self.base)
        candidate = self.job["title_effect_state"]["candidate"]["artifact"]["path"]
        (self.base / candidate).write_bytes(b"changed raster")
        self.assertNotEqual(previous, effects.dependencies(self.job, self.base))
        result = self.composite()
        self.assertFalse(result["applied"])
        self.assertIn("ARTIFACT_CHANGED", result["fallback_reason"])
        self.assertEqual(result["output_path"], str(self.base / "flat.png"))
        self.assertNotIn("applied", self.job["title_effect_state"])
        self.assertEqual(len(self.job["title_effect_attempts"]), 1)

    def test_changed_title_or_typography_invalidates_effect_without_touching_raw(self):
        self.ingest()
        raw_hash = effects._hash(self.base / "background.png")
        self.job["layout"]["text_groups"][0]["headline_weight"] = 400
        result = self.composite()
        self.assertFalse(result["applied"])
        self.assertEqual(result["fallback_reason"], "TITLE_EFFECT_CANDIDATE_STALE")
        self.assertEqual(raw_hash, effects._hash(self.base / "background.png"))
        self.assertEqual(self.prepare()["attempt_counts"]["initial"], 1)

    def test_flat_guide_survives_disposable_renderer_output_replacement(self):
        self.ingest()
        result = self.composite()
        flat_guide = self.job["title_effect_state"]["guide"]["flat"]
        Path(result["output_path"]).replace(self.base / "flat.png")
        self.assertEqual(effects._hash(self.base / flat_guide["path"]), flat_guide["sha256"])
        self.assertNotEqual(effects._hash(self.base / "flat.png"), flat_guide["sha256"])
        self.assertEqual(effects.prepare(self.manifest, self.base, self.job)["fingerprint"], self.job["title_effect_state"]["candidate"]["fingerprint"])

    def test_attempt_budget_survives_json_restart_and_changed_design(self):
        self.ingest()
        self.job = json.loads(json.dumps(self.job))
        self.job["layout"]["text_groups"][0]["decorative_effect"]["material_lighting"] = "Diffuse light from right"
        self.prepare()
        with self.assertRaisesRegex(effects.TitleEffectError, "BUDGET_EXHAUSTED"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started", at=200)
        repair = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", kind="quality_repair", at=200, reason="Updated local lighting")
        effects.attempt_event(self.manifest, self.base, self.job, "failed", attempt_id=repair["id"], at=201, reason="Tool timeout")
        for stamp in [300, 400]:
            retry = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", kind="transient_retry", at=stamp, reason="Retry tool timeout")
            effects.attempt_event(self.manifest, self.base, self.job, "failed", attempt_id=retry["id"], at=stamp + 1, reason="Tool timeout")
        with self.assertRaisesRegex(effects.TitleEffectError, "BUDGET_EXHAUSTED"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started", kind="transient_retry", at=500, reason="Retry")
        self.assertEqual(len(self.job["title_effect_attempts"]), 4)
        self.assertEqual(self.prepare()["attempt_counts"], {"initial": 1, "quality_repair": 1, "transient_retry": 2})

    def test_review_requires_actual_bound_transcription_and_visual_observations(self):
        self.ingest(review={"verdict": "pass"})
        result = self.composite()
        review = self.review(result["binding"])
        self.assertEqual(effects.review_issues(self.job, review), [])
        for field, invalid in [("binding", "old"), ("transcription", "Wrong title"), ("unexpected_text", ["badge"]),
                               ("readable_360", False), ("observed_surface", ""), ("bbox_norm", None)]:
            with self.subTest(field=field):
                bad = {**review, field: invalid}
                self.assertTrue(effects.review_issues(self.job, bad))
        record = effects.submit_review(self.manifest, self.base, self.job, review)
        self.assertTrue((self.base / record["record"]).is_file())
        self.assertFalse(record["image_qa_approved"])

    def test_source_change_invalidates_effect_and_observation(self):
        self.ingest()
        result = self.composite()
        review = self.review(result["binding"])
        Image.new("RGB", self.size, "green").save(self.base / "source.png")
        with self.assertRaisesRegex(effects.TitleEffectError, "REVIEW_BINDING_STALE"):
            effects.submit_review(self.manifest, self.base, self.job, review)
        self.assertFalse(self.composite()["applied"])

    def test_changed_copy_cannot_dispatch_against_old_glyph_guide(self):
        self.prepare()
        self.job["layout"]["text_groups"][0]["headline"] = "Quiet Evening"
        self.assertEqual(effects.prepare(self.manifest, self.base, self.job)["status"], "needs_guide")
        with self.assertRaisesRegex(effects.TitleEffectError, "PREPARED_GUIDE_REQUIRED"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started", at=100)
        self.assertNotIn("title_effect_attempts", self.job)

    def test_actual_return_is_recorded_even_when_source_changed_during_tool(self):
        self.prepare()
        attempt = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", at=100)
        (self.base / "source.png").unlink()
        returned = effects.attempt_event(self.manifest, self.base, self.job, "tool_returned", attempt_id=attempt["id"], at=101)
        self.assertEqual(returned["tool_returned_at"], 101)
        self.assertEqual(returned["status"], "returned")

    def test_invalid_return_can_be_failed_and_repaired_without_resetting_history(self):
        attempt = self.start()
        failed = effects.attempt_event(self.manifest, self.base, self.job, "failed", attempt_id=attempt, at=102,
                                      reason="Returned mask crossed product boundary")
        self.assertEqual(failed["tool_returned_at"], 101)
        repair = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", kind="quality_repair", at=103,
                                      reason="Correct only the mask/title region")
        self.assertEqual(repair["status"], "started")
        self.assertEqual(len(self.job["title_effect_attempts"]), 2)

    def test_review_rejects_copy_changed_without_reprepare(self):
        self.ingest()
        result = self.composite()
        review = self.review(result["binding"])
        self.job["layout"]["text_groups"][0]["headline"] = "Quiet Evening"
        self.assertIn("TITLE_EFFECT_REVIEW_BINDING_STALE", effects.review_issues(self.job, review))

    def test_all_text_glyphs_protect_body_even_if_its_bbox_was_omitted(self):
        self.bboxes = self.bboxes[:1]
        self.job["layout"]["text_groups"][0]["decorative_effect"]["allowed_bbox_norm"] = [0, 0, 1, 1]
        attempt = self.start()
        with Image.open(self.base / "mask.png") as mask:
            mask.putpixel((20, 60), 255)
            mask.save(self.base / "body-mask.png")
        with self.assertRaisesRegex(effects.TitleEffectError, "TOUCHES_OTHER_TEXT"):
            effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "body-mask.png", attempt_id=attempt)

    def test_disable_clears_applied_observation_but_preserves_attempts(self):
        self.ingest()
        self.composite()
        self.job["layout"]["text_groups"][0].pop("decorative_effect")
        result = self.composite()
        self.assertFalse(result["applied"])
        self.assertEqual(self.job["title_effect_state"]["status"], "disabled")
        self.assertNotIn("applied", self.job["title_effect_state"])
        self.assertEqual(len(self.job["title_effect_attempts"]), 1)

    def test_monotonic_timestamps_and_output_path_safety(self):
        self.prepare()
        started = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", at=100, attempt_id="stable-attempt")
        duplicate = effects.attempt_event(self.manifest, self.base, self.job, "tool_started", at=100, attempt_id="stable-attempt")
        self.assertEqual(started, duplicate)
        with self.assertRaisesRegex(effects.TitleEffectError, "EVENT_ORDER_INVALID"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_returned", at=99, attempt_id="stable-attempt")
        effects.attempt_event(self.manifest, self.base, self.job, "tool_returned", at=101, attempt_id="stable-attempt")
        with self.assertRaisesRegex(effects.TitleEffectError, "EVENT_IMMUTABLE"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_returned", at=102, attempt_id="stable-attempt")
        effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "mask.png", attempt_id="stable-attempt")
        before = effects._hash(self.base / "flat.png")
        result = effects.composite(self.job, self.base, self.base / "flat.png", self.base / "background.png", self.base / "glyph.png",
                                   self.bboxes, output_path=self.base / "flat.png", manifest=self.manifest)
        self.assertFalse(result["applied"])
        self.assertIn("DISTINCT_LOCAL_PNG", result["fallback_reason"])
        self.assertEqual(before, effects._hash(self.base / "flat.png"))

    def test_changed_local_background_invalidates_effect_when_guide_is_rebuilt(self):
        self.ingest()
        before = self.job["title_effect_state"]["fingerprint"]
        Image.new("RGB", self.size, "#777777").save(self.base / "background.png")
        result = self.composite()
        self.assertFalse(result["applied"])
        self.assertEqual(result["fallback_reason"], "TITLE_EFFECT_CANDIDATE_STALE")
        self.assertNotEqual(before, self.job["title_effect_state"]["fingerprint"])

    def test_observation_archive_cannot_bless_tampered_candidate(self):
        self.ingest()
        result = self.composite()
        candidate = self.job["title_effect_state"]["candidate"]["artifact"]["path"]
        Image.new("RGB", self.size, "green").save(self.base / candidate)
        with self.assertRaisesRegex(effects.TitleEffectError, "ARTIFACT_CHANGED"):
            effects.submit_review(self.manifest, self.base, self.job, self.review(result["binding"]))

    def test_transparent_candidate_and_wrong_mask_mode_are_rejected(self):
        attempt = self.start()
        Image.new("RGBA", self.size, (100, 100, 100, 0)).save(self.base / "transparent.png")
        with self.assertRaisesRegex(effects.TitleEffectError, "OPAQUE_CANVAS"):
            effects.ingest(self.manifest, self.base, self.job, self.base / "transparent.png", self.base / "mask.png", attempt_id=attempt)
        Image.new("RGB", self.size, "white").save(self.base / "rgb-mask.png")
        with self.assertRaisesRegex(effects.TitleEffectError, "GRAYSCALE_MASK"):
            effects.ingest(self.manifest, self.base, self.job, self.base / "candidate.png", self.base / "rgb-mask.png", attempt_id=attempt)

    def test_layout_dependencies_are_unchanged_by_prepare_render_and_fallback(self):
        before = effects.dependencies(self.job, self.base)
        self.prepare()
        self.assertEqual(before, effects.dependencies(self.job, self.base))
        self.assertFalse(self.composite()["applied"])
        self.assertEqual(before, effects.dependencies(self.job, self.base))
        self.ingest()
        with_candidate = effects.dependencies(self.job, self.base, phase="layout")
        review_before = effects.dependencies(self.job, self.base, phase="review")
        self.assertNotEqual(before, with_candidate)
        self.assertTrue(self.composite()["applied"])
        self.assertEqual(with_candidate, effects.dependencies(self.job, self.base, phase="layout"))
        self.assertNotEqual(review_before, effects.dependencies(self.job, self.base, phase="review"))
        self.assertTrue(self.composite()["applied"])
        self.assertEqual(with_candidate, effects.dependencies(self.job, self.base, phase="layout"))
        self.assertFalse({"applied", "guide", "fingerprint", "fallback_reason"} & set(with_candidate))

    def test_body_and_label_edits_reuse_title_but_require_new_full_image_review(self):
        self.ingest()
        original = self.composite()
        old_review = self.review(original["binding"])
        candidate = copy.deepcopy(self.job["title_effect_state"]["candidate"])
        old_guide = copy.deepcopy(self.job["title_effect_state"]["guide"])
        group = self.job["layout"]["text_groups"][0]
        group.update(body="Revised exact body", label="New supporting label")
        with Image.open(self.base / "flat.png") as flat:
            ImageDraw.Draw(flat).rectangle((20, 60, 85, 65), fill="#AACCCC")
            flat.save(self.base / "flat.png")
        with Image.open(self.base / "glyph.png") as glyph:
            ImageDraw.Draw(glyph).rectangle((20, 60, 85, 65), fill=255)
            glyph.save(self.base / "glyph.png")
        self.bboxes[1]["bbox"]["width"] = 66
        result = self.composite()
        self.assertTrue(result["applied"], result)
        self.assertEqual(candidate, self.job["title_effect_state"]["candidate"])
        self.assertEqual(candidate["fingerprint"], self.job["title_effect_state"]["fingerprint"])
        self.assertNotEqual(old_guide, self.job["title_effect_state"]["guide"])
        self.assertNotEqual(original["binding"], result["binding"])
        self.assertIn("TITLE_EFFECT_REVIEW_BINDING_STALE", effects.review_issues(self.job, old_review))
        self.assertEqual(len(self.job["title_effect_attempts"]), 1)
        with Image.open(result["output_path"]) as final:
            self.assertEqual(final.getpixel((82, 62)), (170, 204, 204))

    def test_background_outside_allowed_region_does_not_spend_an_effect_attempt(self):
        self.ingest()
        previous = self.composite()
        fingerprint = self.job["title_effect_state"]["fingerprint"]
        for name in ("flat.png", "background.png"):
            with Image.open(self.base / name) as image:
                image.putpixel((195, 195), (20, 60, 100))
                image.save(self.base / name)
        result = self.composite()
        self.assertTrue(result["applied"], result)
        self.assertEqual(fingerprint, self.job["title_effect_state"]["fingerprint"])
        self.assertNotEqual(previous["binding"], result["binding"])
        self.assertEqual(len(self.job["title_effect_attempts"]), 1)

    def test_configuration_validation_is_pathless_and_requires_plain_title_guide(self):
        (self.base / "source.png").unlink()
        (self.base / "background.png").unlink()
        self.assertEqual(effects.validate_config(self.job), [])
        for kind in ("shadow", "outline"):
            with self.subTest(kind=kind):
                self.job["layout"]["text_groups"][0]["headline_treatment"] = {"kind": kind, "color": "#000000"}
                self.assertEqual(effects.validate_config(self.job), ["TITLE_EFFECT_PLAIN_GUIDE_REQUIRED"])
        self.job["layout"]["text_groups"][0]["headline_treatment"] = {"kind": "plain"}
        self.assertEqual(effects.validate_config(self.job), [])
        self.job["layout"]["text_groups"][0]["headline"] = "12 Watts"
        self.assertTrue(effects.validate_config(self.job))

    def test_disposable_layout_input_cleanup_preserves_both_dependency_phases(self):
        self.ingest()
        self.composite()
        before = {phase: effects.dependencies(self.job, self.base, phase=phase) for phase in ("layout", "review")}
        for name in ("flat.png", "background.png", "glyph.png"):
            (self.base / name).unlink()
        for phase in ("layout", "review"):
            self.assertEqual(before[phase], effects.dependencies(self.job, self.base, phase=phase))
        self.assertEqual(effects.prepare(self.manifest, self.base, self.job)["fingerprint"], self.job["title_effect_state"]["candidate"]["fingerprint"])

    def test_real_source_and_adopted_assets_invalidate_both_dependency_phases(self):
        self.ingest()
        self.composite()
        before = {phase: effects.dependencies(self.job, self.base, phase=phase) for phase in ("layout", "review")}
        Image.new("RGB", self.size, "pink").save(self.base / "source.png")
        for phase in ("layout", "review"):
            self.assertNotEqual(before[phase], effects.dependencies(self.job, self.base, phase=phase))
        with self.assertRaisesRegex(effects.TitleEffectError, "DEPENDENCY_PHASE_INVALID"):
            effects.dependencies(self.job, self.base, phase="generation")

    def test_impossible_allowed_area_is_rejected_before_a_model_attempt(self):
        self.job["layout"]["text_groups"][0]["decorative_effect"]["allowed_bbox_norm"] = [.8, .8, .1, .1]
        with self.assertRaisesRegex(effects.TitleEffectError, "OUTSIDE_ALLOWED"):
            self.prepare()
        self.assertEqual(self.job.get("title_effect_attempts", []), [])

    def test_disabled_effect_drops_assets_but_keeps_attempt_history(self):
        import lc_typography
        self.ingest(); self.composite()
        self.job["layout"]["text_groups"][0]["decorative_effect"] = {"kind": "none"}
        self.assertFalse(lc_typography.enabled(self.job))
        self.assertFalse(effects.has_effect(self.job))
        for phase in ("layout", "review"):
            self.assertEqual(effects.dependencies(self.job, self.base, phase=phase), {})
        self.assertFalse(self.composite()["applied"])
        self.assertEqual(len(self.job["title_effect_attempts"]), 1)

    def test_hold_full_shared_queue_and_failed_layout_cannot_dispatch(self):
        self.prepare()
        self.manifest.update(concurrency=2, jobs=[self.job, {"id": "a", "status": "generating"}, {"id": "b", "status": "generating"}])
        with self.assertRaisesRegex(effects.TitleEffectError, "CONCURRENCY_FULL"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started")
        self.manifest["jobs"] = [self.job]
        self.job["hold"] = True
        with self.assertRaisesRegex(effects.TitleEffectError, "NOT_READY"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started")
        self.job.pop("hold"); self.job["layout_result"] = {"passed": False}
        with self.assertRaisesRegex(effects.TitleEffectError, "PREFLIGHT_FAILED"):
            effects.attempt_event(self.manifest, self.base, self.job, "tool_started")
        self.assertEqual(self.job.get("title_effect_attempts", []), [])


if __name__ == "__main__":
    unittest.main()
