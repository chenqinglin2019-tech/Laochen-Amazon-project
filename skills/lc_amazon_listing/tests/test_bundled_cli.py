"""Real bundled CLI compatibility against a local HTTP stub; never cloud data."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from test_backend_cli import backend


class BundledCLITests(unittest.TestCase):
    def setUp(self):
        try:
            self.cli = backend.select_cli()
        except backend.BackendError:
            self.skipTest("No bundled binary for current OS/architecture")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.requests = []
        self.qa = {"status": "completed", "site": "US", "qa_pairs": [
            {"keyword": "pen holder", "source": "synthetic-loopback", "questions": ["What is included?"]}]}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append({"path": self.path, "payload": payload,
                                       "auth_matches": self.headers.get("Authorization") == "Bearer synthetic-loopback-only"})
                result = owner.qa if self.path == "/listing-v2/qa" else {"ok": True, "errors": []}
                raw = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def close():
            server.shutdown(); server.server_close(); worker.join(timeout=2)

        self.addCleanup(close)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"backend_url": "http://127.0.0.1:%d" % server.server_port,
                                           "backend_token": "synthetic-loopback-only"}), encoding="utf-8")

    def test_us_qa_sends_title_candidates_and_reads_full_result(self):
        source = self.root / "keywords.json"
        source.write_text(json.dumps({"title_keywords": {"high": ["pen holder"], "relevant": []},
                                      "protected_terms": ["pen holder"], "placement_plan": []}), encoding="utf-8")
        result = backend.run_cli("qa", site="US", config=self.config, keywords_file=source,
                                 output=self.root / "qa.json", cli=self.cli, timeout=10)
        self.assertNotIn("failure_reason", result, result)
        self.assertEqual(result["response"], self.qa)
        self.assertEqual(self.requests, [{"path": "/listing-v2/qa", "payload": {"keywords": ["pen holder"], "site": "US"}, "auth_matches": True}])

    def test_non_us_validate_keeps_site_and_single_product_payload(self):
        source = self.root / "listing.json"
        listing = {"title": "Stiftehalter", "item_highlight": "Für den Schreibtisch", "bullets": ["A"] * 5,
                   "description": "Stiftehalter", "search_terms": "stifte organiser"}
        source.write_text(json.dumps(listing), encoding="utf-8")
        result = backend.run_cli("validate", site="DE", config=self.config, listing_file=source,
                                 cli=self.cli, timeout=10)
        self.assertNotIn("failure_reason", result, result)
        self.assertEqual(result["response"], {"ok": True, "errors": []})
        self.assertEqual(self.requests, [{"path": "/listing-v2/validate", "payload": {"listing": listing, "site": "DE"}, "auth_matches": True}])


if __name__ == "__main__":
    unittest.main()
