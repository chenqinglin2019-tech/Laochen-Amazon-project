"""Lock the user's current HTML format while data and scheduling evolve."""
import ast
import hashlib
import json
from pathlib import Path
import unittest


class ReportFormatLockTests(unittest.TestCase):
    def test_template_and_render_structure_match_approved_format(self):
        root = Path(__file__).resolve().parent.parent
        lock = json.loads((root / 'references/report-format-lock.json').read_text())
        self.assertEqual(hashlib.sha256((root / lock['css_path']).read_bytes()).hexdigest(), lock['css_sha256'])
        expected = lock['render_source_sha256']
        source = (root / 'scripts/report_estimate.py').read_text()
        actual = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
                  for node in ast.parse(source).body
                  if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in expected}
        self.assertEqual(actual, expected)
        source = (root / 'scripts/report_presentation_stage_a.py').read_text()
        expected = lock['presentation_render_source_sha256']
        actual = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
                  for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in expected}
        self.assertEqual(actual, expected)

    def test_explicit_operator_layout_and_render_match_approved_format(self):
        root = Path(__file__).resolve().parent.parent
        lock = json.loads((root / 'references/report-format-lock.json').read_text())
        self.assertEqual(lock['operator_revision'], 'operator-report-v1')
        self.assertEqual(hashlib.sha256((root / lock['operator_css_path']).read_bytes()).hexdigest(), lock['operator_css_sha256'])
        expected = lock['operator_render_source_sha256']
        source = (root / 'scripts/operator_report.py').read_text()
        actual = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
                  for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(actual, expected)

    def test_operator_contract_keeps_seven_sections_nine_modules_and_receipts(self):
        from operator_report import SECTION_ORDER, RIGHTS, APPENDIX_FILES
        root = Path(__file__).resolve().parent.parent
        lock = json.loads((root / 'references/report-format-lock.json').read_text())
        self.assertEqual(SECTION_ORDER, lock['operator_section_order'])
        self.assertEqual([right for right, _ in RIGHTS], lock['operator_module_order'])
        self.assertEqual(APPENDIX_FILES, lock['operator_required_appendices'])
        self.assertEqual(lock['operator_metric_labels'], ['已知结果风险', '查询完成率', '报告状态'])
        self.assertTrue(lock['operator_approved_format']['confidence_required'])



if __name__ == '__main__':
    unittest.main()
