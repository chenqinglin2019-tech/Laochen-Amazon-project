"""Field-level use of retained API records under api-first-v3.

The API is an accepted source, not an official-register impersonation.  A
successful request supports only fields actually present for the exact record.
This module is read-only except for annotating a freshly recorded receipt.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re

from common import now_iso, sha256_file, sha256_json

REVISION = "api-first-v3"
FORM = "trusted_api_record"
PUBLIC_PROVIDERS = frozenset({"serper_web", "serper_images", "serpapi_google_lens"})
PUBLIC_URL_FIELDS = ("url", "link", "source_url", "image_url", "original", "work_url", "original_url")
PROVIDERS = frozenset({"epo_ops", "epo_publication_server", "serper_patents",
    "serper_web", "serper_images", "serpapi_google_patents", "serpapi_google_lens",
    "signa", "euipo_trademark", "euipo_design", "inpi_api", "jpo_api"})
REGISTERED = frozenset({"patent", "utility_model", "design", "trademark_word", "trademark_figurative"})
DYNAMIC = frozenset({"current_status", "rights_holder", "territory"})
IDENTIFIERS = ("publication_number", "record_number", "serial_number", "application_number",
               "registration_number", "provider_record_id", "identifier", "id")
ALIASES = {"status": "current_status", "protection": "protection_content",
           "owner": "rights_holder", "specimen": "representative_figures"}


def enabled(task):
    return isinstance(task, dict) and task.get("retrieval_workflow_revision") == REVISION


def country(value):
    value = str(value or "").strip().upper()
    return {"EM": "EU", "EUIPO": "EU", "USPTO": "US", "UK": "GB"}.get(value, value)


def identifier(value):
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def records(payload):
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("candidates", "results", "records", "items", "data"):
        if isinstance(payload.get(key), list):
            return records(payload[key])
    if isinstance(payload.get("record"), dict):
        return [payload["record"]]
    return [payload]


def _upstream(provider):
    if provider in {"serper_patents", "serpapi_google_patents"}:
        return "google_patents"
    return {"serper_web": "google_search", "serper_images": "google_images",
            "serpapi_google_lens": "google_lens"}.get(provider, provider)


def receipt_metadata(entry, run):
    return {"revision": REVISION, "source_form": FORM,
            "provider": entry.get("provider"), "source_upstream": _upstream(entry.get("provider")),
            "operation": entry.get("operation"), "query_id": entry.get("query_id"),
            "source_run_id": entry.get("source_run_id"), "evidence_id": entry.get("evidence_id"),
            "jurisdiction": entry.get("jurisdiction"), "right_type": entry.get("right_type"),
            "plan_entry_sha256": entry.get("plan_entry_sha256"),
            "payload_sha256": sha256_json(entry.get("payload")),
            "raw_sha256": run.get("payload_digest"), "raw_paths": deepcopy(run.get("raw_paths", [])),
            "checked_at": run.get("finished_at"), "source_updated_at": run.get("data_date") or "",
            "source_environment": run.get("source_environment", "production"),
            "status": run.get("status"), "error_code": run.get("error_code", "")}


def annotate_entry(task, entry, run):
    if (enabled(task) and entry.get("provider") in PROVIDERS
            and run.get("status") in {"success", "no_result"} and not run.get("error_code")
            and run.get("raw_paths")):
        entry[FORM] = receipt_metadata(entry, run)
    return entry


def valid_entry(task, entry, run=None):
    proof = entry.get(FORM) if isinstance(entry, dict) else None
    if not enabled(task) or not isinstance(proof, dict) or entry.get("provider") not in PROVIDERS:
        return False
    if (proof.get("revision") != REVISION or proof.get("source_form") != FORM
            or proof.get("status") not in {"success", "no_result"} or proof.get("error_code")
            or str(proof.get("source_environment", "")).lower() in {"test", "sandbox", "fixture", "mock", "loopback", "test_fixture", "non_production", "synthetic", "offline", "unit_test_only"}
            or proof.get("payload_sha256") != sha256_json(entry.get("payload"))):
        return False
    if any(proof.get(key) != entry.get(key) for key in
           ("provider", "operation", "query_id", "source_run_id", "evidence_id", "jurisdiction", "right_type", "plan_entry_sha256")):
        return False
    if run is not None and proof != receipt_metadata(entry, run):
        return False
    if run is not None and (run.get("run_id") != entry.get("source_run_id")
            or run.get("fixture") or run.get("test_only")
            or any(run.get(key) != entry.get(key) for key in
                   ("provider", "operation", "query_id", "jurisdiction", "right_type", "plan_entry_sha256"))):
        return False
    paths = proof.get("raw_paths")
    if not isinstance(paths, list) or not paths or not proof.get("raw_sha256"):
        return False
    try:
        return any(Path(path).is_file() and sha256_file(Path(path)) == proof["raw_sha256"] for path in paths)
    except (OSError, ValueError, TypeError):
        return False


def _instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return None


def evaluation_at(task, evidence=None):
    if task.get("review_policy_revision") == "final-double-review-v1":
        from final_review import evaluation_at as frozen_time
        return frozen_time(task, evidence)
    return now_iso()


def _fresh(task, entry, at):
    checked, reference = _instant(entry[FORM].get("checked_at")), _instant(at)
    hours = (task.get("retrieval_policy") or {}).get("dynamic_evidence_max_age_hours", 48)
    try:
        age = (reference - checked).total_seconds() / 3600 if checked and reference else None
        return age is not None and -0.01 <= age <= float(hours) and float(hours) > 0
    except (ValueError, TypeError):
        return False


def _record_country(row, entry):
    result = country(row.get("jurisdiction") or row.get("office") or row.get("office_code") or row.get("country"))
    if result:
        return result
    number = str(row.get("publication_number") or "")
    return country(number[:2]) if re.match(r"^[A-Za-z]{2}\d", number) else country(entry.get("jurisdiction"))


def _matches(row, entry, candidate, jurisdiction, right, *, allow_static_territory=False):
    if row.get("source_identity_conflict") or row.get("identity_conflict"):
        return False
    static_ep = (allow_static_territory and _record_country(row, entry) == "EP"
        and country(jurisdiction) in {"EU", "GB", "FR", "DE", "IT", "ES"}
        and right in {"patent", "utility_model"}
        and identifier(row.get("publication_number")).startswith("EP")
        and identifier(row.get("publication_number")) == identifier(candidate.get("publication_number") or candidate.get("record_number")))
    if _record_country(row, entry) != country(jurisdiction) and not static_ep:
        return False
    actual_right = row.get("right_type") or entry.get("right_type")
    if actual_right and actual_right != right and not ({actual_right, right} <= {"trademark_word", "trademark_figurative"}):
        return False
    # A detail's candidate id cannot override a different publication/mark id.
    for key in ("publication_number", "serial_number", "provider_record_id"):
        if row.get(key) and candidate.get(key) and identifier(row[key]) != identifier(candidate[key]):
            return False
    left = {identifier(row.get(key)) for key in IDENTIFIERS if row.get(key)}
    target = {identifier(candidate.get(key)) for key in IDENTIFIERS if candidate.get(key)}
    return bool(left & target)


def _media(row):
    result = []
    for key in ("media", "images", "figures", "drawings", "views", "artifacts"):
        values = row.get(key)
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                continue
            if (item.get("is_thumbnail") is True or item.get("thumbnail_only") is True
                    or str(item.get("role") or item.get("image_kind") or "").lower() in {"thumbnail", "preview"}):
                continue
            try:
                path = Path(item["path"])
                if path.is_file() and sha256_file(path) == item["sha256"] and path.stat().st_size > 0:
                    from common import image_info
                    mime, width, height = image_info(path)
                    if mime.startswith("image/") and width and height:
                        result.append(item)
            except (ImportError, OSError, ValueError, TypeError):
                continue
    return result


def _status_value(value):
    return (value.get("primary") or value.get("stage") or value.get("status")) if isinstance(value, dict) else value


def record_facts(row, entry):
    """Return values plus their real normalized-field location; never fill gaps."""
    values = {}
    def named_party(value):
        if isinstance(value, str):
            return bool(value.strip()) and value.strip().casefold() not in {"unknown", "n/a", "not available", "-"}
        if isinstance(value, list):
            return bool(value) and all(named_party(item) for item in value)
        if isinstance(value, dict):
            return any(named_party(value.get(key)) for key in
                ("name", "owner_name", "ownerName", "legal_name", "entity_name", "organization", "company_name"))
        return False
    def add(fact, field, value):
        if value not in (None, "", [], {}):
            provenance = row.get("field_provenance") or {}
            values[fact] = {"value": deepcopy(value), "source_field": provenance.get(field, field) if isinstance(provenance, dict) else field}
    identities = {key: row[key] for key in IDENTIFIERS if row.get(key)}
    if identities:
        add("identity", "record_identifiers", identities)
    provider = entry.get("provider")
    if provider in {"serper_web", "serper_images", "serpapi_google_lens"}:
        return {}  # Page/image matches contain no register-record assertions.
    for field in ("current_status", "legal_status", "right_state", "status_detail", "status"):
        status = row.get(field)
        state = _status_value(status)
        if isinstance(state, str) and state.strip() and state.strip().casefold() not in {
                "unknown", "not_checked", "success", "no_result", "partial", "failed", "verified", "incomplete",
                "n/a", "not available", "not_available", "unavailable", "unverified", "none", "null", "-"}:
            add("current_status", field, status)
            break
    if "current_status" in values:
        add("territory", "jurisdiction+current_status", {"jurisdiction": _record_country(row, entry),
            "source_reported_status": values["current_status"]["value"]})
    for field in ("current_assignee", "current_owner", "rights_holder", "owners", "owner"):
        if named_party(row.get(field)):
            add("rights_holder", field, row[field])
            break
    # A details endpoint's assignee projection is useful; a search applicant
    # or historical assignment event never silently supplies this fact.
    if "rights_holder" not in values and entry.get("operation") == "candidate_detail" and named_party(row.get("assignees")) and row.get("assignees_are_current") is True:
        add("rights_holder", "assignees", row["assignees"])
    for field in ("claims", "independent_claims", "claim_text"):
        value = row.get(field)
        if value and not row.get("claims_truncated") and not row.get("protection_content_truncated") and not row.get("truncated"):
            if (isinstance(value, str) and value.strip() or isinstance(value, list) and value
                    and all(isinstance(item, str) and item.strip() or isinstance(item, dict)
                            and isinstance(item.get("text"), str) and item["text"].strip() for item in value)):
                add("protection_content", field, value)
                break
    for field in ("goods_services", "goods_and_services", "classifications", "goods"):
        value = row.get(field)
        if not value or row.get("goods_services_truncated") or row.get("goods_services_text_truncated") or row.get("truncated"):
            continue
        if isinstance(value, list) and any(isinstance(item, dict) and
                (item.get("truncated") or item.get("goods_services_text_truncated")) for item in value):
            continue
        if provider == "signa" and isinstance(value, list) and any(isinstance(item, dict) and
                (item.get("truncated", item.get("goods_services_text_truncated")) is not False
                 or item.get("scope") == "as_filed") for item in value):
            continue
        texts = [item.get("goods_services_text") or item.get("text") or item.get("description")
                 for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        if ((field != "classifications" and isinstance(value, str) and value.strip())
                or texts and all(isinstance(text, str) and text.strip() for text in texts)
                or field != "classifications" and isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)):
            add("goods_services", field, value)
            break
    for field in ("mark_text", "wordmark"):
        if isinstance(row.get(field), str) and row[field].strip():
            add("mark_text", field, row[field])
            break
    media = _media(row)
    incomplete_media = (row.get("images_truncated") or row.get("figures_truncated")
        or row.get("media_truncated") or row.get("source_image_conflict")
        or isinstance(row.get("media_acquisition"), dict) and row["media_acquisition"].get("complete") is False)
    if media and not incomplete_media:
        add("representative_figures", "retained_media", media)
    for fact in row.get("api_fact_exclusions", []):
        values.pop(fact, None)
    if row.get("source_status_conflict") or row.get("status_conflict"):
        values.pop("current_status", None)
        values.pop("territory", None)
    return values


def _equivalent(fact, value):
    if fact == "identity":
        return "matched"  # Exact-record matching already occurred above.
    if fact == "current_status":
        state = _status_value(value)
        return str(state).strip().casefold()
    if fact == "territory" and isinstance(value, dict):
        return country(value.get("jurisdiction")), _equivalent("current_status", value.get("source_reported_status"))
    if fact == "rights_holder":
        values = value if isinstance(value, list) else [value]
        if all(isinstance(item, str) for item in values):
            return tuple(sorted({" ".join(item.split()).casefold() for item in values}))
    if fact == "representative_figures":
        return "exact-record-retained-media"  # Views of the same matched record are additive.
    return sha256_json(value)


def _exact_detail_candidate(task, entry, candidate, evidence=None):
    """Use an explicit, original-document-bound publication locator, never a family alias."""
    if (entry.get('provider') != 'serpapi_google_patents' or entry.get('operation') != 'candidate_detail'
            or not isinstance(entry.get('payload'),dict)
            or candidate.get('candidate_id') and entry['payload'].get('candidate_id')
                and candidate['candidate_id'] != entry['payload']['candidate_id']
            or candidate.get('publication_number') == entry['payload'].get('publication_number')):
        return candidate
    try:
        from pathlib import Path
        from common import load_json, sha256_json
        from source_result_processing import detail_record_binding
        paths = entry.get(FORM,{}).get('raw_paths',[])
        if len(paths) != 1 or not Path(paths[0]).is_absolute():
            return candidate
        root = Path(paths[0]).parents[2]
        if load_json(root/'task.json').get('task_id') != task.get('task_id'):
            return candidate
        retained_evidence = load_json(root/'evidence.json') if evidence is None else evidence
        runs = [r for r in retained_evidence.get('source_runs',[]) if r.get('run_id') == entry.get('source_run_id')]
        if len(runs) != 1:
            return candidate
        proof = detail_record_binding(root,runs[0],retained_evidence)
        if proof['candidate_id'] != candidate.get('candidate_id') or proof['entry_sha256'] != sha256_json(entry):
            return candidate
        known = load_json(root/'normalized-candidates.json')
        matches = [c for c in known.get('patents',[]) if c.get('candidate_id') == candidate.get('candidate_id')]
        if len(matches) != 1 or any(candidate.get(k) and identifier(candidate[k]) != identifier(matches[0].get(k))
                for k in IDENTIFIERS):
            return candidate
        return {**candidate, 'publication_number':proof['publication_number']}
    except (OSError,ValueError,KeyError,TypeError,IndexError):
        return candidate


def accepted_candidate_facts(task, evidence, candidate, jurisdiction=None, right_type=None, assessment_at=None):
    if not enabled(task) or not isinstance(evidence, dict):
        return {}
    jurisdiction = jurisdiction or candidate.get("jurisdiction") or candidate.get("office")
    right = right_type or candidate.get("right_type")
    at = assessment_at or evaluation_at(task, evidence)
    runs = {row.get("run_id"): row for row in evidence.get("source_runs", []) if isinstance(row, dict)}
    offered = {}
    entries = [entry for group in evidence.get("collections", {}).values() if isinstance(group, list)
               for entry in group if isinstance(entry, dict) and FORM in entry]
    entries.sort(key=lambda entry: entry[FORM].get("checked_at") or "", reverse=True)
    seen = set()
    for entry in entries:
        run = runs.get(entry.get("source_run_id"))
        if not run or not valid_entry(task, entry, run) or run.get("status") != "success":
            continue
        for row in records(entry.get("payload")):
            if not _matches(row, entry, _exact_detail_candidate(task,entry,candidate,evidence), jurisdiction, right, allow_static_territory=True):
                continue
            for fact, value in record_facts(row, entry).items():
                if fact in DYNAMIC and _record_country(row, entry) != country(jurisdiction):
                    continue
                if fact in DYNAMIC and not _fresh(task, entry, at):
                    continue
                key = (entry[FORM]["source_upstream"], fact)
                if key in seen:
                    continue
                seen.add(key)
                offered.setdefault(fact, []).append({**value,
                    "evidence_refs": [entry["evidence_id"]], "source_run_ids": [entry["source_run_id"]],
                    "provider": entry["provider"], "source_upstream": entry[FORM]["source_upstream"],
                    "source_form": FORM, "checked_at": entry[FORM]["checked_at"],
                    "source_updated_at": row.get("source_data_date") or row.get("source_updated_at") or entry[FORM]["source_updated_at"],
                    "record_identity": {key: row[key] for key in IDENTIFIERS if row.get(key)}})
    result = {}
    for fact, values in offered.items():
        if len({_equivalent(fact, row["value"]) for row in values}) != 1:
            continue  # Conflicting assertions remain a specific missing fact.
        result[fact] = values[0]
        result[fact]["evidence_refs"] = sorted({ref for value in values for ref in value["evidence_refs"]})
        result[fact]["source_run_ids"] = sorted({ref for value in values for ref in value["source_run_ids"]})
        if fact == "representative_figures":
            media = {}
            for value in values:
                for item in value["value"]:
                    media.setdefault(item["sha256"], deepcopy(item))
            result[fact]["value"] = list(media.values())
    return result


def required_facts_for(candidate):
    right = candidate.get("right_type")
    if right not in REGISTERED:
        return set()
    facts = {"identity", "current_status", "territory", "rights_holder"}
    if right in {"patent", "utility_model"}:
        facts.add("protection_content")
    elif right == "design":
        facts.add("representative_figures")
    else:
        facts.add("goods_services")
        facts.add("representative_figures" if right == "trademark_figurative" else "mark_text")
    return facts



def _registered_original_protection(task, evidence, candidate, jurisdiction, right, *,
                                    scope=None, candidates=None, ledger=None, supplement=None, task_dir=None):
    """Credit a current M06 reading of this exact registered original; no API status is invented."""
    if (not enabled(task) or right != 'patent' or country(jurisdiction) != 'US' or task_dir is None
            or not isinstance(scope, dict) or scope.get('candidate_id') != candidate.get('candidate_id')
            or not scope.get('scenario_id') or scope.get('jurisdiction') != jurisdiction
            or scope.get('right_type') != right):
        return None
    number = identifier(candidate.get('publication_number'))
    if not number or not any(identifier(row.get('lead', {}).get('publication_number')) == number
            for row in evidence.get('collections', {}).get('candidate_leads', []) if isinstance(row, dict)):
        return None
    from pathlib import Path
    root = Path(task_dir)
    from record_candidate_lead import validated_candidate_lead_entries
    from workflow_v24 import _scenario_context, scenario_supplement
    from decision_workflow import evidence_index
    import specialty_analysis as specialty
    try:
        if candidates is None or ledger is None:
            candidates, ledger, _ = _scenario_context(root, task)
        if supplement is None:
            supplement = scenario_supplement(root, task=task, evidence=evidence)
        current = specialty._current(task, evidence, candidates, ledger, supplement, specialty._scope(scope))
        intake = specialty._intake(task, specialty._scope(scope))
        if not intake or intake.get('annotation_id') != current.get('annotation', {}).get('annotation_id'):
            return None
        specialty._validate_intake(task, evidence, candidates, ledger, supplement, intake)
        history = [row for row in specialty.events(task) if specialty._scope(row) == specialty._scope(scope)
            and row.get('intake_event_id') == intake['event_id']]
        fact = next((row for row in reversed(history) if row.get('kind') == 'fact' and row.get('fact_kind') == 'protection'), None)
        if not fact or fact.get('outcome') != 'supported':
            return None
        for change in (row for row in history if row.get('kind') in {'change','impact'}):
            field = 'change_event_id' if change['kind'] == 'change' else 'impact_event_id'
            reviewed = next((row for row in reversed(history) if row.get(field) == change['event_id']
                and row.get('kind') in {'change_review','impact_review'}), {})
            if reviewed.get('outcome') != 'continues':
                return None
        indexed = evidence_index(evidence, supplement)
        specialty._fact(task, fact, indexed, evidence=evidence)
        leads = [row for row in validated_candidate_lead_entries(task, evidence, root)
            if identifier(row['lead']['publication_number']) == number and row.get('right_type') == right]
        for lead in leads:
            source_ref = lead['source_registration']['evidence_id']
            document = lead['document']
            for material in history:
                if (material.get('kind') != 'material' or material.get('event_id') not in fact.get('material_event_ids', [])
                        or material.get('source_form') != 'original_document'
                        or identifier(material.get('document_id')) != number
                        or material.get('document_version') != fact.get('document_version')
                        or material.get('status') != 'sufficient_for_listed_purposes'
                        or 'protection' not in material.get('supported_facts', [])
                        or source_ref not in material.get('evidence_refs', [])
                        or source_ref not in fact.get('evidence_refs', [])):
                    continue
                specialty._material(task, material, indexed)
                batches = [row for row in history if row.get('kind') == 'batch'
                    and material['event_id'] in row.get('processed_material_event_ids', [])
                    and source_ref in row.get('received_evidence_refs', [])]
                if not batches:
                    continue
                for batch in batches:
                    specialty._batch(task, batch, evidence, indexed)
                return {'value':fact['raw_statement'], 'source_field':'current_M06_protection_fact',
                    'source_form':'reviewed_original_document', 'provider':lead['provider'],
                    'source_upstream':document['source_url'], 'evidence_refs':sorted(set(fact['evidence_refs'])),
                    'source_run_ids':[], 'checked_at':fact['recorded_at'], 'source_updated_at':'',
                    'record_identity':{'publication_number':number},
                    'reading_proof':{'candidate_sha256':sha256_json(candidate),
                        'annotation_sha256':sha256_json(current['annotation']), 'intake_sha256':sha256_json(intake),
                        'fact_event_id':fact['event_id'],'fact_sha256':sha256_json(fact),
                        'material_event_id':material['event_id'],'material_sha256':sha256_json(material),
                        'batch_sha256':[sha256_json(row) for row in batches],
                        'lead_evidence_id':lead['evidence_id'], 'lead_sha256':sha256_json(lead),
                        'document_sha256':document['sha256'], 'document_version':material['document_version']}}
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return None

def accepted_verification(task, evidence, candidate, jurisdiction=None, right_type=None, assessment_at=None, *,
                          scope=None, candidates=None, ledger=None, supplement=None, task_dir=None):
    reading_scope = scope
    scope = {**candidate, **({"right_type": right_type} if right_type else {})}
    facts = accepted_candidate_facts(task, evidence, candidate, jurisdiction, right_type, assessment_at)
    required = required_facts_for(scope)
    if 'protection_content' in required and 'protection_content' not in facts:
        original = _registered_original_protection(task, evidence, candidate,
            jurisdiction or candidate.get('jurisdiction'), right_type or candidate.get('right_type'),
            scope=reading_scope, candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)
        if original:
            facts['protection_content'] = original
    return {"complete": bool(required) and required <= set(facts), "supported": facts,
            "missing": sorted(required - set(facts)), "basis": ("accepted_api_and_reviewed_original_records"
                if any(value.get("source_form") == "reviewed_original_document" for value in facts.values()) else FORM),
            "evidence_refs": sorted({ref for value in facts.values() for ref in value["evidence_refs"]})}


def bind_material_candidate(task, request, candidates):
    """Bind new API material to canonical candidate identifiers, never caller input."""
    if not enabled(task) or request.get("source_form") != FORM:
        return request
    from annotate_materiality import iter_candidates
    matches = [candidate for _, candidate in iter_candidates(candidates)
               if candidate.get("candidate_id") == request.get("candidate_id")]
    if len(matches) != 1:
        raise ValueError("API_MATERIAL_CANDIDATE_IDENTITY_REQUIRED")
    canonical = matches[0]
    snapshot = {key: deepcopy(canonical[key]) for key in
                IDENTIFIERS + PUBLIC_URL_FIELDS + ("candidate_id", "jurisdiction", "right_type") if canonical.get(key)}
    return {**request, "api_candidate_identity": snapshot}


def _public_urls(row):
    from urllib.parse import urlsplit
    result = set()
    for key in PUBLIC_URL_FIELDS:
        value = row.get(key)
        if not isinstance(value, str):
            continue
        value = value.strip()
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username:
            result.add(value)
    return result


def _public_full_text(row):
    truncated = any(row.get(key) is True for key in ("truncated", "full_text_truncated", "content_truncated", "summary_only"))
    text = any(isinstance(row.get(key), str) and row[key].strip() for key in ("full_text", "document_text"))
    text = text or (row.get("content_complete") is True and any(
        isinstance(row.get(key), str) and row[key].strip() for key in ("text", "content")))
    return text and not truncated


def _public_scope(row):
    """Describe only actual returned public content, never a registered right."""
    result = {"public_identity"} if _public_urls(row) else set()
    if any(isinstance(row.get(key), str) and row[key].strip() for key in ("title", "snippet", "excerpt")):
        result.add("source_excerpt")
    media = _media(row) if not any(row.get(key) is True for key in
        ("thumbnail_only", "is_thumbnail", "images_truncated", "media_truncated", "source_image_conflict")) else []
    if isinstance(row.get("media_acquisition"), dict) and row["media_acquisition"].get("complete") is False:
        media = []
    if _public_full_text(row) or media:
        result.add("original_content")
    if "original_content" in result and any(_instant(row.get(key)) is not None for key in ("publication_date", "published_at", "disclosure_date")):
        result.add("disclosure")
    return result


def public_material_scope(task, material, indexed, *, require_full_text=False):
    """Bind an API page/work to the selected canonical public URL and real content."""
    if not enabled(task) or material.get("source_form") != FORM:
        return set()
    canonical = material.get("api_candidate_identity")
    if not isinstance(canonical, dict) or canonical.get("candidate_id") != material.get("candidate_id"):
        return set()
    document = str(material.get("api_record_identity") or material.get("document_id") or "").strip()
    if document not in _public_urls(canonical):
        return set()
    result = set()
    for ref in material.get("evidence_refs", []):
        entry = indexed.get(ref)
        if (not isinstance(entry, dict) or entry.get("provider") not in PUBLIC_PROVIDERS
                or not valid_entry(task, entry) or country(entry.get("jurisdiction")) != country(material.get("jurisdiction"))):
            continue
        for row in records(entry.get("payload")):
            if (not row.get("source_identity_conflict") and not row.get("identity_conflict") and document in _public_urls(row)
                    and (not require_full_text or _public_full_text(row))):
                result.update(_public_scope(row))
    return result


def material_support(task, request, indexed, fact=None, *, right_identity=None, evidence=None):
    """Check a material's explicit record identity against its retained API row."""
    if not enabled(task):
        return False
    wanted = ("representative_figures" if fact == "protection" and request.get("right_type") == "design"
              else ALIASES.get(fact, fact))
    document = request.get("api_record_identity") or request.get("document_id") or request.get("right_identity")
    candidate = request.get("api_candidate_identity")
    if not isinstance(candidate, dict) or candidate.get("candidate_id") != request.get("candidate_id"):
        return False
    jurisdiction, right = request.get("jurisdiction"), request.get("right_type")
    public_scope = public_material_scope(task, request, indexed)
    if public_scope:
        if right_identity is not None and str(right_identity).strip() not in _public_urls(candidate):
            return False
        public_fact = ({"identity": "public_identity", "protection_content": "original_content"}.get(wanted, wanted)
                       if right in {"copyright", "trade_dress", "unregistered_design"} else wanted)
        if wanted is None or public_fact in public_scope:
            return True
    for ref in request.get("evidence_refs", []):
        entry = indexed.get(ref)
        if not isinstance(entry, dict) or not valid_entry(task, entry):
            continue
        for row in records(entry.get("payload")):
            if entry.get("provider") in PUBLIC_PROVIDERS:
                continue
            identities = {identifier(row.get(key)) for key in IDENTIFIERS if row.get(key)}
            if not identifier(document) or identifier(document) not in identities:
                continue
            if right_identity is not None and identifier(right_identity) not in identities:
                continue
            if not _matches(row, entry, _exact_detail_candidate(task,entry,candidate,evidence), jurisdiction, right, allow_static_territory=True):
                continue
            facts = record_facts(row, entry)
            if wanted in DYNAMIC and _record_country(row, entry) != country(jurisdiction):
                continue
            if wanted in DYNAMIC and not _fresh(task, entry, evaluation_at(task, evidence)):
                continue
            if wanted is None or wanted in facts:
                return True
    return False


def action_facts(task, evidence, row):
    """A follow-up is complete when its exact requested fields are retained."""
    candidate = {key: row[key] for key in IDENTIFIERS if row.get(key)}
    number = row.get("record_number") or row.get("serial_number") or row.get("document") or row.get("q")
    if number:
        candidate.setdefault("record_number", number)
    candidate.update(right_type=row.get("right_type"), jurisdiction=row.get("jurisdiction"))
    requested = row.get("missing_facts") or row.get("required_facts") or []
    if not isinstance(requested, list) or not requested:
        return None
    facts = accepted_candidate_facts(task, evidence, candidate)
    wanted = {ALIASES.get(fact, fact) for fact in requested}
    if not wanted <= set(facts):
        return None
    return {"authority_scope": FORM, "source_query_performed": False,
            "evidence_refs": sorted({ref for fact in wanted for ref in facts[fact]["evidence_refs"]}),
            "facts": {fact: facts[fact] for fact in sorted(wanted)}}


def material_fact(task, material, indexed, fact, *, right_identity=None, evidence=None):
    """A material's declared source form alone never proves the requested fact."""
    return (material.get("source_form") == FORM
            and material_support(task, material, indexed, fact, right_identity=right_identity, evidence=evidence))


def api_run_accepted(task, evidence, run):
    if not enabled(task):
        return False
    return any(valid_entry(task, row, run) for group in evidence.get("collections", {}).values()
               if isinstance(group, list) for row in group if isinstance(row, dict)
               and row.get("source_run_id") == run.get("run_id"))
