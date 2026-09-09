#!/usr/bin/env python3
"""Import user XLSX/CSV/TSV keyword tables locally without filtering or a row cap.

Python 3.9+ standard library. No CLI, backend, configuration, formula execution,
or credentials are needed. The imported snapshot feeds keyword_quality.py.
"""
import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import posixpath
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

SPEC = importlib.util.spec_from_file_location("import_keyword_quality", Path(__file__).with_name("keyword_quality.py"))
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)
SITES = ("US", "UK", "CA", "IN", "JP", "DE", "FR", "IT", "ES")
ALIASES = {
    "keyword": ("关键词", "搜索词", "搜索关键词", "关键词原文", "keyword", "keywords", "search term", "search terms"),
    "monthly_searches": ("月搜索量", "月搜索次数", "搜索量", "monthly searches", "monthly search volume", "search volume", "searches", "monthly_searches"),
    "keyword_translation": ("关键词翻译", "关键词中文翻译", "中文翻译", "关键词(中文)", "翻译", "keyword translation", "keyword_translation", "translation"),
    "traffic_percentage": ("流量占比", "流量占比(%)", "流量百分比", "traffic percentage", "traffic share", "traffic_percentage"),
    "flow_type": ("流量词类型", "流量类型", "词类型", "flow type", "flow_type", "traffic type"),
}


def header_key(value):
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[\s_-]+", "", value)


def cell(value, kind="text", formula=None, percentage=False):
    return {"value": value, "cell_type": kind, "formula": formula, "percentage_format": percentage}


def xlsx_sheets(data):
    """Read stored OOXML cells, including hidden sheets/rows and cached formulas."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        def xml(name):
            return ET.fromstring(archive.read(name))
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(node.itertext()) if not node.findall(".//{*}t") else
                      "".join(t.text or "" for t in node.findall(".//{*}t"))
                      for node in xml("xl/sharedStrings.xml").findall("{*}si")]
        formats, styles = {}, []
        if "xl/styles.xml" in archive.namelist():
            root = xml("xl/styles.xml")
            formats = {int(n.attrib["numFmtId"]): n.attrib.get("formatCode", "") for n in root.findall("{*}numFmts/{*}numFmt")}
            styles = [int(n.attrib.get("numFmtId", "0")) for n in root.findall("{*}cellXfs/{*}xf")]
        relations = {r.attrib["Id"]: r.attrib for r in xml("xl/_rels/workbook.xml.rels")}
        output = []
        for sheet in xml("xl/workbook.xml").findall("{*}sheets/{*}sheet"):
            relation_id = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), None)
            relation = relations.get(relation_id, {})
            if relation.get("TargetMode") == "External":
                raise ValueError("工作表不能来自外部链接")
            target = relation.get("Target", "")
            if not target:
                raise ValueError("工作表缺少内部文件关联")
            target = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
            if not target.startswith("xl/"):
                raise ValueError("工作表路径超出工作簿")
            rows, seen_rows = [], set()
            for fallback_row, row in enumerate(xml(target).findall("{*}sheetData/{*}row"), 1):
                row_number = int(row.attrib.get("r", fallback_row))
                if row_number < 1 or row_number in seen_rows:
                    raise ValueError("工作表行号重复或无效")
                seen_rows.add(row_number)
                values = {}
                for fallback_column, node in enumerate(row.findall("{*}c")):
                    ref = node.attrib.get("r")
                    if ref:
                        match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", ref)
                        if not match or int(match[2]) != row_number:
                            raise ValueError("单元格坐标无效")
                        column = 0
                        for letter in match[1]:
                            column = column * 26 + ord(letter) - ord("A") + 1
                        column -= 1
                    else:
                        column = fallback_column
                    if column in values:
                        raise ValueError("工作表单元格坐标重复")
                    kind = node.attrib.get("t", "n")
                    raw = node.findtext("{*}v")
                    if kind == "s":
                        index = int(raw)
                        if not 0 <= index < len(shared):
                            raise ValueError("共享字符串索引无效")
                        raw = shared[index]
                    elif kind == "inlineStr":
                        raw = "".join(t.text or "" for t in node.findall("{*}is//{*}t"))
                    style_id = int(node.attrib.get("s", "0"))
                    number_format = styles[style_id] if style_id < len(styles) else 0
                    values[column] = cell(raw, kind, node.findtext("{*}f"),
                                          number_format in (9, 10) or "%" in formats.get(number_format, ""))
                rows.append((row_number, values))
            output.append((sheet.attrib["name"], sheet.attrib.get("state", "visible"), rows))
        return output


def delimited_sheets(data, suffix, encoding):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        text = data.decode(encoding)
    if suffix == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    rows = []
    start_line = 1
    for values in reader:
        rows.append((start_line, {i: cell(value) for i, value in enumerate(values)}))
        start_line = reader.line_num + 1
    return [("CSV" if suffix == ".csv" else "TSV", "visible", rows)]


def resolve_header(rows, keyword_column, searches_column):
    aliases = {key: {header_key(value) for value in names} for key, names in ALIASES.items()}
    if keyword_column:
        aliases["keyword"] = {header_key(keyword_column)}
    if searches_column:
        aliases["monthly_searches"] = {header_key(searches_column)}
    # Search the whole worksheet; a title or long note section is not keyword data.
    for position, (row_number, values) in enumerate(rows):
        mapping = {key: [col for col, value in values.items() if header_key(value["value"]) in names]
                   for key, names in aliases.items()}
        if not mapping["keyword"]:
            continue
        for key, matches in mapping.items():
            if len(matches) > 1:
                raise ValueError("第 %d 行的 %s 列存在歧义；用列名参数明确映射" % (row_number, key))
        if searches_column and not mapping["monthly_searches"]:
            raise ValueError("找不到指定的月搜索量列")
        return position, {key: matches[0] for key, matches in mapping.items() if matches}, values
    return None


def metric(value, *, percentage=False):
    raw = value.get("value")
    if raw is None or not str(raw).strip() or str(raw).strip().casefold() in ("-", "--", "—", "n/a", "na", "null", "未知"):
        return None, "formula_without_cache" if value.get("formula") is not None else None
    if value.get("cell_type") in ("e", "b", "d"):
        return None, "invalid_metric"
    number = str(raw).strip()
    explicit_percent = number.endswith("%")
    if explicit_percent:
        number = number[:-1].strip()
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", number):
        number = number.replace(",", "")
    if "," in number or (explicit_percent and not percentage):
        return None, "ambiguous_metric"
    try:
        parsed = Decimal(number)
        if not parsed.is_finite() or parsed < 0:
            return None, "invalid_metric"
        if percentage:
            if value.get("percentage_format") and not explicit_percent:
                parsed *= 100
            if parsed > 100:
                return None, "invalid_metric"
            return float(parsed), None
        if parsed != parsed.to_integral_value():
            return None, "ambiguous_metric"
        return int(parsed), None
    except InvalidOperation:
        return None, "invalid_metric"


def build_import(paths, site, *, sheets=None, keyword_column=None, searches_column=None, encoding="utf-8-sig"):
    if site not in SITES or not paths:
        raise ValueError("需要明确站点和至少一份用户关键词表格")
    resolved = [Path(p).resolve() for p in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("同一个输入文件重复提供")
    keywords, sources, issues = [], [], []
    for file_index, path in enumerate(resolved, 1):
        if path.suffix.lower() not in (".xlsx", ".csv", ".tsv"):
            raise ValueError("仅支持 XLSX/CSV/TSV；旧 XLS 或其他格式请先另存为 XLSX")
        data = path.read_bytes()
        file_id = "file-%03d" % file_index
        source = {"file_id": file_id, "filename": path.name, "path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "sheets": []}
        try:
            tables = xlsx_sheets(data) if path.suffix.lower() == ".xlsx" else delimited_sheets(data, path.suffix.lower(), encoding)
            if sheets and not set(sheets) <= {name for name, _, _ in tables}:
                raise ValueError("指定工作表不存在；多文件采用相同工作表筛选，请核对名称")
            for name, state, rows in tables:
                counts = {"name": name, "visibility": state, "imported_rows": 0, "blank_keyword_rows": [], "repeated_header_rows": []}
                source["sheets"].append(counts)
                if sheets and name not in sheets:
                    counts["status"] = "not_selected"
                    continue
                nonempty = any(value.get("value") not in (None, "") or value.get("formula") is not None for _, values in rows for value in values.values())
                if not nonempty:
                    counts["status"] = "empty"
                    continue
                found = resolve_header(rows, keyword_column, searches_column)
                if found is None:
                    raise ValueError("工作表 %s 找不到关键词表头；指定 --keyword-column 或 --sheet，不能跳过不明数据" % name)
                header_position, mapping, headers = found
                counts.update(status="imported", header_row=rows[header_position][0],
                              columns={key: {"column": col + 1, "header": headers[col]["value"]} for key, col in mapping.items()},
                              preamble_rows=[n for n, _ in rows[:header_position]])
                for row_number, values in rows[header_position + 1:]:
                    original = values.get(mapping["keyword"], cell(None))
                    text = original["value"]
                    if original.get("cell_type") == "e" or (original.get("formula") is not None and text is None):
                        raise ValueError("工作表 %s 第 %d 行关键词为错误值或公式缺缓存，需在表格软件中保存结果" % (name, row_number))
                    if text is None or not str(text).strip():
                        counts["blank_keyword_rows"].append(row_number)
                        continue
                    # A one-column query literally named "keyword" is still data.
                    if len(mapping) > 1 and all(header_key(values.get(col, cell(None))["value"]) == header_key(headers[col]["value"]) for col in mapping.values()):
                        counts["repeated_header_rows"].append(row_number)
                        continue
                    location = {"file_id": file_id, "sheet": name, "row": row_number}
                    record = {"keyword": str(text), "source": location,
                              "raw_cells": [{"column": col + 1, "header": headers.get(col, cell(None))["value"], **value} for col, value in sorted(values.items())]}
                    for key in ("monthly_searches", "traffic_percentage", "keyword_translation", "flow_type"):
                        value = values.get(mapping.get(key), cell(None))
                        if key in ("monthly_searches", "traffic_percentage"):
                            record[key], warning = metric(value, percentage=key == "traffic_percentage")
                            if warning:
                                issues.append({"code": warning, "field": key, **location})
                        else:
                            record[key] = value["value"]
                    keywords.append(record)
                    counts["imported_rows"] += 1
        except (ValueError, KeyError, IndexError, TypeError, ET.ParseError, zipfile.BadZipFile, csv.Error) as exc:
            raise ValueError("文件 %s 导入失败：%s" % (path.name, str(exc))) from None
        sources.append(source)
    if not keywords:
        raise ValueError("所选表格没有有效关键词行")
    groups = {}
    for index, record in enumerate(keywords):
        groups.setdefault(quality.norm(record["keyword"]), []).append(index)
    metrics = []
    for normalized, positions in groups.items():
        item = {"keyword": keywords[positions[0]]["keyword"], "source_positions": positions}
        for field in ("monthly_searches", "traffic_percentage"):
            distinct = {keywords[index][field] for index in positions if keywords[index][field] is not None}
            item[field] = next(iter(distinct)) if len(distinct) == 1 else None
            if len(distinct) > 1:
                issues.append({"code": "metric_conflict", "field": field, "source_positions": positions})
        metrics.append(item)
    return {"source_kind": "user_spreadsheets", "import_schema_version": "1.0", "site": site,
            "source_files": sources, "keywords": keywords, "raw": {"keyword_data": metrics}, "import_issues": issues,
            "import_counts": {"files": len(sources), "raw_records": len(keywords), "unique": len(groups), "duplicates": len(keywords) - len(groups)},
            "import_policy": {"semantic_filtering": False, "row_limit": None, "deduplicate_input": False, "conflicting_metrics": "unknown"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", nargs="+", required=True)
    parser.add_argument("--site", choices=SITES, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--sheet", action="append", help="Explicit worksheet names, if only selected sheets contain keywords")
    parser.add_argument("--keyword-column", help="Exact keyword column label when automatic mapping is ambiguous")
    parser.add_argument("--searches-column", help="Exact monthly search volume column label")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV/TSV encoding; UTF-16 BOM is detected automatically")
    args = parser.parse_args(argv)
    try:
        args.run_dir.mkdir(parents=True, exist_ok=True)
        destination = args.run_dir / quality.RAW
        if destination.exists():
            raise ValueError("02_kw_raw.json 已存在；使用新任务目录，避免覆盖已审查词表")
        profile_path = args.run_dir / quality.PROFILE
        if profile_path.exists():
            profile = quality.read_json(profile_path)
            if not isinstance(profile, dict) or profile.get("site") != args.site:
                raise ValueError("产品画像必须是对象，且导入站点须与画像一致")
        data = build_import(args.files, args.site, sheets=args.sheet, keyword_column=args.keyword_column,
                            searches_column=args.searches_column, encoding=args.encoding)
        quality.atomic_write(destination, data)
        print(json.dumps({"status": "imported", "counts": data["import_counts"], "issues": data["import_issues"]}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, LookupError) as exc:
        print("关键词导入失败：%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
