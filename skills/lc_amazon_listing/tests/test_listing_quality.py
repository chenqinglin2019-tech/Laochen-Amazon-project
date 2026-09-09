"""Regression tests for deterministic listing quality checks (no live backend)."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "listing_quality.py"
SPEC = importlib.util.spec_from_file_location("listing_quality", SCRIPT)
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def claims(measurement=None):
    return [{"field": field, "fact_ids": ["material"],
             "measurement_ids": [measurement] if measurement and field == "description" else []}
            for field in quality.FRONT_FIELDS]


def plan(pid, role, target="all", mid=None, image=None):
    return {"plan_id": pid, "role": role, "applies_to": [target],
            "image": "图1（主图）" if role == "main" else "图2（实物特写）",
            "module": "模块1：材质细节", "asset_type": "image", "direction": "展示真实产品轮廓与材质细节。",
            "buyer_question": "用在哪里？", "selling_point": "真实材质", "visual_evidence": "实物特写",
            "scene_intent": "桌面使用", "overlay_text": "" if role == "main" else "304 Stainless Steel",
            "fact_ids": ["material"], "measurement_ids": [mid] if mid else [],
            "source_image_ids": [image or "product-photo"], "body_refs": ["description"],
            "mobile_check": "手机端检查清楚", "production_notes": "需要补拍实际产品及对应变体，不得伪造素材"}


def complete_media(profile, listing, strategy=None):
    """Full deterministic fixture sets; editorial examples live in knowledge/examples."""
    family = profile.get("listing_mode") == "family"
    listing["media_strategy"] = strategy or ("per_variant_full" if family else "single")
    listing["image_plan"] = [plan("main", "main")]
    listing["a_plus_plan"] = [plan("aplus" if n == 1 else "aplus-%d" % n, "aplus") for n in range(1, 6)]
    for n, item in enumerate(listing["a_plus_plan"], 1):
        item["module"] = "模块%d：产品使用" % n
    shared = {"main": "main", "secondary": [], "a_plus": [p["plan_id"] for p in listing["a_plus_plan"]]}
    for n in range(2, 8):
        item = plan("secondary-%d" % n, "secondary")
        item["image"] = "图%d（产品细节）" % n
        listing["image_plan"].append(item)
        shared["secondary"].append(item["plan_id"])
    listing["image_sets"] = {"shared": shared, "variants": []}
    for variant in profile.get("variants", []) if family else []:
        vid = variant["variant_id"]
        main = plan(vid + "-main", "main", vid)
        listing["image_plan"].append(main)
        child = {"variant_id": vid, "main": main["plan_id"], "secondary": []}
        if listing["media_strategy"] == "shared_secondary":
            child["secondary"] = list(shared["secondary"])
        else:
            for n in range(2, 8):
                item = plan(vid + "-secondary-%d" % n, "secondary", vid)
                item["image"] = "图%d（产品细节）" % n
                listing["image_plan"].append(item)
                child["secondary"].append(item["plan_id"])
        listing["image_sets"]["variants"].append(child)


def single_fixture():
    profile = {
        "schema_version": "2.1", "listing_mode": "single", "site": "US", "listing_language": "English",
        "listing_language_code": "en", "brand": "ACME", "category": "Desk Organizers",
        "product_identity": {"original_name": "笔筒", "canonical_name": "Pen Holder", "protected_terms": ["Pen Holder"]},
        "facts": [{"fact_id": "material", "field": "material", "value": "304 Stainless Steel",
                   "status": "confirmed", "source_ref": "user specification"}],
        "measurements": [{"measurement_id": "height", "kind": "length", "subject": "product", "label": "height",
                          "value": "15.24", "unit": "cm", "source_ref": "drawing"}],
        "images": [{"image_id": "product-photo", "source": "fixture:reference-material", "applies_to": ["all"]}], "forbidden_terms": []}
    profile = quality.normalize_profile(profile)
    listing = {"schema_version": "2.1", "listing_mode": "single", "site": "US", "listing_language": "English",
               "brand_name": "ACME", "buyer_question_coverage": [], "excluded_claims": [],
               "listing_language_code": "en", "title": "ACME 304 Stainless Steel Pen Holder",
               "item_highlight": "Keep writing tools together on your desk.",
               "bullets": ["【MATERIAL】304 stainless steel body.", "【ORGANIZATION】Keeps pens together.", "【PLACEMENT】For a desk or shelf.",
                           "【ACCESS】Open top provides access.", "【FIT】Check your available space before ordering."],
               "description": "This 304 stainless steel pen holder is 6 in high.",
               "search_terms": "stationery organizer", "claims": claims("height"),
               "image_plan": [], "a_plus_plan": []}
    complete_media(profile, listing)
    qa = {"site": "US", "status": "completed", "requested_keywords": ["pen holder"], "qa_pairs": [
        {"keyword": "pen holder", "questions": ["What material is it?"]}], "question_reviews": [
            {"question": "What material is it?", "keyword": "pen holder", "relevance": "relevant",
             "fact_ids": ["material"], "applies_to": ["all"], "disposition": "answered"}]}
    return profile, listing, qa


def family_fixture():
    profile, single, qa = single_fixture()
    profile.update({"listing_mode": "family", "parent_sku": "PARENT", "measurements": [],
                    "variation_dimensions": ["color", "size"],
                    "variation_theme": {"name": "ColorSize", "source_ref": "supplied category template", "status": "confirmed"},
                    "variants": []})
    for index, (color, size, cm) in enumerate((("Black", "M", "15.24"), ("Blue", "S", "10.16"), ("Blue", "M", "15.24")), 1):
        vid = "child-%02d" % index
        profile["variants"].append({"variant_id": vid, "sku": None if index == 1 else "SKU-%d" % index,
                                    "asin": None, "attributes": {
                                        "color": {"value": color, "display": color, "title_value": color},
                                        "size": {"value": size, "display": size, "title_value": size}},
                                    "facts": [], "measurements": [{"measurement_id": "height-%d" % index,
                                        "kind": "length", "subject": "product", "label": "height",
                                        "value": cm, "unit": "cm", "source_ref": "drawing %d" % index}], "image_ids": []})
    profile = quality.normalize_profile(profile)
    listing = {"schema_version": "2.1", "listing_mode": "family", "site": "US", "listing_language": "English",
               "brand_name": "ACME", "buyer_question_coverage": [], "excluded_claims": [],
               "listing_language_code": "en", "parent": {"sku": "PARENT", "title": single["title"],
                   "item_highlight": single["item_highlight"], "claims": claims()[:2]},
               "title_template": "ACME 304 Stainless Steel Pen Holder, {color}, {size}",
               "shared_content": {k: single[k] for k in quality.CONTENT_FIELDS}, "variants": [],
               "image_plan": [], "a_plus_plan": []}
    listing["shared_content"]["description"] = "This pen holder is made of 304 stainless steel."
    for index, variant in enumerate(profile["variants"], 1):
        attrs = {k: v["title_value"] for k, v in variant["attributes"].items()}
        listing["variants"].append({"variant_id": variant["variant_id"], "sku": variant["sku"], "attributes": attrs,
            "title": listing["title_template"].format_map(attrs), "item_highlight": single["item_highlight"],
            "content_overrides": {"description": "This pen holder is %s high." % variant["measurements"][0]["display_text"]},
            "claims": claims("height-%d" % index)})
    complete_media(profile, listing)
    return profile, listing, qa


def codes(profile, listing, qa=None):
    return {issue["code"] for issue in quality.check_local(profile, listing, qa) if issue["severity"] == "error"}


def completed_acceptance(profile, listing, qa):
    fingerprints = {"profile_sha256": "a" * 64, "listing_sha256": "b" * 64, "qa_sha256": "c" * 64}
    policy = quality.load_json(quality.POLICY_PATH)
    targets = ["single"] if profile["listing_mode"] == "single" else ["parent"] + [v["variant_id"] for v in profile["variants"]]
    review = {"fingerprints": fingerprints, "records": [
        {"target": target, "check": check, "status": "pass", "evidence": "Fixture reviewed against supplied facts."}
        for target in targets for check in policy["semantic_checks"]] + [
        {"target": "media", "check": "image_truth", "status": "pass", "evidence": "Fixture plans refer to supplied facts."}]}
    backend = {"records": [{"target": p["target"], "payload_sha256": p["payload_sha256"], "exit_code": 0,
                            "response": {"ok": True, "errors": []}} for p in quality.build_payloads(profile, listing)]}
    return fingerprints, review, backend


class NormalizationTests(unittest.TestCase):
    def test_exact_and_rounded_conversion_preserves_source(self):
        profile, _, _ = single_fixture()
        profile["measurements"][0]["value"] = "10"
        result = quality.normalize_profile(profile)
        record = result["measurements"][0]
        self.assertEqual((record["value"], record["unit"]), ("10", "cm"))
        self.assertEqual((record["display_text"], record["approximate"]), ("3.94 in", True))
        self.assertEqual(profile["measurements"][0]["display_text"], "6 in")

    def test_units_and_half_up(self):
        profile, _, _ = single_fixture()
        for value, unit, expected in (("25.4", "mm", "1 in"), ("1", "m", "39.37 in"),
                                      ("1.5", "ft", "18 in"), ("1.005", "in", "1.01 in")):
            with self.subTest(unit=unit):
                profile["measurements"][0].update(value=value, unit=unit)
                self.assertEqual(quality.normalize_profile(profile)["measurements"][0]["display_text"], expected)

    def test_non_us_preserves_metric_and_nominal_unchanged(self):
        profile, _, _ = single_fixture()
        profile["site"] = "DE"
        self.assertEqual(quality.normalize_profile(profile)["measurements"][0]["display_text"], "15.24 cm")
        profile["site"] = "US"
        profile["measurements"][0].update(kind="nominal", value="M8", unit="thread")
        self.assertEqual(quality.normalize_profile(profile)["measurements"][0]["display_text"], "M8 thread")
        profile["measurements"][0].update(kind="size", value="M", unit="US")
        self.assertEqual(quality.normalize_profile(profile)["measurements"][0]["display_text"], "M US")

    def test_missing_units_nonfinite_zero_and_mass_volume_confusion_rejected(self):
        for update in ({"unit": None}, {"value": None}, {"value": "NaN"}, {"value": "Infinity"}, {"value": "0"},
                       {"value": "0.001", "unit": "cm"}, {"kind": "weight", "unit": "fl oz"},
                       {"kind": "volume", "unit": "oz"}):
            with self.subTest(update=update):
                profile, _, _ = single_fixture()
                profile["measurements"][0].update(update)
                with self.assertRaises(ValueError):
                    quality.normalize_profile(profile)

    def test_per_variant_attributes_and_ids(self):
        profile, _, _ = family_fixture()
        for index, variant in enumerate(profile["variants"], 1):
            variant.pop("variant_id")
            variant["attributes"]["size"]["measurement_id"] = "height-%d" % index
        output = quality.normalize_profile(profile)
        self.assertEqual([v["variant_id"] for v in output["variants"]], ["child-01", "child-02", "child-03"])
        self.assertEqual([v["attributes"]["size"]["title_value"] for v in output["variants"]], ["6 in", "4 in", "6 in"])
        self.assertEqual(output["variants"][0]["sku"], None)
        self.assertEqual(quality.normalize_profile(output), output)

    def test_cross_child_attribute_reference_cannot_normalize(self):
        profile, _, _ = family_fixture()
        profile["variants"][0]["attributes"]["size"]["measurement_id"] = "height-2"
        with self.assertRaises(ValueError):
            quality.normalize_profile(profile)

    def test_duplicate_measurement_ids_rejected(self):
        profile, _, _ = family_fixture()
        profile["variants"][1]["measurements"][0]["measurement_id"] = "height-1"
        with self.assertRaises(ValueError):
            quality.normalize_profile(profile)


class LocalValidationTests(unittest.TestCase):
    def test_single_and_sparse_family_are_valid(self):
        for fixture in (single_fixture, family_fixture):
            with self.subTest(mode=fixture.__name__):
                profile, listing, qa = fixture()
                self.assertEqual(quality.check_local(profile, listing, qa), [])

    def test_critical_identity_never_replaced_by_generic_keyword(self):
        profile, listing, _ = single_fixture()
        listing["title"] = "ACME Stainless Steel Stationery Organizer"
        self.assertIn("identity_dropped", codes(profile, listing))
        listing["title"] = "ACME Pen-Holder"
        self.assertNotIn("identity_dropped", codes(profile, listing))
        listing["title"] = "ACME Pen Writing Holder"
        self.assertIn("identity_dropped", codes(profile, listing))

    def test_title_and_highlight_boundaries_and_search_utf8(self):
        profile, listing, _ = single_fixture()
        listing["title"] = "Pen Holder " + "a" * 64
        listing["item_highlight"] = "x" * 125
        listing["search_terms"] = "中" * 83
        self.assertNotIn("field_length", codes(profile, listing))
        self.assertNotIn("search_bytes", codes(profile, listing))
        listing["title"] += "a"
        listing["item_highlight"] += "x"
        listing["search_terms"] += "a"
        self.assertIn("field_length", codes(profile, listing))
        self.assertIn("search_bytes", codes(profile, listing))

    def test_bullets_count_length_and_highlight_type(self):
        profile, listing, _ = single_fixture()
        listing["bullets"] = ["x" * 201] * 5
        self.assertIn("bullets_length", codes(profile, listing))
        listing["bullets"].pop()
        listing["item_highlight"] = ["not a string"]
        self.assertTrue({"bullets_shape", "text_field"} <= codes(profile, listing))

    def test_missing_extra_and_reordered_variants_fail(self):
        for mutation in (lambda x: x.pop(), lambda x: x.append(copy.deepcopy(x[0])), lambda x: x.reverse()):
            profile, listing, _ = family_fixture()
            mutation(listing["variants"])
            self.assertIn("variant_set_order", codes(profile, listing))

    def test_duplicate_sku_and_combination_and_unsafe_id(self):
        profile, listing, _ = family_fixture()
        profile["variants"][0]["sku"] = "PARENT"
        profile["variants"][1]["attributes"] = copy.deepcopy(profile["variants"][0]["attributes"])
        profile["variants"][2]["variant_id"] = "../escape"
        self.assertTrue({"sku", "duplicate_combination", "variant_id"} <= codes(profile, listing))

    def test_missing_variant_values_and_ambiguous_colors(self):
        profile, listing, _ = family_fixture()
        profile["variants"][0]["attributes"]["size"]["value"] = ""
        profile["variants"][0]["attributes"]["color"]["title_value"] = "Black 1"
        self.assertTrue({"attribute_value", "ambiguous_color"} <= codes(profile, listing))

    def test_parent_values_leak_but_304_material_does_not(self):
        profile, listing, _ = family_fixture()
        self.assertNotIn("parent_variant_leak", codes(profile, listing))
        listing["parent"]["title"] += ", Black"
        listing["parent"]["item_highlight"] = "Size M for your desk."
        self.assertIn("parent_variant_leak", codes(profile, listing))

    def test_parent_price_and_pack_count(self):
        for suffix in (" $10", " 2 Pack", " Pack of 3", " Stock 20"):
            profile, listing, _ = family_fixture()
            listing["parent"]["title"] += suffix
            self.assertIn("parent_price_quantity", codes(profile, listing))

    def test_one_template_and_attribute_order(self):
        profile, listing, _ = family_fixture()
        listing["variants"][1]["title"] = "ACME Pen Holder, S, Blue"
        self.assertIn("title_template_mismatch", codes(profile, listing))
        listing["title_template"] = "Pen Holder {size}, {color}"
        self.assertIn("title_template", codes(profile, listing))
        listing["title_template"] = "Pen Holder {color.__class__} {size}"
        self.assertIn("title_template", codes(profile, listing))

    def test_measurement_conversion_staleness_source_leak_and_wrong_child_ref(self):
        profile, listing, _ = family_fixture()
        listing["variants"][0]["content_overrides"]["description"] = "This pen holder is 15.24 cm high."
        self.assertTrue({"measurement_text", "source_unit_leak"} <= codes(profile, listing))
        profile["variants"][0]["measurements"][0]["display_text"] = "99 in"
        self.assertIn("measurement_display", codes(profile, listing))
        listing["variants"][1]["claims"][-1]["measurement_ids"] = ["height-1"]
        self.assertIn("reference_scope", codes(profile, listing))

    def test_compact_reformatted_and_unregistered_lengths(self):
        for text in ("15.24cm", "15.240 cm", "15 cm", "15 millimeters"):
            profile, listing, _ = single_fixture()
            listing["item_highlight"] = "Height: " + text
            self.assertIn("source_unit_leak", codes(profile, listing))
        profile, listing, _ = single_fixture()
        listing["item_highlight"] = "Height: 99 in"
        self.assertIn("measurement_unregistered", codes(profile, listing))

    def test_cross_child_unannotated_dimension_and_shared_leak(self):
        profile, listing, _ = family_fixture()
        listing["variants"][1]["item_highlight"] = "Height: 6 in"
        self.assertIn("measurement_wrong_variant", codes(profile, listing))
        listing["shared_content"]["description"] = "Height: 4 in"
        found = quality.check_local(profile, listing)
        self.assertTrue(any(i["code"] == "measurement_wrong_variant" and i["path"] == "listing.shared_content.description" for i in found))

    def test_registered_nominal_metric_exception(self):
        profile, listing, _ = single_fixture()
        profile["measurements"].append({"measurement_id": "nominal", "kind": "nominal", "subject": "fit", "label": "nominal size",
                                         "value": "10", "unit": "cm", "source_ref": "manufacturer nominal specification"})
        profile = quality.normalize_profile(profile)
        listing["item_highlight"] = "Nominal size: 10 cm"
        listing["claims"][1]["measurement_ids"] = ["nominal"]
        self.assertEqual(codes(profile, listing), set())

    def test_japanese_contiguous_phrase_and_metadata(self):
        profile, listing, _ = single_fixture()
        profile.update(site="JP", listing_language="Japanese", listing_language_code="ja")
        listing.update(site="JP", listing_language="Japanese", listing_language_code="ja", title="小型ガラスコップセット")
        profile["product_identity"].update(canonical_name="ガラスコップ", protected_terms=["ガラスコップ"])
        profile = quality.normalize_profile(profile)
        listing["description"] = "高さ 15.24 cm"
        self.assertNotIn("identity_dropped", codes(profile, listing))
        listing["title"] = "ガラス製のかわいいコップ"
        self.assertIn("identity_dropped", codes(profile, listing))
        listing["listing_language_code"] = "en"
        self.assertIn("language_metadata", codes(profile, listing))
        self.assertFalse(quality._contains("infrared", "Red"))

    def test_facts_must_be_confirmed_and_in_scope(self):
        profile, listing, _ = family_fixture()
        profile["variants"][0]["facts"] = [{"fact_id": "child-material", "field": "material", "value": "aluminum",
                                          "status": "confirmed", "source_ref": "user"}]
        listing["variants"][1]["claims"][0]["fact_ids"] = ["child-material"]
        self.assertIn("reference_scope", codes(profile, listing))
        profile["facts"][0]["status"] = "unknown"
        self.assertIn("unconfirmed_fact", codes(profile, listing))

    def test_claim_coverage_and_unreferenced_specs(self):
        profile, listing, _ = single_fixture()
        listing["claims"].pop()
        self.assertTrue({"claim_missing", "measurement_unreferenced"} <= codes(profile, listing))

    def test_image_scope_and_main_overlay(self):
        profile, listing, _ = family_fixture()
        profile["images"] = [{"image_id": "black-photo", "source": "user/photo.jpg", "applies_to": ["child-01"]}]
        listing["image_plan"][0]["source_image_ids"] = ["black-photo"]
        listing["image_plan"][0]["overlay_text"] = "Best pen holder"
        self.assertTrue({"plan_image_scope", "main_image_text"} <= codes(profile, listing))
        listing["image_plan"][0]["applies_to"] = ["child-01"]
        self.assertIn("image_set_scope", codes(profile, listing))

    def test_image_dimension_must_match_child_and_corresponding_body(self):
        profile, listing, _ = family_fixture()
        pid = listing["image_sets"]["variants"][1]["secondary"][0]
        image = next(p for p in listing["image_plan"] if p["plan_id"] == pid)
        image["measurement_ids"] = ["height-2"]
        image["overlay_text"] = "Height: 4 in"
        self.assertEqual(codes(profile, listing), set())
        image["overlay_text"] = "Height: 6 in"
        self.assertIn("plan_measurement_text", codes(profile, listing))
        image["applies_to"] = ["child-01"]
        self.assertIn("reference_scope", codes(profile, listing))

    def test_native_aplus_text_specifications_and_forbidden_words(self):
        profile, listing, _ = single_fixture()
        module = listing["a_plus_plan"][0]
        module.update(overlay_text="", native_text="Height: 6 in", measurement_ids=["height"])
        self.assertEqual(codes(profile, listing), set())
        module["native_text"] = "Height: 15.24cm"
        self.assertTrue({"source_unit_leak", "plan_measurement_text"} <= codes(profile, listing))
        module["native_text"] = "Best height: 6 in"
        profile["forbidden_terms"] = ["Best"]
        self.assertIn("forbidden_term", codes(profile, listing))

    def test_unrelated_qa_cannot_be_answered_and_original_questions_preserved(self):
        profile, listing, qa = single_fixture()
        qa["question_reviews"][0]["relevance"] = "irrelevant"
        self.assertIn("qa_unsupported_answer", codes(profile, listing, qa))
        qa["question_reviews"][0]["disposition"] = "excluded"
        self.assertNotIn("qa_unsupported_answer", codes(profile, listing, qa))
        qa["question_reviews"][0]["question"] = "Invented question"
        self.assertTrue({"qa_provenance", "qa_review_coverage"} <= codes(profile, listing, qa))

    def test_unrelated_response_seed_is_preserved_and_quarantined(self):
        profile, listing, qa = single_fixture()
        qa["qa_pairs"][0]["keyword"] = "yoga mat"
        qa["question_reviews"][0].update(keyword="yoga mat", relevance="irrelevant", disposition="excluded", fact_ids=[])
        self.assertEqual(codes(profile, listing, qa), set())
        self.assertTrue(any(i["code"] == "qa_seed_mismatch" and i["severity"] == "warning" for i in quality.check_local(profile, listing, qa)))
        qa["question_reviews"][0].update(relevance="relevant", disposition="answered", fact_ids=["material"])
        self.assertIn("qa_seed_mismatch", codes(profile, listing, qa))

    def test_real_empty_qa_result_allowed_but_requested_keywords_required(self):
        profile, listing, qa = single_fixture()
        qa.update(qa_pairs=[], question_reviews=[])
        self.assertEqual(codes(profile, listing, qa), set())
        qa["requested_keywords"] = []
        self.assertIn("qa_requested_keywords", codes(profile, listing, qa))

    def test_unavailable_qa_is_incomplete_not_product_error(self):
        profile, listing, _ = single_fixture()
        qa = {"site": "US", "status": "unavailable", "reason": "Backend credentials are not configured.",
              "requested_keywords": [], "qa_pairs": [], "question_reviews": []}
        issues = quality.check_local(profile, listing, qa)
        self.assertEqual([(i["code"], i["severity"]) for i in issues], [("qa_unavailable", "incomplete")])
        fingerprints, review, backend = completed_acceptance(profile, listing, qa)
        result = quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["local"]["status"], "incomplete")
        qa["qa_pairs"] = ["fabricated question"]
        self.assertIn("qa_unavailable_shape", codes(profile, listing, qa))

    def test_invalid_root_and_nested_types_fail_without_crashing(self):
        profile, listing, _ = single_fixture()
        self.assertIn("object_required", codes([], listing))
        profile["facts"][0]["value"] = float("nan")
        self.assertIn("malformed_structure", codes(profile, listing))
        profile, listing, _ = family_fixture()
        profile["variants"][0]["variant_id"] = []
        self.assertTrue(codes(profile, listing))

    def test_non_us_qa_skip_is_explicit(self):
        profile, listing, _ = single_fixture()
        profile["site"] = listing["site"] = "UK"
        profile = quality.normalize_profile(profile)
        listing["description"] = "This pen holder is 15.24 cm high."
        qa = {"site": "UK", "status": "skipped", "reason_code": "rufus_us_only", "qa_pairs": []}
        self.assertEqual(codes(profile, listing, qa), set())
        qa["qa_pairs"] = ["US question"]
        self.assertIn("qa_non_us", codes(profile, listing, qa))

    def test_unverified_variation_theme_cannot_pass(self):
        profile, listing, _ = family_fixture()
        profile["variation_theme"]["status"] = "unverified"
        self.assertIn("variation_theme", codes(profile, listing))


class AcceptanceAndBackendTests(unittest.TestCase):
    def test_missing_checks_and_pending_cannot_pass(self):
        profile, listing, qa = single_fixture()
        result = quality.validate_bundle(profile, listing, qa)
        self.assertEqual(result["status"], "incomplete")
        fingerprints, review, backend = completed_acceptance(profile, listing, qa)
        keywords = {"status": "passed", "issues": [], "fingerprints": {"01_product_profile.json": fingerprints["profile_sha256"], "07_listing.json": fingerprints["listing_sha256"], "06_qa.json": fingerprints["qa_sha256"]}}
        review["keyword_fingerprints"] = {name: None for name in ("02_kw_raw.json", "03_keyword_decisions.json", "05_title_keywords.json")}
        complete = quality.validate_bundle(profile, listing, qa, review, backend, fingerprints, keywords=keywords)
        self.assertEqual(complete["status"], "passed")
        self.assertEqual(complete["evidence_fingerprints"], {"review_sha256": quality.canonical_sha256(review), "backend_sha256": quality.canonical_sha256(backend), "keywords_sha256": quality.canonical_sha256(keywords)})
        self.assertEqual(quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)["keywords"]["status"], "incomplete")
        review["records"][0]["status"] = "pending"
        self.assertEqual(quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)["status"], "incomplete")

    def test_semantic_failure_and_not_applicable_need_evidence(self):
        profile, listing, qa = single_fixture()
        fingerprints, review, backend = completed_acceptance(profile, listing, qa)
        review["records"][0]["status"] = "fail"
        self.assertEqual(quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)["status"], "failed")
        review["records"][0].update(status="not_applicable", evidence="")
        self.assertEqual(quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)["status"], "incomplete")

    def test_fingerprints_and_missing_child_backend_result(self):
        profile, listing, qa = family_fixture()
        fingerprints, review, backend = completed_acceptance(profile, listing, qa)
        backend["records"].pop()
        result = quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("backend_coverage", {i["code"] for i in result["issues"]})
        fingerprints["listing_sha256"] = "changed"
        review["fingerprints"] = {"old": "value"}
        backend["records"][0]["payload_sha256"] = "old"
        result = quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)
        self.assertTrue({"review_stale", "backend_stale"} <= {i["code"] for i in result["issues"]})

    def test_all_backend_success_conditions_required(self):
        for change in ({"exit_code": 1}, {"response": {"ok": False, "errors": []}},
                       {"response": {"ok": True, "errors": ["bad field"]}}, {"response": {"ok": True}},
                       {"response": None}, {"exit_code": False}):
            profile, listing, qa = single_fixture()
            fingerprints, review, backend = completed_acceptance(profile, listing, qa)
            backend["records"][0].update(change)
            self.assertEqual(quality.validate_bundle(profile, listing, qa, review, backend, fingerprints)["status"], "failed")

    def test_projection_is_legacy_single_shape_and_every_child_in_order(self):
        profile, listing, _ = family_fixture()
        payloads = quality.build_payloads(profile, listing)
        self.assertEqual([p["target"] for p in payloads], ["child-01", "child-02", "child-03"])
        self.assertEqual(payloads[1]["payload"]["description"], "This pen holder is 4 in high.")
        self.assertEqual(payloads[1]["payload"]["bullets"], listing["shared_content"]["bullets"])
        self.assertFalse({"parent", "variants", "claims", "image_plan"} & set(payloads[0]["payload"]))
        listing["variants"][0]["variant_id"] = "../../bad"
        with self.assertRaises(ValueError):
            quality.build_payloads(profile, listing)

    @patch.object(quality.backend_cli, "load_config", new=lambda path: {"backend_url": "https://offline.example.invalid", "backend_token": "secret-value"})
    @patch.object(quality.backend_cli, "prepare_cli", new=lambda path: None)
    def test_mock_cli_captures_business_errors_and_redacts_secrets(self):
        profile, listing, _ = family_fixture()
        outputs = [subprocess.CompletedProcess([], 0, '{"ok":true,"errors":[]}', "progress"),
                   subprocess.CompletedProcess([], 0, '{"ok":false,"errors":["token secret-value"],"token":"secret-value"}', ""),
                   subprocess.CompletedProcess([], 4, '{"ok":true,"errors":[]}', "")]
        with patch.object(quality.backend_cli.subprocess, "run", side_effect=outputs) as runner, patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": "secret-value"}):
            result = quality.run_backend(profile, listing, "/mock/cli")
            self.assertEqual(runner.call_count, 3)
            self.assertTrue(all(call.args[0][1] == "validate" for call in runner.call_args_list))
            self.assertTrue(all(call.kwargs["env"]["LAOCHEN_BACKEND_TOKEN"] == "secret-value" for call in runner.call_args_list))
        self.assertEqual([r["exit_code"] for r in result["records"]], [0, 0, 4])
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertFalse(result["records"][1]["response"]["ok"])

    @patch.object(quality.backend_cli, "load_config", new=lambda path: {"backend_url": "https://offline.example.invalid", "backend_token": "secret-value"})
    @patch.object(quality.backend_cli, "prepare_cli", new=lambda path: None)
    def test_backend_timeout_invalid_json_and_missing_executable(self):
        profile, listing, _ = single_fixture()
        for fault in (subprocess.TimeoutExpired("cli", 10), OSError("secret value")):
            with patch.object(quality.backend_cli.subprocess, "run", side_effect=fault):
                record = quality.run_backend(profile, listing, "/mock/cli")["records"][0]
                self.assertIsNone(record["exit_code"])
                self.assertIn("failure_reason", record)
        with patch.object(quality.backend_cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "secret raw stderr", "secret")):
            record = quality.run_backend(profile, listing, "/mock/cli")["records"][0]
            self.assertIsNone(record["response"])
            self.assertNotIn("secret raw", json.dumps(record))
        with patch.object(quality.backend_cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"ok":true,"errors":[],"extra":NaN}', "")):
            self.assertIsNone(quality.run_backend(profile, listing, "/mock/cli")["records"][0]["response"])

    def test_byte_fingerprints_and_pending_review_template(self):
        profile, listing, qa = family_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ("profile.json", "listing.json", "qa.json")]
            for path, data in zip(paths, (profile, listing, qa)):
                quality.atomic_write_json(path, data)
            template = quality.make_review_template(*paths)
            self.assertEqual(len(template["records"]), 4 * len(quality.load_json(quality.POLICY_PATH)["semantic_checks"]) + 1)
            self.assertTrue(all(r["status"] == "pending" for r in template["records"]))
            before = template["fingerprints"]
            with open(paths[1], "a", encoding="utf-8") as file:
                file.write("\n")
            after = quality.file_fingerprints(*paths)
            self.assertNotEqual(before["listing_sha256"], after["listing_sha256"])


class MediaDeliveryTests(unittest.TestCase):
    def reused_family(self):
        profile, listing, qa = family_fixture()
        # Two actual size variants of the same appearance, in source order.
        profile["variants"] = profile["variants"][:2]
        listing["variants"] = listing["variants"][:2]
        profile["variation_dimensions"] = ["size"]
        profile["variation_theme"]["name"] = "Size"
        profile["appearance_assessment"] = {"status": "same", "differences_only_size_or_quantity": True,
                                             "source_ref": "fixture input: same appearance, only height differs"}
        listing["title_template"] = "ACME 304 Stainless Steel Pen Holder, {size}"
        for pv, lv in zip(profile["variants"], listing["variants"]):
            pv["attributes"].pop("color")
            lv["attributes"].pop("color")
            lv["title"] = listing["title_template"].format_map(lv["attributes"])
        complete_media(profile, listing, "shared_secondary")
        dimensions = listing["image_plan"][1]
        dimensions["variant_bindings"] = []
        for variant in profile["variants"]:
            measurement = variant["measurements"][0]
            dimensions["variant_bindings"].append({"variant_id": variant["variant_id"],
                "source_image_ids": ["product-photo"], "fact_ids": ["material"],
                "measurement_ids": [measurement["measurement_id"]], "body_refs": ["description"],
                "overlay_text": "Height: " + measurement["display_text"]})
        return profile, listing, qa

    def test_single_and_full_family_counts_and_independence(self):
        for factory, expected_plans in ((single_fixture, 7), (family_fixture, 28)):
            p, l, qa = factory()
            self.assertEqual(len(l["image_plan"]), expected_plans)
            self.assertEqual(len(l["a_plus_plan"]), 5)
            self.assertEqual(quality.check_local(p, l, qa), [])

    def test_missing_slot_duplicate_and_orphan_are_rejected(self):
        for mutate, expected in (
            (lambda l: l["image_sets"]["shared"]["secondary"].pop(), "image_set_count"),
            (lambda l: l["image_sets"]["shared"]["secondary"].__setitem__(1, "secondary-2"), "image_set_duplicate"),
            (lambda l: l["image_plan"].append(plan("extra", "main")), "image_set_orphan"),
            (lambda l: l["image_sets"]["shared"].__setitem__("main", "missing"), "image_set_reference"),
            (lambda l: l["image_plan"].append(copy.deepcopy(l["image_plan"][0])), "plan_id"),
            (lambda l: l["image_plan"][1].__setitem__("image", "图3（尺寸）"), "image_number")):
            with self.subTest(expected=expected):
                p, l, _ = single_fixture()
                mutate(l)
                self.assertIn(expected, codes(p, l))

    def test_text_faq_does_not_count_but_sixth_image_is_allowed(self):
        p, l, _ = single_fixture()
        l["a_plus_plan"][0]["asset_type"] = "text"
        self.assertIn("aplus_image_count", codes(p, l))
        extra = plan("aplus-6", "aplus")
        extra["module"] = "模块6：更多使用说明"
        l["a_plus_plan"].append(extra)
        l["image_sets"]["shared"]["a_plus"].append("aplus-6")
        self.assertEqual(codes(p, l), set())

    def test_child_sets_have_no_aplus_and_cannot_borrow_other_children(self):
        p, l, _ = family_fixture()
        l["image_sets"]["variants"][0]["a_plus"] = ["aplus"]
        self.assertIn("image_set_shape", codes(p, l))
        l["image_sets"]["variants"][0].pop("a_plus")
        l["image_sets"]["variants"][0]["secondary"] = l["image_sets"]["variants"][1]["secondary"]
        self.assertIn("image_set_scope", codes(p, l))
        l["image_sets"]["variants"].reverse()
        self.assertIn("image_sets_variants", codes(p, l))

    def test_same_appearance_reuses_secondary_and_has_per_child_main(self):
        p, l, qa = self.reused_family()
        self.assertEqual(quality.check_local(p, l, qa), [])
        self.assertEqual(len(l["image_plan"]), 9)
        self.assertEqual([b["overlay_text"] for b in l["image_plan"][1]["variant_bindings"]], ["Height: 6 in", "Height: 4 in"])
        self.assertEqual(l["image_sets"]["variants"][0]["secondary"], l["image_sets"]["shared"]["secondary"])
        self.assertNotEqual(l["image_sets"]["variants"][0]["main"], l["image_sets"]["variants"][1]["main"])

    def test_reuse_requires_evidence_and_exact_shared_references(self):
        p, l, _ = self.reused_family()
        p["appearance_assessment"]["source_ref"] = ""
        self.assertIn("media_reuse_evidence", codes(p, l))
        p["appearance_assessment"]["source_ref"] = "user"
        p["appearance_assessment"]["status"] = "different"
        self.assertIn("media_reuse_evidence", codes(p, l))
        l["image_sets"]["variants"][0]["secondary"].reverse()
        self.assertIn("image_reuse_mismatch", codes(p, l))

    def test_binding_dimensions_cannot_leak_from_first_child(self):
        for key, value, expected in (("overlay_text", "Height: 6 in", "measurement_wrong_variant"),
                                      ("measurement_ids", ["height-1"], "reference_scope"),
                                      ("overlay_text", "Height: 10.16 cm", "source_unit_leak"),
                                      ("measurement_ids", [], "measurement_unreferenced")):
            with self.subTest(key=key, value=value):
                p, l, _ = self.reused_family()
                l["image_plan"][1]["variant_bindings"][1][key] = value
                self.assertIn(expected, codes(p, l))
        p, l, _ = self.reused_family()
        l["variants"][1]["content_overrides"]["description"] = "This pen holder keeps writing tools together."
        self.assertIn("plan_body_measurement", codes(p, l))

    def test_missing_duplicate_unknown_and_reordered_bindings_fail(self):
        for mutate in (lambda b: b.pop(), lambda b: b.append(copy.deepcopy(b[0])), lambda b: b.reverse(),
                       lambda b: b[0].__setitem__("variant_id", "unknown")):
            p, l, _ = self.reused_family()
            mutate(l["image_plan"][1]["variant_bindings"])
            self.assertIn("media_binding_coverage", codes(p, l))
        p, l, _ = self.reused_family()
        l["image_plan"][1]["variant_bindings"][0]["role"] = "main"
        self.assertIn("media_binding", codes(p, l))

    def test_binding_source_and_main_image_text_are_checked(self):
        p, l, _ = self.reused_family()
        p["images"].append({"image_id": "first-child", "source": "fixture:first", "applies_to": ["child-01"]})
        l["image_plan"][1]["variant_bindings"][1]["source_image_ids"] = ["first-child"]
        self.assertIn("plan_image_scope", codes(p, l))
        p, l, _ = self.reused_family()
        l["image_plan"][0]["variant_bindings"] = copy.deepcopy(l["image_plan"][1]["variant_bindings"])
        self.assertIn("main_image_text", codes(p, l))

    def test_binding_aplus_parameters_are_checked(self):
        p, l, qa = self.reused_family()
        l["a_plus_plan"][0]["variant_bindings"] = l["image_plan"][1].pop("variant_bindings")
        self.assertEqual(quality.check_local(p, l, qa), [])
        l["a_plus_plan"][0]["variant_bindings"][1]["overlay_text"] = "Height: 6 in"
        self.assertIn("measurement_wrong_variant", codes(p, l))

    def test_missing_material_and_pending_creative_cannot_complete(self):
        p, l, qa = single_fixture()
        for update, expected in (({"source_image_ids": []}, "plan_material_pending"), ({"status": "pending"}, "plan_pending")):
            with self.subTest(expected=expected):
                candidate = copy.deepcopy(l)
                candidate["image_plan"][0].update(update)
                fingerprints, review, backend = completed_acceptance(p, candidate, qa)
                result = quality.validate_bundle(p, candidate, qa, review, backend, fingerprints)
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["local"]["status"], "incomplete")
                self.assertIn(expected, {i["code"] for i in result["issues"]})

    def test_legacy_aplus_alias_and_conflict(self):
        p, l, qa = single_fixture()
        l["aplus_plan"] = l.pop("a_plus_plan")
        self.assertEqual(quality.check_local(p, l, qa), [])
        l["a_plus_plan"] = copy.deepcopy(l["aplus_plan"])
        self.assertEqual(quality.check_local(p, l, qa), [])
        l["a_plus_plan"][0]["direction"] = "Conflicting direction"
        self.assertIn("aplus_alias_conflict", codes(p, l))

    def test_old_schema_cannot_reuse_old_acceptance(self):
        p, l, qa = single_fixture()
        p["schema_version"] = l["schema_version"] = "2.0"
        fingerprints, review, backend = completed_acceptance(p, l, qa)
        self.assertEqual(quality.validate_bundle(p, l, qa, review, backend, fingerprints)["status"], "incomplete")

    def test_bullet_label_format_and_uncased_language(self):
        p, l, _ = single_fixture()
        l["bullets"][0] = "【Material】Body"
        self.assertIn("bullet_format", codes(p, l))
        l["bullets"][0] = "【材質】本体"
        self.assertNotIn("bullet_format", codes(p, l))
        l["bullets"][0] = "【MATERIAL】"
        self.assertIn("bullet_format", codes(p, l))

    def test_quantity_bindings_match_fact_and_body_for_each_child(self):
        p, l, qa = self.reused_family()
        image = l["image_plan"][1]
        for number, (pv, lv, binding) in enumerate(zip(p["variants"], l["variants"], image["variant_bindings"]), 2):
            fid = "quantity-%d" % number
            pv["facts"].append({"fact_id": fid, "field": "package_quantity", "value": number, "status": "confirmed", "source_ref": "fixture quantity"})
            lv["content_overrides"]["description"] += " Quantity: %d." % number
            lv["claims"][-1]["fact_ids"].append(fid)
            binding["fact_ids"].append(fid)
            binding["overlay_text"] += " | %d-Pack" % number
        self.assertEqual(quality.check_local(p, l, qa), [])
        image["variant_bindings"][1]["overlay_text"] = "Height: 4 in | 2-Pack"
        self.assertIn("quantity_wrong_variant", codes(p, l))
        image["variant_bindings"][1]["overlay_text"] = "Height: 4 in | 3-Pack"
        l["variants"][1]["content_overrides"]["description"] = "This pen holder is 4 in high."
        self.assertIn("plan_body_quantity", codes(p, l))

    def test_quantity_requires_a_fact_even_if_no_quantity_was_supplied(self):
        p, l, _ = single_fixture()
        l["image_plan"][1]["overlay_text"] = "2-Pack"
        self.assertIn("quantity_unregistered", codes(p, l))
        l["description"] += " Comes in a 2-Pack."
        issues = quality.check_local(p, l)
        self.assertTrue(any(i["code"] == "quantity_unregistered" and i["path"] == "listing.single.description" for i in issues))

    def test_shared_quantity_cannot_hide_behind_child_overrides(self):
        p, l, _ = self.reused_family()
        for number, variant in enumerate(p["variants"], 2):
            variant["facts"].append({"fact_id": "count-%d" % number, "field": "package_quantity", "value": number,
                                     "status": "confirmed", "source_ref": "fixture quantity"})
        l["shared_content"]["description"] = "This pen holder comes in a 2-Pack."
        issues = quality.check_local(p, l)
        self.assertTrue(any(i["code"] == "quantity_wrong_variant" and i["path"] == "listing.shared_content.description" for i in issues))

    def test_each_quantity_expression_requires_its_own_fact(self):
        p, l, _ = single_fixture()
        for field, count in (("pack_count", 2), ("number_of_items", 4)):
            p["facts"].append({"fact_id": field, "field": field, "value": count, "status": "confirmed", "source_ref": "fixture counts"})
        l["description"] += " Includes 2 packs containing 4 pieces in total."
        l["claims"][-1]["fact_ids"].append("pack_count")
        image = l["image_plan"][1]
        image.update(overlay_text="2 packs / 4 pieces in total", fact_ids=["pack_count"])
        issues = quality.check_local(p, l)
        self.assertTrue(any(i["code"] == "quantity_unreferenced" and i["path"] == "listing.single.description" for i in issues))
        self.assertTrue(any(i["code"] == "quantity_unreferenced" and i["path"] == "listing.image_plan[1].overlay_text" for i in issues))
        l["claims"][-1]["fact_ids"].append("number_of_items")
        image["fact_ids"].append("number_of_items")
        self.assertEqual(codes(p, l), set())

    def test_aplus_module_order_and_question_status(self):
        p, l, _ = single_fixture()
        l["a_plus_plan"][4]["module"] = "模块1：错误编号"
        self.assertIn("aplus_number", codes(p, l))
        l["buyer_question_coverage"] = [{"question": "Material?", "status": "invented", "location": "Bullet 1"}]
        self.assertIn("buyer_question_coverage", codes(p, l))


class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.profile, self.listing, self.qa = family_fixture()
        for name, data in (("profile", self.profile), ("listing", self.listing), ("qa", self.qa)):
            quality.atomic_write_json(self.root / (name + ".json"), data)

    def run_cli(self, command, *extra):
        args = [sys.executable, str(SCRIPT), command, "--profile", str(self.root / "profile.json")]
        if command != "normalize":
            args += ["--listing", str(self.root / "listing.json")]
        return subprocess.run(args + list(extra), capture_output=True, text=True, check=False)

    def test_cli_normalize_in_place_prepare_and_incomplete_check(self):
        result = self.run_cli("normalize", "--output", str(self.root / "profile.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("prepare", "--output-dir", str(self.root / "payloads"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = quality.load_json(self.root / "payloads" / "manifest.json")
        self.assertEqual(len(manifest["records"]), 3)
        self.assertFalse((self.root / "payloads" / "parent.json").exists())
        result = self.run_cli("check", "--qa", str(self.root / "qa.json"), "--output", str(self.root / "validation.json"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(quality.load_json(self.root / "validation.json")["status"], "incomplete")

    def test_backend_never_runs_for_local_errors(self):
        self.listing["variants"][0]["title"] = "Wrong identity"
        quality.atomic_write_json(self.root / "listing.json", self.listing)
        result = self.run_cli("backend", "--cli", "/must-not-run/cli", "--output", str(self.root / "backend.json"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(quality.load_json(self.root / "backend.json")["records"], [])

    def test_cli_legacy_readable_but_not_automatically_accepted(self):
        profile, listing, qa = single_fixture()
        for data in (profile, listing):
            data.pop("schema_version")
            data.pop("listing_mode")
        quality.atomic_write_json(self.root / "profile.json", profile)
        quality.atomic_write_json(self.root / "listing.json", listing)
        result = self.run_cli("check", "--output", str(self.root / "validation.json"))
        self.assertEqual(result.returncode, 1)
        validation = quality.load_json(self.root / "validation.json")
        self.assertEqual(validation["status"], "incomplete")
        self.assertIn("legacy_schema", {i["code"] for i in validation["issues"]})

    def test_cli_rejects_nonfinite_json_without_traceback(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            (self.root / "profile.json").write_text('{"bad":' + constant + '}', encoding="utf-8")
            result = self.run_cli("check", "--output", str(self.root / "validation.json"))
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture; portable subprocess behavior is also mocked above")
    def test_backend_cli_with_local_fake_executable(self):
        config = self.root / "config.json"
        quality.atomic_write_json(config, {"backend_url": "https://offline.example.invalid", "backend_token": "offline-test-token"})
        executable = self.root / "fake-cli"
        executable.write_text("#!" + sys.executable + "\n" +
            "import json, os, sys\n" +
            "assert os.environ['LAOCHEN_BACKEND_TOKEN'] == 'offline-test-token'\n" +
            "assert sys.argv[1] == 'validate'\n" +
            "p=json.load(open(sys.argv[sys.argv.index('--listing-file')+1]))\n" +
            "assert 'parent' not in p and 'variants' not in p\n" +
            "bad='4 in' in p['description']\n" +
            "print(json.dumps({'ok': not bad, 'errors': ['fixture error'] if bad else [], 'echo': os.environ['LAOCHEN_BACKEND_TOKEN']}))\n", encoding="utf-8")
        executable.chmod(0o700)
        result = self.run_cli("backend", "--cli", str(executable), "--config", str(config), "--output", str(self.root / "backend.json"))
        self.assertEqual(result.returncode, 1)
        records = quality.load_json(self.root / "backend.json")["records"]
        self.assertEqual([r["target"] for r in records], ["child-01", "child-02", "child-03"])
        self.assertEqual([r["response"]["ok"] for r in records], [True, False, True])
        self.assertNotIn("offline-test-token", json.dumps(records) + result.stdout + result.stderr)

    def test_backend_config_missing_is_recorded_for_every_child(self):
        config = self.root / "config.json"
        quality.atomic_write_json(config, {"backend_url": "https://offline.example.invalid", "backend_token": ""})
        result = self.run_cli("backend", "--cli", "/must-not-run/cli", "--config", str(config), "--output", str(self.root / "backend.json"))
        self.assertEqual(result.returncode, 1)
        records = quality.load_json(self.root / "backend.json")["records"]
        self.assertEqual([r["target"] for r in records], ["child-01", "child-02", "child-03"])
        self.assertTrue(all(r["exit_code"] is None and r["error_code"] == "config_missing" for r in records))


if __name__ == "__main__":
    unittest.main()
