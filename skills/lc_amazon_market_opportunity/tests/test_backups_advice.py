"""User decisions 2026-10-01: max-total Top3, labelled backups, entry advice, low-coverage note."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import test_niche_recommendation as fixture
from test_refine_inputs import build_project, keyword_files, run_cli

niche = fixture.niche
metrics = niche.helper_module("niche_refinement_metrics")


def edit_definitions(path: Path, change) -> None:
    data = json.loads(path.read_text())
    change({item["id"]: item for item in data["candidates"]})
    path.write_text(json.dumps(data, ensure_ascii=False))


class BackupAndAdviceTests(unittest.TestCase):
    def shortlist(self, project, poe, definitions) -> dict:
        code, err = run_cli(["shortlist", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)])
        self.assertEqual(0, code, err)
        return json.loads((project / "market_opportunity/niche_shortlist.json").read_text())

    def refine(self, project, shortlist) -> dict:
        code, err = run_cli(["refine", "--project-root", str(project), "--shortlist-result", str(project / "market_opportunity/niche_shortlist.json"),
                             "--keyword-input-xlsx", *map(str, keyword_files(project, shortlist))])
        self.assertEqual(0, code, err)
        return json.loads((project / "market_opportunity/08_niche_recommendations.json").read_text())

    def test_backups_are_recorded_but_stay_out_of_refinement_and_report(self):
        # user decision 2026-10-03: the frozen (original) report format has no backups, entry advice or low-coverage notes
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory), {"alpha": 25, "beta": 22, "gamma": 8})
            shortlist = self.shortlist(project, poe, definitions)
            self.assertEqual(["alpha", "beta"], sorted(shortlist["selected_candidate_ids"]))
            self.assertEqual(["gamma"], shortlist["backup_candidate_ids"])
            gamma = next(c for c in shortlist["candidates"] if c["id"] == "gamma")
            self.assertTrue(gamma["backup_reason"].startswith("完整匹配 ASIN 仅 8 个，低于正式门槛 10 个"))
            csv_text = (project / "market_opportunity/niche_shortlist_top20_asins.csv").read_text(encoding="utf-8-sig")
            self.assertNotIn("gamma", csv_text)
            shortlist_html = (project / "market_opportunity/市场机会深挖看板-两轮初筛.html").read_text()
            self.assertIn("共 4 个 Excel", shortlist_html)
            files = keyword_files(project, shortlist)
            self.assertEqual(4, len(files))
            result = self.refine(project, shortlist)
            self.assertEqual(sorted(shortlist["selected_candidate_ids"]), sorted(c["id"] for c in result["candidates"]))
            self.assertTrue(all(c["entry_advice"] for c in result["candidates"]))
            html = (project / "market_opportunity/市场机会深挖看板-两轮复评.html").read_text()
            self.assertIn('data-layout-version="two-round-competition-v1"', html)
            for absent in ("候补", "进入建议", "低覆盖", "niche-entry-advice", "风险等级"):
                self.assertNotIn(absent, html)

    def test_three_formal_markets_need_no_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            shortlist = self.shortlist(project, poe, definitions)
            self.assertEqual(3, len(shortlist["selected_candidate_ids"]))
            self.assertEqual([], shortlist["backup_candidate_ids"])

    def test_backup_never_conflicts_with_a_chosen_market(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory), {"alpha": 25, "beta": 22, "gamma": 8})

            def exclusive(c):
                c["alpha"]["exclusive_with"] = ["gamma"]
                c["gamma"]["exclusive_with"] = ["alpha"]
            edit_definitions(definitions, exclusive)
            shortlist = self.shortlist(project, poe, definitions)
            self.assertIn("alpha", shortlist["selected_candidate_ids"])
            self.assertEqual([], shortlist["backup_candidate_ids"])

    def test_no_formal_market_lists_backups_but_cannot_refine(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))

            def pending(c):
                for item in c.values():
                    item["demand_status"] = "pending"
            edit_definitions(definitions, pending)
            shortlist = self.shortlist(project, poe, definitions)
            self.assertEqual([], shortlist["selected_candidate_ids"])
            self.assertEqual(3, len(shortlist["backup_candidate_ids"]))
            self.assertEqual("shortlist_pending", json.loads((project / "project_manifest.json").read_text())["status"]["niche_recommendation"])
            code, err = run_cli(["refine", "--project-root", str(project), "--shortlist-result", str(project / "market_opportunity/niche_shortlist.json"),
                                 "--keyword-input-xlsx", str(project / "x.xlsx"), str(project / "y.xlsx")])
            self.assertEqual(2, code)
            self.assertIn("没有可进一步分析的冻结 Top3", err)

    def test_refinable_ids_are_formal_markets_only(self):
        shortlist = {"selected_candidate_ids": ["a"], "backup_candidate_ids": ["b", "c"],
                     "candidates": [{"id": "a", "top20": [{"asin": "X"}]}, {"id": "b", "top20": []}, {"id": "c", "top20": [{"asin": "Y"}]}]}
        self.assertEqual(["a"], niche.refinable_candidate_ids(shortlist))

    def test_max_total_selection_is_kept(self):
        # Reference case (市场机会深挖看板-两轮复评.html): the 90.59 market loses to the higher three-market total.
        def ev(cid, score, comp, excl):
            return {"candidate": {"id": cid, "exclusive_with": excl}, "formal_eligible": True, "scoring": {"score": score},
                    "competition_openness_score": comp, "dedupe_conflict_ids": set(excl), "dedupe_conflicts": []}
        case = [ev("folding", 86.25, 69.41, ["small_folding"]), ev("small_folding", 90.59, 94.22, ["folding", "compact"]),
                ev("gaming", 78.80, 66.12, []), ev("compact", 77.21, 57.58, ["small_folding"]), ev("student", 31.70, 95.21, [])]
        self.assertEqual(["folding", "gaming", "compact"], [e["candidate"]["id"] for e in niche.candidate_selection(case, 3)["selected"]])


class AdviceRuleTests(unittest.TestCase):
    def conclusions(self, product="中等", brand="中等", ad="较低", confidence="standard", unknown=()):
        rules = {key: {"status": "ready", "level": None} for key in ("review_dependency", "rating_requirement", "price_sensitivity", "best_price_bands", "new_product_cycle")}
        rules.update(product_monopoly={"status": "ready", "level": product}, brand_monopoly={"status": "ready", "level": brand}, ad_pressure={"status": "ready", "level": ad})
        for key in unknown:
            rules[key] = {"status": "pending_validation", "level": None}
        return {"rules": rules, "confidence": confidence}

    def test_levels_and_advice(self):
        self.assertEqual(("建议优先进入", "低"), tuple(metrics.entry_advice(self.conclusions(), {}, None, False)[k] for k in ("advice", "risk_level")))
        medium = metrics.entry_advice(self.conclusions(product="很高"), {}, None, False)
        self.assertEqual(("可进入，关注所列风险", "中", ["商品垄断度很高"]), (medium["advice"], medium["risk_level"], medium["flags"]))
        high = metrics.entry_advice(self.conclusions(product="很高", brand="很高"), {"low_coverage": True, "coverage_note": "低覆盖（只有 43.1% 的点击同时有转化与竞价数据）"}, None, False)
        self.assertEqual(("谨慎进入，需差异化验证", "高"), (high["advice"], high["risk_level"]))
        self.assertIn("低覆盖（只有 43.1% 的点击同时有转化与竞价数据）", high["flags"])
        backup = metrics.entry_advice(self.conclusions(), {}, None, True)
        self.assertEqual(("谨慎进入，需差异化验证", "中"), (backup["advice"], backup["risk_level"]))
        watch = metrics.entry_advice(self.conclusions(confidence="low"), {}, {"status": "watch"}, False)
        self.assertEqual(2, len(watch["flags"]))

    def test_missing_evidence_wins(self):
        self.assertEqual("证据不足，先补数据", metrics.entry_advice(self.conclusions(unknown=("ad_pressure",)), {}, None, False)["advice"])
        self.assertEqual("证据不足，先补数据", metrics.entry_advice(self.conclusions(unknown=("rating_requirement", "new_product_cycle")), {}, None, False)["advice"])
        self.assertEqual("建议优先进入", metrics.entry_advice(self.conclusions(unknown=("new_product_cycle",)), {}, None, False)["advice"])

    def test_low_coverage_is_a_note_not_a_gate(self):
        rows = [{"key": "desk", "clicks": 570, "purchases": 10, "ppc_bid": None, "conversion_available": True},
                {"key": "folding desk", "clicks": 430, "purchases": 20, "ppc_bid": 1.0, "conversion_available": True}]
        ad = metrics.advertising_evidence(rows, 50)
        self.assertEqual("ready", ad["status"])
        self.assertTrue(ad["low_coverage"])
        self.assertEqual("低覆盖（只有 43.0% 的点击同时有转化与竞价数据）", ad["coverage_note"])
        self.assertAlmostEqual(1.0 / (50 * (20 / 430)) * 100, ad["pressure_estimate"])
        rows[0]["ppc_bid"] = 2.0
        self.assertFalse(metrics.advertising_evidence(rows, 50)["low_coverage"])

    def test_low_coverage_is_recorded_in_data_not_in_ad_pressure_readout(self):
        members = [{"asin": f"B{i}", "price": 50, "monthly_sales": 100 - i, "brand": "x", "launch_days": 100, "review_count": 10, "rating": 4.5} for i in range(12)]
        rows = [{"key": "desk", "clicks": 570, "purchases": 10, "ppc_bid": None}, {"key": "folding desk", "clicks": 430, "purchases": 20, "ppc_bid": 1.0}]
        ad = metrics.advertising_evidence(rows, 50)
        self.assertTrue(ad["low_coverage"])
        summary = metrics.eight_conclusions(members, ad)["rules"]["ad_pressure"]["summary"]
        self.assertNotIn("低覆盖", summary)

if __name__ == "__main__":
    unittest.main()
