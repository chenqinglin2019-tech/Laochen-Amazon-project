#!/usr/bin/env python3
"""消费者声音联合研究的确定性校验、统计与离线报告工具。

本模块只使用 Python 标准库。所有面向用户的统计均从逐条编码记录重算，
不会接受输入文件中的手填分母、次数或占比。
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import html as html_lib
import importlib.util
import json
import mimetypes
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCHEMA_VERSION = "2.0.0"
LEGACY_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({LEGACY_SCHEMA_VERSION, SCHEMA_VERSION})
CATEGORY_SCOPE = "category_30d"
SEGMENT_SCOPES = tuple(f"segment_{index}_90d" for index in range(1, 4))
SEGMENT_IDS = SEGMENT_SCOPES
ALLOWED_SCOPES = frozenset((CATEGORY_SCOPE, *SEGMENT_SCOPES))
RESEARCH_LEVEL_DEFAULT = "quick"
RESEARCH_LEVEL_TARGETS: dict[str, dict[str, Any]] = {
    "quick": {
        "sample_target": {
            "total_valid_min": 500,
            "total_valid_max": 1000,
            "per_scope": {
                "category_30d": {"share": 0.4, "valid_min": 200, "valid_max": 400},
                "segment_1_90d": {"share": 0.2, "valid_min": 100, "valid_max": 200},
                "segment_2_90d": {"share": 0.2, "valid_min": 100, "valid_max": 200},
                "segment_3_90d": {"share": 0.2, "valid_min": 100, "valid_max": 200},
            },
            "min_platforms": 3,
        },
        "time_budget_minutes": {"collection": 35, "total": 60},
    },
    "standard": {
        "sample_target": {
            "total_valid_min": 1000,
            "total_valid_max": 3000,
            "per_scope": {
                "category_30d": {"share": 0.4, "valid_min": 400, "valid_max": 1200},
                "segment_1_90d": {"share": 0.2, "valid_min": 200, "valid_max": 600},
                "segment_2_90d": {"share": 0.2, "valid_min": 200, "valid_max": 600},
                "segment_3_90d": {"share": 0.2, "valid_min": 200, "valid_max": 600},
            },
            "min_platforms": 3,
        },
        "time_budget_minutes": {"collection": 55, "total": 90},
    },
    "deep": {
        "sample_target": {
            "total_valid_min": 3000,
            "total_valid_max": 5000,
            "per_scope": {
                "category_30d": {"share": 0.4, "valid_min": 1200, "valid_max": 2000},
                "segment_1_90d": {"share": 0.2, "valid_min": 600, "valid_max": 1000},
                "segment_2_90d": {"share": 0.2, "valid_min": 600, "valid_max": 1000},
                "segment_3_90d": {"share": 0.2, "valid_min": 600, "valid_max": 1000},
            },
            "min_platforms": 3,
        },
        "time_budget_minutes": {"collection": 75, "total": 120},
    },
}
STOP_REASONS = frozenset(
    {
        "upper_bound_reached",
        "queues_exhausted",
        "low_increment_3_batches",
        "platform_or_quota_limit",
        "collection_deadline",
        "total_deadline",
        "manual_stop",
    }
)
RESEARCH_LEVEL_PRESENTATION = {
    "quick": "快速研究",
    "standard": "标准研究",
    "deep": "深度研究",
}
STOP_REASON_PRESENTATION = {
    "upper_bound_reached": "达到档位上限",
    "queues_exhausted": "待采队列已完成",
    "low_increment_3_batches": "连续三批新增过低",
    "platform_or_quota_limit": "平台或额度限制",
    "collection_deadline": "采集时间到限",
    "total_deadline": "总时间到限",
    "manual_stop": "人工停止",
}
PLATFORM_PRESENTATION = {
    "reddit": "Reddit",
    "x": "X",
    "twitter": "X",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
}
FUNNEL_STAGE_FIELDS = (
    "fetched_records",
    "unique_records",
    "within_window_records",
    "relevant_records",
    "consumer_records",
    "deduplicated_records",
    "valid_voices",
)
V2_SEGMENT_RECENT_FIELDS = frozenset(
    {
        "denominator_recent_30d",
        "need_stats_recent_30d",
        "satisfaction_recent_30d_change",
        "dissatisfaction_recent_30d_change",
        "need_persistence",
    }
)
V2_SEGMENT_SUBWINDOW_KEYS = frozenset(
    {
        *V2_SEGMENT_RECENT_FIELDS,
        "same_window_comparison",
        "recent_30d_start_at",
        "segment_recent_slice_days",
        "is_recent_30d",
        "period_bucket",
        "temporal_buckets",
        "comparison_window_days",
        "recent_30d",
        "segments_recent_30d",
        "recent_30d_voice_count",
        "recent_30d_voice_share",
        "days_31_90_voice_count",
        "days_31_90_voice_share",
        "days_31_90_count_per_30d",
        "still_active_recent_30d",
        "percentage_point_difference",
        "ratio_to_category",
        "change_direction",
    }
)
V2_SEGMENT_SUBWINDOW_VALUES = frozenset(
    {
        "segment_1_recent_30d",
        "segment_2_recent_30d",
        "segment_3_recent_30d",
        "segment_recent_30d",
        "segment_days_31_90",
        "segments_recent_30d",
    }
)
REPRESENTATIVE_EVIDENCE_LIMIT = 3
REQUIRED_REPORT_CSP = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
    "script-src 'none'; connect-src 'none'; font-src 'none'; media-src 'none'; "
    "object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)
PLACEHOLDER_FEATURES = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "null",
        "other",
        "others",
        "unknown",
        "unrecognized",
        "其他",
        "其它",
        "未知",
        "不可识别",
        "未识别",
        "空值",
        "无",
    }
)
KANO_ALIASES = {
    "m": "M",
    "must-be": "M",
    "must_be": "M",
    "basic": "M",
    "必备": "M",
    "必备型": "M",
    "o": "O",
    "one-dimensional": "O",
    "one_dimensional": "O",
    "performance": "O",
    "期望": "O",
    "期望型": "O",
    "a": "A",
    "attractive": "A",
    "delighter": "A",
    "魅力": "A",
    "魅力型": "A",
    "i": "I",
    "indifferent": "I",
    "无差异": "I",
    "无差异型": "I",
    "r": "R",
    "reverse": "R",
    "反向": "R",
    "反向型": "R",
    "insufficient": "evidence_insufficient",
    "evidence_insufficient": "evidence_insufficient",
    "证据不足": "evidence_insufficient",
}
TAG_FIELDS = ("needs", "satisfactions", "dissatisfactions", "ideas")
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
    }
)


class ContractError(Exception):
    """可预期的输入或契约错误。"""

    def __init__(self, message: str, details: Sequence[str] | None = None):
        super().__init__(message)
        self.details = list(details or [])


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, Mapping)
    return True


def _schema_resolve(root: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ContractError(f"仅支持本地JSON Schema引用：{reference}")
    current: Any = root
    for token in reference[2:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or key not in current:
            raise ContractError(f"JSON Schema引用不存在：{reference}")
        current = current[key]
    return current


def _schema_errors(
    value: Any,
    schema: Any,
    root: Mapping[str, Any],
    path: str = "$",
) -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: schema禁止该值"]
    if not isinstance(schema, Mapping):
        return [f"{path}: 无效schema节点"]
    if "$ref" in schema:
        return _schema_errors(value, _schema_resolve(root, str(schema["$ref"])), root, path)
    errors: list[str] = []
    for child in schema.get("allOf", []):
        errors.extend(_schema_errors(value, child, root, path))
    if "oneOf" in schema:
        matches = [
            child
            for child in schema["oneOf"]
            if not _schema_errors(value, child, root, path)
        ]
        if len(matches) != 1:
            errors.append(f"{path}: 必须且只能匹配oneOf中的一个分支")
    if "if" in schema:
        condition_matches = not _schema_errors(value, schema["if"], root, path)
        branch = schema.get("then") if condition_matches else schema.get("else")
        if branch is not None:
            errors.extend(_schema_errors(value, branch, root, path))
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 必须等于 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 不在允许枚举中")
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_schema_type_matches(value, item) for item in expected_types):
            return errors + [f"{path}: 类型必须为 {expected_types}"]
    if isinstance(value, Mapping):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺少必填字段 {key}")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, item in value.items():
                if key in properties:
                    errors.extend(_schema_errors(item, properties[key], root, f"{path}.{key}"))
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}: 不允许额外字段 {key}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: 数组长度小于 {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: 数组长度大于 {schema['maxItems']}")
        if schema.get("uniqueItems"):
            markers = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(markers) != len(set(markers)):
                errors.append(f"{path}: 数组元素必须唯一")
        prefix = schema.get("prefixItems", [])
        for index, child in enumerate(prefix):
            if index < len(value):
                errors.extend(_schema_errors(value[index], child, root, f"{path}[{index}]"))
        items = schema.get("items")
        start = len(prefix)
        if items is not None:
            for index in range(start, len(value)):
                errors.extend(_schema_errors(value[index], items, root, f"{path}[{index}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 字符串过短")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 字符串过长")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            errors.append(f"{path}: 不匹配pattern {schema['pattern']}")
        if schema.get("format") == "date-time":
            try:
                _parse_datetime(value, path)
            except ValueError as exc:
                errors.append(str(exc))
        elif schema.get("format") == "date":
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                errors.append(f"{path}: 不是有效YYYY-MM-DD日期")
        elif schema.get("format") == "uri":
            parts = urlsplit(value)
            if not parts.scheme:
                errors.append(f"{path}: 不是绝对URI")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 小于minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 大于maximum {schema['maximum']}")
    return errors


def _json_path(path: str, key: Any) -> str:
    raw = str(key)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        return f"{path}.{raw}"
    return f"{path}[{json.dumps(raw, ensure_ascii=False)}]"


def _v2_segment_subwindow_errors(value: Any, path: str = "$") -> list[str]:
    """Recursively reject every removed Top3 sub-window construct in v2.

    Only exact enum-like values and known structural field names are inspected;
    consumer prose containing words such as "recent" is intentionally untouched.
    """
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            raw_key = str(key)
            child_path = _json_path(path, raw_key)
            forbidden_key = (
                raw_key in V2_SEGMENT_SUBWINDOW_KEYS
                or re.fullmatch(r"N_segment_[1-3]_recent_30d", raw_key) is not None
                or re.fullmatch(
                    r"segment(?:_[1-3])?_(?:recent_30d|days_31_90)",
                    raw_key,
                )
                is not None
            )
            if forbidden_key:
                errors.append(f"v2禁止细分子窗口字段 {child_path}")
            errors.extend(_v2_segment_subwindow_errors(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_v2_segment_subwindow_errors(item, f"{path}[{index}]"))
    elif isinstance(value, str) and value.casefold() in V2_SEGMENT_SUBWINDOW_VALUES:
        errors.append(f"v2禁止细分子窗口值 {path}={value}")
    return list(dict.fromkeys(errors))


def _validate_against_schema(document: Any, schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    if not isinstance(schema, Mapping):
        raise ContractError(f"{label} Schema顶层必须是对象")
    errors = _schema_errors(document, schema, schema)
    if (
        schema.get("x-v2-forbid-segment-subwindows") is True
        and isinstance(document, Mapping)
        and document.get("schema_version") == SCHEMA_VERSION
    ):
        errors.extend(_v2_segment_subwindow_errors(document))
    if errors:
        raise ContractError(f"{label}未通过JSON Schema校验", errors[:300])


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _print_json(payload: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        file=stream,
    )


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ContractError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"JSON 无法解析：{path}",
            [f"line={exc.lineno}, column={exc.colno}, message={exc.msg}"],
        ) from exc
    except OSError as exc:
        raise ContractError(f"无法读取文件：{path}", [str(exc)]) from exc


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = None
    if path.exists():
        mode = path.stat().st_mode & 0o777
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary_path, mode)
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
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, payload: Any) -> None:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        default=_json_default,
    )
    _atomic_write_text(path, content + "\n")


def _iso(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是带时区的 ISO 8601 时间")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} 不是有效的 ISO 8601 时间：{value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} 必须显式包含时区：{value!r}")
    return parsed.astimezone(timezone.utc)


def _as_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是数字")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是数字") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field} 必须是有限数字")
    return result


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text, flags=re.UNICODE)


def _normalized_feature(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def _normalize_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    if not parts.scheme or not parts.netloc:
        return text
    query = []
    for key, item_value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered in TRACKING_QUERY_KEYS or lowered.startswith(TRACKING_QUERY_PREFIXES):
            continue
        query.append((key, item_value))
    query.sort()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            path,
            urlencode(query, doseq=True),
            "",
        )
    )


def _deep_get(document: Mapping[str, Any], paths: Iterable[Sequence[str]]) -> Any:
    for path in paths:
        current: Any = document
        found = True
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                found = False
                break
            current = current[key]
        if found:
            return current
    return None


def _document_end_at(document: Mapping[str, Any]) -> datetime:
    value = _deep_get(
        document,
        (
            ("end_at",),
            ("research", "end_at"),
            ("research_context", "end_at"),
            ("metadata", "end_at"),
            ("study", "end_at"),
        ),
    )
    try:
        return _parse_datetime(value, "end_at")
    except ValueError as exc:
        raise ContractError("编码文件缺少可复现的统一 end_at", [str(exc)]) from exc


def _document_voices(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    voices = document.get("voices")
    if voices is None:
        voices = document.get("items")
    if not isinstance(voices, list):
        raise ContractError("编码文件必须包含 voices 数组")
    if any(not isinstance(item, Mapping) for item in voices):
        raise ContractError("voices 中每一项都必须是对象")
    return [copy.deepcopy(dict(item)) for item in voices]


def _default_research_plan(level: str = RESEARCH_LEVEL_DEFAULT) -> dict[str, Any]:
    selected = level if level in RESEARCH_LEVEL_TARGETS else RESEARCH_LEVEL_DEFAULT
    return {
        "research_level": selected,
        **copy.deepcopy(RESEARCH_LEVEL_TARGETS[selected]),
    }


def _research_plan(document: Mapping[str, Any]) -> dict[str, Any]:
    raw = document.get("research_plan")
    if not isinstance(raw, Mapping):
        return _default_research_plan()
    level = str(raw.get("research_level") or RESEARCH_LEVEL_DEFAULT)
    # 档位口径是固定契约；调用方只能选择档位，不能改写目标或预算。
    return _default_research_plan(level)


def _default_stop_reason(document: Mapping[str, Any], valid_count: int) -> str:
    raw = str(document.get("stop_reason") or "")
    if raw in STOP_REASONS:
        return raw
    target = _research_plan(document)["sample_target"]
    if valid_count >= int(target["total_valid_max"]):
        return "upper_bound_reached"
    source_runs = document.get("source_runs")
    statuses = {
        str(run.get("status") or "")
        for run in (source_runs if isinstance(source_runs, list) else [])
        if isinstance(run, Mapping)
    }
    if statuses & {"rate_limited", "auth_failed", "unavailable", "error"}:
        return "platform_or_quota_limit"
    if "timeout" in statuses:
        return "collection_deadline"
    return "queues_exhausted"


def _voice_scope_ids(voice: Mapping[str, Any]) -> set[str]:
    scopes: set[str] = set()
    for raw in voice.get("collection_scopes") or []:
        if isinstance(raw, str):
            # A collection hit proves only that the query found the message.
            # Segment denominators require an explicit semantic membership.
            if raw == CATEGORY_SCOPE:
                scopes.add(raw)
        elif isinstance(raw, Mapping):
            scope_id = raw.get("scope_id") or raw.get("id")
            if (
                scope_id == CATEGORY_SCOPE
                and raw.get("is_member", True) is not False
            ):
                scopes.add(str(scope_id))
    for raw in voice.get("segment_memberships") or []:
        if isinstance(raw, str):
            scopes.add(raw)
        elif isinstance(raw, Mapping) and raw.get("is_member") is True:
            segment_id = raw.get("segment_id") or raw.get("scope_id")
            if segment_id:
                scopes.add(str(segment_id))
    return scopes


def _funnel_stage_errors(funnel: Mapping[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    values: list[int] = []
    for field in FUNNEL_STAGE_FIELDS:
        value = funnel.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{prefix}.{field} 必须是非负整数")
            continue
        values.append(value)
    if len(values) == len(FUNNEL_STAGE_FIELDS) and any(
        current < following for current, following in zip(values, values[1:])
    ):
        errors.append(f"{prefix} 各阶段数量必须单调不增")
    return errors


def _validate_collection_contract(
    document: Mapping[str, Any], voices: Sequence[Mapping[str, Any]]
) -> list[str]:
    if document.get("schema_version") != SCHEMA_VERSION:
        return []
    errors: list[str] = []
    plan = document.get("research_plan")
    expected_plan = _research_plan(document)
    if plan != expected_plan:
        errors.append("research_plan 必须严格使用所选research_level的固定目标与预算")
    stop_reason = document.get("stop_reason")
    if stop_reason not in STOP_REASONS:
        errors.append("stop_reason 不在允许枚举中")
    funnel = document.get("collection_funnel")
    if not isinstance(funnel, Mapping):
        return errors + ["collection_funnel 必须是对象"]
    errors.extend(_funnel_stage_errors(funnel, "collection_funnel"))
    excluded = document.get("excluded_records")
    excluded_count = len(excluded) if isinstance(excluded, list) else 0
    if funnel.get("excluded_records") != excluded_count:
        errors.append("collection_funnel.excluded_records 必须等于 excluded_records 数量")
    deduplicated, _ = _deduplicate_voices(voices)
    valid_count = len(deduplicated)
    deduplicated_records = funnel.get("deduplicated_records")
    if (
        isinstance(deduplicated_records, int)
        and not isinstance(deduplicated_records, bool)
        and deduplicated_records < valid_count
    ):
        errors.append(
            "collection_funnel.deduplicated_records 不得少于最终有效留言数"
        )
    if funnel.get("valid_voices") != valid_count:
        errors.append("collection_funnel.valid_voices 必须等于最终有效留言数")
    per_scope = funnel.get("per_scope")
    scope_items = {
        str(item.get("scope_id")): item
        for item in (per_scope if isinstance(per_scope, list) else [])
        if isinstance(item, Mapping)
    }
    if set(scope_items) != set(ALLOWED_SCOPES):
        errors.append("collection_funnel.per_scope 必须完整覆盖全品类与Top3四路")
    for scope_id, item in scope_items.items():
        errors.extend(_funnel_stage_errors(item, f"collection_funnel.per_scope[{scope_id}]"))
        expected_valid = sum(
            1
            for voice in deduplicated
            if scope_id in _voice_scope_ids(voice)
        )
        if item.get("valid_voices") != expected_valid:
            errors.append(
                f"collection_funnel.per_scope[{scope_id}].valid_voices 必须等于该路有效留言数"
            )
    return errors


def _v2_removed_coding_field_errors(document: Mapping[str, Any]) -> list[str]:
    if document.get("schema_version") != SCHEMA_VERSION:
        return []
    errors: list[str] = []
    windows = document.get("windows")
    segment_window = windows.get("segment_90d") if isinstance(windows, Mapping) else None
    if isinstance(segment_window, Mapping) and "recent_30d_start_at" in segment_window:
        errors.append("v2禁止 windows.segment_90d.recent_30d_start_at")
    for index, voice in enumerate(document.get("voices") or []):
        if not isinstance(voice, Mapping):
            continue
        for field in ("is_recent_30d", "period_bucket", "temporal_buckets"):
            if field in voice:
                errors.append(f"v2禁止 voices[{index}].{field}")
    return errors


def _v2_removed_analysis_field_errors(document: Mapping[str, Any]) -> list[str]:
    if document.get("schema_version") != SCHEMA_VERSION:
        return []
    return _v2_segment_subwindow_errors(document)


def _business_sample_gaps(
    plan: Mapping[str, Any],
    denominators: Mapping[str, Any],
    platform_count: int,
) -> list[str]:
    target = plan["sample_target"]
    gaps: list[str] = []
    total_valid = int(denominators.get("N_union_mixed_window") or 0)
    total_min = int(target["total_valid_min"])
    if total_valid < total_min:
        gaps.append(
            f"总有效留言（{total_valid:,}/{total_min:,}，缺{total_min - total_valid:,}条）"
        )
    denominator_keys = {
        CATEGORY_SCOPE: "N_category_30d",
        **{
            scope_id: f"N_segment_{index}_90d"
            for index, scope_id in enumerate(SEGMENT_SCOPES, start=1)
        },
    }
    for scope_id, scope_target in target["per_scope"].items():
        actual = int(denominators.get(denominator_keys[scope_id]) or 0)
        required = int(scope_target["valid_min"])
        if actual < required:
            label = (
                "全品类30天"
                if scope_id == CATEGORY_SCOPE
                else f"Top{scope_id[8]}细分90天"
            )
            gaps.append(
                f"{label}（{actual:,}/{required:,}，缺{required - actual:,}条）"
            )
    platform_min = int(target["min_platforms"])
    if platform_count < platform_min:
        gaps.append(
            f"有效平台（{platform_count}/{platform_min}，缺{platform_min - platform_count}个）"
        )
    return gaps


def _sample_gate_gaps(analysis: Mapping[str, Any]) -> list[str]:
    plan = _research_plan(analysis)
    denominators = (
        analysis.get("denominators")
        if isinstance(analysis.get("denominators"), Mapping)
        else {}
    )
    quality = analysis.get("scope_quality")
    union_quality = next(
        (
            item
            for item in (quality if isinstance(quality, list) else [])
            if isinstance(item, Mapping)
            and item.get("scope_id") == "union_mixed_window"
        ),
        {},
    )
    return _business_sample_gaps(
        plan, denominators, int(union_quality.get("platform_count") or 0)
    )


def _nullable_nonnegative_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _nullable_nonnegative_integer(value: Any) -> int | None:
    number = _nullable_nonnegative_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _load_collection_receipt(coding_path: Path | None) -> Mapping[str, Any] | None:
    if coding_path is None:
        return None
    receipt_path = coding_path.resolve().parent / "collection_receipt.json"
    if not receipt_path.is_file():
        return None
    receipt = _load_json(receipt_path)
    if not isinstance(receipt, Mapping):
        raise ContractError("collection_receipt.json 顶层必须是对象")
    return receipt


def _collection_receipt_provenance_errors(
    receipt: Mapping[str, Any],
    *,
    coding_path: Path,
    research_plan: Mapping[str, Any],
) -> list[str]:
    """Bind an adjacent receipt to the exact coding run being analyzed."""
    errors: list[str] = []
    task_id = str(receipt.get("task_id") or "").strip()
    if not task_id:
        errors.append("collection_receipt.task_id必须为非空任务标识")

    raw_run_dir = str(receipt.get("run_dir") or "").strip()
    if not raw_run_dir:
        errors.append("collection_receipt.run_dir缺失")
    else:
        receipt_run_dir = Path(raw_run_dir).expanduser()
        if not receipt_run_dir.is_absolute():
            errors.append("collection_receipt.run_dir必须是绝对路径")
        elif receipt_run_dir.resolve() != coding_path.resolve().parent:
            errors.append(
                "collection_receipt.run_dir与social_voice_coding.json所在任务目录不一致"
            )

    receipt_plan = receipt.get("research_plan")
    if not isinstance(receipt_plan, Mapping):
        errors.append("collection_receipt.research_plan缺失或不是对象")
    elif dict(receipt_plan) != dict(research_plan):
        errors.append("collection_receipt.research_plan与本轮研究档位计划不一致")
    return errors


def _collection_receipt_summary(
    *,
    coding_path: Path | None,
    research_plan: Mapping[str, Any],
    denominators: Mapping[str, Any],
    collection_funnel: Mapping[str, Any],
) -> dict[str, Any]:
    receipt = _load_collection_receipt(coding_path)
    if receipt is not None and coding_path is not None:
        provenance_errors = _collection_receipt_provenance_errors(
            receipt,
            coding_path=coding_path,
            research_plan=research_plan,
        )
        if provenance_errors:
            raise ContractError(
                "collection_receipt.json不属于本轮消费者声音任务",
                provenance_errors,
            )
    target = research_plan["sample_target"]
    denominator_keys = {
        CATEGORY_SCOPE: "N_category_30d",
        **{
            scope_id: f"N_segment_{index}_90d"
            for index, scope_id in enumerate(SEGMENT_SCOPES, start=1)
        },
    }
    routes = []
    for scope_id, spec in target["per_scope"].items():
        actual = int(denominators.get(denominator_keys[scope_id]) or 0)
        minimum = int(spec["valid_min"])
        routes.append(
            {
                "scope_id": scope_id,
                "share": float(spec["share"]),
                "valid_min": minimum,
                "valid_max": int(spec["valid_max"]),
                "actual_valid": actual,
                "target_met": actual >= minimum,
            }
        )

    per_platform = collection_funnel.get("per_platform")
    valid_platforms = sum(
        1
        for item in (per_platform if isinstance(per_platform, list) else [])
        if isinstance(item, Mapping) and int(item.get("valid_voices") or 0) > 0
    )
    gaps = _business_sample_gaps(research_plan, denominators, valid_platforms)

    time_usage = (
        receipt.get("time_usage_minutes")
        if isinstance(receipt, Mapping)
        and isinstance(receipt.get("time_usage_minutes"), Mapping)
        else {}
    )
    raw_setup_wait = (
        time_usage.get("unmetered_human_setup_wait")
        if isinstance(time_usage.get("unmetered_human_setup_wait"), Mapping)
        else {}
    )
    setup_minutes = _nullable_nonnegative_number(raw_setup_wait.get("minutes"))
    raw_budget_gate = (
        receipt.get("budget_gate")
        if isinstance(receipt, Mapping)
        and isinstance(receipt.get("budget_gate"), Mapping)
        else {}
    )
    collection_minutes = _nullable_nonnegative_number(time_usage.get("collection"))
    total_minutes = _nullable_nonnegative_number(time_usage.get("total"))
    deadline_recorded = (
        receipt is not None
        and collection_minutes is not None
        and total_minutes is not None
        and isinstance(raw_budget_gate.get("deadline_exceeded"), bool)
        and isinstance(raw_budget_gate.get("finalization_only"), bool)
        and bool(str(raw_budget_gate.get("action") or "").strip())
    )

    raw_quota = (
        receipt.get("quota_and_cost")
        if isinstance(receipt, Mapping)
        and isinstance(receipt.get("quota_and_cost"), Mapping)
        else {}
    )
    raw_ledger = raw_quota.get("ledger")
    youtube_ledger = [
        item
        for item in (raw_ledger if isinstance(raw_ledger, list) else [])
        if isinstance(item, Mapping)
        and str(item.get("source") or "").casefold() == "youtube"
    ]
    cost_statuses = {
        str(item.get("cost_status") or "unknown") for item in youtube_ledger
    }
    youtube_actual = sum(
        float(item["amount"])
        for item in youtube_ledger
        if item.get("cost_status") == "provider_confirmed_actual"
        and _nullable_nonnegative_number(item.get("amount")) is not None
    )
    youtube_estimated = sum(
        float(item["amount"])
        for item in youtube_ledger
        if item.get("cost_status") == "estimated_from_price_snapshot"
        and _nullable_nonnegative_number(item.get("amount")) is not None
    )
    quota_units = (
        _nullable_nonnegative_integer(raw_quota.get("quota_units"))
        if receipt is not None
        else None
    )
    request_entries = (
        sum(int(item.get("request_entries") or 0) for item in youtube_ledger)
        if receipt is not None
        else None
    )
    if receipt is None:
        cost_classification = "not_recorded"
        interpretation = (
            "未找到本轮采集回执，YouTube配额和直接费用均未知；未知不等于0。"
        )
    elif len(cost_statuses) > 1:
        cost_classification = "mixed"
        interpretation = (
            "YouTube Data API按配额单位计量，配额不是美元费用；本轮同时存在多种成本口径，"
            "只展示采集回执中可核实的直接费用，未记录不等于0。"
        )
    elif "provider_confirmed_actual" in cost_statuses:
        cost_classification = "provider_actual"
        interpretation = "展示金额为提供方确认的YouTube通道直接费用；YouTube配额单位不等于美元。"
    elif "estimated_from_price_snapshot" in cost_statuses:
        cost_classification = "estimated"
        interpretation = "展示金额为按价格快照估算的YouTube通道直接费用；YouTube配额单位不等于美元。"
    elif "unknown" in cost_statuses:
        cost_classification = "unknown"
        interpretation = "YouTube通道直接费用未知，不能按0美元解释；YouTube配额单位不等于美元。"
    elif "not_metered" in cost_statuses:
        cost_classification = "not_metered"
        interpretation = "本轮通道未记录直接计费；本地计算与网络成本未计入，不能解释为总成本为0。"
    elif "quota_only" in cost_statuses or (quota_units or 0) > 0:
        cost_classification = "quota_only"
        interpretation = "YouTube Data API只记录配额用量，没有按请求计美元费用；配额单位不是美元。"
    else:
        cost_classification = "no_usage"
        interpretation = "本轮回执未记录YouTube API用量或直接费用；未知成本不能按0美元解释。"

    return {
        "available": receipt is not None,
        "target_attainment": {
            "target_met": not gaps,
            "total_valid": int(denominators.get("N_union_mixed_window") or 0),
            "total_valid_min": int(target["total_valid_min"]),
            "total_valid_max": int(target["total_valid_max"]),
            "valid_platforms": valid_platforms,
            "min_platforms": int(target["min_platforms"]),
            "routes": routes,
            "unmet_requirements": gaps,
        },
        "time_usage_minutes": {
            "collection": collection_minutes,
            "total": total_minutes,
            "unmetered_api_setup_wait": {
                "recorded": setup_minutes is not None,
                "minutes": setup_minutes,
                "included_in_collection_or_total": False,
            },
        },
        "deadline_status": {
            "recorded": deadline_recorded,
            "deadline_exceeded": (
                raw_budget_gate.get("deadline_exceeded")
                if deadline_recorded
                else None
            ),
            "finalization_only": (
                raw_budget_gate.get("finalization_only")
                if deadline_recorded
                else None
            ),
            "finalization_reserve_minutes": 5,
            "action": (
                str(raw_budget_gate.get("action")) if deadline_recorded else None
            ),
        },
        "youtube_quota_and_cost": {
            "usage_recorded": receipt is not None,
            "daily_quota_limit": (
                _nullable_nonnegative_integer(raw_quota.get("daily_quota_limit"))
                if receipt is not None
                else None
            ),
            "quota_units": quota_units,
            "request_entries": request_entries,
            "provider_confirmed_actual_cost_usd": (
                round(youtube_actual, 8)
                if "provider_confirmed_actual" in cost_statuses
                else None
            ),
            "estimated_direct_cost_usd": (
                round(youtube_estimated, 8)
                if "estimated_from_price_snapshot" in cost_statuses
                else None
            ),
            "cost_classification": cost_classification,
            "interpretation_zh": interpretation,
        },
    }


def _segment_definitions(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = document.get("segments")
    if source is None:
        source = document.get("selected_segments")
    if source is None and isinstance(document.get("research"), Mapping):
        source = document["research"].get("segments")
    if source is None:
        source = []
    if not isinstance(source, list):
        raise ContractError("segments 必须是数组")
    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for offset, raw in enumerate(source[:3], start=1):
        if not isinstance(raw, Mapping):
            raise ContractError("segments 中每一项都必须是对象")
        rank_value = raw.get("rank", offset)
        try:
            rank = int(rank_value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"segments[{offset - 1}].rank 必须是整数") from exc
        if rank not in (1, 2, 3):
            raise ContractError(f"segments[{offset - 1}].rank 必须为 1、2 或 3")
        scope_id = f"segment_{rank}_90d"
        declared_id = str(raw.get("segment_id") or raw.get("id") or scope_id).strip()
        if declared_id != scope_id:
            raise ContractError(
                f"segments[{offset - 1}].segment_id 必须为 {scope_id}"
            )
        if scope_id in used_ids:
            raise ContractError(f"segments 出现重复 rank：{rank}")
        used_ids.add(scope_id)
        try:
            listing_count = int(raw.get("listing_count", 0))
            listing_share = float(raw.get("listing_share", 0))
            sales_share = float(raw.get("sales_share", 0))
            supply_demand_index = float(raw.get("supply_demand_index", 0))
            dimension_rank = int(raw.get("dimension_rank", rank))
        except (TypeError, ValueError) as exc:
            raise ContractError(f"segments[{offset - 1}] 含无效数值字段") from exc
        synonyms = raw.get("synonyms", [])
        if not isinstance(synonyms, list) or any(
            not isinstance(value, str) for value in synonyms
        ):
            raise ContractError(f"segments[{offset - 1}].synonyms 必须是字符串数组")
        dimension = str(raw.get("dimension") or "").strip()
        feature = str(raw.get("feature") or "").strip()
        if not dimension or not feature:
            raise ContractError(f"segments[{offset - 1}] 必须包含dimension和feature")
        item = {
            "segment_id": scope_id,
            "rank": rank,
            "dimension": dimension,
            "feature": feature,
            "canonical_key": str(
                raw.get("canonical_key")
                or raw.get("semantic_key")
                or f"{_normalized_feature(dimension)}:{_normalized_feature(feature)}"
            ),
            "listing_count": listing_count,
            "listing_share": listing_share,
            "sales_share": sales_share,
            "supply_demand_index": supply_demand_index,
            "dimension_rank": dimension_rank,
            "synonyms": list(dict.fromkeys(value.strip() for value in synonyms if value.strip())),
        }
        result.append(item)
    result.sort(key=lambda item: item["rank"])
    return result


def _canonical_segment_aliases(segments: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for segment in segments:
        canonical = str(segment["segment_id"])
        candidates = {
            canonical,
            str(segment.get("segment_id") or ""),
            str(segment.get("feature") or ""),
            str(segment.get("name") or ""),
            str(segment.get("label") or ""),
        }
        for candidate in candidates:
            normalized = _normalized_feature(candidate)
            if normalized:
                aliases[normalized] = canonical
    return aliases


def _canonicalize_memberships(
    values: Any, aliases: Mapping[str, str]
) -> tuple[list[str], list[str]]:
    if values is None:
        return [], []
    if not isinstance(values, list):
        return [], ["segment_memberships 必须是数组"]
    result: list[str] = []
    errors: list[str] = []
    for raw in values:
        if isinstance(raw, Mapping):
            if not isinstance(raw.get("is_member"), bool):
                errors.append("segment membership对象缺少布尔值is_member")
                continue
            if raw.get("is_member") is not True:
                continue
            raw = raw.get("segment_id") or raw.get("id") or raw.get("feature")
        else:
            errors.append("segment_memberships只能包含对象")
            continue
        normalized = _normalized_feature(raw)
        canonical = aliases.get(normalized)
        if canonical is None and normalized in SEGMENT_IDS:
            canonical = normalized
        if canonical is None:
            errors.append(f"未知细分标签：{raw!r}")
            continue
        if canonical not in result:
            result.append(canonical)
    return result, errors


def _list_of_strings(value: Any, field: str) -> tuple[list[str], list[str]]:
    if not isinstance(value, list):
        return [], [f"{field} 必须是数组"]
    result: list[str] = []
    errors: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field} 只能包含非空字符串")
            continue
        normalized = item.strip()
        if normalized not in result:
            result.append(normalized)
    return result, errors


def _is_placeholder_feature(value: Any) -> bool:
    return _normalized_feature(value) in PLACEHOLDER_FEATURES


def _feature_canonical_map(analysis: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    trace = analysis.get("agent_trace")
    dictionary: Any = None
    if isinstance(trace, Mapping):
        dictionary = trace.get("normalization_dictionary")
    if dictionary is None:
        dictionary = analysis.get("normalization_dictionary")
    if not isinstance(dictionary, list):
        return result
    for item in dictionary:
        if not isinstance(item, Mapping):
            continue
        dimension = _normalized_feature(item.get("dimension"))
        display = _normalized_feature(item.get("display_value"))
        canonical = _normalized_feature(
            item.get("upper_group")
            or item.get("standard_value")
            or item.get("display_value")
        )
        if dimension and display and canonical:
            result[(dimension, display)] = canonical
    return result


def _feature_synonyms_by_semantic_key(
    analysis: Mapping[str, Any],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    trace = analysis.get("agent_trace")
    dictionary: Any = None
    if isinstance(trace, Mapping):
        dictionary = trace.get("normalization_dictionary")
    if dictionary is None:
        dictionary = analysis.get("normalization_dictionary")
    if not isinstance(dictionary, list):
        return result
    for item in dictionary:
        if not isinstance(item, Mapping):
            continue
        dimension = str(item.get("dimension") or "").strip()
        canonical = str(
            item.get("upper_group")
            or item.get("standard_value")
            or item.get("display_value")
            or ""
        ).strip()
        normalized_dimension = _normalized_feature(dimension)
        normalized_canonical = _normalized_feature(canonical)
        if not normalized_dimension or not normalized_canonical:
            continue
        semantic_key = f"{normalized_dimension}:{normalized_canonical}"
        for field in ("raw_value", "standard_value", "display_value", "upper_group"):
            label = str(item.get(field) or "").strip()
            if label and not _is_placeholder_feature(label):
                result[semantic_key].add(label)
    return result


def select_segments(analysis: Mapping[str, Any]) -> dict[str, Any]:
    features = analysis.get("feature_distribution")
    statuses = analysis.get("dimension_statuses")
    if not isinstance(features, list):
        raise ContractError("07_opportunity_analysis.json 缺少 feature_distribution 数组")
    if not isinstance(statuses, list):
        raise ContractError("07_opportunity_analysis.json 缺少 dimension_statuses 数组")

    valid_dimensions: dict[str, bool] = {}
    status_rank: dict[str, int] = {}
    for offset, status in enumerate(statuses, start=1):
        if not isinstance(status, Mapping):
            continue
        name = str(status.get("dimension") or "").strip()
        if not name:
            continue
        valid_dimensions[name] = status.get("valid") is True
        status_rank[name] = offset

    dimension_rank: dict[str, int] = dict(status_rank)

    canonical_map = _feature_canonical_map(analysis)
    candidates: list[dict[str, Any]] = []
    excluded = Counter()
    errors: list[str] = []
    for offset, raw in enumerate(features):
        if not isinstance(raw, Mapping):
            errors.append(f"feature_distribution[{offset}] 不是对象")
            continue
        dimension = str(raw.get("dimension") or "").strip()
        feature = str(raw.get("feature") or "").strip()
        if not dimension or not feature:
            excluded["missing_dimension_or_feature"] += 1
            continue
        if valid_dimensions.get(dimension) is not True:
            excluded["invalid_dimension"] += 1
            continue
        if raw.get("is_effective_feature") is not True:
            excluded["ineffective_feature"] += 1
            continue
        if _is_placeholder_feature(feature):
            excluded["placeholder_feature"] += 1
            continue
        try:
            share = _as_number(raw.get("listing_share"), f"feature_distribution[{offset}].listing_share")
            if 1 < share <= 100:
                share /= 100.0
            if not 0 <= share <= 1:
                raise ValueError("listing_share 必须位于 0-1（或 0-100 百分数）")
            supply_demand = _as_number(
                raw.get("supply_demand_index"),
                f"feature_distribution[{offset}].supply_demand_index",
            )
            listing_count = int(
                _as_number(raw.get("listing_count", 0), f"feature_distribution[{offset}].listing_count")
            )
            sales_share = _as_number(
                raw.get("sales_share", 0), f"feature_distribution[{offset}].sales_share"
            )
            if 1 < sales_share <= 100:
                sales_share /= 100.0
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if share < 0.03 or share > 0.20:
            excluded["outside_3_to_20_percent"] += 1
            continue
        normalized_dimension = _normalized_feature(dimension)
        normalized_display = _normalized_feature(feature)
        semantic = canonical_map.get(
            (normalized_dimension, normalized_display), normalized_display
        )
        item = dict(raw)
        item.update(
            {
                "dimension": dimension,
                "feature": feature,
                "listing_share": share,
                "sales_share": sales_share,
                "listing_count": listing_count,
                "supply_demand_index": supply_demand,
                "dimension_rank": dimension_rank.get(dimension, 10**9),
                "semantic_key": f"{normalized_dimension}:{semantic}",
            }
        )
        candidates.append(item)
    if errors:
        raise ContractError("机会分析中存在无法计算的字段", errors[:50])

    candidates.sort(
        key=lambda item: (
            -item["supply_demand_index"],
            -item["listing_count"],
            -item["sales_share"],
            item["dimension_rank"],
            _normalized_feature(item["dimension"]),
            _normalized_feature(item["feature"]),
        )
    )
    semantic_synonyms = _feature_synonyms_by_semantic_key(analysis)
    for item in candidates:
        semantic_synonyms[item["semantic_key"]].add(item["feature"])

    selected: list[dict[str, Any]] = []
    seen_semantic_keys: set[str] = set()
    semantic_duplicates: list[dict[str, Any]] = []
    for item in candidates:
        if item["semantic_key"] in seen_semantic_keys:
            semantic_duplicates.append(
                {
                    "dimension": item["dimension"],
                    "feature": item["feature"],
                    "semantic_key": item["semantic_key"],
                }
            )
            continue
        seen_semantic_keys.add(item["semantic_key"])
        if len(selected) < 3:
            output_item = {
                "segment_id": f"segment_{len(selected) + 1}_90d",
                "rank": len(selected) + 1,
                "dimension": item["dimension"],
                "feature": item["feature"],
                "canonical_key": item["semantic_key"],
                "listing_count": item["listing_count"],
                "listing_share": item["listing_share"],
                "sales_share": item["sales_share"],
                "supply_demand_index": item["supply_demand_index"],
                "dimension_rank": item["dimension_rank"],
                "synonyms": sorted(
                    label
                    for label in semantic_synonyms.get(item["semantic_key"], set())
                    if _normalized_feature(label)
                    != _normalized_feature(item["feature"])
                ),
            }
            selected.append(output_item)

    selected_rows = {
        (item["dimension"], item["feature"], item["canonical_key"]) for item in selected
    }
    kept_semantic_rows: dict[str, tuple[str, str]] = {}
    for item in candidates:
        kept_semantic_rows.setdefault(
            item["semantic_key"], (item["dimension"], item["feature"])
        )
    ranked_candidates = [
        {
            "dimension": item["dimension"],
            "feature": item["feature"],
            "canonical_key": item["semantic_key"],
            "dimension_valid": True,
            "is_effective_feature": True,
            "listing_count": item["listing_count"],
            "listing_share": item["listing_share"],
            "sales_share": item["sales_share"],
            "supply_demand_index": item["supply_demand_index"],
            "dimension_rank": item["dimension_rank"],
            "eligible": kept_semantic_rows[item["semantic_key"]]
            == (item["dimension"], item["feature"]),
            "selected": (
                item["dimension"], item["feature"], item["semantic_key"]
            )
            in selected_rows,
            "exclusion_reasons": (
                []
                if kept_semantic_rows[item["semantic_key"]]
                == (item["dimension"], item["feature"])
                else ["semantic_duplicate_of_kept_canonical_row"]
            ),
        }
        for item in candidates
    ]
    top3_selection = {
        "source_field": "07_opportunity_analysis.json.feature_distribution",
        "dimension_status_source_field": "07_opportunity_analysis.json.dimension_statuses",
        "listing_share_min": 0.03,
        "listing_share_max": 0.20,
        "boundaries_inclusive": True,
        "required_dimension_valid": True,
        "required_effective_feature": True,
        "excluded_feature_values": sorted(value for value in PLACEHOLDER_FEATURES if value),
        "sort_order": [
            "supply_demand_index:desc",
            "listing_count:desc",
            "sales_share:desc",
            "dimension_rank:asc",
            "dimension_feature_name:asc",
        ],
        "candidate_count_before_filter": len(features),
        "candidate_count_after_filter": len(candidates),
        "normalization_decisions": [
            {
                "canonical_key": item["semantic_key"],
                "kept_label": next(
                    (
                        candidate["feature"]
                        for candidate in candidates
                        if candidate["semantic_key"] == item["semantic_key"]
                    ),
                    item["feature"],
                ),
                "merged_labels": [item["feature"]],
                "reason": "依据agent归一化字典中的upper_group做同义/父子语义去重。",
            }
            for item in semantic_duplicates
        ],
        "ranked_candidates": ranked_candidates,
        "selected_segment_ids": [item["segment_id"] for item in selected],
        "unavailable_ranks": list(range(len(selected) + 1, 4)),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "source": {
            "marketplace": analysis.get("marketplace"),
            "keyword": analysis.get("keyword"),
            "category_node": analysis.get("category_node"),
        },
        "criteria": {
            "source_field": "feature_distribution",
            "valid_dimension_required": True,
            "effective_feature_required": True,
            "placeholder_features_excluded": True,
            "listing_share_min": 0.03,
            "listing_share_max": 0.20,
            "boundaries_inclusive": True,
            "limit": 3,
            "primary_sort": "supply_demand_index_desc",
            "tie_breakers": [
                "listing_count_desc",
                "sales_share_desc",
                "dimension_rank_asc",
                "dimension_name_asc",
                "feature_name_asc",
            ],
            "semantic_dedupe_source": "agent_trace.normalization_dictionary.upper_group",
            "threshold_relaxed_when_insufficient": False,
        },
        "candidate_count_before_semantic_dedupe": len(candidates),
        "semantic_duplicate_count": len(semantic_duplicates),
        "semantic_duplicates": semantic_duplicates,
        "selected_count": len(selected),
        "selection_complete": len(selected) == 3,
        "selected_segments": selected,
        "top3_selection": top3_selection,
        "excluded_counts": dict(sorted(excluded.items())),
    }


def _voice_quote(voice: Mapping[str, Any]) -> str:
    return str(
        voice.get("excerpt")
        or voice.get("quote")
        or voice.get("evidence_quote")
        or voice.get("text")
        or ""
    ).strip()


def _voice_coding(voice: Mapping[str, Any]) -> Mapping[str, Any]:
    coding = voice.get("coding")
    return coding if isinstance(coding, Mapping) else {}


def _voice_tag_source(voice: Mapping[str, Any], field: str) -> Any:
    coding = _voice_coding(voice)
    aliases = {
        "scenarios": "use_scenes",
        "personas": "persona_tags",
        "needs": "need_codes",
        "satisfactions": "satisfaction_codes",
        "dissatisfactions": "dissatisfaction_codes",
        "ideas": "innovation_signals",
        "kano_evidence": "kano_evidence",
    }
    nested_name = aliases.get(field, field)
    if nested_name in coding:
        return coding.get(nested_name)
    return voice.get(field)


def _comment_permalink(value: Any, platform: str) -> str:
    normalized = _normalize_url(value)
    if not normalized:
        return ""
    try:
        parts = urlsplit(str(value))
    except ValueError:
        return ""
    query = {key.casefold(): item for key, item in parse_qsl(parts.query)}
    if any(query.get(key) for key in ("comment", "comment_id", "reply", "reply_id", "lc")):
        return normalized
    path_parts = [item for item in parts.path.split("/") if item]
    lowered = [item.casefold() for item in path_parts]
    if platform == "reddit" and "comments" in lowered:
        comments_index = lowered.index("comments")
        # /comments/<post-id>/<slug>/<comment-id> 才是评论级直链。
        if len(path_parts) >= comments_index + 4:
            return normalized
    return ""


def _dedupe_keys(voice: Mapping[str, Any]) -> list[str]:
    """Return hard message identity keys; never dedupe on text or semantics alone."""
    platform = _normalized_feature(voice.get("platform"))
    content_id = str(voice.get("content_id") or "").strip()
    keys: list[str] = []
    if platform and content_id:
        keys.append(f"content:{platform}:{content_id}")
    permalink = _comment_permalink(
        voice.get("normalized_url") or voice.get("url") or voice.get("source_url"),
        platform,
    )
    if platform and permalink:
        keys.append(f"comment-url:{platform}:{permalink}")
    if keys:
        return keys
    parent_id = str(
        voice.get("parent_content_id")
        or voice.get("parent_id")
        or voice.get("thread_id")
        or ""
    ).strip()
    author = str(voice.get("author_hash") or voice.get("author_label") or "").strip()
    published_at = str(voice.get("published_at") or "").strip()
    exact_text = unicodedata.normalize("NFKC", _voice_quote(voice)).strip()
    if platform and parent_id and author and published_at and exact_text:
        composite = json.dumps(
            [platform, parent_id, author, published_at, exact_text],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(composite.encode("utf-8")).hexdigest()
        return [f"fallback-composite:{digest}"]
    return []


def _stable_union(existing: Any, incoming: Any) -> list[Any]:
    result: list[Any] = []
    for source in (existing, incoming):
        if not isinstance(source, list):
            continue
        for item in source:
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if all(
                json.dumps(known, ensure_ascii=False, sort_keys=True, default=str) != marker
                for known in result
            ):
                result.append(copy.deepcopy(item))
    return result


def _merge_voices(primary: dict[str, Any], duplicate: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(primary)
    for field in (
        "collection_scopes",
        "query_ids",
        "segment_memberships",
        "scenarios",
        "needs",
        "satisfactions",
        "dissatisfactions",
        "ideas",
        "kano",
        "kano_evidence",
        "discoveries",
    ):
        merged[field] = _stable_union(merged.get(field), duplicate.get(field))
    duplicate_ids = merged.get("merged_voice_ids")
    if not isinstance(duplicate_ids, list):
        duplicate_ids = []
    for value in (duplicate.get("voice_id"), *duplicate.get("merged_voice_ids", [])):
        if isinstance(value, str) and value and value != merged.get("voice_id"):
            if value not in duplicate_ids:
                duplicate_ids.append(value)
    merged["merged_voice_ids"] = duplicate_ids
    primary_coding = dict(_voice_coding(merged))
    duplicate_coding = _voice_coding(duplicate)
    for field in (
        "use_scenes",
        "persona_tags",
        "need_codes",
        "satisfaction_codes",
        "dissatisfaction_codes",
        "innovation_signals",
        "kano_evidence",
    ):
        primary_coding[field] = _stable_union(
            primary_coding.get(field), duplicate_coding.get(field)
        )
    merged["coding"] = primary_coding
    return merged


def _deduplicate_voices(
    voices: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    key_to_index: dict[str, int] = {}
    duplicate_pairs: list[dict[str, Any]] = []
    for raw in voices:
        voice = copy.deepcopy(dict(raw))
        keys = _dedupe_keys(voice)
        matching_indexes: set[int] = set()
        for key in keys:
            known_index = key_to_index.get(key)
            if known_index is None:
                continue
            if key.startswith("comment-url:"):
                known_content_id = str(unique[known_index].get("content_id") or "").strip()
                current_content_id = str(voice.get("content_id") or "").strip()
                if (
                    known_content_id
                    and current_content_id
                    and known_content_id != current_content_id
                ):
                    continue
            matching_indexes.add(known_index)
        matching = sorted(matching_indexes)
        if not matching:
            index = len(unique)
            unique.append(voice)
            for key in keys:
                key_to_index[key] = index
            continue
        target_index = matching[0]
        primary = unique[target_index]
        duplicate_pairs.append(
            {
                "kept_voice_id": primary.get("voice_id"),
                "merged_voice_id": voice.get("voice_id"),
                "matching_keys": [key for key in keys if key_to_index.get(key) in matching],
            }
        )
        unique[target_index] = _merge_voices(primary, voice)
        for key in _dedupe_keys(unique[target_index]):
            key_to_index[key] = target_index
        for extra_index in reversed(matching[1:]):
            unique[target_index] = _merge_voices(unique[target_index], unique[extra_index])
            unique.pop(extra_index)
            key_to_index = {}
            for index, known in enumerate(unique):
                for key in _dedupe_keys(known):
                    key_to_index[key] = index
            target_index = min(target_index, extra_index)
    return unique, {
        "raw_voice_count": len(voices),
        "deduplicated_voice_count": len(unique),
        "duplicate_count": len(voices) - len(unique),
        "duplicate_pairs": duplicate_pairs,
        "automatic_methods": [
            "platform+content_id",
            "platform+comment_permalink",
            "platform+parent_content_id+author+published_at+exact_text",
        ],
        "automatic_text_hash": False,
        "automatic_near_text_similarity": False,
    }


def _validate_voice(
    voice: dict[str, Any],
    index: int,
    *,
    end_at: datetime,
    aliases: Mapping[str, str],
    schema_version: str,
) -> tuple[list[str], list[str]]:
    prefix = f"voices[{index}]"
    errors: list[str] = []
    warnings: list[str] = []
    eligible = voice.get("eligible_for_quantitation")
    if not isinstance(eligible, bool):
        errors.append(f"{prefix}.eligible_for_quantitation 必须是布尔值")
        eligible = False
    exclusion_reasons = voice.get("exclusion_reasons")
    if not isinstance(exclusion_reasons, list):
        errors.append(f"{prefix}.exclusion_reasons 必须是数组")
    elif not eligible and not exclusion_reasons:
        errors.append(f"{prefix} 不进入量化时必须填写 exclusion_reasons")
    required_nonempty = (
        "voice_id",
        "platform",
        "backend",
        "content_type",
        "author_hash",
        "author_identity_status",
        "collected_at",
        "language",
        "normalized_url",
        "actor_type",
    )
    if schema_version == LEGACY_SCHEMA_VERSION:
        required_nonempty = (*required_nonempty, "content_id")
    if eligible:
        required_nonempty = (*required_nonempty, "published_at")
    for field in required_nonempty:
        if not isinstance(voice.get(field), str) or not voice[field].strip():
            errors.append(f"{prefix}.{field} 必须是非空字符串")
    for nullable_key in ("thread_id", "author_label"):
        if nullable_key not in voice:
            errors.append(f"{prefix} 必须包含 {nullable_key}")
        elif voice.get(nullable_key) is not None and not isinstance(
            voice.get(nullable_key), str
        ):
            errors.append(f"{prefix}.{nullable_key} 必须为字符串或null")
    for nullable_key in ("parent_id", "region_hint"):
        if nullable_key not in voice:
            errors.append(f"{prefix} 必须显式包含 {nullable_key}（未知时填 null）")
    quote = _voice_quote(voice)
    if not quote:
        errors.append(f"{prefix}.quote 必须是非空原声证据")
    if not isinstance(voice.get("summary_zh"), str) or not voice["summary_zh"].strip():
        errors.append(f"{prefix}.summary_zh 必须是非空中文摘要")
    if not isinstance(voice.get("engagement"), Mapping):
        errors.append(f"{prefix}.engagement 必须是对象")
    if not isinstance(voice.get("discoveries"), list) or not voice.get("discoveries"):
        errors.append(f"{prefix}.discoveries 必须是数组")
    if eligible is not True:
        errors.append(f"{prefix} 中只允许 eligible_for_quantitation=true 的canonical量化记录")
    if voice.get("actor_type") != "consumer":
        errors.append(f"{prefix}.actor_type 必须为 consumer；推广/品牌内容应进入excluded_records")
    if isinstance(exclusion_reasons, list) and exclusion_reasons:
        errors.append(f"{prefix}.exclusion_reasons 必须为空数组；排除记录应进入excluded_records")
    coding = voice.get("coding")
    if not isinstance(coding, Mapping):
        errors.append(f"{prefix}.coding 必须是对象")
        coding = {}
    for field in (
        "use_scenes",
        "persona_tags",
        "need_codes",
        "satisfaction_codes",
        "dissatisfaction_codes",
        "innovation_signals",
        "kano_evidence",
    ):
        if not isinstance(coding.get(field), list):
            errors.append(f"{prefix}.coding.{field} 必须是数组")
    if "sentiment" not in coding:
        errors.append(f"{prefix}.coding 缺少 sentiment")
    if "evidence_confidence" not in coding:
        errors.append(f"{prefix}.coding 缺少 evidence_confidence")
    if coding.get("coding_notes") is not None and not isinstance(
        coding.get("coding_notes"), str
    ):
        errors.append(f"{prefix}.coding.coding_notes 必须是字符串或null")
    kano_evidence = coding.get("kano_evidence")
    if isinstance(kano_evidence, list):
        for kano_index, evidence in enumerate(kano_evidence):
            if not isinstance(evidence, Mapping):
                errors.append(f"{prefix}.coding.kano_evidence[{kano_index}] 必须是对象")
                continue
            evidence_type = evidence.get("evidence_type")
            if evidence_type in {"explicit_indifference"}:
                continue
            if evidence_type in {"explicit_rejection", "harm_or_negative_utility"}:
                continue
            explicit_class = _canonical_kano(
                evidence.get("classification") or evidence.get("kano_type")
            )
            if explicit_class == "I":
                errors.append(
                    f"{prefix}.coding.kano_evidence[{kano_index}] 的I类必须有explicit_indifference证据"
                )
            if explicit_class == "R":
                errors.append(
                    f"{prefix}.coding.kano_evidence[{kano_index}] 的R类必须有explicit_rejection或harm_or_negative_utility证据"
                )

    scopes, scope_errors = _list_of_strings(
        voice.get("collection_scopes"), f"{prefix}.collection_scopes"
    )
    errors.extend(scope_errors)
    unknown_scopes = sorted(set(scopes) - ALLOWED_SCOPES)
    if unknown_scopes:
        errors.append(f"{prefix}.collection_scopes 含未知值：{unknown_scopes}")
    if eligible and not scopes:
        errors.append(f"{prefix}.collection_scopes 至少包含一个采集范围")
    voice["collection_scopes"] = [scope for scope in scopes if scope in ALLOWED_SCOPES]

    query_ids, query_errors = _list_of_strings(voice.get("query_ids"), f"{prefix}.query_ids")
    errors.extend(query_errors)
    if eligible and not query_ids:
        errors.append(f"{prefix}.query_ids 至少包含一个查询ID")
    voice["query_ids"] = query_ids

    memberships, membership_errors = _canonicalize_memberships(
        voice.get("segment_memberships"), aliases
    )
    errors.extend(f"{prefix}.segment_memberships {message}" for message in membership_errors)
    voice["segment_memberships"] = memberships

    published_at: datetime | None = None
    collected_at: datetime | None = None
    if voice.get("published_at") not in (None, ""):
        try:
            published_at = _parse_datetime(voice.get("published_at"), f"{prefix}.published_at")
            voice["published_at"] = _iso(published_at)
        except ValueError as exc:
            errors.append(str(exc))
    elif eligible:
        errors.append(f"{prefix}.published_at 量化记录必须有带时区时间")
    try:
        collected_at = _parse_datetime(voice.get("collected_at"), f"{prefix}.collected_at")
        voice["collected_at"] = _iso(collected_at)
    except ValueError as exc:
        errors.append(str(exc))

    if published_at is not None and eligible:
        start_30 = end_at - timedelta(days=30)
        start_90 = end_at - timedelta(days=90)
        if published_at >= end_at:
            errors.append(f"{prefix}.published_at 必须早于统一 end_at（右开区间）")
        if CATEGORY_SCOPE in scopes and not (start_30 <= published_at < end_at):
            errors.append(f"{prefix} 属于 category_30d，但发布时间不在 [end_at-30天, end_at)")
        if any(scope in SEGMENT_SCOPES for scope in scopes) and not (
            start_90 <= published_at < end_at
        ):
            errors.append(f"{prefix} 属于细分90天采集，但发布时间不在 [end_at-90天, end_at)")
        if published_at < start_90:
            errors.append(f"{prefix}.published_at 早于整个研究的90天窗口")
        if schema_version == LEGACY_SCHEMA_VERSION:
            computed_recent = start_30 <= published_at < end_at
            if "is_recent_30d" in voice and voice["is_recent_30d"] is not computed_recent:
                errors.append(f"{prefix}.is_recent_30d 与发布时间重算结果不一致")
            voice["is_recent_30d"] = computed_recent
            computed_bucket = "recent_30d" if computed_recent else "days_31_90"
            if "period_bucket" in voice and voice["period_bucket"] != computed_bucket:
                errors.append(f"{prefix}.period_bucket 与发布时间重算结果不一致")
            voice["period_bucket"] = computed_bucket
            expected_buckets = [computed_bucket]
            supplied_buckets = voice.get("temporal_buckets")
            if supplied_buckets is not None:
                if not isinstance(supplied_buckets, list):
                    errors.append(f"{prefix}.temporal_buckets 必须是数组")
                elif len(supplied_buckets) != 1:
                    errors.append(f"{prefix}.temporal_buckets 必须恰好包含一个时间桶")
                elif expected_buckets != supplied_buckets:
                    errors.append(f"{prefix}.temporal_buckets 与发布时间不一致")
            voice["temporal_buckets"] = expected_buckets
    if published_at is not None and collected_at is not None and collected_at < published_at:
        warnings.append(f"{prefix}.collected_at 早于 published_at，请核对平台时间")

    normalized_url = _normalize_url(voice.get("normalized_url") or voice.get("url"))
    if not normalized_url.startswith(("https://", "http://")):
        errors.append(f"{prefix}.url 必须是绝对 http(s) 证据链接")
    voice["normalized_url"] = normalized_url
    if schema_version == SCHEMA_VERSION and not _dedupe_keys(voice):
        errors.append(
            f"{prefix} 缺少硬去重身份：需提供content_id、评论级直链，或父内容+作者+时间+原文复合键"
        )
    # The contract intentionally keeps dedupe metadata at top-level
    # ``dedup_groups``; per-voice ``dedupe`` is not a schema field.  Duplicate
    # checks below use stable IDs, normalized URLs and text hashes directly.
    return errors, warnings


def validate_coding_document(
    document: Mapping[str, Any], *, reject_duplicates: bool = True
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(document, Mapping):
        raise ContractError("编码文件顶层必须是对象")
    _validate_against_schema(
        document,
        Path(__file__).resolve().parent.parent
        / "references"
        / "social_voice_coding.schema.json",
        "消费者声音编码",
    )
    normalized = copy.deepcopy(dict(document))
    schema_version = str(normalized.get("schema_version") or "")
    end_at = _document_end_at(normalized)
    segments = _segment_definitions(normalized)
    aliases = _canonical_segment_aliases(segments)
    voices = _document_voices(normalized)
    errors: list[str] = _v2_removed_coding_field_errors(normalized)
    warnings: list[str] = []
    required_top_level = (
        "schema_version",
        "project",
        "generated_at",
        "end_at",
        "windows",
        "top3_selection",
        "segments",
        "query_plan",
        "source_runs",
        "agent_reach_health",
        "need_dictionary",
        "voices",
        "dedup_groups",
        "excluded_records",
        "llm_calls",
    )
    if schema_version == SCHEMA_VERSION:
        required_top_level = (
            *required_top_level,
            "research_plan",
            "collection_funnel",
            "stop_reason",
        )
    for field in required_top_level:
        if field not in normalized:
            errors.append(f"编码文件缺少顶层字段：{field}")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"schema_version 必须为 {LEGACY_SCHEMA_VERSION} 或 {SCHEMA_VERSION}"
        )
    for field in ("source_runs", "need_dictionary", "dedup_groups", "excluded_records", "llm_calls"):
        if field in normalized and not isinstance(normalized.get(field), list):
            errors.append(f"顶层 {field} 必须是数组")
    for field in (
        "project",
        "windows",
        "top3_selection",
        "query_plan",
        "agent_reach_health",
        "research_plan",
        "collection_funnel",
    ):
        if field in normalized and not isinstance(normalized.get(field), Mapping):
            errors.append(f"顶层 {field} 必须是对象")
    try:
        _parse_datetime(normalized.get("generated_at"), "generated_at")
    except ValueError as exc:
        errors.append(str(exc))
    segment_ids = [segment["segment_id"] for segment in segments]
    segment_ranks = [segment["rank"] for segment in segments]
    if len(segment_ids) != len(set(segment_ids)) or len(segment_ranks) != len(set(segment_ranks)):
        errors.append("segments 的 segment_id 与 rank 必须分别唯一")
    top3_selection = normalized.get("top3_selection")
    if isinstance(top3_selection, Mapping):
        unavailable = top3_selection.get("unavailable_ranks")
        expected_unavailable = sorted(set((1, 2, 3)) - set(segment_ranks))
        if not isinstance(unavailable, list) or sorted(unavailable) != expected_unavailable:
            errors.append(
                f"top3_selection.unavailable_ranks 必须准确列出缺失rank：{expected_unavailable}"
            )
        selected_ids = top3_selection.get("selected_segment_ids")
        if selected_ids is not None and selected_ids != segment_ids:
            errors.append("top3_selection.selected_segment_ids 必须与segments顺序完全一致")
    query_plan = normalized.get("query_plan")
    known_query_ids: set[str] = set()
    query_scope_ids: dict[str, set[str]] = {}
    if isinstance(query_plan, Mapping):
        primary_lanes = query_plan.get("primary_lanes")
        if not isinstance(primary_lanes, list):
            errors.append("query_plan.primary_lanes 必须是数组")
            primary_lanes = []
        expected_scopes = [CATEGORY_SCOPE, *segment_ids]
        actual_scopes: list[str] = []
        expected_as_of = end_at.date().isoformat()
        for lane_index, lane in enumerate(primary_lanes):
            if not isinstance(lane, Mapping):
                errors.append(f"query_plan.primary_lanes[{lane_index}] 必须是对象")
                continue
            query_id = str(lane.get("query_id") or "")
            if not query_id or query_id in known_query_ids:
                errors.append(f"query_plan.primary_lanes[{lane_index}].query_id 缺失或重复")
            known_query_ids.add(query_id)
            scope_id = lane.get("scope_id")
            query_scope_ids[query_id] = {str(scope_id)} if scope_id else set()
            actual_scopes.append(scope_id)
            expected_days = 30 if scope_id == CATEGORY_SCOPE else 90
            if lane.get("days") != expected_days:
                errors.append(f"query lane {query_id!r} 的days必须为{expected_days}")
            if lane.get("as_of_utc_date") != expected_as_of:
                errors.append(f"query lane {query_id!r} 的as_of_utc_date必须为{expected_as_of}")
            try:
                lane_start = _parse_datetime(lane.get("start_at"), f"query lane {query_id}.start_at")
                lane_end = _parse_datetime(lane.get("end_at"), f"query lane {query_id}.end_at")
                if lane_end != end_at or lane_start != end_at - timedelta(days=expected_days):
                    errors.append(f"query lane {query_id!r} 必须与统一end_at及{expected_days}天窗口对齐")
            except ValueError as exc:
                errors.append(str(exc))
        if actual_scopes != expected_scopes:
            errors.append(f"query_plan.primary_lanes必须按顺序覆盖：{expected_scopes}")
        gap_fills = query_plan.get("gap_fill_queries")
        if isinstance(gap_fills, list):
            for gap_index, gap in enumerate(gap_fills):
                if not isinstance(gap, Mapping):
                    continue
                query_id = str(gap.get("query_id") or "")
                if not query_id or query_id in known_query_ids:
                    errors.append(
                        f"query_plan.gap_fill_queries[{gap_index}].query_id 缺失或重复"
                    )
                    continue
                known_query_ids.add(query_id)
                query_scope_ids[query_id] = {
                    str(scope_id) for scope_id in (gap.get("scope_ids") or [])
                }
    source_runs = normalized.get("source_runs")
    source_run_ids: set[str] = set()
    source_run_contracts: dict[str, tuple[set[str], set[str]]] = {}
    if isinstance(source_runs, list):
        for run_index, run in enumerate(source_runs):
            if not isinstance(run, Mapping):
                continue
            run_id = str(run.get("run_id") or "")
            if not run_id or run_id in source_run_ids:
                errors.append(f"source_runs[{run_index}].run_id 缺失或重复")
            source_run_ids.add(run_id)
            run_queries = run.get("query_ids")
            normalized_run_queries = {
                str(query_id) for query_id in run_queries
            } if isinstance(run_queries, list) else set()
            normalized_run_scopes = {
                str(scope_id) for scope_id in (run.get("scope_ids") or [])
            }
            source_run_contracts[run_id] = (
                normalized_run_queries,
                normalized_run_scopes,
            )
            if isinstance(run_queries, list):
                unknown = sorted(normalized_run_queries - known_query_ids)
                if unknown:
                    errors.append(f"source run {run_id!r} 引用了未知query_ids：{unknown}")
    need_dictionary = normalized.get("need_dictionary")
    known_need_codes: set[str] = set()
    if isinstance(need_dictionary, list):
        for need_index, item in enumerate(need_dictionary):
            if not isinstance(item, Mapping):
                continue
            code = str(item.get("need_code") or "")
            if not code or code in known_need_codes:
                errors.append(
                    f"need_dictionary[{need_index}].need_code 缺失或重复：{code!r}"
                )
            known_need_codes.add(code)
    seen_voice_ids: set[str] = set()
    seen_discovery_ids: set[str] = set()
    for index, voice in enumerate(voices):
        voice_errors, voice_warnings = _validate_voice(
            voice,
            index,
            end_at=end_at,
            aliases=aliases,
            schema_version=schema_version,
        )
        errors.extend(voice_errors)
        warnings.extend(voice_warnings)
        voice_id = str(voice.get("voice_id") or "")
        if voice_id in seen_voice_ids:
            errors.append(f"voices[{index}].voice_id 重复：{voice_id!r}")
        seen_voice_ids.add(voice_id)
        memberships = voice.get("segment_memberships")
        if isinstance(memberships, list) and len(memberships) != len(set(memberships)):
            errors.append(f"voices[{index}].segment_memberships 不得重复")
        unknown_queries = sorted(set(voice.get("query_ids") or []) - known_query_ids)
        if unknown_queries:
            errors.append(f"voices[{index}] 引用了未知query_ids：{unknown_queries}")
        for discovery_index, discovery in enumerate(voice.get("discoveries") or []):
            if not isinstance(discovery, Mapping):
                continue
            discovery_id = str(discovery.get("discovery_id") or "")
            if not discovery_id or discovery_id in seen_discovery_ids:
                errors.append(f"voices[{index}].discoveries[{discovery_index}] ID缺失或重复")
            seen_discovery_ids.add(discovery_id)
            discovery_query_id = str(discovery.get("query_id") or "")
            discovery_run_id = str(discovery.get("source_run_id") or "")
            discovery_scope_id = str(discovery.get("scope_id") or "")
            if discovery_query_id not in known_query_ids:
                errors.append(f"discovery {discovery_id!r} 引用了未知query_id")
            if discovery_run_id not in source_run_ids:
                errors.append(f"discovery {discovery_id!r} 引用了未知source_run_id")
            if discovery_scope_id not in ALLOWED_SCOPES:
                errors.append(f"discovery {discovery_id!r} 引用了未知scope_id")
            allowed_query_scopes = query_scope_ids.get(discovery_query_id, set())
            if allowed_query_scopes and discovery_scope_id not in allowed_query_scopes:
                errors.append(
                    f"discovery {discovery_id!r} 的scope_id不属于query "
                    f"{discovery_query_id!r}：{sorted(allowed_query_scopes)}"
                )
            run_queries, run_scopes = source_run_contracts.get(
                discovery_run_id, (set(), set())
            )
            if run_queries and discovery_query_id not in run_queries:
                errors.append(
                    f"discovery {discovery_id!r} 的query_id不属于source run "
                    f"{discovery_run_id!r}"
                )
            if run_scopes and discovery_scope_id not in run_scopes:
                errors.append(
                    f"discovery {discovery_id!r} 的scope_id不属于source run "
                    f"{discovery_run_id!r}"
                )
            if discovery_query_id not in set(voice.get("query_ids") or []):
                errors.append(
                    f"discovery {discovery_id!r} 的query_id未汇总到voice.query_ids"
                )
            if discovery_scope_id not in set(voice.get("collection_scopes") or []):
                errors.append(
                    f"discovery {discovery_id!r} 的scope_id未汇总到voice.collection_scopes"
                )
        coding = _voice_coding(voice)
        for code_field in (
            "need_codes",
            "satisfaction_codes",
            "dissatisfaction_codes",
        ):
            codes = coding.get(code_field)
            if isinstance(codes, list):
                unknown_codes = sorted(
                    str(code) for code in codes if str(code) not in known_need_codes
                )
                if unknown_codes:
                    errors.append(
                        f"voices[{index}].coding.{code_field} 引用了未定义need_code：{unknown_codes}"
                    )
        for object_field in ("innovation_signals", "kano_evidence"):
            entries = coding.get(object_field)
            if not isinstance(entries, list):
                continue
            for entry_index, entry in enumerate(entries):
                if not isinstance(entry, Mapping):
                    continue
                code = str(entry.get("need_code") or "")
                if code not in known_need_codes:
                    errors.append(
                        f"voices[{index}].coding.{object_field}[{entry_index}] 引用了未定义need_code：{code!r}"
                    )

    errors.extend(_validate_collection_contract(normalized, voices))

    key_owner: dict[str, str] = {}
    duplicate_details: list[str] = []
    for voice in voices:
        current_id = str(voice.get("voice_id") or "<missing>")
        for key in _dedupe_keys(voice):
            owner = key_owner.get(key)
            if owner is not None and owner != current_id:
                duplicate_details.append(f"{owner!r} 与 {current_id!r} 共用 {key}")
            else:
                key_owner[key] = current_id
    if duplicate_details:
        target = errors if reject_duplicates else warnings
        target.extend(f"重复声音：{detail}" for detail in duplicate_details[:100])

    configured_windows = _deep_get(
        normalized,
        (
            ("research", "windows"),
            ("research_context", "windows"),
            ("metadata", "windows"),
            ("windows",),
        ),
    )
    if isinstance(configured_windows, Mapping):
        category_window = configured_windows.get("category_30d")
        segment_window = configured_windows.get("segment_90d")
        category_days = configured_windows.get("category_days")
        segment_days = configured_windows.get("segment_days")
        if isinstance(category_window, Mapping):
            category_days = category_window.get("days")
        if isinstance(segment_window, Mapping):
            segment_days = segment_window.get("days")
        if category_days not in (None, 30):
            errors.append("全品类窗口必须固定为30天")
        if segment_days not in (None, 90):
            errors.append("Top3细分窗口必须固定为90天")
        expected_window_values: tuple[tuple[Any, str, datetime, str], ...] = (
            (category_window, "start_at", end_at - timedelta(days=30), "windows.category_30d.start_at"),
            (category_window, "end_at", end_at, "windows.category_30d.end_at"),
            (segment_window, "start_at", end_at - timedelta(days=90), "windows.segment_90d.start_at"),
            (segment_window, "end_at", end_at, "windows.segment_90d.end_at"),
        )
        if schema_version == LEGACY_SCHEMA_VERSION:
            expected_window_values = (
                *expected_window_values,
                (
                    segment_window,
                    "recent_30d_start_at",
                    end_at - timedelta(days=30),
                    "windows.segment_90d.recent_30d_start_at",
                ),
            )
        for container, key, expected, label in expected_window_values:
            if not isinstance(container, Mapping):
                continue
            try:
                actual = _parse_datetime(container.get(key), label)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if actual != expected:
                errors.append(f"{label} 必须与统一 end_at 精确对齐")

    if errors:
        raise ContractError("消费者声音编码未通过校验", errors[:200])
    normalized["schema_version"] = schema_version
    normalized["end_at"] = _iso(end_at)
    normalized["segments"] = segments
    normalized["voices"] = voices
    report = {
        "status": "valid",
        "schema_version": schema_version,
        "latest_schema_version": SCHEMA_VERSION,
        "end_at": _iso(end_at),
        "category_window": {
            "start_at": _iso(end_at - timedelta(days=30)),
            "end_at": _iso(end_at),
            "interval": "[start_at, end_at)",
        },
        "segment_window": {
            "start_at": _iso(end_at - timedelta(days=90)),
            "end_at": _iso(end_at),
            "interval": "[start_at, end_at)",
        },
        "voice_count": len(voices),
        "segment_count": len(segments),
        "warning_count": len(warnings),
        "warnings": warnings,
        "duplicate_key_count": len(duplicate_details),
    }
    return normalized, report


def _canonical_item(raw: Any, field: str) -> dict[str, Any] | None:
    if isinstance(raw, str):
        label = raw.strip()
        if not label:
            return None
        return {"key": _normalized_feature(label), "label": label}
    if not isinstance(raw, Mapping):
        return None
    label_value = (
        raw.get("label")
        or raw.get("name")
        or raw.get("description")
        or raw.get("text")
        or raw.get("need")
        or raw.get("need_code")
        or raw.get("satisfaction_code")
        or raw.get("dissatisfaction_code")
        or raw.get("signal_code")
        or raw.get("code")
        or raw.get("need_id")
        or raw.get("id")
        or raw.get("key")
    )
    label = str(label_value or "").strip()
    key_value = (
        raw.get("id")
        or raw.get("key")
        or raw.get("need_id")
        or raw.get("need_code")
        or raw.get("satisfaction_code")
        or raw.get("dissatisfaction_code")
        or raw.get("signal_code")
        or raw.get("code")
        or label
    )
    key = _normalized_feature(key_value)
    if not key or not label:
        return None
    result = dict(raw)
    result["key"] = key
    result["label"] = label
    if field == "ideas":
        idea_type = str(
            raw.get("signal_type")
            or raw.get("idea_type")
            or raw.get("type")
            or "consumer_explicit_idea"
        ).strip()
        result["idea_type"] = idea_type
    return result


def _voice_items(voice: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    value = _voice_tag_source(voice, field)
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        item = _canonical_item(raw, field)
        marker = (
            item["key"],
            str(item.get("idea_type") or "") if item is not None and field == "ideas" else "",
        ) if item is not None else ("", "")
        if item is None or marker in seen:
            continue
        if field == "ideas" and item.get("idea_type") in {
            "agent_design_idea",
            "agent",
            "agent_generated",
        }:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _need_label_map(document: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    dictionary = document.get("need_dictionary")
    if not isinstance(dictionary, list):
        return result
    for item in dictionary:
        if not isinstance(item, Mapping):
            continue
        code = _normalized_feature(item.get("need_code"))
        label = str(item.get("name_zh") or "").strip()
        if code and label:
            result[code] = label
    return result


def _layer_voice_sets(
    voices: Sequence[Mapping[str, Any]], end_at: datetime
) -> dict[str, list[Mapping[str, Any]]]:
    layers: dict[str, list[Mapping[str, Any]]] = {
        CATEGORY_SCOPE: [],
        "segment_1_90d": [],
        "segment_2_90d": [],
        "segment_3_90d": [],
        "union_mixed_window": list(voices),
    }
    for voice in voices:
        voice_scopes = _voice_scope_ids(voice)
        if CATEGORY_SCOPE in voice_scopes:
            layers[CATEGORY_SCOPE].append(voice)
        for index in range(1, 4):
            segment_id = f"segment_{index}_90d"
            if segment_id not in voice_scopes:
                continue
            layers[f"segment_{index}_90d"].append(voice)
    return layers


def _layer_profile(
    voices: Sequence[Mapping[str, Any]], *, raw_message_count: int | None = None
) -> dict[str, Any]:
    author_values = [str(voice.get("author_hash") or "").strip() for voice in voices]
    unidentified_states = {"unknown", "unavailable", "missing", "not_available"}
    identifiable = [
        value
        for voice, value in zip(voices, author_values)
        if value
        and value.casefold() != "unknown"
        and str(voice.get("author_identity_status") or "identified").casefold()
        not in unidentified_states
    ]
    platforms = [str(voice.get("platform") or "").strip() for voice in voices]
    thread_keys = [
        (
            str(voice.get("platform") or "").strip(),
            str(voice.get("thread_id") or "").strip(),
        )
        for voice in voices
    ]
    community_keys = [
        (
            str(voice.get("platform") or "").strip(),
            str(voice.get("community") or "").strip(),
        )
        for voice in voices
    ]
    thread_counts = Counter(value for value in thread_keys if value[1])
    platform_counts = Counter(value for value in platforms if value)
    denominator = len(voices)
    distinct_authors = len(set(identifiable))
    distinct_threads = len(thread_counts)
    if distinct_authors >= 30 and distinct_threads >= 5:
        confidence = "high"
    elif distinct_authors >= 15 and distinct_threads >= 3:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "raw_message_count": raw_message_count if raw_message_count is not None else denominator,
        "valid_deduplicated_message_count": denominator,
        "unique_author_count": distinct_authors,
        "unique_thread_count": distinct_threads,
        "unique_community_count": len(set(value for value in community_keys if value[1])),
        "platform_count": len(platform_counts),
        "largest_platform_share": (
            max(platform_counts.values()) / denominator if denominator and platform_counts else 0.0
        ),
        "largest_thread_share": (
            max(thread_counts.values()) / denominator if denominator and thread_counts else 0.0
        ),
        "author_identification_coverage": (
            len(identifiable) / denominator if denominator else 0.0
        ),
        "sample_confidence": confidence,
    }


def _voice_discovery_count(voice: Mapping[str, Any], scope: str | None = None) -> int:
    discoveries = voice.get("discoveries")
    if isinstance(discoveries, list) and discoveries:
        if scope is None:
            return len(discoveries)
        count = 0
        for discovery in discoveries:
            if not isinstance(discovery, Mapping):
                continue
            discovery_scope = discovery.get("scope_id") or discovery.get("collection_scope")
            if discovery_scope == scope:
                count += 1
        if count:
            return count
    scopes = voice.get("collection_scopes")
    if scope is None or (isinstance(scopes, list) and scope in scopes):
        return 1
    return 0


def _raw_layer_counts(
    voices: Sequence[Mapping[str, Any]],
    end_at: datetime,
    excluded_records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    counts = {
        CATEGORY_SCOPE: 0,
        "segment_1_90d": 0,
        "segment_2_90d": 0,
        "segment_3_90d": 0,
        "union_mixed_window": 0,
    }
    for voice in voices:
        discovery_total = _voice_discovery_count(voice)
        counts["union_mixed_window"] += discovery_total
        counts[CATEGORY_SCOPE] += _voice_discovery_count(voice, CATEGORY_SCOPE)
        memberships: set[str] = set()
        for membership in voice.get("segment_memberships") or []:
            if isinstance(membership, Mapping):
                if membership.get("is_member") is True and membership.get("segment_id"):
                    memberships.add(str(membership["segment_id"]))
            elif isinstance(membership, str):
                memberships.add(membership)
        for index in range(1, 4):
            segment_id = f"segment_{index}_90d"
            if segment_id not in memberships:
                continue
            counts[segment_id] += discovery_total
    # Excluded records still belong in the source funnel's raw-record numerator.
    # They never enter a quantitative denominator, but omitting them would make
    # the collection funnel look artificially clean and break source accounting.
    for record in excluded_records or []:
        if not isinstance(record, Mapping):
            continue
        scope_id = str(record.get("scope_id") or "")
        if scope_id not in {CATEGORY_SCOPE, *SEGMENT_SCOPES}:
            continue
        counts[scope_id] += 1
        counts["union_mixed_window"] += 1
    return counts


def _inferred_collection_funnel(
    document: Mapping[str, Any],
    raw_voices: Sequence[Mapping[str, Any]],
    deduplicated: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    existing = document.get("collection_funnel")
    if isinstance(existing, Mapping) and document.get("schema_version") == SCHEMA_VERSION:
        return copy.deepcopy(dict(existing))
    excluded = [
        item
        for item in (document.get("excluded_records") or [])
        if isinstance(item, Mapping)
    ]
    reason_counts = Counter(
        str(reason)
        for item in excluded
        for reason in (item.get("exclusion_reasons") or [])
    )

    def build_stage(
        raw_items: Sequence[Mapping[str, Any]],
        valid_items: Sequence[Mapping[str, Any]],
        excluded_items: Sequence[Mapping[str, Any]],
    ) -> dict[str, int]:
        fetched = len(raw_items) + len(excluded_items)
        duplicate_excluded = sum(
            "duplicate_of_canonical" in set(item.get("exclusion_reasons") or [])
            for item in excluded_items
        )
        date_excluded = sum(
            bool(
                {"missing_or_unreliable_date", "outside_window"}
                & set(item.get("exclusion_reasons") or [])
            )
            for item in excluded_items
        )
        relevance_excluded = sum(
            bool(
                {"off_topic", "non_target_language"}
                & set(item.get("exclusion_reasons") or [])
            )
            for item in excluded_items
        )
        unique = max(len(raw_items), fetched - duplicate_excluded)
        within = max(len(raw_items), unique - date_excluded)
        relevant = max(len(raw_items), within - relevance_excluded)
        return {
            "fetched_records": fetched,
            "unique_records": unique,
            "within_window_records": within,
            "relevant_records": relevant,
            "consumer_records": len(raw_items),
            "deduplicated_records": len(valid_items),
            "valid_voices": len(valid_items),
        }

    overall = build_stage(raw_voices, deduplicated, excluded)
    per_scope: list[dict[str, Any]] = []
    for scope_id in (CATEGORY_SCOPE, *SEGMENT_SCOPES):
        scope_raw = [
            voice
            for voice in raw_voices
            if scope_id in _voice_scope_ids(voice)
        ]
        scope_valid = [
            voice
            for voice in deduplicated
            if scope_id in _voice_scope_ids(voice)
        ]
        scope_excluded = [item for item in excluded if item.get("scope_id") == scope_id]
        per_scope.append(
            {"scope_id": scope_id, **build_stage(scope_raw, scope_valid, scope_excluded)}
        )
    valid_platforms = Counter(
        str(voice.get("platform") or "unknown") for voice in deduplicated
    )
    fetched_platforms = Counter(
        [str(voice.get("platform") or "unknown") for voice in raw_voices]
        + [str(item.get("platform") or "unknown") for item in excluded]
    )
    return {
        **overall,
        "excluded_records": len(excluded),
        "per_scope": per_scope,
        "per_platform": [
            {
                "platform": platform,
                "fetched_records": fetched_platforms[platform],
                "valid_voices": valid_platforms[platform],
            }
            for platform in sorted(fetched_platforms | valid_platforms)
        ],
        "exclusion_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_counts.items())
        ],
    }


def _evidence_confidence(author_count: int, thread_count: int, platform_count: int) -> str:
    if author_count >= 10 and thread_count >= 5 and platform_count >= 2:
        return "high"
    if author_count >= 5 and thread_count >= 3:
        return "medium"
    return "low"


def _aggregate_field(
    voices: Sequence[Mapping[str, Any]],
    field: str,
    *,
    limit: int | None = None,
    label_map: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    layer_authors = {
        str(voice.get("author_hash") or "").strip()
        for voice in voices
        if str(voice.get("author_hash") or "").strip()
        and str(voice.get("author_hash") or "").strip().casefold() != "unknown"
        and str(voice.get("author_identity_status") or "identified").casefold()
        not in {"unknown", "unavailable", "missing", "not_available"}
    }
    for voice in voices:
        voice_id = str(voice.get("voice_id") or "")
        author = str(voice.get("author_hash") or "").strip()
        thread = str(voice.get("thread_id") or "").strip()
        platform = str(voice.get("platform") or "").strip()
        published_at = str(voice.get("published_at") or "")
        for item in _voice_items(voice, field):
            idea_type = str(item.get("idea_type") or "consumer_explicit_idea")
            bucket_key = (
                f"{item['key']}\u241f{idea_type}" if field == "ideas" else item["key"]
            )
            bucket = buckets.setdefault(
                bucket_key,
                {
                    "key": item["key"],
                    "label": (label_map or {}).get(item["key"], item["label"]),
                    "voice_ids": set(),
                    "authors": set(),
                    "threads": set(),
                    "platforms": set(),
                    "timestamps": [],
                    "idea_types": Counter(),
                },
            )
            bucket["voice_ids"].add(voice_id)
            if (
                author
                and author.casefold() != "unknown"
                and str(voice.get("author_identity_status") or "identified").casefold()
                not in {"unknown", "unavailable", "missing", "not_available"}
            ):
                bucket["authors"].add(author)
            if thread:
                bucket["threads"].add((platform, thread))
            if platform:
                bucket["platforms"].add(platform)
            if published_at:
                bucket["timestamps"].append(published_at)
            if field == "ideas":
                bucket["idea_types"][idea_type] += 1
    denominator = len(voices)
    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        voice_count = len(bucket["voice_ids"])
        author_count = len(bucket["authors"])
        item = {
            "key": bucket["key"],
            "label": bucket["label"],
            "voice_count": voice_count,
            "voice_share": voice_count / denominator if denominator else 0.0,
            "author_count": author_count,
            # A zero identified-author denominator is unknown coverage, not 0%.
            "author_share": author_count / len(layer_authors) if layer_authors else None,
            "thread_count": len(bucket["threads"]),
            "platform_count": len(bucket["platforms"]),
            "evidence_confidence": _evidence_confidence(
                author_count, len(bucket["threads"]), len(bucket["platforms"])
            ),
            "evidence_ids": sorted(bucket["voice_ids"]),
            "time_range": {
                "first_at": min(bucket["timestamps"]) if bucket["timestamps"] else None,
                "last_at": max(bucket["timestamps"]) if bucket["timestamps"] else None,
            },
        }
        if field == "ideas":
            item["idea_types"] = dict(sorted(bucket["idea_types"].items()))
            item["direct_voice_count"] = voice_count
        result.append(item)
    result.sort(
        key=lambda item: (
            -item["voice_count"],
            -item["author_count"],
            -item["thread_count"],
            -item["platform_count"],
            item["key"],
        )
    )
    return result[:limit] if limit is not None else result


def _canonical_kano(value: Any) -> str:
    normalized = _normalized_feature(value).replace(" ", "_")
    return KANO_ALIASES.get(normalized, "EVIDENCE_INSUFFICIENT")


def _voice_kano_entries(voice: Mapping[str, Any]) -> list[dict[str, Any]]:
    explicit = _voice_tag_source(voice, "kano_evidence")
    if explicit is None:
        explicit = voice.get("kano")
    entries: list[dict[str, Any]] = []
    if isinstance(explicit, list):
        for raw in explicit:
            if not isinstance(raw, Mapping):
                continue
            need = _canonical_item(
                {
                    "id": raw.get("need_id") or raw.get("id") or raw.get("key"),
                    "need_code": raw.get("need_code"),
                    "label": raw.get("need_label") or raw.get("label") or raw.get("need") or raw.get("need_code"),
                },
                "needs",
            )
            if need is None:
                continue
            entry = dict(raw)
            entry.update(need)
            evidence_type = str(raw.get("evidence_type") or "").strip()
            evidence_category = {
                "absence_complaint": "M",
                "presence_baseline": "M",
                "performance_positive": "O",
                "performance_negative": "O",
                "surprise_delight": "A",
                "explicit_feature_wish": "A",
                "explicit_indifference": "I",
                "explicit_rejection": "R",
                "harm_or_negative_utility": "R",
                "conflicting_or_weak": "evidence_insufficient",
            }.get(evidence_type)
            entry["category"] = evidence_category or _canonical_kano(
                raw.get("category")
                or raw.get("kano_category")
                or raw.get("kano_type")
                or raw.get("kano")
            )
            entry["evidence_type"] = evidence_type
            entries.append(entry)
    for need in _voice_items(voice, "needs"):
        raw_category = need.get("kano_category") or need.get("kano")
        if raw_category is None:
            continue
        entries.append(
            {
                "key": need["key"],
                "label": need["label"],
                "category": _canonical_kano(raw_category),
                "scope": need.get("kano_scope") or need.get("scope"),
            }
        )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        marker = (
            entry["key"],
            entry["category"],
            str(entry.get("scope") or ""),
            str(entry.get("evidence_type") or ""),
        )
        if marker not in seen:
            seen.add(marker)
            unique.append(entry)
    return unique


def _scope_applies_to_layer(scope: Any, layer: str) -> bool:
    if scope is None or scope == "":
        return True
    normalized = str(scope).strip()
    if normalized == layer:
        return True
    if layer.endswith("_recent_30d"):
        return normalized in {layer.replace("_recent_30d", "_90d"), "recent_30d"}
    if layer == CATEGORY_SCOPE:
        return normalized in {CATEGORY_SCOPE, "category"}
    if layer == "union_mixed_window":
        return True
    return False


def _aggregate_kano(
    voices: Sequence[Mapping[str, Any]],
    layer: str,
    time_window: Mapping[str, Any],
    label_map: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    need_totals = {
        item["key"]: item
        for item in _aggregate_field(voices, "needs", label_map=label_map)
    }
    category_voices: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    evidence_type_voices: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    evidence_ids: dict[str, set[str]] = defaultdict(set)
    voice_dimensions: dict[str, tuple[str, str, str]] = {}
    labels: dict[str, str] = {}
    for voice in voices:
        voice_id = str(voice.get("voice_id") or "")
        voice_dimensions[voice_id] = (
            str(voice.get("author_hash") or "").strip(),
            str(voice.get("thread_id") or "").strip(),
            str(voice.get("platform") or "").strip(),
        )
        for entry in _voice_kano_entries(voice):
            if not _scope_applies_to_layer(entry.get("scope"), layer):
                continue
            category_voices[entry["key"]][entry["category"]].add(voice_id)
            if entry.get("evidence_type"):
                evidence_type_voices[entry["key"]][str(entry["evidence_type"])].add(
                    voice_id
                )
            evidence_ids[entry["key"]].add(voice_id)
            labels[entry["key"]] = (label_map or {}).get(
                entry["key"], entry["label"]
            )
    result: list[dict[str, Any]] = []
    for key, need in need_totals.items():
        counts = Counter(
            {
                category: len(voice_ids)
                for category, voice_ids in category_voices.get(key, {}).items()
            }
        )
        if counts:
            selected = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        else:
            selected = "evidence_insufficient"
        need_author_count = need["author_count"]
        need_thread_count = need["thread_count"]
        need_platform_count = need["platform_count"]
        type_sets = evidence_type_voices.get(key, {})
        type_counts = Counter({evidence_type: len(ids) for evidence_type, ids in type_sets.items()})
        threshold_reason = ""
        substantive_categories = {
            category
            for category, count in counts.items()
            if count > 0 and category != "evidence_insufficient"
        }
        if len(substantive_categories) > 1 or type_counts.get("conflicting_or_weak", 0) > 0:
            threshold_reason = "存在跨需求属性类别冲突或弱证据，保守归入证据不足。"
            selected = "evidence_insufficient"
        selected_voice_ids = set(category_voices.get(key, {}).get(selected, set()))
        selected_dimensions = [
            voice_dimensions[voice_id]
            for voice_id in selected_voice_ids
            if voice_id in voice_dimensions
        ]
        selected_authors = {
            author
            for author, _, _ in selected_dimensions
            if author and author.casefold() != "unknown"
        }
        selected_threads = {
            (platform, thread)
            for _, thread, platform in selected_dimensions
            if thread
        }
        selected_platforms = {platform for _, _, platform in selected_dimensions if platform}
        if selected in {"M", "O", "A"} and (
            len(selected_voice_ids) < 3
            or len(selected_authors) < 2
            or len(selected_threads) < 2
        ):
            threshold_reason = "支持该需求属性分类的证据未达到3留言、2作者、2线程门槛。"
            selected = "evidence_insufficient"
        elif selected == "O" and not (
            type_counts.get("performance_positive", 0) > 0
            and type_counts.get("performance_negative", 0) > 0
        ):
            threshold_reason = "O类缺少performance_positive与performance_negative双向梯度证据。"
            selected = "evidence_insufficient"
        elif selected == "I" and type_counts.get("explicit_indifference", 0) == 0:
            threshold_reason = "I类缺少explicit_indifference明确证据。"
            selected = "evidence_insufficient"
        elif selected == "R" and (
            type_counts.get("explicit_rejection", 0)
            + type_counts.get("harm_or_negative_utility", 0)
            == 0
        ):
            threshold_reason = "R类缺少explicit_rejection或harm_or_negative_utility明确证据。"
            selected = "evidence_insufficient"
        rationale = (
            threshold_reason
            or "按逐条消费者声音中已编码的需求属性证据多数项汇总；这不是成对功能/反功能问卷。"
            if counts or threshold_reason
            else "没有足够的明确需求属性证据，保守归入证据不足。"
        )
        result.append(
            {
                "need_key": key,
                "need_label": labels.get(key, need["label"]),
                "category": selected,
                "category_evidence_counts": {
                    code: counts.get(code, 0)
                    for code in ("M", "O", "A", "I", "R", "evidence_insufficient")
                },
                "evidence_type_counts": {
                    code: type_counts.get(code, 0)
                    for code in (
                        "absence_complaint",
                        "presence_baseline",
                        "performance_positive",
                        "performance_negative",
                        "surprise_delight",
                        "explicit_feature_wish",
                        "explicit_indifference",
                        "explicit_rejection",
                        "harm_or_negative_utility",
                        "conflicting_or_weak",
                    )
                },
                "classified_voice_count": len(
                    set().union(*category_voices.get(key, {}).values())
                    if category_voices.get(key)
                    else set()
                ),
                "scope_id": layer,
                "time_window": dict(time_window),
                "voice_count": need["voice_count"],
                "voice_share": need["voice_share"],
                "author_count": need_author_count,
                "author_share": need["author_share"],
                "thread_count": need_thread_count,
                "platform_count": need_platform_count,
                "evidence_voice_ids": sorted(
                    value for value in evidence_ids.get(key, set()) if value
                ),
                "confidence": _evidence_confidence(
                    len(selected_authors), len(selected_threads), len(selected_platforms)
                ),
                "rationale": rationale,
                "directional_inference": True,
                "formal_survey": False,
            }
        )
    result.sort(key=lambda item: (-item["voice_count"], item["need_key"]))
    return result


def _agent_design_ideas(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = document.get("agent_design_ideas")
    if source is None:
        source = document.get("design_ideas")
    if not isinstance(source, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in source:
        item = _canonical_item(raw, "ideas")
        if item is None:
            continue
        item["idea_type"] = "agent_design_idea"
        item["direct_voice_count"] = 0
        item["direct_voice_share"] = 0.0
        result.append(item)
    return result


def _layer_time_window(layer_name: str, end_at: datetime) -> dict[str, Any]:
    if layer_name == CATEGORY_SCOPE or layer_name.endswith("_recent_30d"):
        return {
            "start_at": _iso(end_at - timedelta(days=30)),
            "end_at": _iso(end_at),
            "days": 30,
            "interval": "[start_at, end_at)",
        }
    if layer_name.endswith("_90d"):
        return {
            "start_at": _iso(end_at - timedelta(days=90)),
            "end_at": _iso(end_at),
            "days": 90,
            "interval": "[start_at, end_at)",
        }
    return {
        "start_at": _iso(end_at - timedelta(days=90)),
        "end_at": _iso(end_at),
        "days": None,
        "window_type": "mixed_30d_category_and_90d_segments",
        "interval": "[scope_start_at, end_at)",
    }


def _public_segments(segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for segment in segments:
        item = copy.deepcopy(dict(segment))
        result.append(item)
    return result


def _analysis_segments(segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "segment_id",
        "rank",
        "dimension",
        "feature",
        "listing_count",
        "listing_share",
        "sales_share",
        "supply_demand_index",
    )
    return [{key: copy.deepcopy(segment[key]) for key in keys} for segment in segments]


def _analysis_scope_id(layer_name: str) -> str:
    if layer_name in {CATEGORY_SCOPE, "union_mixed_window", *SEGMENT_SCOPES}:
        return layer_name
    if re.fullmatch(r"segment_[1-3]_recent_30d", layer_name):
        return layer_name
    raise ContractError(f"未知分析scope：{layer_name}")


def _analysis_time_window(layer_name: str) -> str:
    if layer_name == CATEGORY_SCOPE:
        return "category_30d"
    if layer_name == "union_mixed_window":
        return "union_mixed_window"
    if layer_name.endswith("_recent_30d"):
        return "segment_recent_30d"
    if layer_name.endswith("_90d"):
        return "segment_90d"
    raise ContractError(f"未知分析时间窗口：{layer_name}")


def _stat_evidence_origins(
    layer_name: str,
    evidence_ids: Sequence[str],
    recent_ids: Sequence[str] | None = None,
    history_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    if not evidence_ids:
        return []
    if layer_name == CATEGORY_SCOPE:
        origin_type = "category_recent_30d"
        segment_id = None
    elif layer_name.endswith("_90d"):
        origin_type = "segment_90d"
        segment_id = layer_name
    else:
        origin_type = "cross_layer"
        segment_id = None
    return [
        {
            "origin_type": origin_type,
            "segment_id": segment_id,
            "voice_ids": list(evidence_ids),
            "description": "由该统计层逐条可追溯消费者声音重算。",
        }
    ]


def _strict_need_stats(items: Any, layer_name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        evidence_ids = list(item.get("evidence_ids") or [])
        result.append(
            {
                "need_code": str(item.get("key") or "unknown_need"),
                "name_zh": str(item.get("label") or item.get("key") or "未命名需求"),
                "scope_id": _analysis_scope_id(layer_name),
                "time_window": _analysis_time_window(layer_name),
                "voice_count": int(item.get("voice_count") or 0),
                "voice_share": item.get("voice_share"),
                "author_count": int(item.get("author_count") or 0),
                "author_share": item.get("author_share"),
                "thread_count": int(item.get("thread_count") or 0),
                "platform_count": int(item.get("platform_count") or 0),
                "evidence_voice_ids": evidence_ids,
                "evidence_origins": _stat_evidence_origins(
                    layer_name,
                    evidence_ids,
                    item.get("recent_30d_evidence_ids"),
                    item.get("days_31_90_evidence_ids"),
                ),
                "confidence": item.get("evidence_confidence") or "low",
            }
        )
    return result


def _strict_ranked_items(items: Any, layer_name: str) -> list[dict[str, Any]]:
    eligible = [
        item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping)
        and int(item.get("voice_count") or 0) >= 2
        and int(item.get("author_count") or 0) >= 2
    ][:10]
    result: list[dict[str, Any]] = []
    for rank, item in enumerate(eligible, start=1):
        result.append(
            {
                "rank": rank,
                "code": str(item.get("key") or f"item_{rank}"),
                "label": str(item.get("label") or item.get("key") or f"观点{rank}"),
                "scope_id": _analysis_scope_id(layer_name),
                "time_window": _analysis_time_window(layer_name),
                "voice_count": int(item.get("voice_count") or 0),
                "voice_share": item.get("voice_share"),
                "author_count": int(item.get("author_count") or 0),
                "author_share": item.get("author_share"),
                "thread_count": int(item.get("thread_count") or 0),
                "platform_count": int(item.get("platform_count") or 0),
                "evidence_voice_ids": list(item.get("evidence_ids") or []),
                "confidence": item.get("evidence_confidence") or "low",
            }
        )
    return result


def _strict_labeled_stats(items: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "code": str(item.get("key") or "unknown"),
                "label": str(item.get("label") or item.get("key") or "未命名"),
                "voice_count": int(item.get("voice_count") or 0),
                "voice_share": item.get("voice_share"),
                "author_count": int(item.get("author_count") or 0),
                "author_share": item.get("author_share"),
                "thread_count": int(item.get("thread_count") or 0),
                "platform_count": int(item.get("platform_count") or 0),
                "evidence_voice_ids": list(item.get("evidence_ids") or []),
                "confidence": item.get("evidence_confidence") or "low",
            }
        )
    return result


def _strict_kano(items: Any, layer_name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "need_code": str(item.get("need_key") or "unknown_need"),
                "name_zh": str(item.get("need_label") or item.get("need_key") or "未命名需求"),
                "classification": item.get("category") or "evidence_insufficient",
                "directional_inference": True,
                "formal_survey": False,
                "scope_id": _analysis_scope_id(layer_name),
                "time_window": _analysis_time_window(layer_name),
                "voice_count": int(item.get("voice_count") or 0),
                "voice_share": item.get("voice_share"),
                "author_count": int(item.get("author_count") or 0),
                "author_share": item.get("author_share"),
                "thread_count": int(item.get("thread_count") or 0),
                "platform_count": int(item.get("platform_count") or 0),
                "evidence_counts": dict(item.get("evidence_type_counts") or {}),
                "evidence_voice_ids": list(item.get("evidence_voice_ids") or []),
                "confidence": item.get("confidence") or "low",
                "rationale": str(item.get("rationale") or "证据不足，暂不做确定分类。"),
            }
        )
    return result


def _strict_innovations(items: Any, layer_name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items if isinstance(items, list) else [], start=1):
        if not isinstance(item, Mapping):
            continue
        types = item.get("idea_types") if isinstance(item.get("idea_types"), Mapping) else {}
        raw_type = max(types, key=types.get) if types else "consumer_explicit_idea"
        innovation_type = {
            "consumer_explicit_idea": "consumer_explicit_idea",
            "diy_workaround": "diy_workaround",
            "repeated_pain_signal": "inferred_latent_need",
            "inferred_latent_need": "inferred_latent_need",
        }.get(raw_type, "consumer_explicit_idea")
        author_count = int(item.get("author_count") or 0)
        thread_count = int(item.get("thread_count") or 0)
        has_workaround = raw_type in {"diy_workaround", "repeated_pain_signal"}
        evidence_ids = list(item.get("evidence_ids") or [])
        result.append(
            {
                "innovation_id": f"{_analysis_scope_id(layer_name)}.{item.get('key') or index}.{innovation_type}",
                "innovation_type": innovation_type,
                "need_code": str(item.get("key") or f"innovation_{index}"),
                "title": str(item.get("label") or item.get("key") or f"创意{index}"),
                "description": str(item.get("label") or "消费者声音中观察到的创新信号。"),
                "status": "solution_hypothesis" if innovation_type != "inferred_latent_need" else "observed_pain",
                "meets_consumer_evidence_threshold": (
                    author_count >= 5 and thread_count >= 3 and has_workaround
                ),
                "voice_count": int(item.get("voice_count") or 0),
                "voice_share": item.get("voice_share"),
                "author_count": author_count,
                "author_share": item.get("author_share"),
                "thread_count": thread_count,
                "platform_count": int(item.get("platform_count") or 0),
                "has_failure_or_workaround_evidence": has_workaround,
                "evidence_voice_ids": evidence_ids,
                "evidence_origins": _stat_evidence_origins(
                    layer_name,
                    evidence_ids,
                    item.get("recent_30d_evidence_ids"),
                    item.get("days_31_90_evidence_ids"),
                ),
                "supply_validation_ref": None,
                "confidence": item.get("evidence_confidence") or "low",
            }
        )
    return result


def _strict_scope_quality(
    layer_name: str,
    profile: Mapping[str, Any],
    source_runs: Any,
) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    if isinstance(source_runs, list):
        for run in source_runs:
            if not isinstance(run, Mapping):
                continue
            run_scopes = run.get("scope_ids") if isinstance(run.get("scope_ids"), list) else []
            relevant_scope = CATEGORY_SCOPE if layer_name == CATEGORY_SCOPE else (
                layer_name.replace("_recent_30d", "_90d")
                if layer_name.endswith("_recent_30d")
                else (layer_name if layer_name in SEGMENT_SCOPES else None)
            )
            if relevant_scope and relevant_scope not in run_scopes:
                continue
            for status in run.get("platform_statuses", []):
                if isinstance(status, Mapping):
                    statuses.append(
                        {
                            "platform": str(status.get("platform") or "unknown"),
                            "backend": status.get("backend"),
                            "status": status.get("status") or "not_run",
                            "result_count": int(status.get("result_count") or 0),
                        }
                    )
    confidence = profile.get("sample_confidence") or "low"
    warning = None if confidence == "high" else "样本量或来源分散度不足，结论已降低置信度。"
    return {
        "scope_id": _analysis_scope_id(layer_name),
        "time_window": _analysis_time_window(layer_name),
        "raw_record_count": int(profile.get("raw_message_count") or 0),
        "deduplicated_record_count": int(profile.get("valid_deduplicated_message_count") or 0),
        "valid_voice_count": int(profile.get("valid_deduplicated_message_count") or 0),
        "identified_author_count": int(profile.get("unique_author_count") or 0),
        "thread_count": int(profile.get("unique_thread_count") or 0),
        "community_count": int(profile.get("unique_community_count") or 0),
        "platform_count": int(profile.get("platform_count") or 0),
        "largest_platform_share": profile.get("largest_platform_share") if profile.get("platform_count") else None,
        "largest_thread_share": profile.get("largest_thread_share") if profile.get("unique_thread_count") else None,
        "author_identification_coverage": profile.get("author_identification_coverage") if profile.get("valid_deduplicated_message_count") else None,
        "source_statuses": statuses,
        "confidence": confidence,
        "sample_warning": warning,
    }


def _planned_product_concepts(segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    for index in range(1, 4):
        segment = next((item for item in segments if item.get("rank") == index), None)
        segment_id = segment.get("segment_id") if segment else None
        feature = segment.get("feature") if segment else "市场级补充方向"
        origin = {
            "origin_type": "agent_design_inference",
            "segment_id": segment_id,
            "voice_ids": [],
            "description": "待Agent结合消费者证据、供给验证和工程约束完善。",
        }
        phase = {
            "status": "planned",
            "outputs": [],
            "evidence_voice_ids": [],
            "success_or_decision_gate": "必须由Agent补全证据并通过产品决策门槛后，才可标记为已完成。",
        }
        moscow_item = {
            "feature": "待Agent定义",
            "reason": "分析脚本只生成planned骨架，不代替语义产品设计。",
            "target_segment_ids": [segment_id] if segment_id else [],
            "evidence_origins": [origin],
            "acceptance_criteria": "补全消费者证据、技术方案与量化验收标准。",
        }
        concepts.append(
            {
                "concept_id": f"concept_{index}",
                "name": f"待完善概念 {index}：{feature}",
                "segment_id": segment_id,
                "market_level_hypothesis": segment_id is None,
                "target_consumers": ["待Agent定义"],
                "jtbd": "待Agent结合消费者声音定义JTBD。",
                "use_scenarios": ["待Agent定义"],
                "evidence_origins": [origin],
                "kano_mapping": [],
                "features": ["待Agent定义"],
                "technical_solution": "待Agent与工程约束共同完善。",
                "structure": "待Agent完善结构方案。",
                "materials": ["待Agent选材"],
                "cmf": {
                    "colors": ["待定义"],
                    "finishes": ["待定义"],
                    "visual_language": "待Agent定义视觉语言。",
                },
                "target_price": {
                    "currency": "USD",
                    "min": 0,
                    "max": 0,
                    "assumption": "planned占位，尚未完成价格研究。",
                },
                "bom_assumption": "planned占位，尚未完成BOM评估。",
                "risks": ["证据、供给验证与工程方案尚未补全"],
                "dependencies": ["Agent语义分析", "供给验证", "工程评审"],
                "acceptance_metrics": [
                    {
                        "metric": "概念完整度",
                        "target": "所有必填产品字段和证据完成",
                        "test_method": "最终化门禁校验",
                    }
                ],
                "design_thinking": {
                    key: copy.deepcopy(phase)
                    for key in ("empathize", "define", "ideate", "prototype", "test", "iteration")
                },
                "moscow": {
                    "must": [moscow_item],
                    "should": [],
                    "could": [],
                    "wont_this_release": [],
                },
                "image_prompt": {
                    "prompt_text": "待Agent完成产品策划后生成最终概念图提示词。",
                    "target_product": str(feature),
                    "target_consumer": "待定义",
                    "use_scenario": "待定义",
                    "key_structure": "待定义",
                    "technical_constraints": ["不得虚构已完成工程验证"],
                    "scale_and_proportion": "待定义",
                    "materials": ["待定义"],
                    "cmf": "待定义",
                    "camera": "待定义",
                    "lighting": "待定义",
                    "background": "待定义",
                    "must_show": ["产品主体"],
                    "forbidden": ["虚假认证文字"],
                },
                "image_artifact": {
                    "status": "pending",
                    "attempt_count": 0,
                    "path": None,
                    "mime_type": None,
                    "sha256": None,
                    "embedded_as_data_uri": False,
                    "disclaimer": "AI概念表达，非工程图或认证结果",
                    "error_message": None,
                },
            }
        )
    return concepts


def analyze_coding(
    document: Mapping[str, Any],
    *,
    coding_path: Path | None = None,
    output_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    # Validate the original document before deduplication.  Otherwise an invalid
    # duplicate could be discarded before its schema/cross-field error is seen.
    validate_coding_document(document, reject_duplicates=False)
    all_voices = _document_voices(document)
    raw_voices = [
        voice for voice in all_voices if voice.get("eligible_for_quantitation") is True
    ]
    deduplicated, dedupe_report = _deduplicate_voices(raw_voices)
    working = copy.deepcopy(dict(document))
    working["voices"] = deduplicated
    normalized, validation = validate_coding_document(working, reject_duplicates=True)
    voices = normalized["voices"]
    end_at = _document_end_at(normalized)
    layers = _layer_voice_sets(voices, end_at)
    raw_counts = _raw_layer_counts(
        raw_voices,
        end_at,
        excluded_records=normalized.get("excluded_records") or [],
    )
    need_labels = _need_label_map(normalized)
    layer_analysis: dict[str, dict[str, Any]] = {}
    for layer_name, layer_voices in layers.items():
        needs = _aggregate_field(layer_voices, "needs", label_map=need_labels)
        satisfactions = _aggregate_field(
            layer_voices, "satisfactions", label_map=need_labels
        )
        dissatisfactions = _aggregate_field(
            layer_voices, "dissatisfactions", label_map=need_labels
        )
        ideas = _aggregate_field(layer_voices, "ideas", label_map=need_labels)
        scenarios = _aggregate_field(layer_voices, "scenarios")
        personas = _aggregate_field(layer_voices, "personas")
        layer_analysis[layer_name] = {
            "scope_id": layer_name,
            "time_window": _layer_time_window(layer_name, end_at),
            "profile": _layer_profile(
                layer_voices, raw_message_count=raw_counts.get(layer_name)
            ),
            "needs": needs,
            "satisfactions": satisfactions,
            "satisfaction_top10": satisfactions[:10],
            "dissatisfactions": dissatisfactions,
            "dissatisfaction_top10": dissatisfactions[:10],
            "ideas": ideas,
            "scenarios": scenarios,
            "personas": personas,
            "kano": _aggregate_kano(
                layer_voices,
                layer_name,
                _layer_time_window(layer_name, end_at),
                label_map=need_labels,
            ),
        }

    segments = normalized.get("segments", [])
    selected_ranks = {
        int(item["rank"])
        for item in segments
        if isinstance(item, Mapping) and item.get("rank") in (1, 2, 3)
    }
    denominators = {
        "N_category_30d": len(layers[CATEGORY_SCOPE]),
        "N_segment_1_90d": len(layers["segment_1_90d"]) if 1 in selected_ranks else None,
        "N_segment_2_90d": len(layers["segment_2_90d"]) if 2 in selected_ranks else None,
        "N_segment_3_90d": len(layers["segment_3_90d"]) if 3 in selected_ranks else None,
        "N_union_mixed_window": len(layers["union_mixed_window"]),
    }
    windows = {
        "interval_semantics": "[start_at,end_at)",
        "category_30d": {
            "days": 30,
            "start_at": _iso(end_at - timedelta(days=30)),
            "end_at": _iso(end_at),
        },
        "segment_90d": {
            "start_at": _iso(end_at - timedelta(days=90)),
            "end_at": _iso(end_at),
            "days": 90,
        },
    }
    segment_analyses: list[dict[str, Any]] = []
    for index in sorted(selected_ranks):
        definition = next(item for item in segments if item.get("rank") == index)
        full_layer_name = f"segment_{index}_90d"
        full = layer_analysis[full_layer_name]
        innovations = _strict_innovations(full["ideas"], full_layer_name)
        segment_analyses.append(
            {
                "segment_id": definition["segment_id"],
                "denominator_90d": len(layers[full_layer_name]),
                "need_stats_90d": _strict_need_stats(full["needs"], full_layer_name),
                "kano_90d": _strict_kano(full["kano"], full_layer_name),
                "satisfaction_90d": _strict_ranked_items(full["satisfactions"], full_layer_name),
                "dissatisfaction_90d": _strict_ranked_items(full["dissatisfactions"], full_layer_name),
                "use_scenes": _strict_labeled_stats(full["scenarios"]),
                "personas": _strict_labeled_stats(full["personas"]),
                "diy_workarounds": [item for item in innovations if item["innovation_type"] == "diy_workaround"],
                "new_needs": innovations,
            }
        )
    category = layer_analysis[CATEGORY_SCOPE]
    union = layer_analysis["union_mixed_window"]
    union_need_stats = _strict_need_stats(union["needs"], "union_mixed_window")
    category_codes = {item["key"] for item in category["needs"]}
    segment_code_counts = Counter()
    for index in selected_ranks:
        for item in layer_analysis[f"segment_{index}_90d"]["needs"]:
            segment_code_counts[item["key"]] += 1
    shared_codes = {
        code for code, count in segment_code_counts.items() if code in category_codes and count >= 1
    }
    source_project = document.get("project") if isinstance(document.get("project"), Mapping) else {}
    opportunity_artifact = source_project.get("opportunity_analysis") if isinstance(source_project.get("opportunity_analysis"), Mapping) else {}
    dashboard_artifact = source_project.get("opportunity_dashboard") if isinstance(source_project.get("opportunity_dashboard"), Mapping) else {}
    coding_resolved = coding_path.resolve() if coding_path is not None else Path("consumer_voice_coding.json").resolve()
    coding_sha = hashlib.sha256(coding_resolved.read_bytes()).hexdigest() if coding_resolved.is_file() else "0" * 64
    opportunity_sha = str(opportunity_artifact.get("sha256") or "0" * 64)
    dashboard_sha = str(dashboard_artifact.get("sha256") or "0" * 64)
    analysis_output = output_path.resolve() if output_path is not None else Path("social_voice_analysis.json").resolve()
    report_output = (
        report_path.resolve()
        if report_path is not None
        else analysis_output.with_suffix(".html")
    )
    snapshot_at = str(opportunity_artifact.get("snapshot_at") or _iso(end_at))
    research_plan = _research_plan(document)
    collection_funnel = _inferred_collection_funnel(
        document, raw_voices, deduplicated
    )
    collection_receipt = _collection_receipt_summary(
        coding_path=coding_path,
        research_plan=research_plan,
        denominators=denominators,
        collection_funnel=collection_funnel,
    )
    default_stop_reason = _default_stop_reason(
        document, int(collection_funnel.get("valid_voices") or 0)
    )
    deadline_status = collection_receipt.get("deadline_status")
    final_stop_reason = (
        "total_deadline"
        if isinstance(deadline_status, Mapping)
        and deadline_status.get("deadline_exceeded") is True
        else default_stop_reason
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "project_root": str(source_project.get("project_root") or coding_resolved.parent),
            "marketplace": str(source_project.get("marketplace") or "US"),
            "listing_language": str(source_project.get("listing_language") or "en"),
            "category_keyword": str(source_project.get("category_keyword") or "unknown product"),
            "coding_artifact": str(coding_resolved),
            "coding_sha256": coding_sha,
            "opportunity_analysis": str(opportunity_artifact.get("path") or "07_opportunity_analysis.json"),
            "opportunity_analysis_sha256": opportunity_sha,
        },
        "generated_at": _iso(datetime.now(timezone.utc)),
        "end_at": _iso(end_at),
        "windows": windows,
        "segments": _analysis_segments(segments),
        "research_plan": research_plan,
        "collection_funnel": collection_funnel,
        "collection_receipt": collection_receipt,
        "stop_reason": final_stop_reason,
        "methodology": {
            "category_window_days": 30,
            "segment_window_days": 90,
            "same_end_at": True,
            "auto_window_expansion": False,
            "quantitative_unit": "technically_deduplicated_public_message",
            "author_count_rule": "identified_or_pseudonymous_author_hash_only",
            "kano_mode": "directional_inference",
            "directional_inference": True,
            "formal_survey": False,
            "union_share_label": "混合窗口研究语料占比",
            "ranked_item_min_voice_count": 2,
            "ranked_item_min_author_count": 2,
            "new_need_min_author_count": 5,
            "new_need_min_thread_count": 3,
            "source_failure_rule": "only_no_results_means_successful_zero_results",
            "supply_snapshot_at": snapshot_at,
        },
        "denominators": denominators,
        "scope_quality": [
            _strict_scope_quality(layer, data["profile"], document.get("source_runs"))
            for layer, data in layer_analysis.items()
            if layer == CATEGORY_SCOPE
            or layer == "union_mixed_window"
            or any(layer.startswith(f"segment_{index}_") for index in selected_ranks)
        ],
        "category_30d": {
            "scope_id": "category_30d",
            "denominator": denominators["N_category_30d"],
            "need_stats": _strict_need_stats(category["needs"], CATEGORY_SCOPE),
            "kano": _strict_kano(category["kano"], CATEGORY_SCOPE),
            "satisfaction_top10": _strict_ranked_items(category["satisfactions"], CATEGORY_SCOPE),
            "dissatisfaction_top10": _strict_ranked_items(category["dissatisfactions"], CATEGORY_SCOPE),
            "use_scenes": _strict_labeled_stats(category["scenarios"]),
            "current_new_needs": _strict_innovations(category["ideas"], CATEGORY_SCOPE),
            "reverse_needs": [item for item in _strict_kano(category["kano"], CATEGORY_SCOPE) if item["classification"] == "R"],
            "significant_recent_topics": _strict_labeled_stats(category["needs"][:10]),
        },
        "segment_analyses": segment_analyses,
        "union_analysis": {
            "scope_id": "union_mixed_window",
            "share_label": "混合窗口研究语料占比",
            "denominator": denominators["N_union_mixed_window"],
            "need_stats": union_need_stats,
            "shared_needs": [item for item in union_need_stats if item["need_code"] in shared_codes],
            "extreme_scenarios": _strict_labeled_stats(union["scenarios"]),
            "kano_differences": [],
            "new_needs": _strict_innovations(union["ideas"], "union_mixed_window"),
            "development_priorities": [],
            "interpretation_warning": "联合语料由全品类30天和细分90天定向采集合并，只用于证据综合与产品开发，不代表市场总体消费者比例。",
        },
        "supply_validation": [],
        "product_concepts": _planned_product_concepts(segments),
        "report_artifacts": {
            "coding_json": {"path": str(coding_resolved), "sha256": coding_sha},
            "analysis_json": {"path": str(analysis_output), "status": "written"},
            "html_report": {"path": str(report_output), "status": "planned"},
            "image_paths": [],
            "embedded_image_count": 0,
            "all_product_images_ready": False,
            "standalone_html": False,
            "external_runtime_dependencies": [],
            "original_dashboard_sha256_before": dashboard_sha,
            "original_dashboard_sha256_after": dashboard_sha,
            "status": "partial",
        },
        "limitations": [
            {
                "scope": "social_voice",
                "description": "社媒消费者声音不是概率抽样，且需求属性为方向性推断。",
                "impact": "占比只能解释为当前研究语料分布。",
                "mitigation": "完整证据保留在JSON，并安排正式问卷和场景测试。",
                "affects_confidence": True,
            }
        ],
        "future_validation_checklist": [
            {
                "validation_id": "formal_kano_survey",
                "validation_type": "formal_kano_survey",
                "status": "planned",
                "objective": "用功能/反功能成对问卷验证方向性需求属性分类。",
                "owner_role": "用户研究",
                "trigger": "进入工程立项前",
                "method": "对目标消费者分层发放标准功能/反功能问卷。",
                "acceptance_criteria": "关键Must/One-dimensional/Attractive分类达到预设样本与一致性门槛。",
                "dependencies": ["目标用户招募", "问卷设计"],
            },
            {
                "validation_id": "engineering_reliability",
                "validation_type": "engineering_reliability",
                "status": "planned",
                "objective": "验证结构、材料与极端场景可靠性。",
                "owner_role": "结构工程",
                "trigger": "概念方案冻结后",
                "method": "进行振动、热循环、寿命与道路场景测试。",
                "acceptance_criteria": "所有Must功能达到产品方案中的量化验收指标。",
                "dependencies": ["工程样机", "测试工装"],
            },
            {
                "validation_id": "patent_and_regulatory",
                "validation_type": "patent_freedom_to_operate",
                "status": "planned",
                "objective": "筛查核心结构专利与目标站点合规风险。",
                "owner_role": "知识产权与合规",
                "trigger": "开模和认证投入前",
                "method": "执行FTO检索并建立法规/认证清单。",
                "acceptance_criteria": "高风险权利要求有规避设计或明确授权路径。",
                "dependencies": ["结构图", "目标销售站点"],
            },
            {
                "validation_id": "regulatory_and_certification",
                "validation_type": "regulatory_and_certification",
                "status": "planned",
                "objective": "确认目标站点、电子功能与车内使用相关法规认证要求。",
                "owner_role": "产品合规",
                "trigger": "电子与结构方案冻结前",
                "method": "建立适用法规、材料、无线/充电和运输认证矩阵。",
                "acceptance_criteria": "所有适用要求都有测试、文件或豁免依据。",
                "dependencies": ["目标站点", "最终技术方案", "材料清单"],
            },
        ],
        "llm_calls": copy.deepcopy(document.get("llm_calls", [])),
    }
    return result


def _detect_image_mime(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(payload) >= 12 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if len(payload) >= 12 and payload[4:8] == b"ftyp" and payload[8:12] in {
        b"avif",
        b"avis",
    }:
        return "image/avif"
    if payload.startswith(b"BM"):
        return "image/bmp"
    return None


def _image_file_info(path: Path) -> dict[str, str]:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ContractError(f"概念图不存在：{path}") from exc
    except OSError as exc:
        raise ContractError(f"无法读取概念图：{path}", [str(exc)]) from exc
    mime_type = _detect_image_mime(payload)
    if mime_type is None:
        raise ContractError(f"概念图内容不是受支持的真实图片格式：{path}")
    extension_mime, _ = mimetypes.guess_type(path.name)
    if (
        extension_mime
        and extension_mime.startswith("image/")
        and extension_mime.casefold() != mime_type.casefold()
    ):
        raise ContractError(
            f"概念图扩展名与真实MIME不一致：{path}",
            [f"extension={extension_mime}", f"actual={mime_type}"],
        )
    return {
        "path": str(path.resolve()),
        "mime_type": mime_type,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "data_uri": f"data:{mime_type};base64,{base64.b64encode(payload).decode('ascii')}",
    }


def _data_uri(path: Path) -> str:
    return _image_file_info(path)["data_uri"]


def _parse_images(values: Sequence[str]) -> dict[str, dict[str, Any]]:
    images: dict[str, dict[str, Any]] = {}
    for raw in values:
        if "=" not in raw:
            raise ContractError("--image 必须使用 NAME=/absolute/path.ext 格式")
        name, raw_path = raw.split("=", 1)
        name = name.strip()
        if not name:
            raise ContractError("--image 的 NAME 不能为空")
        path = Path(raw_path).expanduser().resolve()
        if name in images:
            raise ContractError(f"重复的概念图名称：{name}")
        image_info = _image_file_info(path)
        images[name] = {
            "name": name,
            "filename": path.name,
            **image_info,
            "disclaimer": "AI概念表达，非工程图或认证结果",
        }
    return images


def _json_for_inline_script(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _replace_required_placeholder(template: str, names: Sequence[str], value: str) -> str:
    output = template
    found = False
    for name in names:
        if name in output:
            output = output.replace(name, value)
            found = True
    if not found:
        raise ContractError(f"HTML模板缺少占位符：{' 或 '.join(names)}")
    return output


def _replace_optional_placeholder(template: str, names: Sequence[str], value: str) -> str:
    output = template
    for name in names:
        output = output.replace(name, value)
    return output


def _offline_dependency_errors(html_text: str) -> list[str]:
    errors: list[str] = []
    checks = (
        (r"<script\b|</script\s*>", "禁止任何脚本元素"),
        (r"<(?:iframe|frame|frameset)\b", "禁止 iframe/frame 嵌入内容"),
        (r"<form\b", "禁止表单元素"),
        (r"<base\b", "禁止 base 元素改变资源或链接基准"),
        (r"<[^>]+\son[a-z][a-z0-9_-]*\s*=", "禁止内联事件处理器"),
        (
            r"<[^>]+(?:href|src|action|formaction)\s*=\s*['\"]?\s*javascript\s*:",
            "禁止 javascript: URL",
        ),
        (
            r"<link\b[^>]*\bhref\s*=\s*(?:['\"](?!data:|#)|(?!(?:data:|#|['\"]))[^\s>])",
            "link资源必须内嵌为 data URI或使用页内片段",
        ),
        (
            r"<(?:img|source|video|audio|track|iframe|embed|input)\b[^>]*\b(?:src|srcset|poster)\s*=\s*(?:['\"](?!data:)|(?!(?:data:|['\"]))[^\s>])",
            "媒体资源必须内嵌为 data URI",
        ),
        (
            r"<object\b[^>]*\bdata\s*=\s*(?:['\"](?!data:)|(?!(?:data:|['\"]))[^\s>])",
            "object资源必须内嵌为 data URI",
        ),
        (
            r"<(?:image|use)\b[^>]*\b(?:href|xlink:href)\s*=\s*(?:['\"](?!data:|#)|(?!(?:data:|#|['\"]))[^\s>])",
            "SVG资源必须内嵌为 data URI或使用页内片段",
        ),
        (r"<meta\b[^>]*http-equiv\s*=\s*['\"]?refresh", "禁止 meta refresh 运行时导航"),
        (r"@import\b", "禁止 CSS @import"),
        (r"\bfetch\s*\(", "禁止运行时 fetch"),
        (r"\bXMLHttpRequest\b", "禁止运行时 XMLHttpRequest"),
        (r"\bWebSocket\s*\(", "禁止运行时 WebSocket"),
        (r"\bEventSource\s*\(", "禁止运行时 EventSource"),
        (r"\bimport\s*\(", "禁止动态 import"),
    )
    for pattern, message in checks:
        if re.search(pattern, html_text, flags=re.IGNORECASE):
            errors.append(message)
    for match in re.finditer(
        r"url\(\s*(['\"]?)(.*?)\1\s*\)", html_text, flags=re.IGNORECASE | re.DOTALL
    ):
        target = match.group(2).strip()
        if target and not target.casefold().startswith("data:") and not target.startswith("#"):
            errors.append("CSS url() 资源必须内嵌为 data URI")
            break
    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", html_text)))
    if unresolved:
        errors.append(f"模板仍有未替换占位符：{unresolved}")
    if not _has_required_report_csp(html_text):
        errors.append("HTML必须包含固定严格Content-Security-Policy")
    return errors


class _CspMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.policies: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() != "meta":
            return
        values = {str(name).casefold(): value for name, value in attrs}
        if str(values.get("http-equiv") or "").casefold() == "content-security-policy":
            self.policies.append(str(values.get("content") or ""))


def _normalized_csp(value: str) -> dict[str, tuple[str, ...]] | None:
    directives: dict[str, tuple[str, ...]] = {}
    for raw_directive in value.split(";"):
        parts = raw_directive.strip().split()
        if not parts:
            continue
        name = parts[0].casefold()
        if name in directives:
            return None
        directives[name] = tuple(token.casefold() for token in parts[1:])
    return directives


def _has_required_report_csp(html_text: str) -> bool:
    parser = _CspMetaParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        return False
    required = _normalized_csp(REQUIRED_REPORT_CSP)
    return required is not None and any(
        _normalized_csp(policy) == required for policy in parser.policies
    )


def _escape(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


KANO_PRESENTATION = {
    "M": ("必备型", "缺失会直接造成不接受或差评，产品必须稳定满足。"),
    "O": ("期望型", "表现越好，满意度越高，应作为核心性能持续优化。"),
    "A": ("魅力型", "不是购买底线，但做好后有机会形成惊喜和溢价。"),
    "I": ("无差异型", "用户当前不敏感，不应优先投入成本。"),
    "R": ("反向型", "部分用户会排斥该功能，需谨慎设计或提供可选方案。"),
    "evidence_insufficient": ("证据不足", "现有留言不足以稳定归类，先作为待验证假设。"),
}

CONFIDENCE_PRESENTATION = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

SCOPE_PRESENTATION = {
    "category_30d": "全品类 · 最近30天",
    "segment_1_90d": "Top1细分 · 最近90天",
    "segment_2_90d": "Top2细分 · 最近90天",
    "segment_3_90d": "Top3细分 · 最近90天",
    "segment_1_recent_30d": "Top1细分 · 最近30天",
    "segment_2_recent_30d": "Top2细分 · 最近30天",
    "segment_3_recent_30d": "Top3细分 · 最近30天",
    "segment_90d": "细分 · 最近90天",
    "segment_recent_30d": "细分 · 最近30天",
    "union_mixed_window": "联合研究语料",
}

PRESENTATION_VALUE_LABELS = {
    **SCOPE_PRESENTATION,
    "high": "高",
    "medium": "中",
    "low": "低",
    "ready": "已完成",
    "partial": "部分完成",
    "failed": "未完成",
    "complete": "已完成",
    "completed": "已完成",
    "completed_from_research": "已基于研究完成",
    "planned": "已规划",
    "pending": "待处理",
    "written": "已生成",
    "validated": "已校验",
    "in_progress": "进行中",
    "blocked": "受阻",
    "not_started": "未开始",
    "not_run": "未执行",
    "not_available": "当前不可用",
    "ok": "正常",
    "inconclusive": "证据不足，暂不下结论",
    "text_no_hit": "当前已检查文本未识别",
    "few_listings": "仅发现少量供给",
    "verified_rare_supply": "已验证为稀缺供给",
    "no_verified_supply": "当前覆盖范围内未验证到供给",
    "observed_pain": "已观察到痛点",
    "solution_hypothesis": "解决方案假设",
    "supply_gap_hypothesis": "供给缺口假设",
    "validated_new_need": "已验证的新需求",
    "consumer_explicit_idea": "消费者明确提出的创意",
    "diy_workaround": "DIY或绕行方案",
    "inferred_latent_need": "从重复痛点推断的潜在需求",
    "agent_design_concept": "Agent设计创意",
    "agent_design_inference": "产品设计推导",
    "category_recent_30d": "全品类最近30天证据",
    "segment_90d": "细分完整90天证据",
    "segment_recent_30d": "细分最近30天证据",
    "segment_days_31_90": "细分第31–90天证据",
    "cross_layer": "多层交叉证据",
    "both": "销量前30款与累计80%销量双重覆盖",
    "top_30_by_sales": "销量前30款",
    "cumulative_80_percent_sales": "累计覆盖80%销量",
    "title": "标题",
    "parameter": "参数",
    "web_supply": "公开供给页面",
    "formal_kano_survey": "正式需求属性问卷",
    "engineering_reliability": "工程可靠性测试",
    "user_and_scenario_test": "用户与场景测试",
    "patent_freedom_to_operate": "专利自由实施检索",
    "regulatory_and_certification": "法规与认证核查",
    "absence_complaint": "缺失时的抱怨",
    "presence_baseline": "存在即被视为基本配置",
    "performance_positive": "表现越好越满意",
    "performance_negative": "表现越差越不满",
    "surprise_delight": "带来惊喜",
    "explicit_feature_wish": "明确功能愿望",
    "explicit_indifference": "明确无所谓",
    "explicit_rejection": "明确拒绝",
    "harm_or_negative_utility": "可能造成反效果",
    "conflicting_or_weak": "证据冲突或强度不足",
    "daily_navigation": "日常导航",
    "daily_commute": "日常通勤",
    "daily_android_auto": "日常使用 Android Auto",
    "dashboard_mount": "仪表台安装",
    "portrait_navigation": "竖屏导航",
    "road_trip": "长途自驾",
    "hot_weather": "高温天气",
    "hot_cabin": "高温车舱",
    "summer_cooling": "夏季制冷场景",
    "winter_heating": "冬季制热场景",
    "air_conditioning_cycle": "空调冷热循环",
    "custom_install": "定制安装",
    "diy_install": "DIY安装",
    "audio_retrofit": "车载音响改装",
    "foldable_phone_unfolded": "折叠屏展开使用",
    "long_haul_cab": "长途驾驶舱",
    "long_haul_rough_road": "长途颠簸路面",
    "oilfield_dirt_road": "油田土路",
    "towing": "拖挂驾驶",
    "tesla_daily_drive": "Tesla日常驾驶",
    "tesla_fsd": "Tesla辅助驾驶场景",
    "tesla_navigation": "Tesla导航场景",
    "tesla_stock_infotainment": "Tesla原车屏幕场景",
    "commercial_driver_compliance": "营运驾驶合规场景",
    "fleet_camera_monitored_cab": "车队摄像头监控驾驶舱",
    "tesla_model_y_refresh": "Model Y焕新版",
    "truck_driver": "卡车司机",
    "commercial_truck_driver": "营运卡车司机",
    "oilfield_truck_driver": "油田卡车司机",
    "short_stature_truck_driver": "身材较矮的卡车司机",
    "slip_seat_driver": "轮换驾驶员",
    "pickup_driver": "皮卡驾驶者",
    "pickup_tow_driver": "皮卡拖挂驾驶者",
    "tesla_owner": "Tesla车主",
    "tesla_model_y_owner": "Model Y车主",
    "hot_climate_tesla_owner": "高温地区Tesla车主",
    "minimalist_tesla_owner": "偏好极简内饰的Tesla车主",
    "side_button_phone_owner": "侧键位置特殊的手机用户",
    "foldable_phone_owner": "折叠屏手机用户",
    "heavy_phone_owner": "大屏或重型手机用户",
    "compact_cockpit_driver": "紧凑驾驶舱用户",
    "diy_installer": "DIY安装用户",
    "classic_car": "经典老车用户",
    "compact_car": "紧凑型汽车用户",
    "small_car": "小型汽车用户",
    "older_compact_car": "老款紧凑型汽车用户",
    "older_sedan": "老款轿车用户",
    "enthusiast_car": "汽车爱好者",
    "performance_car": "性能车用户",
    "family_minivan": "家庭MPV用户",
    "fabric_dashboard": "织物仪表台用户",
    "pickup_dashboard": "皮卡仪表台用户",
    "mack_pinnacle_cab": "Mack Pinnacle驾驶舱",
    "secure_hold": "稳固不掉落",
    "vehicle_fit": "车型与内饰适配",
    "non_obstructive": "不遮挡且不干涉驾驶",
    "wireless_charging": "无线充电",
    "adjustability": "可调角度与触达距离",
    "preserve_storage": "保留杯架与储物空间",
    "removable_no_damage": "可拆无损安装",
    "durable_material": "材料与连接耐久",
    "phone_compatibility": "手机与厚壳兼容",
    "cooling_thermal": "手机热管理",
    "camera_compliance": "摄像头与合规位置",
    "quick_access": "单手快取快放",
    "shock_vibration": "振动与冲击隔离",
    "multi_device_modularity": "多设备模块化",
    "aesthetic_compact": "紧凑与内饰融合",
    "button_clearance": "侧键避让",
    "cable_management": "线缆管理",
    "safety_distraction": "降低驾驶分心",
    "foldable_phone_support": "折叠屏展开态承托",
    "style_customization": "个性化造型",
    "heat_resistance": "耐高低温循环",
    "navigation_alternative": "原车屏幕替代",
}

PRESENTATION_KEY_LABELS = {
    "status": "状态",
    "outputs": "产出",
    "success_or_decision_gate": "进入下一步的条件",
    "feature": "功能",
    "reason": "原因",
    "acceptance_criteria": "验收标准",
    "metric": "指标",
    "target": "目标",
    "test_method": "测试方法",
    "description": "说明",
    "origin_type": "证据层级",
    "classification": "需求属性类型",
    "design_response": "产品应对",
    "colors": "颜色",
    "finishes": "表面处理",
    "visual_language": "视觉语言",
    "currency": "币种",
    "min": "最低价",
    "max": "最高价",
    "assumption": "假设",
    "items_checked": "检查数量",
    "notes": "说明",
    "claim": "发现",
    "supports_gap": "是否支持供给缺口",
    "finding": "判断",
    "claim_boundary": "结论边界",
    "need_code": "需求",
    "evidence_origins": "证据来源",
    "priority": "优先级",
    "action": "建议动作",
    "title": "标题检查",
    "parameters": "参数检查",
    "images": "图片检查",
    "details": "详情页检查",
    "synonym_solutions": "同义解决方案",
    "agent_reach_web": "公开网页补充",
    "asin": "ASIN",
    "url": "链接",
    "prompt_version": "提示词版本",
    "purpose": "用途",
    "concept_name": "概念名称",
    "product_definition": "产品定义",
    "target_user_scene": "目标用户与场景",
    "design_language": "设计语言",
    "composition": "画面构图",
    "materials": "材料",
    "critical_features": "关键功能",
    "must_show": "必须展示",
    "forbidden": "禁止出现",
    "impact": "影响",
    "mitigation": "应对方式",
    "affects_confidence": "是否影响置信度",
}

PRESENTATION_HIDDEN_KEYS = frozenset(
    {
        "voice_ids",
        "evidence_voice_ids",
        "evidence_ids",
        "demand_voice_ids",
        "supply_evidence_refs",
        "evidence_origins",
        "target_segment_ids",
        "scope_id",
        "segment_id",
        "innovation_id",
        "finding_id",
        "validation_id",
        "backend",
        "query_ids",
        "collection_scopes",
        "temporal_buckets",
        "source_status",
        "source_statuses",
        "evidence_type",
        "evidence_counts",
        "evidence_type_counts",
        "category_evidence_counts",
        "classified_voice_count",
    }
)


def _display_text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    raw = str(value)
    if raw in KANO_PRESENTATION:
        return KANO_PRESENTATION[raw][0]
    if raw in PRESENTATION_VALUE_LABELS:
        return PRESENTATION_VALUE_LABELS[raw]
    replacements = (
        ("KANO", "需求属性"),
        ("证据 ID", "原声引用"),
        ("证据ID", "原声引用"),
        ("evidence_ids", "原声引用"),
        ("evidence_id", "原声引用"),
        ("来源状态", "渠道采集情况"),
        ("证据类型计数", "证据构成"),
        ("directional_inference=true", "基于消费者声音的方向性判断"),
        ("formal_survey=false", "未进行正式需求属性问卷"),
        ("evidence_insufficient", "证据不足"),
        ("conflicting_or_weak", "证据冲突或强度不足"),
        ("segment_1_90d", "Top1细分"),
        ("segment_2_90d", "Top2细分"),
        ("segment_3_90d", "Top3细分"),
        ("category_30d", "全品类最近30天"),
        ("text_no_hit", "当前已检查文本未识别"),
    )
    for source, target in replacements:
        raw = raw.replace(source, target)
    raw = re.sub(r"(?i)evidence[\s_-]*ids?", "原声引用", raw)
    raw = re.sub(r"(?i)source[\s_-]*status(?:es)?", "渠道采集情况", raw)
    return raw


def _confidence_label(value: Any) -> str:
    return CONFIDENCE_PRESENTATION.get(str(value or "low"), "低")


def _confidence_badge(value: Any) -> str:
    raw = str(value or "low")
    return (
        f'<span class="confidence-badge {_escape(raw)}">'
        f'证据强度：{_escape(_confidence_label(raw))}</span>'
    )


def _kano_label(value: Any) -> str:
    return KANO_PRESENTATION.get(
        str(value or "evidence_insufficient"),
        KANO_PRESENTATION["evidence_insufficient"],
    )[0]


def _scope_label(value: Any) -> str:
    return SCOPE_PRESENTATION.get(str(value or ""), _display_text(value))


def _platform_label(value: Any) -> str:
    raw = str(value or "").strip()
    return PLATFORM_PRESENTATION.get(raw.casefold(), raw or "未知平台")


def _stop_reason_label(value: Any) -> str:
    return STOP_REASON_PRESENTATION.get(str(value or ""), "未记录")


def _date_only(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    return match.group(1) if match else _display_text(raw)


def _structured_html(value: Any) -> str:
    if isinstance(value, Mapping):
        visible_items = [
            (key, item)
            for key, item in value.items()
            if str(key) not in PRESENTATION_HIDDEN_KEYS
            and str(key) in PRESENTATION_KEY_LABELS
        ]
        if not visible_items:
            return "—"
        return '<dl class="structured-list">' + "".join(
            f"<dt>{_escape(PRESENTATION_KEY_LABELS.get(str(key), _display_text(key)))}</dt>"
            f"<dd>{_structured_html(item)}</dd>"
            for key, item in visible_items
        ) + "</dl>"
    if isinstance(value, list):
        if not value:
            return "—"
        return '<ul class="structured-list">' + "".join(
            f"<li>{_structured_html(item)}</li>" for item in value
        ) + "</ul>"
    return _escape(_display_text(value))


def _format_percent(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _format_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return _escape(value)


def _render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    extra_class: str = "",
) -> str:
    head = "".join(f"<th scope=\"col\">{_escape(item)}</th>" for item in headers)
    body_rows = []
    for row in rows:
        if len(row) != len(headers):
            raise ContractError(
                "HTML表格列数不一致",
                [f"headers={len(headers)}", f"row={len(row)}"],
            )
        body_rows.append(
            "<tr>"
            + "".join(
                f'<td data-label="{_escape(headers[index])}">{item}</td>'
                for index, item in enumerate(row)
            )
            + "</tr>"
        )
    if not body_rows:
        body_rows.append(
            f"<tr><td colspan=\"{len(headers)}\" class=\"empty-state\">暂无有效数据</td></tr>"
        )
    return (
        f'<div class="table-wrap table-frame {_escape(extra_class)}"><table class="data-table"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def _section_head(
    section_id: str, kicker: str, title: str, description: str
) -> str:
    return (
        f'<div class="section-head" id="{_escape(section_id)}">'
        f'<div><p class="section-kicker">{_escape(kicker)}</p><h2>{_escape(title)}</h2></div>'
        f'<p>{_escape(description)}</p></div>'
    )


def _evidence_id_html(values: Any, *, limit: int = 8) -> str:
    if not isinstance(values, list) or not values:
        return "—"
    displayed = values[:limit]
    suffix = f" +{len(values) - limit}" if len(values) > limit else ""
    return "<code>" + _escape(", ".join(str(value) for value in displayed) + suffix) + "</code>"


def _safe_taxonomy_display(item: Mapping[str, Any], kind: str) -> str:
    for value in (item.get("label"), item.get("code"), item.get("key")):
        raw = str(value or "").strip()
        if raw in PRESENTATION_VALUE_LABELS:
            return PRESENTATION_VALUE_LABELS[raw]
    raw_label = str(item.get("label") or "").strip()
    if re.search(r"[\u3400-\u9fff]", raw_label):
        return raw_label
    return "未归类消费者类型" if kind == "persona" else "未归类使用场景"


def _render_ranked_items(
    title: str,
    items: Any,
    *,
    limit: int = 10,
    presentation_kind: str | None = None,
) -> str:
    source = items if isinstance(items, list) else []
    blocks: list[str] = []
    for rank, item in enumerate(source[:limit], start=1):
        if not isinstance(item, Mapping):
            continue
        label = (
            _safe_taxonomy_display(item, presentation_kind)
            if presentation_kind in {"scene", "persona"}
            else _display_text(
                item.get("label")
                or item.get("need_label")
                or item.get("name_zh")
                or item.get("key")
                or item.get("need_code")
            )
        )
        share = item.get("voice_share")
        try:
            bar_width = max(0.0, min(float(share or 0), 1.0)) * 100
        except (TypeError, ValueError):
            bar_width = 0.0
        blocks.append(
            '<article class="insight-row">'
            f'<div class="insight-rank">{rank:02d}</div>'
            '<div class="insight-content">'
            f'<h4>{_escape(label)}</h4>'
            '<div class="insight-bar" aria-hidden="true">'
            f'<span style="--value:{bar_width:.1f}%"></span></div>'
            '<div class="insight-meta">'
            f'<strong>{_format_number(item.get("voice_count"))} 条 · {_format_percent(share)}</strong>'
            f'<span>{_format_number(item.get("author_count"))} 位作者</span>'
            f'<span>{_format_number(item.get("thread_count"))} 个讨论线程</span>'
            f'<span>{_format_number(item.get("platform_count"))} 个平台</span>'
            "</div></div>"
            + _confidence_badge(
                item.get("evidence_confidence") or item.get("confidence") or "low"
            )
            + "</article>"
        )
    return (
        f'<section class="subsection"><h3>{_escape(title)}</h3>'
        + ('<div class="insight-list">' + "".join(blocks) + "</div>" if blocks else '<p class="empty-state">暂无有效数据</p>')
        + "</section>"
    )


def _render_kano(items: Any, *, limit: int = 8) -> str:
    raw_source = items if isinstance(items, list) else []
    source = sorted(
        (item for item in raw_source if isinstance(item, Mapping)),
        key=lambda item: (
            1
            if str(item.get("classification") or item.get("category"))
            == "evidence_insufficient"
            else 0,
            -int(item.get("voice_count") or 0),
        ),
    )[:limit]
    blocks: list[str] = []
    for item in source:
        category = str(
            item.get("classification") or item.get("category") or "evidence_insufficient"
        )
        css_category = category.casefold() if category != "evidence_insufficient" else "u"
        need_name = _display_text(
            item.get("name_zh")
            or item.get("need_label")
            or item.get("need_key")
            or item.get("need_code")
        )
        product_meaning = KANO_PRESENTATION.get(
            category, KANO_PRESENTATION["evidence_insufficient"]
        )[1]
        blocks.append(
            f'<article class="kano-decision kano-{_escape(css_category)}">'
            '<div class="kano-decision-head">'
            f'<h4>{_escape(need_name)}</h4>'
            f'<span class="tag kano-{_escape(css_category)}">{_escape(_kano_label(category))}</span>'
            "</div>"
            f'<p class="kano-meaning">{_escape(product_meaning)}</p>'
            '<div class="kano-metrics">'
            f'<span>{_format_number(item.get("voice_count"))} 条留言</span>'
            f'<span>{_format_percent(item.get("voice_share"))}</span>'
            + _confidence_badge(item.get("confidence") or "low")
            + "</div>"
            f'<p class="kano-rationale"><strong>判断依据：</strong>{_escape(_display_text(item.get("rationale") or "暂无明确依据"))}</p>'
            "</article>"
        )
    legend = "".join(
        f'<span class="tag kano-{_escape(code.casefold() if code != "evidence_insufficient" else "u")}">{_escape(label)}</span>'
        for code, (label, _) in KANO_PRESENTATION.items()
    )
    return (
        f'<div class="kano-legend" aria-label="需求属性类型图例">{legend}</div>'
        + ('<div class="kano-decision-list">' + "".join(blocks) + "</div>" if blocks else '<p class="empty-state">暂无足够证据进行需求属性判断。</p>')
    )


def _render_scope_summary(analysis: Mapping[str, Any]) -> str:
    denominators = analysis.get("denominators")
    if not isinstance(denominators, Mapping):
        denominators = {}
    labels = (
        ("N_category_30d", "全品类30天"),
        ("N_segment_1_90d", "Top1细分90天"),
        ("N_segment_2_90d", "Top2细分90天"),
        ("N_segment_3_90d", "Top3细分90天"),
        ("N_union_mixed_window", "联合硬身份唯一语料"),
    )
    cards = []
    for key, label in labels:
        cards.append(
            '<article class="metric-card metric">'
            f'<div class="metric-label">{_escape(label)}</div>'
            f'<div class="metric-value">{_format_number(denominators.get(key))}</div>'
            '<div class="metric-note">条有效留言（仅合并同一底层留言）</div>'
            "</article>"
        )
    return '<div class="metric-grid">' + "".join(cards) + "</div>"


def _receipt_for_presentation(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    receipt = analysis.get("collection_receipt")
    if isinstance(receipt, Mapping):
        return receipt
    plan = _research_plan(analysis)
    denominators = (
        analysis.get("denominators")
        if isinstance(analysis.get("denominators"), Mapping)
        else {}
    )
    funnel = (
        analysis.get("collection_funnel")
        if isinstance(analysis.get("collection_funnel"), Mapping)
        else {}
    )
    return _collection_receipt_summary(
        coding_path=None,
        research_plan=plan,
        denominators=denominators,
        collection_funnel=funnel,
    )


def _report_partial_gaps(analysis: Mapping[str, Any]) -> list[str]:
    gaps = _sample_gate_gaps(analysis)
    receipt = _receipt_for_presentation(analysis)
    deadline = (
        receipt.get("deadline_status")
        if isinstance(receipt.get("deadline_status"), Mapping)
        else {}
    )
    if deadline.get("deadline_exceeded") is True:
        gaps.append("完整任务已达到总时间上限")
    concepts = analysis.get("product_concepts")
    concept_items = [
        item
        for item in (concepts if isinstance(concepts, list) else [])
        if isinstance(item, Mapping)
    ]
    if len(concept_items) < 3:
        gaps.append(f"产品方向（{len(concept_items)}/3）")
    ready_images = sum(
        1
        for item in concept_items
        if isinstance(item.get("image_artifact"), Mapping)
        and item["image_artifact"].get("status") == "ok"
    )
    if ready_images < 3:
        gaps.append(f"产品概念图（{ready_images}/3）")
    return list(dict.fromkeys(gaps))


def _format_minutes(value: Any) -> str:
    number = _nullable_nonnegative_number(value)
    if number is None:
        return "未记录"
    return f"{number:,.1f}".rstrip("0").rstrip(".")


def _format_usd(value: Any) -> str:
    number = _nullable_nonnegative_number(value)
    if number is None:
        return "未记录"
    return f"${number:,.2f}"


def _render_compact_execution_receipt(analysis: Mapping[str, Any]) -> str:
    """Render the run facts an operator needs before reading any insight."""
    plan = _research_plan(analysis)
    level = str(plan.get("research_level") or RESEARCH_LEVEL_DEFAULT)
    target = (
        plan.get("sample_target")
        if isinstance(plan.get("sample_target"), Mapping)
        else {}
    )
    budget = (
        plan.get("time_budget_minutes")
        if isinstance(plan.get("time_budget_minutes"), Mapping)
        else {}
    )
    receipt = _receipt_for_presentation(analysis)
    attainment = (
        receipt.get("target_attainment")
        if isinstance(receipt.get("target_attainment"), Mapping)
        else {}
    )
    time_usage = (
        receipt.get("time_usage_minutes")
        if isinstance(receipt.get("time_usage_minutes"), Mapping)
        else {}
    )
    total_actual = int(attainment.get("total_valid") or 0)
    total_min = int(attainment.get("total_valid_min") or target.get("total_valid_min") or 0)
    total_max = int(attainment.get("total_valid_max") or target.get("total_valid_max") or 0)
    route_cards: list[str] = []
    for route in (
        attainment.get("routes")
        if isinstance(attainment.get("routes"), list)
        else []
    ):
        if not isinstance(route, Mapping):
            continue
        actual = int(route.get("actual_valid") or 0)
        minimum = int(route.get("valid_min") or 0)
        maximum = int(route.get("valid_max") or 0)
        met = actual >= minimum
        delta = (
            "已达下限"
            if met
            else f"还缺 {_format_number(max(0, minimum - actual))} 条"
        )
        route_cards.append(
            f'<article class="receipt-route {"met" if met else "gap"}">'
            f'<span>{_escape(_scope_label(route.get("scope_id")))} · {_format_percent(route.get("share"))}配额</span>'
            f'<strong>{_format_number(actual)}<small> / {_format_number(minimum)}–{_format_number(maximum)} 条</small></strong>'
            f'<em>{_escape(delta)}</em></article>'
        )
    valid_platforms = int(attainment.get("valid_platforms") or 0)
    min_platforms = int(attainment.get("min_platforms") or target.get("min_platforms") or 0)
    platform_gate = "已达标" if valid_platforms >= min_platforms else "未达标"
    collection_actual = _format_minutes(time_usage.get("collection"))
    total_time_actual = _format_minutes(time_usage.get("total"))
    total_met = bool(attainment.get("target_met"))
    return (
        '<section class="execution-receipt" aria-label="本轮执行回执">'
        '<header><div><span>本轮执行回执</span>'
        f'<strong>{_escape(RESEARCH_LEVEL_PRESENTATION.get(level, "快速研究"))} · '
        f'{_format_number(total_actual)} / {_format_number(total_min)}–{_format_number(total_max)} 条有效留言</strong></div>'
        f'<b class="receipt-gate {"met" if total_met else "gap"}">{"采集门槛已满足" if total_met else "采集门槛未满足"}</b></header>'
        '<div class="receipt-routes">'
        + "".join(route_cards)
        + '</div><div class="receipt-meta">'
        f'<span><b>平台门槛</b>{_format_number(valid_platforms)} / 至少 {_format_number(min_platforms)} 个 · {_escape(platform_gate)}</span>'
        f'<span><b>采集耗时</b>{_escape(collection_actual)} / {_format_number(budget.get("collection"))} 分钟</span>'
        f'<span><b>任务耗时</b>{_escape(total_time_actual)} / {_format_number(budget.get("total"))} 分钟</span>'
        f'<span><b>停止原因</b>{_escape(_stop_reason_label(analysis.get("stop_reason")))}</span>'
        '</div></section>'
    )


def _render_windows_and_sources(analysis: Mapping[str, Any]) -> str:
    windows = analysis.get("windows") if isinstance(analysis.get("windows"), Mapping) else {}
    category_window = windows.get("category_30d") if isinstance(windows.get("category_30d"), Mapping) else {}
    segment_window = windows.get("segment_90d") if isinstance(windows.get("segment_90d"), Mapping) else {}
    segments = analysis.get("segments") if isinstance(analysis.get("segments"), list) else []
    analyses = analysis.get("segment_analyses") if isinstance(analysis.get("segment_analyses"), list) else []
    analysis_by_segment = {
        item.get("segment_id"): item
        for item in analyses
        if isinstance(item, Mapping)
    }
    segment_rows = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        segment_analysis = analysis_by_segment.get(segment.get("segment_id"), {})
        segment_rows.append(
            [
                _format_number(segment.get("rank")),
                _escape(segment.get("dimension")),
                _escape(segment.get("feature")),
                (
                    f'{_format_number(segment.get("listing_count"))}款 · '
                    f'Listing {_format_percent(segment.get("listing_share"))} / '
                    f'销量 {_format_percent(segment.get("sales_share"))}'
                ),
                _format_number(segment.get("supply_demand_index")),
                f'{_format_number(segment_analysis.get("denominator_90d"))} 条',
            ]
        )
    quality = analysis.get("scope_quality") if isinstance(analysis.get("scope_quality"), list) else []
    quality_map = {
        item.get("scope_id"): item
        for item in quality
        if isinstance(item, Mapping)
    }
    quality_rows = []
    for scope_id in (
        "category_30d",
        "segment_1_90d",
        "segment_2_90d",
        "segment_3_90d",
        "union_mixed_window",
    ):
        item = quality_map.get(scope_id)
        if not isinstance(item, Mapping):
            continue
        quality_rows.append(
            [
                _escape(_scope_label(scope_id)),
                _format_number(item.get("valid_voice_count")),
                _format_number(item.get("identified_author_count")),
                _format_number(item.get("thread_count")),
                _format_number(item.get("platform_count")),
                _format_percent(item.get("largest_platform_share")),
                _confidence_badge(item.get("confidence") or "low"),
            ]
        )
    plan = _research_plan(analysis)
    level_labels = {"quick": "快速", "standard": "标准", "deep": "深度"}
    level = str(plan.get("research_level") or RESEARCH_LEVEL_DEFAULT)
    target = plan.get("sample_target") if isinstance(plan.get("sample_target"), Mapping) else {}
    budget = plan.get("time_budget_minutes") if isinstance(plan.get("time_budget_minutes"), Mapping) else {}
    expected_duration = {
        "quick": "35–55",
        "standard": "50–85",
        "deep": "70–110",
    }.get(level, "35–55")
    plan_cards = (
        '<div class="metric-grid">'
        f'<article class="metric-card metric"><div class="metric-label">研究档位</div><div class="metric-value">{_escape(level_labels.get(level, "快速"))}</div><div class="metric-note">固定采集口径</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">有效留言目标</div><div class="metric-value">{_format_number(target.get("total_valid_min"))}–{_format_number(target.get("total_valid_max"))}</div><div class="metric-note">条</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">预计完成时间</div><div class="metric-value">{_escape(expected_duration)}</div><div class="metric-note">分钟</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">采集时间预算</div><div class="metric-value">{_format_number(budget.get("collection"))}</div><div class="metric-note">分钟</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">任务硬上限</div><div class="metric-value">{_format_number(budget.get("total"))}</div><div class="metric-note">分钟，到限立即收尾</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">平台下限</div><div class="metric-value">{_format_number(target.get("min_platforms"))}</div><div class="metric-note">个有效平台</div></article>'
        "</div>"
    )
    receipt = _receipt_for_presentation(analysis)
    attainment = (
        receipt.get("target_attainment")
        if isinstance(receipt.get("target_attainment"), Mapping)
        else {}
    )
    route_rows = []
    for route in attainment.get("routes") if isinstance(attainment.get("routes"), list) else []:
        if not isinstance(route, Mapping):
            continue
        actual = int(route.get("actual_valid") or 0)
        minimum = int(route.get("valid_min") or 0)
        route_rows.append(
            [
                _escape(_scope_label(route.get("scope_id"))),
                _format_percent(route.get("share")),
                f'{_format_number(minimum)}–{_format_number(route.get("valid_max"))} 条',
                f'{_format_number(actual)} 条',
                "已达下限" if actual >= minimum else f"未达下限，缺 {_format_number(minimum - actual)} 条",
            ]
        )
    time_usage = (
        receipt.get("time_usage_minutes")
        if isinstance(receipt.get("time_usage_minutes"), Mapping)
        else {}
    )
    setup_wait = (
        time_usage.get("unmetered_api_setup_wait")
        if isinstance(time_usage.get("unmetered_api_setup_wait"), Mapping)
        else {}
    )
    deadline_status = (
        receipt.get("deadline_status")
        if isinstance(receipt.get("deadline_status"), Mapping)
        else {}
    )
    total_time_note = (
        "分钟 · 已达到总时间上限"
        if deadline_status.get("deadline_exceeded") is True
        else (
            "分钟 · 已进入5分钟确定性收尾"
            if deadline_status.get("finalization_only") is True
            else "分钟"
        )
    )
    youtube = (
        receipt.get("youtube_quota_and_cost")
        if isinstance(receipt.get("youtube_quota_and_cost"), Mapping)
        else {}
    )
    actual_cost = youtube.get("provider_confirmed_actual_cost_usd")
    estimated_cost = youtube.get("estimated_direct_cost_usd")
    if actual_cost is not None:
        cost_value = _format_usd(actual_cost)
        cost_note = "提供方确认的直接费用"
    elif estimated_cost is not None:
        cost_value = _format_usd(estimated_cost)
        cost_note = "按价格快照估算"
    else:
        cost_value = "未记录"
        cost_note = "未知不等于0美元"
    quota_units = youtube.get("quota_units")
    quota_limit = youtube.get("daily_quota_limit")
    quota_value = (
        f'{_format_number(quota_units)} / {_format_number(quota_limit)}'
        if quota_units is not None and quota_limit is not None
        else _format_number(quota_units)
    )
    setup_value = (
        _format_minutes(setup_wait.get("minutes"))
        if setup_wait.get("recorded") is True
        else "未记录"
    )
    actual_cards = (
        '<div class="metric-grid">'
        f'<article class="metric-card metric"><div class="metric-label">实际采集耗时</div><div class="metric-value">{_escape(_format_minutes(time_usage.get("collection")))}</div><div class="metric-note">分钟</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">实际总耗时</div><div class="metric-value">{_escape(_format_minutes(time_usage.get("total")))}</div><div class="metric-note">{_escape(total_time_note)}</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">首次API准备等待</div><div class="metric-value">{_escape(setup_value)}</div><div class="metric-note">未计入上述耗时</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">YouTube配额</div><div class="metric-value">{_escape(quota_value)}</div><div class="metric-note">已用 / 单日上限（单位）</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">YouTube请求记录</div><div class="metric-value">{_format_number(youtube.get("request_entries"))}</div><div class="metric-note">次</div></article>'
        f'<article class="metric-card metric"><div class="metric-label">YouTube通道直接费用</div><div class="metric-value">{_escape(cost_value)}</div><div class="metric-note">{_escape(cost_note)}</div></article>'
        "</div>"
    )
    funnel = analysis.get("collection_funnel")
    funnel_rows: list[list[str]] = []
    stage_labels = (
        ("fetched_records", "抓取记录"),
        ("unique_records", "初步硬身份唯一记录"),
        ("within_window_records", "时间窗内记录"),
        ("relevant_records", "主题相关记录"),
        ("consumer_records", "消费者表达"),
        ("deduplicated_records", "跨查询同一留言合并后"),
        ("valid_voices", "最终有效留言"),
    )
    if isinstance(funnel, Mapping):
        funnel_rows = [
            [_escape(label), _format_number(funnel.get(field))]
            for field, label in stage_labels
        ]
    platform_rows: list[list[str]] = []
    if isinstance(funnel, Mapping):
        per_platform = funnel.get("per_platform")
        platform_items = [
            item
            for item in (per_platform if isinstance(per_platform, list) else [])
            if isinstance(item, Mapping)
        ]
        union_valid = int(funnel.get("valid_voices") or 0)
        platform_items.sort(
            key=lambda item: (
                -int(item.get("valid_voices") or 0),
                -int(item.get("fetched_records") or 0),
                str(item.get("platform") or "").casefold(),
            )
        )
        for item in platform_items:
            fetched = int(item.get("fetched_records") or 0)
            valid = int(item.get("valid_voices") or 0)
            platform_rows.append(
                [
                    _escape(_platform_label(item.get("platform"))),
                    _format_number(fetched),
                    _format_number(valid),
                    _format_percent(valid / fetched if fetched else None),
                    _format_percent(valid / union_valid if union_valid else None),
                ]
            )
    stop_reason = _stop_reason_label(analysis.get("stop_reason"))
    partial_gaps = _report_partial_gaps(analysis)
    report_artifacts = (
        analysis.get("report_artifacts")
        if isinstance(analysis.get("report_artifacts"), Mapping)
        else {}
    )
    gap_notice = (
        '<div class="method-summary"><strong>本轮未达标：</strong>'
        + _escape("；".join(partial_gaps))
        + "。报告按现有证据生成，未用低相关内容补数。</div>"
        if report_artifacts.get("status") == "partial" and partial_gaps
        else ""
    )
    return (
        '<section class="report-section panel" id="research">'
        + _section_head(
            "windows",
            "研究说明",
            "数据窗口与样本强度",
            "这部分用于判断结论能否采用，不是市场规模估算。",
        )
        + '<div class="method-summary"><strong>如何理解：</strong>全品类看最近30天，用来判断当前市场；Top3看最近90天，用来验证细分需求。硬身份去重只合并同一底层公开留言；不同评论即使语义相同也分别计数。</div>'
        + '<div class="window-strip">'
        + '<article class="window-card card"><span class="badge">当前市场</span>'
        + f'<b>全品类 · {_format_number(category_window.get("days"))} 天</b>'
        + f'<p>{_escape(_date_only(category_window.get("start_at")))} — {_escape(_date_only(category_window.get("end_at")))}</p></article>'
        + '<article class="window-card card segment-window"><span class="badge orange">细分深挖</span>'
        + f'<b>Top3细分 · {_format_number(segment_window.get("days"))} 天</b>'
        + f'<p>{_escape(_date_only(segment_window.get("start_at")))} — {_escape(_date_only(segment_window.get("end_at")))}</p></article>'
        + "</div>"
        + '<h3>研究档位与预算</h3>'
        + plan_cards
        + '<h3>四路样本目标与实际完成度</h3>'
        + _render_table(("采集路线", "计划占比", "目标区间", "实际有效留言", "完成情况"), route_rows)
        + '<h3>本轮实际耗时、YouTube通道成本与配额</h3>'
        + actual_cards
        + f'<p class="footnote">YouTube成本口径：{_escape(youtube.get("interpretation_zh") or "未记录YouTube成本口径；未知不等于0。")} 该卡只代表YouTube通道，不代表全任务总成本；其他采集通道无法可靠计价时按“未知”或“未计量”处理。首次API注册或密钥配置的人工作业不计入采集与总耗时。报告内耗时为生成时快照；最终任务耗时以同目录 collection_receipt.json 为准。</p>'
        + f'<p class="footnote">本轮停止原因：{_escape(stop_reason)}。</p>'
        + gap_notice
        + ('<h3>采集漏斗</h3>' + _render_table(("阶段", "记录数"), funnel_rows) if funnel_rows else "")
        + '<h3>逐平台样本覆盖</h3>'
        + _render_table(
            ("平台", "抓取候选", "有效留言", "抓取有效率", "有效样本贡献"),
            platform_rows,
        )
        + '<p class="footnote">抓取有效率 = 该平台有效留言 ÷ 该平台抓取候选；有效样本贡献 = 该平台有效留言 ÷ 联合有效留言。这里只展示数量与占比，不展示采集运行状态。</p>'
        + '<details class="methodology-details"><summary>查看样本覆盖与Top3筛选依据</summary>'
        + _render_scope_summary(analysis)
        + '<h3>Top3市场结构</h3>'
        + _render_table(
            ("排名", "维度", "细分", "市场结构", "供需指数", "有效留言"),
            segment_rows,
        )
        + '<h3>样本覆盖</h3>'
        + _render_table(
            ("研究范围", "有效留言", "独立作者", "线程", "平台", "最大平台占比", "证据强度"),
            quality_rows,
        )
        + '<p class="footnote">Top3仅从有效特征中筛选，Listing占比限定为3%–20%，按原始供需指数排序。完整技术审计记录保留在JSON中，不进入业务报告。</p>'
        + "</details></section>"
    )


def _render_innovations(title: str, items: Any) -> str:
    rows = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        meets_threshold = bool(item.get("meets_consumer_evidence_threshold"))
        rows.append(
            [
                _escape(_display_text(item.get("innovation_type"))),
                (
                    f'<strong>{_escape(_display_text(item.get("title") or item.get("need_code")))}</strong>'
                    f'<small>{_escape(_display_text(item.get("description") or ""))}</small>'
                ),
                (
                    f'{_format_number(item.get("voice_count"))} 条 · {_format_percent(item.get("voice_share"))}<br>'
                    f'<small>{_format_number(item.get("author_count"))} 位作者 / {_format_number(item.get("thread_count"))} 个线程</small>'
                ),
                "有明确失败或绕行" if item.get("has_failure_or_workaround_evidence") else "尚缺失败或绕行证据",
                (
                    '<span class="badge green">可称消费者新需求</span>'
                    if meets_threshold
                    else '<span class="badge orange">候选需求，继续验证</span>'
                ),
                _confidence_badge(item.get("confidence") or "low"),
            ]
        )
    return (
        f'<section class="panel"><h3>{_escape(title)}</h3>'
        + _render_table(
            (
                "类型",
                "需求与创意",
                "讨论热度",
                "问题证据",
                "当前判断",
                "证据强度",
            ),
            rows,
        )
        + "</section>"
    )


def _render_category(analysis: Mapping[str, Any]) -> str:
    category = analysis.get("category_30d")
    if not isinstance(category, Mapping):
        category = {}
    return (
        '<section class="report-section panel" id="category">'
        + _section_head(
            "category-heading",
            "当前市场声音",
            "消费者真正关心什么",
            "最近30天全品类留言，用来判断当前购买决策、差评风险和满意来源。",
        )
        + _render_ranked_items("购买与使用需求", category.get("need_stats"), limit=10)
        + '<div class="two-col sentiment-grid" id="sentiment">'
        + _render_ranked_items("最容易引发不满的点", category.get("dissatisfaction_top10"), limit=10)
        + _render_ranked_items("最容易获得好评的点", category.get("satisfaction_top10"), limit=10)
        + "</div>"
        + '<section class="subsection" id="kano"><h3>需求属性判断</h3>'
        + _render_kano(category.get("kano"))
        + '<p class="footnote">仅展示优先级最高的8项。这里的需求属性属于消费者声音方向性判断，不等同于正式功能/反功能成对问卷；“证据不足”应进入下一轮验证，而不是直接转成工程必做项。</p>'
        + "</section>"
        + '<div class="two-col">'
        + _render_ranked_items(
            "近期使用场景",
            category.get("use_scenes"),
            limit=8,
            presentation_kind="scene",
        )
        + _render_ranked_items("最近30天显著讨论点", category.get("significant_recent_topics"), limit=8)
        + "</div>"
        + _render_innovations("当前新需求、DIY与创意", category.get("current_new_needs"))
        + (
            '<details><summary>查看可能产生反效果的需求</summary>'
            + _render_kano(category.get("reverse_needs"))
            + "</details>"
            if isinstance(category.get("reverse_needs"), list) and category.get("reverse_needs")
            else ""
        )
        + "</section>"
    )


def _render_segments(analysis: Mapping[str, Any]) -> str:
    analyses = analysis.get("segment_analyses")
    if not isinstance(analyses, list):
        analyses = []
    definitions = {
        item.get("segment_id"): item
        for item in analysis.get("segments", [])
        if isinstance(item, Mapping)
    }
    supply_by_segment = {
        item.get("segment_id"): item
        for item in analysis.get("supply_validation", [])
        if isinstance(item, Mapping)
    }
    max_denominator = max(
        (
            int(item.get("denominator_90d") or 0)
            for item in analyses
            if isinstance(item, Mapping)
        ),
        default=0,
    )
    blocks: list[str] = []
    for entry in analyses:
        if not isinstance(entry, Mapping):
            continue
        segment = definitions.get(entry.get("segment_id"), {})
        name = segment.get("feature") or segment.get("segment_id") or "未选出细分"
        denominator = int(entry.get("denominator_90d") or 0)
        is_priority = denominator == max_denominator and denominator > 0
        action = "优先补样验证" if is_priority else "继续观察与验证"
        top_need_items = entry.get("need_stats_90d") if isinstance(entry.get("need_stats_90d"), list) else []
        top_need = next(
            (
                _display_text(item.get("name_zh") or item.get("label") or item.get("need_code"))
                for item in top_need_items
                if isinstance(item, Mapping)
            ),
            "暂无稳定需求信号",
        )
        supply = supply_by_segment.get(entry.get("segment_id"), {})
        blocks.append(
            '<article class="segment-card card">'
            '<header><div>'
            f'<span class="eyebrow">TOP {_escape(segment.get("rank") or "—")} · {_escape(segment.get("dimension") or "细分机会")}</span>'
            f'<h3>{_escape(name)}</h3></div>'
            f'<span class="decision-badge {"priority" if is_priority else "watch"}">{_escape(action)}</span></header>'
            '<div class="segment-meta">'
            f'<span>Listing占比 {_format_percent(segment.get("listing_share"))}</span>'
            f'<span>销量占比 {_format_percent(segment.get("sales_share"))}</span>'
            f'<span>供需指数 {_format_number(segment.get("supply_demand_index"))}</span>'
            f'<span>90天 {_format_number(denominator)} 条有效留言</span>'
            "</div>"
            + '<div class="segment-thesis">'
            + f'<div><span>最强需求信号</span><strong>{_escape(top_need)}</strong></div>'
            + f'<div><span>供给侧判断</span><strong>{_escape(_display_text(supply.get("finding") or "尚待验证"))}</strong></div>'
            + f'<div><span>当前建议</span><strong>{_escape(action)}，暂不直接立项</strong></div>'
            + "</div>"
            + _render_ranked_items("90天主要需求", entry.get("need_stats_90d"), limit=8)
            + '<div class="two-col">'
            + _render_ranked_items("主要不满意点", entry.get("dissatisfaction_90d"), limit=5)
            + _render_ranked_items("主要满意点", entry.get("satisfaction_90d"), limit=5)
            + "</div>"
            + _render_innovations("新需求与供给缺口信号", entry.get("new_needs"))
            + '<details><summary>查看需求属性、场景与用户分群</summary>'
            + '<section class="subsection"><h4>该细分需求属性判断</h4>'
            + _render_kano(entry.get("kano_90d"))
            + "</section>"
            + '<div class="two-col">'
            + _render_ranked_items(
                "使用场景",
                entry.get("use_scenes"),
                limit=8,
                presentation_kind="scene",
            )
            + _render_ranked_items(
                "消费者分群",
                entry.get("personas"),
                limit=8,
                presentation_kind="persona",
            )
            + "</div>"
            + _render_innovations("DIY与现有绕行方案", entry.get("diy_workarounds"))
            + "</details></article>"
        )
    return (
        '<section class="report-section panel" id="segments">'
        + _section_head(
            "segments-heading",
            "细分机会",
            "Top3细分：先看是否值得继续验证",
            "市场结构与消费者证据共同判断；样本不足时只建议补样，不直接立项。",
        )
        + ("".join(blocks) if blocks else '<p class="empty-state">没有满足3%-20%门槛的细分。</p>')
        + "</section>"
    )


def _render_union_and_supply(analysis: Mapping[str, Any]) -> str:
    union = analysis.get("union_analysis") if isinstance(analysis.get("union_analysis"), Mapping) else {}
    need_labels = {
        item.get("need_code"): item.get("name_zh")
        for item in union.get("need_stats", [])
        if isinstance(item, Mapping)
    }
    segment_labels = {
        item.get("segment_id"): item.get("feature")
        for item in analysis.get("segments", [])
        if isinstance(item, Mapping)
    }
    kano_rows = []
    for item in union.get("kano_differences") if isinstance(union.get("kano_differences"), list) else []:
        if not isinstance(item, Mapping):
            continue
        classification_parts: list[str] = []
        classifications = item.get("classifications")
        for entry in classifications if isinstance(classifications, list) else []:
            if not isinstance(entry, Mapping):
                continue
            classification_parts.append(
                f'<span class="layer-kano"><b>{_escape(_scope_label(entry.get("scope_id")))}</b>'
                f'{_escape(_kano_label(entry.get("classification")))}</span>'
            )
        kano_rows.append(
            [
                _escape(_display_text(need_labels.get(item.get("need_code")) or item.get("need_code"))),
                '<div class="layer-kano-list">' + "".join(classification_parts) + "</div>",
                _escape(_display_text(item.get("rationale"))),
                _confidence_badge(item.get("confidence") or "low"),
            ]
        )
    supply_blocks: list[str] = []
    supply_items = analysis.get("supply_validation")
    for item in supply_items if isinstance(supply_items, list) else []:
        if not isinstance(item, Mapping):
            continue
        segment_name = segment_labels.get(item.get("segment_id")) or "对应细分"
        findings = item.get("findings") if isinstance(item.get("findings"), list) else []
        finding_items = "".join(
            '<li>'
            f'<strong>{_escape(_display_text(finding.get("description") or finding.get("need_code")))}</strong>'
            f'<span>{_escape(_display_text(finding.get("finding") or "尚待验证"))}</span>'
            "</li>"
            for finding in findings
            if isinstance(finding, Mapping)
        )
        supply_blocks.append(
            '<article class="supply-card card">'
            '<header>'
            f'<div><span class="eyebrow">供给核查</span><h3>{_escape(segment_name)}</h3></div>'
            + _confidence_badge(item.get("confidence") or "low")
            + "</header>"
            '<div class="supply-metrics">'
            f'<span><b>{_format_number(item.get("products_checked"))}</b>款商品</span>'
            f'<span><b>{_format_percent(item.get("cumulative_sales_share"))}</b>累计销量覆盖</span>'
            f'<span><b>{_escape(_date_only(item.get("snapshot_at")))}</b>供给快照</span>'
            "</div>"
            f'<p class="supply-finding"><strong>当前结论：</strong>{_escape(_display_text(item.get("finding")))}</p>'
            + ('<ul class="finding-list">' + finding_items + "</ul>" if finding_items else '<p class="empty-state">暂无逐项发现。</p>')
            + f'<p class="boundary-note"><strong>结论边界：</strong>{_escape(_display_text(item.get("claim_boundary")))}</p>'
            + '<details><summary>查看检查范围与限制</summary>'
            + f'<div><strong>检查范围：</strong>{_structured_html(item.get("checked_layers"))}</div>'
            + f'<div><strong>供给证据：</strong>{_structured_html(item.get("supply_evidence"))}</div>'
            + f'<div><strong>限制：</strong>{_structured_html(item.get("limitations"))}</div>'
            + "</details></article>"
        )
    return (
        '<section class="report-section panel" id="unmet">'
        + _section_head(
            "unmet-heading",
            "需求与供给",
            "哪些差异点值得做，哪些还只是猜想",
            "消费者声音只能说明需求信号；是否真有机会，还要结合当前供给覆盖。",
        )
        + '<div class="two-col">'
        + _render_ranked_items("跨细分共同需求", union.get("shared_needs"), limit=10)
        + _render_ranked_items(
            "极端使用场景",
            union.get("extreme_scenarios"),
            limit=10,
            presentation_kind="scene",
        )
        + "</div>"
        + _render_innovations("消费者创意、DIY与潜在新需求", union.get("new_needs"))
        + '<section class="subsection development-priorities"><h3>产品开发优先项</h3>'
        + _structured_html(union.get("development_priorities"))
        + "</section>"
        + '<section class="subsection"><h3>供给验证</h3><div class="supply-grid">'
        + ("".join(supply_blocks) if supply_blocks else '<p class="empty-state">尚未完成供给侧验证；相关创意不得宣称“全市场没有产品”。</p>')
        + "</div></section>"
        + '<details><summary>查看不同研究层的需求属性差异</summary>'
        + _render_table(("需求", "各层需求属性判断", "解释", "证据强度"), kano_rows)
        + "</details></section>"
    )


def _render_image_prompt(value: Any) -> str:
    prompt = value if isinstance(value, Mapping) else {}
    prompt_text = _display_text(prompt.get("prompt_text"))
    prompt_fields = (
        ("target_product", "目标产品"),
        ("target_consumer", "目标消费者"),
        ("use_scenario", "使用场景"),
        ("key_structure", "关键结构"),
        ("technical_constraints", "技术约束"),
        ("scale_and_proportion", "尺寸与比例"),
        ("materials", "材质"),
        ("cmf", "颜色与表面"),
        ("camera", "镜头角度"),
        ("lighting", "光线"),
        ("background", "背景"),
        ("must_show", "必须展示"),
        ("forbidden", "禁止出现"),
    )
    field_html = "".join(
        f'<dt>{_escape(label)}</dt><dd>{_structured_html(prompt.get(key))}</dd>'
        for key, label in prompt_fields
    )
    return (
        '<details class="concept-prompt">'
        '<summary>查看完整概念图提示词</summary>'
        '<p class="prompt-label">可直接用于概念图生成的完整提示词</p>'
        f'<div class="prompt-box">{_escape(prompt_text)}</div>'
        f'<dl class="prompt-spec">{field_html}</dl>'
        '</details>'
    )


def _render_concepts(
    analysis: Mapping[str, Any], images: Mapping[str, Mapping[str, Any]]
) -> str:
    raw_concepts = analysis.get("product_concepts")
    if not isinstance(raw_concepts, list):
        raw_concepts = []
    denominator_by_segment = {
        item.get("segment_id"): int(item.get("denominator_90d") or 0)
        for item in analysis.get("segment_analyses", [])
        if isinstance(item, Mapping)
    }
    priority_segment = max(
        denominator_by_segment,
        key=lambda key: denominator_by_segment.get(key, 0),
        default="",
    )
    concepts = sorted(
        [item for item in raw_concepts if isinstance(item, Mapping)],
        key=lambda item: -denominator_by_segment.get(item.get("segment_id"), 0),
    )
    segment_labels = {
        item.get("segment_id"): item.get("feature")
        for item in analysis.get("segments", [])
        if isinstance(item, Mapping)
    }
    need_labels = {
        item.get("need_code"): item.get("name_zh")
        for item in (
            analysis.get("union_analysis", {}).get("need_stats", [])
            if isinstance(analysis.get("union_analysis"), Mapping)
            else []
        )
        if isinstance(item, Mapping)
    }
    blocks: list[str] = []
    report_artifacts = analysis.get("report_artifacts")
    report_ready = (
        isinstance(report_artifacts, Mapping)
        and report_artifacts.get("status") == "ready"
    )
    fallback_images = list(images.values())
    for index, concept in enumerate(concepts):
        concept_id = str(concept.get("concept_id") or f"concept_{index + 1}")
        segment_id = str(concept.get("segment_id") or "")
        is_priority = segment_id == priority_segment
        if report_ready:
            image_item = images.get(concept_id)
        else:
            image_reference = concept.get("image_artifact")
            if isinstance(image_reference, Mapping):
                image_reference = image_reference.get("key") or image_reference.get("name")
            image_item = images.get(str(image_reference or "")) or images.get(concept_id)
            if image_item is None and index < len(fallback_images):
                image_item = fallback_images[index]
        image_html = ""
        if image_item:
            image_html = (
                '<figure class="concept-figure">'
                f'<img data-concept-id="{_escape(concept_id)}" src="{image_item["data_uri"]}" alt="{_escape(concept.get("name") or concept_id)}概念图">'
                f'<figcaption>{_escape(image_item.get("disclaimer"))}</figcaption></figure>'
            )
        design_thinking = concept.get("design_thinking") if isinstance(concept.get("design_thinking"), Mapping) else {}
        design_cards = "".join(
            '<article class="process-step">'
            f'<span>{step}</span><h4>{_escape(label)}</h4>'
            f'{_structured_html(design_thinking.get(phase))}</article>'
            for step, (phase, label) in enumerate(
                (
                    ("empathize", "同理：理解用户"),
                    ("define", "定义：明确问题"),
                    ("ideate", "构思：形成方案"),
                    ("prototype", "原型：制作样件"),
                    ("test", "测试：验证指标"),
                    ("iteration", "迭代：修正失败"),
                ),
                start=1,
            )
        )
        moscow = concept.get("moscow") if isinstance(concept.get("moscow"), Mapping) else {}
        moscow_cards = "".join(
            f'<article class="moscow-card {css_class}">'
            f'<h4>{_escape(label)}</h4>{_structured_html(moscow.get(key))}</article>'
            for key, label, css_class in (
                ("must", "必须包含", "must"),
                ("should", "应该包含", "should"),
                ("could", "可以包含", "could"),
                ("wont_this_release", "本期不做", "wont"),
            )
        )
        must_items = moscow.get("must") if isinstance(moscow.get("must"), list) else []
        must_features = [
            str(item.get("feature"))
            for item in must_items
            if isinstance(item, Mapping) and item.get("feature")
        ]
        target_consumers = concept.get("target_consumers") if isinstance(concept.get("target_consumers"), list) else []
        first_consumer = str(target_consumers[0]) if target_consumers else "目标细分消费者"
        acceptance_items = concept.get("acceptance_metrics") if isinstance(concept.get("acceptance_metrics"), list) else []
        first_acceptance = next(
            (
                str(item.get("target"))
                for item in acceptance_items
                if isinstance(item, Mapping) and item.get("target")
            ),
            "完成目标场景验证",
        )
        price = concept.get("target_price") if isinstance(concept.get("target_price"), Mapping) else {}
        price_text = (
            f'{price.get("currency") or "USD"} {_format_number(price.get("min"))}–{_format_number(price.get("max"))}'
            if price
            else "待验证"
        )
        acceptance_rows = [
            [
                _escape(_display_text(item.get("metric"))),
                _escape(_display_text(item.get("target"))),
                _escape(_display_text(item.get("test_method"))),
            ]
            for item in acceptance_items
            if isinstance(item, Mapping)
        ]
        kano_rows = []
        kano_items = concept.get("kano_mapping") if isinstance(concept.get("kano_mapping"), list) else []
        for item in kano_items:
            if not isinstance(item, Mapping):
                continue
            kano_rows.append(
                [
                    _escape(_display_text(need_labels.get(item.get("need_code")) or item.get("need_code"))),
                    _escape(_kano_label(item.get("classification"))),
                    _escape(_display_text(item.get("design_response"))),
                ]
            )
        listing_bullets = "".join(
            f'<li>{_escape(feature)}</li>' for feature in must_features[:5]
        ) or '<li>先完成核心卖点验证，再冻结页面表达。</li>'
        blocks.append(
            '<article class="concept-card card">'
            '<header class="concept-header">'
            f'<div><span class="eyebrow">{_escape(segment_labels.get(segment_id) or "联合产品方向")}</span>'
            f'<h3>{_escape(concept.get("name") or concept_id)}</h3></div>'
            f'<span class="decision-badge {"priority" if is_priority else "watch"}">{"优先验证" if is_priority else "备选方向"}</span>'
            "</header>"
            '<div class="concept-hero">'
            + image_html
            + '<div class="concept-brief">'
            + f'<p class="jtbd"><strong>用户任务：</strong>{_escape(_display_text(concept.get("jtbd")))}</p>'
            + '<dl class="decision-facts">'
            + f'<dt>目标消费者</dt><dd>{_structured_html(concept.get("target_consumers"))}</dd>'
            + f'<dt>典型场景</dt><dd>{_structured_html(concept.get("use_scenarios"))}</dd>'
            + f'<dt>目标售价</dt><dd>{_escape(price_text)}</dd>'
            + f'<dt>BOM假设</dt><dd>{_escape(_display_text(concept.get("bom_assumption")))}</dd>'
            + "</dl></div></div>"
            '<div class="decision-rail" aria-label="从用户问题到验收测试">'
            f'<div><span>消费者</span><strong>{_escape(first_consumer)}</strong></div>'
            f'<div><span>失败任务</span><strong>{_escape(_display_text(concept.get("jtbd")))}</strong></div>'
            f'<div><span>产品规格</span><strong>{_escape(must_features[0] if must_features else "核心规格待验证")}</strong></div>'
            f'<div><span>验收测试</span><strong>{_escape(first_acceptance)}</strong></div>'
            "</div>"
            '<section class="subsection"><h3>核心产品定义</h3><div class="spec-grid">'
            + f'<article><h4>功能</h4>{_structured_html(concept.get("features"))}</article>'
            + f'<article><h4>技术与结构</h4><p>{_escape(_display_text(concept.get("technical_solution")))}</p><p>{_escape(_display_text(concept.get("structure")))}</p></article>'
            + f'<article><h4>材料</h4>{_structured_html(concept.get("materials"))}</article>'
            + f'<article><h4>颜色与表面</h4>{_structured_html(concept.get("cmf"))}</article>'
            + "</div></section>"
            + _render_image_prompt(concept.get("image_prompt"))
            + '<section class="subsection"><h3>MoSCoW开发优先级</h3><div class="moscow-grid">'
            + moscow_cards
            + "</div></section>"
            + '<section class="subsection"><h3>量化验收指标</h3>'
            + _render_table(("指标", "通过标准", "测试方法"), acceptance_rows)
            + "</section>"
            + '<div class="two-col risk-grid">'
            + f'<article class="warning-block"><h3>主要风险</h3>{_structured_html(concept.get("risks"))}</article>'
            + f'<article><h3>开发依赖</h3>{_structured_html(concept.get("dependencies"))}</article>'
            + "</div>"
            + '<section class="listing-guidance"><h3>亚马逊页面表达建议</h3>'
            + f'<p><strong>首图主卖点：</strong>{_escape(must_features[0] if must_features else "核心差异点待验证")}</p>'
            + '<p><strong>五点描述优先级：</strong></p><ol>' + listing_bullets + "</ol>"
            + '<p><strong>暂勿直接宣称：</strong>“全市场唯一”“适配所有车型”“通过车规认证”或任何尚未完成测试的性能结论。</p></section>'
            + '<details><summary>查看需求属性映射与设计思维过程</summary>'
            + _render_table(("需求", "需求属性", "产品应对"), kano_rows)
            + '<div class="design-process">' + design_cards + "</div></details>"
            + "</article>"
        )
    if not blocks and images:
        for item in images.values():
            blocks.append(
                '<figure class="concept-figure standalone">'
                f'<img src="{item["data_uri"]}" alt="{_escape(item["name"])}">'
                f'<figcaption>{_escape(item.get("disclaimer"))}</figcaption></figure>'
            )
    return (
        '<section class="report-section panel" id="concepts"><span id="design" aria-hidden="true"></span>'
        + _section_head(
            "concepts-heading",
            "产品定义",
            "三个产品开发方向",
            "按消费者证据量排序；优先方向仍需补样、工程验证和供给复核后才能立项。",
        )
        + ("".join(blocks) if blocks else '<p class="empty-state">尚未生成产品方案或概念图。</p>')
        + "</section>"
    )


def _resolve_coding_artifact(analysis: Mapping[str, Any]) -> Path:
    project = analysis.get("project") if isinstance(analysis.get("project"), Mapping) else {}
    raw_path = str(project.get("coding_artifact") or "").strip()
    if not raw_path:
        raise ContractError("analysis.project.coding_artifact 不能为空")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        project_root = str(project.get("project_root") or "").strip()
        if not project_root:
            raise ContractError("相对coding_artifact缺少project.project_root")
        path = Path(project_root).expanduser() / path
    return path.resolve()


def _load_coding_for_report(analysis: Mapping[str, Any]) -> dict[str, Any]:
    coding_path = _resolve_coding_artifact(analysis)
    document = _load_json(coding_path)
    normalized, _ = validate_coding_document(document, reject_duplicates=True)
    project = analysis.get("project") if isinstance(analysis.get("project"), Mapping) else {}
    declared_sha = str(project.get("coding_sha256") or "")
    actual_sha = hashlib.sha256(coding_path.read_bytes()).hexdigest()
    if actual_sha != declared_sha:
        raise ContractError(
            "报告引用的coding文件SHA-256与analysis.project.coding_sha256不一致",
            [f"declared={declared_sha}", f"actual={actual_sha}"],
        )
    return normalized


def _render_future_validation(analysis: Mapping[str, Any]) -> str:
    rows: list[list[str]] = []
    checklist = analysis.get("future_validation_checklist")
    for item in checklist if isinstance(checklist, list) else []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            [
                _escape(_display_text(item.get("validation_type"))),
                f'<span class="badge gray">{_escape(_display_text(item.get("status")))}</span>',
                _escape(_display_text(item.get("objective"))),
                _escape(_display_text(item.get("trigger"))),
                (
                    f'<strong>{_escape(_display_text(item.get("method")))}</strong>'
                    f'<small>通过标准：{_escape(_display_text(item.get("acceptance_criteria")))}</small>'
                ),
                _escape(_display_text(item.get("owner_role"))),
            ]
        )
    return (
        '<section class="report-section panel" id="validation">'
        + _section_head(
            "validation-roadmap",
            "进入下一阶段的门槛",
            "验证路线",
            "在投入模具、认证和大货资源前，逐项满足消费者、工程与合规证据门槛。",
        )
        + _render_table(
            ("验证事项", "状态", "目的", "触发条件", "方法与通过标准", "负责人"),
            rows,
        )
        + "</section>"
    )


def _render_evidence_appendix(
    analysis: Mapping[str, Any], coding: Mapping[str, Any]
) -> str:
    voice_blocks: list[str] = []
    voices = coding.get("voices") if isinstance(coding.get("voices"), list) else []
    for voice in voices[:REPRESENTATIVE_EVIDENCE_LIMIT]:
        if not isinstance(voice, Mapping):
            continue
        source_url = str(voice.get("normalized_url") or "")
        link = (
            f'<a href="{_escape(source_url)}" target="_blank" rel="noopener noreferrer">查看公开原声</a>'
            if source_url.startswith(("https://", "http://"))
            else "无有效直链"
        )
        voice_blocks.append(
            '<article class="evidence-item">'
            f'<h3>{_escape(str(voice.get("platform") or "公开平台").title())} 用户留言 · {_escape(_date_only(voice.get("published_at")))}</h3>'
            f'<blockquote>{_escape(voice.get("excerpt"))}</blockquote>'
            f'<p><strong>中文摘要：</strong>{_escape(voice.get("summary_zh"))}</p>'
            '<div class="evidence-meta">'
            f'<span>平台：{_escape(str(voice.get("platform") or "—").title())}</span>'
            f'<span>社区：{_escape(voice.get("community") or "—")}</span>'
            f'<span>{link}</span>'
            "</div>"
            "</article>"
        )
    limitations = analysis.get("limitations")
    limitation_html = _structured_html(limitations if isinstance(limitations, list) else [])
    return (
        '<section class="report-section panel" id="evidence">'
        + _section_head(
            "evidence-heading",
            "研究透明度",
            "限制与消费者原声",
            "正文只展示业务结论；需要复核时，可在这里查看研究限制与公开原声。",
        )
        + '<section class="subsection"><h3>研究限制</h3>'
        + limitation_html
        + "</section>"
        + f'<details><summary>查看 {_format_number(len(voice_blocks))} 条代表性消费者原声</summary><div class="evidence-list">'
        + ("".join(voice_blocks) if voice_blocks else '<p class="empty-state">没有有效消费者声音。</p>')
        + '</div><p class="footnote">每项洞察最多展示3条代表性原声，完整证据保留在JSON。</p></details></section>'
    )


def _render_executive_summary(analysis: Mapping[str, Any]) -> str:
    category = analysis.get("category_30d") if isinstance(analysis.get("category_30d"), Mapping) else {}
    segments = analysis.get("segments") if isinstance(analysis.get("segments"), list) else []
    segment_analyses = analysis.get("segment_analyses") if isinstance(analysis.get("segment_analyses"), list) else []
    analysis_by_segment = {
        item.get("segment_id"): item
        for item in segment_analyses
        if isinstance(item, Mapping)
    }
    quality_items = analysis.get("scope_quality") if isinstance(analysis.get("scope_quality"), list) else []
    union_quality = next(
        (
            item
            for item in quality_items
            if isinstance(item, Mapping) and item.get("scope_id") == "union_mixed_window"
        ),
        {},
    )
    best_segment = max(
        (item for item in segments if isinstance(item, Mapping)),
        key=lambda item: int(analysis_by_segment.get(item.get("segment_id"), {}).get("denominator_90d") or 0),
        default={},
    )
    best_segment_id = best_segment.get("segment_id")
    best_segment_name = str(best_segment.get("feature") or "Top3细分")
    best_count = int(analysis_by_segment.get(best_segment_id, {}).get("denominator_90d") or 0)
    report_artifacts = (
        analysis.get("report_artifacts")
        if isinstance(analysis.get("report_artifacts"), Mapping)
        else {}
    )
    report_status = str(report_artifacts.get("status") or "partial")
    report_status_label = {
        "ready": "已完成",
        "partial": "部分完成",
        "failed": "执行失败",
    }.get(report_status, "部分完成")
    platform_count = int(union_quality.get("platform_count") or 0)
    confidence = str(union_quality.get("confidence") or "low")
    sample_gaps = _sample_gate_gaps(analysis)
    # Diversity can make a tiny corpus look statistically "high" in isolation,
    # but the executive badge must never contradict the selected research
    # level's explicit sample gates.
    if sample_gaps:
        confidence = "low"
    enough_for_concept_test = not sample_gaps
    partial_gaps = (
        _report_partial_gaps(analysis) if report_status == "partial" else sample_gaps
    )
    report_artifacts = analysis.get("report_artifacts")
    report_ready = (
        isinstance(report_artifacts, Mapping)
        and report_artifacts.get("status") == "ready"
    )
    if enough_for_concept_test and report_ready:
        action = "进入概念验证"
        decision = "样本与产品方案门槛已满足"
        evidence_summary = "本档位总样本、四路样本和平台覆盖均达到门槛，可结合供给与工程验证推进概念测试。"
    elif enough_for_concept_test:
        action = "完成方案后进入概念验证"
        decision = "样本门槛已满足"
        evidence_summary = "本档位总样本、四路样本和平台覆盖均达到门槛；产品方案、供给或工程证据仍需补齐。"
    else:
        action = "优先补样验证"
        decision = "暂不建议直接立项"
        evidence_summary = (
            "当前仍未达到" + "、".join(sample_gaps) + "门槛；先完成定向补样和供给复核，再决定是否进入工程立项。"
        )
    partial_notice = (
        '<div class="method-summary"><strong>本轮未达标：</strong>'
        + _escape("；".join(partial_gaps))
        + "。</div>"
        if report_status == "partial" and partial_gaps
        else ""
    )

    def first_item(key: str) -> Mapping[str, Any]:
        source = category.get(key)
        if not isinstance(source, list):
            return {}
        return next((item for item in source if isinstance(item, Mapping)), {})

    def item_label(item: Mapping[str, Any]) -> str:
        return _display_text(
            item.get("label")
            or item.get("name_zh")
            or item.get("need_label")
            or item.get("need_code")
            or "暂无稳定信号"
        )

    top_need = first_item("need_stats")
    top_pain = first_item("dissatisfaction_top10")
    top_delight = first_item("satisfaction_top10")
    concept_by_segment = {
        item.get("segment_id"): item
        for item in analysis.get("product_concepts", [])
        if isinstance(item, Mapping)
    }
    preferred_concept = concept_by_segment.get(best_segment_id, {})

    signal_cards = "".join(
        '<article class="signal-card">'
        f'<span>{_escape(label)}</span><h3>{_escape(item_label(item))}</h3>'
        f'<p>{_format_number(item.get("voice_count"))} 条留言 · {_format_percent(item.get("voice_share"))}</p>'
        "</article>"
        for label, item in (
            ("用户最在意", top_need),
            ("首要差评风险", top_pain),
            ("主要好评来源", top_delight),
        )
    )

    opportunity_cards: list[str] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        entry = analysis_by_segment.get(segment.get("segment_id"), {})
        denominator = int(entry.get("denominator_90d") or 0)
        is_best = segment.get("segment_id") == best_segment_id
        opportunity_cards.append(
            f'<article class="opportunity-stop {"active" if is_best else ""}">'
            f'<span>Top{_escape(segment.get("rank"))} · {_escape(segment.get("dimension"))}</span>'
            f'<h3>{_escape(segment.get("feature"))}</h3>'
            '<dl>'
            f'<dt>供需指数</dt><dd>{_format_number(segment.get("supply_demand_index"))}</dd>'
            f'<dt>销量 / Listing</dt><dd>{_format_percent(segment.get("sales_share"))} / {_format_percent(segment.get("listing_share"))}</dd>'
            f'<dt>消费者证据</dt><dd>{_format_number(denominator)} 条</dd>'
            "</dl>"
            f'<strong>{"优先补样" if is_best and not enough_for_concept_test else "继续验证"}</strong>'
            "</article>"
        )

    largest_platform_share = union_quality.get("largest_platform_share")
    execution_receipt = _render_compact_execution_receipt(analysis)
    return (
        '<section class="report-section decision-summary" id="decision">'
        '<div class="decision-copy">'
        '<p class="section-kicker">本轮产品决策</p>'
        f'<span class="status-badge {_escape(report_status)}">报告状态：{_escape(report_status_label)}</span>'
        f'<h2>{_escape(action)}“{_escape(best_segment_name)}”，{_escape(decision)}</h2>'
        f'<p>该细分在Top3中消费者证据最多（{_format_number(best_count)}条）。{_escape(evidence_summary)}</p>'
        '<p><strong>计数口径：</strong>只合并同一底层公开留言；不同评论即使语义相同，也分别计数。</p>'
        + partial_notice
        + '</div>'
        '<aside class="reliability-panel"><span>当前证据可用度</span>'
        f'<strong>{_escape(_confidence_label(confidence))}</strong>'
        '<ul>'
        f'<li>{_format_number(union_quality.get("valid_voice_count"))} 条有效留言</li>'
        f'<li>{_format_number(union_quality.get("identified_author_count"))} 位可识别作者</li>'
        f'<li>{_format_number(platform_count)} 个有效平台</li>'
        f'<li>最大平台贡献 {_format_percent(largest_platform_share)}</li>'
        '</ul></aside>'
        + execution_receipt
        + '<div class="signal-grid">' + signal_cards + "</div>"
        '<div class="decision-track" aria-label="消费者信号到产品验证的决策轨道">'
        f'<div><span>消费者信号</span><strong>{_escape(item_label(top_need))}</strong></div>'
        f'<div><span>优先细分</span><strong>{_escape(best_segment_name)}</strong></div>'
        f'<div><span>产品方向</span><strong>{_escape(preferred_concept.get("name") or "概念待定义")}</strong></div>'
        f'<div><span>下一道门槛</span><strong>{"多平台补样 + 场景测试" if not enough_for_concept_test else "原型测试 + 供给复核"}</strong></div>'
        "</div>"
        '<section class="opportunity-overview"><h3>Top3机会速览</h3><div class="opportunity-route">'
        + "".join(opportunity_cards)
        + "</div></section></section>"
    )


def _render_static_content(
    analysis: Mapping[str, Any],
    images: Mapping[str, Mapping[str, Any]],
    coding: Mapping[str, Any],
) -> str:
    return (
        _render_executive_summary(analysis)
        + _render_category(analysis)
        + _render_segments(analysis)
        + _render_union_and_supply(analysis)
        + _render_concepts(analysis, images)
        + _render_future_validation(analysis)
        + _render_windows_and_sources(analysis)
        + _render_evidence_appendix(analysis, coding)
    )


def _refresh_analysis_runtime_receipt(
    analysis: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Refresh only deterministic runtime receipt fields before final render."""
    updated = copy.deepcopy(dict(analysis))
    project = updated.get("project") if isinstance(updated.get("project"), Mapping) else {}
    coding_path = _resolved_project_path(project, project.get("coding_artifact"))
    if coding_path is None:
        return updated, False
    plan = _research_plan(updated)
    denominators = updated.get("denominators") if isinstance(updated.get("denominators"), Mapping) else {}
    funnel = updated.get("collection_funnel") if isinstance(updated.get("collection_funnel"), Mapping) else {}
    refreshed = _collection_receipt_summary(
        coding_path=coding_path,
        research_plan=plan,
        denominators=denominators,
        collection_funnel=funnel,
    )
    changed = refreshed != updated.get("collection_receipt")
    updated["collection_receipt"] = refreshed
    deadline = refreshed.get("deadline_status") if isinstance(refreshed, Mapping) else {}
    if isinstance(deadline, Mapping) and deadline.get("deadline_exceeded") is True:
        if updated.get("stop_reason") != "total_deadline":
            changed = True
        updated["stop_reason"] = "total_deadline"
        artifacts = updated.get("report_artifacts")
        if isinstance(artifacts, Mapping) and artifacts.get("status") == "ready":
            artifacts = dict(artifacts)
            artifacts["status"] = "partial"
            updated["report_artifacts"] = artifacts
            changed = True
    return updated, changed


def _final_receipt_snapshot_errors(
    analysis_path: Path,
    final_receipt: Mapping[str, Any],
) -> list[str]:
    """Reject a final receipt that moves backwards from the rendered snapshot.

    The HTML is rendered from ``social_voice_analysis.json`` before the manifest
    phase.  That embedded receipt is intentionally a point-in-time snapshot;
    the authoritative ``collection_receipt.json`` may only add elapsed time.
    """

    path = Path(analysis_path)
    if not path.is_file():
        return []
    analysis = _load_json(path)
    if not isinstance(analysis, Mapping):
        return ["social_voice_analysis.json顶层必须是对象"]
    snapshot = analysis.get("collection_receipt")
    if not isinstance(snapshot, Mapping):
        return []
    snapshot_time = snapshot.get("time_usage_minutes")
    final_time = final_receipt.get("time_usage_minutes")
    if not isinstance(snapshot_time, Mapping) or not isinstance(final_time, Mapping):
        return []
    errors: list[str] = []
    tolerance = 0.0001
    for field, label in (("collection", "采集"), ("total", "总")):
        earlier = _nullable_nonnegative_number(snapshot_time.get(field))
        later = _nullable_nonnegative_number(final_time.get(field))
        if earlier is not None and later is None:
            errors.append(f"最终回执缺少{label}耗时，无法核验HTML快照")
        elif earlier is not None and later is not None and later + tolerance < earlier:
            errors.append(
                f"最终回执{label}耗时{later:.4f}分钟小于HTML快照{earlier:.4f}分钟"
            )
    final_collection = _nullable_nonnegative_number(final_time.get("collection"))
    final_total = _nullable_nonnegative_number(final_time.get("total"))
    if (
        final_collection is not None
        and final_total is not None
        and final_total + tolerance < final_collection
    ):
        errors.append("最终回执总耗时不得小于采集耗时")
    return errors


def render_report(
    analysis: Mapping[str, Any],
    template_path: Path,
    output_path: Path,
    image_args: Sequence[str],
    title: str,
    *,
    analysis_path: Path | None = None,
) -> dict[str, Any]:
    analysis, receipt_changed = _refresh_analysis_runtime_receipt(analysis)
    if receipt_changed and analysis_path is not None:
        _atomic_write_json(analysis_path, analysis)
    removed_errors = _v2_removed_analysis_field_errors(analysis)
    if removed_errors:
        raise ContractError("v2分析包含已移除的最近30天细分字段", removed_errors)
    _validate_against_schema(
        analysis,
        Path(__file__).resolve().parent.parent
        / "references"
        / "social_voice_analysis.schema.json",
        "消费者声音分析",
    )
    coding = _load_coding_for_report(analysis)
    try:
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContractError(f"HTML模板不存在：{template_path}") from exc
    except OSError as exc:
        raise ContractError(f"无法读取HTML模板：{template_path}", [str(exc)]) from exc
    images = _parse_images(image_args)
    report_artifacts = analysis.get("report_artifacts")
    report_ready = (
        isinstance(report_artifacts, Mapping)
        and report_artifacts.get("status") == "ready"
    )
    generated_at = datetime.now(timezone(timedelta(hours=8))).strftime(
        "%Y-%m-%d %H:%M（北京时间）"
    )
    required_placeholders = ("{{TITLE}}", "{{GENERATED_AT}}", "{{CONTENT}}")
    counts = {placeholder: template.count(placeholder) for placeholder in required_placeholders}
    invalid_counts = {key: value for key, value in counts.items() if value != 1}
    if invalid_counts:
        raise ContractError(
            "HTML模板的三个占位符必须各出现一次",
            [f"{key} 出现 {value} 次" for key, value in invalid_counts.items()],
        )
    content = _render_static_content(analysis, images, coding)
    rendered = template.replace("{{TITLE}}", _escape(title))
    rendered = rendered.replace("{{GENERATED_AT}}", _escape(generated_at))
    rendered = rendered.replace("{{CONTENT}}", content)
    project = analysis.get("project") if isinstance(analysis.get("project"), Mapping) else {}
    rendered = rendered.replace(
        "{{MARKETPLACE}}", _escape(project.get("marketplace") or "US")
    )
    if analysis_path is not None and analysis_path.is_file():
        analysis_sha256 = hashlib.sha256(analysis_path.read_bytes()).hexdigest()
    else:
        analysis_sha256 = hashlib.sha256(
            json.dumps(
                analysis,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=_json_default,
            ).encode("utf-8")
        ).hexdigest()
    if "</head>" not in rendered:
        raise ContractError("HTML模板缺少 </head>，无法写入analysis数据血缘")
    rendered = rendered.replace(
        "</head>",
        f'<meta name="consumer-analysis-sha256" content="{analysis_sha256}"></head>',
        1,
    )
    dependency_errors = _offline_dependency_errors(rendered)
    if dependency_errors:
        raise ContractError("HTML未通过独立离线校验", dependency_errors)
    if report_ready:
        ready_errors = _ready_gate_errors(
            analysis,
            image_count=len(images),
            images=images,
            analysis_path=analysis_path,
            html_text=rendered,
        )
        if ready_errors:
            raise ContractError("ready分析未通过渲染门禁", ready_errors)
    _atomic_write_text(output_path, rendered)
    return {
        "status": "rendered",
        "output": str(output_path),
        "title": title,
        "image_count": len(images),
        "images_embedded_as_data_uri": True,
        "offline_dependency_check": "passed",
        "runtime_receipt_refreshed": receipt_changed,
        "analysis_sha256": analysis_sha256,
        "byte_count": output_path.stat().st_size,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }


def _manifest_artifact_path(manifest_path: Path, artifact_path: Path) -> str:
    root = manifest_path.parent.resolve()
    resolved = artifact_path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def _resolved_project_path(project: Mapping[str, Any], value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        root = str(project.get("project_root") or "").strip()
        if not root:
            return None
        path = Path(root).expanduser() / path
    return path.resolve()


def _resolve_declared_image_path(
    analysis: Mapping[str, Any],
    value: Any,
    *,
    analysis_path: Path | None,
) -> tuple[Path | None, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, "图片产物路径为空"
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve(), None
    candidates: list[Path] = []
    project = analysis.get("project") if isinstance(analysis.get("project"), Mapping) else {}
    project_root = str(project.get("project_root") or "").strip()
    if project_root:
        candidates.append((Path(project_root).expanduser() / path).resolve())
    if analysis_path is not None:
        candidates.append((analysis_path.resolve().parent / path).resolve())
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return None, f"相对图片路径缺少project.project_root或analysis_path：{raw}"
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if len(existing) > 1:
        return None, f"相对图片路径存在多个解析结果：{raw}"
    return (existing[0] if existing else candidates[0]), None


def _embedded_concept_image_infos(
    html_text: str,
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    images: dict[str, list[dict[str, str]]] = defaultdict(list)
    errors: list[str] = []
    for tag in re.findall(r"<img\b[^>]*>", html_text, flags=re.IGNORECASE | re.DOTALL):
        concept_match = re.search(
            r"\bdata-concept-id\s*=\s*(['\"])(.*?)\1",
            tag,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not concept_match:
            continue
        concept_id = html_lib.unescape(concept_match.group(2)).strip()
        src_match = re.search(
            r"\bsrc\s*=\s*(['\"])(.*?)\1",
            tag,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not src_match:
            errors.append(f"HTML中的{concept_id}概念图缺少src")
            continue
        source = html_lib.unescape(src_match.group(2)).strip()
        uri_match = re.fullmatch(
            r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)",
            source,
        )
        if not uri_match:
            errors.append(f"HTML中的{concept_id}概念图不是内嵌图片Data URI")
            continue
        declared_mime = uri_match.group(1).casefold()
        try:
            payload = base64.b64decode(uri_match.group(2), validate=True)
        except (ValueError, TypeError, binascii.Error) as exc:
            errors.append(f"HTML中的{concept_id}概念图Base64无效：{exc}")
            continue
        actual_mime = _detect_image_mime(payload)
        if actual_mime is None:
            errors.append(f"HTML中的{concept_id}概念图内容不是受支持的真实图片")
            continue
        if declared_mime != actual_mime.casefold():
            errors.append(
                f"HTML中的{concept_id}概念图Data URI MIME与真实内容不一致"
            )
            continue
        images[concept_id].append(
            {
                "mime_type": actual_mime,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return dict(images), errors


def _ready_image_artifact_errors(
    analysis: Mapping[str, Any],
    *,
    images: Mapping[str, Mapping[str, Any]] | None = None,
    analysis_path: Path | None = None,
    html_path: Path | None = None,
    html_text: str | None = None,
) -> list[str]:
    errors: list[str] = []
    concepts = analysis.get("product_concepts")
    concept_items = [item for item in concepts if isinstance(item, Mapping)] if isinstance(concepts, list) else []
    expected_ids = {"concept_1", "concept_2", "concept_3"}
    concept_ids = [str(item.get("concept_id") or "") for item in concept_items]
    if len(concept_ids) != 3 or set(concept_ids) != expected_ids or len(set(concept_ids)) != 3:
        errors.append("ready的三张概念图必须按concept_1、concept_2、concept_3一一绑定")

    expected_infos: dict[str, dict[str, str]] = {}
    resolved_paths: list[Path] = []
    for concept in concept_items:
        concept_id = str(concept.get("concept_id") or "未命名概念")
        artifact = concept.get("image_artifact")
        if not isinstance(artifact, Mapping):
            errors.append(f"{concept_id}.image_artifact缺失")
            continue
        if artifact.get("status") != "ok":
            errors.append(f"{concept_id}.image_artifact.status必须为ok")
        if artifact.get("embedded_as_data_uri") is not True:
            errors.append(f"{concept_id}必须标记embedded_as_data_uri=true")
        artifact_path, path_error = _resolve_declared_image_path(
            analysis,
            artifact.get("path"),
            analysis_path=analysis_path,
        )
        if path_error:
            errors.append(f"{concept_id}：{path_error}")
            continue
        assert artifact_path is not None
        if not artifact_path.is_file():
            errors.append(f"{concept_id}声明的概念图文件不存在：{artifact_path}")
            continue
        try:
            actual = _image_file_info(artifact_path)
        except ContractError as exc:
            errors.append(f"{concept_id}概念图校验失败：{exc}")
            errors.extend(f"{concept_id}：{detail}" for detail in exc.details)
            continue
        declared_mime = str(artifact.get("mime_type") or "").casefold()
        declared_sha = str(artifact.get("sha256") or "").casefold()
        if declared_mime != actual["mime_type"].casefold():
            errors.append(f"{concept_id}声明的MIME与真实图片内容不一致")
        if declared_sha != actual["sha256"].casefold():
            errors.append(f"{concept_id}声明的SHA-256与真实图片文件不一致")
        expected_infos[concept_id] = actual
        resolved_paths.append(artifact_path)

    if len(resolved_paths) == 3 and len(set(resolved_paths)) != 3:
        errors.append("ready的三个产品概念不得复用同一图片文件")
    image_hashes = [item["sha256"] for item in expected_infos.values()]
    if len(image_hashes) == 3 and len(set(image_hashes)) != 3:
        errors.append("ready的三个产品概念不得复用相同图片内容")

    artifacts = analysis.get("report_artifacts")
    artifact_paths = artifacts.get("image_paths") if isinstance(artifacts, Mapping) else None
    declared_report_paths: list[Path] = []
    if not isinstance(artifact_paths, list) or len(artifact_paths) != 3:
        errors.append("ready的report_artifacts.image_paths必须恰好包含3张图")
    else:
        for index, raw_path in enumerate(artifact_paths):
            resolved, path_error = _resolve_declared_image_path(
                analysis,
                raw_path,
                analysis_path=analysis_path,
            )
            if path_error:
                errors.append(f"report_artifacts.image_paths[{index}]：{path_error}")
            elif resolved is not None:
                declared_report_paths.append(resolved)
        if len(declared_report_paths) == 3 and len(set(declared_report_paths)) != 3:
            errors.append("report_artifacts.image_paths不得包含重复图片")
        if len(resolved_paths) == 3 and set(declared_report_paths) != set(resolved_paths):
            errors.append("report_artifacts.image_paths与三个concept image_artifact.path不一致")

    if images is not None:
        if set(images) != expected_ids:
            errors.append("ready渲染的--image名称必须恰好为concept_1、concept_2、concept_3")
        for concept_id in sorted(expected_ids):
            expected = expected_infos.get(concept_id)
            supplied = images.get(concept_id)
            if expected is None or not isinstance(supplied, Mapping):
                continue
            supplied_path = Path(str(supplied.get("path") or "")).resolve()
            if supplied_path != Path(expected["path"]).resolve():
                errors.append(f"ready渲染传入的{concept_id}图片与其声明产物不一致")
            if str(supplied.get("mime_type") or "").casefold() != expected["mime_type"].casefold():
                errors.append(f"ready渲染传入的{concept_id}图片MIME不一致")
            if str(supplied.get("sha256") or "").casefold() != expected["sha256"].casefold():
                errors.append(f"ready渲染传入的{concept_id}图片SHA-256不一致")

    effective_html = html_text
    if effective_html is None and html_path is not None and html_path.is_file():
        try:
            effective_html = html_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"无法读取ready HTML中的概念图：{exc}")
    if effective_html is not None:
        embedded, embedded_errors = _embedded_concept_image_infos(effective_html)
        errors.extend(embedded_errors)
        for concept_id in sorted(expected_ids):
            entries = embedded.get(concept_id, [])
            if len(entries) != 1:
                errors.append(f"ready HTML必须且只能内嵌1张{concept_id}概念图")
                continue
            expected = expected_infos.get(concept_id)
            if expected is None:
                continue
            if entries[0]["mime_type"].casefold() != expected["mime_type"].casefold():
                errors.append(f"ready HTML内嵌的{concept_id}图片MIME不一致")
            if entries[0]["sha256"].casefold() != expected["sha256"].casefold():
                errors.append(f"ready HTML内嵌的{concept_id}图片SHA-256不一致")
    elif html_path is not None:
        errors.append("ready的HTML报告不存在")
    return list(dict.fromkeys(errors))


def _placeholder_locations(value: Any, path: str = "concept") -> list[str]:
    patterns = (
        r"待agent",
        r"待定义",
        r"待完善",
        r"待补",
        r"planned",
        r"pending",
        r"占位",
        r"\btbd\b",
        r"\btodo\b",
        r"unknown product",
    )
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_placeholder_locations(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_placeholder_locations(item, f"{path}[{index}]"))
    elif isinstance(value, str) and any(
        re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns
    ):
        found.append(path)
    return found


def _recomputed_analysis_errors(
    coding: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    coding_path: Path,
    analysis_path: Path,
) -> list[str]:
    recomputed = analyze_coding(
        coding, coding_path=coding_path, output_path=analysis_path
    )
    comparisons: list[tuple[str, Any, Any]] = [
        ("windows", analysis.get("windows"), recomputed.get("windows")),
        ("segments", analysis.get("segments"), recomputed.get("segments")),
        ("methodology", analysis.get("methodology"), recomputed.get("methodology")),
        ("denominators", analysis.get("denominators"), recomputed.get("denominators")),
        ("scope_quality", analysis.get("scope_quality"), recomputed.get("scope_quality")),
        ("category_30d", analysis.get("category_30d"), recomputed.get("category_30d")),
        (
            "segment_analyses",
            analysis.get("segment_analyses"),
            recomputed.get("segment_analyses"),
        ),
    ]
    if analysis.get("schema_version") == SCHEMA_VERSION:
        comparisons.extend(
            [
                (
                    "research_plan",
                    analysis.get("research_plan"),
                    recomputed.get("research_plan"),
                ),
                (
                    "collection_funnel",
                    analysis.get("collection_funnel"),
                    recomputed.get("collection_funnel"),
                ),
                (
                    "collection_receipt",
                    analysis.get("collection_receipt"),
                    recomputed.get("collection_receipt"),
                ),
                (
                    "stop_reason",
                    analysis.get("stop_reason"),
                    recomputed.get("stop_reason"),
                ),
            ]
        )
    analysis_union = analysis.get("union_analysis") if isinstance(analysis.get("union_analysis"), Mapping) else {}
    recomputed_union = recomputed.get("union_analysis") if isinstance(recomputed.get("union_analysis"), Mapping) else {}
    for key in (
        "scope_id",
        "share_label",
        "denominator",
        "need_stats",
        "shared_needs",
        "extreme_scenarios",
        "new_needs",
        "interpretation_warning",
    ):
        comparisons.append(
            (f"union_analysis.{key}", analysis_union.get(key), recomputed_union.get(key))
        )
    return [
        f"{path}未通过从coding的确定性重算对账"
        for path, actual, expected in comparisons
        if actual != expected
    ]


def _artifact_integrity_errors(
    coding: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    coding_path: Path,
    analysis_path: Path,
    html_path: Path,
) -> list[str]:
    errors: list[str] = []
    project = analysis.get("project") if isinstance(analysis.get("project"), Mapping) else {}
    artifacts = analysis.get("report_artifacts") if isinstance(analysis.get("report_artifacts"), Mapping) else {}
    actual_coding_sha = hashlib.sha256(coding_path.read_bytes()).hexdigest()
    actual_analysis_sha = hashlib.sha256(analysis_path.read_bytes()).hexdigest()
    declared_coding_path = _resolved_project_path(project, project.get("coding_artifact"))
    if declared_coding_path != coding_path.resolve():
        errors.append("analysis.project.coding_artifact未指向finalize传入的coding文件")
    if project.get("coding_sha256") != actual_coding_sha:
        errors.append("analysis.project.coding_sha256与实际coding文件不一致")
    coding_artifact = artifacts.get("coding_json") if isinstance(artifacts.get("coding_json"), Mapping) else {}
    artifact_coding_path = _resolved_project_path(project, coding_artifact.get("path"))
    if artifact_coding_path != coding_path.resolve():
        errors.append("report_artifacts.coding_json.path未指向实际coding文件")
    if coding_artifact.get("sha256") != actual_coding_sha:
        errors.append("report_artifacts.coding_json.sha256与实际coding文件不一致")
    analysis_artifact = artifacts.get("analysis_json") if isinstance(artifacts.get("analysis_json"), Mapping) else {}
    artifact_analysis_path = _resolved_project_path(project, analysis_artifact.get("path"))
    if artifact_analysis_path != analysis_path.resolve():
        errors.append("report_artifacts.analysis_json.path未指向实际analysis文件")
    html_artifact = artifacts.get("html_report") if isinstance(artifacts.get("html_report"), Mapping) else {}
    artifact_html_path = _resolved_project_path(project, html_artifact.get("path"))
    if artifact_html_path != html_path.resolve():
        errors.append("report_artifacts.html_report.path未指向实际HTML文件")
    try:
        html_text = html_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"无法读取HTML报告：{exc}")
        return errors
    errors.extend(_offline_dependency_errors(html_text))
    match = re.search(
        r'<meta\s+name=["\']consumer-analysis-sha256["\']\s+content=["\']([a-fA-F0-9]{64})["\']\s*/?>',
        html_text,
        flags=re.IGNORECASE,
    )
    if not match:
        errors.append("HTML缺少consumer-analysis-sha256数据血缘meta")
    elif match.group(1).casefold() != actual_analysis_sha.casefold():
        errors.append("HTML绑定的analysis SHA-256与实际analysis文件不一致")
    before = artifacts.get("original_dashboard_sha256_before")
    after = artifacts.get("original_dashboard_sha256_after")
    if before != after:
        errors.append("原机会看板前后SHA-256不一致")
    coding_project = coding.get("project") if isinstance(coding.get("project"), Mapping) else {}
    dashboard = coding_project.get("opportunity_dashboard")
    if not isinstance(dashboard, Mapping):
        errors.append("coding.project.opportunity_dashboard缺失")
    else:
        dashboard_path = _resolved_project_path(coding_project, dashboard.get("path"))
        if dashboard_path is None or not dashboard_path.is_file():
            errors.append("无法定位原机会看板以复核SHA-256")
        else:
            actual_dashboard_sha = hashlib.sha256(dashboard_path.read_bytes()).hexdigest()
            if actual_dashboard_sha != dashboard.get("sha256"):
                errors.append("原机会看板当前SHA-256与coding快照不一致")
            if actual_dashboard_sha != before:
                errors.append("report_artifacts中的原看板SHA-256不真实")
    return errors


def _ready_gate_errors(
    analysis: Mapping[str, Any],
    *,
    image_count: int | None = None,
    images: Mapping[str, Mapping[str, Any]] | None = None,
    analysis_path: Path | None = None,
    html_path: Path | None = None,
    html_text: str | None = None,
    coding_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    receipt = analysis.get("collection_receipt")
    if not isinstance(receipt, Mapping) or receipt.get("available") is not True:
        errors.append("ready必须有与本轮任务绑定的真实采集回执")
    deadline = (
        receipt.get("deadline_status")
        if isinstance(receipt, Mapping)
        and isinstance(receipt.get("deadline_status"), Mapping)
        else {}
    )
    if deadline.get("recorded") is not True:
        errors.append("ready必须有完整且有效的采集与总耗时记录")
    if deadline.get("deadline_exceeded") is True:
        errors.append("ready不允许完整任务超过所选档位总时间上限")
    elif deadline.get("deadline_exceeded") is not False:
        errors.append("ready必须由真实回执明确记录deadline_exceeded=false")

    time_usage = (
        receipt.get("time_usage_minutes")
        if isinstance(receipt, Mapping)
        and isinstance(receipt.get("time_usage_minutes"), Mapping)
        else {}
    )
    collection_minutes = _nullable_nonnegative_number(time_usage.get("collection"))
    total_minutes = _nullable_nonnegative_number(time_usage.get("total"))
    if collection_minutes is None or total_minutes is None:
        errors.append("ready采集回执必须记录有效的采集耗时和总耗时")
    else:
        total_budget = float(
            _research_plan(analysis)["time_budget_minutes"]["total"]
        )
        if total_minutes >= total_budget and deadline.get("deadline_exceeded") is not True:
            errors.append(
                "ready回执的实际总耗时已达到所选档位上限，不能声明未超时"
            )
    if analysis.get("schema_version") == SCHEMA_VERSION:
        plan = _research_plan(analysis)
        target = plan["sample_target"]
        denominators = (
            analysis.get("denominators")
            if isinstance(analysis.get("denominators"), Mapping)
            else {}
        )
        total_valid = int(denominators.get("N_union_mixed_window") or 0)
        if total_valid < int(target["total_valid_min"]):
            errors.append(
                f"ready的有效留言总量不足：{total_valid} < {target['total_valid_min']}"
            )
        denominator_keys = {
            CATEGORY_SCOPE: "N_category_30d",
            **{
                scope_id: f"N_segment_{index}_90d"
                for index, scope_id in enumerate(SEGMENT_SCOPES, start=1)
            },
        }
        for scope_id, scope_target in target["per_scope"].items():
            actual = int(denominators.get(denominator_keys[scope_id]) or 0)
            if actual < int(scope_target["valid_min"]):
                errors.append(
                    f"ready的{scope_id}有效留言不足：{actual} < {scope_target['valid_min']}"
                )
        quality = analysis.get("scope_quality")
        union_quality = next(
            (
                item
                for item in (quality if isinstance(quality, list) else [])
                if isinstance(item, Mapping)
                and item.get("scope_id") == "union_mixed_window"
            ),
            {},
        )
        platform_count = int(union_quality.get("platform_count") or 0)
        if platform_count < int(target["min_platforms"]):
            errors.append(
                f"ready的有效平台不足：{platform_count} < {target['min_platforms']}"
            )
    concepts = analysis.get("product_concepts")
    if not isinstance(concepts, list) or len(concepts) != 3:
        errors.append("ready必须恰好包含3个产品概念")
    else:
        concept_segments: set[str] = set()
        for index, concept in enumerate(concepts, start=1):
            artifact = concept.get("image_artifact") if isinstance(concept, Mapping) else None
            if not isinstance(artifact, Mapping) or artifact.get("status") != "ok":
                errors.append(f"concept_{index} 的image_artifact.status必须为ok")
            elif artifact.get("embedded_as_data_uri") is not True:
                errors.append(f"concept_{index} 的图片必须标记embedded_as_data_uri=true")
            if not isinstance(concept, Mapping):
                continue
            concept_segments.add(str(concept.get("segment_id") or ""))
            placeholders = _placeholder_locations(concept, f"concept_{index}")
            if placeholders:
                errors.append(
                    f"concept_{index}仍含占位内容：{', '.join(placeholders[:8])}"
                )
            for field in (
                "target_consumers",
                "use_scenarios",
                "evidence_origins",
                "kano_mapping",
                "features",
                "materials",
                "risks",
                "dependencies",
                "acceptance_metrics",
            ):
                if not isinstance(concept.get(field), list) or not concept.get(field):
                    errors.append(f"concept_{index}.{field}必须完成且非空")
            origins = concept.get("evidence_origins")
            if isinstance(origins, list) and not any(
                isinstance(origin, Mapping) and bool(origin.get("voice_ids"))
                for origin in origins
            ):
                errors.append(f"concept_{index}至少需要一组真实消费者voice_ids证据")
            moscow = concept.get("moscow") if isinstance(concept.get("moscow"), Mapping) else {}
            for bucket in ("must", "should", "could", "wont_this_release"):
                items = moscow.get(bucket)
                if not isinstance(items, list) or not items:
                    errors.append(f"concept_{index}.moscow.{bucket}必须非空")
                    continue
                for item_index, item in enumerate(items):
                    if not isinstance(item, Mapping):
                        continue
                    if not item.get("target_segment_ids"):
                        errors.append(
                            f"concept_{index}.moscow.{bucket}[{item_index}]缺少目标细分"
                        )
                    if not item.get("evidence_origins"):
                        errors.append(
                            f"concept_{index}.moscow.{bucket}[{item_index}]缺少证据绑定"
                        )
                    if not str(item.get("acceptance_criteria") or "").strip():
                        errors.append(
                            f"concept_{index}.moscow.{bucket}[{item_index}]缺少量化验收条件"
                        )
        selected_ids = {
            str(item.get("segment_id"))
            for item in analysis.get("segments", [])
            if isinstance(item, Mapping)
        }
        missing_concept_segments = sorted(selected_ids - concept_segments)
        if missing_concept_segments:
            errors.append(f"可用Top3细分未各自绑定产品方向：{missing_concept_segments}")
    segments = analysis.get("segments") if isinstance(analysis.get("segments"), list) else []
    segment_ids = {
        str(item.get("segment_id")) for item in segments if isinstance(item, Mapping)
    }
    supply = analysis.get("supply_validation")
    supply_items = supply if isinstance(supply, list) else []
    supply_by_segment = {
        str(item.get("segment_id")): item
        for item in supply_items
        if isinstance(item, Mapping)
    }
    for segment_id in sorted(segment_ids):
        validation = supply_by_segment.get(segment_id)
        if not isinstance(validation, Mapping):
            errors.append(f"{segment_id}缺少供给验证")
            continue
        method = validation.get("coverage_method")
        if method in {"top_30_by_sales", "both"} and int(validation.get("products_checked") or 0) < 30:
            errors.append(f"{segment_id}未覆盖销量前30款")
        if method in {"cumulative_80_percent_sales", "both"} and float(validation.get("cumulative_sales_share") or 0) < 0.8:
            errors.append(f"{segment_id}累计销量覆盖不足80%")
        checked_layers = validation.get("checked_layers")
        if isinstance(checked_layers, Mapping):
            for layer_name, layer in checked_layers.items():
                if not isinstance(layer, Mapping) or layer.get("status") != "complete":
                    errors.append(f"{segment_id}.checked_layers.{layer_name}未完整检查")
        if not validation.get("supply_evidence") or not validation.get("demand_voice_ids"):
            errors.append(f"{segment_id}供给验证缺少供需双侧可追溯证据")
        if not validation.get("findings"):
            errors.append(f"{segment_id}供给验证缺少逐项finding")
    union = analysis.get("union_analysis") if isinstance(analysis.get("union_analysis"), Mapping) else {}
    if not union.get("kano_differences"):
        errors.append("ready缺少跨层KANO差异分析")
    if not union.get("development_priorities"):
        errors.append("ready缺少联合产品开发优先项")
    artifacts = analysis.get("report_artifacts")
    if not isinstance(artifacts, Mapping):
        errors.append("ready缺少report_artifacts")
    else:
        if artifacts.get("embedded_image_count") != 3:
            errors.append("ready的embedded_image_count必须为3")
        if artifacts.get("all_product_images_ready") is not True:
            errors.append("ready的all_product_images_ready必须为true")
        if artifacts.get("standalone_html") is not True:
            errors.append("ready的standalone_html必须为true")
        if artifacts.get("external_runtime_dependencies") != []:
            errors.append("ready不得有外部运行时依赖")
        if artifacts.get("original_dashboard_sha256_before") != artifacts.get(
            "original_dashboard_sha256_after"
        ):
            errors.append("原机会看板前后SHA-256不一致")
    if image_count is not None and image_count != 3:
        errors.append("ready渲染必须传入3张概念图")
    errors.extend(
        _ready_image_artifact_errors(
            analysis,
            images=images,
            analysis_path=analysis_path,
            html_path=html_path,
            html_text=html_text,
        )
    )
    effective_html = html_text
    if effective_html is None and html_path is not None and html_path.is_file():
        try:
            effective_html = html_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"无法检查ready HTML：{exc}")
    if effective_html is not None:
        errors.extend(_offline_dependency_errors(effective_html))
    if coding_path is not None and coding_path.is_file():
        coding = _load_json(coding_path)
        project = coding.get("project") if isinstance(coding, Mapping) else None
        dashboard = project.get("opportunity_dashboard") if isinstance(project, Mapping) else None
        if isinstance(dashboard, Mapping):
            dashboard_path = Path(str(dashboard.get("path") or ""))
            if not dashboard_path.is_absolute() and project.get("project_root"):
                dashboard_path = Path(str(project["project_root"])) / dashboard_path
            if not dashboard_path.is_file():
                errors.append("无法定位原机会看板以复核SHA-256")
            else:
                actual = hashlib.sha256(dashboard_path.read_bytes()).hexdigest()
                declared = str(dashboard.get("sha256") or "")
                if actual != declared:
                    errors.append("原机会看板当前SHA-256与coding快照不一致")
                if isinstance(artifacts, Mapping) and actual != artifacts.get(
                    "original_dashboard_sha256_before"
                ):
                    errors.append("report_artifacts中的原看板SHA-256不真实")
        else:
            errors.append("coding.project.opportunity_dashboard缺失，无法复核原机会看板")
    return errors


def _manifest_dashboard_snapshot(
    manifest_path: Path, manifest: Mapping[str, Any]
) -> tuple[Path, str]:
    artifacts = manifest.get("artifacts")
    artifact_map = artifacts if isinstance(artifacts, Mapping) else {}
    raw_artifact: Any = None
    for key in (
        "market_opportunity_html",
        "market_opportunity_dashboard",
        "market_dashboard",
    ):
        if key in artifact_map:
            raw_artifact = artifact_map[key]
            break
    expected_sha: str | None = None
    if isinstance(raw_artifact, Mapping):
        raw_path = raw_artifact.get("path")
        declared_sha = str(raw_artifact.get("sha256") or "").strip().casefold()
        expected_sha = declared_sha or None
    else:
        raw_path = raw_artifact
    if not str(raw_path or "").strip():
        raw_path = "market_opportunity/市场机会深挖看板.html"
    dashboard_path = Path(str(raw_path)).expanduser()
    if not dashboard_path.is_absolute():
        dashboard_path = manifest_path.resolve().parent / dashboard_path
    dashboard_path = dashboard_path.resolve()
    if not dashboard_path.is_file():
        raise ContractError(f"无法定位原机会看板以复核SHA-256：{dashboard_path}")
    actual_sha = hashlib.sha256(dashboard_path.read_bytes()).hexdigest()
    if expected_sha is not None and actual_sha.casefold() != expected_sha:
        raise ContractError("manifest记录的原机会看板SHA-256与当前文件不一致")
    return dashboard_path, actual_sha


def finalize_manifest(
    manifest_path: Path,
    coding_path: Path,
    analysis_path: Path,
    report_path: Path,
    status: str,
) -> dict[str, Any]:
    if status not in {"ready", "partial", "failed"}:
        raise ContractError("status 必须为 ready、partial 或 failed")
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ContractError("project_manifest.json 顶层必须是对象")
    dashboard_path, dashboard_sha_before = _manifest_dashboard_snapshot(
        manifest_path, manifest
    )
    for label, path in (
        ("coding", coding_path),
        ("analysis", analysis_path),
        ("report", report_path),
    ):
        if status != "failed" and not path.is_file():
            raise ContractError(f"status={status} 时 {label} 产物必须存在：{path}")
    if status in {"partial", "ready"}:
        coding_document = _load_json(coding_path)
        if not isinstance(coding_document, Mapping):
            raise ContractError(f"{status}时消费者声音coding JSON顶层必须是对象")
        # Includes the formal schema and every cross-field/window/dedupe check.
        validate_coding_document(coding_document, reject_duplicates=True)
        analysis_document = _load_json(analysis_path)
        if not isinstance(analysis_document, Mapping):
            raise ContractError(f"{status}时综合分析JSON顶层必须是对象")
        removed_errors = _v2_removed_analysis_field_errors(analysis_document)
        if removed_errors:
            raise ContractError("v2分析包含已移除的最近30天细分字段", removed_errors)
        _validate_against_schema(
            analysis_document,
            Path(__file__).resolve().parent.parent
            / "references"
            / "social_voice_analysis.schema.json",
            "消费者声音分析",
        )
        denominators = analysis_document.get("denominators")
        union_count = (
            denominators.get("N_union_mixed_window")
            if isinstance(denominators, Mapping)
            else None
        )
        if not isinstance(union_count, int) or union_count <= 0:
            raise ContractError(
                "没有有效的硬身份唯一消费者留言时不得finalize为partial或ready；请使用failed"
            )
        validation_errors = _recomputed_analysis_errors(
            coding_document,
            analysis_document,
            coding_path=coding_path,
            analysis_path=analysis_path,
        )
        validation_errors.extend(
            _artifact_integrity_errors(
                coding_document,
                analysis_document,
                coding_path=coding_path,
                analysis_path=analysis_path,
                html_path=report_path,
            )
        )
        report_artifacts = analysis_document.get("report_artifacts")
        if isinstance(report_artifacts, Mapping) and report_artifacts.get("status") != status:
            validation_errors.append(
                f"report_artifacts.status必须与finalize状态一致：{status}"
            )
        if validation_errors:
            raise ContractError(f"产物未通过{status}数据闭环校验", validation_errors)
    if status == "ready":
        ready_errors = _ready_gate_errors(
            analysis_document,
            analysis_path=analysis_path,
            html_path=report_path,
            coding_path=coding_path,
        )
        if ready_errors:
            raise ContractError("产物未通过ready最终化门禁", ready_errors)
    updated = copy.deepcopy(dict(manifest))
    artifacts = updated.get("artifacts")
    if artifacts is None:
        artifacts = {}
    if not isinstance(artifacts, Mapping):
        raise ContractError("manifest.artifacts 必须是对象")
    artifacts = dict(artifacts)
    artifacts.update(
        {
            "consumer_voice_coding": _manifest_artifact_path(manifest_path, coding_path),
            "consumer_voice_analysis": _manifest_artifact_path(manifest_path, analysis_path),
            "consumer_product_report_html": _manifest_artifact_path(manifest_path, report_path),
        }
    )
    status_object = updated.get("status")
    if status_object is None:
        status_object = {}
    if not isinstance(status_object, Mapping):
        raise ContractError("manifest.status 必须是对象")
    status_object = dict(status_object)
    status_object["consumer_product_discovery"] = status
    updated["artifacts"] = artifacts
    updated["status"] = status_object
    dashboard_sha_prewrite = hashlib.sha256(dashboard_path.read_bytes()).hexdigest()
    if dashboard_sha_prewrite != dashboard_sha_before:
        raise ContractError("最终化期间原机会看板SHA-256发生变化，已停止更新manifest")
    _atomic_write_json(manifest_path, updated)
    dashboard_sha_after = hashlib.sha256(dashboard_path.read_bytes()).hexdigest()
    if dashboard_sha_after != dashboard_sha_before:
        raise ContractError("原机会看板SHA-256在manifest更新后发生变化")
    return {
        "status": "updated",
        "manifest": str(manifest_path),
        "consumer_product_discovery": status,
        "artifact_keys": [
            "consumer_voice_coding",
            "consumer_voice_analysis",
            "consumer_product_report_html",
        ],
        "preserved_existing_keys": True,
        "original_dashboard_sha256_verified": dashboard_sha_after,
    }


def _load_consumer_voice_collector() -> Any:
    module_path = Path(__file__).resolve().with_name("consumer_voice_collector.py")
    spec = importlib.util.spec_from_file_location(
        "lc_amazon_market_opportunity_consumer_voice_collector", module_path
    )
    if spec is None or spec.loader is None:
        raise ContractError("无法加载消费者声音collector计时模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _timed_finalize_lineage_errors(
    store: Any,
    task_id: str,
    run_dir: Path,
    manifest_path: Path,
    coding_path: Path,
    analysis_path: Path,
    report_path: Path,
    *,
    require_receipt: bool = True,
) -> list[str]:
    """Bind the collector clock, receipt and every deliverable before writes."""
    errors: list[str] = []
    task = store.task_payload(task_id)
    declared_run = str(task.get("run_dir") or "").strip()
    declared_project = str(task.get("project_dir") or "").strip()
    project_dir: Path | None = None
    if not declared_run or Path(declared_run).expanduser().resolve() != run_dir:
        errors.append("collector task.run_dir与--collector-run-dir不一致")
    if not declared_project:
        errors.append("collector task.project_dir缺失")
    else:
        project_dir = Path(declared_project).expanduser().resolve()
        if manifest_path != (project_dir / "project_manifest.json").resolve():
            errors.append("--manifest不是collector任务项目的project_manifest.json")
        expected_opportunity_dir = (project_dir / "market_opportunity").resolve()
        if report_path.parent != expected_opportunity_dir:
            errors.append("--report必须直接位于collector任务项目的market_opportunity目录")
    if coding_path != (run_dir / "social_voice_coding.json").resolve():
        errors.append("--coding必须是collector任务目录内的social_voice_coding.json")
    if analysis_path != (run_dir / "social_voice_analysis.json").resolve():
        errors.append("--analysis必须是collector任务目录内的social_voice_analysis.json")

    receipt_path = run_dir / "collection_receipt.json"
    if require_receipt and not receipt_path.is_file():
        errors.append("timed finalize缺少当前任务collection_receipt.json")
    elif require_receipt:
        try:
            receipt = _load_json(receipt_path)
        except ContractError as exc:
            errors.append(str(exc))
        else:
            if not isinstance(receipt, Mapping):
                errors.append("collection_receipt.json顶层必须是对象")
            else:
                if str(receipt.get("task_id") or "").strip() != task_id:
                    errors.append("collection_receipt.task_id与collector SQLite任务不一致")
                receipt_run = str(receipt.get("run_dir") or "").strip()
                if not receipt_run or Path(receipt_run).expanduser().resolve() != run_dir:
                    errors.append("collection_receipt.run_dir与collector任务目录不一致")
                if receipt.get("research_plan") != task.get("research_plan"):
                    errors.append("collection_receipt.research_plan与collector SQLite任务不一致")

    expected_manifest = (
        (project_dir / "project_manifest.json").resolve()
        if project_dir is not None
        else None
    )
    pending = store.connection.execute(
        """SELECT manifest_path FROM manifest_finalize_intents
        WHERE task_id=? AND state IN ('preparing','manifest_written')""",
        (task_id,),
    ).fetchall()
    if expected_manifest is not None and any(
        Path(str(row["manifest_path"])).expanduser().resolve() != expected_manifest
        for row in pending
    ):
        errors.append("存在不属于当前collector项目的未提交manifest intent，已拒绝自动恢复")
    return errors


def _write_authoritative_collection_receipt(
    collector: Any,
    store: Any,
    run_dir: Path,
    task_id: str,
) -> Mapping[str, Any]:
    receipt = collector.build_receipt(store, task_id)
    collector.write_json(run_dir / "collection_receipt.json", receipt)
    return receipt


def _committed_manifest_artifact_errors(
    manifest_path: Path,
    coding_path: Path,
    analysis_path: Path,
    report_path: Path,
) -> list[str]:
    manifest = _load_json(manifest_path)
    artifacts = manifest.get("artifacts") if isinstance(manifest, Mapping) else None
    if not isinstance(artifacts, Mapping):
        return ["已提交manifest缺少artifacts对象"]
    errors: list[str] = []
    expected = {
        "consumer_voice_coding": coding_path,
        "consumer_voice_analysis": analysis_path,
        "consumer_product_report_html": report_path,
    }
    for key, expected_path in expected.items():
        raw = artifacts.get(key)
        if isinstance(raw, Mapping):
            raw = raw.get("path")
        text = str(raw or "").strip()
        if not text:
            errors.append(f"已提交manifest缺少{key}")
            continue
        declared = Path(text).expanduser()
        if not declared.is_absolute():
            declared = manifest_path.parent / declared
        if declared.resolve() != expected_path:
            errors.append(f"已提交manifest的{key}与本次参数不一致")
    return errors


def finalize_manifest_timed(
    manifest_path: Path,
    coding_path: Path,
    analysis_path: Path,
    report_path: Path,
    status: str,
    collector_run_dir: Path,
    phase_run_id: str,
    event_id: str,
    *,
    _collector_module: Any = None,
    _boot_id: str | None = None,
    _monotonic_ns: Callable[[], int] | None = None,
    _after_candidate_write: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Atomically finalize the project manifest under the collector clock.

    The visible manifest is written before phase-end so its I/O is metered.  A
    durable SQLite intent carries the exact pre-write manifest; deadline races,
    exceptions and crash recovery restore that prior file instead of publishing
    a status whose analysis/HTML lineage was not committed in time.
    """

    collector = _collector_module or _load_consumer_voice_collector()
    run_dir = Path(collector_run_dir).expanduser().resolve()
    db_path = run_dir / "collector.sqlite3"
    if not db_path.is_file():
        raise ContractError(f"collector运行数据库不存在：{db_path}")
    manifest_path = Path(manifest_path).expanduser().resolve()
    coding_path = Path(coding_path).expanduser().resolve()
    analysis_path = Path(analysis_path).expanduser().resolve()
    report_path = Path(report_path).expanduser().resolve()
    phase_identifier = str(phase_run_id or "").strip()
    event_identifier = str(event_id or "").strip()
    if not phase_identifier or not event_identifier:
        raise ContractError("timed finalize-manifest 必须提供phase-run-id和event-id")

    shadow_path: Path | None = None
    intent: Mapping[str, Any] | None = None
    candidate_written = False
    phase_closed = False
    manifest_committed = False
    with collector.CollectorStore(db_path) as store:
        task_id = store.resolve_task_id(None)
        existing = store.manifest_finalize_intent(task_id, phase_identifier)
        lineage_errors = _timed_finalize_lineage_errors(
            store,
            task_id,
            run_dir,
            manifest_path,
            coding_path,
            analysis_path,
            report_path,
            require_receipt=not bool(
                isinstance(existing, Mapping)
                and existing.get("state") == "committed"
            ),
        )
        if lineage_errors:
            raise ContractError("timed finalize-manifest任务与产物血缘不一致", lineage_errors)
        if existing is not None and existing.get("state") == "committed":
            if existing.get("event_id") != event_identifier:
                raise ContractError("phase-run-id已经由另一event-id完成manifest提交")
            final_hash = str(existing.get("final_manifest_sha256") or "")
            if not manifest_path.is_file() or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != final_hash:
                raise ContractError("幂等manifest提交记录与当前文件SHA-256不一致")
            committed_lineage_errors = _committed_manifest_artifact_errors(
                manifest_path, coding_path, analysis_path, report_path
            )
            if committed_lineage_errors:
                raise ContractError(
                    "已提交manifest与本次幂等重放产物血缘不一致",
                    committed_lineage_errors,
                )
            try:
                _write_authoritative_collection_receipt(
                    collector, store, run_dir, task_id
                )
            except Exception as exc:
                raise ContractError(
                    "manifest已经提交，但最终回执自愈写入失败；请修复文件系统后重放相同命令",
                    [str(exc)],
                ) from exc
            return {
                "status": "updated",
                "manifest": str(manifest_path),
                "consumer_product_discovery": existing.get("final_status"),
                "timed_finalize": True,
                "replayed": True,
                "intent_id": existing.get("intent_id"),
                "sha256": final_hash,
            }
        # A non-committed intent means a previous process stopped after opening
        # this phase.  Fail closed: restore the old manifest and require a fresh
        # phase instead of guessing whether the visible candidate was durable.
        store.recover_manifest_finalize_intents(
            task_id,
            abandon_running=True,
            reason="next_timed_finalize_recovery",
        )
        phase = store.connection.execute(
            "SELECT * FROM timing_sessions WHERE task_id=? AND phase_run_id=?",
            (task_id, phase_identifier),
        ).fetchone()
        if phase is None or str(phase["phase"]) != "manifest_finalize":
            raise ContractError("phase-run-id未绑定当前任务的manifest_finalize阶段")
        if str(phase["status"]) != "running":
            raise ContractError("manifest_finalize阶段已关闭，请开始新的计时阶段")
        timing_kwargs: dict[str, Any] = {}
        if _boot_id is not None:
            timing_kwargs["boot_id"] = _boot_id
        if _monotonic_ns is not None:
            timing_kwargs["monotonic_ns"] = int(_monotonic_ns())
        gate = store.timing_gate(
            task_id,
            "manifest_finalize",
            **timing_kwargs,
        )
        if not gate.get("allowed") or float(gate.get("max_step_seconds") or 0) <= 0:
            raise ContractError("manifest_finalize已无总时间余量，未写入任何manifest")

        try:
            previous_bytes = manifest_path.read_bytes()
            descriptor, shadow_name = tempfile.mkstemp(
                prefix=".%s.timed." % manifest_path.name,
                suffix=".json",
                dir=str(manifest_path.parent),
            )
            os.close(descriptor)
            shadow_path = Path(shadow_name)
            _atomic_write_text(shadow_path, previous_bytes.decode("utf-8"))
            result = finalize_manifest(
                shadow_path,
                coding_path,
                analysis_path,
                report_path,
                status,
            )
            candidate_bytes = shadow_path.read_bytes()
            candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
            intent = store.create_manifest_finalize_intent(
                task_id,
                phase_identifier,
                event_identifier,
                manifest_path,
                status,
                candidate_hash,
                previous_bytes,
            )
            _atomic_write_text(manifest_path, candidate_bytes.decode("utf-8"))
            candidate_written = True
            store.mark_manifest_finalize_intent_written(task_id, str(intent["intent_id"]))
            if _after_candidate_write is not None:
                _after_candidate_write()

            end_kwargs: dict[str, Any] = {}
            if _boot_id is not None:
                end_kwargs["boot_id"] = _boot_id
            if _monotonic_ns is not None:
                end_kwargs["monotonic_ns"] = int(_monotonic_ns())
            timing_result = store.end_timing_phase(
                task_id,
                phase_identifier,
                event_identifier,
                **end_kwargs,
            )
            phase_closed = True
            deadline_exceeded = bool(
                isinstance(timing_result.get("gate"), Mapping)
                and timing_result["gate"].get("deadline_exceeded")
            )
            if deadline_exceeded:
                rolled_back = store.rollback_manifest_finalize_intent(
                    task_id,
                    str(intent["intent_id"]),
                    "manifest_finalize_total_deadline",
                )
                intent = None
                candidate_written = False
                receipt = collector.build_receipt(store, task_id)
                collector.write_json(run_dir / "collection_receipt.json", receipt)
                raise ContractError(
                    "manifest_finalize在候选写入后超过总时间上限；已原子恢复旧manifest，"
                    "本次产物未发布",
                    [f"rolled_back_intent={rolled_back['intent_id']}"],
                )
            precommit_receipt = collector.build_receipt(store, task_id)
            snapshot_errors = _final_receipt_snapshot_errors(
                analysis_path, precommit_receipt
            )
            if snapshot_errors:
                raise ContractError(
                    "最终采集回执早于报告内耗时快照，已停止manifest提交",
                    snapshot_errors,
                )
            final_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            committed = store.complete_manifest_finalize_intent(
                task_id,
                str(intent["intent_id"]),
                status,
                final_hash,
            )
            manifest_committed = True
            try:
                _write_authoritative_collection_receipt(
                    collector, store, run_dir, task_id
                )
            except Exception as exc:
                raise ContractError(
                    "manifest已经提交，但最终回执写入失败；请修复文件系统后重放相同命令自愈",
                    [str(exc)],
                ) from exc
            return {
                **result,
                "manifest": str(manifest_path),
                "consumer_product_discovery": status,
                "timed_finalize": True,
                "replayed": False,
                "deadline_downgraded": False,
                "intent_id": committed["intent_id"],
                "timing": timing_result,
                "sha256": final_hash,
            }
        except BaseException as exc:
            # SystemExit/KeyboardInterrupt model an abrupt process loss in tests;
            # leave the durable intent for receipt/resume recovery.
            if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                raise
            current_intent = (
                store.manifest_finalize_intent(task_id, phase_identifier)
                if intent is not None
                else None
            )
            committed_state = bool(
                manifest_committed
                or (
                    isinstance(current_intent, Mapping)
                    and current_intent.get("state") == "committed"
                )
            )
            if intent is not None and not committed_state:
                store.rollback_manifest_finalize_intent(
                    task_id, str(intent["intent_id"]), str(exc)
                )
            elif candidate_written:
                if not committed_state:
                    _atomic_write_text(manifest_path, previous_bytes.decode("utf-8"))
            if not phase_closed:
                try:
                    end_kwargs = {}
                    if _boot_id is not None:
                        end_kwargs["boot_id"] = _boot_id
                    if _monotonic_ns is not None:
                        end_kwargs["monotonic_ns"] = int(_monotonic_ns())
                    store.end_timing_phase(
                        task_id, phase_identifier, event_identifier, **end_kwargs
                    )
                except Exception:
                    pass
            try:
                _write_authoritative_collection_receipt(
                    collector, store, run_dir, task_id
                )
            except Exception:
                pass
            if isinstance(exc, ContractError):
                raise
            raise ContractError("timed finalize-manifest失败", [str(exc)]) from exc
        finally:
            if shadow_path is not None:
                try:
                    shadow_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="consumer_product_report.py",
        description="全品类30天 + Top3细分90天消费者声音联合分析工具（纯标准库）。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser(
        "select-segments",
        help="从07_opportunity_analysis.json按固定3％-20％规则选择Top3细分。",
    )
    select_parser.add_argument("--analysis", required=True, type=Path, help="07_opportunity_analysis.json")
    select_parser.add_argument("--output", required=True, type=Path, help="Top3细分JSON输出路径")

    validate_parser = subparsers.add_parser(
        "validate-coding",
        help="校验逐条消费者声音编码、双窗口、语义归属和重复键。",
    )
    validate_parser.add_argument(
        "--input",
        "--coding",
        dest="coding",
        required=True,
        type=Path,
        help="消费者声音编码JSON（--coding为兼容别名）",
    )
    validate_parser.add_argument("--output", type=Path, help="可选校验报告JSON输出路径")

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="从逐条编码重算分母、分层需求、满意/不满意、创意和KANO。",
    )
    analyze_parser.add_argument(
        "--coding",
        "--input",
        dest="coding",
        required=True,
        type=Path,
        help="消费者声音编码JSON（--input为兼容别名）",
    )
    analyze_parser.add_argument(
        "--segments",
        type=Path,
        help="可选的select-segments输出；提供时覆盖编码文件中的segments",
    )
    analyze_parser.add_argument("--output", required=True, type=Path, help="综合分析JSON输出路径")
    analyze_parser.add_argument(
        "--report-output",
        type=Path,
        help="计划生成的独立HTML路径；用于分析与报告血缘绑定",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="使用模板与可选概念图生成无外部渲染依赖的独立HTML。",
    )
    render_parser.add_argument("--analysis", required=True, type=Path, help="综合分析JSON")
    render_parser.add_argument("--template", required=True, type=Path, help="HTML模板")
    render_parser.add_argument("--output", required=True, type=Path, help="独立HTML输出路径")
    render_parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="概念图，可重复；图片会被转为data URI。",
    )
    render_parser.add_argument(
        "--title", default="消费者声音与产品创意开发报告", help="报告标题"
    )

    manifest_parser = subparsers.add_parser(
        "finalize-manifest",
        help="原子增量更新project_manifest.json，不删除或覆盖其他键。",
    )
    manifest_parser.add_argument("--manifest", required=True, type=Path, help="project_manifest.json")
    manifest_parser.add_argument("--coding", required=True, type=Path, help="消费者声音编码JSON")
    manifest_parser.add_argument("--analysis", required=True, type=Path, help="综合分析JSON")
    manifest_parser.add_argument("--report", required=True, type=Path, help="独立HTML报告")
    manifest_parser.add_argument(
        "--status",
        choices=("ready", "partial", "failed"),
        default="ready",
        help="消费者产品发现阶段状态（默认ready）",
    )
    manifest_parser.add_argument(
        "--collector-run-dir",
        type=Path,
        help="启用计时原子最终化时的consumer_voice运行目录",
    )
    manifest_parser.add_argument(
        "--phase-run-id",
        help="已开始的manifest_finalize计时阶段ID",
    )
    manifest_parser.add_argument(
        "--event-id",
        help="manifest_finalize phase-end幂等事件ID",
    )
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "select-segments":
        analysis = _load_json(args.analysis)
        if not isinstance(analysis, Mapping):
            raise ContractError("机会分析JSON顶层必须是对象")
        result = select_segments(analysis)
        _atomic_write_json(args.output, result)
        return {
            "status": "ok",
            "command": args.command,
            "output": str(args.output),
            "selected_count": result["selected_count"],
            "selection_complete": result["selection_complete"],
            "selected_segments": [
                {
                    "rank": item["rank"],
                    "segment_id": item["segment_id"],
                    "dimension": item["dimension"],
                    "feature": item["feature"],
                    "listing_share": item["listing_share"],
                    "supply_demand_index": item["supply_demand_index"],
                }
                for item in result["selected_segments"]
            ],
        }
    if args.command == "validate-coding":
        document = _load_json(args.coding)
        normalized, report = validate_coding_document(document, reject_duplicates=True)
        if args.output:
            _atomic_write_json(args.output, report)
        return {
            "status": "ok",
            "command": args.command,
            "coding": str(args.coding),
            "output": str(args.output) if args.output else None,
            "voice_count": len(normalized["voices"]),
            "warning_count": report["warning_count"],
        }
    if args.command == "analyze":
        document = _load_json(args.coding)
        if not isinstance(document, Mapping):
            raise ContractError("编码文件顶层必须是对象")
        if args.segments:
            segment_document = _load_json(args.segments)
            if not isinstance(segment_document, Mapping) or not isinstance(
                segment_document.get("selected_segments"), list
            ):
                raise ContractError("--segments 必须是select-segments生成的JSON")
            # The analysis must remain reproducible from the exact coding bytes
            # named by coding_sha256.  --segments is therefore an assertion, not
            # an in-memory override that would silently break that provenance.
            if document.get("segments") != segment_document.get("selected_segments"):
                raise ContractError(
                    "--segments与coding.segments不一致；请先把已确认Top3写回coding后再分析"
                )
            if isinstance(segment_document.get("top3_selection"), Mapping) and document.get(
                "top3_selection"
            ) != segment_document.get("top3_selection"):
                raise ContractError(
                    "--segments.top3_selection与coding.top3_selection不一致"
                )
        result = analyze_coding(
            document,
            coding_path=args.coding,
            output_path=args.output,
            report_path=args.report_output,
        )
        _validate_against_schema(
            result,
            Path(__file__).resolve().parent.parent
            / "references"
            / "social_voice_analysis.schema.json",
            "消费者声音分析",
        )
        _atomic_write_json(args.output, result)
        eligible_voices = [
            voice
            for voice in _document_voices(document)
            if voice.get("eligible_for_quantitation") is True
        ]
        _, dedupe_summary = _deduplicate_voices(eligible_voices)
        return {
            "status": "ok",
            "command": args.command,
            "output": str(args.output),
            "denominators": result["denominators"],
            "duplicate_count": dedupe_summary["duplicate_count"],
        }
    if args.command == "render":
        analysis = _load_json(args.analysis)
        if not isinstance(analysis, Mapping):
            raise ContractError("综合分析JSON顶层必须是对象")
        result = render_report(
            analysis,
            args.template,
            args.output,
            args.image,
            args.title,
            analysis_path=args.analysis,
        )
        return {"status": "ok", "command": args.command, **result}
    if args.command == "finalize-manifest":
        timed_values = (args.collector_run_dir, args.phase_run_id, args.event_id)
        if any(timed_values) and not all(timed_values):
            raise ContractError(
                "timed finalize-manifest必须同时提供--collector-run-dir、--phase-run-id和--event-id"
            )
        if all(timed_values):
            result = finalize_manifest_timed(
                args.manifest,
                args.coding,
                args.analysis,
                args.report,
                args.status,
                args.collector_run_dir,
                args.phase_run_id,
                args.event_id,
            )
        else:
            result = finalize_manifest(
                args.manifest, args.coding, args.analysis, args.report, args.status
            )
        return {"status": "ok", "command": args.command, **result}
    raise ContractError(f"未知命令：{args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except ContractError as exc:
        _print_json(
            {
                "status": "error",
                "command": getattr(args, "command", None),
                "message": str(exc),
                "details": exc.details,
            },
            stream=sys.stderr,
        )
        return 2
    except OSError as exc:
        _print_json(
            {
                "status": "error",
                "command": getattr(args, "command", None),
                "message": "文件系统操作失败",
                "details": [str(exc)],
            },
            stream=sys.stderr,
        )
        return 3
    _print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
