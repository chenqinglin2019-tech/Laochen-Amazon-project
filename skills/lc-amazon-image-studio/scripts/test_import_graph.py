"""Every shipped module imports only shipped modules, the standard library, Pillow and NumPy."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
THIRD_PARTY = {"PIL", "numpy"}
REMOVED = {"lc_image_pipeline", "lc_workflow", "lc_layout", "lc_typography", "lc_quality", "lc_transactions",
           "lc_style_reference", "lc_cutout", "lc_main_composite", "lc_doctor", "lc_runtime_env", "lc_prompting"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


class ImportGraphTests(unittest.TestCase):
    def test_shipped_modules_resolve(self):
        local = {path.stem for path in SCRIPTS.glob("*.py")}
        stdlib = set(sys.stdlib_module_names) | {"winreg", "_winapi", "msvcrt"}
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name.startswith(("test_", "benchmark_")) or path.name == "studio_test_support.py":
                continue
            with self.subTest(module=path.name):
                unknown = {name for name in _imports(path) if name not in local | stdlib | THIRD_PARTY}
                self.assertEqual(unknown, set())
                self.assertEqual(_imports(path) & REMOVED, set())

    def test_no_old_pipeline_files_or_node_runtime_remain(self):
        root = SCRIPTS.parent
        self.assertFalse(list(SCRIPTS.glob("*.mjs")))
        self.assertFalse((root / "assets/fonts").exists())
        self.assertFalse((root / "assets/layout-runtime.json").exists())
        for name in REMOVED:
            self.assertFalse((SCRIPTS / f"{name}.py").exists(), name)

    def test_auth_gate_stays_free_of_pillow(self):
        for name in ("auth_gate.py", "lc_auth_pass.py", "lc_paths.py", "diagnose_auth.py", "runtime_bootstrap.py"):
            self.assertEqual(_imports(SCRIPTS / name) & THIRD_PARTY, set(), name)


if __name__ == "__main__":
    unittest.main()
