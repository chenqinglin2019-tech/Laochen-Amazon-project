#!/usr/bin/env python3
"""Index and query project-local Amazon inventory template libraries.

The project root may contain two recursively scanned directories:

* ``空白模板库``: mandatory blank Amazon templates.
* ``样板模板库``: optional, previously filled reference templates.

All state is stored below the project root in
``.amazon-inventory-fill/state.sqlite3``.  The implementation uses only the
Python standard library and reads XLSX/XLSM files directly as OOXML ZIP files.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import posixpath
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


DB_RELATIVE_PATH = Path(".amazon-inventory-fill/state.sqlite3")
LIBRARY_DIRS = {"blank": "空白模板库", "sample": "样板模板库"}
SUPPORTED_SUFFIXES = {".xlsx", ".xlsm"}
SAMPLE_STATUSES = ("unverified", "user_confirmed", "report_verified")
STATUS_RANK = {status: index for index, status in enumerate(SAMPLE_STATUSES)}
REPORT_SUFFIXES = {".txt", ".tsv", ".csv", ".xml", ".json", ".xlsx"}
SCHEMA_VERSION = "1"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CORE = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
NS_DCTERMS = "http://purl.org/dc/terms/"
NS = {"a": NS_MAIN, "r": NS_REL, "rel": NS_PKG_REL}


class LibraryError(Exception):
    """A user-facing CLI error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_processing_report_evidence(path: Path) -> Path:
    report = path.expanduser().resolve()
    if not report.is_file() or report.stat().st_size == 0:
        raise LibraryError(f"Amazon processing report must be a nonempty file: {report}")
    suffix = report.suffix.casefold()
    if suffix not in REPORT_SUFFIXES:
        raise LibraryError(
            "Amazon processing report must use a supported evidence format: "
            + ", ".join(sorted(REPORT_SUFFIXES))
        )
    try:
        if suffix == ".xlsx":
            with ZipFile(report) as archive:
                texts = load_shared_strings(archive)
                for name in archive.namelist():
                    if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                        continue
                    root = ET.fromstring(archive.read(name))
                    texts.extend(node.text or "" for node in root.iter() if node.text)
            content = " ".join(texts)
        else:
            content = report.read_bytes()[: 4 * 1024 * 1024].decode("utf-8-sig", errors="replace")
    except (BadZipFile, ET.ParseError, OSError) as exc:
        raise LibraryError(f"Amazon processing report cannot be inspected: {exc}") from exc
    normalized = re.sub(r"[^a-z0-9]+", " ", content.casefold()).strip()
    strong_markers = (
        "feed processing summary",
        "processing report",
        "number of records processed",
        "processing status",
        "result feed document id",
    )
    column_markers = (
        "original record number",
        "record number",
        "error code",
        "error message",
        "warning code",
        "sku",
    )
    has_strong_marker = any(marker in normalized for marker in strong_markers)
    column_marker_count = sum(marker in normalized for marker in column_markers)
    if not has_strong_marker or column_marker_count < 2:
        raise LibraryError(
            "Evidence file does not contain recognizable Amazon processing-report markers"
        )
    return report


def normalize_marketplace(value: str | None) -> str:
    text = (value or "").strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.upper()


def normalize_language(value: str | None) -> str:
    text = (value or "").strip().replace("-", "_")
    if not text:
        return ""
    parts = text.split("_", 1)
    return parts[0].lower() if len(parts) == 1 else f"{parts[0].lower()}_{parts[1].upper()}"


def normalize_product_type(value: str | None) -> str:
    return re.sub(r"\s+", "_", (value or "").strip()).upper()


def normalize_browse_node(value: str | None) -> str:
    return (value or "").strip().casefold()


def column_number(cell_ref: str | None) -> int | None:
    match = re.match(r"([A-Z]+)[0-9]+", cell_ref or "")
    if not match:
        return None
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - 64
    return number


def relationship_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def load_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{NS_MAIN}}}t"))
        for item in root.findall("a:si", NS)
    ]


def cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    if cell_type == "s" and value is not None and value.text is not None:
        index = int(value.text)
        if index < 0 or index >= len(shared_strings):
            raise ValueError(f"Shared string index out of range: {index}")
        return shared_strings[index]
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{NS_MAIN}}}t"))
    if cell_type == "b" and value is not None:
        return "TRUE" if value.text == "1" else "FALSE"
    return value.text if value is not None and value.text is not None else ""


def worksheet_cells(root: ET.Element, shared_strings: list[str]) -> dict[tuple[int, int], str]:
    result: dict[tuple[int, int], str] = {}
    for row in root.findall("a:sheetData/a:row", NS):
        row_number = int(row.attrib["r"])
        for cell in row.findall("a:c", NS):
            col = column_number(cell.attrib.get("r"))
            if col is not None:
                result[(row_number, col)] = cell_text(cell, shared_strings).strip()
    return result


def parse_settings(raw: str) -> dict[str, str]:
    chunks: list[tuple[int, str]] = []
    for match in re.finditer(r"(?:^|\s)settings(\d*)=(.*?)(?=\ssettings\d+=|$)", raw, re.DOTALL):
        chunks.append((int(match.group(1) or "1"), match.group(2)))
    if not chunks:
        return {}
    payload = "".join(value for _, value in sorted(chunks))
    settings: dict[str, str] = {}
    for part in payload.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        # Amazon metadata contains base64.  unquote_plus would corrupt literal
        # plus signs, so percent-decode without treating '+' as whitespace.
        settings[urllib.parse.unquote(key)] = urllib.parse.unquote(value)
    return settings


def decode_base64_text(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    try:
        return base64.b64decode(padded).decode("utf-8")
    except Exception:
        return base64.urlsafe_b64decode(padded).decode("utf-8")


def decoded_product_types(value: str | None) -> list[str]:
    text = decode_base64_text(value)
    if not text:
        return []
    candidates: list[str]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        candidates = [text]
    else:
        if isinstance(parsed, list):
            candidates = [str(item) for item in parsed]
        elif isinstance(parsed, str):
            candidates = [parsed]
        else:
            candidates = []
    return sorted({normalize_product_type(item) for item in candidates if normalize_product_type(item)})


def decoded_browse_classifications(value: str | None) -> list[tuple[str, str]]:
    text = decode_base64_text(value)
    if not text:
        return []
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("browseClassifications must decode to a JSON array")
    pairs: set[tuple[str, str]] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        product_type = normalize_product_type(str(item.get("productType") or ""))
        nodes = item.get("browseClassificationKeys") or []
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            normalized = normalize_browse_node(str(node))
            if normalized:
                pairs.add((product_type, normalized))
    return sorted(pairs)


def first_core_timestamp(archive: ZipFile) -> str | None:
    if "docProps/core.xml" not in archive.namelist():
        return None
    root = ET.fromstring(archive.read("docProps/core.xml"))
    for namespace, name in ((NS_DCTERMS, "modified"), (NS_DCTERMS, "created"), (NS_CORE, "lastPrinted")):
        node = root.find(f"{{{namespace}}}{name}")
        if node is not None and node.text:
            return node.text.strip()
    return None


def parse_workbook(path: Path) -> dict[str, Any]:
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        required_parts = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
        missing_parts = sorted(required_parts - names)
        if missing_parts:
            raise ValueError("Missing OOXML part(s): " + ", ".join(missing_parts))

        shared_strings = load_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationship_map = {
            rel.attrib["Id"]: relationship_target(rel.attrib["Target"])
            for rel in relationships.findall("rel:Relationship", NS)
        }

        template_name = ""
        template_part = ""
        sheets = workbook.find("a:sheets", NS)
        for sheet in list(sheets) if sheets is not None else []:
            name = sheet.attrib.get("name", "")
            if name.strip().casefold() not in {"template", "模板"}:
                continue
            rel_id = sheet.attrib.get(f"{{{NS_REL}}}id", "")
            template_name = name
            template_part = relationship_map.get(rel_id, "")
            break
        if not template_part or template_part not in names:
            raise ValueError("Could not find a readable Template/模板 worksheet")

        sheet_root = ET.fromstring(archive.read(template_part))
        cells = worksheet_cells(sheet_root, shared_strings)
        row_one = " ".join(value for (row, _), value in sorted(cells.items()) if row == 1 and value)
        settings = parse_settings(row_one)

        def setting_int(name: str, default: int) -> int:
            raw = settings.get(name, "")
            return int(raw) if raw.isdigit() else default

        label_row = setting_int("labelRow", 4)
        attribute_row = setting_int("attributeRow", 5)
        data_row = setting_int("dataRow", 7)
        ordered_fields = [
            value
            for (row, _col), value in sorted(cells.items(), key=lambda item: item[0][1])
            if row == attribute_row and value
        ]
        if not ordered_fields:
            raise ValueError(f"No technical fields found on attribute row {attribute_row}")
        if len(set(ordered_fields)) != len(ordered_fields):
            raise ValueError("Duplicate technical field names found in template")

        sku_columns = {
            column
            for (row, column), value in cells.items()
            if row == attribute_row and re.search(r"(?:^|[_.#])sku(?:$|[_.#])", value.casefold())
        }
        if not sku_columns:
            raise ValueError("No SKU technical field found on the attribute row")
        populated_sku_rows = sorted(
            {
                row
                for (row, column), value in cells.items()
                if row >= data_row and column in sku_columns and value.strip()
            }
        )
        fields_by_column = {
            column: value
            for (row, column), value in cells.items()
            if row == attribute_row and value
        }
        populated_fields = [
            field
            for column, field in sorted(fields_by_column.items())
            if any(
                row >= data_row and data_column == column and value.strip()
                for (row, data_column), value in cells.items()
            )
        ]

        marketplace = normalize_marketplace(settings.get("primaryMarketplaceId"))
        content_language = normalize_language(settings.get("contentLanguageTag"))
        header_language = normalize_language(settings.get("headerLanguageTag"))
        product_types = decoded_product_types(settings.get("ptds"))
        browse_pairs = decoded_browse_classifications(settings.get("browseClassifications"))
        browse_product_types = sorted({product_type for product_type, _ in browse_pairs if product_type})
        product_types = sorted(set(product_types) | set(browse_product_types))
        if len(product_types) == 1:
            browse_pairs = [
                (product_type or product_types[0], node) for product_type, node in browse_pairs
            ]
        browse_pairs = sorted(set(browse_pairs))
        browse_nodes = sorted({node for _product_type, node in browse_pairs})

        missing_metadata = []
        if not marketplace:
            missing_metadata.append("marketplace")
        if not content_language:
            missing_metadata.append("content language")
        if not product_types:
            missing_metadata.append("product type")
        if not browse_nodes:
            missing_metadata.append("browse nodes")
        if missing_metadata:
            raise ValueError("Missing required template metadata: " + ", ".join(missing_metadata))

        schema_fingerprint = hashlib.sha256("\n".join(ordered_fields).encode("utf-8")).hexdigest()

        template_identifier = settings.get("templateIdentifier") or None
        version_keys = ("Version", "templateVersion", "template_version", "schemaVersion", "feedVersion")
        explicit_version = next((settings[key] for key in version_keys if settings.get(key)), None)
        version = explicit_version or template_identifier
        version_source = "metadata" if explicit_version else "templateIdentifier" if template_identifier else None
        download_time = settings.get("timestamp") or first_core_timestamp(archive)

        return {
            "marketplace": marketplace,
            "content_language": content_language,
            "header_language": header_language or None,
            "product_type": product_types[0],
            "product_types": product_types,
            "browse_nodes": browse_nodes,
            "browse_pairs": browse_pairs,
            "version": version,
            "version_source": version_source,
            "download_time": download_time,
            "template_identifier": template_identifier,
            "template_sheet": template_name,
            "label_row": label_row,
            "attribute_row": attribute_row,
            "data_row": data_row,
            "populated_sku_rows": populated_sku_rows,
            "field_count": len(ordered_fields),
            "schema_fingerprint": schema_fingerprint,
            "technical_fields": ordered_fields,
            "populated_fields": populated_fields,
        }


def connect_database(project_root: Path) -> sqlite3.Connection:
    db_path = project_root / DB_RELATIVE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY,
            library_kind TEXT NOT NULL CHECK (library_kind IN ('blank', 'sample')),
            relative_path TEXT NOT NULL,
            absolute_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            suffix TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            marketplace TEXT,
            content_language TEXT,
            header_language TEXT,
            product_type TEXT,
            product_types_json TEXT NOT NULL DEFAULT '[]',
            browse_nodes_json TEXT NOT NULL DEFAULT '[]',
            version TEXT,
            version_source TEXT,
            download_time TEXT,
            template_identifier TEXT,
            template_sheet TEXT,
            label_row INTEGER,
            attribute_row INTEGER,
            data_row INTEGER,
            field_count INTEGER,
            schema_fingerprint TEXT,
            technical_fields_json TEXT NOT NULL DEFAULT '[]',
            populated_fields_json TEXT NOT NULL DEFAULT '[]',
            parse_status TEXT NOT NULL CHECK (parse_status IN ('ok', 'error')),
            parse_error TEXT,
            sample_status TEXT CHECK (sample_status IN ('unverified', 'user_confirmed', 'report_verified')),
            sample_status_updated_at TEXT,
            sample_evidence_path TEXT,
            sample_note TEXT,
            amazon_batch_id TEXT,
            upload_time TEXT,
            first_seen_at TEXT NOT NULL,
            last_scanned_at TEXT NOT NULL,
            UNIQUE (library_kind, relative_path)
        );

        CREATE TABLE IF NOT EXISTS template_browse_nodes (
            template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
            marketplace TEXT NOT NULL,
            content_language TEXT NOT NULL,
            product_type TEXT NOT NULL,
            browse_node TEXT NOT NULL,
            PRIMARY KEY (template_id, marketplace, content_language, product_type, browse_node)
        );

        CREATE INDEX IF NOT EXISTS idx_templates_sha256
            ON templates(library_kind, sha256);
        CREATE INDEX IF NOT EXISTS idx_template_query
            ON template_browse_nodes(marketplace, content_language, product_type, browse_node);
        """
    )
    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(templates)").fetchall()
    }
    for column, declaration in {
        "technical_fields_json": "TEXT NOT NULL DEFAULT '[]'",
        "populated_fields_json": "TEXT NOT NULL DEFAULT '[]'",
        "sample_evidence_path": "TEXT",
        "sample_note": "TEXT",
        "amazon_batch_id": "TEXT",
        "upload_time": "TEXT",
    }.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE templates ADD COLUMN {column} {declaration}")
    existing = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    if existing and existing["value"] != SCHEMA_VERSION:
        raise LibraryError(
            f"Unsupported database schema version {existing['value']}; expected {SCHEMA_VERSION}"
        )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )
    connection.commit()
    return connection


def best_status(statuses: Iterable[str | None]) -> str:
    valid = [status for status in statuses if status in STATUS_RANK]
    return max(valid, key=lambda status: STATUS_RANK[status]) if valid else "unverified"


def status_for_hash(connection: sqlite3.Connection, sha256: str) -> tuple[str, str | None]:
    rows = connection.execute(
        "SELECT sample_status, sample_status_updated_at FROM templates "
        "WHERE library_kind = 'sample' AND sha256 = ?",
        (sha256,),
    ).fetchall()
    status = best_status(row["sample_status"] for row in rows)
    timestamps = [
        row["sample_status_updated_at"]
        for row in rows
        if row["sample_status"] == status and row["sample_status_updated_at"]
    ]
    return status, max(timestamps) if timestamps else None


def workbook_files(library_root: Path) -> list[Path]:
    if not library_root.exists():
        return []
    if not library_root.is_dir():
        raise LibraryError(f"Template library path is not a directory: {library_root}")
    return sorted(
        path for path in library_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES
    )


def record_to_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "entry_id": row["id"],
        "library": row["library_kind"],
        "path": row["relative_path"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "marketplace": row["marketplace"],
        "content_language": row["content_language"],
        "header_language": row["header_language"],
        "product_type": row["product_type"],
        "product_types": json.loads(row["product_types_json"]),
        "browse_nodes": json.loads(row["browse_nodes_json"]),
        "version": row["version"],
        "version_source": row["version_source"],
        "download_time": row["download_time"],
        "template_identifier": row["template_identifier"],
        "schema_fingerprint": row["schema_fingerprint"],
        "field_count": row["field_count"],
        "parse_status": row["parse_status"],
        "parse_error": row["parse_error"],
        "sample_status": row["sample_status"],
        "sample_status_updated_at": row["sample_status_updated_at"],
        "sample_evidence_path": row["sample_evidence_path"],
        "sample_note": row["sample_note"],
        "amazon_batch_id": row["amazon_batch_id"],
        "upload_time": row["upload_time"],
        "last_scanned_at": row["last_scanned_at"],
    }


def scan_project(project_root: Path) -> dict[str, Any]:
    connection = connect_database(project_root)
    now = utc_now()
    summary: dict[str, Any] = {
        "project_root": str(project_root),
        "database": str(project_root / DB_RELATIVE_PATH),
        "libraries": {},
        "errors": [],
    }
    try:
        connection.execute("BEGIN IMMEDIATE")
        for library_kind, directory_name in LIBRARY_DIRS.items():
            library_root = project_root / directory_name
            files = workbook_files(library_root)
            seen_paths: list[str] = []
            counts = {"found": len(files), "ok": 0, "error": 0, "added": 0, "updated": 0, "unchanged": 0, "removed": 0}
            for path in files:
                relative_path = path.relative_to(project_root).as_posix()
                seen_paths.append(relative_path)
                previous = connection.execute(
                    "SELECT id, sha256 FROM templates WHERE library_kind = ? AND relative_path = ?",
                    (library_kind, relative_path),
                ).fetchone()
                stat = path.stat()
                digest = sha256_file(path)
                if previous is None:
                    counts["added"] += 1
                elif previous["sha256"] == digest:
                    counts["unchanged"] += 1
                else:
                    counts["updated"] += 1

                metadata: dict[str, Any] = {}
                parse_status = "ok"
                parse_error = None
                try:
                    metadata = parse_workbook(path)
                    if library_kind == "blank" and metadata["populated_fields"]:
                        raise ValueError("Blank library workbook contains populated product data fields")
                    if library_kind == "sample" and not metadata["populated_sku_rows"]:
                        raise ValueError("Sample library workbook contains no populated SKU data rows")
                    counts["ok"] += 1
                except (BadZipFile, ET.ParseError, UnicodeDecodeError, ValueError, KeyError, IndexError) as exc:
                    parse_status = "error"
                    parse_error = f"{type(exc).__name__}: {exc}"
                    counts["error"] += 1
                    summary["errors"].append({"path": relative_path, "error": parse_error})

                if library_kind == "sample":
                    sample_status, status_updated_at = status_for_hash(connection, digest)
                else:
                    sample_status, status_updated_at = None, None

                values = (
                    library_kind,
                    relative_path,
                    str(path.resolve()),
                    path.name,
                    path.suffix.casefold(),
                    stat.st_size,
                    stat.st_mtime_ns,
                    digest,
                    metadata.get("marketplace"),
                    metadata.get("content_language"),
                    metadata.get("header_language"),
                    metadata.get("product_type"),
                    canonical_json(metadata.get("product_types", [])),
                    canonical_json(metadata.get("browse_nodes", [])),
                    metadata.get("version"),
                    metadata.get("version_source"),
                    metadata.get("download_time"),
                    metadata.get("template_identifier"),
                    metadata.get("template_sheet"),
                    metadata.get("label_row"),
                    metadata.get("attribute_row"),
                    metadata.get("data_row"),
                    metadata.get("field_count"),
                    metadata.get("schema_fingerprint"),
                    canonical_json(metadata.get("technical_fields", [])),
                    canonical_json(metadata.get("populated_fields", [])),
                    parse_status,
                    parse_error,
                    sample_status,
                    status_updated_at,
                    now,
                    now,
                )
                connection.execute(
                    """
                    INSERT INTO templates(
                        library_kind, relative_path, absolute_path, filename, suffix,
                        size_bytes, mtime_ns, sha256, marketplace, content_language,
                        header_language, product_type, product_types_json, browse_nodes_json,
                        version, version_source, download_time, template_identifier,
                        template_sheet, label_row, attribute_row, data_row, field_count,
                        schema_fingerprint, technical_fields_json, populated_fields_json,
                        parse_status, parse_error, sample_status,
                        sample_status_updated_at, first_seen_at, last_scanned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(library_kind, relative_path) DO UPDATE SET
                        absolute_path = excluded.absolute_path,
                        filename = excluded.filename,
                        suffix = excluded.suffix,
                        size_bytes = excluded.size_bytes,
                        mtime_ns = excluded.mtime_ns,
                        sha256 = excluded.sha256,
                        marketplace = excluded.marketplace,
                        content_language = excluded.content_language,
                        header_language = excluded.header_language,
                        product_type = excluded.product_type,
                        product_types_json = excluded.product_types_json,
                        browse_nodes_json = excluded.browse_nodes_json,
                        version = excluded.version,
                        version_source = excluded.version_source,
                        download_time = excluded.download_time,
                        template_identifier = excluded.template_identifier,
                        template_sheet = excluded.template_sheet,
                        label_row = excluded.label_row,
                        attribute_row = excluded.attribute_row,
                        data_row = excluded.data_row,
                        field_count = excluded.field_count,
                        schema_fingerprint = excluded.schema_fingerprint,
                        technical_fields_json = excluded.technical_fields_json,
                        populated_fields_json = excluded.populated_fields_json,
                        parse_status = excluded.parse_status,
                        parse_error = excluded.parse_error,
                        sample_status = excluded.sample_status,
                        sample_status_updated_at = excluded.sample_status_updated_at,
                        last_scanned_at = excluded.last_scanned_at
                    """,
                    values,
                )
                template_id = connection.execute(
                    "SELECT id FROM templates WHERE library_kind = ? AND relative_path = ?",
                    (library_kind, relative_path),
                ).fetchone()["id"]
                connection.execute("DELETE FROM template_browse_nodes WHERE template_id = ?", (template_id,))
                if parse_status == "ok":
                    for product_type, browse_node in metadata["browse_pairs"]:
                        if not product_type and len(metadata["product_types"]) == 1:
                            product_type = metadata["product_types"][0]
                        if not product_type:
                            continue
                        connection.execute(
                            "INSERT OR IGNORE INTO template_browse_nodes "
                            "(template_id, marketplace, content_language, product_type, browse_node) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (
                                template_id,
                                metadata["marketplace"],
                                metadata["content_language"],
                                product_type,
                                browse_node,
                            ),
                        )

            if seen_paths:
                placeholders = ",".join("?" for _ in seen_paths)
                stale = connection.execute(
                    f"SELECT COUNT(*) AS count FROM templates WHERE library_kind = ? "
                    f"AND relative_path NOT IN ({placeholders})",
                    (library_kind, *seen_paths),
                ).fetchone()["count"]
                connection.execute(
                    f"DELETE FROM templates WHERE library_kind = ? AND relative_path NOT IN ({placeholders})",
                    (library_kind, *seen_paths),
                )
            else:
                stale = connection.execute(
                    "SELECT COUNT(*) AS count FROM templates WHERE library_kind = ?",
                    (library_kind,),
                ).fetchone()["count"]
                connection.execute("DELETE FROM templates WHERE library_kind = ?", (library_kind,))
            counts["removed"] = stale
            summary["libraries"][library_kind] = counts
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    summary["parse_status"] = "ok" if not summary["errors"] else "completed_with_errors"
    return summary


def query_project(
    project_root: Path,
    marketplace: str,
    content_language: str,
    product_type: str,
    browse_node: str,
    library: str,
    preferred_blank_entry_id: int | None = None,
) -> dict[str, Any]:
    db_path = project_root / DB_RELATIVE_PATH
    if not db_path.exists():
        raise LibraryError(f"Template index does not exist; run scan first: {db_path}")
    normalized = {
        "marketplace": normalize_marketplace(marketplace),
        "content_language": normalize_language(content_language),
        "product_type": normalize_product_type(product_type),
        "browse_node": normalize_browse_node(browse_node),
    }
    if not all(normalized.values()):
        raise LibraryError("Marketplace, content language, product type, and browse node are all required")
    connection = connect_database(project_root)
    try:
        sql = """
            SELECT DISTINCT t.*
            FROM templates AS t
            JOIN template_browse_nodes AS n ON n.template_id = t.id
            WHERE t.parse_status = 'ok'
              AND n.marketplace = ?
              AND n.content_language = ?
              AND n.product_type = ?
              AND n.browse_node = ?
        """
        parameters: list[Any] = [
            normalized["marketplace"],
            normalized["content_language"],
            normalized["product_type"],
            normalized["browse_node"],
        ]
        if library != "all":
            sql += " AND t.library_kind = ?"
            parameters.append(library)
        sql += """
            ORDER BY
              CASE t.library_kind WHEN 'blank' THEN 0 ELSE 1 END,
              CASE t.sample_status
                WHEN 'report_verified' THEN 0
                WHEN 'user_confirmed' THEN 1
                ELSE 2
              END,
              COALESCE(t.download_time, '') DESC,
              t.relative_path
        """
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    blank_rows = [row for row in rows if row["library_kind"] == "blank"]
    sample_rows = [row for row in rows if row["library_kind"] == "sample"]
    if preferred_blank_entry_id is not None:
        selected = [row for row in blank_rows if row["id"] == preferred_blank_entry_id]
        if not selected:
            raise LibraryError(
                "The selected blank entry does not match marketplace, language, Product Type, and node"
            )
        preferred_blank_row = selected[0]
        blank_rows = [preferred_blank_row, *[row for row in blank_rows if row["id"] != preferred_blank_entry_id]]
    else:
        preferred_blank_row = blank_rows[0] if blank_rows else None
    blank = [record_to_public(row) for row in blank_rows]
    sample = [record_to_public(row) for row in sample_rows]
    preferred_blank = blank[0] if blank else None
    blank_fields = (
        json.loads(preferred_blank_row["technical_fields_json"])
        if preferred_blank_row is not None
        else []
    )
    for row, item in zip(sample_rows, sample):
        sample_fields = json.loads(row["technical_fields_json"])
        populated_fields = json.loads(row["populated_fields_json"])
        if (
            preferred_blank
            and item["schema_fingerprint"]
            and item["schema_fingerprint"] == preferred_blank["schema_fingerprint"]
        ):
            compatibility = "exact_schema"
        elif blank_fields and sample_fields and set(blank_fields) == set(sample_fields):
            compatibility = "remappable_schema"
        elif populated_fields and set(populated_fields).issubset(set(blank_fields)):
            compatibility = "field_subset_compatible"
        else:
            compatibility = "incompatible_schema"
        item["schema_compatibility"] = compatibility
        item["schema_compatible_with_preferred_blank"] = compatibility != "incompatible_schema"
    sample.sort(key=lambda item: item["path"])
    sample.sort(key=lambda item: item.get("download_time") or "", reverse=True)
    sample.sort(key=lambda item: item.get("upload_time") or "", reverse=True)
    sample.sort(key=lambda item: len(item.get("browse_nodes") or []))
    sample.sort(
        key=lambda item: {
            "exact_schema": 0,
            "remappable_schema": 1,
            "field_subset_compatible": 2,
        }.get(
            item["schema_compatibility"], 3
        )
    )
    sample.sort(
        key=lambda item: {"report_verified": 0, "user_confirmed": 1}.get(
            item.get("sample_status"), 2
        )
    )
    usable_sample = [
        item for item in sample
        if item["sample_status"] in {"user_confirmed", "report_verified"}
        and item["schema_compatible_with_preferred_blank"]
    ]
    blank_schema_fingerprints = {
        row["schema_fingerprint"] for row in blank_rows if row["schema_fingerprint"]
    }
    if not blank:
        decision = {"state": "BLOCKED_NO_BLANK_TEMPLATE", "can_continue": False}
    elif len(blank_schema_fingerprints) > 1 and preferred_blank_entry_id is None:
        decision = {
            "state": "BLOCKED_AMBIGUOUS_BLANK_SCHEMA",
            "can_continue": False,
            "requires_blank_entry_selection": True,
        }
    elif not usable_sample:
        decision = {
            "state": "SAMPLE_MISSING_CONFIRM_MODE",
            "can_continue": True,
            "requires_explicit_no_sample_confirmation": True,
        }
    else:
        decision = {"state": "READY_WITH_SAMPLE", "can_continue": True}
    return {
        "query": {
            **normalized,
            "library": library,
            "preferred_blank_entry_id": preferred_blank_entry_id,
        },
        "strict_match": True,
        "blank_templates": blank,
        "preferred_blank_template": preferred_blank,
        "sample_templates": sample,
        "usable_sample_templates": usable_sample,
        "counts": {"blank": len(blank), "sample": len(sample), "total": len(rows)},
        "decision": decision,
    }


def resolve_sample_path(project_root: Path, raw_path: str) -> tuple[Path, str]:
    project_root = project_root.resolve()
    sample_root = (project_root / LIBRARY_DIRS["sample"]).resolve()
    supplied = Path(raw_path).expanduser()
    candidates = [supplied] if supplied.is_absolute() else [project_root / supplied, sample_root / supplied]
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(sample_root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved, resolved.relative_to(project_root).as_posix()
    raise LibraryError(f"Sample path is not a file inside {sample_root}: {raw_path}")


def set_sample_status(
    project_root: Path,
    raw_path: str,
    status: str,
    *,
    report_path: str | None = None,
    note: str | None = None,
    amazon_batch_id: str | None = None,
    upload_time: str | None = None,
) -> dict[str, Any]:
    db_path = project_root / DB_RELATIVE_PATH
    if not db_path.exists():
        raise LibraryError(f"Template index does not exist; run scan first: {db_path}")
    sample_path, relative_path = resolve_sample_path(project_root, raw_path)
    evidence_path: str | None = None
    if report_path:
        evidence = validate_processing_report_evidence(Path(report_path))
        evidence_path = str(evidence)
    if status == "report_verified" and evidence_path is None:
        raise LibraryError("report_verified requires --report with an Amazon processing report")
    connection = connect_database(project_root)
    try:
        row = connection.execute(
            "SELECT * FROM templates WHERE library_kind = 'sample' AND relative_path = ?",
            (relative_path,),
        ).fetchone()
        if row is None:
            raise LibraryError(f"Sample is not indexed; run scan first: {relative_path}")
        current_hash = sha256_file(sample_path)
        if current_hash != row["sha256"]:
            raise LibraryError(f"Sample changed after the last scan; run scan again: {relative_path}")
        now = utc_now()
        updated_at = None if status == "unverified" else now
        cursor = connection.execute(
            "UPDATE templates SET sample_status = ?, sample_status_updated_at = ?, "
            "sample_evidence_path = ?, sample_note = ?, amazon_batch_id = ?, upload_time = ? "
            "WHERE library_kind = 'sample' AND sha256 = ?",
            (status, updated_at, evidence_path, note, amazon_batch_id, upload_time, current_hash),
        )
        connection.commit()
        updated = connection.execute(
            "SELECT * FROM templates WHERE library_kind = 'sample' AND relative_path = ?",
            (relative_path,),
        ).fetchone()
    finally:
        connection.close()
    return {
        "updated": cursor.rowcount,
        "status": status,
        "sample": record_to_public(updated),
    }


def register_sample(
    project_root: Path,
    source: Path,
    status: str,
    destination_name: str | None,
    **verification: Any,
) -> dict[str, Any]:
    registration = register_workbook(project_root, source, "sample", destination_name)
    destination = Path(registration["registered"])
    status_result = set_sample_status(
        project_root,
        str(destination),
        status,
        report_path=verification.get("report_path"),
        note=verification.get("note"),
        amazon_batch_id=verification.get("amazon_batch_id"),
        upload_time=verification.get("upload_time"),
    )
    return {**registration, "verification": status_result}


def _indexed_entry_by_hash(
    project_root: Path, library_kind: str, digest: str
) -> dict[str, Any] | None:
    connection = connect_database(project_root)
    try:
        row = connection.execute(
            "SELECT * FROM templates WHERE library_kind = ? AND sha256 = ? "
            "ORDER BY relative_path LIMIT 1",
            (library_kind, digest),
        ).fetchone()
    finally:
        connection.close()
    return record_to_public(row) if row is not None else None


def _destination_for_registration(
    library_root: Path, source: Path, destination_name: str | None
) -> Path:
    requested = destination_name or source.name
    if Path(requested).name != requested:
        raise LibraryError("destination name must be a filename, not a path")
    if Path(requested).suffix.casefold() != source.suffix.casefold():
        raise LibraryError("destination filename extension must match the source workbook")
    destination = library_root / requested
    if not destination.exists():
        return destination
    if destination_name:
        raise LibraryError(f"Destination already exists; choose a different name: {destination}")
    for counter in range(2, 10000):
        candidate = library_root / f"{source.stem}-{counter}{source.suffix}"
        if not candidate.exists():
            return candidate
    raise LibraryError("Could not allocate a non-overwriting destination filename")


def register_workbook(
    project_root: Path,
    source: Path,
    library_kind: str,
    destination_name: str | None = None,
) -> dict[str, Any]:
    if library_kind not in LIBRARY_DIRS:
        raise LibraryError(f"Unsupported library kind: {library_kind}")
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() not in SUPPORTED_SUFFIXES:
        raise LibraryError(f"Source must be an existing .xlsx/.xlsm file: {source}")
    try:
        metadata = parse_workbook(source)
    except (BadZipFile, ET.ParseError, UnicodeDecodeError, ValueError, KeyError, IndexError) as exc:
        raise LibraryError(f"Workbook cannot be admitted: {type(exc).__name__}: {exc}") from exc
    if library_kind == "blank" and metadata["populated_fields"]:
        raise LibraryError("Blank template admission failed: populated product data fields were found")
    if library_kind == "sample" and not metadata["populated_sku_rows"]:
        raise LibraryError("Sample admission failed: no populated SKU data rows were found")

    project_root = project_root.expanduser().resolve()
    library_root = project_root / LIBRARY_DIRS[library_kind]
    library_root.mkdir(parents=True, exist_ok=True)
    scan_project(project_root)
    digest = sha256_file(source)
    existing = _indexed_entry_by_hash(project_root, library_kind, digest)
    if existing is not None:
        return {
            "registered": str((project_root / existing["path"]).resolve()),
            "entry": existing,
            "duplicate": True,
        }

    destination = _destination_for_registration(library_root, source, destination_name)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".template-admission-", suffix=source.suffix, dir=library_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != digest:
            raise LibraryError("Template copy hash mismatch")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    scan_project(project_root)
    indexed = _indexed_entry_by_hash(project_root, library_kind, digest)
    if indexed is None or indexed["parse_status"] != "ok":
        destination.unlink(missing_ok=True)
        scan_project(project_root)
        raise LibraryError("Template admission failed during index verification")
    return {
        "registered": str(destination.resolve()),
        "entry": indexed,
        "duplicate": False,
    }


def register_blank(
    project_root: Path, source: Path, destination_name: str | None = None
) -> dict[str, Any]:
    return register_workbook(project_root, source, "blank", destination_name)


def json_print(value: Any, *, stream: Any = sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), file=stream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project containing 空白模板库 and 样板模板库 (default: current directory)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="Scan both libraries and refresh the SQLite index")
    commands.add_parser("rescan", help="Alias for scan; rebuild the current library index")

    query = commands.add_parser("query", help="Strictly match indexed templates")
    query.add_argument("--marketplace", required=True, help="Marketplace ID, e.g. ATVPDKIKX0DER")
    query.add_argument("--content-language", required=True, help="Content language, e.g. en_US")
    query.add_argument("--product-type", required=True, help="Amazon Product Type, e.g. SCULPTURE")
    query.add_argument("--browse-node", required=True, help="Exact browse classification key")
    query.add_argument("--library", choices=("all", "blank", "sample"), default="all")
    query.add_argument(
        "--blank-entry-id",
        type=int,
        help="Explicitly select one matching blank entry when candidates have different schemas",
    )

    set_status = commands.add_parser(
        "set-sample-status",
        help="Set verification status for an indexed sample (status follows identical content hashes)",
    )
    set_status.add_argument("path", help="Absolute path, project-relative path, or path below 样板模板库")
    set_status.add_argument("status", choices=SAMPLE_STATUSES)
    set_status.add_argument("--report", help="Amazon processing report; required for report_verified")
    set_status.add_argument("--note")
    set_status.add_argument("--amazon-batch-id")
    set_status.add_argument("--upload-time")

    register_blank_parser = commands.add_parser(
        "register-blank", help="Validate and copy an Amazon-downloaded workbook into 空白模板库"
    )
    register_blank_parser.add_argument("--source", type=Path, required=True)
    register_blank_parser.add_argument("--destination-name")

    register = commands.add_parser("register-sample", help="Copy a validated output into 样板模板库")
    register.add_argument("--source", type=Path, required=True)
    register.add_argument("--status", choices=("user_confirmed", "report_verified"), required=True)
    register.add_argument("--destination-name")
    register.add_argument("--report", help="Amazon processing report; required for report_verified")
    register.add_argument("--note")
    register.add_argument("--amazon-batch-id")
    register.add_argument("--upload-time")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    if not project_root.is_dir():
        json_print({"error": f"Project root is not a directory: {project_root}"}, stream=sys.stderr)
        return 2
    try:
        if args.command in {"scan", "rescan"}:
            result = scan_project(project_root)
        elif args.command == "query":
            result = query_project(
                project_root,
                args.marketplace,
                args.content_language,
                args.product_type,
                args.browse_node,
                args.library,
                args.blank_entry_id,
            )
        elif args.command == "set-sample-status":
            result = set_sample_status(
                project_root,
                args.path,
                args.status,
                report_path=args.report,
                note=args.note,
                amazon_batch_id=args.amazon_batch_id,
                upload_time=args.upload_time,
            )
        elif args.command == "register-blank":
            result = register_blank(project_root, args.source, args.destination_name)
        else:
            result = register_sample(
                project_root,
                args.source,
                args.status,
                args.destination_name,
                report_path=args.report,
                note=args.note,
                amazon_batch_id=args.amazon_batch_id,
                upload_time=args.upload_time,
            )
    except (LibraryError, OSError, sqlite3.Error) as exc:
        json_print({"error": str(exc)}, stream=sys.stderr)
        return 2
    json_print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
