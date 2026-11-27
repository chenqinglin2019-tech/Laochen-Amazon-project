"""要紧项复核（R-007）：评为中及以上、或标"拿不准"的，另开一个看不到第一次结论的会话再比一遍。
几件放在同一个会话里；两次不一致取较高的等级，两种看法都留在报告里。复核没成的保留第一次结论并标"未复核"。"""
from __future__ import annotations

from .. import config, images as image_tools, prompts, sheets
from ..outcome import StepFailed
from .compare import COMPARE_IMAGES, design_sheet, read_items
from .screen import product_pictures


def needs_recheck(finding: dict) -> bool:
    if finding.get("status") != "compared" or finding.get("recheck"):
        return False
    return finding.get("uncertain") or config.risk_rank(finding["risk"]) >= config.risk_rank(config.RECHECK_FROM)


def label_of(finding: dict) -> str:
    return "%s %s 的复核" % (finding["number"], finding["title"])


def run(ctx) -> None:
    task = ctx.task
    todo = [f for f in task["findings"] if needs_recheck(f)]
    if not todo:
        ctx.say("  复核：没有中及以上或拿不准的，不开复核会话")
        return
    # 风险高的先复核；每单最多复核 RECHECK_CAP 件。
    todo.sort(key=lambda f: -config.risk_rank(f["risk"]))
    opened = sum(1 for f in task["findings"] if (f.get("recheck") or {}).get("status") in ("done", "failed"))
    room = max(0, config.RECHECK_CAP - opened)
    chosen, rest = todo[:room], todo[room:]
    order = {id(finding): index for index, finding in enumerate(task["findings"])}
    chosen.sort(key=lambda finding: order[id(finding)])  # 发给 AI 时按原来的先后排，不让排队顺序透露第一次评得高还是低
    live = getattr(ctx.sources, "live", False)
    for finding in rest:
        finding["recheck"] = {"status": "skipped", "reason": "超出每单复核上限（%d 件），未复核" % config.RECHECK_CAP}
        task.add_incomplete(label_of(finding), finding["recheck"]["reason"], finding["right_type"])
    if not chosen:
        ctx.say("  复核：需要 %d 件，都超出了每单上限" % len(todo))
        return

    def failed(finding: dict, why: str) -> None:
        finding["recheck"] = {"status": "failed", "reason": "复核没有完成（%s），保留第一次结论" % why}
        task.add_incomplete(label_of(finding), finding["recheck"]["reason"], finding["right_type"])

    if ctx.usage.should_wrap_up():
        for finding in chosen:
            failed(finding, "到达本单的时间或 token 收口线")
        ctx.say("  复核：到达收口线，%d 件没有复核" % len(chosen))
        return
    pairs, boards, sheet_labels, broken = [], [], [], 0
    for finding in chosen:  # 外观要看图：把比对时拼好的附图带上；图找不到的不送去复核，免得 AI 没看图就下结论
        sheet = config.inside(task.dir, finding["sheet"]) if finding.get("sheet") else None
        seen = sheet is not None and image_tools.readable(sheet)
        if finding["right_type"] == "design" and live and not seen and sheets.available():
            try:  # 比对时拼好的图不见了：用留下的附图重拼一张；拼不成的按没有图处理
                sheet = design_sheet(task, "R%d" % (len(pairs) + 1), finding)
            except Exception:
                sheet = None
            seen = sheet is not None and image_tools.readable(sheet)
        if finding["right_type"] == "design" and live and not seen:
            failed(finding, "附图找不到了，没法复核")
            broken += 1
            continue
        label = "R%d" % (len(pairs) + 1)
        pairs.append((label, finding))
        if seen:
            boards.append(sheet)
            sheet_labels.append("%s（%s）" % (label, finding["number"]))
    if not pairs:
        raise StepFailed("复核有 %d 件没有做成（附图找不到了）" % broken)
    pictures = product_pictures(task, COMPARE_IMAGES)
    try:
        answer = ctx.ai.ask("recheck", "recheck", prompts.recheck(task, pairs, len(pictures), sheet_labels), images=pictures + boards,
                            schema=prompts.RECHECK_SCHEMA, tier="strong", image_max_px=config.SHEET_MAX_PX if boards else None)
        rows = read_items(answer, pairs)
    except StepFailed as exc:
        for _label, finding in pairs:
            failed(finding, exc.message)
        ctx.say("  复核：需要 %d 件，会话没有成（%s）" % (len(todo), exc.message))
        raise StepFailed("复核会话没有成（%s），已保留第一次的结论；再运行一次同样的命令会重试" % exc.message)
    for label, finding in pairs:
        row = rows.get(label) or {}
        if row.get("risk") not in config.RISK_ORDER:
            failed(finding, "AI 没有给出这一件的结论")
            continue
        first = finding["risk"]
        finding["recheck"] = {
            "status": "done",
            "first_risk": first,
            "second_risk": row["risk"],
            "second_basis": str(row.get("basis") or ""),
            "agree": row["risk"] == first,
        }
        # 两次不一致取较高的等级，两种看法都留在报告里。
        if config.risk_rank(row["risk"]) > config.risk_rank(first):
            finding["risk"] = row["risk"]
    task.save()
    done = sum(1 for f in chosen if f["recheck"]["status"] == "done")
    ctx.say("  复核：需要 %d 件，完成 %d 件" % (len(todo), done))
    if done < len(chosen):  # 有漏答或缺图的：这一步算没做完，同一条命令续跑时只重试没成的
        raise StepFailed("复核有 %d 件没有做成，已保留第一次的结论；再运行一次同样的命令会重试" % (len(chosen) - done))
