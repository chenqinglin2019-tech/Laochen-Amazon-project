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
            self.assertIn("尚未生成产品方向", text)
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
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
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
