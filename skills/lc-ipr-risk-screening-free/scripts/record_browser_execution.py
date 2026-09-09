"""Plan-bound execution receipt validation for 2.4 browser evidence.

Receipts establish reproducible provenance, not an unforgeable attestation of a
third-party service. They never constitute source-wide automation permission.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from common import load_json, path_within, sha256_file, validate_checked_at, recall_integrity_enabled


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def ppubs_row_coverage(pages: list, total: int | None) -> dict:
    """Reconstruct source ordinals independently from deduplicated candidates."""
    ordinals, conflicts, families = {}, set(), {}
    invalid, last, duplicates = 0, None, False
    for page in pages:
        for view in page.get("viewports") or []:
            last = view
            snapshot_records = {}
            if view.get("total_hits") != total or view.get("loading") is not False:
                invalid += 1
            for row in view.get("rows") or []:
                record = re.sub(r"[^A-Za-z0-9]", "", str(row.get("documentId") or "")).upper()
                raw = str(row.get("rowNumber") or "")
                ordinal = int(raw) if re.fullmatch(r"[0-9]+", raw) else 0
                if (type(total) is not int or not 1 <= ordinal <= total
                        or not re.fullmatch(r"US(?:(?:D|RE|PP)?\d{5,11})(?:[A-Z]\d?)?", record)):
                    invalid += 1
                    continue
                if record in snapshot_records and snapshot_records[record] != ordinal:
                    duplicates = True
                snapshot_records[record] = ordinal
                if ordinal in ordinals and ordinals[ordinal] != record:
                    conflicts.add(ordinal)
                else:
                    ordinals[ordinal] = record
                label = str(row.get("familyGroup") or "").strip()
                if re.fullmatch(r"[+\u2212-]\s*\d*", label):
                    families[record] = label
    mappings = [[ordinal, record] for ordinal, record in sorted(ordinals.items())]
    position = (last or {}).get("viewport") or {}
    top, height, scroll = (position.get(key) for key in ("top", "height", "scroll_height"))
    bottom = (all(type(value) in {int, float} and math.isfinite(value) for value in (top, height, scroll))
              and top >= 0 and height > 0 and scroll >= height and top + height >= scroll - 1)
    collapsed = sorted(record for record, label in families.items() if re.fullmatch(r"\+\s*\d+", label))
    return {"reported_rows": total, "retrieved_rows": len(mappings), "unique_publications": len(set(ordinals.values())),
            "ordinal_records": mappings, "duplicate_rows_observed": duplicates,
            "invalid_observations": invalid, "conflicting_ordinals": sorted(conflicts),
            "unexpanded_family_records": collapsed, "bottom_confirmed": bottom,
            "complete": type(total) is int and total > 0 and len(mappings) == total
                and all(ordinal == index for index, (ordinal, _) in enumerate(mappings, 1))
                and not invalid and not conflicts and not collapsed and bottom}


def ppubs_counting_complete(coverage: dict, records: list | None = None) -> bool:
    """Check the recorded row-unit proof, preserving unique publication counts."""
    proof = coverage.get("row_coverage")
    if (coverage.get("coverage_counting_revision") != "ppubs-result-rows-v1" or not isinstance(proof, dict)
            or proof.get("complete") is not True or proof.get("bottom_confirmed") is not True
            or proof.get("duplicate_rows_observed") is not True
            or type(coverage.get("total_hits")) is not int or coverage["total_hits"] <= 0
            or proof.get("reported_rows") != coverage["total_hits"]
            or proof.get("retrieved_rows") != coverage["total_hits"]
            or proof.get("unique_publications") != coverage.get("retrieved_hits")
            or proof.get("invalid_observations") != 0 or proof.get("conflicting_ordinals") != []
            or proof.get("unexpanded_family_records") != [] or coverage.get("viewport_gaps") != []
            or coverage.get("unconfirmed_family_member_count") != 0
            or (coverage.get("family_expansion") or {}).get("gaps") != []):
        return False
    mappings = proof.get("ordinal_records")
    if (not isinstance(mappings, list) or len(mappings) != coverage["total_hits"]
            or any(not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int or pair[0] != index
                   or not isinstance(pair[1], str) or not re.fullmatch(r"US(?:(?:D|RE|PP)?\d{5,11})(?:[A-Z]\d?)?", pair[1])
                   for index, pair in enumerate(mappings, 1))):
        return False
    identities = {pair[1] for pair in mappings}
    if len(identities) != coverage.get("retrieved_hits"):
        return False
    if records is not None:
        actual = {re.sub(r"[^A-Za-z0-9]", "", str(row.get("publication_number") or row.get("record_number") or "")).upper()
                  for row in records}
        if len(records) != len(identities) or actual != identities:
            return False
    return True


def _tm_zero_transition(binding: dict, rendered: str) -> bool:
    if binding.get("binding_method") != "submitted_zero_transition_v1":
        return False
    transition = binding.get("zero_result_transition")
    if not isinstance(transition, dict):
        return False
    before = transition.get("baseline")
    if (not isinstance(before, dict) or type(before.get("zero_visible")) is not bool
            or type(before.get("card_count")) is not int or before["card_count"] < 0
            or not isinstance(before.get("result_query"), str)
            or not isinstance(transition.get("submission_id"), str) or not transition["submission_id"]
            or transition.get("rendered_query") != rendered or transition.get("zero_visible") is not True
            or binding.get("result_query") != "" or binding.get("result_view") != "list"
            or type(transition.get("observed_loading")) is not bool):
        return False
    from urllib.parse import urlsplit
    current, previous = urlsplit(str(transition.get("final_url") or "")), urlsplit(str(before.get("url") or ""))
    if (current.scheme != "https" or current.netloc != "tmsearch.uspto.gov" or current.path != "/search/search-results"
            or previous.scheme != "https" or previous.netloc != "tmsearch.uspto.gov"):
        return False
    method = transition.get("method")
    container = transition.get("result_container_transition")
    result_cycle = (isinstance(container, dict) and all(container.get(key) is True for key in
                    ("prior_zero_disappeared", "result_loading_observed", "result_zero_reappeared")))
    return ((method == "result_route" and not before["zero_visible"] and not previous.path.startswith("/search/search-results"))
            or (method == "result_replaced" and not before["zero_visible"] and bool(before["card_count"] or before["result_query"]))
            or (method == "loading_cycle" and before["zero_visible"] and result_cycle and transition["observed_loading"] is True))


def validate_tm_result_binding(capture: dict, observation: dict, rendered: str) -> None:
    """Recheck count/query invariants instead of trusting the browser's boolean."""
    binding = capture.get("query_binding") or {}
    if not isinstance(binding, dict):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM binding must be an object")
    total = binding.get("total_hits")
    rows = capture.get("candidates")
    pages = capture.get("result_pages") or []
    displayed_rows = pages[-1].get("candidates") if isinstance(pages, list) and pages and isinstance(pages[-1], dict) else rows
    normalize = lambda value: re.sub(r"\s+", " ", str(value or "").replace("“", '"').replace("”", '"')).strip()
    query = normalize(rendered)
    zero_transition = (capture.get("status") == "no_result" and total == 0 and not rows
                       and _tm_zero_transition(binding, rendered))
    if (type(total) is not int or total < 0
            or not isinstance(rows, list)
            or binding.get("loading") is not False
            or not isinstance(displayed_rows, list)
            or type(binding.get("parsed_count")) is not int or binding["parsed_count"] != len(displayed_rows)
            or binding.get("result_view") not in {"list", "detail"}
            or (binding.get("result_view") == "detail" and (total != 1 or binding.get("result_index") != 1))
            or not zero_transition and normalize(binding.get("result_query")) not in {query, '"' + query + '"'}
            or observation.get("observed_count") != len(rows)
            or type(observation.get("observed_count")) is not int
            or (capture.get("status") == "no_result" and (total != 0 or rows))
            or (capture.get("status") == "success" and not 0 < len(rows) <= total)):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM query/count contradiction")


def validate_tm_result_pages(capture: dict, task_dir: Path, rendered: str) -> None:
    pages = capture.get("result_pages") or []
    if not isinstance(pages, list) or len(pages) > 8 or (capture.get("status") == "success" and not pages):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM result pages required")
    rows, seen, previous_end = [], set(), 0
    total = (capture.get("query_binding") or {}).get("total_hits")
    for index, page in enumerate(pages, 1):
        if not isinstance(page, dict) or page.get("page_index") != index or not isinstance(page.get("candidates"), list):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM result page identity differs")
        binding, candidates = page.get("query_binding") or {}, page["candidates"]
        if (binding.get("query_bound") is not True or binding.get("total_hits") != total
                or binding.get("input_value") != rendered or binding.get("rendered_query") != rendered
                or binding.get("search_mode") != "Field tag and Search builder"):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM result page query differs")
        validate_tm_result_binding({"query_binding": binding, "candidates": candidates, "status": "success"}, {"observed_count": len(candidates)}, rendered)
        image = Path(str(page.get("screenshot_path") or "")).resolve()
        if not image.is_file() or not path_within(image, task_dir / "screenshots") or sha256_file(image) != page.get("screenshot_sha256"):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM result page screenshot differs")
        if len(pages) > 1:
            bounds = page.get("range") or {}
            if (type(bounds.get("start")) is not int or type(bounds.get("end")) is not int
                    or bounds.get("total") != total or bounds["start"] != previous_end + 1
                    or bounds["end"] - bounds["start"] + 1 != len(candidates)):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM result page range differs")
            previous_end = bounds["end"]
        for row in candidates:
            serial = row.get("serial_number")
            if not isinstance(serial, str) or not re.fullmatch(r"\d{8}", serial) or serial in seen:
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: duplicate or invalid TM serial")
            seen.add(serial)
            rows.append(row)
    if pages and (capture.get("query_binding") != pages[-1]["query_binding"] or rows != capture.get("candidates")):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM candidates differ from bound pages")
    coverage = capture.get("result_coverage") or {}
    if coverage.get("retrieved_hits") != len(rows) or coverage.get("total_hits") != total or coverage.get("pages_retrieved") != (len(pages) or 1):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM coverage differs from bound pages")


PPUBS_FIELD_CODES = {"owner": "ASNM", "assignee": "ASNM", "applicant": "AANM", "inventor": "INV",
                     "uspc": "CCLS", "cpc": "CPC", "ipc": "CIPC", "title": "TI"}
PPUBS_TEXT_FIELDS = {"", "structural_feature", "category", "product", "function", "translation", "synonym", "english", "design", "brand"}


def validate_ppubs_phrase(value: str) -> None:
    if not value or len(value) > 120 or len(value.split()) > 8 or re.search(r'["\r\n!?;<>]', value) or re.search(r"\b(?:PATENTED|MAKE IT EASY|YOUR FAVORITE|SATISFACTION GUARANTEED)\b", value, re.I):
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: phrase must be a short lexical phrase, not marketing text")


def compile_ppubs_boolean(value: str, revision: str | None = None) -> str:
    tokens = re.findall(r'''"[^"\r\n]+"|\(|\)|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*''', value.strip())
    if not tokens or "".join(tokens).replace(" ", "") != re.sub(r"\s", "", value) or len(tokens) > 80:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unsupported Boolean token or excessive query")
    operators = {"AND", "OR", "NOT"}
    if revision == "ppubs-boolean-v2" and any(re.fullmatch(r"(?:WITH|SAME|ADJ\d*|NEAR\d*|XOR)", token, re.I) for token in tokens):
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unquoted PPS reserved operator; supply an explicit supported Boolean expression or revise the source terms")
    for token in tokens:
        if token.startswith('"'):
            validate_ppubs_phrase(token[1:-1])
    if not any(token.upper() in operators for token in tokens) and "(" not in tokens and ")" not in tokens:
        if len(tokens) > 12:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: decompose long product text before querying")
        return " AND ".join(tokens)
    index = 0
    def atom():
        nonlocal index
        token = tokens[index] if index < len(tokens) else ""
        index += 1
        if token.upper() == "NOT":
            return "NOT " + atom()
        if token == "(":
            result = expression()
            if index >= len(tokens) or tokens[index] != ")":
                raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unbalanced Boolean group")
            index += 1
            return f"({result})"
        if not token or token == ")" or token.upper() in operators:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: missing Boolean operand")
        return token
    def expression():
        nonlocal index
        result = atom()
        while index < len(tokens) and tokens[index] != ")":
            operator = tokens[index].upper()
            index += 1
            if operator not in operators:
                raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: explicit Boolean operator required")
            result += f" {operator} " + atom()
        return result
    result = expression()
    if index != len(tokens):
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unmatched Boolean group")
    return result


def compile_ppubs_query(entry: dict, field: str) -> dict:
    value = str(entry.get("q") or entry.get("query") or "").strip()
    strategy = entry.get("strategy")
    if strategy not in {"boolean", "phrase", "record_number"}:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: explicit query strategy required")
    code = PPUBS_FIELD_CODES.get(field)
    if not code and field not in PPUBS_TEXT_FIELDS | {"record_number", "publication_number"}:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unsupported PPS field")
    if strategy == "record_number":
        record = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        record = re.sub(r"^US", "", record)
        record = re.sub(r"(?<=\d)[ABS]\d?$", "", record)
        if not re.fullmatch(r"(?:D|RE|PP)?\d{5,11}", record):
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: malformed known US record number")
        rendered = (f'"{record}".PN.' if entry.get("query_compiler_revision") == "ppubs-quoted-record-v1"
                    else f"{record}.PN.")
    elif field in {"uspc", "cpc", "ipc"}:
        pattern = r"D?\d{1,3}/\d+(?:\.\d+)?" if field == "uspc" else r"[A-HY]\d{2}[A-Z]\d+(?:/\d+)?"
        if strategy != "boolean" or not re.fullmatch(pattern, value, re.I):
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: expected one normalized classification code")
        rendered = f"{value.upper()}.{code}."
    else:
        if strategy == "phrase":
            validate_ppubs_phrase(value)
            rendered = f'"{value}"'
        else:
            rendered = compile_ppubs_boolean(value, entry.get("query_compiler_revision"))
        if code:
            rendered = f"({rendered}).{code}."
    design = entry.get("right_type") == "design" and strategy != "record_number"
    if design:
        rendered = f"({rendered}) AND S.KD."
    return {"rendered_query": rendered, "strategy": strategy,
            "semantics": "known_record" if strategy == "record_number" else "lexical_phrase" if strategy == "phrase" else "boolean_terms",
            "requested_field": field, "language_filter_applied": False,
            "field_code": "PN" if strategy == "record_number" else code,
            "right_type_filter": "S.KD." if design else None}


def compile_tm_figurative_query(entry: dict, field: str) -> dict:
    """Only evidenced design elements use DC/DE; neither is reverse-image search."""
    if entry.get("query_compiler_revision") != "tm-figurative-fields-v1" or entry.get("right_type") != "trademark_figurative":
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: figurative fields require an explicit new compiler revision")
    refs = entry.get("derived_from") or []
    refs = [refs] if isinstance(refs, str) else refs
    if not isinstance(refs, list) or not any(isinstance(ref, str) and re.match(r"^(?:product\.mark_inventory\[\d+\]|evidence:EV[-A-Za-z0-9]+)", ref) for ref in refs):
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: figurative element provenance required")
    value, strategy = str(entry.get("q") or "").strip(), entry.get("strategy")
    if field == "design_code" and strategy == "classification" and re.fullmatch(r"(?:\d{6}|\d{2}\.\d{2}\.\d{2})", value):
        code, rendered, semantics, dimension = "DC", "DC:" + value.replace(".", ""), "design_classification", "classification"
    elif field == "mark_description" and strategy in {"boolean", "phrase"}:
        if strategy == "phrase":
            validate_ppubs_phrase(value)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 '\-]*", value):
                raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unsafe design description phrase")
            rendered = 'DE:"' + value + '"'
        else:
            rendered = "DE:(" + compile_ppubs_boolean(value) + ")"
        code, semantics, dimension = "DE", "design_description", "description"
    else:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: expected one US design code or an English design description")
    return {"rendered_query": rendered, "strategy": strategy, "semantics": semantics,
            "requested_field": field, "language_filter_applied": False,
            "query_compiler_revision": "tm-figurative-fields-v1", "search_mode": "field_tag",
            "field_code": code, "search_dimension": dimension}


def planned_browser_query(provider: str, entry: dict, task: dict | None = None) -> dict:
    """Match the conservative US control mapping in cdp-cli.browserPlannedQuery."""
    value = str(entry.get("q") or entry.get("query") or "").strip()
    filters = entry.get("filters") or {}
    if not value or not isinstance(filters, dict) or set(filters) - {"field", "language"}:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: empty query or unimplemented filters")
    field = str(filters.get("field") or "")
    language = str(filters.get("language") or "").lower()
    if language and language not in {"en", "en-us", "english"}:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unvalidated US query language")
    if language in {"en", "en-us", "english"} and re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value):
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: an English USPTO query contains CJK text")
    strategy = "record_number" if entry.get("operation") == "candidate_verification" else "basic_search"
    rendered = value
    semantics = "known_record" if strategy == "record_number" else "basic_text"
    if strategy == "record_number":
        if field and field not in {"record_number", "publication_number", "serial_number"}:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: expected record-number field")
        if provider == "uspto_patent_browser":
            clean = re.sub(r"[^A-Za-z0-9]", "", value).upper()
            if recall_integrity_enabled(task or {}) and not re.fullmatch(r"(?:US)?(?:D\d{6,8}(?:S\d?)?|\d{6,11}(?:[AB]\d?)?|(?:RE|PP)\d{5,8}(?:[A-Z]\d?)?)", clean):
                raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: malformed known US record number")
            if recall_integrity_enabled(task or {}):
                return compile_ppubs_query({**entry, "strategy": "record_number"}, "record_number")
            design = re.fullmatch(r"(?:US)?D(\d{6,8})(?:S\d?)?", clean)
            utility = re.fullmatch(r"US(\d{6,11})(?:[A-Z]\d?)?", clean)
            rendered = "D" + design[1] if design else utility[1] if utility else value
    elif provider == "uspto_tmsearch_browser":
        if entry.get("query_compiler_revision") == "tm-figurative-fields-v1":
            return compile_tm_figurative_query(entry, field)
        if entry.get("right_type") != "trademark_word" or field and field not in {"brand", "ocr", "translation"}:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unsupported figurative/classification/phonetic field")
        strategy = entry.get("strategy") or ("phrase" if field else "")
        if strategy in {"exact", "phrase"}:
            rendered = '"' + value.replace('"', '') + '"'
            semantics = "lexical_phrase"
        elif strategy == "prefix":
            rendered += "*"
            semantics = "lexical_prefix"
        else:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unsupported trademark text strategy")
        revision = entry.get("query_compiler_revision")
        if revision:
            if revision != "tm-field-tags-v1" or re.search(r'["\\\r\n]', value):
                raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unknown TM compiler or unsafe literal")
            if strategy == "prefix" and not re.fullmatch(r"[A-Za-z0-9]+", value):
                raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: TM prefix requires one literal token")
            return {"rendered_query": "CM:" + rendered, "strategy": strategy, "semantics": semantics,
                    "requested_field": field, "language_filter_applied": False,
                    "query_compiler_revision": revision, "search_mode": "field_tag", "field_code": "CM"}
    elif provider == "uspto_patent_browser":
        if recall_integrity_enabled(task or {}):
            return compile_ppubs_query(entry, field)
        if field and field not in {"structural_feature", "category", "product", "function", "translation", "synonym", "english", "design"}:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: unsupported owner/classification field")
        if '"' in value:
            raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: embedded quotation marks require an explicit Patent Public Search query plan")
        rendered = f'"{value}"'
        strategy = "advanced_literal_phrase"
        semantics = "advanced_literal_phrase"
    else:
        raise ValueError("UNSUPPORTED_QUERY_SEMANTICS: no automatic provider mapping")
    return {"rendered_query": rendered, "strategy": strategy, "semantics": semantics,
            "requested_field": field, "language_filter_applied": False}


def validate_browser_execution(capture: dict, task: dict, task_dir: Path,
                               provider: str) -> dict:
    if task.get("schema_version") != "2.4-free":
        return {}
    if capture.get("operator_attestation") or capture.get("required_operator_attestation"):
        raise ValueError("MANUAL_BUSINESS_ACTION_FORBIDDEN: operator attestation cannot complete a 2.4 query")
    if provider not in {"uspto_patent_browser", "uspto_tmsearch_browser", "uspto_tsdr"}:
        raise ValueError("AUTOMATION_NOT_VALIDATED: no accepted automatic recorder for this route")
    reference = capture.get("query_execution")
    if not isinstance(reference, dict):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_REQUIRED: missing execution receipt")
    receipt_path = Path(str(reference.get("path") or "")).resolve()
    if not receipt_path.is_file() or not path_within(receipt_path, task_dir / "raw" / "browser-execution"):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_REQUIRED: receipt must exist inside raw/browser-execution")
    if sha256_file(receipt_path) != reference.get("sha256"):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: receipt hash mismatch")
    receipt = load_json(receipt_path)
    plan = load_json(task_dir / "search-plan.json")
    matches = [(source, entry) for source, entries in plan.get("queries", {}).items()
               for entry in entries if isinstance(entry, dict)
               and entry.get("query_id") == capture.get("query_id")]
    if len(matches) != 1 or matches[0][0] != provider:
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: query must resolve to one source-bound plan entry")
    entry = matches[0][1]
    execution = planned_browser_query(provider, entry, task)
    if entry.get("query_compiler_revision") == "tm-figurative-fields-v1" and (capture.get("query_semantics") != execution or capture.get("rendered_query") != execution["rendered_query"]):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: figurative query semantics differ from plan")
    expected = {"task_id": task.get("task_id"), "provider": provider,
                "query_id": entry.get("query_id"), "operation": entry.get("operation"),
                "jurisdiction": entry.get("jurisdiction"), "right_type": entry.get("right_type"),
                "query": entry.get("q") or entry.get("query") or "",
                "plan_entry_sha256": canonical_digest(entry), "mode": "automatic",
                "business_actions_by": "agent", "outcome": capture.get("status"),
                "final_url": capture.get("final_url"), "completed_at": capture.get("checked_at"),
                "query_semantics": capture.get("query_semantics"),
                "result_coverage_sha256": canonical_digest(capture.get("result_coverage") or {}),
                "media_coverage_sha256": canonical_digest(capture.get("media_coverage") or {})}
    if recall_integrity_enabled(task):
        expected["result_pages_sha256"] = canonical_digest(capture.get("result_pages") or [])
    if capture.get("document_retrieval"):
        expected["document_retrieval_sha256"] = canonical_digest(capture["document_retrieval"])
    if capture.get("rate_limit_page"):
        page_ref = capture["rate_limit_page"]
        from urllib.parse import urlsplit
        allowed_hosts = {"uspto_patent_browser": {"ppubs.uspto.gov"},
                         "uspto_tmsearch_browser": {"tmsearch.uspto.gov"},
                         "uspto_tsdr": {"tsdr.uspto.gov", "tsdrsec.uspto.gov"}}[provider]
        page_url = urlsplit(str(page_ref.get("url") or "")) if isinstance(page_ref, dict) else None
        if (not isinstance(page_ref, dict) or not re.fullmatch(r"[a-fA-F0-9]{16,64}", str(page_ref.get("target_id") or ""))
                or page_url.scheme != "https" or page_url.netloc not in allowed_hosts
                or page_ref.get("url") != capture.get("final_url")):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: original rate-limit page identity is invalid")
        expected["rate_limit_page_sha256"] = canonical_digest(page_ref)
    if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items()):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: receipt does not match plan or capture")
    validate_checked_at(str(receipt.get("completed_at") or ""))
    events = receipt.get("events")
    if not isinstance(events, list) or any(not isinstance(e, dict) or e.get("actor") != "agent" for e in events):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_REQUIRED: invalid action events")
    for event in events:
        validate_checked_at(str(event.get("at") or ""))
    published_only = (recall_integrity_enabled(task) and provider == "uspto_patent_browser"
                      and entry.get("operation") == "candidate_verification"
                      and capture.get("document_retrieval", {}).get("status") == "success")
    if capture.get("status") in {"success", "no_result"} or published_only:
        submissions = [e for e in events if e.get("action") in {"submit_query", "navigate_record"}]
        observations = [e for e in events if e.get("action") == "observe_result"]
        if not submissions or not observations:
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_REQUIRED: submission and result observation are required")
        if any(e.get("action") == "submit_query" and (not e.get("rendered_query")
               or e.get("input_value") != e.get("rendered_query")) for e in submissions):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: submitted input was not verified")
        planned_query = str(expected["query"])
        if provider == "uspto_tsdr":
            if any(e.get("action") != "navigate_record" or e.get("record_number") != planned_query
                   for e in submissions):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: record navigation differs from plan")
        else:
            rendered = execution["rendered_query"]
            if any(e.get("action") != "submit_query" or e.get("rendered_query") != rendered for e in submissions):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: submitted query differs from plan")
        if observations[-1].get("stable") is not True:
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: result state was not stable")
        if provider == "uspto_tmsearch_browser" and entry.get("query_compiler_revision") in {"tm-field-tags-v1", "tm-figurative-fields-v1"}:
            binding = capture.get("query_binding") or {}
            rendered = execution["rendered_query"]
            if entry.get("query_compiler_revision") == "tm-figurative-fields-v1":
                validate_tm_result_pages(capture, task_dir, rendered)
            validate_tm_result_binding(capture, observations[-1], rendered)
            if binding.get("binding_method") == "submitted_zero_transition_v1":
                transition = binding["zero_result_transition"]
                if (capture.get("final_url") != transition["final_url"]
                        or not any(event.get("submission_id") == transition["submission_id"]
                                   and event.get("submission_confirmed") is True
                                   and event.get("result_baseline") == transition["baseline"]
                                   for event in submissions)):
                    raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM zero result lacks this attempt's confirmed transition")
            if (binding.get("query_bound") is not True or binding.get("input_value") != rendered
                    or binding.get("rendered_query") != rendered
                    or binding.get("search_mode") != "Field tag and Search builder"
                    or observations[-1].get("query_binding") != binding
                    or any(event.get("search_mode") != "Field tag and Search builder" for event in submissions)):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: TM field mode or result binding missing")
        if events.index(submissions[0]) >= events.index(observations[-1]):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: observation precedes submission")
        screenshot = Path(str(capture.get("screenshot_path") or "")).resolve()
        if not screenshot.is_file() or not path_within(screenshot, task_dir / "screenshots"):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: result screenshot is missing")
        if observations[-1].get("screenshot_sha256") != sha256_file(screenshot):
            raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: result screenshot differs from execution")
        if published_only:
            from provider_utils import validate_text_evidence
            validate_text_evidence(capture, expected_stage="source")
            document = capture["document_retrieval"]
            identifier = re.sub(r"[^A-Za-z0-9]", "", str(entry.get("q") or "")).upper()
            if (document.get("authority_scope") != "published_document_only"
                    or document.get("identity_match") is not True
                    or document.get("record_number") != identifier
                    or capture.get("page_record_number") != identifier
                    or observations[-1].get("identity") != identifier
                    or document.get("title") != capture.get("title")
                    or not capture.get("title") or not capture.get("rendered_text")
                    or document.get("rendered_text_sha256") != canonical_digest(capture["rendered_text"])):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: published document identity or text differs")
            bindings = [event for event in events if event.get("action") == "observe_query_binding"]
            if not bindings or bindings[-1].get("query") != execution["rendered_query"] or not bindings[-1].get("result_set_id"):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: published document search history missing")
            history_shot = Path(str(bindings[-1].get("screenshot_path") or "")).resolve()
            if not history_shot.is_file() or not path_within(history_shot, task_dir / "screenshots") or sha256_file(history_shot) != bindings[-1].get("screenshot_sha256"):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: document history screenshot differs")
            images = capture.get("evidence_images") or []
            pages = document.get("document_pages") or []
            if not isinstance(pages, list) or len(pages) > 20 or len(pages) != len(images):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: published document pages differ")
            for number, page in enumerate(pages, 1):
                image = Path(str(page.get("path") or "")).resolve()
                if (page.get("record_number") != identifier or page.get("page") != number
                        or page.get("path") != images[number - 1].get("path")
                        or not image.is_file() or not path_within(image, task_dir / "screenshots")
                        or page.get("sha256") != sha256_file(image)):
                    raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: published image binding differs")
        if recall_integrity_enabled(task) and provider == "uspto_patent_browser" and entry.get("operation") != "candidate_verification":
            result_set = capture.get("result_set_id")
            if not result_set or observations[-1].get("result_set_id") != result_set or observations[-1].get("query_bound") is not True:
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: result set is not bound to the submitted query")
            bindings = [event for event in events if event.get("action") == "observe_query_binding"]
            if not bindings or bindings[-1].get("result_set_id") != result_set or bindings[-1].get("query") != execution["rendered_query"]:
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: search history does not bind the result set")
            history_shot = Path(str(bindings[-1].get("screenshot_path") or "")).resolve()
            if not history_shot.is_file() or not path_within(history_shot, task_dir / "screenshots") or sha256_file(history_shot) != bindings[-1].get("screenshot_sha256"):
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: history screenshot missing or changed")
            pages = capture.get("result_pages") or []
            if not isinstance(pages, list) or len(pages) > 8 or capture["status"] == "success" and not pages:
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: missing or excessive result pages")
            observed_records = set()
            for page_index, page in enumerate(pages, 1):
                if page.get("page_index") != page_index or page.get("result_set_id") != result_set:
                    raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: result page identity differs")
                for viewport in page.get("viewports") or []:
                    if viewport.get("result_set_id") != result_set or viewport.get("editor_value") != execution["rendered_query"]:
                        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: viewport query differs")
                    shot = Path(str(viewport.get("screenshot_path") or "")).resolve()
                    if not shot.is_file() or not path_within(shot, task_dir / "screenshots") or sha256_file(shot) != viewport.get("screenshot_sha256"):
                        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: viewport screenshot missing or changed")
                    observed_records.update(re.sub(r"[^A-Za-z0-9]", "", str(row.get("documentId") or "")).upper()
                                            for row in viewport.get("rows") or [])
            captured_records = {str(row.get("record_number") or "") for row in capture.get("candidates") or []}
            if observed_records != captured_records:
                raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: candidates differ from bound result pages")
            coverage = capture.get("result_coverage") or {}
            if coverage.get("coverage_counting_revision") is not None:
                proof = ppubs_row_coverage(pages, coverage.get("total_hits"))
                if (coverage.get("coverage_counting_revision") != "ppubs-result-rows-v1"
                        or type(coverage.get("total_hits")) is not int or coverage["total_hits"] <= 0
                        or coverage.get("row_coverage") != proof
                        or coverage.get("total_hits") != bindings[-1].get("total_hits")
                        or coverage.get("retrieved_hits") != len(captured_records)
                        or coverage.get("unretrieved_result_row_count") != max(0, proof["reported_rows"] - proof["retrieved_rows"])
                        or coverage.get("unretrieved_document_count") != (0 if proof["complete"] else None)
                        or (coverage.get("truncated") is False and not ppubs_counting_complete(coverage, capture["candidates"]))):
                    raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: PPS result-row coverage differs from ordinal evidence")
    results = capture.get("candidates") if isinstance(capture.get("candidates"), list) else {
        "record_number": capture.get("record_number") or capture.get("serial_number") or "",
        "page_record_number": capture.get("page_record_number") or capture.get("page_case_number") or "",
    }
    if receipt.get("result_sha256") != canonical_digest(results):
        raise ValueError("AUTOMATIC_QUERY_EXECUTION_MISMATCH: captured candidates differ from execution")
    return {"query_execution": reference, "query_semantics": execution,
            **({"query_binding": capture["query_binding"]} if capture.get("query_binding") else {}),
            "result_coverage": capture.get("result_coverage", {}),
            "media_coverage": capture.get("media_coverage", {})}
