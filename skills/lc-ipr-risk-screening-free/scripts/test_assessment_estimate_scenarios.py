"""Offline scenario/triage policy regressions, not live recall or legal findings."""
from copy import deepcopy
from pathlib import Path
import csv
import io
import tempfile
import unittest
from unittest.mock import patch

from common import sha256_json
from assessment_estimate import (compute_assessment, review_digest, _validate_implementation_claims,
    KNOWN_FINDINGS_REVISION, known_findings_enabled)
from decision_workflow import (REVISION, default_assessment_scenarios, make_annotation,
                               scenario_sha256)
from test_assessment_estimate_recall import strict_fixture
from report_estimate import build_report_data, render_html, render_markdown, render_findings_csv


def scenario_fixture(directory):
    values = strict_fixture(directory)
    task, evidence, candidates, plan, ledger, first, second = values
    candidate = candidates["copyright_assets"].pop()
    candidate["right_type"] = "trademark_word"
    candidates["trademarks"].append(candidate)
    query = plan["queries"]["asset_provenance"][0]
    query["right_type"] = "trademark_word"
    for item in (evidence["source_runs"][0], evidence["collections"]["asset_provenance"][0]):
        item.update(right_type="trademark_word", plan_entry_sha256=sha256_json(query))
    evidence["collections"]["asset_provenance"][0]["payload"]["right_type"] = "trademark_word"
    task.update(decision_workflow_revision=REVISION, primary_scenario_id="product_entry",
                assessment_scenarios=default_assessment_scenarios())
    plan["decision_workflow_revision"] = REVISION
    ledger.clear()
    ledger.update(schema_version="2.0", task_id=task["task_id"], annotations=[])
    for scenario in task["assessment_scenarios"]:
        decision = {"annotation_id": "A-" + scenario["scenario_id"], "decision": "selected",
            "scenario_id": scenario["scenario_id"], "reason": "Original source supports bounded comparison.",
            "reading_level": "full_document", "basis_summary": "Original source and visible expression reviewed.",
            "reopen_conditions": ["New materially different licence or product expression."],
            "reviewer": "triage-agent", "annotated_at": "2026-09-07T00:00:00+00:00", "evidence_refs": ["EV-PROV"]}
        ledger["annotations"].append(make_annotation(task, "trademarks", candidate, decision, evidence=evidence))
    primary = task["assessment_scenarios"][0]
    for review in (first, second):
        review["assessments"][0].update(right_type="trademark_word", module_id="word_mark",
            scenario_id=primary["scenario_id"], scenario_sha256=primary["scenario_sha256"])
    refresh(values)
    return values


def refresh(values):
    task, evidence, candidates, plan, ledger, first, second = values
    digest = review_digest(evidence, candidates, ledger, plan, task)
    for review in (first, second):
        review["review_context"]["evidence_digest"] = digest


class ScenarioEstimateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.values = scenario_fixture(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def scopes(self, complete=False):
        return [{"scenario_id": s["scenario_id"], "scenario_sha256": s["scenario_sha256"],
            "jurisdiction": "US", "right_type": "trademark_word", "status": "满足已定义要求" if complete else "部分完成",
            "retrieval_status": "complete" if complete else "incomplete", "triage_status": "complete",
            "verification_status": "complete" if complete else "incomplete", "queries": [],
            "gaps": [] if complete else ["REQUIRED_RECALL_INCOMPLETE"], "obligations": [], "queues": {}}
            for s in self.values[0]["assessment_scenarios"]]

    def calculate(self, *, complete=False, **kwargs):
        # The aggregation unit test supplies explicit obligation state; source,
        # file, reviewer, triage and candidate-binding validation still run.
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes(complete)), \
                patch("workflow_v24.scenario_execution_gaps", return_value=[], create=True):
            return compute_assessment(*self.values, **kwargs)

    def rows(self, **changes):
        for review in self.values[-2:]:
            review["assessments"][0].update(deepcopy(changes))

    def add_brand_row(self, risk="极高"):
        scenario = self.values[0]["assessment_scenarios"][1]
        for review in self.values[-2:]:
            row = deepcopy(review["assessments"][0])
            row.update(scenario_id=scenario["scenario_id"], scenario_sha256=scenario["scenario_sha256"], risk=risk)
            review["assessments"].append(row)

    def change_decision(self, decision, sid="product_entry"):
        task, evidence, candidates, _, ledger, *_ = self.values
        old = next(row for row in ledger["annotations"] if row["scenario_id"] == sid)
        proposal = {**old, "decision": decision}
        if decision == "needs_info":
            proposal.update(missing_information=["Original provenance terms"], next_actions=[{
                "action_id": "ask-license", "kind": "user_information", "purpose": "Resolve origin",
                "question": "Can the source licence be supplied?"}])
        ledger["annotations"][ledger["annotations"].index(old)] = make_annotation(task, "trademarks", candidates["trademarks"][0], proposal, evidence=evidence)
        refresh(self.values)

    def test_current_high_survives_incomplete_and_unrelated_global_low_cap(self):
        for review in self.values[-2:]:
            review["coverage_confidence_cap"] = "低"
        result = self.calculate()
        self.assertEqual((result["overall"]["risk"], result["overall"]["confidence"], result["status"]), ("高", "高", "incomplete"))

    def test_scope_gap_deduplication_does_not_discard_real_query_identity(self):
        scopes = self.scopes()
        scopes[0]["gaps"] = ["REQUIRED_RECALL_INCOMPLETE"]
        execution = [{"scenario_id": "product_entry", "code": "REQUIRED_RECALL_INCOMPLETE", **extra}
                     for extra in ({}, {"query_id": ""}, {"query_id": None}, {"query_id": "Q1"}, {"query_id": "Q2"})]
        with patch("assessment_estimate.coverage_by_scope", return_value=scopes), \
                patch("workflow_v24.scenario_execution_gaps", return_value=execution):
            result = compute_assessment(*self.values)
        gaps = result["scenario_summaries"][0]["completion"]["gaps"]
        self.assertEqual([gap for gap in gaps if gap.startswith("REQUIRED_RECALL_INCOMPLETE")],
                         ["REQUIRED_RECALL_INCOMPLETE", "REQUIRED_RECALL_INCOMPLETE:Q1", "REQUIRED_RECALL_INCOMPLETE:Q2"])
        self.assertEqual((result["overall"]["risk"], result["status"]), ("高", "incomplete"))

    def test_real_obligation_engine_keeps_risk_independent_from_completion(self):
        result = compute_assessment(*self.values)
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(result["coverage"]["scopes"])
        self.assertTrue(all(scope.get("scenario_id") for scope in result["coverage"]["scopes"]))

    def test_unknown_revision_does_not_silently_fall_back(self):
        self.values[0]["decision_workflow_revision"] = "unsupported-next"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_DECISION"):
            self.calculate()

    def patent_candidate(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        task["assessment_scenarios"] = task["assessment_scenarios"][:1]
        candidate = candidates["trademarks"].pop()
        candidate.update(right_type="patent", publication_number="US1234567B2")
        candidates["patents"].append(candidate)
        query = plan["queries"]["asset_provenance"][0]
        query["right_type"] = "patent"
        for item in (evidence["source_runs"][0], evidence["collections"]["asset_provenance"][0]):
            item.update(right_type="patent", plan_entry_sha256=sha256_json(query))
        evidence["collections"]["asset_provenance"][0]["payload"]["right_type"] = "patent"
        ledger["annotations"] = [make_annotation(task, "patents", candidate, {**ledger["annotations"][0], "right_type": "patent"}, evidence=evidence)]
        self.rows(right_type="patent", module_id="utility_patent")
        refresh(self.values)

    def test_selected_current_utility_cannot_use_generic_criteria_only(self):
        self.patent_candidate()
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_CLAIM_COMPARISON_REQUIRED"):
            self.calculate()

    def test_selected_future_does_not_require_current_claim_table(self):
        self.patent_candidate()
        self.rows(future_signal=True)
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"], [])

    def test_selected_current_utility_with_independent_group_is_accepted(self):
        self.patent_candidate()
        comparison = {"criteria": [], "implementations": [{"implementation_id": "as_described", "title": "Observed configuration",
            "description": "The observed flexible strap used with a lid.", "product_evidence_refs": ["EV-PRODUCT"]}],
            "claims": [{"implementation_id": "as_described", "claim_id": "1", "claim_type": "independent",
                "claim_evidence_refs": ["EV-PROV"], "conclusion": "unknown", "elements": [{
                    "claim_element": "Connection element", "claim_quote": "a connection element", "product_feature": "Partly hidden connection",
                    "result": "unknown", "evidence_refs": ["EV-PROV"], "product_evidence_refs": ["EV-PRODUCT"]}]}]}
        self.rows(comparison=comparison, risk="中", evidence_confidence="低")
        self.assertEqual(self.calculate()["overall"]["risk"], "中")

    def test_conditional_higher_risk_does_not_replace_primary(self):
        self.rows(risk="中")
        self.add_brand_row()
        result = self.calculate()
        self.assertEqual(result["overall"]["risk"], "中")
        self.assertEqual(result["scenario_summaries"][1]["risk"], "极高")
        self.assertTrue(all(d["scenario_id"] == "product_entry" for d in result["overall"]["drivers"]))

    def test_scenario_key_does_not_create_false_review_conflict(self):
        self.add_brand_row()
        result = self.calculate()
        self.assertEqual(len(result["assessments"]), 2)
        self.assertTrue(all(not row["review_resolution"]["conflicts"] for row in result["assessments"]))

    def test_review_scenario_hash_and_digest_are_bound(self):
        old = self.values[-1]["review_context"]["evidence_digest"]
        self.values[0]["assessment_scenarios"][0]["assumptions"].append("Changed embodiment")
        scenario = self.values[0]["assessment_scenarios"][0]
        scenario["scenario_sha256"] = scenario_sha256(scenario)
        self.assertNotEqual(old, review_digest(*self.values[1:5], self.values[0]))
        refresh(self.values)
        with self.assertRaisesRegex(ValueError, "SCENARIO_BINDING"):
            self.calculate()

    def test_only_local_low_does_not_imply_overall_low_when_recall_missing(self):
        self.rows(risk="低", counter_evidence=[{"reasoning": "Documented expression differs.", "evidence_refs": ["EV-PROV"]}])
        result = self.calculate()
        self.assertEqual(result["overall"]["known_scoped_risk"], "低")
        self.assertIsNone(result["overall"]["risk"])

    def use_known_findings_policy(self):
        self.values[0]["assessment_revision"] = KNOWN_FINDINGS_REVISION
        refresh(self.values)

    def test_known_policy_pending_candidate_keeps_overall_pending(self):
        self.use_known_findings_policy()
        self.rows(risk=None, assessment_status="pending", pending_reasoning="Internal structure remains unavailable.")
        result = self.calculate()
        row = result["assessments"][0]
        self.assertIsNone(result["overall"]["risk"])
        self.assertEqual(result["overall"]["risk_basis"], "insufficient_evidence")
        self.assertEqual(result["overall"]["listing_recommendation"], "暂缓上架")
        self.assertIsNone(row["risk"])
        self.assertEqual(row["assessment_status"], "pending")
        self.assertFalse(row["risk_aggregation_included"])
        self.assertFalse(result["overall"]["all_scope_clearance"])
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["known_findings"]["by_scope"][0]["risk"])

    def test_known_policy_work_failures_never_change_established_high(self):
        self.use_known_findings_policy()
        base = self.calculate()
        gaps = [{"scenario_id": "product_entry", "code": code, "query_id": "Q-UNFINISHED"}
                for code in ("SOURCE_REQUEST_FAILED", "API_DISCOVERY_BUDGET_EXHAUSTED", "USER_MATERIAL_UNKNOWN")]
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes()), \
                patch("workflow_v24.scenario_execution_gaps", return_value=gaps):
            changed = compute_assessment(*self.values)
        self.assertEqual((base["overall"]["risk"], changed["overall"]["risk"]), ("高", "高"))
        self.assertEqual(changed["overall"]["listing_recommendation"], "不建议上架")
        self.assertEqual(changed["assessments"][0]["evidence_confidence"], "高")
        self.assertEqual(changed["overall"]["risk_basis"], "evidence_supported")
        self.assertTrue(changed["coverage"]["execution_gaps"])

    def test_known_policy_empty_assessments_remain_pending_with_missing_work_visible(self):
        self.use_known_findings_policy()
        self.change_decision("needs_info")
        for review in self.values[-2:]:
            review["assessments"] = []
        result = self.calculate()
        self.assertIsNone(result["overall"]["risk"])
        self.assertEqual(result["overall"]["listing_recommendation"], "暂缓上架")
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(result["scenario_summaries"][0]["completion"]["queues"]["needs_info"])
        self.assertEqual(result["overall"]["drivers"], [])

    def test_known_policy_conditional_high_never_raises_primary(self):
        self.use_known_findings_policy()
        self.rows(risk=None, assessment_status="pending", pending_reasoning="Unresolved expression origin.")
        self.add_brand_row(risk="高")
        for review in self.values[-2:]:
            review["assessments"][-1].update(assessment_status="assessed", pending_reasoning="")
        result = self.calculate()
        self.assertIsNone(result["overall"]["risk"])
        self.assertEqual(result["scenario_summaries"][1]["risk"], "高")
        self.assertEqual(result["scenario_summaries"][0]["completion"]["status"], "incomplete")

    def test_known_policy_future_signal_does_not_become_current_finding(self):
        self.use_known_findings_policy()
        self.rows(risk=None, assessment_status="assessed", future_signal=True)
        result = self.calculate()
        self.assertIsNone(result["overall"]["risk"])
        self.assertEqual(result["overall"]["drivers"], [])
        self.assertIsNone(result["assessments"][0]["risk"])
        self.assertEqual(result["assessments"][0]["known_finding_status"], "signal")
        self.assertFalse(result["assessments"][0]["risk_aggregation_included"])

    def test_known_policy_scope_extreme_low_does_not_clear_whole_product(self):
        self.use_known_findings_policy()
        self.rows(risk="极低", counter_evidence=[{"reasoning": "Decisive limited exclusion.", "evidence_refs": ["EV-PROV"]}],
                  decisive_exclusion={"reasoning": "Actual document has decisive excluded expression.", "evidence_refs": ["EV-PROV"]})
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["risk"], "极低")
        self.assertEqual(result["overall"]["risk"], "低")
        self.assertEqual(result["overall"]["evidence_supported_risk"], "极低")

    def test_known_policy_not_applicable_comes_from_bound_review_not_country_guess(self):
        self.use_known_findings_policy()
        self.rows(candidate_id='', risk=None, assessment_status='pending', pending_reasoning='No applicable regime.',
            scope_applicability={'status':'not_applicable', 'reasoning':'The reviewed regime is not applicable to this bounded product.',
                'evidence_refs':['EV-PROV']})
        result = self.calculate()
        scope = next(row for row in result['known_findings']['by_scope'] if row['scenario_id'] == 'product_entry')
        self.assertEqual(scope['applicability'], 'not_applicable')
        self.assertIn('bounded product', scope['query_not_required_reason'])
        self.assertEqual(scope['applicability_evidence_refs'], ['EV-PROV'])
        self.rows(scope_applicability=None)
        scope = next(row for row in self.calculate()['known_findings']['by_scope'] if row['scenario_id'] == 'product_entry')
        self.assertEqual(scope['applicability'], 'applicable')
        self.assertNotIn('query_not_required_reason', scope)

    def test_known_policy_change_requires_new_digest_not_old_review_rebinding(self):
        old_digest = self.values[-2]["review_context"]["evidence_digest"]
        self.values[0]["assessment_revision"] = KNOWN_FINDINGS_REVISION
        self.assertTrue(known_findings_enabled(self.values[0]))
        current_digest = review_digest(self.values[1], self.values[2], self.values[4], self.values[3], self.values[0])
        self.assertNotEqual(old_digest, current_digest)
        with self.assertRaisesRegex(ValueError, "REVIEW_CONTEXT_INVALID"):
            self.calculate()

    def test_not_selected_needs_no_substantive_rating(self):
        self.change_decision("not_selected")
        for review in self.values[-2:]:
            review["assessments"] = []
        result = self.calculate()
        primary = result["scenario_summaries"][0]
        self.assertEqual(primary["completion"]["queues"]["selected_unassessed"], [])
        self.assertIsNone(result["overall"]["risk"])

    def test_unreviewed_auto_material_cannot_support_final_row(self):
        self.values[4]["annotations"] = []
        refresh(self.values)
        with self.assertRaisesRegex(ValueError, "CURRENT_SELECTED_TRIAGE"):
            self.calculate()

    def test_needs_info_is_precise_queue_not_false_exclusion(self):
        self.change_decision("needs_info")
        for review in self.values[-2:]:
            review["assessments"] = []
        result = self.calculate()
        queue = result["scenario_summaries"][0]["completion"]["queues"]
        self.assertEqual([r["candidate_id"] for r in queue["needs_info"]], ["C-ART"])
        self.assertEqual(queue["selected_unassessed"], [])

    def test_future_selected_review_not_current_missing_or_driver(self):
        self.rows(future_signal=True)
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"], [])
        self.assertIsNone(result["overall"]["risk"])

    def test_reviewed_future_signal_needs_no_fictional_current_risk_grade(self):
        self.rows(future_signal=True, risk=None, assessment_status="assessed")
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"], [])
        self.assertIsNone(result["overall"]["risk"])
        self.assertIsNone(result["assessments"][0]["risk"])

    def test_null_current_grade_cannot_claim_assessed_without_signal_or_pending(self):
        self.rows(risk=None, assessment_status="assessed")
        with self.assertRaisesRegex(ValueError, "FIVE_LEVEL_RISK"):
            self.calculate()

    def test_unrelated_false_confidence_fact_does_not_template_overwrite(self):
        self.rows(confidence_basis={"comparison": {"satisfied": False, "reasoning": "An ancillary image is unknown.", "evidence_refs": []}})
        result = self.calculate()
        self.assertEqual(result["assessments"][0]["evidence_confidence"], "高")
        self.assertTrue(result["assessments"][0]["confidence_gaps"])
        self.assertTrue(any("具体影响见主审理由" in gap for gap in result["assessments"][0]["confidence_gaps"]))
        self.assertFalse(any("并降低置信度" in gap for gap in result["assessments"][0]["confidence_gaps"]))

    def test_scenario_cap_affects_only_its_scenario(self):
        self.add_brand_row()
        scenario = self.values[0]["assessment_scenarios"][1]
        for review in self.values[-2:]:
            review["scenario_confidence_caps"] = {"brand_reuse": {"scenario_sha256": scenario["scenario_sha256"],
                "confidence": "低", "reasoning": "Brand use scope uncertain.", "evidence_refs": ["EV-PRODUCT"]}}
        result = self.calculate()
        self.assertEqual(result["overall"]["confidence"], "高")
        self.assertEqual(result["scenario_summaries"][1]["confidence"], "低")

    def test_complete_obligations_can_complete_without_clearing_conditional_risk(self):
        self.add_brand_row()
        result = self.calculate(complete=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertFalse(result["overall"]["all_scope_clearance"])

    def test_three_report_formats_keep_primary_and_conditional_separate(self):
        self.rows(risk="中")
        self.add_brand_row()
        result = self.calculate()
        task, evidence, candidates, plan, *_ = self.values
        with patch("report_estimate._require_safe"):
            data = build_report_data(self.directory, task, evidence, result, candidates, {}, plan, verify_assessment=False)
        self.assertEqual(data["modules"][3]["risk"], "中")
        html = render_html(data, self.directory)
        md = render_markdown(data)
        rows = list(csv.DictReader(io.StringIO(render_findings_csv(data))))
        for text in (html, md):
            self.assertIn("条件情景", text)
            self.assertIn("检索 未完成", text)
            self.assertIn("极高风险", text)
        self.assertEqual(next(r for r in rows if r["row_type"] == "overall")["risk"], "中")
        total = next(r for r in rows if r["row_type"] == "overall")
        self.assertEqual((total["assessment_status"], total["business_completion"], total["assessment_completion"]),
                         (result["overall"]["assessment_status"], "incomplete", result["scenario_summaries"][0]["completion"]["assessment"]))
        conditional = next(r for r in rows if r["row_type"] == "scenario" and r["scenario_id"] == "brand_reuse")
        self.assertEqual((conditional["risk"], conditional["retrieval_status"]), ("极高", "incomplete"))
        self.assertEqual(conditional["assessment_status"], result["scenario_summaries"][1]["assessment_status"])
        self.assertEqual(conditional["assessment_completion"], result["scenario_summaries"][1]["completion"]["assessment"])

    def test_report_labels_necessary_and_whole_ledger_counts_without_changing_risk(self):
        self.add_brand_row()
        result = self.calculate()
        task, evidence, candidates, plan, *_ = self.values
        with patch("report_estimate._require_safe"):
            data = build_report_data(self.directory, task, evidence, result, candidates, {}, plan, verify_assessment=False)
        # Rendering-only fixture for the two denominators; not a business decision.
        primary = data["scenario_summaries"][0]
        primary["completion"]["triage_counts"] = {"selected": 3, "not_selected": 299, "needs_info": 290, "unreviewed": 0}
        primary["completion"]["all_triage_counts"] = {"selected": 3, "not_selected": 340, "needs_info": 290, "unreviewed": 0}
        primary["completion"]["assessment"] = "incomplete"
        data["coverage"]["triage"]["counts"] = {"selected": 8, "not_selected": 376, "needs_info": 290, "unreviewed": 0}
        for text in (render_html(data, self.directory), render_markdown(data), render_findings_csv(data)):
            self.assertIn("必要范围分流 592 条", text)
            self.assertIn("本情景全量台账 633 条", text)
            self.assertIn("全任务分流台账 674 条", text)
            self.assertIn("不等于独立候选数", text)
            self.assertIn("不等于法律排除", text)
        rows = list(csv.DictReader(io.StringIO(render_findings_csv(data))))
        primary_csv = next(row for row in rows if row["row_type"] == "scenario" and row["scenario_id"] == "product_entry")
        self.assertEqual((primary_csv["assessment_status"], primary_csv["assessment_completion"], primary_csv["risk"]),
                         ("assessed", "incomplete", primary["risk"]))


class ClaimIsolationTests(unittest.TestCase):
    def row(self):
        return {"comparison": {"implementations": [{"implementation_id": "strap_only", "title": "Standalone strap",
            "description": "Only the flexible strap is supplied.", "product_evidence_refs": ["EV-PRODUCT"]}],
            "claims": [{"implementation_id": "strap_only", "claim_id": "1", "claim_type": "independent",
                "conclusion": "excludes_risk", "elements": [{"claim_element": "Required hook", "claim_quote": "a hook",
                    "product_feature": "No hook visible", "product_evidence_refs": ["EV-PRODUCT"],
                    "result": "excludes_risk", "evidence_refs": ["EV-CLAIM"]}]}]}}

    def test_same_claim_separate_implementations_allowed(self):
        row = self.row()
        row["comparison"]["implementations"].append({"implementation_id": "pot_combination", "title": "Combination",
            "description": "Strap used with a pot and lid.", "product_evidence_refs": ["EV-PRODUCT"]})
        claim = deepcopy(row["comparison"]["claims"][0])
        claim["implementation_id"] = "pot_combination"
        row["comparison"]["claims"].append(claim)
        _validate_implementation_claims(row)

    def test_other_claim_missing_element_cannot_exclude_this_claim(self):
        row = self.row()
        row["comparison"]["claims"][0]["elements"][0]["claim_id"] = "12"
        with self.assertRaisesRegex(ValueError, "CROSS_SCOPE"):
            _validate_implementation_claims(row)

    def test_other_implementation_cannot_supply_missing_element(self):
        row = self.row()
        row["comparison"]["claims"][0]["elements"][0]["implementation_id"] = "pot_combination"
        with self.assertRaisesRegex(ValueError, "CROSS_SCOPE"):
            _validate_implementation_claims(row)

    def test_exclusion_needs_own_group_excluding_element(self):
        row = self.row()
        row["comparison"]["claims"][0]["elements"][0]["result"] = "unknown"
        with self.assertRaisesRegex(ValueError, "OWN_MISSING_ELEMENT"):
            _validate_implementation_claims(row)

    def test_duplicate_claim_group_rejected(self):
        row = self.row()
        row["comparison"]["claims"].append(deepcopy(row["comparison"]["claims"][0]))
        with self.assertRaisesRegex(ValueError, "CLAIM_IMPLEMENTATION_SCOPE"):
            _validate_implementation_claims(row)


if __name__ == "__main__":
    unittest.main()
