"""Regression contracts for the dispatcher/publication optimization round.

Batching, digest normalization, compact output, failure limits, structured
conflicts and the adjudication helper must not change any recorded fact.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, print_recorded, sha256_file, sha256_json, summarize_recorded
from continuous_progress_stage_d import (REVISION, record_event, record_events,
                                         recover_interrupted_rounds, status)


class Fixture(unittest.TestCase):
    def make_task(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)
        atomic_write_json(path / "task.json", {"task_id": "T", "continuous_progress_revision": REVISION})
        atomic_write_json(path / "evidence.json", {"task_id": "T", "source_runs": [], "other_facts": []})
        return path

    rows = [
        {"work_id": "W1", "issue_id": "I1", "linked_action_id": "ACTION-1", "kind": "source_lookup",
         "state": "ready", "query_id": "Q1", "provider": "epo_ops", "reason": "SOURCE_PENDING"},
        {"work_id": "W2", "issue_id": "I2", "linked_action_id": "ACTION-2", "kind": "source_lookup",
         "state": "ready", "query_id": "Q2", "provider": "epo_ops", "reason": "SOURCE_PENDING"},
    ]

    def view(self, *_a, **_k):
        self.view_calls = getattr(self, "view_calls", 0) + 1
        return {"entries": [dict(row) for row in self.rows], "status": "incomplete"}

    def request(self, kind, **fields):
        return {"kind": kind, "actor": "advance_work", "reasoning": "test", **fields}

    @staticmethod
    def facts(path):
        return [(e["kind"], e["action_id"], e.get("work_id"), e.get("effective_progress"), e.get("outcome"))
                for e in load_json(path / "evidence.json").get("progress_events", [])]


class ProgressBatchTests(Fixture):
    def test_batched_begin_and_finish_equal_sequential_events(self):
        sequential, batched = self.make_task(), self.make_task()
        with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
            begins = [record_event(sequential, self.request("begin", work_id=w)) for w in ("W1", "W2")]
            for begin in begins:
                record_event(sequential, self.request("finish", begin_id=begin["event_id"], action_taken="dispatch"))
            self.view_calls = 0
            batch = record_events(batched, [self.request("begin", work_id=w) for w in ("W1", "W2")])
            self.assertEqual(self.view_calls, 1)
            self.view_calls = 0
            record_events(batched, [self.request("finish", begin_id=b["event_id"], action_taken="dispatch") for b in batch])
            self.assertEqual(self.view_calls, 1)
        self.assertEqual(self.facts(sequential), self.facts(batched))
        self.assertEqual(status(load_json(batched / "evidence.json"), "ACTION-1")["rounds"], 1)

    def test_batch_rejects_mixed_kinds_and_keeps_accepted_prefix(self):
        path = self.make_task()
        with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
            with self.assertRaisesRegex(ValueError, "BATCH_KIND"):
                record_events(path, [self.request("begin", work_id="W1"), self.request("finish", begin_id="x")])
            with self.assertRaisesRegex(ValueError, "ACTIONABLE"):
                record_events(path, [self.request("begin", work_id="W1"), self.request("begin", work_id="W1")])
        self.assertEqual([f[:2] for f in self.facts(path)], [("begin", "ACTION-1")])

    def test_interrupted_dispatch_round_is_closed_and_next_begin_works(self):
        path = self.make_task()
        with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
            record_event(path, self.request("begin", work_id="W1"))
            with self.assertRaisesRegex(ValueError, "ACTIONABLE"):
                record_event(path, self.request("begin", work_id="W1"))
            closed = recover_interrupted_rounds(path, "advance_work")
            self.assertEqual([e["action_taken"] for e in closed], ["interrupted_dispatch_recovered"])
            self.assertEqual(recover_interrupted_rounds(path, "advance_work"), [])
            record_event(path, self.request("begin", work_id="W1"))

    def test_second_repair_after_failed_repair_round_requires_technical_stop(self):
        path = self.make_task()
        def round_():
            with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
                begin = record_event(path, self.request("begin", work_id="W1"))
                record_event(path, self.request("finish", begin_id=begin["event_id"], action_taken="dispatch"))
        round_(); round_()
        checks = {k: "checked " + k for k in ("command", "receipt", "retained_files", "adapter", "submission")}
        record_event(path, self.request("diagnosis", action_id="ACTION-1", checks=checks))
        for name in ("one", "two"):
            fix = path / (name + ".txt")
            fix.write_text(name, encoding="utf-8")
            ref = {"path": str(fix), "sha256": sha256_file(fix)}
            if name == "one":
                record_event(path, self.request("repair", action_id="ACTION-1", evidence_ref=ref))
                round_()
            else:
                with self.assertRaisesRegex(ValueError, "TECHNICAL_STOP_REQUIRED_AFTER_FAILED_REPAIR"):
                    record_event(path, self.request("repair", action_id="ACTION-1", evidence_ref=ref))
        record_event(path, self.request("technical_stop", action_id="ACTION-1", recovery_condition="new evidence"))


class DispatcherProjectionTests(Fixture):
    def test_plan_repair_awaiting_review_is_a_repair_card_not_an_error(self):
        from advance_work import actionable_packet, action_card
        entry = {"work_id": "W", "kind": "plan_repair", "state": "awaiting_review",
                 "reason": "PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED", "linked_action_id": "ACTION-9"}
        packet = actionable_packet({"entries": [entry]})
        self.assertEqual(packet["repair"], [entry])
        self.assertEqual(action_card(Path("/tmp/t"), entry)["action"], "diagnose_and_repair_original_action")

    def test_supported_review_cards_name_the_template_tool_and_others_do_not(self):
        from advance_work import action_card
        supported = action_card(Path("/tmp/t"), {"kind": "agent_investigation", "reason": "DISCOVERY_DIRECTION_REVIEW_REQUIRED",
                                                 "work_id": "WORK-1"})
        self.assertTrue(supported["input_template"]["tool"].endswith("input_template.py"))
        self.assertEqual(supported["input_template"]["args"][:4], ["--task-dir", "/tmp/t", "--work-id", "WORK-1"])
        triage = action_card(Path("/tmp/t"), {"kind": "triage", "reason": "CANDIDATE_TRIAGE_REQUIRED", "work_id": "WORK-3",
                                              "candidate_id": "C1"})
        self.assertIn("input_template", triage)
        other = action_card(Path("/tmp/t"), {"kind": "agent_read", "reason": "SOMETHING_ELSE", "work_id": "WORK-2"})
        self.assertNotIn("input_template", other)

    def test_progress_digest_ignores_bookkeeping_and_wall_clock_but_not_facts(self):
        from advance_work import progress_digest
        path = self.make_task()
        atomic_write_json(path / "browser-execution-status.json", {"queries": [], "observed_at": "t1", "elapsed_ms": 5})
        base = progress_digest(path)
        with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
            begin = record_event(path, self.request("begin", work_id="W1"))
            record_event(path, self.request("finish", begin_id=begin["event_id"], action_taken="dispatch"))
        atomic_write_json(path / "browser-execution-status.json", {"queries": [], "observed_at": "t2", "elapsed_ms": 9})
        self.assertEqual(progress_digest(path), base)
        evidence = load_json(path / "evidence.json")
        evidence["source_runs"].append({"run_id": "R1", "query_id": "Q1", "status": "success"})
        atomic_write_json(path / "evidence.json", evidence)
        self.assertNotEqual(progress_digest(path), base)


class DeliveryBindingTests(Fixture):
    def dispatcher_run(self, publication, *extra):
        """Run advance_work.main up to and including --publish with everything heavy mocked."""
        import advance_work
        path = self.make_task()
        atomic_write_json(path / "task.json", {"task_id": "T", "execution_policy_revision": "continuous-work-v2"})
        atomic_write_json(path / "search-plan.json", {"task_id": "T", "queries": {}})
        argv = ["advance_work.py", "--task-dir", str(path), "--publish", "--output-dir", str(path / "build"), *extra]
        printed = io.StringIO()
        view = {"entries": [], "status": "complete", "counts": {}}
        with patch("sys.argv", argv), patch("advance_work.work_view_from_dir", return_value=view), \
                patch("advance_work.workflow_stage", return_value="publication"), \
                patch("publish_report.publish", return_value=publication) as publish, redirect_stdout(printed):
            try:
                advance_work.main()
                code = 0
            except SystemExit as exc:
                code = exc.code
        return publish, json.loads(printed.getvalue().splitlines()[0]), code

    def test_deliver_to_is_passed_through_and_completion_stage_decides_the_exit(self):
        done = {"build_only": False, "delivery_status": "entry_verified",
                "completion": {"status": "complete", "stage": "complete"}}
        publish, output, code = self.dispatcher_run(done, "--deliver-to", "/tmp/entry", "--require-complete")
        self.assertEqual(publish.call_args.kwargs["deliver_to"], Path("/tmp/entry"))
        self.assertTrue(publish.call_args.kwargs["require_complete"])
        self.assertEqual((output["stage"], code), ("complete", 0))
        limited = {**done, "completion": {"status": "limited_round_closed", "stage": "limited_round_closed"}}
        self.assertEqual(self.dispatcher_run(limited, "--deliver-to", "/tmp/entry", "--require-complete")[1]["stage"],
                         "limited_round_closed")

    def test_without_deliver_to_a_build_is_not_complete(self):
        publish, output, code = self.dispatcher_run({"build_only": True}, "--require-complete")
        self.assertNotIn("deliver_to", publish.call_args.kwargs)
        self.assertEqual((output["stage"], code), ("delivery", 2))

    def test_successful_delivery_rebinds_the_stop_hook_to_the_entry(self):
        import publish_report
        source = self.make_task()
        with patch("delivery_versions_stage_e.enabled", return_value=True), \
             patch("publish_report._assert_review_pair_current"), \
             patch("delivery_validation.enabled", return_value=False), \
             patch("delivery_versions_stage_e.begin_build", return_value="DV-1"), \
             patch("publish_report._publish_local", return_value={}), \
             patch("delivery_versions_stage_e.finish_build", return_value={}), \
             patch("delivery_versions_stage_e.deliver", return_value={"delivery_status": "entry_verified", "entry": "/e/report.html"}), \
             patch("completion_check.check_completion", return_value={"status": "complete", "stage": "complete", "business_completion": "complete"}), \
             patch("codex_guard.update_bound_paths") as rebind:
            publication = publish_report.publish(source, "f.json", "s.json", output_dir=source / "build",
                                                 deliver_to=source / "entry", require_complete=True)
        rebind.assert_called_once_with(source.resolve(), output_dir=source / "entry")
        self.assertEqual(publication["report"], "/e/report.html")


class CompactOutputTests(unittest.TestCase):
    def test_recorder_echo_keeps_ids_and_states_but_drops_bodies(self):
        event = {"event_id": "E1", "kind": "begin", "reasoning": "x" * 500, "entry": {"work_id": "W", "big": "y" * 999},
                 "fact_snapshot": {"a": ["h"]}, "scope": {"jurisdiction": "US"}, "effective_progress": False}
        summary = summarize_recorded(event)
        self.assertEqual(summary, {"event_id": "E1", "kind": "begin", "scope": {"jurisdiction": "US"},
                                   "effective_progress": False})
        out = io.StringIO()
        with redirect_stdout(out):
            print_recorded({"events": [event, event]})
        self.assertNotIn("\n ", out.getvalue())
        self.assertEqual(len(json.loads(out.getvalue())["events"]), 2)
        out = io.StringIO()
        with redirect_stdout(out):
            print_recorded(event, verbose=True)
        self.assertEqual(json.loads(out.getvalue()), event)

    def test_api_batch_summary_lists_only_problem_rows(self):
        from run_api_plan import compact_batch_result
        result = {"task_id": "T", "status": "access_limited", "counts": {"executed": 2}, "workers": 3, "elapsed_ms": 9,
                  "results": [{"provider": "a", "query_id": "Q1", "status": "success", "dispatch": "executed"},
                              {"provider": "b", "query_id": "Q2", "status": "failed", "dispatch": "failed",
                               "error_code": "HTTP_500"}],
                  "agent_browser_queue": [{"query_id": "QB", "provider": "x"}], "work_view": {"huge": True}}
        summary = compact_batch_result(result, Path("/tmp/t"))
        self.assertEqual([row["query_id"] for row in summary["problem_rows"]], ["Q2"])
        self.assertNotIn("work_view", summary)
        self.assertEqual(summary["agent_browser_queue"], ["QB"])
        self.assertEqual(summary["result_rows"], 2)

    def test_dispatcher_compaction_helpers(self):
        from advance_work import _compact_per_work_progress, _compact_review_progress, _compact_stage_risk
        self.assertEqual(_compact_per_work_progress([{"action_id": "A", "consecutive_no_progress": 0},
                                                     {"action_id": "B", "consecutive_no_progress": 2}]),
                         [{"action_id": "B", "consecutive_no_progress": 2}])
        self.assertEqual(_compact_review_progress({"planned": 3, "items": [1], "history": [2], "by_scope": []}),
                         {"planned": 3, "by_scope": []})
        risk = _compact_stage_risk({"status": "s", "judgments": [{}, {}], "overall": {"stage_risk": "低", "junk": 1},
                                    "signals": [], "scopes_without_any_judgment": [1]})
        self.assertEqual(risk["judgment_count"], 2)
        self.assertEqual(risk["overall"], {"stage_risk": "低"})


class FailureLimitTests(Fixture):
    def test_policy_predicate_is_opt_in_and_validates_value(self):
        from completion_policy import failure_limits_enabled
        self.assertFalse(failure_limits_enabled({}))
        self.assertTrue(failure_limits_enabled({"limited_delivery_revision": "failure-limits-v1"}))
        with self.assertRaises(ValueError):
            failure_limits_enabled({"limited_delivery_revision": "other"})

    def test_technical_stop_needs_recorded_stop_event_and_recovery_condition(self):
        from necessary_completion import _failure_limit
        stop = {"kind": "technical_stop", "event_id": "P-1", "recovery_condition": "new adapter"}
        entry = {"work_id": "W", "state": "blocked", "reason": "TECHNICAL_EXECUTION_STOPPED",
                 "technical_stop_id": "P-1", "recovery_condition": "new adapter"}
        item = _failure_limit(entry, {"progress_events": [stop]})
        self.assertEqual(item["limitation_kind"], "internal_technical_failure")
        self.assertEqual(item["failure_records"][0]["sha256"], sha256_json(stop))
        self.assertEqual(item["official_verification"], "not_verified")
        self.assertIsNone(_failure_limit(entry, {"progress_events": []}))
        self.assertIsNone(_failure_limit({**entry, "recovery_condition": ""}, {"progress_events": [stop]}))
        self.assertIsNone(_failure_limit({**entry, "state": "ready"}, {"progress_events": [stop]}))

    def test_source_failure_limit_is_bound_to_exact_run_hashes(self):
        from necessary_completion import _failure_limit
        run = {"run_id": "R1", "status": "failed", "error_code": "HTTP_500"}
        entry = {"work_id": "W", "state": "blocked", "reason": "SOURCE_AUTOMATIC_RETRY_EXHAUSTED",
                 "recovery": {"source_run_refs": [{"run_id": "R1", "sha256": sha256_json(run)}]}}
        self.assertEqual(_failure_limit(entry, {"source_runs": [run]})["limitation_kind"], "source_retry_exhausted")
        self.assertIsNone(_failure_limit(entry, {"source_runs": [{**run, "status": "success"}]}))
        self.assertIsNone(_failure_limit({**entry, "recovery": {}}, {"source_runs": [run]}))
        waiting = {**entry, "state": "awaiting_access", "reason": "SOURCE_RETRY_DEPENDENCY_REQUIRED"}
        self.assertEqual(_failure_limit(waiting, {"source_runs": [run]})["limitation_kind"], "source_access_dependency")
        self.assertIsNone(_failure_limit({**entry, "reason": "SOMETHING_ELSE"}, {"source_runs": [run]}))

    def test_stop_stage_continues_to_review_only_with_the_revision(self):
        from completion_check import workflow_stage
        packet = {"source": [], "agent": [], "repair": [], "review": [], "waiting": []}
        kwargs = {"first_review": None, "second_review": None, "adjudication": None, "output_dir": None}
        view = {"technical_stops": [{"event_id": "S1"}]}
        path = self.make_task()
        self.assertEqual(workflow_stage(view, packet, task_dir=path, **kwargs), "investigation")
        atomic_write_json(path / "task.json", {"task_id": "T", "limited_delivery_revision": "failure-limits-v1"})
        self.assertEqual(workflow_stage(view, packet, task_dir=path, **kwargs), "independent_review")
        self.assertEqual(workflow_stage({"active_pauses": [{"pause_id": "P"}]}, packet, task_dir=path, **kwargs),
                         "investigation")

    def business(self, revision, limits):
        from business_status_stage_b import classify
        task = {"task_id": "T", "business_status_revision": "business-status-stage-b-v1",
                "assessment_revision": "known-findings-risk-v1", "presentation_policy_revision": "operator-report-v1",
                **({"limited_delivery_revision": revision} if revision else {})}
        stage = {"stage_risk": {"overall": {}, "judgments": []}, "progress": {}}
        stop = {"action_id": "ACTION-1", "event_id": "P-1", "recovery_condition": "c"}
        entry = {"work_id": "W", "kind": "source_lookup", "state": "blocked", "reason": "TECHNICAL_EXECUTION_STOPPED",
                 "technical_stop_id": "P-1", "scenario_id": "S", "jurisdiction": "US", "right_type": "patent"}
        view = {"entries": [entry], "technical_stops": [stop], "unresolved_scopes": []}
        limit = {**entry, "limitation_kind": "internal_technical_failure"} if limits else None
        assessment = {"status": "incomplete", "final_review": {"evidence_digest": "D"},
                      "publication": {"mode": "evidence", "evidence_digest": "D",
                                      "limitations": [limit] if limit else [],
                                      "remaining_work": [dict(entry)] if limit else []}}
        with patch("final_review.enabled", return_value=True), patch("final_review.completed", return_value=True):
            return classify(task, stage, view, assessment, limitation_validator=lambda _e: True)

    def test_business_status_closes_only_over_a_disclosed_stop_and_only_with_the_revision(self):
        self.assertNotEqual(self.business(None, True)["business_status"], "limited_round_closed")
        self.assertNotEqual(self.business("failure-limits-v1", False)["business_status"], "limited_round_closed")
        closed = self.business("failure-limits-v1", True)
        self.assertEqual(closed["business_status"], "limited_round_closed")
        self.assertNotIn("TECHNICAL_STOP_IS_NOT_LIMITATION_PROOF", closed["gaps"])
        self.assertFalse(closed["overall_business_complete"])


class StructuredConflictTests(unittest.TestCase):
    def rows(self):
        base = {"risk": "高", "right_state": "active", "evidence_confidence": "中", "module_id": "utility_patent",
                "comparison": {"implementations": [{"implementation_id": "I1", "description": "as sold",
                                                    "product_evidence_refs": ["E1"]}],
                               "claims": [{"implementation_id": "I1", "claim_id": "claim 1", "claim_type": "independent",
                                           "conclusion": "supports_risk", "evidence_refs": ["E1"],
                                           "elements": [{"claim_element": "a strap", "result": "supports_risk",
                                                         "claim_quote": "a strap", "product_feature": "strap",
                                                         "reasoning": "same", "evidence_refs": ["E1"]}]}]}}
        return base, deepcopy(base)

    def test_wording_differences_conflict_only_in_the_legacy_rule(self):
        from assessment_estimate import _row_conflicts
        left, right = self.rows()
        right["comparison"]["implementations"][0].update(implementation_id="IMPL-A", description="different words")
        right["comparison"]["claims"][0].update(implementation_id="IMPL-A", claim_id="1")
        right["comparison"]["claims"][0]["elements"][0].update(reasoning="other words", claim_quote="the strap",
                                                               product_feature="band", claim_element="strap element")
        legacy = {"decision_workflow_revision": "scenario-triage-v1"}
        structured = {**legacy, "review_conflict_revision": "structured-conflicts-v1"}
        self.assertTrue(_row_conflicts(left, right, legacy))
        self.assertEqual(_row_conflicts(left, right, structured), [])

    def test_outcome_differences_still_conflict(self):
        from assessment_estimate import _row_conflicts
        task = {"decision_workflow_revision": "scenario-triage-v1", "review_conflict_revision": "structured-conflicts-v1"}
        for path, value, expected in (
                (("risk",), "低", "risk"), (("right_state",), "expired", "right_state"),
                (("evidence_confidence",), "高", "evidence_confidence")):
            left, right = self.rows()
            right[path[0]] = value
            self.assertEqual(_row_conflicts(left, right, task), [expected])
        left, right = self.rows()
        right["comparison"]["claims"][0]["conclusion"] = "does_not_support_risk"
        self.assertEqual(_row_conflicts(left, right, task), ["comparison:claims"])
        left, right = self.rows()
        right["decisive_exclusion"] = {"reasoning": "expired", "evidence_refs": ["E2"]}
        self.assertEqual(_row_conflicts(left, right, task), ["decisive_exclusion"])
        with self.assertRaises(ValueError):
            _row_conflicts(left, right, {"review_conflict_revision": "unknown"})


class AdjudicationHelperTests(Fixture):
    def review(self, digest, rows, session):
        return {"reviewer": session, "review_context": {"session_id": session, "evidence_digest": digest},
                "assessments": rows}

    def test_skeleton_lists_only_units_needing_the_chief_and_leaves_decisions_empty(self):
        import prepare_adjudication as pa
        path = self.make_task()
        atomic_write_json(path / "task.json", {"task_id": "T", "review_conflict_revision": "structured-conflicts-v1",
                                               "decision_workflow_revision": "scenario-triage-v1"})
        agree = {"scenario_id": "S", "jurisdiction": "US", "right_type": "patent", "risk": "低", "evidence_confidence": "中",
                 "module_id": "utility_patent"}
        differ_a = {**agree, "jurisdiction": "DE", "risk": "高"}
        excepted = {**agree, "jurisdiction": "FR", "applicability_exception": {"kind": "territorial_effect", "reasoning": "r"}}
        first = self.review("D1", [agree, differ_a, excepted], "a")
        second = self.review("D1", [deepcopy(agree), {**differ_a, "risk": "低"}, deepcopy(excepted)], "b")
        atomic_write_json(path / "first-review.json", first)
        atomic_write_json(path / "second-review.json", second)
        with patch("review_readiness.current_digest", return_value="D1"):
            adjudication, sheet = pa.build(path, path / "first-review.json", path / "second-review.json", reviewer="", session_id="")
        self.assertEqual(sheet["units_total"], 3)
        self.assertEqual(sheet["units_requiring_decision"], 2)
        self.assertEqual({row["unit"]["jurisdiction"] for row in sheet["units"]}, {"DE", "FR"})
        self.assertEqual(sheet["conflict_field_counts"], {"risk": 1})
        expected_refs = {"first": sha256_json(first), "second": sha256_json(second)}
        self.assertEqual(adjudication["review_refs"], expected_refs)
        for decision in adjudication["decisions"]:
            self.assertEqual(decision["adjudication_reasoning"], "")
            self.assertEqual(decision["review_refs"], expected_refs)
        self.assertEqual((adjudication["reviewer"], adjudication["review_context"]["session_id"]), ("", ""))
        with patch("review_readiness.current_digest", return_value="D2"):
            with self.assertRaisesRegex(ValueError, "REVIEW_STALE"):
                pa.build(path, path / "first-review.json", path / "second-review.json")


class ReviewIsolationTests(unittest.TestCase):
    def test_backend_selection_never_downgrades_on_macos(self):
        import review_isolation as ri
        with patch("review_isolation.sys.platform", "linux"):
            self.assertEqual(ri.select_backend("auto"), ri.TOOL_FREE)
            with self.assertRaisesRegex(ValueError, "MACOS_SANDBOX_REQUIRED"):
                ri.select_backend("macos-sandbox")
        with patch("review_isolation.sys.platform", "darwin"), patch("review_isolation.macos_sandbox_available", return_value=False):
            with self.assertRaisesRegex(ValueError, "MACOS_SANDBOX_REQUIRED"):
                ri.select_backend("auto")
        with self.assertRaises(ValueError):
            ri.select_backend("bogus")

    def test_native_command_is_unchanged_on_macos_and_unwrapped_elsewhere(self):
        from report_review_host import native_review_command
        mac = native_review_command(Path("/bin/codex"), Path("/tmp/p.sb"), Path("/tmp/w"))
        self.assertEqual(mac[:4], ["/usr/bin/sandbox-exec", "-f", "/tmp/p.sb", "/bin/codex"])
        plain = native_review_command(Path("/bin/codex"), None, Path("/tmp/w"))
        self.assertEqual(plain[0], "/bin/codex")
        self.assertEqual(mac[4:], plain[1:])
        self.assertIn("gpt-6-astra", " ".join(plain))
        for feature in ("shell_tool", "plugins", "unbounded_connection_retries"):
            self.assertIn(feature, plain)

    def test_wrapper_scripts_are_rejected_off_macos(self):
        import review_isolation as ri
        with patch("review_isolation.sys.platform", "win32"):
            with self.assertRaisesRegex(ValueError, "wrapper"):
                ri.resolve_codex_binary(Path("C:/x/codex.cmd"), ri.TOOL_FREE)

    def test_tool_free_policy_round_trip_and_tamper_detection(self):
        import review_isolation as ri
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "ws"; workspace.mkdir()
            (workspace / "frozen-input.json").write_text("{}", encoding="utf-8")
            binary = root / "codex"; binary.write_bytes(b"#!/bin/sh\necho codex-test 1.0\n"); binary.chmod(0o755)
            policy_path = root / "isolation-policy.json"
            ri.write_policy(policy_path, binary, workspace, {}, image_names=[])
            audit = {"isolation_method": ri.METHOD_TOOL_FREE, "kernel_read_boundary": False, "controls": []}
            ri.validate_policy(policy_path, audit)
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            self.assertEqual(policy["codex_version"], "codex-test 1.0")
            self.assertFalse(policy["kernel_read_boundary"])
            for mutate in (lambda p: p.update(disabled_features=p["disabled_features"][:-1]),
                           lambda p: p.update(kernel_read_boundary=True)):
                broken = deepcopy(policy); mutate(broken)
                policy_path.write_text(json.dumps(broken), encoding="utf-8")
                with self.assertRaises(ValueError):
                    ri.validate_policy(policy_path, audit)
            with self.assertRaises(ValueError):
                ri.validate_policy(policy_path, {**audit, "controls": [{"x": 1}]})


if __name__ == "__main__":
    unittest.main()
