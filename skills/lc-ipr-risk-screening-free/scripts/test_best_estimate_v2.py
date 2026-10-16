"""best-estimate-risk-v2 (round 7): 极高 without the patentee=brand condition, --auto-agree chief drafts,
candidate-subsumed scope rows, the operator evidence block and candidate-bound drawing registration."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

V1 = {"assessment_revision": "known-findings-risk-v1", "best_estimate_revision": "best-estimate-risk-v1"}
V2 = {"assessment_revision": "known-findings-risk-v1", "best_estimate_revision": "best-estimate-risk-v2"}
CAND = "CAND-376fb1059d9db9cdf3"


def detail_evidence(status="Active", assignees=("Individual",)):
    return {"collections": {"patents": [{
        "evidence_id": "EV-detail", "provider": "serpapi_google_patents", "operation": "candidate_detail",
        "right_type": "patent", "jurisdiction": "US", "source_run_id": "ATT-detail",
        "payload": {"candidate_id": CAND, "publication_number": "US11401089B2", "legal_status": status,
                    "title": "Device for and method of securing a lid to a food container",
                    "application_number": "US16/372,470", "filing_date": "2019-04-02", "priority_date": "2018-04-16",
                    "publication_date": "2022-08-02", "assignees": list(assignees),
                    "inventors": [{"name": "Armanda HUGHES"}, {"name": "Cameron HUGHES"}],
                    "pdf": "https://patentimages.storage.googleapis.com/x/US11401089.pdf",
                    "images": ["https://patentimages.storage.googleapis.com/x/US11401089-20220802-D00000.png"],
                    "legal_events": [{"code": "MAFP", "date": "2026-01-28",
                                      "title": "Payment of maintenance fee, 4th year, small entity"}],
                    "claims": ["1. In combination: a food container ..."]}}]}}


def claim_row(results=("supports_risk", "unknown"), risk="高"):
    return {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent", "candidate_id": CAND,
            "assessment_object": "product", "risk": risk, "assessment_status": "assessed", "evidence_confidence": "中",
            "reasoning": "独立项要素对应。", "assumptions": ["端部叠置推定一致。"], "lower_if": ["端部不叠置。"],
            "human_checks": ["核实权利人。"],
            "comparison": {"implementations": [{"implementation_id": "I1", "title": "顶部盖钮安装"}],
                           "claims": [{"implementation_id": "I1", "claim_id": "1", "claim_type": "independent",
                                       "conclusion": "unknown",
                                       "elements": [{"claim_element": "柔性扁平带", "product_feature": "可见扁平带",
                                                     "result": result} for result in results]}]}}


TASK_MARKED = {**V2, "product": {"title": "Lid Latch strap", "bullets": ["PATENTED UNIVERSAL FIT LID LATCH: Flexible silicone"]}}


class ExtremeRuleTests(unittest.TestCase):
    def test_three_facts_give_extreme_and_owner_only_becomes_an_assumption(self):
        from prepare_adjudication import extreme_rule
        applies, reasons, assumptions = extreme_rule(TASK_MARKED, detail_evidence(), claim_row())
        self.assertTrue(applies)
        self.assertEqual(len(reasons), 3)
        self.assertIn("PATENTED", reasons[1])
        self.assertTrue(any("未具名" in text for text in assumptions))

    def test_any_missing_fact_keeps_high(self):
        from prepare_adjudication import extreme_rule
        unmarked = {**V2, "product": {"title": "Lid strap", "bullets": ["Flexible silicone"]}}
        self.assertFalse(extreme_rule(unmarked, detail_evidence(), claim_row())[0])
        self.assertFalse(extreme_rule(TASK_MARKED, detail_evidence(status="Expired - Fee Related"), claim_row())[0])
        self.assertFalse(extreme_rule(TASK_MARKED, detail_evidence(), claim_row(("supports_risk", "excludes_risk")))[0])
        self.assertFalse(extreme_rule(TASK_MARKED, detail_evidence(), claim_row(("unknown", "unknown")))[0])
        self.assertFalse(extreme_rule(TASK_MARKED, {"collections": {"patents": []}}, claim_row())[0])


class AutoAgreeTests(unittest.TestCase):
    def rows(self, left_risk, right_risk):
        left, right = claim_row(risk=left_risk), claim_row(risk=right_risk)
        key = ("k",)
        return {key: left}, {key: right}

    def test_extreme_rule_adds_a_decision_with_reasons(self):
        from prepare_adjudication import _auto_complete
        left, right = self.rows("高", "高")
        decisions, worksheet = [], []
        agreed, extreme = _auto_complete(TASK_MARKED, detail_evidence(), decisions, left, right, {"first": "a", "second": "b"}, worksheet)
        self.assertEqual((agreed, extreme), (0, 1))
        self.assertEqual(decisions[0]["risk"], "极高")
        self.assertEqual(decisions[0]["evidence_confidence"], "高")
        self.assertIn("两审原评高／高", decisions[0]["reasoning"])
        self.assertIn("极高规则", decisions[0]["adjudication_reasoning"])
        self.assertEqual(decisions[0]["review_refs"], {"first": "a", "second": "b"})

    def test_extreme_rule_is_inert_for_v1(self):
        from prepare_adjudication import _auto_complete
        left, right = self.rows("高", "高")
        decisions = []
        _auto_complete({**TASK_MARKED, **V1}, detail_evidence(), decisions, left, right, {}, [])
        self.assertEqual(decisions, [])

    def test_agreeing_conflict_rows_are_settled_and_disagreements_stay_open(self):
        from prepare_adjudication import _auto_complete
        unmarked = {**V2, "product": {"title": "strap"}}
        same = dict(claim_row(risk="低"), candidate_id=None, right_type="design", comparison={})
        other = dict(same, risk="中")
        left = {("a",): same, ("b",): dict(same, right_type="copyright")}
        right = {("a",): dict(same, evidence_confidence="低"), ("b",): dict(other, right_type="copyright")}
        decisions = [dict(same, adjudication_reasoning=""), dict(same, right_type="copyright", adjudication_reasoning="")]
        agreed, extreme = _auto_complete(unmarked, detail_evidence(), decisions, left, right, {}, [])
        self.assertEqual((agreed, extreme), (1, 0))
        self.assertTrue(decisions[0]["adjudication_reasoning"])
        self.assertEqual(decisions[0]["evidence_confidence"], "低")
        self.assertEqual(decisions[1]["adjudication_reasoning"], "")


class PromptTests(unittest.TestCase):
    def test_v2_contract_replaces_the_patentee_condition(self):
        from report_review_host import review_prompt
        prompt = review_prompt({"task": {**V2, "task_id": "T", "target_jurisdictions": ["US"]}}, 1)
        self.assertIn("patent_status_verified_marked_and_claims_correspond", prompt)
        self.assertNotIn("patent_status_verified_marked_and_patentee_product", prompt)
        self.assertIn("权利人未具名", prompt)
        self.assertIn("不写字段名", prompt)
        prompt = review_prompt({"task": {**V1, "task_id": "T", "target_jurisdictions": ["US"]}}, 1)
        self.assertIn("patent_status_verified_marked_and_patentee_product", prompt)
        self.assertNotIn("best-estimate-risk-v2对上文", prompt)


class SubsumedScopeTests(unittest.TestCase):
    def result(self, task):
        from assessment_estimate import _apply_known_findings_revision
        rows = [dict(claim_row(), triage_decision="selected", aggregation_included=True),
                {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent", "candidate_id": None,
                 "assessment_object": "product", "risk": None, "assessment_status": "pending",
                 "pending_reasoning": "由候选决定。"}]
        result = {"assessments": rows, "overall": {"scenario_id": "product_entry"}, "scenario_summaries": [],
                  "review": {"input_reviews": {}}, "coverage": {"scopes": []}, "status": "incomplete"}
        return _apply_known_findings_revision({**task, "task_id": "T"}, result)

    def test_v2_does_not_count_a_scope_row_decided_by_a_graded_candidate(self):
        result = self.result(V2)
        self.assertEqual(result["overall"]["pending_count"], 0)
        self.assertEqual(result["assessments"][1]["known_finding_status"], "subsumed_by_candidate")
        self.assertEqual(result["best_estimate"]["subsumed_scope_rows"][0]["subsumed_by_candidates"], [CAND])
        self.assertEqual(result["overall"]["listing_recommendation"], "不建议上架")

    def test_v1_keeps_counting_it(self):
        result = self.result(V1)
        self.assertEqual(result["overall"]["pending_count"], 1)
        self.assertEqual(result["assessments"][1]["known_finding_status"], "awaiting_judgment")
        self.assertEqual(result["best_estimate"]["revision"], "best-estimate-risk-v1")


class EvidenceBlockTests(unittest.TestCase):
    def test_block_carries_identity_status_marking_claims_and_assumptions(self):
        from operator_report import _evidence_block, _evidence_html
        candidate = {"candidate_id": CAND, "publication_number": "US11401089B2", "right_type": "patent"}
        block = _evidence_block(TASK_MARKED, detail_evidence(), candidate, [claim_row(risk="极高")], [])
        labels = {row["label"]: row["value"] for row in block["identity"]}
        self.assertEqual(labels["现行状态"], "Active（可信 API 记录；最近维持费事件 2026-01-28）")
        self.assertTrue(labels["预计到期"].startswith("2039-04-02"))
        self.assertIn("未具名", labels["权利人"])
        self.assertIn("PATENTED", block["marking"][0])
        self.assertEqual(block["claims"][0]["elements"][0]["result"], "对应")
        self.assertIn("附图未取得", block["missing_figure"])
        page = _evidence_html(block, tempfile.gettempdir())
        self.assertIn("极高风险依据", page)
        self.assertIn("claims-table", page)
        self.assertIn("https://patents.google.com/patent/US11401089B2/en", page)

    def test_no_block_below_high(self):
        from operator_report import _evidence_block
        candidate = {"candidate_id": CAND, "publication_number": "US11401089B2", "right_type": "patent"}
        self.assertIsNone(_evidence_block(TASK_MARKED, detail_evidence(), candidate, [claim_row(risk="中")], []))


class DrawingRegistrationTests(unittest.TestCase):
    def run_recorder(self, task, payload):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "task.json").write_text(json.dumps(task), encoding="utf-8")
            image = root / "d.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            import hashlib
            payload = {**payload, "path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                       "bytes": image.stat().st_size}
            (root / "in.json").write_text(json.dumps(payload), encoding="utf-8")
            script = Path(__file__).with_name("record_public_source.py")
            return subprocess.run([sys.executable, "-X", "utf8", str(script), "--task-dir", str(root), "--input",
                                   str(root / "in.json")], capture_output=True, text=True, env=os.environ)

    def test_drawing_must_bind_a_candidate_under_v2(self):
        payload = {"kind": "patent_drawing_image", "visual_role": "patent_drawings", "publication_number": "US1B2",
                   "source_url": "https://patentimages.storage.googleapis.com/x.png", "reasoning": "官方附图。"}
        result = self.run_recorder({**V2, "task_id": "T"}, payload)
        self.assertIn("PUBLIC_SOURCE_DRAWING_BINDING_INVALID", result.stderr)
        result = self.run_recorder({**V1, "task_id": "T"}, {**payload, "candidate_id": CAND})
        self.assertIn("PUBLIC_SOURCE_DRAWING_BINDING_INVALID", result.stderr)


class ObservationRefsTests(unittest.TestCase):
    def test_v2_binds_observations_by_material_id_only(self):
        from module_review import ModelJudgmentError, validate_original_observations
        packet = {"retained_originals": {"revision": "public-originals-v2", "materials": [
            {"material_id": "M11", "source_refs": ["EV-a", "MEDIA-75515"]}]}}
        raw = {"material_observations": {"M11": {"source_refs": ["EV-a", "MEDIA-82d6"], "observation": "交叉带图样。",
                                                  "limitations": "仅一视图。"}}}
        validate_original_observations(raw, {**packet, "task": V2})
        with self.assertRaisesRegex(ModelJudgmentError, "FINAL_REVIEW_ORIGINAL_OBSERVATION_INVALID: M11"):
            validate_original_observations(raw, {**packet, "task": V1})
        del raw["material_observations"]["M11"]["observation"]
        with self.assertRaisesRegex(ModelJudgmentError, "FINAL_REVIEW_ORIGINAL_OBSERVATION_INVALID: M11"):
            validate_original_observations(raw, {**packet, "task": V2})


if __name__ == "__main__":
    unittest.main()
