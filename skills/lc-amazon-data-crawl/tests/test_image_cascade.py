from __future__ import annotations

import json
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


class FakeResponse:
    def __init__(self, status_code: int, payload: object | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def mini_response(matches: object) -> FakeResponse:
    content = json.dumps({"matches": matches}, ensure_ascii=False)
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def candidate(index: int) -> dict[str, object]:
    asin = f"B{index:09d}"
    return {
        "source_asin": "B999999999",
        "asin": asin,
        "candidate_image_url": f"https://example.invalid/{asin}.jpg",
        "rank": str(index),
    }


def mini_match(
    row: dict[str, object],
    *,
    is_same_product: bool,
    confidence: float = 0.9,
    reason: str = "主体商品一致",
) -> dict[str, object]:
    return {
        "asin": row["asin"],
        "is_same_product": is_same_product,
        "confidence": confidence,
        "reason": reason,
    }


class CascadeEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_image = self.root / "source.jpg"
        self.source_image.write_bytes(b"fixture")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def runtime(self, **overrides: object) -> SimpleNamespace:
        raw: dict[str, object] = {
            "match_mode": "cascade",
            "result_mode": "count_only",
            "is_count_only": True,
            "include_source_as_competitor": False,
            "prescreen_min_similarity": 0.75,
            "prescreen_max_matches": 10,
            "mini_batch_size": 6,
            "mini_retry_attempts": 2,
            "mini_retry_backoff_seconds": 0.0,
            "mini_provider": "doubao_mini",
            "mini_api_key": "mini-secret-for-test",
            "mini_model": image.DOUBAO_MINI_MODEL,
            "mini_base_url": image.DOUBAO_MINI_BASE_URL,
            "mini_api_path": image.DOUBAO_MINI_API_PATH,
            "vision_timeout": 10,
            "max_competitors_per_source": 48,
            "min_match_confidence": 0.7,
            "provider_metrics": {},
        }
        raw.update(overrides)
        return SimpleNamespace(**raw)

    def evaluate(
        self,
        records: list[dict[str, object]],
        embedding_vectors: list[list[float]],
        mini_side_effect: object | None = None,
    ) -> tuple[image.MatchEvaluation, object, object]:
        runtime = self.runtime()
        with (
            patch.object(
                image,
                "call_multimodal_embedding_cached",
                side_effect=embedding_vectors,
            ) as embed,
            patch.object(
                image,
                "call_doubao_mini_verifier",
                side_effect=mini_side_effect,
            ) as mini,
        ):
            result = image.evaluate_competitor_matches(
                runtime,
                self.source_image,
                "",
                records,
            )
        return result, embed, mini

    def test_zero_prescreen_matches_is_verified_zero_without_mini(self) -> None:
        records = [candidate(index) for index in range(1, 5)]
        result, embed, mini = self.evaluate(
            records,
            [[1.0, 0.0]] + [[0.0, 1.0]] * len(records),
        )
        self.assertIsInstance(result, image.MatchEvaluation)
        self.assertEqual(result.prescreen_visual_match_count, 0)
        self.assertEqual(result.processing_status, "verified_zero")
        self.assertEqual(result.same_product_count, 0)
        self.assertEqual(result.same_product_confidence, "")
        self.assertTrue(result.match_reason)
        self.assertEqual(result.accepted_records, [])
        self.assertEqual(embed.call_count, 1 + len(records))
        mini.assert_not_called()

    def test_one_prescreen_match_is_verified_by_mini(self) -> None:
        records = [candidate(index) for index in range(1, 4)]
        mini_rows = [mini_match(records[0], is_same_product=True, confidence=0.91)]
        result, _, mini = self.evaluate(
            records,
            [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]],
            [mini_rows],
        )
        self.assertEqual(result.prescreen_visual_match_count, 1)
        self.assertEqual(result.processing_status, "verified")
        self.assertEqual(result.same_product_count, 1)
        self.assertEqual(result.same_product_confidence, 0.91)
        self.assertEqual([row["asin"] for row in result.accepted_records], [records[0]["asin"]])
        self.assertEqual(mini.call_count, 1)
        self.assertEqual(len(mini.call_args.args[2]), 1)

    def test_ten_prescreen_matches_use_six_plus_four_mini_batches(self) -> None:
        records = [candidate(index) for index in range(1, 11)]
        first = [mini_match(row, is_same_product=True, confidence=0.92) for row in records[:6]]
        second = [mini_match(row, is_same_product=True, confidence=0.81) for row in records[6:]]
        result, embed, mini = self.evaluate(
            records,
            [[1.0, 0.0]] + [[1.0, 0.0]] * 10,
            [first, second],
        )
        self.assertEqual(result.prescreen_visual_match_count, 10)
        self.assertEqual(result.processing_status, "verified")
        self.assertEqual(result.same_product_count, 10)
        self.assertEqual(result.same_product_confidence, 0.81)
        self.assertEqual(embed.call_count, 11)
        self.assertEqual([len(call.args[2]) for call in mini.call_args_list], [6, 4])

    def test_eleventh_prescreen_match_stops_immediately_and_skips_mini(self) -> None:
        records = [candidate(index) for index in range(1, 20)]
        result, embed, mini = self.evaluate(
            records,
            [[1.0, 0.0]] + [[1.0, 0.0]] * 11,
        )
        self.assertIn(result.prescreen_visual_match_count, (11, "11+"))
        self.assertEqual(result.processing_status, "prescreen_excluded")
        self.assertIsNone(result.same_product_count)
        self.assertEqual(result.same_product_confidence, "")
        self.assertTrue(result.match_reason)
        self.assertEqual(result.accepted_records, [])
        self.assertEqual(embed.call_count, 12, "只允许来源图加前 11 个候选向量请求")
        mini.assert_not_called()

    def test_final_result_only_accepts_mini_positive_decisions(self) -> None:
        records = [candidate(index) for index in range(1, 3)]
        decisions = [
            mini_match(records[0], is_same_product=False, confidence=0.99, reason="主体结构不同"),
            mini_match(records[1], is_same_product=True, confidence=0.83),
        ]
        result, _, _ = self.evaluate(
            records,
            [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]],
            [decisions],
        )
        self.assertEqual(result.same_product_count, 1)
        self.assertEqual(result.same_product_confidence, 0.83)
        self.assertEqual([row["asin"] for row in result.accepted_records], [records[1]["asin"]])
        self.assertFalse(result.decisions[str(records[0]["asin"])]["is_competitor"])
        self.assertTrue(result.decisions[str(records[1]["asin"])]["is_competitor"])

    def test_verified_with_no_mini_positive_keeps_blank_confidence(self) -> None:
        records = [candidate(1)]
        result, _, _ = self.evaluate(
            records,
            [[1.0, 0.0], [1.0, 0.0]],
            [[mini_match(records[0], is_same_product=False, confidence=0.97)]],
        )
        self.assertEqual(result.processing_status, "verified")
        self.assertEqual(result.same_product_count, 0)
        self.assertEqual(result.same_product_confidence, "")
        self.assertEqual(result.accepted_records, [])


class MiniStrictJsonTests(unittest.TestCase):
    def runtime(self, **overrides: object) -> SimpleNamespace:
        raw: dict[str, object] = {
            "mini_api_key": "mini-secret-for-test",
            "mini_model": image.DOUBAO_MINI_MODEL,
            "mini_base_url": image.DOUBAO_MINI_BASE_URL,
            "mini_api_path": image.DOUBAO_MINI_API_PATH,
            "mini_retry_attempts": 2,
            "mini_retry_backoff_seconds": 0.0,
            "vision_timeout": 10,
            "provider_metrics": {},
        }
        raw.update(overrides)
        return SimpleNamespace(**raw)

    def source_image(self, root: Path) -> Path:
        path = root / "source.jpg"
        path.write_bytes(b"fixture")
        return path

    def test_malformed_json_retries_whole_batch_then_succeeds(self) -> None:
        rows = [candidate(1), candidate(2)]
        valid = [mini_match(row, is_same_product=True) for row in rows]
        malformed = FakeResponse(
            200,
            {"choices": [{"message": {"content": "not-json"}}]},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.source_image(Path(temp_dir))
            with (
                patch.object(image.requests, "post", side_effect=[malformed, mini_response(valid)]) as post,
                patch.object(image.time, "sleep") as sleep,
            ):
                result = image.call_doubao_mini_verifier(self.runtime(), source, rows)
        self.assertEqual(result, valid)
        self.assertEqual(post.call_count, 2)
        self.assertLessEqual(sleep.call_count, 1)

    def test_ark_multimodal_chat_contract_and_usage_metrics(self) -> None:
        rows = [candidate(1), candidate(2)]
        matches = [mini_match(row, is_same_product=True) for row in rows]
        response = mini_response(matches)
        response._payload["usage"] = {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "prompt_tokens_details": {"image_tokens": 90},
        }
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.source_image(Path(temp_dir))
            with patch.object(image.requests, "post", return_value=response) as post:
                image.call_doubao_mini_verifier(runtime, source, rows)
        self.assertEqual(
            post.call_args.args[0],
            "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], image.DOUBAO_MINI_MODEL)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        content = payload["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(
            [item["type"] for item in content].count("image_url"),
            1 + len(rows),
        )
        self.assertEqual(runtime.provider_metrics["mini_api_calls"], 1)
        self.assertEqual(runtime.provider_metrics["mini_prompt_tokens"], 120)
        self.assertEqual(runtime.provider_metrics["mini_completion_tokens"], 30)
        self.assertEqual(runtime.provider_metrics["mini_total_tokens"], 150)
        self.assertEqual(runtime.provider_metrics["mini_image_tokens"], 90)
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)

    def test_mini_response_rejects_wrappers_extra_root_fields_and_wrong_scalar_types(self) -> None:
        rows = [candidate(1)]
        valid_match = mini_match(rows[0], is_same_product=True)
        valid_json = json.dumps({"matches": [valid_match]}, ensure_ascii=False)
        invalid_responses = {
            "markdown_fence": f"```json\n{valid_json}\n```",
            "leading_prose": f"以下是结果：\n{valid_json}",
            "trailing_prose": f"{valid_json}\n以上为结果。",
            "extra_root_field": json.dumps(
                {"matches": [valid_match], "note": "unexpected"},
                ensure_ascii=False,
            ),
            "string_confidence": json.dumps(
                {"matches": [{**valid_match, "confidence": "0.9"}]},
                ensure_ascii=False,
            ),
            "nonstring_reason": json.dumps(
                {"matches": [{**valid_match, "reason": 123}]},
                ensure_ascii=False,
            ),
            "nonstring_asin": json.dumps(
                {"matches": [{**valid_match, "asin": 123}]},
                ensure_ascii=False,
            ),
        }
        for label, response_text in invalid_responses.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    image.parse_mini_match_response(response_text, rows)

    def test_mini_redirect_is_not_followed_and_fails_closed(self) -> None:
        rows = [candidate(1)]
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.source_image(Path(temp_dir))
            with patch.object(
                image.requests,
                "post",
                return_value=FakeResponse(307, text="redirect"),
            ) as post:
                with self.assertRaises(image.FatalMiniProviderError):
                    image.call_doubao_mini_verifier(runtime, source, rows)

        self.assertEqual(post.call_count, 1)
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)

    def test_strict_schema_rejects_missing_duplicate_unknown_and_nonboolean(self) -> None:
        rows = [candidate(1), candidate(2)]
        valid_first = mini_match(rows[0], is_same_product=True)
        valid_second = mini_match(rows[1], is_same_product=False)
        invalid_payloads = {
            "missing": [valid_first],
            "duplicate": [valid_first, dict(valid_first)],
            "unknown": [valid_first, {**valid_second, "asin": "B888888888"}],
            "nonboolean": [valid_first, {**valid_second, "is_same_product": "false"}],
            "extra_field": [valid_first, {**valid_second, "unexpected": 1}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.source_image(Path(temp_dir))
            for label, matches in invalid_payloads.items():
                with self.subTest(label=label):
                    with patch.object(image.requests, "post", return_value=mini_response(matches)) as post:
                        with self.assertRaises(image.MiniProviderError):
                            image.call_doubao_mini_verifier(
                                self.runtime(mini_retry_attempts=1),
                                source,
                                rows,
                            )
                    self.assertEqual(post.call_count, 1)

    def test_retry_exhaustion_never_defaults_missing_items_to_false(self) -> None:
        rows = [candidate(1), candidate(2)]
        missing = [mini_match(rows[0], is_same_product=True)]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.source_image(Path(temp_dir))
            with patch.object(image.requests, "post", return_value=mini_response(missing)) as post:
                with self.assertRaises(image.MiniProviderError):
                    image.call_doubao_mini_verifier(
                        self.runtime(mini_retry_attempts=2),
                        source,
                        rows,
                    )
        self.assertEqual(post.call_count, 2)

    def test_fatal_auth_error_does_not_retry_or_leak_mini_key(self) -> None:
        rows = [candidate(1)]
        runtime = self.runtime()
        secret = str(runtime.mini_api_key)
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.source_image(Path(temp_dir))
            with patch.object(
                image.requests,
                "post",
                return_value=FakeResponse(401, text=f"Bearer {secret}"),
            ) as post:
                with self.assertRaises(image.FatalMiniProviderError) as caught:
                    image.call_doubao_mini_verifier(runtime, source, rows)
        self.assertEqual(post.call_count, 1)
        self.assertNotIn(secret, str(caught.exception))


class CascadeConfigFingerprintAndOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.products = self.root / "products.csv"
        self.products.write_text(
            "ASIN,商品URL,主图URL,本地图片路径,备注\nB012345678,,,,fixture\n",
            encoding="utf-8",
        )
        self.embedding_config = self.root / "embedding.json"
        self.embedding_config.write_text(
            json.dumps(
                {
                    "api_key": "embedding-secret",
                    "model": image.DOUBAO_EMBEDDING_MODEL,
                    "base_url": image.DOUBAO_EMBEDDING_BASE_URL,
                    "api_path": image.DOUBAO_EMBEDDING_API_PATH,
                    "encoding_format": "float",
                }
            ),
            encoding="utf-8",
        )
        self.mini_config = self.root / "mini.json"
        self.mini_config.write_text(
            json.dumps(
                {
                    "api_key": "mini-secret",
                    "model": image.DOUBAO_MINI_MODEL,
                    "base_url": image.DOUBAO_MINI_BASE_URL,
                    "api_path": image.DOUBAO_MINI_API_PATH,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def raw_config(self, **overrides: object) -> dict[str, object]:
        raw: dict[str, object] = {
            "job_id": "cascade-test",
            "outputs_root": str(self.root / "outputs"),
            "products_file": str(self.products),
            "marketplace": "美国站",
            "result_mode": "count_only",
            "match_mode": "cascade",
            "doubao_embedding_config_file": str(self.embedding_config),
            "prescreen_min_similarity": 0.75,
            "prescreen_max_matches": 10,
            "doubao_mini_config_file": str(self.mini_config),
            "mini_batch_size": 6,
            "mini_retry_attempts": 2,
            "mini_retry_backoff_seconds": 0.0,
            "browser_backend": "cdp",
            "browser_mode": "reuse",
            "extension_path": "auto",
        }
        raw.update(overrides)
        return raw

    def prepared_runtime(self, **overrides: object) -> image.ImageCompetitorRuntimeConfig:
        runtime = image.build_image_runtime_config(self.raw_config(**overrides), no_resume=False)
        image.prepare_vision_provider(runtime)
        return runtime

    def commit_test_source_shard(
        self,
        runtime: image.ImageCompetitorRuntimeConfig,
        *,
        shard_dir: Path,
        current: dict[str, object] | None = None,
        candidate_asins: tuple[str, ...] = ("B000000001", "B000000002"),
        accepted_asins: tuple[str, ...] = ("B000000001",),
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        list[dict[str, object]],
        list[dict[str, object]],
        dict[str, object],
    ]:
        queue = image.load_products(
            runtime.products_file,
            runtime.marketplace_domain,
            dedupe=False,
        )
        source = dict(current or queue[0])
        crawl_plan = image.image_crawl_plan_fingerprint(runtime, queue)
        provider = image.vision_provider_fingerprint(runtime)
        candidate_rows = [
            {
                "source_id": source["source_id"],
                "source_asin": source["source_asin"],
                "asin": asin,
                "is_competitor": asin in accepted_asins,
            }
            for asin in candidate_asins
        ]
        accepted_rows = [
            {
                "source_id": source["source_id"],
                "source_asin": source["source_asin"],
                "asin": asin,
                "is_competitor": True,
            }
            for asin in accepted_asins
        ]
        evaluation = image.MatchEvaluation(
            accepted_records=accepted_rows,
            decisions={},
            prescreen_visual_match_count=len(candidate_rows),
            processing_status="verified",
            same_product_count=len(accepted_rows),
            same_product_confidence=0.9,
            match_reason="test shard",
        )
        count_row = image.build_count_result_row(
            runtime,
            source,
            "amazon_upload",
            "skipped_on_lens",
            len(candidate_rows),
            evaluation,
        )
        image.commit_source_result_shard(
            shard_dir,
            source,
            crawl_plan,
            provider,
            candidate_rows,
            accepted_rows,
            count_row,
        )
        return source, crawl_plan, provider, candidate_rows, accepted_rows, count_row

    def test_cascade_is_count_only_and_validates_bounds(self) -> None:
        with self.assertRaisesRegex(image.UserFacingError, "count_only"):
            image.build_image_runtime_config(
                self.raw_config(result_mode="detail"),
                no_resume=False,
            )
        for key, value in (
            ("prescreen_min_similarity", -0.01),
            ("prescreen_min_similarity", 1.01),
            ("prescreen_max_matches", 0),
            ("mini_batch_size", 0),
            ("mini_retry_attempts", 0),
            ("mini_retry_backoff_seconds", -0.1),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaises(image.UserFacingError):
                    image.build_image_runtime_config(
                        self.raw_config(**{key: value}),
                        no_resume=False,
                    )

    def test_cascade_dry_run_requires_both_provider_credentials_before_browser(self) -> None:
        self.mini_config.write_text(json.dumps({"api_key": ""}), encoding="utf-8")
        runtime = image.build_image_runtime_config(self.raw_config(), no_resume=False)
        with patch.object(image, "start_driver") as start_driver:
            with self.assertRaisesRegex(image.UserFacingError, "Mini.*API Key|API Key.*为空"):
                image.run_image_competitor_crawl(runtime, dry_run=True)
        start_driver.assert_not_called()

    def test_private_mini_config_rejects_insecure_or_ambiguous_endpoints(self) -> None:
        invalid_endpoints = {
            "http": {"base_url": "http://ark.cn-beijing.volces.com/api/v3"},
            "userinfo": {
                "base_url": "https://user:password@ark.cn-beijing.volces.com/api/v3"
            },
            "query_in_base": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3?region=test"
            },
            "fragment_in_base": {
                "base_url": "https://ark.cn-beijing.volces.com/api/v3#credentials"
            },
            "query_in_path": {"api_path": "chat/completions?region=test"},
            "fragment_in_path": {"api_path": "chat/completions#credentials"},
        }
        for label, overrides in invalid_endpoints.items():
            with self.subTest(label=label):
                raw = {
                    "api_key": "mini-secret",
                    "model": image.DOUBAO_MINI_MODEL,
                    "base_url": image.DOUBAO_MINI_BASE_URL,
                    "api_path": image.DOUBAO_MINI_API_PATH,
                    **overrides,
                }
                self.mini_config.write_text(json.dumps(raw), encoding="utf-8")
                runtime = image.build_image_runtime_config(self.raw_config(), no_resume=False)
                with self.assertRaises(image.UserFacingError):
                    image.prepare_vision_provider(runtime)

    def test_cascade_fingerprint_covers_semantics_and_never_secrets(self) -> None:
        runtime = self.prepared_runtime()
        fingerprint = image.vision_provider_fingerprint(runtime)
        serialized = json.dumps(fingerprint, ensure_ascii=False)
        self.assertEqual(fingerprint["match_mode"], "cascade")
        self.assertEqual(fingerprint["prescreen_min_similarity"], 0.75)
        self.assertEqual(fingerprint["prescreen_max_matches"], 10)
        self.assertEqual(fingerprint["mini_batch_size"], 6)
        self.assertIn(image.CASCADE_MATCH_SEMANTICS, serialized)
        self.assertIn(image.MINI_RESPONSE_SEMANTICS, serialized)
        self.assertNotIn(runtime.embedding_api_key, serialized)
        self.assertNotIn(runtime.mini_api_key, serialized)

        changed = self.prepared_runtime(prescreen_min_similarity=0.76)
        self.assertNotEqual(
            fingerprint["sha256"],
            image.vision_provider_fingerprint(changed)["sha256"],
        )

    def test_cascade_crawl_plan_fingerprint_changes_with_file_bytes_and_normalized_queue(self) -> None:
        runtime = self.prepared_runtime()
        original_queue = image.load_products(
            runtime.products_file,
            runtime.marketplace_domain,
            dedupe=False,
        )
        original = image.image_crawl_plan_fingerprint(runtime, original_queue)

        # Even a byte-level input edit that leaves the normalized queue unchanged
        # must invalidate a resumable cascade checkpoint.
        self.products.write_text(
            self.products.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        same_queue = image.load_products(
            runtime.products_file,
            runtime.marketplace_domain,
            dedupe=False,
        )
        file_changed = image.image_crawl_plan_fingerprint(runtime, same_queue)
        self.assertEqual(original_queue, same_queue)
        self.assertNotEqual(original["sha256"], file_changed["sha256"])

        # A normalized queue/order change must also produce a different plan.
        self.products.write_text(
            "ASIN,商品URL,主图URL,本地图片路径,备注\n"
            "B087654321,,,,second\n"
            "B012345678,,,,fixture\n",
            encoding="utf-8",
        )
        changed_queue = image.load_products(
            runtime.products_file,
            runtime.marketplace_domain,
            dedupe=False,
        )
        queue_changed = image.image_crawl_plan_fingerprint(runtime, changed_queue)
        self.assertNotEqual(original_queue, changed_queue)
        self.assertNotEqual(file_changed["sha256"], queue_changed["sha256"])

    def test_changed_cascade_fingerprint_rejects_completed_checkpoint(self) -> None:
        runtime = self.prepared_runtime()
        state_path = self.root / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "job_id": runtime.job_id,
                    "records_count": 1,
                    "completed_sources": ["B012345678"],
                    "delivery_location_fingerprint": runtime.delivery_location_fingerprint,
                    "vision_provider_fingerprint": {"sha256": "old"},
                }
            ),
            encoding="utf-8",
        )
        store = image.ImageCompetitorStateStore(state_path, runtime, [])
        with self.assertRaisesRegex(image.UserFacingError, "新的 job_id"):
            store.load_or_create()

    def test_legacy_embedding_and_chat_fingerprints_do_not_gain_cascade_fields(self) -> None:
        base = {
            "min_match_confidence": 0.7,
            "delivery_location_fingerprint": "delivery-v1",
            "prescreen_min_similarity": 0.75,
            "prescreen_max_matches": 10,
            "mini_batch_size": 6,
            "mini_model": image.DOUBAO_MINI_MODEL,
            "mini_base_url": image.DOUBAO_MINI_BASE_URL,
            "mini_api_path": image.DOUBAO_MINI_API_PATH,
        }
        embedding_runtime = SimpleNamespace(
            **base,
            match_mode="embedding",
            embedding_provider="doubao",
            embedding_model=image.DOUBAO_EMBEDDING_MODEL,
            embedding_base_url=image.DOUBAO_EMBEDDING_BASE_URL,
            embedding_api_path=image.DOUBAO_EMBEDDING_API_PATH,
            embedding_encoding_format="float",
        )
        chat_runtime = SimpleNamespace(
            **base,
            match_mode="chat",
            vision_model="legacy-chat",
            openai_base_url="https://api.openai.com/v1",
            openai_api_path="chat/completions",
        )
        for runtime in (embedding_runtime, chat_runtime):
            fingerprint = image.vision_provider_fingerprint(runtime)
            self.assertNotIn("prescreen_min_similarity", fingerprint)
            self.assertNotIn("prescreen_max_matches", fingerprint)
            self.assertNotIn("mini_model", fingerprint)
            self.assertNotIn("cascade_semantics", fingerprint)

    def test_count_workbook_uses_fixed_review_layout_and_keeps_mini_only_in_jsonl(self) -> None:
        if image.Workbook is None or image.load_workbook is None:
            self.skipTest("openpyxl unavailable")
        source = self.root / "input.xlsx"
        wb = image.Workbook()
        ws = wb.active
        ws.append(
            [
                "ASIN",
                "最佳页码",
                "最佳排名",
                "商品URL",
                "加载状态",
                "备注",
                image.MINI_CONFIRMED_COUNT_HEADER,
                image.COUNT_COLUMN_HEADER,
            ]
        )
        ws.append(["B000000001", 3, 8, "https://example.test/dp/B000000001", "ok", "x", 99, 999])
        ws.append(["B000000002", 5, 6, "https://example.test/dp/B000000002", "ok", "x", 99, 999])
        ws.append(["B000000003", 7, 4, "https://example.test/dp/B000000003", "ok", "x", 99, 999])
        wb.save(source)

        counts = self.root / "counts.jsonl"
        rows = [
            {
                "match_mode": "cascade",
                "input_row": 2,
                "source_product_url": "https://www.amazon.com/dp/B000000001",
                "prescreen_visual_match_count": "11+",
                "processing_status": "prescreen_excluded",
                "same_product_count": None,
                "same_product_confidence": "",
                "match_reason": "粗筛命中第 11 个，停止精审",
            },
            {
                "match_mode": "cascade",
                "input_row": 3,
                "source_product_url": "https://www.amazon.com/dp/B000000002",
                "prescreen_visual_match_count": 0,
                "processing_status": "verified_zero",
                "same_product_count": 0,
                "same_product_confidence": "",
                "match_reason": "粗筛无命中",
            },
            {
                "match_mode": "cascade",
                "input_row": 4,
                "source_product_url": "https://www.amazon.com/dp/B000000003",
                "prescreen_visual_match_count": 2,
                "processing_status": "verified",
                "same_product_count": 2,
                "same_product_confidence": 0.84,
                "match_reason": "Mini 已完成精审",
            },
        ]
        counts.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        output = self.root / "output.xlsx"
        image.write_count_only_workbook(source, counts, output)

        out_wb = image.load_workbook(output, data_only=True)
        out_ws = out_wb.active
        headers = [out_ws.cell(1, column).value for column in range(1, out_ws.max_column + 1)]
        expected_headers = [
            image.COUNT_COLUMN_HEADER,
            "视觉粗筛命中数",
            "处理状态",
            "同款判断置信度",
            "同款判断说明",
        ]
        for header in expected_headers:
            self.assertEqual(headers.count(header), 1)
        for removed_header in (
            "最佳页码",
            "最佳排名",
            "加载状态",
            "备注",
            image.MINI_CONFIRMED_COUNT_HEADER,
        ):
            self.assertNotIn(removed_header, headers)
        by_header = {header: headers.index(header) + 1 for header in expected_headers}
        count_col = by_header[image.COUNT_COLUMN_HEADER]
        self.assertEqual(headers[count_col - 2], image.REVIEW_PRODUCT_URL_HEADER)
        self.assertEqual(headers.count(image.REVIEW_PRODUCT_URL_HEADER), 2)
        self.assertEqual(
            out_ws.cell(2, count_col - 1).value,
            "https://www.amazon.com/dp/B000000001",
        )
        self.assertEqual(
            out_ws.cell(2, count_col - 1).hyperlink.target,
            "https://www.amazon.com/dp/B000000001",
        )
        self.assertIsNone(out_ws.cell(2, by_header[image.COUNT_COLUMN_HEADER]).value)
        self.assertEqual(out_ws.cell(3, by_header[image.COUNT_COLUMN_HEADER]).value, 0)
        self.assertEqual(out_ws.cell(4, by_header[image.COUNT_COLUMN_HEADER]).value, 2)
        self.assertEqual(out_ws.cell(2, by_header["视觉粗筛命中数"]).value, "11+")
        self.assertEqual(out_ws.cell(2, by_header["处理状态"]).value, "prescreen_excluded")
        self.assertEqual(out_ws.cell(4, by_header["同款判断置信度"]).value, 0.84)
        self.assertEqual(out_ws.cell(4, by_header["同款判断说明"]).value, "Mini 已完成精审")

    def test_count_workbook_preserves_legacy_cap_but_cascade_uses_exact_mini_count(self) -> None:
        if image.Workbook is None or image.load_workbook is None:
            self.skipTest("openpyxl unavailable")
        source = self.root / "count-semantics-input.xlsx"
        wb = image.Workbook()
        ws = wb.active
        ws.append(["ASIN", image.COUNT_COLUMN_HEADER])
        ws.append(["B000000001", 999])
        ws.append(["B000000002", 999])
        ws.append(["B000000003", 999])
        wb.save(source)

        counts = self.root / "count-semantics.jsonl"
        counts.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in (
                    {
                        "match_mode": "embedding",
                        "input_row": 2,
                        "similar_count": 48,
                        "count_display": "48+",
                        "same_product_count": 48,
                    },
                    {
                        "match_mode": "chat",
                        "input_row": 3,
                        "similar_count": 48,
                        "count_display": "48+",
                        "same_product_count": 48,
                    },
                    {
                        "match_mode": "cascade",
                        "input_row": 4,
                        "similar_count": 10,
                        "count_display": "10+",
                        "same_product_count": 10,
                        "processing_status": "verified",
                    },
                )
            ),
            encoding="utf-8",
        )
        output = self.root / "count-semantics-output.xlsx"
        image.write_count_only_workbook(source, counts, output)

        out_wb = image.load_workbook(output, data_only=True)
        out_ws = out_wb.active
        headers = [out_ws.cell(1, column).value for column in range(1, out_ws.max_column + 1)]
        count_col = headers.index(image.COUNT_COLUMN_HEADER) + 1
        self.assertEqual(out_ws.cell(2, count_col).value, "48+")
        self.assertEqual(out_ws.cell(3, count_col).value, "48+")
        self.assertEqual(out_ws.cell(4, count_col).value, 10)

    def test_count_jsonl_contract_always_contains_mini_only_count_field(self) -> None:
        fields = {
            "prescreen_visual_match_count",
            "processing_status",
            "same_product_count",
            "same_product_confidence",
            "match_reason",
            image.MINI_CONFIRMED_COUNT_FIELD,
        }
        evaluation = image.MatchEvaluation(
            accepted_records=[],
            decisions={},
            prescreen_visual_match_count="11+",
            processing_status="prescreen_excluded",
            same_product_count=None,
            same_product_confidence="",
            match_reason="粗筛命中第 11 个，停止精审",
        )
        counts_path = self.root / "counts.jsonl"
        runtime = SimpleNamespace(max_candidates_per_source=48, match_mode="cascade")
        image.append_count_result(
            counts_path,
            runtime,
            {"source_id": "row-2", "input_row": 2},
            "amazon_upload",
            "skipped_on_lens",
            48,
            evaluation,
        )
        row = json.loads(counts_path.read_text(encoding="utf-8"))
        self.assertTrue(fields.issubset(row))
        self.assertIsNone(row["same_product_count"])
        self.assertEqual(row["processing_status"], "prescreen_excluded")
        self.assertEqual(
            row[image.MINI_CONFIRMED_COUNT_FIELD],
            image.EMBEDDING_GREATER_THAN_TEN_LABEL,
        )

    def test_mini_only_count_keeps_embedding_zero_blank(self) -> None:
        cases = (
            (
                {"match_mode": "cascade", "processing_status": "verified", "same_product_count": 0},
                0,
            ),
            (
                {"match_mode": "cascade", "processing_status": "verified_zero", "same_product_count": 0},
                "",
            ),
            (
                {"match_mode": "cascade", "processing_status": "prescreen_excluded", "same_product_count": None},
                image.EMBEDDING_GREATER_THAN_TEN_LABEL,
            ),
            (
                {"match_mode": "embedding", "processing_status": "verified", "same_product_count": 3},
                "",
            ),
        )
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(image.mini_confirmed_same_product_count_value(row), expected)

    def test_lens_candidate_extraction_uses_one_combined_dom_order_query(self) -> None:
        captured: dict[str, str] = {}

        class Driver:
            page_source = ""

            def execute_script(self, script: str, include_text: bool) -> list[dict[str, object]]:
                captured["script"] = script
                return [candidate(1)]

        rows = image.extract_lens_candidate_cards(Driver(), include_text=False)
        self.assertEqual([row["asin"] for row in rows], [candidate(1)["asin"]])
        script = captured["script"]
        self.assertEqual(
            script.count("document.querySelectorAll(selectors.join(','))"),
            1,
            "候选卡必须由一个合并 selector 查询，浏览器才会按 DOM 顺序返回节点",
        )
        self.assertNotIn("const seenElements = new Set()", script)
        self.assertNotIn("for (const el of document.querySelectorAll(selector))", script)

    def test_source_shards_rebuild_corrupt_aggregates_once_and_deterministically(self) -> None:
        runtime = self.prepared_runtime(job_id="cascade-shard-rebuild")
        shard_dir = self.root / "source-results-rebuild"
        source, plan, provider, first_candidates, first_accepted, _ = (
            self.commit_test_source_shard(runtime, shard_dir=shard_dir)
        )
        second_source = {
            **source,
            "input_row": 3,
            "source_id": "row-3:B087654321",
            "source_asin": "B087654321",
            "source_product_url": "https://www.amazon.com/dp/B087654321",
        }
        _, _, _, second_candidates, second_accepted, _ = self.commit_test_source_shard(
            runtime,
            shard_dir=shard_dir,
            current=second_source,
            candidate_asins=("B000000003", "B000000004"),
            accepted_asins=("B000000004",),
        )
        candidates_path = self.root / "rebuild-candidates.jsonl"
        records_path = self.root / "rebuild-records.jsonl"
        counts_path = self.root / "rebuild-counts.jsonl"
        for aggregate_path in (candidates_path, records_path, counts_path):
            aggregate_path.write_text(
                '{"stale":true}\n{"truncated":',
                encoding="utf-8",
            )

        committed = image.materialize_source_result_shards(
            shard_dir,
            plan,
            provider,
            candidates_path,
            records_path,
            counts_path,
        )
        expected_candidates = first_candidates + second_candidates
        expected_accepted = first_accepted + second_accepted
        self.assertEqual(sorted(committed), [2, 3])
        self.assertEqual(image.read_jsonl(candidates_path), expected_candidates)
        self.assertEqual(image.read_jsonl(records_path), expected_accepted)
        self.assertEqual(len(image.read_jsonl(counts_path)), 2)
        self.assertEqual(
            len(
                {
                    (row["source_id"], row["asin"])
                    for row in image.read_jsonl(candidates_path)
                }
            ),
            len(expected_candidates),
        )
        self.assertEqual(
            len(
                {
                    (row["source_id"], row["asin"])
                    for row in image.read_jsonl(records_path)
                }
            ),
            len(expected_accepted),
        )
        first_materialization = {
            path.name: path.read_bytes()
            for path in (candidates_path, records_path, counts_path)
        }

        image.materialize_source_result_shards(
            shard_dir,
            plan,
            provider,
            candidates_path,
            records_path,
            counts_path,
        )
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in (candidates_path, records_path, counts_path)
            },
            first_materialization,
        )

    def test_committed_shard_before_state_finish_resumes_without_second_model_run(self) -> None:
        runtime = self.prepared_runtime(
            job_id="cascade-shard-resume",
            search_strategy="amazon_upload",
            sellersprite_on_lens=False,
            enrich_accepted_results=False,
        )
        queue = image.load_products(
            runtime.products_file,
            runtime.marketplace_domain,
            dedupe=False,
        )
        current = queue[0]
        source_image = self.root / "resume-source.jpg"
        source_image.write_bytes(b"source")
        candidate_row = {
            "source_id": current["source_id"],
            "source_asin": current["source_asin"],
            "asin": "B000000001",
            "candidate_image_url": "https://example.invalid/B000000001.jpg",
            "product_url": "https://www.amazon.com/dp/B000000001",
            "rank": "1",
        }
        mini_rows = [mini_match(candidate_row, is_same_product=True, confidence=0.93)]
        driver = MagicMock()
        real_materialize = image.materialize_source_result_shards

        with (
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "ensure_lens_supported"),
            patch.object(image, "resolve_source_image", return_value=source_image) as resolve,
            patch.object(image, "run_image_search", return_value="amazon_upload"),
            patch.object(image, "detect_block", return_value=""),
            patch.object(image, "wait_for_lens_results"),
            patch.object(image, "merge_lens_product_data", return_value=[candidate_row]),
            patch.object(
                image,
                "call_multimodal_embedding_cached",
                side_effect=[[1.0, 0.0], [1.0, 0.0]],
            ) as embedding,
            patch.object(
                image,
                "call_doubao_mini_verifier",
                return_value=mini_rows,
            ) as mini,
            patch.object(image, "sleep_between_pages"),
        ):
            with patch.object(
                image,
                "materialize_source_result_shards",
                side_effect=OSError("injected crash after shard commit"),
            ):
                with self.assertRaisesRegex(OSError, "after shard commit"):
                    image.run_image_competitor_crawl(runtime, dry_run=False)

            shard_dir = runtime.outputs_root / runtime.job_id / "source_results"
            self.assertEqual(len(list(shard_dir.glob("*.json"))), 1)
            state_after_crash = image.load_json(
                runtime.outputs_root / runtime.job_id / "state.json"
            )
            self.assertEqual(state_after_crash["current"]["source_id"], current["source_id"])

            with patch.object(
                image,
                "materialize_source_result_shards",
                wraps=real_materialize,
            ) as materialize:
                image.run_image_competitor_crawl(runtime, dry_run=False)

        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(
            embedding.call_count,
            2,
            "来源图和候选图只应在首次处理时各调用一次向量模型",
        )
        self.assertEqual(mini.call_count, 1, "恢复时不得再次调用 Mini")
        self.assertGreaterEqual(materialize.call_count, 1)
        job_dir = runtime.outputs_root / runtime.job_id
        self.assertEqual(len(image.read_jsonl(job_dir / "candidates.jsonl")), 1)
        self.assertEqual(len(image.read_jsonl(job_dir / "records.jsonl")), 1)
        self.assertEqual(len(image.read_jsonl(job_dir / "counts.jsonl")), 1)
        final_state = image.load_json(job_dir / "state.json")
        self.assertIsNone(final_state["current"])
        self.assertEqual(final_state["completed_sources"], [current["source_id"]])
        self.assertEqual(final_state["records_count"], 1)

    def test_source_shard_identity_and_fingerprints_fail_closed(self) -> None:
        runtime = self.prepared_runtime(job_id="cascade-shard-fail-closed")
        for mismatch in ("source_identity", "crawl_plan", "provider"):
            with self.subTest(mismatch=mismatch):
                case_dir = self.root / f"shard-mismatch-{mismatch}"
                shard_dir = case_dir / "source_results"
                _, plan, provider, _, _, _ = self.commit_test_source_shard(
                    runtime,
                    shard_dir=shard_dir,
                )
                shard_path = next(shard_dir.glob("*.json"))
                payload = image.load_json(shard_path)
                if mismatch == "source_identity":
                    payload["source"]["source_asin"] = "B099999999"
                elif mismatch == "crawl_plan":
                    payload["crawl_plan_sha256"] = "wrong-plan"
                else:
                    payload["provider_sha256"] = "wrong-provider"
                image.dump_json(shard_path, payload)
                candidates_path = case_dir / "candidates.jsonl"
                records_path = case_dir / "records.jsonl"
                counts_path = case_dir / "counts.jsonl"
                for aggregate_path in (candidates_path, records_path, counts_path):
                    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
                    aggregate_path.write_text('{"sentinel":true}\n', encoding="utf-8")

                with self.assertRaisesRegex(
                    image.UserFacingError,
                    "不一致|不匹配|job_id",
                ):
                    image.materialize_source_result_shards(
                        shard_dir,
                        plan,
                        provider,
                        candidates_path,
                        records_path,
                        counts_path,
                    )
                for aggregate_path in (candidates_path, records_path, counts_path):
                    self.assertEqual(
                        image.read_jsonl(aggregate_path),
                        [{"sentinel": True}],
                        "校验失败时不得部分覆盖聚合结果",
                    )

    def test_materialization_interruption_is_recoverable_and_idempotent(self) -> None:
        runtime = self.prepared_runtime(job_id="cascade-materialize-retry")
        shard_dir = self.root / "materialize-retry-source-results"
        _, plan, provider, expected_candidates, expected_accepted, _ = (
            self.commit_test_source_shard(runtime, shard_dir=shard_dir)
        )
        candidates_path = self.root / "retry-candidates.jsonl"
        records_path = self.root / "retry-records.jsonl"
        counts_path = self.root / "retry-counts.jsonl"
        records_path.write_text('{"old":true}\n{"truncated":', encoding="utf-8")
        counts_path.write_text('{"old":true}\n{"truncated":', encoding="utf-8")
        real_write = image.write_jsonl_atomic
        write_attempts = 0

        def fail_on_second_aggregate_write(
            path: Path,
            rows: list[dict[str, object]],
        ) -> None:
            nonlocal write_attempts
            write_attempts += 1
            if write_attempts == 2:
                raise OSError("injected aggregate materialization failure")
            real_write(path, rows)

        with patch.object(
            image,
            "write_jsonl_atomic",
            side_effect=fail_on_second_aggregate_write,
        ):
            with self.assertRaisesRegex(OSError, "materialization failure"):
                image.materialize_source_result_shards(
                    shard_dir,
                    plan,
                    provider,
                    candidates_path,
                    records_path,
                    counts_path,
                )
        self.assertEqual(image.read_jsonl(candidates_path), expected_candidates)

        image.materialize_source_result_shards(
            shard_dir,
            plan,
            provider,
            candidates_path,
            records_path,
            counts_path,
        )
        self.assertEqual(image.read_jsonl(candidates_path), expected_candidates)
        self.assertEqual(image.read_jsonl(records_path), expected_accepted)
        self.assertEqual(len(image.read_jsonl(counts_path)), 1)
        recovered_bytes = {
            path.name: path.read_bytes()
            for path in (candidates_path, records_path, counts_path)
        }
        image.materialize_source_result_shards(
            shard_dir,
            plan,
            provider,
            candidates_path,
            records_path,
            counts_path,
        )
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in (candidates_path, records_path, counts_path)
            },
            recovered_bytes,
        )

    def test_count_commit_recovery_rejects_source_identity_mismatch(self) -> None:
        for mismatch_field in ("source_id", "source_asin"):
            with self.subTest(mismatch_field=mismatch_field):
                runtime = self.prepared_runtime(job_id=f"cascade-mismatch-{mismatch_field}")
                initial_queue = image.load_products(
                    runtime.products_file,
                    runtime.marketplace_domain,
                    dedupe=False,
                )
                current = initial_queue[0]
                job_dir = runtime.outputs_root / runtime.job_id
                job_dir.mkdir(parents=True)
                state_path = job_dir / "state.json"
                state_path.write_text(
                    json.dumps(
                        {
                            "job_id": runtime.job_id,
                            "mode": "image_competitor",
                            "marketplace": runtime.marketplace_domain,
                            "queue": [],
                            "current": current,
                            "completed_sources": [],
                            "records_count": 0,
                            "failures_count": 0,
                            "vision_provider_fingerprint": image.vision_provider_fingerprint(runtime),
                            "crawl_plan_fingerprint": image.image_crawl_plan_fingerprint(
                                runtime,
                                initial_queue,
                            ),
                            "delivery_location_fingerprint": runtime.delivery_location_fingerprint,
                        }
                    ),
                    encoding="utf-8",
                )
                committed = {
                    "match_mode": "cascade",
                    "source_id": current["source_id"],
                    "source_asin": current["source_asin"],
                    "source_product_url": current["source_product_url"],
                    "input_row": current["input_row"],
                    "prescreen_visual_match_count": 1,
                    "processing_status": "verified",
                    "same_product_count": 1,
                    "same_product_confidence": 0.9,
                    "match_reason": "already committed",
                }
                committed[mismatch_field] = (
                    "B099999999" if mismatch_field == "source_asin" else "wrong-source-id"
                )
                (job_dir / "counts.jsonl").write_text(
                    json.dumps(committed) + "\n",
                    encoding="utf-8",
                )
                driver = MagicMock()
                with (
                    patch.object(image, "start_driver", return_value=driver),
                    patch.object(image, "resolve_source_image") as resolve_source,
                    patch.object(image, "evaluate_competitor_matches") as evaluate,
                ):
                    with self.assertRaises(image.UserFacingError) as caught:
                        image.run_image_competitor_crawl(runtime, dry_run=False)
                self.assertRegex(str(caught.exception), "来源|source|job_id")
                resolve_source.assert_not_called()
                evaluate.assert_not_called()

    def test_resume_skips_paid_models_after_count_row_was_committed(self) -> None:
        runtime = self.prepared_runtime(job_id="cascade-commit-recovery")
        initial_queue = image.load_products(
            runtime.products_file,
            runtime.marketplace_domain,
            dedupe=False,
        )
        job_dir = runtime.outputs_root / runtime.job_id
        job_dir.mkdir(parents=True)
        current = initial_queue[0]
        state_path = job_dir / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "job_id": runtime.job_id,
                    "mode": "image_competitor",
                    "marketplace": runtime.marketplace_domain,
                    "queue": [],
                    "current": current,
                    "completed_sources": [],
                    "records_count": 0,
                    "failures_count": 0,
                    "vision_provider_fingerprint": image.vision_provider_fingerprint(runtime),
                    "crawl_plan_fingerprint": image.image_crawl_plan_fingerprint(
                        runtime,
                        initial_queue,
                    ),
                    "delivery_location_fingerprint": runtime.delivery_location_fingerprint,
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "counts.jsonl").write_text(
            json.dumps(
                {
                    "match_mode": "cascade",
                    "source_id": current["source_id"],
                    "source_asin": current["source_asin"],
                    "source_product_url": current["source_product_url"],
                    "input_row": current["input_row"],
                    "prescreen_visual_match_count": 2,
                    "processing_status": "verified",
                    "same_product_count": 1,
                    "same_product_confidence": 0.9,
                    "match_reason": "already committed",
                    "provider_metrics": {"mini_api_calls": 1},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        driver = MagicMock()
        with (
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "resolve_source_image") as resolve_source,
            patch.object(image, "evaluate_competitor_matches") as evaluate,
        ):
            image.run_image_competitor_crawl(runtime, dry_run=False)
        resolve_source.assert_not_called()
        evaluate.assert_not_called()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIsNone(state["current"])
        self.assertEqual(state["records_count"], 1)
        self.assertEqual(state["completed_source_reasons"][current["source_id"]], "verified")


if __name__ == "__main__":
    unittest.main()
