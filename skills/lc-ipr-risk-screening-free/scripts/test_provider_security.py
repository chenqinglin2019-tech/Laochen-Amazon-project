"""Offline transport, source-envelope, and cross-process quota regressions."""
import io
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date, timedelta
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib import error, request

import eps_client
import inpi_client
import provider_utils as transport
import serpapi_patents_client as serpapi
from free_search_budget import reserve_search
from common import sha256_bytes, sha256_json
from provider_utils import ProviderError


class RetainedTextTests(unittest.TestCase):
    def capture(self, text):
        return {"text_evidence_revision": transport.TEXT_EVIDENCE_REVISION,
            "rendered_text": text, "abstract": text, "satisfied_facts": ["abstract"],
            "document_retrieval": {"text_evidence_revision": transport.TEXT_EVIDENCE_REVISION,
                "rendered_text_stage": "source", "text_hash_algorithm": transport.TEXT_HASH_ALGORITHM,
                "rendered_text_sha256": sha256_json(text), "source_rendered_text_sha256": sha256_json(text),
                "source_rendered_text_stage": "source"}}

    def clean(self, text):
        return transport.redact_sensitive_text(text, text_evidence_revision=transport.TEXT_EVIDENCE_REVISION)

    def test_prose_basic_is_preserved_only_in_explicit_new_revision(self):
        for text in ("basic and common features", "Basic principles", "bAsIc structure", "basic\nand", "basic assembly; 中文"):
            with self.subTest(text=text):
                self.assertEqual(self.clean(text), text)
                self.assertNotEqual(transport.redact_sensitive_text(text), text)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED"):
            transport.redact_sensitive_text("basic and", text_evidence_revision="future")

    def test_real_credentials_and_existing_contexts_remain_redacted_idempotently(self):
        text = "\n".join((
            "Basic dXNlcjpwYXNz", "bAsIc dXNlcjpwYXNzIQ==", "Bearer opaque-fixture-01",
            "Authorization: Basic deliberately-not-base64", "Proxy-Authorization: Bearer fixture-02",
            'headers={"Cookie":"fixture-03", "safe":"basic and"}',
            '<config password="fixture-04"><accessToken>fixture-05</accessToken><safe>basic and</safe></config>',
            "--api_key fixture-06", "token=fixture-07; safe=basic and",
            "https://fixture-user:fixture-pass@example.test/path?q=basic+and&api_key=fixture-08#fixture-09",
            "Basic [redacted]", "Bearer [redacted]", "token=[redacted]; safe=kept",
        ))
        clean = self.clean(text)
        for secret in ("dXNlcjpwYXNz", "deliberately-not-base64", "fixture-", "fixture-user", "fixture-pass"):
            self.assertNotIn(secret, clean)
        self.assertIn("<safe>basic and</safe>", clean)
        self.assertIn("q=basic+and", clean)
        self.assertEqual(self.clean(clean), clean)
        self.assertIn("safe=kept", clean)

    def test_source_transform_binds_retained_text_and_is_repeatable(self):
        original = self.capture("Basic principles and basic structure.\nBearer fixture-secret\n中文 token=fixture-key")
        original["cdp_session_id"] = "fixture-session"
        snapshot = deepcopy(original)
        result = transport.sanitize_for_evidence(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(result["document_retrieval"]["rendered_text_stage"], "retained")
        self.assertEqual(result["document_retrieval"]["rendered_text_sha256"], sha256_json(result["rendered_text"]))
        self.assertEqual(result["document_retrieval"]["source_rendered_text_sha256"], sha256_json(original["rendered_text"]))
        self.assertNotEqual(result["document_retrieval"]["rendered_text_sha256"], result["document_retrieval"]["source_rendered_text_sha256"])
        self.assertEqual(result["abstract"], result["rendered_text"])
        self.assertEqual(result["cdp_session_id"], "[redacted]")
        self.assertEqual(transport.sanitize_for_evidence(result), result)
        raw = transport.sanitize_raw_evidence(json.dumps(original).encode(), "json")
        self.assertEqual(json.loads(raw), result)
        self.assertEqual(transport.sanitize_raw_evidence(raw, "json"), raw)
        normalized = {"text_evidence_revision": result["text_evidence_revision"],
            "published_document": {**result["document_retrieval"], "rendered_text": result["rendered_text"]},
            "abstract": result["abstract"], "document_text": result["rendered_text"]}
        self.assertEqual(transport.validate_text_evidence(normalized, expected_stage="retained"), "retained")
        self.assertEqual(transport.sanitize_for_evidence(normalized), normalized)

    def test_bad_hash_stage_algorithm_or_abstract_is_rejected_not_recomputed(self):
        source = self.capture("basic and source text")
        for field, replacement in (("rendered_text_sha256", "0" * 64), ("source_rendered_text_sha256", "0" * 64),
                ("text_hash_algorithm", "sha256-utf8"), ("rendered_text_stage", "unknown"),
                ("text_evidence_revision", "future"), ("source_rendered_text_stage", "retained")):
            bad = deepcopy(source)
            bad["document_retrieval"][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                transport.sanitize_for_evidence(bad)
        retained = transport.sanitize_for_evidence(self.capture("basic and Bearer source-token"))
        retained["document_retrieval"]["rendered_text_sha256"] = retained["document_retrieval"]["source_rendered_text_sha256"]
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            transport.sanitize_for_evidence(retained)
        for changes in ({"rendered_text": "changed"}, {"abstract": "other abstract"}, {"abstract": ""},
                        {"document_text": "other text"}, {"text_evidence_revision": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                transport.sanitize_for_evidence({**source, **changes})
        with self.assertRaisesRegex(ValueError, "STAGE_OR_ALGORITHM"):
            transport.validate_text_evidence(source, expected_stage="retained")
        for value in ({"text_evidence_revision": None}, {**source, "published_document": {}},
                      {"document_retrieval": {}, "published_document": {"text_evidence_revision": transport.TEXT_EVIDENCE_REVISION}}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "DOCUMENT_SHAPE_INVALID"):
                transport.validate_text_evidence(value)

    def test_legacy_raw_bytes_and_mismatched_inherited_hash_are_not_migrated(self):
        legacy = {"rendered_text": "basic and retained", "document_retrieval": {"rendered_text_sha256": sha256_json("basic and retained")}}
        expected = {"rendered_text": "basic [redacted] retained", "document_retrieval": legacy["document_retrieval"]}
        raw = transport.sanitize_raw_evidence(json.dumps(legacy, ensure_ascii=False, sort_keys=True).encode(), "json")
        self.assertEqual(raw, json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        self.assertIsNone(transport.validate_text_evidence(expected))
        self.assertNotIn("text_evidence_revision", json.loads(raw))


class Response(io.BytesIO):
    status = 200
    headers = {}

    def geturl(self):
        return 'https://example.invalid/data'


def reserve_worker(args):
    directory, number = args
    try:
        reserve_search('serpapi', 'dummy', 'https://example.invalid', remaining=1,
                       task_dir=Path(directory) / str(number), query_id='Q', ledger_dir=Path(directory))
        return 'reserved'
    except ProviderError as exc:
        return exc.code


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LC_IPR_TEST_MODE': '', 'LC_IPR_OFFLINE_TESTS': '', 'LC_IPR_OPERATION_DEADLINE_EPOCH': ''})
        self.env.start()
        # These transport-only tests intentionally disable offline network
        # blocking and mock the socket layer.  Keep their User-Agent lookup
        # independent of an installed private config.json so the published
        # package remains verifiable before a user configures credentials.
        self.runtime_config = patch.object(
            transport, 'load_skill_config', return_value={'http': {'user_agent': 'offline-transport-test'}},
        )
        self.runtime_config.start()

    def tearDown(self):
        self.runtime_config.stop()
        self.env.stop()

    def test_cross_origin_and_downgrade_are_rejected_before_following(self):
        handler = transport.SameOriginRedirectHandler()
        req = request.Request('https://example.invalid/data', headers={'Authorization': 'Bearer dummy'})
        for destination in ('https://other.invalid/data', 'http://example.invalid/data', 'https://example.invalid:444/data', 'https://user@example.invalid/data'):
            with self.subTest(destination=destination), self.assertRaises(ProviderError):
                handler.redirect_request(req, None, 302, 'Found', {}, destination)

    def test_same_origin_redirect_is_allowed(self):
        req = request.Request('https://EXAMPLE.invalid/data', headers={'Authorization': 'Bearer dummy'})
        result = transport.SameOriginRedirectHandler().redirect_request(req, None, 302, 'Found', {}, 'https://example.invalid:443/next')
        self.assertEqual(result.get_header('Authorization'), 'Bearer dummy')

    def test_success_response_is_bounded_and_closed(self):
        response = Response(b'12345')
        opener = MagicMock(); opener.open.return_value = response
        with patch.object(transport.request, 'build_opener', return_value=opener), self.assertRaises(ProviderError) as raised:
            transport.http_request('https://example.invalid/data', max_response_bytes=4)
        self.assertEqual(raised.exception.code, 'PROVIDER_RESPONSE_TOO_LARGE')
        self.assertTrue(response.closed)

    def test_unexpected_final_origin_is_rejected(self):
        response = Response(b'ok'); response.geturl = lambda: 'https://other.invalid/data'
        opener = MagicMock(); opener.open.return_value = response
        with patch.object(transport.request, 'build_opener', return_value=opener), self.assertRaises(ProviderError) as raised:
            transport.http_request('https://example.invalid/data')
        self.assertEqual(raised.exception.code, 'PROVIDER_REDIRECT_BLOCKED')

    def test_expired_deadline_sends_no_request(self):
        with patch.dict(os.environ, {'LC_IPR_OPERATION_DEADLINE_EPOCH': str(time.time() - 1)}), patch.object(transport.request, 'build_opener') as factory, self.assertRaises(ProviderError) as raised:
            transport.http_request('https://example.invalid/data')
        self.assertEqual(raised.exception.code, 'OPERATION_DEADLINE_EXCEEDED')
        factory.return_value.open.assert_not_called()

    def test_remaining_deadline_bounds_socket_timeout(self):
        opener = MagicMock(); opener.open.return_value = Response(b'ok')
        with patch.dict(os.environ, {'LC_IPR_OPERATION_DEADLINE_EPOCH': str(time.time() + 2)}), patch.object(transport.request, 'build_opener', return_value=opener):
            self.assertEqual(transport.http_request('https://example.invalid/data')[2], b'ok')
        self.assertGreater(opener.open.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(opener.open.call_args.kwargs['timeout'], 2)

    def test_deadline_is_checked_before_retry_sleep(self):
        opener = MagicMock(); opener.open.side_effect = error.URLError('offline')
        with patch.dict(os.environ, {'LC_IPR_OPERATION_DEADLINE_EPOCH': str(time.time() + .1)}), patch.object(transport.request, 'build_opener', return_value=opener), patch.object(transport.time, 'sleep') as sleep, self.assertRaises(ProviderError):
            transport.http_request('https://example.invalid/data', retries=2)
        sleep.assert_not_called()
        self.assertEqual(opener.open.call_count, 1)

    def test_quota_http_error_is_not_retried(self):
        opener = MagicMock(); opener.open.side_effect = error.HTTPError('https://example.invalid/data', 429, 'limit', {}, io.BytesIO(b'quota'))
        with patch.object(transport.request, 'build_opener', return_value=opener), self.assertRaises(ProviderError) as raised:
            transport.http_request('https://example.invalid/data')
        self.assertEqual(raised.exception.code, 'FREE_QUOTA_EXHAUSTED')
        self.assertEqual(opener.open.call_count, 1)

    def test_test_mode_blocks_external_before_transport(self):
        with patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1'}), patch.object(transport.request, 'build_opener') as factory, self.assertRaises(ProviderError) as raised:
            transport.http_request('https://example.invalid/data')
        self.assertEqual(raised.exception.code, 'TEST_NETWORK_BLOCKED')
        factory.assert_not_called()

    def test_custom_transports_also_block_external_test_mode(self):
        with patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1'}), patch.object(eps_client, 'EpsQuotaLedger') as ledger:
            with self.assertRaises(ProviderError): eps_client.download('EP1004359B1')
            ledger.assert_not_called()
            with self.assertRaises(ProviderError): inpi_client.InpiSession('dummy', 'dummy')

    def test_offline_runner_blocks_network_without_changing_source_mode(self):
        with patch.dict(os.environ, {'LC_IPR_TEST_MODE': '', 'LC_IPR_OFFLINE_TESTS': '1'}), patch.object(transport.request, 'build_opener') as factory, self.assertRaises(ProviderError) as raised:
            transport.http_request('https://example.invalid/data')
        self.assertEqual(raised.exception.code, 'TEST_NETWORK_BLOCKED')
        factory.assert_not_called()

class SerpApiEnvelopeTests(unittest.TestCase):
    def call(self, payload):
        with patch.object(serpapi, 'http_json', return_value=(payload, {}, json.dumps(payload).encode())):
            return serpapi.search('https://example.invalid', 'dummy', 1, {'q': 'audit', 'num': 1, 'country': 'US'})[0]

    def test_error_text_cannot_become_zero(self):
        for message in ('No results because upstream request timed out', 'no results: quota exhausted', "Google hasn't returned any results for this query. timeout"):
            with self.subTest(message=message), self.assertRaises(ProviderError): self.call({'error': message})

    def test_exact_zero_message_requires_successful_envelope(self):
        with self.assertRaises(ProviderError): self.call({'error': serpapi.ZERO_RESULT_MESSAGE})
        with self.assertRaises(ProviderError): self.call({'error': serpapi.ZERO_RESULT_MESSAGE, 'search_metadata': {'status': 'Error'}})
        payload = self.call({'error': serpapi.ZERO_RESULT_MESSAGE, 'search_metadata': {'status': 'Success'}})
        self.assertEqual(payload['organic_results'], [])
        self.assertNotIn('error', payload)

    def test_successful_zero_and_positive_are_preserved(self):
        for rows in ([], [{'patent_id': 'US1A'}]):
            self.assertEqual(self.call({'search_metadata': {'status': 'Success'}, 'organic_results': rows})['organic_results'], rows)

    def test_test_settings_never_resolve_real_key(self):
        with patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1', 'SERPAPI_BASE_URL': 'http://127.0.0.1:9', 'SERPAPI_API_KEY': 'must-not-be-read'}), patch.object(serpapi, 'credential') as credential:
            _, base, key = serpapi.settings()
        self.assertEqual(base, 'http://127.0.0.1:9')
        self.assertEqual(key, serpapi.TEST_CREDENTIAL)
        credential.assert_not_called()

    def test_test_settings_require_explicit_loopback(self):
        for base in ('https://serpapi.com', 'http://127.0.0.1:9/prefix', 'http://user@127.0.0.1:9'):
            with self.subTest(base=base), patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1', 'SERPAPI_BASE_URL': base}), self.assertRaises(ProviderError):
                serpapi.settings()


class FileLockTests(unittest.TestCase):
    def test_missing_platform_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(transport, 'fcntl', None), patch.object(transport, 'msvcrt', None):
            with self.assertRaises(ProviderError) as raised:
                with transport.file_lock(Path(temporary) / '.lock'):
                    self.fail('must not enter unlocked critical section')
        self.assertEqual(raised.exception.code, 'PROVIDER_LOCK_UNAVAILABLE')

    def test_windows_branch_locks_and_unlocks_the_same_byte(self):
        windows = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=MagicMock())
        with tempfile.TemporaryDirectory() as temporary, patch.object(transport, 'fcntl', None), patch.object(transport, 'msvcrt', windows):
            with transport.file_lock(Path(temporary) / '.lock'):
                self.assertEqual(windows.locking.call_count, 1)
        self.assertEqual([call.args[1:] for call in windows.locking.call_args_list], [(1, 1), (2, 1)])

    def test_busy_lock_has_a_bounded_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.lock'
            with transport.file_lock(path):
                started = time.monotonic()
                with self.assertRaises(ProviderError) as raised:
                    with transport.file_lock(path, timeout=.02):
                        self.fail('same file must remain locked')
                self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(raised.exception.code, 'PROVIDER_LOCK_BUSY')


class FallbackEvidenceTests(unittest.TestCase):
    def test_v24_fallback_requires_current_plan_and_intact_fresh_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw = root / 'raw.json'; raw.write_bytes(b'{}')
            row = {'query_id': 'SERPER-Q', 'q': 'original query'}
            run = {'provider': 'serper_patents', 'query_id': 'SERPER-Q', 'status': 'no_result',
                   'plan_entry_sha256': sha256_json(row), 'raw_paths': ['raw.json'], 'payload_digest': sha256_bytes(b'{}'),
                   'finished_at': datetime.now(timezone.utc).isoformat()}
            evidence = {'source_runs': [run]}; item = {'fallback_query_id': 'SERPER-Q'}
            args = {'task_dir': root, 'task': {'schema_version': '2.4-free'}, 'plan': {'queries': {'serper_patents': [row]}}}
            self.assertTrue(serpapi.fallback_satisfied(evidence, item, **args))
            raw.unlink()
            self.assertFalse(serpapi.fallback_satisfied(evidence, item, **args))
            raw.write_bytes(b'changed')
            self.assertFalse(serpapi.fallback_satisfied(evidence, item, **args))
            raw.write_bytes(b'{}')
            run['finished_at'] = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
            self.assertFalse(serpapi.fallback_satisfied(evidence, item, **args))
            run['finished_at'] = datetime.now(timezone.utc).isoformat()
            run['plan_entry_sha256'] = '0' * 64
            self.assertFalse(serpapi.fallback_satisfied(evidence, item, **args))

    def test_v23_fallback_retains_the_historical_rule(self):
        evidence = {'source_runs': [{'provider': 'serper_patents', 'query_id': 'Q', 'status': 'no_result'}]}
        self.assertTrue(serpapi.fallback_satisfied(evidence, {'fallback_query_id': 'Q'}, task={'schema_version': '2.3-free'}))


class FreeSearchBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ipr-free-budget-test-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def reserve(self, query='Q', **kwargs):
        return reserve_search('serpapi', 'dummy-account', 'https://example.invalid', remaining=kwargs.pop('remaining', 1),
                              task_dir=self.root / 'task', query_id=query, ledger_dir=self.root, **kwargs)

    def test_uncertain_request_remains_charged_with_stale_remote_balance(self):
        self.reserve()
        with self.assertRaises(ProviderError): self.reserve('Q2')

    def test_exact_query_cannot_reserve_twice(self):
        self.reserve(remaining=5)
        with self.assertRaises(ProviderError) as raised: self.reserve(remaining=5)
        self.assertEqual(raised.exception.code, 'FREE_SEARCH_ALREADY_RESERVED')

    def test_explicit_repair_attempt_debits_again_without_refund(self):
        self.reserve(remaining=3)
        result = self.reserve(remaining=3, attempt_id='repair-1', retry_reason='Retained original response hash no longer matches')
        self.assertEqual(result['local_free_searches_left'], 1)
        self.assertFalse(result['uncertain_request_refunded'])
        with self.assertRaises(ProviderError): self.reserve(remaining=3, attempt_id='repair-1', retry_reason='Same retry resumed')

    def test_new_attempt_requires_a_reason(self):
        with self.assertRaises(ProviderError) as raised: self.reserve(attempt_id='repair-1')
        self.assertEqual(raised.exception.code, 'FREE_SEARCH_RETRY_REASON_REQUIRED')

    def test_explicit_retry_cannot_escape_account_cap(self):
        self.reserve()
        with self.assertRaises(ProviderError) as raised: self.reserve(attempt_id='repair-1', retry_reason='File missing')
        self.assertEqual(raised.exception.code, 'FREE_QUOTA_EXHAUSTED')

    def test_lost_result_records_do_not_release_the_task_cap(self):
        for number in range(3):
            self.reserve(str(number), remaining=100)
        # No evidence.json was written: every attempted request could have
        # crashed immediately after submission. Reservations still enforce 3.
        with self.assertRaises(ProviderError) as raised:
            self.reserve('Q4', remaining=100, attempt_id='repair-1', retry_reason='Old result file missing')
        self.assertEqual(raised.exception.code, 'FREE_SEARCH_TASK_RESERVATIONS_EXHAUSTED')

    def test_shared_budget_blocks_thread_race(self):
        def attempt(n):
            try: self.reserve(str(n)); return True
            except ProviderError: return False
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(attempt, range(4)))
        self.assertEqual(sum(results), 1)

    def test_shared_budget_blocks_cross_process_race(self):
        with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context('spawn')) as pool:
            results = list(pool.map(reserve_worker, [(str(self.root), n) for n in range(4)]))
        self.assertEqual(results.count('reserved'), 1)

    def test_unknown_cycle_cannot_refill_from_higher_remote_balance(self):
        self.reserve()
        with self.assertRaises(ProviderError): self.reserve('Q2', remaining=100)

    def test_verified_later_cycle_resets_only_after_old_cycle_date(self):
        self.reserve(renewal_date='2020-01-01')
        future = (date.today() + timedelta(days=30)).isoformat()
        self.assertEqual(self.reserve('Q2', renewal_date=future)['local_free_searches_left'], 0)
        with self.assertRaises(ProviderError): self.reserve('Q3', renewal_date=(date.today() + timedelta(days=60)).isoformat())

    def test_invalid_ledger_is_not_reset(self):
        self.reserve()
        path = next(self.root.glob('*.json')); path.write_text('{broken')
        with self.assertRaises(ProviderError) as raised: self.reserve('Q2')
        self.assertEqual(raised.exception.code, 'FREE_SEARCH_LEDGER_INVALID')

    def test_ledger_contains_hashes_not_keys_or_query_text(self):
        self.reserve('sensitive query identifier')
        path = next(self.root.glob('*.json')); raw = path.read_text()
        self.assertNotIn('dummy-account', raw)
        self.assertNotIn('sensitive query identifier', raw)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
