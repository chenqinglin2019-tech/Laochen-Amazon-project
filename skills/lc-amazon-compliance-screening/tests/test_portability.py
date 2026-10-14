"""Cross-platform I/O regressions; real OS runs are still required for release claims."""
import codecs
import csv
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import csc
import csc_table as ct
import csc_runtime as runtime
import build_distribution as packaging
from auth_support import auth_server, configure_local


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="筛查 空格 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", ["csc.py", *map(str, args)]), redirect_stdout(output), patch.object(csc, "require_auth"):
            with self.assertRaises(SystemExit) as exc:
                csc.main()
        return exc.exception.code, json.loads(output.getvalue())

    def workbook(self):
        try:
            excel = runtime.require_excel()
        except ValueError as exc:
            self.skipTest(str(exc))
        source = self.root / "含 空格 原表.xlsx"
        wb = excel.Workbook()
        ws = wb.active
        ws.title = "商品"
        ws.append(["标题", "站点", "公式", "链接"])
        ws.append(["空分装瓶", "US", "=1+2", "网页"])
        ws["D2"].hyperlink = "https://example.com/"
        ws["A2"].font = excel.styles.Font(bold=True, color="FF0000")
        wb.create_sheet("原有附表")["A1"] = "必须保留"
        wb.save(source)
        wb.close()
        return excel, source

    def test_json_encodings(self):
        expected = {"title": "面霜", "bullets": ["中文🙂"]}
        for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-be"):
            with self.subTest(encoding=enc):
                data = json.dumps(expected, ensure_ascii=False).encode(enc)
                if enc == "utf-16-be":
                    data = codecs.BOM_UTF16_BE + data
                path = self.root / "资料.json"
                path.write_bytes(data)
                self.assertEqual(csc.read_json(path), expected)

    def test_csv_tsv_encodings_and_invalid(self):
        for enc in ("utf-8", "utf-8-sig", "utf-16", "gb18030"):
            with self.subTest(encoding=enc):
                path = self.root / "商品.tsv"
                path.write_bytes("标题\t亮点\r\n面霜\t膏状\r\n".encode(enc))
                self.assertEqual(ct.read_table(path)[2], [["标题", "亮点"], ["面霜", "膏状"]])
        path.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "编码"):
            ct.read_table(path)

    def test_cli_utf8_pipe_and_arbitrary_cwd(self):
        skill = self.root / "skill"
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns("config.local.json", "__pycache__"))
        with auth_server() as state:
            env = configure_local(skill, state)
            proc = subprocess.run([sys.executable, "-B", str(skill / "scripts/csc.py"), "families"],
                                  cwd=self.root, env={**env, "PYTHONIOENCODING": "cp1252"}, capture_output=True)
            self.assertEqual(len(state["requests"]), 1)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        self.assertIn("families", json.loads(proc.stdout.decode("utf-8")))

    def test_csv_output_bom_newlines_and_windows_translation(self):
        text = csc.ce.render_csv({"sites": []})
        target = self.root / "报告.csv"
        runtime.write_csv(target, text)
        raw = target.read_bytes()
        self.assertTrue(raw.startswith(codecs.BOM_UTF8))
        self.assertEqual(raw.count(codecs.BOM_UTF8), 1)
        self.assertNotIn(b"\r\r\n", raw)
        self.assertEqual(len(list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))), 1)
        # Emulate Windows default newline translation, even when this test runs on macOS.
        buffers = []
        class KeepOpen(io.BytesIO):
            def close(self):
                pass
        def windows_open(path, mode, encoding, newline=None):
            buf = KeepOpen()
            buffers.append(buf)
            return io.TextIOWrapper(buf, encoding=encoding, newline="\r\n" if newline is None else newline)
        with patch("builtins.open", side_effect=windows_open):
            runtime.write_csv(target, text)
        self.assertNotIn(b"\r\r\n", buffers[0].getvalue())

    def test_missing_excel_no_lossy_output(self):
        target = self.root / "结果.xlsx"
        target.write_bytes(b"existing-output")
        with patch.dict(sys.modules, {"openpyxl": None}):
            with self.assertRaisesRegex(ValueError, "openpyxl"):
                ct.read_table(self.root / "source.xlsx")
            with self.assertRaisesRegex(ValueError, "openpyxl"):
                ct.write_table("source.xlsx", "xlsx", "商品", 0, [], [], {}, [], target)
            code, result = self.cli("families")
            self.assertEqual(code, 0)
        self.assertEqual(target.read_bytes(), b"existing-output")

    def test_macro_and_legacy_input_rejected(self):
        for suffix in (".xlsm", ".xls"):
            with self.assertRaisesRegex(ValueError, "另存为"):
                ct.read_table(self.root / ("商品" + suffix))

    def test_excel_keeps_other_sheets_formulas_styles_hyperlinks(self):
        excel, source = self.workbook()
        kind, sheet, rows = ct.read_table(source)
        target = self.root / "结果.xlsx"
        ct.write_table(source, kind, sheet, 0, rows, ["判定站点", "禁限售标记", "原因"],
                       {1: ["美国", "未发现限制", "原样"]}, [("通用义务", [["说明"]], [20])], target)
        wb = excel.load_workbook(target)
        try:
            self.assertEqual(wb.sheetnames, ["商品", "原有附表", "通用义务"])
            self.assertEqual(wb["原有附表"]["A1"].value, "必须保留")
            self.assertEqual(wb["商品"]["C2"].value, "=1+2")
            self.assertEqual(wb["商品"]["D2"].hyperlink.target, "https://example.com/")
            self.assertTrue(wb["商品"]["A2"].font.bold)
            self.assertEqual(wb["商品"].max_column, 7)
        finally:
            wb.close()

    def test_atomic_replace_failure_keeps_existing_output(self):
        source = self.root / "商品.csv"
        source.write_text("标题,站点\n空瓶,US\n", encoding="utf-8")
        target = self.root / "结果.csv"
        target.write_bytes(b"existing-output")
        with patch.object(Path, "replace", side_effect=PermissionError(13, "locked", str(target))):
            code, result = self.cli("table", "--input", source, "--out", target, "--fetch", "never")
        self.assertEqual(code, 2)
        self.assertIn("关闭 Excel", result["error"])
        self.assertEqual(target.read_bytes(), b"existing-output")
        self.assertFalse(list(self.root.glob(".csc-*")))

    def test_unwritable_directory_error(self):
        with patch.object(csc, "_main", side_effect=PermissionError(13, "denied", str(self.root))):
            code, result = self.cli("families")
        self.assertEqual(code, 2)
        self.assertIn("可写输出位置", result["error"])

    def test_tsv_output_is_tab_delimited(self):
        source = self.root / "商品.tsv"
        source.write_text("标题\t站点\n空瓶\tUS\n", encoding="utf-8")
        target = self.root / "结果.tsv"
        code, result = self.cli("table", "--input", source, "--out", target, "--fetch", "never")
        self.assertEqual(code, 0, result)
        self.assertEqual(len(ct.read_table(target)[2][0]), 5)

    def test_manifest_and_doctor(self):
        manifest, count = runtime.verify_manifest(ROOT)
        self.assertEqual(count, len(manifest["files"]))
        code, result = self.cli("doctor")
        self.assertEqual(code, 0, result)
        self.assertTrue(result["checks"]["distribution"]["valid"])
        with patch.dict(sys.modules, {"openpyxl": None}):
            code, result = self.cli("doctor", "--require-excel")
        self.assertEqual(code, 2)
        self.assertFalse(result["checks"]["excel"]["available"])

    def test_manifest_rejects_bad_paths_and_mismatch(self):
        template = {"schema": "SKILL-DISTRIBUTION/1.0", "package_name": "lc-amazon-compliance-screening"}
        for malformed in ([], {**template, "files": [None]}, {**template, "files": [{"path": None}]}):
            with self.assertRaises(ValueError):
                list(runtime.manifest_entries(self.root, malformed))
        for name in ("../outside", "C:/outside", "/outside", "a\\b", "__pycache__/x.pyc"):
            with self.assertRaises(ValueError):
                list(runtime.manifest_entries(self.root, {**template, "files": [{"path": name}]}))
        (self.root / "x.py").write_text("changed", encoding="utf-8")
        (self.root / "DISTRIBUTION-MANIFEST.json").write_text(json.dumps({**template, "files": [
            {"path": "x.py", "bytes": 0, "sha256": "wrong"}]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            runtime.verify_manifest(self.root)

    def test_zip_whitelist_and_extracted_quick_and_table(self):
        import zipfile
        result = packaging.build(self.root / "发行.zip")
        manifest, _ = runtime.verify_manifest(ROOT)
        expected = {manifest["package_name"] + "/" + x["path"] for x in manifest["files"]}
        expected.add(manifest["package_name"] + "/DISTRIBUTION-MANIFEST.json")
        with zipfile.ZipFile(result["zip"]) as z:
            self.assertEqual(set(z.namelist()), expected)
            for entry in z.infolist():
                if "/tools/bin/" in entry.filename and not entry.filename.endswith(".exe"):
                    self.assertEqual((entry.external_attr >> 16) & 0o777, 0o755)
            z.extractall(self.root / "解压 空格")
        script = self.root / "解压 空格" / manifest["package_name"] / "scripts/csc.py"
        state = self.enter_auth_server()
        env = configure_local(script.parents[1], state)
        cat = {"families": ["cosmetics"], "primary_form": "paste_gel", "form_evidence": "标题：面霜"}
        category = self.root / "分类.json"
        category.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8-sig")
        for args in (["doctor"], ["quick", "--title", "面霜", "--sites", "US", "--category", str(category),
                                  "--out", str(self.root / "解压后报告")]):
            proc = subprocess.run([sys.executable, "-B", str(script), *args], cwd=self.root, env=env, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8"))
            self.assertTrue(json.loads(proc.stdout.decode("utf-8"))["ok"])
        source = self.root / "表.csv"
        source.write_text("标题,站点\n面霜,US\n", encoding="utf-8")
        category.write_text(json.dumps({"2": cat}, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([sys.executable, "-B", str(script), "table", "--input", str(source),
                               "--categories", str(category), "--out", str(self.root / "结果.csv"), "--fetch", "never"],
                              cwd=self.root, env=env, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))
        self.assertEqual(json.loads(proc.stdout.decode("utf-8"))["marks"], {"物流运输强限制": 1})
        self.assertEqual(len(state["requests"]), 2)

        # Run every formal command through the extracted package and real gate.
        # Use unresolved dispositions so this synthetic fixture makes no legal claim.
        def cli(*args, expected=0):
            proc = subprocess.run([sys.executable, "-B", str(script), *map(str, args)], cwd=self.root,
                                  env=env, capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, expected, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8"))
            return json.loads(proc.stdout.decode("utf-8"))

        product = self.root / "商品.json"
        product.write_text(json.dumps({"title": "Hair Clay", "bullets": ["膏状发泥"]}), encoding="utf-8")
        task = self.root / "完整排查"
        cli("init", "--input", product, "--sites", "US", "--task", task)
        self.assertEqual(cli("status", "--task", task)["step"], "initialized")
        profile = runtime.read_json(task / "profile.template.json")
        profile["families"] = [{"id": "cosmetics", "evidence": ["title"]}]
        profile["attributes"]["substance.primary_form"] = {
            "value": "paste_gel", "status": "provided", "evidence": ["bullet:1"]}
        profile_path = self.root / "画像.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        cli("match", "--task", task, "--profile", profile_path)
        review = runtime.read_json(task / "review.template.json")
        self.assertTrue(review["dispositions"])
        for item in review["dispositions"]:
            item.update(decision="needs_info", codes=[], evidence=[],
                        reason_zh="测试资料缺少规则所需信息", question_zh="请补齐适用条件和证明资料")
        review["sites"][0].update(confidence="low", confidence_reason_zh="仅有合成测试资料，信息不完整")
        review_path = self.root / "处置.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        cli("review", "--task", task, "--file", review_path)
        self.assertEqual(cli("status", "--task", task)["step"], "reviewed")

        before = {p.relative_to(task): p.read_bytes() for p in task.rglob("*") if p.is_file()}
        state.update(allowed=False, reason="permission_disabled")
        self.assertEqual(cli("render", "--task", task, expected=1)["reason"], "permission_disabled")
        self.assertEqual(before, {p.relative_to(task): p.read_bytes() for p in task.rglob("*") if p.is_file()})
        state.update(allowed=True, reason="permission_enabled")
        cli("render", "--task", task)
        self.assertEqual(cli("status", "--task", task)["step"], "rendered")
        self.assertEqual((task / "assessment.json").read_bytes(), before[Path("assessment.json")])
        for name in ("report_data.json", "report.html", "report.md", "findings.csv"):
            self.assertGreater((task / name).stat().st_size, 0)
        self.assertEqual(len(state["requests"]), 10)

    def enter_auth_server(self):
        context = auth_server()
        state = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return state


if __name__ == "__main__":
    unittest.main()
