"""r5c fixes found by the end-to-end rehearsal: duplicate query ids in one runner batch, defaults that never saw
unlinked cards, the source-investigation host, the program term fallback and the dossier's record review."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")


class DispatchBatchTests(unittest.TestCase):
    def test_a_query_shared_by_several_work_entries_is_submitted_once(self):
        import advance_work
        plan = {"queries": {"serper_images": [{"query_id": "Q1", "execution_phase": "discovery"}],
                            "serpapi_google_patents": [{"query_id": "Q2", "execution_phase": "discovery"}]}}
        entries = [{"query_id": "Q1", "work_id": "W1"}, {"query_id": "Q1", "work_id": "W2"},
                   {"query_id": "Q2", "work_id": "W3"}, {"query_id": "Q1", "work_id": "W4"}]
        seen = []

        def fake_run(command, **kwargs):
            seen.append(command)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, patch("advance_work.subprocess.run", fake_run):
            advance_work._execute_sources(Path(tmp), plan, entries)
        ids = seen[0][seen[0].index("--query-ids") + 1: seen[0].index("--phase")]
        self.assertEqual(ids, ["Q1", "Q2"])


class DefaultsLinkTests(unittest.TestCase):
    def test_defaults_link_new_cards_to_the_scope_before_deciding(self):
        import triage_defaults
        order = []
        with patch("candidate_scope_link.auto_link", lambda root: order.append("link") or {"linked": 3}), \
                patch.object(triage_defaults, "build_decisions", lambda root: order.append("decide") or ([], [])), \
                patch.object(triage_defaults, "record", lambda root, decisions: {"recorded": 0, "rejected": []}):
            triage_defaults.run(Path("."))
        self.assertEqual(order, ["link", "decide"])


class TermFallbackTests(unittest.TestCase):
    def test_program_fallback_yields_function_and_structural_terms(self):
        import product_understanding_host as host
        title = "Lid Latch the reusable universal lid securing strap for crockpots, casserole dishes"
        self.assertEqual(host.function_phrase(title), "universal lid securing strap")
        self.assertEqual(host.structural_phrase("PATENTED UNIVERSAL FIT LID LATCH: Flexible silicone latch straps fit most"),
                         "flexible silicone latch straps")
        self.assertEqual(host.structural_phrase("Fits most"), "")


class ProvenanceHostTests(unittest.TestCase):
    def packet(self):
        return {"source_url": "https://www.amazon.com/dp/B000000001",
                "capture": {"path": "/run/capture.json", "sha256": "c" * 64, "bytes": 10},
                "product_images": [{"image_id": "IMG-001", "attachment": "a.jpg", "path": "/run/a.jpg", "sha256": "a" * 64, "bytes": 5}],
                "units": [{"unit_id": "PRV-1", "right_type": "trade_dress", "scenario_id": "product_entry", "jurisdiction": "US",
                           "asset_ids": ["PRODUCT"], "query_ids": ["Q1", "Q2"], "scope_sha256": "s" * 64,
                           "steps": [{"step": "public_use", "meaning": "m"}, {"step": "functionality", "meaning": "m"}]}]}

    def test_output_must_cover_every_step_and_keep_unknowns(self):
        import provenance_host as host
        packet = self.packet()
        good = {"units": [{"unit_id": "PRV-1", "steps": {"public_use": "页面在售", "functionality": "孔位由用途决定"},
                           "source_reasoning": "发布者不等于权利人", "unresolved": ["第二含义未确认"]}]}
        decision = host.decisions_from_output(good, packet, "s1")[0]
        payload = host.provenance_input(decision, packet, "EV-CAP", ["EV-BROWSER"], "native-provenance-s1")
        self.assertEqual([step["step"] for step in payload["investigation_steps"]], ["public_use", "functionality"])
        self.assertEqual(payload["investigation_steps"][0]["evidence_refs"], ["EV-CAP", "EV-BROWSER"])
        self.assertEqual(payload["unresolved"], ["第二含义未确认"])
        self.assertEqual(payload["asset_scope_sha256"], "s" * 64)
        for broken in ({"units": [{**good["units"][0], "steps": {"public_use": "x"}}]},
                       {"units": [{**good["units"][0], "unresolved": []}]},
                       {"units": [{**good["units"][0], "steps": {"public_use": "相似度 90%", "functionality": "x"}}]}):
            with self.assertRaises(ValueError):
                host.decisions_from_output(broken, packet, "s1")


class DossierRecordReviewTests(unittest.TestCase):
    def test_the_detail_record_reading_is_registered_once(self):
        import core_dossier
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evidence.json").write_text(json.dumps({"source_runs": [{"run_id": "ATT-1"}], "record_content_reviews": []}))
            with patch("source_result_processing._retained_run", lambda *a: ({}, b"{}")), \
                    patch("source_result_processing._whole_record_reading", lambda *a: (["identity", "claims"], [])), \
                    patch("source_result_processing.append_record_content_review",
                          lambda task_dir, run_id, request: calls.append((run_id, request))):
                self.assertEqual(core_dossier.review_detail_record(root, {"source_run_id": "ATT-1"}), "recorded")
            self.assertEqual(calls[0][1]["reading_units"], ["identity", "claims"])
            self.assertEqual(calls[0][1]["reviewer"], "program:core_dossier")
            (root / "evidence.json").write_text(json.dumps({"source_runs": [{"run_id": "ATT-1"}],
                                                            "record_content_reviews": [{"source_run_id": "ATT-1"}]}))
            self.assertEqual(core_dossier.review_detail_record(root, {"source_run_id": "ATT-1"}), "present")


class DossierLimitationBindingTests(unittest.TestCase):
    def test_a_handoff_gap_covering_two_unknown_facts_is_bound_once(self):
        import core_dossier
        import specialty_analysis as sa
        scope = {"candidate_id": "CAND-1", "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent"}
        history = [
            {"kind": "intake", "event_id": "I1", **scope},
            {"kind": "handoff_classification", "event_id": "H1", "intake_event_id": "I1", "handoff_gap": "状态与权利人未核验",
             "fact_kinds": ["status", "rights_holder"], **scope},
            {"kind": "fact", "event_id": "F1", "intake_event_id": "I1", "fact_kind": "status", "outcome": "unknown", **scope},
            {"kind": "fact", "event_id": "F2", "intake_event_id": "I1", "fact_kind": "rights_holder", "outcome": "unknown", **scope}]
        source = {"required_facts": ["current_status", "rights_holder"],
                  "delivery_limit": {"planning_gap_sha256": "p", "capabilities_sha256": "c"}}
        with patch.object(sa, "_intake", lambda task, key: history[0]), \
                patch.object(sa, "events", lambda task: history), \
                patch.object(core_dossier, "_capabilities", lambda *a: {}), \
                patch("necessary_completion.api_record_gap_entry", lambda *a, **k: source):
            request, reason = core_dossier.limitation_request(Path("."), {}, {}, {}, {}, {}, {}, scope, {"evidence_id": "EV-1"})
        self.assertIsNone(reason)
        gaps = [event for event in request["events"] if event["kind"] == "gap"]
        follows = [event for event in request["events"] if event["kind"] == "followup"]
        self.assertEqual(len(gaps), 2)
        self.assertEqual([f["gap_event_id"] for f in follows], [{"$event": "g0"}, {"$event": "g1"}])
        self.assertEqual(len({g["gap_id"] for g in gaps}), 2)
        for gap in gaps:      # within one gap event a handoff gap is bound at most once
            keys = [(b["reason"], b.get("handoff_gap") or b["fact_kind"]) for b in gap["obligation_bindings"]]
            self.assertEqual(len(keys), len(set(keys)))
        facets = sorted(b["fact_kind"] for gap in gaps for b in gap["obligation_bindings"]
                        if b["reason"] == "SPECIALTY_HANDOFF_GAP_OPEN")
        self.assertEqual(facets, ["rights_holder", "status"])      # every (gap, fact) blocker has a binding
        self.assertEqual({b["fact_kind"] for b in gaps[0]["obligation_bindings"] if b["reason"] == "SPECIALTY_FACT_REQUIRED"},
                         {"status", "rights_holder"})


class InitialProgressTests(unittest.TestCase):
    def test_first_registration_covers_every_unsubmitted_plan_row(self):
        import mechanical_ledger
        task = {"assessment_scenarios": [{"scenario_id": "product_entry"}]}
        plan = {"queries": {
            "serper_images": [{"query_id": "Q1", "scenario_id": "product_entry"}],
            "serpapi_google_patents": [{"query_id": "Q2", "scenario_bindings": [{"scenario_id": "product_entry"},
                                                                              {"scenario_id": "reseller"}]},
                                       {"query_id": "Q3"}],
            "asset_provenance": [{"query_id": "Q4", "scenario_id": "product_entry"}]}}
        evidence = {"source_runs": [{"query_id": "Q4", "source_environment": "local_agent_review"}]}
        entries = mechanical_ledger._initial_progress_entries(task, plan, evidence)
        self.assertEqual([(e["query_id"], e["scenario_id"]) for e in entries],
                         [("Q1", "product_entry"), ("Q2", "product_entry"), ("Q2", "reseller"), ("Q3", "product_entry")])


if __name__ == "__main__":
    unittest.main()
