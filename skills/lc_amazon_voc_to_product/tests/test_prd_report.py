import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consumer_all_history_report as report
import consumer_product_development as development


def analysis():
    return {"methodology": {"kano_mode": "need_holistic_inference"},
            "kano": [{"need_id": "stability", "label": "稳定", "status": "pending", "related_count": 42}],
            "evidence_readiness": {"needs": [{"code": "stability", "support_refs": ["v1"], "counter_refs": ["v2"]}]}}


def judgment():
    return {"schema_version": "consumer-need-judgments-1.0", "needs": [{
        "need_id": "stability", "status": "classified", "classification": "O", "rationale": "表现改善与满意相关",
        "review_version": "review-1", "evidence_ids": ["v1"], "counter_evidence_ids": ["v2"],
        "applicable_scenarios": ["打字"], "validation_questions": ["怎样影响满意度？"]}]}


class PRDReportTest(unittest.TestCase):
    def test_target_progress_can_exceed_one_hundred_percent(self):
        rendered = report._render_evidence({"business_rules_version": "voc-prd-v2", "evidence_readiness": {"checks": [
            {"label": "Amazon", "observed": 4525, "required": 4000, "blocking": False, "passed": True}]}})
        self.assertIn("113.1%", rendered)
        self.assertNotIn("目标进度 1.1%", rendered)

    def test_full_contract_accepts_only_truly_below_threshold_v2(self):
        source = analysis()
        source.update(schema_version=report.SCHEMA_VERSION, business_rules_version="voc-prd-v2",
                      metadata={"no_network": True, "date_filter_applied": False, "source_db_sha256": "a" * 64},
                      funnel={"qualified_consumer_voices": 5539})
        source["kano"] = [{"need_id": "rare", "status": "below_threshold", "count": 166}]
        report._validate_all_history_contract(source, label="analysis", require_kano=True)
        source["kano"][0]["count"] = 167
        with self.assertRaises(report.ReportError):
            report._validate_all_history_contract(source, label="analysis", require_kano=True)

    def test_v2_judgment_requires_current_evidence_fingerprint(self):
        source = analysis()
        source["business_rules_version"] = "voc-prd-v2"
        source["kano"][0]["source_sha256"] = "current-evidence"
        payload = judgment()
        for fingerprint in (None, "stale-evidence"):
            payload["needs"][0]["source_sha256"] = fingerprint
            with self.assertRaises(report.ReportError):
                report.import_need_judgments(source, payload)
        payload["needs"][0]["source_sha256"] = "current-evidence"
        self.assertEqual(report.import_need_judgments(source, payload)["kano"][0]["status"], "classified")

    def test_qa_irrelevant_not_rendered_as_buying_insight(self):
        source = analysis()
        source["alexa_analysis"] = {"records": [{"disposition": "irrelevant", "answer_summary": "床垫厚度", "buying_dimensions": ["床垫"]}]}
        self.assertNotIn("床垫厚度", report._render_qa_analysis(source))

    def test_v2_qa_display_alias_keeps_unknown_dimension(self):
        source = analysis()
        source["business_rules_version"] = "voc-prd-v2"
        source["alexa_analysis"] = {"records": [
            {"disposition": "adopted", "answer_summary": "资料要点", "buying_dimensions": ["首次安装", "安装方式", "新的未知维度"]}]}
        html = report._render_qa_analysis(source)
        self.assertIn("安装、装拆与移动 · 1 条回答", html)
        self.assertIn("新的未知维度 · 1 条回答", html)

    def test_below_threshold_skipped_and_retained_in_audit(self):
        source = analysis()
        source["kano"].append({"need_id": "rare", "status": "below_threshold", "related_count": 1})
        result = report.import_need_judgments(source, judgment())
        self.assertEqual(len(result["kano"]), 2)
        self.assertNotIn("rare", report._render_kano(result))
        self.assertNotIn("v1", report._render_kano(result))

    def test_empty_qa_does_not_pass_and_normalization(self):
        from flyfus_qa_catalog import normalize_answer
        self.assertEqual(normalize_answer({"answer": "Fits", "products": [{"title": "Desk"}]}), "Fits\nDesk")
        source = analysis()
        source["alexa_analysis"] = {"schema_version": "consumer-qa-analysis-1.0", "pending_count": 0}
        self.assertFalse(report.completion_layers(source)["Alexa已采分析"])
        self.assertFalse(report.completion_layers(source)["概念与验证计划"])

    def test_opportunity_threshold_and_no_truncation(self):
        source = {"business_rules_version": "voc-prd-v2", "new_needs": [{"label": "rare", "share": .00499}, *[{"label": "idea" + str(i), "share": .005} for i in range(25)]]}
        html = report._render_innovations(source)
        self.assertNotIn("rare", html)
        self.assertIn("idea24", html)

    def test_holistic_preserves_authoritative_counts_and_input(self):
        source = analysis()
        payload = judgment()
        payload["needs"][0]["related_count"] = 9000
        result = report.import_need_judgments(source, payload)
        self.assertEqual(result["kano"][0]["related_count"], 42)
        self.assertEqual(source["kano"][0]["status"], "pending")
        html = report._render_kano(result)
        self.assertIn("期望", html)
        self.assertNotIn("主导类型", html)

    def test_all_pending_and_uncertain_visible(self):
        self.assertIn("尚未执行", report._render_kano(analysis()))
        payload = judgment()
        payload["needs"][0].update(status="insufficient", classification=None)
        self.assertIn("信息不足", report._render_kano(report.import_need_judgments(analysis(), payload)))

    def test_invalid_judgments_rejected(self):
        for modify in (lambda p: p["needs"].append(copy.deepcopy(p["needs"][0])),
                       lambda p: p["needs"][0].update(evidence_ids=["alexa-1"]),
                       lambda p: p["needs"][0].update(status="insufficient"),
                       lambda p: p["needs"][0].update(review_version="")):
            payload = judgment()
            modify(payload)
            with self.assertRaises(report.ReportError):
                report.import_need_judgments(analysis(), payload)

    def test_rendering_not_business_completion(self):
        self.assertFalse(any(report.completion_layers(analysis()).values()))

    def test_qa_content_bound_to_actual_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa.json"
            path.write_text(json.dumps({"operation": "recommended_qa", "request": {"asin": "B000000001"}, "response": {"data": {"items": [{"answer": "Suitable with conditions"}]}}}))
            records = {"schema_version": "consumer-qa-records-1.0", "records": [{"record_id": "q1", "source_ref": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "item_index": 0, "answer": "Suitable with conditions"}]}
            payload = {"schema_version": "consumer-qa-analysis-1.0", "records": [{"record_id": "q1", "question_summary": "适用吗", "answer_summary": "有条件", "claim_kind": "product_promise", "conflict_check": "未核验商品尺寸", "next_verification": "量桌深", "review_version": "1", "need_ids": ["stability"], "buying_dimensions": ["适用性"], "unknown_conditions": ["桌深"], "evidence_quotes": ["with conditions"]}]}
            result = report.import_qa_analysis(records, payload, analysis())
            self.assertEqual(result["analyzed_count"], 1)
            self.assertNotIn("qualified_consumer_voices", result)
            records["records"][0]["answer"] = "Fake answer"
            with self.assertRaises(report.ReportError):
                report.import_qa_analysis(records, payload, analysis())

    def test_release_gates_are_visible_without_internal_issue_payloads(self):
        result = report._render_release_gates({"release_gates": {
            "engineering_before_human": "先台架再用户", "commercial": "成本与选择门",
            "materials_compliance": {"release": "须核验材料"},
            "internal_voice_ids": ["voice_should_not_show"]}})
        self.assertIn("先台架再用户", result)
        self.assertIn("成本与选择门", result)
        self.assertIn("尚未执行", result)
        self.assertNotIn("voice_should_not_show", result)
        self.assertEqual("", report._render_release_gates({}))
        source = {"business_rules_version": "voc-prd-v2", "product_concepts": []}
        rendered, _, _ = report._render_concepts(source, analysis_dir=Path.cwd(), image_overrides={})
        self.assertIn("恰好三个", rendered)
        self.assertNotIn("允许零推荐", rendered)

    def test_complete_pool_benchmark_and_feature_mapping(self):
        source = analysis()
        source.update(selected_segment={"segment_id": "compact"}, competitive_pool={
            "product_count": 1, "asins": ["B000000001"], "products": [{"asin": "B000000001", "sales": 10, "sales_stat_period": "30d"}]})
        marker = {"asin": "B000000001", "sales": 10, "sales_period": "30d", "selection_rationale": "最接近结构且销量领先"}
        row = {"concept_id": "c1", "core_requirements": ["r1"], "requirement_mapping": {"r1": {"features": ["稳定结构"], "need_ids": ["stability"]}},
               "product_coverage": [{"asin": "B000000001", "requirements": {"r1": "unknown"}, "requirement_evidence": {"r1": {"rationale": "未提供尺寸"}}}],
               "verdict": "verification_pending", "benchmark": marker, "sales_benchmark": copy.deepcopy(marker),
               "comparison": {key: "待验证的比较" for key in ("benchmark_satisfies", "remaining_gap", "our_change", "expected_improvement", "tradeoffs", "validation")}}
        audit = {"segment_id": "compact", "product_pool": {"product_count": 1}, "concepts": [row]}
        concepts = [{"concept_id": "c1", "features": ["稳定结构"], "core_need_codes": ["stability"]}]
        development.validate_competition_audit(audit, source, concepts)
        row["sales_benchmark"]["sales"] = 20
        with self.assertRaises(development.DevelopmentError):
            development.validate_competition_audit(audit, source, concepts)
        row["sales_benchmark"]["sales"] = 10
        row["verdict"] = "no_direct_equivalent"
        with self.assertRaises(development.DevelopmentError):
            development.validate_competition_audit(audit, source, concepts)


if __name__ == "__main__":
    unittest.main()
