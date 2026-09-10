"""Platform boundary regressions; simulated paths do not certify a foreign OS."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

import lc_layout as layout


class PlatformRenderTests(unittest.TestCase):
    def test_renderer_json_pipe_is_explicit_utf8_for_non_ascii_inputs(self):
        with tempfile.TemporaryDirectory(prefix="studio-unicode-") as temp:
            base = Path(temp) / "产品图片 café"
            base.mkdir()
            Image.new("RGB", (1000, 1000), "white").save(base / "源图.png")
            job = {"id": "unicode", "kind": "listing", "canvas": [1000, 1000],
                   "layout_input": "源图.png", "language": "en",
                   "layout": {"template": "scene", "headline": "Café™ 日常门铃"}}
            runtime = {"passed": True, "errors": [], "node": "C:/Node With Spaces/node.exe",
                       "modules": "C:/运行时/node_modules", "chromium": "C:/Browser/chrome.exe",
                       "versions": {}}

            def renderer(argv, **kwargs):
                self.assertEqual(kwargs.get("encoding"), "utf-8")
                self.assertTrue(kwargs.get("text"))
                self.assertEqual(argv[0], runtime["node"])
                payload = json.loads(kwargs["input"])
                self.assertEqual(payload["jobs"][0]["headline"], "Café™ 日常门铃")
                self.assertIn("产品图片 café", payload["output_dir"])
                result = {"unicode": {"passed": True, "output_path": None,
                                      "checks": [], "bboxes": [], "runtime": {}}}
                return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

            with patch.object(layout, "doctor", return_value=runtime), \
                    patch.object(layout, "_font_payload", return_value=([], [])), \
                    patch.object(layout.subprocess, "run", side_effect=renderer) as run:
                result = layout.render_batch({}, base, [job], measure_only=True)
            self.assertTrue(result["unicode"]["passed"])
            self.assertEqual(run.call_count, 1)
            self.assertFalse((base / "review").exists())

    def test_browser_discovery_covers_current_and_legacy_desktop_package_names(self):
        # These are actual package names from Playwright's registry, represented
        # with native temp paths so the same test itself can run on all hosts.
        packages = [
            ("windows-current", "local/ms-playwright/chromium_headless_shell-1228/"
             "chrome-headless-shell-win64/chrome-headless-shell.exe"),
            ("windows-legacy", "local/ms-playwright/chromium_headless_shell-1228/"
             "chrome-headless-shell-win64/headless_shell.exe"),
            ("mac-intel", "Library/Caches/ms-playwright/chromium-1228/chrome-mac-x64/"
             "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
            ("mac-apple-silicon", "Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/"
             "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
            ("mac-legacy", "Library/Caches/ms-playwright/chromium-1228/chrome-mac/"
             "Chromium.app/Contents/MacOS/Chromium"),
            ("mac-headless", "Library/Caches/ms-playwright/chromium_headless_shell-1228/"
             "chrome-headless-shell-mac-arm64/chrome-headless-shell"),
        ]
        lock = json.loads((layout.ASSETS / "layout-runtime.json").read_text(encoding="utf-8"))
        for label, relative in packages:
            with self.subTest(platform_package=label), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                node = base / "Node With Spaces/node.exe"
                browser = base / relative
                modules = base / "运行时/node_modules"
                node.parent.mkdir(parents=True)
                node.touch()
                browser.parent.mkdir(parents=True)
                browser.touch()
                package = modules / "playwright/package.json"
                package.parent.mkdir(parents=True)
                package.write_text(json.dumps({"version": lock["playwright_version"]}), encoding="utf-8")

                def version(argv, **kwargs):
                    return "v24.21.0" if Path(argv[0]) == node else "Chromium " + lock["chromium_version"]

                selected_env = {"LC_LAYOUT_NODE": str(node), "LC_LAYOUT_NODE_MODULES": str(modules),
                                "LOCALAPPDATA": str(base / "local")}
                with patch.dict(os.environ, selected_env, clear=True), \
                        patch.object(Path, "home", return_value=base), \
                        patch.object(layout.shutil, "which", return_value=None), \
                        patch.object(layout.subprocess, "check_output", side_effect=version):
                    result = layout._discover_runtime()
                self.assertTrue(result["passed"], result["errors"])
                self.assertEqual(Path(result["chromium"]), browser)


if __name__ == "__main__":
    unittest.main()
