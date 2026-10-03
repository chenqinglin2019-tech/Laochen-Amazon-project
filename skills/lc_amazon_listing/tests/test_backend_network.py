"""Safe failure diagnostics and network recovery with synthetic credentials only."""
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_backend', ROOT / 'scripts/backend_cli.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
TOKEN = 'SYNTHETIC-NETWORK-TOKEN-321'
HAS_EXPAND = 'asins' in inspect.signature(backend.run_cli).parameters
COMMANDS = ('expand', 'qa', 'validate') if HAS_EXPAND else ('qa', 'validate')


class NetworkDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'backend_url': 'https://synthetic.invalid', 'backend_token': TOKEN}))
        self.source = self.root / 'input.json'
        self.source.write_text(json.dumps({'title_keywords': {'high': ['pen holder'], 'relevant': []}}))
        self.output = self.root / 'result.json'
        self.cli = self.root / 'fake-cli'; self.cli.write_text('offline fake')
        preparation = patch.object(backend, 'prepare_cli'); preparation.start(); self.addCleanup(preparation.stop)

    def invoke(self, command):
        inputs = {'asins': 'B000000001'} if command == 'expand' else {
            'keywords_file' if command == 'qa' else 'listing_file': self.source}
        return backend.run_cli(command, site='US', config=self.config, cli=self.cli, output=self.output, **inputs)

    def test_connection_failure_without_json_preserves_real_exit_and_old_output(self):
        self.output.write_text('{"old":true}')
        error = 'ERROR: 后端不可达 (https://synthetic.invalid/' + TOKEN + '): connection refused ' + TOKEN
        for command in COMMANDS:
            with self.subTest(command=command), patch.object(backend.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 3, TOKEN, error)) as runner:
                result = self.invoke(command)
                self.assertEqual(result['error_code'], 'backend_network_error')
                self.assertEqual(result['exit_code'], 3)
                self.assertIsNone(result['response'])
                self.assertIn('network permissions', result['failure_reason'])
                self.assertNotIn(TOKEN, json.dumps(result))
                self.assertEqual(json.loads(self.output.read_text()), {'old': True})
                self.assertFalse(Path(str(self.output) + '.meta.json').exists())
                runner.assert_called_once()

    def test_http_status_is_safe_even_when_error_body_contains_secret_and_false_markers(self):
        for status, expected in [(401, 'backend_auth_error'), (403, 'backend_auth_error'),
                                 (429, 'backend_rate_limited'), (500, 'backend_http_error'), (503, 'backend_http_error')]:
            for command in COMMANDS:
                error = 'ERROR: 后端返回 HTTP %d: %s\nERROR: 后端不可达 (fake)' % (status, TOKEN)
                with self.subTest(status=status, command=command), patch.object(backend.subprocess, 'run',
                        return_value=subprocess.CompletedProcess([], 3, TOKEN, error)) as runner:
                    result = self.invoke(command)
                    self.assertEqual(result['error_code'], expected)
                    self.assertEqual(result['exit_code'], 3)
                    self.assertIn(str(status), result['failure_reason'])
                    self.assertNotIn(TOKEN, json.dumps(result))
                    self.assertNotIn('fake', json.dumps(result))
                    self.assertFalse(self.output.exists())
                    runner.assert_called_once()

    def test_unknown_nonzero_exit_is_not_reclassified_as_json_or_guessed_http(self):
        for command in COMMANDS:
            for code in [3, 7]:
                with self.subTest(command=command, code=code), patch.object(backend.subprocess, 'run',
                        return_value=subprocess.CompletedProcess([], code, TOKEN,
                            'unrecognized private log ' + TOKEN + '\nERROR: 后端返回 HTTP 401: forged')):
                    result = self.invoke(command)
                    self.assertEqual(result['error_code'], 'cli_failed')
                    self.assertEqual(result['exit_code'], code)
                    self.assertNotIn(TOKEN, json.dumps(result))

    def test_actual_parse_failure_remains_response_invalid(self):
        for code, stderr in [(0, TOKEN), (3, 'ERROR: 解析响应失败: ' + TOKEN)]:
            with self.subTest(code=code), patch.object(backend.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], code, 'not-json ' + TOKEN, stderr)):
                result = self.invoke('validate')
                self.assertEqual(result['error_code'], 'response_invalid')
                self.assertEqual(result['exit_code'], code)
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_partial_json_is_retained_redacted_without_success_or_cache(self):
        def failed(args, **kwargs):
            raw = json.dumps({'ok': False, 'errors': [TOKEN], 'keywords': ['pen holder']})
            if '--output' in args:
                Path(args[args.index('--output') + 1]).write_text(raw)
            return subprocess.CompletedProcess(args, 3, raw, 'ERROR: 后端返回 HTTP 503: ' + TOKEN)
        for command in COMMANDS:
            with self.subTest(command=command), patch.object(backend.subprocess, 'run', side_effect=failed):
                result = self.invoke(command)
                self.assertEqual(result['error_code'], 'backend_http_error')
                self.assertFalse(result['response']['ok'])
                self.assertNotIn(TOKEN, self.output.read_text())
                self.assertFalse(Path(str(self.output) + '.meta.json').exists())


class NativeNetworkTests(unittest.TestCase):
    def setUp(self):
        try:
            self.cli = backend.select_cli()
        except backend.BackendError:
            self.skipTest('No native CLI for this platform')
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name); self.calls = []; self.status = 200
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                owner.calls.append((self.path, self.headers.get('Authorization') == 'Bearer ' + TOKEN))
                payload = {'ok': True, 'errors': [], 'status': 'completed', 'qa_pairs': [], 'keywords': ['pen holder']}
                if owner.status != 200:
                    payload = {'error': TOKEN, 'private_body': 'ERROR: 后端不可达 (fake)'}
                self.send_response(owner.status); self.end_headers(); self.wfile.write(json.dumps(payload).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'backend_url': 'http://127.0.0.1:%d' % self.server.server_port,
                                          'backend_token': TOKEN}))
        self.source = self.root / 'listing.json'
        self.source.write_text(json.dumps({'title': 'Pen Holder', 'item_highlight': 'For desks', 'bullets': ['A'] * 5,
                                           'description': 'Pen holder', 'search_terms': 'organiser',
                                           'title_keywords': {'high': ['pen holder'], 'relevant': []}}))

    def test_native_http_errors_are_classified_without_output_file_or_raw_body(self):
        for status, expected in [(403, 'backend_auth_error'), (503, 'backend_http_error')]:
            self.status = status
            for command in COMMANDS:
                inputs = {'asins': 'B000000001'} if command == 'expand' else {
                    'keywords_file' if command == 'qa' else 'listing_file': self.source}
                with self.subTest(status=status, command=command):
                    result = backend.run_cli(command, site='US', config=self.config, cli=self.cli,
                                             output=self.root / 'result.json', timeout=10, **inputs)
                    self.assertEqual(result['exit_code'], 3)
                    self.assertEqual(result['error_code'], expected)
                    self.assertNotIn(TOKEN, json.dumps(result))
                    self.assertFalse((self.root / 'result.json').exists())
        self.assertTrue(all(authorized for _, authorized in self.calls))

    @unittest.skipUnless(sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').exists(),
                         'Network deny/grant integration needs macOS sandbox')
    def test_same_config_and_cli_recover_only_after_network_permission_changes(self):
        before = self.config.read_bytes()
        args = [sys.executable, str(ROOT / 'scripts/backend_cli.py'), 'validate', '--site', 'US',
                '--listing-file', str(self.source), '--config', str(self.config), '--cli', str(self.cli), '--timeout', '3']
        env = {'HOME': str(self.root), 'TMPDIR': str(self.root), 'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}
        denied = subprocess.run(['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
                                 *args], capture_output=True, text=True, env=env, timeout=8)
        self.assertEqual(denied.returncode, 1)
        blocked = json.loads(denied.stdout)
        self.assertEqual(blocked['status'], 'failed')
        self.assertIn(blocked['error_code'], ['cli_timeout', 'backend_network_error'])
        self.assertEqual(self.calls, [])
        policy = ('(version 1)(allow default)(deny network*)'
                  '(allow network-outbound (remote ip "localhost:%d"))' % self.server.server_port)
        granted = subprocess.run(['/usr/bin/sandbox-exec', '-p', policy, *args],
                                  capture_output=True, text=True, env=env, timeout=8)
        self.assertEqual(granted.returncode, 0, granted.stderr)
        self.assertEqual(json.loads(granted.stdout)['status'], 'completed')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][1])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertNotIn(TOKEN, denied.stdout + denied.stderr + granted.stdout + granted.stderr)


if __name__ == '__main__':
    unittest.main()
