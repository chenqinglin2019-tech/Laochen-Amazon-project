"""Whole offline v2 pipeline with retained synthetic receipts, never live evidence."""
from copy import deepcopy
from pathlib import Path
import unittest

from common import atomic_write_json, load_json, sha256_json, sha256_file, now_iso
from offline_test_support import isolated_test_environment


def build_evidence_delivery_fixture(directory, *, scenario="pending"):
    """Run retained synthetic receipts through real review and delivery gates.

    pending/all_discovery_failed/mixed_high/browser_scope_high and the
    browser_scope_failed/browser_scope_unknown variants publish and rebuild;
    summary_only reaches the real gate and returns its unread-work rejection.
    """
    from test_api_first_planning import ApiFirstPlanningTests
    from test_report_estimate import PNG
    from record_asset_provenance import asset_scope, inventory_identity_sha256
    from workflow_v24 import product_identity_digest, generate_plan, work_view_from_dir
    from api_first_planning import append_followup, triage_digest
    from publish_report import publish
    from report_estimate import RIGHT_MODULES, validate_run, build_bundle
    browser_scope = scenario in {"browser_scope_high", "browser_scope_failed", "browser_scope_unknown"}
    if scenario not in {"pending", "all_discovery_failed", "mixed_high", "summary_only"} and not browser_scope:
        raise ValueError("Unknown offline fixture scenario")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    with isolated_test_environment():
        seed = ApiFirstPlanningTests()
        seed.setUp()
        try:
            task = deepcopy(seed.task)
            evidence = deepcopy(seed.evidence)
            candidates = deepcopy(seed.candidates)
            ledger = deepcopy(seed.ledger)
        finally:
            seed.tearDown()
        task["completion_policy_revision"] = "necessary-work-v2"
        if browser_scope:
            from common import serper_free_enhancement, serpapi_free_enhancement
            task["serper_free_enhancement"] = serper_free_enhancement(False, "api-first-v1")
            task["serpapi_free_enhancement"] = serpapi_free_enhancement(False, "api-first-v1")
            task["signa_free_enhancement"]["enabled"] = False
        task["task_id"] = evidence["task_id"] = candidates["task_id"] = ledger["task_id"] = "IPRF-OFFLINE-EVIDENCE-DELIVERY-V2"
        task["product"].update(title="离线合成流程样本（不是实际商品排查）", source_url="https://example.org/offline-product",
            assets=[{"asset_id": "shape", "usage": "product_configuration", "right_types": ["copyright", "trade_dress"],
                "scenario_ids": ["product_entry"], "scope_reasoning": "Synthetic observed functional configuration",
                "evidence_refs": ["EV-PRODUCT"]}], mark_inventory=[])
        task["query_terms"].append({"kind": "product", "value": "functional strap", "language": "en", "derived_from": "product.category"})
        product_path, source_path = directory / "product.png", directory / "public-source.html"
        product_path.write_bytes(PNG)
        source_path.write_text("<html><body>Offline synthetic original: a functional strap, no confirmed figurative mark. No ownership assertion.</body></html>", encoding="utf-8")
        if scenario == "mixed_high" or browser_scope:
            source_path.write_text("<html><body>OFFLINE SYNTHETIC ORIGINAL: Artist Fixture created the illustrated front artwork in 2024. "
                "The proposed synthetic product reproduces the whole distinct composition and placement. "
                "This synthetic source grants no product reproduction licence. This is test data, not a real right.</body></html>", encoding="utf-8")
        image = {"path": str(product_path), "sha256": sha256_file(product_path), "bytes": product_path.stat().st_size,
            "role": "main", "mime_type": "image/png", "source_url": "https://example.org/offline-product"}
        task["images"] = [image]
        product_evidence = {"evidence_id": "EV-PRODUCT", "kind": "product_record", "provider": "amazon_browser",
            "payload": {"asin": task["product"]["actual_asin"], "images": [deepcopy(image)]}}
        source_evidence = {"evidence_id": "EV-PUBLIC", "kind": "provenance_document", "source_url": "https://example.org/offline-source",
            "path": str(source_path), "sha256": sha256_file(source_path), "bytes": source_path.stat().st_size,
            "checked_at": "2026-01-01T00:00:00Z"}
        evidence["source_runs"] = []
        evidence["collections"] = {"product": [product_evidence], "public_sources": [source_evidence]}
        for key in ("patents", "trademarks", "copyright_assets", "enforcement"):
            candidates[key] = []
        ledger["annotations"] = []
        task["discovery_followups"] = []
        for field, rights in (("asset_scope_review", ("copyright", "trade_dress")),
                              ("mark_inventory_review", ("trademark_figurative",))):
            task["product"][field] = {"status": "reviewed", "reviewer": "offline-inventory-agent",
                "reasoning": "Synthetic source image and complete inventory reviewed for the offline pipeline fixture.",
                "evidence_refs": ["EV-PRODUCT", "EV-PUBLIC"],
                "inventory_identity_sha256_by_right": {right: inventory_identity_sha256(task, right) for right in rights}}
        task["product"]["analysis"]["identity_sha256"] = product_identity_digest(task["product"], task=task)
        if scenario == "mixed_high" or browser_scope:
            from decision_workflow import make_annotation
            source_evidence.update(candidate_id="C-SYNTHETIC-ART", jurisdiction="US", right_type="copyright")
            candidate = {"candidate_id": "C-SYNTHETIC-ART", "right_type": "copyright", "jurisdiction": "US",
                "title": "Synthetic retained original artwork", "evidence_refs": ["EV-PUBLIC"], "sources": [], "material": True}
            candidates["copyright_assets"].append(candidate)
            ledger["annotations"].append(make_annotation(task, "copyright_assets", candidate, {
                "annotation_id": "TRIAGE-SYNTHETIC-ART", "scenario_id": "product_entry", "decision": "selected",
                "reviewer": "offline-triage-agent", "annotated_at": now_iso(), "reading_level": "full_document",
                "reason": "The retained synthetic original identifies the expression used on the product.",
                "basis_summary": "Read the retained source's authorship, reproduction and licence statements.",
                "reopen_conditions": ["Different product artwork or a valid licence."], "evidence_refs": ["EV-PUBLIC", "EV-PRODUCT"]}, evidence=evidence))
        from common import coverage_routes
        providers = {row["provider"] for row in coverage_routes(task)} | {"serper_patents", "serper_web", "serper_images", "asset_provenance"}
        caps = {provider: {"provider": provider, "executable": provider.startswith("serper_") or provider == "asset_provenance",
            "reason": "first_real_query_checks_free_account_and_contract" if provider.startswith("serper_") else
                "free_public_document_or_agent_evidence" if provider == "asset_provenance" else "automation_policy_incompatible",
            "state": "unvalidated" if provider.startswith("serper_") else "unavailable", "cost_ceiling_usd": 0}
            for provider in sorted(providers)}
        if browser_scope:
            for provider, cap in caps.items():
                if provider == "asset_provenance":
                    continue
                cap.update(executable=False, reason="browser_adapter_requires_real_route_acceptance" if provider in
                    {"uspto_patent_browser", "uspto_tmsearch_browser"} else "automation_policy_incompatible")
        atomic_write_json(directory / "source-capabilities.json", {"schema_version": "2.4-free", "task_id": task["task_id"], "sources": list(caps.values())})
        def save():
            for name, value in (("task", task), ("evidence", evidence), ("normalized-candidates", candidates), ("materiality-annotations", ledger)):
                atomic_write_json(directory / (name + ".json"), value)
        save()
        plan = generate_plan(directory)
        task = load_json(directory / "task.json")
        if browser_scope:
            # At this point no invented source failure or observation exists.
            # Empty native route sets and language bindings must already be
            # explainable from the actual frozen plan/capability snapshot.
            initial_work = work_view_from_dir(directory)
            planned_rights = {row["right_type"] for provider, rows in plan["queries"].items() if provider.endswith("browser")
                for row in rows if row.get("search_language") == "en"}
            language = [item for item in initial_work["entries"] if "LANGUAGE" in item["reason"] and item["right_type"] in planned_rights]
            if not language or any(item["state"] == "ready" or not item.get("query_refs") for item in language):
                raise AssertionError("Compiled English browser plans left an orphan translation todo")
            absence = [item for item in initial_work["entries"] if item.get("right_type") in {"copyright", "trade_dress"}
                and item.get("delivery_limit", {}).get("route_absence")]
            if not absence or any(item["delivery_limit"].get("source_run_refs") for item in absence):
                raise AssertionError("An empty qualified route set requires policy/capability proof without a fake failed query")
        artifacts = [{key: image[key] for key in ("path", "sha256", "bytes", "role")},
            {key: source_evidence[key] for key in ("path", "sha256", "bytes")} | {"role": "source_document"}]
        unknown_query = next((row["query_id"] for row in reversed(plan["queries"].get("uspto_patent_browser", []))
            if row["right_type"] == "patent"), None) if scenario == "browser_scope_unknown" else None

        def retain(query, provider, raw, payload, status):
            identity = "RUN-" + str(len(evidence["source_runs"]))
            raw_path = directory / (identity + ".json")
            atomic_write_json(raw_path, raw)
            run = {"run_id": identity, "provider": provider, "status": status,
                "submission_state": "unknown" if query["query_id"] == unknown_query else "submitted",
                "plan_entry_sha256": sha256_json(query), "source_environment": "unit_test_only", "raw_paths": [str(raw_path)],
                "payload_digest": sha256_file(raw_path), "finished_at": now_iso(),
                **({"error_code": payload["error_code"]} if status == "failed" else {}),
                **{key: query[key] for key in ("query_id", "operation", "jurisdiction", "right_type", "requirement_ids")}}
            evidence["source_runs"].append(run)
            entry = {"evidence_id": "EV-" + identity, "source_run_id": identity, "payload": deepcopy(payload),
                **{key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
            evidence["collections"].setdefault("asset_provenance" if provider == "asset_provenance" else "discovery", []).append(entry)
            return run, entry

        def review_discovery(query, run):
            nonlocal task
            failed, unknown = run["status"] == "failed", run["submission_state"] == "unknown"
            append_followup(directory, {"role": "review", "parent_query_id": query["query_id"], "source_run_id": run["run_id"],
                "evidence_ids": ["EV-" + run["run_id"]], "triage_digest": triage_digest(task, evidence, candidates, ledger, query_id=query["query_id"]),
                "reviewer": "offline-discovery-agent", "outcome": "blocked" if failed else "stop_bounded_discovery",
                **({"blocker": "The exact retained timeout response establishes this source limitation, not zero results."} if failed else {}),
                **({"submission_review": {"state": "unknown_after_receipt_review",
                    "reasoning": "The original synthetic receipt was read but does not establish upstream submission. Keep the slot and prohibit replay."}} if unknown else {}),
                "reason": "Read the exact synthetic source response and bounded attempt; official coverage remains unverified."})
            task = load_json(directory / "task.json")

        for provider, rows in plan["queries"].items():
            for query in rows:
                if query.get("action_purpose") == "discovery":
                    payload = {"candidates": [], "fixture_only": True}
                    raw = {"images" if provider == "serper_images" else "organic": [], "fixture_only": True}
                    status = "no_result"
                    if scenario == "all_discovery_failed":
                        raw = {"error": "PROVIDER_TIMEOUT", "message": "Synthetic retained failure response, not a live provider response.", "fixture_only": True}
                        payload, status = {"error_code": "PROVIDER_TIMEOUT", "fixture_only": True}, "failed"
                    if scenario == "browser_scope_failed" or query["query_id"] == unknown_query:
                        raw = {"error_code": "BROWSER_SEMANTIC_TIMEOUT", "message": "Synthetic retained browser timeout, not zero results.", "fixture_only": True}
                        payload, status = {"error_code": "BROWSER_SEMANTIC_TIMEOUT", "fixture_only": True}, "failed"
                    if scenario == "summary_only" and provider == "serper_patents" and query["right_type"] == "patent" and not candidates["patents"]:
                        from serper_client import normalize
                        raw = {"organic": [{"title": "OFFLINE SYNTHETIC strap patent summary", "link": "https://patents.google.com/patent/US12345678B2/en",
                            "snippet": "An abstract-only discovery card about a strap. No claims or original document has been retrieved.", "position": 1}], "fixture_only": True}
                        payload, status = {"candidates": normalize(provider, query["operation"], raw, retrieval_workflow_revision="api-first-v1")}, "success"
                elif provider == "asset_provenance":
                    sid = query.get("scenario_id") or query["scenario_bindings"][0]["scenario_id"]
                    inventory = asset_scope(task, sid, query["right_type"])
                    payload = {"candidate_id": "", "jurisdiction": query["jurisdiction"], "right_type": query["right_type"],
                        "scenario_id": sid, "asset_scope_sha256": inventory["scope_sha256"], "reviewer": "offline-source-agent",
                        "source_url": "https://example.org/offline-source", "ownership_or_source_reasoning": "Synthetic public source reviewed; ownership remains unknown.",
                        "coverage_attestation": {"inventory_complete": True, "asset_ids": inventory["asset_ids"], "reviewed_asset_ids": inventory["asset_ids"]},
                        "artifacts": deepcopy(artifacts), "outstanding_actions": [], "unresolved": ["Ownership remains unconfirmed in this synthetic case."],
                        "investigation_steps": [{"step": query["search_dimension"], "status": "completed" if inventory["asset_ids"] else "not_applicable",
                            "reasoning": "Read the retained synthetic source and product image for this exact step.",
                            "artifact_sha256": [image["sha256"]] if query["search_dimension"] == "visual_comparison" else [item["sha256"] for item in artifacts],
                            "evidence_refs": ["EV-PRODUCT", "EV-PUBLIC"]}]}
                    raw, status = payload, "success"
                else:
                    raise AssertionError("Unexpected provider in bounded offline fixture: " + provider)
                run, entry = retain(query, provider, raw, payload, status)
                if scenario == "summary_only" and payload.get("candidates"):
                    from merge_candidates import merge, apply_candidate_contract
                    from decision_workflow import make_annotation
                    found = merge("patent", [entry], {run["run_id"]: run})
                    apply_candidate_contract("patent", found)
                    candidates["patents"].extend(found)
                    candidate = found[0]
                    ledger["annotations"].append(make_annotation(task, "patents", candidate, {
                        "annotation_id": "TRIAGE-SUMMARY-ONLY", "scenario_id": "product_entry", "decision": "needs_info",
                        "reviewer": "offline-triage-agent", "annotated_at": now_iso(), "reading_level": "abstract",
                        "reason": "Only the normalized discovery summary is present; original claims have not been read.",
                        "basis_summary": "A summary is not evidence of the full protected technical elements.",
                        "reopen_conditions": ["Retrieve and read the original independent claims."], "evidence_refs": [entry["evidence_id"]],
                        "missing_information": ["Original protected technical elements"], "next_actions": [{"action_id": "read-original-claims",
                            "kind": "agent_read", "purpose": "Read original protection content; do not substitute a summary.",
                            "max_attempts": 1, "required_facts": ["protection_content"], "reading_scope": {"level": "protection_content"},
                            "evidence_refs": [entry["evidence_id"]]}]}, evidence=evidence))
                save()
                if query.get("action_purpose") == "discovery" and not (scenario == "summary_only" and payload.get("candidates")):
                    review_discovery(query, run)
                    if scenario == "browser_scope_failed":
                        from workflow_v24 import browser_submitted_failure_state
                        recovery = browser_submitted_failure_state(task, evidence, provider, query)
                        if not recovery or recovery["remaining_attempts"] != 1:
                            raise AssertionError("The original browser policy did not allow this one recovery")
                        run, entry = retain(query, provider, raw, payload, status)
                        save()
                        review_discovery(query, run)
                        recovery = browser_submitted_failure_state(task, evidence, provider, query)
                        if recovery["reason"] != "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED" or recovery["remaining_attempts"]:
                            raise AssertionError("The exact original browser recovery was not exhausted")
        save()
        # Reconcile the reviewed empty mark inventory and any now stale planning gaps.
        plan = generate_plan(directory, expand=True)
        task = load_json(directory / "task.json")
        work = work_view_from_dir(directory)
        if scenario != "summary_only" and any(item["state"] in {"ready", "awaiting_review", "submission_unknown"} for item in work["entries"]):
            raise AssertionError("Offline fixture still has executable work: " + str(work["entries"]))
        reviews = []
        for role in ("first", "second"):
            rows = []
            for obligation in work["review_work"]["entries"]:
                if obligation["action_id"] != "review:" + role:
                    continue
                assessment_scenario = next(item for item in task["assessment_scenarios"] if item["scenario_id"] == obligation["scenario_id"])
                refs = ["EV-PUBLIC", "EV-PRODUCT"] + [entry["evidence_id"] for entries in evidence["collections"].values()
                    for entry in entries if (entry.get("jurisdiction"), entry.get("right_type")) == (obligation["jurisdiction"], obligation["right_type"])]
                rows.append({"scenario_id": assessment_scenario["scenario_id"], "scenario_sha256": assessment_scenario["scenario_sha256"],
                    "jurisdiction": obligation["jurisdiction"], "right_type": obligation["right_type"], "candidate_id": "",
                    "module_id": RIGHT_MODULES[obligation["right_type"]], "title": "离线范围审阅：" + obligation["right_type"],
                    "scope": "US synthetic source-only scope", "risk": None, "assessment_status": "pending", "evidence_confidence": "低",
                    "pending_reasoning": "合成样本已完成有界公开取证；尚无足够具体权利依据评级，官方核验未完成。",
                    "reasoning": "保留实际样本来源与未知事项，不将无命中或来源访问限制当成低风险。",
                    "confidence_reasoning": "本fixture仅验收流程，不提供真实法律事实。", "evidence_refs": refs,
                    "supporting_evidence": [], "counter_evidence": [], "no_supporting_evidence_reasoning": "未取得可评级的具体冲突事实。",
                    "no_counter_evidence_reasoning": "未取得可外推到整体的排除事实。", "assumptions": [], "raise_if": [], "lower_if": [], "human_checks": []})
                if candidates["copyright_assets"] and obligation["right_type"] == "copyright" and obligation["scenario_id"] == "product_entry":
                    rows[-1].update(candidate_id="C-SYNTHETIC-ART", title="已读合成原作与产品表达重合", risk="高", assessment_status="assessed",
                        reasoning="合成原始来源描述的完整美术表达被产品复现，现有合成材料未授予复制许可；其他权利范围仍待评。",
                        supporting_evidence=[{"reasoning": "具体合成原作、复制部位与许可限制来自已留存原文和产品图。", "evidence_refs": ["EV-PUBLIC", "EV-PRODUCT"]}],
                        no_supporting_evidence_reasoning="")
                    rows[-1].pop("pending_reasoning", None)
            review = {"reviewer": "offline-" + role, "review_context": {"session_id": "separate-offline-session-" + role,
                "first_review_visible": False, "evidence_digest": work["review_work"]["evidence_digest"]},
                "coverage_confidence_cap": "低", "coverage_confidence_reasoning": "Synthetic retained evidence only; no live verification.", "assessments": rows}
            atomic_write_json(directory / (role + "-review.json"), review)
            reviews.append(review)
        reviewed = work_view_from_dir(directory, first_review=reviews[0], second_review=reviews[1])
        if reviewed["review_work"]["entries"]:
            raise AssertionError("Whole-scope review fixture is incomplete")
        if scenario == "summary_only":
            unread = [item for item in reviewed["entries"] if item.get("kind") == "agent_read"
                and item["state"] in {"ready", "awaiting_review"}]
            if not unread:
                raise AssertionError("Summary-only candidate lost its original-reading obligation")
            try:
                publish(directory, directory / "first-review.json", directory / "second-review.json", output_dir=directory / "report", mode="auto")
            except ValueError as exc:
                if "EVIDENCE_AGENT_WORK_REMAINS" not in str(exc):
                    raise
                return {"directory": str(directory), "publication_rejected": str(exc), "unread_work": unread,
                    "candidate_id": candidates["patents"][0]["candidate_id"]}
            raise AssertionError("Summary-only candidate incorrectly passed the evidence publication gate")
        outcome = publish(directory, directory / "first-review.json", directory / "second-review.json",
            output_dir=directory / "report", mode="auto")
        output_task = load_json(directory / "report/task.json")
        errors = validate_run(directory, output_task, output_dir=directory / "report")
        if errors:
            raise AssertionError(errors)
        assessment = load_json(directory / "report/assessment.json")
        if assessment["publication"]["work_view_sha256"] != reviewed["work_view_sha256"]:
            raise AssertionError("Publisher and next_work did not use the same frozen work projection")
        build_bundle(directory, output_task, evidence, assessment, candidates,
            {"schema_version": "1.0", "task_id": task["task_id"], "entries": []}, plan, output_dir=directory / "rebuilt")
        # Standalone finalization is publication eligibility, not file delivery.
        from assessment_estimate import finalize
        finalized = finalize(directory, task, directory / "first-review.json", directory / "second-review.json",
            output_dir=directory / "assessment-only", publication_mode="auto")
        if finalized["publication"]["delivery_status"] != "ready":
            raise AssertionError("Standalone finalization must not claim file delivery")
        if any((directory / "assessment-only" / name).exists() for name in
                ("report.html", "report.md", "report-data.json", "report-findings.csv", "report-manifest.json")):
            raise AssertionError("Standalone finalization unexpectedly produced a report")
        return {"directory": str(directory), "report": outcome["report"], "publication_mode": outcome["publication_mode"],
            "delivery_status": outcome["delivery_status"], "assessment_status": assessment["status"],
            "limitations": len(assessment["publication"]["limitations"]), "work_view_sha256": reviewed["work_view_sha256"]}


class EvidenceDeliveryIntegrationTests(unittest.TestCase):
    def test_whole_pipeline_uses_real_projection_and_independent_validation(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ipr-v2-integration-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture")
            self.assertEqual(result["publication_mode"], "evidence")
            self.assertEqual(result["delivery_status"], "completed")
            self.assertEqual(result["assessment_status"], "incomplete")
            self.assertGreater(result["limitations"], 0)

    def test_every_discovery_request_failed_keeps_pending_and_delivers_sources(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ipr-v2-all-failed-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture", scenario="all_discovery_failed")
            directory = Path(result["directory"])
            task, evidence, plan, assessment, report = [load_json(directory / name) for name in
                ("task.json", "evidence.json", "search-plan.json", "report/assessment.json", "report/report-data.json")]
            discovery_ids = {row["query_id"] for rows in plan["queries"].values() for row in rows if row.get("action_purpose") == "discovery"}
            failed = [run for run in evidence["source_runs"] if run["query_id"] in discovery_ids]
            self.assertTrue(discovery_ids)
            self.assertEqual({run["query_id"] for run in failed}, discovery_ids)
            self.assertTrue(all(run["status"] == "failed" and run["error_code"] == "PROVIDER_TIMEOUT" for run in failed))
            self.assertTrue(all(any(review["source_run_id"] == run["run_id"] and review["outcome"] == "blocked"
                and review["source_run_sha256"] == sha256_json(run) for review in task["discovery_followups"]) for run in failed))
            self.assertIsNone(assessment["overall"]["risk"])
            self.assertTrue(all(row["assessment_status"] == "pending" for row in assessment["assessments"]))
            self.assertEqual(report["publication"]["mode"], "evidence")
            self.assertEqual(report["publication"]["delivery_status"], "completed")
            self.assertEqual(assessment["status"], "incomplete")
            self.assertTrue(any(item["reason"] == "PROVIDER_TIMEOUT" for item in report["publication"]["limitations"]))
            self.assertFalse(assessment["overall"]["all_scope_clearance"])

    def test_primary_known_high_and_another_pending_scope_survive_delivery_together(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ipr-v2-mixed-high-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture", scenario="mixed_high")
            directory = Path(result["directory"])
            assessment = load_json(directory / "report/assessment.json")
            report = load_json(directory / "report/report-data.json")
            primary = [row for row in assessment["assessments"] if row["scenario_id"] == "product_entry"]
            high = next(row for row in primary if row["candidate_id"] == "C-SYNTHETIC-ART")
            self.assertEqual((high["risk"], high["assessment_status"]), ("高", "assessed"))
            self.assertIn("EV-PUBLIC", high["evidence_refs"])
            self.assertTrue(any(row["right_type"] == "patent" and row["risk"] is None and row["assessment_status"] == "pending" for row in primary))
            self.assertEqual(assessment["overall"]["risk"], "高")
            self.assertFalse(assessment["overall"]["all_scope_clearance"])
            self.assertEqual((report["publication"]["mode"], report["publication"]["delivery_status"]), ("evidence", "completed"))
            self.assertEqual(assessment["status"], "incomplete")

    def test_summary_only_candidate_cannot_close_unread_original_work(self):
        import tempfile
        from decision_workflow import candidate_document_entries
        with tempfile.TemporaryDirectory(prefix="ipr-v2-summary-only-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture", scenario="summary_only")
            directory = Path(result["directory"])
            task, evidence, candidates, ledger = [load_json(directory / name) for name in
                ("task.json", "evidence.json", "normalized-candidates.json", "materiality-annotations.json")]
            candidate = candidates["patents"][0]
            self.assertTrue(candidate["snippet"])
            self.assertFalse(candidate.get("claims"))
            self.assertEqual(candidate_document_entries(candidate, evidence, task=task), [])
            self.assertEqual(ledger["annotations"][0]["reading_level"], "abstract")
            self.assertEqual(ledger["annotations"][0]["decision"], "needs_info")
            self.assertIn("EVIDENCE_AGENT_WORK_REMAINS", result["publication_rejected"])
            self.assertTrue(result["unread_work"])
            self.assertTrue(all(item["required_facts"] == ["protection_content"] for item in result["unread_work"]))
            for name in ("assessment.json", "report.html", "report.md", "report-data.json", "report-findings.csv", "report-manifest.json"):
                self.assertFalse((directory / "report" / name).exists())

    def test_reviewed_browser_scope_limit_delivers_without_hiding_known_high(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ipr-v2-browser-scope-high-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture", scenario="browser_scope_high")
            directory = Path(result["directory"])
            assessment = load_json(directory / "report/assessment.json")
            plan = load_json(directory / "search-plan.json")
            rows = [row for row in plan["queries"]["uspto_patent_browser"] if row["right_type"] == "patent"]
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["search_dimension"] == "text" for row in rows))
            limits = assessment["publication"]["limitations"]
            classification = next(row for row in limits if row.get("right_type") == "patent"
                and ":AXIS_MISSING:classification" in str(row.get("planning_gap")))
            self.assertTrue(any(item.get("reason") == "API_DISCOVERY_BROWSER_SCOPE_LIMIT" for item in classification["route_limit_refs"]))
            self.assertEqual(assessment["overall"]["risk"], "高")
            self.assertTrue(any(row["scenario_id"] == "product_entry" and row["right_type"] == "patent"
                and row["assessment_status"] == "pending" for row in assessment["assessments"]))
            self.assertEqual(result["publication_mode"], "evidence")
            self.assertEqual(result["delivery_status"], "completed")

    def test_exhausted_browser_failures_deliver_sources_with_known_high_and_pending(self):
        import tempfile
        from runtime_v24 import source_files_complete
        with tempfile.TemporaryDirectory(prefix="ipr-v2-browser-scope-failed-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture", scenario="browser_scope_failed")
            directory = Path(result["directory"])
            evidence, plan, assessment = [load_json(directory / name) for name in
                ("evidence.json", "search-plan.json", "report/assessment.json")]
            patent_rows = [row for row in plan["queries"]["uspto_patent_browser"] if row["right_type"] == "patent"]
            self.assertEqual(len(patent_rows), 2)
            for row in patent_rows:
                runs = [run for run in evidence["source_runs"] if run["query_id"] == row["query_id"]]
                self.assertEqual(len(runs), 2)
                self.assertTrue(all(run["status"] == "failed" and run["submission_state"] == "submitted"
                    and run["error_code"] == "BROWSER_SEMANTIC_TIMEOUT" and source_files_complete(directory, evidence, run) for run in runs))
            classification = next(row for row in assessment["publication"]["limitations"] if row.get("right_type") == "patent"
                and ":AXIS_MISSING:classification" in str(row.get("planning_gap")))
            bound = next(item for item in classification["route_limit_refs"] if item["provider"] == "uspto_patent_browser")
            self.assertEqual(bound["reason"], "API_DISCOVERY_BROWSER_SCOPE_LIMIT")
            self.assertTrue(all(item["recovery_limit"]["reason"] == "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED"
                and item["recovery_limit"]["remaining_attempts"] == 0 for item in bound["attempts"]))
            self.assertEqual(assessment["overall"]["risk"], "高")
            self.assertTrue(any(row["scenario_id"] == "product_entry" and row["right_type"] == "patent"
                and row["assessment_status"] == "pending" for row in assessment["assessments"]))
            self.assertEqual((result["publication_mode"], result["delivery_status"], assessment["status"]),
                ("evidence", "completed", "incomplete"))

    def test_audited_unknown_slot_delivers_impact_but_does_not_clear_or_repeat_request(self):
        import tempfile
        from api_first_planning import dispatch_block
        with tempfile.TemporaryDirectory(prefix="ipr-v2-browser-scope-unknown-") as root:
            result = build_evidence_delivery_fixture(Path(root) / "fixture", scenario="browser_scope_unknown")
            directory = Path(result["directory"])
            task, evidence, plan, candidates, ledger, assessment = [load_json(directory / name) for name in
                ("task.json", "evidence.json", "search-plan.json", "normalized-candidates.json", "materiality-annotations.json", "report/assessment.json")]
            unknown = [run for run in evidence["source_runs"] if run["submission_state"] == "unknown"]
            self.assertEqual(len(unknown), 1)
            run = unknown[0]
            row = next(row for row in plan["queries"][run["provider"]] if row["query_id"] == run["query_id"])
            self.assertEqual(dispatch_block(task, plan, evidence, candidates, ledger, run["provider"], row),
                "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY")
            self.assertEqual(len([item for item in evidence["source_runs"] if item["query_id"] == row["query_id"]]), 1)
            classification = next(item for item in assessment["publication"]["limitations"] if item.get("right_type") == "patent"
                and ":AXIS_MISSING:classification" in str(item.get("planning_gap")))
            bound = next(item for item in classification["route_limit_refs"] if item["provider"] == "uspto_patent_browser")
            self.assertEqual(bound["reason"], "API_DISCOVERY_BROWSER_SCOPE_RESERVED_FOR_UNKNOWN_SUBMISSION")
            self.assertEqual((bound["known_attempt_slots"], bound["unknown_reserved_slots"]), (1, 1))
            reserved = next(item for item in bound["attempts"] if item.get("submission_reservation"))
            self.assertFalse(reserved["submission_reservation"]["completed_search"])
            self.assertNotIn("recovery_limit", reserved)
            self.assertEqual(assessment["overall"]["risk"], "高")
            self.assertFalse(assessment["overall"]["all_scope_clearance"])
            self.assertEqual((result["publication_mode"], result["delivery_status"], assessment["status"]),
                ("evidence", "completed", "incomplete"))

    def test_failed_file_validation_never_returns_completed_delivery(self):
        import tempfile
        from unittest.mock import patch
        from publish_report import publish
        with tempfile.TemporaryDirectory(prefix="ipr-v2-failed-delivery-") as root:
            directory = Path(root) / "fixture"
            build_evidence_delivery_fixture(directory)
            with isolated_test_environment(), patch("report_estimate.validate_run", return_value=["SYNTHETIC_FILE_VALIDATION_FAILURE"]):
                with self.assertRaisesRegex(ValueError, "VALIDATION_FAILED"):
                    publish(directory, directory / "first-review.json", directory / "second-review.json",
                        output_dir=directory / "failed-report", mode="auto")
            saved = load_json(directory / "failed-report" / "assessment.json")
            self.assertEqual(saved["publication"]["delivery_status"], "ready")
            for name in ("report.html", "report.md", "report-data.json", "report-findings.csv", "report-manifest.json"):
                self.assertFalse((directory / "failed-report" / name).exists())


if __name__ == "__main__":
    unittest.main()
