from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.sax.saxutils
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "tools" / "niche_recommendation.py"
SPEC = importlib.util.spec_from_file_location("niche_recommendation", MODULE_PATH)
assert SPEC and SPEC.loader
niche = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(niche)


def _column_name(index: int) -> str:
    value = index + 1
    output = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        output = chr(ord("A") + remainder) + output
    return output


def _xlsx(path: Path, sheet_name: str, rows: list[list[object]]) -> None:
    rendered_rows: list[str] = []
    for row_number, values in enumerate(rows, start=1):
        cells: list[str] = []
        for index, value in enumerate(values):
            reference = f"{_column_name(index)}{row_number}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                escaped = xml.sax.saxutils.escape(str(value))
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>'
                )
        rendered_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{xml.sax.saxutils.escape(sheet_name)}" sheetId="1" r:id="rId1"/>'
        '</sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rendered_rows)}</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


class NicheRecommendationIntegrationTests(unittest.TestCase):
    def _build_project(self, root: Path) -> tuple[Path, Path, Path]:
        project = root / "market_project_fixture"
        research = project / "market_research"
        opportunity = project / "market_opportunity"
        research.mkdir(parents=True)
        opportunity.mkdir()
        keyword_file = project / "keywords.xlsx"
        poe_file = project / "poe.xlsx"
        _xlsx(keyword_file, "关键词", [["关键词", "月搜索量", "月购买量", "PPC竞价"], ["truck phone mount", 500, 50, "$2.00"]])
        _xlsx(
            poe_file,
            "细分市场列表",
            [
                [
                    "细分市场名称", "细分市场分类1", "搜索量-近90天", "销量-近90天", "点击转化率-近90天 (%)", "平均售价-近90天 ($)",
                    "前5商品点击占比-近90天 (%)", "前5商品点击占比-近360天 (%)", "前5品牌点击占比-近90天 (%)", "前5品牌点击占比-近360天 (%)",
                    "退货率-近360天 (%)", "新品发布数-360天", "成功发布数-360天",
                    "搜索量增长率-近90天 (%)", "搜索量增长率-近180天 (%)", "搜索量增长率-近360天 (%)", "建议出价 ($)",
                ],
                ["Truck phone mount", "Vehicle fit", 1000, 200, "20%", "$20", "30%", "35%", "40%", "45%", "2%", 8, 8, "10%", "20%", "30%", "$99.00"],
                ["Cup holder phone accessory", "Accessory", 100, 10, "10%", "$10", "60%", "60%", "60%", "60%", "4%", 1, 0, "-5%", "-3%", "2%", "$0.01"],
            ],
        )

        rows = []
        tags = []
        for index in range(10):
            asin = f"B0TEST{index:04d}"
            rows.append(
                {
                    "asin": asin,
                    "title": f"Truck mount {index}",
                    "brand": f"Brand {index % 3}",
                    "price": 20 + index,
                    "monthly_sales": 100 + index,
                    "monthly_revenue": (100 + index) * (20 + index),
                    "parent_asin": f"PARENT{index:04d}",
                    "product_url": f"https://www.amazon.com/dp/{asin}",
                    "month": "2026-09",
                    "launch_days": 120,
                    "review_count": index * 10,
                    "rating": 4.1 + index / 10,
                }
            )
            tags.append(
                {
                    "asin": asin,
                    "normalized_values": {"车型适配": ["truck_heavy_duty"]},
                    "display_values": {"车型适配": ["卡车/重型车"]},
                }
            )
        (project / "project_manifest.json").write_text(
            json.dumps({"project_id": "market_project_fixture", "marketplace": "US", "artifacts": {}, "status": {}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (research / "cleaned_30d_listings.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
        (research / "01_input_manifest.json").write_text(json.dumps({"keyword_file": "keywords.xlsx", "monthly_files": []}, ensure_ascii=False), encoding="utf-8")
        (opportunity / "agent_listing_tags.json").write_text(json.dumps({"tags": tags}, ensure_ascii=False), encoding="utf-8")
        (opportunity / "07_opportunity_analysis.json").write_text("{}", encoding="utf-8")
        (opportunity / "市场机会深挖看板.html").write_text(
            '<html><head><title>fixture</title></head><body><nav><a href="#formal">组合明细</a><a href="#small">小样本观察</a></nav><main class="content"><h2 id="formal">正式机会组合明细</h2><details><summary>old</summary></details><h2 id="small">小样本观察</h2></main></body></html>',
            encoding="utf-8",
        )
        definitions = project / "niche_candidate_definitions.json"
        definitions.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "project_id": "market_project_fixture",
                    "poe_row_dispositions": [
                        {
                            "row_number": 2,
                            "disposition": "direct_need",
                            "reason": "名称与购买对象均为卡车手机固定。",
                            "candidate_ids": ["truck_cabin_phone_hold"],
                        },
                        {
                            "row_number": 3,
                            "disposition": "accessory",
                            "reason": "购买对象是主商品的配件，不进入车载手机支架主商品推荐。",
                            "candidate_ids": [],
                        }
                    ],
                    "candidates": [
                        {
                            "id": "truck_cabin_phone_hold",
                            "name": "卡车驾驶室内固定手机",
                            "definition": "卡车驾驶者在驾驶室内固定手机用于导航。",
                            "task": "在车辆振动中稳定查看导航。",
                            "selection_constraint_reason": "车型适配改变安装空间和稳定性要求。",
                            "demand_status": "established",
                            "dedupe_group": "truck_cabin_phone_hold",
                            "exclusive_with": [],
                            "primary_poe_row_number": 2,
                            "tag_expression": {"any_of": [{"all_of": [{"dimension": "车型适配", "values": ["truck_heavy_duty"]}]}]},
                            "poe_matches": [{"row_number": 2, "relationship": "exact", "reason": "名称与需求边界准确对应。"}],
                            "keyword_assignments": [{"keyword": "truck phone mount", "type": "direct", "reason": "完整表达卡车手机固定需求。"}],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return project, poe_file, definitions

    def test_prepare_run_and_repeat_render_are_traceable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, poe_file, definitions = self._build_project(Path(temporary))
            workspace = project / "workspace.json"
            self.assertEqual(0, niche.main(["prepare", "--project-root", str(project), "--poe-xlsx", str(poe_file), "--workspace", str(workspace)]))
            self.assertEqual("market_project_fixture", json.loads(workspace.read_text(encoding="utf-8"))["project_id"])
            self.assertEqual(2, len(json.loads(workspace.read_text(encoding="utf-8"))["poe_rows"]))

            command = ["run", "--project-root", str(project), "--poe-xlsx", str(poe_file), "--definitions", str(definitions)]
            self.assertEqual(0, niche.main(command))
            opportunity = project / "market_opportunity"
            first_run_id = json.loads((opportunity / "niche_shortlist.json").read_text(encoding="utf-8"))["run_id"]
            self.assertEqual(0, niche.main(command))

            recommendations = json.loads((opportunity / "niche_shortlist.json").read_text(encoding="utf-8"))
            self.assertEqual(first_run_id, recommendations["run_id"])
            memberships = json.loads((opportunity / "niche_shortlist_memberships.json").read_text(encoding="utf-8"))
            receipt = json.loads((opportunity / "niche_shortlist_run.json").read_text(encoding="utf-8"))
            report = (opportunity / "市场机会深挖看板-两轮初筛.html").read_text(encoding="utf-8")

            self.assertEqual(["truck_cabin_phone_hold"], recommendations["selected_candidate_ids"])
            self.assertEqual(niche.RULE_VERSION, recommendations["selection_source"])
            self.assertTrue(recommendations["poe_input"]["metrics_used_for_scoring"])
            self.assertEqual({"supply_demand", "competition_openness", "new_product_evidence", "demand_scale"}, set(recommendations["candidates"][0]["scoring"]["components"]))
            self.assertNotIn("search_trend", recommendations["candidates"][0]["scoring"]["components"])
            self.assertNotIn("return_risk", recommendations["candidates"][0]["scoring"]["components"])
            self.assertEqual(niche.SCORE_WEIGHTS, recommendations["weights"])
            self.assertEqual("not_calculated", recommendations["candidates"][0]["ad_cost_evidence"]["status"])
            self.assertIn("不参与粗筛", recommendations["candidates"][0]["ad_cost_evidence"]["reason"])
            self.assertAlmostEqual(1.0, recommendations["candidates"][0]["supply_demand_evidence"]["supply_demand_index"])
            self.assertAlmostEqual(50.0, recommendations["candidates"][0]["supply_demand_evidence"]["supply_demand_score"])
            self.assertNotIn("建议出价", json.dumps(recommendations["candidates"][0]["ad_cost_evidence"], ensure_ascii=False))
            self.assertEqual("determinate", recommendations["selection_status"])
            self.assertEqual("direct_need", recommendations["poe_row_dispositions"][0]["disposition"])
            self.assertEqual("accessory", recommendations["poe_row_dispositions"][1]["disposition"])
            self.assertEqual("success", receipt["status"])
            self.assertEqual("determinate", receipt["selection_status"])
            self.assertEqual(recommendations["run_id"], receipt["run_id"])
            self.assertEqual(10, len(memberships["candidates"][0]["top20"]))
            self.assertEqual("B0TEST0009", memberships["candidates"][0]["top20"][0]["asin"])
            self.assertEqual(1, report.count('id="niche-two-round"'))
            self.assertLess(report.index('id="niche-two-round"'), report.index('id="small"'))
            self.assertEqual(1, report.count('<!-- NICHE_TWO_ROUND_NAV_START -->'))
            self.assertIn("粗筛：直接确定 Top3", report)
            self.assertIn("一键复制这 10 个 ASIN", report)
            self.assertNotIn("广告成本压力估算", report)

    def test_failed_run_replaces_only_the_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, poe_file, definitions = self._build_project(Path(temporary))
            command = ["run", "--project-root", str(project), "--poe-xlsx", str(poe_file), "--definitions", str(definitions)]
            self.assertEqual(0, niche.main(command))
            recommendations = project / "market_opportunity" / "niche_shortlist.json"
            previous = recommendations.read_bytes()
            invalid = json.loads(definitions.read_text(encoding="utf-8"))
            invalid["candidates"][0]["keyword_assignments"][0]["keyword"] = "not in complete source"
            definitions.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(2, niche.main(command))
            receipt = json.loads((project / "market_opportunity" / "niche_shortlist_run.json").read_text(encoding="utf-8"))
            self.assertEqual("failed", receipt["status"])
            self.assertEqual(previous, recommendations.read_bytes())

    def test_missing_keyword_ppc_does_not_block_four_component_shortlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, poe_file, definitions = self._build_project(Path(temporary))
            _xlsx(project / "keywords.xlsx", "关键词", [["关键词", "月搜索量", "月购买量"], ["truck phone mount", 500, 50]])
            command = ["run", "--project-root", str(project), "--poe-xlsx", str(poe_file), "--definitions", str(definitions)]
            self.assertEqual(0, niche.main(command))
            recommendations = json.loads((project / "market_opportunity" / "niche_shortlist.json").read_text(encoding="utf-8"))
            candidate = recommendations["candidates"][0]
            self.assertEqual(["truck_cabin_phone_hold"], recommendations["selected_candidate_ids"])
            self.assertEqual("determinate", recommendations["selection_status"])
            self.assertEqual("not_calculated", candidate["ad_cost_evidence"]["status"])

    def test_keyword_ppc_changes_do_not_change_shortlist_score_or_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, poe_file, definitions = self._build_project(Path(temporary))
            _xlsx(project / "keywords.xlsx", "关键词", [
                ["关键词", "月搜索量", "月购买量", "PPC竞价"],
                ["truck phone mount", 500, 50, "$2.00"],
            ])
            command = ["shortlist", "--project-root", str(project), "--poe-xlsx", str(poe_file), "--definitions", str(definitions)]
            self.assertEqual(0, niche.main(command))
            first = json.loads((project / "market_opportunity/niche_shortlist.json").read_text(encoding="utf-8"))
            _xlsx(project / "keywords.xlsx", "关键词", [["关键词", "月搜索量", "月购买量", "PPC竞价"], ["truck phone mount", 500, 50, "$99.00"]])
            self.assertEqual(0, niche.main(command))
            second = json.loads((project / "market_opportunity/niche_shortlist.json").read_text(encoding="utf-8"))
            self.assertEqual(first["selected_candidate_ids"], second["selected_candidate_ids"])
            self.assertEqual(first["candidates"][0]["scoring"], second["candidates"][0]["scoring"])

    def test_optional_poe_context_and_search_trend_do_not_block_or_change_shortlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _, definitions = self._build_project(Path(temporary))
            minimal = project / "minimal-poe.xlsx"
            headers = ["细分市场名称", "细分市场分类1", *niche.POE_SCORING_FIELDS]
            values = {
                "细分市场名称": "Truck phone mount", "细分市场分类1": "Vehicle fit",
                "搜索量-近90天": 1000, "销量-近90天": 200,
                "前5商品点击占比-近90天 (%)": "30%", "前5商品点击占比-近360天 (%)": "35%",
                "前5品牌点击占比-近90天 (%)": "40%", "前5品牌点击占比-近360天 (%)": "45%",
                "新品发布数-360天": 8, "成功发布数-360天": 8,
            }
            _xlsx(minimal, "细分市场列表", [headers, [values[field] for field in headers]])
            definition_data = json.loads(definitions.read_text(encoding="utf-8"))
            definition_data["poe_row_dispositions"] = definition_data["poe_row_dispositions"][:1]
            definitions.write_text(json.dumps(definition_data, ensure_ascii=False), encoding="utf-8")
            command = ["shortlist", "--project-root", str(project), "--poe-xlsx", str(minimal), "--definitions", str(definitions)]
            self.assertEqual(0, niche.main(command))
            result = json.loads((project / "market_opportunity/niche_shortlist.json").read_text(encoding="utf-8"))
            self.assertEqual(["truck_cabin_phone_hold"], result["selected_candidate_ids"])
            self.assertEqual("unavailable", result["candidates"][0]["search_growth_evidence"]["status"])
            self.assertEqual("unavailable", result["candidates"][0]["return_risk_context"]["status"])


if __name__ == "__main__":
    unittest.main()
