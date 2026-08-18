from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import json
import math
import os
from pathlib import Path
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


class DoubaoEmbeddingTests(unittest.TestCase):
    def setUp(self) -> None:
        image.EMBEDDING_CACHE.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.products_file = self.root / "products.csv"
        self.products_file.write_text(
            "ASIN,商品URL,主图URL,本地图片路径,备注\nB012345678,,,,test\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_provider(self, **overrides: object) -> Path:
        raw: dict[str, object] = {
            "api_key": "doubao-secret-for-test",
            "model": image.DOUBAO_EMBEDDING_MODEL,
            "base_url": image.DOUBAO_EMBEDDING_BASE_URL,
            "api_path": image.DOUBAO_EMBEDDING_API_PATH,
            "encoding_format": "float",
        }
        raw.update(overrides)
        path = self.root / "doubao.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return path

    def build_runtime(
        self,
        provider_path: Path | None = None,
        *,
        include_provider_field: bool = True,
        match_mode: str | None = "embedding",
        **overrides: object,
    ) -> image.ImageCompetitorRuntimeConfig:
        raw: dict[str, object] = {
            "job_id": "doubao-test",
            "outputs_root": str(self.root / "outputs"),
            "products_file": str(self.products_file),
            "marketplace": "美国站",
            "result_mode": "count_only",
            "browser_backend": "cdp",
            "browser_mode": "reuse",
            "extension_path": "auto",
            "vision_timeout": 10,
            "embedding_retry_attempts": 3,
            "embedding_retry_backoff_seconds": 0,
        }
        if include_provider_field:
            raw["doubao_embedding_config_file"] = str(
                provider_path or self.root / "missing-doubao.json"
            )
        if match_mode is not None:
            raw["match_mode"] = match_mode
        raw.update(overrides)
        return image.build_image_runtime_config(raw, no_resume=False)

    def prepared_runtime(self) -> image.ImageCompetitorRuntimeConfig:
        runtime = self.build_runtime(self.write_provider())
        image.prepare_vision_provider(runtime)
        return runtime

    def test_template_uses_recommended_ark_contract_and_empty_key(self) -> None:
        template = json.loads(
            (SKILL_ROOT / "assets/config/doubao_embedding_vision.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(template["api_key"], "")
        self.assertEqual(template["model"], "doubao-embedding-vision-251215")
        self.assertEqual(template["base_url"], "https://ark.cn-beijing.volces.com/api/v3")
        self.assertEqual(template["api_path"], "embeddings/multimodal")
        self.assertEqual(template["encoding_format"], "float")

    def test_match_mode_is_strict(self) -> None:
        with self.assertRaisesRegex(image.UserFacingError, "match_mode"):
            self.build_runtime(self.write_provider(), match_mode="automatic")

    def test_missing_invalid_and_empty_provider_config_fail(self) -> None:
        missing = self.build_runtime()
        with self.assertRaisesRegex(image.UserFacingError, "没有找到豆包"):
            image.prepare_vision_provider(missing)

        invalid_path = self.root / "invalid.json"
        invalid_path.write_text("{not-json", encoding="utf-8")
        invalid = self.build_runtime(invalid_path)
        with self.assertRaisesRegex(image.UserFacingError, "有效 JSON"):
            image.prepare_vision_provider(invalid)

        empty_key = self.build_runtime(self.write_provider(api_key=""))
        with self.assertRaisesRegex(image.UserFacingError, "API Key 为空"):
            image.prepare_vision_provider(empty_key)

    def test_explicit_empty_provider_field_never_falls_back_to_legacy_key(self) -> None:
        for empty_value in ("", None):
            with self.subTest(empty_value=empty_value):
                with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-key"}):
                    with self.assertRaisesRegex(
                        image.UserFacingError,
                        "doubao_embedding_config_file.*为空",
                    ):
                        self.build_runtime(
                            self.write_provider(),
                            doubao_embedding_config_file=empty_value,
                        )

    def test_dry_run_checks_key_before_browser_start(self) -> None:
        runtime = self.build_runtime(self.write_provider(api_key=""))
        with patch.object(image, "start_driver") as start_driver:
            with self.assertRaisesRegex(image.UserFacingError, "API Key 为空"):
                image.run_image_competitor_crawl(runtime, dry_run=True)
        start_driver.assert_not_called()

    def test_new_provider_config_takes_priority_over_legacy_environment(self) -> None:
        runtime = self.build_runtime(self.write_provider(api_key="file-key"))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-key"}):
            image.prepare_vision_provider(runtime)
        self.assertEqual(runtime.embedding_provider, "doubao")
        self.assertEqual(runtime.embedding_api_key, "file-key")

    def test_legacy_openai_embedding_fallback_warns(self) -> None:
        runtime = self.build_runtime(
            include_provider_field=False,
            vision_model="legacy-embedding",
            openai_api_path="embeddings",
        )
        stderr = StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-key"}), redirect_stderr(stderr):
            image.prepare_vision_provider(runtime)
        self.assertEqual(runtime.embedding_provider, "legacy_openai")
        self.assertEqual(runtime.embedding_model, "legacy-embedding")
        self.assertIn("弃用提示", stderr.getvalue())

    def test_chat_mode_continues_to_use_legacy_environment(self) -> None:
        runtime = self.build_runtime(
            self.write_provider(),
            match_mode="chat",
            openai_api_path="chat/completions",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "chat-key"}):
            image.prepare_vision_provider(runtime)
        self.assertEqual(runtime.embedding_provider, "openai_chat")

    def test_legacy_config_without_match_mode_keeps_chat_semantics_and_warns(self) -> None:
        runtime = self.build_runtime(
            include_provider_field=False,
            match_mode=None,
            openai_api_path="chat/completions",
        )
        self.assertEqual(runtime.match_mode, "chat")
        stderr = StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "chat-key"}), redirect_stderr(stderr):
            image.prepare_vision_provider(runtime)
        self.assertEqual(runtime.embedding_provider, "openai_chat")
        self.assertIn("弃用提示", stderr.getvalue())

    def test_ark_request_contract_and_retry(self) -> None:
        runtime = self.prepared_runtime()
        success = FakeResponse(200, {"data": [{"embedding": [[0.25, 0.75]]}]})
        with (
            patch.object(
                image.requests,
                "post",
                side_effect=[FakeResponse(429, text="rate limited"), success],
            ) as post,
            patch.object(image.time, "sleep") as sleep,
        ):
            vector = image.call_multimodal_embedding(runtime, "https://example.com/image.jpg")
        self.assertEqual(vector, [0.25, 0.75])
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once()
        _, kwargs = post.call_args
        self.assertEqual(
            kwargs["json"],
            {
                "model": "doubao-embedding-vision-251215",
                "input": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/image.jpg"},
                    }
                ],
                "encoding_format": "float",
            },
        )
        self.assertEqual(
            post.call_args.args[0],
            "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal",
        )
        self.assertEqual(kwargs["timeout"], 10)
        self.assertIs(kwargs["allow_redirects"], False)

    def test_embedding_usage_metrics_include_prompt_total_and_image_tokens(self) -> None:
        runtime = self.prepared_runtime()
        response = FakeResponse(
            200,
            {
                "data": [{"embedding": [0.25, 0.75]}],
                "usage": {
                    "prompt_tokens": 42,
                    "total_tokens": 42,
                    "prompt_tokens_details": {"image_tokens": 39},
                },
            },
        )
        with patch.object(image.requests, "post", return_value=response):
            image.call_multimodal_embedding(runtime, "https://example.com/image.jpg")

        self.assertEqual(runtime.provider_metrics["embedding_api_calls"], 1)
        self.assertEqual(runtime.provider_metrics["embedding_prompt_tokens"], 42)
        self.assertEqual(runtime.provider_metrics["embedding_total_tokens"], 42)
        self.assertEqual(runtime.provider_metrics["embedding_image_tokens"], 39)

    def test_private_embedding_config_rejects_insecure_or_ambiguous_endpoints(self) -> None:
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
            "query_in_path": {"api_path": "embeddings/multimodal?region=test"},
            "fragment_in_path": {"api_path": "embeddings/multimodal#credentials"},
        }
        for label, overrides in invalid_endpoints.items():
            with self.subTest(label=label):
                runtime = self.build_runtime(self.write_provider(**overrides))
                with self.assertRaises(image.UserFacingError):
                    image.prepare_vision_provider(runtime)

    def test_embedding_redirect_is_not_followed_and_fails_closed(self) -> None:
        runtime = self.prepared_runtime()
        with patch.object(
            image.requests,
            "post",
            return_value=FakeResponse(302, text="redirect"),
        ) as post:
            with self.assertRaises(image.FatalEmbeddingProviderError):
                image.call_multimodal_embedding(runtime, "https://example.com/image.jpg")

        self.assertEqual(post.call_count, 1)
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)

    def test_auth_and_model_errors_do_not_retry_or_leak_key(self) -> None:
        runtime = self.prepared_runtime()
        secret = runtime.embedding_api_key
        for response in (
            FakeResponse(401, text=f"Bearer {secret}"),
            FakeResponse(403, text=f"Bearer {secret}"),
            FakeResponse(400, text=f"model not activated; api_key={secret}"),
            FakeResponse(404, text="not found"),
        ):
            with self.subTest(status=response.status_code):
                with patch.object(image.requests, "post", return_value=response) as post:
                    with self.assertRaises(image.EmbeddingProviderError) as caught:
                        image.call_multimodal_embedding(runtime, "https://example.com/image.jpg")
                self.assertEqual(post.call_count, 1)
                self.assertNotIn(secret, str(caught.exception))

    def test_retry_exhaustion_redacts_key(self) -> None:
        runtime = self.prepared_runtime()
        secret = runtime.embedding_api_key
        response = FakeResponse(500, text=f'temporary failure api_key="{secret}"')
        with patch.object(image.requests, "post", return_value=response) as post:
            with self.assertRaises(image.EmbeddingProviderError) as caught:
                image.call_multimodal_embedding(runtime, "https://example.com/image.jpg")
        self.assertEqual(post.call_count, 3)
        self.assertNotIn(secret, str(caught.exception))

    def test_timeout_and_408_are_retried(self) -> None:
        runtime = self.prepared_runtime()
        success = FakeResponse(200, {"data": [{"embedding": [0.5, 0.5]}]})
        with (
            patch.object(
                image.requests,
                "post",
                side_effect=[image.requests.Timeout("timed out"), success],
            ) as post,
            patch.object(image.time, "sleep"),
        ):
            self.assertEqual(
                image.call_multimodal_embedding(runtime, "https://example.com/a.jpg"),
                [0.5, 0.5],
            )
        self.assertEqual(post.call_count, 2)

        with (
            patch.object(
                image.requests,
                "post",
                side_effect=[FakeResponse(408), success],
            ) as post,
            patch.object(image.time, "sleep"),
        ):
            self.assertEqual(
                image.call_multimodal_embedding(runtime, "https://example.com/b.jpg"),
                [0.5, 0.5],
            )
        self.assertEqual(post.call_count, 2)

    def test_vector_must_be_nonempty_finite_and_dimensionally_equal(self) -> None:
        invalid_vectors = (
            {"data": [{"embedding": []}]},
            {"data": [{"embedding": [math.nan, 1]}]},
            {"data": [{"embedding": [math.inf, 1]}]},
            {"data": [{"embedding": [0, 0]}]},
        )
        for payload in invalid_vectors:
            with self.subTest(payload=payload):
                with self.assertRaises(image.EmbeddingProviderError):
                    image.extract_embedding_vector(payload)
        with self.assertRaisesRegex(image.EmbeddingProviderError, "维度不一致"):
            image.cosine_similarity([1.0, 2.0], [1.0])

    def test_candidate_embedding_failure_does_not_return_false_zero(self) -> None:
        runtime = self.prepared_runtime()
        source_image = self.root / "source.jpg"
        source_image.write_bytes(b"test-image")
        records = [
            {
                "source_asin": "B000000001",
                "asin": "B000000002",
                "candidate_image_url": "https://example.com/candidate.jpg",
                "rank": "1",
            }
        ]
        with (
            patch.object(
                image,
                "call_multimodal_embedding_cached",
                side_effect=[
                    [1.0, 0.0],
                    image.EmbeddingProviderError("URL failed"),
                    image.EmbeddingProviderError("data URL failed"),
                ],
            ),
            patch.object(image, "image_url_to_data_url", return_value="data:image/jpeg;base64,dGVzdA=="),
        ):
            with self.assertRaisesRegex(image.EmbeddingProviderError, "不写入相似竞品数量"):
                image.filter_high_confidence_competitors(
                    runtime,
                    source_image,
                    "",
                    records,
                )

    def test_fatal_provider_error_does_not_trigger_candidate_data_url_fallback(self) -> None:
        runtime = self.prepared_runtime()
        source_image = self.root / "source.jpg"
        source_image.write_bytes(b"test-image")
        records = [
            {
                "source_asin": "B000000001",
                "asin": "B000000002",
                "candidate_image_url": "https://example.com/candidate.jpg",
                "rank": "1",
            }
        ]
        with (
            patch.object(
                image,
                "call_multimodal_embedding_cached",
                side_effect=[
                    [1.0, 0.0],
                    image.FatalEmbeddingProviderError("HTTP 401"),
                ],
            ) as embed,
            patch.object(image, "image_url_to_data_url") as fallback,
        ):
            with self.assertRaises(image.FatalEmbeddingProviderError):
                image.filter_high_confidence_competitors(
                    runtime,
                    source_image,
                    "",
                    records,
                )
        self.assertEqual(embed.call_count, 2)
        fallback.assert_not_called()

    def test_candidate_400_image_url_error_uses_local_data_url_fallback(self) -> None:
        runtime = self.prepared_runtime()
        source_image = self.root / "source.jpg"
        source_image.write_bytes(b"test-image")
        records = [
            {
                "source_asin": "B000000001",
                "asin": "B000000002",
                "candidate_image_url": "https://example.com/candidate.jpg",
                "rank": "1",
            }
        ]
        responses = [
            FakeResponse(200, {"data": [{"embedding": [1.0, 0.0]}]}),
            FakeResponse(400, {"error": {"message": "failed to fetch image_url"}}),
            FakeResponse(200, {"data": [{"embedding": [0.99, 0.01]}]}),
        ]
        with (
            patch.object(image.requests, "post", side_effect=responses) as post,
            patch.object(
                image,
                "image_url_to_data_url",
                return_value="data:image/jpeg;base64,dGVzdA==",
            ) as fallback,
        ):
            accepted, decisions = image.filter_high_confidence_competitors(
                runtime,
                source_image,
                "",
                records,
            )
        self.assertEqual(post.call_count, 3)
        fallback.assert_called_once()
        self.assertEqual([row["asin"] for row in accepted], ["B000000002"])
        self.assertTrue(decisions["B000000002"]["is_competitor"])

    def test_chat_provider_error_does_not_leak_key(self) -> None:
        runtime = self.build_runtime(
            self.write_provider(),
            match_mode="chat",
            openai_api_path="chat/completions",
        )
        source_image = self.root / "source.jpg"
        source_image.write_bytes(b"test-image")
        secret = "chat-secret-for-test"
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": secret}),
            patch.object(
                image.requests,
                "post",
                return_value=FakeResponse(500, text=f"api_key={secret}"),
            ),
        ):
            image.prepare_vision_provider(runtime)
            with self.assertRaises(image.EmbeddingProviderError) as caught:
                image.call_openai_vision(runtime, source_image, [])
        self.assertNotIn(secret, str(caught.exception))

    def test_fatal_provider_error_preserves_current_and_exits_without_count(self) -> None:
        runtime = self.build_runtime(
            self.write_provider(),
            job_id="fatal-provider-workflow",
            save_debug_snapshots=False,
        )
        source_image = self.root / "source.jpg"
        source_image.write_bytes(b"test-image")
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/products"
        candidate = {
            "source_asin": "B012345678",
            "asin": "B000000002",
            "candidate_image_url": "https://example.com/candidate.jpg",
        }
        secret = "doubao-secret-for-test"
        with (
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "resolve_source_image", return_value=source_image),
            patch.object(image, "run_image_search", return_value="amazon_upload"),
            patch.object(image, "detect_block", return_value=None),
            patch.object(image, "wait_for_lens_results"),
            patch.object(image, "merge_lens_product_data", return_value=[candidate]),
            patch.object(
                image,
                "filter_high_confidence_competitors",
                side_effect=image.FatalEmbeddingProviderError(secret),
            ),
        ):
            with self.assertRaises(image.FatalEmbeddingProviderError) as caught:
                image.run_image_competitor_crawl(runtime, dry_run=False)
        job_dir = runtime.outputs_root / runtime.job_id
        state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
        failure_text = (job_dir / "failures.jsonl").read_text(encoding="utf-8")
        self.assertIsNotNone(state["current"])
        self.assertFalse((job_dir / "counts.jsonl").exists())
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, failure_text)

    def test_empty_candidate_reextract_preserves_current_instead_of_writing_zero(self) -> None:
        runtime = self.build_runtime(
            self.write_provider(),
            job_id="empty-candidate-workflow",
            save_debug_snapshots=False,
        )
        source_image = self.root / "source.jpg"
        source_image.write_bytes(b"test-image")
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/products"
        with (
            patch.object(image, "start_driver", return_value=driver),
            patch.object(image, "resolve_source_image", return_value=source_image),
            patch.object(image, "run_image_search", return_value="amazon_upload"),
            patch.object(image, "detect_block", return_value=None),
            patch.object(image, "wait_for_lens_results"),
            patch.object(image, "merge_lens_product_data", return_value=[]),
        ):
            with self.assertRaisesRegex(image.EmbeddingProviderError, "不写入零竞品"):
                image.run_image_competitor_crawl(runtime, dry_run=False)
        job_dir = runtime.outputs_root / runtime.job_id
        state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(state["current"])
        self.assertFalse((job_dir / "counts.jsonl").exists())

    def test_verification_timeout_preserves_current_and_stops(self) -> None:
        runtime = self.build_runtime(
            self.write_provider(),
            job_id="verification-timeout-workflow",
            save_debug_snapshots=False,
        )
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/"
        with (
            patch.object(image, "start_driver", return_value=driver),
            patch.object(
                image,
                "resolve_source_image",
                side_effect=image.VerificationUnconfirmedError(
                    "amazon_robot_check_unconfirmed"
                ),
            ),
        ):
            with self.assertRaises(image.VerificationUnconfirmedError):
                image.run_image_competitor_crawl(runtime, dry_run=False)
        job_dir = runtime.outputs_root / runtime.job_id
        state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
        failure_text = (job_dir / "failures.jsonl").read_text(encoding="utf-8")
        self.assertIsNotNone(state["current"])
        self.assertFalse((job_dir / "counts.jsonl").exists())
        self.assertIn("verification_unconfirmed", failure_text)

    def test_fingerprint_contains_provider_settings_but_not_key(self) -> None:
        runtime = self.prepared_runtime()
        fingerprint = image.vision_provider_fingerprint(runtime)
        serialized = json.dumps(fingerprint, ensure_ascii=False)
        self.assertEqual(fingerprint["model"], image.DOUBAO_EMBEDDING_MODEL)
        self.assertEqual(fingerprint["min_match_confidence"], runtime.min_match_confidence)
        self.assertEqual(
            fingerprint["delivery_location_fingerprint"],
            runtime.delivery_location_fingerprint,
        )
        self.assertNotIn(runtime.embedding_api_key, serialized)

    def test_changed_provider_fingerprint_rejects_completed_checkpoint(self) -> None:
        runtime = self.prepared_runtime()
        state_path = self.root / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "job_id": runtime.job_id,
                    "records_count": 1,
                    "completed_sources": ["B012345678"],
                    "vision_provider_fingerprint": {"sha256": "old"},
                }
            ),
            encoding="utf-8",
        )
        store = image.ImageCompetitorStateStore(state_path, runtime, [])
        with self.assertRaisesRegex(image.UserFacingError, "新的 job_id"):
            store.load_or_create()


if __name__ == "__main__":
    unittest.main()
