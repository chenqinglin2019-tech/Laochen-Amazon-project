"""Read-only obligation credit from original facts; never a replacement receipt.

Current triage authorizes the target, whereas an earlier action's immutable plan
and receipt establish its facts. Unsupported sources remain ordinary gaps.
"""
from copy import deepcopy
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
import json
import re

from common import load_json, parse_iso, sha256_file, sha256_json
from historical_evidence import (_declared_files, _declared_paths, _original_date,
                                 _retained_browser_capture, _require, historical_evidence_root)


def _production(value):
    from verify_recall_acceptance import nonproduction
    if nonproduction(value):
        return False
    if isinstance(value, dict):
        for key in ("source_environment", "environment"):
            if key in value and str(value[key]).casefold() != "production":
                return False
        return all(_production(item) for item in value.values())
    return all(_production(item) for item in value) if isinstance(value, list) else True


def _task_directory(task, plan, evidence, run, explicit, root):
    """Resolve only the source's own ancestors, never search a workspace."""
    paths = [Path(explicit).resolve()] if explicit is not None else []
    if not paths:
        for value in run.get("raw_paths", []):
            path = Path(value)
            if path.is_absolute():
                paths.extend(list(path.resolve().parents)[:4])
    found = []
    for path in dict.fromkeys(paths):
        if root is not None and not path.is_relative_to(root):
            continue
        if not all((path / name).is_file() for name in ("task.json", "search-plan.json", "evidence.json")):
            continue
        # finalize() changes only these execution/output fields. Every other
        # field (including unknown future business fields) remains exact.
        projection = lambda value: {key: item for key, item in value.items()
                                    if key not in {"state", "history", "updated_at", "outputs"}}
        if (projection(load_json(path / "task.json")) == projection(task)
                and load_json(path / "search-plan.json") == plan and load_json(path / "evidence.json") == evidence):
            found.append(path)
    _require(len(found) == 1, "SAME_TASK_INPUT_CONTEXT_MISMATCH")
    return found[0]


def _capture(task_dir, task, raw, source):
    from record_browser_execution import validate_browser_execution
    query_id = source["query_id"]
    _require(isinstance(query_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", query_id), "SAME_TASK_QUERY_ID_INVALID")
    # A scheduler disposition may no longer retain capture_path. Enumerate a
    # bounded set of same-query files, then compare the WHOLE original capture
    # with hash-bound raw. No URL construction or field splicing is permitted.
    paths = list(islice(task_dir.glob("uspto_tsdr-" + query_id + "-*-capture.json"), 33))
    _require(len(paths) <= 32, "SAME_TASK_CAPTURE_LOOKUP_BOUND")
    options = [(raw, None)]
    for path in sorted(paths):
        if not path.resolve().is_relative_to(task_dir) or not path.is_file():
            continue
        binding = {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        try:
            value = _retained_browser_capture({"capture": binding}, raw, "uspto_tsdr", task_dir, task_dir)
            options.append((value, binding))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    for capture, binding in options:
        try:
            _require(capture.get("status") == "success" and capture.get("query_id") == query_id
                     and _production(capture), "SAME_TASK_CAPTURE_NOT_REAL_SUCCESS")
            validation = validate_browser_execution(capture, task, task_dir, "uspto_tsdr")
            receipt = load_json(Path(capture["query_execution"]["path"]))
            _require(receipt.get("query_id") == query_id and receipt.get("plan_entry_sha256") == sha256_json(source)
                     and _production(receipt), "SAME_TASK_RECEIPT_NOT_PRODUCTION_OR_SOURCE_MISMATCH")
            _declared_paths(capture, task_dir)
            return capture, binding, validation
        except (OSError, ValueError, TypeError, KeyError):
            continue
    raise ValueError("SAME_TASK_ORIGINAL_CAPTURE_UNVERIFIED")


def _official(task, plan, evidence, candidate, provider, target, *, task_dir, root):
    from assessment_v24 import bound_runs, evidence_index, _entry_matches_run, official_refs
    from provider_utils import PLAN_META_KEYS, sanitize_for_evidence
    from record_tsdr_browser_verification import validate_common, normalize_success
    from runtime_v24 import source_files_complete
    if (provider != "uspto_tsdr" or target.get("jurisdiction") != "US"
            or target.get("right_type") not in {"trademark_word", "trademark_figurative"}):
        return None
    serial = str(candidate.get("serial_number") or "")
    _require(re.fullmatch(r"\d{8}", serial) and target.get("q") == serial
             and target.get("serial_number") == serial, "SAME_TASK_TARGET_RECORD_MISMATCH")
    refs = official_refs(task, evidence, plan, candidate, "US", target["right_type"])
    index = evidence_index(evidence)
    def external(row):
        params = {key: value for key, value in row.items() if key not in PLAN_META_KEYS}
        # TSDR candidate navigation already compiles these defaults regardless
        # of their presence; the original automatic receipt is still mandatory.
        params.setdefault("mode", "agent")
        params.setdefault("strategy", "record_number")
        return params
    for source in plan.get("queries", {}).get(provider, []):
        if (source.get("query_id") == target["query_id"] or external(source) != external(target)
                or any(source.get(key) != target.get(key) for key in ("operation", "jurisdiction", "right_type", "candidate_id"))):
            continue
        runs = bound_runs(evidence, plan, provider, source)
        if not runs:
            continue
        run = runs[-1]
        attempts = [value for value in evidence.get("source_runs", []) if value.get("provider") == provider
                    and value.get("query_id") == source["query_id"]]
        entries = [value for value in index.values() if _entry_matches_run(value, run)]
        accepted = [entry for entry in entries if entry["evidence_id"] in refs]
        if (not accepted or attempts[-1] != run or run.get("status") != "success" or run.get("error_code")
                or run.get("authoritative_for_final_rating") is False or not _production([run, entries])):
            continue
        try:
            directory = _task_directory(task, plan, evidence, run, task_dir, root)
            _require(source_files_complete(directory, evidence, run), "SAME_TASK_SOURCE_FILES_INVALID")
            _declared_files(entries, directory)
            checked_at = _original_date(run, entries)
            raw = load_json((directory / run["raw_paths"][0]).resolve())
            capture, capture_binding, _ = _capture(directory, task, raw, source)
            _require(capture.get("candidate_id") == candidate["candidate_id"]
                     and capture.get("right_type") == target["right_type"], "SAME_TASK_CAPTURE_CANDIDATE_MISMATCH")
            common = validate_common(capture, task, {"tsdr.uspto.gov"}, directory, "success")
            expected = sanitize_for_evidence(normalize_success(capture, common, candidate["candidate_id"]))
            # Facts must derive from this complete original capture, not merely
            # share an EV/serial. Permit extra metadata, never changed content.
            accepted = [entry for entry in accepted if isinstance(entry.get("payload"), dict)
                        and all(entry["payload"].get(key) == value for key, value in expected.items())]
            _require(bool(accepted), "SAME_TASK_NORMALIZED_FACTS_MISMATCH")
            _require(str(expected["case_status"]).strip().casefold() not in {"unknown", "unavailable", "not checked"},
                     "SAME_TASK_CURRENT_STATUS_MISSING")
            return {"authority_scope": "original_official_verification", "source_task_id": task["task_id"],
                    "source_query_id": source["query_id"], "source_plan_entry_sha256": sha256_json(source),
                    "source_run_id": run["run_id"], "source_run_sha256": sha256_json(run),
                    "source_checked_at": checked_at, "evidence_refs": [entry["evidence_id"] for entry in accepted],
                    "source_evidence_sha256": {entry["evidence_id"]: sha256_json(entry) for entry in accepted},
                    "source_query_execution": deepcopy(capture["query_execution"]),
                    "source_capture": capture_binding, "source_payload_digest": run["payload_digest"]}
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            continue
    return None


def _document(candidate, target, supplement, root):
    from assessment_estimate import validate_supplement, _published_supplement_binds_candidate
    if not isinstance(supplement, dict) or root is None:
        return None
    number = target.get("document") or target.get("record_number") or target.get("q")
    if (number != candidate.get("publication_number") or target.get("jurisdiction") != "US"
            or target.get("right_type") != candidate.get("right_type")):
        return None
    items = [item for item in supplement.get("evidence", []) if isinstance(item, dict)
             and _published_supplement_binds_candidate(item, candidate)]
    for item in items:
        try:
            _require(_production(item), "SAME_TASK_DOCUMENT_NOT_PRODUCTION")
            validate_supplement({"schema": "EXISTING-DOCUMENT/1.0", "evidence": [item]}, root)
            checked_at = item.get("source_checked_at") or item["checked_at"]
            _require(item.get("checked_at_meaning") != "retained_file_hash_verification" or item.get("source_checked_at"),
                     "SAME_TASK_ORIGINAL_DOCUMENT_DATE_REQUIRED")
            for value in (checked_at, item["checked_at"]):
                date = parse_iso(value)
                _require(date.tzinfo is not None and date <= datetime.now(timezone.utc), "SAME_TASK_DOCUMENT_DATE_INVALID")
            return {"authority_scope": "published_document_only", "evidence_refs": [item["evidence_id"]],
                    "source_checked_at": checked_at, "source_document": deepcopy(item),
                    "source_evidence_sha256": {item["evidence_id"]: sha256_json(item)}}
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None


def _pps_text(task, plan, evidence, candidate, target, *, task_dir, root):
    """An intact exact publication is readable even when no abstract was found."""
    from assessment_v24 import bound_runs, evidence_index, _entry_matches_run
    from common import load_skill_config
    from provider_utils import sanitize_for_evidence, sanitize_raw_evidence, validate_text_evidence
    from record_uspto_patent_chrome_verification import validate_common, normalize_success, candidate_request_params
    from runtime_v24 import source_files_complete
    number = candidate.get("publication_number")
    if (target.get("q") != number or candidate.get("jurisdiction") != "US"
            or candidate.get("right_type") not in {"patent", "design"}
            or set(target.get("required_facts", [])) - {"abstract", "protection_content"}):
        return None  # Text cannot supply an unretained requested drawing.
    provider = "uspto_patent_browser"
    index = evidence_index(evidence)
    for source in plan.get("queries", {}).get(provider, []):
        if (source.get("q") != number or source.get("candidate_id") != candidate["candidate_id"]
                or source.get("operation") != "candidate_verification" or source.get("jurisdiction") != "US"
                or source.get("right_type") != candidate["right_type"]):
            continue
        for run in reversed(bound_runs(evidence, plan, provider, source)):
            try:
                _require(run.get("status") == "success" or run.get("status") == "access_limited"
                         and run.get("error_code") in {"REQUESTED_CONTENT_INCOMPLETE", "MISSING_OFFICIAL_CURRENT_STATUS"},
                         "READING_PPS_DOCUMENT_UNAVAILABLE")
                entries = [item for item in index.values() if _entry_matches_run(item, run)]
                _require(_production([run, entries]), "READING_PPS_NON_PRODUCTION")
                directory = _task_directory(task, plan, evidence, run, task_dir, root)
                _require(source_files_complete(directory, evidence, run), "READING_PPS_SOURCE_FILES_INVALID")
                raw_path = (directory / run["raw_paths"][0]).resolve()
                raw_bytes = raw_path.read_bytes()
                _require(re.fullmatch(r"[A-Za-z0-9_-]+", source["query_id"]), "READING_PPS_QUERY_INVALID")
                paths = list(islice(directory.glob("uspto_patent_browser-" + source["query_id"] + "-*-capture.json"), 33))
                _require(len(paths) <= 32, "READING_PPS_CAPTURE_LOOKUP_BOUND")
                originals = []
                for path in paths:
                    if not path.resolve().is_relative_to(directory) or not path.is_file():
                        continue
                    capture = load_json(path)
                    if capture.get("query_id") == source["query_id"] and sanitize_raw_evidence(
                            json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8"), "json") == raw_bytes:
                        originals.append((path, capture))
                _require(len(originals) == 1, "READING_PPS_ORIGINAL_CAPTURE_UNVERIFIED")
                path, capture = originals[0]
                _require(_production(capture) and capture.get("status") == run["status"], "READING_PPS_CAPTURE_INVALID")
                hosts = set(load_skill_config()["providers"][provider]["browser_allowed_hosts"])
                common = validate_common(capture, task, hosts, directory, capture["status"])
                _require(_production(load_json(Path(capture["query_execution"]["path"]))), "READING_PPS_RECEIPT_NON_PRODUCTION")
                _require(candidate_request_params(directory, task, capture, number, candidate["right_type"]) == run.get("request_params"),
                         "READING_PPS_REQUEST_MISMATCH")
                text = capture.get("rendered_text")
                _require(capture.get("candidate_id") == candidate["candidate_id"] and common[0] == number
                         and capture.get("document_retrieval", {}).get("status") == "success"
                         and isinstance(text, str) and 0 < len(text) < 200000, "READING_PPS_TEXT_MISSING_OR_TRUNCATED")
                _declared_paths(capture, directory)
                date = parse_iso(capture["checked_at"])
                _require(date.tzinfo is not None and date <= datetime.now(timezone.utc), "READING_PPS_SOURCE_DATE_INVALID")
                expected = sanitize_for_evidence(normalize_success(capture, common, published_only=True))
                accepted = [item for item in entries if isinstance(item.get("payload"), dict)
                            and all(item["payload"].get(key) == value for key, value in expected.items())]
                _require(bool(accepted), "READING_PPS_NORMALIZED_FACTS_MISMATCH")
                for item in accepted:
                    validate_text_evidence(item["payload"], expected_stage="retained")
                return {"authority_scope": "published_document_only", "evidence_refs": [item["evidence_id"] for item in accepted],
                    "source_task_id": task["task_id"], "source_query_id": source["query_id"],
                    "source_plan_entry_sha256": sha256_json(source), "source_run_id": run["run_id"],
                    "source_checked_at": capture["checked_at"], "source_query_execution": deepcopy(capture["query_execution"]),
                    "source_document": {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
                        "text_pointer": "/rendered_text", "publication_number": number,
                        "rendered_text_sha256": sha256_json(text), "text_hash_algorithm": "sha256-canonical-json-utf8"},
                    "source_payload_digest": run["payload_digest"]}
            except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                continue
    return None


def qualified_reading_material(task, plan, evidence, candidates, ledger, provider, row, *,
                               supplement=None, evidence_root=None, task_dir=None):
    """A retained exact original is work for the Agent, not an invented query.

    This intentionally does not claim that any page has been read, that the
    requested facts are satisfied, or that current rights were verified.
    """
    from workflow_v24 import correction_enabled, scenario_dispatch_block, reading_contract_valid
    from decision_workflow import effective_decision, candidate_document_entries
    if (not correction_enabled(task) or row.get("execution_phase") != "needs_info"
            or not reading_contract_valid(row) or set(row["required_facts"]) & {"current_status", "goods_services"}):
        return None
    try:
        if scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence,
                                   supplement=supplement, for_dispatch=False):
            return None
        matches = [(name, item) for name in ("patents", "trademarks") for item in candidates.get(name, [])
                   if item.get("candidate_id") == row.get("candidate_id")]
        _require(len(matches) == 1, "READING_CANDIDATE_AMBIGUOUS")
        collection, candidate = matches[0]
        decision = effective_decision(task, ledger, collection, candidate, row["scenario_id"],
                                     row["jurisdiction"], row["right_type"], evidence=evidence, supplement=supplement)
        _require(decision.get("current") is True and decision.get("decision") == "needs_info", "READING_DECISION_STALE")
        root = historical_evidence_root(task, supplement, evidence_root)
        if root is None and task_dir is not None:
            root = Path(task_dir).resolve()
        # A related page image alone is not a complete original that an Agent
        # can inspect for an arbitrary missing abstract/claim. Require the
        # registered original PDF itself; media linkage remains report work.
        originals = []
        for item in candidate_document_entries(candidate, evidence, supplement, task=task):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = Path(item["path"])
            path = path if path.is_absolute() else Path(root or task_dir) / path
            if path.suffix.lower() != ".pdf" or not path.is_file():
                continue
            with path.open("rb") as stream:
                if not stream.read(5).startswith(b"%PDF-"):
                    continue
            originals.append(item)
        retained = _document(candidate, row, {**(supplement or {}), "evidence": originals}, root)
        if retained is None and provider == "uspto_patent_browser":
            retained = _pps_text(task, plan, evidence, candidate, row, task_dir=task_dir, root=root)
        if retained is None:
            return None
        return {**retained, "complete": False, "available_for_reading": True,
                "dispatch": "agent_read_required", "satisfied_facts": [],
                "required_facts": deepcopy(row["required_facts"]), "reading_scope": deepcopy(row["reading_scope"]),
                "candidate_id": candidate["candidate_id"], "scenario_id": row["scenario_id"],
                "jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
                "source_query_performed": False, "submission_state": "not_submitted"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def qualified_fact_reuse(task, plan, evidence, candidates, ledger, provider, row, *,
                         supplement=None, evidence_root=None, task_dir=None):
    from workflow_v24 import scenario_dispatch_block, scenario_workflow_enabled, correction_enabled, reading_contract_valid
    from decision_workflow import effective_decision, _snapshot_value
    minimal_official = (correction_enabled(task) and row.get("execution_phase") == "needs_info"
        and provider == "uspto_tsdr" and reading_contract_valid(row)
        and set(row["required_facts"]) <= {"goods_services", "current_status"})
    if not scenario_workflow_enabled(task) or not minimal_official and row.get("action_purpose") not in {"official_verification", "document_content"}:
        return None
    try:
        if scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence, supplement=supplement):
            return None
        matches = [(name, value) for name in ("patents", "trademarks") for value in candidates.get(name, [])
                   if value.get("candidate_id") == row.get("candidate_id")]
        _require(len(matches) == 1, "SAME_TASK_CANDIDATE_AMBIGUOUS")
        collection, candidate = matches[0]
        decision = effective_decision(task, ledger, collection, candidate, row["scenario_id"],
            row.get("triage_jurisdiction") or row["jurisdiction"], row["right_type"], evidence=evidence, supplement=supplement)
        _require(decision.get("current") is True and decision.get("decision") == ("needs_info" if minimal_official else "selected"), "SAME_TASK_TARGET_NOT_SELECTED")
        _require(candidate.get("jurisdiction") == row["jurisdiction"] and candidate.get("right_type") == row["right_type"],
                 "SAME_TASK_CANDIDATE_SCOPE_MISMATCH")
        root = historical_evidence_root(task, supplement, evidence_root)
        if isinstance(supplement, dict):
            ids = [item.get("evidence_id") for item in supplement.get("evidence", []) if isinstance(item, dict)]
            _require(len(ids) == len(set(ids)), "SAME_TASK_SUPPLEMENT_DUPLICATE_EVIDENCE_ID")
        _require(_snapshot_value("same_task_production", (task, plan), lambda: _production([task, plan])),
                 "SAME_TASK_NON_PRODUCTION")
        result = (_official(task, plan, evidence, candidate, provider, row, task_dir=task_dir, root=root)
                  if row["action_purpose"] == "official_verification" or minimal_official else _document(candidate, row, supplement, root))
        if result is None:
            return None
        return {**result, "complete": True, "dispatch": "fact_reused", "status": "fact_reused",
                **({"satisfied_facts": deepcopy(row["required_facts"])} if minimal_official else {}),
                "submission_state": "not_submitted", "source_query_performed": False,
                "target_query_id": row["query_id"], "target_plan_entry_sha256": sha256_json(row),
                "scenario_id": row["scenario_id"], "scenario_sha256": row["scenario_sha256"],
                "triage_decision_id": row["triage_decision_id"], "triage_decision_sha256": row["triage_decision_sha256"],
                "candidate_id": candidate["candidate_id"], "jurisdiction": row["jurisdiction"],
                "right_type": row["right_type"], "action_purpose": row["action_purpose"]}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
