"""Credential setup regressions use only synthetic tokens and loopback services."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


writer = module('token_writer', 'configure_credentials.py')
backend = module('token_backend', 'backend_cli.py')


class CredentialSetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'backend_url': 'https://example.invalid', 'backend_token': '', 'keep': True}))

    def test_updates_only_token_with_private_permissions_and_no_echo(self):
        result = writer.configure(self.root, {'backend_token': 'synthetic-token'})
        self.assertNotIn('synthetic-token', json.dumps(result))
        c = json.loads(self.config.read_text())
        self.assertEqual(c, {'backend_url': 'https://example.invalid', 'backend_token': 'synthetic-token', 'keep': True})
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_invalid_inputs_preserve_config(self):
        before = self.config.read_bytes()
        for payload in [{}, [], {'backend_token': ''}, {'backend_token': None},
                        {'backend_token': ' bad'}, {'backend_token': 'bad\nvalue'}, {'backend_token': 'bad\tvalue'}, {'backend_token': 'bad\x7fvalue'},
                        {'backend_token': 'synthetic', 'api_keys': {}}]:
            with self.assertRaises(ValueError):
                writer.configure(self.root, payload)
            self.assertEqual(self.config.read_bytes(), before)

    def test_initializes_missing_config(self):
        self.config.unlink(); writer.configure(self.root, {'backend_token': 'synthetic-token'})
        self.assertEqual(json.loads(self.config.read_text())['backend_url'], 'https://mcp.yixunkuajing.com')

    def test_refuses_symlink(self):
        target = self.root / 'outside'; target.write_text('{}')
        self.config.unlink(); self.config.symlink_to(target)
        with self.assertRaises(ValueError):
            writer.configure(self.root, {'backend_token': 'synthetic-token'})
        self.assertEqual(target.read_text(), '{}')

    def test_invalid_stdin_never_echoes_secret(self):
        token = 'synthetic-invalid-input-token'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/configure_credentials.py')],
                                input='invalid-json ' + token, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(token, result.stdout + result.stderr)


class NativeCredentialChainTests(unittest.TestCase):
    def setUp(self):
        try:
            self.cli = backend.select_cli()
        except backend.BackendError:
            self.skipTest('No native bundled CLI for this platform')
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.calls = []; self.denied = False
        owner = self; self.token = 'synthetic-chat-written-token'

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append({'path': self.path, 'body': body,
                                    'authorized': self.headers.get('Authorization') == 'Bearer ' + owner.token})
                payload = {'ok': False, 'error': owner.token} if owner.denied else (
                    {'status': 'completed', 'qa_pairs': []} if self.path.endswith('/qa') else {'ok': True, 'errors': []})
                data = json.dumps(payload).encode()
                self.send_response(403 if owner.denied else 200)
                self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        (self.root / 'config.json').write_text(json.dumps({'backend_url': 'http://127.0.0.1:%d' % server.server_port,
                                                          'backend_token': ''}))
        (self.root / 'scripts').mkdir()
        import shutil
        shutil.copy2(ROOT / 'scripts/configure_credentials.py', self.root / 'scripts/configure_credentials.py')
        saved = subprocess.run([sys.executable, str(self.root / 'scripts/configure_credentials.py')],
                               input=json.dumps({'backend_token': self.token}), text=True, capture_output=True, timeout=5)
        self.assertEqual(saved.returncode, 0)
        self.assertNotIn(self.token, saved.stdout + saved.stderr)

    def invoke(self, command):
        source = self.root / 'input.json'
        payload = {'title_keywords': {'high': ['pen holder'], 'relevant': []}} if command == 'qa' else {
            'title': 'Pen Holder', 'item_highlight': 'For desks', 'bullets': ['A'] * 5,
            'description': 'Pen holder', 'search_terms': 'organiser'}
        source.write_text(json.dumps(payload))
        inputs = {'keywords_file': source, 'output': self.root / 'qa.json'} if command == 'qa' else {'listing_file': source}
        with patch.object(backend, 'ROOT', self.root):
            result = backend.run_cli(command, site='US', cli=self.cli, timeout=10, **inputs)
        self.assertNotIn(self.token, json.dumps(result))
        return result

    def test_stdin_to_default_config_to_real_qa_and_validate(self):
        for command in ['qa', 'validate']:
            result = self.invoke(command)
            self.assertNotIn('failure_reason', result, result)
            self.assertTrue(self.calls[-1]['authorized'])
            self.assertTrue(self.calls[-1]['path'].endswith('/' + command))

    def test_rejected_token_is_reported_without_echo(self):
        self.denied = True
        result = self.invoke('validate')
        self.assertIn('failure_reason', result)
        self.assertTrue(self.calls[-1]['authorized'])


if __name__ == '__main__':
    unittest.main()
