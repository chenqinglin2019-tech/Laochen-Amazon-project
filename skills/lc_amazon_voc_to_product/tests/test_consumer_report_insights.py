from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPORT_SPEC = importlib.util.spec_from_file_location("consumer_all_history_report", SKILL_ROOT / "scripts" / "consumer_all_history_report.py")
assert REPORT_SPEC and REPORT_SPEC.loader
REPORT = importlib.util.module_from_spec(REPORT_SPEC)
REPORT_SPEC.loader.exec_module(REPORT)
FIXTURE_SPEC = importlib.util.spec_from_file_location("all_history_fixture", SKILL_ROOT / "tests" / "test_consumer_all_history_report.py")
assert FIXTURE_SPEC and FIXTURE_SPEC.loader
FIXTURE = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(FIXTURE)


class ConsumerReportInsightsTests(unittest.TestCase):
    def test_sidecars_are_hash_bound_and_embedded_in_existing_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = FIXTURE._analysis(root)
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
            insights = root / "v5-run"
            insights.mkdir()
            (insights / "need_evidence_links.json").write_text(json.dumps({"needs": [{"need_id": "n1", "research_signal_counts": {"alexa_refs": 2}}]}), encoding="utf-8")
            (insights / "recommended_qa.json").write_text(json.dumps({"summary": {"returned_question_records": 167, "answered_question_records": 166, "keyword_query_count": 10, "product_asin_count": 5, "product_page_count": 9, "gaps": ["仅纳入已保存页"]}}), encoding="utf-8")
            (insights / "active_question_plan.json").write_text(json.dumps({"questions": [{"question_id": "q1", "development_decision": "验证安装兼容", "expected_verification": "确认是否覆盖现有型号"}]}), encoding="utf-8")
            (insights / "active_qa_ledger.jsonl").write_text(json.dumps({"question_id": "q1", "state": "completed"}) + "\n", encoding="utf-8")
            (insights / "flyfus_receipts.jsonl").write_text(json.dumps({"provider": "flyfus", "operation": "review_probe", "status": "batch_contract_mismatch", "points_cap": 10, "points_reserved": 10}) + "\n", encoding="utf-8")
            report_path = root / "report.html"
            receipt = REPORT.render_report(analysis, analysis_path=analysis_path, template_path=REPORT._default_template(), output_path=report_path, insight_dir=insights)
            text = report_path.read_text(encoding="utf-8")
            self.assertEqual(64, len(receipt["insight_sha256"]))
            self.assertIn("Alexa/Rufus 研究线索", text)
            self.assertIn("Flyfus 已保存 167 条返回问答", text)
            self.assertIn("recommended_qa.json", receipt["insight_files"])
            self.assertIn("Flyfus 积分", text)
            self.assertIn("ScrapeCreators credits 分开记录", text)
            self.assertNotIn('href="#evidence"', text)
            self.assertNotIn('href="#sources"', text)
            self.assertNotIn('href="#brainstorm"', text)
            order = [text.index(f'id="{section}"') for section in ("decision", "funnel", "semantics", "voices", "category", "segments", "kano", "innovation", "concepts", "method")]
            self.assertEqual(order, sorted(order))
            self.assertFalse(REPORT.validate_report_html(text))

    def test_finalization_rejects_a_changed_insight_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = FIXTURE._finalizer_fixture(root)
            insights = root / "v5-run"
            insights.mkdir()
            plan = {"questions": [{"question_id": "q1", "development_decision": "验证兼容", "expected_verification": "确认适用性"}]}
            (insights / "active_question_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
            REPORT.render_report(analysis, analysis_path=paths["analysis"], template_path=REPORT._default_template(), output_path=paths["report"], insight_dir=insights)
            REPORT.finalize_manifest(
                manifest_path=paths["manifest"], coding_path=paths["coding"], analysis_path=paths["analysis"],
                report_path=paths["report"], source_db_path=paths["source_db"], dashboard_path=paths["dashboard"],
                status="partial", source_snapshot_path=paths["snapshot"], insight_dir=insights,
            )
            plan["questions"].append({"question_id": "q2", "development_decision": "验证材料", "expected_verification": "确认耐久"})
            (insights / "active_question_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaises(REPORT.ReportError):
                REPORT.finalize_manifest(
                    manifest_path=paths["manifest"], coding_path=paths["coding"], analysis_path=paths["analysis"],
                    report_path=paths["report"], source_db_path=paths["source_db"], dashboard_path=paths["dashboard"],
                    status="partial", source_snapshot_path=paths["snapshot"], insight_dir=insights,
                )


if __name__ == "__main__":
    unittest.main()
