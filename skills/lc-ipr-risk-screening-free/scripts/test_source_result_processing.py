"""04A offline receipt/position progress and local recovery contracts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_bytes
from source_result_processing import (REVISION, append_dispositions,
    append_parsed_rows, append_receipt_disposition, locate_one_to_one,
    make_index, progress, work_entries)


class ResultProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {"task_id": "TASK-04A", "result_processing_revision": REVISION}
        atomic_write_json(self.root / "task.json", self.task)

    def setup_run(self, count=30, parsed=24, *, status="success", submitted="submitted"):
        cards = [{"position": i, "title": f"Result {i}", "publication_number": f"US{i:07d}A1"}
                 for i in range(1, count + 1)]
        body = json.dumps({"candidates": cards}, sort_keys=True).encode()
        path = self.root / "source.json"
        path.write_bytes(body)
        normalized = {"candidates": [{"source_position": i, "publication_number": cards[i-1]["publication_number"]}
                                      for i in range(1, parsed + 1)]}
        index = make_index(self.task, provider="synthetic_browser", evidence_type="patent",
            status=status, submission_state=submitted, raw_body=body, raw_suffix="json",
            normalized=normalized, coverage={"schema_valid": True, "retrieved_hits": count},
            payload_digest=sha256_bytes(body))
        run = {"run_id": "RUN-1", "query_id": "Q-1", "provider": "synthetic_browser",
               "evidence_type": "patent", "status": status, "submission_state": submitted,
               "raw_paths": [path.name], "payload_digest": sha256_bytes(body),
               "result_processing": index}
        evidence = {"source_runs": [run], "collections": {"patents": [{
            "evidence_id": "EV-1", "source_run_id": run["run_id"],
            "payload": normalized}]}}
        atomic_write_json(self.root / "evidence.json", evidence)
        return run, evidence, cards, body

    def test_parse_and_disposition_batch_writes_once_and_repeats_without_write(self):
        from source_result_processing import append_processing_batch
        from common import atomic_write_json as write
        run, evidence, cards, body = self.setup_run(count=2, parsed=1)
        event = {'source_run_id': run['run_id'], 'parsed_rows': [{'position': 2,
            'candidate': {'publication_number': cards[1]['publication_number']},
            'reviewer': 'agent', 'reason': 'Read the retained row'}],
            'decisions': [{'position': i, 'outcome': 'non_candidate', 'candidate_ids': [],
                'reviewer': 'agent', 'reason': 'Read and excluded this row'} for i in (1, 2)]}
        with patch('common.atomic_write_json', wraps=write) as writer:
            result = append_processing_batch(self.root, [event])
        self.assertEqual(writer.call_count, 1)
        self.assertTrue(result['source_runs'][0]['material_processing_complete'])
        self.assertEqual(load_json(self.root / 'evidence.json')['source_runs'], evidence['source_runs'])
        self.assertEqual((self.root / 'source.json').read_bytes(), body)
        with patch('common.atomic_write_json', wraps=write) as writer:
            repeated = append_processing_batch(self.root, [event])
        self.assertFalse(repeated['recorded'])
        writer.assert_not_called()

    def test_invalid_final_event_rolls_back_all_batch_changes(self):
        from source_result_processing import append_processing_batch
        run, evidence, cards, body = self.setup_run(count=2, parsed=1)
        before = (self.root / 'evidence.json').read_bytes()
        good = {'source_run_id': run['run_id'], 'parsed_rows': [{'position': 2,
            'candidate': {'publication_number': cards[1]['publication_number']},
            'reviewer': 'agent', 'reason': 'Read retained row'}]}
        with self.assertRaisesRegex(ValueError, 'RUN_NOT_FOUND'):
            append_processing_batch(self.root, [good, {'source_run_id': 'absent',
                'decisions': [{'position': 1}]}])
        self.assertEqual((self.root / 'evidence.json').read_bytes(), before)

    def test_thirty_returned_twenty_four_parsed_six_pending_and_resume(self):
        run, evidence, cards, body = self.setup_run()
        legacy = make_index(self.task, provider="synthetic_browser", evidence_type="patent",
            status="success", submission_state="submitted", raw_body=body, raw_suffix="json",
            normalized=evidence["collections"]["patents"][0]["payload"],
            coverage={"schema_valid": True, "retrieved_hits": 24},
            payload_digest=sha256_bytes(body))
        self.assertFalse(legacy["count_contradiction"])
        self.assertEqual(legacy["declared_retrieved_interpretation"], "legacy_parsed_count")
        state = progress(self.root, run, evidence)
        self.assertEqual((state["returned_count"], state["parsed_count"]), (30, 24))
        self.assertEqual(state["pending_parse_positions"], list(range(25, 31)))
        self.assertFalse(state["material_processing_complete"])
        before_runs = list(evidence["source_runs"])
        rows = [{"position": i, "candidate": {"publication_number": cards[i-1]["publication_number"]},
                 "reviewer": "agent", "reason": "Read the retained row"} for i in range(25, 31)]
        append_parsed_rows(self.root, run["run_id"], rows)
        append_parsed_rows(self.root, run["run_id"], rows)
        saved = json.loads((self.root / "evidence.json").read_text())
        self.assertEqual(saved["source_runs"], before_runs)
        self.assertEqual(len(saved["collections"]["patents"][0]["payload"]["candidates"]), 30)
        self.assertEqual(len(saved["result_parses"]), 6)
        self.assertEqual(saved["result_parses"][0]["position"], 25)
        self.assertEqual(saved["result_parses"][0]["reason"], "Read the retained row")
        self.assertEqual((self.root / "source.json").read_bytes(), body)
        self.assertEqual(progress(self.root, run, saved)["pending_parse_positions"], [])

    def test_local_reparse_updates_acquisition_without_rewriting_run(self):
        from candidate_acquisition import REVISION as ACQUISITION_REVISION, execution_state, make_receipt
        run, evidence, cards, _ = self.setup_run()
        self.task["candidate_acquisition_revision"] = ACQUISITION_REVISION
        atomic_write_json(self.root / "task.json", self.task)
        run.update(jurisdiction="US", plan_entry_sha256="plan-hash")
        plan_row = {"action_purpose": "discovery", "discovery_role": "browser_fallback",
                    "discovery_intent_id": "INT-04C", "refinement_round": 0}
        run["candidate_acquisition"] = make_receipt(self.task, evidence, run, plan_row,
            evidence["collections"]["patents"][0]["payload"])
        atomic_write_json(self.root / "evidence.json", evidence)
        self.assertEqual(len(run["candidate_acquisition"]["unknown_positions"]), 6)
        original_run = json.loads(json.dumps(run))
        append_parsed_rows(self.root, run["run_id"], [{"position": i,
            "candidate": {"publication_number": cards[i-1]["publication_number"]},
            "reviewer": "agent", "reason": "Parsed the retained row"} for i in range(25, 31)])
        saved = load_json(self.root / "evidence.json")
        self.assertEqual(saved["source_runs"][0], original_run)
        self.assertEqual(len(saved["result_parses"]), 6)
        keys, unresolved = execution_state(saved, saved["source_runs"][0],
                                            run["candidate_acquisition"])
        self.assertEqual((len(keys), unresolved), (30, []))

    def test_fifty_seven_retained_and_all_positions_need_review(self):
        run, evidence, _, _ = self.setup_run(count=57, parsed=57)
        state = progress(self.root, run, evidence)
        self.assertEqual(state["returned_count"], 57)
        self.assertEqual(len(state["pending_positions"]), 57)
        self.assertEqual(len(work_entries(self.task, evidence, self.root)), 1)

    def test_partial_parser_matches_only_unique_exact_raw_identifiers(self):
        run, evidence, cards, body = self.setup_run(count=30, parsed=24)
        candidates = evidence["collections"]["patents"][0]["payload"]["candidates"]
        for candidate in candidates:
            del candidate["source_position"]
        located = locate_one_to_one(self.task, "synthetic_browser", "patent", body,
                                    "json", {"candidates": candidates})
        self.assertEqual([item.get("source_position") for item in located["candidates"]],
                         list(range(1, 25)))
        self.assertEqual(progress(self.root, run, evidence)["pending_parse_positions"],
                         list(range(25, 31)))
        ambiguous = json.dumps({"candidates": [cards[0], cards[0], cards[1]]}).encode()
        result = locate_one_to_one(self.task, "synthetic_browser", "patent", ambiguous,
                                   "json", {"candidates": [{"publication_number": cards[0]["publication_number"]}]})
        self.assertNotIn("source_position", result["candidates"][0])

    def test_uspto_cua_rows_restore_unknown_index_without_rewriting_receipt(self):
        run, evidence, _, _ = self.setup_run(count=2, parsed=0, status="failed")
        body = json.dumps({"rows": [{"cells": [{"text": "US123A1"}, {"text": "Title"}]},
                                     {"cells": ["US456A1", "Other"]}],
                           "history_binding_verified": False}).encode()
        (self.root / "source.json").write_bytes(body)
        run.update(provider="uspto_patent_browser", payload_digest=sha256_bytes(body))
        run["result_processing"].update(payload_digest=sha256_bytes(body),
            returned_count=None, returned_count_basis="unknown", rows=[],
            declared_retrieved_count=None)
        before = json.dumps(run, sort_keys=True)
        state = progress(self.root, run, evidence)
        self.assertEqual(state["returned_count"], 2)
        self.assertEqual(state["pending_parse_positions"], [1, 2])
        self.assertFalse(state["zero_proven"])
        self.assertFalse(state["material_processing_complete"])
        self.assertEqual(state["request_status"], "failed")
        self.assertEqual(json.dumps(run, sort_keys=True), before)
        atomic_write_json(self.root / "evidence.json", evidence)
        evidence_before = (self.root / "evidence.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "RESULT_PROCESSING_QUERY_BINDING_REQUIRED"):
            append_parsed_rows(self.root, run["run_id"], [{"position": 1,
                "candidate": {"publication_number": "US123A1"},
                "reviewer": "offline-test", "reason": "Unbound visible row"}])
        self.assertEqual((self.root / "evidence.json").read_bytes(), evidence_before)
        normalized = {"candidates": [{"publication_number": "US123A1"},
                                     {"publication_number": "US456A1"}]}
        locate_one_to_one(self.task, "uspto_patent_browser", "patent", body, "json", normalized)
        self.assertNotIn("source_position", normalized["candidates"][0])
        (self.root / "source.json").write_bytes(body + b" ")
        with self.assertRaises(ValueError):
            progress(self.root, run, evidence)

    def test_unbound_empty_cua_result_cannot_prove_zero(self):
        body = b'{"rows": [], "history_binding_verified": false}'
        index = make_index(self.task, provider="uspto_patent_browser", evidence_type="patent",
            status="no_result", submission_state="submitted", raw_body=body,
            raw_suffix="json", normalized={"candidates": []},
            coverage={"schema_valid": True, "retrieved_hits": 0},
            payload_digest=sha256_bytes(body))
        self.assertEqual(index["returned_count"], 0)
        self.assertFalse(index["zero_proven"])

    def test_cua_rows_are_provider_scoped_and_malformed_cells_remain_unknown(self):
        for provider, rows in [("synthetic_browser", [{"cells": ["Title"]}]),
                               ("uspto_patent_browser", [{"cells": 3}]),
                               ("uspto_patent_browser", [{"cells": [1]}])]:
            with self.subTest(provider=provider, rows=rows):
                body = json.dumps({"rows": rows}).encode()
                index = make_index(self.task, provider=provider, evidence_type="patent",
                    status="failed", submission_state="submitted", raw_body=body,
                    raw_suffix="json", normalized=None, coverage=None,
                    payload_digest=sha256_bytes(body))
                self.assertIsNone(index["returned_count"])
                self.assertFalse(index["zero_proven"])

    def test_failure_material_and_unknown_submission_are_not_zero(self):
        for status, submitted in (("failed", "submitted"), ("failed", "unknown")):
            with self.subTest(status=status, submitted=submitted):
                run, evidence, _, _ = self.setup_run(count=2, parsed=0, status=status, submitted=submitted)
                state = progress(self.root, run, evidence)
                self.assertEqual(state["returned_count"], 2)
                self.assertFalse(state["zero_proven"])
                self.assertEqual(state["pending_parse_positions"], [1, 2])
        body = b'{"login": "required"}'
        index = make_index(self.task, provider="synthetic_browser", evidence_type="patent",
            status="no_result", submission_state="submitted", raw_body=body, raw_suffix="json",
            normalized={"candidates": []}, coverage={"schema_valid": True, "retrieved_hits": 0},
            payload_digest=sha256_bytes(body))
        self.assertFalse(index["zero_proven"])
        valid = make_index(self.task, provider="synthetic_browser", evidence_type="patent",
            status="no_result", submission_state="submitted", raw_body=b'{"candidates": []}',
            raw_suffix="json", normalized={"candidates": []},
            coverage={"schema_valid": True, "retrieved_hits": 0}, payload_digest="hash")
        self.assertTrue(valid["zero_proven"])
        self.assertIsNone(make_index(self.task, provider="synthetic_browser", evidence_type="patent",
            status="failed", submission_state="not_submitted", raw_body=b"", raw_suffix="json",
            normalized={"candidates": []}, coverage={}, payload_digest="hash"))

    def test_explicit_fault_receipt_disposition_closes_only_processing_and_is_idempotent(self):
        body = (b'<?xml version="1.0"?><fault xmlns="http://ops.epo.org">'
                b'<code>SERVER.EntityNotFound</code><message>No results found</message></fault>')
        path = self.root / "fault.xml"
        path.write_bytes(body)
        digest = sha256_bytes(body)
        index = make_index(self.task, provider="epo_ops", evidence_type="patent",
            status="no_result", submission_state="submitted", raw_body=body, raw_suffix="xml",
            normalized={"candidates": []}, coverage={"schema_valid": False, "retrieved_hits": 0},
            payload_digest=digest)
        run = {"run_id": "RUN-FAULT", "query_id": "Q-FAULT", "provider": "epo_ops",
            "evidence_type": "patent", "status": "no_result", "submission_state": "submitted",
            "raw_paths": [path.name], "payload_digest": digest, "result_processing": index,
            "metadata": {"search_coverage": {"retrieved_hits": 0, "schema_valid": False}}}
        # The importer may retain an empty normalized envelope alongside the
        # fault receipt; it is not itself candidate/result material.
        evidence = {"source_runs": [run], "collections": {"patents": [{
            "evidence_id": "EV-EMPTY-FAULT", "source_run_id": run["run_id"],
            "payload": {"candidates": [], "search_metadata": {"empty_fault_receipt": True}}}]}}
        atomic_write_json(self.root / "evidence.json", evidence)
        before_run = json.loads(json.dumps(run))
        review = {"outcome": "non_result_error", "reviewer": "reviewer",
                  "reason": "Provider returned an XML fault envelope"}
        first = append_receipt_disposition(self.root, run["run_id"], review)
        self.assertTrue(first["receipt_reviewed"])
        self.assertTrue(first["material_processing_complete"])
        self.assertEqual(first["returned_count"], 0)
        self.assertFalse(first["zero_proven"])
        contradicted = load_json(self.root / "evidence.json")
        contradicted["source_runs"][0]["result_processing"]["count_contradiction"] = True
        with self.assertRaisesRegex(ValueError, "DISPOSITION_INVALID_OR_CHANGED"):
            progress(self.root, contradicted["source_runs"][0], contradicted)
        append_receipt_disposition(self.root, run["run_id"], review)
        saved = load_json(self.root / "evidence.json")
        self.assertEqual(len(saved["receipt_dispositions"]), 1)
        self.assertEqual(saved["source_runs"][0], before_run)
        self.assertEqual(saved["source_runs"][0]["metadata"], run["metadata"])
        self.assertEqual(work_entries(self.task, saved, self.root), [])
        with self.assertRaisesRegex(ValueError, "DISPOSITION_CONFLICT"):
            append_receipt_disposition(self.root, run["run_id"], {**review, "reason": "changed"})

        saved["collections"]["patents"][0]["payload"]["candidates"] = [{"publication_number": "US1"}]
        atomic_write_json(self.root / "evidence.json", saved)
        with self.assertRaisesRegex(ValueError, "DISPOSITION_INVALID_OR_CHANGED"):
            progress(self.root, saved["source_runs"][0], saved)

    def ops_empty_fault_run(self):
        body = (b'<?xml version="1.0"?><fault xmlns="http://ops.epo.org">'
                b'<code>SERVER.EntityNotFound</code><message>No results found</message></fault>')
        path = self.root / "ops-empty.xml"
        path.write_bytes(body)
        coverage = {"retrieved_hits": 0, "schema_valid": True, "empty_fault_receipt": True}
        index = make_index(self.task, provider="epo_ops", evidence_type="patent",
            status="no_result", submission_state="submitted", raw_body=body, raw_suffix="xml",
            normalized={"candidates": []}, coverage=coverage, payload_digest=sha256_bytes(body))
        run = {"run_id": "RUN-OPS-EMPTY", "query_id": "Q-OPS-EMPTY", "provider": "epo_ops",
            "operation": "search", "evidence_type": "patent", "status": "no_result",
            "submission_state": "submitted", "raw_paths": [path.name],
            "payload_digest": sha256_bytes(body), "result_processing": index,
            "metadata": {"search_coverage": coverage}}
        evidence = {"source_runs": [run], "collections": {"patents": [{
            "source_run_id": run["run_id"], "payload": {"candidates": [], "search_metadata": coverage}}]}}
        return run, evidence, body

    def test_exact_ops_empty_fault_proves_zero_and_closes_new_processing(self):
        run, evidence, body = self.ops_empty_fault_run()
        index = run["result_processing"]
        self.assertEqual(index["returned_count_basis"], "retained_rows")
        self.assertTrue(index["zero_proven"])
        state = progress(self.root, run, evidence)
        self.assertTrue(state["zero_proven"])
        self.assertTrue(state["material_processing_complete"])
        self.assertEqual(work_entries(self.task, evidence, self.root), [])

    def test_existing_ops_empty_fault_index_is_projected_without_any_write(self):
        run, evidence, body = self.ops_empty_fault_run()
        run["result_processing"].update(returned_count_basis="response_count_only", zero_proven=False)
        atomic_write_json(self.root / "evidence.json", evidence)
        before = json.dumps(evidence, sort_keys=True)
        file_before = (self.root / "evidence.json").read_bytes()
        state = progress(self.root, run, evidence)
        self.assertTrue(state["zero_proven"])
        self.assertTrue(state["material_processing_complete"])
        self.assertEqual(json.dumps(evidence, sort_keys=True), before)
        self.assertEqual((self.root / "evidence.json").read_bytes(), file_before)
        self.assertEqual((self.root / "ops-empty.xml").read_bytes(), body)
        (self.root / "ops-empty.xml").write_bytes(body + b" ")
        with self.assertRaises(ValueError):
            progress(self.root, run, evidence)

    def test_ops_empty_fault_lookalikes_and_error_envelopes_never_prove_zero(self):
        run, evidence, body = self.ops_empty_fault_run()
        variants = [body.replace(b"http://ops.epo.org", b"http://example.test"),
            body.replace(b"SERVER.EntityNotFound", b"SERVER.InternalError"),
            body.replace(b"No results found", b"Entity not found"),
            body.replace(b"No results found", b"No results found: retry"),
            body.replace(b"</fault>", b"<exchange-document/></fault>"),
            body.replace(b"</fault>", b"<document-id/></fault>"),
            body.replace(b"</fault>", b"<code>SERVER.EntityNotFound</code></fault>"),
            body.replace(b"</message>", b"<extra/></message>"),
            body.replace(b"<code>", b"unexpected text<code>"),
            b"<fault/>", b"<html>Login required</html>", b"<fault>"]
        for changed in variants:
            with self.subTest(body=changed):
                index = make_index(self.task, provider="epo_ops", evidence_type="patent",
                    status="no_result", submission_state="submitted", raw_body=changed, raw_suffix="xml",
                    normalized={"candidates": []}, coverage={"retrieved_hits": 0, "schema_valid": True},
                    payload_digest=sha256_bytes(changed))
                self.assertFalse(index["zero_proven"])
                self.assertNotEqual(index["returned_count_basis"], "retained_rows")
        for status, submitted, schema in (("failed", "submitted", True),
                ("no_result", "unknown", True), ("no_result", "submitted", False)):
            with self.subTest(status=status, submitted=submitted, schema=schema):
                index = make_index(self.task, provider="epo_ops", evidence_type="patent",
                    status=status, submission_state=submitted, raw_body=body, raw_suffix="xml",
                    normalized={"candidates": []}, coverage={"retrieved_hits": 0, "schema_valid": schema},
                    payload_digest=sha256_bytes(body))
                self.assertFalse(index["zero_proven"])

    def test_existing_ops_zero_projection_rejects_unknown_and_contradicted_context(self):
        from copy import deepcopy
        run, evidence, unused = self.ops_empty_fault_run()
        run["result_processing"].update(returned_count_basis="response_count_only", zero_proven=False)
        changes = [lambda r, e: r.update(status="failed"),
                   lambda r, e: r.update(submission_state="unknown"),
                   lambda r, e: r.update(operation="candidate_detail"),
                   lambda r, e: r["metadata"]["search_coverage"].update(schema_valid=False),
                   lambda r, e: r["result_processing"].update(count_contradiction=True),
                   lambda r, e: r["result_processing"].update(declared_retrieved_count=1),
                   lambda r, e: r["result_processing"].update(declared_retrieved_count=False),
                   lambda r, e: e["collections"]["patents"][0]["payload"].update(candidates=[{"publication_number": "US1A1"}])]
        for position, change in enumerate(changes):
            changed = deepcopy(evidence)
            candidate = changed["source_runs"][0]
            change(candidate, changed)
            with self.subTest(position=position):
                state = progress(self.root, candidate, changed)
                self.assertFalse(state["zero_proven"])
                self.assertFalse(state["material_processing_complete"])
    def test_receipt_disposition_rejects_tamper_valid_empty_partial_rows_and_success(self):
        review = {"outcome": "non_result_error", "reviewer": "reviewer", "reason": "Transport error"}
        run, evidence, _, _ = self.setup_run(count=1, parsed=0, status="failed")
        # Even an explicit error state cannot relabel a response containing a result row.
        atomic_write_json(self.root / "evidence.json", evidence)
        with self.assertRaisesRegex(ValueError, "HAS_RESULT_MATERIAL"):
            append_receipt_disposition(self.root, run["run_id"], review)

        for name, provider, status, raw, suffix, normalized, coverage in (
            ("empty.json", "synthetic_browser", "no_result", b'{"candidates":[]}', "json",
             {"candidates": []}, {"schema_valid": True, "retrieved_hits": 0}),
            ("partial.json", "synthetic_browser", "failed", b'{"candidates":[{"id":"x"}]}', "json",
             {"candidates": []}, {"schema_valid": False, "retrieved_hits": 1}),
            ("success.json", "synthetic_browser", "success", b'{"message":"timeout"}', "json",
             {"candidates": []}, {"schema_valid": False, "retrieved_hits": 0}),
        ):
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(raw)
                digest = sha256_bytes(raw)
                row_index = make_index(self.task, provider=provider, evidence_type="patent",
                    status=status, submission_state="submitted", raw_body=raw, raw_suffix=suffix,
                    normalized=normalized, coverage=coverage, payload_digest=digest)
                candidate_run = {"run_id": name, "provider": provider, "evidence_type": "patent",
                    "status": status, "submission_state": "submitted", "raw_paths": [name],
                    "payload_digest": digest, "result_processing": row_index}
                snapshot = {"source_runs": [candidate_run], "collections": {"patents": []}}
                atomic_write_json(self.root / "evidence.json", snapshot)
                with self.assertRaises(ValueError):
                    append_receipt_disposition(self.root, name, review)

        run, evidence, _, _ = self.setup_run(count=0, parsed=0, status="failed")
        atomic_write_json(self.root / "evidence.json", evidence)
        (self.root / "source.json").write_bytes(b'{"tampered":true}')
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH|RECEIPT_CHANGED"):
            append_receipt_disposition(self.root, run["run_id"], review)

    def test_unverified_zero_cannot_complete_assessment_or_report_trace(self):
        from assessment_v24 import query_coverage
        from report_query_trace import _attempt
        from common import sha256_json
        query = {"query_id": "Q", "operation": "search", "jurisdiction": "US",
                 "right_type": "patent", "search_dimension": "text", "search_language": "en",
                 "execution_phase": "initial"}
        run = {"run_id": "RUN-Z", "provider": "epo_ops", "status": "no_result",
               "operation": "search", "jurisdiction": "US", "right_type": "patent",
               "submission_state": "submitted", "source_environment": "production",
               "authoritative_for_final_rating": True,
               "plan_entry_sha256": sha256_json(query), "query_id": "Q",
               "result_processing": {"revision": REVISION, "zero_proven": False},
               "metadata": {"search_coverage": {"schema_valid": True,
                   "total_hits": 0, "retrieved_hits": 0, "truncated": False,
                   "stop_reason": "claimed_zero"}}}
        entry = {"evidence_id": "EV-Z", "source_run_id": "RUN-Z", "provider": "epo_ops",
                 "query_id": "Q", "operation": "search", "jurisdiction": "US",
                 "right_type": "patent", "plan_entry_sha256": run["plan_entry_sha256"],
                 "payload": {"candidates": []}}
        evidence = {"source_runs": [run], "collections": {"patents": [entry]}}
        coverage = query_coverage(evidence, {}, {"queries": {"epo_ops": [query]}}, "epo_ops", query)
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["gap"], "ZERO_RESULT_UNVERIFIED")
        attempt = _attempt(run, query, [entry], [], 1)
        self.assertEqual(attempt["status"], "unknown")
        self.assertFalse(attempt["effective"])
        self.assertFalse(attempt["response_complete"])
        self.assertIn("ZERO_RESULT_UNVERIFIED", attempt["reason"])

    def test_batch_review_is_atomic_idempotent_and_receipt_bound(self):
        run, evidence, _, _ = self.setup_run(count=2, parsed=0)
        decisions = [{"position": 1, "outcome": "non_candidate", "candidate_ids": [],
                      "reviewer": "agent", "reason": "Navigation only"},
                     {"position": 2, "outcome": "non_candidate", "candidate_ids": [],
                      "reviewer": "agent", "reason": "Login prompt only"}]
        bad = [*decisions]
        bad[-1] = {**bad[-1], "position": 3}
        with self.assertRaises(ValueError):
            append_dispositions(self.root, run["run_id"], bad)
        self.assertNotIn("result_dispositions", json.loads((self.root / "evidence.json").read_text()))
        first = append_dispositions(self.root, run["run_id"], decisions)
        self.assertTrue(first["material_processing_complete"])
        append_dispositions(self.root, run["run_id"], decisions)
        saved = json.loads((self.root / "evidence.json").read_text())
        self.assertEqual(len(saved["result_dispositions"]), 2)
        (self.root / "source.json").write_text('{"candidates": []}')
        self.assertEqual(work_entries(self.task, saved, self.root)[0]["reason"],
                         "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID")
        with self.assertRaises(ValueError):
            append_dispositions(self.root, run["run_id"], decisions)

    def test_real_recorder_binds_raw_rows_then_merge_keeps_positions(self):
        from provider_utils import record_result
        from merge_candidates import merge, apply_candidate_contract
        self.task.update(schema_version="2.4-free",
                         workflow_correction_revision="workflow-correction-v1")
        atomic_write_json(self.root / "task.json", self.task)
        atomic_write_json(self.root / "evidence.json", {
            "schema_version": "2.4-free", "task_id": self.task["task_id"],
            "source_runs": [], "collections": {}})
        raw = json.dumps({"candidates": [
            {"publication_number": "US1234567A1", "title": "A"},
            {"publication_number": "US7654321A1", "title": "B"}]}).encode()
        normalized = {"candidates": [
            {"publication_number": "US1234567A1", "jurisdiction": "US"},
            {"publication_number": "US7654321A1", "jurisdiction": "US"}],
            "search_metadata": {"schema_valid": True, "retrieved_hits": 2}}
        with patch("provider_utils.require_provider_operation", return_value=False):
            run = record_result(self.root, provider="synthetic_source", operation="search",
                query="fixture", jurisdiction="US", evidence_type="patent", status="success",
                normalized=normalized, raw_body=raw, raw_suffix="json", query_id="Q-1",
                submission_state="submitted")
        evidence = load_json(self.root / "evidence.json")
        entry = evidence["collections"]["patents"][0]
        self.assertEqual(run["result_processing"]["returned_count"], 2)
        self.assertEqual([c["source_position"] for c in entry["payload"]["candidates"]], [1, 2])
        merged = merge("patent", [entry], {run["run_id"]: run})
        apply_candidate_contract("patent", merged)
        self.assertEqual([c["sources"][0]["source_position"] for c in merged], [1, 2])
        self.assertEqual(progress(self.root, run, evidence)["pending_parse_positions"], [])

    def test_candidate_review_requires_same_run_and_position(self):
        run, evidence, _, _ = self.setup_run(count=2, parsed=2)
        candidates = {"patents": [{"candidate_id": "C-1",
            "sources": [{"source_run_id": run["run_id"], "source_position": 1}]}]}
        atomic_write_json(self.root / "normalized-candidates.json", candidates)
        decision = {"position": 2, "outcome": "candidate", "candidate_ids": ["C-1"],
                    "reviewer": "agent", "reason": "Read retained result"}
        with self.assertRaisesRegex(ValueError, "CANDIDATE_NOT_BOUND"):
            append_dispositions(self.root, run["run_id"], [decision])
        decision["position"] = 1
        state = append_dispositions(self.root, run["run_id"], [decision])
        self.assertEqual(state["reviewed_count"], 1)
        self.assertEqual(state["pending_positions"], [2])

    def test_candidate_review_needs_position_or_matching_raw_hash(self):
        run, _, _, _ = self.setup_run(count=1, parsed=1)
        candidates = {"patents": [{"candidate_id": "C-1", "sources": [{
            "source_run_id": run["run_id"]}]}]}
        atomic_write_json(self.root / "normalized-candidates.json", candidates)
        decision = {"position": 1, "outcome": "candidate", "candidate_ids": ["C-1"],
                    "reviewer": "agent", "reason": "Read retained card"}
        with self.assertRaisesRegex(ValueError, "CANDIDATE_NOT_BOUND"):
            append_dispositions(self.root, run["run_id"], [decision])
        candidates["patents"][0]["sources"][0]["source_record_sha256"] = "wrong"
        atomic_write_json(self.root / "normalized-candidates.json", candidates)
        with self.assertRaisesRegex(ValueError, "CANDIDATE_NOT_BOUND"):
            append_dispositions(self.root, run["run_id"], [decision])

    def test_strict_api_cards_reject_manual_reparse(self):
        run, evidence, cards, _ = self.setup_run(count=1, parsed=0)
        run["provider"] = "serper_patents"
        atomic_write_json(self.root / "evidence.json", evidence)
        with self.assertRaisesRegex(ValueError, "STRICT_ADAPTER_REPLAY_REQUIRED"):
            append_parsed_rows(self.root, run["run_id"], [{"position": 1,
                "candidate": {"publication_number": cards[0]["publication_number"]},
                "reviewer": "agent", "reason": "retained row"}])

    def test_xml_source_rows_are_positioned_without_counting_global_hits(self):
        body = b'<root><biblio-search total-result-count="100"><search-result>' \
               b'<exchange-document country="US" doc-number="1" kind="A1"/>' \
               b'<exchange-document country="US" doc-number="2" kind="A1"/>' \
               b'</search-result></biblio-search></root>'
        index = make_index(self.task, provider="epo_ops", evidence_type="patent",
            status="success", submission_state="submitted", raw_body=body, raw_suffix="xml",
            normalized={"candidates": [{"publication_number": "US1A1"},
                                       {"publication_number": "US2A1"}]},
            coverage={"schema_valid": True, "total_hits": 100, "retrieved_hits": 2},
            payload_digest=sha256_bytes(body))
        self.assertEqual(index["returned_count"], 2)
        self.assertEqual([row["position"] for row in index["rows"]], [1, 2])
        self.assertFalse(index["count_contradiction"])
        fault = make_index(self.task, provider="epo_ops", evidence_type="patent",
            status="no_result", submission_state="submitted", raw_body=b"<fault/>",
            raw_suffix="xml", normalized={"candidates": []},
            coverage={"schema_valid": True, "retrieved_hits": 0}, payload_digest="hash")
        self.assertFalse(fault["zero_proven"])



class LegacyXmlDerivationTests(unittest.TestCase):
    setUp = ResultProcessingTests.setUp

    def setup_xml(self, *, extra_damage=False, safe=False):
        url = 'https://example.test/watch?v=1&amp;t=2' if safe else 'https://example.test/watch?v=1&amp%3Bt=2'
        bad = '<broken>' if extra_damage else ''
        body = ('<world xmlns="http://www.epo.org/exchange" xmlns:ops="http://ops.epo.org">'
            '<ops:biblio-search publications-count="2" total-result-count="1048">'
            '<ops:range begin="1" end="2"/><exchange-documents>'
            '<exchange-document country="US" doc-number="20260233409" kind="A1"><abstract><p>Pet robot</p></abstract></exchange-document>'
            '<exchange-document country="WO" doc-number="2026019310" kind="A1"><abstract><p>Purifier</p></abstract>'
            '<citation>' + url + '</citation>' + bad + '</exchange-document>'
            '</exchange-documents></ops:biblio-search></world>').encode()
        path = self.root / 'epo.xml'
        path.write_bytes(body)
        # Deliberately reverse normalized order: bind by exact original identity.
        normalized = {'candidates': [{'publication_number': 'WO2026019310A1', 'title': 'Purifier'},
                                     {'publication_number': 'US20260233409A1', 'title': 'Robot'}]}
        index = make_index(self.task, provider='epo_ops', evidence_type='patent', status='success',
            submission_state='submitted', raw_body=body, raw_suffix='xml', normalized=normalized,
            coverage={'schema_valid': True, 'retrieved_hits': 2}, payload_digest=sha256_bytes(body))
        run = {'run_id': 'RUN-XML', 'query_id': 'Q-XML', 'provider': 'epo_ops',
            'evidence_type': 'patent', 'status': 'success', 'submission_state': 'submitted',
            'raw_paths': [path.name], 'payload_digest': sha256_bytes(body), 'result_processing': index,
            'jurisdiction': 'US', 'right_type': 'patent'}
        evidence = {'source_runs': [run], 'collections': {'patents': [{
            'evidence_id': 'EV-XML', 'source_run_id': run['run_id'], 'provider': 'epo_ops',
            'jurisdiction': 'US', 'right_type': 'patent', 'payload': normalized}]}}
        atomic_write_json(self.root / 'evidence.json', evidence)
        return run, evidence, body

    def derive(self, run):
        from source_result_processing import append_xml_derivation, XML_DERIVATION_TRANSFORM
        return append_xml_derivation(self.root, run['run_id'], {
            'transform': XML_DERIVATION_TRANSFORM, 'reviewer': 'agent',
            'reason': 'Exact retained URL ampersand corruption verified'})

    def setup_redaction_xml(self):
        run, evidence, body = self.setup_xml(safe=True)
        body = body.replace(b'<citation>https://example.test/watch?v=1&amp;t=2</citation>',
            b'<citation><nplcit num="2"><text>Temu https://www.temu.com/-do ---toy?x=1&amp;share_token=[redacted]\n  </nplcit></citation>')
        body = body.replace(b'doc-number="20260233409" kind="A1"', b'doc-number="D1148902" kind="S"')
        normalized = evidence['collections']['patents'][0]['payload']
        normalized['candidates'][1]['publication_number'] = 'USD1148902S'
        (self.root / 'epo.xml').write_bytes(body)
        run['payload_digest'] = sha256_bytes(body)
        run['result_processing'] = make_index(self.task, provider='epo_ops', evidence_type='patent', status='success',
            submission_state='submitted', raw_body=body, raw_suffix='xml', normalized=normalized,
            coverage={'schema_valid': True, 'retrieved_hits': 2}, payload_digest=run['payload_digest'])
        atomic_write_json(self.root / 'evidence.json', evidence)
        return run, evidence, body

    def test_exact_redaction_close_restores_structure_not_unknown_tail(self):
        from source_result_processing import append_xml_derivation, XML_REDACTION_CLOSE_TRANSFORM, _derive_legacy_epo_xml
        run, evidence, body = self.setup_redaction_xml()
        original = json.loads(json.dumps(evidence))
        derived, changes, rows = _derive_legacy_epo_xml(body, XML_REDACTION_CLOSE_TRANSFORM)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['from'], '')
        self.assertEqual(changes[0]['to'], '</text>')
        self.assertEqual(rows[0]['publication_number'], 'USD1148902S')
        self.assertNotIn(b'Oct. 8, 2024', derived)
        append_xml_derivation(self.root, run['run_id'], {'transform': XML_REDACTION_CLOSE_TRANSFORM,
            'reviewer': 'agent', 'reason': 'Only closing tag restored; unknown citation tail remains absent'})
        append_parsed_rows(self.root, run['run_id'], [
            {'position': p, 'bind_existing_publication_number': n, 'reviewer': 'agent', 'reason': 'Exact original identity'}
            for p, n in [(1, 'USD1148902S'), (2, 'WO2026019310A1')]])
        saved = load_json(self.root / 'evidence.json')
        self.assertEqual(saved['source_runs'], original['source_runs'])
        self.assertEqual(saved['collections'], original['collections'])
        self.assertEqual((self.root / 'epo.xml').read_bytes(), body)
        self.assertTrue(saved['result_xml_derivations'][0]['limitations'])
        self.assertEqual(progress(self.root, run, saved)['unlocated_parsed_count'], 0)
        changed = json.loads(json.dumps(saved))
        changed['result_xml_derivations'][0]['limitations'] = []
        with self.assertRaisesRegex(ValueError, 'DERIVATION_CHANGED'):
            progress(self.root, run, changed)
        saved['result_xml_derivations'][0]['changes'][0]['offset'] += 1
        with self.assertRaisesRegex(ValueError, 'DERIVATION_CHANGED'):
            progress(self.root, run, saved)

    def test_redaction_close_rejects_other_missing_tags_and_ambiguous_damage(self):
        from source_result_processing import _derive_legacy_epo_xml, XML_REDACTION_CLOSE_TRANSFORM
        _, _, body = self.setup_redaction_xml()
        for altered in (body.replace(b'www.temu.com', b'example.test'),
                        body.replace(b'share_token=[redacted]', b'access_token=[redacted]'),
                        body.replace(b'\n  </nplcit>', b' tail\n  </nplcit>'),
                        body.replace(b'</citation>', b'</citation><citation><nplcit><text>https://www.temu.com/-do ---toy?x=1&amp;share_token=[redacted]\n  </nplcit></citation>'),
                        body.replace(b'</abstract>', b'<broken></abstract>')):
            with self.subTest(altered=sha256_bytes(altered)):
                with self.assertRaisesRegex(ValueError, 'DAMAGE_UNRECOGNIZED|DERIVATION_INVALID'):
                    _derive_legacy_epo_xml(altered, XML_REDACTION_CLOSE_TRANSFORM)

    def bind(self, run):
        return append_parsed_rows(self.root, run['run_id'], [
            {'position': 1, 'bind_existing_publication_number': 'US20260233409A1',
             'reviewer': 'agent', 'reason': 'Exact original exchange-document identity'},
            {'position': 2, 'bind_existing_publication_number': 'WO2026019310A1',
             'reviewer': 'agent', 'reason': 'Exact original exchange-document identity'}])

    def test_repair_bind_project_merge_review_and_handoff_leave_original_unchanged(self):
        from source_result_processing import project_entry, _retained_run
        from merge_candidates import merge
        from candidate_handoff import _source_state
        run, original, body = self.setup_xml()
        before = json.loads(json.dumps(original))
        self.assertEqual(progress(self.root, run, original)['unlocated_parsed_count'], 2)
        self.derive(run)
        self.derive(run)
        state = self.bind(run)
        self.bind(run)
        saved = load_json(self.root / 'evidence.json')
        self.assertEqual(saved['source_runs'], before['source_runs'])
        self.assertEqual(saved['collections'], before['collections'])
        self.assertEqual(len(saved['result_xml_derivations']), 1)
        self.assertEqual(len(saved['result_parses']), 2)
        self.assertEqual((self.root / 'epo.xml').read_bytes(), body)
        self.assertEqual((state['located_parsed_count'], state['unlocated_parsed_count']), (2, 0))
        index, _ = _retained_run(self.root, run, saved)
        self.assertEqual(index['rows'][1]['raw_sha256'], sha256_bytes(body[
            index['rows'][1]['byte_start']:index['rows'][1]['byte_end']]))
        projected = project_entry(saved['collections']['patents'][0], saved, self.root)
        self.assertEqual(projected['payload']['candidates'][0]['source_position'], 2)
        candidates = merge('patent', [projected], {run['run_id']: run}, identity_revision='candidate-identity-v1')
        atomic_write_json(self.root / 'normalized-candidates.json', {'patents': candidates})
        decisions = []
        for candidate in candidates:
            ref = candidate['sources'][0]
            decisions.append({'position': ref['source_position'], 'outcome': 'candidate',
                'candidate_ids': [candidate['candidate_id']], 'reviewer': 'agent', 'reason': 'Read actual row'})
        self.assertTrue(append_dispositions(self.root, run['run_id'], decisions)['material_processing_complete'])
        saved = load_json(self.root / 'evidence.json')
        for candidate in candidates:
            self.assertEqual(_source_state(candidate['sources'][0], saved, self.root)[0], 'ready')

    def test_unrecognized_or_remaining_malformed_damage_rejected(self):
        run, _, _ = self.setup_xml(extra_damage=True)
        with self.assertRaisesRegex(ValueError, 'DERIVATION_INVALID'):
            self.derive(run)
        self.assertNotIn('result_xml_derivations', load_json(self.root / 'evidence.json'))
        run, evidence, body = self.setup_xml()
        body = body.replace(b'&amp%3B', b'&nonsense')
        (self.root / 'epo.xml').write_bytes(body)
        run['payload_digest'] = sha256_bytes(body)
        run['result_processing']['payload_digest'] = run['payload_digest']
        atomic_write_json(self.root / 'evidence.json', evidence)
        with self.assertRaisesRegex(ValueError, 'DAMAGE_UNRECOGNIZED'):
            self.derive(run)

    def test_safe_xml_has_original_index_and_cannot_be_repaired(self):
        run, evidence, _ = self.setup_xml(safe=True)
        self.assertEqual(run['result_processing']['returned_count_basis'], 'retained_rows')
        with self.assertRaisesRegex(ValueError, 'DERIVATION_NOT_NEEDED'):
            self.derive(run)
        self.assertEqual(load_json(self.root / 'evidence.json'), evidence)

    def test_original_derived_event_and_candidate_tampering_rejected(self):
        import copy
        run, _, _ = self.setup_xml()
        self.derive(run)
        self.bind(run)
        evidence = load_json(self.root / 'evidence.json')
        for field in ('changes', 'rows', 'original_sha256', 'derived_sha256'):
            changed = copy.deepcopy(evidence)
            changed['result_xml_derivations'][0][field] = [] if field in {'changes', 'rows'} else 'f' * 64
            with self.assertRaises((ValueError, OSError)):
                progress(self.root, run, changed)
        changed = copy.deepcopy(evidence)
        changed['collections']['patents'][0]['payload']['candidates'][0]['title'] = 'Changed content'
        with self.assertRaisesRegex(ValueError, 'IDENTITY_BINDING_CHANGED'):
            progress(self.root, run, changed)
        derived = self.root / evidence['result_xml_derivations'][0]['derived_path']
        derived.write_bytes(derived.read_bytes() + b' ')
        with self.assertRaises((ValueError, OSError)):
            progress(self.root, run, evidence)

    def test_exact_identity_mismatch_or_duplicate_refuses_binding_atomically(self):
        run, _, _ = self.setup_xml()
        self.derive(run)
        before = load_json(self.root / 'evidence.json')
        with self.assertRaisesRegex(ValueError, 'IDENTITY_BINDING_INVALID'):
            append_parsed_rows(self.root, run['run_id'], [{
                'position': 1, 'bind_existing_publication_number': 'WO2026019310A1',
                'reviewer': 'agent', 'reason': 'Wrong identity'}])
        self.assertEqual(load_json(self.root / 'evidence.json'), before)

    def test_damage_outside_url_and_false_count_or_duplicate_identity_rejected(self):
        run, evidence, body = self.setup_xml()
        for changed_body, reason in [
                (body.replace(b'https://example.test/watch?v=1&amp%3Bt=2', b'plain &amp%3B text'), 'DAMAGE_UNRECOGNIZED'),
                (body.replace(b'publications-count="2"', b'publications-count="3"'), 'COUNT_INVALID'),
                (body.replace(b'country="WO" doc-number="2026019310"', b'country="US" doc-number="20260233409"'), 'IDENTITY_INVALID')]:
            with self.subTest(reason=reason):
                (self.root / 'epo.xml').write_bytes(changed_body)
                run['payload_digest'] = sha256_bytes(changed_body)
                run['result_processing']['payload_digest'] = run['payload_digest']
                atomic_write_json(self.root / 'evidence.json', evidence)
                with self.assertRaisesRegex(ValueError, reason):
                    self.derive(run)

    def test_derived_spans_refuse_manual_new_candidate_and_invalid_binding_replay(self):
        run, _, _ = self.setup_xml()
        self.derive(run)
        with self.assertRaisesRegex(ValueError, 'EXISTING_IDENTITY_BINDING_REQUIRED'):
            append_parsed_rows(self.root, run['run_id'], [{'position': 1,
                'candidate': {'publication_number': 'US20260233409A1'},
                'reviewer': 'agent', 'reason': 'Would duplicate old candidate'}])
        self.bind(run)
        saved = load_json(self.root / 'evidence.json')
        saved['result_parses'][0]['raw_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'IDENTITY_BINDING_CHANGED'):
            progress(self.root, run, saved)


class OpsZeroConsumerTests(unittest.TestCase):
    def setUp(self):
        ResultProcessingTests.setUp(self)
        self.run, self.evidence, self.body = ResultProcessingTests.ops_empty_fault_run(self)
        self.run["result_processing"].update(returned_count_basis="response_count_only", zero_proven=False)
        self.run.update(jurisdiction="US", right_type="patent", source_environment="production")
        self.run["raw_paths"] = [str(self.root / "ops-empty.xml")]
        self.row = {"query_id": self.run["query_id"], "operation": "search", "jurisdiction": "US", "right_type": "patent"}
        from common import sha256_json
        self.run["plan_entry_sha256"] = sha256_json(self.row)
        self.entry = self.evidence["collections"]["patents"][0]
        self.entry.update(evidence_id="EV-OPS", provider="epo_ops", operation="search", query_id=self.row["query_id"],
            jurisdiction="US", right_type="patent", plan_entry_sha256=self.run["plan_entry_sha256"])
        self.run["metadata"]["search_coverage"].update(total_hits=0, truncated=False, stop_reason="query_exhausted")
        self.plan = {"queries": {"epo_ops": [self.row]}}

    def test_first_business_acceptance_reuses_until_current_anomaly_or_context_changes(self):
        from source_operation import record_operation_acceptance, current_operation_acceptance
        from trusted_api import annotate_entry
        self.task['retrieval_workflow_revision'] = 'api-first-v3'
        annotate_entry(self.task, self.entry, self.run)
        context = {'credential_fingerprint_sha256': 'c' * 64,
            'permission_fingerprint_sha256': 'p' * 64, 'adapter_version': 'a' * 64}
        with patch('common.assert_provider_execution_allowed'), \
                patch('source_operation.operation_acceptance_context', return_value=context) as current, \
                patch('source_operation.load_skill_config', return_value={'providers': {'epo_ops': {}}}):
            acceptance = record_operation_acceptance(self.root, self.task, self.evidence, self.row, self.run, self.entry)
            self.evidence['operation_acceptances'] = [acceptance]
            self.assertTrue(current_operation_acceptance(self.task, self.evidence, 'epo_ops', self.row))
            self.assertIsNone(record_operation_acceptance(self.root, self.task, self.evidence, self.row, self.run, self.entry))
            current.return_value = {**context, 'credential_fingerprint_sha256': 'n' * 64}
            self.assertFalse(current_operation_acceptance(self.task, self.evidence, 'epo_ops', self.row))
            current.return_value = context
            self.evidence['source_runs'].append({**self.run, 'run_id': 'NEW-ANOMALY',
                'finished_at': '2026-09-30T01:00:00Z'})
            self.evidence['operation_acceptance_failures'] = [
                {'source_run_id': 'NEW-ANOMALY', 'reason': 'SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH'}]
            self.assertFalse(current_operation_acceptance(self.task, self.evidence, 'epo_ops', self.row))
            self.assertEqual(len(self.evidence['operation_acceptances']), 1)

    def test_operation_acceptance_reads_legacy_zero_without_rewriting_proof_inputs(self):
        from source_operation import record_operation_acceptance
        from trusted_api import annotate_entry
        self.task["retrieval_workflow_revision"] = "api-first-v3"
        annotate_entry(self.task, self.entry, self.run)
        before = json.dumps(self.evidence, sort_keys=True)
        context = {"credential_fingerprint_sha256": "c" * 64,
                   "permission_fingerprint_sha256": "p" * 64, "adapter_version": "a" * 64}
        with patch("common.assert_provider_execution_allowed"), \
             patch("source_operation.operation_acceptance_context", return_value=context), \
             patch("source_operation.load_skill_config", return_value={"providers": {"epo_ops": {}}}):
            accepted = record_operation_acceptance(self.root, self.task, self.evidence, self.row, self.run, self.entry)
            self.assertTrue(accepted["proof"]["record_identity"]["search_zero_proven"])
            with self.assertRaisesRegex(ValueError, "RESPONSE_MISSING"):
                record_operation_acceptance(None, self.task, self.evidence, self.row, self.run, self.entry)
            (self.root / "ops-empty.xml").write_bytes(self.body.replace(b"No results found", b"Internal failure"))
            with self.assertRaisesRegex(ValueError, "RESPONSE_INCOMPLETE"):
                record_operation_acceptance(self.root, self.task, self.evidence, self.row, self.run, self.entry)
        self.assertEqual(json.dumps(self.evidence, sort_keys=True), before)

    def test_coverage_needs_retained_path_for_legacy_zero_projection(self):
        from assessment_v24 import query_coverage
        with patch("finalize_assessment._authoritative_run", return_value=True):
            without = query_coverage(self.evidence, {}, self.plan, "epo_ops", self.row, self.task)
            self.assertEqual(without["gap"], "ZERO_RESULT_UNVERIFIED")
            verified = query_coverage(self.evidence, {}, self.plan, "epo_ops", self.row, self.task, evidence_root=self.root)
            self.assertTrue(verified["complete"])
            (self.root / "ops-empty.xml").write_bytes(self.body + b" ")
            changed = query_coverage(self.evidence, {}, self.plan, "epo_ops", self.row, self.task, evidence_root=self.root)
            self.assertEqual(changed["gap"], "ZERO_RESULT_UNVERIFIED")

    def test_report_discloses_archived_flag_and_verified_receipt_projection(self):
        from report_query_trace import _attempt
        without = _attempt(self.run, self.row, [self.entry], [], 1, evidence=self.evidence)
        self.assertEqual(without["status"], "unknown")
        verified = _attempt(self.run, self.row, [self.entry], [], 1, evidence=self.evidence, source_task_dir=self.root)
        self.assertEqual(verified["status"], "no_match")
        self.assertTrue(verified["zero_proven"])
        self.assertIs(verified["recorded_zero_proven"], False)
        self.assertEqual(verified["zero_proof_basis"], "retained_receipt_projection")
        (self.root / "ops-empty.xml").write_bytes(self.body + b" ")
        changed = _attempt(self.run, self.row, [self.entry], [], 1, evidence=self.evidence, source_task_dir=self.root)
        self.assertEqual(changed["status"], "unknown")
        self.assertFalse(changed["zero_proven"])


if __name__ == "__main__":
    unittest.main()
