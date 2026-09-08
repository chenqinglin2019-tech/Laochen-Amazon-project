"""Local credential contract using only private temporary fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import auth_gate
import common
import preflight
import validate_run


class CredentialFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(common, "skill_root", return_value=self.root).start()
        patch.object(preflight, "skill_root", return_value=self.root).start()
        patch.dict(os.environ, {"LC_IPR_TEST_MODE": "", "LC_IPR_OFFLINE_TESTS": ""}).start()
        self.config = {"backend_url": "https://backend.example.test", "backend_token": "backend-fixture-secret"}
        self.write("config.json", json.dumps(self.config))
        self.write("config.example.json", json.dumps({**self.config, "backend_token": ""}))
        self.runtime = {"http": {"timeout_seconds": 31}, "providers": {"example": {"base_url": "https://example.test"}}}
        self.write("references/runtime-config.json", json.dumps(self.runtime))
        self.write(".env", "SIGNA_API_KEY=signa-fixture-secret\nSERPAPI_API_KEY=serpapi-fixture-secret\n")

    def write(self, name, text, mode=0o600):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        target.chmod(mode)
        return target

    def test_exact_runtime_and_url_without_backend_secret(self):
        config = common.load_skill_config()
        self.assertEqual(config, {**self.runtime, "backend_url": self.config["backend_url"]})
        self.assertNotIn(self.config["backend_token"], json.dumps(config))

    def test_every_provider_key_uses_only_dotenv(self):
        values = {name: f"fixture-{name}-secret" for name in common.LOCAL_ENV_CREDENTIALS}
        self.write(".env", "\n".join(f"{common.ENV_CREDENTIALS[name]}={value}" for name, value in values.items()))
        with patch.dict(os.environ, {name: "ignored-environment" for name in common.ENV_CREDENTIALS.values()}), \
                patch.object(subprocess, "run", side_effect=AssertionError("Keychain is forbidden")):
            self.assertEqual(common.credential({}, "backend_token"), self.config["backend_token"])
            for name, value in values.items():
                with self.subTest(name=name):
                    self.assertEqual(common.credential({name: "ignored-config"}, name), value)
                    self.assertEqual(common.credential_issue(name), "")
            (self.root / ".env").unlink()
            for name in values:
                self.assertEqual(common.credential({name: "ignored-config"}, name), "")
            (self.root / "config.json").unlink()
            self.assertEqual(common.credential({"backend_token": "ignored-config"}, "backend_token"), "")

    def test_missing_empty_and_unknown_credentials_are_not_filled_from_other_sources(self):
        self.write(".env", "SIGNA_API_KEY=\nLAOCHEN_BACKEND_TOKEN=wrong-place\n")
        self.write("config.json", json.dumps({**self.config, "backend_token": "  "}))
        for name in ("backend_token", "signa_api_key", "serpapi_api_key"):
            self.assertEqual(common.credential({}, name), "")
            self.assertEqual(common.credential_issue(name), "CREDENTIAL_MISSING")
        self.assertEqual(common.credential_issue("unknown"), "UNKNOWN_CREDENTIAL")

    def test_dotenv_literals_preserve_special_characters_without_execution(self):
        for value in ("raw#hash=$HOME=$(never-run)=suffix", r"' spaces # $VALUE \path '", r'"double # ${VALUE} \t"'):
            self.write(".env", f"# comment\n\nSIGNA_API_KEY = {value}\n")
            expected = value[1:-1] if value[:1] in {"'", '"'} else value
            with patch.object(subprocess, "run", side_effect=AssertionError("No shell execution")):
                self.assertEqual(common.credential({}, "signa_api_key"), expected)

    def test_bad_provider_key_does_not_hide_other_valid_credentials(self):
        for broken, code in (("SIGNA_API_KEY=one\nSIGNA_API_KEY=two", "DUPLICATE_KEY"),
                             ("SIGNA_API_KEY='unterminated", "UNMATCHED_QUOTE"),
                             ("SIGNA_API_KEY=bad\x00value", "INVALID_VALUE")):
            self.write(".env", broken + "\nSERPAPI_API_KEY=valid-unaffected-secret\n")
            self.assertEqual(common.credential({}, "signa_api_key"), "")
            self.assertEqual(common.credential_issue("signa_api_key"), f".env:{code}")
            self.assertEqual(common.credential({}, "serpapi_api_key"), "valid-unaffected-secret")

    def test_backend_json_errors_never_expose_values(self):
        cases = [
            ('{"backend_token":"sensitive-unclosed', "INVALID_JSON"),
            (json.dumps({**self.config, "backend_token": None}), "EXPECTED_STRING_VALUES"),
            (json.dumps({**self.config, "backend_token": 123}), "EXPECTED_STRING_VALUES"),
            (json.dumps({**self.config, "extra": "sensitive-value"}), "EXPECTED_BACKEND_FIELDS"),
            ('{"backend_url":"https://example.test","backend_token":"one","backend_token":"two"}', "DUPLICATE_FIELD"),
            ('[]', "EXPECTED_BACKEND_FIELDS"),
        ]
        for text, code in cases:
            with self.subTest(code=code):
                self.write("config.json", text)
                self.assertEqual(common.credential({}, "backend_token"), "")
                self.assertEqual(common.credential_issue("backend_token"), f"config.json:{code}")
                with self.assertRaisesRegex(common.CredentialFileError, f"config.json:{code}"):
                    common.load_skill_config()

    def test_file_failures_are_safe_and_do_not_fall_back(self):
        for filename, name in (("config.json", "backend_token"), (".env", "signa_api_key")):
            original = (self.root / filename).read_text()
            with self.subTest(filename=filename):
                self.write(filename, "x" * (common.LOCAL_ENV_MAX_BYTES + 1))
                self.assertEqual(common.credential_issue(name), f"{filename}:FILE_TOO_LARGE")
                self.write(filename, original)
                with patch.object(common.os, "open", side_effect=PermissionError()):
                    self.assertEqual(common.credential_issue(name), f"{filename}:FILE_UNREADABLE")
                (self.root / filename).unlink()
                self.assertEqual(common.credential_issue(name), f"{filename}:FILE_MISSING")
                target = self.write(filename + ".fixture", original)
                (self.root / filename).symlink_to(target)
                self.assertEqual(common.credential_issue(name), f"{filename}:NOT_REGULAR_FILE")
                (self.root / filename).unlink()
                self.write(filename, original)
                if os.name == "posix":
                    for mode in (0o644, 0o660, 0o000):
                        (self.root / filename).chmod(mode)
                        self.assertEqual(common.credential_issue(name), f"{filename}:PRIVATE_PERMISSIONS_REQUIRED")
                    (self.root / filename).chmod(0o600)

    def test_invalid_assignment_and_encoding(self):
        self.write(".env", "export SIGNA_API_KEY=not-supported\n")
        self.assertEqual(common.credential_issue("signa_api_key"), ".env:INVALID_ASSIGNMENT")
        (self.root / ".env").write_bytes(b"\xff")
        self.assertEqual(common.credential_issue("signa_api_key"), ".env:FILE_UNREADABLE")

    def test_offline_never_opens_private_files_even_with_valid_local_credentials(self):
        for flag in ("LC_IPR_TEST_MODE", "LC_IPR_OFFLINE_TESTS"):
            with patch.dict(os.environ, {flag: "1"}), patch.object(
                common, "_private_credential_text", side_effect=AssertionError("Must not open credential files")
            ):
                self.assertEqual(common.credential({}, "backend_token"), "")
                self.assertEqual(common.credential({}, "signa_api_key"), "")
                self.assertEqual(common.configured_credential_values(), [])
                self.assertNotIn("backend_token", common.load_skill_config())
                self.assertEqual(preflight.local_secret_findings(), [])

    def test_preflight_accepts_backend_and_detects_misplaced_provider_credentials(self):
        self.assertEqual(preflight.local_secret_findings(), [])
        self.assertEqual(preflight.credential_storage_checkpoint()["status"], "local_files_only")
        self.write("references/runtime-config.json", json.dumps({**self.runtime, "items": [{"INPI_PASSWORD": "wrong-place-secret"}]}))
        findings = preflight.local_secret_findings()
        self.assertEqual(findings, ["references/runtime-config.json:items.0.INPI_PASSWORD"])
        checkpoint = preflight.credential_storage_checkpoint()
        self.assertEqual(checkpoint["status"], "configuration_error")
        self.assertNotIn("wrong-place-secret", json.dumps(checkpoint))

    def test_leak_detector_reads_both_credential_files_not_process_environment(self):
        with patch.dict(os.environ, {"SERPER_API_KEY": "ignored-env-secret"}):
            values = validate_run.configured_secrets({"backend_token": "ignored-dictionary-secret"})
        self.assertEqual(set(values), {"backend-fixture-secret", "signa-fixture-secret", "serpapi-fixture-secret"})

    def test_short_account_names_do_not_block_ordinary_evidence_text(self):
        self.write(".env", "JPO_API_USERNAME=patent\nJPO_API_PASSWORD=long-fixture-password\n")
        values = validate_run.configured_secrets({})
        self.assertNotIn("patent", values)
        self.assertIn("long-fixture-password", values)
        self.assertFalse(any(value in '{"right_type":"patent"}' for value in values))

    def test_auth_uses_private_local_config_and_strips_credential_environment(self):
        binary = self.write("tools/bin/auth-fixture", "offline component")
        self.runtime["auth"] = {"binary_sha256": {binary.name: common.sha256_file(binary)}}
        self.write("references/runtime-config.json", json.dumps(self.runtime))
        observed = {}

        def run(command, **kwargs):
            path = Path(command[2])
            observed["path"] = path
            self.assertEqual(json.loads(path.read_text()), self.config)
            self.assertNotIn(self.config["backend_token"], " ".join(command))
            self.assertTrue(set(common.ENV_CREDENTIALS.values()).isdisjoint(kwargs["env"]))
            self.assertNotIn("LAOCHEN_BACKEND_URL", kwargs["env"])
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(auth_gate, "auth_binary", return_value=binary), patch.object(auth_gate.subprocess, "run", side_effect=run), \
                patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": "ignored-env", "LAOCHEN_BACKEND_URL": "https://ignored.test"}):
            auth_gate.require_auth()
        self.assertFalse(observed["path"].exists())

    def test_auth_missing_token_and_invalid_config_fail_without_spawning(self):
        binary = self.write("tools/bin/auth-fixture", "offline component")
        self.runtime["auth"] = {"binary_sha256": {binary.name: common.sha256_file(binary)}}
        self.write("references/runtime-config.json", json.dumps(self.runtime))
        with patch.object(auth_gate, "auth_binary", return_value=binary), patch.object(auth_gate.subprocess, "run") as run:
            self.write("config.json", json.dumps({**self.config, "backend_token": ""}))
            with self.assertRaisesRegex(SystemExit, "未配置访问 Token"):
                auth_gate.require_auth()
            self.write("config.json", "not-json-secret")
            with self.assertRaisesRegex(SystemExit, "鉴权配置无效"):
                auth_gate.require_auth()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
