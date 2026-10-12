"""Render an additive two-round niche report without rewriting the source HTML.

The renderer is deliberately calculation-free: it displays the committed scorer
evidence and never supplies fallback scores, membership, or conversion data.
"""
from __future__ import annotations

import html
import json
import math
import re
from typing import Any
from urllib.parse import urlsplit


COMPONENTS = {
    "supply_demand": "供需指数（80%）",
    "competition_openness": "竞争开放度（10%）",
    "new_product_evidence": "新品进入证据（5%）",
    "demand_scale": "需求承接规模（5%）",
}
RULES = (
    "review_dependency", "rating_requirement", "price_sensitivity",
    "best_price_bands", "new_product_cycle", "product_monopoly",
    "brand_monopoly", "ad_pressure",
)
RULE_LABELS = (
    "评论依赖性", "评分值依赖性", "价格敏感度", "最值得进入的价格带",
    "新品打造周期", "商品垄断度", "品牌垄断度", "广告压力指数",
)
MARKERS = ("NICHE_TWO_ROUND", "NICHE_TWO_ROUND_STYLE", "NICHE_TWO_ROUND_NAV")

STYLE = """<style id="niche-two-round-style">
#niche-two-round{margin-top:34px;color:var(--ink,#182638)}
#niche-two-round *{box-sizing:border-box}
#niche-two-round .ntr-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
#niche-two-round .ntr-card,#niche-two-round .ntr-rule{background:var(--card,#fff);border:1px solid var(--line,#dfe5ed);border-radius:14px;padding:18px;margin:14px 0}
#niche-two-round .ntr-rule{margin:0;padding:14px;overflow-wrap:anywhere}
#niche-two-round .ntr-rule h4{margin:0 0 8px}
#niche-two-round .ntr-badge{display:inline-block;background:#eaf1ff;color:#255d9c;border-radius:20px;padding:5px 10px;font-size:13px;margin-right:8px}
#niche-two-round .ntr-muted{color:var(--muted,#66758a);font-size:14px;line-height:1.7}
#niche-two-round .ntr-notice{border-left:4px solid #c28623;padding:12px 16px;background:#fff7e9;border-radius:6px}
#niche-two-round .ntr-table-frame{overflow:auto;max-width:100%;margin:12px 0;border:1px solid var(--line,#dfe5ed);border-radius:10px}
#niche-two-round table{border-collapse:collapse;width:100%;min-width:900px;font-size:13px}
#niche-two-round th,#niche-two-round td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line,#dfe5ed)}
#niche-two-round th{background:#f3f6fa;white-space:nowrap}
#niche-two-round .ntr-num{font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}
#niche-two-round .ntr-wrap{min-width:200px;max-width:380px;overflow-wrap:anywhere}
#niche-two-round .ntr-stat{border-radius:10px;background:#f4f7fb;padding:12px;overflow-wrap:anywhere}
#niche-two-round .ntr-stat b{display:block;margin-top:5px;font-size:21px}
#niche-two-round a{color:var(--blue,#235eaa)}
#niche-two-round details{margin:12px 0}
#niche-two-round summary{cursor:pointer;line-height:1.7}
#niche-two-round .ntr-formula{padding:12px;background:#f4f7fb;border-radius:8px;line-height:1.8}
#niche-two-round .ntr-section{margin-top:30px}
#niche-two-round .ntr-copy{margin:12px 0}
#niche-two-round .ntr-copy button{border:0;border-radius:8px;padding:9px 13px;background:#255d9c;color:#fff;cursor:pointer;font:inherit}
#niche-two-round .ntr-copy button:disabled{background:#9aa6b5;cursor:not-allowed}
#niche-two-round .ntr-copy-status{margin-left:8px;color:var(--muted,#66758a);font-size:14px}
#niche-two-round .ntr-copy-source{display:block;width:100%;min-height:88px;margin-top:10px;padding:8px;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
@media(max-width:980px){#niche-two-round .ntr-grid{grid-template-columns:repeat(2,minmax(0,1fr))}#niche-two-round .ntr-card{padding:14px}}
@media(max-width:540px){#niche-two-round .ntr-grid{grid-template-columns:1fr}}
</style>
<script id="niche-two-round-copy-script">
(()=>{const copy=button=>{const area=button.closest('.ntr-copy')?.querySelector('.ntr-copy-source');const status=button.closest('.ntr-copy')?.querySelector('.ntr-copy-status');if(!area||!status||!area.value){return;}const done=()=>{status.textContent=`已复制 ${button.dataset.count} 个 ASIN。`;area.hidden=true;};const fallback=()=>{area.hidden=false;area.focus();area.select();let copied=false;try{copied=document.execCommand('copy');}catch(_){copied=false;}if(copied){done();}else{status.textContent='复制受限，已选中 ASIN 文本，请手动复制。';}};if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(area.value).then(done,fallback);}else{fallback();}};document.addEventListener('click',event=>{const button=event.target.closest('.ntr-copy-button');if(button&&!button.disabled){copy(button);}});})();
</script>"""

REPORT_LAYOUT_VERSION = "two-round-competition-v1"

# 固定为两轮复评报告的视觉合同；数据只能替换内容，不能改变页面层级、卡片、表格或透视结构。
COMPETITION_LAYOUT = """<style id="niche-two-round-competition-style">
#niche-two-round{--ntr-ink:#162033;--ntr-muted:#667085;--ntr-line:#dce5ef;--ntr-soft:#f6f8fb;--ntr-blue:#1d4ed8;--ntr-blue-soft:#eef5ff;--ntr-green:#047857;--ntr-amber:#b96513;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;color:var(--ntr-ink)}
#niche-two-round>h2{position:relative;display:flex;align-items:center;gap:12px;margin:42px 0 12px;padding:0 0 14px 16px;border-bottom:1px solid var(--ntr-line);font-size:25px;letter-spacing:-.025em;line-height:1.2}
#niche-two-round>h2::before{position:absolute;left:0;width:4px;height:24px;border-radius:99px;background:linear-gradient(180deg,var(--ntr-blue),#5b8def);content:""}
#niche-two-round>h2::after{width:44px;height:1px;background:linear-gradient(90deg,var(--ntr-blue),transparent);content:""}
#niche-two-round>p.ntr-muted{max-width:980px;margin:0 0 26px;font-size:14px;line-height:1.82}
#niche-two-round .ntr-section{margin-top:36px}
#niche-two-round .ntr-section>h3{display:flex;align-items:center;gap:11px;margin-bottom:12px;color:#21314a;font-size:18px;letter-spacing:-.01em}
#niche-two-round .ntr-section>h3::before{width:7px;height:7px;border:2px solid var(--ntr-blue);border-radius:50%;background:#fff;box-shadow:0 0 0 4px var(--ntr-blue-soft);content:""}
#niche-two-round .ntr-section>h3::after{height:1px;flex:1;background:linear-gradient(90deg,#dce5ef,transparent);content:""}
#niche-two-round .ntr-card{position:relative;margin:16px 0;padding:21px 22px;border-color:var(--ntr-line);border-radius:13px;background:linear-gradient(145deg,#fff 0%,#fbfdff 100%);box-shadow:0 1px 2px rgba(22,32,51,.025),0 7px 18px rgba(30,58,95,.035)}
#niche-two-round .ntr-card>h4{margin:10px 0 14px;font-size:20px;letter-spacing:-.015em}
#niche-two-round .ntr-card>p{max-width:1100px;margin:10px 0;color:#43536a;line-height:1.78}
#niche-two-round .ntr-card>.ntr-muted{font-size:13px}
#niche-two-round .ntr-badge{padding:5px 10px;border:1px solid #cfe0ff;border-radius:999px;background:var(--ntr-blue-soft);color:#245ab5;font-size:12px;font-weight:750;letter-spacing:.015em}
#niche-two-round .ntr-grid{gap:10px}
#niche-two-round .ntr-stat{position:relative;min-height:86px;padding:13px 14px;border:1px solid #e2eaf4;border-radius:11px;background:linear-gradient(145deg,#f8fbff,#f2f6fb);color:#68778c;font-size:13px}
#niche-two-round .ntr-stat::after{position:absolute;right:12px;bottom:12px;width:20px;height:2px;border-radius:99px;background:#c9ddff;content:""}
#niche-two-round .ntr-stat b{position:relative;z-index:1;margin-top:7px;color:#1f2d42;font-size:22px;letter-spacing:-.025em;font-variant-numeric:tabular-nums}
#niche-two-round details{overflow:hidden;margin:13px 0;border:1px solid var(--ntr-line);border-radius:11px;background:#fff}
#niche-two-round details>summary{position:relative;padding:12px 15px;color:#26364c;font-size:14px;font-weight:720;line-height:1.5;list-style:none}
#niche-two-round details>summary::-webkit-details-marker{display:none}
#niche-two-round details>summary::before{display:inline-grid;width:19px;height:19px;margin-right:8px;border-radius:50%;background:#edf4ff;color:var(--ntr-blue);font-size:13px;line-height:19px;text-align:center;content:"+"}
#niche-two-round details[open]>summary{border-bottom:1px solid var(--ntr-line);background:#f8fbff;color:#174a9b}
#niche-two-round details[open]>summary::before{content:"−"}
#niche-two-round .ntr-table-frame{margin:14px 0;border-color:var(--ntr-line);border-radius:10px;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}
#niche-two-round table{color:#425168}
#niche-two-round table caption{padding:10px 13px;background:#fff;color:#65748a;font-size:12px;font-weight:700;text-align:left;caption-side:top}
#niche-two-round th{position:sticky;top:0;z-index:1;padding:11px 12px;border-bottom:1px solid #d7e2ee;background:#f3f7fc;color:#516176;font-size:12px;font-weight:780;letter-spacing:.015em;box-shadow:0 1px 0 #dce5ef}
#niche-two-round td{padding:11px 12px;border-bottom-color:#e8eef5;line-height:1.55}
#niche-two-round tbody tr:last-child td{border-bottom:0}
#niche-two-round tbody tr:hover td{background:#f8fbff}
#niche-two-round .ntr-copy{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:14px 0;padding:10px 12px;border:1px dashed #cbd9eb;border-radius:10px;background:#f8fbff}
#niche-two-round .ntr-copy button{padding:8px 12px;border:1px solid #1c5fbd;border-radius:8px;background:linear-gradient(180deg,#2a6ccc,#1d4ed8);box-shadow:0 2px 4px rgba(29,78,216,.16);font-size:13px;font-weight:700}
#niche-two-round .ntr-copy-status{margin-left:0}
#niche-two-round .ntr-ce{margin-top:28px;color:#1c2838}
#niche-two-round .ntr-ce-lead{position:relative;overflow:hidden;padding:27px 29px;border:1px solid #d3e0ef;border-radius:13px;background:linear-gradient(122deg,#fff 0%,#f7faff 73%,#f3fbf8 100%);box-shadow:0 8px 20px rgba(30,58,95,.045)}
#niche-two-round .ntr-ce-lead::after{position:absolute;top:0;right:0;bottom:0;width:128px;opacity:.42;background:repeating-linear-gradient(90deg,transparent 0 12px,#b9cfed 12px 13px,transparent 13px 25px);mask-image:linear-gradient(90deg,transparent,black);content:"";pointer-events:none}
#niche-two-round .ntr-ce-overline{position:relative;z-index:1;margin:0 0 4px;color:#4f72a9;font-weight:800;font-size:11px;letter-spacing:.12em}
#niche-two-round .ntr-ce-lead h4{position:relative;z-index:1;margin:0;color:#142033;font-size:28px;letter-spacing:-.03em;line-height:1.25}
#niche-two-round .ntr-ce-lead>p{position:relative;z-index:1;max-width:880px;margin:7px 0 20px;color:#65748a;font-size:15px;line-height:1.7}
#niche-two-round .ntr-ce-signals{position:relative;z-index:1;max-width:1060px;border-top:1px solid #dce7f2}
#niche-two-round .ntr-ce-signal{display:grid;grid-template-columns:132px minmax(0,1fr);gap:18px;padding:10px 0;border-bottom:1px solid #dce7f2;line-height:1.5}
#niche-two-round .ntr-ce-signal b{color:#264361;font-size:13px;letter-spacing:.02em}
#niche-two-round .ntr-ce-signal span{color:#506178}
#niche-two-round .ntr-ce-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:14px 0 26px}
#niche-two-round .ntr-ce-summary-card{min-height:0;padding:17px 18px 16px;border:1px solid #d8e3ef;border-top:3px solid #4d83d5;border-radius:12px;background:#fcfdff;box-shadow:0 3px 10px rgba(30,58,95,.025)}
#niche-two-round .ntr-ce-summary-card:nth-child(2){border-top-color:#397fc0}#niche-two-round .ntr-ce-summary-card:nth-child(3){border-top-color:#cc8a33}#niche-two-round .ntr-ce-summary-card:nth-child(4){border-top-color:#259174}
#niche-two-round .ntr-ce-summary-card h5{margin:0 0 12px;color:#203149;font-size:17px;letter-spacing:-.01em}
#niche-two-round .ntr-ce-summary-card>p{margin:14px 0 0;padding-top:12px;border-top:1px solid #e5edf5;color:#718197;font-size:12px;line-height:1.65}
#niche-two-round .ntr-ce-kv{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #e8eef5;color:#728198;font-size:14px;line-height:1.35}
#niche-two-round .ntr-ce-kv:last-of-type{border-bottom:0}
#niche-two-round .ntr-ce-kv strong{max-width:64%;text-align:right;color:#1f2d42;font-size:16px;line-height:1.25;font-variant-numeric:tabular-nums}
#niche-two-round .ntr-ce-table{overflow:auto;border:1px solid #d8e3ef;border-radius:12px;background:#fff;box-shadow:0 4px 12px rgba(30,58,95,.025)}
#niche-two-round .ntr-ce-table h5{margin:0;padding:20px 22px 6px;color:#172436;font-size:20px;letter-spacing:-.015em}
#niche-two-round .ntr-ce-table .ntr-ce-note{margin:0 22px 16px;color:#758398;font-size:13px;line-height:1.6}
#niche-two-round .ntr-ce-table table{width:100%;min-width:900px;margin:0;border-collapse:collapse}
#niche-two-round .ntr-ce-table th{padding:12px 14px;text-align:left;background:#f3f7fc;color:#6a788d;font-size:14px;white-space:nowrap}
#niche-two-round .ntr-ce-table td{padding:13px 14px;border-top:1px solid #dfe6ee;vertical-align:top;line-height:1.5;color:#445368}
#niche-two-round .ntr-ce-table td:first-child{font-weight:750;color:#263549}
#niche-two-round .ntr-ce-value{font-weight:750;color:#2c3b4e}
#niche-two-round .ntr-ce-level{display:inline-flex;align-items:center;min-height:24px;padding:2px 9px;border-radius:99px;font-weight:750;font-size:12px;white-space:nowrap}
#niche-two-round .ntr-ce-level-high{background:#fff0f0;color:#c6372c}#niche-two-round .ntr-ce-level-mid{background:#fff5df;color:#9a5a00}#niche-two-round .ntr-ce-level-low{background:#eaf6f1;color:#117c5d}#niche-two-round .ntr-ce-level-muted{background:#eff2f6;color:#68778c}
#niche-two-round .ntr-ce-pivot{margin-top:24px;padding:21px 22px 22px;border:1px solid #d8e3ef;border-radius:12px;background:#fff;box-shadow:0 4px 12px rgba(30,58,95,.025)}
#niche-two-round .ntr-ce-pivot-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}
#niche-two-round .ntr-ce-pivot h5{margin:0;color:#172436;font-size:20px;letter-spacing:-.015em}
#niche-two-round .ntr-ce-tabs{display:flex;gap:3px;padding:3px;border:1px solid #e1e9f2;border-radius:11px;background:#f2f6fa;overflow:auto}
#niche-two-round .ntr-ce-tab{border:0;border-radius:8px;padding:8px 12px;background:transparent;color:#68778c;font:700 13px/1.2 inherit;white-space:nowrap;cursor:pointer}
#niche-two-round .ntr-ce-tab[aria-selected="true"]{background:#fff;color:#226cd2;box-shadow:0 2px 6px rgba(27,55,88,.13)}
#niche-two-round .ntr-ce-legend{display:flex;gap:18px;margin:0 0 12px;color:#6d7c91;font-size:13px}
#niche-two-round .ntr-ce-dot{display:inline-block;width:9px;height:9px;margin-right:6px;border-radius:50%;background:#3876d1}#niche-two-round .ntr-ce-dot.sales{background:#167f63}
#niche-two-round .ntr-ce-bars{display:grid;gap:9px;padding:3px 0}
#niche-two-round .ntr-ce-bar-row{display:grid;grid-template-columns:148px minmax(200px,1fr) 74px 74px 64px;gap:11px;align-items:center}
#niche-two-round .ntr-ce-band{font-size:13px;font-weight:750;color:#2d3a4b;letter-spacing:-.01em;overflow-wrap:anywhere}
#niche-two-round .ntr-ce-tracks{display:grid;gap:4px}#niche-two-round .ntr-ce-track{height:8px;border-radius:10px;background:#edf2f8;overflow:hidden}#niche-two-round .ntr-ce-fill{display:block;height:100%;min-width:2px;border-radius:inherit;background:linear-gradient(90deg,#5d8cda,#3976cf)}#niche-two-round .ntr-ce-fill.sales{background:linear-gradient(90deg,#63a993,#258064)}
#niche-two-round .ntr-ce-bar-num{text-align:right;color:#536278;font-variant-numeric:tabular-nums}.ntr-ce-ratio{text-align:right;color:var(--ntr-green);font-weight:800;font-variant-numeric:tabular-nums}
#niche-two-round .ntr-ce-pivot-table{width:100%;margin-top:20px;border:1px solid #e0e8f1;border-collapse:collapse;border-radius:8px;overflow:hidden;font-size:14px}
#niche-two-round .ntr-ce-pivot-table th,#niche-two-round .ntr-ce-pivot-table td{padding:10px 8px;border-top:1px solid #e0e7ef;text-align:right;color:#536278}
#niche-two-round .ntr-ce-pivot-table th{background:#f5f8fc;color:#718096;font-weight:750}
#niche-two-round .ntr-ce-pivot-table th:first-child,#niche-two-round .ntr-ce-pivot-table td:first-child{text-align:left;color:#2d3a4b;font-weight:700}
#niche-two-round .ntr-ce-empty{padding:28px 0;color:#718096;text-align:center}
#niche-refinement .ntr-table-frame{overflow:auto;background:#fff;border-color:#cfdae7}
#niche-refinement table{width:100%;min-width:900px;table-layout:fixed;border-collapse:collapse}
#niche-refinement table caption{border:1px solid #d7e2ee;border-bottom:0}
#niche-refinement th,#niche-refinement td{box-sizing:border-box;border:1px solid #d7e2ee}
#niche-refinement th{vertical-align:middle}
#niche-refinement th:first-child,#niche-refinement td:first-child{width:22%;text-align:left}
#niche-refinement th:not(:first-child),#niche-refinement td:not(:first-child){width:13%;text-align:center;white-space:nowrap}
@media(max-width:1180px){#niche-two-round .ntr-ce-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:980px){#niche-two-round>h2{margin-top:32px}#niche-two-round .ntr-ce-summary{grid-template-columns:repeat(2,minmax(0,1fr))}#niche-two-round .ntr-ce-bar-row{grid-template-columns:126px minmax(180px,1fr) 68px 68px 60px}}
@media(max-width:680px){#niche-two-round>h2{font-size:22px}#niche-two-round .ntr-section>h3{font-size:16px}#niche-two-round .ntr-card{padding:17px 15px}#niche-two-round .ntr-card>h4{font-size:18px}#niche-two-round .ntr-ce-lead{padding:21px 18px}#niche-two-round .ntr-ce-lead h4{font-size:24px}#niche-two-round .ntr-ce-signal{grid-template-columns:1fr;gap:3px}#niche-two-round .ntr-ce-summary{grid-template-columns:1fr}#niche-two-round .ntr-ce-pivot{padding:17px 15px}#niche-two-round .ntr-ce-bar-row{grid-template-columns:92px minmax(130px,1fr) 52px 52px 54px;gap:7px}#niche-two-round .ntr-ce-table h5{padding-left:16px}#niche-two-round .ntr-ce-table .ntr-ce-note{margin-left:16px;margin-right:16px}#niche-refinement table{min-width:760px}#niche-refinement th:first-child,#niche-refinement td:first-child{width:26%}#niche-refinement th:not(:first-child),#niche-refinement td:not(:first-child){width:12.333%}}
</style>
<script id="niche-two-round-pivot-script">
(()=>{document.addEventListener('click',event=>{const button=event.target.closest('.ntr-ce-tab');if(!button)return;const section=button.closest('.ntr-ce-pivot');if(!section)return;section.querySelectorAll('.ntr-ce-tab').forEach(tab=>tab.setAttribute('aria-selected',String(tab===button)));section.querySelectorAll('[data-ntr-pivot-panel]').forEach(panel=>{panel.hidden=panel.dataset.ntrPivotPanel!==button.dataset.ntrPivot;});});})();
</script>"""

STYLE += COMPETITION_LAYOUT


def _text(value: Any) -> str:
    if value is None or value == "":
        return "未提供"
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return html.escape(str(value), quote=True)


def _number(value: Any, decimals: int = 0) -> str:
    if value is None or isinstance(value, bool):
        return "未提供"
    if isinstance(value, (int, float)):
        return f"{value:,.{decimals}f}" if math.isfinite(value) else "未提供"
    return _text(value)


def _percent(value: Any, *, ratio: bool = False) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "未提供"
    return f"{value * (100 if ratio else 1):.2f}%"


def _score(candidate: dict[str, Any]) -> str:
    scoring = candidate.get("scoring") or {}
    if scoring.get("score") is not None:
        return _number(scoring["score"], 2)
    lower, upper = scoring.get("lower_bound"), scoring.get("upper_bound")
    if lower is not None and upper is not None:
        return f"待验证（{_number(lower, 2)}–{_number(upper, 2)}）"
    return "待验证"


def _safe_link(value: Any) -> str | None:
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
    except ValueError:
        return None
    return html.escape(value, quote=True)


def _marked(name: str, content: str) -> str:
    return f"<!-- {name}_START -->{content}<!-- {name}_END -->"


def _strip_owned(source: str) -> str:
    """Only remove explicit extension markers; preserve surrounding whitespace."""
    for name in (*MARKERS, "NICHE_TOP3"):
        source = re.sub(rf"<!-- {name}_START -->.*?<!-- {name}_END -->", "", source, flags=re.DOTALL)
    source = re.sub(r'<style\b(?=[^>]*\bid=[\"\']niche-top3-style[\"\'])[^>]*>.*?</style>', "", source, flags=re.DOTALL | re.IGNORECASE)
    source = re.sub(r'<a\b(?=[^>]*\bdata-niche-top3-nav=[\"\']true[\"\'])[^>]*>.*?</a>', "", source, flags=re.DOTALL | re.IGNORECASE)
    return source


def _table(headers: list[str], rows: list[list[str]], caption: str) -> str:
    if not rows:
        return '<p class="ntr-muted">暂无可展示记录。</p>'
    head = "".join(f"<th scope=\"col\">{_text(value)}</th>" for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="ntr-table-frame" tabindex="0" role="region" aria-label="{_text(caption)}"><table><caption>{_text(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _reasons(item: dict[str, Any], selected: bool) -> str:
    values = [item.get("selection_note"), item.get("formal_ineligible_reason")]
    values.extend(item.get("scoring_issues") or [])
    if not selected:
        conflicts = [c for c in item.get("dedupe_conflicts") or [] if isinstance(c, dict)]
        conflicts.sort(key=lambda c: (-(c.get("shared_sales_ratio") or 1.0), str(c.get("candidate_name") or "")))
        for conflict in conflicts[:3]:
            values.append(f"重复机会：与「{conflict.get('candidate_name') or conflict.get('candidate_id')}」属同一需求，{conflict.get('reason') or '互斥'}")
        if len(conflicts) > 3:
            values.append(f"另与 {len(conflicts) - 3} 个候选重叠")
        values.extend(f"重复机会：{c}" for c in item.get("dedupe_conflicts") or [] if not isinstance(c, dict))
    reasons = list(dict.fromkeys(str(value) for value in values if value))
    return _text("；".join(reasons)) if reasons else ("满足本轮条件，入选兼容机会组合" if selected else "综合得分或组合选择未入围")


def _selected(result: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in result.get("candidates", [])}
    ids = result.get("selected_candidate_ids") or []
    if len(set(ids)) != len(ids) or any(key not in by_id for key in ids):
        raise ValueError("推荐 ID 重复或没有对应候选明细")
    return [by_id[key] for key in ids]


def _score_table(result: dict[str, Any]) -> str:
    rank = {key: index for index, key in enumerate(result.get("selected_candidate_ids") or [], 1)}
    rows = []
    for item in result.get("candidates", []):
        components = (item.get("scoring") or {}).get("components") or {}
        status = f"入围 {rank[item['id']]}" if item.get("id") in rank else "未入围／待验证"
        row = [_text(item.get("name")), _score(item)]
        row += [_number(components.get(key), 2) for key in COMPONENTS]
        row += [_text(status), _reasons(item, item.get("id") in rank)]
        rows.append(row)
    headers = ["细分市场", "总分"] + list(COMPONENTS.values()) + ["粗筛状态", "原因／缺失证据"]
    return _table(headers, rows, "Top3 粗筛全部候选评分")


def _expression(candidate: dict[str, Any]) -> str:
    parts = []
    for branch in (candidate.get("tag_expression") or {}).get("any_of") or []:
        parts.append(" + ".join(str(condition.get("dimension", "")) + "：" + "／".join(map(str, condition.get("values") or [])) for condition in branch.get("all_of") or []))
    return _text(" 或 ".join(parts))


def _growth(item: dict[str, Any]) -> str:
    rates = (item.get("search_growth_evidence") or {}).get("growth_rates") or {}
    parts = [f"{days} 天 {_percent(rates.get(f'搜索量增长率-近{days}天 (%)'))}" for days in (90, 180, 360)]
    return '<p class="ntr-muted">商机表原始搜索增长：' + "；".join(parts) + "。只作方向与近期下滑判断，不计趋势分。</p>"


def _top20(item: dict[str, Any]) -> str:
    members = item.get("top20") or []
    copy_text = "\n".join(str(member.get("asin") or "") for member in members if member.get("asin"))
    actual = len(members)
    rows = []
    for index, member in enumerate(members, 1):
        asin = _text(member.get("asin"))
        url = _safe_link(member.get("product_url"))
        if url:
            asin = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{asin}</a>'
        rows.append([str(index), asin, _text(member.get("title")), _text(member.get("brand")), _number(member.get("price"), 2), _number(member.get("monthly_sales")), _text(member.get("month")), _text(member.get("parent_asin"))])
    label = f"一键复制这 {actual} 个 ASIN" if actual else "暂无可复制的 ASIN"
    copy_control = (
        f'<div class="ntr-copy"><button type="button" class="ntr-copy-button" data-count="{actual}"'
        + (" disabled" if not copy_text else "")
        + f'>{_text(label)}</button><span class="ntr-copy-status" role="status" aria-live="polite"></span>'
        + f'<textarea class="ntr-copy-source" hidden readonly aria-label="按行复制的 ASIN">{html.escape(copy_text, quote=False)}</textarea></div>'
    )
    return f'<details><summary>本市场月销量前 20 个 ASIN（实际 {actual} 个）</summary><p class="ntr-muted">来自完整匹配商品集合，按有效月销量降序；同销量按 ASIN 排序。价格使用原表币种。</p>' + copy_control + _table(["排名", "ASIN", "商品名称", "品牌", "价格", "月销量", "数据周期", "父 ASIN"], rows, "细分市场销量前 20 个 ASIN") + "</details>"


def _keyword_rows(item: dict[str, Any], refined: bool) -> str:
    ad = item.get("ad_cost_evidence") or {}
    if refined:
        rows = []
        for detail in ad.get("keyword_details") or []:
            reason = detail.get("reason") or detail.get("reasons") or detail.get("exclusion_reason")
            participated = detail.get("participating", detail.get("included"))
            status = detail.get("status") or ("参与计算" if participated else "未参与计算")
            rows.append([
                _text(detail.get("keyword")), _text(detail.get("period")),
                _number(detail.get("clicks")), _number(detail.get("purchases")),
                _number(detail.get("bid", detail.get("ppc_bid")), 4),
                _percent(detail.get("click_weight", detail.get("purchase_weight")), ratio=True),
                _number(detail.get("weighted_bid", detail.get("weighted_bid_contribution")), 4),
                _text(status), _text(reason), _text(detail.get("bid_source_rows")),
                _text(detail.get("conversion_source_rows")),
            ])
        return '<details><summary>核心关键词逐词计算与排除明细</summary>' + _table(["核心关键词", "转化统计周期", "点击量", "购买量", "卖家精灵竞价", "点击量占比", "加权竞价贡献", "状态", "原因", "卖家精灵竞价来源行", "新商机表转化来源行"], rows, "第二轮统一词集的逐词计算") + "</details>"
    rows = []
    for assignment in item.get("keyword_assignments") or []:
        if assignment.get("type") != "direct":
            continue
        for source in assignment.get("main_source_rows") or [{}]:
            fields = source.get("fields") or {}
            rows.append([_text(assignment.get("keyword")), _number(fields.get("月搜索量")), _text(fields.get("PPC竞价")), _text(assignment.get("reason")), _text(source.get("row_number", source.get("source_row")))])
    return '<details><summary>粗筛核心关键词清单</summary><p class="ntr-muted">只展示明确表达本需求的 direct 核心词，用于需求核验、去重及后续补充关键词转化表；粗筛不计算广告压力。</p>' + _table(["核心关键词", "月搜索量", "归属依据", "卖家精灵来源行"], [[row[0], row[1], row[3], row[4]] for row in rows], "粗筛直接需求词") + "</details>"


def _ad_details(item: dict[str, Any], refined: bool) -> str:
    ad = item.get("ad_cost_evidence") or {}
    primary = (item.get("primary_poe") or {}).get("metrics") or {}
    if refined:
        counts = "；".join([
            f"转化表关键词 {_number(ad.get('core_keyword_count'))} 个",
            f"有转化数据 {_number(ad.get('conversion_keyword_count'))} 个",
            f"实际参与 {_number(ad.get('participating_keyword_count'))} 个",
            f"缺有效竞价 {_number(ad.get('missing_bid_count'))} 个",
            f"转化有效率 {_percent(ad.get('conversion_match_rate'), ratio=True)}",
            f"PPC购买量覆盖 {_percent(ad.get('purchase_coverage'), ratio=True)}",
            f"PPC点击量覆盖 {_percent(ad.get('click_coverage'), ratio=True)}",
        ])
        price = ad.get("mean_price", (item.get("refined_product_evidence") or {}).get("mean_price"))
        cvr = _percent(ad.get("click_conversion_rate"), ratio=True)
        sample = f"参与计算的关键词：点击量 {_number(ad.get('total_clicks'))}，购买量 {_number(ad.get('total_purchases'))}。缺转化数据或缺卖家精灵建议竞价的关键词整行忽略，转化率和加权CPC使用同一批关键词。"
    else:
        counts = "初筛只使用准确主评分行市场名称的同名卖家精灵关键词"
        price = primary.get("average_price_90d")
        cvr = _percent(primary.get("click_conversion_rate_90d"))
        sample = f"主评分行市场名称：{_text(ad.get('primary_poe_market_name'))}；同名关键词：{_text(ad.get('matched_keyword'))}；卖家精灵来源行：{_text(ad.get('bid_source_rows'))}。"
    half = ad.get("half_click_conversion_pressure_estimate", ad.get("half_conversion_pressure_estimate"))
    return (
        f"<p>{counts}。</p>"
        f"<p>加权CPC {_number(ad.get('representative_bid'), 4)}；商品均价 {_number(price, 2)}；90天转化率 {cvr}；广告压力 ACOS {_percent(ad.get('pressure_estimate'))}；转化率减半情景 {_percent(half)}。</p>"
        f'<p class="ntr-muted">{sample} 建议竞价只取自卖家精灵关键词反查表，关键词转化表与商机表中的出价字段不参与计算。加权CPC按“纳入词点击量／纳入词点击量之和 × 词PPC竞价”累加，不代表真实 ACOS 或利润。</p>'
    )


def _supply_demand_details(item: dict[str, Any]) -> str:
    evidence = item.get("supply_demand_evidence") or {}
    if evidence.get("status") != "available":
        return f'<p class="ntr-muted">供需指数：待验证。{_text(evidence.get("reason"))}</p>'
    return (
        '<p>供需指数 '
        f'<strong>{_number(evidence.get("supply_demand_index"), 4)}</strong>（供需分 {_number(evidence.get("supply_demand_score"), 2)}）：'
        f'本市场 Listing 数量占比 {_percent(evidence.get("listing_count_share"), ratio=True)}，销量占比 {_percent(evidence.get("listing_sales_share"), ratio=True)}。'
        f'比较母集为原始品类有效商品全集：{_number(evidence.get("category_valid_asin_count"))} 个 ASIN、月销量 {_number(evidence.get("category_monthly_sales_sum"))}。</p>'
    )


def _return_context(item: dict[str, Any]) -> str:
    context = item.get("return_risk_context") or {}
    if context.get("status") != "available":
        return f'<p class="ntr-muted">退货风险提示：未提供。{_text(context.get("reason"))}</p>'
    return f'<p class="ntr-muted">退货风险提示：商机表近 360 天退货率 {_percent(context.get("return_rate_360d"))}，仅作补充风险信息，不参与本轮评分。</p>'


def _money(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "无法判断"
    return f"${value:,.2f}"


def _rule_views(item: dict[str, Any]) -> list[dict[str, Any]]:
    rules = ((item.get("rule_conclusions") or {}).get("rules") or {})
    views = []
    for key, fallback_label in zip(RULES, RULE_LABELS):
        rule = rules.get(key) or {}
        raw_value = rule.get("value")
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            value = _percent(raw_value)
        elif isinstance(raw_value, list):
            value = "、".join(str(part) for part in raw_value) or "无法判断"
        else:
            value = str(raw_value) if raw_value not in (None, "") else "无法判断"
        status = "已计算" if rule.get("status") == "ready" else "无法判断"
        views.append({
            "key": key,
            "label": str(rule.get("label") or fallback_label),
            "level": str(rule.get("level") or status),
            "value": value,
            "readout": str(rule.get("summary") or "缺少本市场必要证据，无法判断。"),
            "basis": str(rule.get("basis") or "数据不足"),
        })
    return views


def _ce_level_class(level: str) -> str:
    if re.search(r"很高|较高", level):
        return "ntr-ce-level-high"
    if re.search(r"很低|较低|极低", level):
        return "ntr-ce-level-low"
    if re.search(r"中等|已计算|已识别", level):
        return "ntr-ce-level-mid"
    return "ntr-ce-level-muted"


def _price_band_to_money(band: str, mean_price: Any) -> str:
    if not isinstance(mean_price, (int, float)) or isinstance(mean_price, bool) or mean_price <= 0:
        return "无法判断"
    clean = re.sub(r"\s+", "", band)
    match = re.fullmatch(r"<([0-9.]+)x均价", clean)
    if match:
        return "＜" + _money(mean_price * float(match.group(1)))
    match = re.fullmatch(r">=([0-9.]+)x均价", clean)
    if match:
        return "≥" + _money(mean_price * float(match.group(1)))
    match = re.fullmatch(r"([0-9.]+)-([0-9.]+)x均价", clean)
    if match:
        return _money(mean_price * float(match.group(1))) + "–" + _money(mean_price * float(match.group(2)))
    return band or "无法判断"


def _price_bands(value: str, mean_price: Any) -> str:
    if value == "无法判断" or not value:
        return "无法判断"
    return "、".join(_price_band_to_money(part, mean_price) for part in re.split(r"[、,]", value))


def _pivot_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return 0.0


def _ce_pivot_rows(item: dict[str, Any], source_key: str, mean_price: Any) -> list[dict[str, str | float]]:
    data = ((item.get("rule_conclusions") or {}).get("pivots") or {}).get(source_key) or []
    if isinstance(data, dict):
        data = data.get("rows") or data.get("bands") or []
    rows = []
    for row in data:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "未提供")
        if source_key == "price":
            label = _price_band_to_money(label, mean_price)
        listing_value = _pivot_number(row.get("listing_count_share"))
        sales_value = _pivot_number(row.get("sales_share"))
        rows.append({
            "label": label,
            "count": _number(row.get("listing_count")),
            "listing": _percent(row.get("listing_count_share")),
            "sales": _number(row.get("sales")),
            "sales_share": _percent(row.get("sales_share")),
            "average": _number(row.get("avg_sales"), 2),
            "listing_value": listing_value,
            "sales_value": sales_value,
        })
    return rows


def _ce_pivot_panel(key: str, label: str, rows: list[dict[str, str | float]]) -> str:
    if not rows:
        return f'<div data-ntr-pivot-panel="{_text(key)}" hidden><div class="ntr-ce-empty">该细分市场缺少{_text(label)}字段，暂无法生成透视。</div></div>'
    bars, table_rows = [], []
    for row in rows:
        listing_value = float(row["listing_value"])
        sales_value = float(row["sales_value"])
        ratio = sales_value / listing_value if listing_value else 0.0
        bars.append(
            '<div class="ntr-ce-bar-row">'
            f'<div class="ntr-ce-band">{_text(row["label"])}</div>'
            '<div class="ntr-ce-tracks">'
            f'<div class="ntr-ce-track"><i class="ntr-ce-fill" style="width:{min(100.0, max(0.0, listing_value)):.2f}%"></i></div>'
            f'<div class="ntr-ce-track"><i class="ntr-ce-fill sales" style="width:{min(100.0, max(0.0, sales_value)):.2f}%"></i></div>'
            '</div>'
            f'<div class="ntr-ce-bar-num">{_text(row["listing"])}</div><div class="ntr-ce-bar-num">{_text(row["sales_share"])}</div><div class="ntr-ce-ratio">{ratio:.2f}x</div>'
            '</div>'
        )
        table_rows.append(
            "<tr>" + "".join(
                f"<td>{_text(value)}</td>" for value in (
                    row["label"], row["listing"], row["sales_share"], row["count"], row["average"], f"{ratio:.2f}x"
                )
            ) + "</tr>"
        )
    return (
        f'<div data-ntr-pivot-panel="{_text(key)}" hidden>'
        '<div class="ntr-ce-legend"><span><i class="ntr-ce-dot"></i>Listing 数量占比</span><span><i class="ntr-ce-dot sales"></i>月销量占比</span></div>'
        f'<div class="ntr-ce-bars">{"".join(bars)}</div>'
        f'<table class="ntr-ce-pivot-table"><thead><tr><th>{_text(label)}区间</th><th>Listing占比</th><th>销量占比</th><th>Listing数</th><th>平均月销量</th><th>供需比</th></tr></thead><tbody>{"".join(table_rows)}</tbody></table></div>'
    )


def _ce_kv(label: str, value: str) -> str:
    return f'<div class="ntr-ce-kv"><span>{_text(label)}</span><strong>{_text(value)}</strong></div>'


def _ce_summary_card(title: str, rows: list[tuple[str, str]], note: str) -> str:
    return f'<article class="ntr-ce-summary-card"><h5>{_text(title)}</h5>{"".join(_ce_kv(label, value) for label, value in rows)}<p>{_text(note)}</p></article>'


def _competition_environment(item: dict[str, Any]) -> str:
    products = item.get("product_metrics") or {}
    full = item.get("refined_product_evidence") or {}
    supply = item.get("supply_demand_evidence") or {}
    ad = item.get("ad_cost_evidence") or {}
    rules = _rule_views(item)
    by_label = {rule["label"]: rule for rule in rules}

    def rule(label: str) -> dict[str, Any]:
        return by_label.get(label, {"label": label, "level": "无法判断", "value": "无法判断", "readout": "无法判断", "basis": "数据不足"})

    name = str(item.get("name") or "细分市场")
    count = _number(full.get("effective_count", products.get("matched_asin_count")))
    sales = _number(full.get("total_monthly_sales", products.get("monthly_sales_known_sum")))
    direct_count = _number((item.get("keyword_metrics") or {}).get("direct_assignment_count"))
    supply_index = _number(supply.get("supply_demand_index"), 4)
    listing_share = _percent(supply.get("listing_count_share"), ratio=True)
    sales_share = _percent(supply.get("listing_sales_share"), ratio=True)
    confidence = ((item.get("rule_conclusions") or {}).get("confidence"))
    confidence_label = {"low": "低置信度（有效商品少于 50 个）", "standard": "常规样本置信度"}.get(confidence, str(confidence or "样本置信度未提供"))
    mean_price = ad.get("mean_price", full.get("mean_price"))
    product, brand, ad_rule = rule("商品垄断度"), rule("品牌垄断度"), rule("广告压力指数")
    cycle, rating, sensitivity = rule("新品打造周期"), rule("评分值依赖性"), rule("价格敏感度")
    best_price = rule("最值得进入的价格带")
    review = rule("评论依赖性")
    ad_pending = "无法判断" in (ad_rule["level"] + ad_rule["value"])
    concentrated = bool(re.search(r"很高|较高", product["level"] + brand["level"]))
    lead_title = "需求已验证，但广告证据待补全" if ad_pending else ("需求已验证，但头部集中度偏高" if concentrated else "市场结构相对开放，可继续验证进入窗口")
    lead_copy = (
        "销量与供需已形成信号，但转化表、有效 PPC 或商品均价不完整，广告成本暂不下结论。"
        if ad_pending else "头部份额与进入窗口需结合阅读；广告压力仅作为获客难度的参考，不等同真实 ACOS 或利润。"
    )
    coverage = _percent(ad.get("purchase_coverage"), ratio=True)
    cpc = _money(ad.get("representative_bid"))
    conversion = _percent(ad.get("click_conversion_rate"), ratio=True)
    price_bands = _price_bands(best_price["value"], mean_price)
    conclusion_rows = []
    for entry in rules:
        value = price_bands if entry["label"] == "最值得进入的价格带" else entry["value"]
        readout = f"更值得观察的价格带：{value}" if entry["label"] == "最值得进入的价格带" and value != "无法判断" else entry["readout"]
        conclusion_rows.append(
            f'<tr><td>{_text(entry["label"])}</td><td class="ntr-ce-value">{_text(value)}</td><td><span class="ntr-ce-level {_ce_level_class(entry["level"])}">{_text(entry["level"])}</span></td><td>{_text(readout)}</td><td>{_text(entry["basis"])}</td></tr>'
        )
    pivot_specs = (("review", "review_count", "评论数"), ("launch", "launch_days", "上架天数"), ("rating", "rating", "评分"), ("price", "price", "售价"))
    tabs = "".join(
        f'<button type="button" class="ntr-ce-tab" role="tab" aria-selected="{str(key == "review").lower()}" data-ntr-pivot="{key}">{label}</button>'
        for key, _source, label in pivot_specs
    )
    panels = "".join(_ce_pivot_panel(key, label, _ce_pivot_rows(item, source, mean_price)) for key, source, label in pivot_specs)
    panels = panels.replace('data-ntr-pivot-panel="review" hidden', 'data-ntr-pivot-panel="review"', 1)
    return (
        '<section class="ntr-ce">'
        '<div class="ntr-ce-lead">'
        f'<p class="ntr-ce-overline">MARKET READOUT · {_text(name)}</p><h4>细分市场竞争环境分析</h4>'
        f'<p>{_text(lead_title)}。{_text(lead_copy)}</p>'
        '<div class="ntr-ce-signals">'
        f'<div class="ntr-ce-signal"><b>竞争结构</b><span>商品前10%拿走 {_text(product["value"])}；品牌前10%拿走 {_text(brand["value"])}。</span></div>'
        f'<div class="ntr-ce-signal"><b>获客成本</b><span>{_text("广告压力无法判断；有效购买量覆盖 " + coverage + "。" if ad_pending else "广告压力 " + ad_rule["value"] + "，等级为 " + ad_rule["level"] + "。")}</span></div>'
        f'<div class="ntr-ce-signal"><b>新品信号</b><span>新品打造周期 {_text(cycle["value"])}；评分门槛 {_text(rating["value"])}。</span></div>'
        f'<div class="ntr-ce-signal"><b>数据覆盖</b><span>完整有效商品 {_text(count)} 个；核心需求词 {_text(direct_count)} 个；供需指数 {_text(supply_index)}；{_text(confidence_label)}。</span></div>'
        '</div></div>'
        '<div class="ntr-ce-summary">'
        + _ce_summary_card("市场规模", [("完整有效商品", count + " 个"), ("近30天月销量", sales), ("Listing 占比", listing_share), ("销量占比", sales_share)], "使用本细分市场完整有效商品集合，不外推全年市场规模。")
        + _ce_summary_card("价格与获客", [("商品均价", _money(mean_price)), ("加权CPC", cpc), ("90天转化率", conversion), ("广告压力 ACOS", "无法判断" if ad_pending else ad_rule["value"])], "加权CPC为有效PPC关键词点击量加权的建议竞价；广告压力 ACOS 仅在转化、竞价和均价可用时判定。")
        + _ce_summary_card("竞争集中", [("商品垄断", product["value"] + " · " + product["level"]), ("品牌垄断", brand["value"] + " · " + brand["level"]), ("评论依赖", review["value"] + " · " + review["level"]), ("价格敏感度", sensitivity["value"] + " · " + sensitivity["level"])], "前10%商品和品牌的销量份额越高，头部控制力越强。")
        + _ce_summary_card("进入窗口", [("新品周期", cycle["value"]), ("评分门槛", rating["value"]), ("价格敏感度", sensitivity["level"]), ("推荐价格带", price_bands)], "结合新品周期、价格带和评分门槛判断，不代表单品盈利预测。")
        + '</div>'
        '<div class="ntr-ce-table"><h5>8 项规则结论</h5><p class="ntr-ce-note">规则值来自本细分市场完整商品样本；文字只解释固定规则结果，不改变 Top3 排名。</p><table><thead><tr><th>指标</th><th>规则值</th><th>等级</th><th>读数</th><th>口径</th></tr></thead><tbody>'
        + "".join(conclusion_rows)
        + '</tbody></table></div>'
        '<section class="ntr-ce-pivot"><div class="ntr-ce-pivot-head"><h5>基础维度透视</h5><div class="ntr-ce-tabs" role="tablist" aria-label="基础维度切换">'
        + tabs + '</div></div>' + panels + '</section></section>'
    )


def _candidate_card(item: dict[str, Any], rank: int, refined: bool) -> str:
    products = item.get("product_metrics") or {}
    full = item.get("refined_product_evidence") or {}
    primary = item.get("primary_poe") or {}
    count = full.get("effective_count", products.get("matched_asin_count"))
    sales = full.get("total_monthly_sales", products.get("monthly_sales_known_sum"))
    keyword_count = (item.get("keyword_metrics") or {}).get("direct_assignment_count")
    supply = item.get("supply_demand_evidence") or {}
    stats = [("完整有效商品", _number(count)), ("月销量总和", _number(sales)), ("供需指数", _number(supply.get("supply_demand_index"), 4)), ("核心需求词", _number(keyword_count)), ("本轮得分", _score(item))]
    metrics = '<div class="ntr-grid">' + "".join(f'<div class="ntr-stat">{name}<b>{value}</b></div>' for name, value in stats) + "</div>"
    refined_metrics = ""
    if refined:
        refined_metrics = f"<p>销量前 10% 商品占比 {_percent(full.get('product_head_share_pct'))}；销量前 10% 品牌占比 {_percent(full.get('brand_head_share_pct'))}；360 天内新品 {_number(full.get('new_product_count'))} 个，成功新品 {_number(full.get('successful_new_product_count'))} 个。</p>"
    return (
        '<article class="ntr-card">'
        f'<span class="ntr-badge">{"进一步分析" if refined else "粗筛 Top3"} {rank}</span><h4>{_text(item.get("name"))}</h4>'
        f"<p>{_text(item.get('definition'))}</p><p>共同任务：{_text(item.get('task'))}</p>"
        f"<p>必要条件：{_expression(item)}；购买选择限制：{_text(item.get('selection_constraint_reason'))}</p>"
        f"<p>包含范围：{_text(item.get('include_scope') or item.get('inclusion_scope') or item.get('definition'))}；排除范围：{_text(item.get('exclude_scope') or item.get('exclusion_scope') or '不满足上述必要条件及明确非候选属性的商品')}</p>"
        + metrics + refined_metrics
        + f"<p>推荐与风险依据：{_reasons(item, True)}</p>"
        + '<p class="ntr-muted">' + (f'商机表对应：第 {_text(primary.get("primary_row_number"))} 行，仅作需求证据与风险参考。' if primary.get("primary_row_number") is not None else "多维组合候选，没有商机表行。")
        + ("进一步分析不重新评分或更改 Top3。" if refined else "粗筛四项分数按本市场商品样本计算。") + "</p>"
        + _supply_demand_details(item) + _return_context(item) + _growth(item) + (_ad_details(item, True) if refined else "") + _keyword_rows(item, refined) + _top20(item)
        + (_competition_environment(item) if refined else "")
        + "</article>"
    )


def render_report(base_html: str, shortlist: dict, refinement: dict | None = None) -> str:
    """Return a new HTML string; never read or write project or source files.

    Results use public candidates with ``top20`` and ``keyword_assignments``.
    Percentages named ``*_coverage`` and the refined CVR are ratios; pressure,
    concentration, growth and pivot shares are percentage points.
    """
    selected_shortlist = _selected(shortlist)
    if len(selected_shortlist) > 3:
        raise ValueError("粗筛入围市场不得超过 Top3")
    selected_refined = _selected(refinement) if refinement is not None else []
    if refinement is not None:
        frozen_ids = [item["id"] for item in selected_shortlist]
        if refinement.get("selected_candidate_ids") != frozen_ids or {item.get("id") for item in refinement.get("candidates", [])} != set(frozen_ids):
            raise ValueError("进一步分析必须继承冻结的 Top3 身份与排名")
    source = _strip_owned(base_html)
    small = re.search(r'<h2\b[^>]*\bid=[\"\']small[\"\'][^>]*>', source, re.IGNORECASE)
    formal = re.search(r'<h2\b[^>]*\bid=[\"\']formal[\"\'][^>]*>', source, re.IGNORECASE)
    if not formal or not small or formal.start() >= small.start():
        raise ValueError("未找到顺序正确的 h2#formal、h2#small；拒绝改动原报告结构")
    head = re.search(r'</head\s*>', source, re.IGNORECASE)
    small_nav = re.search(r'<a\b[^>]*\bhref=[\"\']#small[\"\'][^>]*>', source, re.IGNORECASE)
    if not head or not small_nav:
        raise ValueError("原报告缺少 head 或 #small 导航，无法插入独立样式和导航")

    body = (
        '<section id="niche-two-round" aria-labelledby="niche-two-round-title"'
        f' data-layout-version="{REPORT_LAYOUT_VERSION}" data-shortlist-run-id="{_text(shortlist.get("run_id"))}" data-refinement-run-id="{_text((refinement or {}).get("run_id", ""))}">'
        '<h2 id="niche-two-round-title">细分市场 Top3 与进一步分析</h2>'
        '<p class="ntr-muted">粗筛仅按供需指数 80%、竞争开放度 10%、新品进入证据 5%、需求承接规模 5% 选择 Top3。搜索增长和退货率仅作风险提示。全量指用户提供的数据全集，不代表整个亚马逊市场。</p>'
        '<section class="ntr-section" id="niche-shortlist"><h3>粗筛：直接确定 Top3</h3>'
        f'<p>实际选出 {len(selected_shortlist)} 个市场；名单、排名和需求边界已冻结。后续关键词转化表只用于补充各市场的八项结论，不重新排序或淘汰。</p>'
        + _score_table(shortlist)
        + "".join('<details><summary>' + f"初筛 {index} · {_text(item.get('name'))} · {_score(item)} 分" + "</summary>" + _candidate_card(item, index, False) + "</details>" for index, item in enumerate(selected_shortlist, 1))
        + "</section>"
    )
    if refinement is None:
        body += '<section class="ntr-section" id="niche-awaiting-conversion"><h3>进一步分析：等待关键词级转化表</h3><p class="ntr-notice">请为上述 ' + str(len(selected_shortlist)) + ' 个市场各提供 1 份细分市场关键词转化表（关键词、点击量、购买量，同一近90天周期）和 1 份卖家精灵关键词反查表（含 Asin 工作表，ASIN 与该市场冻结 Top20 完全一致），共 ' + str(2 * len(selected_shortlist)) + ' 个 Excel。补表后将分别计算各市场的广告压力和八项结论；项目原有关键词表不会自动替代新表。</p></section>'
    else:
        body += '<section class="ntr-section" id="niche-refinement"><h3>进一步分析：关键词覆盖与广告压力</h3><p class="ntr-muted">以下计算分别使用各市场完整商品成员、该市场转化表全量关键词及其配对卖家精灵 PPC 数据。广告数据缺口只影响对应结论，不改变粗筛 Top3 名单或排名。</p>'
        coverage_rows = []
        for item in refinement.get("candidates", []):
            ad = item.get("ad_cost_evidence") or {}
            mean_price = ad.get("mean_price", (item.get("refined_product_evidence") or {}).get("mean_price"))
            coverage_rows.append([
                _text(item.get("name")),
                _number(ad.get("core_keyword_count")),
                _number(ad.get("participating_keyword_count")),
                _money(mean_price),
                _money(ad.get("representative_bid")),
                _percent(ad.get("click_conversion_rate"), ratio=True),
                _percent(ad.get("pressure_estimate")),
            ])
        body += _table(["细分市场", "核心词数", "参与词数", "商品均价", "加权CPC", "90天转化率", "广告压力"], coverage_rows, "第二轮关键词覆盖与广告指标")
        body += "</section>"
        body += '<section class="ntr-section" id="niche-final-top3"><h3>Top3 细分市场竞争环境分析</h3>' + f"<p>已分析 {len(selected_refined)} 个粗筛市场；缺失字段会在对应结论中显示为无法判断。</p>" + "".join(_candidate_card(item, index, True) for index, item in enumerate(selected_refined, 1)) + "</section>"
    body += f'<p class="ntr-muted">粗筛运行 ID：{_text(shortlist.get("run_id"))}；进一步分析运行 ID：{_text((refinement or {}).get("run_id"))}。规则版本：{_text((refinement or shortlist).get("rule_version"))}。</p></section>'
    insertions = [
        (head.start(), _marked("NICHE_TWO_ROUND_STYLE", STYLE)),
        (small_nav.start(), _marked("NICHE_TWO_ROUND_NAV", '<a href="#niche-two-round">两轮细分推荐</a>')),
        (small.start(), _marked("NICHE_TWO_ROUND", body)),
    ]
    for offset, fragment in sorted(insertions, reverse=True):
        source = source[:offset] + fragment + source[offset:]
    return source
