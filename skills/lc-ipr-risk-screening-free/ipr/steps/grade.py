"""定级（R-008 的数据部分）：纯程序。每类权利一行，再合成总评。
只要这一类还有缺口（有检索没查成、初筛没完成、入选的没比完、看不清、超上限），就不评低，写待定并说明；
已经比出中及以上的照常显示，只降置信度。"""
from __future__ import annotations

from .. import config, outcome
from .search import route_state


def lower(confidence: str) -> str:
    index = config.CONFIDENCE_ORDER.index(confidence) if confidence in config.CONFIDENCE_ORDER else 0
    return config.CONFIDENCE_ORDER[max(0, index - 1)]


def confidence_rank(confidence: str) -> int:
    return config.CONFIDENCE_ORDER.index(confidence) if confidence in config.CONFIDENCE_ORDER else 0


def top_finding(findings: list) -> dict:
    """等级最高的一件；并列时取置信度最低的。"""
    return sorted(findings, key=lambda f: (-config.risk_rank(f["risk"]), confidence_rank(f.get("confidence", ""))))[0]


def decision_of(cand: dict) -> str:
    return (cand.get("screen") or {}).get("decision", "")


def grade_right(task, right_type: str) -> dict:
    row = {"right_type": right_type, "name": config.RIGHT_NAMES[right_type]}
    reason = config.NOT_APPLICABLE.get((task.country, right_type))
    if reason:
        row.update(state="not_applicable", risk="", confidence="", basis=reason)
        return row

    if not task.step_done("search"):  # 检索这一步没做完：不管留下了什么，一律算没检索
        row.update(state="not_searched", risk=config.RISK_PENDING, confidence="", basis="检索这一步没有完成")
        return row

    routes = [s for s in task["searches"] if s.get("route") == right_type]
    main_routes = [s for s in routes if not s.get("optional")]  # 辅助来源没查成不算这类权利的缺口
    failed_routes = [s for s in main_routes if s.get("status") != "ok"]
    cut_routes = [s for s in main_routes if s.get("status") == "ok" and s.get("truncated")]
    candidates = [c for c in task["candidates"] if c["right_type"] == right_type]
    selected = [c for c in candidates if decision_of(c) == "selected"]
    compared = [f for f in task["findings"] if f["right_type"] == right_type and f["status"] == "compared"]

    if route_state(task, right_type) != "ok" and not compared:
        why = "；".join(sorted({s.get("reason", "") for s in routes if s.get("reason")})) or "这一类没有可用的检索来源，本次没有检索"
        row.update(state="not_searched", risk=config.RISK_PENDING, confidence="", basis=why)
        return row

    # 缺口：只要有一条，这一类就不能评低。
    gaps = []
    if not routes:
        gaps.append("这一类没有做检索，只比对了从产品上看出来的权利")
    elif not main_routes:
        gaps.append("主要的那一路检索没有做，只有辅助来源的结果")
    elif failed_routes:
        untouched = sorted({s.get("reason", "") for s in failed_routes if s.get("status") == "skipped" and "未检索" in s.get("reason", "")})
        gaps.append("%d 路检索里 %d 路没查成" % (len(main_routes), len(failed_routes)) + ("（%s）" % "；".join(untouched) if untouched else ""))
    if cut_routes:
        gaps.append("有 %d 路检索命中太多、只取了前面一部分" % len(cut_routes))
    if task["understanding"].get("fallback"):
        gaps.append("产品理解没有完成、检索词取自标题")
    screened = all(decision_of(c) for c in candidates)  # 文字、看图两批各管各的：这一类的候选都有了决定就算筛完
    if not screened:
        gaps.append("初筛没有完成")
    if len(compared) < len(selected):
        gaps.append("%d 件入选的没有比完" % (len(selected) - len(compared)))
    unseen = sum(1 for c in candidates if decision_of(c) == "unseen") if screened else 0
    if unseen:
        gaps.append("%d 件看不清、未能比对" % unseen)
    unsure = sum(1 for f in compared if f.get("uncertain") and (f.get("recheck") or {}).get("status") != "done")
    if unsure:
        gaps.append("%d 件拿不准的没有复核" % unsure)
    below = config.risk_rank(config.RECHECK_FROM)
    partial = sum(1 for f in compared if f.get("material_limit") and config.risk_rank(f["risk"]) < below)
    if partial:  # 只读到一部分权利要求、只看到一张附图就说不像：复核看的也是同一份残缺材料，不能当成比过
        gaps.append("%d 件材料不全、评低不可靠" % partial)
    skipped_look = sum(1 for c in candidates if decision_of(c) == "over_cap" and "初筛" in (c.get("screen") or {}).get("reason", ""))
    over_cap = sum(1 for c in candidates if decision_of(c) == "over_cap") - skipped_look
    if skipped_look:
        gaps.append("%d 件超出本轮初筛上限、没有看" % skipped_look)
    if over_cap:
        gaps.append("%d 件超出本轮深查上限" % over_cap)
    # 没读到公开页的，或者读到了却没解析出摘要和权利要求的发明：AI 手里只有标题
    title_only = sum(1 for c in candidates if right_type in ("patent", "utility_model") and decision_of(c) in ("not_selected", "watch") and (
        c.get("page_note") or (c.get("enriched") and not (c.get("claim1") or c.get("abstract")))))  # 外观是看图筛的，不算这一条
    if title_only:
        gaps.append("%d 件没读到权利要求、只凭标题判的" % title_only)
    gap_text = "、".join(gaps)

    if compared:
        top = top_finding(compared)
        basis = "入选 %d 件，已比对 %d 件，最高的是 %s（%s）" % (len(selected), len(compared), top["number"] or top["title"], top["risk"])
        blind = sum(1 for f in compared if f.get("blind") and config.risk_rank(f["risk"]) < below)  # 复核抬到中以上的不再这么说
        if blind:
            basis += "；其中 %d 件的要素从照片上一个都看不到，评低只是因为没看到对应，需要拿样品核对" % blind
            row["blind"] = blind
        if not gaps:
            row.update(state="checked", risk=top["risk"], confidence=top["confidence"] or config.CONFIDENCE_ORDER[0], basis=basis)
        elif config.risk_rank(top["risk"]) >= config.risk_rank(config.RECHECK_FROM):
            row.update(state="checked", risk=top["risk"], confidence=lower(top["confidence"]), basis="%s；另有 %s" % (basis, gap_text),
                       gapped=True)
        else:
            row.update(state="checked", risk=config.RISK_PENDING, confidence="", basis="%s；但 %s，不能据此判断为低" % (basis, gap_text))
    elif gaps and candidates and screened and not (unseen or over_cap or skipped_look or title_only):
        # 查到的都筛过了、没有要深查的，只是还有别的没查到：把两头都说清楚
        row.update(state="checked", risk=config.RISK_PENDING, confidence="",
                   basis="检索到 %d 件候选，初筛后没有需要深查的；但%s，不能据此判断为低" % (len(candidates), gap_text))
    elif gaps:
        row.update(state="checked", risk=config.RISK_PENDING, confidence="",
                   basis="检索到 %d 件候选，%s，无法判断" % (len(candidates), gap_text))
    else:
        row.update(state="checked", risk=config.RISK_LOW, confidence=config.CONFIDENCE_ORDER[1],
                   basis="检索到 %d 件候选，初筛后没有需要深查的" % len(candidates))
        if not candidates and main_routes and all(s.get("empty") for s in main_routes):
            row.update(nothing=True, basis="没有需要查的词，没有检索")  # 这一行的"低"不是查出来的
    return row


ADVICE = {
    "极高": "不建议上架。先人工核对下面的风险项。",
    "高": "不建议上架。先人工核对下面的风险项。",
    "中": "暂缓上架。人工核对下面的风险项后再定。",
    "低": "已查的部分没有发现中高风险，可以上架。",
    "极低": "已查的部分没有发现风险，可以上架。",
}


def run(ctx) -> None:
    task = ctx.task
    rows = [grade_right(task, right) for right in config.RIGHT_TYPES]
    task["rights_summary"] = rows

    rated = [r for r in rows if r["state"] == "checked" and r["risk"] in config.RISK_ORDER]
    gaps = [r["name"] for r in rows if r["state"] == "not_searched" or (r["state"] == "checked" and r["risk"] == config.RISK_PENDING)]
    if not [r for r in rated if not r.get("nothing")]:  # 评出等级的行里没有一行是真的查过的
        task["overall"] = {"risk": config.RISK_PENDING, "confidence": "", "partial": True,
                           "advice": "没有任何一类权利完成排查，无法判断。暂缓上架。"}
    else:
        top = sorted(rated, key=lambda r: (-config.risk_rank(r["risk"]), confidence_rank(r["confidence"])))[0]
        unfinished = (getattr(ctx, "result", None) or {}).get("kind", outcome.DONE) != outcome.DONE
        partial = bool(gaps or task["incomplete"] or unfinished)
        # 这一行自己已经因为缺口降过一次的，不再降第二次。
        confidence = lower(top["confidence"]) if partial and not top.get("gapped") else top["confidence"]
        advice = ADVICE[top["risk"]]
        if partial and config.risk_rank(top["risk"]) < config.risk_rank(config.RECHECK_FROM):
            advice = "已查的部分没有发现中高风险，但%s没有查完，不能据此当作低风险。暂缓上架，补查后再定。" % ("、".join(gaps) or "有些项目")
        elif gaps:
            advice += "另外%s没有查完。" % "、".join(gaps)
        blind = sum(r.get("blind", 0) for r in rows)
        if blind:
            advice += "另有 %d 件专利的要素从照片上看不到，上架前建议拿样品核对。" % blind
        task["overall"] = {"risk": top["risk"], "confidence": confidence, "partial": partial, "advice": advice}
    ctx.say("  总评：%s%s，置信度 %s" % (task["overall"]["risk"], "（仅就已查部分）" if task["overall"].get("partial") else "",
                                    task["overall"]["confidence"] or "—"))
