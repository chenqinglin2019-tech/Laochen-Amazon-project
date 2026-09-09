"""Private supply-chain requests cannot substitute for public investigations."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from assessment_v24 import query_coverage
from common import sha256_file, sha256_json
from record_asset_provenance import asset_scope, external_information_actions, investigation_complete
import test_asset_scope


class ExternalInformationTests(unittest.TestCase):
    def setUp(self):
        original = test_asset_scope.AssetScopeTests()
        original.setUp()
        self.task = original.task
        self.task["completion_policy_revision"] = "necessary-work-v1"
        self.temp = tempfile.TemporaryDirectory(prefix="ipr-external-info-")
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict("os.environ", {"LC_IPR_OFFLINE_TESTS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.registry, artifacts = {}, []
        for eid, name, kind in (("EV-PRODUCT", "source.html", "provenance_document"),
                                ("EV-IMAGE", "source.png", "source_image")):
            path = Path(self.temp.name) / name
            path.write_bytes(("synthetic offline binding fixture " + name).encode())
            artifact = {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size, "role": "source"}
            artifacts.append(artifact)
            self.registry[eid] = {"evidence_id": eid, "kind": kind, "source_url": "https://example.org/fixture", **artifact}
        scope = asset_scope(self.task, "product_entry", "copyright")
        self.query = {"query_id": "Q-public-provenance", "operation": "provenance_review", "jurisdiction": "US",
            "right_type": "copyright", "search_dimension": "provenance", "asset_scope_sha256": scope["scope_sha256"]}
        self.payload = {"scenario_id": "product_entry", "asset_scope_sha256": scope["scope_sha256"],
            "coverage_attestation": {"inventory_complete": True, "asset_ids": scope["asset_ids"], "reviewed_asset_ids": scope["asset_ids"]},
            "unresolved": ["No private licence supplied; absence of licence not established"],
            "outstanding_actions": [{"action_id": "SUPPLIER-LICENCE", "kind": "user_information", "owner": "supplier",
                "purpose": "Check the proposed product's own supply chain", "question": "Can your supplier provide its applicable licence or creation records?",
                "reasoning": "The published source policy addresses general users and cannot establish this supplier's private permission.",
                "evidence_needed": ["supply_chain_authorization", "independent_creation_records"],
                "evidence_refs": ["EV-PRODUCT", "EV-IMAGE"]}],
            "artifacts": artifacts, "investigation_steps": [{"step": "provenance", "status": "completed",
                "reasoning": "Retained original source and the adopted configuration compared in this synthetic fixture",
                "artifact_sha256": [item["sha256"] for item in artifacts], "evidence_refs": ["EV-PRODUCT", "EV-IMAGE"]}]}

    def external(self, payload=None, task=None, registry=None):
        return external_information_actions(task or self.task, self.payload if payload is None else payload,
            self.query, "product_entry", self.registry if registry is None else registry)

    def coverage(self, payloads):
        evidence = {"collections": {"sources": list(self.registry.values()), "asset_provenance": []}, "source_runs": []}
        for index, payload in enumerate(payloads):
            run = {**{key: self.query[key] for key in ("query_id", "operation", "jurisdiction", "right_type")},
                "provider": "asset_provenance", "run_id": "R-" + str(index), "status": "success", "plan_entry_sha256": sha256_json(self.query)}
            evidence["source_runs"].append(run)
            evidence["collections"]["asset_provenance"].append({**run, "evidence_id": "EV-REVIEW-" + str(index),
                "source_run_id": run["run_id"], "payload": deepcopy(payload)})
        return query_coverage(evidence, {}, {"queries": {"asset_provenance": [self.query]}}, "asset_provenance", self.query,
            self.task, scenario_id="product_entry")

    def test_valid_private_request_is_separate_from_completed_public_work(self):
        before = deepcopy(self.payload)
        result = self.external()
        self.assertEqual(result, self.payload["outstanding_actions"])
        self.assertFalse(investigation_complete(self.task, self.payload, self.query, "product_entry", self.registry))
        result[0]["question"] = "changed return value"
        self.assertEqual(self.payload, before)
        coverage = self.coverage([self.payload])
        self.assertFalse(coverage["complete"])
        self.assertTrue(coverage["retrieval_complete"])
        self.assertEqual(coverage["investigation_status"], "completed")
        self.assertEqual(coverage["gap"], "USER_INFORMATION_REQUIRED")
        self.assertEqual(coverage["evidence_refs"], ["EV-REVIEW-0"])

    def test_missing_or_incomplete_public_step_cannot_become_user_work(self):
        for change in ({"investigation_steps": []}, {"artifacts": []},
                       {"coverage_attestation": {"inventory_complete": False}}, {"scenario_id": "brand_reuse"}):
            with self.subTest(change=change):
                self.assertEqual(self.external({**self.payload, **change}), [])
        incomplete = deepcopy(self.payload)
        incomplete["investigation_steps"][0]["status"] = "pending"
        self.assertEqual(self.external(incomplete), [])

    def test_stale_scope_or_unreviewed_inventory_reopens_public_work(self):
        self.assertEqual(self.external({**self.payload, "asset_scope_sha256": "stale"}), [])
        task = deepcopy(self.task)
        task["product"]["asset_scope_review"]["status"] = "pending"
        self.assertEqual(self.external(task=task), [])
        self.query["asset_scope_sha256"] = "stale"
        self.assertEqual(self.external(), [])

    def test_unknown_unregistered_or_receipt_only_refs_cannot_establish_dependency(self):
        self.assertEqual(self.external(registry={}), [])
        for kind in ("agent_review", "retained_source_record"):
            registry = deepcopy(self.registry)
            registry["EV-PRODUCT"]["kind"] = kind
            self.assertEqual(self.external(registry=registry), [])
        for refs in ([], ["EV-PRODUCT"], ["EV-IMAGE"], ["UNKNOWN"], ["EV-PRODUCT", "EV-PRODUCT"]):
            payload = deepcopy(self.payload)
            payload["outstanding_actions"][0]["evidence_refs"] = refs
            self.assertEqual(self.external(payload), [], refs)

    def test_changed_retained_file_is_not_accepted(self):
        Path(self.payload["artifacts"][0]["path"]).write_text("changed fixture")
        self.assertEqual(self.external(), [])

    def test_empty_generic_public_or_mixed_actions_remain_agent_work(self):
        for key, value in (("question", " "), ("reasoning", ""), ("purpose", ""), ("action_id", ""),
                ("owner", "public_registry"), ("owner", None), ("owner", []),
                ("evidence_needed", []), ("evidence_needed", None), ("evidence_needed", ["public_search"]),
                ("evidence_needed", ["supply_chain_authorization", "supply_chain_authorization"]),
                ("kind", "public_investigation")):
            with self.subTest(key=key, value=value):
                payload = deepcopy(self.payload)
                payload["outstanding_actions"][0][key] = value
                self.assertEqual(self.external(payload), [])
        for extra in ({"kind": "agent_read", "purpose": "Read original page"},
                      deepcopy(self.payload["outstanding_actions"][0]), "read original"):
            payload = deepcopy(self.payload)
            payload["outstanding_actions"].append(extra)
            self.assertEqual(self.external(payload), [])

    def test_unknown_facts_without_explicit_dependency_do_not_create_user_work(self):
        payload = {**self.payload, "outstanding_actions": []}
        self.assertEqual(self.external(payload), [])
        self.assertTrue(self.coverage([payload])["complete"])

    def test_latest_private_dependency_cannot_fall_back_to_earlier_completed_payload(self):
        old = {**self.payload, "outstanding_actions": []}
        result = self.coverage([old, self.payload])
        self.assertFalse(result["complete"])
        self.assertEqual(result["evidence_refs"], ["EV-REVIEW-1"])
        self.assertTrue(result["external_information_actions"])

    def test_latest_invalid_or_mixed_revision_cannot_hide_behind_old_completion(self):
        old = {**self.payload, "outstanding_actions": []}
        for mutation in ("mixed", "missing_evidence", "missing_step", "stale"):
            payload = deepcopy(self.payload)
            if mutation == "mixed":
                payload["outstanding_actions"].append({"kind": "agent_read"})
            elif mutation == "missing_evidence":
                payload["outstanding_actions"][0]["evidence_refs"] = []
            elif mutation == "missing_step":
                payload["investigation_steps"] = []
            else:
                payload["asset_scope_sha256"] = "stale"
            result = self.coverage([old, payload])
            self.assertFalse(result["complete"], mutation)
            self.assertFalse(result["retrieval_complete"], mutation)
            self.assertNotIn("external_information_actions", result)

    def test_later_satisfied_request_can_complete_without_rewriting_history(self):
        current = {**self.payload, "outstanding_actions": [], "unresolved": []}
        self.assertTrue(self.coverage([self.payload, current])["complete"])

    def test_legacy_tasks_keep_existing_completion_semantics(self):
        self.task.pop("completion_policy_revision")
        self.assertEqual(self.external(), [])
        old = {**self.payload, "outstanding_actions": []}
        self.assertTrue(self.coverage([old, self.payload])["complete"])

    def test_actual_plan_and_work_view_distinguish_private_request_from_public_work(self):
        from common import atomic_write_json
        from record_asset_provenance import inventory_identity_sha256
        from test_scenario_planning import ScenarioPlanningTests
        from workflow_v24 import generate_plan, product_identity_digest, work_view_from_dir
        fixture = ScenarioPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.task["completion_policy_revision"] = "necessary-work-v1"
        fixture.task["product"]["assets"] = deepcopy(self.task["product"]["assets"])
        fixture.task["product"]["asset_scope_review"] = {
            "status": "reviewed", "reviewer": "offline-agent", "reasoning": "Actual fixture inventory reviewed",
            "evidence_refs": ["EV-PRODUCT"], "inventory_identity_sha256_by_right": {
                right: inventory_identity_sha256(fixture.task, right) for right in ("copyright", "trade_dress")}}
        fixture.task["product"]["analysis"]["identity_sha256"] = product_identity_digest(fixture.task["product"], task=fixture.task)
        registry, artifacts = deepcopy(self.registry), []
        for item in registry.values():
            path = fixture.path / Path(item["path"]).name
            path.write_bytes(Path(item["path"]).read_bytes())
            item["path"] = str(path)
            artifacts.append({key: item[key] for key in ("path", "sha256", "bytes", "role")})
        fixture.evidence["collections"]["fixture_sources"] = list(registry.values())
        fixture.save()
        fixture.plan = generate_plan(fixture.path, expand=True)
        scope = asset_scope(fixture.task, "product_entry", "copyright")
        query = next(row for row in fixture.plan["queries"]["asset_provenance"]
            if row["right_type"] == "copyright" and row["search_dimension"] == "provenance"
            and row.get("asset_scope_sha256") == scope["scope_sha256"])
        payload = deepcopy(self.payload)
        payload.update(asset_scope_sha256=scope["scope_sha256"], artifacts=artifacts,
            coverage_attestation={"inventory_complete": True, "asset_ids": scope["asset_ids"], "reviewed_asset_ids": scope["asset_ids"]})
        self.assertTrue(external_information_actions(fixture.task, payload, query, "product_entry", registry))
        def append_revision(value):
            index = len(fixture.evidence["source_runs"])
            run = {**{key: query[key] for key in ("query_id", "operation", "jurisdiction", "right_type", "requirement_ids")},
                "provider": "asset_provenance", "run_id": "R-public-" + str(index), "status": "success",
                "submission_state": "submitted", "plan_entry_sha256": sha256_json(query)}
            fixture.evidence["source_runs"].append(run)
            fixture.evidence["collections"].setdefault("asset_provenance", []).append({**run,
                "evidence_id": "EV-public-" + str(index), "source_run_id": run["run_id"], "payload": deepcopy(value)})
            atomic_write_json(fixture.path / "evidence.json", fixture.evidence)
        append_revision({**payload, "outstanding_actions": []})
        append_revision(payload)
        view = work_view_from_dir(fixture.path)
        rows = [row for row in view["entries"] if row.get("query_id") == query["query_id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["kind"], rows[0]["state"]), ("user_information", "awaiting_user"))
        self.assertEqual(rows[0]["question"], payload["outstanding_actions"][0]["question"])
        self.assertTrue(rows[0]["evidence_refs"])
        mixed = deepcopy(payload)
        mixed["outstanding_actions"].append({"kind": "agent_read", "purpose": "Read a still missing public source"})
        append_revision(mixed)
        rows = [row for row in work_view_from_dir(fixture.path)["entries"] if row.get("query_id") == query["query_id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["kind"], rows[0]["state"]), ("agent_investigation", "ready"))


if __name__ == "__main__":
    unittest.main()
