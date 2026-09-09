"""Offline launcher regressions: fake credentials and fake/mocked subprocesses."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("backend_cli_test", ROOT / "scripts/backend_cli.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
CONFIG = {"backend_url": "https://offline.example.invalid/api", "backend_token": 'fake-$(`never-run`)-"雪"/&'}


class BackendLauncherTests(unittest.TestCase):
    def setUp(self):
        quarantine = patch.object(backend, "_clear_quarantine")
        quarantine.start()
        self.addCleanup(quarantine.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="backend test 中文 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.source = self.root / "input.json"
        self.source.write_text('{"title":"Offline product"}', encoding="utf-8")
        self.cli = self.root / "fake-cli"
        self.cli.write_text("fake", encoding="utf-8")
        self.output = self.root / "result.json"

    def invoke(self, command="validate", **kwargs):
        options = dict(site="US", config=self.config, cli=self.cli)
        options.update({"asins": "B000000001,B000000002"} if command == "expand" else
                       {"keywords_file" if command == "qa" else "listing_file": self.source})
        options.update(kwargs)
        return backend.run_cli(command, **options)

    def completed(self, response, code=0):
        def run(args, **kwargs):
            raw = json.dumps(response, ensure_ascii=True)
            if "--output" in args:
                Path(args[args.index("--output") + 1]).write_text(raw, encoding="utf-8")
                raw = "truncated stdout " + CONFIG["backend_token"]
            return subprocess.CompletedProcess(args, code, raw, CONFIG["backend_token"])
        return run

    def assert_safe(self, data):
        text = json.dumps(data, ensure_ascii=False)
        for secret in CONFIG.values():
            self.assertNotIn(secret, text)
            self.assertNotIn(quote(secret, safe=""), text)

    def test_missing_and_invalid_config_never_starts_cli_or_uses_ambient_token(self):
        invalid = [{}, [], None, {**CONFIG, "backend_token": None}, {**CONFIG, "backend_token": " "},
                   {**CONFIG, "backend_token": 17}, {**CONFIG, "backend_url": ""},
                   {**CONFIG, "backend_token": "leading "}, {**CONFIG, "backend_token": "bad\nvalue"},
                   {**CONFIG, "backend_url": "file:///tmp/x"}, {**CONFIG, "backend_url": "https://host:bad"},
                   {**CONFIG, "backend_url": "https://user:password@host"}]
        with patch.object(backend.subprocess, "run") as runner, patch.object(backend, "prepare_cli") as prepare, \
                patch.dict(os.environ, dict(zip(backend.ENV_KEYS, CONFIG.values()))):
            for data in invalid:
                with self.subTest(data_type=type(data).__name__):
                    self.config.write_text(json.dumps(data), encoding="utf-8")
                    result = self.invoke()
                    self.assertIsNone(result["exit_code"])
                    self.assertTrue(result["error_code"].startswith("config_"))
                    self.assert_safe(result)
            self.config.write_text('{"broken":', encoding="utf-8")
            self.assertEqual(self.invoke()["error_code"], "config_unreadable")
            self.config.unlink()
            self.assertEqual(self.invoke()["error_code"], "config_unreadable")
            runner.assert_not_called()
            prepare.assert_not_called()

    def test_config_is_injected_only_into_child_environment(self):
        with patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": "stale-token", "LAOCHEN_BACKEND_URL": "stale-url"}), \
                patch.object(backend.subprocess, "run", side_effect=self.completed({"ok": True, "errors": []})) as runner:
            result = self.invoke()
            self.assertNotIn("failure_reason", result)
            args, kwargs = runner.call_args
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["env"]["LAOCHEN_BACKEND_TOKEN"], CONFIG["backend_token"])
            self.assertEqual(kwargs["env"]["LAOCHEN_BACKEND_URL"], CONFIG["backend_url"])
            self.assertEqual(os.environ["LAOCHEN_BACKEND_TOKEN"], "stale-token")
            self.assertNotIn(CONFIG["backend_token"], str(args))
            self.assertNotIn(CONFIG["backend_url"], str(args))

    def test_full_expand_and_qa_files_are_redacted_before_publication(self):
        for command in ("expand", "qa"):
            response = {"keywords": ["goose statue"] * 500, "qa_pairs": [], "raw": {"tokens": CONFIG["backend_token"]},
                        "message": list(CONFIG.values()) + [quote(CONFIG["backend_token"], safe=""),
                                                           json.dumps(CONFIG["backend_token"])[1:-1]],
                        CONFIG["backend_token"]: "sensitive key"}
            with self.subTest(command=command), patch.object(backend.subprocess, "run", side_effect=self.completed(response)) as runner:
                result = self.invoke(command, output=self.output)
                self.assertNotIn("failure_reason", result)
                saved = json.loads(self.output.read_text(encoding="utf-8"))
                self.assertEqual(len(saved["keywords"]), 500)
                self.assertEqual(saved, result["response"])
                self.assert_safe(saved)
                raw_path = Path(runner.call_args.args[0][-1])
                self.assertNotEqual(raw_path, self.output)
                self.assertFalse(raw_path.parent.exists())
                self.assertNotIn("truncated stdout", json.dumps(result))
                self.assertIsNone(runner.call_args.kwargs["timeout"])  # Preserve original CLI polling behavior.

    def test_validate_redacts_nested_secrets_and_preserves_business_failure(self):
        response = {"ok": False, "errors": ["Denied: " + CONFIG["backend_token"], {"Authorization": "Bearer another-token"}],
                    "backend_url": CONFIG["backend_url"], "detail": "Bearer unknown-token"}
        with patch.object(backend.subprocess, "run", side_effect=self.completed(response)):
            result = self.invoke(output=self.output)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["error_code"], "backend_rejected")
        self.assertFalse(result["response"]["ok"])
        self.assert_safe(result)
        self.assertNotIn("another-token", json.dumps(result))
        self.assertNotIn("unknown-token", json.dumps(result))
        self.assertFalse(json.loads(self.output.read_text())["ok"])

    def test_failure_conditions_never_report_success(self):
        cases = [("validate", {"ok": True}, 0, "backend_rejected"),
                 ("validate", {"ok": True, "errors": ["bad"]}, 0, "backend_rejected"),
                 ("validate", {"ok": True, "errors": []}, 7, "cli_failed"),
                 ("expand", {"ok": False}, 0, "backend_rejected"),
                 ("expand", {"errors": ["failed ASIN"]}, 0, "backend_rejected"),
                 ("qa", {"status": "failed"}, 0, "backend_rejected")]
        for command, response, code, error in cases:
            with self.subTest(command=command, error=error), patch.object(backend.subprocess, "run", side_effect=self.completed(response, code)):
                result = self.invoke(command)
                self.assertEqual(result["error_code"], error)
                self.assertEqual(result["exit_code"], code)

    def test_missing_full_output_does_not_fall_back_to_stdout_or_replace_old_file(self):
        self.output.write_text('{"old":true}', encoding="utf-8")
        with patch.object(backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"keywords":[]}', "")):
            result = self.invoke("expand", output=self.output)
        self.assertEqual(result["error_code"], "response_invalid")
        self.assertEqual(json.loads(self.output.read_text()), {"old": True})

    def test_malformed_output_and_exceptions_never_echo_raw_logs(self):
        for raw in (CONFIG["backend_token"], '[]', '{"ok":true,"errors":[],"x":NaN}'):
            with patch.object(backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, CONFIG["backend_token"])):
                result = self.invoke()
            self.assertIsNone(result["response"])
            self.assertEqual(result["error_code"], "response_invalid")
            self.assert_safe(result)
        for exception, error in ((subprocess.TimeoutExpired("cli", 1, output=CONFIG["backend_token"]), "cli_timeout"),
                                 (OSError(CONFIG["backend_token"]), "cli_unavailable")):
            with patch.object(backend.subprocess, "run", side_effect=exception) as runner:
                result = self.invoke()
                self.assertEqual(runner.call_count, 1)
                self.assertIsNone(result["exit_code"])
                self.assertEqual(result["error_code"], error)
                self.assert_safe(result)

    def test_invalid_input_output_and_non_us_qa_stop_before_subprocess(self):
        with patch.object(backend.subprocess, "run") as runner:
            for output in (self.config, self.cli, self.source):
                self.assertEqual(self.invoke(output=output)["error_code"], "invalid_output")
            self.assertEqual(self.invoke(listing_file=self.config)["error_code"], "invalid_arguments")
            self.assertEqual(self.invoke(listing_file=self.root / "missing")["error_code"], "input_missing")
            self.assertEqual(self.invoke("qa", site="DE")["error_code"], "qa_us_only")
            for timeout in (0, -1, float("nan"), float("inf"), True):
                self.assertEqual(self.invoke(timeout=timeout)["error_code"], "invalid_arguments")
            self.assertEqual(self.invoke(cli=self.root / "missing-cli")["error_code"], "cli_missing")
            runner.assert_not_called()

    def test_default_config_is_relative_to_skill_and_platform_selection_is_explicit(self):
        with patch.object(backend, "ROOT", self.root), patch.object(backend.subprocess, "run", side_effect=self.completed({"ok": True, "errors": []})):
            self.assertNotIn("failure_reason", self.invoke(config=None))
        for system, machine, suffix in (("Darwin", "arm64", "darwin-arm64"), ("Darwin", "x86_64", "darwin-amd64"),
                                        ("Linux", "x86_64", "linux-amd64"), ("Windows", "AMD64", "windows-amd64.exe")):
            with patch.object(backend.platform, "system", return_value=system), patch.object(backend.platform, "machine", return_value=machine):
                self.assertTrue(str(backend.select_cli()).endswith(suffix))
        with patch.object(backend.platform, "system", return_value="Linux"), patch.object(backend.platform, "machine", return_value="aarch64"):
            with self.assertRaises(backend.BackendError):
                backend.select_cli()

    def test_help_and_bad_arguments_never_load_config_or_echo_credentials(self):
        with patch.object(backend, "load_config") as config:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as done:
                backend.main(["--help"])
            self.assertEqual(done.exception.code, 0)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as done:
                backend.main(["validate", "--site", "US", "--listing-file", "x", "--token", CONFIG["backend_token"]])
            self.assertEqual(done.exception.code, 2)
            self.assertNotIn(CONFIG["backend_token"], stderr.getvalue())
            config.assert_not_called()

    def test_main_returns_nonzero_for_business_error_even_when_cli_exits_zero(self):
        stdout = io.StringIO()
        with patch.object(backend.subprocess, "run", side_effect=self.completed({"ok": False, "errors": [CONFIG["backend_token"]]})), \
                contextlib.redirect_stdout(stdout):
            code = backend.main(["validate", "--site", "US", "--config", str(self.config), "--cli", str(self.cli),
                                 "--listing-file", str(self.source)])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["status"], "failed")
        self.assert_safe(result)

    def test_file_write_failure_never_reports_completion(self):
        with patch.object(backend.subprocess, "run", side_effect=self.completed({"keywords": []})), \
                patch.object(backend, "_write_json", side_effect=OSError(CONFIG["backend_token"])):
            result = self.invoke("expand", output=self.output)
        self.assertEqual(result["error_code"], "local_io_error")
        self.assertFalse(self.output.exists())
        self.assert_safe(result)

    def test_private_raw_file_is_cleaned_after_timeout(self):
        captured = []
        def interrupted(args, **kwargs):
            raw = Path(args[args.index("--output") + 1])
            raw.write_text(CONFIG["backend_token"], encoding="utf-8")
            captured.append(raw)
            raise subprocess.TimeoutExpired(args, 1, output=CONFIG["backend_token"])
        with patch.object(backend.subprocess, "run", side_effect=interrupted):
            result = self.invoke("expand", output=self.output, timeout=1)
        self.assertEqual(result["error_code"], "cli_timeout")
        self.assertFalse(captured[0].parent.exists())
        self.assertFalse(self.output.exists())
        self.assert_safe(result)

    @unittest.skipIf(os.name == "nt", "POSIX fake executable; platform selection is tested separately")
    def test_real_launcher_process_all_commands_without_backend_or_shell_expansion(self):
        self.cli.write_text("#!" + sys.executable + "\n" + '''import json, os, pathlib, sys
args = sys.argv[1:]
token = os.environ["LAOCHEN_BACKEND_TOKEN"]
response = {"ok": True, "errors": [], "keywords": ["goose statue"], "qa_pairs": [], "echo": token}
print(token, file=sys.stderr)
if "--output" in args:
    pathlib.Path(args[args.index("--output") + 1]).write_text(json.dumps(response), encoding="utf-8")
    print("short summary " + token)
else:
    print(json.dumps(response))
''', encoding="utf-8")
        for command in ("expand", "qa", "validate"):
            args = [sys.executable, str(ROOT / "scripts/backend_cli.py"), command, "--site", "US",
                    "--config", str(self.config), "--cli", str(self.cli), "--output", str(self.output)]
            args += ["--asins", "B000000001"] if command == "expand" else ["--keywords-file" if command == "qa" else "--listing-file", str(self.source)]
            process = subprocess.run(args, capture_output=True, text=True, cwd=self.root, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)["status"], "completed")
            self.assert_safe(process.stdout + process.stderr)
            self.assertEqual(json.loads(self.output.read_text())["echo"], "[REDACTED]")


class QuarantineTests(unittest.TestCase):
    def test_only_selected_cli_quarantine_is_removed_when_present(self):
        responses = [subprocess.CompletedProcess([], 0, b"com.apple.quarantine\n", b""),
                     subprocess.CompletedProcess([], 0, b"", b"")]
        with patch.object(backend.subprocess, "run", side_effect=responses) as runner:
            backend._clear_quarantine(Path("/fake/selected-cli"))
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(runner.call_args.args[0], ["/usr/bin/xattr", "-d", "com.apple.quarantine", "/fake/selected-cli"])
        with patch.object(backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as runner:
            backend._clear_quarantine(Path("/fake/selected-cli"))
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
