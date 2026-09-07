"""Offline direct-entry and identity contracts; fixtures are not IP evidence."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import common
import provider_utils as transport
import serper_client
import signa_client
import serpapi_patents_client
from authorize_scenario_action import authorize


class ScenarioTransportTests(unittest.TestCase):
    def test_reference_to_actual_product_confirmation_reopens_identity(self):
        from decision_workflow import product_identity_sha256
        task = {"product": {"input_role": "reference_product", "structure": ["flat strap"]}}
        before = product_identity_sha256(task)
        task["product"].update(input_role="actual_product",
            actual_product_confirmation={"source": "user_request", "statement": "Same visible configuration"})
        self.assertNotEqual(before, product_identity_sha256(task))

    def test_metadata_changes_identity_but_never_external_parameters(self):
        metadata = {"decision_workflow_revision": "scenario-triage-v1",
                    "scenario_bindings": [{"scenario_id": "product_entry", "scenario_sha256": "a" * 64}],
                    "action_purpose": "recall", "evidence_obligation_id": "OBL-test"}
        cases = [
            ("serper_patents", "patent_recall", {"q": "lid strap", "num": 10, "right_type": "patent"},
             lambda row: common._serper_expected_query_id("serper_patents", "patent_recall", "US", row)),
            (common.SIGNA_PROVIDER, common.SIGNA_OPERATION,
             {"q": "TEST", "strategies": ["exact"], "filters": {}, "limit": 10, "options": {}, "right_type": "trademark_word"},
             common._signa_expected_query_id),
            (common.SERPAPI_PROVIDER, common.SERPAPI_OPERATION,
             {"q": "lid strap", "num": 10, "country": "US", "right_type": "patent"},
             common._serpapi_expected_query_id),
        ]
        for provider, operation, params, expected in cases:
            with self.subTest(provider=provider):
                old = {**params, "jurisdiction": "US"}
                new = {**old, **metadata}
                self.assertEqual(expected(old), transport.query_identity(provider, operation, "US", params["q"], params))
                self.assertEqual(expected(new), transport.query_identity(provider, operation, "US", params["q"], {**params, **metadata}))
                self.assertNotEqual(expected(old), expected(new))
                external = {k: v for k, v in new.items() if k not in transport.PLAN_META_KEYS}
                self.assertFalse(set(metadata) & set(external))

    def test_shared_guard_is_legacy_noop_and_fail_closed_for_unknown_revision(self):
        with patch("workflow_v24.scenario_dispatch_block_from_dir") as guard:
            transport.authorize_current_scenario_action(Path("unused"), {}, "test", {})
            guard.assert_not_called()
            for revision in ("unknown", "", None):
                with self.subTest(revision=revision):
                    with self.assertRaises(transport.ProviderError) as raised:
                        transport.authorize_current_scenario_action(Path("unused"), {"decision_workflow_revision": revision}, "test", {})
                    self.assertEqual(raised.exception.code, "DECISION_WORKFLOW_REVISION_UNSUPPORTED")

    def test_direct_clients_stop_before_network_when_decision_is_cancelled(self):
        task = {"schema_version": "2.4-free", "decision_workflow_revision": "scenario-triage-v1"}
        error = transport.ProviderError("TRIAGE_ACTION_STALE", "access_limited", "Synthetic cancelled decision")
        cases = [(serper_client, "authorize_serper_free_plan_entry"),
                 (signa_client, "authorize_signa_free_plan_entry"),
                 (serpapi_patents_client, "authorize_serpapi_free_plan_entry")]
        for client, auth_name in cases:
            with self.subTest(client=client.__name__), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                stack.enter_context(patch.object(client, "load_json", side_effect=[task, {}]))
                stack.enter_context(patch.object(client, auth_name, return_value={"query_id": "Q1"}))
                guard = stack.enter_context(patch.object(client, "authorize_current_scenario_action", side_effect=error))
                network = stack.enter_context(patch.object(client, "http_json"))
                if client is serper_client:
                    stack.enter_context(patch.object(client, "_find_entry", return_value=("serper_patents", "patent_recall")))
                if client is serpapi_patents_client:
                    stack.enter_context(patch.object(client, "provider_execution_error", return_value=""))
                with self.assertRaises(transport.ProviderError):
                    client.execute(Path(directory), "Q1")
                guard.assert_called_once()
                network.assert_not_called()

    def test_cli_rejects_unknown_revision_and_ambiguous_query(self):
        from decision_workflow import decision_workflow_enabled
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common.atomic_write_json(root / "task.json", {})
            self.assertEqual(authorize(root, "test", "Q1"), {"allowed": True, "legacy": True})
            for revision in ("future", "", None):
                common.atomic_write_json(root / "task.json", {"decision_workflow_revision": revision})
                self.assertFalse(authorize(root, "test", "Q1")["allowed"])
                with self.assertRaisesRegex(ValueError, "UNSUPPORTED_DECISION_WORKFLOW_REVISION"):
                    decision_workflow_enabled({"decision_workflow_revision": revision})
            common.atomic_write_json(root / "task.json", {"decision_workflow_revision": "scenario-triage-v1"})
            common.atomic_write_json(root / "search-plan.json", {"queries": {"test": [{"query_id": "Q1"}, {"query_id": "Q1"}]}})
            self.assertEqual(authorize(root, "test", "Q1")["code"], "SCENARIO_QUERY_ID_MISMATCH")


if __name__ == "__main__":
    unittest.main()
