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

        shutil.copy2(
            SKILL_ROOT / "scripts" / "setup_runner.sh",
            skill / "scripts" / "setup_runner.sh",
        )
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

    def test_setup_preserves_local_credentials_and_user_configs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill, runner = self.make_fixture(Path(temp_dir))
            self.run_setup(skill, runner)

            credential = runner / "config" / "doubao_embedding_vision.json"
            public_example = runner / "config" / "doubao_embedding_vision.example.json"
            task_config = runner / "config" / "amazon_front_keyword_search.json"
            self.assertTrue(credential.is_file())
            self.assertFalse(public_example.exists())
            self.assertEqual(json.loads(credential.read_text(encoding="utf-8"))["api_key"], "")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)
            self.assertIn(
                "doubao_embedding_vision: unconfigured",
                self.run_doctor(runner).stdout,
            )

            dummy_key = "test-key-must-not-be-logged"
            credential.write_text(
                json.dumps(
                    {
                        "api_key": dummy_key,
                        "model": "custom-model",
                        "base_url": "https://example.invalid/api/v3",
                        "api_path": "embeddings/multimodal",
                        "encoding_format": "float",
                    }
                ),
                encoding="utf-8",
            )
            credential.chmod(0o644)
            task_config.write_text(json.dumps({"custom": "user"}), encoding="utf-8")

            second_setup = self.run_setup(skill, runner)
            self.assertNotIn(dummy_key, second_setup.stdout + second_setup.stderr)
            self.assertEqual(
                json.loads(credential.read_text(encoding="utf-8"))["api_key"],
                dummy_key,
            )
            self.assertEqual(
                json.loads(task_config.read_text(encoding="utf-8")),
                {"custom": "user"},
            )
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)

            ignore_lines = (runner / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertIn("outputs/", ignore_lines)
            self.assertEqual(
                ignore_lines.count("config/doubao_embedding_vision.json"), 1
            )

            doctor = self.run_doctor(runner)
            self.assertIn("doubao_embedding_vision: ready", doctor.stdout)
            self.assertNotIn(dummy_key, doctor.stdout + doctor.stderr)

            credential.write_text("not-json", encoding="utf-8")
            self.assertIn(
                "doubao_embedding_vision: unconfigured",
                self.run_doctor(runner).stdout,
            )
            credential.unlink()
            self.assertIn(
                "doubao_embedding_vision: missing",
                self.run_doctor(runner).stdout,
            )

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


if __name__ == "__main__":
    unittest.main()
