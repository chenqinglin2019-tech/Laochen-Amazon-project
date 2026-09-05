import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_harness_app.py"
SOURCE_CLI = ROOT / "scripts" / "feiyushentu_amazon.py"


class HarnessInstallerTests(unittest.TestCase):
    def run_installer(self, apps_root, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--apps-root",
                str(apps_root),
                "--skip-harness-check",
                "--no-start",
                *extra,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_fresh_install_uses_verified_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            result = self.run_installer(apps_root)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            target = apps_root / "amazon-image-generator"
            manifest = json.loads((target / "app.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "飞鱼神图")
            self.assertEqual(manifest["visibility"], "root")
            self.assertNotIn("icon", manifest)
            self.assertEqual(output["entry"], "/custom/apps/amazon-image-generator/index.html")
            self.assertFalse(output["backend_started"])
            self.assertTrue((target / "web" / "index.html").is_file())
            self.assertTrue((target / "backend" / "server.py").is_file())
            self.assertEqual(
                (target / "backend" / "vendor" / SOURCE_CLI.name).read_bytes(),
                SOURCE_CLI.read_bytes(),
            )
            self.assertTrue((target / "data" / "uploads").is_dir())
            self.assertTrue((target / "data" / "generated").is_dir())

    def test_update_preserves_token_and_data_and_creates_code_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            first = self.run_installer(apps_root)
            self.assertEqual(first.returncode, 0, first.stderr)
            target = apps_root / "amazon-image-generator"
            token = target / "data" / "feiyushentu.toml"
            token.write_text('feiyushentu_token = "test-only-secret"\n', encoding="utf-8")
            token.chmod(0o600)
            database = target / "data" / "app.sqlite3"
            database.write_bytes(b"existing-database")
            (target / "web" / "index.html").write_text("old code", encoding="utf-8")

            second = self.run_installer(apps_root)

            self.assertEqual(second.returncode, 0, second.stderr)
            output = json.loads(second.stdout)
            backup = Path(output["backup"])
            self.assertTrue((backup / "web" / "index.html").is_file())
            self.assertEqual(token.read_text(encoding="utf-8"), 'feiyushentu_token = "test-only-secret"\n')
            self.assertEqual(stat.S_IMODE(token.stat().st_mode), 0o600)
            self.assertEqual(database.read_bytes(), b"existing-database")
            self.assertNotEqual((target / "web" / "index.html").read_text(encoding="utf-8"), "old code")
            self.assertTrue(output["data_preserved"])
            self.assertFalse(output["token_copied"])

    def test_different_existing_app_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            target = apps_root / "amazon-image-generator"
            target.mkdir(parents=True)
            manifest = target / "app.json"
            original = '{"manifest": 1, "name": "其他应用", "entry": "index.html"}'
            manifest.write_text(original, encoding="utf-8")

            result = self.run_installer(apps_root)

            self.assertEqual(result.returncode, 1)
            self.assertIn("different custom app", result.stderr)
            self.assertEqual(manifest.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
