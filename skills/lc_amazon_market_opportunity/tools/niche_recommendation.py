#!/usr/bin/env python3
"""Select a frozen Top3 shortlist, then add per-market deep analysis.

The legacy market-opportunity CLI remains the source of tag analysis.  This tool
only reads its completed outputs, user-supplied POE Excel, and paths explicitly
recorded in the project's input manifest.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import itertools
import importlib.util
import json
import math
import os
import posixpath
import re
import statistics
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as et
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


RULE_VERSION = "niche_recommendation_v10_dual_source_robust"
RUN_ID_PREFIX = "niche-v10"
SCHEMA_VERSION = "5.0.0"
POE_SEARCH_TREND_FIELDS = (
    "搜索量增长率-近90天 (%)",
    "搜索量增长率-近180天 (%)",
    "搜索量增长率-近360天 (%)",
)
POE_SCORING_FIELDS = (
    "搜索量-近90天",
    "销量-近90天",
    "前5商品点击占比-近90天 (%)",
    "前5商品点击占比-近360天 (%)",
    "前5品牌点击占比-近90天 (%)",
    "前5品牌点击占比-近360天 (%)",
    "新品发布数-360天",
    "成功发布数-360天",
)
POE_CONTEXT_FIELDS = (
    "点击转化率-近90天 (%)",
    "平均售价-近90天 ($)",
    "退货率-近360天 (%)",
)
POE_ENTRY_VALUE_FIELDS = (*POE_SCORING_FIELDS, *POE_CONTEXT_FIELDS)
POE_REQUIRED_FIELDS = ("细分市场名称", "细分市场分类1")
SCORE_WEIGHTS = {
    "supply_demand": 80.0,
    "competition_openness": 10.0,
    "new_product_evidence": 5.0,
    "demand_scale": 5.0,
}
SUPPLY_DEMAND_ANCHORS = ((0.0, 0.0), (0.8, 30.0), (1.0, 50.0), (1.2, 70.0), (1.4, 80.0), (1.6, 90.0), (1.8, 100.0))
UNKNOWN_VALUES = {"unrecognized", "不可识别", "other", "其他"}
NON_CANDIDATE_VALUES = {"通用未限定", "未披露充电", "非候选安装位", "general_unspecified_position", "no_charging_disclosed", "not_car_or_not_specified", "other_or_unspecified_mechanism"}
UNKNOWN_BRANDS = {"", "na", "n/a", "unknown", "未知", "not provided"}
POE_DISPOSITIONS = {
    "direct_need",
    "brand_navigation",
    "accessory",
    "other_use",
    "ambiguous",
}


class RecommendationError(RuntimeError):
    """A user-correctable input or contract error."""


def fail(message: str) -> None:
    raise RecommendationError(message)


def guarded(collect: list[str] | None, function: Any, *args: Any) -> Any:
    """Run a validation step; in collect mode record its error and return None instead of stopping."""
    if collect is None:
        return function(*args)
    try:
        return function(*args)
    except RecommendationError as exc:
        collect.append(str(exc))
        return None


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def display_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalized_asin(value: Any) -> str:
    return display_text(value).upper()


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = display_text(value)
    if not text:
        return None
    text = text.replace(",", "").replace("$", "").replace("%", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def percentage_points(value: Any) -> float | None:
    """POE (%) columns contain points; Excel percentage styles are handled at import."""
    return parse_number(value)


def json_canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        fail(f"缺少{label}：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"无法读取{label}：{path}（{exc}）")


def xlsx_sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook_path = "xl/workbook.xml"
    relationships_path = "xl/_rels/workbook.xml.rels"
    if workbook_path not in archive.namelist() or relationships_path not in archive.namelist():
        fail("不是可读取的 .xlsx 工作簿")
    workbook = et.fromstring(archive.read(workbook_path))
    relationships = et.fromstring(archive.read(relationships_path))
    targets = {
        relation.attrib.get("Id"): relation.attrib.get("Target", "")
        for relation in relationships
        if relation.attrib.get("Id")
    }
    resolved: dict[str, str] = {}
    relationship_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.findall(".//{*}sheet"):
        name = sheet.attrib.get("name")
        target = targets.get(sheet.attrib.get(relationship_id))
        if name and target:
            resolved[name] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    return resolved


def extract_xml_text(node: et.Element) -> str:
    return "".join(part.text or "" for part in node.iter() if part.tag.endswith("}t"))


def column_index(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference)
    if not letters:
        return 0
    value = 0
    for character in letters.group(1):
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[tuple[int, list[Any]]]:
    if not path.is_file():
        fail(f"缺少 Excel 文件：{path}")
    try:
        with zipfile.ZipFile(path) as archive:
            sheets = xlsx_sheet_paths(archive)
            if sheet_name not in sheets:
                fail(f"Excel 缺少工作表“{sheet_name}”，可用工作表：{'、'.join(sheets) or '无'}")
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = et.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [extract_xml_text(item) for item in shared_root.findall(".//{*}si")]
            root = et.fromstring(archive.read(sheets[sheet_name]))
            percent_styles = set()
            if "xl/styles.xml" in archive.namelist():
                styles = et.fromstring(archive.read("xl/styles.xml"))
                formats = {int(n.attrib["numFmtId"]): n.attrib.get("formatCode", "") for n in styles.findall(".//{*}numFmt")}
                for i, xf in enumerate(styles.findall("{*}cellXfs/{*}xf")):
                    fmt_id = int(xf.attrib.get("numFmtId", "0"))
                    fmt = re.sub(r'"[^"]*"|\\.', '', formats.get(fmt_id, ""))
                    if fmt_id in {9, 10} or "%" in fmt:
                        percent_styles.add(i)
    except (OSError, zipfile.BadZipFile, et.ParseError) as exc:
        fail(f"无法读取 Excel {path.name}：{exc}")

    rows: list[tuple[int, list[Any]]] = []
    for row in root.findall(".//{*}sheetData/{*}row"):
        values: dict[int, Any] = {}
        for cell in row.findall("{*}c"):
            index = column_index(cell.attrib.get("r", ""))
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value: Any = extract_xml_text(cell)
            else:
                value_node = cell.find("{*}v")
                raw = value_node.text if value_node is not None else ""
                if cell_type == "s" and raw:
                    try:
                        value = shared_strings[int(raw)]
                    except (ValueError, IndexError):
                        value = raw
                elif cell_type == "b":
                    value = raw == "1"
                elif cell_type == "str":
                    value = raw
                elif raw == "":
                    value = None
                else:
                    try:
                        parsed = float(raw)
                        value = int(parsed) if parsed.is_integer() else parsed
                    except ValueError:
                        value = raw
            if isinstance(value, (int, float)) and not isinstance(value, bool) and int(cell.attrib.get("s", "0")) in percent_styles:
                value = f"{value * 100:.12g}%"
            values[index] = value
        maximum = max(values, default=-1)
        rows.append((int(row.attrib.get("r", len(rows) + 1)), [values.get(i) for i in range(maximum + 1)]))
    return rows


def table_from_sheet(path: Path, sheet_name: str, required_headers: Iterable[str]) -> list[dict[str, Any]]:
    rows = read_xlsx_sheet(path, sheet_name)
    header_index = next((index for index, (_, values) in enumerate(rows) if any(display_text(value) for value in values)), None)
    if header_index is None:
        fail(f"工作表“{sheet_name}”没有表头")
    header_row_number, header_values = rows[header_index]
    headers = [display_text(value) for value in header_values]
    duplicate_headers = {header for header in headers if header and headers.count(header) > 1}
    if duplicate_headers:
        fail(f"工作表“{sheet_name}”存在重复表头：{'、'.join(sorted(duplicate_headers))}")
    missing = [header for header in required_headers if header not in headers]
    if missing:
        fail(f"工作表“{sheet_name}”缺少必需表头：{'、'.join(missing)}")
    records: list[dict[str, Any]] = []
    for row_number, values in rows[header_index + 1 :]:
        fields = {headers[index]: values[index] if index < len(values) else None for index in range(len(headers)) if headers[index]}
        if any(value is not None and display_text(value) for value in fields.values()):
            records.append({"row_number": row_number, "fields": fields, "header_row_number": header_row_number})
    return records


def table_from_any_sheet(path: Path, required_headers: Iterable[str]) -> tuple[str, list[dict[str, Any]]]:
    try:
        with zipfile.ZipFile(path) as archive:
            sheets = list(xlsx_sheet_paths(archive))
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"无法读取 Excel {path.name}：{exc}")
    errors: list[str] = []
    for name in sheets:
        try:
            return name, table_from_sheet(path, name, required_headers)
        except RecommendationError as exc:
            errors.append(str(exc))
    fail(f"Excel {path.name} 没有包含必需表头的工作表：{'；'.join(errors)}")


def resolve_manifest_path(project_root: Path, raw: Any, label: str, required: bool) -> Path | None:
    if not raw:
        if required:
            fail(f"01_input_manifest.json 缺少 {label}")
        return None
    candidate = Path(str(raw)).expanduser()
    path = candidate if candidate.is_absolute() else project_root / candidate
    if not path.is_file():
        if required:
            fail(f"{label} 指向的文件不存在：{path}")
        return None
    return path


def known_brand(value: Any) -> bool:
    return normalize_text(value) not in UNKNOWN_BRANDS


def valid_sales(item: dict[str, Any]) -> float | None:
    value = item.get("monthly_sales")
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None


def source_listing(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "asin": item["asin"],
        "title": item.get("title"),
        "brand": item.get("brand"),
        "price": item.get("price"),
        "monthly_sales": item.get("monthly_sales"),
        "parent_asin": item.get("parent_asin"),
        "product_url": item.get("product_url"),
        "month": item.get("month"),
        "launch_days": item.get("launch_days"),
        "review_count": item.get("review_count"),
        "rating": item.get("rating"),
    }


def load_project(project_root: Path) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    manifest_path = root / "project_manifest.json"
    manifest = load_json(manifest_path, "project_manifest.json")
    if not isinstance(manifest, dict):
        fail("project_manifest.json 必须是对象")
    opportunity_dir = root / "market_opportunity"
    research_dir = root / "market_research"
    listing_path = research_dir / "cleaned_30d_listings.json"
    tags_path = opportunity_dir / "agent_listing_tags.json"
    analysis_path = opportunity_dir / "07_opportunity_analysis.json"
    input_manifest_path = research_dir / "01_input_manifest.json"
    listings_data = load_json(listing_path, "cleaned_30d_listings.json")
    tags_data = load_json(tags_path, "agent_listing_tags.json")
    analysis_data = load_json(analysis_path, "07_opportunity_analysis.json")
    input_manifest = load_json(input_manifest_path, "01_input_manifest.json")
    if not isinstance(listings_data, dict) or not isinstance(listings_data.get("rows"), list):
        fail("cleaned_30d_listings.json 缺少 rows 数组")
    if not isinstance(tags_data, dict) or not isinstance(tags_data.get("tags"), list):
        fail("agent_listing_tags.json 缺少 tags 数组")
    if not isinstance(analysis_data, dict):
        fail("07_opportunity_analysis.json 必须是对象")
    if not isinstance(input_manifest, dict):
        fail("01_input_manifest.json 必须是对象")

    listings: dict[str, dict[str, Any]] = {}
    for raw in listings_data["rows"]:
        if not isinstance(raw, dict):
            continue
        asin = normalized_asin(raw.get("asin"))
        if not asin:
            fail("cleaned_30d_listings.json 存在空 ASIN")
        normalized = {
            "asin": asin,
            "title": raw.get("title"),
            "brand": raw.get("brand"),
            "price": parse_number(raw.get("price")),
            "monthly_sales": parse_number(raw.get("monthly_sales")),
            "monthly_revenue": parse_number(raw.get("monthly_revenue")),
            "parent_asin": normalized_asin(raw.get("parent_asin")) or None,
            "product_url": display_text(raw.get("product_url")) or None,
            "month": raw.get("month"),
            "launch_days": parse_number(raw.get("launch_days")),
            "review_count": parse_number(raw.get("review_count")),
            "rating": parse_number(raw.get("rating")),
        }
        if asin in listings and json_canonical(listings[asin]) != json_canonical(normalized):
            fail(f"cleaned_30d_listings.json 中 ASIN {asin} 有冲突记录")
        listings[asin] = normalized

    tag_by_asin: dict[str, dict[str, list[str]]] = {}
    display_by_value: dict[tuple[str, str], set[str]] = defaultdict(set)
    for raw in tags_data["tags"]:
        if not isinstance(raw, dict):
            continue
        asin = normalized_asin(raw.get("asin"))
        values = raw.get("normalized_values")
        display_values = raw.get("display_values")
        if not asin or not isinstance(values, dict):
            fail("agent_listing_tags.json 存在没有 normalized_values 的标签记录")
        normalized_values: dict[str, list[str]] = {}
        for dimension, entries in values.items():
            if not isinstance(entries, list):
                continue
            dimension_name = display_text(dimension)
            normalized_values[dimension_name] = [display_text(value) for value in entries if display_text(value)]
            if isinstance(display_values, dict):
                for index, value in enumerate(normalized_values[dimension_name]):
                    display_entries = display_values.get(dimension, [])
                    if isinstance(display_entries, list) and index < len(display_entries):
                        display_by_value[(dimension_name, normalize_text(value))].add(display_text(display_entries[index]))
        if asin in tag_by_asin and json_canonical(tag_by_asin[asin]) != json_canonical(normalized_values):
            fail(f"agent_listing_tags.json 中 ASIN {asin} 有冲突标签")
        tag_by_asin[asin] = normalized_values
    missing_tags = sorted(set(listings) - set(tag_by_asin))
    if missing_tags:
        fail(f"有 {len(missing_tags)} 个有效商品没有已有标签，例如：{'、'.join(missing_tags[:5])}")
    for asin, listing in listings.items():
        listing["tags"] = tag_by_asin[asin]

    available_values: dict[str, dict[str, str]] = defaultdict(dict)
    for values in tag_by_asin.values():
        for dimension, entries in values.items():
            for entry in entries:
                available_values[dimension][normalize_text(entry)] = entry

    pool = helper_module("niche_candidate_pool")
    value_classes: dict[tuple[str, str], str] = {}
    value_display: dict[tuple[str, str], str] = {}
    display_index: dict[tuple[str, str], str] = {}
    for dimension, values in available_values.items():
        for key, original in values.items():
            displays = sorted(display_by_value.get((dimension, key), set()))
            value_classes[(dimension, original)] = pool.value_class(original, displays, NON_CANDIDATE_VALUES)
            value_display[(dimension, original)] = displays[0] if displays else original
            display_index[(dimension, normalize_text(original))] = original
            for display in displays:
                display_index.setdefault((dimension, normalize_text(display)), original)

    keyword_path = resolve_manifest_path(root, input_manifest.get("keyword_file"), "keyword_file", True)
    project_id = display_text(manifest.get("project_id")) or root.name
    return {
        "root": root,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "opportunity_dir": opportunity_dir,
        "research_dir": research_dir,
        "listing_path": listing_path,
        "tags_path": tags_path,
        "analysis_path": analysis_path,
        "input_manifest_path": input_manifest_path,
        "input_manifest": input_manifest,
        "listings": list(listings.values()),
        "analysis": analysis_data,
        "value_classes": value_classes,
        "value_display": value_display,
        "display_index": display_index,
        "available_values": available_values,
        "display_by_value": display_by_value,
        "keyword_path": keyword_path,
        "project_id": project_id,
        "marketplace": display_text(manifest.get("marketplace")),
    }


def load_poe(path: Path) -> dict[str, Any]:
    records = table_from_sheet(path, "细分市场列表", POE_REQUIRED_FIELDS)
    isolated: list[dict[str, Any]] = []
    identities: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        fields = record["fields"]
        name = display_text(fields.get("细分市场名称"))
        category = display_text(fields.get("细分市场分类1"))
        if not name or not category:
            isolated.append({"row_number": record["row_number"], "reason": "缺少细分市场名称或细分市场分类1", "fields": fields})
            continue
        item = {
            "id": f"poe_row_{record['row_number']}",
            "row_number": record["row_number"],
            "name": name,
            "category1": category,
            "category2": display_text(fields.get("细分市场分类2")) or None,
            "category3": display_text(fields.get("细分市场分类3")) or None,
            "period": display_text(fields.get("最后一次出现期数")) or None,
            "fields": fields,
        }
        identity = (normalize_text(name), normalize_text(category), normalize_text(item["period"]))
        identities[identity].append(item)
    valid: list[dict[str, Any]] = []
    conflicted: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    for identity, items in identities.items():
        items = sorted(items, key=lambda item: item["row_number"])
        exact = len({json_canonical(item["fields"]) for item in items}) == 1
        if len(items) == 1:
            valid.append({**items[0], "source_row_numbers": [items[0]["row_number"]]})
            continue
        duplicate_groups.append(
            {
                "identity": identity,
                "row_numbers": [item["row_number"] for item in items],
                "exact_duplicate": exact,
            }
        )
        if exact:
            valid.append({**items[0], "source_row_numbers": [item["row_number"] for item in items]})
        else:
            conflicted.append(
                {
                    "row_numbers": [item["row_number"] for item in items],
                    "reason": "相同名称、分类和期数的商机记录存在不同字段值，已隔离且不进入当前候选",
                    "records": items,
                }
            )
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": valid,
        "isolated_rows": isolated,
        "conflicted_rows": conflicted,
        "duplicate_groups": duplicate_groups,
        "row_numbers": {item["row_number"] for item in valid},
    }


def deduplicate_keywords(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalize_text(row["fields"].get("关键词"))
        if key:
            groups[key].append(row)
    result, conflicts = {}, []
    for key, group in groups.items():
        signatures = {json_canonical({field: row["fields"].get(field) for field in fields}) for row in group}
        source_rows = sorted(row["row_number"] for row in group)
        first = group[0]
        record = {"keyword": display_text(first["fields"].get("关键词")), "row_number": first["row_number"], "source_row_numbers": source_rows, "fields": first["fields"]}
        if len(signatures) > 1:
            record = {**record, "fields": {"关键词": record["keyword"]}, "exclusion_reason": "同一关键词存在冲突或跨期记录，已隔离"}
            conflicts.append({"key": key, "source_row_numbers": source_rows, "reason": record["exclusion_reason"]})
        result[key] = [record]
    return result, conflicts


def keyword_source(path: Path) -> dict[str, Any]:
    """The project's full keyword table: keyword demand evidence (月搜索量) only, never bids."""
    main_sheet, main_rows = table_from_any_sheet(path, ("关键词", "月搜索量"))
    main_by_key, conflicts = deduplicate_keywords(main_rows, ("月搜索量", "月购买量", "站点", "时间节点", "统计周期", "周期"))
    if not main_by_key:
        fail("完整关键词文件没有有效关键词")
    return {"main_path": path, "main_sheet": main_sheet, "main_by_key": main_by_key, "conversion_by_key": {}, "main_conflicts": conflicts}


CONVERSION_COLUMN_ALIASES = {
    "近90天点击量": ("近90天点击量", "点击量-近90天", "点击量"),
    "近90天购买量": ("近90天购买量", "购买量-近90天", "销量-近90天", "购买量", "销量"),
}


def _conversion_column_mapping(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    headers = set(rows[0]["fields"]) if rows else set()
    mapping = {
        target: next((field for field in names if field in headers), None)
        for target, names in CONVERSION_COLUMN_ALIASES.items()
    }
    return mapping if all(mapping.values()) else None


def _validate_keyword_marketplace(rows: list[dict[str, Any]], marketplace: str, label: str) -> None:
    for row in rows:
        fields = row["fields"]
        for field in ("站点", "marketplace"):
            market = display_text(fields.get(field))
            if market and normalize_text(market) != normalize_text(marketplace):
                fail(f"{label}第{row['row_number']}行站点与项目不一致")


def load_refinement_conversion_file(path: Path, marketplace: str, period: str | None) -> dict[str, Any]:
    """Read one keyword conversion workbook: only keyword, clicks and purchases are used.

    Bid columns such as ``最高出价``/``最低出价``/``建议出价`` in this workbook are
    deliberately ignored; suggested bids come only from the SellerSprite
    reverse-lookup workbook (user decision 2026-10-03).
    """
    with zipfile.ZipFile(path) as archive:
        sheets = list(xlsx_sheet_paths(archive))
    chosen = None
    for name in sheets:
        try:
            rows = table_from_sheet(path, name, ("关键词",))
        except RecommendationError:
            continue
        mapping = _conversion_column_mapping(rows)
        if mapping:
            chosen = name, rows, mapping
            break
    if chosen is None:
        fail("新关键词表必须包含关键词、点击量和购买量（同一近90天窗口）")
    sheet, rows, mapping = chosen
    _validate_keyword_marketplace(rows, marketplace, "关键词转化表")
    declared = display_text(period)
    periods = set()
    for row in rows:
        f = row["fields"]
        for field in ("时间节点", "统计周期", "周期"):
            if display_text(f.get(field)):
                periods.add(display_text(f[field]))
    if len(periods) > 1 or (declared and periods and periods != {declared}):
        fail("关键词新表存在不同统计窗口，不能跨期相加；请提供统一周期表")
    uses_explicit_90_day_headers = any("近90天" in source for source in mapping.values())
    window = declared or next(iter(periods), "") or ("近90天" if uses_explicit_90_day_headers else "")
    if not window:
        fail("关键词新表缺少统计周期；请通过 --conversion-period 明确统一近90天窗口")
    for row in rows:
        original = row["fields"]
        rate = original.get("点击转化率")
        rate_ratio = parse_number(rate)
        if isinstance(rate, str) and "%" in rate:
            rate_ratio = None if rate_ratio is None else rate_ratio / 100
        if "点击转化率 (%)" in original:
            points = percentage_points(original["点击转化率 (%)"])
            rate_ratio = None if points is None else points / 100
        row["fields"] = {**original, **{target: original[source] for target, source in mapping.items()},
                         "统计周期": window, "reported_click_conversion_rate": rate_ratio}
    return {
        "path": str(path), "sha256": sha256_file(path), "sheet": sheet, "period": window,
        "rows": rows, "keyword_keys": {normalize_text(row["fields"].get("关键词")) for row in rows if normalize_text(row["fields"].get("关键词"))},
        "column_mapping": mapping,
    }


def load_sellersprite_keyword_file(path: Path, marketplace: str, require_association: bool = True) -> dict[str, Any]:
    """Read SellerSprite keyword/PPC data and isolate ambiguous PPC values."""
    sheet, rows = table_from_any_sheet(path, ("关键词", "PPC竞价"))
    _validate_keyword_marketplace(rows, marketplace, "卖家精灵关键词表")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalize_text(row["fields"].get("关键词"))
        if key:
            grouped[key].append(row)
    by_key: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for key, source_rows in grouped.items():
        valid_bids = sorted({bid for bid in (parse_number(row["fields"].get("PPC竞价")) for row in source_rows) if bid is not None and bid > 0})
        record = {
            "keyword": display_text(source_rows[0]["fields"].get("关键词")),
            "source_row_numbers": [row["row_number"] for row in source_rows],
            "ppc_bid": valid_bids[0] if len(valid_bids) == 1 else None,
            "exclusion_reason": None,
        }
        if not valid_bids:
            record["exclusion_reason"] = "missing_or_nonpositive_sellersprite_bid"
        elif len(valid_bids) > 1:
            record["exclusion_reason"] = "conflicting_sellersprite_bid"
            conflicts.append({"key": key, "source_row_numbers": record["source_row_numbers"], "reason": record["exclusion_reason"]})
        by_key[key] = record
    if not by_key:
        fail("卖家精灵关键词表没有有效关键词")
    if not require_association:
        return {
            "path": str(path), "sha256": sha256_file(path), "sheet": sheet,
            "rows": rows, "keyword_keys": set(by_key), "by_key": by_key, "conflicts": conflicts,
            "source_asins": set(), "traffic_top90_keyword_keys": set(by_key),
            "traffic_top90_keyword_count": len(by_key), "traffic_top90_cumulative_share": None,
        }
    try:
        with zipfile.ZipFile(path) as archive:
            asin_sheet = next((name for name in xlsx_sheet_paths(archive) if normalize_text(name) == "asin"), None)
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"无法读取 Excel {path.name}：{exc}")
    if not asin_sheet:
        fail(f"卖家精灵关键词表 {path.name} 缺少 Asin 工作表")
    asin_rows = table_from_sheet(path, asin_sheet, ("ASIN",))
    source_asins = {normalized_asin(row["fields"].get("ASIN")) for row in asin_rows if normalized_asin(row["fields"].get("ASIN"))}
    # The exact set is checked against each frozen Top20 during association;
    # a market may legitimately freeze fewer than 20 ASINs.
    if not 1 <= len(source_asins) <= 20:
        fail(f"卖家精灵关键词表 {path.name} 的 Asin 工作表必须包含 1—20 个不同 ASIN（应与对应市场冻结 Top20 完全一致）")

    def traffic_share(value: Any) -> float | None:
        number = parse_number(value)
        if number is None or number < 0:
            return None
        text = display_text(value)
        if "%" in text or number > 1:
            number /= 100
        return number if number <= 1 else None

    traffic_rows = []
    for row in rows:
        key = normalize_text(row["fields"].get("关键词"))
        share = traffic_share(row["fields"].get("流量占比"))
        if key and share is not None:
            traffic_rows.append((key, share, row["row_number"]))
    traffic_rows.sort(key=lambda item: (-item[1], item[2], item[0]))
    cumulative_share = 0.0
    top90_keyword_keys: set[str] = set()
    for key, share, _ in traffic_rows:
        if cumulative_share >= .9:
            break
        top90_keyword_keys.add(key)
        cumulative_share += share
    if cumulative_share < .9:
        fail(f"卖家精灵关键词表 {path.name} 的流量占比无法覆盖累计前 90%")
    return {
        "path": str(path), "sha256": sha256_file(path), "sheet": sheet,
        "rows": rows, "keyword_keys": set(by_key), "by_key": by_key, "conflicts": conflicts,
        "source_asins": source_asins,
        "traffic_top90_keyword_keys": top90_keyword_keys,
        "traffic_top90_keyword_count": len(top90_keyword_keys),
        "traffic_top90_cumulative_share": cumulative_share,
    }


def _unique_keyword_assignment(left: list[dict[str, Any]], right: list[dict[str, Any]], score_fn: Any, label: str) -> list[tuple[int, int, int]]:
    """Return the unique maximum one-to-one exact-keyword assignment."""
    if len(left) != len(right) or not left:
        fail(f"{label}需要数量相同且非空的两组文件")
    scored: list[tuple[int, tuple[int, ...], list[int]]] = []
    for permutation in itertools.permutations(range(len(right))):
        scores = [score_fn(left[index], right[target]) for index, target in enumerate(permutation)]
        scored.append((sum(scores), permutation, scores))
    best_total = max(item[0] for item in scored)
    best = [item for item in scored if item[0] == best_total]
    if len(best) != 1:
        fail(f"{label}存在并列的关键词重叠匹配，无法自动识别对应关系")
    _, permutation, scores = best[0]
    if any(score <= 0 for score in scores):
        fail(f"{label}缺少可验证的关键词重叠，无法自动识别对应关系")
    return [(index, target, scores[index]) for index, target in enumerate(permutation)]


def refinement_file_requirement(market_count: int) -> str:
    return (f"进一步分析需要 {2 * market_count} 个不同的 Excel：{market_count} 个细分市场关键词转化表和 "
            f"{market_count} 个卖家精灵关键词表（每个冻结市场各 1 份，顺序不限）")


def classify_refinement_keyword_files(paths: list[Path], marketplace: str, period: str | None, market_count: int = 3) -> dict[str, Any]:
    """Classify one conversion and one SellerSprite workbook per frozen market.

    Conversion-to-SellerSprite pairing is based solely on overlap with each
    SellerSprite table's cumulative-traffic-top-90% keyword set.  This is input
    association, not relevance classification.
    """
    if market_count < 1:
        fail("没有可进一步分析的冻结市场")
    if len(paths) != 2 * market_count or len({path.resolve() for path in paths}) != len(paths):
        fail(refinement_file_requirement(market_count) + f"；本次收到 {len(paths)} 个（含重复时按不同文件计）")
    conversions: list[dict[str, Any]] = []
    sellers: list[dict[str, Any]] = []
    for path in paths:
        try:
            with zipfile.ZipFile(path) as archive:
                has_asin_sheet = any(normalize_text(name) == "asin" for name in xlsx_sheet_paths(archive))
        except (OSError, zipfile.BadZipFile) as exc:
            fail(f"无法读取 Excel {path.name}：{exc}")
        if has_asin_sheet:
            # SellerSprite reverse-lookup export: the only accepted source of suggested bids (PPC竞价).
            sellers.append(load_sellersprite_keyword_file(path, marketplace))
            continue
        try:
            _, rows = table_from_any_sheet(path, ("关键词",))
        except RecommendationError:
            fail(f"无法识别关键词文件类型：{path.name}")
        if _conversion_column_mapping(rows) is None:
            fail(f"{path.name} 既不是卖家精灵关键词反查表（缺少 Asin 工作表），也不是关键词转化表（缺少点击量或购买量列）")
        conversions.append(load_refinement_conversion_file(path, marketplace, period))
    if len(conversions) != market_count or len(sellers) != market_count:
        fail(f"识别出 {len(conversions)} 个关键词转化表和 {len(sellers)} 个卖家精灵关键词表；" + refinement_file_requirement(market_count))
    pairings = []
    for conversion_index, seller_index, overlap in _unique_keyword_assignment(
        conversions,
        sellers,
        lambda conversion, seller: len(conversion["keyword_keys"] & seller["traffic_top90_keyword_keys"]),
        "关键词转化表与卖家精灵关键词表",
    ):
        conversion = conversions[conversion_index]
        overlap_rate = overlap / len(conversion["keyword_keys"]) if conversion["keyword_keys"] else 0
        if overlap_rate < .8:
            fail(f"{Path(conversion['path']).name} 与其卖家精灵累计流量前90%关键词重叠不足80%，无法可靠关联")
        pairings.append({"conversion": conversion, "seller": sellers[seller_index], "keyword_overlap_count": overlap, "keyword_overlap_rate": overlap_rate})
    periods = {item["period"] for item in conversions}
    if len(periods) != 1:
        fail("各细分市场关键词转化表的统计周期不一致，不能合并为同一轮分析")
    return {
        "mode": "six_file_full_keyword_conversion",
        "period": next(iter(periods)),
        "conversion_files": conversions,
        "seller_sprite_files": sellers,
        "pairings": pairings,
        "file_classification": {
            "conversion_paths": [item["path"] for item in conversions],
            "seller_sprite_paths": [item["path"] for item in sellers],
            "pairing_basis": "exact_normalized_keyword_overlap_with_sellersprite_traffic_top90",
        },
    }


def refinement_input_summary(inputs: dict[str, Any]) -> dict[str, Any]:
    """Keep receipts auditable without embedding every uploaded keyword row."""
    return {
        "mode": inputs.get("mode"),
        "period": inputs.get("period"),
        "file_classification": inputs.get("file_classification"),
        "conversion_files": [
            {key: item.get(key) for key in ("path", "sha256", "sheet", "period", "column_mapping")}
            for item in inputs.get("conversion_files", [])
        ],
        "seller_sprite_files": [
            {key: item.get(key) for key in ("path", "sha256", "sheet")}
            for item in inputs.get("seller_sprite_files", [])
        ],
        "market_mappings": inputs.get("market_mappings", []),
    }


def generate_combo_cores(project: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Positive cores of the CLI formal combinations (rule v10)."""
    pool = helper_module("niche_candidate_pool")
    analysis = project.get("analysis") or {}
    formal = analysis.get("formal_opportunities") if isinstance(analysis, dict) else None
    if not isinstance(formal, list) or not formal:
        return [], []
    return pool.combo_cores(
        [item for item in formal if isinstance(item, dict)],
        project["available_values"],
        lambda dimension, display: project["display_index"].get((display_text(dimension), normalize_text(display))),
        project["value_classes"],
        project["value_display"],
    )


def combo_expression(core: dict[str, Any]) -> dict[str, Any]:
    return {"any_of": [{"all_of": [{"dimension": dimension, "values": list(values)} for dimension, values in core["key"]]}]}


def expression_core_key(expression: dict[str, Any]) -> tuple | None:
    branches = expression.get("any_of") or []
    if len(branches) != 1:
        return None
    pool = helper_module("niche_candidate_pool")
    return pool.core_key((condition["dimension"], condition["values"]) for condition in branches[0]["all_of"])


def public_combo(core: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": core["id"], "name": core["name"], "tag_expression": combo_expression(core),
        "cli_best_rank": core["best_rank"], "cli_opportunity_score": core["opportunity_score"],
        "merged_cli_combinations": [variant["features"] for variant in core["variants"]],
        "entry_hint": core["entry_hint"],
    }


def candidate_workspace(project: dict[str, Any], poe: dict[str, Any]) -> dict[str, Any]:
    combos, skipped = generate_combo_cores(project)
    dimensions: list[dict[str, Any]] = []
    for dimension in sorted(project["available_values"], key=normalize_text):
        values = project["available_values"][dimension]
        dimensions.append(
            {
                "dimension": dimension,
                "values": [
                    {
                        "normalized_value": original,
                        "display_values": sorted(project["display_by_value"].get((dimension, key), {original})),
                    }
                    for key, original in sorted(values.items())
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "project_id": project["project_id"],
        "marketplace": project["marketplace"],
        "poe_input": {"path": poe["path"], "sha256": poe["sha256"]},
        "poe_rows": poe["rows"],
        "isolated_poe_rows": poe["isolated_rows"],
        "conflicted_poe_rows": poe["conflicted_rows"],
        "poe_duplicate_groups": poe["duplicate_groups"],
        "poe_row_disposition_contract": {
            "required_for_each_row_number": True,
            "allowed_values": sorted(POE_DISPOSITIONS),
            "direct_need_requirement": "必须关联至少一个候选；其余类别不得关联候选。",
        },
        "available_tag_dimensions": dimensions,
        "candidate_definition_contract": "references/niche_recommendation_contract.md#2-候选池与候选定义",
        "combo_candidates": [public_combo(core) for core in combos],
        "skipped_cli_combinations": skipped,
        "combo_review_contract": "每个与商机表候选条件不同的组合都要在 combo_reviews 中审核一次：decision 为 keep 或 drop（drop 必须写原因）；"
                                 "keep 时用 keyword_assignments 从完整关键词表归属 direct 词，没有有搜索量的 direct 词只能作候补。",
        "combo_review_template": [{"id": core["id"], "name": core["name"], "decision": "keep", "reason": "", "keyword_assignments": []} for core in combos],
        "candidates": [],
    }


def validate_expression(raw: Any, project: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("any_of"), list) or not raw["any_of"]:
        fail(f"候选 {candidate_id} 的 tag_expression.any_of 必须是非空数组")
    branches: list[dict[str, Any]] = []
    for branch_index, branch in enumerate(raw["any_of"], start=1):
        conditions = branch.get("all_of") if isinstance(branch, dict) else None
        if not isinstance(conditions, list) or not 1 <= len(conditions) <= 3:
            fail(f"候选 {candidate_id} 的第 {branch_index} 个 OR 分支必须有 1—3 个 AND 条件")
        seen_dimensions: set[str] = set()
        normalized_conditions: list[dict[str, Any]] = []
        for condition in conditions:
            if not isinstance(condition, dict):
                fail(f"候选 {candidate_id} 的标签条件必须是对象")
            dimension = display_text(condition.get("dimension"))
            values = condition.get("values")
            if dimension in seen_dimensions:
                fail(f"候选 {candidate_id} 的同一 OR 分支不能重复维度“{dimension}”")
            seen_dimensions.add(dimension)
            if dimension not in project["available_values"]:
                fail(f"候选 {candidate_id} 使用了不存在的标签维度“{dimension}”")
            if not isinstance(values, list) or not values:
                fail(f"候选 {candidate_id} 的维度“{dimension}”缺少 values")
            selected: list[str] = []
            for value in values:
                key = normalize_text(value)
                if key in UNKNOWN_VALUES or key in NON_CANDIDATE_VALUES:
                    fail(f"候选 {candidate_id} 不能把“{value}”作为可推荐标签")
                if key not in project["available_values"][dimension]:
                    fail(f"候选 {candidate_id} 使用了不存在的标签值“{dimension}={value}”")
                selected.append(project["available_values"][dimension][key])
            normalized_conditions.append({"dimension": dimension, "values": sorted(set(selected), key=normalize_text)})
        branches.append({"all_of": normalized_conditions})
    return {"any_of": branches}


def validate_poe_dispositions(raw: Any, poe: dict[str, Any], candidate_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        fail("候选定义文件缺少 poe_row_dispositions 数组")
    by_row: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            fail("poe_row_dispositions 只能包含对象")
        row_number = item.get("row_number")
        disposition = display_text(item.get("disposition"))
        reason = display_text(item.get("reason"))
        candidate_refs = item.get("candidate_ids", [])
        if not isinstance(row_number, int) or row_number not in poe["row_numbers"]:
            fail(f"poe_row_dispositions 引用了不存在或已隔离的商机表行：{row_number}")
        if row_number in by_row:
            fail(f"poe_row_dispositions 重复处理商机表行：{row_number}")
        if disposition not in POE_DISPOSITIONS:
            fail(f"商机表行 {row_number} 的 disposition 不合法：{disposition}")
        if not reason:
            fail(f"商机表行 {row_number} 缺少处理原因")
        if not isinstance(candidate_refs, list) or any(not isinstance(value, str) or not value.strip() for value in candidate_refs):
            fail(f"商机表行 {row_number} 的 candidate_ids 必须是字符串数组")
        candidate_refs = [display_text(value) for value in candidate_refs]
        if len(candidate_refs) != len(set(candidate_refs)) or any(value not in candidate_ids for value in candidate_refs):
            fail(f"商机表行 {row_number} 的 candidate_ids 有重复或未知候选")
        if disposition == "direct_need" and not candidate_refs:
            fail(f"本品类直接需求商机表行 {row_number} 必须关联至少一个候选")
        if disposition != "direct_need" and candidate_refs:
            fail(f"商机表行 {row_number} 不是本品类直接需求，不能关联候选")
        by_row[row_number] = {
            "row_number": row_number,
            "disposition": disposition,
            "reason": reason,
            "candidate_ids": candidate_refs,
        }
    expected_rows = set(poe["row_numbers"])
    if set(by_row) != expected_rows:
        missing = sorted(expected_rows - set(by_row))
        extra = sorted(set(by_row) - expected_rows)
        details = []
        if missing:
            details.append("未处理行：" + "、".join(map(str, missing)))
        if extra:
            details.append("无效行：" + "、".join(map(str, extra)))
        fail("poe_row_dispositions 必须覆盖每个可分析商机记录（" + "；".join(details) + "）")
    return [by_row[row_number] for row_number in sorted(by_row)]


def validate_keyword_assignments(assignments: Any, keywords: dict[str, Any], candidate_id: str, collect: list[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(assignments, list):
        fail(f"候选 {candidate_id} 的 keyword_assignments 必须是数组")
    assigned_types: dict[str, str] = {}
    normalized_assignments: list[dict[str, Any]] = []
    for assignment in assignments:
        item = guarded(collect, _validate_keyword_assignment, assignment, keywords, candidate_id, assigned_types)
        if item is not None:
            normalized_assignments.append(item)
    return normalized_assignments


def _validate_keyword_assignment(assignment: Any, keywords: dict[str, Any], candidate_id: str, assigned_types: dict[str, str]) -> dict[str, Any]:
    if not isinstance(assignment, dict):
        fail(f"候选 {candidate_id} 的关键词归属必须是对象")
    keyword = display_text(assignment.get("keyword"))
    key = normalize_text(keyword)
    assignment_type = display_text(assignment.get("type"))
    if assignment_type not in {"direct", "extended", "ambiguous"}:
        fail(f"候选 {candidate_id} 的关键词 {keyword} 归属类型不合法")
    if not key or key not in keywords["main_by_key"]:
        fail(f"候选 {candidate_id} 的关键词不在完整关键词来源中：{keyword}")
    previous = assigned_types.get(key)
    if previous:
        fail(f"候选 {candidate_id} 的关键词 {keyword} 重复归属（{previous}、{assignment_type}）")
    assigned_types[key] = assignment_type
    return {"keyword": keyword, "key": key, "type": assignment_type, "reason": display_text(assignment.get("reason"))}


def combo_candidates(definitions: dict[str, Any], project: dict[str, Any], keywords: dict[str, Any],
                     poe_candidates: list[dict[str, Any]], collect: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn reviewed CLI combination cores into candidates; cores equal to a POE candidate are merged."""
    cores, skipped = generate_combo_cores(project)
    poe_by_core = {key: candidate for candidate in poe_candidates if (key := expression_core_key(candidate["tag_expression"])) is not None}
    merged, pending = [], []
    for core in cores:
        candidate = poe_by_core.get(core["key"])
        if candidate is not None:
            candidate["source"] = "poe+combo"
            candidate["entry_hint"] = core["entry_hint"]
            candidate["combo_evidence"] = public_combo(core)
            merged.append({"combo_id": core["id"], "candidate_id": candidate["id"], "name": core["name"]})
        else:
            pending.append(core)
    reviews = definitions.get("combo_reviews", [])
    if not isinstance(reviews, list):
        fail("combo_reviews 必须是数组")
    by_id: dict[str, dict[str, Any]] = {}
    merged_ids = {item["combo_id"] for item in merged}
    pending_ids = {core["id"] for core in pending}
    def register(review: Any) -> None:
        if not isinstance(review, dict):
            fail("combo_reviews 只能包含对象")
        review_id = display_text(review.get("id"))
        if review_id in merged_ids:
            return
        if review_id not in pending_ids:
            fail(f"combo_reviews 引用了不存在的多维组合：{review_id or '空'}（请以 prepare 生成的 combo_review_template 为准）")
        if review_id in by_id:
            fail(f"combo_reviews 重复审核组合：{review_id}")
        by_id[review_id] = review

    for review in reviews:
        guarded(collect, register, review)
    missing = [f"{core['id']}（{core['name']}）" for core in pending if core["id"] not in by_id]
    if missing:
        guarded(collect, fail, "以下多维组合候选尚未审核，请按 workspace 的 combo_review_template 补齐 combo_reviews：" + "、".join(missing))
    candidates, dropped = [], []
    for core in pending:
        if core["id"] not in by_id:
            continue
        built = guarded(collect, _combo_candidate, core, by_id[core["id"]], keywords, dropped, collect)
        if built is not None:
            candidates.append(built)
    summary = {"generated_combo_count": len(cores), "merged_with_poe": merged, "dropped_combos": dropped,
               "skipped_cli_combinations": skipped, "combo_candidate_count": len(candidates)}
    return candidates, summary


def _combo_candidate(core: dict[str, Any], review: dict[str, Any], keywords: dict[str, Any], dropped: list[dict[str, Any]],
                     collect: list[str] | None) -> dict[str, Any] | None:
    decision = display_text(review.get("decision"))
    reason = display_text(review.get("reason"))
    if decision not in {"keep", "drop"}:
        fail(f"多维组合 {core['id']} 的 decision 只能是 keep 或 drop")
    if decision == "drop":
        if not reason:
            fail(f"多维组合 {core['id']} 被剔除时必须写原因")
        dropped.append({"combo_id": core["id"], "name": core["name"], "reason": reason})
        return None
    assignments = validate_keyword_assignments(review.get("keyword_assignments", []), keywords, core["id"], collect)
    name = display_text(review.get("name")) or core["name"]
    return {
        "id": core["id"], "name": name, "definition": f"多维打标组合：{core['name']}",
        "task": display_text(review.get("task")) or "由多维打标组合识别的细分需求",
        "selection_constraint_reason": reason or "组合内各标签条件同时满足",
        "demand_status": "established" if any(item["type"] == "direct" for item in assignments) else "pending",
        "dedupe_group": core["id"], "exclusive_with": [], "tag_expression": combo_expression(core),
        "poe_matches": [], "keyword_assignments": assignments, "source": "combo",
        "entry_hint": core["entry_hint"], "combo_evidence": public_combo(core),
        "primary_poe_row_number": None, "primary_poe_relationship": None, "primary_poe_selection": "多维组合候选，没有商机表行",
    }


def _exclusive_entries(raw: Any, candidate_id: str) -> list[dict[str, str]]:
    """exclusive_with items: a candidate id, or {"id": ..., "reason": ...} stating the evidence."""
    if not isinstance(raw, list):
        fail(f"候选 {candidate_id} 的 exclusive_with 必须是数组")
    entries = []
    for value in raw:
        other, reason = (display_text(value.get("id")), display_text(value.get("reason"))) if isinstance(value, dict) else (display_text(value), "")
        if not other:
            fail(f"候选 {candidate_id} 的 exclusive_with 含空引用")
        entries.append({"id": other, "reason": reason})
    return entries


def _validate_candidate(raw: Any, project: dict[str, Any], poe: dict[str, Any], keywords: dict[str, Any],
                        ids: set[str], groups: set[str], collect: list[str] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        fail("candidates 只能包含对象")
    candidate_id = display_text(raw.get("id"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", candidate_id):
        fail(f"候选 id 不合法：{candidate_id or '空'}")
    if candidate_id in ids:
        fail(f"候选 id 重复：{candidate_id}")
    ids.add(candidate_id)
    for field in ("name", "definition", "task", "selection_constraint_reason", "dedupe_group"):
        if not display_text(raw.get(field)):
            fail(f"候选 {candidate_id} 缺少 {field}")
    group = display_text(raw.get("dedupe_group"))
    if group in groups:
        fail(f"dedupe_group 必须唯一：{group}。替代方案应合并到同一候选的 OR 分支。")
    groups.add(group)
    demand_status = display_text(raw.get("demand_status"))
    if demand_status not in {"established", "pending"}:
        fail(f"候选 {candidate_id} 的 demand_status 只能是 established 或 pending")
    expression = validate_expression(raw.get("tag_expression"), project, candidate_id)
    poe_matches = raw.get("poe_matches", [])
    if not isinstance(poe_matches, list):
        fail(f"候选 {candidate_id} 的 poe_matches 必须是数组")
    normalized_poe: list[dict[str, Any]] = []
    for match in poe_matches:
        if not isinstance(match, dict):
            fail(f"候选 {candidate_id} 的 poe_matches 必须包含对象")
        relationship = display_text(match.get("relationship"))
        if relationship not in {"exact", "partial", "none"}:
            fail(f"候选 {candidate_id} 的商机对应 relationship 不合法")
        row_number = match.get("row_number")
        if relationship != "none":
            if not isinstance(row_number, int) or row_number not in poe["row_numbers"]:
                fail(f"候选 {candidate_id} 引用了不存在的商机表行：{row_number}")
        normalized_poe.append({"row_number": row_number if relationship != "none" else None, "relationship": relationship,
                               "reason": display_text(match.get("reason"))})
    normalized_assignments = validate_keyword_assignments(raw.get("keyword_assignments", []), keywords, candidate_id, collect)
    has_direct = any(item["type"] == "direct" for item in normalized_assignments)
    has_poe = any(item["relationship"] in {"exact", "partial"} for item in normalized_poe)
    if demand_status == "established" and not (has_direct or has_poe):
        fail(f"候选 {candidate_id} 标为 established，但没有直接需求词或有效商机对应")
    exclusive = _exclusive_entries(raw.get("exclusive_with", []), candidate_id)
    return {
        "id": candidate_id,
        "name": display_text(raw["name"]),
        "definition": display_text(raw["definition"]),
        "task": display_text(raw["task"]),
        "selection_constraint_reason": display_text(raw["selection_constraint_reason"]),
        "demand_status": demand_status,
        "dedupe_group": group,
        "exclusive_with": [entry["id"] for entry in exclusive],
        "exclusive_reasons": {entry["id"]: entry["reason"] for entry in exclusive if entry["reason"]},
        "tag_expression": expression,
        "poe_matches": normalized_poe,
        "requested_primary_poe_row_number": raw.get("primary_poe_row_number"),
        "keyword_assignments": normalized_assignments,
    }


def _check_exclusive(candidate: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    for other in candidate["exclusive_with"]:
        if other not in by_id or other == candidate["id"]:
            fail(f"候选 {candidate['id']} 的 exclusive_with 引用无效：{other}")
        if candidate["id"] not in by_id[other]["exclusive_with"]:
            fail(f"exclusive_with 必须对称：{candidate['id']} 与 {other}")


def _assign_primary_row(candidate: dict[str, Any], poe: dict[str, Any], direct_rows: dict[int, set[str]]) -> None:
    for match in candidate["poe_matches"]:
        if match["relationship"] in {"exact", "partial"}:
            allowed_candidates = direct_rows.get(match["row_number"])
            if allowed_candidates is None or candidate["id"] not in allowed_candidates:
                fail(f"候选 {candidate['id']} 只能引用已关联到该候选的本品类直接需求商机表行")
    matched_rows = {match["row_number"]: match["relationship"] for match in candidate["poe_matches"] if match["relationship"] == "exact"}
    requested_primary = candidate.pop("requested_primary_poe_row_number", None)
    if requested_primary is not None:
        if not isinstance(requested_primary, int):
            fail(f"候选 {candidate['id']} 的 primary_poe_row_number 必须是整数")
        primary_row_number = requested_primary if requested_primary in matched_rows else None
        primary_selection = "明确指定的准确商机行" if primary_row_number else "指定记录不是 exact，不能作为准确商机行"
    elif matched_rows:
        def primary_key(row_number: int) -> tuple[Any, ...]:
            row = next(row for row in poe["rows"] if row["row_number"] == row_number)
            period_number = parse_number(re.sub(r"[^0-9.]", "", display_text(row.get("period")))) or 0.0
            search_volume = parse_number(row["fields"].get("搜索量-近90天")) or 0.0
            return (-period_number, -search_volume, row_number)

        primary_row_number = min(matched_rows, key=primary_key)
        primary_selection = "按最后出现期数、近90天搜索量、行号确定"
    else:
        primary_row_number = None
        primary_selection = "没有 exact 商机对应行"
    candidate["primary_poe_row_number"] = primary_row_number
    candidate["primary_poe_relationship"] = matched_rows.get(primary_row_number) if primary_row_number else None
    candidate["primary_poe_selection"] = primary_selection


def validate_definitions(definitions: Any, project: dict[str, Any], poe: dict[str, Any], keywords: dict[str, Any],
                         collect: list[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Validate the Agent's candidate definitions.

    Without ``collect`` the first error stops the run (shortlist/refine).  With
    a list (``validate`` command) every independent item is checked and all
    errors are recorded, so the Agent can fix them in one pass.
    """
    if not isinstance(definitions, dict):
        fail("候选定义文件必须是 JSON 对象")
    project_id = display_text(definitions.get("project_id"))
    if project_id and project_id != project["project_id"]:
        guarded(collect, fail, f"候选定义的 project_id 为 {project_id}，与当前项目 {project['project_id']} 不一致")
    raw_candidates = definitions.get("candidates")
    if not isinstance(raw_candidates, list):
        guarded(collect, fail, "候选定义文件缺少 candidates 数组")
        raw_candidates = []
    ids: set[str] = set()
    groups: set[str] = set()
    candidates = [item for item in (guarded(collect, _validate_candidate, raw, project, poe, keywords, ids, groups, collect)
                                    for raw in raw_candidates) if item is not None]
    by_id = {candidate["id"]: candidate for candidate in candidates}
    for candidate in candidates:
        guarded(collect, _check_exclusive, candidate, by_id)
    dispositions = guarded(collect, validate_poe_dispositions, definitions.get("poe_row_dispositions"), poe, set(ids)) or []
    direct_rows = {d["row_number"]: set(d["candidate_ids"]) for d in dispositions if d["disposition"] == "direct_need"}
    for candidate in candidates:
        if guarded(collect, _assign_primary_row, candidate, poe, direct_rows) is None and "primary_poe_selection" not in candidate:
            candidate.update(primary_poe_row_number=None, primary_poe_relationship=None, primary_poe_selection="校验未通过")
            candidate.pop("requested_primary_poe_row_number", None)
        candidate.setdefault("source", "poe")
        candidate.setdefault("entry_hint", None)
        candidate.setdefault("combo_evidence", None)
    combos, pool_summary = combo_candidates(definitions, project, keywords, candidates, collect)
    clashes = {candidate["id"] for candidate in candidates} & {combo["id"] for combo in combos}
    if clashes:
        guarded(collect, fail, "候选 id 与多维组合 id 冲突：" + "、".join(sorted(clashes)))
    pool_summary["poe_candidate_count"] = len(candidates)
    return candidates + combos, dispositions, pool_summary


def match_expression(tags: dict[str, list[str]], expression: dict[str, Any]) -> tuple[str, list[str]]:
    unresolved_dimensions: set[str] = set()
    for branch in expression["any_of"]:
        branch_unknown: set[str] = set()
        branch_false = False
        for condition in branch["all_of"]:
            actual = {normalize_text(value) for value in tags.get(condition["dimension"], [])}
            expected = {normalize_text(value) for value in condition["values"]}
            if (actual - NON_CANDIDATE_VALUES - UNKNOWN_VALUES) & expected:
                continue
            if actual & NON_CANDIDATE_VALUES:
                branch_false = True
            elif not actual or UNKNOWN_VALUES & actual:
                branch_unknown.add(condition["dimension"])
            else:
                branch_false = True
        if not branch_false:
            if not branch_unknown:
                return "matched", []
            unresolved_dimensions.update(branch_unknown)
    return ("unresolved", sorted(unresolved_dimensions)) if unresolved_dimensions else ("excluded", [])


def match_members(project: dict[str, Any], candidate: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for listing in project["listings"]:
        status, dimensions = match_expression(listing["tags"], candidate["tag_expression"])
        if status == "matched":
            matched.append(listing)
        elif status == "unresolved":
            unresolved.append({"asin": listing["asin"], "unresolved_dimensions": dimensions})
    return matched, unresolved


def median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def sort_sales(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (-(valid_sales(item) or 0.0), item["asin"]))


def parent_representatives(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    representatives: dict[str, dict[str, Any]] = {}
    for item in sort_sales(items):
        parent = item.get("parent_asin")
        if parent and parent not in representatives:
            representatives[parent] = item
    return list(representatives.values())


def concentration(values: list[float], top_count: int) -> float | None:
    total = sum(values)
    return sum(sorted(values, reverse=True)[:top_count]) / total if total > 0 else None


def product_metrics(members: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [item for item in members if valid_sales(item) is not None]
    valid_values = [valid_sales(item) for item in valid]
    assert all(value is not None for value in valid_values)
    values = [float(value) for value in valid_values if value is not None]
    positive = [item for item in valid if (valid_sales(item) or 0) > 0]
    sorted_valid = sort_sales(valid)
    known_brands = {normalize_text(item.get("brand")) for item in valid if known_brand(item.get("brand"))}
    known_parents = {item["parent_asin"] for item in valid if item.get("parent_asin")}
    unknown_brand_sales = sum(valid_sales(item) or 0.0 for item in valid if not known_brand(item.get("brand")))
    brand_sales: dict[str, float] = defaultdict(float)
    for item in valid:
        if known_brand(item.get("brand")):
            brand_sales[normalize_text(item.get("brand"))] += valid_sales(item) or 0.0
    total = sum(values)
    return {
        "matched_asin_count": len(members),
        "unresolved_asin_count": len(unresolved),
        "membership_complete": len(unresolved) == 0,
        "valid_sales_count": len(valid),
        "invalid_sales_count": len(members) - len(valid),
        "sales_complete": len(valid) == len(members),
        "positive_sales_asin_count": len(positive),
        "monthly_sales_known_sum": total,
        "monthly_sales_median": median(values),
        "monthly_sales_mean": total / len(values) if values else None,
        "price_median": median([item["price"] for item in members if item.get("price") is not None and item["price"] >= 0]),
        "known_parent_count": len(known_parents),
        "known_brand_count": len(known_brands),
        "unknown_brand_sales_share": unknown_brand_sales / total if total > 0 else None,
        "product_cr1": concentration(values, 1),
        "product_cr3": concentration(values, 3),
        "product_cr5": concentration(values, 5),
        "brand_cr1_known": concentration(list(brand_sales.values()), 1),
        "brand_cr3_known": concentration(list(brand_sales.values()), 3),
        "brand_cr5_known": concentration(list(brand_sales.values()), 5),
        "brand_concentration_complete": unknown_brand_sales == 0,
        "head_asins": [item["asin"] for item in sorted_valid[:3]],
    }


def supply_demand_baseline(project: dict[str, Any]) -> dict[str, Any]:
    """Freeze the original category's valid ASIN and monthly-sales universe.

    The denominator is intentionally independent from candidate membership and
    shortlist composition.  A zero monthly-sale ASIN remains part of supply;
    it was already accepted by the completed cleaned-listing input.
    """
    members = [listing for listing in project["listings"] if valid_sales(listing) is not None]
    total_sales = sum(valid_sales(listing) or 0.0 for listing in members)
    return {
        "source": "market_research/cleaned_30d_listings.json",
        "membership_policy": "原始品类去重有效 ASIN；有效月销量为非负有限值，零销量保留在 Listing 数量供给中。",
        "category_valid_asin_count": len(members),
        "category_monthly_sales_sum": total_sales,
    }


def linear_score(value: float, anchors: tuple[tuple[float, float], ...]) -> float:
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (left_value, left_score), (right_value, right_score) in zip(anchors, anchors[1:]):
        if value <= right_value:
            ratio = (value - left_value) / (right_value - left_value)
            return left_score + (right_score - left_score) * ratio
    return anchors[-1][1]


def primary_poe_evidence(candidate: dict[str, Any], poe: dict[str, Any]) -> dict[str, Any]:
    row_number = candidate.get("primary_poe_row_number")
    evidence: dict[str, Any] = {
        "status": "unavailable",
        "source": "user_provided_poe_xlsx",
        "primary_row_number": row_number,
        "relationship": candidate.get("primary_poe_relationship"),
        "selection": candidate.get("primary_poe_selection"),
        "required_fields": list(POE_SCORING_FIELDS),
    }
    if row_number is None or candidate.get("primary_poe_relationship") != "exact":
        evidence["reason"] = "没有准确对应的商机探测器主评分行"
        return evidence
    row = next((item for item in poe["rows"] if item["row_number"] == row_number), None)
    if row is None:
        evidence["reason"] = "主评分行不存在或已隔离"
        return evidence
    fields = row["fields"]
    metrics = {
        "search_volume_90d": parse_number(fields.get("搜索量-近90天")),
        "sales_90d": parse_number(fields.get("销量-近90天")),
        "click_conversion_rate_90d": percentage_points(fields.get("点击转化率-近90天 (%)")),
        "average_price_90d": parse_number(fields.get("平均售价-近90天 ($)")),
        "top5_product_click_share_90d": percentage_points(fields.get("前5商品点击占比-近90天 (%)")),
        "top5_product_click_share_360d": percentage_points(fields.get("前5商品点击占比-近360天 (%)")),
        "top5_brand_click_share_90d": percentage_points(fields.get("前5品牌点击占比-近90天 (%)")),
        "top5_brand_click_share_360d": percentage_points(fields.get("前5品牌点击占比-近360天 (%)")),
        "return_rate_360d": percentage_points(fields.get("退货率-近360天 (%)")),
        "new_product_count_360d": parse_number(fields.get("新品发布数-360天")),
        "successful_new_product_count_360d": parse_number(fields.get("成功发布数-360天")),
    }
    missing = [name for name, value in metrics.items() if value is None]
    invalid: list[str] = []
    for name in ("search_volume_90d", "sales_90d", "average_price_90d", "new_product_count_360d", "successful_new_product_count_360d"):
        if metrics[name] is not None and metrics[name] < 0:
            invalid.append(name)
    for name in (
        "click_conversion_rate_90d",
        "top5_product_click_share_90d",
        "top5_product_click_share_360d",
        "top5_brand_click_share_90d",
        "top5_brand_click_share_360d",
        "return_rate_360d",
    ):
        if metrics[name] is not None and not 0.0 <= metrics[name] <= 100.0:
            invalid.append(name)
    new_count = metrics["new_product_count_360d"]
    success_count = metrics["successful_new_product_count_360d"]
    if new_count is not None and new_count != int(new_count):
        invalid.append("new_product_count_360d")
    if success_count is not None and success_count != int(success_count):
        invalid.append("successful_new_product_count_360d")
    if new_count is not None and success_count is not None and success_count > new_count:
        invalid.append("successful_new_product_count_360d")
    evidence.update(
        {
            "poe_name": row["name"],
            "source_row_numbers": row.get("source_row_numbers", [row_number]),
            "metrics": metrics,
            "raw_fields": {field: fields.get(field) for field in (*POE_ENTRY_VALUE_FIELDS, *POE_SEARCH_TREND_FIELDS)},
        }
    )
    for name in invalid:
        metrics[name] = None
    evidence["missing_or_invalid_fields"] = sorted(set(missing + invalid))
    evidence["status"] = "available"
    if missing or invalid:
        evidence["reason"] = "主评分行部分指标缺失或无效：" + "、".join(sorted(set(missing + invalid)))
    return evidence


def require_metrics(primary: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    if primary.get("status") != "available":
        return primary.get("reason") or "没有准确主评分行"
    missing = [key for key in fields if primary.get("metrics", {}).get(key) is None]
    return "缺少可用指标：" + "、".join(missing) if missing else None


def search_growth_evidence(primary: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": "unavailable",
        "source": "user_provided_poe_xlsx",
        "rule": "不计入总分；近90天和近180天均不高于-20%时列为待观察。",
        "growth_rates": {},
    }
    raw_fields = primary.get("raw_fields") if isinstance(primary, dict) else None
    if not isinstance(raw_fields, dict):
        evidence["reason"] = "没有主评分行的搜索增长记录"
        return evidence
    rates = {field: percentage_points(raw_fields.get(field)) for field in POE_SEARCH_TREND_FIELDS}
    missing = [field for field, value in rates.items() if value is None]
    evidence["growth_rates"] = rates
    if missing:
        evidence["reason"] = "缺少或无法解析：" + "、".join(missing)
        return evidence
    evidence["status"] = "watch" if rates["搜索量增长率-近90天 (%)"] <= -20 and rates["搜索量增长率-近180天 (%)"] <= -20 else "normal"
    return evidence


def keyword_summary(candidate: dict[str, Any], keywords: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    expanded: list[dict[str, Any]] = []
    direct_keys: set[str] = set()
    all_assigned_keys: set[str] = set()
    for assignment in candidate["keyword_assignments"]:
        key = assignment["key"]
        all_assigned_keys.add(key)
        if assignment["type"] == "direct":
            direct_keys.add(key)
        main_rows = keywords["main_by_key"][key]
        conversion_rows = keywords["conversion_by_key"].get(key, [])
        expanded.append(
            {
                "keyword": assignment["keyword"],
                "normalized_keyword": key,
                "type": assignment["type"],
                "reason": assignment["reason"],
                "main_source_rows": main_rows,
                "conversion_source_rows": conversion_rows,
            }
        )
    direct_rows = [row for item in expanded if item["type"] == "direct" for row in item["main_source_rows"]]
    search_values = [parse_number(row["fields"].get("月搜索量")) for row in direct_rows]
    purchase_values = [parse_number(row["fields"].get("月购买量")) for row in direct_rows]
    direct_conversion_rows = [row for item in expanded if item["type"] == "direct" for row in item["conversion_source_rows"]]
    clicks = [parse_number(row["fields"].get("近90天点击量")) for row in direct_conversion_rows]
    purchases_90 = [parse_number(row["fields"].get("近90天购买量")) for row in direct_conversion_rows]
    valid_click_purchase = [(click, purchase) for click, purchase in zip(clicks, purchases_90) if click is not None and click > 0 and purchase is not None and purchase >= 0]
    total_clicks = sum(click for click, _ in valid_click_purchase)
    total_purchases = sum(purchase for _, purchase in valid_click_purchase)
    main_count = sum(len(value) for value in keywords["main_by_key"].values())
    return (
        {
            "assignment_count": len(expanded),
            "direct_assignment_count": len(direct_keys),
            "extended_assignment_count": sum(item["type"] == "extended" for item in expanded),
            "ambiguous_assignment_count": sum(item["type"] == "ambiguous" for item in expanded),
            "direct_monthly_search": {
                "known_sum": sum(value for value in search_values if value is not None and value >= 0),
                "valid_source_row_count": sum(value is not None for value in search_values),
                "source_row_count": len(search_values),
                "complete": bool(search_values) and all(value is not None and value >= 0 for value in search_values),
            },
            "direct_monthly_purchase": {
                "known_sum": sum(value for value in purchase_values if value is not None),
                "valid_source_row_count": sum(value is not None for value in purchase_values),
                "source_row_count": len(purchase_values),
                "complete": all(value is not None for value in purchase_values),
            },
            "direct_90_day_click_conversion": {
                "clicks": total_clicks if valid_click_purchase else None,
                "purchases": total_purchases if valid_click_purchase else None,
                "click_conversion_rate": total_purchases / total_clicks if total_clicks > 0 else None,
                "valid_source_row_count": len(valid_click_purchase),
                "source_row_count": len(direct_conversion_rows),
            },
            "main_keyword_source_row_count": main_count,
            "assigned_main_keyword_source_row_count": sum(len(keywords["main_by_key"][key]) for key in all_assigned_keys),
        },
        expanded,
    )


def return_risk_context(primary: dict[str, Any]) -> dict[str, Any]:
    """Keep POE return rate visible without giving it a ranking weight."""
    reason = require_metrics(primary, ("return_rate_360d",))
    if reason:
        return {"status": "unavailable", "reason": reason, "note": "退货率不参与两轮总分或正式推荐门槛。"}
    return {
        "status": "available",
        "source": "user_provided_poe_xlsx",
        "primary_row_number": primary.get("primary_row_number"),
        "return_rate_360d": primary["metrics"]["return_rate_360d"],
        "note": "退货率仅作补充风险提示，不参与两轮总分或正式推荐门槛。",
    }


def score_payload(components: dict[str, float | None], weights: dict[str, float]) -> dict[str, Any]:
    lower = 0.0
    upper = 0.0
    unknown: list[str] = []
    for key, weight in weights.items():
        value = components.get(key)
        if value is None:
            upper += weight
            unknown.append(key)
        else:
            lower += value / 100 * weight
            upper += value / 100 * weight
    return {
        "components": components,
        "weights": weights,
        "score": lower if not unknown else None,
        "lower_bound": lower,
        "upper_bound": upper,
        "unknown_components": unknown,
        "determinate": not unknown,
    }


def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    scoring = item["scoring"]
    score = scoring["score"] if scoring["score"] is not None else scoring["lower_bound"]
    competition = item.get("competition_openness_score")
    competition = competition if competition is not None else -1.0
    return (-score, -competition, item["candidate"]["id"])


def set_dedupe_conflicts(evaluations: list[dict[str, Any]]) -> None:
    """Shared monthly sales >= 50% of the smaller market => same demand; explicit declarations still count."""
    pool = helper_module("niche_candidate_pool")
    by_id = {item["candidate"]["id"]: item for item in evaluations}
    for item in evaluations:
        item["dedupe_conflicts"] = []
        item["dedupe_conflict_ids"] = set()
    markets = [{"id": item["candidate"]["id"], "sales_by_asin": {m["asin"]: valid_sales(m) or 0.0 for m in item["members"] if valid_sales(m) is not None}}
               for item in evaluations]
    pairs = {tuple(sorted(pair)): ("auto", ratio) for pair, ratio in pool.containment_conflicts(markets).items()}
    declared_reasons: dict[tuple[str, str], str] = {}
    for item in evaluations:
        for other in item["candidate"].get("exclusive_with") or []:
            if other in by_id:
                pair = tuple(sorted((item["candidate"]["id"], other)))
                pairs.setdefault(pair, ("declared", None))
                reason = (item["candidate"].get("exclusive_reasons") or {}).get(other)
                if reason:
                    declared_reasons[pair] = reason
    for (left_id, right_id), (kind, ratio) in sorted(pairs.items()):
        left, right = by_id[left_id], by_id[right_id]
        reason = (f"共享月销量占较小市场的 {ratio:.0%}（≥{pool.CONTAINMENT_THRESHOLD:.0%}，视为同一需求）" if kind == "auto"
                  else "候选定义中声明的父子／替代需求互斥" + (f"：{declared_reasons[(left_id, right_id)]}" if (left_id, right_id) in declared_reasons else "（未写依据）"))
        for one, two in ((left, right), (right, left)):
            one["dedupe_conflicts"].append({"candidate_id": two["candidate"]["id"], "candidate_name": two["candidate"]["name"],
                                            "kind": kind, "shared_sales_ratio": ratio, "reason": reason})
            one["dedupe_conflict_ids"].add(two["candidate"]["id"])


def candidate_selection(evaluations: list[dict[str, Any]], target_k: int = 3) -> dict[str, Any]:
    """Exact bounded independent-set selection; never materialize all combinations."""
    formal = sorted((item for item in evaluations if item["formal_eligible"]), key=rank_key)
    if not formal:
        return {"selected": [], "pending": evaluations, "reason": "没有满足正式推荐门槛的候选", "determinate": False}
    target_k = min(target_k, len(formal))
    def group_key(indices: list[int]) -> tuple[Any, ...]:
        group = [formal[i] for i in indices]
        return (-len(group), -sum(item["scoring"]["score"] for item in group),
                -sum(item["competition_openness_score"] for item in group),
                tuple(sorted(item["candidate"]["id"] for item in group)))
    indices = {item["candidate"]["id"]: i for i, item in enumerate(formal)}
    conflicts = [sum(1 << indices[c] for c in item["dedupe_conflict_ids"] if c in indices) for item in formal]
    best: list[int] = []
    best_key = group_key(best)
    def search(chosen: list[int], available: int) -> None:
        nonlocal best, best_key
        current_key = group_key(chosen)
        if current_key < best_key:
            best, best_key = chosen[:], current_key
        room = target_k - len(chosen)
        if not room or not available:
            return
        remaining = [i for i in range(len(formal)) if available & (1 << i)]
        optimistic = chosen + remaining[:room]
        if group_key(optimistic) >= best_key:
            return
        while available:
            bit = available & -available
            i = bit.bit_length() - 1
            available ^= bit
            if len(chosen) + 1 + bin(available).count("1") < len(best):
                break
            search(chosen + [i], available & ~conflicts[i])
            remaining = [j for j in range(len(formal)) if available & (1 << j)]
            if group_key(chosen + remaining[:room]) >= best_key:
                break
    if not any(conflicts):
        best = list(range(target_k))
    else:
        search([], (1 << len(formal)) - 1)
    selected = sorted((formal[i] for i in best), key=rank_key)
    selected_ids = {item["candidate"]["id"] for item in selected}
    pending = [item for item in evaluations if item["candidate"]["id"] not in selected_ids]
    for item in pending:
        if item["formal_eligible"]:
            item["selection_note"] = ("与已选市场属于同义、父子或高度重叠需求" if item["dedupe_conflict_ids"] & selected_ids else "本轮兼容组合总分未入选")
    return {"selected": selected, "pending": pending,
            "reason": None if len(selected) == target_k else "候选存在冲突，只推荐互不重复的市场。", "determinate": True}


def backup_rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    scoring = item["scoring"]
    score = scoring["score"] if scoring["score"] is not None else scoring["lower_bound"]
    competition = item.get("competition_openness_score")
    return (len(scoring["unknown_components"]), -score, -(competition if competition is not None else -1.0), item["candidate"]["id"])


def backup_selection(evaluations: list[dict[str, Any]], selected_ids: list[str], target_k: int = 3) -> list[dict[str, Any]]:
    """Fill up to target_k with clearly labelled backups; never relaxes the formal gate.

    Only candidates that conflict with no chosen market are eligible, ordered by
    missing scoring components, score (lower bound when incomplete),
    competition openness and id.
    """
    chosen = set(selected_ids)
    backups: list[dict[str, Any]] = []
    for item in sorted((item for item in evaluations if item["candidate"]["id"] not in chosen), key=backup_rank_key):
        if len(chosen) >= target_k:
            break
        if item["dedupe_conflict_ids"] & chosen:
            continue
        backups.append(item)
        chosen.add(item["candidate"]["id"])
    for rank, item in enumerate(backups, 1):
        item["backup_rank"] = rank
        item["backup_reason"] = item.get("formal_ineligible_reason") or "未达到正式推荐条件"
    return backups


def brand_identity(value: Any) -> str | None:
    return normalize_text(value) if known_brand(value) else None


def set_product_demand_scale_scores(evaluations: list[dict[str, Any]]) -> None:
    """Percentiles among comparable candidates: segment monthly sales 60%, direct-keyword monthly search 40%."""
    pool = helper_module("niche_candidate_pool")
    comparable = [item for item in evaluations if item["base_eligible"]]
    sales = pool.percentiles(comparable, lambda item: item["metrics"]["monthly_sales_known_sum"], lambda item: item["candidate"]["id"]) if comparable else {}
    search = pool.percentiles(comparable, lambda item: item["keyword_metrics"]["direct_monthly_search"]["known_sum"], lambda item: item["candidate"]["id"]) if comparable else {}
    for item in evaluations:
        candidate_id = item["candidate"]["id"]
        if candidate_id not in sales:
            item["demand_scale_score"] = None
            item["demand_scale_evidence"] = {"status": "unavailable", "reason": "未满足需求证据、匹配数量或正销量条件，不参与需求规模比较"}
            continue
        item["demand_scale_score"] = 0.4 * search[candidate_id] + 0.6 * sales[candidate_id]
        item["demand_scale_evidence"] = {
            "status": "available", "source": "product_sample+keyword_file", "comparison_candidate_count": len(comparable),
            "segment_monthly_sales": item["metrics"]["monthly_sales_known_sum"],
            "direct_keyword_monthly_search": item["keyword_metrics"]["direct_monthly_search"]["known_sum"],
            "sales_percentile_score": sales[candidate_id], "search_percentile_score": search[candidate_id],
            "formula": "60%×本市场月销量百分位 + 40%×direct 核心词月搜索量百分位（同批可比候选）",
        }


def candidate_evaluations(project: dict[str, Any], candidates: list[dict[str, Any]], keywords: dict[str, Any], poe: dict[str, Any], refinement: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pool = helper_module("niche_candidate_pool")
    evaluations: list[dict[str, Any]] = []
    started = time.perf_counter()
    matching_seconds = 0.0
    supply_baseline = supply_demand_baseline(project)
    for candidate in candidates:
        matching_started = time.perf_counter()
        members, unresolved = match_members(project, candidate)
        metrics = product_metrics(members, unresolved)
        keyword_metrics, keyword_assignments = keyword_summary(candidate, keywords)
        matching_seconds += time.perf_counter() - matching_started
        has_poe_evidence = candidate.get("primary_poe_row_number") is not None
        has_keyword_evidence = keyword_metrics["direct_assignment_count"] > 0 and keyword_metrics["direct_monthly_search"]["known_sum"] > 0
        base_eligible = (
            candidate["demand_status"] == "established"
            and (has_keyword_evidence or has_poe_evidence)
            and metrics["matched_asin_count"] >= 10
            and metrics["positive_sales_asin_count"] > 0
        )
        primary = primary_poe_evidence(candidate, poe) if has_poe_evidence else {
            "status": "not_applicable", "reason": "多维组合候选，没有商机表行" if candidate.get("source") == "combo" else "没有准确对应的商机表行"}
        trend = search_growth_evidence(primary)
        supply = pool.robust_supply_demand(members, supply_baseline["category_valid_asin_count"], supply_baseline["category_monthly_sales_sum"], valid_sales)
        supply_score = linear_score(supply["robust_index"], SUPPLY_DEMAND_ANCHORS) if supply["status"] == "available" else None
        supply.update(supply_demand_index=supply.get("robust_index"), supply_demand_score=supply_score, score_anchors=list(SUPPLY_DEMAND_ANCHORS),
                      source=supply_baseline["source"])
        competition, competition_evidence = pool.product_competition(members, valid_sales, brand_identity)
        newcomer, newcomer_evidence = pool.product_new_entry(members, valid_sales)
        evaluations.append(
            {
                "candidate": candidate,
                "members": members,
                "unresolved": unresolved,
                "metrics": metrics,
                "keyword_metrics": keyword_metrics,
                "keyword_assignments": keyword_assignments,
                "base_eligible": base_eligible,
                "has_keyword_evidence": has_keyword_evidence,
                "primary_poe": primary,
                "search_growth_evidence": trend,
                "supply_demand_score": supply_score,
                "supply_demand_evidence": supply,
                "competition_openness_score": competition,
                "competition_openness_evidence": competition_evidence,
                "new_product_evidence_score": newcomer,
                "new_product_evidence": newcomer_evidence,
                "ad_cost_evidence": {
                    "status": "not_calculated",
                    "reason": "广告压力不参与粗筛；等待用户提供关键词转化表后再按统一词集计算。",
                },
                "return_risk_context": return_risk_context(primary),
                "direct_keyword_keys": {item["normalized_keyword"] for item in keyword_assignments if item["type"] == "direct"},
            }
        )
    set_product_demand_scale_scores(evaluations)
    if refinement is not None:
        apply_refinement(evaluations, refinement)
    for item in evaluations:
        issues: list[str] = []
        if not item["base_eligible"]:
            is_combo = item["candidate"].get("source") == "combo"
            if item["candidate"]["demand_status"] != "established":
                issues.append("多维组合没有 direct 核心词，需求证据不足" if is_combo else "需求状态为待验证（pending）")
            elif not (item["has_keyword_evidence"] or item["candidate"].get("primary_poe_row_number") is not None):
                issues.append("direct 核心词没有搜索量，且没有准确商机主行，需求证据不足")
            if item["metrics"]["matched_asin_count"] < 10:
                issues.append(f"完整匹配 ASIN 仅 {item['metrics']['matched_asin_count']} 个，低于正式门槛 10 个")
            if item["metrics"]["positive_sales_asin_count"] <= 0:
                issues.append("没有月销量为正的匹配商品")
        robust = item["supply_demand_evidence"].get("robust_index")
        if robust is not None and robust < pool.MIN_ROBUST_INDEX:
            issues.append(f"稳健供需指数 {robust:.2f} 低于 {pool.MIN_ROBUST_INDEX:.1f}，单品平均销量不高于品类平均")
        components = {
            "supply_demand": item["supply_demand_score"],
            "competition_openness": item["competition_openness_score"],
            "new_product_evidence": item["new_product_evidence_score"],
            "demand_scale": item["demand_scale_score"],
        }
        for key, value in components.items():
            if value is None and not (key == "demand_scale" and not item["base_eligible"]):
                evidence_name = {
                    "supply_demand": "supply_demand_evidence",
                    "demand_scale": "demand_scale_evidence",
                    "competition_openness": "competition_openness_evidence",
                    "new_product_evidence": "new_product_evidence",
                }[key]
                issues.append(item[evidence_name].get("reason") or f"{key} 缺少可用评分数据")
        item["scoring"] = score_payload(components, SCORE_WEIGHTS)
        item["scoring_issues"] = list(dict.fromkeys(issues))
        item["formal_eligible"] = not item["scoring_issues"] and item["scoring"]["determinate"]
        item["formal_ineligible_reason"] = None if item["formal_eligible"] else "；".join(item["scoring_issues"])
    set_dedupe_conflicts(evaluations)
    return evaluations, {
        "weights": SCORE_WEIGHTS,
        "scoring_model": "frozen_top3_deep_analysis" if refinement is not None else "four_component_product_sample_shortlist",
        "supply_demand_reference": supply_baseline,
        "timings_seconds": {"matching": matching_seconds, "scoring": time.perf_counter() - started - matching_seconds},
    }


def helper_module(name: str) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
        if spec is None or spec.loader is None:
            fail(f"缺少本地计算模块：{name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def associate_refinement_sources(evaluations: list[dict[str, Any]], inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Associate each uploaded conversion/SellerSprite pair to one frozen niche.

    SellerSprite's Asin sheet must be the frozen market's full Top20 ASIN set.
    The conversion table has already been paired to that SellerSprite table by
    cumulative-traffic-top-90% keyword overlap.  No candidate keyword list is
    used for calculation or association.
    """
    pairings = inputs.get("pairings") or []
    if not evaluations or len(evaluations) != len(pairings):
        fail("关键词文件组数必须与冻结市场数一一对应")
    matches = _unique_keyword_assignment(
        evaluations,
        pairings,
        lambda evaluation, pairing: len({member["asin"] for member in top20_members(evaluation)} & pairing["seller"]["source_asins"]),
        "细分市场 Top20 ASIN 与卖家精灵 Asin 工作表",
    )
    sources: dict[str, dict[str, Any]] = {}
    mapping_evidence = []
    for market_index, pair_index, overlap in matches:
        market = evaluations[market_index]
        pair = pairings[pair_index]
        candidate_id = market["candidate"]["id"]
        frozen_top20 = {member["asin"] for member in top20_members(market)}
        source_asins = pair["seller"]["source_asins"]
        if source_asins != frozen_top20:
            missing = sorted(frozen_top20 - source_asins)
            extra = sorted(source_asins - frozen_top20)
            fail(f"{Path(pair['seller']['path']).name} 的 Asin 工作表与“{market['candidate']['name']}”冻结 Top20 ASIN 不完全一致"
                 f"（冻结 {len(frozen_top20)} 个；缺少：{'、'.join(missing) or '无'}；多出：{'、'.join(extra) or '无'}）")
        sources[candidate_id] = pair
        mapping_evidence.append({
            "candidate_id": candidate_id,
            "candidate_name": market["candidate"]["name"],
            "conversion_path": pair["conversion"]["path"],
            "seller_sprite_path": pair["seller"]["path"],
            "top20_asin_overlap": overlap,
            "top20_asin_match_count": len(frozen_top20),
            "conversion_top90_keyword_overlap": pair.get("keyword_overlap_count"),
            "conversion_top90_keyword_overlap_rate": pair.get("keyword_overlap_rate"),
            "basis": "seller_sprite_asin_sheet_equals_frozen_top20_then_conversion_overlaps_traffic_top90",
        })
    inputs["market_mappings"] = mapping_evidence
    return sources


def apply_refinement(evaluations: list[dict[str, Any]], conversions: dict[str, Any]) -> None:
    engine = helper_module("niche_refinement_metrics")
    sources = associate_refinement_sources(evaluations, conversions)
    for item in evaluations:
        # Frozen membership and Top20 stay untouched; the price/sales-valid
        # subset is only the sample for refined evidence and the eight rules.
        product = engine.product_evidence(item["members"])
        item["refined_product_evidence"] = {k: v for k, v in product.items() if k != "members"}
        source = sources[item["candidate"]["id"]]
        conversion_source = source["conversion"]
        seller_source = source["seller"]
        keyword_rows = []
        for conversion in conversion_source["rows"]:
            fields = conversion["fields"]
            key = normalize_text(fields.get("关键词"))
            seller = seller_source["by_key"].get(key)
            seller_reason = seller.get("exclusion_reason") if seller else "missing_sellersprite_keyword"
            click = parse_number(fields.get("近90天点击量"))
            purchase = parse_number(fields.get("近90天购买量"))
            reported = fields.get("reported_click_conversion_rate")
            row = {"keyword": display_text(fields.get("关键词")), "key": key,
                   "ppc_bid": seller.get("ppc_bid") if seller else None,
                   "clicks": click, "purchases": purchase,
                   "conversion_available": True,
                   "exclusion_reason": seller_reason,
                   "bid_source_rows": seller.get("source_row_numbers", []) if seller else [],
                   "conversion_source_rows": [conversion["row_number"]],
                   "period": conversion_source["period"], "reported_click_conversion_rate": reported,
                   "conversion_rate_mismatch": reported is not None and click is not None and click > 0 and purchase is not None and abs(reported - purchase / click) > 0.0001}
            keyword_rows.append(row)
        ad = engine.advertising_evidence(keyword_rows, product["mean_price"])
        ad["mean_price"] = product["mean_price"]
        ad["half_click_conversion_pressure_estimate"] = ad.get("half_conversion_pressure_estimate")
        ad["source"] = "seller_sprite_keyword_file.PPC竞价 + user_full_keyword_conversion_xlsx"
        ad["conversion_path"] = conversion_source["path"]
        ad["seller_sprite_path"] = seller_source["path"]
        ad["file_association"] = "seller_sprite_asin_sheet_equals_frozen_top20_and_conversion_overlaps_traffic_top90"
        ad["reason"] = "；".join(ad.get("reasons", []))
        item["ad_cost_evidence"] = ad
        item["keyword_metrics"]["direct_90_day_click_conversion"] = {
            "clicks": ad.get("total_clicks"), "purchases": ad.get("total_purchases"),
            "click_conversion_rate": ad.get("click_conversion_rate"),
            "source": "round2_keywords_with_both_conversion_and_bid",
        }


def inherit_shortlist_selection(evaluations: list[dict[str, Any]], shortlist: dict[str, Any]) -> list[str]:
    """Freeze Top3 identity and coarse scores while adding deep-analysis evidence."""
    selected_ids = shortlist["selected_candidate_ids"]
    market_ids = refinable_candidate_ids(shortlist)
    backup_ids = market_ids[len(selected_ids):]
    shortlist_by_id = {item["id"]: item for item in shortlist["candidates"]}
    evaluation_by_id = {item["candidate"]["id"]: item for item in evaluations}
    if set(market_ids) != set(evaluation_by_id) or any(key not in shortlist_by_id for key in market_ids):
        fail("进一步分析候选与冻结粗筛市场不一致，请重跑初筛")
    engine = helper_module("niche_refinement_metrics")
    for rank, candidate_id in enumerate(market_ids, 1):
        item = evaluation_by_id[candidate_id]
        frozen = shortlist_by_id[candidate_id]
        if [member["asin"] for member in top20_members(item)] != [member.get("asin") for member in frozen.get("top20") or []]:
            fail(f"“{item['candidate']['name']}”当前 Top20 与冻结粗筛 Top20 不一致，请重跑初筛")
        for field in (
            "scoring", "formal_eligible", "formal_ineligible_reason", "selection_note",
            "supply_demand_evidence", "demand_scale_evidence",
            "competition_openness_evidence", "new_product_evidence",
            "return_risk_context", "search_growth_evidence", "backup_rank", "backup_reason",
        ):
            item[field] = frozen.get(field)
        item["supply_demand_score"] = (frozen.get("scoring") or {}).get("components", {}).get("supply_demand")
        item["competition_openness_score"] = (frozen.get("scoring") or {}).get("components", {}).get("competition_openness")
        item["new_product_evidence_score"] = (frozen.get("scoring") or {}).get("components", {}).get("new_product_evidence")
        item["demand_scale_score"] = (frozen.get("scoring") or {}).get("components", {}).get("demand_scale")
        item["round1_rank"] = rank if candidate_id in selected_ids else None
        item["rule_conclusions"] = engine.eight_conclusions(item["members"], item["ad_cost_evidence"])
        item["entry_advice"] = engine.entry_advice(item["rule_conclusions"], item["ad_cost_evidence"],
                                                   item.get("search_growth_evidence"), candidate_id in backup_ids)
        reasons = []
        if item["ad_cost_evidence"].get("status") != "ready":
            reasons.append(item["ad_cost_evidence"].get("reason") or "广告压力证据不完整")
        if item["rule_conclusions"].get("status") != "ready":
            reasons.append("本市场部分八项结论缺少必要证据")
        item["deep_analysis_status"] = "ready" if not reasons else "partial"
        item["deep_analysis_reason"] = "；".join(reasons) if reasons else None
    return selected_ids, backup_ids


def ranking_snapshot(evaluations: list[dict[str, Any]], weights: dict[str, float], label: str, target_k: int = 3) -> dict[str, Any]:
    copies: list[dict[str, Any]] = []
    for item in evaluations:
        copied = dict(item)
        copied["scoring"] = score_payload(item["scoring"]["components"], weights)
        copies.append(copied)
    selection = candidate_selection(copies, target_k)
    return {
        "label": label,
        "weights": weights,
        "selected_candidate_ids": [item["candidate"]["id"] for item in selection["selected"]],
        "pending_candidate_ids": [item["candidate"]["id"] for item in selection["pending"]],
        "reason": selection["reason"],
    }


def sensitivity(evaluations: list[dict[str, Any]], base_weights: dict[str, float], target_k: int = 3) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for key in base_weights:
        for multiplier in (0.8, 1.2):
            changed = {name: value * (multiplier if name == key else 1.0) for name, value in base_weights.items()}
            total = sum(changed.values())
            normalized = {name: value / total * 100 for name, value in changed.items()}
            results.append(ranking_snapshot(evaluations, normalized, f"weight_{key}_{multiplier:.1f}", target_k))
    for item in evaluations:
        members = item["members"]
        ordered = sort_sales([member for member in members if valid_sales(member) is not None])
        for count in (1, 3):
            remaining = [member for member in members if member["asin"] not in {entry["asin"] for entry in ordered[:count]}]
            total = sum(valid_sales(member) or 0.0 for member in members if valid_sales(member) is not None)
            retained = sum(valid_sales(member) or 0.0 for member in remaining if valid_sales(member) is not None)
            results.append(
                {
                    "label": f"remove_top_{count}_asins:{item['candidate']['id']}",
                    "scope": "仅观察该候选原字段销量对头部 ASIN 的依赖；不重定义商品成员或替代正式评分。",
                    "candidate_id": item["candidate"]["id"],
                    "retained_monthly_sales_share": retained / total if total > 0 else None,
                    "remaining_asin_count": len(remaining),
                }
            )
        representatives = parent_representatives(members)
        retained = sum(valid_sales(member) or 0.0 for member in representatives if valid_sales(member) is not None)
        total = sum(valid_sales(member) or 0.0 for member in members if valid_sales(member) is not None)
        results.append(
            {
                "label": f"one_highest_asin_per_known_parent:{item['candidate']['id']}",
                "scope": "仅作父体重复敏感性情景，不替代原 ASIN 月销量口径。",
                "candidate_id": item["candidate"]["id"],
                "retained_monthly_sales_share": retained / total if total > 0 else None,
                "retained_known_parent_count": len(representatives),
            }
        )
    return results


def output_member(item: dict[str, Any], candidate: dict[str, Any], ranking: int | None = None) -> dict[str, Any]:
    result = source_listing(item)
    result.update({"candidate_id": candidate["id"], "matched_tag_expression": candidate["tag_expression"]})
    if ranking is not None:
        result["rank"] = ranking
    return result


def top20_members(item: dict[str, Any]) -> list[dict[str, Any]]:
    valid = [member for member in item["members"] if valid_sales(member) is not None]
    return [output_member(member, item["candidate"], index) for index, member in enumerate(sort_sales(valid)[:20], start=1)]


def public_candidate(item: dict[str, Any], selection_rank: int | None, selected: bool) -> dict[str, Any]:
    candidate = item["candidate"]
    result = {
        "id": candidate["id"],
        "name": candidate["name"],
        "source": candidate.get("source", "poe"),
        "entry_hint": candidate.get("entry_hint"),
        "combo_evidence": candidate.get("combo_evidence"),
        "definition": candidate["definition"],
        "task": candidate["task"],
        "selection_constraint_reason": candidate["selection_constraint_reason"],
        "demand_status": candidate["demand_status"],
        "tag_expression": candidate["tag_expression"],
        "poe_matches": candidate["poe_matches"],
        "primary_poe": item["primary_poe"],
        "formal_eligible": item["formal_eligible"],
        "formal_ineligible_reason": item["formal_ineligible_reason"],
        "product_metrics": item["metrics"],
        "keyword_metrics": item["keyword_metrics"],
        "supply_demand_evidence": item["supply_demand_evidence"],
        "demand_scale_evidence": item["demand_scale_evidence"],
        "competition_openness_evidence": item["competition_openness_evidence"],
        "new_product_evidence": item["new_product_evidence"],
        "ad_cost_evidence": item["ad_cost_evidence"],
        "return_risk_context": item["return_risk_context"],
        "search_growth_evidence": item["search_growth_evidence"],
        "dedupe_conflicts": item["dedupe_conflicts"],
        "scoring_issues": item["scoring_issues"],
        "scoring": item["scoring"],
        "selected": selected,
        "rank": selection_rank,
        "backup": item.get("backup_rank") is not None,
        "backup_rank": item.get("backup_rank"),
        "backup_reason": item.get("backup_reason"),
        "entry_advice": item.get("entry_advice"),
        "selection_note": item.get("selection_note"),
        "top20": top20_members(item),
        "keyword_assignments": item["keyword_assignments"],
        "refined_product_evidence": item.get("refined_product_evidence"),
        "rule_conclusions": item.get("rule_conclusions"),
        "round1_rank": item.get("round1_rank"),
        "deep_analysis_status": item.get("deep_analysis_status"),
        "deep_analysis_reason": item.get("deep_analysis_reason"),
    }
    return result


def formula_safe(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def build_csv(selected: list[dict[str, Any]], backups: list[dict[str, Any]] | None = None) -> str:
    rows: list[dict[str, Any]] = []
    markets = [(rank, item) for rank, item in enumerate(selected, start=1)]
    markets += [(f"候补{rank}", item) for rank, item in enumerate(backups or [], start=1)]
    for market_rank, item in markets:
        for member in top20_members(item):
            rows.append(
                {
                    "市场排名": market_rank,
                    "市场ID": item["candidate"]["id"],
                    "细分市场": item["candidate"]["name"],
                    "商品排名": member["rank"],
                    "ASIN": member["asin"],
                    "月销量": member["monthly_sales"],
                    "数据周期": member["month"],
                    "品牌": member["brand"],
                    "价格": member["price"],
                    "父ASIN": member["parent_asin"],
                    "商品名称": member["title"],
                    "商品链接": member["product_url"],
                }
            )
    fields = ["市场排名", "市场ID", "细分市场", "商品排名", "ASIN", "月销量", "数据周期", "品牌", "价格", "父ASIN", "商品名称", "商品链接"]
    from io import StringIO

    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: formula_safe(row.get(key)) for key in fields})
    return handle.getvalue()


def input_hashes(project: dict[str, Any], poe_path: Path, definitions_path: Path) -> dict[str, str]:
    manifest_for_fingerprint = {
        key: value
        for key, value in project["manifest"].items()
        if key not in {"artifacts", "status", "updated_at"}
    }
    paths = {
        "cleaned_listings": project["listing_path"],
        "listing_tags": project["tags_path"],
        "opportunity_analysis": project["analysis_path"],
        "input_manifest": project["input_manifest_path"],
        "poe_xlsx": poe_path,
        "candidate_definitions": definitions_path,
        "keyword_file": project["keyword_path"],
    }
    return {
        "project_manifest_semantic": hashlib.sha256(json_canonical(manifest_for_fingerprint).encode("utf-8")).hexdigest(),
        **{name: sha256_file(path) for name, path in paths.items()},
    }
def run_id_from_hashes(hashes: dict[str, str], stage: str) -> str:
    identity = {"hashes": hashes, "stage": stage, "target_k": 3, "rule_version": RULE_VERSION}
    digest = hashlib.sha256(json_canonical(identity).encode("utf-8")).hexdigest()
    return f"{RUN_ID_PREFIX}-{stage}-{digest[:16]}"


def build_outputs(project: dict[str, Any], poe: dict[str, Any], poe_dispositions: list[dict[str, Any]], evaluations: list[dict[str, Any]], context: dict[str, Any], hashes: dict[str, str], run_id: str, stage: str, frozen_selected_ids: list[str] | None = None, frozen_backup_ids: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    target_k = 3
    selection_started = time.perf_counter()
    if frozen_selected_ids is None:
        selection = candidate_selection(evaluations, target_k)
    else:
        evaluation_by_id = {item["candidate"]["id"]: item for item in evaluations}
        if len(frozen_selected_ids) > target_k or any(key not in evaluation_by_id for key in frozen_selected_ids):
            fail("冻结的 Top3 与当前进一步分析结果不一致")
        selected = [evaluation_by_id[key] for key in frozen_selected_ids]
        selected_set = set(frozen_selected_ids)
        selection = {
            "selected": selected,
            "pending": [item for item in evaluations if item["candidate"]["id"] not in selected_set],
            "reason": "继承粗筛已确定的 Top3 与排名；进一步分析不重新选择。",
            "determinate": True,
        }
    selected = selection["selected"]
    selected_ids = [item["candidate"]["id"] for item in selected]
    if frozen_selected_ids is None:
        backups = backup_selection(evaluations, selected_ids, target_k)
    else:
        backups = [evaluation_by_id[key] for key in frozen_backup_ids or [] if key in evaluation_by_id]
    backup_ids = [item["candidate"]["id"] for item in backups]
    selection_seconds = time.perf_counter() - selection_started
    pending_ids = [item["candidate"]["id"] for item in selection["pending"] if item["candidate"]["id"] not in backup_ids]
    selection_status = "determinate" if selection["determinate"] else "pending_verification"
    ranks = {candidate_id: index for index, candidate_id in enumerate(selected_ids, start=1)}
    if frozen_selected_ids is None:
        for item in selected:
            tied = [other["candidate"]["name"] for other in selected if other is not item and rank_key(other)[:-1] == rank_key(item)[:-1]]
            if tied:
                item["selection_note"] = "同优先级：" + "、".join(tied)
    recommendations = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "run_id": run_id,
        "project_id": project["project_id"],
        "marketplace": project["marketplace"],
        "source": {
            "keyword": display_text(project["manifest"].get("keyword") or project["input_manifest"].get("keyword")) or None,
            "category_node": display_text(project["manifest"].get("category_node") or project["input_manifest"].get("category_node")) or None,
        },
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "selection_source": RULE_VERSION if frozen_selected_ids is None else "frozen_shortlist_top3",
        "input_hashes": hashes,
        "poe_input": {
            "path": poe["path"],
            "sha256": poe["sha256"],
            "metrics_used_for_scoring": True,
            "primary_score_fields": list(POE_SCORING_FIELDS),
            "context_only_fields": [*POE_CONTEXT_FIELDS, *POE_SEARCH_TREND_FIELDS],
            "search_growth_fields": list(POE_SEARCH_TREND_FIELDS),
            "search_growth_rule": "展示主评分行的90／180／360天原始增长率，只作风险提示，不计入总分或入选门槛。",
            "accepted_record_count": len(poe["rows"]),
            "isolated_record_count": len(poe["isolated_rows"]),
            "conflicted_record_count": len(poe["conflicted_rows"]),
        },
        "poe_row_dispositions": poe_dispositions,
        "selected_candidate_ids": selected_ids,
        "backup_candidate_ids": backup_ids,
        "pending_candidate_ids": pending_ids,
        "selection_status": selection_status,
        "selection_reason": selection["reason"],
        "scoring_model": context["scoring_model"],
        "weights": context["weights"],
        "supply_demand_reference": context["supply_demand_reference"],
        "candidate_pool": context.get("candidate_pool"),
        "candidates": [public_candidate(item, ranks.get(item["candidate"]["id"]), item["candidate"]["id"] in ranks) for item in evaluations],
        "sensitivity": sensitivity(evaluations, context["weights"], target_k) if frozen_selected_ids is None else [],
        "stage": stage, "target_k": target_k,
    }
    if frozen_selected_ids is not None:
        per_market = {item["candidate"]["id"]: item.get("deep_analysis_status", "partial") for item in [*selected, *backups]}
        recommendations["shortlist_run_id"] = None
        recommendations["deep_analysis_by_candidate"] = per_market
        recommendations["deep_analysis_status"] = "ready" if all(status == "ready" for status in per_market.values()) else "partial"
    keyword_output = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "run_id": run_id,
        "project_id": project["project_id"],
        "keyword_source": {
            "path": str(project["keyword_path"]),
            "sha256": hashes["keyword_file"],
            "conversion_path": None,
        },
        "candidates": [
            {
                "candidate_id": item["candidate"]["id"],
                "summary": item["keyword_metrics"],
                "assignments": item["keyword_assignments"],
            }
            for item in evaluations
        ],
    }
    membership_output = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "run_id": run_id,
        "project_id": project["project_id"],
        "candidates": [
            {
                "candidate_id": item["candidate"]["id"],
                "tag_expression": item["candidate"]["tag_expression"],
                "matched_members": [output_member(member, item["candidate"]) for member in sort_sales(item["members"])],
                "unresolved_members": item["unresolved"],
                "excluded_asin_count": len(project["listings"]) - len(item["members"]) - len(item["unresolved"]),
                "top20": top20_members(item) if item["candidate"]["id"] in ranks or item["candidate"]["id"] in backup_ids else [],
            }
            for item in evaluations
        ],
    }
    csv_text = build_csv(selected)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "run_id": run_id,
        "project_id": project["project_id"],
        "status": "success",
        "input_hashes": hashes,
        "selection_source": RULE_VERSION,
        "selection_status": selection_status,
        "selected_candidate_ids": selected_ids,
        "backup_candidate_ids": backup_ids,
        "pending_candidate_ids": pending_ids,
        "supply_demand_reference": context["supply_demand_reference"],
        "generated_at": recommendations["generated_at"],
        "selection_seconds": selection_seconds,
    }
    if frozen_selected_ids is not None:
        receipt["deep_analysis_by_candidate"] = recommendations["deep_analysis_by_candidate"]
        receipt["deep_analysis_status"] = recommendations["deep_analysis_status"]
    for payload in (keyword_output, membership_output, receipt):
        payload["stage"] = stage
        payload["target_k"] = target_k
    return recommendations, keyword_output, membership_output, csv_text, receipt


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def core_keyword_csv(result: dict[str, Any]) -> str:
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["市场ID", "细分市场", "核心关键词", "月搜索量", "关键词表源行", "初筛运行ID"])
    selected = set(result["selected_candidate_ids"])
    for candidate in result["candidates"]:
        if candidate["id"] not in selected:
            continue
        for row in candidate["keyword_assignments"]:
            if row["type"] == "direct":
                source = row["main_source_rows"][0]
                writer.writerow([formula_safe(value) for value in (candidate["id"], candidate["name"], row["keyword"], source["fields"].get("月搜索量"), ",".join(map(str, source.get("source_row_numbers", [source["row_number"]]))), result["run_id"])])
    return output.getvalue()


FROZEN_INPUT_DIR = "frozen_inputs"


def frozen_input_path(project: dict[str, Any], raw: str) -> Path:
    """Frozen inputs are stored relative to the project root; older shortlists kept absolute paths."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else project["root"] / path


def commit_outputs(project: dict[str, Any], outputs: tuple, shortlist: dict[str, Any] | None = None,
                   snapshots: dict[Path, bytes] | None = None) -> Path:
    result, keywords, memberships, csv_text, receipt = outputs
    stage = result["stage"]
    folder = project["opportunity_dir"]
    original = folder / "市场机会深挖看板.html"
    if not original.is_file():
        fail(f"缺少机会看板：{original}")
    started = time.perf_counter()
    report_text = helper_module("niche_two_round_report").render_report(original.read_text(encoding="utf-8"), result if stage == "shortlist" else shortlist, result if stage == "refine" else None)
    receipt["timings_seconds"]["rendering"] = time.perf_counter() - started
    if stage == "shortlist":
        report_path = folder / "市场机会深挖看板-两轮初筛.html"
        files = {folder / "niche_shortlist.json": json_bytes(result),
                 folder / "niche_shortlist_keywords.json": json_bytes(keywords),
                 folder / "niche_shortlist_memberships.json": json_bytes(memberships),
                 folder / "niche_shortlist_core_keywords.csv": core_keyword_csv(result).encode("utf-8-sig"),
                 folder / "niche_shortlist_top20_asins.csv": csv_text.encode("utf-8-sig")}
        receipt_path = folder / "niche_shortlist_run.json"
        files.update(snapshots or {})
        artifact_keys = {"niche_shortlist": "niche_shortlist.json", "niche_shortlist_run": receipt_path.name,
                         "niche_shortlist_core_keywords": "niche_shortlist_core_keywords.csv", "niche_shortlist_report": report_path.name}
    else:
        report_path = folder / "市场机会深挖看板-两轮复评.html"
        conclusions = {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION, "run_id": result["run_id"],
                       "shortlist_run_id": result["shortlist_run_id"], "stage": stage,
                       "candidates": [{"candidate_id": c["id"], **c["rule_conclusions"]} for c in result["candidates"] if c["selected"]]}
        files = {folder / "08_niche_recommendations.json": json_bytes(result),
                 folder / "09_niche_keyword_assignments.json": json_bytes(keywords),
                 folder / "10_niche_product_memberships.json": json_bytes(memberships),
                 folder / "niche_top20_asins.csv": csv_text.encode("utf-8-sig"),
                 folder / "niche_rule_conclusions.json": json_bytes(conclusions)}
        receipt_path = folder / "niche_recommendation_run.json"
        artifact_keys = {"niche_recommendations": "08_niche_recommendations.json", "niche_recommendation_run": receipt_path.name,
                         "niche_keyword_assignments": "09_niche_keyword_assignments.json", "niche_product_memberships": "10_niche_product_memberships.json",
                         "niche_top20_asins": "niche_top20_asins.csv", "niche_rule_conclusions": "niche_rule_conclusions.json", "niche_refinement_report": report_path.name}
    files[report_path] = report_text.encode("utf-8")
    receipt["output_hashes"] = {path.name: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    receipt["total_compute_seconds"] = time.perf_counter() - receipt.pop("_start_counter")
    files[receipt_path] = json_bytes(receipt)
    manifest = dict(project["manifest"])
    manifest["artifacts"] = {**manifest.get("artifacts", {}), **{key: "market_opportunity/" + value for key, value in artifact_keys.items()}}
    state = (
        "awaiting_keyword_conversion" if stage == "shortlist" and refinable_candidate_ids(result)
        else "shortlist_pending" if stage == "shortlist"
        else "refined_ready" if result.get("deep_analysis_status") == "ready"
        else "refinement_pending"
    )
    manifest["status"] = {**manifest.get("status", {}), "niche_recommendation": state}
    manifest["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    files[project["manifest_path"]] = json_bytes(manifest)
    backup = {path: path.read_bytes() if path.exists() else None for path in files}
    try:
        for path, data in files.items():
            atomic_write_bytes(path, data)
    except BaseException:
        for path, previous in backup.items():
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, previous)
        raise
    return report_path


def write_failure_receipt(project_root: Path, stage: str, exc: BaseException) -> None:
    folder = project_root / "market_opportunity"
    if folder.is_dir():
        atomic_write_json(folder / ("niche_shortlist_run.json" if stage == "shortlist" else "niche_recommendation_run.json"), {
            "schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION, "stage": stage,
            "status": "failed", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "error": str(exc), "note": "历史成功结果不代表本次输入，不能交接下游。"})
        manifest_path = project_root / "project_manifest.json"
        if manifest_path.is_file():
            manifest = load_json(manifest_path, "项目状态")
            manifest["status"] = {**manifest.get("status", {}), "niche_recommendation": stage + "_failed"}
            atomic_write_json(manifest_path, manifest)


def command_prepare(args: argparse.Namespace) -> None:
    project = load_project(Path(args.project_root))
    poe = load_poe(Path(args.poe_xlsx).expanduser().resolve())
    workspace_path = Path(args.workspace).expanduser().resolve() if args.workspace else project["opportunity_dir"] / "niche_recommendation_workspace.json"
    atomic_write_json(workspace_path, candidate_workspace(project, poe))
    print(json.dumps({"status": "prepared", "workspace": str(workspace_path), "poe_row_count": len(poe["rows"])}, ensure_ascii=False))


VALIDATION_LEDGER = "niche_definition_validation.json"
VALIDATION_NO_PROGRESS_LIMIT = 2   # consecutive validate rounds whose error count did not fall


def command_validate(args: argparse.Namespace) -> int:
    """Check a definitions file and list ALL errors at once; record attempts so endless fix loops are visible."""
    project = load_project(Path(args.project_root))
    poe = load_poe(Path(args.poe_xlsx).expanduser().resolve())
    keywords = keyword_source(project["keyword_path"])
    definitions_path = Path(args.definitions).expanduser().resolve()
    errors: list[str] = []
    definitions = guarded(errors, load_json, definitions_path, "候选定义文件")
    if definitions is not None:
        guarded(errors, validate_definitions, definitions, project, poe, keywords, errors)
    errors = list(dict.fromkeys(errors))
    ledger_path = project["opportunity_dir"] / VALIDATION_LEDGER
    ledger = load_json(ledger_path, "定义校验记录") if ledger_path.is_file() else {"attempts": []}
    attempts = ledger.get("attempts") if isinstance(ledger, dict) and isinstance(ledger.get("attempts"), list) else []
    attempts.append({"at": dt.datetime.now(dt.timezone.utc).isoformat(), "definitions_sha256": sha256_file(definitions_path) if definitions_path.is_file() else None,
                     "error_count": len(errors)})
    no_progress = 0
    for previous, current in zip(attempts, attempts[1:]):
        no_progress = no_progress + 1 if current["error_count"] > 0 and current["error_count"] >= previous["error_count"] else 0
    atomic_write_json(ledger_path, {"attempts": attempts[-50:]})
    stop = bool(errors) and no_progress >= VALIDATION_NO_PROGRESS_LIMIT
    print(json.dumps({
        "status": "valid" if not errors else "invalid", "error_count": len(errors), "errors": errors,
        "attempt": len(attempts), "consecutive_rounds_without_progress": no_progress, "stop_recommended": stop,
        "next": ("可以运行 shortlist" if not errors else
                 "连续多轮错误数没有下降：停止修改，把以上错误和已尝试的修改报告给用户" if stop else "一次改完以上全部错误后再运行 validate"),
    }, ensure_ascii=False, indent=2))
    return 2 if errors else 0


BASE_STAGES = (
    ("fetch-roots", "market_opportunity/02_keyword_roots.json", "词根获取（计费）"),
    ("dimension-candidates", "market_opportunity/03_dimension_candidates.json", "维度候选"),
    ("confirm-dimensions", "market_opportunity/agent_dimensions.json", "Agent 整理并由用户确认维度"),
    ("tagging-template", "market_opportunity/04_tagging_workspace.json", "打标模板"),
    ("tag-listings", "market_opportunity/agent_listing_tags.json", "Agent 全量打标"),
    ("analyze-tags", "market_opportunity/07_opportunity_analysis.json", "原机会分析与看板"),
)


def project_status(root: Path) -> dict[str, Any]:
    """Read-only stage routing: what is done, what is next, and what must NOT be re-run."""
    root = root.expanduser().resolve()
    out: dict[str, Any] = {"project_root": str(root), "done": [], "warnings": []}
    if not (root / "project_manifest.json").is_file() or not (root / "market_research/cleaned_30d_listings.json").is_file():
        return {**out, "stage": "invalid_project", "next": "确认用户给出的是已完成市场调研的 market_project_* 根目录（需要 project_manifest.json 和 market_research/cleaned_30d_listings.json）"}
    for key, relative, label in BASE_STAGES:
        if not (root / relative).is_file() or (key == "analyze-tags" and not (root / "market_opportunity/市场机会深挖看板.html").is_file()):
            hint = "从这一步继续；之前步骤的产物已存在，不要重跑" if out["done"] else "从这一步开始"
            return {**out, "stage": f"base:{key}", "next": f"{label}（{key}）：{hint}。命令格式见 INSTRUCTIONS.md。"}
        out["done"].append(key)
    out["warnings"].append("基础分析已完成：不要重跑 fetch-roots（计费）或重新打标，否则会改变标签哈希，使已冻结的 Top3 失效。")
    folder = root / "market_opportunity"
    shortlist_path, shortlist_receipt = folder / "niche_shortlist.json", folder / "niche_shortlist_run.json"
    if not shortlist_path.is_file():
        ready = (folder / "niche_recommendation_workspace.json").is_file()
        return {**out, "stage": "recommend:prepare" if not ready else "recommend:definitions",
                "next": ("向用户索取商机探测器细分市场 Excel 后运行 prepare" if not ready else
                         "按 workspace 写候选定义与 combo_reviews，先运行 validate 直到无错误，再运行 shortlist")}
    receipt = json.loads(shortlist_receipt.read_text(encoding="utf-8")) if shortlist_receipt.is_file() else {}
    if receipt.get("status") != "success":
        return {**out, "stage": "recommend:shortlist_failed",
                "next": "上次粗筛失败：用同一份商机表和候选定义修正后重跑 shortlist（输入不变时结果与运行 ID 相同）",
                "last_error": receipt.get("error")}
    try:
        project = load_project(root)
        shortlist = verified_shortlist(project, shortlist_path)
    except RecommendationError as exc:
        return {**out, "stage": "recommend:shortlist_stale", "next": f"冻结的粗筛已失效：{exc}", "warnings": out["warnings"]}
    out["done"].append("shortlist")
    markets = refinable_candidate_ids(shortlist)
    names = {item["id"]: item["name"] for item in shortlist.get("candidates", [])}
    out["frozen_markets"] = [{"id": key, "name": names.get(key), "backup": key not in shortlist.get("selected_candidate_ids", [])} for key in markets]
    refine_receipt_path = folder / "niche_recommendation_run.json"
    refine_receipt = json.loads(refine_receipt_path.read_text(encoding="utf-8")) if refine_receipt_path.is_file() else {}
    if refine_receipt.get("status") == "success" and refine_receipt.get("shortlist_run_id") == shortlist.get("run_id"):
        state = "refined_ready" if refine_receipt.get("deep_analysis_status") == "ready" else "refinement_pending"
        out["done"].append("refine")
        return {**out, "stage": f"done:{state}", "next": "交付复评报告“市场机会深挖看板-两轮复评.html”；有“无法判断”的结论时说明缺哪项数据"}
    note = "；上次进一步分析失败：" + str(refine_receipt.get("error")) if refine_receipt.get("status") == "failed" else ""
    return {**out, "stage": "recommend:awaiting_keyword_files",
            "next": f"等待用户为 {len(markets)} 个冻结市场各提供 1 份关键词转化表和 1 份卖家精灵关键词反查表（共 {2 * len(markets)} 个），然后运行 refine；不要重跑粗筛{note}"}


def command_status(args: argparse.Namespace) -> None:
    print(json.dumps(project_status(Path(args.project_root)), ensure_ascii=False, indent=2))


def refinable_candidate_ids(shortlist: dict[str, Any]) -> list[str]:
    """Only the formal Top markets go to refinement and the report (user decision 2026-10-03:
    the frozen report format has no backups); backup ids stay in niche_shortlist.json for reference."""
    return list(shortlist.get("selected_candidate_ids", []))


def implementation_hash() -> str:
    names = ("niche_recommendation.py", "niche_refinement_metrics.py", "niche_two_round_report.py", "niche_candidate_pool.py")
    return hashlib.sha256(json_canonical({name: sha256_file(Path(__file__).with_name(name)) for name in names}).encode()).hexdigest()


def verified_shortlist(project: dict[str, Any], path: Path) -> dict[str, Any]:
    expected = project["opportunity_dir"] / "niche_shortlist.json"
    if path.resolve() != expected.resolve():
        fail("复评必须使用当前项目已提交的 niche_shortlist.json")
    result = load_json(path, "第一轮初筛结果")
    receipt = load_json(path.with_name("niche_shortlist_run.json"), "初筛运行回执")
    if result.get("stage") != "shortlist" or result.get("rule_version") != RULE_VERSION or result.get("project_id") != project["project_id"]:
        fail("初筛阶段、规则版本或项目身份不匹配，请重跑初筛")
    if receipt.get("status") != "success" or receipt.get("run_id") != result.get("run_id") or receipt.get("output_hashes", {}).get(path.name) != sha256_file(path):
        fail("初筛回执或结果哈希不匹配，请重跑初筛")
    markets = refinable_candidate_ids(result)
    if not markets or len(markets) > 3 or len(markets) != len(set(markets)) or result.get("target_k") != 3:
        fail("初筛没有可进一步分析的冻结 Top3")
    frozen = result["frozen_inputs"]
    poe_path, definitions_path = frozen_input_path(project, frozen["poe_path"]), frozen_input_path(project, frozen["definitions_path"])
    for label, path in (("商机表", poe_path), ("候选定义", definitions_path)):
        if not path.is_file():
            fail(f"初筛冻结的{label}文件不存在：{path}，请用原文件重跑初筛")
    hashes = input_hashes(project, poe_path, definitions_path)
    hashes["implementation"] = implementation_hash()
    hashes["base_report"] = sha256_file(project["opportunity_dir"] / "市场机会深挖看板.html")
    if hashes != result["input_hashes"]:
        fail("初筛后商品、标签、关键词、商机表、需求定义、基础报告或规则实现发生变化，请重跑初筛")
    return result


def command_run(args: argparse.Namespace) -> None:
    root = Path(args.project_root).expanduser().resolve()
    stage = "refine" if args.command == "refine" else "shortlist"
    started = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        project = load_project(root)
        shortlist = verified_shortlist(project, Path(args.shortlist_result).expanduser().resolve()) if stage == "refine" else None
        poe_path = (frozen_input_path(project, shortlist["frozen_inputs"]["poe_path"]) if shortlist else Path(args.poe_xlsx).expanduser()).resolve()
        definitions_path = (frozen_input_path(project, shortlist["frozen_inputs"]["definitions_path"]) if shortlist else Path(args.definitions).expanduser()).resolve()
        poe = load_poe(poe_path)
        keywords = keyword_source(project["keyword_path"])
        definitions = load_json(definitions_path, "候选定义文件")
        candidates, dispositions, pool_summary = validate_definitions(definitions, project, poe, keywords)
        conversions = None
        if shortlist:
            selected_set = set(refinable_candidate_ids(shortlist))
            candidates = [c for c in candidates if c["id"] in selected_set]
            if candidates != [c for c in shortlist["frozen_candidate_definitions"] if c["id"] in selected_set]:
                fail("初筛需求定义与当前定义不一致，请重跑初筛")
            uploaded = [Path(value).expanduser().resolve() for value in (args.keyword_input_xlsx or [])]
            if args.keyword_conversion_xlsx:
                fail("单文件参数 --keyword-conversion-xlsx 已停用：建议竞价只能来自卖家精灵关键词反查表。" + refinement_file_requirement(len(candidates)))
            if not uploaded:
                fail(refinement_file_requirement(len(candidates)))
            conversions = classify_refinement_keyword_files(uploaded, project["marketplace"], args.conversion_period, len(candidates))
        timings["data_import"] = time.perf_counter() - started
        hashes = input_hashes(project, poe_path, definitions_path)
        hashes["implementation"] = implementation_hash()
        hashes["base_report"] = sha256_file(project["opportunity_dir"] / "市场机会深挖看板.html")
        if shortlist:
            hashes["shortlist_result"] = sha256_file(Path(args.shortlist_result))
            hashes["refinement_keyword_files"] = hashlib.sha256(json_canonical([
                {"kind": "conversion", "sha256": item["sha256"]} for item in conversions["conversion_files"]
            ] + [
                {"kind": "seller_sprite", "sha256": item["sha256"]} for item in conversions["seller_sprite_files"]
            ]).encode()).hexdigest()
            hashes["conversion_period"] = hashlib.sha256(conversions["period"].encode()).hexdigest()
        run_id = run_id_from_hashes(hashes, stage)
        checkpoint = time.perf_counter()
        evaluations, context = candidate_evaluations(project, candidates, keywords, poe, conversions)
        context["candidate_pool"] = pool_summary
        timings.update(context["timings_seconds"])
        checkpoint = time.perf_counter()
        if shortlist:
            frozen_selected_ids, frozen_backup_ids = inherit_shortlist_selection(evaluations, shortlist)
        else:
            frozen_selected_ids = frozen_backup_ids = None
        outputs = build_outputs(project, poe, dispositions, evaluations, context, hashes, run_id, stage, frozen_selected_ids, frozen_backup_ids)
        result, keyword_output, _, _, receipt = outputs
        result["keyword_source_conflicts"] = keywords["main_conflicts"]
        if shortlist:
            result["shortlist_run_id"] = shortlist["run_id"]
            result["keyword_conversion_input"] = refinement_input_summary(conversions)
            result["poe_input"]["primary_score_fields"] = []
            result["poe_input"]["context_only_fields"] = [*POE_CONTEXT_FIELDS, *POE_SEARCH_TREND_FIELDS]
            keyword_output["keyword_source"]["conversion_path"] = [item["path"] for item in conversions["conversion_files"]]
            keyword_output["keyword_source"]["conversion_period"] = conversions["period"]
            keyword_output["keyword_source"]["conversion_sha256"] = [item["sha256"] for item in conversions["conversion_files"]]
            keyword_output["keyword_source"]["seller_sprite_paths"] = [item["path"] for item in conversions["seller_sprite_files"]]
            keyword_output["keyword_source"]["file_association"] = conversions.get("market_mappings", [])
            receipt["shortlist_run_id"] = shortlist["run_id"]
            wait_seconds = max(0, (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(shortlist["generated_at"])).total_seconds())
            receipt["elapsed_since_shortlist_seconds"] = wait_seconds
            receipt["waiting_time_note"] = "两轮间隔单独记录；包含补表及其他间隔，不计入运行耗时。"
        else:
            frozen_dir = project["opportunity_dir"] / FROZEN_INPUT_DIR
            snapshots = {frozen_dir / "poe.xlsx": poe_path.read_bytes(), frozen_dir / "niche_candidate_definitions.json": definitions_path.read_bytes()}
            result["frozen_inputs"] = {"poe_path": f"market_opportunity/{FROZEN_INPUT_DIR}/poe.xlsx",
                                       "definitions_path": f"market_opportunity/{FROZEN_INPUT_DIR}/niche_candidate_definitions.json",
                                       "original_poe_path": str(poe_path), "original_definitions_path": str(definitions_path)}
            selected_set = set(result["selected_candidate_ids"]) | set(result["backup_candidate_ids"])
            result["frozen_candidate_definitions"] = [c for c in candidates if c["id"] in selected_set]
            result["next_stage"] = "awaiting_user_keyword_conversion_table" if refinable_candidate_ids(result) else "pending_verification"
            receipt["elapsed_since_shortlist_seconds"] = None
        timings["selection"] = receipt.pop("selection_seconds")
        timings["output_preparation"] = time.perf_counter() - checkpoint - timings["selection"]
        receipt["timings_seconds"] = timings
        receipt["_start_counter"] = started
        report_path = commit_outputs(project, outputs, shortlist, None if shortlist else snapshots)
        print(json.dumps({"status": "success", "stage": stage, "run_id": run_id,
                          "selected_candidate_ids": result["selected_candidate_ids"], "report": str(report_path),
                          "total_compute_seconds": receipt["total_compute_seconds"]}, ensure_ascii=False))
    except BaseException as exc:
        write_failure_receipt(root, stage, exc)
        if isinstance(exc, RecommendationError):
            raise
        raise RecommendationError(f"细分市场{stage}运行失败：{exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="四项粗筛确定Top3→补关键词转化表→逐市场八项结论")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="只读：判断项目当前阶段与下一步，避免重跑计费或已冻结步骤")
    status.add_argument("--project-root", required=True)
    status.set_defaults(handler=command_status)
    validate = subparsers.add_parser("validate", help="一次列出候选定义与组合审核的全部错误（不写推荐产物）")
    validate.add_argument("--project-root", required=True)
    validate.add_argument("--poe-xlsx", required=True)
    validate.add_argument("--definitions", required=True)
    validate.set_defaults(handler=command_validate)
    prepare = subparsers.add_parser("prepare", help="校验项目和商机Excel，生成候选定义工作区")
    prepare.add_argument("--project-root", required=True)
    prepare.add_argument("--poe-xlsx", required=True)
    prepare.add_argument("--workspace")
    prepare.set_defaults(handler=command_prepare)
    for name in ("shortlist", "run"):
        command = subparsers.add_parser(name, help="四项粗筛直接确定Top3；run为shortlist兼容别名")
        command.add_argument("--project-root", required=True)
        command.add_argument("--poe-xlsx", required=True)
        command.add_argument("--definitions", required=True)
        command.set_defaults(handler=command_run)
    refine = subparsers.add_parser("refine", help="每个冻结市场使用一组关键词转化／卖家精灵表补充八项结论")
    refine.add_argument("--project-root", required=True)
    refine.add_argument("--shortlist-result", required=True)
    refine.add_argument("--keyword-input-xlsx", nargs="+", help="每个冻结市场 2 个文件（Top3 时共 6 个）：关键词转化表和卖家精灵关键词表；顺序不限")
    refine.add_argument("--keyword-conversion-xlsx", help="已停用：竞价只能来自卖家精灵表，请改用 --keyword-input-xlsx")
    refine.add_argument("--conversion-period")
    refine.set_defaults(handler=command_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code = args.handler(args)
    except RecommendationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
