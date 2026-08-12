#!/usr/bin/env python3
"""Build the fixed-format Markdown and self-contained HTML evidence dossier."""

from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from common import atomic_write_json, ensure_object, load_json, now_iso, sha256_file, sha256_json


REPORT_SCHEMA_VERSION = "1.0"
MODULE_NAMES = {
    "appearance_patent": "外观设计 / 外观专利",
    "utility_patent": "实用 / 发明专利",
    "pending_application": "待审申请",
    "word_mark": "文字商标",
    "figurative_trade_dress": "图形商标与商业外观",
    "copyright_ip": "版权与角色 IP",
    "enforcement": "执法与争议",
}
RISK_CLASS = {"极低": "very-low", "低": "low", "中": "medium", "高": "high", "极高": "critical"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SENSITIVE_QUERY_KEYS = {"requesttoken", "token", "api_key", "apikey", "key", "access_token", "client_secret"}


def text(value: Any) -> str:
    return str(value if value is not None else "")


def esc(value: Any) -> str:
    return html.escape(text(value), quote=True)


def md_escape(value: Any) -> str:
    return text(value).replace("|", "\\|").replace("\n", " ")


def sanitize_url(value: Any) -> str:
    raw = text(value).strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query = urlencode([(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.casefold() not in SENSITIVE_QUERY_KEYS])
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except ValueError:
        return ""


def image_label(path: Path, role: str = "") -> str:
    name = path.stem.casefold()
    if role == "main":
        return "Amazon 当前变体主图"
    labels = (
        ("figures", "USPTO 专利图样页"),
        ("uspto-patent", "USPTO 专利检索证据"),
        ("design", "USPTO 专利图样证据"),
        ("drawing", "USPTO 专利图样证据"),
        ("patent-detail", "USPTO 专利详情证据"),
        ("patent-search", "USPTO 专利检索证据"),
        ("tsdr", "USPTO TSDR 商标核验证据"),
        ("tmsearch", "USPTO 商标检索证据"),
        ("product-core", "Amazon 商品主区域"),
        ("product-details", "Amazon 商品详情"),
        ("wipo", "WIPO PATENTSCOPE 检索证据"),
        ("espacenet", "Espacenet 检索证据"),
    )
    for needle, label in labels:
        if needle in name:
            return label
    return role.replace("_", " ").strip().title() or path.stem.replace("-", " ").title()


def walk_paths(value: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, str) and (str(key).endswith("path") or str(key) == "path"):
                yield current, item
            else:
                yield from walk_paths(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_paths(item, f"{prefix}[{index}]")


def key_evidence(task_dir: Path, task: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(path_value: Any, role: str, source: str, label: str = "") -> None:
        path = Path(text(path_value)).expanduser().resolve()
        if not path.is_file() or path.suffix.casefold() not in IMAGE_SUFFIXES:
            return
        try:
            path.relative_to(task_dir)
        except ValueError:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        relative = Path(os.path.relpath(path, task_dir)).as_posix()
        records.append({
            "path": key,
            "relative_path": relative,
            "label": label or image_label(path, role),
            "role": role,
            "source": source,
            "sha256": sha256_file(path),
        })

    for image in task.get("images", []):
        if isinstance(image, dict):
            add(image.get("path"), str(image.get("role") or "main"), "amazon_browser")
    browser = evidence.get("collections", {}).get("browser", [])
    if browser and isinstance(browser[0], dict):
        for role, path in browser[0].get("screenshots", {}).items():
            add(path, str(role), "amazon_browser")
    # Older runs sometimes saved official drawings without adding their path to
    # capture JSON. Include only clearly named evidence files from screenshots/.
    screenshot_dir = task_dir / "screenshots"
    if screenshot_dir.is_dir():
        evidence_pattern = re.compile(r"design|drawing|figures|patent-detail|patent-search|tsdr|tmsearch|product-core|product-details|wipo|espacenet", re.I)
        for path in sorted(screenshot_dir.iterdir()):
            # A transient TSDR navigation blank is not probative once a later
            # case-page capture succeeds; keep real registry blockers such as
            # WIPO/Espacenet, but omit this superseded debugging artifact.
            if path.name.casefold().startswith("tsdr-") and "access-limited" in path.name.casefold():
                continue
            if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES and evidence_pattern.search(path.name):
                add(path, "discovered_evidence", "task_screenshots")
    for collection_name, collection in evidence.get("collections", {}).items():
        for dotted_key, path in walk_paths(collection):
            role = dotted_key.rsplit(".", 1)[-1]
            add(path, role, collection_name)
    return records[:16]


def report_candidates(candidates: dict[str, Any], journal: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind in ("patents", "trademarks"):
        for item in candidates.get(kind, []):
            if isinstance(item, dict) and (item.get("material") or item.get("official_verification", {}).get("status") == "verified"):
                identifier = candidate_identifier(item)
                key = (kind, identifier.casefold())
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"kind": kind, **item})
    for entry in journal.get("entries", []):
        if not isinstance(entry, dict) or not entry.get("record_number"):
            continue
        identifier = text(entry.get("record_number"))
        key = ("patents", identifier.casefold())
        if key in seen:
            continue
        seen.add(key)
        status = text(entry.get("status") or "pending")
        rows.append({
            "kind": "patents",
            "record_number": identifier,
            "title": text(entry.get("title") or "浏览器已打开，候选信息待完成提取"),
            "owners": [],
            "official_verification": {
                "status": "capture_success_pending_ingest" if status == "success" else status,
                "url": sanitize_url(entry.get("final_url")),
            },
        })
    return rows


def candidate_identifier(item: dict[str, Any]) -> str:
    return next((text(item.get(key)) for key in ("publication_number", "grant_number", "application_number", "serial_number", "registration_number", "record_number") if item.get(key)), "—")


def short_title(value: Any, maximum_words: int = 15) -> str:
    raw = text(value).strip()
    words = raw.split()
    return raw if len(words) <= maximum_words else " ".join(words[:maximum_words]) + "…"


def fixed_manifest(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any],
    assessment: dict[str, Any], candidates: dict[str, Any], journal: dict[str, Any],
) -> dict[str, Any]:
    task_for_digest = {**task, "outputs": {}}
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "task_id": task.get("task_id"),
        "generated_at": now_iso(),
        "section_order": ["decision", "modules", "material_rights", "key_evidence", "coverage", "actions", "disclaimer"],
        "input_digests": {
            "task": sha256_json(task_for_digest), "evidence": sha256_json(evidence),
            "assessment": sha256_json(assessment), "candidates": sha256_json(candidates),
            "candidate_journal": sha256_json(journal),
        },
        "key_evidence": key_evidence(task_dir, task, evidence),
    }


def markdown(
    task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    candidates: dict[str, Any], journal: dict[str, Any], manifest: dict[str, Any],
) -> str:
    product = task.get("product", {})
    overall = assessment.get("overall", {})
    lines = [
        "# Amazon 知识产权风险筛查报告（免费数据源版）", "",
        f"- 报告格式：`IPR Evidence Dossier v{REPORT_SCHEMA_VERSION}`",
        f"- 任务：`{md_escape(task.get('task_id'))}`",
        f"- ASIN：`{md_escape(product.get('actual_asin') or product.get('requested_asin'))}`",
        f"- 商品：{md_escape(product.get('title'))}",
        f"- 站点 / 法域：{md_escape(task.get('request', {}).get('marketplace'))} / {md_escape(', '.join(task.get('target_jurisdictions', [])))}",
        f"- 状态：`{md_escape(assessment.get('status'))}`", "",
        "## 1. 决策结论", "",
    ]
    if assessment.get("status") == "completed":
        lines += [f"- 总风险：**{md_escape(overall.get('risk'))}**", f"- 风险驱动置信度：**{md_escape(overall.get('confidence'))}**"]
    else:
        lines.append("当前证据不足以生成最终风险等级。")
    lines += [f"- {md_escape(reason)}" for reason in overall.get("reasons", [])]
    lines += ["", "## 2. 模块评估", "", "| 模块 | 风险 | 置信度 | 说明 |", "|---|---|---|---|"]
    findings: list[str] = []
    for module_id in MODULE_NAMES:
        module = assessment.get("modules", {}).get(module_id, {})
        lines.append(f"| {MODULE_NAMES[module_id]} | {md_escape(module.get('risk'))} | {md_escape(module.get('confidence'))} | {md_escape(module.get('reasoning'))} |")
        for finding in module.get("findings", []):
            findings.append(f"- **{md_escape(finding.get('title'))}**：{md_escape(finding.get('recommended_action'))}；证据：`{md_escape(', '.join(finding.get('evidence_refs', [])))}`")
    if findings:
        lines += ["", "### 模块发现与动作", "", *findings]
    lines += ["", "## 3. 重要权利候选", "", "| 类型 | 编号 | 标题 / 商标 | 权利人 | 官方核验 |", "|---|---|---|---|---|"]
    rights = report_candidates(candidates, journal)
    for item in rights:
        verification = item.get("official_verification", {})
        label = item.get("title") or item.get("mark_text") or "—"
        owner = item.get("owner") or ", ".join(map(str, item.get("owners", []))) or "—"
        url = sanitize_url(verification.get("url"))
        verified = f"{verification.get('status', 'not_checked')} {url}".strip()
        lines.append(f"| {md_escape(item['kind'])} | {md_escape(candidate_identifier(item))} | {md_escape(label)} | {md_escape(owner)} | {md_escape(verified)} |")
    if not rights:
        lines.append("| — | — | 未形成重要候选 | — | — |")
    lines += ["", "## 4. 关键证据", ""]
    for index, item in enumerate(manifest["key_evidence"], 1):
        lines += [f"### 4.{index} {md_escape(item['label'])}", "", f"![{md_escape(item['label'])}]({item['relative_path']})", "", f"- 来源：`{md_escape(item['source'])}`", f"- SHA-256：`{item['sha256']}`", ""]
    coverage = assessment.get("coverage", {})
    lines += ["## 5. 覆盖与数据源", "", f"- 缺失必要来源：`{md_escape(', '.join(coverage.get('missing_required_sources', [])) or '无')}`", f"- 缺失必要查询：`{md_escape(', '.join(coverage.get('missing_required_queries', [])) or '无')}`", f"- 未完成低风险门禁：`{md_escape(', '.join(coverage.get('missing_low_risk_gate_sources', [])) or '无')}`", f"- 可选来源损失：`{md_escape(', '.join(coverage.get('optional_source_losses', [])) or '无')}`", ""]
    lines += ["## 6. 建议动作", ""] + [f"- {md_escape(action)}" for action in assessment.get("recommended_actions", [])]
    if not assessment.get("recommended_actions"):
        lines.append("- 根据模块发现补充官方核验或授权材料。")
    lines += ["", "## 7. 声明", "", "本报告是面向 Amazon 卖家运营的知识产权风险初筛，不构成律师出具的法律意见、FTO 法律结论或不侵权保证。", ""]
    return "\n".join(lines)


def evidence_gallery(items: list[dict[str, str]]) -> str:
    cards = []
    for index, item in enumerate(items, 1):
        cards.append(f"""
        <figure class="evidence-card" id="evidence-{index}">
          <a class="evidence-image" href="{esc(item['relative_path'])}" target="_blank" rel="noopener">
            <img src="{esc(item['relative_path'])}" alt="{esc(item['label'])}" loading="lazy">
            <span class="evidence-index">EV·{index:02d}</span>
          </a>
          <figcaption>
            <strong>{esc(item['label'])}</strong>
            <span>{esc(item['source'])}</span>
            <code title="{esc(item['sha256'])}">{esc(item['sha256'][:16])}…</code>
          </figcaption>
        </figure>""")
    return "".join(cards) or '<p class="empty">没有可展示的关键图片证据。</p>'


def html_report(
    task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    candidates: dict[str, Any], journal: dict[str, Any], manifest: dict[str, Any],
) -> str:
    product = task.get("product", {})
    overall = assessment.get("overall", {})
    risk = text(overall.get("risk") or "未定级")
    risk_class = RISK_CLASS.get(risk, "pending")
    module_cards = []
    for module_id, label in MODULE_NAMES.items():
        module = assessment.get("modules", {}).get(module_id, {})
        findings = "".join(
            f'<li><strong>{esc(item.get("title"))}</strong><span>{esc(item.get("recommended_action"))}</span><code>{esc(", ".join(item.get("evidence_refs", [])))}</code></li>'
            for item in module.get("findings", [])
        ) or '<li class="empty">未记录具体发现</li>'
        module_cards.append(f"""
        <article class="module-card">
          <header><span>{esc(label)}</span><b class="risk-chip {RISK_CLASS.get(text(module.get('risk')), 'pending')}">{esc(module.get('risk') or '—')}</b></header>
          <p>{esc(module.get('reasoning'))}</p>
          <div class="confidence">置信度 <strong>{esc(module.get('confidence') or '—')}</strong></div>
          <ul>{findings}</ul>
        </article>""")

    rights_rows = []
    for item in report_candidates(candidates, journal):
        verification = item.get("official_verification", {})
        label = item.get("title") or item.get("mark_text") or "—"
        owner = item.get("owner") or ", ".join(map(str, item.get("owners", []))) or "—"
        url = sanitize_url(verification.get("url"))
        status = esc(verification.get("status") or "not_checked")
        official = f'<a href="{esc(url)}" target="_blank" rel="noopener">{status}</a>' if url else status
        rights_rows.append(f"<tr><td>{'专利 / 设计' if item['kind']=='patents' else '商标'}</td><td><code>{esc(candidate_identifier(item))}</code></td><td>{esc(label)}</td><td>{esc(owner)}</td><td>{official}</td></tr>")
    if not rights_rows:
        rights_rows.append('<tr><td colspan="5" class="empty">未形成重要候选，不能据此推定不存在权利。</td></tr>')

    source_rows = []
    for run in evidence.get("source_runs", []):
        source_rows.append(f'<tr><td>{esc(run.get("provider"))}</td><td>{esc(run.get("operation"))}</td><td><span class="status status-{esc(run.get("status"))}">{esc(run.get("status"))}</span></td><td>{esc(run.get("jurisdiction"))}</td><td>{esc(run.get("error_code"))}</td></tr>')
    coverage = assessment.get("coverage", {})
    coverage_items = [
        ("必要来源", coverage.get("missing_required_sources", [])),
        ("必要查询", coverage.get("missing_required_queries", [])),
        ("低风险门禁", coverage.get("missing_low_risk_gate_sources", [])),
        ("可选来源", coverage.get("optional_source_losses", [])),
    ]
    coverage_html = "".join(f'<div><span>{esc(label)}</span><strong>{esc(", ".join(values) or "完整")}</strong></div>' for label, values in coverage_items)
    reasons = "".join(f"<li>{esc(reason)}</li>" for reason in overall.get("reasons", [])) or "<li>未记录补充理由。</li>"
    actions = "".join(f"<li>{esc(action)}</li>" for action in assessment.get("recommended_actions", [])) or "<li>根据模块发现补充官方核验或授权材料。</li>"

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="report-schema" content="IPR-EVIDENCE-DOSSIER/{REPORT_SCHEMA_VERSION}">
<title>{esc(product.get('actual_asin') or product.get('requested_asin'))} · 知识产权风险卷宗</title>
<style>
:root{{--paper:#f4f6f3;--sheet:#fff;--ink:#172126;--muted:#637078;--line:#cbd2cf;--navy:#173f5f;--blue:#2a6690;--red:#b52b2f;--amber:#bd7418;--green:#27724d;--soft:#e9eeeb;--mono:ui-monospace,SFMono-Regular,Menlo,monospace;--body:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif;--display:Georgia,"Songti SC",serif}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 var(--body)}}a{{color:var(--blue);text-underline-offset:3px}}a:focus-visible{{outline:3px solid #5ba4d0;outline-offset:3px}}.shell{{max-width:1180px;margin:auto;padding:28px}}.case-header{{position:relative;display:grid;grid-template-columns:1fr 230px;gap:34px;background:var(--navy);color:#fff;padding:44px 48px;border-top:8px solid #0e263a;overflow:hidden}}.case-header:after{{content:"IPR";position:absolute;right:250px;bottom:-52px;color:#ffffff0c;font:900 180px/1 var(--display);letter-spacing:-12px}}.eyebrow{{font:700 11px/1 var(--mono);letter-spacing:.18em;text-transform:uppercase;color:#b9d3e5}}h1{{max-width:790px;margin:14px 0 12px;font:700 clamp(30px,4vw,48px)/1.08 var(--display);letter-spacing:-.025em}}.full-title{{max-width:790px;margin:0 0 20px;color:#c9dae6;font-size:13px}}.case-meta{{display:flex;flex-wrap:wrap;gap:8px 20px;color:#dce8f0}}.case-meta code{{color:#fff}}.risk-seal{{z-index:1;align-self:center;aspect-ratio:1;display:grid;place-content:center;text-align:center;border:2px solid #ffffff88;outline:1px solid #ffffff35;outline-offset:-9px;border-radius:50%;transform:rotate(-4deg);background:#ffffff0a}}.risk-seal span{{font:700 11px var(--mono);letter-spacing:.2em}}.risk-seal strong{{font:800 46px/1.1 var(--display)}}.risk-seal small{{color:#dce8f0}}.risk-seal.critical,.risk-seal.high{{background:#8d1f28}}.risk-seal.medium{{background:#8d5b15}}.risk-seal.low,.risk-seal.very-low{{background:#246044}}main{{background:var(--sheet);box-shadow:0 18px 70px #18334418}}section{{padding:42px 48px;border-bottom:1px solid var(--line)}}.section-head{{display:grid;grid-template-columns:145px 1fr;gap:28px;margin-bottom:26px}}.section-head span{{font:700 11px var(--mono);letter-spacing:.14em;color:var(--blue);text-transform:uppercase}}h2{{margin:0;font:700 28px/1.18 var(--display)}}.decision-grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:28px}}.decision-note{{padding:24px;border-left:5px solid var(--red);background:#f8eeee}}.decision-note strong{{display:block;font:700 20px var(--display);margin-bottom:8px}}.decision-note ul,.actions{{margin:10px 0 0;padding-left:20px}}.coverage-strip{{display:grid;gap:1px;background:var(--line);border:1px solid var(--line)}}.coverage-strip div{{display:grid;grid-template-columns:120px 1fr;gap:16px;padding:12px 14px;background:#fff}}.coverage-strip span{{color:var(--muted)}}.modules{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.module-card{{border:1px solid var(--line);padding:20px;background:#fff}}.module-card header{{display:flex;align-items:center;justify-content:space-between;gap:16px;font-weight:750}}.module-card p{{min-height:48px;color:#34434b}}.module-card ul{{padding:0;margin:16px 0 0;list-style:none;border-top:1px solid var(--line)}}.module-card li{{display:grid;gap:3px;padding:12px 0;border-bottom:1px dotted var(--line)}}.module-card li span{{color:var(--muted)}}.module-card code{{font-size:11px;color:var(--blue)}}.confidence{{font:12px var(--mono);color:var(--muted)}}.risk-chip{{padding:3px 9px;border:1px solid currentColor;font:700 12px var(--mono)}}.risk-chip.critical,.risk-chip.high{{color:var(--red)}}.risk-chip.medium{{color:var(--amber)}}.risk-chip.low,.risk-chip.very-low{{color:var(--green)}}.table-wrap{{overflow:auto;border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:12px 14px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{position:sticky;top:0;background:var(--soft);font:700 11px var(--mono);letter-spacing:.06em}}td code{{font-size:12px}}.evidence-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.evidence-card{{margin:0;border:1px solid var(--line);background:#f8faf8}}.evidence-image{{position:relative;display:block;aspect-ratio:4/3;background:#dfe5e2;overflow:hidden}}.evidence-image img{{width:100%;height:100%;object-fit:contain;display:block;transition:transform .18s ease}}.evidence-image:hover img{{transform:scale(1.015)}}.evidence-index{{position:absolute;left:0;top:0;padding:7px 10px;background:var(--navy);color:#fff;font:700 11px var(--mono);letter-spacing:.1em}}figcaption{{display:grid;grid-template-columns:1fr auto;gap:4px 14px;padding:14px 16px}}figcaption strong{{font-family:var(--display)}}figcaption span{{grid-column:1;color:var(--muted);font-size:12px}}figcaption code{{grid-column:2;grid-row:1/3;align-self:center;font-size:11px;color:var(--blue)}}.status{{font:700 11px var(--mono)}}.status-success,.status-no_result{{color:var(--green)}}.status-failed,.status-access_limited,.status-needs_user_action{{color:var(--red)}}.empty{{color:var(--muted);font-style:italic}}.notice{{background:#f2f5f3;border-left:5px solid var(--navy);padding:18px 20px}}footer{{padding:24px 48px;background:#172126;color:#d7e0dc;display:flex;justify-content:space-between;gap:20px;font:11px var(--mono)}}
@media(max-width:760px){{.shell{{padding:0}}.case-header{{grid-template-columns:1fr;padding:34px 24px}}.risk-seal{{width:170px}}section{{padding:34px 22px}}.section-head,.decision-grid{{grid-template-columns:1fr}}.modules,.evidence-grid{{grid-template-columns:1fr}}footer{{padding:22px;flex-direction:column}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}.evidence-image img{{transition:none}}}}
@media print{{body{{background:#fff}}.shell{{max-width:none;padding:0}}main{{box-shadow:none}}.case-header{{break-after:avoid}}.module-card,.evidence-card{{break-inside:avoid}}a{{color:inherit;text-decoration:none}}}}
</style></head>
<body><div class="shell"><main>
<header class="case-header">
  <div><div class="eyebrow">IPR evidence dossier · v{REPORT_SCHEMA_VERSION}</div><h1 title="{esc(product.get('title'))}">{esc(short_title(product.get('title') or 'Amazon 商品知识产权筛查'))}</h1><p class="full-title">{esc(product.get('title'))}</p>
  <div class="case-meta"><span>ASIN <code>{esc(product.get('actual_asin') or product.get('requested_asin'))}</code></span><span>CASE <code>{esc(task.get('task_id'))}</code></span><span>{esc(task.get('request',{}).get('marketplace'))} · {esc(', '.join(task.get('target_jurisdictions',[])))}</span></div></div>
  <div class="risk-seal {risk_class}"><span>OVERALL RISK</span><strong>{esc(risk)}</strong><small>置信度 {esc(overall.get('confidence') or '未定')}</small></div>
</header>
<section id="decision"><div class="section-head"><span>01 / Decision</span><h2>决策结论</h2></div><div class="decision-grid"><div class="decision-note"><strong>{'可以形成最终等级' if assessment.get('status')=='completed' else '证据链尚未闭合'}</strong><ul>{reasons}</ul></div><div class="coverage-strip">{coverage_html}</div></div></section>
<section id="modules"><div class="section-head"><span>02 / Modules</span><h2>七模块风险审查</h2></div><div class="modules">{''.join(module_cards)}</div></section>
<section id="rights"><div class="section-head"><span>03 / Rights</span><h2>重要权利候选与官方核验</h2></div><div class="table-wrap"><table><thead><tr><th>类型</th><th>编号</th><th>标题 / 商标</th><th>权利人</th><th>官方状态</th></tr></thead><tbody>{''.join(rights_rows)}</tbody></table></div></section>
<section id="evidence"><div class="section-head"><span>04 / Evidence</span><h2>关键证据接触印样</h2></div><div class="evidence-grid">{evidence_gallery(manifest['key_evidence'])}</div></section>
<section id="sources"><div class="section-head"><span>05 / Sources</span><h2>来源执行记录</h2></div><div class="table-wrap"><table><thead><tr><th>数据源</th><th>操作</th><th>状态</th><th>法域</th><th>错误码</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div></section>
<section id="actions"><div class="section-head"><span>06 / Action</span><h2>建议动作</h2></div><ol class="actions">{actions}</ol></section>
<section id="disclaimer"><div class="section-head"><span>07 / Notice</span><h2>使用边界</h2></div><div class="notice">本报告是面向 Amazon 卖家运营的知识产权风险初筛，不构成律师出具的法律意见、FTO 法律结论或不侵权保证。</div></section>
<footer><span>REPORT · {esc(task.get('task_id'))}</span><span>GENERATED · {esc(manifest.get('generated_at'))}</span><span>SCHEMA · IPR-EVIDENCE-DOSSIER/{REPORT_SCHEMA_VERSION}</span></footer>
</main></div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build fixed-format Markdown and HTML IPR reports.")
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    assessment = ensure_object(load_json(task_dir / "assessment.json"), "assessment.json")
    candidate_path = task_dir / "normalized-candidates.json"
    candidates = ensure_object(load_json(candidate_path), "normalized-candidates.json") if candidate_path.exists() else {"patents": [], "trademarks": []}
    journal_path = task_dir / "browser-candidate-journal.json"
    journal = ensure_object(load_json(journal_path), "browser-candidate-journal.json") if journal_path.exists() else {"schema_version": "1.0", "task_id": task.get("task_id"), "entries": []}
    manifest = fixed_manifest(task_dir, task, evidence, assessment, candidates, journal)
    markdown_text = markdown(task, evidence, assessment, candidates, journal, manifest)
    html_text = html_report(task, evidence, assessment, candidates, journal, manifest)
    (task_dir / "report.md").write_text(markdown_text, encoding="utf-8")
    (task_dir / "report.html").write_text(html_text, encoding="utf-8")
    atomic_write_json(task_dir / "report-manifest.json", manifest)
    task.setdefault("outputs", {}).update({
        "report_md": str(task_dir / "report.md"),
        "report_html": str(task_dir / "report.html"),
        "report_manifest": str(task_dir / "report-manifest.json"),
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": manifest["generated_at"],
        "input_digests": manifest["input_digests"],
    })
    atomic_write_json(task_dir / "task.json", task)
    print(task_dir / "report.md")


if __name__ == "__main__":
    main()
