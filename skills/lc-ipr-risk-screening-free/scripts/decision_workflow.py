"""Pure, opt-in scenario and candidate-triage contracts shared by the workflow.

No I/O, source calls, scheduling, or legal risk classification belongs here.
Historical tasks are never opted in by the presence of a ledger or material flag.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime
from typing import Any

from common import sha256_json

REVISION = "scenario-triage-v1"
CORRECTION_REVISION = "workflow-correction-v1"
TRIAGE_SCOPE_REVISION = "candidate-triage-scope-v1"
UNLOCATED = "UNLOCATED"
LEDGER_SCHEMA_VERSION = "2.0"
DECISIONS = {"selected", "not_selected", "needs_info"}
SCENARIO_TYPES = {"product_entry", "brand_reuse", "genuine_resale"}
RIGHT_TYPES = frozenset({"patent", "utility_model", "design", "trademark_word", "trademark_figurative",
                         "copyright", "trade_dress", "unregistered_design", "enforcement"})
READING_LEVELS = frozenset({"result_record", "registry_record", "abstract", "independent_claims",
                           "drawings", "image_comparison", "full_document"})
COLLECTIONS = ("patents", "trademarks", "copyright_assets", "enforcement")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
# These retail statistics describe marketplace activity, not the observed object.
# Keep the allowlist exact and scoped to specifications; all physical fields stay.
NON_IDENTITY_SPECIFICATIONS = frozenset({"Best Sellers Rank", "Customer Reviews"})
# Acquisition metadata and duplicate publication wrappers are not new facts.
VOLATILE = {
    "created_at", "updated_at", "collected_at", "checked_at", "captured_at",
    "annotated_at", "retrieved_at", "source_checked_at", "source_updated_at",
    "last_checked_at", "checked_at_meaning", "evidence_id", "query_id",
    "source_run_id", "source_run_ids", "run_id", "attempt_id", "provider",
    "source", "sources", "source_url", "source_urls", "url", "path",
    "raw_path", "raw_paths", "capture_provenance", "query_execution",
    "screenshots", "screenshot", "evidence_refs", "verification_refs",
    "material", "material_reason", "materiality_annotation", "disposition",
    "priority_signals", "triage_by_scenario", "triage_decisions", "query",
}
CANDIDATE_FACT_FIELDS = {
    "publication_number", "application_number", "registration_number", "serial_number", "record_number",
    "title", "titles", "mark", "mark_text", "wordmark", "abstract", "claims", "independent_claims",
    "claim_text", "description", "drawings", "drawing_sha256", "document_sha256",
    "goods", "goods_services", "goods_services_truncated", "goods_and_services", "classes", "nice_classes",
    "owner", "owners", "applicant", "applicants", "assignee", "assignees",
    "inventor", "inventors", "right_state", "legal_status", "status",
    "status_date", "expiry_date", "expiration_date", "territorial_effects",
    "comparison_elements", "exclusion_basis", "publication_relations", "publication_documents",
    "official_verification", "legal_events", "views", "figures", "media", "artifacts", "conflicts",
    "family_members", "publication_numbers", "application_numbers", "priority_numbers",
}

# A memo belongs to one in-process immutable evaluation, never to a task file,
# clock window or a previous run. No source-file verification is cached here.
_SNAPSHOT = ContextVar("ipr_decision_snapshot", default=None)


@contextmanager
def decision_snapshot(task, evidence, candidates, plan, ledger, supplement=None, *, memo_state=None):
    """Share pure indexes inside a content-checked, immutable call boundary."""
    inputs = (task, evidence, candidates, plan, ledger, supplement)
    parent = _SNAPSHOT.get()
    if parent is not None and all(a is b for a, b in zip(parent["inputs"], inputs)):
        yield parent
        return
    before = sha256_json(inputs)
    if memo_state is not None and not isinstance(memo_state, dict):
        raise ValueError("DECISION_SNAPSHOT_MEMO_STATE_INVALID")
    prior = memo_state.get("snapshot") if memo_state is not None else None
    if (isinstance(prior, dict) and memo_state.get("input_sha256") == before
            and all(a is b for a, b in zip(prior["inputs"], inputs))):
        snapshot = prior
    else:
        snapshot = {"inputs": inputs, "memo": {}, "retained": {}, "hits": 0, "misses": 0}
        if memo_state is not None:
            memo_state.clear()
            memo_state.update(snapshot=snapshot, input_sha256=before)
    token = _SNAPSHOT.set(snapshot)
    succeeded = False
    try:
        yield snapshot
        succeeded = True
    finally:
        _SNAPSHOT.reset(token)
        mutated = sha256_json(inputs) != before
        if memo_state is None or not succeeded or mutated:
            snapshot["memo"].clear()
            snapshot["retained"].clear()
            if memo_state is not None:
                memo_state.clear()
        if mutated:
            raise ValueError("DECISION_SNAPSHOT_INPUT_MUTATED")


def _snapshot_value(name, objects, compute, *, copy_result=False):
    snapshot = _SNAPSHOT.get()
    if snapshot is None:
        return compute()
    # Retaining references prevents id reuse for transient projections. The
    # surrounding boundary rejects changes to any business input before return.
    identities = tuple(id(value) for value in objects)
    key = (name, identities)
    if key not in snapshot["memo"]:
        snapshot["misses"] += 1
        snapshot["retained"][key] = objects
        snapshot["memo"][key] = compute()
    else:
        snapshot["hits"] += 1
    value = snapshot["memo"][key]
    return deepcopy(value) if copy_result else value


def decision_workflow_enabled(task: dict) -> bool:
    if "decision_workflow_revision" not in task:
        return False
    revision = task.get("decision_workflow_revision")
    if revision != REVISION:
        raise ValueError("UNSUPPORTED_DECISION_WORKFLOW_REVISION")
    return True


def correction_enabled(task: dict | None) -> bool:
    revision = (task or {}).get("workflow_correction_revision")
    if revision is None:
        return False
    if revision != CORRECTION_REVISION or not decision_workflow_enabled(task):
        raise ValueError("UNSUPPORTED_WORKFLOW_CORRECTION_REVISION")
    return True


def triage_scope_enabled(task: dict | None) -> bool:
    revision = (task or {}).get("triage_scope_revision")
    if revision is None:
        return False
    if revision != TRIAGE_SCOPE_REVISION or not correction_enabled(task):
        raise ValueError("TRIAGE_SCOPE_REVISION_INVALID")
    return True


def scenario_right_types(scenario: dict) -> frozenset[str]:
    kind = scenario.get("type")
    if not isinstance(kind, str) or kind not in SCENARIO_TYPES:
        raise ValueError("SCENARIO_TYPE_INVALID")
    return frozenset({"trademark_word", "trademark_figurative"}) if kind == "brand_reuse" else RIGHT_TYPES


def light_triage_right_allowed(task: dict, scenario: dict, right: str) -> bool:
    """Unknown identity may be screened; dispatch remains separately gated."""
    return right in scenario_right_types(scenario) or (
        right == "unknown" and scenario.get("type") != "brand_reuse"
        and task.get("candidate_identity_revision") == "candidate-identity-v1")


def necessary_scenario_right_types(task: dict, scenario: dict) -> frozenset[str]:
    """Necessary work is narrower than the valid triage/assessment vocabulary.

    A reference-only entry assumption does not supply a proposed mark. Keep
    reference-mark work in brand_reuse, while retaining trade dress and other
    rights in the copied structure. This is scope, never trademark clearance.
    """
    allowed = scenario_right_types(scenario)
    if task.get("execution_policy_revision") == "continuous-work-v2":
        required = task.get("execution_scenario_ids")
        if not isinstance(required, list) or not all(isinstance(value, str) and value for value in required):
            raise ValueError("EXECUTION_SCENARIO_IDS_REQUIRED")
        if scenario.get("scenario_id") not in set(required):
            return frozenset()
    if not decision_workflow_enabled(task) or scenario.get("type") != "product_entry":
        return allowed
    import product_scope as ps
    if ps.enabled(task): return ps.required_rights(task,scenario,allowed)
    product = task.get("product") or {}
    supplied = any(product.get(field) for field in
        ("own_brand", "own_brand_name", "own_brand_logo", "own_logo"))
    supplied = supplied or (product.get("brand_role") == "own"
                            and any(product.get(field) for field in ("brand", "logo")))
    if product.get("input_role") == "reference_product" and not supplied:
        return allowed - {"trademark_word", "trademark_figurative"}
    return allowed


def execution_scenario_ids(task: dict) -> tuple[str, ...]:
    """Return scenarios that can create executable completion work."""
    scenarios = scenario_index(task)
    if task.get("execution_policy_revision") != "continuous-work-v2":
        return tuple(scenarios)
    values = task.get("execution_scenario_ids")
    if (not isinstance(values, list) or not values or len(set(values)) != len(values)
            or any(value not in scenarios for value in values)):
        raise ValueError("EXECUTION_SCENARIO_IDS_REQUIRED")
    if task.get("primary_scenario_id") not in values:
        raise ValueError("PRIMARY_SCENARIO_EXECUTION_REQUIRED")
    return tuple(values)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: Any, *, required: bool = True) -> bool:
    return isinstance(value, list) and (bool(value) or not required) and all(_text(v) for v in value)


def semantic_content(value: Any) -> Any:
    """Canonical content, insensitive to wrapper metadata, ordering and reposts."""
    if isinstance(value, dict):
        return {k: semantic_content(v) for k, v in sorted(value.items())
                if k not in VOLATILE and v not in (None, "", [], {})}
    if isinstance(value, list):
        values = [semantic_content(v) for v in value]
        return [v for _, v in sorted({sha256_json(v): v for v in values}.items())]
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def product_identity_content(value: Any) -> Any:
    """Canonical product facts, excluding only named retail-statistics fields."""
    def without_retail_statistics(item):
        if isinstance(item, dict):
            return {key: without_retail_statistics(
                        {name: data for name, data in child.items() if name not in NON_IDENTITY_SPECIFICATIONS}
                        if key == "specifications" and isinstance(child, dict) else child)
                    for key, child in item.items()}
        if isinstance(item, list):
            return [without_retail_statistics(child) for child in item]
        return item
    return semantic_content(without_retail_statistics(value))


_OBSERVED_FIELDS = ("product_id", "purpose", "requested_asin", "actual_asin", "variant", "selected_variant", "title", "brand",
                    "brand_byline_raw", "brand_placeholder",
                    "manufacturer", "category", "bullets", "specifications", "visible_ip_claims",
                    "structure", "visual_features", "ocr_text", "media_identity")
_STRUCTURAL_FIELDS = ("structure", "function", "functions", "visual_features", "dimensions", "materials",
                      "material", "specifications", "shape", "color", "colours", "decoration")
_CONTEXT_FIELDS = ("product_id", "requested_asin", "actual_asin", "variant", "selected_variant", "input_role",
                   "actual_product_confirmation")
_EDITORIAL_FIELDS = frozenset({"reason", "reasoning", "scope_reasoning", "basis_summary", "reviewer",
    "reading_level", "reading_scope", "reopen_conditions", "visual_reason", "finding", "caption", "alt",
    "label", "inventory_identity_sha256", "source_path", "local_path", "file_path", "screenshot_path",
    "page_verified_at", "page_verification_method", "derived_from_evidence_id", "rendered_at"})


def factual_content(value: Any) -> Any:
    """Strip acquisition/editorial wrappers, retaining declared factual values."""
    if isinstance(value, dict):
        return {key: factual_content(child) for key, child in sorted(value.items())
                if key not in VOLATILE | _EDITORIAL_FIELDS and child not in (None, "", [], {})}
    if isinstance(value, list):
        rows = [factual_content(row) for row in value]
        return [row for _, row in sorted({sha256_json(row): row for row in rows}.items())]
    return " ".join(value.split()) if isinstance(value, str) else value


def observed_product_content(product: dict) -> dict:
    """One source-fact vocabulary for capture, analysis and retained identity."""
    raw = product.get("raw_capture") or {}
    observed = {key: product[key] for key in _OBSERVED_FIELDS if key in product}
    observed["raw_observations"] = {key: raw[key] for key in _OBSERVED_FIELDS
                                    if isinstance(raw, dict) and key in raw}
    return factual_content(product_identity_content(observed))


def observed_product_sha256(product: dict) -> str:
    return sha256_json(observed_product_content(product))


def scoped_product_content(task: dict, scenario_id: str | None, right_type: str | None) -> dict:
    import product_scope as ps
    if ps.enabled(task): return ps.scoped_content(task,scenario_id,right_type)
    product = task.get("product") or {}
    raw = product.get("raw_capture") or {}
    raw = raw if isinstance(raw, dict) else {}
    common = {key: product[key] for key in _CONTEXT_FIELDS if key in product}
    if right_type in {"trademark_word", "trademark_figurative"}:
        common["marks"] = {key: product[key] for key in ("brand", "own_brand", "own_brand_name", "own_brand_logo",
            "own_logo", "brand_role", "brand_byline_raw", "brand_placeholder", "logo", "product_type", "category", "intended_goods") if key in product}
        common["mark_inventory"] = [row for row in (product.get("mark_inventory") or []) if isinstance(row, dict)
            and (scenario_id is None or scenario_id in (row.get("scenario_ids") or []))]
    elif right_type is not None:
        common["structure"] = {key: product.get(key, raw.get(key)) for key in _STRUCTURAL_FIELDS
                               if key in product or isinstance(raw, dict) and key in raw}
        common["raw_structure"] = {key: raw[key] for key in _STRUCTURAL_FIELDS if key in raw}
        for field in ("structure", "raw_structure"):
            specs = common[field].get("specifications")
            if isinstance(specs, dict):
                common[field]["specifications"] = {key: val for key, val in specs.items()
                    if key not in {"Brand", "Manufacturer", *NON_IDENTITY_SPECIFICATIONS}}
        common["media_identity"] = product.get("media_identity") or sorted({row.get("sha256")
            for row in task.get("images", []) if isinstance(row, dict) and row.get("sha256")})
    else:
        common["observations"] = observed_product_content(product)
        common["structure"] = product.get("structure")
    if right_type not in {"patent", "utility_model", "trademark_word", "trademark_figurative"}:
        common["assets"] = [row for row in (product.get("assets") or []) if isinstance(row, dict)
            and (scenario_id is None or scenario_id in (row.get("scenario_ids") or []))
            and (right_type is None or right_type in (row.get("right_types") or []))]
    return factual_content(product_identity_content(common))


def scenario_sha256(scenario: dict) -> str:
    return sha256_json({k: semantic_content(scenario.get(k)) for k in
                       ("scenario_id", "type", "title", "assumptions", "fact_sources", "conditional")})


def default_assessment_scenarios(*, genuine_resale: bool = False) -> list[dict]:
    definitions = [
        ("product_entry", "同结构与用途的选品进入", False,
         ["以参考商品已展示的结构、功能和用途作为拟进入方案的条件假设，不判断原卖家的既成侵权责任。",
          "不依赖尚未提供的许可；未获许可与不存在许可均不被改写为已知事实。",
          "不默认沿用竞品品牌、图片、文案或包装；未展示的内部结构保持未知。"]),
        ("brand_reuse", "沿用参考标识的条件情景", True,
         ["仅分析在同类商品上沿用参考商品标识且不依赖许可时的条件风险，不推定用户决定如此使用。"]),
    ]
    if genuine_resale:
        definitions.append(("genuine_resale", "明确请求的正品转售情景", True,
                            ["评估明确请求的正品转售路径；真品身份、进货及可适用授权仍需证据，不因情景名称视为已证实。 "]))
    result = []
    for kind, title, conditional, assumptions in definitions:
        row = {"scenario_id": kind, "type": kind, "title": title,
               "assumptions": assumptions, "conditional": conditional,
               "fact_sources": [{"kind": "user_request" if kind == "genuine_resale" else "workflow_assumption",
                                 "ref": "request.genuine_resale" if kind == "genuine_resale" else REVISION,
                                 "statement": "用户明确请求正品转售情景。" if kind == "genuine_resale" else "选品条件假设，不是已确认用户行为。"}]}
        row["scenario_sha256"] = scenario_sha256(row)
        result.append(row)
    return result


def validate_decision_workflow(task: dict) -> list[str]:
    if not decision_workflow_enabled(task):
        return []
    errors = []
    scenarios = task.get("assessment_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return ["ASSESSMENT_SCENARIOS_REQUIRED"]
    ids = set()
    for row in scenarios:
        if not isinstance(row, dict):
            errors.append("SCENARIO_MUST_BE_OBJECT")
            continue
        sid = row.get("scenario_id")
        if not _text(sid) or sid in ids:
            errors.append("SCENARIO_ID_INVALID_OR_DUPLICATE")
        ids.add(sid if isinstance(sid, str) else "")
        if not _text(row.get("type")) or row["type"] not in SCENARIO_TYPES or not _text(row.get("title")) or not _strings(row.get("assumptions")):
            errors.append("SCENARIO_DEFINITION_INVALID")
        sources = row.get("fact_sources")
        if (not isinstance(sources, list) or not sources or any(not isinstance(s, dict)
                or not _text(s.get("kind")) or s["kind"] not in {"workflow_assumption", "task_field", "user_request", "evidence"}
                or not _text(s.get("ref")) or not _text(s.get("statement")) for s in sources)):
            errors.append("SCENARIO_FACT_SOURCES_INVALID")
        if type(row.get("conditional")) is not bool:
            errors.append("SCENARIO_CONDITIONAL_REQUIRED")
        if row.get("type") == "brand_reuse" and row.get("conditional") is not True:
            errors.append("BRAND_REUSE_MUST_BE_CONDITIONAL")
        if row.get("type") == "genuine_resale" and ((task.get("request") or {}).get("genuine_resale") is not True
                or not isinstance(sources, list)
                or not any(isinstance(s, dict) and s.get("kind") == "user_request" for s in sources)):
            errors.append("GENUINE_RESALE_EXPLICIT_REQUEST_REQUIRED")
        if row.get("scenario_sha256") != scenario_sha256(row):
            errors.append("SCENARIO_SHA256_MISMATCH")
    primary = next((r for r in scenarios if isinstance(r, dict) and r.get("scenario_id") == task.get("primary_scenario_id")), None)
    if primary is None or primary.get("type") != "product_entry":
        errors.append("PRIMARY_PRODUCT_ENTRY_SCENARIO_REQUIRED")
    return errors


def scenario_index(task: dict) -> dict[str, dict]:
    return _snapshot_value("scenarios", (task,), lambda: _scenario_index(task), copy_result=True)


def _scenario_view(task: dict) -> dict[str, dict]:
    """Internal read-only use only; public callers receive detached scenario rows."""
    return _snapshot_value("scenarios", (task,), lambda: _scenario_index(task))


def _scenario_index(task: dict) -> dict[str, dict]:
    if not decision_workflow_enabled(task):
        return {}
    errors = validate_decision_workflow(task)
    if errors:
        raise ValueError("INVALID_DECISION_WORKFLOW: " + "; ".join(errors))
    return {r["scenario_id"]: r for r in task["assessment_scenarios"]}


def product_identity_sha256(task: dict, *, scenario_id: str | None = None, right_type: str | None = None, candidate_id: str | None = None) -> str:
    import product_scope as ps
    if ps.enabled(task): return sha256_json(ps.scoped_content(task,scenario_id,right_type,candidate_id))
    if correction_enabled(task):
        return _snapshot_value(("scoped_product_identity", scenario_id, right_type), (task,),
            lambda: sha256_json(scoped_product_content(task, scenario_id, right_type)))
    return _snapshot_value("product_identity", (task,), lambda: _product_identity_sha256(task))


def _product_identity_sha256(task: dict) -> str:
    product = task.get("product") or {}
    keys = ("input_role", "intended_use", "actual_product_confirmation",
            "requested_asin", "actual_asin", "variant", "title", "brand", "manufacturer",
            "bullets", "specifications", "structure", "visible_ip_claims", "assets", "raw_capture", "main_visual")
    return sha256_json(product_identity_content({"product": {k: product.get(k) for k in keys}, "images": task.get("images", [])}))


def candidate_identity_fingerprint(collection: str, candidate: dict) -> str:
    cid = str(candidate.get("candidate_id") or "").strip()
    return sha256_json({"collection": collection, "candidate_id": cid,
                       "normalization_key": str(candidate.get("normalization_key") or cid).strip(),
                       "jurisdiction": str(candidate.get("jurisdiction") or candidate.get("office") or "").upper().strip(),
                       "right_type": str(candidate.get("right_type") or "").strip()})


def evidence_index(evidence: dict | None = None, supplement: dict | None = None) -> dict[str, dict]:
    # The index is private to callers in this evaluation; return a shallow map
    # so adding/removing entries cannot poison later lookups.
    return dict(_snapshot_value("evidence_index", (evidence, supplement),
                               lambda: _evidence_index(evidence, supplement)))


def _evidence_index(evidence: dict | None = None, supplement: dict | None = None) -> dict[str, dict]:
    result = {}
    for entries in (evidence or {}).get("collections", {}).values():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and _text(entry.get("evidence_id")):
                    if entry["evidence_id"] in result and result[entry["evidence_id"]] != entry:
                        raise ValueError("DUPLICATE_EVIDENCE_ID")
                    result[entry["evidence_id"]] = entry
    for entry in (supplement or {}).get("evidence", []):
        if isinstance(entry, dict) and _text(entry.get("evidence_id")):
            if entry["evidence_id"] in result and result[entry["evidence_id"]] != entry:
                raise ValueError("DUPLICATE_EVIDENCE_ID")
            result[entry["evidence_id"]] = entry
    return result


def _identity_tokens(record: dict) -> set[str]:
    return {re.sub(r"[^A-Z0-9]", "", str(record[k]).upper()) for k in
            ("candidate_id", "publication_number", "application_number", "registration_number", "serial_number", "record_number")
            if _text(record.get(k))}


def _evidence_content(entry: dict, candidate: dict | None = None, *, task: dict | None = None) -> Any:
    return _snapshot_value("evidence_content", (entry, candidate, task),
                           lambda: _uncached_evidence_content(entry, candidate, task=task))


def _uncached_evidence_content(entry: dict, candidate: dict | None = None, *, task: dict | None = None) -> Any:
    payload = entry.get("payload", entry)
    if candidate is not None and isinstance(payload, dict):
        tokens = _identity_tokens(candidate)
        for key in ("candidates", "records", "results", "hits"):
            records = payload.get(key)
            if not isinstance(records, list):
                continue
            def record_index():
                identified, by_token = [], {}
                for position, record in enumerate(records):
                    if not isinstance(record, dict):
                        continue
                    identities = _identity_tokens(record)
                    if not identities:
                        continue
                    identified.append(position)
                    for identity in identities:
                        by_token.setdefault(identity, set()).add(position)
                return identified, by_token
            identified, by_token = _snapshot_value("evidence_record_identities", (records,), record_index)
            if not identified:
                continue
            positions = set().union(*(by_token.get(token, set()) for token in tokens))
            matches = [records[position] for position in sorted(positions)]
            if correction_enabled(task):
                publication = _full_publication_number(candidate)
                if publication:
                    matches = [record for record in matches if _full_publication_number(record) in (None, publication)]
                matches = [_candidate_record_facts(record) for record in matches]
            # An unrelated hit or the whole-query screenshot is not new content
            # for this candidate. Candidate-local figures/artifacts stay bound.
            result = {"candidate_records": matches, "candidate_record_missing": not bool(matches)}
            if correction_enabled(task):
                result["identity_scope"] = ("exact_publication" if matches and _full_publication_number(candidate)
                    and all(_full_publication_number(record) == _full_publication_number(candidate) for record in matches)
                    else "record_identity_only_not_grant_document")
            return semantic_content(result)
    return semantic_content(payload)


def _candidate_record_facts(record: dict) -> dict:
    """Ignore result-list capture metadata, never candidate-local visual facts.

    A different row position or whole-results screenshot is not a new patent
    drawing/mark specimen. Unknown browser fields are retained conservatively.
    Raw evidence and its integrity checks remain untouched.
    """
    result = {key: value for key, value in record.items() if key != "result_ordinal"}
    browser = result.get("browser_evidence")
    if isinstance(browser, dict):
        result["browser_evidence"] = {key: value for key, value in browser.items()
            if key not in {"screenshot_path", "screenshot_sha256", "screenshot_bytes"}}
    return result


def _full_publication_number(record: dict) -> str | None:
    number = record.get("publication_number")
    if not isinstance(number, str):
        return None
    number = re.sub(r"[\s,./-]", "", number.upper())
    return number if re.fullmatch(r"[A-Z]{2}(?:D|RE|PP)?\d+[A-Z]\d?", number) else None


def _publication_identity(record: dict) -> tuple[str, str, str] | None:
    """Exact full publication only; an application/family number cannot substitute."""
    number = _full_publication_number(record)
    country, right = record.get("jurisdiction"), record.get("right_type")
    if not isinstance(number, str) or not isinstance(country, str) or right not in {"patent", "design", "utility_model"}:
        return None
    if not number.startswith(country.upper()):
        return None
    return country.upper(), right, number


def candidate_document_entries(candidate: dict, evidence: dict | None = None,
                               supplement: dict | None = None, *, task: dict | None = None) -> list[dict]:
    """Return exactly related registered documents/pages; callers verify source bytes.

    A page may inherit the number only through its registered parent path AND
    hash. Contradictory explicit page identity is never ignored. No file-name,
    title, same-family, application-number or partial-number matching is used.
    """
    identity = _publication_identity(candidate)
    if identity is None:
        return []
    def document_index():
        registry = evidence_index(evidence, supplement)
        documents, pages = {}, {}
        for entry in registry.values():
            if (entry.get("authority_scope") != "published_document_only"
                    or entry.get("kind") not in {"patent_document", "design_drawings"}
                    or not isinstance(entry.get("path"), str)
                    or not HASH_RE.fullmatch(str(entry.get("sha256", "")))):
                continue
            if entry["path"].lower().endswith(".pdf"):
                key = _publication_identity(entry)
                if key is not None:
                    documents.setdefault(key, []).append(entry)
            elif (type(entry.get("page_number")) is int and entry["page_number"] >= 1
                    and entry.get("visual_role") in {"document_identity", "patent_claims", "patent_drawings"}
                    and isinstance(entry.get("source_document"), str)
                    and HASH_RE.fullmatch(str(entry.get("source_document_sha256", "")))):
                pages.setdefault((entry["source_document"], entry["source_document_sha256"]), []).append(entry)
        return documents, pages
    documents, page_index = _snapshot_value("registered_document_index", (evidence, supplement), document_index)
    parents = documents.get(identity, [])
    pages, seen = [], set()
    for parent in parents:
        for entry in page_index.get((parent["path"], parent["sha256"]), []):
            if (entry.get("jurisdiction") != identity[0] or entry.get("right_type") != identity[1]
                    or entry.get("publication_number") and _publication_identity(entry) != identity):
                continue
            if entry.get("evidence_id") not in seen:
                pages.append(entry)
                seen.add(entry.get("evidence_id"))
    return deepcopy(parents + pages)


def _presentation_reuses_original(entry: dict, candidate: dict, index: dict, task: dict | None) -> bool:
    """A display attachment cannot hide new content merely by declaring a flag.

    Only the new policy accepts an exact original already in the evidence
    registry. Explicit factual references to the attachment still enter the
    candidate digest, and all original/render bytes remain delivery inputs.
    """
    if ((task or {}).get("assessment_revision") != "known-findings-risk-v1"
            or entry.get("evidence_use") != "presentation_only"):
        return False
    original = index.get(entry.get("presentation_source_evidence_id"))
    if (not isinstance(original, dict) or original is entry
            or original.get("evidence_use") == "presentation_only"
            or original.get("kind") not in {"patent_document", "design_drawings"}
            or _publication_identity(original) != _publication_identity(candidate)
            or not HASH_RE.fullmatch(str(original.get("sha256", "")))
            or not str(original.get("path", "")).lower().endswith(".pdf")):
        return False
    if str(entry.get("path", "")).lower().endswith(".pdf"):
        return (entry.get("sha256") == original["sha256"]
                and entry.get("bytes") == original.get("bytes"))
    return (entry.get("source_document_sha256") == original["sha256"]
            and type(entry.get("page_number")) is int and entry["page_number"] >= 1)


def candidate_document_content(candidate: dict, evidence=None, supplement=None, *, task=None) -> list[dict]:
    values = []
    index = evidence_index(evidence, supplement)
    for entry in candidate_document_entries(candidate, evidence, supplement, task=task):
        if _presentation_reuses_original(entry, candidate, index, task):
            continue
        if entry["path"].lower().endswith(".pdf"):
            values.append({"publication": _publication_identity(candidate), "document_sha256": entry["sha256"]})
        else:
            # Different encodings/renders of the same page are the same content.
            values.append({"publication": _publication_identity(candidate),
                "document_sha256": entry["source_document_sha256"], "page_number": entry["page_number"],
                "figure_labels": entry.get("figure_labels", [])})
    return semantic_content(values)


def basis_evidence_sha256(refs: list[str], evidence: dict | None = None, supplement: dict | None = None, *,
                          candidate: dict | None = None, task: dict | None = None) -> str:
    index = evidence_index(evidence, supplement)
    if not _strings(refs, required=False) or len(refs) != len(set(refs)):
        raise ValueError("TRIAGE_EVIDENCE_REFS_INVALID")
    if any(ref not in index for ref in refs):
        raise ValueError("TRIAGE_UNKNOWN_EVIDENCE_REF")
    if any(_evidence_content(index[ref], candidate, task=task) in (None, "", [], {}) for ref in refs):
        raise ValueError("TRIAGE_EMPTY_EVIDENCE_CONTENT")
    # Different IDs pointing to identical retained content are one factual basis.
    return sha256_json(sorted({sha256_json(_evidence_content(index[ref], candidate, task=task)) for ref in refs}))


def candidate_content_sha256(candidate: dict, evidence: dict | None = None, supplement: dict | None = None,
                             *, task: dict | None = None) -> str:
    return _snapshot_value("candidate_content", (candidate, evidence, supplement, task),
                           lambda: _candidate_content_sha256(candidate, evidence, supplement, task=task))


def _candidate_content_sha256(candidate: dict, evidence: dict | None = None, supplement: dict | None = None,
                              *, task: dict | None = None) -> str:
    index = evidence_index(evidence, supplement)
    refs = [r for key in ("evidence_refs", "verification_refs") for r in candidate.get(key, []) if isinstance(r, str)]
    if task and task.get("candidate_identity_revision") == "candidate-identity-v1":
        duplicate_refs = set(candidate.get("duplicate_evidence_refs", []))
        refs = [ref for ref in refs if ref not in duplicate_refs]
    documents = candidate_document_entries(candidate, evidence, supplement, task=task) if correction_enabled(task) else []
    document_refs = {entry.get("evidence_id") for entry in documents
                     if not _presentation_reuses_original(entry, candidate, index, task)}
    contents = sorted({sha256_json(_evidence_content(index[r], candidate, task=task)) for r in refs if r in index and r not in document_refs})
    payload = {"candidate": semantic_content({k: candidate[k] for k in CANDIDATE_FACT_FIELDS if k in candidate}),
               "source_content": contents}
    if correction_enabled(task):
        payload["registered_document_content"] = candidate_document_content(candidate, evidence, supplement, task=task)
    return sha256_json(payload)


def decision_key(candidate_id: str, scenario_id: str, jurisdiction: str, right_type: str) -> tuple[str, str, str, str]:
    return candidate_id, scenario_id, jurisdiction.upper(), right_type


def triage_product_digest(task: dict, scenario_id: str, right_type: str, candidate_id: str) -> str:
    # An unidentified right can depend on several scoped directions. Binding
    # only the literal "unknown" direction would miss changed product facts.
    scoped_right = None if triage_scope_enabled(task) and right_type == "unknown" else right_type
    return product_identity_sha256(task, scenario_id=scenario_id, right_type=scoped_right,
                                   candidate_id=candidate_id)


def candidate_scope_details(task: dict, scenario_id: str, right_type: str,
                            candidate: dict) -> dict:
    """05A object disposition, independent of candidate identity or relevance."""
    import product_scope as ps
    if not ps.enabled(task):
        return {"status": "included", "objects": [], "ready_direction_ids": []}
    try:
        data = ps.scope(task)
    except ValueError:
        return {"status": "pending", "objects": [], "ready_direction_ids": []}
    links = [row for row in data.get("candidate_links", [])
             if row.get("candidate_id") == candidate.get("candidate_id")]
    if len(links) != 1:
        return {"status": "pending", "objects": [], "ready_direction_ids": []}
    objects = {row["object_id"]: row for row in data["objects"]}
    details = []
    ready_directions = set()
    for object_id in links[0].get("object_ids", []):
        obj = objects.get(object_id)
        if obj is None or (scenario_id != "genuine_resale" and ps.object_scenario(obj) != scenario_id):
            continue
        if right_type != "unknown" and right_type not in obj.get("right_types", []):
            continue
        state = obj["scope_status"]
        directions = [row for row in ps.directions(task, scenario_id)
                      if object_id in row["object_ids"]
                      and (right_type == "unknown" or row["right_type"] == right_type)]
        ready = [row["direction_id"] for row in directions if ps.direction_state(task, row) == "ready"]
        if state == "included":
            state = "included" if ready else "pending"
            ready_directions.update(ready)
        details.append({"object_id": object_id, "scope_status": state,
                        "upstream_scope_status": obj["scope_status"],
                        "ready_direction_ids": ready})
    statuses = {row["scope_status"] for row in details}
    status = ("included" if "included" in statuses else "pending" if "pending" in statuses
              else "user_excluded" if statuses == {"user_excluded"} else "default_excluded"
              if details else "default_excluded")
    return {"status": status, "objects": details,
            "ready_direction_ids": sorted(ready_directions),
            "link_evidence_refs": links[0].get("source_refs", [])}


def _triage_basis_errors(annotation: dict, task: dict) -> list[str]:
    if not triage_scope_enabled(task):
        return []
    errors = []
    relation = annotation.get("candidate_relation")
    comparison = annotation.get("comparison")
    if (not isinstance(relation, dict) or not _strings(relation.get("product_object_ids"))
            or not isinstance(relation.get("direction_ids"), list)
            or not all(_text(value) for value in relation["direction_ids"])
            or len(relation["direction_ids"]) != len(set(relation["direction_ids"]))
            or not _text(relation.get("scope_reason"))
            or not _strings(relation.get("evidence_refs"))
            or not isinstance(relation.get("identity_gaps"), list)
            or not all(_text(value) for value in relation["identity_gaps"])):
        errors.append("TRIAGE_CANDIDATE_RELATION_REQUIRED")
    if (not isinstance(comparison, dict)
            or not _text(comparison.get("candidate_content"))
            or not _text(comparison.get("product_content"))
            or not _text(comparison.get("relationship"))):
        errors.append("TRIAGE_CONCRETE_COMPARISON_REQUIRED")
    elif annotation.get("decision") == "selected" and not _text(comparison.get("investigation_question")):
        errors.append("TRIAGE_SELECTED_QUESTION_REQUIRED")
    elif annotation.get("decision") == "not_selected" and (
            not _text(comparison.get("difference"))
            or not _text(comparison.get("applicability_limit"))):
        errors.append("TRIAGE_EXCLUSION_DIFFERENCE_AND_SCOPE_REQUIRED")
    elif annotation.get("decision") == "needs_info" and (
            not _text(comparison.get("missing_fact_effect"))
            or not _text(comparison.get("completion_condition"))
            or not _text(comparison.get("existing_material_review"))):
        errors.append("TRIAGE_INFORMATION_DECISION_BASIS_REQUIRED")
    if isinstance(relation, dict) and _strings(relation.get("evidence_refs")):
        if not set(relation["evidence_refs"]) <= set(annotation.get("evidence_refs") or []):
            errors.append("TRIAGE_RELATION_EVIDENCE_NOT_READ")
    if isinstance(relation, dict) and relation.get("identity_gaps"):
        location = relation.get("identity_location")
        if (not isinstance(location, dict) or not _text(location.get("reason"))
                or not _text(location.get("affected_work"))
                or not _text(location.get("next_action"))):
            errors.append("TRIAGE_IDENTITY_LOCATION_REQUIRED")
    return errors


def next_action_errors(actions: Any, *, task: dict | None = None,
                       known_evidence: set[str] | None = None) -> list[str]:
    if not isinstance(actions, list) or not actions:
        return ["NEEDS_INFO_NEXT_ACTIONS_REQUIRED"]
    errors, ids = [], set()
    for action in actions:
        if not isinstance(action, dict):
            errors.append("NEXT_ACTION_INVALID")
            continue
        aid = action.get("action_id")
        if not _text(aid) or aid in ids or not _text(action.get("purpose")):
            errors.append("NEXT_ACTION_ID_OR_PURPOSE_INVALID")
        ids.add(aid if isinstance(aid, str) else "")
        if correction_enabled(task) and action.get("kind") in {"source_lookup", "agent_read"}:
            facts = action.get("required_facts")
            allowed = {"abstract", "representative_figures", "protection_content", "current_status", "goods_services"}
            scope = action.get("reading_scope")
            if not _strings(facts) or len(set(facts)) != len(facts) or not set(facts) <= allowed:
                errors.append("NEXT_ACTION_REQUIRED_FACTS_INVALID")
            if (not isinstance(scope, dict) or not isinstance(scope.get("level"), str) or scope.get("level") not in allowed
                    or isinstance(facts, list) and scope.get("level") not in facts):
                errors.append("NEXT_ACTION_READING_SCOPE_INVALID")
            elif "page_numbers" in scope or scope["level"] == "representative_figures":
                pages = scope.get("page_numbers")
                if (not isinstance(pages, list) or not pages or any(type(page) is not int or page < 1 for page in pages)
                        or len(set(pages)) != len(pages)):
                    errors.append("NEXT_ACTION_PAGE_NUMBERS_REQUIRED")
        if action.get("kind") == "source_lookup":
            if (not _text(action.get("provider")) or not _text(action.get("operation"))
                    or not isinstance(action.get("params"), dict)
                    or type(action.get("max_attempts")) is not int or action["max_attempts"] != 1):
                errors.append("NEXT_ACTION_BOUNDED_SOURCE_REQUIRED")
        elif action.get("kind") == "agent_read" and correction_enabled(task):
            if (not _strings(action.get("evidence_refs")) or action.get("max_attempts") != 1
                    or type(action.get("max_attempts")) is not int
                    or any(key in action for key in ("provider", "operation", "params"))):
                errors.append("NEXT_ACTION_LOCAL_EVIDENCE_REQUIRED")
        elif isinstance(action.get("kind"), str) and action["kind"] in {"user_information", "professional_review"}:
            if not _text(action.get("question")):
                errors.append("NEXT_ACTION_QUESTION_REQUIRED")
        elif action.get("kind") == "discovery_binding" and task and task.get("triage_followup_revision"):
            pass  # A reviewed existing discovery plan row supplies the executable request.
        else:
            errors.append("NEXT_ACTION_KIND_INVALID")
        from candidate_followup import enabled as followup_enabled, action_errors as followup_action_errors
        if followup_enabled(task):
            errors.extend(followup_action_errors(action, known_evidence=known_evidence))
    return errors


def annotation_errors(annotation: Any, *, known_evidence: set[str] | None = None,
                      task: dict | None = None) -> list[str]:
    if not isinstance(annotation, dict):
        return ["TRIAGE_ANNOTATION_MUST_BE_OBJECT"]
    errors = []
    for field in ("annotation_id", "candidate_id", "scenario_id", "jurisdiction", "right_type", "reason", "reviewer", "basis_summary"):
        if not _text(annotation.get(field)):
            errors.append("TRIAGE_REQUIRED_FIELD: " + field)
    if not _text(annotation.get("decision")) or annotation["decision"] not in DECISIONS:
        errors.append("TRIAGE_DECISION_INVALID")
    if not _text(annotation.get("reading_level")) or annotation["reading_level"] not in READING_LEVELS:
        errors.append("TRIAGE_READING_LEVEL_REQUIRED")
    if not _strings(annotation.get("reopen_conditions")):
        errors.append("TRIAGE_REOPEN_CONDITIONS_REQUIRED")
    for field in ("candidate_identity_fingerprint", "product_identity_sha256", "scenario_sha256", "candidate_content_sha256", "basis_sha256"):
        if not isinstance(annotation.get(field), str) or not HASH_RE.fullmatch(annotation[field]):
            errors.append("TRIAGE_HASH_INVALID: " + field)
    try:
        if datetime.fromisoformat(str(annotation.get("annotated_at", "")).replace("Z", "+00:00")).tzinfo is None:
            raise ValueError()
    except ValueError:
        errors.append("TRIAGE_TIMESTAMP_INVALID")
    refs = annotation.get("evidence_refs")
    if (not _strings(refs)
            or len(refs) != len(set(refs))):
        errors.append("TRIAGE_EVIDENCE_REFS_INVALID")
    elif known_evidence is not None and not set(refs) <= known_evidence:
        errors.append("TRIAGE_UNKNOWN_EVIDENCE_REF")
    if annotation.get("decision") == "needs_info":
        if not _strings(annotation.get("missing_information")):
            errors.append("NEEDS_INFO_MISSING_INFORMATION_REQUIRED")
        context = task if annotation.get("workflow_correction_revision") == CORRECTION_REVISION else None
        errors.extend(next_action_errors(annotation.get("next_actions"), task=context,
                                         known_evidence=known_evidence))
        if task and task.get("triage_followup_revision") and isinstance(annotation.get("next_actions"), list):
            for action in annotation.get("next_actions", []):
                if not isinstance(action, dict):
                    continue
                basis = action.get("followup_basis") or {}
                locator = action.get("target_locator") or {}
                if any(not _strings(refs, required=False)
                       or not set(refs) <= set(annotation.get("evidence_refs") or [])
                       for refs in (basis.get("existing_evidence_refs", []), locator.get("evidence_refs", []))
                       if isinstance(refs, list)):
                    errors.append("FOLLOWUP_BASIS_EVIDENCE_NOT_READ")
        if correction_enabled(context) and known_evidence is not None:
            for action in annotation.get("next_actions", []) if isinstance(annotation.get("next_actions"), list) else []:
                if isinstance(action, dict) and action.get("kind") == "agent_read" and _strings(action.get("evidence_refs")):
                    if not set(action["evidence_refs"]) <= known_evidence:
                        errors.append("NEXT_ACTION_UNKNOWN_EVIDENCE_REF")
    errors.extend(_triage_basis_errors(annotation, task or {}))
    if (task and task.get("candidate_identity_revision") == "candidate-identity-v1"
            and annotation.get("right_type") == "unknown"
            and annotation.get("decision") == "selected"
            and not triage_scope_enabled(task)):
        errors.append("TRIAGE_UNKNOWN_TYPE_CANNOT_BE_SELECTED")
    if annotation.get("workflow_correction_revision") not in (None, CORRECTION_REVISION):
        errors.append("TRIAGE_CORRECTION_REVISION_MISMATCH")
    return errors


def triage_ledger_errors(task: dict, ledger: dict, candidates: dict, *, evidence: dict | None = None,
                         supplement: dict | None = None) -> list[str]:
    """Validate history, not completion; stale valid history is reopened, not erased."""
    if not decision_workflow_enabled(task):
        return ["TRIAGE_REVISION_REQUIRED"]
    errors = validate_decision_workflow(task)
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        errors.append("TRIAGE_LEDGER_SCHEMA_REQUIRED")
    if ledger.get("task_id") != task.get("task_id"):
        errors.append("TRIAGE_LEDGER_TASK_MISMATCH")
    rows = ledger.get("annotations")
    if not isinstance(rows, list):
        return [*errors, "TRIAGE_ANNOTATIONS_REQUIRED"]
    known = set(evidence_index(evidence, supplement))
    candidate_ids = set()
    for collection in COLLECTIONS:
        entries = candidates.get(collection, [])
        if not isinstance(entries, list):
            errors.append("TRIAGE_CANDIDATE_COLLECTION_INVALID")
            continue
        for candidate in entries:
            cid = candidate.get("candidate_id") if isinstance(candidate, dict) else None
            if not _text(cid) or cid in candidate_ids:
                errors.append("TRIAGE_CANDIDATE_ID_INVALID_OR_DUPLICATE")
            if isinstance(cid, str):
                candidate_ids.add(cid)
    ids, last = set(), None
    retired_ids = ({cid for alias in candidates.get("identity_aliases", [])
                    if isinstance(alias, dict) and alias.get("kind") in {"merge", "split"}
                    for cid in alias.get("old_candidate_ids", [])}
                   if task.get("triage_stage_revision") == "candidate-triage-stage-v1" else set())
    for row in rows:
        errors.extend(annotation_errors(row, known_evidence=known, task=task))
        if not isinstance(row, dict):
            continue
        aid = row.get("annotation_id")
        if isinstance(aid, str):
            if aid in ids:
                errors.append("TRIAGE_DUPLICATE_ANNOTATION_ID")
            ids.add(aid)
        if row.get("candidate_id") not in candidate_ids | retired_ids:
            errors.append("TRIAGE_UNKNOWN_CANDIDATE")
        try:
            at = datetime.fromisoformat(str(row.get("annotated_at", "")).replace("Z", "+00:00"))
            if at.tzinfo is not None:
                if last is not None and at < last:
                    errors.append("TRIAGE_APPEND_ORDER_INVALID")
                last = at
        except ValueError:
            pass
    return errors


def candidate_triage_origin(task: dict, candidate: dict) -> str:
    """Do not turn a public search's market parameter into a rights territory.

    Keep retained candidates and source receipts unchanged. Only the default
    decision scope changes for v3 unlocated public cards; explicit reviewed
    country decisions remain visible through the existing ledger projection.
    """
    origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
    public_route = (candidate.get("source"), candidate.get("source_index"), candidate.get("candidate_nature"))
    query_territory = public_route in {
        ("serpapi_google_lens", "google_lens", "visual_match"),
        ("serper_images", "google_images", "visual_match"),
        ("serper_web", "google_search", "web_result"),
    }
    resolutions = candidate.get("field_resolutions")
    resolution = resolutions.get("jurisdiction") if isinstance(resolutions, dict) else None
    reviewed_origin = (isinstance(resolution, dict) and resolution.get("event_id")
                       and resolution.get("evidence_refs")
                       and str(resolution.get("selected_value") or "").upper() == origin)
    if (triage_scope_enabled(task) and task.get("retrieval_workflow_revision") == "api-first-v3"
            and candidate.get("retrieval_workflow_revision") == "api-first-v3"
            and candidate.get("right_type") == "unknown" and query_territory and not reviewed_origin):
        return UNLOCATED
    return origin


def make_annotation(task: dict, collection: str, candidate: dict, decision: dict, *,
                    evidence: dict | None = None, supplement: dict | None = None) -> dict:
    """Bind a caller-supplied decision, ID and time to the exact current basis."""
    scenarios = _scenario_view(task)
    sid = decision.get("scenario_id", task.get("primary_scenario_id"))
    if sid not in scenarios:
        raise ValueError("TRIAGE_SCENARIO_UNKNOWN")
    positioned = triage_scope_enabled(task)
    origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
    triage_origin = candidate_triage_origin(task, candidate)
    default_country = triage_origin if triage_origin in task.get("target_jurisdictions", []) else UNLOCATED
    jurisdiction = str(decision.get("jurisdiction") or
                       (default_country if positioned else origin)).upper()
    right = decision.get("right_type", candidate.get("right_type"))
    allowed_countries = set(task.get("target_jurisdictions", [])) | ({UNLOCATED} if positioned else set())
    if jurisdiction not in allowed_countries or right != candidate.get("right_type"):
        raise ValueError("TRIAGE_SCOPE_MISMATCH")
    if not light_triage_right_allowed(task, scenarios[sid], right):
        raise ValueError("TRIAGE_SCENARIO_RIGHT_MISMATCH")
    if right == "unknown" and decision.get("decision") == "selected" and not positioned:
        raise ValueError("TRIAGE_UNKNOWN_TYPE_CANNOT_BE_SELECTED")
    if positioned:
        relation = decision.get("candidate_relation")
        scope = candidate_scope_details(task, sid, right, candidate)
        included = {row["object_id"] for row in scope["objects"]
                    if row["scope_status"] == "included"}
        if (scope["status"] != "included" or not isinstance(relation, dict)
                or not _strings(relation.get("product_object_ids"))
                or not set(relation["product_object_ids"]) <= included
                ):
            raise ValueError("TRIAGE_OBJECT_SCOPE_NOT_INCLUDED")
        direction_ids = relation.get("direction_ids")
        selected_directions = {direction for item in scope["objects"]
                               if item["object_id"] in relation["product_object_ids"]
                               for direction in item["ready_direction_ids"]}
        if (not isinstance(direction_ids, list) or not all(_text(value) for value in direction_ids)
                or not set(direction_ids) <= selected_directions
                or (decision.get("decision") == "selected" and not direction_ids)):
            raise ValueError("TRIAGE_DIRECTION_BASIS_INVALID")
        gaps = relation.get("identity_gaps")
        required_gaps = ({"target_jurisdiction"} if origin != jurisdiction else set())
        if right == "unknown":
            required_gaps.add("right_type")
        if not isinstance(gaps, list) or not all(_text(value) for value in gaps) or not required_gaps <= set(gaps):
            raise ValueError("TRIAGE_IDENTITY_GAPS_REQUIRED")
    if correction_enabled(task) and isinstance(evidence, dict):
        from merge_candidates import candidate_verification_view, verification_index
        official = _snapshot_value("triage_verification_index", (evidence,),
            lambda: verification_index(evidence.get("collections", {}).get("official_verifications", [])))
        refreshed = candidate_verification_view(task, collection, candidate, evidence, official)
        if candidate_content_sha256(candidate, evidence, supplement, task=task) != candidate_content_sha256(
                refreshed, evidence, supplement, task=task):
            raise ValueError("TRIAGE_CANDIDATE_VIEW_STALE: " + str(candidate.get("candidate_id") or "")
                             + "; merge current evidence before freezing/reviewing and importing decisions")
    refs = decision.get("evidence_refs", [])
    row = {k: decision[k] for k in ("annotation_id", "decision", "reason", "reviewer", "annotated_at", "missing_information", "next_actions",
                                   "reading_level", "basis_summary", "reopen_conditions",
                                   "candidate_relation", "comparison") if k in decision}
    row.update(candidate_id=candidate.get("candidate_id"), scenario_id=sid, jurisdiction=jurisdiction,
               right_type=right, evidence_refs=refs,
               candidate_identity_fingerprint=candidate_identity_fingerprint(collection, candidate),
               product_identity_sha256=triage_product_digest(task, sid, right, candidate.get("candidate_id")), scenario_sha256=scenarios[sid]["scenario_sha256"],
               candidate_content_sha256=candidate_content_sha256(candidate, evidence, supplement, task=task),
               basis_sha256=basis_evidence_sha256(refs, evidence, supplement, candidate=candidate, task=task))
    if correction_enabled(task):
        row["workflow_correction_revision"] = CORRECTION_REVISION
    errors = annotation_errors(row, known_evidence=set(evidence_index(evidence, supplement)), task=task)
    if errors:
        raise ValueError("INVALID_TRIAGE_DECISION: " + "; ".join(errors))
    return row


def effective_decision(task: dict, ledger: dict, collection: str, candidate: dict, scenario_id: str,
                       jurisdiction: str | None = None, right_type: str | None = None, *,
                       evidence: dict | None = None, supplement: dict | None = None) -> dict:
    # Include value fields in the namespace: independently constructed equal
    # strings must address the same decision; object inputs stay identity-bound.
    key = ("effective_decision", collection, scenario_id, jurisdiction, right_type)
    return _snapshot_value(key, (task, ledger, candidate, evidence, supplement),
        lambda: _effective_decision(task, ledger, collection, candidate, scenario_id,
            jurisdiction, right_type, evidence=evidence, supplement=supplement), copy_result=True)


def _effective_decision(task: dict, ledger: dict, collection: str, candidate: dict, scenario_id: str,
                       jurisdiction: str | None = None, right_type: str | None = None, *,
                       evidence: dict | None = None, supplement: dict | None = None) -> dict:
    """Return unreviewed for absent/stale decisions; source material never selects."""
    scenarios = _scenario_view(task)
    country = (jurisdiction or candidate_triage_origin(task, candidate)).upper()
    right = right_type or candidate.get("right_type", "")
    cid = candidate.get("candidate_id", "")
    result = {"candidate_id": cid, "scenario_id": scenario_id, "scenario_sha256": scenarios.get(scenario_id, {}).get("scenario_sha256"),
              "jurisdiction": country, "right_type": right, "decision": "unreviewed", "current": False,
              "annotation": None, "reopen_reasons": [], "next_actions": []}
    if not decision_workflow_enabled(task):
        return result
    allowed_countries = set(task.get("target_jurisdictions", [])) | (
        {UNLOCATED} if triage_scope_enabled(task) else set())
    if (scenario_id not in scenarios or country not in allowed_countries
            or right != candidate.get("right_type") or ledger.get("schema_version") != LEDGER_SCHEMA_VERSION
            or ledger.get("task_id") != task.get("task_id")):
        result["reopen_reasons"] = ["TRIAGE_CONTEXT_MISMATCH"]
        return result
    if not light_triage_right_allowed(task, scenarios[scenario_id], right):
        result["reopen_reasons"] = ["TRIAGE_SCENARIO_RIGHT_MISMATCH"]
        return result
    key = decision_key(cid, scenario_id, country, right)
    def latest_annotations():
        return {decision_key(r.get("candidate_id", ""), r.get("scenario_id", ""), str(r.get("jurisdiction", "")), r.get("right_type", "")): r
                for r in ledger.get("annotations", []) if isinstance(r, dict)}
    latest = _snapshot_value("latest_annotations", (ledger,), latest_annotations)
    matching = [latest[key]] if key in latest else []
    if not matching:
        return result
    row = matching[-1]
    result["annotation"] = row
    reasons = annotation_errors(row, known_evidence=set(evidence_index(evidence, supplement)), task=task)
    if correction_enabled(task) and row.get("workflow_correction_revision") != CORRECTION_REVISION:
        reasons.append("TRIAGE_CORRECTION_REVISION_MISMATCH")
    expected = {"candidate_identity_fingerprint": candidate_identity_fingerprint(collection, candidate),
                "product_identity_sha256": triage_product_digest(task, scenario_id, right, cid), "scenario_sha256": scenarios[scenario_id]["scenario_sha256"],
                "candidate_content_sha256": candidate_content_sha256(candidate, evidence, supplement, task=task)}
    for field, digest in expected.items():
        if row.get(field) != digest:
            reasons.append("TRIAGE_BASIS_CHANGED: " + field)
    if triage_scope_enabled(task):
        scope = candidate_scope_details(task, scenario_id, right, candidate)
        relation = row.get("candidate_relation") or {}
        included = {item["object_id"] for item in scope["objects"]
                    if item["scope_status"] == "included"}
        object_ids = relation.get("product_object_ids")
        direction_ids = relation.get("direction_ids")
        selected_directions = {direction for item in scope["objects"]
                               if isinstance(object_ids, list) and item["object_id"] in object_ids
                               for direction in item["ready_direction_ids"]}
        if (scope["status"] != "included"
                or not _strings(object_ids)
                or not isinstance(direction_ids, list) or not all(_text(value) for value in direction_ids)
                or not set(object_ids) <= included
                or not set(direction_ids) <= selected_directions):
            reasons.append("TRIAGE_OBJECT_OR_DIRECTION_CHANGED")
    if task.get("triage_stage_revision"):
        from candidate_triage_stage import reopen_reason
        change_reason = reopen_reason(task, row)
        if change_reason:
            reasons.append(change_reason)
    if not reasons:
        try:
            if row["basis_sha256"] != basis_evidence_sha256(row["evidence_refs"], evidence, supplement, candidate=candidate, task=task):
                reasons.append("TRIAGE_BASIS_CHANGED: basis_sha256")
        except ValueError as exc:
            reasons.append(str(exc))
    result["reopen_reasons"] = reasons
    if not reasons:
        result.update(decision=row["decision"], current=True, next_actions=row.get("next_actions", []))
    return result


def triage_summary(task: dict, candidates: dict, ledger: dict, *, evidence: dict | None = None,
                   supplement: dict | None = None, scenario_id: str | None = None) -> dict:
    return _snapshot_value(("triage_summary", scenario_id), (task, candidates, ledger, evidence, supplement),
        lambda: _triage_summary(task, candidates, ledger, evidence=evidence,
                               supplement=supplement, scenario_id=scenario_id), copy_result=True)


def _triage_summary(task: dict, candidates: dict, ledger: dict, *, evidence: dict | None = None,
                    supplement: dict | None = None, scenario_id: str | None = None) -> dict:
    scenarios = _scenario_view(task)
    if scenario_id is not None and scenario_id not in scenarios:
        raise ValueError("TRIAGE_SCENARIO_UNKNOWN")
    result = {"counts": {d: 0 for d in (*sorted(DECISIONS), "unreviewed")}, "by_scenario": {}, "records": []}
    def ledger_countries():
        indexed = {}
        for row in ledger.get("annotations", []):
            if isinstance(row, dict):
                indexed.setdefault((row.get("candidate_id"), row.get("scenario_id")), set()).add(
                    str(row.get("jurisdiction") or "").upper())
        return indexed
    country_index = _snapshot_value("ledger_candidate_scenario_countries", (ledger,), ledger_countries)
    targets = set(task.get("target_jurisdictions", []))
    positioned = triage_scope_enabled(task)
    for sid in ([scenario_id] if scenario_id is not None else scenarios):
        counts = {d: 0 for d in (*sorted(DECISIONS), "unreviewed")}
        for collection in COLLECTIONS:
            for candidate in candidates.get(collection, []):
                if not isinstance(candidate, dict):
                    continue
                if not light_triage_right_allowed(task, scenarios[sid], candidate.get("right_type")):
                    continue
                origin = candidate_triage_origin(task, candidate)
                # A WO/EP/unknown-origin recall is not automatically locally
                # enforceable, but still needs triage; it must not disappear.
                countries = {origin} if origin in targets else ({UNLOCATED} if positioned else set(targets))
                countries.update(country_index.get((candidate.get("candidate_id"), sid), set()))
                for country in sorted(countries & (targets | ({UNLOCATED} if positioned else set()))):
                    import product_scope as ps
                    if positioned:
                        disposition = candidate_scope_details(task, sid, candidate.get("right_type"), candidate)
                        for item in disposition["objects"]:
                            if item["scope_status"] != "included":
                                result.setdefault("scope_dispositions", []).append({
                                    "candidate_id": candidate.get("candidate_id"),
                                    "scenario_id": sid, "jurisdiction": country,
                                    "right_type": candidate.get("right_type"),
                                    "object_id": item["object_id"],
                                    "scope_status": item["scope_status"],
                                    "reason": "Upstream object scope; relevance not judged",
                                    "evidence_refs": disposition.get("link_evidence_refs", [])})
                        if disposition["status"] != "included":
                            if not disposition["objects"]:
                                result.setdefault("scope_dispositions", []).append({
                                    "candidate_id": candidate.get("candidate_id"),
                                    "scenario_id": sid, "jurisdiction": country,
                                    "right_type": candidate.get("right_type"),
                                    "scope_status": disposition["status"],
                                    "reason": "Candidate object relation unresolved; relevance not judged",
                                    "evidence_refs": disposition.get("link_evidence_refs", [])})
                            continue
                    elif ps.enabled(task) and candidate.get("right_type") != "unknown":
                        disposition=ps.candidate_scope(task,sid,candidate.get('right_type'),candidate,evidence)
                        if disposition!='included':
                            result.setdefault('scope_dispositions',[]).append({'candidate_id':candidate.get('candidate_id'),
                                'scenario_id':sid,'jurisdiction':country,'right_type':candidate.get('right_type'),
                                'scope_status':disposition,'reason':'Current product object scope; not a relevance decision',
                                'evidence_refs':candidate.get('evidence_refs',[])})
                            continue
                    record = effective_decision(task, ledger, collection, candidate, sid, country, evidence=evidence, supplement=supplement)
                    result["records"].append(record)
                    counts[record["decision"]] += 1
        result["by_scenario"][sid] = {"counts": counts, "scenario_sha256": scenarios[sid]["scenario_sha256"]}
        for name, count in counts.items():
            result["counts"][name] += count
    return result


def effective_selected_candidates(task: dict, candidates: dict, ledger: dict, *, evidence: dict | None = None,
                                  supplement: dict | None = None, scenario_id: str | None = None) -> list[dict]:
    selected = [r for r in triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement,
                                         scenario_id=scenario_id)["records"]
                if r["current"] and r["decision"] == "selected"]
    if not triage_scope_enabled(task):
        return selected
    # An association-level selection is a valid triage decision, but no
    # country/right-specific source action may inherit unknown identity.
    index = {item.get("candidate_id"): item for collection in COLLECTIONS
             for item in candidates.get(collection, []) if isinstance(item, dict)}
    return [row for row in selected if row["jurisdiction"] in task.get("target_jurisdictions", [])
            and row["right_type"] in RIGHT_TYPES
            and str(index.get(row["candidate_id"], {}).get("jurisdiction") or "").upper()
                == row["jurisdiction"]]
