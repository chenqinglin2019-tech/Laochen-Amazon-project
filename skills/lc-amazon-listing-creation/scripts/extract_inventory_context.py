#!/usr/bin/env python3
"""Extract Amazon inventory template and product-sheet context as JSON.

This script uses only the Python standard library. It reads XLSX/XLSM files
directly as Office Open XML so macro-enabled inventory templates are safe to
inspect without rewriting them.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": NS_MAIN, "r": NS_REL, "rel": NS_PKG_REL}
MANUAL_REVIEW_VALUE = "信息不足，请人工核对"


def col_to_num(col: str) -> int:
    n = 0
    for char in col.upper():
        n = n * 26 + ord(char) - 64
    return n


def num_to_col(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def split_addr(addr: str | None) -> tuple[int | None, int | None]:
    match = re.match(r"([A-Z]+)(\d+)", addr or "")
    if not match:
        return None, None
    return col_to_num(match.group(1)), int(match.group(2))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def norm_label(value: str) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).casefold()


def sanitize_defined_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.]", "", value)


def requirement_level(value: str) -> str:
    """Normalize Amazon's localized requirement labels without substring traps."""
    text = norm_label(value)
    if not text:
        return "unspecified"
    if text in {"required", "必填"}:
        return "required"
    if text in {"conditionally required", "conditional required", "有条件必填", "条件必填"}:
        return "conditionally_required"
    if text in {"recommended", "建议", "推荐"}:
        return "recommended"
    if text in {"optional", "可选"}:
        return "optional"
    return "unspecified"


def is_required_status(value: str) -> bool:
    return requirement_level(value) in {"required", "conditionally_required"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class WorkbookReader:
    path: Path
    zip_file: ZipFile
    shared_strings: list[str]
    sheet_paths: dict[str, str]
    sheet_states: dict[str, str]
    defined_names: dict[str, str]

    @classmethod
    def open(cls, path: Path) -> "WorkbookReader":
        zf = ZipFile(path)
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", NS):
                shared_strings.append("".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        sheet_paths: dict[str, str] = {}
        sheet_states: dict[str, str] = {}
        sheets = workbook.find("a:sheets", NS)
        for sheet in list(sheets) if sheets is not None else []:
            rid = sheet.attrib[f"{{{NS_REL}}}id"]
            target = relmap[rid]
            sheet_paths[sheet.attrib["name"]] = "xl/" + target if not target.startswith("/") else target[1:]
            sheet_states[sheet.attrib["name"]] = sheet.attrib.get("state", "visible")

        defined_names: dict[str, str] = {}
        defined_root = workbook.find("a:definedNames", NS)
        if defined_root is not None:
            for item in defined_root.findall("a:definedName", NS):
                name = item.attrib.get("name")
                if name and item.text:
                    defined_names[name] = item.text

        return cls(path, zf, shared_strings, sheet_paths, sheet_states, defined_names)

    def close(self) -> None:
        self.zip_file.close()

    def _cell_value(self, cell: ET.Element) -> str:
        cell_type = cell.attrib.get("t")
        value_el = cell.find("a:v", NS)
        if cell_type == "s" and value_el is not None and value_el.text is not None:
            return self.shared_strings[int(value_el.text)]
        if cell_type == "inlineStr":
            return "".join(t.text or "" for t in cell.iter(f"{{{NS_MAIN}}}t"))
        if cell_type == "b" and value_el is not None:
            return "TRUE" if value_el.text == "1" else "FALSE"
        return value_el.text if value_el is not None and value_el.text is not None else ""

    def sheet_root(self, sheet_name: str) -> ET.Element:
        return ET.fromstring(self.zip_file.read(self.sheet_paths[sheet_name]))

    def sheet_cells(self, sheet_name: str) -> dict[tuple[int, int], str]:
        root = self.sheet_root(sheet_name)
        cells: dict[tuple[int, int], str] = {}
        for row in root.findall("a:sheetData/a:row", NS):
            row_num = int(row.attrib["r"])
            for cell in row.findall("a:c", NS):
                col_num, _ = split_addr(cell.attrib.get("r"))
                if col_num is not None:
                    cells[(row_num, col_num)] = self._cell_value(cell)
        return cells


def find_sheet(workbook: WorkbookReader, names: list[str]) -> str | None:
    by_norm = {norm_label(name): name for name in workbook.sheet_paths}
    for candidate in names:
        found = by_norm.get(norm_label(candidate))
        if found:
            return found
    return None


def parse_range_ref(ref: str) -> tuple[str, int, int, int, int] | None:
    match = re.match(r"'?([^']+)'?!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", ref)
    if not match:
        return None
    sheet, c1, r1, c2, r2 = match.groups()
    return sheet, col_to_num(c1), int(r1), col_to_num(c2 or c1), int(r2 or r1)


def values_from_ref(workbook: WorkbookReader, ref: str, limit: int = 1000) -> list[str]:
    parsed = parse_range_ref(ref)
    if not parsed:
        return []
    sheet, c1, r1, c2, r2 = parsed
    if sheet not in workbook.sheet_paths:
        return []
    cells = workbook.sheet_cells(sheet)
    values: list[str] = []
    seen: set[str] = set()
    for row in range(r1, r2 + 1):
        for col in range(c1, c2 + 1):
            value = clean_text(cells.get((row, col), ""))
            if value and value not in seen:
                seen.add(value)
                values.append(value)
                if len(values) >= limit:
                    return values
    return values


def template_settings(cells: dict[tuple[int, int], str]) -> dict[str, int]:
    settings = " ".join(value for (row, _), value in cells.items() if row == 1)
    out = {"labelRow": 4, "attributeRow": 5, "dataRow": 7}
    for key in list(out):
        match = re.search(rf"{key}=([0-9]+)", settings)
        if match:
            out[key] = int(match.group(1))
    return out


def max_col_for_row(cells: dict[tuple[int, int], str], row: int) -> int:
    cols = [col for (r, col), value in cells.items() if r == row and clean_text(value)]
    return max(cols, default=0)


def parse_template(workbook: WorkbookReader) -> dict[str, Any]:
    sheet_name = find_sheet(workbook, ["Template", "模板"])
    if not sheet_name:
        raise SystemExit(f"Could not find Template/模板 sheet in {workbook.path}")
    cells = workbook.sheet_cells(sheet_name)
    settings = template_settings(cells)
    label_row = settings["labelRow"]
    attr_row = settings["attributeRow"]
    max_col = max(max_col_for_row(cells, label_row), max_col_for_row(cells, attr_row))

    groups: dict[int, str] = {}
    current_group = ""
    for col in range(1, max_col + 1):
        group = clean_text(cells.get((label_row - 1, col), ""))
        if group:
            current_group = group
        groups[col] = current_group

    fields: dict[str, dict[str, Any]] = {}
    column_fields: list[dict[str, Any]] = []
    for col in range(1, max_col + 1):
        field_name = clean_text(cells.get((attr_row, col), ""))
        label = clean_text(cells.get((label_row, col), ""))
        if not field_name and not label:
            continue
        item = {
            "field": field_name,
            "label": label,
            "column": num_to_col(col),
            "column_index": col,
            "group": groups.get(col, ""),
        }
        column_fields.append(item)
        if field_name:
            fields[field_name] = item

    return {
        "sheet_name": sheet_name,
        "settings": settings,
        "fields": fields,
        "columns": column_fields,
    }


def schema_fingerprint(template: dict[str, Any]) -> str:
    ordered = [item["field"] for item in template["columns"] if item.get("field")]
    return hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()


def _settings_query(workbook: WorkbookReader) -> dict[str, list[str]]:
    chunks: list[tuple[int, str]] = []
    for value in workbook.shared_strings:
        match = re.match(r"settings(\d*)=(.*)", value, re.DOTALL)
        if match:
            index = int(match.group(1) or "1")
            chunks.append((index, match.group(2)))
    if not chunks:
        return {}
    payload = "".join(value for _, value in sorted(chunks))
    return parse_qs(payload, keep_blank_values=True)


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    return unquote(values[0]) if values else ""


def _decode_browse_classifications(encoded: str) -> tuple[list[str], list[str]]:
    if not encoded:
        return [], []
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.b64decode(encoded + padding).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return [], []
    product_types: list[str] = []
    nodes: list[str] = []
    for item in payload if isinstance(payload, list) else []:
        product_type = clean_text(item.get("productType")) if isinstance(item, dict) else ""
        if product_type and product_type not in product_types:
            product_types.append(product_type)
        for node in item.get("browseClassificationKeys", []) if isinstance(item, dict) else []:
            node = clean_text(node)
            if node and node not in nodes:
                nodes.append(node)
    return product_types, nodes


def workbook_metadata(workbook: WorkbookReader, template: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract stable matching metadata; templateIdentifier is trace-only."""
    template = template or parse_template(workbook)
    query = _settings_query(workbook)
    product_types, nodes = _decode_browse_classifications(_first(query, "browseClassifications"))
    if not product_types:
        product_types = dropdown_values_for_field(workbook, "", "product_type#1.value")
    marketplace = _first(query, "primaryMarketplaceId")
    if marketplace.startswith("amzn1.mp.o."):
        marketplace = marketplace.removeprefix("amzn1.mp.o.")
    if not marketplace:
        for field in template["fields"]:
            match = re.search(r"marketplace_id=([^\]]+)", field)
            if match:
                marketplace = match.group(1)
                break
    return {
        "marketplace": marketplace,
        "content_language": _first(query, "contentLanguageTag"),
        "header_language": _first(query, "headerLanguageTag"),
        "product_types": product_types,
        "browse_nodes": nodes,
        "version": _first(query, "Version"),
        "downloaded_at": _first(query, "timestamp"),
        "template_identifier": _first(query, "templateIdentifier"),
        "file_sha256": sha256_file(workbook.path),
        "schema_fingerprint": schema_fingerprint(template),
        "technical_field_count": len(template["fields"]),
    }


def parse_data_definitions(workbook: WorkbookReader) -> dict[str, dict[str, str]]:
    sheet_name = find_sheet(workbook, ["Data Definitions", "数据定义"])
    if not sheet_name:
        return {}
    cells = workbook.sheet_cells(sheet_name)
    max_row = max((row for row, _ in cells), default=0)
    definitions: dict[str, dict[str, str]] = {}
    current_group = ""
    for row in range(3, max_row + 1):
        group = clean_text(cells.get((row, 1), ""))
        if group:
            current_group = group
        field = clean_text(cells.get((row, 2), ""))
        if not field:
            continue
        definitions[field] = {
            "group": current_group,
            "label": clean_text(cells.get((row, 3), "")),
            "accepted_values_rule": clean_text(cells.get((row, 4), "")),
            "example": clean_text(cells.get((row, 5), "")),
            "required": clean_text(cells.get((row, 6), "")),
        }
    return definitions


def parse_valid_values(workbook: WorkbookReader) -> dict[str, list[str]]:
    sheet_name = find_sheet(workbook, ["Valid Values", "有效值"])
    if not sheet_name:
        return {}
    cells = workbook.sheet_cells(sheet_name)
    max_row = max((row for row, _ in cells), default=0)
    max_col = max((col for _, col in cells), default=0)
    out: dict[str, list[str]] = {}
    for row in range(1, max_row + 1):
        label = clean_text(cells.get((row, 2), ""))
        if " - [" not in label:
            continue
        base_label = label.split(" - [", 1)[0].strip()
        values = [clean_text(cells.get((row, col), "")) for col in range(3, max_col + 1)]
        values = [value for value in values if value]
        if values:
            out[base_label] = values
    return out


def dropdown_values_for_field(workbook: WorkbookReader, product_type: str, field: str) -> list[str]:
    names_to_try: list[str] = []
    if field == "product_type#1.value":
        names_to_try.append("product_type1.value")
    names_to_try.append(sanitize_defined_name(product_type + field))
    names_to_try.append(sanitize_defined_name(field))
    for name in names_to_try:
        ref = workbook.defined_names.get(name)
        if ref:
            values = values_from_ref(workbook, ref)
            if values:
                return values
    return []


MINIMUM_PRODUCT_HEADERS = ("父子变体", "标题", "产品详细介绍")

PRODUCT_HEADER_ALIASES = {
    "brand": ("品牌", "品牌名", "Brand", "Brand Name"),
    "model_name": ("型号名称", "Model Name", "产品型号名称"),
    "part_number": ("零件编号", "Part Number", "Part No", "Part No."),
    "number_of_items": (
        "销售件数",
        "装数",
        "包装数量",
        "Number of Items",
        "Pack Count",
    ),
    "mounting_type": ("安装方式", "摆放方式", "Mounting Type"),
    "fulfillment_method": (
        "发货方式",
        "物流渠道",
        "配送方式",
        "Fulfillment Method",
        "Fulfillment Channel",
    ),
    "core_keyword": (
        "商品核心关键词",
        "产品核心关键词",
        "核心关键词",
        "Core Keyword",
        "Product Core Keyword",
    ),
    "list_price": ("售价", "销售价格", "List Price", "Price"),
    "item_length": ("商品长度", "产品长度", "Item Length", "Product Length"),
    "item_width": ("商品宽度", "产品宽度", "Item Width", "Product Width"),
    "item_height": ("商品高度", "产品高度", "Item Height", "Product Height"),
    "item_dimension_unit": (
        "商品尺寸单位",
        "产品尺寸单位",
        "Item Dimension Unit",
        "Product Dimension Unit",
    ),
    "item_dimensions": ("商品尺寸", "产品尺寸", "Item Dimensions", "Product Dimensions"),
    "item_weight": ("商品重量", "产品重量", "Item Weight", "Product Weight"),
    "item_weight_unit": ("商品重量单位", "产品重量单位", "Item Weight Unit", "Product Weight Unit"),
    "package_length": ("包装长度", "Package Length", "Item Package Length"),
    "package_width": ("包装宽度", "Package Width", "Item Package Width"),
    "package_height": ("包装高度", "Package Height", "Item Package Height"),
    "package_dimension_unit": ("包装尺寸单位", "Package Dimension Unit"),
    "package_dimensions": ("包装尺寸", "Package Dimensions", "Item Package Dimensions"),
    "package_weight": ("包装重量", "Package Weight", "Item Package Weight"),
    "package_weight_unit": ("包装重量单位", "Package Weight Unit", "Item Package Weight Unit"),
}

RULE_DEFAULT_FIELD_NEEDLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("condition", ("condition_type",)),
    ("model_number", ("model_number",)),
    ("model_name", ("model_name",)),
    ("manufacturer", ("manufacturer[",)),
    ("number_of_items", ("number_of_items",)),
    ("part_number", ("part_number",)),
    ("mounting_type", ("mounting_type",)),
    ("fulfillment", ("fulfillment_channel_code",)),
)

LENGTH_FACTORS_TO_INCHES = {
    "mm": Decimal("0.0393700787401575"),
    "millimeter": Decimal("0.0393700787401575"),
    "millimeters": Decimal("0.0393700787401575"),
    "毫米": Decimal("0.0393700787401575"),
    "cm": Decimal("0.393700787401575"),
    "centimeter": Decimal("0.393700787401575"),
    "centimeters": Decimal("0.393700787401575"),
    "厘米": Decimal("0.393700787401575"),
    "m": Decimal("39.3700787401575"),
    "meter": Decimal("39.3700787401575"),
    "meters": Decimal("39.3700787401575"),
    "米": Decimal("39.3700787401575"),
    "in": Decimal("1"),
    "inch": Decimal("1"),
    "inches": Decimal("1"),
    "\"": Decimal("1"),
    "英寸": Decimal("1"),
}

WEIGHT_FACTORS_TO_POUNDS = {
    "g": Decimal("0.00220462262184878"),
    "gram": Decimal("0.00220462262184878"),
    "grams": Decimal("0.00220462262184878"),
    "克": Decimal("0.00220462262184878"),
    "kg": Decimal("2.20462262184878"),
    "kilogram": Decimal("2.20462262184878"),
    "kilograms": Decimal("2.20462262184878"),
    "千克": Decimal("2.20462262184878"),
    "公斤": Decimal("2.20462262184878"),
    "oz": Decimal("0.0625"),
    "ounce": Decimal("0.0625"),
    "ounces": Decimal("0.0625"),
    "盎司": Decimal("0.0625"),
    "lb": Decimal("1"),
    "lbs": Decimal("1"),
    "pound": Decimal("1"),
    "pounds": Decimal("1"),
    "磅": Decimal("1"),
}


def parse_product_sheet(workbook: WorkbookReader) -> dict[str, Any]:
    visible = [name for name, state in workbook.sheet_states.items() if state == "visible"]
    sheet_name = visible[0] if visible else next(iter(workbook.sheet_paths))
    cells = workbook.sheet_cells(sheet_name)
    max_row = max((row for row, _ in cells), default=0)
    max_col = max((col for _, col in cells), default=0)
    headers = [clean_text(cells.get((1, col), "")) for col in range(1, max_col + 1)]
    rows: list[dict[str, Any]] = []
    for row in range(2, max_row + 1):
        values = {headers[col - 1] or num_to_col(col): clean_text(cells.get((row, col), "")) for col in range(1, max_col + 1)}
        if any(values.values()):
            rows.append({
                "row_number": row,
                "values": values,
                "cell_references": {
                    headers[col - 1] or num_to_col(col): f"{sheet_name}!{num_to_col(col)}{row}"
                    for col in range(1, max_col + 1)
                },
            })
    expected = [
        "父子变体", "标题", "副标题", "关键词栏", "五点描述1", "五点描述2", "五点描述3", "五点描述4", "五点描述5",
        "长描", "主图链接", "附图1链接", "附图2链接", "附图3链接", "附图4链接", "附图5链接", "附图6链接", "附图7链接",
        "Swatch Image链接", "产品详细介绍", "商品编号类型", "商品ID",
    ]
    return {
        "sheet_name": sheet_name,
        "headers": headers,
        "column_references": {
            headers[col - 1] or num_to_col(col): f"{sheet_name}!{num_to_col(col)}"
            for col in range(1, max_col + 1)
        },
        "missing_expected_headers": [header for header in expected if header not in headers],
        "minimum_required_headers": list(MINIMUM_PRODUCT_HEADERS),
        "missing_required_headers": [
            header for header in MINIMUM_PRODUCT_HEADERS if header not in headers
        ],
        "rows": rows,
    }


def normalize_product_header(value: str) -> str:
    return re.sub(r"[\s_\-:/（）()\[\]]+", "", clean_text(value)).casefold()


def product_row_value(
    row: dict[str, Any], alias_key: str
) -> tuple[str, str | None]:
    aliases = {
        normalize_product_header(value)
        for value in PRODUCT_HEADER_ALIASES[alias_key]
    }
    values = row.get("values") or {}
    references = row.get("cell_references") or {}
    for header, value in values.items():
        if normalize_product_header(header) in aliases and clean_text(value):
            return clean_text(value), references.get(header)
    return "", None


def _decimal_text(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(quantized, "f").rstrip("0").rstrip(".") or "0"


def _number_and_optional_unit(value: str) -> tuple[Decimal | None, str]:
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z\u4e00-\u9fff\"]*)\s*",
        clean_text(value),
    )
    if not match:
        return None, ""
    try:
        return Decimal(match.group(1)), match.group(2).casefold()
    except InvalidOperation:
        return None, ""


def _convert_measurement(value: str, unit: str, kind: str) -> str | None:
    number, embedded_unit = _number_and_optional_unit(value)
    if number is None:
        return None
    effective_unit = clean_text(unit).casefold() or embedded_unit
    factors = LENGTH_FACTORS_TO_INCHES if kind == "length" else WEIGHT_FACTORS_TO_POUNDS
    factor = factors.get(effective_unit)
    if factor is None:
        return None
    return _decimal_text(number * factor)


def _parse_dimension_triplet(value: str, separate_unit: str) -> tuple[list[str], str] | None:
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*[x×*]\s*"
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*[x×*]\s*"
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z\u4e00-\u9fff\"]*)\s*",
        clean_text(value),
        re.IGNORECASE,
    )
    if not match:
        return None
    unit = clean_text(separate_unit).casefold() or clean_text(match.group(4)).casefold()
    converted = [
        _convert_measurement(match.group(index), unit, "length")
        for index in range(1, 4)
    ]
    if any(item is None for item in converted):
        return None
    return [str(item) for item in converted], unit


def _role_from_product_row(row: dict[str, Any]) -> str:
    value = norm_label((row.get("values") or {}).get("父子变体", ""))
    if value.startswith("父") or value == "parent":
        return "Parent"
    if value.startswith("子") or value == "child":
        return "Child"
    return "Standalone"


def _measurement_source(
    row: dict[str, Any],
    value_key: str,
    unit_key: str,
    kind: str,
) -> dict[str, Any] | None:
    value, value_ref = product_row_value(row, value_key)
    unit, unit_ref = product_row_value(row, unit_key)
    if not value:
        return None
    converted = _convert_measurement(value, unit, kind)
    if converted is None:
        return {
            "status": "missing_or_invalid_unit",
            "references": [item for item in (value_ref, unit_ref) if item],
        }
    return {
        "status": "resolved",
        "value": converted,
        "references": [item for item in (value_ref, unit_ref) if item],
    }


def _dimension_sources(
    row: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    composite_key = "item_dimensions" if prefix == "item" else "package_dimensions"
    unit_key = "item_dimension_unit" if prefix == "item" else "package_dimension_unit"
    composite, composite_ref = product_row_value(row, composite_key)
    separate_unit, unit_ref = product_row_value(row, unit_key)
    if composite:
        parsed = _parse_dimension_triplet(composite, separate_unit)
        if parsed is None:
            return {
                "status": "missing_or_invalid_unit",
                "references": [item for item in (composite_ref, unit_ref) if item],
            }
        values, _ = parsed
        return {
            "status": "resolved",
            "length": values[0],
            "width": values[1],
            "height": values[2],
            "references": [item for item in (composite_ref, unit_ref) if item],
        }

    result: dict[str, Any] = {"status": "resolved", "references": []}
    found = False
    for dimension in ("length", "width", "height"):
        value, value_ref = product_row_value(row, f"{prefix}_{dimension}")
        if not value:
            result[dimension] = None
            continue
        found = True
        converted = _convert_measurement(value, separate_unit, "length")
        if converted is None:
            result["status"] = "missing_or_invalid_unit"
        result[dimension] = converted
        result["references"].extend(
            item for item in (value_ref, unit_ref) if item and item not in result["references"]
        )
    if not found:
        result["status"] = "missing"
    return result


def _technical_field(template: dict[str, Any], *needles: str) -> str | None:
    return _first_matching_field(template, *needles)


def policy_rule_default_fields(
    template: dict[str, Any], roles: list[str]
) -> dict[str, list[str]]:
    """Return Mapping 2.2 policy-controlled fields by applicable row role."""
    resolved = {
        name: _technical_field(template, *needles)
        for name, needles in RULE_DEFAULT_FIELD_NEEDLES
    }
    output: dict[str, list[str]] = {}
    for role in roles:
        fields: list[str] = []
        if resolved.get("condition"):
            fields.append(str(resolved["condition"]))
        if role in {"Child", "Standalone"}:
            fields.extend(
                str(resolved[name])
                for name, _ in RULE_DEFAULT_FIELD_NEEDLES
                if name != "condition" and resolved.get(name)
            )
        output[role] = fields
    return output


def _content_references(row: dict[str, Any]) -> list[str]:
    references = row.get("cell_references") or {}
    values = row.get("values") or {}
    preferred_headers = (
        "标题",
        "副标题",
        "关键词栏",
        "五点描述1",
        "五点描述2",
        "五点描述3",
        "五点描述4",
        "五点描述5",
        "长描",
        "产品详细介绍",
    )
    return [
        references[header]
        for header in preferred_headers
        if clean_text(values.get(header, "")) and references.get(header)
    ]


def _allowed_candidates(
    field: str | None,
    valid_values_by_field: dict[str, list[str]] | None,
    dropdown_values_by_field: dict[str, list[str]] | None,
) -> list[str]:
    if not field:
        return []
    output: list[str] = []
    for source in (dropdown_values_by_field or {}, valid_values_by_field or {}):
        for value in source.get(field, []):
            value = clean_text(value)
            if value and value not in output:
                output.append(value)
    return output


def _candidate_by_semantics(candidates: list[str], semantic: str) -> str | None:
    normalized = semantic.casefold()
    aliases = {
        "fba": ("fulfillment by amazon", "amazon logistics", "亚马逊物流", "amazon_na"),
        "mfn": ("fulfillment by merchant", "merchant fulfilled", "卖家自行配送", "default"),
        "inches": ("inch", "inches", "英寸"),
        "pounds": ("pound", "pounds", "lb", "lbs", "磅"),
        "ounces": ("ounce", "ounces", "oz", "盎司"),
    }
    needles = aliases.get(normalized, (normalized,))
    for candidate in candidates:
        folded = candidate.casefold()
        if any(needle in folded for needle in needles):
            return candidate
    return None


def _map_explicit_candidate(value: str, candidates: list[str]) -> str | None:
    normalized = norm_label(value)
    for candidate in candidates:
        if norm_label(candidate) == normalized:
            return candidate
    if any(token in normalized for token in ("fba", "amazon", "亚马逊物流")):
        return _candidate_by_semantics(candidates, "fba")
    if any(token in normalized for token in ("mfn", "merchant", "卖家", "自发货")):
        return _candidate_by_semantics(candidates, "mfn")
    return None


def _parse_pack_count(row: dict[str, Any]) -> dict[str, Any]:
    explicit, explicit_ref = product_row_value(row, "number_of_items")
    sources: list[tuple[str, str | None]] = []
    if explicit:
        sources.append((explicit, explicit_ref))
    else:
        values = row.get("values") or {}
        refs = row.get("cell_references") or {}
        for header in ("标题", "副标题", "产品详细介绍", "长描"):
            if clean_text(values.get(header, "")):
                sources.append((clean_text(values[header]), refs.get(header)))
    patterns = (
        r"(?<!\d)(\d{1,4})\s*(?:pcs?|pieces?|pack|count)(?![a-z])",
        r"(?:pack|set)\s+of\s+(\d{1,4})(?!\d)",
        r"(?<!\d)(\d{1,4})\s*个装",
    )
    matches: list[tuple[int, str | None]] = []
    for text, reference in sources:
        stripped = clean_text(text)
        if explicit and re.fullmatch(r"\d+", stripped):
            matches.append((int(stripped), reference))
            break
        for pattern in patterns:
            found = re.search(pattern, stripped, re.IGNORECASE)
            if found:
                matches.append((int(found.group(1)), reference))
                break
    unique = {count for count, _ in matches if count > 0}
    if len(unique) == 1:
        count = next(iter(unique))
        return {
            "status": "resolved",
            "value": str(count),
            "references": [ref for value, ref in matches if value == count and ref],
            "defaulted": False,
        }
    if len(unique) > 1:
        return {
            "status": "conflicting_pack_counts",
            "references": [ref for _, ref in matches if ref],
        }
    return {"status": "resolved", "value": "1", "references": [], "defaulted": True}


def _weight_value_for_unit(pounds_value: str, semantic_unit: str) -> str:
    value = Decimal(pounds_value)
    if semantic_unit == "ounces":
        value *= Decimal("16")
    return _decimal_text(value)


def _select_weight_semantic_unit(
    pounds_value: str,
    unit_fields: list[str | None],
    valid_values_by_field: dict[str, list[str]] | None,
    dropdown_values_by_field: dict[str, list[str]] | None,
) -> str | None:
    supported: set[str] | None = None
    for field in unit_fields:
        if not field:
            continue
        candidates = _allowed_candidates(field, valid_values_by_field, dropdown_values_by_field)
        field_supported = {
            semantic
            for semantic in ("pounds", "ounces")
            if _candidate_by_semantics(candidates, semantic)
        }
        supported = field_supported if supported is None else supported & field_supported
    supported = supported or set()
    if "pounds" in supported and "ounces" in supported:
        return "ounces" if Decimal(pounds_value) < 1 else "pounds"
    if "pounds" in supported:
        return "pounds"
    if "ounces" in supported:
        return "ounces"
    return None


def product_resolution_hints(
    product: dict[str, Any] | None,
    template: dict[str, Any],
    sample_preferred: dict[str, list[str]],
    valid_values_by_field: dict[str, list[str]] | None = None,
    dropdown_values_by_field: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Resolve deterministic defaults and physical measurements without inventing facts."""
    controlled_fields = {
        name: _technical_field(template, *needles)
        for name, needles in RULE_DEFAULT_FIELD_NEEDLES
    }
    condition_field = controlled_fields["condition"]
    item_fields = {
        # User L×W×H semantics: width input is front-to-back depth; length input is side-to-side width.
        "length": _technical_field(template, "item_depth_width_height", "width.value"),
        "width": _technical_field(template, "item_depth_width_height", "depth.value"),
        "height": _technical_field(template, "item_depth_width_height", "height.value"),
        "length_unit": _technical_field(template, "item_depth_width_height", "width.unit"),
        "width_unit": _technical_field(template, "item_depth_width_height", "depth.unit"),
        "height_unit": _technical_field(template, "item_depth_width_height", "height.unit"),
        "weight": _technical_field(template, "item_weight", "#1.value"),
        "weight_unit": _technical_field(template, "item_weight", "#1.unit"),
        "normalized_weight": _technical_field(template, "item_weight", "normalized_value.value"),
        "normalized_weight_unit": _technical_field(template, "item_weight", "normalized_value.unit"),
    }
    package_fields = {
        "length": _technical_field(template, "item_package_dimensions", "length.value"),
        "width": _technical_field(template, "item_package_dimensions", "width.value"),
        "height": _technical_field(template, "item_package_dimensions", "height.value"),
        "length_unit": _technical_field(template, "item_package_dimensions", "length.unit"),
        "width_unit": _technical_field(template, "item_package_dimensions", "width.unit"),
        "height_unit": _technical_field(template, "item_package_dimensions", "height.unit"),
        "weight": _technical_field(template, "item_package_weight", "#1.value"),
        "weight_unit": _technical_field(template, "item_package_weight", "#1.unit"),
    }
    roles = product_roles(product)
    role_defaults = policy_rule_default_fields(template, roles)

    output_rows: list[dict[str, Any]] = []
    for row in (product or {}).get("rows", []):
        role = _role_from_product_row(row)
        hints: list[dict[str, Any]] = []
        def measurement_decision(field: str) -> str:
            return (
                "sample_preferred"
                if field in set(sample_preferred.get(role, []))
                else "evidence_fillable"
            )

        if condition_field:
            hints.append({
                "field": condition_field,
                "value": "New",
                "decision_set": "rule_default",
                "source_type": "business_rule",
                "source_reference": "rule:item-condition-new",
                "status": "resolved",
            })
        if role in {"Child", "Standalone"}:
            content_references = _content_references(row)

            list_price_field = _technical_field(template, "list_price", "#1.value")
            list_price_value, list_price_ref = product_row_value(row, "list_price")
            if list_price_field and list_price_value:
                hints.append({
                    "field": list_price_field,
                    "value": list_price_value,
                    "decision_set": measurement_decision(list_price_field),
                    "source_type": "product_cell",
                    "source_reference": list_price_ref,
                    "status": "resolved",
                })

            model_number_field = controlled_fields.get("model_number")
            if model_number_field:
                hints.append({
                    "field": model_number_field,
                    "decision_set": "rule_default",
                    "source_type": "business_rule",
                    "source_reference": "rule:model-number-equals-sku",
                    "value_from_field": "contribution_sku#1.value",
                    "status": "requires_mapping_field",
                })

            manufacturer_field = controlled_fields.get("manufacturer")
            if manufacturer_field:
                hints.append({
                    "field": manufacturer_field,
                    "decision_set": "rule_default",
                    "source_type": "business_rule",
                    "source_reference": "rule:manufacturer-equals-brand",
                    "value_from_field": _technical_field(template, "brand["),
                    "status": "requires_mapping_field",
                })

            for alias_key, field_key, rule_id in (
                ("model_name", "model_name", "rule:model-name-core-keyword-fallback"),
                ("part_number", "part_number", "rule:part-number-core-keyword-fallback"),
            ):
                target = controlled_fields.get(field_key)
                if not target:
                    continue
                explicit_value, explicit_ref = product_row_value(row, alias_key)
                core_value, core_ref = product_row_value(row, "core_keyword")
                if explicit_value:
                    hints.append({
                        "field": target,
                        "value": explicit_value,
                        "decision_set": "rule_default",
                        "source_type": "product_cell",
                        "source_reference": explicit_ref,
                        "status": "resolved_explicit",
                    })
                elif core_value:
                    hints.append({
                        "field": target,
                        "value": core_value,
                        "decision_set": "rule_default",
                        "source_type": "model_rule",
                        "source_reference": core_ref,
                        "rule_id": rule_id,
                        "status": "resolved_core_keyword",
                    })
                else:
                    hints.append({
                        "field": target,
                        "decision_set": "rule_default",
                        "source_type": "model_rule",
                        "source_reference": content_references,
                        "rule_id": rule_id,
                        "status": "requires_core_keyword_derivation",
                    })

            number_field = controlled_fields.get("number_of_items")
            if number_field:
                pack = _parse_pack_count(row)
                hints.append({
                    "field": number_field,
                    "value": pack.get("value"),
                    "decision_set": "rule_default",
                    "source_type": "business_rule" if pack.get("defaulted") else "model_extracted",
                    "source_reference": (
                        "rule:number-of-items-default-one"
                        if pack.get("defaulted")
                        else pack.get("references", [])
                    ),
                    "status": pack["status"],
                })

            fulfillment_field = controlled_fields.get("fulfillment")
            if fulfillment_field:
                candidates = _allowed_candidates(
                    fulfillment_field, valid_values_by_field, dropdown_values_by_field
                )
                explicit_value, explicit_ref = product_row_value(row, "fulfillment_method")
                selected = (
                    _map_explicit_candidate(explicit_value, candidates)
                    if explicit_value
                    else _candidate_by_semantics(candidates, "fba")
                )
                hints.append({
                    "field": fulfillment_field,
                    "value": selected,
                    "decision_set": "rule_default",
                    "source_type": "model_extracted" if explicit_value else "business_rule",
                    "source_reference": (
                        explicit_ref if explicit_value else "rule:fulfillment-default-fba"
                    ),
                    "status": "resolved" if selected else "target_candidate_missing",
                    "allowed_values": candidates,
                })

            mounting_field = controlled_fields.get("mounting_type")
            if mounting_field:
                candidates = _allowed_candidates(
                    mounting_field, valid_values_by_field, dropdown_values_by_field
                )
                explicit_value, explicit_ref = product_row_value(row, "mounting_type")
                selected = _map_explicit_candidate(explicit_value, candidates) if explicit_value else None
                hints.append({
                    "field": mounting_field,
                    "value": selected,
                    "decision_set": "rule_default",
                    "source_type": "model_extracted" if explicit_value else "model_rule",
                    "source_reference": explicit_ref if explicit_value else content_references,
                    "rule_id": "rule:mounting-type-enum-selection",
                    "status": "resolved_explicit" if selected else "requires_enum_selection",
                    "allowed_values": candidates,
                })

            item_dimensions = _dimension_sources(row, "item")
            package_dimensions = _dimension_sources(row, "package")
            item_weight = _measurement_source(row, "item_weight", "item_weight_unit", "weight")
            package_weight = _measurement_source(
                row, "package_weight", "package_weight_unit", "weight"
            )
            if package_dimensions["status"] in {"missing", "resolved"}:
                for dimension in ("length", "width", "height"):
                    if not package_dimensions.get(dimension) and item_dimensions.get(dimension):
                        package_dimensions[dimension] = item_dimensions[dimension]
                        package_dimensions["references"] = list(item_dimensions["references"])
                        package_dimensions["fallback_from_product"] = True
            if package_weight is None and item_weight and item_weight.get("status") == "resolved":
                package_weight = {
                    **item_weight,
                    "fallback_from_product": True,
                }

            for dimension in ("length", "width", "height"):
                value = item_dimensions.get(dimension)
                field = item_fields[dimension]
                unit_field = item_fields[f"{dimension}_unit"]
                if field and unit_field and value:
                    unit_value = _candidate_by_semantics(
                        _allowed_candidates(
                            unit_field, valid_values_by_field, dropdown_values_by_field
                        ),
                        "inches",
                    ) or "Inches"
                    for target, payload in ((field, value), (unit_field, unit_value)):
                        hints.append({
                            "field": target,
                            "value": payload,
                            "decision_set": measurement_decision(target),
                            "source_type": "model_extracted",
                            "source_reference": item_dimensions["references"],
                            "status": "resolved",
                        })
                elif field and unit_field and field in set(sample_preferred.get(role, [])):
                    # The user explicitly fixed all item-dimension target units to Inches.
                    unit_value = _candidate_by_semantics(
                        _allowed_candidates(
                            unit_field, valid_values_by_field, dropdown_values_by_field
                        ),
                        "inches",
                    )
                    if unit_value:
                        hints.append({
                            "field": unit_field,
                            "value": unit_value,
                            "decision_set": measurement_decision(unit_field),
                            "source_type": "business_rule",
                            "source_reference": "rule:item-dimension-unit-inches",
                            "status": "resolved_default_unit",
                        })
                value = package_dimensions.get(dimension)
                field = package_fields[dimension]
                unit_field = package_fields[f"{dimension}_unit"]
                if field and unit_field and value:
                    unit_value = _candidate_by_semantics(
                        _allowed_candidates(
                            unit_field, valid_values_by_field, dropdown_values_by_field
                        ),
                        "inches",
                    ) or "Inches"
                    for target, payload in ((field, value), (unit_field, unit_value)):
                        hints.append({
                            "field": target,
                            "value": payload,
                            "decision_set": measurement_decision(target),
                            "source_type": "model_extracted",
                            "source_reference": package_dimensions["references"],
                            "status": "fallback_from_product"
                            if package_dimensions.get("fallback_from_product")
                            else "resolved",
                        })
            if item_weight and item_weight.get("status") == "resolved":
                semantic_unit = _select_weight_semantic_unit(
                    item_weight["value"],
                    [item_fields["weight_unit"], item_fields["normalized_weight_unit"]],
                    valid_values_by_field,
                    dropdown_values_by_field,
                )
                converted_value = (
                    _weight_value_for_unit(item_weight["value"], semantic_unit)
                    if semantic_unit
                    else None
                )
                weight_unit = _candidate_by_semantics(
                    _allowed_candidates(
                        item_fields["weight_unit"], valid_values_by_field, dropdown_values_by_field
                    ),
                    semantic_unit or "",
                )
                normalized_unit = _candidate_by_semantics(
                    _allowed_candidates(
                        item_fields["normalized_weight_unit"],
                        valid_values_by_field,
                        dropdown_values_by_field,
                    ),
                    semantic_unit or "",
                )
                for target, payload in (
                    (item_fields["weight"], converted_value),
                    (item_fields["weight_unit"], weight_unit),
                    (item_fields["normalized_weight"], converted_value),
                    (item_fields["normalized_weight_unit"], normalized_unit),
                ):
                    if target:
                        hints.append({
                            "field": target,
                            "value": payload,
                            "decision_set": measurement_decision(target),
                            "source_type": "model_extracted",
                            "source_reference": item_weight["references"],
                            "status": "resolved" if payload is not None else "target_unit_missing",
                        })
            if package_weight and package_weight.get("status") == "resolved":
                semantic_unit = _select_weight_semantic_unit(
                    package_weight["value"],
                    [package_fields["weight_unit"]],
                    valid_values_by_field,
                    dropdown_values_by_field,
                )
                converted_value = (
                    _weight_value_for_unit(package_weight["value"], semantic_unit)
                    if semantic_unit
                    else None
                )
                package_unit = _candidate_by_semantics(
                    _allowed_candidates(
                        package_fields["weight_unit"], valid_values_by_field, dropdown_values_by_field
                    ),
                    semantic_unit or "",
                )
                for target, payload in (
                    (package_fields["weight"], converted_value),
                    (package_fields["weight_unit"], package_unit),
                ):
                    if target:
                        hints.append({
                            "field": target,
                            "value": payload,
                            "decision_set": measurement_decision(target),
                            "source_type": "model_extracted",
                            "source_reference": package_weight["references"],
                            "status": (
                                "target_unit_missing"
                                if payload is None
                                else "fallback_from_product"
                                if package_weight.get("fallback_from_product")
                                else "resolved"
                            ),
                        })

        resolved_fields = {
            item["field"] for item in hints
            if item.get("value") is not None and item.get("status", "").startswith("resolved")
            or item.get("status") == "fallback_from_product"
        }
        manual_candidates = [
            field
            for field in sample_preferred.get(role, [])
            if field not in resolved_fields
        ]
        output_rows.append({
            "source_row": row["row_number"],
            "role": role,
            "hints": hints,
            "manual_review_candidates": manual_candidates,
        })
    return {
        "manual_review_value": MANUAL_REVIEW_VALUE,
        "rule_default": role_defaults,
        "rows": output_rows,
    }


def sample_field_expectations(
    reference_profile: dict[str, Any] | None,
    definitions: dict[str, dict[str, str]],
    valid_by_field: dict[str, list[str]],
    dropdown_by_field: dict[str, list[str]],
) -> list[dict[str, Any]]:
    if not reference_profile or not reference_profile.get("eligible_for_learning"):
        return []
    output: list[dict[str, Any]] = []
    for profile in reference_profile.get("profiles", []):
        fields = []
        for item in profile.get("filled_fields", []):
            field = item["field"]
            fields.append({
                **item,
                "data_definition": definitions.get(field, {}),
                "allowed_values": valid_by_field.get(field)
                or dropdown_by_field.get(field)
                or [],
            })
        output.append({
            "role": profile["role"],
            "variation_theme": profile["variation_theme"],
            "row_count": profile["row_count"],
            "fields": fields,
        })
    return output


def _matching_fields(template: dict[str, Any], *needles: str) -> list[str]:
    return [
        field for field in template["fields"]
        if all(needle.casefold() in field.casefold() for needle in needles)
    ]


def _first_matching_field(template: dict[str, Any], *needles: str) -> str | None:
    matches = _matching_fields(template, *needles)
    return matches[0] if matches else None


def _row_role(values: dict[str, str], template: dict[str, Any]) -> str:
    field = _first_matching_field(template, "parentage_level")
    value = norm_label(values.get(field or "", ""))
    if value in {"parent", "父体", "父项"}:
        return "Parent"
    if value in {"child", "子体", "子项"}:
        return "Child"
    return "Standalone"


def reference_field_profiles(workbook: WorkbookReader, definitions: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Return role/theme field usage statistics without exposing old product values."""
    template = parse_template(workbook)
    cells = workbook.sheet_cells(template["sheet_name"])
    data_row = template["settings"]["dataRow"]
    max_row = max((row for row, _ in cells), default=0)
    fields_by_col = {info["column_index"]: info["field"] for info in template["columns"] if info["field"]}
    theme_field = _first_matching_field(template, "variation_theme")
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in range(data_row, max_row + 1):
        values = {
            field: clean_text(cells.get((row, col), ""))
            for col, field in fields_by_col.items()
        }
        if not any(values.values()):
            continue
        role = _row_role(values, template)
        variation_theme = clean_text(values.get(theme_field or "", "")) or "NONE"
        groups[(role, variation_theme)].append(values)

    profiles: list[dict[str, Any]] = []
    for (role, variation_theme), rows in sorted(groups.items()):
        counts = Counter(field for row in rows for field, value in row.items() if value)
        filled_fields = []
        for field, count in sorted(counts.items(), key=lambda item: template["fields"][item[0]]["column_index"]):
            filled_fields.append({
                "field": field,
                "label": template["fields"][field]["label"],
                "filled_count": count,
                "fill_frequency": round(count / len(rows), 4),
                "requirement": requirement_level(definitions.get(field, {}).get("required", "")),
            })
        profiles.append({
            "role": role,
            "variation_theme": variation_theme,
            "row_count": len(rows),
            "filled_field_count": len(filled_fields),
            "filled_fields": filled_fields,
        })
    return {"profiles": profiles, "data_row_count": sum(item["row_count"] for item in profiles)}


def reference_compatibility(
    blank_metadata: dict[str, Any],
    reference_metadata: dict[str, Any],
    blank_template: dict[str, Any],
    reference_template: dict[str, Any],
    marketplace: str,
    content_language: str,
    product_type: str,
    node: str,
    reference_filled_fields: set[str] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if marketplace and reference_metadata["marketplace"] != marketplace:
        reasons.append("marketplace_mismatch")
    if content_language and reference_metadata["content_language"] != content_language:
        reasons.append("content_language_mismatch")
    if product_type and product_type not in reference_metadata["product_types"]:
        reasons.append("product_type_mismatch")
    if node and node not in reference_metadata["browse_nodes"]:
        reasons.append("browse_node_mismatch")

    blank_order = [item["field"] for item in blank_template["columns"] if item.get("field")]
    reference_order = [item["field"] for item in reference_template["columns"] if item.get("field")]
    if blank_order == reference_order:
        structure = "exact_schema"
    elif set(blank_order) == set(reference_order):
        structure = "remappable_schema"
    elif reference_filled_fields and reference_filled_fields.issubset(set(blank_order)):
        structure = "field_subset_compatible"
    else:
        structure = "incompatible_schema"
        reasons.append("technical_fields_incompatible")
    return {
        "compatible": not reasons,
        "structure": structure,
        "reasons": reasons,
        "cross_version_allowed": not reasons and blank_metadata.get("version") != reference_metadata.get("version"),
        "target_value_lists_authoritative": True,
    }


DIRECT_SOURCE_PATTERNS: dict[str, list[tuple[str, ...]]] = {
    "标题": [("item_name[",)],
    "副标题": [("title_differentiation[",)],
    "关键词栏": [("generic_keyword[",)],
    "长描": [("product_description[",)],
    "主图链接": [("main_product_image_locator",)],
    "Swatch Image链接": [("swatch_product_image_locator",)],
    "商品编号类型": [("product_id_type",)],
    "商品ID": [("product_id_value",)],
    "售价": [("list_price", "#1.value")],
}
for _index in range(1, 6):
    DIRECT_SOURCE_PATTERNS[f"五点描述{_index}"] = [("bullet_point[", f"#{_index}.value")]
for _index in range(1, 8):
    DIRECT_SOURCE_PATTERNS[f"附图{_index}链接"] = [(f"other_product_image_locator_{_index}",)]


def evidence_fillable_fields(product: dict[str, Any] | None, template: dict[str, Any]) -> list[dict[str, Any]]:
    if not product:
        return []
    nonempty_headers = {
        header for header in product["headers"]
        if any(clean_text(row["values"].get(header, "")) for row in product["rows"])
    }
    evidence: dict[str, set[str]] = defaultdict(set)
    for header, patterns in DIRECT_SOURCE_PATTERNS.items():
        if header not in nonempty_headers:
            continue
        for pattern in patterns:
            for field in _matching_fields(template, *pattern):
                evidence[field].add(header)
    normalized_nonempty = {normalize_product_header(header): header for header in nonempty_headers}
    price_headers = [
        normalized_nonempty[normalize_product_header(alias)]
        for alias in PRODUCT_HEADER_ALIASES["list_price"]
        if normalize_product_header(alias) in normalized_nonempty
    ]
    for header in price_headers:
        for field in _matching_fields(template, "list_price", "#1.value"):
            evidence[field].add(header)
    return [
        {"field": field, "source_columns": sorted(headers), "evidence_type": "direct_product_column"}
        for field, headers in sorted(evidence.items(), key=lambda item: template["fields"][item[0]]["column_index"])
    ]


def product_roles(product: dict[str, Any] | None) -> list[str]:
    if not product:
        return ["Parent", "Child", "Standalone"]
    roles: set[str] = set()
    for row in product["rows"]:
        value = norm_label(row["values"].get("父子变体", ""))
        if value.startswith("父") or value == "parent":
            roles.add("Parent")
        elif value.startswith("子") or value == "child":
            roles.add("Child")
        else:
            roles.add("Standalone")
    return sorted(roles) or ["Standalone"]


def gtin_gate(product: dict[str, Any] | None, explicit_status: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {"explicit_status": explicit_status, "rows": [], "blocking_errors": []}
    if not product:
        result["state"] = "requires_product_preflight"
        return result
    for row in product["rows"]:
        role_text = norm_label(row["values"].get("父子变体", ""))
        if role_text.startswith("父") or role_text == "parent":
            continue
        id_type = clean_text(row["values"].get("商品编号类型", ""))
        product_id = clean_text(row["values"].get("商品ID", ""))
        if bool(id_type) != bool(product_id):
            state = "blocked_one_sided_id"
            result["blocking_errors"].append({"source_row": row["row_number"], "code": state})
        elif id_type and product_id:
            state = "provided_pair"
        elif explicit_status == "confirmed_exempt":
            state = "confirmed_exempt"
        elif explicit_status == "unknown":
            state = "unknown_draft_only"
        else:
            state = "requires_explicit_choice"
            result["blocking_errors"].append({"source_row": row["row_number"], "code": state})
        result["rows"].append({"source_row": row["row_number"], "state": state})
    result["state"] = "blocked" if result["blocking_errors"] else "ready"
    return result


def role_must_fill(
    definitions: dict[str, dict[str, str]], template: dict[str, Any], roles: list[str]
) -> dict[str, list[str]]:
    required = [
        field for field, definition in definitions.items()
        if requirement_level(definition.get("required", "")) == "required" and field in template["fields"]
    ]
    universal = [
        field for field in ("contribution_sku#1.value", "product_type#1.value", "::record_action")
        if field in template["fields"]
    ]
    parentage = _first_matching_field(template, "parentage_level")
    parent_sku = _first_matching_field(template, "child_parent_sku_relationship", "parent_sku")
    variation_theme = _first_matching_field(template, "variation_theme")
    product_id_type = _first_matching_field(template, "product_id_type")
    out: dict[str, list[str]] = {}
    for role in roles:
        fields = set(required + universal)
        if role == "Parent":
            fields.discard(product_id_type or "")
        if role in {"Parent", "Child"}:
            fields.update(field for field in (parentage, variation_theme) if field)
        if role == "Child" and parent_sku:
            fields.add(parent_sku)
        out[role] = sorted(fields, key=lambda field: template["fields"][field]["column_index"])
    return out


def build_context(
    product_path: Path | None,
    template_path: Path,
    reference_path: Path | None,
    *,
    marketplace: str = "",
    content_language: str = "",
    product_type: str = "",
    node: str = "",
    gtin_status: str | None = None,
    reference_verification: str = "unverified",
) -> dict[str, Any]:
    template_wb = WorkbookReader.open(template_path)
    try:
        template = parse_template(template_wb)
        definitions = parse_data_definitions(template_wb)
        valid_by_label = parse_valid_values(template_wb)
        metadata = workbook_metadata(template_wb, template)
        product_type_values = dropdown_values_for_field(template_wb, "", "product_type#1.value")
        effective_product_type = product_type or (product_type_values[0] if len(product_type_values) == 1 else "")

        requested = {
            "marketplace": marketplace,
            "content_language": content_language,
            "product_type": product_type,
            "browse_node": node,
        }
        missing_target = [key for key, value in requested.items() if not value]
        target_mismatches: list[str] = []
        if marketplace and marketplace != metadata["marketplace"]:
            target_mismatches.append("marketplace")
        if content_language and content_language != metadata["content_language"]:
            target_mismatches.append("content_language")
        if product_type and product_type not in metadata["product_types"]:
            target_mismatches.append("product_type")
        if node and node not in metadata["browse_nodes"]:
            target_mismatches.append("browse_node")

        valid_by_field: dict[str, list[str]] = {}
        dropdown_by_field: dict[str, list[str]] = {}
        for field, info in template["fields"].items():
            definition = definitions.get(field, {})
            label_candidates = [info.get("label", ""), definition.get("label", "")]
            for label in label_candidates:
                if label and label in valid_by_label:
                    valid_by_field[field] = valid_by_label[label]
                    break
            dropdown_values = dropdown_values_for_field(template_wb, effective_product_type, field)
            if dropdown_values:
                dropdown_by_field[field] = dropdown_values

        product = None
        if product_path:
            product_wb = WorkbookReader.open(product_path)
            try:
                product = parse_product_sheet(product_wb)
            finally:
                product_wb.close()

        reference_profile = None
        sample_preferred: dict[str, list[str]] = {}
        if reference_path:
            if reference_verification not in {"unverified", "user_confirmed", "report_verified"}:
                raise ValueError(f"Unsupported reference verification level: {reference_verification}")
            reference_wb = WorkbookReader.open(reference_path)
            try:
                reference_template = parse_template(reference_wb)
                reference_metadata = workbook_metadata(reference_wb, reference_template)
                reference_definitions = parse_data_definitions(reference_wb)
                profiles = reference_field_profiles(reference_wb, reference_definitions or definitions)
                reference_filled_fields = {
                    item["field"]
                    for profile in profiles["profiles"]
                    for item in profile["filled_fields"]
                }
                compatibility = reference_compatibility(
                    metadata,
                    reference_metadata,
                    template,
                    reference_template,
                    marketplace,
                    content_language,
                    product_type,
                    node,
                    reference_filled_fields,
                )
                reference_profile = {
                    "verification_level": reference_verification,
                    "eligible_for_learning": bool(
                        compatibility["compatible"]
                        and reference_verification in {"user_confirmed", "report_verified"}
                    ),
                    "metadata": reference_metadata,
                    "compatibility": compatibility,
                    **profiles,
                }
                if reference_profile["eligible_for_learning"]:
                    by_role: dict[str, set[str]] = defaultdict(set)
                    for profile in profiles["profiles"]:
                        by_role[profile["role"]].update(item["field"] for item in profile["filled_fields"])
                    sample_preferred = {
                        role: sorted(fields, key=lambda field: template["fields"][field]["column_index"])
                        for role, fields in by_role.items()
                    }
            finally:
                reference_wb.close()

        roles = product_roles(product)
        must_fill = role_must_fill(definitions, template, roles)
        rule_default = {
            role: [
                field
                for field in fields
                if field not in set(must_fill.get(role, []))
            ]
            for role, fields in policy_rule_default_fields(template, roles).items()
        }
        rule_default_fields = {
            field for role_fields in rule_default.values() for field in role_fields
        }
        sample_preferred = {
            role: [
                field
                for field in fields
                if field not in set(must_fill.get(role, []))
                and field not in set(rule_default.get(role, []))
            ]
            for role, fields in sample_preferred.items()
        }
        reserved_decision_fields = {
            field for role_fields in must_fill.values() for field in role_fields
        }
        reserved_decision_fields.update(rule_default_fields)
        reserved_decision_fields.update(
            field for role_fields in sample_preferred.values() for field in role_fields
        )
        evidence = [
            item
            for item in evidence_fillable_fields(product, template)
            if item["field"] not in reserved_decision_fields
        ]
        resolution_hints = product_resolution_hints(
            product,
            template,
            sample_preferred,
            valid_by_field,
            dropdown_by_field,
        )
        evidence_by_field = {item["field"]: item for item in evidence}
        for row in resolution_hints["rows"]:
            for hint in row["hints"]:
                if (
                    hint["decision_set"] == "evidence_fillable"
                    and hint["field"] not in reserved_decision_fields
                    and hint["field"] not in evidence_by_field
                ):
                    evidence_item = {
                        "field": hint["field"],
                        "source_columns": hint["source_reference"],
                        "evidence_type": "normalized_product_measurement",
                    }
                    evidence.append(evidence_item)
                    evidence_by_field[hint["field"]] = evidence_item
        evidence.sort(key=lambda item: template["fields"][item["field"]]["column_index"])
        evidence_fields = [item["field"] for item in evidence]
        conditional_candidates = [
            field for field, definition in definitions.items()
            if requirement_level(definition.get("required", "")) == "conditionally_required" and field in template["fields"]
        ]
        model_evidence_candidates = [
            field for field, definition in definitions.items()
            if requirement_level(definition.get("required", "")) in {"optional", "recommended", "conditionally_required"}
            and field in template["fields"]
        ]
        target_fields = set(evidence_fields)
        for role_fields in must_fill.values():
            target_fields.update(role_fields)
        for role_fields in rule_default.values():
            target_fields.update(role_fields)
        for role_fields in sample_preferred.values():
            target_fields.update(role_fields)
        expectations = sample_field_expectations(
            reference_profile,
            definitions,
            valid_by_field,
            dropdown_by_field,
        )

        return {
            "contract_version": "2.2",
            "task_scope": requested,
            "preflight": {
                "missing_target_scope": missing_target,
                "target_template_mismatches": target_mismatches,
                "blank_template_required": True,
                "reference_optional": True,
                "gtin_gate": gtin_gate(product, gtin_status),
            },
            "template_path": str(template_path),
            "product_path": str(product_path) if product_path else None,
            "reference_path": str(reference_path) if reference_path else None,
            "template_metadata": metadata,
            "template": template,
            "data_definitions": definitions,
            "valid_values_by_label": valid_by_label,
            "valid_values_by_field": valid_by_field,
            "dropdown_values_by_field": dropdown_by_field,
            "reference_profile": reference_profile,
            "sample_field_expectations": expectations,
            "field_decision": {
                "must_fill": must_fill,
                "rule_default": rule_default,
                "sample_preferred": sample_preferred,
                "evidence_fillable": evidence,
                "conditional_candidates": conditional_candidates,
                "model_evidence_candidates": model_evidence_candidates,
                "rules": {
                    "sample_blank_does_not_waive_requirement": True,
                    "sample_values_exposed": False,
                    "target_template_values_authoritative": True,
                    "without_sample": "must_fill_union_evidence_fillable",
                    "manual_review_value": MANUAL_REVIEW_VALUE,
                    "manual_review_requires_draft": True,
                },
            },
            "field_resolution": resolution_hints,
            "target_fields": sorted(target_fields, key=lambda field: template["fields"][field]["column_index"]),
            "product_input": {
                "path": str(product_path.expanduser().resolve()),
                "sha256": sha256_file(product_path.expanduser().resolve()),
            } if product_path else None,
            "product_sheet": product,
        }
    finally:
        template_wb.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, help="User product spreadsheet (.xlsx/.xlsm)")
    parser.add_argument("--template", type=Path, required=True, help="Amazon inventory template (.xlsx/.xlsm)")
    parser.add_argument("--reference", type=Path, help="Optional completed reference template")
    parser.add_argument("--marketplace", required=True, help="Explicit target marketplace ID, for example ATVPDKIKX0DER")
    parser.add_argument("--content-language", required=True, help="Explicit target content language, for example en_US")
    parser.add_argument("--product-type", required=True, help="Explicit Amazon Product Type")
    parser.add_argument("--node", required=True, help="Explicit leaf browse node key")
    parser.add_argument(
        "--gtin-status",
        choices=["confirmed_exempt", "unknown"],
        help="Required when applicable product rows have neither product ID field",
    )
    parser.add_argument(
        "--reference-verification",
        choices=["unverified", "user_confirmed", "report_verified"],
        default="unverified",
    )
    parser.add_argument("--out", type=Path, help="Write JSON context to this file")
    args = parser.parse_args()

    context = build_context(
        args.product,
        args.template,
        args.reference,
        marketplace=args.marketplace,
        content_language=args.content_language,
        product_type=args.product_type,
        node=args.node,
        gtin_status=args.gtin_status,
        reference_verification=args.reference_verification,
    )
    if context["preflight"]["target_template_mismatches"]:
        raise SystemExit(
            "Target scope does not match blank template: "
            + ", ".join(context["preflight"]["target_template_mismatches"])
        )
    text = json.dumps(context, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    gtin_gate_result = context["preflight"]["gtin_gate"]
    if gtin_gate_result.get("state") == "blocked":
        print(
            "GTIN preflight blocked: "
            + json.dumps(gtin_gate_result.get("blocking_errors", []), ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
