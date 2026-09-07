"""Synthetic regression fixtures; never provider execution or legal evidence."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

import decision_workflow as workflow
from common import sha256_json
from record_asset_provenance import inventory_identity_sha256, asset_scope
import test_decision_workflow as fixtures
import test_historical_evidence as historical_fixtures


class CorrectedIdentityTests(TestCase):
    def setUp(self):
        self.f = fixtures.DecisionWorkflowTests()
        self.f.setUp()
        self.task = self.f.task
        self.task["workflow_correction_revision"] = workflow.CORRECTION_REVISION
        self.supplement = {"evidence": []}

    def digest(self, right="patent", sid="product_entry"):
        return workflow.product_identity_sha256(self.task, scenario_id=sid, right_type=right)

    def document(self, identifier="PDF", number="US11111111B2", digest="a" * 64):
        return {"evidence_id": identifier, "publication_number": number, "jurisdiction": "US",
            "right_type": "patent", "kind": "patent_document", "authority_scope": "published_document_only",
            "path": "/synthetic/" + identifier + ".pdf", "sha256": digest, "bytes": 100}

    def page(self, number=2, digest="b" * 64):
        return {"evidence_id": "PAGE" + str(number), "jurisdiction": "US", "right_type": "patent",
            "kind": "patent_document", "authority_scope": "published_document_only", "path": "/synthetic/page.png",
            "sha256": digest, "bytes": 100, "source_document": "/synthetic/PDF.pdf",
            "source_document_sha256": "a" * 64, "page_number": number, "visual_role": "patent_drawings"}

    def annotation(self):
        row = self.f.annotation()
        row["candidate_content_sha256"] = workflow.candidate_content_sha256(self.f.candidate,
            self.f.evidence, self.supplement, task=self.task)
        self.f.ledger["annotations"].append(row)

    def effective(self):
        return workflow.effective_decision(self.task, self.f.ledger, "patents", self.f.candidate,
            "product_entry", evidence=self.f.evidence, supplement=self.supplement)

    def test_brand_and_structure_have_separate_decision_scope(self):
        patent, mark = self.digest(), self.digest("trademark_word", "brand_reuse")
        self.task["product"]["brand"] = "NEW MARK"
        self.assertEqual(self.digest(), patent)
        self.assertNotEqual(self.digest("trademark_word", "brand_reuse"), mark)
        mark = self.digest("trademark_word", "brand_reuse")
        self.task["product"]["structure"] = ["changed hook geometry"]
        self.assertNotEqual(self.digest(), patent)
        self.assertEqual(self.digest("trademark_word", "brand_reuse"), mark)

    def test_assets_explanation_and_acquisition_metadata_do_not_reopen(self):
        product = self.task["product"]
        product["assets"] = [{"asset_id": "shape", "usage": "product_configuration", "right_types": ["copyright"],
            "scenario_ids": ["product_entry"], "scope_reasoning": "Initial explanation", "path": "/old/a.png",
            "sha256": "a" * 64, "evidence_refs": ["E1"]}]
        before = self.digest("copyright")
        product["assets"][0].update(scope_reasoning="Clearer explanation", path="/new/a.png", checked_at="later")
        self.assertEqual(self.digest("copyright"), before)
        product["assets"][0]["usage"] = "intended_material"
        self.assertNotEqual(self.digest("copyright"), before)

    def test_observed_facts_use_exact_retail_statistics_exclusion(self):
        product = self.task["product"]
        product["specifications"] = {"Best Sellers Rank": "1", "Customer Reviews": "10", "Capacity": "6 quart"}
        before = workflow.observed_product_sha256(product)
        product["specifications"]["Best Sellers Rank"] = "500"
        product["specifications"]["Customer Reviews"] = "100"
        self.assertEqual(workflow.observed_product_sha256(product), before)
        product["specifications"]["Capacity"] = "8 quart"
        self.assertNotEqual(workflow.observed_product_sha256(product), before)

    def test_new_exact_unreferenced_document_reopens_only_matching_candidate(self):
        self.annotation()
        self.assertEqual(self.effective()["decision"], "selected")
        self.supplement["evidence"].append(self.document(number="US11111111A1"))
        self.assertEqual(self.effective()["decision"], "selected")
        self.supplement["evidence"].append(self.document(identifier="GRANT"))
        self.assertEqual(self.effective()["decision"], "unreviewed")

    def test_raw_record_full_publication_precedes_shared_application(self):
        candidate = {**self.f.candidate, "application_number": "US16123456"}
        published = {"publication_number": "US11111111A1", "application_number": "US16123456", "claims": "published claims"}
        grant = {"publication_number": "US11111111B2", "application_number": "US16123456", "claims": "granted claims"}
        entry = {"payload": {"records": [published, grant]}}
        corrected = workflow._evidence_content(entry, candidate, task=self.task)
        self.assertEqual(corrected["candidate_records"], [grant])
        self.assertEqual(corrected["identity_scope"], "exact_publication")
        before = sha256_json(corrected)
        published["claims"] = "changed publication claims"
        self.assertEqual(sha256_json(workflow._evidence_content(entry, candidate, task=self.task)), before)
        grant["claims"] = "changed granted claims"
        self.assertNotEqual(sha256_json(workflow._evidence_content(entry, candidate, task=self.task)), before)
        application_only = {"application_number": "US16123456", "status": "pending"}
        entry["payload"]["records"] = [published, application_only]
        corrected = workflow._evidence_content(entry, candidate, task=self.task)
        self.assertEqual(corrected["candidate_records"], [application_only])
        self.assertEqual(corrected["identity_scope"], "record_identity_only_not_grant_document")
        self.assertEqual(len(workflow._evidence_content(entry, candidate)["candidate_records"]), 2)

    def test_new_page_reopens_but_duplicate_render_does_not(self):
        self.supplement["evidence"] = [self.document(), self.page()]
        self.annotation()
        same_page = deepcopy(self.page(digest="c" * 64))
        same_page.update(evidence_id="OTHER-RENDER", path="/different/render.png", checked_at="later")
        self.supplement["evidence"].append(same_page)
        self.assertEqual(self.effective()["decision"], "selected")
        self.supplement["evidence"].append(self.page(3))
        self.assertEqual(self.effective()["decision"], "unreviewed")

    def test_wrong_parent_page_and_explicit_wrong_number_cannot_bind(self):
        self.supplement["evidence"] = [self.document(), self.page()]
        self.assertEqual(len(workflow.candidate_document_entries(self.f.candidate, self.f.evidence, self.supplement)), 2)
        for change in ({"source_document_sha256": "f" * 64}, {"publication_number": "US11111111A1"},
                       {"page_number": 0}, {"source_document": "/synthetic/other.pdf"}):
            self.supplement["evidence"][1] = {**self.page(), **change}
            self.assertEqual(len(workflow.candidate_document_entries(self.f.candidate, self.f.evidence, self.supplement)), 1)

    def test_old_revision_preserves_global_identity_and_document_digest(self):
        self.task.pop("workflow_correction_revision")
        before = self.digest()
        self.task["product"]["brand"] = "NEW"
        self.assertNotEqual(self.digest(), before)
        before = workflow.candidate_content_sha256(self.f.candidate, self.f.evidence, self.supplement, task=self.task)
        self.supplement["evidence"].append(self.document())
        self.assertEqual(workflow.candidate_content_sha256(self.f.candidate, self.f.evidence, self.supplement, task=self.task), before)

    def test_inventory_scope_is_stable_when_only_review_explanation_changes(self):
        self.task["specialty_workflow_revision"] = "asset-scope-v1"
        self.task["product"]["assets"] = []
        review = {"status": "reviewed", "reviewer": "agent", "reasoning": "actual empty inventory", "evidence_refs": ["E1"]}
        review["inventory_identity_sha256"] = inventory_identity_sha256(self.task, "copyright")
        self.task["product"]["asset_scope_review"] = review
        before = asset_scope(self.task, "product_entry", "copyright")
        review.update(reasoning="clearer actual inventory explanation", checked_at="later")
        after = asset_scope(self.task, "product_entry", "copyright")
        self.assertTrue(after["inventory_reviewed"])
        self.assertEqual(before["scope_sha256"], after["scope_sha256"])

    def test_inventory_review_digest_only_reopens_affected_right(self):
        self.task["product"]["assets"] = [{"asset_id": "work", "right_types": ["copyright"],
            "scenario_ids": ["product_entry"], "usage": "intended_material", "sha256": "a" * 64}]
        copyright_before = inventory_identity_sha256(self.task, "copyright")
        dress_before = inventory_identity_sha256(self.task, "trade_dress")
        self.task["product"]["assets"][0]["sha256"] = "b" * 64
        self.assertNotEqual(inventory_identity_sha256(self.task, "copyright"), copyright_before)
        self.assertEqual(inventory_identity_sha256(self.task, "trade_dress"), dress_before)

    def test_new_needs_info_has_explicit_read_scope_and_agent_read(self):
        action = {"action_id": "READ", "kind": "agent_read", "purpose": "Read necessary drawing",
            "evidence_refs": ["E1"], "max_attempts": 1, "required_facts": ["representative_figures"],
            "reading_scope": {"level": "representative_figures", "page_numbers": [2]}}
        self.assertEqual(workflow.next_action_errors([action], task=self.task), [])
        action["reading_scope"].pop("page_numbers")
        self.assertIn("NEXT_ACTION_PAGE_NUMBERS_REQUIRED", workflow.next_action_errors([action], task=self.task))
        action["reading_scope"]["level"] = []
        self.assertIn("NEXT_ACTION_READING_SCOPE_INVALID", workflow.next_action_errors([action], task=self.task))

    def test_batch_memo_reuses_only_same_inputs_and_rechecks_changed_generation(self):
        self.annotation()
        state, plan = {}, {}
        args = (self.task, self.f.evidence, self.f.candidates, plan, self.f.ledger, self.supplement)
        with patch.object(workflow, "_effective_decision", wraps=workflow._effective_decision) as calculate:
            with workflow.decision_snapshot(*args, memo_state=state):
                self.assertEqual(self.effective()["decision"], "selected")
            with workflow.decision_snapshot(*args, memo_state=state):
                self.assertEqual(self.effective()["decision"], "selected")
            self.assertEqual(calculate.call_count, 1)
            self.task["product"]["structure"] = ["changed physical structure"]
            with workflow.decision_snapshot(*args, memo_state=state):
                self.assertEqual(self.effective()["decision"], "unreviewed")
            self.assertEqual(calculate.call_count, 2)
        with self.assertRaisesRegex(ValueError, "INPUT_MUTATED"):
            with workflow.decision_snapshot(*args, memo_state=state):
                self.task["product"]["structure"] = ["changed during decision"]
        self.assertEqual(state, {})

    def test_snapshot_indexes_records_and_summary_once_and_does_not_leak_mutation(self):
        self.annotation()
        with workflow.decision_snapshot(self.task, self.f.evidence, self.f.candidates, {}, self.f.ledger, self.supplement):
            with patch.object(workflow, "_triage_summary", wraps=workflow._triage_summary) as calculate:
                first = workflow.triage_summary(self.task, self.f.candidates, self.f.ledger, evidence=self.f.evidence, supplement=self.supplement)
                first["records"][0]["decision"] = "not_selected"
                second = workflow.triage_summary(self.task, self.f.candidates, self.f.ledger, evidence=self.f.evidence, supplement=self.supplement)
                self.assertEqual(second["records"][0]["decision"], "selected")
                self.assertEqual(calculate.call_count, 1)
        records = [{"publication_number": "US" + str(11111000 + i) + "B2"} for i in range(100)]
        entry = {"payload": {"records": records}}
        with workflow.decision_snapshot(self.task, self.f.evidence, self.f.candidates, {}, self.f.ledger, self.supplement):
            with patch.object(workflow, "_identity_tokens", wraps=workflow._identity_tokens) as identities:
                for record in records:
                    workflow._evidence_content(entry, record)
                self.assertLessEqual(identities.call_count, 200)

    def test_corrected_historical_prefilter_keeps_source_hash_checks(self):
        f = historical_fixtures.HistoricalEvidenceTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.task["workflow_correction_revision"] = workflow.CORRECTION_REVISION
        f.item["reuse_binding"]["product_identity_sha256"] = workflow.product_identity_sha256(
            f.task, scenario_id="product_entry", right_type="patent")
        state = {}
        with workflow.decision_snapshot(f.task, {}, f.candidates, {}, {}, f.supplement, memo_state=state):
            self.assertIsNotNone(f.reuse())
            (f.old / "response.json").write_bytes(b"tampered synthetic source")
            self.assertIsNone(f.reuse())
