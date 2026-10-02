"""Offline regression coverage for final-only reviews and immutable unit reuse."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import sha256_json
import final_review as final


STATEMENT = {"overall": "The selected product judgment remains supported.",
    "scope": "US patent and copyright discovery were reviewed.",
    "limitations": "No additional unresolved facts in the reviewed scope."}


def receipt(rows, material, session="first", previous=None, reuse=None):
    payload = {"final_review_statement": deepcopy(STATEMENT), "reused_unit_ids": reuse or []}
    assessments, binding = final.prepare_rows(payload, rows, material, previous)
    digest = sha256_json(material)
    return {"reviewer": session, "assessments": assessments, "review_context": {
        "session_id": session, "evidence_digest": digest, "first_review_visible": False,
        "execution": {"agent_id": session, "run_id": "run-" + session,
            "input_digest": digest, "assessment_digest": sha256_json(assessments),
            "final_review_digest": sha256_json(binding)},
        "final_review": binding}}


class FinalReviewTests(unittest.TestCase):
    def setUp(self):
        self.task = {"review_policy_revision": final.REVISION, "task_id": "T1",
            "product": {"title": "Product", "structure": "hinged"}, "target_jurisdictions": ["US", "GB"]}
        self.rows = [{"scenario_id": "S1", "jurisdiction": "US", "right_type": "patent",
            "candidate_id": key, "reasoning": "Bound comparison", "evidence_refs": ["E-" + key]}
            for key in ("P1", "P2")]
        self.evidence = {"evidence": [{"evidence_id": "E-" + key, "candidate_id": key,
            "jurisdiction": "US", "right_type": "patent", "payload": {"claim": key},
            "path": "/old/" + key, "sha256": key * 32, "checked_at": "2026-09-28T00:00:00Z"}
            for key in ("P1", "P2")]}
        self.candidates = {"api": [{"candidate_id": key, "jurisdiction": "US", "right_type": "patent",
            "title": key} for key in ("P1", "P2")]}
        self.plan = {"queries": {"api": [{"query_id": "Q1", "jurisdiction": "US", "right_type": "patent", "query": "hinge"}]}}

    def material(self):
        return final.inputs(self.evidence, self.candidates, {}, self.plan, self.task)

    def test_explicit_partial_is_only_an_immutable_unit_reuse_source(self):
        from assessment_estimate import _validate_review
        material = self.material()
        partial = receipt(self.rows[:1], material, session='original-slot2')
        partial['registration_scope'] = 'validated_unit_subset'
        before = deepcopy(partial)
        key = final.unit_id(self.rows[0])
        self.assertEqual(final.reuse_options(partial, material)['reusable_unit_ids'], [key])
        current = receipt(self.rows[1:], material, session='correction-slot2',
                          previous=partial, reuse=[key])
        final.validate_envelope(current, material)
        self.assertEqual(partial, before)
        self.assertEqual(current['assessments'][1], self.rows[0])
        with self.assertRaisesRegex(ValueError, 'FINAL_REVIEW_PARTIAL_NOT_PUBLISHABLE'):
            _validate_review(partial, 'D', set(), {}, {'US'}, {})
        current['assessments'][1]['reasoning'] = 'host rewritten'
        with self.assertRaises(ValueError):
            final.validate_envelope(current, material)

    def test_administrative_progress_dates_and_hashed_paths_do_not_reopen(self):
        before = self.material()
        self.evidence["history"] = [{"message": "finished", "created_at": "later"}]
        self.evidence["review_progress_events"] = [{"state": "complete"}]
        self.evidence["evidence"][0]["path"] = "/new/P1"
        self.plan.update(generated_at="later", updated_at="later")
        self.plan["queries"]["api"][0]["priority"] = 10
        self.assertEqual(self.material(), before)

    def test_real_query_and_content_changes_invalidate(self):
        before = self.material()
        self.plan["queries"]["api"][0]["query"] = "latch"
        self.assertNotEqual(self.material(), before)
        before = self.material()
        self.evidence["evidence"][0]["payload"]["claim"] = "new claim"
        self.assertNotEqual(self.material(), before)

    def test_rating_policy_change_reopens_units_without_rebinding_old_receipt(self):
        self.task['assessment_revision'] = 'partial-evidence-v2'
        prior = receipt(self.rows, self.material())
        original = deepcopy(prior)
        self.task['assessment_revision'] = 'known-findings-risk-v1'
        options = final.reuse_options(prior, self.material())
        self.assertEqual(set(options['changed_unit_ids']), {final.unit_id(row) for row in self.rows})
        self.assertEqual(options['reusable_unit_ids'], [])
        self.assertEqual(prior, original)
        with self.assertRaisesRegex(ValueError, 'REUSED_UNIT_CHANGED'):
            receipt([], self.material(), 'next', prior, [final.unit_id(self.rows[0])])

    def test_operating_scope_grade_preserves_pending_candidate_in_final_projection(self):
        assessment = {'final_review': {'revision': final.REVISION, 'status': 'complete',
            'evidence_digest': 'D', 'review_sha256s': ['A', 'B']}, 'generated_at': '2026-09-29T00:00:00Z',
            'status': 'incomplete', 'assessments': [{**self.rows[0], 'risk': None,
                'assessment_status': 'pending', 'aggregation_included': False}],
            'overall': {'risk': '低', 'confidence': '低', 'screening_grade': True},
            'known_findings': {'revision': 'known-findings-risk-v1', 'by_scope': [{
                'scenario_id': 'S1', 'jurisdiction': 'US', 'right_type': 'patent',
                'risk': '低', 'screening_grade': True, 'pending_count': 1, 'drivers': []}]}}
        stage = final.project_stage({'product': {'product_version': 1}}, assessment)
        self.assertEqual(stage['stage_risk']['by_scope'][0]['display_grade'], '低')
        self.assertEqual(stage['stage_risk']['judgments'][0]['verification_status'], 'pending')
        self.assertIsNone(stage['stage_risk']['judgments'][0]['stage_risk'])
        self.assertEqual(stage['stage_risk']['overall']['verification_status'], 'pending')

    def test_only_query_queue_order_is_administrative(self):
        self.plan['queries']['api'].extend([{'query_id': 'Q2', 'query': 'strap'},
            {'query_id': 'Q2', 'query': 'strap'}])
        before = self.material()
        self.plan['queries']['api'].reverse()
        self.assertEqual(self.material(), before)
        self.plan['queries']['api'].pop(0)
        self.assertNotEqual(self.material(), before)  # Do not silently deduplicate.
        self.evidence['evidence'][0]['payload']['claims'] = ['one', 'two']
        before = self.material()
        self.evidence['evidence'][0]['payload']['claims'].reverse()
        self.assertNotEqual(self.material(), before)

    def test_unfingerprinted_paths_remain_material_dependencies(self):
        self.evidence["evidence"][0].pop("sha256")
        before = self.material()
        self.evidence["evidence"][0]["path"] = "/missing/file"
        self.assertNotEqual(self.material(), before)

    def test_only_affected_candidate_unit_reopens(self):
        previous = receipt(self.rows, self.material())
        self.evidence["evidence"][0]["payload"]["claim"] = "amended claim"
        options = final.reuse_options(previous, self.material())
        self.assertEqual(options["changed_unit_ids"], [final.unit_id(self.rows[0])])
        self.assertEqual(options["reusable_unit_ids"], [final.unit_id(self.rows[1])])

    def test_real_record_envelope_and_run_changes_reopen_only_bound_candidate(self):
        self.evidence = {'source_runs': [], 'collections': {'patents': []}}
        self.plan['queries'] = {'api': []}
        for key in ('P1', 'P2'):
            self.candidates['api'][int(key[-1]) - 1]['sources'] = [{'evidence_id': 'E-' + key}]
            self.evidence['source_runs'].append({'run_id': 'R-' + key, 'query_id': 'Q-' + key,
                'provider': 'api', 'jurisdiction': 'US', 'right_type': 'patent', 'payload_digest': key * 32})
            self.evidence['collections']['patents'].append({'evidence_id': 'E-' + key,
                'source_run_id': 'R-' + key, 'query_id': 'Q-' + key, 'jurisdiction': 'US',
                'right_type': 'patent', 'payload_sha256': key * 32,
                'payload': {'records': [{'publication_number': 'US' + key, 'claims': key}]}})
            self.plan['queries']['api'].append({'query_id': 'Q-' + key, 'candidate_id': key,
                'jurisdiction': 'US', 'right_type': 'patent', 'q': key})
        scope = {**self.rows[0], 'candidate_id': '', 'evidence_refs': []}
        before = receipt([*self.rows, scope], self.material())
        self.evidence['source_runs'][1]['payload_digest'] = 'new retained bytes'
        self.evidence['collections']['patents'][1]['payload_sha256'] = 'new retained bytes'
        self.evidence['collections']['patents'][1]['payload']['records'][0]['claims'] = 'changed claim'
        self.plan['queries']['api'][1]['q'] = 'changed record query'
        options = final.reuse_options(before, self.material())
        self.assertEqual(options['reusable_unit_ids'], [final.unit_id(self.rows[0])])
        self.assertEqual(set(options['changed_unit_ids']), {final.unit_id(self.rows[1]), final.unit_id(scope)})

    def test_raw_and_payload_fingerprints_make_paths_administrative(self):
        for field in ('raw_sha256', 'payload_sha256'):
            self.assertEqual(final.semantic({field: 'a' * 64, 'raw_paths': ['/old']}),
                final.semantic({field: 'a' * 64, 'raw_paths': ['/new']}))

    def test_specialty_fact_change_is_a_material_final_input(self):
        before = self.material()
        self.task['specialty_analysis_events'] = [{'candidate_id': 'P1', 'kind': 'fact', 'outcome': 'unknown'}]
        self.assertNotEqual(before, self.material())

    def test_scope_judgment_reopens_for_candidate_change(self):
        scope = {**self.rows[0], "candidate_id": ""}
        previous = receipt([scope], self.material())
        self.candidates["api"][1]["title"] = "Corrected identity"
        self.assertEqual(final.reuse_options(previous, self.material())["changed_unit_ids"], [final.unit_id(scope)])

    def test_prior_receipt_is_preserved_and_validated_without_rebinding(self):
        prior = receipt(self.rows, self.material())
        original = deepcopy(prior)
        self.evidence["evidence"][0]["payload"]["claim"] = "amended claim"
        current = receipt([self.rows[0]], self.material(), "next", prior, [final.unit_id(self.rows[1])])
        final.validate_envelope(current, self.material())
        self.assertEqual(prior, original)
        self.assertEqual(current["review_context"]["final_review"]["previous_review"], original)
        self.assertNotEqual(current["review_context"]["evidence_digest"], prior["review_context"]["evidence_digest"])

    def test_changed_unit_cannot_be_reused(self):
        prior = receipt(self.rows, self.material())
        self.evidence["evidence"][0]["payload"]["claim"] = "amended claim"
        with self.assertRaisesRegex(ValueError, "REUSED_UNIT_CHANGED"):
            receipt([], self.material(), "next", prior, [final.unit_id(self.rows[0])])

    def test_prior_attestation_tamper_is_rejected(self):
        prior = receipt(self.rows, self.material())
        current = receipt([], self.material(), "next", prior, [final.unit_id(row) for row in self.rows])
        current["review_context"]["final_review"]["previous_review"]["review_context"]["evidence_digest"] = "rewritten"
        with self.assertRaisesRegex(ValueError, "ATTESTATION_INVALID|PREVIOUS_RECEIPT_CHANGED"):
            final.validate_envelope(current)

    def test_duplicate_review_and_reuse_rejected(self):
        prior = receipt(self.rows, self.material())
        with self.assertRaisesRegex(ValueError, "REVIEWED_AND_REUSED"):
            receipt(self.rows, self.material(), "next", prior, [final.unit_id(self.rows[0])])

    def test_current_overall_scope_and_limitations_always_required(self):
        with self.assertRaisesRegex(ValueError, "CURRENT_OVERALL_SCOPE_LIMITATIONS_REQUIRED"):
            final.prepare_rows({}, self.rows, self.material())

    def test_same_old_judgment_cannot_supply_both_independent_sides(self):
        prior = receipt(self.rows, self.material())
        ids = [final.unit_id(row) for row in self.rows]
        first = receipt([], self.material(), "next-first", prior, ids)
        second = receipt([], self.material(), "next-second", prior, ids)
        with self.assertRaisesRegex(ValueError, "ORIGIN_NOT_INDEPENDENT"):
            final.pair_summary(first, second, sha256_json(self.material()))

    def test_independent_prior_origins_are_reusable(self):
        ids = [final.unit_id(row) for row in self.rows]
        first = receipt([], self.material(), "next-first", receipt(self.rows, self.material(), "first"), ids)
        second = receipt([], self.material(), "next-second", receipt(self.rows, self.material(), "second"), ids)
        self.assertEqual(final.pair_summary(first, second, sha256_json(self.material()))["reused_unit_counts"], [2, 2])

    def test_freeze_time_is_stable_until_source_facts_change(self):
        at = "2026-09-28T00:00:00Z"
        self.task["final_review_freeze"] = final.freeze_time_binding(self.task, self.evidence, at)
        with patch.object(final, "now_iso", return_value="later"):
            self.assertEqual(final.evaluation_at(self.task, self.evidence), at)
            self.evidence["history"] = [{"progress": "later"}]
            self.assertEqual(final.evaluation_at(self.task, self.evidence), at)
            self.evidence["evidence"][0]["payload"]["claim"] = "changed"
            self.assertEqual(final.evaluation_at(self.task, self.evidence), "later")

    def test_stage_review_disabled_only_for_new_policy(self):
        from stage_review_stage_c import enabled
        self.assertTrue(enabled({"stage_review_revision": "stage-review-stage-c-v1"}))
        self.assertFalse(enabled({**self.task, "stage_review_revision": "stage-review-stage-c-v1"}))

    def test_old_digest_preserves_legacy_metadata_behavior(self):
        from assessment_estimate import review_digest
        old = {"task_id": "T1"}
        before = review_digest({}, {}, {}, {}, old)
        self.assertNotEqual(before, review_digest({"history": ["later"]}, {}, {}, {}, old))

    def test_validated_pair_drives_assessment_and_presentation(self):
        from test_assessment_estimate import fixture
        from assessment_estimate import compute_assessment, review_digest
        with tempfile.TemporaryDirectory() as directory:
            task, evidence, candidates, plan, ledger, first, second = fixture(Path(directory))
            task["review_policy_revision"] = final.REVISION
            material = final.inputs(evidence, candidates, ledger, plan, task)
            for position, review in enumerate((first, second)):
                bound = receipt(review["assessments"], material, str(position))
                review["review_context"] = bound["review_context"]
                review["review_context"]["evidence_digest"] = review_digest(evidence, candidates, ledger, plan, task)
            assessment = compute_assessment(task, evidence, candidates, plan, ledger, first, second)
            self.assertEqual(assessment["final_review"]["status"], "complete")
            stage = final.project_stage({"product": {"product_version": "1"}}, assessment)
            self.assertEqual(stage["review_label"], "最终双审已完成")
            self.assertEqual(stage["stage_risk"]["overall"]["review_status"], "complete")
            self.assertEqual(stage["stage_risk"]["judgments"][0]["stage_risk"], "高")

    def test_business_completion_uses_final_pair_without_stage_review(self):
        from business_status_stage_b import classify
        assessment = {"status": "completed", "final_review": {"revision": final.REVISION,
            "status": "complete", "evidence_digest": "digest"}}
        task = {**self.task, "business_status_revision": "business-status-stage-b-v1"}
        stage = {"progress": {"completed": 1, "planned": 1}, "stage_risk": {"judgments": [],
            "overall": {"review_status": "complete", "applicability": "current"}}}
        result = classify(task, stage, {"entries": []}, assessment)
        self.assertEqual(result["business_status"], "business_complete")
        self.assertNotIn("NECESSARY_09C_REVIEW_PENDING", result["gaps"])

    def test_limited_round_uses_scoped_final_judgment_instead_of_09c_batch(self):
        from business_status_stage_b import classify
        scope = {'scenario_id': 'S1', 'jurisdiction': 'US', 'right_type': 'patent'}
        assessment = {'status': 'incomplete', 'final_review': {'revision': final.REVISION,
            'status': 'complete', 'evidence_digest': 'digest'}, 'assessments': [{**scope,
                'assessment_status': 'pending', 'pending_reasoning': 'Current claim text is unavailable.'}]}
        stage = {'progress': {'completed': 0, 'planned': 1}, 'stage_risk': {'judgments': [], 'overall': {}},
            'product': {'product_version': '1'}}
        entry = {**scope, 'work_id': 'W1', 'state': 'blocked', 'kind': 'source_lookup',
            'resume_condition': 'API account access restored', 'delivery_limit': {'source_run_refs': ['R1']}}
        result = classify({**self.task, 'business_status_revision': 'business-status-stage-b-v1'},
            stage, {'entries': [entry], 'unresolved_scopes': [scope]}, assessment,
            limitation_validator=lambda value: True)
        self.assertEqual(result['business_status'], 'limited_round_closed')
        self.assertEqual(result['limitations'][0]['judgment_impact'], 'Current claim text is unavailable.')
        self.assertFalse(result['limitations'][0]['gaps'])

    def test_final_html_uses_final_grade_and_pair_without_pending_stage_banner(self):
        from test_report_presentation_stage_a import PresentationStageATests
        fixture = PresentationStageATests('test_eight_sections_five_columns_and_separate_progress_review_risk')
        fixture.setUp()
        try:
            fixture.fixture.task['review_policy_revision'] = final.REVISION
            assessment = fixture.fixture.assessment
            assessment['status'] = 'completed'
            assessment['final_review'] = {'revision': final.REVISION, 'status': 'complete',
                'evidence_digest': 'current', 'review_sha256s': ['first', 'second']}
            fixture.build()
            page = (fixture.fixture.out / 'report.html').read_text()
            self.assertIn('最终报告 · 最终双审已完成', page)
            self.assertNotIn('阶段判断 ·', page)
            self.assertNotIn('待双审', page)
            self.assertIn('整体对应与实质差异并存', page)
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
