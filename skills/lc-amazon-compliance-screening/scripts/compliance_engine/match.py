"""Rule matching with three-valued logic (True / False / None=unknown)."""
from __future__ import annotations

import datetime

from .common import CORE_ATTRS, SEVERITY_RANK, digest
from .profile import searchable

UNKNOWN = None
# Sub-attributes are absent when their gate attribute is known false (no battery -> no battery chemistry, etc.).
GATES = {"battery.": "battery.included", "laser.": "laser.present", "blade.": "blade.present"}


class _Eval:
    def __init__(self, pack, profile, without_claims=False):
        self.pack = pack
        self.families = {f["id"] for f in profile.get("families") or []}
        self.claims = set() if without_claims else {c["id"] for c in profile.get("claims") or []}
        self.attrs = profile.get("attributes") or {}
        self.unknown = set()      # attributes whose unknown value blocked a decision
        self.anchor = False       # a family/claim condition evaluated True
        self.attr_hit = False     # a (non-negated) attribute condition evaluated True: the product has the property

    def cond(self, c, in_any=False, negated=False):
        for op in ("all", "any", "none"):
            if op in c:
                vals = [self.cond(x, in_any=(op == "any"), negated=negated or op == "none") for x in c[op]]
                if op == "all":
                    if False in vals:
                        return False
                    return UNKNOWN if UNKNOWN in vals else True
                if op == "any":
                    if True in vals:
                        return True
                    return UNKNOWN if UNKNOWN in vals else False
                if True in vals:
                    return False
                return UNKNOWN if UNKNOWN in vals else True
        if c.get("all_products"):
            return True
        if "family" in c:
            hit = c["family"] in self.families
            self.anchor = self.anchor or hit
            return hit
        if "claim" in c:
            hit = c["claim"] in self.claims
            self.anchor = self.anchor or hit
            return hit
        name = c["attr"]
        item = self.attrs.get(name)
        for prefix, gate in GATES.items():
            if name.startswith(prefix) and name != gate:
                g = self.attrs.get(gate) or {}
                if g.get("status") in ("provided", "inferred") and g.get("value") is False:
                    return False
        if not item or item.get("status") == "unknown" or item.get("value") is None:
            if in_any and name not in CORE_ATTRS:
                # One alternative among several, about a detail the profile need not state (origin, Wh, fibre %...):
                # unstated counts as not shown. Inside an AND with other evidence it stays unknown (a real question).
                return False
            self.unknown.add(name)
            return UNKNOWN
        res = self._attr(c, item["value"])
        if res is True and not negated:
            self.attr_hit = True
        return res

    @staticmethod
    def _attr(c, v):
        if "in" in c:
            have = {str(x) for x in (v if isinstance(v, list) else [v])}
            return bool(have & {str(x) for x in c["in"]})
        if "eq" in c:
            return v == c["eq"]
        for op, fn in (("gt", lambda a, b: a > b), ("gte", lambda a, b: a >= b),
                       ("lt", lambda a, b: a < b), ("lte", lambda a, b: a <= b)):
            if op in c:
                try:
                    return fn(float(v), float(c[op]))
                except (TypeError, ValueError):
                    return UNKNOWN
        return UNKNOWN


def is_general(rule) -> bool:
    """A rule whose only trigger is all_products (e.g. GPSR) is a general obligation."""
    t = rule.get("triggers") or {}

    def only_all(c):
        if c.get("all_products"):
            return True
        for op in ("all", "any"):
            if op in c and len(c) == 1:
                return all(only_all(x) for x in c[op])
        return False
    return only_all(t)


def _question(pack, attrs) -> list:
    out = []
    for a in sorted(attrs):
        spec = pack.attributes.get(a, {})
        q = f"请确认：{spec.get('zh', a)}（{a}）"
        if spec.get("values"):
            q += f"，可选：{'/'.join(str(v) for v in spec['values'])}"
        out.append(q)
    return out


def _claims_in(cond) -> set:
    if not isinstance(cond, dict):
        return set()
    if "claim" in cond:
        return {cond["claim"]}
    return set().union(*[_claims_in(x) for op in ("all", "any", "none") for x in cond.get(op) or []])


def match_site(pack, profile: dict, facts: dict, site: str, signals=None, quick: bool = False, as_of=None) -> list:
    """Candidates for one site. kind: triggered | possible | keyword_flag | platform_signal | general.

    A ban or approval rule that only the copy's claims trigger (e.g. "antibacterial") is lowered to compliance level:
    the new Listing must not repeat the claim (claim_only). A rule not yet in force is listed as upcoming (info)."""
    text = searchable(facts)
    as_of = as_of or datetime.date.today().isoformat()
    profile_claims = {c["id"] for c in profile.get("claims") or []}
    out = []
    for rule in pack.rules_for(site):
        rid = rule["id"]
        ev = _Eval(pack, profile)
        res = ev.cond(rule["triggers"])
        strong_m, weak_m = pack.rule_matchers[rid]
        strong = strong_m.find(text)
        weak = weak_m.find(text)
        general = is_general(rule)
        kind = None
        if general:
            # A duty for every product (recalls, counterfeits...). Its strong keywords in the title make it a case to review.
            kind = "keyword_flag" if strong else "general"
        elif res is True:
            kind = "triggered"
        elif res is UNKNOWN:
            # Quick mode cannot see attributes: only count rules anchored on a family/claim/keyword hit.
            if not quick or ev.anchor or strong:
                kind = "possible"
        if kind is None and strong:
            kind = "keyword_flag"
        if kind is None:
            continue
        severity, extra = rule["severity"], {}
        severe = SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK["approval_required"]
        if severe and kind == "triggered" and not strong and _Eval(pack, profile, without_claims=True).cond(rule["triggers"]) is False:
            extra = {"claim_only": sorted(profile_claims & _claims_in(rule["triggers"])), "severity_original": severity}
            severity = "compliance_required"
        start = str(rule.get("effective_from") or "")
        if start and start > as_of:
            extra.update({"upcoming": start, "severity_original": extra.get("severity_original") or severity})
            severity = "info"
        if rule.get("ban_condition_zh"):
            extra["condition_zh"] = rule["ban_condition_zh"]
        out.append({
            "cid": f"{site}:{rid}", "site": site, "rule_id": rid, "kind": kind,
            "severity": severity, "layer": rule["layer"], "topic_zh": rule["topic_zh"],
            "fba": rule.get("fba"), "quick_mode": bool(rule.get("quick_mode")),
            "can_prohibit": bool(rule.get("can_prohibit")),
            # The rule names concrete items (strong keywords): the product family is only where they occur. A rule can say
            # item_specific: false when its keywords are just examples and the trigger itself is the scope.
            "specific_item": bool(rule.get("item_specific", bool(strong_m.items))) and bool(strong_m.items),
            "unknown_attrs": sorted(ev.unknown) if kind == "possible" else [],
            "questions": _question(pack, ev.unknown) if kind == "possible" else [],
            "keyword_hits": {"strong": strong, "weak": weak},
            **extra,
        })
    for i, s in enumerate(signals or [], 1):
        out.append({
            "cid": f"{site}:SIGNAL-{i:02d}", "site": site, "rule_id": None, "kind": "platform_signal",
            "severity": "approval_required" if s.get("reasonCode") in ("APPROVAL_REQUIRED", "NOT_ELIGIBLE") else "info",
            "layer": "L2", "topic_zh": s.get("topic_zh") or "SP-API 审核限制", "fba": None, "quick_mode": False,
            "can_prohibit": False, "specific_item": False, "unknown_attrs": [], "questions": [],
            "keyword_hits": {"strong": [], "weak": []},
            "signal": {k: s.get(k) for k in ("reasonCode", "message", "links", "asin", "source")},
        })
    out.sort(key=lambda c: (-SEVERITY_RANK.get(c["severity"], 0), c["kind"] != "triggered", c["cid"]))
    return out


def match(pack, profile: dict, facts: dict, sites, signals_by_site=None, quick: bool = False, as_of=None) -> dict:
    cands = []
    for site in sites:
        cands.extend(match_site(pack, profile, facts, site, (signals_by_site or {}).get(site), quick=quick, as_of=as_of))
    body = {"ruleset": pack.digest, "profile": digest(profile), "candidates": cands}
    return {"candidates": cands, "candidates_digest": digest(body)}
