import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIGURATOR = ROOT / "scripts" / "configure_harness_proxy.py"


class GoodHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"data":{"ok":true},"requestId":"test"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class HtmlFallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>Harness</title>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class HarnessProxyConfiguratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.health_server = ThreadingHTTPServer(("127.0.0.1", 0), GoodHealthHandler)
        cls.health_thread = threading.Thread(target=cls.health_server.serve_forever, daemon=True)
        cls.health_thread.start()
        cls.health_origin = f"http://127.0.0.1:{cls.health_server.server_port}"

        cls.html_server = ThreadingHTTPServer(("127.0.0.1", 0), HtmlFallbackHandler)
        cls.html_thread = threading.Thread(target=cls.html_server.serve_forever, daemon=True)
        cls.html_thread.start()
        cls.html_origin = f"http://127.0.0.1:{cls.html_server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.health_server.shutdown()
        cls.health_server.server_close()
        cls.html_server.shutdown()
        cls.html_server.server_close()
        cls.health_thread.join(timeout=2)
        cls.html_thread.join(timeout=2)

    def make_nginx(self, directory, test_status=0, reload_status=0):
        executable = Path(directory) / "nginx"
        executable.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-t\" ]; then exit " + str(test_status) + "; fi\n"
            "if [ \"$1\" = \"-s\" ]; then exit " + str(reload_status) + "; fi\n"
            "exit 2\n",
            encoding="utf-8",
        )
        executable.chmod(0o750)
        return executable

    def run_configurator(self, config_file, nginx_bin, *extra):
        verification = ["--verify-origin", self.health_origin] if "--apply" in extra else []
        return subprocess.run(
            [
                sys.executable,
                str(CONFIGURATOR),
                "--config-file",
                str(config_file),
                "--nginx-bin",
                str(nginx_bin),
                "--skip-root-check",
                *verification,
                *extra,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_requires_an_explicit_mutation_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx)

            self.assertEqual(result.returncode, 2)
            self.assertIn("one of the arguments --apply --remove is required", result.stderr)
            self.assertFalse(config.exists())

    def test_apply_requires_public_origin_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            nginx = self.make_nginx(root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONFIGURATOR),
                    "--config-file",
                    str(config),
                    "--nginx-bin",
                    str(nginx),
                    "--skip-root-check",
                    "--apply",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("At least one --verify-origin", result.stderr)
            self.assertFalse(config.exists())

    def test_applies_only_scoped_managed_location(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx, "--apply")

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            content = config.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# managed-by: amazon-image-generator"))
            self.assertIn("location ^~ /custom-api/amazon-image-generator/", content)
            self.assertIn("proxy_pass http://127.0.0.1:39081/;", content)
            self.assertNotIn("server {", content)
            self.assertTrue(output["nginx_reloaded"])
            self.assertEqual(
                output["verified_health_urls"],
                [self.health_origin + "/custom-api/amazon-image-generator/health"],
            )

    def test_refuses_unmanaged_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            config.write_text("# owned by administrator\n", encoding="utf-8")
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx, "--apply")

            self.assertEqual(result.returncode, 1)
            self.assertIn("unmanaged Nginx file", result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), "# owned by administrator\n")

    def test_failed_nginx_test_rolls_back_new_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            nginx = self.make_nginx(root, test_status=1)

            result = self.run_configurator(config, nginx, "--apply")

            self.assertEqual(result.returncode, 1)
            self.assertIn("rolled back", result.stderr)
            self.assertFalse(config.exists())

    def test_failed_reload_restores_previous_managed_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            previous = (
                "# managed-by: amazon-image-generator\n"
                "location ^~ /custom-api/amazon-image-generator/ {\n"
                "    proxy_pass http://127.0.0.1:39082/;\n"
                "}\n"
            )
            config.write_text(previous, encoding="utf-8")
            nginx = self.make_nginx(root, reload_status=1)

            result = self.run_configurator(config, nginx, "--apply")

            self.assertEqual(result.returncode, 1)
            self.assertIn("reload failed", result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), previous)

    def test_html_fallback_public_route_rolls_back_new_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            nginx = self.make_nginx(root)

            result = self.run_configurator(
                config,
                nginx,
                "--apply",
                "--verify-origin",
                self.html_origin,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("text/html", result.stderr)
            self.assertIn("rolled back", result.stderr)
            self.assertFalse(config.exists())

    def test_refuses_symlink_config_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_config = root / "real.conf"
            real_config.write_text("do not replace\n", encoding="utf-8")
            config = root / "amazon-image-generator.conf"
            config.symlink_to(real_config)
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx, "--apply")

            self.assertEqual(result.returncode, 1)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(real_config.read_text(encoding="utf-8"), "do not replace\n")

    def test_refuses_a_different_config_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "other-module.conf"
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx, "--apply")

            self.assertEqual(result.returncode, 1)
            self.assertIn("must be named amazon-image-generator.conf", result.stderr)
            self.assertFalse(config.exists())

    def test_remove_archives_and_removes_only_managed_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            config.write_text(
                "# managed-by: amazon-image-generator\n"
                "location ^~ /custom-api/amazon-image-generator/ {}\n",
                encoding="utf-8",
            )
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx, "--remove")

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["action"], "remove")
            self.assertFalse(config.exists())
            self.assertTrue(Path(output["backup"]).is_file())
            self.assertTrue(output["nginx_reloaded"])

    def test_remove_refuses_unmanaged_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            config.write_text("# administrator config\n", encoding="utf-8")
            nginx = self.make_nginx(root)

            result = self.run_configurator(config, nginx, "--remove")

            self.assertEqual(result.returncode, 1)
            self.assertIn("Refusing to remove an unmanaged", result.stderr)
            self.assertTrue(config.exists())

    def test_failed_remove_validation_restores_managed_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "amazon-image-generator.conf"
            previous = "# managed-by: amazon-image-generator\nlocation /example {}\n"
            config.write_text(previous, encoding="utf-8")
            nginx = self.make_nginx(root, test_status=1)

            result = self.run_configurator(config, nginx, "--remove")

            self.assertEqual(result.returncode, 1)
            self.assertIn("removal was rolled back", result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), previous)


if __name__ == "__main__":
    unittest.main()
