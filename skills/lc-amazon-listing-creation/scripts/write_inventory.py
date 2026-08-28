#!/usr/bin/env python3
"""Safely write validated field mappings into an Amazon inventory workbook."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from manage_task_state import (
    finalize_task_output,
    LibraryError,
    set_task_skus_status,
    verify_mapping_reservations,
)
from validate_inventory import validate_mapping, validate_output

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": NS_MAIN, "r": NS_REL, "rel": NS_PKG_REL}
ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_REL)

TEMPLATE_LIBRARY_NAMES = {"空白模板库", "样板模板库"}


def col_to_num(col: str) -> int:
    value = 0
    for char in col.upper():
        value = value * 26 + ord(char) - 64
    return value


def num_to_col(number: int) -> str:
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def split_addr(addr: str | None) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", addr or "")
    if not match:
        return None, None
    return col_to_num(match.group(1)), int(match.group(2))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def norm_label(value: str) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip().casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_shared_strings(zf: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iter(f"{{{NS_MAIN}}}t"))
        for item in root.findall("a:si", NS)
    ]


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    if cell_type == "s" and value is not None and value.text is not None:
        return shared_strings[int(value.text)]
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{{{NS_MAIN}}}t"))
    return value.text if value is not None and value.text is not None else ""


def find_template_sheet(zf: ZipFile) -> tuple[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relation_map = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
    sheets = workbook.find("a:sheets", NS)
    for sheet in list(sheets) if sheets is not None else []:
        name = sheet.attrib["name"]
        if norm_label(name) not in {"template", "模板"}:
            continue
        target = relation_map[sheet.attrib[f"{{{NS_REL}}}id"]]
        path = "xl/" + target if not target.startswith("/") else target[1:]
        return name, path
    raise ValueError("Could not find required Template/模板 worksheet")


def worksheet_cells(root: ET.Element, shared_strings: list[str]) -> dict[tuple[int, int], str]:
    cells: dict[tuple[int, int], str] = {}
    for row in root.findall("a:sheetData/a:row", NS):
        row_number = int(row.attrib["r"])
        for cell in row.findall("a:c", NS):
            column, _ = split_addr(cell.attrib.get("r"))
            if column is not None:
                cells[(row_number, column)] = cell_value(cell, shared_strings)
    return cells


def template_settings(cells: dict[tuple[int, int], str]) -> dict[str, int]:
    settings_text = " ".join(value for (row, _), value in cells.items() if row == 1)
    settings = {"labelRow": 4, "attributeRow": 5, "dataRow": 7}
    for key in settings:
        match = re.search(rf"{key}=([0-9]+)", settings_text)
        if match:
            settings[key] = int(match.group(1))
    return settings


def field_columns(cells: dict[tuple[int, int], str], attribute_row: int) -> dict[str, int]:
    return {
        value.strip(): column
        for (row, column), value in cells.items()
        if row == attribute_row and value.strip()
    }


def get_sheet_data(root: ET.Element) -> ET.Element:
    sheet_data = root.find("a:sheetData", NS)
    if sheet_data is None:
        raise ValueError("Template worksheet has no sheetData")
    return sheet_data


def rows_by_number(sheet_data: ET.Element) -> dict[int, ET.Element]:
    return {int(row.attrib["r"]): row for row in sheet_data.findall("a:row", NS)}


def _renumber_row(row: ET.Element, row_number: int) -> None:
    row.attrib["r"] = str(row_number)
    for cell in row.findall("a:c", NS):
        column, _ = split_addr(cell.attrib.get("r"))
        if column is not None:
            cell.attrib["r"] = f"{num_to_col(column)}{row_number}"


def _clear_cell_payload(cell: ET.Element) -> None:
    for child in list(cell):
        if child.tag in {f"{{{NS_MAIN}}}v", f"{{{NS_MAIN}}}is"}:
            cell.remove(child)
    if cell.find("a:f", NS) is None:
        cell.attrib.pop("t", None)


def clone_prototype_row(prototype: ET.Element, row_number: int) -> ET.Element:
    row = copy.deepcopy(prototype)
    _renumber_row(row, row_number)
    for cell in row.findall("a:c", NS):
        _clear_cell_payload(cell)
    return row


def _cell_for_column(row: ET.Element, row_number: int, column: int, prototype: ET.Element) -> ET.Element:
    cell_ref = f"{num_to_col(column)}{row_number}"
    for cell in row.findall("a:c", NS):
        if cell.attrib.get("r") == cell_ref:
            return cell

    prototype_cell: ET.Element | None = None
    for candidate in prototype.findall("a:c", NS):
        candidate_column, _ = split_addr(candidate.attrib.get("r"))
        if candidate_column == column:
            prototype_cell = candidate
            break
    if prototype_cell is not None:
        cell = copy.deepcopy(prototype_cell)
        cell.attrib["r"] = cell_ref
        _clear_cell_payload(cell)
    else:
        cell = ET.Element(f"{{{NS_MAIN}}}c", {"r": cell_ref})

    inserted = False
    for index, existing in enumerate(row.findall("a:c", NS)):
        existing_column, _ = split_addr(existing.attrib.get("r"))
        if existing_column is not None and existing_column > column:
            row.insert(index, cell)
            inserted = True
            break
    if not inserted:
        row.append(cell)
    return cell


def set_text_cell(row: ET.Element, row_number: int, column: int, value: str, prototype: ET.Element) -> None:
    cell = _cell_for_column(row, row_number, column, prototype)
    _clear_cell_payload(cell)
    if value == "":
        return
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, f"{{{NS_MAIN}}}is")
    text = ET.SubElement(inline, f"{{{NS_MAIN}}}t")
    if value.startswith(" ") or value.endswith(" ") or "\n" in value:
        text.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
    text.text = value


def insert_or_replace_row(sheet_data: ET.Element, row: ET.Element, row_number: int) -> None:
    for index, existing in enumerate(list(sheet_data)):
        existing_number = int(existing.attrib.get("r", "0"))
        if existing_number == row_number:
            sheet_data.remove(existing)
            sheet_data.insert(index, row)
            return
        if existing_number > row_number:
            sheet_data.insert(index, row)
            return
    sheet_data.append(row)


def update_dimension(root: ET.Element, minimum_max_row: int, max_column: int) -> None:
    dimension = root.find("a:dimension", NS)
    if dimension is None:
        dimension = ET.Element(f"{{{NS_MAIN}}}dimension")
        root.insert(0, dimension)
    current = dimension.attrib.get("ref", "A1")
    last_ref = current.split(":")[-1]
    current_column, current_row = split_addr(last_ref)
    max_row = max(minimum_max_row, current_row or 1)
    max_col = max(max_column, current_column or 1)
    dimension.attrib["ref"] = f"A1:{num_to_col(max_col)}{max_row}"


def in_template_library(path: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    return any(parent.name in TEMPLATE_LIBRARY_NAMES for parent in (resolved, *resolved.parents))


def validate_paths(template: Path, output: Path) -> None:
    template_resolved = template.expanduser().resolve(strict=True)
    output_resolved = output.expanduser().resolve(strict=False)
    if template_resolved == output_resolved:
        raise ValueError("Input template and output path must be different")
    if in_template_library(output_resolved):
        raise ValueError("Output must not be written inside 空白模板库 or 样板模板库")
    if output_resolved.exists():
        raise ValueError("Output already exists; choose a new path instead of overwriting it")
    if template.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise ValueError("Template must be .xlsx or .xlsm")
    if output.suffix.casefold() != template.suffix.casefold():
        raise ValueError("Output extension must match the template extension")


def _zip_entries(template: Path) -> tuple[list[tuple[ZipInfo, bytes]], list[str], str]:
    with ZipFile(template, "r") as archive:
        if archive.testzip() is not None:
            raise ValueError("Template ZIP container is corrupt")
        shared_strings = load_shared_strings(archive)
        _, sheet_path = find_template_sheet(archive)
        entries = [(copy.copy(info), archive.read(info.filename)) for info in archive.infolist()]
    return entries, shared_strings, sheet_path


def _mapping_value(record: Any) -> str:
    if not isinstance(record, dict) or "value" not in record:
        raise ValueError("Every mapped field must be an object containing value and provenance metadata")
    return clean_text(record["value"])


def build_workbook_bytes(
    template: Path, mapping: dict[str, Any]
) -> tuple[list[tuple[ZipInfo, bytes]], str, bytes]:
    entries, shared_strings, sheet_path = _zip_entries(template)
    entry_map = {info.filename: data for info, data in entries}
    root = ET.fromstring(entry_map[sheet_path])
    cells = worksheet_cells(root, shared_strings)
    settings = template_settings(cells)
    attribute_row = settings["attributeRow"]
    data_row = settings["dataRow"]
    populated_data_cells = [
        (row, column) for (row, column), value in cells.items()
        if row >= data_row and clean_text(value).strip()
    ]
    if populated_data_cells:
        raise ValueError("Source must be a blank template; populated product data rows were found")
    fields = field_columns(cells, attribute_row)
    sheet_data = get_sheet_data(root)
    existing_rows = rows_by_number(sheet_data)
    prototype = existing_rows.get(data_row) or existing_rows.get(data_row - 1)
    if prototype is None:
        raise ValueError("Template has no prototype row at dataRow or dataRow - 1")

    write_rows = mapping["rows"]
    for offset, item in enumerate(write_rows):
        row_number = data_row + offset
        row = clone_prototype_row(prototype, row_number)
        for field, record in item["fields"].items():
            set_text_cell(row, row_number, fields[field], _mapping_value(record), prototype)
        insert_or_replace_row(sheet_data, row, row_number)

    update_dimension(root, data_row + len(write_rows) - 1, max(fields.values(), default=1))
    modified = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return entries, sheet_path, modified


def _write_zip(path: Path, entries: list[tuple[ZipInfo, bytes]], sheet_path: str, modified: bytes) -> None:
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            if info.filename == sheet_path:
                data = modified
            compression = info.compress_type if info.compress_type is not None else ZIP_DEFLATED
            archive.writestr(info, data, compress_type=compression)


def write_workbook(
    template: Path, mapping_path: Path, output: Path, project_root: Path | None = None
) -> dict[str, Any]:
    validate_paths(template, output)
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    preflight = validate_mapping(mapping, template, project_root)
    if not preflight["ok"]:
        raise ValueError("Mapping validation failed: " + json.dumps(preflight["errors"], ensure_ascii=False))

    requested_status = mapping.get("task", {}).get("result_status")
    if requested_status == "DRAFT_NOT_FOR_UPLOAD" and "draft_not_for_upload" not in output.stem.casefold():
        raise ValueError(
            "DRAFT_NOT_FOR_UPLOAD output filename must contain DRAFT_NOT_FOR_UPLOAD"
        )
    task_id = str(mapping.get("task", {}).get("task_id") or "").strip()
    state_report: dict[str, Any] | None = None
    if project_root is not None:
        if not task_id:
            raise ValueError("task.task_id is required when --project-root is used")
        state_report = verify_mapping_reservations(project_root, task_id, mapping)
        if not state_report["ok"]:
            raise ValueError(
                "Mapping SKUs do not match task reservations: "
                + json.dumps(state_report["errors"], ensure_ascii=False)
            )
        if requested_status == "LOCAL_VALIDATION_PASSED":
            state_report["validated"] = set_task_skus_status(project_root, task_id, "validated")

    output.parent.mkdir(parents=True, exist_ok=True)
    template_hash_before = sha256_file(template)
    entries, sheet_path, modified = build_workbook_bytes(template, mapping)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=output.suffix, dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _write_zip(temporary, entries, sheet_path, modified)
        output_validation = validate_output(template, temporary)
        if not output_validation["ok"]:
            raise ValueError(
                "Output validation failed: "
                + json.dumps(output_validation["errors"], ensure_ascii=False)
            )
        if sha256_file(template) != template_hash_before:
            raise RuntimeError("Input template changed during the write operation")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    result_status = "DRAFT_NOT_FOR_UPLOAD" if requested_status == "DRAFT_NOT_FOR_UPLOAD" else "LOCAL_VALIDATION_PASSED"
    if project_root is not None:
        mapping_hash = sha256_file(mapping_path)
        output_hash = sha256_file(output)
        state_report = state_report or {}
        try:
            state_report["finalized"] = finalize_task_output(
                project_root,
                task_id,
                result_status,
                mapping_hash,
                output,
                output_hash,
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise
    return {
        "ok": True,
        "status": result_status,
        "upload_eligibility": (
            "NOT_FOR_UPLOAD" if result_status == "DRAFT_NOT_FOR_UPLOAD" else "LOCALLY_VALIDATED"
        ),
        "output": str(output),
        "output_sha256": sha256_file(output),
        "template_sha256": template_hash_before,
        "mapping_validation": preflight,
        "output_validation": output_validation,
        "task_state": state_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True, help="Source blank Amazon inventory template")
    parser.add_argument("--mapping", type=Path, required=True, help="Validated Mapping v2 JSON")
    parser.add_argument("--out", type=Path, required=True, help="Output .xlsx/.xlsm path outside template libraries")
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Project state root; required for product snapshot and SKU reservation verification",
    )
    parser.add_argument("--report", type=Path, help="Optional JSON validation report")
    args = parser.parse_args()
    try:
        report = write_workbook(args.template, args.mapping, args.out, args.project_root)
    except (OSError, ValueError, KeyError, LibraryError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
