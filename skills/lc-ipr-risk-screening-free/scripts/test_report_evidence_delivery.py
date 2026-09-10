"""Rendering and fact provenance; synthetic source records are not live checks."""
from copy import deepcopy
import csv
import io
import json
import unittest
from unittest.mock import patch

from common import now_iso, sha256_json
import report_estimate as report
import test_report_estimate as legacy_report_test


class EvidenceDeliveryReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy_report_test.EstimateReportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        environment = patch.dict("os.environ", {"LC_IPR_OFFLINE_TESTS": "1"})
        environment.start()
        self.addCleanup(environment.stop)
        f = self.fixture
        f.task.update(schema_version="2.4-free", completion_policy_revision="necessary-work-v2",
                      workflow_correction_revision="workflow-correction-v1", decision_workflow_revision="scenario-triage-v1",
                      primary_scenario_id="product_entry")
        f.assessment.update(status="incomplete", publication={"revision": "necessary-work-v2", "mode": "evidence",
            "delivery_status": "completed", "limitations": [{"scenario_id": "", "jurisdiction": "US", "right_type": "design",
                "kind": "source_lookup", "reason": "OFFICIAL_SOURCE_UNAVAILABLE", "evidence_refs": ["E1"],
                "official_verification": "not_verified", "reasoning": "官方来源未能访问，已保留公开来源原文。"}]})
        f.assessment["overall"].update(risk="高", confidence="低", business_completion="incomplete")
        f.assessment["overall"].update(scenario_id="product_entry", scenario_sha256="a" * 64, assessment_status="complete")
        f.assessment["assessments"][0].update(risk="高", scenario_id="product_entry", scenario_sha256="a" * 64)
        f.assessment["scenario_summaries"] = [{"scenario_id": "product_entry", "scenario_sha256": "a" * 64,
            "title": "同结构选品", "primary": True, "conditional": False, "risk": "高", "confidence": "低", "assumptions": [],
            "assessment_status": "complete", "completion": {"status": "incomplete", "retrieval": "incomplete",
                "triage": "complete", "verification": "incomplete", "assessment": "complete", "queues": {},
                "triage_counts": {"selected": 1, "not_selected": 0, "needs_info": 0, "unreviewed": 0}}}]
        record = f.evidence["collections"][0]
        record.update(provider="public_web", source_name="公开专利聚合来源", checked_at="2026-09-01T02:00:00+00:00",
            payload={"candidate_id": "D1", "jurisdiction": "US", "right_type": "design", "title": "Example design",
                     "legal_status": "Active", "owner": "Example owner"})
        self.candidates = {"designs": [{"candidate_id": "D1", "jurisdiction": "US", "right_type": "design"}]}

    def build(self):
        f = self.fixture
        # This is the rendering unit boundary. Publisher integration tests own
        # canonical assessment/dual-review validation; they are not mocked here.
        data = report.build_report_data(f.root, f.task, f.evidence, f.assessment, self.candidates, f.journal, {},
            output_dir=f.out, report_content=None, verify_assessment=False, visual_policy_revision=None)
        _, manifest = report._write_bundle(data, f.out)
        return data, manifest

    def fact(self, data, name):
        return next(fact for fact in data["verification_basis"]["assessments"][0]["facts"] if fact["field"] == name)

    def test_five_artifacts_disclose_delivery_and_preserve_known_high(self):
        f = self.fixture
        before = deepcopy(f.assessment)
        data, manifest = self.build()
        self.assertEqual(f.assessment, before)
        self.assertEqual(data["overall"]["risk"], "高")
        self.assertEqual(data["overall"]["confidence"], "低")
        self.assertEqual(data["overall"]["business_completion"], "incomplete")
        self.assertEqual(manifest["delivery_status"], "completed")
        self.assertEqual(manifest["verification_basis"]["sha256"], report._digest(data["verification_basis"]))
        self.assertEqual(manifest["section_order"], report.SECTION_ORDER)
        self.assertEqual(len(data["modules"]), 7)
        self.assertEqual(manifest["template_css_sha256"], report._sha(report.CSS_PATH.read_bytes()))
        for name in ("report.html", "report.md", "report-findings.csv"):
            content = (f.out / name).read_text(encoding="utf-8-sig")
            for expected in ("未经官方核验", "公开专利聚合来源", "https://example.com/source", "2026-09-01T02:00:00+00:00", "Active", "OFFICIAL_SOURCE_UNAVAILABLE"):
                self.assertIn(expected, content, name)
        csv_rows = list(csv.DictReader(io.StringIO(report.render_findings_csv(data))))
        item = next(row for row in csv_rows if row["row_type"] == "assessment")
        self.assertEqual(item["risk"], "高")
        self.assertEqual(item["delivery_status"], "completed")
        self.assertIn("法律状态", item["unverified_facts"])
        self.assertEqual(self.fact(data, "legal_status")["basis"], "source_observed")
        self.assertEqual(self.fact(data, "review_inference")["basis"], "inferred")
        self.assertEqual(json.loads((f.out / "report-data.json").read_text())["verification_basis"], data["verification_basis"])

    def test_official_named_object_or_domain_cannot_upgrade_source_active(self):
        entry = self.fixture.evidence["collections"][0]
        entry["source_url"] = "https://ppubs.uspto.gov/pubwebapp/"
        entry["payload"]["official_verification"] = {"status": "verified", "identity_match": True,
            "legal_status": "Active", "owner": "Example owner", "authority": "USPTO", "method": "browser",
            "checked_at": now_iso(), "url": entry["source_url"]}
        data, _ = self.build()
        self.assertEqual(self.fact(data, "legal_status")["basis"], "source_observed")
        self.assertEqual(data["verification_basis"]["fact_counts"]["official_verified"], 0)

    def test_wrong_candidate_and_failed_capture_supply_no_observed_legal_fact(self):
        f = self.fixture
        for candidate_id, status, country in (("OTHER", "success", "US"), ("D1", "failed", "US"), ("D1", "success", "GB")):
            entry = f.evidence["collections"][0]
            entry["payload"]["candidate_id"] = candidate_id
            entry["payload"]["jurisdiction"] = country
            entry["source_run_id"] = "R1"
            f.evidence["source_runs"] = [{"run_id": "R1", "status": status}]
            basis = report.build_verification_basis(f.task, f.evidence, f.assessment, self.candidates, {})
            self.assertEqual(self.fact({"verification_basis": basis}, "legal_status")["basis"], "unknown")

    def test_conflicting_observations_keep_both_sources(self):
        f = self.fixture
        second = deepcopy(f.evidence["collections"][0])
        second.update(evidence_id="E2", source_name="另一公开来源")
        second["payload"]["legal_status"] = "Expired"
        f.evidence["collections"].append(second)
        f.assessment["assessments"][0]["evidence_refs"].append("E2")
        data, _ = self.build()
        fact = self.fact(data, "legal_status")
        self.assertEqual(fact["basis"], "conflicted")
        self.assertEqual(fact["evidence_refs"], ["E1", "E2"])

    def test_historical_time_never_replaced_by_hash_check_or_report_date(self):
        f = self.fixture
        entry = f.evidence["collections"][0]
        entry.update(checked_at="2026-09-09T00:00:00+00:00", checked_at_meaning="retained_file_hash_verification",
                     source_checked_at="2025-01-01T00:00:00+00:00")
        basis = report.build_verification_basis(f.task, f.evidence, f.assessment, self.candidates, {})
        self.assertEqual(basis["sources"][0]["source_checked_at"], "2025-01-01T00:00:00+00:00")
        entry.pop("source_checked_at")
        basis = report.build_verification_basis(f.task, f.evidence, f.assessment, self.candidates, {})
        self.assertEqual(basis["sources"][0]["source_checked_at"], "")

    def test_legacy_report_gets_no_new_delivery_columns_or_labels(self):
        f = self.fixture
        f.task.pop("completion_policy_revision")
        f.assessment.pop("publication")
        data, manifest = self.build()
        self.assertNotIn("verification_basis", data)
        self.assertNotIn("delivery_status", manifest)
        self.assertNotIn("delivery_status", report.render_findings_csv(data).splitlines()[0])
        self.assertNotIn("来源取证报告已生成", report.render_markdown(data))

    def test_ungraded_evidence_delivery_is_not_labeled_as_stage_or_low_risk(self):
        f = self.fixture
        f.task["screening_revision"] = "recall-integrity-v1"
        f.assessment["overall"].update(risk=None, assessment_status="pending", known_scoped_risk=None)
        f.assessment["assessments"][0].update(risk=None, assessment_status="pending", aggregation_included=False,
                                            pending_reasoning="现有取证可留档，尚不足以作风险定级。")
        f.assessment["scenario_summaries"][0].update(risk=None, assessment_status="pending")
        data, manifest = self.build()
        self.assertIsNone(data["overall"]["risk"])
        self.assertIsNone(manifest["overall"]["risk"])
        self.assertEqual(manifest["delivery_status"], "completed")
        for text in (report.render_html(data, f.out), report.render_markdown(data), report.render_findings_csv(data)):
            self.assertIn("来源取证报告", text)
            self.assertNotIn("阶段性报告", text)

    def test_limitation_only_evidence_is_portable_and_scope_disclosure_keeps_status(self):
        f = self.fixture
        entry = deepcopy(f.evidence["collections"][0])
        entry.update(evidence_id="LIMITATION-SOURCE", source_name="受阻补充来源")
        f.evidence["collections"].append(entry)
        limitation = f.assessment["publication"]["limitations"][0]
        limitation.update(scenario_id="product_entry", evidence_refs=["LIMITATION-SOURCE"])
        scope = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "design", "status": "受阻",
                 "verification_status": "incomplete", "retrieval_status": "incomplete", "triage_status": "complete", "queues": {}, "gaps": ["OFFICIAL_SOURCE_UNAVAILABLE"]}
        f.assessment["coverage"]["scopes"] = [scope]
        data, _ = self.build()
        indexed = next(item for item in data["evidence_index"] if item["evidence_id"] == "LIMITATION-SOURCE")
        self.assertTrue((f.out / indexed["path"]).is_file())
        rendered_scope = report._scope_display(data["coverage"]["scopes"][0], data)
        self.assertEqual(rendered_scope["verification_status"], "incomplete")
        self.assertEqual(rendered_scope["delivery_status"], "completed")
        self.assertIn("法律状态", rendered_scope["unverified_facts"])
        self.assertEqual(rendered_scope["delivery_limitations"], [limitation])

    def test_exact_existing_official_predicate_is_required_for_each_fact(self):
        f = self.fixture
        requirement = {"requirement_id": "VERIFY", "phase": "candidate_verification", "jurisdiction": "US",
                       "right_type": "patent", "routes": [{"provider": "uspto_patent_browser", "operation": "candidate_verification"}]}
        f.task["coverage_requirements"] = [requirement]
        row = f.assessment["assessments"][0]
        row.update(right_type="patent", evidence_refs=["E1"])
        candidate = self.candidates["designs"][0]
        candidate.update(right_type="patent", publication_number="US1234567A1", verification_refs=["E1"])
        query = {"query_id": "Q1", "q": "US1234567A1", "candidate_id": "D1", "operation": "candidate_verification",
                 "jurisdiction": "US", "right_type": "patent", "requirement_ids": ["VERIFY"], "required": True}
        plan = {"queries": {"uspto_patent_browser": [query]}}
        common = {key: query[key] for key in ("query_id", "operation", "jurisdiction", "right_type", "requirement_ids")}
        common.update(provider="uspto_patent_browser", plan_entry_sha256=sha256_json(query))
        run = {**common, "run_id": "RUN1", "status": "success", "query": query["q"], "request_params": {"candidate_id": "D1"}}
        entry = deepcopy(f.evidence["collections"][0])
        entry.update(common, source_run_id="RUN1", payload={"candidate_id": "D1", "right_type": "patent", "claims": "A device comprising a housing.",
            "official_verification": {"status": "verified", "identity_match": True, "authority": "USPTO", "method": "cdp_agent",
                "checked_at": now_iso(), "owner": "Example owner", "legal_status": "Active", "url": "https://ppubs.uspto.gov/pubwebapp/"}})
        evidence = {"source_runs": [run], "collections": {"official_verifications": [entry]}}
        basis = report.build_verification_basis(f.task, evidence, f.assessment, self.candidates, plan)
        self.assertEqual(self.fact({"verification_basis": basis}, "legal_status")["basis"], "official_verified")
        # Published claims and the reviewer comparison do not inherit a current
        # status record's official qualification for their own separate facts.
        self.assertEqual(self.fact({"verification_basis": basis}, "claims")["basis"], "source_observed")
        self.assertEqual(self.fact({"verification_basis": basis}, "review_inference")["basis"], "inferred")
        run["plan_entry_sha256"] = "0" * 64
        basis = report.build_verification_basis(f.task, evidence, f.assessment, self.candidates, plan)
        self.assertEqual(self.fact({"verification_basis": basis}, "legal_status")["basis"], "source_observed")


if __name__ == "__main__":
    unittest.main()
