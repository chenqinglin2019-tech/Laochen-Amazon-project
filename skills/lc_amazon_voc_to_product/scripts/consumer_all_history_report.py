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
TEMPLATE_VERSION = "1.5.0"
SUPPORTED_TEMPLATE_VERSIONS = frozenset({"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", TEMPLATE_VERSION})
IMAGE_DISCLAIMER = "AI概念表达，非工程图或认证结果"
ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
REQUIRED_CSP = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
    "script-src 'none'; connect-src 'none'; font-src 'none'; media-src 'none'; "
    "object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)
INSIGHT_JSON_FILES = (
    "keyword_summary.json", "review_summary.json", "social_summary.json",
    "recommended_qa.json", "active_question_plan.json", "need_evidence_links.json",
)
INSIGHT_JSONL_FILES = ("active_qa_ledger.jsonl", "flyfus_receipts.jsonl")

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


def _load_insight_dir(path: Path | None) -> Mapping[str, Any]:
    """Read only known V5 sidecars from one explicit run directory.

    These artifacts add research provenance to the report.  They never alter the
    Coding/Analysis consumer denominators or KANO calculation.
    """
    if path is None:
        return {"sha256": "none", "files": {}, "json": {}, "jsonl": {}}
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ReportError(f"insight-dir 必须是既有 V5 运行目录：{root}")
    files: dict[str, str] = {}
    objects: dict[str, Mapping[str, Any]] = {}
    streams: dict[str, list[Mapping[str, Any]]] = {}
    for name in INSIGHT_JSON_FILES + INSIGHT_JSONL_FILES:
        candidate = root / name
        if not candidate.exists():
            continue
        if candidate.is_symlink() or not candidate.is_file() or candidate.resolve().parent != root:
            raise ReportError(f"insight-dir 只允许直接包含的常规文件：{name}")
        files[name] = _file_sha256(candidate, f"insight {name}")
        if name.endswith(".json"):
            value = _load_json(candidate)
            objects[name] = value
            continue
        rows: list[Mapping[str, Any]] = []
        try:
            raw_lines = candidate.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ReportError(f"无法读取 insight {name}") from exc
        for line_number, raw in enumerate(raw_lines, start=1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ReportError(f"insight {name} 第 {line_number} 行不是有效 JSON") from exc
            if not isinstance(value, Mapping):
                raise ReportError(f"insight {name} 第 {line_number} 行必须为对象")
            rows.append(value)
        streams[name] = rows
    digest_input = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "path": str(root), "sha256": hashlib.sha256(digest_input).hexdigest(),
        "files": files, "json": objects, "jsonl": streams,
    }


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
        meta = [f"{_format_number(count)} 条有效声音"] if count else []
        if share is not None:
            meta.append(_format_share(share))
        author_count = _integer(_first(item, "known_authors", "authors", "author_count", default=0))
        anonymous_author_voices = _integer(_first(item, "anonymous_author_voice_records", default=0))
        thread_count = _integer(_first(item, "threads", "thread_count", default=0))
        platform_count, _ = _platform_summary(
            _first(item, "platforms", "platform_count", default=0)
        )
        if author_count:
            author_label = "位可识别发声者" if "known_authors" in item else "条作者记录（旧口径待复核）"
            meta.append(f"{_format_number(author_count)} {author_label}")
        if anonymous_author_voices:
            meta.append(f"{_format_number(anonymous_author_voices)} 条作者未公开")
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


def _single_segment_mode(analysis: Mapping[str, Any]) -> bool:
    return analysis.get("workflow_mode") == "single_segment" or _mapping(analysis.get("metadata")).get("workflow_mode") == "single_segment"


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


def _front_amazon_counts(analysis: Mapping[str, Any]) -> tuple[Any, Any]:
    row = _front_source_counts(analysis)["amazon"]
    return row["qualified_consumer_voices"], row["hard_unique_records"]


def _front_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    number = _number(value)
    return int(number) if number is not None and number >= 0 and number == int(number) else None


def _front_processing_complete(analysis: Mapping[str, Any]) -> bool:
    coding = _mapping(analysis.get("coding_review"))
    unreviewed = _number(coding.get("unreviewed_records"))
    if unreviewed is None:
        unreviewed = max(0, (_number(coding.get("pending")) or 0) - (_number(coding.get("completed_undetermined")) or 0))
    return analysis.get("processing_status") in {"complete", "completed"} and unreviewed == 0


def _front_sampling(analysis: Mapping[str, Any]) -> tuple[int | None, int | None, int | None]:
    sampling = _mapping(_mapping(analysis.get("report_front")).get("sampling"))
    values = tuple(_front_count(sampling.get(key)) for key in ("successful", "candidates", "failed"))
    success, candidates, failed = values
    if None in values or success + failed != candidates:
        return None, None, None
    return values


def _front_source_counts(analysis: Mapping[str, Any]) -> dict[str, dict[str, int | None]]:
    """Read per-platform counts; unavailable/malformed totals remain unknown."""
    keys = ("hard_unique_records", "qualified_consumer_voices", "excluded_records", "pending_records")
    groups = {"amazon": {key: None for key in keys}, "offsite": {key: None for key in keys}}
    platforms = _funnel(analysis).get("platforms")
    if isinstance(platforms, Mapping):
        # Historical dictionaries contain effective counts only, never raw counts.
        for group in groups:
            values = [_front_count(value) for name, value in platforms.items()
                      if (str(name).casefold() == "amazon") == (group == "amazon")]
            if all(value is not None for value in values):
                groups[group]["qualified_consumer_voices"] = sum(values)
        total = _front_count(_funnel(analysis).get("qualified_consumer_voices"))
        values = [groups[group]["qualified_consumer_voices"] for group in groups]
        if total is not None and all(value is not None for value in values) and sum(values) != total:
            groups["amazon"]["qualified_consumer_voices"] = groups["offsite"]["qualified_consumer_voices"] = None
        return groups
    if not isinstance(platforms, list):
        return groups
    rows = [_mapping(row) for row in platforms]
    if any(not str(row.get("platform", "")).strip() for row in rows):
        return groups
    names = [str(row["platform"]).casefold() for row in rows]
    if len(names) != len(set(names)):
        return groups
    for group in groups:
        selected = [row for row in rows if (str(row["platform"]).casefold() == "amazon") == (group == "amazon")]
        for key in keys:
            values = [_front_count(row.get(key)) for row in selected]
            if all(value is not None for value in values):
                groups[group][key] = sum(values)
    for key in keys:
        amazon, offsite = groups["amazon"][key], groups["offsite"][key]
        total = _front_count(_funnel(analysis).get(key))
        if amazon is not None and offsite is not None and total is not None and amazon + offsite != total:
            groups["amazon"][key] = groups["offsite"][key] = None
    return groups


def _render_front_metrics(analysis: Mapping[str, Any]) -> str:
    sources = _front_source_counts(analysis)
    def cleaning_note(group: str) -> str:
        row = sources[group]
        excluded, pending = row["excluded_records"], row["pending_records"]
        if excluded is None or pending is None:
            return "清洗分项未提供；未知不作零"
        pending_label = "已审信息不足" if _front_processing_complete(analysis) else "待复核或信息不足"
        return "明确排除 " + _format_number(excluded) + " 条 · " + pending_label + " " + _format_number(pending) + " 条"
    cards = (
        ("Amazon 评论抓取量", sources["amazon"]["hard_unique_records"], "按原生评论 ID 合并", "同一评论跨子体不重复计数"),
        ("Amazon 清洗后有效评论", sources["amazon"]["qualified_consumer_voices"], "进入需求与产品分析", cleaning_note("amazon")),
        ("站外 VOC 抓取量", sources["offsite"]["hard_unique_records"], "按原生内容 ID 合并", "包含本轮站外评论及网页消费者表达"),
        ("站外清洗后有效 VOC", sources["offsite"]["qualified_consumer_voices"], "进入需求与产品分析", cleaning_note("offsite")),
    )
    kpis = '<div class="vf-kpis" aria-label="分渠道抓取与清洗数量">' + ''.join(
        '<article class="vf-kpi"><span class="vf-kpi-label">' + label + '</span><strong>'
        + _format_number(value) + '</strong><p>' + (note if value is not None else "未提供可核对数量")
        + '<span>' + detail + '</span></p></article>' for label, value, note, detail in cards) + '</div>'
    total = _funnel(analysis).get("qualified_consumer_voices")
    baseline = _mapping(_mapping(analysis.get("report_front")).get("baseline"))
    growth = ('<span class="vf-growth">' + _format_number(baseline.get("qualified_consumer_voices"))
              + ' → ' + _format_number(total) + '</span><span>条消费者原声</span>') if _front_count(baseline.get("qualified_consumer_voices")) is not None else '条消费者原声'
    success, candidates, failed = _front_sampling(analysis)
    coverage = _format_number(success) + '<span class="vf-kpi-denom"> / ' + _format_number(candidates) + '</span>' if success is not None else '—'
    note = (f'{_format_number(success)} 个读取成功<span class="vf-warning-text">{_format_number(failed)} 个接口失败，未视作零评论</span>'
            if success is not None else '未提供采集范围<span>未知覆盖不视作采集完成</span>')
    return kpis + '<div class="vf-source-totals">' + ''.join(
        '<article class="vf-source-total"><span class="vf-kpi-label">' + label + '</span><strong>'
        + value + '</strong><p>' + detail + '</p></article>'
        for label, value, detail in (("有效 VOC 总数", _format_number(total), growth), ("候选子体采集覆盖", coverage, note))) + '</div>'


def _render_front_layers(analysis: Mapping[str, Any]) -> str:
    amazon, _ = _front_amazon_counts(analysis)
    layers = _mapping(_mapping(analysis.get("report_front")).get("amazon_evidence_layers"))
    specs = (("at_least_one_current_need", "current", "至少一项当前适用需求"),
             ("only_unknown_or_historical_needs", "unknown", "仅未知或历史适用需求"),
             ("no_specific_need_general_or_comparison", "general", "泛化满意或比较背景"))
    values = [_front_count(layers.get(key)) for key, _, _ in specs]
    content = '<p class="vf-card-intro">未提供经过核对的评论适用性分层；不把未知变体归为子体缺陷。</p>'
    if None not in values and _front_count(amazon) is not None and sum(values) == amazon:
        bar = ''.join(f'<span class="vf-layer-{color}" style="flex:{value}"></span>' for (_, color, _), value in zip(specs, values))
        rows = ''.join('<div><dt><i class="vf-dot-' + color + '" aria-hidden="true"></i>' + label
                       + '</dt><dd><strong>' + _format_number(value) + '</strong><span>'
                       + _format_share(value / amazon if amazon else None) + '</span></dd></div>'
                       for (_, color, label), value in zip(specs, values))
        content = ('<p class="vf-card-intro">区分当前适用需求与关联背景，避免把混合款评价归为子体缺陷。</p>'
                   + ('<div class="vf-layer-bar" aria-hidden="true">' + bar + '</div>' if amazon else '')
                   + '<dl class="vf-layer-list">' + rows + '</dl>')
    return ('<section class="vf-evidence-card" aria-labelledby="vf-evidence-title"><div class="vf-card-heading">'
            '<h3 id="vf-evidence-title">Amazon 证据分层</h3><span>' + _format_number(amazon)
            + ' 条有效评论</span></div>' + content
            + '<p class="vf-context-note">购买变体未公开，“当前适用”不等于已确认购买该子体。</p></section>')


def _render_decision(analysis: Mapping[str, Any]) -> str:
    funnel = _funnel(analysis)
    summary = _category_summary(analysis)
    top_need = _first_ranked(summary, ("needs", "need_stats"))
    top_pain = _first_ranked(summary, ("dissatisfactions", "dissatisfaction_top10"))
    top_delight = _first_ranked(summary, ("satisfactions", "satisfaction_top10"))
    segments = _segments(analysis)
    lead_segment = segments[0] if segments else {}
    qualified = _integer(funnel.get("qualified_consumer_voices"))
    need_label = _item_label(top_need) if top_need else "尚未形成可排序需求"
    pain_label = _item_label(top_pain) if top_pain else "尚未形成可排序痛点"
    delight_label = _item_label(top_delight) if top_delight else "尚未形成可排序满意点"
    segment_label = _public_text(_first(lead_segment, "feature", "name", "label", default="已选细分待确认"))
    readiness = _mapping(analysis.get("evidence_readiness"))
    if readiness.get("status") == "sufficient" and top_need:
        headline = f'围绕“{need_label}”进入产品验证'
        if top_pain and pain_label != need_label:
            headline += f'，关注“{pain_label}”'
    elif top_need:
        headline = f'本地语料集中讨论“{need_label}”，开发判断仍需结合证据检查'
    else:
        headline = "整理已采集的消费者声音，补齐需求与产品验证依据"
    topics = ([row for row in _list(readiness.get("needs")) if isinstance(row, Mapping) and row.get("eligible") is True]
              if "needs" in readiness else _top_items(summary, "needs", "need_stats"))
    topic_html = ''.join('<span>' + _escape(_item_label(_mapping(item))) + ' <b>'
                         + _format_share(_number(_first(_mapping(item), "related_count", "count")) / qualified
                                         if qualified and _number(_first(_mapping(item), "related_count", "count")) is not None else None)
                         + '</b></span>' for item in topics[:3] if isinstance(item, Mapping))
    evidence = _inline_section(_render_evidence(analysis))
    marker = '<h3>核心需求依据、反证与适用性</h3>'
    evidence_front, boundary, protected = evidence.partition(marker)
    return (
        '<section class="decision-summary" id="decision"><div class="voc-front">'
        + _render_funnel(analysis)
        + _render_front_metrics(analysis)
        + '<section class="vf-conclusion" aria-labelledby="vf-conclusion-title">'
        '<div class="vf-conclusion-top"><span class="vf-section-label">本轮核心结论</span><span class="vf-tag">'
        + ('进入产品体验验证' if readiness.get("status") == "sufficient" and top_need else _escape(_evidence_label(analysis)))
        + '</span></div>'
        f'<h2 id="vf-conclusion-title">{_escape(headline)}</h2>'
        f'<p>全量本地清洗后纳入 {_format_number(qualified)} 条有效 VOC。机会筛选首项为“{_escape(segment_label)}”；主要满意来源为“{_escape(delight_label)}”。</p>'
        + ('<div class="vf-topic-row" aria-label="关键需求提及率">' + topic_html + '</div>' if topic_html else '')
        + '<p class="vf-context-note">提及率包含支持与反证，用于识别需求，不代表故障率或退货率。</p></section>'
        + evidence_front + '</div>' + boundary + protected + '</section>'
    )


def _render_funnel(analysis: Mapping[str, Any]) -> str:
    funnel = _funnel(analysis)
    discovered = _integer(funnel.get("discovered_records"))
    unique = _integer(funnel.get("hard_unique_records"))
    examined = _integer(funnel.get("examined_records"))
    excluded = _integer(funnel.get("excluded_records"))
    qualified = _integer(funnel.get("qualified_consumer_voices"))
    pending = _integer(funnel.get("pending_records"))
    undetermined = _integer(_mapping(analysis.get("coding_review")).get("completed_undetermined")) if _holistic_mode(analysis) else 0
    pending = max(0, pending - undetermined)
    platform_count, platform_names = _platform_summary(funnel.get("platforms"))
    steps = [
        ("发现关系", discovered, "同一留言可被多路发现"),
        ("硬身份唯一", unique, "仅合并同一底层留言"),
        ("完成本地检查", examined, "逐条进入清洗规则"),
        ("未纳入量化", excluded, "无关、营销、机器人或空内容"),
        ("有效 VOC", qualified, "进入需求与产品分析"),
    ]
    if pending:
        steps.insert(-1, ("待语义复核", pending, "保留原文，暂不计入有效分母"))
    if undetermined:
        steps.insert(-1, ("已判断但不确定", undetermined, "已完成处理，不计入有效声音"))
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
        + '<p class="vf-source-scope">累计已保存数据；按原生评论或内容 ID 合并，发现关系不等于独立评论数量。</p>'
        + f'<div class="funnel">{cards}</div>'
        + '<div class="method-note"><strong>漏斗说明：</strong>有效 VOC、明确排除、待复核与已审信息不足分别统计；已审信息不足不计入有效声音。未命中旧词典不自动排除。'
        + f'本轮有效数据覆盖 {_escape(platform_text)}。</div></section>'
    )


def _evidence_label(analysis: Mapping[str, Any]) -> str:
    return {
        "sufficient": "达到本轮证据门槛",
        "partial": "仍有证据缺口",
    }.get(_mapping(analysis.get("evidence_readiness")).get("status"), "尚未评估")


def _count_entries(value: Any) -> str:
    return _format_number(len(value) if isinstance(value, (list, dict)) else value)


def _representative_evidence(values: Any, *, empty: str) -> str:
    """Show at most three actual excerpts; audit identifiers never become prose."""
    rows = []
    for raw in _list(values):
        if not isinstance(raw, Mapping):
            continue
        excerpt = _first(raw, "excerpt", "raw_excerpt", "text", "quote", "original_text", default="")
        if not isinstance(excerpt, str) or not excerpt.strip():
            continue
        platform = _first(raw, "platform", "source_label", default="消费者原声")
        summary = _first(raw, "summary_zh", "summary", default="")
        rows.append(
            '<article class="voice-item">'
            f'<div class="voice-meta">{_escape(platform)}</div>'
            f'<blockquote>{_escape(excerpt)}</blockquote>'
            + (f'<p>{_escape(summary)}</p>' if isinstance(summary, str) and summary else "")
            + '</article>'
        )
        if len(rows) == 3:
            break
    return '<div class="voice-list">' + "".join(rows) + '</div>' if rows else f'<p>{_escape(empty)}</p>'


def _need_excerpts(analysis: Mapping[str, Any], need: Mapping[str, Any], *, counter: bool) -> list[Any]:
    supplied = _first(
        need,
        *(('representative_counter', 'counterevidence') if counter else ('representative_support', 'supporting_evidence')),
        default=[],
    )
    if supplied:
        return _list(supplied)
    index = _mapping(analysis.get("evidence_excerpt_index"))
    return [index[ref] for ref in _list(need.get("counter_refs" if counter else "support_refs")) if isinstance(ref, str) and ref in index][:3]


def _need_identifier(need: Mapping[str, Any]) -> str:
    return str(_first(need, "need_id", "need_code", "code", default="")).strip()


def _eligible_need_rows(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for row in _list(_mapping(analysis.get("evidence_readiness")).get("needs"))
            if isinstance(row, Mapping) and row.get("eligible") is True and _need_identifier(row)]


def _need_evidence_ids(need: Mapping[str, Any]) -> set[str]:
    ids = set(_list(need.get("support_refs"))) | set(_list(need.get("counter_refs")))
    for value in _mapping(need.get("applicability")).values():
        ids.update(value if isinstance(value, list) else [])
    return {str(value) for value in ids if isinstance(value, str) and value}


def _need_summary_fingerprint(need: Mapping[str, Any]) -> str:
    """Fingerprint the Python-owned evidence context before model summarisation."""
    payload = {
        "need_id": _need_identifier(need),
        "label": _item_label(need),
        "count": _first(need, "related_count", "count", default=0),
        "support_refs": sorted(str(value) for value in _list(need.get("support_refs"))),
        "counter_refs": sorted(str(value) for value in _list(need.get("counter_refs"))),
        "applicability": _mapping(need.get("applicability")),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _need_semantic_summary(analysis: Mapping[str, Any], need: Mapping[str, Any]) -> Mapping[str, Any]:
    container = _mapping(analysis.get("consumer_semantic_summaries"))
    rows = _list(container.get("needs"))
    key = _need_identifier(need)
    for raw in rows:
        item = _mapping(raw)
        if str(item.get("need_id") or "") == key:
            return item
    return {}


def _render_front_evidence(
    analysis: Mapping[str, Any], *, processing: str, check_html: str,
    review_html: str, saturation_label: str, batches_html: str,
) -> str:
    readiness = _mapping(analysis.get("evidence_readiness"))
    checks = {str(_mapping(row).get("code")): _mapping(row) for row in _list(readiness.get("checks"))}
    coding = _mapping(analysis.get("coding_review"))
    pending = coding.get("unreviewed_records")
    complete = _front_processing_complete(analysis)
    processed = _funnel(analysis).get("examined_records")
    progress_note = (_format_number(processed) + ' 条记录均已处理，无待复核记录'
                     if complete and _number(pending) == 0 else '已检查 ' + _format_number(processed)
                     + ' 条记录；未执行复核 ' + _format_number(pending) + ' 条')
    progress_label = '全量处理完成' if complete else '存在尚未完成复核的记录' if analysis.get("processing_status") in {"complete", "completed"} else processing
    rows = [(complete, progress_label, progress_note)]
    for code, label in (("quality", "质量抽检与问题闭环"), ("scenarios", "关键场景查漏已记录")):
        passed = checks.get(code, {}).get("passed")
        note = '已通过本轮检查' if passed is True else '尚未通过，查看验收详情' if passed is False else '未提供检查记录'
        rows.append((passed is True, label, note))
    check_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 12 4 4 8-8"/></svg>'
    unknown_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"/></svg>'
    status_rows = ''.join('<li>' + (check_icon if passed else unknown_icon) + '<span>' + _escape(label)
                          + '<small>' + _escape(note) + '</small></span></li>' for passed, label, note in rows)
    concepts = len(_list(analysis.get("product_concepts")))
    development_label = f'{concepts} 个已记录方向' if concepts else '待冻结'
    funnel = _funnel(analysis)
    platforms, _ = _platform_summary(funnel.get("platforms"))
    undetermined = coding.get("completed_undetermined")
    count_note = ('<p>' + _format_number(funnel.get("hard_unique_records")) + ' 条硬身份唯一记录中，'
                  + _format_number(funnel.get("qualified_consumer_voices")) + ' 条有效、'
                  + _format_number(funnel.get("excluded_records")) + ' 条排除。有效原声来自 '
                  + _format_number(platforms) + ' 个平台。'
                  + ('另有 ' + _format_number(undetermined) + ' 条已审信息不足，不计入有效分母。' if _number(undetermined) is not None else '') + '</p>')
    success, candidates, failed = _front_sampling(analysis)
    sampling_note = ('<p>' + _format_number(candidates) + ' 个候选子体中，' + _format_number(success)
                     + ' 个读取成功、' + _format_number(failed) + ' 个接口失败；失败不视作零评论。</p>') if success is not None else ''
    return (
        '<div class="vf-evidence-row">' + _render_front_layers(analysis)
        + '<section class="vf-status-card" id="evidence-heading" aria-labelledby="vf-status-title">'
        '<div class="vf-card-heading"><h3 id="vf-status-title">处理进度与证据充分性</h3></div>'
        '<ul class="vf-checks">' + status_rows + '</ul><p class="vf-context-note">'
        + _escape(_evidence_label(analysis)) + '；处理完成不代表证据充分，研究门槛不代表统计代表性。</p>'
        '<div class="vf-status-foot"><span>需求饱和：' + _escape(saturation_label)
        + '</span><span>正式开发方向：' + development_label + '</span></div></section></div>'
        '<details class="vf-audit"><summary><span>口径与验收详情<small>纳入范围、参考目标与研究边界</small></span>'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4"/></svg></summary>'
        '<div class="vf-audit-body"><div class="vf-audit-grid"><section><h3>计数口径</h3>'
        '<p>不限制留言发布时间；仅分析已保存到本地的数据。不做语义、主题或讨论串去重；不同原始留言分别计数，同一底层留言重复发现时合并。已知作者与作者未公开的声音分别披露。</p>'
        + count_note + sampling_note + '</section><section><h3>证据使用边界</h3>'
        '<p>数量、独立性、场景覆盖和主题稳定分别检查。研究门槛不是统计代表性保证；提及率不能解释为独立消费者比例、市场缺陷率或退货率。</p>'
        '<p>采不到新评论、访问受限或预算耗尽，都不能当作需求饱和。</p><h3>需要补齐的证据</h3>'
        + _list_html(readiness.get("gaps"), limit=30, empty="未记录具体缺口；只有检查明确通过，才能确认达到本轮门槛。")
        + '</section></div><h3>参考目标与验收结果</h3>' + check_html
        + '<div class="vf-audit-caption">' + review_html + '</div>' + batches_html + '</div></details>'
    )


def _render_evidence(analysis: Mapping[str, Any]) -> str:
    readiness = _mapping(analysis.get("evidence_readiness"))
    processing = {
        "complete": "处理完成",
        "completed": "处理完成",
        "pending_review": "存在尚未完成复核的记录",
        "partial": "处理尚未完成",
        "failed": "处理失败",
    }.get(analysis.get("processing_status"), "未提供处理完成记录")
    checks = []
    for raw in _list(readiness.get("checks")):
        item = _mapping(raw)
        label = _first(item, "label", default="证据检查项")
        status = "通过" if item.get("passed") is True else "未通过" if item.get("passed") is False else "尚未检查"
        if _v2_mode(analysis) and item.get("blocking") is False:
            status = "参考目标已达" if item.get("passed") is True else "参考目标未达（不阻断）"
        observed = item.get("observed")
        required = item.get("required")
        # Values can be counts or a short label, never dump nested audit objects.
        public_statuses = {"saturated": "主题稳定条件已达到", "not_saturated": "主题稳定条件未达到"}
        observation = _escape(public_statuses.get(observed, observed)) if isinstance(observed, (str, int, float, bool)) else "见检查说明"
        requirement = _escape(public_statuses.get(required, required)) if isinstance(required, (str, int, float, bool)) else "见研究设置"
        if _v2_mode(analysis) and item.get("blocking") is False and isinstance(observed, (int, float)) and isinstance(required, (int, float)) and required > 0:
            observation += f'（目标进度 {observed / required * 100:.1f}%）'
        if isinstance(item.get("description"), str) and item["description"].strip():
            observation += '<small>' + _escape(item["description"]) + '</small>'
        checks.append(f'<tr><td>{_escape(label)}</td><td>{status}</td><td>{observation}</td><td>{requirement}</td></tr>')
    check_html = (
        '<div class="table-frame"><table><thead><tr><th>检查项</th><th>结果</th><th>实际</th><th>目标 / 验收条件</th></tr></thead><tbody>'
        + "".join(checks) + '</tbody></table></div>'
        if checks else '<p class="empty-state">尚未执行数量、覆盖和独立性检查；处理完成不代表证据充分。</p>'
    )
    saturation = _mapping(readiness.get("saturation"))
    saturation_label = {
        "saturated": "达到本轮主题稳定条件",
        "sufficient": "达到本轮主题稳定条件",
        "stable": "达到本轮主题稳定条件",
        "not_saturated": "需求主题仍在变化",
        "partial": "尚未满足主题稳定条件",
        "insufficient_batches": "合格增量批次不足",
        "not_evaluated": "尚未评估",
    }.get(saturation.get("status"), "尚未评估")
    recent_batches = []
    for index, raw in enumerate(_list(saturation.get("batches"))[-3:], start=1):
        batch = _mapping(raw)
        recent_batches.append(
            f'<tr><td>增量批次 {index}</td><td>{_format_number(batch.get("new_valid_voices"))}</td>'
            f'<td>{_format_number(batch.get("new_topics"))}</td><td>{_format_share(batch.get("new_topic_ratio"))}</td>'
            f'<td>{_format_number(batch.get("stable_top_topics"))}</td><td>{"通过" if batch.get("passed") is True else "未通过"}</td></tr>'
        )
    batches_html = (
        '<details><summary>最近三个增量批次的主题变化</summary><div class="table-frame"><table><thead><tr><th>批次</th><th>新增有效 VOC</th><th>新增主题</th><th>占原主题数</th><th>前十主题保留数</th><th>结果</th></tr></thead><tbody>'
        + ''.join(recent_batches) + '</tbody></table></div></details>' if recent_batches else ''
    )
    needs = []
    for item in _eligible_need_rows(analysis):
        applicable = _mapping(item.get("applicability"))
        related_count = _integer(item.get("related_count", item.get("count", len(set(item.get("support_refs", [])) | set(item.get("counter_refs", []))))))
        total = _integer(_funnel(analysis).get("qualified_consumer_voices"))
        semantic = _need_semantic_summary(analysis, item)
        summary_text = _public_text(semantic.get("summary")) or "本轮尚未导入该需求的模型语义总结；不能将量化计数直接解释为完整消费者动机。"
        statement = _public_text(semantic.get("need_statement")) or "待基于已验证的消费者证据包明确具体任务、障碍、期望结果与使用边界。"
        boundary = (f'当前结构或型号 { _count_entries(applicable.get("current")) } 条 · '
                    f'历史结构或型号 { _count_entries(applicable.get("historical")) } 条 · '
                    f'尚未判断 { _count_entries(applicable.get("unknown")) } 条。') if applicable else "尚未判断型号与结构适用性。"
        needs.append(
            '<details><summary>' + _escape(_item_label(item))
            + (' · 可作为主要依据' if item.get("eligible") is True else ' · 需要继续验证') + '</summary>'
            + f'<p>已知作者 {_count_entries(item.get("known_authors"))} 位 · 独立讨论上下文 {_count_entries(item.get("contexts"))} 个 · 来源渠道 {_count_entries(item.get("channels"))} 个。</p>'
            + '<p>相关声音：' + _format_number(related_count) + ' 条 · ' + _format_share(related_count / total if total else None) + '。</p>'
            + '<section class="need-semantic-summary"><h4>消费者声音语义总结</h4><p>' + _escape(summary_text) + '</p>'
            + '<h4>对应需求的具体描述</h4><p>' + _escape(statement) + '</p>'
            + '<h4>证据使用边界</h4><p>' + _escape(boundary) + '</p>'
            + '<p class="muted">适用性按型号、结构和场景判断；发布日期不决定纳入或权重。完整原声与例外说明保留在审计文件，不在报告正文展开。</p></section></details>'
        )
    coding = _mapping(analysis.get("coding_review"))
    review_html = (
        '<p>编码复核：已由智能体复核 ' + _format_number(coding.get("agent_reviewed"))
        + ' 条；规则初判 ' + _format_number(coding.get("rule_provisional"))
        + ' 条；待复核 ' + _format_number(coding.get("pending")) + ' 条。</p>'
        if coding else ''
    )
    if _holistic_mode(analysis):
        methods = _mapping(coding.get("coding_method_counts"))
        review_html = ('<p>编码方式：规则确定分类 ' + _format_number(methods.get("rule_classified", coding.get("rule_classified")))
                       + ' 条；模型复核 ' + _format_number(methods.get("model_reviewed", coding.get("model_reviewed")))
                       + ' 条；历史智能体复核 ' + _format_number(coding.get("agent_reviewed")) + ' 条。</p>')
        saturation_label += '（仅观察信息，不是停止硬门槛）'
    return (
        '<section class="report-section panel" id="evidence">'
        + _render_front_evidence(analysis, processing=processing, check_html=check_html,
                                 review_html=review_html, saturation_label=saturation_label, batches_html=batches_html)
        + ('<h3>核心需求依据、反证与适用性</h3><div class="need-evidence-grid">' + "".join(needs) + '</div>' if needs else '')
        + '</section>'
    )


def _render_sources(analysis: Mapping[str, Any]) -> str:
    collection = _mapping(analysis.get("collection_summary"))
    mode = _first(collection, "collection_mode", "mode", default="")
    mode_label = {"free": "免费采集", "scrapecreators": "用户自备 ScrapeCreators", "mixed": "免费与用户自备 ScrapeCreators 混合采集", "legacy_unspecified": "历史采集方式未记录"}.get(mode, "未记录采集方式")
    cost = _mapping(_first(collection, "acquisition_budget", "cost", default={}))
    credit_limit = _first(cost, "credits_cap", "credits_limit", default=_first(collection, "credits_limit", "credit_limit", "credits_cap"))
    credits_used = _first(cost, "committed_credits", "credits_used", default=_first(collection, "credits_consumed", "credits_used", "credits_charged"))
    uncertain = _first(cost, "uncertain_credits", default=collection.get("uncertain_credits"))
    cost_usd = _first(cost, "estimated_cost_usd", default=_first(collection, "estimated_cost_usd", "cost_usd"))
    cost_detail = (
        '<p>任务额度上限：' + _format_number(credit_limit) + ' credits；已消耗或保守占用：'
        + _format_number(credits_used) + ' credits；已确认消耗折算：'
        + (f'${_number(cost_usd):,.2f}' if _number(cost_usd) is not None else '尚未记录') + '。</p>'
        + ('<p>其中计费待确认 ' + _format_number(uncertain) + ' credits，仍保守占用预算。</p>' if _number(uncertain) else '')
        + '<p>折算消耗不等于套餐购买金额，也不包含 AI 分析或人工费用；未记录金额不能解释为零费用。</p>'
    )
    if mode == "free":
        cost_html = '<p><strong>本次新增数据接口费用：0。</strong>已有 AI、设备、网络和人工投入另计。免费方式的速度与来源覆盖取决于实际可访问能力。</p>'
        if "acquisition_budget" in collection and _number(credits_used):
            cost_html += '<p>下列为同一任务历史运行与续采累计，不是当前免费模式的新收费。</p>' + cost_detail
    else:
        cost_html = cost_detail
        if "acquisition_budget" in collection:
            cost_html += '<p>额度记录按本任务累计，包含此前运行与续采。</p>'
    kinds = {"social": "社媒讨论", "review": "商品评价", "after_sales": "售后与退货"}
    source_cards = []
    for raw in _list(analysis.get("source_breakdown")):
        item = _mapping(raw)
        label = kinds.get(item.get("source_kind"), "未分类来源")
        platform_count, platform_names = _platform_summary(item.get("platforms"))
        platform_text = '、'.join(platform_names) if platform_names else f'{platform_count} 个渠道'
        source_cards.append(
            '<article class="card"><h3>' + label + '</h3>'
            + '<p><strong>' + _format_number(item.get("count")) + ' 条有效 VOC</strong> · 占本地有效语料 ' + _format_share(item.get("share")) + '</p>'
            + '<p>已知作者 ' + _count_entries(item.get("known_authors")) + ' 位；独立上下文 ' + _count_entries(item.get("contexts")) + ' 个。</p>'
            + '<p>来源：' + _escape(platform_text) + '</p>'
            + _render_ranked('该来源主要主题', item.get("top_topics"), limit=5)
            + '</article>'
        )
    repetition = _mapping(analysis.get("repetition_audit"))
    repetition_html = (
        '<p>重复传播检查：发现 ' + _format_number(repetition.get("duplicate_text_groups")) + ' 组相同文本，涉及 '
        + _format_number(repetition.get("records_in_groups")) + ' 条不同身份留言。原始留言均保留，需结合作者与讨论上下文评估独立性。</p>'
        if repetition else ''
    )
    return (
        '<section class="report-section panel" id="sources">'
        + _section_head("sources-heading", "数据从哪里来", "采集方式、费用与来源构成", "同一留言跨渠道发现只计一次；不同来源的频率不能解释为市场需求比例。")
        + '<h3>' + mode_label + '</h3>' + cost_html
        + ('<div class="three-col">' + "".join(source_cards) + '</div>' if source_cards else '<p class="empty-state">旧语料尚未按社媒、商品评价与售后分层；来源构成尚未评估。</p>')
        + repetition_html
        + '<div class="method-note">地域口径：按目标站点选择相关社区、商品和使用场景。地域未知的相关评论仍可纳入；有效 VOC 不代表已逐一核验国籍或目标市场购买经历。</div>'
        + '</section>'
    )


def _render_brainstorm(analysis: Mapping[str, Any]) -> str:
    concepts = [_mapping(c) for c in _list(analysis.get("product_concepts"))]
    cards = []
    for index, concept in enumerate(concepts, 1):
        row = _report_copy(analysis, concept)
        name = _first(concept, "name", "title", default=f"产品方向{index}")
        actions = '<dl class="br-actions">' + ''.join('<div><dt>' + label + '</dt><dd>' + _escape(row.get(key) or "尚未提供本方向的业务摘要") + '</dd></div>'
                  for key, label in (("operations", "运营先确认"), ("development", "开发先完成"), ("decision", "推进与停止条件"))) + '</dl>'
        cards.append('<article class="br-action-card"><div class="br-action-heading"><h4><a href="#prd-direction-' + str(index) + '">' + f'{index:02d} · ' + _escape(name.split('|')[0].split('｜')[0])
                     + '</a></h4><span>' + _escape(row.get("status") or "研究状态待核对") + '</span></div>' + actions + '</article>')
    return ('<section class="br-review" aria-label="开发评审结论与下一步"><header id="brainstorm-heading"><p class="section-kicker">运营与开发行动清单</p><h3>开发评审结论与下一步</h3>'
            '<p>按各方向的实际研究状态分步推进；打样、用户测试、成本与上市条件分别核验。</p></header><div class="br-action-list">'
            + (''.join(cards) or '<p class="empty-state">尚无正式产品方向，待补齐证据与开发评审。</p>') + '</div></section>')


def _render_semantics(analysis: Mapping[str, Any]) -> str:
    semantic_map = _semantic_map(analysis)
    cards: list[str] = []
    for index, (code, label) in enumerate(SEMANTIC_DEFINITIONS, start=1):
        item = semantic_map.get(code, {})
        count = _integer(_first(item, "count", "voice_count", default=0))
        share = _first(item, "share", "voice_share", default=None)
        authors = _integer(_first(item, "known_authors", "authors", "author_count", default=0))
        author_label = "位已知作者" if "known_authors" in item else "条作者记录（旧口径待复核）"
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
            f'<p class="muted">{_format_number(authors)} {author_label} · {_format_number(threads)} 个讨论 · {_format_number(platforms)} 个平台</p>'
            + (f'<div class="topic-chips">{chips}</div>' if chips else "")
            + '</article>'
        )
    return (
        '<section class="report-section panel" id="semantics">'
        + _section_head(
            "semantics-heading",
            "消费者表达分类",
            "六类消费者表达覆盖",
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
    single = _single_segment_mode(analysis)
    return (
        '<section class="report-section panel" id="category">'
        + _section_head(
            "category-heading",
            "所选细分消费者声音" if single else "全品类消费者声音",
            "需求、满意与不满意",
            "占比以本轮硬身份唯一的有效声音为分母；不同作者在同一讨论中表达同一观点也分别计数。每项同时显示可识别发声者数；作者未公开的声音单列，不冒充为可识别人数。" if single else "占比以本轮硬身份唯一的有效声音为分母；不同作者在同一讨论中表达同一观点也分别计数。每项同时显示可识别发声者数；作者未公开的声音单列，不冒充为可识别人数。",
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
    single = _single_segment_mode(analysis)
    return (
        '<section class="report-section panel" id="segments">'
        + _section_head(
            "segments-heading",
            "已选细分深挖" if single else "机会维度深挖",
            "所选细分的全历史消费者声音" if single else "Top3细分的全历史消费者声音",
            "该细分由用户在上游机会结果中明确选择；所有采集、编码和统计只在该作用域内进行。" if single else "Top3仍沿用机会分析的供需筛选结果；这里只替换消费者声音的统计口径。",
        )
        + ("".join(blocks) if blocks else ('<p class="empty-state">暂无所选细分数据</p>' if single else '<p class="empty-state">暂无Top3细分数据</p>'))
        + '</section>'
    )


def _kano_presentation(value: Any) -> tuple[str, str]:
    token = _normalized_token(value)
    return KANO_PRESENTATION.get(token, ("待验证", "pending"))


def _holistic_mode(analysis: Mapping[str, Any]) -> bool:
    return _mapping(analysis.get("methodology")).get("kano_mode") == "need_holistic_inference"


def _v2_mode(analysis: Mapping[str, Any]) -> bool:
    return analysis.get("business_rules_version") in {"voc-prd-v2", "voc-prd-v2.1", "voc-prd-v2.2", "voc-prd-v2.3"} or _mapping(analysis.get("methodology")).get("prd_version") in {"2.0", "2.1", "2.2", "2.3"}


def _render_holistic_kano(analysis: Mapping[str, Any]) -> str:
    statuses = {"classified": "已分类", "insufficient": "信息不足", "conflict": "证据冲突", "not_applicable": "不适用", "pending": "尚未执行"}
    cards = []
    for item in _list(analysis.get("kano")):
        item = _mapping(item)
        status = item.get("status", "pending")
        if status == "below_threshold":
            continue
        label, css = _kano_presentation(item.get("classification")) if status == "classified" else (statuses.get(status, "尚未执行"), "pending")
        cards.append('<article class="kano-item ' + _escape(css) + '"><div class="kano-head"><h3>'
                     + _escape(_item_label(item)) + '</h3><span class="kano-label">' + _escape(label) + '</span></div>'
                     + '<p>相关声音：' + _format_number(item.get("related_count", item.get("count"))) + ' 条 · ' + _format_share(item.get("related_share", item.get("share"))) + '</p>'
                     + '<p>' + _escape(item.get("rationale") or "尚未完成按需求综合复核") + '</p>'
                     + '<p>适用场景：' + _escape("；".join(map(str, _list(item.get("applicable_scenarios"))))) + '</p>'
                     + _list_html(item.get("validation_questions"), limit=100, empty="未记录追加验证问题") + '</article>')
    return '<section class="report-section panel" id="kano">' + _section_head(
        "kano-heading", "需求属性", "消费者声音推断型 KANO", "按需求综合判断，保留信息不足、冲突与尚未执行状态；不作逐声投票，不代表正式配对问卷。") + '<div class="kano-grid">' + ''.join(cards) + '</div></section>'


def _render_kano(analysis: Mapping[str, Any]) -> str:
    if _holistic_mode(analysis):
        return _render_holistic_kano(analysis)
    items = _list(analysis.get("kano"))
    if "kano" not in analysis:
        items = _list(_category_summary(analysis).get("kano"))
    # Historical analysis may contain one row per need/type. Collapse it on
    # read without pretending missing related totals are known.
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for raw in items:
        if isinstance(raw, Mapping):
            groups.setdefault(str(raw.get("need_code") or _item_label(raw)), []).append(raw)
    selected = []
    for rows in groups.values():
        best = max(_item_count(row) for row in rows)
        winners = [row for row in rows if _item_count(row) == best]
        if len(winners) == 1:
            selected.append(winners[0])
    selected.sort(key=lambda row: (-_integer(row.get("related_count", _item_count(row))), _item_label(row)))
    cards: list[str] = []
    for raw in selected[:20]:
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
        if rationale == "需通过原型测试和正式问卷继续验证。" and isinstance(item.get("rationales"), list):
            rationale = "；".join(str(x) for x in item["rationales"][:3]) or rationale
        if "related_count" in item and "classified_count" in item:
            counts_html = (
                '<strong>相关声音：' + _format_number(item["related_count"]) + ' 条 · 占全部有效VOC '
                + _format_share(item.get("related_share")) + '</strong><br>'
                + '<span>主导类型依据：' + _format_number(count) + ' 条 / 可分类 '
                + _format_number(item["classified_count"]) + ' 条 · 占比 '
                + _format_share(item.get("dominant_share")) + '</span>'
            )
        else:
            counts_html = f'<strong>分类支持：{_format_number(count)} 条 · 占全部有效VOC {_format_share(share)}</strong>'
        cards.append(
            f'<article class="kano-item {_escape(css_class)}"><div class="kano-head">'
            f'<h3>{_escape(label)}</h3><span class="kano-label">{_escape(kano_label)}</span></div>'
            f'<div class="insight-meta">{counts_html}</div>'
            f'<p><strong>产品含义：</strong>{_escape(rationale)}</p></article>'
        )
    return (
        '<section class="report-section panel" id="kano">'
        + _section_head(
            "kano-heading",
            "需求属性",
            "消费者声音推断型 KANO",
            "同一需求只保留可分类声音中数量最多的类型；并列暂不定型。相关总量与分类支持量分别统计，不能替代正式双向问卷。"
            + (f"本节展示相关声音最多的20项，共{len(selected)}项有主导类型。" if len(selected) > 20 else ""),
        )
        + ('<div class="kano-grid">' + "".join(cards) + '</div>' if cards else '<p class="empty-state">暂无可展示的需求属性判断</p>')
        + '</section>'
    )


def _render_innovations(analysis: Mapping[str, Any]) -> str:
    tracks = _mapping(analysis.get("opportunity_tracks"))
    streams = (
        ("具体新需求与绕行方案", _list(tracks.get("specific_new_needs", analysis.get("new_needs"))), "用户主动提出的具体诉求、替代做法、DIY或改装机制；不借用宽泛需求的频次。"),
        ("现有需求的改进机会", _list(tracks.get("established_need_improvements")), "已有需求中的明确缺陷、使用限制与可改进环节；并非宣称市场空白。"),
    )
    stream_html: list[str] = []
    for heading, items, description in streams:
        cards: list[str] = []
        for raw in items:
            item = raw if isinstance(raw, Mapping) else {"label": raw}
            if (_v2_mode(analysis)
                    and (_item_share(item) is None or _item_share(item) < 0.005)):
                continue
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
        empty = ('本次没有达到 0.5% 且具当前适用依据的具体新需求；低频候选只保留在审计文件。'
                 if heading == "具体新需求与绕行方案" else "暂无达到 0.5% 且具当前适用依据的既有需求改进机会。")
        stream_html.append('<div class="innovation-track"><h3>' + _escape(heading) + '</h3><p class="muted">' + _escape(description) + '</p>' + (('<div class="innovation-list">' + ''.join(cards) + '</div>') if cards else '<p class="empty-state">' + _escape(empty) + '</p>') + '</div>')
    return (
        '<section class="report-section panel" id="innovation">'
        + _section_head(
            "innovation-heading",
            "未满足需求",
            "双轨产品机会",
            "消费者明确创意、DIY绕行和重复痛点推导分开解释；产品团队创意不冒充消费者留言。",
        )
        + ''.join(stream_html)
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


def _concept_images(
    analysis: Mapping[str, Any],
    concept: Mapping[str, Any],
    *,
    analysis_dir: Path,
    overrides: Mapping[str, Path],
) -> list[tuple[str, str, str]]:
    """Load the v2.1 three-image asset set, retaining the legacy single-image path."""
    concept_id = str(_first(concept, "concept_id", "id", default=""))
    assets = _mapping(analysis.get("concept_image_assets"))
    declared_assets = _list(assets.get(concept_id))
    images: list[tuple[str, str, str]] = []
    for raw in declared_assets:
        item = _mapping(raw)
        raw_path = _first(item, "path", default="")
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = analysis_dir / path
        path = path.resolve()
        if not path.is_file():
            raise ReportError(f"概念图资产不存在：{path}")
        data_uri, _mime, digest = _image_data_uri(path)
        expected = str(_first(item, "sha256", default="")).strip().casefold()
        if expected and expected != digest:
            raise ReportError(f"概念图SHA-256不一致：{path.name}")
        images.append((_public_text(_first(item, "role_label", "role", default="产品概念示意")), data_uri, digest))
    if images:
        return images
    uri, digest = _concept_image(concept, analysis_dir=analysis_dir, overrides=overrides)
    return [("产品概念示意", uri, digest)] if uri and digest else []


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
    colors = _list(_first(value, "colors", "color", default=[]))
    finishes = _list(_first(value, "finishes", "finish", default=[]))
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


PRESENTATION_SCHEMA = "consumer-report-presentation-1.0"
REPORT_ACTION_FIELDS = ("status", "operations", "development", "decision")
REPORT_BENCHMARK_FIELDS = ("existing", "proposal", "value", "tradeoff", "test", "stop", "boundary")


def _competition_row(analysis: Mapping[str, Any], concept: Mapping[str, Any]) -> Mapping[str, Any]:
    cid = str(_first(concept, "concept_id", "id", default=""))
    return next((_mapping(row) for row in _list(_mapping(analysis.get("competition_audit")).get("concepts"))
                 if str(_mapping(row).get("concept_id", "")) == cid), {})


def _presentation_source_sha256(analysis: Mapping[str, Any], concept: Mapping[str, Any]) -> str:
    data = {"concept": concept, "competition": _competition_row(analysis, concept)}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_report_copy(analysis: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for concept in _list(analysis.get("product_concepts")):
        concept = _mapping(concept)
        rows.append({"concept_id": str(_first(concept, "concept_id", "id", default="")),
                     "source_sha256": _presentation_source_sha256(analysis, concept),
                     **{key: "" for key in REPORT_ACTION_FIELDS},
                     "benchmark": {key: "" for key in REPORT_BENCHMARK_FIELDS}, "mechanism_labels": {}})
    return {"schema_version": PRESENTATION_SCHEMA, "review_version": "", "product_directions": rows}


def import_report_copy(analysis: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    if (payload.get("schema_version") != PRESENTATION_SCHEMA
            or not isinstance(payload.get("review_version"), str) or not payload["review_version"].strip()
            or not isinstance(payload.get("product_directions"), list)):
        raise ReportError("报告展示摘要缺少 schema_version 或 review_version")
    concepts = {str(_first(_mapping(c), "concept_id", "id", default="")): _mapping(c) for c in _list(analysis.get("product_concepts"))}
    rows = _list(payload.get("product_directions"))
    seen = set()
    for raw in rows:
        row = _mapping(raw); cid = str(row.get("concept_id", ""))
        if not cid or cid not in concepts or cid in seen:
            raise ReportError("报告展示摘要包含缺失、重复或非当前产品方向")
        seen.add(cid)
        if row.get("source_sha256") != _presentation_source_sha256(analysis, concepts[cid]):
            raise ReportError("报告展示摘要的产品或竞品快照已变化")
        for block, fields in ((row, REPORT_ACTION_FIELDS), (_mapping(row.get("benchmark")), REPORT_BENCHMARK_FIELDS)):
            for key in fields:
                value = block.get(key)
                if not isinstance(value, str) or not value.strip() or len(value) > 220:
                    raise ReportError("报告展示摘要 %s 必须为1至220字的短文" % key)
                if re.search(r"(?:agent_id|product_architect|runtime_receipt|phase[0-9]|已记录完成|\broot\b)", value, re.I):
                    raise ReportError("报告展示摘要不得展示智能体或运行过程术语")
        if not isinstance(row.get("mechanism_labels"), Mapping):
            raise ReportError("报告展示摘要必须提供候选机制展示别名表")
        for key, value in row["mechanism_labels"].items():
            if not isinstance(value, str) or not value.strip() or len(value) > 80:
                raise ReportError("候选机制展示别名必须是简短业务名称")
        for key in ("benchmark_name", "benchmark_title"):
            if key in row and (not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 80):
                raise ReportError("竞品展示名称和标题必须为1至80字")
    if seen != set(concepts):
        raise ReportError("报告展示摘要必须完整覆盖正式产品方向")
    result = copy.deepcopy(dict(analysis))
    result["report_presentation"] = copy.deepcopy(dict(payload))
    return result


def _report_copy(analysis: Mapping[str, Any], concept: Mapping[str, Any]) -> Mapping[str, Any]:
    cid = str(_first(concept, "concept_id", "id", default=""))
    return next((_mapping(row) for row in _list(_mapping(analysis.get("report_presentation")).get("product_directions"))
                 if str(_mapping(row).get("concept_id", "")) == cid), {})


def _record_cards(records: Iterable[Sequence[tuple[str, Any]]]) -> str:
    cards = []
    for fields in records:
        cards.append('<article class="prd-record"><dl class="prd-record-fields">' + ''.join(
            '<div class="prd-record-field"><dt>' + _escape(label) + '</dt><dd>' + _escape(value)
            + '</dd></div>' for label, value in fields) + '</dl></article>')
    return '<div class="prd-record-list">' + ''.join(cards) + '</div>'


def _disclosure(title: str, body: str, extra: str = "") -> str:
    return ('<details class="prd-details' + (' ' + extra if extra else '') + '"><summary>'
            + _escape(title) + '</summary><div class="prd-disclosure-body">' + body + '</div></details>')


def _render_v22_moscow(concept: Mapping[str, Any]) -> str:
    scopes = _mapping(concept.get("moscow_versions"))
    if not scopes:
        return _render_moscow(concept)
    blocks = []
    for key, title in (("research_prototype", "研究与打样版"), ("provisional_v1", "暂定上市 V1")):
        scope = _mapping(scopes.get(key))
        records = []
        for raw in _list(scope.get("items")):
            item = _mapping(raw)
            records.append((("优先级", _first(item, "priority", default="待定")),
                            ("范围项", _first(item, "description", default="待定义")),
                            ("不做的后果", _first(item, "not_doing_consequence", default="待定义")),
                            ("验收标准", _first(item, "acceptance_criteria", default="待定义"))))
        blocks.append('<article class="prd-version"><h4>' + _escape(title) + '</h4><p>'
                      + _escape(scope.get("version_goal") or "待定义版本目标") + '</p>'
                      + (_record_cards(records) if records else '<p class="empty-state">尚无范围项</p>') + '</article>')
    return '<div class="prd-version-list">' + ''.join(blocks) + '</div>'


def _render_decision_chain(concept: Mapping[str, Any], analysis: Mapping[str, Any] | None = None) -> str:
    analysis = analysis or {}
    names = {str(row.get("code") or row.get("need_id")): _item_label(row)
             for row in _list(_mapping(analysis.get("evidence_readiness")).get("needs")) if isinstance(row, Mapping)}
    mechanisms = _mapping(_report_copy(analysis, concept).get("mechanism_labels"))
    records = []
    for raw in _list(concept.get("design_decision_chain")):
        item = _mapping(raw)
        if not item: continue
        need = str(item.get("need_id") or "")
        kano = str(item.get("kano_type") or "")
        mechanism = str(item.get("candidate_mechanism") or "")
        # Display labels come from this run; machine identifiers stay in the audit.
        mechanism_label = mechanisms.get(mechanism) or item.get("candidate_mechanism_label")
        if not mechanism_label:
            mechanism_label = mechanism if not re.fullmatch(r"[a-z0-9_]+", mechanism) else "候选机制业务名称待补充"
        decision = _first(item, "adopt_or_reject", "decision", default="待决")
        decisions = {"adopt_research_hypothesis_only": "纳入研究，效果待验证", "adopt": "纳入方案", "reject": "不采用"}
        records.append((("需求", names.get(need) or item.get("need_label") or "需求展示名称待补充"),
                        ("KANO", (_kano_presentation(kano)[0] + '（' + kano.upper() + '）') if kano else "待判断"),
                        ("设计策略", item.get("kano_strategy") or "待定义"),
                        ("候选机制", mechanism_label), ("采用/淘汰", decisions.get(str(decision), decision))))
    return '<p class="muted">KANO 为消费者声音推断，作用于设计策略和版本取舍，不等同正式配对问卷。</p>' + (_record_cards(records) if records else '<p class="empty-state">尚无设计决策链</p>')


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
        raw = process.get(key)
        item = _mapping(raw)
        if isinstance(raw, str) and raw.strip():
            outputs = [raw.strip()]
            status = {
                "empathize": "证据研究已执行",
                "define": "问题定义已执行",
                "ideate": "工作坊构思已执行",
                "prototype": "视觉概念待生成；实物样机尚未执行",
                "test": "测试计划已定义，尚未执行",
                "iteration": "评审修订已完成；测试后迭代待执行",
            }[key]
            gate = ""
        else:
            outputs = _list(_first(item, "outputs", "output", "evidence", default=[]))
            if not outputs and isinstance(_first(item, "output", default=""), str):
                outputs = [_first(item, "output", default="")]
            status = _public_text(_first(item, "status", default=""))
            status = {"research_completed": "已完成消费者研究", "defined": "已定义问题",
                      "workshop_completed": "已完成方案评审", "prototype_planned": "待制作原型",
                      "planned": "待执行测试", "not_executed": "尚未开展"}.get(status, status)
            basis = _public_text(_first(item, "basis", "evidence_basis", default=""))
            next_validation = _public_text(_first(item, "next_validation", "next_step", default=""))
            gate = _first(item, "success_or_decision_gate", "decision_gate", "gate", default="")
        if isinstance(raw, str) and raw.strip():
            basis = "冻结的消费者证据、需求判断与工作坊记录"
            next_validation = "按该阶段记录继续验证"
        cards.append(
            '<article class="process-step">'
            f'<span>{index}</span><h4>{_escape(label)}</h4>'
            + (f'<p class="muted">{_escape(status)}</p>' if status else "")
            + _list_html(outputs, limit=5, empty="尚无已执行产出")
            + (f'<small>依据：{_escape(basis)}</small>' if basis else "")
            + (f'<small>下一步：{_escape(next_validation)}</small>' if next_validation else "")
            + (f'<small>决策门槛：{_escape(gate)}</small>' if gate else "")
            + '</article>'
        )
    return '<div class="process-grid">' + "".join(cards) + '</div>'


def _acceptance_table(concept: Mapping[str, Any]) -> str:
    records = []
    for raw in _list(concept.get("acceptance_metrics")):
        item = raw if isinstance(raw, Mapping) else {"metric": raw}
        records.append((("验收项", _first(item, "metric", "name", default="验收项")),
                        ("目标", _first(item, "target", "acceptance_criteria", default="待定义")),
                        ("测试方法", _first(item, "test_method", "method", default="待定义")),
                        ("测试对象", _first(item, "test_subjects", "test_object", "test_subject", default="待定义")),
                        ("失败条件", _first(item, "failure_condition", "failure_criteria", default="待定义"))))
    return ('<p>以下为计划中的测试与通过标准，未声明已完成实际验证。</p>'
            + (_record_cards(records) if records else '<p class="empty-state">尚未定义量化验收指标</p>'))


def _prompt_text(concept: Mapping[str, Any]) -> str:
    value = concept.get("image_prompt")
    if isinstance(value, Mapping):
        return _public_text(_first(value, "prompt_text", "prompt", default=""))
    return _public_text(value)


def _feature_evidence(concept: Mapping[str, Any]) -> str:
    labels = {
        "consumer_explicit": "消费者直接提出",
        "evidence_inference": "根据证据推导",
        "design_hypothesis": "尚待验证的创意",
    }
    cards = []
    for raw in _list(concept.get("feature_evidence")):
        item = _mapping(raw)
        if not item:
            continue
        cards.append(
            '<article class="card"><h4>' + _escape(_first(item, "feature", default="功能建议")) + '</h4>'
            + '<p><strong>' + labels.get(item.get("origin"), "依据尚未标注") + '</strong></p>'
            + '<p>依据：' + _escape(_first(item, "reasoning", default="尚未说明")) + '</p>'
            + '<p>验证计划：' + _escape(_first(item, "validation_plan", default="尚未定义")) + '</p>'
            + '</article>'
        )
    return (
        ('<div class="prd-evidence-list">' + ''.join(cards) + '</div>' if cards else '<p class="warning">尚未建立逐项功能依据；不能将设计构想解释为消费者直接提出的要求。</p>')
    )


def _render_concepts(
    analysis: Mapping[str, Any], *, analysis_dir: Path,
    image_overrides: Mapping[str, Path], exploratory: bool = False,
) -> tuple[str, int, dict[str, str]]:
    concepts = [item for item in _list(analysis.get("exploration_concepts" if exploratory else "product_concepts")) if isinstance(item, Mapping)]
    if exploratory and not concepts: return "", 0, {}
    segment_names = {str(_first(item, "segment_id", "id", default=f"rank-{index}")):
                     _public_text(_first(item, "feature", "name", "label", default=f"Top{index}细分"))
                     for index, item in enumerate(_segments(analysis), 1)}
    blocks, links = [], []
    embedded_count, image_digests = 0, {}
    for index, concept in enumerate(concepts, 1):
        cid = str(_first(concept, "concept_id", "id", default=f"concept_{index}"))
        name = _public_text(_first(concept, "name", "title", default=f"产品方向{index}"))
        segment_name = segment_names.get(str(concept.get("segment_id", "")), "细分归属待复核")
        anchor = f'{"explore" if exploratory else "prd"}-direction-{index}'
        links.append('<a href="#' + anchor + '">' + f'{index:02d}  ' + _escape(name.split('|')[0].split('｜')[0]) + '</a>')
        images = _concept_images(analysis, concept, analysis_dir=analysis_dir, overrides=image_overrides)
        embedded_count += len(images)
        image_digests.update({f"{cid}:{role}": digest for role, _uri, digest in images})
        figures = ['<figure class="concept-figure"><img src="' + uri + '" alt="' + _escape(name) + ' · ' + _escape(role)
                   + '" width="1536" height="1024" loading="lazy" decoding="async"><figcaption>' + _escape(role)
                   + ' · ' + IMAGE_DISCLAIMER + '</figcaption></figure>' for role, uri, _digest in images]
        figure = figures[0] if figures else '<div class="empty-state">概念图尚未提供；请结合已有产品定义与验证计划评估。</div>'
        gallery = _disclosure(f'展开关键结构与研究场景 · {len(figures)-1} 张概念图', '<div class="prd-secondary-gallery">' + ''.join(figures[1:]) + '</div>') if len(figures) > 1 else ''
        consumers = _list(_first(concept, "target_consumers", "personas", default=[]))
        scenarios = _list(_first(concept, "use_scenarios", "scenarios", default=[]))
        bom_estimate = _mapping(concept.get("bom_estimate"))
        bom = _price_text(bom_estimate) if bom_estimate else _public_text(_first(concept, "bom_assumption", "bom", default=""))
        bom_basis = "声明为附来源的供应商报价；仍需核对规格、数量与报价适用条件。" if bom_estimate.get("basis") == "supplier_quote" else "成本为工程估算假设，未经供应商报价确认。"
        contexts = '<dl class="prd-context-list">' + ''.join('<div><dt>' + label + '</dt><dd>' + _escape('、'.join(_public_text(x) for x in values) or "待细化") + '</dd></div>'
                     for label, values in (("目标消费者", consumers), ("使用场景", scenarios))) + '</dl>'
        costs = '<div class="prd-cost-strip"><dl class="prd-cost-facts">' + ''.join('<div><dt>' + label + '</dt><dd>' + _escape(value or "待验证") + '</dd></div>'
                  for label, value in (("目标价格", _price_text(_first(concept, "target_price", "price", default=""))), ("BOM假设", bom))) + '</dl><p>' + bom_basis + '</p></div>'
        structure = '<article><h3>结构、材料与外观</h3>' + ''.join('<p><strong>' + label + '：</strong>' + _escape(value) + '</p>'
                    for label, value in (("结构", _first(concept, "structure", "structural_solution", default="待工程定义")),
                                         ("材料", '、'.join(_public_text(x) for x in _list(concept.get("materials"))) or "待工程定义"),
                                         ("颜色与表面", _cmf_text(_first(concept, "cmf", "appearance", default="")) or "待视觉定义"))) + '</article>'
        boundaries = '<div class="prd-boundaries">' + ''.join('<article class="card"><h3>' + title + '</h3>' + _list_html(concept.get(key), limit=8) + '</article>' for title, key in (("风险", "risks"), ("依赖", "dependencies"))) + '</div>'
        blocks.append(
            '<article class="concept-card prd-reading-card" id="' + anchor + '" data-concept-id="' + _escape(cid) + '">'
            '<header class="concept-header prd-header"><span class="prd-number" aria-hidden="true">' + f'{index:02d}' + '</span><div><p class="section-kicker">'
            + ("探索方向" if exploratory else "正式推荐方向") + f' {index} · ' + _escape(segment_name) + '</p><h3>' + _escape(name)
            + '</h3></div><span class="segment-badge">' + ("尚待验证" if exploratory else _escape(segment_name)) + '</span></header>'
            '<div class="prd-overview"><div class="prd-task"><h4>用户任务（JTBD）</h4><p>' + _escape(concept.get("jtbd") or "待补充用户任务") + '</p></div>'
            + contexts + costs + '</div>' + figure + gallery
            + '<article class="prd-technical"><h3>功能与技术方案</h3><h4>核心功能</h4>' + _list_html(_first(concept, "features", "functions", default=[]), limit=10)
            + '<h4>技术方案</h4><p>' + _escape(_first(concept, "technical_solution", "technology", default="待工程定义")) + '</p></article>'
            + boundaries + _render_release_gates(concept)
            + '<div class="prd-reading-guide"><h4>开发详情</h4><p>按需展开以下内容；风险、依赖与研究范围保留在上方。</p></div>'
            + _disclosure("结构、材料与外观", structure)
            + _disclosure("BOM 估算前提", _list_html(bom_estimate.get("assumptions"), limit=12, empty="尚未提供成本估算前提"))
            + _disclosure("功能与消费者证据的关系", _feature_evidence(concept), "prd-evidence-two")
            + _disclosure("需求 → KANO → 机制的设计决策链", _render_decision_chain(concept, analysis), "prd-decision-two")
            + _disclosure("MoSCoW：研究打样版与暂定上市 V1", _render_v22_moscow(concept))
            + _disclosure("量化验收指标", _acceptance_table(concept))
            + '<details class="concept-process prd-details prd-process prd-two-column"><summary>查看设计思维过程</summary><p class="process-intro">每一步均区分已完成的研究产出、依据与下一项验证；视觉概念不等于实体样机，测试计划不等于已完成用户测试。</p>' + _design_process(concept) + '</details>'
            + '<p class="muted">三张概念图仅转译本方向冻结的产品定义；完整提示词与图片哈希保留在审计文件。</p>'
            + ('' if exploratory else _render_direction_benchmark(analysis, concept, index)) + '</article>'
        )
    if exploratory:
        heading = _section_head("exploration-heading", "创意保留", "探索性创意:尚待验证", "保留低频、新颖及历史构想，不能作为已验证的开发结论。")
    else:
        description = ("完整交付须恰好三个通过评审的打样验证方向；结构、成本和性能仍须实物验证，不代表已获量产放行。"
                       if _v2_mode(analysis) else "最多三个方向；缺少主要证据时允许零推荐，避免强行立项。")
        heading = ('<div class="section-head" id="concepts-heading"><div><p class="section-kicker">产品定义</p><h2>'
                   '<span class="prd-title-line">产品机会与开发</span><span class="prd-title-line prd-title-line-with-count"><span>正式推荐产品方向</span>'
                   '<span class="prd-title-count">（' + str(len(concepts)) + ' 个）</span></span></h2></div>'
                   '<p>' + description + '</p></div>')
    nav = '<nav class="prd-direction-nav" aria-label="产品方向快速跳转">' + ''.join(links) + '</nav>' if links else ''
    section = '<section class="report-section panel" id="' + ('exploration' if exploratory else 'concepts') + '">' + heading + nav + (''.join(blocks) or '<p class="empty-state">尚未形成正式推荐产品方向。</p>') + '</section>'
    return section, embedded_count, image_digests


def _render_release_gates(concept: Mapping[str, Any]) -> str:
    gates = _mapping(concept.get("release_gates"))
    if not gates:
        return ""
    materials = _mapping(gates.get("materials_compliance"))
    rows = [("用户测试前的工程门", gates.get("engineering_before_human")),
            ("材料与销售合规", materials.get("release")),
            ("包装运输", gates.get("packaging")),
            ("成本与购买选择", gates.get("commercial"))]
    return ('<details><summary>查看打样、用户测试与商业放行条件（尚未执行）</summary>'
            + '<dl class="facts">' + ''.join('<dt>' + label + '</dt><dd>' + _escape(_public_text(value)) + '</dd>'
                for label, value in rows if value) + '</dl></details>')


def _render_direction_benchmark(analysis: Mapping[str, Any], concept: Mapping[str, Any], index: int) -> str:
    row = _competition_row(analysis, concept)
    benchmark = _mapping(concept.get("benchmark_reference")) or _mapping(row.get("benchmark"))
    presentation = _report_copy(analysis, concept)
    summary = _mapping(presentation.get("benchmark"))
    cid = str(_first(concept, "concept_id", "id", default=""))
    asin = str(benchmark.get("asin") or "")
    url = str(benchmark.get("product_url") or "")
    link = ('<a href="' + _escape(url) + '" target="_blank" rel="noopener noreferrer">查看商品 · ' + _escape(asin) + '</a>') if url.startswith("https://") else '<span>商品链接待核验</span>'
    name = presentation.get("benchmark_name") or (str(benchmark.get("brand") or asin or "主对标待确认") + " · 主对标商品")
    pool = _mapping(_mapping(analysis.get("competition_audit")).get("product_pool")).get("product_count")
    currency = str(benchmark.get("currency") or _mapping(analysis.get("project")).get("currency") or "USD")
    symbol = "$" if currency == "USD" else currency + " "
    price = _number(benchmark.get("price"))
    metrics = (("价格快照", symbol + f"{price:,.2f}" if price is not None else "—"),
               ("子体销量", _format_number(benchmark.get("sales"))),
               ("子体销售额", (symbol + _format_number(benchmark.get("child_revenue"))) if _number(benchmark.get("child_revenue")) is not None else "—"),
               ("样本内销量排名", _format_number(benchmark.get("sales_rank")) + ' / ' + _format_number(pool)))
    tiles = '<dl class="br-metrics">' + ''.join('<div class="br-metric"><dt>' + label + '</dt><dd>' + _escape(value) + '</dd></div>' for label, value in metrics) + '</dl>'
    labels = (("existing", "竞品已确认"), ("proposal", "本方向拟增加"), ("value", "希望改善什么"), ("tradeoff", "新增投入与取舍"), ("test", "首轮怎么验证"), ("stop", "什么情况停止"))
    cards = '<div class="br-compare-grid">' + ''.join('<article class="br-compare-item' + (' br-proposal' if key == 'proposal' else '') + '"><h5>' + label + '</h5><p>' + _escape(summary.get(key) or "本项短摘要尚未提供，请先核对冻结产品定义与竞品证据。") + '</p></article>' for key, label in labels) + '</div>'
    period = benchmark.get("verified_original_sales_period") or benchmark.get("sales_period") or "统计期未记录"
    return ('<section class="br-benchmark" data-concept-id="' + _escape(cid) + '" aria-label="本方向的竞品对标"><header class="br-heading" id="'
            + ('competition-audit-heading' if index == 1 else f'competition-direction-{index}') + '"><h4>' + _escape(presentation.get("benchmark_title") or "本方向的竞品对标") + '</h4><span class="br-badge">差异效果待验证</span></header>'
            + '<div class="br-product"><strong>' + _escape(name) + '</strong>' + link + '</div><p class="br-scope">' + _escape(period) + '；以下为冻结子体数据的历史快照。</p>'
            + tiles + cards + '<p class="br-boundary">' + _escape(summary.get("boundary") or "未知能力不作缺失；竞品声明不等于已通过实物测试。") + '</p>'
            + '<details class="br-method"><summary>查看对标选择依据</summary><p>' + _escape(benchmark.get("selection_rationale") or "筛选依据未提供")
            + ' 基础特征重叠不证明升级效果；不同方向可以选中同一主对标。</p></details></section>')


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
        marker = (str(item.get("voice_id") or item.get("record_id") or len(result)) if _holistic_mode(analysis)
                  else _normalized_token(platform + "|" + excerpt))
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
        source_url = str(item.get("source_url") or item.get("url") or "")
        source_link = ('<p><a href="' + _escape(source_url) + '" target="_blank" rel="noopener noreferrer">查看原始来源</a></p>'
                       if _holistic_mode(analysis) and re.match(r"^https://[^\s<>\"']+$", source_url) else '')
        cards.append(
            '<article class="voice-item">'
            f'<div class="voice-meta">{_escape(platform)}{(" · " + _escape(semantic)) if semantic else ""}</div>'
            f'<blockquote>{_escape(excerpt)}</blockquote>'
            + (f'<p><strong>中文摘要：</strong>{_escape(summary)}</p>' if summary else "")
            + ('<p>记录 ID：' + _escape(item.get("voice_id") or item.get("record_id") or "未提供") + '</p>' if _holistic_mode(analysis) else '')
            + source_link
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
        "计数规则：不做语义、主题或讨论串去重；不同作者的相同观点分别计为有效声音。可识别发声者按作者去重，作者未公开的记录单列。",
        "多标签规则：同一留言可以同时进入多个需求或语义统计，因此各项占比不可相加",
        "全历史定义：对本地已经抓取并保存的语料做全量处理，不等于互联网或平台的全部历史留言",
        f"执行方式：{'完全离线，未发起新的网络采集' if no_network is not False else '基于既有本地数据重算'}",
    )
    if _holistic_mode(analysis):
        method_items = tuple("社媒纳入：保留相关评论、原创提问/分享及非推广第一人称体验视频；推广性质或产品语境有冲突时小批复核。" if item.startswith("YouTube清洗：") else item for item in method_items)
    return (
        '<section class="report-section panel" id="method">'
        + _section_head(
            "method-heading",
            "研究透明度",
            "方法与限制",
            "说明本轮如何从本地记录得到消费者需求，及结论不能覆盖的边界。",
        )
        + '<div class="method-note"><strong>本报告生成阶段没有重新抓取数据。</strong>分析由已保存的本地数据库离线清洗与重算，采集方式与消耗另见前文。</div>'
        + '<ul>' + "".join(f'<li>{_escape(item)}</li>' for item in method_items) + '</ul>'
        + _render_sample_structure(analysis)
        + ('<div class="three-col">' + "".join(limitations) + '</div>' if limitations else "")
        + '</section>'
    )


def _inline_section(section: str) -> str:
    """Use a former top-level panel inside its prescribed parent section."""
    match = re.fullmatch(r"<section\b[^>]*>(.*)</section>", section, flags=re.DOTALL)
    if not match:
        raise ReportError("内部报告片段不是完整 section")
    # The caller owns the only first-level section.  Embedded material keeps
    # its wording and cards, but its former h2 becomes a local h3.
    return re.sub(r"<(\/?)h2\b", r"<\1h3", match.group(1))


def _append_to_section(section: str, fragment: str) -> str:
    if not fragment:
        return section
    if not section.endswith("</section>"):
        raise ReportError("内部报告片段缺少 section 结束标签")
    return section[:-10] + fragment + "</section>"


def _insight_objects(insights: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    value = insights.get("json")
    return value if isinstance(value, Mapping) else {}


def _insight_rows(insights: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    streams = insights.get("jsonl")
    value = streams.get(name, []) if isinstance(streams, Mapping) else []
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _render_research_signals(insights: Mapping[str, Any]) -> tuple[str, str]:
    objects = _insight_objects(insights)
    links = objects.get("need_evidence_links.json", {})
    needs = links.get("needs", []) if isinstance(links, Mapping) else []
    alexa_refs = 0
    if isinstance(needs, list):
        for need in needs:
            counts = _mapping(_mapping(need).get("research_signal_counts"))
            alexa_refs += _integer(counts.get("alexa_refs"))
    plan = objects.get("active_question_plan.json", {})
    questions = plan.get("questions", []) if isinstance(plan, Mapping) else []
    ledger = _insight_rows(insights, "active_qa_ledger.jsonl")
    states: dict[str, str] = {}
    for event in ledger:
        question_id = _public_text(event.get("question_id"))
        state = _public_text(event.get("state"))
        if question_id and state:
            states[question_id] = state
    total = len(questions) if isinstance(questions, list) else 0
    completed = sum(1 for state in states.values() if state == "completed")
    pending = max(total - completed, 0)
    catalog = _mapping(objects.get("recommended_qa.json"))
    catalog_summary = _mapping(catalog.get("summary"))
    returned_questions = _integer(catalog_summary.get("returned_question_records"))
    answered_questions = _integer(catalog_summary.get("answered_question_records"))
    keyword_queries = _integer(catalog_summary.get("keyword_query_count"))
    product_asins = _integer(catalog_summary.get("product_asin_count"))
    product_pages = _integer(catalog_summary.get("product_page_count"))
    raw_gaps = catalog_summary.get("gaps", [])
    catalog_gaps = [
        _public_text(item)
        for item in raw_gaps
        if _public_text(item)
    ] if isinstance(raw_gaps, list) else []
    catalog_note = ""
    if returned_questions:
        catalog_note = (
            f'Flyfus 已保存 {_format_number(returned_questions)} 条返回问答，其中 '
            f'{_format_number(answered_questions)} 条附带回答；'
            f'覆盖 {_format_number(keyword_queries)} 个关键词、'
            f'{_format_number(product_asins)} 个商品 ASIN / {_format_number(product_pages)} 页。'
        )
    signal = (
        '<div class="method-note"><strong>Alexa/Rufus 研究线索：</strong>'
        + catalog_note
        + (f'已关联 {_format_number(alexa_refs)} 条线索；' if alexa_refs else '本次未提供已关联线索；')
        + f'问题计划 {_format_number(total)} 项，已确认完成 {_format_number(completed)} 项。'
        + '该类线索只用于事实核验与假设，不计入 VOC、消费者人数、KANO 或来源渠道数量。</div>'
    )
    rows = []
    for raw in (questions if isinstance(questions, list) else [])[:6]:
        question = _mapping(raw)
        question_id = _public_text(question.get("question_id"))
        status = states.get(question_id, "待执行")
        rows.append(
            '<li><strong>' + _escape(_public_text(question.get("development_decision")) or "待决策") + '</strong>：'
            + _escape(_public_text(question.get("expected_verification")) or "待确认")
            + '（' + _escape(status) + '）</li>'
        )
    validation = (
        '<div class="subsection"><h3>Alexa/Rufus 待验证事项</h3>' + signal
        + ('<ul>' + ''.join(rows) + '</ul>' if rows else '<p>未执行 Alexa/Rufus 问答，保留为后续研究线索。</p>')
        + ('<p>仍待确认事项：' + _format_number(pending) + ' 项。</p>' if total else '')
        + (
            '<p><strong>问答覆盖边界：</strong>'
            + '；'.join(_escape(item) for item in catalog_gaps)
            + '。</p>'
            if catalog_gaps else ''
        )
        + '</div>'
    )
    return signal, validation


def _render_flyfus_cost(insights: Mapping[str, Any]) -> str:
    receipts = [row for row in _insight_rows(insights, "flyfus_receipts.jsonl") if _public_text(row.get("provider")).casefold() == "flyfus"]
    if not receipts:
        return '<p><strong>Flyfus 积分：</strong>未提供本运行目录中的回执；未知扣费不显示为零。</p>'
    reserved = sum(_number(row.get("points_reserved")) or 0 for row in receipts)
    caps = [number for row in receipts if (number := _number(row.get("points_cap"))) is not None]
    known_used = [number for row in receipts for key in ("points_used", "points_consumed", "points_charged") if (number := _number(row.get(key))) is not None]
    mismatch = sum(1 for row in receipts if _public_text(row.get("status")) == "batch_contract_mismatch")
    return (
        '<p><strong>Flyfus 积分：</strong>回执 ' + _format_number(len(receipts)) + ' 份；'
        + '本次积分上限 ' + (_format_number(max(caps)) if caps else '未记录') + ' points；'
        + '保守预留 ' + _format_number(reserved) + ' points；'
        + ('已确认消耗 ' + _format_number(sum(known_used)) + ' points。' if known_used else '已确认消耗未记录，不能按零处理。')
        + (f'其中 {mismatch} 个评论批次因接口/计费合同不匹配已停止。' if mismatch else '')
        + 'Flyfus points 与 ScrapeCreators credits 分开记录，不能相互折算。</p>'
    )


def _render_content(
    analysis: Mapping[str, Any],
    *,
    analysis_dir: Path,
    image_overrides: Mapping[str, Path],
    insights: Mapping[str, Any],
) -> tuple[str, int, dict[str, str]]:
    concepts_html, embedded_count, image_digests = _render_concepts(
        analysis, analysis_dir=analysis_dir, image_overrides=image_overrides
    )
    exploration_html, exploration_images, exploration_digests = _render_concepts(
        analysis,
        analysis_dir=analysis_dir,
        image_overrides=image_overrides,
        exploratory=True,
    )
    embedded_count += exploration_images
    image_digests.update(exploration_digests)
    signal_html, signal_validation = _render_research_signals(insights)
    if _v2_mode(analysis):
        # V2's answer-level analysis supersedes the legacy V5 summary receipt.
        signal_html = ""
        qa = _mapping(analysis.get("alexa_analysis"))
        signal_validation = ('<p>Alexa 已处理 ' + _format_number(qa.get("analyzed_count"))
                             + ' 条回答；产品声明、冲突与后续测试见 <a href="#voices">Alexa 选购洞察与验证</a>。不计入 VOC。</p>')
    decision_html = _append_to_section(_render_decision(analysis), _render_completion(analysis))
    innovation_html = _append_to_section(_render_innovations(analysis), signal_html)
    concept_addendum = _render_brainstorm(analysis)
    concepts_html = _append_to_section(concepts_html, concept_addendum)
    method_html = _append_to_section(
        _render_method(analysis),
        _inline_section(_render_sources(analysis)) + _render_flyfus_cost(insights),
    )
    content = (
        decision_html
        + _render_semantics(analysis)
        + '<section class="report-section panel" id="voices">' + _section_head("voices-heading", "选购研究", "Alexa 选购洞察与验证", "选购维度 → 消费者发现 → Alexa 回答要点 → 商品资料核验 → 设计影响与待验证事项。Alexa 不计入有效 VOC 及需求占比分母。") + _render_qa_analysis(analysis) + '</section>'
        + _render_category(analysis)
        + _render_segments(analysis)
        + _render_kano(analysis)
        + innovation_html
        + concepts_html
        + exploration_html
        + method_html
    )
    return content, embedded_count, image_digests


class _OfflineHTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.csp_values: list[str] = []
        self.template_version: str | None = None
        self.analysis_sha256: str | None = None
        self.insight_sha256: str | None = None

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
            if lowered == "a" and attribute == "href" and value.startswith("https://"):
                continue  # A provenance link is not a runtime dependency.
            if value.startswith(("http://", "https://", "file://", "//")):
                self.errors.append(f"报告包含外部{attribute}依赖")
        if lowered == "meta" and values.get("http-equiv", "").casefold() == "content-security-policy":
            self.csp_values.append(values.get("content", ""))
        if lowered == "meta" and values.get("name") == "all-history-report-template-version":
            self.template_version = values.get("content")
        if lowered == "meta" and values.get("name") == "analysis-sha256":
            self.analysis_sha256 = values.get("content")
        if lowered == "meta" and values.get("name") == "insight-sha256":
            self.insight_sha256 = values.get("content")


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
    if inspector.template_version not in SUPPORTED_TEMPLATE_VERSIONS:
        errors.append("报告模板版本不正确")
    if not re.fullmatch(r"[0-9a-f]{64}", str(inspector.analysis_sha256 or "")):
        errors.append("报告缺少有效的analysis-sha256元数据")
    if inspector.insight_sha256 is not None and inspector.insight_sha256 != "none" and not re.fullmatch(r"[0-9a-f]{64}", inspector.insight_sha256):
        errors.append("报告包含无效的insight-sha256元数据")
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


def _hero_status_line(analysis: Mapping[str, Any]) -> str:
    """Return the concise evidence status shown in the persistent report header."""
    qualified = _integer(_funnel(analysis).get("qualified_consumer_voices"))
    status = _mapping(analysis.get("evidence_readiness")).get("status")
    label = {
        "sufficient": "已达到本轮证据门槛",
        "partial": "阶段性：仍有证据缺口",
    }.get(status, "阶段性：证据状态尚未评估")
    return f"{_format_number(qualified)} 条有效 VOC · {label}"


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
        concepts = document.get("product_concepts", [])
        if not isinstance(concepts, list) or len(concepts) > 3 or any(not isinstance(item, Mapping) for item in concepts):
            raise ReportError(f"{label}.product_concepts必须是包含0至3个对象的数组")
        if document.get("business_rules_version") in {"voc-prd-v2.1", "voc-prd-v2.2", "voc-prd-v2.3"}:
            if len(concepts) != 3:
                raise ReportError(f"{label}.product_concepts在PRD v2.1+中必须恰好包含3个对象")
            assets = _mapping(document.get("concept_image_assets"))
            for concept in concepts:
                concept_id = str(_first(concept, "concept_id", "id", default=""))
                if len(_list(assets.get(concept_id))) != 3:
                    raise ReportError(f"{label}.{concept_id}必须具有3张概念图资产")
                if document.get("business_rules_version") in {"voc-prd-v2.2", "voc-prd-v2.3"}:
                    if not isinstance(_mapping(concept.get("moscow_versions")).get("research_prototype"), Mapping) or not isinstance(_mapping(concept.get("moscow_versions")).get("provisional_v1"), Mapping):
                        raise ReportError(f"{label}.{concept_id}缺少研究打样版与暂定上市 V1 的 MoSCoW")
                    if not _list(concept.get("design_decision_chain")):
                        raise ReportError(f"{label}.{concept_id}缺少需求到机制的设计决策链")
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
                if _holistic_mode(document):
                    if _v2_mode(document) and item.get("status") == "below_threshold":
                        denominator = _mapping(document.get("funnel")).get("qualified_consumer_voices", 0)
                        count = item.get("count", 0)
                        if denominator and count * 100 >= denominator * 3:
                            raise ReportError("达到3%的需求不能标为below_threshold")
                        continue
                    if item.get("status") not in {"classified", "insufficient", "conflict", "not_applicable", "pending"}:
                        raise ReportError("综合KANO缺少有效处理状态")
                    if item.get("status") == "classified" and item.get("classification") not in {"M", "O", "A", "I", "R"}:
                        raise ReportError("已分类综合KANO类型无效")
                    continue
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
    insight_dir: Path | None = None,
) -> dict[str, Any]:
    metadata = _validate_all_history_contract(
        analysis,
        label="全历史分析",
        require_kano=True,
    )
    if analysis.get("report_presentation") is not None:
        import_report_copy(analysis, _mapping(analysis.get("report_presentation")))
    project = _mapping(analysis.get("project"))
    marketplace = _public_text(
        _first(project, "marketplace", default=_first(metadata, "marketplace", default="站点未记录"))
    ) or "站点未记录"
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
    template_inspector = _OfflineHTMLInspector()
    template_inspector.feed(template)
    if template_inspector.template_version != TEMPLATE_VERSION or 'id="approved-report-reading-layout"' not in template:
        raise ReportError("新报告必须使用已确认的 HTML 1.5.0 共享母版；旧版仅兼容检查既有报告")
    analysis_sha256 = hashlib.sha256(analysis_path.read_bytes()).hexdigest()
    insights = _load_insight_dir(insight_dir)
    overrides = _parse_image_overrides(image_args, analysis_path.parent)
    content, embedded_count, image_digests = _render_content(
        analysis,
        analysis_dir=analysis_path.parent,
        image_overrides=overrides,
        insights=insights,
    )
    replacements = {
        "{{ANALYSIS_SHA256}}": analysis_sha256,
        "{{INSIGHT_SHA256}}": str(insights["sha256"]),
        "{{MARKETPLACE}}": _escape(marketplace),
        "{{TITLE}}": _escape(report_title),
        "{{GENERATED_AT}}": _escape(generated_at),
        "{{STATUS_LINE}}": _escape(_hero_status_line(analysis)),
        "{{CATEGORY_TITLE}}": _escape(category_keyword),
        "{{GENERATED_AT_LABEL}}": _escape(generated_at.replace("T", " ").replace("+08:00", "")),
        "{{FRONT_STATUS}}": _escape("处理完成" if _front_processing_complete(analysis) else "阶段性：" + ("证据状态尚未评估" if not _mapping(analysis.get("evidence_readiness")).get("status") else _evidence_label(analysis))),
        "{{FRONT_STATUS_ICON}}": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 12 4 4 8-8"/></svg>' if _front_processing_complete(analysis) else '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"/></svg>',
        "{{FRONT_COLLECTION_LABEL}}": _escape(_public_text(_mapping(analysis.get("report_front")).get("collection_label")) or "全历史本地消费者声音"),
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
        "insight_dir": insights.get("path"),
        "insight_sha256": insights["sha256"],
        "insight_files": sorted(_mapping(insights.get("files")).keys()),
        "report_path": str(output_path.resolve()),
        "report_sha256": report_sha256,
        "standalone_html": True,
        "external_runtime_dependencies": 0,
        "embedded_image_count": embedded_count,
        "image_sha256": image_digests,
        "processing_status": analysis.get("processing_status", "not_recorded"),
        "evidence_status": _mapping(analysis.get("evidence_readiness")).get("status", "not_assessed"),
        "recommended_concept_count": len(_list(analysis.get("product_concepts"))),
        "exploration_concept_count": len(_list(analysis.get("exploration_concepts"))),
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
    insight_dir: Path | None = None,
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
    insights = _load_insight_dir(insight_dir)

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
    if coding_metadata.get("evidence_protocol") == "1.0.0":
        # New documents must reconcile from their per-record coding even when
        # callers bypass the normal reprocess/development CLI sequence.
        script_dir = str(Path(__file__).resolve().parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        from consumer_voice_local_reprocess import LocalReprocessError, validate_v3_documents
        from consumer_product_development import DevelopmentError, validate_concept, validate_development_receipt
        try:
            validate_v3_documents(coding, analysis)
            concepts = analysis.get("product_concepts", [])
            if concepts and _mapping(analysis.get("development")).get("status") != "reviewed":
                raise DevelopmentError("正式方案必须经过工作坊最终校验")
            validate_development_receipt(analysis)
            voices = {v["voice_id"]: v for v in coding["voices"]}
            for concept in concepts:
                validate_concept(concept, voices, analysis, formal=True)
        except (LocalReprocessError, DevelopmentError, ValueError, TypeError, KeyError) as exc:
            raise ReportError(f"新版证据与开发契约校验失败：{exc}") from exc
    if status == "ready":
        if _holistic_mode(analysis) and not all(completion_layers(analysis).values()):
            raise ReportError("分层业务验收尚未全部通过；请以partial交付")
        readiness = analysis.get("evidence_readiness")
        if readiness is not None and _mapping(readiness).get("status") != "sufficient":
            raise ReportError("证据尚未达到本轮门槛；请以partial交付阶段性报告")
        pending = max(
            _integer(_funnel(analysis).get("pending_records")),
            _integer(_funnel(coding).get("pending_records")),
            len(_list(coding.get("pending_records"))),
        )
        review = _mapping(analysis.get("coding_review"))
        if _holistic_mode(analysis):
            pending = max(0, pending - _integer(review.get("completed_undetermined")))
        coverage = _number(review.get("coverage"))
        review_pending = max(0, _integer(review.get("pending")) - (_integer(review.get("completed_undetermined")) if _holistic_mode(analysis) else 0))
        if pending or review_pending or _integer(review.get("rule_provisional")) or _integer(review.get("unreviewed_records")) or (coverage is not None and coverage < 1):
            raise ReportError("逐条编码复核尚未完成；请以partial交付阶段性报告")
        if "processing_status" in analysis and analysis["processing_status"] not in ({"complete", "completed"} if _holistic_mode(analysis) else {"complete"}):
            raise ReportError("本地处理尚未完成，不能标记ready")
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
    if insight_dir is not None:
        insight_hash = str(insights["sha256"])
        if inspector.insight_sha256 != insight_hash:
            raise ReportError("HTML内嵌insight-sha256与指定insight-dir不一致")

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
        "insight": str(_load_insight_dir(insight_dir)["sha256"]),
    }
    expected_hashes = {
        "source-db": source_db_hash,
        "dashboard": dashboard_hash,
        "coding": coding_hash,
        "analysis": analysis_hash,
        "report": report_hash,
        "insight": str(insights["sha256"]),
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
        "insight_sha256": (str(insights["sha256"]) if insight_dir is not None else None),
        "source_snapshot_sha256": (
            _file_sha256(source_snapshot_path, "source-snapshot")
            if source_snapshot_path is not None
            else None
        ),
    }


def _default_template() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "consumer_all_history_report.template.html"


def import_need_judgments(analysis: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a model-authored per-need artifact; never infer types from votes."""
    if not _holistic_mode(analysis):
        raise ReportError("仅新按需求综合判断模式接受此导入；历史分析保持不变")
    if payload.get("schema_version") != "consumer-need-judgments-1.0":
        raise ReportError("需求判断 schema_version 无效")
    expected = {str(row.get("need_id") or row.get("need_code") or row.get("code")): row
                for row in _list(analysis.get("kano")) if isinstance(row, Mapping) and row.get("status") != "below_threshold"}
    evidence = {str(row.get("code") or row.get("need_id")): row for row in _list(_mapping(analysis.get("evidence_readiness")).get("needs")) if isinstance(row, Mapping)}
    rows = payload.get("needs")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ReportError("needs 必须为数组")
    ids = [str(row.get("need_id") or "") for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ReportError("需求判断必须完整覆盖且不得重复/增加 need_id")
    result = copy.deepcopy(dict(analysis))
    judgments = []
    for row in rows:
        key = str(row["need_id"])
        if _v2_mode(analysis) and (not expected[key].get("source_sha256") or row.get("source_sha256") != expected[key]["source_sha256"]):
            raise ReportError("KANO判断证据指纹缺失或已失效，须重新分析受影响需求")
        status = row.get("status")
        if status not in {"classified", "insufficient", "conflict", "not_applicable"}:
            raise ReportError("判断状态无效；未执行不能作为已复核导入")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip() or not row.get("review_version"):
            raise ReportError("每项判断须有理由和复核版本")
        category = row.get("classification")
        if (status == "classified" and category not in {"M", "O", "A", "I", "R"}) or (status != "classified" and category is not None):
            raise ReportError("只有已分类需求可填写 M/O/A/I/R")
        for field in ("evidence_ids", "counter_evidence_ids", "applicable_scenarios", "validation_questions"):
            values = row.get(field)
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values) or len(values) != len(set(values)):
                raise ReportError(f"{key}.{field} 必须为无重复文本数组")
        available = evidence.get(key, {})
        known = set(available.get("support_refs", [])) | set(available.get("counter_refs", []))
        for values in _mapping(available.get("applicability")).values():
            known.update(values if isinstance(values, list) else [])
        if not set(row["evidence_ids"] + row["counter_evidence_ids"]).issubset(known):
            raise ReportError("KANO引用必须属于该需求消费者证据，不允许Alexa或不存在的ID")
        if status == "classified" and (not row["evidence_ids"] or not row["applicable_scenarios"]):
            raise ReportError("已分类判断必须有消费者证据与适用场景")
        item = dict(expected[key])
        # Counts belong to Python analysis, not the imported reasoning artifact.
        for field in ("status", "classification", "rationale", "review_version", "evidence_ids", "counter_evidence_ids", "applicable_scenarios", "validation_questions"):
            item[field] = row.get(field)
        item["need_id"] = key
        for field in ("kano_type", "classified_count", "dominant_share", "type_counts"):
            item.pop(field, None)
        judgments.append(item)
    judgments.extend(copy.deepcopy(row) for row in _list(analysis.get("kano")) if _mapping(row).get("status") == "below_threshold")
    result["kano"] = judgments
    if isinstance(result.get("category_summary"), dict):
        result["category_summary"]["kano"] = copy.deepcopy(judgments)
    return result


def prepare_need_semantic_summaries(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Export bounded, evidence-linked prompts for a Codex need-summary pass.

    This is deliberately offline: Python owns the complete eligible-need list,
    counts and evidence fingerprints; the model only writes the two prose fields.
    Raw excerpts are included for review input, never rendered into the HTML.
    """
    needs: list[dict[str, Any]] = []
    total = _integer(_funnel(analysis).get("qualified_consumer_voices"))
    for need in _eligible_need_rows(analysis):
        evidence_rows: list[dict[str, str]] = []
        for stance in ("support", "counter"):
            for index, raw in enumerate(_need_excerpts(analysis, need, counter=stance == "counter"), start=1):
                item = _mapping(raw)
                excerpt = _public_text(_first(item, "excerpt", "raw_excerpt", "text", "quote", "original_text", default=""))
                if not excerpt:
                    continue
                evidence_rows.append({
                    "evidence_id": str(_first(item, "record_id", "voice_id", "id", default=f"{stance}-{index}")),
                    "stance": stance,
                    "excerpt": excerpt[:1600],
                })
        count = _integer(_first(need, "related_count", "count", default=0))
        needs.append({
            "need_id": _need_identifier(need),
            "label": _item_label(need),
            "count": count,
            "share": count / total if total else None,
            "source_sha256": _need_summary_fingerprint(need),
            "allowed_evidence_ids": sorted(_need_evidence_ids(need)),
            "evidence_samples": evidence_rows,
            "task": "基于消费者证据总结共同任务、障碍、期望结果与边界；不得编造型号、性能、频率或原声。",
        })
    return {
        "schema_version": "consumer-need-semantic-summary-input-1.0",
        "guardrail": "模型只能归纳原声语义；统计、占比、适用性数量和need_id由Python固定。报告不展示原声或记录ID。",
        "needs": needs,
    }


def import_need_semantic_summaries(analysis: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate model summaries before they become public report prose."""
    if payload.get("schema_version") != "consumer-need-semantic-summaries-1.0":
        raise ReportError("需求语义总结 schema_version 无效")
    expected = {_need_identifier(row): row for row in _eligible_need_rows(analysis)}
    rows = payload.get("needs")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ReportError("需求语义总结 needs 必须为数组")
    ids = [str(row.get("need_id") or "") for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ReportError("需求语义总结必须完整覆盖全部 eligible need_id，且不得重复或增加")
    imported: list[dict[str, Any]] = []
    for raw in rows:
        row = _mapping(raw)
        need_id = str(row["need_id"])
        need = expected[need_id]
        if row.get("source_sha256") != _need_summary_fingerprint(need):
            raise ReportError(f"{need_id} 的消费者证据已变化，语义总结必须重做")
        for field in ("summary", "need_statement", "review_version"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 900:
                raise ReportError(f"{need_id}.{field} 必须是1至900字的非空文本")
        evidence_ids = row.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids or any(not isinstance(value, str) or not value.strip() for value in evidence_ids):
            raise ReportError(f"{need_id}.evidence_ids 必须是非空文本数组")
        if len(evidence_ids) != len(set(evidence_ids)) or not set(evidence_ids).issubset(_need_evidence_ids(need)):
            raise ReportError(f"{need_id}.evidence_ids 必须属于该需求已冻结的消费者证据")
        imported.append({
            "need_id": need_id,
            "summary": row["summary"].strip(),
            "need_statement": row["need_statement"].strip(),
            "review_version": row["review_version"].strip(),
            "source_sha256": row["source_sha256"],
            "evidence_ids": list(evidence_ids),
        })
    result = copy.deepcopy(dict(analysis))
    result["consumer_semantic_summaries"] = {
        "schema_version": "consumer-need-semantic-summaries-1.0",
        "status": "completed",
        "needs": imported,
    }
    return result


def prepare_qa_records(run_dir: Path) -> dict[str, Any]:
    """Read saved Flyfus pages only. Per-return IDs do not claim global uniqueness."""
    from flyfus_qa_catalog import build_catalog, _load_receipt, _response_items, normalize_answer
    root = run_dir.resolve()
    catalog = build_catalog(root)
    records = []
    for receipt in catalog["receipts"]:
        path = (root / receipt["receipt_path"]).resolve()
        if not path.is_relative_to(root):
            raise ReportError("问答回执越出运行目录")
        source_hash = _file_sha256(path, "问答原始回执")
        for index, item in enumerate(_response_items(_load_receipt(path))):
            record_id = hashlib.sha256((receipt["receipt_path"] + ":" + str(index)).encode()).hexdigest()[:24]
            answer = item.get("answer")
            question = item.get("question") or item.get("questionText") or item.get("text") or ""
            records.append({"record_id": record_id, "question": question, "answer": answer,
                            "answer_text": normalize_answer(answer),
                            "source_ref": str(path), "source_sha256": source_hash, "item_index": index,
                            "asin": receipt.get("asin"), "keyword": receipt.get("keyword"),
                            "status": "pending" if normalize_answer(answer) else "no_answer"})
    return {"schema_version": "consumer-qa-records-1.0", "records": records,
            "guardrail": "按接口返回条目计数；不进入消费者声音、KANO或人数"}


def import_qa_analysis(records: Mapping[str, Any], payload: Mapping[str, Any], analysis: Mapping[str, Any]) -> dict[str, Any]:
    if records.get("schema_version") != "consumer-qa-records-1.0" or payload.get("schema_version") != "consumer-qa-analysis-1.0":
        raise ReportError("Alexa内容分析 schema_version 无效")
    from flyfus_qa_catalog import normalize_answer
    originals = {str(row.get("record_id")): row for row in _list(records.get("records")) if isinstance(row, Mapping) and normalize_answer(row.get("answer"))}
    rows = payload.get("records")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ReportError("Alexa分析 records 必须是数组")
    ids = [str(row.get("record_id")) for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(originals):
        raise ReportError("Alexa分析须完整覆盖所有已保存非空回答，不能漏ID/多ID/重复ID")
    needs = {str(row.get("need_id") or row.get("code") or row.get("need_code")) for row in [*_list(analysis.get("kano")), *_list(_mapping(analysis.get("evidence_readiness")).get("needs"))] if isinstance(row, Mapping)}
    merged = []
    for row in rows:
        original = originals[str(row["record_id"])]
        disposition = row.get("disposition", "adopted")
        if disposition not in {"adopted", "irrelevant", "parse_failed", "insufficient"}:
            raise ReportError("Alexa处理结果无效")
        if _file_sha256(Path(original["source_ref"]), "问答回执") != original["source_sha256"]:
            raise ReportError("问答原始回执已改变")
        from flyfus_qa_catalog import _load_receipt, _response_items
        source_items = _response_items(_load_receipt(Path(original["source_ref"])))
        index = original.get("item_index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(source_items) or source_items[index].get("answer") != original["answer"]:
            raise ReportError("问答清单与原始回执条目不一致")
        for field in ("question_summary", "answer_summary", "claim_kind", "conflict_check", "next_verification", "review_version"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ReportError(f"Alexa内容分析缺少 {field}")
        if row["claim_kind"] not in {"product_promise", "verifiable_claim", "inference", "general_advice", "mixed"}:
            raise ReportError("Alexa声明性质无效")
        for field in ("need_ids", "buying_dimensions", "unknown_conditions", "evidence_quotes"):
            if not isinstance(row.get(field), list) or any(not isinstance(value, str) or not value.strip() for value in row[field]):
                raise ReportError(f"Alexa内容分析 {field} 必须为文本数组")
        if not set(row["need_ids"]).issubset(needs):
            raise ReportError("Alexa关联了不存在的需求")
        if disposition == "adopted" and not row["need_ids"] and not row["buying_dimensions"]:
            raise ReportError("Alexa分析必须关联需求或选购维度")
        verification = row.get("verification_status", "pending_verification")
        if verification not in {"independently_verified", "conflicting", "pending_verification"}:
            raise ReportError("Alexa核验状态无效")
        if verification == "independently_verified" and not row.get("verification_sources"):
            raise ReportError("独立核实必须有商品资料来源")
        answer = original["answer"] if isinstance(original["answer"], str) else json.dumps(original["answer"], ensure_ascii=False)
        if not row["evidence_quotes"] or any(quote not in answer for quote in row["evidence_quotes"]):
            raise ReportError("Alexa引文不存在于原始回答")
        merged.append({**original, **{key: row[key] for key in ("question_summary", "answer_summary", "claim_kind", "conflict_check", "next_verification", "review_version", "need_ids", "buying_dimensions", "unknown_conditions", "evidence_quotes")}, "verification_status": verification, "verification_sources": row.get("verification_sources", []), "disposition": disposition, "status": "analyzed"})
    return {"schema_version": "consumer-qa-analysis-1.0", "records": merged,
            "question_count": len(_list(records.get("records"))), "answer_count": len(originals), "analyzed_count": len(merged), "pending_count": 0,
            "status": "completed" if originals else "data_limited",
            "disposition_counts": {state: sum(row["disposition"] == state for row in merged) for state in ("adopted", "irrelevant", "parse_failed", "insufficient")},
            "empty_records": [{**row, "status": "no_answer"} for row in _list(records.get("records")) if isinstance(row, Mapping) and not normalize_answer(row.get("answer"))],
            "no_answer_count": len(_list(records.get("records"))) - len(originals)}


def completion_layers(analysis: Mapping[str, Any]) -> dict[str, bool]:
    readiness = _mapping(analysis.get("evidence_readiness"))
    review = _mapping(analysis.get("coding_review"))
    qa = _mapping(analysis.get("alexa_analysis"))
    development = _mapping(analysis.get("development"))
    kano = _list(analysis.get("kano"))
    workshop = False
    if development.get("status") == "reviewed":
        try:
            from consumer_product_development import validate_development_receipt
            validate_development_receipt(analysis)
            workshop = bool(development.get("workshop_receipt"))
        except (ValueError, TypeError, KeyError):
            pass
    return {
        "采集查漏": (_mapping(analysis.get("collection_execution")).get("status") == "completed" if _v2_mode(analysis) else readiness.get("status") == "sufficient"),
        "全量处理": analysis.get("processing_status") in {"complete", "completed"} and not max(0, _integer(_funnel(analysis).get("pending_records")) - _integer(review.get("completed_undetermined"))),
        "疑难与质量": review.get("coverage") == 1 and not _integer(review.get("unreviewed_records")) and _mapping(analysis.get("quality_audit")).get("status") == "passed",
        "需求与KANO": bool(kano) and all(_mapping(row).get("status") == "below_threshold" or (_mapping(row).get("status") in {"classified", "insufficient", "conflict", "not_applicable"} and _mapping(row).get("review_version")) for row in kano),
        "Alexa已采分析": qa.get("schema_version") == "consumer-qa-analysis-1.0" and qa.get("pending_count") == 0 and (bool(qa.get("answer_count")) or (qa.get("status") == "data_limited" and bool(qa.get("question_count")))),
        "工作坊与竞品": workshop and len(_list(analysis.get("product_concepts"))) == 3 and bool(analysis.get("competition_audit")),
        "概念与验证计划": workshop and len(_list(analysis.get("product_concepts"))) == 3 and all(bool(_mapping(row).get("acceptance_metrics")) for row in _list(analysis.get("product_concepts"))),
    }


def _render_completion(analysis: Mapping[str, Any]) -> str:
    if not _holistic_mode(analysis):
        return ""
    return '<div class="method-note"><strong>业务完成状态（HTML渲染成功不代表业务完成）</strong><ul>' + ''.join(
        '<li>' + _escape(name) + '：' + ('已通过' if passed else '尚未通过 / 缺少验收产物') + '</li>' for name, passed in completion_layers(analysis).items()) + '</ul></div>'


def _render_qa_analysis(analysis: Mapping[str, Any]) -> str:
    qa = _mapping(analysis.get("alexa_analysis"))
    if not qa:
        return '<p>Alexa已采回答尚未完成内容分析；原始数量不代表需求关联已完成。</p>' if _holistic_mode(analysis) else ''
    items = []
    labels = {"independently_verified": "已独立核实", "conflicting": "存在冲突", "pending_verification": "待核实"}
    dimensions: dict[str, list[Mapping[str, Any]]] = {}
    need_labels = {str(n.get("need_id") or n.get("code")): _item_label(n)
                   for n in _list(_mapping(analysis.get("evidence_readiness")).get("needs")) if isinstance(n, Mapping)}
    # Presentation aliases only: preserve model-authored dimensions in audit.
    dimension_groups = {
        "空间形态与占地": "卧室适配 小空间形态 折叠与扩展 收纳体积 收纳厚度 收纳折叠 有限空间布局 空间与设备保留 空间利用 空间增益未证实 空间效率方案 空间机制 转角布局 转角收益",
        "坐姿、升降与净空": "L形升降边界 人体工学接口 人体工学系统 低身高适配 升降与尺寸 升降收纳取舍 升降范围 升降记忆位 升降配置复核 坐站取舍 坐站方案边界 座椅兼容 座椅收纳包络 提醒控制 收纳与膝部空间 桌椅兼容 电动升降 视距与输入面 调高方式 折叠升降对比",
        "收纳、理线与供电": "L桌理线借鉴 低预算理线 供电与模块化 储物与视线 储物密度 内置与外加理线 内置供电 内置理线边界 可逆收纳 可重构收纳 外挂收纳 大型L桌理线 抽屉价值 收纳分区 收纳功能取舍 收纳布局 收纳易清洁 收纳边界 文件安全附件 模块收纳 物理与数字收纳 理线与维护 理线适配 组织配件 综合收纳 跨行业模块收纳 转角收纳",
        "设备容纳与扩展接口": "单屏与双屏 多屏接口 扩展接口 屏幕留存线索 线缆配件兼容 设备容纳 附件接口 附件生态",
        "承重、材料与耐久": "墙体条件 多屏承载 座椅载荷 承重与稳定 承重口径 易清洁材料 材料与稳定 材料寿命 材料工艺 材料强度 材料维护 稳定结构 耐久材料声明",
        "安装、装拆与移动": "安装复杂度 安装方式 安装验收 定位灵活性 抽屉桌安装 搬家与装拆 移动与携带 移动便携 装拆承诺冲突 跨行业便携 首次安装",
        "价格、品牌与配置取舍": "价格与配置 促销时效 品牌选择 家用桌对比 折叠预算 抽屉价格 热销线索 白色外观预算 预算与适配 预算与配置",
        "适用场景与产品边界": "儿童场景边界 儿童材料边界 儿童用途边界 办公适配资料不足 商业与家用边界 多用途转换 游戏需求取舍 膝上与整桌边界 轻办公边界 迷你桌任务适配",
    }
    dimension_aliases = {label: group for group, labels_in_group in dimension_groups.items() for label in labels_in_group.split()}
    for row in _list(qa.get("records")):
        row = _mapping(row)
        if row.get("disposition", "adopted") != "adopted":
            continue
        display_dimensions = _list(row.get("buying_dimensions")) or ["综合选购"]
        if _v2_mode(analysis):
            # Use existing model-authored links, never infer a new semantic label here.
            linked = [need_labels[n] for n in _list(row.get("need_ids")) if n in need_labels]
            display_dimensions = list(dict.fromkeys(linked or [dimension_aliases.get(str(d), str(d)) for d in display_dimensions]))
        for dimension in display_dimensions:
            dimensions.setdefault(str(dimension), []).append(row)
    for dimension, rows in dimensions.items():
        unique = {(row.get("answer_summary"), row.get("conflict_check"), row.get("next_verification")): row for row in rows}
        body = ''.join('<article><p>' + _escape(row.get("answer_summary")) + '</p><p>核验状态：' + labels.get(row.get("verification_status"), "待核实") + '</p><p>开发影响与冲突：' + _escape(row.get("conflict_check")) + '</p><p>验证方法：' + _escape(row.get("next_verification")) + '</p></article>' for row in unique.values())
        items.append('<details><summary>' + _escape(dimension) + ' · ' + str(len(rows)) + ' 条回答</summary>' + body + '</details>')
    state = '资料受限：暂无可用回答。' if not qa.get("answer_count") else ''
    dispositions = _mapping(qa.get("disposition_counts"))
    disposition_text = ('；采纳 ' + _format_number(dispositions.get("adopted"))
                        + '；无关 ' + _format_number(dispositions.get("irrelevant"))
                        + '；解析失败 ' + _format_number(dispositions.get("parse_failed"))
                        + '；证据不足 ' + _format_number(dispositions.get("insufficient"))) if dispositions else ''
    return '<p>' + state + '问题 ' + _format_number(qa.get("question_count")) + '；回答 ' + _format_number(qa.get("answer_count")) + '；已分析 ' + _format_number(qa.get("analyzed_count")) + disposition_text + '。重复回答保留原始计数，不代表需求热度；以下仅归纳采纳项。按已有需求关联组织维度，同一回答可进入多个维度，分类数量不可相加。</p>' + ''.join(items)


def _render_discovery(analysis: Mapping[str, Any]) -> str:
    discovery = _mapping(analysis.get("search_discovery"))
    labels = {"completed": "已执行", "failed": "执行失败", "not_executed": "未执行", "legacy_untraceable": "历史来源无法追溯"}
    rows = []
    for item in _list(discovery.get("clues")):
        item = _mapping(item)
        rows.append('<tr><td>' + _escape(item.get("label")) + '</td><td>' + _escape(labels.get(item.get("status"), "未执行")) + '</td><td>' + _escape('；'.join(map(str, _list(item.get("queries"))))) + '</td><td>' + _format_number(item.get("candidate_count")) + '</td><td>' + _format_number(item.get("valid_count")) + '</td><td>' + _escape(item.get("note")) + '</td></tr>')
    return '<h3>十类需求发现线索执行情况</h3>' + ('<div class="table-frame"><table><thead><tr><th>线索</th><th>执行状态</th><th>实际查询</th><th>候选数</th><th>有效声音</th><th>说明</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>' if rows else '<p>未提供可追溯查询执行记录；历史声音不能据此宣称十类线索已覆盖。</p>')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="全历史本地消费者声音独立HTML报告工具"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_qa = subparsers.add_parser("prepare-qa-analysis", help="从已保存问答页导出内容复核清单，不联网")
    prepare_qa.add_argument("--run-dir", required=True, type=Path)
    prepare_qa.add_argument("--output", required=True, type=Path)
    prepare_summaries = subparsers.add_parser("prepare-need-summaries", help="导出逐需求消费者语义总结包，不联网")
    prepare_summaries.add_argument("--analysis", required=True, type=Path)
    prepare_summaries.add_argument("--output", required=True, type=Path)
    import_summaries = subparsers.add_parser("import-need-summaries", help="校验并导入模型完成的逐需求语义总结")
    import_summaries.add_argument("--analysis", required=True, type=Path)
    import_summaries.add_argument("--semantic-summaries", required=True, type=Path)
    import_summaries.add_argument("--output", required=True, type=Path)
    enrich = subparsers.add_parser("import-insights", help="校验按需求KANO和Alexa正文分析，写入新的分析文件")
    enrich.add_argument("--analysis", required=True, type=Path)
    enrich.add_argument("--need-judgments", type=Path)
    enrich.add_argument("--qa-records", type=Path)
    enrich.add_argument("--qa-analysis", type=Path)
    enrich.add_argument("--output", required=True, type=Path)
    for command in ("prepare-report-copy", "import-report-copy"):
        entry = subparsers.add_parser(command, help="准备或导入面向运营与开发的短摘要，不改产品定义")
        entry.add_argument("--analysis", required=True, type=Path)
        entry.add_argument("--output", required=True, type=Path)
        if command == "import-report-copy":
            entry.add_argument("--presentation", required=True, type=Path)
    render = subparsers.add_parser("render", help="生成单文件离线HTML")
    render.add_argument("--analysis", required=True, type=Path)
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--template", type=Path, default=_default_template())
    render.add_argument("--title")
    render.add_argument("--final", action="store_true", help="要求所有业务验收通过，且恰好三个正式方向")
    render.add_argument("--insight-dir", type=Path, help="仅读取指定 V5 运行目录内的既有摘要、问答账本与费用回执")
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
    finalize.add_argument("--insight-dir", type=Path, help="校验报告所引用的既有 V5 运行目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"prepare-report-copy", "import-report-copy"}:
            if args.output.exists() or args.output.resolve() == args.analysis.resolve():
                raise ReportError("必须写入不存在的新版本文件，不覆盖历史分析")
            analysis = _load_json(args.analysis)
            result = (prepare_report_copy(analysis) if args.command == "prepare-report-copy"
                      else import_report_copy(analysis, _load_json(args.presentation)))
            _atomic_write_json(args.output, result)
            return 0
        if args.command == "prepare-qa-analysis":
            if args.output.exists():
                raise ReportError("输出已存在，请使用新版本路径")
            _atomic_write_json(args.output, prepare_qa_records(args.run_dir))
            return 0
        if args.command == "prepare-need-summaries":
            if args.output.exists():
                raise ReportError("输出已存在，请使用新版本路径")
            _atomic_write_json(args.output, prepare_need_semantic_summaries(_load_json(args.analysis)))
            return 0
        if args.command == "import-need-summaries":
            if args.output.exists() or args.output.resolve() == args.analysis.resolve():
                raise ReportError("必须写入不存在的新版本文件，不覆盖历史分析")
            result = import_need_semantic_summaries(_load_json(args.analysis), _load_json(args.semantic_summaries))
            _atomic_write_json(args.output, result)
            return 0
        if args.command == "import-insights":
            if args.output.exists() or args.output.resolve() == args.analysis.resolve():
                raise ReportError("必须写入不存在的新版本文件，不覆盖历史分析")
            result = _load_json(args.analysis)
            if not args.need_judgments and not args.qa_analysis:
                raise ReportError("至少提供一种洞察产物")
            if args.need_judgments:
                result = import_need_judgments(result, _load_json(args.need_judgments))
            if args.qa_analysis:
                if not args.qa_records:
                    raise ReportError("Alexa分析必须绑定原始清单")
                result["alexa_analysis"] = import_qa_analysis(_load_json(args.qa_records), _load_json(args.qa_analysis), result)
            _atomic_write_json(args.output, result)
            return 0
        if args.command == "render":
            analysis_path = args.analysis.expanduser().resolve()
            template_path = args.template.expanduser().resolve()
            output_path = args.output.expanduser().resolve()
            analysis = _load_json(analysis_path)
            if args.final:
                import_report_copy(analysis, _mapping(analysis.get("report_presentation")))
                failures = [name for name, passed in completion_layers(analysis).items() if not passed]
                if failures:
                    raise ReportError("完整报告验收未通过：" + "、".join(failures))
            receipt = render_report(
                analysis,
                analysis_path=analysis_path,
                template_path=template_path,
                output_path=output_path,
                title=args.title,
                image_args=args.concept_image,
                insight_dir=args.insight_dir,
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
                insight_dir=args.insight_dir,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0
    except (ReportError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
