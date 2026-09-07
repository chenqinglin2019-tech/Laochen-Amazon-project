import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from record_browser_execution import planned_browser_query, validate_browser_execution, validate_tm_result_binding, validate_tm_result_pages
from record_uspto_tmsearch_browser_result import normalize_candidate
from common import now_iso

ROOT = Path(__file__).resolve().parents[1]


def planned(value="26.17.13", field="design_code", strategy="classification"):
    return {"jurisdiction": "US", "operation": "trademark_recall", "right_type": "trademark_figurative",
            "q": value, "filters": {"field": field, "language": "en"}, "strategy": strategy,
            "query_compiler_revision": "tm-figurative-fields-v1", "derived_from": ["product.mark_inventory[0]"]}


class FigurativeFieldTests(unittest.TestCase):
    def test_python_js_compile_identically_without_turning_text_into_image_recall(self):
        examples = [planned(), planned("261713"), planned("parallel lines", "mark_description", "phrase"),
                    planned("line AND (horizontal OR vertical)", "mark_description", "boolean")]
        expected = [planned_browser_query("uspto_tmsearch_browser", row) for row in examples]
        code = "import {browserPlannedQuery} from './tools/cdp/cdp-cli.mjs'; process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map(q=>browserPlannedQuery('uspto_tmsearch_browser',q))));"
        result = subprocess.run(["node", "--input-type=module", "-e", code, json.dumps(examples)], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(expected[0]["rendered_query"], "DC:261713")
        self.assertEqual(expected[2]["rendered_query"], 'DE:"parallel lines"')
        self.assertEqual(expected[3]["rendered_query"], "DE:(line AND (horizontal OR vertical))")
        self.assertEqual([row["search_dimension"] for row in expected], ["classification", "classification", "description", "description"])

    def test_missing_provenance_legacy_fake_figurative_and_injection_stay_rejected(self):
        for row in [dict(planned(), derived_from=[]), dict(planned(), derived_from=["product.brand"]),
                    dict(planned(), query_compiler_revision="tm-field-tags-v1"),
                    planned("261713 OR *"), planned("26.17"), planned("横线", "mark_description", "phrase"),
                    planned('line) OR CM:*', "mark_description", "boolean"), planned('line" OR *', "mark_description", "phrase")]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                planned_browser_query("uspto_tmsearch_browser", row)

    def fixtures(self, folder):
        screenshot = folder / "screenshots" / "page.png"
        screenshot.parent.mkdir()
        screenshot.write_bytes(b"retained screenshot fixture")
        query = "DC:261713"
        pages = []
        for index in [1, 2]:
            binding = {"total_hits": 2, "result_query": query, "loading": False, "parsed_count": 1,
                       "result_view": "list", "query_bound": True, "input_value": query,
                       "rendered_query": query, "search_mode": "Field tag and Search builder"}
            pages.append({"page_index": index, "query_binding": binding,
                          "range": {"start": index, "end": index, "total": 2},
                          "candidates": [{"serial_number": f"9999999{index}", "mark_text": "TEST"}],
                          "screenshot_path": str(screenshot), "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()})
        return {"status": "success", "result_pages": pages, "query_binding": pages[-1]["query_binding"],
                "candidates": [row for page in pages for row in page["candidates"]],
                "result_coverage": {"total_hits": 2, "retrieved_hits": 2, "pages_retrieved": 2}}, query

    def test_bound_pages_aggregate_exact_candidates_without_overwriting_last_page_count(self):
        with tempfile.TemporaryDirectory() as directory:
            capture, query = self.fixtures(Path(directory))
            validate_tm_result_pages(capture, Path(directory), query)
            validate_tm_result_binding(capture, {"observed_count": 2}, query)
            self.assertEqual(capture["query_binding"]["parsed_count"], 1)

    def test_page_range_query_screenshot_and_candidate_changes_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            capture, query = self.fixtures(Path(directory))
            for change in ["range", "query", "hash", "candidate", "count"]:
                bad = copy.deepcopy(capture)
                if change == "range": bad["result_pages"][1]["range"]["start"] = 1
                if change == "query": bad["result_pages"][0]["query_binding"]["input_value"] = "OTHER"
                if change == "hash": bad["result_pages"][0]["screenshot_sha256"] = "0" * 64
                if change == "candidate": bad["candidates"][0] = {**bad["candidates"][0], "mark_text": "OTHER"}
                if change == "count": bad["result_coverage"]["retrieved_hits"] = 1
                with self.subTest(change=change), self.assertRaises(ValueError): validate_tm_result_pages(bad, Path(directory), query)

    def test_no_result_requires_true_zero_and_no_candidates(self):
        capture = {"status": "no_result", "candidates": [], "result_pages": [],
                   "query_binding": {"total_hits": 0, "loading": False, "parsed_count": 0, "result_view": "list", "result_query": "DC:261713"},
                   "result_coverage": {"total_hits": 0, "retrieved_hits": 0, "pages_retrieved": 1}}
        with tempfile.TemporaryDirectory() as folder:
            validate_tm_result_pages(capture, Path(folder), "DC:261713")
            validate_tm_result_binding(capture, {"observed_count": 0}, "DC:261713")
            capture["query_binding"]["total_hits"] = 2
            with self.assertRaises(ValueError): validate_tm_result_binding(capture, {"observed_count": 0}, "DC:261713")

    def test_nonverbal_candidate_keeps_missing_wordmark_explicit_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            shot = Path(folder) / "shot.png"
            shot.write_bytes(b"fixture")
            item = {"serial_number": "99999991", "mark_text": "", "mark_text_missing": True}
            result = normalize_candidate(item, str(shot), "fixture", "2026-09-07T00:00:00Z", {}, "trademark_figurative")
            self.assertEqual(result["mark_text"], "")
            self.assertTrue(result["mark_text_missing"])
            with self.assertRaises(ValueError): normalize_candidate(item, str(shot), "fixture", "2026-09-07T00:00:00Z", {}, "trademark_word")

    def test_javascript_receipt_is_accepted_by_python_for_real_page_shape_not_altered_semantics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capture, rendered = self.fixtures(root)
            query = {**planned(), "query_id": "Q-FIGURE-TEST"}
            task = {"schema_version": "2.4-free", "screening_revision": "recall-integrity-v1", "task_id": "T-FIXTURE"}
            (root / "search-plan.json").write_text(json.dumps({"queries": {"uspto_tmsearch_browser": [query]}}))
            at = now_iso()
            capture.update(query_id=query["query_id"], checked_at=at, final_url="https://tmsearch.uspto.gov/search/search-results",
                           screenshot_path=capture["result_pages"][-1]["screenshot_path"], rendered_query=rendered,
                           query_semantics=planned_browser_query("uspto_tmsearch_browser", query, task))
            events = [{"action": "submit_query", "actor": "agent", "at": at, "rendered_query": rendered, "input_value": rendered,
                       "search_mode": "Field tag and Search builder"},
                      {"action": "observe_result", "actor": "agent", "at": at, "stable": True, "observed_count": 2,
                       "query_binding": capture["query_binding"], "screenshot_sha256": capture["result_pages"][-1]["screenshot_sha256"]}]
            js = "import {executionReceipt} from './tools/cdp/cdp-cli.mjs'; const x=JSON.parse(process.argv[1]);process.stdout.write(JSON.stringify(executionReceipt(x.task,'uspto_tmsearch_browser',x.query,x.events,x.capture)));"
            result = subprocess.run(["node", "--input-type=module", "-e", js, json.dumps(dict(task=task, query=query, events=events, capture=capture))], cwd=ROOT, capture_output=True, text=True, check=True)
            receipt = root / "raw/browser-execution/fixture.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(result.stdout)
            capture["query_execution"] = {"path": str(receipt), "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
            validate_browser_execution(capture, task, root, "uspto_tmsearch_browser")
            capture["query_semantics"]["field_code"] = "CM"
            with self.assertRaisesRegex(ValueError, "semantics differ"):
                validate_browser_execution(capture, task, root, "uspto_tmsearch_browser")


if __name__ == "__main__":
    unittest.main()
