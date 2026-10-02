"""Offline image-fact metadata through generated API rows and real authorizers."""
from copy import deepcopy
import unittest

import common
from api_first_planning import make_row
from coverage_v3 import build_requirements
from product_delivery import validate_fact_query
from workflow_v24 import build_coverage_requirements_v24
import test_serper_entitlement as entitlement_fixture


class ProductFactApiAuthorizationTests(unittest.TestCase):
    def setUp(self):
        fixture = entitlement_fixture.ApiPlanAndExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.task = fixture.task
        self.task.update(retrieval_workflow_revision="api-first-v3",
            product_delivery_revision="image-fact-v1",
            signa_free_enhancement=common.signa_free_enhancement(True))
        self.task["coverage_requirements"] = build_requirements(self.task,
            build_coverage_requirements_v24(self.task["target_jurisdictions"],
                screening_revision=self.task.get("screening_revision"),
                specialty_workflow_revision=self.task.get("specialty_workflow_revision")))
        self.task["product_scope"] = {"facts": [{"fact_id": "claim", "version": 1,
            "source_path": "product.structure[0]", "nature": "page_claim", "verification": "claim_only"}]}

    def row_and_plan(self, provider):
        right = "trademark_word" if provider == "signa" else "patent"
        term = {"kind": "brand" if provider == "signa" else "structural_feature",
                "value": "FIXTURE", "language": "en", "derived_from": "product.structure[0]"}
        refs = [row["requirement_id"] for row in self.task["coverage_requirements"]
                if row["jurisdiction"] == "US" and row["right_type"] == right]
        row = make_row(self.task, provider, term, "US", right, refs)
        plan = deepcopy(self.task)
        plan["queries"] = {provider: [row]}
        return row, plan

    def authorize(self, provider, row, plan, task=None):
        task = task or self.task
        if provider.startswith("serper_"):
            return common.authorize_serper_free_plan_entry(task, plan, provider, row["operation"], row["query_id"])
        if provider == "signa":
            return common.authorize_signa_free_plan_entry(task, plan, row["query_id"])
        return common.authorize_serpapi_free_plan_entry(task, plan, row["operation"], row["query_id"])

    def test_generated_rows_with_fact_versions_reach_all_commercial_authorizers(self):
        for provider in ("serper_patents", "serper_web", "serper_images", "serpapi_google_patents", "signa"):
            with self.subTest(provider=provider):
                row, plan = self.row_and_plan(provider)
                self.assertEqual(row["product_fact_refs"][0]["fact_id"], "claim")
                self.assertEqual(self.authorize(provider, row, plan), row)
                self.assertIsNone(validate_fact_query(self.task, row))
                historical = deepcopy(self.task)
                historical.pop("product_delivery_revision")
                with self.assertRaisesRegex(ValueError, "PLAN_PARAMETERS_INVALID"):
                    self.authorize(provider, row, plan, task=historical)
                row["unexpected_field"] = True
                with self.assertRaisesRegex(ValueError, "PLAN_PARAMETERS_INVALID"):
                    self.authorize(provider, row, plan)

    def test_fact_version_changes_still_reject_stale_rows(self):
        row, unused = self.row_and_plan("serper_patents")
        self.task["product_scope"]["facts"][0]["version"] = 2
        self.assertEqual(validate_fact_query(self.task, row), "PRODUCT_FACT_VERSION_REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
