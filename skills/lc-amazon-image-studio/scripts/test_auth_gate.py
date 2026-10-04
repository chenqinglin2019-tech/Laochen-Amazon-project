"""Auth preparation regressions. Temporary files and mocked account calls only."""

import contextlib
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import auth_gate as gate
import diagnose_auth as diagnosis

SECRET = "synthetic-value-never-print"


class AuthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binary = self.root / "tools/bin/lc-auth-check-darwin-arm64"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"synthetic checker")
        self.binary.chmod(0o600)
        (self.root / "references").mkdir()
        (self.root / "references/auth-binaries.json").write_text(json.dumps({
            "schema": "LC-AUTH-BINARIES/1.0",
            "sha256": {self.binary.name: hashlib.sha256(self.binary.read_bytes()).hexdigest()},
        }))
        patch = mock.patch.object(gate, "skill_root", return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def mac(self):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(gate.platform, "system", return_value="Darwin"))
        stack.enter_context(mock.patch.object(gate.platform, "machine", return_value="arm64"))
        return stack

    def safe_failure(self, operation, expected):
        with self.assertRaises(SystemExit) as error:
            operation()
        message = str(error.exception)
        self.assertEqual(len(message.splitlines()), 2)
        self.assertTrue(message.startswith(gate.SAFE_FAILURE))
        self.assertIn(expected, message)
        self.assertNotIn(SECRET, message)

    def test_executable_in_read_only_sandbox_skips_chmod(self):
        with self.mac(), mock.patch.object(gate.os, "access", return_value=True), \
             mock.patch.object(Path, "chmod", side_effect=PermissionError(SECRET)) as chmod, \
             mock.patch.object(gate.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            gate.prepare_binary(self.binary)
        chmod.assert_not_called()
        self.assertEqual(run.call_count, 1)

    def test_missing_permission_fails_before_xattr_or_account(self):
        with self.mac(), mock.patch.object(gate.os, "access", return_value=False), \
             mock.patch.object(Path, "chmod", side_effect=PermissionError(SECRET)), \
             mock.patch.object(gate.subprocess, "run") as run:
            self.safe_failure(gate.require_auth, "缺少执行权限")
        run.assert_not_called()

    def test_missing_permission_is_repaired_then_rechecked(self):
        with mock.patch.object(gate.platform, "system", return_value="Linux"), \
             mock.patch.object(gate.os, "access", side_effect=[False, True]), \
             mock.patch.object(gate.subprocess, "run") as run:
            gate.prepare_binary(self.binary)
        self.assertEqual(self.binary.stat().st_mode & 0o111, 0o111)
        run.assert_not_called()

    def test_chmod_cannot_override_host_execute_restriction(self):
        with mock.patch.object(gate.platform, "system", return_value="Linux"), \
             mock.patch.object(gate.os, "access", return_value=False):
            self.safe_failure(lambda: gate.prepare_binary(self.binary), "缺少执行权限")

    def test_windows_does_not_mutate_posix_modes_or_call_xattr(self):
        with mock.patch.object(gate.platform, "system", return_value="Windows"), \
             mock.patch.object(Path, "chmod", side_effect=PermissionError(SECRET)) as chmod, \
             mock.patch.object(gate.subprocess, "run") as run:
            gate.prepare_binary(self.binary)
        chmod.assert_not_called()
        run.assert_not_called()

    def test_only_selected_quarantine_is_removed(self):
        responses = [subprocess.CompletedProcess([], 0, "other.attribute\ncom.apple.quarantine\n", ""),
                     subprocess.CompletedProcess([], 0, "", "")]
        with self.mac(), mock.patch.object(gate.subprocess, "run", side_effect=responses) as run:
            gate.prepare_binary(self.binary)
        self.assertEqual(run.call_args_list[1].args[0],
                         ["/usr/bin/xattr", "-d", "com.apple.quarantine", str(self.binary)])

    def test_attribute_inspection_failure_is_safe_and_blocks_account(self):
        for exception in [PermissionError(SECRET), subprocess.TimeoutExpired(SECRET, 10),
                          subprocess.CalledProcessError(1, SECRET, stderr=SECRET)]:
            with self.subTest(exception=type(exception).__name__), self.mac(), \
                 mock.patch.object(gate.subprocess, "run", side_effect=exception) as run:
                self.safe_failure(gate.require_auth, "无法检查 macOS")
                self.assertEqual(run.call_count, 1)

    def test_quarantine_failure_is_safe_and_blocks_account(self):
        responses = [subprocess.CompletedProcess([], 0, "com.apple.quarantine\n", ""),
                     subprocess.CalledProcessError(1, SECRET, stderr=SECRET)]
        with self.mac(), mock.patch.object(gate.subprocess, "run", side_effect=responses) as run:
            self.safe_failure(gate.require_auth, "无法移除")
        self.assertEqual(run.call_count, 2)

    def test_invalid_or_symlink_component_never_mutates_or_launches(self):
        for invalid in ["hash", "symlink"]:
            with self.subTest(invalid=invalid):
                if invalid == "hash":
                    self.binary.write_bytes(b"wrong content")
                else:
                    target = self.root / "outside"
                    self.binary.rename(target)
                    self.binary.symlink_to(target)
                with self.mac(), mock.patch.object(Path, "chmod") as chmod, \
                     mock.patch.object(gate.subprocess, "run") as run:
                    self.safe_failure(gate.require_auth, "校验失败")
                chmod.assert_not_called()
                run.assert_not_called()

    def test_platform_routing(self):
        for system, machine, suffix in [("Darwin", "arm64", "darwin-arm64"),
                                        ("Darwin", "x86_64", "darwin-amd64"),
                                        ("Linux", "x86_64", "linux-amd64"),
                                        ("Windows", "AMD64", "windows-amd64.exe")]:
            with self.subTest(system=system), mock.patch.object(gate.platform, "system", return_value=system), \
                 mock.patch.object(gate.platform, "machine", return_value=machine):
                self.assertEqual(gate.auth_binary().name, "lc-auth-check-" + suffix)
        with mock.patch.object(gate.platform, "system", return_value="Linux"), \
             mock.patch.object(gate.platform, "machine", return_value="arm64"):
            self.safe_failure(gate.auth_binary, "没有可用")

    def test_failed_auth_never_writes_pass_or_leaks_logs(self):
        cases = [(subprocess.CompletedProcess([], 3, SECRET, '{"ok":false,"reason":"auth_service_unavailable"}'),
                  None, "连接或服务不可用"),
                 (None, subprocess.TimeoutExpired(SECRET, 20, stderr=SECRET), "请求超时"),
                 (subprocess.CompletedProcess([], 3, SECRET, '{"ok":false,"reason":"auth_rejected"}'),
                  None, "Token"),
                 (subprocess.CompletedProcess([], 0, SECRET, SECRET), None, "返回异常")]
        for result, exception, expected in cases:
            with self.subTest(expected=expected), mock.patch.object(gate, "auth_binary", return_value=self.binary), \
                 mock.patch.object(gate, "verify_binary"), mock.patch.object(gate, "prepare_binary"), \
                 mock.patch.object(gate.subprocess, "run", return_value=result, side_effect=exception), \
                 mock.patch("lc_auth_pass.write_pass") as write_pass:
                self.safe_failure(gate.require_auth, expected)
                write_pass.assert_not_called()

    def test_success_protocol_writes_pass_and_preserves_config_argument(self):
        with mock.patch.object(gate, "auth_binary", return_value=self.binary), \
             mock.patch.object(gate, "verify_binary"), mock.patch.object(gate, "prepare_binary"), \
             mock.patch.object(gate.subprocess, "run", return_value=subprocess.CompletedProcess(
                 [], 0, '{"ok":true,"message":"auth_passed"}', "")) as run, \
             mock.patch("lc_auth_pass.write_pass") as write_pass:
            gate.require_auth()
        self.assertEqual(run.call_args.args[0], [str(self.binary), "--config", str(self.root / "config.json")])
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        write_pass.assert_called_once_with(self.root)

    def test_offline_diagnosis_never_reads_config_or_mutates_installation(self):
        (self.root / "config.json").write_text(SECRET)
        self.binary.chmod(0o755)
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            self.assertNotEqual(path.name, "config.json")
            return original(path, *args, **kwargs)

        with self.mac(), mock.patch.object(Path, "read_text", read_text), \
             mock.patch.object(Path, "chmod") as chmod, \
             mock.patch.object(gate.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run, \
             mock.patch("lc_auth_pass.write_pass") as write_pass:
            report = diagnosis.inspect_installation()
        self.assertTrue(report["installation_ok"])
        self.assertFalse(report["network_tested"])
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/xattr")
        chmod.assert_not_called()
        write_pass.assert_not_called()

    @unittest.skipUnless(platform.system() == "Darwin" and Path("/usr/bin/sandbox-exec").exists(),
                         "Native macOS sandbox regression")
    def test_actual_read_only_sandbox_can_prepare_executable(self):
        self.binary.chmod(0o755)
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import auth_gate; '
                'from pathlib import Path; auth_gate.prepare_binary(Path(sys.argv[2])); print("prepare_ok")')
        result = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny file-write*)",
                                 sys.executable, "-c", code, str(Path(gate.__file__).parent), str(self.binary)],
                                text=True, capture_output=True, timeout=15,
                                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "prepare_ok")

    @unittest.skipUnless(platform.system() == "Darwin", "Native macOS installation diagnosis")
    def test_diagnosis_cli_creates_no_bytecode_or_files(self):
        self.binary.chmod(0o755)
        scripts = self.root / "scripts"
        scripts.mkdir()
        for module in [gate, diagnosis]:
            shutil.copyfile(module.__file__, scripts / Path(module.__file__).name)
        (self.root / "config.json").write_text(SECRET)
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(scripts / "diagnose_auth.py"), "--json"],
                                text=True, capture_output=True, timeout=15,
                                env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["installation_ok"])
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        after = {str(p.relative_to(self.root)): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
