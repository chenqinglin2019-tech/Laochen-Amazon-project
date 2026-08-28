#!/usr/bin/env python3
"""Validate an Amazon inventory mapping and the structure of a written workbook.

The validator has no third-party dependencies.  It performs deterministic
pre-write validation against an Amazon blank template and, when ``--output``
is supplied, verifies that protected workbook structure still matches that
template.  A JSON report is always written to stdout; ``--report`` optionally
writes the same report to a file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import posixpath
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_inventory_context import (  # noqa: E402
    MANUAL_REVIEW_VALUE,
    WorkbookReader,
    build_context,
    norm_label,
    parse_product_sheet,
    parse_template,
    product_resolution_hints,
)
from manage_template_library import DB_RELATIVE_PATH, LibraryError, query_project  # noqa: E402


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": NS_MAIN, "r": NS_REL, "rel": NS_PKG_REL}

ROLE_ALIASES = {
    "parent": "Parent",
    "父体": "Parent",
    "父": "Parent",
    "child": "Child",
    "子体": "Child",
    "子": "Child",
    "standalone": "Standalone",
    "single": "Standalone",
    "单体": "Standalone",
    "单品": "Standalone",
    "独立商品": "Standalone",
}

VARIATION_ALIASES = {
    "color": ("color", "color_name", "colour", "colour_name"),
    "colour": ("color", "color_name", "colour", "colour_name"),
    "size": ("size", "size_name"),
    "base_material": ("base_material", "material"),
    "material": ("material", "base_material"),
    "pattern": ("pattern", "pattern_name"),
    "pattern_name": ("pattern_name", "pattern"),
    "item_package_quantity": ("item_package_quantity", "package_quantity"),
    "package_quantity": ("package_quantity", "item_package_quantity"),
}

DECISION_SETS_V20 = {"must_fill", "sample_preferred", "evidence_fillable"}
DECISION_SETS_V21 = {
    "must_fill",
    "rule_default",
    "sample_preferred",
    "evidence_fillable",
}
SUPPORTED_SCHEMA_VERSIONS = {"2.0", "2.1", "2.2"}
RULE_DEFAULT_VERSIONS = {"2.1", "2.2"}
EXTENDED_RULE_VERSION = "2.2"
FILL_MODES = {"SAMPLE_GUIDED", "NO_SAMPLE_CONFIRMED"}
CONFIRMATION_STATUSES = {"confirmed", "not_required", "pending"}
FIELD_VALIDATION_STATUSES = {"passed", "pending", "warning", "blocked"}
SOURCE_TYPES = {
    "product_cell",
    "model_extracted",
    "model_summarized",
    "user_confirmation",
    "target_template_allowed_value",
    "task_scope",
    "sku_reservation",
    "relationship",
    "system_generated",
    "business_rule",
    "model_rule",
    "manual_review_marker",
}
PRODUCT_SOURCE_TYPES = {"product_cell", "model_extracted", "model_summarized", "model_rule"}
BUSINESS_RULES_V22 = {
    "rule:item-condition-new": ("condition_type", "new"),
    "rule:model-number-equals-sku": ("model_number", None),
    "rule:manufacturer-equals-brand": ("manufacturer", None),
    "rule:number-of-items-default-one": ("number_of_items", "1"),
    "rule:fulfillment-default-fba": ("fulfillment_availability", "fulfillment by amazon (na)"),
    "rule:item-dimension-unit-inches": ("item_depth_width_height", "inches"),
}
MODEL_RULES_V22 = {
    "rule:model-name-core-keyword-fallback": "model_name",
    "rule:part-number-core-keyword-fallback": "part_number",
    "rule:mounting-type-enum-selection": "mounting_type",
}
SENSITIVE_MIN_CONFIDENCE = 0.8
SENSITIVE_FIELD_MARKERS = (
    "product_id",
    "brand",
    "manufacturer",
    "model_number",
    "part_number",
    "country_of_origin",
    "origin_country",
    "batter",
    "dangerous",
    "hazmat",
    "supplier_declared_dg",
    "compliance",
    "regulatory",
    "certification",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def _nonblank(value: Any) -> bool:
    return bool(_text(value).strip())


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).strip()).casefold()


def _field_base(field: str) -> str:
    return re.split(r"[\[#]", field, maxsplit=1)[0].casefold()


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    item.update({key: value for key, value in details.items() if value is not None})
    return item


def _add_error(section: dict[str, Any], code: str, message: str, **details: Any) -> None:
    section["errors"].append(_issue(code, message, **details))


def _add_warning(section: dict[str, Any], code: str, message: str, **details: Any) -> None:
    section["warnings"].append(_issue(code, message, **details))


def _add_missing_value_issue(
    section: dict[str, Any],
    result_status: str,
    code: str,
    message: str,
    **details: Any,
) -> None:
    if result_status == "DRAFT_NOT_FOR_UPLOAD":
        _add_warning(section, code, message, **details)
    else:
        _add_error(section, code, message, **details)


def _row_details(index: int, item: dict[str, Any] | None = None) -> dict[str, Any]:
    details: dict[str, Any] = {"row_index": index}
    if item and item.get("source_row") is not None:
        details["source_row"] = item.get("source_row")
    return details


def _values_for_fields(fields: dict[str, Any], candidates: list[str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for field in candidates:
        value = _text(fields.get(field, ""))
        if value.strip():
            values.append((field, value))
    return values


def _single_value(
    section: dict[str, Any],
    fields: dict[str, Any],
    candidates: list[str],
    code: str,
    label: str,
    row_details: dict[str, Any],
) -> str:
    values = _values_for_fields(fields, candidates)
    distinct = {_normalized(value) for _, value in values}
    if len(distinct) > 1:
        _add_error(
            section,
            code,
            f"同一行存在互相冲突的{label}值。",
            fields=[field for field, _ in values],
            values=[value for _, value in values],
            **row_details,
        )
    return values[0][1] if values else ""


def _required_status(value: Any) -> bool:
    text = _normalized(value)
    if text == "required":
        return True
    return "必填" in text and "条件" not in text


def _role_from_value(value: Any) -> str | None:
    return ROLE_ALIASES.get(_normalized(value))


def _is_gtin_exempt(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", _normalized(value))
    return normalized in {"gtinexempt", "exempt"}


def _is_sensitive_field(field: str) -> bool:
    lowered = field.casefold()
    return any(marker in lowered for marker in SENSITIVE_FIELD_MARKERS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping_evidence_context(
    mapping: dict[str, Any], report: dict[str, Any], template_path: Path
) -> tuple[
    dict[tuple[str, str], str],
    dict[str, dict[str, Any]],
    dict[str, Any] | None,
]:
    cells: dict[tuple[str, str], str] = {}
    product_sheet: dict[str, Any] | None = None
    inputs = mapping.get("inputs")
    product = inputs.get("product") if isinstance(inputs, dict) else None
    if not isinstance(product, dict):
        _add_error(report, "product_input_required", "Mapping 必须包含 inputs.product 快照。")
    else:
        raw_path = product.get("path")
        expected_hash = product.get("sha256")
        if not isinstance(raw_path, str) or not raw_path.strip():
            _add_error(report, "product_input_path_required", "inputs.product.path 必须是绝对文件路径。")
        else:
            product_path = Path(raw_path).expanduser()
            if not product_path.is_absolute():
                _add_error(report, "product_input_path_not_absolute", "inputs.product.path 必须是绝对路径。")
            else:
                product_path = product_path.resolve()
                in_template_library = any(
                    parent.name in {"空白模板库", "样板模板库"}
                    for parent in (product_path, *product_path.parents)
                )
                if product_path == template_path.expanduser().resolve() or in_template_library:
                    _add_error(
                        report,
                        "product_input_template_library_forbidden",
                        "产品信息输入不得使用空白模板、样板或模板库内文件。",
                        path=str(product_path),
                    )
                elif not product_path.is_file() or product_path.suffix.casefold() not in {".xlsx", ".xlsm"}:
                    _add_error(
                        report,
                        "product_input_unreadable",
                        "inputs.product.path 必须指向可读取的 .xlsx/.xlsm 产品信息表。",
                        path=str(product_path),
                    )
                elif not isinstance(expected_hash, str) or _sha256_file(product_path) != expected_hash:
                    _add_error(
                        report,
                        "product_input_hash_mismatch",
                        "产品信息表当前 SHA-256 与 Mapping 快照不一致。",
                        path=str(product_path),
                    )
                else:
                    try:
                        workbook = WorkbookReader.open(product_path)
                        try:
                            product_sheet = parse_product_sheet(workbook)
                            for sheet_name in workbook.sheet_paths:
                                for (row, column), value in workbook.sheet_cells(sheet_name).items():
                                    address = f"{_column_letters(column)}{row}"
                                    cells[(sheet_name.casefold(), address)] = _text(value)
                        finally:
                            workbook.close()
                    except Exception as exc:
                        _add_error(
                            report,
                            "product_input_parse_failed",
                            "产品信息表无法解析。",
                            path=str(product_path),
                            error=f"{type(exc).__name__}: {exc}",
                        )

    confirmations: dict[str, dict[str, Any]] = {}
    raw_confirmations = mapping.get("confirmations", [])
    if not isinstance(raw_confirmations, list):
        _add_error(report, "confirmations_invalid", "Mapping confirmations 必须是数组。")
    else:
        for index, item in enumerate(raw_confirmations, start=1):
            if not isinstance(item, dict):
                _add_error(report, "confirmation_not_object", "confirmations 项必须是 object。", index=index)
                continue
            confirmation_id = item.get("id")
            if not isinstance(confirmation_id, str) or not confirmation_id.strip():
                _add_error(report, "confirmation_id_required", "确认记录必须包含非空 id。", index=index)
                continue
            if confirmation_id in confirmations:
                _add_error(report, "confirmation_id_duplicate", "确认记录 id 不得重复。", confirmation_id=confirmation_id)
                continue
            if item.get("confirmed") is not True:
                _add_error(report, "confirmation_not_confirmed", "确认记录必须显式 confirmed=true。", confirmation_id=confirmation_id)
            if not isinstance(item.get("field"), str) or "value" not in item:
                _add_error(report, "confirmation_payload_invalid", "确认记录必须包含 field 和 value。", confirmation_id=confirmation_id)
            confirmations[confirmation_id] = item
    return cells, confirmations, product_sheet


def _product_row_role(row: dict[str, Any]) -> str:
    value = _normalized((row.get("values") or {}).get("父子变体", ""))
    if value.startswith("父") or value == "parent":
        return "Parent"
    if value.startswith("子") or value == "child":
        return "Child"
    return "Standalone"


def _inferred_project_root(template_path: Path, project_root: Path | None) -> Path | None:
    if project_root is not None:
        return Path(project_root).expanduser().resolve()
    resolved = template_path.expanduser().resolve()
    if resolved.parent.name == "空白模板库":
        return resolved.parent.parent
    return None


def _validate_template_selection(
    report: dict[str, Any],
    templates: dict[str, Any],
    task_scope: dict[str, str],
    template_path: Path,
    project_root: Path | None,
) -> None:
    root = _inferred_project_root(template_path, project_root)
    if root is None or not (root / DB_RELATIVE_PATH).is_file():
        _add_error(
            report,
            "template_index_required",
            "必须从项目模板库索引验证空白模板和样板选择；请先运行 scan。",
        )
        return

    blank_entry_id = templates.get("blank_entry_id")
    if isinstance(blank_entry_id, bool) or not isinstance(blank_entry_id, int):
        _add_error(
            report,
            "blank_entry_id_required",
            "templates.blank_entry_id 必须是模板索引中的整数 ID。",
        )
        return
    try:
        result = query_project(
            root,
            task_scope["marketplace"],
            task_scope["content_language"],
            task_scope["product_type"],
            task_scope["browse_node"],
            "all",
            preferred_blank_entry_id=blank_entry_id,
        )
    except (LibraryError, OSError, sqlite3.Error, ValueError) as exc:
        _add_error(
            report,
            "template_index_query_failed",
            "模板库索引查询失败。",
            error=str(exc),
        )
        return

    blank = result.get("preferred_blank_template")
    if not isinstance(blank, dict) or blank.get("entry_id") != blank_entry_id:
        _add_error(report, "blank_index_entry_mismatch", "空白模板索引记录与 Mapping 不一致。")
    elif blank.get("sha256") != templates.get("blank_sha256"):
        _add_error(report, "blank_index_hash_mismatch", "空白模板哈希与模板库索引不一致。")
    else:
        indexed_path = (root / str(blank.get("path") or "")).resolve()
        if indexed_path != template_path.expanduser().resolve():
            _add_error(
                report,
                "blank_index_path_mismatch",
                "当前空白模板路径与 Mapping 选择的模板库记录不一致。",
            )
        elif not indexed_path.is_file() or _sha256_file(indexed_path) != blank.get("sha256"):
            _add_error(report, "blank_index_file_stale", "空白模板库原件已变化，必须重新扫描。")

    if task_scope["fill_mode"] != "SAMPLE_GUIDED":
        return
    sample_entry_id = templates.get("sample_entry_id")
    if isinstance(sample_entry_id, bool) or not isinstance(sample_entry_id, int):
        _add_error(report, "sample_entry_id_required", "SAMPLE_GUIDED 必须记录整数 sample_entry_id。")
        return
    candidates = {
        item.get("entry_id"): item for item in result.get("usable_sample_templates", [])
    }
    sample = candidates.get(sample_entry_id)
    if not isinstance(sample, dict):
        _add_error(
            report,
            "sample_index_entry_unusable",
            "样板不存在、未认证、节点不匹配或与所选空白模板结构不兼容。",
            sample_entry_id=sample_entry_id,
        )
        return
    checks = {
        "sample_sha256": sample.get("sha256"),
        "sample_verification": sample.get("sample_status"),
        "sample_schema_compatibility": sample.get("schema_compatibility"),
    }
    for field, expected in checks.items():
        if templates.get(field) != expected:
            _add_error(
                report,
                "sample_index_metadata_mismatch",
                "Mapping 样板元数据与模板库索引不一致。",
                field=field,
                mapping_value=templates.get(field),
                index_value=expected,
            )
    indexed_path = (root / str(sample.get("path") or "")).resolve()
    if not indexed_path.is_file() or _sha256_file(indexed_path) != sample.get("sha256"):
        _add_error(report, "sample_index_file_stale", "样板模板库原件已变化，必须重新扫描。")


def _sample_expected_fields(
    report: dict[str, Any],
    templates: dict[str, Any],
    task_scope: dict[str, str],
    template_path: Path,
    project_root: Path | None,
) -> dict[tuple[str, str], set[str]]:
    if task_scope.get("fill_mode") != "SAMPLE_GUIDED":
        return {}
    root = _inferred_project_root(template_path, project_root)
    if root is None:
        return {}
    try:
        result = query_project(
            root,
            task_scope["marketplace"],
            task_scope["content_language"],
            task_scope["product_type"],
            task_scope["browse_node"],
            "all",
            preferred_blank_entry_id=templates.get("blank_entry_id"),
        )
        sample_entry_id = templates.get("sample_entry_id")
        sample = next(
            item
            for item in result.get("usable_sample_templates", [])
            if item.get("entry_id") == sample_entry_id
        )
        sample_path = (root / str(sample["path"])).resolve()
        context = build_context(
            None,
            template_path,
            sample_path,
            marketplace=task_scope["marketplace"],
            content_language=task_scope["content_language"],
            product_type=task_scope["product_type"],
            node=task_scope["browse_node"],
            reference_verification=str(templates.get("sample_verification") or ""),
        )
    except (StopIteration, KeyError, LibraryError, OSError, sqlite3.Error, ValueError) as exc:
        _add_error(
            report,
            "sample_profile_unavailable",
            "无法从当前已验证样板重建人工核对字段资格。",
            error=str(exc),
        )
        return {}
    output: dict[tuple[str, str], set[str]] = {}
    profile = context.get("reference_profile") or {}
    for item in profile.get("profiles", []):
        key = (item["role"], norm_label(item.get("variation_theme", "NONE")))
        output[key] = {
            field["field"] for field in item.get("filled_fields", [])
        }
    return output


def _column_letters(number: int) -> str:
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _product_reference_value(
    reference: str, product_cells: dict[tuple[str, str], str]
) -> str | None:
    if "!" not in reference:
        return None
    sheet_name, address = reference.rsplit("!", 1)
    sheet_name = sheet_name.strip().strip("'").casefold()
    address = address.replace("$", "").strip().upper()
    if not re.fullmatch(r"[A-Z]+[1-9][0-9]*", address):
        return None
    return product_cells.get((sheet_name, address), "")


def _gtin_check_digit_valid(value: str) -> bool:
    if not value.isdigit() or len(value) < 2:
        return False
    body = value[:-1]
    total = sum(
        int(digit) * (3 if (len(body) - index) % 2 == 1 else 1)
        for index, digit in enumerate(body)
    )
    expected = (10 - total % 10) % 10
    return expected == int(value[-1])


def _field_record_value(
    section: dict[str, Any],
    field: str,
    record: Any,
    row_details: dict[str, Any],
    result_status: str,
    fill_mode: str,
    product_cells: dict[tuple[str, str], str],
    confirmations: dict[str, dict[str, Any]],
    schema_version: str,
) -> Any:
    """Validate a Mapping v2 field record and return its payload value."""
    if not isinstance(record, dict):
        _add_error(
            section,
            "field_record_required",
            "Mapping v2 的 fields 值必须是包含 value/source/confidence/confirmation_status/validation 的 object，不能使用裸值。",
            field=field,
            **row_details,
        )
        return None

    required_keys = {
        "value",
        "source",
        "confidence",
        "confirmation_status",
        "decision_set",
        "validation",
    }
    missing_keys = sorted(required_keys - set(record))
    if missing_keys:
        _add_error(
            section,
            "field_record_keys_missing",
            "字段记录缺少 Mapping v2 必需属性。",
            field=field,
            missing_keys=missing_keys,
            **row_details,
        )

    value = record.get("value")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        _add_error(
            section,
            "field_value_not_scalar",
            "字段记录的 value 必须是字符串、数字、布尔值或 null。",
            field=field,
            **row_details,
        )

    source = record.get("source")
    if not isinstance(source, dict):
        _add_error(section, "field_source_invalid", "字段记录的 source 必须是 object。", field=field, **row_details)
    else:
        raw_source_type = source.get("type")
        source_type = raw_source_type if isinstance(raw_source_type, str) else ""
        if not source_type.strip():
            _add_error(section, "field_source_type_required", "字段来源必须包含非空 type。", field=field, **row_details)
        elif source_type not in SOURCE_TYPES:
            _add_error(
                section,
                "field_source_type_unsupported",
                "字段来源 type 不在 Mapping v2 允许集合中。",
                field=field,
                source_type=source_type,
                **row_details,
            )
        reference = source.get("reference")
        if reference is None:
            _add_error(section, "field_source_reference_required", "字段来源必须包含 reference。", field=field, **row_details)
        elif source_type in PRODUCT_SOURCE_TYPES:
            references = reference if isinstance(reference, list) else [reference]
            if not references or any(not isinstance(item, str) for item in references):
                _add_error(
                    section,
                    "product_source_references_invalid",
                    "产品来源 reference 必须是单元格引用字符串或字符串数组。",
                    field=field,
                    **row_details,
                )
            else:
                evidence_values: list[str] = []
                for item in references:
                    evidence = _product_reference_value(item, product_cells)
                    if evidence is None:
                        _add_error(
                            section,
                            "product_source_reference_invalid",
                            "产品来源必须使用存在的 Sheet!A1 单元格引用。",
                            field=field,
                            reference=item,
                            **row_details,
                        )
                    elif not evidence.strip():
                        _add_error(
                            section,
                            "product_source_cell_blank",
                            "字段来源引用的产品信息单元格为空。",
                            field=field,
                            reference=item,
                            **row_details,
                        )
                    else:
                        evidence_values.append(evidence)
                if source_type == "product_cell" and evidence_values and not any(
                    _normalized(item) == _normalized(value) for item in evidence_values
                ):
                    _add_error(
                        section,
                        "product_cell_value_mismatch",
                        "product_cell 来源的写入值与引用单元格不一致。",
                        field=field,
                        **row_details,
                    )
                if source_type == "model_rule":
                    rule_id = source.get("rule_id")
                    expected_base = MODEL_RULES_V22.get(rule_id)
                    if (
                        schema_version != EXTENDED_RULE_VERSION
                        or expected_base is None
                        or _field_base(field) != expected_base
                    ):
                        _add_error(
                            section,
                            "model_rule_invalid",
                            "model_rule 仅允许 Mapping 2.2 的白名单字段和规则。",
                            field=field,
                            rule_id=rule_id,
                            **row_details,
                        )
        elif source_type == "user_confirmation":
            if not isinstance(reference, str) or not reference.startswith("confirmation:"):
                _add_error(
                    section,
                    "confirmation_reference_invalid",
                    "user_confirmation 必须引用 confirmation:<id>。",
                    field=field,
                    **row_details,
                )
            else:
                confirmation_id = reference.split(":", 1)[1]
                confirmation = confirmations.get(confirmation_id)
                if confirmation is None:
                    _add_error(
                        section,
                        "confirmation_reference_missing",
                        "字段引用的确认记录不存在。",
                        field=field,
                        confirmation_id=confirmation_id,
                        **row_details,
                    )
                elif confirmation.get("field") != field or _normalized(confirmation.get("value")) != _normalized(value):
                    _add_error(
                        section,
                        "confirmation_payload_mismatch",
                        "确认记录的 field/value 与字段写入值不一致。",
                        field=field,
                        confirmation_id=confirmation_id,
                        **row_details,
                    )
        elif source_type == "task_scope" and _field_base(field) != "product_type":
            _add_error(
                section,
                "structural_source_field_mismatch",
                "task_scope 只能用于 Product Type 系统字段。",
                field=field,
                source_type=source_type,
                **row_details,
            )
        elif source_type == "sku_reservation" and _field_base(field) != "contribution_sku":
            _add_error(
                section,
                "structural_source_field_mismatch",
                "sku_reservation 只能用于 SKU 技术字段。",
                field=field,
                source_type=source_type,
                **row_details,
            )
        elif source_type == "relationship" and not any(
            marker in field.casefold()
            for marker in ("parentage_level", "parent_sku", "variation_theme")
        ):
            _add_error(
                section,
                "structural_source_field_mismatch",
                "relationship 只能用于父子关系或变体主题系统字段。",
                field=field,
                source_type=source_type,
                **row_details,
            )
        elif source_type == "system_generated" and field != "::record_action":
            _add_error(
                section,
                "structural_source_field_mismatch",
                "system_generated 仅允许用于 ::record_action；SKU 和关系字段使用专用来源。",
                field=field,
                source_type=source_type,
                **row_details,
            )
        elif source_type == "business_rule":
            legacy_valid = (
                schema_version == "2.1"
                and _field_base(field) == "condition_type"
                and _normalized(value) == "new"
                and reference == "rule:item-condition-new"
            )
            rule_spec = BUSINESS_RULES_V22.get(reference) if schema_version == "2.2" else None
            extended_valid = bool(
                rule_spec
                and _field_base(field) == rule_spec[0]
                and (rule_spec[1] is None or _normalized(value) == rule_spec[1])
            )
            if not (legacy_valid or extended_valid):
                _add_error(
                    section,
                    "business_rule_invalid",
                    "business_rule 必须匹配当前 Mapping 版本允许的字段、规则 ID 和规则值。",
                    field=field,
                    rule_id=reference,
                    **row_details,
                )
        elif source_type == "manual_review_marker":
            expected_reference = (
                f"manual_review:{row_details.get('source_row')}:{field}"
            )
            if schema_version not in RULE_DEFAULT_VERSIONS:
                _add_error(
                    section,
                    "manual_review_requires_v21",
                    "manual_review_marker 仅允许 Mapping 2.1 或 2.2。",
                    field=field,
                    **row_details,
                )
            if result_status != "DRAFT_NOT_FOR_UPLOAD":
                _add_error(
                    section,
                    "manual_review_requires_draft",
                    "中文人工核对提示只能用于 DRAFT_NOT_FOR_UPLOAD。",
                    field=field,
                    **row_details,
                )
            if value != MANUAL_REVIEW_VALUE:
                _add_error(
                    section,
                    "manual_review_value_invalid",
                    "人工核对提示必须使用固定中文文本。",
                    field=field,
                    expected=MANUAL_REVIEW_VALUE,
                    value=value,
                    **row_details,
                )
            if reference != expected_reference:
                _add_error(
                    section,
                    "manual_review_reference_invalid",
                    "manual_review_marker 必须引用当前来源行和技术字段。",
                    field=field,
                    expected=expected_reference,
                    value=reference,
                    **row_details,
                )
            _add_warning(
                section,
                "manual_review_required",
                "字段含中文人工核对提示；当前文件不得上传。",
                field=field,
                **row_details,
            )
        elif _nonblank(value) and _is_sensitive_field(field) and source_type == "target_template_allowed_value":
            _add_error(
                section,
                "sensitive_fact_source_invalid",
                "模板候选值只能证明格式合法，不能单独证明敏感商品事实。",
                field=field,
                **row_details,
            )
        elif source_type == "target_template_allowed_value" and not (
            field == "::record_action"
            or _field_base(field) == "product_type"
            or any(
                marker in field.casefold()
                for marker in ("parentage_level", "parent_sku", "variation_theme")
            )
        ):
            _add_error(
                section,
                "template_candidate_source_field_mismatch",
                "target_template_allowed_value 不能单独作为商品事实来源。",
                field=field,
                **row_details,
            )

    confidence = record.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        _add_error(
            section,
            "field_confidence_invalid",
            "字段 confidence 必须是 0 到 1 之间的数字。",
            field=field,
            value=confidence,
            **row_details,
        )

    confirmation_status = record.get("confirmation_status")
    if confirmation_status not in CONFIRMATION_STATUSES:
        _add_error(
            section,
            "field_confirmation_status_invalid",
            "字段 confirmation_status 必须是 confirmed、not_required 或 pending。",
            field=field,
            value=confirmation_status,
            **row_details,
        )
    elif result_status == "LOCAL_VALIDATION_PASSED" and confirmation_status == "pending":
        _add_error(
            section,
            "field_confirmation_pending",
            "LOCAL_VALIDATION_PASSED 不允许存在 pending 字段确认状态。",
            field=field,
            **row_details,
        )

    decision_set = record.get("decision_set")
    allowed_decision_sets = (
        DECISION_SETS_V21 if schema_version in RULE_DEFAULT_VERSIONS else DECISION_SETS_V20
    )
    if decision_set not in allowed_decision_sets:
        _add_error(
            section,
            "field_decision_set_invalid",
            "字段 decision_set 不属于当前 Mapping 版本允许集合。",
            field=field,
            value=decision_set,
            **row_details,
        )
    elif fill_mode == "NO_SAMPLE_CONFIRMED" and decision_set == "sample_preferred":
        _add_error(
            section,
            "sample_preferred_forbidden_without_sample",
            "NO_SAMPLE_CONFIRMED 不允许任何字段使用 sample_preferred。",
            field=field,
            **row_details,
        )

    validation = record.get("validation")
    if not isinstance(validation, dict):
        _add_error(section, "field_validation_invalid", "字段 validation 必须是 object。", field=field, **row_details)
    else:
        validation_status = validation.get("status")
        if validation_status not in FIELD_VALIDATION_STATUSES:
            _add_error(
                section,
                "field_validation_status_invalid",
                "字段 validation.status 必须是 passed、pending、warning 或 blocked。",
                field=field,
                value=validation_status,
                **row_details,
            )
        elif validation_status == "blocked":
            _add_error(
                section,
                "field_validation_not_passed",
                "字段自身 validation.status 表示该值尚未通过校验。",
                field=field,
                validation_status=validation_status,
                **row_details,
            )
        elif result_status == "LOCAL_VALIDATION_PASSED" and validation_status == "pending":
            _add_error(
                section,
                "field_validation_pending",
                "LOCAL_VALIDATION_PASSED 不允许字段 validation.status=pending。",
                field=field,
                **row_details,
            )
        if (
            isinstance(source, dict)
            and source.get("type") == "manual_review_marker"
            and validation_status != "warning"
        ):
            _add_error(
                section,
                "manual_review_validation_status_invalid",
                "manual_review_marker 的 validation.status 必须为 warning。",
                field=field,
                value=validation_status,
                **row_details,
            )
        messages = validation.get("messages")
        if not isinstance(messages, list) or any(not isinstance(message, str) for message in messages):
            _add_error(
                section,
                "field_validation_messages_invalid",
                "字段 validation.messages 必须是字符串数组。",
                field=field,
                **row_details,
            )

    is_manual_review = (
        isinstance(source, dict) and source.get("type") == "manual_review_marker"
    )
    source_type = source.get("type") if isinstance(source, dict) else ""
    trusted_rule_derivation = (
        schema_version == EXTENDED_RULE_VERSION
        and (
            source_type == "model_rule"
            or source_type == "business_rule"
            and source.get("reference") in BUSINESS_RULES_V22
        )
    )
    if trusted_rule_derivation and _nonblank(value) and _is_sensitive_field(field):
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or confidence < SENSITIVE_MIN_CONFIDENCE
        ):
            _add_error(
                section,
                "rule_derived_sensitive_value_low_confidence",
                "规则推导的敏感字段仍须达到最低置信度。",
                field=field,
                confidence=confidence,
                minimum_confidence=SENSITIVE_MIN_CONFIDENCE,
                **row_details,
            )
    if (
        _nonblank(value)
        and _is_sensitive_field(field)
        and not is_manual_review
        and not trusted_rule_derivation
    ):
        if not isinstance(confidence, bool) and isinstance(confidence, (int, float)):
            if confidence < SENSITIVE_MIN_CONFIDENCE:
                _add_error(
                    section,
                    "sensitive_value_low_confidence",
                    "敏感客观字段的非空值置信度不足，禁止写入。",
                    field=field,
                    confidence=confidence,
                    minimum_confidence=SENSITIVE_MIN_CONFIDENCE,
                    **row_details,
                )
        if _normalized(confirmation_status) != "confirmed":
            _add_error(
                section,
                "sensitive_value_not_confirmed",
                "敏感客观字段的非空值必须具有 confirmed 状态。",
                field=field,
                confirmation_status=confirmation_status,
                **row_details,
            )
    return value


def _theme_components(theme: str) -> list[str]:
    parts = re.split(r"\s*[/,+]\s*", theme.strip())
    output: list[str] = []
    for part in parts:
        token = re.sub(r"[^a-z0-9]+", "_", part.casefold()).strip("_")
        if token:
            output.append(token)
    return output


def _variation_value(
    fields: dict[str, Any],
    template_fields: list[str],
    component: str,
) -> tuple[str, str] | None:
    aliases = set(VARIATION_ALIASES.get(component, (component,)))
    candidates: list[str] = []
    for field in template_fields:
        if _field_base(field) not in aliases:
            continue
        lowered = field.casefold()
        if lowered.endswith(".unit") or ".unit" in lowered:
            continue
        candidates.append(field)

    preferred = [field for field in candidates if "#1.value" in field.casefold()]
    for field in preferred + [field for field in candidates if field not in preferred]:
        value = _text(fields.get(field, ""))
        if value.strip():
            return field, value
    return None


def _new_mapping_report(mapping_source: str | Path, template_path: Path) -> dict[str, Any]:
    return {
        "checked": True,
        "mapping": str(mapping_source),
        "template": str(template_path),
        "row_count": 0,
        "ok": False,
        "status": "invalid",
        "errors": [],
        "warnings": [],
    }


def validate_mapping(
    mapping: dict[str, Any], template_path: Path, project_root: Path | None = None
) -> dict[str, Any]:
    """Validate an in-memory mapping against ``template_path``.

    This is the stable integration entry point used by the writer.  It never
    writes the workbook and always returns ``ok``, ``status``, ``errors`` and
    ``warnings``.
    """
    template_path = Path(template_path)
    report = _new_mapping_report("<in-memory>", template_path)
    if not isinstance(mapping, dict):
        _add_error(report, "mapping_not_object", "Mapping 顶层必须是 JSON object。")
        return report
    schema_version = mapping.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _add_error(
            report,
            "mapping_schema_version_invalid",
            "Mapping schema_version 必须为 2.0、2.1 或 2.2。",
            value=schema_version,
        )

    rows = mapping.get("rows")
    if not isinstance(rows, list) or not rows:
        _add_error(report, "rows_required", "Mapping 必须包含非空 rows 数组。")
        return report
    report["row_count"] = len(rows)

    declared_blocking_errors = mapping.get("blocking_errors")
    if not isinstance(declared_blocking_errors, list):
        _add_error(report, "blocking_errors_invalid", "Mapping blocking_errors 必须是数组。")
        declared_blocking_errors = []
    declared_warnings = mapping.get("warnings")
    if not isinstance(declared_warnings, list):
        _add_error(report, "warnings_invalid", "Mapping warnings 必须是数组。")
    manual_review_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    raw_manual_review = mapping.get("manual_review", [])
    if not isinstance(raw_manual_review, list):
        _add_error(report, "manual_review_invalid", "Mapping manual_review 必须是数组。")
        raw_manual_review = []
    if schema_version == "2.0" and raw_manual_review:
        _add_error(
            report,
            "manual_review_requires_v21",
            "Mapping 2.0 不允许 manual_review；请升级为 2.1。",
        )
    for index, item in enumerate(raw_manual_review, start=1):
        if not isinstance(item, dict):
            _add_error(
                report,
                "manual_review_item_invalid",
                "manual_review 项必须是 object。",
                index=index,
            )
            continue
        source_row = item.get("source_row")
        field = item.get("field")
        role = item.get("role")
        if (
            isinstance(source_row, bool)
            or not isinstance(source_row, int)
            or source_row < 2
            or not isinstance(field, str)
            or not field.strip()
            or role not in {"Parent", "Child", "Standalone"}
        ):
            _add_error(
                report,
                "manual_review_identity_invalid",
                "manual_review 必须包含有效 source_row、role 和 field。",
                index=index,
            )
            continue
        if item.get("value") != MANUAL_REVIEW_VALUE:
            _add_error(
                report,
                "manual_review_value_invalid",
                "manual_review.value 必须使用固定中文文本。",
                index=index,
                field=field,
            )
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            _add_error(
                report,
                "manual_review_reason_required",
                "manual_review 必须记录非空 reason。",
                index=index,
                field=field,
            )
        if not isinstance(item.get("data_definition"), dict):
            _add_error(
                report,
                "manual_review_definition_required",
                "manual_review 必须记录 data_definition object。",
                index=index,
                field=field,
            )
        if not isinstance(item.get("template_restriction"), dict):
            _add_error(
                report,
                "manual_review_restriction_required",
                "manual_review 必须记录 template_restriction object。",
                index=index,
                field=field,
            )
        key = (source_row, field)
        if key in manual_review_by_key:
            _add_error(
                report,
                "manual_review_duplicate",
                "同一来源行和技术字段不得重复登记 manual_review。",
                source_row=source_row,
                field=field,
            )
        manual_review_by_key[key] = item
    product_cells, confirmations, product_sheet = _mapping_evidence_context(
        mapping, report, template_path
    )

    task = mapping.get("task")
    gtin_status = ""
    result_status = ""
    task_scope = {
        "marketplace": "",
        "content_language": "",
        "product_type": "",
        "browse_node": "",
        "fill_mode": "",
    }
    if not isinstance(task, dict):
        _add_error(report, "task_required", "Mapping v2 必须包含 task object。")
    else:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            _add_error(report, "task_id_required", "task.task_id 必须是非空字符串。")
        for key in task_scope:
            value = task.get(key, "")
            if not isinstance(value, str) or not value.strip():
                _add_error(
                    report,
                    "task_scope_required",
                    "task 必须包含非空 marketplace、content_language、product_type、browse_node 和 fill_mode。",
                    field=key,
                )
            else:
                task_scope[key] = value.strip()
        if task_scope["fill_mode"] and task_scope["fill_mode"] not in FILL_MODES:
            _add_error(
                report,
                "task_fill_mode_invalid",
                "task.fill_mode 必须是 SAMPLE_GUIDED 或 NO_SAMPLE_CONFIRMED。",
                value=task_scope["fill_mode"],
            )
        gtin_status = task.get("gtin_status", "")
        if not isinstance(gtin_status, str) or gtin_status not in {"provided", "confirmed_exempt", "unknown"}:
            _add_error(
                report,
                "task_gtin_status_invalid",
                "task.gtin_status 必须是 provided、confirmed_exempt 或 unknown。",
                value=gtin_status,
            )
        result_status = task.get("result_status", "")
        allowed_result_statuses = {
            "DRAFT_NOT_FOR_UPLOAD",
            "LOCAL_VALIDATION_PASSED",
            "ACCEPTED_USER_CONFIRMED",
            "ACCEPTED_REPORT_VERIFIED",
        }
        if not isinstance(result_status, str) or result_status not in allowed_result_statuses:
            _add_error(
                report,
                "task_result_status_invalid",
                "task.result_status 必须是 PRD 定义的四种固定状态之一。",
                value=result_status,
            )
        elif result_status in {"ACCEPTED_USER_CONFIRMED", "ACCEPTED_REPORT_VERIFIED"}:
            _add_error(
                report,
                "accepted_status_not_writable",
                "ACCEPTED 状态只能在外部确认后登记，不能作为新工作簿写入请求。",
                value=result_status,
            )
        if gtin_status == "unknown":
            if result_status == "DRAFT_NOT_FOR_UPLOAD":
                _add_warning(
                    report,
                    "task_gtin_status_unknown_draft",
                    "GTIN 状态尚未确定；只允许生成明确标记为不可上传的草稿。",
                )
            else:
                _add_error(
                    report,
                    "task_gtin_status_unknown",
                    "task.gtin_status=unknown 时结果状态必须是 DRAFT_NOT_FOR_UPLOAD。",
                )
        report["task"] = {
            **task_scope,
            "task_id": task_id.strip() if isinstance(task_id, str) else "",
            "gtin_status": gtin_status,
            "result_status": result_status if isinstance(result_status, str) else None,
        }

    if result_status == "LOCAL_VALIDATION_PASSED" and declared_blocking_errors:
        _add_error(
            report,
            "declared_blocking_errors_present",
            "LOCAL_VALIDATION_PASSED 的 Mapping 不得包含任何 blocking_errors。",
            blocking_errors=declared_blocking_errors,
        )

    if product_sheet is not None:
        missing_headers = product_sheet.get("missing_required_headers") or []
        if missing_headers:
            _add_missing_value_issue(
                report,
                result_status,
                "product_required_headers_missing",
                "产品信息表缺少最低必需表头。",
                headers=missing_headers,
                sheet=product_sheet.get("sheet_name"),
            )
        if not product_sheet.get("rows"):
            _add_missing_value_issue(
                report,
                result_status,
                "product_rows_empty",
                "产品信息表没有可处理的数据行。",
                sheet=product_sheet.get("sheet_name"),
            )

    try:
        context = build_context(None, template_path, None)
    except SystemExit as exc:
        _add_error(report, "template_context_failed", "空白模板上下文提取失败。", error=str(exc))
        return report
    except Exception as exc:
        _add_error(report, "template_context_failed", "空白模板上下文提取失败。", error=str(exc))
        return report

    template_fields = list(context["template"]["fields"])
    template_field_set = set(template_fields)
    definitions = context.get("data_definitions") or {}
    metadata = context.get("template_metadata") or {}
    expected_resolution_by_row: dict[int, dict[str, Any]] = {}
    if schema_version == EXTENDED_RULE_VERSION and product_sheet is not None:
        resolution = product_resolution_hints(
            product_sheet,
            context["template"],
            {},
            context.get("valid_values_by_field") or {},
            context.get("dropdown_values_by_field") or {},
        )
        expected_resolution_by_row = {
            item["source_row"]: {
                hint["field"]: hint
                for hint in item.get("hints", [])
                if hint.get("value") is not None
                and hint.get("status") in {
                    "resolved",
                    "resolved_explicit",
                    "resolved_core_keyword",
                    "fallback_from_product",
                }
            }
            for item in resolution.get("rows", [])
        }
    templates = mapping.get("templates")
    if not isinstance(templates, dict):
        _add_error(report, "templates_required", "Mapping v2 必须包含 templates object。")
        templates = {}
    blank_hash = templates.get("blank_sha256")
    if blank_hash != metadata.get("file_sha256"):
        _add_error(
            report,
            "blank_template_hash_mismatch",
            "Mapping 记录的 blank_sha256 与当前空白模板不一致。",
            mapping_value=blank_hash,
            template_value=metadata.get("file_sha256"),
        )
    blank_schema = templates.get("blank_schema_fingerprint")
    if blank_schema != metadata.get("schema_fingerprint"):
        _add_error(
            report,
            "blank_schema_fingerprint_mismatch",
            "Mapping 记录的 blank_schema_fingerprint 与当前空白模板不一致。",
            mapping_value=blank_schema,
            template_value=metadata.get("schema_fingerprint"),
        )
    if task_scope["fill_mode"] == "SAMPLE_GUIDED":
        if not isinstance(templates.get("sample_sha256"), str) or not templates["sample_sha256"].strip():
            _add_error(report, "sample_hash_required", "SAMPLE_GUIDED 必须记录 sample_sha256。")
        if templates.get("sample_verification") not in {"user_confirmed", "report_verified"}:
            _add_error(
                report,
                "sample_verification_invalid",
                "SAMPLE_GUIDED 只能使用 user_confirmed 或 report_verified 样板。",
                value=templates.get("sample_verification"),
            )
        if templates.get("sample_schema_compatibility") not in {
            "exact_schema",
            "remappable_schema",
            "field_subset_compatible",
        }:
            _add_error(
                report,
                "sample_schema_compatibility_invalid",
                "SAMPLE_GUIDED 必须记录允许的样板结构兼容结果。",
                value=templates.get("sample_schema_compatibility"),
            )
    elif task_scope["fill_mode"] == "NO_SAMPLE_CONFIRMED":
        if any(
            _nonblank(templates.get(field))
            for field in (
                "sample_entry_id",
                "sample_sha256",
                "sample_verification",
                "sample_schema_compatibility",
            )
        ):
            _add_error(
                report,
                "sample_metadata_forbidden_without_sample",
                "NO_SAMPLE_CONFIRMED 不得携带任何样板索引或认证元数据。",
            )
    _validate_template_selection(
        report, templates, task_scope, template_path, project_root
    )
    sample_expected_fields = (
        _sample_expected_fields(
            report, templates, task_scope, template_path, project_root
        )
        if manual_review_by_key
        else {}
    )

    field_plan_must: dict[str, set[str]] = {}
    field_plan_rule: dict[str, set[str]] = {}
    field_plan_sample: dict[str, set[str]] = {}
    field_plan_evidence: set[str] = set()
    field_plan = mapping.get("field_plan")
    if not isinstance(field_plan, dict):
        _add_error(report, "field_plan_required", "Mapping v2 必须包含 field_plan object。")
    else:
        must_plan = field_plan.get("must_fill")
        if not isinstance(must_plan, dict):
            _add_error(report, "field_plan_must_fill_invalid", "field_plan.must_fill 必须是按角色分组的 object。")
        else:
            for role, fields in must_plan.items():
                if role not in {"Parent", "Child", "Standalone"} or not isinstance(fields, list) or any(
                    not isinstance(field, str) for field in fields
                ):
                    _add_error(report, "field_plan_must_fill_invalid", "field_plan.must_fill 的角色和值格式无效。", role=role)
                    continue
                field_plan_must[role] = set(fields)
        rule_plan = field_plan.get("rule_default", {})
        if schema_version in RULE_DEFAULT_VERSIONS:
            if not isinstance(rule_plan, dict):
                _add_error(
                    report,
                    "field_plan_rule_default_invalid",
                    "Mapping 2.1/2.2 的 field_plan.rule_default 必须是按角色分组的 object。",
                )
            else:
                for role, fields in rule_plan.items():
                    if (
                        role not in {"Parent", "Child", "Standalone"}
                        or not isinstance(fields, list)
                        or any(not isinstance(field, str) for field in fields)
                    ):
                        _add_error(
                            report,
                            "field_plan_rule_default_invalid",
                            "field_plan.rule_default 的角色和值格式无效。",
                            role=role,
                        )
                        continue
                    field_plan_rule[role] = set(fields)
        elif rule_plan:
            _add_error(
                report,
                "field_plan_rule_default_requires_v21",
                "Mapping 2.0 不允许 field_plan.rule_default。",
            )
        sample_plan = field_plan.get("sample_preferred")
        if not isinstance(sample_plan, dict):
            _add_error(report, "field_plan_sample_preferred_invalid", "field_plan.sample_preferred 必须是按角色分组的 object。")
        elif task_scope["fill_mode"] == "NO_SAMPLE_CONFIRMED" and any(
            isinstance(fields, list) and fields for fields in sample_plan.values()
        ):
            _add_error(
                report,
                "field_plan_sample_preferred_forbidden_without_sample",
                "NO_SAMPLE_CONFIRMED 的 field_plan.sample_preferred 必须为空。",
            )
        if isinstance(sample_plan, dict):
            for role, fields in sample_plan.items():
                if role not in {"Parent", "Child", "Standalone"} or not isinstance(fields, list) or any(
                    not isinstance(field, str) for field in fields
                ):
                    _add_error(report, "field_plan_sample_preferred_invalid", "field_plan.sample_preferred 的角色和值格式无效。", role=role)
                    continue
                field_plan_sample[role] = set(fields)
        evidence_plan = field_plan.get("evidence_fillable")
        if not isinstance(evidence_plan, list) or any(not isinstance(field, str) for field in evidence_plan):
            _add_error(report, "field_plan_evidence_fillable_invalid", "field_plan.evidence_fillable 必须是数组。")
        else:
            field_plan_evidence = set(evidence_plan)
        for role in {"Parent", "Child", "Standalone"}:
            sets = {
                "must_fill": field_plan_must.get(role, set()),
                "rule_default": field_plan_rule.get(role, set()),
                "sample_preferred": field_plan_sample.get(role, set()),
                "evidence_fillable": field_plan_evidence,
            }
            ordered_sets = ("must_fill", "rule_default", "sample_preferred", "evidence_fillable")
            for left_index, left in enumerate(ordered_sets):
                for right in ordered_sets[left_index + 1:]:
                    overlap = sorted(sets[left] & sets[right])
                    if overlap:
                        _add_error(
                            report,
                            "field_plan_sets_overlap",
                            "字段决策集合必须按 must_fill、rule_default、sample_preferred、evidence_fillable 优先级互斥。",
                            role=role,
                            sets=[left, right],
                            fields=overlap,
                        )
    scope_checks = {
        "marketplace": (task_scope["marketplace"], metadata.get("marketplace", "")),
        "content_language": (task_scope["content_language"], metadata.get("content_language", "")),
    }
    for key, (actual, expected) in scope_checks.items():
        if actual and not expected:
            _add_error(
                report,
                "template_scope_metadata_missing",
                "空白模板缺少用于确认任务范围的元数据。",
                field=key,
            )
        elif actual and actual != expected:
            _add_error(
                report,
                "task_template_scope_mismatch",
                "Mapping task 范围与空白模板元数据不匹配。",
                field=key,
                task_value=actual,
                template_value=expected,
            )
    for key, metadata_key in (("product_type", "product_types"), ("browse_node", "browse_nodes")):
        actual = task_scope[key]
        expected_values = metadata.get(metadata_key) or []
        if actual and not expected_values:
            _add_error(
                report,
                "template_scope_metadata_missing",
                "空白模板缺少用于确认任务范围的候选元数据。",
                field=key,
            )
        elif actual and actual not in expected_values:
            _add_error(
                report,
                "task_template_scope_mismatch",
                "Mapping task 范围不属于空白模板允许范围。",
                field=key,
                task_value=actual,
                template_values=expected_values,
            )
    allowed_by_field: dict[str, set[str]] = defaultdict(set)
    for source in (context.get("valid_values_by_field") or {}, context.get("dropdown_values_by_field") or {}):
        for field, values in source.items():
            allowed_by_field[field].update(_text(value) for value in values if _nonblank(value))

    fields_by_base: dict[str, list[str]] = defaultdict(list)
    for field in template_fields:
        fields_by_base[_field_base(field)].append(field)
    value_unit_pairs = [
        (field, field[: -len(".value")] + ".unit")
        for field in template_fields
        if field.endswith(".value")
        and field[: -len(".value")] + ".unit" in template_field_set
    ]

    sku_fields = fields_by_base.get("contribution_sku", [])
    brand_fields = fields_by_base.get("brand", [])
    model_number_fields = fields_by_base.get("model_number", [])
    model_name_fields = fields_by_base.get("model_name", [])
    manufacturer_fields = fields_by_base.get("manufacturer", [])
    number_of_items_fields = fields_by_base.get("number_of_items", [])
    part_number_fields = fields_by_base.get("part_number", [])
    mounting_type_fields = fields_by_base.get("mounting_type", [])
    fulfillment_fields = fields_by_base.get("fulfillment_availability", [])
    product_type_fields = fields_by_base.get("product_type", [])
    action_fields = [field for field in template_fields if field == "::record_action"]
    parentage_fields = fields_by_base.get("parentage_level", [])
    parent_sku_fields = [field for field in template_fields if ".parent_sku" in field.casefold()]
    theme_fields = fields_by_base.get("variation_theme", [])
    product_id_type_fields = [field for field in template_fields if "product_id_type" in field.casefold()]
    product_id_value_fields = [field for field in template_fields if "product_id_value" in field.casefold()]

    required_fields = [
        field
        for field, definition in definitions.items()
        if field in template_field_set and _required_status(definition.get("required", ""))
    ]
    context_must_fill = (context.get("field_decision") or {}).get("must_fill") or {}
    context_rule_default = (context.get("field_decision") or {}).get("rule_default") or {}

    row_infos: list[dict[str, Any]] = []
    sku_to_rows: dict[str, list[int]] = defaultdict(list)
    product_rows_by_number = {
        row["row_number"]: row
        for row in (product_sheet or {}).get("rows", [])
        if isinstance(row.get("row_number"), int)
    }
    seen_source_rows: set[int] = set()
    manual_marker_keys_seen: set[tuple[int, str]] = set()

    for index, raw_item in enumerate(rows, start=1):
        if not isinstance(raw_item, dict):
            _add_error(report, "row_not_object", "rows 中的每一项都必须是 object。", row_index=index)
            row_infos.append({"index": index, "item": {}, "fields": {}, "role": None, "sku": ""})
            continue

        details = _row_details(index, raw_item)
        source_row = raw_item.get("source_row")
        source_key = raw_item.get("source_key")
        if isinstance(source_row, bool) or not isinstance(source_row, int) or source_row < 2:
            _add_error(
                report,
                "source_row_invalid",
                "rows[].source_row 必须是产品信息表中的数据行号。",
                **details,
            )
        else:
            if source_row in seen_source_rows:
                _add_error(report, "source_row_duplicate", "同一产品来源行不得重复映射。", **details)
            seen_source_rows.add(source_row)
            if product_sheet is not None and source_row not in product_rows_by_number:
                _add_error(
                    report,
                    "source_row_not_found",
                    "source_row 不存在于产品信息表的数据行中。",
                    **details,
                )
            expected_key = f"product-row-{source_row}"
            if source_key != expected_key:
                _add_error(
                    report,
                    "source_key_mismatch",
                    "source_key 必须由产品来源行确定，格式为 product-row-<source_row>。",
                    expected=expected_key,
                    value=source_key,
                    **details,
                )
        field_records = raw_item.get("fields")
        if not isinstance(field_records, dict) or not field_records:
            _add_error(report, "fields_required", "每个 Mapping 行都必须包含非空 fields object。", **details)
            field_records = {}

        fields: dict[str, Any] = {}
        for field, record in field_records.items():
            if not isinstance(field, str):
                _add_error(report, "field_name_not_string", "字段名必须是字符串。", field=repr(field), **details)
                continue
            if field not in template_field_set:
                _add_error(report, "unknown_field", "Mapping 字段不存在于空白模板技术字段行。", field=field, **details)
            fields[field] = _field_record_value(
                report,
                field,
                record,
                details,
                result_status,
                task_scope["fill_mode"],
                product_cells,
                confirmations,
                str(schema_version),
            )

        if schema_version == EXTENDED_RULE_VERSION and isinstance(source_row, int):
            expected_hints = expected_resolution_by_row.get(source_row, {})
            for field, record in field_records.items():
                if not isinstance(record, dict):
                    continue
                source = record.get("source")
                expected = expected_hints.get(field)
                if (
                    not isinstance(source, dict)
                    or source.get("type") != "model_extracted"
                    or not isinstance(expected, dict)
                ):
                    continue
                if _text(record.get("value")).strip() != _text(expected.get("value")).strip():
                    _add_error(
                        report,
                        "model_extracted_value_mismatch",
                        "Mapping 2.2 的结构化提取值与产品来源行的确定性换算结果不一致。",
                        field=field,
                        expected=expected.get("value"),
                        value=record.get("value"),
                        **details,
                    )

        for field, candidates in allowed_by_field.items():
            if field not in fields or not _nonblank(fields[field]):
                continue
            value = _text(fields[field])
            if value not in candidates:
                ordered = sorted(candidates)
                record = field_records.get(field)
                source = record.get("source") if isinstance(record, dict) else {}
                if (
                    schema_version in RULE_DEFAULT_VERSIONS
                    and result_status == "DRAFT_NOT_FOR_UPLOAD"
                    and value == MANUAL_REVIEW_VALUE
                    and isinstance(source, dict)
                    and source.get("type") == "manual_review_marker"
                ):
                    _add_warning(
                        report,
                        "manual_review_bypasses_allowed_value_in_draft",
                        "草稿中的人工核对提示不属于模板枚举，文件不得上传。",
                        field=field,
                        **details,
                    )
                else:
                    _add_error(
                        report,
                        "invalid_allowed_value",
                        "字段值不在模板允许值中。",
                        field=field,
                        value=value,
                        allowed_count=len(ordered),
                        allowed_preview=ordered[:20],
                        **details,
                    )

        for value_field, unit_field in value_unit_pairs:
            has_value = _nonblank(fields.get(value_field, ""))
            has_unit = _nonblank(fields.get(unit_field, ""))
            if has_value == has_unit:
                continue
            _add_missing_value_issue(
                report,
                result_status,
                "value_unit_pair_incomplete",
                "数值字段与单位字段必须成对填写。",
                value_field=value_field,
                unit_field=unit_field,
                missing_field=unit_field if has_value else value_field,
                **details,
            )

        item_role_raw = raw_item.get("role")
        item_role = _role_from_value(item_role_raw) if _nonblank(item_role_raw) else None
        if _nonblank(item_role_raw) and item_role is None:
            _add_error(report, "invalid_trace_role", "role 只能是 Parent、Child 或 Standalone。", value=item_role_raw, **details)

        parentage_value = _single_value(
            report,
            fields,
            parentage_fields,
            "conflicting_parentage",
            "父子角色",
            details,
        )
        field_role = _role_from_value(parentage_value) if parentage_value else None
        if parentage_value and field_role not in {"Parent", "Child"}:
            _add_error(report, "invalid_parentage", "父子关系技术字段必须为 Parent 或 Child。", value=parentage_value, **details)

        if item_role and field_role and item_role != field_role:
            _add_error(
                report,
                "role_parentage_conflict",
                "Mapping role 与父子关系技术字段不一致。",
                role=item_role,
                parentage=field_role,
                **details,
            )
        role = field_role or item_role or "Standalone"
        if not field_role and not item_role:
            _add_error(
                report,
                "row_role_required",
                "无法从 role 或父子关系技术字段确认行角色；不得默认推断为独立商品。",
                **details,
            )
        if role in {"Parent", "Child"} and not field_role:
            _add_error(report, "parentage_field_required", "父体或子体行必须显式填写父子关系技术字段。", role=role, **details)
        if isinstance(source_row, int) and source_row in product_rows_by_number:
            product_role = _product_row_role(product_rows_by_number[source_row])
            if role != product_role:
                _add_error(
                    report,
                    "source_row_role_mismatch",
                    "Mapping 行角色与产品信息表来源行不一致。",
                    mapping_role=role,
                    product_role=product_role,
                    **details,
                )
        variation_theme = (
            _single_value(
                report,
                fields,
                theme_fields,
                "conflicting_variation_theme",
                "变体主题",
                details,
            )
            or "NONE"
        )
        expected_sample_fields = sample_expected_fields.get(
            (role, norm_label(variation_theme)),
            set(),
        )
        for field, record in field_records.items():
            source = record.get("source") if isinstance(record, dict) else {}
            if not isinstance(source, dict) or source.get("type") != "manual_review_marker":
                continue
            if not isinstance(source_row, int):
                continue
            marker_key = (source_row, field)
            manual_marker_keys_seen.add(marker_key)
            review_item = manual_review_by_key.get(marker_key)
            if review_item is None:
                _add_error(
                    report,
                    "manual_review_entry_missing",
                    "manual_review_marker 缺少对应的顶层 manual_review 记录。",
                    field=field,
                    **details,
                )
            elif review_item.get("role") != role:
                _add_error(
                    report,
                    "manual_review_role_mismatch",
                    "manual_review 角色与 Mapping 行角色不一致。",
                    field=field,
                    **details,
                )
            if field not in expected_sample_fields:
                _add_error(
                    report,
                    "manual_review_field_not_in_sample",
                    "中文提示只能用于同角色、同变体主题样板实际填写过的字段。",
                    field=field,
                    role=role,
                    variation_theme=variation_theme,
                    **details,
                )

        sku = _single_value(report, fields, sku_fields, "conflicting_sku", "SKU", details)
        if sku:
            sku_to_rows[_normalized(sku)].append(index)

        declared_raw = raw_item.get("must_fill")
        declared_must_fill: list[str] = []
        if not isinstance(declared_raw, list):
            _add_missing_value_issue(
                report,
                result_status,
                "row_must_fill_required",
                "每个 Mapping 行都必须声明 rows[].must_fill 技术字段列表。",
                **details,
            )
        else:
            for field in declared_raw:
                if not isinstance(field, str):
                    _add_error(report, "row_must_fill_field_invalid", "rows[].must_fill 只能包含技术字段名字符串。", **details)
                    continue
                if field not in template_field_set:
                    _add_error(
                        report,
                        "row_must_fill_unknown_field",
                        "rows[].must_fill 包含空白模板中不存在的技术字段。",
                        field=field,
                        **details,
                    )
                    continue
                if field not in declared_must_fill:
                    declared_must_fill.append(field)

        required_reasons: dict[str, list[str]] = defaultdict(list)
        for field in sku_fields + product_type_fields + action_fields:
            required_reasons[field].append("core")
        for field in required_fields:
            required_reasons[field].append("data_definitions_required")
        expected_for_role = [
            field for field in context_must_fill.get(role, []) if field in template_field_set
        ]
        for field in expected_for_role:
            required_reasons[field].append("template_role_must_fill")
        for field in declared_must_fill:
            required_reasons[field].append("row_declared_must_fill")

        missing_declarations = sorted(set(expected_for_role) - set(declared_must_fill))
        if missing_declarations:
            _add_missing_value_issue(
                report,
                result_status,
                "row_must_fill_incomplete",
                "rows[].must_fill 未覆盖模板为当前角色确定的必填字段。",
                fields=missing_declarations,
                **details,
            )

        if schema_version in RULE_DEFAULT_VERSIONS:
            expected_rule_fields = [
                field
                for field in context_rule_default.get(role, [])
                if field in template_field_set
                and (
                    schema_version == EXTENDED_RULE_VERSION
                    or _field_base(field) == "condition_type"
                )
            ]
            missing_rule_plan = sorted(
                set(expected_rule_fields) - field_plan_rule.get(role, set())
            )
            if missing_rule_plan:
                _add_error(
                    report,
                    "row_rule_default_incomplete",
                    "Mapping 当前版本必须为当前角色登记全部适用的规则控制字段。",
                    fields=missing_rule_plan,
                    **details,
                )
            for field in expected_rule_fields:
                record = field_records.get(field)
                if not isinstance(record, dict) or not _nonblank(record.get("value")):
                    _add_error(
                        report,
                        "rule_default_value_required",
                        "规则控制字段必须提供非空值。",
                        field=field,
                        **details,
                    )
                elif record.get("decision_set") != "rule_default":
                    _add_error(
                        report,
                        "rule_default_decision_set_mismatch",
                        "固定业务规则字段必须使用 decision_set=rule_default。",
                        field=field,
                        **details,
                    )

            condition_values = [
                fields.get(field) for field in expected_rule_fields
                if _field_base(field) == "condition_type"
            ]
            if condition_values and any(_normalized(value) != "new" for value in condition_values):
                _add_error(
                    report,
                    "item_condition_new_required",
                    "Item Condition 必须统一填写目标枚举 New。",
                    **details,
                )

            if schema_version == EXTENDED_RULE_VERSION and role in {"Child", "Standalone"}:
                model_number = _single_value(
                    report, fields, model_number_fields, "conflicting_model_number", "Model Number", details
                )
                if not sku or _normalized(model_number) != _normalized(sku):
                    _add_error(
                        report,
                        "model_number_must_equal_sku",
                        "Mapping 2.2 的 Model Number 必须严格等于当前行 SKU。",
                        sku=sku,
                        value=model_number,
                        **details,
                    )

                brand = _single_value(
                    report, fields, brand_fields, "conflicting_brand", "Brand", details
                )
                manufacturer = _single_value(
                    report,
                    fields,
                    manufacturer_fields,
                    "conflicting_manufacturer",
                    "Manufacturer",
                    details,
                )
                if not brand or _normalized(manufacturer) != _normalized(brand):
                    _add_error(
                        report,
                        "manufacturer_must_equal_brand",
                        "Mapping 2.2 的 Manufacturer 必须严格等于当前行品牌。",
                        brand=brand,
                        value=manufacturer,
                        **details,
                    )

                number_of_items = _single_value(
                    report,
                    fields,
                    number_of_items_fields,
                    "conflicting_number_of_items",
                    "Number of Items",
                    details,
                )
                if not re.fullmatch(r"[1-9][0-9]*", _text(number_of_items).strip()):
                    _add_error(
                        report,
                        "number_of_items_invalid",
                        "Number of Items 必须是正整数；无明确装数时使用 1。",
                        value=number_of_items,
                        **details,
                    )

                model_name = _single_value(
                    report, fields, model_name_fields, "conflicting_model_name", "Model Name", details
                )
                part_number = _single_value(
                    report, fields, part_number_fields, "conflicting_part_number", "Part Number", details
                )
                model_name_record = next(
                    (field_records.get(field) for field in model_name_fields if field in field_records),
                    None,
                )
                part_number_record = next(
                    (field_records.get(field) for field in part_number_fields if field in field_records),
                    None,
                )
                def fallback_rule(record: Any, rule_id: str) -> bool:
                    source = record.get("source") if isinstance(record, dict) else None
                    return bool(
                        isinstance(source, dict)
                        and source.get("type") == "model_rule"
                        and source.get("rule_id") == rule_id
                    )
                if (
                    fallback_rule(model_name_record, "rule:model-name-core-keyword-fallback")
                    and fallback_rule(part_number_record, "rule:part-number-core-keyword-fallback")
                    and _normalized(model_name) != _normalized(part_number)
                ):
                    _add_error(
                        report,
                        "core_keyword_fallback_mismatch",
                        "Model Name 与 Part Number 同时使用核心关键词回退时必须一致。",
                        model_name=model_name,
                        part_number=part_number,
                        **details,
                    )

                fulfillment = _single_value(
                    report,
                    fields,
                    fulfillment_fields,
                    "conflicting_fulfillment",
                    "Fulfillment",
                    details,
                )
                fulfillment_record = next(
                    (field_records.get(field) for field in fulfillment_fields if field in field_records),
                    None,
                )
                fulfillment_source = (
                    fulfillment_record.get("source") if isinstance(fulfillment_record, dict) else {}
                )
                if (
                    isinstance(fulfillment_source, dict)
                    and fulfillment_source.get("type") == "business_rule"
                    and fulfillment_source.get("reference") == "rule:fulfillment-default-fba"
                    and _normalized(fulfillment) != "fulfillment by amazon (na)"
                ):
                    _add_error(
                        report,
                        "fulfillment_fba_default_mismatch",
                        "未提供发货方式时必须使用目标模板的 FBA 精确候选值。",
                        value=fulfillment,
                        **details,
                    )

        for field, reasons in required_reasons.items():
            if role == "Parent" and field in product_id_type_fields + product_id_value_fields:
                continue
            if (
                gtin_status == "unknown"
                and result_status == "DRAFT_NOT_FOR_UPLOAD"
                and field in product_id_type_fields + product_id_value_fields
            ):
                continue
            if not _nonblank(fields.get(field, "")):
                definition = definitions.get(field, {})
                _add_missing_value_issue(
                    report,
                    result_status,
                    "missing_must_fill_value",
                    "缺少当前行 must_fill/Required 字段值。",
                    field=field,
                    label=definition.get("label", ""),
                    reasons=sorted(set(reasons)),
                    **details,
                )
                continue
            record = field_records.get(field)
            if isinstance(record, dict) and record.get("decision_set") != "must_fill":
                _add_error(
                    report,
                    "must_fill_decision_set_mismatch",
                    "Required/must_fill 字段记录的 decision_set 必须为 must_fill。",
                    field=field,
                    value=record.get("decision_set"),
                    **details,
                )

        undeclared_records = sorted(
            field
            for field, record in field_records.items()
            if isinstance(field, str)
            and isinstance(record, dict)
            and record.get("decision_set") == "must_fill"
            and field not in declared_must_fill
        )
        if undeclared_records:
            _add_missing_value_issue(
                report,
                result_status,
                "must_fill_record_not_declared",
                "字段记录标记为 must_fill，但未列入 rows[].must_fill。",
                fields=undeclared_records,
                **details,
            )

        for field, record in field_records.items():
            if not isinstance(field, str) or not isinstance(record, dict):
                continue
            decision = record.get("decision_set")
            if decision == "must_fill" and field not in field_plan_must.get(role, set()):
                _add_error(
                    report,
                    "field_plan_membership_mismatch",
                    "must_fill 字段未登记在当前角色的 field_plan.must_fill。",
                    field=field,
                    role=role,
                    **details,
                )
            elif decision == "rule_default" and field not in field_plan_rule.get(role, set()):
                _add_error(
                    report,
                    "field_plan_membership_mismatch",
                    "rule_default 字段未登记在当前角色的 field_plan.rule_default。",
                    field=field,
                    role=role,
                    **details,
                )
            elif decision == "sample_preferred" and field not in field_plan_sample.get(role, set()):
                _add_error(
                    report,
                    "field_plan_membership_mismatch",
                    "sample_preferred 字段未登记在当前角色的 field_plan.sample_preferred。",
                    field=field,
                    role=role,
                    **details,
                )
            elif decision == "evidence_fillable" and field not in field_plan_evidence:
                _add_error(
                    report,
                    "field_plan_membership_mismatch",
                    "evidence_fillable 字段未登记在 field_plan.evidence_fillable。",
                    field=field,
                    role=role,
                    **details,
                )

        id_type = _single_value(
            report,
            fields,
            product_id_type_fields,
            "conflicting_product_id_type",
            "商品编号类型",
            details,
        )
        id_value = _single_value(
            report,
            fields,
            product_id_value_fields,
            "conflicting_product_id_value",
            "商品 ID",
            details,
        )
        if role == "Parent":
            if id_type or id_value:
                _add_error(report, "parent_product_id_forbidden", "父体行不得填写商品编号类型或商品 ID。", **details)
        elif gtin_status == "provided":
            if _is_gtin_exempt(id_type):
                _add_error(report, "gtin_status_conflict", "task.gtin_status=provided 时不得使用 GTIN Exempt。", **details)
            elif id_type and not id_value:
                _add_error(report, "product_id_value_required", "已填写商品编号类型，但缺少商品 ID。", **details)
            elif id_value and not id_type:
                _add_error(report, "product_id_type_required", "已填写商品 ID，但缺少商品编号类型。", **details)
            elif not id_type and not id_value:
                _add_error(report, "provided_gtin_pair_required", "task.gtin_status=provided 时必须成对填写商品编号类型和商品 ID。", **details)
            else:
                normalized_type = re.sub(r"\s+", "", id_type).upper()
                normalized_id = id_value.strip()
                expected_lengths: set[int] | None = None
                if normalized_type == "UPC":
                    expected_lengths = {12}
                elif normalized_type == "EAN":
                    expected_lengths = {8, 13}
                elif normalized_type == "GTIN":
                    expected_lengths = {8, 12, 13, 14}

                if expected_lengths is not None:
                    if not normalized_id.isdigit() or len(normalized_id) not in expected_lengths:
                        _add_error(
                            report,
                            "product_id_format_invalid",
                            "UPC/EAN/GTIN 必须是类型对应长度的纯数字。",
                            product_id_type=id_type,
                            product_id=id_value,
                            allowed_lengths=sorted(expected_lengths),
                            **details,
                        )
                    elif not _gtin_check_digit_valid(normalized_id):
                        _add_error(
                            report,
                            "product_id_checksum_invalid",
                            "UPC/EAN/GTIN 校验位不正确。",
                            product_id_type=id_type,
                            product_id=id_value,
                            **details,
                        )
                elif normalized_type == "ASIN" and not re.fullmatch(r"[A-Z0-9]{10}", normalized_id):
                    _add_error(
                        report,
                        "asin_format_invalid",
                        "ASIN 必须是 10 位大写字母或数字。",
                        product_id=id_value,
                        **details,
                    )
        elif gtin_status == "confirmed_exempt":
            if not _is_gtin_exempt(id_type):
                _add_error(
                    report,
                    "explicit_gtin_exempt_required",
                    "task.gtin_status=confirmed_exempt 时必须在商品编号类型中明确填写 GTIN Exempt。",
                    **details,
                )
            if id_value:
                _add_error(report, "gtin_exempt_with_value", "明确 GTIN Exempt 时商品 ID 必须留空。", **details)
        else:
            if id_type or id_value:
                _add_error(
                    report,
                    "gtin_status_conflict",
                    "task.gtin_status=unknown 与已填写的商品编号信息不一致；应改为 provided 或 confirmed_exempt。",
                    **details,
                )
            if bool(id_type) != bool(id_value) and not _is_gtin_exempt(id_type):
                _add_error(report, "product_id_pair_incomplete", "商品编号类型与商品 ID 必须成对填写。", **details)

        parent_sku = _single_value(
            report,
            fields,
            parent_sku_fields,
            "conflicting_parent_sku",
            "父 SKU",
            details,
        )
        theme = _single_value(
            report,
            fields,
            theme_fields,
            "conflicting_variation_theme",
            "变体主题",
            details,
        )
        row_infos.append(
            {
                "index": index,
                "item": raw_item,
                "fields": fields,
                "role": role,
                "sku": sku,
                "parent_sku": parent_sku,
                "theme": theme,
                "details": details,
            }
        )

    if product_sheet is not None:
        missing_source_rows = sorted(set(product_rows_by_number) - seen_source_rows)
        if missing_source_rows:
            _add_error(
                report,
                "product_rows_not_mapped",
                "产品信息表中的数据行必须一一进入当前商品家族 Mapping。",
                source_rows=missing_source_rows,
            )

    for normalized_sku, indexes in sku_to_rows.items():
        if normalized_sku and len(indexes) > 1:
            _add_error(report, "duplicate_sku", "同一批次内 SKU 重复。", row_indexes=indexes)

    parent_rows = [info for info in row_infos if info["role"] == "Parent"]
    child_rows = [info for info in row_infos if info["role"] == "Child"]
    standalone_rows = [info for info in row_infos if info["role"] == "Standalone"]
    if parent_rows or child_rows:
        if len(parent_rows) != 1:
            _add_error(
                report,
                "single_parent_required",
                "父子任务必须且只能包含一个父体。",
                parent_row_indexes=[info["index"] for info in parent_rows],
            )
        if not child_rows:
            _add_error(report, "children_required", "父子任务必须至少包含一个子体。")
        if standalone_rows:
            _add_error(
                report,
                "mixed_standalone_and_family",
                "一个父子任务中不得混入独立商品。",
                standalone_row_indexes=[info["index"] for info in standalone_rows],
            )
    elif len(standalone_rows) != 1:
        _add_error(
            report,
            "single_standalone_required",
            "非变体任务必须且只能包含一个独立商品，不能在一个任务中混入多个商品家族。",
            standalone_row_indexes=[info["index"] for info in standalone_rows],
        )

    parents: dict[str, dict[str, Any]] = {}
    for info in row_infos:
        if info["role"] == "Parent" and info["sku"]:
            parents[_normalized(info["sku"])] = info

    child_count: dict[str, int] = defaultdict(int)
    combinations: dict[tuple[Any, ...], int] = {}
    for info in row_infos:
        role = info["role"]
        details = info.get("details", {"row_index": info["index"]})
        parent_sku = info.get("parent_sku", "")
        theme = info.get("theme", "")

        if role == "Parent":
            if parent_sku:
                _add_error(report, "parent_must_not_reference_parent", "父体行不得填写父 SKU。", **details)
            if not theme:
                _add_error(report, "parent_variation_theme_required", "父体行必须填写变体主题。", **details)
            continue

        if role == "Standalone":
            if parent_sku:
                _add_error(report, "standalone_parent_sku_forbidden", "单体商品不得填写父 SKU。", **details)
            if theme:
                _add_error(report, "standalone_variation_theme_forbidden", "单体商品不得填写变体主题。", **details)
            continue

        if not parent_sku:
            _add_error(report, "child_parent_sku_required", "子体行必须填写父 SKU。", **details)
            continue
        parent_key = _normalized(parent_sku)
        parent = parents.get(parent_key)
        if parent is None:
            _add_error(report, "child_parent_not_found", "子体引用的父 SKU 不存在于本次 Mapping。", parent_sku=parent_sku, **details)
        else:
            child_count[parent_key] += 1
            parent_theme = parent.get("theme", "")
            if parent_theme and theme and _normalized(parent_theme) != _normalized(theme):
                _add_error(
                    report,
                    "variation_theme_mismatch",
                    "子体变体主题与父体不一致。",
                    parent_theme=parent_theme,
                    child_theme=theme,
                    **details,
                )

        if not theme:
            _add_error(report, "child_variation_theme_required", "子体行必须填写变体主题。", **details)
            continue

        component_values: list[tuple[str, str]] = []
        missing_component = False
        for component in _theme_components(theme):
            found = _variation_value(info["fields"], template_fields, component)
            if found is None:
                missing_component = True
                _add_error(
                    report,
                    "variation_attribute_required",
                    "子体缺少变体主题要求的属性。",
                    theme=theme,
                    component=component,
                    **details,
                )
            else:
                field, value = found
                component_values.append((component, _normalized(value)))

        if not missing_component:
            combination_key: tuple[Any, ...] = (
                parent_key,
                _normalized(theme),
                tuple(component_values),
            )
            previous = combinations.get(combination_key)
            if previous is not None:
                _add_error(
                    report,
                    "duplicate_variation_combination",
                    "同一父体下存在重复的子体变体属性组合。",
                    first_row_index=previous,
                    duplicate_row_index=info["index"],
                    parent_sku=parent_sku,
                    theme=theme,
                    combination={component: value for component, value in component_values},
                )
            else:
                combinations[combination_key] = info["index"]

    for parent_key, parent in parents.items():
        if child_count.get(parent_key, 0) == 0:
            _add_error(report, "parent_without_children", "父体行没有任何有效子体引用。", **parent["details"])

    orphaned_manual_review = sorted(
        set(manual_review_by_key) - manual_marker_keys_seen
    )
    if orphaned_manual_review:
        _add_error(
            report,
            "manual_review_entry_orphaned",
            "顶层 manual_review 存在没有对应字段记录的项目。",
            entries=[
                {"source_row": source_row, "field": field}
                for source_row, field in orphaned_manual_review
            ],
        )

    report["ok"] = not report["errors"]
    report["status"] = "valid" if report["ok"] else "invalid"
    return report


def _validate_mapping_file(
    template_path: Path, mapping_path: Path, project_root: Path | None = None
) -> dict[str, Any]:
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report = _new_mapping_report(mapping_path, template_path)
        _add_error(report, "mapping_unreadable", "Mapping JSON 无法读取或解析。", error=str(exc))
        return report

    report = validate_mapping(mapping, template_path, project_root)
    report["mapping"] = str(mapping_path)
    return report


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_part(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def _freeze_element(element: ET.Element | None) -> Any:
    if element is None:
        return None
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        element.text or "",
        tuple(_freeze_element(child) for child in list(element)),
    )


def _inventory_sheet_structure(
    root: ET.Element, data_row: int
) -> tuple[Any, tuple[Any, ...]]:
    """Freeze all inventory-sheet structure except writable cell payloads."""
    def normalized_row_structure(source: ET.Element) -> Any:
        row = copy.deepcopy(source)
        row.attrib["r"] = "0"
        for cell in row.findall("a:c", NS):
            reference = cell.attrib.get("r", "")
            match = re.fullmatch(r"([A-Z]+)[0-9]+", reference)
            if match:
                cell.attrib["r"] = f"{match.group(1)}0"
            for child in list(cell):
                if child.tag in {f"{{{NS_MAIN}}}v", f"{{{NS_MAIN}}}is"}:
                    cell.remove(child)
            if cell.find("a:f", NS) is None:
                cell.attrib.pop("t", None)
        return _freeze_element(row)

    sheet = copy.deepcopy(root)
    dimension = sheet.find("a:dimension", NS)
    if dimension is not None:
        sheet.remove(dimension)
    sheet_data = sheet.find("a:sheetData", NS)
    normalized_data_rows: list[Any] = []
    fallback_prototype: ET.Element | None = None
    if sheet_data is not None:
        for row in list(sheet_data.findall("a:row", NS)):
            row_number = int(row.attrib.get("r", "0"))
            if row_number == data_row - 1:
                fallback_prototype = row
            if row_number < data_row:
                continue
            sheet_data.remove(row)
            normalized_data_rows.append(normalized_row_structure(row))
    if not normalized_data_rows and fallback_prototype is not None:
        normalized_data_rows.append(normalized_row_structure(fallback_prototype))
    return _freeze_element(sheet), tuple(normalized_data_rows)


def _workbook_snapshot(path: Path, side: str, report: dict[str, Any]) -> dict[str, Any] | None:
    try:
        with ZipFile(path) as zf:
            names = zf.namelist()
            duplicate_names = sorted(name for name, count in _counts(names).items() if count > 1)
            if duplicate_names:
                _add_error(report, "duplicate_zip_members", "工作簿 ZIP 包含重复部件。", side=side, parts=duplicate_names)

            corrupt_member = zf.testzip()
            if corrupt_member:
                _add_error(report, "zip_member_corrupt", "工作簿 ZIP 部件 CRC 校验失败。", side=side, part=corrupt_member)

            entries = {name: zf.read(name) for name in names}
    except (OSError, BadZipFile, RuntimeError) as exc:
        _add_error(report, "zip_unreadable", "工作簿不是可读的 Office Open XML ZIP 文件。", side=side, error=str(exc))
        return None

    xml_parts = [
        name
        for name in entries
        if name == "[Content_Types].xml" or name.endswith(".xml") or name.endswith(".rels")
    ]
    parsed: dict[str, ET.Element] = {}
    for name in xml_parts:
        try:
            parsed[name] = ET.fromstring(entries[name])
        except ET.ParseError as exc:
            _add_error(report, "xml_unreadable", "工作簿 XML 部件无法解析。", side=side, part=name, error=str(exc))

    required_parts = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    missing_parts = sorted(required_parts - set(entries))
    if missing_parts:
        _add_error(report, "core_parts_missing", "工作簿缺少核心 OOXML 部件。", side=side, parts=missing_parts)
        return None
    if any(part not in parsed for part in required_parts):
        return None

    workbook = parsed["xl/workbook.xml"]
    workbook_rels = parsed["xl/_rels/workbook.xml.rels"]
    relmap = {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in workbook_rels.findall("rel:Relationship", NS)
    }

    sheets: list[tuple[str, str, str]] = []
    validations: dict[str, Any] = {}
    conditional_formats: dict[str, Any] = {}
    sheets_root = workbook.find("a:sheets", NS)
    if sheets_root is None:
        _add_error(report, "sheets_missing", "工作簿没有 sheets 定义。", side=side)
    else:
        for sheet in sheets_root.findall("a:sheet", NS):
            name = sheet.attrib.get("name", "")
            state = sheet.attrib.get("state", "visible")
            rid = sheet.attrib.get(f"{{{NS_REL}}}id", "")
            target = relmap.get(rid, "")
            part = _resolve_part("xl/workbook.xml", target) if target else ""
            sheets.append((name, state, part))
            root = parsed.get(part)
            if root is None:
                _add_error(report, "worksheet_part_unreadable", "工作表对应 XML 部件缺失或不可读。", side=side, sheet=name, part=part)
                continue
            validations[name] = tuple(
                _freeze_element(element) for element in root.findall("a:dataValidations", NS)
            )
            conditional_formats[name] = tuple(
                _freeze_element(element) for element in root.findall("a:conditionalFormatting", NS)
            )

    defined_names = _freeze_element(workbook.find("a:definedNames", NS))
    inventory_sheet_parts = [
        part for name, _state, part in sheets if _normalized(name) in {"template", "模板"}
    ]
    if len(inventory_sheet_parts) != 1:
        _add_error(
            report,
            "inventory_sheet_identity_invalid",
            "工作簿必须且只能包含一个 Template/模板 数据工作表。",
            side=side,
            parts=inventory_sheet_parts,
        )
    inventory_non_data_structure = None
    inventory_data_row_structures: tuple[Any, ...] = ()
    inventory_data_row = None
    if len(inventory_sheet_parts) == 1 and inventory_sheet_parts[0] in parsed:
        try:
            reader = WorkbookReader.open(path)
            try:
                inventory_data_row = int(parse_template(reader)["settings"]["dataRow"])
            finally:
                reader.close()
            (
                inventory_non_data_structure,
                inventory_data_row_structures,
            ) = _inventory_sheet_structure(
                parsed[inventory_sheet_parts[0]], inventory_data_row
            )
        except Exception as exc:
            _add_error(
                report,
                "inventory_structure_snapshot_failed",
                "无法建立 Template/模板 工作表的非数据区结构快照。",
                side=side,
                error=f"{type(exc).__name__}: {exc}",
            )
    relationship_hashes = {
        name: _sha256(data) for name, data in entries.items() if name.endswith(".rels")
    }
    vba_hashes = {
        name: _sha256(data) for name, data in entries.items() if "vba" in name.casefold()
    }
    content_types_hash = _sha256(entries.get("[Content_Types].xml", b""))

    return {
        "sheets": sheets,
        "defined_names": defined_names,
        "validations": validations,
        "conditional_formats": conditional_formats,
        "inventory_sheet_part": inventory_sheet_parts[0] if len(inventory_sheet_parts) == 1 else None,
        "inventory_data_row": inventory_data_row,
        "inventory_non_data_structure": inventory_non_data_structure,
        "inventory_data_row_structures": inventory_data_row_structures,
        "part_hashes": {name: _sha256(data) for name, data in entries.items()},
        "relationship_hashes": relationship_hashes,
        "vba_hashes": vba_hashes,
        "content_types_hash": content_types_hash,
        "xml_part_count": len(xml_parts),
        "zip_part_count": len(entries),
    }


def _counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return counts


def _compare_hash_maps(
    report: dict[str, Any],
    code_prefix: str,
    label: str,
    expected: dict[str, str],
    actual: dict[str, str],
) -> bool:
    ok = True
    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    changed = sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name])
    if missing:
        ok = False
        _add_error(report, f"{code_prefix}_missing", f"输出工作簿缺少{label}。", parts=missing)
    if added:
        ok = False
        _add_error(report, f"{code_prefix}_added", f"输出工作簿新增了未授权的{label}。", parts=added)
    if changed:
        ok = False
        _add_error(report, f"{code_prefix}_changed", f"输出工作簿的{label}哈希发生变化。", parts=changed)
    return ok


def validate_output(template_path: Path, output_path: Path) -> dict[str, Any]:
    """Validate protected OOXML structure in ``output_path``.

    This is the stable post-write integration entry point.  Product data cells
    and the worksheet dimension may differ; protected workbook structure may
    not.
    """
    template_path = Path(template_path)
    output_path = Path(output_path)
    report: dict[str, Any] = {
        "checked": True,
        "template": str(template_path),
        "output": str(output_path),
        "ok": False,
        "status": "invalid",
        "errors": [],
        "warnings": [],
        "checks": {},
    }
    before_error_count = len(report["errors"])
    try:
        template = _workbook_snapshot(template_path, "template", report)
        output = _workbook_snapshot(output_path, "output", report)
    except Exception as exc:
        _add_error(
            report,
            "workbook_snapshot_failed",
            "工作簿结构快照失败。",
            error=f"{type(exc).__name__}: {exc}",
        )
        return report
    report["checks"]["zip_and_xml_readable"] = (
        template is not None and output is not None and len(report["errors"]) == before_error_count
    )
    if template is None or output is None:
        return report

    sheets_ok = template["sheets"] == output["sheets"]
    report["checks"]["sheets_and_hidden_states"] = sheets_ok
    if not sheets_ok:
        _add_error(
            report,
            "sheet_structure_changed",
            "输出工作簿的工作表名称、顺序、隐藏状态或关系目标发生变化。",
            expected=template["sheets"],
            actual=output["sheets"],
        )

    names_ok = template["defined_names"] == output["defined_names"]
    report["checks"]["defined_names"] = names_ok
    if not names_ok:
        _add_error(report, "defined_names_changed", "输出工作簿的命名区域发生变化。")

    validations_ok = template["validations"] == output["validations"]
    report["checks"]["data_validations"] = validations_ok
    if not validations_ok:
        changed_sheets = sorted(
            name
            for name in set(template["validations"]) | set(output["validations"])
            if template["validations"].get(name) != output["validations"].get(name)
        )
        _add_error(report, "data_validations_changed", "输出工作簿的数据验证规则发生变化。", sheets=changed_sheets)

    formatting_ok = template["conditional_formats"] == output["conditional_formats"]
    report["checks"]["conditional_formatting"] = formatting_ok
    if not formatting_ok:
        changed_sheets = sorted(
            name
            for name in set(template["conditional_formats"]) | set(output["conditional_formats"])
            if template["conditional_formats"].get(name) != output["conditional_formats"].get(name)
        )
        _add_error(report, "conditional_formatting_changed", "输出工作簿的条件格式发生变化。", sheets=changed_sheets)

    inventory_non_data_ok = (
        template["inventory_data_row"] == output["inventory_data_row"]
        and template["inventory_non_data_structure"]
        == output["inventory_non_data_structure"]
    )
    report["checks"]["inventory_non_data_structure"] = inventory_non_data_ok
    if not inventory_non_data_ok:
        _add_error(
            report,
            "inventory_non_data_structure_changed",
            "Template/模板 工作表的列宽、表头、格式、合并区域或其他非数据区结构发生变化。",
        )

    template_prototypes = set(template["inventory_data_row_structures"])
    output_data_structures = output["inventory_data_row_structures"]
    inventory_rows_ok = bool(output_data_structures) and bool(template_prototypes) and all(
        structure in template_prototypes for structure in output_data_structures
    )
    report["checks"]["inventory_data_row_structure"] = inventory_rows_ok
    if not inventory_rows_ok:
        _add_error(
            report,
            "inventory_data_row_structure_changed",
            "输出数据行未完整继承空白模板原型行结构。",
        )

    protected_template_parts = {
        name: digest
        for name, digest in template["part_hashes"].items()
        if name != template["inventory_sheet_part"]
    }
    protected_output_parts = {
        name: digest
        for name, digest in output["part_hashes"].items()
        if name != output["inventory_sheet_part"]
    }
    protected_parts_ok = _compare_hash_maps(
        report,
        "protected_parts",
        "受保护 ZIP 部件",
        protected_template_parts,
        protected_output_parts,
    )
    report["checks"]["protected_part_hashes"] = protected_parts_ok

    rels_ok = _compare_hash_maps(
        report,
        "relationship_parts",
        "关系部件",
        template["relationship_hashes"],
        output["relationship_hashes"],
    )
    report["checks"]["relationship_part_hashes"] = rels_ok

    vba_ok = _compare_hash_maps(
        report,
        "vba_parts",
        "VBA 部件",
        template["vba_hashes"],
        output["vba_hashes"],
    )
    if template["vba_hashes"] or output["vba_hashes"]:
        if template["content_types_hash"] != output["content_types_hash"]:
            vba_ok = False
            _add_error(report, "macro_content_types_changed", "含 VBA 的工作簿 Content Types 部件发生变化。")
    report["checks"]["vba_part_hashes"] = vba_ok

    report["metrics"] = {
        "template_zip_parts": template["zip_part_count"],
        "output_zip_parts": output["zip_part_count"],
        "template_xml_parts": template["xml_part_count"],
        "output_xml_parts": output["xml_part_count"],
        "relationship_parts": len(template["relationship_hashes"]),
        "vba_parts": len(template["vba_hashes"]),
    }
    report["ok"] = not report["errors"]
    report["status"] = "valid" if report["ok"] else "invalid"
    return report


def build_report(
    template_path: Path,
    mapping_path: Path,
    output_path: Path | None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    mapping_report = _validate_mapping_file(template_path, mapping_path, project_root)
    workbook_report: dict[str, Any]
    if output_path is None:
        workbook_report = {
            "checked": False,
            "ok": None,
            "status": "not_checked",
            "errors": [],
            "warnings": [],
            "reason": "未提供 --output，仅执行 Mapping 预写校验。",
        }
    else:
        workbook_report = validate_output(template_path, output_path)

    error_count = len(mapping_report["errors"]) + len(workbook_report["errors"])
    warning_count = len(mapping_report["warnings"]) + len(workbook_report["warnings"])
    task = mapping_report.get("task") if isinstance(mapping_report.get("task"), dict) else {}
    result_status = task.get("result_status")
    upload_eligibility = (
        "ELIGIBLE_FOR_UPLOAD_ATTEMPT"
        if error_count == 0 and result_status == "LOCAL_VALIDATION_PASSED"
        else "NOT_FOR_UPLOAD"
    )
    return {
        "schema_version": 1,
        "ok": error_count == 0,
        "status": "valid" if error_count == 0 else "invalid",
        "result_status": result_status,
        "upload_eligibility": upload_eligibility,
        "summary": {
            "errors": error_count,
            "warnings": warning_count,
            "mapping_ok": mapping_report.get("ok", False),
            "workbook_checked": workbook_report.get("checked", False),
            "workbook_ok": workbook_report.get("ok"),
        },
        "mapping_validation": mapping_report,
        "workbook_validation": workbook_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True, help="Original blank Amazon .xlsx/.xlsm template")
    parser.add_argument("--mapping", type=Path, required=True, help="Mapping JSON to validate before writing")
    parser.add_argument("--output", type=Path, help="Optional written workbook to compare with the blank template")
    parser.add_argument("--project-root", type=Path, help="Project root containing the indexed template libraries")
    parser.add_argument("--report", type=Path, help="Optional path for the JSON validation report")
    args = parser.parse_args()

    try:
        report = build_report(args.template, args.mapping, args.output, args.project_root)
        exit_code = 0 if report["ok"] else 1
    except Exception as exc:  # Last-resort JSON failure contract for CLI callers.
        report = {
            "schema_version": 1,
            "ok": False,
            "status": "invalid",
            "summary": {"errors": 1, "warnings": 0},
            "errors": [
                _issue(
                    "validator_exception",
                    "校验器遇到未处理异常。",
                    error=f"{type(exc).__name__}: {exc}",
                )
            ],
        }
        exit_code = 2

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
