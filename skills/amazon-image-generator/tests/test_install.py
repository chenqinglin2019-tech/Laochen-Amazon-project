import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


class InstallerDependencyTests(unittest.TestCase):
    def run_installer(self, codex_home):
        env = dict(os.environ)
        env["CODEX_HOME"] = str(codex_home)
        return subprocess.run(
            ["bash", str(INSTALLER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

    def test_existing_ui_skill_is_not_reinstalled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)
            dependency = codex_home / "skills" / "ui-ux-pro-max"
            dependency.mkdir(parents=True)
            (dependency / "SKILL.md").write_text("installed", encoding="utf-8")

            result = self.run_installer(codex_home)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("UI dependency already installed", result.stdout)
            self.assertTrue(
                (codex_home / "skills" / "amazon-image-generator" / "SKILL.md").is_file()
            )

    def test_missing_ui_skill_uses_system_skill_installer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)
            helper = (
                codex_home
                / "skills"
                / ".system"
                / "skill-installer"
                / "scripts"
                / "install-skill-from-github.py"
            )
            helper.parent.mkdir(parents=True)
            helper.write_text(
                '''import os
from pathlib import Path
import sys

home = Path(os.environ["CODEX_HOME"])
target = home / "skills" / "ui-ux-pro-max"
target.mkdir(parents=True)
(target / "SKILL.md").write_text("installed", encoding="utf-8")
(home / "installer-args.txt").write_text(" ".join(sys.argv[1:]), encoding="utf-8")
''',
                encoding="utf-8",
            )

            result = self.run_installer(codex_home)

            self.assertEqual(result.returncode, 0, result.stderr)
            args = (codex_home / "installer-args.txt").read_text(encoding="utf-8")
            self.assertIn("nextlevelbuilder/ui-ux-pro-max-skill", args)
            self.assertIn(".claude/skills/ui-ux-pro-max", args)
            self.assertTrue((codex_home / "skills" / "ui-ux-pro-max" / "SKILL.md").is_file())

    def test_missing_system_installer_fails_with_recovery_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_installer(Path(temp_dir))

            self.assertEqual(result.returncode, 1)
            self.assertIn("Codex skill-installer is unavailable", result.stderr)
            self.assertIn("nextlevelbuilder/ui-ux-pro-max-skill", result.stderr)


if __name__ == "__main__":
    unittest.main()
