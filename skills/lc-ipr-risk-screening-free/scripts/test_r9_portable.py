"""r9 (portable-v1, owner decisions 2026-10-16): sharing fixes - honest design search coverage, Windows behaviour,
proxy-following downloads, network notices, EU/JP step 1. No network is used; Windows is simulated."""
import errno
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

import portable

PORTABLE = {portable.TASK_FIELD: portable.REVISION}


def design(number, position, run='ATT-1', provider='serpapi_google_patents', granted='2024-12-03'):
    return {'candidate_id': 'CAND-' + number, 'right_type': 'design', 'publication_number': number,
            'grant_date': granted, 'candidate_nature': 'patent_search_result',
            'sources': [{'provider': provider, 'source_run_id': run, 'operation': 'search', 'right_type': 'design',
                         'jurisdiction': 'US', 'source_position': position}]}


class DesignCoverageTests(unittest.TestCase):
    """Run B0FHQ475MY: 529 hits, the first 100 read; the report had said designs after 2024-12-03 were not searched."""

    def coverage(self, count, num=100, provider='serpapi_google_patents'):
        import module_review
        candidates = {'patents': [design('USD%07dS1' % (900000 + i), i + 1, provider=provider) for i in range(count)]}
        runs = [{'run_id': 'ATT-1', 'provider': provider, 'request_params': {'num': num} if num else {}}]
        return module_review.design_search_coverage(candidates, runs)

    def test_a_query_stopped_at_its_request_limit_says_later_results_were_not_read(self):
        value = self.coverage(100)
        self.assertTrue(value['limit_reached'])
        self.assertIn('单次请求的上限', value['note'])
        self.assertIn('前 100 条', value['note'])
        self.assertNotIn('不在本次检索范围', value['note'])
        self.assertIn('2024-12-03', value['note'])

    def test_a_complete_query_names_only_the_google_indexing_lag(self):
        value = self.coverage(51)
        self.assertFalse(value['limit_reached'])
        self.assertIn('共返回 51 条结果，已全部读取', value['note'])
        self.assertIn('Google Patents 收录新授权的美国外观约滞后两个月', value['note'])
        self.assertNotIn('不在本次检索范围', value['note'])

    def test_the_epo_route_reads_at_most_25_and_does_not_cite_google(self):
        value = self.coverage(25, num=None, provider='epo_ops')
        self.assertTrue(value['limit_reached'])
        self.assertIn('EPO', value['note'])
        self.assertNotIn('Google', value['note'])

    def test_old_tasks_keep_the_r5d25_boundary_and_new_tasks_get_the_coverage(self):
        import module_review
        frozen = {'task': {'design_query_revision': 'title-phrases-v1'}, 'evidence_digest': 'x',
                  'candidates': {'patents': [design('USD0900001S1', 1)]},
                  'evidence': {'source_runs': [{'run_id': 'ATT-1', 'provider': 'serpapi_google_patents',
                                                'request_params': {'num': 100}}]}}
        with mock.patch('recall.phrases_enabled', return_value=True):
            old = module_review.module_packet(frozen, 'appearance').get('design_search_boundary')
            frozen['task'] = {**frozen['task'], **PORTABLE}
            new = module_review.module_packet(frozen, 'appearance').get('design_search_boundary')
        self.assertNotIn('revision', old)
        self.assertIn('此日之后授权的美国外观不在本次检索范围', old['note'])
        self.assertEqual(new['revision'], portable.REVISION)

    def test_the_review_instruction_follows_the_packet(self):
        text = (Path(__file__).resolve().parent / 'report_review_host.py').read_text(encoding='utf-8')
        self.assertIn("'revision') == 'portable-v1'", text)
        self.assertIn('不要写成“某日之后授权的外观不在本次检索范围”', text)


class WindowsBehaviourTests(unittest.TestCase):
    def test_the_ledger_flush_uses_a_writable_handle(self):
        """Windows FlushFileBuffers needs write access; a read-only fsync failed every SerpApi/Serper/Signa request."""
        import free_search_budget
        real = os.fsync

        def windows_like(fd):
            # a regular file opened read-only cannot be flushed on Windows (the POSIX-only directory fsync is fine)
            if stat.S_ISREG(os.fstat(fd).st_mode) and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
                raise OSError(errno.EBADF, 'Bad file descriptor')
            return real(fd)
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1'}), \
                mock.patch('os.fsync', side_effect=windows_like):
            task = Path(folder) / 'task'
            task.mkdir()
            (task / 'task.json').write_text(json.dumps({'task_id': 'IPRF-1'}), encoding='utf-8')
            result = free_search_budget.reserve_search('serpapi', 'k', 'https://serpapi.com', remaining=10,
                                                       task_dir=task, query_id='QRY-1',
                                                       ledger_dir=Path(folder) / 'ledger')
        self.assertEqual(result['reserved_requests'], 1)

    def test_the_delivery_link_check_skips_retained_originals_whatever_the_separator(self):
        import delivery_versions_stage_e as stage_e
        from common import sha256_file
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # a record written on Windows names files\page.html; here that is one file with a backslash in its name
            page = root / 'files\\page.html'
            page.write_text('<a href="/patent/US1/en">x</a><img src="relative.png">', encoding='utf-8')
            errors = stage_e._file_errors(root, {'files\\page.html': sha256_file(page)})
        self.assertEqual(errors, [])

    def test_inspection_names_files_with_forward_slashes(self):
        text = (Path(__file__).resolve().parent / 'delivery_inspection_stage_d.py').read_text(encoding='utf-8')
        self.assertIn("'checked_files': {path.relative_to(out).as_posix():", text)

    def test_a_held_target_is_replaced_after_a_short_retry_on_windows_only(self):
        import common
        calls = []

        def busy(source, target):
            calls.append(target)
            if len(calls) < 3:
                raise PermissionError(13, 'in use')
        with mock.patch.object(common, 'os', SimpleNamespace(name='nt', replace=busy)), mock.patch('time.sleep'):
            common.replace_file('a.tmp', 'a.json')
        self.assertEqual(len(calls), 3)
        with mock.patch('os.replace', side_effect=PermissionError(13, 'in use')), self.assertRaises(PermissionError):
            common.replace_file('a.tmp', 'a.json')              # POSIX: no retry, unchanged

    def test_source_runners_run_in_utf8_mode(self):
        import advance_work
        seen = {}

        def run(command, **kwargs):
            seen.update(command=command, env=kwargs.get('env'))
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        plan = {'queries': {'serpapi_google_patents': [{'query_id': 'QRY-1', 'execution_phase': 'discovery'}]}}
        with tempfile.TemporaryDirectory() as folder, mock.patch('subprocess.run', side_effect=run):
            advance_work._execute_sources(Path(folder), plan, [{'query_id': 'QRY-1', 'work_id': 'W1'}])
        self.assertTrue(seen['command'][1].endswith('run_api_plan.py'))
        self.assertEqual(seen['env'].get('PYTHONUTF8'), '1')

    def test_the_stop_hook_runs_in_utf8_mode_on_windows_only(self):
        import install_codex_guard
        with mock.patch.object(install_codex_guard, 'os', SimpleNamespace(name='nt', path=os.path)):
            windows = install_codex_guard.definition()['Stop'][0]['hooks'][0]['command']
        posix = install_codex_guard.definition()['Stop'][0]['hooks'][0]['command']
        self.assertIn('-X utf8', windows)
        self.assertNotIn('-X utf8', posix)

    def test_an_npm_codex_on_a_mac_is_found_inside_its_package(self):
        import native_runtime_discovery as discovery
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            package = prefix / 'lib/node_modules/@openai/codex'
            (package / 'bin').mkdir(parents=True)
            (package / 'bin/codex.js').write_text('#!/usr/bin/env node\n', encoding='utf-8')
            native = package / 'vendor/aarch64-apple-darwin/codex/codex'
            native.parent.mkdir(parents=True)
            native.write_bytes(b'\xcf\xfa\xed\xfe' + b'\0' * 64)
            native.chmod(native.stat().st_mode | stat.S_IXUSR)
            (package / 'bin/codex.js').chmod(0o755)
            (prefix / 'bin').mkdir()
            (prefix / 'bin/codex').symlink_to(package / 'bin/codex.js')
            found = discovery.discover_binary(platform='darwin', environment={'PATH': str(prefix / 'bin')},
                                              home=prefix)
        self.assertEqual(found.name, 'codex')
        self.assertIn('vendor', str(found))


class SpeedTests(unittest.TestCase):
    def test_the_image_screen_runs_five_sessions_and_the_text_screen_keeps_its_limit(self):
        import recall_screen
        import text_triage_host
        from test_r5d17_speed_design_screen import SPEED
        limits = {'text_parallel': 3}
        self.assertEqual(text_triage_host.slot_count(SPEED, recall_screen.make_driver('image'), limits), 5)
        self.assertEqual(text_triage_host.slot_count(SPEED, recall_screen.make_driver('text'), limits), 3)
        self.assertEqual(text_triage_host.slot_count({}, recall_screen.make_driver('image'), limits), 3)

    def test_picture_reads_use_six_threads(self):
        import pipeline_robust
        self.assertEqual(pipeline_robust.GOOGLE_WORKERS, 6)


class PipelineTests(unittest.TestCase):
    def pipeline(self, folder, **overrides):
        import run_pipeline
        args = {'task_dir': Path(folder) / 'run', 'url': 'https://www.amazon.de/dp/B0GJD92G1K', 'product_input': None,
                'jurisdictions': None, 'guard_session_id': '', 'chief': None, 'allow_limited_sources': True,
                'enable_serper_free': False, 'use_serper_existing_balance': False, 'enable_serpapi_free': False,
                'enable_signa_free': False, 'all_sources': False}
        args.update(overrides)
        line = run_pipeline.Pipeline(SimpleNamespace(**args))
        commands = []
        line.call = lambda stage, command, **kwargs: commands.append([str(part) for part in command]) or (0, '', '')
        line.reach_check = lambda: None
        return line, commands

    def test_a_link_without_countries_follows_its_marketplace_and_the_session_falls_back_to_the_env(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {'CODEX_THREAD_ID': 'thread-1'}):
            line, commands = self.pipeline(folder)
            line.s_create()
        command = commands[0]
        self.assertNotIn('--jurisdictions', command)
        self.assertEqual(command[command.index('--guard-session-id') + 1], 'thread-1')

    def test_user_materials_keep_the_us_default(self):
        with tempfile.TemporaryDirectory() as folder:
            line, commands = self.pipeline(folder, url=None, product_input=Path(folder) / 'input.json')
            line.s_create()
        command = commands[0]
        self.assertEqual(command[command.index('--jurisdictions') + 1], 'US')

    def test_the_resume_command_names_the_real_interpreter_and_script(self):
        with tempfile.TemporaryDirectory() as folder:
            line, _ = self.pipeline(folder)
            text = line.resume_command()
        self.assertIn(sys.executable, text)
        self.assertIn(str(Path(__file__).resolve().parent / 'run_pipeline.py'), text)

    def test_unreachable_google_stops_before_the_task_exists(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder:
            line, commands = self.pipeline(folder)
            del line.reach_check
            result = {'status': 'google_unreachable', 'advice': ['连不上', '请打开代理']}
            with mock.patch('network_diagnostic.diagnose', return_value=result), \
                    self.assertRaises(run_pipeline.StageFailed) as caught:
                line.s_create()
        self.assertEqual(caught.exception.code, 'PIPELINE_GOOGLE_UNREACHABLE')
        self.assertEqual(commands, [])

    def test_a_sandbox_without_network_is_named_beside_the_auth_failure(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {'CODEX_SANDBOX_NETWORK_DISABLED': '1'}):
            line, _ = self.pipeline(folder)

            def fail(stage, command, **kwargs):
                raise run_pipeline.StageFailed('auth', 'AUTH_SERVICE_UNAVAILABLE', 'service_unavailable')
            line.call = fail
            with self.assertRaises(run_pipeline.StageFailed):
                line.s_auth()
        self.assertIn('沙箱', line.search_notice()['network_notice'])

    def test_missing_image_libraries_are_named_up_front(self):
        import run_pipeline
        real = __import__

        def no_pil(name, *args, **kwargs):
            if name == 'PIL':
                raise ImportError(name)
            return real(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            line, _ = self.pipeline(folder)
            with mock.patch('builtins.__import__', side_effect=no_pil), \
                    self.assertRaises(run_pipeline.StageFailed) as caught:
                line.dependency_check()
        self.assertEqual(caught.exception.code, 'PIPELINE_PYTHON_DEPENDENCIES_MISSING')

    def test_an_unavailable_review_model_is_named(self):
        self.assertTrue(portable.model_unavailable("The model 'gpt-6-astra' does not exist or you do not have access to it"))
        self.assertFalse(portable.model_unavailable('stream disconnected before completion'))
        self.assertIn('review-host.json', portable.model_notice())


class ProxyTests(unittest.TestCase):
    def setUp(self):
        import candidate_media
        self.cm = candidate_media
        self.saved = dict(candidate_media._FAKE_IP_MODE)
        self.addCleanup(lambda: (candidate_media._FAKE_IP_MODE.clear(), candidate_media._FAKE_IP_MODE.update(self.saved)))

    def resolve(self, *addresses):
        rows = [(socket.AF_INET6 if ':' in a else socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 443)) for a in addresses]
        return mock.patch.object(self.cm.socket, 'getaddrinfo', return_value=rows)

    def test_the_user_proxy_is_used_only_without_a_fake_ip_proxy(self):
        self.cm._FAKE_IP_MODE['value'] = False
        with mock.patch('urllib.request.getproxies', return_value={'https': 'http://u:p@127.0.0.1:7890'}), \
                mock.patch('urllib.request.proxy_bypass', return_value=False):
            self.assertEqual(self.cm.download_proxy('patents.google.com'), ('127.0.0.1', 7890, 'Basic dTpw'))
        with mock.patch('urllib.request.getproxies', return_value={'https': 'http://127.0.0.1:7890'}), \
                mock.patch('urllib.request.proxy_bypass', return_value=True):
            self.assertIsNone(self.cm.download_proxy('intranet.example'))
        with mock.patch('urllib.request.getproxies', return_value={'https': 'socks5://127.0.0.1:7891'}):
            self.assertIsNone(self.cm.download_proxy('patents.google.com'))
        self.cm._FAKE_IP_MODE['value'] = True
        with mock.patch('urllib.request.getproxies', return_value={'https': 'http://127.0.0.1:7890'}):
            self.assertIsNone(self.cm.download_proxy('patents.google.com'))

    def test_a_connect_tunnel_carries_the_real_host_name(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        received = []

        def serve():
            connection, _ = server.accept()
            received.append(connection.recv(4096))
            connection.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            connection.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        connection = self.cm.PublicConnection('patents.google.com', '142.250.1.2', 5)
        raw = connection._through_proxy(('127.0.0.1', server.getsockname()[1], None))
        raw.close()
        thread.join(2)
        server.close()
        self.assertTrue(received[0].startswith(b'CONNECT patents.google.com:443 HTTP/1.1'))

    def test_a_refused_tunnel_is_an_error(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)

        def serve():
            connection, _ = server.accept()
            connection.recv(4096)
            connection.sendall(b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n')
            connection.close()
        threading.Thread(target=serve, daemon=True).start()
        connection = self.cm.PublicConnection('patents.google.com', '142.250.1.2', 5)
        with self.assertRaisesRegex(OSError, 'MEDIA_PROXY_TUNNEL_REFUSED:407'):
            connection._through_proxy(('127.0.0.1', server.getsockname()[1], None))
        server.close()

    def test_connect_wraps_tls_for_the_real_host_through_the_proxy(self):
        connection = self.cm.PublicConnection('patents.google.com', '142.250.1.2', 5)
        raw = mock.Mock()
        with mock.patch.object(self.cm, 'download_proxy', return_value=('127.0.0.1', 7890, None)), \
                mock.patch.object(connection, '_through_proxy', return_value=raw) as tunnel, \
                mock.patch.object(connection._context, 'wrap_socket', return_value='tls') as wrap:
            connection.connect()
        tunnel.assert_called_once()
        self.assertEqual(wrap.call_args.kwargs['server_hostname'], 'patents.google.com')

    def test_ipv4_first_and_the_next_address_after_a_failure(self):
        self.cm._FAKE_IP_MODE['value'] = False
        with self.resolve('2606:4700::1', '8.8.8.8'):
            _, address = self.cm.public_address('https://example.com/a')
        self.assertEqual((address, address.alternates), ('8.8.8.8', ('2606:4700::1',)))
        connection = self.cm.PublicConnection('example.com', address, 5)
        attempts = []

        def create(target, timeout):
            attempts.append(target[0])
            if target[0] == '8.8.8.8':
                raise OSError(errno.ENETUNREACH, 'unreachable')
            return 'socket'
        with mock.patch.object(self.cm, 'download_proxy', return_value=None), \
                mock.patch.object(self.cm.socket, 'create_connection', side_effect=create):
            self.assertEqual(connection._direct(), 'socket')
        self.assertEqual(attempts, ['8.8.8.8', '2606:4700::1'])

    def test_fake_ip_with_an_ipv6_placeholder_uses_the_198_18_answer_and_other_private_answers_stay_refused(self):
        self.cm._FAKE_IP_MODE['value'] = True
        with self.resolve('198.18.0.7', 'fd00::7'):
            self.assertEqual(self.cm.public_address('https://patents.google.com/a')[1], '198.18.0.7')
        with self.resolve('198.18.0.7', '10.0.0.5'), self.assertRaises(ValueError):
            self.cm.public_address('https://patents.google.com/a')
        self.cm._FAKE_IP_MODE['value'] = False
        with self.resolve('198.18.0.7', 'fd00::7'), self.assertRaises(ValueError):
            self.cm.public_address('https://patents.google.com/a')


class NetworkDiagnosticTests(unittest.TestCase):
    PUBLIC = {'m.media-amazon.com': ['151.101.1.16'], 'images-na.ssl-images-amazon.com': ['151.101.1.17'],
              'encrypted-tbn0.gstatic.com': ['142.251.40.110'], 'patentimages.storage.googleapis.com': ['142.250.1.1'],
              'patents.google.com': ['142.250.1.2'], 'ppubs.uspto.gov': ['151.101.2.2'], 'www.amazon.com': ['52.94.1.1']}

    def resolver(self, table):
        def lookup(host, port, type=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port)) for address in table[host]]
        return lookup

    def test_statuses_and_notices(self):
        import network_diagnostic as nd
        proxy = {'configured': True, 'source': 'system', 'scheme': 'http', 'host': '127.0.0.1', 'port': 7890}
        with mock.patch.object(nd, 'proxy_settings', return_value=proxy):
            result = nd.diagnose(resolver=self.resolver(self.PUBLIC))
        self.assertEqual(result['status'], 'proxy_without_fake_ip')
        self.assertIn('经该代理下载', nd.notice(result))
        fake = {**self.PUBLIC, 'www.amazon.com': ['198.18.0.3']}
        with mock.patch.object(nd, 'proxy_settings', return_value={'configured': False}):
            result = nd.diagnose(resolver=self.resolver(fake))
            unreachable = nd.diagnose(resolver=self.resolver(self.PUBLIC), reach=True,
                                      connect=mock.Mock(side_effect=OSError('timed out')))
            reachable = nd.diagnose(resolver=self.resolver(self.PUBLIC), reach=True, connect=mock.Mock())
        self.assertEqual(result['status'], 'fake_ip_detected')
        self.assertIn('已自动兼容', nd.notice(result))
        self.assertNotIn('Clash', nd.notice(result))                 # the old fixes are only kept as fallback lines
        self.assertEqual(unreachable['status'], 'google_unreachable')
        self.assertIn('TUN', nd.notice(unreachable))
        self.assertEqual(reachable['status'], 'ok')


class EuJapanTests(unittest.TestCase):
    TASK = {**PORTABLE, 'coverage_requirements': [
        {'jurisdiction': 'EU', 'right_type': 'patent', 'phase': 'official_recall'},
        {'jurisdiction': 'DE', 'right_type': 'patent', 'phase': 'official_recall'},
        {'jurisdiction': 'DE', 'right_type': 'patent', 'phase': 'candidate_verification'},
        {'jurisdiction': 'DE', 'right_type': 'design', 'phase': 'official_recall'},
        {'jurisdiction': 'DE', 'right_type': 'trademark_word', 'phase': 'official_recall'}]}

    def test_checkpoint_one_names_the_national_scopes_that_cannot_be_searched(self):
        text = portable.scope_notice(self.TASK, None)
        self.assertIn('德国本国的发明专利、外观', text)
        self.assertNotIn('商标', text)                         # scenario-dependent: not predicted
        self.assertIn('德语', text)
        self.assertEqual(portable.scope_notice({**PORTABLE, 'coverage_requirements': [
            {'jurisdiction': 'US', 'right_type': 'design', 'phase': 'official_recall'}]}, None), '')
        with_terms = {'terms': [{'value': 'Grillkorb', 'language': 'de'}]}
        self.assertEqual(portable.scope_notice(self.TASK, with_terms), '')

    def test_after_planning_the_plan_gaps_name_the_scopes(self):
        """Rehearsal on the B0GJD92G1K capture re-targeted to EU+DE: six DE rights had no term at all."""
        plan = {'terms': [{'value': 'cervical pillow', 'language': 'en'}], 'planning_gaps': [
            {'code': 'API_DISCOVERY_TERMS_MISSING', 'jurisdiction': 'DE', 'right_type': 'utility_model'},
            {'code': 'API_DISCOVERY_TERMS_MISSING', 'jurisdiction': 'DE', 'right_type': 'trade_dress'},
            {'code': 'QUERY_IMAGE_ROUTE_UNAVAILABLE'}]}
        text = portable.scope_notice(self.TASK, plan)
        self.assertIn('德国本国的实用新型、商业外观', text)
        self.assertNotIn('发明专利', text)

    def test_a_task_with_nothing_searchable_stops_after_planning(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / 'task.json').write_text(json.dumps({**PORTABLE, 'coverage_requirements': [
                {'jurisdiction': 'JP', 'right_type': 'design', 'phase': 'official_recall'}]}), encoding='utf-8')
            (run / 'search-plan.json').write_text(json.dumps({'queries': {'asset_provenance': [{'query_id': 'Q'}]},
                'planning_gaps': [{'code': 'API_DISCOVERY_TERMS_MISSING', 'jurisdiction': 'JP',
                                   'right_type': 'design'}]}), encoding='utf-8')
            line = run_pipeline.Pipeline(SimpleNamespace(task_dir=run, guard_session_id=None))
            with self.assertRaises(run_pipeline.StageFailed) as caught:
                line.nothing_searchable()
            self.assertEqual(caught.exception.code, 'PIPELINE_NOTHING_SEARCHABLE')
            (run / 'search-plan.json').write_text(json.dumps({'queries': {'epo_ops': [{'query_id': 'Q2'}]}}),
                                                  encoding='utf-8')
            line.nothing_searchable()                          # something to search: no stop

    def test_a_marketplace_missing_from_the_countries_is_named(self):
        self.assertIn('德国站', portable.market_notice('DE', ['US']))
        self.assertEqual(portable.market_notice('DE', ['EU', 'DE']), '')
        self.assertEqual(portable.market_notice('US', ['US']), '')

    def test_a_language_gap_closed_by_the_time_box_says_what_happened(self):
        import time_box
        entry = {'work_id': 'W1', 'state': 'ready', 'jurisdiction': 'JP', 'right_type': 'design',
                 'kind': 'plan_repair', 'reason': 'API_DISCOVERY_TERMS_MISSING'}
        candidate_entry = {**entry, 'work_id': 'W2', 'candidate_id': 'CAND-1'}
        with tempfile.TemporaryDirectory() as folder:
            task = {**PORTABLE, 'task_id': 'IPRF-1', 'time_box_revision': time_box.REVISION}
            time_box.close(folder, task, [entry, candidate_entry], active_seconds=10, why='test')
            new = time_box.limitation(task, entry, folder)
            candidate = time_box.limitation(task, candidate_entry, folder)
            old = time_box.limitation({key: value for key, value in task.items() if key != portable.TASK_FIELD},
                                      entry, folder)
        self.assertEqual(new['reason'], time_box.REASON)
        self.assertEqual(new['limitation_detail'], portable.LIMITATION_CODE)
        self.assertIn('日语', new['reasoning'])
        self.assertEqual(old['reasoning'], time_box.REASONING)
        self.assertEqual(candidate['reasoning'], time_box.REASONING)   # candidate work keeps the time-box text

    def test_designs_outside_the_us_keep_their_25_year_lifetime(self):
        import recall
        task = {**PORTABLE, 'recall_revision': recall.REVISION, 'created_at': '2026-10-16T00:00:00Z'}
        with mock.patch.object(recall, 'enabled', return_value=True), \
                mock.patch.object(recall, '_created', return_value=date(2026, 10, 16)):
            us = recall.serpapi_params(task, 'design', country='US')['after']
            jp = recall.serpapi_params(task, 'design', country='JP')['after']
            old_jp = recall.serpapi_params({'recall_revision': recall.REVISION}, 'design', country='JP')['after']
        self.assertEqual((us, jp, old_jp), ('priority:20101016', 'priority:20001016', 'priority:20101016'))

    def test_a_granted_japanese_patent_goes_to_jpo_as_a_registration_number(self):
        from merge_candidates import _jp_candidate_number
        self.assertEqual(_jp_candidate_number({'publication_number': 'JP6123456B2'}, 'patent'),
                         ('JP6123456B2', 'registration'))
        self.assertEqual(_jp_candidate_number({'publication_number': 'JP2020123456A'}, 'patent'),
                         ('JP2020123456A', 'publication'))

    def test_the_balance_notice_names_the_task_countries(self):
        import search_guard
        record = {'state': 'known', 'available': 200, 'renewal_date': '2026-11-16', 'needed_discovery': 4,
                  'route': 'serpapi'}
        self.assertIn('本次美国专利与外观检索', search_guard.notice(record))
        self.assertIn('本次专利与外观检索', search_guard.notice({**record, 'targets': ['DE', 'EU']}))
        self.assertNotIn('美国', search_guard.notice({**record, 'targets': ['DE', 'EU'], 'route': 'none',
                                                         'available': 0}))

    def test_new_tasks_carry_the_marker(self):
        text = (Path(__file__).resolve().parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn('task[PORTABLE_FIELD] = PORTABLE_REVISION', text)


if __name__ == '__main__':
    unittest.main()
