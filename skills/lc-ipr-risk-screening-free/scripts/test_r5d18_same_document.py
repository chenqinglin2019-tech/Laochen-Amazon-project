"""r5d18 (run B0H16FDSD8, 2026-10-14): one document in two spellings.

EPO's search card USD1035381S and Google's USD1035381S1 name one design patent. They stayed two candidates, each got its
own detail read, comparison and screen; the dossier took the newer record of the number for both, so the older record
was never registered as read and the run stopped at checkpoint 2 (SOURCE_RESULTS_PENDING_PROCESSING).

Golden replay of the real run (scratchpad golden18/g18.py): readiness reproduces the single blocker, the catch-up dossier
step registers the twin record's reading, readiness passes and the final-review preflight is ready.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

import candidate_identity as ci
import core_dossier
import merge_candidates as mc
import pipeline_robust

SCRIPTS = Path(__file__).resolve().parent


def scope(number):
    return {"publication_number": number, "jurisdiction": "US", "right_type": "design"}


class IdentityKeyTests(unittest.TestCase):
    def test_docdb_and_google_spellings_share_one_key_on_new_tasks(self):
        for docdb, google in (("USD1035381S", "USD1035381S1"), ("US2014020569A1", "US20140020569A1")):
            left = ci.identity_key("patent", scope(docdb), "A1", canonical=True)
            right = ci.identity_key("patent", scope(google), "A2", canonical=True)
            self.assertEqual(left, right)
            self.assertEqual(left[1], "exact_document_number")

    def test_older_tasks_keep_one_key_per_spelling(self):
        self.assertNotEqual(ci.identity_key("patent", scope("USD1035381S"), "A1"),
                            ci.identity_key("patent", scope("USD1035381S1"), "A2"))

    def test_other_numbers_and_rows_without_a_number_are_unchanged(self):
        self.assertEqual(ci.identity_key("patent", scope("US11234567B2"), "A", canonical=True),
                         ci.identity_key("patent", scope("US11234567B2"), "A"))
        self.assertEqual(ci.identity_key("patent", scope(""), "A", canonical=True), ("patent:provisional:A", "identity_pending"))

    def test_the_marker(self):
        self.assertFalse(ci.canonical_numbers({}))
        self.assertTrue(ci.canonical_numbers({"candidate_number_revision": ci.NUMBER_REVISION}))
        with self.assertRaises(ValueError):
            ci.canonical_numbers({"candidate_number_revision": "other"})


class MergeTests(unittest.TestCase):
    """The real cards of run B0H16FDSD8, shortened."""

    def entries(self):
        epo = {"evidence_id": "EV-EPO", "source_run_id": "ATT-EPO", "provider": "epo_ops", "operation": "search",
               "jurisdiction": "US", "right_type": "patent", "collected_at": "2026-10-14T00:05:12Z",
               "payload": {"candidates": [{
                   "applicants": ["Shenzhen Haipin Yigou Trading Co., Ltd."], "application_number": "US202329877409F",
                   "authoritative_for_final_rating": True, "family_id": "91845549", "jurisdiction": "US", "kind_code": "S",
                   "publication_number": "USD1035381S", "publication_numbers": ["USD1035381S"],
                   "retrieval_workflow_revision": "api-first-v3", "source": "epo_ops", "title": "Rolling grilling basket",
                   "source_position": 4}]}}
        google = {"evidence_id": "EV-GP", "source_run_id": "ATT-GP", "provider": "serpapi_google_patents",
                  "operation": "search", "jurisdiction": "US", "right_type": "design",
                  "collected_at": "2026-10-14T00:05:22Z",
                  "payload": {"candidates": [{
                      "assignee": "Shenzhen Haipin Yigou Trading Co., Ltd.", "grant_date": "2024-07-16", "jurisdiction": "US",
                      "publication_number": "USD1035381S1", "retrieval_workflow_revision": "api-first-v3",
                      "source": "serpapi_google_patents", "source_index": "google_patents", "title": "Rolling grilling basket",
                      "figures": [{"full": "https://patentimages.storage.googleapis.com/x/USD1035381-20240716-D00000.png"}],
                      "source_position": 1, "source_record_sha256": "6" * 64}]}}
        return [epo, google]

    def merged(self, canonical):
        return mc.merge("patent", self.entries(), {}, identity_revision=ci.REVISION, canonical_numbers=canonical)

    def test_new_tasks_get_one_candidate_with_both_cards(self):
        rows = self.merged(True)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["right_type"], "design")
        self.assertEqual(row["normalization_key"], "US:design:publication:USD1035381S1")
        self.assertEqual([source["evidence_id"] for source in row["sources"]], ["EV-EPO", "EV-GP"])
        self.assertNotIn("publication_number", row["conflicts"])          # one document, two spellings: no conflict
        self.assertEqual([claim["value"] for claim in row["field_claims"]["publication_number"]],
                         ["USD1035381S", "USD1035381S1"])                 # every original spelling stays traceable
        self.assertEqual(row["application_number"], "US202329877409F")    # EPO facts and Google figures both kept
        self.assertEqual(len(row["figures"]), 1)

    def test_the_google_spelling_gives_the_same_candidate_whichever_card_comes_first(self):
        first = self.merged(True)[0]["candidate_id"]
        entries = list(reversed(self.entries()))
        second = mc.merge("patent", entries, {}, identity_revision=ci.REVISION, canonical_numbers=True)
        self.assertEqual([row["candidate_id"] for row in second], [first])

    def test_older_tasks_keep_two_candidates(self):
        rows = self.merged(False)
        self.assertEqual(sorted(row["publication_number"] for row in rows), ["USD1035381S", "USD1035381S1"])

    def test_the_merge_step_reads_the_marker(self):
        text = (SCRIPTS / "merge_candidates.py").read_text(encoding="utf-8")
        self.assertIn("canonical = bool(identity_revision) and canonical_numbers(task)", text)
        self.assertIn("evidence=evidence, canonical_numbers=canonical)", text)
        create = (SCRIPTS / "create_task.py").read_text(encoding="utf-8")
        self.assertIn("task['candidate_number_revision'] = NUMBER_REVISION", create)


class SameDocumentReadingTests(unittest.TestCase):
    def evidence(self):
        detail = lambda run, number: {"evidence_id": "EV-" + run, "source_run_id": run, "provider": "serpapi_google_patents",
                                      "operation": "candidate_detail", "payload": {"publication_number": number}}
        run = lambda run_id: {"run_id": run_id, "provider": "serpapi_google_patents", "operation": "candidate_detail",
                              "status": "success"}
        return {"source_runs": [run("ATT-OLD"), run("ATT-READ"), run("ATT-OTHER")],
                "collections": {"patents": [detail("ATT-OLD", "USD1035381S1"), detail("ATT-READ", "USD1035381S1"),
                                            detail("ATT-OTHER", "US11234567B2")]},
                "record_content_reviews": [{"source_run_id": "ATT-READ", "reviewer": "program:core_dossier"}]}

    def run_with(self, append):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "evidence.json").write_text(json.dumps(self.evidence()), encoding="utf-8")
        with mock.patch("source_result_processing._retained_run", lambda *a: ({}, b"{}")), \
                mock.patch("source_result_processing._whole_record_reading", lambda *a: (["identity", "claims"], [])), \
                mock.patch("source_result_processing.append_record_content_review", append):
            return core_dossier.read_same_document_records(root)

    def test_the_unread_twin_of_a_read_record_is_registered(self):
        calls = []
        done, left = self.run_with(lambda task_dir, run_id, request: calls.append((run_id, request)))
        self.assertEqual((done, left), (["ATT-OLD"], []))
        run_id, request = calls[0]
        self.assertEqual(run_id, "ATT-OLD")
        self.assertEqual(request["reading_units"], ["identity", "claims"])     # the recorder's own reading units
        self.assertEqual(request["reviewer"], "program:core_dossier")
        self.assertIn("ATT-READ", request["reason"])
        self.assertIn("USD1035381S1", request["reason"])

    def test_a_record_whose_document_nobody_read_stays_for_the_agent(self):
        calls = []
        self.run_with(lambda task_dir, run_id, request: calls.append(run_id))
        self.assertNotIn("ATT-OTHER", calls)

    def test_a_refused_registration_is_reported_not_raised(self):
        def refuse(task_dir, run_id, request):
            raise ValueError("RESULT_PROCESSING_DETAIL_IDENTITY_MISMATCH")
        done, left = self.run_with(refuse)
        self.assertEqual(done, [])
        self.assertEqual(left[0]["run_id"], "ATT-OLD")
        self.assertIn("IDENTITY_MISMATCH", left[0]["reason"])


class DossierGateTests(unittest.TestCase):
    def test_the_dossier_step_reads_twins_on_r5d17_and_newer_tasks_only(self):
        import specialty_analysis as sa
        for task, expected in (({"pipeline_speed_revision": pipeline_robust.SPEED_REVISION}, 1), ({}, 0)):
            root = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, root, True)
            (root / "task.json").write_text(json.dumps(task), encoding="utf-8")
            (root / "search-plan.json").write_text("{}", encoding="utf-8")
            calls = []
            with mock.patch.object(core_dossier, "enabled", return_value=True), \
                    mock.patch.object(sa, "enabled", return_value=True), \
                    mock.patch.object(sa, "_context", return_value=(task, {}, {}, {}, {}, {})), \
                    mock.patch.object(sa, "project", return_value={"scopes": []}), \
                    mock.patch.object(core_dossier, "read_same_document_records",
                                      side_effect=lambda root: calls.append(root) or (["ATT-OLD"], [])):
                summary = core_dossier.run(root)
            self.assertEqual(len(calls), expected)
            if expected:
                self.assertEqual(summary["same_document_readings"], {"recorded": ["ATT-OLD"], "left_for_agent": []})
            else:
                self.assertNotIn("same_document_readings", summary)


if __name__ == "__main__":
    unittest.main()
