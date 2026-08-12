#!/usr/bin/env python3
"""Generate concise, traceable and resumable provider queries from Amazon evidence."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import EU_COUNTRIES, atomic_write_json, ensure_object, load_json, load_skill_config, normalize_text, now_iso
from provider_utils import query_identity


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


def clean_phrase(value: object, maximum_words: int = 8) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", str(value or ""))
    words = [word for word in words if word.casefold() not in STOPWORDS]
    return " ".join(words[:maximum_words]).strip()


def add_term(target: list[dict[str, str]], value: object, kind: str, source: str) -> None:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:-")
    if len(text) < 2:
        return
    key = normalize_text(text)
    if not key or key in {normalize_text(item["value"]) for item in target}:
        return
    target.append({"value": text, "kind": kind, "derived_from": source})


def useful_category(value: object) -> str:
    # Amazon breadcrumbs are poor patent queries; retain only the leaf and its
    # immediately useful product words.
    leaf = str(value or "").split(">")[-1].strip()
    return clean_phrase(leaf, 5)


def concise_visual(value: object) -> str:
    text = str(value or "")
    tokens = clean_phrase(text, 9)
    return tokens


def classification_candidates(text: str) -> dict[str, list[str]]:
    result = {"ipc": [], "cpc": [], "locarno": [], "nice": []}
    lowered = text.casefold()
    for needles, mapping in CLASS_HINTS:
        if any(needle in lowered for needle in needles):
            for kind, values in mapping.items():
                result[kind].extend(value for value in values if value not in result[kind])
    return result


def entry(
    provider: str, operation: str, jurisdiction: str, params: dict[str, Any],
    *, required: bool, derived_from: list[str], wave: int = 1,
) -> dict[str, Any]:
    query = str(params.get("q") or params.get("query") or "")
    return {
        **params,
        "query_id": query_identity(provider, operation, jurisdiction, query, params),
        "operation": operation,
        "jurisdiction": jurisdiction,
        "required": required,
        "wave": wave,
        "derived_from": derived_from,
    }


def unique_values(terms: list[dict[str, str]], kinds: set[str], limit: int) -> list[tuple[str, list[str]]]:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build search-plan.json from accepted browser evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    if task.get("state") not in {"collecting", "ready_for_assessment", "incomplete"}:
        raise SystemExit("Evidence preflight must pass before generating a search plan")
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

    config = load_skill_config()
    limits = config.get("limits", {})
    jurisdictions = [str(value).upper() for value in task.get("target_jurisdictions", [])]
    patent_jurisdictions = [value for value in jurisdictions if value != "EU"] or jurisdictions
    required_sources = set(task.get("required_sources", []))
    optional_sources = set(task.get("optional_sources", []))

    product_terms = unique_values(terms, {"category", "product", "function"}, 3)
    design_terms = unique_values(terms, {"design"}, 2)
    brand_terms = unique_values(terms, {"brand", "owner", "ocr"}, 3)
    if not product_terms:
        raise SystemExit("Search planning requires at least one concise product or functional term")

    queries: dict[str, list[dict[str, Any]]] = {}
    serpapi_limit = int(limits.get("serpapi_google_patents_queries_per_task", 6))
    serpapi_entries: list[dict[str, Any]] = []
    for jurisdiction in patent_jurisdictions:
        grant_terms = product_terms[:1]
        design_source = design_terms[:1] or product_terms[:1]
        application_terms = product_terms[:1]
        planned = [
            (*grant_terms[0], "GRANT", "PATENT", 1),
            (*application_terms[0], "APPLICATION", "PATENT", 1),
            (*design_source[0], "GRANT", "DESIGN", 1),
        ]
        if brand_terms:
            planned.append((*brand_terms[0], "", "PATENT", 2))
        for value, provenance, status, kind, wave in planned:
            if len(serpapi_entries) >= serpapi_limit:
                break
            params = {"q": value, "country": jurisdiction, "status": status, "type": kind}
            serpapi_entries.append(entry(
                "serpapi_google_patents", "search", jurisdiction, params,
                required=wave == 1, derived_from=provenance, wave=wave,
            ))
    queries["serpapi_google_patents"] = serpapi_entries

    serper_values = [*product_terms, *design_terms, *brand_terms]
    serper_values = serper_values[: int(limits.get("serper_patents_queries_per_task", 8))]
    primary_jurisdiction = patent_jurisdictions[0] if patent_jurisdictions else ""
    queries["serper_patents"] = [
        entry("serper_patents", "patents", primary_jurisdiction, {"q": value, "num": 10}, required=index < 3, derived_from=source, wave=1 if index < 3 else 2)
        for index, (value, source) in enumerate(serper_values)
    ]
    enforcement_terms = brand_terms or product_terms[:1]
    queries["serper_web"] = [
        entry("serper_web", "search", primary_jurisdiction, {"q": f"{value} patent lawsuit infringement", "num": 10}, required=True, derived_from=source)
        for value, source in enforcement_terms[: int(limits.get("serper_web_queries_per_task", 8))]
    ]
    queries["serper_images"] = [
        entry("serper_images", "images", primary_jurisdiction, {"q": value, "num": 10}, required=True, derived_from=source)
        for value, source in (design_terms or brand_terms or product_terms)[: int(limits.get("serper_images_queries_per_task", 4))]
    ]

    if "epo_ops" in required_sources | optional_sources:
        required = "epo_ops" in required_sources
        us_low_risk_gate = "US" in jurisdictions and "epo_ops" in set(task.get("low_risk_gate_sources", []))
        epo_values = (product_terms + design_terms + brand_terms)[:3 if us_low_risk_gate else 4]
        queries["epo_ops"] = [
            entry(
                "epo_ops", "search", primary_jurisdiction,
                {"q": value, "range": "1-25"},
                required=us_low_risk_gate or (required and index < 2),
                derived_from=source,
                wave=1 if us_low_risk_gate or index < 2 else 2,
            )
            for index, (value, source) in enumerate(epo_values)
        ]

    if "US" in jurisdictions:
        browser_values = (product_terms[:1] + design_terms[:1] + brand_terms[:1])[:3]
        for provider, mode, limit_key in (
            ("wipo_patentscope_browser", "simple", "wipo_patentscope_browser_queries_per_task"),
            ("uspto_patent_browser", "basic_search", "uspto_patent_browser_queries_per_task"),
        ):
            queries[provider] = [
                entry(provider, "patent_recall", "US", {"q": value, "mode": mode}, required=False, derived_from=source)
                for value, source in browser_values[: int(limits.get(limit_key, 3))]
            ]
        tm_values = brand_terms[:3]
        queries["uspto_tmsearch_browser"] = [
            entry(
                "uspto_tmsearch_browser", "trademark_recall", "US",
                {"q": value, "strategy": strategy}, required=True,
                derived_from=source,
            )
            for value, source in tm_values
            for strategy in ("exact", "phrase", "prefix")
        ]
        if "signa" in optional_sources:
            queries["signa"] = [
                entry("signa", "trademark_search", "US", {"q": value, "office": "US", "strategies": ["exact", "phonetic", "fuzzy", "prefix"]}, required=False, derived_from=source)
                for value, source in tm_values
            ]
        if "rapidapi_uspto_trademark" in optional_sources:
            queries["rapidapi_uspto_trademark"] = [
                entry("rapidapi_uspto_trademark", "trademark_search", "US", {"q": value, "search_type": "active"}, required=False, derived_from=source)
                for value, source in tm_values
            ]
    elif "signa" in required_sources:
        tm_values = brand_terms[:5]
        signa_targets = [("EU", "EM")] if "EU" in jurisdictions or any(value in EU_COUNTRIES for value in jurisdictions) else [(value, value) for value in jurisdictions]
        queries["signa"] = [
            entry("signa", "trademark_search", jurisdiction, {"q": value, "office": office, "strategies": ["exact", "phonetic", "fuzzy", "prefix"]}, required=True, derived_from=source)
            for jurisdiction, office in signa_targets
            for value, source in tm_values
        ]
    if "euipo_trademark" in required_sources:
        queries["euipo_trademark"] = [
            entry("euipo_trademark", "search", "EU", {"q": value, "page": 0, "size": 25}, required=True, derived_from=source)
            for value, source in brand_terms[:3]
        ]
    if "euipo_design" in required_sources:
        queries["euipo_design"] = [
            entry("euipo_design", "search", "EU", {"q": value, "page": 0, "size": 25}, required=True, derived_from=source)
            for value, source in (design_terms or product_terms)[:3]
        ]

    product_text = " ".join(str(value) for value in [product.get("title"), product.get("category"), *product.get("bullets", []), *product.get("structure", [])])
    plan: dict[str, Any] = {
        "schema_version": task["schema_version"],
        "task_id": task["task_id"],
        "created_at": now_iso(),
        "terms": terms,
        "classification_candidates": classification_candidates(product_text),
        "queries": queries,
        "execution_policy": {
            "waves": [
                {"wave": 1, "rule": "execute high-precision required queries"},
                {"wave": 2, "rule": "execute only when wave 1 has insufficient relevant candidates"},
            ],
            "max_api_concurrency": int(config.get("performance", {}).get("max_api_concurrency", 3)),
            "browser_execution": "hybrid_cdp_manual",
        },
    }
    atomic_write_json(task_dir / "search-plan.json", plan)
    print(task_dir / "search-plan.json")


if __name__ == "__main__":
    main()
