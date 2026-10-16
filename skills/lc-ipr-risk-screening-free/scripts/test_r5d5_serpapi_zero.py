"""r5d5: SerpApi Google Patents' exact zero-result envelope proves zero (B0GLNPC6K8 real run).

SerpApi omits ``organic_results`` when a search finds nothing. The receipt then had no result list to count, the
zero was never proven, the query stayed SOURCE_RESULTS_PENDING_PROCESSING and API_DISCOVERY_SOURCE_CARDS_INVALID,
and light triage held back every other source until the core stage stopped with PIPELINE_READY_SOURCES_UNDISPATCHED.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, sha256_bytes
from source_result_processing import REVISION, _serpapi_empty_search, make_index, progress, work_entries

ZERO = {"error": "Google Patents hasn't returned any results for this query.",
        "search_information": {"organic_results_state": "Fully empty", "page_number": 1, "total_pages": 0,
                               "total_results": 0},
        "search_metadata": {"id": "abc", "status": "Success", "json_endpoint": "https://serpapi.com/searches/x.json"},
        "search_parameters": {"country": "US", "engine": "google_patents", "num": "10", "q": "butterfly cat toy",
                              "type": "DESIGN"}}


def body_of(value):
    return json.dumps(value, sort_keys=True).encode()


class SerpApiZeroTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {"task_id": "TASK-R5D5", "result_processing_revision": REVISION}
        atomic_write_json(self.root / "task.json", self.task)

    def index(self, body, **overrides):
        options = dict(provider="serpapi_google_patents", evidence_type="patent", status="no_result",
                       submission_state="submitted", raw_body=body, raw_suffix="json", normalized={"candidates": []},
                       coverage={"retrieved_hits": 0, "schema_valid": True}, payload_digest=sha256_bytes(body))
        options.update(overrides)
        return make_index(self.task, **options)

    def run_of(self, body, index):
        path = self.root / "raw" / "serpapi_google_patents" / "QRY-1_zero.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        run = {"run_id": "ATT-1", "query_id": "QRY-1", "provider": "serpapi_google_patents", "operation": "search",
               "evidence_type": "patent", "status": "no_result", "submission_state": "submitted",
               "raw_paths": [path.relative_to(self.root).as_posix()], "payload_digest": sha256_bytes(body),
               "result_processing": index,
               "metadata": {"search_coverage": {"retrieved_hits": 0, "schema_valid": True}}}
        evidence = {"source_runs": [run], "collections": {"patents": [{
            "source_run_id": "ATT-1", "payload": {"candidates": []}}]}}
        atomic_write_json(self.root / "evidence.json", evidence)
        return run, evidence

    def test_exact_zero_envelope_proves_zero_at_record_time(self):
        body = body_of(ZERO)
        index = self.index(body)
        self.assertEqual((index["returned_count"], index["returned_count_basis"]), (0, "retained_rows"))
        self.assertTrue(index["zero_proven"])
        run, evidence = self.run_of(body, index)
        state = progress(self.root, run, evidence)
        self.assertTrue(state["zero_proven"])
        self.assertTrue(state["material_processing_complete"])
        self.assertEqual(work_entries(self.task, evidence, self.root), [])
        # the older engine wording and an explicit empty list are the same envelope
        older = dict(ZERO, error="Google hasn't returned any results for this query.", organic_results=[])
        self.assertTrue(self.index(body_of(older))["zero_proven"])

    def test_index_recorded_before_the_fix_is_projected_without_any_write(self):
        # the real run's stored index: response_count_only, zero not proven
        body = body_of(ZERO)
        index = {**self.index(body), "returned_count_basis": "response_count_only", "zero_proven": False}
        run, evidence = self.run_of(body, index)
        file_before = (self.root / "evidence.json").read_bytes()
        state = progress(self.root, run, evidence)
        self.assertTrue(state["zero_proven"])
        self.assertTrue(state["material_processing_complete"])
        self.assertEqual((self.root / "evidence.json").read_bytes(), file_before)
        (self.root / run["raw_paths"][0]).write_bytes(body + b" ")
        with self.assertRaises(ValueError):
            progress(self.root, run, evidence)

    def test_lookalikes_and_other_errors_never_prove_zero(self):
        variants = [dict(ZERO, error="Invalid API key."),
                    dict(ZERO, error="Google Patents hasn't returned any results for this query. Retry"),
                    dict(ZERO, search_metadata={"status": "Error"}),
                    dict(ZERO, search_parameters={**ZERO["search_parameters"], "engine": "google_patents_details"}),
                    dict(ZERO, search_information={**ZERO["search_information"], "total_results": 3}),
                    dict(ZERO, search_information={**ZERO["search_information"], "total_results": False}),
                    dict(ZERO, search_information={**ZERO["search_information"],
                                                   "organic_results_state": "Results for exact spelling"}),
                    dict(ZERO, organic_results=[{"patent_id": "patent/USD1/en"}]),
                    dict(ZERO, extra_block={"anything": 1}),
                    {k: v for k, v in ZERO.items() if k != "error"}]
        for value in variants:
            with self.subTest(value=value):
                body = body_of(value)
                self.assertFalse(_serpapi_empty_search(body, "json", "serpapi_google_patents"))
                index = self.index(body)
                self.assertFalse(index["zero_proven"])
        body = body_of(ZERO)
        self.assertFalse(_serpapi_empty_search(body, "json", "serper_patents"))
        self.assertFalse(_serpapi_empty_search(body, "xml", "serpapi_google_patents"))
        for status, submitted, schema in (("failed", "submitted", True), ("no_result", "unknown", True),
                                          ("no_result", "submitted", False)):
            with self.subTest(status=status, submitted=submitted, schema=schema):
                self.assertFalse(self.index(body, status=status, submission_state=submitted,
                                            coverage={"retrieved_hits": 0, "schema_valid": schema})["zero_proven"])

    def test_stored_index_projection_needs_the_whole_zero_context(self):
        body = body_of(ZERO)
        index = {**self.index(body), "returned_count_basis": "response_count_only", "zero_proven": False}
        run, evidence = self.run_of(body, index)
        changes = [lambda r, e: r.update(status="failed"),
                   lambda r, e: r.update(submission_state="unknown"),
                   lambda r, e: r.update(operation="candidate_detail"),
                   lambda r, e: r["metadata"]["search_coverage"].update(schema_valid=False),
                   lambda r, e: r["result_processing"].update(count_contradiction=True),
                   lambda r, e: r["result_processing"].update(declared_retrieved_count=1),
                   lambda r, e: e["collections"]["patents"][0]["payload"].update(
                       candidates=[{"publication_number": "USD1S1"}])]
        for position, change in enumerate(changes):
            changed = deepcopy(evidence)
            candidate = changed["source_runs"][0]
            change(candidate, changed)
            with self.subTest(position=position):
                self.assertFalse(progress(self.root, candidate, changed)["zero_proven"])

    def test_source_card_contract_accepts_the_zero_envelope_only(self):
        from api_first_planning import source_files_error
        body = body_of(ZERO)
        run, evidence = self.run_of(body, self.index(body))
        with patch("runtime_v24.source_files_complete", return_value=True), \
                patch("assessment_v24._source_records", return_value=[]):
            self.assertIsNone(source_files_error(self.root, evidence, run))
            (self.root / run["raw_paths"][0]).write_bytes(body_of(dict(ZERO, error="Invalid API key.")))
            self.assertEqual(source_files_error(self.root, evidence, run), "API_DISCOVERY_SOURCE_CARDS_INVALID")
            (self.root / run["raw_paths"][0]).write_bytes(body)
            self.assertEqual(source_files_error(self.root, evidence, {**run, "status": "success"}),
                             "API_DISCOVERY_SOURCE_CARDS_INVALID")


if __name__ == "__main__":
    unittest.main()
