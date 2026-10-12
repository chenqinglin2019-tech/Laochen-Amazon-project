"""Offline integration with synthetic fixtures, never a real research execution."""
import copy
import hashlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consumer_all_history_report as report
import single_segment_contract as contract
import test_consumer_voice_local_reprocess as fixtures
from test_single_segment_contract import input_payload


class PRDIntegrationTest(unittest.TestCase):
    def test_rules_review_holistic_import_and_report_requires_finished_development(self):
        fixture = fixtures.LocalReprocessTestCase()
        fixture.setUp()
        try:
            source_hash = None
            with sqlite3.connect(fixture.db) as db:
                db.execute("DELETE FROM comment_discoveries")
                db.execute("DELETE FROM comments")
                for rid, platform, text in (("review", "amazon", "My truck phone mount shakes"),
                                            ("web", "web", "My truck phone mount shakes"),
                                            ("unclear", "web", "I wonder about this"),
                                            ("empty", "web", "🔥")):
                    db.execute("INSERT INTO comments(record_id,task_id,source,content_id,hard_key,author_id,text,canonical_url,raw_json) VALUES(?,?,?,?,?,?,?,?,?)",
                               (rid, "task-1", platform, rid, rid, "same-author", text, "https://example.com/" + rid, "{}"))
                    db.execute("INSERT INTO comment_discoveries(task_id,record_id,batch_id,scope,query_id,source) VALUES(?,?,?,?,?,?)",
                               ("task-1", rid, "b1", "selected_segment_all_history", "q1", platform))
            source_hash = hashlib.sha256(fixture.db.read_bytes()).hexdigest()
            input_file = fixture.root / "input.json"
            input_file.write_text(json.dumps(input_payload()))
            plan = contract.materialise(input_file, fixture.root / "frozen")
            selection = Path(plan["selection"])
            rules = {"version": "integration-v1", "rules": [{"id": "shake", "product_phrases": ["truck phone mount"],
                "phrases": ["shakes"], "semantic_codes": ["failure_complaint_return_alternative"],
                "need": {"need_id": "stability", "label": "稳定性", "stance": "support", "applicability": "current", "applicability_reason": "显式当前使用产品"}}]}
            rule_path = fixture.root / "rules.json"
            rule_path.write_text(json.dumps(rules))
            fixtures.cvlr.reprocess(fixture.db, fixture.output, selection_file=selection, rule_config=rule_path)
            coding, first = fixture._load_outputs()
            self.assertEqual(json.loads(selection.read_text())["full_product_pool"], first["competitive_pool"])
            self.assertEqual(2, len(coding["voices"]))
            self.assertEqual({"review", "social"}, {row["source_kind"] for row in coding["voices"]})
            self.assertTrue(first["evidence_readiness"]["needs"][0]["eligible"])
            self.assertFalse(report.completion_layers(first)["全量处理"])
            queue = [json.loads(line) for line in (fixture.output / "agent_coding_queue.jsonl").read_text().splitlines()]
            self.assertEqual(["unclear"], [row["record_id"] for row in queue])
            decision = {**queue[0], "decision": "undetermined", "coding_method": "model_reviewed", "reviewed_by": "synthetic-test", "reason": "测试夹具没有明确产品上下文"}
            reviewed = fixture.root / "reviewed.jsonl"
            reviewed.write_text(json.dumps(decision) + "\n")
            reviewed_dir = fixture.root / "before-quality"
            fixtures.cvlr.reprocess(fixture.db, reviewed_dir, selection_file=selection, rule_config=rule_path, agent_coding=[reviewed])
            sample = json.loads((reviewed_dir / "quality_review_queue.json").read_text())
            quality = fixture.root / "quality.json"
            quality.write_text(json.dumps({"reviewer": "synthetic-QA", "taxonomy_sha256": sample["taxonomy_sha256"], "results_sha256": sample["results_sha256"],
                                           "reviewed_cache_keys": [row["cache_key"] for row in sample["entries"]], "open_issues": 0}))
            final_dir = fixture.root / "reviewed"
            fixtures.cvlr.reprocess(fixture.db, final_dir, selection_file=selection, rule_config=rule_path, agent_coding=[reviewed], quality_review=quality)
            final = json.loads((final_dir / fixtures.cvlr.ANALYSIS_FILENAME).read_text())
            final_coding = json.loads((final_dir / fixtures.cvlr.CODING_FILENAME).read_text())
            self.assertEqual({"include": 2, "exclude": 1, "undetermined": 1, "pending": 0}, final["processing_reconciliation"])
            self.assertTrue(report.completion_layers(final)["全量处理"])
            self.assertTrue(report.completion_layers(final)["疑难与质量"])
            need = final["evidence_readiness"]["needs"][0]
            payload = {"schema_version": "consumer-need-judgments-1.0", "needs": [{"need_id": "stability", "source_sha256": final["kano"][0]["source_sha256"], "status": "insufficient", "classification": None,
                "rationale": "合成夹具仅表达晃动，无法区分KANO类型", "review_version": "synthetic-v1", "evidence_ids": need["support_refs"],
                "counter_evidence_ids": [], "applicable_scenarios": ["当前使用"], "validation_questions": ["满足与不满足分别如何影响体验？"]}]}
            judgment_file = fixture.root / "need-judgments.json"
            judgment_file.write_text(json.dumps(payload))
            enriched = fixture.root / "enriched.json"
            self.assertEqual(0, report.main(["import-insights", "--analysis", str(final_dir / fixtures.cvlr.ANALYSIS_FILENAME), "--need-judgments", str(judgment_file), "--output", str(enriched)]))
            imported = json.loads(enriched.read_text())
            fixtures.cvlr.validate_v3_documents(final_coding, imported)
            self.assertTrue(report.completion_layers(imported)["需求与KANO"])
            self.assertFalse(all(report.completion_layers(imported).values()))
            output = fixture.root / "report.html"
            # This synthetic fixture stops before the required three-direction
            # workshop; processing/KANO completion cannot stand in for development.
            with self.assertRaisesRegex(report.ReportError, "恰好包含3个对象"):
                report.render_report(imported, analysis_path=enriched, template_path=report._default_template(), output_path=output)
            self.assertFalse(output.exists())
            rendered = report._render_decision(imported) + report._render_completion(imported)
            self.assertIn("已判断但不确定", rendered)
            self.assertIn("信息不足", rendered)
            self.assertIn("尚未通过", rendered)
            self.assertEqual("partial", imported["evidence_readiness"]["status"])
            self.assertEqual(source_hash, hashlib.sha256(fixture.db.read_bytes()).hexdigest())
            unknown = copy.deepcopy(final_coding["voices"])
            for voice in unknown:
                voice["needs"][0]["applicability"] = "unknown"
            import consumer_voice_evidence as evidence
            self.assertFalse(evidence.need_metrics(unknown, evidence.DEFAULT_THRESHOLDS)[0]["eligible"])
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
