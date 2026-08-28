from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import extract_inventory_context as context_mod
import manage_task_state as task_state
import manage_template_library as library
import validate_inventory as validator
import write_inventory as writer

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": NS_MAIN}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_record(value: str, decision_set: str, row_number: int, *, sensitive: bool = False) -> dict:
    return {
        "value": value,
        "decision_set": decision_set,
        "source": {"type": "current_product_fixture", "reference": f"fixture-row-{row_number}"},
        "confidence": 1.0,
        "confirmation_status": "confirmed" if sensitive else "not_required",
        "validation": {"status": "passed", "messages": []},
    }


def build_real_mapping(blank: Path, sample: Path, product_path: Path) -> tuple[dict, dict]:
    context = context_mod.build_context(
        None,
        blank,
        sample,
        marketplace="ATVPDKIKX0DER",
        content_language="en_US",
        product_type="SCULPTURE",
        node="outdoor-statues",
        gtin_status="confirmed_exempt",
        reference_verification="user_confirmed",
    )
    blank_allowed: dict[str, set[str]] = {}
    for source in (context["valid_values_by_field"], context["dropdown_values_by_field"]):
        for field, values in source.items():
            blank_allowed.setdefault(field, set()).update(values)

    confirmations: list[dict] = []
    legacy_rule_default = {
        role: [
            field for field in fields
            if validator._field_base(field) == "condition_type"
        ]
        for role, fields in context["field_decision"]["rule_default"].items()
    }
    legacy_sample_preferred = copy.deepcopy(context["field_decision"]["sample_preferred"])
    for profile in context["reference_profile"]["profiles"]:
        role = profile["role"]
        bucket = legacy_sample_preferred.setdefault(role, [])
        for item in profile["filled_fields"]:
            field = item["field"]
            if (
                field not in context["field_decision"]["must_fill"].get(role, [])
                and field not in legacy_rule_default.get(role, [])
                and field not in bucket
            ):
                bucket.append(field)
    workbook = context_mod.WorkbookReader.open(sample)
    try:
        template = context_mod.parse_template(workbook)
        cells = workbook.sheet_cells(template["sheet_name"])
        fields_by_col = {
            item["column_index"]: item["field"]
            for item in template["columns"]
            if item["field"]
        }
        rows = []
        condition_field = next(
            field for field in context["template"]["fields"]
            if field.startswith("condition_type[")
        )
        for row_number in range(7, 11):
            raw_values = {
                field: context_mod.clean_text(cells.get((row_number, column), ""))
                for column, field in fields_by_col.items()
                if context_mod.clean_text(cells.get((row_number, column), ""))
            }
            role = "Parent" if row_number == 7 else "Child"
            must_fill = context["field_decision"]["must_fill"][role]
            records = {}
            for field, raw_value in raw_values.items():
                value = raw_value
                candidates = blank_allowed.get(field, set())
                if candidates and value not in candidates:
                    value = sorted(candidates)[0]
                sensitive = validator._is_sensitive_field(field)
                record = make_record(
                    value,
                    "must_fill" if field in must_fill else "sample_preferred",
                    row_number,
                    sensitive=sensitive,
                )
                confirmation_id = f"fixture-{row_number}-{len(confirmations) + 1}"
                record["source"] = {
                    "type": "user_confirmation",
                    "reference": f"confirmation:{confirmation_id}",
                }
                record["confirmation_status"] = "confirmed"
                confirmations.append(
                    {
                        "id": confirmation_id,
                        "field": field,
                        "value": value,
                        "confirmed": True,
                    }
                )
                records[field] = record
            records[condition_field] = {
                "value": "New",
                "decision_set": "rule_default",
                "source": {
                    "type": "business_rule",
                    "reference": "rule:item-condition-new",
                },
                "confidence": 1.0,
                "confirmation_status": "not_required",
                "validation": {"status": "passed", "messages": []},
            }
            rows.append({
                "source_row": row_number,
                "source_key": f"product-row-{row_number}",
                "role": role,
                "must_fill": must_fill,
                "fields": records,
            })
    finally:
        workbook.close()

    query = library.query_project(
        blank.parent.parent,
        "ATVPDKIKX0DER",
        "en_US",
        "SCULPTURE",
        "outdoor-statues",
        "all",
    )
    selected_blank = query["preferred_blank_template"]
    selected_sample = query["usable_sample_templates"][0]
    mapping = {
        "schema_version": "2.1",
        "task": {
            "task_id": "real-sculpture-001",
            "marketplace": "ATVPDKIKX0DER",
            "content_language": "en_US",
            "product_type": "SCULPTURE",
            "browse_node": "outdoor-statues",
            "fill_mode": "SAMPLE_GUIDED",
            "gtin_status": "confirmed_exempt",
            "result_status": "LOCAL_VALIDATION_PASSED",
        },
        "templates": {
            "blank_entry_id": selected_blank["entry_id"],
            "blank_sha256": context["template_metadata"]["file_sha256"],
            "blank_schema_fingerprint": context["template_metadata"]["schema_fingerprint"],
            "sample_entry_id": selected_sample["entry_id"],
            "sample_sha256": context["reference_profile"]["metadata"]["file_sha256"],
            "sample_verification": "user_confirmed",
            "sample_schema_compatibility": selected_sample["schema_compatibility"],
        },
        "inputs": {
            "product": {
                "path": str(product_path.resolve()),
                "sha256": sha256(product_path),
            }
        },
        "confirmations": confirmations,
        "field_plan": {
            "must_fill": context["field_decision"]["must_fill"],
            "rule_default": legacy_rule_default,
            "sample_preferred": legacy_sample_preferred,
            "evidence_fillable": [],
        },
        "rows": rows,
        "manual_review": [],
        "blocking_errors": [],
        "warnings": [],
    }
    return mapping, context


def build_v22_mapping(mapping_v21: dict, context: dict) -> dict:
    mapping = copy.deepcopy(mapping_v21)
    mapping["schema_version"] = "2.2"
    mapping["field_plan"]["rule_default"] = copy.deepcopy(
        context["field_decision"]["rule_default"]
    )
    controlled = {
        role: set(fields)
        for role, fields in mapping["field_plan"]["rule_default"].items()
    }
    for role, fields in mapping["field_plan"]["sample_preferred"].items():
        mapping["field_plan"]["sample_preferred"][role] = [
            field for field in fields if field not in controlled.get(role, set())
        ]

    fields_by_base: dict[str, list[str]] = {}
    for field in context["template"]["fields"]:
        fields_by_base.setdefault(validator._field_base(field), []).append(field)

    def only(base: str) -> str:
        return fields_by_base[base][0]

    sku_field = only("contribution_sku")
    brand_field = only("brand")
    model_number_field = only("model_number")
    model_name_field = only("model_name")
    manufacturer_field = only("manufacturer")
    number_field = only("number_of_items")
    part_field = only("part_number")
    mounting_field = only("mounting_type")
    fulfillment_field = only("fulfillment_availability")

    def business_record(value: str, reference: str) -> dict:
        return {
            "value": value,
            "decision_set": "rule_default",
            "source": {"type": "business_rule", "reference": reference},
            "confidence": 1.0,
            "confirmation_status": "not_required",
            "validation": {"status": "passed", "messages": []},
        }

    def model_rule_record(value: str, source_row: int, rule_id: str) -> dict:
        return {
            "value": value,
            "decision_set": "rule_default",
            "source": {
                "type": "model_rule",
                "reference": f"Products!B{source_row}",
                "rule_id": rule_id,
            },
            "confidence": 0.95,
            "confirmation_status": "not_required",
            "validation": {"status": "passed", "messages": []},
        }

    for row in mapping["rows"]:
        if row["role"] not in {"Child", "Standalone"}:
            continue
        fields = row["fields"]
        sku = fields[sku_field]["value"]
        brand = fields[brand_field]["value"]
        source_row = row["source_row"]
        fields[model_number_field] = business_record(
            sku, "rule:model-number-equals-sku"
        )
        fields[manufacturer_field] = business_record(
            brand, "rule:manufacturer-equals-brand"
        )
        fields[model_name_field] = model_rule_record(
            "Sculpture Core Keyword", source_row, "rule:model-name-core-keyword-fallback"
        )
        fields[part_field] = model_rule_record(
            "Sculpture Core Keyword", source_row, "rule:part-number-core-keyword-fallback"
        )
        fields[number_field] = business_record("1", "rule:number-of-items-default-one")
        fields[mounting_field] = model_rule_record(
            "Floor Mount", source_row, "rule:mounting-type-enum-selection"
        )
        fields[fulfillment_field] = business_record(
            "Fulfillment by Amazon (NA)", "rule:fulfillment-default-fba"
        )
    return mapping


def make_product_xlsx(
    path: Path,
    *,
    family: bool = False,
    measurements: bool = False,
    measurement_values: list[str] | None = None,
) -> None:
    headers = ["父子变体", "标题", "主图链接", "产品详细介绍", "商品编号类型", "商品ID"]
    if measurements:
        headers.extend([
            "商品长度",
            "商品宽度",
            "商品高度",
            "商品尺寸单位",
            "商品重量",
            "商品重量单位",
            "包装长度",
            "包装宽度",
            "包装高度",
            "包装尺寸单位",
            "包装重量",
            "包装重量单位",
        ])
    if family:
        product_rows = [
            (7, ["父体", "Sculpture family", "", "Sculpture parent listing", "", ""]),
            (8, ["子体", "Sculpture child A", "https://example.invalid/a.jpg", "Sculpture child A details", "", ""]),
            (9, ["子体", "Sculpture child B", "https://example.invalid/b.jpg", "Sculpture child B details", "", ""]),
            (10, ["子体", "Sculpture child C", "https://example.invalid/c.jpg", "Sculpture child C details", "", ""]),
        ]
    else:
        resolved_measurement_values = (
            measurement_values
            if measurement_values is not None
            else ["25.4", "12.7", "50.8", "cm", "1000", "g", "", "", "", "", "", ""]
            if measurements
            else []
        )
        product_rows = [(
            2,
            [
                "独立商品",
                "Evidence-backed sculpture title",
                "https://example.invalid/main.jpg",
                "Resin sculpture with user-supplied dimensions and material details.",
                "UPC",
                "036000291452",
                *resolved_measurement_values,
            ],
        )]
    sheet = ET.Element(f"{{{NS_MAIN}}}worksheet")
    data = ET.SubElement(sheet, f"{{{NS_MAIN}}}sheetData")
    for row_number, row_values in [(1, headers), *product_rows]:
        row = ET.SubElement(data, f"{{{NS_MAIN}}}row", {"r": str(row_number)})
        for column, value in enumerate(row_values, start=1):
            ref = f"{context_mod.num_to_col(column)}{row_number}"
            cell = ET.SubElement(row, f"{{{NS_MAIN}}}c", {"r": ref, "t": "inlineStr"})
            inline = ET.SubElement(cell, f"{{{NS_MAIN}}}is")
            ET.SubElement(inline, f"{{{NS_MAIN}}}t").text = value

    workbook = ET.Element(f"{{{NS_MAIN}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{NS_MAIN}}}sheets")
    ET.SubElement(
        sheets,
        f"{{{NS_MAIN}}}sheet",
        {"name": "Products", "sheetId": "1", f"{{{NS_REL}}}id": "rId1"},
    )
    workbook_rels = ET.Element(f"{{{NS_PKG_REL}}}Relationships")
    ET.SubElement(
        workbook_rels,
        f"{{{NS_PKG_REL}}}Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            "Target": "worksheets/sheet1.xml",
        },
    )
    package_rels = ET.Element(f"{{{NS_PKG_REL}}}Relationships")
    ET.SubElement(
        package_rels,
        f"{{{NS_PKG_REL}}}Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "xl/workbook.xml",
        },
    )
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", ET.tostring(package_rels, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/workbook.xml", ET.tostring(workbook, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(workbook_rels, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet, encoding="utf-8", xml_declaration=True))


def rename_template_sheet(source: Path, output: Path) -> None:
    with ZipFile(source) as archive:
        entries = [(copy.copy(info), archive.read(info.filename)) for info in archive.infolist()]
    with ZipFile(output, "w") as archive:
        for info, data in entries:
            if info.filename == "xl/workbook.xml":
                root = ET.fromstring(data)
                for sheet in root.findall("a:sheets/a:sheet", NS):
                    if sheet.attrib.get("name") == "Template":
                        sheet.attrib["name"] = "Not Inventory"
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            archive.writestr(info, data, compress_type=info.compress_type)


def add_zip_part(source: Path, output: Path, name: str, payload: bytes) -> None:
    with ZipFile(source) as archive:
        entries = [(copy.copy(info), archive.read(info.filename)) for info in archive.infolist()]
    with ZipFile(output, "w") as archive:
        for info, data in entries:
            archive.writestr(info, data, compress_type=info.compress_type)
        archive.writestr(name, payload, compress_type=ZIP_DEFLATED)


def replace_sheet_cell_text(source: Path, output: Path, address: str, value: str) -> None:
    with ZipFile(source) as archive:
        entries = [(copy.copy(info), archive.read(info.filename)) for info in archive.infolist()]
        try:
            _, sheet_path = writer.find_template_sheet(archive)
        except ValueError:
            sheet_path = "xl/worksheets/sheet1.xml"
    with ZipFile(output, "w") as archive:
        for info, data in entries:
            if info.filename == sheet_path:
                root = ET.fromstring(data)
                cell = root.find(f".//a:c[@r='{address}']", NS)
                if cell is None:
                    raise AssertionError(f"Cell not found: {address}")
                for child in list(cell):
                    cell.remove(child)
                cell.attrib["t"] = "inlineStr"
                inline = ET.SubElement(cell, f"{{{NS_MAIN}}}is")
                ET.SubElement(inline, f"{{{NS_MAIN}}}t").text = value
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            archive.writestr(info, data, compress_type=info.compress_type)


def add_inventory_value(source: Path, output: Path, field: str, value: str) -> None:
    entries, shared_strings, sheet_path = writer._zip_entries(source)
    entry_map = {info.filename: data for info, data in entries}
    root = ET.fromstring(entry_map[sheet_path])
    cells = writer.worksheet_cells(root, shared_strings)
    settings = writer.template_settings(cells)
    fields = writer.field_columns(cells, settings["attributeRow"])
    sheet_data = writer.get_sheet_data(root)
    existing = writer.rows_by_number(sheet_data)
    prototype = existing.get(settings["dataRow"]) or existing.get(settings["dataRow"] - 1)
    if prototype is None:
        raise AssertionError("Missing prototype row")
    row = writer.clone_prototype_row(prototype, settings["dataRow"])
    writer.set_text_cell(row, settings["dataRow"], fields[field], value, prototype)
    writer.insert_or_replace_row(sheet_data, row, settings["dataRow"])
    modified = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    writer._write_zip(output, entries, sheet_path, modified)


def mutate_first_column_width(source: Path, output: Path) -> None:
    with ZipFile(source) as archive:
        entries = [(copy.copy(info), archive.read(info.filename)) for info in archive.infolist()]
        _, sheet_path = writer.find_template_sheet(archive)
    with ZipFile(output, "w") as archive:
        for info, data in entries:
            if info.filename == sheet_path:
                root = ET.fromstring(data)
                column = root.find("a:cols/a:col", NS)
                if column is None:
                    raise AssertionError("Template sheet has no column definition")
                column.attrib["width"] = "999"
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            archive.writestr(info, data, compress_type=info.compress_type)


class RealWorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source_root_raw = os.environ.get("LC_AMAZON_TEST_PROJECT")
        if not source_root_raw:
            raise unittest.SkipTest("Set LC_AMAZON_TEST_PROJECT to run real workbook tests")
        cls.source_root = Path(source_root_raw)
        cls.source_blank = cls.source_root / "空白模板库" / "SCULPTURE.xlsm"
        cls.source_sample = cls.source_root / "样板模板库" / "SCULPTURE.xlsm"
        if not cls.source_sample.is_file():
            cls.source_sample = cls.source_root / "样板模板库" / "SCULPTURE已填写模板.xlsm"
        cls.source_hashes = (sha256(cls.source_blank), sha256(cls.source_sample))
        cls.temp = tempfile.TemporaryDirectory(prefix="lc-amazon-skill-test-")
        cls.project = Path(cls.temp.name)
        (cls.project / "空白模板库").mkdir()
        (cls.project / "样板模板库").mkdir()
        (cls.project / "输出").mkdir()
        cls.blank = cls.project / "空白模板库" / cls.source_blank.name
        cls.sample = cls.project / "样板模板库" / cls.source_sample.name
        shutil.copy2(cls.source_blank, cls.blank)
        shutil.copy2(cls.source_sample, cls.sample)
        cls.product = cls.project / "product-input.xlsx"
        library.scan_project(cls.project)
        library.set_sample_status(cls.project, str(cls.sample), "user_confirmed", note="fixture")
        make_product_xlsx(cls.product, family=True)
        cls.mapping, cls.context = build_real_mapping(cls.blank, cls.sample, cls.product)
        cls.mapping_path = cls.project / "mapping.json"
        cls.mapping_path.write_text(json.dumps(cls.mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_01_reference_profiles_and_node_boundary(self) -> None:
        self.assertEqual(self.context["template_metadata"]["technical_field_count"], 295)
        profiles = {
            item["role"]: (item["row_count"], item["filled_field_count"])
            for item in self.context["reference_profile"]["profiles"]
        }
        self.assertEqual(profiles, {"Parent": (1, 18), "Child": (3, 52)})
        for role in ("Parent", "Child"):
            must = set(self.context["field_decision"]["must_fill"].get(role, []))
            preferred = set(self.context["field_decision"]["sample_preferred"].get(role, []))
            self.assertFalse(must & preferred)
        serialized = json.dumps(self.context, ensure_ascii=False)
        self.assertNotIn("100-DBE-0", serialized)

        other_node = context_mod.build_context(
            None,
            self.blank,
            self.sample,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="statues",
            reference_verification="user_confirmed",
        )
        self.assertFalse(other_node["reference_profile"]["compatibility"]["compatible"])
        self.assertEqual(other_node["field_decision"]["sample_preferred"], {})

        unverified = context_mod.build_context(
            None,
            self.blank,
            self.sample,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="outdoor-statues",
            reference_verification="unverified",
        )
        self.assertFalse(unverified["reference_profile"]["eligible_for_learning"])
        self.assertEqual(unverified["field_decision"]["sample_preferred"], {})

    def test_02_library_query_and_sample_status(self) -> None:
        scan = library.scan_project(self.project)
        self.assertEqual(scan["libraries"]["blank"]["ok"], 1)
        self.assertEqual(scan["libraries"]["sample"]["ok"], 1)
        library.set_sample_status(self.project, str(self.sample), "user_confirmed", note="fixture")
        empty_report = self.project / "empty-processing-report.txt"
        empty_report.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(library.LibraryError, "nonempty file"):
            library.set_sample_status(
                self.project,
                str(self.sample),
                "report_verified",
                report_path=str(empty_report),
            )
        fake_report = self.project / "not-an-amazon-report.md"
        fake_report.write_text("not an Amazon processing report\n", encoding="utf-8")
        with self.assertRaisesRegex(library.LibraryError, "supported evidence format"):
            library.set_sample_status(
                self.project,
                str(self.sample),
                "report_verified",
                report_path=str(fake_report),
            )
        outdoor = library.query_project(
            self.project, "ATVPDKIKX0DER", "en_US", "SCULPTURE", "outdoor-statues", "all"
        )
        statues = library.query_project(
            self.project, "ATVPDKIKX0DER", "en_US", "SCULPTURE", "statues", "all"
        )
        self.assertEqual(outdoor["decision"]["state"], "READY_WITH_SAMPLE")
        self.assertEqual(
            outdoor["usable_sample_templates"][0]["schema_compatibility"], "exact_schema"
        )
        self.assertEqual(outdoor["counts"], {"blank": 1, "sample": 1, "total": 2})
        self.assertEqual(statues["counts"]["sample"], 0)
        self.assertEqual(statues["decision"]["state"], "SAMPLE_MISSING_CONFIRM_MODE")

        duplicate_source = self.project / "downloaded-blank.xlsm"
        shutil.copy2(self.blank, duplicate_source)
        admission = library.register_blank(self.project, duplicate_source)
        self.assertTrue(admission["duplicate"])
        self.assertEqual(admission["entry"]["path"], f"空白模板库/{self.blank.name}")

        with self.assertRaisesRegex(library.LibraryError, "populated product"):
            library.register_blank(self.project, self.sample, "filled-is-not-blank.xlsm")

        title_only = self.project / "filled-title-only.xlsm"
        add_inventory_value(
            self.blank,
            title_only,
            "item_name[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value",
            "This is not a blank template",
        )
        with self.assertRaisesRegex(library.LibraryError, "populated product"):
            library.register_blank(self.project, title_only)

        with sqlite3.connect(self.project / library.DB_RELATIVE_PATH) as connection:
            fields = json.loads(
                connection.execute(
                    "SELECT technical_fields_json FROM templates WHERE library_kind = 'sample'"
                ).fetchone()[0]
            )
            connection.execute(
                "UPDATE templates SET schema_fingerprint = ?, technical_fields_json = ? "
                "WHERE library_kind = 'sample'",
                ("simulated-reordered-schema", json.dumps(list(reversed(fields)))),
            )
        remappable = library.query_project(
            self.project, "ATVPDKIKX0DER", "en_US", "SCULPTURE", "outdoor-statues", "all"
        )
        self.assertEqual(remappable["decision"]["state"], "READY_WITH_SAMPLE")
        self.assertEqual(
            remappable["usable_sample_templates"][0]["schema_compatibility"],
            "remappable_schema",
        )
        library.scan_project(self.project)

    def test_03_mapping_guards(self) -> None:
        empty = validator.validate_mapping({}, self.blank)
        self.assertIn("rows_required", {item["code"] for item in empty["errors"]})

        invalid_enum = copy.deepcopy(self.mapping)
        invalid_enum["rows"][0]["fields"]["product_type#1.value"]["value"] = "NOT_ALLOWED"
        report = validator.validate_mapping(invalid_enum, self.blank)
        self.assertIn("invalid_allowed_value", {item["code"] for item in report["errors"]})

        one_sided = copy.deepcopy(self.mapping)
        one_sided["task"]["gtin_status"] = "provided"
        child = one_sided["rows"][1]
        child["fields"]["amzn1.volt.ca.product_id_type"]["value"] = "UPC"
        report = validator.validate_mapping(one_sided, self.blank)
        self.assertIn("product_id_value_required", {item["code"] for item in report["errors"]})

        low_confidence_identity = copy.deepcopy(self.mapping)
        brand_field = "brand[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value"
        low_confidence_identity["rows"][0]["fields"][brand_field] = {
            **make_record("Unconfirmed Brand", "evidence_fillable", 7),
            "source": {
                "type": "target_template_allowed_value",
                "reference": "blank-template-candidate",
            },
            "confidence": 0.4,
            "confirmation_status": "pending",
        }
        report = validator.validate_mapping(low_confidence_identity, self.blank)
        identity_codes = {item["code"] for item in report["errors"]}
        self.assertIn("sensitive_value_low_confidence", identity_codes)
        self.assertIn("sensitive_value_not_confirmed", identity_codes)
        self.assertIn("sensitive_fact_source_invalid", identity_codes)

        blank_cell_provenance = copy.deepcopy(self.mapping)
        first_field, first_value = next(
            iter(blank_cell_provenance["rows"][0]["fields"].items())
        )
        first_value["source"] = {"type": "product_cell", "reference": "Products!B99"}
        report = validator.validate_mapping(blank_cell_provenance, self.blank)
        self.assertIn(
            "product_source_cell_blank",
            {item["code"] for item in report["errors"]},
        )

        direct_product_provenance = copy.deepcopy(self.mapping)
        title_field = "item_name[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value"
        title_record = direct_product_provenance["rows"][0]["fields"][title_field]
        title_record["value"] = "Sculpture family"
        title_record["source"] = {"type": "product_cell", "reference": "Products!B7"}
        title_record["confirmation_status"] = "not_required"
        report = validator.validate_mapping(direct_product_provenance, self.blank)
        self.assertTrue(report["ok"], report["errors"])

        wrong_product_hash = copy.deepcopy(self.mapping)
        wrong_product_hash["inputs"]["product"]["sha256"] = "0" * 64
        report = validator.validate_mapping(wrong_product_hash, self.blank)
        self.assertIn(
            "product_input_hash_mismatch",
            {item["code"] for item in report["errors"]},
        )

        missing_header_product = self.project / "product-missing-role-header.xlsx"
        replace_sheet_cell_text(self.product, missing_header_product, "A1", "角色")
        missing_header_mapping = copy.deepcopy(self.mapping)
        missing_header_mapping["inputs"]["product"] = {
            "path": str(missing_header_product.resolve()),
            "sha256": sha256(missing_header_product),
        }
        report = validator.validate_mapping(missing_header_mapping, self.blank)
        self.assertIn(
            "product_required_headers_missing",
            {item["code"] for item in report["errors"]},
        )

        nonexistent_source_row = copy.deepcopy(self.mapping)
        nonexistent_source_row["rows"][0]["source_row"] = 900
        nonexistent_source_row["rows"][0]["source_key"] = "product-row-900"
        report = validator.validate_mapping(nonexistent_source_row, self.blank)
        self.assertIn("source_row_not_found", {item["code"] for item in report["errors"]})

        forged_sample = copy.deepcopy(self.mapping)
        forged_sample["templates"]["sample_sha256"] = "0" * 64
        forged_sample["templates"]["sample_verification"] = "report_verified"
        report = validator.validate_mapping(forged_sample, self.blank)
        self.assertIn(
            "sample_index_metadata_mismatch",
            {item["code"] for item in report["errors"]},
        )

        incomplete_measurement = copy.deepcopy(self.mapping)
        weight_value = "item_weight[marketplace_id=ATVPDKIKX0DER]#1.value"
        weight_unit = "item_weight[marketplace_id=ATVPDKIKX0DER]#1.unit"
        measured_row = next(
            row
            for row in incomplete_measurement["rows"]
            if weight_value in row["fields"] and weight_unit in row["fields"]
        )
        measured_row["fields"].pop(weight_unit)
        report = validator.validate_mapping(incomplete_measurement, self.blank)
        self.assertIn(
            "value_unit_pair_incomplete",
            {item["code"] for item in report["errors"]},
        )

        overlapping_plan = copy.deepcopy(self.mapping)
        overlap_role = overlapping_plan["rows"][0]["role"]
        overlap_field = overlapping_plan["field_plan"]["must_fill"][overlap_role][0]
        overlapping_plan["field_plan"]["sample_preferred"].setdefault(overlap_role, []).append(
            overlap_field
        )
        report = validator.validate_mapping(overlapping_plan, self.blank)
        self.assertIn("field_plan_sets_overlap", {item["code"] for item in report["errors"]})

        sample_as_product = copy.deepcopy(self.mapping)
        sample_as_product["inputs"]["product"] = {
            "path": str(self.sample.resolve()),
            "sha256": sha256(self.sample),
        }
        report = validator.validate_mapping(sample_as_product, self.blank)
        self.assertIn(
            "product_input_template_library_forbidden",
            {item["code"] for item in report["errors"]},
        )

        leaked_sample_preferences = copy.deepcopy(self.mapping)
        leaked_sample_preferences["task"]["fill_mode"] = "NO_SAMPLE_CONFIRMED"
        leaked_sample_preferences["templates"].pop("sample_sha256", None)
        leaked_sample_preferences["templates"].pop("sample_verification", None)
        leaked_sample_preferences["field_plan"]["sample_preferred"] = {}
        report = validator.validate_mapping(leaked_sample_preferences, self.blank)
        self.assertIn(
            "sample_preferred_forbidden_without_sample",
            {item["code"] for item in report["errors"]},
        )

        unresolved_local = copy.deepcopy(self.mapping)
        unresolved_local["blocking_errors"] = [{"code": "known_blocker"}]
        first_record = next(iter(unresolved_local["rows"][0]["fields"].values()))
        first_record["confirmation_status"] = "pending"
        first_record["validation"]["status"] = "pending"
        report = validator.validate_mapping(unresolved_local, self.blank)
        unresolved_codes = {item["code"] for item in report["errors"]}
        self.assertIn("declared_blocking_errors_present", unresolved_codes)
        self.assertIn("field_confirmation_pending", unresolved_codes)
        self.assertIn("field_validation_pending", unresolved_codes)

        wrong_sheet = self.project / "wrong-sheet.xlsm"
        rename_template_sheet(self.blank, wrong_sheet)
        report = validator.validate_mapping(self.mapping, wrong_sheet)
        self.assertIn("template_context_failed", {item["code"] for item in report["errors"]})

        manual_draft = copy.deepcopy(self.mapping)
        manual_draft["task"]["result_status"] = "DRAFT_NOT_FOR_UPLOAD"
        manual_field = "mounting_type[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value"
        manual_row = manual_draft["rows"][1]
        manual_row["fields"][manual_field] = {
            "value": context_mod.MANUAL_REVIEW_VALUE,
            "decision_set": "sample_preferred",
            "source": {
                "type": "manual_review_marker",
                "reference": f"manual_review:{manual_row['source_row']}:{manual_field}",
            },
            "confidence": 0.0,
            "confirmation_status": "not_required",
            "validation": {
                "status": "warning",
                "messages": ["信息不足，请人工核对"],
            },
        }
        manual_draft["manual_review"] = [{
            "source_row": manual_row["source_row"],
            "role": "Child",
            "field": manual_field,
            "label": "Mounting Type",
            "value": context_mod.MANUAL_REVIEW_VALUE,
            "reason": "产品信息未提供安装方式",
            "data_definition": self.context["data_definitions"][manual_field],
            "template_restriction": {
                "allowed_values": self.context["valid_values_by_field"][manual_field],
            },
        }]
        report = validator.validate_mapping(manual_draft, self.blank)
        self.assertTrue(report["ok"], report["errors"])
        self.assertIn(
            "manual_review_bypasses_allowed_value_in_draft",
            {item["code"] for item in report["warnings"]},
        )

        local_marker = copy.deepcopy(manual_draft)
        local_marker["task"]["result_status"] = "LOCAL_VALIDATION_PASSED"
        report = validator.validate_mapping(local_marker, self.blank)
        self.assertIn(
            "manual_review_requires_draft",
            {item["code"] for item in report["errors"]},
        )

        blank_sample_field = next(
            field
            for field in self.context["template"]["fields"]
            if field.startswith("other_product_image_locator_8")
        )
        forged_marker = copy.deepcopy(manual_draft)
        forged_marker["field_plan"]["sample_preferred"]["Child"].append(blank_sample_field)
        forged_marker["rows"][1]["fields"][blank_sample_field] = {
            "value": context_mod.MANUAL_REVIEW_VALUE,
            "decision_set": "sample_preferred",
            "source": {
                "type": "manual_review_marker",
                "reference": f"manual_review:8:{blank_sample_field}",
            },
            "confidence": 0.0,
            "confirmation_status": "not_required",
            "validation": {
                "status": "warning",
                "messages": ["信息不足，请人工核对"],
            },
        }
        forged_marker["manual_review"].append({
            "source_row": 8,
            "role": "Child",
            "field": blank_sample_field,
            "label": "Other Image URL 8",
            "value": context_mod.MANUAL_REVIEW_VALUE,
            "reason": "fixture",
            "data_definition": self.context["data_definitions"].get(blank_sample_field, {}),
            "template_restriction": {"allowed_values": []},
        })
        report = validator.validate_mapping(forged_marker, self.blank)
        self.assertIn(
            "manual_review_field_not_in_sample",
            {item["code"] for item in report["errors"]},
        )

        legacy = copy.deepcopy(self.mapping)
        legacy["schema_version"] = "2.0"
        legacy["field_plan"].pop("rule_default")
        legacy.pop("manual_review")
        condition_field = next(
            field for field in self.context["template"]["fields"]
            if field.startswith("condition_type[")
        )
        legacy["field_plan"]["sample_preferred"].setdefault("Parent", []).append(condition_field)
        legacy["field_plan"]["sample_preferred"].setdefault("Child", []).append(condition_field)
        legacy_confirmation = {
            "id": "legacy-condition-new",
            "field": condition_field,
            "value": "New",
            "confirmed": True,
        }
        legacy["confirmations"].append(legacy_confirmation)
        for row in legacy["rows"]:
            row["fields"][condition_field] = {
                "value": "New",
                "decision_set": "sample_preferred",
                "source": {
                    "type": "user_confirmation",
                    "reference": "confirmation:legacy-condition-new",
                },
                "confidence": 1.0,
                "confirmation_status": "confirmed",
                "validation": {"status": "passed", "messages": []},
            }
        report = validator.validate_mapping(legacy, self.blank)
        self.assertTrue(report["ok"], report["errors"])

    def test_03b_mapping_v22_rule_contract(self) -> None:
        mapping = build_v22_mapping(self.mapping, self.context)
        report = validator.validate_mapping(mapping, self.blank)
        self.assertTrue(report["ok"], report["errors"])

        parent_bases = {
            validator._field_base(field) for field in mapping["rows"][0]["fields"]
        }
        self.assertNotIn("model_number", parent_bases)
        self.assertNotIn("manufacturer", parent_bases)

        child = mapping["rows"][1]
        fields_by_base = {
            validator._field_base(field): field for field in child["fields"]
        }
        model_number_field = fields_by_base["model_number"]
        manufacturer_field = fields_by_base["manufacturer"]
        sku_field = fields_by_base["contribution_sku"]
        brand_field = fields_by_base["brand"]
        self.assertEqual(
            child["fields"][model_number_field]["value"],
            child["fields"][sku_field]["value"],
        )
        self.assertEqual(
            child["fields"][manufacturer_field]["value"],
            child["fields"][brand_field]["value"],
        )

        wrong_model = copy.deepcopy(mapping)
        wrong_model["rows"][1]["fields"][model_number_field]["value"] = "WRONG"
        wrong_report = validator.validate_mapping(wrong_model, self.blank)
        self.assertIn(
            "model_number_must_equal_sku",
            {item["code"] for item in wrong_report["errors"]},
        )

        wrong_manufacturer = copy.deepcopy(mapping)
        wrong_manufacturer["rows"][1]["fields"][manufacturer_field]["value"] = "WRONG"
        wrong_report = validator.validate_mapping(wrong_manufacturer, self.blank)
        self.assertIn(
            "manufacturer_must_equal_brand",
            {item["code"] for item in wrong_report["errors"]},
        )

        fixture_row = {
            "values": {"父子变体": "子体", "标题": "Outdoor hooks 10PCS"},
            "cell_references": {"标题": "Products!B2"},
        }
        self.assertEqual(context_mod._parse_pack_count(fixture_row)["value"], "10")
        components_only = {
            "values": {"父子变体": "子体", "标题": "Set includes hat, wings and prop"},
            "cell_references": {"标题": "Products!B2"},
        }
        self.assertEqual(context_mod._parse_pack_count(components_only)["value"], "1")

    def test_04_no_sample_mode_keeps_evidenced_optional_fields(self) -> None:
        blocked_context_path = self.project / "blocked-gtin-context.json"
        with mock.patch(
            "sys.argv",
            [
                "extract_inventory_context.py",
                "--product",
                str(self.product),
                "--template",
                str(self.blank),
                "--marketplace",
                "ATVPDKIKX0DER",
                "--content-language",
                "en_US",
                "--product-type",
                "SCULPTURE",
                "--node",
                "outdoor-statues",
                "--out",
                str(blocked_context_path),
            ],
        ):
            self.assertEqual(context_mod.main(), 2)
        self.assertTrue(blocked_context_path.is_file())

        product = self.project / "product.xlsx"
        make_product_xlsx(product)
        context = context_mod.build_context(
            product,
            self.blank,
            None,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="statues",
            gtin_status=None,
        )
        self.assertEqual(context["product_input"]["path"], str(product.resolve()))
        self.assertEqual(context["product_input"]["sha256"], sha256(product))
        self.assertEqual(
            context["product_sheet"]["rows"][0]["cell_references"]["标题"],
            "Products!B2",
        )
        evidence = {item["field"] for item in context["field_decision"]["evidence_fillable"]}
        standalone_must = set(context["field_decision"]["must_fill"]["Standalone"])
        self.assertFalse(standalone_must & evidence)
        main_image = "main_product_image_locator[marketplace_id=ATVPDKIKX0DER]#1.media_location"
        self.assertIn(main_image, evidence)
        self.assertIn(main_image, context["target_fields"])
        self.assertLess(len(context["target_fields"]), 105)

        measurement_product = self.project / "product-measurements.xlsx"
        make_product_xlsx(measurement_product, measurements=True)
        measurement_context = context_mod.build_context(
            measurement_product,
            self.blank,
            None,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="statues",
        )
        hints = {
            item["field"]: item
            for item in measurement_context["field_resolution"]["rows"][0]["hints"]
        }
        depth = "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.depth.value"
        width = "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.width.value"
        depth_unit = "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.depth.unit"
        item_weight = "item_weight[marketplace_id=ATVPDKIKX0DER]#1.value"
        item_weight_unit = "item_weight[marketplace_id=ATVPDKIKX0DER]#1.unit"
        normalized_weight_unit = "item_weight[marketplace_id=ATVPDKIKX0DER]#1.normalized_value.unit"
        package_length = "item_package_dimensions[marketplace_id=ATVPDKIKX0DER]#1.length.value"
        package_weight = "item_package_weight[marketplace_id=ATVPDKIKX0DER]#1.value"
        self.assertEqual(hints[depth]["value"], "5")
        self.assertEqual(hints[width]["value"], "10")
        self.assertEqual(hints[depth_unit]["value"], "Inches")
        self.assertEqual(hints[item_weight]["value"], "2.205")
        self.assertEqual(hints[item_weight_unit]["value"], "Pounds")
        self.assertEqual(hints[normalized_weight_unit]["value"], "pounds")
        self.assertEqual(hints[package_length]["value"], "10")
        self.assertEqual(hints[package_length]["status"], "fallback_from_product")
        self.assertEqual(hints[package_weight]["value"], "2.205")
        self.assertEqual(hints[package_weight]["status"], "fallback_from_product")
        evidenced = {
            item["field"]
            for item in measurement_context["field_decision"]["evidence_fillable"]
        }
        self.assertIn(depth, evidenced)
        self.assertIn(package_weight, evidenced)
        condition_field = next(
            field for field in measurement_context["template"]["fields"]
            if field.startswith("condition_type[")
        )
        self.assertIn(
            condition_field,
            measurement_context["field_decision"]["rule_default"]["Standalone"],
        )
        self.assertEqual(context_mod._convert_measurement("25.4", "mm", "length"), "1")
        self.assertEqual(context_mod._convert_measurement("0.1", "m", "length"), "3.937")
        self.assertEqual(context_mod._convert_measurement("10", "in", "length"), "10")
        self.assertEqual(context_mod._convert_measurement("1", "kg", "weight"), "2.205")
        self.assertEqual(context_mod._convert_measurement("16", "oz", "weight"), "1")
        self.assertEqual(context_mod._convert_measurement("2", "lb", "weight"), "2")
        self.assertEqual(
            context_mod._parse_dimension_triplet("25.4×12.7×50.8 cm", ""),
            (["10", "5", "20"], "cm"),
        )

        partial_package_product = self.project / "product-partial-package.xlsx"
        make_product_xlsx(
            partial_package_product,
            measurements=True,
            measurement_values=[
                "25.4", "12.7", "50.8", "cm", "1000", "g",
                "30.48", "", "", "cm", "", "",
            ],
        )
        partial_context = context_mod.build_context(
            partial_package_product,
            self.blank,
            None,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="statues",
        )
        partial_hints = {
            item["field"]: item
            for item in partial_context["field_resolution"]["rows"][0]["hints"]
        }
        package_width = "item_package_dimensions[marketplace_id=ATVPDKIKX0DER]#1.width.value"
        package_height = "item_package_dimensions[marketplace_id=ATVPDKIKX0DER]#1.height.value"
        self.assertEqual(partial_hints[package_length]["value"], "12")
        self.assertEqual(partial_hints[package_width]["value"], "5")
        self.assertEqual(partial_hints[package_height]["value"], "20")

        missing_unit_product = self.project / "product-measurements-without-unit.xlsx"
        make_product_xlsx(
            missing_unit_product,
            measurements=True,
            measurement_values=[
                "25.4", "12.7", "50.8", "", "1000", "",
                "", "", "", "", "", "",
            ],
        )
        missing_unit_context = context_mod.build_context(
            missing_unit_product,
            self.blank,
            None,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="statues",
        )
        missing_unit_hints = {
            item["field"]
            for item in missing_unit_context["field_resolution"]["rows"][0]["hints"]
        }
        self.assertNotIn(depth, missing_unit_hints)
        self.assertNotIn(item_weight, missing_unit_hints)

        no_measurement_context = context_mod.build_context(
            product,
            self.blank,
            None,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="statues",
        )
        no_measurement_hints = {
            item["field"]
            for item in no_measurement_context["field_resolution"]["rows"][0]["hints"]
        }
        self.assertNotIn(depth, no_measurement_hints)
        self.assertNotIn(package_weight, no_measurement_hints)

        sample_missing_measurement_context = context_mod.build_context(
            self.product,
            self.blank,
            self.sample,
            marketplace="ATVPDKIKX0DER",
            content_language="en_US",
            product_type="SCULPTURE",
            node="outdoor-statues",
            reference_verification="user_confirmed",
        )
        child_resolution = next(
            item
            for item in sample_missing_measurement_context["field_resolution"]["rows"]
            if item["role"] == "Child"
        )
        child_hints = {item["field"]: item for item in child_resolution["hints"]}
        item_dimension_values = {
            "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.depth.value",
            "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.height.value",
            "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.width.value",
        }
        item_dimension_units = {
            "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.depth.unit",
            "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.height.unit",
            "item_depth_width_height[marketplace_id=ATVPDKIKX0DER]#1.width.unit",
        }
        self.assertTrue(item_dimension_values <= set(child_resolution["manual_review_candidates"]))
        for field in item_dimension_units:
            self.assertEqual(child_hints[field]["value"], "Inches")
            self.assertEqual(child_hints[field]["status"], "resolved_default_unit")

    def test_05_safe_writer_and_task_state(self) -> None:
        scope = {
            "marketplace": "ATVPDKIKX0DER",
            "content_language": "en_US",
            "product_type": "SCULPTURE",
            "browse_node": "outdoor-statues",
            "fill_mode": "SAMPLE_GUIDED",
        }
        task_state.save_task(
            self.project,
            self.mapping["task"]["task_id"],
            scope,
            {
                "product": self.mapping["inputs"]["product"],
                "templates": self.mapping["templates"],
            },
            "DRAFT_NOT_FOR_UPLOAD",
        )
        retry = task_state.save_task(
            self.project,
            self.mapping["task"]["task_id"],
            scope,
            {
                "product": self.mapping["inputs"]["product"],
                "templates": self.mapping["templates"],
            },
            "DRAFT_NOT_FOR_UPLOAD",
        )
        self.assertTrue(retry["retry"])
        with self.assertRaisesRegex(task_state.LibraryError, "cannot change the scope"):
            task_state.save_task(
                self.project,
                self.mapping["task"]["task_id"],
                {**scope, "browse_node": "statues"},
                {
                    "product": self.mapping["inputs"]["product"],
                    "templates": self.mapping["templates"],
                },
                "DRAFT_NOT_FOR_UPLOAD",
            )
        for row in self.mapping["rows"]:
            sku = row["fields"]["contribution_sku#1.value"]["value"]
            task_state.reserve_sku(
                self.project,
                self.mapping["task"]["task_id"],
                row["role"],
                row["source_key"],
                sku,
            )
        changed_template_selection = copy.deepcopy(self.mapping)
        changed_template_selection["templates"]["sample_sha256"] = "0" * 64
        state_check = task_state.verify_mapping_reservations(
            self.project,
            self.mapping["task"]["task_id"],
            changed_template_selection,
        )
        self.assertIn(
            "template_snapshot_mismatch",
            {item["code"] for item in state_check["errors"]},
        )
        preflight = validator.validate_mapping(self.mapping, self.blank)
        self.assertTrue(preflight["ok"], preflight["errors"])

        output = self.project / "输出" / "SCULPTURE-filled.xlsm"
        report = writer.write_workbook(self.blank, self.mapping_path, output, self.project)
        self.assertEqual(report["status"], "LOCAL_VALIDATION_PASSED")
        self.assertTrue(report["output_validation"]["ok"])
        with ZipFile(output) as archive:
            self.assertIsNone(archive.testzip())

        task = task_state.get_task(self.project, self.mapping["task"]["task_id"])
        self.assertEqual(task["result_status"], "LOCAL_VALIDATION_PASSED")
        self.assertTrue(all(item["status"] == "committed" for item in task["sku_reservations"]))

        with ZipFile(output) as archive:
            _, sheet_path = writer.find_template_sheet(archive)
            root = ET.fromstring(archive.read(sheet_path))
        rows = {int(row.attrib["r"]): row for row in root.findall("a:sheetData/a:row", NS)}
        self.assertEqual(
            {key: value for key, value in rows[6].attrib.items() if key != "r"},
            {key: value for key, value in rows[7].attrib.items() if key != "r"},
        )
        self.assertEqual(self.source_hashes, (sha256(self.source_blank), sha256(self.source_sample)))

        with self.assertRaisesRegex(task_state.LibraryError, "requires an attached processing report"):
            task_state.update_task_result(
                self.project,
                self.mapping["task"]["task_id"],
                "ACCEPTED_REPORT_VERIFIED",
                None,
            )
        processing_report = self.project / "amazon-processing-report.txt"
        processing_report.write_text(
            "Feed Processing Summary\n"
            "Number of records processed: 4\n"
            "original-record-number\tsku\terror-code\terror-message\n",
            encoding="utf-8",
        )
        accepted = task_state.update_task_result(
            self.project,
            self.mapping["task"]["task_id"],
            "ACCEPTED_REPORT_VERIFIED",
            None,
            report_path=processing_report,
            note="fixture verification",
        )
        self.assertEqual(accepted["acceptance_evidence_path"], str(processing_report.resolve()))

        task_state.update_task_result(
            self.project,
            self.mapping["task"]["task_id"],
            "DRAFT_NOT_FOR_UPLOAD",
            None,
            note="fixture draft revision",
        )
        draft_revision = copy.deepcopy(self.mapping)
        draft_revision["task"]["result_status"] = "DRAFT_NOT_FOR_UPLOAD"
        draft_revision_path = self.project / "draft-revision-mapping.json"
        draft_revision_path.write_text(
            json.dumps(draft_revision, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        draft_revision_output = (
            self.project / "输出" / "SCULPTURE-revision-DRAFT_NOT_FOR_UPLOAD.xlsm"
        )
        draft_revision_report = writer.write_workbook(
            self.blank,
            draft_revision_path,
            draft_revision_output,
            self.project,
        )
        self.assertEqual(
            draft_revision_report["task_state"]["finalized"]["sku_status"],
            "committed_reused",
        )
        task = task_state.get_task(self.project, self.mapping["task"]["task_id"])
        self.assertTrue(
            all(item["status"] == "committed" for item in task["sku_reservations"])
        )

    def test_06_writer_path_and_failure_guards(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be different"):
            writer.validate_paths(self.blank, self.blank)
        with self.assertRaisesRegex(ValueError, "must not be written"):
            writer.validate_paths(self.blank, self.project / "样板模板库" / "output.xlsm")

        invalid_path = self.project / "输出" / "invalid-mapping.xlsm"
        invalid_mapping_path = self.project / "invalid.json"
        invalid_mapping_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Mapping validation failed"):
            writer.write_workbook(self.blank, invalid_mapping_path, invalid_path)
        self.assertFalse(invalid_path.exists())

        interrupted_path = self.project / "输出" / "interrupted.xlsm"
        with mock.patch.object(
            writer,
            "validate_output",
            return_value={"ok": False, "errors": [{"code": "injected_failure"}], "warnings": [], "status": "invalid"},
        ):
            with self.assertRaisesRegex(ValueError, "Output validation failed"):
                writer.write_workbook(self.blank, self.mapping_path, interrupted_path)
        self.assertFalse(interrupted_path.exists())

        draft_mapping = copy.deepcopy(self.mapping)
        draft_mapping["task"]["result_status"] = "DRAFT_NOT_FOR_UPLOAD"
        draft_mapping_path = self.project / "draft-mapping.json"
        draft_mapping_path.write_text(
            json.dumps(draft_mapping, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "filename must contain DRAFT_NOT_FOR_UPLOAD"):
            writer.write_workbook(
                self.blank,
                draft_mapping_path,
                self.project / "输出" / "ordinary-name.xlsm",
            )
        draft_output = self.project / "输出" / "SCULPTURE-DRAFT_NOT_FOR_UPLOAD.xlsm"
        draft_report = writer.write_workbook(
            self.blank,
            draft_mapping_path,
            draft_output,
        )
        self.assertEqual(draft_report["upload_eligibility"], "NOT_FOR_UPLOAD")

        fake_macro_template = self.project / "空白模板库" / "SCULPTURE-fake-macro.xlsm"
        fake_macro_payload = b"synthetic-vba-part-copy-test"
        add_zip_part(self.blank, fake_macro_template, "xl/vbaProject.bin", fake_macro_payload)
        library.scan_project(self.project)
        fake_query = library.query_project(
            self.project,
            "ATVPDKIKX0DER",
            "en_US",
            "SCULPTURE",
            "outdoor-statues",
            "all",
        )
        fake_blank_entry = next(
            item for item in fake_query["blank_templates"] if item["filename"] == fake_macro_template.name
        )
        fake_macro_mapping = copy.deepcopy(self.mapping)
        fake_macro_mapping["templates"]["blank_entry_id"] = fake_blank_entry["entry_id"]
        fake_macro_mapping["templates"]["blank_sha256"] = sha256(fake_macro_template)
        fake_macro_mapping_path = self.project / "fake-macro-mapping.json"
        fake_macro_mapping_path.write_text(
            json.dumps(fake_macro_mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        fake_macro_output = self.project / "输出" / "fake-macro-output.xlsm"
        report = writer.write_workbook(fake_macro_template, fake_macro_mapping_path, fake_macro_output)
        self.assertTrue(report["output_validation"]["checks"]["vba_part_hashes"])
        with ZipFile(fake_macro_output) as archive:
            self.assertEqual(archive.read("xl/vbaProject.bin"), fake_macro_payload)

        unauthorized_output = self.project / "输出" / "unauthorized-extra-part.xlsm"
        add_zip_part(fake_macro_output, unauthorized_output, "custom/untracked-part.bin", b"not allowed")
        unauthorized_report = validator.validate_output(fake_macro_template, unauthorized_output)
        self.assertFalse(unauthorized_report["ok"])
        self.assertIn(
            "protected_parts_added",
            {item["code"] for item in unauthorized_report["errors"]},
        )

        changed_columns = self.project / "输出" / "changed-columns.xlsm"
        mutate_first_column_width(fake_macro_output, changed_columns)
        changed_columns_report = validator.validate_output(fake_macro_template, changed_columns)
        self.assertFalse(changed_columns_report["ok"])
        self.assertIn(
            "inventory_non_data_structure_changed",
            {item["code"] for item in changed_columns_report["errors"]},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
