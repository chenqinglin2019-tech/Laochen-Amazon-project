"""Cross-host contract simulations, not a claim of native Windows validation."""
from __future__ import annotations

import os
import json
from pathlib import Path, PureWindowsPath
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import lc_command_diagnostics as diagnostics
import lc_assets as assets
import lc_delivery as delivery
import lc_image_pipeline as pipeline
import lc_style_reference as style
import lc_transactions as transactions
import lc_workflow as workflow


class ResolvedWindowsPath(PureWindowsPath):
    """Pure Windows lexical semantics without touching the host filesystem."""
    def resolve(self, **kwargs):
        return self


class WindowsOSView:
    name = "nt"
    sep = "\\"

    def __getattr__(self, name):
        return getattr(os, name)


class WindowsPathContractTests(unittest.TestCase):
    def test_cli_json_protocol_configures_utf8_without_changing_auth(self):
        stdout, stderr = Mock(), Mock()
        with patch.object(pipeline.sys, "stdout", stdout), \
                patch.object(pipeline.sys, "stderr", stderr), \
                patch.object(pipeline, "parser") as parser, \
                patch.object(diagnostics, "run_observed_command", return_value=0) as observed:
            self.assertEqual(pipeline.main(), 0)
        stdout.reconfigure.assert_called_once_with(encoding="utf-8")
        stderr.reconfigure.assert_called_once_with(encoding="utf-8")
        self.assertEqual(observed.call_args.args[0], parser.return_value.parse_args.return_value)

    def test_persisted_relative_path_uses_portable_slashes(self):
        base = ResolvedWindowsPath(r"C:\Users\Studio User\图片项目")
        self.assertEqual(pipeline.relpath(base / "review" / "layouts" / "a.png", base),
                         "review/layouts/a.png")

    def test_artifact_owner_accepts_windows_and_portable_relative_paths(self):
        manifest = {"jobs": [{"id": "a", "raw_output": "raw/a.png", "final_output": "final/a.jpg"},
                             {"id": "a-b"}]}
        paths = [("raw/a.png", "a"), ("final/a.jpg", "a"), ("review/layouts/a.png", "a"),
                 ("review/layouts/a-b.png", "a-b"), ("review/details/a/detail.png", "a"),
                 ("review/submissions/a-proof.json", "a"), ("title_effects/a/candidate.png", "a")]
        with patch.object(transactions, "Path", PureWindowsPath):
            for relative, expected in paths:
                for spelling in (relative, relative.replace("/", "\\")):
                    with self.subTest(relative=spelling):
                        self.assertEqual(transactions._artifact_owner(spelling, manifest), expected)

    def test_output_mapping_accepts_case_and_separator_variants_on_windows(self):
        source = PureWindowsPath(r"C:\Work\图片\stage")
        target = PureWindowsPath(r"C:\Work\图片\project")
        inputs = [r"C:\Work\图片\stage\review\a.png", "C:/Work/图片/stage/review/a.png",
                  r"c:\work\图片\STAGE\review\a.png"]
        # Patch this module's os view, not global os.name/Path filesystem flavor.
        with patch.object(transactions, "os", SimpleNamespace(sep="\\", name="nt")):
            for original in inputs:
                with self.subTest(original=original):
                    mapped = transactions._map_outputs({"output_path": original}, source, target)
                    self.assertEqual(PureWindowsPath(mapped["output_path"]), target / "review/a.png")
            untouched = r"C:\Work\图片\stage-other\review\a.png"
            self.assertEqual(transactions._map_outputs({"output_path": untouched}, source, target),
                             {"output_path": untouched})

    def test_decoded_json_rebases_root_paths_and_path_keys(self):
        for source, target, os_view in (
                (PureWindowsPath(r"C:\Work\图片\stage"), PureWindowsPath(r"C:\Work\图片\project"), WindowsOSView()),
                (Path("/tmp/Windows\\style/stage"), Path("/tmp/Windows\\style/project"), os)):
            with self.subTest(source=source), patch.object(transactions, "os", os_view):
                old_path, new_path = str(source / "review/a.png"), str(target / "review/a.png")
                payload = {"output_dir": str(source), "files": {old_path: "same-sha"}}
                output = transactions._canonicalize_text(json.dumps(payload), source, target)
                self.assertEqual(json.loads(output), {"output_dir": str(target), "files": {new_path: "same-sha"}})
                self.assertEqual(transactions._canonicalize_text(output, source, target), output)

    def test_windows_staging_errors_share_the_same_diagnostic_key(self):
        base = ResolvedWindowsPath(r"C:\Work\图片项目")
        with patch.object(diagnostics, "Path", ResolvedWindowsPath):
            for separator in ("\\", "/"):
                errors = [f"Missing source: {base}{separator}.lc-transactions{separator}tx-{number}{separator}workspace{separator}source.png"
                          for number in (1, 2)]
                normalized = [diagnostics._normalized_error(error, base) for error in errors]
                self.assertEqual(normalized[0], normalized[1])
                self.assertNotIn(".lc-transactions", normalized[0])
            foreign = r"Missing source: C:\Other Project\.lc-transactions\tx-1\workspace\source.png"
            self.assertEqual(diagnostics._normalized_error(foreign, base), foreign)


class WindowsLockSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-win-lock-simulation-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "project_manifest.json"
        self.events = []

    def module(self, *, contention=False):
        attempts = 0
        def locking(descriptor, kind, length):
            nonlocal attempts
            self.assertEqual(length, 1)
            self.assertEqual(os.lseek(descriptor, 0, os.SEEK_CUR), 0)
            self.assertGreaterEqual(os.fstat(descriptor).st_size, 1)
            self.events.append(kind)
            if kind == 1:
                attempts += 1
                if contention and attempts == 1:
                    raise OSError("Simulated lock contention")
        return SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)

    def test_manifest_windows_lock_retries_same_byte_and_releases(self):
        with patch.dict(sys.modules, {"msvcrt": self.module(contention=True)}), \
                patch.object(workflow, "os", SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)), \
                patch.object(workflow.time, "sleep") as sleep, \
                patch.object(transactions, "recover_pending") as recovery:
            with workflow.manifest_lock(self.path):
                self.assertEqual(self.events, [1, 1])
            recovery.assert_called_once_with(self.path)
            sleep.assert_called_once_with(.05)
        self.assertEqual(self.events, [1, 1, 2])

    def test_manifest_windows_lock_releases_when_recovery_fails(self):
        with patch.dict(sys.modules, {"msvcrt": self.module()}), \
                patch.object(workflow, "os", SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)), \
                patch.object(transactions, "recover_pending", side_effect=ValueError("recovery refused")):
            with self.assertRaisesRegex(ValueError, "recovery refused"):
                with workflow.manifest_lock(self.path):
                    self.fail("Unsafe recovery must not enter operation")
        self.assertEqual(self.events, [1, 2])

    def test_delivery_windows_selection_lock_releases_on_error(self):
        with patch.dict(sys.modules, {"msvcrt": self.module()}), patch.object(style, "fcntl", None):
            with self.assertRaisesRegex(ValueError, "body failed"):
                with style._selection_lock(self.path):
                    raise ValueError("body failed")
        self.assertEqual(self.events, [1, 2])


class PortableFilesystemTests(unittest.TestCase):
    def test_windows_hash_cache_detects_same_size_change_with_restored_mtime(self):
        with tempfile.TemporaryDirectory(prefix="lc-win-hash-simulation-") as temporary:
            source = Path(temporary) / "source.bin"
            source.write_bytes(b"old pixels")
            original = source.stat()
            def windows_token(stat):
                # Python 3.12 Windows ctime is creation time, not modification.
                return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, original.st_ctime_ns)
            with patch.object(assets, "os", WindowsOSView()), \
                    patch.object(assets, "_file_token", side_effect=windows_token), assets.file_hash_context(fresh=True):
                before = assets.file_hash(source)
                source.write_bytes(b"new pixels")
                os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
                after = assets.file_hash(source)
            self.assertNotEqual(before, after, "Windows stat-only caching must not reuse changed source bytes")

    def test_windows_transaction_token_detects_same_size_change_with_restored_mtime(self):
        with tempfile.TemporaryDirectory(prefix="lc-win-cas-simulation-") as temporary:
            source = Path(temporary) / "source.bin"
            source.write_bytes(b"old pixels")
            original = source.stat()
            original_stat = Path.stat
            def windows_stat(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if path == source:
                    value = SimpleNamespace(**{name: getattr(result, name) for name in dir(result) if name.startswith("st_")})
                    value.st_ctime_ns = original.st_ctime_ns
                    value.st_ctime = original.st_ctime
                    return value
                return result
            with patch.object(transactions, "os", WindowsOSView()), \
                    patch.object(transactions, "sys", SimpleNamespace(platform="win32")), \
                    patch.object(Path, "stat", autospec=True, side_effect=windows_stat):
                before = transactions._token(source)
                source.write_bytes(b"new pixels")
                os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
                after = transactions._token(source)
            self.assertNotEqual(before, after, "Windows CAS must detect actual source-content replacement")

    def test_staged_json_paths_are_rebased_after_json_unescaping(self):
        # A literal backslash exercises JSON escaping on POSIX; on Windows the
        # same value denotes a nested path and still covers native separators.
        with tempfile.TemporaryDirectory(prefix="lc-json-path-simulation-") as temporary:
            base = Path(temporary).resolve() / "Windows\\style project"
            base.mkdir(parents=True)
            path = base / "project_manifest.json"
            manifest = {"test_fixture": True, "project_id": "json-escape-fixture", "concurrency": 2,
                        "generation_gate": {"status": "open"}, "jobs": [
                            {"id": "a", "status": "generated", "render_mode": "reference_generate",
                             "raw_output": "raw/a.png", "final_output": "final/a.png"}]}
            pipeline.write_json(path, manifest)
            def operation(staged):
                pipeline.write_json(staged.parent / "review/layouts/a.json",
                                    {"output_path": str(staged.parent / "review/layouts/a.png")})
                return 0
            transactions.run_staged_command(path, ["a"], operation, command_name="postprocess")
            saved = pipeline.read_json(base / "review/layouts/a.json")
            self.assertEqual(saved["output_path"], str(base / "review/layouts/a.png"))
            self.assertNotIn(".lc-transactions", saved["output_path"])

    def test_atomic_writers_close_their_files_before_replace(self):
        original_named, original_open, original_replace = tempfile.NamedTemporaryFile, Path.open, os.replace
        opened = []
        def named(*args, **kwargs):
            handle = original_named(*args, **kwargs)
            opened.append((Path(handle.name), handle))
            return handle
        def path_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            opened.append((path, handle))
            return handle
        def replace(source, target):
            for path, handle in opened:
                if path in {Path(source), Path(target)}:
                    self.assertTrue(handle.closed, f"Windows cannot replace own open handle: {path}")
            return original_replace(source, target)
        with tempfile.TemporaryDirectory(prefix="lc-close-before-replace-") as temporary:
            root = Path(temporary)
            with patch.object(tempfile, "NamedTemporaryFile", side_effect=named), \
                    patch.object(Path, "open", autospec=True, side_effect=path_open), \
                    patch.object(os, "replace", side_effect=replace):
                pipeline.write_json(root / "pipeline.json", {"fixture": True})
                workflow._atomic_bytes(root / "workflow.bin", b"synthetic")
                transactions._atomic(root / "transaction.bin", b"synthetic")
                delivery._write_json(root / "delivery.json", {"fixture": True})

    def test_windows_and_mac_without_clone_support_use_private_copy(self):
        with tempfile.TemporaryDirectory(prefix="lc-portable-clone-") as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"known synthetic source")
            for platform in ("win32", "darwin"):
                with self.subTest(platform=platform):
                    target = root / platform / "snapshot.bin"
                    metrics = {"cloned_files": 0, "copied_bytes": 0}
                    with patch.object(transactions, "sys", SimpleNamespace(platform=platform)), \
                            patch.object(transactions.ctypes, "CDLL", return_value=SimpleNamespace()) as library, \
                            patch.object(transactions.os, "link", side_effect=AssertionError("Writable snapshot cannot hard-link")):
                        transactions._clone(source, target, metrics)
                    if platform == "win32":
                        library.assert_not_called()
                    self.assertEqual(target.read_bytes(), source.read_bytes())
                    self.assertEqual(metrics, {"cloned_files": 0, "copied_bytes": source.stat().st_size})
                    self.assertEqual(target.stat().st_mtime_ns, source.stat().st_mtime_ns)
                    target.write_bytes(b"isolated mutation")
                    self.assertEqual(source.read_bytes(), b"known synthetic source")


if __name__ == "__main__":
    unittest.main()
