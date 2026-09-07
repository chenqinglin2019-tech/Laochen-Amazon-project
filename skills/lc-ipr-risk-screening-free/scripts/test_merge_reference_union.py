"""Same-record provenance survives both historical/fresh arrival orders."""
from copy import deepcopy
import json
from itertools import permutations
import unittest

from merge_candidates import (apply_candidate_contract, merge, coalesce_candidate_ids,
                              verification_index, apply_verifications, hydrate_tsdr_candidate_facts)
from decision_workflow import REVISION, candidate_content_sha256


class MergeReferenceUnionTests(unittest.TestCase):
    def entries(self, kind):
        identity = ({"publication_number": "US11111111B2", "jurisdiction": "US", "right_type": "patent"}
                    if kind == "patent" else {"serial_number": "11111111", "jurisdiction": "US", "right_type": "trademark_word"})
        fresh = {"evidence_id": "EV-FRESH", "provider": "uspto_patent_browser", "payload": {"candidates": [
            {**identity, "evidence_refs": ["EV-FRESH-RAW"], "verification_refs": ["EV-FRESH-DETAIL"],
             "official_verification": {"status": "not_checked", "identity_match": None}}]}}
        retained = {"evidence_id": "EV-IMPORT", "provider": "retained_candidate_facts", "payload": {"candidates": [
            {**identity, "evidence_refs": ["EV-OLD", "EV-REUSE"], "verification_refs": ["EV-OLD-DETAIL"],
             "authority_scope": "retained_candidate_facts_only"}]}}
        return fresh, retained

    def test_fresh_then_historical_and_reverse_preserve_all_provenance(self):
        for kind in ("patent", "trademark"):
            fresh, retained = self.entries(kind)
            for entries in ([fresh, retained], [retained, fresh]):
                with self.subTest(kind=kind, first=entries[0]["provider"]):
                    before = deepcopy(entries)
                    rows = merge(kind, entries, {})
                    apply_candidate_contract(kind, rows)
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(set(rows[0]["evidence_refs"]), {"EV-FRESH-RAW", "EV-OLD", "EV-REUSE", "EV-FRESH", "EV-IMPORT"})
                    self.assertEqual(set(rows[0]["verification_refs"]), {"EV-FRESH-DETAIL", "EV-OLD-DETAIL"})
                    self.assertNotIn("evidence_refs", rows[0]["conflicts"])
                    self.assertNotIn("verification_refs", rows[0]["conflicts"])
                    self.assertEqual(rows[0]["official_verification"]["status"], "not_checked")
                    self.assertIsNone(rows[0]["official_verification"]["identity_match"])
                    self.assertFalse(rows[0]["material"])
                    self.assertEqual(entries, before)

    def test_repeated_merge_is_stable_and_refs_do_not_create_verification(self):
        entries = list(self.entries("patent"))
        first = merge("patent", entries, {})
        apply_candidate_contract("patent", first)
        second = merge("patent", entries, {})
        apply_candidate_contract("patent", second)
        self.assertEqual(first, second)
        self.assertNotEqual(first[0]["official_verification"]["status"], "verified")

    def test_same_id_aliases_merge_conflict_maps_without_self_reference(self):
        initial = [{"candidate_id": "C1", "normalization_key": "uspto:mark:11111111", "title": "First",
                    "conflicts": {"owner": ["Old", "New"]}},
                   {"candidate_id": "C1", "normalization_key": "us:mark:11111111", "title": "Second",
                    "conflicts": {"owner": ["New", "Other"], "goods": ["Kitchen", "Household"]}}]
        for sequence in permutations(initial):
            with self.subTest(first=sequence[0]["normalization_key"]):
                rows = deepcopy(list(sequence))
                coalesce_candidate_ids(rows)
                self.assertEqual(len(rows), 1)
                json.dumps(rows, check_circular=True)
                self.assertEqual(set(rows[0]["conflicts"]["owner"]), {"Old", "New", "Other"})
                self.assertEqual(set(rows[0]["conflicts"]["goods"]), {"Kitchen", "Household"})
                self.assertEqual(set(rows[0]["conflicts"]["title"]), {"First", "Second"})
                self.assertNotIn("conflicts", rows[0]["conflicts"])

    def test_multiple_official_verifications_and_lineage_aliases_are_order_independent(self):
        identity = {"candidate_id": "C1", "serial_number": "11111111", "right_type": "trademark_word", "jurisdiction": "US"}
        observations = [
            {"evidence_id": "EV-OLD", "provider": "retained_candidate_facts", "payload": {"candidates": [
                {**identity, "office": "USPTO", "title": "Synthetic mark", "evidence_refs": ["EV-REUSE-OLD"]}]}},
            {"evidence_id": "EV-LINEAGE", "provider": "retained_candidate_facts", "payload": {"candidates": [
                {**identity, "title": "Synthetic mark", "evidence_refs": ["EV-REUSE-NEW"]}]}},
        ]
        official = [{"evidence_id": "EV-VERIFY-" + str(index), "provider": "uspto_tsdr", "payload": {**identity,
            "official_verification": verification}} for index, verification in enumerate([
                {"status": "not_checked", "identity_match": None},
                {"status": "verified", "identity_match": True, "legal_status": "Registered", "checked_at": "2026-01-01T00:00:00Z"},
                {"status": "verified", "identity_match": True, "legal_status": "Cancelled", "checked_at": "2026-01-02T00:00:00Z"}])]
        original = deepcopy((observations, official))
        for incoming in permutations(observations):
            for details in permutations(official):
                rows = merge("trademark", deepcopy(list(incoming)), {})
                apply_candidate_contract("trademark", rows)
                index = verification_index(deepcopy(list(details)))
                apply_verifications("trademark", rows, index)
                apply_verifications("trademark", rows, index)  # The production chain applies details twice.
                apply_candidate_contract("trademark", rows)
                coalesce_candidate_ids(rows)
                json.dumps(rows, check_circular=True)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["official_verification"]["legal_status"], "Cancelled")
                self.assertEqual(set(rows[0]["verification_refs"]), {"EV-VERIFY-0", "EV-VERIFY-1", "EV-VERIFY-2"})
                self.assertTrue({"EV-REUSE-OLD", "EV-REUSE-NEW"} <= set(rows[0]["evidence_refs"]))
                self.assertNotIn("conflicts", rows[0]["conflicts"])
                self.assertFalse(rows[0]["material"])
        self.assertEqual((observations, official), original)

    def test_invalid_conflict_maps_fail_explicitly_instead_of_flattening_values(self):
        for conflicts in (None, [], {"owner": "not-an-alternatives-list"}):
            with self.subTest(conflicts=conflicts):
                rows = [{"candidate_id": "C1", "normalization_key": "first", "conflicts": {}},
                        {"candidate_id": "C1", "normalization_key": "second", "conflicts": conflicts}]
                with self.assertRaisesRegex(ValueError, "CANDIDATE_CONFLICTS_INVALID"):
                    coalesce_candidate_ids(rows)


class TsdrFactualHydrationTests(unittest.TestCase):
    def setUp(self):
        self.task = {"decision_workflow_revision": REVISION}
        self.candidate = {"candidate_id": "C1", "serial_number": "11111111", "jurisdiction": "US",
                          "right_type": "trademark_word", "registration_number": "",
                          "goods_services": ["Elastomer..."], "goods_services_truncated": True,
                          "title": "Original recall title", "material": False,
                          "official_verification": {"status": "not_checked"},
                          "evidence_refs": ["EV-RECALL"], "conflicts": {"owner": ["A", "B"]}}

    def detail(self, suffix, *, stamp="2026-01-01T00:00:00Z", goods=None, truncated=False):
        run = {"run_id": "RUN-" + suffix, "query_id": "Q-" + suffix, "provider": "uspto_tsdr",
               "status": "success", "operation": "candidate_verification", "jurisdiction": "US",
               "right_type": "trademark_word", "requirement_ids": ["REQ1"], "plan_entry_sha256": suffix * 64}
        row = {"candidate_id": "C1", "serial_number": "11111111", "jurisdiction": "US",
               "right_type": "trademark_word", "registration_number": "7777777",
               "goods_services": goods if goods is not None else ["Elastomer tie-down straps"],
               "goods_services_truncated": truncated, "title": "Do not replace recall title", "material": True,
               "official_verification": {"status": "verified", "identity_match": True,
                                         "checked_at": stamp, "legal_status": "Registered"}}
        entry = {**{key: value for key, value in run.items() if key not in {"run_id", "status"}},
                 "source_run_id": run["run_id"], "evidence_id": "EV-" + suffix, "payload": row}
        return entry, run

    def test_full_record_facts_preserve_schema_conflicts_refs_and_reopen_content_not_selection(self):
        for goods in (["Elastomer tie-down straps"], "Elastomer tie-down straps"):
            with self.subTest(schema=type(goods).__name__):
                entry, run = self.detail("a", goods=goods)
                rows = [deepcopy(self.candidate)]
                original = deepcopy((entry, run))
                old_hash = candidate_content_sha256(rows[0])
                hydrate_tsdr_candidate_facts(self.task, rows, [entry], {run["run_id"]: run})
                item = rows[0]
                self.assertEqual(item["registration_number"], "7777777")
                self.assertEqual(item["goods_services"], goods)
                self.assertIs(item["goods_services_truncated"], False)
                self.assertIn(["Elastomer..."], item["conflicts"]["goods_services"])
                self.assertEqual(item["conflicts"]["owner"], ["A", "B"])
                self.assertEqual(set(item["evidence_refs"]), {"EV-RECALL", "EV-a"})
                self.assertEqual(item["verification_refs"], ["EV-a"])
                self.assertEqual(item["title"], self.candidate["title"])
                self.assertEqual(item["official_verification"], {"status": "not_checked"})
                self.assertFalse(item["material"])
                self.assertNotEqual(old_hash, candidate_content_sha256(item))
                self.assertEqual(original, (entry, run))

    def test_newer_valid_details_win_in_both_orders_and_repeated_hydration_is_stable(self):
        older, old_run = self.detail("a", goods="Older goods", truncated=None)
        newer, new_run = self.detail("b", stamp="2026-01-02T00:00:00Z", goods=["Complete newer goods"])
        newer["payload"]["registration_number"] = "8888888"
        failed, failed_run = self.detail("c", stamp="2026-01-03T00:00:00Z", goods="Do not replace verified goods")
        failed_run["status"] = "failed"
        runs = {run["run_id"]: run for run in (old_run, new_run, failed_run)}
        outputs = []
        for entries in permutations((older, newer, failed)):
            rows = [deepcopy(self.candidate)]
            hydrate_tsdr_candidate_facts(self.task, rows, list(entries), runs)
            before = deepcopy(rows)
            hydrate_tsdr_candidate_facts(self.task, rows, list(entries), runs)
            self.assertEqual(rows, before)
            self.assertEqual(rows[0]["goods_services"], ["Complete newer goods"])
            self.assertEqual(rows[0]["registration_number"], "8888888")
            self.assertNotIn("EV-c", rows[0]["evidence_refs"])
            json.dumps(rows, check_circular=True)
            outputs.append(rows)
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def test_failed_identity_false_or_wrong_scope_cannot_hydrate_good_facts(self):
        for target, key, value in (("run", "status", "failed"), ("run", "authoritative_for_final_rating", False),
                                   ("verification", "identity_match", False), ("verification", "status", "failed"),
                                   ("row", "candidate_id", "C2"), ("row", "serial_number", "22222222"),
                                   ("row", "jurisdiction", "GB"), ("row", "right_type", "trademark_figurative"),
                                   ("entry", "plan_entry_sha256", "wrong"), ("entry", "provider", "retained_candidate_facts")):
            with self.subTest(target=target, key=key):
                entry, run = self.detail("a")
                subjects = {"entry": entry, "run": run, "row": entry["payload"],
                            "verification": entry["payload"]["official_verification"]}
                subjects[target][key] = value
                rows = [deepcopy(self.candidate)]
                hydrate_tsdr_candidate_facts(self.task, rows, [entry], {run["run_id"]: run})
                self.assertEqual(rows, [self.candidate])

    def test_empty_and_malformed_facts_cannot_erase_and_unknown_truncation_is_explicit(self):
        for goods in (None, "", [], [""], [1]):
            with self.subTest(goods=goods):
                entry, run = self.detail("a")
                entry["payload"].update(registration_number="", goods_services=goods)
                rows = [deepcopy(self.candidate)]
                hydrate_tsdr_candidate_facts(self.task, rows, [entry], {run["run_id"]: run})
                self.assertEqual(rows, [self.candidate])
        entry, run = self.detail("a")
        entry["payload"].pop("goods_services_truncated")
        rows = [deepcopy(self.candidate)]
        hydrate_tsdr_candidate_facts(self.task, rows, [entry], {run["run_id"]: run})
        self.assertIsNone(rows[0]["goods_services_truncated"])

    def test_old_task_semantics_are_unchanged(self):
        entry, run = self.detail("a")
        rows = [deepcopy(self.candidate)]
        hydrate_tsdr_candidate_facts({"schema_version": "2.4-free"}, rows, [entry], {run["run_id"]: run})
        self.assertEqual(rows, [self.candidate])


if __name__ == "__main__":
    unittest.main()
