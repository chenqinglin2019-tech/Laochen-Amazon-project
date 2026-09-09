"""Authorization startup with synthetic files and no real backend requests."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import auth_gate
import common
from offline_test_support import offline_environment


class AuthStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="auth startup fixture ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, name, value in (
            (common, "skill_root", self.root),
            (auth_gate, "skill_root", self.root),
            (auth_gate.platform, "system", "Darwin"),
            (auth_gate.platform, "machine", "arm64"),
        ):
            mock = patch.object(target, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        environment = offline_environment()
        environment.update(LC_IPR_TEST_MODE="", LC_IPR_OFFLINE_TESTS="", LAOCHEN_AUTH_PASSED="",
                           LAOCHEN_BACKEND_TOKEN="synthetic-environment-secret")
        mock = patch.dict(os.environ, environment, clear=True)
        mock.start()
        self.addCleanup(mock.stop)
        config = self.root / "config.json"
        config.write_text(json.dumps({"backend_url": "https://backend.example.test",
                                      "backend_token": "synthetic-config-secret"}))
        config.chmod(0o600)
        self.binary = self.make_component()

    def make_component(self):
        binary = auth_gate.auth_binary()
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("Synthetic component; never execute this file.")
        binary.chmod(0o600)
        runtime = self.root / "references/runtime-config.json"
        runtime.parent.mkdir(exist_ok=True)
        runtime.write_text(json.dumps({"auth": {"binary_sha256": {
            binary.name: common.sha256_file(binary),
        }}}))
        return binary

    def test_both_mac_architectures_remove_only_quarantine_before_auth(self):
        for machine in ("arm64", "x86_64"):
            with self.subTest(machine=machine), patch.object(auth_gate.platform, "machine", return_value=machine):
                binary = self.make_component()
                commands = []

                def run(command, **kwargs):
                    commands.append(command)
                    self.assertTrue(set(common.ENV_CREDENTIALS.values()).isdisjoint(kwargs["env"]))
                    self.assertNotIn("synthetic-config-secret", " ".join(command))
                    if command == ["/usr/bin/xattr", str(binary)]:
                        return subprocess.CompletedProcess(command, 0, "com.apple.quarantine\ncom.apple.provenance\n", "")
                    if command[0] == str(binary):
                        self.assertTrue(binary.stat().st_mode & 0o111)
                        self.assertEqual(command[1], "--config")
                        self.assertEqual(json.loads(Path(command[2]).read_text())["backend_token"],
                                         "synthetic-environment-secret")
                    return subprocess.CompletedProcess(command, 0, "", "")

                with patch.object(auth_gate.subprocess, "run", side_effect=run):
                    auth_gate.require_auth()
                self.assertEqual(commands[:2], [["/usr/bin/xattr", str(binary)],
                    ["/usr/bin/xattr", "-d", "com.apple.quarantine", str(binary)]])
                self.assertEqual(len(commands), 3)
                self.assertEqual(commands[-1][0], str(binary))

    def test_mac_without_quarantine_continues_without_deleting_attributes(self):
        with patch.object(auth_gate.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, "com.apple.provenance\n", ""
        )) as run:
            auth_gate.require_auth()
        self.assertEqual(len(run.call_args_list), 2)
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/xattr", str(self.binary)])
        self.assertEqual(run.call_args_list[1].args[0][0], str(self.binary))

    def test_linux_and_windows_do_not_call_xattr(self):
        for system in ("Linux", "Windows"):
            with self.subTest(system=system), patch.object(auth_gate.platform, "system", return_value=system):
                binary = self.make_component()
                with patch.object(auth_gate.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
                    auth_gate.require_auth()
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0][0], str(binary))

    def test_hash_mismatch_stops_before_any_preparation(self):
        self.binary.write_text("Changed after hashing")
        with patch.object(auth_gate.subprocess, "run") as run, self.assertRaisesRegex(SystemExit, "校验失败"):
            auth_gate.require_auth()
        run.assert_not_called()
        self.assertEqual(self.binary.stat().st_mode & 0o777, 0o600)

    def test_symlink_component_cannot_modify_its_target(self):
        target = self.root / "outside-component"
        self.binary.rename(target)
        self.binary.symlink_to(target)
        with patch.object(auth_gate.subprocess, "run") as run, self.assertRaisesRegex(SystemExit, "校验失败"):
            auth_gate.require_auth()
        run.assert_not_called()
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_preparation_failures_stop_before_auth_with_safe_reason(self):
        failures = (
            FileNotFoundError("sensitive-helper-detail"),
            subprocess.CalledProcessError(1, ["xattr"], stderr="sensitive-helper-detail"),
            subprocess.TimeoutExpired(["xattr"], 10, stderr="sensitive-helper-detail"),
        )
        for failed_step in ("list", "delete"):
            for failure in failures:
                with self.subTest(step=failed_step, failure=type(failure).__name__):
                    effects = [failure] if failed_step == "list" else [
                        subprocess.CompletedProcess([], 0, "com.apple.quarantine\n", ""), failure,
                    ]
                    with patch.object(auth_gate.subprocess, "run", side_effect=effects) as run, \
                            self.assertRaisesRegex(SystemExit, "鉴权组件启动准备失败") as raised:
                        auth_gate.require_auth()
                    self.assertNotIn("sensitive-helper-detail", str(raised.exception))
                    self.assertTrue(all(call.args[0][0] == "/usr/bin/xattr" for call in run.call_args_list))

    def test_chmod_failure_stops_before_spawning(self):
        with patch.object(Path, "chmod", side_effect=PermissionError("private-detail")), \
                patch.object(auth_gate.subprocess, "run") as run, \
                self.assertRaisesRegex(SystemExit, "鉴权组件启动准备失败"):
            auth_gate.require_auth()
        run.assert_not_called()

    def test_first_gate_and_preflight_recheck_keep_safe_permission_reason(self):
        import runtime_v24
        task_dir = self.root / "task"
        task_dir.mkdir()
        common.atomic_write_json(task_dir / "task.json", {
            "schema_version": "2.4-free", "task_id": "OFFLINE-AUTH", "state": "pending"})
        executions = []

        def run(command, **kwargs):
            self.assertEqual(kwargs["encoding"], "utf-8")
            if command[0] == "/usr/bin/xattr":
                return subprocess.CompletedProcess(command, 0, "", "")
            self.assertEqual(kwargs["timeout"], 20)
            executions.append(command)
            if len(executions) == 1:
                return subprocess.CompletedProcess(command, 0, '{"ok":true}', "")
            return subprocess.CompletedProcess(command, 1, "", '{"ok":false,"reason":"permission_missing"}')

        with patch.object(auth_gate.subprocess, "run", side_effect=run), \
                patch.object(runtime_v24, "assert_active_free_policy"), \
                patch("preflight.credential_storage_checkpoint", return_value={}):
            auth_gate.require_auth()
            with self.assertRaisesRegex(SystemExit, "缺少本 Skill 权限"):
                runtime_v24.preflight_credentials(task_dir)
        self.assertEqual(len(executions), 2)
        task = common.load_json(task_dir / "task.json")
        self.assertEqual(task["state"], "incomplete")
        self.assertIn("AUTH_FAILED", json.dumps(task))
        self.assertIn("缺少本 Skill 权限", json.dumps(task, ensure_ascii=False))
        self.assertNotIn("synthetic-environment-secret", json.dumps(task))

    def test_safe_reasons_and_unknown_errors_do_not_leak(self):
        for reason in ("unknown_skill", "skill_disabled", "permission_disabled", "permission_missing"):
            with self.subTest(reason=reason):
                self.assertEqual(auth_gate.result_reason(json.dumps({"reason": reason})), reason)
                with self.assertRaises(SystemExit) as raised:
                    auth_gate.stop(reason)
                self.assertEqual(auth_gate.safe_failure_message(raised.exception), str(raised.exception))
        self.assertEqual(auth_gate.safe_failure_message(SystemExit("private-token-body")), auth_gate.SAFE_FAILURE)
        self.assertEqual(auth_gate.result_reason('{"reason":"private-token-body"}'), "auth_failed")

    def test_legacy_preflight_preserves_only_allowlisted_auth_messages(self):
        import preflight
        task_dir = self.root / "legacy-task"
        task_dir.mkdir()
        safe = auth_gate.SAFE_FAILURE + "\n原因：" + auth_gate.SAFE_REASONS["permission_disabled"]
        for incoming, expected in ((safe, safe), ("private-response-body", auth_gate.SAFE_FAILURE)):
            common.atomic_write_json(task_dir / "task.json", {
                "schema_version": "2.3-free", "task_id": "OFFLINE-AUTH-LEGACY", "state": "pending"})
            with patch.object(preflight, "assert_active_free_policy"), \
                    patch.object(preflight, "is_active_schema", return_value=True), \
                    patch.object(preflight, "credential_storage_checkpoint", return_value={}), \
                    patch.object(preflight, "require_auth", side_effect=SystemExit(incoming)), \
                    self.assertRaises(SystemExit) as raised:
                preflight.phase_credentials(task_dir)
            self.assertEqual(str(raised.exception), expected)
            task = common.load_json(task_dir / "task.json")
            self.assertEqual(task["errors"][-1]["code"], "AUTH_FAILED")
            self.assertEqual(task["errors"][-1]["detail"], expected)
            self.assertNotIn("private-response-body", json.dumps(task))

    def test_component_timeout_keeps_original_service_reason(self):
        def run(command, **kwargs):
            if command[0] == "/usr/bin/xattr":
                return subprocess.CompletedProcess(command, 0, "", "")
            raise subprocess.TimeoutExpired(command, 20, output="private-token-body")
        with patch.object(auth_gate.subprocess, "run", side_effect=run), \
                self.assertRaisesRegex(SystemExit, "鉴权服务暂时不可用") as raised:
            auth_gate.require_auth()
        self.assertNotIn("private-token-body", str(raised.exception))

    @unittest.skipUnless(sys.platform == "darwin", "Native macOS extended attributes")
    def test_native_mac_removal_is_idempotent_and_preserves_other_files_and_attributes(self):
        real_run = subprocess.run
        sibling = self.root / "unselected-component"
        sibling.write_text("Do not prepare this other component.")
        environment = offline_environment()

        def xattr(*arguments):
            return real_run(["/usr/bin/xattr", *map(str, arguments)], check=True, capture_output=True,
                            text=True, timeout=10, env=environment)

        for path in (self.binary, sibling):
            xattr("-w", "com.apple.quarantine", "0081;00000000;OfflineAuthTest;", path)
        xattr("-w", "com.laochen.auth-test", "preserve-me", self.binary)
        digest = common.sha256_file(self.binary)

        def run(command, **kwargs):
            if command[0] == "/usr/bin/xattr":
                return real_run(command, **kwargs)
            self.assertEqual(command[0], str(self.binary))
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(auth_gate.subprocess, "run", side_effect=run) as mocked:
            auth_gate.require_auth()
            auth_gate.require_auth()
        deletions = [call for call in mocked.call_args_list if "-d" in call.args[0]]
        self.assertEqual(len(deletions), 1)
        self.assertNotIn("com.apple.quarantine", xattr(self.binary).stdout.splitlines())
        self.assertIn("com.apple.quarantine", xattr(sibling).stdout.splitlines())
        self.assertEqual(xattr("-p", "com.laochen.auth-test", self.binary).stdout.strip(), "preserve-me")
        self.assertEqual(common.sha256_file(self.binary), digest)


if __name__ == "__main__":
    unittest.main()
