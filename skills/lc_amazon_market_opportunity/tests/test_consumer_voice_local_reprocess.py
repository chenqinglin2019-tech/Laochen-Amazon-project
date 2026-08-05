from __future__ import annotations

import importlib.util
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "consumer_voice_local_reprocess.py"
SPEC = importlib.util.spec_from_file_location("consumer_voice_local_reprocess", MODULE_PATH)
assert SPEC and SPEC.loader
cvlr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cvlr)


class LocalReprocessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "collector.sqlite3"
        self.output = self.root / "out"
        self.selection = self.root / "selected_segments.json"
        self.dashboard = self.root / "市场机会深挖看板.html"
        self._create_database()
        self._write_selection()
        self.dashboard.write_text("<!doctype html><title>机会看板</title>", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create_database(self) -> None:
        connection = sqlite3.connect(self.db)
        connection.executescript(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY, topic TEXT, project_dir TEXT, run_dir TEXT,
                created_at TEXT
            );
            CREATE TABLE batches (
                batch_id TEXT PRIMARY KEY, task_id TEXT, backend TEXT, source TEXT,
                scope TEXT, query_id TEXT, query_text TEXT
            );
            CREATE TABLE comments (
                record_id TEXT PRIMARY KEY, task_id TEXT, source TEXT, content_id TEXT,
                hard_key TEXT, parent_content_id TEXT, thread_id TEXT, video_id TEXT,
                author_id TEXT, author_label TEXT, author_hash TEXT, text TEXT,
                published_at TEXT, canonical_url TEXT, raw_json TEXT,
                first_seen_at TEXT
            );
            CREATE TABLE comment_discoveries (
                discovery_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
                record_id TEXT, batch_id TEXT, scope TEXT, query_id TEXT, source TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?)",
            ("task-1", "car phone holder", str(self.root), str(self.root), "2026-08-01T00:00:00Z"),
        )
        connection.executemany(
            "INSERT INTO batches VALUES(?,?,?,?,?,?,?)",
            [
                ("b1", "task-1", "youtube-data-api", "youtube", "category_30d", "q1", "car phone holder"),
                ("b2", "task-1", "external", "reddit", "segment_2_90d", "q2", "truck phone mount"),
                ("b3", "task-1", "youtube-data-api", "youtube", "category_30d", "q3", "music video"),
            ],
        )
        records = [
            ("root", "youtube", "video-1", "hk-root", None, "video-1", "video-1", "creator", "Car phone holder installation test", "2010-01-01T00:00:00Z"),
            ("same-a", "youtube", "a", "hk-a", "root", "video-1", "video-1", "a", "I need a stronger car phone holder clamp that will not shake", "2009-01-01T00:00:00Z"),
            ("same-b", "youtube", "b", "hk-b", "root", "video-1", "video-1", "b", "I need a stronger car phone holder clamp that will not shake", "2009-01-01T00:00:00Z"),
            ("missing-date", "youtube", "c", "hk-c", "root", "video-1", "video-1", "c", "It works perfectly", None),
            ("generic-praise", "youtube", "d", "hk-d", "root", "video-1", "video-1", "d", "Awesome video", None),
            ("ad", "youtube", "e", "hk-e", "root", "video-1", "video-1", "seller", "Shop now: buy our car phone holder https://a.example using promo code SAVE", "2026-01-01T00:00:00Z"),
            ("emoji", "youtube", "f", "hk-f", "root", "video-1", "video-1", "f", "🔥🔥🔥", "2026-01-01T00:00:00Z"),
            ("unrelated", "youtube", "g", "hk-g", None, "music-1", "music-1", "g", "I love this song", "2026-01-01T00:00:00Z"),
            ("truck", "reddit", "r1", "hk-r1", None, "thread-r", None, "r", "I need a heavy duty truck phone mount for rough roads", "2008-01-01T00:00:00Z"),
            ("seller-link", "youtube", "sl", "hk-sl", "root", "video-1", "video-1", "seller-link", "Here is the link: https://shop.example buy this car phone holder", "2026-01-01T00:00:00Z"),
            ("user-link-question", "youtube", "ul", "hk-ul", "root", "video-1", "video-1", "buyer", "Where can I buy this car phone holder? Please share the link", "2026-01-01T00:00:00Z"),
            ("creator-cta", "youtube", "cta", "hk-cta", "root", "video-1", "video-1", "creator-cta", "Today I'll show this car phone holder, you gotta try it and order now", "2026-01-01T00:00:00Z"),
            ("media-comment", "youtube", "media", "hk-media", "root", "video-1", "video-1", "media", "I love this video and the creator's filming", "2026-01-01T00:00:00Z"),
        ]
        for record_id, source, content_id, hard_key, parent_id, thread_id, video_id, author, text, published_at in records:
            connection.execute(
                """INSERT INTO comments(record_id,task_id,source,content_id,hard_key,
                parent_content_id,thread_id,video_id,author_id,author_label,author_hash,
                text,published_at,canonical_url,raw_json,first_seen_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id,
                    "task-1",
                    source,
                    content_id,
                    hard_key,
                    parent_id,
                    thread_id,
                    video_id,
                    author,
                    author,
                    "hash-" + author,
                    text,
                    published_at,
                    "https://example.com/" + record_id,
                    "{}",
                    "2026-08-01T00:00:00Z",
                ),
            )
            batch = "b2" if source == "reddit" else ("b3" if record_id == "unrelated" else "b1")
            scope = "segment_2_90d" if source == "reddit" else "category_30d"
            query_id = "q2" if source == "reddit" else ("q3" if record_id == "unrelated" else "q1")
            connection.execute(
                "INSERT INTO comment_discoveries(task_id,record_id,batch_id,scope,query_id,source) VALUES(?,?,?,?,?,?)",
                ("task-1", record_id, batch, scope, query_id, source),
            )
        connection.commit()
        connection.close()

    def _write_selection(self) -> None:
        self.selection.write_text(
            json.dumps(
                {
                    "source": {"marketplace": "US", "keyword": "car phone holder"},
                    "top3_selection": {"source_field": "feature_distribution"},
                    "selected_segments": [
                        {"segment_id": "segment_1_90d", "rank": 1, "dimension": "机制", "feature": "机械夹持"},
                        {"segment_id": "segment_2_90d", "rank": 2, "dimension": "车型", "feature": "卡车/重型车适用"},
                        {"segment_id": "segment_3_90d", "rank": 3, "dimension": "车型", "feature": "Tesla专用"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _walk_keys(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield str(key)
                yield from self._walk_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_keys(child)

    def _walk_strings(self, value):
        if isinstance(value, dict):
            for child in value.values():
                yield from self._walk_strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_strings(child)
        elif isinstance(value, str):
            yield value

    def _load_outputs(self):
        coding = json.loads((self.output / cvlr.CODING_FILENAME).read_text(encoding="utf-8"))
        analysis = json.loads((self.output / cvlr.ANALYSIS_FILENAME).read_text(encoding="utf-8"))
        return coding, analysis

    def test_all_history_keeps_same_text_different_id_and_missing_or_old_dates(self) -> None:
        receipt = cvlr.reprocess(
            self.db,
            self.output,
            selection_file=self.selection,
            dashboard=self.dashboard,
        )
        self.assertTrue(receipt["opportunity_dashboard_unchanged"])
        self.assertEqual(13, receipt["funnel"]["hard_unique_records"])
        coding = json.loads((self.output / cvlr.CODING_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(
            cvlr.file_sha256(self.dashboard),
            coding["metadata"]["opportunity_dashboard"]["sha256"],
        )
        voices = {item["voice_id"]: item for item in coding["voices"]}
        self.assertIn("same-a", voices)
        self.assertIn("same-b", voices)
        self.assertIn("missing-date", voices)
        self.assertIn("truck", voices)
        self.assertEqual(None, voices["missing-date"]["published_at"])
        self.assertEqual("本条显式产品锚点", voices["same-a"]["product_context_source"])
        self.assertEqual("已确认根内容", voices["missing-date"]["product_context_source"])
        self.assertIn("segment_2_all_history", voices["truck"]["segment_memberships"])
        self.assertNotIn("generic-praise", voices)
        self.assertNotIn("ad", voices)
        self.assertNotIn("emoji", voices)
        self.assertNotIn("unrelated", voices)
        self.assertNotIn("seller-link", voices)
        self.assertNotIn("creator-cta", voices)
        self.assertNotIn("media-comment", voices)
        self.assertIn("user-link-question", voices)

    def test_outputs_have_no_grading_field_and_use_all_history_scopes(self) -> None:
        cvlr.reprocess(self.db, self.output, selection_file=self.selection)
        for filename in (cvlr.CODING_FILENAME, cvlr.ANALYSIS_FILENAME):
            document = json.loads((self.output / filename).read_text(encoding="utf-8"))
            self.assertFalse(any("confidence" in key.casefold() for key in self._walk_keys(document)))
            self.assertFalse(any("window" in key.casefold() for key in self._walk_keys(document)))
            self.assertFalse(
                any(
                    "evidence" in key.casefold()
                    and ("count" in key.casefold() or "total" in key.casefold())
                    for key in self._walk_keys(document)
                )
            )
            self.assertFalse(
                any(
                    old_scope in text
                    for text in self._walk_strings(document)
                    for old_scope in ("category_30d", "segment_1_90d", "segment_2_90d", "segment_3_90d")
                )
            )
            self.assertEqual(cvlr.SCHEMA_VERSION, document["schema_version"])
            self.assertFalse(document["metadata"]["date_filter_applied"])
        analysis = json.loads((self.output / cvlr.ANALYSIS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(6, len(analysis["semantic_categories"]))
        self.assertIn(
            "installation_compatibility_scenario",
            [item["code"] for item in analysis["semantic_categories"]],
        )
        self.assertTrue(
            {item["kano_type"] for item in analysis["kano"]}.issubset(
                {"必备型", "期望型", "魅力型", "无差异型", "反向型"}
            )
        )
        self.assertEqual(
            ["segment_1_all_history", "segment_2_all_history", "segment_3_all_history"],
            [item["segment_id"] for item in analysis["top_segments"]],
        )
        self.assertTrue((self.output / cvlr.SOURCE_SNAPSHOT_FILENAME).is_file())
        self.assertIn("source_snapshot", json.loads((self.output / cvlr.RECEIPT_FILENAME).read_text(encoding="utf-8")))
        for section in (
            "needs",
            "satisfactions",
            "dissatisfactions",
            "scenarios",
            "diy_workarounds",
            "innovations",
        ):
            self.assertFalse(
                any(
                    str(item["code"]).startswith("general_")
                    for item in analysis["category_summary"][section]
                )
            )

    def test_unknown_title_context_requires_five_percent_explicit_product_share(self) -> None:
        connection = sqlite3.connect(self.db)
        rows = []
        for index in range(2):
            rows.append(
                (
                    f"threshold-anchor-{index}",
                    f"anchor-{index}",
                    f"hk-anchor-{index}",
                    f"author-anchor-{index}",
                    "I need a stable car phone holder",
                )
            )
        for index in range(39):
            rows.append(
                (
                    f"threshold-generic-{index}",
                    f"generic-{index}",
                    f"hk-generic-{index}",
                    f"author-generic-{index}",
                    "It works perfectly",
                )
            )
        for record_id, content_id, hard_key, author, text in rows:
            connection.execute(
                """INSERT INTO comments(record_id,task_id,source,content_id,hard_key,
                parent_content_id,thread_id,video_id,author_id,author_label,author_hash,
                text,published_at,canonical_url,raw_json,first_seen_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id,
                    "task-1",
                    "youtube",
                    content_id,
                    hard_key,
                    None,
                    "threshold-video",
                    "threshold-video",
                    author,
                    author,
                    "hash-" + author,
                    text,
                    "2020-01-01T00:00:00Z",
                    "https://example.com/" + record_id,
                    "{}",
                    "2026-08-01T00:00:00Z",
                ),
            )
            connection.execute(
                "INSERT INTO comment_discoveries(task_id,record_id,batch_id,scope,query_id,source) VALUES(?,?,?,?,?,?)",
                ("task-1", record_id, "b1", "category_30d", "q1", "youtube"),
            )
        connection.commit()
        connection.close()
        cvlr.reprocess(self.db, self.output, selection_file=self.selection)
        coding = json.loads((self.output / cvlr.CODING_FILENAME).read_text(encoding="utf-8"))
        voice_ids = {item["voice_id"] for item in coding["voices"]}
        self.assertIn("threshold-anchor-0", voice_ids)
        self.assertIn("threshold-anchor-1", voice_ids)
        self.assertNotIn("threshold-generic-0", voice_ids)

    def test_implicit_context_requires_a_product_or_experience_anchor(self) -> None:
        self.assertFalse(
            cvlr.is_recognizable_implicit_product_expression(
                "It seems like everything you own is cracked, even your windshield."
            )
        )
        self.assertTrue(
            cvlr.is_recognizable_implicit_product_expression(
                "It fell off twice and will not hold my phone."
            )
        )
        self.assertTrue(
            cvlr.is_platform_parent_content(
                {
                    "source": "youtube",
                    "content_id": "video-1",
                    "video_id": "video-1",
                    "raw_json": '{"raw_origin":"last30days_parent"}',
                }
            )
        )

    def test_prior_analysis_reuses_product_detail_after_deep_cleaning(self) -> None:
        prior = self.root / "prior.json"
        prior.write_text(
            json.dumps(
                {
                    "product_concepts": [
                        {
                            "concept_id": "concept_1",
                            "name": "Prior detailed concept",
                            "segment_id": "segment_1_90d",
                            "confidence": "low",
                            "features": ["adjustable jaws"],
                            "technical_solution": "aluminum rail and cam lock",
                            "materials": ["6061 aluminum", "silicone"],
                            "cmf": {"colors": ["black"]},
                            "design_thinking": {
                                "empathize": {
                                    "status": "completed",
                                    "evidence_voice_ids": ["secret-id"],
                                }
                            },
                            "moscow": {
                                "must": [
                                    {
                                        "feature": "stable hold",
                                        "target_segment_ids": ["segment_1_90d"],
                                        "evidence_origins": [
                                            {"voice_ids": ["secret-id"], "segment_id": "segment_1_90d"}
                                        ],
                                    }
                                ]
                            },
                            "kano_mapping": [
                                {"need_code": "secure_hold", "classification": "evidence_insufficient"},
                                {"need_code": "unknown_need", "classification": "evidence_insufficient"},
                            ],
                            "image_prompt": {"prompt_text": "complete prompt"},
                            "image_artifact": {"status": "ok", "path": "/tmp/concept.png"},
                            "evidence_counts": {"x": 3},
                        }
                    ],
                    "validation": {"status": "planned", "confidence": "low"},
                    "future_validation_checklist": [
                        {"validation_id": "engineering", "segment_id": "segment_1_90d", "status": "planned"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cvlr.reprocess(
            self.db,
            self.output,
            selection_file=self.selection,
            prior_analysis=prior,
        )
        analysis = json.loads((self.output / cvlr.ANALYSIS_FILENAME).read_text(encoding="utf-8"))
        concept = analysis["product_concepts"][0]
        self.assertEqual("Prior detailed concept", concept["name"])
        self.assertEqual("segment_1_all_history", concept["segment_id"])
        self.assertEqual("aluminum rail and cam lock", concept["technical_solution"])
        self.assertEqual("complete prompt", concept["image_prompt"]["prompt_text"])
        self.assertEqual("/tmp/concept.png", concept["image_artifact"]["path"])
        self.assertGreater(concept["supporting_voice_count"], 0)
        self.assertEqual(1, len(concept["kano_mapping"]))
        self.assertIn(
            concept["kano_mapping"][0]["classification"],
            {"必备型", "期望型", "魅力型", "无差异型", "反向型"},
        )
        self.assertEqual(
            "segment_1_all_history",
            analysis["future_validation_checklist"][0]["segment_id"],
        )
        self.assertFalse(any("confidence" in key.casefold() for key in self._walk_keys(analysis)))
        self.assertFalse(any(key in {"voice_ids", "evidence_voice_ids", "evidence_ids", "evidence_counts"} for key in self._walk_keys(analysis)))

    def test_strict_v3_reconciliation_rejects_tampered_documents(self) -> None:
        cvlr.reprocess(self.db, self.output, selection_file=self.selection)
        coding, analysis = self._load_outputs()
        cvlr.validate_v3_documents(coding, analysis)

        mutations = []

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_coding["semantic_taxonomy"][0]["code"] = "not_one_of_six"
        mutations.append((bad_coding, bad_analysis))

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_coding["funnel"]["examined_records"] -= 1
        bad_analysis["funnel"]["examined_records"] -= 1
        mutations.append((bad_coding, bad_analysis))

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_coding["excluded_records"][0]["hard_identity"] = bad_coding["voices"][0]["hard_identity"]
        mutations.append((bad_coding, bad_analysis))

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_analysis["semantic_categories"][0]["count"] += 1
        mutations.append((bad_coding, bad_analysis))

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_analysis["semantic_categories"][0]["share"] = 0.123456
        mutations.append((bad_coding, bad_analysis))

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_analysis["kano"][0]["kano_type"] = "M"
        mutations.append((bad_coding, bad_analysis))

        for forbidden_key in (
            "confidence",
            "research_window",
            "source_status",
            "evidence_voice_count",
        ):
            bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
            bad_analysis[forbidden_key] = "forbidden"
            mutations.append((bad_coding, bad_analysis))

        bad_coding, bad_analysis = copy.deepcopy(coding), copy.deepcopy(analysis)
        bad_coding["voices"][0]["collection_scopes"].append("category_30d")
        mutations.append((bad_coding, bad_analysis))

        for bad_coding, bad_analysis in mutations:
            with self.assertRaises(cvlr.LocalReprocessError):
                cvlr.validate_v3_documents(bad_coding, bad_analysis)

    def test_non_car_project_requires_taxonomy_profile(self) -> None:
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE tasks SET topic=? WHERE task_id=?", ("coffee grinder", "task-1"))
        connection.commit()
        connection.close()
        self.selection.write_text(
            json.dumps(
                {
                    "source": {"marketplace": "US", "keyword": "coffee grinder"},
                    "top3_selection": {},
                    "selected_segments": [],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(cvlr.LocalReprocessError, "taxonomy-profile"):
            cvlr.reprocess(self.db, self.output, selection_file=self.selection)

    def test_custom_taxonomy_profile_drives_non_car_project(self) -> None:
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE tasks SET topic=? WHERE task_id=?", ("coffee grinder", "task-1"))
        connection.execute(
            """INSERT INTO comments(record_id,task_id,source,content_id,hard_key,
            parent_content_id,thread_id,video_id,author_id,author_label,author_hash,
            text,published_at,canonical_url,raw_json,first_seen_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "grinder-voice",
                "task-1",
                "reddit",
                "grinder-comment",
                "hk-grinder",
                None,
                "grinder-thread",
                None,
                "grinder-buyer",
                "grinder-buyer",
                "hash-grinder-buyer",
                "Coffee grinder dial repeatability matters for espresso",
                None,
                "https://example.com/grinder-voice",
                "{}",
                "2026-08-01T00:00:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO comment_discoveries(task_id,record_id,batch_id,scope,query_id,source) VALUES(?,?,?,?,?,?)",
            ("task-1", "grinder-voice", "b2", "segment_2_90d", "q2", "reddit"),
        )
        connection.commit()
        connection.close()
        self.selection.write_text(
            json.dumps(
                {
                    "source": {"marketplace": "US", "keyword": "coffee grinder"},
                    "top3_selection": {},
                    "selected_segments": [],
                }
            ),
            encoding="utf-8",
        )
        profile = self.root / "coffee-grinder-taxonomy.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "profile_id": "coffee_grinder_us",
                    "product_label": "咖啡磨豆机",
                    "product_terms": ["coffee grinder"],
                    "product_patterns": [],
                    "implicit_product_terms": ["grinder", "burr"],
                    "implicit_product_patterns": [],
                    "implicit_experience_patterns": [],
                    "semantic_extensions": {
                        "feature_reverse_innovation": {
                            "terms": ["dial repeatability"],
                            "patterns": [],
                        }
                    },
                    "topics": [
                        {
                            "code": "dial_repeatability",
                            "label": "刻度复位一致性",
                            "terms": ["dial repeatability"],
                            "patterns": [],
                        }
                    ],
                    "segments": [
                        {
                            "segment_id": "segment_espresso_all_history",
                            "rank": 1,
                            "dimension": "冲煮方式",
                            "feature": "意式浓缩",
                            "terms": ["espresso"],
                            "patterns": [],
                        }
                    ],
                    "kano_mapping": {"dial_repeatability": "期望型"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cvlr.reprocess(
            self.db,
            self.output,
            selection_file=self.selection,
            taxonomy_profile=profile,
        )
        coding, analysis = self._load_outputs()
        voice = next(item for item in coding["voices"] if item["voice_id"] == "grinder-voice")
        self.assertIn("feature_reverse_innovation", voice["semantic_codes"])
        self.assertIn("dial_repeatability", voice["topic_codes"])
        self.assertIn("segment_espresso_all_history", voice["segment_memberships"])
        self.assertEqual("coffee_grinder_us", coding["metadata"]["taxonomy_profile"]["profile_id"])
        self.assertEqual("file", coding["metadata"]["taxonomy_profile"]["source"])
        self.assertEqual("期望型", analysis["kano"][0]["kano_type"])
        self.assertEqual("segment_espresso_all_history", analysis["top_segments"][0]["segment_id"])
        cvlr.validate_v3_documents(coding, analysis)

    def test_taxonomy_profile_schema_files_are_valid_json(self) -> None:
        for name in (
            "social_voice_all_history_coding.schema.json",
            "social_voice_all_history_analysis.schema.json",
            "consumer_voice_taxonomy.schema.json",
        ):
            document = json.loads((SKILL_ROOT / "references" / name).read_text(encoding="utf-8"))
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", document["$schema"])

    def test_dry_run_writes_nothing_and_keeps_source_database_unchanged(self) -> None:
        before_hash = cvlr.file_sha256(self.db)
        before_stat = self.db.stat()
        receipt = cvlr.reprocess(
            self.db,
            self.output,
            selection_file=self.selection,
            dry_run=True,
        )
        after_stat = self.db.stat()
        self.assertFalse(self.output.exists())
        self.assertFalse(receipt["outputs_written"])
        self.assertTrue(receipt["source_db_unchanged"])
        self.assertEqual(before_hash, cvlr.file_sha256(self.db))
        self.assertEqual(before_stat.st_mtime_ns, after_stat.st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
