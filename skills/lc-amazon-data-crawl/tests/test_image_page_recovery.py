from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_image_competitor_crawler as image


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class FixedRng:
    def uniform(self, minimum: float, maximum: float) -> float:
        return (float(minimum) + float(maximum)) / 2.0


class MemoryRetryState:
    def __init__(self) -> None:
        self.retry: dict[str, object] | None = None
        self.history: list[dict[str, object]] = []

    def load_amazon_page_retry(self) -> dict[str, object] | None:
        return dict(self.retry) if self.retry is not None else None

    def write_amazon_page_retry(self, retry: object) -> None:
        self.retry = dict(retry)  # type: ignore[arg-type]
        self.history.append(dict(self.retry))

    def clear_amazon_page_retry(self) -> None:
        self.retry = None


class ImageStageRecoveryTests(unittest.TestCase):
    def runtime(self, clock: FakeClock) -> SimpleNamespace:
        return SimpleNamespace(
            marketplace_domain="amazon.com",
            amazon_page_unavailable_retry_schedule_seconds=(
                (180.0, 180.0),
                (180.0, 180.0),
                (1800.0, 1800.0),
                (3600.0, 3600.0),
            ),
            _amazon_page_retry_clock=clock.time,
            _amazon_page_retry_waiter=clock.sleep,
            _amazon_page_retry_rng=FixedRng(),
            _amazon_page_retry_heartbeat_seconds=60.0,
        )

    def test_stage_uses_exactly_five_attempts_and_chunked_fake_waits(self) -> None:
        clock = FakeClock()
        state = MemoryRetryState()
        cleanup_calls: list[int] = []
        attempts: list[int] = []

        def operation(attempt: object) -> str:
            attempt_number = int(getattr(attempt, "attempt_number"))
            attempts.append(attempt_number)
            if attempt_number < 5:
                raise image.TransientAmazonPageUnavailable(
                    "dog page",
                    reason="amazon_dog_error",
                    url="https://www.amazon.com/dp/B000000001",
                )
            return "ok"

        with redirect_stdout(io.StringIO()):
            result = image.run_image_page_stage_with_recovery(
                self.runtime(clock),  # type: ignore[arg-type]
                state,  # type: ignore[arg-type]
                {"source_id": "B000000001"},
                "lens_results",
                "https://www.amazon.com/products?searchtype=flow",
                lambda: cleanup_calls.append(1),
                operation,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, [1, 2, 3, 4, 5])
        self.assertEqual(sum(clock.sleeps), 5760.0)
        self.assertTrue(clock.sleeps)
        self.assertLessEqual(max(clock.sleeps), 60.0)
        self.assertEqual(len(cleanup_calls), 5)
        self.assertIsNone(state.retry)

    def test_fifth_failure_requires_manual_resume_and_same_stage_starts_cycle_two(self) -> None:
        clock = FakeClock()
        runtime = self.runtime(clock)
        runtime.amazon_page_unavailable_retry_schedule_seconds = (
            (0.0, 0.0),
            (0.0, 0.0),
            (0.0, 0.0),
            (0.0, 0.0),
        )
        state = MemoryRetryState()
        failed_attempts: list[int] = []

        def fail(attempt: object) -> None:
            failed_attempts.append(int(getattr(attempt, "attempt_number")))
            raise image.TransientAmazonPageUnavailable(
                "blank",
                reason="blank_page",
            )

        with self.assertRaises(image.AmazonPageRetryExhausted):
            image.run_image_page_stage_with_recovery(
                runtime,  # type: ignore[arg-type]
                state,  # type: ignore[arg-type]
                {"source_id": "B000000001"},
                "source_product",
                "https://www.amazon.com/dp/B000000001",
                lambda: None,
                fail,
            )

        self.assertEqual(failed_attempts, [1, 2, 3, 4, 5])
        self.assertEqual(state.retry["status"], "manual_resume_required")  # type: ignore[index]
        resumed: list[tuple[int, int]] = []
        image.run_image_page_stage_with_recovery(
            runtime,  # type: ignore[arg-type]
            state,  # type: ignore[arg-type]
            {"source_id": "B000000001"},
            "source_product",
            "https://www.amazon.com/dp/B000000001",
            lambda: None,
            lambda attempt: resumed.append(
                (int(getattr(attempt, "cycle")), int(getattr(attempt, "attempt_number")))
            ),
        )
        self.assertEqual(resumed, [(2, 1)])
        self.assertIsNone(state.retry)

    def test_ctrl_c_still_cleans_owned_attempt_pages(self) -> None:
        clock = FakeClock()
        state = MemoryRetryState()
        cleanup_calls: list[int] = []

        def interrupt(_attempt: object) -> None:
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            image.run_image_page_stage_with_recovery(
                self.runtime(clock),  # type: ignore[arg-type]
                state,  # type: ignore[arg-type]
                {"source_id": "B000000001"},
                "lens_upload",
                "https://www.amazon.com/products?searchtype=flow",
                lambda: cleanup_calls.append(1),
                interrupt,
            )

        self.assertEqual(cleanup_calls, [1])
        self.assertEqual(state.retry["status"], "attempting")  # type: ignore[index]
        self.assertEqual(state.retry["stage"], "lens_upload")  # type: ignore[index]


class LensHealthIntegrationTests(unittest.TestCase):
    def test_timeout_accepts_only_explicit_lens_empty_state(self) -> None:
        runtime = SimpleNamespace(page_timeout=1, lens_results_timeout=1)
        state = None
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/products?searchtype=flow"
        driver.title = "Amazon"
        driver.execute_script.return_value = True
        with patch.object(image, "wait_for_lens_results", side_effect=image.TimeoutException()):
            self.assertEqual(
                image.wait_for_lens_results_with_health(driver, runtime, state),
                "no_results",
            )

        driver.execute_script.return_value = False
        with patch.object(image, "wait_for_lens_results", side_effect=image.TimeoutException()):
            with self.assertRaises(image.TransientAmazonPageUnavailable):
                image.wait_for_lens_results_with_health(driver, runtime, state)


class ImageWorkflowRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.products = self.root / "products.csv"
        self.products.write_text(
            "ASIN,主图URL\nB012345678,https://example.invalid/source.jpg\n",
            encoding="utf-8",
        )
        self.source_image = self.root / "source.jpg"
        self.source_image.write_bytes(b"source")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def runtime(self) -> image.ImageCompetitorRuntimeConfig:
        template = json.loads(
            (SKILL_ROOT / "assets/config/amazon_image_competitors.json").read_text(
                encoding="utf-8"
            )
        )
        template.update(
            {
                "job_id": "image-page-recovery",
                "outputs_root": str(self.root / "outputs"),
                "products_file": str(self.products),
                "save_debug_snapshots": False,
                "search_strategy": "amazon_upload",
                "amazon_page_unavailable_retry_schedule_seconds": [
                    [0, 0],
                    [0, 0],
                    [0, 0],
                    [0, 0],
                ],
            }
        )
        return image.build_image_runtime_config(template, no_resume=False)

    def test_ambiguous_empty_exhausts_once_then_same_command_resumes_current(self) -> None:
        runtime = self.runtime()
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/products?searchtype=flow"
        candidate = {
            "source_id": "B012345678#row-2",
            "source_asin": "B012345678",
            "asin": "B000000001",
            "candidate_image_url": "https://example.invalid/candidate.jpg",
            "product_url": "https://www.amazon.com/dp/B000000001",
            "rank": "1",
        }
        evaluation = image.MatchEvaluation(
            accepted_records=[],
            decisions={"B000000001": {"is_competitor": False}},
            prescreen_visual_match_count=0,
            processing_status="verified_zero",
            same_product_count=0,
            same_product_confidence="",
            match_reason="粗筛未发现同款",
            provider_metrics={},
        )

        common_patches = (
            patch.object(image, "prepare_vision_provider"),
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "resolve_source_image", return_value=self.source_image),
            patch.object(image, "run_image_search", return_value="amazon_upload"),
            patch.object(image, "wait_for_lens_results", return_value="results"),
            patch.object(image, "sleep_between_pages"),
        )
        with common_patches[0], common_patches[1], common_patches[2], common_patches[3] as search, common_patches[4], common_patches[5], patch.object(
            image,
            "merge_lens_product_data",
            return_value=[],
        ), self.assertRaisesRegex(image.UserFacingError, "manual_resume_required"):
            image.run_image_competitor_crawl(runtime, dry_run=False)

        job_dir = runtime.outputs_root / runtime.job_id
        state_path = job_dir / "state.json"
        saved = image.load_json(state_path)
        self.assertIsNotNone(saved["current"])
        self.assertEqual(saved["amazon_page_retry"]["status"], "manual_resume_required")
        self.assertEqual(saved["amazon_page_retry"]["stage"], "lens_results")
        failures = image.read_jsonl(job_dir / "failures.jsonl")
        exhausted = [
            row
            for row in failures
            if row.get("reason") == "amazon_page_unavailable_retry_exhausted"
        ]
        self.assertEqual(len(exhausted), 1)
        self.assertFalse((job_dir / "counts.jsonl").exists())
        self.assertEqual(search.call_count, 5)

        with (
            patch.object(image, "prepare_vision_provider"),
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "run_image_search", return_value="amazon_upload"),
            patch.object(image, "wait_for_lens_results", return_value="results"),
            patch.object(image, "merge_lens_product_data", return_value=[candidate]),
            patch.object(image, "evaluate_competitor_matches", return_value=evaluation) as evaluate,
            patch.object(image, "sleep_between_pages"),
        ):
            image.run_image_competitor_crawl(runtime, dry_run=False)

        final_state = image.load_json(state_path)
        self.assertIsNone(final_state["current"])
        self.assertNotIn("amazon_page_retry", final_state)
        self.assertEqual(evaluate.call_count, 1)
        self.assertEqual(len(image.read_jsonl(job_dir / "counts.jsonl")), 1)
        self.assertEqual(
            len(
                [
                    row
                    for row in image.read_jsonl(job_dir / "failures.jsonl")
                    if row.get("reason")
                    == "amazon_page_unavailable_retry_exhausted"
                ]
            ),
            1,
        )

    def test_enrichment_resume_uses_model_checkpoint_without_repeating_model(self) -> None:
        runtime = self.runtime()
        runtime.job_id = "image-enrichment-recovery"
        runtime.result_mode = "detail"
        runtime.match_mode = "embedding"
        runtime.enrich_accepted_results = True
        runtime.sellersprite_required = False
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/s?k=B000000001"
        driver.title = "Amazon search"
        candidate = {
            "source_id": "B012345678",
            "source_asin": "B012345678",
            "asin": "B000000001",
            "candidate_image_url": "https://example.invalid/candidate.jpg",
            "product_url": "https://www.amazon.com/dp/B000000001",
            "rank": "1",
            "load_status": "lens_only",
        }
        evaluation = image.MatchEvaluation(
            accepted_records=[dict(candidate)],
            decisions={"B000000001": {"is_competitor": True}},
            prescreen_visual_match_count="",
            processing_status="verified",
            same_product_count=1,
            same_product_confidence=0.9,
            match_reason="模型已完成",
            provider_metrics={"embedding_api_calls": 2},
        )

        with (
            patch.object(image, "prepare_vision_provider"),
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "resolve_source_image", return_value=self.source_image),
            patch.object(image, "run_image_search", return_value="amazon_upload"),
            patch.object(image, "wait_for_lens_results", return_value="results"),
            patch.object(image, "merge_lens_product_data", return_value=[candidate]),
            patch.object(image, "evaluate_competitor_matches", return_value=evaluation) as evaluate,
            patch.object(image, "open_image_amazon_page"),
            patch.object(image, "wait_for_amazon_products", side_effect=image.TimeoutException()),
            patch.object(image, "sleep_between_pages"),
            patch.object(image, "write_workbook"),
            self.assertRaisesRegex(image.UserFacingError, "manual_resume_required"),
        ):
            image.run_image_competitor_crawl(runtime, dry_run=False)

        job_dir = runtime.outputs_root / runtime.job_id
        state_path = job_dir / "state.json"
        saved = image.load_json(state_path)
        self.assertEqual(evaluate.call_count, 1)
        self.assertIn(image.MODEL_CHECKPOINT_KEY, saved["current"])
        self.assertEqual(
            saved["amazon_page_retry"]["stage"],
            "enrichment_search:B000000001",
        )
        self.assertFalse((job_dir / "records.jsonl").exists())

        with (
            patch.object(image, "prepare_vision_provider"),
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "run_image_search") as search,
            patch.object(image, "evaluate_competitor_matches") as evaluate_again,
            patch.object(image, "open_image_amazon_page"),
            patch.object(image, "wait_for_amazon_products"),
            patch.object(image, "wait_for_sellersprite_data", return_value="not_required"),
            patch.object(image, "merge_lens_product_data", return_value=[candidate]),
            patch.object(image, "sleep_between_pages"),
            patch.object(image, "write_workbook"),
        ):
            image.run_image_competitor_crawl(runtime, dry_run=False)

        search.assert_not_called()
        evaluate_again.assert_not_called()
        final_state = image.load_json(state_path)
        self.assertIsNone(final_state["current"])
        self.assertEqual(len(image.read_jsonl(job_dir / "records.jsonl")), 1)


if __name__ == "__main__":
    unittest.main()
