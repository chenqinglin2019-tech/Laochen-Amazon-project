"""Full independent judgments are preserved; compact inputs cannot carry grades."""
import unittest
from record_independent_review import FULL_ASSESSMENT_FIELDS, normalize_review_row


class IndependentReviewNormalizationTests(unittest.TestCase):
    def test_full_pending_review_is_preserved_byte_for_byte_as_a_value(self):
        row = {key: None for key in FULL_ASSESSMENT_FIELDS}
        row.update({"scenario_id": "S1", "jurisdiction": "US", "right_type": "patent",
            "module_id": "utility_patent", "title": "US patent", "scope": "C1",
            "risk": None, "assessment_status": "pending", "reasoning": "No confirmed mapping.",
            "confidence_reasoning": "Unverified claim scope.", "pending_reasoning": "Need claim chart.",
            "evidence_confidence": "低", "evidence_refs": [], "supporting_evidence": [],
            "counter_evidence": [], "no_supporting_evidence_reasoning": "No positive support.",
            "no_counter_evidence_reasoning": "Missing evidence is not counterevidence.",
            "assumptions": [], "raise_if": [], "lower_if": [], "human_checks": [],
            "right_state": "unknown", "confidence_basis": {}, "custom_judgment": "preserve me"})
        self.assertEqual(normalize_review_row(row, {}), row)

    def test_compact_risk_judgment_is_rejected_instead_of_erased(self):
        with self.assertRaisesRegex(ValueError, "CANNOT_CARRY_A_RISK_JUDGMENT"):
            normalize_review_row({"jurisdiction": "US", "right_type": "patent", "risk": "高",
                                  "reasoning": "Claim may read on the product."}, {})


if __name__ == "__main__":
    unittest.main()
