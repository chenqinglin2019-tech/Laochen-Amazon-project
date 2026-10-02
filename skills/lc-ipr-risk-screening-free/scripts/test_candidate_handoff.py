"""04C partial handoff and material-completion boundaries."""
import tempfile
import unittest
from pathlib import Path

from common import atomic_write_json, load_json, sha256_bytes
from candidate_handoff import REVISION, load_ledger, project, record_batch, work_entries
from source_result_processing import make_index


class CandidateHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.task = {"task_id": "TASK-HANDOFF", "state": "collecting",
                     "candidate_handoff_revision": REVISION,
                     "candidate_identity_revision": "candidate-identity-v1",
                     "assessment_scenarios": [{"scenario_id": "S-1", "type": "product_entry"}],
                     "target_jurisdictions": ["US", "GB"]}
        self.evidence = {"collections": {"patents": [{"evidence_id": "EV-IMPORT",
            "collected_at": "2026-09-24T00:00:00Z"}]}, "source_runs": []}
        self.candidates = {"patents": [{"candidate_id": "C-1", "normalization_key": "doc:1",
            "right_type": "patent", "jurisdiction": "US", "title": "A",
            "sources": [{"evidence_id": "EV-IMPORT", "source_anchor": "SRC-1"}]}]}
        self.save()

    def save(self):
        for name, value in (("task", self.task), ("evidence", self.evidence),
                            ("normalized-candidates", self.candidates)):
            atomic_write_json(self.path / (name + ".json"), value)

    def review(self, country, *, evidence_id="EV-IMPORT", applicability="applicable"):
        return {"candidate_id": "C-1", "scenario_id": "S-1", "jurisdiction": country,
                "applicability": applicability, "reason": "Retained source applies to this scope",
                "evidence_refs": [evidence_id]}

    def test_same_source_can_handoff_two_scopes_in_one_batch_without_new_run(self):
        first = project(self.task, self.evidence, self.candidates, self.path)
        self.assertEqual(first["rows"][0]["handoff_state"], "ready")
        self.assertEqual(len(first["rows"][0]["remaining_scopes"]), 2)
        request = {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("US"), self.review("GB")],
            "reviewer": "agent", "reason": "Two target scopes reviewed against one retained source"}
        event = record_batch(self.path, request)
        self.assertEqual(record_batch(self.path, request), event)
        self.assertEqual(len(event["scope_reviews"]), 2)
        self.assertEqual(project(self.task, self.evidence, self.candidates, self.path)
                         ["rows"][0]["handoff_state"], "current")
        self.assertEqual(self.evidence["source_runs"], [])
        self.assertEqual(len(load_ledger(self.path, self.task)["batches"]), 1)

    def test_handoff_history_change_is_rejected(self):
        record_batch(self.path, {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("US")], "reviewer": "agent", "reason": "US scope ready"})
        ledger = load_json(self.path / "candidate-handoffs.json")
        ledger["batches"][0]["reason"] = "Changed after review"
        atomic_write_json(self.path / "candidate-handoffs.json", ledger)
        with self.assertRaisesRegex(ValueError, "HISTORY_CHANGED"):
            load_ledger(self.path, self.task)

    def test_partial_scope_handoff_then_second_scope_and_source_only_duplicate(self):
        record_batch(self.path, {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("US")], "reviewer": "agent", "reason": "US scope ready"})
        view = project(self.task, self.evidence, self.candidates, self.path)
        self.assertEqual(view["rows"][0]["remaining_scopes"],
                         [{"scenario_id": "S-1", "jurisdiction": "GB"}])
        self.assertEqual(len(work_entries(self.task, self.evidence, self.candidates, self.path)), 1)
        record_batch(self.path, {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("GB")], "reviewer": "agent", "reason": "GB scope ready"})
        self.evidence["collections"]["patents"].append({"evidence_id": "EV-DUP"})
        self.candidates["patents"][0]["sources"].append(
            {"evidence_id": "EV-DUP", "source_anchor": "SRC-DUP"})
        self.save()
        self.assertEqual(project(self.task, self.evidence, self.candidates, self.path)
                         ["rows"][0]["handoff_state"], "current")
        self.candidates["patents"][0]["title"] = "Materially changed"
        self.save()
        self.assertEqual(project(self.task, self.evidence, self.candidates, self.path)
                         ["rows"][0]["handoff_state"], "ready")

    def test_other_unparsed_run_does_not_block_ready_batch_or_complete_materials(self):
        raw = b'{"results":[{"title":"unparsed one"},{"title":"unparsed two"}]}'
        raw_path = self.path / "raw" / "pending.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(raw)
        digest = sha256_bytes(raw)
        index = make_index({"result_processing_revision": "source-result-processing-v1"},
            provider="fixture", evidence_type="patent", status="success",
            submission_state="submitted", raw_body=raw, raw_suffix="json",
            normalized={"candidates": []}, coverage={}, payload_digest=digest)
        self.evidence["source_runs"].append({"run_id": "RUN-PENDING", "provider": "fixture",
            "evidence_type": "patent", "status": "success", "submission_state": "submitted",
            "payload_digest": digest, "raw_paths": [str(raw_path)],
            "result_processing": index})
        self.save()
        state = project(self.task, self.evidence, self.candidates, self.path)
        self.assertFalse(state["material_processing_complete"])
        self.assertEqual(state["unfinished_source_run_ids"], ["RUN-PENDING"])
        self.assertEqual(state["rows"][0]["handoff_state"], "ready")
        record_batch(self.path, {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("US"), self.review("GB")],
            "reviewer": "agent", "reason": "Ready candidate proceeds while other run is pending"})
        after = project(self.task, self.evidence, self.candidates, self.path)
        self.assertTrue(after["candidate_handoff_complete"])
        self.assertFalse(after["material_processing_complete"])

    def test_one_reviewed_source_run_supports_two_scope_reviews_once(self):
        raw = b'{"results":[{"publication_number":"US11111111B2"}]}'
        raw_path = self.path / "raw" / "one.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(raw)
        digest = sha256_bytes(raw)
        index = make_index({"result_processing_revision": "source-result-processing-v1"},
            provider="fixture", evidence_type="patent", status="success",
            submission_state="submitted", raw_body=raw, raw_suffix="json",
            normalized={"candidates": [{"publication_number": "US11111111B2", "source_position": 1}]},
            coverage={}, payload_digest=digest)
        run = {"run_id": "RUN-ONE", "provider": "fixture", "evidence_type": "patent",
               "status": "success", "submission_state": "submitted", "payload_digest": digest,
               "raw_paths": [str(raw_path)], "result_processing": index}
        self.evidence["source_runs"].append(run)
        self.evidence["collections"]["patents"] = [{"evidence_id": "EV-RUN",
            "source_run_id": "RUN-ONE", "payload": {"candidates": [
                {"publication_number": "US11111111B2", "source_position": 1}]}}]
        self.evidence["result_dispositions"] = [{"source_run_id": "RUN-ONE",
            "position": 1, "raw_sha256": index["rows"][0]["raw_sha256"],
            "payload_digest": digest, "outcome": "candidate", "candidate_ids": ["C-1"],
            "reviewer": "agent", "reason": "Confirmed source row"}]
        self.candidates["patents"][0]["sources"] = [{"evidence_id": "EV-RUN",
            "source_run_id": "RUN-ONE", "source_position": 1, "source_anchor": "SRC-RUN"}]
        self.save()
        self.assertTrue(project(self.task, self.evidence, self.candidates, self.path)
                        ["material_processing_complete"])
        event = record_batch(self.path, {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("US", evidence_id="EV-RUN"),
                              self.review("GB", evidence_id="EV-RUN")],
            "reviewer": "agent", "reason": "One real execution; applicability checked separately"})
        self.assertEqual(len({ref["source_run_id"] for ref in event["candidates"][0]["ready_sources"]}), 1)
        self.assertEqual(len(self.evidence["source_runs"]), 1)

    def test_invalid_scope_or_unknown_evidence_rolls_back_whole_batch(self):
        with self.assertRaisesRegex(ValueError, "SCOPE_REVIEW_INVALID"):
            record_batch(self.path, {"candidate_ids": ["C-1"],
                "scope_reviews": [self.review("US"), self.review("GB", evidence_id="EV-NO")],
                "reviewer": "agent", "reason": "Invalid second scope"})
        self.assertFalse((self.path / "candidate-handoffs.json").exists())

    def test_missing_candidate_source_stays_in_unified_work_and_blocks_material_complete(self):
        self.candidates["patents"][0]["sources"] = [{"evidence_id": "EV-MISSING"}]
        self.save()
        view = project(self.task, self.evidence, self.candidates, self.path)
        self.assertEqual(view["rows"][0]["handoff_state"], "source_pending")
        self.assertFalse(view["material_processing_complete"])
        self.assertEqual(work_entries(self.task, self.evidence, self.candidates, self.path)
                         [0]["reason"], "CANDIDATE_HANDOFF_SOURCE_PENDING")

    def test_historical_entry_keeps_original_source_time_separate_from_retention_check(self):
        self.evidence["collections"]["patents"][0].update(
            kind="historical_source_reuse", source_checked_at="2023-01-01T00:00:00Z",
            checked_at="2026-09-24T00:00:00Z")
        self.save()
        source = project(self.task, self.evidence, self.candidates, self.path)
        source = source["rows"][0]["ready_sources"][0]
        self.assertEqual(source["original_collected_at"], "2023-01-01T00:00:00Z")
        self.assertEqual(source["retention_checked_at"], "2026-09-24T00:00:00Z")

    def test_05a_unknown_origin_handoff_is_unlocated_not_all_target_countries(self):
        self.task.update(triage_scope_revision="candidate-triage-scope-v1",
                         workflow_correction_revision="workflow-correction-v1",
                         decision_workflow_revision="scenario-triage-v1")
        self.candidates["patents"][0]["jurisdiction"] = "unknown"
        self.save()
        row = project(self.task, self.evidence, self.candidates, self.path)["rows"][0]
        self.assertEqual(row["remaining_scopes"], [{"scenario_id": "S-1",
                                                    "jurisdiction": "UNLOCATED"}])
        event = record_batch(self.path, {"candidate_ids": ["C-1"],
            "scope_reviews": [self.review("UNLOCATED", applicability="unknown")],
            "reviewer": "agent", "reason": "Original material reviewed; target country unresolved"})
        self.assertEqual(event["scope_reviews"][0]["jurisdiction"], "UNLOCATED")


if __name__ == "__main__":
    unittest.main()
