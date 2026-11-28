"""把任务状态套进固定模板，生成一份离线能打开的中文 HTML 报告（R-008）。纯程序，不用 AI。

五块：顶部结论 → 每类权利一行 → 风险项明细 → 没查到或没查完的（折叠）→ 这次查了什么（折叠）。
"""
from __future__ import annotations

import base64
import io
import mimetypes
from html import escape
from pathlib import Path

from .. import config, outcome

CSS = (Path(__file__).resolve().parent / "report.css").read_text(encoding="utf-8")
ELEMENT_VERDICTS = {"match": "对应", "absent": "不对应", "unseen": "图上看不到"}
DECISION_NAMES = {"selected": "入选深查", "not_selected": "未入选", "unseen": "未能比对", "over_cap": "超出上限", "watch": "仅关注"}
SEARCH_STATUS = {"ok": "已查", "failed": "没查成", "skipped": "未检索"}
_URI_CACHE = {}


def e(value) -> str:
    """写进报告的任何外部内容都先过这里：空值当空字符串，其余转成文字再转义。"""
    return escape("" if value is None else str(value))


def link(url, label=None) -> str:
    """只有 http 和 https 的链接才做成可点的，其余当普通文字。"""
    url = "" if url is None else str(url).strip()
    if url.lower().startswith(("http://", "https://")):
        return '<a href="%s" rel="noopener noreferrer">%s</a>' % (e(url), e(label or url))
    return e(label or url)


def data_uri(path: Path, max_px: int = 720, trim: bool = False) -> str:
    """把图片嵌进报告。装了 Pillow 就先缩小，报告不会太大；没装就原样嵌入。trim=True 先裁掉四周白边（专利附图是整页扫描）。"""
    path = Path(path)
    if not path.is_file():
        return ""
    key = (str(path), max_px, trim, path.stat().st_mtime_ns)
    if key not in _URI_CACHE:
        _URI_CACHE[key] = _encode(path, max_px, trim)
    return _URI_CACHE[key]


def _encode(path: Path, max_px: int, trim: bool = False) -> str:
    try:
        from PIL import Image  # noqa: 可选依赖
        with Image.open(path) as image:
            image = image.convert("RGB")
            if trim:
                from .. import sheets
                image = sheets.trim(image)
            image.thumbnail((max_px, max_px))
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def risk_span(risk: str, big: bool = False) -> str:
    cls = "risk-" + (risk if risk in config.RISK_ORDER or risk == config.RISK_PENDING else "none")
    text = risk or "—"
    return '<strong class="%s">%s</strong>' % (cls, e(text)) if big else '<span class="badge %s">%s</span>' % (cls, e(text))


def figure(task_dir: Path, rel: str, caption: str, max_px: int = 720, trim: bool = False) -> str:
    path = config.inside(task_dir, rel)  # 路径来自状态文件：跑到任务目录外面去的不读
    uri = data_uri(path, max_px, trim) if path else ""
    if not uri:
        return ""
    return '<figure><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>' % (uri, e(caption), e(caption))


def items(values) -> str:
    values = [v for v in values or [] if v]
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % e(str(v)) for v in values) if values else ""


# ---------------- 第一块：顶部结论 ----------------
def block_top(task, result: dict) -> str:
    product, under, overall = task["product"], task["understanding"], task["overall"]
    country = config.COUNTRIES[task.country]["name"]
    out = ['<header><div class="eyebrow">侵权风险排查报告 · %s</div><h1>%s</h1>' % (e(country), e(product.get("title", "（没有商品标题）")))]
    meta = ["目的国：%s" % country, "生成时间：%s" % e(result.get("finished_at", "")[:16].replace("T", " "))]
    if product.get("asin"):
        meta.append("ASIN：%s" % e(product["asin"]))
    if product.get("url"):
        meta.append(link(product["url"], "商品链接"))
    out.append('<p class="small">%s</p>' % " · ".join(meta))
    if task["demo"]:
        out.append('<div class="banner">演示数据：商品和检索结果来自录好的一次真实任务，AI 判断是固定样例，不是真实结论。</div>')
    if result.get("test_faults"):
        out.append('<div class="banner">这一单开着测试开关（%s），是故障演练，结果不能当真。</div>' % e(result["test_faults"]))
    if result.get("kind") and result["kind"] != outcome.DONE:
        when, how = "", ""
        if result["kind"] == outcome.QUOTA_STOPPED:
            when = ("额度大约在 %s 恢复。" % result["resume_at"] if result.get("resume_at")
                    else "恢复时间 Codex 这次没有给出，可以在 Codex 里看额度什么时候恢复。")
        if not task["demo"]:  # 演示数据没有"接着跑"这回事
            how = "把同一条命令原样再运行一次，会接着做没做完的部分，已经查过的不重查。"
            if result["kind"] == outcome.ERROR_STOPPED:
                how = "%d 小时以内%s过了这个时间，同一条命令会重新开一单（用 --task-dir 指定这个任务目录可以照样接着做）。" % (config.RESUME_ERROR_HOURS, how)
            elif result["kind"] == outcome.QUOTA_STOPPED:
                how = "恢复之后" + how
        out.append('<div class="banner">本次没有跑完（%s）：%s%s</div>'
                   % (e(outcome.TITLES[result["kind"]]), e(result.get("message", "")), "<br>" + e(when + how) if when or how else ""))
    if product.get("asin_note"):
        out.append('<div class="banner">%s</div>' % e(product["asin_note"]))
    if task["entry"].get("type") == "url" and task["entry"].get("site_country") != task.country:
        site = config.COUNTRIES.get(task["entry"].get("site_country") or "", {}).get("name", "七国之外的站点")
        out.append('<div class="banner">链接所在站点是%s，本次按%s排查。</div>' % (e(site), e(country)))
    out.append("</header>")

    image = product.get("images") or []
    picture = figure(task.dir, image[0]["file"], "商品主图") if image else ""
    risk = overall.get("risk", config.RISK_PENDING)
    verdict = ['<div class="verdict">',
               '<div class="metric"><span>总风险等级%s</span>%s</div>' % ("（仅就已查部分）" if overall.get("partial") else "", risk_span(risk, True)),
               '<div class="metric"><span>置信度</span><strong>%s</strong></div>' % e(overall.get("confidence") or "—"),
               "</div>",
               '<p class="advice">%s</p>' % e(overall.get("advice") or "定级没有完成，无法给出建议。暂缓上架。")]
    understanding = ["<h3>AI 对产品的理解（请核对）</h3>"]
    if under.get("fallback"):
        understanding.append('<div class="empty">产品理解未完成，检索词来自标题。</div>')
    if under.get("description"):
        understanding.append("<p>%s</p>" % e(under["description"]))
    elif not under.get("fallback"):
        understanding.append('<div class="empty">产品理解这一步没有做。</div>')
    understanding.append(items((under.get("structure") or []) + (under.get("appearance") or [])))
    hypotheses = under.get("hypotheses") or []
    if hypotheses:
        understanding.append("<h3>产品上可能属于别人的图案、角色、文字</h3>")
        understanding.append(items("%s：%s%s%s" % (h.get("name", ""), h.get("reason", ""),
                                                 "（可能的权利人：%s）" % h["owner"] if h.get("owner") else "",
                                                 " " + h["watch_note"] if h.get("watch_note") else "") for h in hypotheses))
    out.append('<div class="hero"><div>%s</div><div>%s%s</div></div>' % (picture, "".join(verdict), "".join(understanding)))
    return "".join(out)


# ---------------- 第二块：每类权利一行 ----------------
def block_rights(task) -> str:
    rows = []
    for row in task["rights_summary"]:
        if row["state"] == "not_applicable":
            level, confidence = '<span class="badge risk-none">不适用</span>', "—"
        elif row["state"] == "not_searched":
            level, confidence = '<span class="badge risk-待定">未检索</span>', "—"
        elif row["state"] == "nothing":
            level, confidence = '<span class="badge risk-none">无可查项</span>', "—"
        else:
            level, confidence = risk_span(row["risk"]), e(row["confidence"] or "—")
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(row["name"]), level, confidence, e(row["basis"])))
    return ('<section><h2>各类权利</h2><div class="table-wrap"><table><thead><tr><th>权利</th><th>等级</th><th>置信度</th><th>依据</th></tr></thead>'
            "<tbody>%s</tbody></table></div>%s</section>" % ("".join(rows), progress_table(task)))


def progress_table(task) -> str:
    """核查进度：每类权利分开写"检索到 / 取到材料 / 已比对 / 官方状态已核"，免得把"查到了"当成"比过了"、把"比过了"当成"状态核过了"。"""
    rows = []
    for row in task["rights_summary"]:
        right = row["right_type"]
        if row["state"] == "not_applicable":
            continue
        cands = [c for c in task["candidates"] if c["right_type"] == right]
        findings = [f for f in task["findings"] if f["right_type"] == right]
        if right in ("patent", "utility_model"):
            material = sum(1 for c in cands if c.get("claim1") or c.get("abstract")) or sum(1 for f in findings if f.get("claims"))
            material_text = "%d 件读到权利要求或摘要" % material
        elif right == "design":
            material = sum(1 for c in cands if c.get("thumb"))
            listed = sum(1 for c in cands if c.get("no_figures"))
            material_text = "%d 件取到附图%s" % (material, "，%d 件只有名单没有图" % listed if listed else "")
        else:
            material_text = "—"
        searched = "未检索" if row["state"] == "not_searched" else "%d 件" % len(cands)
        compared = sum(1 for f in findings if f.get("status") == "compared")
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%d 件</td><td>0 件</td></tr>" % (
            e(row["name"]), e(searched), e(material_text), compared))
    if not rows:
        return ""
    return ('<details><summary>核查进度（检索到、取到材料、已比对、官方状态已核分开写）</summary><div class="table-wrap"><table><thead><tr>'
            "<th>权利</th><th>检索到</th><th>取到材料</th><th>已比对</th><th>官方状态已核</th></tr></thead><tbody>%s</tbody></table></div>"
            '<p class="small">官方状态：本工具没有接官方的状态接口，"是否有效"都来自公开数据库（Google Patents 等），评到中以上的请到官方核对。</p></details>'
            % "".join(rows))


# ---------------- 第三块：风险项明细 ----------------
RIGHT_IMAGES_KEY, RIGHT_IMAGES_REST = 4, 2   # 明细里每件放几张对方附图：要紧的多放，折叠起来的少放
USED_NAMES = {"yes": "有", "no": "没有", "unclear": "说不清"}


def finding_card(task, finding: dict, key: bool = True) -> str:
    out = ['<article class="finding"><div class="finding-head"><h3>%s　%s</h3><div>%s <span class="badge">置信度 %s</span></div></div>'
           % (e(finding.get("number", "")), e(finding.get("title", "")), risk_span(finding["risk"]), e(finding.get("confidence") or "—"))]
    facts = [("类别", config.RIGHT_NAMES.get(finding["right_type"], finding["right_type"])),
             ("权利人", finding.get("owner") or "未取得"),
             ("申请日", finding.get("filing_date") or "未取得"),
             ("授权日", finding.get("grant_date") or "未取得"),
             ("是否有效", ("状态存疑：%s（未核官方）" % finding["status_doubt"]) if finding.get("status_doubt") else
                         ("%s（公开数据库记载，未核官方）" % finding["legal_status"]) if finding.get("legal_status") else "未核实"),
             ("到期日", finding.get("expiry") or "未核实")]
    if finding["right_type"] in ("trademark", "artwork"):
        facts = [fact for fact in facts if fact[0] != "到期日" and not (finding["right_type"] == "artwork" and fact[0] in ("申请日", "授权日", "是否有效"))]
        if finding.get("detail"):
            facts.append(("登记信息" if finding["right_type"] == "trademark" else "怀疑的原因", finding["detail"]))
        if finding.get("used_on_product"):
            facts.append(("产品或页面上有没有用", USED_NAMES.get(finding["used_on_product"], finding["used_on_product"])))
    rows = "".join("<dt>%s</dt><dd>%s</dd>" % (e(k), e(v)) for k, v in facts)
    if finding.get("url"):
        rows += "<dt>官方链接</dt><dd>%s</dd>" % link(finding["url"])
    out.append("<dl>%s</dl>" % rows)

    images = task["product"].get("images") or []
    left = figure(task.dir, images[0]["file"], "你的产品") if images else ""
    right = "".join(figure(task.dir, rel, "对方附图 %d" % (i + 1), 560, True)
                    for i, rel in enumerate((finding.get("right_images") or [])[:RIGHT_IMAGES_KEY if key else RIGHT_IMAGES_REST]))
    if left and right:
        out.append('<div class="compare">%s<div class="pair">%s</div></div>' % (left, right))
    elif finding["right_type"] in ("design", "patent", "utility_model", "artwork"):
        out.append('<div class="empty">没有取到对方的附图，请点官方链接核对。</div>')

    if finding.get("selected_reason"):
        out.append("<p><b>入选原因：</b>%s</p>" % e(finding["selected_reason"]))
    out.append("<p><b>比对结论：</b>%s</p>" % e(finding.get("basis", "")))
    if finding.get("elements"):
        body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                       % (e(el.get("text", "")), e(ELEMENT_VERDICTS.get(str(el.get("verdict") or ""), el.get("verdict", ""))), e(el.get("note", "")))
                       for el in finding["elements"])
        which = "对方第 %d 项独立权利要求要求的要素" % finding["claim_number"] if finding.get("claim_number") else "对方要求的要素"
        out.append('<div class="table-wrap"><table><thead><tr><th>%s</th><th>判断</th><th>说明</th></tr></thead><tbody>%s</tbody></table></div>' % (which, body))
        if finding.get("claims_compared", 0) > 1:
            out.append('<p class="muted">一共比了 %d 项独立权利要求，上面列的是最接近的那一项。</p>' % finding["claims_compared"])
    if finding.get("differences"):
        out.append("<p><b>主要差异：</b>%s</p>" % e(finding["differences"]))
    if finding.get("human_checks"):
        out.append("<p><b>需要你核对的：</b></p>%s" % items(finding["human_checks"]))
    recheck = finding.get("recheck") or {}
    if recheck.get("status") == "done":
        out.append("<p><b>两次判断：</b>第一次评%s，复核评%s%s。复核意见：%s</p>"
                   % (e(recheck["first_risk"]), e(recheck["second_risk"]),
                      "，一致" if recheck["agree"] else "，不一致，取较高的等级", e(recheck.get("second_basis", ""))))
    elif recheck.get("status") in ("skipped", "failed"):
        out.append('<p class="muted">未复核：%s</p>' % e(recheck.get("reason", "")))
    elif finding.get("uncertain") or config.risk_rank(finding["risk"]) >= config.risk_rank(config.RECHECK_FROM):
        out.append('<p class="muted">未复核：复核这一步没有做到这一件，上面只是第一次的判断。</p>')
    out.append("</article>")
    return "".join(out)


def block_findings(task) -> str:
    compared = [f for f in task["findings"] if f["status"] == "compared"]
    compared.sort(key=lambda f: -config.risk_rank(f["risk"]))
    key = [f for f in compared if config.risk_rank(f["risk"]) >= config.risk_rank(config.RECHECK_FROM) or f.get("uncertain")]
    rest = [f for f in compared if f not in key]
    out = ["<section><h2>风险项明细（请人工核对）</h2>"]
    if key:
        out.append("".join(finding_card(task, f) for f in key))
    elif not compared and task["rights_summary"] and all(task.step_done(s) for s in ("search", "screen", "compare")) and not task["findings"] \
            and not any((c.get("screen") or {}).get("decision") in ("unseen", "over_cap", "selected") for c in task["candidates"]):
        out.append('<div class="empty">初筛后没有需要深查的候选。</div>')
    elif not compared:
        out.append('<div class="empty">本次没有完成任何比对，原因见下面"没查到或没查完的"。</div>')
    else:
        out.append('<div class="empty">已比对的 %d 件里，没有评为中及以上或拿不准的。</div>' % len(compared))
    if rest:
        out.append("<details><summary>已比对、评为低的 %d 件</summary>%s</details>" % (len(rest), "".join(finding_card(task, f, key=False) for f in rest)))
    out.append("</section>")
    return "".join(out)


def block_pending(task) -> str:
    """关注清单：已公开、还没授权、但和本产品相关的申请。不评等级（授权前不能主张权利），要留意它的进展。"""
    pending = [c for c in task["candidates"] if c.get("watchlist_pending")]
    if not pending:
        return ""
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        link(c.get("url"), c.get("number")) if c.get("url") else e(c.get("number", "")), e(c.get("title", "")), e(c.get("owner") or "—"),
        e(str((c.get("screen") or {}).get("reason", "")).replace("已公开未授权，列进关注清单：", ""))) for c in pending)
    return ('<section><h2>关注清单：已公开、还没授权的申请（%d 件，不评等级）</h2><p class="small">授权前不能用来主张权利；'
            "但授权后，对方可能要求公开以后的补偿（例如日本特许法第 65 条：先书面警告，授权后才能行使）。上架后要留意它们的进展，"
            "授权了就要按授权的权利要求重新比对。</p><div class=\"table-wrap\"><table><thead><tr><th>号码</th><th>名称</th><th>申请人</th>"
            "<th>为什么列进来</th></tr></thead><tbody>%s</tbody></table></div></section>" % (len(pending), rows))


def block_competitors(task) -> str:
    """竞品（可选）：采到的品牌、标题和页面上的专利、外观标注。"""
    rows = []
    for comp in task.data.get("competitors") or []:
        if not isinstance(comp, dict):
            continue
        label = link(comp.get("url"), comp.get("asin") or comp.get("input")) if comp.get("url") else e(comp.get("input", ""))
        if comp.get("status") == "ok":
            rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (label, e(comp.get("brand") or "—"), e(comp.get("title", "")[:120]),
                                                                          e("；".join(comp.get("marking") or []) or "没有标注")))
        else:
            rows.append('<tr><td>%s</td><td colspan="3">没采到：%s</td></tr>' % (label, e(comp.get("note", ""))))
    if not rows:
        return ""
    return ('<section><h2>竞品（%d 个）</h2><p class="small">页面上标注的专利、外观号码已经直接列入深查（见上面的明细）。竞品的品牌、图片、文案都不要用在你的上架里。'
            "品牌名通常不是专利权人的名字，按品牌查权利人不可靠，本工具只取了页面标注。</p>"
            '<div class="table-wrap"><table><thead><tr><th>竞品</th><th>品牌</th><th>标题</th><th>页面上的专利、外观标注</th></tr></thead><tbody>%s</tbody></table></div>'
            "</section>" % (len(rows), "".join(rows)))


def block_image_notes(task) -> str:
    """上架图片要注意的：不是产品本身、但出现在拟上架图片里的道具、水印、别人的标识。本工具没有对它们做检索。"""
    notes = [n for n in (task["understanding"] or {}).get("image_notes") or [] if isinstance(n, dict) and n.get("what")]
    if not notes:
        return ""
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (e("第 %d 张" % n["image"] if n.get("image") else "—"), e(n.get("kind", "")),
                                                              e(n["what"])) for n in notes)
    return ('<section><h2>上架图片要注意的（%d 处）</h2><p class="small">这些不是产品本身，但出现在拟上架的图片里：道具和别人的品牌、角色可能涉及版权或商标，'
            "水印说明图片来源要确认授权，图里的文字也要和文案一样避开别人的商标。本工具没有对它们做检索，请人工确认或换掉。</p>"
            '<div class="table-wrap"><table><thead><tr><th>哪张图</th><th>类型</th><th>看到了什么</th></tr></thead><tbody>%s</tbody></table></div></section>'
            % (len(notes), rows))


def block_manual_marks(task) -> str:
    """日本这类没有可查商标库的：要人工核对的词和检索链接。放在明细后面、不折叠——这是要用户动手的事。"""
    if task.country not in config.TRADEMARK_MANUAL or not task.step_done("search"):
        return ""
    marks = task.data.get("manual_marks") or []
    intro = ('<p class="small">%s的商标没有可以合规地用程序检索的来源，这一类本工具<strong>没有查</strong>（报告里写"未检索"，不是低风险）。'
             "请逐个点开链接人工核对：有没有相同或读音相近的注册，它的指定商品是否覆盖本产品，状态是否有效。"
             "两个网站都禁止程序自动查询，这里只给链接。</p>" % e(config.COUNTRIES[task.country]["name"]))
    if not marks:
        body = '<div class="empty">没有挑出要查的词。定了自有品牌后，品牌名也要到 J-PlatPat 查。</div>'
    else:
        rows = []
        for mark in marks:
            remind = "；".join(x for x in (("权利人：" + mark["owner"]) if mark.get("owner") else "", mark.get("note", ""),
                                           ("可以换成：" + mark["plain"]) if mark.get("plain") else "") if x)
            links = "<br>".join(link(item.get("url"), item.get("label")) for item in mark.get("links") or [] if isinstance(item, dict))
            rows.append("<tr><td><strong>%s</strong></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                e(mark["term"]), e(mark.get("why", "")), e(remind or "—"), links or "—"))
        body = ('<div class="table-wrap"><table><thead><tr><th>词</th><th>为什么要查</th><th>提醒</th><th>点开核对</th></tr></thead>'
                "<tbody>%s</tbody></table></div>" % "".join(rows))
        body += '<p class="small">定了自有品牌后，品牌名也要查。</p>'
    return "<section><h2>商标要人工核对的词</h2>%s%s</section>" % (intro, body)


# ---------------- 第四块：没查到或没查完的 ----------------
def block_incomplete(task) -> str:
    rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (e(i["what"]), e(i["why"])) for i in task["incomplete"])
    body = ('<div class="table-wrap"><table><thead><tr><th>什么</th><th>为什么</th></tr></thead><tbody>%s</tbody></table></div>' % rows
            if rows else '<p class="muted">没有。</p>')
    return "<section><details><summary>没查到或没查完的（%d 项）</summary>%s</details></section>" % (len(task["incomplete"]), body)


# ---------------- 第五块：这次查了什么 ----------------
def candidate_rows(candidates: list) -> str:
    return "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        e(config.RIGHT_NAMES.get(c["right_type"], c["right_type"])),
        link(c.get("url"), c.get("number") or c.get("title")) if c.get("url") else e(c.get("number") or "—"),
        e(c.get("title", "")), e((c.get("screen") or {}).get("reason", ""))) for c in candidates)


def block_searches(task) -> str:
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        e(config.RIGHT_NAMES.get(s.get("route"), s.get("route_name") or s.get("route", ""))), e(s.get("source", "")),
        e(s.get("query", "")), e(SEARCH_STATUS.get(s.get("status"), s.get("status", ""))),
        e(str(s.get("count", ""))) if s.get("status") == "ok" else e(s.get("reason", ""))) for s in task["searches"])
    counts = {}
    for cand in task["candidates"]:
        decision = (cand.get("screen") or {}).get("decision", "未初筛")
        key = (config.RIGHT_NAMES.get(cand["right_type"], cand["right_type"]), DECISION_NAMES.get(decision, decision))
        counts[key] = counts.get(key, 0) + 1
    tally = "；".join("%s%s %d 件" % (k[0], k[1], v) for k, v in sorted(counts.items()))
    out = ['<div class="table-wrap"><table><thead><tr><th>方向</th><th>来源</th><th>检索式</th><th>状态</th><th>结果数或原因</th></tr></thead>'
           "<tbody>%s</tbody></table></div>" % rows if rows else '<p class="muted">没有检索记录。</p>']
    out.append('<p class="small">候选去向：%s</p>' % e(tally or "无"))
    for note in task.data.get("search_notes") or []:
        out.append('<p class="small">%s</p>' % e(note))
    head = "<thead><tr><th>类别</th><th>号码</th><th>名称</th><th>原因</th></tr></thead>"
    selected = [c for c in task["candidates"] if (c.get("screen") or {}).get("decision") == "selected"]
    watch = [c for c in task["candidates"] if (c.get("screen") or {}).get("decision") == "watch" and not c.get("watchlist_pending")]
    if selected:
        out.append('<h3>初筛入选、进入深查的 %d 件</h3><div class="table-wrap"><table>%s<tbody>%s</tbody></table></div>' % (
            len(selected), head, candidate_rows(selected)))
    closest = [c for c in task["candidates"] if c.get("closest") and (c.get("screen") or {}).get("decision") == "not_selected"]
    if closest:
        out.append('<h3>没入选里最接近的 %d 件（初筛说明了为什么不选，可以复查）</h3><div class="table-wrap"><table>%s<tbody>%s</tbody></table></div>' % (
            len(closest), head, candidate_rows(closest)))
    if watch:
        out.append('<h3>仅关注、没有深查的 %d 件</h3><div class="table-wrap"><table>%s<tbody>%s</tbody></table></div>' % (
            len(watch), head, candidate_rows(watch)))
    listed = [c for c in task["candidates"] if c.get("no_figures") and (c.get("screen") or {}).get("decision") == "unseen"]
    if listed:  # 来源只有名单没有图的外观：给官方链接，人工打开看图
        rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            link(c.get("url"), c.get("number")) if c.get("url") else e(c.get("number") or "—"), e(c.get("title", "")),
            e(c.get("owner", "") or "—"), e(c.get("filing_date", "") or "—")) for c in listed)
        out.append('<h3>名称相关、没有附图可比的外观 %d 件（要人工看图：欧盟外观点开号码；日本意匠到 J-PlatPat 按登记号查）</h3><div class="table-wrap"><table><thead><tr><th>号码</th>'
                   "<th>名称</th><th>权利人</th><th>申请日</th></tr></thead><tbody>%s</tbody></table></div>" % (len(listed), rows))
    lens = task.data.get("lens") or []
    if lens:
        out.append("<h3>用商品主图搜到的长得像的网页（前 %d 条）</h3>%s" % (min(len(lens), 10), items(
            "%s：%s" % (m.get("source", ""), m.get("title", "")) for m in lens[:10])))
    signals = task.data.get("enforcement") or []
    if signals:
        out.append("<h3>维权相关的网页（前 %d 条）</h3><ul>%s</ul>" % (min(len(signals), 8), "".join(
            "<li>%s</li>" % link(m.get("link"), m.get("title") or m.get("link")) for m in signals[:8])))
    return "<section><details><summary>这次查了什么（%d 条检索，%d 件候选）</summary>%s</details></section>" % (
        len(task["searches"]), len(task["candidates"]), "".join(out))


def block_footer(task, usage: dict) -> str:
    minutes = usage["seconds"] / 60.0
    if task["demo"]:
        tokens = "演示数据，没有真实的 AI 会话"
    elif usage["unknown_sessions"]:
        tokens = "%s token（另有 %d 个会话用量未知）" % (format(usage["tokens"], ","), usage["unknown_sessions"])
    else:
        tokens = "%s token" % format(usage["tokens"], ",")
    calls = "，".join("%s %d 次" % (k, v) for k, v in sorted(usage["source_calls"].items())) or "无"
    sessions = "用了 %d 份固定样例" % usage["sessions"] if task["demo"] else "AI 会话 %d 个" % usage["sessions"]
    spent = "本单用时 %.1f 分钟" % minutes
    if usage.get("resumed"):  # 续跑过：累计的和这一次的分开写
        spent = "本单累计用时 %.1f 分钟（这一次运行 %.1f 分钟）" % (minutes, usage.get("run_seconds", 0) / 60.0)
    notes = []
    if usage.get("shared"):
        notes.append("跑的时候这台电脑上同时还有别的单在跑，时间线按 %d 分钟算" % (usage.get("limit_seconds", 0) // 60))
    if not task["demo"] and usage.get("within_limit") is False:
        notes.append("超出了每单 %d 分钟、%d 万 token 的线" % (usage.get("limit_seconds", 0) // 60, usage.get("limit_tokens", 0) // 10000))
    steps = " · ".join("%s %.0f 秒" % (config.STEP_NAMES.get(name, name), seconds)
                       for name, seconds in (usage.get("steps") or {}).items() if seconds >= 1 and name in config.STEP_NAMES)
    return ("<footer>%s · %s · %s · 检索接口调用：%s · 采集方式：%s · Skill 版本 %s%s%s<br>"
            "本报告是选品用的风险预判，不是法律意见。</footer>") % (
        e(spent), sessions, e(tokens), e(calls), e(task["product"].get("captured_by") or "—"), e(config.VERSION),
        "<br>各步用时：%s" % e(steps) if steps else "", "<br>%s。" % e("；".join(notes)) if notes else "")


def render(task, usage_summary: dict, result: dict) -> str:
    body = "".join([block_top(task, result), block_rights(task), block_findings(task), block_pending(task), block_manual_marks(task), block_image_notes(task), block_competitors(task),
                    block_incomplete(task), block_searches(task), block_footer(task, usage_summary)])
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>侵权风险排查报告 - %s</title><style>%s</style></head><body><main>%s</main></body></html>") % (
        e(task["product"].get("title", "")), CSS, body)
