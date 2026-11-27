"""检索（R-004）：各路检索的记录和候选清单。哪一路没查成如实记下，不影响其他路。"""
from __future__ import annotations

from .. import config
from ..outcome import StepFailed


def run(ctx) -> None:
    task = ctx.task
    task["searches"], task["candidates"] = [], []
    found = ctx.sources.search(ctx)
    if (not isinstance(found, dict) or not isinstance(found.get("searches") or [], list)
            or not isinstance(found.get("candidates"), list)):
        raise StepFailed("检索返回的记录或候选清单格式不对")
    candidates, not_applicable, broken = normalize(found["candidates"], task.country)
    task["searches"] = normalize_searches(found.get("searches") or [])
    task["candidates"] = candidates
    task["lens"] = [m for m in found.get("lens") or [] if isinstance(m, dict)][:30]
    task["enforcement"] = [m for m in found.get("enforcement") or [] if isinstance(m, dict)][:16]
    task["search_notes"] = [str(n) for n in found.get("notes") or [] if n]
    if not_applicable:
        ctx.say("  有 %d 件候选属于%s不存在的权利类型，已剔除" % (not_applicable, config.COUNTRIES[task.country]["name"]))
    if broken:
        task.add_incomplete("%d 件检索结果" % broken, "记录不完整或权利类型认不出，没有处理")
    for search in task["searches"]:
        if search.get("status") == "ok" and search["truncated"] and not search["optional"]:
            task.add_incomplete("%s检索（%s）" % (config.RIGHT_NAMES.get(search.get("route"), search.get("route", "")), search.get("source", "")),
                                "命中的比取回的多：%s" % search.get("count", ""), search.get("route", ""))
        if search.get("status") != "ok" and not search["optional"]:  # 辅助来源没查成：检索记录里照样写着，但不算"没查完"
            task.add_incomplete(
                "%s检索（%s）" % (config.RIGHT_NAMES.get(search.get("route"), search.get("route_name") or search.get("route", "")), search.get("source", "")),
                search.get("reason") or "没有查成",
                search.get("route", ""),
            )
    ok = sum(1 for s in task["searches"] if s.get("status") == "ok")
    counts = {}
    for cand in candidates:
        counts[cand["right_type"]] = counts.get(cand["right_type"], 0) + 1
    ctx.say("  检索 %d 条已查、%d 条没有查，候选 %d 件（%s）" % (ok, len(task["searches"]) - ok, len(candidates),
            "，".join("%s %d" % (config.RIGHT_NAMES[k], v) for k, v in counts.items()) or "无"))


TEXT_FIELDS = ("number", "title", "owner", "filing_date", "grant_date", "priority_date", "url", "snippet", "source",
               "legal_status", "expiry", "image_location", "matched_term", "office")
LIST_FIELDS = ("figures", "classes", "cpc", "via")


def normalize(candidates, country: str):
    """外部来的候选记录先整理：缺的字段补空字符串；目的国不存在的权利剔除（不为它们开 AI 会话）；
    记录不完整或类型认不出的单独计数，由调用方记进"没查完"。返回 (留下的, 不适用的件数, 有问题的件数)。"""
    kept, not_applicable, broken, seen = [], 0, 0, set()
    for cand in candidates:
        if (not isinstance(cand, dict) or not isinstance(cand.get("id"), str) or not cand["id"]
                or not isinstance(cand.get("right_type"), str) or cand["right_type"] not in config.RIGHT_TYPES):
            broken += 1
            continue
        if cand["id"] in seen:  # 同一件重复出现，留第一件
            continue
        right = cand["right_type"]
        if (country, right) in config.NOT_APPLICABLE:
            not_applicable += 1
            continue
        for field in TEXT_FIELDS:
            value = cand.get(field)
            cand[field] = "" if value is None else str(value)
        for field in ("pages", "figures_from", "figures_to"):
            cand[field] = cand[field] if isinstance(cand.get(field), int) and not isinstance(cand.get(field), bool) else 0
        cand["watchlist"] = cand.get("watchlist") is True
        for field in LIST_FIELDS:
            cand[field] = [str(f) for f in cand[field] if f] if isinstance(cand.get(field), list) else []
        cand.pop("screen", None)  # 初筛结果只由初筛这一步写
        seen.add(cand["id"])
        kept.append(cand)
    return kept, not_applicable, broken


def normalize_searches(searches: list) -> list:
    """检索记录同样先整理：只留字典，字段转成文字，状态只认 ok / failed / skipped。"""
    kept = []
    for search in searches:
        if not isinstance(search, dict):
            continue
        row = {key: ("" if search.get(key) is None else str(search.get(key)))
               for key in ("id", "route", "route_name", "source", "query", "reason", "count")}
        row["status"] = search.get("status") if search.get("status") in ("ok", "failed", "skipped") else "failed"
        if isinstance(search.get("seconds"), (int, float)):
            row["seconds"] = search["seconds"]
        row["optional"], row["truncated"] = search.get("optional") is True, search.get("truncated") is True
        if search.get("empty") is True:
            row["empty"] = True
        kept.append(row)
    return kept


def route_state(task, right_type: str) -> str:
    """某类权利的检索状态：ok（至少一路查成）、failed（有检索但都没成）、none（没有安排检索）。"""
    routes = [s for s in task["searches"] if s.get("route") == right_type]
    if not routes:
        return "none"
    return "ok" if any(s.get("status") == "ok" for s in routes) else "failed"
