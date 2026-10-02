"""09D preliminary stage delivery and independent validation contracts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from stage_delivery_stage_d import (REVISION, build_model, create_output, render_markdown,
                                    validate_output)


class StageDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "task"
        self.source.mkdir()
        self.task = {"task_id": "T09D", "stage_delivery_revision": REVISION,
            "review_progress_revision": "review-progress-stage-a-v1",
            "product_change_version": "V1", "product": {"product_id": "P1", "title": "测试产品"},
            "primary_scenario_id": "base"}
        self.evidence = {"task_id": "T09D", "collections": {"source": [
            {"evidence_id": "E1", "fact": "事实1"}, {"evidence_id": "E2", "fact": "事实2"}]},
            "source_runs": [], "stage_risk_events": [], "stage_review_events": [],
            "review_progress_events": []}
        self.scope = {"scenario_id": "base", "jurisdiction": "US", "right_type": "patent",
                      "product_version": "V1", "module_id": "utility_patent", "candidate_id": ""}
        self.judgment("J1", "E1", "高")
        self.progress = {"status": "defined", "plan_version": 1, "completed": 60, "planned": 100,
            "percentage": 60, "excluded": {"removed": 0, "exempt": 0}, "items": [],
            "by_scope": [{k: self.scope[k] for k in ("scenario_id", "jurisdiction", "right_type", "product_version")}
                         | {"completed": 60, "planned": 100, "percentage": 60}],
            "by_scope_module": [{k: self.scope[k] for k in ("scenario_id", "jurisdiction", "right_type", "product_version")}
                                | {"module_id": "utility_patent", "completed": 60,
                                   "planned": 100, "percentage": 60}]}
        self.view = {"status": "incomplete", "entries": [{"work_id": "W1", "state": "ready",
            "kind": "agent_investigation", "reason": "仍有可执行工作"}],
            "review_progress": self.progress,
            "stage_risk": {"judgments": [self.row("J1", "E1", "高")], "signals": [],
                "by_country": [{"scenario_id": "base", "jurisdiction": "US", "product_version": "V1",
                                "stage_risk": "高", "display_grade": "阶段性高"}],
                "by_scenario": [{"scenario_id": "base", "product_version": "V1",
                                 "stage_risk": "高", "display_grade": "阶段性高"}],
                "overall": {"stage_risk": "高", "display_grade": "阶段性高",
                            "verification_status": "pending", "review_status": "pending"},
                "stage_review": {"batches": []}, "scopes_without_any_judgment": []}}
        self.save()

    def save(self):
        atomic_write_json(self.source / "task.json", self.task)
        atomic_write_json(self.source / "evidence.json", self.evidence)

    def judgment(self, event_id, ref, grade):
        record = {"origin": "evidence", "row": next(row for row in self.evidence["collections"]["source"]
                                                   if row["evidence_id"] == ref)}
        self.evidence["stage_risk_events"].append({"kind": "review", "event_id": event_id,
            "scope": self.scope, "stage_risk": grade, "evidence_refs": [ref], "outcome_refs": [ref],
            "ref_fingerprints": {ref: sha256_json(record)}})

    def row(self, event_id, ref, grade):
        return {"event_id": event_id, "scope": self.scope, "stage_risk": grade,
                "display_grade": "阶段性" + grade, "applicability": "current",
                "verification_status": "pending", "review_status": "single_review_pending_09C",
                "assessment_date": "2026-09-25", "confidence": None,
                "comparison": "逐项比较", "gaps": [{"missing_fact": "状态", "impact": "影响核实",
                "minimal_action": "核状态"}], "evidence_refs": [ref], "outcome_refs": [ref]}

    def test_preliminary_result_keeps_ready_work_and_real_progress(self):
        model = build_model(self.source, generated_at="2026-09-26T00:00:00Z", view=self.view)
        self.assertEqual(model["progress"]["completed"], 60)
        self.assertEqual(model["stage_risk"]["overall"]["stage_risk"], "高")
        self.assertEqual(model["review_label"], "初步判断／待双审")
        self.assertEqual(model["work"]["entries"][0]["state"], "ready")
        self.assertEqual(model["business_completion"], "not_claimed")
        self.assertIn("60/100", render_markdown(model))

    def test_executed_reviews_needing_facts_are_not_displayed_as_unstarted_reviews(self):
        self.view["stage_risk"]["judgments"][0]["review_status"] = "needs_supplement"
        model = build_model(self.source, view=self.view)
        self.assertEqual(model["review_label"], "所列批次已执行双审主审／待补证")
        self.assertEqual(model["stage_risk"]["overall"]["review_status"], "pending")
        self.assertEqual(model["business_completion"], "not_claimed")
        self.assertIn("已执行双审主审／待补证", render_markdown(model))
        self.judgment("J2", "E2", "低")
        self.view["stage_risk"]["judgments"].append(self.row("J2", "E2", "低"))
        self.save()
        model = build_model(self.source, view=self.view)
        self.assertEqual(model["review_label"], "初步判断／待双审")

    def test_delivery_preserves_original_comparison_and_discloses_actual_chief_basis(self):
        model = build_model(self.source, view=self.view)
        row = model["stage_risk"]["judgments"][0]
        row.update(review_status="chief_reviewed", chief_fact_basis="参考耳部被遮挡，不能确认完整耳长",
                   chief_reasoning="采纳仅限可见材料的阶段判断")
        rendered = render_markdown(model)
        self.assertIn("原单审比较：逐项比较", rendered)
        self.assertIn("参考耳部被遮挡，不能确认完整耳长", rendered)
        self.assertEqual(row["comparison"], "逐项比较")
        row["review_status"] = "invalid_for_delivery"
        self.assertNotIn("主审事实：", render_markdown(model))

    def test_one_bad_ref_is_quarantined_and_independent_higher_grade_remains(self):
        self.judgment("J2", "E2", "极高")
        self.view["stage_risk"]["judgments"].append(self.row("J2", "E2", "极高"))
        self.evidence["stage_risk_events"][0]["ref_fingerprints"]["E1"] = "bad"
        self.save()
        model = build_model(self.source, view=self.view)
        self.assertEqual(model["quarantined_judgments"][0]["event_id"], "J1")
        self.assertEqual(model["stage_risk"]["judgments"][0]["applicability"], "suspended")
        self.assertEqual(model["stage_risk"]["overall"]["stage_risk"], "极高")

    def test_global_product_identity_failure_yields_status_only(self):
        self.task["product"] = {}
        self.save()
        model = build_model(self.source, view=self.view)
        self.assertEqual(model["stage_risk"], {})
        self.assertIn("PRODUCT_IDENTITY_MISSING", model["identity_errors"])
        self.assertEqual(model["progress"]["completed"], 60)

    def test_unverifiable_chief_proof_downgrades_to_preliminary(self):
        self.view["stage_risk"]["judgments"][0].update(review_status="chief_reviewed",
            single_review_stage_risk="中", review_batch_id="B1", stage_risk="高")
        model = build_model(self.source, view=self.view)
        self.assertEqual(model["stage_risk"]["judgments"][0]["stage_risk"], "中")
        self.assertEqual(model["stage_risk"]["judgments"][0]["review_status"], "awaiting_valid_independent_review")
        self.assertEqual(model["review_label"], "初步判断／待双审")

    def test_completed_batch_keeps_older_grade_cutoff_and_ready_work(self):
        self.view["stage_risk"]["judgments"][0].update(review_status="chief_reviewed",
            review_batch_id="B1", chief_event_id="C1")
        self.view["stage_risk"]["stage_review"]["batches"] = [{"batch_id": "B1",
            "scope": {k: self.scope[k] for k in ("scenario_id", "jurisdiction", "right_type", "product_version")},
            "status": "complete", "evidence_digest": "digest"}]
        frozen = {"event_id": "B1", "kind": "freeze", "stage_risk_cutoff": 1,
            "evidence_cutoff": 0, "coverage": {"plan_version": 1, "scope": [{**self.scope,
            "completed": 15, "planned": 30}]}}
        self.progress["completed"] = 20
        self.progress["planned"] = 30
        self.progress["percentage"] = 66.7
        self.progress["by_scope"][0].update(completed=20, planned=30, percentage=66.7)
        with patch("stage_delivery_stage_d._review_receipt_valid", return_value=True), \
             patch("stage_review_stage_c._events", return_value=[frozen]):
            model = build_model(self.source, view=self.view)
        self.assertEqual(model["review_label"], "所列批次已双审主审")
        self.assertEqual(model["grade_cutoff"]["batches"][0]["later_completed_not_in_batch"], 5)
        self.assertEqual(model["work"]["entries"][0]["state"], "ready")
        self.assertIn("较新已完成工作尚未纳入", " ".join(model["limitations"]))

    def test_validation_receipt_cannot_be_claimed_as_delivery(self):
        out = self.root / "stage-output"
        with patch("workflow_v24.work_view_from_dir", return_value=self.view):
            create_output(self.source, out)
            receipt = load_json(out / "stage-validation.json")
            receipt["actual_delivery"] = "claimed"
            atomic_write_json(out / "stage-validation.json", receipt)
            self.assertEqual(validate_output(self.source, out), ["STAGE_VALIDATION_RECEIPT_MISMATCH"])

    def test_signal_without_review_proof_keeps_stage_preliminary(self):
        self.view["stage_risk"]["judgments"][0].update(review_status="chief_reviewed",
            review_batch_id="B1", chief_event_id="C1")
        self.view["stage_risk"]["signals"] = [{"event_id": "S1", "review_status": "chief_reviewed",
            "review_batch_id": "B1", "chief_event_id": "C1", "chief_signal_conclusion": "已审信号",
            "signal_reasoning": "原始信号"}]
        with patch("stage_delivery_stage_d._review_receipt_valid", side_effect=[True, False]):
            model = build_model(self.source, view=self.view)
        self.assertEqual(model["review_label"], "初步判断／待双审")
        self.assertNotIn("chief_signal_conclusion", model["stage_risk"]["signals"][0])

    def test_output_round_trip_and_stale_source_rejected(self):
        out = self.root / "stage-output"
        with patch("workflow_v24.work_view_from_dir", return_value=self.view):
            receipt = create_output(self.source, out)
            self.assertEqual(receipt["status"], "locally_validated")
            self.assertEqual(validate_output(self.source, out), [])
            self.evidence["source_runs"].append({"run_id": "NEW"})
            self.save()
            self.assertIn("STAGE_RESULT_SOURCE_OR_MODEL_CHANGED", validate_output(self.source, out))

    def test_changed_rendered_bytes_and_output_reuse_rejected(self):
        out = self.root / "stage-output"
        with patch("workflow_v24.work_view_from_dir", return_value=self.view):
            create_output(self.source, out)
            with self.assertRaisesRegex(ValueError, "NEW_OUTPUT_DIRECTORY_REQUIRED"):
                create_output(self.source, out)
            (out / "stage-result.md").write_text("伪造结果")
            self.assertIn("STAGE_ARTIFACT_MISMATCH:stage-result.md", validate_output(self.source, out))


if __name__ == "__main__":
    unittest.main()
