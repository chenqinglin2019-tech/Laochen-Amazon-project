"""Published examples must work through the real local CLI, without network."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublishedExamplesWorkflowTests(unittest.TestCase):
    def test_every_published_example_normalizes_projects_and_renders(self):
        case_count = 0
        strategies = set()
        for source in sorted((ROOT / "knowledge/examples").glob("*.json")):
            for case in json.loads(source.read_text(encoding="utf-8"))["examples"]:
                case_count += 1
                strategies.add(case["good_listing"]["media_strategy"])
                with self.subTest(case=case["case_id"]), tempfile.TemporaryDirectory() as directory:
                    run = Path(directory)
                    profile_file = run / "01_product_profile.json"
                    listing_file = run / "07_listing.json"
                    for path, value in ((profile_file, case["input_profile"]),
                                        (listing_file, case["good_listing"])):
                        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                    quality = [sys.executable, str(ROOT / "scripts/listing_quality.py")]
                    process = subprocess.run(quality + ["normalize", "--profile", str(profile_file),
                                                        "--output", str(profile_file)], capture_output=True, text=True)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    inputs = ["--profile", str(profile_file), "--listing", str(listing_file)]
                    process = subprocess.run(quality + ["check"] + inputs + ["--output", str(run / "08_validation.json")],
                                             capture_output=True, text=True)
                    self.assertEqual(process.returncode, 1)  # Missing evidence is never a pass.
                    result = json.loads((run / "08_validation.json").read_text())
                    self.assertEqual(result["local"]["status"], "passed", result["issues"])
                    self.assertEqual(result["status"], "incomplete")
                    process = subprocess.run(quality + ["prepare"] + inputs + ["--output-dir", str(run / "payloads")],
                                             capture_output=True, text=True)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    manifest = json.loads((run / "payloads/manifest.json").read_text())
                    normalized = json.loads(profile_file.read_text())
                    expected_ids = ([v["variant_id"] for v in normalized["variants"]]
                                    if normalized["listing_mode"] == "family" else ["single"])
                    self.assertEqual([record["target"] for record in manifest["records"]], expected_ids)
                    for record in manifest["records"]:
                        payload = json.loads((run / "payloads" / record["filename"]).read_text())
                        self.assertIsInstance(payload["item_highlight"], str)
                        self.assertNotIn("parent", payload)
                        self.assertNotIn("variants", payload)
                    process = subprocess.run([sys.executable, str(ROOT / "scripts/render_listing.py"),
                                              "--run-dir", str(run)], capture_output=True, text=True)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(json.loads(process.stdout)["validation_status"], "incomplete")
                    markdown = (run / "07_listing.md").read_text(encoding="utf-8")
                    report = (run / "report.html").read_text(encoding="utf-8")
                    self.assertIn("尚未完成验收", report)
                    self.assertNotIn("尚未完成验收", markdown)
                    for internal in ("```json", '"claims"', '"fingerprints"', "## 产品画像", "声明引用"):
                        self.assertNotIn(internal, markdown)
                    for heading in ("## 附图策划", "## A+ 整体策划", "## 买家问题覆盖清单"):
                        self.assertIn(heading, markdown)
                    self.assertIn("图7", markdown)
                    self.assertIn("模块5", markdown)
                    self.assertIn("- 【", markdown)
                    self.assertTrue(listing_file.exists())
                    self.assertFalse((run / "文案预览.md").exists())
                    self.assertFalse((run / "文案预览.html").exists())
                    if expected_ids != ["single"]:
                        self.assertEqual(markdown.count("## 子体 "), len(expected_ids))
                        self.assertTrue(markdown.startswith("## 父体\n"))
                        for number, child_id in enumerate(expected_ids, 1):
                            self.assertIn(child_id.replace("_", "\\_"), markdown)
                            self.assertIn('id="variant-copy-%d"' % number, report)
                            self.assertIn('id="variant-images-%d"' % number, report)
                            self.assertNotIn('href="#variant-copy-%d"' % number, report)
                    else:
                        headings = [line for line in markdown.splitlines() if line.startswith("## ")]
                        self.assertEqual(headings, ["## Title", "## Item Highlight", "## Bullet Points",
                                                   "## Description", "## Search Terms", "## 附图策划",
                                                   "## A+ 整体策划", "## 买家问题覆盖清单"])
        self.assertGreaterEqual(case_count, 6)
        self.assertEqual(strategies, {"single", "per_variant_full", "shared_secondary"})


if __name__ == "__main__":
    unittest.main()
