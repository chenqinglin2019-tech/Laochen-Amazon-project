"""Offline physical-response identity regression; no API or business task writes."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from candidate_identity import REVISION, source_anchor
from common import atomic_write_json, load_json, sha256_file, sha256_json
from decision_workflow import candidate_content_sha256, candidate_identity_fingerprint
from merge_candidates import merge, apply_candidate_contract, physical_response_identity_aliases, main as merge_main
from provider_utils import PLAN_META_KEYS
from runtime_v24 import physical_response_source, _physical_request_identity
from serpapi_lens_client import normalize


class LensPhysicalCandidateIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.provider = "serpapi_google_lens"
        # The first two cards even share a URL and title. Ordinal and retained
        # content still distinguish them; URL deduplication would be incorrect.
        self.raw = {"search_metadata": {"status": "Success"}, "visual_matches": [
            {"title": "Rolling toy", "link": "https://example.test/toy", "image": "https://example.test/a.jpg"},
            {"title": "Rolling toy", "link": "https://example.test/toy", "image": "https://example.test/b.jpg"},
            {"title": "Different toy", "link": "https://example.test/other", "image": "https://example.test/c.jpg"}]}
        atomic_write_json(self.root / "raw.json", self.raw)
        self.plan = {"queries": {self.provider: []}}
        self.evidence = {"source_runs": [], "collections": {"copyright_assets": []}}
        for index, right in enumerate(("design", "copyright", "trade_dress", "design")):
            query = {"query_id": "Q-%s" % index, "operation": "image_search", "jurisdiction": "US",
                     "right_type": right, "image_url": "https://example.test/product.jpg",
                     "type": "all", "hl": "en", "country": "us"}
            self.plan["queries"][self.provider].append(query)
            params = {key: value for key, value in query.items() if key not in PLAN_META_KEYS}
            params["right_type"] = right
            run = {"run_id": "RUN-%s" % index, "query_id": query["query_id"], "provider": self.provider,
                "operation": "image_search", "jurisdiction": "US", "right_type": right,
                "request_params": params, "plan_entry_sha256": sha256_json(query),
                "status": "success", "submission_state": "submitted" if index == 0 else "not_submitted",
                "source_query_performed": index == 0, "quota": {"network_request_attempted": index == 0},
                "raw_paths": ["raw.json"], "payload_digest": sha256_file(self.root / "raw.json"),
                "started_at": "2026-09-29T01:00:00Z", "finished_at": "2026-09-29T01:00:01Z",
                "data_date": "2026-09-29", "metadata": {}}
            entry = {"evidence_id": "EV-%s" % index, "source_run_id": run["run_id"],
                "query_id": run["query_id"], "provider": self.provider, "operation": run["operation"],
                "jurisdiction": "US", "right_type": right, "plan_entry_sha256": run["plan_entry_sha256"],
                "collected_at": run["finished_at"], "payload": normalize(self.raw,
                    retrieval_workflow_revision="api-first-v3", investigation_right_type=right)}
            if index:
                original = self.evidence["source_runs"][0]
                run["metadata"]["physical_response_reuse"] = {
                    "source_run_id": original["run_id"], "source_run_sha256": sha256_json(original),
                    "request_identity_sha256": sha256_json(_physical_request_identity(self.provider,
                        {**original["request_params"], "operation": original["operation"], "jurisdiction": "US"})),
                    "source_finished_at": original["finished_at"], "independent_source_count": 1,
                    "network_request_attempted": False, "bound_at": "2026-09-29T01:01:00Z"}
                entry["physical_response_reuse"] = {"source_evidence_id": "EV-0", "source_run_id": "RUN-0",
                    "source_run_sha256": sha256_json(original), "source_collected_at": original["finished_at"],
                    "independent_source_count": 1, "bound_at": "2026-09-29T01:01:00Z"}
            self.evidence["source_runs"].append(run)
            self.evidence["collections"]["copyright_assets"].append(entry)
        atomic_write_json(self.root / "search-plan.json", self.plan)

    def merged(self, entries=None, **kwargs):
        rows = merge("copyright", self.entries if entries is None else entries,
            {row["run_id"]: row for row in self.evidence["source_runs"]}, identity_revision=REVISION,
            task_dir=self.root, evidence=self.evidence, **kwargs)
        apply_candidate_contract("copyright", rows)
        return rows

    @property
    def entries(self):
        return self.evidence["collections"]["copyright_assets"]

    def test_four_logical_scopes_keep_original_ids_and_content_with_all_refs(self):
        for run in self.evidence["source_runs"][1:]:
            self.assertIsNotNone(physical_response_source(self.root, self.evidence, run))
        before = deepcopy(self.evidence)
        original = self.merged([self.entries[0]])
        rows = self.merged()
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["candidate_id"] for row in rows], [row["candidate_id"] for row in original])
        task = {"candidate_identity_revision": REVISION}
        for old, new in zip(original, rows):
            self.assertEqual(new["conflicts"], {})
            self.assertEqual(new["source_indexes"], ["google_lens"])
            self.assertEqual({ref["source_run_id"] for ref in new["sources"]}, {"RUN-0", "RUN-1", "RUN-2", "RUN-3"})
            self.assertEqual({ref["right_type"] for ref in new["sources"]}, {"design", "copyright", "trade_dress"})
            self.assertEqual(new["evidence_refs"], ["EV-0", "EV-1", "EV-2", "EV-3"])
            self.assertEqual(new["duplicate_evidence_refs"], ["EV-1", "EV-2", "EV-3"])
            self.assertEqual(candidate_content_sha256(old, self.evidence, task=task),
                             candidate_content_sha256(new, self.evidence, task=task))
            self.assertEqual(candidate_identity_fingerprint("copyright_assets", old),
                             candidate_identity_fingerprint("copyright_assets", new))
        self.assertEqual(before, self.evidence)

    def test_reordered_collection_still_uses_physical_card_as_original(self):
        before = self.merged()
        after = self.merged(list(reversed(self.entries)))
        self.assertEqual([row["candidate_id"] for row in before], [row["candidate_id"] for row in after])
        for row in after:
            self.assertEqual(row["sources"][0]["source_run_id"], "RUN-0")
            self.assertEqual(row["investigation_right_type"], "design")
            self.assertNotIn("EV-0", row["duplicate_evidence_refs"])

    def test_former_wrapper_ids_remain_traceable_without_review_transfer(self):
        old = merge("copyright", self.entries,
            {row["run_id"]: row for row in self.evidence["source_runs"]}, identity_revision=REVISION,
            task_dir=self.root)
        aliases = physical_response_identity_aliases({"copyright_assets": self.merged()})
        self.assertEqual(len(aliases), 9)
        self.assertEqual({row["candidate_id"] for row in old[3:]},
                         {alias["old_candidate_ids"][0] for alias in aliases})
        self.assertTrue(all(alias["kind"] == "physical_response_reuse" and
                            alias["transfers_status_or_risk"] is False for alias in aliases))

    def test_unproven_or_tampered_run_is_not_collapsed(self):
        original = deepcopy(self.evidence)
        mutations = [
            lambda run: run["metadata"].pop("physical_response_reuse"),
            lambda run: run["metadata"]["physical_response_reuse"].update(source_run_sha256="0" * 64),
            lambda run: run["metadata"]["physical_response_reuse"].update(independent_source_count=2),
            lambda run: run["metadata"]["physical_response_reuse"].update(request_identity_sha256="0" * 64),
            lambda run: run["quota"].update(network_request_attempted=True),
            lambda run: run.update(finished_at="2026-09-29T02:00:00Z"),
            lambda run: run["request_params"].update(image_url="https://example.test/another.jpg"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.evidence = deepcopy(original)
                mutate(self.evidence["source_runs"][1])
                self.assertEqual(len(self.merged()), 6)

    def test_entry_proof_must_identify_actual_original_entry(self):
        original = deepcopy(self.evidence)
        for field, value in (("source_evidence_id", "EV-NOT-RETAINED"), ("source_run_id", "RUN-2"),
                             ("source_run_sha256", "0" * 64), ("independent_source_count", 2),
                             ("source_collected_at", "2026-01-01T00:00:00Z")):
            with self.subTest(field=field):
                self.evidence = deepcopy(original)
                self.entries[1]["physical_response_reuse"][field] = value
                self.assertEqual(len(self.merged()), 6)

    def test_changed_plan_is_not_a_valid_physical_reuse(self):
        self.plan["queries"][self.provider][1]["country"] = "gb"
        atomic_write_json(self.root / "search-plan.json", self.plan)
        self.assertEqual(len(self.merged()), 6)

    def test_changed_url_image_title_hash_or_card_order_is_rejected(self):
        original = deepcopy(self.evidence)
        for field, value in (("url", "https://example.test/forged"),
                             ("image_url", "https://example.test/forged.jpg"),
                             ("title", "New title"), ("source_record_sha256", "0" * 64),
                             ("source_collection", "exact_matches")):
            with self.subTest(field=field):
                self.evidence = deepcopy(original)
                self.entries[1]["payload"]["candidates"][0][field] = value
                with self.assertRaisesRegex(ValueError, "LENS_RETAINED_NORMALIZATION_INVALID"):
                    self.merged()
        self.evidence = deepcopy(original)
        self.entries[1]["payload"]["candidates"].reverse()
        with self.assertRaisesRegex(ValueError, "LENS_RETAINED_NORMALIZATION_INVALID"):
            self.merged()

    def test_raw_bytes_tamper_is_rejected(self):
        atomic_write_json(self.root / "raw.json", {**self.raw, "changed": True})
        with self.assertRaisesRegex(ValueError, "LENS_RETAINED_NORMALIZATION_INVALID"):
            self.merged()

    def test_unrelated_identical_physical_response_stays_a_distinct_source(self):
        # A second physical network request may contain the same exact cards.
        run = self.evidence["source_runs"][1]
        run.update(submission_state="submitted", source_query_performed=True, metadata={},
                   quota={"network_request_attempted": True})
        self.entries[1].pop("physical_response_reuse")
        self.assertEqual(len(self.merged()), 6)

    def test_missing_original_entry_cannot_supply_an_anchor(self):
        self.assertEqual(len(self.merged(self.entries[1:])), 9)

    def test_pre_v3_records_keep_their_existing_identity_behavior(self):
        for run, entry in zip(self.evidence["source_runs"], self.entries):
            run["raw_paths"] = [str(self.root / "raw.json")]
            entry["payload"] = normalize(self.raw, retrieval_workflow_revision="api-first-v2")
        original_hash = sha256_json(self.evidence["source_runs"][0])
        for run, entry in zip(self.evidence["source_runs"][1:], self.entries[1:]):
            run["metadata"]["physical_response_reuse"]["source_run_sha256"] = original_hash
            entry["physical_response_reuse"]["source_run_sha256"] = original_hash
        self.assertEqual(len(self.merged()), 12)

    def test_reviewed_identity_assignment_is_not_overwritten(self):
        logical_anchor = source_anchor("copyright", self.entries[1], 1)
        rows = self.merged(identity_assignments={logical_anchor: "copyright:reviewed:separate"})
        self.assertEqual(len(rows), 4)
        separate = next(row for row in rows if row["normalization_key"] == "copyright:reviewed:separate")
        self.assertEqual(len(separate["sources"]), 1)
        self.assertNotIn("logical_candidate_id", separate["sources"][0])

    def test_distinct_positions_survive_even_when_cards_are_identical(self):
        self.raw["visual_matches"][1] = deepcopy(self.raw["visual_matches"][0])
        atomic_write_json(self.root / "raw.json", self.raw)
        for run, entry in zip(self.evidence["source_runs"], self.entries):
            run["payload_digest"] = sha256_file(self.root / "raw.json")
            entry["payload"] = normalize(self.raw, retrieval_workflow_revision="api-first-v3",
                                         investigation_right_type=entry["right_type"])
        original_hash = sha256_json(self.evidence["source_runs"][0])
        for run, entry in zip(self.evidence["source_runs"][1:], self.entries[1:]):
            run["metadata"]["physical_response_reuse"]["source_run_sha256"] = original_hash
            entry["physical_response_reuse"]["source_run_sha256"] = original_hash
        rows = self.merged()
        self.assertEqual(len(rows), 3)
        self.assertNotEqual(rows[0]["candidate_id"], rows[1]["candidate_id"])

    def test_merge_cli_projects_aliases_and_is_repeatable_without_new_receipts(self):
        from test_assessment_estimate_recall import strict_fixture
        task, evidence, _, plan, *_ = strict_fixture(self.root)
        task["candidate_identity_revision"] = REVISION
        evidence["source_runs"].extend(deepcopy(self.evidence["source_runs"]))
        evidence["collections"]["copyright_assets"] = deepcopy(self.entries)
        plan["queries"][self.provider] = deepcopy(self.plan["queries"][self.provider])
        for name, value in (("task", task), ("evidence", evidence), ("search-plan", plan)):
            atomic_write_json(self.root / (name + ".json"), value)
        receipt_before = (self.root / "evidence.json").read_bytes()
        def run_merge():
            with patch("sys.argv", ["merge_candidates.py", "--task-dir", str(self.root)]), redirect_stdout(StringIO()):
                merge_main()
            return load_json(self.root / "normalized-candidates.json")
        first = run_merge()
        second = run_merge()
        self.assertEqual(len(first["copyright_assets"]), 3)
        self.assertEqual(len(first["identity_aliases"]), 9)
        self.assertEqual(first["identity_aliases"], second["identity_aliases"])
        self.assertEqual(first["copyright_assets"], second["copyright_assets"])
        self.assertEqual(receipt_before, (self.root / "evidence.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
