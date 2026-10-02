"""04B exact identity, provisional leads, and sourced relations."""
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from candidate_identity import REVISION, relation_view
from candidate_identity_corrections import (record_correction, load_ledger,
    projection_policy, apply_reviewed_fields, correction_view)
from common import atomic_write_json, load_json
from merge_candidates import apply_candidate_contract, merge, main as merge_main


class CandidateIdentityTests(unittest.TestCase):
    def entry(self, evidence_id, kind, *cards, jurisdiction="US", right_type="patent"):
        return {"evidence_id": evidence_id, "source_run_id": "RUN-" + evidence_id,
            "provider": "fixture", "jurisdiction": jurisdiction, "right_type": right_type,
            "collected_at": "2026-09-24T00:00:00Z", "payload": {"candidates": list(cards)}}

    def merged(self, kind, entries):
        rows = merge(kind, entries, {}, identity_revision=REVISION)
        apply_candidate_contract(kind, rows)
        return rows

    def test_incomplete_patent_identity_survives_without_inheriting_query_type(self):
        rows = self.merged("patent", [self.entry("EV-1", "patent",
            {"title": "Same title", "publication_number": "US/123"},
            {"title": "Same title", "publication_number": "US/123"})])
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["candidate_id"], rows[1]["candidate_id"])
        self.assertTrue(all(row["identity_status"] == "identity_pending" for row in rows))
        self.assertTrue(all(row["right_type"] == "unknown" for row in rows))
        self.assertTrue(all(row["module"] == "identity_pending" for row in rows))
        self.assertEqual(rows[0]["original_identifiers"]["publication_number"]["raw"], "US/123")

    def test_weak_trademark_and_copyright_keys_do_not_merge(self):
        trademarks = self.merged("trademark", [self.entry("EV-T", "trademark",
            {"mark_text": "ACME"}, {"mark_text": "ACME"}, right_type="trademark_word")])
        copyright_rows = self.merged("copyright", [self.entry("EV-C", "copyright",
            {"title": "Same", "owner": "Alice"}, {"title": "Same", "owner": "Alice"}, right_type="copyright")])
        self.assertEqual(len(trademarks), 2)
        self.assertEqual(len(copyright_rows), 2)

    def test_exact_document_same_record_merges_but_a1_b2_stay_distinct(self):
        rows = self.merged("patent", [self.entry("EV-1", "patent",
            {"publication_number": "US11111111A1", "application_number": "US/12"},
            {"publication_number": "US11111111B2", "application_number": "US/12"}),
            self.entry("EV-2", "patent", {"publication_number": "US 11111111 A1",
                 "application_number": "US/12"})])
        self.assertEqual(len(rows), 2)
        first = next(row for row in rows if row["publication_number"].endswith("A1"))
        self.assertEqual(len(first["sources"]), 2)
        relations = relation_view({"patents": rows})
        self.assertEqual(len(relations["relations"]), 1)
        self.assertEqual(relations["relations"][0]["relation"], "same_application")

    def test_source_candidate_id_cannot_override_canonical_identity(self):
        rows = self.merged("patent", [self.entry("EV-1", "patent",
            {"publication_number": "US11111111B2", "candidate_id": "SOURCE-ARBITRARY"}),
            self.entry("EV-2", "patent", {"publication_number": "US11111111B2"})])
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["candidate_id"], "SOURCE-ARBITRARY")
        self.assertEqual(len(rows[0]["sources"]), 2)

    def test_same_title_different_documents_are_only_suspected_duplicates(self):
        rows = self.merged("patent", [self.entry("EV-1", "patent",
            {"publication_number": "US11111111B2", "title": "Shared title"}),
            self.entry("EV-2", "patent",
            {"publication_number": "US22222222B2", "title": "Shared title"})])
        relations = relation_view({"patents": rows})["relations"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["relation"], "suspected_duplicate")
        self.assertEqual(relations[0]["status"], "review_required")
        self.assertEqual(relations[0]["evidence_refs"], ["EV-1", "EV-2"])
        self.assertFalse(relations[0]["transfers_status_or_risk"])

    def test_duplicate_discovery_wrapper_preserves_decision_content(self):
        from decision_workflow import candidate_content_sha256
        original = self.entry("EV-A", "patent", {"publication_number": "US11111111B2",
            "title": "Same record", "url": "https://example.test/first"})
        duplicate = self.entry("EV-B", "patent", {"publication_number": "US11111111B2",
            "title": "Same record", "url": "https://example.test/second"})
        def digest(entries):
            rows = self.merged("patent", entries)
            return rows[0], candidate_content_sha256(rows[0],
                {"collections": {"patents": entries}}, task={"candidate_identity_revision": REVISION})
        before, first = digest([original])
        after, second = digest([original, duplicate])
        self.assertEqual(first, second)
        self.assertEqual(len(after["sources"]), 2)
        self.assertEqual(after["duplicate_evidence_refs"], ["EV-B"])
        self.assertNotIn("url", after["conflicts"])

    def test_family_list_is_a_lead_with_own_source_not_an_inherited_candidate(self):
        rows = self.merged("patent", [self.entry("EV-F", "patent",
            {"publication_number": "US11111111B2", "family_id": "F-1",
             "family_members": ["GB2222222A1"], "legal_status": "active"})])
        self.assertEqual(len(rows), 1)
        view = relation_view({"patents": rows})
        self.assertEqual(len(view["member_leads"]), 1)
        lead = view["member_leads"][0]
        self.assertEqual(lead["publication_number"], "GB2222222A1")
        self.assertEqual(lead["source_refs"], ["EV-F"])
        self.assertFalse(lead["full_record_acquired"])
        self.assertEqual(lead["legal_status"], "unknown")

    def test_cross_country_family_and_territory_do_not_merge_or_transfer_status(self):
        rows = self.merged("patent", [self.entry("EV-US", "patent",
            {"publication_number": "US11111111B2", "family_id": "F-1",
             "territorial_effects": ["GB"], "legal_status": "active"}),
            self.entry("EV-GB", "patent", {"publication_number": "GB2222222A1",
             "family_id": "F-1", "legal_status": "expired"}, jurisdiction="GB")])
        view = relation_view({"patents": rows})
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["legal_status"] for row in rows}, {"active", "expired"})
        self.assertEqual(view["relations"][0]["relation"], "same_family")
        self.assertFalse(view["relations"][0]["transfers_status_or_risk"])
        self.assertEqual(view["territorial_claims"][0]["status"], "source_claim_unverified")
        self.assertEqual(view["territorial_claims"][0]["evidence_refs"], ["EV-US"])

    def correction_fixture(self, entries, kind="patent"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        task = {"task_id": "TASK-04B", "candidate_identity_revision": REVISION,
                "state": "collecting"}
        rows = self.merged(kind, entries)
        collection = {"patent": "patents", "trademark": "trademarks",
                      "copyright": "copyright_assets"}[kind]
        current = {collection: rows, "identity_correction_head": ""}
        atomic_write_json(path / "task.json", task)
        atomic_write_json(path / "evidence.json", {"collections": {collection: entries}})
        atomic_write_json(path / "normalized-candidates.json", current)
        return path, rows, current

    def request(self, kind, ids, refs, **extra):
        return {"kind": kind, "candidate_ids": ids, "evidence_refs": refs,
            "reviewer": "agent", "reason": "Retained source rows identify the same object",
            "quote": "Specific object identity appears in retained source", **extra}

    def test_reviewed_merge_keeps_old_ids_and_does_not_merge_new_weak_match(self):
        entries = [self.entry("EV-1", "patent", {"title": "Same title"}),
                   self.entry("EV-2", "patent", {"title": "Same title"})]
        path, rows, _ = self.correction_fixture(entries)
        old_ids = [row["candidate_id"] for row in rows]
        event = record_correction(path, self.request("merge", old_ids, ["EV-1", "EV-2"]))
        self.assertEqual(record_correction(path, self.request("merge", old_ids, ["EV-1", "EV-2"],)), event)
        assignments, redirects, retired = projection_policy(load_ledger(path, {"task_id": "TASK-04B"}))
        merged = merge("patent", [*entries, self.entry("EV-3", "patent", {"title": "Same title"})], {},
            identity_revision=REVISION, identity_assignments=assignments,
            identity_redirects=redirects, retired_identity_keys=retired)
        apply_candidate_contract("patent", merged)
        self.assertEqual(len(merged), 2)
        joined = next(row for row in merged if len(row["sources"]) == 2)
        self.assertEqual({ref["evidence_id"] for ref in joined["sources"]}, {"EV-1", "EV-2"})
        view = correction_view({"patents": merged}, {"events": [event]})
        self.assertEqual(view["aliases"][0]["old_candidate_ids"], old_ids)
        self.assertEqual(view["aliases"][0]["current_candidate_ids"], [joined["candidate_id"]])

    def test_merge_requires_source_evidence_for_each_candidate_and_ledger_is_integrity_checked(self):
        entries = [self.entry("EV-1", "patent", {"title": "A"}),
                   self.entry("EV-2", "patent", {"title": "B"})]
        path, rows, _ = self.correction_fixture(entries)
        ids = [row["candidate_id"] for row in rows]
        with self.assertRaisesRegex(ValueError, "EVIDENCE_UNRELATED"):
            record_correction(path, self.request("merge", ids, ["EV-1"]))
        self.assertFalse((path / "candidate-identity-corrections.json").exists())
        record_correction(path, self.request("merge", ids, ["EV-1", "EV-2"]))
        ledger = load_json(path / "candidate-identity-corrections.json")
        ledger["events"][0]["reason"] = "Changed after review"
        atomic_write_json(path / "candidate-identity-corrections.json", ledger)
        with self.assertRaisesRegex(ValueError, "LEDGER_CHANGED"):
            load_ledger(path, {"task_id": "TASK-04B"})

    def test_reviewed_split_partitions_sources_and_retires_old_identity(self):
        entries = [self.entry("EV-1", "patent", {"publication_number": "US11111111B2", "title": "A"}),
                   self.entry("EV-2", "patent", {"publication_number": "US11111111B2", "title": "B"})]
        path, rows, _ = self.correction_fixture(entries)
        self.assertEqual(len(rows), 1)
        anchors = [ref["source_anchor"] for ref in rows[0]["sources"]]
        bad = self.request("split", [rows[0]["candidate_id"]], ["EV-1", "EV-2"],
                           partitions=[[anchors[0]], ["missing"]])
        with self.assertRaisesRegex(ValueError, "PARTITIONS_NOT_EXACT"):
            record_correction(path, bad)
        self.assertFalse((path / "candidate-identity-corrections.json").exists())
        event = record_correction(path, {**bad, "partitions": [[anchors[0]], [anchors[1]]],
            "reason": "The shared number was misread on one source row"})
        assignments, redirects, retired = projection_policy(load_ledger(path, {"task_id": "TASK-04B"}))
        split = merge("patent", entries, {}, identity_revision=REVISION,
            identity_assignments=assignments, identity_redirects=redirects,
            retired_identity_keys=retired)
        apply_candidate_contract("patent", split)
        self.assertEqual(len(split), 2)
        self.assertTrue(all(len(row["sources"]) == 1 for row in split))
        self.assertNotIn(rows[0]["candidate_id"], {row["candidate_id"] for row in split})
        aliases = correction_view({"patents": split}, {"events": [event]})["aliases"]
        self.assertEqual(len(aliases[0]["current_candidate_ids"]), 2)

    def test_split_retires_older_merge_redirects_for_future_source_rows(self):
        entries = [self.entry("EV-1", "patent", {"publication_number": "US11111111B2"}),
                   self.entry("EV-2", "patent", {"publication_number": "US22222222B2"})]
        path, rows, _ = self.correction_fixture(entries)
        merged_event = record_correction(path, self.request("merge",
            [row["candidate_id"] for row in rows], ["EV-1", "EV-2"]))
        assignments, redirects, retired = projection_policy(load_ledger(path, {"task_id": "TASK-04B"}))
        joined = merge("patent", entries, {}, identity_revision=REVISION,
            identity_assignments=assignments, identity_redirects=redirects,
            retired_identity_keys=retired)
        apply_candidate_contract("patent", joined)
        atomic_write_json(path / "normalized-candidates.json",
            {"patents": joined, "identity_correction_head": merged_event["event_id"]})
        anchors = [ref["source_anchor"] for ref in joined[0]["sources"]]
        record_correction(path, self.request("split", [joined[0]["candidate_id"]],
            ["EV-1", "EV-2"], partitions=[[anchors[0]], [anchors[1]]]))
        assignments, redirects, retired = projection_policy(load_ledger(path, {"task_id": "TASK-04B"}))
        fresh = merge("patent", [*entries, self.entry("EV-3", "patent",
            {"publication_number": "US11111111B2"})], {}, identity_revision=REVISION,
            identity_assignments=assignments, identity_redirects=redirects,
            retired_identity_keys=retired)
        apply_candidate_contract("patent", fresh)
        self.assertEqual(len(fresh), 3)
        new = next(row for row in fresh if row["sources"][0]["evidence_id"] == "EV-3")
        self.assertEqual(new["identity_status"], "identity_pending")
        self.assertEqual(len(new["sources"]), 1)

    def test_field_resolution_uses_retained_claim_and_keeps_conflict(self):
        entries = [self.entry("EV-1", "patent", {"publication_number": "US11111111B2", "owner": "A"}),
                   self.entry("EV-2", "patent", {"publication_number": "US11111111B2", "owner": "B"})]
        path, rows, current = self.correction_fixture(entries)
        cid = rows[0]["candidate_id"]
        with self.assertRaisesRegex(ValueError, "SELECTED_CLAIM_UNSUPPORTED"):
            record_correction(path, self.request("field_selection", [cid], ["EV-1"],
                field="owner", selected_value="B"))
        event = record_correction(path, self.request("field_selection", [cid], ["EV-2"],
            field="owner", selected_value="B"))
        ledger = {"events": [event]}
        apply_reviewed_fields(current, ledger)
        self.assertEqual(rows[0]["owner"], "B")
        self.assertEqual(set(rows[0]["conflicts"]["owner"]), {"A", "B"})
        self.assertEqual(rows[0]["field_resolutions"]["owner"]["evidence_refs"], ["EV-2"])

    def test_field_resolution_follows_source_anchor_after_reviewed_merge(self):
        entries = [self.entry("EV-1", "patent", {"title": "Same", "owner": "A"}),
                   self.entry("EV-2", "patent", {"title": "Same", "owner": "B"})]
        path, rows, _ = self.correction_fixture(entries)
        first = next(row for row in rows if row["owner"] == "A")
        field_event = record_correction(path, self.request("field_selection",
            [first["candidate_id"]], ["EV-1"], field="owner", selected_value="A"))
        ledger = load_ledger(path, {"task_id": "TASK-04B"})
        assignments, redirects, retired = projection_policy(ledger)
        interim = merge("patent", entries, {}, identity_revision=REVISION,
            identity_assignments=assignments, identity_redirects=redirects,
            retired_identity_keys=retired)
        apply_candidate_contract("patent", interim)
        apply_reviewed_fields({"patents": interim}, ledger)
        atomic_write_json(path / "normalized-candidates.json",
            {"patents": interim, "identity_correction_head": field_event["event_id"]})
        merge_event = record_correction(path, self.request("merge",
            [row["candidate_id"] for row in interim], ["EV-1", "EV-2"]))
        assignments, redirects, retired = projection_policy(load_ledger(path, {"task_id": "TASK-04B"}))
        joined = merge("patent", entries, {}, identity_revision=REVISION,
            identity_assignments=assignments, identity_redirects=redirects,
            retired_identity_keys=retired)
        apply_candidate_contract("patent", joined)
        apply_reviewed_fields({"patents": joined}, {"events": [field_event, merge_event]})
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0]["owner"], "A")
        self.assertEqual(joined[0]["field_resolutions"]["owner"]["event_id"], field_event["event_id"])

    def test_merge_cli_replays_reviewed_identity_without_new_source_run(self):
        from test_assessment_estimate_recall import strict_fixture
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        task, evidence, _, plan, *_ = strict_fixture(path)
        task["candidate_identity_revision"] = REVISION
        evidence.setdefault("collections", {}).setdefault("patents", []).extend([
            self.entry("EV-04B-1", "patent", {"title": "Unnumbered actual object"}),
            self.entry("EV-04B-2", "patent", {"title": "Unnumbered actual object"})])
        for name, value in (("task", task), ("evidence", evidence), ("search-plan", plan)):
            atomic_write_json(path / (name + ".json"), value)
        def run_merge():
            with patch("sys.argv", ["merge_candidates.py", "--task-dir", str(path)]), redirect_stdout(StringIO()):
                merge_main()
            from common import load_json
            return load_json(path / "normalized-candidates.json")
        first = run_merge()
        leads = [row for row in first["patents"] if row.get("title") == "Unnumbered actual object"]
        self.assertEqual(len(leads), 2)
        old_ids = [row["candidate_id"] for row in leads]
        before_runs = evidence["source_runs"]
        record_correction(path, self.request("merge", old_ids, ["EV-04B-1", "EV-04B-2"]))
        second = run_merge()
        joined = [row for row in second["patents"] if row.get("title") == "Unnumbered actual object"]
        self.assertEqual(len(joined), 1)
        self.assertEqual(len(joined[0]["sources"]), 2)
        self.assertEqual(second["identity_aliases"][0]["old_candidate_ids"], old_ids)
        from common import load_json
        self.assertEqual(load_json(path / "evidence.json")["source_runs"], before_runs)


if __name__ == "__main__":
    unittest.main()
