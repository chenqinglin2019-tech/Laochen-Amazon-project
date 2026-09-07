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


if __name__ == '__main__':
    unittest.main()
