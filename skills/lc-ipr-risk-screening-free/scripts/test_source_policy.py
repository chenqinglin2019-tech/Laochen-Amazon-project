"""Offline regression tests for source policy, shared limits and recovery."""
import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import common
import create_task
import candidate_api_actions
import jpo_api_client
import serpapi_patents_client as patents
import serpapi_patent_details_client as details
import signa_client as signa
import source_policy
import trusted_api
from provider_utils import ProviderError
from recovery_stage_b import record_review


def new_policy_task():
    return {"schema_version": "2.4-free", "task_id": "T-source-policy",
            "free_policy_revision": source_policy.REVISION,
            "free_policy": source_policy.account_policy(),
            "source_settings_revision": source_policy.CONFIG_REVISION,
            "retrieval_policy": {"dynamic_evidence_max_age_hours": 6},
            "retrieval_workflow_revision": "api-first-v3"}


class SourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((common.skill_root() / "references/runtime-config.json").read_text())
        self.task = new_policy_task()

    def test_new_policy_and_original_free_policy_are_both_valid(self):
        self.assertTrue(common.task_free_policy_valid(self.task))
        self.assertTrue(common.task_free_policy_valid({"schema_version": "2.4-free",
            "free_policy_revision": common.AUTOMATION_POLICY_REVISION,
            "free_policy": common.active_free_policy()}))
        for field in ("allow_new_purchase", "allow_recharge", "allow_upgrade"):
            changed = deepcopy(self.task)
            changed["free_policy"][field] = True
            self.assertFalse(common.task_free_policy_valid(changed))
        self.assertIsNone(source_policy.cost_ceiling(self.task))
        self.assertEqual(source_policy.cost_ceiling({}), 0)

    def test_task_creation_freezes_limits_and_opt_in_existing_balance(self):
        self.config["api_first"]["signa_max_requests"] = 1
        self.config["performance"]["dynamic_evidence_max_age_hours"] = 6
        with tempfile.TemporaryDirectory() as directory:
            args = ["create_task.py", "--url", "https://www.amazon.com/dp/B012345678",
                    "--jurisdictions", "US", "--enable-serper-free", "--enable-signa-free",
                    "--output-dir", directory]
            with patch.object(sys, "argv", args), patch.object(create_task, "load_skill_config", return_value=self.config), \
                    patch.object(common, "load_skill_config", return_value=self.config), contextlib.redirect_stdout(io.StringIO()):
                create_task.main()
            task = common.load_json(Path(directory) / "task.json")
        self.assertTrue(common.task_free_policy_valid(task))
        self.assertEqual(task["signa_free_enhancement"]["max_queries_per_task"], 1)
        self.assertEqual(task["retrieval_policy"]["dynamic_evidence_max_age_hours"], 6)
        self.assertTrue(task["serper_existing_balance_authorization"]["authorized"])
        self.assertFalse(task["serpapi_free_enhancement"]["enabled"])
        self.assertEqual(common.signa_free_enhancement_error(task), "")

    def test_review_and_operation_context_bind_new_task_source_policy(self):
        import final_review
        import source_operation
        before = final_review.digest({}, {}, {}, {}, self.task)
        with patch.object(common, "credential", return_value=""), patch.object(source_operation, "load_skill_config", return_value=self.config):
            context = source_operation.operation_acceptance_context(self.task, "signa")
            self.task["retrieval_policy"]["dynamic_evidence_max_age_hours"] = 2
            altered = source_operation.operation_acceptance_context(self.task, "signa")
        self.assertNotEqual(context["permission_fingerprint_sha256"], altered["permission_fingerprint_sha256"])
        self.assertNotEqual(before, final_review.digest({}, {}, {}, {}, self.task))

    def test_frozen_freshness_controls_fact_acceptance(self):
        entry = {"trusted_api_record": {"checked_at": "2026-10-02T00:00:00+00:00"}}
        self.config["performance"]["dynamic_evidence_max_age_hours"] = 48
        self.assertEqual(source_policy.dynamic_max_age_hours(self.task, self.config), 6)
        self.assertFalse(trusted_api._fresh(self.task, entry, "2026-10-03T00:00:00+00:00"))
        self.assertTrue(trusted_api._fresh({}, entry, "2026-10-03T00:00:00+00:00"))
        for value in (None, True, 0, -1, float("nan"), float("inf")):
            self.task["retrieval_policy"]["dynamic_evidence_max_age_hours"] = value
            with self.assertRaisesRegex(ValueError, "SOURCE_FRESHNESS"):
                source_policy.dynamic_max_age_hours(self.task)

    def test_null_or_non_object_retrieval_policy_retains_legacy_default_and_rejects_new_tasks(self):
        self.assertEqual(source_policy.dynamic_max_age_hours({"retrieval_policy": None}), 48)
        for value in (None, [], ["invalid"], "invalid"):
            task = {**self.task, "retrieval_policy": value}
            with self.assertRaisesRegex(ValueError, "SOURCE_FRESHNESS"):
                source_policy.dynamic_max_age_hours(task)

    def test_signa_detail_budget_matches_lowered_search_budget(self):
        self.task["signa_free_enhancement"] = common.signa_free_enhancement(True, maximum=1)
        with patch.object(signa, "consumed_queries", return_value=1), patch.object(signa, "persisted_stop_reason", return_value=None):
            self.assertEqual(candidate_api_actions._budget_issue(self.task, {"source_runs": []}, {}, "signa"),
                             "FREE_TASK_REQUEST_LIMIT_REACHED")

    def test_paid_serpapi_capacity_is_accepted_only_for_new_policy(self):
        payload = {"plan_name": "Pro", "plan_monthly_price": 75, "plan_searches_left": 0,
                   "extra_credits": 20, "account_status": "active"}
        with patch.object(patents, "http_json", return_value=(payload, {}, b"{}")):
            value = patents.free_account_snapshot("https://example.test", "dummy", 1, task=self.task)
            self.assertEqual(value["searches_available"], 20)
            self.assertEqual(value["plan_monthly_price"], 75)
            self.assertFalse(value["cost_verified"])
            with self.assertRaises(ProviderError):
                patents.free_account_snapshot("https://example.test", "dummy", 1)
            for field, bad in (("extra_credits", -1), ("plan_searches_left", None), ("account_status", "suspended"), ("plan_name", {"invalid": "plan"}), ("plan_monthly_price", "1e10000")):
                changed = {**payload, field: bad}
                with patch.object(patents, "http_json", return_value=(changed, {}, b"{}")), self.assertRaises(ProviderError):
                    patents.free_account_snapshot("https://example.test", "dummy", 1, task=self.task)

    def test_paid_detail_execution_reserves_existing_credits_once_without_purchasing(self):
        self.task["serpapi_free_enhancement"] = common.serpapi_free_enhancement(True, "api-first-v3")
        row = {"query_id": "Q-detail", "operation": "candidate_detail", "jurisdiction": "US",
               "right_type": "patent", "q": "US1234567B2", "publication_number": "US1234567B2",
               "patent_id": "patent/US1234567B2/en", "candidate_id": "C1"}
        account = {"plan_name": "Pro", "plan_monthly_price": 75, "plan_searches_left": 0,
                   "extra_credits": 2, "account_status": "active"}
        payload = {"publication_number": row["q"], "claims": ["1. A synthetic strap."], "images": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common.atomic_write_json(root / "task.json", self.task)
            common.atomic_write_json(root / "evidence.json", {"task_id": self.task["task_id"], "source_runs": []})
            with patch.dict(os.environ, {"LC_IPR_TEST_MODE": "1", "LC_IPR_FREE_SEARCH_LEDGER_DIR": str(root / "ledger")}), \
                    patch.object(details, "_item", return_value=(self.task, row)), \
                    patch.object(details, "settings", return_value=({"http": {"timeout_seconds": 1}}, "http://127.0.0.1", "dummy-paid-test")), \
                    patch.object(patents, "http_json", return_value=(account, {}, b"{}")), \
                    patch.object(details, "http_json", return_value=(payload, {}, json.dumps(payload).encode())) as network, \
                    patch.object(details, "record_result", side_effect=lambda _, **values: values):
                result = details.execute(root, row["query_id"])
                self.assertEqual(result["status"], "success")
                self.assertFalse(result["quota"]["cost_verified"])
                self.assertEqual(result["quota"]["plan_monthly_price"], 75)
                self.assertEqual(result["quota"]["local_free_searches_left"], 1)
                with self.assertRaises(ProviderError) as repeated:
                    details.execute(root, row["query_id"])
                self.assertEqual(repeated.exception.code, "FREE_SEARCH_ALREADY_RESERVED")
            self.assertEqual(network.call_count, 1)

    def test_signa_paid_plan_and_credits_preserve_actual_fields(self):
        identity = {"plan": "pro", "billing_preview": True,
                    "api_key": {"scopes": ["trademarks:read", "billing:read"]}}
        credits = {"balance": 20, "reserved": 1, "pending": 1,
                   "grants": {"plan": 10, "addon": 10, "promo": 0}}
        self.assertEqual(signa._identity_state(identity, task=self.task)["plan"], "pro")
        self.assertEqual(signa._credit_state(credits, task=self.task)["balance"], 20)
        with self.assertRaises(ProviderError):
            signa._identity_state(identity)
        with self.assertRaises(ProviderError):
            signa._credit_state(credits)
        credits["balance"] = -1
        with self.assertRaises(ProviderError):
            signa._credit_state(credits, task=self.task)

    def test_signa_operation_config_is_versioned(self):
        with patch.object(signa, "load_skill_config", return_value=self.config), patch.object(signa, "credential", return_value="dummy"):
            signa.settings(self.task)
            signa.settings()
            self.config["providers"]["signa"]["v3_supported_operations"] = ["trademark_search"]
            with self.assertRaisesRegex(ProviderError, "configuration violates"):
                signa.settings(self.task)
            signa.settings()  # Historical search configuration remains valid.

    def test_jpo_data_does_not_request_transport_retries(self):
        def transport(url, **kwargs):
            self.assertEqual(kwargs["retries"], 0)
            return {"result": {"statusCode": "100", "remainAccessCount": 10, "data": {}}}, {}, b"{}"
        client = jpo_api_client.JpoApiClient(self.config, transport=transport)
        with patch.object(client, "_authenticate", return_value="dummy"):
            client._get("patent", "progress", "2020000001")

    def test_detail_success_repair_requires_exact_claim_and_actual_repair_condition(self):
        from datetime import datetime, timedelta, timezone
        self.task["continuous_recovery_revision"] = "continuous-recovery-stage-b-v1"
        row = {"query_id": "Q-detail", "operation": "candidate_detail", "jurisdiction": "US",
               "right_type": "patent", "q": "US123B1", "publication_number": "US123B1"}
        run = {"run_id": "R1", "provider": "serpapi_google_patents", "operation": "candidate_detail",
               "query_id": row["query_id"], "plan_entry_sha256": common.sha256_json(row),
               "jurisdiction": "US", "right_type": "patent", "query": row["q"],
               "request_params": {"q": row["q"], "publication_number": row["q"]},
               "status": "success", "submission_state": "submitted", "raw_paths": [],
               "finished_at": (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()}
        evidence = {"task_id": self.task["task_id"], "source_runs": [run]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common.atomic_write_json(root / "task.json", self.task)
            raw = root / "raw.json"
            raw.write_text('{}')
            run.update(raw_paths=[str(raw)], payload_digest=common.sha256_file(raw))
            evidence["collections"] = {"patents": [{"source_run_id": "R1", "payload": {}}]}
            identity = {"provider": "serpapi_google_patents", "query_id": row["query_id"],
                        "plan_entry_sha256": common.sha256_json(row), "prior_source_run_id": "R1",
                        "retry_reason": "dynamic_evidence_expired"}
            attempt = "repair-" + common.sha256_json(identity)[:24]
            with self.assertRaises(ProviderError):
                details.authorize_detail_retry(root, self.task, row, evidence, attempt, identity["retry_reason"])
            common.atomic_write_json(root / "api-retry-claims.json", {"task_id": self.task["task_id"], "attempts": {attempt: identity}})
            details.authorize_detail_retry(root, self.task, row, evidence, attempt, identity["retry_reason"])
            run["finished_at"] = datetime.now(timezone.utc).isoformat()
            with self.assertRaises(ProviderError):
                details.authorize_detail_retry(root, self.task, row, evidence, attempt, identity["retry_reason"])
            identity["retry_reason"] = "retained_evidence_missing_or_changed"
            attempt = "repair-" + common.sha256_json(identity)[:24]
            common.atomic_write_json(root / "api-retry-claims.json", {"task_id": self.task["task_id"], "attempts": {attempt: identity}})
            raw.unlink()
            details.authorize_detail_retry(root, self.task, row, evidence, attempt, identity["retry_reason"])
            with self.assertRaises(ProviderError):
                details.authorize_detail_retry(root, self.task, row, evidence, attempt, "unbound reason")

    def test_detail_retry_requires_bound_receipt_review_and_stops_after_two_failures(self):
        self.task["continuous_recovery_revision"] = "continuous-recovery-stage-b-v1"
        row = {"query_id": "Q-detail", "operation": "candidate_detail", "jurisdiction": "US",
               "right_type": "patent", "q": "US123B1", "publication_number": "US123B1"}
        run = {"run_id": "R1", "provider": "serpapi_google_patents", "operation": "candidate_detail",
               "query_id": row["query_id"], "plan_entry_sha256": common.sha256_json(row),
               "jurisdiction": "US", "right_type": "patent", "query": row["q"],
               "request_params": {"q": row["q"], "publication_number": row["q"]},
               "status": "failed", "submission_state": "submitted", "error_code": "TIMEOUT", "raw_paths": []}
        evidence = {"task_id": self.task["task_id"], "source_runs": [run]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common.atomic_write_json(root / "task.json", self.task)
            common.atomic_write_json(root / "evidence.json", evidence)
            with self.assertRaises(ProviderError):
                details.authorize_detail_retry(root, self.task, row, evidence, "retry-1", "source recovered")
            record_review(root, {"kind": "failure_review", "source_run_id": "R1",
                "source_run_sha256": common.sha256_json(run), "reviewer": "offline reviewer",
                "reasoning": "Original request and receipt checked", "receipt_review": "original error receipt checked",
                "receipt_absence_reason": "no response body; retained error receipt checked",
                "material_review": "no readable response", "remaining_work": "exact known record",
                "failure_cause": "source timeout", "repair_basis": "source access recovered",
                "source_rule_ref": "source-policy.md", "source_allows_retry": True})
            evidence = common.load_json(root / "evidence.json")
            details.authorize_detail_retry(root, self.task, row, evidence, "retry-1", "source recovered")
            evidence["source_runs"].append({**run, "run_id": "R2"})
            with self.assertRaises(ProviderError):
                details.authorize_detail_retry(root, self.task, row, evidence, "retry-2", "source recovered again")
            evidence["source_runs"] = [{**run, "submission_state": "unknown"}]
            with self.assertRaises(ProviderError):
                details.authorize_detail_retry(root, self.task, row, evidence, "retry-3", "unknown receipt")


if __name__ == "__main__":
    unittest.main()
