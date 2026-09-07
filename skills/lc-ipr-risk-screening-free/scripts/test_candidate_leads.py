"""Offline synthetic fixtures: known-document handoff is not blind recall."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file
from assessment_estimate import validate_inputs, _substantive_refs
from assessment_v24 import evidence_index
from annotate_materiality import main as annotate_main
from merge_candidates import main as merge_main, merge
from record_candidate_lead import (SCHEMA, build_record, record_candidate_lead,
                                  validated_candidate_lead_entries)
from test_assessment_estimate_recall import strict_fixture
from verify_recall_acceptance import evaluate_recall
from workflow_v24 import product_identity_digest


class CandidateLeadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.values = strict_fixture(self.root)
        self.task, self.evidence, self.candidates, self.plan, self.ledger, *_ = self.values
        self.task["product"]["requested_asin"] = "B000000001"
        for filename, value in (("task.json", self.task), ("evidence.json", self.evidence),
                                ("search-plan.json", self.plan)):
            atomic_write_json(self.root / filename, value)
        artifact = self.root / "synthetic-publication.txt"
        artifact.write_text("OFFLINE SYNTHETIC TEST ONLY. US1234567B2 Fixture retainer. "
                            "Prior publication US20100123456A1.")
        self.source = {"evidence_id": "EV-ORIGINAL-FIXTURE", "kind": "patent_document",
            "publication_number": "US1234567B2", "jurisdiction": "US", "right_type": "patent",
            "path": artifact.name, "sha256": sha256_file(artifact), "bytes": artifact.stat().st_size,
            "source_url": "https://example.test/synthetic-publication", "checked_at": "2026-09-06T01:00:00Z",
            "publication_relations": [{"publication_number": "US20100123456A1", "relation": "prior_publication"}]}
        self.supplement = {"schema": "IPR-RETAINED-DOCUMENTS/1.0", "task_id": self.task["task_id"],
                           "evidence": [self.source], "coverage_notes": []}
        self.payload = {"schema": SCHEMA, "publication_number": "US1234567B2", "jurisdiction": "US",
            "right_type": "patent", "title": "Fixture retainer",
            "product_identity_sha256": product_identity_digest(self.task["product"], task=self.task),
            "source_registration": {"kind": "supplement", "manifest": "supplemental-evidence.json",
                                    "evidence_id": self.source["evidence_id"]},
            "document": {key: self.source[key] for key in ("path", "sha256", "bytes", "source_url")},
            "review": {"reviewer": "offline-test-reviewer", "reviewed_at": "2026-09-06T01:01:00Z",
                       "number_location": "synthetic fixture, line 1", "number_quote": "US1234567B2 Fixture retainer",
                       "reasoning": "Synthetic source-binding regression only; no live finding.",
                       "content_verification": "agent_read_original"},
            "publication_relations": [{"publication_number": "US20100123456A1", "relation": "prior_publication",
                                       "location": "synthetic fixture, line 1", "quote": "Prior publication US20100123456A1"}]}
        self.save_supplement()

    def save_supplement(self):
        atomic_write_json(self.root / "supplemental-evidence.json", self.supplement)

    def register(self):
        return record_candidate_lead(self.root, self.payload)

    def current_evidence(self):
        return load_json(self.root / "evidence.json")

    def merge_cli(self):
        with patch("sys.argv", ["merge_candidates.py", "--task-dir", str(self.root)]), redirect_stdout(StringIO()):
            merge_main()
        return load_json(self.root / "normalized-candidates.json")

    def test_valid_import_is_bound_unreviewed_not_official_and_idempotent(self):
        before_runs = deepcopy(self.evidence["source_runs"])
        record, created = self.register()
        self.assertTrue(created)
        digest = sha256_file(self.root / "evidence.json")
        self.assertEqual(self.register(), (record, False))
        self.assertEqual(sha256_file(self.root / "evidence.json"), digest)
        current = self.current_evidence()
        self.assertEqual(before_runs, current["source_runs"])
        self.assertNotIn("source_run_id", record)
        candidate = self.merge_cli()["patents"][0]
        self.assertFalse(candidate["material"])
        self.assertEqual(candidate["disposition"], "unreviewed")
        self.assertEqual(candidate["right_state"], "unknown")
        self.assertEqual(candidate["official_verification"]["status"], "not_checked")
        self.assertIsNone(candidate["official_verification"]["identity_match"])
        self.assertEqual(candidate["official_verification"]["owner"], [])
        self.assertEqual(candidate["authority_scope"], "published_document_only")
        self.assertEqual(candidate["evidence_refs"], [record["evidence_id"]])
        self.assertIn(record["evidence_id"], evidence_index(current))
        self.assertEqual(candidate["sources"][0]["status"], "")
        self.assertEqual(len(self.merge_cli()["patents"]), 1)

    def test_materiality_review_reaches_known_number_action_and_survives_remerge(self):
        self.register()
        candidate = self.merge_cli()["patents"][0]
        arguments = ["annotate_materiality.py", "--task-dir", str(self.root), "--candidate-id", candidate["candidate_id"],
                     "--material", "true", "--material-reason", "Synthetic comparison requires further verification", "--reviewer", "test"]
        with patch("sys.argv", arguments), redirect_stdout(StringIO()):
            annotate_main()
        current = self.merge_cli()["patents"][0]
        self.assertEqual(current["candidate_id"], candidate["candidate_id"])
        self.assertTrue(current["material"])
        actions = [row for rows in load_json(self.root / "search-plan.json")["queries"].values() for row in rows
                   if row.get("candidate_id") == candidate["candidate_id"] and row["operation"] == "candidate_verification"]
        self.assertTrue(any(row.get("record_number") == "US1234567B2" for row in actions))
        self.assertTrue(all(row.get("strategy") == "record_number" for row in actions))

    def test_document_relation_does_not_guess_or_create_family_member(self):
        record, _ = self.register()
        patents = self.merge_cli()["patents"]
        self.assertEqual(len(patents), 1)
        self.assertEqual(patents[0]["publication_relations"][0]["publication_number"], "US20100123456A1")
        self.assertEqual(patents[0]["publication_relations"][0]["evidence_refs"], [record["evidence_id"]])
        self.assertFalse(patents[0].get("family_id"))
        self.assertNotIn("US20100123456A1", patents[0].get("publication_numbers", []))

    def test_same_number_merges_without_overwriting_verified_status_or_materiality(self):
        self.register()
        lead = validated_candidate_lead_entries(self.task, self.current_evidence(), self.root)
        official = {"evidence_id": "EV-RECALL", "provider": "uspto_patent_browser", "payload": {"candidates": [
            {"publication_number": "US1234567B2", "title": "Official fixture title", "jurisdiction": "US", "right_type": "patent",
             "material": True, "official_verification": {"status": "verified", "identity_match": True, "checked_at": "2026-01-01T00:00:00Z"}}]}}
        for entries in ([official, *lead], [*lead, official]):
            candidate = merge("patent", entries, {})[0]
            self.assertTrue(candidate["material"])
            self.assertEqual(candidate["official_verification"]["status"], "verified")
            self.assertEqual(len(candidate["sources"]), 2)
            self.assertTrue(candidate["publication_documents"])

    def test_evidence_collection_can_supply_registered_original(self):
        self.evidence["collections"]["original_documents"] = [self.source]
        atomic_write_json(self.root / "evidence.json", self.evidence)
        self.payload["source_registration"] = {"kind": "evidence", "evidence_id": self.source["evidence_id"]}
        self.register()
        self.assertEqual(len(self.merge_cli()["patents"]), 1)

    def test_scope_number_hash_url_identity_and_review_fail_closed(self):
        changes = [({"publication_number": "USD123456S1"}, "SCOPE_OR_TYPE"),
                   ({"publication_number": "US1234567"}, "PUBLICATION_INVALID"),
                   ({"publication_number": "US7654321B2"}, "REGISTERED_PUBLICATION"),
                   ({"jurisdiction": "GB"}, "SCOPE_OR_TYPE"),
                   ({"right_type": "design"}, "SCOPE_OR_TYPE"),
                   ({"product_identity_sha256": "0" * 64}, "PRODUCT_IDENTITY"),
                   ({"document": {**self.payload["document"], "sha256": "0" * 64}}, "HASH_OR_BINDING"),
                   ({"document": {**self.payload["document"], "bytes": True}}, "HASH_OR_BINDING"),
                   ({"document": {**self.payload["document"], "source_url": "https://unregistered.test/doc"}}, "SOURCE_URL"),
                   ({"review": {**self.payload["review"], "number_quote": "US7654321B2"}}, "NUMBER_QUOTE"),
                   ({"review": {**self.payload["review"], "number_quote": "US1234567B20"}}, "NUMBER_QUOTE"),
                   ({"review": {**self.payload["review"], "content_verification": "automatic_text_claim"}}, "SOURCE_REVIEW"),
                   ({"review": {**self.payload["review"], "reviewed_at": "2026-01-01T00:00:00"}}, "TIMESTAMP")]
        for change, error in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                build_record(self.task, self.evidence, self.root, {**self.payload, **change})

    def test_quote_alone_cannot_register_number_or_relation(self):
        self.source.pop("publication_number")
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "PUBLICATION_INVALID"):
            self.register()
        self.source["publication_number"] = "US1234567B2"
        self.source["publication_relations"] = []
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "RELATION_NOT_DOCUMENT_BACKED"):
            self.register()

    def test_original_publication_slash_format_survives_reconstruction(self):
        self.payload["publication_relations"][0]["quote"] = "US 2010/0123456 A1"
        self.register()
        self.assertEqual(len(validated_candidate_lead_entries(self.task, self.current_evidence(), self.root)), 1)

    def test_failed_or_nonproduction_source_cannot_be_promoted(self):
        self.source["source_run_id"] = "R-FAILED"
        self.evidence["source_runs"].append({"run_id": "R-FAILED", "status": "failed"})
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "SOURCE_RUN_NOT_SUCCESSFUL"):
            build_record(self.task, self.evidence, self.root, self.payload)
        self.evidence["source_runs"][-1].update(status="success", source_environment="fixture")
        with self.assertRaisesRegex(ValueError, "NONPRODUCTION_SOURCE"):
            build_record(self.task, self.evidence, self.root, self.payload)
        self.source.pop("source_run_id")
        self.source["test_only"] = True
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "NONPRODUCTION_SOURCE"):
            self.register()

    def test_all_project_nonproduction_source_markers_are_rejected(self):
        markers = [{"source_environment": value} for value in (
            "sandbox", "fixture", "test", "test_fixture", "mock", "simulation",
            "non_production", "synthetic", "offline", " TEST_FIXTURE ")]
        markers += [{key: True} for key in (
            "test_only", "fixture", "synthetic", "simulation", "mock", "non_production")]
        markers += [{"provenance": {"environment": "test_fixture"}},
                    {"capture_provenance": {"kind": "fixture"}}]
        original = deepcopy(self.source)
        for marker in markers:
            with self.subTest(marker=marker):
                self.source.clear()
                self.source.update(deepcopy(original) | marker)
                self.save_supplement()
                with self.assertRaisesRegex(ValueError, "NONPRODUCTION_SOURCE"):
                    build_record(self.task, self.evidence, self.root, self.payload)

    def test_nonproduction_markers_are_inherited_from_registered_source_chain(self):
        for origin in ("task", "payload", "registration", "supplement", "source_run", "evidence"):
            with self.subTest(origin=origin):
                task, evidence, payload, supplement = map(deepcopy, (
                    self.task, self.evidence, self.payload, self.supplement))
                if origin == "task":
                    target = task
                elif origin == "payload":
                    target = payload
                elif origin == "registration":
                    target = payload["source_registration"]
                elif origin == "supplement":
                    target = supplement
                elif origin == "source_run":
                    target = {"run_id": "R-REGISTERED-SOURCE", "status": "success"}
                    supplement["evidence"][0]["source_run_id"] = target["run_id"]
                    evidence["source_runs"].append(target)
                else:
                    target = evidence
                    evidence["collections"]["original_documents"] = [deepcopy(self.source)]
                    payload["source_registration"] = {"kind": "evidence", "evidence_id": self.source["evidence_id"]}
                target["provenance"] = {"source_environment": "test_fixture"}
                atomic_write_json(self.root / "supplemental-evidence.json", supplement)
                with self.assertRaisesRegex(ValueError, "NONPRODUCTION_SOURCE"):
                    build_record(task, evidence, self.root, payload)

    def test_real_agent_review_and_unrelated_fixture_source_are_not_rejected(self):
        self.source.update(source_environment="agent_review", fixture=False)
        self.supplement["source_environment"] = "agent_document_review"
        self.payload["review"]["reasoning"] = "Read original document; fixture and test are prose, not provenance."
        unrelated = deepcopy(self.source) | {"evidence_id": "EV-OTHER-FIXTURE", "fixture": True}
        self.supplement["evidence"].append(unrelated)
        self.save_supplement()
        self.assertEqual(build_record(self.task, self.evidence, self.root, self.payload)["source_environment"],
                         "agent_document_review")
        self.evidence["collections"]["original_documents"] = [self.source, unrelated]
        self.evidence["source_runs"].append({"run_id": "R-UNRELATED", "status": "success", "fixture": True})
        self.payload["source_registration"] = {"kind": "evidence", "evidence_id": self.source["evidence_id"]}
        self.assertEqual(build_record(self.task, self.evidence, self.root, self.payload)["authority_scope"],
                         "published_document_only")

    def test_new_nonproduction_container_marker_invalidates_imported_lead(self):
        self.register()
        self.supplement["source_environment"] = "non_production"
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "NONPRODUCTION_SOURCE"):
            validated_candidate_lead_entries(self.task, self.current_evidence(), self.root)

    def test_missing_or_duplicate_source_and_derived_image_rejected(self):
        self.payload["source_registration"]["evidence_id"] = "UNREGISTERED"
        with self.assertRaisesRegex(ValueError, "NOT_UNIQUE"):
            self.register()
        self.payload["source_registration"]["evidence_id"] = self.source["evidence_id"]
        self.supplement["evidence"].append(deepcopy(self.source))
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EVIDENCE_ID"):
            self.register()
        self.supplement["evidence"].pop()
        self.source["source_document"] = self.source["path"]
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "ORIGINAL_PUBLICATION"):
            self.register()

    def test_path_escape_or_unregistered_file_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            file = Path(outside) / "outside.txt"
            file.write_text("not in this task")
            self.payload["document"]["path"] = str(file)
            with self.assertRaisesRegex(ValueError, "OUTSIDE_OR_MISSING"):
                self.register()

    def test_tampering_document_or_registration_fails_after_import(self):
        self.register()
        evidence = self.current_evidence()
        self.source["title"] = "changed after import"
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "REGISTRATION_CHANGED"):
            validated_candidate_lead_entries(self.task, evidence, self.root)
        self.source.pop("title")
        self.save_supplement()
        (self.root / self.source["path"]).write_text("tampered retained document")
        with self.assertRaisesRegex(ValueError, "HASH_OR_SIZE_MISMATCH"):
            validated_candidate_lead_entries(self.task, evidence, self.root)

    def test_injected_verification_fields_in_record_rejected(self):
        self.register()
        evidence = self.current_evidence()
        evidence["collections"]["candidate_leads"][0]["payload"] = {"candidates": [{"material": True}]}
        with self.assertRaisesRegex(ValueError, "REGISTRATION_CHANGED"):
            validated_candidate_lead_entries(self.task, evidence, self.root)

    def test_existing_lead_conflict_is_not_silently_overwritten(self):
        self.register()
        before = sha256_file(self.root / "evidence.json")
        self.payload["title"] = "Conflicting replacement"
        with self.assertRaisesRegex(ValueError, "IDENTITY_CONFLICT"):
            self.register()
        self.assertEqual(sha256_file(self.root / "evidence.json"), before)

    def test_source_append_does_not_invalidate_existing_entry_binding(self):
        self.register()
        extra = deepcopy(self.source)
        extra["evidence_id"] = "EV-UNRELATED-APPEND"
        self.supplement["evidence"].append(extra)
        self.save_supplement()
        self.assertEqual(len(validated_candidate_lead_entries(self.task, self.current_evidence(), self.root)), 1)

    def test_historical_schema_ignored_and_import_rejected(self):
        for task in ({**self.task, "schema_version": "2.3-free"},
                     {key: value for key, value in self.task.items() if key != "screening_revision"}):
            with self.subTest(schema=task.get("schema_version")):
                self.assertEqual(validated_candidate_lead_entries(task, {"collections": {"candidate_leads": "ignored"}}, self.root), [])
                with self.assertRaisesRegex(ValueError, "REQUIRES_RECALL_INTEGRITY"):
                    build_record(task, self.evidence, self.root, self.payload)

    def test_completed_run_is_read_only(self):
        self.task["state"] = "completed"
        atomic_write_json(self.root / "task.json", self.task)
        with self.assertRaisesRegex(ValueError, "COMPLETED_RUN_READ_ONLY"):
            self.register()

    def test_assessment_registry_revalidates_registration_and_keeps_document_refs(self):
        record, _ = self.register()
        evidence = self.current_evidence()
        validate_inputs(self.task, evidence, self.candidates, self.plan, self.ledger, evidence_root=self.root)
        self.assertEqual(_substantive_refs([record["evidence_id"]], evidence_index(evidence), {}), {record["evidence_id"]})
        self.source["publication_number"] = "US7654321B2"
        self.save_supplement()
        with self.assertRaisesRegex(ValueError, "REGISTERED_PUBLICATION_MISMATCH"):
            validate_inputs(self.task, evidence, self.candidates, self.plan, self.ledger, evidence_root=self.root)

    def test_known_design_document_cannot_pass_blind_recall(self):
        artifact = self.root / self.source["path"]
        artifact.write_text("OFFLINE SYNTHETIC TEST ONLY. USD123456S1 fixture strap")
        self.source.update(sha256=sha256_file(artifact), bytes=artifact.stat().st_size)
        self.payload["document"].update(sha256=self.source["sha256"], bytes=self.source["bytes"])
        self.source.update(publication_number="USD123456S1", right_type="design", publication_relations=[])
        self.payload.update(publication_number="USD123456S1", right_type="design", publication_relations=[])
        self.payload["review"]["number_quote"] = "USD123456S1 synthetic fixture"
        self.save_supplement()
        self.register()
        self.merge_cli()
        oracle = {"schema": "IPR-RECALL-ORACLE/1.0", "asin": self.task["product"]["requested_asin"],
            "jurisdiction": "US", "right_type": "design", "expected_publication_numbers": ["USD123456S1"],
            "identity_review": {"reviewer": "fixture", "reasoning": "Synthetic test only", "artifacts": [
                {"path": str(self.root / self.source["path"]), "sha256": self.source["sha256"], "source_url": self.source["source_url"]}]}}
        self.assertEqual(evaluate_recall(self.root, oracle)["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
