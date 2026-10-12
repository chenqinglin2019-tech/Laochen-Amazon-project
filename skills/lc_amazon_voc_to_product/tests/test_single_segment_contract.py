from __future__ import annotations

import json
import copy
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consumer_voice_collector as collector
import demand_insight_v5 as demand
import single_segment_contract as contract


def input_payload() -> dict:
    return {
        "schema_version": "single-segment-input-1.0",
        "project": {"project_id": "p1", "marketplace": "US", "language": "en"},
        "selected_segment": {"id": "truck_mount", "name": "Truck phone mounts", "definition": "cab vibration use"},
        "sales_stat_period": "2026-08",
        "products": [
            {"asin": "B000000003", "sales": 50, "parent_asin": "P1"},
            {"asin": "B000000001", "sales": 100, "parent_asin": "P1"},
            {"asin": "B000000002", "sales": 100, "parent_asin": "P2"},
            {"asin": "B000000004", "sales": 20, "parent_asin": "P3"},
            {"asin": "B000000005", "sales": 10, "parent_asin": "P4"},
            {"asin": "B000000006", "sales": 5, "parent_asin": "P5"},
        ],
        "keywords": [
            {"keyword": "truck phone mount", "traffic_share": 0.4},
            {"keyword": "semi truck phone holder", "traffic_share": 0.4},
            {"keyword": "cab phone mount", "traffic_share": 0.2},
        ],
        "search_plan": {"planner_version": "test-v1", "expressions": [
            {"expression": term, "supporting_keywords": [term], "intent": intent,
             "reason": "full keyword evidence", "false_positive_scope": "unrelated holders"}
            for term, intent in (("truck phone mount", "product"),
                                 ("semi truck phone holder", "vehicle"), ("cab phone mount", "space"))]},
    }


class SingleSegmentContractTests(unittest.TestCase):
    def test_freezes_ranked_review_pool_with_top_five_initial_activation_and_top_ten_keywords(self):
        plan = contract.build_plan(input_payload())
        reviews = plan["sampling"]["reviews"]
        self.assertEqual(
            ["B000000001", "B000000002", "B000000003", "B000000004", "B000000005", "B000000006"],
            [item["asin"] for item in reviews["asins"]],
        )
        self.assertEqual(5, reviews["initial_asin_count"])
        self.assertEqual(50, reviews["max_asin_count"])
        self.assertEqual(6, reviews["actual_candidate_asin_count"])
        pool = plan["selection"]["full_product_pool"]
        self.assertEqual("2026-08", pool["sales_stat_period"])
        self.assertEqual(6, len(pool["products"]))
        self.assertEqual({"asin": "B000000001", "sales": 100.0, "sales_stat_period": "2026-08",
                          "detail": input_payload()["products"][1]}, pool["products"][0])
        self.assertEqual(1000, reviews["per_asin_raw_review_limit"])
        self.assertIn("documented_evidence_gap", reviews["progression_rule"])
        self.assertEqual(
            ["semi truck phone holder", "truck phone mount", "cab phone mount"],
            [item["keyword"] for item in plan["sampling"]["alexa"]["keywords"]],
        )
        social = plan["sampling"]["social"]
        self.assertEqual(2000, social["normal_valid_target"])
        self.assertIsNone(social["normal_valid_max"])
        self.assertIsNone(social["data_exhaustion_downgrade_floor"])
        self.assertEqual(4000, reviews["effective_review_target"])

    def test_materialise_writes_snapshot_plan_and_single_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.json"
            source.write_text(json.dumps(input_payload()), encoding="utf-8")
            result = contract.materialise(source, root / "run")
            selection = json.loads(Path(result["selection"]).read_text(encoding="utf-8"))
            self.assertEqual("single_segment", selection["workflow_mode"])
            self.assertEqual("truck_mount", selection["selected_segment"]["segment_id"])
            self.assertEqual(6, selection["full_product_pool"]["product_count"])

    def test_duplicate_asin_is_rejected(self):
        payload = input_payload()
        payload["products"].append(dict(payload["products"][0]))
        with self.assertRaises(contract.SingleSegmentContractError):
            contract.build_plan(payload)

    def test_collector_queue_contains_only_single_segment_scope(self):
        plan = contract.build_plan(input_payload())
        queues, query_plan, _ = collector._single_segment_query_queues(plan, "2026-09-13T00:00:00Z")
        self.assertTrue(queues)
        self.assertEqual({"selected_segment_all_history"}, {item["scope"] for item in queues})
        self.assertEqual("single_segment", query_plan["workflow_mode"])
        self.assertFalse(query_plan["constraints"]["date_filter_applied"])

    def test_demand_sidecar_uses_the_same_single_segment_plan(self):
        result = demand.plan_single_segment(input_payload())
        self.assertEqual("single_segment", result["workflow_mode"])
        self.assertEqual("truck_mount", result["selection"]["selected_segment"]["segment_id"])

    def test_unknown_market_requires_explicit_semantic_search_plan(self):
        payload = input_payload()
        payload.pop("search_plan")
        plan = contract.build_plan(payload)
        self.assertEqual("planning_required", plan["sampling"]["social"]["search_plan"]["status"])
        with self.assertRaises(collector.ConfigurationError):
            collector._single_segment_query_queues(plan, "2026-09-13T00:00:00Z")

    def test_category_examples_never_replace_an_explicit_search_plan(self):
        payload = input_payload()
        payload.pop("search_plan")
        payload["selected_segment"]["name"] = "紧凑型电脑办公桌"
        payload["keywords"] = [{"keyword": term, "traffic_share": share} for term, share in
                               (("small desk", .7), ("small computer desk", .2), ("compact office desk", .1))]
        plan = contract.build_plan(payload)
        self.assertEqual("planning_required", plan["sampling"]["social"]["search_plan"]["status"])
        with self.assertRaises(collector.ConfigurationError):
            collector._single_segment_query_queues(plan, "2026-09-13T00:00:00Z")

    def test_refresh_preserves_companion_search_tasks(self):
        plan = contract.build_plan(input_payload())
        _, _, queue = collector._single_segment_query_queues(plan, "2026-09-13T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp, collector.CollectorStore(Path(tmp) / "db.sqlite3") as store:
            root = Path(tmp)
            store.create_task("test", "desk", "single_segment", "2026-09-13T00:00:00Z", [], task_id="refresh")
            path = root / "agent_reach_queue.json"
            path.write_text(json.dumps(queue), encoding="utf-8")
            collector.refresh_agent_reach_queue(root, store, "refresh")
            refreshed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(queue["tasks"], refreshed["tasks"])

    def test_targets_are_independent_and_quality_is_required(self):
        for amazon, social in ((5000, 1000), (3000, 3000), (4000, 1900)):
            self.assertTrue(contract.collection_gate(amazon, social, processing_complete=True,
                             quality_passed=True, gap_check_recorded=True, approved_directions=3)["can_stop"])
        self.assertTrue(contract.collection_gate(4000, 2000, processing_complete=True,
                        quality_passed=True, gap_check_recorded=True, approved_directions=3)["can_stop"])
        self.assertFalse(contract.collection_gate(4000, 2000, processing_complete=False,
                         quality_passed=True, gap_check_recorded=True)["can_stop"])

    def test_review_expansion_uses_amazon_only(self):
        plan = contract.build_plan(input_payload())
        initial = contract.next_review_asins(plan, [], 0, current_batch_processed=True)
        self.assertEqual(5, len(initial))
        self.assertEqual([], contract.next_review_asins(plan, initial, 3999, current_batch_processed=True))
        self.assertEqual(["B000000006"], contract.next_review_asins(plan, initial, 3999, current_batch_processed=True, evidence_gap=True))
        self.assertEqual(["B000000006"], contract.next_review_asins(plan, initial, 4000, current_batch_processed=True, evidence_gap=True))
        progress = demand.single_segment_progress({"sampling_plan": plan, "completed_asins": initial,
            "amazon_valid": 3999, "social_valid": 2500, "current_batch_processed": True,
            "processing_complete": True, "quality_passed": True, "gap_check_recorded": True, "evidence_gap": True})
        self.assertEqual("collect_next_review_batch", progress["next_action"])
        self.assertEqual(1, progress["gaps"]["amazon"])

    def test_invalid_traffic_units_and_nonfinite_are_rejected(self):
        for value in (float("nan"), float("inf"), 40):
            payload = input_payload()
            payload["keywords"][0]["traffic_share"] = value
            with self.assertRaises(contract.SingleSegmentContractError):
                contract.build_plan(payload)

    def test_single_segment_policy_has_no_social_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp, collector.CollectorStore(Path(tmp) / "db.sqlite3") as store:
            task = store.create_task("test", "desk", "single_segment", "2026-09-13T00:00:00Z", [], task_id="uncapped")
            collector._apply_single_segment_policy(store, "uncapped", 4500)
            policy = store.task_payload("uncapped")
            self.assertIsNone(policy["research_plan"]["sample_target"]["total_valid_max"])
            self.assertEqual(4500, policy["collection_policy"]["evidence_target"]["normal_valid_target"])

    def test_web_originals_keep_site_identity_and_research_signals_do_not_count(self):
        with tempfile.TemporaryDirectory() as tmp, collector.CollectorStore(Path(tmp) / "db.sqlite3") as store:
            store.create_task("test", "desk", "single_segment", "2026-09-13T00:00:00Z", [], task_id="web")
            batch = store.add_batch("web", {"source": "web", "backend": "external", "scope": collector.SINGLE_SEGMENT_SCOPE})
            for domain, kind in (("a.test", "consumer_original"), ("b.test", "consumer_original"), ("c.test", "research_signal")):
                store.insert_comment("web", batch, {"source": "web", "source_kind": "social", "evidence_kind": kind,
                    "url": "https://" + domain + "/posts/1", "content_id": "1", "author_id": "same-local-id",
                    "text": "My small desk fits well", "published_at": "2026-09-01T00:00:00Z"})
            rows = store.connection.execute("SELECT technical_eligible,author_hash FROM comments ORDER BY canonical_url").fetchall()
            self.assertEqual([1, 1, 0], [row[0] for row in rows])
            self.assertNotEqual(rows[0][1], rows[1][1])

    def test_materialise_refuses_existing_frozen_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.json"
            source.write_text(json.dumps(input_payload()), encoding="utf-8")
            result = contract.materialise(source, root / "run")
            before = Path(result["input_snapshot"]).read_bytes()
            with self.assertRaises(contract.SingleSegmentContractError):
                contract.materialise(source, root / "run")
            self.assertEqual(before, Path(result["input_snapshot"]).read_bytes())

    def test_both_companion_directories_import_and_replay_without_inflation(self):
        with tempfile.TemporaryDirectory() as tmp, collector.CollectorStore(Path(tmp) / "db.sqlite3") as store:
            root = Path(tmp)
            store.create_task("test", "desk", "single_segment", "2026-09-13T00:00:00Z", [], task_id="companions")
            shared = {"platform": "web", "evidence_kind": "consumer_original", "source_kind": "social",
                "content_id": "post-1", "url": "https://forum.test/posts/1", "author_id": "user-1",
                "exact_text": "My small desk fits in my bedroom", "published_at": "2026-08-25T00:00:00Z"}
            for folder in ("agent_reach", "last30days"):
                directory = root / folder
                directory.mkdir()
                rows = [shared]
                if folder == "last30days":
                    rows += [dict(shared, content_id="post-2", url="https://forum.test/posts/2", author_id="user-2")]
                (directory / "voices.json").write_text(json.dumps({"scope_id": collector.SINGLE_SEGMENT_SCOPE,
                    "query_id": "q1", "records": rows}), encoding="utf-8")
            collector._import_external_agent_records(root, store, "companions")
            self.assertEqual(2, store.connection.execute("SELECT COUNT(*) FROM comments").fetchone()[0])
            self.assertEqual(3, store.connection.execute("SELECT COUNT(*) FROM comment_discoveries").fetchone()[0])
            again = collector._import_external_agent_records(root, store, "companions")
            self.assertEqual(0, again["records_seen"])
            raw = json.loads(store.connection.execute("SELECT raw_json FROM comments WHERE content_id='post-2'").fetchone()[0])
            self.assertEqual("last30days", raw["acquisition_tool"])
            self.assertEqual("recent_30_days", raw["source_window"])
            self.assertFalse(raw["global_date_filter_applied"])

    def test_success_page_survives_store_reopen_and_cursor_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "pages.sqlite3"
            response = {"status": "success", "response": {"items": [{"id": "r1"}]}, "received_at": "2026-09-15"}
            with collector.CollectorStore(db) as store:
                store.save_raw_page("task", "batch", "page1", response)
                store.save_raw_page("task", "batch", "page1", {"status": "overwritten"})
            with collector.CollectorStore(db) as store:
                self.assertEqual(response, store.raw_page("task", "batch", "page1"))
                store.clear_checkpoint("task", "batch")
                self.assertEqual(response, store.raw_page("task", "batch", "page1"))

    def test_raw_successful_page_is_saved_before_child_failure_and_reused(self):
        pages, checkpoint, emitted = {}, {}, []
        class Api(collector.YoutubeDataApiCollector):
            calls = []
            fail = True
            def _get(self, operation, params, before_request):
                self.calls.append(operation)
                if operation == "comments":
                    if self.fail:
                        raise collector.CollectorError("child failed")
                    return {"items": []}
                return {"items": [{"id": "thread", "snippet": {"totalReplyCount": 1,
                    "topLevelComment": {"id": "c1", "snippet": {"textDisplay": "test"}}}}]}
        api = Api("unused", object())
        def run():
            return api.collect("v1", checkpoint, emitted.append, checkpoint.update,
                lambda *args: None, lambda: None, load_page=lambda key: pages.get(key, {}),
                save_page=lambda key, value: pages.__setitem__(key, value))
        with self.assertRaises(collector.CollectorError):
            run()
        self.assertEqual(1, len(pages))
        api.fail = False
        run()
        self.assertEqual(1, api.calls.count("commentThreads"))
        self.assertEqual(2, len(pages))

    def test_report_renders_selected_segment_without_top3_heading(self):
        import consumer_all_history_report as report
        from tests.test_consumer_all_history_report import _analysis

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = copy.deepcopy(_analysis(root / "concept.png"))
            segment = dict(analysis["top_segments"][0])
            segment.update(segment_id="truck_mount", feature="Truck phone mounts", rank=1)
            analysis.update(
                workflow_mode="single_segment",
                selected_segment={"segment_id": "truck_mount", "name": "Truck phone mounts"},
                top_segments=[segment],
            )
            analysis_path = root / "analysis.json"
            output = root / "report.html"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            report.render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=report._default_template(),
                output_path=output,
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("所选细分的全历史消费者声音", rendered)
            self.assertNotIn("Top3细分的全历史消费者声音", rendered)


if __name__ == "__main__":
    unittest.main()
