"""Loopback-only fake authorization service; no production credentials or bypass flags."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

TEST_TOKEN = "local-compliance-test-token"


@contextmanager
def auth_server():
    state = {"allowed": True, "reason": "permission_enabled", "status": 200, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            state["requests"].append((self.path, data))
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"allowed": state["allowed"], "reason": state["reason"]}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def configure_local(skill, state):
    (skill / "config.local.json").write_text(json.dumps({"backend_url": state["url"],
                                                       "backend_token": TEST_TOKEN}), encoding="utf-8")
    # Override any inherited real credential for every subprocess.
    return {**os.environ, "LAOCHEN_BACKEND_TOKEN": TEST_TOKEN, "PYTHONDONTWRITEBYTECODE": "1"}
