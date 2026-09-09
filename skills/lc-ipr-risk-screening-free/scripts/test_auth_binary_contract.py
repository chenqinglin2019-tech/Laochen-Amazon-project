"""Frozen package acceptance using synthetic tokens and loopback-only sandboxing."""
from __future__ import annotations

import ast
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "scripts/fixtures/auth-contract-20260811.json").read_text(encoding="utf-8"))


def function_ast_sha256(source: str, name: str) -> str:
    definitions = [node for node in ast.parse(source).body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(definitions) != 1:
        raise ValueError("AUTH_FROZEN_FUNCTION_MISSING_OR_DUPLICATED")
    canonical = ast.dump(definitions[0], annotate_fields=True, include_attributes=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuthBinaryContractTests(unittest.TestCase):
    def test_wrapper_and_backend_functions_match_explicit_code_freeze(self):
        freeze = BASELINE["source_freeze"]
        for name, expected in freeze["file_sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected,
                                 "Auth changes require an explicit baseline review")
        for name, functions in freeze["function_ast_sha256"].items():
            source = (ROOT / name).read_text(encoding="utf-8")
            for function, expected in functions.items():
                with self.subTest(file=name, function=function):
                    self.assertEqual(function_ast_sha256(source, function), expected,
                                     "Auth/config semantics changed; do not refresh this baseline incidentally")

    def test_function_freeze_detects_backend_change_without_locking_unrelated_helpers(self):
        source = (ROOT / "scripts/common.py").read_text(encoding="utf-8")
        expected = BASELINE["source_freeze"]["function_ast_sha256"]["scripts/common.py"]["_backend_config"]
        self.assertEqual(function_ast_sha256(source + "\n# An unrelated retrieval comment\n", "_backend_config"), expected)
        changed = source.replace('"config.local.json"', '"incorrect-backend.json"')
        self.assertNotEqual(function_ast_sha256(changed, "_backend_config"), expected)

    def test_all_components_and_runtime_hashes_equal_frozen_package(self):
        runtime = json.loads((ROOT / "references/runtime-config.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["auth"]["timeout_seconds"], BASELINE["timeout_seconds"])
        self.assertEqual(runtime["auth"]["binary_sha256"], BASELINE["binary_sha256"])
        for name, expected in BASELINE["binary_sha256"].items():
            with self.subTest(component=name):
                binary = ROOT / "tools/bin" / name
                self.assertFalse(binary.is_symlink())
                self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), expected)

    @unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists(),
                         "Native test needs macOS loopback-only sandbox; no unrestricted network fallback")
    def test_native_zip_protocol_and_success_failure_matrix(self):
        import platform
        name = "lc-ipr-auth-check-darwin-" + ("arm64" if platform.machine() in {"arm64", "aarch64"} else "amd64")
        binary = ROOT / "tools/bin" / name
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), BASELINE["binary_sha256"][name])
        current = {}
        calls = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                calls.append((self.path, dict(self.headers), body))
                value = current["body"]
                payload = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
                self.send_response(current["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory(prefix="auth-frozen-contract-") as directory:
                root = Path(directory)
                config = root / "synthetic.json"
                config.write_text(json.dumps({"backend_url": f"http://127.0.0.1:{server.server_port}",
                    "backend_token": "SYNTHETIC-NOT-REAL-TOKEN"}), encoding="utf-8")
                config.chmod(0o600)
                profile = ('(version 1)(allow default)(deny network*)'
                    f'(allow network-outbound (remote ip "localhost:{server.server_port}"))'
                    '(deny file-read* (subpath "/Users"))'
                    f'(allow file-read* (literal {json.dumps(str(binary), ensure_ascii=False)}))'
                    '(deny file-write*)'
                    f'(allow file-write* (subpath {json.dumps(directory)}))')
                cases = [
                    (200, {"allowed": True, "reason": "permission_enabled"}, None),
                    (200, {"allowed": True, "reason": " permission_enabled "}, None),
                    (200, {"allowed": True}, "invalid_response"),
                    (200, {"allowed": True, "reason": "PERMISSION_ENABLED"}, "invalid_response"),
                    (200, {"user": {"status": "enabled", "balance": 10}}, "invalid_response"),
                    (200, {"allowed": False, "reason": "permission_enabled"}, "invalid_response"),
                    (200, {"allowed": False, "reason": "synthetic-unknown"}, "invalid_response"),
                    (200, b"not-json", "invalid_response"),
                    (201, {"allowed": True, "reason": "permission_enabled"}, "service_unavailable"),
                    (401, {}, "invalid_token"), (403, {}, "invalid_token"),
                    (429, {}, "rate_limited"), (503, {}, "service_unavailable"),
                ]
                cases += [(200, {"allowed": False, "reason": reason}, reason) for reason in (
                    "invalid_token", "user_disabled", "insufficient_balance", "unknown_skill",
                    "skill_disabled", "permission_disabled", "permission_missing")]
                for status, body, reason in cases:
                    with self.subTest(status=status, body=body):
                        current.update(status=status, body=body)
                        before = len(calls)
                        process = subprocess.run(["/usr/bin/sandbox-exec", "-p", profile,
                            str(binary), "--config", str(config)], cwd=directory,
                            env={"HOME": directory, "TMPDIR": directory, "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True, encoding="utf-8", timeout=5, check=False)
                        self.assertEqual(len(calls) - before, 1, "No automatic auth retry")
                        path, headers, request = calls[-1]
                        self.assertEqual(path, BASELINE["path"])
                        self.assertNotIn("Authorization", headers)
                        self.assertEqual(request, {"api_key": "SYNTHETIC-NOT-REAL-TOKEN",
                                                  "skill_id": BASELINE["skill_id"]})
                        if reason is None:
                            self.assertEqual(process.returncode, 0, process.stderr)
                            self.assertEqual(json.loads(process.stdout), {"ok": True, "message": "auth_passed"})
                        else:
                            self.assertNotEqual(process.returncode, 0)
                            self.assertEqual(json.loads(process.stderr), {"ok": False, "reason": reason})
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
