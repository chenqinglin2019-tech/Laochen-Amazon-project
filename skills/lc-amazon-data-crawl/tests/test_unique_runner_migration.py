from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import migrate_unique_runner as migration  # noqa: E402


class UniqueRunnerMigrationTests(unittest.TestCase):
    def fixture(self, root: Path):
        canonical = root / "lc-amazon-data-crawl-runner"
        opportunity = root / "Opportunity-Explorer"
        build = root / ".lc-amazon-data-crawl-runner.build-20260902"
        archive = root / "_archive" / "lc-amazon-data-crawl-legacy-20260902"
        for directory in (canonical, opportunity, build):
            directory.mkdir(parents=True)
        (canonical / "old.txt").write_text("old runner", encoding="utf-8")
        launcher = canonical / "lc-amazon-data-crawl.sh"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
        (canonical / "config.json").write_text(
            '{"backend_token":"must-not-be-hashed"}', encoding="utf-8"
        )
        config_dir = canonical / "config"
        config_dir.mkdir()
        (config_dir / "custom-provider.json").write_text(
            '{"api_key":"must-not-be-hashed"}', encoding="utf-8"
        )
        profile = opportunity / "chrome_profiles" / "legacy" / "Default"
        profile.mkdir(parents=True)
        (profile / "Cookies").write_text("must-not-be-read", encoding="utf-8")
        (opportunity / "result.jsonl").write_text("{}\n", encoding="utf-8")
        (build / "new.txt").write_text("new runner", encoding="utf-8")
        return canonical, opportunity, build, archive, launcher

    def test_success_archives_both_roots_and_promotes_only_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical, opportunity, build, archive, _launcher = self.fixture(root)
            hashed_paths = []
            real_hash = migration._sha256

            def record_hash(path: Path) -> str:
                hashed_paths.append(path)
                return real_hash(path)

            with patch.object(migration, "_sha256", side_effect=record_hash):
                manifest_path = migration.migrate(
                    workspace=root,
                    build_dir=build,
                    canonical_dir=canonical,
                    archive_dir=archive,
                    legacy_dirs=[canonical, opportunity],
                )

            self.assertEqual((canonical / "new.txt").read_text(), "new runner")
            self.assertFalse(build.exists())
            self.assertTrue((archive / "lc-amazon-data-crawl-runner" / "old.txt").is_file())
            self.assertTrue((archive / "Opportunity-Explorer" / "chrome_profiles").is_dir())
            archived_launcher = archive / "lc-amazon-data-crawl-runner" / "lc-amazon-data-crawl.sh"
            self.assertEqual(stat.S_IMODE(archived_launcher.stat().st_mode) & 0o111, 0)
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o700)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            listed_paths = [
                item["path"]
                for archived_root in payload["roots"]
                for item in archived_root["files"]
            ]
            self.assertNotIn("chrome_profiles/legacy/Default/Cookies", listed_paths)
            config_entry = next(
                item
                for archived_root in payload["roots"]
                for item in archived_root["files"]
                if item["path"] == "config.json"
            )
            self.assertNotIn("sha256", config_entry)
            self.assertTrue(
                all("chrome_profiles" not in str(path) for path in hashed_paths)
            )
            self.assertTrue(all(path.name != "config.json" for path in hashed_paths))
            self.assertTrue(
                all("config" not in path.parts for path in hashed_paths)
            )

    def test_failure_restores_paths_and_launcher_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical, opportunity, build, archive, launcher = self.fixture(root)
            original_mode = stat.S_IMODE(launcher.stat().st_mode)
            with patch.object(
                migration,
                "_write_json_atomic",
                side_effect=OSError("fixture write failure"),
            ):
                with self.assertRaisesRegex(OSError, "fixture write failure"):
                    migration.migrate(
                        workspace=root,
                        build_dir=build,
                        canonical_dir=canonical,
                        archive_dir=archive,
                        legacy_dirs=[canonical, opportunity],
                    )
            self.assertTrue(canonical.is_dir())
            self.assertTrue(opportunity.is_dir())
            self.assertTrue(build.is_dir())
            self.assertFalse(archive.exists())
            self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), original_mode)

    def test_interrupt_immediately_after_legacy_rename_restores_every_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical, opportunity, build, archive, launcher = self.fixture(root)
            original_mode = stat.S_IMODE(launcher.stat().st_mode)
            real_rename = migration.os.rename

            def interrupt_after_rename(source, destination):
                real_rename(source, destination)
                if Path(source).resolve() == canonical.resolve():
                    raise KeyboardInterrupt("fixture legacy rename interrupt")

            with patch.object(migration.os, "rename", side_effect=interrupt_after_rename):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "fixture legacy rename interrupt",
                ):
                    migration.migrate(
                        workspace=root,
                        build_dir=build,
                        canonical_dir=canonical,
                        archive_dir=archive,
                        legacy_dirs=[canonical, opportunity],
                    )

            self.assertTrue(canonical.is_dir())
            self.assertTrue(opportunity.is_dir())
            self.assertTrue(build.is_dir())
            self.assertFalse(archive.exists())
            self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), original_mode)

    def test_interrupt_immediately_after_build_promotion_restores_every_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical, opportunity, build, archive, launcher = self.fixture(root)
            original_mode = stat.S_IMODE(launcher.stat().st_mode)
            real_rename = migration.os.rename

            def interrupt_after_rename(source, destination):
                real_rename(source, destination)
                if Path(source).resolve() == build.resolve():
                    raise KeyboardInterrupt("fixture build promotion interrupt")

            with patch.object(migration.os, "rename", side_effect=interrupt_after_rename):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "fixture build promotion interrupt",
                ):
                    migration.migrate(
                        workspace=root,
                        build_dir=build,
                        canonical_dir=canonical,
                        archive_dir=archive,
                        legacy_dirs=[canonical, opportunity],
                    )

            self.assertTrue(canonical.is_dir())
            self.assertTrue(opportunity.is_dir())
            self.assertTrue(build.is_dir())
            self.assertFalse(archive.exists())
            self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), original_mode)

    def test_interrupt_immediately_after_archive_mkdir_removes_transaction_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical, opportunity, build, archive, launcher = self.fixture(root)
            original_mode = stat.S_IMODE(launcher.stat().st_mode)
            real_mkdir = migration.os.mkdir

            def interrupt_after_mkdir(path, mode=0o777, *args, **kwargs):
                real_mkdir(path, mode, *args, **kwargs)
                if Path(path).resolve() == archive.resolve():
                    raise KeyboardInterrupt("fixture archive mkdir interrupt")

            with patch.object(migration.os, "mkdir", side_effect=interrupt_after_mkdir):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "fixture archive mkdir interrupt",
                ):
                    migration.migrate(
                        workspace=root,
                        build_dir=build,
                        canonical_dir=canonical,
                        archive_dir=archive,
                        legacy_dirs=[canonical, opportunity],
                    )

            self.assertTrue(canonical.is_dir())
            self.assertTrue(opportunity.is_dir())
            self.assertTrue(build.is_dir())
            self.assertFalse(archive.exists())
            self.assertFalse(archive.parent.exists())
            self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), original_mode)

    def test_interrupt_after_first_launcher_chmod_restores_permissions_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical, opportunity, build, archive, launcher = self.fixture(root)
            original_mode = stat.S_IMODE(launcher.stat().st_mode)
            real_chmod = migration.os.chmod
            interrupted = False

            def interrupt_after_chmod(path, mode, *args, **kwargs):
                nonlocal interrupted
                real_chmod(path, mode, *args, **kwargs)
                candidate = Path(path)
                if (
                    not interrupted
                    and candidate.name == "lc-amazon-data-crawl.sh"
                    and archive.resolve() in candidate.resolve().parents
                ):
                    interrupted = True
                    raise KeyboardInterrupt("fixture launcher chmod interrupt")

            with patch.object(migration.os, "chmod", side_effect=interrupt_after_chmod):
                with self.assertRaisesRegex(
                    KeyboardInterrupt,
                    "fixture launcher chmod interrupt",
                ):
                    migration.migrate(
                        workspace=root,
                        build_dir=build,
                        canonical_dir=canonical,
                        archive_dir=archive,
                        legacy_dirs=[canonical, opportunity],
                    )

            self.assertTrue(canonical.is_dir())
            self.assertTrue(opportunity.is_dir())
            self.assertTrue(build.is_dir())
            self.assertFalse(archive.exists())
            self.assertFalse(archive.parent.exists())
            self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), original_mode)


if __name__ == "__main__":
    unittest.main()
