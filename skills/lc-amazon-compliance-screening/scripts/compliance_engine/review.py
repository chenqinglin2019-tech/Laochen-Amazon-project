"""Disposition validation (gates G3-G6) and deterministic assessment (G7-G8)."""
from __future__ import annotations

from .common import (CONFIDENCES, DG_ATTRS, SEVERITY_RANK, VERDICT_RANK, bad_text, canonical)
from .profile import check_refs, valid_refs

REVIEW_SCHEMA = "compliance-review-v1"
DECISIONS = ("applies", "not_applicable", "needs_info")
APPLIES_CODES = ("family_match", "attribute_match", "claim_present", "keyword_confirmed", "visual_confirmed",
                 "platform_signal")
EXCLUSION_CODES = ("different_product_type", "attribute_absent_verified", "claim_absent", "keyword_false_positive",
                   "condition_not_met", "exemption_applies", "duplicate_of_other_rule")
RESTRICTED_EXCLUSIONS = ("different_product_type", "attribute_absent_verified", "keyword_false_positive",
                         "condition_not_met", "exemption_applies")
SIGNAL_CLASSES = ("category_gate", "brand_gate", "asin_specific", "unclear")
CAP_ZH = {"low": "低", "medium": "中"}


def template(match_result: dict, sites) -> dict:
    disp = []
    for c in match_result["candidates"]:
        if c["kind"] == "general":
            continue
        item = {"cid": c["cid"], "decision": None, "codes": [], "reason_zh": None, "evidence": [],
                "_kind": c["kind"], "_severity": c["severity"], "_topic": c["topic_zh"]}
        if c.get("specific_item"):
            item["_check"] = "该规则针对具体物品：先核对商品是否就是规则所说的物品，不是就判 not_applicable（different_product_type）"
        if c.get("condition_zh"):
            item["_check"] = ("该规则只禁止这种情况：" + c["condition_zh"] + "。资料显示商品属于这种情况判 applies；"
                              "没有任何迹象判 not_applicable（condition_not_met），reason_zh 写明依据；有迹象但不能确定判 needs_info")
        if c.get("claim_only"):
            item["_check"] = "只因文案宣称触发（新 Listing 将禁止这些宣称）：核对原文案是否确有该宣称，有就判 applies"
        if c.get("upcoming"):
            item["_check"] = "该规则 " + c["upcoming"] + " 起生效，目前只作提醒：适用就判 applies"
        if c["kind"] == "possible":
            item["_unknown"] = c["unknown_attrs"]
            item["question_zh"] = None
        if c["kind"] == "platform_signal":
            item["classification"] = None
            item["_signal"] = c.get("signal")
        disp.append(item)
    return {
        "schema": REVIEW_SCHEMA,
        "candidates_digest": match_result["candidates_digest"],
        "dispositions": disp,
        "sites": [{"site": s, "confidence": None, "confidence_reason_zh": None, "summary_zh": None} for s in sites],
        "_examples": {
            "applies": {"decision": "applies", "codes": ["family_match"], "reason_zh": "商品是充电宝，属于该规则的品类",
                        "evidence": ["title", "image:img-1"]},
            "not_applicable": {"decision": "not_applicable", "codes": ["different_product_type"],
                               "reason_zh": "关键词 knife 来自「knife sharpener」，商品是磨刀器，不带刀刃",
                               "evidence": ["title", "image:img-2"]},
            "needs_info": {"decision": "needs_info", "codes": [], "reason_zh": "图片和文案都看不出电池类型",
                           "evidence": [], "question_zh": "电池是锂电池还是干电池？容量多少？"},
            "platform_signal": {"classification": "category_gate", "decision": "applies", "codes": ["platform_signal"],
                                "reason_zh": "限制原因是品类需要审核，与品牌无关", "evidence": []},
            "_codes": {"applies": list(APPLIES_CODES), "not_applicable": list(EXCLUSION_CODES)},
            "_rules": "每个候选恰好处置一次。禁售/需审核规则判不适用，只能用 " + "、".join(RESTRICTED_EXCLUSIONS)
                      + "，并给证据。possible 候选里列出的未知属性，不能用 attribute_absent_verified 排除——"
                        "要么在画像里补上该属性再重提，要么判 needs_info。",
        },
    }


def _err(errors, path, msg):
    errors.append({"path": path, "message": msg})


def validate(match_result: dict, review, profile: dict, facts: dict, sites) -> list:
    errors = []
    if not isinstance(review, dict):
        return [{"path": "", "message": "审阅必须是 JSON 对象"}]
    if review.get("schema") != REVIEW_SCHEMA:
        _err(errors, "schema", f"schema 必须是 {REVIEW_SCHEMA}")
    if review.get("candidates_digest") != match_result["candidates_digest"]:
        _err(errors, "candidates_digest", "候选清单已变化，请重新获取候选后再审阅")
    allowed = valid_refs(facts)
    cands = {c["cid"]: c for c in match_result["candidates"] if c["kind"] != "general"}
    seen = set()
    for i, d in enumerate(review.get("dispositions") or []):
        w = f"dispositions[{i}]"
        if not isinstance(d, dict):
            _err(errors, w, "必须是对象"); continue
        cid = d.get("cid")
        c = cands.get(cid)
        if c is None:
            _err(errors, w, f"不存在的候选 {cid!r}"); continue
        if cid in seen:
            _err(errors, w, f"候选 {cid} 处置了不止一次"); continue
        seen.add(cid)
        dec = d.get("decision")
        if dec not in DECISIONS:
            _err(errors, w + ".decision", "只能是 applies / not_applicable / needs_info"); continue
        reason = d.get("reason_zh")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 400 or bad_text(reason):
            _err(errors, w + ".reason_zh", "需要 400 字以内的中文理由")
        codes = d.get("codes") or []
        if not isinstance(codes, list):
            _err(errors, w + ".codes", "codes 必须是列表"); codes = []
        if c["kind"] == "platform_signal":
            if d.get("classification") not in SIGNAL_CLASSES:
                _err(errors, w + ".classification", "SP-API 审核信号必须分类：" + "/".join(SIGNAL_CLASSES))
            check_refs(d.get("evidence") or [], allowed, w + ".evidence", errors, required=False)
            continue
        if dec == "applies":
            if not codes or any(x not in APPLIES_CODES for x in codes):
                _err(errors, w + ".codes", "applies 需要触发码：" + "/".join(APPLIES_CODES))
            check_refs(d.get("evidence"), allowed, w + ".evidence", errors)
        elif dec == "not_applicable":
            if not codes or any(x not in EXCLUSION_CODES for x in codes):
                _err(errors, w + ".codes", "not_applicable 需要排除码：" + "/".join(EXCLUSION_CODES))
            elif SEVERITY_RANK[c["severity"]] >= SEVERITY_RANK["approval_required"] and \
                    not set(codes) & set(RESTRICTED_EXCLUSIONS):
                _err(errors, w + ".codes", "禁售/需审核规则只能用这些排除码：" + "、".join(RESTRICTED_EXCLUSIONS))
            if c["kind"] == "possible" and "attribute_absent_verified" in codes:
                _err(errors, w + ".codes", "未知属性 " + "、".join(c["unknown_attrs"])
                     + " 不能用 attribute_absent_verified 排除：先在画像里补齐属性，或判 needs_info")
            check_refs(d.get("evidence"), allowed, w + ".evidence", errors)
        else:
            q = d.get("question_zh")
            if not isinstance(q, str) or not q.strip() or len(q) > 300 or bad_text(q):
                _err(errors, w + ".question_zh", "needs_info 需要写明要补的信息（300 字以内）")
    missing = sorted(set(cands) - seen)
    if missing:
        _err(errors, "dispositions", f"还有 {len(missing)} 个候选没有处置：" + "、".join(missing[:20]))
    site_items = {s.get("site"): s for s in review.get("sites") or [] if isinstance(s, dict)}
    for s in sites:
        item = site_items.get(s)
        if not item:
            _err(errors, "sites", f"缺少站点 {s} 的置信度说明"); continue
        if item.get("confidence") not in CONFIDENCES:
            _err(errors, f"sites.{s}.confidence", "只能是 low / medium / high")
        r = item.get("confidence_reason_zh")
        if not isinstance(r, str) or not r.strip() or len(r) > 400 or bad_text(r):
            _err(errors, f"sites.{s}.confidence_reason_zh", "需要 400 字以内的置信度理由")
    return errors


def _cap(conf, cap):
    order = {c: i for i, c in enumerate(CONFIDENCES)}
    return conf if order[conf] <= order[cap] else cap


def _requirements(pack, rule_ids):
    merged = {}
    for rid in rule_ids:
        rule = pack.rules[rid]
        for q in rule.get("requirements") or []:
            key = canonical([q.get("kind"), (q.get("name_zh") or "").strip().lower()])
            item = merged.setdefault(key, {"kind": q.get("kind"), "name_zh": q.get("name_zh"),
                                           "detail_zh": q.get("detail_zh"), "issuer_zh": q.get("issuer_zh"),
                                           "submit_via_zh": q.get("submit_via_zh"), "rules": [], "sources": []})
            if rid not in item["rules"]:
                item["rules"].append(rid)
            for s in rule.get("sources") or []:
                if s not in item["sources"]:
                    item["sources"].append(s)
    return list(merged.values())


def _constraints(pack, rule_ids, strength):
    forbid, required = [], []
    for rid in rule_ids:
        lc = pack.rules[rid].get("listing_constraints") or {}
        for cl in lc.get("forbid_claims") or []:
            forbid.append({"claim": cl, "claim_zh": pack.claims.get(cl, {}).get("zh", cl), "rule": rid, "strength": strength})
        for st in lc.get("required_statements_zh") or []:
            required.append({"text_zh": st, "rule": rid, "strength": strength})
    return {"forbid_claims": forbid, "required_statements": required}


def assess_site(pack, site, cands, dispositions, profile, site_review=None, coverage=None, quick=False) -> dict:
    """Deterministic verdict for one site from candidates + dispositions."""
    coverage = coverage or {}
    general = [c for c in cands if c["kind"] == "general"]
    applied, needs, notes, caps = [], [], [], []
    signal_floor = None
    for c in cands:
        if c["kind"] == "general":
            continue
        d = dispositions.get(c["cid"]) or {}
        if c["kind"] == "platform_signal":
            cls = d.get("classification") or "unclear"
            if cls == "category_gate":
                signal_floor = "approval_required"
                notes.append("SP-API：该 ASIN 在本账号需审核，且原因属于品类级")
            elif cls == "unclear":
                caps.append(("medium", "SP-API 审核限制原因不明"))
                needs.append(c)
            else:
                notes.append("SP-API 限制为品牌级或 ASIN 级，不影响自有品牌新品")
            continue
        dec = d.get("decision")
        if dec == "applies":
            applied.append(c)
        elif dec == "needs_info":
            needs.append(c)
    rank = 1
    verdict = "no_specific_restriction"
    blocked_prohibit = []
    for c in applied:
        sev = c["severity"]
        if sev == "prohibited" and not c["can_prohibit"] and not quick:
            blocked_prohibit.append(c["rule_id"])
            needs.append(c)
            continue
        v = {"prohibited": "prohibited", "approval_required": "approval_required",
             "compliance_required": "compliance_required", "info": "no_specific_restriction"}[sev]
        if VERDICT_RANK[v] > rank:
            rank, verdict = VERDICT_RANK[v], v
    if signal_floor and VERDICT_RANK[signal_floor] > rank:
        rank, verdict = VERDICT_RANK[signal_floor], signal_floor
    provisional = verdict
    open_worse = [c for c in needs if SEVERITY_RANK.get(c["severity"], 0) >= rank and
                  SEVERITY_RANK.get(c["severity"], 0) >= SEVERITY_RANK["compliance_required"]]
    if open_worse:
        verdict = "needs_info"
    if blocked_prohibit:
        notes.append("命中的禁售规则尚未完成核验（" + "、".join(blocked_prohibit) + "），不能直接判禁售，已转为待补信息")
    # FBA dimension
    fba = "fba_ok"
    fba_rules = applied
    if quick:
        # Same evidence bar as bans: a strong keyword, or a rule whose category is itself the evidence.
        fba_rules = [c for c in applied if (c.get("keyword_hits") or {}).get("strong")
                     or (c["kind"] == "triggered" and c.get("quick_mode") and not c.get("specific_item"))]
    if any(c.get("fba") == "prohibited" for c in fba_rules):
        fba = "fba_prohibited"
    elif any(c.get("fba") == "dg_review" for c in fba_rules):
        fba = "fba_dg_review"
    else:
        attrs = profile.get("attributes") or {}
        if any((attrs.get(a) or {}).get("status", "unknown") == "unknown" for a in DG_ATTRS):
            fba = "unknown"
    # confidence
    conf = (site_review or {}).get("confidence") or ("low" if quick else "medium")
    reason = (site_review or {}).get("confidence_reason_zh") or ("初筛只看标题关键词，未看图" if quick else "")
    if quick:
        caps.append(("low", "初筛只看标题关键词和商品类型，未看图"))
    if any(c["kind"] == "possible" for c in needs):
        caps.append(("medium", "部分关键属性未知"))
    for gap in coverage.get("gaps") or []:
        caps.append(("medium", gap))
    if not quick and not coverage.get("images_viewed"):
        caps.append(("medium", "没有可查看的商品图片"))
    for cap, why in caps:
        new = _cap(conf, cap)
        if new != conf:
            reason = (reason + "；" if reason else "") + "置信度封顶为" + CAP_ZH[cap] + "：" + why
        conf = new
    # Rules not in force yet, and conditional bans whose condition is not met, are reminders: listed, never raise the verdict.
    upcoming = [c for c in applied if c.get("upcoming")]
    applied = [c for c in applied if not c.get("upcoming")]
    reminders = [{"rule_id": c["rule_id"], "topic_zh": c["topic_zh"], "severity": c.get("severity_original") or c["severity"],
                  "text_zh": c["upcoming"] + " 起生效：" + c["topic_zh"]} for c in upcoming]
    for c in cands:
        d = dispositions.get(c["cid"]) or {}
        if c.get("condition_zh") and d.get("decision") == "not_applicable" and "condition_not_met" in (d.get("codes") or []):
            reminders.append({"rule_id": c["rule_id"], "topic_zh": c["topic_zh"], "severity": c["severity"],
                              "text_zh": "不得销售：" + c["condition_zh"]})
    applied_ids = [c["rule_id"] for c in applied if c["rule_id"]]
    general_ids = [c["rule_id"] for c in general]
    possible_ids = [c["rule_id"] for c in needs if c.get("rule_id")]
    constraints = _constraints(pack, applied_ids, "must")
    soft = _constraints(pack, possible_ids, "check")
    constraints["forbid_claims"] += soft["forbid_claims"]
    constraints["required_statements"] += soft["required_statements"]
    for c in applied:
        for cl in c.get("claim_only") or []:
            constraints["forbid_claims"].append({"claim": cl, "claim_zh": pack.claims.get(cl, {}).get("zh", cl),
                                                 "rule": c["rule_id"], "strength": "must"})
            notes.append(f"原文案的「{pack.claims.get(cl, {}).get('zh', cl)}」宣称会触发{c['rule_id']}（"
                         f"{ {'prohibited': '禁售', 'approval_required': '需审核'}.get(c.get('severity_original'), '')}）：新 Listing 不得使用该宣称")
    return {
        "site": site, "verdict": verdict, "provisional_verdict": provisional, "fba": fba,
        "confidence": conf, "confidence_reason_zh": reason,
        "summary_zh": (site_review or {}).get("summary_zh"),
        "applied": [{"rule_id": c["rule_id"], "severity": c["severity"], "layer": c["layer"],
                     "topic_zh": c["topic_zh"], "reason_zh": (dispositions.get(c["cid"]) or {}).get("reason_zh")}
                    for c in applied],
        "open_questions": [{"rule_id": c.get("rule_id"), "topic_zh": c["topic_zh"], "severity": c["severity"],
                            "question_zh": (dispositions.get(c["cid"]) or {}).get("question_zh")
                            or "；".join(c.get("questions") or [])} for c in needs],
        # A claim-only rule asks for no documents: its remedy is the forbidden claim.
        "requirements": _requirements(pack, [c["rule_id"] for c in applied if c["rule_id"] and not c.get("claim_only")]),
        "reminders": reminders,
        "general_obligations": _requirements(pack, general_ids),
        "constraints": constraints,
        "notes": notes,
        "formal_allowed": verdict != "needs_info",
    }


def assess(pack, match_result, review, profile, sites, coverage_by_site=None) -> dict:
    disp = {d["cid"]: d for d in (review or {}).get("dispositions") or [] if isinstance(d, dict) and d.get("cid")}
    site_reviews = {s.get("site"): s for s in (review or {}).get("sites") or [] if isinstance(s, dict)}
    results = []
    for s in sites:
        cands = [c for c in match_result["candidates"] if c["site"] == s]
        results.append(assess_site(pack, s, cands, disp, profile, site_reviews.get(s),
                                   (coverage_by_site or {}).get(s)))
    return {"sites": results, "report_mode": "formal" if all(r["formal_allowed"] for r in results) else "draft"}


def quick_assess(pack, match_result, profile, site, coverage=None) -> dict:
    """Quick screen: no dispositions. Triggered and anchored-possible rules count; strong keyword flags count."""
    cands = [c for c in match_result["candidates"] if c["site"] == site]
    disp = {}
    for c in cands:
        strong = bool((c.get("keyword_hits") or {}).get("strong"))
        severe = SEVERITY_RANK.get(c["severity"], 0) >= SEVERITY_RANK["approval_required"]
        family_is_evidence = c["kind"] == "triggered" and c["quick_mode"] and not c.get("specific_item")
        if severe and c["kind"] in ("triggered", "possible") and not strong and not family_is_evidence:
            # A ban or approval inferred from the product category alone is not evidence: titles cannot show the content
            # (symbols, origin, claims, the exact item) these rules are about. Count it only on a strong keyword, or
            # when the rule is usable in quick mode and names no specific items (its category is the evidence).
            continue
        if c.get("specific_item") and not strong:
            continue  # the rule names specific items (prop money, helium tanks...) and the text names none of them
        if c["kind"] in ("triggered", "keyword_flag"):
            disp[c["cid"]] = {"decision": "applies"}
        elif c["kind"] == "possible":
            # Uncertain compliance-level rules are listed as likely requirements; only approval/prohibited
            # level uncertainty makes the quick result "needs_info" (formal pre-check required).
            sev = SEVERITY_RANK.get(c["severity"], 0)
            if sev >= SEVERITY_RANK["approval_required"]:
                disp[c["cid"]] = {"decision": "needs_info"}
            elif sev == SEVERITY_RANK["compliance_required"]:
                disp[c["cid"]] = {"decision": "applies"}
        elif c["kind"] == "platform_signal":
            disp[c["cid"]] = {"classification": "category_gate"}  # quick mode cannot tell brand from category: be strict
    res = assess_site(pack, site, cands, disp, profile, None, coverage, quick=True)
    # In quick mode a prohibited hit is only "suspected"; anything open at approval level or above needs a formal check.
    return res
