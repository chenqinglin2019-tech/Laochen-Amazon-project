"""Bootstrap tests use synthetic runtimes; no downloads, auth, or real installs."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import runtime_bootstrap as rb


class RuntimeBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "skill"
        self.fonts = self.root / "assets/fonts"
        self.fonts.mkdir(parents=True)
        self.lock = {"node_min_major": 20, "pillow_version": "12.3.0", "playwright_version": "1.62.1", "chromium_version": "149.0.7827.55"}
        (self.root / "assets/layout-runtime.json").write_text(json.dumps(self.lock))
        (self.fonts / "test.ttf").write_bytes(b"frozen font bytes")
        (self.fonts / "OFL.txt").write_text("synthetic license")
        (self.fonts / "manifest.json").write_text(json.dumps({"fonts": [{"file": "test.ttf", "sha256": hashlib.sha256(b"frozen font bytes").hexdigest()}], "license_files": ["OFL.txt"]}))
        self.bootstrap = rb.RuntimeBootstrap(self.root, self.base / "cache")
        self.python, self.node, self.browser = (self.base / name for name in ("python", "node", "chromium"))
        for path in (self.python, self.node, self.browser):
            path.touch()
        self.modules = self.base / "modules"
        (self.modules / "playwright").mkdir(parents=True)
        (self.modules / "playwright/package.json").write_text(json.dumps({"version": "1.62.1"}))
        self.candidates = {"python": [str(self.python)], "node": [str(self.node)], "modules": [str(self.modules)], "chromium": [str(self.browser)]}
        self.pillow = "12.3.0"
        self.numpy = "2.3.5"
        self.browser_version = "Chromium 149.0.7827.55"
        self.node_version = "v24.21.0"
        self.calls = []

    def runner(self, argv, **kwargs):
        self.calls.append((list(map(str, argv)), kwargs))
        if argv[-1] == rb.PYTHON_PROBE:
            return json.dumps({"version": [3, 12, 8], "bits": 64, "pillow": self.pillow, "numpy": self.numpy})
        if str(argv[0]) == str(self.node):
            return self.node_version
        if str(argv[0]) == str(self.browser):
            return self.browser_version
        raise AssertionError(argv)

    @contextlib.contextmanager
    def simulated(self):
        with patch.object(self.bootstrap, "_candidates", return_value=self.candidates), patch.object(rb, "_run", side_effect=self.runner):
            yield

    def test_complete_inspect_reuses_all_without_writes_or_network(self):
        with self.simulated(), patch.object(rb, "_official_download", side_effect=AssertionError("network forbidden")):
            result = self.bootstrap.inspect()
        self.assertTrue(result["ready"])
        self.assertFalse(result["verified"])
        self.assertTrue(result["verification_required"])
        self.assertFalse(result["needs_confirmation"])
        self.assertEqual(result["commands"]["env"]["LC_LAYOUT_NODE"], str(self.node))
        self.assertEqual(result["commands"]["pipeline_argv_prefix"][0], str(self.python))
        self.assertFalse(self.bootstrap.cache.exists())

    def test_missing_pillow_is_inspectable_without_importing_pil(self):
        self.pillow = None
        with self.simulated():
            result = self.bootstrap.inspect()
        self.assertEqual(result["installable"], ["pillow"])
        self.assertEqual(result["usable_python"], str(self.python))
        self.assertFalse(self.bootstrap.cache.exists())

    def test_old_node_and_browser_prefix_are_rejected(self):
        self.node_version = "v18.20.0"
        self.browser_version = "Chromium 149.0.7827.550"
        with self.simulated():
            result = self.bootstrap.inspect()
        self.assertEqual(result["installable"], ["node", "chromium"])

    def test_invalid_preferred_runtime_falls_through_to_valid(self):
        bad_node = self.base / "bad-node"
        bad_node.touch()
        self.candidates["node"].insert(0, str(bad_node))
        original = self.runner
        with patch.object(self.bootstrap, "_candidates", return_value=self.candidates), patch.object(rb, "_run", side_effect=lambda argv, **kw: "broken" if str(argv[0]) == str(bad_node) else original(argv, **kw)):
            result = self.bootstrap.inspect()
        self.assertEqual(result["selected"]["node"], str(self.node))

    def test_unknown_and_restricted_never_install(self):
        self.pillow = None
        for authorization in ("unknown", "restricted"):
            with self.simulated(), patch.object(self.bootstrap, "_install_python", side_effect=AssertionError("installation forbidden")):
                result = self.bootstrap.install(authorization)
            self.assertTrue(result["needs_confirmation"])
            self.assertFalse(result["installation_performed"])
        self.assertFalse(self.bootstrap.cache.exists())

    def test_font_failure_requires_restore_not_substitution(self):
        (self.fonts / "test.ttf").write_bytes(b"wrong font")
        with self.simulated(), patch.object(self.bootstrap, "_prepare_cache", side_effect=AssertionError("no writes")):
            result = self.bootstrap.install("full-access")
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing"][0]["name"], "bundled_fonts")
        self.assertIn("SHA-256", result["missing"][0]["details"][0])

    def test_missing_python_requires_external_confirmation(self):
        self.candidates["python"] = []
        with self.simulated():
            result = self.bootstrap.install("user-confirmed")
        self.assertEqual(result["missing"][0]["name"], "python")
        self.assertFalse(result["missing"][0]["installable"])
        self.assertFalse(self.bootstrap.cache.exists())

    def test_authorized_install_publishes_selection_only_after_verification(self):
        self.pillow = None
        def install(python):
            self.assertEqual(python, str(self.python))
            self.pillow = "12.3.0"
            return str(self.python)
        def verify(report):
            self.assertTrue(report["ready"])
            self.assertFalse(self.bootstrap.selection_path.exists())
            return {"doctor_passed": True, "browser_launch_passed": True}
        with self.simulated(), patch.object(self.bootstrap, "_install_python", side_effect=install), patch.object(self.bootstrap, "verify", side_effect=verify):
            result = self.bootstrap.install("full-access")
        self.assertTrue(result["ready"])
        self.assertEqual(result["installed"], ["pillow"])
        self.assertTrue(self.bootstrap.selection_path.is_file())

    def test_failed_doctor_never_publishes_selection_or_claims_ready(self):
        with self.simulated(), patch.object(self.bootstrap, "verify", side_effect=rb.BootstrapError("missing shared OS library")):
            result = self.bootstrap.install("user-confirmed")
        self.assertFalse(result["ready"])
        self.assertIn("missing shared OS library", result["error"])
        self.assertTrue(result["needs_confirmation"])
        self.assertFalse(self.bootstrap.selection_path.exists())

    def test_install_error_lists_remaining_dependencies(self):
        self.pillow = None
        with self.simulated(), patch.object(self.bootstrap, "_install_python", side_effect=rb.BootstrapError("wheel unavailable")):
            result = self.bootstrap.install("full-access")
        self.assertEqual(result["installable"], ["pillow"])
        self.assertIn("wheel unavailable", result["error"])
        self.assertFalse(result["ready"])

    def test_venv_pip_exact_pin_isolated_no_system_change(self):
        self.bootstrap._prepare_cache()
        with patch.object(rb, "_run", return_value="") as run:
            binary = self.bootstrap._install_python(str(self.python))
        commands = [[str(item) for item in call.args[0]] for call in run.call_args_list]
        self.assertEqual(commands[0][1:4], ["-I", "-m", "venv"])
        self.assertIn("--isolated", commands[1])
        self.assertIn("Pillow==12.3.0", commands[1])
        self.assertIn("numpy==2.3.5", commands[1])
        self.assertIn("--only-binary=:all:", commands[1])
        self.assertEqual(run.call_args_list[1].kwargs["env"]["PIP_CONFIG_FILE"], rb.os.devnull)
        self.assertTrue(Path(binary).is_relative_to(self.bootstrap.cache))
        self.assertNotIn("--break-system-packages", commands[1])

    def test_playwright_exact_pin_and_builtin_chromium_install(self):
        self.bootstrap._prepare_cache()
        npm = self.base / "npm-cli.js"
        npm.touch()
        with patch.object(self.bootstrap, "_npm_cli", return_value=str(npm)), patch.object(rb, "_run", return_value="") as run:
            modules = self.bootstrap._install_playwright(str(self.node))
            playwright = Path(modules) / "playwright"
            playwright.mkdir(parents=True)
            (playwright / "cli.js").touch()
            self._write_browser_manifest(Path(modules), "149.0.7827.55", "1228")
            self.bootstrap._install_browser(str(self.node), modules)
        commands = [[str(item) for item in call.args[0]] for call in run.call_args_list]
        self.assertIn("playwright@1.62.1", commands[0])
        self.assertIn("--ignore-scripts", commands[0])
        npm_env = run.call_args_list[0].kwargs["env"]
        self.assertNotEqual(npm_env["npm_config_userconfig"], npm_env["npm_config_globalconfig"])
        self.assertEqual(Path(npm_env["npm_config_userconfig"]).read_text(), "")
        self.assertEqual(Path(npm_env["npm_config_globalconfig"]).read_text(), "")
        self.assertEqual(commands[1][-2:], ["install", "chromium"])
        self.assertNotIn("--with-deps", commands[1])
        self.assertTrue(Path(run.call_args_list[1].kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"]).is_relative_to(self.bootstrap.cache))

    def _write_browser_manifest(self, modules, version, revision):
        core = Path(modules) / "playwright-core"
        core.mkdir(parents=True, exist_ok=True)
        (core / "browsers.json").write_text(json.dumps({"browsers": [
            {"name": name, "browserVersion": version, "revision": revision}
            for name in ("chromium", "chromium-headless-shell")]}))
        return core

    def test_cold_browser_install_uses_official_149_driver_not_runtime_151(self):
        self._write_browser_manifest(self.modules, "151.0.7922.34", "1234")
        driver_modules = self.base / "browser-installer/node_modules"
        core = self._write_browser_manifest(driver_modules, "149.0.7827.55", "1228")
        (core / "package.json").write_text(json.dumps({"version": "1.61.0"}))
        (core / "cli.js").touch()
        with patch.object(self.bootstrap, "_install_npm_package", return_value=str(driver_modules)) as install, patch.object(rb, "_run", return_value="") as run:
            result = self.bootstrap._install_browser(str(self.node), str(self.modules))
        install.assert_called_once_with(str(self.node), "playwright-core", "1.61.0", "browser-installer-")
        self.assertEqual(run.call_args.args[0][1], str(core / "cli.js"))
        self.assertEqual(result["chromium_version"], "149.0.7827.55")
        self.assertEqual(result["rendering_playwright_version"], "1.62.1")
        self.assertEqual(json.loads((self.modules / "playwright/package.json").read_text())["version"], "1.62.1")

    def test_cold_browser_install_rejects_wrong_version_or_revision_before_download(self):
        self._write_browser_manifest(self.modules, "151.0.7922.34", "1234")
        driver_modules = self.base / "browser-installer/node_modules"
        for version, revision in (("151.0.7922.34", "1234"), ("149.0.7827.55", "9999")):
            with self.subTest(version=version, revision=revision):
                core = self._write_browser_manifest(driver_modules, version, revision)
                (core / "package.json").write_text(json.dumps({"version": "1.61.0"}))
                (core / "cli.js").touch()
                with patch.object(self.bootstrap, "_install_npm_package", return_value=str(driver_modules)), patch.object(rb, "_run", side_effect=AssertionError("No mismatched browser download allowed")):
                    with self.assertRaisesRegex(rb.BootstrapError, "frozen version/revision"):
                        self.bootstrap._install_browser(str(self.node), str(self.modules))

    def test_browser_manifest_requires_both_targets_once(self):
        core = self._write_browser_manifest(self.modules, "149.0.7827.55", "1228")
        self.assertTrue(self.bootstrap._browser_manifest_matches(core / "browsers.json", "149.0.7827.55", "1228"))
        content = json.loads((core / "browsers.json").read_text())
        content["browsers"].pop()
        (core / "browsers.json").write_text(json.dumps(content))
        self.assertFalse(self.bootstrap._browser_manifest_matches(core / "browsers.json", "149.0.7827.55", "1228"))

    def test_browser_installer_is_not_discovered_as_rendering_modules(self):
        installer = self.bootstrap.cache / "browser-installer-test/node_modules/playwright"
        installer.mkdir(parents=True)
        (installer / "package.json").write_text(json.dumps({"version": "1.61.0"}))
        self.assertNotIn(str(installer.parent), self.bootstrap._candidates()["modules"])

    def test_authorized_cold_browser_handoff_preserves_production_versions(self):
        self.candidates["chromium"] = []
        self._write_browser_manifest(self.modules, "151.0.7922.34", "1234")
        driver_modules = self.base / "browser-installer/node_modules"
        core = self._write_browser_manifest(driver_modules, "149.0.7827.55", "1228")
        (core / "package.json").write_text(json.dumps({"version": "1.61.0"}))
        (core / "cli.js").touch()
        original = self.runner
        def run(argv, **kwargs):
            if len(argv) > 1 and str(argv[1]) == str(core / "cli.js"):
                self.candidates["chromium"] = [str(self.browser)]
                return ""
            return original(argv, **kwargs)
        def verify(report):
            self.assertEqual(report["selected"]["modules"], str(self.modules))
            self.assertEqual(report["versions"]["playwright"], "1.62.1")
            self.assertEqual(report["versions"]["chromium"], "149.0.7827.55")
            return {"doctor_passed": True, "python_modules_passed": True, "browser_launch_passed": True}
        with patch.object(self.bootstrap, "_candidates", return_value=self.candidates), patch.object(rb, "_run", side_effect=run), patch.object(self.bootstrap, "_install_npm_package", return_value=str(driver_modules)), patch.object(self.bootstrap, "verify", side_effect=verify):
            result = self.bootstrap.install("full-access")
        self.assertTrue(result["verified"])
        self.assertEqual(result["installed"], ["chromium"])
        self.assertEqual(result["browser_installation"]["installer_package"], "playwright-core")
        self.assertEqual(json.loads(self.bootstrap.selection_path.read_text())["modules"], str(self.modules))

    def test_installer_env_excludes_registry_credentials_and_browser_mirrors(self):
        with patch.dict(rb.os.environ, {"NPM_TOKEN": "secret", "npm_config_registry": "https://private.invalid", "PLAYWRIGHT_DOWNLOAD_HOST": "https://mirror.invalid", "NODE_OPTIONS": "--require unexpected.js", "NODE_PATH": "/unexpected", "NODE_TLS_REJECT_UNAUTHORIZED": "0"}):
            env = self.bootstrap._install_env(str(self.node))
        self.assertNotIn("NPM_TOKEN", env)
        self.assertNotIn("npm_config_registry", env)
        self.assertNotIn("PLAYWRIGHT_DOWNLOAD_HOST", env)
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertNotIn("NODE_PATH", env)
        self.assertNotIn("NODE_TLS_REJECT_UNAUTHORIZED", env)

    def test_actual_doctor_and_browser_are_both_required(self):
        with self.simulated():
            report = self.bootstrap.inspect()
        with patch.object(rb, "_run", side_effect=[json.dumps({"passed": True, "errors": []}), "ok", '{"passed":true}']) as run:
            verified = self.bootstrap.verify(report)
        self.assertEqual(verified, {"doctor_passed": True, "python_modules_passed": True, "browser_launch_passed": True})
        self.assertIn("lc_layout.py", str(run.call_args_list[0].args[0]))
        self.assertIn("lc_typography", str(run.call_args_list[1].args[0]))
        self.assertEqual(run.call_args_list[2].args[0][2], rb.BROWSER_SMOKE)

    def test_missing_numpy_is_explicit_and_python_310_is_not_installable(self):
        self.numpy = None
        with self.simulated():
            result = self.bootstrap.inspect()
        self.assertEqual(result["installable"], ["numpy"])
        original = self.runner
        with patch.object(self.bootstrap, "_candidates", return_value=self.candidates), patch.object(rb, "_run", side_effect=lambda argv, **kw: json.dumps({"version": [3, 10, 12], "bits": 64, "pillow": "12.3.0", "numpy": None}) if argv[-1] == rb.PYTHON_PROBE else original(argv, **kw)):
            result = self.bootstrap.inspect()
        self.assertEqual(result["missing"][0]["name"], "python")
        self.assertFalse(result["missing"][0]["installable"])

    def test_verify_failure_is_not_replaced_with_presence_success(self):
        with self.simulated(), patch.object(self.bootstrap, "verify", side_effect=rb.BootstrapError("browser failed")):
            result = self.bootstrap.verified_report()
        self.assertFalse(result["ready"])
        self.assertFalse(result["verified"])
        self.assertIn("browser failed", result["error"])

    def test_verify_cli_uses_verification_not_presence(self):
        with patch.object(rb, "RuntimeBootstrap") as constructor, contextlib.redirect_stdout(io.StringIO()):
            constructor.return_value.verified_report.return_value = {"ready": True, "verified": True}
            self.assertEqual(rb.main(["verify", "--json"]), 0)
        constructor.return_value.verified_report.assert_called_once_with()
        constructor.return_value.inspect.assert_not_called()

    def test_node_archive_hash_failure_prevents_extract_and_execute(self):
        self.bootstrap._prepare_cache()
        def download(url, path):
            if url.endswith("SHASUMS256.txt"):
                Path(path).write_text("0" * 64 + f"  node-v{rb.NODE_FALLBACK_VERSION}-darwin-arm64.tar.gz\n")
            else:
                Path(path).write_bytes(b"wrong bytes")
        with patch.object(rb.platform, "system", return_value="Darwin"), patch.object(rb.platform, "machine", return_value="arm64"), patch.object(rb, "_official_download", side_effect=download), patch.object(rb, "_extract_node", side_effect=AssertionError("must not extract")):
            with self.assertRaisesRegex(rb.BootstrapError, "SHA-256 mismatch"):
                self.bootstrap._install_node()

    def test_node_verified_archive_uses_official_pinned_source(self):
        self.bootstrap._prepare_cache()
        urls = []
        def download(url, path):
            urls.append(url)
            if url.endswith("SHASUMS256.txt"):
                Path(path).write_text(hashlib.sha256(b"archive").hexdigest() + f"  node-v{rb.NODE_FALLBACK_VERSION}-linux-x64.tar.gz\n")
            else:
                Path(path).write_bytes(b"archive")
        with patch.object(rb.platform, "system", return_value="Linux"), patch.object(rb.platform, "machine", return_value="x86_64"), patch.object(rb, "_official_download", side_effect=download), patch.object(rb, "_extract_node") as extract:
            binary = self.bootstrap._install_node()
        self.assertTrue(all(url.startswith(f"https://nodejs.org/dist/v{rb.NODE_FALLBACK_VERSION}/") for url in urls))
        self.assertTrue(binary.endswith("/bin/node"))
        extract.assert_called_once()

    def test_archive_rejects_traversal_and_does_not_extract_symlinks(self):
        archive = self.base / "test.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            item = tarfile.TarInfo("node-root/../../escape")
            item.size = 1
            bundle.addfile(item, io.BytesIO(b"x"))
        with self.assertRaisesRegex(rb.BootstrapError, "Unsafe"):
            rb._extract_node(archive, self.base / "out", "node-root")
        self.assertFalse((self.base / "escape").exists())
        with tarfile.open(archive, "w:gz") as bundle:
            item = tarfile.TarInfo("node-root/bin/npm")
            item.type = tarfile.SYMTYPE
            item.linkname = "/not/a/safe/path"
            bundle.addfile(item)
        rb._extract_node(archive, self.base / "out", "node-root")
        self.assertFalse((self.base / "out/node-root/bin/npm").is_symlink())

    def test_zip_rejects_traversal(self):
        archive = self.base / "test.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("node-root/../../escape", "x")
        with self.assertRaisesRegex(rb.BootstrapError, "Unsafe"):
            rb._extract_node(archive, self.base / "out", "node-root")

    def test_unofficial_download_rejected_before_network(self):
        with patch.object(rb.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")):
            for url in ("http://nodejs.org/dist/test", "https://example.org/dist/test"):
                with self.assertRaises(rb.BootstrapError):
                    rb._official_download(url, self.base / "archive")

    def test_symlink_cache_cannot_redirect_install(self):
        target = self.base / "unrelated"
        target.mkdir()
        self.bootstrap.cache_root.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(rb.BootstrapError, "symlinks"):
            self.bootstrap._prepare_cache()

    def test_nested_installer_caches_cannot_redirect_writes(self):
        self.bootstrap._prepare_cache()
        target = self.base / "unrelated"
        target.mkdir()
        for name in ("browsers", "npm-cache", "pip-cache"):
            with self.subTest(name=name):
                link = self.bootstrap.cache / name
                link.symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(rb.BootstrapError, "real directory"):
                    self.bootstrap._prepare_cache()
                link.unlink()

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

    def test_four_platform_node_archives_extract_without_network(self):
        """Synthetic archives, not macOS Intel or Windows executable testing."""
        cases = [("mac-intel", "Darwin", "x86_64", "darwin-x64", "bin/node"),
                 ("mac-silicon", "Darwin", "arm64", "darwin-arm64", "bin/node"),
                 ("win10-x64", "Windows", "AMD64", "win-x64", "node.exe"),
                 ("win11-x64", "Windows", "AMD64", "win-x64", "node.exe")]
        self.bootstrap._prepare_cache()
        for label, system, machine, suffix, binary in cases:
            with self.subTest(platform=label):
                folder = f"node-v{rb.NODE_FALLBACK_VERSION}-{suffix}"
                npm_rel = "node_modules/npm/bin/npm-cli.js" if system == "Windows" else "lib/node_modules/npm/bin/npm-cli.js"
                data = io.BytesIO()
                entries = {f"{folder}/{binary}": b"synthetic binary", f"{folder}/{npm_rel}": b"// synthetic npm"}
                if system == "Windows":
                    with zipfile.ZipFile(data, "w") as bundle:
                        for name, body in entries.items():
                            bundle.writestr(name, body)
                else:
                    with tarfile.open(fileobj=data, mode="w:gz") as bundle:
                        for name, body in entries.items():
                            item = tarfile.TarInfo(name)
                            item.size, item.mode = len(body), 0o755
                            bundle.addfile(item, io.BytesIO(body))
                archive_bytes = data.getvalue()
                extension = ".zip" if system == "Windows" else ".tar.gz"
                def download(url, destination):
                    if url.endswith("SHASUMS256.txt"):
                        Path(destination).write_text(hashlib.sha256(archive_bytes).hexdigest() + "  " + folder + extension + "\n")
                    else:
                        self.assertTrue(url.endswith(folder + extension))
                        Path(destination).write_bytes(archive_bytes)
                with patch.object(rb.platform, "system", return_value=system), patch.object(rb.platform, "machine", return_value=machine), patch.object(rb, "_official_download", side_effect=download):
                    installed = Path(self.bootstrap._install_node())
                self.assertEqual(installed.read_bytes(), b"synthetic binary")
                self.assertTrue(installed.as_posix().endswith(binary))
                self.assertEqual(Path(self.bootstrap._npm_cli(installed)).read_bytes(), b"// synthetic npm")

    def test_windows_venv_uses_exe_not_shell_activation(self):
        self.bootstrap._prepare_cache()
        with patch.object(rb.platform, "system", return_value="Windows"), patch.object(rb, "_run", return_value="") as run:
            binary = self.bootstrap._install_python(str(self.python))
        self.assertTrue(binary.endswith("Scripts/python.exe"))
        self.assertEqual(str(run.call_args_list[1].args[0][0]), binary)
        self.assertFalse(any(str(part).endswith((".sh", ".bat", ".cmd")) for call in run.call_args_list for part in call.args[0]))

    def test_windows_cache_uses_localappdata(self):
        local = self.base / "用户 Local AppData"
        with patch.object(rb.platform, "system", return_value="Windows"), patch.dict(rb.os.environ, {"LOCALAPPDATA": str(local)}):
            bootstrap = rb.RuntimeBootstrap(self.root)
        self.assertEqual(bootstrap.cache_root, local / "lc-amazon-image-studio/runtime")
        self.assertFalse(bootstrap.cache_root.exists())

    def test_windows_path_separator_and_case_are_normalized(self):
        with patch.object(rb.platform, "system", return_value="Windows"), patch.dict(rb.os.environ, {"Path": r"C:\Windows;C:\Tools", "node_options": "--require bad.js"}, clear=True):
            env = self.bootstrap._install_env(r"C:\Users\客户 A\Node\node.exe")
        self.assertEqual(env["PATH"], "C:\\Users\\客户 A\\Node;C:\\Windows;C:\\Tools")
        self.assertNotIn("Path", env)
        self.assertNotIn("node_options", env)

    def test_windows_launcher_lists_only_and_keeps_spaces(self):
        listing = " -V:3.12 * C:\\Users\\客户 A\\Python312\\python.exe\n -3.11-64 C:\\Python311\\python.exe\n"
        with patch.object(rb.platform, "system", return_value="Windows"), patch.object(rb.shutil, "which", return_value="C:/Windows/py.exe"), patch.object(rb, "_run", return_value=listing) as run:
            paths = self.bootstrap._launcher_pythons()
        self.assertEqual(paths, [r"C:\Users\客户 A\Python312\python.exe", r"C:\Python311\python.exe"])
        self.assertEqual(run.call_args.args[0], ["C:/Windows/py.exe", "-0p"])

    def test_32bit_python_is_not_offered_as_installable(self):
        original = self.runner
        with patch.object(self.bootstrap, "_candidates", return_value=self.candidates), patch.object(rb, "_run", side_effect=lambda argv, **kw: json.dumps({"version": [3, 12, 8], "bits": 32, "pillow": "12.3.0", "numpy": "2.3.5"}) if argv[-1] == rb.PYTHON_PROBE else original(argv, **kw)):
            report = self.bootstrap.inspect()
        self.assertEqual(report["missing"][0]["name"], "python")
        self.assertIn("64-bit", report["missing"][0]["reason"])

    def test_browser_discovery_keeps_new_and_legacy_names(self):
        cache = self.base / "浏览器 cache"
        names = ["chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe",
                 "chromium_headless_shell-1228/chrome-headless-shell-win64/headless_shell.exe",
                 "chromium-1228/chrome-win64/chrome.exe",
                 "chromium-1228/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                 "chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                 "chromium-1228/chrome-mac/Chromium.app/Contents/MacOS/Chromium"]
        for name in names:
            path = cache / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        with patch.dict(rb.os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(cache)}):
            candidates = self.bootstrap._candidates()["chromium"]
        self.assertTrue(all(str(cache / name) in candidates for name in names))

    def test_windows_and_macos_support_reports_do_not_claim_unrun_tests(self):
        cases = [("Windows", "AMD64", "10", "10.0.19045", "", False),
                 ("Windows", "AMD64", "11", "10.0.26100", "", True),
                 ("Darwin", "x86_64", "23", "Darwin", "14.7", True),
                 ("Darwin", "arm64", "23", "Darwin", "14.7", True),
                 ("Darwin", "arm64", "22", "Darwin", "13.5", False),
                 ("Windows", "ARM64", "11", "10.0.26100", "", False)]
        for system, machine, release, version, mac_version, supported in cases:
            with self.subTest(system=system, machine=machine, version=version), patch.object(rb.platform, "system", return_value=system), patch.object(rb.platform, "machine", return_value=machine), patch.object(rb.platform, "release", return_value=release), patch.object(rb.platform, "version", return_value=version), patch.object(rb.platform, "mac_ver", return_value=(mac_version, (), "")):
                result = rb._host_info()
            self.assertEqual(result["playwright_official_os_support"], supported)
            self.assertIn("not target-machine tests", result["validation"])
            if not supported:
                self.assertTrue(result["warnings"])

    def test_utf8_subprocess_and_python_command_protocol(self):
        result = subprocess.CompletedProcess(["fake"], 0, "客户 路径", "")
        with patch.object(rb.subprocess, "run", return_value=result) as run:
            self.assertEqual(rb._run(["fake"]), "客户 路径")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")
        with self.simulated():
            report = self.bootstrap.inspect()
        self.assertEqual(report["commands"]["doctor_argv"][1:3], ["-X", "utf8"])
        self.assertEqual(report["commands"]["pipeline_argv_prefix"][1:3], ["-X", "utf8"])


if __name__ == "__main__":
    unittest.main()
