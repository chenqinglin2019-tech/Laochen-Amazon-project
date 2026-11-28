"""候选初筛（R-005）：程序先补材料、筛掉已失效的；AI 再成批判断——文字一批（发明、商标、图案），看图一批（外观拼图），
看不清的外观补齐附图再看一次。选出少量值得深查的，其余记下原因。初筛不定风险等级。

原则：没看过的不能写成"未入选"。一批里只要有对不上的回答、或者 AI 没看全，这批里没被点名的候选就不落决定，
定级时那一类会写"初筛没有完成"。"""
from __future__ import annotations

import re
from datetime import date

from .. import config, enrich, numbers, prompts, sheets
from .. import images as image_tools
from ..outcome import StepFailed
from ..sources import gpatents

VISUAL_CAP = enrich.DESIGN_THUMBS  # 一轮看图最多看多少件外观
SECOND_LOOK_CAP = 6   # 看不清的最多补图再看几件
PRODUCT_IMAGES = 2
WEIGHT = {"selected": 4, "same": 4, "similar": 3, "watch": 2, "unseen": 2, "different": 1}  # 同一件有两个结论时取重的


def decision_of(cand: dict) -> str:
    return (cand.get("screen") or {}).get("decision", "")


def set_decision(cand: dict, decision: str, reason: str, by: str = "ai", rank: int = 9) -> None:
    cand["screen"] = {"decision": decision, "by": by, "reason": reason, "rank": rank}


def apply_caps(candidates: list) -> None:
    """每类权利的深查名单有上限；按先后取前几件，超出的写明"超出本轮深查上限"。"""
    taken = {}
    for cand in candidates:
        if decision_of(cand) != "selected":
            continue
        right = cand["right_type"]
        taken[right] = taken.get(right, 0) + 1
        cap = config.DEEP_CAP.get(right, 0)
        if taken[right] > cap:
            set_decision(cand, "over_cap", "超出本轮深查上限（%s最多 %d 件），未深查" % (config.RIGHT_NAMES.get(right, right), cap), "program")


def keys_for(label: str, cand: dict) -> set:
    """AI 回答里可能用来指这件候选的各种写法：编号（大小写、少写前导零）、候选 id、专利号（带不带 US、带不带类别码）。"""
    out = {label.upper(), re.sub(r"(?<=[A-Z])0+(?=\d)", "", label.upper()), str(cand["id"]).upper()}
    number = re.sub(r"[^A-Za-z0-9]", "", str(cand.get("number") or "")).upper()
    if number:
        out |= {number, number[2:] if number.startswith("US") else number}
        key = numbers.us_key(number)
        if key:
            out |= {key, "US" + key}
    return {k for k in out if k}


def lookup_of(pairs: list) -> dict:
    table, clash = {}, set()
    for label, cand in pairs:
        for key in keys_for(label, cand):
            if key in table and table[key] is not cand:
                clash.add(key)
            table[key] = cand
    for key in clash:  # 两件候选撞了同一个写法：这个写法谁也不算
        table.pop(key, None)
    return table


def find(lookup: dict, raw):
    text = re.sub(r"[^A-Za-z0-9\-]", "", str(raw or "")).upper()
    base = re.sub(r"-\d+$", "", text)
    for key in (text, base, re.sub(r"(?<=[A-Z])0+(?=\d)", "", base), text.replace("-", ""), numbers.us_key(text)):
        if key and key in lookup:
            return lookup[key]
    return None


def read_decisions(answer, lookup: dict, absent: str = "", ghosts_out: list = None) -> tuple:
    """把 AI 的回答对到候选上。返回 ([(候选, 决定, 理由)], 对不上的条数)；回答不成样子抛 StepFailed。
    absent：这一批里一件都没有的类别的编号字母（如没有图案候选时的 A）。AI 硬编出这类编号（A01）时不算"对不上"：
    它不可能是把哪件真候选的编号写错了。"""
    rows = answer.get("decisions") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        raise StepFailed("初筛的回答里没有决定清单")
    bad, ghosts, best, order = 0, 0, {}, []
    for row in rows:
        cand = find(lookup, row.get("id")) if isinstance(row, dict) else None
        if cand is None:
            if isinstance(row, dict) and absent and re.fullmatch(r"[%s]\d{1,3}" % absent, str(row.get("id") or "").strip().upper()):
                ghosts += 1
                if ghosts_out is not None:
                    ghosts_out.append("%s（%s）" % (str(row.get("id")).strip().upper(), str(row.get("reason") or "")[:80]))
                continue
            bad += 1
            continue
        entry = (cand, str(row.get("decision") or ""), str(row.get("reason") or ""))
        if id(cand) not in best:
            order.append(id(cand))
            best[id(cand)] = entry
        elif WEIGHT.get(entry[1], 0) > WEIGHT.get(best[id(cand)][1], 0):
            best[id(cand)] = entry  # 同一件说了两次（比如按附图一张张答）：取更重的那个结论
    matched = [best[key] for key in order]
    if rows and not matched:  # 一条都没对上（包括全是不存在的编号）：这份回答不能用
        raise StepFailed("初筛回答里的 %d 条决定都对不上候选" % len(rows))
    return matched, bad


def labelled(candidates: list, prefix: str) -> list:
    return [("%s%02d" % (prefix, index + 1), cand) for index, cand in enumerate(candidates)]


def settle_rest(pairs: list, bad: int, default) -> None:
    """一批里没被 AI 点名的候选：回答都对上了，就按约定算"不深查"；有对不上的条目，就不落决定（不知道那条说的是谁）。"""
    if bad:
        left = sum(1 for _label, cand in pairs if not decision_of(cand))
        raise StepFailed("回答里有 %d 条对不上候选，这一批里没被点名的 %d 件没法下结论" % (bad, left))
    for _label, cand in pairs:
        if not decision_of(cand):
            set_decision(cand, "not_selected", default(cand))


# ---------------- 程序先筛 ----------------
def program_filter(task, today: date = None) -> None:
    today = today or date.today()
    for cand in task["candidates"]:
        if decision_of(cand):
            continue
        raw = cand.get("legal_status_raw", "")
        expiry = numbers.parse_date(cand.get("expiry", "")) if raw else None  # 读到公开页的才信这个到期日（含期限调整）
        lifetime = raw.strip().lower().startswith("expired - lifetime")  # 保护期届满是按日期算死的，可靠
        if raw and gpatents.is_dead(raw) and not lifetime:  # 欠费、放弃、撤回这类：来源记载可能不准，标"状态存疑"照常初筛
            cand["status_doubt"] = "Google Patents 记载：%s" % gpatents.status_name(raw)
        if cand.get("no_figures"):  # 欧盟外观、日本意匠：来源只有名单没有图，看图初筛看不了
            kind = config.NO_FIGURE_OFFICES.get(numbers.office_of(cand.get("number", "")), "外观")
            if cand.get("marked_by"):
                set_decision(cand, "unseen", "%s标注了这件%s：Google Patents 不提供附图，要人工看图（优先看这一件）" % (cand["marked_by"], kind), "program", 0)
            else:
                set_decision(cand, "unseen", "名称相关的%s，Google Patents 不提供它的附图，没有做外观比对" % kind, "program")
        elif cand.get("marked_by") and not lifetime and not (expiry and expiry < today):  # 页面标注了的：那款产品就受它保护，直接深查
            set_decision(cand, "selected", "%s标注了这件，直接深查" % cand["marked_by"], "program", 0)
        elif lifetime:
            set_decision(cand, "not_selected", "保护期已届满（Google Patents 记载：%s）" % gpatents.status_name(raw), "program")
        elif expiry and expiry < today:
            set_decision(cand, "not_selected", "保护期已于 %s 届满" % expiry.isoformat(), "program")
        elif cand["right_type"] == "artwork" and cand.get("watchlist"):
            set_decision(cand, "selected", "常见维权方清单点名了权利人：%s" % (cand.get("owner") or cand.get("title")), "program", 0)


# ---------------- 文字一批：发明、商标、图案 ----------------
def text_round(ctx) -> None:
    task = ctx.task
    open_items = [c for c in task["candidates"] if not decision_of(c)]
    patent_items = [c for c in open_items if c["right_type"] in ("patent", "utility_model")]
    if getattr(ctx.sources, "live", False):  # 真实运行只给前 N 件补了材料，文字初筛也只看这一批
        for cand in [c for c in patent_items if not c.get("enriched")]:
            set_decision(cand, "over_cap", "超出本轮文字初筛的上限（%d 件），没有看" % enrich.PATENT_PAGES, "program")
        patent_items = [c for c in patent_items if c.get("enriched")]
    patents = labelled(patent_items, "P")
    trademarks = labelled([c for c in open_items if c["right_type"] == "trademark"], "T")
    artworks = labelled([c for c in open_items if c["right_type"] == "artwork"], "A")
    pairs = patents + trademarks + artworks
    if not pairs:
        return
    answer = ctx.ai.ask("screen", "screen", prompts.screen_text(task, patents, trademarks, artworks), schema=prompts.SCREEN_TEXT_SCHEMA, tier="light")
    absent = "".join(letter for letter, group in (("P", patents), ("T", trademarks), ("A", artworks)) if not group)
    ghosts = []
    matched, bad = read_decisions(answer, lookup_of(pairs), absent, ghosts)
    if ghosts:  # 不丢：写进报告"这次查了什么"的说明里，人能看到 AI 提过什么
        note = "文字初筛时 AI 提到了不在候选里的编号，没有采用：" + "；".join(ghosts[:5])
        notes = task.data.setdefault("search_notes", [])
        if note not in notes:
            notes.append(note)
    for rank, (cand, decision, reason) in enumerate(matched):
        if decision in ("selected", "watch") and cand.get("pending"):  # 申请公开：授权前不能主张权利，进关注清单，不深查不评等级
            set_decision(cand, "watch", "已公开未授权，列进关注清单：%s" % reason, "ai", rank)
            cand["watchlist_pending"] = True
        elif decision in ("selected", "watch"):
            set_decision(cand, decision, reason, "ai", rank)
        else:
            set_decision(cand, "unseen", "初筛给出的决定认不出（%s）" % decision)
    rows = answer.get("closest") if isinstance(answer, dict) and isinstance(answer.get("closest"), list) else []
    table = lookup_of(patents)
    for row in rows[:3]:  # 没入选里最接近的几件：写明不选的理由，报告里单列，人能复查初筛有没有漏
        cand = find(table, row.get("id")) if isinstance(row, dict) else None
        if cand is not None and not decision_of(cand):
            set_decision(cand, "not_selected", "最接近的几件之一，没有入选：%s" % str(row.get("reason") or "AI 没有说明")[:160], "ai")
            cand["closest"] = True
    settle_rest(pairs, bad, lambda cand: {"trademark": "商标文字和产品上的文字、名字对不上，或只是通用词",
                                          "artwork": "没有发现具体的权利人或维权迹象"}.get(cand["right_type"], "保护的不是和本产品同一类的物品"))


# ---------------- 看图一批：外观 ----------------
def product_pictures(task, count: int = PRODUCT_IMAGES) -> list:
    """给看图会话用的商品图：先缩到普通尺寸存一份。拼图要按大尺寸发，商品图不必跟着放大，省 token。"""
    originals = [task.dir / image["file"] for image in task["product"]["images"][:count]]
    folder = task.dir / "sessions" / "sheets" / "product"
    folder.mkdir(parents=True, exist_ok=True)
    small = image_tools.prepare(originals, folder, config.AI_IMAGE_MAX_PX)
    return small or originals


def apply_looks(matched: list, second: bool = False) -> None:
    ranks = {"same": 0, "similar": 1}
    for cand, decision, reason in matched:
        if decision in ranks:
            set_decision(cand, "selected", reason, "ai", ranks[decision])
            cand["screen"]["look"] = decision
        elif decision == "different" and second:
            set_decision(cand, "not_selected", reason or "补图后看，造型明显不同")
        else:
            set_decision(cand, "unseen", reason or ("补图后仍然看不清主体造型" if second else "代表图看不清主体造型"))


def visual_round(ctx) -> None:
    task = ctx.task
    designs = [c for c in enrich.design_order(task["candidates"]) if not decision_of(c)]
    if not designs:
        return
    live = getattr(ctx.sources, "live", False)
    if live:
        for cand in [c for c in designs if not c.get("enriched")]:  # 没排进这一轮取图的
            set_decision(cand, "over_cap", "超出本轮看图初筛的上限（%d 件），没有看" % VISUAL_CAP, "program")
        designs = [c for c in designs if c.get("enriched")]
        for cand in designs:
            if not cand.get("thumb") or not image_tools.readable(task.dir / cand["thumb"]):
                set_decision(cand, "unseen", "没有取到附图", "program")
                cand["screen"]["retry"] = bool(cand.get("image_location") or cand.get("euipo"))  # 官方那边有这件的附图，只是这次没取到：续跑时再取
        designs = [c for c in designs if not decision_of(c)]
        if not designs:
            return
        if not sheets.available():
            raise StepFailed("没有装图像库 Pillow，没法拼图给 AI 看；请先运行安装脚本")
    pairs = labelled(designs, "D")
    pictures = product_pictures(task)
    boards, blank = [], []
    if live:
        boards = sheets.sheets([(label, task.dir / cand["thumb"]) for label, cand in pairs], task.dir / "sessions" / "sheets", "designs", blank)
        for label, cand in pairs:
            if label in blank:  # 拼图时才发现打不开的：这一格是空的，直接记看不清
                set_decision(cand, "unseen", "附图打不开", "program")
        pairs = [(label, cand) for label, cand in pairs if label not in blank]
        if not pairs:
            return
    answer = ctx.ai.ask("screen", "screen-visual", prompts.screen_visual(task, pairs, len(pictures)), images=pictures + boards,
                        schema=prompts.SCREEN_VISUAL_SCHEMA, tier="light", image_max_px=config.SHEET_MAX_PX)
    matched, bad = read_decisions(answer, lookup_of(pairs))
    apply_looks(matched)
    viewed = answer.get("viewed") if isinstance(answer, dict) else None
    if live and (not isinstance(viewed, int) or isinstance(viewed, bool) or viewed < len(pairs)):
        # AI 没说看了几格，或者自己说没看全：没被点名的不能当成"看过、不同"
        told = "它说看了 %d 格" % viewed if isinstance(viewed, int) and not isinstance(viewed, bool) else "它没说看了几格"
        raise StepFailed("AI 没有确认看全（%s，这一批共 %d 格），没被点名的没法下结论" % (told, len(pairs)))
    settle_rest(pairs, bad, lambda _cand: "代表图显示造型明显不同")
    if live:
        second_look(ctx, [c for _l, c in pairs if decision_of(c) == "unseen"])


def second_look(ctx, unclear: list) -> None:
    """看不清的外观：把它的前几张附图都取来，一件拼一张，再看一次。仍然看不清的留作"未能比对"。"""
    task = ctx.task
    for cand in unclear[SECOND_LOOK_CAP:]:
        cand["screen"]["reason"] += "（看不清的太多，这一件没有补图再看）"
    pairs, boards = [], []
    for label, cand in labelled(unclear[:SECOND_LOOK_CAP], "D"):
        figures = ctx.sources.more_figures(ctx, cand)
        if len(set(figures)) < 2:
            cand["screen"]["reason"] += "（没能补到更多附图）"
            continue
        pairs.append((label, cand))
        boards.append(sheets.grid([("%s-%d" % (label, i + 1), path) for i, path in enumerate(figures)],
                                  task.dir / "sessions" / "sheets" / ("second-%s.jpg" % label), columns=2))
    if not pairs:
        return
    pictures = product_pictures(task)
    try:
        answer = ctx.ai.ask("screen", "screen-visual-2", prompts.screen_visual(task, pairs, len(pictures), second=True),
                            images=pictures + boards, schema=prompts.SCREEN_SECOND_SCHEMA, tier="light", image_max_px=config.AI_IMAGE_MAX_PX)
        matched, _bad = read_decisions(answer, lookup_of(pairs))
    except StepFailed:
        for _label, cand in pairs:
            cand["screen"]["reason"] += "（补图再看没有完成）"
        return
    apply_looks(matched, second=True)


def close_out(ctx) -> None:
    """收尾：入选的排前面（主体造型相同的先于相似的）、按上限截取、把看不清和超上限的记进"没查完"。无论中途是否停下都要做。"""
    task = ctx.task
    compared = {f["candidate_id"] for f in task["findings"] if f.get("status") == "compared"}
    # 入选的排前面；续跑时已经比过的那几件先占名额（不然会被新入选的挤出去，比出来的结论就丢了），再按主体相同先于相似
    task["candidates"] = sorted(task["candidates"], key=lambda c: (0 if decision_of(c) == "selected" else 1, 0 if c["id"] in compared else 1,
                                                                   (c.get("screen") or {}).get("rank", 9)))
    apply_caps(task["candidates"])
    counts = {}
    listed = [c for c in task["candidates"] if c.get("no_figures") and decision_of(c) == "unseen"]
    if listed:  # 来源不给图的外观：合成一条，不一件一条地刷屏
        how = "到日本特许厅的检索网站 J-PlatPat 按登记号查看附图" if task.country == "JP" else "点开号码看图"
        task.add_incomplete("%d 件名称相关的外观" % len(listed), '未能比对：来源不提供附图，只列了名单（在报告末尾"这次查了什么"里），要人工%s' % how, "design")
    unread = [c for c in task["candidates"] if decision_of(c) == "over_cap" and "文字初筛的上限" in c["screen"]["reason"]]
    if unread:
        task.add_incomplete("%d 件发明或实用新型" % len(unread), "超出本轮文字初筛的上限，没有看", unread[0]["right_type"])
    for cand in task["candidates"]:
        decision = decision_of(cand)
        counts[decision] = counts.get(decision, 0) + 1
        label = ("%s %s" % (cand.get("number", ""), cand.get("title", ""))).strip()
        if decision == "unseen" and cand.get("no_figures"):
            continue
        if decision == "unseen":
            task.add_incomplete(label, "未能比对：%s" % (cand["screen"]["reason"] or "看不清"), cand["right_type"])
        elif decision == "over_cap" and cand not in unread:
            task.add_incomplete(label, cand["screen"]["reason"], cand["right_type"])
    ctx.say("  初筛：入选 %d 件，未入选 %d 件，仅关注 %d 件，看不清 %d 件，超上限 %d 件%s" % (
        counts.get("selected", 0), counts.get("not_selected", 0), counts.get("watch", 0), counts.get("unseen", 0), counts.get("over_cap", 0),
        "，没下结论 %d 件" % counts[""] if counts.get("") else ""))


TITLE_NOTE = "只看标题判断不是同一类物品，没有读公开页（标题多是机器翻译，可能不准）"


def title_round(ctx) -> None:
    """发明和实用新型的候选超过一轮能读的件数时，先只看标题挑出可能相关的，免得读不完的那部分"超出上限、没有看"。
    这一轮没成就照旧：读前面那一批，其余记超上限。"""
    task = ctx.task
    cap = enrich.PATENT_PAGES
    # 页面标注了的不进这一轮（程序会直接选去深查，标题还常是空的）
    open_items = [c for c in task["candidates"] if c["right_type"] in ("patent", "utility_model") and not decision_of(c) and not c.get("marked_by")]
    if len(open_items) <= cap:
        return
    labels = [("K%03d" % (i + 1), c) for i, c in enumerate(open_items)]
    items = [{"id": label, "title": " ".join(str(c.get("title") or "").split())[:140],
              "kind": "申请公开" if c.get("pending") else config.RIGHT_NAMES.get(c["right_type"], "")} for label, c in labels]
    answer = ctx.ai.ask("screen", "screen-titles", prompts.screen_titles(task, items, cap), schema=prompts.TITLE_SCHEMA, tier="light")
    by_label = dict(labels)
    raw_keep = answer.get("keep") if isinstance(answer, dict) else None
    if not isinstance(raw_keep, list):
        raise StepFailed("只看标题的那一轮没有给出可用的回答")
    keep = []
    for raw in raw_keep:
        cand = by_label.get(str(raw).strip().upper())
        if cand is not None and cand not in keep:
            keep.append(cand)
    if raw_keep and not keep:  # 答了一串编号却一个都对不上：这份回答不能用（一个都不留的空清单是有效回答）
        raise StepFailed("只看标题的那一轮回答里的编号都对不上")
    # AI 认为相关、但超出一轮能读的件数的（实用新型另有上限）：记超上限，会进"没查完"，不说成"不是同一类"
    within, utility = [], 0
    over = []
    for cand in keep:
        is_utility = cand["right_type"] == "utility_model"
        if len(within) < cap and not (is_utility and utility >= enrich.UTILITY_PAGES):
            within.append(cand)
            utility += 1 if is_utility else 0
        else:
            over.append(cand)
    dropped = 0
    for cand in open_items:
        if cand in over:
            set_decision(cand, "over_cap", "超出本轮文字初筛的上限，没有看（只看标题时认为可能相关）", "program")
        elif cand not in within:
            set_decision(cand, "not_selected", TITLE_NOTE, "ai-title")
            dropped += 1
    keep = within
    # 留下的排到前面，补材料时按这个先后读公开页
    order = {id(c): i for i, c in enumerate(keep)}
    task["candidates"] = sorted(task["candidates"], key=lambda c: order.get(id(c), len(order)))
    note = "发明和实用新型候选 %d 件，超过一轮能读的 %d 件：先只看标题排除了 %d 件明显不是同一类的（标题多是机器翻译，排除的那些没有读公开页）%s。" % (
        len(open_items), cap, dropped, "；另有 %d 件可能相关但超出上限、没有看" % len(over) if over else "")
    notes = task.data.setdefault("search_notes", [])
    if note not in notes:
        notes.append(note)
    ctx.say("  只看标题：%d 件里留下 %d 件去读公开页" % (len(open_items), len(keep)))


def run(ctx) -> None:
    task = ctx.task
    if not task["candidates"]:
        ctx.say("  没有候选，跳过初筛")
        return
    failures = []
    try:
        try:
            title_round(ctx)
        except StepFailed as exc:  # 锦上添花的一轮：没成就照旧读前面那一批，其余记超上限（那些会写进"没查完"）
            ctx.say("  只看标题的那一轮没有完成（%s），按原来的先后读前 %d 件" % (exc.message, enrich.PATENT_PAGES))
        ctx.sources.enrich(ctx)
        program_filter(task)
        for name, round_ in (("文字初筛", text_round), ("看图初筛", visual_round)):
            try:
                round_(ctx)
            except StepFailed as exc:  # 这一批没成：这批里没下结论的候选留着没有决定，另一批照常做
                failures.append("%s没有完成（%s）" % (name, exc.message))
    finally:
        close_out(ctx)
    lost = sum(1 for cand in task["candidates"] if (cand.get("screen") or {}).get("retry"))
    if lost:
        failures.append("有 %d 件外观没有取到附图（网络一时不通，或者%s的取图接口这会儿不给图）；过一阵再运行一次同样的命令只补这几件" % (
            lost, "美国专利局" if task.country == "US" else "官方"))
    if failures:
        raise StepFailed("；".join(failures))
