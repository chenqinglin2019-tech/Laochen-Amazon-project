"""r5d17 (run B0HF19R4YF, 2026-10-13): stale compiled caches after an upgrade, design patents screened before the final
review (owner decision), comparison labels normalized, five comparison slots, final-review originals once per file
content, idle source / core rounds skipped, and the delivered output says the completion check already ran.

Golden replay of the real run (scratchpad golden15/g15.py): the seven designs the real comparison called plainly
different leave through the audited route, readiness passes, the appearance module goes from 157 materials / 143
images to 21 / 19, the chief draft has no open row and publication returns limited_round_closed.
"""
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import comparison_host as ch
import design_screen as ds
import module_review
import pipeline_robust
import prereview_screen as ps
import run_pipeline as rp
import text_triage_host
from common import sha256_bytes

SPEED = {'pipeline_speed_revision': pipeline_robust.SPEED_REVISION}
SCRIPTS = Path(__file__).resolve().parent


def pipeline(root):
    return rp.Pipeline(rp.parser().parse_args(['--task-dir', str(root)]))


class StaleBytecodeTests(unittest.TestCase):
    """r5d16 changed 10 to 20 in api_first_planning.py without changing its size; the zip gave every file one date, so
    Python kept running the r5d15 cache (API_FIRST_RETRIEVAL_POLICY_INVALID)."""

    def value(self, scripts):
        result = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import probe_r5d17; '
                                 'print(probe_r5d17.VALUE)', str(scripts)], capture_output=True, text=True,
                                env={k: v for k, v in os.environ.items() if k not in ('PYTHONDONTWRITEBYTECODE',
                                                                                         'PYTHONPYCACHEPREFIX')})
        return result.stdout.strip()

    def test_a_same_size_edit_under_the_same_date_is_read_after_the_cache_is_cleared(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        scripts = root / 'scripts'
        scripts.mkdir()
        (root / 'DISTRIBUTION-MANIFEST.json').write_text('{"release": "r5d16"}', encoding='utf-8')
        source = scripts / 'probe_r5d17.py'
        source.write_text('VALUE = 10\n', encoding='utf-8')
        os.utime(source, (1760313600, 1760313600))
        py_compile.compile(str(source), invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP, doraise=True)
        source.write_text('VALUE = 20\n', encoding='utf-8')          # same size, same date: the zip of a new release
        os.utime(source, (1760313600, 1760313600))
        self.assertEqual(self.value(scripts), '10')                    # the trap: the old bytecode still runs
        self.assertTrue(rp.clear_stale_bytecode(root))
        self.assertEqual(self.value(scripts), '20')
        self.assertTrue((scripts / '__pycache__' / rp.BUILD_STAMP).is_file())
        self.assertFalse(rp.clear_stale_bytecode(root))                # same release: nothing to do
        (root / 'DISTRIBUTION-MANIFEST.json').write_text('{"release": "r5d17"}', encoding='utf-8')
        self.assertTrue(rp.clear_stale_bytecode(root))

    def test_a_skill_without_a_manifest_is_left_alone(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        self.assertFalse(rp.clear_stale_bytecode(root))

    def test_the_package_dates_every_entry_with_its_build(self):
        text = (SCRIPTS / 'package_skill.py').read_text(encoding='utf-8')
        self.assertIn('date_time=built', text)


class LabelTests(unittest.TestCase):
    def test_labels_are_rewritten_not_refused(self):
        self.assertEqual(ch.normalized_label('internal_roller_and_hidden_details', set()), 'internal_roller_and_hidden')
        self.assertEqual(ch.normalized_label('Handle-Grip Part', set()), 'handle_grip_part')
        self.assertEqual(ch.normalized_label('roller_body', {'roller_body'}), 'roller_body_2')
        self.assertEqual(ch.normalized_label('123abc', set()), 'p_123abc')
        for value in ('', '***', None):
            self.assertIsNone(ch.normalized_label(value, set()))
        for value in ('x' * 80, 'a_' * 40, 'Ünïcode part'):
            label = ch.normalized_label(value, set())
            self.assertTrue(ch.PART_ID.match(label), label)

    def design_packet(self, normalize):
        return {'units': [{'unit_id': 'CMP-1', 'kind': ch.DESIGN_UNIT,
                           'views': [{'view_id': 'D1', 'evidence_id': 'EV-1'}, {'view_id': 'D2', 'evidence_id': 'EV-2'}]}],
                'product_images': [{'image_id': 'IMG-001'}],
                **({'label_normalization': pipeline_robust.SPEED_REVISION} if normalize else {})}

    @staticmethod
    def design_answer(part_id):
        return {'units': [{'unit_id': 'CMP-1', 'product_state': '手持使用状态', 'overall_visual_relationship': '整体不同',
            'perspective_limitations': '缺少底面', 'views': [
                {'view_id': view, 'result': 'differs', 'reasoning': '轮廓不同', 'right_location': '柄部',
                 'product_location': '提手', 'image_ids': ['IMG-001']} for view in ('D1', 'D2')],
            'design_scope_parts': [{'part_id': part_id, 'description': '内部滚筒', 'treatment': 'excluded',
                                    'interpretation_basis': '虚线绘制'}],
            'similarities': [], 'differences': [], 'unknowns': [], 'assumptions': [], 'lower_if': []}]}

    def test_a_long_part_label_voided_the_batch_and_now_is_shortened(self):
        answer = self.design_answer('internal_roller_and_hidden_details')
        with self.assertRaisesRegex(ValueError, 'COMPARISON_DESIGN_PART_INVALID'):
            ch.decisions_from_output(answer, self.design_packet(False), 's')
        decision = ch.decisions_from_output(answer, self.design_packet(True), 's')[0]
        self.assertEqual([part['part_id'] for part in decision['parts']], ['internal_roller_and_hidden'])

    def test_content_rules_still_refuse(self):
        answer = self.design_answer('roller')
        answer['units'][0]['design_scope_parts'][0]['treatment'] = 'partly'
        with self.assertRaisesRegex(ValueError, 'COMPARISON_DESIGN_PART_INVALID'):
            ch.decisions_from_output(answer, self.design_packet(True), 's')

    def test_a_renamed_implementation_keeps_its_comparisons(self):
        claim = 'A cleaning device comprising a roller and a handle.'
        packet = {'units': [{'unit_id': 'CMP-2', 'claims': [{'number': 1, 'text': claim, 'elements': [
            {'element_id': '1-1', 'quote': 'a roller'}, {'element_id': '1-2', 'quote': 'a handle'}]}]}],
            'product_images': [{'image_id': 'IMG-001'}], 'label_normalization': pipeline_robust.SPEED_REVISION}
        long_id = 'Illustrated-Use-With-The-Cover-Attached'
        answer = {'units': [{'unit_id': 'CMP-2', 'implementations': [{'implementation_id': long_id, 'description': '装罩使用'}],
            'comparisons': [{'implementation_id': long_id, 'claim': 1, 'elements': [
                {'element_id': element, 'result': 'corresponds', 'product_fact': '可见', 'reasoning': '对应',
                 'image_ids': ['IMG-001']} for element in ('1-1', '1-2')]}], 'assumptions': [], 'lower_if': []}]}
        decision = ch.decisions_from_output(answer, packet, 's')[0]
        self.assertEqual(list(decision['implementations']), ['illustrated_use_with_the_cover'])
        self.assertEqual(decision['comparisons'][0]['implementation_id'], 'illustrated_use_with_the_cover')
        packet.pop('label_normalization')
        with self.assertRaisesRegex(ValueError, 'COMPARISON_IMPLEMENTATION_INVALID'):
            ch.decisions_from_output(answer, packet, 's')


class SlotTests(unittest.TestCase):
    def test_the_comparison_runs_in_five_slots_on_new_tasks_only(self):
        limits = {'text_parallel': 3}
        # r9 (run B0GJD92G1K: nine comparison sessions, two queued): six, the machine-wide model slot count
        self.assertEqual(text_triage_host.slot_count(SPEED, ch, limits), 6)
        self.assertEqual(text_triage_host.slot_count({}, ch, limits), 3)
        self.assertEqual(text_triage_host.slot_count(SPEED, ps, limits), 3)       # other drivers keep their slots
        self.assertEqual(text_triage_host.slot_count(SPEED, ds, limits), 3)


class OriginalDedupeTests(unittest.TestCase):
    """The same drawing retained by the SerpApi adapter and by the dossier was sent twice (143 images, 86 distinct)."""

    def packet(self, task):
        from test_report_estimate import PNG
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        rows = []
        for folder, ref in (('serpapi', 'EV-RECORD'), ('dossier', 'EV-FIGURE')):
            image = root / 'raw' / folder / 'D00000.png'
            image.parent.mkdir(parents=True)
            image.write_bytes(PNG)
            rows.append({'evidence_id': ref, 'payload': {'path': str(image), 'sha256': sha256_bytes(PNG), 'bytes': len(PNG),
                         'source_url': 'https://patentimages.storage.googleapis.com/x/USD1075310-20250520-D00000.png'}})
        packet = {'task': task, 'evidence': {'collections': {'sources': rows}}}
        images = module_review.attach_originals(packet, root)
        return packet['retained_originals']['materials'], images

    def test_one_file_content_is_one_material_with_every_source(self):
        materials, images = self.packet(dict(SPEED))
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]['source_refs'], ['EV-RECORD', 'EV-FIGURE'])
        self.assertEqual(len(images), 1)

    def test_older_tasks_keep_one_material_per_path(self):
        materials, images = self.packet({})
        self.assertEqual(len(materials), 2)


class RoundTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / 'run'
        self.root.mkdir()
        self.addCleanup(__import__('shutil').rmtree, self.root.parent, True)

    def sources(self, speed):
        """Round 1 finds candidates, round 2 only reads their exact details, round 3 would find nothing."""
        subject = pipeline(self.root)
        counters, calls = {'progress': 0, 'discovery': 0}, []

        def source_round(stage, robust):
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                counters['progress'] += 1
                counters['discovery'] += 1
            elif len(calls) == 2:
                counters['progress'] += 1
            return False
        with mock.patch.object(subject, 'robust', return_value=True), \
                mock.patch.object(subject, 'speed', return_value=speed), \
                mock.patch.object(subject, 'require_discovery_sources'), \
                mock.patch.object(subject, 'source_round', side_effect=source_round), \
                mock.patch.object(subject, 'progress_signature', side_effect=lambda: [counters['progress']]), \
                mock.patch.object(subject, 'discovery_signature', side_effect=lambda: [counters['discovery']]), \
                mock.patch.object(subject, 'ready', return_value={'ready': False}), \
                mock.patch.object(subject, 'flush_sources', return_value=[]), \
                mock.patch.object(subject, 'external_runs', return_value=[{'run_id': 'R'}]):
            subject.s_sources()
        return calls, subject.state['rounds']

    def test_a_round_that_only_read_details_ends_the_source_stage(self):
        calls, rounds = self.sources(True)
        self.assertEqual(calls, [1, 2])
        self.assertTrue(rounds[-1].get('discovery_idle'))

    def test_older_tasks_still_run_the_idle_round(self):
        calls, _ = self.sources(False)
        self.assertEqual(calls, [1, 2, 3])

    def core(self, speed, ready):
        subject = pipeline(self.root)
        rounds, signature = [], [0]

        def core_round(stage, robust, ran, number):
            rounds.append(number)
            signature[0] += 1
        with mock.patch.object(subject, 'robust', return_value=True), \
                mock.patch.object(subject, 'speed', return_value=speed), \
                mock.patch.object(subject, 'core_round', side_effect=core_round), \
                mock.patch.object(subject, 'progress_signature', side_effect=lambda: [signature[0]]), \
                mock.patch.object(subject, 'ready', return_value={'ready': ready}), \
                mock.patch.object(subject, 'flush_sources', return_value=[]), \
                mock.patch.object(subject, 'call', return_value=(0, '', '')):
            subject.s_core()
        return rounds

    def test_a_ready_core_stage_does_not_run_a_second_round(self):
        self.assertEqual(self.core(True, True), [1])
        self.assertEqual(self.core(True, False), [1, 2, 3])
        self.assertEqual(self.core(False, True), [1, 2, 3])


class DeliveredOutputTests(unittest.TestCase):
    def test_the_completion_status_is_reported(self):
        root = Path(tempfile.mkdtemp()) / 'run'
        root.mkdir()
        self.addCleanup(__import__('shutil').rmtree, root.parent, True)
        subject = pipeline(root)
        out = 'report.html\nindependent_semantic_checks: 1\ncompletion_status: limited_round_closed\n'
        with mock.patch.object(subject, 'call', return_value=(0, out, '')):
            result = subject.s_publish()
        self.assertEqual(result['completion_status'], 'limited_round_closed')

    def test_the_delivered_line_tells_the_agent_not_to_publish_again(self):
        root = Path(tempfile.mkdtemp()) / 'run'
        root.mkdir()
        self.addCleanup(__import__('shutil').rmtree, root.parent, True)
        printed = []
        with mock.patch.object(rp, 'clear_stale_bytecode'), \
                mock.patch.object(rp.Pipeline, 'execute', return_value={'report': 'r.html', 'completion_status': 'complete'}), \
                mock.patch('builtins.print', side_effect=lambda *a, **k: printed.append(a[0] if a else '')):
            self.assertEqual(rp.main(['--task-dir', str(root)]), rp.EXIT_OK)
        line = json.loads(printed[-1])
        self.assertEqual(line['status'], 'delivered')
        self.assertIn('不要再运行 publish_report.py', line['next'])


class DesignVerdictTests(unittest.TestCase):
    """A: the recorded view-by-view comparison of the scope's current design inventory."""
    SCOPE = {'candidate_id': 'CAND-D', 'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design'}

    def verdict(self, results, *, necessary=None, disposition='compared'):
        key = dict(self.SCOPE)
        intake = {**key, 'kind': 'intake', 'event_id': 'E-IN'}
        inventory = {**key, 'kind': 'inventory', 'event_id': 'E-INV', 'intake_event_id': 'E-IN',
                     'reviewer': 'native-comparison-s', 'units': [{'kind': 'design', 'necessary_views':
                                                                  necessary or [v for v, _ in results]}]}
        close = {**key, 'kind': 'comparison', 'event_id': 'E-CMP', 'intake_event_id': 'E-IN', 'unit_id': 'design',
                 'inventory_event_id': 'E-INV', 'disposition': disposition,
                 'views': [{'view_id': v, 'result': r} for v, r in results], 'overall_visual_relationship': '整体不同'}
        import specialty_analysis as sa
        with mock.patch.object(sa, 'events', return_value=[intake, inventory, close]), \
                mock.patch.object(sa, '_intake', return_value=intake):
            return ds.comparison_verdict({'task_id': 'T'}, self.SCOPE)

    def test_plainly_different_views_with_some_unseen_ones_agree_to_exclude(self):
        verdict = self.verdict([('D1', 'differs'), ('D2', 'differs'), ('D3', 'unknown')])
        self.assertTrue(verdict['exclude'])
        self.assertEqual(verdict['counts'], {'corresponds': 0, 'differs': 2, 'unknown': 1})

    def test_a_matching_view_or_too_few_differences_keep_the_design(self):
        self.assertEqual(self.verdict([('D1', 'differs'), ('D2', 'differs'), ('D3', 'corresponds')])['reason'],
                         'view_corresponds')
        self.assertEqual(self.verdict([('D1', 'differs'), ('D2', 'unknown'), ('D3', 'unknown')])['reason'],
                         'too_few_differing_views')
        self.assertEqual(self.verdict([('D1', 'differs'), ('D2', 'differs'), ('D3', 'unknown'), ('D4', 'unknown'),
                                       ('D5', 'unknown')])['reason'], 'too_few_differing_views')
        self.assertEqual(self.verdict([('D1', 'differs'), ('D2', 'differs')], necessary=['D1', 'D2', 'D3'])['reason'],
                         'view_set_mismatch')
        self.assertEqual(self.verdict([('D1', 'differs'), ('D2', 'differs')], disposition='waiting')['reason'],
                         'not_compared')


class DesignCheckOutputTests(unittest.TestCase):
    """B: keep by default; an exclude names two different drawing views with the product pictures."""
    PACKET = {'units': [{'unit_id': 'DSC-1', 'views': [{'view_id': 'D1'}, {'view_id': 'D2'}, {'view_id': 'D3'}]}],
              'product_images': [{'image_id': 'IMG-001'}, {'image_id': 'IMG-002'}]}

    @staticmethod
    def exclude(*views, image='IMG-001', difference='提手与壳体的组合不同'):
        return {'decisions': [{'unit_id': 'DSC-1', 'decision': 'exclude', 'relationship': '整体轮廓明显不同',
                               'difference': difference,
                               'differences': [{'view_id': view, 'image_ids': [image], 'design_feature': '细长柄',
                                                'product_feature': '环形提手'} for view in views]}]}

    def test_a_keep_needs_nothing_else(self):
        out = ds.decisions_from_output({'decisions': [{'unit_id': 'DSC-1', 'decision': 'keep'}]}, self.PACKET, 's')
        self.assertEqual(out, [{'unit_id': 'DSC-1', 'decision': 'keep', 'session': 's'}])

    def test_an_exclude_on_two_views_is_accepted(self):
        out = ds.decisions_from_output(self.exclude('D1', 'D3'), self.PACKET, 's')[0]
        self.assertEqual([item['view_id'] for item in out['differences']], ['D1', 'D3'])

    def test_weak_or_invalid_excludes_are_refused(self):
        for answer, code in ((self.exclude('D1'), 'DESIGN_SCREEN_TWO_VIEWS_REQUIRED'),
                             (self.exclude('D1', 'D1'), 'DESIGN_SCREEN_TWO_VIEWS_REQUIRED'),
                             (self.exclude('D1', 'D9'), 'DESIGN_SCREEN_DIFFERENCE_INVALID'),
                             (self.exclude('D1', 'D2', image='IMG-404'), 'DESIGN_SCREEN_DIFFERENCE_INVALID'),
                             (self.exclude('D1', 'D2', difference='相似度 20%'), 'DESIGN_SCREEN_NUMERIC_SCORE_IS_NOT_A_BASIS'),
                             ({'decisions': []}, 'DESIGN_SCREEN_OUTPUT_UNIT_COVERAGE_INVALID'),
                             ({'decisions': [{'unit_id': 'DSC-1', 'decision': 'maybe'}]}, 'DESIGN_SCREEN_DECISION_INVALID')):
            with self.assertRaisesRegex(ValueError, code):
                ds.decisions_from_output(answer, self.PACKET, 's')

    def test_the_prompt_states_the_owner_rule(self):
        packet = {'schema': 'IPR-DESIGN-SCREEN/1.0', 'product': {}, 'objects': [], 'product_images': [], 'units': []}
        text = ds.prompt(packet)
        self.assertIn('个别共同点', text)
        self.assertIn('只看实线部分', text)
        self.assertIn('至少 2 项', text)


class DesignCommitTests(unittest.TestCase):
    """Both judgments must say plainly different; anything else keeps the design for the final dual review."""
    SCOPE = {'candidate_id': 'CAND-D', 'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design'}

    def commit(self, judgment, verdict):
        task = {'prereview_screen_revision': ps.REVISION, 'prereview_design_revision': ds.REVISION}
        material = {'event_id': 'E-MAT', 'document_version': 'v1'}
        drawings = [{'view_id': 'D1', 'evidence_id': 'EV-1', 'sha256': 'a' * 64}]
        receipt = {'receipt_key': ds._receipt_key(self.SCOPE, material, drawings), 'claims_evidence_ref': 'EV-REC',
                   'publication_number': 'USD1084670S1', 'judgment': judgment}
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        with mock.patch.object(ps, '_context', return_value=(task, {}, {}, {}, {}, {})), \
                mock.patch.object(ps, 'selected_scopes', return_value=[(dict(self.SCOPE), {'annotation_id': 'A-1'}, {})]), \
                mock.patch.object(ds, '_dossier', return_value=(material, {}, drawings)), \
                mock.patch.object(ds, '_receipts', return_value={receipt['receipt_key']: receipt}), \
                mock.patch.object(ds, 'comparison_verdict', return_value=verdict), \
                mock.patch('input_template.triage_decision', return_value=({}, {'included_product_objects': {'PRODUCT'}})), \
                mock.patch.object(ps, '_decision', side_effect=lambda *a, **k: dict(k, candidate_id='CAND-D')) as decision, \
                mock.patch.object(ps, 'commit_exclusions', return_value=(['CAND-D'], [])) as recorder:
            summary = ds.run_commit(root)
        return summary, decision, recorder

    EXCLUDE = {'decision': 'exclude', 'session': 'S1', 'relationship': '整体不同', 'difference': '细长柄对环形提手',
               'differences': [{'view_id': 'D1', 'design_feature': '细长柄', 'product_feature': '环形提手'},
                               {'view_id': 'D2', 'design_feature': '纵向圆柱', 'product_feature': '横置滚筒'}]}

    def test_both_judgments_set_the_design_aside_with_its_number_in_the_reason(self):
        summary, decision, recorder = self.commit(self.EXCLUDE, {'exclude': True, 'counts': {'differs': 5, 'unknown': 1},
                                                                 'reviewer': 'native-comparison-x', 'inventory_event_id': 'E'})
        self.assertEqual(summary['excluded'], ['CAND-D'])
        kwargs = decision.call_args.kwargs
        self.assertEqual(kwargs['reviewer'], 'native-screen-S1')
        self.assertEqual(kwargs['reading_level'], 'image_comparison')
        self.assertIn('USD1084670S1', kwargs['reason'])
        self.assertTrue(ps.screened_reviewer(kwargs['reviewer']))      # stubbed in final-review packets like patents
        recorder.assert_called_once()

    def test_a_disagreeing_comparison_or_a_keep_keeps_the_design(self):
        summary, _, recorder = self.commit(self.EXCLUDE, {'exclude': False, 'reason': 'view_corresponds'})
        self.assertEqual(summary['kept'], [{'candidate_id': 'CAND-D', 'reason': 'comparison_disagrees:view_corresponds'}])
        recorder.assert_not_called()
        summary, _, recorder = self.commit({'decision': 'keep', 'session': 'S1'}, {'exclude': True})
        self.assertEqual(summary['kept'], [{'candidate_id': 'CAND-D', 'reason': 'independent_check_keep'}])
        recorder.assert_not_called()


class GatingTests(unittest.TestCase):
    def test_new_tasks_carry_both_markers(self):
        text = (SCRIPTS / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn("task['pipeline_speed_revision'] = SPEED_REVISION", text)
        self.assertIn("task['prereview_design_revision'] = DESIGN_SCREEN_REVISION", text)

    def test_the_design_screen_needs_both_screen_markers(self):
        self.assertTrue(ds.enabled({'prereview_screen_revision': ps.REVISION, 'prereview_design_revision': ds.REVISION}))
        self.assertFalse(ds.enabled({'prereview_screen_revision': ps.REVISION}))
        self.assertFalse(ds.enabled({'prereview_design_revision': ds.REVISION}))

    def test_an_older_task_reports_not_applicable(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        (root / 'task.json').write_text(json.dumps({'task_id': 'T', 'prereview_screen_revision': ps.REVISION}), encoding='utf-8')
        printed = []
        with mock.patch('builtins.print', side_effect=lambda *a, **k: printed.append(a[0])):
            self.assertEqual(ds.main(['--task-dir', str(root), '--check']), 0)
        self.assertEqual(json.loads(printed[-1])['status'], 'not_applicable')

    def test_the_core_round_runs_the_design_check_beside_the_comparison(self):
        root = Path(tempfile.mkdtemp()) / 'run'
        root.mkdir()
        self.addCleanup(__import__('shutil').rmtree, root.parent, True)
        for design in (True, False):
            subject = pipeline(root)
            parallel, calls = [], []
            with mock.patch.object(subject, 'design_screen', return_value=design), \
                    mock.patch.object(subject, 'ready_sources', return_value=0), \
                    mock.patch.object(subject, 'refine'), \
                    mock.patch.object(subject, 'run_parallel', side_effect=lambda stage, commands: parallel.append(
                        [Path(c[3]).name + ' ' + ' '.join(str(x) for x in c[4:] if str(x).startswith('--check')) for c in commands])
                        or [(0, '', '')] * len(commands)), \
                    mock.patch.object(subject, 'call', side_effect=lambda stage, command, **k: calls.append(
                        Path(command[3]).name + ' ' + ' '.join(str(x) for x in command[4:] if str(x).startswith('--')))
                        or (0, '', '')):
                subject.core_round('core', True, [], 1)
            names = [name.strip() for name in parallel[0]]
            if design:
                self.assertEqual(names, ['comparison_host.py', 'prereview_screen.py', 'design_screen.py --check'])
                self.assertLess(calls.index('prereview_screen.py --task-dir --commit'),
                                calls.index('design_screen.py --task-dir --commit'))
            else:
                self.assertEqual(names, ['comparison_host.py', 'prereview_screen.py'])
                self.assertFalse(any(call.startswith('design_screen.py') for call in calls))


if __name__ == '__main__':
    unittest.main()
