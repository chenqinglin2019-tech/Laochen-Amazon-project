"""Read-only validation of retained source evidence, never a new source receipt.

Only an individually complete original action is reusable. Multi-query page
series and candidate-ID remapping deliberately fail closed in this adapter.
The caller still authorizes the current plan and checks the current triage.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import re
from urllib.parse import urlparse

from common import load_json, load_skill_config, parse_iso, plan_free_policy_matches_task, sha256_file, sha256_json
from decision_workflow import (decision_workflow_enabled, product_identity_sha256,
                               scenario_index, scenario_right_types, semantic_content, product_identity_content,
                               correction_enabled, observed_product_sha256, _snapshot_value)

KIND = "historical_source_reuse"
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIERS = ("publication_number", "registration_number", "application_number", "serial_number", "record_number")
BROWSER_PROVIDERS = {"uspto_patent_browser", "uspto_tmsearch_browser", "uspto_tsdr"}
OFFICIAL_PROVIDERS = BROWSER_PROVIDERS | {"epo_ops", "euipo_trademark", "euipo_design", "jpo_api",
                                          "inpi_api", "prv_open_data", "epo_publication_server"}


def historical_evidence_root(task, supplement, explicit=None) -> Path | None:
    """Resolve an explicit, digest-bound root; conflicting declarations fail."""
    values = ([explicit] if explicit is not None else [])
    if isinstance(supplement, dict) and "evidence_root" in supplement:
        values.append(supplement["evidence_root"])
    if isinstance(task, dict) and "historical_evidence_root" in task:
        values.append(task["historical_evidence_root"])
    roots = []
    for value in values:
        _require(isinstance(value, (str, Path)) and bool(str(value).strip()), "HISTORICAL_EVIDENCE_ROOT_INVALID")
        path = Path(value).expanduser()
        _require(path.is_absolute(), "HISTORICAL_EVIDENCE_ROOT_MUST_BE_ABSOLUTE")
        path = path.resolve()
        _require(path.is_dir(), "HISTORICAL_EVIDENCE_ROOT_MISSING")
        roots.append(path)
    _require(len(set(roots)) <= 1, "HISTORICAL_EVIDENCE_ROOT_CONFLICT")
    return roots[0] if roots else None


def observed_product_identity_sha256(task) -> str:
    """Bind the observed object, not previous assessment intentions or analysis."""
    product = task.get("product", {})
    if correction_enabled(task):
        return observed_product_sha256(product)
    raw = product.get("raw_capture") or {}
    fields = ("requested_asin", "actual_asin", "variant", "selected_variant", "title", "brand", "manufacturer",
              "bullets", "specifications", "visible_ip_claims", "structure", "visual_features", "ocr_text")
    observed = {key: raw[key] for key in fields if isinstance(raw, dict) and key in raw}
    # Core identifiers must remain equal even when one input has richer analysis.
    core = {key: product.get(key) for key in ("requested_asin", "actual_asin", "variant", "selected_variant")}
    hashes = set()
    for image in [*task.get("images", []), product.get("main_visual", {})]:
        if isinstance(image, dict) and image.get("sha256"):
            _require(isinstance(image["sha256"], str) and HASH_RE.fullmatch(image["sha256"]), "HISTORICAL_PRODUCT_IMAGE_HASH_INVALID")
            hashes.add(image["sha256"])
    _require(any(_text(core.get(key)) for key in ("requested_asin", "actual_asin")), "HISTORICAL_OBSERVED_PRODUCT_IDENTITY_MISSING")
    return sha256_json({"identifiers": semantic_content(core), "raw_observations": product_identity_content(observed),
                        "original_image_sha256": sorted(hashes)})


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _retained_browser_capture(source, raw, provider, old_dir, root):
    """Select a whole original TSDR capture, never repair or combine its fields.

    record_tsdr_browser_verification passes the capture through record_result's
    JSON sanitizer. That strips URL fragments and redacts the CDP session ID.
    Only these two observed, non-content transformations are accepted here;
    the full original receipt is still checked against the original old plan.
    """
    if "capture" not in source:
        return raw
    _require(provider == "uspto_tsdr", "HISTORICAL_ORIGINAL_CAPTURE_PROVIDER_UNSUPPORTED")
    path = _file(source["capture"], root)
    _require(path.is_relative_to(old_dir.resolve()), "HISTORICAL_ORIGINAL_CAPTURE_OUTSIDE_TASK")
    capture = load_json(path)
    _require(isinstance(capture, dict) and isinstance(raw, dict), "HISTORICAL_BROWSER_CAPTURE_INVALID")
    _require(isinstance(capture.get("query_execution"), dict)
             and capture["query_execution"] == raw.get("query_execution"),
             "HISTORICAL_ORIGINAL_CAPTURE_RECEIPT_MISMATCH")
    from provider_utils import sanitize_for_evidence
    projected = deepcopy(capture)
    for field in ("final_url", "cdp_session_id"):
        if field in projected:
            projected[field] = sanitize_for_evidence(projected[field], field)
    _require(capture == raw or projected == raw, "HISTORICAL_ORIGINAL_CAPTURE_CONTENT_MISMATCH")
    return capture


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _file(binding, root):
    _require(isinstance(binding, dict) and _text(binding.get("path"))
             and isinstance(binding.get("sha256"), str) and HASH_RE.fullmatch(binding["sha256"])
             and type(binding.get("bytes")) is int and binding["bytes"] >= 0, "HISTORICAL_FILE_BINDING_INVALID")
    path = (root / binding["path"]).resolve()
    _require(path.is_relative_to(root) and path.is_file(), "HISTORICAL_FILE_OUTSIDE_ROOT_OR_MISSING")
    _require(path.stat().st_size == binding["bytes"] and sha256_file(path) == binding["sha256"],
             "HISTORICAL_FILE_HASH_OR_SIZE_MISMATCH")
    return path


def _declared_files(value, root):
    """Check all declared files, including screenshot_path/hash style bindings."""
    from assessment_estimate import _verify_declared_artifacts
    _declared_paths(value, root)
    _verify_declared_artifacts(value, root, set())


def _declared_product_files(product, root):
    """Clue source_path is a hash-bound field locator, not a file path."""
    from workflow_v24 import product_clue_inventory
    projected = deepcopy(product)
    clues = {item["source_path"]: item["source_sha256"]
             for item in product_clue_inventory({"product": product})}
    analysis = projected.get("analysis") or {}
    rows = analysis.get("clue_dispositions", []) if isinstance(analysis, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("source_path") in clues:
            _require(row.get("source_sha256") == clues[row["source_path"]],
                     "HISTORICAL_PRODUCT_CLUE_HASH_MISMATCH")
            row.pop("source_path")
    # Every other path, including an unrecognized locator, retains the normal
    # containment/existence/hash checks; the original product is untouched.
    _declared_files(projected, root)


def _declared_paths(value, root):
    if isinstance(value, dict):
        for key, raw in value.items():
            if isinstance(raw, str) and (key == "path" or key.endswith("_path")) and raw:
                path = (root / raw).resolve()
                _require(path.is_relative_to(root) and path.is_file(), "HISTORICAL_ARTIFACT_OUTSIDE_ROOT_OR_MISSING")
            _declared_paths(raw, root)
    elif isinstance(value, list):
        for item in value:
            _declared_paths(item, root)


def _dates(value):
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"checked_at", "source_checked_at"} and item not in (None, ""):
                result.append(item)
            result.extend(_dates(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_dates(item))
    return result


def _original_date(run, entries):
    limit = float(load_skill_config().get("performance", {}).get("dynamic_evidence_max_age_hours", 48))
    _require(math.isfinite(limit) and limit > 0, "HISTORICAL_FRESHNESS_CONFIG_INVALID")
    immutable = run.get("provider") == "epo_publication_server" and run.get("operation") == "document_retrieval"
    values = [run.get("finished_at"), *_dates(entries)]
    parsed = []
    for value in values:
        _require(_text(value), "HISTORICAL_SOURCE_DATE_MISSING")
        date = parse_iso(value)
        _require(date.tzinfo is not None, "HISTORICAL_SOURCE_DATE_TIMEZONE_REQUIRED")
        age = (datetime.now(timezone.utc) - date).total_seconds() / 3600
        _require(age >= 0 and (immutable or age <= limit), "HISTORICAL_SOURCE_STALE_OR_FUTURE")
        parsed.append((date, value))
    return min(parsed)[1]


def _normalized(value):
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _same_record(record, candidate, row):
    field = next((key for key in IDENTIFIERS if record.get(key)), None)
    return (field is not None and _normalized(record[field]) == _normalized(candidate.get(field))
            and candidate.get("right_type") == (record.get("right_type") or row.get("right_type"))
            and candidate.get("jurisdiction") == (record.get("jurisdiction") or row.get("jurisdiction")))


def _candidate_rows(candidates, task):
    _require(isinstance(candidates, dict) and candidates.get("task_id") == task.get("task_id")
             and candidates.get("schema_version") == task.get("schema_version"), "HISTORICAL_NEW_CANDIDATE_IDENTITY_MISMATCH")
    rows = []
    for name in ("patents", "trademarks", "copyright_assets", "enforcement"):
        values = candidates.get(name, [])
        _require(isinstance(values, list) and all(isinstance(value, dict) for value in values), "HISTORICAL_CANDIDATES_INVALID")
        rows.extend(values)
    ids = [row.get("candidate_id") for row in rows]
    _require(all(_text(value) for value in ids) and len(ids) == len(set(ids)), "HISTORICAL_CANDIDATES_INVALID")
    return rows


def _validate_item(task, provider, row, candidates, item, evidence_root):
    from assessment_estimate import validate_supplement
    from assessment_v24 import bound_runs, evidence_index, query_coverage, _entry_matches_run, _source_records
    from finalize_assessment import _authoritative_run
    from provider_utils import PLAN_META_KEYS
    from runtime_v24 import source_files_complete
    from verify_recall_acceptance import nonproduction

    _require(decision_workflow_enabled(task), "HISTORICAL_SCENARIO_WORKFLOW_REQUIRED")
    _require(provider in OFFICIAL_PROVIDERS, "HISTORICAL_PROVIDER_UNSUPPORTED")
    _require(evidence_root is not None, "HISTORICAL_EVIDENCE_ROOT_REQUIRED")
    root = Path(evidence_root).resolve()
    _require(item.get("kind") == KIND, "HISTORICAL_KIND_INVALID")
    # A retention check is never a source query date, even when equal by chance.
    _require(item.get("checked_at_meaning") == "retained_file_hash_verification", "HISTORICAL_CHECKED_AT_MEANING_REQUIRED")
    source, binding = item.get("historical_source"), item.get("reuse_binding")
    _require(isinstance(source, dict) and isinstance(binding, dict), "HISTORICAL_BINDING_REQUIRED")
    scenarios = scenario_index(task)
    sid = binding.get("scenario_id")
    _require(sid in scenarios and binding.get("scenario_sha256") == scenarios[sid]["scenario_sha256"], "HISTORICAL_SCENARIO_MISMATCH")
    _require(row.get("right_type") in scenario_right_types(scenarios[sid]), "HISTORICAL_SCENARIO_RIGHT_MISMATCH")
    row_bindings = row.get("scenario_bindings") or [{"scenario_id": row.get("scenario_id"), "scenario_sha256": row.get("scenario_sha256")}]
    _require(isinstance(row_bindings, list) and {"scenario_id": sid, "scenario_sha256": binding["scenario_sha256"]} in row_bindings
             and row.get("decision_workflow_revision") == task["decision_workflow_revision"], "HISTORICAL_NEW_ROW_SCENARIO_MISMATCH")
    _require(all(binding.get(key) == row.get(key) and _text(binding.get(key))
                 for key in ("jurisdiction", "right_type", "action_purpose")), "HISTORICAL_SCOPE_OR_PURPOSE_MISMATCH")
    _require(_text(binding.get("reviewer")) and _text(binding.get("reasoning")), "HISTORICAL_REVIEW_REQUIRED")
    product_hash = product_identity_sha256(task, scenario_id=sid, right_type=row.get("right_type"))
    _require(binding.get("product_identity_sha256") == product_hash, "HISTORICAL_PRODUCT_MISMATCH")

    # Reject unrelated scenario/scope/purpose bindings before touching their
    # retained files. A matching binding still receives every original hash,
    # path, plan, receipt, date and payload check below on each validation call.
    validate_supplement({"schema": "HISTORICAL-REUSE/1.0", "evidence": [item]}, root)

    evidence_path = _file(item, root)
    task_path, plan_path = _file(source.get("task"), root), _file(source.get("plan"), root)
    _require(task_path.name == "task.json" and evidence_path.name == "evidence.json" and plan_path.name == "search-plan.json"
             and task_path.parent == evidence_path.parent == plan_path.parent, "HISTORICAL_SOURCE_LAYOUT_MISMATCH")
    old_task, old_evidence, old_plan = load_json(task_path), load_json(evidence_path), load_json(plan_path)
    _require(all(isinstance(value, dict) for value in (old_task, old_evidence, old_plan)), "HISTORICAL_SOURCE_DOCUMENT_INVALID")
    _require(_text(old_task.get("task_id")) and old_task["task_id"] != task.get("task_id")
             and all(value.get("task_id") == old_task["task_id"] and value.get("schema_version") == "2.4-free"
                     for value in (old_task, old_evidence, old_plan))
             and plan_free_policy_matches_task(old_task, old_plan), "HISTORICAL_SOURCE_IDENTITY_OR_POLICY_MISMATCH")
    original_identity = observed_product_sha256(old_task.get("product", {})) if correction_enabled(task) else observed_product_identity_sha256(old_task)
    _require(original_identity == observed_product_identity_sha256(task), "HISTORICAL_ORIGINAL_PRODUCT_MISMATCH")
    _require(not nonproduction([old_task, old_plan]), "HISTORICAL_NON_PRODUCTION_OR_NON_AUTHORITATIVE")
    _declared_files(old_task.get("images", []), task_path.parent)
    _declared_product_files(old_task.get("product", {}), task_path.parent)
    queries = old_plan.get("queries", {})
    _require(isinstance(queries, dict), "HISTORICAL_PLAN_INVALID")
    matches = [(name, value) for name, values in queries.items() if isinstance(values, list)
               for value in values if isinstance(value, dict) and value.get("query_id") == source.get("query_id")]
    _require(len(matches) == 1 and matches[0][0] == provider, "HISTORICAL_QUERY_IDENTITY_MISMATCH")
    original = matches[0][1]
    _require(source.get("plan_entry_sha256") == sha256_json(original), "HISTORICAL_PLAN_ENTRY_HASH_MISMATCH")
    _require(all(original.get(key) == row.get(key) for key in ("operation", "jurisdiction", "right_type")), "HISTORICAL_EXTERNAL_SCOPE_MISMATCH")
    _require({key: value for key, value in original.items() if key not in PLAN_META_KEYS}
             == {key: value for key, value in row.items() if key not in PLAN_META_KEYS}, "HISTORICAL_EXTERNAL_PARAMS_MISMATCH")
    _require(original.get("candidate_id") == row.get("candidate_id"), "HISTORICAL_CANDIDATE_REMAP_UNSUPPORTED")
    runs = bound_runs(old_evidence, old_plan, provider, original)
    selected = [run for run in runs if run.get("run_id") == source.get("run_id")]
    _require(len(selected) == 1 and len([r for r in old_evidence.get("source_runs", []) if r.get("run_id") == source.get("run_id")]) == 1,
             "HISTORICAL_RUN_BINDING_MISMATCH")
    run = selected[0]
    # A later failed/corrected attempt cannot be hidden by pointing to old success.
    attempts = [value for value in old_evidence.get("source_runs", []) if value.get("provider") == provider
                and value.get("query_id") == original["query_id"] and value.get("plan_entry_sha256") == sha256_json(original)]
    _require(attempts[-1] == run and run.get("status") in {"success", "no_result"} and not run.get("error_code"), "HISTORICAL_RUN_NOT_LATEST_SUCCESS")
    document_only = row.get("action_purpose") == "document_content" and provider == "epo_publication_server"
    _require(provider != "epo_publication_server" or document_only, "HISTORICAL_PUBLICATION_CANNOT_PROVE_STATUS_OR_RECALL")
    _require(_authoritative_run(old_evidence, run) and (document_only or run.get("authoritative_for_final_rating") is not False)
             and str(run.get("source_environment") or "production").casefold() == "production", "HISTORICAL_NON_PRODUCTION_OR_NON_AUTHORITATIVE")
    _require(source_files_complete(task_path.parent, old_evidence, run), "HISTORICAL_ORIGINAL_FILES_INVALID")
    index = evidence_index(old_evidence)
    entries = [entry for entry in index.values() if _entry_matches_run(entry, run)]
    _require(not nonproduction([run, *entries]), "HISTORICAL_NON_PRODUCTION_OR_NON_AUTHORITATIVE")
    ids = source.get("evidence_ids")
    _require(isinstance(ids, list) and ids and all(_text(value) for value in ids) and len(ids) == len(set(ids))
             and set(ids) == {entry["evidence_id"] for entry in entries}, "HISTORICAL_EVIDENCE_IDS_INCOMPLETE_OR_MISMATCH")
    _declared_files(entries, task_path.parent)
    original_date = _original_date(run, entries)
    _require(item.get("source_checked_at") == original_date, "HISTORICAL_SOURCE_DATE_MISMATCH")
    if provider in BROWSER_PROVIDERS:
        from record_browser_execution import validate_browser_execution
        raw_capture = load_json((task_path.parent / run["raw_paths"][0]).resolve())
        capture = _retained_browser_capture(source, raw_capture, provider, task_path.parent, root)
        _require(isinstance(capture, dict) and not nonproduction(capture), "HISTORICAL_BROWSER_CAPTURE_INVALID")
        parsed = urlparse(str(capture.get("final_url") or ""))
        config_key = "tsdr" if provider == "uspto_tsdr" else provider
        allowed = load_skill_config().get("providers", {}).get(config_key, {}).get("browser_allowed_hosts", [])
        _require(parsed.scheme == "https" and parsed.hostname in allowed, "HISTORICAL_BROWSER_OFFICIAL_HOST_REQUIRED")
        validate_browser_execution(capture, old_task, task_path.parent, provider)
        # Raw captures may bind a screenshot through receipt.events rather than
        # duplicate its hash next to screenshot_path. The original validator
        # verifies that binding; normalized entries above verify retained media.
        _declared_paths(capture, task_path.parent)
        if row.get("action_purpose") == "recall":
            raw_records = capture.get("candidates")
            normalized_records = _source_records(old_evidence, run["run_id"])
            _require(isinstance(raw_records, list) and isinstance(normalized_records, list)
                     and len(raw_records) == len(normalized_records), "HISTORICAL_BROWSER_NORMALIZATION_MISMATCH")
            unmatched = list(normalized_records)
            for record in raw_records:
                _require(isinstance(record, dict), "HISTORICAL_BROWSER_NORMALIZATION_MISMATCH")
                field = next((key for key in IDENTIFIERS if record.get(key)), None)
                alternate = "serial_number" if provider == "uspto_tmsearch_browser" and field == "application_number" else field
                matches = [value for value in unmatched if field and _normalized(record[field])
                           == _normalized(value.get(field) or value.get(alternate))]
                _require(len(matches) == 1, "HISTORICAL_BROWSER_NORMALIZATION_MISMATCH")
                unmatched.remove(matches[0])

    current_candidates = _candidate_rows(candidates, task)
    purpose = row["action_purpose"]
    base = {"complete": True, "retrieval_complete": False, "triage_complete": False,
            "source_task_id": old_task["task_id"], "source_query_id": original["query_id"],
            "source_plan_entry_sha256": sha256_json(original), "source_run_id": run["run_id"],
            "source_run_sha256": sha256_json(run), "source_checked_at": original_date,
            "evidence_ids": list(ids), "evidence_refs": [item["evidence_id"]],
            "source_evidence_sha256": {entry["evidence_id"]: sha256_json(entry) for entry in entries},
            "reuse_evidence_id": item["evidence_id"], "authority_scope": "original_source_only",
            "scenario_id": sid, "scenario_sha256": binding["scenario_sha256"],
            "jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
            "action_purpose": purpose, "reason": binding["reasoning"]}
    if "capture" in source:
        _require(provider == "uspto_tsdr", "HISTORICAL_ORIGINAL_CAPTURE_PROVIDER_UNSUPPORTED")
        base["source_capture"] = deepcopy(source["capture"])
        base["source_capture_normalization"] = "tsdr-retained-url-session-v1"
    payloads = [entry.get("payload") for entry in entries]
    if purpose == "recall":
        records = _source_records(old_evidence, run["run_id"])
        _require(isinstance(records, list), "HISTORICAL_SOURCE_RECORDS_MISSING")
        retained = []
        for record in records:
            found = [candidate for candidate in current_candidates if _same_record(record, candidate, original)]
            _require(len(found) == 1, "HISTORICAL_ORIGINAL_RESULT_NOT_RETAINED")
            _require(item["evidence_id"] in found[0].get("evidence_refs", []), "HISTORICAL_NEW_CANDIDATE_PROVENANCE_MISSING")
            retained.append(found[0]["candidate_id"])
        _require(len(retained) == len(set(retained)), "HISTORICAL_DUPLICATE_ORIGINAL_RECORDS")
        # A temporary read-only lineage projection evaluates raw retrieval under
        # the current contract, without creating source runs or trusting old review.
        projected = deepcopy(candidates)
        for values in projected.values():
            if isinstance(values, list):
                for candidate in values:
                    if isinstance(candidate, dict) and candidate.get("candidate_id") in retained:
                        candidate.setdefault("evidence_refs", []).extend(ids)
        selected_evidence = {**old_evidence, "source_runs": [run],
                             "collections": {"retained": entries}}
        coverage = query_coverage(selected_evidence, projected, old_plan, provider, original, task,
                                  strict_lineage=True, scenario_id=sid)
        _require(coverage.get("retrieval_complete") is True, "HISTORICAL_RETRIEVAL_INCOMPLETE:" + str(coverage.get("gap")))
        base.update(retrieval_complete=True, authority_scope="original_recall", source_records=deepcopy(records),
                    retained_candidate_ids=sorted(set(retained)), source_coverage=coverage)
    elif purpose in {"official_verification", "document_content"}:
        records = [record for payload in payloads
                   for record in (payload if isinstance(payload, list) else payload.get("candidates", [payload]) if isinstance(payload, dict) else [])
                   if isinstance(record, dict)]
        found_candidates = [candidate for candidate in current_candidates if candidate.get("candidate_id") == row.get("candidate_id")]
        _require(len(found_candidates) == 1, "HISTORICAL_DEEP_CANDIDATE_MISSING")
        matched = [record for record in records if record.get("candidate_id") == row.get("candidate_id") and _same_record(record, found_candidates[0], row)]
        _require(bool(matched), "HISTORICAL_DEEP_RECORD_IDENTITY_MISMATCH")
        if purpose == "official_verification":
            accepted = [record for record in matched if record.get("official_verification", {}).get("status") == "verified"
                        and record["official_verification"].get("identity_match") is True
                        and _text(record["official_verification"].get("legal_status"))
                        and _text(record["official_verification"].get("checked_at"))
                        and record.get("authority_scope") != "published_document_only"]
            _require(bool(accepted), "HISTORICAL_OFFICIAL_VERIFICATION_INVALID")
            base["authority_scope"] = "original_official_verification"
        else:
            accepted = [record for record in matched if record.get("authority_scope") == "published_document_only"
                        and (record.get("document_identity_match") is True or record.get("official_verification", {}).get("identity_match") is True)
                        and any(record.get(key) for key in ("claims", "claim_text", "document_text", "description"))]
            _require(bool(accepted), "HISTORICAL_DOCUMENT_CONTENT_INVALID")
            base["authority_scope"] = "published_document_only"
        base["payload"] = deepcopy(accepted)
    else:
        raise ValueError("HISTORICAL_ACTION_PURPOSE_UNSUPPORTED")
    return base


def _results(task, provider, row, candidates, supplement, evidence_root):
    if supplement is None:
        return [], []
    if not isinstance(supplement, dict) or not isinstance(supplement.get("evidence"), list):
        return [], ["HISTORICAL_SUPPLEMENT_INVALID"]
    try:
        evidence_root = historical_evidence_root(task, supplement, evidence_root)
    except (OSError, TypeError, ValueError) as exc:
        return [], [str(exc)]
    all_ids = [item.get("evidence_id") for item in supplement["evidence"] if isinstance(item, dict)]
    if len(all_ids) != len(set(str(value) for value in all_ids)):
        return [], ["HISTORICAL_DUPLICATE_EVIDENCE_ID"]
    results, errors = [], []
    items = supplement["evidence"]
    if correction_enabled(task):
        def scope_index():
            result = {}
            for item in items:
                binding = item.get("reuse_binding") if isinstance(item, dict) else None
                if isinstance(binding, dict) and item.get("kind") == KIND:
                    key = tuple(binding.get(field) for field in ("scenario_id", "jurisdiction", "right_type", "action_purpose"))
                    if all(isinstance(value, str) and value for value in key):
                        result.setdefault(key, []).append(item)
            return result
        indexed = _snapshot_value("historical_scope_descriptors", (items,), scope_index)
        bindings = row.get("scenario_bindings") or [{"scenario_id": row.get("scenario_id")}]
        items = [item for binding in bindings if isinstance(binding, dict) and isinstance(binding.get("scenario_id"), str)
                 for item in indexed.get((binding.get("scenario_id"), row.get("jurisdiction"),
                                          row.get("right_type"), row.get("action_purpose")), [])]
        # Preselection only rejects obviously unrelated bindings. Matching
        # descriptors still recheck all source files on every validation call.
        items = [item for item in items if item["reuse_binding"].get("product_identity_sha256") ==
                 product_identity_sha256(task, scenario_id=item["reuse_binding"]["scenario_id"], right_type=row.get("right_type"))]
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != KIND:
            continue
        try:
            results.append(_validate_item(task, provider, row, candidates, item, evidence_root))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
            errors.append(str(item.get("evidence_id") or "") + ":" + str(exc))
    return results, errors


def historical_action_reuse(task, provider, row, candidates, supplement, evidence_root) -> dict | None:
    """Return validated old provenance, or None. This never grants dispatch authority."""
    results, _ = _results(task, provider, row, candidates, supplement, evidence_root)
    return results[0] if len(results) == 1 else None


def historical_action_reuse_errors(task, provider, row, candidates, supplement, evidence_root) -> list[str]:
    """Read-only diagnostics; a failed reuse remains an ordinary unfinished action."""
    results, errors = _results(task, provider, row, candidates, supplement, evidence_root)
    return errors + (["HISTORICAL_AMBIGUOUS_REUSE"] if len(results) > 1 else [])
