"""Offline PPS capture/recorder/reading-work chain; all inputs are synthetic."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, sha256_file, sha256_json
from provider_utils import sanitize_for_evidence, validate_text_evidence
from record_browser_execution import planned_browser_query
from run_browser_plan import execute_plan
from same_task_evidence import _pps_text
from workflow_v24 import append_candidate_actions, requested_facts_satisfied, scenario_reading_material
from finalize_assessment import verification_plan_binding_errors
import test_scenario_planning


class RetainedPpsPipelineTests(unittest.TestCase):
    def setUp(self):
        self.f = test_scenario_planning.ScenarioPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        self.skill = Path(__file__).resolve().parents[1]
        f.candidate = {"candidate_id": "P-RETAINED", "publication_number": "US3431004A", "title": "Synthetic retaining strap",
                       "jurisdiction": "US", "right_type": "patent", "evidence_refs": ["E1"]}
        f.candidates["patents"] = [f.candidate]
        f.candidates["trademarks"] = []
        f.evidence["collections"] = {"patents": [{"evidence_id": "E1", "payload": deepcopy(f.candidate)}]}
        self.action = {"action_id": "READ-TEXT", "kind": "source_lookup", "purpose": "abstract", "max_attempts": 1,
            "provider": "uspto_patent_browser", "operation": "candidate_verification",
            "params": {"q": "US3431004A", "record_number": "US3431004A", "candidate_id": "P-RETAINED", "strategy": "record_number"},
            "required_facts": ["abstract"], "reading_scope": {"level": "abstract"}}
        self.annotate()
        self.source = deepcopy(self.row)
        at = now_iso()
        shot = f.path / "screenshots" / "synthetic-pps.png"
        atomic_write_bytes(shot, base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII="))
        semantics = planned_browser_query("uspto_patent_browser", self.source, f.task)
        self.capture = {"browser": "chrome_desktop", "capture_transport": "cdp", "browser_version": "Chrome-offline-test",
            "protocol_version": "1.3", "cdp_session_id": "synthetic_session", "status": "success", "submission_state": "submitted",
            "query_id": self.source["query_id"], "candidate_id": "P-RETAINED", "record_number": "US3431004A", "page_record_number": "US3431004A",
            "right_type": "patent", "title": f.candidate["title"], "final_url": "https://ppubs.uspto.gov/pubwebapp/", "checked_at": at,
            "screenshot_path": str(shot), "query_semantics": semantics, "workflow_correction_revision": "workflow-correction-v1",
            "required_facts": ["abstract"], "reading_scope": {"level": "abstract"}, "satisfied_facts": ["abstract"],
            "content_retrieval_status": "completed", "phase": "retrieve_requested_content",
            "abstract": "A basic and useful strap.\nBearer synthetic-secret",
            "rendered_text": "ABSTRACT OF THE DISCLOSURE\nA basic and useful strap.\nBearer synthetic-secret\nClaims\n1. A strap.",
            "document_retrieval": {"status": "success", "authority_scope": "published_document_only", "identity_match": True,
                "record_number": "US3431004A", "title": f.candidate["title"], "document_pages": []}}
        self.events = [
            {"action": "submit_query", "actor": "agent", "at": at, "rendered_query": semantics["rendered_query"], "input_value": semantics["rendered_query"]},
            {"action": "observe_query_binding", "actor": "agent", "at": at, "query": semantics["rendered_query"], "result_set_id": "L1",
                "screenshot_path": str(shot), "screenshot_sha256": sha256_file(shot)},
            {"action": "observe_result", "actor": "agent", "at": at, "stable": True, "identity": "US3431004A", "screenshot_sha256": sha256_file(shot)}]
        self.path = f.path / ("uspto_patent_browser-" + self.source["query_id"] + "-synthetic-capture.json")

    def annotate(self):
        f = self.f
        from merge_candidates import candidate_verification_view, verification_index
        f.candidate.update(candidate_verification_view(f.task, "patents", f.candidate, f.evidence,
            verification_index(f.evidence["collections"].get("official_verifications", []))))
        f.annotate("needs_info", missing_information=["Read original text"], next_actions=[self.action])
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        self.row = next(row for row in reversed(f.plan["queries"]["uspto_patent_browser"]) if row.get("candidate_id") == f.candidate["candidate_id"])

    def persist(self, *, revision=True, refresh_hash=True):
        js = """import {executionReceipt,ppubsTextEvidenceMetadata} from './tools/cdp/cdp-cli.mjs';
let raw=''; for await (const c of process.stdin) raw+=c; const x=JSON.parse(raw);
if(x.revision && x.refresh) { x.capture.text_evidence_revision='retained-text-v1'; Object.assign(x.capture.document_retrieval,ppubsTextEvidenceMetadata(x.capture.rendered_text)); }
console.log(JSON.stringify({capture:x.capture,receipt:executionReceipt(x.task,'uspto_patent_browser',x.query,x.events,x.capture)}));"""
        if not revision:
            self.capture["document_retrieval"]["rendered_text_sha256"] = sha256_json(self.capture["rendered_text"])
        result = subprocess.run(["node", "--input-type=module", "-e", js], cwd=self.skill,
            input=json.dumps({"task": self.f.task, "query": self.source, "capture": self.capture,
                             "events": self.events, "revision": revision, "refresh": refresh_hash}), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.capture = value["capture"]
        receipt_path = self.f.path / "raw/browser-execution/synthetic-pps-receipt.json"
        atomic_write_json(receipt_path, value["receipt"])
        self.capture["query_execution"] = {"path": str(receipt_path), "sha256": sha256_file(receipt_path)}
        atomic_write_json(self.path, self.capture)

    def record(self, expected_error=None):
        before = sha256_file(self.f.path / "evidence.json")
        result = subprocess.run([sys.executable, str(self.skill / "scripts/record_uspto_patent_chrome_verification.py"),
            "--task-dir", str(self.f.path), "--capture", str(self.path)], capture_output=True, text=True)
        if expected_error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected_error, result.stderr)
            self.assertEqual(sha256_file(self.f.path / "evidence.json"), before)
            return
        self.assertEqual(result.returncode, 0, result.stderr)
        self.f.task = load_json(self.f.path / "task.json")
        self.f.evidence = load_json(self.f.path / "evidence.json")
        return self.f.evidence["collections"]["official_verifications"][-1]["payload"]

    def material(self):
        f = self.f
        return scenario_reading_material(f.task, f.plan, f.evidence, f.candidates, f.ledger,
            "uspto_patent_browser", self.row, task_dir=f.path)

    def test_real_corrected_recorder_binds_source_retained_abstract_and_consumer(self):
        self.persist()
        before = sha256_file(self.path)
        payload = self.record()
        self.assertEqual(before, sha256_file(self.path))
        self.assertEqual(validate_text_evidence(payload, expected_stage="retained"), "retained")
        self.assertIn("basic and", payload["document_text"])
        self.assertNotIn("synthetic-secret", payload["document_text"])
        self.assertTrue(requested_facts_satisfied(self.row, payload))
        raw = load_json(Path(self.f.evidence["source_runs"][-1]["raw_paths"][0]))
        self.assertEqual(raw["rendered_text"], payload["document_text"])
        self.assertEqual(raw, sanitize_for_evidence(self.capture))
        self.assertEqual(sanitize_for_evidence(raw), raw)
        f = self.f
        merge = subprocess.run([sys.executable, str(self.skill / "scripts/merge_candidates.py"), "--task-dir", str(f.path)], capture_output=True, text=True)
        self.assertEqual(merge.returncode, 0, merge.stderr)
        f.candidates = load_json(f.path / "normalized-candidates.json")
        self.assertEqual(verification_plan_binding_errors(f.task, f.evidence, f.candidates, f.plan), [])
        for mutate in (lambda p: p["published_document"].update(rendered_text_sha256="0" * 64),
                       lambda p: p.update(abstract="not in the full text"),
                       lambda p: p["published_document"].update(rendered_text_stage="source")):
            bad = deepcopy(payload); mutate(bad)
            self.assertFalse(requested_facts_satisfied(self.row, bad))
            evidence = deepcopy(f.evidence)
            evidence["collections"]["official_verifications"][-1]["payload"] = bad
            self.assertTrue(any("TEXT_EVIDENCE_" in item for item in verification_plan_binding_errors(f.task, evidence, f.candidates, f.plan)))

    def test_wrong_inner_hash_fails_even_after_outer_receipt_rehash(self):
        self.persist()
        self.capture["document_retrieval"]["rendered_text_sha256"] = "0" * 64
        self.persist(refresh_hash=False)
        self.record("TEXT_EVIDENCE_HASH_MISMATCH")

    def test_legacy_corrected_recorder_still_rejects_unbound_abstract(self):
        self.capture["abstract"] = "This is not in the source text"
        self.persist(revision=False)
        self.record("Abstract is not bound")

    def test_saved_full_text_without_abstract_becomes_read_work_not_new_query(self):
        self.capture.update(status="access_limited", error_code="REQUESTED_CONTENT_INCOMPLETE", satisfied_facts=[],
                            abstract="", content_retrieval_status="incomplete", rendered_text="Old publication without an abstract heading.\nClaims\n1. A retaining strap.")
        self.persist()
        self.record()
        # Same already-submitted action: available reading must take priority
        # over the bounded-attempt gate without authorizing a second query.
        result = self.material()
        self.assertIsNotNone(result)
        self.assertEqual(result["dispatch"], "agent_read_required")
        self.assertFalse(result["complete"])
        self.assertEqual(result["satisfied_facts"], [])
        self.assertEqual(result["source_query_id"], self.source["query_id"])
        self.assertEqual(result["source_document"]["text_pointer"], "/rendered_text")
        f = self.f
        before = sha256_file(f.path / "evidence.json")
        output = execute_plan(f.path, query_ids_filter=[self.row["query_id"]], runner=lambda *_: self.fail("must not query"))
        self.assertEqual(next(row for row in output["queries"] if row["query_id"] == self.row["query_id"])["dispatch"], "agent_read_required")
        self.assertEqual(sha256_file(f.path / "evidence.json"), before)
        self.assertTrue(any(item.get("kind") == "agent_read" and item.get("query_id") == self.row["query_id"] for item in output["work_view"]["entries"]))
        entry = f.evidence["collections"]["official_verifications"][-1]
        saved_payload = deepcopy(entry["payload"])
        entry["payload"]["published_document"]["rendered_text"] += " altered normalized text"
        f.save()
        self.assertIsNone(self.material())
        entry["payload"] = saved_payload
        f.save()
        raw = Path(f.evidence["source_runs"][-1]["raw_paths"][0])
        original = raw.read_bytes()
        atomic_write_bytes(raw, original + b" ")
        self.assertIsNone(self.material())
        atomic_write_bytes(raw, original)
        bad = deepcopy(self.capture); bad["rendered_text"] += "changed"
        atomic_write_json(self.path, bad)
        self.assertIsNone(self.material())
        atomic_write_json(self.path, self.capture)
        receipt = Path(self.capture["query_execution"]["path"])
        atomic_write_bytes(receipt, receipt.read_bytes() + b" ")
        self.assertIsNone(self.material())

    def test_old_unmarked_text_is_readable_without_migrating_it(self):
        self.capture.update(status="access_limited", error_code="REQUESTED_CONTENT_INCOMPLETE", satisfied_facts=[], abstract="",
                            rendered_text="ABSTRACT OF THE DISCLOSURE\nA basic and old strap.\nClaims\n1. A strap.")
        self.persist(revision=False)
        self.record()
        self.annotate()
        before = sha256_file(self.path)
        self.assertIsNotNone(self.material())
        self.assertEqual(sha256_file(self.path), before)
        self.assertNotIn("text_evidence_revision", load_json(self.path))

    def test_bad_source_plan_truncation_or_missing_requested_figure_gets_no_credit(self):
        self.capture.update(status="access_limited", error_code="REQUESTED_CONTENT_INCOMPLETE", satisfied_facts=[], abstract="",
                            rendered_text="x" * 200000)
        self.persist()
        self.record()
        self.annotate()
        self.assertIsNone(self.material())
        f = self.f
        target = {**self.row, "required_facts": ["representative_figures"], "reading_scope": {"level": "representative_figures", "page_numbers": [1]}}
        self.assertIsNone(_pps_text(f.task, f.plan, f.evidence, f.candidate, target, task_dir=f.path, root=f.path))
        plan = deepcopy(f.plan)
        next(r for r in plan["queries"]["uspto_patent_browser"] if r["query_id"] == self.source["query_id"])["q"] = "US9999999A"
        self.assertIsNone(_pps_text(f.task, plan, f.evidence, f.candidate, self.row, task_dir=f.path, root=f.path))


if __name__ == "__main__":
    unittest.main()
