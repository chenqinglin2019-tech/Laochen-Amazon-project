"""Lossless local keyword ingestion and end-to-end integration; synthetic data only."""
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from keyword_fixtures import ROOT, keywords as k, make_run, classify, write
from test_keyword_workflow import completed_run
from test_listing_quality import quality
from test_render_listing import renderer, ScriptCollector

SPEC = importlib.util.spec_from_file_location("keyword_import_tests", ROOT / "scripts/import_keywords.py")
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


def workbook(path, sheets, shared=()):
    """Write a small real OOXML workbook without spreadsheet dependencies."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    book = ET.Element("workbook", {"xmlns": ns, "xmlns:r": rel})
    refs = ET.SubElement(book, "sheets")
    relationships = ET.Element("Relationships", {"xmlns": package})
    with zipfile.ZipFile(path, "w") as archive:
        for index, (name, rows, hidden) in enumerate(sheets, 1):
            rid = "rId%d" % index
            ET.SubElement(refs, "sheet", {"name": name, "sheetId": str(index), "r:id": rid, "state": "hidden" if hidden else "visible"})
            ET.SubElement(relationships, "Relationship", {"Id": rid, "Type": rel + "/worksheet", "Target": "worksheets/sheet%d.xml" % index})
            sheet = ET.Element("worksheet", {"xmlns": ns})
            body = ET.SubElement(sheet, "sheetData")
            for number, row in enumerate(rows, 1):
                node = ET.SubElement(body, "row", {"r": str(number), "hidden": "1" if hidden else "0"})
                for column, value in enumerate(row):
                    if value is None:
                        continue
                    attrs = {"r": chr(ord("A") + column) + str(number)}
                    if isinstance(value, dict):
                        attrs.update(value.get("attrs", {}))
                        c = ET.SubElement(node, "c", attrs)
                        if "formula" in value:
                            ET.SubElement(c, "f").text = value["formula"]
                        if value.get("value") is not None:
                            ET.SubElement(c, "v").text = str(value["value"])
                    elif isinstance(value, (int, float)):
                        ET.SubElement(ET.SubElement(node, "c", attrs), "v").text = str(value)
                    else:
                        attrs["t"] = "inlineStr"
                        inline = ET.SubElement(ET.SubElement(node, "c", attrs), "is")
                        ET.SubElement(inline, "t").text = value
            archive.writestr("xl/worksheets/sheet%d.xml" % index, ET.tostring(sheet))
        archive.writestr("xl/workbook.xml", ET.tostring(book))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))
        archive.writestr("xl/styles.xml", '<styleSheet xmlns="%s"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="10"/></cellXfs></styleSheet>' % ns)
        strings = ET.Element("sst", {"xmlns": ns})
        for text in shared:
            # Rich strings in common spreadsheet exports.
            si = ET.SubElement(strings, "si")
            for part in (text[:2], text[2:]):
                ET.SubElement(ET.SubElement(si, "r"), "t").text = part
        archive.writestr("xl/sharedStrings.xml", ET.tostring(strings))


class KeywordImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="keyword import 中文 ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def table(self, rows, name="keywords.csv", encoding="utf-8-sig", delimiter=","):
        file = self.root / name
        with file.open("w", encoding=encoding, newline="") as handle:
            csv.writer(handle, delimiter=delimiter).writerows(rows)
        return file

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = importer.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_more_than_150_rows_unicode_zero_unknown_and_extra_columns_are_preserved(self):
        words = ["bathroom cat decor", "lightweight cat decor", "猫咪门角装饰", "décor porte", "猫の飾り"] + ["decor %d" % i for i in range(200)]
        path = self.table([["关键词", "月搜索量", "自定义指标"]] + [[word, 0 if i == 0 else "", "extra"] for i, word in enumerate(words)])
        data = importer.build_import([path], "US")
        self.assertEqual([r["keyword"] for r in data["keywords"]], words)
        self.assertEqual(data["import_counts"], dict(files=1, raw_records=205, unique=205, duplicates=0))
        self.assertEqual(data["keywords"][0]["monthly_searches"], 0)
        self.assertIsNone(data["keywords"][1]["monthly_searches"])
        self.assertEqual(data["keywords"][0]["raw_cells"][2]["value"], "extra")
        self.assertEqual(data["source_files"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(data["keywords"][-1]["source"]["row"], 206)
        self.assertIsNone(data["import_policy"]["row_limit"])

    def test_multiple_files_normalization_provenance_and_conflicting_metrics(self):
        example = json.loads((ROOT / "knowledge/keyword_import_examples.json").read_text())
        files = [self.table(item["rows"], item["filename"]) for item in example["input_tables"]]
        data = importer.build_import(files, "US")
        self.assertEqual({key: data["import_counts"][key] for key in example["expected_counts"]}, example["expected_counts"])
        for actual, expected in zip(data["raw"]["keyword_data"], example["expected_metrics"]):
            self.assertEqual(actual["keyword"], expected["keyword"])
            self.assertEqual(actual["monthly_searches"], expected["monthly_searches"])
        self.assertEqual(data["raw"]["keyword_data"][0]["source_positions"], [0, 4])
        self.assertEqual(data["keywords"][4]["source"], {"file_id": "file-002", "sheet": "CSV", "row": 2})
        self.assertEqual(data["import_issues"][0]["code"], "metric_conflict")

    def test_multi_sheet_hidden_rows_shared_strings_and_percent_format(self):
        path = self.root / "keywords.xlsx"
        workbook(path, [("表一", [["说明"], ["关键词", "月搜索量", "流量占比"],
                                     [{"attrs": {"t": "s"}, "value": 0}, 100, {"attrs": {"s": "1"}, "value": 0.125}]], False),
                        ("Hidden", [["Keyword", "Monthly Searches"], ["猫咪装饰", 0]], True)], shared=["black cat door corner"])
        data = importer.build_import([path], "US")
        self.assertEqual(len(data["keywords"]), 2)
        self.assertEqual(data["keywords"][0]["keyword"], "black cat door corner")
        self.assertEqual(data["keywords"][0]["traffic_percentage"], 12.5)
        self.assertEqual(data["keywords"][0]["source"]["row"], 3)
        self.assertEqual(data["source_files"][0]["sheets"][0]["preamble_rows"], [1])
        self.assertEqual(data["source_files"][0]["sheets"][1]["visibility"], "hidden")

    def test_header_ambiguity_fails_and_explicit_columns_resolve_it(self):
        path = self.table([["Keyword", "Search Term", "Monthly Searches", "Search Volume"], ["cat decor", "bird decor", 20, 40]])
        with self.assertRaisesRegex(ValueError, "歧义"):
            importer.build_import([path], "US")
        data = importer.build_import([path], "US", keyword_column="Search Term", searches_column="Search Volume")
        self.assertEqual(data["keywords"][0]["keyword"], "bird decor")
        self.assertEqual(data["keywords"][0]["monthly_searches"], 40)
        self.assertEqual(len(data["keywords"][0]["raw_cells"]), 4)

    def test_unknown_nonempty_sheet_requires_explicit_selection(self):
        path = self.root / "mixed.xlsx"
        workbook(path, [("Notes", [["报告说明"]], False), ("Words", [["Keyword"], ["cat decor"]], False)])
        with self.assertRaisesRegex(ValueError, "找不到关键词表头"):
            importer.build_import([path], "US")
        data = importer.build_import([path], "US", sheets=["Words"])
        self.assertEqual(data["source_files"][0]["sheets"][0]["status"], "not_selected")
        with self.assertRaisesRegex(ValueError, "不存在"):
            importer.build_import([path], "US", sheets=["Missing"])

    def test_blank_rows_and_repeated_headers_are_recorded_not_keyword_deletions(self):
        path = self.table([["Keyword", "Monthly Searches"], ["cat decor", 1], ["", ""], ["Keyword", "Monthly Searches"], ["bird decor", ""]])
        data = importer.build_import([path], "US")
        sheet = data["source_files"][0]["sheets"][0]
        self.assertEqual(sheet["blank_keyword_rows"], [3])
        self.assertEqual(sheet["repeated_header_rows"], [4])
        self.assertEqual(data["import_counts"]["raw_records"], 2)

    def test_missing_optional_metrics_and_whitespace_only_queries(self):
        path = self.table([["Keyword"], ["cat decor"], ["   "], ["..."], ["keyword"]])
        data = importer.build_import([path], "US")
        self.assertIsNone(data["keywords"][0]["monthly_searches"])
        self.assertEqual(data["keywords"][1]["keyword"], "...")  # Semantic unusable-query decision comes later.
        self.assertEqual(data["keywords"][2]["keyword"], "keyword")
        self.assertEqual(data["import_counts"]["raw_records"], 3)

    def test_cached_formula_is_read_and_missing_volume_cache_keeps_keyword(self):
        path = self.root / "formula.xlsx"
        workbook(path, [("Words", [["Keyword", "Monthly Searches"],
                                    ["cat decor", {"formula": "SUM(10,20)", "value": 30}],
                                    ["bird decor", {"formula": "SUM(A3)"}]], False)])
        data = importer.build_import([path], "US")
        self.assertEqual(data["keywords"][0]["monthly_searches"], 30)
        self.assertIsNone(data["keywords"][1]["monthly_searches"])
        self.assertEqual(data["import_issues"][0]["code"], "formula_without_cache")
        self.assertEqual(data["keywords"][0]["raw_cells"][1]["formula"], "SUM(10,20)")

    def test_error_or_missing_formula_cache_in_keyword_column_fails(self):
        for value in [{"formula": '"cat decor"'}, {"attrs": {"t": "e"}, "value": "#VALUE!"}]:
            path = self.root / "bad.xlsx"
            workbook(path, [("Words", [["Keyword"], [value]], False)])
            with self.assertRaisesRegex(ValueError, "关键词为错误值或公式缺缓存"):
                importer.build_import([path], "US")

    def test_unknown_invalid_numeric_formats_never_invent_traffic(self):
        path = self.table([["Keyword", "Monthly Searches", "Traffic Share"]] +
                          [["decor %d" % i, volume, share] for i, (volume, share) in enumerate([
                              ("1,234", "12.5%"), ("0", "0"), ("1,2", "200%"), ("2K", "?"),
                              ("-1", "-5%"), ("Infinity", "NaN"), ("1.5", ""), ("—", "")])])
        data = importer.build_import([path], "US")
        self.assertEqual([r["monthly_searches"] for r in data["keywords"]], [1234, 0, None, None, None, None, None, None])
        self.assertEqual([r["traffic_percentage"] for r in data["keywords"]][:3], [12.5, 0, None])
        self.assertEqual(len(data["keywords"]), 8)

    def test_tsv_utf16_gb18030_semicolon_and_multiline_cells(self):
        rows = [["Keyword", "Monthly Searches"], ["猫咪\n门角装饰", 10], ["cat decor", 20]]
        for suffix, encoding, delimiter in [(".tsv", "utf-16", "\t"), (".csv", "utf-8-sig", ";"), (".csv", "gb18030", ",")]:
            path = self.table(rows, "words" + suffix, encoding, delimiter)
            data = importer.build_import([path], "JP", encoding=encoding)
            self.assertEqual(data["keywords"][0]["keyword"], "猫咪\n门角装饰")
            self.assertEqual(data["keywords"][1]["source"]["row"], 4)

    def test_no_files_duplicates_empty_unknown_header_and_unsupported_format_fail(self):
        path = self.table([["Keyword"], ["cat decor"]])
        for files in ([], [path, path]):
            with self.assertRaises(ValueError):
                importer.build_import(files, "US")
        for rows in ([["Keyword"]], [["不明列"], ["cat decor"]]):
            path = self.table(rows)
            with self.assertRaises(ValueError):
                importer.build_import([path], "US")
        with self.assertRaisesRegex(ValueError, "XLSX"):
            importer.build_import([self.root / "legacy.xls"], "US")

    def test_command_refuses_overwrite_and_partial_import_has_no_output(self):
        run = self.root / "run"
        path = self.table([["Keyword"], ["cat decor"]])
        args = ["--files", str(path), "--site", "US", "--run-dir", str(run)]
        self.assertEqual(self.invoke(*args)[0], 0)
        snapshot = (run / k.RAW).read_bytes()
        self.assertEqual(self.invoke(*args)[0], 1)
        self.assertEqual((run / k.RAW).read_bytes(), snapshot)
        bad = self.table([["Unknown"], ["cat decor"]], "bad.csv")
        partial = self.root / "partial"
        self.assertEqual(self.invoke("--files", str(path), str(bad), "--site", "US", "--run-dir", str(partial))[0], 1)
        self.assertFalse((partial / k.RAW).exists())

    def test_profile_site_mismatch_and_malformed_profile_stop_import(self):
        path = self.table([["Keyword"], ["cat decor"]])
        for profile in ({"site": "DE"}, [], None):
            write(self.root, k.PROFILE, profile)
            self.assertEqual(self.invoke("--files", str(path), "--site", "US", "--run-dir", str(self.root))[0], 1)
            self.assertFalse((self.root / k.RAW).exists())

    def test_real_command_import_prepare_and_export_preserve_provenance_without_second_review(self):
        profile, _ = make_run(self.root)
        (self.root / k.RAW).unlink(); (self.root / k.DECISIONS).unlink()
        path = self.table([["Keyword", "Monthly Searches"], ["Black Cat Door Corner", ""], ["black cat door corner", 0], ["cat iron decor", ""]])
        result = subprocess.run([sys.executable, str(ROOT / "scripts/import_keywords.py"), "--files", str(path), "--site", "US", "--run-dir", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = k.prepare(self.root)
        self.assertIsNone(ledger["records"][0]["decision"])
        self.assertEqual(ledger["records"][0]["source_positions"], [0, 1])
        self.assertTrue(ledger["supplemental_terms"])  # Full core identity missing from input stays protected.
        for record in k.all_records(ledger):
            classify(record)
            if record["keyword"] == "cat iron decor":
                classify(record, "deferred", "unknown_fact", ["iron"])
                record["intent_group"] = "iron-material"
        write(self.root, k.DECISIONS, ledger)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(k.main(["export", "--run-dir", str(self.root)]), 0)
        tags = k.read_json(self.root / "04_kw_tagged.json")
        self.assertEqual(tags[0]["searches"], 0)
        self.assertEqual(len(k.read_json(self.root / "03_kw_pending.json")), 1)
        self.assertFalse((self.root / "03_keyword_review.json").exists())
        self.assertEqual(k.read_json(self.root / k.VALIDATION)["counts"]["duplicates"], 1)

    def test_imported_snapshot_reaches_same_three_files_and_full_acceptance(self):
        completed_run(self.root)
        check_args = [sys.executable, str(ROOT / "scripts/listing_quality.py"), "check"]
        for flag, name in [("profile", k.PROFILE), ("listing", "07_listing.json"), ("qa", "06_qa.json"),
                           ("review", "08_semantic_review.json"), ("backend", "08_backend_validation.json"), ("output", "08_validation.json")]:
            check_args += ["--" + flag, str(self.root / name)]
        self.assertEqual(subprocess.run(check_args, capture_output=True).returncode, 0)
        (self.root / k.RAW).unlink(); (self.root / k.DECISIONS).unlink()
        path = self.table([["Keyword", "Monthly Searches"], ["Pen Holder", ""], ["stationery organizer", 0], ["iron pen holder", ""], ["electronic pet flap", 2]])
        self.assertEqual(self.invoke("--files", str(path), "--site", "US", "--run-dir", str(self.root))[0], 0)
        ledger = k.prepare(self.root)
        for record in k.all_records(ledger):
            classify(record)
            record.update(query_intent="寻找笔筒", evidence="synthetic pen-holder identity", reason="合成产品资料支持文具收纳。", intent_group="pen-storage")
            if record["keyword"] in ("iron pen holder", "electronic pet flap"):
                decision, code = ("deferred", "unknown_fact") if record["keyword"].startswith("iron") else ("excluded", "product_mismatch")
                classify(record, decision, code)
                record.update(intent_group=record["keyword"], query_intent=record["keyword"], evidence="synthetic pen-holder identity", reason="核对完整对象，铁材质未知；电子宠物门与笔筒不符。")
        write(self.root, k.DECISIONS, ledger)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(k.main(["export", "--run-dir", str(self.root)]), 0)
        # A changed keyword snapshot invalidates the old final semantic review.
        self.assertEqual(renderer.build_report(self.root)[2], "incomplete")
        review = quality.make_review_template(self.root / k.PROFILE, self.root / "07_listing.json", self.root / "06_qa.json")
        for record in review["records"]:
            record.update(status="pass", evidence="Synthetic fixture reviewed against imported terms; no real product claims.")
        write(self.root, "08_semantic_review.json", review)
        checked = subprocess.run(check_args, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        md, page, status = renderer.build_report(self.root)
        self.assertEqual(status, "passed")
        parsed = ScriptCollector(); parsed.feed(page)
        self.assertEqual(json.loads(parsed.values["data-kw-raw"])["source_kind"], "user_spreadsheets")
        self.assertIn("关键词表格导入", page)
        self.assertNotIn("来源 ASIN", page)
        self.assertEqual(sum(tag == "section" and attrs.get("class") == "chapter" for tag, attrs in parsed.tags), 7)
        self.assertIn("【MATERIAL】", md)
        process = subprocess.run([sys.executable, str(ROOT / "scripts/render_listing.py"), "--run-dir", str(self.root)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        for name in ("07_listing.md", "07_listing.json", "report.html"):
            self.assertTrue((self.root / name).is_file())


if __name__ == "__main__":
    unittest.main()
