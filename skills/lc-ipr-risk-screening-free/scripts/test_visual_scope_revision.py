"""Real follow-up work converges on one visual judgment per legal scope."""
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from candidate_followup import record_review
from common import atomic_write_json, load_json
from visual_triage_host import commit, group_entries, pending_entries, prepare_packet
import test_visual_triage_host


class VisualScopeRevisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_visual_triage_host.VisualHostTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def continued_actions(self):
        scope, entries, packet = self.fixture.scoped_packet()
        raw = self.fixture.raw(packet)
        row, unit = raw['decisions'][0], packet['units'][0]
        row.update(decision='needs_info', adequate=False, missing_information=['Two exact protected details remain unclear'])
        row['comparison'].update(missing_fact_effect='Protected contour cannot be established',
            completion_condition='Read the exact complete views', existing_material_review='The thumbnail lacks the fine contours')
        row['next_actions'] = []
        for number in (1, 2):
            basis = {key: 'The retained image leaves detail ' + str(number) + ' unresolved' for key in
                packet['followup_contract']['all_actions']['followup_basis']}
            basis['existing_evidence_refs'] = unit['candidate_image_ids']
            row['next_actions'].append({'kind': 'agent_read', 'purpose': 'Read exact detail ' + str(number),
                'max_attempts': 1, 'evidence_refs': unit['candidate_image_ids'],
                'required_facts': ['representative_figures'],
                'reading_scope': {'level': 'representative_figures', 'page_numbers': [number]},
                'followup_basis': basis})
        directory = scope.run / 'first-decisions'; directory.mkdir()
        with redirect_stdout(StringIO()): commit(scope.run, entries, packet, raw, 'first-session', directory)
        annotation = next(a for a in load_json(scope.run / 'materiality-annotations.json')['annotations']
                          if a['candidate_id'] == unit['template']['candidate_id'])
        for number, action in enumerate(annotation['next_actions'], 1):
            request = {key: annotation[key] for key in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type', 'annotation_id')}
            request.update(action_id=action['action_id'], outcome='continue',
                result_evidence_refs=unit['candidate_image_ids'], unresolved_fact='The contour in detail ' + str(number) + ' remains unclear',
                next_value='A full view can resolve the particular contour', boundary_remaining='One exact retained-document route remains',
                next_action_id='NEXT-' + str(number), reason='The thumbnail does not supply the exact detail', reviewer='offline-agent')
            record_review(scope.run, request)
        return scope, annotation

    def test_two_real_continue_actions_produce_one_unit_and_one_new_decision(self):
        scope, annotation = self.continued_actions()
        entries = pending_entries(scope.run)
        self.assertEqual(len(entries), 2)
        self.assertEqual({e['action_id'] for e in entries}, {a['action_id'] for a in annotation['next_actions']})
        packet, _ = prepare_packet(scope.run, entries)
        self.assertEqual(len(packet['units']), 1)
        self.assertEqual(len(packet['units'][0]['origin_work_refs']), 2)
        before = load_json(scope.run / 'materiality-annotations.json')['annotations']
        directory = scope.run / 'second-decision'; directory.mkdir()
        with redirect_stdout(StringIO()):
            commit(scope.run, entries, packet, self.fixture.raw(packet), 'second-session', directory)
        after = load_json(scope.run / 'materiality-annotations.json')['annotations']
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(pending_entries(scope.run), [])

    def test_changed_followup_work_rejects_old_packet(self):
        scope, annotation = self.continued_actions()
        entries = pending_entries(scope.run); packet, _ = prepare_packet(scope.run, entries)
        action = annotation['next_actions'][0]
        request = {key: annotation[key] for key in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type', 'annotation_id')}
        request.update(action_id=action['action_id'], outcome='waiting', result_evidence_refs=action['evidence_refs'],
            dependency='The complete view is unavailable', resume_condition='A retained complete view arrives',
            reason='The expected new document was not supplied', reviewer='offline-agent')
        record_review(scope.run, request)
        before = (scope.run / 'materiality-annotations.json').read_bytes()
        directory = scope.run / 'obsolete'; directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'VISUAL_INPUT_CHANGED'):
            commit(scope.run, entries, packet, self.fixture.raw(packet), 'obsolete-session', directory)
        self.assertEqual((scope.run / 'materiality-annotations.json').read_bytes(), before)

    def test_already_completed_scope_cannot_be_overwritten_by_old_model_output(self):
        entries, packet, _ = self.fixture.collected_packet(1)
        first = self.fixture.root / 'first'; first.mkdir()
        with redirect_stdout(StringIO()):
            commit(self.fixture.root, entries, packet, self.fixture.raw(packet), 'first', first)
        before = (self.fixture.root / 'materiality-annotations.json').read_bytes()
        second = self.fixture.root / 'second'; second.mkdir()
        with self.assertRaisesRegex(ValueError, 'VISUAL_INPUT_CHANGED'):
            commit(self.fixture.root, entries, packet, self.fixture.raw(packet), 'second', second)
        self.assertEqual((self.fixture.root / 'materiality-annotations.json').read_bytes(), before)

    def test_changed_basis_with_the_same_work_ids_rejects_old_packet(self):
        from candidate_followup import events
        scope, annotation = self.continued_actions()
        entries = pending_entries(scope.run); packet, _ = prepare_packet(scope.run, entries)
        action = annotation['next_actions'][0]
        task = load_json(scope.run / 'task.json')
        changed = {key: value for key, value in next(row for row in events(task)
            if row['action_id'] == action['action_id']).items() if key not in {'event_id', 'previous_event_id'}}
        changed.update(
            unresolved_fact='A newly read contour reveals a different unresolved boundary',
            next_value='A newly identified view can resolve this boundary', boundary_remaining='One precise document route remains',
            next_action_id='NEXT-CHANGED', reason='New reading changed the missing fact', reviewer='offline-agent')
        new = record_review(scope.run, changed)
        self.assertEqual(new['next_value'], changed['next_value'])
        self.assertEqual([e['work_id'] for e in entries], [e['work_id'] for e in pending_entries(scope.run)])
        directory = scope.run / 'changed-basis'; directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'VISUAL_INPUT_CHANGED'):
            commit(scope.run, entries, packet, self.fixture.raw(packet), 'obsolete-session', directory)

    def followup_transition(self, scope, annotation):
        from candidate_followup import events
        action = annotation['next_actions'][0]
        original = next(row for row in events(load_json(scope.run / 'task.json')) if row['action_id'] == action['action_id'])
        waiting = {key: annotation[key] for key in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type', 'annotation_id')}
        waiting.update(action_id=action['action_id'], outcome='waiting', result_evidence_refs=action['evidence_refs'],
            dependency='The complete view is temporarily unavailable', resume_condition='The exact complete view is retained',
            reason='The new view has not yet arrived', reviewer='offline-agent')
        return original, waiting

    def test_continue_waiting_continue_records_the_current_transition(self):
        from candidate_followup import events, latest_event
        scope, annotation = self.continued_actions()
        original, waiting = self.followup_transition(scope, annotation)
        record_review(scope.run, waiting)
        before = events(load_json(scope.run / 'task.json'))
        resumed = record_review(scope.run, original)
        after_task = load_json(scope.run / 'task.json')
        self.assertNotEqual(resumed['event_id'], original['event_id'])
        self.assertEqual(latest_event(after_task, 'result_review', annotation['annotation_id'], original['action_id'])['outcome'], 'continue')
        self.assertEqual(events(after_task)[:-1], before)
        self.assertTrue(any(e.get('action_id') == original['action_id'] for e in pending_entries(scope.run)))

    def test_identical_current_result_is_idempotent_despite_new_timestamp(self):
        scope, annotation = self.continued_actions()
        original, _ = self.followup_transition(scope, annotation)
        before = (scope.run / 'task.json').read_bytes()
        with patch('candidate_followup.now_iso', return_value='2099-01-01T00:00:00Z'):
            same = record_review(scope.run, original)
        self.assertEqual(same['event_id'], original['event_id'])
        self.assertEqual((scope.run / 'task.json').read_bytes(), before)

    def test_changed_validated_result_references_are_not_swallowed(self):
        from candidate_followup import events
        scope, annotation = self.continued_actions()
        original, _ = self.followup_transition(scope, annotation)
        before = events(load_json(scope.run / 'task.json'))
        # An unresolved continue may explicitly have no newly read originals;
        # this is not a sufficient/completed material decision.
        changed = record_review(scope.run, {**original, 'result_evidence_refs': []})
        self.assertNotEqual(changed['event_id'], original['event_id'])
        self.assertEqual(changed['result_evidence_refs'], [])
        self.assertEqual(events(load_json(scope.run / 'task.json'))[:-1], before)

    def test_legacy_result_idempotency_and_historical_bytes_are_unchanged(self):
        from candidate_followup import latest_event
        scope, annotation = self.continued_actions()
        task = load_json(scope.run / 'task.json'); task['execution_efficiency_revision'] = 'execution-efficiency-v1'
        atomic_write_json(scope.run / 'task.json', task)
        original, waiting = self.followup_transition(scope, annotation)
        record_review(scope.run, waiting)
        before = (scope.run / 'task.json').read_bytes()
        old = record_review(scope.run, original)
        self.assertEqual(old['event_id'], original['event_id'])
        self.assertEqual((scope.run / 'task.json').read_bytes(), before)
        self.assertEqual(latest_event(load_json(scope.run / 'task.json'), 'result_review',
            annotation['annotation_id'], original['action_id'])['outcome'], 'waiting')

    def test_unrelated_candidate_decision_does_not_invalidate_this_packet(self):
        entries, packet, _ = self.fixture.collected_packet(2)
        first_entries = entries[:1]; first_packet, _ = prepare_packet(self.fixture.root, first_entries)
        other_entries = entries[1:]; other_packet, _ = prepare_packet(self.fixture.root, other_entries)
        other = self.fixture.root / 'other'; other.mkdir()
        first = self.fixture.root / 'first'; first.mkdir()
        with redirect_stdout(StringIO()):
            commit(self.fixture.root, other_entries, other_packet, self.fixture.raw(other_packet), 'other', other)
            commit(self.fixture.root, first_entries, first_packet, self.fixture.raw(first_packet), 'first', first)
        self.assertEqual(len(load_json(self.fixture.root / 'materiality-annotations.json')['annotations']), 2)

    def test_countries_scenarios_and_right_types_do_not_merge(self):
        base = {'candidate_id': 'C1', 'scenario_id': 'product_entry', 'jurisdiction': 'US',
            'right_type': 'design', 'work_id': 'W1', 'action_id': 'A1', 'state': 'awaiting_review', 'reason': 'FOLLOWUP_NEXT_DECISION_REQUIRED'}
        rows = [base, {**base, 'work_id': 'W2', 'action_id': 'A2'},
            {**base, 'jurisdiction': 'CA', 'work_id': 'W3'},
            {**base, 'scenario_id': 'brand_reuse', 'work_id': 'W4'},
            {**base, 'right_type': 'copyright', 'work_id': 'W5'}]
        grouped = group_entries(rows)
        self.assertEqual(len(grouped), 4)
        self.assertEqual(len(grouped[0]['origin_work_refs']), 2)

    def test_legacy_packet_retains_its_original_fields(self):
        task = load_json(self.fixture.root / 'task.json')
        task['execution_efficiency_revision'] = 'execution-efficiency-v1'
        atomic_write_json(self.fixture.root / 'task.json', task)
        _, packet, _ = self.fixture.collected_packet(1)
        self.assertNotIn('origin_work_refs', packet['units'][0])
        self.assertNotIn('origin_basis_sha256', packet['units'][0])


if __name__ == '__main__':
    unittest.main()
