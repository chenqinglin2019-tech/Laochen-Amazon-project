"""Only the built-in generator is reachable; retired projects remain untouched."""
from __future__ import annotations
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import lc_image_pipeline as p
from pipeline_test_support import SECONDARY_ID, create_v3_fixture, prepare_fixture


class GenerationBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lc-backend-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.m = create_v3_fixture(self.base)
        prepare_fixture(self.m, self.base)
        self.job = p.find_by_id(self.m["jobs"], SECONDARY_ID)

    def test_new_project_and_prepared_dispatch_use_builtin(self):
        path = p.init_project(self.base / "new", "fixture", marketplace="US", language="en")
        self.assertEqual(p.read_json(path)["generation_backend"], "built_in_image_gen")
        self.m["anchor_job_id"] = SECONDARY_ID
        dispatch = p.execution_plan(self.m)["dispatch"]
        item = next(item for item in dispatch if item["id"] == SECONDARY_ID)
        self.assertEqual(item["action"], "image_gen")
        self.assertEqual(item["generation_reference_paths"], self.job["generation_reference_paths"])
        self.assertTrue(all(item["action"] in {"image_gen", "compose"} for item in dispatch))

    def test_removed_commands_are_rejected_by_cli(self):
        for command in ("web-browser", "web-run", "web-status", "web-backoff", "web-event", "web-accept-native"):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    p.parser().parse_args([command, "--json"])
                self.assertEqual(error.exception.code, 2)

    def test_removed_backend_options_cannot_create_or_modify_a_project(self):
        path = self.base / "project_manifest.json"
        p.write_json(path, self.m)
        before = path.read_bytes()
        directory = self.base / "forbidden"
        commands = [
            ["init", "--project-dir", str(directory), "--project-id", "fixture", "--marketplace", "US", "--language", "en", "--generation-backend", "chatgpt_web"],
            ["plan", "--manifest", str(path), "--generation-backend", "chatgpt_web"],
            ["plan", "--manifest", str(path), "--web-strict"],
            ["plan", "--manifest", str(path), "--web-parallel", "2"],
        ]
        for command in commands:
            result = subprocess.run([sys.executable, "-B", str(p.SCRIPT_DIR / "lc_image_pipeline.py"), *command], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("unrecognized arguments", result.stderr)
            self.assertFalse(directory.exists())
            self.assertEqual(path.read_bytes(), before)

    def test_retired_project_plan_fails_without_rewriting_existing_files(self):
        self.m["generation_backend"] = "chatgpt_web"
        path = self.base / "project_manifest.json"
        p.write_json(path, self.m)
        original = {f: f.read_bytes() for f in self.base.rglob("*") if f.is_file()}
        result = subprocess.run([sys.executable, "-B", str(p.SCRIPT_DIR / "lc_image_pipeline.py"), "plan", "--manifest", str(path), "--json"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertIn("generation_backend", result.stdout)
        for file, content in original.items():
            self.assertEqual(file.read_bytes(), content, str(file))
        self.assertEqual(list((self.base / "raw").glob("*")), [])

    def test_nonbuiltin_history_is_not_reinterpreted_as_builtin(self):
        for field in ("generation_attempts", "title_effect_attempts"):
            for binding in ({"backend": "chatgpt_web"}, {"backend": None}, {"web": {"state": "submitted"}}):
                with self.subTest(field=field, binding=binding):
                    manifest = copy.deepcopy(self.m)
                    manifest["jobs"][1][field] = [{"id": "old-attempt", **binding}]
                    before = copy.deepcopy(manifest)
                    self.assertTrue(p.validate_generation_backend(manifest))
                    with self.assertRaises(p.PipelineError):
                        p.execution_plan(manifest)
                    self.assertEqual(manifest, before)

    def test_retired_options_require_archival_even_if_backend_label_was_changed(self):
        for field in ("web_policy", "web_health", "web_batch_pause", "web_reference_source"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.m)
                manifest[field] = {}
                self.assertTrue(any(field in e for e in p.validate_manifest(manifest, self.base)))
                with self.assertRaises(p.PipelineError):
                    p.execution_plan(manifest)
        for field in ("native_canvas_approval", "web_native_export_approval"):
            manifest = copy.deepcopy(self.m)
            manifest["jobs"][1][field] = {}
            self.assertTrue(any(field in e for e in p.validate_manifest(manifest, self.base)))

    def test_builtin_history_and_missing_legacy_backend_remain_accepted(self):
        for field in ("generation_attempts", "title_effect_attempts"):
            for attempt in ({"id": "legacy"}, {"id": "current", "backend": "built_in_image_gen"}):
                manifest = copy.deepcopy(self.m)
                manifest["jobs"][1][field] = [attempt]
                self.assertEqual(p.validate_generation_backend(manifest), [])
        before = p.execution_plan(self.m)
        del self.m["generation_backend"]
        self.assertEqual(p.execution_plan(self.m), before)
        self.assertEqual(p.validate_manifest(self.m, self.base), [])
        for value in (None, "", [], {}, "unknown"):
            self.m["generation_backend"] = value
            self.assertTrue(p.validate_generation_backend(self.m))


if __name__ == "__main__":
    unittest.main()
