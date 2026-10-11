"""Bootstrap tests use synthetic runtimes; no downloads, auth, or real installs."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import runtime_bootstrap as rb


class RuntimeBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "skill"
        (self.root / "scripts").mkdir(parents=True)
        for name in rb.VERIFIED_SOURCES:
            (self.root / name).write_text("# synthetic source\n", encoding="utf-8")
        self.bootstrap = rb.RuntimeBootstrap(self.root, self.base / "cache")
        self.python, self.other = self.base / "python", self.base / "python-other"
        for path in (self.python, self.other):
            path.touch()
        self.candidates = [str(self.python)]
        self.probes = {str(self.python): {"version": [3, 12, 8], "bits": 64, "pillow": "12.3.0", "numpy": "2.3.5"},
                       str(self.other): {"version": [3, 12, 8], "bits": 64, "pillow": "12.3.0", "numpy": "2.3.5"}}
        self.smoke = json.dumps({"passed": True, "checks": ["main_white_jpeg", "xmp_disclosure"]})
        self.calls = []

    def runner(self, argv, **kwargs):
        argv = list(map(str, argv))
        self.calls.append((argv, kwargs))
        if argv[-1] == rb.PYTHON_PROBE:
            return json.dumps(self.probes[argv[0]])
        if rb.VERIFY_SMOKE in argv:
            return self.smoke
        if "venv" in argv or "pip" in argv:
            return ""
        raise AssertionError(argv)

    @contextlib.contextmanager
    def simulated(self):
        with patch.object(self.bootstrap, "_candidates", side_effect=lambda: list(self.candidates)), \
                patch.object(rb, "_run", side_effect=self.runner):
            yield

    def test_compatible_python_is_ready_without_writes(self):
        with self.simulated():
            result = self.bootstrap.inspect()
        self.assertTrue(result["ready"])
        self.assertFalse(result["verified"])
        self.assertTrue(result["verification_required"])
        self.assertEqual(result["selected"], {"python": str(self.python)})
        self.assertEqual(result["commands"]["studio_argv_prefix"][1:3], ["-X", "utf8"])
        self.assertTrue(result["commands"]["studio_argv_prefix"][3].endswith("studio.py"))
        self.assertFalse(self.bootstrap.cache.exists())

    def test_compatible_ranges_are_accepted_and_out_of_range_needs_install(self):
        cases = [("11.0.0", "1.26.4", True), ("12.1.0", "2.1.3", True), ("10.4.0", "2.3.5", False),
                 ("13.0.0", "2.3.5", False), ("12.3.0", "1.25.2", False), ("12.3.0", "3.0.0", False),
                 (None, "2.3.5", False), ("12.3.0", None, False)]
        for pillow, numpy, ready in cases:
            with self.subTest(pillow=pillow, numpy=numpy):
                self.probes[str(self.python)].update(pillow=pillow, numpy=numpy)
                with self.simulated():
                    result = self.bootstrap.inspect()
                self.assertEqual(result["ready"], ready)
                if not ready:
                    self.assertTrue(result["installable"])
                    self.assertEqual(result["usable_python"], str(self.python))
                    self.assertTrue(result["needs_confirmation"])

    def test_first_compatible_candidate_wins_and_incompatible_ones_are_skipped(self):
        self.probes[str(self.python)].update(pillow="9.5.0")
        self.candidates = [str(self.python), str(self.other)]
        with self.simulated():
            result = self.bootstrap.inspect()
        self.assertTrue(result["ready"])
        self.assertEqual(result["selected"]["python"], str(self.other))
        self.assertEqual(result["usable_python"], str(self.python))

    def test_old_or_32bit_python_is_not_installable(self):
        for change in ({"version": [3, 10, 12]}, {"bits": 32}):
            with self.subTest(change=change):
                self.probes[str(self.python)].update(change)
                with self.simulated():
                    report = self.bootstrap.inspect()
                self.assertEqual(report["missing"][0]["name"], "python")
                self.assertFalse(report["missing"][0]["installable"])
                self.assertIn("64-bit", report["missing"][0]["reason"])
                self.probes[str(self.python)].update(version=[3, 12, 8], bits=64)

    def test_probe_hides_pythonpath_and_cwd_but_keeps_user_site(self):
        with self.simulated():
            self.bootstrap.inspect()
        argv = self.calls[0][0]
        self.assertEqual(argv[1:4], ["-E", "-P", "-B"])
        self.assertNotIn("-I", argv[:4])
        self.assertNotIn("-s", argv[:4])

    def test_unknown_and_restricted_never_install(self):
        self.probes[str(self.python)].update(pillow=None)
        for authorization in ("unknown", "restricted"):
            with self.subTest(authorization=authorization), self.simulated():
                report = self.bootstrap.install(authorization)
            self.assertFalse(report["installation_attempted"])
            self.assertTrue(report["needs_confirmation"])
        self.assertFalse(any("pip" in argv for argv, _ in self.calls))
        self.assertFalse(self.bootstrap.cache.exists())

    def test_missing_python_requires_the_user_not_an_install(self):
        self.probes[str(self.python)].update(version=[3, 9, 6])
        with self.simulated():
            report = self.bootstrap.install("user-confirmed")
        self.assertFalse(report["installation_attempted"])
        self.assertIn("Python", report["next_action"])

    def test_authorized_install_pins_wheels_in_a_private_venv_then_verifies_and_publishes(self):
        self.probes[str(self.python)].update(pillow="10.0.0", numpy=None)
        venv_python = []

        def runner(argv, **kwargs):
            argv = list(map(str, argv))
            if "venv" in argv:
                target = Path(argv[-1])
                binary = target / "bin/python"
                binary.parent.mkdir(parents=True)
                binary.touch()
                venv_python.append(str(binary))
                self.probes[str(binary)] = {"version": [3, 12, 8], "bits": 64, "pillow": "12.3.0", "numpy": "2.3.5"}
                self.candidates.append(str(binary))
            return self.runner(argv, **kwargs)
        with patch.object(self.bootstrap, "_candidates", side_effect=lambda: list(self.candidates)), \
                patch.object(rb, "_run", side_effect=runner), patch.object(rb.platform, "system", return_value="Linux"):
            report = self.bootstrap.install("user-confirmed")
        self.assertTrue(report["ready"], report)
        self.assertTrue(report["verified"])
        self.assertEqual(report["installed"], ["pillow", "numpy"])
        self.assertEqual(report["selected"]["python"], venv_python[0])
        self.assertTrue(Path(venv_python[0]).is_relative_to(self.bootstrap.cache))
        pip = next((argv, kwargs) for argv, kwargs in self.calls if "pip" in argv)
        self.assertIn("--only-binary=:all:", pip[0])
        self.assertIn("Pillow==12.3.0", pip[0])
        self.assertIn("numpy==2.3.5", pip[0])
        self.assertEqual(pip[1]["env"]["PIP_CONFIG_FILE"], rb.os.devnull)
        self.assertEqual(json.loads(self.bootstrap.selection_path.read_text())["python"], venv_python[0])

    def test_failed_smoke_test_never_publishes_or_claims_ready(self):
        self.smoke = json.dumps({"passed": False})
        with self.simulated():
            report = self.bootstrap.verified_report()
        self.assertFalse(report["ready"])
        self.assertIn("smoke test", report["error"])
        self.assertFalse(self.bootstrap.selection_path.exists())
        self.assertFalse(self.bootstrap.verified_path.exists())

    def test_verify_runs_the_real_smoke_script_against_the_skill_scripts(self):
        with self.simulated():
            report = self.bootstrap.verified_report()
        self.assertTrue(report["verified"])
        argv = next(argv for argv, _ in self.calls if rb.VERIFY_SMOKE in argv)
        self.assertEqual(argv[-1], str(self.root / "scripts"))
        self.assertIn("studio_main.export", rb.VERIFY_SMOKE)
        self.assertIn("xmp_disclosure", rb.VERIFY_SMOKE)

    def test_stamp_is_reused_for_seven_days_and_invalidated_by_source_or_python_change(self):
        with self.simulated():
            self.bootstrap.verified_report()
            calls = len(self.calls)
            self.assertTrue(self.bootstrap.verified_report()["cached_verification"])
            self.assertEqual(len(self.calls), calls)
            (self.root / "scripts/studio_main.py").write_text("# changed\n", encoding="utf-8")
            self.assertIsNone(self.bootstrap.cached_report())
            self.bootstrap.verified_report()
            self.python.write_bytes(b"new interpreter build")
            self.assertIsNone(self.bootstrap.cached_report())
            self.bootstrap.verified_report()
            stamp = json.loads(self.bootstrap.verified_path.read_text())
            stamp["verified_at"] = time.time() - rb.VERIFIED_TTL_SECONDS - 5
            self.bootstrap.verified_path.write_text(json.dumps(stamp))
            self.assertIsNone(self.bootstrap.cached_report())

    def test_unwritable_cache_falls_back_to_a_user_temp_stamp(self):
        fallback = self.base / "fallback"
        with self.simulated(), patch.object(type(self.bootstrap), "fallback_cache", new=property(lambda _: fallback)), \
                patch.object(self.bootstrap, "_prepare_cache", side_effect=rb.BootstrapError("read-only")):
            report = self.bootstrap.verified_report()
            self.assertEqual(report["stamp_dir"], str(fallback))
            self.assertEqual(self.bootstrap._selection()["python"], str(self.python))
            self.assertTrue(self.bootstrap.cached_report()["cached_verification"])

    def test_symlink_cache_cannot_redirect_install(self):
        real = self.base / "real"
        real.mkdir()
        link = self.base / "link"
        link.symlink_to(real, target_is_directory=True)
        bootstrap = rb.RuntimeBootstrap(self.root, link / "runtime")
        with self.assertRaises(rb.BootstrapError):
            bootstrap._prepare_cache()

    def test_candidates_include_override_selection_and_earlier_private_venvs(self):
        old_venv = self.bootstrap.cache_root / "50adf1f1e3035a97" / "python-abc" / "bin" / "python"
        old_venv.parent.mkdir(parents=True)
        old_venv.touch()
        with patch.dict(rb.os.environ, {"LC_STUDIO_PYTHON": str(self.other)}), \
                patch.object(rb.platform, "system", return_value="Linux"):
            candidates = self.bootstrap._candidates()
        self.assertEqual(candidates[0], str(self.other))
        self.assertIn(str(old_venv), candidates)

    def test_cli_install_does_not_default_to_full_access(self):
        with patch.object(rb, "RuntimeBootstrap") as constructor, contextlib.redirect_stdout(io.StringIO()):
            constructor.return_value.install.return_value = {"ready": False}
            self.assertEqual(rb.main(["install", "--json"]), 2)
        constructor.return_value.install.assert_called_once_with("unknown")

    def test_error_redacts_package_url_password(self):
        result = subprocess.CompletedProcess(["fake"], 1, "", "failed https://user:secret@example.invalid/file")
        with patch.object(rb.subprocess, "run", return_value=result):
            with self.assertRaises(rb.BootstrapError) as caught:
                rb._run(["fake"])
        self.assertNotIn("secret", str(caught.exception))

    def test_windows_venv_uses_exe_not_shell_activation(self):
        self.bootstrap._prepare_cache()
        with patch.object(rb.platform, "system", return_value="Windows"), patch.object(rb, "_run", return_value="") as run:
            binary = self.bootstrap._install_python(str(self.python))
        self.assertTrue(binary.replace("\\", "/").endswith("Scripts/python.exe"))
        self.assertEqual(str(run.call_args_list[1].args[0][0]), binary)
        self.assertFalse(any(str(part).endswith((".sh", ".bat", ".cmd")) for call in run.call_args_list for part in call.args[0]))

    def test_windows_cache_uses_localappdata(self):
        local = self.base / "用户 Local AppData"
        with patch.object(rb.platform, "system", return_value="Windows"), \
                patch.dict(rb.os.environ, {"LOCALAPPDATA": str(local), "LC_AMAZON_STUDIO_CACHE": ""}):
            bootstrap = rb.RuntimeBootstrap(self.root)
        self.assertEqual(bootstrap.cache_root, local / "lc-amazon-image-studio/runtime")
        self.assertFalse(bootstrap.cache_root.exists())

    def test_windows_launcher_lists_only_and_keeps_spaces(self):
        listing = " -V:3.12 * C:\\Users\\客户 A\\Python312\\python.exe\n -3.11-64 C:\\Python311\\python.exe\n"
        with patch.object(rb.platform, "system", return_value="Windows"), \
                patch.object(rb.shutil, "which", return_value="C:/Windows/py.exe"), \
                patch.object(rb, "_run", return_value=listing) as run:
            paths = self.bootstrap._launcher_pythons()
        self.assertEqual(paths, [r"C:\Users\客户 A\Python312\python.exe", r"C:\Python311\python.exe"])
        self.assertEqual(run.call_args.args[0], ["C:/Windows/py.exe", "-0p"])

    def test_platform_report_flags_windows_arm_only(self):
        cases = [("Windows", "AMD64", False), ("Windows", "ARM64", True), ("Darwin", "arm64", False), ("Darwin", "x86_64", False)]
        for system, machine, warned in cases:
            with self.subTest(system=system, machine=machine), patch.object(rb.platform, "system", return_value=system), \
                    patch.object(rb.platform, "machine", return_value=machine):
                result = rb._host_info()
            self.assertEqual(bool(result["warnings"]), warned)
            self.assertIn("not target-machine tests", result["validation"])

    def test_utf8_subprocess(self):
        result = subprocess.CompletedProcess(["fake"], 0, "客户 路径", "")
        with patch.object(rb.subprocess, "run", return_value=result) as run:
            self.assertEqual(rb._run(["fake"]), "客户 路径")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_module_stays_standard_library_only(self):
        source = Path(rb.__file__).read_text(encoding="utf-8")
        head = source.split("REQUIREMENTS", 1)[0]
        self.assertNotIn("import PIL", head)
        self.assertNotIn("import numpy", head)
        for word in ("playwright", "chromium", "node_modules", "fonts/"):
            self.assertNotIn(word, source.lower())

    def test_real_smoke_script_passes_with_this_interpreter(self):
        """Runs the shipped smoke script for real with the test interpreter (needs Pillow + NumPy)."""
        root = Path(rb.__file__).resolve().parents[1]
        output = rb._run([sys.executable, *rb.PROBE_FLAGS, "-c", rb.VERIFY_SMOKE, str(root / "scripts")], timeout=120)
        self.assertTrue(json.loads(output.splitlines()[-1])["passed"])


if __name__ == "__main__":
    unittest.main()
