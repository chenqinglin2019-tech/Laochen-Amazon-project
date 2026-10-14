"""Authorization failures must stop before business input, networking, or output."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import auth_gate
import csc
from auth_support import auth_server, configure_local, TEST_TOKEN


class AuthTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="compliance-auth-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # Minimal isolated config and native binary; never edit the source package.
        shutil.copy2(ROOT / "config.json", self.root / "config.json")
        binary = auth_gate.auth_binary()
        target = self.root / "tools/bin" / binary.name
        target.parent.mkdir(parents=True)
        shutil.copy2(binary, target)
        shutil.copy2(ROOT / "tools/auth.json", self.root / "tools/auth.json")
        root_patch = patch.object(auth_gate, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        env_patch = patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": TEST_TOKEN})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_real_binary_sends_only_token_and_new_skill_id_and_rechecks(self):
        with auth_server() as state:
            configure_local(self.root, state)
            auth_gate.require_auth()
            state.update(allowed=False, reason="permission_disabled")
            # Prior success and reference-skill test flags cannot bypass the gate.
            with patch.dict(os.environ, {"LAOCHEN_AUTH_PASSED": "1", "LC_IPR_TEST_MODE": "1"}):
                with self.assertRaises(auth_gate.AuthError) as exc:
                    auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "permission_disabled")
            self.assertEqual(state["requests"], [("/auth/skill-check", {
                "api_key": TEST_TOKEN, "skill_id": "amazon_compliance_screening"})] * 2)

    def test_deny_reasons_and_service_failure(self):
        with auth_server() as state:
            configure_local(self.root, state)
            for reason in ("invalid_token", "user_disabled", "insufficient_balance", "unknown_skill",
                           "skill_disabled", "permission_missing", "permission_disabled"):
                with self.subTest(reason=reason):
                    state.update(allowed=False, reason=reason)
                    with self.assertRaises(auth_gate.AuthError) as exc:
                        auth_gate.require_auth()
                    self.assertEqual(exc.exception.reason, reason)
            state.update(status=503)
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "service_unavailable")

    def test_unreachable_service_stops(self):
        with auth_server() as state:
            configure_local(self.root, state)
        with self.assertRaises(auth_gate.AuthError) as exc:
            auth_gate.require_auth()
        self.assertEqual(exc.exception.reason, "service_unavailable")

    def test_package_rejects_private_config_token_and_missing_auth_binary(self):
        import build_distribution as packaging
        import csc_runtime as runtime
        skill = self.root / "package"
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns("config.local.json", "__pycache__"))
        manifest_path = skill / "DISTRIBUTION-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        configure_local(skill, {"url": "http://127.0.0.1:1"})
        with patch.object(packaging, "ROOT", skill):
            built = packaging.build(self.root / "clean.zip")
        import zipfile
        with zipfile.ZipFile(built["zip"]) as archive:
            self.assertFalse(any(name.endswith("config.local.json") for name in archive.namelist()))
        config_path = skill / "config.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        cfg["backend_token"] = "must-not-ship-test-secret"
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        with patch.object(packaging, "ROOT", skill):
            with self.assertRaisesRegex(ValueError, "backend_token 必须为空"):
                packaging.build(self.root / "secret.zip", refresh=True)
        self.assertFalse((self.root / "secret.zip").exists())
        manifest["files"] = [item for item in manifest["files"] if not item["path"].endswith("linux-amd64")]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        cfg["backend_token"] = ""
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        with patch.object(packaging, "ROOT", skill):
            with self.assertRaisesRegex(ValueError, "缺少必需文件"):
                packaging.build(self.root / "missing.zip", refresh=True)
        manifest["files"].append({"path": "config.local.json"})
        with self.assertRaisesRegex(ValueError, "不安全"):
            list(runtime.manifest_entries(skill, manifest))

    def test_missing_token_never_starts_binary(self):
        with patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": ""}), patch.object(auth_gate.subprocess, "run") as run:
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "missing_token")
            run.assert_not_called()

    def test_environment_token_precedes_local_config(self):
        with auth_server() as state:
            configure_local(self.root, state)
            with patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": "environment-test-token"}):
                auth_gate.require_auth()
            self.assertEqual(state["requests"][0][1]["api_key"], "environment-test-token")
            with patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": ""}):
                auth_gate.require_auth()
            self.assertEqual(state["requests"][1][1]["api_key"], TEST_TOKEN)

    def test_bad_or_missing_binary_never_executes(self):
        with patch.object(auth_gate.subprocess, "run") as run:
            binary = auth_gate.auth_binary()
            binary.write_bytes(b"corrupt")
            for candidate in (binary, self.root / "missing"):
                with patch.object(auth_gate, "auth_binary", return_value=candidate):
                    with self.assertRaises(auth_gate.AuthError) as exc:
                        auth_gate.require_auth()
                    self.assertEqual(exc.exception.reason, "auth_component_invalid")
            run.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX executable permissions")
    def test_executable_in_read_only_install_does_not_require_chmod(self):
        binary = auth_gate.auth_binary()
        binary.chmod(0o555)
        original_chmod = Path.chmod

        def readonly_chmod(path, mode, **kwargs):
            if path == binary:
                raise PermissionError("read-only installation")
            return original_chmod(path, mode, **kwargs)

        with auth_server() as state:
            configure_local(self.root, state)
            with patch.object(Path, "chmod", readonly_chmod):
                auth_gate.require_auth()
            self.assertEqual(len(state["requests"]), 1)

    def test_package_rejects_missing_runtime_dependencies(self):
        import build_distribution as packaging
        skill = self.root / "incomplete-package"
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns("config.local.json", "__pycache__"))
        manifest_path = skill / "DISTRIBUTION-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for missing in ("scripts/csc_runtime.py", "scripts/csc_table.py",
                        "scripts/compliance_engine/review.py", "tests/auth_support.py", "tools/auth.json"):
            with self.subTest(missing=missing):
                incomplete = {**manifest, "files": [item for item in manifest["files"] if item["path"] != missing]}
                manifest_path.write_text(json.dumps(incomplete), encoding="utf-8")
                with patch.object(packaging, "ROOT", skill), self.assertRaisesRegex(ValueError, "缺少必需文件"):
                    packaging.build(self.root / "incomplete.zip", refresh=True)

    def test_package_rejects_private_config_case_variants(self):
        import csc_runtime as runtime
        manifest = {"schema": "SKILL-DISTRIBUTION/1.0", "package_name": ROOT.name}
        for name in ("CONFIG.LOCAL.JSON", "Config.Local.Json", "nested/config.local.json"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('{"backend_token":"private-test-token"}', encoding="utf-8")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "不安全"):
                list(runtime.manifest_entries(self.root, {**manifest, "files": [{"path": name}]}))

    def test_bad_config_and_local_hash_override_rejected(self):
        local = self.root / "config.local.json"
        for data in ([], None, {"auth": {"binary_sha256": {}}}, {"backend_token": 123}, {"backend_url": None}):
            local.write_text(json.dumps(data), encoding="utf-8")
            with patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": ""}):
                with self.assertRaises(auth_gate.AuthError) as exc:
                    auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "configuration_error")

    def test_internal_auth_config_missing_or_corrupt_stops_before_execution(self):
        path = self.root / "tools/auth.json"
        original = json.loads(path.read_text())
        saved = path.with_suffix(".saved")
        path.rename(saved)
        with patch.object(auth_gate.subprocess, "run") as run:
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "configuration_error")
            run.assert_not_called()
        saved.rename(path)
        invalid = ["{", "null", "[]", "{}"]
        invalid += [json.dumps({**original, "timeout_seconds": value}) for value in (None, True, 0, -1, "20")]
        invalid += [json.dumps({**original, "binary_sha256": value}) for value in (None, {}, {k: "bad" for k in original["binary_sha256"]})]
        for raw in invalid:
            with self.subTest(raw=raw), patch.object(auth_gate.subprocess, "run") as run:
                path.write_text(raw)
                with self.assertRaises(auth_gate.AuthError) as exc:
                    auth_gate.require_auth()
                self.assertEqual(exc.exception.reason, "configuration_error")
                run.assert_not_called()
        original["binary_sha256"][auth_gate.auth_binary().name] = "0" * 64
        path.write_text(json.dumps(original))
        with patch.object(auth_gate.subprocess, "run") as run:
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "auth_component_invalid")
            run.assert_not_called()

    def test_two_field_user_config_works_with_separate_internal_settings(self):
        with auth_server() as state, patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": ""}):
            (self.root / "config.json").write_text(json.dumps({
                "backend_url": state["url"], "backend_token": TEST_TOKEN}))
            auth_gate.require_auth()
            self.assertEqual(state["requests"][0][1]["api_key"], TEST_TOKEN)
            state.update(allowed=False, reason="permission_disabled")
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "permission_disabled")

    def test_package_rejects_extra_public_settings_and_internal_hash_mismatch(self):
        import build_distribution as packaging
        skill = self.root / "package-settings"
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns("config.local.json", "__pycache__"))
        config_path = skill / "config.json"
        config = json.loads(config_path.read_text())
        config_path.write_text(json.dumps({**config, "auth": {}}))
        with patch.object(packaging, "ROOT", skill):
            with self.assertRaisesRegex(ValueError, "只允许"):
                packaging.build(self.root / "extra.zip", refresh=True)
            config_path.write_text(json.dumps(config))
            auth_path = skill / "tools/auth.json"
            settings = json.loads(auth_path.read_text())
            settings["binary_sha256"][auth_gate.auth_binary().name] = "0" * 64
            auth_path.write_text(json.dumps(settings))
            with self.assertRaisesRegex(ValueError, "鉴权二进制与配置摘要不一致"):
                packaging.build(self.root / "bad-hash.zip", refresh=True)

    def test_unsupported_architecture_stops(self):
        with patch.object(auth_gate.platform, "system", return_value="Linux"), patch.object(auth_gate.platform, "machine", return_value="aarch64"):
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "auth_component_invalid")

    def test_timeout_and_invalid_component_responses(self):
        cases = [(subprocess.CompletedProcess([], 0, '{}', ''), "invalid_response"),
                 (subprocess.CompletedProcess([], 0, '{"ok":1,"message":"auth_passed"}', ''), "invalid_response"),
                 (subprocess.CompletedProcess([], 1, '', TEST_TOKEN), "invalid_response")]
        for result, reason in cases:
            with patch.object(auth_gate.subprocess, "run", return_value=result):
                with self.assertRaises(auth_gate.AuthError) as exc:
                    auth_gate.require_auth()
                self.assertEqual(exc.exception.reason, reason)
                self.assertNotIn(TEST_TOKEN, str(exc.exception))
        with patch.object(auth_gate.subprocess, "run", side_effect=subprocess.TimeoutExpired("auth", 1)):
            with self.assertRaises(auth_gate.AuthError) as exc:
                auth_gate.require_auth()
            self.assertEqual(exc.exception.reason, "service_unavailable")

    def test_token_not_in_argv_and_temp_config_is_private(self):
        def run(argv, **kwargs):
            self.assertNotIn(TEST_TOKEN, " ".join(argv))
            path = Path(argv[argv.index("--config") + 1])
            self.assertEqual(json.loads(path.read_text())["backend_token"], TEST_TOKEN)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.is_relative_to(self.root))
            return subprocess.CompletedProcess(argv, 0, '{"ok":true,"message":"auth_passed"}', '')
        with patch.object(auth_gate.subprocess, "run", side_effect=run):
            auth_gate.require_auth()

    def test_all_business_commands_stop_before_handlers(self):
        commands = {
            "quick": [], "table": ["--input", "unread.csv"],
            "init": ["--input", "unread.json", "--sites", "US", "--task", str(self.root / "task")],
            "match": ["--task", "unread", "--profile", "unread"],
            "review": ["--task", "unread", "--file", "unread"],
            "render": ["--task", "unread"], "status": ["--task", "unread"], "families": [],
        }
        for cmd, args in commands.items():
            with self.subTest(command=cmd), patch.object(sys, "argv", ["csc.py", cmd, *args]), \
                    patch.object(csc, "require_auth", side_effect=auth_gate.AuthError("permission_disabled")), \
                    patch.object(csc, "cmd_" + cmd) as handler, redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exc:
                    csc.main()
                self.assertEqual(exc.exception.code, 1)
                self.assertEqual(json.loads(output.getvalue())["reason"], "permission_disabled")
                handler.assert_not_called()
        self.assertFalse((self.root / "task").exists())

    def test_help_and_doctor_do_not_call_cloud(self):
        with patch.object(csc, "require_auth", side_effect=AssertionError("cloud call")):
            for args in (["--help"], ["quick", "--help"], ["doctor"]):
                with patch.object(sys, "argv", ["csc.py", *args]), redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as exc:
                        csc.main()
                    self.assertEqual(exc.exception.code, 0)

    def test_real_denial_has_no_business_output_or_page_fetch(self):
        with auth_server() as state:
            configure_local(self.root, state)
            state.update(allowed=False, reason="permission_missing")
            output_dir = self.root / "must-not-exist"
            with patch.object(sys, "argv", ["csc.py", "quick", "--url", "https://example.invalid/item",
                                          "--input", "missing-input.json", "--out", str(output_dir)]), \
                    patch.object(csc.ct, "fetch_page", side_effect=AssertionError("business fetch")), \
                    redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exc:
                    csc.main()
            self.assertEqual(exc.exception.code, 1)
            self.assertEqual(json.loads(output.getvalue())["reason"], "permission_missing")
            self.assertNotIn(TEST_TOKEN, output.getvalue())
            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
