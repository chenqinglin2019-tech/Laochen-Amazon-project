"""Synthetic credentials only; no real accounts or network."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('credential_writer', Path(__file__).with_name('configure_credentials.py'))
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config.json').write_text(json.dumps({'backend_url': 'https://example.invalid',
                                                          'backend_token': '', 'keep': True}))
        (self.root / '.env').write_text('# preserved\nSERPER_API_KEY=old\nSIGNA_API_KEY=keep\n')

    def test_token_and_key_update_preserves_other_fields_and_hides_values(self):
        result = writer.configure(self.root, {'backend_token': 'synthetic-token-1',
                                             'api_keys': {'SERPER_API_KEY': 'synthetic-"$#-key'}})
        self.assertNotIn('synthetic', json.dumps(result))
        config = json.loads((self.root / 'config.json').read_text())
        self.assertEqual(config['backend_url'], 'https://example.invalid')
        self.assertTrue(config['keep'])
        self.assertEqual(config['backend_token'], 'synthetic-token-1')
        env = (self.root / '.env').read_text()
        self.assertIn('SIGNA_API_KEY=keep', env)
        self.assertIn('# preserved', env)
        if os.name == 'posix':
            for name in ['config.json', '.env']:
                self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o600)

    def test_token_only_secures_git_checkout_env_without_changing_bytes(self):
        path = self.root / '.env'; before = path.read_bytes(); path.chmod(0o644)
        writer.configure(self.root, {'backend_token': 'synthetic'})
        self.assertEqual(path.read_bytes(), before)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_written_api_keys_reach_all_provider_readers_and_request_adapters(self):
        from unittest.mock import patch
        import common
        import serper_client as serper
        import serpapi_patents_client as serpapi
        import epo_ops_client as epo
        import shutil
        keys = {key: 'synthetic-' + key for key in writer.API_FIELDS}
        writer.configure(self.root, {'api_keys': keys})
        (self.root / 'references').mkdir()
        shutil.copy2(Path(__file__).resolve().parents[1] / 'references/runtime-config.json',
                     self.root / 'references/runtime-config.json')
        with patch.dict(os.environ, {}, clear=True), patch.object(common, 'skill_root', return_value=self.root):
            for internal, name in common.ENV_CREDENTIALS.items():
                if internal != 'backend_token':
                    self.assertEqual(common.credential({}, internal), keys[name])
            self.assertEqual(epo.settings()[-2:], (keys['EPO_OPS_CONSUMER_KEY'], keys['EPO_OPS_CONSUMER_SECRET']))
            with patch.object(serper, 'http_json', return_value=({'organic': []}, {}, b'{}')) as send:
                serper.call('search', {'q': 'synthetic fixture'})
                self.assertEqual(send.call_args.kwargs['headers']['X-API-KEY'], keys['SERPER_API_KEY'])
            with patch.object(serpapi, 'http_json', return_value=({'organic_results': [], 'search_metadata': {'status': 'Success'}}, {}, b'{}')) as send:
                _, base, key = serpapi.settings()
                serpapi.search(base, key, 5, {'q': 'synthetic', 'num': 10, 'country': 'US'})
                from urllib.parse import parse_qs, urlparse
                self.assertEqual(parse_qs(urlparse(send.call_args.args[0]).query)['api_key'], [keys['SERPAPI_API_KEY']])

    def test_invalid_input_does_not_write(self):
        before = (self.root / 'config.json').read_bytes()
        for payload in [{}, {'backend_token': ''}, {'backend_token': None},
                        {'api_keys': {'UNKNOWN_KEY': 'synthetic'}},
                        {'backend_token': 'synthetic', 'api_keys': {'SERPER_API_KEY': 'bad\nvalue'}}]:
            with self.assertRaises(ValueError):
                writer.configure(self.root, payload)
            self.assertEqual(before, (self.root / 'config.json').read_bytes())

    def test_duplicate_env_is_rejected_before_token_write(self):
        (self.root / '.env').write_text('SERPER_API_KEY=\nSERPER_API_KEY=\n')
        before = (self.root / 'config.json').read_bytes()
        with self.assertRaises(ValueError):
            writer.configure(self.root, {'backend_token': 'synthetic', 'api_keys': {'SERPER_API_KEY': 'synthetic'}})
        self.assertEqual(before, (self.root / 'config.json').read_bytes())

    def test_symlink_is_refused(self):
        target = self.root / 'outside'; target.write_text('{}')
        (self.root / 'config.json').unlink()
        (self.root / 'config.json').symlink_to(target)
        with self.assertRaises(ValueError):
            writer.configure(self.root, {'backend_token': 'synthetic'})
        self.assertEqual(target.read_text(), '{}')

    def test_token_can_initialize_missing_config_but_key_needs_env(self):
        (self.root / 'config.json').unlink()
        writer.configure(self.root, {'backend_token': 'synthetic'})
        self.assertEqual(json.loads((self.root / 'config.json').read_text())['backend_token'], 'synthetic')
        (self.root / '.env').unlink()
        with self.assertRaises(ValueError):
            writer.configure(self.root, {'api_keys': {'SERPER_API_KEY': 'synthetic'}})


if __name__ == '__main__':
    unittest.main()
