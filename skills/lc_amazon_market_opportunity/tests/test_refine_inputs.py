"""Production refine path: one conversion + one SellerSprite workbook per frozen market."""
from __future__ import annotations

import contextlib
import io
import json
import random
import tempfile
import unittest
import xml.sax.saxutils
import zipfile
from pathlib import Path

import test_niche_recommendation as fixture

niche = fixture.niche

POE_HEADERS = [
    "细分市场名称", "细分市场分类1", "搜索量-近90天", "销量-近90天",
    "前5商品点击占比-近90天 (%)", "前5商品点击占比-近360天 (%)", "前5品牌点击占比-近90天 (%)", "前5品牌点击占比-近360天 (%)",
    "新品发布数-360天", "成功发布数-360天", "退货率-近360天 (%)",
]


def write_workbook(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    names = list(sheets)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(f'<sheet name="{xml.sax.saxutils.escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, 1))
        + "</sheets></workbook>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        for i, name in enumerate(names, 1):
            rows = []
            for r, values in enumerate(sheets[name], 1):
                cells = "".join(
                    f'<c r="{fixture._column_name(c)}{r}"><v>{v}</v></c>' if isinstance(v, (int, float)) and not isinstance(v, bool)
                    else f'<c r="{fixture._column_name(c)}{r}" t="inlineStr"><is><t>{xml.sax.saxutils.escape(str(v))}</t></is></c>'
                    for c, v in enumerate(values)
                )
                rows.append(f'<row r="{r}">{cells}</row>')
            archive.writestr(f"xl/worksheets/sheet{i}.xml",
                             '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                             f'<sheetData>{"".join(rows)}</sheetData></worksheet>')


MARKETS = {"alpha": 25, "beta": 22, "gamma": 15}


def build_project(root: Path, sizes: dict[str, int] = MARKETS, missing_price: str | None = None) -> tuple[Path, Path, Path]:
    project = root / "market_project_multi"
    (project / "market_research").mkdir(parents=True)
    (project / "market_opportunity").mkdir()
    rows, tags = [], []
    # "other" listings sell little, so every fixture market is above the category average (robust index >= 1.0).
    for market, size in [*sizes.items(), ("other", 12)]:
        for index in range(size):
            asin = f"B0{market[:2].upper()}{index:06d}"
            rows.append({"asin": asin, "title": f"{market} desk {index}", "brand": f"{market}-brand-{index % 4}",
                         "price": None if asin == missing_price else 30 + index, "monthly_sales": 20 if market == "other" else 500 - index * 7,
                         "parent_asin": f"P{asin}", "product_url": f"https://www.amazon.com/dp/{asin}", "month": "2026-09",
                         "launch_days": 60 + index * 30, "review_count": 10 + index * 15, "rating": 4.0 + (index % 9) / 10})
            tags.append({"asin": asin, "normalized_values": {"场景": [market]}, "display_values": {"场景": [market]}})
    (project / "project_manifest.json").write_text(json.dumps({"project_id": "market_project_multi", "marketplace": "US", "artifacts": {}, "status": {}}))
    (project / "market_research/cleaned_30d_listings.json").write_text(json.dumps({"rows": rows}))
    (project / "market_research/01_input_manifest.json").write_text(json.dumps({"keyword_file": "keywords.xlsx"}))
    (project / "market_opportunity/agent_listing_tags.json").write_text(json.dumps({"tags": tags}, ensure_ascii=False))
    (project / "market_opportunity/07_opportunity_analysis.json").write_text("{}")
    (project / "market_opportunity/市场机会深挖看板.html").write_text(
        '<html><head></head><body><nav><a href="#formal">f</a><a href="#small">s</a></nav>'
        '<h2 id="formal">正式机会组合明细</h2><h2 id="small">小样本观察</h2></body></html>')
    fixture._xlsx(project / "keywords.xlsx", "关键词", [["关键词", "月搜索量"]] + [[f"{m} desk", 1000] for m in sizes])
    poe = project / "poe.xlsx"
    fixture._xlsx(poe, "细分市场列表", [POE_HEADERS] + [
        [f"{m} desk", "Desks", 10000 - i * 1000, 3000 - i * 300, 30 + i, 32 + i, 35 + i, 36 + i, 20, 8 + i, 2]
        for i, m in enumerate(sizes)])
    definitions = project / "definitions.json"
    definitions.write_text(json.dumps({
        "project_id": "market_project_multi",
        "poe_row_dispositions": [{"row_number": i + 2, "disposition": "direct_need", "reason": "准确对应", "candidate_ids": [m]} for i, m in enumerate(sizes)],
        "candidates": [{
            "id": m, "name": f"市场{m}", "definition": f"{m} 需求", "task": "办公", "selection_constraint_reason": "场景决定购买",
            "demand_status": "established", "dedupe_group": m, "exclusive_with": [], "primary_poe_row_number": i + 2,
            "tag_expression": {"any_of": [{"all_of": [{"dimension": "场景", "values": [m]}]}]},
            "poe_matches": [{"row_number": i + 2, "relationship": "exact", "reason": "准确对应"}],
            "keyword_assignments": [{"keyword": f"{m} desk", "type": "direct", "reason": "直接需求"}],
        } for i, m in enumerate(sizes)],
    }, ensure_ascii=False))
    return project, poe, definitions


def run_cli(argv: list[str]) -> tuple[int, str]:
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = niche.main(argv)
    return code, err.getvalue()


def keyword_files(project: Path, shortlist: dict, tamper: dict[str, list[str]] | None = None) -> list[Path]:
    paths = []
    by_id = {candidate["id"]: candidate for candidate in shortlist["candidates"]}
    for market in niche.refinable_candidate_ids(shortlist):
        candidate = by_id[market]
        words = [f"{market} kw{i}" for i in range(5)]
        conversion = project / f"conv_{market}.xlsx"
        write_workbook(conversion, {"关键词转化": [["关键词", "近90天点击量", "近90天购买量"]] + [[w, 1000 + i * 100, 40 + i] for i, w in enumerate(words)]})
        asins = (tamper or {}).get(market) or [m["asin"] for m in candidate["top20"]]
        seller = project / f"seller_{market}.xlsx"
        write_workbook(seller, {"关键词": [["关键词", "PPC竞价", "流量占比"]] + [[w, 1.0 + i / 10, "20%"] for i, w in enumerate(words)],
                                "Asin": [["ASIN"]] + [[a] for a in asins]})
        paths += [conversion, seller]
    return paths


class RefineInputTests(unittest.TestCase):
    def shortlist(self, project: Path, poe: Path, definitions: Path) -> dict:
        code, err = run_cli(["shortlist", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)])
        self.assertEqual(0, code, err)
        return json.loads((project / "market_opportunity/niche_shortlist.json").read_text())

    def refine(self, project: Path, files: list[Path]) -> tuple[int, str]:
        return run_cli(["refine", "--project-root", str(project), "--shortlist-result", str(project / "market_opportunity/niche_shortlist.json"),
                        "--keyword-input-xlsx", *map(str, files)])

    def test_three_markets_in_any_order_including_a_15_asin_top20(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            shortlist = self.shortlist(project, poe, definitions)
            self.assertEqual(3, len(shortlist["selected_candidate_ids"]))
            files = keyword_files(project, shortlist)
            random.Random(7).shuffle(files)
            code, err = self.refine(project, files)
            self.assertEqual(0, code, err)
            result = json.loads((project / "market_opportunity/08_niche_recommendations.json").read_text())
            frozen = {c["id"]: [m["asin"] for m in c["top20"]] for c in shortlist["candidates"]}
            for candidate in result["candidates"]:
                self.assertEqual(frozen[candidate["id"]], [m["asin"] for m in candidate["top20"]])
            self.assertEqual(15, len(frozen["gamma"]))
            mappings = {m["candidate_id"]: Path(m["seller_sprite_path"]).name for m in result["keyword_conversion_input"]["market_mappings"]}
            self.assertEqual({m: f"seller_{m}.xlsx" for m in MARKETS}, mappings)

    def test_two_frozen_markets_need_four_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory), {"alpha": 25, "beta": 22})
            shortlist = self.shortlist(project, poe, definitions)
            self.assertEqual(["alpha", "beta"], sorted(shortlist["selected_candidate_ids"]))
            self.assertEqual([], shortlist["backup_candidate_ids"])
            files = keyword_files(project, shortlist)
            self.assertEqual(4, len(files))
            code, err = self.refine(project, files + [files[0].with_name("extra1.xlsx"), files[1].with_name("extra2.xlsx")])
            self.assertEqual(2, code)
            self.assertIn("需要 4 个不同的 Excel", err)
            code, err = self.refine(project, files)
            self.assertEqual(0, code, err)

    def test_single_frozen_market_needs_two_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory), {"alpha": 12})
            shortlist = self.shortlist(project, poe, definitions)
            files = keyword_files(project, shortlist)
            code, err = self.refine(project, files)
            self.assertEqual(0, code, err)
            result = json.loads((project / "market_opportunity/08_niche_recommendations.json").read_text())
            self.assertEqual(12, len(result["candidates"][0]["top20"]))

    def test_asin_sheet_mismatch_names_missing_and_extra_asins(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            shortlist = self.shortlist(project, poe, definitions)
            alpha = next(c for c in shortlist["candidates"] if c["id"] == "alpha")
            asins = [m["asin"] for m in alpha["top20"]]
            dropped = asins[-1]
            files = keyword_files(project, shortlist, {"alpha": asins[:-1] + ["B0ZZ999999"]})
            code, err = self.refine(project, files)
            self.assertEqual(2, code)
            self.assertIn(dropped, err)
            self.assertIn("B0ZZ999999", err)

    def test_refine_keeps_frozen_top20_when_a_member_lacks_price(self):
        with tempfile.TemporaryDirectory() as directory:
            best = "B0AL000000"
            project, poe, definitions = build_project(Path(directory), missing_price=best)
            shortlist = self.shortlist(project, poe, definitions)
            alpha_frozen = [m["asin"] for m in next(c for c in shortlist["candidates"] if c["id"] == "alpha")["top20"]]
            self.assertEqual(best, alpha_frozen[0])
            code, err = self.refine(project, keyword_files(project, shortlist))
            self.assertEqual(0, code, err)
            result = json.loads((project / "market_opportunity/08_niche_recommendations.json").read_text())
            alpha = next(c for c in result["candidates"] if c["id"] == "alpha")
            self.assertEqual(alpha_frozen, [m["asin"] for m in alpha["top20"]])
            self.assertIn(best, [x["asin"] for x in alpha["refined_product_evidence"]["excluded_products"]])
            self.assertEqual(24, alpha["rule_conclusions"]["sample_count"])
            members = json.loads((project / "market_opportunity/10_niche_product_memberships.json").read_text())
            alpha_members = next(c for c in members["candidates"] if c["candidate_id"] == "alpha")["matched_members"]
            self.assertEqual(25, len(alpha_members))

    def test_awaiting_notice_lists_exact_file_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory), {"alpha": 25, "beta": 15, "gamma": 8})
            self.shortlist(project, poe, definitions)
            html = (project / "market_opportunity/市场机会深挖看板-两轮初筛.html").read_text()
            notice = html[html.index('id="niche-awaiting-conversion"'):]
            self.assertIn("请为上述 2 个市场各提供 1 份细分市场关键词转化表", notice)
            self.assertIn("共 4 个 Excel", notice)
            self.assertNotIn("一张", notice)

if __name__ == "__main__":
    unittest.main()
