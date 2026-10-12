from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "consumer_all_history_report.py"
TEMPLATE_PATH = SKILL_ROOT / "assets" / "consumer_all_history_report.template.html"

SPEC = importlib.util.spec_from_file_location("consumer_all_history_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
REPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REPORT
SPEC.loader.exec_module(REPORT)


def _analysis(image_path: Path) -> dict:
    semantic_labels = [label for _, label in REPORT.SEMANTIC_DEFINITIONS]
    return {
        "schema_version": "3.0.0-all-history",
        "metadata": {
            "generated_at": "2026-08-05T12:00:00+08:00",
            "source_db": "/private/run/collector.sqlite3",
            "source_db_sha256": "a" * 64,
            "mode": "all_history_local",
            "no_network": True,
            "date_filter_applied": False,
        },
        "project": {
            "marketplace": "US",
            "category_keyword": "车载手机支架",
        },
        "funnel": {
            "discovered_records": 32715,
            "hard_unique_records": 29111,
            "examined_records": 29111,
            "qualified_consumer_voices": 4850,
            "excluded_records": 24261,
            "platforms": {"youtube": 4500, "reddit": 250, "tiktok": 100},
        },
        "sample_structure": {
            "platform_distribution": {
                "youtube": 4500,
                "reddit": 250,
                "tiktok": 100,
            },
            "year_distribution": {"2024": 1200, "2025": 2100, "2026": 1550},
            "largest_single_video_share": 0.08,
            "largest_single_video_count": 388,
        },
        "semantic_categories": [
            {
                "code": code,
                "label": label,
                "count": 700 + index * 10,
                "share": 0.14 + index * 0.01,
                "authors": 600,
                "threads": 80,
                "platforms": 3,
                "top_topics": ["稳固", "兼容"],
                "representative_voices": [
                    {
                        "platform": "youtube",
                        "excerpt": f"用户原声 {index}",
                        "summary_zh": label,
                    }
                ],
            }
            for index, (code, label) in enumerate(REPORT.SEMANTIC_DEFINITIONS)
        ],
        "category_summary": {
            "needs": [
                {
                    "label": "更强的固定",
                    "count": 500,
                    "share": 500 / 4850,
                    "authors": 430,
                    "threads": 71,
                    "platforms": 3,
                }
            ],
            "satisfactions": [{"label": "单手取放", "count": 320, "share": 0.066}],
            "dissatisfactions": [{"label": "颠簸掉落", "count": 410, "share": 0.085}],
            "scenarios": ["重卡长途", "日常通勤"],
            "diy_workarounds": ["加扎带固定"],
            "innovations": ["可换车快拆底座"],
        },
        "top_segments": [
            {
                "segment_id": f"segment_{index}_all_history",
                "rank": index,
                "dimension": "夹持方式" if index == 1 else "车型适配",
                "feature": ["机械夹持", "卡车/重型车适用", "Tesla专用"][index - 1],
                "listing_share": 0.08,
                "sales_share": 0.12,
                "supply_demand_index": 1.5,
                "consumer_voice_count": 800 - index * 50,
                "needs": [{"label": "稳固", "count": 300}],
                "dissatisfactions": [{"label": "关节下垂", "count": 120}],
                "scenarios": ["粗糙路面"],
                "diy_workarounds": ["加垫片"],
                "innovations": ["隔振快拆"],
            }
            for index in range(1, 4)
        ],
        "kano": [
            {
                "need": "稳定固定",
                "kano_type": "必备型",
                "count": 500,
                "share": 0.103,
                "rationale": "缺失会导致设备掉落，产品应作为硬门槛。",
            },
            {
                "need": "主动散热",
                "kano_type": "魅力型",
                "count": 80,
                "share": 0.016,
            },
        ],
        "new_needs": [
            {
                "label": "重卡隔振快迁移",
                "type_label": "重复痛点推导",
                "count": 145,
                "share": 0.03,
                "consumer_problem": "换车和烂路时支架不稳定",
                "current_workaround": "扎带与双底座",
                "supply_gap": "极少同时覆盖隔振和快拆",
                "product_response": "模块轨和双级隔振",
            }
        ],
        "product_concepts": [
            {
                "concept_id": "concept_1",
                "name": "FleetRail X2",
                "segment_id": "segment_2_all_history",
                "target_consumers": ["重卡长途司机"],
                "jtbd": "在颠簸和换车时，让手机稳定、可见并能戴手套快拆。",
                "use_scenarios": ["油田土路", "车队换车"],
                "features": ["双级隔振", "戴手套快拆"],
                "technical_solution": "铝合金承力轨加双硬度弹性体。",
                "structure": "底座—隔振器—模块轨—设备坞。",
                "materials": ["6061-T6铝合金", "EPDM", "TPU"],
                "cmf": {
                    "colors": ["哑光黑", "安全橙"],
                    "finishes": ["硬质阳极氧化"],
                    "visual_language": "车队级工业感",
                },
                "target_price": {"currency": "USD", "min": 89, "max": 129},
                "bom_assumption": "目标BOM 28–42美元",
                "risks": ["隔振过软影响触控"],
                "dependencies": ["六款驾驶室实车验证"],
                "acceptance_metrics": [
                    {
                        "metric": "振动留置",
                        "target": "3g RMS 8小时零脱落",
                        "test_method": "三轴振动台",
                    }
                ],
                "design_thinking": {
                    "empathize": {"outputs": ["识别换车和颠簸冲突"]},
                    "define": {"outputs": ["定义稳定、触达、迁移三目标"]},
                    "ideate": {"outputs": ["双级隔振与快拆坞"]},
                    "prototype": {"outputs": ["三套低保真原型"]},
                    "test": {"outputs": ["振动与司机任务测试"]},
                    "iteration": {"outputs": ["按位移和任务时间迭代"]},
                },
                "moscow": {
                    "must": [{"feature": "机械留置", "reason": "防掉落"}],
                    "should": [{"feature": "多底座共用"}],
                    "could": [{"feature": "主动冷却"}],
                    "wont": [{"feature": "本版不做屏幕"}],
                },
                "image_prompt": {"prompt_text": "industrial truck phone mount"},
                "image_artifact": {"path": str(image_path), "status": "ok"},
            }
        ],
        "validation": {
            "checklist": [
                {
                    "validation_type": "重卡道路测试",
                    "status": "planned",
                    "objective": "验证极端振动留置",
                    "method": "六款驾驶室实车测试",
                    "acceptance_criteria": "8小时零脱落",
                    "owner_role": "结构工程师",
                }
            ]
        },
        "limitations": [
            {
                "scope": "样本边界",
                "description": "本地数据不等于互联网全量。",
                "mitigation": "后续按渠道继续扩充。",
            }
        ],
        "representative_voices": [
            {
                "platform": "reddit",
                "excerpt": "I need something that does not fall on rough roads.",
                "summary_zh": "消费者需要在粗糙路面保持稳定。",
            }
        ],
        "_semantic_labels_for_test": semantic_labels,
    }


def _finalizer_fixture(root: Path) -> dict[str, Path]:
    image = root / "concept.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nminimal-test-image")
    source_db = root / "collector.sqlite3"
    source_db.write_bytes(b"local-read-only-source-database")
    dashboard = root / "market_opportunity" / "市场机会深挖看板.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<html><body>opportunity</body></html>", encoding="utf-8")
    source_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
    dashboard_hash = hashlib.sha256(dashboard.read_bytes()).hexdigest()

    analysis = _analysis(image)
    analysis["metadata"]["source_db"] = str(source_db)
    analysis["metadata"]["source_db_sha256"] = source_hash
    analysis_path = root / "run" / "social_voice_all_history_analysis.json"
    analysis_path.parent.mkdir(parents=True)
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

    coding = {
        "schema_version": REPORT.SCHEMA_VERSION,
        "metadata": {
            "mode": "all_history_local_reprocess",
            "no_network": True,
            "date_filter_applied": False,
            "source_db": str(source_db),
            "source_db_sha256": source_hash,
        },
        "project": analysis["project"],
        "semantic_taxonomy": [
            {"code": code, "label": label}
            for code, label in REPORT.SEMANTIC_DEFINITIONS
        ],
        "funnel": analysis["funnel"],
        "voices": [],
        "excluded_records": [],
    }
    coding_path = analysis_path.with_name("social_voice_all_history_coding.json")
    coding_path.write_text(json.dumps(coding, ensure_ascii=False), encoding="utf-8")
    report_path = root / "market_opportunity" / "全历史报告.html"
    REPORT.render_report(
        analysis,
        analysis_path=analysis_path,
        template_path=TEMPLATE_PATH,
        output_path=report_path,
    )
    snapshot = {
        "schema_version": REPORT.SCHEMA_VERSION,
        "no_network": True,
        "source_db": str(source_db),
        "source_db_sha256": source_hash,
        "opportunity_dashboard": {
            "path": str(dashboard),
            "sha256": dashboard_hash,
        },
    }
    snapshot_path = analysis_path.with_name("source_snapshot.json")
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    manifest_path = root / "project_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "fixture-project",
                "artifacts": {
                    "market_opportunity_html": "market_opportunity/市场机会深挖看板.html",
                    "keep_me": "unchanged.bin",
                },
                "status": {"market_opportunity": "ready", "keep_me": "stable"},
                "sentinel": {"nested": [1, 2, 3]},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "image": image,
        "source_db": source_db,
        "dashboard": dashboard,
        "analysis": analysis_path,
        "coding": coding_path,
        "report": report_path,
        "snapshot": snapshot_path,
        "manifest": manifest_path,
    }


class AllHistoryReportTests(unittest.TestCase):
    def presentation_fixture(self, analysis: dict) -> dict:
        payload = REPORT.prepare_report_copy(analysis)
        payload['review_version'] = 'business-summary-test-1'
        for row in payload['product_directions']:
            row.update(status='待完成离体样机验证', operations='确认目标用户的真实任务与普通替代效果',
                       development='先测量接口和尺寸，再做非人体对照', decision='普通方案效果相当或退出失控时停止')
            row['benchmark'] = dict(existing='基础结构已确认，升级能力待核验', proposal='增加本案冻结定义的辅助机制',
                                    value='目标是降低完整任务负担，效果待验证', tradeoff='增加结构与维护成本，报价待确认',
                                    test='先验证样机，再与同等教学的普通方法比较', stop='普通方案等效或出现关键故障时停止',
                                    boundary='未知能力不作缺失，未测试优势不作性能承诺')
        return payload

    def test_report_copy_preserves_signed_concepts_and_rejects_stale_or_incomplete_data(self) -> None:
        analysis = _analysis(Path('/missing.png'))
        payload = self.presentation_fixture(analysis)
        result = REPORT.import_report_copy(analysis, payload)
        self.assertEqual(result['product_concepts'], analysis['product_concepts'])
        self.assertNotIn('report_presentation', analysis)
        changed = copy.deepcopy(analysis)
        changed['product_concepts'][0]['features'].append('新增未经原摘要审查的功能')
        with self.assertRaises(REPORT.ReportError): REPORT.import_report_copy(changed, payload)
        changed = copy.deepcopy(analysis)
        changed['competition_audit'] = {'concepts': [{'concept_id': analysis['product_concepts'][0]['concept_id'], 'benchmark': {'asin': 'CHANGED'}}]}
        with self.assertRaises(REPORT.ReportError): REPORT.import_report_copy(changed, payload)
        for bad in ('missing', 'duplicate', 'long', 'internal'):
            malformed = copy.deepcopy(payload)
            if bad == 'missing': malformed['product_directions'] = []
            elif bad == 'duplicate': malformed['product_directions'] *= 2
            elif bad == 'long': malformed['product_directions'][0]['decision'] = '长' * 221
            else: malformed['product_directions'][0]['operations'] = 'product_architect已记录完成'
            with self.subTest(bad=bad), self.assertRaises(REPORT.ReportError):
                REPORT.import_report_copy(analysis, malformed)

    def test_source_metrics_use_raw_and_valid_counts_independently_and_reject_bad_totals(self) -> None:
        analysis = {'processing_status': 'complete', 'funnel': {
            'hard_unique_records': 40, 'qualified_consumer_voices': 25, 'excluded_records': 12, 'pending_records': 3,
            'platforms': [{'platform': 'amazon', 'hard_unique_records': 12, 'qualified_consumer_voices': 8, 'excluded_records': 3, 'pending_records': 1},
                          {'platform': 'reddit', 'hard_unique_records': 20, 'qualified_consumer_voices': 13, 'excluded_records': 5, 'pending_records': 2},
                          {'platform': 'instagram', 'hard_unique_records': 8, 'qualified_consumer_voices': 4, 'excluded_records': 4, 'pending_records': 0}]}}
        counts = REPORT._front_source_counts(analysis)
        self.assertEqual(counts['amazon']['hard_unique_records'], 12)
        self.assertEqual(counts['offsite']['hard_unique_records'], 28)
        self.assertEqual(counts['offsite']['qualified_consumer_voices'], 17)
        analysis['funnel']['qualified_consumer_voices'] = 999
        self.assertIsNone(REPORT._front_source_counts(analysis)['offsite']['qualified_consumer_voices'])
        analysis['funnel']['platforms'].append(copy.deepcopy(analysis['funnel']['platforms'][0]))
        self.assertIsNone(REPORT._front_source_counts(analysis)['amazon']['hard_unique_records'])
        legacy = REPORT._front_source_counts({'funnel': {'platforms': {'Amazon': 8, 'reddit': 17}}})
        self.assertEqual(legacy['amazon']['qualified_consumer_voices'], 8)
        self.assertIsNone(legacy['offsite']['hard_unique_records'])

    def test_new_reports_have_per_direction_benchmarks_and_business_actions_without_parent_sales(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = _analysis(root/'missing.png')
            analysis['competition_audit'] = {'product_pool': {'product_count': 28}, 'concepts': []}
            concept = analysis['product_concepts'][0]
            concept['benchmark_reference'] = {'asin': 'B0TEST0001', 'brand': 'Test Brand', 'product_url': 'https://www.amazon.com/dp/B0TEST0001',
                'price': 6.75, 'sales': 25, 'child_revenue': 169, 'sales_rank': 2, 'sales_period': '冻结统计期', 'month_sales': 999999, 'month_revenue': 999999}
            concept['moscow_versions'] = {'research_prototype': {'version_goal': '研究版', 'items': [{'priority':'must','description':'先测量实际接口','acceptance_criteria':'签版后才能进入下一步'}]},
                'provisional_v1': {'version_goal':'待验证上市版','items':[{'priority':'wont','description':'本版不做自动化'}]}}
            result = REPORT.import_report_copy(analysis, self.presentation_fixture(analysis))
            text, receipt = self.render_fixture(root, result)
            body = text[text.index('<section class="report-section panel" id="concepts">'):text.index('<section class="report-section panel" id="method">')]
            self.assertEqual(body.count('class="br-benchmark"'), 1)
            self.assertLess(body.index('class="br-benchmark"'), body.index('class="br-review"'))
            self.assertNotIn('999999', body)
            self.assertIn('$169', body)
            self.assertIn('$6.75', body)
            self.assertIn('运营先确认', body)
            self.assertIn('先测量接口和尺寸', body)
            self.assertNotIn('<table', body)
            self.assertNotIn('多角色产品讨论', body)
            self.assertEqual(body.count('class="prd-version"'), 2)
            self.assertIn('prd-evidence-two', body)
            self.assertIn('prd-decision-two', body)
            self.assertIn('prd-process prd-two-column', body)
            self.assertLess(text.index('id="funnel"'), text.index('class="vf-kpis"'))
            self.assertEqual(text.count('id="funnel"'), 1)
            self.assertEqual(receipt['template_version'], '1.5.0')
            changed = copy.deepcopy(result)
            changed['product_concepts'][0]['benchmark_reference']['child_revenue'] = 170
            with self.assertRaises(REPORT.ReportError): self.render_fixture(root, changed)

    def test_new_render_rejects_old_template_but_existing_report_remains_checkable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); analysis = _analysis(root/'missing.png')
            current, _ = self.render_fixture(root, analysis)
            historical = current.replace('all-history-report-template-version" content="1.5.0"', 'all-history-report-template-version" content="1.4.0"')
            self.assertEqual(REPORT.validate_report_html(historical), [])
            old = root/'old.template.html'
            old.write_text(TEMPLATE_PATH.read_text().replace('content="1.5.0"', 'content="1.4.0"'))
            with self.assertRaises(REPORT.ReportError):
                REPORT.render_report(analysis, analysis_path=root/'analysis.json', template_path=old, output_path=root/'old.html')

    def render_fixture(self, root: Path, analysis: dict) -> tuple[str, dict]:
        analysis_path = root / "analysis.json"
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        output = root / "report.html"
        receipt = REPORT.render_report(
            analysis, analysis_path=analysis_path, template_path=TEMPLATE_PATH, output_path=output,
        )
        return output.read_text(encoding="utf-8"), receipt

    def test_fixed_front_uses_current_counts_and_keeps_unknowns_unassessed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = _analysis(root / "missing.png")
            analysis["product_concepts"] = []
            analysis["project"]["category_keyword"] = "咖啡杯"
            text, receipt = self.render_fixture(root, analysis)
            front = text[text.index('<header class="hero voc-front-hero"'):text.index('<section class="report-section panel" id="semantics">')]
            self.assertEqual(receipt["template_version"], "1.5.0")
            self.assertIn('<h1>咖啡杯</h1>', front)
            self.assertIn('<strong>4,850</strong>', front)
            self.assertIn('未提供采集范围', front)
            self.assertIn('未提供经过核对的评论适用性分层', front)
            self.assertIn('未提供检查记录', front)
            self.assertNotIn('本轮检查已通过', front)
            self.assertNotIn('1,822', front)
            self.assertNotIn('马蹄形鼻饰', front)
            self.assertIn('<details class="vf-audit">', front)
            self.assertNotIn('<details class="vf-audit" open', front)
            self.assertEqual(REPORT.validate_report_html(text), [])

    def test_front_layers_and_coverage_reject_inconsistent_counts(self) -> None:
        analysis = {
            'funnel': {'qualified_consumer_voices': 10, 'platforms': [
                {'platform': 'amazon', 'qualified_consumer_voices': 8, 'hard_unique_records': 12},
                {'platform': 'reddit', 'qualified_consumer_voices': 2}]},
            'report_front': {
                'sampling': {'successful': 3, 'candidates': 4, 'failed': 1},
                'amazon_evidence_layers': {'at_least_one_current_need': 3,
                    'only_unknown_or_historical_needs': 4, 'no_specific_need_general_or_comparison': 1}},
        }
        self.assertIn('37.5%', REPORT._render_front_layers(analysis))
        self.assertIn('3<span class="vf-kpi-denom"> / 4', REPORT._render_front_metrics(analysis))
        analysis['report_front']['sampling']['successful'] = 4
        analysis['report_front']['amazon_evidence_layers']['at_least_one_current_need'] = 4
        self.assertIn('未提供采集范围', REPORT._render_front_metrics(analysis))
        self.assertIn('未提供经过核对', REPORT._render_front_layers(analysis))
        analysis['report_front']['sampling']['successful'] = None
        self.assertIn('未提供采集范围', REPORT._render_front_metrics(analysis))

    def test_front_does_not_promote_ineligible_needs_or_unchecked_quality(self) -> None:
        analysis = {'processing_status': 'pending_review', 'funnel': {'qualified_consumer_voices': 20},
                    'evidence_readiness': {'status': 'partial', 'needs': [
                        {'need_id': 'unqualified', 'label': '不适用的结构需求', 'count': 20, 'eligible': False}]}}
        text = REPORT._render_decision(analysis)
        self.assertNotIn('不适用的结构需求', text)
        self.assertIn('存在尚未完成复核的记录', text)
        self.assertIn('未提供检查记录', text)
        self.assertNotIn('已通过本轮检查', text)
        self.assertNotIn('进入产品体验验证', text)
        analysis.update(processing_status='completed', coding_review={'unreviewed_records': 1})
        text = REPORT._render_decision(analysis)
        self.assertIn('存在尚未完成复核的记录', text)
        self.assertNotIn('全量处理完成', text)

    def test_zero_recommendations_is_a_complete_partial_evidence_report_without_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _finalizer_fixture(root)
            analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
            analysis.update({
                "product_concepts": [],
                "processing_status": "complete",
                "evidence_readiness": {
                    "status": "partial",
                    "checks": [{"code": "segment", "label": "细分方向样本", "passed": False, "observed": 750, "required": 1000}],
                    "gaps": ["优先细分需要补充安装场景原声"],
                },
            })
            paths["analysis"].write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            receipt = REPORT.render_report(
                analysis, analysis_path=paths["analysis"], template_path=TEMPLATE_PATH, output_path=paths["report"],
            )
            text = paths["report"].read_text(encoding="utf-8")
            self.assertEqual(receipt["embedded_image_count"], 0)
            self.assertEqual(receipt["recommended_concept_count"], 0)
            self.assertEqual(receipt["processing_status"], "complete")
            self.assertEqual(receipt["evidence_status"], "partial")
            self.assertIn("处理完成", text)
            self.assertIn("仍有证据缺口", text)
            self.assertIn("正式推荐产品方向</span>", text)
            self.assertIn("（0 个）</span>", text)
            self.assertIn("优先细分需要补充安装场景原声", text)
            self.assertNotIn("达到本轮证据门槛", text)
            self.assertNotIn("概念图尚未提供", text)
            finalized = REPORT.finalize_manifest(
                manifest_path=paths["manifest"], coding_path=paths["coding"],
                analysis_path=paths["analysis"], report_path=paths["report"],
                source_db_path=paths["source_db"], dashboard_path=paths["dashboard"],
                status="partial", source_snapshot_path=paths["snapshot"],
            )
            self.assertEqual(finalized["consumer_voice_all_history"], "partial")

    def test_readiness_and_pending_finalization_gates_do_not_require_concepts_or_images(self) -> None:
        cases = (
            ("partial_evidence", {"evidence_readiness": {"status": "partial"}}, False),
            ("pending_review", {"evidence_readiness": {"status": "sufficient"}, "coding_review": {"pending": 1}}, False),
            ("provisional", {"evidence_readiness": {"status": "sufficient"}, "coding_review": {"rule_provisional": 1}}, False),
            ("coverage_gap", {"evidence_readiness": {"status": "sufficient"}, "coding_review": {"coverage": 0.9}}, False),
            ("rounded_coverage_gap", {"evidence_readiness": {"status": "sufficient"}, "coding_review": {"coverage": 1.0, "unreviewed_records": 1}}, False),
            ("ready_zero_concepts", {"evidence_readiness": {"status": "sufficient"}, "coding_review": {"coverage": 1.0, "pending": 0, "rule_provisional": 0}}, True),
        )
        for name, additions, allowed in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                paths = _finalizer_fixture(Path(temporary))
                analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
                analysis.update({"product_concepts": [], "processing_status": "complete", **additions})
                paths["analysis"].write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
                REPORT.render_report(analysis, analysis_path=paths["analysis"], template_path=TEMPLATE_PATH, output_path=paths["report"])
                before = paths["manifest"].read_bytes()
                kwargs = {
                    "manifest_path": paths["manifest"], "coding_path": paths["coding"],
                    "analysis_path": paths["analysis"], "report_path": paths["report"],
                    "source_db_path": paths["source_db"], "dashboard_path": paths["dashboard"],
                    "status": "ready", "source_snapshot_path": paths["snapshot"],
                }
                if allowed:
                    self.assertEqual(REPORT.finalize_manifest(**kwargs)["consumer_voice_all_history"], "ready")
                else:
                    with self.assertRaises(REPORT.ReportError):
                        REPORT.finalize_manifest(**kwargs)
                    self.assertEqual(paths["manifest"].read_bytes(), before)

    def test_legacy_missing_evidence_is_unassessed_and_missing_need_is_not_invented(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = _analysis(root / "missing.png")
            analysis["product_concepts"] = []
            analysis["category_summary"] = {}
            analysis["project"]["category_keyword"] = "咖啡杯"
            text, receipt = self.render_fixture(root, analysis)
            self.assertIn("尚未评估", text)
            self.assertIn("处理完成不代表证据充分", text)
            self.assertNotIn("稳定固定与安全使用", text)
            self.assertNotIn("优先围绕", text)
            self.assertEqual(receipt["evidence_status"], "not_assessed")
            self.assertEqual(REPORT.validate_report_html(text.replace('content="1.1.0"', 'content="1.0.0"')), [])

    def test_collection_modes_costs_source_layers_and_secrets_allowlist(self) -> None:
        for mode in ("free", "scrapecreators", ""):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                analysis = _analysis(root / "missing.png")
                analysis["product_concepts"] = []
                analysis["collection_summary"] = {
                    "collection_mode": mode, "credits_limit": 6250,
                    "credits_used": 1700, "estimated_cost_usd": 3.196,
                    "api_key": "SENSITIVE_SENTINEL_KEY", "error": "SENSITIVE_SENTINEL_ERROR",
                }
                analysis["source_breakdown"] = [
                    {"source_kind": kind, "count": count, "share": count / 1000, "known_authors": 0, "contexts": 4, "top_topics": [{"label": topic, "count": 10}]}
                    for kind, count, topic in (("social", 600, "日常使用"), ("review", 300, "商品耐用性"), ("after_sales", 100, "退货原因"))
                ]
                text, _ = self.render_fixture(root, analysis)
                for label in ("社媒讨论", "商品评价", "售后与退货", "商品耐用性", "退货原因"):
                    self.assertIn(label, text)
                self.assertIn("已知作者 0 位", text)
                self.assertIn("地域未知的相关评论仍可纳入", text)
                self.assertNotIn("SENSITIVE_SENTINEL", text)
                self.assertNotIn("api_key", text)
                self.assertNotIn("source_kind", text)
                if mode == "free":
                    self.assertIn("本次新增数据接口费用：0", text)
                    self.assertNotIn("$3.20", text)
                elif mode == "scrapecreators":
                    self.assertIn("用户自备 ScrapeCreators", text)
                    self.assertIn("6,250 credits", text)
                    self.assertIn("$3.20", text)
                    self.assertIn("折算消耗不等于套餐购买金额", text)
                else:
                    self.assertIn("未记录采集方式", text)
                    self.assertNotIn("本次新增数据接口费用：0", text)
                self.assertEqual(REPORT.validate_report_html(text), [])

    def test_needs_show_counterevidence_applicability_and_pending_without_exposing_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = _analysis(root / "missing.png")
            analysis["product_concepts"] = []
            analysis["funnel"]["pending_records"] = 12
            analysis["coding_review"] = {"agent_reviewed": 100, "rule_provisional": 34, "pending": 12}
            analysis["evidence_readiness"] = {
                "status": "partial", "saturation": {"status": "insufficient_batches", "batches": [{"batch_id": "PRIVATE_BATCH", "new_valid_voices": 200, "new_topics": 1, "new_topic_ratio": 0.04, "stable_top_topics": 8, "passed": True}]},
                "needs": [{
                    "label": "兼容厚手机壳", "eligible": False,
                    "known_authors": 12, "contexts": 3, "channels": 1,
                    "support_refs": ["PRIVATE_SUPPORT_REF"], "counter_refs": ["PRIVATE_COUNTER_REF"],
                    "alternative_explanations": ["问题可能来自安装方向，而非夹持宽度"],
                    "applicability": {"current": ["PRIVATE_MODEL_REF"], "historical": [], "unknown": ["PRIVATE_UNKNOWN_REF"]},
                }],
            }
            analysis["evidence_excerpt_index"] = {
                "PRIVATE_SUPPORT_REF": {"platform": "reddit", "excerpt": "My thick case does not fit."},
                "PRIVATE_COUNTER_REF": {"platform": "reddit", "excerpt": "A wider clamp would block my button."},
            }
            text, _ = self.render_fixture(root, analysis)
            for expected in ("待语义复核", "合格增量批次不足"):
                self.assertIn(expected, text)
            self.assertNotIn("兼容厚手机壳", text)
            self.assertNotIn("My thick case does not fit.", text)
            self.assertNotIn("PRIVATE_", text)
            self.assertNotIn("support_refs", text)
            self.assertNotIn("counter_refs", text)
            self.assertIn("最近三个增量批次的主题变化", text)
            self.assertIn("4.0%", text)

    def test_need_semantic_summaries_are_evidence_bound_and_replace_legacy_caveats(self) -> None:
        analysis = _analysis(Path("/tmp/semantic-summary.png"))
        analysis["product_concepts"] = []
        analysis["evidence_readiness"] = {
            "status": "sufficient",
            "needs": [{
                "need_id": "need_install_clear",
                "label": "清晰的首次安装",
                "eligible": True,
                "related_count": 20,
                "known_authors": ["author-1"],
                "contexts": ["context-1"],
                "channels": ["amazon"],
                "support_refs": ["voice-1"],
                "counter_refs": ["voice-2"],
                "alternative_explanations": ["不应在报告正文显示的替代解释"],
                "applicability": {"current": ["voice-1"], "historical": [], "unknown": ["voice-2"]},
            }],
        }
        analysis["evidence_excerpt_index"] = {
            "voice-1": {"record_id": "voice-1", "excerpt": "I could not tell which part to install first."},
            "voice-2": {"record_id": "voice-2", "excerpt": "The instructions were clear for me."},
        }
        prepared = REPORT.prepare_need_semantic_summaries(analysis)
        self.assertEqual(prepared["needs"][0]["need_id"], "need_install_clear")
        imported = REPORT.import_need_semantic_summaries(analysis, {
            "schema_version": "consumer-need-semantic-summaries-1.0",
            "needs": [{
                "need_id": "need_install_clear",
                "source_sha256": prepared["needs"][0]["source_sha256"],
                "summary": "消费者需要减少首次装配时对方向、顺序和完成状态的猜测。",
                "need_statement": "让首次安装者能确认关键部件方向和连接是否到位。",
                "evidence_ids": ["voice-1", "voice-2"],
                "review_version": "need-semantic-1.0",
            }],
        })
        with tempfile.TemporaryDirectory() as temporary:
            text, _ = self.render_fixture(Path(temporary), imported)
        self.assertIn("消费者声音语义总结", text)
        self.assertIn("让首次安装者能确认关键部件方向", text)
        self.assertIn("证据使用边界", text)
        self.assertNotIn("不应在报告正文显示的替代解释", text)
        self.assertNotIn("voice-1", text)

    def test_cumulative_paid_cost_remains_visible_after_switching_to_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = _analysis(root / "missing.png")
            analysis["product_concepts"] = []
            analysis["collection_summary"] = {
                "collection_mode": "free",
                "acquisition_budget": {
                    "credits_cap": 6250, "committed_credits": 200,
                    "uncertain_credits": 10, "estimated_cost_usd": 0.36,
                    "accounting_scope": "task_cumulative_including_prior_resumes",
                    "price_basis": "PRIVATE_PRICE_AUDIT_VALUE",
                },
            }
            text, _ = self.render_fixture(root, analysis)
            self.assertIn("本次新增数据接口费用：0", text)
            self.assertIn("历史运行与续采累计", text)
            self.assertIn("$0.36", text)
            self.assertIn("计费待确认 10 credits", text)
            self.assertNotIn("PRIVATE_PRICE_AUDIT_VALUE", text)

    def test_product_evidence_is_visible_and_runtime_details_stay_in_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nminimal-test-image")
            analysis = _analysis(image)
            concept = analysis["product_concepts"][0]
            concept["feature_evidence"] = [
                {"feature": "自适应夹爪", "origin": origin, "voice_ids": ["PRIVATE_REF"], "reasoning": "原声指出厚壳难以装入", "validation_plan": "比较三种壳厚的安装成功率"}
                for origin in ("consumer_explicit", "evidence_inference", "design_hypothesis")
            ]
            concept["supporting_evidence"] = [{"raw_excerpt": "I need space for my rugged case."}]
            concept["cmf"] = {"color": "森林绿", "finish": "细砂纹"}
            concept["counterevidence"] = [{"excerpt": "The bigger mount blocks the vent."}]
            concept["acceptance_metrics"][0].update({"test_object": "三款常见厚壳", "failure_condition": "任一设备脱落"})
            concept["bom_estimate"] = {"currency": "USD", "min": 4, "max": 6, "basis": "engineering_estimate", "assumptions": ["按一万件注塑估算"]}
            concept["acceptance_metrics"][0]["test_subjects"] = "三款常见厚壳"
            exploration = copy.deepcopy(concept)
            exploration.update({"concept_id": "explore_1", "name": "换车快拆探索", "image_artifact": None})
            analysis["exploration_concepts"] = [exploration]
            analysis["development"] = {
                "status": "reviewed", "execution_mode": "subagents",
                "roles": [{"role": "creative", "label": "大胆创意者", "agent_id": "PRIVATE_AGENT"}],
                "rounds_completed": ["ideate", "merge", "review", "revise", "select"],
                "candidate_count": 6, "recommended_count": 1, "exploration_count": 1,
            }
            text, receipt = self.render_fixture(root, analysis)
            for expected in ("消费者直接提出", "根据证据推导", "尚待验证的创意", "原声指出厚壳难以装入", "比较三种壳厚的安装成功率", "三款常见厚壳", "任一设备脱落", "按一万件注塑估算", "探索性创意:尚待验证", "换车快拆探索"):
                self.assertIn(expected, text)
            self.assertNotIn("PRIVATE_", text)
            self.assertIn("森林绿", text)
            self.assertIn("细砂纹", text)
            self.assertNotIn("绑定 Top1 细分", text)
            self.assertEqual(receipt["recommended_concept_count"], 1)
            self.assertEqual(receipt["exploration_concept_count"], 1)
            analysis["development"]["execution_mode"] = "role_simulation"
            simulated, _ = self.render_fixture(root, analysis)
            self.assertIn("开发评审结论与下一步", simulated)
            self.assertNotIn("大胆创意者", simulated)
            self.assertNotIn("独立子智能体参与", simulated)

    def test_four_formal_recommendations_are_rejected_instead_of_silently_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = _analysis(root / "missing.png")
            analysis["product_concepts"] *= 4
            with self.assertRaises(REPORT.ReportError):
                self.render_fixture(root, analysis)
            self.assertFalse((root / "report.html").exists())

    def test_public_labels_and_effective_platform_count_are_consumer_facing(self) -> None:
        self.assertEqual(
            "关键必备型/期望型/魅力型分类",
            REPORT._public_text("关键Must/One-dimensional/Attractive分类"),
        )
        self.assertEqual(
            (1, ["Youtube"]),
            REPORT._platform_summary(
                [
                    {"platform": "youtube", "qualified_consumer_voices": 12},
                    {"platform": "instagram", "qualified_consumer_voices": 0},
                ]
            ),
        )

    def test_render_is_offline_chinese_and_hides_internal_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nminimal-test-image")
            analysis = _analysis(image)
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            output = root / "report.html"

            receipt = REPORT.render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=TEMPLATE_PATH,
                output_path=output,
            )

            self.assertEqual(receipt["status"], "ok")
            self.assertEqual(receipt["embedded_image_count"], 1)
            self.assertTrue(receipt["standalone_html"])
            self.assertEqual(receipt["external_runtime_dependencies"], 0)
            text = output.read_text(encoding="utf-8")
            lowered = text.casefold()
            self.assertIn("data:image/png;base64,", text)
            self.assertIn("购买、选型和推荐", text)
            self.assertIn("故障、抱怨、退货和替代", text)
            self.assertIn("新功能、反向需求和创意", text)
            self.assertIn("必备型", text)
            self.assertIn("主动散热", text)
            self.assertIn("魅力型", text)
            self.assertIn("发现关系", text)
            self.assertIn("最大单视频贡献", text)
            self.assertIn("全历史定义", text)
            self.assertIn("阶段性:证据状态尚未评估", text)
            self.assertIn("细分市场声音", text)
            self.assertIn("产品机会与开发", text)
            self.assertIn("不等于互联网或平台的全部历史留言", text)
            self.assertIn("YouTube清洗", text)
            self.assertIn("@media print", text)
            self.assertIn("@media (max-width: 680px)", text)
            self.assertNotIn("<script", lowered)
            self.assertNotIn("src=\"http", lowered)
            self.assertNotIn(str(image), text)
            for forbidden in REPORT.FORBIDDEN_VISIBLE_TERMS:
                self.assertNotIn(forbidden.casefold(), lowered)
            self.assertEqual(REPORT.validate_report_html(text), [])

    def test_missing_optional_sections_render_as_empty_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = {
                "schema_version": "3.0.0-all-history",
                "metadata": {
                    "no_network": True,
                    "date_filter_applied": False,
                    "source_db_sha256": "a" * 64,
                },
                "project": {"marketplace": "US", "category_keyword": "测试商品"},
                "funnel": {},
                "kano": [],
            }
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            output = root / "report.html"
            REPORT.render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=TEMPLATE_PATH,
                output_path=output,
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("暂无Top3细分数据", text)
            self.assertIn("尚未形成正式推荐产品方向", text)
            self.assertEqual(REPORT.validate_report_html(text), [])

    def test_values_are_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            analysis = {
                "schema_version": "3.0.0-all-history",
                "metadata": {
                    "no_network": True,
                    "date_filter_applied": False,
                    "source_db_sha256": "a" * 64,
                },
                "project": {
                    "marketplace": "US",
                    "category_keyword": "<img src=https://bad.invalid/x onerror=alert(1)>",
                },
                "funnel": {},
                "representative_voices": [
                    {"platform": "test", "excerpt": "<script>alert(1)</script>"}
                ],
                "kano": [],
            }
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            output = root / "report.html"
            REPORT.render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=TEMPLATE_PATH,
                output_path=output,
            )
            text = output.read_text(encoding="utf-8")
            self.assertNotIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
            self.assertNotIn("<script>alert(1)</script>", text)
            self.assertNotIn("src=\"https://bad.invalid", text)
            self.assertEqual(REPORT.validate_report_html(text), [])

    def test_render_rejects_non_all_history_contracts_and_non_chinese_kano(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nminimal-test-image")
            valid = _analysis(image)
            invalid_cases = {
                "wrong schema": ("schema_version", "2.0.0"),
                "network enabled": ("metadata.no_network", False),
                "date filtering enabled": ("metadata.date_filter_applied", True),
                "legacy kano": ("kano.0.kano_type", "evidence_insufficient"),
                "english kano": ("kano.0.kano_type", "must"),
                "nested legacy kano": (
                    "category_summary.kano",
                    [{"need": "旧分类", "kano_type": "evidence_insufficient"}],
                ),
            }
            for name, (path, value) in invalid_cases.items():
                with self.subTest(name=name):
                    analysis = copy.deepcopy(valid)
                    if path == "schema_version":
                        analysis[path] = value
                    elif path.startswith("metadata."):
                        analysis["metadata"][path.split(".", 1)[1]] = value
                    elif path == "category_summary.kano":
                        analysis["category_summary"]["kano"] = value
                    else:
                        analysis["kano"][0]["kano_type"] = value
                    analysis_path = root / f"{name.replace(' ', '_')}.json"
                    analysis_path.write_text(
                        json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
                    )
                    output = root / f"{name.replace(' ', '_')}.html"
                    with self.assertRaises(REPORT.ReportError):
                        REPORT.render_report(
                            analysis,
                            analysis_path=analysis_path,
                            template_path=TEMPLATE_PATH,
                            output_path=output,
                        )
                    self.assertFalse(output.exists())

    def test_legacy_internal_fields_are_cleaned_from_visible_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nminimal-test-image")
            analysis = _analysis(image)
            analysis["representative_voices"][0].update(
                {
                    "evidence_id": "voice_legacy_1",
                    "source_status": "partial",
                    "confidence": "low",
                }
            )
            analysis["product_concepts"][0]["segment_id"] = "segment_2_90d"
            analysis["product_concepts"][0]["technical_solution"] = (
                "segment_2_90d 使用铝合金承力轨加双硬度弹性体。"
            )
            analysis["limitations"][0]["description"] = (
                "旧字段 confidence、source_status 和 evidence_id 仅用于审计。"
            )
            analysis_path = root / "legacy-analysis.json"
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            output = root / "legacy-report.html"

            REPORT.render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=TEMPLATE_PATH,
                output_path=output,
            )

            text = output.read_text(encoding="utf-8")
            lowered = text.casefold()
            self.assertIn("Top2细分", text)
            for forbidden in REPORT.FORBIDDEN_VISIBLE_TERMS:
                self.assertNotIn(forbidden.casefold(), lowered)
            self.assertEqual(REPORT.validate_report_html(text), [])

    def test_finalize_manifest_cli_preserves_existing_keys_and_adds_only_all_history_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _finalizer_fixture(Path(temporary))
            before = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "finalize-manifest",
                    "--manifest",
                    str(paths["manifest"]),
                    "--coding",
                    str(paths["coding"]),
                    "--analysis",
                    str(paths["analysis"]),
                    "--report",
                    str(paths["report"]),
                    "--source-db",
                    str(paths["source_db"]),
                    "--dashboard",
                    str(paths["dashboard"]),
                    "--source-snapshot",
                    str(paths["snapshot"]),
                    "--status",
                    "ready",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "updated")
            after = json.loads(paths["manifest"].read_text(encoding="utf-8"))

            self.assertEqual(after["schema_version"], before["schema_version"])
            self.assertEqual(after["project_id"], before["project_id"])
            self.assertEqual(after["sentinel"], before["sentinel"])
            self.assertEqual(
                after["artifacts"]["market_opportunity_html"],
                before["artifacts"]["market_opportunity_html"],
            )
            self.assertEqual(
                after["artifacts"]["keep_me"], before["artifacts"]["keep_me"]
            )
            self.assertEqual(
                after["status"]["market_opportunity"],
                before["status"]["market_opportunity"],
            )
            self.assertEqual(after["status"]["keep_me"], before["status"]["keep_me"])
            self.assertEqual(after["status"]["consumer_voice_all_history"], "ready")
            self.assertEqual(
                set(after["artifacts"]) - set(before["artifacts"]),
                {
                    "consumer_voice_all_history_coding",
                    "consumer_voice_all_history_analysis",
                    "consumer_voice_all_history_report_html",
                },
            )

    def test_finalize_manifest_validation_failure_never_writes_manifest(self) -> None:
        mutators = {
            "source database changed": lambda paths: paths["source_db"].write_bytes(
                b"changed-source-database"
            ),
            "dashboard changed": lambda paths: paths["dashboard"].write_text(
                "<html>changed</html>", encoding="utf-8"
            ),
            "analysis changed after render": lambda paths: paths["analysis"].write_text(
                paths["analysis"].read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            ),
        }
        for name, mutate in mutators.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                paths = _finalizer_fixture(Path(temporary))
                manifest_before = paths["manifest"].read_bytes()
                mutate(paths)
                with self.assertRaises(REPORT.ReportError):
                    REPORT.finalize_manifest(
                        manifest_path=paths["manifest"],
                        coding_path=paths["coding"],
                        analysis_path=paths["analysis"],
                        report_path=paths["report"],
                        source_db_path=paths["source_db"],
                        dashboard_path=paths["dashboard"],
                        status="partial",
                        source_snapshot_path=paths["snapshot"],
                    )
                self.assertEqual(paths["manifest"].read_bytes(), manifest_before)

    def test_cli_render_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nminimal-test-image")
            analysis_path = root / "analysis.json"
            analysis_path.write_text(
                json.dumps(_analysis(image), ensure_ascii=False), encoding="utf-8"
            )
            output = root / "report.html"
            render = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "render",
                    "--analysis",
                    str(analysis_path),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(render.returncode, 0, render.stderr)
            receipt = json.loads(render.stdout)
            self.assertEqual(receipt["report_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            check = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "check", "--report", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertEqual(json.loads(check.stdout)["errors"], [])


if __name__ == "__main__":
    unittest.main()
