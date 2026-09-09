"""Installation checks use private temporary roots and synthetic credentials."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import setup_skill as setup


class SetupSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="安装 test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {"backend_url": "https://example.test", "backend_token": ""}
        (self.root / "config.example.json").write_bytes(b'\xef\xbb\xbf'+json.dumps(self.config).encode()+b'\r\n')
        (self.root / ".env.example").write_bytes(b'\xef\xbb\xbf# empty\r\nSERPER_API_KEY=\r\n')
        patcher = patch.dict(os.environ, {"LAOCHEN_BACKEND_TOKEN": ""})
        patcher.start(); self.addCleanup(patcher.stop)

    def test_init_handles_bom_crlf_and_private_new_files(self):
        result = setup.initialize(self.root)
        self.assertEqual([r["status"] for r in result], ["created_empty"] * 2)
        self.assertEqual((self.root / "config.json").read_bytes(), (self.root / "config.example.json").read_bytes())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((self.root / ".env").stat().st_mode), 0o600)
        self.assertEqual(setup.local_file_checks(self.root)["config.json"]["status"], "needs_token")

    def test_init_preserves_existing_secret_bytes_and_permissions(self):
        for name, content in (("config.json", b'original-private-configuration\r\n'), (".env", b'SERPER_API_KEY=synthetic-secret\r\n')):
            p = self.root / name;p.write_bytes(content);p.chmod(0o640)
        before = {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in (self.root / "config.json", self.root / ".env")}
        result = setup.initialize(self.root)
        self.assertTrue(all(x["status"] == "preserved_existing" for x in result))
        for name, state in before.items():
            p=self.root/name;self.assertEqual((p.read_bytes(),stat.S_IMODE(p.stat().st_mode)),state)

    def test_populated_templates_are_rejected_before_any_write(self):
        (self.root / ".env.example").write_text('SERPER_API_KEY=synthetic-template-secret\n',encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"ENV_TEMPLATE_MUST_BE_EMPTY"):
            setup.initialize(self.root)
        self.assertFalse((self.root / "config.json").exists())

    def test_env_backend_token_is_configured_without_echoing_it(self):
        setup.initialize(self.root)
        with patch.dict(os.environ,{"LAOCHEN_BACKEND_TOKEN":"synthetic-environment-secret"}):
            result=setup.local_file_checks(self.root)
        self.assertEqual(result["config.json"]["status"],"configured")
        self.assertEqual(result["config.json"]["token_source"],"environment")
        self.assertNotIn("synthetic-environment-secret",json.dumps(result))

    def test_environment_token_does_not_hide_invalid_config_url(self):
        setup.initialize(self.root)
        (self.root / "config.json").write_text(json.dumps({"backend_url":"missing-scheme","backend_token":""}),encoding="utf-8")
        with patch.dict(os.environ,{"LAOCHEN_BACKEND_TOKEN":"synthetic-environment-secret"}):
            result=setup.local_file_checks(self.root)
        self.assertEqual(result["config.json"]["status"],"invalid")

    def test_backend_diagnostic_preserves_frozen_selection_semantics(self):
        setup.initialize(self.root)
        for environment, token, source in ((" ","file-token","environment"),("",0,"config"),("",None,"config"),("","",None)):
            (self.root/"config.json").write_text(json.dumps({**self.config,"backend_token":token}),encoding="utf-8")
            with patch.dict(os.environ,{"LAOCHEN_BACKEND_TOKEN":environment}):
                result=setup.local_file_checks(self.root)["config.json"]
            self.assertEqual(result["token_source"],source)
            self.assertEqual(result["status"],"configured" if source else "needs_token")

    def test_install_environment_does_not_forward_credentials(self):
        with patch.dict(os.environ,{"LAOCHEN_BACKEND_TOKEN":"synthetic-env","SERPER_API_KEY":"synthetic-key","PYTHONPATH":"untrusted-path","PIP_TARGET":"outside-venv","PIP_PREFIX":"outside-prefix","PIP_CONFIG_FILE":"untrusted-config"}):
            environment=setup._environment()
        for key in ("LAOCHEN_BACKEND_TOKEN","SERPER_API_KEY","PYTHONPATH","PIP_TARGET","PIP_PREFIX"):
            self.assertNotIn(key,environment)
        self.assertEqual(environment["PYTHONUTF8"],"1")
        self.assertEqual(environment["PIP_CONFIG_FILE"],os.devnull)

    def test_python_override_priority_matches_browser_runtime(self):
        with patch.dict(os.environ,{"LC_IPR_PYTHON":"selected-python"}), \
             patch.object(setup,"python_probe") as probe:
            self.assertEqual(setup.select_python(self.root),"selected-python")
            self.assertEqual(setup.select_python(self.root,"explicit-python"),"explicit-python")
        probe.assert_not_called()

    def test_python_probe_reports_selected_process_platform(self):
        value={"version":[3,12,0],"platform":{"process_arch":"x64","translation":"rosetta"}}
        with patch.object(setup,"_probe",return_value=(0,json.dumps(value),"")) as probe:
            result=setup.python_probe("selected-python")
        self.assertEqual(result["platform"],value["platform"])
        self.assertIn("'platform':inspect_platform()",probe.call_args.args[0][2])

    def test_check_uses_selected_platform_and_keeps_bootstrap_separate(self):
        bootstrap={"compatible":True,"process_arch":"arm64","auth_binary_name":None}
        selected={"compatible":True,"process_arch":"x64","translation":"rosetta","auth_binary_name":None}
        py={"supported":True,"pypdf":True,"pypdf_version":"6.10.0","platform":selected}
        with patch.object(setup,"inspect_platform",return_value=bootstrap), \
             patch.object(setup,"select_python",return_value="selected-python"), \
             patch.object(setup,"python_probe",return_value=py), \
             patch.object(setup,"_json",side_effect=[{}, {"dependencies":{"playwright-core":"1.62.0"}}, {"version":"1.62.0"}]), \
             patch.object(setup.shutil,"which",return_value=None), \
             patch.object(setup,"_browser_check",return_value={"status":"missing"}), \
             patch.object(setup,"local_file_checks",return_value={"config.json":{"status":"needs_token"},".env":{"status":"valid"}}):
            result=setup.inspect_install(self.root)
        self.assertEqual(result["platform"],selected)
        self.assertEqual(result["bootstrap_platform"],bootstrap)

    def test_dependency_install_uses_local_venv_and_fixed_lock_commands(self):
        with patch.object(setup,"select_python",return_value="explicit-python"), \
             patch.object(setup,"python_probe",return_value={"supported":True,"is_venv":True,"prefix":str(self.root/".venv")}), \
             patch.object(setup,"_run_install") as run, \
             patch.object(setup.shutil,"which",return_value="npm.cmd" if os.name=="nt" else "/safe/npm"), \
             patch.object(Path,"is_file",return_value=True):
            result=setup.install_dependencies(self.root)
        self.assertFalse(result["global_packages_changed"])
        commands=[x.args[0] for x in run.call_args_list]
        self.assertEqual(commands[0][:3],["explicit-python","-m","venv"])
        self.assertIn(str(self.root/"requirements.txt"),commands[1])
        self.assertTrue(str(commands[1][0]).startswith(str(self.root/".venv")))
        self.assertIn("--ignore-scripts", " ".join(commands[2]))

    def test_invalid_existing_venv_is_never_replaced(self):
        (self.root/".venv").mkdir()
        with patch.object(setup,"select_python",return_value="explicit-python"), \
             patch.object(setup,"python_probe",return_value={"supported":True}), \
             patch.object(setup,"_run_install") as run, \
             self.assertRaisesRegex(ValueError,"EXISTING_VENV_INCOMPLETE"):
            setup.install_dependencies(self.root)
        run.assert_not_called()

    def test_readonly_checks_do_not_create_missing_files(self):
        result=setup.local_file_checks(self.root)
        self.assertTrue(all(x["status"]=="invalid" for x in result.values()))
        self.assertFalse((self.root/"config.json").exists())
        self.assertFalse((self.root/".env").exists())


if __name__ == "__main__":
    unittest.main()
