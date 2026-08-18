from __future__ import annotations

import copy
import json
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_front_crawler as front


class FrontConfigTests(unittest.TestCase):
    def base_config(self) -> dict:
        raw = json.loads(
            (SKILL_ROOT / "assets" / "config" / "amazon_front_keyword_search.json").read_text(
                encoding="utf-8"
            )
        )
        raw["keywords_file"] = str(
            SKILL_ROOT / "assets" / "inputs" / "keywords.example.csv"
        )
        return raw

    def test_tab_concurrency_range_and_backend_contract(self) -> None:
        raw = self.base_config()
        raw["browser_tab_concurrency"] = 3
        runtime = front.build_front_runtime_config(raw, no_resume=False)
        self.assertEqual(runtime.browser_tab_concurrency, 3)

        for invalid in (0, 4):
            invalid_raw = dict(raw, browser_tab_concurrency=invalid)
            with self.assertRaises(front.UserFacingError):
                front.build_front_runtime_config(invalid_raw, no_resume=False)

        invalid_raw = dict(
            raw,
            browser_tab_concurrency=2,
            browser_backend="selenium",
            browser_mode="reuse",
        )
        with self.assertRaises(front.UserFacingError):
            front.build_front_runtime_config(invalid_raw, no_resume=False)

    def test_enabled_filters_require_sellersprite(self) -> None:
        raw = self.base_config()
        raw["sellersprite_required"] = False
        raw["product_filters"] = {
            "allowed_fulfillment_methods": ["FBM"],
            "allow_missing_fulfillment": True,
            "require_subcategory_rank": True,
        }
        with self.assertRaises(front.UserFacingError):
            front.build_front_runtime_config(raw, no_resume=False)


class FrontPaginationTests(unittest.TestCase):
    def runtime(self) -> SimpleNamespace:
        return SimpleNamespace(max_pages_per_keyword=5, store_page_limit=5)

    def test_raw_records_drive_next_page_even_when_nothing_is_accepted(self) -> None:
        task = {
            "source_type": "storefront",
            "source_id": "store-a|sort:Newest Arrivals",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A&page=1",
            "seen_page_urls": [],
            "previous_page_asins": [],
        }
        driver = SimpleNamespace(current_url=task["page_url"])
        raw_records = [{"asin": "B000000001"}]
        with patch.object(
            front,
            "find_next_page_url",
            return_value="https://www.amazon.com/s?me=A&page=2",
        ):
            next_task, reason = front.build_next_front_task(
                driver, self.runtime(), task, raw_records
            )
        self.assertEqual(reason, "")
        self.assertIsNotNone(next_task)
        self.assertEqual(next_task["page_number"], 2)
        self.assertEqual(next_task["previous_page_asins"], ["B000000001"])

    def test_empty_raw_page_stops_source(self) -> None:
        task = {
            "source_type": "keyword_search",
            "source_id": "test|sort:Featured",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?k=test",
        }
        next_task, reason = front.build_next_front_task(
            SimpleNamespace(current_url=task["page_url"]), self.runtime(), task, []
        )
        self.assertIsNone(next_task)
        self.assertEqual(reason, "empty_page")


class FrontStateV2Tests(unittest.TestCase):
    def runtime(self, root: Path, resume: bool) -> SimpleNamespace:
        filters = front.ProductFilterConfig(
            allowed_fulfillment_methods=("FBM",),
            allow_missing_fulfillment=True,
            require_subcategory_rank=True,
        )
        return SimpleNamespace(
            resume=resume,
            job_id="front-state-test",
            mode="storefront",
            outputs_root=root,
            include_sponsored=False,
            max_pages_per_keyword=5,
            store_page_limit=10,
            sellersprite_required=True,
            field_selectors={},
            delivery_location_fingerprint="delivery-v1",
            record_contract_fingerprint=front.record_contract_fingerprint(filters),
        )

    def tasks(self) -> list[dict]:
        return [
            {
                "source_type": "storefront",
                "source_id": "source-a",
                "page_number": 1,
                "page_url": "https://www.amazon.com/s?me=A&page=1",
            },
            {
                "source_type": "storefront",
                "source_id": "source-a",
                "page_number": 2,
                "page_url": "https://www.amazon.com/s?me=A&page=2",
            },
            {
                "source_type": "storefront",
                "source_id": "source-b",
                "page_number": 1,
                "page_url": "https://www.amazon.com/s?me=B&page=1",
            },
        ]

    def test_same_source_is_never_leased_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = front.FrontStateStore(
                root / "state.json", self.runtime(root, False), self.tasks()
            )
            state.load_or_create()
            first = state.lease_next("tab-1")
            second = state.lease_next("tab-2")
            self.assertEqual(front.front_source_id(first), "source-a")
            self.assertEqual(front.front_source_id(second), "source-b")
            self.assertIsNone(state.lease_next("tab-3"))

    def test_stale_pending_tasks_from_completed_source_are_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = front.FrontStateStore(
                root / "state.json", self.runtime(root, False), self.tasks()[:2]
            )
            state.load_or_create()
            state.data["completed_sources"] = ["source-a"]
            self.assertIsNone(state.lease_next("tab-1"))
            self.assertFalse(state.has_work())
            self.assertEqual(state.data["pending"], [])

    def test_orphan_page_commit_recovers_inflight_and_materializes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            runtime = self.runtime(root, False)
            first_task = self.tasks()[0]
            state = front.FrontStateStore(state_path, runtime, [first_task])
            state.load_or_create()
            leased = state.lease_next("tab-1")
            stale_state = copy.deepcopy(state.data)
            next_task = dict(first_task, page_number=2, page_url="https://www.amazon.com/s?me=A&page=2")
            result = front.FrontPageResult(
                worker_id="tab-1",
                task=leased,
                page_key="source-a|page:1|actual",
                page_url=first_task["page_url"],
                raw_records=[{"asin": "B000000001"}, {"asin": "B000000002"}],
                accepted_records=[{"asin": "B000000001"}],
                rejection_counts={"subcategory_bsr_rank_missing": 1},
                plugin_status="ok",
                next_task=next_task,
            )
            state.commit_page_result(result)

            # Simulate a crash after the atomic page shard but before state.json commit.
            front.dump_json(state_path, stale_state)
            resumed_runtime = self.runtime(root, True)
            resumed = front.FrontStateStore(state_path, resumed_runtime, [first_task])
            resumed.load_or_create()

            self.assertEqual(resumed.data["completed_pages"], [result.page_key])
            self.assertEqual(resumed.data["records_count"], 1)
            self.assertEqual(resumed.data["scanned_count"], 2)
            self.assertEqual(resumed.data["filtered_count"], 1)
            self.assertEqual(len(resumed.data["pending"]), 1)
            self.assertEqual(resumed.data["pending"][0]["page_number"], 2)

            records_path = root / "records.jsonl"
            self.assertEqual(front.materialize_front_records(resumed, records_path), 1)
            self.assertEqual(front.read_jsonl(records_path), [{"asin": "B000000001"}])

    def test_old_state_with_progress_requires_new_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps({"completed_pages": ["legacy-page"], "records_count": 0}),
                encoding="utf-8",
            )
            state = front.FrontStateStore(
                state_path, self.runtime(root, True), self.tasks()
            )
            with self.assertRaises(front.UserFacingError):
                state.load_or_create()

    def test_records_without_state_or_page_shards_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "records.jsonl").write_text('{"asin":"B000000001"}\n', encoding="utf-8")
            state = front.FrontStateStore(
                root / "state.json", self.runtime(root, True), self.tasks()
            )
            with self.assertRaises(front.UserFacingError):
                state.load_or_create()

    def test_missing_committed_page_shard_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = self.tasks()[0]
            state_path = root / "state.json"
            state = front.FrontStateStore(
                state_path, self.runtime(root, False), [task]
            )
            state.load_or_create()
            leased = state.lease_next("tab-1")
            result = front.FrontPageResult(
                worker_id="tab-1",
                task=leased,
                page_key="source-a|page:1|actual",
                page_url=task["page_url"],
                raw_records=[{"asin": "B000000001"}],
                accepted_records=[{"asin": "B000000001"}],
                plugin_status="ok",
                finish_reason="no_next_page",
            )
            state.commit_page_result(result)
            state.page_result_path(result.page_key).unlink()

            resumed = front.FrontStateStore(
                state_path, self.runtime(root, True), [task]
            )
            with self.assertRaises(front.UserFacingError):
                resumed.load_or_create()

    def test_changed_crawl_plan_with_progress_requires_new_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            state = front.FrontStateStore(
                state_path, self.runtime(root, False), [self.tasks()[0]]
            )
            state.load_or_create()
            state.lease_next("tab-1")

            changed_task = dict(
                self.tasks()[0],
                source_id="source-changed",
                page_url="https://www.amazon.com/s?me=CHANGED&page=1",
            )
            resumed = front.FrontStateStore(
                state_path, self.runtime(root, True), [changed_task]
            )
            with self.assertRaises(front.UserFacingError):
                resumed.load_or_create()

    def test_changed_crawl_plan_without_progress_rebuilds_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            original = self.tasks()[0]
            state = front.FrontStateStore(
                state_path, self.runtime(root, False), [original]
            )
            state.load_or_create()

            changed = dict(
                original,
                source_id="source-changed",
                page_url="https://www.amazon.com/s?me=CHANGED&page=1",
            )
            resumed = front.FrontStateStore(
                state_path, self.runtime(root, True), [changed]
            )
            resumed.load_or_create()
            self.assertEqual(resumed.data["pending"], [changed])
            self.assertEqual(resumed.data["mode"], "storefront")

    def test_orphan_shard_from_different_plan_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = self.tasks()[0]
            state_path = root / "state.json"
            state = front.FrontStateStore(
                state_path, self.runtime(root, False), [task]
            )
            state.load_or_create()
            leased = state.lease_next("tab-1")
            state.commit_page_result(
                front.FrontPageResult(
                    worker_id="tab-1",
                    task=leased,
                    page_key="source-a|page:1|actual",
                    page_url=task["page_url"],
                    raw_records=[{"asin": "B000000001"}],
                    accepted_records=[{"asin": "B000000001"}],
                    plugin_status="ok",
                    finish_reason="no_next_page",
                )
            )
            state_path.unlink()

            changed = dict(
                task,
                source_id="source-changed",
                page_url="https://www.amazon.com/s?me=CHANGED&page=1",
            )
            resumed = front.FrontStateStore(
                state_path, self.runtime(root, True), [changed]
            )
            with self.assertRaises(front.UserFacingError):
                resumed.load_or_create()


class FrontOutputTests(unittest.TestCase):
    def test_front_merge_recognizes_compacted_fbm_card_text(self) -> None:
        card = {
            "asin": "B000000001",
            "rank": "1",
            "is_sponsored": "no",
            "text": "ASIN:B000000001 配送:FBM卖家:1 FBA费用:$3.81",
        }
        runtime = SimpleNamespace(include_sponsored=False, field_selectors={})
        current = {
            "source_type": "storefront",
            "source_id": "source-a",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A",
        }
        driver = SimpleNamespace(current_url=current["page_url"])
        with (
            patch.object(front, "extract_front_product_cards", return_value=[card]),
            patch.object(front, "extract_table_rows", return_value=[]),
        ):
            record = front.merge_front_product_data(driver, runtime, current, "ok")[0]
        self.assertEqual(record["fulfillment_method"], "FBM")
        self.assertEqual(record["fulfillment_method_raw"], "FBM卖家")

    def test_merge_preserves_unknown_fulfillment_evidence_for_filtering(self) -> None:
        card = {
            "asin": "B000000001",
            "rank": "1",
            "title": "Test",
            "product_url": "https://www.amazon.com/dp/B000000001",
            "is_sponsored": "no",
            "text": "ASIN: B000000001 FBA费用: $6.31",
        }
        row = {
            "asin": "B000000001",
            "headers": ["配送方式"],
            "cells": ["SFP"],
            "text": "ASIN: B000000001 配送: SFP #130 in Fruit Bowls",
        }
        runtime = SimpleNamespace(
            include_sponsored=False,
            field_selectors={},
        )
        current = {
            "source_type": "storefront",
            "source_id": "source-a",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A",
        }
        driver = SimpleNamespace(current_url=current["page_url"])
        with (
            patch.object(front, "extract_front_product_cards", return_value=[card]),
            patch.object(front, "extract_table_rows", return_value=[row]),
        ):
            records = front.merge_front_product_data(driver, runtime, current, "ok")
        self.assertEqual(records[0]["fulfillment_method"], "")
        self.assertEqual(records[0]["fulfillment_method_raw"], "SFP")
        accepted, counts = front.filter_product_records(
            records,
            front.ProductFilterConfig(("FBM",), True, False),
        )
        self.assertEqual(accepted, [])
        self.assertEqual(counts, {"fulfillment_method_not_allowed": 1})

    def test_front_merge_unknown_selector_cannot_overwrite_table_canonical(self) -> None:
        card = {
            "asin": "B000000001",
            "rank": "1",
            "is_sponsored": "no",
            "text": "ASIN:B000000001 配送:FBM卖家:1",
        }
        row = {
            "asin": "B000000001",
            "headers": ["配送方式"],
            "cells": ["FBA"],
            "text": "ASIN:B000000001 配送:FBA",
        }
        runtime = SimpleNamespace(
            include_sponsored=False,
            field_selectors={"fulfillment_method": [".fulfillment"]},
        )
        current = {
            "source_type": "storefront",
            "source_id": "source-a",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A",
        }
        driver = SimpleNamespace(current_url=current["page_url"])
        with (
            patch.object(front, "extract_front_product_cards", return_value=[card]),
            patch.object(front, "extract_table_rows", return_value=[row]),
            patch.object(
                front,
                "extract_by_selectors",
                return_value={"fulfillment_method": "SFPPlus"},
            ),
        ):
            record = front.merge_front_product_data(driver, runtime, current, "ok")[0]
        self.assertEqual(record["fulfillment_method"], "FBA")
        self.assertEqual(record["fulfillment_method_raw"], "FBA")

        with (
            patch.object(front, "extract_front_product_cards", return_value=[card]),
            patch.object(front, "extract_table_rows", return_value=[row]),
            patch.object(
                front,
                "extract_by_selectors",
                return_value={"fulfillment_method": "FBMPlus"},
            ),
        ):
            record = front.merge_front_product_data(driver, runtime, current, "ok")[0]
        self.assertEqual(record["fulfillment_method"], "FBM")
        self.assertEqual(record["fulfillment_method_raw"], "FBMPlus")

    def test_subcategory_rank_pairs_are_merged_atomically(self) -> None:
        rows = front.build_front_dedup_rows(
            [
                {
                    "asin": "B000000001",
                    "page_number": 1,
                    "rank": 1,
                    "subcategory_bsr_ranks": [
                        {"rank": 130, "category_name": "Fruit Bowls"}
                    ],
                },
                {
                    "asin": "B000000001",
                    "page_number": 2,
                    "rank": 3,
                    "subcategory_bsr_ranks": [
                        {"rank": 999, "category_name": "Fruit Bowls"},
                        {"rank": 25, "category_name": "Serving Bowls"},
                    ],
                },
            ]
        )
        self.assertEqual(
            rows[0]["subcategory_bsr_ranks"],
            [
                {"rank": 130, "category_name": "Fruit Bowls"},
                {"rank": 25, "category_name": "Serving Bowls"},
            ],
        )

    @unittest.skipIf(front.Workbook is None, "openpyxl is unavailable")
    def test_excel_rank_column_is_wide_enough_for_formatted_values(self) -> None:
        workbook = front.Workbook()
        sheet = workbook.active
        front.write_front_sheet(
            sheet,
            ["ASIN", "子类目节点排名"],
            [{
                "asin": "B000000001",
                "subcategory_bsr_ranks": [
                    {"rank": 11638, "category_name": "Women's Yoga Leggings"}
                ],
            }],
        )
        self.assertEqual(sheet["B2"].value, "#11,638 in Women's Yoga Leggings")
        self.assertGreaterEqual(sheet.column_dimensions["B"].width, 42)


class FrontWorkerTests(unittest.TestCase):
    def test_card_extraction_error_is_not_converted_to_empty_page(self) -> None:
        driver = SimpleNamespace(
            execute_script=lambda *_args: (_ for _ in ()).throw(
                front.JavascriptException("script failed")
            )
        )
        with self.assertRaises(front.JavascriptException):
            front.extract_front_product_cards(driver, False)

    def test_card_extraction_reads_explicit_bsr_list_items(self) -> None:
        class CaptureDriver:
            script = ""

            def execute_script(self, script: str, *_args):
                self.script = script
                return []

        driver = CaptureDriver()
        self.assertEqual(front.extract_front_product_cards(driver, False), [])
        self.assertIn(".rank-number-box .bsr-list-item", driver.script)
        self.assertIn("bsr_text", driver.script)

    def test_manual_coordinator_keeps_nested_pause_until_outer_resume(self) -> None:
        manual = front.ManualActionCoordinator()
        task = {
            "source_type": "storefront",
            "source_id": "source-a",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A",
        }
        manual.begin("tab-1", task, "outer", task["page_url"])
        manual.begin("tab-1", task, "inner", task["page_url"])
        manual.end("tab-1")
        self.assertTrue(manual.is_paused())
        self.assertEqual(manual.snapshot()["tab-1"]["reason"], "outer")
        manual.end("tab-1")
        self.assertFalse(manual.is_paused())

        manual.begin("tab-1", task, "outer", task["page_url"])
        manual.begin("tab-1", task, "inner", task["page_url"])
        manual.release_all("tab-1")
        self.assertFalse(manual.is_paused())

    def test_retry_counter_resets_on_next_page(self) -> None:
        retry_task, should_retry, retry_number = front.prepare_front_retry_task(
            {"source_id": "source-a", "worker_retry_count": 1}
        )
        self.assertTrue(should_retry)
        self.assertEqual(retry_number, 2)
        self.assertEqual(retry_task["worker_retry_count"], 2)

        current = {
            "source_type": "storefront",
            "source_id": "source-a",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A&page=1",
            "worker_retry_count": 2,
        }
        driver = SimpleNamespace(current_url=current["page_url"])
        with patch.object(
            front,
            "find_next_page_url",
            return_value="https://www.amazon.com/s?me=A&page=2",
        ):
            next_task, _reason = front.build_next_front_task(
                driver,
                SimpleNamespace(max_pages_per_keyword=5, store_page_limit=5),
                current,
                [{"asin": "B000000001"}],
            )
        self.assertNotIn("worker_retry_count", next_task)

    def test_two_workers_process_independent_sources_concurrently(self) -> None:
        class FakeDriver:
            def __init__(self) -> None:
                self.current_url = "about:blank"
                self.closed = False

            def quit(self) -> None:
                self.closed = True

        runtime = SimpleNamespace(
            save_debug_snapshots=False,
            delay_seconds_min=0,
            delay_seconds_max=0,
            delivery_location_enabled=False,
            include_sponsored=False,
            field_selectors={},
            product_filters=front.ProductFilterConfig(),
            sellersprite_required=True,
            manual_pause_timeout=1,
        )
        results: "queue.Queue[front.FrontPageResult]" = queue.Queue()
        manual = front.ManualActionCoordinator()
        throttle = front.NavigationThrottle(0, 0)
        locks = front.DeliveryDomainLocks()
        barrier = threading.Barrier(2)
        thread_ids = set()

        def fake_open(driver, url, *_args, **_kwargs) -> None:
            driver.current_url = url

        def fake_merge(_driver, _runtime, current, _plugin_status):
            thread_ids.add(threading.get_ident())
            barrier.wait(timeout=2)
            return [{"asin": current["source_id"], "subcategory_bsr_ranks": []}]

        workers = [
            front.FrontWorker(
                f"tab-{index}",
                runtime,
                results,
                manual,
                throttle,
                locks,
                Path(tempfile.gettempdir()),
            )
            for index in (1, 2)
        ]
        with (
            patch.object(front, "start_driver", side_effect=lambda _runtime: FakeDriver()),
            patch.object(front, "open_amazon_page", side_effect=fake_open),
            patch.object(front, "detect_block", return_value=None),
            patch.object(front, "wait_for_product_cards", return_value=True),
            patch.object(front, "wait_for_sellersprite_data_or_prompt", return_value="ok"),
            patch.object(front, "merge_front_product_data", side_effect=fake_merge),
            patch.object(front, "find_next_page_url", return_value=""),
        ):
            for worker in workers:
                worker.start()
            workers[0].submit(
                {
                    "source_type": "keyword_search",
                    "source_id": "B000000001",
                    "page_number": 1,
                    "page_url": "https://www.amazon.com/s?k=one",
                }
            )
            workers[1].submit(
                {
                    "source_type": "keyword_search",
                    "source_id": "B000000002",
                    "page_number": 1,
                    "page_url": "https://www.amazon.com/s?k=two",
                }
            )
            received = [results.get(timeout=3), results.get(timeout=3)]
            for worker in workers:
                worker.stop()
            for worker in workers:
                worker.join()

        self.assertTrue(
            all(not item.error_reason for item in received),
            [(item.error_reason, item.error_message) for item in received],
        )
        self.assertEqual(len(thread_ids), 2)
        self.assertEqual({item.task["source_id"] for item in received}, {"B000000001", "B000000002"})

    def test_sponsored_only_page_uses_raw_asins_for_pagination(self) -> None:
        class FakeDriver:
            current_url = "https://www.amazon.com/s?k=test&page=1"

            def quit(self) -> None:
                pass

        runtime = SimpleNamespace(
            save_debug_snapshots=False,
            delay_seconds_min=0,
            delay_seconds_max=0,
            delivery_location_enabled=False,
            include_sponsored=False,
            field_selectors={},
            product_filters=front.ProductFilterConfig(),
            sellersprite_required=True,
            manual_pause_timeout=1,
            max_pages_per_keyword=5,
            store_page_limit=5,
        )
        results: "queue.Queue[front.FrontPageResult]" = queue.Queue()
        worker = front.FrontWorker(
            "tab-1",
            runtime,
            results,
            front.ManualActionCoordinator(),
            front.NavigationThrottle(0, 0),
            front.DeliveryDomainLocks(),
            Path(tempfile.gettempdir()),
        )
        task = {
            "source_type": "keyword_search",
            "source_id": "test|sort:Featured",
            "page_number": 1,
            "page_url": FakeDriver.current_url,
        }
        with (
            patch.object(front, "start_driver", return_value=FakeDriver()),
            patch.object(front, "open_amazon_page"),
            patch.object(front, "detect_block", return_value=None),
            patch.object(front, "wait_for_product_cards", return_value=True),
            patch.object(front, "wait_for_sellersprite_data_or_prompt", return_value="ok"),
            patch.object(
                front,
                "merge_front_product_data",
                return_value=[
                    {
                        "asin": "B000000001",
                        "is_sponsored": "yes",
                        "subcategory_bsr_ranks": [],
                    }
                ],
            ),
            patch.object(
                front,
                "find_next_page_url",
                return_value="https://www.amazon.com/s?k=test&page=2",
            ),
        ):
            result = worker._process(task)
        worker._close_driver()

        self.assertEqual([row["asin"] for row in result.raw_records], ["B000000001"])
        self.assertEqual(result.accepted_records, [])
        self.assertEqual(result.rejection_counts, {"sponsored_excluded": 1})
        self.assertEqual(result.next_task["page_number"], 2)

    def test_worker_always_publishes_a_fatal_result_if_process_escapes(self) -> None:
        runtime = SimpleNamespace()
        results: "queue.Queue[front.FrontPageResult]" = queue.Queue()
        worker = front.FrontWorker(
            "tab-1",
            runtime,
            results,
            front.ManualActionCoordinator(),
            front.NavigationThrottle(0, 0),
            front.DeliveryDomainLocks(),
            Path(tempfile.gettempdir()),
        )
        task = {
            "source_type": "storefront",
            "source_id": "source-a",
            "page_number": 1,
            "page_url": "https://www.amazon.com/s?me=A",
        }
        with patch.object(worker, "_process", side_effect=OSError("disk full")):
            worker.start()
            worker.submit(task)
            result = results.get(timeout=2)
            worker.stop()
            self.assertTrue(worker.join(timeout=2))
        self.assertEqual(result.error_reason, "worker_crashed")
        self.assertTrue(result.fatal)


if __name__ == "__main__":
    unittest.main()
