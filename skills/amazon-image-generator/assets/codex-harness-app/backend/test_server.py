import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("feiyu_module_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


class ValidationTests(unittest.TestCase):
    def test_image_magic(self):
        self.assertEqual(SERVER.image_kind(b"\x89PNG\r\n\x1a\nrest"), (".png", "image/png"))
        self.assertEqual(SERVER.image_kind(b"\xff\xd8\xffrest"), (".jpg", "image/jpeg"))
        self.assertEqual(SERVER.image_kind(b"RIFF1234WEBPrest"), (".webp", "image/webp"))
        self.assertIsNone(SERVER.image_kind(b"<script>alert(1)</script>"))

    def test_payload_limits(self):
        payload = SERVER.validate_payload(
            {
                "title": "Bottle",
                "description": "Steel bottle",
                "total": "2",
                "ai_model": "1|nano-banana-2",
                "fixed_setting": '{"style":"亚马逊风格"}',
                "setting": '{"aspect_ratio":"1:1","images":["ignored"]}',
            }
        )
        self.assertEqual(payload["total"], 2)
        self.assertNotIn("images", payload["setting"])
        maximum = SERVER.validate_payload(
            {
                "title": "Bottle",
                "description": "Steel bottle",
                "total": "15",
                "ai_model": "1|nano-banana-2",
            }
        )
        self.assertEqual(maximum["total"], 15)
        with self.assertRaises(SERVER.AppError) as context:
            SERVER.validate_payload(
                {"title": "Bottle", "description": "x", "total": "16", "ai_model": "x"}
            )
        self.assertEqual(context.exception.code, "invalid_total")

    def test_public_file_url_never_exposes_server_path(self):
        previous = SERVER.GENERATED_DIR
        with tempfile.TemporaryDirectory() as directory:
            SERVER.GENERATED_DIR = Path(directory)
            local_file = Path(directory) / "job-1" / "image.png"
            local_file.parent.mkdir()
            local_file.write_bytes(b"x")
            url = SERVER.public_file_url(str(local_file))
            self.assertEqual(url, "/custom-api/amazon-image-generator/files/generated/job-1/image.png")
            self.assertIsNone(SERVER.public_file_url("/etc/passwd"))
        SERVER.GENERATED_DIR = previous

    def test_status_mapping_keeps_generation_and_archive_separate(self):
        self.assertEqual(SERVER.derive_status({"state": "success", "archive": {"status": "partial"}})[0], "archive_partial")
        self.assertEqual(SERVER.derive_status({"state": "timeout"})[0], "timeout")
        self.assertEqual(SERVER.derive_status({"state": "failed"})[0], "generation_failed")

    def test_http_token_requires_explicit_acknowledgement(self):
        SERVER.require_transport_acknowledgement({"Origin": "https://example.test"})
        SERVER.require_transport_acknowledgement({"Origin": "http://127.0.0.1:38080"})
        with self.assertRaises(SERVER.AppError) as context:
            SERVER.require_transport_acknowledgement({"Origin": "http://example.test"})
        self.assertEqual(context.exception.code, "transport_ack_required")
        SERVER.require_transport_acknowledgement(
            {"Origin": "http://example.test", "x-insecure-token-ack": "confirmed"}
        )

    def test_token_is_passed_only_through_stdin(self):
        completed = mock.Mock(stdout='{"ok": true}', returncode=0)
        with mock.patch.object(SERVER.subprocess, "run", return_value=completed) as run:
            SERVER.run_cli(["set-token", "--stdin"], stdin_text="super-secret", timeout=1)
        command = run.call_args.args[0]
        self.assertNotIn("super-secret", command)
        self.assertEqual(run.call_args.kwargs["input"], "super-secret")


class HistoryTests(unittest.TestCase):
    """GET /api/jobs is the generation-history endpoint; see references/api.md."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        patches = {
            "DATA_DIR": root,
            "UPLOAD_DIR": root / "uploads",
            "GENERATED_DIR": root / "generated",
            "DB_PATH": root / "app.sqlite3",
        }
        for name, value in patches.items():
            patcher = mock.patch.object(SERVER, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        SERVER.init_db()

    def _insert(self, title, created_at):
        row = SERVER.insert_job(
            {
                "title": title,
                "description": "desc",
                "total": 2,
                "ai_model": "1|nano-banana-2",
                "fixed_setting": {"language": "en"},
                "setting": {"aspect_ratio": "1:1"},
            },
            [{"url": "https://example.test/a.png", "original_name": "a.png"}],
        )
        with SERVER.DB_LOCK, SERVER.connect_db() as connection:
            connection.execute(
                "UPDATE jobs SET created_at = ? WHERE id = ?", (created_at, row["id"])
            )
        return row["id"]

    def test_pagination_is_server_side_and_newest_first(self):
        for index in range(7):
            self._insert(f"P{index}", f"2026-08-{20 + index:02d}T00:00:00Z")
        rows, total, page, size = SERVER.list_jobs(page=1, size=5)
        self.assertEqual((total, page, size, len(rows)), (7, 1, 5, 5))
        self.assertEqual(rows[0]["title"], "P6")
        rows, total, page, _size = SERVER.list_jobs(page=2, size=5)
        self.assertEqual((total, page, len(rows)), (7, 2, 2))

    def test_page_out_of_range_is_clamped(self):
        self._insert("only", "2026-08-20T00:00:00Z")
        _rows, _total, page, _size = SERVER.list_jobs(page=99, size=5)
        self.assertEqual(page, 1)

    def test_date_range_filters_inclusively(self):
        for index in range(5):
            self._insert(f"P{index}", f"2026-08-{20 + index:02d}T12:00:00Z")
        rows, total, _page, _size = SERVER.list_jobs(
            page=1, size=50, start="2026-08-21", end="2026-08-23"
        )
        self.assertEqual(total, 3)
        self.assertEqual([row["title"] for row in rows], ["P3", "P2", "P1"])

    def test_bad_date_is_ignored_rather_than_crashing(self):
        self._insert("only", "2026-08-20T00:00:00Z")
        _rows, total, _page, _size = SERVER.list_jobs(page=1, size=5, start="not-a-date")
        self.assertEqual(total, 1)


class ImageSourceTests(unittest.TestCase):
    """Product images may be uploaded files or public links, either one."""

    def test_public_links_are_accepted(self):
        records = SERVER.parse_image_urls('["https://example.test/a.png"]')
        self.assertEqual(records[0]["url"], "https://example.test/a.png")

    def test_non_http_links_are_rejected(self):
        for raw in ('["javascript:alert(1)"]', '["file:///etc/passwd"]', '"not-a-list"'):
            with self.assertRaises(SERVER.AppError):
                SERVER.parse_image_urls(raw)

    def test_links_alone_satisfy_the_image_requirement(self):
        urls = SERVER.parse_image_urls('["https://example.test/a.png"]')
        self.assertEqual(SERVER.save_uploads([], urls), urls)
        with self.assertRaises(SERVER.AppError) as context:
            SERVER.save_uploads([], [])
        self.assertEqual(context.exception.code, "missing_images")

    def test_link_jobs_pass_the_url_straight_to_the_cli(self):
        row = {
            "total": 1,
            "title": "t",
            "description": "d",
            "fixed_setting_json": "{}",
            "ai_model": "m",
            "setting_json": "{}",
            "uploads_json": '[{"url": "https://example.test/a.png"}]',
        }
        arguments, _uploads = SERVER.job_arguments(row)
        self.assertIn("https://example.test/a.png", arguments)

    def test_source_urls_never_expose_a_server_path(self):
        previous = SERVER.UPLOAD_DIR
        with tempfile.TemporaryDirectory() as directory:
            SERVER.UPLOAD_DIR = Path(directory)
            try:
                urls = SERVER.source_image_urls(
                    [
                        {"path": str(Path(directory) / "photo.png")},
                        {"url": "https://example.test/a.png"},
                        {"path": "/etc/passwd"},
                    ]
                )
            finally:
                SERVER.UPLOAD_DIR = previous
        self.assertEqual(
            urls,
            [
                "/custom-api/amazon-image-generator/files/uploads/photo.png",
                "https://example.test/a.png",
            ],
        )


if __name__ == "__main__":
    unittest.main()
