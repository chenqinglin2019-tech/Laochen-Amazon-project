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


def scenario_right_types(scenario: dict) -> frozenset[str]:
    kind = scenario.get("type")
    if not isinstance(kind, str) or kind not in SCENARIO_TYPES:
        raise ValueError("SCENARIO_TYPE_INVALID")
    return frozenset({"trademark_word", "trademark_figurative"}) if kind == "brand_reuse" else RIGHT_TYPES


def necessary_scenario_right_types(task: dict, scenario: dict) -> frozenset[str]:
    """Necessary work is narrower than the valid triage/assessment vocabulary.

    A reference-only entry assumption does not supply a proposed mark. Keep
    reference-mark work in brand_reuse, while retaining trade dress and other
    rights in the copied structure. This is scope, never trademark clearance.
    """
    allowed = scenario_right_types(scenario)
    if not decision_workflow_enabled(task) or scenario.get("type") != "product_entry":
        return allowed
    product = task.get("product") or {}
    supplied = any(product.get(field) for field in
        ("own_brand", "own_brand_name", "own_brand_logo", "own_logo"))
    supplied = supplied or (product.get("brand_role") == "own"
                            and any(product.get(field) for field in ("brand", "logo")))
    if product.get("input_role") == "reference_product" and not supplied:
        return allowed - {"trademark_word", "trademark_figurative"}
    return allowed


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


_OBSERVED_FIELDS = ("requested_asin", "actual_asin", "variant", "selected_variant", "title", "brand",
                    "brand_byline_raw", "brand_placeholder",
                    "manufacturer", "category", "bullets", "specifications", "visible_ip_claims",
                    "structure", "visual_features", "ocr_text", "media_identity")
_STRUCTURAL_FIELDS = ("structure", "function", "functions", "visual_features", "dimensions", "materials",
                      "material", "specifications", "shape", "color", "colours", "decoration")
_CONTEXT_FIELDS = ("requested_asin", "actual_asin", "variant", "selected_variant", "input_role",
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


def product_identity_sha256(task: dict, *, scenario_id: str | None = None, right_type: str | None = None) -> str:
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


def candidate_document_content(candidate: dict, evidence=None, supplement=None, *, task=None) -> list[dict]:
    values = []
    for entry in candidate_document_entries(candidate, evidence, supplement, task=task):
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
    documents = candidate_document_entries(candidate, evidence, supplement, task=task) if correction_enabled(task) else []
    document_refs = {entry.get("evidence_id") for entry in documents}
    contents = sorted({sha256_json(_evidence_content(index[r], candidate, task=task)) for r in refs if r in index and r not in document_refs})
    payload = {"candidate": semantic_content({k: candidate[k] for k in CANDIDATE_FACT_FIELDS if k in candidate}),
               "source_content": contents}
    if correction_enabled(task):
        payload["registered_document_content"] = candidate_document_content(candidate, evidence, supplement, task=task)
    return sha256_json(payload)


def decision_key(candidate_id: str, scenario_id: str, jurisdiction: str, right_type: str) -> tuple[str, str, str, str]:
    return candidate_id, scenario_id, jurisdiction.upper(), right_type


def next_action_errors(actions: Any, *, task: dict | None = None) -> list[str]:
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
        else:
            errors.append("NEXT_ACTION_KIND_INVALID")
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
        errors.extend(next_action_errors(annotation.get("next_actions"), task=context))
        if correction_enabled(context) and known_evidence is not None:
            for action in annotation.get("next_actions", []) if isinstance(annotation.get("next_actions"), list) else []:
                if isinstance(action, dict) and action.get("kind") == "agent_read" and _strings(action.get("evidence_refs")):
                    if not set(action["evidence_refs"]) <= known_evidence:
                        errors.append("NEXT_ACTION_UNKNOWN_EVIDENCE_REF")
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
    for row in rows:
        errors.extend(annotation_errors(row, known_evidence=known, task=task))
        if not isinstance(row, dict):
            continue
        aid = row.get("annotation_id")
        if isinstance(aid, str):
            if aid in ids:
                errors.append("TRIAGE_DUPLICATE_ANNOTATION_ID")
            ids.add(aid)
        if row.get("candidate_id") not in candidate_ids:
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


def make_annotation(task: dict, collection: str, candidate: dict, decision: dict, *,
                    evidence: dict | None = None, supplement: dict | None = None) -> dict:
    """Bind a caller-supplied decision, ID and time to the exact current basis."""
    scenarios = _scenario_view(task)
    sid = decision.get("scenario_id", task.get("primary_scenario_id"))
    if sid not in scenarios:
        raise ValueError("TRIAGE_SCENARIO_UNKNOWN")
    jurisdiction = str(decision.get("jurisdiction") or candidate.get("jurisdiction") or candidate.get("office") or "").upper()
    right = decision.get("right_type", candidate.get("right_type"))
    if jurisdiction not in task.get("target_jurisdictions", []) or right != candidate.get("right_type"):
        raise ValueError("TRIAGE_SCOPE_MISMATCH")
    if right not in scenario_right_types(scenarios[sid]):
        raise ValueError("TRIAGE_SCENARIO_RIGHT_MISMATCH")
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
                                   "reading_level", "basis_summary", "reopen_conditions") if k in decision}
    row.update(candidate_id=candidate.get("candidate_id"), scenario_id=sid, jurisdiction=jurisdiction,
               right_type=right, evidence_refs=refs,
               candidate_identity_fingerprint=candidate_identity_fingerprint(collection, candidate),
               product_identity_sha256=product_identity_sha256(task, scenario_id=sid, right_type=right), scenario_sha256=scenarios[sid]["scenario_sha256"],
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
    country = (jurisdiction or candidate.get("jurisdiction") or candidate.get("office") or "").upper()
    right = right_type or candidate.get("right_type", "")
    cid = candidate.get("candidate_id", "")
    result = {"candidate_id": cid, "scenario_id": scenario_id, "scenario_sha256": scenarios.get(scenario_id, {}).get("scenario_sha256"),
              "jurisdiction": country, "right_type": right, "decision": "unreviewed", "current": False,
              "annotation": None, "reopen_reasons": [], "next_actions": []}
    if not decision_workflow_enabled(task):
        return result
    if (scenario_id not in scenarios or country not in task.get("target_jurisdictions", [])
            or right != candidate.get("right_type") or ledger.get("schema_version") != LEDGER_SCHEMA_VERSION
            or ledger.get("task_id") != task.get("task_id")):
        result["reopen_reasons"] = ["TRIAGE_CONTEXT_MISMATCH"]
        return result
    if right not in scenario_right_types(scenarios[scenario_id]):
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
                "product_identity_sha256": product_identity_sha256(task, scenario_id=scenario_id, right_type=right), "scenario_sha256": scenarios[scenario_id]["scenario_sha256"],
                "candidate_content_sha256": candidate_content_sha256(candidate, evidence, supplement, task=task)}
    for field, digest in expected.items():
        if row.get(field) != digest:
            reasons.append("TRIAGE_BASIS_CHANGED: " + field)
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
    for sid in ([scenario_id] if scenario_id is not None else scenarios):
        counts = {d: 0 for d in (*sorted(DECISIONS), "unreviewed")}
        for collection in COLLECTIONS:
            for candidate in candidates.get(collection, []):
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("right_type") not in scenario_right_types(scenarios[sid]):
                    continue
                origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
                # A WO/EP/unknown-origin recall is not automatically locally
                # enforceable, but still needs triage; it must not disappear.
                countries = {origin} if origin in targets else set(targets)
                countries.update(country_index.get((candidate.get("candidate_id"), sid), set()))
                for country in sorted(countries & targets):
                    record = effective_decision(task, ledger, collection, candidate, sid, country, evidence=evidence, supplement=supplement)
                    result["records"].append(record)
                    counts[record["decision"]] += 1
        result["by_scenario"][sid] = {"counts": counts, "scenario_sha256": scenarios[sid]["scenario_sha256"]}
        for name, count in counts.items():
            result["counts"][name] += count
    return result


def effective_selected_candidates(task: dict, candidates: dict, ledger: dict, *, evidence: dict | None = None,
                                  supplement: dict | None = None, scenario_id: str | None = None) -> list[dict]:
    return [r for r in triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement,
                                     scenario_id=scenario_id)["records"] if r["current"] and r["decision"] == "selected"]
