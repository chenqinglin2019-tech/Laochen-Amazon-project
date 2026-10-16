"""v2 media budgets, durable completed URLs and bounded receipt validation."""
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from candidate_media import collect, download, MediaBudgetExhausted, MediaDownloadError
from common import atomic_write_json, load_json, sha256_file
from offline_test_support import isolated_test_environment
import test_execution_efficiency


class MediaBudgetRevisionTests(unittest.TestCase):
    def setUp(self):
        environment = isolated_test_environment(); environment.__enter__()
        self.addCleanup(environment.__exit__, None, None, None)
        self.fixture = test_execution_efficiency.MediaTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.f.root
        self.ids = self.fixture.ids

    def result(self, url, **kwargs):
        return self.fixture.image, '.png', (20, 20), url

    def distinct_urls(self, count=6, alternate=False, title_suffix=''):
        from source_result_processing import make_index
        raw = {'visual_matches': [{'title': 'Towel ' + str(i) + title_suffix, 'link': 'https://example.test/' + str(i),
            'image': 'https://images.example.test/' + str(i) + '.png',
            **({'thumbnail': 'https://images.example.test/alternate.png'} if alternate else {})}
            for i in range(count)]}
        path = self.root / 'lens.json'; atomic_write_json(path, raw)
        evidence = load_json(self.root / 'evidence.json')
        run = next(r for r in evidence['source_runs'] if r['run_id'] == 'LENS-R')
        run['payload_digest'] = sha256_file(path)
        run['result_processing'] = make_index(load_json(self.root / 'task.json'), provider='serpapi_google_lens',
            evidence_type='copyright', status='success', submission_state='submitted', raw_body=path.read_bytes(),
            raw_suffix='json', normalized={}, coverage={'schema_valid': True, 'retrieved_hits': count},
            payload_digest=run['payload_digest'])
        candidates = load_json(self.root / 'normalized-candidates.json')
        candidates['copyright_assets'] = candidates['copyright_assets'][:count]
        for candidate, row in zip(candidates['copyright_assets'], run['result_processing']['rows']):
            candidate['sources'][0]['source_record_sha256'] = row['raw_sha256']
        atomic_write_json(self.root / 'evidence.json', evidence)
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)
        self.ids = self.ids[:count]

    def test_budget_before_request_is_not_a_failed_or_attempted_url(self):
        self.distinct_urls(1, alternate=True)
        with patch('candidate_media.public_address') as dns, \
                patch('candidate_media.ThreadPoolExecutor.submit') as submit, self.assertRaises(MediaBudgetExhausted):
            collect(self.root, self.ids, deadline=time.time() - 1)
        dns.assert_not_called()
        submit.assert_not_called()
        cache = load_json(self.root / 'candidate-media.json')
        self.assertEqual(cache['urls'], {})
        self.assertEqual(cache['candidates'][self.ids[0]]['attempted'], [])
        with patch('candidate_media.download', side_effect=self.result) as fetch:
            result = collect(self.root, self.ids, deadline=time.time() + 10)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result[self.ids[0]]['status'], 'retained')

    def test_expired_budget_can_reuse_current_images_without_network_submission(self):
        with patch('candidate_media.download', side_effect=self.result):
            before = collect(self.root, self.ids)
        with patch('candidate_media.download') as fetch:
            after = collect(self.root, self.ids, deadline=time.time() - 1)
        fetch.assert_not_called()
        self.assertEqual(after, before)

    def test_expired_budget_does_not_rebind_a_stale_cached_url_to_changed_receipt(self):
        self.distinct_urls(1)
        with patch('candidate_media.download', side_effect=self.result):
            collect(self.root, self.ids)
        prior = load_json(self.root / 'candidate-media.json')['urls']
        self.distinct_urls(1, title_suffix=' changed source content')
        with patch('candidate_media.download') as fetch, self.assertRaises(MediaBudgetExhausted):
            collect(self.root, self.ids, deadline=time.time() - 1)
        fetch.assert_not_called()
        cache = load_json(self.root / 'candidate-media.json')
        self.assertEqual(cache['urls'], prior)
        self.assertEqual(cache['candidates']['C0']['status'], 'needs_info')
        self.assertEqual(cache['candidates']['C0']['attempted'], [])

    def test_historical_ambiguous_failure_stays_unknown_and_is_not_retried(self):
        url = 'https://images.example.test/shared.png'
        old = {'status': 'failed', 'reason': 'TimeoutError:MEDIA_TIMEOUT', 'checked_at': 'historical'}
        atomic_write_json(self.root / 'candidate-media.json', {'schema': 'IPR-CANDIDATE-MEDIA/1.0',
            'urls': {url: old}, 'candidates': {}})
        with patch('candidate_media.download') as fetch:
            collect(self.root, self.ids, deadline=time.time() + 10)
        fetch.assert_not_called()
        self.assertEqual(load_json(self.root / 'candidate-media.json')['urls'][url], old)

    def test_started_budget_interruption_remains_no_retry_and_skips_alternate(self):
        self.distinct_urls(1, alternate=True)
        with patch('candidate_media.download', side_effect=MediaBudgetExhausted(True)) as fetch, \
                self.assertRaises(MediaBudgetExhausted):
            collect(self.root, self.ids, deadline=time.time() + 10)
        self.assertEqual(fetch.call_count, 1)
        cache = load_json(self.root / 'candidate-media.json')
        failed = cache['urls']['https://images.example.test/0.png']
        self.assertEqual(failed['failure_kind'], 'execution_budget')
        self.assertIs(failed['request_started'], True)
        self.assertNotIn('https://images.example.test/alternate.png', cache['urls'])
        with patch('candidate_media.download', side_effect=self.result) as fetch:
            collect(self.root, self.ids, deadline=time.time() + 10)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ['https://images.example.test/alternate.png'])

    def test_receipt_is_validated_twice_for_18_shared_candidates(self):
        import source_result_processing
        with patch('source_result_processing._retained_run', wraps=source_result_processing._retained_run) as validate, \
                patch('candidate_media.download', side_effect=self.result) as fetch:
            collect(self.root, self.ids)
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(fetch.call_count, 1)

    def test_changed_original_after_download_still_rejects_registration(self):
        def changed(url, **kwargs):
            result = self.result(url)
            (self.root / 'lens.json').write_text('{}')
            return result
        with patch('candidate_media.download', side_effect=changed), self.assertRaisesRegex(ValueError, 'CHANGED|MISMATCH'):
            collect(self.root, self.ids)
        self.assertFalse((self.root / 'supplemental-evidence.json').exists())

    def test_fast_success_is_checkpointed_before_slow_first_url_and_survives_budget_stop(self):
        self.distinct_urls(4)
        checkpoint_seen = threading.Event()
        def fetch(url, **kwargs):
            if url.endswith('/1.png'):
                return self.result(url)
            end = time.monotonic() + 3
            while time.monotonic() < end:
                path = self.root / 'candidate-media.json'
                if path.is_file() and 'https://images.example.test/1.png' in load_json(path)['urls']:
                    checkpoint_seen.set()
                    raise MediaBudgetExhausted(url.endswith('/0.png'))
                time.sleep(.005)
            raise AssertionError('Completion-order checkpoint did not occur')
        with patch('candidate_media.download', side_effect=fetch), self.assertRaises(MediaBudgetExhausted):
            collect(self.root, self.ids)
        self.assertTrue(checkpoint_seen.is_set())
        cache = load_json(self.root / 'candidate-media.json')
        self.assertEqual(cache['candidates']['C1']['status'], 'retained')
        self.assertEqual(cache['candidates']['C2']['attempted'], [])
        self.assertEqual(len(load_json(self.root / 'supplemental-evidence.json')['evidence']), 1)
        with patch('candidate_media.download', side_effect=self.result) as fetch:
            collect(self.root, self.ids)
        self.assertEqual({call.args[0] for call in fetch.call_args_list},
                         {'https://images.example.test/2.png', 'https://images.example.test/3.png'})

    def test_no_more_than_four_downloads_are_in_flight(self):
        self.distinct_urls(12)
        lock = threading.Lock(); state = {'active': 0, 'maximum': 0}
        def fetch(url, **kwargs):
            with lock:
                state['active'] += 1; state['maximum'] = max(state['maximum'], state['active'])
            time.sleep(.01)
            with lock: state['active'] -= 1
            return self.result(url)
        with patch('candidate_media.download', side_effect=fetch):
            collect(self.root, self.ids)
        self.assertEqual(state['maximum'], 4)

    def test_legacy_task_does_not_silently_migrate_cached_budget_behavior(self):
        task = load_json(self.root / 'task.json'); task['execution_efficiency_revision'] = 'execution-efficiency-v1'
        atomic_write_json(self.root / 'task.json', task)
        with patch('candidate_media.public_address') as dns:
            collect(self.root, self.ids, deadline=time.time() - 1)
        dns.assert_not_called()
        row = next(iter(load_json(self.root / 'candidate-media.json')['urls'].values()))
        self.assertEqual(row['status'], 'failed')
        self.assertNotIn('request_started', row)

    def test_real_downloader_distinguishes_shared_and_url_deadlines(self):
        class Socket:
            def __init__(self): self.closed = threading.Event()
            def settimeout(self, value): pass
            def shutdown(self, how): self.closed.set()
        class Connection:
            def __init__(self, *args): self.sock = Socket()
            def request(self, *args, **kwargs): pass
            def getresponse(self):
                self.sock.closed.wait(1)
                raise OSError('Deadline closed the socket')
            def close(self): pass
        with patch('candidate_media.public_address', return_value=(urlsplit('https://example.com/a'), '8.8.8.8')), \
                patch('candidate_media.PublicConnection', Connection):
            with self.assertRaises(MediaBudgetExhausted) as budget:
                download('https://example.com/a', timeout=1, deadline=time.time() + .02, revised_budget=True)
            self.assertIs(budget.exception.request_started, True)
            with self.assertRaises(MediaDownloadError) as url:
                download('https://example.com/a', timeout=.02, deadline=time.time() + 1, revised_budget=True)
            self.assertIs(url.exception.request_started, True)

    def test_budget_shutdown_eof_is_not_misreported_as_an_invalid_image(self):
        class Socket:
            def __init__(self): self.closed = threading.Event()
            def settimeout(self, value): pass
            def shutdown(self, how): self.closed.set()
        class Response:
            status = 200
            def __init__(self, sock): self.sock = sock
            def getheader(self, name): return None
            def read1(self, size):
                self.sock.closed.wait(1)
                return b''
        class Connection:
            def __init__(self, *args): self.sock = Socket()
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response(self.sock)
            def close(self): pass
        with patch('candidate_media.public_address', return_value=(urlsplit('https://example.com/a'), '8.8.8.8')), \
                patch('candidate_media.PublicConnection', Connection), patch('candidate_media.decode_image') as decode, \
                self.assertRaises(MediaBudgetExhausted) as stopped:
            download('https://example.com/a', timeout=1, deadline=time.time() + .02, revised_budget=True)
        self.assertIs(stopped.exception.request_started, True)
        decode.assert_not_called()


if __name__ == '__main__':
    unittest.main()
