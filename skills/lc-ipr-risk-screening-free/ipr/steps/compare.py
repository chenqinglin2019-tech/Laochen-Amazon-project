"""深查比对（R-006）：对入选的取材料后成批比对——发明一个会话、外观一个会话、商标和图案一个会话。
取不到材料或没比成的记为"未能比对"，不评低。等级口径：发明按要素对照表由程序定，外观按主体关系由程序定，商标和图案由 AI 按规则给。"""
from __future__ import annotations

import re

from .. import config, images as image_tools, prompts, sheets
from ..outcome import StepFailed, StopSignal
from .screen import product_pictures

COMPARE_IMAGES = 3       # 比对和复核时给 AI 看几张商品图（初筛只看 2 张）
SHEET_COLUMNS = 3        # 外观附图拼图：一行几张
SHEET_CELL = 420         # 每张附图的格子大小（比初筛的大，看得清细节）
HUMAN_CHECKS = 5
GROUPS = [("patent", ("patent", "utility_model")), ("design", ("design",)), ("marks", ("trademark", "artwork"))]
DESIGN_RISK = {"same_form": "高", "similar": "中", "different": "低"}
VERDICTS = ("match", "absent", "unseen")
MATERIAL_KINDS = ("patent", "utility_model", "design")  # 这几类要先取材料（权利要求、附图）才能比


def blank_finding(cand: dict) -> dict:
    return {
        "candidate_id": cand["id"],
        "right_type": cand["right_type"],
        "number": cand.get("number", ""),
        "title": cand.get("title", ""),
        "owner": cand.get("owner", ""),
        "url": cand.get("url", ""),
        "filing_date": cand.get("filing_date", ""),
        "grant_date": cand.get("grant_date", ""),
        "legal_status": cand.get("legal_status", ""),
        "expiry": cand.get("expiry", ""),
        "selected_reason": (cand.get("screen") or {}).get("reason", ""),
        "detail": cand.get("snippet") or cand.get("watch_note") or "",
        "matched_term": cand.get("matched_term", ""),
        "watchlist": cand.get("watchlist") is True,
        "status": "not_compared",
        "risk": config.RISK_PENDING,
        "confidence": "",
        "basis": "",
        "elements": [],
        "claims": [],
        "differences": "",
        "human_checks": [],
        "uncertain": False,
        "right_images": [],
    }


def label_of(finding: dict) -> str:
    return ("%s %s" % (finding["number"], finding["title"])).strip()


def fail(task, finding: dict, reason: str) -> None:
    finding["reason"] = reason
    task.add_incomplete(label_of(finding), reason, finding["right_type"])


def read_items(answer, pairs: list) -> dict:
    """把回答对回这一批的各件：按编号认，也认号码。返回 {编号: 那一条回答}；回答不成样子抛 StepFailed。"""
    rows = answer.get("items") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        raise StepFailed("比对的回答里没有结论清单")
    def norm(text) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()
    table = {}
    for label, finding in pairs:
        table[norm(label)] = label
        if norm(finding.get("number")):
            table.setdefault(norm(finding["number"]), label)
        table.setdefault(norm(finding["candidate_id"]), label)
    out = {}
    for row in rows:
        label = table.get(norm(row.get("id"))) if isinstance(row, dict) else None
        if label and label not in out:
            out[label] = row
    return out


def common(finding: dict, row: dict) -> None:
    finding.update({
        "status": "compared",
        "confidence": row.get("confidence") if row.get("confidence") in config.CONFIDENCE_ORDER else config.CONFIDENCE_ORDER[0],
        "basis": str(row.get("basis") or ""),
        "differences": str(row.get("differences") or ""),
        "human_checks": [str(item) for item in row.get("human_checks") or [] if item][:HUMAN_CHECKS] if isinstance(row.get("human_checks"), list) else [],
        "uncertain": row.get("uncertain") is True,
    })
    finding.pop("reason", None)


# ---------------- 发明：按要素对照表定级 ----------------
def claim_level(elements: list) -> str:
    """一项独立权利要求的等级：全部对应 → 高；看得到的都对应、有看不到的 → 中；有不对应的，或一个都看不到 → 低。"""
    verdicts = [el["verdict"] for el in elements]
    if "absent" in verdicts:
        return "低"
    if all(verdict == "match" for verdict in verdicts):
        return "高"
    return "中" if "match" in verdicts else "低"


def marked_on_page(task, number: str) -> bool:
    """商品页面或产品本体上有没有标着这件专利的号码（"patent pending"这类不算）。"""
    found = re.search(r"\d{6,}", number or "")  # 只取号码本身，不带末尾的类型码（B2 的 2）
    if not found:
        return False
    product, understanding = task["product"], task["understanding"]
    text = " ".join([str(product.get("title") or ""), str(product.get("description") or "")]
                    + [str(item) for field in ("bullets", "marking") for item in product.get(field) or []]
                    + [str(item) for field in ("text_on_product", "marking") for item in understanding.get(field) or []])
    # 号码要完整出现，三位一组之间可以带逗号、句点或空格；前后不能再连着数字（或再接一组千分位）：
    # 条码、型号、重量里碰巧含这串数字的不算
    digits = found.group(0)
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i:i + 3] for i in range(head, len(digits), 3)]
    pattern = r"(?<!\d)(?<!\d\.)" + r"[,.\s]?".join(groups) + r"(?!\d)(?![.,]\d{3}(?!\d))"
    for hit in re.finditer(pattern, text):
        # 前面紧跟"数字加逗号"：号码自己带分隔符时，多半是更长的一串数字的后半截，不算；
        # 号码自己不带分隔符时，是"10444555,10633217"这种紧凑的列表，算
        joined = re.search(r"\d,$", text[:hit.start()]) is not None
        if not (joined and re.search(r"\D", hit.group(0))):
            return True
    return False


def apply_patent(task, finding: dict, row: dict) -> bool:
    claims = []
    for claim in row.get("claims") if isinstance(row.get("claims"), list) else []:
        raw = claim.get("elements") if isinstance(claim, dict) and isinstance(claim.get("elements"), list) else []
        elements = [{"text": str(el.get("text") or ""), "verdict": el.get("verdict"), "note": str(el.get("note") or "")}
                    for el in raw if isinstance(el, dict) and el.get("verdict") in VERDICTS and el.get("text")]
        number = claim.get("claim") if isinstance(claim, dict) and isinstance(claim.get("claim"), int) and not isinstance(claim.get("claim"), bool) else 0
        if elements and not (number and number in {c["number"] for c in claims}):  # 同一项答了两遍的只算一遍
            claims.append({"number": number, "elements": elements})
    if not claims:
        return False  # 没有逐要素的对照：不能算比过
    given = {c.get("number") for c in finding.get("claims") or []}
    answered = {claim["number"] for claim in claims} & given
    # 给了几项独立权利要求就得比几项：按项号对。项号对不上时，只有 AI 自己从 1 往下挨个编了号（1、2、3…，条数一样）
    # 才按先后算比全；没写项号、重复、或写了别的号的不算——那可能是同一项答了两遍，或者比的不是给它的那几项
    renumbered = sorted(claim["number"] for claim in claims) == list(range(1, len(given) + 1))
    complete = answered == given or len(given) <= 1 or renumbered
    levels = [claim_level(claim["elements"]) for claim in claims]
    if not complete and config.risk_rank(max(levels, key=config.risk_rank)) < config.risk_rank(config.RECHECK_FROM):
        return False  # 只比了其中一部分就说不像：没比的那几项可能正好对得上，不能算比过
    best = max(claims, key=lambda claim: (config.risk_rank(claim_level(claim["elements"])),
                                          sum(1 for el in claim["elements"] if el["verdict"] == "match")))
    risk = claim_level(best["elements"])
    common(finding, row)
    unseen = [el["text"] for el in best["elements"] if el["verdict"] == "unseen"]
    if risk == "高" and finding.get("legal_status") == "有效" and marked_on_page(task, finding["number"]):
        risk = "极高"
        finding["basis"] += " 商品页面上标着这件专利的号码，而且它现行有效。"
    if risk == "低" and unseen and not any(el["verdict"] == "absent" for el in best["elements"]):
        finding["confidence"] = config.CONFIDENCE_ORDER[0]  # 一个要素都看不到：评低但把握很小，交给复核
        finding["uncertain"] = True
    if not finding["human_checks"]:  # AI 没列要核对的事：把看不到的要素列上
        finding["human_checks"] = ["拿样品或向供应商核对：%s" % text for text in unseen][:HUMAN_CHECKS]
    limited(finding)
    finding.update(risk=risk, elements=best["elements"], claim_number=best["number"], claims_compared=len(claims),
                   blind=risk == "低" and all(el["verdict"] == "unseen" for el in best["elements"]))
    return True


def limited(finding: dict) -> None:
    """材料不全的（只读到一段权利要求、只取到一张附图）：结论照给，但标拿不准、把握记低，并写明缺什么。"""
    if finding.get("material_limit"):
        finding["confidence"] = config.CONFIDENCE_ORDER[0]
        finding["uncertain"] = True
        finding["basis"] += " （%s。）" % finding["material_limit"]


def batch_patent(ctx, findings: list) -> list:
    task = ctx.task
    pairs = [("P%d" % (index + 1), finding) for index, finding in enumerate(findings)]
    pictures = product_pictures(task, COMPARE_IMAGES)
    answer = ctx.ai.ask("compare", "compare-patent", prompts.compare_patent(task, pairs, len(pictures)), images=pictures,
                        schema=prompts.COMPARE_PATENT_SCHEMA, tier="strong")
    rows = read_items(answer, pairs)
    return [finding for label, finding in pairs if not (label in rows and apply_patent(task, finding, rows[label]))]


# ---------------- 外观：按主体关系定级 ----------------
def design_sheet(task, label: str, finding: dict):
    """把一件外观的几张附图拼成一张给 AI 看。返回拼图路径；一张都打不开返回 None。"""
    paths = [path for path in (config.inside(task.dir, rel) for rel in finding["right_images"]) if path is not None]  # 路径不出任务目录
    if not paths:
        return None
    blank = []
    dest = task.dir / "sessions" / "sheets" / "compare" / ("%s.jpg" % re.sub(r"[^A-Za-z0-9]", "", finding["number"] or label))
    # 格子上印专利号：比对和复核用的是同一张拼图，两边给这件起的编号不一样，印专利号才不会认错
    name = re.sub(r"[^A-Za-z0-9]", "", finding["number"] or label)
    sheets.grid([("%s-%d" % (name, index + 1), path) for index, path in enumerate(paths)], dest, columns=SHEET_COLUMNS, missing=blank,
                cell=SHEET_CELL)
    return dest if len(blank) < len(paths) else None


def apply_design(task, finding: dict, row: dict) -> bool:
    relation = row.get("relation") if isinstance(row.get("relation"), str) else ""
    if relation == "unseen":
        fail(task, finding, "未能比对：附图看不清或缺少关键视图（%s）" % (str(row.get("basis") or "")[:80] or "AI 没有说明"))
        return True
    if relation not in DESIGN_RISK:
        return False
    common(finding, row)
    risk = DESIGN_RISK[relation]
    if row.get("near_copy") is True:
        if relation == "same_form":
            risk = "极高"
        else:
            finding["uncertain"] = True  # 一边说几乎照抄、一边说主体不同：自相矛盾，交复核
    limited(finding)
    finding.update(risk=risk, relation=relation)
    return True


def batch_design(ctx, findings: list) -> list:
    task = ctx.task
    live = getattr(ctx.sources, "live", False)
    if live and not sheets.available():
        raise StepFailed("没有装图像库 Pillow，没法拼图给 AI 看；请先运行安装脚本")
    pairs, boards = [], []
    for finding in findings:
        label = "D%d" % (len(pairs) + 1)
        if live:
            board = design_sheet(task, label, finding)
            if board is None:
                fail(task, finding, "未能比对：附图打不开")
                continue
            boards.append(board)
            finding["sheet"] = board.relative_to(task.dir).as_posix()
        pairs.append((label, finding))
    if not pairs:
        return []
    pictures = product_pictures(task, COMPARE_IMAGES)
    answer = ctx.ai.ask("compare", "compare-design", prompts.compare_design(task, pairs, len(pictures)), images=pictures + boards,
                        schema=prompts.COMPARE_DESIGN_SCHEMA, tier="strong", image_max_px=config.SHEET_MAX_PX)
    rows = read_items(answer, pairs)
    return [finding for label, finding in pairs if not (label in rows and apply_design(task, finding, rows[label]))]


# ---------------- 商标和图案：AI 按规则给等级 ----------------
def apply_mark(task, finding: dict, row: dict) -> bool:
    if row.get("risk") not in config.RISK_ORDER:
        return False
    common(finding, row)
    risk = row["risk"]
    if finding["right_type"] == "artwork" and finding.get("watchlist") and config.risk_rank(risk) < config.risk_rank("中"):
        # 常见维权方清单点名的图案：这类权利人主张的范围很宽、惯于批量起诉，AI 看不到它的作品原图，不能只凭"题材常见"评低
        risk = "中"
        finding["basis"] += " 这个权利人在常见维权方清单上，惯于对带这类图案的商品批量起诉，所以按“中”处理，请人工核对。"
        note = "对照 %s 的官方图样，确认图案是否落在它主张的范围内；拿不准就换掉这个图案" % (finding.get("owner") or "权利人")
        finding["human_checks"] = ([note] + finding["human_checks"])[:HUMAN_CHECKS]
    finding.update(risk=risk, used_on_product=row.get("used_on_product") if row.get("used_on_product") in ("yes", "no", "unclear") else "unclear")
    return True


def batch_marks(ctx, findings: list) -> list:
    task = ctx.task
    marks = [("T%d" % (i + 1), f) for i, f in enumerate(f for f in findings if f["right_type"] == "trademark")]
    arts = [("A%d" % (i + 1), f) for i, f in enumerate(f for f in findings if f["right_type"] != "trademark")]
    pictures = product_pictures(task, COMPARE_IMAGES)
    answer = ctx.ai.ask("compare", "compare-marks", prompts.compare_marks(task, marks, arts, len(pictures)), images=pictures,
                        schema=prompts.COMPARE_MARKS_SCHEMA, tier="strong")
    rows = read_items(answer, marks + arts)
    return [finding for label, finding in marks + arts if not (label in rows and apply_mark(task, finding, rows[label]))]


BATCHES = {"patent": batch_patent, "design": batch_design, "marks": batch_marks}
GROUP_NAMES = {"patent": "发明专利", "design": "外观设计", "marks": "商标和图案"}


def run(ctx) -> None:
    task = ctx.task
    selected = [c for c in task["candidates"] if (c.get("screen") or {}).get("decision") == "selected"]
    still = {c["id"] for c in selected}
    # 续跑：比过的留着，没比成的重来；初筛重做后不再入选的那几件，旧的比对记录不要
    kept = [f for f in task["findings"] if f.get("status") == "compared" and f["candidate_id"] in still]
    # 上次因为专利局的取图接口不给图、只拿到一张图就比了的：这次重新取图重新比。旧记录先收着——没取全或没比成就放回去，比出来的结论不能丢
    stale = {f["candidate_id"]: f for f in kept if f.get("limit_retry")}
    task["findings"] = [f for f in kept if f["candidate_id"] not in stale]
    done_ids = {f["candidate_id"] for f in task["findings"]}
    todo = [(cand, blank_finding(cand)) for cand in selected if cand["id"] not in done_ids]
    task["findings"] += [finding for _cand, finding in todo]
    failed = []

    def put_back(finding: dict) -> None:
        """把这一件换回上次的比对记录（这次的不要了）。"""
        old = stale.pop(finding["candidate_id"])
        task["findings"][task["findings"].index(finding)] = old
        finding["restored"] = True
        if finding.get("material_limit") and not finding.get("limit_retry"):
            # 这一轮没有被专利局拒，图却还是只有一张：不是接口不给图的事，再试也一样。不再反复重试（"材料不全"的标记留着，定级照样不让评低）
            old.pop("limit_retry", None)
        label = label_of(finding)
        task["incomplete"] = [i for i in task["incomplete"] if not (i.get("what") == label and i.get("step") == task.current_step)]
    try:
        if todo and ctx.usage.should_wrap_up():
            for _cand, finding in todo:
                if finding["candidate_id"] in stale:
                    put_back(finding)  # 上次比过的：沿用上次的结论
                else:
                    fail(task, finding, "到达本单的时间或 token 收口线，未比对")
            todo = []
        if todo:
            ctx.say("  取材料：%d 件（发明读权利要求，外观取附图）…" % len(todo))
            try:
                ctx.sources.dossier(ctx, todo)
            except StopSignal:
                raise
            except Exception as exc:  # 取材料整个出了意料之外的错：发明和外观都没材料可比，商标和图案照常
                for _cand, finding in todo:
                    if finding["right_type"] in MATERIAL_KINDS and not finding.get("claims") and not finding.get("right_images"):
                        finding.update(material_note="取材料时程序出错（%s）" % type(exc).__name__, material_retry=True)
            for _cand, finding in todo:  # 还是没取全（或者这次干脆没取到）：不白开一次会话，沿用上次的结论，到时再试
                if finding["candidate_id"] in stale and (finding.get("material_note") or finding.get("material_limit")):
                    put_back(finding)
            task.save()
        for name, kinds in GROUPS:
            group = [finding for _cand, finding in todo if finding["right_type"] in kinds and not finding.get("restored")]
            ready, retry = [], 0
            for finding in group:
                if finding.get("material_note"):
                    fail(task, finding, "未能比对：%s" % finding["material_note"])
                    retry += 1 if finding.get("material_retry") else 0  # 连不上、被限这类：再跑一次可能就取到了
                else:
                    ready.append(finding)
            if retry:
                failed.append("%s有 %d 件没有取到材料" % (GROUP_NAMES[name], retry))
            if not ready:
                continue
            if ctx.usage.should_wrap_up():
                for finding in ready:
                    fail(task, finding, "到达本单的时间或 token 收口线，未比对")
                continue
            try:
                missed = BATCHES[name](ctx, ready)
                why = "AI 没有给出这一件的结论"
            except StopSignal:
                raise
            except StepFailed as exc:
                missed = [f for f in ready if f["status"] != "compared" and not f.get("reason")]
                why = exc.message
            except Exception as exc:  # 这一批出了意料之外的错（比如回答的形状完全不对）：只算这一批没比成
                missed = [f for f in ready if f["status"] != "compared" and not f.get("reason")]
                why = "程序出错（%s）" % type(exc).__name__
            for finding in missed:
                fail(task, finding, "未能比对：%s" % why)
            if missed:
                failed.append("%s有 %d 件没有比成（%s）" % (GROUP_NAMES[name], len(missed), why))
            task.save()
    finally:
        for _cand, finding in todo:  # 重比没比成（收口、会话没成、中途停下）的：换回上次的记录
            if not finding.get("restored") and finding["candidate_id"] in stale and finding["status"] != "compared":
                put_back(finding)
        todo = [(cand, finding) for cand, finding in todo if not finding.get("restored")]
        for _cand, finding in todo:  # 中途停下（比如额度用尽）：没轮到的写明没有比
            if finding["status"] != "compared" and not finding.get("reason"):
                fail(task, finding, "未能比对：%s" % finding["material_note"] if finding.get("material_note") else "前面已停下，这一件没有比")
        compared = [f for f in task["findings"] if f["status"] == "compared"]
        levels = {}
        for finding in compared:
            levels[finding["risk"]] = levels.get(finding["risk"], 0) + 1
        ctx.say("  比对：本次完成 %d 件，累计 %d 件%s" % (
            sum(1 for _c, f in todo if f["status"] == "compared"), len(compared),
            "（%s）" % "，".join("%s %d" % (risk, levels[risk]) for risk in reversed(config.RISK_ORDER) if risk in levels) if levels else ""))
    short = sum(1 for f in task["findings"] if f.get("limit_retry"))
    if short:
        failed.append("有 %d 件外观只凭一张图比的（附图没取全，多半是美国专利局的取图接口这会儿不给图），还没能重取重比；过一阵再运行一次同样的命令会再试" % short)
    if failed:
        raise StepFailed("；".join(failed))
