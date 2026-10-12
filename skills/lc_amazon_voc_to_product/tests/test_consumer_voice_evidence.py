from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

import test_consumer_voice_local_reprocess as fixtures

cvlr = fixtures.cvlr
ev = cvlr.evidence


class EvidencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LocalReprocessTestCase()
        self.fixture.setUp()
        self.__dict__.update({k: getattr(self.fixture, k) for k in ("root", "db", "output", "selection", "dashboard")})

    def tearDown(self):
        self.fixture.tearDown()

    def run_analysis(self, **kwargs):
        return cvlr.reprocess(self.db, self.output, selection_file=self.selection, dashboard=self.dashboard, **kwargs)

    def outputs(self):
        return self.fixture._load_outputs()

    def decision(self, row, *, include=True):
        result = {key: row[key] for key in ("record_id", "hard_identity", "cache_key", "text_sha256", "context_sha256", "taxonomy_sha256")}
        result.update(reviewed_by="test-agent", reason="测试语料逐条复核", decision="include" if include else "exclude")
        if include:
            result.update(
                semantic_codes=["feature_reverse_innovation"],
                segment_memberships=["segment_1_all_history"],
                product_context={"basis": "self", "quote": row["text"]},
                needs=[{"code": "open_new_need", "label": "开放发现的结构需求", "quote": row["text"], "stance": "support", "applicability": "unknown", "alternative_explanations": ["也可能与用户现有配件有关"]}],
                scenarios=[{"code": "daily_use", "label": "日常使用", "quote": row["text"]}],
            )
        return result

    def test_unmatched_voice_is_pending_then_agent_import_and_cache_resolve_it(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE comments SET text=? WHERE record_id='same-a'", ("Car phone holder tessellation during the commute",))
        con.commit(); con.close()
        self.run_analysis()
        coding, analysis = self.outputs()
        self.assertIn("same-a", {r["record_id"] for r in coding["pending_records"]})
        self.assertNotIn("same-a", {r["record_id"] for r in coding["excluded_records"]})
        self.assertEqual("complete", analysis["processing_status"])
        self.assertEqual("partial", analysis["evidence_readiness"]["status"])
        queue = [json.loads(x) for x in (self.output / "agent_coding_queue.jsonl").read_text().splitlines()]
        self.assertEqual(coding["funnel"]["hard_unique_records"], len(queue))
        imported = self.root / "reviewed.jsonl"
        item = self.decision(next(r for r in queue if r["record_id"] == "same-a"))
        imported.write_text(json.dumps(item) + "\n")
        cache = self.root / "cache.json"
        self.run_analysis(agent_coding=[imported], coding_cache=cache)
        coding, analysis = self.outputs()
        voice = next(v for v in coding["voices"] if v["voice_id"] == "same-a")
        self.assertEqual("agent_reviewed", voice["coding_method"])
        self.assertEqual(["open_new_need"], voice["topic_codes"])
        self.assertEqual("unknown", voice["needs"][0]["applicability"])
        self.assertEqual([], analysis["product_concepts"])
        self.assertIn("same-a", analysis["evidence_readiness"]["needs"][0]["support_refs"])
        self.assertFalse(cache.exists())
        cache.write_bytes((self.output / "coding_cache.json").read_bytes())
        self.run_analysis(coding_cache=cache)
        self.assertEqual(1, self.outputs()[1]["coding_review"]["agent_reviewed"])
        self.assertEqual(12, len((self.output / "agent_coding_queue.jsonl").read_text().splitlines()))
        con = sqlite3.connect(self.db)
        con.execute("UPDATE comments SET text=text || ' changed' WHERE record_id='same-a'")
        con.commit(); con.close()
        self.run_analysis(coding_cache=cache)
        self.assertEqual(0, self.outputs()[1]["coding_review"]["agent_reviewed"])
        with self.assertRaises(cvlr.LocalReprocessError):
            self.run_analysis(agent_coding=[imported], coding_cache=cache)

    def test_false_quote_and_unknown_segment_are_rejected(self):
        self.run_analysis()
        row = next(json.loads(x) for x in (self.output / "agent_coding_queue.jsonl").read_text().splitlines() if json.loads(x)["record_id"] == "same-a")
        for mutation in ("quote", "segment"):
            item = self.decision(row)
            if mutation == "quote": item["needs"][0]["quote"] = "Invented consumer words"
            else: item["segment_memberships"] = ["segment_unknown_all_history"]
            imported = self.root / "bad.json"
            imported.write_text(json.dumps({"entries": [item]}))
            with self.assertRaises(ev.EvidenceError): self.run_analysis(agent_coding=[imported])

    def test_unknown_author_source_kind_and_full_text_retention(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE comments SET author_id=NULL,author_label=NULL,author_hash=NULL WHERE record_id IN ('same-a','same-b')")
        con.execute("UPDATE comments SET author_id='[deleted]',author_label='[deleted]',author_hash='hash-of-deleted' WHERE record_id='truck'")
        con.execute("UPDATE comments SET raw_json=? WHERE record_id='same-a'", (json.dumps({"original": {"source_kind": "after_sales"}}),))
        long_text = "I need a car phone holder. " + "Observed joint behavior. " * 120
        con.execute("UPDATE comments SET text=? WHERE record_id='same-b'", (long_text,))
        con.commit(); con.close()
        self.run_analysis()
        coding, analysis = self.outputs()
        self.assertEqual(3, analysis["sample_structure"]["unknown_author_records"])
        voice = next(v for v in coding["voices"] if v["voice_id"] == "same-a")
        self.assertIsNone(voice["author_key"])
        self.assertEqual("after_sales", voice["source_kind"])
        self.assertEqual(long_text.strip(), next(v for v in coding["voices"] if v["voice_id"] == "same-b")["excerpt"])
        self.assertEqual(1, next(x for x in analysis["source_breakdown"] if x["source_kind"] == "after_sales")["count"])

    def test_source_breakdown_merges_alias_codes_without_losing_distinct_voices(self):
        voices = [
            {
                "voice_id": "voice-a", "source_kind": "social", "platform": "reddit",
                "author_key": "author-a", "thread_key": "thread-a",
                "topic_codes": ["surface_depth", "multi_device_capacity"],
                "topic_labels": ["桌面深度与设备容纳", "桌面深度与设备容纳"],
            },
            {
                "voice_id": "voice-b", "source_kind": "social", "platform": "reddit",
                "author_key": "author-b", "thread_key": "thread-a",
                "topic_codes": ["multi_device_capacity"],
                "topic_labels": ["桌面深度与设备容纳"],
            },
        ]
        social = next(row for row in ev.source_breakdown(voices) if row["source_kind"] == "social")
        self.assertEqual(2, len(social["top_topics"]))
        self.assertEqual("桌面深度与设备容纳", social["top_topics"][0]["label"])
        self.assertEqual(2, social["top_topics"][0]["count"])
        self.assertEqual(1.0, social["top_topics"][0]["share"])

    def test_pending_reconciliation_and_input_path_protection(self):
        self.run_analysis()
        coding, analysis = self.outputs()
        self.assertEqual(coding["funnel"]["hard_unique_records"], sum(len(coding[key]) for key in ("voices", "excluded_records", "pending_records")))
        bad = copy.deepcopy(coding)
        bad["pending_records"].append({"record_id": "fake", "hard_identity": "fake"})
        with self.assertRaises(cvlr.LocalReprocessError): cvlr.validate_v3_documents(bad, analysis)
        original = self.db.read_bytes()
        with self.assertRaises(cvlr.LocalReprocessError): self.run_analysis(coding_cache=self.db)
        self.assertEqual(original, self.db.read_bytes())
        with self.assertRaises(cvlr.LocalReprocessError): self.run_analysis(export_coding_queue=self.dashboard)

    def test_same_task_receipt_is_whitelisted_and_cannot_certify_readiness(self):
        receipt = self.root / "receipt.json"
        receipt.write_text(json.dumps({"task_id": "task-1", "collection_mode": "scrapecreators", "acquisition_budget": {"credits_cap": 6250, "committed_credits": 3, "private_key": "secret"}, "evidence_saturation": {"status": "saturated"}}))
        self.run_analysis(collection_receipt=receipt)
        analysis = self.outputs()[1]
        self.assertEqual(3, analysis["collection_summary"]["credits_used"])
        self.assertNotIn("secret", json.dumps(analysis))
        self.assertEqual("not_saturated", analysis["evidence_readiness"]["saturation"]["status"])
        receipt.write_text(json.dumps({"task_id": "other"}))
        with self.assertRaises(cvlr.LocalReprocessError): self.run_analysis(collection_receipt=receipt)

    def test_real_free_plan_import_and_local_reprocess_preserve_all_history_query_ids(self):
        collector = Path(cvlr.__file__).with_name("consumer_voice_collector.py")
        collection = self.root / "collection"
        backend_path = self.root / "backend_config.json"
        backend_path.write_text(json.dumps({"backend_url": "https://backend.example.com", "backend_token": "sk-example-test-token"}))
        backend_path.chmod(0o600)
        def command(*args):
            proc = subprocess.run([sys.executable, str(collector), *args], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, proc.stderr)
        command("plan", "--backend-config", str(backend_path), "--run-dir", str(collection), "--task-id", "roundtrip", "--topic", "car phone holder", "--collection-mode", "free", "--no-reminders")
        records = self.root / "reviews.json"
        records.write_text(json.dumps([{"id": "comment-one", "text": "I need a stronger car phone holder clamp", "url": "https://example.com/product", "author_id": "customer", "thread_id": "product-one"}]))
        command("import-records", "--run-dir", str(collection), "--task-id", "roundtrip", "--source-kind", "review", "--source", "amazon", "--input", str(records))
        db = collection / "collector.sqlite3"
        before = cvlr.file_sha256(db)
        out = self.root / "roundtrip-output"
        cvlr.reprocess(db, out, task_id="roundtrip", selection_file=self.selection, dashboard=self.dashboard)
        coding = json.loads((out / cvlr.CODING_FILENAME).read_text())
        self.assertEqual(before, cvlr.file_sha256(db))
        self.assertEqual(1, coding["funnel"]["qualified_consumer_voices"])
        self.assertEqual("review", coding["voices"][0]["source_kind"])
        self.assertTrue(all("30d" not in route["query_id"] for route in coding["voices"][0]["discovery_routes"]))

    def test_readiness_recomputation_rejects_forged_certification(self):
        self.run_analysis()
        coding, analysis = self.outputs()
        analysis["evidence_readiness"]["status"] = "sufficient"
        for check in analysis["evidence_readiness"]["checks"]:
            check["passed"] = True
        with self.assertRaises(cvlr.LocalReprocessError): cvlr.validate_v3_documents(coding, analysis)

    def test_cross_provider_identity_is_merged_but_different_comment_ids_survive(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        record = dict(con.execute("SELECT * FROM comments WHERE record_id='same-a'").fetchone())
        record.update(record_id="second-provider-copy", hard_key="another-provider-key")
        con.execute("INSERT INTO comments (%s) VALUES (%s)" % (",".join(record), ",".join("?" for _ in record)), tuple(record.values()))
        con.commit(); con.close()
        self.run_analysis()
        coding, _ = self.outputs()
        self.assertEqual(13, coding["funnel"]["hard_unique_records"])
        self.assertEqual(1, coding["funnel"]["hard_duplicate_rows_skipped"])
        self.assertTrue({"same-a", "same-b"}.issubset({v["voice_id"] for v in coding["voices"]}))

    def test_reverse_kano_and_current_applicability_bind_to_exact_need(self):
        text = "I do not want magnets in my car phone holder but I need a stronger clamp."
        con = sqlite3.connect(self.db)
        con.execute("UPDATE comments SET text=? WHERE record_id='same-a'", (text,))
        con.commit(); con.close()
        self.run_analysis()
        row = next(json.loads(x) for x in (self.output / "agent_coding_queue.jsonl").read_text().splitlines() if json.loads(x)["record_id"] == "same-a")
        decision = self.decision(row)
        decision["needs"] = [
            {"code": "unwanted_magnets", "label": "避免磁吸", "quote": "I do not want magnets", "stance": "counter", "applicability": "unknown", "kano_type": "反向型", "kano_reason": "该原文明确拒绝磁铁", "kano_review_status": "classified", "kano_review_version": "1.0.0"},
            {"code": "clamp_retention", "label": "夹持可靠性", "quote": "I need a stronger clamp", "stance": "support", "applicability": "current", "applicability_reason": "当前项目采用夹持结构，同一接口场景仍适用"},
        ]
        path = self.root / "reviewed.json"
        path.write_text(json.dumps({"entries": [decision]}))
        self.run_analysis(agent_coding=[path])
        analysis = self.outputs()[1]
        self.assertEqual(["unwanted_magnets"], [row["need_code"] for row in analysis["kano"]])
        self.assertEqual("反向型", analysis["kano"][0]["kano_type"])
        clamp = next(n for n in analysis["evidence_readiness"]["needs"] if n["code"] == "clamp_retention")
        self.assertEqual(["same-a"], clamp["applicability"]["current"])


class AdequacyTests(unittest.TestCase):
    def test_identical_viewpoint_labels_merge_without_losing_distinct_voices(self):
        voices = [
            {"voice_id": "voice-a", "author_key": "youtube:author-a", "thread_key": "youtube:one", "platform": "youtube", "excerpt": "第一个用户的原话", "topic_codes": ["old_capacity_code"], "topic_labels": ["桌面深度与设备容纳"], "semantic_codes": []},
            {"voice_id": "voice-b", "author_key": "reddit:author-b", "thread_key": "reddit:one", "platform": "reddit", "excerpt": "第二个用户的原话", "topic_codes": ["new_capacity_code"], "topic_labels": ["桌面深度与设备容纳"], "semantic_codes": []},
        ]
        metrics = cvlr._topic_metrics(voices, 2)
        self.assertEqual(2, len(metrics))
        self.assertEqual("桌面深度与设备容纳", metrics[0]["label"])
        self.assertEqual(1, metrics[0]["count"])
        self.assertEqual(1, metrics[0]["known_authors"])

    def test_same_thread_distinct_authors_remain_separate_voice_counts(self):
        voices = [
            {
                "voice_id": "voice-a", "platform": "youtube", "author_key": "youtube:author-a",
                "thread_key": "youtube:video-1", "coding_method": "agent_reviewed",
                "needs": [{"code": "desk_stability", "label": "稳定性", "stance": "support", "applicability": "current", "alternative_explanations": []}],
            },
            {
                "voice_id": "voice-b", "platform": "youtube", "author_key": "youtube:author-b",
                "thread_key": "youtube:video-1", "coding_method": "agent_reviewed",
                "needs": [{"code": "desk_stability", "label": "稳定性", "stance": "support", "applicability": "current", "alternative_explanations": []}],
            },
            {
                "voice_id": "voice-c", "platform": "youtube", "author_key": "unknown:voice-c",
                "thread_key": "youtube:video-1", "coding_method": "agent_reviewed",
                "needs": [{"code": "desk_stability", "label": "稳定性", "stance": "support", "applicability": "current", "alternative_explanations": []}],
            },
        ]
        need = ev.need_metrics(voices, ev.DEFAULT_THRESHOLDS)[0]
        self.assertEqual(3, need["count"])
        self.assertEqual(2, need["known_authors"])
        self.assertEqual(1, need["anonymous_author_voice_records"])
        self.assertEqual(1, need["contexts"])

    def voices(self):
        result = []
        for batch, size in (("b0", 2400), ("b1", 200), ("b2", 200), ("b3", 200)):
            for i in range(size):
                platform = "reddit" if i % 3 else "youtube"
                result.append({"voice_id": batch + ":" + str(i), "platform": platform, "source_kind": "social", "excerpt": "real observation", "author_key": platform + ":" + str(i), "thread_key": platform + ":thread:" + str(i % 7), "coding_method": "agent_reviewed", "first_batch_id": batch, "segment_memberships": ["segment_1_all_history"], "topic_codes": ["topic_%02d" % (i % 10)], "semantic_codes": ["feature_reverse_innovation"], "scenarios": [{"code": "daily_use"}], "needs": [{"code": "topic_%02d" % (i % 10), "label": "need", "stance": "support", "applicability": "current", "alternative_explanations": []}]})
        return result

    def evaluate(self, voices, batches=None, **kwargs):
        return ev.evaluate(voices, [{"segment_id": "segment_1_all_history", "feature": "sample segment"}], batches or ["b0", "b1", "b2", "b3"], {"unreviewed_records": 0}, required_scenarios=["daily_use"], **kwargs)

    def test_genuine_independent_saturation_satisfies_default_gates(self):
        result = self.evaluate(self.voices())
        self.assertEqual("sufficient", result["status"])
        self.assertEqual("saturated", result["saturation"]["status"])
        self.assertTrue(all(need["eligible"] for need in result["needs"]))
        self.assertEqual(10000, result["thresholds"]["target"])

    def test_single_segment_requires_6000_total_effective_voices(self):
        result = ev.evaluate_single_segment(
            self.voices()[:2999],
            {"segment_id": "segment_1_all_history", "feature": "sample segment"},
            ["b0", "b1", "b2", "b3"],
            {"unreviewed_records": 0},
            social_policy={
                "normal_valid_target": 2000,
                "normal_valid_max": 3000,
                "data_exhaustion_downgrade_floor": 1200,
            },
            required_scenarios=["daily_use"],
        )
        quantity = next(item for item in result["checks"] if item["code"] == "quantity")
        self.assertEqual(6000, quantity["required"])
        self.assertFalse(quantity["passed"])
        self.assertEqual(6000, result["thresholds"]["target"])

    def test_future_unstarted_query_is_not_a_failed_observation(self):
        batches = ["b0", "b1", "b2", "b3", "future"]
        statuses = {batch: "completed" for batch in batches}
        statuses["future"] = "planned"
        result = self.evaluate(self.voices(), batches, batch_statuses=statuses)
        self.assertEqual("sufficient", result["status"])
        self.assertEqual(["future"], result["saturation"]["unstarted_batch_ids"])
        statuses["future"] = "failed"
        self.assertEqual("partial", self.evaluate(self.voices(), batches, batch_statuses=statuses)["status"])

    def test_failed_or_duplicate_only_batch_cannot_be_saturation(self):
        result = self.evaluate(self.voices(), ["b0", "b1", "b2", "b3", "failed"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(0, result["saturation"]["batches"][-1]["new_valid_voices"])
        voices = self.voices()
        for voice in voices: voice["first_batch_id"] = "b0"
        self.assertEqual("not_saturated", self.evaluate(voices)["saturation"]["status"])

    def test_novel_topics_small_batches_and_changed_top_ten_break_saturation(self):
        voices = self.voices()
        for v in voices:
            if v["first_batch_id"] == "b3": v["needs"][0]["code"] = "novel_" + v["needs"][0]["code"]
        self.assertEqual("not_saturated", self.evaluate(voices)["saturation"]["status"])
        voices = [v for v in self.voices() if not (v["first_batch_id"] == "b3" and v["voice_id"].endswith(":199"))]
        self.assertEqual("not_saturated", self.evaluate(voices)["saturation"]["status"])

    def test_unknown_authors_historical_only_and_missing_scenarios_are_not_adequate(self):
        voices = self.voices()
        for v in voices:
            v["author_key"] = "unknown:" + v["voice_id"]
            v["needs"][0]["applicability"] = "historical"
            v["scenarios"] = []
        result = self.evaluate(voices)
        self.assertEqual("partial", result["status"])
        self.assertTrue(all(n["known_authors"] == 0 and not n["eligible"] for n in result["needs"]))
        self.assertEqual(3000, next(c for c in result["checks"] if c["code"] == "quantity")["observed"])

    def test_counterevidence_is_retained_without_becoming_support(self):
        voices = self.voices()
        voices[0]["needs"][0].update(stance="counter", alternative_explanations=["installation differs"])
        result = self.evaluate(voices)
        need = next(n for n in result["needs"] if n["code"] == "topic_00")
        self.assertIn(voices[0]["voice_id"], need["counter_refs"])
        self.assertNotIn(voices[0]["voice_id"], need["support_refs"])
        self.assertIn("installation differs", need["alternative_explanations"])

    def test_failed_batch_with_many_comments_and_unrecommended_segments(self):
        voices = self.voices()
        status = {batch: "completed" for batch in ("b0", "b1", "b2", "b3")}
        status["b3"] = "failed"
        self.assertEqual("partial", self.evaluate(voices, batch_statuses=status)["status"])
        result = ev.evaluate(voices, [{"segment_id": "segment_1_all_history"}, {"segment_id": "segment_2_all_history"}], ["b0", "b1", "b2", "b3"], {"unreviewed_records": 0}, required_scenarios=["daily_use"])
        self.assertEqual("sufficient", result["status"])
        self.assertFalse(result["segment_coverage"][1]["meets_quantity"])

    def test_four_fifty_record_collections_make_one_auditable_increment(self):
        voices = self.voices()[:200]
        for i, v in enumerate(voices):
            v["first_batch_id"] = "source_%d" % (i // 50)
        result = ev.saturation(voices, ["source_0", "source_1", "source_2", "source_3"], ev.DEFAULT_THRESHOLDS)
        self.assertEqual(1, len(result["batches"]))
        self.assertEqual(200, result["batches"][0]["new_valid_voices"])
        self.assertEqual(["source_0", "source_1", "source_2", "source_3"], result["batches"][0]["source_batch_ids"])
        self.assertFalse(result["batches"][0]["passed"], "The first observation has no previous themes for comparison")

    def test_empty_collection_interrupts_group_and_duplicate_rediscovery_is_not_new(self):
        voices = self.voices()[:200]
        for i, v in enumerate(voices):
            v["first_batch_id"] = "source_%d" % (i // 50)
        result = ev.saturation(voices, ["source_0", "source_1", "empty", "source_2", "source_3"], ev.DEFAULT_THRESHOLDS)
        self.assertEqual([100, 0, 100], [r["new_valid_voices"] for r in result["batches"]])
        self.assertTrue(all(not r["passed"] for r in result["batches"]))
        copies = copy.deepcopy(voices)
        for v in copies: v["first_batch_id"] = "rediscovered"
        result = ev.saturation([*voices, *copies], ["source_0", "source_1", "source_2", "source_3", "rediscovered"], ev.DEFAULT_THRESHOLDS)
        self.assertEqual([200, 0], [r["new_valid_voices"] for r in result["batches"]])


if __name__ == "__main__":
    unittest.main()
