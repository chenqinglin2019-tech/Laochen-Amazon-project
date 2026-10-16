"""r5d8: the USPTO grant PDF is the design's protection material; sleep is detected and reported (B0GLNPC6K8 new task).

The new task stopped at checkpoint 2 with two selected US designs whose grant PDFs the program had retained: one had
no SerpApi record and no Google page (intake pending), the other had a record whose drawings Google refuses
(protection unknown, so the view comparison never ran). The full flow was replayed on a copy of that run (both
designs compared, readiness passes); these tests pin the pieces.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import atomic_write_json
import core_dossier
import pipeline_robust

USPTO = pipeline_robust.USPTO_PDF + 'D1140376'
CID = 'CAND-aad8df531e8432244c'


def page_entry(number, page, evidence_id=None, url=USPTO):
    return {'evidence_id': evidence_id or 'EV-P%02d' % page, 'collected_at': '2026-10-13T03:37:31Z',
            'payload': {'kind': 'patent_drawing_image', 'candidate_id': CID, 'publication_number': number,
                        'figure_label': 'USPTO-P%02d' % page, 'source_url': url, 'path': '/x/page-%02d.png' % page,
                        'sha256': 'h%d' % page, 'derived_from': {'page_number': page, 'original_sha256': 'pdf'}}}


def evidence_with_pages(pages=(2, 1, 3)):
    google = {'evidence_id': 'EV-G', 'payload': {'kind': 'patent_drawing_image', 'candidate_id': CID,
                                                'publication_number': 'USD1140376S1', 'figure_label': 'D00000',
                                                'source_url': 'https://patentimages.storage.googleapis.com/x.png'}}
    return {'collections': {'sources': [google] + [page_entry('USD1140376S1', n) for n in pages]}}


class GrantMaterialTests(unittest.TestCase):
    def test_grant_pages_in_page_order_only_from_the_official_file(self):
        grant = core_dossier.uspto_grant(evidence_with_pages(), CID)
        self.assertEqual((grant['number'], grant['pages'], grant['evidence_refs']),
                         ('USD1140376S1', [1, 2, 3], ['EV-P01', 'EV-P02', 'EV-P03']))
        self.assertIsNone(core_dossier.uspto_grant(evidence_with_pages(), 'CAND-other'))
        self.assertIsNone(core_dossier.uspto_grant({'collections': {'sources': []}}, CID))

    def test_grant_batch_uses_a_known_import_id_and_accounts_every_page(self):
        grant = core_dossier.uspto_grant(evidence_with_pages(), CID)
        batch = core_dossier._grant_batch(grant, 'm_uspto')
        self.assertEqual(batch['batch_id'], 'import:EV-P01')
        self.assertEqual(set(batch['disposition_by_evidence_ref']), {'EV-P01', 'EV-P02', 'EV-P03'})
        material = core_dossier._grant_material(grant, 'm', ['protection'], ['protection'], '2026-10-13')
        self.assertEqual((material['source_form'], material['document_version'], material['status']),
                         ('original_document', 'uspto-2026-10-13', 'sufficient_for_listed_purposes'))


class BaseRequestTests(unittest.TestCase):
    """The request shapes; the replay recorded them through the real validators."""

    def setUp(self):
        self.scope = {'candidate_id': CID, 'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design'}
        self.grant = core_dossier.uspto_grant(evidence_with_pages(), CID)
        self.candidates = {'patents': [{'candidate_id': CID, 'title': 'Automatic laser cat toy', 'evidence_refs': ['EV-CARD']}]}
        self.indexed = {ref: {} for ref in ('EV-P01', 'EV-P02', 'EV-P03', 'EV-CARD', 'EV-PROD', 'EV-API')}
        handoff = {'event_id': 'H1', 'verification_gaps': ['完整视图与保护范围尚未读取', '当前法律状态与权利人尚未核验']}
        patches = [mock.patch('specialty_analysis._current', return_value={'annotation': {'annotation_id': 'A1'}}),
                   mock.patch.object(core_dossier, '_handoff', return_value=handoff),
                   mock.patch.object(core_dossier, 'product_evidence', return_value={
                       'evidence_id': 'EV-PROD', 'image_ids': ['IMG-001'], 'description': '逗猫玩具', 'statements': []})]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def request(self, detail=None, history=()):
        with mock.patch('specialty_analysis._intake', return_value=history[0] if history else None), \
                mock.patch('specialty_analysis.events', return_value=list(history)):
            return core_dossier.base_request({'task_id': 'T'}, {}, self.candidates, {}, None, self.indexed,
                                             self.scope, detail, today='2026-10-13', grant=self.grant)

    def test_no_record_and_no_page_the_grant_is_the_record_material(self):
        request, info = self.request()
        events = {row.get('alias'): row for row in request['events']}
        self.assertEqual(info['supported_facts'], ['identity', 'protection'])
        self.assertEqual(events['m_api']['source_form'], 'original_document')
        self.assertEqual(events['m_api']['evidence_refs'], ['EV-P01', 'EV-P02', 'EV-P03'])
        outcomes = {row['fact_kind']: row['outcome'] for row in request['events'] if row['kind'] == 'fact'}
        self.assertEqual(outcomes, {'identity': 'supported', 'protection': 'supported', 'territory': 'unknown',
                                    'status': 'unknown', 'rights_holder': 'unknown', 'product': 'supported'})
        self.assertEqual(events['f_protection']['resolves_handoff_gaps'], ['完整视图与保护范围尚未读取'])
        self.assertIn('USPTO', events['f_identity']['raw_statement'])
        batches = [row for row in request['events'] if row['kind'] == 'batch']
        self.assertEqual(batches[0]['batch_id'], 'import:EV-P01')
        self.assertIn('import:EV-CARD', [row['batch_id'] for row in batches])

    def test_a_record_without_drawings_gets_the_grant_as_its_protection(self):
        detail = {'evidence_id': 'EV-API', 'collected_at': '2026-10-13T03:47:18Z',
                  'payload': {'publication_number': 'USD1140376S1', 'title': 'Automatic laser cat toy',
                              'legal_status': 'Active', 'claims': ['The ornamental design for a cat toy.']}}
        supported = {'identity', 'territory', 'status'}
        with mock.patch('trusted_api.bind_material_candidate', side_effect=lambda task, request, c: request), \
                mock.patch('trusted_api.material_support',
                           side_effect=lambda task, draft, indexed, fact, evidence=None: fact in supported):
            request, info = self.request(detail)
        events = {row.get('alias'): row for row in request['events']}
        self.assertEqual(events['m_api']['source_form'], 'trusted_api_record')
        self.assertEqual(events['m_uspto']['supported_facts'], ['protection'])
        protection = events['f_protection']
        self.assertEqual((protection['outcome'], protection['material_event_ids'], protection['document_version']),
                         ('supported', [{'$event': 'm_uspto'}], 'uspto-2026-10-13'))
        self.assertEqual(protection['evidence_refs'], ['EV-P01'])
        self.assertLess([row.get('alias') for row in request['events']].index('m_uspto'),
                        [row.get('alias') for row in request['events']].index('f_protection'))
        self.assertIn('import:EV-P01', [row['batch_id'] for row in request['events'] if row['kind'] == 'batch'])

    def test_an_earlier_program_intake_without_protection_is_amended_in_place(self):
        intake = {'event_id': 'I1', 'kind': 'intake', 'selected_handoff_event_id': 'H1',
                  'verification_gaps': ['完整视图与保护范围尚未读取', '当前法律状态与权利人尚未核验']}
        mine = [intake, {'kind': 'material', 'intake_event_id': 'I1', 'reviewer': core_dossier.REVIEWER,
                         'status': 'sufficient_for_listed_purposes', 'supported_facts': ['identity']}]
        request, info = self.request(history=mine)
        self.assertEqual(info['amended'], 'uspto_grant')
        self.assertEqual([row['kind'] for row in request['events']], ['material', 'fact', 'batch'])
        self.assertEqual(request['events'][1]['resolves_handoff_gaps'], ['完整视图与保护范围尚未读取'])
        # once protection is supported, nothing more is added
        mine.append({'kind': 'material', 'intake_event_id': 'I1', 'reviewer': core_dossier.REVIEWER,
                     'status': 'sufficient_for_listed_purposes', 'supported_facts': ['protection']})
        self.assertEqual(self.request(history=mine), (None, 'already_recorded'))
        # an Agent's own specialty events are never amended
        mine[-1]['reviewer'] = 'agent'
        mine[-1]['supported_facts'] = ['identity']
        self.assertEqual(self.request(history=mine), (None, 'already_recorded'))


class RecordGapPlannedTests(unittest.TestCase):
    def test_planner_row_is_enough_without_an_intake(self):
        scope = {'candidate_id': CID, 'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design'}
        row = {**scope, 'code': 'API_RECORD_FACT_GAP', 'required_facts': ['identity']}
        plan = {'candidate_action_gaps': [row], 'queries': {}}
        candidates = {'patents': [{'candidate_id': CID}]}
        with mock.patch.object(core_dossier, '_capabilities', return_value={}), \
                mock.patch('specialty_analysis._current', return_value={}), \
                mock.patch('specialty_analysis._intake', return_value=None), \
                mock.patch('candidate_api_actions.append', return_value=[row]):
            self.assertTrue(core_dossier.record_gap_planned(None, {}, {}, candidates, {}, None, plan, scope))
        with mock.patch.object(core_dossier, '_capabilities', return_value={}), \
                mock.patch('specialty_analysis._current', return_value={}), \
                mock.patch('candidate_api_actions.append', return_value=[]):
            # the current planner no longer lists it: the scope keeps waiting for its record
            self.assertFalse(core_dossier.record_gap_planned(None, {}, {}, candidates, {}, None, plan, scope))
        self.assertFalse(core_dossier.record_gap_planned(None, {}, {}, candidates, {}, None,
                                                         {'candidate_action_gaps': []}, scope))


class SleepTests(unittest.TestCase):
    def test_mac_keep_awake_is_checked_against_the_system_list(self):
        from keep_awake import KeepAwake
        process = mock.Mock(pid=77)
        process.poll.return_value = None
        popen = mock.Mock(return_value=process)
        which = lambda name: '/usr/bin/' + name
        with KeepAwake(platform='darwin', popen=popen, which=which, check=lambda: 'pid 77(caffeinate): [0x1] x') as awake:
            self.assertEqual(awake.mode, 'caffeinate')
        with KeepAwake(platform='darwin', popen=popen, which=which, check=lambda: 'pid 9(other)') as awake:
            self.assertEqual(awake.mode, 'caffeinate_unconfirmed')
        process.poll.return_value = 1
        with KeepAwake(platform='darwin', popen=popen, which=which, check=lambda: '') as awake:
            self.assertEqual(awake.mode, 'caffeinate_exited')

    def test_wall_clock_beyond_process_clock_is_logged_and_reported(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as root:
            args = mock.Mock(task_dir=root, guard_session_id='s', chief=None)
            pipeline = run_pipeline.Pipeline(args)
            pipeline.note_sleep('sources', 'provenance_host.py', 30.0, 29.5)
            self.assertEqual(pipeline.sleep_notice(), {})
            pipeline.note_sleep('sources', 'provenance_host.py', 1645.0, 68.3)
            pipeline.note_sleep('sources', 'discovery_review_host.py', 461.4, 71.3)
            notice = pipeline.sleep_notice()
            self.assertEqual(notice['slept_minutes'], 33)
            self.assertIn('不要合盖', notice['sleep_warning'])
            log = (Path(root) / run_pipeline.LOG_FILE).read_text(encoding='utf-8')
            self.assertEqual(log.count('"system_sleep"'), 2)


if __name__ == '__main__':
    unittest.main()
