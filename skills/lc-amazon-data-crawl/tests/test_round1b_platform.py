"""Round-1b platform fixes (review P2-12a/b) for the Windows launcher.

P2-12a: `powershell -File` (the .cmd shim) splits `--config=C:\\x.json` at the drive
colon into `--config=C` and `\\x.json`; the launcher rebuilds it, or stops with
exit 40 and a hint when the path part is missing.
P2-12b: `Find-BasePython` falls back to `py -3` after the versioned probes, so a
py-launcher-only Python 3.14 is found.

Behaviour tests need PowerShell (pwsh on PATH or LC_TEST_PWSH) and a POSIX
shell for the fake executables; the static checks always run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import test_round1_platform as round1  # noqa: E402

PWSH = round1.PWSH
LAUNCHER_PS1 = round1.LAUNCHER_PS1
SCRIPTS_DIR = round1.SCRIPTS_DIR

FAKE_LOGGING_PYTHON = (
    "import json, os, sys\n"
    "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as handle:\n"
    "    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + '\\n')\n"
    "name = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else ''\n"
    "variable = {'safety_cli.py': 'FAKE_GUARD_EXIT', 'start_cdp_browser.py': 'FAKE_START_EXIT'}.get(name, 'FAKE_RUN_EXIT')\n"
    "raise SystemExit(int(os.environ.get(variable, '0')))\n"
)

# Mimics py.exe with a single installed Python: `-3` and `-3.<installed>` work,
# any other `-3.x` fails like "No suitable Python runtime found" (exit 103).
FAKE_PY_LAUNCHER = (
    "import json, os, sys\n"
    "from pathlib import Path\n"
    "args = sys.argv[1:]\n"
    "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as handle:\n"
    "    handle.write(json.dumps(['py'] + args) + '\\n')\n"
    "installed = os.environ['FAKE_PY_VERSION']\n"
    "if not args or args[0] not in ('-3', '-' + installed):\n"
    "    print('No suitable Python runtime found', file=sys.stderr)\n"
    "    raise SystemExit(103)\n"
    "rest = args[1:]\n"
    "if rest[:1] == ['-c']:\n"
    "    print(installed)\n"
    "    raise SystemExit(0)\n"
    "if rest[:2] == ['-m', 'venv'] and len(rest) == 3:\n"
    "    target = Path(rest[2]) / 'bin' / 'python'\n"
    "    target.parent.mkdir(parents=True)\n"
    "    target.write_text(os.environ['FAKE_VENV_PYTHON'], encoding='utf-8')\n"
    "    target.chmod(0o755)\n"
    "    raise SystemExit(0)\n"
    "raise SystemExit(1)\n"
)

# Mimics the Microsoft Store `python`/`python3` alias stubs.
FAKE_STORE_ALIAS = (
    "import json, os, sys\n"
    "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as handle:\n"
    "    handle.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + '\\n')\n"
    "print('Python was not found; run without arguments to install from the Microsoft Store', file=sys.stderr)\n"
    "raise SystemExit(9009 % 256)\n"
)


def python_script(body: str) -> str:
    return f"#!{sys.executable}\n" + body


def write_python_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(python_script(body), encoding="utf-8")
    path.chmod(0o755)


def launcher_text() -> str:
    return LAUNCHER_PS1.read_text(encoding="utf-8-sig")


class LauncherStaticTests(unittest.TestCase):
    def test_find_base_python_tries_py_3_after_the_versioned_probes(self) -> None:
        match = re.search(r"function Find-BasePython \{.*?foreach \(\$spec in @\(([^)]*)\)\)", launcher_text(), re.S)
        self.assertIsNotNone(match)
        specs = re.findall(r"'([^']+)'", match.group(1))
        self.assertEqual(specs, ["py -3.13", "py -3.12", "py -3.11", "py -3.10", "py -3", "python", "python3"])

    def test_setup_runner_probe_uses_the_py_launcher_first(self) -> None:
        text = (SCRIPTS_DIR / "setup_runner.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("foreach ($spec in @('py -3', 'python', 'python3'))", text)

    def test_split_config_is_repaired_before_any_command_runs(self) -> None:
        text = launcher_text()
        repair = text.index("$Rest = @(Repair-SplitConfigArgument $Rest)")
        self.assertLess(text.index("$Rest = @($args[1..($args.Count - 1)]"), repair)
        self.assertLess(repair, text.index("switch -Exact ($Command) {"))
        function = text.split("function Repair-SplitConfigArgument", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("exit 40", function)
        self.assertIn("--config <", function)


@unittest.skipUnless(PWSH, "PowerShell not available (set LC_TEST_PWSH)")
@unittest.skipIf(os.name == "nt", "fake executables need a POSIX shell")
class LauncherBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="启动器 round1b ")
        self.root = Path(self.temp.name)
        self.runner = self.root / "runner 数据抓取"
        (self.runner / "scripts").mkdir(parents=True)
        shutil.copy2(LAUNCHER_PS1, self.runner / "lc-amazon-data-crawl.ps1")
        self.auth_log = self.root / "auth-calls"
        (self.runner / "scripts" / "check_auth.ps1").write_text(
            "param([switch]$AllowRecent)\n"
            "Add-Content -LiteralPath $env:FAKE_AUTH_LOG -Value 'auth'\n"
            "exit 0\n",
            encoding="utf-8-sig",
        )
        self.log = self.root / "calls.jsonl"
        self.env = {k: v for k, v in os.environ.items() if k != "LC_AUTH_VERIFIED_AT"}
        self.env.update(FAKE_LOG=str(self.log), FAKE_AUTH_LOG=str(self.auth_log))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def ps(self, *args: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(self.runner / "lc-amazon-data-crawl.ps1"), *args],
            text=True, capture_output=True, env=env or self.env, timeout=120,
        )

    def calls(self) -> List[List[str]]:
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.log.unlink()
        return [[os.path.basename(entry[0])] + entry[1:] if entry else entry for entry in entries]

    # -- P2-12a ---------------------------------------------------------------

    def install_fake_venv(self) -> None:
        write_python_executable(self.runner / ".venv" / "bin" / "python", FAKE_LOGGING_PYTHON)

    def test_split_drive_config_is_rejoined_for_guard_browser_and_crawler(self) -> None:
        self.install_fake_venv()
        path = "C:\\Users\\a b\\数据\\x.json"
        result = self.ps("category-rank-run", "--config=" + path, "--operation-mode", "unattended",
                         env=dict(self.env, FAKE_RUN_EXIT="21"))
        self.assertEqual(result.returncode, 21, result.stderr)
        self.assertEqual(self.calls(), [
            ["safety_cli.py", "guard"],
            ["start_cdp_browser.py", "--if-needed", "--config", path],
            ["run_category_rank_crawl.py", "--config=" + path, "--operation-mode", "unattended"],
        ])

    def test_rejoin_covers_dry_runs_drive_relative_and_lowercase_paths(self) -> None:
        self.install_fake_venv()
        cases = [
            (("image-competitor-dry-run", "--config=c:/cfg dir/x.json"),
             [["run_amazon_image_competitor_crawl.py", "--dry-run", "--config=c:/cfg dir/x.json"]]),
            (("amazon-front-run", "--config=D:x.json", "--resume-after-review"),
             [["safety_cli.py", "guard"],
              ["start_cdp_browser.py", "--if-needed", "--config", "D:x.json"],
              ["run_amazon_front_crawl.py", "--config=D:x.json", "--resume-after-review"]]),
            (("sellersprite-check", "--config=C:\\a\\k.json", "--config=E:\\b\\k.json"),
             [["safety_cli.py", "guard"],
              ["start_cdp_browser.py", "--if-needed", "--config", "E:\\b\\k.json"],
              ["run_sellersprite_check.py", "--config=C:\\a\\k.json", "--config=E:\\b\\k.json"]]),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.ps(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), expected)

    def test_documented_and_colon_forms_are_unchanged(self) -> None:
        self.install_fake_venv()
        cases = [
            (("category-rank-dry-run", "--config", "C:\\x y\\c.json"),
             ["run_category_rank_crawl.py", "--dry-run", "--config", "C:\\x y\\c.json"]),
            (("category-rank-dry-run", "--config=config/s.json"),
             ["run_category_rank_crawl.py", "--dry-run", "--config=config/s.json"]),
            # PowerShell turns `--config:C:\x.json` into `--config` `C:\x.json`, which argparse accepts.
            (("category-rank-dry-run", "--config:C:\\x.json"),
             ["run_category_rank_crawl.py", "--dry-run", "--config", "C:\\x.json"]),
            (("category-rank-dry-run", "--config=C"),
             ["run_category_rank_crawl.py", "--dry-run", "--config=C"]),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.ps(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [expected])

    def test_unrecoverable_split_stops_with_config_error_before_anything_runs(self) -> None:
        self.install_fake_venv()
        for args in (("category-rank-run", "--config=C:", "--operation-mode", "unattended"),
                     ("amazon-front-dry-run", "--config=C:-x.json"),
                     ("image-competitor-run", "--config=C:", "--dry-run")):
            with self.subTest(args=args):
                result = self.ps(*args)
                self.assertEqual(result.returncode, 40, result.stdout + result.stderr)
                self.assertIn("--config <", result.stderr)
                self.assertIn("--config=C:", result.stderr)
                self.assertEqual(self.calls(), [])
        self.assertFalse(self.auth_log.exists())

    # -- P2-12b ---------------------------------------------------------------

    def install_env(self, version: str) -> Dict[str, str]:
        bindir = self.root / "bin"
        write_python_executable(bindir / "py", FAKE_PY_LAUNCHER)
        for alias in ("python", "python3"):
            write_python_executable(bindir / alias, FAKE_STORE_ALIAS)
        env = {
            "PATH": str(bindir),
            "HOME": os.environ.get("HOME", str(self.root)),
            "FAKE_LOG": str(self.log),
            "FAKE_AUTH_LOG": str(self.auth_log),
            "FAKE_PY_VERSION": version,
            "FAKE_VENV_PYTHON": python_script(FAKE_LOGGING_PYTHON),
        }
        for name in ("TMPDIR", "LANG", "LC_ALL"):
            if os.environ.get(name):
                env[name] = os.environ[name]
        return env

    def probe(self, selector: str) -> List[str]:
        return ["py", selector, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]

    def test_install_finds_py_launcher_only_python_314(self) -> None:
        result = self.ps("install", env=self.install_env("3.14"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        venv = str(self.runner / ".venv")
        calls = self.calls()
        self.assertEqual(calls[:6], [self.probe("-3.13"), self.probe("-3.12"), self.probe("-3.11"),
                                     self.probe("-3.10"), self.probe("-3"), ["py", "-3", "-m", "venv", venv]])
        self.assertEqual(calls[6], ["-m", "pip", "install", "--upgrade", "pip"])
        self.assertEqual(calls[7], ["-m", "pip", "install", "-r", str(self.runner / "requirements.txt")])
        self.assertEqual(len(calls), 9)
        self.assertNotIn("python", [call[0] for call in calls])

    def test_versioned_probe_still_wins_and_old_python_is_refused(self) -> None:
        result = self.ps("install", env=self.install_env("3.12"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(calls[2], ["py", "-3.12", "-m", "venv", str(self.runner / ".venv")])
        shutil.rmtree(self.runner / ".venv")
        result = self.ps("install", env=self.install_env("3.9"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Scrapling requires Python 3.10 or newer.", result.stderr)
        calls = self.calls()
        self.assertEqual(calls[4], self.probe("-3"))
        self.assertEqual([call[0] for call in calls[5:]], ["python", "python3"])
        self.assertFalse((self.runner / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
