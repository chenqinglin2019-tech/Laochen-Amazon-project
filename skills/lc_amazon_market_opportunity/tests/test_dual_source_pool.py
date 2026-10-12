"""Rule v10: POE niches + multi-dimensional combinations, product-sample scoring, robust gate, shared-sales dedupe."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import test_niche_recommendation as fixture
from test_refine_inputs import keyword_files, run_cli, write_workbook

niche = fixture.niche
pool = niche.helper_module("niche_candidate_pool")

DISPLAY = {
    "尺寸": {"compact": "紧凑/小空间", "standard": "标准尺寸/未特别强调小空间", "unidentified": "不可识别"},
    "场景": {"gaming": "游戏", "office": "家庭办公", "other": "其他用途"},
    "收纳": {"drawers": "抽屉收纳", "shelves": "层架收纳", "storage_unspecified": "泛收纳", "no_storage": "未体现收纳"},
}


def listing(asin, size, scene, storage, sales, launch=200):
    return ({"asin": asin, "title": asin, "brand": f"brand-{asin[-2:]}", "price": 80, "monthly_sales": sales, "parent_asin": f"P{asin}",
             "product_url": f"https://www.amazon.com/dp/{asin}", "month": "2026-09", "launch_days": launch, "review_count": 50, "rating": 4.5},
            {"asin": asin, "normalized_values": {"尺寸": [size], "场景": [scene], "收纳": [storage]},
             "display_values": {"尺寸": [DISPLAY["尺寸"][size]], "场景": [DISPLAY["场景"][scene]], "收纳": [DISPLAY["收纳"][storage]]}})


def build(root: Path, formal_opportunities: list[dict] | None = None) -> tuple[Path, Path, Path]:
    project = root / "market_project_dual"
    (project / "market_research").mkdir(parents=True)
    (project / "market_opportunity").mkdir()
    rows, tags = [], []
    storages = ["drawers", "shelves", "storage_unspecified", "no_storage"]
    # category average ≈ 276; compact gaming ≈ 485 (robust ≈ 1.29), all gaming ≈ 332 (≈ 1.12), office ≈ 229 (< 1.0)
    specs = ([("compact", "gaming", 560 - i * 10) for i in range(16)] + [("standard", "gaming", 250) for _ in range(30)]
             + [("compact", "office", 300) for _ in range(16)] + [("standard", "office", 200) for _ in range(40)]
             + [("unidentified", "other", 280) for _ in range(30)])
    for i, (size, scene, sales) in enumerate(specs):
        r, t = listing(f"B0DS{i:06d}", size, scene, storages[i % 4], sales, launch=100 + (i % 12) * 60)
        rows.append(r); tags.append(t)
    (project / "project_manifest.json").write_text(json.dumps({"project_id": "market_project_dual", "marketplace": "US", "artifacts": {}, "status": {}}))
    (project / "market_research/cleaned_30d_listings.json").write_text(json.dumps({"rows": rows}))
    (project / "market_research/01_input_manifest.json").write_text(json.dumps({"keyword_file": "keywords.xlsx"}))
    (project / "market_opportunity/agent_listing_tags.json").write_text(json.dumps({"tags": tags}, ensure_ascii=False))
    combos = formal_opportunities if formal_opportunities is not None else [
        {"dimensions": "尺寸 + 场景 + 收纳", "features": "紧凑/小空间 + 游戏 + 未体现收纳", "opportunity_score": 95, "listing_count": 4, "supply_demand_index": 5.1},
        {"dimensions": "尺寸 + 场景", "features": "紧凑/小空间 + 游戏", "opportunity_score": 92, "listing_count": 16, "supply_demand_index": 3.9},
        {"dimensions": "尺寸 + 收纳", "features": "紧凑/小空间 + 泛收纳", "opportunity_score": 85, "listing_count": 8, "supply_demand_index": 2.5},
        {"dimensions": "场景 + 收纳", "features": "游戏 + 未体现收纳", "opportunity_score": 80, "listing_count": 9, "supply_demand_index": 2.0},
        {"dimensions": "尺寸 + 场景", "features": "不可识别 + 其他用途", "opportunity_score": 70, "listing_count": 30, "supply_demand_index": 0.3},
    ]
    (project / "market_opportunity/07_opportunity_analysis.json").write_text(json.dumps({"formal_opportunities": combos}, ensure_ascii=False))
    (project / "market_opportunity/市场机会深挖看板.html").write_text(
        '<html><head></head><body><nav><a href="#formal">f</a><a href="#small">s</a></nav><h2 id="formal">正式机会组合明细</h2><h2 id="small">小样本观察</h2></body></html>')
    fixture._xlsx(project / "keywords.xlsx", "关键词", [["关键词", "月搜索量"], ["gaming desk", 9000], ["small gaming desk", 5000], ["small desk with storage", 3000], ["office desk", 4000]])
    poe = project / "poe.xlsx"
    fixture._xlsx(poe, "细分市场列表", [["细分市场名称", "细分市场分类1"], ["gaming desk", "Desks"], ["office desk", "Desks"]])
    definitions = project / "definitions.json"
    definitions.write_text(json.dumps({
        "project_id": "market_project_dual",
        "poe_row_dispositions": [{"row_number": 2, "disposition": "direct_need", "reason": "准确", "candidate_ids": ["gaming"]},
                                 {"row_number": 3, "disposition": "direct_need", "reason": "准确", "candidate_ids": ["office"]}],
        "candidates": [
            {"id": "gaming", "name": "游戏电脑桌", "definition": "游戏桌", "task": "游戏", "selection_constraint_reason": "场景", "demand_status": "established",
             "dedupe_group": "gaming", "exclusive_with": [], "primary_poe_row_number": 2,
             "tag_expression": {"any_of": [{"all_of": [{"dimension": "场景", "values": ["gaming"]}]}]},
             "poe_matches": [{"row_number": 2, "relationship": "exact", "reason": "准确"}],
             "keyword_assignments": [{"keyword": "gaming desk", "type": "direct", "reason": "直接"}]},
            {"id": "office", "name": "家庭办公桌", "definition": "办公桌", "task": "办公", "selection_constraint_reason": "场景", "demand_status": "established",
             "dedupe_group": "office", "exclusive_with": [], "primary_poe_row_number": 3,
             "tag_expression": {"any_of": [{"all_of": [{"dimension": "场景", "values": ["office"]}]}]},
             "poe_matches": [{"row_number": 3, "relationship": "exact", "reason": "准确"}],
             "keyword_assignments": [{"keyword": "office desk", "type": "direct", "reason": "直接"}]},
        ],
    }, ensure_ascii=False))
    return project, poe, definitions


def prepare(project: Path, poe: Path) -> dict:
    code, err = run_cli(["prepare", "--project-root", str(project), "--poe-xlsx", str(poe)])
    assert code == 0, err
    return json.loads((project / "market_opportunity/niche_recommendation_workspace.json").read_text())


def review(definitions: Path, workspace: dict, keywords: dict[str, list[str]], drop: dict[str, str] | None = None) -> None:
    data = json.loads(definitions.read_text())
    reviews = []
    for item in workspace["combo_review_template"]:
        entry = dict(item)
        if item["name"] in (drop or {}):
            entry.update(decision="drop", reason=drop[item["name"]])
        else:
            entry["keyword_assignments"] = [{"keyword": k, "type": "direct", "reason": "表达组合需求"} for k in keywords.get(item["name"], [])]
        reviews.append(entry)
    data["combo_reviews"] = reviews
    definitions.write_text(json.dumps(data, ensure_ascii=False))


def shortlist(project: Path, poe: Path, definitions: Path) -> tuple[int, str]:
    return run_cli(["shortlist", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)])


class ValueClassTests(unittest.TestCase):
    def test_category_agnostic_classes(self):
        self.assertEqual("unknown", pool.value_class("unidentified", ["不可识别"]))
        self.assertEqual("absence", pool.value_class("not_stated", ["未体现移动/可调"]))
        self.assertEqual("absence", pool.value_class("standard_41_55_or_unspecified", ["标准尺寸/未特别强调小空间"]))
        self.assertEqual("absence", pool.value_class("general_unspecified_position", [], niche.NON_CANDIDATE_VALUES))
        self.assertEqual("vague", pool.value_class("storage_unspecified", ["泛收纳"]))
        self.assertEqual("positive", pool.value_class("compact_small_space", ["紧凑/小空间"]))

    def test_containment_threshold(self):
        below = [{"id": "a", "sales_by_asin": {"x": 49, "y": 51}}, {"id": "b", "sales_by_asin": {"x": 49, "z": 500}}]
        self.assertEqual({}, pool.containment_conflicts(below))
        at = [{"id": "a", "sales_by_asin": {"x": 50, "y": 50}}, {"id": "b", "sales_by_asin": {"x": 50, "z": 500}}]
        self.assertEqual({("a", "b"): 0.5}, pool.containment_conflicts(at))


class DualSourcePoolTests(unittest.TestCase):
    def test_workspace_lists_combo_cores_with_absence_stripped_and_vague_widened(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, _ = build(Path(directory))
            workspace = prepare(project, poe)
            names = [item["name"] for item in workspace["combo_candidates"]]
            self.assertEqual(["紧凑/小空间 + 游戏", "紧凑/小空间 + 带收纳（任意）", "游戏"], names)
            core = workspace["combo_candidates"][0]
            self.assertIn("未体现收纳", core["entry_hint"]["text"])
            storage = workspace["combo_candidates"][1]["tag_expression"]["any_of"][0]["all_of"]
            values = next(c["values"] for c in storage if c["dimension"] == "收纳")
            self.assertEqual(["drawers", "shelves", "storage_unspecified"], values)
            self.assertEqual(1, len(workspace["skipped_cli_combinations"]))

    def test_unreviewed_combo_is_rejected_with_its_name(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build(Path(directory))
            prepare(project, poe)
            code, err = shortlist(project, poe, definitions)
            self.assertEqual(2, code)
            self.assertIn("紧凑/小空间 + 游戏", err)
            self.assertIn("combo_review_template", err)

    def test_drop_requires_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build(Path(directory))
            workspace = prepare(project, poe)
            review(definitions, workspace, {}, drop={"紧凑/小空间 + 带收纳（任意）": ""})
            code, err = shortlist(project, poe, definitions)
            self.assertEqual(2, code)
            self.assertIn("必须写原因", err)

    def test_combo_competes_with_poe_niches_and_shared_sales_dedupe_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build(Path(directory))
            workspace = prepare(project, poe)
            review(definitions, workspace, {"紧凑/小空间 + 游戏": ["small gaming desk"]})
            code, err = shortlist(project, poe, definitions)
            self.assertEqual(0, code, err)
            result = json.loads((project / "market_opportunity/niche_shortlist.json").read_text())
            by_name = {c["name"]: c for c in result["candidates"]}
            combo = by_name["紧凑/小空间 + 游戏"]
            self.assertEqual("combo", combo["source"])
            self.assertEqual("poe+combo", by_name["游戏电脑桌"]["source"])
            self.assertIn(combo["id"], result["selected_candidate_ids"])
            # the combo sits inside the gaming niche: same demand, only one of them may be chosen
            self.assertIn("gaming", {c["candidate_id"] for c in combo["dedupe_conflicts"]})
            self.assertNotIn("gaming", result["selected_candidate_ids"])
            storage = by_name["紧凑/小空间 + 带收纳（任意）"]
            self.assertFalse(storage["formal_eligible"])
            self.assertIn("没有 direct 核心词", storage["formal_ineligible_reason"])
            self.assertEqual(2, result["candidate_pool"]["combo_candidate_count"])
            self.assertEqual("gaming", result["candidate_pool"]["merged_with_poe"][0]["candidate_id"])
            # source, entry hint and pool summary live in the data; the frozen report format is unchanged
            self.assertIn("未体现收纳", combo["entry_hint"]["text"])
            html = (project / "market_opportunity/市场机会深挖看板-两轮初筛.html").read_text()
            self.assertIn('data-layout-version="two-round-competition-v1"', html)
            for absent in ('<th scope="col">来源</th>', "候选池：", "切入点提示", "稳健供需指数 <strong>", "{'candidate_id'"):
                self.assertNotIn(absent, html)
            self.assertIn("属同一需求，共享月销量占较小市场的", html)

    def test_robust_index_below_one_cannot_be_formal(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build(Path(directory))
            workspace = prepare(project, poe)
            review(definitions, workspace, {"紧凑/小空间 + 游戏": ["small gaming desk"]})
            self.assertEqual(0, shortlist(project, poe, definitions)[0])
            result = json.loads((project / "market_opportunity/niche_shortlist.json").read_text())
            office = next(c for c in result["candidates"] if c["id"] == "office")
            self.assertLess(office["supply_demand_evidence"]["robust_index"], 1.0)
            self.assertFalse(office["formal_eligible"])
            self.assertIn("稳健供需指数", office["formal_ineligible_reason"])
            self.assertNotIn("office", result["selected_candidate_ids"])

    def test_combo_market_goes_through_refinement(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build(Path(directory))
            workspace = prepare(project, poe)
            review(definitions, workspace, {"紧凑/小空间 + 游戏": ["small gaming desk"]})
            self.assertEqual(0, shortlist(project, poe, definitions)[0])
            result = json.loads((project / "market_opportunity/niche_shortlist.json").read_text())
            files = keyword_files(project, result)
            code, err = run_cli(["refine", "--project-root", str(project), "--shortlist-result", str(project / "market_opportunity/niche_shortlist.json"),
                                 "--keyword-input-xlsx", *map(str, files)])
            self.assertEqual(0, code, err)
            refined = json.loads((project / "market_opportunity/08_niche_recommendations.json").read_text())
            combo = next(c for c in refined["candidates"] if c["source"] == "combo")
            self.assertEqual(8, len(combo["rule_conclusions"]["rules"]))
            self.assertIsNotNone(combo["entry_advice"])

    def test_no_cli_combinations_keeps_poe_only_behaviour(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build(Path(directory), formal_opportunities=[])
            workspace = prepare(project, poe)
            self.assertEqual([], workspace["combo_candidates"])
            self.assertEqual(0, shortlist(project, poe, definitions)[0])


if __name__ == "__main__":
    unittest.main()
