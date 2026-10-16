"""Visual host on batch-host tasks: compact judgments, identical-content sharing and halved retry."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

from common import atomic_write_json, load_json


class VisualCompactTests(unittest.TestCase):
    def setUp(self):
        import host_triage
        import test_visual_triage_host as base
        self.base = base.VisualHostTests('test_all_18_candidates_register_directly_in_three_batches')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        task = load_json(self.root / 'task.json')
        task.update(host_triage_revision=host_triage.REVISION, host_triage=dict(host_triage.DEFAULTS))
        atomic_write_json(self.root / 'task.json', task)

    def compact(self, packet, **special):
        rows = []
        for unit in packet['units']:
            cid = unit['template']['candidate_id']
            row = {'unit_id': unit['unit_id'], 'viewed_all': True, 'adequate': True, 'decision': 'selected',
                   'relationship': 'The visible motif outline of ' + cid + ' may correspond to the product motif',
                   'investigation_question': 'Which work and licence does this image represent?'}
            row.update(special.get(cid, {}))
            rows.append(row)
        return {'decisions': rows}

    def test_compact_form_is_expanded_to_the_full_recorded_decision(self):
        from visual_triage_host import commit, prepare_packet, decisions_from_output
        entries, packet, _ = self.base.collected_packet()
        self.assertEqual(packet['output_form'], 'compact')
        raw = self.compact(packet, C1={'decision': 'not_selected', 'difference': 'The candidate shows a different motif',
                                        'investigation_question': None})
        decisions = decisions_from_output(raw, packet, 'synthetic')
        by_id = {d['candidate_id']: d for d in decisions}
        self.assertEqual(by_id['C0']['decision'], 'selected')
        self.assertEqual(by_id['C0']['comparison']['investigation_question'], 'Which work and licence does this image represent?')
        self.assertIn('差异', by_id['C1']['reason'])
        self.assertTrue(by_id['C1']['comparison']['applicability_limit'])
        self.assertTrue(by_id['C0']['comparison']['candidate_content'])
        self.assertEqual(by_id['C0']['reviewer'], 'native-visual-synthetic')
        directory = self.root / 'commit'
        directory.mkdir()
        with redirect_stdout(StringIO()):
            commit(self.root, entries, packet, raw, 'synthetic', directory)
        rows = {r['candidate_id']: r for r in load_json(self.root / 'materiality-annotations.json')['annotations']}
        self.assertEqual({k: v['decision'] for k, v in rows.items()},
                         {**{'C%d' % i: 'selected' for i in range(6)}, 'C1': 'not_selected'})

    def test_compact_form_still_requires_the_concrete_basis(self):
        from visual_triage_host import decisions_from_output
        _, packet, _ = self.base.collected_packet()
        for special, code in (({'C0': {'viewed_all': False}}, 'IMAGE_READING'),
                              ({'C0': {'relationship': '  '}}, 'CONCRETE_OBSERVATIONS'),
                              ({'C0': {'decision': 'not_selected'}}, 'EXCLUSION_DIFFERENCE'),
                              ({'C0': {'investigation_question': None}}, 'SELECTED_QUESTION'),
                              ({'C0': {'relationship': 'Similarity 92% to the product'}}, 'NUMERIC_SCORE'),
                              ({'C0': {'adequate': False}}, 'INSUFFICIENT_IMAGES')):
            with self.assertRaisesRegex(ValueError, code, msg=str(special)):
                decisions_from_output(self.compact(packet, **special), packet, 'synthetic')

    def test_batch_host_task_judges_candidates_when_the_product_has_three_views(self):
        """A real listing keeps three views; the legacy limit of two made every batch unrunnable."""
        from visual_triage_host import prepare_packet, _limits
        task = self.base.add_views()
        atomic_write_json(self.root / 'task.json', task)
        self.assertEqual(len(task['images']), 3)
        self.assertEqual(task['execution_efficiency']['vision_product_images'], 2)
        self.assertEqual(_limits(task)['vision_product_images'], 6)
        packet, _ = prepare_packet(self.root, self.base.entries()[:6])
        self.assertEqual(len(packet['product_image_ids']), 3)
        self.assertEqual(len([i for i in packet['images'] if i['role'] == 'product']), 3)

    def test_views_beyond_the_batch_host_limit_still_stop_the_batch(self):
        from visual_triage_host import prepare_packet
        task = self.base.add_views()
        task['host_triage']['vision_product_images'] = 2
        atomic_write_json(self.root / 'task.json', task)
        with self.assertRaisesRegex(ValueError, 'VISUAL_SPLIT_REQUIRED_FOR_PRODUCT_VIEWS'):
            prepare_packet(self.root, self.base.entries()[:6])

    def test_task_frozen_before_the_view_limit_existed_keeps_working(self):
        import host_triage
        task = load_json(self.root / 'task.json')
        task['host_triage'] = {k: v for k, v in host_triage.DEFAULTS.items() if k not in host_triage.OPTIONAL}
        self.assertEqual(host_triage.policy(task)['vision_product_images'], host_triage.OPTIONAL['vision_product_images'])
        task['host_triage']['unknown_limit'] = 1
        with self.assertRaisesRegex(ValueError, 'HOST_TRIAGE_POLICY_INVALID'):
            host_triage.policy(task)
        task['host_triage'] = {k: v for k, v in host_triage.DEFAULTS.items() if k != 'text_parallel'}
        with self.assertRaisesRegex(ValueError, 'HOST_TRIAGE_POLICY_INVALID'):
            host_triage.policy(task)

    def test_candidates_without_a_retained_image_are_left_open_and_never_sent_to_a_session(self):
        base = self.base
        def fail(url, **kwargs):
            raise ValueError('MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking_198.18.0.0/15')
        base.download = fail
        result = base.run_host()
        self.assertEqual(base.calls, [])
        self.assertEqual(load_json(self.root / 'materiality-annotations.json')['annotations'], [])
        self.assertTrue(result['batches'])
        for row in result['batches']:
            self.assertEqual((row['status'], row['phase']), ('needs_info', 'media'))
            self.assertIn('VISUAL_CANDIDATE_IMAGE_UNAVAILABLE', row['reason'])
            self.assertIn('benchmarking_198.18.0.0/15', row['reason'])
            # the fix is named in the same place the cause is, not only in a separate command
            self.assertIn('--check-network', row['next_action'])
            self.assertIn('fake-IP', row['next_action'])
        self.assertEqual(sorted({c for row in result['batches'] for c in row['candidate_ids']}),
                         sorted({e['candidate_id'] for e in base.entries()}))
        cache = load_json(self.root / 'candidate-media.json')
        attempts = [a for row in cache['candidates'].values() for a in row.get('attempted', [])]
        self.assertTrue(attempts)
        self.assertTrue(all('MEDIA_PUBLIC_ADDRESS_REQUIRED' in a['failure'] for a in attempts))

    def test_full_form_is_still_accepted_on_a_batch_host_task(self):
        from visual_triage_host import commit
        entries, packet, _ = self.base.collected_packet()
        directory = self.root / 'commit'
        directory.mkdir()
        with redirect_stdout(StringIO()):
            commit(self.root, entries, packet, self.base.raw(packet), 'synthetic', directory)
        self.assertEqual(len(load_json(self.root / 'materiality-annotations.json')['annotations']), 6)

    def test_identical_listing_shares_one_judgment_and_keeps_its_own_evidence(self):
        import host_triage
        from visual_triage_host import commit, prepare_packet, split_duplicates, pending_entries
        scope, _, _ = self.base.scoped_packet()
        root = scope.run
        task = load_json(root / 'task.json')
        task.update(host_triage_revision=host_triage.REVISION, host_triage=dict(host_triage.DEFAULTS))
        atomic_write_json(root / 'task.json', task)
        candidates = load_json(root / 'normalized-candidates.json')
        rows = candidates['copyright_assets']
        for number, row in enumerate(rows):
            row.update(title='Marketplace listing %d' % number, url='https://shop.example.test/item/%d' % number,
                       image_url='https://images.example.test/%d.png' % number, match_type='visual_matches')
        for key in ('title', 'url', 'image_url'):
            rows[1][key] = rows[0][key]           # the same listing seen again in another country's search
        atomic_write_json(root / 'normalized-candidates.json', candidates)
        entries = pending_entries(root)
        representatives, duplicates = split_duplicates(root, entries)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]['entries'][0]['candidate_id'], rows[1]['candidate_id'])
        self.assertEqual({e['candidate_id'] for e in representatives},
                         {r['candidate_id'] for r in rows} - {rows[1]['candidate_id']})
        packet, _ = prepare_packet(root, representatives)
        self.assertEqual(len(packet['units']), 5)
        directory = root / 'commit'
        directory.mkdir()
        scopes = {(e['candidate_id'], e['scenario_id'], e['jurisdiction'], e['right_type']) for e in representatives}
        with redirect_stdout(StringIO()):
            commit(root, representatives, packet, self.compact(packet), 'synthetic', directory,
                   [item for item in duplicates if item['representative'] in scopes])
        recorded = {r['candidate_id']: r for r in load_json(root / 'materiality-annotations.json')['annotations']}
        self.assertEqual(set(recorded), {r['candidate_id'] for r in rows})
        copy, original = recorded[rows[1]['candidate_id']], recorded[rows[0]['candidate_id']]
        self.assertEqual(copy['decision'], original['decision'])
        self.assertIn(rows[0]['candidate_id'], copy['basis_summary'])
        self.assertNotEqual(copy['annotation_id'], original['annotation_id'])
        self.assertEqual(copy['candidate_relation']['product_object_ids'], ['pattern'])

    def test_an_invalid_session_is_retried_in_halves_on_batch_host_tasks(self):
        import visual_triage_host as host
        candidates = load_json(self.root / 'normalized-candidates.json')
        candidates['copyright_assets'] = candidates['copyright_assets'][:6]
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)
        calls, state = [], {'broken': False}
        original = self.base.native

        def native(command, prompt, workspace, trace_path, stderr_path, timeout):
            packet = load_json(trace_path.parent / 'packet.json')
            calls.append(len(packet['units']))
            if not state['broken']:
                state['broken'] = True
                raw = self.compact(packet)
                raw['decisions'] = raw['decisions'][:-1]
                stderr_path.write_text('synthetic native output only')
                events = [{'type': 'thread.started', 'thread_id': 'broken'}, {'type': 'turn.started'},
                          {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(raw)}},
                          {'type': 'turn.completed'}]
                text = '\n'.join(map(json.dumps, events))
                trace_path.write_text(text)
                return SimpleNamespace(returncode=0, pid=7000), text, ''
            return original(command, prompt, workspace, trace_path, stderr_path, timeout)

        with patch('candidate_media.download', side_effect=self.base.download), \
             patch('report_review_host.run_native_logged', side_effect=native), \
             patch('review_isolation.select_backend', return_value='macos-sandbox'), \
             patch('native_review_jobs._probe', return_value=[]), patch('macos_review_host.require_chatgpt_auth'), \
             redirect_stdout(StringIO()):
            result = host.run(self.root, binary=self.base.binary, isolation='macos-sandbox')
        self.assertTrue(all(b['status'] == 'recorded' for b in result['batches']), result)
        self.assertEqual(len(load_json(self.root / 'materiality-annotations.json')['annotations']), 6)
        self.assertEqual(calls[0], 6)
        self.assertEqual(sum(calls[1:]), 6)


class PublicCardClosureTests(unittest.TestCase):
    """best-estimate-risk-v2: user_information needs_info on a public third-party card closes as not_selected."""

    def decision(self, **extra):
        value = {'candidate_id': 'C9', 'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'unknown',
                 'decision': 'needs_info', 'reason': 'Card image shows a pot lid, not a strap',
                 'basis_summary': '需补材料依据已读候选图片与产品图片比较', 'reopen_conditions': ['候选图片变化时重新分流'],
                 'comparison': {'candidate_content': 'Card', 'product_content': 'Strap', 'relationship': 'Unclear',
                                'missing_fact_effect': 'x', 'completion_condition': 'y', 'existing_material_review': 'z'},
                 'missing_information': ['Full view of the card strap'],
                 'next_actions': [{'kind': 'user_information', 'question': 'Is the card picture wrong?', 'purpose': 'p'}]}
        value.update(extra)
        return value

    def test_public_card_user_question_is_closed_with_the_gap_kept(self):
        from visual_triage_host import close_public_card, PUBLIC_CARD_REOPEN
        unit = {'candidate': {'right_type': 'unknown', 'candidate_nature': 'visual_match'}}
        closed = close_public_card(self.decision(), unit)
        self.assertEqual(closed['decision'], 'not_selected')
        self.assertNotIn('next_actions', closed)
        self.assertNotIn('missing_information', closed)
        self.assertTrue(closed['comparison']['difference'] and closed['comparison']['applicability_limit'])
        self.assertNotIn('missing_fact_effect', closed['comparison'])
        self.assertIn(PUBLIC_CARD_REOPEN, closed['reopen_conditions'])
        self.assertTrue(any('Full view of the card strap' in item for item in closed['reopen_conditions']))

    def test_other_requests_and_typed_rights_are_untouched(self):
        from visual_triage_host import close_public_card
        public = {'candidate': {'right_type': 'unknown', 'candidate_nature': 'visual_match'}}
        source = self.decision(next_actions=[{'kind': 'source_lookup', 'purpose': 'p'}])
        self.assertEqual(close_public_card(source, public), source)
        typed = {'candidate': {'right_type': 'design', 'publication_number': 'USD1', 'candidate_nature': 'patent'}}
        self.assertEqual(close_public_card(self.decision(), typed)['decision'], 'needs_info')
        selected = self.decision(decision='selected')
        self.assertEqual(close_public_card(selected, public), selected)

    def test_closed_decision_passes_the_annotation_validator(self):
        from decision_workflow import annotation_errors
        from visual_triage_host import close_public_card
        closed = close_public_card(self.decision(evidence_refs=['EV-1'], candidate_relation={
            'product_object_ids': ['STRAP'], 'direction_ids': ['DIR-copyright'], 'scope_reason': 'card',
            'evidence_refs': ['EV-1'], 'identity_gaps': []}), {'candidate': {'right_type': 'unknown'}})
        errors = annotation_errors({**closed, 'annotation_id': 'TRIAGE-1', 'reviewer': 'native-visual-s',
                                    'reading_level': 'image_comparison', 'annotated_at': '2026-10-11T00:00:00Z'},
                                   task={'decision_workflow_revision': 'scenario-triage-v1'})
        self.assertFalse([e for e in errors if 'HASH' not in e and 'REQUIRED_FIELD' not in e
                          and 'REVISION' not in e], errors)


if __name__ == '__main__':
    unittest.main()
