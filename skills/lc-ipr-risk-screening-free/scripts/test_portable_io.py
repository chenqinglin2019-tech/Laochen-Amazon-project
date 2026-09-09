"""Exercise local atomic writes and real process locks on the running platform."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import common
import epo_quota_ledger as quota
import eps_client
import serper_client
import provider_utils
from execution_lock import execution_lock
from offline_test_support import offline_environment
from provider_utils import file_lock
from security_quota_test import quota_config


class PortableIOTests(unittest.TestCase):
    def test_source_locks_fail_closed_without_a_native_backend(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(provider_utils, "fcntl", None), patch.object(provider_utils, "msvcrt", None):
            root = Path(raw)
            locks = (serper_client.serper_budget_lock(root), eps_client.EpsQuotaLedger(root).locked())
            for lock in locks:
                with self.assertRaises(provider_utils.ProviderError) as error:
                    with lock:
                        self.fail("unlocked network work must not execute")
                self.assertEqual(error.exception.code, "PROVIDER_LOCK_UNAVAILABLE")

    def test_utf8_bom_crlf_and_atomic_replacement_in_chinese_space_path(self):
        with tempfile.TemporaryDirectory(prefix="中文 用户 ") as raw:
            path = Path(raw) / "配置 文件.json"
            path.write_bytes(b"\xef\xbb\xbf" + '{\r\n"名字":"张三"\r\n}'.encode("utf-8"))
            self.assertEqual(common.load_json(path), {"名字": "张三"})
            common.atomic_write_json(path, {"名字": "李四"})
            self.assertEqual(common.load_json(path), {"名字": "李四"})
            before = path.read_bytes()
            with patch.object(common.os, "replace", side_effect=PermissionError("fixture sharing violation")):
                with self.assertRaises(PermissionError):
                    common.atomic_write_json(path, {"名字": "不能发布"})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(raw).iterdir()), [path])

    def test_quota_writer_without_fchmod_closes_handle_before_replace(self):
        class OSWithoutFchmod:
            def __getattr__(self, name):
                if name == "fchmod":
                    raise AttributeError(name)
                return getattr(os, name)
        with tempfile.TemporaryDirectory(prefix="额度 测试 ") as raw:
            manager = quota.EpoQuotaLedger(quota_config(), "synthetic-portable-account", ledger_dir=Path(raw))
            with patch.object(quota, "os", OSWithoutFchmod()):
                manager.reserve("任务一")
            stored = json.loads(manager.path.read_text(encoding="utf-8"))
            self.assertTrue(stored["reservations"])
            before = manager.path.read_bytes()
            with patch.object(quota.os, "replace", side_effect=PermissionError("fixture sharing violation")):
                with self.assertRaises(PermissionError):
                    manager.reserve("任务二")
            self.assertEqual(manager.path.read_bytes(), before)
            self.assertFalse(list(Path(raw).glob(".epo-quota.*")))

    def test_native_cross_process_locks_block_and_release(self):
        script = """
import sys
from pathlib import Path
from execution_lock import execution_lock
from provider_utils import file_lock, ProviderError
path, kind = Path(sys.argv[1]), sys.argv[2]
try:
    with (execution_lock(path, 'api') if kind == 'execution' else file_lock(path / '.evidence.lock', timeout=.1)):
        print('acquired')
except (ValueError, ProviderError):
    print('blocked')
"""
        with tempfile.TemporaryDirectory(prefix="锁 中文 ") as raw:
            root = Path(raw)
            for kind in ("execution", "provider"):
                def attempt():
                    result = subprocess.run([sys.executable, "-c", script, raw, kind],
                        cwd=Path(__file__).parent, env=offline_environment(),
                        capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
                    return result.stdout.strip()
                with (execution_lock(root, "api") if kind == "execution" else file_lock(root / ".evidence.lock")):
                    self.assertEqual(attempt(), "blocked", kind)
                self.assertEqual(attempt(), "acquired", kind)


if __name__ == "__main__":
    unittest.main()
