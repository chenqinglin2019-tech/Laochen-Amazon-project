"""Temporary release fixtures only; never package or read real credentials."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import build_release as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "skill"
        (self.root / "tools/bin").mkdir(parents=True)
        (self.root / "references").mkdir()
        self.hashes = {}
        for names in release.PLATFORM_BINARIES.values():
            for name in names:
                path = self.root / "tools/bin" / name
                path.write_bytes(name.encode())
                self.hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root / "references/auth-binaries.json").write_text(json.dumps({
            "schema": "LC-AUTH-BINARIES/1.0", "sha256": self.hashes,
        }))
        (self.root / "config.json").write_text("synthetic-local-token-never-package")
        self.out = Path(temporary.name) / "out"
        patch = mock.patch.object(release, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def test_selected_platforms_blank_token_and_unix_archive_modes(self):
        for platform in ["all", "mac", "win", "linux"]:
            with self.subTest(platform=platform):
                report = release.build(self.out, False, platform, platform)
                with zipfile.ZipFile(report["zip"]) as archive:
                    binaries = {Path(i.filename).name for i in archive.infolist() if "/tools/bin/" in i.filename}
                    expected = set(self.hashes) if platform == "all" else set(release.PLATFORM_BINARIES[platform])
                    self.assertEqual(binaries, expected)
                    for info in archive.infolist():
                        self.assertEqual(info.create_system, 3)
                        if "/tools/bin/" in info.filename:
                            self.assertEqual(info.external_attr >> 16 & 0o777, 0o755)
                    config = archive.getinfo(release.NAME + "/config.json")
                    self.assertEqual(config.external_attr >> 16 & 0o777, 0o600)
                    self.assertEqual(json.loads(archive.read(config)), {
                        "backend_url": "https://mcp.yixunkuajing.com", "backend_token": ""})

    def test_missing_selected_binary_refuses_release(self):
        (self.root / "tools/bin/lc-auth-check-linux-amd64").unlink()
        with self.assertRaisesRegex(SystemExit, "Missing auth binary"):
            release.build(self.out, False, "all", "missing")
        self.assertFalse(self.out.exists())
        release.build(self.out, False, "mac", "mac-is-complete")

    def test_wrong_hash_or_symlink_refuses_release(self):
        path = self.root / "tools/bin/lc-auth-check-darwin-arm64"
        path.write_bytes(b"wrong bytes")
        with self.assertRaisesRegex(SystemExit, "hash mismatch"):
            release.build(self.out, False, "mac", "bad-hash")
        outside = self.root / "outside"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaisesRegex(SystemExit, "Missing auth binary"):
            release.build(self.out, False, "mac", "symlink")


if __name__ == "__main__":
    unittest.main()
