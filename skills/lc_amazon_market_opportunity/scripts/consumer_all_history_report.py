#!/usr/bin/env python3
"""Render an all-history, local-only consumer voice report.

The renderer intentionally has no collection code and no network dependency.  It
accepts the compact ``3.0.0-all-history`` analysis contract, tolerates missing
optional sections, embeds local concept images, and produces one offline HTML
file.  All user-facing values are selected from an explicit allow-list so
internal audit fields never leak into the report.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html as html_lib
import json
import mimetypes
import os
import re
import sys
import tempfile
import unicodedata
from collections import OrderedDict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "3.0.0-all-history"
TEMPLATE_VERSION = "1.0.0"
IMAGE_DISCLAIMER = "AI概念表达，非工程图或认证结果"
ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
REQUIRED_CSP = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
    "script-src 'none'; connect-src 'none'; font-src 'none'; media-src 'none'; "
    "object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)

SEMANTIC_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("purchase_selection_recommendation", "购买、选型和推荐"),
    ("failure_complaint_return_alternative", "故障、抱怨、退货和替代"),
    ("satisfaction_recommendation_repurchase", "满意、推荐和复购"),
    ("installation_compatibility_scenario", "安装、兼容性和使用场景"),
    ("diy_modification_workaround", "DIY、改装和绕行方案"),
    ("feature_reverse_innovation", "新功能、反向需求和创意"),
)

SEMANTIC_ALIASES: dict[str, str] = {
    "purchase_selection_recommendation": "purchase_selection_recommendation",
    "purchase_selection": "purchase_selection_recommendation",
    "purchase": "purchase_selection_recommendation",
    "购买选型推荐": "purchase_selection_recommendation",
    "failure_complaint_return_alternative": "failure_complaint_return_alternative",
    "failure_complaint": "failure_complaint_return_alternative",
    "complaint": "failure_complaint_return_alternative",
    "故障抱怨退货替代": "failure_complaint_return_alternative",
    "satisfaction_recommendation_repurchase": "satisfaction_recommendation_repurchase",
    "satisfaction": "satisfaction_recommendation_repurchase",
    "满意推荐复购": "satisfaction_recommendation_repurchase",
    "installation_compatibility_scenario": "installation_compatibility_scenario",
    "installation_compatibility": "installation_compatibility_scenario",
    "scenario": "installation_compatibility_scenario",
    "安装兼容性使用场景": "installation_compatibility_scenario",
    "diy_modification_workaround": "diy_modification_workaround",
    "diy_workaround": "diy_modification_workaround",
    "diy改装绕行方案": "diy_modification_workaround",
    "feature_reverse_innovation": "feature_reverse_innovation",
    "innovation": "feature_reverse_innovation",
    "新功能反向需求创意": "feature_reverse_innovation",
}

KANO_PRESENTATION: dict[str, tuple[str, str]] = {
    "m": ("必备型", "must"),
    "must": ("必备型", "must"),
    "mustbe": ("必备型", "must"),
    "必备": ("必备型", "must"),
    "必备型": ("必备型", "must"),
    "o": ("期望型", "performance"),
    "onedimensional": ("期望型", "performance"),
    "performance": ("期望型", "performance"),
    "期望": ("期望型", "performance"),
    "期望型": ("期望型", "performance"),
    "a": ("魅力型", "attractive"),
    "attractive": ("魅力型", "attractive"),
    "魅力": ("魅力型", "attractive"),
    "魅力型": ("魅力型", "attractive"),
    "i": ("无差异型", "indifferent"),
    "indifferent": ("无差异型", "indifferent"),
    "无差异": ("无差异型", "indifferent"),
    "无差异型": ("无差异型", "indifferent"),
    "r": ("反向型", "reverse"),
    "reverse": ("反向型", "reverse"),
    "反向": ("反向型", "reverse"),
    "反向型": ("反向型", "reverse"),
    "evidenceinsufficient": ("待验证", "pending"),
    "insufficient": ("待验证", "pending"),
    "pending": ("待验证", "pending"),
    "待验证": ("待验证", "pending"),
    "证据不足": ("待验证", "pending"),
}
ALLOWED_KANO_TYPES = frozenset({"必备型", "期望型", "魅力型", "无差异型", "反向型"})

FORBIDDEN_VISIBLE_TERMS = (
    "source_status",
    "source statuses",
    "来源状态",
    "evidence_id",
    "证据id",
    "证据 id",
    "证据类型计数",
    "confidence",
    "置信度",
    "category_30d",
    "segment_1_90d",
    "segment_2_90d",
    "segment_3_90d",
    "union_mixed_window",
    "evidence_insufficient",
)


class ReportError(Exception):
    """Expected input or rendering error."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise ReportError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(
            f"JSON无法解析：{path}（第{exc.lineno}行，第{exc.colno}列）"
        ) from exc
    except OSError as exc:
        raise ReportError(f"无法读取文件：{path}（{exc}）") from exc
    if not isinstance(value, dict):
        raise ReportError("分析JSON顶层必须是对象")
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = path.stat().st_mode & 0o777 if path.exists() else None
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, previous_mode if previous_mode is not None else 0o600)
        os.replace(temporary_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
    )


def _file_sha256(path: Path, label: str) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError as exc:
        raise ReportError(f"{label}不存在：{path}") from exc
    except OSError as exc:
        raise ReportError(f"无法读取{label}：{path}（{exc}）") from exc


def _escape(value: Any) -> str:
    return html_lib.escape(_public_text(value), quote=True)


def _normalized_token(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", text)


def _public_text(value: Any) -> str:
    """Return display text while removing old scope/internal vocabulary."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    text = unicodedata.normalize("NFKC", str(value)).strip()
    replacements = (
        (r"(?i)segment_1_90d", "Top1细分"),
        (r"(?i)segment_2_90d", "Top2细分"),
        (r"(?i)segment_3_90d", "Top3细分"),
        (r"(?i)category_30d", "全品类"),
        (r"(?i)union_mixed_window", "全部合并语料"),
        (r"(?i)evidence_insufficient", "待验证"),
        (r"(?i)evidence[\s_-]*ids?", "原声引用"),
        (r"(?i)source[\s_-]*status(?:es)?", "渠道情况"),
        (r"(?i)confidence", "研究限制"),
        (r"证据\s*ID", "原声引用"),
        (r"证据类型计数", "原声构成"),
        (r"来源状态", "渠道情况"),
        (r"置信度", "研究限制"),
        (r"(?i)formal_kano_survey", "正式KANO问卷"),
        (r"(?i)engineering_reliability", "工程可靠性验证"),
        (r"(?i)patent_freedom_to_operate", "专利自由实施检索"),
        (r"(?i)regulatory_and_certification", "法规与认证核查"),
        (r"(?i)(?<![A-Za-z])Must(?![A-Za-z])", "必备型"),
        (r"(?i)(?<![A-Za-z])One[- ]dimensional(?![A-Za-z])", "期望型"),
        (r"(?i)(?<![A-Za-z])Attractive(?![A-Za-z])", "魅力型"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _first(mapping: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _integer(value: Any) -> int:
    number = _number(value)
    if number is None:
        return 0
    return max(0, int(round(number)))


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_share(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.1f}%"


def _share_fraction(value: Any) -> float:
    number = _number(value)
    if number is None:
        return 0.0
    if number > 1:
        number /= 100
    return max(0.0, min(1.0, number))


def _item_label(item: Any) -> str:
    if isinstance(item, Mapping):
        return _public_text(
            _first(
                item,
                "label",
                "name",
                "name_zh",
                "need_label",
                "topic",
                "feature",
                "title",
                "need",
                "need_code",
                "key",
                default="未命名观点",
            )
        )
    return _public_text(item) or "未命名观点"


def _item_count(item: Any) -> int:
    if not isinstance(item, Mapping):
        return 0
    return _integer(_first(item, "count", "voice_count", "messages", "mentions", default=0))


def _item_share(item: Any) -> float | None:
    if not isinstance(item, Mapping):
        return None
    return _number(_first(item, "share", "voice_share", "message_share", default=None))


def _list_html(values: Any, *, limit: int = 8, empty: str = "暂无有效数据") -> str:
    items = _list(values)[:limit]
    if not items:
        return f'<p class="empty-state">{_escape(empty)}</p>'
    rows = []
    for item in items:
        if isinstance(item, Mapping):
            label = _item_label(item)
            reason = _first(item, "reason", "description", "rationale", default="")
            acceptance = _first(item, "acceptance_criteria", "target", default="")
            detail = ""
            if reason:
                detail += f'<small>{_escape(reason)}</small>'
            if acceptance:
                detail += f'<small>验收：{_escape(acceptance)}</small>'
            rows.append(f"<li><strong>{_escape(label)}</strong>{detail}</li>")
        else:
            rows.append(f"<li>{_escape(item)}</li>")
    return '<ul class="structured-list">' + "".join(rows) + "</ul>"


def _section_head(section_id: str, kicker: str, title: str, description: str) -> str:
    return (
        f'<div class="section-head" id="{_escape(section_id)}">'
        f'<div><p class="section-kicker">{_escape(kicker)}</p><h2>{_escape(title)}</h2></div>'
        f'<p>{_escape(description)}</p></div>'
    )


def _semantic_code(item: Mapping[str, Any]) -> str:
    raw = _first(item, "code", "semantic_code", "key", "label", default="")
    token = _normalized_token(raw)
    if token in SEMANTIC_ALIASES:
        return SEMANTIC_ALIASES[token]
    for code, label in SEMANTIC_DEFINITIONS:
        if token in {_normalized_token(code), _normalized_token(label)}:
            return code
    return ""


def _semantic_map(analysis: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in _list(analysis.get("semantic_categories")):
        if not isinstance(item, Mapping):
            continue
        code = _semantic_code(item)
        if code and code not in result:
            result[code] = item
    return result


def _funnel(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(analysis.get("funnel"))


def _platform_summary(value: Any) -> tuple[int, list[str]]:
    if isinstance(value, Mapping):
        names = [_public_text(key).title() for key, count in value.items() if _integer(count) > 0]
        return len(names), names
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                name = _first(item, "platform", "name", "label", default="")
                qualified = _first(
                    item,
                    "qualified_consumer_voices",
                    "count",
                    "records",
                    "voices",
                    default=0,
                )
                if name and _integer(qualified) > 0:
                    names.append(_public_text(name).title())
            elif item:
                names.append(_public_text(item).title())
        names = list(OrderedDict.fromkeys(names))
        return len(names), names
    return _integer(value), []


def _category_summary(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(analysis.get("category_summary"))


def _top_items(summary: Mapping[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, list):
            return value
    return []


def _render_ranked(title: str, items: Any, *, limit: int = 10) -> str:
    source = _list(items)[:limit]
    blocks: list[str] = []
    for rank, raw in enumerate(source, start=1):
        item = raw if isinstance(raw, Mapping) else {"label": raw}
        label = _item_label(item)
        count = _item_count(item)
        share = _item_share(item)
        width = _share_fraction(share) * 100
        meta = [f"{_format_number(count)} 条"] if count else []
        if share is not None:
            meta.append(_format_share(share))
        author_count = _integer(_first(item, "authors", "author_count", default=0))
        thread_count = _integer(_first(item, "threads", "thread_count", default=0))
        platform_count, _ = _platform_summary(
            _first(item, "platforms", "platform_count", default=0)
        )
        if author_count:
            meta.append(f"{_format_number(author_count)} 位消费者")
        if thread_count:
            meta.append(f"{_format_number(thread_count)} 个讨论")
        if platform_count:
            meta.append(f"{_format_number(platform_count)} 个平台")
        blocks.append(
            '<article class="insight-row">'
            f'<div class="insight-rank">{rank:02d}</div>'
            '<div class="insight-content">'
            f'<h4>{_escape(label)}</h4>'
            f'<div class="insight-bar" aria-hidden="true"><span style="--value:{width:.1f}%"></span></div>'
            f'<div class="insight-meta"><strong>{_escape(" · ".join(meta) or "已识别")}</strong></div>'
            '</div>'
            f'<div class="insight-side">{_escape(_first(item, "type_label", "category_label", default=""))}</div>'
            '</article>'
        )
    return (
        f'<section class="subsection"><h3>{_escape(title)}</h3>'
        + ('<div class="insight-list">' + "".join(blocks) + "</div>" if blocks else '<p class="empty-state">暂无有效数据</p>')
        + "</section>"
    )


def _first_ranked(summary: Mapping[str, Any], keys: Sequence[str]) -> Mapping[str, Any]:
    source = _top_items(summary, *keys)
    for item in source:
        if isinstance(item, Mapping):
            return item
        if item:
            return {"label": item}
    return {}


def _segments(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result = [item for item in _list(analysis.get("top_segments")) if isinstance(item, Mapping)]
    return result[:3]


def _segment_voice_count(segment: Mapping[str, Any]) -> int:
    nested = _mapping(segment.get("analysis"))
    return _integer(
        _first(
            segment,
            "count",
            "consumer_voice_count",
            "voice_count",
            "denominator",
            "qualified_consumer_voices",
            default=_first(nested, "denominator", "voice_count", default=0),
        )
    )


def _render_decision(analysis: Mapping[str, Any]) -> str:
    funnel = _funnel(analysis)
    summary = _category_summary(analysis)
    top_need = _first_ranked(summary, ("needs", "need_stats"))
    top_pain = _first_ranked(summary, ("dissatisfactions", "dissatisfaction_top10"))
    top_delight = _first_ranked(summary, ("satisfactions", "satisfaction_top10"))
    segments = _segments(analysis)
    lead_segment = segments[0] if segments else {}
    qualified = _integer(funnel.get("qualified_consumer_voices"))
    hard_unique = _integer(funnel.get("hard_unique_records"))
    excluded = _integer(funnel.get("excluded_records"))
    platform_count, _ = _platform_summary(funnel.get("platforms"))
    need_label = _item_label(top_need) if top_need else "稳定固定与安全使用"
    pain_label = _item_label(top_pain) if top_pain else "尚未形成可排序痛点"
    delight_label = _item_label(top_delight) if top_delight else "尚未形成可排序满意点"
    segment_label = _public_text(_first(lead_segment, "feature", "name", "label", default="Top3细分待确认"))
    return (
        '<section class="decision-summary" id="decision">'
        '<div class="decision-copy"><p class="section-kicker">本轮核心结论</p>'
        f'<h2>优先围绕“{_escape(need_label)}”开发，把“{_escape(pain_label)}”转成可量化验收指标</h2>'
        f'<p>全量本地清洗后纳入 {_format_number(qualified)} 条可识别消费者表达。首要细分为“{_escape(segment_label)}”；主要满意来源为“{_escape(delight_label)}”。</p>'
        '<div class="callout"><strong>计数口径：</strong>同语义的不同留言不合并；500条独立留言都提出同一需求，就计为500条。只有同一底层留言被重复发现时才合并。</div>'
        '</div>'
        '<aside class="decision-facts"><span>可识别消费者表达</span>'
        f'<strong>{_format_number(qualified)}</strong><ul>'
        f'<li><span>硬身份唯一记录</span><b>{_format_number(hard_unique)}</b></li>'
        f'<li><span>未纳入量化</span><b>{_format_number(excluded)}</b></li>'
        f'<li><span>有效平台</span><b>{_format_number(platform_count)}</b></li>'
        f'<li><span>Top3优先项</span><b>{_escape(segment_label)}</b></li>'
        '</ul></aside></section>'
    )


def _render_funnel(analysis: Mapping[str, Any]) -> str:
    funnel = _funnel(analysis)
    discovered = _integer(funnel.get("discovered_records"))
    unique = _integer(funnel.get("hard_unique_records"))
    examined = _integer(funnel.get("examined_records"))
    excluded = _integer(funnel.get("excluded_records"))
    qualified = _integer(funnel.get("qualified_consumer_voices"))
    platform_count, platform_names = _platform_summary(funnel.get("platforms"))
    steps = (
        ("发现关系", discovered, "同一留言可被多路发现"),
        ("硬身份唯一", unique, "仅合并同一底层留言"),
        ("完成本地检查", examined, "逐条进入清洗规则"),
        ("未纳入量化", excluded, "无关、营销、机器人或空内容"),
        ("六语义有效表达", qualified, "进入需求与产品分析"),
    )
    cards = "".join(
        '<article class="funnel-step">'
        f'<span>{_escape(label)}</span><strong>{_format_number(value)}</strong><small>{_escape(note)}</small>'
        '</article>'
        for label, value, note in steps
    )
    platform_text = "、".join(platform_names) if platform_names else f"{platform_count}个平台"
    return (
        '<section class="report-section panel" id="funnel">'
        + _section_head(
            "funnel-heading",
            "本地全量清洗",
            "从已抓取记录到消费者表达",
            "不再按发布时间筛选；每条记录只要与产品相关并命中六类语义中的任意一类，即可进入量化。",
        )
        + f'<div class="funnel">{cards}</div>'
        + '<div class="method-note"><strong>漏斗说明：</strong>“未纳入量化”和“六语义有效表达”是完成检查后的两类结果，并非先后执行的两个过滤步骤。'
        + f'本轮有效数据覆盖 {_escape(platform_text)}。</div></section>'
    )


def _render_semantics(analysis: Mapping[str, Any]) -> str:
    semantic_map = _semantic_map(analysis)
    cards: list[str] = []
    for index, (code, label) in enumerate(SEMANTIC_DEFINITIONS, start=1):
        item = semantic_map.get(code, {})
        count = _integer(_first(item, "count", "voice_count", default=0))
        share = _first(item, "share", "voice_share", default=None)
        authors = _integer(_first(item, "authors", "author_count", default=0))
        threads = _integer(_first(item, "threads", "thread_count", default=0))
        platforms, _ = _platform_summary(
            _first(item, "platforms", "platform_count", default=0)
        )
        topics = _list(_first(item, "top_topics", "topics", default=[]))[:5]
        chips = "".join(f'<span class="chip">{_escape(_item_label(topic))}</span>' for topic in topics)
        cards.append(
            '<article class="semantic-card">'
            f'<span>语义 {index:02d}</span><h3>{_escape(label)}</h3>'
            f'<div class="semantic-number">{_format_number(count)}<small>{_format_share(share)}留言占比</small></div>'
            f'<p class="muted">{_format_number(authors)} 位消费者 · {_format_number(threads)} 个讨论 · {_format_number(platforms)} 个平台</p>'
            + (f'<div class="topic-chips">{chips}</div>' if chips else "")
            + '</article>'
        )
    return (
        '<section class="report-section panel" id="semantics">'
        + _section_head(
            "semantics-heading",
            "消费者表达分类",
            "六类语义覆盖",
            "一条留言可以同时命中多类语义，因此六类次数和占比不能直接相加。",
        )
        + '<div class="semantic-grid">' + "".join(cards) + '</div></section>'
    )


def _render_category(analysis: Mapping[str, Any]) -> str:
    summary = _category_summary(analysis)
    needs = _top_items(summary, "needs", "need_stats")
    satisfactions = _top_items(summary, "satisfactions", "satisfaction_top10")
    dissatisfactions = _top_items(summary, "dissatisfactions", "dissatisfaction_top10")
    scenarios = _top_items(summary, "scenarios", "use_scenes")
    diy = _top_items(summary, "diy_workarounds", "workarounds")
    innovations = _top_items(summary, "innovations", "ideas", "current_new_needs")
    return (
        '<section class="report-section panel" id="category">'
        + _section_head(
            "category-heading",
            "全品类消费者声音",
            "需求、满意与不满意",
            "所有占比都以本轮全量清洗后的可识别消费者表达为分母；同一留言可贡献多个需求点。",
        )
        + '<div class="two-col">'
        + '<article class="card">' + _render_ranked("需求 Top10", needs) + '</article>'
        + '<article class="card">' + _render_ranked("不满意 Top10", dissatisfactions) + '</article>'
        + '<article class="card">' + _render_ranked("满意 Top10", satisfactions) + '</article>'
        + '<article class="card"><h3>场景、绕行与创意</h3>'
        + '<h4>典型使用场景</h4>' + _list_html(scenarios, limit=8)
        + '<h4>DIY、改装和绕行方案</h4>' + _list_html(diy, limit=8)
        + '<h4>新功能与反向需求</h4>' + _list_html(innovations, limit=8)
        + '</article></div></section>'
    )


def _segment_collection(segment: Mapping[str, Any], *keys: str) -> list[Any]:
    nested = _mapping(segment.get("analysis"))
    for source in (segment, nested):
        for key in keys:
            value = source.get(key)
            if isinstance(value, list):
                return value
    return []


def _compact_signals(title: str, values: Any, *, limit: int = 5) -> str:
    items = _list(values)[:limit]
    if not items:
        return f'<div><h4>{_escape(title)}</h4><p class="muted">暂无可展示信号</p></div>'
    lines: list[str] = []
    for item in items:
        label = _item_label(item)
        count = _item_count(item)
        suffix = f" · {_format_number(count)}条" if count else ""
        lines.append(f'<li>{_escape(label + suffix)}</li>')
    return f'<div><h4>{_escape(title)}</h4><ul>{"".join(lines)}</ul></div>'


def _render_segments(analysis: Mapping[str, Any]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(_segments(analysis), start=1):
        rank = _integer(_first(segment, "rank", default=index)) or index
        name = _public_text(_first(segment, "feature", "name", "label", default=f"Top{rank}细分"))
        dimension = _public_text(_first(segment, "dimension", "dimension_name", default="细分维度"))
        voice_count = _segment_voice_count(segment)
        listing_share = _first(segment, "listing_share", default=None)
        sales_share = _first(segment, "sales_share", default=None)
        supply_demand = _first(segment, "supply_demand_index", default=None)
        needs = _segment_collection(segment, "needs", "need_stats", "need_stats_all_history")
        pains = _segment_collection(segment, "dissatisfactions", "dissatisfaction", "pain_points")
        scenarios = _segment_collection(segment, "scenarios", "use_scenes")
        diy = _segment_collection(segment, "diy_workarounds", "workarounds")
        ideas = _segment_collection(segment, "innovations", "new_needs", "ideas")
        blocks.append(
            '<article class="segment-card">'
            '<header><div>'
            f'<p class="section-kicker">TOP {rank} · {_escape(dimension)}</p><h3>{_escape(name)}</h3>'
            '<p>该细分使用全部已保存历史留言重算，不与其他细分直接相加。</p>'
            f'</div><span class="segment-badge">{_format_number(voice_count)} 条消费者表达</span></header>'
            '<div class="segment-metrics">'
            f'<div><span>Listing占比</span><strong>{_format_share(listing_share)}</strong></div>'
            f'<div><span>销量占比</span><strong>{_format_share(sales_share)}</strong></div>'
            f'<div><span>供需指数</span><strong>{_format_number(supply_demand)}</strong></div>'
            f'<div><span>消费者表达</span><strong>{_format_number(voice_count)}</strong></div>'
            '</div><div class="three-col">'
            + _compact_signals("主要需求", needs)
            + _compact_signals("主要不满意", pains)
            + _compact_signals("典型场景", scenarios)
            + _compact_signals("DIY与绕行", diy)
            + _compact_signals("新需求与创意", ideas)
            + '</div></article>'
        )
    return (
        '<section class="report-section panel" id="segments">'
        + _section_head(
            "segments-heading",
            "机会维度深挖",
            "Top3细分的全历史消费者声音",
            "Top3仍沿用机会分析的供需筛选结果；这里只替换消费者声音的统计口径。",
        )
        + ("".join(blocks) if blocks else '<p class="empty-state">暂无Top3细分数据</p>')
        + '</section>'
    )


def _kano_presentation(value: Any) -> tuple[str, str]:
    token = _normalized_token(value)
    return KANO_PRESENTATION.get(token, ("待验证", "pending"))


def _render_kano(analysis: Mapping[str, Any]) -> str:
    items = _list(analysis.get("kano"))
    if not items:
        items = _list(_category_summary(analysis).get("kano"))
    cards: list[str] = []
    for raw in items[:20]:
        item = raw if isinstance(raw, Mapping) else {"label": raw}
        label = _item_label(item)
        kano_value = _first(
            item,
            "kano_type",
            "kano",
            "classification",
            "category",
            "type",
            default="待验证",
        )
        kano_label, css_class = _kano_presentation(kano_value)
        # Unknown/insufficient classifications are an audit outcome, not a
        # consumer-facing KANO type.  The all-history report omits them instead
        # of turning evidence sufficiency into another visual tier.
        if css_class == "pending":
            continue
        count = _item_count(item)
        share = _item_share(item)
        rationale = _first(item, "rationale", "reason", "design_response", default="需通过原型测试和正式问卷继续验证。")
        cards.append(
            f'<article class="kano-item {_escape(css_class)}"><div class="kano-head">'
            f'<h3>{_escape(label)}</h3><span class="kano-label">{_escape(kano_label)}</span></div>'
            f'<div class="insight-meta"><strong>{_format_number(count)} 条 · {_format_share(share)}</strong></div>'
            f'<p><strong>产品含义：</strong>{_escape(rationale)}</p></article>'
        )
    return (
        '<section class="report-section panel" id="kano">'
        + _section_head(
            "kano-heading",
            "需求属性",
            "消费者声音推断型 KANO",
            "类型名称全部中文化；这里只用于产品优先级判断，不能替代正式双向问卷。",
        )
        + ('<div class="kano-grid">' + "".join(cards) + '</div>' if cards else '<p class="empty-state">暂无可展示的需求属性判断</p>')
        + '</section>'
    )


def _render_innovations(analysis: Mapping[str, Any]) -> str:
    items = _list(analysis.get("new_needs"))
    cards: list[str] = []
    for raw in items[:15]:
        item = raw if isinstance(raw, Mapping) else {"label": raw}
        label = _item_label(item)
        need_type = _public_text(_first(item, "type_label", "need_type", "source_type", "type", default="消费者需求"))
        count = _item_count(item)
        share = _item_share(item)
        fields = (
            ("消费者问题", _first(item, "consumer_problem", "problem", "pain", default="")),
            ("现有绕行", _first(item, "current_workaround", "workaround", "diy", default="")),
            ("供给缺口", _first(item, "supply_gap", "gap", "finding", default="")),
            ("产品机会", _first(item, "product_response", "opportunity", "proposed_solution", default="")),
            ("下一步验证", _first(item, "next_test", "validation", default="")),
        )
        details = "".join(
            f'<dt>{_escape(field)}</dt><dd>{_escape(value)}</dd>'
            for field, value in fields
            if value not in (None, "", [], {})
        )
        cards.append(
            '<article class="innovation-item"><header><div>'
            f'<span>{_escape(need_type)}</span><h3>{_escape(label)}</h3></div>'
            f'<span>{_format_number(count)} 条 · {_format_share(share)}</span></header>'
            + (f'<dl>{details}</dl>' if details else "")
            + '</article>'
        )
    return (
        '<section class="report-section panel" id="innovation">'
        + _section_head(
            "innovation-heading",
            "未满足需求",
            "新需求、绕行方案与产品机会",
            "消费者明确创意、DIY绕行和重复痛点推导分开解释；产品团队创意不冒充消费者留言。",
        )
        + ('<div class="innovation-list">' + "".join(cards) + '</div>' if cards else '<p class="empty-state">暂无可展示的新需求</p>')
        + '</section>'
    )


def _parse_image_overrides(values: Sequence[str], analysis_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ReportError(f"概念图参数必须为 CONCEPT_ID=PATH：{value}")
        concept_id, raw_path = value.split("=", 1)
        concept_id = concept_id.strip()
        if not concept_id or not raw_path.strip():
            raise ReportError(f"概念图参数不能为空：{value}")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = analysis_dir / path
        result[concept_id] = path.resolve()
    return result


def _image_data_uri(path: Path) -> tuple[str, str, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReportError(f"无法读取概念图：{path}（{exc}）") from exc
    mime_type = mimetypes.guess_type(path.name)[0] or ""
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ReportError(f"不支持的概念图格式：{path.name}")
    digest = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}", mime_type, digest


def _concept_image(
    concept: Mapping[str, Any],
    *,
    analysis_dir: Path,
    overrides: Mapping[str, Path],
) -> tuple[str | None, str | None]:
    concept_id = str(_first(concept, "concept_id", "id", default=""))
    path = overrides.get(concept_id)
    artifact = _mapping(concept.get("image_artifact"))
    if path is None:
        raw = _first(artifact, "path", default=_first(concept, "image_path", default=""))
        if raw:
            path = Path(str(raw)).expanduser()
            if not path.is_absolute():
                path = analysis_dir / path
            path = path.resolve()
    if path is None or not path.is_file():
        return None, None
    data_uri, _, digest = _image_data_uri(path)
    declared = str(_first(artifact, "sha256", default="")).strip().casefold()
    if declared and declared != digest:
        raise ReportError(f"概念图SHA-256不一致：{path.name}")
    return data_uri, digest


def _price_text(value: Any) -> str:
    if isinstance(value, Mapping):
        currency = _public_text(_first(value, "currency", default="USD"))
        minimum = _first(value, "min", "minimum", default=None)
        maximum = _first(value, "max", "maximum", default=None)
        if minimum is not None or maximum is not None:
            return f"{currency} {_format_number(minimum)}–{_format_number(maximum)}"
        return _public_text(_first(value, "assumption", "description", default=""))
    return _public_text(value)


def _cmf_text(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _public_text(value)
    parts: list[str] = []
    colors = _list(value.get("colors"))
    finishes = _list(value.get("finishes"))
    language = _first(value, "visual_language", "appearance", default="")
    if colors:
        parts.append("颜色：" + "、".join(_public_text(item) for item in colors))
    if finishes:
        parts.append("表面：" + "、".join(_public_text(item) for item in finishes))
    if language:
        parts.append("视觉：" + _public_text(language))
    return "；".join(parts)


def _moscow_items(concept: Mapping[str, Any], key: str) -> list[Any]:
    moscow = _mapping(concept.get("moscow"))
    aliases = {
        "must": ("must", "必须包含"),
        "should": ("should", "应当包含"),
        "could": ("could", "可以包含"),
        "wont": ("wont", "won_t", "won't", "本版本不包含", "没有必要包含"),
    }
    for alias in aliases[key]:
        value = moscow.get(alias)
        if isinstance(value, list):
            return value
    return []


def _render_moscow(concept: Mapping[str, Any]) -> str:
    labels = (
        ("must", "必须包含", "must"),
        ("should", "应当包含", "should"),
        ("could", "可以包含", "could"),
        ("wont", "本版本不包含", "wont"),
    )
    cards = []
    for key, label, css_class in labels:
        cards.append(
            f'<article class="moscow-card {css_class}"><span class="priority-tag {css_class}">{_escape(label)}</span>'
            + _list_html(_moscow_items(concept, key), limit=8, empty="本轮无明确项目")
            + '</article>'
        )
    return '<div class="moscow-grid">' + "".join(cards) + '</div>'


def _design_process(concept: Mapping[str, Any]) -> str:
    process = _mapping(concept.get("design_thinking"))
    steps = (
        ("empathize", "同理用户"),
        ("define", "定义问题"),
        ("ideate", "提出创意"),
        ("prototype", "制作原型"),
        ("test", "用户测试"),
        ("iteration", "迭代优化"),
    )
    cards: list[str] = []
    for index, (key, label) in enumerate(steps, start=1):
        item = _mapping(process.get(key))
        outputs = _list(_first(item, "outputs", "output", default=[]))
        gate = _first(item, "success_or_decision_gate", "gate", "next_step", default="")
        cards.append(
            '<article class="process-step">'
            f'<span>{index}</span><h4>{_escape(label)}</h4>'
            + _list_html(outputs, limit=5, empty="待补充")
            + (f'<small>决策门槛：{_escape(gate)}</small>' if gate else "")
            + '</article>'
        )
    return '<div class="process-grid">' + "".join(cards) + '</div>'


def _acceptance_table(concept: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for raw in _list(concept.get("acceptance_metrics")):
        item = raw if isinstance(raw, Mapping) else {"metric": raw}
        rows.append(
            '<tr>'
            f'<td>{_escape(_first(item, "metric", "name", default="验收项"))}</td>'
            f'<td>{_escape(_first(item, "target", "acceptance_criteria", default="待定义"))}</td>'
            f'<td>{_escape(_first(item, "test_method", "method", default="待定义"))}</td>'
            '</tr>'
        )
    if not rows:
        return '<p class="empty-state">尚未定义量化验收指标</p>'
    return (
        '<div class="table-frame"><table><thead><tr><th>验收项</th><th>目标</th><th>测试方法</th></tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div>'
    )


def _prompt_text(concept: Mapping[str, Any]) -> str:
    value = concept.get("image_prompt")
    if isinstance(value, Mapping):
        return _public_text(_first(value, "prompt_text", "prompt", default=""))
    return _public_text(value)


def _render_concepts(
    analysis: Mapping[str, Any],
    *,
    analysis_dir: Path,
    image_overrides: Mapping[str, Path],
) -> tuple[str, int, dict[str, str]]:
    concepts = [item for item in _list(analysis.get("product_concepts")) if isinstance(item, Mapping)][:3]
    segments = _segments(analysis)
    segment_names = {
        str(_first(item, "segment_id", "id", default=f"rank-{index}")): _public_text(
            _first(item, "feature", "name", "label", default=f"Top{index}细分")
        )
        for index, item in enumerate(segments, start=1)
    }
    blocks: list[str] = []
    embedded_count = 0
    image_digests: dict[str, str] = {}
    for index, concept in enumerate(concepts, start=1):
        concept_id = str(_first(concept, "concept_id", "id", default=f"concept_{index}"))
        name = _public_text(_first(concept, "name", "title", default=f"产品方向{index}"))
        segment_id = str(_first(concept, "segment_id", default=""))
        segment_name = segment_names.get(segment_id, f"Top{index}细分")
        image_uri, image_digest = _concept_image(
            concept, analysis_dir=analysis_dir, overrides=image_overrides
        )
        if image_uri:
            embedded_count += 1
            image_digests[concept_id] = str(image_digest)
            figure = (
                '<figure class="concept-figure">'
                f'<img src="{image_uri}" alt="{_escape(name)} 产品概念图">'
                f'<figcaption>{IMAGE_DISCLAIMER}</figcaption></figure>'
            )
        else:
            figure = '<div class="empty-state">概念图未提供；产品定义与提示词仍完整保留。</div>'
        target_consumers = _list(_first(concept, "target_consumers", "personas", default=[]))
        scenarios = _list(_first(concept, "use_scenarios", "scenarios", default=[]))
        features = _list(_first(concept, "features", "functions", default=[]))
        materials = _list(concept.get("materials"))
        technical_solution = _first(concept, "technical_solution", "technology", default="待工程定义")
        structure = _first(concept, "structure", "structural_solution", default="待工程定义")
        cmf = _cmf_text(_first(concept, "cmf", "appearance", default=""))
        target_price = _price_text(_first(concept, "target_price", "price", default=""))
        bom = _public_text(_first(concept, "bom_assumption", "bom", default=""))
        risks = _list(concept.get("risks"))
        dependencies = _list(concept.get("dependencies"))
        prompt = _prompt_text(concept)
        facts = (
            '<dl class="facts">'
            f'<dt>目标消费者</dt><dd>{_escape("、".join(_public_text(item) for item in target_consumers) or "待细化")}</dd>'
            f'<dt>使用场景</dt><dd>{_escape("、".join(_public_text(item) for item in scenarios) or "待细化")}</dd>'
            f'<dt>目标价格</dt><dd>{_escape(target_price or "待验证")}</dd>'
            f'<dt>BOM假设</dt><dd>{_escape(bom or "待验证")}</dd>'
            '</dl>'
        )
        blocks.append(
            '<article class="concept-card">'
            '<header class="concept-header"><div>'
            f'<p class="section-kicker">产品方向 {index} · {_escape(segment_name)}</p><h3>{_escape(name)}</h3>'
            f'</div><span class="segment-badge">绑定 Top{index} 细分</span></header>'
            '<div class="concept-hero">' + figure
            + '<div class="concept-brief"><h4>用户任务（JTBD）</h4>'
            f'<p class="jtbd">{_escape(_first(concept, "jtbd", default="待补充用户任务"))}</p>{facts}</div></div>'
            '<div class="spec-grid">'
            '<article><h3>功能与技术方案</h3><h4>核心功能</h4>' + _list_html(features, limit=10)
            + f'<h4>技术方案</h4><p>{_escape(technical_solution)}</p></article>'
            '<article><h3>结构、材料与外观</h3>'
            f'<p><strong>结构：</strong>{_escape(structure)}</p>'
            f'<p><strong>材料：</strong>{_escape("、".join(_public_text(item) for item in materials) or "待工程定义")}</p>'
            f'<p><strong>颜色与表面：</strong>{_escape(cmf or "待视觉定义")}</p></article>'
            '</div><h3>MoSCoW 产品优先级</h3>' + _render_moscow(concept)
            + '<h3>量化验收指标</h3>' + _acceptance_table(concept)
            + '<details><summary>查看设计思维过程</summary>' + _design_process(concept) + '</details>'
            + '<div class="two-col"><article class="card"><h3>风险</h3>' + _list_html(risks, limit=8)
            + '</article><article class="card"><h3>依赖</h3>' + _list_html(dependencies, limit=8) + '</article></div>'
            + ('<details><summary>查看概念图生成提示词</summary><div class="prompt-box">' + _escape(prompt) + '</div></details>' if prompt else "")
            + '</article>'
        )
    section = (
        '<section class="report-section panel" id="concepts">'
        + _section_head(
            "concepts-heading",
            "产品定义",
            "三个产品开发方向",
            "每个方向包含消费者、场景、功能、技术方案、材料外观、优先级和量化验收条件。",
        )
        + ("".join(blocks) if blocks else '<p class="empty-state">尚未生成产品方向</p>')
        + '</section>'
    )
    return section, embedded_count, image_digests


def _validation_items(analysis: Mapping[str, Any]) -> list[Any]:
    value = analysis.get("validation")
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        for key in ("checklist", "items", "future_validation_checklist"):
            if isinstance(value.get(key), list):
                return value[key]
    return _list(analysis.get("future_validation_checklist"))


def _status_label(value: Any) -> str:
    token = _normalized_token(value)
    return {
        "planned": "待执行",
        "pending": "待执行",
        "todo": "待执行",
        "inprogress": "进行中",
        "completed": "已完成",
        "done": "已完成",
        "blocked": "受阻",
        "待执行": "待执行",
        "进行中": "进行中",
        "已完成": "已完成",
        "受阻": "受阻",
    }.get(token, _public_text(value) or "待执行")


def _render_validation(analysis: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for raw in _validation_items(analysis):
        item = raw if isinstance(raw, Mapping) else {"objective": raw}
        validation_type = _first(item, "validation_type", "type", "name", default="验证任务")
        objective = _first(item, "objective", "purpose", default="待定义")
        method = _first(item, "method", "test_method", default="待定义")
        criteria = _first(item, "acceptance_criteria", "target", default="待定义")
        owner = _first(item, "owner_role", "owner", default="产品/工程团队")
        status = _status_label(_first(item, "status", "stage", default="待执行"))
        rows.append(
            '<tr>'
            f'<td>{_escape(validation_type)}</td><td>{_escape(status)}</td><td>{_escape(objective)}</td>'
            f'<td><strong>{_escape(method)}</strong><small>通过标准：{_escape(criteria)}</small></td>'
            f'<td>{_escape(owner)}</td></tr>'
        )
    table = (
        '<div class="table-frame"><table><thead><tr><th>验证事项</th><th>阶段</th><th>目的</th><th>方法与通过标准</th><th>负责人</th></tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div>'
        if rows
        else '<p class="empty-state">尚未建立验证路线</p>'
    )
    return (
        '<section class="report-section panel" id="validation">'
        + _section_head(
            "validation-heading",
            "进入开发的门槛",
            "验证路线",
            "在投入模具、认证和大货前，先完成消费者、工程、兼容性和法规验证。",
        )
        + table + '</section>'
    )


def _voice_candidates(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []

    def append(values: Any) -> None:
        for item in _list(values):
            if isinstance(item, Mapping):
                candidates.append(item)

    append(analysis.get("representative_voices"))
    for semantic in _list(analysis.get("semantic_categories")):
        if isinstance(semantic, Mapping):
            append(semantic.get("representative_voices"))
    summary = _category_summary(analysis)
    for key in ("needs", "satisfactions", "dissatisfactions", "scenarios", "diy_workarounds", "innovations"):
        for item in _list(summary.get(key)):
            if isinstance(item, Mapping):
                append(item.get("representative_voices"))
    for item in _list(analysis.get("new_needs")):
        if isinstance(item, Mapping):
            append(item.get("representative_voices"))
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        excerpt = _public_text(_first(item, "excerpt", "text", "quote", "original_text", default=""))
        if not excerpt:
            continue
        platform = _public_text(_first(item, "platform", default="公开平台"))
        marker = _normalized_token(platform + "|" + excerpt)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
        if len(result) >= 18:
            break
    return result


def _render_voices(analysis: Mapping[str, Any]) -> str:
    cards: list[str] = []
    for item in _voice_candidates(analysis):
        platform = _public_text(_first(item, "platform", default="公开平台")).title()
        excerpt = _first(item, "excerpt", "text", "quote", "original_text", default="")
        summary = _first(item, "summary_zh", "summary", "interpretation", default="")
        semantic = _first(item, "semantic_label", "category_label", default="")
        cards.append(
            '<article class="voice-item">'
            f'<div class="voice-meta">{_escape(platform)}{(" · " + _escape(semantic)) if semantic else ""}</div>'
            f'<blockquote>{_escape(excerpt)}</blockquote>'
            + (f'<p><strong>中文摘要：</strong>{_escape(summary)}</p>' if summary else "")
            + '</article>'
        )
    return (
        '<section class="report-section panel" id="voices">'
        + _section_head(
            "voices-heading",
            "原声复核",
            "代表性消费者留言",
            "正文只展示少量代表性原声；完整编码与统计保留在JSON中。",
        )
        + ('<div class="voice-list">' + "".join(cards) + '</div>' if cards else '<p class="empty-state">暂无可展示的代表性原声</p>')
        + '</section>'
    )


def _limitation_text(item: Any) -> tuple[str, str, str]:
    if isinstance(item, Mapping):
        title = _public_text(_first(item, "title", "scope", "name", default="研究限制"))
        description = _public_text(_first(item, "description", "limitation", "impact", default=""))
        mitigation = _public_text(_first(item, "mitigation", "next_step", default=""))
        return title, description, mitigation
    return "研究限制", _public_text(item), ""


def _distribution_items(value: Any, *, label_keys: Sequence[str]) -> list[tuple[str, int, Any]]:
    """Normalize a platform/year distribution without exposing raw fields."""
    rows: list[tuple[str, int, Any]] = []
    if isinstance(value, Mapping):
        for label, raw in value.items():
            if isinstance(raw, Mapping):
                count = _integer(_first(raw, "count", "voices", "records", default=0))
                share = _first(raw, "share", "voice_share", default=None)
            else:
                count = _integer(raw)
                share = None
            if count:
                rows.append((_public_text(label).title(), count, share))
    elif isinstance(value, list):
        for raw in value:
            if not isinstance(raw, Mapping):
                continue
            label = ""
            for key in label_keys:
                if raw.get(key) not in (None, ""):
                    label = _public_text(raw[key]).title()
                    break
            count = _integer(_first(raw, "count", "voices", "records", default=0))
            share = _first(raw, "share", "voice_share", default=None)
            if label and count:
                rows.append((label, count, share))
    total = sum(count for _, count, _ in rows)
    normalized = [
        (label, count, share if share is not None else (count / total if total else None))
        for label, count, share in rows
    ]
    return sorted(normalized, key=lambda item: (-item[1], item[0]))


def _render_sample_structure(analysis: Mapping[str, Any]) -> str:
    structure = _mapping(analysis.get("sample_structure"))
    funnel = _funnel(analysis)
    platform_value = _first(
        structure,
        "platform_distribution",
        "platforms",
        default=funnel.get("platforms"),
    )
    year_value = _first(
        structure,
        "year_distribution",
        "years",
        default=_first(funnel, "year_distribution", "years", default={}),
    )
    platform_rows = _distribution_items(
        platform_value, label_keys=("platform", "name", "label")
    )
    year_rows = _distribution_items(year_value, label_keys=("year", "name", "label"))
    largest_video_share = _first(
        structure,
        "largest_single_video_share",
        "largest_video_share",
        "max_video_share",
        "largest_parent_content_share",
        default=_first(
            funnel,
            "largest_single_video_share",
            "largest_video_share",
            "largest_parent_content_share",
            default=None,
        ),
    )
    largest_video_count = _first(
        structure,
        "largest_single_video_count",
        "largest_video_count",
        "max_video_count",
        default=_first(
            funnel,
            "largest_single_video_count",
            "largest_video_count",
            default=None,
        ),
    )
    platform_html = _list_html(
        [f"{label}：{_format_number(count)}条（{_format_share(share)}）" for label, count, share in platform_rows],
        limit=12,
        empty="未提供平台分布",
    )
    year_html = _list_html(
        [f"{label}：{_format_number(count)}条（{_format_share(share)}）" for label, count, share in year_rows],
        limit=16,
        empty="未提供年份分布",
    )
    largest_text = (
        f"{_format_share(largest_video_share)}"
        if largest_video_share is not None
        else "未提供"
    )
    if largest_video_count is not None:
        largest_text += f"（{_format_number(largest_video_count)}条）"
    return (
        '<div class="three-col">'
        f'<article class="card"><h3>平台分布</h3>{platform_html}</article>'
        f'<article class="card"><h3>年份分布</h3>{year_html}</article>'
        '<article class="card"><h3>最大单视频贡献</h3>'
        f'<p class="metric-value">{_escape(largest_text)}</p>'
        '<p class="muted">用于判断单一内容是否过度主导样本；不改变留言计数。</p></article>'
        '</div>'
    )


def _render_method(analysis: Mapping[str, Any]) -> str:
    metadata = _mapping(analysis.get("metadata"))
    funnel = _funnel(analysis)
    source_db = Path(str(_first(metadata, "source_db", default="本地数据库"))).name
    no_network = _first(metadata, "no_network", default=True)
    limitations = []
    for raw in _list(analysis.get("limitations")):
        title, description, mitigation = _limitation_text(raw)
        if not description and not mitigation:
            continue
        limitations.append(
            '<article class="card">'
            f'<h3>{_escape(title)}</h3><p>{_escape(description)}</p>'
            + (f'<p><strong>应对：</strong>{_escape(mitigation)}</p>' if mitigation else "")
            + '</article>'
        )
    method_items = (
        f"数据源：{source_db}，共检查 {_format_number(funnel.get('examined_records'))} 条本地硬身份唯一留言",
        f"数据关系：{_format_number(funnel.get('discovered_records'))} 条是发现关系；{_format_number(funnel.get('hard_unique_records'))} 条才是去除同一底层重复发现后的硬唯一留言",
        "时间口径：不按发布时间筛选；有日期、无日期及更早的本地留言使用同一语义规则",
        "纳入规则：与产品相关，且命中六类语义中的任意一类",
        "排除规则：广告、机器人、空文本、纯转发及与产品无关内容不进入量化",
        "YouTube清洗：查询命中不直接证明相关性；只采用评论本身、已确认父级/根内容或同一视频多作者产品锚点建立产品语境，并排除创作者正文与推广内容",
        "计数规则：不做语义去重；不同留言即使表达相同，也分别计数",
        "多标签规则：同一留言可以同时进入多个需求或语义统计，因此各项占比不可相加",
        "全历史定义：对本地已经抓取并保存的语料做全量处理，不等于互联网或平台的全部历史留言",
        f"执行方式：{'完全离线，未发起新的网络采集' if no_network is not False else '基于既有本地数据重算'}",
    )
    return (
        '<section class="report-section panel" id="method">'
        + _section_head(
            "method-heading",
            "研究透明度",
            "方法与限制",
            "说明本轮如何从本地记录得到消费者需求，及结论不能覆盖的边界。",
        )
        + '<div class="method-note"><strong>本轮没有重新抓取数据。</strong>所有结果均由既有本地数据库离线清洗与重算。</div>'
        + '<ul>' + "".join(f'<li>{_escape(item)}</li>' for item in method_items) + '</ul>'
        + _render_sample_structure(analysis)
        + ('<div class="three-col">' + "".join(limitations) + '</div>' if limitations else "")
        + '</section>'
    )


def _render_content(
    analysis: Mapping[str, Any],
    *,
    analysis_dir: Path,
    image_overrides: Mapping[str, Path],
) -> tuple[str, int, dict[str, str]]:
    concepts_html, embedded_count, image_digests = _render_concepts(
        analysis, analysis_dir=analysis_dir, image_overrides=image_overrides
    )
    content = (
        _render_decision(analysis)
        + _render_funnel(analysis)
        + _render_semantics(analysis)
        + _render_category(analysis)
        + _render_segments(analysis)
        + _render_kano(analysis)
        + _render_innovations(analysis)
        + concepts_html
        + _render_validation(analysis)
        + _render_voices(analysis)
        + _render_method(analysis)
    )
    return content, embedded_count, image_digests


class _OfflineHTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.csp_values: list[str] = []
        self.template_version: str | None = None
        self.analysis_sha256: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        lowered = tag.casefold()
        if lowered == "script":
            self.errors.append("报告不得包含script标签")
        if lowered in {"iframe", "object", "embed", "form"}:
            self.errors.append(f"报告不得包含{lowered}标签")
        if lowered == "link" and values.get("rel", "").casefold() == "stylesheet":
            self.errors.append("报告不得引用外部样式表")
        if lowered == "img":
            src = values.get("src", "")
            if not src.startswith("data:image/"):
                self.errors.append("所有图片必须内嵌为data URI")
        for attribute in ("src", "href"):
            value = values.get(attribute, "").strip().casefold()
            if value.startswith(("http://", "https://", "file://", "//")):
                self.errors.append(f"报告包含外部{attribute}依赖")
        if lowered == "meta" and values.get("http-equiv", "").casefold() == "content-security-policy":
            self.csp_values.append(values.get("content", ""))
        if lowered == "meta" and values.get("name") == "all-history-report-template-version":
            self.template_version = values.get("content")
        if lowered == "meta" and values.get("name") == "analysis-sha256":
            self.analysis_sha256 = values.get("content")


def validate_report_html(text: str) -> list[str]:
    errors: list[str] = []
    if "{{" in text or "}}" in text:
        errors.append("报告仍包含未替换模板占位符")
    inspector = _OfflineHTMLInspector()
    try:
        inspector.feed(text)
        inspector.close()
    except Exception as exc:  # pragma: no cover - HTMLParser is intentionally tolerant
        errors.append(f"HTML解析失败：{exc}")
    errors.extend(inspector.errors)
    if REQUIRED_CSP not in inspector.csp_values:
        errors.append("报告缺少固定离线CSP")
    if inspector.template_version != TEMPLATE_VERSION:
        errors.append("报告模板版本不正确")
    if not re.fullmatch(r"[0-9a-f]{64}", str(inspector.analysis_sha256 or "")):
        errors.append("报告缺少有效的analysis-sha256元数据")
    lowered = text.casefold()
    for term in FORBIDDEN_VISIBLE_TERMS:
        if term.casefold() in lowered:
            errors.append(f"报告包含不应展示的内部词：{term}")
    if "@media print" not in text or "@media (max-width: 680px)" not in text:
        errors.append("报告缺少打印或移动端样式")
    return list(OrderedDict.fromkeys(errors))


def _format_generated_at(value: Any) -> str:
    text = _public_text(value)
    if not text:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    return text


def _validate_all_history_contract(
    document: Mapping[str, Any],
    *,
    label: str,
    require_kano: bool,
) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise ReportError(f"{label}顶层必须是对象")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ReportError(
            f"{label}.schema_version必须严格等于{SCHEMA_VERSION}"
        )
    metadata = document.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ReportError(f"{label}.metadata必须是对象")
    if metadata.get("no_network") is not True:
        raise ReportError(f"{label}.metadata.no_network必须严格为true")
    if metadata.get("date_filter_applied") is not False:
        raise ReportError(
            f"{label}.metadata.date_filter_applied必须严格为false"
        )
    declared_source_hash = str(metadata.get("source_db_sha256") or "").strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", declared_source_hash):
        raise ReportError(f"{label}.metadata.source_db_sha256必须是64位小写SHA-256")
    if require_kano:
        kano_items = document.get("kano")
        if not isinstance(kano_items, list):
            raise ReportError(f"{label}.kano必须是数组")
        kano_collections: list[tuple[str, list[Any]]] = [(f"{label}.kano", kano_items)]
        category_summary = document.get("category_summary")
        if isinstance(category_summary, Mapping) and "kano" in category_summary:
            category_kano = category_summary.get("kano")
            if not isinstance(category_kano, list):
                raise ReportError(f"{label}.category_summary.kano必须是数组")
            kano_collections.append(
                (f"{label}.category_summary.kano", category_kano)
            )
        for collection_label, collection in kano_collections:
            for index, item in enumerate(collection):
                if not isinstance(item, Mapping):
                    raise ReportError(f"{collection_label}[{index}]必须是对象")
                kano_type = item.get("kano_type")
                if kano_type not in ALLOWED_KANO_TYPES:
                    raise ReportError(
                        f"{collection_label}[{index}].kano_type只允许五种中文类型"
                    )
    return metadata


def render_report(
    analysis: Mapping[str, Any],
    *,
    analysis_path: Path,
    template_path: Path,
    output_path: Path,
    title: str | None = None,
    image_args: Sequence[str] = (),
) -> dict[str, Any]:
    metadata = _validate_all_history_contract(
        analysis,
        label="全历史分析",
        require_kano=True,
    )
    project = _mapping(analysis.get("project"))
    marketplace = _public_text(
        _first(project, "marketplace", default=_first(metadata, "marketplace", default="US"))
    ) or "US"
    category_keyword = _public_text(
        _first(project, "category_keyword", "product_category", default="目标商品")
    ) or "目标商品"
    report_title = title or f"{category_keyword}：全历史消费者声音与产品创意开发报告"
    generated_at = _format_generated_at(
        _first(metadata, "generated_at", default=analysis.get("generated_at"))
    )
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"无法读取报告模板：{template_path}（{exc}）") from exc
    analysis_sha256 = hashlib.sha256(analysis_path.read_bytes()).hexdigest()
    overrides = _parse_image_overrides(image_args, analysis_path.parent)
    content, embedded_count, image_digests = _render_content(
        analysis,
        analysis_dir=analysis_path.parent,
        image_overrides=overrides,
    )
    replacements = {
        "{{ANALYSIS_SHA256}}": analysis_sha256,
        "{{MARKETPLACE}}": _escape(marketplace),
        "{{TITLE}}": _escape(report_title),
        "{{GENERATED_AT}}": _escape(generated_at),
        "{{CONTENT}}": content,
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    errors = validate_report_html(rendered)
    if errors:
        raise ReportError("离线HTML校验失败：" + "；".join(errors))
    _atomic_write_text(output_path, rendered)
    report_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "template_version": TEMPLATE_VERSION,
        "analysis_path": str(analysis_path.resolve()),
        "analysis_sha256": analysis_sha256,
        "report_path": str(output_path.resolve()),
        "report_sha256": report_sha256,
        "standalone_html": True,
        "external_runtime_dependencies": 0,
        "embedded_image_count": embedded_count,
        "image_sha256": image_digests,
    }


def _manifest_artifact_path(manifest_path: Path, artifact_path: Path) -> str:
    manifest_root = manifest_path.parent.resolve()
    resolved = artifact_path.resolve()
    try:
        return resolved.relative_to(manifest_root).as_posix()
    except ValueError:
        return str(resolved)


def _declared_dashboard_hashes(
    document: Mapping[str, Any],
    *,
    label: str,
) -> list[str]:
    values: list[str] = []
    containers = [
        document.get("metadata"),
        document.get("project"),
    ]
    scalar_keys = (
        "dashboard_sha256",
        "opportunity_dashboard_sha256",
        "original_dashboard_sha256",
    )
    mapping_keys = ("dashboard", "opportunity_dashboard")
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in scalar_keys:
            if key not in container:
                continue
            value = str(container.get(key) or "").strip().casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ReportError(f"{label}.{key}不是有效SHA-256")
            values.append(value)
        for key in mapping_keys:
            item = container.get(key)
            if not isinstance(item, Mapping) or "sha256" not in item:
                continue
            value = str(item.get("sha256") or "").strip().casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ReportError(f"{label}.{key}.sha256不是有效SHA-256")
            values.append(value)
    return values


def _declared_path_matches(
    raw_path: Any,
    expected: Path,
    *,
    base_dir: Path,
    label: str,
) -> None:
    text = str(raw_path or "").strip()
    if not text:
        return
    declared = Path(text).expanduser()
    if not declared.is_absolute():
        declared = base_dir / declared
    if declared.resolve() != expected.resolve():
        raise ReportError(f"{label}与命令参数不是同一文件")


def finalize_manifest(
    *,
    manifest_path: Path,
    coding_path: Path,
    analysis_path: Path,
    report_path: Path,
    source_db_path: Path,
    dashboard_path: Path,
    status: str,
    source_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    if status not in {"ready", "partial", "failed"}:
        raise ReportError("status只允许ready、partial或failed")
    manifest_path = manifest_path.expanduser().resolve()
    coding_path = coding_path.expanduser().resolve()
    analysis_path = analysis_path.expanduser().resolve()
    report_path = report_path.expanduser().resolve()
    source_db_path = source_db_path.expanduser().resolve()
    dashboard_path = dashboard_path.expanduser().resolve()
    if source_snapshot_path is not None:
        source_snapshot_path = source_snapshot_path.expanduser().resolve()

    # Load and validate every input before constructing a candidate manifest.
    manifest = _load_json(manifest_path)
    coding = _load_json(coding_path)
    analysis = _load_json(analysis_path)
    coding_metadata = _validate_all_history_contract(
        coding,
        label="全历史编码",
        require_kano=False,
    )
    analysis_metadata = _validate_all_history_contract(
        analysis,
        label="全历史分析",
        require_kano=True,
    )
    coding_source_hash = str(coding_metadata["source_db_sha256"]).casefold()
    analysis_source_hash = str(analysis_metadata["source_db_sha256"]).casefold()
    if coding_source_hash != analysis_source_hash:
        raise ReportError("Coding与Analysis声明的source_db_sha256不一致")
    _declared_path_matches(
        coding_metadata.get("source_db"),
        source_db_path,
        base_dir=coding_path.parent,
        label="Coding metadata.source_db",
    )
    _declared_path_matches(
        analysis_metadata.get("source_db"),
        source_db_path,
        base_dir=analysis_path.parent,
        label="Analysis metadata.source_db",
    )

    source_db_hash = _file_sha256(source_db_path, "source-db")
    if source_db_hash != coding_source_hash:
        raise ReportError("实际source-db SHA-256与Coding/Analysis声明不一致")

    dashboard_hash = _file_sha256(dashboard_path, "dashboard")
    declared_dashboard_hashes = _declared_dashboard_hashes(
        coding,
        label="Coding",
    ) + _declared_dashboard_hashes(
        analysis,
        label="Analysis",
    )
    snapshot_hash: str | None = None
    if source_snapshot_path is not None:
        snapshot = _load_json(source_snapshot_path)
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            raise ReportError("source-snapshot.schema_version不正确")
        if snapshot.get("no_network") is not True:
            raise ReportError("source-snapshot.no_network必须严格为true")
        snapshot_source_hash = str(snapshot.get("source_db_sha256") or "").casefold()
        if snapshot_source_hash != source_db_hash:
            raise ReportError("source-snapshot的source_db_sha256与实际文件不一致")
        _declared_path_matches(
            snapshot.get("source_db"),
            source_db_path,
            base_dir=source_snapshot_path.parent,
            label="source-snapshot.source_db",
        )
        dashboard_snapshot = snapshot.get("opportunity_dashboard")
        if isinstance(dashboard_snapshot, Mapping):
            _declared_path_matches(
                dashboard_snapshot.get("path"),
                dashboard_path,
                base_dir=source_snapshot_path.parent,
                label="source-snapshot.opportunity_dashboard.path",
            )
            snapshot_hash = str(dashboard_snapshot.get("sha256") or "").casefold()
        elif snapshot.get("dashboard_sha256") is not None:
            snapshot_hash = str(snapshot.get("dashboard_sha256") or "").casefold()
        if snapshot_hash is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", snapshot_hash):
                raise ReportError("source-snapshot中的dashboard SHA-256无效")
            declared_dashboard_hashes.append(snapshot_hash)
    if not declared_dashboard_hashes:
        raise ReportError(
            "缺少dashboard SHA-256声明；请提供--source-snapshot或在metadata中记录"
        )
    if any(value != dashboard_hash for value in declared_dashboard_hashes):
        raise ReportError("实际dashboard SHA-256与快照/metadata声明不一致")

    analysis_hash = _file_sha256(analysis_path, "analysis")
    coding_hash = _file_sha256(coding_path, "coding")
    report_hash = _file_sha256(report_path, "report")
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReportError("report不是有效UTF-8 HTML") from exc
    html_errors = validate_report_html(report_text)
    if html_errors:
        raise ReportError("report未通过离线校验：" + "；".join(html_errors))
    inspector = _OfflineHTMLInspector()
    inspector.feed(report_text)
    inspector.close()
    if inspector.analysis_sha256 != analysis_hash:
        raise ReportError("HTML内嵌analysis-sha256与实际Analysis文件不一致")

    artifacts = manifest.get("artifacts")
    if artifacts is None:
        artifacts = {}
    if not isinstance(artifacts, Mapping):
        raise ReportError("manifest.artifacts必须是对象")
    status_object = manifest.get("status")
    if status_object is None:
        status_object = {}
    if not isinstance(status_object, Mapping):
        raise ReportError("manifest.status必须是对象")
    updated = copy.deepcopy(dict(manifest))
    updated_artifacts = dict(artifacts)
    updated_artifacts.update(
        {
            "consumer_voice_all_history_coding": _manifest_artifact_path(
                manifest_path, coding_path
            ),
            "consumer_voice_all_history_analysis": _manifest_artifact_path(
                manifest_path, analysis_path
            ),
            "consumer_voice_all_history_report_html": _manifest_artifact_path(
                manifest_path, report_path
            ),
        }
    )
    updated_status = dict(status_object)
    updated_status["consumer_voice_all_history"] = status
    updated["artifacts"] = updated_artifacts
    updated["status"] = updated_status

    # Detect source/artifact mutation immediately before the only write.
    prewrite_hashes = {
        "source-db": _file_sha256(source_db_path, "source-db"),
        "dashboard": _file_sha256(dashboard_path, "dashboard"),
        "coding": _file_sha256(coding_path, "coding"),
        "analysis": _file_sha256(analysis_path, "analysis"),
        "report": _file_sha256(report_path, "report"),
    }
    expected_hashes = {
        "source-db": source_db_hash,
        "dashboard": dashboard_hash,
        "coding": coding_hash,
        "analysis": analysis_hash,
        "report": report_hash,
    }
    if prewrite_hashes != expected_hashes:
        raise ReportError("最终校验期间输入文件发生变化，manifest未更新")
    _atomic_write_json(manifest_path, updated)
    return {
        "status": "updated",
        "manifest": str(manifest_path),
        "consumer_voice_all_history": status,
        "artifact_keys": [
            "consumer_voice_all_history_coding",
            "consumer_voice_all_history_analysis",
            "consumer_voice_all_history_report_html",
        ],
        "preserved_existing_keys": True,
        "source_db_sha256": source_db_hash,
        "dashboard_sha256": dashboard_hash,
        "coding_sha256": coding_hash,
        "analysis_sha256": analysis_hash,
        "report_sha256": report_hash,
        "source_snapshot_sha256": (
            _file_sha256(source_snapshot_path, "source-snapshot")
            if source_snapshot_path is not None
            else None
        ),
    }


def _default_template() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "consumer_all_history_report.template.html"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全历史本地消费者声音独立HTML报告工具"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render", help="生成单文件离线HTML")
    render.add_argument("--analysis", required=True, type=Path)
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--template", type=Path, default=_default_template())
    render.add_argument("--title")
    render.add_argument(
        "--concept-image",
        action="append",
        default=[],
        metavar="CONCEPT_ID=PATH",
        help="覆盖某个产品方向的本地概念图，可重复传入",
    )
    check = subparsers.add_parser("check", help="检查已有HTML是否为离线安全报告")
    check.add_argument("--report", required=True, type=Path)
    finalize = subparsers.add_parser(
        "finalize-manifest",
        help="校验全历史产物并原子增量更新project_manifest.json",
    )
    finalize.add_argument("--manifest", required=True, type=Path)
    finalize.add_argument("--coding", required=True, type=Path)
    finalize.add_argument("--analysis", required=True, type=Path)
    finalize.add_argument("--report", required=True, type=Path)
    finalize.add_argument("--source-db", required=True, type=Path)
    finalize.add_argument("--dashboard", required=True, type=Path)
    finalize.add_argument(
        "--status",
        required=True,
        choices=("ready", "partial", "failed"),
    )
    finalize.add_argument("--source-snapshot", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "render":
            analysis_path = args.analysis.expanduser().resolve()
            template_path = args.template.expanduser().resolve()
            output_path = args.output.expanduser().resolve()
            analysis = _load_json(analysis_path)
            receipt = render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=template_path,
                output_path=output_path,
                title=args.title,
                image_args=args.concept_image,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check":
            text = args.report.expanduser().resolve().read_text(encoding="utf-8")
            errors = validate_report_html(text)
            payload = {
                "status": "ok" if not errors else "failed",
                "report": str(args.report.expanduser().resolve()),
                "errors": errors,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if not errors else 2
        if args.command == "finalize-manifest":
            receipt = finalize_manifest(
                manifest_path=args.manifest,
                coding_path=args.coding,
                analysis_path=args.analysis,
                report_path=args.report,
                source_db_path=args.source_db,
                dashboard_path=args.dashboard,
                status=args.status,
                source_snapshot_path=args.source_snapshot,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0
    except (ReportError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
