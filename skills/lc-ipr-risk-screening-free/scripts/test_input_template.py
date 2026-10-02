"""input_template.py prefills derivable fields and leaves every judgment null (recorders reject nulls)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from unittest.mock import patch

from common import atomic_write_json, load_json
from record_discovery_semantics import record_batch
import input_template as it
import test_discovery_semantics as fixtures
import test_source_result_processing as result_fixtures
import test_triage_scope as triage_fixtures
import test_candidate_handoff as handoff_fixtures
import test_recovery_stage_b as recovery_fixtures


class InputTemplateTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.DiscoverySemanticsTests("test_two_checks_gate_dispatch_and_complete_direction")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.run_dir = self.h.f.run
        import discovery_semantics as ds
        def view(*_a, **_k):
            task = load_json(self.run_dir / "task.json")
            plan = load_json(self.run_dir / "search-plan.json") if (self.run_dir / "search-plan.json").is_file() else self.h.plan
            entries = ds.work_entries(task, plan, load_json(self.run_dir / "evidence.json"))
            return {"entries": [{**e, "work_id": "WORK-" + str(i)} for i, e in enumerate(entries)]}
        patcher = patch("workflow_v24.work_view_from_dir", side_effect=view)
        patcher.start()
        self.addCleanup(patcher.stop)

    def design_event(self, stage, files):
        return next(e for e in files["discovery-" + stage + ".json"]["events"] if e["right_type"] == "design")

    def test_direction_template_lists_exact_inventory_and_is_rejected_until_filled(self):
        files, summaries, skipped = it.build(self.run_dir)
        event = self.design_event("direction", files)
        self.assertEqual(skipped, [])
        self.assertIn("reviewer", next(s for s in summaries if s["file"] == "discovery-direction.json")["fill"])
        self.assertIn("clues.[].disposition", next(s for s in summaries if s["file"] == "discovery-direction.json")["fill"])
        with self.assertRaises((ValueError, KeyError, TypeError)):
            record_batch(self.run_dir, [event])                     # nulls are never accepted
        self.assertEqual(load_json(self.run_dir / "task.json").get("discovery_semantic_reviews", []), [])
        event.update(reviewer="agent", reason="Checked the scoped facts and design direction.")
        for clue in event["clues"]:
            clue.update(disposition="included", reason="Visible product outline matters.")
        for direction in event["directions"]:
            direction.update(question="Which protected shapes resemble this stand?", method="Shape and use search",
                             proposed_sources=["uspto_patent_browser"], evidence_needed="Reviewed design result set",
                             supplement_trigger="Shape variants or truncated results")
        [saved] = record_batch(self.run_dir, [event])
        self.assertEqual(saved["stage"], "direction")

    def test_before_and_after_templates_carry_query_direction_and_run_ids(self):
        h = self.h
        event = self.design_event("direction", it.build(self.run_dir)[0])
        event.update(reviewer="agent", reason="Checked the scoped facts and design direction.")
        for clue in event["clues"]:
            clue.update(disposition="included", reason="Visible product outline matters.")
        for direction in event["directions"]:
            direction.update(question="q", method="m", proposed_sources=["uspto_patent_browser"],
                             evidence_needed="e", supplement_trigger="s")
        record_batch(self.run_dir, [event])
        files, summaries, _ = it.build(self.run_dir, [w for s in it.build(self.run_dir)[1] for w in s["work_ids"]])
        before = next(e for e in files["discovery-before.json"]["events"] if e["query_id"] == h.row["query_id"])
        self.assertEqual((before["direction_id"], before["stage"]), ("outline", "before"))
        guide = next(s for s in summaries if s["file"] == "discovery-before.json")["guide"]
        self.assertTrue(any(g["actual_query_to_review"] == h.row.get("q") for g in guide))
        with self.assertRaises((ValueError, KeyError, TypeError)):
            record_batch(self.run_dir, [before])
        before.update(reviewer="agent", reason="Checked the actual planned expression.", semantic_fit="full",
                      expression_reason="Folding stand describes the visible overall shape.",
                      concepts_in_query=["folding stand"], uncovered_clues=[], independent_structure=False,
                      whole_product_constraint=False)
        record_batch(self.run_dir, [before])
        h.source()
        files, summaries, _ = it.build(self.run_dir)
        after = next(e for e in files["discovery-after.json"]["events"] if e["query_id"] == h.row["query_id"])
        self.assertEqual(after["source_run_id"], "RUN-SEMANTIC")
        self.assertIn("EV-SEMANTIC", next(s for s in summaries if s["file"] == "discovery-after.json")["guide"][0]["evidence_ids_of_this_run"])
        after.update(evidence_refs=["EV-SEMANTIC"], reviewer="agent", reason="Reviewed the returned set.",
                     original_problem_checked=True, problem_covered=True, result_reason="Addresses the shape.",
                     uncovered_clues=[], excluded_by_narrowing=[], next_action="none")
        record_batch(self.run_dir, [after])
        self.assertEqual([e["stage"] for e in load_json(self.run_dir / "task.json")["discovery_semantic_reviews"]],
                         ["direction", "before", "after"])

    def test_unknown_or_unsupported_work_ids_are_reported_not_guessed(self):
        with self.assertRaisesRegex(ValueError, "NOT_CURRENT"):
            it.build(self.run_dir, ["WORK-does-not-exist"])

    def test_cli_writes_a_new_directory_and_never_overwrites(self):
        out = self.run_dir.parent / "templates-out"
        script = str(Path(__file__).resolve().parent / "input_template.py")
        done = subprocess.run([sys.executable, script, "--task-dir", str(self.run_dir), "--output-dir", str(out)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertTrue((out / "discovery-direction.json").is_file())
        self.assertIn("record_discovery_semantics.py", report["written"][0]["command"])
        again = subprocess.run([sys.executable, script, "--task-dir", str(self.run_dir), "--output-dir", str(out)],
                               capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(again.returncode, 0)


class ResultProcessingTemplateTests(unittest.TestCase):
    def setUp(self):
        self.h = result_fixtures.ResultProcessingTests("test_parse_and_disposition_batch_writes_once_and_repeats_without_write")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.root = self.h.root

    def entry(self, **changes):
        from source_result_processing import work_entries
        task = load_json(self.root / "task.json")
        entry = work_entries(task, load_json(self.root / "evidence.json"), self.root)[0]
        return {**entry, "work_id": "WORK-R", **changes}

    def test_template_lists_every_parsed_pending_position_and_records_once_filled(self):
        from source_result_processing import append_processing_batch, progress
        run, evidence, cards, _ = self.h.setup_run(count=3, parsed=3)
        event, guide = it.result_processing_event(self.root, evidence, {}, self.entry())
        self.assertEqual([d["position"] for d in event["decisions"]], [1, 2, 3])
        self.assertEqual(guide["outcome"], ["candidate", "duplicate_source", "non_candidate"])
        with self.assertRaises(ValueError):
            append_processing_batch(self.root, [event])              # nulls are rejected, nothing recorded
        self.assertNotIn("result_dispositions", load_json(self.root / "evidence.json"))
        for decision in event["decisions"]:
            decision.update(outcome="non_candidate", reviewer="agent", reason="Read the retained row; unrelated.")
        append_processing_batch(self.root, [event])
        state = progress(self.root, run, load_json(self.root / "evidence.json"))
        self.assertTrue(state["material_processing_complete"])

    def test_unparsed_positions_are_left_out_and_reported(self):
        run, evidence, cards, _ = self.h.setup_run(count=4, parsed=2)
        event, guide = it.result_processing_event(self.root, evidence, {}, self.entry())
        self.assertEqual([d["position"] for d in event["decisions"]], [1, 2])
        self.assertEqual(guide["unparsed_positions_need_parsed_rows_first"], [3, 4])
        entry = {**self.entry(), "pending_positions": [3, 4], "pending_parse_positions": [3, 4]}
        self.assertEqual(it.result_processing_event(self.root, evidence, {}, entry)[0], None)

    def test_candidate_bindings_are_offered_per_position(self):
        run, evidence, cards, _ = self.h.setup_run(count=2, parsed=2)
        candidates = {"patents": [{"candidate_id": "C-1", "sources": [{"source_run_id": "RUN-1", "source_position": 2}]},
                                  {"candidate_id": "C-2", "sources": [{"source_run_id": "OTHER", "source_position": 1}]}]}
        _event, guide = it.result_processing_event(self.root, evidence, candidates, self.entry())
        self.assertEqual(guide["bound_candidates_by_position"], {"2": ["C-1"]})


class TriageTemplateTests(unittest.TestCase):
    def setUp(self):
        self.h = triage_fixtures.TriageScopeTests("test_unknown_country_has_one_unlocated_triage_and_selected_waits_for_identity")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def entry(self):
        return {"work_id": "W", "kind": "triage", "candidate_id": self.h.candidate["candidate_id"],
                "scenario_id": "product_entry", "jurisdiction": str(self.h.candidate["jurisdiction"]).upper(),
                "right_type": "patent", "reason": "CANDIDATE_TRIAGE_REQUIRED"}

    def test_template_is_supported_rejected_until_filled_and_accepted_once_filled(self):
        import decision_workflow as workflow
        self.assertTrue(it.supported(self.entry()))
        self.assertFalse(it.supported({**self.entry(), "kind": "source_lookup", "reason": "OTHER"}))
        template, guide = it.triage_decision(self.h.task, self.h.candidates, self.entry())
        self.assertEqual(template["candidate_relation"]["identity_gaps"], [])
        self.assertIn("strap", guide["included_product_objects"])
        request = {**template, "annotation_id": "D-T-1", "annotated_at": "2026-09-24T00:00:00Z"}
        with self.assertRaises(ValueError):
            workflow.make_annotation(self.h.task, "patents", self.h.candidate, request, evidence=self.h.evidence)
        request.update(decision="selected", reason="Read and compared the retained material", reviewer="agent",
                       reading_level="result_record", basis_summary="Concrete product-to-candidate comparison",
                       evidence_refs=["E1"], reopen_conditions=["New protection content or product scope"])
        request["candidate_relation"].update(product_object_ids=["strap"], direction_ids=["strap-structure"],
                                             scope_reason="Read source E1 and mapped the strap object", evidence_refs=["E1"])
        request["comparison"].update(candidate_content="Retained record describes a strap and hook",
                                     product_content="The scoped product has a strap and hook",
                                     relationship="The retained structure maps to the included strap",
                                     investigation_question="Could the protected strap structure affect this product?")
        row = workflow.make_annotation(self.h.task, "patents", self.h.candidate, request, evidence=self.h.evidence)
        self.assertEqual(row["decision"], "selected")

    def test_identity_gaps_are_prefilled_with_a_location_scaffold(self):
        self.h.candidate["jurisdiction"] = "unknown"
        entry = {**self.entry(), "jurisdiction": "UNLOCATED"}
        template, guide = it.triage_decision(self.h.task, self.h.candidates, entry)
        self.assertIn("target_jurisdiction", template["candidate_relation"]["identity_gaps"])
        self.assertEqual(template["candidate_relation"]["identity_location"],
                         {"reason": None, "affected_work": None, "next_action": None})
        self.assertEqual(it.triage_decision(self.h.task, self.h.candidates, {**entry, "candidate_id": "NOPE"})[1],
                         "CANDIDATE_UNKNOWN")


class HandoffTemplateTests(unittest.TestCase):
    def setUp(self):
        self.h = handoff_fixtures.CandidateHandoffTests("test_same_source_can_handoff_two_scopes_in_one_batch_without_new_run")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def entries(self):
        from candidate_handoff import work_entries
        return [{**e, "work_id": "WORK-H"} for e in work_entries(self.h.task, self.h.evidence, self.h.candidates, self.h.path)]

    def test_batch_template_lists_every_open_scope_and_records_once_filled(self):
        from candidate_handoff import project, record_batch
        [entry] = self.entries()
        item, guide = it.handoff_item(entry)
        self.assertEqual([(r["scenario_id"], r["jurisdiction"]) for r in item["scope_reviews"]], [("S-1", "GB"), ("S-1", "US")])
        self.assertEqual(guide["ready_evidence_ids"], ["EV-IMPORT"])
        request = {"candidate_ids": ["C-1"], "scope_reviews": item["scope_reviews"], "reviewer": None, "reason": None}
        with self.assertRaises(ValueError):
            record_batch(self.h.path, request)
        for review in request["scope_reviews"]:
            review.update(applicability="applicable", reason="Retained source applies to this scope", evidence_refs=["EV-IMPORT"])
        request.update(reviewer="agent", reason="Scopes reviewed against the retained source")
        record_batch(self.h.path, request)
        self.assertEqual(project(self.h.task, self.h.evidence, self.h.candidates, self.h.path)["rows"][0]["handoff_state"], "current")

    def test_build_writes_one_batch_file_for_all_ready_candidates(self):
        from unittest.mock import patch
        entries = self.entries()
        with patch("workflow_v24.work_view_from_dir", return_value={"entries": entries}):
            files, summaries, skipped = it.build(self.h.path)
        batch = files["candidate-handoff.json"]
        self.assertEqual(batch["candidate_ids"], ["C-1"])
        self.assertIsNone(batch["reviewer"])
        self.assertEqual(summaries[0]["fill"], ["reason", "reviewer", "scope_reviews.[].applicability",
                                                "scope_reviews.[].evidence_refs", "scope_reviews.[].reason"])
        self.assertEqual(summaries[0]["guide"]["applicability"], ["applicable", "not_applicable", "unknown"])


class RecoveryTemplateTests(unittest.TestCase):
    def setUp(self):
        self.h = recovery_fixtures.RecoveryStageBTests("test_legacy_is_unchanged_and_identity_ignores_action_name")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def entry(self, reason, *runs):
        from common import sha256_json
        return {"work_id": "WORK-V", "kind": "source_lookup", "reason": reason,
                "recovery": {"source_run_refs": [{"run_id": r["run_id"], "sha256": sha256_json(r)} for r in runs]}}

    def test_failure_review_template_is_bound_to_the_exact_run_and_recordable_once_filled(self):
        from recovery_stage_b import record_review
        run = self.h.add_run("R1")
        found, guide, error = it.recovery_request(self.h.task, self.h.evidence,
                                                  self.entry("SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED", run))
        self.assertIsNone(error)
        request = found["request"]
        self.assertEqual((request["kind"], request["source_run_id"]), ("failure_review", "R1"))
        self.assertEqual(request["failure_cause"], "TIMEOUT: request failed")
        self.assertIn("receipt_absence_reason", request)
        with self.assertRaises(ValueError):
            record_review(self.h.path, request)                       # nulls are rejected
        request.update(reviewer="Reviewer", reasoning="Original request and failure checked",
                       receipt_review="original receipt checked", receipt_absence_reason="no retained body",
                       material_review="no valid material", remaining_work="same target",
                       repair_basis="source status recovered", source_rule_ref="confirmed source policy",
                       source_allows_retry=True)
        self.assertTrue(record_review(self.h.path, request)["review_id"].startswith("REC-REV-"))

    def test_pre_submission_repair_and_unknown_check_templates(self):
        from recovery_stage_b import record_review
        pre = self.h.add_run("R-PRE", status="failed", submission="not_submitted")
        found, _g, _e = it.recovery_request(self.h.task, self.h.evidence, self.entry("PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED", pre))
        request = found["request"]
        self.assertEqual(request["kind"], "pre_submission_repair")
        with self.assertRaises(ValueError):
            record_review(self.h.path, request)
        request.update(reviewer="R", reasoning="checked", failure_cause="invalid input", repair_basis="corrected",
                       condition_check="revalidated", receipt_review="guard receipt checked")
        record_review(self.h.path, request)
        unknown = self.h.add_run("R-UNK", status="failed", submission="unknown")
        found, guide, _e = it.recovery_request(self.h.task, self.h.evidence, self.entry("VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY", unknown))
        request = found["request"]
        self.assertEqual((request["kind"], request["outcome"]), ("unknown_check", None))
        self.assertIn("still_unknown", guide["outcome"])
        with self.assertRaises(ValueError):
            record_review(self.h.path, request)
        request.update(reviewer="R", reasoning="checked", outcome="still_unknown", original_receipt_review="timeout receipt",
                       basis="saved status", check_method="existing_receipt", disposition="continue_check")
        record_review(self.h.path, request)

    def test_new_operator_policy_gets_a_failure_closeout_wrapper_and_no_run_is_reported(self):
        run = self.h.add_run("R2", raw_paths=["raw/x.json"])
        task = {**self.h.task, "retrieval_workflow_revision": "api-first-v3", "assessment_revision": "known-findings-risk-v1",
                "presentation_policy_revision": "operator-report-v1"}
        found, guide, _e = it.recovery_request(task, self.h.evidence, self.entry("SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED", run))
        request = found["request"]
        self.assertEqual(request["kind"], "failure_closeout")
        self.assertEqual(request["receipt_disposition"], {"outcome": None})
        self.assertNotIn("receipt_absence_reason", request["failure_review"])
        self.assertIn("closeout", guide)
        self.assertEqual(it.recovery_request(task, self.h.evidence, self.entry("PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED", run))[2],
                         "NO_MATCHING_RUN")
        self.assertEqual(found["name"], "recovery-R2.json")


class PureTemplateTests(unittest.TestCase):
    def test_null_paths_collapse_list_rows_and_source_operation_template_shape(self):
        paths = it._null_paths({"a": None, "rows": [{"x": None, "y": 1}, {"x": None}], "n": {"z": None}})
        self.assertEqual(paths, ["a", "n.z", "rows.[].x"])

    def test_progress_and_operation_templates(self):
        plan = {"queries": {"epo_ops": [{"query_id": "Q1", "jurisdiction": "US", "right_type": "patent", "operation": "search"}]}}
        task = {"product_change_version": "V1", "product_scope": {"product_version": "V1"}}
        import review_progress_stage_a as rp
        entry = {"scenario_id": "S", "query_id": "Q1"}
        item, error = it.progress_item({**task}, plan, entry) if hasattr(rp, "_version") else (None, None)
        self.assertIsNone(error)
        self.assertEqual((item["kind"], item["query_id"], item["module_ids"], item["acceptance_condition"]),
                         ("query", "Q1", None, None))
        self.assertTrue(item["item_id"].startswith("ITEM-"))
        self.assertEqual(it.progress_item(task, plan, {"scenario_id": "S", "query_id": "Q9"})[1], "QUERY_UNKNOWN")
        run = {"run_id": "R1", "query_id": "Q1", "provider": "epo_ops"}
        from unittest.mock import patch
        with patch("source_operation._runs", return_value=[run]):
            template, guide = it.operation_template({}, plan, {}, {"query_id": "Q1"})
        self.assertEqual(template["source_run_id"], "R1")
        self.assertIsNone(template["decision"])
        self.assertIsNone(template["checks"]["request_response_binding"])
        self.assertEqual(guide["decision"], ["accepted", "rejected", "unvalidated"])


if __name__ == "__main__":
    unittest.main()
