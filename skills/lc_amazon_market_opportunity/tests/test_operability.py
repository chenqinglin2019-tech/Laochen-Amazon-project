"""validate (all errors at once + attempt ledger), status routing, in-project frozen inputs, exclusivity evidence."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import test_niche_recommendation as fixture
from test_refine_inputs import build_project, keyword_files

niche = fixture.niche


def cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = niche.main(argv)
    return code, out.getvalue(), err.getvalue()


class ValidateTests(unittest.TestCase):
    def test_all_errors_listed_in_one_run_and_ledger_detects_no_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            data = json.loads(definitions.read_text())
            data["candidates"][0]["name"] = ""                                   # error in candidate alpha
            data["candidates"][1]["demand_status"] = "maybe"                     # error in candidate beta
            data["candidates"][2]["keyword_assignments"][0]["type"] = "core"     # error in candidate gamma
            data["poe_row_dispositions"] = data["poe_row_dispositions"][:2]      # row 4 not handled
            definitions.write_text(json.dumps(data, ensure_ascii=False))
            argv = ["validate", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)]
            code, out, _ = cli(argv)
            report = json.loads(out)
            self.assertEqual(2, code)
            self.assertEqual("invalid", report["status"])
            text = "\n".join(report["errors"])
            for expected in ("缺少 name", "demand_status", "归属类型不合法", "未处理行：4"):
                self.assertIn(expected, text)
            self.assertGreaterEqual(report["error_count"], 4)
            self.assertFalse(report["stop_recommended"])
            cli(argv)
            report = json.loads(cli(argv)[1])
            self.assertEqual(3, report["attempt"])
            self.assertTrue(report["stop_recommended"])
            self.assertFalse((project / "market_opportunity/niche_shortlist.json").exists())

    def test_valid_definitions(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            code, out, _ = cli(["validate", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)])
            self.assertEqual(0, code)
            self.assertEqual("valid", json.loads(out)["status"])


class StatusAndFrozenInputTests(unittest.TestCase):
    def test_status_routes_each_stage_and_frozen_copies_survive_moved_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            status = lambda: json.loads(cli(["status", "--project-root", str(project)])[1])  # noqa: E731
            self.assertEqual("base:fetch-roots", status()["stage"])
            folder = project / "market_opportunity"
            for name in ("02_keyword_roots.json", "03_dimension_candidates.json", "agent_dimensions.json", "04_tagging_workspace.json"):
                (folder / name).write_text("{}")
            self.assertEqual("recommend:prepare", status()["stage"])
            self.assertEqual(0, cli(["prepare", "--project-root", str(project), "--poe-xlsx", str(poe)])[0])
            self.assertEqual("recommend:definitions", status()["stage"])
            self.assertEqual(0, cli(["shortlist", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)])[0])
            current = status()
            self.assertEqual("recommend:awaiting_keyword_files", current["stage"])
            self.assertEqual(3, len(current["frozen_markets"]))
            self.assertIn("不要重跑", " ".join(current["warnings"]) + current["next"])
            shortlist = json.loads((folder / "niche_shortlist.json").read_text())
            self.assertEqual("market_opportunity/frozen_inputs/poe.xlsx", shortlist["frozen_inputs"]["poe_path"])
            # the user's original files are moved away between the two rounds
            poe.rename(poe.with_suffix(".moved"))
            definitions.rename(definitions.with_suffix(".moved"))
            files = keyword_files(project, shortlist)
            code, _, err = cli(["refine", "--project-root", str(project), "--shortlist-result", str(folder / "niche_shortlist.json"),
                                "--keyword-input-xlsx", *map(str, files)])
            self.assertEqual(0, code, err)
            self.assertTrue(status()["stage"].startswith("done:"))
            (folder / "agent_listing_tags.json").write_text((folder / "agent_listing_tags.json").read_text() + "\n")
            self.assertEqual("recommend:shortlist_stale", status()["stage"])

    def test_declared_exclusivity_carries_its_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions = build_project(Path(directory))
            data = json.loads(definitions.read_text())
            data["candidates"][0]["exclusive_with"] = [{"id": "beta", "reason": "同一买家任务的替代方案"}]
            data["candidates"][1]["exclusive_with"] = ["alpha"]
            definitions.write_text(json.dumps(data, ensure_ascii=False))
            self.assertEqual(0, cli(["shortlist", "--project-root", str(project), "--poe-xlsx", str(poe), "--definitions", str(definitions)])[0])
            result = json.loads((project / "market_opportunity/niche_shortlist.json").read_text())
            alpha = next(c for c in result["candidates"] if c["id"] == "alpha")
            reasons = [c["reason"] for c in alpha["dedupe_conflicts"] if c["candidate_id"] == "beta"]
            self.assertEqual(["候选定义中声明的父子／替代需求互斥：同一买家任务的替代方案"], reasons)


if __name__ == "__main__":
    unittest.main()
