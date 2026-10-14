"""Offline regression runner; never starts the real-integration browser or uses live traffic state."""
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
import safety_control


def main():
    original_root = safety_control.default_safety_root
    original_home = Path.home()
    suite = unittest.TestSuite()
    for file in sorted((ROOT / "tests").glob("test_*.py")):
        if file.name != "test_browser_runtime_real_integration.py":
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(file.stem))
    log_path = ROOT / "outputs/non-browser-tests.log"
    log_path.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        # Respect tests' own isolated home fixtures, but protect the user's real
        # scheduler, locks and risk state when a test does not supply a fixture.
        def isolated_root():
            return original_root() if Path.home() != original_home else Path(temp) / "safety"
        with patch.object(safety_control, "default_safety_root", side_effect=isolated_root), \
                log_path.open("w", encoding="utf-8") as log, \
                contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            result = unittest.TextTestRunner(stream=log).run(suite)
    print(f"{result.testsRun} tests; {len(result.failures)} failures; {len(result.errors)} errors; {len(result.skipped)} skipped. Log: {log_path}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
