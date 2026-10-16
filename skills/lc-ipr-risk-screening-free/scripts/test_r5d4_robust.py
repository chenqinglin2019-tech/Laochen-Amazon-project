"""r5d4 fixes from the B0FSJBDTF2 real run (about 75 minutes, no report): the computer kept awake, gated discovery
rows left out before the dispatch cap, refused picture cards no longer holding dispatch, six product views chosen
instead of a refused batch, the Google spelling of US design numbers, "no such record" reads closed by the program,
fake-IP downloads only when confirmed, GIF / TIFF originals carried as PNG, candidate ratings bound to the evidence
the publication check accepts, and the licence default in the review prompt."""
import json
import os
import socket
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

ROBUST = {'pipeline_robust_revision': 'robust-v1'}


def gif_bytes(color=(10, 120, 200)):
    from PIL import Image
    out = BytesIO()
    Image.new('RGB', (12, 8), color).save(out, format='GIF')
    return out.getvalue()


class KeepAwakeTests(unittest.TestCase):
    def test_mac_starts_caffeinate_for_this_process_and_stops_it(self):
        from keep_awake import KeepAwake
        process = mock.Mock(pid=5151)
        process.poll.return_value = None
        popen = mock.Mock(return_value=process)
        listed = lambda: '   pid 5151(caffeinate): [0x0001] 00:00:01 PreventUserIdleSystemSleep named: "caffeinate"'
        with KeepAwake(platform='darwin', popen=popen, which=lambda name: '/usr/bin/' + name, pid=4242,
                       check=listed) as awake:
            self.assertEqual(awake.mode, 'caffeinate')
        self.assertEqual(popen.call_args[0][0], ['/usr/bin/caffeinate', '-i', '-s', '-w', '4242'])
        process.terminate.assert_called_once()

    def test_windows_sets_and_clears_the_execution_state(self):
        from keep_awake import KeepAwake, ES_CONTINUOUS, ES_SYSTEM_REQUIRED
        kernel32 = mock.Mock()
        kernel32.SetThreadExecutionState.return_value = 1
        with KeepAwake(platform='win32', kernel32=kernel32) as awake:
            self.assertEqual(awake.mode, 'windows')
        self.assertEqual([c[0][0] for c in kernel32.SetThreadExecutionState.call_args_list],
                         [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS])

    def test_other_systems_and_failures_never_fail_a_run(self):
        from keep_awake import KeepAwake
        with KeepAwake(platform='linux') as awake:
            self.assertEqual(awake.mode, 'none')
        with KeepAwake(platform='darwin', which=lambda name: None) as awake:
            self.assertEqual(awake.mode, 'unavailable')
        broken = mock.Mock(side_effect=OSError('no caffeinate'))
        with KeepAwake(platform='darwin', popen=broken, which=lambda name: '/usr/bin/caffeinate') as awake:
            self.assertEqual(awake.mode, 'unavailable')


class DispatchTests(unittest.TestCase):
    def test_gated_rows_are_left_out_before_the_cap(self):
        import pipeline_robust
        entries = [{'query_id': 'Q1'}, {'query_id': 'Q2'}, {'query_id': 'Q3'}]
        with mock.patch.object(pipeline_robust, 'gated_queries', return_value={'Q2': 'API_DISCOVERY_DIRECTION_REVIEW_REQUIRED'}):
            ready, held = pipeline_robust.dispatchable('/nowhere', {}, entries)
        self.assertEqual([row['query_id'] for row in ready], ['Q1', 'Q3'])
        self.assertEqual(held, {'Q2': 'API_DISCOVERY_DIRECTION_REVIEW_REQUIRED'})
        self.assertEqual(pipeline_robust.dispatchable('/nowhere', {}, []), ([], {}))

    def test_advance_work_leaves_gated_rows_out_only_for_robust_tasks(self):
        text = (Path(__file__).parent / 'advance_work.py').read_text(encoding='utf-8')
        self.assertIn('pipeline_robust', text)
        self.assertIn('source_dispatch_gated', text)

    def test_refused_picture_cards_do_not_hold_dispatch(self):
        import pipeline_robust
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(pipeline_robust.refused_work_ids(root), set())
            (root / 'visual-triage').mkdir()
            (root / 'visual-triage' / 'last-run.json').write_text(json.dumps({'batches': [
                {'status': 'needs_info', 'phase': 'preparation', 'work_ids': ['W1', 'W2']},
                {'status': 'needs_info', 'phase': 'media', 'work_ids': ['W3']},
                {'status': 'needs_info', 'phase': 'session', 'work_ids': ['W4']},
                {'status': 'recorded', 'phase': 'preparation', 'work_ids': ['W5']}]}), encoding='utf-8')
            self.assertEqual(pipeline_robust.refused_work_ids(root), {'W1', 'W2', 'W3'})
            view = {'entries': [{'work_id': 'W1', 'kind': 'light_triage'}]}
            with mock.patch('candidate_triage_stage.light_triage_pending', side_effect=lambda v: bool(v['entries'])):
                self.assertFalse(pipeline_robust.light_triage_pending(view, root))
                self.assertTrue(pipeline_robust.light_triage_pending({'entries': [{'work_id': 'W9'}]}, root))


class ProductViewTests(unittest.TestCase):
    def test_seven_views_give_the_first_six_in_order_and_duplicates_are_free(self):
        from pipeline_robust import choose_product_views
        rows = [('IMG-%d' % i, {'sha256': 'h%d' % i}) for i in range(1, 8)]
        kept, omitted = choose_product_views(rows, 6)
        self.assertEqual([ref for ref, _ in kept], ['IMG-1', 'IMG-2', 'IMG-3', 'IMG-4', 'IMG-5', 'IMG-6'])
        self.assertEqual(omitted, ['IMG-7'])
        self.assertEqual(choose_product_views(rows, 6), (kept, omitted))           # deterministic
        rows.insert(2, ('IMG-1b', {'sha256': 'h1'}))
        kept, omitted = choose_product_views(rows, 6)
        self.assertIn('IMG-1b', [ref for ref, _ in kept])
        self.assertEqual(omitted, ['IMG-7'])

    def test_visual_host_chooses_instead_of_refusing(self):
        text = (Path(__file__).parent / 'visual_triage_host.py').read_text(encoding='utf-8')
        self.assertIn('choose_product_views', text)


class DesignNumberTests(unittest.TestCase):
    def test_docdb_design_numbers_take_the_google_spelling(self):
        from common import canonical_patent_number
        self.assertEqual(canonical_patent_number('USD1110120S'), 'USD1110120S1')
        self.assertEqual(canonical_patent_number('USD01151082S'), 'USD1151082S1')
        self.assertEqual(canonical_patent_number('USD887770S1'), 'USD887770S1')
        self.assertEqual(canonical_patent_number('USD300000S'), 'USD300000S')      # before the S1 kind code
        self.assertEqual(canonical_patent_number('US11401089B2'), 'US11401089B2')
        self.assertEqual(canonical_patent_number('US2018201441A1'), 'US20180201441A1')

    def test_detail_request_uses_the_google_spelling(self):
        import candidate_api_actions
        candidate = {'candidate_id': 'CAND-1', 'publication_number': 'USD1151082S', 'right_type': 'design'}
        options = candidate_api_actions._options({}, {}, candidate, 'US', 'design', {'identity'}, {})
        detail = [params for provider, operation, params, *_ in options if operation == 'candidate_detail']
        self.assertEqual(detail[0]['patent_id'], 'patent/USD1151082S1/en')
        self.assertEqual(detail[0]['q'], 'USD1151082S1')

    def test_design_picture_number(self):
        from pipeline_robust import us_design_number
        self.assertEqual(us_design_number({'right_type': 'design', 'publication_number': 'USD1151082S'}), 'USD1151082S1')
        self.assertIsNone(us_design_number({'right_type': 'patent', 'publication_number': 'US11401089B2'}))
        self.assertIsNone(us_design_number({'right_type': 'design', 'publication_number': 'EM0012345670001'}))


class RecordAbsentTests(unittest.TestCase):
    def test_closeouts_do_nothing_for_older_tasks(self):
        import pipeline_robust
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'task.json').write_text(json.dumps({'task_id': 't'}), encoding='utf-8')
            self.assertEqual(pipeline_robust.close_record_not_found(root), {'recorded': 0, 'closed': [], 'rejected': []})

    def test_record_absent_codes_and_proof_are_wired(self):
        import recovery_stage_b
        self.assertIn('PROVIDER_RECORD_NOT_FOUND', recovery_stage_b.RECORD_ABSENT_CODES)
        self.assertTrue(callable(recovery_stage_b.record_absent_no_retry_proof))
        text = (Path(__file__).parent / 'necessary_completion.py').read_text(encoding='utf-8')
        self.assertIn('no_retry_limit_proof', text)


class FakeIpTests(unittest.TestCase):
    def setUp(self):
        import candidate_media
        self.cm = candidate_media
        self.saved = dict(candidate_media._FAKE_IP_MODE)

    def tearDown(self):
        self.cm._FAKE_IP_MODE.clear()
        self.cm._FAKE_IP_MODE.update(self.saved)

    def resolve(self, *addresses):
        rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)) for address in addresses]
        return mock.patch.object(self.cm.socket, 'getaddrinfo', return_value=rows)

    def test_fake_ip_block_is_allowed_only_when_the_probe_confirmed_it(self):
        url = 'https://patentimages.storage.googleapis.com/a/b.png'
        self.cm._FAKE_IP_MODE['value'] = True
        with self.resolve('198.18.0.7'):
            self.assertEqual(self.cm.public_address(url)[1], '198.18.0.7')
        self.cm._FAKE_IP_MODE['value'] = False
        with self.resolve('198.18.0.7'), self.assertRaises(ValueError):
            self.cm.public_address(url)

    def test_other_private_addresses_stay_refused_even_in_fake_ip_mode(self):
        url = 'https://patents.google.com/patent/USD1151082S1/en'
        self.cm._FAKE_IP_MODE['value'] = True
        for address in ('10.0.0.5', '127.0.0.1', '192.168.1.2', '169.254.1.1'):
            with self.resolve(address), self.assertRaises(ValueError):
                self.cm.public_address(url)
        with self.resolve('198.18.0.7', '10.0.0.5'), self.assertRaises(ValueError):
            self.cm.public_address(url)
        with self.resolve('142.250.1.1'):
            self.assertEqual(self.cm.public_address(url)[1], '142.250.1.1')


class GifTests(unittest.TestCase):
    def test_gif_becomes_a_deterministic_png(self):
        import image_convert
        data = gif_bytes()
        png = image_convert.to_png(data)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(png, image_convert.to_png(data))
        with self.assertRaises(ValueError):
            image_convert.to_png(png)                         # only GIF / TIFF are converted
        with self.assertRaises(ValueError):
            image_convert.to_png(b'not an image')

    def test_registration_keeps_the_original_beside_the_png(self):
        from record_public_source import image_payload
        from common import sha256_bytes
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gazette.gif'
            data = gif_bytes()
            path.write_bytes(data)
            payload = {'path': str(path), 'sha256': sha256_bytes(data), 'bytes': len(data), 'kind': 'patent_drawing_image'}
            result = image_payload(payload, path)
            self.assertTrue(result['path'].endswith('gazette.gif.png'))
            self.assertEqual(result['sha256'], sha256_bytes(Path(result['path']).read_bytes()))
            self.assertEqual(result['derived_from']['original_sha256'], payload['sha256'])
            self.assertEqual(result['derived_from']['original_format'], 'GIF')
            self.assertEqual(image_payload(payload, path), result)                  # repeatable
            png = Path(tmp) / 'a.png'
            png.write_bytes(b'x')
            self.assertEqual(image_payload({'path': str(png)}, png), {'path': str(png)})
            bmp = Path(tmp) / 'a.bmp'
            bmp.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'PUBLIC_SOURCE_IMAGE_FORMAT_UNSUPPORTED'):
                image_payload({'path': str(bmp)}, bmp)

    def test_preflight_checks_the_inventory_before_sessions(self):
        text = (Path(__file__).parent / 'review_preflight.py').read_text(encoding='utf-8')
        self.assertIn('validate_inventory', text)


class BindingTests(unittest.TestCase):
    def check(self, row, refs=None):
        from module_review import candidate_row_binding_problem
        return candidate_row_binding_problem(row, {'C1': ['EV-rec'], 'C2': []} if refs is None else refs)

    def test_rated_rows_must_cite_bindable_evidence(self):
        low = {'candidate_id': 'C1', 'risk': '低', 'counter_evidence': [{'evidence_refs': ['EV-draw']}],
               'comparison': {'criteria': [{'criterion': 'overall'}]}}
        self.assertIn('every counter_evidence', self.check(low))
        low['counter_evidence'][0]['evidence_refs'].append('EV-rec')
        self.assertIsNone(self.check(low))
        del low['comparison']
        self.assertIn('comparison.criteria', self.check(low))
        very_low = {'candidate_id': 'C1', 'risk': '极低', 'decisive_exclusion': {'evidence_refs': ['EV-draw']}}
        self.assertIn('decisive_exclusion', self.check(very_low))
        very_low['decisive_exclusion']['evidence_refs'] = ['EV-rec']
        self.assertIsNone(self.check(very_low))
        high = {'candidate_id': 'C1', 'risk': '高', 'supporting_evidence': [{'evidence_refs': ['EV-draw', 'IMG-001']}]}
        self.assertIn('supporting_evidence', self.check(high))
        high['supporting_evidence'].append({'evidence_refs': ['EV-rec']})
        self.assertIsNone(self.check(high))

    def test_unlisted_candidates_and_unbindable_candidates(self):
        self.assertIn('ASSESSMENT_REQUIRES_CURRENT_SELECTED_TRIAGE', self.check({'candidate_id': 'C9', 'risk': '低'}))
        self.assertIsNone(self.check({'candidate_id': 'C2', 'risk': '高', 'supporting_evidence': []}))  # cannot repair
        self.assertIsNone(self.check({'candidate_id': 'C1', 'risk': None}))
        self.assertIsNone(self.check({'candidate_id': None, 'risk': '低'}))


class PromptRuleTests(unittest.TestCase):
    def test_licence_default_and_binding_rules_follow_the_markers(self):
        import report_review_host as host
        import pipeline_robust
        self.assertTrue(pipeline_robust.review_rules_enabled(ROBUST))
        self.assertTrue(pipeline_robust.review_rules_enabled({'review_focus_revision': 'review-focus-v1'}))
        self.assertFalse(pipeline_robust.review_rules_enabled({}))
        self.assertIn('许可', host.LICENSE_DEFAULT_RULE)
        self.assertIn('candidate_counter_refs', host.CANDIDATE_BINDING_RULE)
        text = (Path(__file__).parent / 'report_review_host.py').read_text(encoding='utf-8')
        self.assertIn('pipeline_robust.review_rules_enabled(task)', text)


class PipelineOrderTests(unittest.TestCase):
    def test_new_tasks_carry_both_markers(self):
        text = (Path(__file__).parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn("task['pipeline_robust_revision'] = ROBUST_REVISION", text)
        self.assertIn("task['prereview_screen_revision'] = SCREEN_REVISION", text)

    def test_dry_run_lists_the_core_screen_steps(self):
        import run_pipeline
        core = ' '.join(run_pipeline.COMMANDS['core'])
        for step in ('prereview_screen.py --status', 'prereview_screen.py --claims', 'prereview_screen.py --commit'):
            self.assertIn(step, core)
        self.assertLess(core.index('--status'), core.index('--claims'))
        self.assertLess(core.index('--claims'), core.index('--commit'))
        self.assertIn('catch-up', ' '.join(run_pipeline.COMMANDS['readiness']))


if __name__ == '__main__':
    unittest.main()
