from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backend_config.py"
SPEC = importlib.util.spec_from_file_location("backend_config", MODULE_PATH)
assert SPEC and SPEC.loader
backend_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend_config)


class BackendConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "config.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, content: str, mode: int = 0o600) -> None:
        self.path.write_text(content, encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.path, mode)

    def test_valid_config_returns_only_redacted_auth_summary(self) -> None:
        self.write('{"backend_url":"https://mcp.example.com","backend_token":"sk-example-secret"}')
        result = backend_config.validate(self.path)
        self.assertEqual("configured", result["status"])
        self.assertNotIn("sk-example-secret", str(result))

    def test_rejects_insecure_or_incomplete_config(self) -> None:
        self.write('{"backend_url":"https://mcp.example.com"}', 0o600)
        with self.assertRaises(backend_config.BackendConfigError):
            backend_config.validate(self.path)
        self.write('{"backend_url":"https://mcp.example.com","backend_token":"sk-example-secret"}', 0o644)
        if os.name != "nt":
            with self.assertRaises(backend_config.BackendConfigError):
                backend_config.validate(self.path)
