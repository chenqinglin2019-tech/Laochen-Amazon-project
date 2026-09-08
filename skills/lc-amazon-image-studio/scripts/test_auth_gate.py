#!/usr/bin/env python3
"""Offline auth-launch regression tests; all configs and mutations are temporary."""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("auth_gate.py")
SPEC = importlib.util.spec_from_file_location("studio_auth_gate_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
SECRET = "synthetic-token-must-never-be-printed"
MAC_NAME = "lc-auth-check-darwin-arm64"
IS_MAC = platform.system() == "Darwin"
NATIVE_NAME = (
    MAC_NAME if platform.machine().lower() in {"arm64", "aarch64"}
    else "lc-auth-check-darwin-amd64"
)


def native_xattr(*args):
    """Use macOS's bundled tool; its system Python may omit os.*xattr APIs."""
    return subprocess.run(["/usr/bin/xattr", *(str(arg) for arg in args)],
                          text=True, capture_output=True, check=True, timeout=10,
                          env={"PATH": "/usr/bin:/bin"}).stdout


class TemporarySkill(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-auth-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tools/bin").mkdir(parents=True)
        (self.root / "references").mkdir()
        self.binary = self.root / "tools/bin" / MAC_NAME
        self.binary.write_bytes(b"synthetic checker fixture\n")
        self.binary.chmod(0o600)
        self.write_manifest()
        self.root_patch = mock.patch.object(gate, "skill_root", return_value=self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def write_manifest(self, binary=None, digest=None):
        binary = binary or self.binary
        digest = digest or hashlib.sha256(binary.read_bytes()).hexdigest()
        (self.root / "references/auth-binaries.json").write_text(json.dumps({
            "schema": "LC-AUTH-BINARIES/1.0", "sha256": {binary.name: digest},
        }), encoding="utf-8")

    def mac(self):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(gate.platform, "system", return_value="Darwin"))
        stack.enter_context(mock.patch.object(gate.platform, "machine", return_value="arm64"))
        return stack


class RoutingAndIntegrityTests(TemporarySkill):
    def test_platform_routes_and_architecture_aliases(self):
        for system, machine, filename in [
            ("Darwin", "arm64", MAC_NAME),
            ("Darwin", "aarch64", MAC_NAME),
            ("Darwin", "x86_64", "lc-auth-check-darwin-amd64"),
            ("Darwin", "AMD64", "lc-auth-check-darwin-amd64"),
            ("Linux", "x86_64", "lc-auth-check-linux-amd64"),
            ("Windows", "AMD64", "lc-auth-check-windows-amd64.exe"),
        ]:
            with self.subTest(system=system, machine=machine), \
                 mock.patch.object(gate.platform, "system", return_value=system), \
                 mock.patch.object(gate.platform, "machine", return_value=machine):
                self.assertEqual(gate.auth_binary(), self.root / "tools/bin" / filename)

    def test_unsupported_platform_stops_before_mutation(self):
        for system, machine in [("Linux", "arm64"), ("Windows", "arm64"), ("FreeBSD", "amd64")]:
            with self.subTest(system=system), \
                 mock.patch.object(gate.platform, "system", return_value=system), \
                 mock.patch.object(gate.platform, "machine", return_value=machine), \
                 mock.patch.object(Path, "chmod") as chmod, \
                 mock.patch.object(gate.subprocess, "run") as run:
                with self.assertRaises(SystemExit):
                    gate.require_auth()
                chmod.assert_not_called()
                run.assert_not_called()

    def test_wrong_hash_never_changes_permissions_or_attributes(self):
        self.write_manifest(digest="0" * 64)
        with self.mac(), mock.patch.object(Path, "chmod") as chmod, \
             mock.patch.object(gate.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as error:
                gate.require_auth()
            self.assertIn("校验失败", str(error.exception))
            chmod.assert_not_called()
            run.assert_not_called()

    def test_symlink_even_to_matching_contents_is_not_prepared(self):
        target = self.root / "outside-checker"
        self.binary.rename(target)
        self.binary.symlink_to(target)
        with self.mac(), mock.patch.object(Path, "chmod") as chmod, \
             mock.patch.object(gate.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                gate.require_auth()
            chmod.assert_not_called()
            run.assert_not_called()
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_missing_or_invalid_manifest_stops_before_mutation(self):
        path = self.root / "references/auth-binaries.json"
        for content in [None, "broken json", "{}", "null", '{"sha256":{}}']:
            with self.subTest(content=content):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content, encoding="utf-8")
                with self.mac(), mock.patch.object(Path, "chmod") as chmod, \
                     mock.patch.object(gate.subprocess, "run") as run:
                    with self.assertRaises(SystemExit):
                        gate.require_auth()
                    chmod.assert_not_called()
                    run.assert_not_called()


class StartupTests(TemporarySkill):
    def test_mac_order_hash_then_permission_then_selected_quarantine_then_auth(self):
        events = []
        original_verify = gate.verify_binary

        def verify(binary):
            original_verify(binary)
            events.append("verified")

        def run(args, **kwargs):
            self.assertEqual(events[0], "verified")
            self.assertEqual(self.binary.stat().st_mode & 0o111, 0o111)
            if args == ["/usr/bin/xattr", str(self.binary)]:
                events.append("listed")
                return subprocess.CompletedProcess(args, 0, "com.apple.quarantine\nother.attribute\n", "")
            if args == ["/usr/bin/xattr", "-d", "com.apple.quarantine", str(self.binary)]:
                events.append("removed")
                return subprocess.CompletedProcess(args, 0, "", "")
            self.assertEqual(args, [str(self.binary), "--config", str(self.root / "config.json")])
            self.assertEqual(kwargs["cwd"], self.root)
            self.assertTrue(Path(args[2]).is_absolute())
            events.append("authenticated")
            return subprocess.CompletedProcess(args, 0, '{"message":"auth_passed","ok":true}\n', "")

        with self.mac(), mock.patch.object(gate, "verify_binary", side_effect=verify), \
             mock.patch.object(gate.subprocess, "run", side_effect=run):
            gate.require_auth()
        self.assertEqual(events, ["verified", "listed", "removed", "authenticated"])

    def test_no_quarantine_never_runs_delete_and_can_repeat(self):
        with self.mac(), mock.patch.object(gate.subprocess, "run", return_value=
                subprocess.CompletedProcess([], 0, "other.attribute\n", "")) as run:
            gate.prepare_binary(self.binary)
            gate.prepare_binary(self.binary)
        self.assertEqual(run.call_args_list, [
            mock.call(["/usr/bin/xattr", str(self.binary)], text=True, capture_output=True,
                      check=True, timeout=10),
            mock.call(["/usr/bin/xattr", str(self.binary)], text=True, capture_output=True,
                      check=True, timeout=10),
        ])

    def test_other_platforms_do_not_call_xattr(self):
        for system in ["Linux", "Windows"]:
            with self.subTest(system=system), \
                 mock.patch.object(gate.platform, "system", return_value=system), \
                 mock.patch.object(gate.subprocess, "run") as run:
                gate.prepare_binary(self.binary)
                run.assert_not_called()

    def test_chmod_failure_blocks_account_call(self):
        with self.mac(), mock.patch.object(Path, "chmod", side_effect=PermissionError(SECRET)), \
             mock.patch.object(gate.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as error:
                gate.require_auth()
            self.assertIn("启动准备失败", str(error.exception))
            self.assertNotIn(SECRET, str(error.exception))
            run.assert_not_called()

    def test_attribute_list_or_delete_error_and_timeout_block_account_call(self):
        for phase in ["list", "delete"]:
            for exception in [
                subprocess.CalledProcessError(1, SECRET, output=SECRET, stderr=SECRET),
                subprocess.TimeoutExpired(SECRET, 10, output=SECRET, stderr=SECRET),
                OSError(SECRET),
            ]:
                with self.subTest(phase=phase, exception=type(exception).__name__):
                    effects = [exception] if phase == "list" else [
                        subprocess.CompletedProcess([], 0, "com.apple.quarantine\n", ""), exception,
                    ]
                    with self.mac(), mock.patch.object(gate.subprocess, "run", side_effect=effects) as run:
                        with self.assertRaises(SystemExit) as error:
                            gate.require_auth()
                    self.assertIn("启动准备失败", str(error.exception))
                    self.assertNotIn(SECRET, str(error.exception))
                    self.assertTrue(all(call.args[0][0] == "/usr/bin/xattr" for call in run.call_args_list))


class SafeResultTests(TemporarySkill):
    def invoke(self, result=None, exception=None):
        with mock.patch.object(gate, "auth_binary", return_value=self.binary), \
             mock.patch.object(gate, "verify_binary"), mock.patch.object(gate, "prepare_binary"), \
             mock.patch.object(gate.subprocess, "run", return_value=result, side_effect=exception):
            gate.require_auth()

    def test_payload_ignores_non_object_or_non_boolean_results(self):
        for stream in ["bad json", "[]", '"text"', '{"ok":1}', '{"ok":"true"}', "null"]:
            with self.subTest(stream=stream):
                self.assertEqual(gate.result_payload(stream), {})
        self.assertEqual(gate.result_payload("log\n", '{"ok":false,"reason":"missing_api_key"}\n'),
                         {"ok": False, "reason": "missing_api_key"})

    def test_rejected_reason_explains_token_and_balance_without_echoing_data(self):
        raw = json.dumps({"ok": False, "reason": "auth_rejected", "token": SECRET})
        with self.assertRaises(SystemExit) as error:
            self.invoke(subprocess.CompletedProcess([], 4, SECRET, raw))
        self.assertIn("Token", str(error.exception))
        self.assertIn("余额", str(error.exception))
        self.assertNotIn(SECRET, str(error.exception))

    def test_disabled_reason_refers_to_account_state(self):
        with self.assertRaises(SystemExit) as error:
            self.invoke(subprocess.CompletedProcess([], 4, "", '{"ok":false,"reason":"user_not_enabled"}'))
        self.assertIn("账户状态", str(error.exception))

    def test_unknown_reason_and_process_diagnostics_are_never_echoed(self):
        for returncode, stdout, stderr in [
            (3, SECRET, json.dumps({"ok": False, "reason": SECRET})),
            (3, SECRET, SECRET),
            (0, SECRET, SECRET),
            (0, '{"ok":false,"reason":"missing_api_key"}', SECRET),
            (0, '{"ok":true}', SECRET),
            (3, '{"ok":true}', SECRET),
            (3, "", json.dumps({"ok": False, "reason": [SECRET]})),
        ]:
            with self.subTest(returncode=returncode, stdout=stdout):
                with self.assertRaises(SystemExit) as error:
                    self.invoke(subprocess.CompletedProcess([], returncode, stdout, stderr))
                self.assertIn(gate.SAFE_FAILURE, str(error.exception))
                self.assertNotIn(SECRET, str(error.exception))

    def test_account_timeout_and_launch_errors_are_safe(self):
        for exception in [subprocess.TimeoutExpired(SECRET, 20, output=SECRET), OSError(SECRET),
                          UnicodeDecodeError("utf-8", b"\xff", 0, 1, SECRET)]:
            with self.subTest(exception=type(exception).__name__):
                with self.assertRaises(SystemExit) as error:
                    self.invoke(exception=exception)
                self.assertNotIn(SECRET, str(error.exception))
                self.assertIn(gate.SAFE_FAILURE, str(error.exception))

    def test_success_main_emits_only_one_safe_json_object(self):
        output = io.StringIO()
        with mock.patch.object(gate, "require_auth"), contextlib.redirect_stdout(output):
            gate.main()
        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "message": "auth_passed"})
        self.assertEqual(len(output.getvalue().splitlines()), 1)


@unittest.skipUnless(IS_MAC, "Native quarantine behavior requires macOS")
class NativeMacTests(TemporarySkill):
    def test_only_selected_quarantine_removed_other_file_and_attributes_unchanged(self):
        other = self.root / "tools/bin/another-checker"
        other.write_bytes(b"another synthetic file")
        other.chmod(0o600)
        quarantine = "0081;00000000;StudioAuthOfflineTest;"
        custom = "com.laochen.studio-auth-regression"
        native_xattr("-w", "com.apple.quarantine", quarantine, self.binary)
        native_xattr("-w", custom, "preserve-me", self.binary)
        native_xattr("-w", "com.apple.quarantine", quarantine, other)
        gate.verify_binary(self.binary)
        gate.prepare_binary(self.binary)
        gate.prepare_binary(self.binary)
        self.assertNotIn("com.apple.quarantine", native_xattr(self.binary).splitlines())
        self.assertEqual(native_xattr("-p", custom, self.binary).strip(), "preserve-me")
        self.assertEqual(native_xattr("-p", "com.apple.quarantine", other).strip(), quarantine)
        self.assertEqual(other.stat().st_mode & 0o777, 0o600)

    def test_real_checker_loopback_from_other_cwd_success_and_rejection(self):
        source_binary = MODULE_PATH.parent.parent / "tools/bin" / NATIVE_NAME
        if not source_binary.is_file():
            self.skipTest("Current platform's bundled checker is unavailable")
        native = self.root / "tools/bin" / NATIVE_NAME
        shutil.copyfile(source_binary, native)
        native.chmod(0o600)
        self.write_manifest(native)
        (self.root / "scripts").mkdir()
        script = self.root / "scripts/auth_gate.py"
        shutil.copyfile(MODULE_PATH, script)
        elsewhere = self.root / "unrelated-working-directory"
        elsewhere.mkdir()
        state = {"requests": [], "balance": 1}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                state["requests"].append({"path": self.path, "body": data})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"user": {"status": "enabled", "balance": state["balance"]}}).encode())

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        (self.root / "config.json").write_text(json.dumps({
            "backend_url": f"http://127.0.0.1:{server.server_port}", "backend_token": SECRET,
        }), encoding="utf-8")
        native_xattr("-w", "com.apple.quarantine", "0081;00000000;StudioAuthOfflineTest;", native)
        # A minimal environment prevents real tokens or proxy settings entering the checker.
        env = {"PATH": "/usr/bin:/bin", "LAOCHEN_BACKEND_TOKEN": "synthetic-env-fallback"}
        success = subprocess.run([sys.executable, str(script)], cwd=elsewhere, env=env,
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(json.loads(success.stdout), {"ok": True, "message": "auth_passed"})
        self.assertEqual(success.stderr, "")
        self.assertNotIn("com.apple.quarantine", native_xattr(native).splitlines())
        self.assertEqual(state["requests"], [{"path": "/public/account", "body": {
            "api_key": SECRET, "days": 1, "limit": 1, "page": 1, "page_size": 1,
        }}])
        state["balance"] = 0
        rejected = subprocess.run([sys.executable, str(script)], cwd=elsewhere, env=env,
                                  text=True, capture_output=True, timeout=10)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(rejected.stdout, "")
        self.assertIn("Token", rejected.stderr)
        self.assertIn("余额", rejected.stderr)
        self.assertNotIn(SECRET, success.stdout + success.stderr + rejected.stdout + rejected.stderr)


if __name__ == "__main__":
    unittest.main()
