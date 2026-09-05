import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_harness_app.py"
REMOVER = ROOT / "scripts" / "remove_harness_app.py"


class HarnessRemoverTests(unittest.TestCase):
    def install(self, apps_root):
        return subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--apps-root",
                str(apps_root),
                "--skip-harness-check",
                "--no-start",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def remove(self, apps_root):
        return subprocess.run(
            [
                sys.executable,
                str(REMOVER),
                "--apps-root",
                str(apps_root),
                "--skip-harness-check",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_remove_archives_entire_app_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            installed = self.install(apps_root)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            target = apps_root / "amazon-image-generator"
            token = target / "data" / "feiyushentu.toml"
            token.write_text('feiyushentu_token = "test-only-secret"\n', encoding="utf-8")
            database = target / "data" / "app.sqlite3"
            database.write_bytes(b"database-bytes")
            generated = target / "data" / "generated" / "result.png"
            generated.write_bytes(b"image-bytes")

            removed = self.remove(apps_root)

            self.assertEqual(removed.returncode, 0, removed.stderr)
            output = json.loads(removed.stdout)
            archive = Path(output["archive"])
            self.assertFalse(target.exists())
            self.assertTrue(archive.is_dir())
            self.assertEqual(
                (archive / "data" / "feiyushentu.toml").read_text(encoding="utf-8"),
                'feiyushentu_token = "test-only-secret"\n',
            )
            self.assertEqual((archive / "data" / "app.sqlite3").read_bytes(), b"database-bytes")
            self.assertEqual((archive / "data" / "generated" / "result.png").read_bytes(), b"image-bytes")
            self.assertTrue(output["data_preserved"])
            self.assertFalse(output["skill_removed"])
            self.assertFalse(output["host_ingress_changed"])

    def test_remove_is_idempotent_when_app_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            apps_root.mkdir()

            removed = self.remove(apps_root)

            self.assertEqual(removed.returncode, 0, removed.stderr)
            output = json.loads(removed.stdout)
            self.assertTrue(output["already_absent"])
            self.assertIsNone(output["archive"])

    def test_remove_rejects_a_different_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            target = apps_root / "amazon-image-generator"
            target.mkdir(parents=True)
            manifest = target / "app.json"
            original = '{"manifest": 1, "name": "其他应用", "entry": "index.html"}'
            manifest.write_text(original, encoding="utf-8")

            removed = self.remove(apps_root)

            self.assertEqual(removed.returncode, 1)
            self.assertIn("different custom app", removed.stderr)
            self.assertTrue(target.is_dir())
            self.assertEqual(manifest.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
