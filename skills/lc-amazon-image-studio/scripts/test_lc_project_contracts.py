"""Opt-in project design/copy gates; generated pixels are synthetic fixtures."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import lc_design as design
import lc_layout as layout
import lc_project_contracts as contracts


class ProjectContractTests(unittest.TestCase):
    def manifest(self):
        return {"style_contract": contracts.adaptive_style_contract(), "copy_budget": contracts.default_copy_budget(),
                "facts": [{"id": "indoor"}], "jobs": [{"id": "scene", "kind": "listing", "canvas": [1000, 1000],
                    "layout_input": "base.png", "layout": {"version": 3, "recipe": "photo_overlay",
                        "text_groups": [{"id": "hero", "headline": "A Gentle Glow", "body": "Indoor accent lighting",
                                         "evidence_refs": ["indoor"], "box": [.08, .07, .84, .34]}]}}]}

    def bound(self):
        m = self.manifest()
        contracts.apply_project_contracts(m)
        return m, m["jobs"][0]

    def test_no_contract_is_legacy_noop(self):
        m = {"jobs": [{"id": "old", "layout": {"version": 2, "headline": "Old title", "text_color": "#000000"}}]}
        old = copy.deepcopy(m)
        self.assertEqual(contracts.apply_project_contracts(m), [])
        self.assertEqual(m, old)
        self.assertTrue(contracts.project_contract_report(m)["passed"])

    def test_adaptive_style_preserves_explicit_group_and_brief_choices(self):
        m, job = self.bound()
        job["design_brief"] = {"layout": {"text_color": "#FF0000", "headline_family": "serif"}}
        job["layout"].update(text_color="#0000FF", headline_weight=600)
        group = job["layout"]["text_groups"][0]
        group.update(text_color="#FFFFFF", headline_weight=400, headline_family="serif", mobile_sizes={"headline": 18})
        before = copy.deepcopy(job)
        actual = layout.resolve_layout_defaults(job)
        self.assertEqual(job, before)
        self.assertEqual(actual["text_color"], "#0000FF")
        self.assertEqual(actual["text_groups"][0]["text_color"], "#FFFFFF")
        self.assertEqual(actual["text_groups"][0]["headline_family"], "serif")
        self.assertEqual(actual["text_groups"][0]["headline_weight"], 400)
        self.assertEqual(actual["text_groups"][0]["mobile_sizes"], {"headline": 18})
        self.assertNotIn("surface", actual["text_groups"][0])

    def test_main_has_no_copy_and_native_needs_explicit_reason(self):
        m, job = self.bound()
        job["kind"] = "main"
        contracts.apply_project_contracts(m)
        self.assertEqual(job["text_mode"], "none")
        self.assertTrue(design.validate_design(job))
        job.update(kind="listing", text_mode="model_native", layout={}, copy={"headline": "Etched Into Wood"})
        self.assertIn("model_native_reason", " ".join(design.validate_design(job)))
        job["model_native_reason"] = {"kind": "integrated_material", "notes": "The requested letters are carved into a prop."}
        self.assertEqual(design.validate_design(job), [])
        payload = design.design_generation_payload(job)["project_typography"]
        self.assertEqual(payload["selection"], "adaptive_per_image")
        self.assertNotIn("text_color", payload)

    def test_local_palette_and_copy_do_not_enter_model_payload(self):
        m, job = self.bound()
        before = design.design_generation_payload(job)
        m["style_contract"] = {**contracts.legacy_style_contract(), "text_color": "#FFF0D4", "surface_color": "#241811"}
        contracts.apply_project_contracts(m)
        job["layout"]["text_groups"][0]["headline"] = "Fresh Copy"
        self.assertEqual(design.design_generation_payload(job), before)

    def test_invalid_contracts_report_errors_before_any_mutation(self):
        for field, value in (("style_contract", None), ("style_contract", {"text_color": "red"}),
                             ("style_contract", {"mobile_sizes": None}), ("style_contract", {"version": 1, "text_color": "#FFFFFF", "surface_color": "#FFFFFF"}),
                             ("copy_budget", {"target_ratio": .7}), ("copy_budget", {"baseline_words": True}),
                             ("copy_budget", {"baseline_words": 10, "tolerance": [float("nan"), .8]})):
            m = self.manifest(); m[field] = value
            old = copy.deepcopy(m)
            self.assertTrue(contracts.validate_project_contracts(m))
            with self.assertRaises(ValueError):
                contracts.apply_project_contracts(m)
            self.assertEqual(m, old)

    def test_budget_counts_rendered_copy_and_preserves_required_facts(self):
        m, job = self.bound()
        m["copy_budget"].update(baseline_words=10, required_text=[{"job_id": "scene", "text": "Indoor"}], required_fact_ids=["indoor"])
        job["layout"]["text_groups"][0]["body"] = "Warm indoor accent lighting"
        report = contracts.project_contract_report(m)
        self.assertEqual(report["words"], 7)
        self.assertEqual(report["allowed_words"], [7, 7])
        self.assertTrue(report["passed"], report)
        job["layout"]["text_groups"][0]["body"] = "Warm outdoor accent lighting"
        report = contracts.project_contract_report(m)
        self.assertIn("COPY_REQUIRED_TEXT_MISSING", " ".join(report["issues"]))
        job["layout"]["text_groups"][0]["evidence_refs"] = []
        self.assertIn("COPY_REQUIRED_FACT_MISSING", " ".join(contracts.project_contract_report(m)["issues"]))

    def test_budget_range_fails_without_truncating_or_inventing_baseline(self):
        m, job = self.bound()
        self.assertNotIn("baseline_words", m["copy_budget"])
        m["copy_budget"]["baseline_words"] = 30
        before = copy.deepcopy(job)
        report = contracts.project_contract_report(m)
        self.assertFalse(report["passed"])
        self.assertIn("COPY_BUDGET", " ".join(report["issues"]))
        self.assertEqual(job, before)

    def test_density_preserves_faq_and_dimensions_but_not_ordinary_paragraphs(self):
        m, job = self.bound()
        job["layout"]["text_groups"][0]["body"] = " ".join(["necessary"] * 30)
        self.assertFalse(contracts.project_contract_report(m)["passed"])
        job["copy_role"] = "faq"
        self.assertTrue(contracts.project_contract_report(m)["passed"])
        del job["copy_role"]
        job["layout"]["template"] = "dimensions"
        self.assertTrue(contracts.project_contract_report(m)["passed"])

    def test_word_units_include_measurements_and_non_latin_copy(self):
        self.assertEqual(contracts.word_count("4.4 in × 3.54 in"), 4)
        self.assertEqual(contracts.word_count("Energy-Efficient Plug-In SMALL-SPACE"), 3)
        self.assertEqual(contracts.word_count("Warm灯光"), 3)
        self.assertEqual(contracts.word_count("室内照明"), 4)
        self.assertEqual(contracts.word_count("ضوء داخلي"), 2)
        self.assertEqual(contracts.word_count("ضَوْء داخلي"), 2)

    def test_report_applies_project_rules_without_a_prior_prepare(self):
        m = self.manifest()
        m["jobs"][0].update(text_mode="model_native", layout={}, copy={"headline": "Ordinary Marketing"})
        self.assertIn("model_native_reason", " ".join(contracts.project_contract_report(m)["issues"]))
        self.assertNotIn("_project_style", m["jobs"][0])

    def test_contract_removal_restores_original_layout_and_no_copy_loss(self):
        m, job = self.bound()
        old = copy.deepcopy(job["layout"])
        m.pop("style_contract")
        contracts.apply_project_contracts(m)
        self.assertNotIn("_project_style", job)
        self.assertEqual(job["layout"], old)

    def test_binding_can_be_scoped_to_a_transaction_job(self):
        m = self.manifest()
        m["jobs"].append({"id": "other", "kind": "main"})
        other = copy.deepcopy(m["jobs"][1])
        self.assertEqual(contracts.apply_project_contracts(m, ["scene"]), ["scene"])
        self.assertEqual(other, m["jobs"][1])

    def test_renderer_receives_single_ink_for_icons_and_labels(self):
        m = self.manifest(); m["style_contract"] = contracts.legacy_style_contract(); contracts.apply_project_contracts(m); job = m["jobs"][0]
        job["layout"].update(template="benefits", items=[{"text": "Indoor", "icon": "check", "evidence_refs": ["indoor"]}])
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); Image.new("RGB", (1000, 1000), "white").save(base / "base.png")
            prepared = layout._prepare_job(m, base, job)
            self.assertEqual(prepared["ink"], prepared["theme"]["accent"])
            self.assertEqual(prepared["graphic_text_color"], prepared["ink"])
            self.assertEqual(prepared["label_weight"], 400)
            self.assertEqual(layout._prepared_font_weights(prepared), {400, 700})

    def test_preflight_checks_fonts_geometry_and_never_claims_image_review(self):
        m, job = self.bound()
        report = contracts.preflight_project_contracts(m, Path("."))
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["typography_preflight"], [{"id": "scene", "passed": True}])
        self.assertNotIn("qa_verdict", job)
        job["layout"]["text_groups"][0]["body"] = "Unsupported \U0010ffff"
        report = contracts.preflight_project_contracts(m, Path("."))
        self.assertFalse(report["passed"])
        self.assertIn("missing bundled glyphs", " ".join(report["issues"]))

    def test_adaptive_typography_binds_actual_background_and_uses_surface_when_needed(self):
        m, job = self.bound()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            Image.new("RGB", (1000, 1000), "white").save(base / "base.png")
            changed = contracts.apply_adaptive_typography(m, job, base)
            self.assertTrue(changed)
            decision = job["typography_decision"]
            group = job["layout"]["text_groups"][0]
            self.assertEqual(decision["rendering_route"], "local_overlay")
            self.assertEqual(decision["background"]["path"], "base.png")
            self.assertIn(group["text_color"], {"#17212B", "#111111"})
            self.assertFalse(contracts.apply_adaptive_typography(m, job, base))
            image = Image.new("RGB", (1000, 1000), "white")
            image.paste("black", (0, 0, 500, 1000)); image.save(base / "base.png")
            self.assertTrue(contracts.apply_adaptive_typography(m, job, base))
            self.assertEqual(group["surface"]["kind"], "solid")
            record = decision = job["typography_decision"]["background"]["groups"]["hero"]
            self.assertTrue(record["surface_added"])
            self.assertGreaterEqual(record["contrast_min"], 4.5)

    def test_surface_embedded_3d_is_limited_to_short_decorative_native_copy(self):
        m, job = self.bound()
        job.update(text_mode="model_native", layout={}, copy={"headline": "Made to Glow"}, claim_ids=[],
                   model_native_reason={"kind": "artistic_lettering", "notes": "The decorative headline is part of the scene."},
                   embedding_decision={"kind": "surface_embedded_3d", "reason": "A decorative scene headline improves the composition.",
                                       "surface": "A visible wooden backdrop", "material_lighting": "Raking warm light reveals the raised letters."})
        self.assertEqual(design.validate_design(job), [])
        job["copy"]["body"] = "Includes a confirmed feature"
        self.assertIn("cannot carry body", " ".join(design.validate_design(job)))

    def test_real_text_fit_preflight_is_cached_and_does_not_approve_pixels(self):
        m, job = self.bound()
        with patch("lc_layout.render_batch", wraps=layout.render_batch) as renderer:
            report = contracts.preflight_layout_fit(m, Path("."), ["scene"])
        self.assertTrue(report["passed"], report)
        self.assertFalse(report["jobs"][0]["cached"])
        self.assertTrue(renderer.call_args.kwargs["measure_only"])
        self.assertNotIn("qa_verdict", job)
        self.assertNotIn("text_contrast", [c["check"] for c in report["jobs"][0]["checks"]])
        with patch("lc_layout.render_batch", side_effect=AssertionError("unchanged text must not render again")):
            cached = contracts.preflight_layout_fit(m, Path("."), ["scene"])
            self.assertTrue(cached["jobs"][0]["cached"])
        job["layout"]["text_groups"][0]["body"] = " ".join(["Overflow"] * 50)
        failed = contracts.preflight_layout_fit(m, Path("."), ["scene"])
        self.assertFalse(failed["passed"])
        self.assertNotIn("qa_verdict", job)


if __name__ == "__main__":
    unittest.main()
