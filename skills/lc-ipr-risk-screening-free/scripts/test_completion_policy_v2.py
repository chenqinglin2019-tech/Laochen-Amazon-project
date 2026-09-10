"""Offline compatibility and multi-product planning, never live evidence."""
from copy import deepcopy
from pathlib import Path
import unittest

from common import load_json, sha256_json
from completion_policy import CURRENT_REVISION, supported, evidence_delivery_enabled
from runtime_v24 import operation_accepted, resolved_capabilities
from workflow_v24 import generate_plan, product_identity_digest, work_view_from_dir
import test_api_first_v2 as fixtures
import test_necessary_browser_recovery as recovery_fixtures
import test_necessary_partial_recovery as partial_fixtures


class CompletionPolicyV2Tests(unittest.TestCase):
    def test_capabilities_do_not_accept_another_operation_or_untrusted_saved_assertion(self):
        row = {"jurisdiction": "US", "right_type": "patent", "operation": "search",
               "query_compiler_revision": "one"}
        cap = {"executable": False, "operations": [row]}
        self.assertTrue(operation_accepted(cap, row))
        for field, other in (("jurisdiction", "GB"), ("right_type", "design"),
                             ("operation", "candidate_verification"), ("query_compiler_revision", "two")):
            self.assertFalse(operation_accepted(cap, {**row, field: other}))
        source = {"browser": cap}
        output = resolved_capabilities({"completion_policy_revision": CURRENT_REVISION}, {}, {}, source, None)
        self.assertEqual(output, {"browser": {"executable": False}})
        self.assertEqual(source["browser"], cap)

    def test_revision_predicates_are_closed_and_old_fields_are_not_mutated(self):
        for revision, active, delivery in ((None, False, False), ("necessary-work-v1", True, False),
                                         (CURRENT_REVISION, True, True), ("necessary-work-v3", False, False)):
            task = {"completion_policy_revision": revision}
            before = deepcopy(task)
            self.assertEqual(supported(task), active)
            self.assertEqual(evidence_delivery_enabled(task), delivery)
            self.assertEqual(task, before)
        self.assertFalse(supported(None))

    def test_six_retained_products_have_fair_nonempty_initial_discovery(self):
        corpus = load_json(Path(__file__).resolve().parent.parent / "fixtures/evidence-delivery-products.json")
        self.assertEqual(len(corpus["products"]), 6)
        for product in corpus["products"]:
            with self.subTest(asin=product["asin"], category=product["category"]):
                fixture = fixtures.ApiFirstV2Tests()
                fixture.setUp()
                try:
                    task = fixture.task
                    task["product"].update(title=product["title"], brand=product["brand"],
                        own_brand=product["brand"], structure=deepcopy(product["structure"]))
                    task["query_terms"] = [{"kind": kind, "value": value, "language": "en",
                        "derived_from": "product.structure[" + str(index) + "]", "strategy": "phrase"}
                        for kind, value, index in product["terms"]]
                    if product["brand"] != "Generic":
                        task["query_terms"].append({"kind": "brand", "value": product["brand"],
                            "language": "en", "derived_from": "product.brand", "strategy": "phrase"})
                    task["product"]["analysis"]["identity_sha256"] = product_identity_digest(task["product"], task=task)
                    task["serper_free_enhancement"]["max_queries_per_task"] = 10
                    plan = fixture.regenerate()
                    rows = [row for provider, values in plan["queries"].items()
                            if provider.startswith("serper_") for row in values]
                    self.assertLessEqual(len(rows), 8)
                    self.assertTrue(set(product["expected_first_rights"]) <= {r["right_type"] for r in rows})
                    original = deepcopy(plan["queries"])
                    expanded = generate_plan(fixture.path, expand=True)
                    self.assertEqual(expanded["queries"], original)
                    # Same frozen inputs, no live capabilities or credentials, same work IDs/hash.
                    first = work_view_from_dir(fixture.path, source_capabilities={})
                    second = work_view_from_dir(fixture.path, source_capabilities={})
                    self.assertEqual(first, second)
                    self.assertTrue(first["entries"])
                    self.assertTrue(all(row.get("work_id") for row in first["entries"]))
                    self.assertEqual(first["work_view_sha256"], sha256_json({k: v for k, v in first.items()
                        if k not in {"work_view_sha256", "review_work"}}))
                finally:
                    fixture.tearDown()

    def test_browser_executor_and_cli_use_identical_identity_bound_status(self):
        import test_scenario_planning as scenario_fixtures
        from common import atomic_write_json
        from run_browser_plan import execute_plan
        fixture = scenario_fixtures.ScenarioPlanningTests()
        fixture.setUp()
        try:
            fixture.task["completion_policy_revision"] = CURRENT_REVISION
            fixture.save()
            row = fixture.plan["queries"]["uspto_patent_browser"][0]
            calls = []
            def unavailable(command, timeout=180):
                calls.append(command)
                if "automation-capability" in command:
                    return {"executor_available": False}
                raise AssertionError("No source request is authorized by this offline capability test")
            output = execute_plan(fixture.path, query_id_filter=row["query_id"], runner=unavailable)
            self.assertTrue(calls)
            current = work_view_from_dir(fixture.path)
            self.assertEqual(output["work_view"], current)
            self.assertEqual(load_json(fixture.path / "browser-execution-status.json")["task_id"], fixture.task["task_id"])
        finally:
            fixture.tearDown()

    def test_api_executor_uses_same_frozen_capabilities_as_cli(self):
        from unittest.mock import patch
        from common import atomic_write_json
        from runtime_v24 import execute_api_plan
        fixture = fixtures.ApiFirstV2Tests()
        fixture.setUp()
        try:
            fixture.many_terms(4)
            fixture.regenerate()
            row = fixture.primary()
            fixture.plan.setdefault("execution_dispositions", []).append({
                "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                "status": "cancelled", "reason": "Offline scheduler-only diagnostic"})
            atomic_write_json(fixture.path / "search-plan.json", fixture.plan)
            frozen = {"provider": "serper_patents", "state": "unavailable", "executable": False,
                "reason": "optional_credentials_missing", "credentials_present": False}
            snapshot = {"schema_version": fixture.task["schema_version"],
                "task_id": fixture.task["task_id"], "sources": [frozen]}
            atomic_write_json(fixture.path / "source-capabilities.json", snapshot)
            fresh = {**frozen, "state": "unvalidated", "executable": True,
                "reason": "first_real_query_checks_free_account_and_contract", "credentials_present": True}
            with patch("runtime_v24.capabilities", return_value=[fresh]), patch(
                    "runtime_v24.subprocess.run", side_effect=AssertionError("No source request expected")):
                output = execute_api_plan(fixture.path, query_ids_filter=[row["query_id"]], phase="discovery")
            self.assertEqual(output["results"][0]["dispatch"], "cancelled")
            self.assertEqual(output["work_view"], work_view_from_dir(fixture.path))
            self.assertEqual(load_json(fixture.path / "source-capabilities.json"), snapshot)
        finally:
            fixture.tearDown()


class V2SubmittedFailureTests(recovery_fixtures.SubmittedFailureStateTests):
    def setUp(self):
        super().setUp()
        self.task["completion_policy_revision"] = CURRENT_REVISION


class V2PartialRecoveryTests(partial_fixtures.PartialStateTests):
    def setUp(self):
        super().setUp()
        self.task["completion_policy_revision"] = CURRENT_REVISION


if __name__ == "__main__":
    unittest.main()
