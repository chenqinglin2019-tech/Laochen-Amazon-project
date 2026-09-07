"""Offline identity discovery, clue handoff and bounded quality fallback contracts."""
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json
from workflow_v24 import (RECALL_PLANNING_REVISION, generate_plan, product_clue_inventory,
                         product_analysis_readiness, validated_discovery_followup)
from serpapi_patents_client import fallback_satisfied
from runtime_v24 import execute_api_plan
from test_workflow_v24 import RecallIntegrityTests


class IdentityDiscoveryTests(unittest.TestCase):
    def setUp(self):
        RecallIntegrityTests.setUp(self)
        self.task["recall_planning_revision"] = RECALL_PLANNING_REVISION
        self.task["serper_free_enhancement"]["enabled"] = True
        self.task["serpapi_free_enhancement"]["enabled"] = True
        self.task["product"]["raw_capture"] = {"ocr_text": ["Lid Latch"], "visual_features": ["round hole"]}
        self.task["query_terms"].extend([
            {"kind": "ocr", "value": "Lid Latch", "language": "en", "derived_from": "product.raw_capture.ocr_text[0]"},
            {"kind": "design", "value": "round hole", "language": "en", "derived_from": "product.raw_capture.visual_features[0]"},
        ])
        self.map_clues()

    tearDown = RecallIntegrityTests.tearDown
    confirm = RecallIntegrityTests.confirm

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)

    def map_clues(self):
        self.task["product"]["analysis"]["clue_dispositions"] = [
            {"source_path": clue["source_path"], "source_sha256": clue["source_sha256"],
             "disposition": "mapped", "reason": "Analysed visible feature or marking",
             "query_term_sha256": [sha256_json(t) for t in self.task["query_terms"] if t["derived_from"] == clue["source_path"]]}
            for clue in product_clue_inventory(self.task)
        ]
        self.save()

    def test_identity_patent_and_dispute_queries_preserve_all_sources_not_assignee(self):
        plan = generate_plan(self.path)
        for provider in ("serper_patents", "serpapi_google_patents"):
            row = next(r for r in plan["queries"][provider] if "Lid Latch" in r["q"])
            self.assertIn("Example", row["q"])
            self.assertIn("NotAnAssignee", row["q"])
            self.assertIn("(Synthetic AND Inventor)", row["q"])
            self.assertIn("product.manufacturer", row["derived_from"])
            self.assertEqual(row["right_type"], "patent")
            self.assertFalse(row["authoritative_for_final_rating"])
        web = [r["q"] for r in plan["queries"]["serper_web"]]
        self.assertTrue(any(" patent" in q for q in web))
        self.assertTrue(any("lawsuit OR infringement" in q for q in web))
        self.assertFalse(any("NotAnAssignee" in r["q"] for r in plan["queries"]["uspto_patent_browser"]))
        self.assertEqual(plan["recall_planning_revision"], RECALL_PLANNING_REVISION)

    def test_missing_or_stale_handoff_blocks_new_plan(self):
        for mutation in (lambda rows: rows.pop(), lambda rows: rows[0].update(source_sha256="0" * 64),
                         lambda rows: rows[0].update(query_term_sha256=["0" * 64]),
                         lambda rows: rows[0].update(reason="")):
            with self.subTest(mutation=mutation):
                self.map_clues()
                mutation(self.task["product"]["analysis"]["clue_dispositions"])
                self.save()
                with self.assertRaisesRegex(ValueError, "PRODUCT_CLUE_UNACCOUNTED"):
                    generate_plan(self.path)
                self.assertFalse((self.path / "search-plan.json").exists())

    def test_exclusion_and_unknown_are_explicit_and_not_query_generation(self):
        self.task["product"]["raw_capture"]["ocr_text"].extend(["unknown", "", "未知"])
        rows = self.task["product"]["analysis"]["clue_dispositions"]
        rows[-1].update(disposition="excluded", reason="Shape is a photographic reflection, not product geometry")
        rows[-1].pop("query_term_sha256")
        self.save()
        self.assertEqual(len(product_clue_inventory(self.task)), 4)
        self.assertTrue(product_analysis_readiness(self.task)["ready"])

    def test_existing_plan_is_unchanged_and_new_clues_are_checked(self):
        before = generate_plan(self.path)
        self.task["product"]["raw_capture"]["ocr_text"].append("New mark")
        self.save()
        with self.assertRaisesRegex(ValueError, "PRODUCT_CLUE_UNACCOUNTED"):
            generate_plan(self.path)
        with self.assertRaisesRegex(ValueError, "PRODUCT_CLUE_UNACCOUNTED"):
            generate_plan(self.path, expand=True)
        self.assertEqual(before, load_json(self.path / "search-plan.json"))

    def test_caps_and_existing_hashes_unchanged_by_expansion(self):
        self.task["images"] = [{"source_url": "https://m.media-amazon.com/images/I/example.jpg", "sha256": "fixture"}]
        self.save()
        before = generate_plan(self.path)
        after = generate_plan(self.path, expand=True)
        self.assertEqual(before["queries"], after["queries"])
        self.assertLessEqual(sum(len(v) for k, v in after["queries"].items() if k.startswith("serpapi_")), 3)
        self.assertEqual(len(after["queries"]["serpapi_google_lens"]), 1)
        for provider, cap in (("serper_patents", 4), ("serper_web", 3), ("serper_images", 3)):
            self.assertLessEqual(len(after["queries"].get(provider, [])), cap)

    def test_disabled_sources_stay_disabled(self):
        self.task["serper_free_enhancement"]["enabled"] = False
        self.task["serpapi_free_enhancement"]["enabled"] = False
        self.save()
        self.assertFalse(any(p.startswith(("serper", "serpapi")) for p in generate_plan(self.path)["queries"]))

    def test_identity_text_is_not_mislabeled_as_english(self):
        self.task["query_terms"].append({"kind": "manufacturer", "value": "中文供应商", "language": "en", "derived_from": "evidence:original-name"})
        self.save()
        plan = generate_plan(self.path)
        self.assertTrue(any(g["code"] == "IDENTITY_TARGET_SCRIPT_MISSING" for g in plan["planning_gaps"]))
        self.assertFalse(any("中文" in r["q"] for p, rows in plan["queries"].items() if p.startswith(("serper", "serpapi")) for r in rows))

    def test_null_terms_and_malformed_dispositions_have_defined_gaps(self):
        self.task["query_terms"] = None
        self.assertFalse(product_analysis_readiness(self.task)["ready"])
        self.task["product"]["analysis"]["clue_dispositions"] = {"unexpected": "object"}
        self.assertIn("CLUE_DISPOSITIONS_INVALID", [g["code"] for g in product_analysis_readiness(self.task)["gaps"]])

    def fallback_fixture(self):
        plan = generate_plan(self.path)
        row = plan["queries"]["serpapi_google_patents"][0]
        primary = next(r for r in plan["queries"]["serper_patents"] if r["query_id"] == row["fallback_query_id"])
        raw = self.path / "fixture-serper.json"
        atomic_write_json(raw, {"organic": []})
        run = {"run_id": "RUN-PRIMARY", "provider": "serper_patents", "status": "no_result",
               "query_id": primary["query_id"], "plan_entry_sha256": sha256_json(primary),
               "raw_paths": [str(raw)], "payload_digest": sha256_file(raw), "finished_at": now_iso()}
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"] = [run]
        evidence["collections"]["patents"] = [{"evidence_id": "EV-PRIMARY", "source_run_id": "RUN-PRIMARY", "payload": {"candidates": []}}]
        atomic_write_json(self.path / "evidence.json", evidence)
        decision = {"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                    "source_run_id": "RUN-PRIMARY", "evidence_ids": ["EV-PRIMARY"],
                    "reason_code": "zero_results", "reason": "A second index is needed after exact zero results", "reviewer": "offline-agent"}
        return plan, row, evidence, decision

    def test_quality_fallback_explicit_bound_and_legacy_default_unchanged(self):
        plan, row, evidence, decision = self.fallback_fixture()
        args = dict(task_dir=self.path, task=self.task, plan=plan)
        self.assertTrue(fallback_satisfied(evidence, row, **args))
        self.task["discovery_followups"] = [decision]
        self.assertFalse(fallback_satisfied(evidence, row, **args))
        self.assertEqual(validated_discovery_followup(self.path, self.task, plan, evidence, row), decision)
        for key, value in (("plan_entry_sha256", "0" * 64), ("source_run_id", "missing"),
                           ("evidence_ids", ["unrelated"]), ("reason", ""), ("reviewer", "")):
            changed = copy.deepcopy(self.task)
            changed["discovery_followups"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "DISCOVERY_FOLLOWUP"):
                validated_discovery_followup(self.path, changed, plan, evidence, row)
        historical = copy.deepcopy(self.task)
        historical.pop("recall_planning_revision")
        self.assertIsNone(validated_discovery_followup(self.path, historical, plan, evidence, row))

    def test_unknown_or_malformed_followup_is_not_silently_ignored(self):
        plan, row, evidence, decision = self.fallback_fixture()
        for followups in ([None], [{"query_id": "missing"}], {"unexpected": "object"}):
            self.task["discovery_followups"] = followups
            with self.subTest(followups=followups), self.assertRaisesRegex(ValueError, "DISCOVERY_FOLLOWUPS_INVALID"):
                validated_discovery_followup(self.path, self.task, plan, evidence, row)

    def test_missing_expired_or_changed_evidence_cannot_authorize_quality_fallback(self):
        plan, row, evidence, decision = self.fallback_fixture()
        self.task["discovery_followups"] = [decision]
        run = evidence["source_runs"][0]
        run["finished_at"] = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        with self.assertRaisesRegex(ValueError, "DISCOVERY_FOLLOWUP_SOURCE_INVALID"):
            validated_discovery_followup(self.path, self.task, plan, evidence, row)
        run["finished_at"] = now_iso()
        run["payload_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "DISCOVERY_FOLLOWUP_SOURCE_INVALID"):
            validated_discovery_followup(self.path, self.task, plan, evidence, row)

    def test_foreign_task_or_explicit_fixture_cannot_authorize_quality_fallback(self):
        plan, row, evidence, decision = self.fallback_fixture()
        self.task["discovery_followups"] = [decision]
        foreign = copy.deepcopy(evidence)
        foreign["task_id"] = "FOREIGN"
        with self.assertRaisesRegex(ValueError, "DISCOVERY_FOLLOWUP_TASK_MISMATCH"):
            validated_discovery_followup(self.path, self.task, plan, foreign, row)
        evidence["source_runs"][0]["source_environment"] = "test_fixture"
        with self.assertRaisesRegex(ValueError, "DISCOVERY_FOLLOWUP_NON_PRODUCTION"):
            validated_discovery_followup(self.path, self.task, plan, evidence, row)

    def test_scheduler_and_client_use_same_quality_decision(self):
        plan, row, evidence, decision = self.fallback_fixture()
        self.task["discovery_followups"] = [decision]
        self.save()
        primary = plan["queries"]["serper_patents"][0]
        plan["queries"] = {"serper_patents": [primary], "serpapi_google_patents": [row]}
        atomic_write_json(self.path / "search-plan.json", plan)
        response = SimpleNamespace(returncode=0, stdout=json.dumps({"provider": "serpapi_google_patents", "query_id": row["query_id"], "status": "no_result"}), stderr="")
        with patch("runtime_v24.capabilities", return_value=[{"provider": "serpapi_google_patents", "executable": True}]), patch("runtime_v24.subprocess.run", return_value=response) as call:
            output = execute_api_plan(self.path)
        self.assertEqual(call.call_count, 1)
        result = next(r for r in output["results"] if r["provider"] == "serpapi_google_patents")
        self.assertNotEqual(result["dispatch"], "fallback_reused")
        self.assertEqual(result["discovery_followup_sha256"], sha256_json(decision))


if __name__ == "__main__":
    unittest.main()
