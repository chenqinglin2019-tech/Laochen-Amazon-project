from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "flyfus_client.py"
SPEC = importlib.util.spec_from_file_location("flyfus_client", MODULE_PATH)
assert SPEC and SPEC.loader
flyfus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flyfus)


class FlyfusClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Path(self.temporary.name) / "private" / "flyfus_api.env"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_initialization_is_private_and_never_overwrites(self) -> None:
        first = flyfus.initialize_config(self.config)
        self.assertEqual("created", first["status"])
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(self.config.stat().st_mode))
        self.config.write_text("FLYFUS_API_KEY=local-test-key\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.config, 0o600)
        second = flyfus.initialize_config(self.config)
        self.assertEqual("exists", second["status"])
        self.assertEqual("local-test-key", flyfus.load_api_key(self.config))

    def test_config_rejects_placeholder_extra_key_and_unsafe_permission(self) -> None:
        flyfus.initialize_config(self.config)
        with self.assertRaises(flyfus.FlyfusConfigurationError):
            flyfus.load_api_key(self.config)
        self.config.write_text("FLYFUS_API_KEY=local-test-key\nUNRELATED=value\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.config, 0o600)
        with self.assertRaises(flyfus.FlyfusConfigurationError):
            flyfus.load_api_key(self.config)
        self.config.write_text("FLYFUS_API_KEY=local-test-key\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.config, 0o644)
            with self.assertRaises(flyfus.FlyfusConfigurationError):
                flyfus.load_api_key(self.config)

    def test_review_probe_stops_on_pagination_contract_mismatch_and_preserves_ids(self) -> None:
        response = {
            "code": 0,
            "data": {
                "total": 2500,
                "list": [
                    {"reviewId": "R-1", "title": "Works", "content": "Great fit", "date": "2026-01-01", "rating": 5},
                    {"reviewId": "R-2", "content": "same text", "date": "2026-01-02", "rating": 4},
                ],
            },
        }
        receipt = flyfus.review_probe_receipt(response, "B012345678", "US", 10, "local-test-key")
        self.assertEqual("batch_contract_mismatch", receipt["status"])
        self.assertEqual(2, receipt["returned_record_count"])
        self.assertEqual(["R-1", "R-2"], [record["content_id"] for record in receipt["records"]])
        self.assertEqual("unknown", receipt["records"][0]["metadata"]["purchase_variant"])
        self.assertNotIn("local-test-key", json.dumps(receipt))

    def test_review_page_collection_keeps_distinct_pages_and_stops_at_per_asin_cap(self) -> None:
        calls = []
        responses = {
            1: {"code": 0, "data": {"total": 3, "list": [{"reviewId": "R-1", "content": "first"}, {"reviewId": "R-2", "content": "second"}]}},
            2: {"code": 0, "data": {"total": 3, "list": [{"reviewId": "R-3", "content": "third"}]}},
        }

        def fetch(page: int):
            calls.append(page)
            return responses[page]

        receipt = flyfus.collect_review_pages(fetch, "B012345678", "US", 1, 10, 3, None, "local-test-key")
        self.assertEqual([1, 2], calls)
        self.assertEqual("reported_total_reached", receipt["halt_reason"])
        self.assertEqual(2, receipt["pages_fetched"])
        self.assertEqual(["R-1", "R-2", "R-3"], [record["content_id"] for record in receipt["records"]])
        self.assertEqual(20, receipt["points_reserved"])

    def test_review_page_collection_stops_when_api_repeats_a_page(self) -> None:
        response = {"code": 0, "data": {"total": 30, "list": [{"reviewId": "R-1", "content": "same"}]}}
        receipt = flyfus.collect_review_pages(lambda _: response, "B012345678", "US", 1, 10, 30, None, "local-test-key")
        self.assertEqual("nonincremental_page", receipt["halt_reason"])
        self.assertEqual(2, receipt["pages_fetched"])
        self.assertEqual(1, receipt["unique_record_count"])

    def test_recommendation_pre_reservation_rejects_overspend_before_request(self) -> None:
        args = flyfus.build_parser().parse_args([
            "--config", str(self.config), "recommendations", "--kind", "keyword", "--keyword", "porch goose clothes",
            "--market", "US", "--points-cap", "10", "--reserve-points", "11", "--output", str(self.config.parent / "out.json"),
        ])
        with self.assertRaises(flyfus.FlyfusConfigurationError) as raised:
            flyfus.execute(args)
        self.assertIn("预留积分", str(raised.exception))

    def test_successful_page_is_saved_before_later_error_without_retry(self) -> None:
        saved = []
        calls = []
        def fetch(page):
            calls.append(page)
            if page == 2:
                raise flyfus.FlyfusError("request uncertain")
            return {"data": {"total": 20, "list": [{"reviewId": "R1", "content": "desk fits"}]}}
        with self.assertRaises(flyfus.FlyfusError):
            flyfus.collect_review_pages(fetch, "B012345678", "US", 1, 5, 1000, None, "local-test-key", save_page=saved.append)
        self.assertEqual([1, 2], calls)
        self.assertEqual(1, len(saved))
        self.assertEqual("R1", saved[0]["records"][0]["content_id"])

    def test_nonempty_unparseable_page_is_not_empty_or_reliable_end(self) -> None:
        result = flyfus.collect_review_pages(lambda _: {"data": {"list": [{"title": "no id"}]}}, "B012345678", "US", 1, 3, 1000, None, "")
        self.assertEqual("normalization_empty", result["halt_reason"])

    def test_actual_author_fields_are_preserved_not_invented(self) -> None:
        records = flyfus.review_records({"data": {"list": [{"reviewId": "R1", "text": "desk", "authorName": "person", "reviewerId": "u1"}, {"reviewId": "R2", "text": "desk"}]}}, "B012345678", "US")
        self.assertEqual("u1", records[0]["author_id"])
        self.assertIsNone(records[1]["author_id"])

    def test_raw_id_cap_counts_empty_text_and_same_page_duplicates_once(self) -> None:
        calls = []
        def fetch(page):
            calls.append(page)
            return {"data": {"total": 9, "list": [{"reviewId": "R1", "text": "desk"}, {"reviewId": "R1", "text": "desk"}, {"reviewId": "R2", "text": ""}]}}
        result = flyfus.collect_review_pages(fetch, "B012345678", "US", 1, 10, 2, None, "")
        self.assertEqual([1], calls)
        self.assertEqual(2, result["sampled_native_id_count"])
        self.assertEqual(1, result["unique_record_count"])

    def test_task_completion_mode_does_not_require_points_cap(self) -> None:
        args = flyfus.build_parser().parse_args([
            "--config", str(self.config), "recommendations", "--kind", "keyword", "--keyword", "small desk",
            "--market", "US", "--reserve-points", "11", "--output", str(self.config.parent / "out.json"),
        ])
        self.assertIsNone(args.points_cap)
        receipt = flyfus.recommendation_receipt({"code": 0, "data": []}, {"keyword": "small desk"}, None, 11, "local-test-key")
        self.assertEqual("task_completion", receipt["spend_boundary"])


if __name__ == "__main__":
    unittest.main()
