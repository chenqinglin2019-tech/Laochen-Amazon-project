#!/usr/bin/env python3
"""Focused offline regressions for candidate reachability and formal-risk gates."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from annotate_materiality import (
    apply_materiality_annotations, candidate_identity_fingerprint,
    empty_materiality_ledger, materiality_ledger_errors,
)
from common import (
    FREE_POLICY_REVISION, MODULE_IDS, active_free_policy, build_coverage_requirements,
    now_iso, sha256_json,
)
from finalize_assessment import (
    coverage_requirement_gaps, material_unverified, official_verification_complete,
    validate_review, verification_plan_binding_errors,
)
from merge_candidates import (
    append_public_web_candidate_verification_actions, apply_candidate_contract,
    dynamic_candidate_action_ids, merge,
    prune_dynamic_candidate_actions,
)
from report_v2 import assessment_module_errors, candidate_rows
import record_registry_browser as registry_recorder
from record_registry_browser import jpo_verification_already_complete


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def annotate(
    task: dict[str, Any], candidates: dict[str, Any],
    decisions: dict[str, tuple[bool, str]],
) -> dict[str, Any]:
    ledger = empty_materiality_ledger(str(task["task_id"]))
    indexed = {
        str(item["candidate_id"]): (collection, item)
        for collection in ("patents", "trademarks", "copyright_assets", "enforcement")
        for item in candidates.get(collection, [])
    }
    for index, (candidate_id, (material, reason)) in enumerate(decisions.items(), 1):
        collection, item = indexed[candidate_id]
        decision = "material" if material else "excluded"
        ledger["annotations"].append({
            "annotation_id": f"MAT-FOCUSED-{index}",
            "candidate_id": candidate_id,
            "candidate_identity_fingerprint": candidate_identity_fingerprint(collection, item),
            "material": material,
            "decision": decision,
            "material_reason": reason,
            "reviewer": "focused-test-reviewer",
            "annotated_at": now_iso(),
        })
    apply_materiality_annotations(ledger, str(task["task_id"]), candidates)
    assert materiality_ledger_errors(ledger, str(task["task_id"]), candidates) == []
    return ledger


def verification(
    checked_at: str, *, identity_match: bool, authority: str, url: str,
) -> dict[str, Any]:
    return {
        "status": "verified" if identity_match else "identity_mismatch",
        "authority": authority,
        "method": "official_free_lookup",
        "identity_match": identity_match,
        "legal_status": "active",
        "owner": ["Example Owner"],
        "classes": [],
        "media": [],
        "url": url,
        "checked_at": checked_at,
    }


def test_public_candidate_chain() -> None:
    runs = {
        "RUN-COPY": {
            "run_id": "RUN-COPY", "provider": "public_web_browser",
            "operation": "copyright_recall", "jurisdiction": "US",
            "right_type": "copyright", "status": "success",
        },
        "RUN-ENF": {
            "run_id": "RUN-ENF", "provider": "public_web_browser",
            "operation": "enforcement_recall", "jurisdiction": "US",
            "right_type": "enforcement", "status": "success",
        },
        "RUN-SERPER": {
            "run_id": "RUN-SERPER", "provider": "serper_images",
            "operation": "images", "jurisdiction": "US",
            "right_type": "copyright", "status": "success",
            "authoritative_for_final_rating": False,
        },
    }
    copyright_entries = [{
        "evidence_id": "EV-COPY", "source_run_id": "RUN-COPY",
        "provider": "public_web_browser", "operation": "copyright_recall",
        "jurisdiction": "US", "right_type": "copyright",
        "payload": {"candidates": [{
            "record_number": "VA0000123456", "title": "Registered artwork",
            "owner": "Example Owner", "jurisdiction": "US",
        }]},
    }, {
        "evidence_id": "EV-SERPER", "source_run_id": "RUN-SERPER",
        "provider": "serper_images", "operation": "images",
        "jurisdiction": "US", "right_type": "copyright",
        "payload": {"candidates": [{
            "title": "Unverified similar image", "jurisdiction": "US",
            "url": "https://example.invalid/image-result",
            "authoritative_for_final_rating": False,
            # A third-party row cannot self-promote itself to official evidence.
            "official_verification": verification(
                now_iso(), identity_match=True, authority="Serper",
                url="https://example.invalid/image-result",
            ),
        }]},
    }]
    enforcement_entries = [{
        "evidence_id": "EV-ENF", "source_run_id": "RUN-ENF",
        "provider": "public_web_browser", "operation": "enforcement_recall",
        "jurisdiction": "US", "right_type": "enforcement",
        "payload": {"candidates": [{
            "case_number": "TTAB-123", "title": "Public proceeding",
            "owner": "Example Owner", "jurisdiction": "US",
        }]},
    }]

    copyright_assets = merge("copyright", copyright_entries, runs)
    enforcement = merge("enforcement", enforcement_entries, runs)
    apply_candidate_contract("copyright", copyright_assets)
    apply_candidate_contract("enforcement", enforcement)
    assert len(copyright_assets) == 2 and len(enforcement) == 1
    assert all(item["right_type"] == "copyright" for item in copyright_assets)
    assert all(item["module"] == "copyright_ip" for item in copyright_assets)
    serper_row = next(item for item in copyright_assets if item.get("role") == "discovery_only")
    assert serper_row["official_verification"]["status"] == "not_checked"
    assert serper_row["official_verification"]["authority"] == ""
    assert enforcement[0]["right_type"] == "enforcement"
    assert enforcement[0]["module"] == "enforcement"

    task = {
        "schema_version": "2.3-free", "task_id": "TASK-PUBLIC-CANDIDATES",
        "target_jurisdictions": ["US"], "free_policy": active_free_policy(),
        "free_policy_revision": FREE_POLICY_REVISION,
        "coverage_requirements": build_coverage_requirements(["US"]),
    }
    candidates = {
        "patents": [], "trademarks": [],
        "copyright_assets": copyright_assets, "enforcement": enforcement,
    }
    ids = [item["candidate_id"] for item in [*copyright_assets, *enforcement]]
    ledger_errors = materiality_ledger_errors(
        empty_materiality_ledger(task["task_id"]), task["task_id"], candidates,
    )
    assert {error.rsplit(": ", 1)[-1] for error in ledger_errors} >= set(ids)

    annotate(task, candidates, {
        copyright_assets[0]["candidate_id"]: (True, "官方记录与当前素材可能相关"),
        copyright_assets[1]["candidate_id"]: (True, "第三方相似图片需要官方核验"),
        enforcement[0]["candidate_id"]: (False, "程序主体与当前商品无关"),
    })
    assert set(material_unverified(
        candidates, strict=True, evidence={"source_runs": [], "collections": {}},
        task=task,
    )) == {
        copyright_assets[0]["candidate_id"], copyright_assets[1]["candidate_id"],
    }
    rows = candidate_rows(candidates)
    assert len(rows) == 3
    assert {row["module_id"] for row in rows} == {"copyright_ip", "enforcement"}


def test_public_candidate_verification_actions() -> None:
    with tempfile.TemporaryDirectory(prefix="lc-ipr-public-candidate-") as temporary:
        task_dir = Path(temporary)
        task = {
            "schema_version": "2.3-free", "task_id": "TASK-PUBLIC-VERIFY",
            "target_jurisdictions": ["US"], "free_policy": active_free_policy(),
            "free_policy_revision": FREE_POLICY_REVISION,
            "coverage_requirements": build_coverage_requirements(["US"]),
        }
        verification_requirements = {
            item["requirement_id"]: item
            for item in task["coverage_requirements"]
            if item.get("phase") == "candidate_verification"
            and item.get("right_type") in {"copyright", "enforcement"}
        }
        assert set(verification_requirements) == {
            "COV-US-COPYRIGHT-VERIFY", "COV-US-ENFORCEMENT-VERIFY",
        }
        assert all(item["routes"] == [{
            "provider": "public_web_browser", "operation": "candidate_verification",
            "method": "manual_capture", "priority": 1,
        }] for item in verification_requirements.values())

        runs = {
            "RUN-COPY-VERIFY": {
                "provider": "public_web_browser", "operation": "copyright_recall",
                "jurisdiction": "US", "right_type": "copyright", "status": "success",
                "request_params": {"source_key": "copyright_records"},
            },
            "RUN-ENF-VERIFY": {
                "provider": "public_web_browser", "operation": "enforcement_recall",
                "jurisdiction": "US", "right_type": "enforcement", "status": "success",
                "request_params": {"source_key": "ptab"},
            },
        }
        copyright_assets = merge("copyright", [{
            "evidence_id": "EV-COPY-VERIFY", "source_run_id": "RUN-COPY-VERIFY",
            "provider": "public_web_browser", "operation": "copyright_recall",
            "jurisdiction": "US", "right_type": "copyright",
            "payload": {"candidates": [{
                "record_number": "VA 2-345-678", "title": "Registered artwork",
                "jurisdiction": "US", "material": True,
            }]},
        }], runs)
        enforcement = merge("enforcement", [{
            "evidence_id": "EV-ENF-VERIFY", "source_run_id": "RUN-ENF-VERIFY",
            "provider": "public_web_browser", "operation": "enforcement_recall",
            "jurisdiction": "US", "right_type": "enforcement",
            "payload": {"candidates": [{
                "case_number": "IPR2026-00123", "title": "PTAB proceeding",
                "jurisdiction": "US", "material": True,
            }]},
        }], runs)
        apply_candidate_contract("copyright", copyright_assets)
        apply_candidate_contract("enforcement", enforcement)
        assert copyright_assets[0]["sources"][0]["source_key"] == "copyright_records"
        assert enforcement[0]["sources"][0]["source_key"] == "ptab"
        write_json(task_dir / "search-plan.json", {
            "schema_version": "2.3-free", "task_id": task["task_id"], "queries": {},
        })
        append_public_web_candidate_verification_actions(
            task_dir, task, copyright_assets, enforcement,
        )
        plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
        actions = plan["queries"]["public_web_browser"]
        assert len(actions) == 2
        expected = {
            "copyright": ("VA 2-345-678", "copyright_records", "COV-US-COPYRIGHT-VERIFY"),
            "enforcement": ("IPR2026-00123", "ptab", "COV-US-ENFORCEMENT-VERIFY"),
        }
        for action in actions:
            record, source_key, requirement_id = expected[action["right_type"]]
            candidate = copyright_assets[0] if action["right_type"] == "copyright" else enforcement[0]
            assert action["q"] == record and action["record_number"] == record
            assert action["candidate_id"] == candidate["candidate_id"]
            assert action["jurisdiction"] == "US"
            assert action["source_key"] == source_key
            assert action["requirement_ids"] == [requirement_id]
            assert action["operation"] == "candidate_verification"
            assert action["mode"] == "manual_capture" and action["required_for"] == "formal"

        missing_copyright = {
            "title": "Similar artwork without an official number",
            "jurisdiction": "US", "right_type": "copyright",
            "source_key": "copyright_records", "material": True,
        }
        missing_enforcement = {
            "title": "Proceeding mentioned without its docket",
            "jurisdiction": "US", "right_type": "enforcement",
            "source_key": "ptab", "case_number": "unknown", "material": True,
        }
        apply_candidate_contract("copyright", [missing_copyright])
        apply_candidate_contract("enforcement", [missing_enforcement])
        append_public_web_candidate_verification_actions(
            task_dir, task, [missing_copyright], [missing_enforcement],
        )
        plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
        assert len(plan["queries"]["public_web_browser"]) == 2
        missing_ids = {
            missing_copyright["candidate_id"], missing_enforcement["candidate_id"],
        }
        assert not any(
            row.get("candidate_id") in missing_ids
            for row in plan["queries"]["public_web_browser"]
        )
        gaps = [
            gap for gap in task["coverage_gaps"]
            if gap.get("error_code") == "PUBLIC_RECORD_IDENTIFIER_REQUIRED"
        ]
        assert {gap["candidate_id"] for gap in gaps} == missing_ids
        assert all(
            gap["status"] == "needs_user_action"
            and gap["operation"] == "candidate_verification"
            and gap["query_id"] == ""
            and gap["requirement_id"] in {
                "COV-US-COPYRIGHT-VERIFY", "COV-US-ENFORCEMENT-VERIFY",
            }
            and gap["user_action"]["next_operation"] in {
                "copyright_recall", "enforcement_recall",
            }
            and gap["user_action"]["required_capture_binding"] == {
                "candidate_id": gap["candidate_id"],
            }
            and "candidate_id" in gap["user_action"]["do_not_infer_from"]
            for gap in gaps
        )
        checkpoint = task["checkpoints"]["public_record_identifier_resolution"]
        assert checkpoint["status"] == "needs_user_action" and checkpoint["pending"] == 2

        # Once exact official numbers are observed, rerunning merge planning
        # clears the identifier gaps and creates source-bound verification rows.
        missing_copyright["registration_number"] = "TX 9-876-543"
        missing_enforcement["case_number"] = "IPR2026-00999"
        append_public_web_candidate_verification_actions(
            task_dir, task, [missing_copyright], [missing_enforcement],
        )
        plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
        new_actions = [
            row for row in plan["queries"]["public_web_browser"]
            if row.get("candidate_id") in missing_ids
        ]
        assert len(new_actions) == 2
        assert {row["q"] for row in new_actions} == {
            "TX 9-876-543", "IPR2026-00999",
        }
        assert not any(
            gap.get("error_code") == "PUBLIC_RECORD_IDENTIFIER_REQUIRED"
            for gap in task["coverage_gaps"]
        )
        checkpoint = task["checkpoints"]["public_record_identifier_resolution"]
        assert checkpoint["status"] == "success" and checkpoint["actions"] == []


def test_evidence_backed_medium_high_gate() -> None:
    digest = "d" * 64
    review = {
        "reviewer": "focused-reviewer",
        "modules": {
            module_id: {
                "risk": "低", "confidence": "中", "reasoning": "固定说明",
                "findings": [],
            }
            for module_id in MODULE_IDS
        },
        "review_triggers": {},
        "compound_escalation": {"enabled": False, "justification": ""},
        "review_context": {
            "session_id": "focused-session", "evidence_digest": digest,
            "first_review_visible": False,
        },
    }
    validate_review(review, {"EV-1"}, digest)
    review["modules"]["utility_patent"]["risk"] = "中"
    try:
        validate_review(
            review, {"EV-1"}, digest,
            formal_risk_evidence={module_id: set() for module_id in MODULE_IDS},
        )
    except ValueError as exc:
        assert "exact planned official candidate verification" in str(exc)
    else:
        raise AssertionError("an evidence-free medium-risk module was accepted")

    finding = {
        "finding_id": "F-1", "title": "证据发现",
        "recommended_action": "人工复核", "evidence_refs": ["EV-1"],
    }
    review["modules"]["utility_patent"]["findings"] = [finding]
    empty_formal = {module_id: set() for module_id in MODULE_IDS}
    try:
        validate_review(
            review, {"EV-1"}, digest, formal_risk_evidence=empty_formal,
        )
    except ValueError as exc:
        assert "exact planned official candidate verification" in str(exc)
    else:
        raise AssertionError("discovery-only evidence supported a formal medium-risk conclusion")
    formal = {module_id: set() for module_id in MODULE_IDS}
    formal["utility_patent"] = {"EV-1"}
    validate_review(review, {"EV-1"}, digest, formal_risk_evidence=formal)
    review["modules"]["utility_patent"].update({"risk": "低", "findings": [finding]})
    review["compound_escalation"] = {
        "enabled": True, "justification": "组合效应", "evidence_refs": [],
    }
    try:
        validate_review(review, {"EV-1"}, digest, formal_risk_evidence=formal)
    except ValueError as exc:
        assert "compound escalation" in str(exc)
    else:
        raise AssertionError("an unreferenced compound escalation was accepted")
    review["compound_escalation"]["evidence_refs"] = ["EV-1"]
    validate_review(review, {"EV-1"}, digest, formal_risk_evidence=formal)

    assessment = {
        "status": "completed", "overall": {"risk": "中"},
        "modules": {
            module_id: {
                "risk": "低", "confidence": "中", "reasoning": "固定说明",
                "findings": [],
            }
            for module_id in MODULE_IDS
        },
    }
    assert any(
        "overall risk requires formally eligible evidence-backed findings" in error
        for error in assessment_module_errors(
            assessment, known_evidence={"EV-1"}, formal_risk_evidence=empty_formal,
        )
    )

    candidate = {
        "candidate_id": "C-EXACT-PLAN", "right_type": "patent",
        "jurisdiction": "US", "publication_number": "US1234567A1",
        "official_verification": verification(
            now_iso(), identity_match=True, authority="USPTO",
            url="https://ppubs.uspto.gov/pubwebapp/external.html?q=US1234567A1",
        ),
        "verification_refs": ["EV-EXACT-PLAN"],
    }
    plan_row = {
        "query_id": "QRY-EXACT-PLAN", "q": "US1234567A1",
        "candidate_id": "C-EXACT-PLAN", "right_type": "patent",
        "record_number": "US1234567A1", "operation": "candidate_verification",
        "jurisdiction": "US", "required": False, "required_for": "formal",
        "requirement_ids": ["COV-US-PATENT-VERIFY"], "wave": 2,
        "derived_from": ["normalized-candidates:C-EXACT-PLAN"],
        "execute_by_default": True,
    }
    plan_digest = sha256_json(plan_row)
    run = {
        "run_id": "RUN-EXACT-PLAN", "query_id": "QRY-EXACT-PLAN",
        "provider": "uspto_patent_browser", "operation": "candidate_verification",
        "query": "US1234567A1", "jurisdiction": "US", "right_type": "patent",
        "status": "success", "requirement_ids": ["COV-US-PATENT-VERIFY"],
        "request_params": {
            "candidate_id": "C-EXACT-PLAN", "right_type": "patent",
            "record_number": "US1234567A1",
        },
        "plan_entry_sha256": plan_digest,
    }
    entry = {
        "evidence_id": "EV-EXACT-PLAN", "source_run_id": "RUN-EXACT-PLAN",
        "query_id": "QRY-EXACT-PLAN", "provider": "uspto_patent_browser",
        "operation": "candidate_verification", "jurisdiction": "US",
        "right_type": "patent", "requirement_ids": ["COV-US-PATENT-VERIFY"],
        "plan_entry_sha256": plan_digest,
        "payload": json.loads(json.dumps(candidate)),
    }
    exact_plan = {"queries": {"uspto_patent_browser": [plan_row]}}
    exact_evidence = {
        "source_runs": [run], "collections": {"official_verifications": [entry]},
    }
    call = {
        "strict": True, "evidence": exact_evidence,
        "allowed_routes": [{
            "provider": "uspto_patent_browser", "operation": "candidate_verification",
        }],
        "jurisdiction": "US", "right_type": "patent",
        "requirement_ids": {"COV-US-PATENT-VERIFY"},
    }
    assert official_verification_complete(candidate, search_plan=exact_plan, **call)
    task = {
        "schema_version": "2.3-free", "task_id": "TASK-EXACT-PLAN",
        "target_jurisdictions": ["US"], "free_policy": active_free_policy(),
        "free_policy_revision": FREE_POLICY_REVISION,
        "coverage_requirements": build_coverage_requirements(["US"]),
    }
    assert verification_plan_binding_errors(
        task, exact_evidence, {"patents": [candidate], "trademarks": []}, exact_plan,
    ) == []
    candidate["material"] = True
    assert "COV-US-PATENT-VERIFY" not in coverage_requirement_gaps(
        task, exact_evidence, {"patents": [candidate], "trademarks": []}, exact_plan,
    )
    unplanned = json.loads(json.dumps(exact_plan))
    unplanned["queries"]["uspto_patent_browser"][0]["query_id"] = "QRY-OTHER"
    assert not official_verification_complete(candidate, search_plan=unplanned, **call)
    assert "COV-US-PATENT-VERIFY" in coverage_requirement_gaps(
        task, exact_evidence, {"patents": [candidate], "trademarks": []}, unplanned,
    )
    original_official = json.loads(json.dumps(candidate["official_verification"]))
    candidate["official_verification"]["owner"] = ["Forged report owner"]
    assert any(
        "top-level official_verification" in error
        for error in verification_plan_binding_errors(
            task, exact_evidence, {"patents": [candidate], "trademarks": []}, exact_plan,
        )
    )
    candidate["official_verification"] = {"status": "not_checked"}
    assert any(
        "top-level official_verification" in error
        for error in verification_plan_binding_errors(
            task, exact_evidence, {"patents": [candidate], "trademarks": []}, exact_plan,
        )
    )
    candidate["official_verification"] = original_official
    entry.pop("plan_entry_sha256")
    assert not official_verification_complete(candidate, search_plan=exact_plan, **call)


def test_excluded_mismatch_action_is_repairable() -> None:
    with tempfile.TemporaryDirectory(prefix="lc-ipr-candidate-gate-") as temporary:
        task_dir = Path(temporary)
        task = {
            "schema_version": "2.3-free", "task_id": "TASK-MISMATCH-REPAIR",
            "target_jurisdictions": ["JP"], "free_policy": active_free_policy(),
            "free_policy_revision": FREE_POLICY_REVISION,
            "coverage_requirements": build_coverage_requirements(["JP"]),
        }
        candidate = {
            "candidate_id": "CAND-MISMATCH-REPAIR", "jurisdiction": "JP",
            "right_type": "patent", "application_number": "2020008423",
            "normalization_key": "JP:patent:JP2020008423A",
            "module": "utility_patent", "module_id": "utility_patent",
            "material": False, "disposition": "unreviewed",
            "verification_refs": ["EV-MISMATCH"],
        }
        candidates = {
            "patents": [candidate], "trademarks": [],
            "copyright_assets": [], "enforcement": [],
        }
        annotate(task, candidates, {
            candidate["candidate_id"]: (False, "技术特征与当前商品不一致"),
        })
        checked = datetime.now(timezone.utc).replace(microsecond=0)
        mismatch = verification(
            (checked - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            identity_match=False, authority="Japan Patent Office",
            url="https://ip-data.jpo.go.jp/api/patent/v1/app_progress/2020008423",
        )
        candidate["official_verification"] = mismatch
        run = {
            "run_id": "RUN-MISMATCH", "query_id": "QRY-MISMATCH",
            "provider": "jpo_api", "operation": "candidate_verification",
            "jurisdiction": "JP", "right_type": "patent", "status": "success",
            "requirement_ids": ["COV-JP-PATENT-VERIFY"],
            "request_params": {
                "candidate_id": candidate["candidate_id"], "number": "2020008423",
            },
            "source_environment": "production", "authoritative_for_final_rating": True,
        }
        entry = {
            "evidence_id": "EV-MISMATCH", "source_run_id": "RUN-MISMATCH",
            "query_id": "QRY-MISMATCH", "provider": "jpo_api",
            "operation": "candidate_verification", "jurisdiction": "JP",
            "right_type": "patent", "requirement_ids": ["COV-JP-PATENT-VERIFY"],
            "payload": {
                "candidate_id": candidate["candidate_id"], "right_type": "patent",
                "application_number": "2020008423", "official_verification": mismatch,
            },
        }
        evidence = {
            "source_runs": [run], "collections": {"official_verifications": [entry]},
        }
        assert dynamic_candidate_action_ids(task, evidence, candidates) == {
            candidate["candidate_id"],
        }
        action = {
            "query_id": "QRY-DYNAMIC", "operation": "candidate_verification",
            "candidate_id": candidate["candidate_id"],
            "derived_from": [f"normalized-candidates:{candidate['candidate_id']}"],
        }
        write_json(task_dir / "search-plan.json", {"queries": {"jpo_api": [action]}})
        prune_dynamic_candidate_actions(task_dir, task, evidence, candidates)
        plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
        assert plan["queries"]["jpo_api"] == [action]

        matched = verification(
            (checked - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            identity_match=True, authority="J-PlatPat",
            url="https://www.j-platpat.inpit.go.jp/",
        )
        candidate["official_verification"] = matched
        candidate["verification_refs"].append("EV-MATCHED")
        evidence["source_runs"].append({
            "run_id": "RUN-MATCHED", "query_id": "QRY-MATCHED",
            "provider": "jplatpat_browser", "operation": "candidate_verification",
            "jurisdiction": "JP", "right_type": "patent", "status": "success",
            "requirement_ids": ["COV-JP-PATENT-VERIFY"],
            "request_params": {
                "candidate_id": candidate["candidate_id"], "record_number": "2020008423",
            },
        })
        evidence["collections"]["official_verifications"].append({
            "evidence_id": "EV-MATCHED", "source_run_id": "RUN-MATCHED",
            "query_id": "QRY-MATCHED", "provider": "jplatpat_browser",
            "operation": "candidate_verification", "jurisdiction": "JP",
            "right_type": "patent", "requirement_ids": ["COV-JP-PATENT-VERIFY"],
            "payload": {
                "candidate_id": candidate["candidate_id"], "right_type": "patent",
                "application_number": "2020008423", "official_verification": matched,
            },
        })
        verification_requirement = next(
            requirement for requirement in task["coverage_requirements"]
            if requirement["requirement_id"] == "COV-JP-PATENT-VERIFY"
        )
        assert official_verification_complete(
            candidate, strict=True, evidence=evidence,
            allowed_routes=verification_requirement["routes"], jurisdiction="JP",
            right_type="patent", requirement_ids={"COV-JP-PATENT-VERIFY"},
        )
        evidence["collections"]["official_verifications"][-1]["query_id"] = "QRY-OTHER"
        assert not official_verification_complete(
            candidate, strict=True, evidence=evidence,
            allowed_routes=verification_requirement["routes"], jurisdiction="JP",
            right_type="patent", requirement_ids={"COV-JP-PATENT-VERIFY"},
        )
        evidence["collections"]["official_verifications"][-1]["query_id"] = "QRY-MATCHED"
        evidence["source_runs"][-1]["request_params"]["candidate_id"] = "CAND-OTHER"
        assert not official_verification_complete(
            candidate, strict=True, evidence=evidence,
            allowed_routes=verification_requirement["routes"], jurisdiction="JP",
            right_type="patent", requirement_ids={"COV-JP-PATENT-VERIFY"},
        )
        evidence["source_runs"][-1]["request_params"]["candidate_id"] = candidate["candidate_id"]
        assert dynamic_candidate_action_ids(task, evidence, candidates) == set()
        executed_action = {
            "query_id": "QRY-MATCHED", "operation": "candidate_verification",
            "candidate_id": candidate["candidate_id"],
            "derived_from": [f"normalized-candidates:{candidate['candidate_id']}"],
        }
        plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
        plan["queries"]["jplatpat_browser"] = [executed_action]
        write_json(task_dir / "search-plan.json", plan)
        prune_dynamic_candidate_actions(task_dir, task, evidence, candidates)
        plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
        assert "jpo_api" not in plan["queries"]
        assert plan["queries"]["jplatpat_browser"] == [executed_action]


def test_registry_verification_records_planned_query() -> None:
    with tempfile.TemporaryDirectory(prefix="lc-ipr-registry-query-") as temporary:
        task_dir = Path(temporary)
        task = {
            "schema_version": "2.3-free", "task_id": "TASK-REGISTRY-QUERY",
            "target_jurisdictions": ["JP"], "free_policy": active_free_policy(),
            "free_policy_revision": FREE_POLICY_REVISION,
            "coverage_requirements": build_coverage_requirements(["JP"]),
        }
        requirement_id = next(
            requirement["requirement_id"]
            for requirement in task["coverage_requirements"]
            if requirement.get("jurisdiction") == "JP"
            and requirement.get("right_type") == "patent"
            and requirement.get("phase") == "candidate_verification"
        )
        planned_query = "JP 2020-008423"
        plan_entry = {
            "query_id": "QRY-REGISTRY-FORMAT", "q": planned_query,
            "candidate_id": "CAND-REGISTRY-FORMAT", "right_type": "patent",
            "mode": "user_assisted", "operation": "candidate_verification",
            "jurisdiction": "JP", "required": False, "required_for": "formal",
            "requirement_ids": [requirement_id], "wave": 1,
            "derived_from": ["normalized-candidates:CAND-REGISTRY-FORMAT"],
        }
        write_json(task_dir / "task.json", task)
        write_json(task_dir / "search-plan.json", {
            "queries": {"jplatpat_browser": [plan_entry]},
        })
        capture_path = task_dir / "capture.json"
        write_json(capture_path, {
            "provider": "jplatpat_browser", "operation": "candidate_verification",
            "right_type": "patent", "jurisdiction": "JP", "status": "success",
            "query_id": plan_entry["query_id"],
            "candidate_id": plan_entry["candidate_id"],
            "record_number": "JP2020008423", "page_record_number": "JP2020008423",
        })
        recorded: dict[str, Any] = {}

        def fake_record_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
            recorded.update(kwargs)
            return {"status": "success", "run_id": "RUN-REGISTRY-FORMAT"}

        argv = [
            "record_registry_browser.py", "--task-dir", str(task_dir),
            "--provider", "jplatpat_browser", "--capture", str(capture_path),
            "--operation", "candidate_verification", "--right-type", "patent",
            "--jurisdiction", "JP", "--record", "JP2020008423",
            "--candidate-id", plan_entry["candidate_id"],
            "--query-id", plan_entry["query_id"],
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                registry_recorder, "_common_capture",
                return_value=("https://www.j-platpat.inpit.go.jp/", now_iso(), "cdp", {}),
            ),
            patch.object(registry_recorder, "_terms_review", return_value={}),
            patch.object(
                registry_recorder, "_normalize_success_verification",
                return_value={"candidate_id": plan_entry["candidate_id"]},
            ),
            patch.object(registry_recorder, "record_result", side_effect=fake_record_result),
        ):
            registry_recorder.main()

        assert recorded["query"] == planned_query
        assert recorded["request_params"]["q"] == planned_query


def test_jplatpat_skip_requires_exact_jpo_plan() -> None:
    with tempfile.TemporaryDirectory(prefix="lc-ipr-jpo-skip-plan-") as temporary:
        task_dir = Path(temporary)
        task = {
            "schema_version": "2.3-free", "task_id": "TASK-JPO-SKIP-PLAN",
            "target_jurisdictions": ["JP"], "free_policy": active_free_policy(),
            "free_policy_revision": FREE_POLICY_REVISION,
            "coverage_requirements": build_coverage_requirements(["JP"]),
        }
        requirement_id = "COV-JP-PATENT-VERIFY"
        candidate_id = "CAND-JPO-SKIP-PLAN"
        planned_query = "2020008423"
        plan_entry = {
            "query_id": "QRY-JPO-SKIP-PLAN", "q": planned_query,
            "number": planned_query, "number_kind": "application",
            "candidate_id": candidate_id, "right_type": "patent",
            "operation": "candidate_verification", "jurisdiction": "JP",
            "required": False, "required_for": "formal", "wave": 1,
            "derived_from": [f"normalized-candidates:{candidate_id}"],
            "requirement_ids": [requirement_id], "execute_by_default": True,
            "fallback_provider": "jplatpat_browser",
        }
        plan = {"queries": {"jpo_api": [plan_entry]}}
        plan_digest = sha256_json(plan_entry)
        official = verification(
            now_iso(), identity_match=True, authority="Japan Patent Office (JPO)",
            url="https://ip-data.jpo.go.jp/api/patent/v1/app_progress/2020008423",
        )
        candidate = {
            "candidate_id": candidate_id, "jurisdiction": "JP",
            "right_type": "patent", "application_number": planned_query,
            "material": True, "verification_refs": ["EV-JPO-SKIP-PLAN"],
            "official_verification": official,
        }
        run = {
            "run_id": "RUN-JPO-SKIP-PLAN", "query_id": plan_entry["query_id"],
            "provider": "jpo_api", "operation": "candidate_verification",
            "query": planned_query, "jurisdiction": "JP", "right_type": "patent",
            "status": "success", "requirement_ids": [requirement_id],
            "request_params": {
                "number": planned_query, "number_kind": "application",
                "candidate_id": candidate_id, "right_type": "patent",
            },
            "source_environment": "production", "authoritative_for_final_rating": True,
            "plan_entry_sha256": plan_digest,
        }
        evidence = {
            "source_runs": [run], "collections": {"official_verifications": [{
                "evidence_id": "EV-JPO-SKIP-PLAN", "source_run_id": run["run_id"],
                "query_id": plan_entry["query_id"], "provider": "jpo_api",
                "operation": "candidate_verification", "jurisdiction": "JP",
                "right_type": "patent", "requirement_ids": [requirement_id],
                "plan_entry_sha256": plan_digest,
                "payload": {
                    "candidate_id": candidate_id, "right_type": "patent",
                    "application_number": planned_query,
                    "official_verification": official,
                },
            }]},
        }
        write_json(task_dir / "task.json", task)
        write_json(task_dir / "search-plan.json", plan)
        write_json(task_dir / "normalized-candidates.json", {
            "patents": [candidate], "trademarks": [],
        })
        write_json(task_dir / "evidence.json", evidence)
        assert jpo_verification_already_complete(
            task_dir, "patent", candidate_id, planned_query,
        )
        plan["queries"]["jpo_api"][0]["q"] = "DIFFERENT"
        write_json(task_dir / "search-plan.json", plan)
        assert not jpo_verification_already_complete(
            task_dir, "patent", candidate_id, planned_query,
        )


def main() -> None:
    test_public_candidate_chain()
    test_public_candidate_verification_actions()
    test_evidence_backed_medium_high_gate()
    test_excluded_mismatch_action_is_repairable()
    test_registry_verification_records_planned_query()
    test_jplatpat_skip_requires_exact_jpo_plan()
    print("candidate gate hardening tests passed")


if __name__ == "__main__":
    main()
