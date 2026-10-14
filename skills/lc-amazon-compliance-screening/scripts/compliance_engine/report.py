"""Single view model (report_data) and its renderers: HTML, Markdown, CSV, copy-constraint text."""
from __future__ import annotations

import csv
import html
import io
import time

from .common import (CONFIDENCE_ZH, DECISION_ZH, FBA_ZH, KIND_ZH, LAYER_ZH, QUICK_VERDICT_ZH, SITE_ZH,
                     VERDICT_ZH)

REPORT_SCHEMA = "compliance-report-v1"
DISCLAIMER = ("本报告依据规则库收录的亚马逊政策与当地法规做筛查，帮助判断上架前要准备什么；它不是法律意见，"
              "也不保证商品可以销售。规则库只覆盖已收录的条目，未命中不等于没有要求。正式上架前请以亚马逊后台"
              "（含 Add Products 显示的限制）和主管机构的最新要求为准，高风险品类建议咨询当地合规顾问。")
ICON = {"prohibited": "⛔", "approval_required": "🔒", "compliance_required": "📋", "no_specific_restriction": "✅",
        "needs_info": "❓"}


def build_view(pack, facts, assessment, mode, profile=None, extra=None) -> dict:
    labels = QUICK_VERDICT_ZH if mode == "quick" else VERDICT_ZH
    sites, used_sources = [], set()
    for r in assessment["sites"]:
        item = dict(r)
        item.update(site_zh=SITE_ZH.get(r["site"], r["site"]), verdict_zh=labels[r["verdict"]],
                    decision_zh=("初筛 · " if mode == "quick" else "") + DECISION_ZH[r["verdict"]],
                    fba_zh=FBA_ZH[r["fba"]], confidence_zh=CONFIDENCE_ZH[r["confidence"]],
                    icon=ICON[r["verdict"]])
        for group in ("requirements", "general_obligations"):
            for q in item.get(group) or []:
                q["kind_zh"] = KIND_ZH.get(q.get("kind"), q.get("kind"))
                used_sources.update(q.get("sources") or [])
        for a in item.get("applied") or []:
            a["layer_zh"] = LAYER_ZH.get(a["layer"], a["layer"])
            used_sources.update(pack.rules.get(a["rule_id"], {}).get("sources") or [])
        item.update(((extra or {}).get("business_results") or {}).get(r["site"]) or {})
        sites.append(item)
    p = (facts or {}).get("product") or {}
    fam_zh = [pack.families.get(f["id"], {}).get("zh", f["id"]) for f in (profile or {}).get("families") or []]
    view = {
        "schema": REPORT_SCHEMA, "mode": mode, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ruleset": {"version": pack.version, "digest": pack.digest},
        "product": {"title": p.get("title"), "asin": p.get("asin"), "url": p.get("url"),
                    "source_site": p.get("source_site"), "brand": p.get("brand"),
                    "image_count": len((facts or {}).get("images") or []), "families_zh": fam_zh,
                    "name_zh": ((profile or {}).get("product") or {}).get("name_zh")},
        "sites": sites,
        "sources": [{"id": s, "title": pack.sources[s].get("title"), "url": pack.sources[s].get("url"),
                     "level": pack.sources[s].get("level"), "accessed": pack.sources[s].get("accessed")}
                    for s in sorted(used_sources) if s in pack.sources],
        "disclaimer_zh": DISCLAIMER,
    }
    if extra:
        view.update({k: v for k, v in extra.items() if k != "business_results"})
    if sites and all("classification_complete" in s for s in sites):
        view["classification_complete"] = all(s["classification_complete"] for s in sites)
    return view


def _e(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--muted:#6b6b6b;--line:#e3e3df;--bad:#b42318;--warn:#b54708;--info:#175cd3;--ok:#067647}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#ececec;--muted:#a0a0a0;--line:#333;--bad:#f97066;--warn:#fdb022;--info:#84adff;--ok:#47cd89}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}h3{font-size:15px;margin:18px 0 8px}
.meta{color:var(--muted);font-size:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:7px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}.v-prohibited{color:var(--bad)}.v-approval_required{color:var(--warn)}
.v-compliance_required{color:var(--info)}.v-no_specific_restriction{color:var(--ok)}.v-needs_info{color:var(--warn)}
.tag{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 8px;font-size:12px;margin-right:4px}
.big{font-size:18px;font-weight:700}details summary{cursor:pointer;color:var(--muted)}a{color:var(--info);word-break:break-all}
.wrap{overflow-x:auto}.note{color:var(--muted);font-size:12px}
"""


def render_html(view) -> str:
    mode_zh = {"quick": "初筛", "formal": "正式", "draft": "草稿"}[view["mode"]]
    p = view["product"]
    out = ["<!doctype html><html lang=zh-CN><head><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           f"<title>禁限售预检报告</title><style>{CSS}</style></head><body><main>",
           f"<h1>禁限售预检报告 · {mode_zh}</h1>",
           f"<div class=meta>{_e(p.get('title'))}<br>ASIN {_e(p.get('asin') or '—')} · 来源站点 {_e(p.get('source_site') or '—')}"
           f" · 规则库 {_e(view['ruleset']['version'])} · 生成于 {_e(view['generated_at'])}</div>"]
    if p.get("families_zh"):
        out.append("<div class=meta>产品族：" + "、".join(_e(x) for x in p["families_zh"]) + "</div>")
    out.append("<h2>各站点结论</h2><div class='card wrap'><table><tr><th>站点</th><th>业务标记</th><th>FBA</th><th>置信度</th><th>说明</th></tr>")
    for s in view["sites"]:
        out.append(f"<tr><td>{_e(s['site_zh'])}</td><td class='big'>{_e(s.get('mark', s['verdict_zh']))}</td>"
                   f"<td>{_e(s['fba_zh'])}</td><td>{_e(s['confidence_zh'])}</td><td>{_e(s.get('detail', s['decision_zh']))}</td></tr>")
    out.append("</table></div>")
    for s in view["sites"]:
        out.append(f"<h2>{_e(s['site_zh'])}：{_e(s.get('mark', s['decision_zh']))}</h2><div class=card>")
        if s.get("detail"):
            out.append(f"<p>{_e(s['detail'])}</p><p class=note>法规规则结论：{_e(s['verdict_zh'])}；FBA：{_e(s['fba_zh'])}</p>")
        if s.get("summary_zh"):
            out.append(f"<p>{_e(s['summary_zh'])}</p>")
        out.append(f"<p class=note>置信度：{_e(s['confidence_zh'])}。{_e(s.get('confidence_reason_zh'))}</p>")
        for n in s.get("notes") or []:
            out.append(f"<p class=note>{_e(n)}</p>")
        if s.get("applied"):
            out.append("<h3>命中的规则</h3><div class=wrap><table><tr><th>层级</th><th>要求</th><th>判断依据</th><th>规则</th></tr>")
            for a in s["applied"]:
                out.append(f"<tr><td>{_e(a['layer_zh'])}</td><td class='v-{_e(a['severity'])}'>{_e(a['topic_zh'])}</td>"
                           f"<td>{_e(a.get('reason_zh'))}</td><td class=note>{_e(a['rule_id'])}</td></tr>")
            out.append("</table></div>")
        if s.get("requirements"):
            out.append("<h3>上架前要准备的</h3><div class=wrap><table><tr><th>类型</th><th>事项</th><th>说明</th><th>谁出具</th><th>在哪提交</th></tr>")
            for q in s["requirements"]:
                out.append(f"<tr><td>{_e(q['kind_zh'])}</td><td>{_e(q['name_zh'])}</td><td>{_e(q.get('detail_zh'))}</td>"
                           f"<td>{_e(q.get('issuer_zh'))}</td><td>{_e(q.get('submit_via_zh'))}</td></tr>")
            out.append("</table></div>")
        if s.get("open_questions"):
            out.append("<h3>待补信息</h3><ul>")
            for q in s["open_questions"]:
                out.append(f"<li><b>{_e(q['topic_zh'])}</b>：{_e(q.get('question_zh'))}</li>")
            out.append("</ul>")
        c = s.get("constraints") or {}
        if c.get("forbid_claims") or c.get("required_statements"):
            out.append("<h3>文案约束</h3><ul>")
            for f in c.get("forbid_claims") or []:
                out.append(f"<li>{'必须' if f['strength'] == 'must' else '建议核对'}：不得宣称「{_e(f['claim_zh'])}」</li>")
            for r in c.get("required_statements") or []:
                out.append(f"<li>{'必须' if r['strength'] == 'must' else '建议核对'}：{_e(r['text_zh'])}</li>")
            out.append("</ul>")
        if s.get("reminders"):
            out.append("<h3>提醒（不影响结论）</h3><ul>")
            for r in s["reminders"]:
                out.append(f"<li>{_e(r['text_zh'])} <span class=note>{_e(r['rule_id'])}</span></li>")
            out.append("</ul>")
        if s.get("general_obligations"):
            out.append(f"<details><summary>该站通用义务（{len(s['general_obligations'])} 项，所有商品都适用）</summary><ul>")
            for q in s["general_obligations"]:
                out.append(f"<li>{_e(q['kind_zh'])}：{_e(q['name_zh'])}{(' — ' + _e(q['detail_zh'])) if q.get('detail_zh') else ''}</li>")
            out.append("</ul></details>")
        out.append("</div>")
    if view.get("signals"):
        out.append("<h2>外部数据</h2><div class=card><ul>")
        for x in view["signals"]:
            out.append(f"<li>{_e(x)}</li>")
        out.append("</ul></div>")
    if view["sources"]:
        out.append("<h2>来源</h2><div class=card><ol>")
        for src in view["sources"]:
            out.append(f"<li>[{_e(src['level'])}] {_e(src['title'])} — <a href='{_e(src['url'])}' rel=noreferrer>{_e(src['url'])}</a>"
                       f" <span class=note>访问 {_e(src.get('accessed'))} · {_e(src['id'])}</span></li>")
        out.append("</ol></div>")
    cover = f"<p class=note>{_e(view['coverage_note_zh'])}</p>" if view.get("coverage_note_zh") else ""
    out.append(f"<h2>说明</h2>{cover}<p class=note>{_e(view['disclaimer_zh'])}</p></main></body></html>")
    return "".join(out)


def render_markdown(view) -> str:
    mode_zh = {"quick": "初筛", "formal": "正式", "draft": "草稿"}[view["mode"]]
    p = view["product"]
    lines = [f"# 禁限售预检报告（{mode_zh}）", "", f"- 商品：{p.get('title') or '—'}",
             f"- ASIN：{p.get('asin') or '—'}；规则库：{view['ruleset']['version']}", "",
             "| 站点 | 业务标记 | FBA | 置信度 |", "|---|---|---|---|"]
    for s in view["sites"]:
        lines.append(f"| {s['site_zh']} | {s.get('mark', s['verdict_zh'])} | {s['fba_zh']} | {s['confidence_zh']} |")
    for s in view["sites"]:
        lines += ["", f"## {s['site_zh']}：{s.get('mark', s['decision_zh'])}"]
        if s.get("detail"):
            lines += ["", s["detail"], "", f"法规规则结论：{s['verdict_zh']}；FBA：{s['fba_zh']}"]
        for q in s.get("requirements") or []:
            lines.append(f"- [{q['kind_zh']}] {q['name_zh']}" + (f"：{q['detail_zh']}" if q.get("detail_zh") else ""))
        for q in s.get("open_questions") or []:
            lines.append(f"- 待补：{q['topic_zh']} — {q.get('question_zh') or ''}")
        for n in s.get("notes") or []:
            lines.append(f"- 说明：{n}")
        for r in s.get("reminders") or []:
            lines.append(f"- 提醒：{r['text_zh']}（{r['rule_id']}）")
    if view.get("coverage_note_zh"):
        lines += ["", view["coverage_note_zh"]]
    lines += ["", view["disclaimer_zh"], ""]
    return "\n".join(lines)


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def render_csv(view) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["站点", "结论", "类型", "规则", "严重度", "事项", "说明"])
    for s in view["sites"]:
        if s.get("mark"):
            w.writerow([_cell(x) for x in (s["site"], s["mark"], "业务标记", "", "", s["mark"], s["detail"])])
        for a in s.get("applied") or []:
            w.writerow([_cell(x) for x in (s["site"], s["verdict"], "命中规则", a["rule_id"], a["severity"], a["topic_zh"], a.get("reason_zh"))])
        for q in s.get("requirements") or []:
            w.writerow([_cell(x) for x in (s["site"], s["verdict"], "要求", "、".join(q["rules"]), q["kind"], q["name_zh"], q.get("detail_zh"))])
        for q in s.get("open_questions") or []:
            w.writerow([_cell(x) for x in (s["site"], s["verdict"], "待补", q.get("rule_id"), q["severity"], q["topic_zh"], q.get("question_zh"))])
        for r in s.get("reminders") or []:
            w.writerow([_cell(x) for x in (s["site"], s["verdict"], "提醒", r["rule_id"], r["severity"], r["topic_zh"], r["text_zh"])])
    return "﻿" + buf.getvalue()


def constraints_text(site_result, source: str, limit: int = 2000) -> str:
    """Plain-text copy constraints for the Listing prompt; only curated rule-pack strings."""
    c = site_result.get("constraints") or {}
    tag = {"must": "必须", "check": "建议核对"}
    lines = []
    if source == "quick":
        lines.append("以下来自初筛（只看标题），用「建议核对」处理：")
    for f in c.get("forbid_claims") or []:
        lines.append(f"- {tag['check'] if source == 'quick' else tag[f['strength']]}：不得宣称「{f['claim_zh']}」（{f['rule']}）")
    for r in c.get("required_statements") or []:
        lines.append(f"- {tag['check'] if source == 'quick' else tag[r['strength']]}：{r['text_zh']}（{r['rule']}）")
    if site_result.get("verdict") in ("approval_required", "compliance_required"):
        lines.append("- 不得在文案中宣称已获得任何认证、注册或审批，除非资料中有证据。")
    if not lines:
        return ""
    lines.append("与技能默认写法冲突时以本约束为准，并在 06_qa.json 记录。")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[: limit - 20] + "\n（其余约束见预检报告）"
