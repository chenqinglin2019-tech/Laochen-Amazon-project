"""Versioned source roles for country/right/stage routing."""
from __future__ import annotations

from typing import Any

GOOGLE_PATENT_SOURCES = frozenset({"serper_patents", "serpapi_google_patents"})
EU_TARGETS = frozenset({"FR", "DE", "IT", "ES"})


def _signa_available(country: str) -> bool:
    try:
        from common import load_skill_config
        config = load_skill_config().get("providers", {}).get("signa", {})
        office = str(config.get("office_map", {}).get(country, "")).upper()
        return bool(office and office not in {str(value).upper() for value in config.get("excluded_offices", [])})
    except (OSError, ValueError, TypeError):
        return False


def source_upstream(provider: str) -> str:
    if provider in GOOGLE_PATENT_SOURCES:
        return "google_patents"
    if provider.startswith("serpapi_"):
        return "serpapi"
    if provider.startswith("euipo_"):
        return "euipo"
    return provider


def priority(country: str, right_type: str, stage: str, *, revision: str = "api-first-v2") -> list[tuple[str, str]]:
    """Ordered provider roles; callers still apply existing capability gates."""
    country = country.upper()
    if revision == "api-first-v3":
        return _priority_v3(country, right_type, stage)
    if stage == "content" and right_type in {"patent", "utility_model", "design"}:
        if country == "EP":
            return [("epo_publication_server", "preferred"), ("epo_ops", "complement"), ("serpapi_google_patents", "fallback")]
        if country == "FR":
            return [("inpi_api", "preferred"), ("epo_ops", "complement"), ("serpapi_google_patents", "fallback")]
        return [("epo_ops", "preferred"), ("serpapi_google_patents", "fallback")]
    if stage == "status":
        if country == "FR": return [("inpi_api", "preferred")]
        if country == "JP": return [("jpo_api", "preferred")]
        if country == "EU" and right_type == "design": return [("euipo_design", "preferred")]
        if country == "EU" and right_type.startswith("trademark"): return [("euipo_trademark", "preferred")]
        return []
    if stage != "discovery": return []
    if right_type in {"patent", "utility_model"}:
        base = [("inpi_api", "preferred")] if country == "FR" else []
        return [*base, ("epo_ops", "preferred" if not base else "complement"), ("serper_patents", "fallback"), ("serpapi_google_patents", "fallback")]
    if right_type == "design":
        if country == "US":
            # PPS remains the browser fallback; this route covers the
            # executable native Google Patents DESIGN query first.
            return [("serpapi_google_patents", "preferred"), ("serper_patents", "complement")]
        base = [("inpi_api", "preferred")] if country == "FR" else []
        if country in EU_TARGETS or country == "EU": base.append(("euipo_design", "preferred" if not base else "complement"))
        return [*base, ("serper_patents", "fallback"), ("serpapi_google_patents", "fallback")]
    if right_type == "trademark_word":
        base = [("inpi_api", "preferred")] if country == "FR" else []
        if country == "EU": base.append(("euipo_trademark", "preferred"))
        if country in {"US", "FR", "EU"}: base.append(("signa", "complement" if base else "preferred"))
        return [*base, ("serper_web", "fallback")]
    if right_type in {"copyright", "trade_dress", "unregistered_design", "trademark_figurative"}:
        return [("serpapi_google_lens", "preferred"), ("serper_images", "complement"), ("serper_web", "fallback")]
    return []


def _priority_v3(country: str, right_type: str, stage: str) -> list[tuple[str, str]]:
    """API-first v3 routes by available official/API coverage, then targeted web."""
    if stage == "content" and right_type in {"patent", "utility_model", "design"}:
        return priority(country, right_type, stage, revision="api-first-v2")
    if stage == "status":
        return priority(country, right_type, stage, revision="api-first-v2")
    if stage != "discovery":
        return []
    if right_type in {"patent", "utility_model"}:
        routes = [("inpi_api", "preferred")] if country == "FR" else []
        routes.append(("epo_ops", "complement" if routes else "preferred"))
        routes.extend([("serper_patents", "web_fallback"),
                       ("serpapi_google_patents", "fallback")])
        return routes
    if right_type == "design":
        routes = []
        if country == "FR":
            routes.append(("inpi_api", "preferred"))
        if country == "EU" or country in EU_TARGETS:
            routes.append(("euipo_design", "preferred" if not routes else "complement"))
        # Serper's Google Patents endpoint must remain in the plan when enabled,
        # including the US design lane; it is distinct from API availability.
        routes.extend([("serpapi_google_patents", "preferred" if not routes else "complement"),
                       ("serper_patents", "web_fallback")])
        return routes
    if right_type == "trademark_word":
        routes = []
        if country == "EU":
            routes.append(("euipo_trademark", "preferred"))
        if country == "FR":
            routes.append(("inpi_api", "preferred" if not routes else "complement"))
        if _signa_available(country):
            routes.append(("signa", "preferred" if not routes else "complement"))
        routes.append(("serper_web", "web_fallback"))
        return routes
    if right_type == "trademark_figurative":
        routes = []
        if country == "EU":
            routes.append(("euipo_trademark", "preferred"))
        if _signa_available(country):
            routes.append(("signa", "preferred" if not routes else "complement"))
        routes.extend([("serpapi_google_lens", "image_api"), ("serper_images", "web_fallback"),
                       ("serper_web", "web_fallback")])
        return routes
    if right_type in {"trade_dress", "unregistered_design", "copyright"}:
        return [("serpapi_google_lens", "preferred"), ("serper_images", "complement"),
                ("serper_web", "web_fallback")]
    if right_type == "enforcement":
        return [("serper_web", "preferred_web_api"), ("public_web_browser", "targeted_web_fallback")]
    return []


def executable_routes(country: str, right_type: str, stage: str, capabilities: dict[str, Any]) -> list[dict[str, str]]:
    return [{"provider": p, "provider_role": r, "source_upstream": source_upstream(p)}
            for p, r in priority(country, right_type, stage)
            if p.startswith(("serper_", "serpapi_", "signa")) or capabilities.get(p, {}).get("executable") is True]
