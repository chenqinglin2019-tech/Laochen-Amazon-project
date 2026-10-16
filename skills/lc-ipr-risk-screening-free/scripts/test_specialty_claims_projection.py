"""claims_projection: the recorded independent-claim comparison in the final-review claims-table shape."""
import unittest

import specialty_analysis as sa
from assessment_estimate import _validate_comparison, _validate_implementation_claims

SCOPE = {"candidate_id": "CAND-1", "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent"}
KNOWN = {"EV-PUB-1", "EV-IMG-1", "EV-IMG-2"}


def elements(spec, num, *, product_refs=("EV-IMG-1",)):
    return [{"element_id": name, "result": result, "claim_quote": "quote " + name,
             "original_location": "PDF page 7 claim %s" % num, "product_fact": "fact " + name,
             "reasoning": "why " + name, "claim_evidence_refs": ["EV-PUB-1"],
             "product_evidence_refs": list(product_refs) if result != "unknown" else []}
            for name, result in spec]


def task_with_events(units):
    """units: [(unit_id, implementation_id, claim_number, [(element_id, result), ...]), ...]"""
    task = {"task_id": "T-claims", "specialty_analysis_events": []}
    intake = sa._append(task, "intake", {**SCOPE, "reviewer": "r", "assessment_date": "2026-10-11"})
    inventory = sa._append(task, "inventory", {**SCOPE, "intake_event_id": intake["event_id"], "evidence_refs": ["EV-PUB-1"],
        "units": [{"unit_id": uid, "kind": "independent_claim", "implementation_id": impl,
                   "product_configuration": "配置 " + impl, "original_location": "PDF page 7 columns 5-6 claim %s" % num,
                   "necessary_elements": [name for name, _ in spec]} for uid, impl, num, spec in units]})
    for uid, impl, num, spec in units:
        sa._append(task, "comparison", {**SCOPE, "intake_event_id": intake["event_id"],
            "inventory_event_id": inventory["event_id"], "unit_id": uid, "disposition": "compared",
            "evidence_refs": ["EV-PUB-1", "EV-IMG-1"], "elements": elements(spec, num)})
    return task, intake, inventory


class ClaimsProjectionTests(unittest.TestCase):
    def test_results_and_conclusions_follow_the_contract(self):
        task, _, _ = task_with_events([
            ("C1-knob", "knob", 1, [("a", "corresponds"), ("b", "corresponds")]),
            ("C1-bare", "bare", 1, [("a", "corresponds"), ("b", "differs")]),
            ("C5-knob", "knob", 5, [("a", "corresponds"), ("c", "unknown")]),
        ])
        projection = sa.claims_projection(task, SCOPE)
        by_key = {(c["implementation_id"], c["claim_id"]): c for c in projection["claims"]}
        self.assertEqual(by_key[("knob", "1")]["conclusion"], "supports_risk")
        self.assertEqual(by_key[("bare", "1")]["conclusion"], "excludes_risk")
        self.assertEqual(by_key[("knob", "5")]["conclusion"], "unknown")
        self.assertEqual([e["result"] for e in by_key[("bare", "1")]["elements"]], ["supports_risk", "excludes_risk"])
        unknown = by_key[("knob", "5")]["elements"][1]
        self.assertEqual(unknown["result"], "unknown")
        self.assertEqual(unknown["product_evidence_refs"], ["EV-IMG-1"])     # fallback to the examined product material
        self.assertEqual(unknown["claim_element"], "c")
        self.assertEqual({c["claim_type"] for c in projection["claims"]}, {"independent"})
        self.assertEqual({i["implementation_id"] for i in projection["implementations"]}, {"knob", "bare"})
        for implementation in projection["implementations"]:
            self.assertEqual(implementation["product_evidence_refs"], ["EV-IMG-1"])
            self.assertTrue(implementation["title"] and implementation["description"])
        row = {"comparison": {"criteria": [], **projection}}
        _validate_comparison(row, KNOWN)
        _validate_implementation_claims(row)

    def test_latest_comparison_of_a_unit_wins_and_scope_is_isolated(self):
        task, intake, inventory = task_with_events([("C1-knob", "knob", 1, [("a", "corresponds")])])
        sa._append(task, "comparison", {**SCOPE, "intake_event_id": intake["event_id"],
            "inventory_event_id": inventory["event_id"], "unit_id": "C1-knob", "disposition": "compared",
            "evidence_refs": ["EV-PUB-1", "EV-IMG-2"], "elements": elements([("a", "differs")], 1, product_refs=("EV-IMG-2",))})
        projection = sa.claims_projection(task, SCOPE)
        self.assertEqual([c["conclusion"] for c in projection["claims"]], ["excludes_risk"])
        self.assertEqual(projection["implementations"][0]["product_evidence_refs"], ["EV-IMG-2"])
        self.assertEqual(sa.claims_projection(task, {**SCOPE, "candidate_id": "CAND-2"}), {"implementations": [], "claims": []})
        self.assertEqual(sa.claims_projection({"task_id": "T", "specialty_analysis_events": []}, SCOPE),
                         {"implementations": [], "claims": []})

    def test_claim_numbers_come_from_the_location_or_the_unit_id(self):
        self.assertEqual(sa._claim_number({"original_location": "PDF page 7 columns 5-6 claim 12", "unit_id": "C1-x"}), "12")
        self.assertEqual(sa._claim_number({"original_location": "page 7", "unit_id": "C7-knob"}), "7")
        self.assertIsNone(sa._claim_number({"original_location": "page 7", "unit_id": "knob"}))

    def test_units_without_a_compared_record_are_left_out(self):
        task, intake, inventory = task_with_events([("C1-knob", "knob", 1, [("a", "corresponds")])])
        inventory["units"].append({"unit_id": "C9-knob", "kind": "independent_claim", "implementation_id": "knob",
                                   "product_configuration": "配置", "original_location": "claim 9", "necessary_elements": ["z"]})
        # mutating a retained event breaks the chain: the projection then reports nothing rather than guessing
        self.assertEqual(sa.claims_projection(task, SCOPE), {"implementations": [], "claims": []})


if __name__ == "__main__":
    unittest.main()


class SelectedCandidateDraftTests(unittest.TestCase):
    def test_chief_drafts_carry_the_projected_table_and_leave_the_grade_open(self):
        import prepare_adjudication as pa
        task, _, _ = task_with_events([("C1-knob", "knob", 1, [("a", "corresponds"), ("b", "unknown")])])
        key = ("product_entry", "US", "patent", "CAND-1", "product")
        base = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent", "candidate_id": "CAND-1",
                "assessment_object": "product", "risk": "高", "assessment_status": "assessed",
                "evidence_refs": ["EV-PUB-1"], "comparison": {"criteria": []}}
        scope_row = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "copyright",
                     "assessment_object": "product", "risk": "低", "assessment_status": "assessed"}
        left = {key: dict(base), ("product_entry", "US", "copyright", None, "product"): scope_row}
        right = {key: {**base, "risk": "中"}, ("product_entry", "US", "copyright", None, "product"): dict(scope_row)}
        refs = {"first": "a" * 64, "second": "b" * 64}
        drafts, notes = pa._selected_candidate_drafts(task, left, right, refs)
        self.assertEqual(len(drafts), 1)
        draft = drafts[0]
        self.assertIsNone(draft["risk"])
        self.assertEqual(draft["assessment_status"], "pending")
        self.assertEqual(draft["adjudication_reasoning"], "")
        self.assertEqual(draft["review_refs"], refs)
        self.assertEqual([c["conclusion"] for c in draft["comparison"]["claims"]], ["unknown"])
        self.assertEqual(draft["comparison"]["implementations"][0]["implementation_id"], "knob")
        self.assertEqual(draft["evidence_refs"], ["EV-PUB-1", "EV-IMG-1"])
        self.assertNotIn("chief_must_fill", draft)
        self.assertEqual(notes[0]["draft"], "claims_projection")
        self.assertIn("risk", notes[0]["chief_must_fill"])
        self.assertEqual(notes[0]["claims"][0]["elements"], {"supports_risk": 1, "excludes_risk": 0, "unknown": 1})
        # a reviewer who supplied the claims table, or a scope without a recorded comparison, is not drafted
        left[key] = {**base, "comparison": {"criteria": [], "claims": [{"claim_id": "1"}]}}
        self.assertEqual(pa._selected_candidate_drafts(task, left, right, refs), ([], []))
        other = {("product_entry", "US", "patent", "CAND-9", "product"): {**base, "candidate_id": "CAND-9"}}
        drafts, notes = pa._selected_candidate_drafts(task, other, {}, refs)
        self.assertEqual((drafts, [n["draft"] for n in notes]), ([], ["no_recorded_claim_comparison"]))
