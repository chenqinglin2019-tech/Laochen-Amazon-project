"""Module-06 selected handoff, facts, comparisons and stage completion."""
from pathlib import Path
import tempfile
import unittest

from common import atomic_write_json, load_json, sha256_json
from candidate_triage_stage import record_selected_handoff
from specialty_analysis import REVISION, project, record
import test_triage_scope as base


class SpecialtyAnalysisTests(unittest.TestCase):
    def atomic_request(self, children, **changes):
        self.task['assessment_revision'] = 'known-findings-risk-v1'
        self.save()
        return {'events': children, 'scope': self.scope(), 'reviewer': 'atomic-agent',
            'reason': 'Reviewed exact original and actual product facts once', **changes}

    def atomic_material_request(self):
        return {'kind': 'material', 'alias': 'original', 'document_id': 'US-1', 'document_version': 'grant-v1',
            'evidence_refs': ['E1'], 'acquired_at': '2026-09-01T00:00:00Z', 'source_form': 'official_register',
            'purposes': ['identity', 'protection'], 'status': 'sufficient_for_listed_purposes',
            'supported_facts': ['identity', 'protection'], 'reading_locations': ['Original page 1 and claims'],
            'support_reasoning': 'Actual full original supports these listed uses'}

    def test_atomic_alias_chain_commits_once_and_repeated_request_is_idempotent(self):
        from unittest.mock import patch
        import specialty_analysis as module
        children = [{'kind': 'intake', 'alias': 'start', 'selected_handoff_event_id': self.handoff_id,
                     'assessment_date': '2026-09-24'}, self.atomic_material_request(),
            {'kind': 'fact', 'alias': 'identity', 'fact_id': 'F-ID', 'fact_kind': 'identity', 'outcome': 'supported',
             'raw_statement': 'Exact identity from original', 'reasoning': 'Original identity was read',
             'document_version': 'grant-v1', 'reading_locations': ['Original page 1'], 'evidence_refs': ['E1'],
             'material_event_ids': [{'$event': 'original'}]}]
        children[1]['intake_event_id'] = {'$event': 'start'}
        request = self.atomic_request(children, transaction_id='EXACT-ONCE')
        with patch.object(module, 'atomic_write_json', wraps=module.atomic_write_json) as write, \
             patch.object(module, 'project', wraps=module.project) as refresh:
            result = record(self.path, request)
            write.assert_called_once()
            refresh.assert_called_once()
        self.assertEqual(result['appended_event_count'], 3)
        events = result['events']
        self.assertEqual(events[2]['material_event_ids'], [events[1]['event_id']])
        self.assertEqual(events[1]['intake_event_id'], events[0]['event_id'])
        self.assertEqual(events[2]['reviewer'], 'atomic-agent')
        before = (self.path / 'task.json').read_bytes()
        repeated = record(self.path, request)
        self.assertEqual(repeated['status'], 'reused')
        self.assertEqual(repeated['events'], events)
        self.assertEqual((self.path / 'task.json').read_bytes(), before)

    def test_atomic_last_event_error_rolls_back_every_prior_child(self):
        request = self.atomic_request([{'kind': 'intake', 'alias': 'start',
            'selected_handoff_event_id': self.handoff_id, 'assessment_date': '2026-09-24'},
            self.atomic_material_request(), {'kind': 'fact', 'fact_kind': 'identity', 'outcome': 'supported'}])
        before = (self.path / 'task.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'FACT_INVALID'):
            record(self.path, request)
        self.assertEqual((self.path / 'task.json').read_bytes(), before)

    def test_atomic_forward_and_duplicate_aliases_leave_original_unchanged(self):
        for children in ([{'kind': 'material', 'intake_event_id': {'$event': 'future'}}],
                         [{'kind': 'intake', 'alias': 'same', 'selected_handoff_event_id': self.handoff_id,
                           'assessment_date': '2026-09-24'}, {'kind': 'intake', 'alias': 'same',
                           'selected_handoff_event_id': self.handoff_id, 'assessment_date': '2026-09-24'}]):
            request = self.atomic_request(children)
            before = (self.path / 'task.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'ALIAS_'):
                record(self.path, request)
            self.assertEqual((self.path / 'task.json').read_bytes(), before)

    def test_atomic_policy_and_reused_id_changed_input_are_not_silently_accepted(self):
        request = {'scope': self.scope(), 'reviewer': 'agent', 'reason': 'actual review',
            'events': [{'kind': 'intake', 'selected_handoff_event_id': self.handoff_id,
                        'assessment_date': '2026-09-24'}]}
        with self.assertRaisesRegex(ValueError, 'TRANSACTION_POLICY_REQUIRED'):
            record(self.path, request)
        request = self.atomic_request(request['events'], transaction_id='FIXED')
        record(self.path, request)
        with self.assertRaisesRegex(ValueError, 'ID_REUSED'):
            record(self.path, {**request, 'reason': 'different actual review'})
        self.evidence['collections']['product'][0]['payload']['product']['title'] = 'Changed actual product fact'
        atomic_write_json(self.path / 'evidence.json', self.evidence)
        with self.assertRaisesRegex(ValueError, 'TRANSACTION_INPUT_CHANGED'):
            record(self.path, request)

    def test_atomic_receipt_rejects_changed_actual_original_or_capability(self):
        from common import sha256_file
        self.intake()
        original = self.path / 'original.txt'
        original.write_text('Exact retained original source')
        self.evidence['collections']['sources'] = [{'evidence_id': 'LOCAL', 'path': str(original),
                                                   'sha256': sha256_file(original)}]
        request = self.atomic_request([self.atomic_material_request()])
        record(self.path, request)
        original.write_text('Changed source bytes without editing evidence JSON')
        before = (self.path / 'task.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'RETAINED_PATH_HASH_MISMATCH'):
            record(self.path, request)
        self.assertEqual((self.path / 'task.json').read_bytes(), before)
        original.write_text('Exact retained original source')
        atomic_write_json(self.path / 'source-capabilities.json', {'sources': ['new actual capability']})
        with self.assertRaisesRegex(ValueError, 'TRANSACTION_INPUT_CHANGED'):
            record(self.path, request)

    def test_atomic_source_change_during_validation_rolls_back_every_child(self):
        from unittest.mock import patch
        import specialty_analysis as module
        self.intake()
        request = self.atomic_request([self.atomic_material_request()])
        before = (self.path / 'task.json').read_bytes()
        with patch.object(module, '_transaction_source_fingerprints', side_effect=[{'raw': 'ONE'}, {'raw': 'TWO'}]):
            with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED_DURING_RECORD'):
                record(self.path, request)
        self.assertEqual((self.path / 'task.json').read_bytes(), before)

    def atomic_comparison_fixture(self, result='unknown'):
        self.intake()
        material = self.material()
        inventory = self.add('inventory', document_id='US-1', document_version='grant-v1',
            evidence_refs=['E1'], material_event_ids=[material['event_id']], reading_locations=['claim 1'],
            completeness_reasoning='All independent claims identified', units=[{
                'unit_id': 'claim-1', 'kind': 'independent_claim', 'implementation_id': 'sale',
                'product_configuration': 'actual strap', 'original_location': 'claim 1', 'necessary_elements': ['A']}])
        self.task.update(product_feedback_revision='product-feedback-v1',
            product_feedback_history=[{'kind': 'requested', 'request_id': 'PF-CMP',
                                      'target_sha256': self.task.get('product_identity', {}).get('sha256')}])
        comparison = {'inventory_event_id': inventory['event_id'], 'unit_id': 'claim-1',
            'disposition': 'compared', 'evidence_refs': ['E1', 'E2'], 'reasoning': 'Exact claim and product compared',
            'elements': [{'element_id': 'A', 'result': result, 'claim_quote': 'Actual claim A',
                'original_location': 'claim 1', 'product_fact': 'Internal mechanism not visible in supplied photo',
                'reasoning': 'No provided internal photograph confirms this element', 'claim_evidence_refs': ['E1'],
                'product_evidence_refs': [] if result == 'unknown' else ['E2']}]}
        self.task['assessment_revision'] = 'known-findings-risk-v1'
        self.save()
        return {'kind': 'comparison_close', 'scope': self.scope(), 'alias': 'compared',
            'reviewer': 'actual-reviewer', 'reason': 'Actual original and available product picture compared',
            'comparison': comparison}

    def test_comparison_close_derives_exact_gap_and_links_followup_atomically(self):
        from specialty_analysis import comparison_blockers, work_entries
        request = self.atomic_comparison_fixture()
        request.update(gap={'action_kind': 'user_fact', 'product_feedback_request_id': 'PF-CMP',
            'question': 'Provide actual internal mechanism', 'minimum_action': 'Supplier internal photo',
            'completion_condition': 'Claim A can be compared to actual internal mechanism',
            'existing_material_check': 'Available external photos read', 'next_value': 'Establish actual claim element'},
            followup={'outcome': 'waiting', 'result_review': 'No supplier internals have been provided',
                'remaining_impact': 'This element remains unknown', 'next_action_or_dependency': 'PF-CMP internal photo'})
        result = record(self.path, request)
        comparison, gap, follow = result['events']
        self.assertEqual(gap['basis_event_id'], comparison['event_id'])
        self.assertEqual(gap['obligation_bindings'][0]['basis_event_id'], comparison['event_id'])
        self.assertEqual(gap['obligation_bindings'][0]['reason'], comparison_blockers(comparison)[0]['reason'])
        self.assertEqual(follow['gap_event_id'], gap['event_id'])
        self.assertEqual(follow['gap_id'], gap['gap_id'])
        self.assertEqual(comparison['elements'][0]['result'], 'unknown')
        self.assertEqual(result['aliases']['compared.followup'], follow['event_id'])
        row = next(row for row in work_entries(result['projection']) if row.get('reason') == 'SPECIALTY_COMPARISON_UNKNOWN')
        self.assertEqual(row['state'], 'awaiting_user')
        before = (self.path / 'task.json').read_bytes()
        self.assertEqual(record(self.path, request)['status'], 'reused')
        self.assertEqual((self.path / 'task.json').read_bytes(), before)

    def test_comparison_close_without_real_recovery_or_valid_dependency_rolls_back(self):
        request = self.atomic_comparison_fixture()
        before = (self.path / 'task.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'DISPOSITION_AND_RECOVERY_REQUIRED'):
            record(self.path, request)
        self.assertEqual((self.path / 'task.json').read_bytes(), before)
        request.update(gap={'action_kind': 'user_fact', 'product_feedback_request_id': 'PF-CMP',
            'question': 'Internals?', 'minimum_action': 'Photo', 'completion_condition': 'Observable internals',
            'existing_material_check': 'External read', 'next_value': 'Compare'},
            followup={'outcome': 'limited', 'result_review': 'No internal source supplied',
                'remaining_impact': 'Unknown', 'next_action_or_dependency': 'Wait for supplier'})
        with self.assertRaisesRegex(ValueError, 'LIMIT_BASIS_REQUIRED'):
            record(self.path, request)
        self.assertEqual((self.path / 'task.json').read_bytes(), before)

    def test_known_comparison_creates_no_fake_gap_or_followup(self):
        request = self.atomic_comparison_fixture(result='differs')
        result = record(self.path, request)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['derived_gaps'], [])
        self.assertEqual(result['events'][0]['elements'][0]['result'], 'differs')

    def test_comparison_close_can_reference_inventory_created_earlier_in_same_batch(self):
        # Existing material/intake remain exact; a new inventory and comparison
        # bind sequentially without a separately persisted intermediate record.
        closure = self.atomic_comparison_fixture(result='differs')
        inventory = next(row for row in self.task['specialty_analysis_events'] if row['kind'] == 'inventory')
        draft_inventory = {key: value for key, value in inventory.items()
            if key not in {'event_id', 'recorded_at', 'previous_event_id', 'product_version_sha256', 'candidate_version_sha256'}}
        draft_inventory['alias'] = 'fresh-list'
        closure['comparison']['inventory_event_id'] = {'$event': 'fresh-list'}
        request = self.atomic_request([draft_inventory, closure])
        result = record(self.path, request)
        self.assertEqual(result['events'][1]['inventory_event_id'], result['events'][0]['event_id'])

    def status_plan_limit_fixture(self, handoff_gap=None):
        from necessary_completion import status_route_gap_entry
        self.task.update(completion_policy_revision="necessary-work-v3", assessment_policy="evidence-estimate-v1")
        self.task["coverage_requirements"] = [{"requirement_id": "STATUS-VERIFY", "jurisdiction": "US",
                                               "right_type": "patent", "phase": "candidate_verification"}]
        self.save()
        if handoff_gap:
            prior = next(row for row in self.task["candidate_triage_stage_events"] if row["event_id"] == self.handoff_id)
            handoff = record_selected_handoff(self.path, {**self.scope(), "annotation_id": prior["annotation_id"],
                "evidence_refs": ["E1"], "reading_scope": {"level": "result_record", "sections": ["claims"]},
                "verification_gaps": [handoff_gap], "reviewer": "agent", "reason": "Reviewed exact legacy obligation"})
            self.handoff_id = handoff["event_id"]
            self.refresh()
        self.intake()
        material = self.material()
        fact = self.fact("status", material, outcome="unknown")
        plan = {"queries": {}, "candidate_action_gaps": [{**self.scope(), "code": "US_PATENT_STATUS_ROUTE_UNIMPLEMENTED",
                "assigned_to": "implementation", "requirement_id": "STATUS-VERIFY", "required_facts": ["current_status"]}]}
        caps = {"uspto_patent_browser": {"provider": "uspto_patent_browser", "state": "unvalidated",
                "reason": "browser_adapter_requires_real_route_acceptance", "executable": False,
                "checked_at": "2026-09-27T00:00:00Z"}}
        atomic_write_json(self.path / "search-plan.json", plan)
        atomic_write_json(self.path / "source-capabilities.json", {"task_id": self.task["task_id"], "sources": list(caps.values())})
        entry = status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, caps, self.scope())
        self.assertIsNotNone(entry)
        return fact, plan, caps, entry

    def status_plan_gap(self, fact, entry, **changes):
        fields = dict(gap_id="STATUS-PLAN", question="Current status remains unknown", affected_judgment="status",
            action_kind="verify_known_right", source_plan_gap_sha256=entry["delivery_limit"]["planning_gap_sha256"],
            source_capabilities_sha256=entry["delivery_limit"]["capabilities_sha256"], minimum_action="Restore status route",
            completion_condition="Read a current official status record", existing_material_check="Grant already read",
            next_value="Current legal effect remains unknown", evidence_refs=["E1"],
            obligation_bindings=[{"reason": "SPECIALTY_FACT_REQUIRED", "fact_kind": "status", "basis_event_id": fact["event_id"],
                                  "reasoning": "The reviewed status fact alone depends on this missing Skill route"}])
        return self.add("gap", **{**fields, **changes})

    def test_exact_status_plan_gap_defers_only_reviewed_unknown_status(self):
        from specialty_analysis import work_entries
        from necessary_completion import _delivery_limit_valid
        fact, plan, caps, entry = self.status_plan_limit_fixture()
        gap = self.status_plan_gap(fact, entry)
        self.add("followup", gap_id="STATUS-PLAN", gap_event_id=gap["event_id"], outcome="limited",
                 result_review="The Skill status route is not implemented; no official query was made",
                 remaining_impact="Status stays unknown", next_action_or_dependency="Implement and accept the status route",
                 limit_evidence="Exact current plan/capability/intake proof", limit_kind="evidence_not_obtainable_within_scope",
                 restore_condition="A current status route is available")
        rows = work_entries(project(self.task, self.evidence, self.candidates, self.ledger,
            plan=plan, capabilities=caps, task_dir=self.path, source_work=[entry]))
        status = next(row for row in rows if row.get("specialty_reason") == "SPECIALTY_FACT_REQUIRED")
        self.assertEqual(status["state"], "blocked")
        self.assertEqual(status["fact_kind"], "status")
        self.assertEqual(status["official_verification"], "not_verified")
        self.assertTrue(_delivery_limit_valid(status, self.task, self.evidence, plan, caps,
            candidates=self.candidates, ledger=self.ledger))
        self.assertTrue(any(row.get("fact_kind") == "product" and row["state"] == "awaiting_review" for row in rows))

    def test_status_plan_limit_rejects_changed_plan_capability_candidate_and_restored_route(self):
        from copy import deepcopy
        from necessary_completion import _delivery_limit_valid, status_route_gap_entry
        _, plan, caps, entry = self.status_plan_limit_fixture()
        changed = deepcopy(plan); changed["updated_at"] = "later"
        self.assertFalse(_delivery_limit_valid(entry, self.task, self.evidence, changed, caps,
            candidates=self.candidates, ledger=self.ledger))
        cap_changed = deepcopy(caps); cap_changed["uspto_patent_browser"]["checked_at"] = "later"
        self.assertFalse(_delivery_limit_valid(entry, self.task, self.evidence, plan, cap_changed,
            candidates=self.candidates, ledger=self.ledger))
        restored = deepcopy(plan); restored["queries"] = {"registry": [{**self.scope(), "query_id": "REAL-STATUS",
                                                                        "required_facts": ["current_status"]}]}
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, restored, caps, self.scope()))
        cap_restored = deepcopy(caps); cap_restored["uspto_patent_browser"]["operations"] = [
            {"jurisdiction": "US", "right_type": "patent", "operation": "current_status"}]
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, cap_restored, self.scope()))
        candidates = deepcopy(self.candidates); candidates["patents"][0]["title"] = "different candidate"
        self.assertFalse(_delivery_limit_valid(entry, self.task, self.evidence, plan, caps,
            candidates=candidates, ledger=self.ledger))
        forged = deepcopy(entry); forged["query_id"] = "NEVER-SUBMITTED"
        self.assertFalse(_delivery_limit_valid(forged, self.task, self.evidence, plan, caps,
            candidates=self.candidates, ledger=self.ledger))
        forged = deepcopy(entry); forged["official_verification"] = "verified"
        self.assertFalse(_delivery_limit_valid(forged, self.task, self.evidence, plan, caps,
            candidates=self.candidates, ledger=self.ledger))

    def test_candidate_projection_metadata_does_not_reopen_current_route_dependency(self):
        from copy import deepcopy
        from necessary_completion import status_route_gap_entry
        from specialty_analysis import work_entries
        fact, plan, caps, source = self.status_plan_limit_fixture()
        gap = self.status_plan_gap(fact, source)
        self.add("followup", gap_id=gap["gap_id"], gap_event_id=gap["event_id"], outcome="limited",
            result_review="Status route missing", remaining_impact="Current status remains unknown",
            next_action_or_dependency="Implement route", limit_evidence="Exact current route gap",
            limit_kind="evidence_not_obtainable_within_scope", restore_condition="Accepted current route")
        candidates = deepcopy(self.candidates)
        candidates["patents"][0]["triage_by_scenario"] = {"product_entry": [{"current": True}]}
        current = status_route_gap_entry(self.task, self.evidence, candidates, self.ledger, plan, caps, self.scope())
        self.assertIsNotNone(current)
        self.assertNotEqual(source["delivery_limit"]["candidate_sha256"], current["delivery_limit"]["candidate_sha256"])
        rows = work_entries(project(self.task, self.evidence, candidates, self.ledger, plan=plan,
                                    capabilities=caps, task_dir=self.path, source_work=[current]))
        self.assertEqual(next(row for row in rows if row.get("fact_kind") == "status")["state"], "blocked")
        candidates["patents"][0]["title"] = "Changed substantive candidate content"
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, candidates, self.ledger, plan, caps, self.scope()))

    def test_unrelated_operation_acceptance_refreshes_route_proof_without_reopening_unknown(self):
        from copy import deepcopy
        from necessary_completion import status_route_gap_entry
        from specialty_analysis import work_entries
        fact, plan, caps, source = self.status_plan_limit_fixture()
        gap = self.status_plan_gap(fact, source)
        self.add("followup", gap_id=gap["gap_id"], gap_event_id=gap["event_id"], outcome="limited",
            result_review="Status route missing", remaining_impact="Current status stays unknown",
            next_action_or_dependency="Implement route", limit_evidence="Exact current proof",
            limit_kind="evidence_not_obtainable_within_scope", restore_condition="Current status route available")
        changed = deepcopy(caps)
        changed["uspto_patent_browser"]["operations"] = [{"jurisdiction": "US", "right_type": "patent",
            "operation": "patent_recall", "search_dimension": "text", "query_compiler_revision": "ppubs-boolean-v2"}]
        current = status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, changed, self.scope())
        self.assertIsNotNone(current)
        self.assertNotEqual(source["delivery_limit"]["capabilities_sha256"], current["delivery_limit"]["capabilities_sha256"])
        rows = work_entries(project(self.task, self.evidence, self.candidates, self.ledger, plan=plan,
                                    capabilities=changed, task_dir=self.path, source_work=[current]))
        self.assertEqual(next(row for row in rows if row.get("fact_kind") == "status")["state"], "blocked")
        changed["uspto_patent_browser"]["operations"].append({"jurisdiction": "US", "right_type": "patent",
            "operation": "current_status", "search_dimension": "current_status"})
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, changed, self.scope()))
        rows = work_entries(project(self.task, self.evidence, self.candidates, self.ledger, plan=plan,
                                    capabilities=changed, task_dir=self.path, source_work=[current]))
        self.assertEqual(next(row for row in rows if row.get("fact_kind") == "status")["state"], "awaiting_review")

    def test_status_plan_limit_disappears_when_unknown_fact_is_replaced(self):
        from necessary_completion import status_route_gap_entry
        fact, plan, caps, _ = self.status_plan_limit_fixture()
        material = next(row for row in self.task["specialty_analysis_events"]
                        if row["event_id"] == fact["material_event_ids"][0])
        self.fact("status", material)
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, caps, self.scope()))

    def test_status_plan_gap_cannot_use_claims_query_product_or_comparison(self):
        fact, _, _, entry = self.status_plan_limit_fixture()
        with self.assertRaisesRegex(ValueError, "BOUNDARY_REQUIRED"):
            self.status_plan_gap(fact, entry, source_query_id="CLAIMS")
        for reason, field, value in (("SPECIALTY_FACT_REQUIRED", "fact_kind", "product"),
                                    ("SPECIALTY_COMPARISON_UNKNOWN", "unit_id", "claim-1")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, "FACT_BOUNDARY_REQUIRED"):
                self.status_plan_gap(fact, entry, obligation_bindings=[{"reason": reason, field: value,
                    "basis_event_id": fact["event_id"], "reasoning": "Cannot borrow the status limit"}])

    def test_status_plan_gap_only_links_explicit_current_status_handoff(self):
        fact, _, _, entry = self.status_plan_limit_fixture()
        binding = {"reason": "SPECIALTY_HANDOFF_GAP_OPEN", "handoff_gap": "current_status", "fact_kind": "status",
                   "basis_event_id": fact["event_id"], "reasoning": "This exact intake gap concerns the same unknown status"}
        with self.assertRaisesRegex(ValueError, "FACT_BOUNDARY_REQUIRED"):
            self.status_plan_gap(fact, entry, obligation_bindings=[binding])
        mixed = {**binding, "handoff_gap": "current_status and owner/assignment"}
        with self.assertRaisesRegex(ValueError, "FACT_BOUNDARY_REQUIRED"):
            self.status_plan_gap(fact, entry, obligation_bindings=[mixed],
                                 status_handoff_gaps=[mixed["handoff_gap"]])
        self.status_plan_gap(fact, entry, obligation_bindings=[binding], status_handoff_gaps=["current_status"])

    def test_reviewed_legacy_handoff_classification_preserves_unknown_and_other_obligations(self):
        from specialty_analysis import work_entries
        raw = "Maintenance fee and current legal status remain unverified"
        fact, plan, caps, entry = self.status_plan_limit_fixture(raw)
        classified = self.add("handoff_classification", handoff_gap=raw, fact_kinds=["status"],
            material_event_ids=fact["material_event_ids"], evidence_refs=fact["evidence_refs"],
            reading_locations=["Exact intake handoff and retained grant status reading"],
            classification_reasoning="Both maintenance and current legal effect are status; no owner question is present")
        binding = {"reason": "SPECIALTY_HANDOFF_GAP_OPEN", "fact_kind": "status", "handoff_gap": raw,
            "basis_event_id": fact["event_id"], "reasoning": "Explicitly reviewed status-only obligation",
            "handoff_classification_event_id": classified["event_id"],
            "handoff_classification_sha256": sha256_json(classified)}
        gap = self.status_plan_gap(fact, entry, obligation_bindings=[binding])
        self.add("followup", gap_id=gap["gap_id"], gap_event_id=gap["event_id"], outcome="limited",
            result_review="Status route unimplemented", remaining_impact="Current status remains unknown",
            next_action_or_dependency="Implement status route", limit_evidence="Current exact plan proof",
            limit_kind="evidence_not_obtainable_within_scope", restore_condition="Accepted current status route")
        def rows():
            return work_entries(project(self.task, self.evidence, self.candidates, self.ledger,
                plan=plan, capabilities=caps, task_dir=self.path, source_work=[entry]))
        self.assertEqual(next(row for row in rows() if row.get("handoff_gap") == raw)["state"], "blocked")
        self.assertEqual(next(row for row in self.task["specialty_analysis_events"]
            if row["event_id"] == fact["event_id"])["outcome"], "unknown")
        self.assertTrue(any(row.get("fact_kind") == "product" and row["state"] == "awaiting_review" for row in rows()))
        change = self.add("change", change_id="CLASS-READING", change_kind="classification_reading",
            substantive=True, affected_event_ids=classified["material_event_ids"], evidence_refs=["E1"],
            impact_reasoning="The classification's reading basis requires review")
        self.assertEqual(next(row for row in rows() if row.get("handoff_gap") == raw)["state"], "awaiting_review")
        self.add("change_review", change_event_id=change["event_id"], outcome="continues",
            reviewed_affected_event_ids=classified["material_event_ids"], evidence_refs=["E1"],
            recheck_reasoning="Reread actual material; it continues to support the classification only")
        self.assertEqual(next(row for row in rows() if row.get("handoff_gap") == raw)["state"], "blocked")
        # Append a reviewed classification change; an old ID/hash never authorizes the new kinds.
        self.add("handoff_classification", handoff_gap=raw, fact_kinds=["status", "rights_holder"],
            material_event_ids=fact["material_event_ids"], evidence_refs=fact["evidence_refs"],
            reading_locations=["Exact intake handoff"], classification_reasoning="A separate owner obligation was identified",
            supersedes_event_id=classified["event_id"], revision_reasoning="Correct the reviewed scope")
        self.assertEqual(next(row for row in rows() if row.get("handoff_gap") == raw)["state"], "awaiting_review")

    def test_legacy_handoff_classification_rejects_unread_foreign_gap_and_preserves_mixed_facets(self):
        raw = "Current status and owner/assignment have not been checked"
        fact, _, _, entry = self.status_plan_limit_fixture(raw)
        fields = dict(handoff_gap=raw, fact_kinds=["status", "rights_holder"],
            material_event_ids=fact["material_event_ids"], evidence_refs=fact["evidence_refs"],
            reading_locations=["Exact intake handoff"], classification_reasoning="Preserve both explicit obligations")
        for changes in ({"handoff_gap": "different text"}, {"fact_kinds": ["invented"]},
                        {"material_event_ids": ["missing"]}, {"reading_locations": []}):
            with self.assertRaises(ValueError):
                self.add("handoff_classification", **{**fields, **changes})
        unread = self.add("material", document_id="UNREAD", document_version="v1", evidence_refs=["E1"],
            acquired_at="2026-09-01T00:00:00Z", source_form="official_register", purposes=["status"],
            status="acquired", reading_locations=[], support_reasoning="Retained, not yet read")
        with self.assertRaisesRegex(ValueError, "CLASSIFICATION_READING_REQUIRED"):
            self.add("handoff_classification", **{**fields, "material_event_ids": [unread["event_id"]]})
        classified = self.add("handoff_classification", **fields)
        binding = {"reason": "SPECIALTY_HANDOFF_GAP_OPEN", "fact_kind": "status", "handoff_gap": raw,
            "basis_event_id": fact["event_id"], "reasoning": "Attempt to hide ownership with status",
            "handoff_classification_event_id": classified["event_id"],
            "handoff_classification_sha256": sha256_json(classified)}
        self.status_plan_gap(fact, entry, obligation_bindings=[binding])
        facets = [row for row in self.view()["scopes"][0]["blockers"] if row.get("handoff_gap") == raw]
        self.assertEqual({row["fact_kind"] for row in facets}, {"status", "rights_holder"})
        with self.assertRaisesRegex(ValueError, "CLASSIFICATION_REVISION_REQUIRED"):
            self.add("handoff_classification", **{**fields, "fact_kinds": ["status"]})

    def test_mixed_handoff_needs_separate_current_status_and_owner_dependencies(self):
        from copy import deepcopy
        from necessary_completion import status_route_gap_entry, _delivery_limit_valid
        from specialty_analysis import work_entries
        raw = "Current status and owner/assignment have not been checked"
        status_fact, plan, caps, status_source = self.status_plan_limit_fixture(raw)
        owner_material = self.material(purposes=["rights_holder"])
        owner_fact = self.fact("rights_holder", owner_material, outcome="unknown")
        classification = self.add("handoff_classification", handoff_gap=raw, fact_kinds=["status", "rights_holder"],
            material_event_ids=status_fact["material_event_ids"], evidence_refs=status_fact["evidence_refs"],
            reading_locations=["Exact mixed handoff"], classification_reasoning="Both status and ownership must be checked")
        def binding(kind, fact):
            return {"reason": "SPECIALTY_HANDOFF_GAP_OPEN", "fact_kind": kind, "handoff_gap": raw,
                "basis_event_id": fact["event_id"], "reasoning": "Only the explicitly classified facet depends on this route",
                "handoff_classification_event_id": classification["event_id"],
                "handoff_classification_sha256": sha256_json(classification)}
        status_gap = self.status_plan_gap(status_fact, status_source, obligation_bindings=[binding("status", status_fact)])
        def limited(gap):
            self.add("followup", gap_id=gap["gap_id"], gap_event_id=gap["event_id"], outcome="limited",
                result_review="Exact Skill route not implemented; no official query", remaining_impact="Facet remains unknown",
                next_action_or_dependency="Implement and accept route", limit_evidence="Current exact route-gap proof",
                limit_kind="evidence_not_obtainable_within_scope", restore_condition="Accepted route is restored")
        limited(status_gap)
        # An unrelated plan addition must refresh current proofs, preserving the relevant status dependency.
        plan["candidate_action_gaps"].append({**self.scope(), "code": "US_PATENT_OWNER_ROUTE_UNIMPLEMENTED",
            "assigned_to": "implementation", "requirement_id": "STATUS-VERIFY", "required_facts": ["rights_holder"]})
        atomic_write_json(self.path / "search-plan.json", plan)
        status_source = status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, caps, self.scope())
        owner_source = status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, plan, caps,
                                              self.scope(), fact_kind="rights_holder")
        self.assertEqual(owner_source["delivery_limit"]["kind"], "ownership_plan_gap")
        self.assertTrue(_delivery_limit_valid(owner_source, self.task, self.evidence, plan, caps,
            candidates=self.candidates, ledger=self.ledger))
        restored_caps = deepcopy(caps)
        restored_caps["uspto_patent_browser"]["operations"] = [{"jurisdiction": "US", "right_type": "patent",
                                                                 "operation": "patent_assignment"}]
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger,
            plan, restored_caps, self.scope(), fact_kind="rights_holder"))
        wrong = deepcopy(owner_source); wrong["fact_kind"] = "status"
        self.assertFalse(_delivery_limit_valid(wrong, self.task, self.evidence, plan, caps,
            candidates=self.candidates, ledger=self.ledger))
        def facets():
            return [row for row in work_entries(project(self.task, self.evidence, self.candidates, self.ledger,
                plan=plan, capabilities=caps, task_dir=self.path, source_work=[status_source, owner_source]))
                if row.get("handoff_gap") == raw]
        self.assertEqual({row["fact_kind"]: row["state"] for row in facets()},
                         {"status": "blocked", "rights_holder": "awaiting_review"})
        owner_gap = self.status_plan_gap(owner_fact, owner_source, gap_id="OWNER-PLAN",
            obligation_bindings=[binding("rights_holder", owner_fact)], affected_judgment="rights_holder")
        limited(owner_gap)
        self.assertEqual({row["fact_kind"]: row["state"] for row in facets()},
                         {"status": "blocked", "rights_holder": "blocked"})
        # Restoring ownership alone invalidates its proof while the status route remains independently missing.
        restored = deepcopy(plan); restored["queries"] = {"registry": [{**self.scope(), "query_id": "OWNER-REAL",
            "required_facts": ["rights_holder"]}]}
        self.assertIsNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger, restored,
            caps, self.scope(), fact_kind="rights_holder"))
        self.assertFalse(_delivery_limit_valid(owner_source, self.task, self.evidence, restored, caps,
            candidates=self.candidates, ledger=self.ledger))
        self.assertIsNotNone(status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger,
                                                   restored, caps, self.scope()))

    def test_registered_design_status_owner_and_territory_gaps_are_typed_separately(self):
        from unittest.mock import patch
        from necessary_completion import status_route_gap_entry, _delivery_limit_valid
        from specialty_analysis import _scope
        self.task.update(completion_policy_revision="necessary-work-v3", assessment_policy="evidence-estimate-v1")
        scope = {**self.scope(), "right_type": "design"}
        self.task["coverage_requirements"] = [{"requirement_id": "DESIGN-VERIFY", "jurisdiction": "US",
            "right_type": "design", "phase": "candidate_verification"}]
        caps = {"uspto_patent_browser": {"provider": "uspto_patent_browser", "executable": False,
            "state": "unvalidated", "reason": "browser_adapter_requires_real_route_acceptance",
            "checked_at": "2026-09-27T00:00:00Z"}}
        current = {"annotation": {"annotation_id": "ANN-D"}}
        intake = {"event_id": "INT-D", "annotation_id": "ANN-D", "selected_handoff_event_id": "HAND-D"}
        handoff = {**scope, "event_id": "HAND-D", "kind": "selected_handoff", "annotation_id": "ANN-D"}
        candidate = {"candidate_id": scope["candidate_id"], "right_type": "design"}
        def check(fact_kind, code, required, plan_required, proof_kind):
            fact = {**scope, "event_id": "FACT-" + fact_kind, "kind": "fact", "fact_kind": fact_kind,
                "outcome": "unknown", "intake_event_id": "INT-D"}
            plan = {"queries": {}, "candidate_action_gaps": [{**scope, "code": code,
                "assigned_to": "implementation", "requirement_id": "DESIGN-VERIFY",
                "required_facts": required}]}
            with patch("specialty_analysis._current", return_value=current), \
                    patch("specialty_analysis._intake", return_value=intake), \
                    patch("specialty_analysis.events", return_value=[fact]), \
                    patch("candidate_triage_stage.events", return_value=[handoff]), \
                    patch("annotate_materiality.iter_candidates", return_value=[("C1", candidate)]):
                entry = status_route_gap_entry(self.task, self.evidence, self.candidates, self.ledger,
                    plan, caps, scope, fact_kind=fact_kind)
                self.assertEqual(entry["delivery_limit"]["kind"], proof_kind)
                self.assertEqual(entry["delivery_limit"]["fact_kind"], fact_kind)
                self.assertTrue(_delivery_limit_valid(entry, self.task, self.evidence, plan, caps,
                    candidates=self.candidates, ledger=self.ledger))
                altered = {**entry, "fact_kind": "status" if fact_kind != "status" else "territory"}
                self.assertFalse(_delivery_limit_valid(altered, self.task, self.evidence, plan, caps,
                    candidates=self.candidates, ledger=self.ledger))
        check("status", "US_DESIGN_STATUS_ROUTE_UNIMPLEMENTED", ["current_status"],
            ["current_status"], "status_plan_gap")
        check("rights_holder", "US_DESIGN_OWNER_ROUTE_UNIMPLEMENTED", ["rights_holder"],
            ["rights_holder"], "ownership_plan_gap")
        check("territory", "US_DESIGN_STATUS_ROUTE_UNIMPLEMENTED", ["current_status"],
            ["current_status"], "territory_current_effect_plan_gap")

    def discovery_delegation_fixture(self):
        from specialty_analysis import _discovery_scope_basis, FACT_KINDS
        raw = "Other US patents and design patents have not been comprehensively searched"
        fact, plan, caps, source = self.status_plan_limit_fixture(raw)
        self.task["coverage_requirements"] += [{"requirement_id": "RECALL-" + right, "jurisdiction": "US",
            "right_type": right, "phase": "official_recall"} for right in ("patent", "design")]
        self.save(); atomic_write_json(self.path / "search-plan.json", {**plan, "task_id": self.task["task_id"]})
        plan["task_id"] = self.task["task_id"]
        basis = _discovery_scope_basis(self.task, tuple(self.scope().values()))
        fields = dict(handoff_gap=raw, classification="residual_discovery", excluded_fact_kinds=sorted(FACT_KINDS),
            coverage_requirement_ids=list(basis["coverage_requirements"]), direction_refs=basis["direction_refs"],
            nondelegated_event_ids=[fact["event_id"]], evidence_refs=fact["evidence_refs"],
            material_event_ids=fact["material_event_ids"], reading_locations=["Exact residual handoff and reviewed grant"],
            scope_reasoning="This means additional unknown-object discovery; known-right facts and comparisons stay separate",
            remaining_impact="Other rights may exist; residual discovery remains pending in the canonical recall queue")
        return raw, fact, plan, caps, fields

    def test_residual_discovery_delegation_keeps_original_unknown_and_ready_source_work(self):
        from specialty_analysis import discovery_delegation_entry, work_entries
        from necessary_completion import _delivery_limit_valid
        raw, fact, plan, caps, fields = self.discovery_delegation_fixture()
        review = self.add("handoff_discovery_scope", **fields)
        entry = discovery_delegation_entry(self.task, self.evidence, self.candidates, self.ledger, plan, self.scope(), raw)
        self.assertIsNotNone(entry)
        self.assertTrue(_delivery_limit_valid(entry, self.task, self.evidence, plan, caps,
            candidates=self.candidates, ledger=self.ledger))
        ready = {**self.scope(), "kind": "source_lookup", "state": "ready", "query_id": "REAL-DISCOVERY"}
        view = project(self.task, self.evidence, self.candidates, self.ledger, plan=plan, capabilities=caps, source_work=[ready])
        rows = work_entries(view)
        delegated = next(row for row in rows if row.get("handoff_gap") == raw)
        self.assertEqual(delegated["state"], "blocked")
        self.assertEqual(delegated["limitation_kind"], "residual_discovery_pending")
        self.assertTrue(any(row["reason"] == "SPECIALTY_SOURCE_PENDING" and row["state"] == "awaiting_review" for row in rows))
        self.assertNotEqual(view["status"], "normal_complete")
        self.assertEqual(fact["outcome"], "unknown")
        self.assertEqual(review["handoff_gap"], raw)
        # Current proof changes with the plan, while the exact canonical delegation stays applicable.
        updated = {**plan, "updated_at": "later"}
        self.assertFalse(_delivery_limit_valid(entry, self.task, self.evidence, updated, caps,
            candidates=self.candidates, ledger=self.ledger))
        self.assertIsNotNone(discovery_delegation_entry(self.task, self.evidence, self.candidates, self.ledger,
                                                       updated, self.scope(), raw))
        self.task["coverage_requirements"][-1]["new_rule"] = "changed"
        self.assertIsNone(discovery_delegation_entry(self.task, self.evidence, self.candidates, self.ledger,
                                                    plan, self.scope(), raw))

    def test_residual_discovery_delegation_rejects_partial_mapping_and_known_fact_gap(self):
        raw, fact, _, _, fields = self.discovery_delegation_fixture()
        for changes in ({"coverage_requirement_ids": ["RECALL-patent"]}, {"direction_refs": []},
                        {"nondelegated_event_ids": []}, {"excluded_fact_kinds": ["status"]},
                        {"handoff_gap": "foreign gap"}, {"material_event_ids": ["UNREAD"]}):
            with self.assertRaises(ValueError):
                self.add("handoff_discovery_scope", **{**fields, **changes})
        self.add("handoff_classification", handoff_gap=raw, fact_kinds=["status"],
            material_event_ids=fact["material_event_ids"], evidence_refs=fact["evidence_refs"],
            reading_locations=["Exact handoff"], classification_reasoning="A concrete fact obligation, not residual discovery")
        with self.assertRaisesRegex(ValueError, "KNOWN_OBLIGATION_FORBIDDEN"):
            self.add("handoff_discovery_scope", **fields)

    def original_content_reuse_fixture(self):
        from common import (active_free_policy, AUTOMATION_POLICY_REVISION, RECALL_INTEGRITY_REVISION, sha256_file,
                            serper_free_enhancement, serpapi_free_enhancement, signa_free_enhancement)
        from record_candidate_lead import record_candidate_lead, SCHEMA
        from workflow_v24 import product_identity_digest, build_coverage_requirements_v24
        self.task.update(free_policy=active_free_policy(), free_policy_revision=AUTOMATION_POLICY_REVISION,
                         screening_revision=RECALL_INTEGRITY_REVISION,
                         serper_free_enhancement=serper_free_enhancement(),
                         serpapi_free_enhancement=serpapi_free_enhancement(), signa_free_enhancement=signa_free_enhancement(),
                         coverage_requirements=build_coverage_requirements_v24(self.task["target_jurisdictions"],
                             screening_revision=RECALL_INTEGRITY_REVISION))
        self.evidence.update(schema_version=self.task["schema_version"], task_id=self.task["task_id"])
        self.save()
        path = self.path / "original.pdf"
        path.write_bytes(b"%PDF-1.4\nOFFLINE synthetic test only. US11111111B2 grant and claim 1.\n")
        source = {"evidence_id": "ORIGINAL", "kind": "patent_document", "publication_number": "US11111111B2",
            "jurisdiction": "US", "right_type": "patent", "path": str(path), "sha256": sha256_file(path),
            "bytes": path.stat().st_size, "source_url": "https://example.test/original", "checked_at": "2026-09-01T00:00:00Z"}
        atomic_write_json(self.path / "supplemental-evidence.json", {"evidence": [source], "schema": "IPR-RETAINED-DOCUMENTS/1.0"})
        record_candidate_lead(self.path, {"schema": SCHEMA, "publication_number": "US11111111B2", "title": "Retained grant",
            "jurisdiction": "US", "right_type": "patent", "product_identity_sha256": product_identity_digest(self.task["product"], task=self.task),
            "source_registration": {"kind": "supplement", "manifest": "supplemental-evidence.json", "evidence_id": "ORIGINAL"},
            "document": {key: source[key] for key in ("path", "sha256", "bytes", "source_url")},
            "review": {"reviewer": "offline-test", "reviewed_at": "2026-09-01T00:01:00Z", "number_location": "fixture first line",
                "number_quote": "US11111111B2", "reasoning": "Exact retained fixture only", "content_verification": "agent_read_original"}})
        self.evidence = load_json(self.path / "evidence.json")
        self.intake()
        material = self.add("material", document_id="US11111111B2", document_version="original-v1",
            evidence_refs=["ORIGINAL"], acquired_at="2026-09-01T00:00:00Z", source_form="original_document",
            purposes=["protection"], reading_locations=["claim 1"], status="sufficient_for_listed_purposes",
            supported_facts=["protection"], support_reasoning="Exact original claim actually read in fixture")
        fact = self.fact("protection", material)
        row = {**self.scope(), "action_purpose": "document_content", "required_facts": ["protection_content"],
               "reading_scope": {"level": "protection_content"}, "record_number": "US11111111B2"}
        return path, row, fact, material, load_json(self.path / "supplemental-evidence.json")

    def test_current_read_supported_original_content_reuse_has_no_source_receipt(self):
        from same_task_evidence import _specialty_document_content
        path, row, fact, material, supplement = self.original_content_reuse_fixture()
        result = _specialty_document_content(self.task, self.evidence, self.candidates, self.ledger,
            "uspto_patent_browser", row, supplement=supplement, directory=self.path)
        self.assertIsNotNone(result)
        self.assertEqual(result["satisfied_facts"], ["protection_content"])
        self.assertEqual(result["specialty_reading_proof"]["fact_event_id"], fact["event_id"])
        self.assertNotIn("source_run_id", result)
        self.assertNotIn("source_query_execution", result)
        path.write_bytes(b"changed")
        self.assertIsNone(_specialty_document_content(self.task, self.evidence, self.candidates, self.ledger,
            "uspto_patent_browser", row, supplement=supplement, directory=self.path))

    def test_original_content_reuse_rejects_status_owner_unknown_and_suspended_reading(self):
        from same_task_evidence import _specialty_document_content
        _, row, fact, material, supplement = self.original_content_reuse_fixture()
        def reuse(value):
            return _specialty_document_content(self.task, self.evidence, self.candidates, self.ledger,
                "uspto_patent_browser", value, supplement=supplement, directory=self.path)
        for changes in ({"required_facts": ["current_status"]}, {"required_facts": ["rights_holder"]},
                        {"record_number": "US22222222B2"}, {"reading_scope": {"level": "drawings"}}):
            self.assertIsNone(reuse({**row, **changes}))
        self.add("change", change_id="READING-CHANGE", change_kind="protection",
            substantive=True, affected_event_ids=[material["event_id"]], evidence_refs=["ORIGINAL"],
            impact_reasoning="Reading applicability needs review")
        self.assertIsNone(reuse(row))
        self.fact("protection", material, outcome="unknown")
        self.assertIsNone(reuse(row))

    def setUp(self):
        fixture = base.TriageScopeTests()
        fixture.setUp()
        self.f = fixture
        self.task, self.candidate = fixture.task, fixture.candidate
        self.evidence, self.candidates, self.ledger = fixture.evidence, fixture.candidates, fixture.ledger
        self.task.update(triage_followup_revision="candidate-followup-v1",
                         triage_stage_revision="candidate-triage-stage-v1",
                         specialty_analysis_revision=REVISION)
        self.evidence["collections"]["product"] = [{"evidence_id": "E2", "kind": "product_record",
            "payload": {"product": {"title": "Synthetic strap configuration"}}}]
        self.candidate["sources"] = [{"evidence_id": "E1", "source_anchor": "import-row-1"}]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.save()
        annotation = self.f.annotation("selected")
        self.ledger["annotations"].append(annotation)
        self.save()
        handoff = record_selected_handoff(self.path, {**self.scope(),
            "annotation_id": annotation["annotation_id"], "evidence_refs": ["E1"],
            "reading_scope": {"level": "result_record", "sections": ["claims"]},
            "verification_gaps": ["current_status"], "reviewer": "agent",
            "reason": "Concrete association needs specialty review"})
        self.handoff_id = handoff["event_id"]
        self.refresh()

    def scope(self):
        return {"candidate_id": "C1", "scenario_id": "product_entry",
                "jurisdiction": "US", "right_type": "patent"}

    def save(self):
        for name, value in (("task", self.task), ("evidence", self.evidence),
                            ("normalized-candidates", self.candidates),
                            ("materiality-annotations", self.ledger), ("search-plan", {"queries": {}})):
            atomic_write_json(self.path / (name + ".json"), value)

    def refresh(self):
        self.task = load_json(self.path / "task.json")

    def add(self, kind, **fields):
        request = {**self.scope(), "kind": kind, "reviewer": "agent",
                   "reason": "Reviewed retained evidence and its actual scope", **fields}
        if kind != "intake":
            request.setdefault("intake_event_id", self.intake_id)
            request.setdefault("assessment_date", "2026-09-24")
        result = record(self.path, request)
        self.refresh()
        return result

    def intake(self):
        result = self.add("intake", selected_handoff_event_id=self.handoff_id,
                          assessment_date="2026-09-24")
        self.intake_id = result["event_id"]
        return result

    def material(self, purposes=None, **changes):
        return self.add("material", document_id="US-1", document_version="grant-v1",
            evidence_refs=["E1"], acquired_at="2026-09-01T00:00:00Z",
            source_form="official_register",
            purposes=purposes or ["identity", "territory", "status", "protection", "product", "comparison"],
            reading_locations=["page 1, identity and claim 1"], status="sufficient_for_listed_purposes",
            supported_facts=["identity", "territory", "status", "protection", "product"],
            support_reasoning="The reviewed location supports only the listed uses", **changes)

    def product_material(self):
        return self.add("material", document_id="PRODUCT-1", document_version="product-v1",
            evidence_refs=["E2"], acquired_at="2026-09-01T00:00:00Z",
            source_form="product_original", purposes=["product"],
            reading_locations=["product photo: front"], status="sufficient_for_listed_purposes",
            supported_facts=["product"], support_reasoning="Actual product configuration read")

    def fact(self, kind, material, **changes):
        values = dict(fact_id="F-" + kind, fact_kind=kind, outcome="supported",
                      raw_statement=kind + " source statement", reasoning="Checked this exact statement",
                      document_version=material["document_version"], reading_locations=["page 1"],
                      evidence_refs=material["evidence_refs"], material_event_ids=[material["event_id"]])
        if kind in {"territory", "status"}:
            values.update(right_identity="US-1", territory_basis="US record for this right")
        if kind == "status":
            values["source_checked_date"] = "2026-09-01"
            if changes.get("outcome", "supported") == "supported":
                values["resolves_handoff_gaps"] = ["current_status"]
        values.update(changes)
        return self.add("fact", **values)

    def view(self):
        return project(self.task, self.evidence, self.candidates, self.ledger)

    def waiting_gap(self, basis, **changes):
        self.task.update(product_feedback_revision="product-feedback-v1",
            product_feedback_history=[{"kind": "requested", "request_id": "PF1",
                "target_sha256": self.task.get("product_identity", {}).get("sha256")}])
        self.save()
        values = dict(gap_id="GP", question="Provide product internals", affected_judgment="product",
            action_kind="user_fact", product_feedback_request_id="PF1", minimum_action="Product teardown",
            completion_condition="Internal elements observable", existing_material_check="Photos reviewed",
            next_value="Enables all-element comparison", evidence_refs=["E2"],
            obligation_bindings=[{"reason": "SPECIALTY_FACT_REQUIRED", "fact_kind": "product",
                "basis_event_id": basis["event_id"], "reasoning": "Unknown internals need user sample"}])
        values.update(changes)
        gap = self.add("gap", **values)
        self.add("followup", gap_id=gap["gap_id"], gap_event_id=gap["event_id"], outcome="waiting",
            result_review="Available photos cannot show internals", remaining_impact="No all-element conclusion",
            next_action_or_dependency="PF1 product sample")
        return gap

    def test_exact_unknown_becomes_user_dependency_without_establishing_fact(self):
        from specialty_analysis import work_entries
        self.intake()
        material = self.product_material()
        fact = self.fact("product", material, outcome="unknown")
        self.waiting_gap(fact)
        row = next(row for row in work_entries(self.view()) if row.get("fact_kind") == "product")
        self.assertEqual((row["kind"], row["state"]), ("user_evidence", "awaiting_user"))
        self.assertEqual(row["basis_event_id"], fact["event_id"])
        self.assertNotEqual(self.view()["status"], "normal_complete")
        self.assertEqual(next(row for row in self.task["specialty_analysis_events"]
                              if row["event_id"] == fact["event_id"])["outcome"], "unknown")

    def test_structure_policy_limits_only_current_reviewed_unknown(self):
        from product_feedback import STRUCTURE_POLICY
        from specialty_analysis import work_entries
        self.intake()
        material = self.product_material()
        fact = self.fact("product", material, outcome="unknown")
        self.waiting_gap(fact)
        self.task['product_structure_policy'] = STRUCTURE_POLICY
        self.task['product_feedback_history'][0].update(fact_id='internal', direction_id='internal-search',
            source_refs=['E2'], candidate_id=self.scope()['candidate_id'], jurisdiction='US')
        self.save()
        # Real source-bound structure receipts are covered by test_product_feedback;
        # this fixture isolates the specialty unknown-to-limitation projection.
        from unittest.mock import patch
        limit = {'kind':'product_information_limit', 'state':'blocked',
                 'reason':'PRODUCT_STRUCTURE_UNAVAILABLE', 'question':'',
                 'delivery_limit':{'kind':'product_structure_unavailable'}}
        with patch('product_feedback.unavailable', return_value=self.task['product_feedback_history']), \
             patch('product_feedback.structure_limitation_entry', return_value=limit):
            row = next(row for row in work_entries(self.view()) if row.get('fact_kind') == 'product')
        self.assertEqual((row['state'], row['reason']), ('blocked', 'PRODUCT_STRUCTURE_UNAVAILABLE'))
        self.assertEqual(row['question'], '')
        self.assertEqual(row['delivery_limit']['unknown_bindings'][0]['basis_event_id'], fact['event_id'])
        self.assertEqual(fact['outcome'], 'unknown')
        # Newly received unknowns remain executable review; the old limitation cannot hide them.
        self.fact('product', material, fact_id='F-new', outcome='unknown')
        row = next(row for row in work_entries(self.view()) if row.get('fact_kind') == 'product')
        self.assertEqual(row['state'], 'awaiting_review')

    def test_new_unknown_or_resolved_feedback_requires_recheck(self):
        from specialty_analysis import work_entries
        self.intake()
        material = self.product_material()
        fact = self.fact("product", material, outcome="unknown")
        self.waiting_gap(fact)
        self.fact("product", material, fact_id="F-new", outcome="unknown")
        row = next(row for row in work_entries(self.view()) if row.get("fact_kind") == "product")
        self.assertEqual(row["state"], "awaiting_review")
        self.task["product_feedback_history"].append({"kind": "resolved", "request_id": "PF1"})
        self.assertTrue(all(row["state"] != "awaiting_user" for row in work_entries(self.view())))

    def test_binding_rejects_supported_fact_and_other_scope_basis(self):
        self.intake()
        material = self.product_material()
        fact = self.fact("product", material)
        with self.assertRaisesRegex(ValueError, "BASIS_NOT_CURRENT_UNKNOWN"):
            self.waiting_gap(fact)

    def test_distinct_specialty_obligations_have_unique_stable_ids(self):
        from specialty_analysis import work_entries
        self.intake()
        rows = work_entries(self.view())
        ids = [row["obligation_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for scope in self.view()["scopes"]:
            for blocker in scope["blockers"]:
                blocker["state"] = "waiting"
        self.assertEqual(ids, [row["obligation_id"] for row in work_entries(self.view())])

    def test_source_limit_binds_only_valid_current_proof_and_reviewed_unknown(self):
        from unittest.mock import patch
        from specialty_analysis import work_entries
        self.intake()
        material = self.material()
        fact = self.fact("status", material, outcome="unknown")
        query = {**self.scope(), "query_id": "Q-STATUS", "required_facts": ["current_status"]}
        plan = {"queries": {"registry": [query]}}
        atomic_write_json(self.path / "search-plan.json", plan)
        gap = self.add("gap", gap_id="GS", question="Current official state?", affected_judgment="status",
            action_kind="verify_known_right", source_query_id="Q-STATUS", minimum_action="Read official status",
            completion_condition="Current state supported", existing_material_check="Historical record read",
            next_value="Current force may change assessment", evidence_refs=["E1"],
            obligation_bindings=[{"reason": "SPECIALTY_FACT_REQUIRED", "fact_kind": "status",
                "basis_event_id": fact["event_id"], "reasoning": "Only this official state remains unknown"}])
        self.add("followup", gap_id="GS", gap_event_id=gap["event_id"], outcome="limited",
            result_review="Official route constrained", remaining_impact="Status unknown",
            next_action_or_dependency="Restore official access", limit_evidence="Bound source proof",
            limit_kind="source_unavailable_with_no_recovery", restore_condition="Official source restored")
        source = {**self.scope(), "provider": "registry", "kind": "source_lookup", "state": "blocked",
            "query_id": "Q-STATUS", "reason": "SOURCE_LIMIT", "delivery_limit": {"kind": "source_constraint"}}
        def projected():
            return work_entries(project(self.task, self.evidence, self.candidates, self.ledger,
                plan=plan, capabilities={}, task_dir=self.path, source_work=[source]))
        with patch("necessary_completion._delivery_limit_valid", return_value=False):
            self.assertEqual(next(row for row in projected() if row.get("fact_kind") == "status")["state"], "awaiting_review")
        with patch("necessary_completion._delivery_limit_valid", return_value=True) as validate:
            row = next(row for row in projected() if row.get("fact_kind") == "status")
            self.assertEqual((row["state"], row["reason"]), ("blocked", "SOURCE_LIMIT"))
            self.assertEqual(row["specialty_reason"], "SPECIALTY_FACT_REQUIRED")
            self.assertEqual(row["delivery_limit"], source["delivery_limit"])
            validate.assert_called()
            source["state"] = "ready"
            self.assertEqual(next(row for row in projected() if row.get("fact_kind") == "status")["state"], "awaiting_review")
            source["state"] = "blocked"
            plan["queries"]["registry"][0]["q"] = "changed request"
            self.assertEqual(next(row for row in projected() if row.get("fact_kind") == "status")["state"], "awaiting_review")

    def test_official_dependency_cannot_hide_product_or_unrelated_right_fact(self):
        from specialty_analysis import _dependency_matches
        gap = {"action_kind": "verify_known_right", "source_required_facts": ["current_status"]}
        binding = {"reason": "SPECIALTY_FACT_REQUIRED"}
        self.assertTrue(_dependency_matches(gap, binding, {"fact_kind": "status"}))
        self.assertFalse(_dependency_matches(gap, binding, {"fact_kind": "product"}))
        self.assertFalse(_dependency_matches(gap, binding, {"fact_kind": "protection"}))
        self.assertFalse(_dependency_matches(gap, {"reason": "SPECIALTY_COMPARISON_UNKNOWN"}, {}))
        self.assertFalse(_dependency_matches({"action_kind": "verify_known_right"}, binding, {"fact_kind": "status"}))

    def test_user_product_request_cannot_defer_official_status(self):
        self.intake()
        material = self.material()
        fact = self.fact("status", material, outcome="unknown")
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_FACT_MISMATCH"):
            self.waiting_gap(fact, obligation_bindings=[{"reason": "SPECIALTY_FACT_REQUIRED",
                "fact_kind": "status", "basis_event_id": fact["event_id"], "reasoning": "Unrelated request"}])

    def test_intake_requires_current_handoff_and_fixed_assessment_date(self):
        with self.assertRaisesRegex(ValueError, "HANDOFF"):
            self.add("intake", selected_handoff_event_id="wrong", assessment_date="2026-09-24")
        self.intake()
        with self.assertRaisesRegex(ValueError, "ASSESSMENT_DATE_CHANGED"):
            self.add("material", intake_event_id=self.intake_id, assessment_date="2026-09-25",
                document_id="US-1", document_version="grant-v1", evidence_refs=["E1"],
                acquired_at="2026-09-01T00:00:00Z", source_form="official_register", purposes=["status"],
                reading_locations=["page 1"], status="read", support_reasoning="Read status")

    def test_specialty_work_has_a_concrete_recorder(self):
        from advance_work import action_card
        from specialty_analysis import work_entries
        row = work_entries(self.view())[0]
        card = action_card(self.path, row)
        self.assertEqual(card["action"], "review_patent_or_design_specialty")
        self.assertTrue(card["recorder"].endswith("record_specialty_analysis.py"))

    def test_pending_known_right_source_keeps_specialty_scope_open(self):
        source = {**self.scope(), "kind": "source_lookup", "state": "ready",
                  "query_id": "Q-STATUS"}
        view = project(self.task, self.evidence, self.candidates, self.ledger,
                       source_work=[source])
        self.assertIn("SPECIALTY_SOURCE_PENDING", [row["reason"]
            for row in view["scopes"][0]["blockers"]])

    def test_new_assessment_round_preserves_old_material_time_and_rechecks_scope(self):
        first = self.intake()
        original = self.material()
        with self.assertRaisesRegex(ValueError, "INTAKE_CHANGE_REQUIRES_REVIEW"):
            self.add("intake", selected_handoff_event_id=self.handoff_id,
                     assessment_date="2026-09-25")
        second = self.add("intake", selected_handoff_event_id=self.handoff_id,
                          assessment_date="2026-09-25", prior_intake_event_id=first["event_id"],
                          new_round_reasoning="User changed the assessment date")
        self.intake_id = second["event_id"]
        reused = self.add("material", assessment_date="2026-09-25", document_id="US-1",
            document_version="grant-v1", evidence_refs=["E1"],
            acquired_at="2026-09-01T00:00:00Z", source_form="official_register",
            purposes=["identity", "territory", "status"],
            reading_locations=["page 1, identity and claim 1"],
            status="read", support_reasoning="Reused the earlier actual reading",
            reuse_from_event_id=original["event_id"],
            reuse_applicability_reasoning="Document identity and content are unchanged; status sufficiency is rechecked")
        self.assertEqual(reused["acquired_at"], original["acquired_at"])
        self.assertEqual(self.view()["status"], "in_progress")

    def test_new_round_cannot_resolve_old_round_conflict(self):
        first = self.intake()
        old_material = self.material()
        conflict = self.fact("status", old_material, outcome="conflicted",
            conflicting_evidence_refs=["E1"], conflict_explanation="Old round conflict")
        second = self.add("intake", selected_handoff_event_id=self.handoff_id,
            assessment_date="2026-09-25", prior_intake_event_id=first["event_id"],
            new_round_reasoning="Assessment date changed")
        self.intake_id = second["event_id"]
        new_material = self.material(assessment_date="2026-09-25")
        with self.assertRaisesRegex(ValueError, "CONFLICT_RESOLUTION_INVALID"):
            self.fact("status", new_material, assessment_date="2026-09-25",
                resolves_fact_event_ids=[conflict["event_id"]],
                adoption_reasoning="Old-round conflict cannot be reused")

    def test_download_only_cannot_support_status_or_completion(self):
        self.intake()
        material = self.add("material", document_id="US-1", document_version="grant-v1",
            evidence_refs=["E1"], acquired_at="2026-09-01T00:00:00Z",
            source_form="official_register",
            purposes=["status"], reading_locations=[], status="acquired",
            support_reasoning="Downloaded only")
        with self.assertRaisesRegex(ValueError, "PURPOSE_READING_REQUIRED"):
            self.fact("status", material)
        with self.assertRaisesRegex(ValueError, "BATCH_UNREAD_MATERIAL_CANNOT_COMPLETE"):
            self.add("batch", batch_id="import:E1", received_evidence_refs=["E1"],
                     disposition_by_evidence_ref={"E1": "Retained page still needs reading"},
                     received_material_event_ids=[material["event_id"]],
                     processed_material_event_ids=[material["event_id"]],
                     disposition_reasoning="Downloaded but not read")
        self.assertEqual(self.view()["status"], "in_progress")

    def test_summary_cannot_be_used_as_unchecked_decisive_status(self):
        self.intake()
        with self.assertRaisesRegex(ValueError, "ORIGINAL_LOCATION_REQUIRED"):
            self.add("material", document_id="US-1", document_version="summary-v1",
                evidence_refs=["E1"], acquired_at="2026-09-01T00:00:00Z",
                source_form="summary", purposes=["identity", "status"], reading_locations=["summary"],
                original_evidence_refs=["E1"],
                status="sufficient_for_listed_purposes", supported_facts=["status"],
                support_reasoning="Summary says expired")
        summary = self.add("material", document_id="US-1", document_version="summary-v1",
            evidence_refs=["E1"], acquired_at="2026-09-01T00:00:00Z",
            source_form="summary", purposes=["identity", "status"], reading_locations=["summary"],
            original_evidence_refs=["E1"], original_locations=["original page 1"],
            original_verified=True, status="sufficient_for_listed_purposes",
            supported_facts=["identity", "status"], support_reasoning="Original content checked")
        identity = self.fact("identity", summary, document_version="summary-v1")
        self.assertEqual(identity["fact_kind"], "identity")
        # A status summary, even when its wording is checked, is not an
        # official status event for an action-level comparison exemption.
        with self.assertRaisesRegex(ValueError, "OFFICIAL_STATUS_OR_TERRITORY_REQUIRED"):
            self.fact("status", summary, document_version="summary-v1",
                excludes_action_ids=["all_comparisons"], exclusion_reasoning="Expired",
                assessment_applicability_reasoning="Event predates assessment")

    def test_exemption_closes_only_comparison_after_supported_facts(self):
        self.intake()
        material = self.material()
        facts = [self.fact(kind, material, **({"excludes_action_ids": ["all_comparisons"],
            "exclusion_reasoning": "Expiry prevents the specified comparison at this time",
            "assessment_applicability_reasoning": "Expiry event precedes the assessment date"}
            if kind == "status" else {})) for kind in ("identity", "territory", "status")]
        without_decisive = [row["event_id"] for row in facts if row["fact_kind"] != "status"]
        with self.assertRaisesRegex(ValueError, "BASIS_INCOMPLETE"):
            self.add("exemption", action_id="all_comparisons", fact_event_ids=without_decisive,
                right_identity="US-1", territory_basis="US record", scenario_basis="product_entry",
                reasoning="Summary suggests expiry", remaining_obligations=[])
        exemption = self.add("exemption", action_id="all_comparisons", fact_event_ids=[row["event_id"] for row in facts],
            right_identity="US-1", territory_basis="US record", scenario_basis="product_entry",
            reasoning="This exact right expired before assessment date", remaining_obligations=[])
        self.assertEqual(self.view()["status"], "in_progress")
        self.add("batch", batch_id="import:E1", received_evidence_refs=["E1"],
                 disposition_by_evidence_ref={"E1": "Reviewed for this status question"},
                 received_material_event_ids=[material["event_id"]],
                 processed_material_event_ids=[material["event_id"]],
                 disposition_reasoning="Reviewed the retained page for foundational facts")
        self.assertEqual(self.view()["status"], "normal_complete")
        self.add("handoff", destination="09", result_event_ids=[exemption["event_id"]],
                 handoff_reasoning="Review this factual exemption without assigning risk here")
        self.assertEqual(self.view()["scopes"][0]["handoffs"][0]["currently_usable_event_ids"],
                         [exemption["event_id"]])

    def test_conflict_blocks_exemption_until_explicit_resolution(self):
        self.intake()
        material = self.material()
        facts = [self.fact(kind, material, **({"excludes_action_ids": ["all_comparisons"],
            "exclusion_reasoning": "Expiry prevents the specified comparison at this time",
            "assessment_applicability_reasoning": "Expiry event precedes the assessment date"}
            if kind == "status" else {})) for kind in ("identity", "territory", "status")]
        conflict = self.fact("status", material, fact_id="F-conflict", outcome="conflicted",
            conflicting_evidence_refs=["E1"], conflict_explanation="Two status statements differ")
        exempt = dict(action_id="all_comparisons", fact_event_ids=[row["event_id"] for row in facts],
            right_identity="US-1", territory_basis="US record", scenario_basis="product_entry",
            reasoning="Specific expiry event", remaining_obligations=[])
        with self.assertRaisesRegex(ValueError, "CONFLICT_OPEN"):
            self.add("exemption", **exempt)
        self.fact("status", material, fact_id="F-resolved",
                  resolves_fact_event_ids=[conflict["event_id"]], adoption_reasoning="Verified event chronology")
        self.add("exemption", **exempt)

    def test_all_claim_elements_and_unknown_remain_visible(self):
        self.intake()
        material = self.material()
        for kind in ("identity", "territory", "status", "protection"):
            self.fact(kind, material)
        self.fact("product", self.product_material())
        inventory = self.add("inventory", document_id="US-1", document_version="grant-v1",
            evidence_refs=["E1"], material_event_ids=[material["event_id"]],
            reading_locations=["claims 1-3"],
            completeness_reasoning="All independent claims identified", units=[
                {"unit_id": "claim-1", "kind": "independent_claim", "implementation_id": "sale-configuration",
                 "product_configuration": "sold strap", "original_location": "claim 1",
                 "necessary_elements": ["A", "B", "C"]}])
        def element(name, result):
            return {"element_id": name, "result": result, "claim_quote": "claim phrase " + name,
                    "original_location": "claim 1", "product_fact": "strap feature " + name,
                    "reasoning": "Compared the retained original and product",
                    "claim_evidence_refs": ["E1"],
                    "product_evidence_refs": [] if result == "unknown" else ["E1"]}
        common = dict(inventory_event_id=inventory["event_id"], unit_id="claim-1",
                      disposition="compared", evidence_refs=["E1"], reasoning="Element comparison")
        with self.assertRaisesRegex(ValueError, "ALL_NECESSARY_ELEMENTS_REQUIRED"):
            self.add("comparison", **common, elements=[element("A", "corresponds"), element("B", "differs")])
        self.add("comparison", **common, elements=[element("A", "corresponds"),
            element("B", "differs"), element("C", "unknown")])
        self.add("batch", batch_id="import:E1", received_evidence_refs=["E1"],
                 disposition_by_evidence_ref={"E1": "Original claims reviewed"},
                 received_material_event_ids=[material["event_id"]],
                 processed_material_event_ids=[material["event_id"]],
                 disposition_reasoning="Claims read and compared")
        self.assertIn("SPECIALTY_COMPARISON_UNKNOWN", [row["reason"] for row in self.view()["scopes"][0]["blockers"]])

    def test_gap_limit_keeps_stage_limited_only_when_other_work_complete(self):
        self.intake()
        material = self.material()
        facts = [self.fact(kind, material, **({"excludes_action_ids": ["all_comparisons"],
            "exclusion_reasoning": "Expiry prevents the specified comparison at this time",
            "assessment_applicability_reasoning": "Expiry event precedes the assessment date"}
            if kind == "status" else {})) for kind in ("identity", "territory", "status")]
        self.add("exemption", action_id="all_comparisons", fact_event_ids=[row["event_id"] for row in facts],
                 right_identity="US-1", territory_basis="US", scenario_basis="product_entry",
                 reasoning="Documented terminal status", remaining_obligations=[])
        self.add("batch", batch_id="import:E1", received_evidence_refs=["E1"],
                 disposition_by_evidence_ref={"E1": "Reviewed foundational fact"},
                 received_material_event_ids=[material["event_id"]],
                 processed_material_event_ids=[material["event_id"]], disposition_reasoning="Reviewed")
        gap = self.add("gap", gap_id="G1", question="Confirm effective event date",
                 affected_judgment="status", action_kind="read_existing",
                 minimum_action="Read retained event page",
                 completion_condition="Event date established", existing_material_check="Existing page read",
                 next_value="Might change the exemption", evidence_refs=["E1"])
        self.assertEqual(self.view()["status"], "in_progress")
        self.add("followup", gap_id="G1", gap_event_id=gap["event_id"], outcome="limited",
                 result_review="No obtainable event record in present scope", remaining_impact="Status date uncertain",
                 next_action_or_dependency="Restore official access", limit_evidence="Access prohibited",
                 limit_kind="no_lawful_route",
                 restore_condition="Official access returns", evidence_refs=[])
        self.assertEqual(self.view()["status"], "limited")

    def test_resolved_gap_needs_new_judgment_after_gap(self):
        self.intake()
        material = self.material()
        self.fact("status", material)
        gap = self.add("gap", gap_id="G1", question="Is this state current?",
                 affected_judgment="status", action_kind="read_existing",
                 minimum_action="Read retained event page",
                 completion_condition="Current status established", existing_material_check="Older page checked",
                 next_value="Could resolve status", evidence_refs=["E1"])
        common = dict(gap_id="G1", gap_event_id=gap["event_id"], outcome="resolved",
                      result_review="New event supports current status", remaining_impact="None",
                      evidence_refs=["E1"])
        with self.assertRaisesRegex(ValueError, "RESOLVED_JUDGMENT_REQUIRED"):
            self.add("followup", **common, resolved_event_ids=[])
        updated = self.fact("status", material, fact_id="F-updated")
        self.add("followup", **common, resolved_event_ids=[updated["event_id"]])

    def test_material_change_requires_exact_impact_review(self):
        self.intake()
        material = self.material()
        status = self.fact("status", material)
        change = self.add("change", change_id="CH-1", change_kind="status_event",
            substantive=True, impact_reasoning="New event may alter current status",
            affected_event_ids=[status["event_id"]], evidence_refs=["E1"])
        current = next(row for row in self.view()["scopes"][0]["results"]
                       if row["event_id"] == status["event_id"])
        self.assertFalse(current["currently_usable"])
        with self.assertRaisesRegex(ValueError, "IMPACT_REVIEW_INCOMPLETE"):
            self.add("change_review", change_event_id=change["event_id"], outcome="continues",
                recheck_reasoning="Rechecked event meaning", evidence_refs=["E1"],
                reviewed_affected_event_ids=[])
        self.add("change_review", change_event_id=change["event_id"], outcome="continues",
            recheck_reasoning="Rechecked event meaning", evidence_refs=["E1"],
            reviewed_affected_event_ids=[status["event_id"]])

    def test_changed_status_does_not_reuse_superseded_supported_fact(self):
        self.intake()
        material = self.material()
        old = self.fact("status", material)
        change = self.add("change", change_id="CH-2", change_kind="status_event",
            substantive=True, impact_reasoning="New event may change the prior status",
            affected_event_ids=[old["event_id"]], evidence_refs=["E1"])
        current = self.fact("status", material, fact_id="F-new-status", outcome="unknown")
        with self.assertRaisesRegex(ValueError, "REPLACEMENT_REQUIRED"):
            self.add("change_review", change_event_id=change["event_id"], outcome="changed",
                recheck_reasoning="New event leaves status unknown", evidence_refs=["E1"],
                reviewed_affected_event_ids=[old["event_id"]], replacement_by_affected={})
        self.add("change_review", change_event_id=change["event_id"], outcome="changed",
            recheck_reasoning="New event leaves status unknown", evidence_refs=["E1"],
            reviewed_affected_event_ids=[old["event_id"]],
            replacement_by_affected={old["event_id"]: [current["event_id"]]})
        self.assertIn({"reason": "SPECIALTY_FACT_REQUIRED", "fact_kind": "status"},
                      self.view()["scopes"][0]["blockers"])

    def test_comparison_cannot_reuse_superseded_unit_exemption(self):
        self.intake()
        material = self.material()
        identity = self.fact("identity", material)
        decisive = self.fact("status", material, excludes_action_ids=["claim-1"],
            exclusion_reasoning="Specified action excluded by status event",
            assessment_applicability_reasoning="Event precedes assessment")
        inventory = self.add("inventory", document_id="US-1", document_version="grant-v1",
            evidence_refs=["E1"], material_event_ids=[material["event_id"]],
            reading_locations=["claim 1"], completeness_reasoning="One independent claim", units=[
                {"unit_id": "claim-1", "kind": "independent_claim",
                 "implementation_id": "sale-configuration", "product_configuration": "sold strap",
                 "original_location": "claim 1", "necessary_elements": ["A"]}])
        exemption_args = dict(action_id="claim-1",
            fact_event_ids=[identity["event_id"], decisive["event_id"]],
            right_identity="US-1", territory_basis="US record",
            scenario_basis="product_entry", reasoning="Action-specific status exclusion",
            remaining_obligations=[])
        old = self.add("exemption", **exemption_args)
        self.add("comparison", inventory_event_id=inventory["event_id"], unit_id="claim-1",
            disposition="exempt", exemption_event_id=old["event_id"])
        change = self.add("change", change_id="CH-exemption", change_kind="status_event",
            substantive=True, impact_reasoning="Exemption basis changed",
            affected_event_ids=[old["event_id"]], evidence_refs=["E1"])
        replacement = self.add("exemption", **exemption_args)
        self.add("change_review", change_event_id=change["event_id"], outcome="changed",
            recheck_reasoning="New exemption assessed", evidence_refs=["E1"],
            reviewed_affected_event_ids=[old["event_id"]],
            replacement_by_affected={old["event_id"]: [replacement["event_id"]]})
        self.assertIn({"reason": "SPECIALTY_UNIT_EXEMPTION_STALE", "unit_id": "claim-1"},
                      self.view()["scopes"][0]["blockers"])

    def test_comparison_cannot_import_previous_round_exemption(self):
        first = self.intake()
        old_material = self.material()
        identity = self.fact("identity", old_material)
        decisive = self.fact("status", old_material, excludes_action_ids=["claim-1"],
            exclusion_reasoning="Old round status excluded action",
            assessment_applicability_reasoning="Old round assessment only")
        exemption = self.add("exemption", action_id="claim-1",
            fact_event_ids=[identity["event_id"], decisive["event_id"]],
            right_identity="US-1", territory_basis="US record",
            scenario_basis="product_entry", reasoning="Old round exemption",
            remaining_obligations=[])
        second = self.add("intake", selected_handoff_event_id=self.handoff_id,
            assessment_date="2026-09-25", prior_intake_event_id=first["event_id"],
            new_round_reasoning="Assessment date changed")
        self.intake_id = second["event_id"]
        new_material = self.material(assessment_date="2026-09-25")
        inventory = self.add("inventory", assessment_date="2026-09-25",
            document_id="US-1", document_version="grant-v1", evidence_refs=["E1"],
            material_event_ids=[new_material["event_id"]], reading_locations=["claim 1"],
            completeness_reasoning="One independent claim", units=[{
                "unit_id": "claim-1", "kind": "independent_claim",
                "implementation_id": "sale-configuration", "product_configuration": "sold strap",
                "original_location": "claim 1", "necessary_elements": ["A"]}])
        with self.assertRaisesRegex(ValueError, "UNIT_EXEMPTION_REQUIRED"):
            self.add("comparison", assessment_date="2026-09-25",
                inventory_event_id=inventory["event_id"], unit_id="claim-1",
                disposition="exempt", exemption_event_id=exemption["event_id"])

    def test_design_requires_all_views_and_overall_relationship(self):
        fixture = base.TriageScopeTests()
        fixture.setUp()
        fixture.candidate["right_type"] = "design"
        fixture.candidate["sources"] = [{"evidence_id": "E1", "source_anchor": "design-row"}]
        fixture.task.update(triage_followup_revision="candidate-followup-v1",
                            triage_stage_revision="candidate-triage-stage-v1",
                            specialty_analysis_revision=REVISION)
        row = fixture.annotation("selected", candidate_relation=fixture.basis(directions=["strap-appearance"]))
        fixture.ledger["annotations"].append(row)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            for name, value in (("task", fixture.task), ("evidence", fixture.evidence),
                                ("normalized-candidates", fixture.candidates),
                                ("materiality-annotations", fixture.ledger), ("search-plan", {"queries": {}})):
                atomic_write_json(path / (name + ".json"), value)
            scope = {"candidate_id": "C1", "scenario_id": "product_entry",
                     "jurisdiction": "US", "right_type": "design"}
            handoff = record_selected_handoff(path, {**scope, "annotation_id": row["annotation_id"],
                "evidence_refs": ["E1"], "reading_scope": {"level": "result_record", "sections": ["figures"]},
                "verification_gaps": [], "reviewer": "agent", "reason": "Appearance association"})
            common = {**scope, "reviewer": "agent", "reason": "Reviewed original and product"}
            intake = record(path, {**common, "kind": "intake",
                "selected_handoff_event_id": handoff["event_id"], "assessment_date": "2026-09-24"})
            common.update(intake_event_id=intake["event_id"], assessment_date="2026-09-24")
            material = record(path, {**common, "kind": "material", "document_id": "USD1",
                "document_version": "registered-v1", "evidence_refs": ["E1"],
                "acquired_at": "2026-09-01T00:00:00Z", "source_form": "original_document",
                "purposes": ["protection"],
                "reading_locations": ["front/back drawings"], "status": "sufficient_for_listed_purposes",
                "supported_facts": ["protection"], "support_reasoning": "Read drawings"})
            inventory = record(path, {**common, "kind": "inventory", "document_id": "USD1",
                "document_version": "registered-v1", "evidence_refs": ["E1"],
                "material_event_ids": [material["event_id"]], "reading_locations": ["front/back drawings"],
                "completeness_reasoning": "One actual registered design", "units": [{
                    "unit_id": "design-1", "kind": "design", "design_id": "USD1-1",
                    "product_configuration": "sold strap", "product_state": "folded",
                    "original_location": "drawings", "necessary_views": ["front", "back"]}]})
            view = {"view_id": "front", "result": "differs", "reasoning": "Front contour differs",
                    "right_evidence_refs": ["E1"], "product_evidence_refs": ["E1"],
                    "right_location": "registered drawing front", "product_location": "front photo"}
            comp = {**common, "kind": "comparison", "inventory_event_id": inventory["event_id"],
                    "unit_id": "design-1", "disposition": "compared", "evidence_refs": ["E1"],
                    "reasoning": "Compared known views", "registered_basis": "registered",
                    "design_scope_basis": "Read drawing key", "overall_visual_relationship": "Front differs; back unknown",
                    "design_scope_parts": [{"part_id": "solid-outline", "treatment": "claimed",
                        "interpretation_basis": "Drawing key and applicable scope rule", "evidence_refs": ["E1"]}],
                    "similarities": [], "differences": ["front contour"], "unknowns": ["back"],
                    "perspective_limitations": "Back product view unavailable"}
            with self.assertRaisesRegex(ValueError, "ALL_NECESSARY_VIEWS_REQUIRED"):
                record(path, {**comp, "views": [view]})
            record(path, {**comp, "views": [view, {"view_id": "back", "result": "unknown",
                "reasoning": "No matching product view", "right_evidence_refs": [],
                "product_evidence_refs": []}]})
            task = load_json(path / "task.json")
            stage = project(task, fixture.evidence, fixture.candidates, fixture.ledger)
            self.assertIn("SPECIALTY_COMPARISON_UNKNOWN", [item["reason"]
                for item in stage["scopes"][0]["blockers"]])
            record(path, {**comp, "views": [view, {"view_id": "back", "result": "corresponds",
                "reasoning": "Matching back contour", "right_evidence_refs": ["E1"],
                "product_evidence_refs": ["E1"], "right_location": "back drawing",
                "product_location": "back photo"}],
                "design_scope_parts": [{"part_id": "broken-outline", "treatment": "unknown",
                    "interpretation_basis": "Applicable broken-line rule not yet verified",
                    "evidence_refs": ["E1"]}]})
            stage = project(load_json(path / "task.json"), fixture.evidence,
                            fixture.candidates, fixture.ledger)
            self.assertIn("SPECIALTY_DESIGN_SCOPE_UNKNOWN", [item["reason"]
                for item in stage["scopes"][0]["blockers"]])

    def test_unregistered_design_keeps_unknown_condition_open(self):
        fixture = base.TriageScopeTests()
        fixture.setUp()
        fixture.candidate["right_type"] = "unregistered_design"
        fixture.candidate["sources"] = [{"evidence_id": "E1", "source_anchor": "design-clue"}]
        fixture.task.update(triage_followup_revision="candidate-followup-v1",
                            triage_stage_revision="candidate-triage-stage-v1",
                            specialty_analysis_revision=REVISION)
        fixture.task["product_scope"]["objects"][0]["right_types"].append("unregistered_design")
        fixture.task["product_scope"]["directions"].append({"direction_id": "strap-unregistered",
            "scenario_id": "product_entry", "right_type": "unregistered_design",
            "object_ids": ["strap"], "fact_ids": []})
        row = fixture.annotation("selected", candidate_relation=fixture.basis(directions=["strap-unregistered"]))
        fixture.ledger["annotations"].append(row)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            for name, value in (("task", fixture.task), ("evidence", fixture.evidence),
                                ("normalized-candidates", fixture.candidates),
                                ("materiality-annotations", fixture.ledger), ("search-plan", {"queries": {}})):
                atomic_write_json(path / (name + ".json"), value)
            scope = {"candidate_id": "C1", "scenario_id": "product_entry",
                     "jurisdiction": "US", "right_type": "unregistered_design"}
            handoff = record_selected_handoff(path, {**scope, "annotation_id": row["annotation_id"],
                "evidence_refs": ["E1"], "reading_scope": {"level": "result_record", "sections": ["design"]},
                "verification_gaps": [], "reviewer": "agent", "reason": "Appearance association"})
            common = {**scope, "reviewer": "agent", "reason": "Reviewed applicable condition"}
            intake = record(path, {**common, "kind": "intake",
                "selected_handoff_event_id": handoff["event_id"], "assessment_date": "2026-09-24"})
            common.update(intake_event_id=intake["event_id"], assessment_date="2026-09-24")
            material = record(path, {**common, "kind": "material", "document_id": "RULE-US",
                "document_version": "rule-v1", "evidence_refs": ["E1"],
                "acquired_at": "2026-09-01T00:00:00Z", "source_form": "legal_rule",
                "purposes": ["legal_conditions"], "reading_locations": ["rule section 1"],
                "status": "sufficient_for_listed_purposes", "supported_facts": ["legal_conditions"],
                "support_reasoning": "Read condition text"})
            fact = {**common, "kind": "fact", "fact_id": "F-rules",
                "fact_kind": "legal_conditions", "outcome": "supported",
                "raw_statement": "A specific condition needs factual proof",
                "reasoning": "Rule applies to this design", "document_version": "rule-v1",
                "reading_locations": ["rule section 1"], "evidence_refs": ["E1"],
                "material_event_ids": [material["event_id"]], "rules_basis": "US rule for this claimed right",
                "conditions": [{"condition_id": "disclosure", "outcome": "unknown",
                    "applicability_reasoning": "Earlier page has no verified historical design image",
                    "evidence_refs": ["E1"], "design_version": "version-a",
                    "disclosed_content": "Current image only", "date_basis": "page label unverified",
                    "geographic_basis": "US relation unknown"}]}
            record(path, fact)
            stage = project(load_json(path / "task.json"), fixture.evidence,
                            fixture.candidates, fixture.ledger)
            self.assertIn("SPECIALTY_UNREGISTERED_CONDITION_PENDING", [item["reason"]
                for item in stage["scopes"][0]["blockers"]])


if __name__ == "__main__":
    unittest.main()
