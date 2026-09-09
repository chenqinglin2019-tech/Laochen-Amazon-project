"""Count retained source rows separately from exact publication identities."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from assessment_v24 import query_coverage
from common import sha256_json
from record_browser_execution import ppubs_row_coverage, ppubs_counting_complete

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/ppubs-duplicate-rows.json").read_text())


def coverage():
    return {"coverage_counting_revision": "ppubs-result-rows-v1", "total_hits": 37, "retrieved_hits": 20,
            "schema_valid": True, "truncated": False, "stop_reason": "browser_results_exhausted",
            "viewport_gaps": [], "unconfirmed_family_member_count": 0, "family_expansion": {"gaps": []},
            "row_coverage": ppubs_row_coverage(FIXTURE["pages"], 37)}


class PpubsRowCountTests(unittest.TestCase):
    def test_real_ordinal_fixture_preserves_both_count_units_and_rejects_missing_conflicting_or_unexpanded_rows(self):
        good = coverage()
        self.assertTrue(ppubs_counting_complete(good))
        self.assertEqual(good["row_coverage"]["retrieved_rows"], 37)
        self.assertEqual(good["row_coverage"]["unique_publications"], 20)
        for kind in ("missing", "conflict", "family", "bottom", "loading"):
            pages = deepcopy(FIXTURE["pages"])
            views = pages[0]["viewports"]
            if kind == "missing":
                for view in views:
                    view["rows"] = [r for r in view["rows"] if r["rowNumber"] != "2"]
            elif kind == "conflict":
                views[-1]["rows"].append({"rowNumber": "1", "documentId": "US D999999 S"})
            elif kind == "family":
                views[-1]["rows"][0]["familyGroup"] = "+1"
            elif kind == "bottom":
                views[-1]["viewport"]["top"] = 0
            else:
                views[-1]["loading"] = True
            bad = {**good, "row_coverage": ppubs_row_coverage(pages, 37)}
            self.assertFalse(ppubs_counting_complete(bad), kind)
        for key, value in (("viewport_gaps", [{"reason": "not stable"}]), ("unconfirmed_family_member_count", 1)):
            self.assertFalse(ppubs_counting_complete({**good, key: value}))

    def test_assessment_accepts_row_retrieval_without_claiming_candidate_review_or_reinterpreting_legacy_counts(self):
        query = {"query_id": "Q1", "operation": "design_recall", "jurisdiction": "US", "right_type": "design"}
        proof = coverage()
        run = {"run_id": "R1", "provider": "uspto_patent_browser", **query, "plan_entry_sha256": sha256_json(query),
               "status": "success", "metadata": {"search_coverage": proof}}
        records = [{"publication_number": record} for record in sorted({row[1] for row in proof["row_coverage"]["ordinal_records"]})]
        entry = {"evidence_id": "EV1", "source_run_id": "R1", "payload": {"candidates": records},
                 **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "plan_entry_sha256")}}
        evidence = {"source_runs": [run], "collections": {"patents": [entry]}}
        plan = {"queries": {"uspto_patent_browser": [query]}}
        check = lambda: query_coverage(evidence, {}, plan, "uspto_patent_browser", query)
        self.assertEqual(check()["gap"], "CANDIDATES_NOT_BOUND_OR_REVIEWED")
        records[0]["publication_number"] = "USD999999S"
        self.assertEqual(check()["gap"], "SOURCE_RECORD_IDENTITY_NOT_ACCOUNTED_FOR")
        proof.pop("coverage_counting_revision")
        self.assertEqual(check()["gap"], "SEARCH_TRUNCATED")


if __name__ == "__main__":
    unittest.main()
