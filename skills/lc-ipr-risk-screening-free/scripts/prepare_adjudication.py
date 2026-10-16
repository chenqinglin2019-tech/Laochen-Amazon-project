#!/usr/bin/env python3
"""Prepare the chief adjudication: a bound skeleton plus a worksheet of the units that need a decision.

Reads both final reviews, checks they match the live input digest, applies the task's own
conflict rule (``assessment_estimate._row_conflicts``) and writes

* ``adjudication.json`` -- live digest, ``review_refs`` (hash of each whole review) and one draft
  decision per unit that needs the chief (a copy of the first review's row). ``reviewer``,
  ``review_context.session_id`` and every ``adjudication_reasoning`` are left empty on purpose:
  the publication gate rejects the file until the chief has actually decided and filled them.
* ``adjudication-worksheet.json`` -- for each such unit the conflicting fields with both reviewers'
  values side by side, so the chief does not have to diff two full reviews.

No validator is changed and nothing is decided here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
import re
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, sha256_json

UNIT_KEYS = ("scenario_id", "jurisdiction", "right_type", "candidate_id", "assessment_object")
SHOWN_FIELDS = ("risk", "right_state", "exclusion_basis", "evidence_confidence", "module_id", "out_of_scope",
                "future_signal", "signal_only", "scope_exclusion_basis")


def _claims(row):
    return sorted({(str(claim.get("claim_id")), str(claim.get("claim_type")), str(claim.get("conclusion")))
                   for claim in row.get("comparison", {}).get("claims", []) if isinstance(claim, dict)})


def _summary(row):
    shown = {key: row.get(key) for key in SHOWN_FIELDS if key in row}
    if row.get("comparison", {}).get("claims"):
        shown["claims"] = [list(item) for item in _claims(row)]
    exception = row.get("applicability_exception")
    if exception:
        shown["applicability_exception"] = {"kind": exception.get("kind"), "reasoning": exception.get("reasoning")}
    for key in ("reasoning", "pending_reasoning"):
        if isinstance(row.get(key), str) and row[key].strip():
            shown[key] = row[key] if len(row[key]) <= 800 else row[key][:800] + "…"
    return shown


def _selected_candidate_drafts(task, left, right, refs):
    """Draft decisions for every rated-or-pending patent candidate both reviewers left without a claims table.

    Under best-estimate-risk-v1 a rated patent row must carry comparison.claims[] with the independent
    claims; the recorded specialty comparison is projected into that shape so the chief only writes the
    grade, status and reasoning. Nothing is graded here (risk stays null, status stays pending).
    """
    from specialty_analysis import claims_projection
    drafts, notes = [], []
    for key in sorted(set(left) | set(right), key=str):
        chosen = left.get(key) or right[key]
        if (not chosen.get("candidate_id") or chosen.get("right_type") not in {"patent", "utility_model"}
                or chosen.get("out_of_scope") or chosen.get("future_signal") or chosen.get("signal_only")
                or any(((side.get(key) or {}).get("comparison") or {}).get("claims") for side in (left, right))):
            continue        # a reviewer already supplied the claims table: nothing to draft
        projection = claims_projection(task, {name: chosen.get(name) for name in
                                              ("candidate_id", "scenario_id", "jurisdiction", "right_type")})
        if not projection["claims"]:
            notes.append({"unit": {name: chosen.get(name) for name in UNIT_KEYS if name in chosen},
                          "draft": "no_recorded_claim_comparison"})
            continue
        draft = deepcopy(chosen)
        draft["comparison"] = {**(draft.get("comparison") or {}), "implementations": projection["implementations"],
                               "claims": projection["claims"]}
        refs_in_table = {ref for claim in projection["claims"] for element in claim["elements"] for ref in element["evidence_refs"]}
        refs_in_table |= {ref for item in projection["implementations"] for ref in item["product_evidence_refs"]}
        draft["evidence_refs"] = list(dict.fromkeys([*draft.get("evidence_refs", []), *sorted(refs_in_table)]))
        draft["risk"] = None
        draft["assessment_status"] = "pending"
        draft["adjudication_reasoning"] = ""
        draft["review_refs"] = dict(refs)
        drafts.append(draft)
        notes.append({"unit": {name: chosen.get(name) for name in UNIT_KEYS if name in chosen},
                      "draft": "claims_projection",
                      "chief_must_fill": ["risk", "assessment_status", "adjudication_reasoning",
                                          "assumptions/lower_if for elements whose result is unknown"],
                      "claims": [{"claim_id": claim["claim_id"],
                          "implementation_id": claim["implementation_id"], "conclusion": claim["conclusion"],
                          "elements": {result: sum(1 for element in claim["elements"] if element["result"] == result)
                                       for result in ("supports_risk", "excludes_risk", "unknown")}}
                          for claim in projection["claims"]]})
    return drafts, notes


def _independent_claims(row):
    return [claim for claim in ((row or {}).get("comparison") or {}).get("claims") or []
            if isinstance(claim, dict) and claim.get("claim_type") == "independent"]


def _adopt_claims_table(draft, other):
    """A selected patent row drafted from a review without an independent-claim table takes the table the other
    review gave for the same unit (its implementations, claims and the evidence they cite). r5d2 real run: the first
    reviewer rated four selected patents 极低 without element tables, the second gave them; the draft took the first
    row and publication refused it (SELECTED_PATENT_INDEPENDENT_CLAIM_COMPARISON_REQUIRED). No grade changes."""
    if (not other or draft.get("right_type") not in {"patent", "utility_model"} or not draft.get("candidate_id")
            or _independent_claims(draft) or not _independent_claims(other)):
        return False
    theirs = other.get("comparison") or {}
    draft["comparison"] = {**(draft.get("comparison") or {}), "claims": deepcopy(theirs.get("claims")),
                           "implementations": deepcopy(theirs.get("implementations") or [])}
    draft["evidence_refs"] = list(dict.fromkeys([*draft.get("evidence_refs", []), *other.get("evidence_refs", [])]))
    return True


CONFIDENCE_ORDER = ("低", "中", "高")
MARKING_RE = re.compile(r"\bpatent(?:ed|s)?\b|\bpat\.?\s*(?:no|#)|\b(?:US|U\.S\.)\s*(?:pat\w*\s*)?(?:no\.?\s*)?[\dD][\d,]{5,}", re.I)


def _detail_record(evidence, row):
    """The exact SerpApi detail record of this candidate (bound by candidate id), or None."""
    for entry in (evidence.get("collections") or {}).get("patents", []):
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        if (entry.get("provider") == "serpapi_google_patents" and entry.get("operation") == "candidate_detail"
                and payload.get("candidate_id") == row.get("candidate_id")
                and entry.get("right_type") == row.get("right_type")):
            return entry
    return None


def _marking_text(task):
    product = task.get("product") or {}
    texts = [product.get("title")] + list(product.get("bullets") or []) + list(product.get("visible_ip_claims") or [])
    for text in texts:
        value = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
        found = MARKING_RE.search(value or "")
        if found:
            start = max(0, found.start() - 60)
            return value[start:found.end() + 60].strip()
    return None


def marking_for(task, number):
    """r6 (report-always-v1): the listing text that marks THIS patent - its own number, not "patent pending",
    "patent leather" or another patent. None when the listing does not name the candidate's number."""
    match = re.match(r"^(?:[A-Z]{2})?(D)?0*(\d+)", str(number or "").upper().replace(" ", ""))
    if not match or len(match.group(2)) < 6:
        return None
    digits, design = match.group(2), bool(match.group(1))
    product = task.get("product") or {}
    texts = [product.get("title")] + list(product.get("bullets") or []) + list(product.get("visible_ip_claims") or [])
    for text in texts:
        value = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
        for found in re.finditer(r"(?:D\s*)?\d[\d,\s]{5,12}\d", value or "", re.I):
            seen = re.sub(r"[^0-9]", "", found.group(0))
            if seen.lstrip("0") == digits.lstrip("0") and (not design or found.group(0).upper().startswith("D")
                                                            or "D" in value[max(0, found.start() - 4):found.start()].upper()):
                start = max(0, found.start() - 60)
                return value[start:found.end() + 60].strip()
    return None


def extreme_rule(task, evidence, row):
    """best-estimate-risk-v2 极高 rule, checked on frozen facts only.

    (1) trusted API record of this candidate says the right is in force, (2) the listing carries a patent
    marking, (3) one independent claim of one implementation has every element supports_risk or unknown and
    at least one supports_risk. Returns (applies, reasons, assumptions)."""
    if row.get("right_type") not in {"patent", "utility_model"} or not row.get("candidate_id"):
        return False, [], []
    detail = _detail_record(evidence, row)
    payload = (detail or {}).get("payload") or {}
    status = str(payload.get("legal_status") or payload.get("status") or "")
    reasons, assumptions = [], []
    if status.lower() != "active":
        return False, [], []
    reasons.append("可信API记录现行状态为有效（" + status + "）")
    import report_always
    marked = report_always.enabled(task)
    # r6: the listing must name this patent's own number, and every element of the claim must correspond (owner
    # decision 2026-10-15: elements the photos cannot show cap the grade at 中)
    marking = marking_for(task, payload.get("publication_number")) if marked else _marking_text(task)
    if not marking:
        return False, [], []
    reasons.append("商品页面标注专利：“" + marking[:80] + "”")
    allowed = {"supports_risk"} if marked else {"supports_risk", "unknown"}
    claims = [claim for claim in (row.get("comparison") or {}).get("claims", []) if isinstance(claim, dict)
              and claim.get("claim_type") == "independent" and claim.get("elements")
              and all(element.get("result") in allowed for element in claim["elements"])
              and any(element.get("result") == "supports_risk" for element in claim["elements"])]
    if not claims:
        return False, [], []
    reasons.append("独立权利要求" + "、".join(dict.fromkeys(str(claim.get("claim_id")) for claim in claims))
                   + "的必要要素均为对应或与已见结构一致")
    owners = [str(item) for item in payload.get("assignees") or [] if str(item).strip()]
    if not owners or all(owner.lower() == "individual" for owner in owners):
        inventors = "、".join(item.get("name", "") for item in payload.get("inventors") or [] if isinstance(item, dict))
        assumptions.append("权利人记录未具名（个人申请人" + ("：" + inventors if inventors else "") + "），按专利有效推定其可主张权利；不影响等级。")
    return True, reasons, assumptions


RISK_ORDER = ("极低", "低", "中", "高", "极高")


def utility_cap_level(row):
    """r6 (owner decision 2026-10-15): the highest level an invention row's own independent-claim table supports.

    every element of one independent claim corresponds -> 极高 (the 极高 rule still needs its other conditions);
    visible elements correspond and some cannot be seen -> 中; no element can be seen -> 低; an element differs -> 低.
    None when the row carries no independent-claim table."""
    best = None
    for claim in _independent_claims(row):
        results = [element.get("result") for element in claim.get("elements") or [] if isinstance(element, dict)]
        if not results:
            continue
        if "excludes_risk" in results:
            level = "低"
        elif all(result == "supports_risk" for result in results):
            level = "极高"
        elif all(result == "unknown" for result in results):
            level = "低"
        else:
            level = "中"
        if best is None or RISK_ORDER.index(level) > RISK_ORDER.index(best):
            best = level
    return best


def _utility_cap(task, decisions, index, by_key, refs, worksheet, key_of):
    """r6: an invention row never settles above the level its own claim table supports; review levels above it are
    lowered to it. When the lowered levels agree the program writes the chief decision, otherwise the row stays open
    with the cap named in the worksheet. Returns the number of rows the program settled."""
    settled = 0
    for key, rows in index.items():
        sample = rows[0]
        if (sample.get("right_type") not in {"patent", "utility_model"} or not sample.get("candidate_id")
                or sample.get("out_of_scope") or sample.get("future_signal") or sample.get("signal_only")):
            continue
        levels, capped = [], False
        for row in rows:
            cap, risk = utility_cap_level(row), row.get("risk")
            if cap and risk in RISK_ORDER and RISK_ORDER.index(risk) > RISK_ORDER.index(cap):
                levels.append(cap)
                capped = True
            else:
                levels.append(risk)
        if not capped:
            continue
        unit = {name: sample.get(name) for name in UNIT_KEYS if name in sample}
        original = [str(row.get("risk")) for row in rows]
        if len(rows) != 2 or len(set(levels)) != 1 or levels[0] not in RISK_ORDER:
            worksheet.append({"unit": unit, "conflicts": [], "program_resolution": "utility_cap_open",
                              "caps": [utility_cap_level(row) for row in rows], "reviews": original})
            continue
        target = by_key.get(key)
        if target is not None and str(target.get("adjudication_reasoning") or "").strip():
            continue
        level = levels[0]
        # the decision is written from the review that already gave this level (its arguments and comparison argue
        # for it); a claims table the draft projected from the recorded comparison is kept
        agreeing = next((row for row in rows if row.get("risk") == level), None)
        base = deepcopy(agreeing or (target if target is not None else sample))
        if target is not None:
            drafted = (target.get("comparison") or {})
            if drafted.get("claims") and not (base.get("comparison") or {}).get("claims"):
                base["comparison"] = {**(base.get("comparison") or {}), "claims": deepcopy(drafted["claims"]),
                                      "implementations": deepcopy(drafted.get("implementations") or [])}
            target.clear()
            target.update(base)
        else:
            target = base
        target["review_refs"] = dict(refs)
        reasoning = ("按发明专利定级规则：独立权利要求" + ("有照片上看不到的要素，最高定中" if level == "中" else
                     "的要素在照片上无法核对或有要素不对应，定低") + "；两审原评" + "／".join(original) + "。")
        target.update(risk=level, assessment_status="assessed")
        target.pop("pending_reasoning", None)
        target["reasoning"] = reasoning + "审阅理由：" + str(target.get("reasoning") or "")
        target["evidence_confidence"] = _lower(target.get("evidence_confidence"), "中") or "中"
        target["adjudication_reasoning"] = ("按发明专利定级规则（用户 2026-10-15 决定）：可见要素都对应但有看不到的要素最高定中，"
            "要素一个都看不到定低；两审原评" + "／".join(original) + "，主审按规则定为" + level + "。")
        if key not in by_key:
            decisions.append(target)
            by_key[key] = target
        settled += 1
        worksheet.append({"unit": unit, "conflicts": [], "program_resolution": "utility_cap_v1", "reviews": original,
                          "level": level})
    return settled


def _lower(*values):
    known = [value for value in values if value in CONFIDENCE_ORDER]
    return min(known, key=CONFIDENCE_ORDER.index) if known else None


def _design_floor(task, task_dir, decisions, index, by_key, refs, worksheet, key_of):
    """r5d20 (design-overall-v1 tasks, owner decision): a design never settles below the level its recorded main-body
    relation supports (design_overall.floor). Review levels below the floor are lifted to it; when the lifted levels
    agree the program writes the chief decision (reasoning says the reviews' levels and why), otherwise the row stays
    open for the chief with the floor named in the worksheet. Returns the number of rows the program settled."""
    import design_overall
    settled, lifted_scopes = 0, {}
    for key, rows in index.items():
        sample = rows[0]
        if (sample.get('right_type') != 'design' or not sample.get('candidate_id') or sample.get('out_of_scope')
                or sample.get('future_signal') or sample.get('signal_only') or design_overall.exempt(rows)):
            continue
        level, basis = design_overall.floor(task, task_dir, sample)
        if level is None or not any(design_overall.below(row.get('risk'), level) for row in rows):
            continue
        lifted = [level if design_overall.below(row.get('risk'), level) else row.get('risk') for row in rows]
        unit = {name: sample.get(name) for name in UNIT_KEYS if name in sample}
        if len(set(lifted)) != 1:
            # one review is above the floor: the chief chooses between the two, never below the floor
            worksheet.append({'unit': unit, 'conflicts': [], 'program_resolution': 'design_floor_open', 'floor': level,
                              'reviews': [row.get('risk') for row in rows], 'basis': basis['relation']})
            continue
        target = by_key.get(key)
        if target is None:
            target = deepcopy(sample)
            target['review_refs'] = dict(refs)
            target['adjudication_reasoning'] = ''
        elif str(target.get('adjudication_reasoning') or '').strip() and not design_overall.below(target.get('risk'), level):
            continue
        original = [str(row.get('risk')) for row in rows]
        cited = [ref for row in rows for argument in (row.get('counter_evidence') or []) + (row.get('supporting_evidence') or [])
                 if isinstance(argument, dict) for ref in argument.get('evidence_refs') or [] if isinstance(ref, str)]
        cited = list(dict.fromkeys(cited or basis['evidence_refs']))
        reasoning = design_overall.floor_reasoning(level, basis, original)
        target.update(risk=level, assessment_status='assessed', evidence_confidence='中')
        target.pop('pending_reasoning', None)
        target['supporting_evidence'] = [{'reasoning': reasoning, 'evidence_refs': cited},
                                         *[arg for arg in target.get('supporting_evidence') or [] if isinstance(arg, dict)]]
        target['evidence_refs'] = list(dict.fromkeys([*target.get('evidence_refs', []), *cited]))
        target['reasoning'] = reasoning + '两审原理由：' + str(target.get('reasoning') or '')
        target['lower_if'] = list(dict.fromkeys([*target.get('lower_if', []),
            '实物或补充视图显示产品主体造型与授权附图的实线主体明显不同时，可下调。']))
        target['adjudication_reasoning'] = ('按外观评级规则（design-overall-v1）：比对记录（%s）认定%s，两审原评%s，'
            '低于该主体关系对应的%s，主审按规则定为%s、置信度中。' % (basis['comparison_event_id'],
                design_overall.RELATION_TEXT[basis['relation']], '／'.join(original), level, level))
        if key not in by_key:
            decisions.append(target)
            by_key[key] = target
        settled += 1
        lifted_scopes.setdefault((sample.get('scenario_id'), sample.get('jurisdiction')), []).append(
            str(target.get('title') or target.get('candidate_id')))
        worksheet.append({'unit': unit, 'conflicts': [], 'program_resolution': design_overall.FLOOR_RESOLUTION,
                          'floor': level, 'reviews': original, 'basis': basis['relation']})
    # best-estimate-risk-v2 convention: a whole-scope row whose risk a graded candidate now decides stays pending with one
    # plain sentence, instead of repeating the reviews' low-risk wording next to the lifted candidate
    for (scenario, country), names in lifted_scopes.items():
        for key, rows in index.items():
            sample = rows[0]
            if (sample.get('candidate_id') or sample.get('right_type') != 'design' or sample.get('scenario_id') != scenario
                    or sample.get('jurisdiction') != country or (sample.get('assessment_object') or 'product') != 'product'
                    or sample.get('out_of_scope') or not all(row.get('risk') in {'极低', '低'} for row in rows)):
                continue
            target = by_key.get(key)
            if target is None:
                target = deepcopy(sample)
                target['review_refs'] = dict(refs)
                decisions.append(target)
                by_key[key] = target
            elif str(target.get('adjudication_reasoning') or '').strip():
                continue
            target.update(risk=None, assessment_status='pending',
                          pending_reasoning='该范围风险由候选%s决定。' % '、'.join(names))
            target['adjudication_reasoning'] = ('按外观评级规则（design-overall-v1）：同范围候选%s已按主体关系定级，'
                                                '整体行改为由该候选决定，不再沿用两审的低风险表述。' % '、'.join(names))
            worksheet.append({'unit': {name: sample.get(name) for name in UNIT_KEYS if name in sample}, 'conflicts': [],
                              'program_resolution': design_overall.FLOOR_RESOLUTION + ':scope_subsumed'})
    return settled


def _auto_complete(task, evidence, decisions, left, right, refs, worksheet, task_dir=None):
    """--auto-agree: settle decision rows the two reviews already agree on, and apply the v2 极高 rule.

    A row is settled only when both reviewers gave the same grade and status; anything else stays open
    (empty adjudication_reasoning) for the chief. Returns (auto_agreed, extreme_applied).
    r5d20 (design-overall-v1): a design row is first held to the floor of its recorded main-body relation."""
    from assessment_estimate import _inactive_conditional_scenario, best_estimate_v2
    agreed = extreme = 0
    def key_of(row):
        return tuple(row.get(name) for name in UNIT_KEYS)
    index = {}
    for side in (left, right):
        for row in side.values():
            index.setdefault(key_of(row), []).append(row)
    by_key = {key_of(row): row for row in decisions}
    import design_overall
    if design_overall.enabled(task):
        agreed += _design_floor(task, task_dir, decisions, index, by_key, refs, worksheet, key_of)
    import report_always
    if report_always.enabled(task):
        agreed += _utility_cap(task, decisions, index, by_key, refs, worksheet, key_of)
    if best_estimate_v2(task):
        for key, rows in index.items():
            sample = rows[0]
            if (not sample.get("candidate_id") or sample.get("right_type") not in {"patent", "utility_model"}
                    or len(rows) != 2 or not all(row.get("risk") in {"高", "极高"} for row in rows)):
                continue
            target = by_key.get(key)
            if target is None:
                target = deepcopy(sample)
                target["review_refs"] = dict(refs)
                target["adjudication_reasoning"] = ""
            applies, reasons, assumptions = extreme_rule(task, evidence, target)
            if not applies or (target.get("risk") == "极高" and target.get("adjudication_reasoning")):
                continue
            target.update(risk="极高", assessment_status="assessed", evidence_confidence="高")
            target.pop("pending_reasoning", None)
            target["assumptions"] = list(dict.fromkeys([*target.get("assumptions", []), *assumptions]))
            original = [str(row.get("risk")) for row in rows]
            target["reasoning"] = ("专利现行有效、商品页面标注专利、独立权利要求要素与产品对应或与已见结构一致，定为极高风险"
                                   + ("（两审原评" + "／".join(original) + "，按规则上调）" if "极高" not in original or len(set(original)) > 1 else "")
                                   + "。审阅理由：" + str(target.get("reasoning") or ""))
            target["adjudication_reasoning"] = ("按best-estimate-risk-v2极高规则：" + "；".join(reasons)
                + "。两审原评" + "／".join(str(row.get("risk")) for row in rows) + "，主审按规则定极高、置信度高。")
            if key not in by_key:
                decisions.append(target)
                by_key[key] = target
            extreme += 1
            worksheet.append({"unit": {name: target.get(name) for name in UNIT_KEYS if name in target},
                              "conflicts": [], "program_resolution": "extreme_rule_v2", "reasons": reasons})
    import pipeline_robust
    robust = pipeline_robust.enabled(task)
    for decision in decisions:
        if decision.get("adjudication_reasoning"):
            continue
        rows = index.get(key_of(decision), [])
        # r5d15 (B0GLNPC6K8): the second review added the optional own-brand word / logo rows as pending (no brand
        # name or logo was supplied), the first left them out, and checkpoint 3 stopped for two rows on which no grade
        # can be given. A unit only one review lists, with no candidate and no grade, is carried as pending.
        if (robust and len(rows) == 1 and not rows[0].get("candidate_id") and rows[0].get("risk") is None
                and rows[0].get("assessment_status") == "pending" and str(rows[0].get("pending_reasoning") or "").strip()
                and decision.get("risk") is None):
            decision["adjudication_reasoning"] = (
                "该单元只有一份终审列出，且为待判断、未定等级（" + str(rows[0]["pending_reasoning"]).strip()
                + "）；另一份终审未列此单元。没有可比较的等级，主审照录为待判断，不赋予风险等级。")
            agreed += 1
            continue
        # r5d19 (B0H16FDSD8): rows of a conditional scenario the task never activated may now be out of scope (bound
        # to the task's own record). One review may say so while the other leaves the row pending; neither gives a
        # grade, so there is nothing for the chief to weigh and the drafted row is carried as it is.
        if (robust and len(rows) == 2 and decision.get("risk") is None and all(row.get("risk") is None for row in rows)
                and any(row.get("out_of_scope") is True for row in rows)
                and all(row.get("out_of_scope") is True or row.get("assessment_status") == "pending" for row in rows)
                and _inactive_conditional_scenario(decision, task)):
            labels = ["未纳入范围" if row.get("out_of_scope") is True else "待判断" for row in rows]
            decision["adjudication_reasoning"] = (
                "两审都未给等级（" + "／".join(labels) + "）；该条件情景未被本任务启用，没有必做工作，也没有可比较的等级。"
                "主审照录为" + ("未纳入范围" if decision.get("out_of_scope") is True else "待判断") + "，不赋予风险等级。")
            agreed += 1
            continue
        if (len(rows) != 2 or rows[0].get("risk") != rows[1].get("risk")
                or rows[0].get("assessment_status") != rows[1].get("assessment_status")):
            continue
        risk, status = rows[0].get("risk"), rows[0].get("assessment_status")
        confidence = _lower(rows[0].get("evidence_confidence"), rows[1].get("evidence_confidence"))
        if decision.get("risk") is None and risk is not None:
            # a drafted claims table row: carry the agreed grade into it
            decision.update(risk=risk, assessment_status=status)
            decision.pop("pending_reasoning", None)
        if confidence:
            decision["evidence_confidence"] = confidence
        claims = (decision.get("comparison") or {}).get("claims")
        from_review = bool(claims) and any(((row.get("comparison") or {}).get("claims") == claims) for row in rows) \
            and any(not _independent_claims(row) for row in rows)
        decision["adjudication_reasoning"] = ("两审等级一致（" + (risk or "待定") + ("／置信度" + confidence if confidence else "")
            + "），差异只在依据字段或比较表细节；主审采纳一致等级" + (
                "并采用两审中给出的权利要求对照表" if from_review else
                "并补入专项比较登记的权利要求对照表" if claims else "") + "。")
        agreed += 1
    return agreed, extreme


def _single_review(task, left, right):
    """r6 (report-always-v1): the one review row that has a usable judgment when the other chain's row is a program
    pending row (its module had no usable answer, or the row could not stand); None otherwise."""
    import report_always
    if not report_always.enabled(task) or not left or not right:
        return None
    from module_repair import PENDING_TEXT
    def unusable(row):
        return row.get("pending_basis") in PENDING_TEXT and row.get("risk") is None
    if unusable(left) and not unusable(right):
        return right
    if unusable(right) and not unusable(left):
        return left
    return None


def build(task_dir: Path, first_path: Path, second_path: Path, *, reviewer: str = "", session_id: str = "",
          draft_selected_candidates: bool = False, auto_agree: bool = False):
    from assessment_estimate import _review_scope_key, _row_conflicts, validate_product_scope_coverage
    from review_readiness import current_digest
    task_dir = Path(task_dir).resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    digest = current_digest(task_dir)
    reviews = {}
    for label, path in (("first", first_path), ("second", second_path)):
        review = ensure_object(load_json(Path(path)), label + " review")
        context = review.get("review_context")
        if not isinstance(context, dict) or context.get("evidence_digest") != digest:
            raise ValueError("PREPARE_ADJUDICATION_REVIEW_STALE: " + label + " (re-run the final review for the current inputs)")
        validate_product_scope_coverage(review.get("assessments", []), task,
            error_code="PREPARE_ADJUDICATION_PRODUCT_SCOPE_MISSING:" + label)
        reviews[label] = review
    left = {_review_scope_key(row, task): row for row in reviews["first"]["assessments"]}
    right = {_review_scope_key(row, task): row for row in reviews["second"]["assessments"]}
    refs = {"first": sha256_json(reviews["first"]), "second": sha256_json(reviews["second"])}
    decisions, worksheet, counts = [], [], {}
    for key in sorted(set(left) | set(right), key=str):
        conflicts = (_row_conflicts(left[key], right[key], task) if key in left and key in right
                     else ["review_scope_missing"])
        chosen = left.get(key) or right[key]
        # A chosen row carrying an applicability exception always needs the chief, even without a conflict.
        needs = bool(conflicts) or bool(chosen.get("applicability_exception"))
        if not needs:
            continue
        for name in conflicts:
            counts[name] = counts.get(name, 0) + 1
        single = _single_review(task, left.get(key), right.get(key))
        if single is not None:
            chosen = single      # r6: the draft starts from the review that has a usable judgment
        draft = deepcopy(chosen)
        _adopt_claims_table(draft, right.get(key) if chosen is left.get(key) else left.get(key))
        draft["adjudication_reasoning"] = ""
        draft["review_refs"] = dict(refs)
        decisions.append(draft)
        worksheet.append({"unit": {name: chosen.get(name) for name in UNIT_KEYS if name in chosen},
            "conflicts": conflicts or ["applicability_exception_requires_chief"],
            "first": _summary(left[key]) if key in left else None,
            "second": _summary(right[key]) if key in right else None,
            **({"other_review_unavailable": "first" if single is right.get(key) else "second",
                "chief_note": ("另一审阅链的这一行没有可用的终审结论（程序已按待定处理，原因见该审的 pending_reasoning）；"
                               "草稿取自有结论的这一审，主审核对后填写等级、状态和理由，或改判。")}
               if single is not None else {})})
    drafts = []
    if draft_selected_candidates:
        drafts, draft_notes = _selected_candidate_drafts(task, left, right, refs)
        decided = {tuple(row.get(name) for name in UNIT_KEYS) for row in decisions}
        for draft in drafts:
            key = tuple(draft.get(name) for name in UNIT_KEYS)
            if key in decided:
                # the conflict draft already exists for this unit: enrich it with the claims table instead
                for row in decisions:
                    if tuple(row.get(name) for name in UNIT_KEYS) == key:
                        row["comparison"] = draft["comparison"]
                        row["evidence_refs"] = draft["evidence_refs"]
            else:
                decisions.append(draft)
        worksheet.extend({"unit": note["unit"], "conflicts": [], "selected_candidate_draft": note} for note in draft_notes)
    auto = {}
    if auto_agree:
        evidence = load_json(task_dir / "evidence.json")
        agreed, extreme = _auto_complete(task, evidence, decisions, left, right, refs, worksheet, task_dir=task_dir)
        auto = {"auto_agreed": agreed, "extreme_rule_applied": extreme}
    # Every evidence id a drafted row cites in a nested field (a projected claims table carries element product images
    # and claim texts) is part of its roll-up; the row validator refuses the decision otherwise (r6 replay of run
    # B0GFNWR8FW: ROW_EVIDENCE_REFS_MUST_INCLUDE_ARGUMENT_REFS at publication). Only ids the row already cites are added.
    from module_review import row_evidence_ref_additions
    for row in decisions:
        extra = row_evidence_ref_additions(row)
        if extra:
            row["evidence_refs"] = [*row["evidence_refs"], *extra]
    adjudication = {"reviewer": reviewer, "review_context": {"session_id": session_id, "evidence_digest": digest},
                    "review_refs": refs, "decisions": decisions}
    return adjudication, {"schema": "IPR-ADJUDICATION-WORKSHEET/1.0", "evidence_digest": digest,
                          "units_total": len(set(left) | set(right)), "units_requiring_decision": len(decisions),
                          "open_decisions": sum(1 for row in decisions if not str(row.get("adjudication_reasoning") or "").strip()),
                          **auto, "conflict_field_counts": dict(sorted(counts.items())), "units": worksheet}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path)
    parser.add_argument("--second-review", type=Path)
    parser.add_argument("--output", type=Path, help="Skeleton path; default TASK/adjudication.json (never overwritten)")
    parser.add_argument("--worksheet", type=Path, help="Worksheet path; default TASK/adjudication-worksheet.json")
    parser.add_argument("--reviewer", default="", help="Chief reviewer name; left empty when omitted")
    parser.add_argument("--session-id", default=os.environ.get("CODEX_THREAD_ID", ""),
                        help="Chief session id; default $CODEX_THREAD_ID, empty when unset")
    parser.add_argument("--draft-selected-candidates", action="store_true",
                        help="Also draft a decision row for every selected patent/utility-model candidate with the recorded "
                             "independent-claim comparison projected into comparison.implementations/claims (risk left null)")
    parser.add_argument("--auto-agree", action="store_true",
                        help="Settle rows both reviews grade identically (reasoning written for the chief to sign) and, "
                             "under best-estimate-risk-v2, apply the 极高 rule on frozen facts; other rows stay open")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    first = args.first_review or task_dir / "first-review.json"
    second = args.second_review or task_dir / "second-review.json"
    output = args.output or task_dir / "adjudication.json"
    sheet = args.worksheet or task_dir / "adjudication-worksheet.json"
    if output.exists() or sheet.exists():
        parser.error("refusing to overwrite an existing adjudication or worksheet; choose new paths")
    adjudication, worksheet = build(task_dir, first, second, reviewer=args.reviewer, session_id=args.session_id,
                                    draft_selected_candidates=args.draft_selected_candidates,
                                    auto_agree=args.auto_agree)
    atomic_write_json(output, adjudication)
    atomic_write_json(sheet, worksheet)
    print(json.dumps({"adjudication": str(output), "worksheet": str(sheet),
                      "units_total": worksheet["units_total"],
                      "units_requiring_decision": worksheet["units_requiring_decision"],
                      "conflict_field_counts": worksheet["conflict_field_counts"],
                      "open_decisions": worksheet["open_decisions"],
                      **{key: worksheet[key] for key in ("auto_agreed", "extreme_rule_applied") if key in worksheet},
                      "still_required": [name for name, value in (("reviewer", adjudication["reviewer"]),
                          ("review_context.session_id", adjudication["review_context"]["session_id"])) if not value]
                      + (["adjudication_reasoning for every open decision", "final risk/evidence in each open decision row"]
                         if worksheet["open_decisions"] else [])}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
