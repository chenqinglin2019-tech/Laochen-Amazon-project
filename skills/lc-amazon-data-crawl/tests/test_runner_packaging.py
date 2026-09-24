from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def auth_binary_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("darwin"):
        os_name, extension = "darwin", ""
    elif system.startswith("linux"):
        os_name, extension = "linux", ""
    elif system.startswith(("windows", "mingw", "msys", "cygwin")):
        os_name, extension = "windows", ".exe"
    else:
        raise unittest.SkipTest(f"unsupported test platform: {system}")
    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        raise unittest.SkipTest(f"unsupported test architecture: {machine}")
    if os_name == "windows":
        arch = "amd64"
    return f"lc-auth-check-{os_name}-{arch}{extension}"


class RunnerPackagingTests(unittest.TestCase):
    def mac_xattr(self, path: Path, *args: str) -> str:
        return subprocess.run(
            ["xattr", *args, str(path)], check=True, text=True, capture_output=True
        ).stdout.strip()

    def make_fixture(self, root: Path) -> tuple[Path, Path]:
        skill = root / "skill"
        runner = root / "runner"
        for directory in (
            skill / "scripts",
            skill / "assets" / "config",
            skill / "assets" / "inputs",
            skill / "tools" / "bin",
        ):
            directory.mkdir(parents=True)

        for script in ("setup_runner.sh", "check_auth.sh", "migrate_operation_config.py", "install_for_user.sh"):
            shutil.copy2(SKILL_ROOT / "scripts" / script, skill / "scripts" / script)
        (skill / "scripts" / "stub.py").write_text("# fixture\n", encoding="utf-8")
        (skill / "assets" / "requirements.txt").write_text("", encoding="utf-8")
        (skill / "assets" / "inputs" / "stub.csv").write_text(
            "value\nfixture\n", encoding="utf-8"
        )
        (skill / "assets" / "config" / "amazon_delivery_locations.json").write_text(
            json.dumps(
                {
                    "locations": {
                        "amazon.com": {
                            "city": "New York",
                            "postal_code": "10001",
                            "strategy": "postal",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (skill / "assets" / "config" / "amazon_front_keyword_search.json").write_text(
            json.dumps({"custom": "template"}), encoding="utf-8"
        )
        (skill / "assets" / "config" / "doubao_embedding_vision.example.json").write_text(
            json.dumps(
                {
                    "api_key": "",
                    "model": "doubao-embedding-vision-251215",
                    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                    "api_path": "embeddings/multimodal",
                    "encoding_format": "float",
                }
            ),
            encoding="utf-8",
        )
        (skill / "assets" / "config" / "doubao_same_product_mini.example.json").write_text(
            json.dumps(
                {
                    "api_key": "",
                    "model": "doubao-seed-2-0-mini-260428",
                    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                    "api_path": "chat/completions",
                }
            ),
            encoding="utf-8",
        )
        (skill / "config.json").write_text(
            json.dumps({"backend_url": "fixture", "backend_token": "fixture"}),
            encoding="utf-8",
        )
        auth_binary = skill / "tools" / "bin" / auth_binary_name()
        auth_binary.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        auth_binary.chmod(0o755)
        runner.mkdir()
        (runner / ".gitignore").write_text("outputs/\n", encoding="utf-8")
        return skill, runner

    def run_setup(self, skill: Path, runner: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(skill / "scripts" / "setup_runner.sh"), str(runner)],
            check=True,
            text=True,
            capture_output=True,
        )

    def run_doctor(self, runner: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(runner / "lc-amazon-data-crawl.sh"), "doctor"],
            cwd=runner,
            check=True,
            text=True,
            capture_output=True,
        )

    def test_public_install_uses_local_token_without_changing_blank_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, runner = self.make_fixture(Path(temp_dir))
            public_config = skill / "config.json"
            public_config.write_text(
                json.dumps({"backend_url": "fixture", "backend_token": ""}),
                encoding="utf-8",
            )
            env = dict(os.environ, LC_AMAZON_INSTALL_SETUP_ONLY="1")
            completed = subprocess.run(
                ["bash", str(skill / "scripts" / "install_for_user.sh"), str(runner)],
                input="recipient-token\n",
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )
            self.assertNotIn("recipient-token", completed.stdout + completed.stderr)
            self.assertEqual(json.loads(public_config.read_text())["backend_token"], "")
            self.assertEqual(
                json.loads((skill / "config.local.json").read_text())["backend_token"],
                "recipient-token",
            )
            self.assertEqual(
                json.loads((runner / "config.local.json").read_text())["backend_token"],
                "recipient-token",
            )
            self.assertIn("config.local.json", (runner / ".gitignore").read_text())

    def test_auth_prefers_local_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, _runner = self.make_fixture(Path(temp_dir))
            (skill / "config.local.json").write_text(
                json.dumps({"backend_url": "fixture", "backend_token": "recipient-token"}),
                encoding="utf-8",
            )
            capture = Path(temp_dir) / "auth-config-path.txt"
            auth_binary = skill / "tools" / "bin" / auth_binary_name()
            auth_binary.write_text(
                '#!/usr/bin/env bash\nprintf "%s" "$2" > "$AUTH_CAPTURE"\n',
                encoding="utf-8",
            )
            auth_binary.chmod(0o755)
            env = dict(os.environ, AUTH_CAPTURE=str(capture))
            subprocess.run(
                ["bash", str(skill / "scripts" / "check_auth.sh")],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(capture.read_text(), str(skill / "config.local.json"))

    def test_setup_preserves_local_credentials_and_user_configs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, runner = self.make_fixture(Path(temp_dir))
            self.run_setup(skill, runner)

            embedding_credential = runner / "config" / "doubao_embedding_vision.json"
            mini_credential = runner / "config" / "doubao_same_product_mini.json"
            embedding_example = runner / "config" / "doubao_embedding_vision.example.json"
            mini_example = runner / "config" / "doubao_same_product_mini.example.json"
            task_config = runner / "config" / "amazon_front_keyword_search.json"
            auth_config = runner / "config.json"
            self.assertTrue(embedding_credential.is_file())
            self.assertTrue(mini_credential.is_file())
            self.assertFalse(embedding_example.exists())
            self.assertFalse(mini_example.exists())
            self.assertEqual(
                json.loads(embedding_credential.read_text(encoding="utf-8"))["api_key"],
                "",
            )
            self.assertEqual(
                json.loads(mini_credential.read_text(encoding="utf-8"))["api_key"],
                "",
            )
            if os.name != "nt":
                self.assertEqual(
                    stat.S_IMODE(embedding_credential.stat().st_mode), 0o600
                )
                self.assertEqual(stat.S_IMODE(mini_credential.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(auth_config.stat().st_mode), 0o600)
            self.assertIn(
                "doubao_embedding_vision: unconfigured",
                self.run_doctor(runner).stdout,
            )
            self.assertIn(
                "doubao_same_product_mini: unconfigured",
                self.run_doctor(runner).stdout,
            )

            embedding_dummy_key = "embedding-test-key-must-not-be-logged"
            mini_dummy_key = "mini-test-key-must-not-be-logged"
            embedding_credential.write_text(
                json.dumps(
                    {
                        "api_key": embedding_dummy_key,
                        "model": "custom-model",
                        "base_url": "https://example.invalid/api/v3",
                        "api_path": "embeddings/multimodal",
                        "encoding_format": "float",
                    }
                ),
                encoding="utf-8",
            )
            mini_credential.write_text(
                json.dumps(
                    {
                        "api_key": mini_dummy_key,
                        "model": "custom-mini-model",
                        "base_url": "https://example.invalid/api/v3",
                        "api_path": "chat/completions",
                    }
                ),
                encoding="utf-8",
            )
            embedding_credential.chmod(0o644)
            mini_credential.chmod(0o644)
            task_config.write_text(json.dumps({"custom": "user"}), encoding="utf-8")
            auth_config.write_text(
                json.dumps({"backend_url": "fixture", "backend_token": "user-token"}),
                encoding="utf-8",
            )
            # Simulate a runner generated before the shared entry point existed.
            (runner / "scripts" / "check_auth.sh").unlink()
            (runner / "lc-amazon-data-crawl.sh").write_text(
                "#!/usr/bin/env bash\nexit 99\n", encoding="utf-8"
            )

            second_setup = self.run_setup(skill, runner)
            self.assertTrue((runner / "scripts" / "check_auth.sh").is_file())
            self.assertEqual(
                json.loads(auth_config.read_text(encoding="utf-8"))["backend_token"],
                "user-token",
            )
            self.assertNotIn(
                embedding_dummy_key, second_setup.stdout + second_setup.stderr
            )
            self.assertNotIn(mini_dummy_key, second_setup.stdout + second_setup.stderr)
            self.assertEqual(
                json.loads(embedding_credential.read_text(encoding="utf-8"))["api_key"],
                embedding_dummy_key,
            )
            self.assertEqual(
                json.loads(mini_credential.read_text(encoding="utf-8"))["api_key"],
                mini_dummy_key,
            )
            migrated = json.loads(task_config.read_text(encoding="utf-8"))
            self.assertEqual(migrated["custom"], "user")
            self.assertEqual(migrated["operation_mode"], "supervised")
            self.assertEqual(migrated["batch_pause_seconds_min"], 180)
            before_third_setup = task_config.read_bytes()
            self.run_setup(skill, runner)
            self.assertEqual(task_config.read_bytes(), before_third_setup)
            if os.name != "nt":
                self.assertEqual(
                    stat.S_IMODE(embedding_credential.stat().st_mode), 0o600
                )
                self.assertEqual(stat.S_IMODE(mini_credential.stat().st_mode), 0o600)

            ignore_lines = (runner / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertIn("outputs/", ignore_lines)
            self.assertEqual(
                ignore_lines.count("config/doubao_embedding_vision.json"), 1
            )
            self.assertEqual(
                ignore_lines.count("config/doubao_same_product_mini.json"), 1
            )
            self.assertEqual(ignore_lines.count("config.json"), 1)

            doctor = self.run_doctor(runner)
            self.assertIn("doubao_embedding_vision: ready", doctor.stdout)
            self.assertIn("doubao_same_product_mini: ready", doctor.stdout)
            self.assertNotIn(embedding_dummy_key, doctor.stdout + doctor.stderr)
            self.assertNotIn(mini_dummy_key, doctor.stdout + doctor.stderr)

            embedding_credential.write_text("not-json", encoding="utf-8")
            self.assertIn(
                "doubao_embedding_vision: unconfigured",
                self.run_doctor(runner).stdout,
            )
            mini_credential.write_text("not-json", encoding="utf-8")
            self.assertIn(
                "doubao_same_product_mini: unconfigured",
                self.run_doctor(runner).stdout,
            )
            embedding_credential.unlink()
            mini_credential.unlink()
            self.assertIn(
                "doubao_embedding_vision: missing",
                self.run_doctor(runner).stdout,
            )
            self.assertIn(
                "doubao_same_product_mini: missing",
                self.run_doctor(runner).stdout,
            )

    def test_auth_entry_repairs_permissions_and_uses_its_own_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="鉴权 中文路径 ") as temp_dir:
            skill, _ = self.make_fixture(Path(temp_dir))
            entry = skill / "scripts" / "check_auth.sh"
            entry.chmod(0o600)
            auth_bin = skill / "tools" / "bin" / auth_binary_name()
            auth_bin.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$0.args"\n',
                encoding="utf-8",
            )
            auth_bin.chmod(0o600)
            for _ in range(2):
                result = subprocess.run(
                    ["bash", str(entry)], cwd=temp_dir, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")
            self.assertTrue(os.access(auth_bin, os.X_OK))
            self.assertEqual(
                Path(str(auth_bin) + ".args").read_text().splitlines(),
                ["--config", str(skill / "config.json")],
            )

    @unittest.skipUnless(platform.system() == "Darwin", "macOS quarantine only")
    def test_setup_and_runner_remove_real_quarantine_before_auth(self) -> None:
        with tempfile.TemporaryDirectory(prefix="下载 中文路径 ") as temp_dir:
            skill, runner = self.make_fixture(Path(temp_dir))
            auth_bin = skill / "tools" / "bin" / auth_binary_name()
            auth_bin.chmod(0o600)
            self.mac_xattr(auth_bin, "-w", "com.apple.quarantine", "0083;65000000;Test;")
            self.mac_xattr(auth_bin, "-w", "com.example.lc-auth-test", "keep")
            # Only the selected binary may be changed.
            other = skill / "tools" / "bin" / "unrelated-file"
            other.write_text("untouched", encoding="utf-8")
            self.mac_xattr(other, "-w", "com.apple.quarantine", "0083;65000000;Test;")
            self.run_setup(skill, runner)
            self.assertNotIn("com.apple.quarantine", self.mac_xattr(auth_bin).splitlines())
            self.assertEqual(self.mac_xattr(auth_bin, "-p", "com.example.lc-auth-test"), "keep")
            self.assertIn("com.apple.quarantine", self.mac_xattr(other).splitlines())

            runner_bin = runner / "tools" / "bin" / auth_binary_name()
            runner_bin.chmod(0o600)
            self.mac_xattr(runner_bin, "-w", "com.apple.quarantine", "0083;65000000;Test;")
            self.assertIn("runner:", self.run_doctor(runner).stdout)
            self.assertNotIn("com.apple.quarantine", self.mac_xattr(runner_bin).splitlines())
            self.assertTrue(os.access(runner_bin, os.X_OK))
            self.run_doctor(runner)

    def test_auth_failure_stops_setup_before_writing_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, runner = self.make_fixture(Path(temp_dir))
            auth_bin = skill / "tools" / "bin" / auth_binary_name()
            auth_bin.write_text(
                "#!/usr/bin/env bash\necho sensitive-response\n"
                "echo sensitive-response >&2\nexit 1\n", encoding="utf-8"
            )
            before = sorted(p.relative_to(runner) for p in runner.rglob("*"))
            result = subprocess.run(
                ["bash", str(skill / "scripts" / "setup_runner.sh"), str(runner)],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 4)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr.strip(), "云端鉴权未通过，本轮不继续执行。")
            self.assertEqual(before, sorted(p.relative_to(runner) for p in runner.rglob("*")))

    def test_every_runner_command_stops_on_auth_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, runner = self.make_fixture(Path(temp_dir))
            self.run_setup(skill, runner)
            auth_bin = runner / "tools" / "bin" / auth_binary_name()
            auth_bin.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            # Harmless sentinel prevents installs/browser actions even on a regression.
            python = runner / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text(
                '#!/usr/bin/env bash\nprintf called > "$0.called"\n', encoding="utf-8"
            )
            python.chmod(0o755)
            for command in (
                "install", "doctor", "amazon-front-dry-run", "amazon-front-run",
                "category-rank-dry-run", "category-rank-run",
                "image-competitor-dry-run", "image-competitor-run",
                "cdp-browser-start", "sellersprite-check",
            ):
                with self.subTest(command=command):
                    result = subprocess.run(
                        ["bash", str(runner / "lc-amazon-data-crawl.sh"), command],
                        text=True, capture_output=True,
                    )
                    self.assertEqual(result.returncode, 4, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr.strip(), "云端鉴权未通过，本轮不继续执行。")
                    self.assertFalse(Path(str(python) + ".called").exists())

    def test_missing_auth_binary_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, _ = self.make_fixture(Path(temp_dir))
            (skill / "tools" / "bin" / auth_binary_name()).unlink()
            result = subprocess.run(
                ["bash", str(skill / "scripts" / "check_auth.sh")],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("鉴权工具缺失", result.stderr)

    @unittest.skipUnless(platform.system() == "Darwin", "macOS quarantine only")
    def test_quarantine_failures_stop_before_binary_execution(self) -> None:
        cases = {
            "read_failed": "exit 1\n",
            "remove_failed": '[[ "${1:-}" == "-d" ]] && exit 1\necho com.apple.quarantine\n',
            "attribute_remains": '[[ "${1:-}" == "-d" ]] && exit 0\necho com.apple.quarantine\n',
        }
        for name, body in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                skill, runner = self.make_fixture(Path(temp_dir))
                auth_bin = skill / "tools" / "bin" / auth_binary_name()
                auth_bin.write_text(
                    '#!/usr/bin/env bash\nprintf called > "$0.called"\n', encoding="utf-8"
                )
                fake_tools = Path(temp_dir) / "fake-tools"
                fake_tools.mkdir()
                fake_xattr = fake_tools / "xattr"
                fake_xattr.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
                fake_xattr.chmod(0o755)
                result = subprocess.run(
                    ["bash", str(skill / "scripts" / "setup_runner.sh"), str(runner)],
                    env={**os.environ, "PATH": str(fake_tools) + os.pathsep + os.environ["PATH"]},
                    text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("启动准备失败", result.stderr)
                self.assertNotIn("云端鉴权未通过", result.stderr)
                self.assertFalse(Path(str(auth_bin) + ".called").exists())
                self.assertFalse((runner / "scripts").exists())

    def test_execute_permission_failures_stop_before_auth(self) -> None:
        for status in (0, 1):
            with self.subTest(chmod_status=status), tempfile.TemporaryDirectory() as temp_dir:
                skill, _ = self.make_fixture(Path(temp_dir))
                auth_bin = skill / "tools" / "bin" / auth_binary_name()
                auth_bin.chmod(0o600)
                fake_tools = Path(temp_dir) / "fake-tools"
                fake_tools.mkdir()
                fake_chmod = fake_tools / "chmod"
                fake_chmod.write_text(f"#!/usr/bin/env bash\nexit {status}\n", encoding="utf-8")
                fake_chmod.chmod(0o755)
                result = subprocess.run(
                    ["bash", str(skill / "scripts" / "check_auth.sh")],
                    env={**os.environ, "PATH": str(fake_tools) + os.pathsep + os.environ["PATH"]},
                    text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("执行权限", result.stderr)

    @unittest.skipUnless(platform.system() == "Darwin", "real macOS binary smoke test")
    def test_real_downloaded_binary_reaches_empty_token_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="真实鉴权 中文路径 ") as temp_dir:
            skill, _ = self.make_fixture(Path(temp_dir))
            auth_bin = skill / "tools" / "bin" / auth_binary_name()
            shutil.copyfile(SKILL_ROOT / "tools" / "bin" / auth_binary_name(), auth_bin)
            (skill / "config.json").write_text(
                json.dumps({"backend_url": "https://example.invalid", "backend_token": ""}),
                encoding="utf-8",
            )
            auth_bin.chmod(0o600)
            self.mac_xattr(auth_bin, "-w", "com.apple.quarantine", "0083;65000000;Test;")
            result = subprocess.run(
                ["bash", str(skill / "scripts" / "check_auth.sh")],
                text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertEqual(result.stderr.strip(), "云端鉴权未通过，本轮不继续执行。")
            self.assertNotIn("com.apple.quarantine", self.mac_xattr(auth_bin).splitlines())
            self.assertTrue(os.access(auth_bin, os.X_OK))

    def test_public_doubao_example_is_empty_and_uses_ark_contract(self) -> None:
        example = json.loads(
            (
                SKILL_ROOT
                / "assets"
                / "config"
                / "doubao_embedding_vision.example.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(example["api_key"], "")
        self.assertEqual(example["model"], "doubao-embedding-vision-251215")
        self.assertEqual(
            example["base_url"], "https://ark.cn-beijing.volces.com/api/v3"
        )
        self.assertEqual(example["api_path"], "embeddings/multimodal")
        self.assertEqual(example["encoding_format"], "float")

    def test_public_doubao_mini_example_is_empty_and_uses_ark_contract(self) -> None:
        example = json.loads(
            (
                SKILL_ROOT
                / "assets"
                / "config"
                / "doubao_same_product_mini.example.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(example["api_key"], "")
        self.assertEqual(example["model"], "doubao-seed-2-0-mini-260428")
        self.assertEqual(
            example["base_url"], "https://ark.cn-beijing.volces.com/api/v3"
        )
        self.assertEqual(example["api_path"], "chat/completions")

    def test_image_template_uses_cascade_contract(self) -> None:
        config = json.loads(
            (
                SKILL_ROOT / "assets" / "config" / "amazon_image_competitors.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(config["match_mode"], "cascade")
        self.assertEqual(config["prescreen_min_similarity"], 0.7)
        self.assertEqual(config["prescreen_max_matches"], 10)
        self.assertEqual(
            config["doubao_mini_config_file"],
            "config/doubao_same_product_mini.json",
        )
        self.assertEqual(config["mini_batch_size"], 6)
        self.assertEqual(config["mini_retry_attempts"], 3)
        self.assertEqual(config["mini_retry_backoff_seconds"], 1)


if __name__ == "__main__":
    unittest.main()
