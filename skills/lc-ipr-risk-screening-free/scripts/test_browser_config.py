"""Offline browser reuse fingerprints must never depend on local credentials."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_browser_plan as browser


class BrowserConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="ipr-browser-config-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cdp = self.root / "tools" / "cdp" / "cdp-cli.mjs"
        self.cdp.parent.mkdir(parents=True)
        self.cdp.write_text("// fixture browser implementation\n")
        (self.cdp.parent / "registry-adapters.mjs").write_text("// fixture adapter\n")
        self.runtime = self.root / "references" / "runtime-config.json"
        self.runtime.parent.mkdir()
        self.runtime.write_text('{"cdp":{"operation_timeout_ms":1000}}')
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ("workflow_v24.py", "run_browser_plan.py", "provider_utils.py",
                     "record_uspto_patent_chrome_verification.py"):
            (scripts / name).write_text("# fixture Python implementation\n")
        for name, value in (("ROOT", self.root), ("CDP", self.cdp)):
            patcher = patch.object(browser, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_credentials_never_affect_legacy_or_corrected_fingerprints(self):
        for corrected in (False, True):
            with self.subTest(corrected=corrected), patch.object(browser, "correction_enabled", return_value=corrected):
                original = browser.browser_implementation_digest({})
                for name in ("config.json", ".env", "config.local.json"):
                    credential = self.root / name
                    credential.write_text("fixture-only credentials A")
                    self.assertEqual(original, browser.browser_implementation_digest({}))
                    credential.write_text("fixture-only credentials B")
                    self.assertEqual(original, browser.browser_implementation_digest({}))
                    credential.unlink()
                    self.assertEqual(original, browser.browser_implementation_digest({}))

    def test_runtime_changes_invalidate_legacy_and_corrected_fingerprints(self):
        for corrected in (False, True):
            with self.subTest(corrected=corrected), patch.object(browser, "correction_enabled", return_value=corrected):
                original = browser.browser_implementation_digest({})
                self.runtime.write_text('{"cdp":{"operation_timeout_ms":2000}}')
                self.assertNotEqual(original, browser.browser_implementation_digest({}))
                self.runtime.write_text('{"cdp":{"operation_timeout_ms":1000}}')
                self.assertEqual(original, browser.browser_implementation_digest({}))

    def test_browser_and_corrected_python_changes_still_invalidate_reuse(self):
        with patch.object(browser, "correction_enabled", return_value=True):
            original = browser.browser_implementation_digest({})
            self.cdp.write_text("// changed browser implementation\n")
            browser_changed = browser.browser_implementation_digest({})
            self.assertNotEqual(original, browser_changed)
            (self.root / "scripts" / "provider_utils.py").write_text("# changed Python implementation\n")
            self.assertNotEqual(browser_changed, browser.browser_implementation_digest({}))


if __name__ == "__main__":
    unittest.main()
