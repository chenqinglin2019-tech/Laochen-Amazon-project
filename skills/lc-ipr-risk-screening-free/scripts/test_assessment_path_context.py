"""Offline task-relative files with an explicit historical supplement boundary."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import assessment_estimate as assessment
import report_estimate as report
from common import atomic_write_bytes, atomic_write_json, load_json, sha256_file, sha256_json
from decision_workflow import make_annotation
from record_candidate_lead import SCHEMA, build_record
from test_assessment_workflow_correction import corrected_fixture
from workflow_v24 import product_identity_digest


class TaskArtifactContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ipr-path-context-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "new"
        self.source.mkdir()
        self.values = corrected_fixture(self.source)
        task, evidence, candidates, plan, ledger, first, second = self.values
        task["historical_evidence_root"] = str(self.root)
        self.document = self.source / "local-document.txt"
        atomic_write_bytes(self.document, b"OFFLINE TEST ONLY US1234567B2")
        self.original = {"evidence_id": "LOCAL-ORIGINAL", "kind": "patent_document",
            "publication_number": "US1234567B2", "jurisdiction": "US", "right_type": "patent",
            "path": self.document.name, "sha256": sha256_file(self.document),
            "bytes": self.document.stat().st_size, "checked_at": "2026-09-07T00:00:00Z",
            "source_url": "https://example.test/local-original"}
        atomic_write_json(self.source / "lead-source.json", {"schema": "retained-test", "evidence": [self.original]})
        payload = {"schema": SCHEMA, "publication_number": "US1234567B2", "jurisdiction": "US",
            "right_type": "patent", "title": "Synthetic source-binding document",
            "product_identity_sha256": product_identity_digest(task["product"], task=task),
            "source_registration": {"kind": "supplement", "manifest": "lead-source.json",
                                    "evidence_id": self.original["evidence_id"]},
            "document": {key: self.original[key] for key in ("path", "sha256", "bytes", "source_url")},
            "review": {"reviewer": "offline-path-regression", "reviewed_at": "2026-09-07T00:00:00Z",
                "number_location": "test text line 1", "number_quote": "US1234567B2",
                "content_verification": "agent_read_original", "reasoning": "Offline path regression, not a finding."}}
        self.lead = build_record(task, evidence, self.source, payload)
        evidence["collections"]["candidate_leads"] = [self.lead]
        evidence["collections"]["local_originals"] = [self.original,
            {"evidence_id": "LOCAL-NESTED", "document": deepcopy(payload["document"])}]
        candidates["trademarks"][0]["publication_documents"] = [deepcopy(payload["document"])]
        self.historical = self.root / "historical.txt"
        atomic_write_bytes(self.historical, b"retained historical test content")
        self.supplement = {"schema": "retained-test", "evidence_root": str(self.root), "evidence": [
            {"evidence_id": "HIST-RELATIVE", "path": self.historical.name,
             "sha256": sha256_file(self.historical), "bytes": self.historical.stat().st_size,
             "kind": "source_document", "checked_at": "2026-09-07T00:00:00Z",
             "source_url": "https://example.test/historical"},
            {"evidence_id": "HIST-ABSOLUTE", "path": str(self.historical),
             "sha256": sha256_file(self.historical), "bytes": self.historical.stat().st_size,
             "kind": "source_document", "checked_at": "2026-09-07T00:00:00Z",
             "source_url": "https://example.test/historical"}]}
        for run in evidence["source_runs"]:
            run["raw_paths"] = [str(Path(path).relative_to(self.source)) for path in run.get("raw_paths", [])]
        ledger["annotations"] = [make_annotation(task, "trademarks", candidates["trademarks"][0], row,
            evidence=evidence, supplement=self.supplement) for row in ledger["annotations"]]
        for review in (first, second):
            review["assessments"][0]["evidence_refs"].extend(["LOCAL-ORIGINAL", "HIST-RELATIVE", "HIST-ABSOLUTE"])
            review["review_context"]["evidence_digest"] = assessment.review_digest(
                evidence, candidates, ledger, plan, task, self.supplement)
        for name, value in zip(("task", "evidence", "normalized-candidates", "search-plan",
                                "materiality-annotations", "first-review", "second-review"), self.values):
            atomic_write_json(self.source / (name + ".json"), value)
        atomic_write_json(self.source / "supplemental-evidence.json", self.supplement)

    def test_inputs_use_task_dir_but_supplement_keeps_explicit_root(self):
        with self.assertRaisesRegex(ValueError, "CANDIDATE_LEAD_DOCUMENT_OUTSIDE_OR_MISSING"):
            assessment.validate_inputs(*self.values[:5], evidence_root=self.root, supplement=self.supplement)
        self.assertEqual(assessment.validate_inputs(*self.values[:5], evidence_root=self.root,
            supplement=self.supplement, task_dir=self.source), [])
        self.assertEqual(len(assessment.validate_supplement(self.supplement, self.root,
            task=self.values[0], evidence=self.values[1])), 2)

    def test_tampered_local_nested_or_historical_file_still_fails(self):
        for path in (self.document, self.historical):
            content = path.read_bytes()
            atomic_write_bytes(path, content + b"tampered")
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "HASH|BINDING"):
                assessment.compute_assessment(*self.values, supplement=self.supplement,
                    evidence_root=self.root, task_dir=self.source)
            atomic_write_bytes(path, content)

    def test_candidate_lead_cannot_escape_task_dir_even_inside_historical_root(self):
        evidence = deepcopy(self.values[1])
        evidence["collections"]["candidate_leads"][0]["document"]["path"] = "../historical.txt"
        from record_candidate_lead import validated_candidate_lead_entries
        with self.assertRaisesRegex(ValueError, "OUTSIDE_OR_MISSING"):
            validated_candidate_lead_entries(self.values[0], evidence, self.source)

    def test_legacy_and_context_free_resolution_do_not_change(self):
        task = dict(self.values[0])
        task.pop("workflow_correction_revision")
        self.assertEqual(assessment.task_artifact_root(task, self.root, self.source), self.root)
        self.assertEqual(assessment.task_artifact_root(self.values[0], self.root), self.root)
        self.assertIsNone(assessment.task_artifact_root(task, "", self.source))

    def test_missing_task_file_does_not_fall_back_to_same_name_at_boundary(self):
        atomic_write_bytes(self.root / self.document.name, self.document.read_bytes())
        self.document.unlink()
        with self.assertRaisesRegex(ValueError, "HASH|OUTSIDE_OR_MISSING|ARTIFACT_INVALID"):
            assessment.validate_inputs(*self.values[:5], evidence_root=self.root,
                supplement=self.supplement, task_dir=self.source)

    def test_report_recursive_media_copy_preserves_inputs_and_boundary(self):
        original = deepcopy(self.values[1])
        media = report._task_file_declarations(original, self.root, self.source)
        self.assertEqual(original, self.values[1])
        self.assertEqual(media["collections"]["candidate_leads"][0]["document"]["path"], str(self.document))
        self.assertEqual(media["collections"]["local_originals"][1]["document"]["path"], str(self.document))
        bindings = report._registered_files(self.root, media, self.supplement)
        self.assertIn(str(self.document), bindings)
        self.assertIn(str(self.historical), bindings)
        outside = {"path": "../../outside.txt", "sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "OUTSIDE_EVIDENCE_ROOT"):
            report._task_file_declarations(outside, self.root, self.source)
        private = {"private": True, "path": "../../private.txt", "sha256": "0" * 64}
        self.assertEqual(report._task_file_declarations(private, self.root, self.source), private)

    def test_publish_build_and_independent_validate_keep_task_context(self):
        from publish_report import publish
        before = {path: sha256_file(path) for path in self.source.glob("*.json")}
        output = self.root / "published"
        with patch.object(assessment, "compute_assessment", wraps=assessment.compute_assessment) as compute:
            result = publish(self.source, self.source / "first-review.json", self.source / "second-review.json",
                             output_dir=output)
        self.assertEqual(result["file_integrity"], "valid")
        self.assertEqual(compute.call_count, 2)
        self.assertTrue(all(Path(call.kwargs["task_dir"]) == self.source for call in compute.call_args_list))
        data = load_json(output / "report-data.json")
        files = {item.get("evidence_id"): item.get("source_path") for item in data["evidence_index"]}
        self.assertEqual(files["LOCAL-ORIGINAL"], str(self.document))
        self.assertEqual(files["HIST-RELATIVE"], str(self.historical))
        self.assertEqual(files["HIST-ABSOLUTE"], str(self.historical))
        self.assertEqual(data["trace"]["input_digests"]["evidence"], report._digest(self.values[1]))
        task = load_json(output / "task.json")
        with patch.object(assessment, "compute_assessment", wraps=assessment.compute_assessment) as compute:
            self.assertEqual(report.validate_run(self.source, task, output_dir=output), [])
        self.assertEqual(Path(compute.call_args.kwargs["task_dir"]), self.source)
        with patch.object(assessment, "compute_assessment", wraps=assessment.compute_assessment) as compute:
            report.build_bundle(self.source, task, self.values[1], load_json(output / "assessment.json"),
                self.values[2], {"schema_version": "1.0", "task_id": task["task_id"], "entries": []},
                self.values[3], output_dir=self.root / "standalone")
        self.assertEqual(Path(compute.call_args.kwargs["task_dir"]), self.source)
        self.assertTrue(all(sha256_file(path) == digest for path, digest in before.items()))


if __name__ == "__main__":
    unittest.main()
