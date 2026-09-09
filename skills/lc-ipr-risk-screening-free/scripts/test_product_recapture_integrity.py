"""Offline recapture preserves original evidence, not merely analysis values."""
import base64
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common import atomic_write_json, load_json, now_iso, sha256_file
from workflow_v24 import product_identity_digest
from record_browser_product import merge_captured_product
from decision_workflow import scoped_product_content


class ProductRecaptureIntegrityTests(unittest.TestCase):
    def test_byline_metadata_survives_ingestion_without_stale_placeholder(self):
        task = {"product": {}}
        capture = {"actual_asin": "B000000001", "variant": {}, "brand": "Generic",
                   "brand_byline_raw": "Brand: Generic", "brand_placeholder": True}
        merge_captured_product(task, capture, [])
        self.assertEqual(task["product"]["brand_byline_raw"], "Brand: Generic")
        self.assertIs(task["product"]["brand_placeholder"], True)
        merge_captured_product(task, {"actual_asin": "B000000001", "variant": {}, "brand": "Example"}, [])
        self.assertNotIn("brand_placeholder", task["product"])
        self.assertNotIn("brand_byline_raw", task["product"])

    def test_byline_metadata_rejects_non_boolean_placeholder(self):
        with self.assertRaisesRegex(ValueError, "brand_placeholder has an invalid type"):
            merge_captured_product({"product": {}}, {"variant": {}, "brand_placeholder": "false"}, [])

    def test_new_placeholder_fact_reopens_analysis_and_only_mark_scope(self):
        task = {"schema_version": "2.4-free", "screening_revision": "recall-integrity-v1",
                "workflow_correction_revision": "workflow-correction-v1",
                "decision_workflow_revision": "scenario-triage-v1", "product": {}}
        capture = {"actual_asin": "B000000001", "variant": {}, "brand": "Generic"}
        merge_captured_product(task, capture, [])
        task["product"]["analysis"] = {"status": "confirmed",
            "identity_sha256": product_identity_digest(task["product"], task=task)}
        old_mark = scoped_product_content(task, None, "trademark_word")
        old_structure = scoped_product_content(task, None, "patent")
        merge_captured_product(task, {**capture, "brand_byline_raw": "Brand: Generic", "brand_placeholder": True}, [])
        self.assertEqual(task["product"]["analysis"]["status"], "stale")
        self.assertNotEqual(old_mark, scoped_product_content(task, None, "trademark_word"))
        self.assertEqual(old_structure, scoped_product_content(task, None, "patent"))

    def test_recapture_is_append_only_and_identical_capture_is_idempotent(self):
        scripts = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run([sys.executable, str(scripts / "create_task.py"), "--url",
                "https://www.amazon.com/dp/B000000001", "--jurisdictions", "US", "--output-dir", str(root)],
                check=True, capture_output=True)
            task = load_json(root / "task.json")
            task["state"] = "awaiting_browser"
            atomic_write_json(root / "task.json", task)
            png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII=")
            media = root / "images" / "main.png"
            media.write_bytes(png)
            captures = []
            for round_number in (1, 2):
                screenshots = {}
                for role in ("product_core", "product_details"):
                    screenshot = root / "screenshots" / f"{role}-{round_number}.png"
                    screenshot.write_bytes(png)
                    screenshots[role] = str(screenshot)
                capture = {"browser": "chrome_desktop", "capture_transport": "cdp", "browser_version": "offline-fixture",
                    "protocol_version": "1.3", "cdp_session_id": "offline-fixture-session", "status": "success",
                    "requested_url": "https://www.amazon.com/dp/B000000001", "final_url": "https://www.amazon.com/dp/B000000001",
                    "actual_asin": "B000000001", "variant": {"label": "Color", "value": "Blue", "confirmed": True},
                    "title": "Example lid strap", "brand": "Example", "brand_byline_raw": "Visit the Example Store",
                    "brand_placeholder": False, "category": "Kitchen", "bullets": ["Silicone lid strap"],
                    "collected_at": now_iso(), "screenshots": screenshots, "main_image": {"path": str(media),
                    "source_url": "https://m.media-amazon.com/images/I/offline-fixture.png", "sha256": sha256_file(media),
                    "width": 1, "height": 1, "format": "PNG"}}
                path = root / f"input-{round_number}.json"
                atomic_write_json(path, capture)
                captures.append(path)

            def record(path):
                process = subprocess.run([sys.executable, str(scripts / "record_browser_product.py"), "--task-dir", str(root),
                    "--capture", str(path)], check=True, capture_output=True, text=True)
                self.assertEqual(process.stdout.strip(), "success")

            record(captures[0])
            captured_product = load_json(root / "task.json")["product"]
            self.assertEqual(captured_product["raw_capture"]["brand_byline_raw"], "Visit the Example Store")
            self.assertIs(captured_product["raw_capture"]["brand_placeholder"], False)
            evidence = load_json(root / "evidence.json")
            retained_run = deepcopy(evidence["source_runs"][0])
            retained_entry = deepcopy(evidence["collections"]["product"][0])
            retained_raw = Path(retained_run["raw_paths"][0]).read_bytes()
            task = load_json(root / "task.json")
            task["state"] = "collecting"
            task["product"]["structure"] = ["Flexible strap"]
            task["query_terms"] = [{"value": "lid AND strap", "kind": "design", "language": "en", "derived_from": "product.structure[0]"}]
            task["product"]["analysis"] = {"status": "confirmed", "identity_sha256": product_identity_digest(task["product"], task=task)}
            atomic_write_json(root / "task.json", task)
            record(captures[1])
            result = load_json(root / "evidence.json")
            self.assertEqual(len(result["source_runs"]), 2)
            self.assertEqual(len(result["collections"]["product"]), 2)
            self.assertEqual(result["source_runs"][0], retained_run)
            self.assertEqual(result["collections"]["product"][0], retained_entry)
            self.assertEqual(Path(retained_run["raw_paths"][0]).read_bytes(), retained_raw)
            self.assertEqual(load_json(root / "task.json")["product"]["analysis"]["status"], "confirmed")
            record(captures[1])
            self.assertEqual(load_json(root / "evidence.json"), result)


if __name__ == "__main__":
    unittest.main()
