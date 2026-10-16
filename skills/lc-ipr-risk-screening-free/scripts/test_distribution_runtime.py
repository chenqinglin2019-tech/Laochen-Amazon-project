"""Recipient runtime checks: no real login/model calls and no account state."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_runtime_discovery as native
import setup_skill
from review_isolation import DISABLED_FEATURES


class NativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='接收者 runtime ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def binary(self, path, windows=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b'\xcf\xfa\xed\xfe' + b'\0' * 124
        if windows:
            data = bytearray(b'MZ' + b'\0' * 126)
            data[60:64] = (64).to_bytes(4, 'little')
            data[64:68] = b'PE\0\0'
            data[68:70] = (0x8664).to_bytes(2, 'little')
        path.write_bytes(data)
        path.chmod(0o700)
        return path

    def test_explicit_priority_and_invalid_override_never_falls_back(self):
        binary = self.binary(self.root / 'explicit')
        with patch.object(native.shutil, 'which') as which:
            self.assertEqual(native.discover_binary(binary, platform='darwin', environment={'LC_IPR_CODEX_BINARY': 'missing'}), binary.resolve())
            with self.assertRaisesRegex(ValueError, 'NATIVE_CLI_REQUIRED'):
                native.discover_binary(self.root / 'missing', platform='darwin', environment={})
            which.assert_not_called()

    def test_script_wrappers_rejected_including_no_extension(self):
        for name in ('codex.cmd', 'codex.ps1', 'codex'):
            path = self.root / name
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o700)
            with self.assertRaisesRegex(ValueError, 'NATIVE_CLI_REQUIRED'):
                native.validate_binary(path, 'darwin')

    def test_mac_user_app_discovered_without_path(self):
        binary = self.binary(self.root / 'Applications/Codex.app/Contents/Resources/codex')
        with patch.object(native.shutil, 'which', return_value=None), patch.object(native, 'validate_binary', wraps=native.validate_binary) as validate:
            original = validate._mock_wraps
            validate.side_effect = lambda path, platform: original(path, platform) if self.root in Path(path).parents else (_ for _ in ()).throw(ValueError('missing'))
            self.assertEqual(native.discover_binary(platform='darwin', environment={}, home=self.root), binary.resolve())

    def test_windows_package_metadata_and_bounded_scan(self):
        binary = self.binary(self.root / 'app/resources/codex-cli/codex.exe', windows=True)
        calls = []
        def probe(command):
            calls.append(command)
            return 0, json.dumps([str(self.root / 'app')]), ''
        with patch.object(native.shutil, 'which', return_value=None):
            self.assertEqual(native.discover_binary(platform='win32', environment={}, probe=probe), binary.resolve())
        self.assertIn('-NoProfile', calls[0])
        self.assertIn('Get-AppxPackage', calls[0][-1])
        self.assertNotIn('-AllUsers', calls[0][-1])

    def test_windows_npm_global_install_finds_the_vendor_binary_but_never_the_cmd_shim(self):
        shim = self.root / 'npm' / 'codex.cmd'
        shim.parent.mkdir(parents=True)
        shim.write_text('@echo off\r\nnode "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n')
        binary = self.binary(self.root / 'npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/codex/codex.exe',
                             windows=True)
        def which(name, path=None):
            return str(shim) if name == 'codex.cmd' else None
        with patch.object(native.shutil, 'which', side_effect=which):
            self.assertEqual(native.discover_binary(platform='win32', environment={'PATH': str(shim.parent)}),
                             binary.resolve())
            with self.assertRaisesRegex(ValueError, 'NATIVE_CLI_REQUIRED'):
                native.discover_binary(shim, platform='win32', environment={})
        appdata = self.root / 'appdata'
        vendor = self.binary(appdata / 'npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/codex/codex.exe',
                             windows=True)
        with patch.object(native.shutil, 'which', return_value=None):
            self.assertEqual(native.discover_binary(platform='win32', environment={'APPDATA': str(appdata)}),
                             vendor.resolve())

    def test_windows_native_path_supported_and_bad_pe_rejected(self):
        binary = self.binary(self.root / 'codex.exe', windows=True)
        with patch.object(native.shutil, 'which', return_value=str(binary)):
            self.assertEqual(native.discover_binary(platform='win32', environment={}), binary.resolve())
        binary.write_bytes(b'MZnot a native PE')
        with self.assertRaises(ValueError):
            native.validate_binary(binary, 'win32')

    def test_cli_capability_reports_without_login_or_model(self):
        calls = []
        def probe(command):
            calls.append(command)
            if command[-1] == '--version':
                return 0, 'codex-cli 0.162.0-alpha.2\n', ''
            if command[-1] == '--help':
                return 0, '\n'.join(native.REQUIRED_OPTIONS) + '\nread-only\n', ''
            return 0, '\n'.join(x + ' stable false' for x in (*DISABLED_FEATURES, 'skip_host_skill_discovery')), ''
        result = native.inspect_capability(self.root / 'codex', probe, DISABLED_FEATURES, 'tool-free-process')
        self.assertEqual(result['status'], 'cli_capable')
        self.assertEqual([x[1:] for x in calls], [['--version'], ['exec', '--help'], ['features', 'list']])
        self.assertEqual(result['model_availability'], 'not_verified')

    def test_missing_isolation_feature_is_not_silently_accepted(self):
        def probe(command):
            if command[-1] == '--version':
                return 0, 'codex-cli 1.0\n', ''
            if command[-1] == '--help':
                return 0, '\n'.join(native.REQUIRED_OPTIONS) + '\nread-only\n', ''
            return 0, 'shell_tool stable true\n', ''
        result = native.inspect_capability(self.root / 'codex', probe, DISABLED_FEATURES, 'tool-free-process')
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('skip_host_skill_discovery', result['missing_features'])

    def test_diagnostic_failure_hides_arbitrary_output(self):
        result = native.inspect_capability(self.root / 'codex', lambda cmd: (1, 'secret-value', 'secret-value'), DISABLED_FEATURES, 'tool-free-process')
        self.assertNotIn('secret-value', json.dumps(result))

    def test_automatic_discovery_skips_old_native_and_selects_capable_app(self):
        old = self.binary(self.root / 'Applications/ChatGPT.app/Contents/Resources/codex')
        current = self.binary(self.root / 'Applications/Codex.app/Contents/Resources/codex')
        checked = []
        def capability(path):
            checked.append(path)
            return {'status': 'cli_capable' if path == current else 'unavailable'}
        validate = native.validate_binary
        def local_only(path, platform):
            if self.root not in Path(path).parents:
                raise ValueError('missing')
            return validate(path, platform)
        with patch.object(native, 'validate_binary', side_effect=local_only), \
             patch.object(native.shutil, 'which', return_value=None):
            chosen = native.discover_binary(platform='darwin', environment={}, home=self.root, capability=capability)
        self.assertEqual(chosen, current)
        self.assertEqual(checked, [old, current])

    def test_explicit_native_without_capability_does_not_fall_back(self):
        old = self.binary(self.root / 'old-native')
        with patch.object(native.shutil, 'which') as which:
            with self.assertRaisesRegex(ValueError, 'CAPABILITY_UNAVAILABLE'):
                native.discover_binary(old, platform='darwin', environment={},
                                       capability=lambda path: {'status': 'unavailable'})
            which.assert_not_called()

    def test_read_only_capability_cache_is_process_local_and_invalidates_changed_binary(self):
        from review_isolation import inspect_native_capability
        binary = self.binary(self.root / 'cache-native')
        def probe(command):
            if command[-1] == '--version':
                return 0, 'codex-cli 1.0\n', ''
            if command[-1] == '--help':
                return 0, '\n'.join(native.REQUIRED_OPTIONS) + '\nread-only\n', ''
            return 0, '\n'.join(DISABLED_FEATURES) + '\nskip_host_skill_discovery\n', ''
        with patch('setup_skill._probe', side_effect=probe) as checked:
            self.assertEqual(inspect_native_capability(binary, 'macos-sandbox')['status'], 'cli_capable')
            inspect_native_capability(binary, 'macos-sandbox')
            self.assertEqual(checked.call_count, 3)
            binary.write_bytes(binary.read_bytes() + b'changed')
            inspect_native_capability(binary, 'macos-sandbox')
            self.assertEqual(checked.call_count, 6)


class TomlInstallTests(unittest.TestCase):
    def test_low_python_lock_and_alias_without_sender_fallback(self):
        import runtime_compat
        import types
        parser = types.ModuleType('tomli')
        original_spec = runtime_compat.importlib.util.find_spec
        with patch.object(runtime_compat.importlib.util, 'find_spec', side_effect=lambda name: (object() if sys.modules.get('tomllib') is parser else None) if name == 'tomllib' else object() if name == 'tomli' else original_spec(name)), \
             patch.object(runtime_compat.importlib, 'import_module', return_value=parser), \
             patch.object(runtime_compat, '_package_path', return_value=None) as fallback, \
             patch.dict(sys.modules):
            runtime_compat.install_existing_dependencies()
            self.assertIs(sys.modules['tomllib'], parser)
            self.assertFalse(any(call.args[0] == 'tomllib' for call in fallback.call_args_list))
        requirements = (Path(__file__).resolve().parents[1] / 'requirements.txt').read_text()
        self.assertIn("tomli==2.5.0; python_version < '3.11'", requirements)


if __name__ == '__main__':
    unittest.main()
