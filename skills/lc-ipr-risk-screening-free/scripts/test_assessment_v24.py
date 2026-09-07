"""Offline behavior regressions for scoped publication and evidence sufficiency."""
from copy import deepcopy
import base64
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from common import (active_free_policy, now_iso, sha256_file, sha256_json, atomic_write_json,
                    serper_free_enhancement, serpapi_free_enhancement, signa_free_enhancement)
from annotate_materiality import (empty_materiality_ledger, apply_materiality_annotations,
                                 candidate_identity_fingerprint)
from assessment_v24 import (CRITERIA, CONFIDENCE_FACTS, bound_runs, compute_assessment,
                            coverage_by_scope, evaluate_row, query_coverage, review_digest, _conflicts,
                            _claim_documents, candidate_applies, _typed_comparison_gaps, _product_evidence)
from workflow_v24 import build_coverage_requirements_v24
from report_v24 import build_v24_bundle, validate_run
from record_asset_provenance import validate_payload


def setup_scope(directory: Path):
    task = {"schema_version": "2.4-free", "task_id": "T-SCOPED", "free_policy": active_free_policy(),
            "free_policy_revision": "automation-first-v1", "state": "incomplete", "target_jurisdictions": ["US", "GB"],
            "coverage_requirements": build_coverage_requirements_v24(["US", "GB"]),
            "product": {"title": "Test product", "input_role": "actual_product", "actual_asin": "B000000001", "assets": [{"asset_id": "front-art"}]}, "outputs": {}}
    task.update(serper_free_enhancement=serper_free_enhancement(), serpapi_free_enhancement=serpapi_free_enhancement(), signa_free_enhancement=signa_free_enhancement())
    plan = {key: deepcopy(task[key]) for key in ("schema_version", "task_id", "free_policy", "free_policy_revision")}
    for key in ("serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement"):
        plan[key] = deepcopy(task[key])
    plan["execution_policy"] = {"commercial_freemium_allowlist": [], "commercial_providers_enabled": False, "paid_execution_enabled": False}
    query = {"query_id": "Q-PROVENANCE", "operation": "provenance_review", "q": "C-ART",
             "candidate_id": "C-ART", "jurisdiction": "US", "right_type": "copyright",
             "requirement_ids": ["COV-US-COPYRIGHT-PROVENANCE"], "required": False,
             "search_dimension": "provenance", "search_language": "", "execution_phase": "initial"}
    plan["queries"] = {"asset_provenance": [query]}
    path = directory / "source.txt"
    path.write_text("Author's documented original and licence evidence")
    artifact = {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size, "role": "source_document"}
    payload = {"candidate_id": "C-ART", "jurisdiction": "US", "right_type": "copyright", "reviewer": "source-agent",
               "source_document": "Source document retained", "ownership_or_source_reasoning": "Authorship traced to original source and dated copy",
               "artifacts": [artifact], "unresolved": [], "checked_at": now_iso()}
    run = {"run_id": "RUN-PROV", "provider": "asset_provenance", "status": "success", "query": "C-ART", "request_params": query,
           **{key: query[key] for key in ("query_id", "operation", "jurisdiction", "right_type", "requirement_ids")},
           "plan_entry_sha256": sha256_json(query)}
    entry = {"evidence_id": "EV-PROV", "source_run_id": run["run_id"], "payload": payload,
             **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
    product_image = directory / "product.png"
    product_image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII="))
    task["images"] = [{"path": str(product_image), "sha256": sha256_file(product_image), "bytes": product_image.stat().st_size, "role": "main", "mime_type": "image/png"}]
    product = {"evidence_id": "EV-PRODUCT", "provider": "amazon_browser", "payload": {"asin": "B000000001", "images": deepcopy(task["images"])}}
    evidence = {"schema_version": "2.4-free", "task_id": task["task_id"], "source_runs": [run],
                "collections": {"asset_provenance": [entry], "browser": [product], "product": [deepcopy(product)]}}
    candidate = {"candidate_id": "C-ART", "right_type": "copyright", "jurisdiction": "US", "title": "Similar original artwork",
                 "evidence_refs": ["EV-PROV"], "sources": [{"query_id": query["query_id"]}], "material": True}
    candidates = {"schema_version": "2.4-free", "task_id": task["task_id"], "copyright_assets": [candidate], "patents": [], "trademarks": [], "enforcement": []}
    ledger = empty_materiality_ledger(task["task_id"])
    ledger["annotations"] = [{"annotation_id": "MAT-1", "candidate_id": "C-ART", "candidate_identity_fingerprint": candidate_identity_fingerprint("copyright_assets", candidate),
        "material": True, "decision": "material", "material_reason": "Relevant artwork", "reviewer": "material-agent", "annotated_at": now_iso()}]
    apply_materiality_annotations(ledger, task["task_id"], candidates)
    row = {"jurisdiction": "US", "right_type": "copyright", "candidate_id": "C-ART", "risk": "高", "evidence_confidence": "高",
           "reasoning": "Substantial protected expression is reproduced without a documented licence", "evidence_refs": ["EV-PROV", "EV-PRODUCT"],
           "confidence_basis": {key: {"satisfied": True, "reasoning": "Bound evidence supports this prerequisite", "evidence_refs": ["EV-PROV", "EV-PRODUCT"] if key == "comparison" else ["EV-PRODUCT" if key == "product" else "EV-PROV"]} for key in CONFIDENCE_FACTS},
           "comparison": {"criteria": [{"criterion": key, "result": "supports_risk", "reasoning": "Criterion supported by retained evidence", "evidence_refs": ["EV-PROV", "EV-PRODUCT"]} for key in CRITERIA["copyright"]], "unresolved": []},
           "findings": [{"finding_id": "F-COPY", "title": "Protected expression overlap", "recommended_action": "Replace or obtain the documented licence", "evidence_refs": ["EV-PROV", "EV-PRODUCT"]}]}
    digest = review_digest(evidence, candidates, ledger, plan, task)
    first = {"reviewer": "agent-1", "review_context": {"session_id": "independent-1", "evidence_digest": digest, "first_review_visible": False}, "assessments": [row]}
    second = deepcopy(first)
    second.update(reviewer="agent-2", review_context={"session_id": "independent-2", "evidence_digest": digest, "first_review_visible": False})
    return task, evidence, candidates, plan, ledger, first, second


def refresh_reviews(evidence, candidates, ledger, plan, first, second, task):
    for review in (first, second):
        review["review_context"]["evidence_digest"] = review_digest(evidence, candidates, ledger, plan, task)


class ScopedAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.values = setup_scope(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def calculate(self):
        return compute_assessment(*self.values)

    def test_copyright_without_registration_can_publish_scoped_high(self):
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["publication"], "confirmed_scoped")
        self.assertEqual(result["assessments"][0]["evidence_confidence"], "高")
        self.assertEqual(result["overall"]["known_scoped_risk"], "高")
        self.assertEqual(result["overall"]["risk"], "")
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["review"]["human_review_required"])

    def test_reference_product_cannot_publish_actual_product_conclusion(self):
        self.values[0]["product"]["input_role"] = "reference_product"
        task, evidence, candidates, plan, ledger, first, second = self.values
        refresh_reviews(evidence, candidates, ledger, plan, first, second, task)
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["publication"], "discovery_only")
        self.assertIn("ACTUAL_PRODUCT_IDENTITY_NOT_ESTABLISHED", result["assessments"][0]["publication_gaps"])

    def test_same_risk_different_claim_state_or_exclusion_is_disputed(self):
        left = deepcopy(self.values[-2]["assessments"][0])
        right = deepcopy(left)
        left["right_state"] = "active"
        right["right_state"] = "pending"
        self.assertIn("right_state", _conflicts(left, right))
        right["right_state"] = "active"
        right["exclusion_basis"] = "Claim element absent"
        self.assertIn("exclusion_basis", _conflicts(left, right))
        left["comparison"]["claims"] = [{"claim_id": "1", "elements": [{"claim_element": "hinge", "result": "supports_risk"}]}]
        right["comparison"]["claims"] = [{"claim_id": "1", "elements": [{"claim_element": "hinge", "result": "excludes_risk"}]}]
        self.assertIn("claim_elements", _conflicts(left, right))

    def test_unverified_suspicious_candidate_remains_a_discovery_signal(self):
        task, evidence, candidates, plan, ledger, first, second = self.values
        evidence["collections"]["asset_provenance"][0]["provider"] = "third_party"
        refresh_reviews(evidence, candidates, ledger, plan, first, second, task)
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "高")
        self.assertEqual(result["assessments"][0]["publication"], "discovery_only")
        self.assertEqual(result["overall"]["discovery_signal"], "高")

    def test_optional_failed_source_does_not_cap_verified_confidence(self):
        task, evidence, candidates, plan, ledger, first, second = self.values
        evidence["source_runs"].append({"run_id": "FAIL", "provider": "serper_images", "query_id": "Q-OPTIONAL", "status": "access_limited", "authoritative_for_final_rating": False})
        refresh_reviews(evidence, candidates, ledger, plan, first, second, task)
        self.assertEqual(self.calculate()["assessments"][0]["evidence_confidence"], "高")

    def test_scoped_disagreement_is_unresolved_without_human_work(self):
        self.values[-1]["assessments"][0]["risk"] = "低"
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "无法判断")
        self.assertFalse(result["review"]["human_review_required"])
        self.assertIn("INDEPENDENT_REVIEW_CONFLICT:risk", result["assessments"][0]["publication_gaps"])

    def test_unknown_claim_reference_is_rejected(self):
        self.values[-2]["assessments"][0]["comparison"]["claims"] = [{"claim_id": "1", "claim_evidence_refs": ["NONEXISTENT"], "elements": []}]
        with self.assertRaisesRegex(ValueError, "claim text"):
            self.calculate()

    def test_ledger_digest_change_invalidates_reviews(self):
        self.values[3]["generated_at"] = "changed"
        with self.assertRaisesRegex(ValueError, "REVIEW_CONTEXT"):
            self.calculate()

    def test_product_identity_change_invalidates_reviews(self):
        self.values[0]["product"]["input_role"] = "reference_product"
        with self.assertRaisesRegex(ValueError, "REVIEW_CONTEXT"):
            self.calculate()

    def test_registration_record_does_not_replace_visual_comparison(self):
        row = deepcopy(self.values[-2]["assessments"][0])
        row["right_type"] = "design"
        row["comparison"]["criteria"] = [{"criterion": key, "result": "supports_risk", "reasoning": "Reviewed", "evidence_refs": ["EV-PROV"]} for key in CRITERIA["design"]]
        result = evaluate_row(row, deepcopy(row), *self.values[:4], {"status": "满足已定义要求"})
        self.assertIn("REQUIRED_VISUAL_VIEWS_INCOMPLETE", result["publication_gaps"])
        self.assertNotEqual(result["evidence_confidence"], "高")

    def test_active_patent_uses_claims_and_local_state_not_A_kind(self):
        task, evidence, candidates, plan, ledger, first, second = self.values
        candidate = candidates["copyright_assets"].pop()
        candidate.update(right_type="patent", publication_number="US1234567A1", kind_code="A1", verification_refs=["EV-OFFICIAL"])
        candidates["patents"] = [candidate]
        annotation = ledger["annotations"][0]
        annotation["candidate_identity_fingerprint"] = candidate_identity_fingerprint("patents", candidate)
        apply_materiality_annotations(ledger, task["task_id"], candidates)
        query = {"query_id": "Q-VERIFY", "q": "US1234567A1", "candidate_id": "C-ART", "operation": "candidate_verification", "jurisdiction": "US",
                 "right_type": "patent", "requirement_ids": ["COV-US-PATENT-VERIFY"], "required": True,
                 "search_dimension": "identity", "execution_phase": "expansion"}
        plan["queries"]["uspto_patent_browser"] = [query]
        official = {"status": "verified", "identity_match": True, "authority": "USPTO", "method": "cdp_agent", "checked_at": now_iso(),
                    "owner": "Example owner", "legal_status": "active granted right confirmed", "url": "https://ppubs.uspto.gov/pubwebapp/"}
        run = {"run_id": "R-VERIFY", "provider": "uspto_patent_browser", "status": "success", "query": query["q"], "request_params": {"candidate_id": "C-ART"},
               **{key: query[key] for key in ("query_id", "operation", "jurisdiction", "right_type", "requirement_ids")}, "plan_entry_sha256": sha256_json(query)}
        entry = {"evidence_id": "EV-OFFICIAL", "source_run_id": run["run_id"], "payload": {"candidate_id": "C-ART", "right_type": "patent", "official_verification": official},
                 **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
        # Contract fixture: an adapter must retain typed original claims in its
        # raw capture as well as the normalized record. Current USPTO recorder
        # does not yet produce this contract; its status-only output is below
        # tested as a gap. This is not evidence of an accepted online route.
        source_document = {"publication_number": "US1234567A1", "claims": [{"number": "1", "language": "en", "text": "A device comprising a hinged housing."}]}
        raw_document = self.directory / "official-claims.json"
        atomic_write_json(raw_document, source_document)
        run.update(raw_paths=[str(raw_document)], payload_digest=sha256_file(raw_document))
        entry["payload"].update(source_document)
        evidence["source_runs"].append(run)
        evidence["collections"]["official_verifications"] = [entry]
        candidate["official_verification"] = official
        row = first["assessments"][0]
        row.update(right_type="patent", right_state="active", right_state_evidence_refs=["EV-OFFICIAL"], evidence_refs=["EV-OFFICIAL", "EV-PRODUCT"])
        for key, basis in row["confidence_basis"].items():
            basis["evidence_refs"] = ["EV-OFFICIAL", "EV-PRODUCT"] if key == "comparison" else ["EV-PRODUCT" if key == "product" else "EV-OFFICIAL"]
        row["comparison"] = {"criteria": [{"criterion": key, "result": "supports_risk", "reasoning": "Current claim and product correspondence reviewed", "evidence_refs": ["EV-OFFICIAL", "EV-PRODUCT"]} for key in CRITERIA["patent"]], "unresolved": [],
             "claims": [{"claim_id": "1", "claim_evidence_refs": ["EV-OFFICIAL"], "elements": [{"claim_element": "hinged housing", "claim_quote": "A device comprising a hinged housing.", "product_feature": "hinged housing visible in product", "result": "supports_risk", "evidence_refs": ["EV-OFFICIAL"], "product_evidence_refs": ["EV-PRODUCT"]}]}]}
        second["assessments"] = deepcopy(first["assessments"])
        refresh_reviews(evidence, candidates, ledger, plan, first, second, task)
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["publication"], "confirmed_scoped")
        self.assertEqual(result["overall"]["known_scoped_risk"], "高")
        # The same US verification cannot establish effect in Great Britain.
        row_gb = deepcopy(row)
        row_gb["jurisdiction"] = "GB"
        gb = evaluate_row(row_gb, deepcopy(row_gb), task, evidence, candidates, plan, {"status": "受阻"})
        self.assertEqual(gb["publication"], "discovery_only")
        self.assertIn("OFFICIAL_VERIFICATION_REQUIRED", gb["publication_gaps"])
        for review in (first, second):
            review["assessments"][0]["right_state"] = "pending"
        pending = self.calculate()
        self.assertEqual(pending["assessments"][0]["risk"], "无法判断")
        self.assertTrue(pending["future_applications"])

    def test_status_or_product_evidence_cannot_replace_original_claims(self):
        self.test_active_patent_uses_claims_and_local_state_not_A_kind()
        task, evidence, candidates, plan, ledger, first, second = self.values
        for review in (first, second):
            row = review["assessments"][0]
            row["right_state"] = "active"
            row["comparison"]["claims"][0]["claim_evidence_refs"] = ["EV-PRODUCT"]
            row["comparison"]["claims"][0]["elements"][0]["evidence_refs"] = ["EV-PRODUCT"]
            for criterion in row["comparison"]["criteria"]:
                if criterion["criterion"] in {"current_claims", "element_mapping"}:
                    criterion["evidence_refs"] = ["EV-PRODUCT"]
        result = self.calculate()["assessments"][0]
        self.assertEqual(result["publication"], "discovery_only")
        self.assertNotEqual(result["evidence_confidence"], "高")
        self.assertIn("CLAIM_ORIGINAL_EVIDENCE_REQUIRED:current_claims", result["publication_gaps"])
        # Restoring references cannot make the actual status-only recorder output
        # contain the missing original claim text.
        for review in (first, second):
            row = review["assessments"][0]
            row["comparison"]["claims"][0]["claim_evidence_refs"] = ["EV-OFFICIAL"]
        del evidence["collections"]["official_verifications"][0]["payload"]["claims"]
        refresh_reviews(evidence, candidates, ledger, plan, first, second, task)
        self.assertEqual(self.calculate()["assessments"][0]["publication"], "discovery_only")

    def test_claim_quote_product_side_and_second_review_are_bound(self):
        self.test_active_patent_uses_claims_and_local_state_not_A_kind()
        for review in self.values[-2:]:
            review["assessments"][0]["right_state"] = "active"
        second = self.values[-1]["assessments"][0]
        second["comparison"]["claims"][0]["elements"][0]["product_evidence_refs"] = ["EV-OFFICIAL"]
        result = self.calculate()["assessments"][0]
        self.assertEqual(result["publication"], "discovery_only")
        self.assertIn("CLAIM_ELEMENT_PRODUCT_EVIDENCE_REQUIRED:1", result["publication_gaps"])
        for review in self.values[-2:]:
            element = review["assessments"][0]["comparison"]["claims"][0]["elements"][0]
            element.update(product_evidence_refs=["EV-PRODUCT"], claim_quote="invented telescoping spring")
        self.assertIn("CLAIM_ELEMENT_ORIGINAL_QUOTE_REQUIRED:1", self.calculate()["assessments"][0]["publication_gaps"])

    def test_one_mapped_feature_cannot_omit_remaining_claim_text(self):
        self.test_active_patent_uses_claims_and_local_state_not_A_kind()
        task, evidence, candidates, plan, ledger, first, second = self.values
        entry = evidence["collections"]["official_verifications"][0]
        entry["payload"]["claims"][0]["text"] = "A device comprising a hinged housing and a telescoping spring."
        raw = self.directory / "official-claims.json"
        atomic_write_json(raw, {"publication_number": "US1234567A1", "claims": entry["payload"]["claims"]})
        next(run for run in evidence["source_runs"] if run["run_id"] == "R-VERIFY")["payload_digest"] = sha256_file(raw)
        for review in (first, second):
            row = review["assessments"][0]
            row["right_state"] = "active"
            row["comparison"]["claims"][0]["elements"][0]["claim_quote"] = "A device comprising a hinged housing"
        refresh_reviews(evidence, candidates, ledger, plan, first, second, task)
        result = self.calculate()["assessments"][0]
        self.assertEqual(result["publication"], "discovery_only")
        self.assertIn("CLAIM_FULL_TEXT_MAPPING_INCOMPLETE", result["publication_gaps"])

    def test_unregistered_source_country_does_not_exclude_other_scopes(self):
        candidate = self.values[2]["copyright_assets"][0]
        self.assertTrue(candidate_applies(candidate, "JP", "copyright"))
        self.assertTrue(any("CANDIDATE_ASSESSMENT_MISSING:C-ART" in row["gaps"] for row in self.calculate()["coverage"]["scopes"] if row["jurisdiction"] == "GB" and row["right_type"] == "copyright"))

    def test_eps_native_claims_require_same_document_and_retained_xml(self):
        from eps_client import normalize_document
        task, evidence, candidates, plan, *_ = self.values
        candidate = {"candidate_id": "C-EP", "publication_number": "EP1004359B1", "right_type": "patent", "jurisdiction": "EP"}
        query = {"query_id": "Q-EPS", "operation": "document_retrieval", "candidate_id": "C-EP", "q": "EP1004359B1", "jurisdiction": "GB", "right_type": "patent", "requirement_ids": []}
        plan["queries"]["epo_publication_server"] = [query]
        raw = self.directory / "document.xml"
        raw.write_text('<ep-patent-document country="EP" doc-number="1004359" kind="B1" lang="en"><claims lang="en"><claim num="0001"><claim-text>A device comprising a hinged housing.</claim-text></claim></claims></ep-patent-document>')
        run = {"run_id": "R-EPS", "provider": "epo_publication_server", "status": "success", "source_environment": "production", "authoritative_for_final_rating": False, "raw_paths": [str(raw)], "payload_digest": sha256_file(raw), "plan_entry_sha256": sha256_json(query), **{key: query[key] for key in ("query_id", "operation", "jurisdiction", "right_type", "requirement_ids")}}
        entry = {"evidence_id": "EV-EPS", "source_run_id": "R-EPS", "payload": normalize_document("EP1004359B1", raw.read_bytes(), "C-EP"), **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
        evidence["source_runs"].append(run)
        evidence["collections"]["patents"] = [entry]
        self.assertEqual(_claim_documents(evidence, plan, candidate, set())["EV-EPS"]["1"], "A device comprising a hinged housing.")
        # Foreign family documents cannot silently serve as this member's claims.
        self.assertEqual(_claim_documents(evidence, plan, {**candidate, "publication_number": "US1234567A1"}, set()), {})
        run["source_environment"] = "test_fixture"
        self.assertEqual(_claim_documents(evidence, plan, candidate, set()), {})
        run["source_environment"] = "production"
        raw.write_text("tampered")
        self.assertEqual(_claim_documents(evidence, plan, candidate, set()), {})

    def test_visual_views_must_bind_real_media_on_the_correct_side(self):
        task, evidence, candidates, plan, _, first, _ = self.values
        row = deepcopy(first["assessments"][0])
        row["right_type"] = "unregistered_design"
        row["comparison"]["criteria"] = [{"criterion": key, "result": "supports_risk", "reasoning": "Compared both sides", "evidence_refs": ["EV-PROV", "EV-PRODUCT"]} for key in CRITERIA["unregistered_design"]]
        artifact = {**task["images"][0], "role": "original_work"}
        evidence["collections"]["asset_provenance"][0]["payload"]["artifacts"].append(artifact)
        row["comparison"]["visual_coverage"] = {"required_views": ["front"], "product_views": [{"view": "front", "artifact_sha256": artifact["sha256"], "evidence_refs": ["EV-PRODUCT"]}], "right_views": [{"view": "front", "artifact_sha256": artifact["sha256"], "evidence_refs": ["EV-PROV"]}]}
        args = (task, evidence, plan, candidates["copyright_assets"][0], {"EV-PROV"}, _product_evidence(task, evidence))
        self.assertEqual(_typed_comparison_gaps(row, *args), [])
        row["comparison"]["visual_coverage"]["right_views"][0]["evidence_refs"] = ["EV-PRODUCT"]
        self.assertIn("VISUAL_ARTIFACT_BINDING_INVALID:right_views:front", _typed_comparison_gaps(row, *args))
        row["comparison"]["visual_coverage"]["product_views"][0]["artifact_sha256"] = "0" * 64
        self.assertIn("VISUAL_ARTIFACT_BINDING_INVALID:product_views:front", _typed_comparison_gaps(row, *args))

    def test_missing_sources_do_not_turn_low_into_medium(self):
        for review in self.values[-2:]:
            review["assessments"][0]["risk"] = "低"
            review["assessments"][0]["comparison"]["criteria"][0]["result"] = "excludes_risk"
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "无法判断")
        self.assertNotEqual(result["overall"]["discovery_signal"], "中")

    def test_provenance_artifact_tampering_is_rejected(self):
        task, evidence, candidates, plan, *_ = self.values
        payload = evidence["collections"]["asset_provenance"][0]["payload"]
        query = plan["queries"]["asset_provenance"][0]
        validate_payload(self.directory, payload, query, candidates)
        (self.directory / "source.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError, "HASH"):
            validate_payload(self.directory, payload, query, candidates)

    def test_offline_bundle_preserves_local_high_and_detects_tampering(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        result = self.calculate()
        atomic_write_json(self.directory / "materiality-annotations.json", ledger)
        journal = {"schema_version": "1.0", "task_id": task["task_id"], "entries": []}
        data, manifest = build_v24_bundle(self.directory, task, evidence, result, candidates, journal, plan)
        self.assertEqual(data["report_mode"], "Partial")
        html = (self.directory / "report.html").read_text()
        self.assertIn("已确认分项最高风险（全范围未完成）", html)
        self.assertNotIn("<script", html)
        for name, value in (("task", task), ("evidence", evidence), ("assessment", result), ("normalized-candidates", candidates), ("search-plan", plan)):
            atomic_write_json(self.directory / (name + ".json"), value)
        task["outputs"]["report_manifest_sha256"] = sha256_file(self.directory / "report-manifest.json")
        self.assertEqual(validate_run(self.directory, task), [])
        (self.directory / "report.html").write_text(html.replace("已确认分项", "伪造正式结论"))
        self.assertTrue(any("renderer" in error for error in validate_run(self.directory, task)))

    def test_cli_finalize_build_validate_pipeline(self):
        task, evidence, candidates, plan, ledger, first, second = self.values
        for name, value in (("task", task), ("evidence", evidence), ("normalized-candidates", candidates), ("search-plan", plan),
                            ("materiality-annotations", ledger), ("first-review", first), ("second-review", second)):
            atomic_write_json(self.directory / (name + ".json"), value)
        scripts = Path(__file__).resolve().parent
        commands = [("finalize_assessment.py", ["--first-review", str(self.directory / "first-review.json"), "--second-review", str(self.directory / "second-review.json")]),
                    ("build_report.py", []), ("validate_run.py", [])]
        for name, extra in commands:
            completed = subprocess.run([sys.executable, str(scripts / name), "--task-dir", str(self.directory), *extra], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, name + ": " + completed.stderr + completed.stdout)
        self.assertTrue((self.directory / "report.html").is_file())


class SearchCoverageTests(unittest.TestCase):
    def setUp(self):
        self.query = {"query_id": "Q", "operation": "search", "jurisdiction": "US", "right_type": "patent",
                      "requirement_ids": ["COV"], "search_dimension": "text", "search_language": "en", "execution_phase": "initial"}
        self.plan = {"queries": {"epo_ops": [self.query]}}
        run = {"run_id": "R", "provider": "epo_ops", "status": "no_result", **self.query,
               "source_environment": "production", "authoritative_for_final_rating": True,
               "plan_entry_sha256": sha256_json(self.query), "metadata": {"search_coverage": {
                   "schema_valid": True, "total_hits": 0, "retrieved_hits": 0, "truncated": False, "stop_reason": "explicit_zero"}}}
        self.evidence = {"source_runs": [run], "collections": {"patents": [{"evidence_id": "EV", "source_run_id": "R", "payload": {"candidates": []},
            **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}]}}

    def check(self):
        return query_coverage(self.evidence, {}, self.plan, "epo_ops", self.query)

    def test_explicit_zero_complete(self):
        self.assertTrue(self.check()["complete"])

    def test_unknown_total_or_missing_schema_not_zero(self):
        for key, value in (("schema_valid", False), ("total_hits", None)):
            old = self.evidence["source_runs"][0]["metadata"]["search_coverage"][key]
            self.evidence["source_runs"][0]["metadata"]["search_coverage"][key] = value
            self.assertFalse(self.check()["complete"])
            self.evidence["source_runs"][0]["metadata"]["search_coverage"][key] = old

    def test_25_of_500_not_coverage(self):
        run = self.evidence["source_runs"][0]
        run["status"] = "success"
        run["metadata"]["search_coverage"].update(total_hits=500, retrieved_hits=25, reviewed_hits=500, truncated=True)
        self.assertEqual(self.check()["gap"], "SEARCH_TRUNCATED")

    def test_run_cannot_self_assert_hash_or_forged_review_count(self):
        self.evidence["source_runs"][0]["plan_entry_sha256"] = "forged"
        self.assertEqual(bound_runs(self.evidence, self.plan, "epo_ops", self.query), [])
        self.assertFalse(self.check()["complete"])

    def test_captcha_is_gap_not_no_result(self):
        self.evidence["source_runs"][0]["status"] = "needs_user_action"
        self.assertFalse(self.check()["complete"])

    def test_sandbox_zero_never_satisfies_official_recall(self):
        self.evidence["source_runs"][0]["source_environment"] = "sandbox"
        self.assertEqual(self.check()["gap"], "NON_AUTHORITATIVE_RECALL_SOURCE")

    def test_text_success_cannot_cover_missing_classification(self):
        task = {"coverage_requirements": [{"requirement_id": "COV", "jurisdiction": "US", "right_type": "patent", "phase": "official_recall",
                "required_axes": ["text", "classification"], "routes": [{"provider": "epo_ops", "operation": "search"}]}]}
        coverage = coverage_by_scope(task, self.evidence, {}, self.plan)[0]
        self.assertEqual(coverage["status"], "部分完成")
        self.assertIn("COV:AXIS_MISSING:classification", coverage["gaps"])

    def test_zero_keyword_cannot_hide_incomplete_keyword_on_same_axis(self):
        other_query = {**self.query, "query_id": "Q-OTHER", "q": "other structure"}
        self.plan["queries"]["epo_ops"].append(other_query)
        task = {"coverage_requirements": [{"requirement_id": "COV", "jurisdiction": "US", "right_type": "patent", "phase": "official_recall",
                "required_axes": ["text"], "routes": [{"provider": "epo_ops", "operation": "search"}]}]}
        coverage = coverage_by_scope(task, self.evidence, {}, self.plan)[0]
        self.assertIn("COV:AXIS_MISSING:text", coverage["gaps"])
        self.assertNotEqual(coverage["status"], "满足已定义要求")

    def test_foreign_material_candidate_does_not_force_local_expansion(self):
        task = {"coverage_requirements": [{"requirement_id": "COV", "jurisdiction": "US", "right_type": "patent", "phase": "official_recall",
                "required_axes": ["text"], "expansion_required": True, "routes": [{"provider": "epo_ops", "operation": "search"}]}]}
        candidates = {"patents": [{"candidate_id": "JP-CAND", "right_type": "patent", "jurisdiction": "JP", "material": True}]}
        coverage = coverage_by_scope(task, self.evidence, candidates, self.plan)[0]
        self.assertEqual(coverage["status"], "满足已定义要求")

    def test_paginated_distinct_records_must_all_be_reviewed(self):
        task = {"coverage_requirements": [{"requirement_id": "COV", "jurisdiction": "US", "right_type": "patent", "phase": "official_recall",
                "required_axes": ["text"], "routes": [{"provider": "epo_ops", "operation": "search"}]}]}
        plan, evidence, candidates = {"queries": {"epo_ops": []}}, {"source_runs": [], "collections": {"patents": []}}, {"patents": []}
        for page in (1, 2):
            query = {**self.query, "q": "hinged device", "query_id": "Q" + str(page), "range": f"{page}-{page}"}
            run = {"run_id": "R" + str(page), "provider": "epo_ops", "status": "success", **query, "plan_entry_sha256": sha256_json(query),
                   "source_environment": "production", "authoritative_for_final_rating": True,
                   "metadata": {"search_coverage": {"schema_valid": True, "total_hits": 2, "retrieved_hits": 1, "truncated": True, "stop_reason": "page_limit"}}}
            candidate = {"candidate_id": "C" + str(page), "publication_number": "US100" + str(page) + "B1", "jurisdiction": "US", "right_type": "patent", "material": False,
                         "evidence_refs": ["E" + str(page)]}
            entry = {"evidence_id": "E" + str(page), "source_run_id": run["run_id"], "payload": {"candidates": [deepcopy(candidate)]},
                     **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
            plan["queries"]["epo_ops"].append(query)
            evidence["source_runs"].append(run)
            evidence["collections"]["patents"].append(entry)
            candidates["patents"].append(candidate)
        ledger = empty_materiality_ledger("T")
        for candidate in candidates["patents"]:
            ledger["annotations"].append({"annotation_id": "M" + candidate["candidate_id"], "candidate_id": candidate["candidate_id"],
                "candidate_identity_fingerprint": candidate_identity_fingerprint("patents", candidate), "material": False, "decision": "excluded",
                "material_reason": "Different structure", "reviewer": "agent", "annotated_at": now_iso()})
        apply_materiality_annotations(ledger, "T", candidates)
        result = coverage_by_scope(task, evidence, candidates, plan)[0]
        self.assertEqual(result["status"], "满足已定义要求")
        self.assertTrue(all(row["pagination_complete"] for row in result["queries"]))
        evidence["collections"]["patents"][1]["payload"]["candidates"][0]["publication_number"] = "US1001B1"
        self.assertNotEqual(coverage_by_scope(task, evidence, candidates, plan)[0]["status"], "满足已定义要求")


if __name__ == "__main__":
    unittest.main()
