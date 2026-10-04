"""Full stdin-write/auth-entry chain with synthetic credentials and loopback only."""
import http.server
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').exists(),
                     'Native integration requires macOS loopback sandbox')
class CredentialAuthChainTests(unittest.TestCase):
    def test_stdin_token_reaches_native_auth_and_success_then_failure(self):
        is_ipr = (ROOT / 'scripts/credential_defaults.py').exists()
        token = 'SYNTHETIC-CHAT-AUTH-TOKEN-789'
        state = {'accepted': True, 'requests': []}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                state['requests'].append((self.path, body))
                payload = ({'allowed': True, 'reason': 'permission_enabled'} if is_ipr else
                           {'user': {'status': 'enabled', 'balance': 1}})
                self.send_response(200 if state['accepted'] else 401)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *_):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir(); (root / 'references').mkdir(); (root / 'tools/bin').mkdir(parents=True)
            for f in (ROOT / 'scripts').glob('*.py'):
                if not f.name.startswith('test_'):
                    shutil.copy2(f, root / 'scripts' / f.name)
            reference = 'runtime-config.json' if is_ipr else 'auth-binaries.json'
            shutil.copy2(ROOT / 'references' / reference, root / 'references' / reference)
            name = ('lc-ipr-auth-check-' if is_ipr else 'lc-auth-check-') + 'darwin-' + (
                'arm64' if platform.machine() == 'arm64' else 'amd64')
            shutil.copy2(ROOT / 'tools/bin' / name, root / 'tools/bin' / name)
            # Simulate extractors that drop POSIX modes and downloaded Mac
            # archives that inherit quarantine. Only this temporary copy changes.
            native = root / 'tools/bin' / name
            native.chmod(0o600)
            subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine',
                            '0081;00000000;SyntheticAuthDistributionTest;', str(native)],
                           check=True, capture_output=True, timeout=10)
            (root / 'config.json').write_text(json.dumps({'backend_url': 'http://127.0.0.1:%d' % server.server_port,
                                                        'backend_token': ''}))
            env = {'HOME': temporary, 'TMPDIR': temporary, 'PATH': '/usr/bin:/bin',
                   'LC_AMAZON_STUDIO_CACHE': str(root / 'cache'), 'PYTHONDONTWRITEBYTECODE': '1'}
            saved = subprocess.run([sys.executable, str(root / 'scripts/configure_credentials.py')],
                                   input=json.dumps({'backend_token': token}), text=True,
                                   capture_output=True, env=env, timeout=10)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertNotIn(token, saved.stdout + saved.stderr)
            before = (root / 'config.json').read_bytes()
            blocked = subprocess.run(['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
                                     sys.executable, str(root / 'scripts/auth_gate.py')],
                                     capture_output=True, text=True, env=env, timeout=30)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(state['requests'], [])
            self.assertIn('云端鉴权未通过，本轮不继续执行。', blocked.stderr)
            self.assertEqual(len(blocked.stderr.strip().splitlines()), 2)
            self.assertFalse((root / 'cache/auth-pass.json').exists())
            self.assertIn('连接或服务不可用', blocked.stderr)
            self.assertEqual(native.stat().st_mode & 0o111, 0o111)
            attributes = subprocess.run(['/usr/bin/xattr', str(native)], check=True,
                                        capture_output=True, text=True, timeout=10)
            self.assertNotIn('com.apple.quarantine', attributes.stdout.splitlines())
            policy = ('(version 1)(allow default)(deny network*)'
                      '(allow network-outbound (remote ip "localhost:%d"))' % server.server_port)
            command = ['/usr/bin/sandbox-exec', '-p', policy, sys.executable, str(root / 'scripts/auth_gate.py')]
            success = subprocess.run(command, capture_output=True, text=True, env=env, timeout=15)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(success.stdout), {'ok': True, 'message': 'auth_passed'})
            self.assertEqual((root / 'config.json').read_bytes(), before)
            self.assertEqual(state['requests'][0][1]['api_key'], token)
            self.assertEqual(state['requests'][0][0], '/auth/skill-check' if is_ipr else '/public/account')
            if not is_ipr:
                self.assertTrue((root / 'cache/auth-pass.json').exists())
            state['accepted'] = False
            denied = subprocess.run(command, capture_output=True, text=True, env=env, timeout=15)
            self.assertNotEqual(denied.returncode, 0)
            self.assertNotIn(token, blocked.stdout + blocked.stderr + success.stdout + success.stderr + denied.stdout + denied.stderr)


if __name__ == '__main__':
    unittest.main()
