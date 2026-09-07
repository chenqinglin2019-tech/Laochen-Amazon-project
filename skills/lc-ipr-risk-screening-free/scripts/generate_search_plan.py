#!/usr/bin/env python3
"""Generate a traceable official/free-only search plan from Amazon evidence."""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path
from typing import Any

from common import (
    AUTHORIZED_FREE_COMMERCIAL_PROVIDERS, COMMERCIAL_PROVIDERS, EU_COUNTRIES,
    SCHEMA_VERSION, SERPAPI_FREE_MAX_QUERIES_PER_TASK, SERPAPI_PROVIDER,
    SIGNA_FREE_MAX_QUERIES_PER_TASK, SIGNA_OPERATION, SIGNA_PROVIDER,
    SERPER_PROVIDERS,
    SERPER_PROVIDER_QUERY_CAPS,
    WIPO_PROVIDERS, assert_active_free_policy, assert_default_discovery_plan_contract,
    atomic_write_json,
    ensure_object, is_active_schema, load_json, load_skill_config, normalize_text,
    now_iso, serpapi_free_enabled, serper_free_enabled, signa_free_enabled,
)
from provider_utils import query_identity
from euipo_client import search_rsql as euipo_search_rsql


STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "amazon", "new", "cute",
    "comfortable", "office", "home", "computer", "desktop", "accessories",
}

# Conservative reusable mappings. They are candidates, never claims that a
# product belongs to a class without reviewer confirmation.
CLASS_HINTS = (
    ({"mousepad", "mouse pad", "wrist rest", "wrist support"}, {
        "ipc": ["G06F3/039"], "cpc": ["G06F3/039"], "locarno": ["14-02"], "nice": ["9", "20"],
    }),
)

FIGURATIVE_SCHEME_ALIASES = {
    "design_code": "uspto_design_code",
    "uspto_design_code": "uspto_design_code",
    "vienna": "vienna_classification",
    "vienna_class": "vienna_classification",
    "vienna_classification": "vienna_classification",
    "jpo_figurative": "jpo_figurative_classification",
    "jpo_figurative_class": "jpo_figurative_classification",
    "jpo_figurative_classification": "jpo_figurative_classification",
}

EXPLICIT_QUERY_TERM_KINDS = {
    "original_japanese", "english", "romaji", "applicant", "owner", "ipc", "cpc",
    "locarno", "nice", "similar_group", "pronunciation", "reading",
    "classification", "figurative_classification", "jpo_figurative_classification",
}
JP_TEXT_TERM_KINDS = {"original_japanese", "english", "romaji"}
JP_OWNER_TERM_KINDS = {"applicant", "owner"}
QUERY_SCHEME_KINDS = {
    "ipc": "ipc", "cpc": "cpc", "locarno": "locarno",
    "locarno_classification": "locarno", "nice": "nice",
    "nice_classification": "nice", "similar_group": "similar_group",
    "similar_group_code": "similar_group",
}


def script_hint(value: str) -> str:
    if re.search(r"[\u3040-\u30ff]", value):
        return "japanese_kana"
    if re.search(r"[\u3400-\u9fff]", value):
        return "cjk_ideograph"
    return "latin_or_numeric"


def clean_phrase(value: object, maximum_words: int = 8) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    words = re.findall(r"[^\W_]+(?:-[^\W_]+)*", normalized, flags=re.UNICODE)
    words = [word for word in words if word.casefold() not in STOPWORDS]
    return " ".join(words[:maximum_words]).strip()


def normalize_figurative_scheme(value: object) -> str:
    key = re.sub(r"[\s-]+", "_", str(value or "").strip().casefold())
    return FIGURATIVE_SCHEME_ALIASES.get(key, "")


def explicit_query_terms(task: dict[str, Any]) -> list[dict[str, str]]:
    """Validate caller-supplied terms without inventing translations or romanizations."""
    raw_terms = task.get("query_terms", [])
    if raw_terms is None:
        return []
    if not isinstance(raw_terms, list):
        raise SystemExit("task.query_terms must be an array")
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(raw_terms):
        if not isinstance(item, dict):
            raise SystemExit(f"task.query_terms[{index}] must be an object")
        value = re.sub(
            r"\s+", " ", unicodedata.normalize("NFKC", str(item.get("value") or "")),
        ).strip(" ,.;:-")
        kind = re.sub(r"[\s-]+", "_", str(item.get("kind") or "").strip().casefold())
        derived_from = str(item.get("derived_from") or "").strip()
        scheme = re.sub(r"[\s-]+", "_", str(item.get("scheme") or "").strip().casefold())
        figurative_scheme = normalize_figurative_scheme(scheme or kind)
        if kind == "classification":
            kind = QUERY_SCHEME_KINDS.get(scheme, figurative_scheme)
        if kind not in EXPLICIT_QUERY_TERM_KINDS:
            raise SystemExit(f"task.query_terms[{index}].kind is unsupported: {kind or '<empty>'}")
        if not value:
            raise SystemExit(f"task.query_terms[{index}].value is required")
        if not derived_from:
            raise SystemExit(f"task.query_terms[{index}].derived_from is required")
        if kind in {"figurative_classification", "jpo_figurative_classification"}:
            if not figurative_scheme:
                raise SystemExit(f"task.query_terms[{index}].scheme is unsupported")
            scheme = figurative_scheme
        elif scheme and QUERY_SCHEME_KINDS.get(scheme, scheme) != kind:
            raise SystemExit(f"task.query_terms[{index}] has conflicting kind/scheme")
        key = (normalize_text(value), kind, scheme, derived_from)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        term = {
            "value": value, "kind": kind, "derived_from": derived_from,
            "script": script_hint(value),
        }
        if scheme:
            term["scheme"] = scheme
        output.append(term)
    return output


def add_term(
    target: list[dict[str, str]], value: object, kind: str, source: str,
    *, scheme: str = "",
) -> None:
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip(" ,.;:-")
    if len(text) < 2:
        return
    key = normalize_text(text)
    if not key or any(
        normalize_text(item["value"]) == key
        and (not scheme or item.get("scheme", "") == scheme)
        for item in target
    ):
        return
    record = {
        "value": text,
        "kind": kind,
        "derived_from": source,
        "script": script_hint(text),
    }
    if scheme:
        record["scheme"] = scheme
    target.append(record)


def figurative_classification_values(
    terms: list[dict[str, str]], jurisdiction: str, limit: int = 3,
) -> list[tuple[str, list[str], str]]:
    """Return only explicit official classification inputs; never infer image codes."""
    jurisdiction = jurisdiction.upper()
    allowed = (
        {"uspto_design_code"} if jurisdiction == "US" else
        {"jpo_figurative_classification"} if jurisdiction == "JP" else
        {"vienna_classification"}
    )
    output: list[tuple[str, list[str], str]] = []
    seen: set[tuple[str, str]] = set()
    for item in terms:
        scheme = str(item.get("scheme") or "")
        if scheme not in allowed:
            continue
        value = str(item.get("value") or "").strip()
        if scheme == "uspto_design_code":
            valid = bool(re.fullmatch(r"(?:\d{2}\.\d{2}(?:\.\d{2})?|\d{4}(?:\d{2})?)", value))
        elif scheme == "vienna_classification":
            valid = bool(re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?", value))
        else:
            valid = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./_-]{1,31}", value)) and any(
                character.isdigit() for character in value
            )
        key = (scheme, normalize_text(value))
        if not valid or not key[1] or key in seen:
            continue
        seen.add(key)
        output.append((value, [str(item.get("derived_from") or "explicit_figurative_classification")], scheme))
        if len(output) >= limit:
            break
    return output


def useful_category(value: object) -> str:
    leaf = str(value or "").split(">")[-1].strip()
    return clean_phrase(leaf, 5)


def concise_visual(value: object) -> str:
    return clean_phrase(value, 9)


def classification_candidates(text: str) -> dict[str, list[str]]:
    result = {"ipc": [], "cpc": [], "locarno": [], "nice": []}
    lowered = unicodedata.normalize("NFKC", text).casefold()
    for needles, mapping in CLASS_HINTS:
        if any(needle in lowered for needle in needles):
            for kind, values in mapping.items():
                result[kind].extend(value for value in values if value not in result[kind])
    return result


def classification_term_records(candidates: dict[str, list[str]]) -> list[dict[str, str]]:
    """Expose every inferred class with an explicit, reviewable derivation rule."""
    return [
        {
            "value": value,
            "kind": "classification",
            "scheme": scheme,
            "derived_from": "rule:CLASS_HINTS(product.title+category+bullets+structure)",
            "script": "latin_or_numeric",
        }
        for scheme, values in candidates.items()
        for value in values
    ]


def entry(
    provider: str, operation: str, jurisdiction: str, params: dict[str, Any],
    *, required: bool, derived_from: list[str], wave: int = 1,
    right_type: str = "", requirement_ids: list[str] | None = None,
    required_for: str = "low_risk",
) -> dict[str, Any]:
    query = str(params.get("q") or params.get("query") or "")
    identity_params = {**params, "right_type": right_type}
    return {
        **params,
        "query_id": query_identity(provider, operation, jurisdiction, query, identity_params),
        "operation": operation,
        "jurisdiction": jurisdiction,
        "right_type": right_type,
        "required": required,
        "required_for": required_for,
        "requirement_ids": list(dict.fromkeys(requirement_ids or [])),
        "wave": wave,
        "derived_from": derived_from,
    }


def serper_discovery_entry(
    provider: str, operation: str, jurisdiction: str, value: str,
    provenance: list[str], right_type: str,
) -> dict[str, Any]:
    """Build a non-gating entry for an explicitly selected bounded free balance."""
    item = entry(
        provider, operation, jurisdiction, {"q": value, "num": 10},
        required=False, derived_from=provenance, wave=2,
        right_type=right_type, requirement_ids=[], required_for="discovery_only",
    )
    item.update({
        "role": "discovery_only",
        "execute_by_default": True,
        "authoritative_for_final_rating": False,
    })
    return item


def signa_discovery_entry(
    jurisdiction: str, value: str, provenance: list[str], offices: list[str],
) -> dict[str, Any]:
    """Build one bounded multi-office Signa word-mark discovery entry."""
    item = entry(
        SIGNA_PROVIDER, SIGNA_OPERATION, jurisdiction,
        {
            "q": value,
            "strategies": ["exact", "phonetic", "fuzzy", "prefix"],
            "filters": {"offices": offices},
            "limit": 25,
            "options": {"include_total": False},
        },
        required=False, derived_from=provenance, wave=2,
        right_type="trademark_word", requirement_ids=[],
        required_for="discovery_only",
    )
    item.update({
        "role": "discovery_only",
        "execute_by_default": True,
        "authoritative_for_final_rating": False,
    })
    return item


def serpapi_discovery_entry(
    jurisdiction: str, value: str, provenance: list[str], right_type: str,
    *, fallback_query_id: str = "",
) -> dict[str, Any]:
    """Build a non-gating SerpApi Free-plan Google Patents entry."""
    country = "EP" if jurisdiction == "EU" else jurisdiction
    item = entry(
        SERPAPI_PROVIDER, "search", jurisdiction,
        {"q": value, "num": 100, "country": country},
        required=False, derived_from=provenance, wave=2,
        right_type=right_type, requirement_ids=[], required_for="discovery_only",
    )
    item.update({
        "role": "discovery_only",
        "execute_by_default": True,
        "authoritative_for_final_rating": False,
    })
    if fallback_query_id:
        item.update({
            "execute_when": "serper_unavailable_or_exhausted",
            "fallback_provider": "serper_patents",
            "fallback_query_id": fallback_query_id,
        })
    return item


def unique_values(
    terms: list[dict[str, str]], kinds: set[str], limit: int,
) -> list[tuple[str, list[str]]]:
    output: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for item in terms:
        if item["kind"] not in kinds:
            continue
        value = item["value"]
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            output.append((value, [item["derived_from"]]))
        if len(output) >= limit:
            break
    return output


def requirement_ids(
    task: dict[str, Any], provider: str, operation: str, jurisdiction: str,
    right_type: str = "",
) -> list[str]:
    matches: list[str] = []
    for requirement in task.get("coverage_requirements", []):
        if not isinstance(requirement, dict):
            continue
        requirement_jurisdiction = str(requirement.get("jurisdiction") or "").upper()
        if requirement_jurisdiction != jurisdiction.upper():
            continue
        if right_type and requirement.get("right_type") != right_type:
            continue
        if any(
            isinstance(route, dict)
            and route.get("provider") == provider
            and route.get("operation") == operation
            for route in requirement.get("routes", [])
        ):
            matches.append(str(requirement.get("requirement_id") or ""))
    return [value for value in matches if value]


def append_queries(
    queries: dict[str, list[dict[str, Any]]], provider: str,
    entries: list[dict[str, Any]],
) -> None:
    bucket = queries.setdefault(provider, [])
    known = {str(item.get("query_id") or "") for item in bucket}
    for item in entries:
        if item["query_id"] not in known:
            known.add(item["query_id"])
            bucket.append(item)


def patent_cql(value: str, jurisdiction: str, right_type: str = "patent") -> str:
    publication_country = "EP" if jurisdiction == "EU" else jurisdiction
    escaped = value.replace('"', " ")
    publications = f"pn={publication_country}*"
    if right_type == "patent" and publication_country != "WO":
        publications = f"({publications} or pn=WO*)"
    return f'{publications} and (ta="{escaped}")'


def merge_sources(target: list[str], values: list[str]) -> None:
    for value in values:
        source = str(value or "").strip()
        if source and source not in target:
            target.append(source)


def jp_epo_facets(
    supplied_terms: list[dict[str, str]], product_terms: list[tuple[str, list[str]]],
    brand_terms: list[tuple[str, list[str]]], value_limit: int = 6,
) -> list[tuple[str, list[str]]]:
    """Build at most three OR facets so all sourced JP variants fit the OPS cap."""
    groups: tuple[tuple[set[str], str], ...] = (
        ({"ipc", "cpc"}, "classification"),
        (JP_TEXT_TERM_KINDS, "ta"),
        (JP_OWNER_TERM_KINDS, "pa"),
    )
    output: list[tuple[str, list[str]]] = []
    for kinds, field in groups:
        values: list[tuple[str, list[str], str]] = []
        seen: set[tuple[str, str]] = set()
        for item in supplied_terms:
            kind = str(item.get("kind") or "")
            if kind not in kinds:
                continue
            actual_field = kind if field == "classification" else field
            key = (actual_field, normalize_text(item["value"]))
            if not key[1] or key in seen:
                for index, (value, sources, existing_field) in enumerate(values):
                    if (existing_field, normalize_text(value)) == key:
                        merge_sources(sources, [item["derived_from"]])
                        values[index] = (value, sources, existing_field)
                        break
                continue
            seen.add(key)
            values.append((item["value"], [item["derived_from"]], actual_field))
            if len(values) >= value_limit:
                break
        if not values and field == "ta":
            values = [(value, list(sources), "ta") for value, sources in product_terms[:value_limit]]
        elif not values and field == "pa":
            values = [(value, list(sources), "pa") for value, sources in brand_terms[:value_limit]]
        if not values:
            continue
        clauses = []
        provenance: list[str] = []
        for value, sources, actual_field in values:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            clauses.append(f'{actual_field}="{escaped}"')
            merge_sources(provenance, sources)
        output.append((" or ".join(clauses), provenance))
    return output


def jp_jplatpat_requests(
    supplied_terms: list[dict[str, str]], right_type: str,
) -> list[tuple[str, str, str, list[str]]]:
    """Return value/query-mode/scheme/provenance tuples for one exact J-PlatPat lane."""
    mappings = {
        "patent": {
            **{kind: ("title_abstract", "") for kind in JP_TEXT_TERM_KINDS},
            **{kind: ("applicant", "") for kind in JP_OWNER_TERM_KINDS},
            "ipc": ("classification", "ipc"),
        },
        "utility_model": {
            **{kind: ("title_abstract", "") for kind in JP_TEXT_TERM_KINDS},
            **{kind: ("applicant", "") for kind in JP_OWNER_TERM_KINDS},
            "ipc": ("classification", "ipc"),
        },
        "design": {
            **{kind: ("article_name", "") for kind in JP_TEXT_TERM_KINDS},
            **{kind: ("applicant", "") for kind in JP_OWNER_TERM_KINDS},
            "locarno": ("classification", "locarno_classification"),
        },
        "trademark_word": {
            **{kind: ("mark_text", "") for kind in JP_TEXT_TERM_KINDS},
            **{kind: ("applicant", "") for kind in JP_OWNER_TERM_KINDS},
            "nice": ("classification", "nice_classification"),
            "similar_group": ("similar_group", ""),
            "pronunciation": ("pronunciation", ""),
            "reading": ("pronunciation", ""),
        },
        "trademark_figurative": {
            "figurative_classification": ("figurative_classification", "jpo_figurative_classification"),
            "jpo_figurative_classification": ("figurative_classification", "jpo_figurative_classification"),
        },
    }
    output: list[tuple[str, str, str, list[str]]] = []
    positions: dict[tuple[str, str, str], int] = {}
    for item in supplied_terms:
        mapping = mappings[right_type].get(str(item.get("kind") or ""))
        if not mapping:
            continue
        query_mode, default_scheme = mapping
        scheme = default_scheme or str(item.get("scheme") or "")
        key = (normalize_text(item["value"]), query_mode, scheme)
        if key in positions:
            index = positions[key]
            value, stored_mode, stored_scheme, sources = output[index]
            merge_sources(sources, [item["derived_from"]])
            output[index] = (value, stored_mode, stored_scheme, sources)
            continue
        positions[key] = len(output)
        output.append((item["value"], query_mode, scheme, [item["derived_from"]]))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build official/free-only search-plan.json.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--expand", action="store_true", help="Append candidate-derived 2.4 searches without rewriting existing query hashes")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if task.get("schema_version") == "2.4-free":
        from workflow_v24 import generate_plan
        generate_plan(task_dir, expand=args.expand)
        print(task_dir / "search-plan.json")
        return
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    if not is_active_schema(task):
        raise SystemExit("Legacy 2.1/2.2 tasks are evidence-read-only; search plans cannot be regenerated")
    assert_active_free_policy(task)
    if task.get("state") not in {"collecting", "ready_for_assessment", "incomplete"}:
        raise SystemExit("Evidence preflight must pass before generating a search plan")
    if not isinstance(task.get("coverage_requirements"), list) or not task["coverage_requirements"]:
        raise SystemExit("2.3 task is missing coverage_requirements")
    browser = evidence.get("collections", {}).get("browser", [])
    if not browser:
        raise SystemExit("Accepted browser evidence is missing")

    product, capture = task["product"], browser[0]
    terms: list[dict[str, str]] = []
    add_term(terms, useful_category(product.get("category")), "category", "product.category.leaf")
    add_term(terms, product.get("brand"), "brand", "product.brand")
    add_term(terms, product.get("manufacturer"), "owner", "product.manufacturer")
    add_term(terms, clean_phrase(product.get("title"), 7), "product", "product.title")
    for index, value in enumerate(product.get("bullets", [])):
        add_term(terms, clean_phrase(value, 7), "function", f"product.bullets[{index}]")
    for key, value in product.get("specifications", {}).items():
        add_term(terms, clean_phrase(f"{key} {value}", 6), "specification", f"product.specifications.{key}")
    for index, value in enumerate(product.get("structure", [])):
        add_term(terms, clean_phrase(value, 8), "function", f"product.structure[{index}]")
    for index, value in enumerate(capture.get("visual_features", [])):
        add_term(terms, concise_visual(value), "design", f"browser.visual_features[{index}]")
    for index, value in enumerate(capture.get("ocr_text", [])):
        add_term(terms, clean_phrase(value, 6), "ocr", f"browser.ocr_text[{index}]")
    # Reviewer-supplied terms remain separate so provider routing can retain
    # kind, classification scheme and the exact supplied provenance.
    supplied_terms = explicit_query_terms(task)
    terms.extend(supplied_terms)

    config = load_skill_config()
    limits = config.get("limits", {})
    jurisdictions = [str(value).upper() for value in task.get("target_jurisdictions", [])]
    product_terms = unique_values(terms, {"category", "product", "function", "specification"}, 4)
    design_terms = unique_values(terms, {"design"}, 3)
    brand_terms = unique_values(terms, {"brand", "owner", "ocr"}, 3)
    us_figurative_terms = figurative_classification_values(terms, "US")
    eu_figurative_terms = figurative_classification_values(terms, "EU")
    jp_figurative_terms = figurative_classification_values(terms, "JP")
    if not product_terms:
        raise SystemExit("Search planning requires at least one concise product or functional term")

    queries: dict[str, list[dict[str, Any]]] = {}
    epo_limit = int(limits.get("epo_search_queries_per_task", 6))
    epo_targets: list[tuple[str, str]] = []
    for requirement in task["coverage_requirements"]:
        for route in requirement.get("routes", []):
            if route.get("provider") == "epo_ops" and route.get("operation") == "search":
                jurisdiction = str(requirement.get("jurisdiction") or "").upper()
                right_type = str(requirement.get("right_type") or "patent")
                target = (jurisdiction, right_type)
                if jurisdiction and target not in epo_targets:
                    epo_targets.append(target)
    epo_entries: list[dict[str, Any]] = []
    jp_facets = jp_epo_facets(supplied_terms, product_terms, brand_terms)
    for index in range(3):
        for jurisdiction, right_type in epo_targets:
            if len(epo_entries) >= epo_limit:
                break
            if jurisdiction == "JP" and right_type in {"patent", "utility_model"}:
                if index >= len(jp_facets):
                    continue
                clause, provenance = jp_facets[index]
                publications = "pn=JP*"
                if right_type == "patent":
                    publications = f"({publications} or pn=WO*)"
                q = f"{publications} and ({clause})"
                epo_entries.append(entry(
                    "epo_ops", "search", "JP", {"q": q, "range": "1-25"},
                    required=True, derived_from=provenance, wave=1,
                    right_type=right_type,
                    requirement_ids=requirement_ids(task, "epo_ops", "search", "JP", right_type),
                ))
                continue
            values = (
                (design_terms or product_terms) if right_type == "design" else
                (product_terms + design_terms + brand_terms)
            )[:3]
            if index >= len(values):
                continue
            value, provenance = values[index]
            q = patent_cql(value, jurisdiction, right_type)
            epo_entries.append(entry(
                "epo_ops", "search", jurisdiction, {"q": q, "range": "1-25"},
                required=True, derived_from=provenance, wave=1 if index < 2 else 2,
                right_type=right_type,
                requirement_ids=requirement_ids(task, "epo_ops", "search", jurisdiction, right_type),
            ))
    append_queries(queries, "epo_ops", epo_entries)

    if "US" in jurisdictions:
        patent_browser_limit = int(limits.get("uspto_patent_browser_queries_per_task", 3))
        patent_browser_entries: list[dict[str, Any]] = []
        patent_browser_groups = (
            ("patent", product_terms),
            ("design", design_terms or product_terms),
        )
        for index in range(max((len(values) for _, values in patent_browser_groups), default=0)):
            for right_type, values in patent_browser_groups:
                if len(patent_browser_entries) >= patent_browser_limit or index >= len(values):
                    continue
                value, provenance = values[index]
                patent_browser_entries.append(entry(
                    "uspto_patent_browser", "patent_recall", "US",
                    {"q": value, "mode": "basic_search", "search_focus": right_type},
                    required=True, derived_from=provenance, right_type=right_type,
                    requirement_ids=requirement_ids(
                        task, "uspto_patent_browser", "patent_recall", "US", right_type,
                    ),
                ))
        append_queries(queries, "uspto_patent_browser", patent_browser_entries)
        append_queries(queries, "uspto_tmsearch_browser", [
            entry(
                "uspto_tmsearch_browser", "trademark_recall", "US",
                {"q": value, "strategy": strategy}, required=True,
                derived_from=provenance, right_type="trademark_word",
                requirement_ids=requirement_ids(
                    task, "uspto_tmsearch_browser", "trademark_recall", "US", "trademark_word",
                ),
            )
            for value, provenance in brand_terms
            for strategy in ("exact", "phrase", "prefix")
        ])
        append_queries(queries, "uspto_tmsearch_browser", [
            entry(
                "uspto_tmsearch_browser", "trademark_recall", "US",
                {
                    "q": value, "strategy": "design_code",
                    "classification_scheme": scheme,
                },
                required=True, derived_from=provenance, right_type="trademark_figurative",
                requirement_ids=requirement_ids(
                    task, "uspto_tmsearch_browser", "trademark_recall", "US",
                    "trademark_figurative",
                ),
            )
            for value, provenance, scheme in us_figurative_terms
        ])

    european_targets = {*EU_COUNTRIES, "GB"}
    eu_layer_target = "EU" in jurisdictions or any(value in EU_COUNTRIES for value in jurisdictions)
    european_scope = eu_layer_target or "GB" in jurisdictions
    if european_scope:
        if eu_layer_target:
            append_queries(queries, "euipo_trademark", [
                entry(
                    "euipo_trademark", "search", "EU", {
                        "q": value,
                        "query": euipo_search_rsql("trademark", value, "trademark_word"),
                        "page": 0,
                        "size": 25,
                    },
                    required=True, derived_from=provenance, right_type="trademark_word",
                    requirement_ids=requirement_ids(
                        task, "euipo_trademark", "search", "EU", "trademark_word",
                    ),
                )
                for value, provenance in brand_terms
            ])
            # Trademark Search 1.1.0 has no Vienna-class selector. Bind the
            # classification query to EUIPO's visible official eSearch instead
            # of pretending a broad API query completed figurative recall.
            append_queries(queries, "euipo_esearch_browser", [
                entry(
                    "euipo_esearch_browser", "trademark_recall", "EU", {
                        "q": value,
                        "mode": "user_assisted",
                        "query_mode": "vienna_classification",
                        "classification_scheme": scheme,
                    },
                    required=True,
                    derived_from=[*provenance, f"classification_scheme:{scheme}"],
                    right_type="trademark_figurative",
                    requirement_ids=requirement_ids(
                        task, "euipo_esearch_browser", "trademark_recall", "EU", "trademark_figurative",
                    ),
                )
                for value, provenance, scheme in eu_figurative_terms
            ])
            append_queries(queries, "euipo_design", [
                entry(
                    "euipo_design", "search", "EU", {
                        "q": value,
                        "query": euipo_search_rsql("design", value, "design"),
                        "page": 0,
                        "size": 25,
                    },
                    required=True, derived_from=provenance, right_type="design",
                    requirement_ids=requirement_ids(
                        task, "euipo_design", "search", "EU", "design",
                    ),
                )
                for value, provenance in (design_terms or product_terms)[:3]
            ])
        for jurisdiction in [value for value in jurisdictions if value in european_targets]:
            if jurisdiction == "FR":
                for right_type, dataset, values in (
                    ("patent", "patent", product_terms[:3]),
                    ("utility_model", "patent", product_terms[:3]),
                    ("design", "design", (design_terms or product_terms)[:3]),
                    ("trademark_word", "trademark", brand_terms[:3]),
                ):
                    append_queries(queries, "inpi_api", [
                        entry(
                            "inpi_api", "search", "FR", {"q": value, "dataset": dataset},
                            required=True, derived_from=provenance, right_type=right_type,
                            requirement_ids=requirement_ids(task, "inpi_api", "search", "FR", right_type),
                        )
                        for value, provenance in values
                    ])
                append_queries(queries, "inpi_api", [
                    entry(
                        "inpi_api", "search", "FR", {"q": value, "dataset": "trademark"},
                        required=True,
                        derived_from=[*provenance, f"classification_scheme:{scheme}"],
                        right_type="trademark_figurative",
                        requirement_ids=requirement_ids(
                            task, "inpi_api", "search", "FR", "trademark_figurative",
                        ),
                    )
                    for value, provenance, scheme in eu_figurative_terms
                ])
            if jurisdiction == "SE":
                for right_type, dataset, values in (
                    ("patent", "patent", product_terms[:3]),
                    ("design", "design", (design_terms or product_terms)[:3]),
                    ("trademark_word", "trademark", brand_terms[:3]),
                ):
                    append_queries(queries, "prv_open_data", [
                        entry(
                            "prv_open_data", "search", "SE",
                            {"q": value, "dataset": dataset, "mode": "local_index"},
                            required=True, derived_from=provenance, right_type=right_type,
                            requirement_ids=requirement_ids(task, "prv_open_data", "search", "SE", right_type),
                        )
                        for value, provenance in values
                    ])
                append_queries(queries, "prv_open_data", [
                    entry(
                        "prv_open_data", "search", "SE",
                        {
                            "q": value, "dataset": "trademark", "mode": "local_index",
                            "classification_scheme": scheme,
                        },
                        required=True, derived_from=provenance,
                        right_type="trademark_figurative",
                        requirement_ids=requirement_ids(
                            task, "prv_open_data", "search", "SE", "trademark_figurative",
                        ),
                    )
                    for value, provenance, scheme in eu_figurative_terms
                ])
            browser_groups = (
                ("tmview_browser", "trademark_recall", "trademark_word", brand_terms[:3]),
                ("designview_browser", "design_recall", "design", (design_terms or product_terms)[:3]),
                ("official_registry_browser", "patent_recall", "patent", product_terms[: int(limits.get("national_registry_queries_per_right_type", 3))]),
                ("official_registry_browser", "utility_model_recall", "utility_model", product_terms[: int(limits.get("national_registry_queries_per_right_type", 3))]),
                ("official_registry_browser", "design_recall", "design", (design_terms or product_terms)[:3]),
                ("official_registry_browser", "trademark_recall", "trademark_word", brand_terms[:3]),
            )
            for provider, operation, right_type, values in browser_groups:
                linked = requirement_ids(task, provider, operation, jurisdiction, right_type)
                if not linked:
                    continue
                append_queries(queries, provider, [
                    entry(
                        provider, operation, jurisdiction, {"q": value, "mode": "user_assisted"},
                        required=True, derived_from=provenance, right_type=right_type,
                        requirement_ids=linked,
                    )
                    for value, provenance in values
                ])
            for provider in ("tmview_browser", "official_registry_browser"):
                linked = requirement_ids(
                    task, provider, "trademark_recall", jurisdiction, "trademark_figurative",
                )
                if not linked:
                    continue
                append_queries(queries, provider, [
                    entry(
                        provider, "trademark_recall", jurisdiction,
                        {
                            "q": value, "mode": "user_assisted",
                            "query_mode": "figurative_classification",
                            "classification_scheme": scheme,
                        },
                        required=True, derived_from=provenance,
                        right_type="trademark_figurative", requirement_ids=linked,
                    )
                    for value, provenance, scheme in eu_figurative_terms
                ])

    if "JP" in jurisdictions:
        jp_limit = int(limits.get("jplatpat_queries_per_right_type", 12))
        jp_groups = (
            ("patent", "patent_recall", product_terms, "title_abstract"),
            ("utility_model", "utility_model_recall", product_terms, "title_abstract"),
            ("design", "design_recall", design_terms or product_terms, "article_name"),
            ("trademark_word", "trademark_recall", brand_terms, "mark_text"),
        )
        for right_type, operation, fallback_values, fallback_mode in jp_groups:
            linked = requirement_ids(task, "jplatpat_browser", operation, "JP", right_type)
            if not linked:
                continue
            planned: list[dict[str, Any]] = []
            for value, query_mode, scheme, provenance in jp_jplatpat_requests(
                supplied_terms, right_type,
            ):
                params = {"q": value, "mode": "user_assisted", "query_mode": query_mode}
                if scheme:
                    params["classification_scheme"] = scheme
                planned.append(entry(
                    "jplatpat_browser", operation, "JP", params,
                    required=True, derived_from=provenance, right_type=right_type,
                    requirement_ids=linked,
                ))
            for value, provenance in fallback_values:
                if len(planned) >= jp_limit:
                    break
                planned.append(entry(
                    "jplatpat_browser", operation, "JP",
                    {"q": value, "mode": "user_assisted", "query_mode": fallback_mode},
                    required=True, derived_from=provenance, right_type=right_type,
                    requirement_ids=linked,
                ))
            append_queries(queries, "jplatpat_browser", planned[:jp_limit])
        figurative_linked = requirement_ids(
            task, "jplatpat_browser", "trademark_recall", "JP", "trademark_figurative",
        )
        if figurative_linked:
            append_queries(queries, "jplatpat_browser", [
                entry(
                    "jplatpat_browser", "trademark_recall", "JP",
                    {
                        "q": value, "mode": "user_assisted",
                        "query_mode": "figurative_classification",
                        "classification_scheme": scheme,
                    },
                    required=True, derived_from=provenance,
                    right_type="trademark_figurative",
                    requirement_ids=figurative_linked,
                )
                for value, provenance, scheme in jp_figurative_terms[:jp_limit]
            ])

    public_supported = {"US", "JP", "GB", "BE", "DE", "ES", "FR", "IT", "NL", "PL", "SE"}
    substantive_targets = [value for value in jurisdictions if value in public_supported]
    if not substantive_targets and jurisdictions == ["EU"]:
        substantive_targets = ["EU"]
    for jurisdiction in substantive_targets:
        public_routes: list[tuple[str, str, list[tuple[str, list[str]]], str]] = [
            ("copyright", "copyright_recall", design_terms or product_terms[:1], ""),
            ("enforcement", "enforcement_recall", brand_terms or product_terms[:1], ""),
        ]
        if jurisdiction == "US":
            public_routes = [
                ("copyright", "copyright_recall", design_terms or product_terms[:1], "copyright_records"),
                ("enforcement", "enforcement_recall", brand_terms or product_terms[:1], "ttabvue"),
                ("enforcement", "enforcement_recall", brand_terms or product_terms[:1], "ptab"),
                ("enforcement", "enforcement_recall", brand_terms or product_terms[:1], "copyright_claims_board"),
            ]
        for right_type, operation, values, source_key in public_routes:
            append_queries(queries, "public_web_browser", [
                entry(
                    "public_web_browser", operation, jurisdiction,
                    {
                        "q": value,
                        "mode": "manual_capture",
                        **({"source_key": source_key} if source_key else {}),
                    },
                    required=True,
                    derived_from=[
                        *provenance,
                        *([f"official_source:{source_key}"] if source_key else []),
                    ],
                    right_type=right_type,
                    requirement_ids=requirement_ids(task, "public_web_browser", operation, jurisdiction, right_type),
                )
                for value, provenance in values[:1]
            ])

    serper_enabled = serper_free_enabled(task)
    if serper_enabled:
        patents_limit = int(limits.get("serper_patents_queries_per_task", 0))
        search_limit = int(limits.get("serper_search_queries_per_task", 0))
        images_limit = int(limits.get("serper_images_queries_per_task", 0))
        maximum = int(limits.get("serper_free_max_queries_per_task", 0))
        task_maximum = int(task["serper_free_enhancement"]["max_queries_per_task"])
        if (
            (patents_limit, search_limit, images_limit) != (
                SERPER_PROVIDER_QUERY_CAPS["serper_patents"],
                SERPER_PROVIDER_QUERY_CAPS["serper_web"],
                SERPER_PROVIDER_QUERY_CAPS["serper_images"],
            )
            or maximum != task_maximum
            or patents_limit + search_limit + images_limit > maximum
        ):
            raise SystemExit("SERPER_FREE_POLICY_INVALID: expected shared 10-query cap (4+3+3)")
        primary_jurisdiction = next(
            (value for value in jurisdictions if value != "EU"),
            jurisdictions[0] if jurisdictions else "",
        )
        patent_seeds = [
            *((value, source, "patent") for value, source in product_terms[:2]),
            *((value, source, "design") for value, source in design_terms[:1]),
            *((value, source, "patent") for value, source in brand_terms[:1]),
        ][:patents_limit]
        append_queries(queries, "serper_patents", [
            serper_discovery_entry(
                "serper_patents", "patents", primary_jurisdiction,
                value, source, right_type,
            )
            for value, source, right_type in patent_seeds
        ])
        append_queries(queries, "serper_web", [
            serper_discovery_entry(
                "serper_web", "search", primary_jurisdiction,
                f"{value} patent infringement lawsuit", source, "enforcement",
            )
            for value, source in (brand_terms + product_terms)[:search_limit]
        ])
        append_queries(queries, "serper_images", [
            serper_discovery_entry(
                "serper_images", "images", primary_jurisdiction,
                value, source, "copyright",
            )
            for value, source in (design_terms + brand_terms + product_terms)[:images_limit]
        ])

    signa_enabled = signa_free_enabled(task)
    if signa_enabled:
        signa_limit = int(limits.get("signa_free_max_queries_per_task", 0))
        result_limit = int(limits.get("signa_results_per_query", 0))
        task_limit = int(task["signa_free_enhancement"]["max_queries_per_task"])
        if (
            signa_limit != SIGNA_FREE_MAX_QUERIES_PER_TASK
            or task_limit != SIGNA_FREE_MAX_QUERIES_PER_TASK
            or result_limit != 25
        ):
            raise SystemExit("SIGNA_FREE_POLICY_INVALID: expected 3 searches with 25 results each")
        signa_config = config.get("providers", {}).get("signa", {})
        office_map = signa_config.get("office_map", {})
        excluded = {str(value).upper() for value in signa_config.get("excluded_offices", [])}
        mapped: list[tuple[str, str]] = []
        for target in jurisdictions:
            office = str(office_map.get(target, "")).upper()
            pair = (target, office)
            if office and office not in excluded and pair not in mapped:
                mapped.append(pair)
        offices = list(dict.fromkeys(office for _, office in mapped))
        if offices:
            scope = mapped[0][0] if len(offices) == 1 else "MULTI"
            append_queries(queries, SIGNA_PROVIDER, [
                signa_discovery_entry(scope, value, provenance, offices)
                for value, provenance in brand_terms[:signa_limit]
            ])

    serpapi_enabled = serpapi_free_enabled(task)
    if serpapi_enabled:
        serpapi_limit = int(limits.get("serpapi_google_patents_queries_per_task", 0))
        task_limit = int(task["serpapi_free_enhancement"]["max_queries_per_task"])
        if (
            serpapi_limit != SERPAPI_FREE_MAX_QUERIES_PER_TASK
            or task_limit != SERPAPI_FREE_MAX_QUERIES_PER_TASK
        ):
            raise SystemExit("SERPAPI_FREE_POLICY_INVALID: expected a 3-query task cap")
        primary_jurisdiction = next(
            (value for value in jurisdictions if value != "EU"),
            jurisdictions[0] if jurisdictions else "",
        )
        seeds = [
            *((value, source, "patent") for value, source in product_terms[:2]),
            *((value, source, "design") for value, source in (design_terms or product_terms)[:1]),
        ][:serpapi_limit]
        serper_by_key = {
            (normalize_text(str(item.get("q") or "")), str(item.get("right_type") or "")):
            str(item.get("query_id") or "")
            for item in queries.get("serper_patents", [])
            if isinstance(item, dict)
        }
        append_queries(queries, SERPAPI_PROVIDER, [
            serpapi_discovery_entry(
                primary_jurisdiction, value, source, right_type,
                fallback_query_id=serper_by_key.get((normalize_text(value), right_type), ""),
            )
            for value, source, right_type in seeds
        ])

    forbidden = set(queries) & (
        WIPO_PROVIDERS | (COMMERCIAL_PROVIDERS - AUTHORIZED_FREE_COMMERCIAL_PROVIDERS)
    )
    if not serper_enabled:
        forbidden |= set(queries) & SERPER_PROVIDERS
    if not serpapi_enabled:
        forbidden |= set(queries) & {SERPAPI_PROVIDER}
    if not signa_enabled:
        forbidden |= set(queries) & {SIGNA_PROVIDER}
    if forbidden:
        raise SystemExit("Free-only search plan contains forbidden providers: " + ", ".join(sorted(forbidden)))
    product_text = " ".join(str(value) for value in [
        product.get("title"), product.get("category"), *product.get("bullets", []),
        *product.get("structure", []),
    ])
    inferred_classes = classification_candidates(product_text)
    for kind in ("ipc", "cpc", "locarno", "nice", "similar_group", "jpo_figurative_classification"):
        values = inferred_classes.setdefault(kind, [])
        for item in supplied_terms:
            item_kind = str(item.get("kind") or "")
            if item_kind == "figurative_classification" and item.get("scheme") == kind:
                item_kind = kind
            if item_kind == kind and item["value"] not in values:
                values.append(item["value"])
    plan: dict[str, Any] = {
        "schema_version": task["schema_version"],
        "task_id": task["task_id"],
        "created_at": now_iso(),
        "terms": [*terms, *classification_term_records(inferred_classes)],
        "classification_candidates": inferred_classes,
        "queries": {provider: entries for provider, entries in queries.items() if entries},
        "free_policy": task.get("free_policy"),
        "free_policy_revision": task.get("free_policy_revision", ""),
        "serper_free_enhancement": task.get("serper_free_enhancement"),
        "signa_free_enhancement": task.get("signa_free_enhancement"),
        "serpapi_free_enhancement": task.get("serpapi_free_enhancement"),
        "execution_policy": {
            "waves": [
                {"wave": 1, "rule": "execute high-precision official/free queries"},
                {"wave": 2, "rule": "execute selected bounded optional discovery and lower-priority official queries"},
            ],
            "max_api_concurrency": int(config.get("performance", {}).get("max_api_concurrency", 3)),
            "browser_execution": "user_triggered_visible_sequential",
            "commercial_providers_enabled": serper_enabled or signa_enabled or serpapi_enabled,
            "commercial_freemium_allowlist": [
                name for name, enabled in (
                    ("serper", serper_enabled), ("signa", signa_enabled),
                    ("serpapi", serpapi_enabled),
                ) if enabled
            ],
            "paid_execution_enabled": False,
        },
    }
    try:
        assert_default_discovery_plan_contract(task, plan)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    atomic_write_json(task_dir / "search-plan.json", plan)
    print(task_dir / "search-plan.json")


if __name__ == "__main__":
    main()
