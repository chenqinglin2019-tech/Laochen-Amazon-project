from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "demand_insight_v5.py"
SPEC = importlib.util.spec_from_file_location("demand_insight_v5", MODULE_PATH)
assert SPEC and SPEC.loader
insight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(insight)


class DemandInsightV5Test(unittest.TestCase):
    def test_review_plan_selects_three_parent_limit_and_reuses_shared_asin(self) -> None:
        payload = {
            "sales_stat_period": "2026-08",
            "segments": [
                {"segment_id": "a", "valid": True, "listing_share": 0.10, "candidates": [
                    {"asin": "A1", "parent_id": "P1", "sales": 100, "sales_stat_period": "2026-08"},
                    {"asin": "A2", "parent_id": "P2", "sales": 90, "sales_stat_period": "2026-08"},
                ]},
                {"segment_id": "b", "valid": True, "listing_share": 0.12, "candidates": [
                    {"asin": "A2", "parent_id": "P2", "sales": 90, "sales_stat_period": "2026-08"},
                    {"asin": "B1", "parent_id": "P3", "sales": 80, "sales_stat_period": "2026-08"},
                ]},
            ],
        }
        result = insight.plan_reviews(payload)
        self.assertEqual(2000, result["segments"][0]["effective_text_review_target"])
        shared = next(item for item in result["unique_products"] if item["asin"] == "A2")
        self.assertEqual(["a", "b"], shared["segment_ids"])

    def test_review_summary_keeps_same_text_with_different_ids_and_deduplicates_id(self) -> None:
        payload = {"records": [
            {"content_id": "R1", "source_kind": "review", "segment_ids": ["a"], "text": "same", "coding_status": "coded", "needs": [{"code": "fit"}, {"code": "fit"}, {"code": "wash"}], "metadata": {"request_asin": "A1", "purchase_variant": "unknown"}},
            {"content_id": "R1", "source_kind": "review", "segment_ids": ["a"], "text": "same", "coding_status": "coded", "needs": [{"code": "fit"}], "metadata": {"request_asin": "A1", "purchase_variant": "unknown"}},
            {"content_id": "R2", "source_kind": "review", "segment_ids": ["a"], "text": "same", "coding_status": "coded", "needs": [{"code": "fit"}], "metadata": {"request_asin": "A2", "purchase_variant": "unknown"}},
        ]}
        segment = insight.summarize_voices(payload, "review")["segments"][0]
        self.assertEqual(2, segment["unique_record_id_count"])
        self.assertEqual(2, segment["coded_effective_text_record_count"])
        counts = {item["need_code"]: item["mention_count"] for item in segment["needs"]}
        self.assertEqual(2, counts["fit"])
        self.assertEqual(1, counts["wash"])

    def test_question_limits_ledger_recovery_and_alexa_exclusion(self) -> None:
        questions = {"questions": [{
            "question_id": "q1", "segment_id": "a", "phase": "initial", "question": "What fit range?",
            "source_refs": ["keyword:k1"], "target": {"asin": "A1"}, "development_decision": "fit system",
            "expected_verification": "size chart", "followup_condition": "range absent",
        }]}
        self.assertEqual("q1", insight.active_question_plan(questions)["questions"][0]["question_id"])
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "active_qa_ledger.jsonl"
            for state in ("submitting", "submitted"):
                insight.append_qa_event(ledger, {"question_id": "q1", "state": state, "page_binding": "product:A1"})
            completed = insight.append_qa_event(ledger, {"question_id": "q1", "state": "completed", "page_binding": "product:A1", "answer": "sizes", "completion_verified": True})
            self.assertTrue(completed["completion_verified"])
            self.assertEqual(3, len(ledger.read_text(encoding="utf-8").splitlines()))
        evidence = insight.evidence_links({"needs": [{"need_id": "fit", "evidence": [
            {"source_type": "review", "source_id": "R1", "role": "support"},
            {"source_type": "social", "source_id": "S1", "role": "support"},
            {"source_type": "alexa", "source_id": "Q1", "role": "research_signal"},
        ]}]})["needs"][0]
        self.assertEqual({"review_unique_records": 1, "social_unique_records": 1}, evidence["consumer_voice_counts"])
        self.assertEqual(1, evidence["research_signal_counts"]["alexa_refs"])
        self.assertIn("never enter", evidence["guardrail"])

    def test_question_plan_rejects_overfilled_initial_quota(self) -> None:
        template = {"segment_id": "a", "phase": "initial", "question": "x", "source_refs": ["r"], "target": {"keyword": "x"}, "development_decision": "d", "expected_verification": "v", "followup_condition": "f"}
        payload = {"questions": [dict(template, question_id="q%d" % index) for index in range(7)]}
        with self.assertRaises(insight.ContractError):
            insight.active_question_plan(payload)


if __name__ == "__main__":
    unittest.main()
