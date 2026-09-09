"""Isolated packaging regressions: no production credentials, UI, or network."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import package_skill as package


class PackageSkillTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(package.os.environ, {}, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "sender"
        self.source.mkdir()
        self.output = self.base / "recipient"
        self.spec = self.base / "allowlist.json"
        self.files = {
            "SKILL.md": b"# Portable skill\n",
            ".env.example": b"SERPER_API_KEY=\n",
            "config.example.json": b'{"backend_url":"https://example.invalid","backend_token":""}\n',
            "scripts/example.py": b"print('ready')\n",
        }
        for name, value in self.files.items():
            self.put(name, value)
        self.entries = [self.entry(name) for name in self.files]
        self.write_spec()

    def entry(self, name, **extra):
        return {"path": name, "kind": "text", "required": True, "mode": "0644", **extra}

    def put(self, name, value):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def write_spec(self):
        self.spec.write_text(json.dumps({"schema": package.SCHEMA, "package_name": "portable-skill", "files": self.entries}))

    def build(self, **kwargs):
        return package.package_skill(self.source, self.output, allowlist_path=self.spec, **kwargs)

    def blocked(self, code, **kwargs):
        with self.assertRaisesRegex(package.PackageError, code):
            self.build(**kwargs)
        self.assertFalse(self.output.exists() and list(self.output.iterdir()))

    def test_only_allowlist_with_empty_templates_manifest_hashes_and_modes(self):
        secret = "offline-Fabricated-Credential-9281"
        self.put(".env", ("SERPER_API_KEY="+secret).encode())
        for name in ["config.json", "config.local.json", "runs-free/private/evidence.json",
                     ".venv/private", "tools/cdp/node_modules/private", "unknown.txt"]:
            self.put(name, b"private runtime data")
        # Private JSON references must parse, but their contents never enter stage.
        self.put("config.json", b'{"backend_token":"offline-synthetic-token-47382"}')
        self.put("config.local.json", b"{}")
        before = {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.source.rglob("*") if p.is_file()}
        self.entries[-1]["mode"] = "0755"; self.write_spec()
        result = self.build()
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertEqual(set(archive.namelist()), {"portable-skill/"+n for n in self.files} |
                             {"portable-skill/"+package.MANIFEST, "portable-skill/.env"})
            manifest = json.loads(archive.read("portable-skill/"+package.MANIFEST))
            for row in manifest["files"]:
                content = archive.read("portable-skill/"+row["path"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
                self.assertEqual(len(content), row["bytes"])
                self.assertNotIn(secret.encode(), content)
            self.assertEqual((archive.getinfo("portable-skill/scripts/example.py").external_attr >> 16) & 0o777, 0o755)
            generated = archive.read("portable-skill/.env")
            self.assertEqual(generated, self.files[".env.example"])
            self.assertFalse(any(package._env_values(generated).values()))
            self.assertEqual((archive.getinfo("portable-skill/.env").external_attr >> 16) & 0o777, 0o600)
            row = next(r for r in manifest["files"] if r["path"] == ".env")
            self.assertEqual(row["generated_from"], ".env.example")
        after = {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.source.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual([Path(result["archive"])], [p.resolve() for p in self.output.iterdir()])

    def test_required_missing_fails_without_final_or_stage(self):
        (self.source / "scripts/example.py").unlink()
        self.blocked("REQUIRED_DISTRIBUTION_FILE_MISSING")

    def test_empty_env_is_generated_even_without_sender_env(self):
        self.assertFalse((self.source / ".env").exists())
        result = self.build()
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertEqual(archive.read("portable-skill/.env"), self.files[".env.example"])
        self.assertFalse((self.source / ".env").exists())

    def test_generated_env_needs_an_allowlisted_template(self):
        self.entries = [self.entry("SKILL.md")]; self.write_spec()
        result = self.build()
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertNotIn("portable-skill/.env", archive.namelist())

    def test_unknown_files_never_read_or_staged(self):
        self.put("unknown-credentials.txt", b"do not read")
        original = package._read_regular
        with patch.object(package, "_read_regular", side_effect=lambda root, rel:
                          self.fail("unknown read") if rel == "unknown-credentials.txt" else original(root, rel)):
            self.build()

    def test_private_paths_refused_even_when_explicitly_allowlisted(self):
        for name in [".env", "config.json", "config.local.json", "nested/.ENV", "reports/report.md",
                     ".venv/bin/python", "tools/cdp/node_modules/a.js", "state/evidence.json", "q/a.log"]:
            with self.subTest(name=name):
                self.entries = [self.entry(name)]; self.write_spec()
                self.blocked("PRIVATE_OR_RUNTIME_PATH_FORBIDDEN")

    def test_traversal_glob_windows_paths_and_case_collisions_refused(self):
        for name in [".", "../private", "/private", "C:\\private", "scripts/*.py", "a/../b", "CON.txt", "a."]:
            with self.subTest(name=name):
                self.entries = [self.entry(name)]; self.write_spec()
                self.blocked("INVALID_DISTRIBUTION_PATH")
        self.entries = [self.entry("SKILL.md"), self.entry("skill.MD")]; self.write_spec()
        self.blocked("DUPLICATE_DISTRIBUTION_PATH")

    def test_symlink_file_and_parent_refused(self):
        target = self.put("outside.txt", b"private")
        for directory in [False, True]:
            with self.subTest(directory=directory):
                link = self.source / ("linkdir" if directory else "link")
                try:
                    link.symlink_to(target.parent if directory else target, target_is_directory=directory)
                except (OSError, NotImplementedError):
                    self.skipTest("Host cannot create symlinks")
                self.entries = [self.entry("linkdir/outside.txt" if directory else "link")]; self.write_spec()
                self.blocked("DISTRIBUTION_SYMLINK_FORBIDDEN")

    def test_hardlink_alias_refused(self):
        import os
        target = self.put("private.dat", b"private")
        os.link(target, self.source / "alias.txt")
        self.entries = [self.entry("alias.txt")]; self.write_spec()
        self.blocked("DISTRIBUTION_FILE_TYPE_FORBIDDEN")

    def test_populated_templates_rejected_even_short_value(self):
        self.put(".env.example", b"SERPER_API_KEY=x\n")
        self.blocked("POPULATED_CREDENTIAL_TEMPLATE")
        self.put(".env.example", b"SERPER_API_KEY=\n")
        self.put("config.example.json", b'{"backend_url":"https://example.invalid","backend_token":"x"}')
        self.blocked("POPULATED_OR_INVALID_CONFIG_TEMPLATE")

    def test_case_variant_template_cannot_bypass_empty_check(self):
        self.put("examples/.ENV.EXAMPLE", b"SERPER_API_KEY=x\n")
        self.entries = [self.entry("examples/.ENV.EXAMPLE")]; self.write_spec()
        self.blocked("POPULATED_CREDENTIAL_TEMPLATE")

    def test_known_secret_in_public_text_fails_without_disclosure(self):
        secret = "offline-Captured-Token-A1b2c3d4"
        self.put(".env", ("SERPER_API_KEY="+secret).encode())
        self.put("SKILL.md", ("accidental copy: "+secret).encode())
        with self.assertRaises(package.PackageError) as caught:
            self.build()
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("SECRET_DETECTED", str(caught.exception))
        self.assertEqual([], list(self.output.iterdir()))

    def test_low_entropy_reference_does_not_false_positive_in_source(self):
        self.put(".env", b"SERPER_API_KEY=x\n")
        self.put("scripts/example.py", b"x = 'xxxxxxxxxxxxxxxxxxxxxxxxxx'\n")
        self.build()

    def test_bom_crlf_templates_and_private_reference_are_supported(self):
        self.put(".env.example", b"\xef\xbb\xbf# Example\r\nSERPER_API_KEY=\r\n")
        self.put("config.example.json", b'\xef\xbb\xbf{"backend_url":"https://example.invalid","backend_token":""}\r\n')
        self.put(".env", b"\xef\xbb\xbfSERPER_API_KEY=synthetic-BOM-Key-92813\r\n")
        self.build()

    def test_backend_environment_token_is_memory_only_and_detects_leak(self):
        secret = "offline-Environment-Token-73482"
        self.put("SKILL.md", secret.encode())
        with patch.dict(package.os.environ, {"LAOCHEN_BACKEND_TOKEN": secret}):
            self.blocked("SECRET_DETECTED")

    def test_known_secret_utf16_in_platform_binary_rejected(self):
        secret = "Synthetic-UTF16-Key-8392"
        name = "tools/bin/lc-ipr-auth-check-windows-amd64.exe"
        self.put(name, b"MZ"+secret.encode("utf-16-le"))
        self.entries = [self.entry(name, kind="binary", mode="0755")]; self.write_spec()
        self.blocked("SECRET_DETECTED", known_secrets=[secret])

    def test_sensitive_json_state_and_unknown_binary_rejected(self):
        self.put("fixture.json", b'{"schema":"SERPER-ACCOUNT-CAPTURE/1.0","account_fingerprint":"a"}')
        self.entries = [self.entry("fixture.json")]; self.write_spec()
        self.blocked("ACCOUNT_OR_EVIDENCE_STATE_FORBIDDEN")
        self.entries = [self.entry("fixture.json", kind="binary")]; self.write_spec()
        self.blocked("UNSUPPORTED_DISTRIBUTION_BINARY")

    def test_sender_paths_and_unknown_profile_paths_rejected(self):
        for value in [str(self.source), str(Path.home()), "/"+"Users/alice/private", "C:"+"\\Users\\Alice\\private"]:
            with self.subTest(value=value):
                self.put("SKILL.md", value.encode())
                self.blocked("SENDER_MACHINE_PATH_DETECTED")

    def test_sender_build_paths_in_platform_binaries_rejected(self):
        name = "tools/bin/lc-ipr-auth-check-windows-amd64.exe"
        self.entries = [self.entry(name, kind="binary", mode="0755")]; self.write_spec()
        for encoding in ("utf-8", "utf-16-le"):
            with self.subTest(encoding=encoding):
                self.put(name, b"MZ\x00"+("C:"+"\\Users\\Builder\\private").encode(encoding))
                self.blocked("SENDER_MACHINE_PATH_DETECTED")

    def test_malformed_allowlist_is_safely_rejected(self):
        for spec in ({"schema": package.SCHEMA, "package_name": None, "files": self.entries},
                     {"schema": package.SCHEMA, "package_name": "portable", "files": [self.entry("SKILL.md", kind=[])]}):
            with self.subTest(spec=spec):
                self.spec.write_text(json.dumps(spec))
                self.blocked("INVALID_DISTRIBUTION_(ALLOWLIST|ENTRY)")

    def test_history_transform_is_staged_only_and_command_not_executable(self):
        path = "/"+"Users/sender/private-backup/restore.py"
        original = ("# History\n2026-09-06 evidence unchanged.\n[Restore]("+path+")\n"
                    "```bash\npython3 "+path+" --verify-only\n```\n").encode()
        self.put(package.HISTORY_PATH, original)
        self.entries.append(self.entry(package.HISTORY_PATH, transform=package.HISTORY_TRANSFORM)); self.write_spec()
        result = self.build()
        self.assertEqual(original, (self.source/package.HISTORY_PATH).read_bytes())
        with zipfile.ZipFile(result["archive"]) as archive:
            text = archive.read("portable-skill/"+package.HISTORY_PATH).decode()
        self.assertNotIn(path, text)
        self.assertNotIn("python3 ", text)
        self.assertIn("2026-09-06 evidence unchanged", text)
        self.assertIn("不适用于接收者环境", text)

    def test_transform_cannot_hide_a_secret_or_target_arbitrary_file(self):
        secret = "synthetic-Secret-Embedded-1234"
        self.put(package.HISTORY_PATH, ("/"+"Users/sender/"+secret).encode())
        self.entries = [self.entry(package.HISTORY_PATH, transform=package.HISTORY_TRANSFORM)]; self.write_spec()
        self.blocked("SECRET_DETECTED", known_secrets=[secret])
        self.entries = [self.entry("SKILL.md", transform=package.HISTORY_TRANSFORM)]; self.write_spec()
        self.blocked("UNSUPPORTED_DISTRIBUTION_TRANSFORM")

    def test_output_cannot_be_in_source_or_overwrite_existing_delivery(self):
        with self.assertRaisesRegex(package.PackageError, "OUTPUT_MUST_BE_OUTSIDE_SOURCE"):
            package.package_skill(self.source, self.source/"dist", allowlist_path=self.spec)
        result = self.build(); path = Path(result["archive"]); original = path.read_bytes()
        with self.assertRaisesRegex(package.PackageError, "OUTPUT_ALREADY_EXISTS"):
            self.build()
        self.assertEqual(original, path.read_bytes())

    def test_atomic_publication_failure_and_race_never_expose_partial_zip(self):
        with patch.object(package.os, "link", side_effect=OSError("private exception details")):
            self.blocked("ATOMIC_PUBLICATION_UNAVAILABLE")
        def race(source, destination):
            Path(destination).write_bytes(b"existing delivery")
            raise FileExistsError()
        with patch.object(package.os, "link", side_effect=race):
            with self.assertRaisesRegex(package.PackageError, "OUTPUT_ALREADY_EXISTS"):
                self.build()
        self.assertEqual(["portable-skill.zip"], [p.name for p in self.output.iterdir()])
        self.assertEqual(b"existing delivery", (self.output/"portable-skill.zip").read_bytes())

    def test_source_change_during_staging_fails(self):
        original = package._transform
        def changed(relative, content, transform):
            if relative == "scripts/example.py":
                self.put(relative, b"changed concurrently")
            return original(relative, content, transform)
        with patch.object(package, "_transform", side_effect=changed):
            self.blocked("SOURCE_CHANGED_DURING_PACKAGE")

    def test_cli_errors_are_json_and_do_not_print_secret(self):
        secret = "offline-Cli-Secret-Z987654"
        self.put(".env", ("SERPER_API_KEY="+secret).encode())
        self.put("SKILL.md", secret.encode())
        output = io.StringIO()
        argv = ["package_skill.py", "--source-root", str(self.source), "--output-dir", str(self.output), "--allowlist", str(self.spec)]
        with patch("sys.argv", argv), contextlib.redirect_stdout(output):
            status = package.main()
        self.assertEqual(2, status)
        self.assertEqual("blocked", json.loads(output.getvalue())["status"])
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
