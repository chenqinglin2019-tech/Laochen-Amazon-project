"""09C batch, isolation and chief decision contract."""
import hashlib
import hmac
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, sha256_file, sha256_json
import stage_review_stage_c as mod
from review_progress_stage_a import _fact_digest


SCOPE = {"scenario_id": "base", "jurisdiction": "US", "right_type": "patent", "product_version": "v1"}
ITEM = {"event_id": "J1", "scope": {**SCOPE, "candidate_id": "C1"}, "stage_risk": "中", "evidence_refs": ["E1"],
        "comparison": "产品特征与候选比较", "gaps": [], "applicability": "current",
        "verification_status": "verified", "right_state": "active",
        "right_state_evidence_refs": ["E1"]}
COVERAGE = {"plan_version": 1, "scope": [{**SCOPE, "completed": 1, "planned": 1}], "unreviewed": []}


def request_item(grade="中", refs=None, reasoning="产品事实与权利对应"):
    return {"stage_risk": grade, "evidence_refs": refs if refs is not None else ["E1"],
            "comparison": "逐项比较产品特征", "gaps": [], "reasoning": reasoning}


def receipt(batch, reviewer, suffix, directory):
    log_path = Path(directory) / ("audit-" + suffix + ".json")
    atomic_write_json(log_path, {"workspace_id": "workspace-" + suffix,
        "input_digest": batch["evidence_digest"], "mounted_artifacts": ["frozen_input"],
        "read_artifacts": ["frozen_input"], "task_directory_mounted": False})
    row = {"host": "review-host", "run_id": "run-" + suffix,
           "session_id": "session-" + suffix, "agent_id": "agent-" + suffix,
           "reviewer": reviewer, "workspace_id": "workspace-" + suffix,
           "audit_log_path": str(log_path), "audit_log_sha256": sha256_file(log_path),
           "input_digest": batch["evidence_digest"],
           "first_review_visible": False, "visible_review_ids": [], "read_review_ids": [],
           "output_created_after_isolation": True, "task_directory_mounted": False}
    row["host_hmac_sha256"] = hmac.new(b"test-host-key", sha256_json(row).encode(), hashlib.sha256).hexdigest()
    return row


class StageReviewTest(unittest.TestCase):
    def setUp(self):
        self.key = patch.dict(os.environ, {"LC_IPR_REVIEW_HOST_KEY": "test-host-key"})
        self.key.start()
        self.addCleanup(self.key.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = {"task_id": "T1", "product": {"name": "test"}}
        self.evidence = {"task_id": "T1", "source_runs": [], "stage_risk_events": []}
        self.items = {"J1": ITEM}
        self.current = patch.object(mod, "_current_items", return_value=(self.items, COVERAGE))
        self.current.start()
        self.addCleanup(self.current.stop)
        self.registry = patch.object(mod, "evidence_registry", return_value={"E1": {
            "origin": "evidence", "row": {"evidence_id": "E1", "fact": "原始事实"}}})
        self.registry.start()
        self.addCleanup(self.registry.stop)
        self.freeze = mod._freeze(self.task, self.evidence, {"scope": SCOPE,
            "trigger": "deliverable_batch", "trigger_reasoning": "专项成果已形成",
            "item_ids": ["J1"], "coverage_notes": self.notes()}, [])
        self.freeze["event_id"] = "B1"

    @staticmethod
    def notes():
        return [{"subject": subject, "disposition": "reviewed" if subject == "necessary_directions" else "none",
                 "reasoning": "已核对，当前无额外项目"} for subject in sorted(mod.COVERAGE_SUBJECTS)]

    def review(self, reviewer, suffix, grade="中", reasoning="产品事实与权利对应"):
        row = mod._review({"evidence_digest": self.freeze["evidence_digest"],
            "isolation_receipt": receipt(self.freeze, reviewer, suffix, self.temp.name),
            "items": {"J1": request_item(grade, reasoning=reasoning)},
            "coverage": {k: "审查了" + k for k in ("plan", "unreviewed", "exclusions", "limitations")}},
            self.freeze, [] if suffix == "1" else [self.first])
        row["event_id"] = "R" + suffix
        return row

    def test_two_reviews_and_chief_conflict(self):
        self.first = self.review("甲", "1")
        second = self.review("乙", "2", "低", "具体权利状态与比对不同")
        chief = mod._adjudicate({"review_refs": [
            {"event_id": r["event_id"], "sha256": r["review_sha256"]} for r in (self.first, second)],
            "decisions": {"J1": {"conflict": True, "status": "resolved", "stage_risk": "中",
            "reasoning": "采纳甲的限定事实", "fact_basis": "E1 的状态"}},
            "coverage_reasoning": "必要方向已检查", "chief_reviewer": "主审"},
            self.freeze, [self.first, second], [])
        self.assertEqual(chief["status"], "complete")

    def test_same_grade_different_reason_is_conflict(self):
        self.first = self.review("甲", "1")
        second = self.review("乙", "2", reasoning="不同的排除分析")
        with self.assertRaisesRegex(ValueError, "CONFLICT_NOT_LOCATED"):
            mod._adjudicate({"review_refs": [{"event_id": r["event_id"], "sha256": r["review_sha256"]}
                for r in (self.first, second)], "decisions": {"J1": {"conflict": False,
                "status": "resolved", "stage_risk": "中", "reasoning": "说明", "fact_basis": "E1"}},
                "coverage_reasoning": "已核对", "chief_reviewer": "主审"}, self.freeze, [self.first, second], [])

    def test_missing_fact_enters_original_queue(self):
        self.first = self.review("甲", "1")
        second = self.review("乙", "2", "低")
        chief = mod._adjudicate({"review_refs": [{"event_id": r["event_id"], "sha256": r["review_sha256"]}
                for r in (self.first, second)], "decisions": {"J1": {"conflict": True,
                "status": "needs_supplement", "reasoning": "状态材料缺失", "fact_basis": "E1",
                "gap": {"missing_fact": "当前权利状态", "impact": "可能改变等级",
                "minimal_action": "查当前登记状态", "responsible_step": "来源核验"}}},
                "coverage_reasoning": "缺口已定位", "chief_reviewer": "主审"}, self.freeze,
                [self.first, second], [])
        self.freeze.update(kind="freeze", version=1, previous_event_id="")
        self.freeze["event_id"] = "STAGE-REVIEW-" + sha256_json({"task_id": "T1", "event": {
            k: v for k, v in self.freeze.items() if k != "event_id"}})[:24]
        chief.update(kind="adjudicate", batch_id=self.freeze["event_id"], version=2,
                     previous_event_id=self.freeze["event_id"])
        chief["event_id"] = "STAGE-REVIEW-" + sha256_json({"task_id": "T1", "event": {
            k: v for k, v in chief.items() if k != "event_id"}})[:24]
        queue = mod.supplement_entries({"stage_review_revision": mod.REVISION},
                                       {"task_id": "T1", "stage_review_events": [self.freeze, chief]})
        self.assertEqual(queue[0]["reason"], "STAGE_REVIEW_MINIMAL_SUPPLEMENT")
        self.assertEqual(queue[0]["state"], "awaiting_review")

    def test_isolation_claim_alone_is_rejected(self):
        row = receipt(self.freeze, "甲", "1", self.temp.name)
        row.pop("host_hmac_sha256")
        with self.assertRaisesRegex(ValueError, "ATTESTATION_INVALID"):
            mod._receipt({"isolation_receipt": row}, self.freeze, [])

    def test_signed_log_with_other_review_access_is_rejected(self):
        row = receipt(self.freeze, "甲", "1", self.temp.name)
        path = Path(row["audit_log_path"])
        log = {"workspace_id": row["workspace_id"], "input_digest": self.freeze["evidence_digest"],
               "mounted_artifacts": ["frozen_input", "prior_review"], "read_artifacts": ["frozen_input"],
               "task_directory_mounted": False}
        atomic_write_json(path, log)
        row["audit_log_sha256"] = sha256_file(path)
        row["host_hmac_sha256"] = hmac.new(b"test-host-key", sha256_json({k: v for k, v in row.items()
            if k != "host_hmac_sha256"}).encode(), hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(ValueError, "AUDIT_LOG_SHOWS_FORK_OR_LEAK"):
            mod._receipt({"isolation_receipt": row}, self.freeze, [])

    def test_reused_reviewer_or_workspace_rejected(self):
        self.first = self.review("甲", "1")
        with self.assertRaisesRegex(ValueError, "REVIEWER_OR_WORKSPACE_REUSED"):
            mod._receipt({"isolation_receipt": receipt(self.freeze, "甲", "2", self.temp.name)}, self.freeze, [self.first])

    def test_incomplete_coverage_rejected(self):
        with self.assertRaisesRegex(ValueError, "ITEM_COVERAGE_INCOMPLETE"):
            mod._review({"evidence_digest": self.freeze["evidence_digest"],
                "isolation_receipt": receipt(self.freeze, "甲", "1", self.temp.name), "items": {},
                "coverage": {k: "审查了" + k for k in ("plan", "unreviewed", "exclusions", "limitations")}},
                self.freeze, [])

    def test_changed_or_added_item_stales_batch(self):
        self.items["J2"] = {**ITEM, "event_id": "J2"}
        with self.assertRaisesRegex(ValueError, "FROZEN_INPUT_STALE"):
            mod._assert_current(self.task, self.evidence, self.freeze)

    def test_material_invalidation_requires_event(self):
        with self.assertRaisesRegex(ValueError, "INVALIDATION_REQUIRED"):
            mod._freeze(self.task, self.evidence, {"scope": SCOPE,
                "trigger": "material_invalidation", "trigger_reasoning": "依据失效",
                "item_ids": ["J1"], "coverage_notes": self.notes()}, [])

    def test_material_invalidation_can_freeze_suspended_judgment(self):
        self.items["J1"] = {**ITEM, "applicability": "suspended"}
        self.evidence["stage_risk_events"] = [{"kind": "invalidate", "event_id": "INV1",
            "judgment_id": "J1", "scope": SCOPE}]
        frozen = mod._freeze(self.task, self.evidence, {"scope": SCOPE,
            "trigger": "material_invalidation", "trigger_reasoning": "权利状态变化，立即复核",
            "invalidation_id": "INV1", "item_ids": ["J1"], "coverage_notes": self.notes()}, [])
        self.assertEqual(frozen["invalidation_id"], "INV1")

    def test_missing_retained_fact_is_explicit_in_freeze(self):
        with patch.object(mod, "evidence_registry", return_value={}):
            frozen = mod._freeze(self.task, self.evidence, {"scope": SCOPE,
                "trigger": "wait_or_stop", "trigger_reasoning": "材料暂时缺失，先交接",
                "item_ids": ["J1"], "coverage_notes": self.notes()}, [])
        self.assertEqual(frozen["missing_source_refs"], ["E1"])

    def test_unjudged_candidate_requires_explicit_disposition(self):
        inventory = [{"candidate_id": "C2", "candidate_sha256": "a" * 64}]
        with self.assertRaisesRegex(ValueError, "UNJUDGED_CANDIDATES_UNEXPLAINED"):
            mod._freeze(self.task, self.evidence, {"scope": SCOPE, "trigger": "deliverable_batch",
                "trigger_reasoning": "已有结果", "item_ids": ["J1"],
                "coverage_notes": self.notes()}, [], inventory)
        notes = self.notes()
        excluded = next(row for row in notes if row["subject"] == "excluded_candidates")
        excluded.update(disposition="unreviewed", candidate_ids=["C2"], reasoning="材料未审，留待办")
        frozen = mod._freeze(self.task, self.evidence, {"scope": SCOPE, "trigger": "deliverable_batch",
            "trigger_reasoning": "已有结果", "item_ids": ["J1"], "coverage_notes": notes}, [], inventory)
        self.assertEqual(frozen["unjudged_candidate_ids"], ["C2"])

    def test_candidate_inventory_change_stales_frozen_batch(self):
        with patch.object(mod, "_candidate_inventory", return_value=[{"candidate_id": "C2"}]):
            with self.assertRaisesRegex(ValueError, "FROZEN_INPUT_STALE"):
                mod._assert_current(self.task, self.evidence, self.freeze, Path(self.temp.name))

    def test_stage_review_events_are_not_new_source_facts(self):
        before = _fact_digest(self.evidence)
        self.evidence["stage_review_events"] = [{"kind": "review", "event_id": "R1"}]
        self.evidence["stage_risk_events"] = [{"kind": "review", "event_id": "J1"}]
        self.assertEqual(_fact_digest(self.evidence), before)

    def test_chief_grade_is_projected_without_overwriting_single_review(self):
        self.first = self.review("甲", "1")
        second = self.review("乙", "2", "高", "更严格的比对")
        chief = mod._adjudicate({"review_refs": [
            {"event_id": r["event_id"], "sha256": r["review_sha256"]} for r in (self.first, second)],
            "decisions": {"J1": {"conflict": True, "status": "resolved", "stage_risk": "高",
            "reasoning": "采纳乙的限定事实", "fact_basis": "E1 的具体比较"}},
            "coverage_reasoning": "必要方向已核对", "chief_reviewer": "主审"}, self.freeze,
            [self.first, second], [])
        chief.update(kind="adjudicate", batch_id="B1", event_id="C1")
        frozen = {**self.freeze, "kind": "freeze"}
        rows = [frozen, chief]
        judgment = {**ITEM, "scope": {**SCOPE, "candidate_id": "C1"}, "confidence": "中",
                    "review_status": "single_review_pending_09C", "assessment_date": "2026-09-25"}
        view = {"stage_risk": {"judgments": [judgment], "signals": [],
            "by_country": [{**{k: SCOPE[k] for k in ("scenario_id", "jurisdiction", "product_version")},
                            "coverage_ready_for_09C": True}],
            "by_scenario": [{"scenario_id": "base", "product_version": "v1"}],
            "overall": {"coverage_ready_for_09C": True}}}
        with patch.object(mod, "_events", return_value=rows), patch.object(mod, "_assert_current"):
            result = mod.project({"stage_review_revision": mod.REVISION, "primary_scenario_id": "base"},
                                 view, self.evidence)["stage_risk"]
        self.assertEqual(result["judgments"][0]["single_review_stage_risk"], "中")
        self.assertEqual(result["judgments"][0]["stage_risk"], "高")
        self.assertEqual(result["overall"]["stage_risk"], "高")
        self.assertEqual(result["judgments"][0]["review_status"], "chief_reviewed")

    def test_record_export_submit_and_adjudicate_chain(self):
        task_dir = Path(self.temp.name) / "task"
        task_dir.mkdir()
        atomic_write_json(task_dir / "task.json", {**self.task, "stage_review_revision": mod.REVISION})
        atomic_write_json(task_dir / "evidence.json", self.evidence)
        frozen = mod.record_event(task_dir, {"kind": "freeze", "actor": "协调者",
            "scope": SCOPE, "trigger": "user_stage_request", "trigger_reasoning": "用户要阶段交付",
            "item_ids": ["J1"], "coverage_notes": self.notes()})
        exported = mod.export_batch_input(task_dir, frozen["event_id"])
        self.assertEqual(exported["source_facts"]["E1"]["row"]["fact"], "原始事实")
        reviews = []
        for reviewer, suffix in (("甲", "1"), ("乙", "2")):
            reviews.append(mod.record_event(task_dir, {"kind": "review", "actor": reviewer,
                "batch_id": frozen["event_id"], "evidence_digest": frozen["evidence_digest"],
                "isolation_receipt": receipt(frozen, reviewer, suffix, self.temp.name),
                "items": {"J1": request_item()}, "coverage": {k: "已审" + k for k in
                    ("plan", "unreviewed", "exclusions", "limitations")}}))
        chief = mod.record_event(task_dir, {"kind": "adjudicate", "actor": "主审",
            "batch_id": frozen["event_id"], "review_refs": [
                {"event_id": row["event_id"], "sha256": row["review_sha256"]} for row in reviews],
            "decisions": {"J1": {"conflict": False, "status": "resolved", "stage_risk": "中",
                "reasoning": "两审事实与比较一致", "fact_basis": "E1 原始事实"}},
            "coverage_reasoning": "未审与排除范围已核", "chief_reviewer": "主审"})
        self.assertEqual(chief["status"], "complete")
        self.assertEqual(len(mod._events(mod.load_json(task_dir / "evidence.json"))), 4)


if __name__ == "__main__":
    unittest.main()
