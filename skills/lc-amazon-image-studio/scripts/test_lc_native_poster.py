"""Opt-in native poster validation; no credentials, model calls or image verdicts."""
import copy
import unittest

import lc_design as design
import lc_image_pipeline as pipeline
import lc_project_contracts as contracts


class NativePosterTests(unittest.TestCase):
    def job(self):
        return {
            "kind": "listing", "render_mode": "reference_generate", "text_mode": "model_native",
            "prompt_profile": "images_2_5_v1", "image_intent": "lifestyle_hero", "layout": {},
            "_project_style": {"version": 3},
            "model_native_reason": {"kind": "native_poster", "notes": "Integrate a flat title and short finish description."},
            "copy": {"headline": "Gentle Light for Comfortable Evenings at Home", "body": "A soft matte finish"},
            "claim_ids": ["matte_finish"],
        }

    def test_flat_title_over_five_words_and_evidenced_short_benefit_are_supported(self):
        job = self.job()
        self.assertEqual(design.validate_design(job), [])
        self.assertFalse(design.needs_local_layout(job))
        self.assertEqual(contracts.style_job_issues(job), [])
        self.assertTrue(all(block["evidence_refs"] == ["matte_finish"] for block in design.copy_blocks(job)))
        manifest = {"references": [], "facts": [{"id": "matte_finish", "text": "Matte surface finish",
                                                  "evidence": "Synthetic fixture fact only"}]}
        self.assertEqual(pipeline.claim_issues(manifest, job), [])
        manifest["facts"][0]["evidence"] = ""
        self.assertIn("CLAIM_EVIDENCE_MISSING:matte_finish", pipeline.claim_issues(manifest, job))
        job["claim_ids"] = ["missing_fact"]
        self.assertIn("CLAIM_EVIDENCE_MISSING:missing_fact", pipeline.claim_issues(manifest, job))

    def test_native_poster_requires_explicit_profile_mode_and_notes_without_style_contract(self):
        for field, value in (("prompt_profile", "legacy"), ("prompt_profile", None),
                             ("text_mode", "none"), ("text_mode", "local_overlay")):
            job = self.job()
            job.pop("_project_style")
            job[field] = value
            with self.subTest(field=field, value=value):
                self.assertIn("native_poster requires", " ".join(design.validate_design(job)))
        job = self.job()
        job.pop("prompt_profile")
        self.assertIn("native_poster requires", " ".join(design.validate_design(job)))
        for notes in (None, "", "   ", [], 42):
            job = self.job()
            job.pop("_project_style")
            job["model_native_reason"]["notes"] = notes
            with self.subTest(notes=notes):
                self.assertIn("specific model_native_reason notes", " ".join(design.validate_design(job)))

    def test_invalid_prompt_profiles_are_rejected_even_without_marketing_text(self):
        for profile in (None, [], {}, True, 1, "", "images_2_5", "unverified"):
            with self.subTest(profile=profile):
                self.assertIn("prompt_profile must be", " ".join(design.validate_design(
                    {"text_mode": "none", "prompt_profile": profile})))
        for job in ({"text_mode": "none"}, {"text_mode": "none", "prompt_profile": "legacy"},
                    {"text_mode": "none", "prompt_profile": "images_2_5_v1"}):
            self.assertEqual(design.validate_design(job), [])

    def test_ascii_and_unicode_numeric_copy_is_rejected_in_both_blocks(self):
        for numeral in ("2", "２", "٢", "²", "②", "⅓", "二"):
            for field in ("headline", "body"):
                job = self.job()
                job["copy"][field] = f"Confirmed {numeral} items"
                with self.subTest(numeral=numeral, field=field):
                    self.assertIn("cannot contain numeric copy", " ".join(design.validate_design(job)))

    def test_explicit_precision_intents_keep_local_copy(self):
        for intent in ("dimensions", "specifications", "steps", "FAQ", "step-by-step", "how_to",
                       "assembly", "installation", "setup", ["lifestyle_hero", "faq"]):
            job = self.job()
            job["image_intent"] = intent
            with self.subTest(intent=intent):
                self.assertIn("explicit precision-copy intents", " ".join(design.validate_design(job)))
        for key in ("layout", "design_brief"):
            for layout in ({"template": "dimensions"}, {"template": "components"}, {"recipe": "steps"},
                           {"faq": [{}]}):
                job = self.job()
                job[key] = layout if key == "layout" else {"layout": layout}
                with self.subTest(key=key, layout=layout):
                    self.assertIn("explicit precision-copy intents", " ".join(design.validate_design(job)))
        job = self.job()
        job["copy_role"] = "faq"
        self.assertIn("explicit precision-copy intents", " ".join(design.validate_design(job)))

    def test_native_poster_keeps_copy_shape_length_and_single_source_rules(self):
        job = self.job()
        job["copy"] = {"headline": "A" * 180, "body": "B" * 200}
        self.assertEqual(design.validate_design(job), [])
        for copy_value in ({"headline": "A" * 181}, {"headline": "Title", "body": "B" * 201},
                           None, {}, {"headline": ""}, {"headline": "Title", "body": None},
                           {"headline": "Title", "label": "Extra block"}):
            candidate = copy.deepcopy(job)
            candidate["copy"] = copy_value
            with self.subTest(copy=copy_value):
                self.assertTrue(design.validate_design(candidate))
        for layout in ({"headline": "Duplicate"}, {"text_groups": [{"headline": "Duplicate"}]},
                       {"items": [{"icon": "leaf"}]}, {"panels": [{"image": "fixture.png"}]}):
            candidate = copy.deepcopy(job)
            candidate["layout"] = layout
            with self.subTest(layout=layout):
                self.assertIn("cannot also contain local", " ".join(design.validate_design(candidate)))
        for field, value in (("kind", "main"), ("render_mode", "pixel_composite")):
            candidate = copy.deepcopy(job)
            candidate[field] = value
            self.assertIn("unavailable for main images or pixel_composite", " ".join(design.validate_design(candidate)))

    def test_artistic_native_behavior_and_legacy_error_remain_unchanged(self):
        for kind in ("artistic_lettering", "integrated_material"):
            for profile in (None, "legacy", "images_2_5_v1"):
                job = self.job()
                job["model_native_reason"]["kind"] = kind
                job["copy"]["body"] = "Existing native copy with 2 supported items"
                if profile is None:
                    job.pop("prompt_profile")
                else:
                    job["prompt_profile"] = profile
                with self.subTest(kind=kind, profile=profile):
                    self.assertEqual(design.validate_design(job), [])
        job = self.job()
        job.pop("prompt_profile")
        job.pop("model_native_reason")
        self.assertEqual(contracts.style_job_issues(job), [
            "model_native requires model_native_reason kind artistic_lettering/integrated_material and specific notes; ordinary copy uses local_overlay"])
        job.pop("_project_style")
        self.assertEqual(design.validate_design(job), [])

    def test_three_dimensional_lettering_stays_separate_and_restricted(self):
        job = self.job()
        job.update(copy={"headline": "Soft Evening Glow"}, claim_ids=[], embedding_decision={
            "kind": "surface_embedded_3d", "reason": "Decorative scene lettering", "surface": "A backdrop",
            "material_lighting": "Soft raking light across the backdrop"})
        self.assertIn("native_poster is flat typography", " ".join(design.validate_design(job)))
        job["model_native_reason"]["kind"] = "artistic_lettering"
        self.assertEqual(design.validate_design(job), [])
        for copy_value, claim_ids in (({"headline": "A Decorative Headline With More Than Five Words"}, []),
                                      ({"headline": "Glow 2"}, []), ({"headline": "Glow", "body": "Extra copy"}, []),
                                      ({"headline": "Glow"}, ["matte_finish"])):
            candidate = copy.deepcopy(job)
            candidate.update(copy=copy_value, claim_ids=claim_ids)
            with self.subTest(copy=copy_value, claim_ids=claim_ids):
                self.assertTrue(design.validate_design(candidate))


if __name__ == "__main__":
    unittest.main()
