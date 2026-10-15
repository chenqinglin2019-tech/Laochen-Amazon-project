"""Recipient auth acceptance: synthetic credentials, isolated files, loopback only."""
import contextlib
import http.server
import io
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import auth_runtime as auth
import test_runner_packaging as packaging

TOKEN = 'SYNTHETIC-RECIPIENT-CLOUD-TOKEN'
NEW_TOKEN = 'SYNTHETIC-REPLACEMENT-CLOUD-TOKEN'


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='凭据 isolated ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / 'config.json'
        self.local = self.root / 'config.local.json'
        self.public.write_text(json.dumps({'backend_url': 'https://example.invalid', 'backend_token': ''}))

    def write(self, path, **fields):
        path.write_text(json.dumps(fields))

    def test_empty_local_token_does_not_mask_valid_public_token_or_endpoint(self):
        self.write(self.public, backend_url='https://example.invalid', backend_token=TOKEN)
        for value in ('', '  ', None):
            self.write(self.local, backend_url='https://wrong.invalid', backend_token=value)
            config, path = auth.resolve_config(self.root)
            self.assertEqual(config['backend_token'], TOKEN)
            self.assertEqual(config['backend_url'], 'https://example.invalid')
            self.assertEqual(path, self.public)

    def test_conflicting_nonempty_tokens_stop_before_network(self):
        self.write(self.public, backend_url='https://example.invalid', backend_token=TOKEN)
        self.write(self.local, backend_token=NEW_TOKEN)
        with patch.object(auth.subprocess, 'run') as run, self.assertRaises(auth.AuthError) as error:
            auth.check(self.root, self.root / 'checker')
        self.assertEqual(error.exception.reason, 'configuration_conflict')
        run.assert_not_called()

    def test_partial_local_override_and_bom_use_private_normalized_config(self):
        for bom in (False, True):
            if bom:
                self.public.write_text(json.dumps({'backend_url': 'https://example.invalid', 'backend_token': TOKEN}), encoding='utf-8-sig')
                self.local.unlink(missing_ok=True)
            else:
                self.write(self.local, backend_token=TOKEN)
            seen = []
            def native(argv, **kwargs):
                path = Path(argv[-1]); seen.append(path)
                self.assertEqual(argv[1], '--config')
                self.assertEqual(json.loads(path.read_text())['backend_token'], TOKEN)
                self.assertNotIn(TOKEN, ' '.join(argv))
                if os.name != 'nt': self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                return subprocess.CompletedProcess(argv, 0, '', '')
            with patch.object(auth.subprocess, 'run', side_effect=native): auth.check(self.root, self.root / 'checker')
            self.assertFalse(seen[0].exists())

    def test_explicit_replacement_repairs_old_token_and_clears_public_secret(self):
        self.write(self.public, backend_url='https://example.invalid', backend_token=TOKEN, public_setting='keep')
        self.write(self.local, backend_url='https://example.invalid', backend_token='OLD-SYNTHETIC-TOKEN', private_setting='keep')
        auth.write_credentials(self.root, NEW_TOKEN)
        config, path = auth.resolve_config(self.root)
        self.assertEqual(config['backend_token'], NEW_TOKEN)
        self.assertEqual(path, self.local)
        self.assertEqual(json.loads(self.public.read_text())['backend_token'], '')
        self.assertEqual(json.loads(self.local.read_text())['private_setting'], 'keep')
        self.assertEqual(json.loads(self.public.read_text())['public_setting'], 'keep')

    def test_explicit_replacement_can_repair_corrupt_local_file(self):
        self.local.write_text('invalid json')
        with self.assertRaises(auth.AuthError): auth.resolve_config(self.root)
        auth.write_credentials(self.root, TOKEN)
        self.assertEqual(auth.resolve_config(self.root)[0]['backend_token'], TOKEN)

    def test_failed_second_write_restores_previous_credentials(self):
        self.write(self.public, backend_url='https://example.invalid', backend_token=TOKEN)
        self.write(self.local, backend_url='https://example.invalid', backend_token=TOKEN)
        before = (self.public.read_bytes(), self.local.read_bytes())
        original = auth.atomic_write
        def write(path, data):
            if path == self.public: raise PermissionError(NEW_TOKEN)
            original(path, data)
        with patch.object(auth, 'atomic_write', side_effect=write), self.assertRaises(auth.AuthError) as error:
            auth.write_credentials(self.root, NEW_TOKEN)
        self.assertEqual(error.exception.reason, 'credential_write_failed')
        self.assertEqual((self.public.read_bytes(), self.local.read_bytes()), before)
        self.assertEqual(list(self.root.glob('.config.local.*')), [])

    def test_sync_updates_only_cloud_credentials_and_preserves_other_files(self):
        self.write(self.public, backend_url='https://example.invalid', backend_token=TOKEN)
        target = self.root / 'runner'; target.mkdir()
        self.write(target / 'config.json', backend_url='https://old.invalid', backend_token='OLD-SYNTHETIC-TOKEN', task_setting='keep')
        self.write(target / 'config.local.json', backend_token='OLD-SYNTHETIC-TOKEN', private_setting='keep')
        other = target / 'model.json'; other.write_text('SYNTHETIC-MODEL-KEY')
        auth.sync_runner(self.root, target)
        self.assertEqual(auth.resolve_config(target)[0]['backend_token'], TOKEN)
        self.assertEqual(json.loads((target / 'config.json').read_text())['task_setting'], 'keep')
        self.assertEqual(json.loads((target / 'config.local.json').read_text())['private_setting'], 'keep')
        self.assertEqual(other.read_text(), 'SYNTHETIC-MODEL-KEY')

    def test_symlink_credentials_are_not_followed(self):
        outside = self.root / 'outside'; outside.write_text('unchanged')
        self.local.symlink_to(outside)
        with self.assertRaises(auth.AuthError): auth.write_credentials(self.root, TOKEN)
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_missing_and_nonstring_tokens_never_start_native_account_check(self):
        for token in ('', None, 123, True, 'line\nbreak'):
            self.write(self.public, backend_url='https://example.invalid', backend_token=token)
            with patch.object(auth.subprocess, 'run') as run, self.assertRaises(auth.AuthError): auth.check(self.root, self.root / 'checker')
            run.assert_not_called()

    def test_diagnostics_classify_failures_without_response_or_token(self):
        cases = {'auth_service_unavailable': 'service_unavailable', 'auth_http_status_503': 'service_unavailable',
                 'auth_rejected': 'auth_rejected', 'user_not_enabled': 'user_not_enabled',
                 'auth_rate_limited': 'rate_limited', 'auth_http_status_404': 'service_endpoint_invalid',
                 'auth_response_unreadable': 'invalid_response', TOKEN: 'auth_failed'}
        for native_reason, reason in cases.items():
            value = json.dumps({'ok': False, 'reason': native_reason, 'detail': TOKEN})
            self.assertEqual(auth.failure_reason(TOKEN, value), reason)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr): auth.report_error(auth.AuthError(reason))
            self.assertNotIn(TOKEN, stderr.getvalue())
            self.assertEqual(len(stderr.getvalue().splitlines()), 2)

    def test_process_timeout_is_distinct_from_account_rejection(self):
        self.write(self.public, backend_url='https://example.invalid', backend_token=TOKEN)
        with patch.object(auth.subprocess, 'run', side_effect=subprocess.TimeoutExpired(TOKEN, 20)), self.assertRaises(auth.AuthError) as error:
            auth.check(self.root, self.root / 'checker')
        self.assertEqual(error.exception.reason, 'service_timeout')

    def test_install_cache_is_bound_to_current_credentials_and_expiry(self):
        auth.write_credentials(self.root, TOKEN)
        fingerprint = auth.credential_fingerprint(self.root)
        with patch.dict(os.environ, {'LC_AUTH_VERIFIED_AT': '1000', 'LC_AUTH_VERIFIED_CONFIG': fingerprint}), \
                patch.object(auth.time, 'time', return_value=1100):
            self.assertTrue(auth.recent_auth(self.root))
            auth.write_credentials(self.root, NEW_TOKEN)
            self.assertFalse(auth.recent_auth(self.root))
        with patch.dict(os.environ, {'LC_AUTH_VERIFIED_AT': '1000', 'LC_AUTH_VERIFIED_CONFIG': auth.credential_fingerprint(self.root)}), \
                patch.object(auth.time, 'time', return_value=1601):
            self.assertFalse(auth.recent_auth(self.root))

    def test_new_credential_cli_never_places_token_in_stdout_or_argv(self):
        for script in ('auth_runtime.py', 'configure_credentials.py'):
            shutil.copy2(ROOT / 'scripts' / script, self.root / script)
        # The deployed entry derives its root from scripts/, as on recipients.
        (self.root / 'scripts').mkdir()
        for script in ('auth_runtime.py', 'configure_credentials.py'):
            shutil.move(str(self.root / script), self.root / 'scripts' / script)
        result = subprocess.run([sys.executable, str(self.root / 'scripts/configure_credentials.py')],
                                input=json.dumps({'backend_token': TOKEN}), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertEqual(auth.resolve_config(self.root)[0]['backend_token'], TOKEN)


@unittest.skipUnless(platform.system() == 'Darwin' and Path('/usr/bin/sandbox-exec').exists(), 'Native macOS loopback acceptance')
class RecipientNativeAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='接收者 complete chain ')
        self.addCleanup(self.temp.cleanup)
        self.fx = packaging.RunnerPackagingTests()
        self.skill, self.runner = self.fx.make_fixture(Path(self.temp.name))
        binary = packaging.auth_binary_name()
        shutil.copy2(ROOT / 'tools/bin' / binary, self.skill / 'tools/bin' / binary)
        self.token, self.status, self.requests = TOKEN, 200, []
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, body))
                accepted = body.get('api_key') == owner.token
                self.send_response(owner.status if accepted else 401)
                self.end_headers()
                self.wfile.write(json.dumps({'user': {'status': 'enabled', 'balance': 1}}).encode())
            def log_message(self, *_): pass
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
        (self.skill / 'config.json').write_text(json.dumps({'backend_url': self.url, 'backend_token': ''}))
        self.env = {'PATH': os.pathsep.join((str(Path(sys.executable).parent), '/usr/bin', '/bin')),
                    'LC_AMAZON_INSTALL_SETUP_ONLY': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        self.policy = '(version 1)(allow default)(deny network*)(allow network-outbound (remote ip "localhost:%d"))' % self.server.server_port

    def run_entry(self, argv, stdin=None):
        result = subprocess.run(['/usr/bin/sandbox-exec', '-p', self.policy] + argv, input=stdin,
                                cwd=self.skill, env=self.env, capture_output=True, text=True, timeout=45)
        for secret in (TOKEN, NEW_TOKEN): self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def install(self, replace=False):
        command = ['bash', str(self.skill / 'scripts/install_for_user.sh'), str(self.runner)]
        if replace: command.append('--replace-token')
        result = self.run_entry(command, self.token + '\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def check_runner_and_business_sentinel(self):
        python = self.runner / '.venv/bin/python'; python.parent.mkdir(parents=True, exist_ok=True)
        if not python.exists(): python.symlink_to(sys.executable)
        script = self.runner / 'scripts/run_amazon_front_crawl.py'
        script.write_text('from pathlib import Path\nPath(__file__).with_suffix(".called").write_text("called")\n')
        result = self.run_entry(['bash', str(self.runner / 'lc-amazon-data-crawl.sh'), 'amazon-front-dry-run'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(script.with_suffix('.called').is_file())

    def test_first_recipient_valid_stdin_token_reaches_real_native_gate_and_runner(self):
        self.install()
        self.assertEqual(len(self.requests), 1)  # Existing installation auth-call budget unchanged.
        self.check_runner_and_business_sentinel()
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(path == '/public/account' and body['api_key'] == TOKEN for path, body in self.requests))
        self.assertEqual(json.loads((self.skill / 'config.json').read_text())['backend_token'], '')
        self.assertEqual(auth.resolve_config(self.runner)[0]['backend_token'], TOKEN)

    def test_token_rotation_updates_existing_runner_and_preserves_api_keys(self):
        self.install()
        api_file = self.runner / 'config/doubao_same_product_mini.json'
        api_file.write_text(json.dumps({'api_key': 'SYNTHETIC-MODEL-KEY', 'model': 'keep'}))
        before = api_file.read_bytes()
        self.token = NEW_TOKEN
        supplied = self.run_entry([sys.executable, str(self.skill / 'scripts/configure_credentials.py')], json.dumps({'backend_token': NEW_TOKEN}))
        self.assertEqual(supplied.returncode, 0, supplied.stderr)
        updated = self.run_entry(['bash', str(self.skill / 'scripts/setup_runner.sh'), str(self.runner)])
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.check_runner_and_business_sentinel()
        self.assertEqual(auth.resolve_config(self.runner)[0]['backend_token'], NEW_TOKEN)
        self.assertEqual(api_file.read_bytes(), before)

    def test_replace_token_installer_repairs_conflict_and_both_roots(self):
        self.install()
        (self.skill / 'config.json').write_text(json.dumps({'backend_url': self.url, 'backend_token': 'STALE-PUBLIC-TOKEN'}))
        self.token = NEW_TOKEN
        self.install(replace=True)
        self.check_runner_and_business_sentinel()
        self.assertEqual(auth.resolve_config(self.skill)[0]['backend_token'], NEW_TOKEN)
        self.assertEqual(auth.resolve_config(self.runner)[0]['backend_token'], NEW_TOKEN)

    def test_empty_local_override_no_longer_rejects_valid_legacy_public_token(self):
        (self.skill / 'config.json').write_text(json.dumps({'backend_url': self.url, 'backend_token': TOKEN}))
        (self.skill / 'config.local.json').write_text(json.dumps({'backend_token': ''}))
        self.install()
        self.check_runner_and_business_sentinel()

    def test_wrong_token_stops_before_business_or_runner_credentials_are_changed(self):
        self.install()
        before = (self.runner / 'config.local.json').read_bytes()
        auth.write_credentials(self.skill, NEW_TOKEN)  # Server still accepts TOKEN only.
        result = self.run_entry(['bash', str(self.skill / 'scripts/setup_runner.sh'), str(self.runner)])
        self.assertEqual(result.returncode, 4)
        self.assertIn('账户鉴权被拒绝', result.stderr)
        self.assertEqual((self.runner / 'config.local.json').read_bytes(), before)
        auth.write_credentials(self.runner, NEW_TOKEN)
        called = self.runner / 'scripts/run_amazon_front_crawl.called'
        self.assertFalse(called.exists())
        result = self.run_entry(['bash', str(self.runner / 'lc-amazon-data-crawl.sh'), 'amazon-front-dry-run'])
        self.assertEqual(result.returncode, 4)
        self.assertFalse(called.exists())

    def test_service_failure_reports_network_reason_for_valid_token(self):
        auth.write_credentials(self.skill, TOKEN)
        self.status = 503
        result = self.run_entry(['bash', str(self.skill / 'scripts/check_auth.sh')])
        self.assertEqual(result.returncode, 4)
        self.assertIn('不能据此判定 token 无效', result.stderr)
        self.assertNotIn('账户鉴权被拒绝', result.stderr)
        self.assertEqual(len(self.requests), 1)  # No new auth retry loop.

    @unittest.skipUnless(os.environ.get('LC_TEST_PWSH'), 'PowerShell executable not configured')
    def test_powershell_install_and_rotation_reach_same_native_account_protocol(self):
        # PowerShell scripts run on macOS here; use the identical native account
        # checker under the Windows entry's filename. This tests script wiring,
        # not the Windows executable ABI (which requires a real Windows host).
        for name in ('check_auth.ps1', 'setup_runner.ps1', 'install_for_user.ps1'):
            shutil.copy2(ROOT / 'scripts' / name, self.skill / 'scripts' / name)
        (self.skill / 'scripts/runner').mkdir()
        for name in ('lc-amazon-data-crawl.ps1', 'lc-amazon-data-crawl.cmd'):
            shutil.copy2(ROOT / 'scripts/runner' / name, self.skill / 'scripts/runner' / name)
        shutil.copy2(ROOT / 'tools/bin' / packaging.auth_binary_name(), self.skill / 'tools/bin/lc-auth-check-windows-amd64.exe')
        pwsh = os.environ['LC_TEST_PWSH']
        for token in (TOKEN, NEW_TOKEN):
            self.token = token
            supplied = self.run_entry([sys.executable, str(self.skill / 'scripts/configure_credentials.py')], json.dumps({'backend_token': token}))
            self.assertEqual(supplied.returncode, 0, supplied.stderr)
            installed = self.run_entry([pwsh, '-NoLogo', '-NoProfile', '-File', str(self.skill / 'scripts/install_for_user.ps1'), str(self.runner)])
            self.assertEqual(installed.returncode, 0, installed.stderr)
            python = self.runner / '.venv/bin/python'; python.parent.mkdir(parents=True, exist_ok=True)
            if not python.exists(): python.symlink_to(sys.executable)
            script = self.runner / 'scripts/run_amazon_front_crawl.py'
            script.write_text('from pathlib import Path\nPath(__file__).with_suffix(".called").write_text("called")\n')
            script.with_suffix('.called').unlink(missing_ok=True)
            ran = self.run_entry([pwsh, '-NoLogo', '-NoProfile', '-File', str(self.runner / 'lc-amazon-data-crawl.ps1'), 'amazon-front-dry-run'])
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertTrue(script.with_suffix('.called').exists())
            self.assertEqual(auth.resolve_config(self.runner)[0]['backend_token'], token)
        self.assertEqual([body['api_key'] for _, body in self.requests], [TOKEN, TOKEN, NEW_TOKEN, NEW_TOKEN])


if __name__ == '__main__':
    unittest.main()
