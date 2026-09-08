"""Offline verification cannot inherit account credentials or read user files."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common import ENV_CREDENTIALS
from offline_test_support import offline_environment
import self_test
import verify_skill


class OfflineVerificationTests(unittest.TestCase):
    def test_environment_keeps_runtime_controls_and_removes_all_credential_names(self):
        supplied = {name: "synthetic-credential" for name in ENV_CREDENTIALS.values()}
        supplied.update(PATH="synthetic-path", LC_IPR_TEST_MODE="1", SERPAPI_BASE_URL="http://127.0.0.1:9")
        environment = offline_environment(supplied)
        self.assertTrue(set(ENV_CREDENTIALS.values()).isdisjoint(environment))
        self.assertEqual(environment["LC_IPR_OFFLINE_TESTS"], "1")
        self.assertEqual(environment["LC_IPR_TEST_MODE"], "1")
        self.assertEqual(environment["SERPAPI_BASE_URL"], "http://127.0.0.1:9")
        self.assertEqual(environment["PATH"], "synthetic-path")
        self.assertIn("LAOCHEN_BACKEND_TOKEN", supplied)

    def test_both_entrypoints_isolate_parent_fixture_work_and_restore_caller_environment(self):
        def fixture_work():
            self.assertEqual(os.environ["LC_IPR_OFFLINE_TESTS"], "1")
            self.assertTrue(set(ENV_CREDENTIALS.values()).isdisjoint(os.environ))
            return 0

        for module in (verify_skill, self_test):
            with self.subTest(entrypoint=module.__name__), patch.dict(os.environ, {
                "LAOCHEN_BACKEND_TOKEN": "synthetic-parent-secret", "LC_IPR_OFFLINE_TESTS": "",
            }), patch.object(module, "_main", side_effect=fixture_work) as work:
                module.main()
                work.assert_called_once_with()
                self.assertEqual(os.environ["LAOCHEN_BACKEND_TOKEN"], "synthetic-parent-secret")
                self.assertEqual(os.environ["LC_IPR_OFFLINE_TESTS"], "")

    def test_verification_child_gets_only_runtime_controls_and_test_output(self):
        supplied = {"LAOCHEN_BACKEND_TOKEN": "synthetic-child-secret", "LC_IPR_TEST_MODE": "1"}
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            verify_skill.subprocess, "run", return_value=subprocess.CompletedProcess(["synthetic"], 0, "ok", "")
        ) as run:
            result = verify_skill.run_check("fixture", ["synthetic"], Path(temporary), env=supplied)
            environment = run.call_args.kwargs["env"]
            self.assertTrue(set(ENV_CREDENTIALS.values()).isdisjoint(environment))
            self.assertEqual(environment["LC_IPR_OFFLINE_TESTS"], "1")
            self.assertEqual(environment["LC_IPR_TEST_MODE"], "1")
            self.assertEqual(result["status"], "passed")
            self.assertNotIn("synthetic-child-secret", (Path(temporary) / "fixture.log").read_text())

    def test_legacy_command_cannot_forward_inherited_credentials(self):
        with patch.object(self_test.subprocess, "run", return_value=subprocess.CompletedProcess(["fixture"], 0, "", "")) as run:
            self_test.command("fixture.py", env={"SIGNA_API_KEY": "synthetic-secret", "LC_IPR_TEST_MODE": "1"})
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("SIGNA_API_KEY", environment)
        self.assertEqual(environment["LC_IPR_OFFLINE_TESTS"], "1")
        self.assertEqual(environment["LC_IPR_TEST_MODE"], "1")


if __name__ == "__main__":
    unittest.main()
