"""Consumer acceptance follows a verified Lens receipt without a new request."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import test_lens_physical_reuse as lens_fixture
from common import atomic_write_json, load_json, sha256_json
from provider_utils import PLAN_META_KEYS
from review_progress_stage_a import _completion
from source_operation import current_operation_acceptance, record_operation_acceptance
from trusted_api import annotate_entry


class LensConsumerReuseTests(unittest.TestCase):
    def setUp(self):
        self.f = lens_fixture.LensReuseTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.original_row = {**self.f.row, "query_id": "old", "right_type": "design"}
        self.f.original["plan_entry_sha256"] = sha256_json(self.original_row)
        self.f.entry["plan_entry_sha256"] = self.f.original["plan_entry_sha256"]
        annotate_entry(self.f.task, self.f.entry, self.f.original)
        self.f.save()
        self.plan = {"queries": {"serpapi_google_lens": [self.original_row, self.f.row]}}
        atomic_write_json(self.f.root / "search-plan.json", self.plan)
        self.reused = self.f.reuse()
        self.evidence = load_json(self.f.root / "evidence.json")
        self.copied = self.evidence["collections"]["copyright_assets"][-1]

    def test_progress_accepts_logical_run_only_with_exact_physical_receipt(self):
        task = {**self.f.task, "product_change_version": "1"}
        item = {"kind": "query", "provider": "serpapi_google_lens", "query_id": self.f.row["query_id"],
            "plan_entry_sha256": sha256_json(self.f.row), "scope": {"product_version": "1"}}
        request = {"source_run_id": self.reused["run_id"],
                   "evidence_refs": [self.reused["run_id"], self.copied["evidence_id"]]}
        before = deepcopy(self.evidence)
        result = _completion(item, request, task, self.evidence, self.plan, {"entries": []}, self.f.root)
        self.assertEqual(result["source_run_id"], self.reused["run_id"])
        self.assertEqual(self.evidence, before)
        with self.assertRaisesRegex(ValueError, "SUCCESSFUL_BOUND_RUN_REQUIRED"):
            _completion(item, request, task, self.evidence, self.plan, {"entries": []})
        for change in ({"source_run_sha256": "wrong"}, {"source_finished_at": "2099-01-01T00:00:00Z"}):
            changed = deepcopy(self.evidence)
            changed["source_runs"][-1]["metadata"]["physical_response_reuse"].update(change)
            with self.assertRaisesRegex(ValueError, "SUCCESSFUL_BOUND_RUN_REQUIRED"):
                _completion(item, request, task, changed, self.plan, {"entries": []}, self.f.root)

    def test_operation_reuses_original_acceptance_and_cannot_create_new_one(self):
        context = {"credential_fingerprint_sha256": "c" * 64,
                   "permission_fingerprint_sha256": "p" * 64, "adapter_version": "a" * 64}
        config = {"providers": {"serpapi_google_lens": {}}}
        with patch("common.assert_provider_execution_allowed"), \
             patch("source_operation.operation_acceptance_context", return_value=context), \
             patch("source_operation.load_skill_config", return_value=config):
            accepted = record_operation_acceptance(self.f.root, self.f.task, self.evidence,
                self.original_row, self.f.original, self.f.entry)
            self.evidence["operation_acceptances"] = [accepted]
            before = deepcopy(self.evidence)
            self.assertTrue(current_operation_acceptance(self.f.task, self.evidence,
                "serpapi_google_lens", self.f.row, self.f.root))
            self.assertFalse(current_operation_acceptance(self.f.task, self.evidence,
                "serpapi_google_lens", self.f.row))
            with self.assertRaisesRegex(ValueError, "PHYSICAL_REUSE_NOT_NEW_REQUEST"):
                record_operation_acceptance(self.f.root, self.f.task, self.evidence,
                    self.f.row, self.reused, self.copied)
            changed = deepcopy(self.evidence)
            changed["source_runs"][-1]["metadata"]["physical_response_reuse"]["source_run_sha256"] = "wrong"
            self.assertFalse(current_operation_acceptance(self.f.task, changed,
                "serpapi_google_lens", self.f.row, self.f.root))
            self.assertEqual(self.evidence, before)

    def test_semantic_after_review_binds_logical_query_to_verified_original(self):
        import test_discovery_semantics as semantic_fixture
        from common import now_iso, sha256_file
        from discovery_semantics import current
        from runtime_v24 import _physical_request_identity
        fixture = semantic_fixture.DiscoverySemanticsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prior_provider, prior_row = fixture.provider, fixture.row
        row = {**prior_row, "operation": "image_search", "q": self.f.url, "image_url": self.f.url,
               "hl": "en", "country": "us", "type": "all"}
        fixture.plan["queries"][prior_provider] = [item for item in fixture.plan["queries"][prior_provider]
                                                   if item["query_id"] != row["query_id"]]
        original_row = {**row, "query_id": "ORIGINAL-LENS-SEMANTIC"}
        fixture.plan["queries"]["serpapi_google_lens"] = [original_row, row]
        fixture.provider, fixture.row = "serpapi_google_lens", row
        root = fixture.f.run
        atomic_write_json(root / "search-plan.json", fixture.plan)
        fixture.direction()
        fixture.before()
        raw = root / "lens-receipt.json"
        atomic_write_json(raw, {"search_metadata": {"status": "Success"}, "visual_matches": []})
        params = {key: value for key, value in row.items() if key not in PLAN_META_KEYS}
        params["right_type"] = row["right_type"]
        checked_at = now_iso()
        original = {"run_id": "ORIGINAL-LENS", "provider": fixture.provider, "operation": "image_search",
            "query_id": original_row["query_id"], "plan_entry_sha256": sha256_json(original_row),
            "status": "success", "submission_state": "submitted", "quota": {"network_request_attempted": True},
            "jurisdiction": "US", "right_type": "design", "request_params": params,
            "started_at": checked_at, "finished_at": checked_at, "raw_paths": [str(raw)],
            "payload_digest": sha256_file(raw), "metadata": {}}
        identity = _physical_request_identity(fixture.provider, row)
        logical = {**deepcopy(original), "run_id": "RUN-SEMANTIC", "query_id": row["query_id"],
            "plan_entry_sha256": sha256_json(row), "submission_state": "not_submitted",
            "source_query_performed": False, "quota": {"network_request_attempted": False},
            "metadata": {"physical_response_reuse": {"source_run_id": original["run_id"],
                "source_run_sha256": sha256_json(original), "request_identity_sha256": sha256_json(identity),
                "source_finished_at": checked_at, "bound_at": checked_at,
                "independent_source_count": 1, "network_request_attempted": False}}}
        evidence = load_json(root / "evidence.json")
        evidence["source_runs"].extend([original, logical])
        evidence["collections"].setdefault("copyright_assets", []).extend([
            {"evidence_id": "EV-ORIGINAL", "source_run_id": original["run_id"], "payload": {"candidates": []}},
            {"evidence_id": "EV-SEMANTIC", "source_run_id": logical["run_id"], "payload": {"candidates": []}}])
        atomic_write_json(root / "evidence.json", evidence)
        after = fixture.after()
        task = load_json(root / "task.json")
        options = dict(stage="after", scenario_id="product_entry", jurisdiction="US", right_type="design",
                       direction_id="outline", provider=fixture.provider, row=row)
        self.assertEqual(current(task, fixture.plan, evidence, task_dir=root, **options)["review_id"], after["review_id"])
        self.assertIsNone(current(task, fixture.plan, evidence, **options))
        evidence["source_runs"][-1]["metadata"]["physical_response_reuse"]["source_run_sha256"] = "tampered"
        self.assertIsNone(current(task, fixture.plan, evidence, task_dir=root, **options))

    def test_report_shows_one_original_request_and_explicit_response_reuse(self):
        from report_query_trace import _attempt, _bounded_discovery_receipt, build_query_trace
        self.f.row["action_purpose"] = "discovery"
        self.original_row["action_purpose"] = "discovery"
        # Bind the current logical row after adding report-only discovery
        # metadata. The original receipt remains unchanged and historical.
        self.reused["plan_entry_sha256"] = sha256_json(self.f.row)
        self.evidence["source_runs"][-1] = self.reused
        self.copied["plan_entry_sha256"] = self.reused["plan_entry_sha256"]
        annotate_entry(self.f.task, self.copied, self.reused)
        self.plan = {"queries": {"serpapi_google_lens": [self.f.row]}}
        atomic_write_json(self.f.root / "search-plan.json", self.plan)
        bound = _bounded_discovery_receipt(self.evidence, self.f.row, self.reused, self.f.root)
        self.assertTrue(bound["valid"])
        attempt = _attempt(self.reused, self.f.row, [self.copied], [], 1,
            discovery=bound, evidence=self.evidence, source_task_dir=self.f.root)
        self.assertEqual(attempt["status"], "hit")
        self.assertFalse(attempt["source_query_performed"])
        self.assertTrue(attempt["physical_response_reused"])
        self.assertEqual(attempt["physical_source_run_id"], self.f.original["run_id"])
        self.assertEqual(attempt["checked_at"], self.f.original["finished_at"])
        trace = build_query_trace(self.f.task, self.evidence, {}, {}, self.plan, source_task_dir=self.f.root)
        self.assertEqual(trace["summary"]["effective_search_count"], 1)
        self.reused["metadata"]["physical_response_reuse"]["source_run_sha256"] = "tampered"
        invalid = _attempt(self.reused, self.f.row, [self.copied], [], 1,
            evidence=self.evidence, source_task_dir=self.f.root)
        self.assertEqual(invalid["status"], "not_run")
        self.assertFalse(invalid["physical_response_reused"])


if __name__ == "__main__":
    unittest.main()
