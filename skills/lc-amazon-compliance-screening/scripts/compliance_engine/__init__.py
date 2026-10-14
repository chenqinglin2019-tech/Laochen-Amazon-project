"""禁限售合规排查共享引擎（Skill 与 product-selection 内置预检共用）。Python 3.9+，仅标准库。"""
from __future__ import annotations

from . import match as _match
from . import profile as _profile
from . import report as _report
from . import review as _review
from .common import SITES, digest
from .rulepack import RulePack, RulePackError

ENGINE_VERSION = "compliance-engine-1.2.0"

__all__ = ["ENGINE_VERSION", "RulePack", "RulePackError", "SITES", "make_facts", "profile_template",
           "validate_profile", "match", "review_template", "validate_review", "assess", "quick_screen",
           "build_view", "render_html", "render_markdown", "render_csv", "constraints_text"]


def make_facts(product: dict, images=None, sites=None, fulfillment="unknown", catalog=None, user=None) -> dict:
    facts = {"schema": "compliance-facts-v1", "product": product, "images": images or [],
             "sites": list(sites or []), "fulfillment": fulfillment, "catalog": catalog or {}, "user": user or {}}
    facts["facts_digest"] = _profile.facts_digest(facts)
    return facts


profile_template = _profile.template
validate_profile = _profile.validate
review_template = _review.template
build_view = _report.build_view
render_html = _report.render_html
render_markdown = _report.render_markdown
render_csv = _report.render_csv
constraints_text = _report.constraints_text


def match(pack, profile, facts, sites, signals_by_site=None):
    return _match.match(pack, profile, facts, sites, signals_by_site)


def validate_review(pack, match_result, review, profile, facts, sites):
    return _review.validate(match_result, review, profile, facts, sites)


def assess(pack, match_result, review, profile, sites, coverage_by_site=None):
    return _review.assess(pack, match_result, review, profile, sites, coverage_by_site)


def quick_screen(pack, facts, site, signals=None, coverage=None) -> dict:
    """Backend-only screen for one site: keyword/product-type matching, no model, confidence low."""
    prof = _profile.quick_profile(pack, facts)
    m = _match.match(pack, prof, facts, [site], {site: signals or []}, quick=True)
    res = _review.quick_assess(pack, m, prof, site, coverage)
    return {"site": site, "profile": prof, "match": m, "result": res,
            "families": [f["id"] for f in prof["families"]], "digest": digest([facts.get("facts_digest"), pack.digest, site])}
