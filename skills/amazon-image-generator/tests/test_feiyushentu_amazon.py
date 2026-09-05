import argparse
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import urllib.error
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "feiyushentu_amazon.py"
SPEC = importlib.util.spec_from_file_location("feiyushentu_amazon", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeHeaders(dict):
    def get_content_type(self):
        return self.get("Content-Type", "").split(";", 1)[0]


class FakeResponse:
    def __init__(self, body=b"image-bytes", content_type="image/png"):
        self._body = io.BytesIO(body)
        self.headers = FakeHeaders({"Content-Type": content_type})

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TokenStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_path = MODULE.CONFIG_PATH
        MODULE.CONFIG_PATH = Path(self.temp_dir.name) / "config" / "site.toml"

    def tearDown(self):
        MODULE.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def test_save_replace_and_check_never_returns_token(self):
        MODULE.CONFIG_PATH.parent.mkdir(parents=True)
        MODULE.CONFIG_PATH.write_text(
            'other_setting = true\nfeiyushentu_token = "stale-one"\nfeiyushentu_token = "stale-two"\n',
            encoding="utf-8",
        )
        MODULE.save_token("first-secret-token")
        MODULE.save_token("replacement-secret-token")

        content = MODULE.CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn("other_setting = true", content)
        self.assertNotIn("stale-one", content)
        self.assertNotIn("stale-two", content)
        self.assertNotIn("first-secret-token", content)
        self.assertEqual(content.count(MODULE.TOKEN_KEY), 1)
        self.assertEqual(MODULE.load_token(), "replacement-secret-token")
        self.assertEqual(stat.S_IMODE(MODULE.CONFIG_PATH.stat().st_mode), 0o600)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = MODULE.cmd_check_token(argparse.Namespace())
        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(result, {"ok": True, "token_configured": True})
        self.assertNotIn("replacement-secret-token", output.getvalue())
        self.assertNotIn("secret", output.getvalue())

    def test_set_token_reads_stdin(self):
        output = io.StringIO()
        with mock.patch.object(MODULE.sys, "stdin", io.StringIO("stdin-secret-token\n")):
            with contextlib.redirect_stdout(output):
                status = MODULE.cmd_set_token(argparse.Namespace(stdin=True))
        self.assertEqual(status, 0)
        self.assertEqual(MODULE.load_token(), "stdin-secret-token")
        self.assertNotIn("stdin-secret-token", output.getvalue())

    def test_emit_redacts_nested_token_values_and_sensitive_fields(self):
        MODULE.save_token("configured-secret-token")
        output = io.StringIO()
        payload = {
            "message": "upstream echoed configured-secret-token",
            "response": {"token": "another-secret", "secretKey": "temporary-secret"},
        }
        with contextlib.redirect_stdout(output):
            MODULE.emit(payload)
        rendered = output.getvalue()
        self.assertNotIn("configured-secret-token", rendered)
        self.assertNotIn("another-secret", rendered)
        self.assertNotIn("temporary-secret", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_config_path_precedence(self):
        env_path = Path(self.temp_dir.name) / "env.toml"
        cli_path = Path(self.temp_dir.name) / "cli.toml"
        with mock.patch.dict(os.environ, {MODULE.CONFIG_PATH_ENV: str(env_path)}):
            self.assertEqual(MODULE.resolve_config_path(), env_path.resolve())
            self.assertEqual(MODULE.resolve_config_path(str(cli_path)), cli_path.resolve())

    def test_legacy_positional_token_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.build_parser().parse_args(["set-token", "plaintext-token"])


class ImageArchiveTests(unittest.TestCase):
    def test_archive_preserves_success_when_another_download_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            records = [
                {"task_id": "TASK-1", "source_url": "https://example.com/one.png"},
                {"task_id": "TASK-2", "source_url": "https://example.com/two.png"},
            ]

            def fake_urlopen(url, timeout=0):
                self.assertEqual(timeout, 120)
                if str(url).endswith("two.png"):
                    raise urllib.error.URLError("expired")
                return FakeResponse(b"first-image")

            with mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=fake_urlopen):
                archive = MODULE.archive_generated_images(records, temp_dir)

            self.assertEqual(archive["status"], "partial")
            self.assertEqual(archive["success"], 1)
            self.assertEqual(archive["failed"], 1)
            saved = archive["images"][0]
            self.assertEqual(saved["archive_status"], "success")
            self.assertEqual(saved["sha256"], hashlib.sha256(b"first-image").hexdigest())
            self.assertTrue(Path(saved["local_path"]).is_file())
            self.assertEqual(Path(saved["local_path"]).parent.name, "TASK-1")
            self.assertEqual(archive["images"][1]["archive_status"], "failed")
            self.assertIsNone(archive["images"][1]["local_path"])

    def test_output_directory_inside_skill_is_rejected(self):
        with self.assertRaises(MODULE.SkillError) as caught:
            MODULE.resolve_output_dir(str(MODULE.SKILL_ROOT / "generated-images"))
        self.assertEqual(caught.exception.error_type, "invalid_output_dir")

    def test_apply_archive_keeps_url_only_compatibility(self):
        result = {
            "ok": True,
            "state": "success",
            "images": ["https://example.com/image.png"],
        }
        archived = MODULE.apply_archive(result, None)
        self.assertTrue(archived["ok"])
        self.assertEqual(archived["archive"]["status"], "not_requested")

    def test_batch_writes_archive_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "products.csv"
            output_path = Path(temp_dir) / "results.csv"
            archive_dir = Path(temp_dir) / "generated"
            input_path.write_text(
                "title,desc,total,image_urls\nBottle,Steel bottle,1,https://example.com/ref.png\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                csv=str(input_path),
                output=str(output_path),
                fixed_setting="{}",
                setting="{}",
                ai_model="model",
                encoding="utf-8",
                poll_interval=0,
                max_polls=1,
                verbose=False,
                status_method="post-query",
                output_dir=str(archive_dir),
            )
            polled = {
                "ok": True,
                "state": "success",
                "task_ids": ["TASK-CSV"],
                "images": ["https://example.com/generated.png"],
                "generated_images": [
                    {"task_id": "TASK-CSV", "source_url": "https://example.com/generated.png"}
                ],
            }

            with mock.patch.object(MODULE, "prepare_images", return_value=["https://example.com/ref.png"]):
                with mock.patch.object(MODULE, "submit_task", return_value={"task_ids": ["TASK-CSV"]}):
                    with mock.patch.object(MODULE, "poll_tasks", return_value=polled):
                        with mock.patch.object(
                            MODULE.urllib.request,
                            "urlopen",
                            return_value=FakeResponse(b"generated-image"),
                        ):
                            with contextlib.redirect_stdout(io.StringIO()):
                                status = MODULE.cmd_batch(args)

            self.assertEqual(status, 0)
            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["status"], "success")
            self.assertEqual(rows[0]["archive_status"], "success")
            self.assertTrue(Path(rows[0]["local_paths"]).is_file())
            image_records = json.loads(rows[0]["image_records"])
            self.assertEqual(image_records[0]["task_id"], "TASK-CSV")
            self.assertEqual(image_records[0]["archive_status"], "success")


if __name__ == "__main__":
    unittest.main()
