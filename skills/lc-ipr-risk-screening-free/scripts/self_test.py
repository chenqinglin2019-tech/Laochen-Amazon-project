#!/usr/bin/env python3
"""Offline mock and end-to-end self-test for the independent free-tier skill."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from epo_ops_client import normalize_search, probe as epo_probe
import euipo_client
from euipo_client import normalize as euipo_normalize, probe as euipo_probe
from provider_utils import ProviderError, http_request
from serper_client import normalize as serper_normalize
from rapidapi_uspto_trademark_client import probe as rapid_probe
from serpapi_patents_client import search as serpapi_search
from signa_client import probe as signa_probe
from common import capture_provenance, sha256_json


SCRIPTS = Path(__file__).resolve().parent
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
CDP_PROVENANCE = {
    "browser": "chrome_desktop",
    "capture_transport": "cdp",
    "browser_version": "Chrome/150.0.0.0",
    "protocol_version": "1.3",
    "cdp_session_id": "selftestcdpsession01",
}
MANUAL_PROVENANCE = {
    "browser": "chrome_desktop",
    "capture_transport": "manual",
    "operator_confirmed": True,
}


class MockHandler(BaseHTTPRequestHandler):
    epo_auth_fail = False
    signa_stale = False
    signa_missing = False
    rapid_limited = False
    rapid_paths: list[str] = []
    euipo_token_count = 0
    epo_ranges: list[str] = []

    def log_message(self, *_: object) -> None:
        return

    def send(self, status: int, payload: object, content_type: str = "application/json") -> None:
        if isinstance(payload, bytes):
            body = payload
        elif content_type == "application/json":
            body = json.dumps(payload).encode()
        else:
            body = str(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-RateLimit-Remaining", "99")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if parsed.path == "/epo/auth":
            self.send(401 if self.epo_auth_fail else 200, {"error": "bad"} if self.epo_auth_fail else {"access_token": "mock-epo", "expires_in": 1200})
        elif parsed.path.startswith("/serper/"):
            operation = parsed.path.rsplit("/", 1)[-1]
            key = "images" if operation == "images" else "organic"
            self.send(200, {key: [{"title": f"{operation} result", "link": "https://example.test/result", "snippet": "mock"}]})
        elif parsed.path == "/signa/v1/trademarks":
            self.send(200, {"data": [{"office_code": "uspto", "serial_number": "78787878", "mark_text": "MOCKMARK", "status_stage": "registered", "source_data_date": datetime.now(timezone.utc).date().isoformat(), "image_url": "https://example.test/mark.png"}]})
        elif parsed.path == "/euipo/token":
            type(self).euipo_token_count += 1
            self.send(200, {"access_token": f"euipo-{self.euipo_token_count}", "expires_in": 60})
        else:
            self.send(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path
        if path.startswith("/epo/rest/"):
            type(self).epo_ranges.append(self.headers.get("Range", ""))
            xml = b'<ops:world-patent-data xmlns:ops="ops" xmlns:ex="ex"><ex:exchange-documents><ex:exchange-document country="US" doc-number="1234" kind="A1"/></ex:exchange-documents></ops:world-patent-data>'
            self.send(200, xml, "application/xml")
        elif path == "/serpapi/account.json":
            self.send(200, {"plan_name": "Free", "total_searches_left": 10, "this_month_usage": 1})
        elif path == "/serpapi/search":
            query = params.get("q", [""])[0]
            if query == "schema":
                self.send(200, {"unexpected": []})
            else:
                results = [] if query == "zero" else [{"publication_number": "US1234A1", "title": "Mock patent", "patent_link": "https://patents.google.com/patent/US1234A1/en", "assignee": "Mock Inc"}]
                self.send(200, {"search_metadata": {"status": "Success"}, "organic_results": results, "search_information": {"total_results": len(results)}})
        elif path == "/signa/v1/offices":
            if self.signa_missing:
                self.send(200, {"data": []})
            else:
                sync = datetime.now(timezone.utc) - (timedelta(days=90) if self.signa_stale else timedelta(hours=1))
                self.send(200, {"data": [{"code": "US", "status": "live", "last_synced_at": sync.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "total_marks": 1000}]})
        elif path == "/signa/v1/organization/me":
            self.send(200, {"object": "identity", "plan": "free", "api_key": {"scopes": ["trademarks:read", "billing:read"]}})
        elif path == "/signa/v1/organization/usage":
            self.send(200, {"object": "usage", "by_endpoint_type": {"search": {"used": 10, "limit": 1000}}, "rate_limits": {"search": 60}})
        elif path == "/rapid/v1/databaseStatus":
            self.send(429 if self.rapid_limited else 200, {"status": "limited" if self.rapid_limited else "ok"})
        elif path == "/rapid/v1/trademarkSearch/MOCKMARK/active":
            type(self).rapid_paths.append(path)
            self.send(200, {"count": 1, "items": [{
                "keyword": "MOCKMARK", "registration_number": "1234567", "serial_number": "78787878",
                "status_label": "Live/Registered", "classification": [{"international_code": "035"}],
                "owners": [{"name": "Mock Inc."}],
            }]})
        elif path.startswith("/tsdr/casestatus/sn") and path.endswith("/info.xml"):
            serial = path.split("sn", 1)[1].split("/", 1)[0]
            xml = b"<case></case>" if serial == "00000000" else f"<case><serial>{serial}</serial><status>LIVE</status></case>".encode()
            self.send(200, xml, "application/xml")
        elif path.startswith("/tsdr/rawImage/"):
            self.send(200, PNG, "image/png")
        elif path in {"/euipo/trademark/trademarks", "/euipo/design/designs"}:
            if "design" in path:
                self.send(200, {"content": [{"designNumber": "009999999-0001", "productIndication": "Mouse pad", "views": ["https://example.test/view.png"]}]})
            else:
                self.send(200, {"content": [{"applicationNumber": "018999999", "wordMark": "MOCKMARK", "status": "Registered"}]})
        elif path == "/euipo/trademark/trademarks/018999999":
            self.send(200, {"applicationNumber": "018999999", "wordMark": "MOCKMARK", "status": "Registered", "ownerName": "EU Mock Inc", "image": True})
        elif path == "/euipo/trademark/trademarks/018999999/image":
            self.send(200, PNG, "image/png")
        elif path == "/euipo/design/designs/009999999-0001":
            self.send(200, {"designNumber": "009999999-0001", "productIndication": "Mouse pad", "status": "Registered", "views": [{"order": 1}]})
        elif path == "/euipo/design/designs/009999999-0001/views/1":
            self.send(200, PNG, "image/png")
        elif path == "/euipo/design/designs/000000013-0001":
            self.send(200, {"designNumber": "000000013-0001", "productIndication": "Sandbox fixture", "status": "Registered", "views": [{"order": 1}, {"order": 2}]})
        elif path == "/euipo/design/designs/000000013-0001/views/1":
            self.send(200, PNG, "image/png")
        elif path == "/euipo/design/designs/000000013-0001/views/1/thumbnail":
            self.send(200, PNG, "image/png")
        elif path == "/error429":
            self.send(429, {"error": "quota exhausted"})
        else:
            self.send(404, {"error": "not found"})


def run(*args: str, env: dict[str, str]) -> str:
    result = subprocess.run([sys.executable, *args], text=True, capture_output=True, env=env, check=False)
    if result.returncode:
        raise AssertionError(f"command failed: {' '.join(args)}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""


def review(risk: str, evidence_id: str, reviewer: str, evidence_digest: str, session_id: str) -> dict:
    modules = {}
    for index, module in enumerate(("appearance_patent", "utility_patent", "pending_application", "word_mark", "figurative_trade_dress", "copyright_ip", "enforcement"), 1):
        modules[module] = {"risk": risk, "confidence": "高", "reasoning": f"Mock evidence review for {module}", "findings": [{"finding_id": f"F-{index:03d}", "title": "Mock finding", "evidence_refs": [evidence_id], "recommended_action": "Keep evidence"}]}
    return {"reviewer": reviewer, "review_context": {"session_id": session_id, "evidence_digest": evidence_digest, "first_review_visible": False}, "modules": modules, "compound_escalation": {"enabled": False, "justification": ""}, "review_triggers": {"uncertain_material_status": False, "disputed_class_overlap": False, "incomplete_copyright_provenance": False, "module_conflict": False}, "summary_reasons": ["Mock summary"], "recommended_actions": ["Mock action"]}


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    env = os.environ.copy()
    env.update({
        "LAOCHEN_AUTH_PASSED": "1", "LC_IPR_TEST_MODE": "1", "EPO_OPS_CONSUMER_KEY": "mock", "EPO_OPS_CONSUMER_SECRET": "mock",
        "EPO_OPS_AUTH_URL": f"{base}/epo/auth", "EPO_OPS_BASE_URL": f"{base}/epo/rest",
        "SERPAPI_API_KEY": "mock", "SERPAPI_BASE_URL": f"{base}/serpapi",
        "SERPER_API_KEY": "mock", "SERPER_BASE_URL": f"{base}/serper",
        "SIGNA_API_KEY": "mock", "SIGNA_BASE_URL": f"{base}/signa",
        "RAPIDAPI_KEY": "mock", "RAPIDAPI_USPTO_BASE_URL": f"{base}/rapid",
        "EUIPO_CLIENT_ID": "mock", "EUIPO_CLIENT_SECRET": "mock", "EUIPO_TOKEN_URL": f"{base}/euipo/token",
        "EUIPO_ENVIRONMENT": "production",
        "EUIPO_AUTHORITATIVE_FOR_FINAL_RATING": "1",
        "EUIPO_TRADEMARK_BASE_URL": f"{base}/euipo/trademark", "EUIPO_DESIGN_BASE_URL": f"{base}/euipo/design",
    })
    os.environ.update(env)
    try:
        assert capture_provenance(
            {"browser": "chrome_desktop"}, {"schema_version": "2.1-free"},
            allowed_transports={"cdp"},
        )["capture_transport"] == "legacy"
        assert capture_provenance(
            MANUAL_PROVENANCE, {"schema_version": "2.2-free"},
            allowed_transports={"manual"},
        )["operator_confirmed"] is True
        try:
            capture_provenance(
                {**CDP_PROVENANCE, "cdp_endpoint": "ws://127.0.0.1:9222"},
                {"schema_version": "2.2-free"}, allowed_transports={"cdp"},
            )
            raise AssertionError("Sensitive CDP endpoint was accepted")
        except ValueError:
            pass
        assert epo_probe()["ready"]
        assert len(normalize_search(b'<root><exchange-document country="US" doc-number="1" kind="A1"/><exchange-document country="US" doc-number="2" kind="B2"/></root>')) == 2
        assert serpapi_search({"q": "zero"})[0]["candidates"] == []
        try:
            serpapi_search({"q": "schema"})
            raise AssertionError("SerpApi schema change was not detected")
        except ProviderError as exc:
            assert exc.code == "RESPONSE_SCHEMA_CHANGED"
        signa_coverage = signa_probe(["US"])["coverage"]["US"]
        assert signa_coverage["production"]
        assert signa_coverage["provider_status"] == "live"
        MockHandler.signa_stale = True
        try:
            signa_probe(["US"])
            raise AssertionError("Stale Signa data was not blocked")
        except ProviderError as exc:
            assert exc.code == "SOURCE_DATA_STALE"
        MockHandler.signa_stale = False
        MockHandler.signa_missing = True
        try:
            signa_probe(["US"])
            raise AssertionError("Missing Signa office was not blocked")
        except ProviderError as exc:
            assert exc.code == "COVERAGE_UNVERIFIED"
        MockHandler.signa_missing = False
        assert rapid_probe()["ready"]
        MockHandler.rapid_limited = True
        try:
            rapid_probe()
            raise AssertionError("RapidAPI limit was not detected")
        except ProviderError as exc:
            assert exc.code == "FREE_QUOTA_EXHAUSTED"
        MockHandler.rapid_limited = False
        try:
            http_request(f"{base}/error429", retries=0)
            raise AssertionError("HTTP 429 was not detected")
        except ProviderError as exc:
            assert exc.code == "FREE_QUOTA_EXHAUSTED"
        assert euipo_probe()["coverage"]["design"]["subscribed"]
        os.environ["EUIPO_ENVIRONMENT"] = "sandbox"
        sandbox_design_probe = euipo_probe("design")["coverage"]["design"]
        assert sandbox_design_probe["fixture_design_number"] == "000000013-0001"
        assert sandbox_design_probe["detail_ready"]
        assert sandbox_design_probe["views_ready"]
        assert sandbox_design_probe["thumbnail_ready"]
        assert sandbox_design_probe["view_count"] == 2
        os.environ["EUIPO_ENVIRONMENT"] = "production"
        assert euipo_normalize("trademark", {"content": [{"applicationNumber": "018999999", "wordMark": "MOCKMARK"}]})[0]["official_verification"]["status"] == "not_checked"
        sandbox_shape = euipo_normalize("trademark", {"trademarks": [{
            "applicationNumber": "018888888",
            "wordMarkSpecification": {"verbalElement": "SANDBOX MARK"},
            "applicants": [{"name": "Sandbox Owner"}],
        }]})[0]
        assert sandbox_shape["mark_text"] == "SANDBOX MARK"
        assert sandbox_shape["owner"] == "Sandbox Owner"
        assert serper_normalize("lens", {"organic": [], "visual_matches": [{"title": "visual", "link": "https://example.test/visual"}]})
        patent_result = serper_normalize("patents", {"organic": [{"title": "patent", "link": "https://patents.google.com/patent/US1234567B2/en"}]})[0]
        assert patent_result["publication_number"] == "US1234567B2"
        assert MockHandler.euipo_token_count == 1
        euipo_client._TOKEN_CACHE["expires_at"] = 0.0
        assert euipo_probe()["coverage"]["trademark"]["subscribed"]
        assert MockHandler.euipo_token_count == 2
        MockHandler.epo_auth_fail = True
        try:
            epo_probe()
            raise AssertionError("Expired EPO credentials were not detected")
        except ProviderError as exc:
            assert exc.code == "AUTH_FAILED"
        MockHandler.epo_auth_fail = False

        with tempfile.TemporaryDirectory(prefix="ipr-free-self-test-") as temp:
            root = Path(temp)
            task_dir = root / "run"
            run(str(SCRIPTS / "create_task.py"), "--url", "https://www.amazon.com/dp/B0TEST1234", "--jurisdictions", "US", "--output-dir", str(task_dir), env=env)
            MockHandler.signa_missing = True
            MockHandler.epo_auth_fail = True
            assert run(str(SCRIPTS / "preflight.py"), "--task", str(task_dir / "task.json"), "--phase", "credentials", env=env) == "awaiting_browser"
            # US EPO OPS is a low-risk gate: an unavailable account cannot block
            # higher-risk evidence collection at credential preflight.
            MockHandler.epo_auth_fail = False
            MockHandler.signa_missing = False
            image = task_dir / "images" / "main.png"
            core = task_dir / "screenshots" / "product-core.png"
            details = task_dir / "screenshots" / "product-details.png"
            image.write_bytes(PNG)
            core.write_bytes(PNG)
            details.write_bytes(PNG)
            import hashlib
            digest = hashlib.sha256(PNG).hexdigest()
            capture = {
                **CDP_PROVENANCE,
                "status": "success", "requested_url": "https://www.amazon.com/dp/B0TEST1234", "final_url": "https://www.amazon.com/dp/B0TEST1234",
                "requested_asin": "B0TEST1234", "actual_asin": "B0TEST1234", "variant": {"label": "Color", "value": "Pink", "confirmed": True},
                "title": "Mock Cat Paw Mouse Pad", "brand": "MOCKMARK", "manufacturer": "Mock Inc", "category": "Mouse Pads",
                "bullets": ["Ergonomic wrist support"], "specifications": {"Material": "Silicone"}, "structure": ["cat paw wrist rest"],
                "visible_ip_claims": [], "ocr_text": ["MOCKMARK"], "visual_features": ["pink cat paw silhouette"],
                "main_image": {"path": str(image), "source_url": "https://m.media-amazon.com/images/I/mock.png", "width": 1, "height": 1, "format": "PNG", "sha256": digest},
                "screenshots": {"product_core": str(core), "product_details": str(details)}, "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            capture_path = root / "capture.json"
            write_json(capture_path, capture)
            assert run(str(SCRIPTS / "record_browser_product.py"), "--task-dir", str(task_dir), "--capture", str(capture_path), env=env) == "success"
            evidence_preflight = run(str(SCRIPTS / "preflight.py"), "--task", str(task_dir / "task.json"), "--phase", "evidence", "--cdp-capability-confirmed", env=env)
            assert evidence_preflight == "collecting", (evidence_preflight, json.loads((task_dir / "task.json").read_text()).get("errors"))
            run(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir), env=env)
            search_plan = json.loads((task_dir / "search-plan.json").read_text())
            assert "uspto_tmsearch_browser" in search_plan["queries"]
            assert "signa" in search_plan["queries"]
            assert any(entry.get("type") == "DESIGN" for entry in search_plan["queries"]["serpapi_google_patents"])
            assert search_plan["classification_candidates"]["locarno"]
            assert set(("wipo_patentscope_browser", "epo_ops", "uspto_patent_browser")) <= set(search_plan["queries"])
            assert "espacenet_browser" not in search_plan["queries"]
            browser_hosts = {
                "wipo_patentscope_browser": "patentscope.wipo.int",
                "uspto_patent_browser": "ppubs.uspto.gov",
            }
            for provider, host in browser_hosts.items():
                for index, entry in enumerate(search_plan["queries"][provider]):
                    patent_recall_capture = root / f"{provider}-{index}.json"
                    candidate_found = index == 0
                    write_json(patent_recall_capture, {
                        **(MANUAL_PROVENANCE if provider == "wipo_patentscope_browser" else CDP_PROVENANCE),
                        "status": "success" if candidate_found else "no_result", "query": entry["q"],
                        "mode": entry["mode"],
                        "final_url": f"https://{host}/search?q={entry['q']}",
                        "candidates": ([{"publication_number": "US1234A1", "title": "Mock patent", "assignee": "Mock Inc", "jurisdiction": "US"}] if candidate_found else []),
                        "result_message": "No matching patents" if not candidate_found else "",
                        "screenshot_path": str(details), "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    })
                    expected_status = "success" if candidate_found else "no_result"
                    assert run(str(SCRIPTS / "record_patent_browser_recall.py"), "--task-dir", str(task_dir), "--provider", provider, "--capture", str(patent_recall_capture), env=env) == expected_status
            for entry in search_plan["queries"]["uspto_tmsearch_browser"]:
                strategy, query = entry["strategy"], entry["q"]
                candidate_found = query == "MOCKMARK" and strategy == "exact"
                tm_screenshot = task_dir / "screenshots" / f"tmsearch-{strategy}-{query.casefold().replace(' ', '-')}.png"
                tm_screenshot.write_bytes(PNG)
                tmsearch_capture = root / f"main-tmsearch-{strategy}-{query.casefold().replace(' ', '-')}.json"
                write_json(tmsearch_capture, {
                    **CDP_PROVENANCE,
                    "status": "success" if candidate_found else "no_result", "query": query, "strategy": strategy,
                    "rendered_query": f"{strategy}:{query}",
                    "final_url": "https://tmsearch.uspto.gov/search/search-results", "candidates": ([{
                        "serial_number": "78787878", "registration_number": "1234567", "mark_text": "MOCKMARK",
                        "owner": "Mock Inc", "status": "LIVE", "nice_classes": ["035"], "goods_services": ["Mouse pads"],
                    }] if candidate_found else []), "result_message": "No matching marks" if not candidate_found else "",
                    "screenshot_path": str(tm_screenshot), "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                })
                expected_status = "success" if candidate_found else "no_result"
                assert run(str(SCRIPTS / "record_uspto_tmsearch_browser_result.py"), "--task-dir", str(task_dir), "--capture", str(tmsearch_capture), env=env) == expected_status
            run(str(SCRIPTS / "run_api_plan.py"), "--task-dir", str(task_dir), "--wave", "1", env=env)
            api_evidence = json.loads((task_dir / "evidence.json").read_text())
            serpapi_runs = [item for item in api_evidence["source_runs"] if item.get("provider") == "serpapi_google_patents" and item.get("operation") == "search"]
            assert len({tuple(item.get("raw_paths", [])) for item in serpapi_runs}) == len(serpapi_runs), "SerpApi request variants overwrote raw evidence"
            assert run(str(SCRIPTS / "epo_ops_client.py"), "--task-dir", str(task_dir), "--query", "mouse pad", "--jurisdiction", "US", env=env) == "success"
            assert "1-25" in MockHandler.epo_ranges
            assert run(str(SCRIPTS / "signa_client.py"), "--task-dir", str(task_dir), "--query", "MOCKMARK", "--jurisdiction", "US", env=env) == "success"
            assert run(str(SCRIPTS / "rapidapi_uspto_trademark_client.py"), "--task-dir", str(task_dir), "--query", "MOCKMARK", env=env) == "success"
            assert run(str(SCRIPTS / "euipo_client.py"), "trademark", "--task-dir", str(task_dir), "--query", "MOCKMARK", env=env) == "success"
            assert run(str(SCRIPTS / "euipo_client.py"), "trademark", "--task-dir", str(task_dir), "--query", "018999999", "--identifier", "018999999", "--verify", env=env) == "success"
            assert run(str(SCRIPTS / "euipo_client.py"), "design", "--task-dir", str(task_dir), "--query", "009999999-0001", "--identifier", "009999999-0001", "--verify", env=env) == "success"
            rapid_entry = [entry for entry in json.loads((task_dir / "evidence.json").read_text())["collections"]["trademarks"] if entry["provider"] == "rapidapi_uspto_trademark"][-1]
            rapid_candidate = rapid_entry["payload"]["candidates"][0]
            assert MockHandler.rapid_paths[-1] == "/rapid/v1/trademarkSearch/MOCKMARK/active"
            assert rapid_candidate["mark_text"] == "MOCKMARK"
            assert rapid_candidate["nice_classes"] == ["035"]
            assert rapid_candidate["owner"] == "Mock Inc."
            tsdr_capture = root / "main-tsdr-chrome.json"
            write_json(tsdr_capture, {
                **CDP_PROVENANCE,
                "status": "success", "serial_number": "78787878", "page_case_number": "78787878",
                "final_url": "https://tsdr.uspto.gov/#caseNumber=78787878&caseSearchType=US_APPLICATION",
                "case_status": "LIVE", "owners": ["Mock Inc"], "goods_services": ["Mouse pads"],
                "mark_text": "MOCKMARK", "registration_number": "1234567",
                "screenshot_path": str(core), "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            })
            assert run(str(SCRIPTS / "record_tsdr_browser_verification.py"), "--task-dir", str(task_dir), "--capture", str(tsdr_capture), env=env) == "success"
            patent_capture = root / "main-uspto-patent-chrome.json"
            write_json(patent_capture, {
                **CDP_PROVENANCE,
                "status": "success", "record_number": "US1234A1", "page_record_number": "US1234A1",
                "publication_number": "US1234A1", "title": "Mock patent", "legal_status": "Published application",
                "owners": ["Mock Inc"], "final_url": "https://ppubs.uspto.gov/basic/?query=US1234A1",
                "screenshot_path": str(details), "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            })
            assert run(str(SCRIPTS / "record_uspto_patent_chrome_verification.py"), "--task-dir", str(task_dir), "--capture", str(patent_capture), env=env) == "success"
            run(str(SCRIPTS / "blacklist_check.py"), "--task-dir", str(task_dir), env=env)
            run(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(task_dir), env=env)
            candidates = json.loads((task_dir / "normalized-candidates.json").read_text())
            assert len(candidates["patents"]) == 1, candidates["patents"]
            assert any(item.get("serial_number") == "78787878" for item in candidates["trademarks"]), candidates["trademarks"]
            assert any(item.get("application_number") == "018999999" and item.get("official_verification", {}).get("status") == "verified" for item in candidates["trademarks"])
            evidence = json.loads((task_dir / "evidence.json").read_text())
            evidence_id = evidence["collections"]["browser"][0]["evidence_id"]
            review_digest = sha256_json({"evidence": evidence, "candidates": candidates})
            low = root / "low.json"
            high = root / "high.json"
            high2 = root / "high2.json"
            low2 = root / "low2.json"
            write_json(low, review("低", evidence_id, "independent-review-1", review_digest, "session-low-1"))
            write_json(high, review("高", evidence_id, "independent-review-1", review_digest, "session-high-1"))
            write_json(high2, review("高", evidence_id, "independent-review-2", review_digest, "session-high-2"))
            write_json(low2, review("低", evidence_id, "independent-review-2", review_digest, "session-low-2"))
            assert run(str(SCRIPTS / "finalize_assessment.py"), "--task-dir", str(task_dir), "--first-review", str(low), env=env) == "completed"
            assessment = json.loads((task_dir / "assessment.json").read_text())
            assert assessment["overall"]["risk"] == "低"
            design_evidence = task_dir / "screenshots" / "uspto-design-mock-drawing.png"
            design_evidence.write_bytes(PNG)
            run(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir), env=env)
            report_manifest = json.loads((task_dir / "report-manifest.json").read_text())
            assert any(Path(item["path"]).name == design_evidence.name and item["label"] == "USPTO 专利图样证据" for item in report_manifest["key_evidence"])
            assert "IPR-EVIDENCE-DOSSIER/1.0" in (task_dir / "report.html").read_text()
            assert run(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), env=env) == "run valid"
            legacy_files = (
                "task.json", "evidence.json", "assessment.json",
                "search-plan.json", "normalized-candidates.json",
            )
            current_payloads = {
                name: json.loads((task_dir / name).read_text())
                for name in legacy_files
            }
            for name, payload in current_payloads.items():
                legacy_payload = json.loads(json.dumps(payload))
                legacy_payload["schema_version"] = "2.1-free"
                write_json(task_dir / name, legacy_payload)
            run(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir), env=env)
            assert run(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), env=env) == "run valid"
            for name, payload in current_payloads.items():
                write_json(task_dir / name, payload)
            run(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir), env=env)
            assert run(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), env=env) == "run valid"
            complete_evidence = json.loads(json.dumps(evidence))
            evidence["source_runs"] = [run_item for run_item in evidence["source_runs"] if not (
                run_item.get("provider") == "wipo_patentscope_browser" and run_item.get("operation") == "patent_recall"
            )]
            write_json(task_dir / "evidence.json", evidence)
            changed_digest = sha256_json({"evidence": evidence, "candidates": candidates})
            write_json(low, review("低", evidence_id, "independent-review-1", changed_digest, "session-low-wipo-gap"))
            assert run(str(SCRIPTS / "finalize_assessment.py"), "--task-dir", str(task_dir), "--first-review", str(low), env=env) == "completed"
            assessment = json.loads((task_dir / "assessment.json").read_text())
            assert assessment["overall"]["risk"] == "中"
            assert "wipo_patentscope_browser" in assessment["coverage"]["missing_low_risk_gate_sources"]
            write_json(task_dir / "evidence.json", complete_evidence)
            evidence = complete_evidence
            write_json(low, review("低", evidence_id, "independent-review-1", review_digest, "session-low-1"))
            assert run(str(SCRIPTS / "finalize_assessment.py"), "--task-dir", str(task_dir), "--first-review", str(high), env=env) == "needs_review"
            assert run(str(SCRIPTS / "finalize_assessment.py"), "--task-dir", str(task_dir), "--first-review", str(high), "--second-review", str(high2), env=env) == "completed"
            assert run(str(SCRIPTS / "finalize_assessment.py"), "--task-dir", str(task_dir), "--first-review", str(high), "--second-review", str(low2), env=env) == "needs_review"
            evidence["source_runs"] = [run_item for run_item in evidence["source_runs"] if not (
                run_item.get("provider") == "uspto_tmsearch_browser" and run_item.get("query") == "prefix:MOCKMARK"
            )]
            write_json(task_dir / "evidence.json", evidence)
            changed_digest = sha256_json({"evidence": evidence, "candidates": candidates})
            write_json(low, review("低", evidence_id, "independent-review-1", changed_digest, "session-low-tm-gap"))
            assert run(str(SCRIPTS / "finalize_assessment.py"), "--task-dir", str(task_dir), "--first-review", str(low), env=env) == "incomplete"
            assessment = json.loads((task_dir / "assessment.json").read_text())
            assert any(value.startswith("uspto_tmsearch_browser:") for value in assessment["coverage"]["missing_required_queries"])
            run(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir), env=env)
            assert run(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), env=env) == "run valid"

            browser_env = env.copy()
            browser_tsdr_dir = root / "browser-tsdr"
            run(str(SCRIPTS / "create_task.py"), "--url", "https://www.amazon.com/dp/B0TSDR1234", "--jurisdictions", "US", "--output-dir", str(browser_tsdr_dir), env=browser_env)
            assert run(str(SCRIPTS / "preflight.py"), "--task", str(browser_tsdr_dir / "task.json"), "--phase", "credentials", env=browser_env) == "awaiting_browser"
            browser_tsdr_task = json.loads((browser_tsdr_dir / "task.json").read_text())
            assert browser_tsdr_task["checkpoints"]["tsdr_route"]["status"] == "chrome_desktop_cdp_required"
            browser_tsdr_evidence = json.loads((browser_tsdr_dir / "evidence.json").read_text())
            assert any(
                item.get("provider") == "uspto_tsdr" and item.get("operation") == "api_preflight"
                and item.get("status") == "not_applicable"
                for item in browser_tsdr_evidence["source_runs"]
            )
            tsdr_screenshot = browser_tsdr_dir / "screenshots" / "tsdr-78787878.png"
            tsdr_mark = browser_tsdr_dir / "images" / "tsdr-mark-78787878.png"
            tsdr_screenshot.write_bytes(PNG)
            tsdr_mark.write_bytes(PNG)
            tsdr_capture = root / "tsdr-browser-success.json"
            write_json(tsdr_capture, {
                **CDP_PROVENANCE,
                "status": "success", "serial_number": "78787878", "page_case_number": "78787878",
                "final_url": "https://tsdr.uspto.gov/#caseNumber=78787878&caseSearchType=US_APPLICATION",
                "case_status": "LIVE", "owners": ["Mock Inc"], "goods_services": ["Mouse pads"],
                "mark_text": "MOCKMARK", "registration_number": "1234567",
                "screenshot_path": str(tsdr_screenshot), "mark_image_path": str(tsdr_mark),
                "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            })
            assert run(str(SCRIPTS / "record_tsdr_browser_verification.py"), "--task-dir", str(browser_tsdr_dir), "--capture", str(tsdr_capture), env=browser_env) == "success"
            browser_tsdr_evidence = json.loads((browser_tsdr_dir / "evidence.json").read_text())
            browser_verification = browser_tsdr_evidence["collections"]["official_verifications"][-1]["payload"]
            assert browser_verification["official_verification"]["method"] == "chrome_desktop"
            assert browser_verification["capture_transport"] == "cdp"
            assert browser_verification["browser_evidence"]["screenshot_sha256"] == digest
            assert run(str(SCRIPTS / "signa_client.py"), "--task-dir", str(browser_tsdr_dir), "--query", "MOCKMARK", "--jurisdiction", "US", env=browser_env) == "success"
            assert run(str(SCRIPTS / "rapidapi_uspto_trademark_client.py"), "--task-dir", str(browser_tsdr_dir), "--query", "MOCKMARK", env=browser_env) == "success"
            run(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(browser_tsdr_dir), env=browser_env)
            browser_candidates = json.loads((browser_tsdr_dir / "normalized-candidates.json").read_text())
            assert browser_candidates["trademarks"][0]["official_verification"]["status"] == "verified"
            assert browser_candidates["trademarks"][0]["official_verification"]["method"] == "chrome_desktop"

            blocked_tsdr_dir = root / "blocked-tsdr"
            run(str(SCRIPTS / "create_task.py"), "--url", "https://www.amazon.com/dp/B0TSDR5678", "--jurisdictions", "US", "--output-dir", str(blocked_tsdr_dir), env=browser_env)
            run(str(SCRIPTS / "preflight.py"), "--task", str(blocked_tsdr_dir / "task.json"), "--phase", "credentials", env=browser_env)
            blocked_screenshot = blocked_tsdr_dir / "screenshots" / "tsdr-87654321.png"
            blocked_screenshot.write_bytes(PNG)
            blocked_capture = root / "tsdr-browser-blocked.json"
            write_json(blocked_capture, {
                **CDP_PROVENANCE,
                "status": "access_limited", "serial_number": "87654321", "page_case_number": "87654321",
                "final_url": "https://tsdr.uspto.gov/#caseNumber=87654321&caseSearchType=US_APPLICATION",
                "screenshot_path": str(blocked_screenshot), "detail": "Official page could not be confirmed",
                "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            })
            assert run(str(SCRIPTS / "record_tsdr_browser_verification.py"), "--task-dir", str(blocked_tsdr_dir), "--capture", str(blocked_capture), env=browser_env) == "access_limited"
            blocked_task = json.loads((blocked_tsdr_dir / "task.json").read_text())
            assert blocked_task["state"] == "incomplete"
            assert any(gap.get("provider") == "uspto_tsdr" and gap.get("mandatory") for gap in blocked_task["coverage_gaps"])

            robot_dir = root / "robot"
            run(str(SCRIPTS / "create_task.py"), "--url", "https://www.amazon.com/dp/B0ROBOT123", "--jurisdictions", "US", "--output-dir", str(robot_dir), env=env)
            run(str(SCRIPTS / "preflight.py"), "--task", str(robot_dir / "task.json"), "--phase", "credentials", env=env)
            robot_capture = root / "robot-capture.json"
            write_json(robot_capture, {**CDP_PROVENANCE, "status": "robot_check", "requested_url": "https://www.amazon.com/dp/B0ROBOT123", "final_url": "https://www.amazon.com/errors/validateCaptcha"})
            assert run(str(SCRIPTS / "record_browser_product.py"), "--task-dir", str(robot_dir), "--capture", str(robot_capture), env=env) == "needs_user_action"

            mismatch_dir = root / "mismatch"
            run(str(SCRIPTS / "create_task.py"), "--url", "https://www.amazon.com/dp/B0MATCH123", "--jurisdictions", "US", "--output-dir", str(mismatch_dir), env=env)
            run(str(SCRIPTS / "preflight.py"), "--task", str(mismatch_dir / "task.json"), "--phase", "credentials", env=env)
            mismatch_capture = root / "mismatch-capture.json"
            write_json(mismatch_capture, {**CDP_PROVENANCE, "status": "success", "actual_asin": "B0OTHER123", "variant": {"confirmed": True}})
            assert run(str(SCRIPTS / "record_browser_product.py"), "--task-dir", str(mismatch_dir), "--capture", str(mismatch_capture), env=env) == "incomplete"
            mismatch_task = json.loads((mismatch_dir / "task.json").read_text())
            assert mismatch_task["errors"][-1]["code"] == "AMAZON_ASIN_MISMATCH"

            missing_image_dir = root / "missing-image"
            run(str(SCRIPTS / "create_task.py"), "--url", "https://www.amazon.com/dp/B0IMAGE123", "--jurisdictions", "US", "--output-dir", str(missing_image_dir), env=env)
            run(str(SCRIPTS / "preflight.py"), "--task", str(missing_image_dir / "task.json"), "--phase", "credentials", env=env)
            missing_image_capture = root / "missing-image-capture.json"
            write_json(missing_image_capture, {**CDP_PROVENANCE, "status": "success", "requested_url": "https://www.amazon.com/dp/B0IMAGE123", "final_url": "https://www.amazon.com/dp/B0IMAGE123", "actual_asin": "B0IMAGE123", "variant": {"confirmed": True}, "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")})
            assert run(str(SCRIPTS / "record_browser_product.py"), "--task-dir", str(missing_image_dir), "--capture", str(missing_image_capture), env=env) == "incomplete"
            missing_image_task = json.loads((missing_image_dir / "task.json").read_text())
            assert missing_image_task["errors"][-1]["code"] == "MAIN_IMAGE_UNAVAILABLE"
        print("self-test passed")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
