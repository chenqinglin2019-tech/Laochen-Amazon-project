"""09A plan arithmetic, identity, provenance and isolation contracts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from review_progress_stage_a import REVISION, _counts, dispatch_block, ledger, project, record_event


class ReviewProgressStageATest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.task = {"task_id": "T09A", "review_progress_revision": REVISION,
                     "product_change_version": "1", "target_jurisdictions": ["US", "GB"],
                     "assessment_scenarios": [{"scenario_id": "S1"}]}
        self.evidence = {"task_id": "T09A", "source_runs": [], "review_progress_events": [],
                         "product_scope_events": []}
        self.row = {"query_id": "Q1", "jurisdiction": "US", "right_type": "patent",
                    "scenario_id": "S1"}
        self.plan = {"queries": {"registry": [self.row]}}
        self.open_issues = [{"issue_id": "ISSUE-1", "identity_quality": "exact",
                             "scope": {"scenario_id": "S1", "jurisdiction": "US", "right_type": "patent"}}]
        self.entries = []
        self.save()

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "evidence.json", self.evidence)
        atomic_write_json(self.path / "search-plan.json", self.plan)

    def view(self, *_args, **_kwargs):
        return {"status": "incomplete", "entries": self.entries,
                "continuous_work": {"issues": self.open_issues}}

    def event(self, kind, **fields):
        self.save()
        with patch("workflow_v24.work_view_from_dir", side_effect=self.view):
            result = record_event(self.path, {"kind": kind, "actor": "reviewer",
                "reasoning": "verified scope and original evidence", **fields})
        self.evidence = load_json(self.path / "evidence.json")
        return result

    def item(self, number, kind="issue", country="US", modules=None):
        row = {"item_id": f"ITEM-{number}", "kind": kind,
               "scope": {"scenario_id": "S1", "jurisdiction": country,
                         "right_type": "patent", "product_version": "1"},
               "module_ids": modules or ["M03"], "acceptance_condition": "original fact reviewed"}
        row["issue_id" if kind == "issue" else "query_id"] = "ISSUE-1" if kind == "issue" else "Q1"
        return row

    def test_missing_plan_and_zero_denominator_are_not_complete(self):
        self.assertEqual(ledger(self.task, self.evidence)["status"], "plan_required")
        self.event("initialize", items=[])
        result = ledger(self.task, self.evidence)
        self.assertEqual((result["completed"], result["planned"], result["percentage"]), (0, 0, None))
        self.assertEqual(result["status"], "no_active_items")

    def test_shared_module_identity_counts_once_in_total(self):
        self.event("initialize", items=[self.item(1, modules=["M03", "M06"])])
        result = ledger(self.task, self.evidence)
        self.assertEqual(result["planned"], 1)
        self.assertEqual(sum(row["planned"] for row in result["by_scope_module"]), 2)
        self.assertEqual(result["by_scope"][0]["planned"], 1)

    def test_query_completion_is_separate_from_risk_review(self):
        self.event("initialize", items=[self.item(1, kind="query")])
        self.evidence["source_runs"] = [{"run_id": "RUN-1", "provider": "registry", "query_id": "Q1",
            "plan_entry_sha256": sha256_json(self.row), "submission_state": "submitted", "status": "no_result"}]
        self.entries = [{"kind": "agent_investigation", "state": "awaiting_review", "query_id": "Q1"}]
        self.event("complete", item_id="ITEM-1", source_run_id="RUN-1", evidence_refs=["RUN-1"])
        result = ledger(self.task, self.evidence)
        self.assertEqual(result["percentage"], 100)
        self.assertEqual(result["counting_basis"].split(";")[1], " business_review_and_delivery_separate")

    def test_completion_accepts_registered_collection_evidence_and_rejects_missing_ref(self):
        self.event("initialize", items=[self.item(1, kind="query")])
        self.evidence["source_runs"] = [{"run_id": "RUN-1", "provider": "registry", "query_id": "Q1",
            "plan_entry_sha256": sha256_json(self.row), "submission_state": "submitted", "status": "success"}]
        self.evidence["collections"] = {"patents": [{"evidence_id": "EV-1", "source_run_id": "RUN-1"}]}
        with self.assertRaisesRegex(ValueError, "VERIFIED_EVIDENCE_REFS_REQUIRED"):
            self.event("complete", item_id="ITEM-1", source_run_id="RUN-1", evidence_refs=["RUN-1", "EV-MISSING"])
        self.event("complete", item_id="ITEM-1", source_run_id="RUN-1", evidence_refs=["RUN-1", "EV-1"])
        self.assertEqual(ledger(self.task, self.evidence)["percentage"], 100)

    def test_upstream_ids_include_registered_sources_and_semantics_without_progress_cycles(self):
        from review_progress_stage_a import _upstream_exists
        self.task["discovery_semantic_reviews"] = [{"review_id": "SEM-1"}]
        self.evidence["source_runs"] = [{"run_id": "RUN-1"}]
        self.evidence["collections"] = {"product_scope": [{"evidence_id": "EV-SCOPE"}]}
        self.evidence["review_progress_events"] = [{"event_id": "SELF-1"}]
        self.evidence["progress_events"] = [{"event_id": "SELF-2"}]
        for ref in ("SEM-1", "RUN-1", "EV-SCOPE"):
            with self.subTest(ref=ref):
                self.assertTrue(_upstream_exists(self.task, self.evidence, ref))
        for ref in ("SELF-1", "SELF-2", "UNKNOWN"):
            with self.subTest(ref=ref):
                self.assertFalse(_upstream_exists(self.task, self.evidence, ref))

    def test_ops_legacy_zero_completes_from_verified_projection_and_errors_stay_open(self):
        import test_source_result_processing as processing_fixture
        f = processing_fixture.ResultProcessingTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        run, evidence, body = f.ops_empty_fault_run()
        run["result_processing"].update(returned_count_basis="response_count_only", zero_proven=False)
        self.row.update(query_id=run["query_id"])
        self.plan = {"queries": {"epo_ops": [self.row]}}
        item = self.item(1, kind="query")
        item["query_id"] = run["query_id"]
        self.event("initialize", items=[item])
        (self.path / "ops-empty.xml").write_bytes(body)
        run["plan_entry_sha256"] = sha256_json(self.row)
        evidence["collections"]["patents"][0]["evidence_id"] = "EV-OPS"
        self.evidence.update(source_runs=[run], collections=evidence["collections"])
        run["metadata"]["search_coverage"]["schema_valid"] = False
        with self.assertRaisesRegex(ValueError, "ZERO_RESULT_UNVERIFIED"):
            self.event("complete", item_id="ITEM-1", source_run_id=run["run_id"], evidence_refs=[run["run_id"], "EV-OPS"])
        run["metadata"]["search_coverage"]["schema_valid"] = True
        self.event("complete", item_id="ITEM-1", source_run_id=run["run_id"], evidence_refs=[run["run_id"], "EV-OPS"])
        self.assertEqual(ledger(self.task, self.evidence)["percentage"], 100)
        self.assertIs(self.evidence["source_runs"][0]["result_processing"]["zero_proven"], False)

    def test_failure_wait_and_unregistered_run_do_not_complete(self):
        self.event("initialize", items=[self.item(1, kind="query")])
        self.evidence["source_runs"] = [{"run_id": "RUN-1", "provider": "registry", "query_id": "Q1",
            "plan_entry_sha256": sha256_json(self.row), "submission_state": "unknown", "status": "failed"}]
        with self.assertRaisesRegex(ValueError, "SUCCESSFUL_BOUND_RUN"):
            self.event("complete", item_id="ITEM-1", source_run_id="RUN-1", evidence_refs=["RUN-1"])
        self.assertEqual(ledger(self.task, self.evidence)["completed"], 0)

    def test_new_operating_progress_accepts_effective_submission_without_changing_run(self):
        from copy import deepcopy
        self.task['assessment_revision'] = 'known-findings-risk-v1'
        self.event('initialize', items=[self.item(1, kind='query')])
        run = {'run_id': 'RUN-AUDIT', 'provider': 'registry', 'query_id': 'Q1',
            'plan_entry_sha256': sha256_json(self.row), 'submission_state': 'unknown', 'status': 'success'}
        original = deepcopy(run)
        self.evidence['source_runs'] = [run]
        self.evidence['recovery_reviews'] = [{'source_run_id': run['run_id'],
            'source_run_sha256': sha256_json(run), 'kind': 'unknown_check', 'outcome': 'result_obtained'}]
        event = self.event('complete', item_id='ITEM-1', source_run_id=run['run_id'], evidence_refs=[run['run_id']])
        self.assertEqual(self.evidence['source_runs'][0], original)
        self.assertEqual(event['accepted_submission_state'], 'submitted')
        self.assertEqual(event['accepted_source_status'], 'success')
        self.assertEqual(event['source_run_sha256'], sha256_json(original))

    def test_new_operating_progress_audited_failed_request_does_not_count_complete(self):
        self.task['presentation_policy_revision'] = 'operator-report-v1'
        self.event('initialize', items=[self.item(1, kind='query')])
        run = {'run_id': 'RUN-FAILED', 'provider': 'registry', 'query_id': 'Q1',
            'plan_entry_sha256': sha256_json(self.row), 'submission_state': 'unknown', 'status': 'failed'}
        self.evidence['source_runs'] = [run]
        self.evidence['recovery_reviews'] = [{'source_run_id': run['run_id'],
            'source_run_sha256': sha256_json(run), 'kind': 'unknown_check', 'outcome': 'submitted_failed'}]
        with self.assertRaisesRegex(ValueError, 'SUCCESSFUL_BOUND_RUN'):
            self.event('complete', item_id='ITEM-1', source_run_id=run['run_id'], evidence_refs=[run['run_id']])
        self.assertEqual(ledger(self.task, self.evidence)['completed'], 0)

    def test_new_operating_progress_zero_needs_verified_retained_receipt(self):
        self.task['assessment_revision'] = 'known-findings-risk-v1'
        self.event('initialize', items=[self.item(1, kind='query')])
        run = {'run_id': 'RUN-NO-RECEIPT', 'provider': 'registry', 'query_id': 'Q1',
            'plan_entry_sha256': sha256_json(self.row), 'submission_state': 'submitted', 'status': 'no_result'}
        self.evidence['source_runs'] = [run]
        with self.assertRaisesRegex(ValueError, 'ZERO_RESULT_UNVERIFIED'):
            self.event('complete', item_id='ITEM-1', source_run_id=run['run_id'], evidence_refs=[run['run_id']])
        self.assertEqual(ledger(self.task, self.evidence)['completed'], 0)

    def test_stale_effective_submission_audit_does_not_complete(self):
        self.task['assessment_revision'] = 'known-findings-risk-v1'
        self.event('initialize', items=[self.item(1, kind='query')])
        run = {'run_id': 'RUN-AUDIT', 'provider': 'registry', 'query_id': 'Q1',
            'plan_entry_sha256': sha256_json(self.row), 'submission_state': 'unknown', 'status': 'success'}
        self.evidence['source_runs'] = [run]
        self.evidence['recovery_reviews'] = [{'source_run_id': run['run_id'],
            'source_run_sha256': '0' * 64, 'kind': 'unknown_check', 'outcome': 'result_obtained'}]
        with self.assertRaisesRegex(ValueError, 'SUCCESSFUL_BOUND_RUN'):
            self.event('complete', item_id='ITEM-1', source_run_id=run['run_id'], evidence_refs=[run['run_id']])

    def test_local_review_without_hashed_materials_cannot_complete(self):
        self.row.update(right_type="copyright", operation="provenance_review")
        self.plan = {"queries": {"asset_provenance": [self.row]}}
        item = self.item(1, kind="query"); item["scope"]["right_type"] = "copyright"
        self.event("initialize", items=[item])
        self.evidence["source_runs"] = [{"run_id": "RUN-LOCAL", "provider": "asset_provenance",
            "query_id": "Q1", "operation": "provenance_review", "source_environment": "local_agent_review",
            "plan_entry_sha256": sha256_json(self.row), "submission_state": "not_submitted", "status": "success"}]
        with self.assertRaisesRegex(ValueError, "SUCCESSFUL_BOUND_RUN"):
            self.event("complete", item_id="ITEM-1", source_run_id="RUN-LOCAL", evidence_refs=["RUN-LOCAL"])
        self.assertEqual(ledger(self.task, self.evidence)["completed"], 0)

    def test_private_user_action_is_separate_from_completed_public_local_review(self):
        from review_progress_stage_a import _local_asset_review_complete
        from copy import deepcopy
        payload = {"outstanding_actions": [{"kind": "user_information", "action_id": "SUPPLIER-1"}]}
        entry = {"payload": payload}
        run = {"provider": "asset_provenance", "operation": "provenance_review",
            "source_environment": "local_agent_review", "submission_state": "not_submitted", "status": "success"}
        evidence = {}
        row = {"operation": "provenance_review", "right_type": "copyright"}
        item = {"scope": {"scenario_id": "S1"}}
        with patch("assessment_v24.evidence_index", return_value={"EV": entry}), \
             patch("assessment_v24._entry_matches_run", return_value=True), \
             patch("assessment_v24._retained_artifacts_complete", return_value=True), \
             patch("record_asset_provenance.external_information_actions", return_value=deepcopy(payload["outstanding_actions"])) as external, \
             patch("record_asset_provenance.investigation_complete", side_effect=lambda _t, p, *_a: p["outstanding_actions"] == []) as public:
            self.assertTrue(_local_asset_review_complete({}, evidence, row, item, run))
            self.assertEqual(payload["outstanding_actions"], [{"kind": "user_information", "action_id": "SUPPLIER-1"}])
            public.assert_called_once()
            self.assertEqual(public.call_args.args[1]["outstanding_actions"], [])
        with patch("assessment_v24.evidence_index", return_value={"EV": entry}), \
             patch("assessment_v24._entry_matches_run", return_value=True), \
             patch("assessment_v24._retained_artifacts_complete", return_value=True), \
             patch("record_asset_provenance.external_information_actions", return_value=[]), \
             patch("record_asset_provenance.investigation_complete", return_value=True):
            self.assertFalse(_local_asset_review_complete({}, evidence, row, item, run))

    def test_executed_local_review_cannot_register_plan_retroactively(self):
        self.row.update(right_type="copyright", operation="provenance_review")
        self.plan = {"queries": {"asset_provenance": [self.row]}}
        self.evidence["source_runs"] = [{"run_id": "RUN-LOCAL", "provider": "asset_provenance",
            "query_id": "Q1", "operation": "provenance_review", "source_environment": "local_agent_review",
            "plan_entry_sha256": sha256_json(self.row), "submission_state": "not_submitted", "status": "success"}]
        item = self.item(1, kind="query"); item["scope"]["right_type"] = "copyright"
        with self.assertRaisesRegex(ValueError, "RETROACTIVE_QUERY_ITEM"):
            self.event("initialize", items=[item])

    def test_plan_change_and_reopen_preserve_history(self):
        self.event("initialize", items=[self.item(1)])
        self.open_issues = []
        self.evidence["product_scope_events"].append({"event_id": "FACT-1"})
        self.event("complete", item_id="ITEM-1", evidence_refs=["FACT-1"])
        self.evidence["product_scope_events"].append({"event_id": "CHANGE-1"})
        self.event("reopen", item_id="ITEM-1", upstream_ref="CHANGE-1")
        result = ledger(self.task, self.evidence)
        self.assertEqual((result["completed"], result["planned"]), (0, 1))
        self.assertEqual(result["items"][0]["completion_history"][0]["evidence_refs"], ["FACT-1"])
        self.event("exempt", item_id="ITEM-1", upstream_ref="CHANGE-1")
        result = ledger(self.task, self.evidence)
        self.assertEqual((result["completed"], result["planned"], result["percentage"]), (0, 0, None))

    def _change_version(self, version=2, *, affected_queries=None, affected_directions=None,
                        affected_candidates=None):
        from common import sha256_json
        self.task["product_change_version"] = version
        change = {"change_id": f"CHG-{version}", "version": version, "kind": "scope_change",
                  "affected_query_ids": affected_queries or [],
                  "affected_direction_ids": affected_directions or [],
                  "affected_candidate_ids": affected_candidates or [],
                  "expanded_candidate_ids": []}
        change["sha256"] = sha256_json(change)
        self.task["product_change_history"] = [change]

    def test_rebind_preserves_id_and_acceptance_but_returns_to_pending(self):
        self.task["product_change_version"] = "2"
        item = self.item(1, kind="query"); item["scope"]["product_version"] = "2"
        self.event("initialize", items=[item])
        self.evidence["source_runs"] = [{"run_id": "RUN-1", "provider": "registry", "query_id": "Q1",
            "plan_entry_sha256": sha256_json(self.row), "submission_state": "submitted", "status": "success"}]
        self.event("complete", item_id="ITEM-1", source_run_id="RUN-1", evidence_refs=["RUN-1"])
        original = ledger(self.task, self.evidence)["items"][0]
        original_acceptance = original["acceptance_condition"]
        self._change_version(version=3)
        self.assertEqual(dispatch_block(self.task, self.evidence, "registry", self.row),
                         "REVIEW_PROGRESS_QUERY_NOT_PLANNED")
        event = self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-3")
        result = ledger(self.task, self.evidence)["items"][0]
        self.assertEqual(event["kind"], "rebind")
        self.assertEqual(result["item_id"], "ITEM-1")
        self.assertEqual(result["scope"]["product_version"], "3")
        self.assertEqual(result["acceptance_condition"], original_acceptance)
        self.assertEqual(result["state"], "planned")
        self.assertNotIn("completion", result)
        self.assertEqual(result["completion_history"][0]["source_run_id"], "RUN-1")
        self.assertEqual(result["rebind_history"][0]["upstream_ref"], "CHG-3")
        self.assertIsNone(dispatch_block(self.task, self.evidence, "registry", self.row))

    def test_rebind_rejects_affected_query_or_direction(self):
        for kwargs, error in [
            ({"affected_queries": ["Q1"]}, "REBIND_QUERY_AFFECTED"),
            ({"affected_directions": ["D1"]}, "REBIND_DIRECTION_AFFECTED"),
        ]:
            with self.subTest(error=error):
                self.evidence["review_progress_events"] = []
                self.task["product_change_version"] = "1"
                self.task.pop("product_change_history", None)
                self.row["product_dependencies"] = [{"direction_id": "D1"}]
                self.plan = {"queries": {"registry": [self.row]}}
                self.event("initialize", items=[self.item(1, kind="query")])
                self._change_version(**kwargs)
                with self.assertRaisesRegex(ValueError, error):
                    self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-2")

    def test_rebind_rejects_changed_plan_or_unbound_change(self):
        self.event("initialize", items=[self.item(1, kind="query")])
        self._change_version()
        self.row["query"] = "changed query"
        self.plan = {"queries": {"registry": [self.row]}}
        with self.assertRaisesRegex(ValueError, "REBIND_PLAN_HASH_CHANGED"):
            self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-2")
        self.row.pop("query")
        self.plan = {"queries": {"registry": [self.row]}}
        with self.assertRaisesRegex(ValueError, "REBIND_PRODUCT_CHANGE_REQUIRED"):
            self.event("rebind", item_id="ITEM-1", upstream_ref="UNKNOWN")
        self.task["product_change_history"][0]["sha256"] = "tampered"
        with self.assertRaisesRegex(ValueError, "REBIND_PRODUCT_CHANGE_REQUIRED"):
            self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-2")

    def test_rebind_rejects_ambiguous_candidate_change_and_issue_item(self):
        self.event("initialize", items=[self.item(1, kind="query")])
        self._change_version(affected_candidates=["CAND-1"])
        with self.assertRaisesRegex(ValueError, "REBIND_CANDIDATE_SCOPE_AMBIGUOUS"):
            self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-2")
        self.evidence["review_progress_events"] = []
        self.task["product_change_version"] = "1"
        self.task.pop("product_change_history", None)
        self.event("initialize", items=[self.item(2, kind="issue")])
        self._change_version()
        with self.assertRaisesRegex(ValueError, "REBIND_QUERY_ONLY"):
            self.event("rebind", item_id="ITEM-2", upstream_ref="CHG-2")

    def test_rebind_rejects_skipping_an_intermediate_product_version(self):
        self.event("initialize", items=[self.item(1, kind="query")])
        changes = []
        for number in (2, 3):
            change = {"change_id": f"CHG-{number}", "version": number,
                      "kind": "scope_change", "affected_query_ids": [],
                      "affected_direction_ids": [], "affected_candidate_ids": [],
                      "expanded_candidate_ids": []}
            change["sha256"] = sha256_json(change)
            changes.append(change)
        self.task["product_change_version"] = 3
        self.task["product_change_history"] = changes
        with self.assertRaisesRegex(ValueError, "REBIND_VERSION_NOT_ADJACENT"):
            self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-3")

    def test_rebind_accepts_adjacent_v_prefixed_fixture_versions(self):
        self.task["product_change_version"] = "V1"
        item = self.item(1, kind="query"); item["scope"]["product_version"] = "V1"
        self.event("initialize", items=[item])
        self._change_version(version="V2")
        self.event("rebind", item_id="ITEM-1", upstream_ref="CHG-V2")
        self.assertEqual(ledger(self.task, self.evidence)["items"][0]["scope"]["product_version"], "V2")

    def test_prd_denominator_changes_and_completed_removal(self):
        items = {f"ITEM-{n}": {"state": "completed" if n < 60 else "planned"}
                 for n in range(100)}
        self.assertEqual(_counts(items)["percentage"], 60)
        items.update({f"ITEM-{n}": {"state": "planned"} for n in range(100, 120)})
        self.assertEqual((_counts(items)["completed"], _counts(items)["planned"],
                          _counts(items)["percentage"]), (60, 120, 50))
        for n in range(5):
            items[f"ITEM-{n}"]["state"] = "removed"
        self.assertEqual((_counts(items)["completed"], _counts(items)["planned"]), (55, 115))
        for n in range(100, 110):
            items[f"ITEM-{n}"]["state"] = "exempt"
        self.assertEqual((_counts(items)["completed"], _counts(items)["planned"]), (55, 105))
        for n in range(5, 10):
            items[f"ITEM-{n}"]["state"] = "planned"
        self.assertEqual((_counts(items)["completed"], _counts(items)["planned"]), (50, 105))

    def test_initialized_plan_blocks_unlisted_query_only(self):
        self.assertIsNone(dispatch_block(self.task, self.evidence, "registry", self.row))
        self.event("initialize", items=[self.item(1, kind="query")])
        self.assertIsNone(dispatch_block(self.task, self.evidence, "registry", self.row))
        self.assertEqual(dispatch_block(self.task, self.evidence, "registry",
                         {**self.row, "query_id": "Q2"}), "REVIEW_PROGRESS_QUERY_NOT_PLANNED")
        self.evidence["product_scope_events"].append({"event_id": "CHANGE-1"})
        self.event("remove", item_id="ITEM-1", upstream_ref="CHANGE-1")
        self.assertEqual(dispatch_block(self.task, self.evidence, "registry", self.row),
                         "REVIEW_PROGRESS_QUERY_NOT_PLANNED")

    def test_reconciliation_keeps_unregistered_query_resumable_after_plan_add(self):
        from contextlib import nullcontext
        from workflow_v24 import reconcile_scenario_actions
        self.event("initialize", items=[])

        def gate(task, plan, provider, row, *args, **kwargs):
            code = dispatch_block(task, self.evidence, provider, row)
            return {"code": code, "reason": code} if code else None

        with patch("workflow_v24.scenario_workflow_enabled", return_value=True), \
             patch("workflow_v24.correction_enabled", return_value=True), \
             patch("workflow_v24.scenario_supplement", return_value=None), \
             patch("workflow_v24.scenario_dispatch_block", side_effect=gate), \
             patch("decision_workflow.decision_snapshot", return_value=nullcontext()):
            reconcile_scenario_actions(self.path, self.task, self.plan, {}, {}, self.evidence)
            self.assertEqual(self.plan["execution_dispositions"], [])
            self.assertEqual(dispatch_block(self.task, self.evidence, "registry", self.row),
                             "REVIEW_PROGRESS_QUERY_NOT_PLANNED")
            self.evidence["product_scope_events"].append({"event_id": "RESULT-1"})
            self.event("add", items=[self.item(1, kind="query")], upstream_ref="RESULT-1")
            reconcile_scenario_actions(self.path, self.task, self.plan, {}, {}, self.evidence)
            self.assertEqual(self.plan["execution_dispositions"], [])
            self.assertIsNone(dispatch_block(self.task, self.evidence, "registry", self.row))

    def test_shared_country_scope_has_one_item_and_ep_is_allowed(self):
        self.task["target_jurisdictions"] = ["FR", "DE"]
        self.row["jurisdiction"] = "EP"
        self.plan["queries"]["registry"][0] = self.row
        item = self.item(1, kind="query", country="EP")
        self.event("initialize", items=[item])
        result = ledger(self.task, self.evidence)
        self.assertEqual(result["planned"], 1)
        self.assertEqual(result["by_scope"][0]["jurisdiction"], "EP")

    def test_closed_issue_without_new_fact_is_not_complete(self):
        self.evidence["product_scope_events"].append({"event_id": "OLD-FACT"})
        self.event("initialize", items=[self.item(1)])
        self.open_issues = []
        with self.assertRaisesRegex(ValueError, "NO_NEW_FACT"):
            self.event("complete", item_id="ITEM-1", evidence_refs=["OLD-FACT"])

    def test_no_retroactive_query_or_duplicate_obligation(self):
        self.evidence["source_runs"] = [{"run_id": "RUN-OLD", "provider": "registry", "query_id": "Q1",
            "submission_state": "submitted", "status": "success"}]
        with self.assertRaisesRegex(ValueError, "RETROACTIVE"):
            self.event("initialize", items=[self.item(1, kind="query")])
        self.evidence["source_runs"] = []
        self.event("initialize", items=[self.item(1)])
        self.evidence["product_scope_events"].append({"event_id": "CHANGE-1"})
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OBLIGATION"):
            self.event("add", items=[self.item(2)], upstream_ref="CHANGE-1")

    def test_old_task_is_untouched_and_projection_keeps_work(self):
        view = {"entries": [{"work_id": "W1", "state": "ready"}], "work_view_sha256": "old"}
        old = dict(self.task)
        del old["review_progress_revision"]
        self.assertIs(project(old, view, self.evidence), view)
        current = project(self.task, view, self.evidence)
        self.assertEqual(current["entries"], view["entries"])
        self.assertEqual(current["review_progress"]["status"], "plan_required")


if __name__ == "__main__":
    unittest.main()
