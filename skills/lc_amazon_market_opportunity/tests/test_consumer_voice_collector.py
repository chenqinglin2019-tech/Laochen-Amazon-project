from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "consumer_voice_collector.py"
SPEC = importlib.util.spec_from_file_location("consumer_voice_collector", MODULE_PATH)
assert SPEC and SPEC.loader
cvc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cvc)


END_AT = "2026-08-05T00:00:00Z"


def top_comment(comment_id: str, text: str = "top", author: str = "a") -> Dict[str, Any]:
    return {
        "id": comment_id,
        "snippet": {
            "textOriginal": text,
            "publishedAt": "2026-08-01T00:00:00Z",
            "updatedAt": "2026-08-01T00:00:00Z",
            "authorDisplayName": author,
            "authorChannelId": {"value": "channel-" + author},
            "likeCount": 2,
        },
    }


def thread(thread_id: str, top_id: str, total_replies: int = 0, replies: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": thread_id,
        "snippet": {"topLevelComment": top_comment(top_id), "totalReplyCount": total_replies},
    }
    if replies:
        result["replies"] = {"comments": list(replies)}
    return result


class FakeHttp:
    def __init__(self, responses: Mapping[Any, Any]):
        self.responses = dict(responses)
        self.calls = []

    def get_json(self, url: str, params: Mapping[str, Any], timeout: float, headers=None) -> Mapping[str, Any]:
        resource = url.rsplit("/", 1)[-1]
        key = (resource, params.get("pageToken"), params.get("parentId"))
        self.calls.append((resource, dict(params), dict(headers or {})))
        value = self.responses[key]
        if isinstance(value, Exception):
            raise value
        return value


class FailOnceHttp(FakeHttp):
    def __init__(self, responses: Mapping[Any, Any], fail_key: Any):
        super().__init__(responses)
        self.fail_key = fail_key
        self.failed = False

    def get_json(self, url: str, params: Mapping[str, Any], timeout: float, headers=None) -> Mapping[str, Any]:
        resource = url.rsplit("/", 1)[-1]
        key = (resource, params.get("pageToken"), params.get("parentId"))
        self.calls.append((resource, dict(params), dict(headers or {})))
        if key == self.fail_key and not self.failed:
            self.failed = True
            raise RuntimeError("network failed key=SECRET_SHOULD_NOT_LEAK")
        return self.responses[key]


class CollectorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "collector.sqlite3"
        self.old_registry = os.environ.get("LCADMO_TASK_REGISTRY")
        self.old_youtube_config = os.environ.get("LCADMO_YOUTUBE_API_CONFIG")
        os.environ["LCADMO_TASK_REGISTRY"] = str(self.root / "task_registry.json")
        os.environ["LCADMO_YOUTUBE_API_CONFIG"] = str(self.root / "youtube_api.env")

    def tearDown(self) -> None:
        if self.old_registry is None:
            os.environ.pop("LCADMO_TASK_REGISTRY", None)
        else:
            os.environ["LCADMO_TASK_REGISTRY"] = self.old_registry
        if self.old_youtube_config is None:
            os.environ.pop("LCADMO_YOUTUBE_API_CONFIG", None)
        else:
            os.environ["LCADMO_YOUTUBE_API_CONFIG"] = self.old_youtube_config
        self.temporary.cleanup()

    def make_store(self, queues: Sequence[Mapping[str, Any]], level: str = "quick"):
        store = cvc.CollectorStore(self.db)
        task = store.create_task("test", "chair", level, END_AT, queues, task_id="task-1")
        return store, task

    def youtube_queue(self, **overrides: Any) -> Dict[str, Any]:
        queue = {
            "source": "youtube",
            "backend": "youtube-data-api",
            "scope": "category_30d",
            "query_id": "q1",
            "video_id": "video-1",
        }
        queue.update(overrides)
        return queue

    def test_fixed_research_levels_and_default_nonblocking_reminder(self) -> None:
        expected = {
            "quick": (500, 1000, 35, 60, 200, 400, 100, 200),
            "standard": (1000, 3000, 55, 90, 400, 1200, 200, 600),
            "deep": (3000, 5000, 75, 120, 1200, 2000, 600, 1000),
        }
        for level, values in expected.items():
            plan = cvc.research_plan(level)
            target = plan["sample_target"]
            budget = plan["time_budget_minutes"]
            category = target["per_scope"]["category_30d"]
            segment = target["per_scope"]["segment_1_90d"]
            actual = (
                target["total_valid_min"],
                target["total_valid_max"],
                budget["collection"],
                budget["total"],
                category["valid_min"],
                category["valid_max"],
                segment["valid_min"],
                segment["valid_max"],
            )
            self.assertEqual(values, actual)
            self.assertEqual(3, target["min_platforms"])
            self.assertEqual(
                {"research_level", "sample_target", "time_budget_minutes"}, set(plan)
            )
            policy = cvc.collection_policy(level)
            self.assertEqual("non_blocking", policy["reminder_policy"]["mode"])
            self.assertTrue(policy["reminder_policy"]["enabled"])

    def test_plan_rejects_overridden_fixed_statistics(self) -> None:
        plan_file = self.root / "plan.json"
        plan_file.write_text(
            json.dumps(
                {
                    "research_plan": {
                        "research_level": "quick",
                        "sample_target": {"total_valid_min": 1},
                    }
                }
            ),
            encoding="utf-8",
        )
        args = cvc.build_parser().parse_args(
            ["plan", "--db", str(self.db), "--plan-file", str(plan_file)]
        )
        with self.assertRaises(cvc.ConfigurationError):
            cvc.create_plan_from_args(args)

    def test_sqlite_has_required_state_tables(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        tables = {
            row[0]
            for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue(
            {"tasks", "batches", "comments", "checkpoints", "quota_ledger"}.issubset(tables)
        )
        store.close()

    def test_collector_database_sidecars_and_run_directory_are_private(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX permission bits are not portable to Windows")
        run_dir = self.root / "consumer_voice_private"
        run_dir.mkdir(mode=0o755)
        db_path = run_dir / "collector.sqlite3"
        store = cvc.CollectorStore(db_path)
        store.create_task(
            "private",
            "phone mount",
            "quick",
            END_AT,
            [],
            task_id="private-task",
            run_dir=run_dir,
        )
        self.assertEqual(0o700, stat.S_IMODE(run_dir.stat().st_mode))
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(db_path) + suffix)
            self.assertTrue(path.exists(), path)
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode), path)
        store.close()

    def test_hard_dedupe_never_uses_text_or_parent_url_alone(self) -> None:
        queues = [
            self.youtube_queue(),
            self.youtube_queue(
                batch_id="b2", scope="segment_1_90d", query_id="q2", backend="external"
            ),
        ]
        store, _ = self.make_store(queues)
        batches = [store.batch_payload(row) for row in store.list_batches("task-1")]
        base = {
            "source": "youtube",
            "parent_content_id": "parent",
            "thread_id": "parent",
            "author_id": "author-a",
            "author_label": "A",
            "text": "same exact text",
            "published_at": "2026-08-01T00:00:00Z",
            "url": "https://youtube.com/watch?v=video-1",
        }
        first = dict(base, content_id="id-1")
        second = dict(base, content_id="id-2")
        _, new1, _ = store.insert_comment("task-1", batches[0], first)
        _, new2, _ = store.insert_comment("task-1", batches[0], second)
        self.assertTrue(new1 and new2, "same text with different ids must remain separate")
        fallback_a = dict(base)
        fallback_b = dict(base, author_id="author-b", author_label="B")
        _, new3, _ = store.insert_comment("task-1", batches[0], fallback_a)
        _, new4, _ = store.insert_comment("task-1", batches[0], fallback_b)
        self.assertTrue(new3 and new4, "same text with different authors must remain separate")
        _, duplicate, _ = store.insert_comment("task-1", batches[1], fallback_a)
        self.assertFalse(duplicate, "the exact fallback composite identity should merge")
        self.assertEqual(4, store.connection.execute("SELECT COUNT(*) FROM comments").fetchone()[0])
        store.close()

    def test_same_text_on_different_platforms_remains_separate(self) -> None:
        store, _ = self.make_store(
            [self.youtube_queue(), {"source": "reddit", "backend": "external", "scope": "category_30d"}]
        )
        batches = [store.batch_payload(row) for row in store.list_batches("task-1")]
        base = {
            "parent_content_id": "parent",
            "author_label": "same",
            "text": "identical",
            "published_at": "2026-08-01T00:00:00Z",
        }
        store.insert_comment("task-1", batches[0], dict(base, source="youtube"))
        store.insert_comment("task-1", batches[1], dict(base, source="reddit"))
        self.assertEqual(2, store.connection.execute("SELECT COUNT(*) FROM comments").fetchone()[0])
        store.close()

    def test_identity_aliases_merge_url_only_then_explicit_id_and_reverse(self) -> None:
        for reverse in (False, True):
            db = self.root / ("reverse.sqlite3" if reverse else "forward.sqlite3")
            store = cvc.CollectorStore(db)
            store.create_task(
                "alias",
                "holder",
                "quick",
                END_AT,
                [
                    {"source": "reddit", "backend": "external", "scope": "category_30d", "batch_id": "b1"},
                    {"source": "reddit", "backend": "external", "scope": "segment_1_90d", "batch_id": "b2"},
                ],
                task_id="task-1",
            )
            first_batch, second_batch = [
                store.batch_payload(row) for row in store.list_batches("task-1")
            ]
            url_only = {
                "source": "reddit",
                "parent_content_id": "post-1",
                "author_label": "driver",
                "text": "needs a stronger clamp",
                "published_at": "2026-08-01T00:00:00Z",
                "url": "https://www.reddit.com/r/truckers/comments/post_1/title/comment_1/?utm_source=share&context=3",
            }
            with_id = dict(url_only, content_id="comment_1")
            ordered = (with_id, url_only) if reverse else (url_only, with_id)
            first_id, first_new, _ = store.insert_comment("task-1", first_batch, ordered[0])
            second_id, second_new, _ = store.insert_comment("task-1", second_batch, ordered[1])
            self.assertTrue(first_new)
            self.assertFalse(second_new)
            self.assertEqual(first_id, second_id)
            self.assertEqual(1, store.connection.execute("SELECT COUNT(*) FROM comments").fetchone()[0])
            self.assertEqual(
                2,
                store.connection.execute("SELECT COUNT(*) FROM comment_discoveries").fetchone()[0],
            )
            row = store.connection.execute(
                "SELECT content_id FROM comments WHERE record_id=?", (first_id,)
            ).fetchone()
            self.assertEqual("comment_1", row["content_id"])
            store.close()

    def test_canonical_url_parameter_order_and_tracking_variants_merge(self) -> None:
        store, _ = self.make_store(
            [
                {"source": "reddit", "backend": "external", "scope": "category_30d", "batch_id": "r1"},
                {"source": "reddit", "backend": "external", "scope": "category_30d", "batch_id": "r2"},
            ]
        )
        first_batch, second_batch = [
            store.batch_payload(row) for row in store.list_batches("task-1")
        ]
        base = {
            "source": "reddit",
            "parent_content_id": "post-1",
            "author_label": "driver",
            "text": "same public comment",
            "published_at": "2026-08-01T00:00:00Z",
        }
        first = dict(
            base,
            url="https://www.reddit.com/r/truckers/comments/post_1/title/comment_1/?b=2&a=1&utm_medium=social&context=3",
        )
        second = dict(
            base,
            url="https://reddit.com/r/truckers/comments/post_1/title/comment_1?a=1&b=2",
        )
        first_id, _, _ = store.insert_comment("task-1", first_batch, first)
        second_id, second_new, _ = store.insert_comment("task-1", second_batch, second)
        self.assertEqual(first_id, second_id)
        self.assertFalse(second_new)
        row = store.connection.execute(
            "SELECT canonical_url FROM comments WHERE record_id=?", (first_id,)
        ).fetchone()
        self.assertEqual(
            "https://reddit.com/r/truckers/comments/post_1/title/comment_1?a=1&b=2",
            row["canonical_url"],
        )
        store.close()

    def test_later_complete_discovery_enriches_canonical_and_recomputes_eligibility(self) -> None:
        store, _ = self.make_store(
            [
                self.youtube_queue(batch_id="b1"),
                self.youtube_queue(batch_id="b2", scope="segment_1_90d", query_id="q2"),
            ]
        )
        first_batch, second_batch = [
            store.batch_payload(row) for row in store.list_batches("task-1")
        ]
        incomplete = {
            "source": "youtube",
            "content_id": "comment-1",
            "video_id": "video-1",
            "text": "short",
        }
        complete = {
            "source": "youtube",
            "content_id": "comment-1",
            "parent_content_id": "top-1",
            "thread_id": "thread-1",
            "video_id": "video-1",
            "author_id": "channel-1",
            "author_label": "Driver One",
            "text": "short, but the full comment asks for a much stronger clamp",
            "published_at": "2026-08-01T00:00:00Z",
            "url": "https://www.youtube.com/watch?v=video-1&lc=comment-1&utm_source=share",
            "engagement": {"likes": 7},
        }
        record_id, _, first_valid = store.insert_comment("task-1", first_batch, incomplete)
        same_id, second_new, second_valid = store.insert_comment("task-1", second_batch, complete)
        self.assertFalse(first_valid)
        self.assertFalse(second_new)
        self.assertTrue(second_valid)
        self.assertEqual(record_id, same_id)
        row = store.connection.execute("SELECT * FROM comments WHERE record_id=?", (record_id,)).fetchone()
        self.assertEqual(1, row["technical_eligible"])
        self.assertEqual(1, row["eligible_for_quantitation"])
        self.assertEqual(complete["text"], row["text"])
        self.assertEqual("2026-08-01T00:00:00Z", row["published_at"])
        self.assertEqual("channel-1", row["author_id"])
        self.assertEqual("top-1", row["parent_content_id"])
        raw = json.loads(row["raw_json"])
        self.assertEqual(2, len(raw["_raw_provenance"]))
        self.assertEqual(7, raw["engagement"]["likes"])
        store.close()

    def test_later_incomplete_discovery_cannot_downgrade_complete_canonical(self) -> None:
        store, _ = self.make_store(
            [self.youtube_queue(batch_id="b1"), self.youtube_queue(batch_id="b2", query_id="q2")]
        )
        first_batch, second_batch = [
            store.batch_payload(row) for row in store.list_batches("task-1")
        ]
        complete = {
            "source": "youtube",
            "content_id": "comment-1",
            "parent_content_id": "top-1",
            "thread_id": "thread-1",
            "video_id": "video-1",
            "author_id": "channel-1",
            "author_label": "Driver One",
            "text": "complete consumer comment",
            "published_at": "2026-08-01T00:00:00Z",
            "url": "https://youtube.com/watch?lc=comment-1&v=video-1",
        }
        incomplete = {
            "source": "youtube",
            "content_id": "comment-1",
            "video_id": "video-1",
            "text": "",
        }
        record_id, _, first_valid = store.insert_comment("task-1", first_batch, complete)
        same_id, second_new, second_valid = store.insert_comment("task-1", second_batch, incomplete)
        self.assertTrue(first_valid)
        self.assertFalse(second_new or second_valid)
        self.assertEqual(record_id, same_id)
        row = store.connection.execute("SELECT * FROM comments WHERE record_id=?", (record_id,)).fetchone()
        self.assertEqual(1, row["technical_eligible"])
        self.assertEqual(1, row["eligible_for_quantitation"])
        for field, expected in {
            "text": complete["text"],
            "published_at": "2026-08-01T00:00:00Z",
            "author_id": "channel-1",
            "parent_content_id": "top-1",
            "thread_id": "thread-1",
        }.items():
            self.assertEqual(expected, row[field])
        raw = json.loads(row["raw_json"])
        self.assertEqual(2, len(raw["_raw_provenance"]))
        store.close()

    def test_last30days_local_rank_ids_never_drive_cross_query_dedupe(self) -> None:
        for platform, local_id in (
            ("reddit", "R1"),
            ("x", "X1"),
            ("youtube", "YT1"),
            ("tiktok", "TK1"),
            ("instagram", "IG1"),
        ):
            self.assertEqual("", cvc._stable_last30days_content_id(platform, local_id, ""))
        store, _ = self.make_store(
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "q1",
                    "query_text": "first",
                },
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "q2",
                    "query_text": "second",
                },
            ]
        )
        first_batch, second_batch = [
            store.batch_payload(row) for row in store.list_batches("task-1")
        ]

        def collect(payload: Mapping[str, Any], batch: Mapping[str, Any]) -> None:
            cvc._extract_last30days_payload(
                payload,
                batch,
                lambda comment: store.insert_comment("task-1", batch, comment),
            )

        collect(
            {
                "items_by_source": {
                    "reddit": [
                        {
                            "item_id": "R1",
                            "body": "same wording",
                            "published_at": "2026-08-01T00:00:00Z",
                            "url": "https://www.reddit.com/r/a/comments/1abcde/first/",
                        },
                        {
                            "item_id": "R1",
                            "body": "same wording",
                            "published_at": "2026-08-01T00:00:00Z",
                            "url": "https://www.reddit.com/r/b/comments/1fghij/second/",
                        },
                    ]
                }
            },
            first_batch,
        )
        collect(
            {
                "items_by_source": {
                    "reddit": [
                        {
                            "item_id": "R9",
                            "body": "same wording",
                            "published_at": "2026-08-01T00:00:00Z",
                            "url": "https://www.reddit.com/r/a/comments/1abcde/first/?utm_source=test",
                        }
                    ]
                }
            },
            second_batch,
        )
        rows = store.connection.execute(
            "SELECT content_id FROM comments ORDER BY content_id"
        ).fetchall()
        self.assertEqual(["1abcde", "1fghij"], [row["content_id"] for row in rows])
        self.assertEqual(
            3,
            store.connection.execute("SELECT COUNT(*) FROM comment_discoveries").fetchone()[0],
        )
        store.close()

    def test_missing_hard_identity_is_saved_opaquely_but_never_quantified_or_cross_merged(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        incomplete = {
            "source": "youtube",
            "text": "same anonymous text",
            "published_at": "2026-08-01T00:00:00Z",
            "source_position": "page1:0",
        }
        _, first_new, first_valid = store.insert_comment("task-1", batch, incomplete)
        _, second_new, second_valid = store.insert_comment(
            "task-1", batch, dict(incomplete, source_position="page2:0")
        )
        self.assertTrue(first_new and second_new)
        self.assertFalse(first_valid or second_valid)
        reasons = [row[0] for row in store.connection.execute("SELECT exclusion_reason FROM comments")]
        self.assertEqual(["missing_hard_identity", "missing_hard_identity"], sorted(reasons))
        store.close()

    def test_youtube_api_paginates_threads_and_all_replies(self) -> None:
        r1 = top_comment("r1", "reply one", "r")
        responses = {
            ("commentThreads", None, None): {
                "items": [thread("t1", "c1", total_replies=3, replies=[r1])],
                "nextPageToken": "T2",
            },
            ("comments", None, "c1"): {
                "items": [r1, top_comment("r2", "reply two", "r2")],
                "nextPageToken": "R2",
            },
            ("comments", "R2", "c1"): {"items": [top_comment("r3", "reply three", "r3")]},
            ("commentThreads", "T2", None): {"items": [thread("t2", "c2")]},
        }
        http = FakeHttp(responses)
        store, _ = self.make_store([self.youtube_queue()])
        receipt = cvc.CollectorService(store, api_key="secret-key", http_client=http).run("task-1")
        self.assertEqual("queues_exhausted", receipt["stop_reason"])
        self.assertEqual(5, receipt["collection_funnel"]["valid_voices"])
        self.assertEqual(6, receipt["collection_funnel"]["fetched_records"])
        self.assertEqual(4, receipt["quota_and_cost"]["quota_units"])
        self.assertEqual(["quota_only"], receipt["quota_and_cost"]["cost_statuses"])
        self.assertTrue(
            all(item["amount"] is None for item in receipt["quota_and_cost"]["ledger"])
        )
        self.assertEqual(4, len(http.calls))
        self.assertTrue(
            all(call[1].get("order") == "time" for call in http.calls if call[0] == "commentThreads")
        )
        self.assertEqual([], receipt["checkpoints"])
        store.close()

    def test_youtube_list_operations_use_current_one_unit_quota_cost(self) -> None:
        http = FakeHttp(
            {
                ("search", None, None): {
                    "items": [{"id": {"videoId": "video-1"}}]
                }
            }
        )
        charged = []
        result = cvc.YoutubeDataApiCollector("secret", http).search_videos(
            "phone mount", lambda operation, units: charged.append((operation, units))
        )
        self.assertEqual(["video-1"], result["video_ids"])
        self.assertEqual([("search.list", 1)], charged)

    def test_official_search_paginates_incrementally_when_existing_videos_cannot_fill_scope_minimum(self) -> None:
        store, _ = self.make_store(
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_q1",
                    "query_text": "phone mount",
                }
            ]
        )
        plan = cvc.research_plan("quick")
        plan["sample_target"]["total_valid_min"] = 4
        plan["sample_target"]["total_valid_max"] = 4
        plan["sample_target"]["per_scope"]["category_30d"].update(
            {"valid_min": 4, "valid_max": 4}
        )
        store.update_task(
            "task-1", research_plan_json=cvc.compact_json(plan), updated_at=cvc.iso_utc()
        )
        task = store.task_payload("task-1")
        batch = store.batch_payload(store.list_batches("task-1")[0])
        http = FakeHttp(
            {
                ("search", None, None): {
                    "items": [{"id": {"videoId": "search-1"}}],
                    "nextPageToken": "PAGE-2",
                },
                ("search", "PAGE-2", None): {
                    "items": [
                        {"id": {"videoId": "search-2"}},
                        {"id": {"videoId": "search-3"}},
                    ]
                },
            }
        )
        config = {
            "enabled": True,
            "daily_quota_units": 10000,
            "quota_reserve": 2500,
            "search_enabled": True,
            "max_results": 100,
            "max_workers": 4,
        }
        service = cvc.CollectorService(
            store, api_key="secret", http_client=http, youtube_config=config
        )
        service._enqueue_youtube_videos(task, batch, ["already-discovered"])
        charged = []
        first_error = service._expand_youtube_search_for_scope(
            task,
            batch,
            lambda operation, units: charged.append((operation, units)),
            lambda: None,
            lambda: 60.0,
        )
        self.assertIsNone(first_error)
        self.assertEqual([None], [call[1].get("pageToken") for call in http.calls])
        self.assertEqual(
            "PAGE-2",
            store.checkpoint(
                "task-1", batch["batch_id"], key="youtube_search_discovery"
            )["next_page_token"],
        )
        second_error = service._expand_youtube_search_for_scope(
            task,
            batch,
            lambda operation, units: charged.append((operation, units)),
            lambda: None,
            lambda: 60.0,
        )
        self.assertIsNone(second_error)
        self.assertEqual([None, "PAGE-2"], [call[1].get("pageToken") for call in http.calls])
        self.assertEqual([3, 2], [call[1]["maxResults"] for call in http.calls])
        self.assertEqual(2, len(charged))
        self.assertEqual(
            4,
            len(service._youtube_pending_video_ids("task-1", "category_30d")),
        )
        self.assertEqual(0, service._youtube_video_candidate_gap(task, "category_30d"))
        store.close()

    def test_official_search_respects_single_task_global_call_cap(self) -> None:
        store, _ = self.make_store(
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_q1",
                    "query_text": "phone mount",
                }
            ]
        )
        batch = store.batch_payload(store.list_batches("task-1")[0])
        for _ in range(9):
            store.record_quota(
                "task-1",
                batch["batch_id"],
                "youtube",
                "search.list",
                1,
                cost_status="quota_only",
                pricing_basis="test",
            )
        http = FakeHttp(
            {
                ("search", None, None): {
                    "items": [{"id": {"videoId": "only-page"}}],
                    "nextPageToken": "MUST-NOT-BE-READ",
                }
            }
        )
        config = {
            "enabled": True,
            "daily_quota_units": 10000,
            "quota_reserve": 2500,
            "search_enabled": True,
            "max_results": 100,
            "max_workers": 4,
        }
        service = cvc.CollectorService(
            store, api_key="secret", http_client=http, youtube_config=config
        )

        def charge(operation: str, units: int) -> None:
            store.record_quota(
                "task-1",
                batch["batch_id"],
                "youtube",
                operation,
                units,
                cost_status="quota_only",
                pricing_basis="test",
            )

        service._expand_youtube_search_for_scope(
            store.task_payload("task-1"),
            batch,
            charge,
            lambda: None,
            lambda: 60.0,
        )
        self.assertEqual(1, len(http.calls))
        self.assertEqual(10, store.operation_count("task-1", "search.list"))
        store.close()

    def test_youtube_quota_boundary_falls_back_without_stopping_other_queues(self) -> None:
        calls = []

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            calls.append(list(argv))
            payload = {
                "id": "video-1",
                "comments": [
                    {
                        "id": "fallback-1",
                        "parent": "root",
                        "author": "viewer",
                        "text": "fallback voice",
                        "timestamp": 1785542400,
                    }
                ],
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        store, _ = self.make_store([self.youtube_queue(backend="auto")])
        config = {
            "enabled": True,
            "daily_quota_units": 2500,
            "quota_reserve": 2500,
            "search_enabled": False,
            "max_results": 100,
            "max_workers": 4,
        }
        receipt = cvc.CollectorService(
            store,
            api_key="secret",
            http_client=FakeHttp({}),
            runner=runner,
            youtube_config=config,
        ).run("task-1")
        self.assertEqual("platform_or_quota_limit", receipt["stop_reason"])
        self.assertEqual("paused", receipt["status"])
        self.assertEqual(4, receipt["youtube_execution"]["configured_worker_upper_bound"])
        self.assertEqual(1, receipt["youtube_execution"]["actual_workers"])
        self.assertEqual(1, receipt["collection_funnel"]["valid_voices"])
        official = next(item for item in receipt["queues"] if item["backend"] == "auto")
        fallback = next(item for item in receipt["queues"] if item["backend"] == "yt-dlp")
        self.assertEqual("paused", official["status"])
        self.assertEqual("completed", fallback["status"])
        self.assertEqual(official["batch_id"], fallback["metadata"]["fallback_for_batch_id"])
        self.assertIn("--write-comments", calls[0])
        store.close()

    def test_resume_starts_from_persisted_thread_page_token(self) -> None:
        responses = {
            ("commentThreads", None, None): {
                "items": [thread("t1", "c1")],
                "nextPageToken": "T2",
            },
            ("commentThreads", "T2", None): {"items": [thread("t2", "c2")]},
        }
        failing = FailOnceHttp(responses, ("commentThreads", "T2", None))
        store, _ = self.make_store([self.youtube_queue()])
        first = cvc.CollectorService(store, api_key="secret-key", http_client=failing).run("task-1")
        self.assertEqual("platform_or_quota_limit", first["stop_reason"])
        self.assertEqual("paused", first["status"])
        official = next(item for item in first["queues"] if item["backend"] == "youtube-data-api")
        self.assertEqual("paused", official["status"])
        self.assertEqual("T2", first["checkpoints"][0]["state"]["thread_page_token"])
        second_http = FakeHttp(responses)
        second = cvc.CollectorService(store, api_key="secret-key", http_client=second_http).run(
            "task-1", resume=True
        )
        self.assertEqual("queues_exhausted", second["stop_reason"])
        self.assertEqual("T2", second_http.calls[0][1].get("pageToken"))
        self.assertEqual(2, second["collection_funnel"]["valid_voices"])
        self.assertEqual([], second["checkpoints"])
        store.close()

    def test_auto_backend_falls_back_to_injected_ytdlp_runner(self) -> None:
        calls = []

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            calls.append(list(argv))
            payload = {
                "id": "video-1",
                "comments": [
                    {
                        "id": "yd1",
                        "parent": "root",
                        "author": "viewer",
                        "author_id": "viewer-id",
                        "text": "works well",
                        "timestamp": 1785542400,
                    }
                ],
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        store, _ = self.make_store([self.youtube_queue(backend="auto")])
        receipt = cvc.CollectorService(store, runner=runner).run("task-1")
        self.assertEqual(1, receipt["collection_funnel"]["valid_voices"])
        self.assertIn("--write-comments", calls[0])
        official = next(item for item in receipt["queues"] if item["backend"] == "auto")
        fallback = next(item for item in receipt["queues"] if item["backend"] == "yt-dlp")
        self.assertEqual("paused", official["status"])
        self.assertEqual("completed", fallback["status"])
        self.assertEqual(official["batch_id"], fallback["metadata"]["fallback_for_batch_id"])
        self.assertEqual(["not_metered"], receipt["quota_and_cost"]["cost_statuses"])
        self.assertIsNone(receipt["quota_and_cost"]["estimated_direct_cost_usd"])
        store.close()

    def test_same_level_resume_after_adding_key_keeps_official_api_checkpoint(self) -> None:
        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            payload = {
                "id": "video-1",
                "comments": [
                    {
                        "id": "fallback-voice",
                        "parent": "root",
                        "author": "viewer",
                        "text": "fallback voice",
                        "timestamp": 1785542400,
                    }
                ],
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        store, _ = self.make_store([self.youtube_queue(backend="auto")])
        official_id = str(store.list_batches("task-1")[0]["batch_id"])
        store.save_checkpoint(
            "task-1",
            official_id,
            {
                "thread_page_token": "T2",
                "item_offset": 0,
                "reply_parent_id": None,
                "reply_page_token": None,
            },
        )
        first = cvc.CollectorService(store, runner=runner).run("task-1")
        self.assertEqual("paused", next(item for item in first["queues"] if item["batch_id"] == official_id)["status"])
        self.assertEqual("T2", first["checkpoints"][0]["state"]["thread_page_token"])

        http = FakeHttp({("commentThreads", "T2", None): {"items": [thread("t2", "api-voice")]}})
        second = cvc.CollectorService(
            store,
            api_key="secret",
            http_client=http,
            runner=runner,
        ).run("task-1", resume=True)
        official = next(item for item in second["queues"] if item["batch_id"] == official_id)
        self.assertEqual("completed", official["status"])
        self.assertEqual("youtube-data-api", official["backend"])
        self.assertEqual("T2", http.calls[0][1].get("pageToken"))
        self.assertEqual([], second["checkpoints"])
        store.close()

    def test_youtube_transient_http_errors_retry_with_bounded_backoff(self) -> None:
        class TransientHttp:
            def __init__(self) -> None:
                self.calls = 0

            def get_json(self, url, params, timeout, headers=None):
                self.calls += 1
                if self.calls < 3:
                    raise cvc.RetryableHttpError(500)
                return {"items": []}

        http = TransientHttp()
        charged = []
        waits = []
        result = cvc.YoutubeDataApiCollector(
            "secret",
            http,
            retry_wait=waits.append,
            max_retries=2,
        ).collect(
            "video-1",
            {},
            lambda record: None,
            lambda checkpoint: None,
            lambda operation, units: charged.append((operation, units)),
            lambda: None,
        )
        self.assertEqual(1, result["page_count"])
        self.assertEqual(3, http.calls)
        self.assertEqual([0.5, 1.0], waits)
        self.assertEqual(3, len(charged))

    def test_youtube_retry_recomputes_timeout_from_remaining_deadline(self) -> None:
        class TransientHttp:
            def __init__(self) -> None:
                self.timeouts = []

            def get_json(self, url, params, timeout, headers=None):
                self.timeouts.append(timeout)
                if len(self.timeouts) < 3:
                    raise cvc.RetryableHttpError(500)
                return {"items": []}

        remaining = iter([9.0, 4.0, 2.0])
        http = TransientHttp()
        cvc.YoutubeDataApiCollector(
            "secret",
            http,
            timeout=20.0,
            timeout_provider=lambda: next(remaining),
            retry_wait=lambda delay: None,
        ).search_videos("phone mount", lambda operation, units: None)
        self.assertEqual([9.0, 4.0, 2.0], http.timeouts)

    def test_last30days_discovery_enqueues_and_expands_youtube_in_same_run(self) -> None:
        run_dir = self.root / "run"
        run_dir.mkdir()
        commands = []

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            commands.append(list(argv))
            if "-c" in argv:
                return subprocess.CompletedProcess(argv, 0, "3.12.13\n", "")
            output_index = list(argv).index("--output") + 1
            output = Path(argv[output_index])
            payload = {
                "items_by_source": {
                    "youtube": [
                        {
                            "item_id": "video-1",
                            "body": "video review",
                            "url": "https://www.youtube.com/watch?v=video-1",
                            "published_at": "2026-08-01T00:00:00Z",
                            "author": "creator",
                            "metadata": {"video_id": "video-1", "top_comments": []},
                        }
                    ],
                    "arxiv": [
                        {
                            "item_id": "paper-1",
                            "body": "must never become consumer voice",
                            "published_at": "2026-08-01T00:00:00Z",
                        }
                    ],
                }
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        http = FakeHttp(
            {
                ("commentThreads", None, None): {
                    "items": [thread("thread-1", "comment-1")]
                }
            }
        )
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "seat cushion",
            "quick",
            END_AT,
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_primary",
                    "query_text": "seat cushion review",
                    "metadata": {"days": 30, "as_of_utc_date": "2026-08-05"},
                }
            ],
            task_id="task-1",
            run_dir=run_dir,
        )
        config = {
            "enabled": True,
            "daily_quota_units": 10000,
            "quota_reserve": 2500,
            "search_enabled": False,
            "max_results": 100,
            "max_workers": 4,
        }
        receipt = cvc.CollectorService(
            store,
            api_key="secret",
            http_client=http,
            runner=runner,
            youtube_config=config,
        ).run("task-1")
        self.assertEqual("queues_exhausted", receipt["stop_reason"])
        self.assertEqual(2, len(receipt["queues"]))
        self.assertEqual({"last30days", "youtube"}, {item["source"] for item in receipt["queues"]})
        self.assertEqual(2, receipt["collection_funnel"]["valid_voices"])
        self.assertNotIn("arxiv", {item["platform"] for item in receipt["collection_funnel"]["per_platform"]})
        last30days_command = next(command for command in commands if "--output" in command)
        self.assertIn("--plan", last30days_command)
        plan_path = Path(last30days_command[last30days_command.index("--plan") + 1])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual("seat cushion review", plan["raw_topic"])
        self.assertEqual(
            ["reddit", "x", "youtube", "tiktok", "instagram"],
            plan["subqueries"][0]["sources"],
        )
        if os.name != "nt":
            self.assertEqual(0o700, stat.S_IMODE(run_dir.stat().st_mode))
            raw_dir = run_dir / "last30days"
            self.assertEqual(0o700, stat.S_IMODE(raw_dir.stat().st_mode))
            for artifact in raw_dir.rglob("*"):
                expected = 0o700 if artifact.is_dir() else 0o600
                self.assertEqual(expected, stat.S_IMODE(artifact.stat().st_mode), artifact)
        store.close()

    def test_last30days_without_video_enqueues_ytdlp_search_discovery(self) -> None:
        run_dir = self.root / "run"
        run_dir.mkdir()
        commands = []

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            commands.append(list(argv))
            if "-c" in argv:
                return subprocess.CompletedProcess(argv, 0, "3.12.13\n", "")
            if "--output" in argv:
                output = Path(argv[list(argv).index("--output") + 1])
                payload = {
                    "items_by_source": {
                        "reddit": [
                            {
                                "item_id": "R1",
                                "body": "real category discussion",
                                "url": "https://www.reddit.com/r/test/comments/post1/title/",
                                "published_at": "2026-08-01T00:00:00Z",
                            }
                        ]
                    }
                }
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
            payload = {
                "id": "video-search-result",
                "comments": [
                    {
                        "id": "youtube-search-comment",
                        "parent": "root",
                        "author": "viewer",
                        "text": "youtube discovered by yt-dlp",
                        "timestamp": 1785542400,
                    }
                ],
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "seat cushion",
            "quick",
            END_AT,
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_q1",
                    "query_text": "seat cushion install compatibility",
                    "metadata": {"days": 30, "as_of_utc_date": "2026-08-05"},
                }
            ],
            task_id="task-1",
            run_dir=run_dir,
        )
        receipt = cvc.CollectorService(store, runner=runner).run("task-1")
        youtube_batch = next(item for item in receipt["queues"] if item["source"] == "youtube")
        self.assertEqual("yt-dlp", youtube_batch["backend"])
        self.assertTrue(youtube_batch["query_text"].startswith("ytsearch50:"))
        self.assertTrue(any("--write-comments" in command for command in commands))
        self.assertEqual(2, receipt["collection_funnel"]["valid_voices"])
        store.close()

    def test_optional_youtube_search_error_continues_to_ytdlp(self) -> None:
        run_dir = self.root / "run-search-error"
        run_dir.mkdir()

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            if "-c" in argv:
                return subprocess.CompletedProcess(argv, 0, "3.12.13\n", "")
            if "--output" in argv:
                output = Path(argv[list(argv).index("--output") + 1])
                payload = {"items_by_source": {}}
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
            payload = {
                "id": "fallback-video",
                "comments": [{
                    "id": "fallback-comment",
                    "parent": "root",
                    "author": "viewer",
                    "text": "fallback after optional search error",
                    "timestamp": 1785542400,
                }],
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test", "seat cushion", "quick", END_AT,
            [{
                "source": "last30days", "backend": "last30days",
                "scope": "category_30d", "query_id": "category_30d_q1",
                "query_text": "seat cushion", "metadata": {"days": 30},
            }],
            task_id="task-1", run_dir=run_dir,
        )
        config = {
            "enabled": True, "daily_quota_units": 10000, "quota_reserve": 2500,
            "search_enabled": True, "max_results": 100, "max_workers": 4,
        }
        http = FakeHttp({
            ("search", None, None): {"error": {"code": 403, "message": "forbidden"}}
        })
        receipt = cvc.CollectorService(
            store, api_key="secret", http_client=http, runner=runner, youtube_config=config
        ).run("task-1")
        discovery = next(item for item in receipt["queues"] if item["source"] == "last30days")
        fallback = next(item for item in receipt["queues"] if item["source"] == "youtube")
        self.assertEqual("completed", discovery["status"])
        self.assertEqual("completed", fallback["status"])
        self.assertIn("forbidden", fallback["metadata"]["official_search_error"])
        self.assertEqual(1, receipt["collection_funnel"]["valid_voices"])
        store.close()

    def test_last30days_runtime_probe_is_deadline_bounded_and_cached(self) -> None:
        run_dir = self.root / "run-runtime-cache"
        run_dir.mkdir()
        script = self.root / "last30days.py"
        script.write_text("# test fixture\n", encoding="utf-8")
        old_python = os.environ.get("LCADMO_PYTHON")
        old_script = os.environ.get("LAST30DAYS_SCRIPT")
        os.environ["LCADMO_PYTHON"] = "fake-python"
        os.environ["LAST30DAYS_SCRIPT"] = str(script)
        version_timeouts = []

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            if "-c" in argv:
                version_timeouts.append(timeout)
                return subprocess.CompletedProcess(argv, 0, "3.12.13\n", "")
            if "--output" in argv:
                output = Path(argv[list(argv).index("--output") + 1])
                marker = output.stem
                payload = {"items_by_source": {"reddit": [{
                    "item_id": marker,
                    "body": "runtime cache voice " + marker,
                    "url": "https://www.reddit.com/comments/%s/title/" % marker,
                    "published_at": "2026-08-01T00:00:00Z",
                }]}}
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
            return subprocess.CompletedProcess(argv, 0, json.dumps({"comments": []}), "")

        try:
            store = cvc.CollectorStore(self.db)
            store.create_task(
                "test", "seat cushion", "quick", END_AT,
                [
                    {"source": "last30days", "backend": "last30days", "scope": "category_30d", "query_id": "q1", "query_text": "one"},
                    {"source": "last30days", "backend": "last30days", "scope": "category_30d", "query_id": "q2", "query_text": "two"},
                ],
                task_id="task-1", run_dir=run_dir,
            )
            store.update_task(
                "task-1", collection_elapsed_seconds=2095.0, updated_at=cvc.iso_utc()
            )
            cvc.CollectorService(store, runner=runner).run("task-1")
            self.assertEqual(1, len(version_timeouts))
            self.assertLessEqual(version_timeouts[0], 5.0)
            store.close()
        finally:
            if old_python is None:
                os.environ.pop("LCADMO_PYTHON", None)
            else:
                os.environ["LCADMO_PYTHON"] = old_python
            if old_script is None:
                os.environ.pop("LAST30DAYS_SCRIPT", None)
            else:
                os.environ["LAST30DAYS_SCRIPT"] = old_script

    def test_scope_window_is_strict_left_closed_right_open(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        for index, timestamp in enumerate(
            ["2026-07-06T00:00:00Z", "2026-08-04T23:59:59Z", "2026-08-05T00:00:00Z"]
        ):
            store.insert_comment(
                "task-1",
                batch,
                {
                    "source": "youtube",
                    "content_id": "c%d" % index,
                    "text": "voice",
                    "published_at": timestamp,
                },
            )
        self.assertEqual(2, store.valid_count("task-1"))
        funnel = store.collection_funnel("task-1")
        self.assertEqual(3, funnel["unique_records"])
        self.assertEqual(1, funnel["excluded_records"])
        store.close()

    def test_funnel_fetched_count_cannot_fall_below_unique_discoveries(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        for index in range(2):
            store.insert_comment(
                "task-1",
                batch,
                {
                    "source": "youtube",
                    "content_id": "underreported-%d" % index,
                    "text": "voice %d" % index,
                    "published_at": "2026-08-01T00:00:00Z",
                },
            )
        store.update_batch(batch["batch_id"], raw_candidate_count=1)
        funnel = store.collection_funnel("task-1")
        self.assertEqual(2, funnel["fetched_records"])
        self.assertEqual(2, funnel["unique_records"])
        self.assertTrue(
            all(
                funnel[left] >= funnel[right]
                for left, right in zip(cvc.FUNNEL_STAGE_FIELDS, cvc.FUNNEL_STAGE_FIELDS[1:])
            )
        )
        scope_funnel = funnel["per_scope"][0]
        self.assertEqual(2, scope_funnel["fetched_records"])
        self.assertEqual(2, scope_funnel["unique_records"])
        store.close()

    def test_prepare_and_merge_coding_updates_funnel(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        store.insert_comment(
            "task-1",
            batch,
            {
                "source": "youtube",
                "content_id": "c1",
                "text": "seller promotion",
                "published_at": "2026-08-01T00:00:00Z",
            },
        )
        output = self.root / "coding"
        manifest = cvc.prepare_coding(store, "task-1", output, batch_size=1)
        self.assertEqual(1, manifest["record_count"])
        path = Path(manifest["files"][0]["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["records"][0]["coding"] = {
            "eligible_for_quantitation": False,
            "is_relevant": False,
            "is_consumer": False,
            "exclusion_reason": "seller_promotion",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        merged = cvc.merge_coding(store, "task-1", [path])
        self.assertEqual(1, merged["updated"])
        funnel = store.collection_funnel("task-1")
        self.assertEqual(0, funnel["valid_voices"])
        self.assertEqual("seller_promotion", funnel["exclusion_reasons"][0]["reason"])
        store.close()

    def test_duplicate_discovery_cannot_reenable_a_coding_exclusion(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        comment = {
            "source": "youtube",
            "content_id": "coded-exclusion",
            "video_id": "video-1",
            "text": "buy now promotion",
            "published_at": "2026-08-01T00:00:00Z",
        }
        record_id, _, _ = store.insert_comment("task-1", batch, comment)
        store.merge_coding(
            "task-1",
            [
                {
                    "record_id": record_id,
                    "coding": {
                        "eligible_for_quantitation": False,
                        "is_relevant": False,
                        "is_consumer": False,
                        "exclusion_reason": "seller_promotion",
                    },
                }
            ],
        )
        _, new_unique, new_valid = store.insert_comment("task-1", batch, comment)
        self.assertFalse(new_unique or new_valid)
        row = store.connection.execute(
            "SELECT eligible_for_quantitation,coding_status,exclusion_reason FROM comments WHERE record_id=?",
            (record_id,),
        ).fetchone()
        self.assertEqual(0, row["eligible_for_quantitation"])
        self.assertEqual("coded", row["coding_status"])
        self.assertEqual("seller_promotion", row["exclusion_reason"])
        store.close()

    def test_three_low_increment_batches_and_receipt_disclosure(self) -> None:
        queues = [self.youtube_queue(batch_id="b%d" % index, query_id="q%d" % index) for index in range(3)]
        store, _ = self.make_store(queues)
        for index in range(3):
            store.update_batch(
                "b%d" % index,
                status="completed",
                raw_candidate_count=100,
                new_valid_count=2,
                finished_at="2026-08-01T00:00:0%dZ" % index,
                updated_at="2026-08-01T00:00:0%dZ" % index,
            )
        self.assertTrue(store.has_three_low_increment_batches("task-1"))
        self.assertTrue(store.has_three_low_increment_batches("task-1", scope="category_30d"))
        receipt = cvc.build_receipt(store, "task-1")
        self.assertEqual(3, len(receipt["recent_3_batches"]))
        self.assertTrue(all(item["increment_rate"] < 0.03 for item in receipt["recent_3_batches"]))
        store.close()

    def test_low_increment_saturation_is_scoped(self) -> None:
        queues = [
            self.youtube_queue(batch_id="category-%d" % index, query_id="cq%d" % index)
            for index in range(3)
        ]
        store, _ = self.make_store(queues)
        for index in range(3):
            store.update_batch(
                "category-%d" % index,
                status="completed",
                raw_candidate_count=100,
                new_valid_count=2,
                finished_at="2026-08-01T00:00:0%dZ" % index,
                updated_at="2026-08-01T00:00:0%dZ" % index,
            )
        self.assertTrue(store.has_three_low_increment_batches("task-1", scope="category_30d"))
        self.assertFalse(store.has_three_low_increment_batches("task-1", scope="segment_1_90d"))
        self.assertTrue(store.has_completed_comment_expansion_batch("task-1", "category_30d"))
        self.assertFalse(
            store.has_completed_comment_expansion_batch("task-1", "segment_1_90d")
        )
        store.close()

    def test_prepare_coding_autocodes_technical_exclusions(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        invalid = {
            "source": "youtube",
            "content_id": "old-comment",
            "thread_id": "thread-old",
            "author_label": "viewer",
            "text": "old but otherwise valid comment",
            "published_at": "2025-01-01T00:00:00Z",
            "url": "https://www.youtube.com/watch?v=video&lc=old-comment",
        }
        store.insert_comment("task-1", batch, invalid)
        manifest = cvc.prepare_coding(store, "task-1", self.root / "coding", batch_size=200)
        self.assertEqual(0, manifest["record_count"])
        self.assertEqual(1, manifest["technical_auto_excluded_count"])
        row = store.connection.execute(
            "SELECT coding_status,coding_batch_id,coding_json FROM comments WHERE content_id=?",
            ("old-comment",),
        ).fetchone()
        self.assertEqual("coded", row["coding_status"])
        self.assertEqual("technical_precheck", row["coding_batch_id"])
        self.assertFalse(json.loads(row["coding_json"])["eligible_for_quantitation"])
        store.close()

    def test_youtube_batches_are_round_robin_by_scope(self) -> None:
        rows = [
            {"batch_id": "broad", "source": "last30days", "scope": "category_30d"},
            {"batch_id": "c1", "source": "youtube", "scope": "category_30d"},
            {"batch_id": "c2", "source": "youtube", "scope": "category_30d"},
            {"batch_id": "s21", "source": "youtube", "scope": "segment_2_90d"},
            {"batch_id": "s22", "source": "youtube", "scope": "segment_2_90d"},
            {"batch_id": "s31", "source": "youtube", "scope": "segment_3_90d"},
        ]
        scheduled = cvc.interleave_youtube_batches_by_scope(
            rows, ["segment_2_90d", "segment_3_90d", "category_30d"]
        )
        self.assertEqual(
            ["broad", "s21", "s31", "c1", "s22", "c2"],
            [row["batch_id"] for row in scheduled],
        )

    def test_empty_fallback_children_do_not_trigger_low_increment_stop(self) -> None:
        store, _ = self.make_store([])
        for index in range(3):
            store.add_batch(
                "task-1",
                {
                    "batch_id": "fallback-%d" % index,
                    "source": "youtube",
                    "backend": "yt-dlp",
                    "scope": "category_30d",
                    "query_id": "fallback-q%d" % index,
                    "metadata": {"fallback_for_batch_id": "official-%d" % index},
                },
            )
            store.update_batch(
                "fallback-%d" % index,
                status="completed",
                raw_candidate_count=0,
                new_valid_count=0,
                finished_at="2026-08-01T00:00:0%dZ" % index,
                updated_at="2026-08-01T00:00:0%dZ" % index,
            )
        self.assertEqual([], store.low_increment_tail("task-1"))
        self.assertFalse(store.has_three_low_increment_batches("task-1"))
        store.close()

    def test_collection_deadline_is_hard_stop_reason(self) -> None:
        class Clock:
            values = iter([0.0, 0.0, 2200.0, 2200.0, 2200.0])

            def __call__(self) -> float:
                return next(self.values, 2200.0)

        store, _ = self.make_store([self.youtube_queue()])
        receipt = cvc.CollectorService(store, api_key="key", monotonic=Clock()).run("task-1")
        self.assertEqual("collection_deadline", receipt["stop_reason"])
        self.assertEqual("paused", receipt["status"])
        store.close()

    def test_youtube_setup_creates_blank_0600_config_without_accepting_a_key(self) -> None:
        config = self.root / "youtube.env"
        result = cvc.setup_youtube_api_config(config)
        self.assertEqual(0o600, stat.S_IMODE(config.stat().st_mode))
        self.assertEqual("created", result["status"])
        self.assertEqual(set(cvc.YOUTUBE_CONFIG_KEYS), set(cvc.parse_env_file(config)))
        self.assertEqual("true", cvc.parse_env_file(config)["YOUTUBE_DATA_API_ENABLED"])
        original = config.read_text(encoding="utf-8")
        second = cvc.setup_youtube_api_config(config)
        self.assertEqual("exists_not_overwritten", second["status"])
        self.assertEqual(original, config.read_text(encoding="utf-8"))
        checked = cvc.check_youtube_api_config(config)
        self.assertEqual("needs_setup", checked["status"])
        with self.assertRaises(SystemExit):
            cvc.build_parser().parse_args(
                ["youtube-api-setup", "--config", str(config), "--api-key", "forbidden"]
            )

    def test_first_run_after_blank_setup_disables_official_api_without_aborting(self) -> None:
        config = self.root / "youtube.env"
        cvc.setup_youtube_api_config(config)
        parser = cvc.build_parser()
        planned = cvc.execute(
            parser.parse_args(
                [
                    "plan",
                    "--db",
                    str(self.db),
                    "--research-level",
                    "quick",
                    "--youtube-config",
                    str(config),
                ]
            )
        )
        self.assertEqual("needs_setup", planned["youtube_channel_status"])
        result = cvc.execute(
            parser.parse_args(
                ["run", "--db", str(self.db), "--youtube-config", str(config)]
            )
        )
        self.assertEqual("collection_completed", result["status"])
        self.assertEqual("queues_exhausted", result["stop_reason"])
        self.assertEqual("needs_setup", result["youtube_channel_status"])
        self.assertIn("instructions", result["youtube_setup"])

    def test_youtube_live_check_is_read_only_and_never_returns_key_fingerprint(self) -> None:
        config = self.root / "youtube.env"
        secret = "AIzaTHIS_IS_A_PRIVATE_KEY_123456"
        values = dict(cvc.YOUTUBE_CONFIG_DEFAULTS)
        values["YOUTUBE_DATA_API_ENABLED"] = "true"
        values["YOUTUBE_DATA_API_KEY"] = secret
        config.write_text("\n".join("%s=%s" % item for item in values.items()) + "\n", encoding="utf-8")
        os.chmod(config, 0o600)
        http = FakeHttp({("videos", None, None): {"items": [{"id": "dQw4w9WgXcQ"}]}})
        result = cvc.youtube_api_live_check(config, http)
        self.assertEqual("ok", result["status"])
        self.assertEqual("videos.list", result["live_check"]["operation"])
        self.assertNotIn("key", http.calls[0][1])
        self.assertEqual(secret, http.calls[0][2]["x-goog-api-key"])
        rendered = json.dumps(result)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("fingerprint", rendered)
        self.assertIn("<redacted>", cvc.redact_text("https://x.test?a=1&key=" + secret))

    def test_insecure_key_file_is_rejected(self) -> None:
        config = self.root / "youtube.env"
        config.write_text("YOUTUBE_API_KEY=secret\n", encoding="utf-8")
        os.chmod(config, 0o644)
        with self.assertRaises(cvc.ConfigurationError):
            cvc.parse_env_file(config, require_secure=True)

    def test_resume_allows_only_research_level_upgrade(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        self.assertEqual("standard", store.upgrade_research_level("task-1", "standard"))
        upgraded = store.task_payload("task-1")["research_plan"]
        self.assertEqual(3000, upgraded["sample_target"]["total_valid_max"])
        with self.assertRaises(cvc.ConfigurationError):
            store.upgrade_research_level("task-1", "quick")
        store.close()

    def test_boot_id_separates_incompatible_python_clock_domains(self) -> None:
        completed = subprocess.CompletedProcess(
            ["sysctl", "-n", "kern.boottime"],
            0,
            stdout="{ sec = 123, usec = 0 }\n",
            stderr="",
        )
        with mock.patch.object(cvc.sys, "platform", "darwin"), mock.patch.object(
            cvc.subprocess, "run", return_value=completed
        ):
            with mock.patch.object(cvc.sys, "executable", "/runtime/a/python3"):
                first = cvc.current_boot_id()
            with mock.patch.object(cvc.sys, "executable", "/runtime/b/python3"):
                second = cvc.current_boot_id()
        self.assertNotEqual(first, second)
        self.assertEqual(24, len(first))
        self.assertEqual(24, len(second))

    def test_external_phase_timing_is_idempotent_and_blocks_concurrent_phase(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        started = store.begin_timing_phase(
            "task-1",
            "agent_reach",
            "workflow-1",
            boot_id="boot-a",
            monotonic_ns=1_000_000_000,
        )
        phase_id = started["phase_run_id"]
        with self.assertRaises(cvc.ConfigurationError):
            store.begin_timing_phase(
                "task-1",
                "codex_coding",
                "workflow-1",
                boot_id="boot-a",
                monotonic_ns=2_000_000_000,
            )
        first = store.heartbeat_timing_phase(
            "task-1",
            phase_id,
            "event-1",
            boot_id="boot-a",
            monotonic_ns=11_000_000_000,
        )
        replay = store.heartbeat_timing_phase(
            "task-1",
            phase_id,
            "event-1",
            boot_id="boot-a",
            monotonic_ns=21_000_000_000,
        )
        self.assertEqual(10.0, first["delta_seconds"])
        self.assertTrue(replay["replayed"])
        ended = store.end_timing_phase(
            "task-1",
            phase_id,
            "event-2",
            boot_id="boot-a",
            monotonic_ns=31_000_000_000,
        )
        self.assertEqual(20.0, ended["delta_seconds"])
        usage = store.timing_usage(
            "task-1", include_running=False, boot_id="boot-a", monotonic_ns=31_000_000_000
        )
        self.assertEqual(30.0, usage["external_total_seconds"])
        self.assertEqual(30.0, usage["external_collection_seconds"])
        self.assertEqual(2, store.connection.execute("SELECT COUNT(*) FROM timing_events").fetchone()[0])
        store.close()

    def test_agent_reach_heartbeat_and_end_enforce_collection_deadline(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        phase = store.begin_timing_phase(
            "task-1",
            "agent_reach",
            "workflow-agent",
            boot_id="boot-a",
            monotonic_ns=0,
        )
        phase_id = phase["phase_run_id"]
        heartbeat = store.heartbeat_timing_phase(
            "task-1",
            phase_id,
            "agent-heartbeat",
            boot_id="boot-a",
            monotonic_ns=36 * 60 * 1_000_000_000,
        )
        self.assertFalse(heartbeat["gate"]["allowed"])
        self.assertEqual("stop_collection", heartbeat["gate"]["action"])
        self.assertEqual(0.0, heartbeat["gate"]["max_step_seconds"])
        task = store.task_row("task-1")
        self.assertEqual("collection_deadline", task["stop_reason"])
        self.assertEqual("collection_deadline", task["collection_stop_reason"])

        ended = store.end_timing_phase(
            "task-1",
            phase_id,
            "agent-end",
            boot_id="boot-a",
            monotonic_ns=36 * 60 * 1_000_000_000,
        )
        self.assertEqual("stop_collection", ended["gate"]["action"])
        self.assertEqual("completed", ended["status"])
        store.close()

    def test_unmetered_setup_and_stale_phase_do_not_consume_budget_or_idle_gap(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        setup = store.begin_timing_phase(
            "task-1",
            "youtube_api_setup",
            "workflow-setup",
            boot_id="boot-a",
            monotonic_ns=1,
        )
        store.end_timing_phase(
            "task-1",
            setup["phase_run_id"],
            "setup-end",
            boot_id="boot-a",
            monotonic_ns=86_400_000_000_001,
        )
        coding = store.begin_timing_phase(
            "task-1",
            "codex_coding",
            "workflow-1",
            boot_id="boot-a",
            monotonic_ns=100_000_000_000_000,
        )
        store.heartbeat_timing_phase(
            "task-1",
            coding["phase_run_id"],
            "coding-heartbeat",
            boot_id="boot-a",
            monotonic_ns=110_000_000_000_000,
        )
        # A different boot cannot add the uncommitted idle interval.
        usage = store.timing_usage(
            "task-1",
            include_running=True,
            boot_id="boot-b",
            monotonic_ns=999_999_999_999_999,
        )
        self.assertEqual(10_000.0, usage["external_total_seconds"])
        self.assertEqual(86_400.0, usage["unmetered_seconds"])
        self.assertEqual(1, store.abandon_open_timing_sessions("task-1"))
        self.assertEqual(
            "abandoned",
            store.connection.execute(
                "SELECT status FROM timing_sessions WHERE phase_run_id=?",
                (coding["phase_run_id"],),
            ).fetchone()[0],
        )
        store.close()

    def test_resume_abandons_open_external_phase_but_keeps_heartbeats(self) -> None:
        store, _ = self.make_store([self.youtube_queue(backend="yt-dlp")])
        phase = store.begin_timing_phase(
            "task-1",
            "agent_reach",
            "workflow-before-resume",
            boot_id="boot-a",
            monotonic_ns=1_000_000_000,
        )
        store.heartbeat_timing_phase(
            "task-1",
            phase["phase_run_id"],
            "before-resume-heartbeat",
            boot_id="boot-a",
            monotonic_ns=11_000_000_000,
        )

        def runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
            payload = {
                "id": "video-1",
                "comments": [
                    {
                        "id": "after-resume",
                        "text": "new comment",
                        "timestamp": 1785542400,
                        "author": "driver",
                    }
                ],
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

        cvc.CollectorService(store, runner=runner).run("task-1", resume=True)
        session = store.connection.execute(
            "SELECT status,committed_seconds FROM timing_sessions WHERE phase_run_id=?",
            (phase["phase_run_id"],),
        ).fetchone()
        self.assertEqual("abandoned", session["status"])
        self.assertEqual(10.0, session["committed_seconds"])
        self.assertGreaterEqual(
            store.timing_usage("task-1", include_running=False)["external_total_seconds"],
            10.0,
        )
        store.close()

    def test_three_level_finalization_reserve_gate_and_upgrade_preserve_time(self) -> None:
        original_db = self.db
        try:
            for level, used_minutes in (("quick", 55), ("standard", 85), ("deep", 115)):
                with self.subTest(level=level):
                    self.db = self.root / ("collector_%s.sqlite3" % level)
                    store, _ = self.make_store([self.youtube_queue()], level=level)
                    store.update_task(
                        "task-1",
                        total_elapsed_seconds=used_minutes * 60,
                        updated_at=cvc.iso_utc(),
                    )
                    expansion = store.timing_gate("task-1", "concept_images")
                    finalization = store.timing_gate("task-1", "report_finalize")
                    self.assertFalse(expansion["allowed"])
                    self.assertEqual("finalize_now", expansion["action"])
                    self.assertEqual(0.0, expansion["max_step_seconds"])
                    self.assertTrue(finalization["allowed"])
                    self.assertEqual(300.0, finalization["max_step_seconds"])
                    if level == "quick":
                        store.upgrade_research_level("task-1", "standard")
                        self.assertEqual(
                            used_minutes * 60,
                            store.timing_usage("task-1", include_running=False)[
                                "effective_total_seconds"
                            ],
                        )
                    store.close()
        finally:
            self.db = original_db

    def test_collector_resume_never_consumes_finalization_reserve(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        store.update_task(
            "task-1",
            total_elapsed_seconds=55 * 60,
            updated_at=cvc.iso_utc(),
        )
        receipt = cvc.CollectorService(store, monotonic=lambda: 0.0).run(
            "task-1", resume=True
        )
        self.assertEqual("total_deadline", receipt["stop_reason"])
        self.assertEqual("paused", receipt["status"])
        self.assertEqual(55.0, receipt["time_usage_minutes"]["total"])
        self.assertIsNone(receipt["finished_at"])
        store.close()

    def test_manifest_finalize_is_the_only_phase_that_finishes_full_task(self) -> None:
        store, _ = self.make_store([])
        collected = cvc.CollectorService(store, monotonic=lambda: 0.0).run("task-1")
        self.assertEqual("collection_completed", collected["status"])
        self.assertIsNone(collected["finished_at"])

        phase = store.begin_timing_phase(
            "task-1",
            "manifest_finalize",
            "workflow-finalize",
            boot_id="boot-a",
            monotonic_ns=1_000_000_000,
            now=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
        )
        manifest_path = self.root / "project_manifest.json"
        candidate = b'{"status":{"consumer_product_discovery":"ready"}}\n'
        fallback = b'{"status":{"consumer_product_discovery":"partial"}}\n'
        intent = store.create_manifest_finalize_intent(
            "task-1",
            phase["phase_run_id"],
            "manifest-finished",
            manifest_path,
            "ready",
            cvc.hashlib.sha256(candidate).hexdigest(),
            fallback,
        )
        cvc._atomic_write_bytes(manifest_path, candidate)
        store.mark_manifest_finalize_intent_written("task-1", intent["intent_id"])
        store.end_timing_phase(
            "task-1",
            phase["phase_run_id"],
            "manifest-finished",
            boot_id="boot-a",
            monotonic_ns=2_000_000_000,
            now=datetime(2026, 8, 5, 1, 1, tzinfo=timezone.utc),
        )
        store.complete_manifest_finalize_intent(
            "task-1",
            intent["intent_id"],
            "ready",
            cvc.hashlib.sha256(candidate).hexdigest(),
            now=datetime(2026, 8, 5, 1, 1, tzinfo=timezone.utc),
        )
        finished = store.task_row("task-1")
        self.assertEqual("completed", finished["status"])
        self.assertEqual("2026-08-05T01:01:00Z", finished["finished_at"])
        store.close()

    def test_finalization_gate_rejects_new_phase_after_total_deadline(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        store.update_task(
            "task-1",
            total_elapsed_seconds=60 * 60,
            updated_at=cvc.iso_utc(),
        )
        gate = store.timing_gate("task-1", "report_finalize")
        self.assertFalse(gate["allowed"])
        self.assertEqual("deadline_exceeded", gate["action"])
        self.assertEqual(0.0, gate["max_step_seconds"])
        with self.assertRaises(cvc.ConfigurationError):
            store.begin_timing_phase(
                "task-1", "report_finalize", "workflow-too-late"
            )
        store.close()

    def test_receipt_is_timing_read_only(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        store.update_task("task-1", total_elapsed_seconds=12.5, updated_at=cvc.iso_utc())
        store.close()
        parser = cvc.build_parser()
        args = parser.parse_args(
            ["receipt", "--db", str(self.db), "--task-id", "task-1"]
        )
        first = cvc.execute(args)
        second = cvc.execute(args)
        self.assertEqual(first["time_usage_minutes"], second["time_usage_minutes"])
        with cvc.CollectorStore(self.db) as reopened:
            self.assertEqual(12.5, reopened.task_row("task-1")["total_elapsed_seconds"])

    def test_upgrade_after_queues_exhausted_clones_completed_acquisition_once(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        first_http = FakeHttp(
            {("commentThreads", None, None): {"items": [thread("t-quick", "quick-comment")]}}
        )
        first = cvc.CollectorService(store, api_key="secret", http_client=first_http).run(
            "task-1"
        )
        self.assertEqual("queues_exhausted", first["stop_reason"])
        self.assertEqual("completed", first["queues"][0]["status"])
        original_end_at = store.task_row("task-1")["end_at"]

        self.assertEqual("standard", store.upgrade_research_level("task-1", "standard"))
        batches = [store.batch_payload(row) for row in store.list_batches("task-1")]
        self.assertEqual(2, len(batches))
        clone = next(batch for batch in batches if batch["status"] == "planned")
        self.assertEqual("standard", clone["metadata"]["upgrade_target_level"])
        self.assertEqual(batches[0]["batch_id"], clone["metadata"]["upgrade_root_batch_id"])
        self.assertEqual(original_end_at, store.task_row("task-1")["end_at"])

        # A same-level resume must not create another clone.
        self.assertEqual("standard", store.upgrade_research_level("task-1", "standard"))
        self.assertEqual(2, len(store.list_batches("task-1")))

        second_http = FakeHttp(
            {("commentThreads", None, None): {"items": [thread("t-standard", "standard-comment")]}}
        )
        second = cvc.CollectorService(store, api_key="secret", http_client=second_http).run(
            "task-1", resume=True
        )
        self.assertEqual("queues_exhausted", second["stop_reason"])
        self.assertEqual(2, second["collection_funnel"]["valid_voices"])
        self.assertEqual(original_end_at, store.task_row("task-1")["end_at"])
        store.close()

    def test_upgrade_clones_official_chain_but_not_fallback_child(self) -> None:
        store, _ = self.make_store([self.youtube_queue(batch_id="official", backend="auto")])
        store.update_batch(
            "official", status="completed", raw_candidate_count=1,
            finished_at="2026-08-01T00:00:00Z", updated_at="2026-08-01T00:00:00Z",
        )
        store.add_batch(
            "task-1",
            {
                "batch_id": "fallback", "source": "youtube", "backend": "yt-dlp",
                "scope": "category_30d", "query_id": "q1__fallback", "video_id": "video-1",
                "metadata": {"fallback_for_batch_id": "official"},
            },
        )
        store.update_batch(
            "fallback", status="completed", raw_candidate_count=1,
            finished_at="2026-08-01T00:00:01Z", updated_at="2026-08-01T00:00:01Z",
        )
        store.upgrade_research_level("task-1", "standard")
        batches = [store.batch_payload(row) for row in store.list_batches("task-1")]
        clones = [item for item in batches if item["status"] == "planned"]
        self.assertEqual(1, len(clones))
        self.assertEqual("official", clones[0]["metadata"]["upgrade_root_batch_id"])
        self.assertNotIn("fallback_for_batch_id", clones[0]["metadata"])
        store.close()

    def test_scope_cap_pauses_batch_so_upgrade_can_resume_same_checkpoint(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        for index in range(400):
            store.insert_comment(
                "task-1",
                batch,
                {
                    "source": "youtube",
                    "content_id": "pre-%d" % index,
                    "video_id": "video-1",
                    "text": "distinct consumer message %d" % index,
                    "published_at": "2026-08-01T00:00:00Z",
                },
            )
        first = cvc.CollectorService(store).run("task-1")
        self.assertEqual("paused", first["queues"][0]["status"])
        self.assertEqual("scope_upper_reached", first["queues"][0]["error"])
        store.upgrade_research_level("task-1", "standard")
        http = FakeHttp(
            {("commentThreads", None, None): {"items": [thread("t-new", "post-upgrade")]}}
        )
        second = cvc.CollectorService(store, api_key="secret", http_client=http).run(
            "task-1", resume=True
        )
        self.assertEqual("completed", second["queues"][0]["status"])
        self.assertEqual(401, second["collection_funnel"]["valid_voices"])
        store.close()

    def test_segment_cap_reopens_after_semantic_membership_coding(self) -> None:
        store, _ = self.make_store(
            [self.youtube_queue(scope="segment_1_90d")]
        )
        batch = store.batch_payload(store.list_batches("task-1")[0])
        record_ids = []
        for index in range(200):
            record_id, _, _ = store.insert_comment(
                "task-1",
                batch,
                {
                    "source": "youtube",
                    "content_id": "segment-pre-%d" % index,
                    "video_id": "video-1",
                    "text": "query hit %d" % index,
                    "published_at": "2026-08-01T00:00:00Z",
                },
            )
            record_ids.append(record_id)
        first = cvc.CollectorService(store).run("task-1")
        self.assertEqual("paused", first["queues"][0]["status"])
        self.assertEqual(200, store.valid_count("task-1", scope="segment_1_90d"))
        store.merge_coding(
            "task-1",
            [
                {
                    "record_id": record_id,
                    "coding": {
                        "eligible_for_quantitation": True,
                        "is_relevant": True,
                        "is_consumer": True,
                        "segment_memberships": [
                            {
                                "segment_id": "segment_1_90d",
                                "is_member": index < 20,
                            }
                        ],
                    },
                }
                for index, record_id in enumerate(record_ids)
            ],
        )
        self.assertEqual(20, store.valid_count("task-1", scope="segment_1_90d"))
        http = FakeHttp(
            {("commentThreads", None, None): {"items": [thread("t-refill", "segment-refill")]}}
        )
        second = cvc.CollectorService(store, api_key="secret", http_client=http).run(
            "task-1", resume=True
        )
        self.assertEqual("completed", second["queues"][0]["status"])
        self.assertEqual(21, store.valid_count("task-1", scope="segment_1_90d"))
        store.close()

    def test_only_supported_platforms_with_direct_links_enter_quantitation(self) -> None:
        store, _ = self.make_store(
            [
                {"source": "x", "backend": "external", "scope": "category_30d", "batch_id": "x1"},
                {"source": "twitter", "backend": "external", "scope": "category_30d", "batch_id": "x2"},
                {"source": "mastodon", "backend": "external", "scope": "category_30d", "batch_id": "m1"},
            ]
        )
        batches = {row["batch_id"]: store.batch_payload(row) for row in store.list_batches("task-1")}
        common = {
            "content_id": "123456789",
            "text": "same public voice",
            "published_at": "2026-08-01T00:00:00Z",
            "url": "https://x.com/example/status/123456789",
        }
        _, first_new, first_valid = store.insert_comment("task-1", batches["x1"], dict(common, source="x"))
        _, second_new, second_valid = store.insert_comment("task-1", batches["x2"], dict(common, source="twitter"))
        self.assertTrue(first_new and first_valid)
        self.assertFalse(second_new or second_valid)
        _, _, unknown_valid = store.insert_comment(
            "task-1",
            batches["m1"],
            dict(common, source="mastodon", content_id="m-1", url="https://example.social/post/m-1"),
        )
        _, _, missing_url_valid = store.insert_comment(
            "task-1",
            batches["x1"],
            dict(common, content_id="x-no-url", url=""),
        )
        self.assertFalse(unknown_valid or missing_url_valid)
        reasons = {
            row["content_id"]: row["exclusion_reason"]
            for row in store.connection.execute(
                "SELECT content_id,exclusion_reason FROM comments WHERE eligible_for_quantitation=0"
            )
        }
        self.assertEqual("unsupported_platform", reasons["m-1"])
        self.assertEqual("missing_source_url", reasons["x-no-url"])
        receipt = cvc.build_receipt(store, "task-1")
        self.assertEqual(1, receipt["target_attainment"]["valid_platforms"])
        self.assertEqual(["x"], [item["platform"] for item in receipt["collection_funnel"]["per_platform"] if item["valid_voices"]])
        store.close()

    def test_coding_cannot_promote_technically_invalid_records(self) -> None:
        store, _ = self.make_store(
            [
                {"source": "reddit", "backend": "external", "scope": "category_30d", "batch_id": "r1"},
                {"source": "mastodon", "backend": "external", "scope": "category_30d", "batch_id": "m1"},
            ]
        )
        batches = {row["batch_id"]: store.batch_payload(row) for row in store.list_batches("task-1")}
        invalid_comments = [
            (
                batches["m1"],
                {
                    "source": "mastodon",
                    "content_id": "unsupported-1",
                    "text": "voice",
                    "published_at": "2026-08-01T00:00:00Z",
                    "url": "https://example.social/post/unsupported-1",
                },
            ),
            (
                batches["r1"],
                {
                    "source": "reddit",
                    "text": "anonymous voice",
                    "published_at": "2026-08-01T00:00:00Z",
                    "source_position": "anonymous:1",
                },
            ),
            (
                batches["r1"],
                {
                    "source": "reddit",
                    "content_id": "reply-without-permalink",
                    "parent_content_id": "post-1",
                    "text": "reply voice",
                    "published_at": "2026-08-01T00:00:00Z",
                    "url": "https://www.reddit.com/r/test/comments/post1/title/",
                },
            ),
        ]
        for batch, comment in invalid_comments:
            record_id, _, became_valid = store.insert_comment("task-1", batch, comment)
            self.assertFalse(became_valid)
            with self.assertRaises(cvc.CollectorError):
                store.merge_coding(
                    "task-1",
                    [
                        {
                            "record_id": record_id,
                            "coding": {
                                "eligible_for_quantitation": True,
                                "is_relevant": True,
                                "is_consumer": True,
                            },
                        }
                    ],
                )
            row = store.connection.execute(
                "SELECT technical_eligible,eligible_for_quantitation FROM comments WHERE record_id=?",
                (record_id,),
            ).fetchone()
            self.assertEqual((0, 0), tuple(row))
        store.close()

    def test_default_level_reminder_is_once_and_explicit_level_is_silent(self) -> None:
        parser = cvc.build_parser()
        default_args = parser.parse_args(["plan", "--db", str(self.db)])
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            cvc.create_plan_from_args(default_args)
        self.assertEqual(1, stream.getvalue().count(cvc.DEFAULT_LEVEL_REMINDER))
        with cvc.CollectorStore(self.db) as default_store:
            default_policy = default_store.task_payload(default_store.resolve_task_id(None))[
                "collection_policy"
            ]
        self.assertFalse(default_policy["research_level_explicit"])
        explicit_db = self.root / "explicit.sqlite3"
        explicit_args = parser.parse_args(
            ["plan", "--db", str(explicit_db), "--research-level", "quick"]
        )
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            cvc.create_plan_from_args(explicit_args)
        self.assertEqual("", stream.getvalue())
        with cvc.CollectorStore(explicit_db) as explicit_store:
            explicit_policy = explicit_store.task_payload(explicit_store.resolve_task_id(None))[
                "collection_policy"
            ]
        self.assertTrue(explicit_policy["research_level_explicit"])

    def test_explicit_quick_progress_reminder_offers_nonblocking_upgrades(self) -> None:
        class Clock:
            values = iter([0.0, 61.0])

            def __call__(self) -> float:
                return next(self.values)

        events = []
        reminder = cvc.NonBlockingReminder(
            True,
            60.0,
            sink=events.append,
            monotonic=Clock(),
            research_level="quick",
            offer_level_options=True,
        )
        reminder.maybe({"task_id": "task-1"})
        self.assertEqual(1, len(events))
        self.assertFalse(events[0]["blocking"])
        self.assertEqual(["standard", "deep"], events[0]["optional_research_levels"])
        self.assertNotIn("?", events[0]["level_note"])
        self.assertNotIn("？", events[0]["level_note"])

    def test_project_query_plan_has_two_queries_per_scope_and_all_six_intents(self) -> None:
        selection = {
            "source": {"keyword": "seat cushion"},
            "selected_segments": [
                {"segment_id": "segment_%d_90d" % index, "feature": "feature%d" % index, "synonyms": []}
                for index in range(1, 4)
            ],
            "top3_selection": {"selected_segment_ids": ["segment_%d_90d" % index for index in range(1, 4)]},
        }
        queues, plan, agent_queue = cvc._project_query_queues(selection, END_AT)
        self.assertEqual(8, len(queues))
        self.assertEqual(8, len({item["query_id"] for item in queues}))
        self.assertEqual(8, len({item["query_id"] for item in plan["queries"]}))
        for scope in cvc.SCOPES:
            self.assertEqual(2, sum(1 for item in plan["queries"] if item["scope_id"] == scope))
        intents = {
            intent for item in plan["queries"] for intent in item["intent_coverage"]
        }
        self.assertEqual(
            {
                "purchase_selection_recommendation",
                "satisfaction_recommendation_repurchase",
                "installation_compatibility_usage_scenario",
                "failure_complaint_return_alternative",
                "diy_modification_workaround",
                "feature_request_reverse_need_idea",
            },
            intents,
        )
        self.assertTrue(any("repurchase" in item["query_text"] and "compatibility" in item["query_text"] for item in plan["queries"]))
        self.assertTrue(any("workaround" in item["query_text"] and "return" in item["query_text"] for item in plan["queries"]))
        self.assertEqual(8, len(agent_queue["tasks"]))
        self.assertIn("required_fields", agent_queue["import_contract"])
        self.assertTrue(all("仅深读重点 Reddit/X" in item["instruction"] for item in agent_queue["tasks"]))
        self.assertTrue(all("Reddit/X/YouTube" not in item["instruction"] for item in agent_queue["tasks"]))

    def test_segment_queries_use_canonical_target_language_as_or_filter(self) -> None:
        selection = {
            "source": {"keyword": "car phone holder"},
            "selected_segments": [
                {
                    "segment_id": "segment_1_90d",
                    "feature": "机械夹持",
                    "canonical_key": "手机固定机制:mechanical_clamp",
                    "synonyms": [],
                },
                {
                    "segment_id": "segment_2_90d",
                    "feature": "卡车/重型车适用",
                    "canonical_key": "车型适配:truck",
                    "synonyms": ["semi truck"],
                },
                {
                    "segment_id": "segment_3_90d",
                    "feature": "Tesla专用",
                    "canonical_key": "车型适配:tesla",
                    "synonyms": [],
                },
            ],
            "top3_selection": {
                "selected_segment_ids": [
                    "segment_1_90d",
                    "segment_2_90d",
                    "segment_3_90d",
                ]
            },
        }
        _, plan, _ = cvc._project_query_queues(selection, END_AT)
        by_scope = {
            scope: [row["query_text"] for row in plan["queries"] if row["scope_id"] == scope]
            for scope in cvc.SCOPES[1:]
        }
        self.assertTrue(all('"mechanical clamp" OR "机械夹持"' in text for text in by_scope["segment_1_90d"]))
        self.assertTrue(all('(truck OR "卡车/重型车适用" OR "semi truck")' in text for text in by_scope["segment_2_90d"]))
        self.assertTrue(all('(tesla OR "Tesla专用")' in text for text in by_scope["segment_3_90d"]))

    def test_plan_first_use_creates_secure_blank_youtube_config(self) -> None:
        parser = cvc.build_parser()
        config = Path(os.environ["LCADMO_YOUTUBE_API_CONFIG"])
        self.assertFalse(config.exists())
        result = cvc.create_plan_from_args(parser.parse_args(["plan", "--db", str(self.db)]))
        self.assertTrue(config.is_file())
        self.assertEqual(0o600, stat.S_IMODE(config.stat().st_mode))
        self.assertEqual("needs_setup", result["youtube_channel_status"])
        self.assertEqual("created", result["youtube_configuration"]["first_use_setup"]["status"])

    def test_run_project_dir_reuses_latest_matching_planned_task(self) -> None:
        project = self.root / "market_project_20260805_000000"
        run_dir = project / "market_opportunity" / "consumer_voice_20260805_000000"
        run_dir.mkdir(parents=True)
        db_path = run_dir / "collector.sqlite3"
        with cvc.CollectorStore(db_path) as store:
            store.create_task(
                "planned",
                "chair",
                "quick",
                END_AT,
                [],
                task_id="planned-task",
                project_dir=project,
                run_dir=run_dir,
            )
        parser = cvc.build_parser()
        result = cvc.execute(
            parser.parse_args(
                [
                    "run",
                    "--project-dir",
                    str(project),
                    "--research-level",
                    "quick",
                ]
            )
        )
        self.assertEqual("planned-task", result["task_id"])
        self.assertEqual(str(run_dir.resolve()), result["run_dir"])
        self.assertEqual(
            [run_dir],
            [child for child in run_dir.parent.glob("consumer_voice_*") if child.is_dir()],
        )

    def test_external_agent_records_are_imported_idempotently_before_coding(self) -> None:
        run_dir = self.root / "run"
        agent_dir = run_dir / "agent_reach"
        agent_dir.mkdir(parents=True)
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "chair",
            "quick",
            END_AT,
            [],
            task_id="task-1",
            run_dir=run_dir,
        )
        payload = {
            "scope_id": "category_30d",
            "query_id": "category_30d_q1",
            "records": [
                {
                    "platform": "reddit",
                    "content_id": "comment-1",
                    "parent_content_id": "post-1",
                    "author_label": "viewer",
                    "published_at": "2026-08-01T00:00:00Z",
                    "exact_text": "consumer experience",
                    "url": "https://reddit.com/comments/post/title/comment-1",
                }
            ],
        }
        (agent_dir / "category_30d_q1.json").write_text(json.dumps(payload), encoding="utf-8")
        (agent_dir / "doctor.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        (agent_dir / "check_update.json").write_text(
            json.dumps({"status": "ok"}), encoding="utf-8"
        )
        first = cvc._import_external_agent_records(run_dir, store, "task-1")
        second = cvc._import_external_agent_records(run_dir, store, "task-1")
        self.assertEqual(1, first["files_scanned"])
        self.assertEqual(1, first["new_valid"])
        self.assertEqual(0, second["new_valid"])
        self.assertEqual(1, store.valid_count("task-1"))
        store.close()

    def test_external_import_pauses_at_scope_cap_and_resumes_after_upgrade(self) -> None:
        run_dir = self.root / "run-external-cap"
        agent_dir = run_dir / "agent_reach"
        agent_dir.mkdir(parents=True)
        records = [
            {
                "platform": "reddit", "content_id": "comment-%d" % index,
                "parent_content_id": "post-1", "author_label": "viewer-%d" % index,
                "published_at": "2026-08-01T00:00:00Z",
                "exact_text": "consumer experience %d" % index,
                "url": "https://reddit.com/comments/post/title/comment-%d" % index,
            }
            for index in range(3)
        ]
        (agent_dir / "category.json").write_text(
            json.dumps({"scope_id": "category_30d", "query_id": "q1", "records": records}),
            encoding="utf-8",
        )
        store = cvc.CollectorStore(self.db)
        store.create_task("test", "chair", "quick", END_AT, [], task_id="task-1", run_dir=run_dir)
        constrained = cvc.research_plan("quick")
        constrained["sample_target"]["per_scope"]["category_30d"]["valid_max"] = 1
        store.update_task(
            "task-1", research_plan_json=cvc.compact_json(constrained), updated_at=cvc.iso_utc()
        )
        first = cvc._import_external_agent_records(run_dir, store, "task-1")
        self.assertEqual("paused_at_upper_bound", first["status"])
        self.assertEqual("scope_upper_reached", first["paused_batches"][0]["reason"])
        self.assertEqual(1, first["paused_batches"][0]["record_offset"])
        self.assertEqual(1, store.valid_count("task-1"))

        store.upgrade_research_level("task-1", "standard")
        second = cvc._import_external_agent_records(run_dir, store, "task-1")
        self.assertEqual("ok", second["status"])
        self.assertEqual(2, second["new_valid"])
        self.assertEqual(3, store.valid_count("task-1"))
        external = next(
            store.batch_payload(row)
            for row in store.list_batches("task-1")
            if row["backend"] == "external"
        )
        self.assertEqual("completed", external["status"])
        self.assertEqual(3, store.checkpoint("task-1", external["batch_id"], "external_import")["record_offset"])
        store.close()

    def test_external_import_never_crosses_total_upper_bound(self) -> None:
        run_dir = self.root / "run-external-total"
        agent_dir = run_dir / "agent_reach"
        agent_dir.mkdir(parents=True)
        records = [
            {
                "platform": "reddit", "content_id": "total-%d" % index,
                "parent_content_id": "post-total", "author_label": "viewer",
                "published_at": "2026-08-01T00:00:00Z", "exact_text": "voice",
                "url": "https://reddit.com/comments/post/title/total-%d" % index,
            }
            for index in range(2)
        ]
        (agent_dir / "category.json").write_text(
            json.dumps({"scope_id": "category_30d", "query_id": "q1", "records": records}),
            encoding="utf-8",
        )
        store = cvc.CollectorStore(self.db)
        store.create_task("test", "chair", "quick", END_AT, [], task_id="task-1", run_dir=run_dir)
        constrained = cvc.research_plan("quick")
        constrained["sample_target"]["total_valid_max"] = 1
        store.update_task(
            "task-1", research_plan_json=cvc.compact_json(constrained), updated_at=cvc.iso_utc()
        )
        result = cvc._import_external_agent_records(run_dir, store, "task-1")
        self.assertEqual("total_upper_reached", result["paused_batches"][0]["reason"])
        self.assertEqual(1, store.valid_count("task-1"))
        store.close()

    def test_agent_reach_queue_is_refreshed_with_discovered_reddit_x_urls(self) -> None:
        run_dir = self.root / "run"
        run_dir.mkdir()
        (run_dir / "agent_reach_queue.json").write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "ar_category_30d_q1",
                            "scope_id": "category_30d",
                            "query_id": "category_30d_q1",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "chair",
            "quick",
            END_AT,
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_q1",
                }
            ],
            task_id="task-1",
            run_dir=run_dir,
        )
        batch = store.batch_payload(store.list_batches("task-1")[0])
        store.insert_comment(
            "task-1",
            batch,
            {
                "source": "reddit",
                "content_id": "comment-1",
                "parent_content_id": "post-1",
                "text": "deep read this thread",
                "published_at": "2026-08-01T00:00:00Z",
                "url": "https://www.reddit.com/r/test/comments/post/title/comment-1",
            },
        )
        result = cvc.refresh_agent_reach_queue(run_dir, store, "task-1")
        self.assertEqual("ready_for_agent_execution", result["status"])
        queue = json.loads((run_dir / "agent_reach_queue.json").read_text(encoding="utf-8"))
        self.assertEqual(1, queue["tasks"][0]["target_count"])
        self.assertEqual("reddit", queue["tasks"][0]["target_urls"][0]["platform"])
        self.assertIn("Reddit/X", queue["tasks"][0]["instruction"])
        self.assertNotIn("Reddit/X/YouTube", queue["tasks"][0]["instruction"])
        store.close()

    def test_agent_reach_queue_globally_dedupes_thread_and_imports_all_routes(self) -> None:
        run_dir = self.root / "run-shared-thread"
        run_dir.mkdir()
        (run_dir / "agent_reach_queue.json").write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "ar_category",
                            "scope_id": "category_30d",
                            "query_id": "category_30d_q1",
                            "query_text": "phone mount",
                        },
                        {
                            "task_id": "ar_segment",
                            "scope_id": "segment_1_90d",
                            "query_id": "segment_1_90d_q1",
                            "query_text": "truck phone mount",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "phone mount",
            "quick",
            END_AT,
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_q1",
                    "batch_id": "category-batch",
                },
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "segment_1_90d",
                    "query_id": "segment_1_90d_q1",
                    "batch_id": "segment-batch",
                },
            ],
            task_id="task-1",
            run_dir=run_dir,
        )
        category, segment = [
            store.batch_payload(row) for row in store.list_batches("task-1")
        ]
        common = {
            "source": "reddit",
            "parent_content_id": "post-1",
            "thread_id": "post-1",
            "author_label": "driver",
            "text": "need a stronger mount",
            "published_at": "2026-08-01T00:00:00Z",
        }
        store.insert_comment(
            "task-1",
            category,
            dict(
                common,
                content_id="comment-1",
                url="https://reddit.com/r/truckers/comments/post-1/title/comment-1",
            ),
        )
        store.insert_comment(
            "task-1",
            segment,
            dict(
                common,
                content_id="comment-2",
                url="https://www.reddit.com/r/truckers/comments/post-1/title/comment-2?context=3",
            ),
        )
        result = cvc.refresh_agent_reach_queue(run_dir, store, "task-1")
        self.assertEqual(1, result["target_url_count"])
        queue = json.loads((run_dir / "agent_reach_queue.json").read_text(encoding="utf-8"))
        self.assertEqual(1, len(queue["tasks"]))
        deep_task = queue["tasks"][0]
        self.assertEqual(
            ["category_30d", "segment_1_90d"], deep_task["collection_scopes"]
        )
        self.assertEqual(
            ["category_30d_q1", "segment_1_90d_q1"], deep_task["query_ids"]
        )
        self.assertEqual(2, len(deep_task["output_import_targets"]))
        self.assertEqual(["comment-1", "comment-2"], deep_task["target_urls"][0]["content_ids"])

        output = run_dir / deep_task["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "output_import_targets": deep_task["output_import_targets"],
                    "records": [
                        {
                            "platform": "reddit",
                            "content_id": "deep-comment",
                            "parent_content_id": "post-1",
                            "thread_id": "post-1",
                            "author_label": "another driver",
                            "published_at": "2026-08-02T00:00:00Z",
                            "exact_text": "the clamp still shakes on rough roads",
                            "url": "https://reddit.com/r/truckers/comments/post-1/title/deep-comment",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        imported = cvc._import_external_agent_records(run_dir, store, "task-1")
        self.assertEqual("ok", imported["status"])
        routes = store.connection.execute(
            """SELECT d.scope,d.query_id FROM comments c
            JOIN comment_discoveries d ON d.record_id=c.record_id
            WHERE c.task_id=? AND c.content_id=? ORDER BY d.scope,d.query_id""",
            ("task-1", "deep-comment"),
        ).fetchall()
        self.assertEqual(
            [
                ("category_30d", "category_30d_q1"),
                ("segment_1_90d", "segment_1_90d_q1"),
            ],
            [(row["scope"], row["query_id"]) for row in routes],
        )
        store.close()

    def test_source_run_labels_youtube_backend_instead_of_last30days(self) -> None:
        run_dir = self.root / "run"
        run_dir.mkdir()
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "chair",
            "quick",
            END_AT,
            [self.youtube_queue(backend="yt-dlp")],
            task_id="task-1",
            run_dir=run_dir,
        )
        store.update_batch(
            store.list_batches("task-1")[0]["batch_id"],
            status="completed",
            backend="yt-dlp",
            raw_candidate_count=1,
            finished_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
        )
        runs = cvc._source_runs(store, "task-1", run_dir)
        self.assertEqual("yt-dlp", runs[0]["tool"])
        self.assertEqual("deep_thread_read", runs[0]["role"])
        self.assertEqual(["category_30d_primary"], runs[0]["query_ids"])
        store.close()

    def test_agent_reach_import_query_id_is_shared_by_plan_and_source_run(self) -> None:
        run_dir = self.root / "run"
        run_dir.mkdir()
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "phone mount",
            "quick",
            END_AT,
            [
                self.youtube_queue(
                    source="last30days",
                    backend="last30days",
                    query_id="category_30d_q1",
                    video_id=None,
                )
            ],
            task_id="task-1",
            run_dir=run_dir,
        )
        store.add_batch(
            "task-1",
            {
                "batch_id": "arimport-1",
                "source": "agent-reach",
                "backend": "external",
                "scope": "category_30d",
                "query_id": "category_30d_q1",
                "query_text": "phone mount complaints",
            },
        )
        (run_dir / "agent_reach_queue.json").write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "ar_thread_unrelated_internal_id",
                            "scope_id": "category_30d",
                            "query_id": "category_30d_q1",
                            "output_import_targets": [
                                {
                                    "scope_id": "category_30d",
                                    "query_id": "category_30d_q1",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        end_at = cvc.parse_timestamp(END_AT)
        self.assertIsNotNone(end_at)
        plan = cvc._coding_query_plan(store, "task-1", "en", end_at)
        gap_ids = {item["query_id"] for item in plan["gap_fill_queries"]}
        self.assertEqual({"ar_category_30d_q1"}, gap_ids)
        agent_run = next(
            run for run in cvc._source_runs(store, "task-1", run_dir)
            if run["tool"] == "agent-reach"
        )
        self.assertEqual(["ar_category_30d_q1"], agent_run["query_ids"])
        self.assertTrue(set(agent_run["query_ids"]).issubset(gap_ids))
        store.close()

    def test_last30days_source_runs_preserve_each_platform_status(self) -> None:
        run_dir = self.root / "run"
        raw_dir = run_dir / "last30days"
        raw_dir.mkdir(parents=True)
        raw_path = raw_dir / "category_30d_q1.json"
        raw_path.write_text(
            json.dumps(
                {
                    "items_by_source": {
                        "reddit": [{"item_id": "R1"}],
                        "x": [{"item_id": "X1"}, {"item_id": "X2"}],
                    },
                    "source_status": {
                        "reddit": {"attempted": True, "state": "ok", "items_returned": 1},
                        "x": {"attempted": True, "state": "ok", "items_returned": 2},
                        "youtube": {"attempted": True, "state": "timeout", "items_returned": 0},
                        "tiktok": {"attempted": True, "state": "auth_failed", "items_returned": 0},
                        "instagram": {"attempted": False, "state": "unavailable", "items_returned": 0},
                    },
                }
            ),
            encoding="utf-8",
        )
        store = cvc.CollectorStore(self.db)
        store.create_task(
            "test",
            "chair",
            "quick",
            END_AT,
            [
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": "category_30d",
                    "query_id": "category_30d_q1",
                }
            ],
            task_id="task-1",
            run_dir=run_dir,
        )
        batch_id = str(store.list_batches("task-1")[0]["batch_id"])
        store.update_batch(
            batch_id,
            status="completed",
            raw_candidate_count=3,
            finished_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
        )
        run = cvc._source_runs(store, "task-1", run_dir)[0]
        statuses = {item["platform"]: item for item in run["platform_statuses"]}
        self.assertEqual(set(cvc.PRIMARY_SOCIAL_PLATFORMS), set(statuses))
        self.assertEqual("ok", statuses["reddit"]["status"])
        self.assertEqual(2, statuses["x"]["result_count"])
        self.assertEqual("timeout", statuses["youtube"]["status"])
        self.assertEqual("auth_failed", statuses["tiktok"]["status"])
        self.assertEqual("not_run", statuses["instagram"]["status"])
        self.assertEqual("partial", run["status"])
        store.close()

    def test_agent_reach_health_accepts_real_doctor_mapping_and_text_update(self) -> None:
        run_dir = self.root / "run"
        agent_dir = run_dir / "agent_reach"
        agent_dir.mkdir(parents=True)
        (agent_dir / "doctor.json").write_text(
            json.dumps(
                {
                    "reddit": {"status": "ok", "active_backend": "public"},
                    "twitter": {"status": "warn", "active_backend": "web"},
                }
            ),
            encoding="utf-8",
        )
        (agent_dir / "check_update.json").write_text(
            "当前版本: v1.5.0\n✅ 已是最新版本\n",
            encoding="utf-8",
        )
        health = cvc._agent_reach_health(run_dir)
        backends = {item["platform"]: item for item in health["doctor"]["active_backends"]}
        self.assertEqual("public", backends["reddit"]["active_backend"])
        self.assertEqual("partial", backends["x"]["status"])
        self.assertEqual("partial", health["doctor"]["status"])
        self.assertEqual("ok", health["check_update"]["status"])
        self.assertEqual("1.5.0", health["check_update"]["current_version"])

    def test_doctor_overall_ready_requires_successful_agent_reach_doctor(self) -> None:
        script = self.root / "last30days.py"
        script.write_text("# fixture\n", encoding="utf-8")

        def which_without_agent(command: str):
            return "/usr/local/bin/yt-dlp" if command == "yt-dlp" else None

        with mock.patch.object(
            cvc, "detect_last30days_python", return_value={"available": True, "selected": "python3", "checked": []}
        ), mock.patch.object(cvc, "DEFAULT_LAST30DAYS_SCRIPT", script), mock.patch.object(
            cvc.shutil, "which", side_effect=which_without_agent
        ):
            missing = cvc.doctor_report(None, self.root / "missing-youtube.env")
        self.assertEqual("partial", missing["status"])
        self.assertFalse(missing["agent_reach"]["available"])
        self.assertFalse(missing["agent_reach"]["binary_available"])

        def which_with_agent(command: str):
            return {
                "yt-dlp": "/usr/local/bin/yt-dlp",
                "agent-reach": "/usr/local/bin/agent-reach",
            }.get(command)

        with mock.patch.object(
            cvc, "detect_last30days_python", return_value={"available": True, "selected": "python3", "checked": []}
        ), mock.patch.object(cvc, "DEFAULT_LAST30DAYS_SCRIPT", script), mock.patch.object(
            cvc.shutil, "which", side_effect=which_with_agent
        ):
            failed = cvc.doctor_report(
                None,
                self.root / "missing-youtube.env",
                runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 1, "", "failed"),
            )
            ready = cvc.doctor_report(
                None,
                self.root / "missing-youtube.env",
                runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "{}", ""),
            )
        self.assertEqual("partial", failed["status"])
        self.assertFalse(failed["agent_reach"]["available"])
        self.assertTrue(failed["agent_reach"]["binary_available"])
        self.assertEqual("ok", ready["status"])
        self.assertTrue(ready["agent_reach"]["available"])

    def test_youtube_level_budgets_and_quota_reserve_are_fixed(self) -> None:
        self.assertEqual(
            {
                "quick": {"comment_request_budget": 1000, "search_call_max": 10},
                "standard": {"comment_request_budget": 2500, "search_call_max": 20},
                "deep": {"comment_request_budget": 5000, "search_call_max": 30},
            },
            cvc.YOUTUBE_LEVEL_BUDGETS,
        )
        self.assertEqual("2500", cvc.YOUTUBE_CONFIG_DEFAULTS["YOUTUBE_API_QUOTA_RESERVE"])

    def test_youtube_daily_reserve_is_shared_across_tasks(self) -> None:
        ledger_path = self.root / "youtube_quota_ledger.sqlite3"
        moment = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
        with cvc.YoutubeGlobalQuotaLedger(ledger_path) as ledger:
            first = ledger.reserve(500, 3000, 2500, moment, "task-a", "batch-a", "comments.list")
            self.assertEqual(500, first["used_after"])
            with self.assertRaises(cvc.QuotaLimitError):
                ledger.reserve(1, 3000, 2500, moment, "task-b", "batch-b", "comments.list")
        self.assertEqual(0o600, stat.S_IMODE(ledger_path.stat().st_mode))

    def test_materialized_v2_coding_passes_report_validator(self) -> None:
        project = self.root / "market_project_20260805_000000"
        opportunity = project / "market_opportunity"
        research = project / "market_research"
        run_dir = opportunity / "consumer_voice_20260805_000000"
        run_dir.mkdir(parents=True)
        research.mkdir(parents=True)
        agent_health_dir = run_dir / "agent_reach"
        agent_health_dir.mkdir()
        (agent_health_dir / "doctor.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "active_backends": [
                        {"platform": "reddit", "active_backend": "public", "status": "ok"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        (agent_health_dir / "check_update.json").write_text(
            json.dumps({"status": "ok", "current_version": "1", "latest_version": "1"}),
            encoding="utf-8",
        )
        (project / "project_manifest.json").write_text("{}", encoding="utf-8")
        (research / "01_input_manifest.json").write_text(
            json.dumps({"marketplace": "US", "listing_language": "en"}), encoding="utf-8"
        )
        analysis = {
            "marketplace": "US",
            "listing_language": "en",
            "keyword": "seat cushion",
            "dimension_statuses": [{"dimension": "Feature", "valid": True}],
            "feature_distribution": [
                {
                    "dimension": "Feature",
                    "feature": "Option %d" % index,
                    "is_effective_feature": True,
                    "listing_share": 0.05 + index * 0.01,
                    "listing_count": 20 - index,
                    "sales_share": 0.1,
                    "supply_demand_index": 4 - index,
                }
                for index in range(3)
            ],
        }
        analysis_path = opportunity / "07_opportunity_analysis.json"
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        (opportunity / "市场机会深挖看板.html").write_text("<html></html>", encoding="utf-8")
        selection = cvc._select_project_segments(project, run_dir)
        dashboard_baseline = selection["project_snapshot"]["opportunity_dashboard"]["sha256"]
        self.assertEqual(
            cvc._sha256_file(opportunity / "市场机会深挖看板.html"),
            dashboard_baseline,
        )
        (run_dir / "selected_segments.json").write_text(json.dumps(selection), encoding="utf-8")
        category_queue = self.youtube_queue(
            source="last30days",
            backend="last30days",
            query_id="category_30d_primary",
            query_text="seat cushion reviews",
            video_id=None,
        )
        segment_queue = dict(
            category_queue,
            batch_id="segment-batch",
            scope="segment_1_90d",
            query_id="segment_1_90d_primary",
            query_text="seat cushion option 1 reviews",
        )
        store = cvc.CollectorStore(run_dir / "collector.sqlite3")
        store.create_task(
            "test",
            "seat cushion",
            "quick",
            END_AT,
            [category_queue, segment_queue],
            task_id="task-1",
            project_dir=project,
            run_dir=run_dir,
        )
        batches = {
            row["scope"]: store.batch_payload(row)
            for row in store.list_batches("task-1")
        }
        batch = batches["category_30d"]
        record_id, _, _ = store.insert_comment(
            "task-1",
            batch,
            {
                "source": "youtube",
                "content_id": "comment-1",
                "thread_id": "video-1",
                "video_id": "video-1",
                "author_label": "viewer",
                "text": "I like the support.",
                "published_at": "2026-08-01T00:00:00Z",
                "url": "https://www.youtube.com/watch?v=video-1&lc=comment-1",
            },
        )
        cross_window = {
            "source": "youtube",
            "content_id": "comment-cross-window",
            "thread_id": "video-2",
            "video_id": "video-2",
            "author_label": "viewer-two",
            "text": "This belongs only to the 90 day segment window.",
            "published_at": "2026-06-20T00:00:00Z",
            "url": "https://www.youtube.com/watch?v=video-2&lc=comment-cross-window",
        }
        cross_record_id, _, category_valid = store.insert_comment(
            "task-1", batches["category_30d"], cross_window
        )
        repeated_id, _, segment_valid = store.insert_comment(
            "task-1", batches["segment_1_90d"], cross_window
        )
        self.assertEqual(cross_record_id, repeated_id)
        self.assertFalse(category_valid)
        self.assertTrue(segment_valid)
        invalid_record_id, _, invalid_valid = store.insert_comment(
            "task-1",
            batches["category_30d"],
            {
                "source": "reddit",
                "content_id": "missing-source-url",
                "author_label": "viewer-three",
                "text": "relevant voice without a traceable direct URL",
                "published_at": "2026-08-01T00:00:00Z",
            },
        )
        self.assertFalse(invalid_valid)
        store.update_batch(
            batch["batch_id"],
            status="completed",
            raw_candidate_count=3,
            new_valid_count=1,
            finished_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
        )
        store.update_batch(
            batches["segment_1_90d"]["batch_id"],
            status="completed",
            raw_candidate_count=1,
            new_valid_count=1,
            finished_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
        )
        store.update_task(
            "task-1",
            status="completed",
            stop_reason="queues_exhausted",
            updated_at="2026-08-04T00:00:00Z",
        )
        store.merge_coding(
            "task-1",
            [
                {
                    "record_id": record_id,
                    "coding": {
                        "eligible_for_quantitation": True,
                        "is_relevant": True,
                        "is_consumer": True,
                        "sentiment": "positive",
                        "use_scenes": ["daily use"],
                        "persona_tags": ["driver"],
                        "need_codes": ["support"],
                        "satisfaction_codes": ["support"],
                        "dissatisfaction_codes": [],
                        "innovation_signals": [],
                        "kano_evidence": [],
                        "evidence_confidence": "medium",
                        "coding_notes": None,
                        "summary_zh": "用户认可支撑性。",
                        "language": "en",
                        "segment_memberships": [
                            {
                                "segment_id": "segment_1_90d",
                                "is_member": True,
                                "evidence": "全品类发现但正文属于测试细分",
                                "confidence": "high",
                                "method": "explicit_text",
                            }
                        ],
                    },
                },
                {
                    "record_id": cross_record_id,
                    "coding": {
                        "eligible_for_quantitation": True,
                        "is_relevant": True,
                        "is_consumer": True,
                        "sentiment": "negative",
                        "use_scenes": ["long term use"],
                        "persona_tags": ["driver"],
                        "need_codes": ["support"],
                        "satisfaction_codes": [],
                        "dissatisfaction_codes": ["support"],
                        "innovation_signals": [],
                        "kano_evidence": [],
                        "evidence_confidence": "medium",
                        "coding_notes": None,
                        "summary_zh": "该留言只属于90天细分窗口。",
                        "language": "en",
                        "segment_memberships": [
                            {
                                "segment_id": "segment_1_90d",
                                "is_member": True,
                                "evidence": "正文属于测试细分",
                                "confidence": "high",
                                "method": "explicit_text",
                            }
                        ],
                    },
                },
                {
                    "record_id": invalid_record_id,
                    "coding": {
                        "eligible_for_quantitation": False,
                        "is_relevant": True,
                        "is_consumer": True,
                        "exclusion_reason": "missing_source_url",
                        "sentiment": "neutral",
                        "use_scenes": [],
                        "persona_tags": [],
                        "need_codes": [],
                        "satisfaction_codes": [],
                        "dissatisfaction_codes": [],
                        "innovation_signals": [],
                        "kano_evidence": [],
                        "evidence_confidence": "low",
                        "coding_notes": None,
                        "summary_zh": "缺少可追溯直链。",
                        "language": "en",
                        "segment_memberships": [],
                    },
                },
            ],
        )
        self.assertEqual(2, store.valid_count("task-1", scope="segment_1_90d"))
        result = cvc.materialize_social_voice_coding(store, "task-1")
        self.assertEqual("passed", result["validation"])
        coding_path = run_dir / "social_voice_coding.json"
        self.assertTrue(coding_path.is_file())
        coding = json.loads(coding_path.read_text(encoding="utf-8"))
        cross_voice = next(
            voice for voice in coding["voices"] if voice["content_id"] == "comment-cross-window"
        )
        self.assertEqual(["segment_1_90d"], cross_voice["collection_scopes"])
        self.assertEqual(["segment_1_90d_primary"], cross_voice["query_ids"])
        segment_funnel = next(
            item
            for item in coding["collection_funnel"]["per_scope"]
            if item["scope_id"] == "segment_1_90d"
        )
        self.assertEqual(2, segment_funnel["valid_voices"])
        self.assertTrue(
            all(
                segment_funnel[left] >= segment_funnel[right]
                for left, right in zip(cvc.FUNNEL_STAGE_FIELDS, cvc.FUNNEL_STAGE_FIELDS[1:])
            )
        )
        self.assertGreater(
            coding["collection_funnel"]["deduplicated_records"],
            coding["collection_funnel"]["valid_voices"],
        )
        self.assertEqual("ok", coding["agent_reach_health"]["doctor"]["status"])
        self.assertEqual("reddit", coding["agent_reach_health"]["doctor"]["active_backends"][0]["platform"])
        (opportunity / "市场机会深挖看板.html").write_text(
            "<html>mutated after plan</html>", encoding="utf-8"
        )
        with self.assertRaises(cvc.CollectorError) as caught:
            cvc._project_context(project, dashboard_baseline)
        self.assertIn("plan基线", str(caught.exception))
        store.close()

    def test_union_upper_alone_does_not_stop_before_all_route_uppers(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        batch = store.batch_payload(store.list_batches("task-1")[0])
        for index in range(1000):
            store.insert_comment(
                "task-1",
                batch,
                {
                    "source": "youtube",
                    "content_id": "union-%d" % index,
                    "video_id": "video-1",
                    "text": "category voice %d" % index,
                    "published_at": "2026-08-01T00:00:00Z",
                },
            )
        receipt = cvc.CollectorService(store).run("task-1")
        self.assertEqual("queues_exhausted", receipt["stop_reason"])
        self.assertEqual(1000, receipt["collection_funnel"]["valid_voices"])
        self.assertEqual(0, receipt["target_attainment"]["per_scope_valid"]["segment_1_90d"])
        store.close()

    def test_receipt_uses_fixed_funnel_field_names(self) -> None:
        store, _ = self.make_store([self.youtube_queue()])
        receipt = cvc.build_receipt(store, "task-1")
        expected = {
            "fetched_records",
            "unique_records",
            "within_window_records",
            "relevant_records",
            "consumer_records",
            "deduplicated_records",
            "valid_voices",
            "excluded_records",
            "per_scope",
            "per_platform",
            "exclusion_reasons",
        }
        self.assertEqual(expected, set(receipt["collection_funnel"]))
        self.assertEqual("category_30d", receipt["collection_funnel"]["per_scope"][0]["scope_id"])
        self.assertIn("estimated_direct_cost_usd", receipt["quota_and_cost"])
        self.assertIsNone(receipt["quota_and_cost"]["estimated_direct_cost_usd"])
        self.assertTrue(receipt["quota_and_cost"]["unknown_is_not_zero"])
        self.assertEqual(1, receipt["youtube_execution"]["actual_workers"])
        store.close()

    def test_receipt_separates_actual_estimated_and_unknown_costs(self) -> None:
        store, _ = self.make_store([])
        store.record_quota(
            "task-1",
            None,
            "paid-provider",
            "job.run",
            1,
            actual_cost_usd=0.12,
            cost_status="provider_confirmed_actual",
            currency="USD",
            pricing_basis="provider invoice line item",
        )
        store.record_quota(
            "task-1",
            None,
            "priced-provider",
            "job.run",
            2,
            estimated_cost_usd=0.34,
            cost_status="estimated_from_price_snapshot",
            currency="USD",
            price_snapshot_at="2026-08-05T00:00:00Z",
            pricing_basis="2 requests x USD 0.17",
        )
        store.record_quota(
            "task-1",
            None,
            "last30days",
            "research.run",
            1,
            cost_status="unknown",
            pricing_basis="provider charges unavailable",
        )
        receipt = cvc.build_receipt(store, "task-1")
        costs = receipt["quota_and_cost"]
        self.assertEqual(0.12, costs["provider_confirmed_actual_cost_usd"])
        self.assertEqual(0.34, costs["estimated_direct_cost_usd"])
        self.assertEqual(
            ["estimated_from_price_snapshot", "provider_confirmed_actual", "unknown"],
            costs["cost_statuses"],
        )
        unknown = next(item for item in costs["ledger"] if item["cost_status"] == "unknown")
        self.assertIsNone(unknown["amount"])
        store.close()

    def test_cli_writes_contract_artifacts_updates_on_resume_and_never_persists_key(self) -> None:
        parser = cvc.build_parser()
        run_dir = self.root / "contract-run"
        config = self.root / "youtube-secret.env"
        # Keep the test value realistic at runtime without committing a
        # secret-shaped literal that could trigger repository secret scanning.
        secret = "AI" + "zaTHIS_IS_A_PRIVATE_KEY_123456789"
        values = dict(cvc.YOUTUBE_CONFIG_DEFAULTS)
        values["YOUTUBE_DATA_API_KEY"] = secret
        config.write_text(
            "\n".join("%s=%s" % item for item in values.items()) + "\n",
            encoding="utf-8",
        )
        os.chmod(config, 0o600)

        planned = cvc.execute(
            parser.parse_args(
                [
                    "plan",
                    "--run-dir",
                    str(run_dir),
                    "--task-id",
                    "contract-task",
                    "--research-level",
                    "quick",
                    "--youtube-config",
                    str(config),
                ]
            )
        )
        run_dir = run_dir.resolve()
        plan_path = run_dir / "research_plan.json"
        state_path = run_dir / "collection_state.json"
        source_path = run_dir / "source_status.json"
        self.assertEqual(str(plan_path), planned["research_plan_path"])
        self.assertTrue(plan_path.is_file())
        self.assertFalse(state_path.exists())
        self.assertFalse(source_path.exists())

        first = cvc.execute(
            parser.parse_args(
                [
                    "run",
                    "--run-dir",
                    str(run_dir),
                    "--task-id",
                    "contract-task",
                    "--youtube-config",
                    str(config),
                ]
            )
        )
        first_state_text = state_path.read_text(encoding="utf-8")
        first_state = json.loads(first_state_text)
        self.assertEqual("quick", first_state["research_level"])
        self.assertEqual(1, first_state["run_count"])
        self.assertEqual("collection_completed", first_state["status"])
        self.assertEqual("queues_exhausted", first_state["stop_reason"])
        self.assertEqual(
            {
                "research_plan": str(plan_path),
                "collection_state": str(state_path),
                "source_status": str(source_path),
            },
            first["contract_artifacts"],
        )

        resumed = cvc.execute(
            parser.parse_args(
                [
                    "resume",
                    "--run-dir",
                    str(run_dir),
                    "--task-id",
                    "contract-task",
                    "--research-level",
                    "standard",
                    "--youtube-config",
                    str(config),
                ]
            )
        )
        updated_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        updated_state_text = state_path.read_text(encoding="utf-8")
        updated_state = json.loads(updated_state_text)
        updated_source = json.loads(source_path.read_text(encoding="utf-8"))
        self.assertEqual("standard", updated_plan["research_plan"]["research_level"])
        self.assertEqual(3000, updated_plan["research_plan"]["sample_target"]["total_valid_max"])
        self.assertEqual("standard", updated_state["research_level"])
        self.assertEqual(2, updated_state["run_count"])
        self.assertNotEqual(first_state_text, updated_state_text)
        self.assertEqual("collection_completed", updated_source["status"])
        self.assertEqual(0, updated_source["source_run_summary"]["total"])
        self.assertEqual(resumed["status"], updated_state["status"])

        for artifact in (plan_path, state_path, source_path):
            self.assertEqual(0o600, stat.S_IMODE(artifact.stat().st_mode))
            self.assertNotIn(secret, artifact.read_text(encoding="utf-8"))
            self.assertEqual({}, {item.name: True for item in run_dir.glob(".%s.*" % artifact.name)})

    def test_cli_exposes_all_required_commands(self) -> None:
        parser = cvc.build_parser()
        subparser_action = next(
            action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
        )
        self.assertEqual(
            {
                "plan",
                "run",
                "resume",
                "prepare-coding",
                "merge-coding",
                "receipt",
                "doctor",
                "youtube-api-setup",
                "youtube-api-check",
            },
            set(subparser_action.choices),
        )

    def test_task_registry_supports_task_id_only_and_is_0600(self) -> None:
        run_dir = self.root / "run"
        run_dir.mkdir()
        cvc.register_task("task-only", self.db, run_dir)
        registry = Path(os.environ["LCADMO_TASK_REGISTRY"])
        self.assertEqual(0o600, stat.S_IMODE(registry.stat().st_mode))
        db_path, resolved_run = cvc.resolve_registered_task("task-only")
        self.assertEqual(self.db.resolve(), db_path)
        self.assertEqual(run_dir.resolve(), resolved_run)


if __name__ == "__main__":
    unittest.main()
