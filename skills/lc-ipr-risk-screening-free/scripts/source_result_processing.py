"""04A: receipt-bound result positions and review progress, without new requests."""
from __future__ import annotations

import json
import re
import copy
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from common import load_json, now_iso, sha256_bytes, sha256_file, sha256_json

REVISION = "source-result-processing-v1"
COLLECTIONS = {"patent": "patents", "trademark": "trademarks",
               "copyright": "copyright_assets", "enforcement": "enforcement"}
RAW_LISTS = {
    "serper_patents": ("organic",), "serper_web": ("organic",),
    "serper_images": ("images",), "serpapi_google_patents": ("organic_results",),
    "serpapi_google_lens": ("visual_matches", "exact_matches"),
}
WHOLE_RECORD = "whole_record_receipt"

OUTCOMES = {"candidate", "duplicate_source", "non_candidate"}
RECEIPT_OUTCOMES = {"non_result_error"}
NON_SUCCESS_STATUSES = {"failed", "access_limited", "blocked", "error", "unavailable"}


def enabled(task: dict) -> bool:
    value = task.get("result_processing_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("RESULT_PROCESSING_REVISION_INVALID")
    return True


def _candidate_rows(value: Any) -> list[dict]:
    if isinstance(value, dict):
        value = value.get("candidates", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _detail_record(raw, provider):
    """Recognize the provider's successful single-publication envelope only."""
    if not isinstance(raw,dict) or not isinstance(raw.get('search_metadata'),dict) or not isinstance(raw.get('search_parameters'),dict):
        return False
    if (provider != 'serpapi_google_patents'
            or raw.get('search_metadata', {}).get('status') != 'Success'
            or raw.get('search_parameters', {}).get('engine') != 'google_patents_details'
            or not isinstance(raw.get('publication_number'), str)
            or not re.fullmatch(r'[A-Z]{2}[A-Z0-9]+', raw['publication_number'])
            or raw.get('search_parameters', {}).get('patent_id') !=
                'patent/' + raw['publication_number'] + '/en'
            or not isinstance(raw.get('title'), str) or not raw['title'].strip()
            or not any(raw.get(k) for k in ('abstract', 'claims', 'description', 'images'))
            or 'claims' in raw and (not isinstance(raw['claims'], list)
                or any(not isinstance(c, str) for c in raw['claims']))
            or 'images' in raw and not isinstance(raw['images'], list)
            or any(k in raw and not isinstance(raw[k],str) for k in ('abstract','description'))
            or raw.get('error')):
        return False
    return True


def _json_result_values(body: bytes, provider: str) -> list[tuple[str, int, Any]] | None:
    try:
        raw = json.loads(body)
    except (ValueError, UnicodeError):
        return None
    if isinstance(raw, list):
        groups = (("results", raw),)
    elif isinstance(raw, dict):
        if provider == 'serpapi_google_patents' and isinstance(raw.get('search_parameters'),dict) and raw['search_parameters'].get('engine') == 'google_patents_details':
            return [(WHOLE_RECORD, 1, raw)] if _detail_record(raw, provider) else None
        keys = RAW_LISTS.get(provider, ("candidates", "results", "records"))
        # CUA captures retain visible table cells, independently of whether
        # the result set could be bound to the submitted query.
        if provider == "uspto_patent_browser" and not any(key in raw for key in keys):
            if "rows" in raw:
                visible = raw["rows"]
                if (not isinstance(visible, list) or any(not isinstance(row, dict)
                        or not isinstance(row.get("cells"), list) or not row["cells"]
                        or any(not (isinstance(cell, str) or isinstance(cell, dict)
                            and isinstance(cell.get("text"), str)) for cell in row["cells"])
                        for row in visible)):
                    return None
                keys = ("rows",)
        groups = tuple((key, raw[key]) for key in keys if key in raw)
        if any(not isinstance(rows, list) for _, rows in groups):
            return None
    else:
        return None
    if not groups:
        return None
    return [(name, index, row) for name, rows in groups
            for index, row in enumerate(rows, 1)]


def _unbound_cua_rows(body: bytes, provider: str) -> bool:
    if provider != "uspto_patent_browser":
        return False
    try:
        raw = json.loads(body)
    except (ValueError, UnicodeError):
        return False
    return (isinstance(raw, dict) and "rows" in raw
            and raw.get("history_binding_verified") is False)


def _ops_images_metadata(body):
    """Recognize one OPS document-inquiry, with both exact publication identifiers."""
    ops, exchange = '{http://ops.epo.org}', '{http://www.epo.org/exchange}'
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError):
        return None
    if root.tag != ops + 'world-patent-data' or len(list(root)) != 1 or root[0].tag != ops + 'document-inquiry':
        return None
    inquiry = root[0]
    requested = inquiry.findall(ops+'publication-reference/'+exchange+'document-id')
    results = inquiry.findall(ops+'inquiry-result')
    if (len(requested) != 1 or requested[0].get('document-id-type') != 'epodoc'
            or len(results) != 1 or len(list(inquiry)) != 2):
        return None
    if any(child.tag not in {exchange+'publication-reference',ops+'document-instance'} for child in results[0]):
        return None
    actual = results[0].findall(exchange+'publication-reference/'+exchange+'document-id')
    if len(actual) != 1 or actual[0].get('document-id-type') != 'docdb':
        return None
    parts = [actual[0].findtext(exchange+k) for k in ('country','doc-number','kind')]
    if not all(isinstance(part,str) and re.fullmatch(r'[A-Z0-9]+',part) for part in parts):
        return None
    pub = ''.join(parts)
    if requested[0].findtext(exchange+'doc-number') != pub:
        return None
    instances = results[0].findall(ops+'document-instance')
    full = [instance for instance in instances if instance.get('desc') == 'FullDocument']
    if len(full) != 1 or any(instance.get('desc') not in {'FullDocument','Drawing'} for instance in instances):
        return None
    full = full[0]
    link = 'published-data/images/' + '/'.join(parts) + '/fullimage'
    try:
        pages = int(full.get('number-of-pages',''))
    except ValueError:
        return None
    if full.get('system') != 'ops.epo.org' or full.get('link') != link or pages < 1:
        return None
    formats = [node.text for node in full.findall(ops+'document-format-options/'+ops+'document-format')]
    if not formats or any(value not in {'application/pdf','application/tiff'} for value in formats):
        return None
    sections = []
    for section in full.findall(ops+'document-section'):
        try:
            page = int(section.get('start-page',''))
        except ValueError:
            return None
        if not section.get('name') or not 1 <= page <= pages:
            return None
        sections.append({'name':section.get('name'),'start_page':page})
    return {'publication_number':pub,'jurisdiction':parts[0], 'fullimage_link':link,
        'available_document_pages':pages,'formats':formats,'sections':sections}


def _raw_rows(body: bytes, suffix: str, provider: str) -> list[dict] | None:
    if not body:
        return None
    if suffix == "xml" and provider in {"epo_ops", "inpi_api"}:
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return None
        if provider == "epo_ops":
            if _ops_images_metadata(body) is not None:
                return [{'position':1,'collection':WHOLE_RECORD,'collection_position':1,
                         'raw_sha256':sha256_bytes(body)}]
            nodes = root.findall(".//{*}exchange-document")
            if not nodes:
                nodes = root.findall(".//{*}publication-reference/{*}document-id")
            known_envelope = (bool(root.findall(".//{*}biblio-search")
                or root.findall(".//{*}bibliographic-search"))
                or root.tag.rsplit("}", 1)[-1] in {"biblio-search", "bibliographic-search"})
        else:
            solr = [node for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] == "result" and "numFound" in node.attrib]
            containers = [node for node in root.iter()
                          if node.tag.rsplit("}", 1)[-1] in {"results", "notices", "documents"}]
            nodes = list(solr[0]) if len(solr) == 1 else list(containers[0]) if len(containers) == 1 else []
            known_envelope = len(solr) == 1 or len(containers) == 1
        if not known_envelope:
            return None
        return [{"position": position, "collection": "xml_results",
                 "collection_position": position,
                 "raw_sha256": sha256_bytes(ElementTree.tostring(node))}
                for position, node in enumerate(nodes, 1)]
    if suffix != "json":
        return None
    values = _json_result_values(body, provider)
    if values is None:
        return None
    return [{"position": position, "collection": name, "collection_position": index,
             "raw_sha256": sha256_json(row)}
            for position, (name, index, row) in enumerate(values, 1)]


def _recognized_fault(body: bytes, suffix: str, provider: str) -> bool:
    if suffix != "xml" or provider not in {"epo_ops", "inpi_api"}:
        return False
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError):
        return False
    return (root.tag.rsplit("}", 1)[-1].casefold() == "fault"
            and not root.findall(".//{*}exchange-document")
            and not root.findall(".//{*}document-id"))


def _ops_empty_search_fault(body: bytes, suffix: str, provider: str) -> bool:
    """Identify the exact retained OPS no-results envelope, never generic faults."""
    if suffix != "xml" or provider != "epo_ops":
        return False
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError):
        return False
    namespace = "{http://ops.epo.org}"
    if root.tag != namespace + "fault":
        return False
    children = list(root)
    if (len(children) != 2 or {child.tag for child in children} !=
            {namespace + "code", namespace + "message"}
            or any(list(child) or (child.tail or "").strip() for child in children)
            or (root.text or "").strip()):
        return False
    code = " ".join((root.findtext(namespace + "code") or "").split())
    message = " ".join((root.findtext(namespace + "message") or "").split())
    return code == "SERVER.EntityNotFound" and message == "No results found"


def locate_one_to_one(task: dict, provider: str, evidence_type: str,
                      raw_body: bytes, raw_suffix: str, normalized: Any) -> Any:
    """Bind full-order rows or uniquely matched partial rows to the receipt."""
    if not enabled(task) or evidence_type not in COLLECTIONS:
        return normalized
    # API-first cards have a strict retained normalization contract and their
    # own row hashes; adding projection fields would invalidate that contract.
    if provider in RAW_LISTS:
        return normalized
    if _unbound_cua_rows(raw_body, provider):
        return normalized
    rows = _raw_rows(raw_body, raw_suffix, provider)
    if rows and rows[0]['collection'] == WHOLE_RECORD:
        return normalized
    candidates = normalized.get("candidates") if isinstance(normalized, dict) else normalized
    if rows is None or not isinstance(candidates, list):
        return normalized
    if len(rows) == len(candidates):
        for row, candidate in zip(rows, candidates):
            if not isinstance(candidate, dict):
                return normalized
            existing = candidate.get("source_position")
            if existing is not None and existing != row["position"]:
                return normalized
        for row, candidate in zip(rows, candidates):
            candidate.setdefault("source_position", row["position"])
            candidate.setdefault("source_position_basis", "adapter_order_equal_count")
        return normalized
    # Partial parser output must never borrow positions by list order. Exact
    # raw identifier fields can bind an individual row only when unique.
    values = _json_result_values(raw_body, provider) if raw_suffix == "json" else None
    if values is None:
        return normalized
    identifiers = ("publication_number", "registration_number", "serial_number",
                   "record_number", "application_number")
    used: set[int] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        possible: set[int] | None = None
        for field in identifiers:
            value = candidate.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            matches = {position for position, (_, _, raw) in enumerate(values, 1)
                       if isinstance(raw, dict) and isinstance(raw.get(field), str)
                       and raw[field].strip().casefold() == value.strip().casefold()}
            if matches:
                possible = matches if possible is None else possible & matches
        if possible is None or len(possible) != 1:
            continue
        position = next(iter(possible))
        existing = candidate.get("source_position")
        if position in used or (existing is not None and existing != position):
            continue
        candidate.setdefault("source_position", position)
        candidate.setdefault("source_position_basis", "exact_raw_identifier")
        used.add(position)
    return normalized


def make_index(task: dict, *, provider: str, evidence_type: str, status: str,
               submission_state: str, raw_body: bytes, raw_suffix: str,
               normalized: Any, coverage: dict | None, payload_digest: str) -> dict | None:
    if not enabled(task) or evidence_type not in COLLECTIONS:
        return None
    if not raw_body and status not in {"success", "no_result"}:
        return None
    parsed = _candidate_rows(normalized)
    rows = _raw_rows(raw_body, raw_suffix, provider)
    if rows and rows[0]['collection'] == WHOLE_RECORD and task.get('retrieval_workflow_revision') != 'api-first-v3':
        rows = None
    metadata = coverage if isinstance(coverage, dict) else {}
    if (rows is None and status == "no_result" and submission_state == "submitted"
            and metadata.get("schema_valid") is True and not parsed
            and _ops_empty_search_fault(raw_body, raw_suffix, provider)):
        rows = []
    acquired = metadata.get("retrieved_hits")
    if type(acquired) is not int or acquired < 0:
        acquired = None
    if rows is not None:
        count = len(rows)
        count_basis = "retained_rows"
    elif acquired is not None and raw_body:
        count = acquired
        count_basis = "response_count_only"
        rows = [{"position": index, "collection": "unknown", "collection_position": index,
                 "raw_sha256": None} for index in range(1, count + 1)]
    else:
        count = None
        count_basis = "unknown"
        rows = []
    # Older adapters used retrieved_hits for normalized rows. When that value
    # equals parsed_count, retain it as parser progress, not a contradiction
    # of the larger raw response.
    count_contradiction = (acquired is not None and count is not None
                           and acquired not in {count, len(parsed)})
    count_interpretation = ("legacy_parsed_count" if acquired is not None
                            and acquired == len(parsed) and acquired != count
                            else "acquired_count" if acquired == count else "unknown")
    # A claimed zero is only a response fact when the request was submitted,
    # the adapter validated its schema, and its retained rows are truly empty.
    zero_proven = (status == "no_result" and submission_state == "submitted"
                   and metadata.get("schema_valid") is True and count == 0
                   and not parsed and bool(raw_body)
                   and count_basis == "retained_rows"
                   and not _unbound_cua_rows(raw_body, provider))
    return {"revision": REVISION, "payload_digest": payload_digest,
            "returned_count": count, "returned_count_basis": count_basis,
            "parsed_count": len(parsed), "rows": rows,
            "declared_retrieved_count": acquired,
            "declared_retrieved_interpretation": count_interpretation,
            "count_contradiction": count_contradiction,
            "zero_proven": zero_proven and not count_contradiction}


XML_DERIVATION_TRANSFORM = "xml-url-amp-semicolon-v1"
XML_REDACTION_CLOSE_TRANSFORM = "xml-temu-redaction-text-close-v1"
XML_DERIVATION_TRANSFORMS = {XML_DERIVATION_TRANSFORM, XML_REDACTION_CLOSE_TRANSFORM}
XML_REDACTION_CLOSE_LIMITATIONS = ["Redaction removed an unknown citation tail; only </text> was restored. No lost text or date is recovered."]


def _derive_legacy_epo_xml(body: bytes, transform: str = XML_DERIVATION_TRANSFORM) -> tuple[bytes, list[dict], list[dict]]:
    """Replay one narrowly recognized structural repair; never recover lost facts."""
    try:
        ElementTree.fromstring(body)
    except ElementTree.ParseError:
        pass
    else:
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_NOT_NEEDED")
    changes = []
    if transform == XML_DERIVATION_TRANSFORM:
        for url in re.finditer(rb'https?://[^\s<>"\']+', body):
            for damaged in re.finditer(rb'&amp%3B', url.group()):
                changes.append({"offset": url.start() + damaged.start(),
                                "from": "&amp%3B", "to": "&amp;"})
    elif transform == XML_REDACTION_CLOSE_TRANSFORM:
        # The old bare-key sanitizer ate only this missing closing tag and the
        # unknown citation tail. Add the tag, retaining the tail as missing.
        pattern = rb'<nplcit\b[^<>]*>\s*<text>[^<>]*https://www\.temu\.com/[^<>]*&amp;share_token=\[redacted\](?P<end>)[ \t]*\r?\n[ \t]*</nplcit>'
        matches = list(re.finditer(pattern, body))
        if len(matches) == 1:
            changes.append({"offset": matches[0].start("end"), "from": "", "to": "</text>"})
    else:
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_INPUT_INVALID")
    if not changes:
        raise ValueError("RESULT_PROCESSING_XML_DAMAGE_UNRECOGNIZED")
    derived = body
    for change in reversed(changes):
        pos = change["offset"]
        derived = derived[:pos] + change["to"].encode() + derived[pos + len(change["from"].encode()):]
    try:
        root = ElementTree.fromstring(derived)
    except ElementTree.ParseError as exc:
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_INVALID") from exc
    searches = root.findall(".//{*}biblio-search")
    if len(searches) != 1:
        raise ValueError("RESULT_PROCESSING_XML_ENVELOPE_INVALID")
    nodes = root.findall(".//{*}exchange-document")
    spans = list(re.finditer(rb'<exchange-document\b[^>]*>.*?</exchange-document>', body, re.S))
    if not nodes or len(spans) != len(nodes):
        raise ValueError("RESULT_PROCESSING_XML_SPANS_INVALID")
    rows, identities = [], set()
    for position, (span, node) in enumerate(zip(spans, nodes), 1):
        opening = re.match(rb'<exchange-document\b([^>]*)>', span.group())
        attrs = {key.decode(): value.decode() for key, value in
                 re.findall(rb'([a-z-]+)="([^"<>]*)"', opening.group(1))}
        identity = "".join(attrs.get(key, "") for key in ("country", "doc-number", "kind"))
        parsed_identity = "".join(node.attrib.get(key, "") for key in ("country", "doc-number", "kind"))
        if (not re.fullmatch(r'(?:(?:US|WO)[0-9]+[A-Z][0-9]?|USD[0-9]+S[0-9]?)', identity)
                or identity != parsed_identity or identity in identities):
            raise ValueError("RESULT_PROCESSING_XML_IDENTITY_INVALID")
        identities.add(identity)
        rows.append({"position": position, "collection": "xml_original_byte_spans",
            "collection_position": position, "raw_sha256": sha256_bytes(span.group()),
            "byte_start": span.start(), "byte_end": span.end(),
            "publication_number": identity})
    count = searches[0].attrib.get("publications-count")
    ranges = searches[0].findall("{*}range")
    if (count != str(len(rows)) or len(ranges) != 1
            or ranges[0].attrib.get("begin") != "1"
            or ranges[0].attrib.get("end") != str(len(rows))):
        raise ValueError("RESULT_PROCESSING_XML_COUNT_INVALID")
    return derived, changes, rows


def _verified_xml_derivation(task_dir: Path, run: dict, body: bytes,
                             evidence: dict) -> dict | None:
    events = [e for e in evidence.get("result_xml_derivations", [])
              if isinstance(e, dict) and e.get("source_run_id") == run.get("run_id")]
    if not events:
        return None
    if len(events) != 1:
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_CONFLICT")
    event = events[0]
    if (run.get("provider") != "epo_ops" or run.get("evidence_type") != "patent"
            or event.get("transform") not in XML_DERIVATION_TRANSFORMS
            or event.get("payload_digest") != run.get("payload_digest")
            or event.get("original_sha256") != sha256_bytes(body)
            or not all(isinstance(event.get(k), str) and event[k].strip()
                       for k in ("reviewer", "reason"))):
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_INVALID")
    if (event["transform"] == XML_REDACTION_CLOSE_TRANSFORM
            and event.get("limitations") != XML_REDACTION_CLOSE_LIMITATIONS):
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_CHANGED")
    derived, changes, rows = _derive_legacy_epo_xml(body, event["transform"])
    from common import resolve_retained_path
    retained = resolve_retained_path(task_dir, event.get("derived_path"),
                                    expected_sha256=event.get("derived_sha256"))
    if (retained.read_bytes() != derived or event.get("derived_sha256") != sha256_bytes(derived)
            or event.get("changes") != changes or event.get("rows") != rows
            or run["result_processing"].get("returned_count") != len(rows)
            or run["result_processing"].get("returned_count_basis") != "response_count_only"):
        raise ValueError("RESULT_PROCESSING_XML_DERIVATION_CHANGED")
    return event


def append_xml_derivation(task_dir: Path, source_run_id: str, item: dict) -> dict:
    """Append an explicit replayable repair receipt; the source bytes/run stay immutable."""
    from provider_utils import evidence_lock
    from common import atomic_write_json, atomic_write_bytes
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        if not enabled(task):
            raise ValueError("RESULT_PROCESSING_NOT_ENABLED")
        evidence = load_json(task_dir / "evidence.json")
        runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == source_run_id]
        if len(runs) != 1:
            raise ValueError("RESULT_PROCESSING_RUN_NOT_FOUND")
        run = runs[0]
        if (not isinstance(item, dict) or set(item) != {"transform", "reviewer", "reason"}
                or item.get("transform") not in XML_DERIVATION_TRANSFORMS
                or not all(isinstance(item.get(k), str) and item[k].strip() for k in ("reviewer", "reason"))
                or run.get("provider") != "epo_ops" or run.get("evidence_type") != "patent"
                or not str(run.get("raw_paths", [""])[0]).endswith(".xml")):
            raise ValueError("RESULT_PROCESSING_XML_DERIVATION_INPUT_INVALID")
        index, body = _retained_run(task_dir, run, evidence)
        existing = _verified_xml_derivation(task_dir, run, body, evidence)
        if existing:
            if any(existing[k] != item[k].strip() for k in ("reviewer", "reason")):
                raise ValueError("RESULT_PROCESSING_XML_DERIVATION_CONFLICT")
            return progress(task_dir, run, evidence)
        derived, changes, rows = _derive_legacy_epo_xml(body, item["transform"])
        if (index.get("returned_count_basis") != "response_count_only"
                or index.get("returned_count") != len(rows) or index.get("count_contradiction")):
            raise ValueError("RESULT_PROCESSING_XML_COUNT_INVALID")
        digest = sha256_bytes(derived)
        relative = "raw/derived/" + digest + ".xml"
        path = task_dir / relative
        if path.exists() and path.read_bytes() != derived:
            raise ValueError("RESULT_PROCESSING_XML_DERIVED_PATH_COLLISION")
        atomic_write_bytes(path, derived)
        evidence.setdefault("result_xml_derivations", []).append({
            "source_run_id": source_run_id, "payload_digest": run["payload_digest"],
            "original_sha256": sha256_bytes(body), "derived_sha256": digest,
            "derived_path": relative, "transform": item["transform"],
            "changes": changes, "rows": rows, "reviewer": item["reviewer"].strip(),
            "reason": item["reason"].strip(), "derived_at": now_iso(),
            **({"limitations": XML_REDACTION_CLOSE_LIMITATIONS.copy()}
               if item["transform"] == XML_REDACTION_CLOSE_TRANSFORM else {})})
        atomic_write_json(task_dir / "evidence.json", evidence)
        return progress(task_dir, run, evidence)


def _retained_run(task_dir: Path, run: dict, evidence: dict | None = None) -> tuple[dict, bytes]:
    index = run.get("result_processing")
    if not isinstance(index, dict) or index.get("revision") != REVISION \
            or index.get("payload_digest") != run.get("payload_digest"):
        raise ValueError("RESULT_PROCESSING_INDEX_MISSING_OR_CHANGED")
    paths = run.get("raw_paths", [])
    if not isinstance(paths, list) or len(paths) != 1:
        raise ValueError("RESULT_PROCESSING_RECEIPT_MISSING")
    from common import resolve_retained_path
    path = resolve_retained_path(task_dir, paths[0], expected_sha256=run["payload_digest"])
    if sha256_file(path) != run["payload_digest"]:
        raise ValueError("RESULT_PROCESSING_RECEIPT_CHANGED")
    body = path.read_bytes()
    suffix = path.suffix.lstrip(".")
    actual = _raw_rows(body, suffix, str(run.get("provider") or ""))
    task = load_json(task_dir / 'task.json')
    if actual and actual[0]['collection'] == WHOLE_RECORD and task.get('retrieval_workflow_revision') != 'api-first-v3':
        actual = None
    empty_ops_fault = _ops_empty_search_fault(body, suffix, str(run.get("provider") or ""))
    if (actual is None and empty_ops_fault
            and index.get("returned_count_basis") == "retained_rows"):
        actual = []
    if index["returned_count_basis"] == "retained_rows" and actual != index["rows"]:
        raise ValueError("RESULT_PROCESSING_ROWS_CHANGED")
    # An old unrecognized CUA envelope may now be readable. Derive a local
    # projection from its verified immutable receipt; never rewrite the run.
    if (run.get("provider") == "uspto_patent_browser"
            and index.get("returned_count_basis") == "unknown"
            and index.get("returned_count") is None and index.get("rows") == []
            and actual is not None):
        index = {**index, "rows": actual, "returned_count": len(actual),
                 "returned_count_basis": "retained_rows", "zero_proven": False}
        acquired = index.get("declared_retrieved_count")
        index["count_contradiction"] = (acquired is not None
            and acquired not in {len(actual), index.get("parsed_count")})
    if evidence is None:
        evidence = load_json(task_dir / "evidence.json") if (task_dir / "evidence.json").is_file() else {}
    # Older indexes missed OPS' exact zero-result fault. Re-read the immutable
    # receipt and project its zero rows without rewriting the archived run.
    coverage = run.get("metadata", {}).get("search_coverage", {})
    if (empty_ops_fault and run.get("operation") == "search"
            and run.get("status") == "no_result" and run.get("submission_state") == "submitted"
            and isinstance(coverage, dict) and coverage.get("schema_valid") is True
            and index.get("returned_count_basis") == "response_count_only"
            and type(index.get("returned_count")) is int and index["returned_count"] == 0
            and type(index.get("declared_retrieved_count")) is int and index["declared_retrieved_count"] == 0
            and type(index.get("parsed_count")) is int and index["parsed_count"] == 0
            and index.get("rows") == []
            and index.get("count_contradiction") is False
            and not _has_archived_result_material(_run_entries(evidence, str(run.get("run_id") or "")))):
        index = {**index, "returned_count_basis": "retained_rows", "zero_proven": True}
    if actual and len(actual) == 1 and actual[0]['collection'] == WHOLE_RECORD:
        _whole_record_binding(task_dir, run, evidence, body)
        if (index.get('returned_count_basis') == 'unknown' and index.get('returned_count') is None
                and index.get('rows') == [] and type(index.get('parsed_count')) is int
                and index.get('parsed_count') in {0,1}
                and index.get('count_contradiction') is False):
            index = {**index, 'rows': actual, 'returned_count': 1,
                     'returned_count_basis': 'retained_rows', 'zero_proven': False}
    derivation = _verified_xml_derivation(task_dir, run, body, evidence)
    if derivation is not None:
        index = {**index, "rows": derivation["rows"], "returned_count_basis": "derived_original_byte_spans"}
    return index, body


def detail_record_binding(task_dir, run, evidence, body=None):
    """Bind an exact detail to its known candidate; aliases need read original text."""
    from decision_workflow import candidate_content_sha256
    from workflow_v24 import scenario_supplement
    task_dir = Path(task_dir)
    task = load_json(task_dir / 'task.json')
    if (task.get('retrieval_workflow_revision') != 'api-first-v3'
            or run.get('provider') != 'serpapi_google_patents'
            or run.get('operation') != 'candidate_detail' or run.get('status') != 'success'
            or run.get('submission_state') != 'submitted'):
        raise ValueError('RESULT_PROCESSING_DETAIL_RECEIPT_INVALID')
    paths = run.get('raw_paths', [])
    if len(paths) != 1:
        raise ValueError('RESULT_PROCESSING_DETAIL_RECEIPT_INVALID')
    from common import resolve_retained_path
    path = resolve_retained_path(task_dir, paths[0], expected_sha256=run['payload_digest'])
    retained = path.read_bytes()
    if sha256_bytes(retained) != run['payload_digest'] or body is not None and retained != body:
        raise ValueError('RESULT_PROCESSING_DETAIL_RECEIPT_CHANGED')
    raw = json.loads(retained)
    params = run.get('request_params', {})
    pub = raw.get('publication_number')
    if (not _detail_record(raw, run['provider']) or params.get('publication_number',pub) != pub
            or params.get('patent_id') != 'patent/' + pub + '/en'
            or run.get('jurisdiction') != pub[:2]):
        raise ValueError('RESULT_PROCESSING_DETAIL_IDENTITY_MISMATCH')
    cid = params.get('candidate_id')
    candidates = load_json(task_dir / 'normalized-candidates.json')
    matches = [c for c in candidates.get('patents', []) if c.get('candidate_id') == cid]
    if len(matches) != 1 or matches[0].get('jurisdiction') != run['jurisdiction']:
        raise ValueError('RESULT_PROCESSING_DETAIL_CANDIDATE_MISMATCH')
    candidate = matches[0]
    entries = _run_entries(evidence, run['run_id'])
    if (len(entries) != 1 or entries[0].get('payload', {}).get('publication_number') != pub
            or entries[0]['payload'].get('candidate_id') != cid
            or entries[0]['payload'].get('source_record_sha256') != run['payload_digest']
            or any(entries[0]['payload'].get(k) != raw.get(k) for k in ('claims','images') if k in raw)):
        raise ValueError('RESULT_PROCESSING_DETAIL_ENTRY_MISMATCH')
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    locator_proof = []
    if candidate.get('publication_number') != pub:
        ledger = load_json(task_dir / 'materiality-annotations.json')
        meta = run.get('metadata', {})
        annotations = [a for a in ledger.get('annotations', [])
            if a.get('annotation_id') == meta.get('triage_decision_id') and a.get('candidate_id') == cid]
        if len(annotations) != 1 or sha256_json(annotations[0]) != meta.get('triage_decision_sha256'):
            raise ValueError('RESULT_PROCESSING_DETAIL_EXPLICIT_LOCATOR_REQUIRED')
        actions = [a for a in annotations[0].get('next_actions', [])
            if a.get('action_id') == meta.get('triage_action_id')]
        if len(actions) != 1:
            raise ValueError('RESULT_PROCESSING_DETAIL_EXPLICIT_LOCATOR_REQUIRED')
        locator = actions[0].get('target_locator', {})
        if (locator.get('kind') != 'publication_number' or locator.get('value') != pub
                or not locator.get('unique_reason') or not locator.get('evidence_refs')):
            raise ValueError('RESULT_PROCESSING_DETAIL_EXPLICIT_LOCATOR_REQUIRED')
        registry = {e.get('evidence_id'): e for e in (supplement or {}).get('evidence', [])}
        for ref in locator['evidence_refs']:
            original = registry.get(ref, {})
            if (original.get('candidate_id') != cid or original.get('publication_number') != pub
                    or original.get('jurisdiction') != run['jurisdiction']):
                raise ValueError('RESULT_PROCESSING_DETAIL_ORIGINAL_IDENTITY_MISMATCH')
            original_path = resolve_retained_path(task_dir, original.get('path'), expected_sha256=original.get('sha256'))
            text = original_path.read_text(encoding='utf-8')
            identifiers = (pub, candidate.get('publication_number'), candidate.get('application_number'))
            if (not all(isinstance(v, str) and v and re.search(r'(?<![A-Z0-9])'+re.escape(v)+r'(?![A-Z0-9])', text)
                    for v in identifiers)):
                raise ValueError('RESULT_PROCESSING_DETAIL_ORIGINAL_IDENTITY_MISMATCH')
            locator_proof.append({'evidence_id':ref, 'sha256':sha256_json(original),
                'original_sha256':original['sha256'], 'annotation_sha256':sha256_json(annotations[0]),
                'locator_sha256':sha256_json(locator)})
    return {'candidate_id':cid, 'publication_number':pub, 'jurisdiction':run['jurisdiction'],
        'candidate_content_sha256':candidate_content_sha256(candidate,evidence,supplement,task=task),
        'entry_sha256':sha256_json(entries[0]), 'source_run_sha256':sha256_json(run),
        'payload_digest':run['payload_digest'], 'locator_proof':locator_proof}


def _ops_images_binding(task_dir,run,evidence,body):
    from common import resolve_retained_path
    task_dir = Path(task_dir)
    task = load_json(task_dir/'task.json')
    params = run.get('request_params',{})
    metadata = _ops_images_metadata(body)
    if (task.get('retrieval_workflow_revision') != 'api-first-v3' or run.get('status') != 'success'
            or run.get('operation') != 'candidate_detail' or run.get('submission_state') != 'submitted'
            or params.get('detail_operation') != 'images' or metadata is None
            or any(params.get(k) != metadata['publication_number'] for k in ('document','q'))
            or run.get('jurisdiction') != metadata['jurisdiction']):
        raise ValueError('RESULT_PROCESSING_OPS_IMAGES_IDENTITY_INVALID')
    entries = _run_entries(evidence,run['run_id'])
    if len(entries) != 1 or entries[0].get('payload',{}).get('detail_operation') != 'images':
        raise ValueError('RESULT_PROCESSING_OPS_IMAGES_ENTRY_INVALID')
    rows = _candidate_rows(entries[0]['payload'])
    cid = params.get('candidate_id')
    if (len(rows) != 1 or run.get('result_processing',{}).get('parsed_count') != 1
            or rows[0].get('candidate_id') != cid
            or rows[0].get('publication_number') != metadata['publication_number']
            or rows[0].get('jurisdiction') != metadata['jurisdiction']
            or rows[0].get('detail_operations') != ['images']):
        raise ValueError('RESULT_PROCESSING_OPS_IMAGES_ENTRY_INVALID')
    candidate_rows = load_json(task_dir/'normalized-candidates.json').get('patents',[])
    known = [c for c in candidate_rows if c.get('candidate_id') == cid]
    if (len(known) != 1 or known[0].get('publication_number') != metadata['publication_number']
            or known[0].get('jurisdiction') != metadata['jurisdiction']):
        raise ValueError('RESULT_PROCESSING_OPS_IMAGES_CANDIDATE_INVALID')
    media = rows[0].get('media')
    acquired = rows[0].get('media_acquisition',{})
    if (not isinstance(media,list) or not media or rows[0].get('images') != media
            or acquired.get('available_document_pages') != metadata['available_document_pages']
            or acquired.get('retained') != len(media)):
        raise ValueError('RESULT_PROCESSING_OPS_IMAGES_MEDIA_INVALID')
    retained = []
    from PIL import Image
    for item in media:
        if (not isinstance(item,dict) or item.get('publication_number') != metadata['publication_number']
                or item.get('source_path') != metadata['fullimage_link'] or item.get('is_thumbnail') is not False
                or item.get('mime_type') != 'image/tiff' or type(item.get('page_number')) is not int
                or not 1 <= item['page_number'] <= metadata['available_document_pages']
                or item['page_number'] not in acquired.get('acquired_page_numbers',[])):
            raise ValueError('RESULT_PROCESSING_OPS_IMAGES_MEDIA_INVALID')
        path = resolve_retained_path(task_dir,item.get('path'),expected_sha256=item.get('sha256'))
        if path.stat().st_size != item.get('bytes'):
            raise ValueError('RESULT_PROCESSING_OPS_IMAGES_MEDIA_CHANGED')
        with Image.open(path) as picture:
            if picture.format != 'TIFF' or picture.size != (item.get('width'),item.get('height')):
                raise ValueError('RESULT_PROCESSING_OPS_IMAGES_MEDIA_CHANGED')
            picture.load()
        retained.append({'sha256':item['sha256'],'page_number':item['page_number'],
            'metadata_sha256':sha256_json(item)})
    return {'candidate_id':cid,'publication_number':metadata['publication_number'],
        'jurisdiction':metadata['jurisdiction'],
        'entry_sha256':sha256_json(entries[0]),'source_run_sha256':sha256_json(run),
        'payload_digest':run['payload_digest'],'image_metadata':metadata,'retained_media':retained}


def _whole_record_binding(task_dir,run,evidence,body):
    if run.get('provider') == 'epo_ops':
        return _ops_images_binding(task_dir,run,evidence,body)
    return detail_record_binding(task_dir,run,evidence,body)


def _whole_record_reading(run,evidence,body):
    if run.get('provider') == 'epo_ops':
        rows = _candidate_rows(_run_entries(evidence,run['run_id'])[0]['payload'])
        acquired = rows[0].get('media_acquisition',{})
        limits = ['The receipt describes available pages; only the explicitly retained pages are read.']
        if acquired.get('complete') is not True:
            limits.append(acquired.get('limitation') or 'All design views remain incomplete.')
        return ['identity','image_metadata','retained_media'],limits
    raw = json.loads(body)
    units = ['identity','document_text'] + (['claims'] if raw.get('claims') else []) + (['image_links'] if raw.get('images') else [])
    limits = ['Image URLs are not retained or visually reviewed drawings.']
    limits += [k for k in ('claims_truncated','images_truncated','protection_content_truncated','truncated') if raw.get(k)]
    return units,limits



def _reading_binding(run, binding):
    """OPS page reads depend on their exact original, not merged candidate facts.

    Historical event signatures are checked before this projection. Only the
    old aggregate candidate digest is ignored for OPS images; original run,
    entry, publication, page metadata and actual media hashes remain binding.
    """
    if (run.get('provider') == 'epo_ops' and run.get('operation') == 'candidate_detail'
            and run.get('request_params', {}).get('detail_operation') == 'images'
            and isinstance(binding, dict)):
        return {key: value for key, value in binding.items() if key != 'candidate_content_sha256'}
    return binding


def _whole_record_review(task_dir, run, evidence, body):
    matches = [r for r in evidence.get('record_content_reviews', [])
        if isinstance(r, dict) and r.get('source_run_id') == run['run_id']]
    if not matches:
        return None
    previous = ''
    for retained in matches:
        unsigned = {k:v for k,v in retained.items() if k != 'event_sha256'}
        if retained.get('previous_event_sha256') != previous or retained.get('event_sha256') != sha256_json(unsigned):
            raise ValueError('RESULT_PROCESSING_RECORD_REVIEW_CHANGED')
        previous = retained['event_sha256']
    event = matches[-1]
    required,limits = _whole_record_reading(run,evidence,body)
    if (_reading_binding(run, event.get('binding')) != _reading_binding(run, _whole_record_binding(task_dir,run,evidence,body))
            or event.get('reading_units') != required or event.get('limitations') != limits
            or not all(isinstance(event.get(k),str) and event[k].strip() for k in ('reviewer','reason'))):
        raise ValueError('RESULT_PROCESSING_RECORD_REVIEW_CHANGED')
    return event


def append_record_content_review(task_dir, source_run_id, request, *, _context=None):
    """Register a whole-document read, without making search cards or reading URLs as images."""
    from provider_utils import evidence_lock
    from common import atomic_write_json
    task_dir = Path(task_dir)
    with evidence_lock(task_dir) if _context is None else nullcontext():
        evidence = load_json(task_dir / 'evidence.json') if _context is None else _context[1]
        runs = [r for r in evidence.get('source_runs',[]) if r.get('run_id') == source_run_id]
        if len(runs) != 1:
            raise ValueError('RESULT_PROCESSING_RUN_NOT_FOUND')
        run = runs[0]
        index, body = _retained_run(task_dir,run,evidence)
        if not index['rows'] or index['rows'][0]['collection'] != WHOLE_RECORD:
            raise ValueError('RESULT_PROCESSING_NOT_WHOLE_RECORD')
        units,limits = _whole_record_reading(run,evidence,body)
        if (not isinstance(request,dict) or request.get('reading_units') != units
                or not all(isinstance(request.get(k),str) and request[k].strip() for k in ('reviewer','reason'))):
            raise ValueError('RESULT_PROCESSING_RECORD_READING_REQUIRED')
        record = {'source_run_id':source_run_id,'binding':_whole_record_binding(task_dir,run,evidence,body),
            'reading_units':units,'limitations':limits,'reviewer':request['reviewer'].strip(),'reason':request['reason'].strip()}
        prior_events = [r for r in evidence.get('record_content_reviews',[]) if r.get('source_run_id') == source_run_id]
        previous = ''
        for retained in prior_events:
            if retained.get('previous_event_sha256') != previous or retained.get('event_sha256') != sha256_json({k:v for k,v in retained.items() if k != 'event_sha256'}):
                raise ValueError('RESULT_PROCESSING_RECORD_REVIEW_CHANGED')
            previous = retained['event_sha256']
        prior = prior_events[-1] if prior_events else None
        if prior is not None and _reading_binding(run, prior.get('binding')) == _reading_binding(run, record['binding']):
            comparable = {k:v for k,v in prior.items() if k not in {'reviewed_at','event_sha256','previous_event_sha256'}}
            comparable['binding'] = _reading_binding(run, comparable.get('binding'))
            if comparable != {**record, 'binding': _reading_binding(run, record['binding'])}:
                raise ValueError('RESULT_PROCESSING_RECORD_REVIEW_CONFLICT')
        else:
            event = {**record,'reviewed_at':now_iso(),'previous_event_sha256':previous}
            event['event_sha256'] = sha256_json(event)
            evidence.setdefault('record_content_reviews',[]).append(event)
            if _context is None:
                atomic_write_json(task_dir / 'evidence.json',evidence)
        return progress(task_dir,run,evidence) if _context is None else {'source_run_id': source_run_id}


def project_entry(entry: dict, evidence: dict, task_dir: Path) -> dict:
    """Apply validated append-only identity bindings without rewriting archived candidates."""
    run_id = entry.get("source_run_id")
    bindings = [event for event in evidence.get("result_parses", [])
                if isinstance(event, dict) and event.get("source_run_id") == run_id
                and event.get("prior_candidate_sha256")]
    if not bindings:
        return entry
    runs = [run for run in evidence.get("source_runs", []) if run.get("run_id") == run_id]
    if len(runs) != 1:
        raise ValueError("RESULT_PROCESSING_RUN_NOT_FOUND")
    index, _ = _retained_run(task_dir, runs[0], evidence)
    rows = {row["position"]: row for row in index["rows"]}
    projected = copy.deepcopy(entry)
    candidates = _candidate_rows(projected.get("payload"))
    seen = set()
    for event in bindings:
        source = rows.get(event.get("position"))
        matches = [candidate for candidate in candidates
                   if sha256_json(candidate) == event["prior_candidate_sha256"]]
        if (source is None or source.get("collection") != "xml_original_byte_spans"
                or event.get("position") in seen or len(matches) != 1
                or event.get("payload_digest") != runs[0].get("payload_digest")
                or event.get("raw_sha256") != source["raw_sha256"]
                or event.get("publication_number") != source["publication_number"]
                or matches[0].get("publication_number") != source["publication_number"]
                or not all(isinstance(event.get(k), str) and event[k].strip()
                           for k in ("reviewer", "reason"))):
            raise ValueError("RESULT_PROCESSING_IDENTITY_BINDING_CHANGED")
        seen.add(event["position"])
        matches[0].update(source_position=source["position"], source_record_sha256=source["raw_sha256"])
        if event.get("candidate_sha256") != sha256_json(matches[0]):
            raise ValueError("RESULT_PROCESSING_IDENTITY_BINDING_CHANGED")
        if runs[0].get("candidate_acquisition"):
            from candidate_acquisition import parsed_identity
            key, basis = parsed_identity(runs[0], matches[0], source["position"])
            if (event.get("candidate_acquisition_identity_key") != key
                    or event.get("candidate_acquisition_basis") != basis):
                raise ValueError("RESULT_PROCESSING_IDENTITY_BINDING_CHANGED")
    return projected


def _run_entries(evidence: dict, run_id: str, task_dir: Path | None = None) -> list[dict]:
    entries = [entry for name in COLLECTIONS.values()
            for entry in evidence.get("collections", {}).get(name, [])
            if isinstance(entry, dict) and entry.get("source_run_id") == run_id]
    return [project_entry(entry, evidence, task_dir) for entry in entries] if task_dir else entries


def _has_archived_result_material(entries: list[dict]) -> bool:
    """Empty receipt/archive envelopes are not result material; candidate rows are."""
    return any(_candidate_rows(entry.get("payload")) for entry in entries)


def _parsed_positions(index: dict, entries: list[dict]) -> tuple[set[int], int]:
    rows = index["rows"]
    by_hash: dict[str, set[int]] = {}
    for row in rows:
        if row["raw_sha256"]:
            by_hash.setdefault(row["raw_sha256"], set()).add(row["position"])
    located: set[int] = set()
    unlocated = 0
    for entry in entries:
        for item in _candidate_rows(entry.get("payload")):
            position = item.get("source_position") or item.get("result_position")
            digest = (item.get("source_record_sha256")
                      or item.get("original_source_record_sha256") or sha256_json(item))
            if type(position) is int and 1 <= position <= len(rows):
                located.add(position)
            elif isinstance(digest, str) and len(by_hash.get(digest, ())) == 1:
                located.update(by_hash[digest])
            else:
                unlocated += 1
    return located, unlocated


def _latest_decisions(evidence: dict, run_id: str, index: dict | None = None) -> dict[int, dict]:
    output = {}
    rows = {row["position"]: row for row in index["rows"]} if index is not None else None
    for event in evidence.get("result_dispositions", []):
        if isinstance(event, dict) and event.get("source_run_id") == run_id:
            position = event.get("position")
            if (type(position) is not int or position in output
                    or event.get("outcome") not in OUTCOMES
                    or not isinstance(event.get("reviewer"), str) or not event["reviewer"].strip()
                    or not isinstance(event.get("reason"), str) or not event["reason"].strip()
                    or rows is not None and (position not in rows
                        or event.get("raw_sha256") != rows[position]["raw_sha256"]
                        or event.get("payload_digest") != index["payload_digest"])):
                raise ValueError("RESULT_PROCESSING_DECISION_INVALID_OR_CHANGED")
            output[event["position"]] = event
    return output


def progress(task_dir: Path, run: dict, evidence: dict) -> dict:
    index, body = _retained_run(task_dir, run, evidence)
    entries = _run_entries(evidence, str(run["run_id"]), task_dir)
    located, unlocated = _parsed_positions(index, entries)
    decisions = _latest_decisions(evidence, str(run["run_id"]), index)
    receipt_disposition = _latest_receipt_disposition(evidence, run, index)
    if receipt_disposition is not None:
        suffix = str(run.get("raw_paths", [""])[0]).rsplit(".", 1)[-1]
        fault = _recognized_fault(body, suffix, str(run.get("provider") or ""))
        if ((run.get("status") not in NON_SUCCESS_STATUSES and not fault)
                or run.get("status") == "success"
                or _raw_rows(body, suffix, str(run.get("provider") or "")) is not None
                or index.get("parsed_count") != 0 or index.get("rows") != []
                or index.get("count_contradiction") or _has_archived_result_material(entries)):
            raise ValueError("RESULT_PROCESSING_RECEIPT_DISPOSITION_INVALID_OR_CHANGED")
    whole = bool(index['rows'] and index['rows'][0]['collection'] == WHOLE_RECORD)
    whole_review = _whole_record_review(task_dir,run,evidence,body) if whole else None
    if whole:
        return {'source_run_id':run['run_id'], 'query_id':run.get('query_id'),
            'request_status':run.get('status'), 'submission_state':run.get('submission_state'),
            'result_form':WHOLE_RECORD, 'returned_count':1, 'parsed_count':index['parsed_count'],
            'located_parsed_count':0,'unlocated_parsed_count':0,'reviewed_count':int(whole_review is not None),
            'pending_positions':[] if whole_review else [1], 'pending_parse_positions':[],
            'zero_proven':False,'receipt_reviewed':False,'receipt_disposition':None,
            'record_content_review':whole_review,'reading_units':_whole_record_reading(run,evidence,body)[0],
            'count_contradiction':index['count_contradiction'],
            'material_processing_complete':whole_review is not None and not index['count_contradiction']}
    pending = [row["position"] for row in index["rows"] if row["position"] not in decisions]
    parse_pending = [position for position in pending if position not in located]
    count = index["returned_count"]
    return {"source_run_id": run["run_id"], "query_id": run.get("query_id"),
            "request_status": run.get("status"), "submission_state": run.get("submission_state"),
            "returned_count": count, "parsed_count": len(located) + unlocated,
            "located_parsed_count": len(located),
            "unlocated_parsed_count": unlocated, "reviewed_count": len(decisions),
            "pending_positions": pending, "pending_parse_positions": parse_pending,
            "zero_proven": index["zero_proven"],
            "receipt_reviewed": receipt_disposition is not None,
            "receipt_disposition": receipt_disposition,
            "count_contradiction": index["count_contradiction"],
            "material_processing_complete": (
                ((count == 0 and index["zero_proven"])
                 or (count is not None and count > 0 and not pending and not unlocated
                     and all(event["outcome"] != "pending_parse"
                             for event in decisions.values())))
                and not index["count_contradiction"]
            ) or receipt_disposition is not None}


def zero_result_proven(run: dict, evidence: dict, task_dir: Path | None = None) -> bool:
    """Reuse verified receipt projection when available; never promote without it."""
    index = run.get("result_processing")
    if not isinstance(index, dict):
        return False
    if task_dir is None:
        return index.get("zero_proven") is True
    try:
        return progress(Path(task_dir), run, evidence).get("zero_proven") is True
    except (OSError, ValueError, KeyError, TypeError):
        return False



def _specific_record_scope(task_dir, run):
    """A failed exact-record request is still local to its bound candidate."""
    if run.get('operation') not in {'candidate_detail','candidate_verification'}:
        return {}
    candidate = (run.get('request_params') or {}).get('candidate_id')
    if not isinstance(candidate, str) or not candidate.strip() or task_dir is None:
        return {}
    try:
        plan = load_json(Path(task_dir)/'search-plan.json')
        rows = [row for row in plan.get('queries', {}).get(run.get('provider'), [])
            if row.get('query_id') == run.get('query_id')]
        if (len(rows) != 1 or sha256_json(rows[0]) != run.get('plan_entry_sha256')
                or rows[0].get('candidate_id') != candidate
                or any(rows[0].get(key) != run.get(key) for key in ('operation','jurisdiction','right_type'))):
            return {}
        return {'candidate_id':candidate, 'scenario_id':rows[0].get('scenario_id')}
    except (OSError, ValueError, TypeError, KeyError):
        return {}

def work_entries(task: dict, evidence: dict, task_dir: Path | None) -> list[dict]:
    if not enabled(task) or task_dir is None:
        return []
    output = []
    for run in evidence.get("source_runs", []):
        if not isinstance(run, dict) or not isinstance(run.get("result_processing"), dict):
            continue
        try:
            state = progress(Path(task_dir), run, evidence)
            if state["material_processing_complete"]:
                continue
            reason = "SOURCE_RESULTS_PENDING_PROCESSING"
        except (OSError, ValueError, KeyError, TypeError):
            state = {"pending_positions": [], "pending_parse_positions": []}
            reason = "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"
        output.append({"kind": "agent_investigation", "state": "awaiting_review",
                       "provider": run.get("provider"), "query_id": run.get("query_id"),
                       "source_run_id": run.get("run_id"), **_specific_record_scope(task_dir, run),
                       "jurisdiction": run.get("jurisdiction"),
                       "right_type": run.get("right_type"), "reason": reason,
                       "returned_count": state.get("returned_count"),
                       "parsed_count": state.get("parsed_count"),
                       "reviewed_count": state.get("reviewed_count"),
                       "result_form": state.get("result_form"),
                       "reading_units": state.get("reading_units"),
                       "pending_positions": state["pending_positions"],
                       "pending_parse_positions": state["pending_parse_positions"]})
    return output


def append_dispositions(task_dir: Path, source_run_id: str, decisions: list[dict], *, _context=None) -> dict:
    from provider_utils import evidence_lock
    from common import atomic_write_json
    with evidence_lock(task_dir) if _context is None else nullcontext():
        task = load_json(task_dir / "task.json") if _context is None else _context[0]
        if not enabled(task):
            raise ValueError("RESULT_PROCESSING_NOT_ENABLED")
        evidence = load_json(task_dir / "evidence.json") if _context is None else _context[1]
        runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == source_run_id]
        if len(runs) != 1:
            raise ValueError("RESULT_PROCESSING_RUN_NOT_FOUND")
        run = runs[0]
        index, _ = _retained_run(task_dir, run, evidence)
        if not isinstance(decisions, list) or not decisions:
            raise ValueError("RESULT_PROCESSING_DECISIONS_REQUIRED")
        if index['rows'] and index['rows'][0]['collection'] == WHOLE_RECORD:
            raise ValueError('RESULT_PROCESSING_WHOLE_RECORD_REVIEW_REQUIRED')
        rows = {row["position"]: row for row in index["rows"]}
        existing = _latest_decisions(evidence, source_run_id, index)
        pending = []
        seen = set()
        for item in decisions:
            if not isinstance(item, dict) or type(item.get("position")) is not int:
                raise ValueError("RESULT_PROCESSING_POSITION_INVALID")
            position = item["position"]
            if position not in rows or position in seen:
                raise ValueError("RESULT_PROCESSING_POSITION_UNKNOWN_OR_DUPLICATE")
            seen.add(position)
            if not rows[position]["raw_sha256"]:
                raise ValueError("RESULT_PROCESSING_ROW_CONTENT_UNAVAILABLE")
            if item.get("outcome") not in OUTCOMES or not all(isinstance(item.get(k), str) and item[k].strip()
                    for k in ("reviewer", "reason")):
                raise ValueError("RESULT_PROCESSING_REVIEW_INVALID")
            candidate_ids = item.get("candidate_ids", [])
            if (not isinstance(candidate_ids, list)
                    or any(not isinstance(cid, str) or not cid.strip() for cid in candidate_ids)
                    or len(candidate_ids) != len(set(candidate_ids))):
                raise ValueError("RESULT_PROCESSING_CANDIDATES_INVALID")
            if item["outcome"] in {"candidate", "duplicate_source"} and not candidate_ids \
                    or item["outcome"] == "non_candidate" and candidate_ids:
                raise ValueError("RESULT_PROCESSING_OUTCOME_CANDIDATES_MISMATCH")
            if candidate_ids:
                candidates = load_json(task_dir / "normalized-candidates.json")
                known = set()
                for name in ("patents", "trademarks", "copyright_assets", "enforcement"):
                    for candidate in candidates.get(name, []):
                        if not isinstance(candidate, dict):
                            continue
                        for source in candidate.get("sources", []):
                            if not isinstance(source, dict) or source.get("source_run_id") != source_run_id:
                                continue
                            bound_position = source.get("source_position") or source.get("result_position")
                            bound_hashes = {source.get("source_record_sha256"),
                                            source.get("original_source_record_sha256")}
                            if (bound_position is None and not any(bound_hashes)
                                    or bound_position is not None and bound_position != position
                                    or any(bound_hashes) and rows[position]["raw_sha256"] not in bound_hashes):
                                continue
                            known.add(candidate.get("candidate_id"))
                if not set(candidate_ids) <= known:
                    raise ValueError("RESULT_PROCESSING_CANDIDATE_NOT_BOUND")
            record = {"source_run_id": source_run_id, "position": position,
                      "raw_sha256": rows[position]["raw_sha256"],
                      "payload_digest": run["payload_digest"],
                      "outcome": item["outcome"], "candidate_ids": candidate_ids,
                      "reviewer": item["reviewer"].strip(), "reason": item["reason"].strip()}
            if position in existing:
                if {key: value for key, value in existing[position].items() if key != "reviewed_at"} != record:
                    raise ValueError("RESULT_PROCESSING_DECISION_CONFLICT")
                continue
            pending.append({**record, "reviewed_at": now_iso()})
        if pending:
            evidence.setdefault("result_dispositions", []).extend(pending)
            if _context is None:
                atomic_write_json(task_dir / "evidence.json", evidence)
        return progress(task_dir, run, evidence) if _context is None else {'source_run_id': source_run_id}


def _latest_receipt_disposition(evidence: dict, run: dict, index: dict) -> dict | None:
    matches = [item for item in evidence.get("receipt_dispositions", [])
               if isinstance(item, dict) and item.get("source_run_id") == run.get("run_id")]
    if len(matches) > 1:
        raise ValueError("RESULT_PROCESSING_RECEIPT_DISPOSITION_INVALID_OR_CHANGED")
    if not matches:
        return None
    item = matches[0]
    if (item.get("outcome") not in RECEIPT_OUTCOMES
            or item.get("payload_digest") != run.get("payload_digest")
            or item.get("raw_sha256") != run.get("payload_digest")
            or not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip()
            or item.get("reviewer") != item["reviewer"].strip()
            or not isinstance(item.get("reason"), str) or not item["reason"].strip()
            or item.get("reason") != item["reason"].strip()):
        raise ValueError("RESULT_PROCESSING_RECEIPT_DISPOSITION_INVALID_OR_CHANGED")
    return item


def append_receipt_disposition(task_dir: Path, source_run_id: str, item: dict, *, _context=None) -> dict:
    """Classify a verified, explicitly failed non-result receipt without asserting zero hits."""
    from provider_utils import evidence_lock
    from common import atomic_write_json
    with evidence_lock(task_dir) if _context is None else nullcontext():
        task = load_json(task_dir / "task.json") if _context is None else _context[0]
        if not enabled(task):
            raise ValueError("RESULT_PROCESSING_NOT_ENABLED")
        evidence = load_json(task_dir / "evidence.json") if _context is None else _context[1]
        runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == source_run_id]
        if len(runs) != 1:
            raise ValueError("RESULT_PROCESSING_RUN_NOT_FOUND")
        run = runs[0]
        index, body = _retained_run(task_dir, run, evidence)
        if (not isinstance(item, dict) or item.get("outcome") not in RECEIPT_OUTCOMES
                or not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip()
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
            raise ValueError("RESULT_PROCESSING_RECEIPT_REVIEW_INVALID")
        # Receipt review is only for a query failure explicitly represented by
        # the run state, or a provider-recognized XML fault envelope. An
        # unrecognized rows=None payload alone is never enough.
        is_fault = _recognized_fault(
                body, str(run.get("raw_paths", [""])[0]).rsplit(".", 1)[-1],
                str(run.get("provider") or ""))
        if run.get("status") not in NON_SUCCESS_STATUSES and not is_fault:
            raise ValueError("RESULT_PROCESSING_RECEIPT_NOT_EXPLICIT_ERROR")
        if (_raw_rows(body, str(run.get("raw_paths", [""])[0]).rsplit(".", 1)[-1],
                      str(run.get("provider") or "")) is not None
                or index.get("parsed_count") != 0 or index.get("rows") != []
                or index.get("count_contradiction")
                or _has_archived_result_material(_run_entries(evidence, source_run_id))):
            raise ValueError("RESULT_PROCESSING_RECEIPT_HAS_RESULT_MATERIAL")
        if run.get("status") == "success" or run.get("status") == "no_result" and not is_fault:
            raise ValueError("RESULT_PROCESSING_RECEIPT_NOT_EXPLICIT_ERROR")
        record = {"source_run_id": source_run_id, "payload_digest": run["payload_digest"],
                  "raw_sha256": run["payload_digest"], "outcome": "non_result_error",
                  "reviewer": item["reviewer"].strip(), "reason": item["reason"].strip()}
        existing = _latest_receipt_disposition(evidence, run, index)
        if existing is not None:
            if {k: v for k, v in existing.items() if k != "reviewed_at"} != record:
                raise ValueError("RESULT_PROCESSING_RECEIPT_DISPOSITION_CONFLICT")
        else:
            evidence.setdefault("receipt_dispositions", []).append({**record, "reviewed_at": now_iso()})
            if _context is None:
                atomic_write_json(task_dir / "evidence.json", evidence)
        return progress(task_dir, run, evidence) if _context is None else {'source_run_id': source_run_id}


def append_parsed_rows(task_dir: Path, source_run_id: str, parsed_rows: list[dict], *, _context=None) -> dict:
    """Resume local normalization from a retained row; never submit a source request."""
    from provider_utils import evidence_lock
    from common import atomic_write_json, stable_id
    with evidence_lock(task_dir) if _context is None else nullcontext():
        task = load_json(task_dir / "task.json") if _context is None else _context[0]
        if not enabled(task):
            raise ValueError("RESULT_PROCESSING_NOT_ENABLED")
        evidence = load_json(task_dir / "evidence.json") if _context is None else _context[1]
        runs = [r for r in evidence.get("source_runs", []) if r.get("run_id") == source_run_id]
        if len(runs) != 1 or runs[0].get("evidence_type") not in COLLECTIONS:
            raise ValueError("RESULT_PROCESSING_RUN_NOT_FOUND")
        run = runs[0]
        if run.get("provider") in RAW_LISTS:
            # These adapters have an exact raw-card/normalized-card contract.
            # A hand-entered parsed row would break its source integrity proof.
            raise ValueError("RESULT_PROCESSING_STRICT_ADAPTER_REPLAY_REQUIRED")
        index, body = _retained_run(task_dir, run, evidence)
        if _unbound_cua_rows(body, str(run.get("provider") or "")):
            raise ValueError("RESULT_PROCESSING_QUERY_BINDING_REQUIRED")
        if not isinstance(parsed_rows, list) or not parsed_rows:
            raise ValueError("RESULT_PROCESSING_PARSED_ROWS_REQUIRED")
        source_rows = {row["position"]: row for row in index["rows"]}
        collection = evidence.setdefault("collections", {}).setdefault(COLLECTIONS[run["evidence_type"]], [])
        entries = _run_entries(evidence, source_run_id)
        if len(entries) > 1:
            raise ValueError("RESULT_PROCESSING_MULTIPLE_SOURCE_ENTRIES")
        existing = entries[0] if entries else None
        if existing is not None and not isinstance(existing.get("payload"), (dict, list)):
            raise ValueError("RESULT_PROCESSING_SOURCE_PAYLOAD_INVALID")
        current = _candidate_rows(existing.get("payload")) if existing else []
        by_position = {row.get("source_position"): row for row in current
                       if type(row.get("source_position")) is int}
        by_hash = {}
        for row in current:
            digest = row.get("source_record_sha256") or row.get("original_source_record_sha256")
            if isinstance(digest, str) and digest:
                by_hash.setdefault(digest, []).append(row)
        additions = []
        parse_events = []
        seen = set()
        for item in parsed_rows:
            if not isinstance(item, dict) or type(item.get("position")) is not int:
                raise ValueError("RESULT_PROCESSING_POSITION_INVALID")
            position = item["position"]
            if position not in source_rows or position in seen:
                raise ValueError("RESULT_PROCESSING_POSITION_UNKNOWN_OR_DUPLICATE")
            seen.add(position)
            source = source_rows[position]
            if not source["raw_sha256"]:
                raise ValueError("RESULT_PROCESSING_ROW_CONTENT_UNAVAILABLE")
            if not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip() \
                    or not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise ValueError("RESULT_PROCESSING_REVIEW_INVALID")
            if "bind_existing_publication_number" in item:
                identity = item["bind_existing_publication_number"]
                if (set(item) != {"position", "bind_existing_publication_number", "reviewer", "reason"}
                        or source.get("collection") != "xml_original_byte_spans"
                        or identity != source.get("publication_number")):
                    raise ValueError("RESULT_PROCESSING_IDENTITY_BINDING_INVALID")
                matches = [row for row in current if row.get("publication_number") == identity
                           and row.get("source_position") is None
                           and row.get("source_record_sha256") is None]
                if len(matches) != 1:
                    raise ValueError("RESULT_PROCESSING_IDENTITY_BINDING_AMBIGUOUS")
                prior = matches[0]
                projected = {**prior, "source_position": position, "source_record_sha256": source["raw_sha256"]}
                event = {"source_run_id": source_run_id, "position": position,
                    "raw_sha256": source["raw_sha256"], "payload_digest": run["payload_digest"],
                    "publication_number": identity, "prior_candidate_sha256": sha256_json(prior),
                    "candidate_sha256": sha256_json(projected), "reviewer": item["reviewer"].strip(),
                    "reason": item["reason"].strip()}
                from candidate_acquisition import enabled as acquisition_enabled, parsed_identity
                if acquisition_enabled(task) and run.get("candidate_acquisition"):
                    key, basis = parsed_identity(run, projected, position)
                    event.update(candidate_acquisition_identity_key=key, candidate_acquisition_basis=basis)
                existing_bindings = [e for e in evidence.get("result_parses", [])
                    if e.get("source_run_id") == source_run_id and e.get("position") == position
                    and e.get("prior_candidate_sha256")]
                if existing_bindings:
                    if len(existing_bindings) != 1 or {k: v for k, v in existing_bindings[0].items()
                            if k != "parsed_at"} != event:
                        raise ValueError("RESULT_PROCESSING_IDENTITY_BINDING_CONFLICT")
                else:
                    parse_events.append({**event, "parsed_at": now_iso()})
                continue
            candidate = item.get("candidate")
            if source.get("collection") == "xml_original_byte_spans":
                raise ValueError("RESULT_PROCESSING_XML_EXISTING_IDENTITY_BINDING_REQUIRED")
            if not isinstance(candidate, dict) or not candidate:
                raise ValueError("RESULT_PROCESSING_CANDIDATE_INVALID")
            candidate = dict(candidate)
            candidate.update(source_position=position, source_record_sha256=source["raw_sha256"])
            prior = by_position.get(position)
            if prior is None and len(by_hash.get(source["raw_sha256"], [])) == 1:
                prior = by_hash[source["raw_sha256"]][0]
            if prior is not None:
                common = {key: value for key, value in candidate.items()
                          if key not in {"source_position", "source_record_sha256"}}
                if any(prior.get(key) != value for key, value in common.items()):
                    raise ValueError("RESULT_PROCESSING_PARSED_ROW_CONFLICT")
                continue
            additions.append(candidate)
            parse_events.append({"source_run_id": source_run_id, "position": position,
                "raw_sha256": source["raw_sha256"], "payload_digest": run["payload_digest"],
                "candidate_sha256": sha256_json(candidate),
                "reviewer": item["reviewer"].strip(), "reason": item["reason"].strip(),
                "parsed_at": now_iso()})
            from candidate_acquisition import enabled as acquisition_enabled, parsed_identity
            if acquisition_enabled(task) and run.get("candidate_acquisition"):
                key, basis = parsed_identity(run, candidate, position)
                parse_events[-1].update(candidate_acquisition_identity_key=key,
                                        candidate_acquisition_basis=basis)
        if additions:
            if existing is None:
                existing = {"evidence_id": stable_id("EV-REPARSE", source_run_id),
                            "source_run_id": source_run_id, "query_id": run.get("query_id"),
                            "provider": run.get("provider"), "operation": run.get("operation"),
                            "jurisdiction": run.get("jurisdiction"),
                            "right_type": run.get("right_type"),
                            "collected_at": run.get("finished_at"), "payload": {"candidates": []},
                            "plan_entry_sha256": run.get("plan_entry_sha256")}
                collection.append(existing)
            payload = existing.get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
                raise ValueError("RESULT_PROCESSING_SOURCE_PAYLOAD_INVALID")
            payload["candidates"].extend(additions)
        if parse_events:
            evidence.setdefault("result_parses", []).extend(parse_events)
            if _context is None:
                atomic_write_json(task_dir / "evidence.json", evidence)
        return progress(task_dir, run, evidence) if _context is None else {'source_run_id': source_run_id}


def append_processing_batch(task_dir: Path, events: list[dict]) -> dict:
    """One receipt-bound local transaction, with one evidence write and refresh."""
    from provider_utils import evidence_lock
    from common import atomic_write_json
    task_dir = Path(task_dir).resolve()
    if not isinstance(events, list) or not events:
        raise ValueError('RESULT_PROCESSING_BATCH_REQUIRED')
    operations = {'parsed_rows': append_parsed_rows, 'decisions': append_dispositions,
        'receipt_disposition': append_receipt_disposition,
        'record_content_review': append_record_content_review}
    with evidence_lock(task_dir):
        task = load_json(task_dir / 'task.json')
        if not enabled(task):
            raise ValueError('RESULT_PROCESSING_NOT_ENABLED')
        evidence = load_json(task_dir / 'evidence.json')
        before = sha256_json(evidence)
        run_ids = []
        for event in events:
            if not isinstance(event, dict) or set(event) - {'source_run_id', *operations}:
                raise ValueError('RESULT_PROCESSING_BATCH_EVENT_INVALID')
            run_id = event.get('source_run_id')
            keys = [key for key in operations if key in event]
            if not isinstance(run_id, str) or not run_id or not keys:
                raise ValueError('RESULT_PROCESSING_BATCH_EVENT_INVALID')
            # Parse then decide in the same in-memory snapshot. Candidate
            # outcomes still require existing, correctly bound normalized IDs.
            for key in keys:
                operations[key](task_dir, run_id, event[key], _context=(task, evidence))
            if run_id not in run_ids:
                run_ids.append(run_id)
        runs = {run['run_id']: run for run in evidence.get('source_runs', [])}
        states = [progress(task_dir, runs[run_id], evidence) for run_id in run_ids]
        changed = sha256_json(evidence) != before
        if changed:
            atomic_write_json(task_dir / 'evidence.json', evidence)
        return {'source_runs': states, 'recorded': changed, 'event_count': len(events)}
