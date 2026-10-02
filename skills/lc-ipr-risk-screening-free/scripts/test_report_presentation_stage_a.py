"""10A report presentation reads 09 state without reviving legacy grading."""
import copy
import csv
import hashlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from report_presentation_stage_a import REVISION, SAMPLE_STYLE_SHA256, build as build_presentation
from report_estimate import _digest
from test_report_estimate import EstimateReportTests


class OperatorReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = EstimateReportTests("test_all_formats_keep_reasons_and_grade")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.task = self.fixture.task
        self.task.update(presentation_policy_revision="operator-report-v1",
            assessment_revision="known-findings-risk-v1", primary_scenario_id="product_entry")
        self.assessment = copy.deepcopy(self.fixture.assessment)
        self.assessment["overall"]["risk"] = "低"
        self.assessment["known_findings"] = {"by_scope": [
            {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "copyright", "risk": "低"},
            {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "utility_model", "risk": "低",
             "applicability": "not_applicable", "query_not_required_reason": "本次普通玩具不涉及该独立权利制度。"}]}
        self.data = {"product": copy.deepcopy(self.task["product"]), "trace": {"source_task_dir": str(self.fixture.root)},
            "generated_at": "2026-09-29", "visual_evidence": [], "query_trace": {"queries": [], "unfinished_work": []},
            "presentation_stage_a": {"candidate_inventory": [], "stage": {"progress": {"completed": 7, "planned": 9,
                "percentage": 77.7778, "by_scope": [{"right_type": "copyright", "scenario_id": "product_entry", "completed": 5, "planned": 5}]},
                "stage_risk": {"judgments": [{"scope": {"right_type": "copyright", "scenario_id": "product_entry"},
                    "assessment_status": "pending", "risk": None, "pending_reasoning": "作者及授权尚未查明 EV-abcdef123456。"}]}}}}

    def model(self):
        from operator_report import build
        return build(self.task, self.fixture.evidence, self.assessment, {}, self.data)

    def test_completed_query_with_pending_facts_is_not_not_started(self):
        model = self.model()
        copyright = next(m for m in model["modules"] if m["right_type"] == "copyright")
        self.assertEqual(copyright["query_status"], "本轮计划步骤完成")
        self.assertEqual(copyright["risk"], "低")
        self.assertEqual(copyright["finding"], "存在待判断线索")
        self.assertTrue(copyright["unfinished"])
        self.assertEqual(model["progress"]["completed"], 7)
        self.assertEqual(model["progress"]["planned"], 9)
        utility = next(m for m in model["modules"] if m["right_type"] == "utility_model")
        self.assertEqual(utility["query_status"], "不适用")
        self.assertIsNone(utility["risk"])
        self.assertEqual(utility["risk_label"], "不适用")

    def test_unqueried_module_has_explicit_pending_grade_and_reason(self):
        from operator_report import project, render, render_markdown, render_csv
        model = self.model()
        patent = next(m for m in model["modules"] if m["right_type"] == "patent")
        self.assertEqual((patent["query_status"], patent["risk"], patent["risk_label"]),
            ("未查询", None, "待定"))
        self.assertTrue(any("尚未登记有效查询" in text for text in patent["unfinished"]))
        page = render(project(self.data, model), self.fixture.out)
        self.assertIn("本项风险：<b>待定</b>", page)
        self.assertIn("本项风险：待定", render_markdown(self.data))
        rows = list(csv.DictReader(io.StringIO(render_csv(self.data))))
        self.assertEqual(next(row for row in rows if row["right_type"] == "patent")["risk"], "待定")

    def test_confirmed_high_remains_visible_when_query_trace_is_missing(self):
        self.assessment["known_findings"]["by_scope"].append({"scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "risk": "高"})
        patent = next(m for m in self.model()["modules"] if m["right_type"] == "patent")
        self.assertEqual((patent["query_status"], patent["risk_label"]), ("未查询", "高"))

    def test_unreadable_official_export_is_disclosed_on_affected_card(self):
        from operator_report import build
        self.task['target_jurisdictions'] = ['US']
        issue = {'evidence_id': 'EV-BROKEN', 'jurisdiction': 'US',
            'affected_right_types': ['trademark_figurative'], 'error_code': 'TMSEARCH_EXPORT_INVALID'}
        model = build(self.task, self.fixture.evidence, self.assessment,
            {'official_export_issues': [issue]}, self.data)
        figurative = next(m for m in model['modules'] if m['right_type'] == 'trademark_figurative')
        word = next(m for m in model['modules'] if m['right_type'] == 'trademark_word')
        self.assertEqual(figurative['risk_label'], '待定')
        self.assertTrue(any('格式损坏' in text for text in figurative['unfinished']))
        self.assertFalse(any('格式损坏' in text for text in word['unfinished']))

    def test_operator_grade_reads_engine_and_annex_keeps_technical_data(self):
        from operator_report import project, render, render_audit
        self.assessment["overall"]["risk"] = "高"
        model = self.model()
        model["pending_items"].append({"modules": ["外观专利"], "text": "仍缺其他视图"})
        data = project(self.data, model)
        page = render(data, self.fixture.out)
        self.assertIn("高风险", page)
        self.assertNotIn("未开展／待确认", page)
        self.assertNotIn("EV-abcdef123456", page)
        self.assertNotIn("<pre", page)
        self.assertEqual(page.count('class="module"'), 9)
        self.assertIn("operator-appendix.html", page)
        self.assertIn("<pre", render_audit(data, self.fixture.out))

    def test_generic_name_and_missing_own_brand_are_distinct(self):
        self.data["product"]["brand_name_query"] = {"display": "无风险（Generic 通用占位，仅名称项）"}
        module = next(m for m in self.model()["modules"] if m["right_type"] == "trademark_word")
        self.assertEqual(module["query_status"], "无需查询（Generic 名称项）")
        self.assertTrue(any("自有品牌" in x and "未提供" in x for x in module["unfinished"]))

    def test_pending_recheck_never_claims_selected_and_compared(self):
        self.data['presentation_stage_a']['candidate_inventory'] = [{'candidate_id': 'D1',
            'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design',
            'publication_number': 'USD123456S1', 'title': 'Exact synthetic design',
            'triage_status': 'pending_recheck'}]
        self.assertEqual(self.model()['focus_candidates'][0]['status'], '待重新判断')

    def test_selection_requires_actual_comparison_before_claiming_compared(self):
        self.data['presentation_stage_a']['candidate_inventory'] = [{'candidate_id': 'D1',
            'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design',
            'publication_number': 'USD123456S1', 'title': 'Exact synthetic design',
            'triage_status': 'selected'}]
        self.assertEqual(self.model()['focus_candidates'][0]['status'], '已入选待比较')
        self.data['presentation_stage_a']['stage']['stage_risk']['judgments'].append({
            'scope': {'candidate_id': 'D1', 'scenario_id': 'product_entry', 'right_type': 'design'},
            'comparison': {'criteria': [{'criterion': 'overall_impression',
                'reasoning': 'Read the exact images and compared the recorded proportions.'}]}})
        self.assertEqual(self.model()['focus_candidates'][0]['status'], '已入选并比较')

    def test_pending_dedup_uses_object_and_fact_identity(self):
        rows = self.data['presentation_stage_a']['stage']['stage_risk']['judgments']
        rows[:] = [{'scope': {'candidate_id': candidate, 'scenario_id': 'product_entry',
            'right_type': 'copyright'}, 'assessment_status': 'pending',
            'pending_reasoning': '相同文字仍对应不同对象。'} for candidate in ('P1', 'P2')]
        items = [item for item in self.model()['pending_items'] if '相同文字' in item['text']]
        self.assertEqual(len(items), 2)
        rows[:] = [{'scope': {'scenario_id': 'product_entry', 'right_type': right},
            'assessment_object': 'animal-expression', 'fact_event_id': 'FACT-SHARED',
            'assessment_status': 'pending', 'pending_reasoning': text}
            for right, text in [('copyright', '作者未知。'), ('trade_dress', '来源未知。')]]
        items = [item for item in self.model()['pending_items'] if 'FACT-SHARED' in str(item['identity'])]
        self.assertEqual(len(items), 1)
        self.assertEqual(set(items[0]['modules']), {'版权', '商业外观'})
        self.assertIn('作者未知', items[0]['text'])
        self.assertIn('来源未知', items[0]['text'])

    def test_missing_policy_result_rejects_without_inventing_low(self):
        self.assessment["overall"]["risk"] = None
        with self.assertRaisesRegex(ValueError, "OPERATOR_REPORT_POLICY_RESULT_MISSING"):
            self.model()

    def test_pending_policy_result_and_product_specific_scenario_render(self):
        from operator_report import project, render, render_markdown, render_csv
        self.assessment['overall'].update(risk=None, risk_basis='insufficient_evidence',
            listing_recommendation='暂缓上架', listing_reason='尚无完成复核的适用判断。')
        self.data['product']['scope_assumption'] = '按用户声明销售蓝色陶瓷花瓶；品牌资料待补。'
        self.data['presentation_stage_a']['stage']['stage_risk']['judgments'][0]['scope']['jurisdiction'] = 'GB'
        model = self.model()
        self.assertIsNone(model['overall']['risk'])
        self.assertEqual(model['focus_candidates'][-1]['jurisdiction'], 'GB')
        page = render(project(self.data, model), self.fixture.out)
        self.assertIn('风险待定', page)
        self.assertIn('暂缓上架', page)
        self.assertIn('蓝色陶瓷花瓶', page)
        self.assertNotIn('毛绒动物', page)
        self.assertNotIn('使用自己的品牌销售与参考商品外观、功能一致', page)
        self.assertIn('上架建议：暂缓上架', render_markdown(self.data))
        overall_csv = next(csv.DictReader(io.StringIO(render_csv(self.data))))
        self.assertEqual((overall_csv['risk'], overall_csv['listing_recommendation']), ('待定', '暂缓上架'))


class PresentationStageATests(unittest.TestCase):
    def setUp(self):
        self.fixture = EstimateReportTests("test_all_formats_keep_reasons_and_grade")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.task["report_presentation_revision"] = REVISION
        self.fixture.task["stage_delivery_revision"] = "stage-delivery-stage-d-v1"
        scope = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "design",
                 "product_version": "V1", "candidate_id": "D1", "module_id": "appearance_patent"}
        self.stage = {"identity_errors": [], "product": {"product_version": "V1"},
            "review_label": "初步判断／待双审",
            "progress": {"completed": 60, "planned": 100, "percentage": 60, "plan_version": 2,
                "excluded": {"exempt": 10}, "by_scope_module": [{**scope, "completed": 15, "planned": 30,
                    "percentage": 50}]},
            "stage_risk": {"overall": {"stage_risk": "高", "display_grade": "阶段性高",
                "verification_status": "pending", "review_status": "pending", "confidence": None,
                "applicability": "current", "drivers": ["J1"]},
                "judgments": [{"event_id": "J1", "scope": scope, "stage_risk": "高",
                    "display_grade": "阶段性高", "review_status": "single_review_pending_09C",
                    "verification_status": "pending", "applicability": "current",
                    "assessment_date": "2026-09-25", "evidence_refs": ["E1"],
                    "comparison": "产品与权利逐项比较", "gaps": ["缺必要视角"]}], "signals": []},
            "work": {"entries": [{"work_id": "W1", "state": "ready", "reason": "待补视角",
                "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "design",
                "completion_condition": "补图后比较"}]},
            "progress_cutoff": {"source_run_count": 20},
            "grade_cutoff": {"stage_risk_event_count": 15, "stage_review_event_count": 0}}

    def build(self):
        with patch("stage_delivery_stage_d.build_model", return_value=copy.deepcopy(self.stage)):
            return self.fixture.build()

    def test_generic_name_label_reaches_stage_html_and_markdown_without_new_risk(self):
        self.fixture.task["retrieval_workflow_revision"] = "api-first-v3"
        self.fixture.task["product"]["brand"] = "Generic"
        before = copy.deepcopy(self.fixture.task)
        data, _ = self.build()
        for name in ("report.html", "report.md"):
            output = (self.fixture.out / name).read_text()
            self.assertIn("无风险（Generic 通用占位，仅名称项）", output)
            self.assertIn("自有品牌未评估", output)
        self.assertEqual(data["overall"]["risk"], "高")
        self.assertEqual(self.fixture.task, before)

    def test_sample_style_is_preserved_as_css_prefix(self):
        css = (Path(__file__).resolve().parent.parent / "assets/evidence-estimate-template.css").read_bytes()
        self.assertEqual(hashlib.sha256(css[:6116]).hexdigest(), SAMPLE_STYLE_SHA256)

    def test_10b_business_and_delivery_status_share_one_projection(self):
        self.fixture.task["business_status_revision"] = "business-status-stage-b-v1"
        data, manifest = self.build()
        status = data["business_status_stage_b"]
        self.assertEqual(status["business_status"], "continue")
        self.assertEqual(status["delivery_status"], "not_verified")
        self.assertEqual(manifest["business_status_stage_b"]["sha256"], _digest(status))
        self.assertIn("业务状态：继续处理", (self.fixture.out / "report.html").read_text())
        self.assertIn("交付状态：尚未核对实际可访问入口", (self.fixture.out / "report.md").read_text())
        rows = list(csv.DictReader(io.StringIO((self.fixture.out / "report-findings.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual(rows[0]["business_status"], "continue")
        self.assertEqual(rows[0]["delivery_status"], "not_verified")

    def test_eight_sections_five_columns_and_separate_progress_review_risk(self):
        data, manifest = self.build()
        page = (self.fixture.out / "report.html").read_text()
        self.assertEqual(page.count('<section id="'), 8)
        self.assertEqual(page.count('<th scope="col">'), 5)
        for phrase in ("限制与待办", "60/100", "阶段性高", "核实待评", "初步判断／待双审",
                       "待补视角", "产品与权利逐项比较", "缺对应权利图", "计划版本 2"):
            self.assertIn(phrase, page)
        self.assertEqual(data["presentation_stage_a"]["stage"]["progress"]["planned"], 100)
        self.assertIn('aria-valuenow="60"', page)
        self.assertNotIn("已审定高", page)
        self.assertEqual(data["overall"]["risk"], "高")
        self.assertIsNone(data["overall"]["confidence"])
        self.assertEqual(manifest["overall"]["risk"], "高")
        self.assertEqual(data["assessments"], [])
        self.assertIn("当前阶段风险：阶段性高", (self.fixture.out / "report.md").read_text())
        rows = list(csv.DictReader(io.StringIO((self.fixture.out / "report-findings.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual(rows[0]["stage_risk"], "高")
        self.assertEqual(rows[1]["candidate_id"], "D1")
        self.assertIn("D1", page)

    def test_unknown_candidate_count_and_empty_stage_are_not_filled(self):
        self.stage["progress"].update(completed=0, planned=0, percentage=None)
        self.stage["stage_risk"]["overall"].update(stage_risk=None, display_grade="尚无已审阶段等级",
            drivers=[])
        self.stage["stage_risk"]["judgments"] = []
        self.stage["work"]["entries"] = []
        self.stage["progress"]["by_scope_module"] = []
        self.build()
        page = (self.fixture.out / "report.html").read_text()
        self.assertIn("0/0（不可计算）", page)
        self.assertIn("尚无已审阶段等级", page)
        self.assertIn("当前无符合重点展示条件", page)
        self.assertNotIn('aria-valuenow="100"', page)

    def test_bad_global_binding_rejects_report(self):
        self.stage["identity_errors"] = ["PRODUCT_IDENTITY_MISSING"]
        with self.assertRaisesRegex(ValueError, "REPORT_PRESENTATION_IDENTITY_INVALID"):
            self.build()

    def test_suspended_high_is_not_current_risk_or_visual(self):
        self.stage["stage_risk"]["overall"].update(stage_risk=None,
            display_grade="当前待复核；上次等级：高（已暂停适用）", applicability="pending_recheck")
        self.stage["stage_risk"]["judgments"][0].update(applicability="suspended",
            display_grade="上次等级：高（已暂停适用）")
        data, manifest = self.build()
        page = (self.fixture.out / "report.html").read_text()
        self.assertIsNone(data["overall"]["risk"])
        self.assertIsNone(manifest["overall"]["risk"])
        self.assertIn("已暂停适用", page)
        self.assertIn("当前无符合重点展示条件", page)

    def test_future_signal_is_separate_from_current_risk(self):
        self.stage["stage_risk"]["signals"].append({"scope": {"scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent"}, "signal_type": "future_application",
            "signal_reasoning": "仅为公开申请", "applicability": "current"})
        data, _ = self.build()
        page = (self.fixture.out / "report.html").read_text()
        self.assertIn("已公开申请", page)
        self.assertIn("仅为公开申请", page)
        self.assertEqual(data["overall"]["risk"], "高")

    def test_same_candidate_in_two_scenarios_keeps_both_judgments(self):
        second = copy.deepcopy(self.stage["stage_risk"]["judgments"][0])
        second["event_id"] = "J2"
        second["scope"]["scenario_id"] = "brand_reuse"
        second["comparison"] = "另一情景的独立比较"
        self.stage["stage_risk"]["judgments"].append(second)
        self.build()
        page = (self.fixture.out / "report.html").read_text()
        self.assertEqual(page.count("<tr><td>D1</td>"), 2)
        self.assertIn("另一情景的独立比较", page)

    def test_user_material_without_asin_and_many_candidates(self):
        from report_estimate import render_html
        data, _ = self.build()
        data["product"].update(entry_type="user_materials", product_id="P-USER", asin="")
        data["presentation_stage_a"]["candidate_inventory"] = [
            {"candidate_id": f"C-{number:03}", "title": "长标题" * 20,
             "jurisdiction": "US", "right_type": "design", "scope_status": "included"}
            for number in range(80)]
        page = render_html(data, self.fixture.out)
        self.assertIn("用户提供的产品资料", page)
        self.assertIn("P-USER", page)
        self.assertNotIn("<span>ASIN</span>", page)
        self.assertEqual(page.count("<tr><td>C-"), 80)

    def test_changed_sample_style_prefix_blocks_new_presentation(self):
        with patch.object(Path, "read_bytes", return_value=b"changed"):
            with self.assertRaisesRegex(ValueError, "REPORT_PRESENTATION_SAMPLE_STYLE_CHANGED"):
                build_presentation(self.fixture.root, self.fixture.task, self.fixture.assessment, {})

    def test_current_triage_reason_reopen_and_family_members_reach_html_and_csv(self):
        candidate={'candidate_id':'D1','title':'具体外观','jurisdiction':'US','right_type':'design',
            'family_members':['US-D1','GB-D1']}
        self.fixture.assessment['coverage']['triage']={'records':[{'candidate_id':'D1',
            'scenario_id':'product_entry','jurisdiction':'US','right_type':'design',
            'current':False,'decision':'unreviewed','annotation':{'reason':'原入选原因','evidence_refs':['E1']},
            'reopen_reasons':['权利范围变化'],'next_actions':['回原待办复核']}], 'scope_dispositions':[]}
        with patch('stage_delivery_stage_d.build_model',return_value=copy.deepcopy(self.stage)):
            presentation=build_presentation(self.fixture.root,self.fixture.task,self.fixture.assessment,{'designs':[candidate]})
        inventory=presentation['candidate_inventory'][0]
        self.assertEqual(inventory['triage_status'],'pending_recheck')
        data,_=self.build();data['presentation_stage_a']['candidate_inventory']=presentation['candidate_inventory']
        from report_estimate import render_html
        from report_presentation_stage_a import render_csv
        page=render_html(data,self.fixture.out)
        # The risk row and current triage disposition remain separate state axes.
        self.assertIn('待复核',page);self.assertIn('US-D1',page);self.assertIn('GB-D1',page)
        self.assertIn('原入选原因',page);self.assertIn('权利范围变化',page)
        csv_text=render_csv(data)
        self.assertIn('权利范围变化',csv_text);self.assertIn('原入选原因',csv_text)

    def test_all_candidate_dispositions_survive_export_without_grades(self):
        data,_=self.build();data['presentation_stage_a']['stage']['stage_risk']['judgments']=[]
        data['presentation_stage_a']['candidate_inventory']=[{'candidate_id':f'C-{number}',
            'jurisdiction':'US','right_type':'design','scope_status':scope,'triage_status':triage,
            'triage_reasoning':'逐项真实理由'} for number,(scope,triage) in enumerate([
                ('out_of_scope','scope_not_assessed'),('included','selected'),('included','needs_info'),
                ('included','not_selected'),('included','pending_recheck')])]
        from report_estimate import render_html
        from report_presentation_stage_a import render_csv, render_markdown
        for text in (render_html(data,self.fixture.out),render_csv(data),render_markdown(data)):
            for label in ('入选','待补信息','不入选','待复核','范围未纳入处置'):
                self.assertIn(label,text)
            for number in range(5):self.assertIn(f'C-{number}',text)

    def test_shared_module_does_not_hide_unreviewed_trade_dress(self):
        self.stage['stage_risk']['judgments'][0]['scope']['right_type']='trademark_figurative'
        self.stage['stage_risk']['judgments'][0]['scope']['module_id']='figurative_trade_dress'
        self.build();page=(self.fixture.out/'report.html').read_text()
        self.assertIn('trademark_figurative',page)
        self.assertIn('商业外观：尚未形成当前判断',page)
        self.assertEqual(page.count('<article class="module">'),7)

    def test_supplied_search_similarity_is_not_infringement_probability(self):
        data,_=self.build();data['presentation_stage_a']['candidate_inventory']=[{'candidate_id':'D1',
            'jurisdiction':'US','right_type':'design','search_similarity':'0.91'}]
        from report_estimate import render_html
        page=render_html(data,self.fixture.out)
        self.assertIn('检索相似度：0.91',page)
        self.assertIn('来源检索指标，不代表侵权概率',page)

    def test_legacy_unmarked_report_keeps_existing_renderer(self):
        self.fixture.task.pop("report_presentation_revision")
        data, _ = self.fixture.build()
        page = (self.fixture.out / "report.html").read_text()
        self.assertNotIn("presentation_stage_a", data)
        self.assertIn("人工核查", page)
        self.assertNotIn('<th scope="col">', page)


if __name__ == "__main__":
    unittest.main()
