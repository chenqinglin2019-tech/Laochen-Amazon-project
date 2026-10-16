"""best-estimate-risk-v1 flow: marking resolution first, core candidates before discovery, memoized views."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import atomic_write_json, load_json
import advance_work
import product_scope
import work_view_memo
import test_product_entry as fixture_module
import test_product_scope as scope_fixture


def _view(entries):
    return {"entries": entries, "review_work": {"entries": []}}


class CoreFirstOrderTests(unittest.TestCase):
    PLAN = {"queries": {
        "serpapi_google_patents": [
            {"query_id": "Q-disc", "execution_phase": "discovery"},
            {"query_id": "Q-mark", "execution_phase": "discovery", "discovery_role": "marking_resolution"},
            {"query_id": "Q-detail", "execution_phase": "verification", "candidate_id": "CAND-1"}],
        "serper_web": [{"query_id": "Q-web", "execution_phase": "discovery"}]}}
    ENTRIES = [
        {"kind": "source_lookup", "state": "ready", "query_id": "Q-disc", "provider": "serpapi_google_patents", "work_id": "W1"},
        {"kind": "source_lookup", "state": "ready", "query_id": "Q-web", "provider": "serper_web", "work_id": "W2"},
        {"kind": "source_lookup", "state": "ready", "query_id": "Q-detail", "provider": "serpapi_google_patents",
         "candidate_id": "CAND-1", "work_id": "W3"},
        {"kind": "source_lookup", "state": "ready", "query_id": "Q-mark", "provider": "serpapi_google_patents", "work_id": "W4"},
        {"kind": "triage", "state": "ready", "reason": "TRIAGE_REVIEW_REQUIRED", "work_id": "A1"},
        {"kind": "agent_read", "state": "ready", "reason": "ORIGINAL_READING_REQUIRED", "work_id": "A2"},
        {"kind": "professional_review", "state": "ready", "reason": "SPECIALTY_REVIEW_REQUIRED", "candidate_id": "CAND-1", "work_id": "A3"},
        {"kind": "product_analysis", "state": "ready", "reason": "PRODUCT_SCOPE_REVIEW_REQUIRED", "work_id": "A4"},
        {"kind": "product_analysis", "state": "ready", "reason": "PATENT_MARKING_RESOLUTION_REQUIRED", "work_id": "WORK-patent-marking"},
        {"kind": "agent_investigation", "state": "awaiting_review", "reason": "SOURCE_OPERATION_REVIEW_REQUIRED", "work_id": "A6"},
        {"kind": "source_lookup", "state": "awaiting_access", "query_id": "Q-web", "provider": "serper_web", "work_id": "WAIT"},
    ]

    def test_marked_tasks_order_core_work_first_and_others_keep_their_order(self):
        marked = {"best_estimate_revision": "best-estimate-risk-v1"}
        packet = advance_work.actionable_packet(_view(self.ENTRIES), task=marked, plan=self.PLAN)
        self.assertEqual([e["work_id"] for e in packet["source"]], ["W4", "W3", "W1", "W2"])
        self.assertEqual([e["work_id"] for e in packet["agent"]], ["WORK-patent-marking", "A4", "A3", "A2", "A1", "A6"])
        self.assertEqual([e["work_id"] for e in packet["waiting"]], ["WAIT"])
        historical = advance_work.actionable_packet(_view(self.ENTRIES), task={}, plan=self.PLAN)
        self.assertEqual([e["work_id"] for e in historical["source"]], ["W1", "W2", "W3", "W4"])
        self.assertEqual([e["work_id"] for e in historical["agent"]], ["A1", "A2", "A3", "A4", "WORK-patent-marking", "A6"])
        self.assertEqual(advance_work.actionable_packet(_view(self.ENTRIES)), historical)
        # the budget-limited source dispatch follows the same order
        entries, deferred = advance_work.source_entries_after_triage_priority(marked, _view(self.ENTRIES), self.PLAN)
        self.assertFalse(deferred)
        self.assertEqual([e["work_id"] for e in entries], ["W4", "W3", "W1", "W2"])


class MarkingEntryTests(scope_fixture.ScopeTests):
    TITLE = "Folding stand (PATENTED)"

    def setUp(self):
        original = fixture_module.ProductEntryTests.write_input

        def write_input(inner):
            inner.data["product"]["title"] = self.TITLE
            original(inner)
        with mock.patch.object(fixture_module.ProductEntryTests, "write_input", write_input):
            super().setUp()
        self.data["scope"]["facts"][1]["value"] = self.TITLE

    def test_patented_title_adds_the_marking_entry_first_with_its_card(self):
        task = self.save()
        self.assertTrue(product_scope.enabled(task))
        entries = product_scope.work_entries(task)
        marking = [e for e in entries if e["reason"] == "PATENT_MARKING_RESOLUTION_REQUIRED"]
        self.assertEqual(len(marking), 1)
        self.assertEqual(marking[0]["work_id"], "WORK-patent-marking")
        self.assertEqual((marking[0]["kind"], marking[0]["state"]), ("product_analysis", "ready"))
        self.assertFalse([e for e in product_scope.work_entries({**task, "best_estimate_revision": None})
                          if e["reason"] == "PATENT_MARKING_RESOLUTION_REQUIRED"])
        card = advance_work.action_card(self.run, marking[0])
        self.assertEqual(card["action"], "resolve_patent_marking_before_discovery")
        self.assertEqual(len(card["steps"]), 4)
        self.assertTrue(card["recorder"].endswith("record_product_analysis.py"))
        self.assertTrue(card["lead_recorder"].endswith("record_candidate_lead.py"))
        from workflow_v24 import work_view_from_dir
        view = work_view_from_dir(self.run)
        packet = advance_work.actionable_packet(view, task=task)
        self.assertEqual(packet["agent"][0]["work_id"], "WORK-patent-marking")
        # a completed follow-up closes the entry
        task["product"]["patent_claim_followup"] = {"status": "completed", "findings": "US11401089B2 from the brand's marking page",
                                                    "evidence_ids": ["EV-X"]}
        self.assertFalse([e for e in product_scope.work_entries(task) if e["reason"] == "PATENT_MARKING_RESOLUTION_REQUIRED"])


class UnmarkedTitleTests(scope_fixture.ScopeTests):
    def test_unmarked_title_adds_nothing(self):
        task = self.save()
        self.assertFalse([e for e in product_scope.work_entries(task) if e["reason"] == "PATENT_MARKING_RESOLUTION_REQUIRED"])


class WorkViewMemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        atomic_write_json(self.root / "task.json", {"task_id": "T", "best_estimate_revision": "best-estimate-risk-v1"})
        (self.root / "raw").mkdir()
        (self.root / "raw" / "receipt.bin").write_bytes(b"abc")
        self.calls = 0

    def compute(self):
        self.calls += 1
        return {"n": self.calls, "nested": [1, {"a": "b"}]}

    def test_reused_until_any_file_changes(self):
        first = work_view_memo.cached(self.root, "unit", {"opt": 1}, self.compute)
        second = work_view_memo.cached(self.root, "unit", {"opt": 1}, self.compute)
        self.assertEqual((first, second, self.calls), ({"n": 1, "nested": [1, {"a": "b"}]}, first, 1))
        second["nested"].append(2)                                  # a served copy never leaks into the memo
        self.assertEqual(work_view_memo.cached(self.root, "unit", {"opt": 1}, self.compute)["nested"], [1, {"a": "b"}])
        work_view_memo.cached(self.root, "unit", {"opt": 2}, self.compute)      # other options: own entry
        self.assertEqual(self.calls, 2)
        (self.root / "raw" / "receipt.bin").write_bytes(b"abd")
        work_view_memo.cached(self.root, "unit", {"opt": 1}, self.compute)
        self.assertEqual(self.calls, 3)
        atomic_write_json(self.root / "evidence.json", {"collections": {}})
        work_view_memo.cached(self.root, "unit", {"opt": 1}, self.compute)
        self.assertEqual(self.calls, 4)
        work_view_memo.cached(self.root, "other", {"opt": 1}, self.compute)     # other name: own entry
        self.assertEqual(self.calls, 5)

    def test_disabled_without_the_marker_or_by_environment(self):
        atomic_write_json(self.root / "task.json", {"task_id": "T"})
        for _ in range(2):
            work_view_memo.cached(self.root, "unit", {}, self.compute)
        self.assertEqual(self.calls, 2)
        atomic_write_json(self.root / "task.json", {"task_id": "T", "best_estimate_revision": "best-estimate-risk-v1"})
        with mock.patch.dict(os.environ, {"LC_IPR_WORK_VIEW_MEMO": "0"}):
            for _ in range(2):
                work_view_memo.cached(self.root, "unit", {}, self.compute)
        self.assertEqual(self.calls, 4)

    def test_memo_lives_outside_the_task_directory(self):
        work_view_memo.cached(self.root, "unit", {}, self.compute)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["raw", "task.json"])
        store = work_view_memo._store_dir(self.root)
        self.assertTrue(any(p.name.startswith("unit-") for p in store.iterdir()))
        saved = json.loads(next(store.glob("unit-*.json")).read_text(encoding="utf-8"))
        self.assertEqual(saved["value"]["n"], 1)


for _cls in (MarkingEntryTests, UnmarkedTitleTests):
    for _name in [n for n in dir(scope_fixture.ScopeTests) if n.startswith("test_") and n not in vars(_cls)]:
        setattr(_cls, _name, None)

if __name__ == "__main__":
    unittest.main()
