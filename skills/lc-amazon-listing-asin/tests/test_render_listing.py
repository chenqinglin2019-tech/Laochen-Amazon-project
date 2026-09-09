"""Offline renderer regression cases; no backend credentials or network required."""

import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("render_listing", ROOT / "scripts/render_listing.py")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values, self.current = {}, None
        self.tags = []
        self.visible = []
        self.raw_tag = None

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag in ("script", "style"):
            self.raw_tag = tag
        if tag == "script":
            self.current = dict(attrs).get("id")
            if self.current:
                self.values[self.current] = ""

    def handle_endtag(self, tag):
        if tag == self.raw_tag:
            self.raw_tag = None
        if tag == "script":
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.values[self.current] += data
        if self.raw_tag is None:
            self.visible.append(data)


class RenderListingTests(unittest.TestCase):
    def setUp(self):
        self.real_local_check = renderer.current_local_issues
        self.real_keyword_check = renderer.current_keyword_stage
        patcher = patch.object(renderer, "current_local_issues", return_value=[])
        self.local_check = patcher.start()
        self.addCleanup(patcher.stop)
        keyword_patcher = patch.object(renderer, "current_keyword_stage", return_value={"status": "passed", "issues": []})
        self.keyword_check = keyword_patcher.start()
        self.addCleanup(keyword_patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.profile = {"site": "US", "category": "Ghost Night Light", "materials": ["resin"]}
        self.listing = {
            "title": "Ghost Night Light", "item_highlight": "Warm campfire glow",
            "bullets": [f"Bullet {i}" for i in range(1, 6)],
            "description": "First paragraph.\n\nSecond paragraph.", "search_terms": "halloween seasonal",
            "image_plan": [{"image": "图1", "direction": "白底实际产品"}],
            "a_plus_plan": [{"module": "Legacy A+", "direction": "保留旧字段"}],
        }
        self.write("01_product_profile.json", self.profile)
        self.write("07_listing.json", self.listing)

    def write(self, name, value):
        (self.run / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def modern_media(self):
        self.profile["schema_version"] = "2.1"
        self.listing["schema_version"] = "2.1"
        self.listing["media_strategy"] = "single"
        self.listing["image_plan"] = [{"plan_id": f"shared-{i}", "role": "main" if i == 1 else "secondary", "image": f"图{i}（主图）" if i == 1 else f"图{i}（附图）", "direction": f"共用画面 {i}", "applies_to": ["all"]} for i in range(1, 8)]
        self.listing.pop("aplus_plan", None)
        self.listing["a_plus_plan"] = [{"plan_id": f"a-plus-{i}", "role": "aplus", "asset_type": "image", "module": f"模块{i}：主题", "direction": f"A+ 画面 {i}", "applies_to": ["all"]} for i in range(1, 6)]
        self.listing["image_sets"] = {"shared": {"main": "shared-1", "secondary": [f"shared-{i}" for i in range(2, 8)], "a_plus": [f"a-plus-{i}" for i in range(1, 6)]}, "variants": []}
        self.write("01_product_profile.json", self.profile)
        self.write("07_listing.json", self.listing)

    def passed(self, legacy=False, **changes):
        if not legacy and self.listing.get("listing_mode", "single") == "single" and "image_sets" not in self.listing:
            self.modern_media()
        evidence = {"review": {"checks": [{"target": "single", "status": "pass", "evidence": "已复审"}]},
                    "backend": {"records": [{"target": "single", "exit_code": 0, "response": {"ok": True, "errors": []}}]}}
        evidence_fingerprints = {}
        for key, value in evidence.items():
            filename = "08_semantic_review.json" if key == "review" else "08_backend_validation.json"
            self.write(filename, value)
            canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            evidence_fingerprints[key + "_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        evidence_fingerprints["keywords_sha256"] = renderer.canonical_fingerprint(self.keyword_check.return_value)
        fingerprints = {}
        for key, filename in (("profile", "01_product_profile.json"), ("listing", "07_listing.json"), ("qa", "06_qa.json")):
            path = self.run / filename
            fingerprints[key + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        record = {"status": "passed", "fingerprints": fingerprints, "evidence_fingerprints": evidence_fingerprints, "local": {"status": "passed"}, "semantic": {"status": "passed"}, "backend": {"status": "passed"}, "keywords": self.keyword_check.return_value, "issues": []}
        record.update(changes)
        self.write("08_validation.json", record)

    def build(self):
        return renderer.build_report(self.run, generated_at="2026-09-08T18:00:00+08:00")

    def family(self, count=3):
        order = list(range(count, 0, -1))
        variants = [{"variant_id": f"v{i}", "sku": f"SKU-{i}", "asin": None,
                     "attributes": {"color": {"value": f"color{i}", "display": f"Color {i}", "title_value": f"Color {i}"},
                                    "size": {"value": str(i), "display": f"{i} in", "title_value": f"{i} in"},
                                    "finish": {"value": f"finish{i}", "display": f"Finish {i}", "title_value": f"Finish {i}"}}} for i in order]
        self.profile.update({"listing_mode": "family", "parent_sku": "PARENT", "variation_dimensions": ["color", "size"], "variants": variants,
                             "facts": [{"fact_id": "common_fact", "value": "Shared support", "source_ref": "provided sheet", "status": "confirmed"}],
                             "images": [{"image_id": "image_common", "source": "supplied/product.jpg", "applies_to": ["all"]}]})
        self.listing = {"listing_mode": "family", "parent": {"sku": "PARENT", "title": "Family Ghost Night Light", "item_highlight": "Parent highlight"},
                        "title_template": "Ghost Night Light, {color}, {size}",
                        "shared_content": {"bullets": [f"Shared bullet {i}" for i in range(5)], "description": "Shared full description", "search_terms": "shared search"},
                        "variants": [{"variant_id": f"v{i}", "sku": f"SKU-{i}", "attributes": {"color": f"Color {i}", "size": f"{i} in", "finish": f"Finish {i}"},
                                      "title": f"Ghost Night Light, Color {i}, {i} in", "item_highlight": f"Variant highlight {i}",
                                      "content_overrides": {"description": "Special description"} if i == 1 else {}} for i in range(1, count + 1)],
                        "image_plan": [{"plan_id": "plan_specific", "role": "secondary", "applies_to": ["v1"], "buyer_question": "How big?", "selling_point": "Small footprint", "overlay_text": "1 in", "fact_ids": ["common_fact"], "measurement_ids": ["height1"], "source_image_ids": ["image_common"], "body_refs": ["description"], "mobile_check": "Readable", "production_notes": "Show ruler"}],
                        "aplus_plan": [{"plan_id": "aplus_common", "role": "aplus", "applies_to": ["all"], "fact_ids": ["common_fact"], "source_image_ids": ["image_common"], "body_refs": ["bullets[0]"], "native_text": "Native module copy: Height 1 in"}]}
        self.write("01_product_profile.json", self.profile)
        self.write("07_listing.json", self.listing)

    def test_legacy_single_and_old_aplus_remain_readable(self):
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("缺少 08", page)
        for text in ("Ghost Night Light", "Warm campfire glow", "First paragraph.", "Second paragraph.", "Legacy A+", "保留旧字段"):
            self.assertIn(text, md)
            self.assertIn(text, page)
        self.assertIn('id="funnel"', page)
        self.assertIn('id="profileGrid"', page)
        for heading in ("Title", "Item Highlight", "Bullet Points", "Description", "Search Terms"):
            self.assertIn("## " + heading + "\n", md)
        self.assertIn("2026-09-08T18:00:00+08:00", page)
        self.assertNotIn("new Date(", page)

    def test_family_full_output_in_input_order_and_inheritance(self):
        self.family(60)
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("Parent highlight", page)
        self.assertEqual(md.count("## 子体 "), 60)
        self.assertLess(md.index("## 子体 01 · v60"), md.index("## 子体 60 · v1"))
        self.assertLess(page.index("子体 01 · v60"), page.index("子体 60 · v1"))
        for i in range(1, 61):
            for text in (f"SKU-{i}", f"Variant highlight {i}", f"Finish {i}", f"Ghost Night Light, Color {i}, {i} in"):
                self.assertIn(text, md)
                self.assertIn(text, page)
        self.assertEqual(md.count("Shared full description"), 1)  # Inheritors do not duplicate shared copy.
        self.assertIn("Special description", md)
        self.assertEqual(md.count("## 子体差异正文"), 1)
        self.assertLess(md.index("## 父体"), md.index("## 子体 01 · v60"))
        self.assertLess(md.index("## 子体 60 · v1"), md.index("## 系列共用正文"))
        self.assertLess(md.index("## 子体差异正文 60 · v1"), md.index("## 附图策划"))
        self.assertEqual(md.count("### Item Highlight"), 61)

    def test_media_copy_visible_and_full_evidence_preserved_in_embedded_data(self):
        self.family()
        md, page, _ = self.build()
        parsed = ScriptCollector()
        parsed.feed(page)
        self.assertEqual(json.loads(parsed.values["data-listing"]), self.listing)
        self.assertEqual(json.loads(parsed.values["data-profile"]), self.profile)
        visible = " ".join(parsed.visible)
        for text in ("Small footprint", "1 in", "Native module copy: Height 1 in"):
            self.assertIn(text, visible)
        for text in ("正文对应位置", "事实引用", "素材引用", "image_common", "source-json"):
            self.assertNotIn(text, visible)
        self.assertIn("aplus", md)

    def test_current_validation_passes(self):
        self.passed()
        md, page, status = self.build()
        self.assertEqual(status, "passed")
        self.assertIn('id="validationSection" data-validation-status="passed"', page)
        self.assertTrue(md.startswith("## Title"))
        self.assertNotIn("验收通过", md)

    def test_changed_listing_invalidates_pass(self):
        self.passed()
        self.listing["title"] = "A changed title"
        self.write("07_listing.json", self.listing)
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("必须重新验收", page)
        self.assertIn('id="validationSection" data-validation-status="incomplete"', page)
        self.assertNotIn('id="validationSection" data-validation-status="passed"', page)

    def test_changed_or_new_qa_invalidates_pass(self):
        for first in (None, {"status": "completed", "qa_pairs": []}):
            with self.subTest(first=first):
                if first is None:
                    (self.run / "06_qa.json").unlink(missing_ok=True)
                else:
                    self.write("06_qa.json", first)
                self.passed()
                self.write("06_qa.json", {"status": "completed", "qa_pairs": [{"question": "New question"}]})
                self.assertEqual(self.build()[2], "incomplete")

    def test_changed_profile_invalidates_pass(self):
        self.passed()
        self.profile["materials"] = ["A newly supplied material"]
        self.write("01_product_profile.json", self.profile)
        self.assertEqual(self.build()[2], "incomplete")

    def test_missing_original_evidence_cannot_pass(self):
        for filename in ("08_semantic_review.json", "08_backend_validation.json"):
            with self.subTest(filename=filename):
                self.passed()
                (self.run / filename).unlink()
                md, page, status = self.build()
                self.assertEqual(status, "incomplete")
                self.assertIn("不能仅凭汇总声明通过", page)

    def test_changed_original_evidence_invalidates_summary(self):
        for filename in ("08_semantic_review.json", "08_backend_validation.json"):
            with self.subTest(filename=filename):
                self.passed()
                self.write(filename, {"changed": "New evidence"})
                md, page, status = self.build()
                self.assertEqual(status, "incomplete")
                self.assertIn("记录与汇总不匹配", page)

    def test_evidence_formatting_does_not_invalidate_canonical_fingerprint(self):
        self.passed()
        for filename in ("08_semantic_review.json", "08_backend_validation.json"):
            path = self.run / filename
            value = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(value, ensure_ascii=True, indent=4), encoding="utf-8")
        self.assertEqual(self.build()[2], "passed")

    def test_missing_fingerprints_and_unfinished_stages_cannot_pass(self):
        for changes in ({"fingerprints": {}}, {"evidence_fingerprints": {}}, {"semantic": {"status": "pending"}}, {"backend": None}, {"status": "incomplete"}):
            with self.subTest(changes=changes):
                self.passed(**changes)
                self.assertEqual(self.build()[2], "incomplete")

    def test_failed_stage_and_error_issue_override_declared_pass(self):
        for changes in ({"local": {"status": "failed"}}, {"issues": [{"severity": "error", "code": "IDENTITY", "path": "title", "message": "Core identity missing"}]}):
            with self.subTest(changes=changes):
                self.passed(**changes)
                md, page, status = self.build()
                self.assertEqual(status, "failed")
                self.assertIn("验收失败", page)
                self.assertNotIn("验收失败", md)

    def test_missing_family_member_cannot_hide_behind_pass(self):
        self.family()
        self.listing["variants"].pop()
        self.write("07_listing.json", self.listing)
        self.passed()
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("子体缺少输出：v3", page)
        self.assertIn("子体 01 · v3", page)
        self.assertEqual(md.count("## 子体 "), 3)

    def test_script_and_html_injection_are_escaped_losslessly(self):
        malicious = '</script><img src=x onerror="alert(1)"><script>attack</script>&\u2028\u2029__DATA_PROFILE__'
        self.listing["title"] = malicious
        self.profile["category"] = malicious
        self.write("01_product_profile.json", self.profile)
        self.write("07_listing.json", self.listing)
        self.write("02_kw_raw.json", {"keywords": [malicious]})
        md, page, _ = self.build()
        parsed = ScriptCollector()
        parsed.feed(page)
        self.assertEqual(json.loads(parsed.values["data-listing"])["title"], malicious)
        self.assertEqual(json.loads(parsed.values["data-profile"])["category"], malicious)
        self.assertFalse(any(tag == "img" for tag, attrs in parsed.tags))
        self.assertNotIn('<script>attack</script>', page)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertIn("\\u2028", page)
        self.assertIn("&lt;/script&gt;", md)

    def test_corrupt_optional_json_fails_without_replacing_existing_outputs(self):
        (self.run / "06_qa.json").write_text('{"status":', encoding="utf-8")
        (self.run / "07_listing.md").write_text("keep previous md", encoding="utf-8")
        (self.run / "report.html").write_text("keep previous html", encoding="utf-8")
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/render_listing.py"), "--run-dir", str(self.run)], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("06_qa.json", proc.stderr)
        self.assertEqual((self.run / "07_listing.md").read_text(), "keep previous md")
        self.assertEqual((self.run / "report.html").read_text(), "keep previous html")

    def test_missing_required_and_wrong_shapes_are_errors(self):
        self.write("04_kw_tagged.json", {})
        with self.assertRaisesRegex(renderer.ReportError, "04_kw_tagged"):
            self.build()
        (self.run / "04_kw_tagged.json").unlink()
        (self.run / "07_listing.json").unlink()
        with self.assertRaisesRegex(renderer.ReportError, "07_listing"):
            self.build()

    def test_cli_outputs_are_created_and_status_is_explicit(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/render_listing.py"), "--run-dir", str(self.run)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["validation_status"], "incomplete")
        self.assertTrue((self.run / "07_listing.md").exists())
        self.assertTrue((self.run / "report.html").exists())
        self.assertEqual(json.loads(proc.stdout)["files"], ["07_listing.md", "07_listing.json", "report.html"])

    def family_media(self, shared=True):
        self.family(3)
        self.modern_media()
        self.listing["media_strategy"] = "shared_secondary" if shared else "per_variant_full"
        for source in self.profile["variants"]:
            vid = source["variant_id"]
            n = vid[1:]
            source["measurements"] = [{"measurement_id": "height-" + vid, "label": "高度", "value": str(float(n) * 2.54), "unit": "cm", "display_text": n + " in", "source_ref": "用户尺寸表"}]
            self.profile["images"].append({"image_id": "photo-" + vid, "source": "photos/" + vid + ".jpg", "applies_to": [vid]})
            child_main = {"plan_id": "main-" + vid, "role": "main", "image": "图1（主图）", "direction": "该子体实物主图 " + vid, "applies_to": [vid]}
            self.listing["image_plan"].append(child_main)
            secondaries = self.listing["image_sets"]["shared"]["secondary"][:]
            if not shared:
                secondaries = []
                for i in range(2, 8):
                    pid = vid + "-secondary-" + str(i)
                    secondaries.append(pid)
                    self.listing["image_plan"].append({"plan_id": pid, "role": "secondary", "image": f"图{i}（附图）", "direction": f"独立附图 {vid} {i}", "applies_to": [vid]})
            self.listing["image_sets"]["variants"].append({"variant_id": vid, "main": "main-" + vid, "secondary": secondaries})
            if shared:
                for plan in self.listing["image_plan"]:
                    if plan["plan_id"] in secondaries:
                        plan.setdefault("variant_bindings", []).append({"variant_id": vid, "overlay_text": "Height " + n + " in", "fact_ids": ["common_fact"], "measurement_ids": ["height-" + vid], "source_image_ids": ["photo-" + vid], "body_refs": ["description"], "production_notes": "替换为当前子体的尺码与实物"})
        self.write("01_product_profile.json", self.profile)
        self.write("07_listing.json", self.listing)

    def test_single_delivery_sections_and_no_internal_records_in_markdown(self):
        self.modern_media()
        self.listing["claims"] = [{"field": "title", "fact_ids": ["private_fact_identifier"]}]
        self.listing["bullets"] = [f"【BENEFIT {i}】Copy {i}." for i in range(1, 6)]
        self.listing["buyer_question_coverage"] = [{"question": "How does it work?", "status": "covered", "location": "五点第2条"}]
        self.listing["excluded_claims"] = ["unsupported lifespan claim"]
        self.write("07_listing.json", self.listing)
        md, page, _ = self.build()
        headings = [line[3:] for line in md.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["Title", "Item Highlight", "Bullet Points", "Description", "Search Terms", "附图策划", "A+ 整体策划", "买家问题覆盖清单"])
        self.assertEqual(len([line for line in md.splitlines() if line.startswith("### 图")]), 7)
        self.assertEqual(len([line for line in md.splitlines() if line.startswith("### 模块")]), 5)
        self.assertIn("- 【BENEFIT 1】Copy 1.", md)
        self.assertIn("1. How does it work? → 五点第2条", md)
        for text in ("private_fact_identifier", "source-json", "fingerprints", "验收汇总", "产品画像与来源记录", "~~~json", "unsupported lifespan claim"):
            self.assertNotIn(text, md)
        self.assertIn("private_fact_identifier", page)
        parsed = ScriptCollector()
        parsed.feed(page)
        self.assertNotIn("private_fact_identifier", " ".join(parsed.visible))
        self.assertFalse(any(tag in ("details", "nav", "pre") for tag, _ in parsed.tags))
        self.assertIn('<strong class="k2">【BENEFIT 1】</strong>Copy 1.', page)
        self.assertIn('<span class="search-term">halloween</span>', page)
        self.assertIn('<p>First paragraph.</p>\n<p>Second paragraph.</p>', page)
        self.assertIn('<p>1. How does it work? → 五点第2条</p>', page)

    def test_full_family_creatives_expand_every_child_without_child_aplus(self):
        self.family_media(shared=False)
        md, page, _ = self.build()
        self.assertEqual(md.count("### 方案 B｜子体"), 3)
        self.assertEqual(md.count("#### 图1（主图）"), 4)
        self.assertEqual(md.count("#### 图7（附图）"), 4)
        self.assertEqual(md.count("### 模块"), 5)
        for vid in ("v3", "v2", "v1"):
            for i in range(2, 8):
                self.assertIn(f"独立附图 {vid} {i}", md)
        self.assertNotIn("复用共用附图", md)
        self.assertLess(md.index("方案 B｜子体 01 · v3"), md.index("方案 B｜子体 03 · v1"))
        self.assertNotIn('aria-label="图片方案导航"', page)
        for vid in ("v3", "v2", "v1"):
            for i in range(2, 8):
                self.assertIn(f'<p>独立附图 {vid} {i}</p>', page)

    def test_same_appearance_reuses_creatives_and_expands_each_binding(self):
        self.family_media(shared=True)
        md, page, _ = self.build()
        self.assertEqual(md.count("共用画面 2"), 1)
        self.assertEqual(md.count("（复用共用附图）"), 18)
        self.assertEqual(md.count("#### 图1（主图）"), 4)
        for vid in ("v3", "v2", "v1"):
            # Binding text remains readable without technical IDs or JSON.
            self.assertIn("该子体实物素材：photos/" + vid + ".jpg", md)
            self.assertEqual(md.count("替换后的上图文案：Height " + vid[1:] + " in"), 6)
            self.assertIn("该子体规格：高度：" + vid[1:] + " in（来源：用户尺寸表）", md)
        self.assertNotIn("height-v1", md)
        parsed = ScriptCollector()
        parsed.feed(page)
        self.assertEqual(json.loads(parsed.values["data-listing"]), self.listing)
        visible = " ".join(parsed.visible)
        self.assertNotIn("事实引用与制作校验明细", visible)
        for i in range(1, 4):
            self.assertEqual(visible.count(f"Height {i} in"), 6)

    def test_shared_aplus_keeps_one_creative_and_readable_variant_bindings(self):
        self.family_media(shared=True)
        bindings = self.listing["image_plan"][1]["variant_bindings"]
        self.listing["a_plus_plan"][0]["variant_bindings"] = bindings
        self.write("07_listing.json", self.listing)
        md, _, _ = self.build()
        self.assertEqual(md.count("A+ 画面 1"), 1)
        a_plus = md.split("## A+ 整体策划\n", 1)[1]
        for i, vid in enumerate(("v3", "v2", "v1"), 1):
            self.assertIn(f"#### 子体替换 {i:02d} · {vid}", a_plus)
            self.assertIn("photos/" + vid + ".jpg", a_plus)

    def test_family_sections_keep_unique_anchors_without_added_navigation(self):
        self.family_media(shared=True)
        _, page, _ = self.build()
        parsed = ScriptCollector()
        parsed.feed(page)
        ids = [attrs["id"] for _, attrs in parsed.tags if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        targets = [attrs["href"][1:] for tag, attrs in parsed.tags if tag == "a" and attrs.get("href", "").startswith("#")]
        self.assertFalse(targets)
        self.assertTrue(set(targets).issubset(ids))
        self.assertTrue({"parent-copy", "variant-copy-1", "variant-copy-2", "variant-copy-3", "shared-copy", "shared-images", "a-plus-plans"}.issubset(ids))

    def test_validation_details_remain_complete_without_visible_error_panel(self):
        self.passed(status="failed", issues=[{"severity": "error", "code": "test_error", "message": "Internal failure detail", "path": "variants[0]"}])
        _, page, status = self.build()
        parsed = ScriptCollector()
        parsed.feed(page)
        self.assertEqual(status, "failed")
        self.assertIn("验收失败", " ".join(parsed.visible))
        self.assertNotIn("Internal failure detail", " ".join(parsed.visible))
        self.assertEqual(json.loads(parsed.values["data-evidence"])["validation"], json.loads((self.run / "08_validation.json").read_text()))
        self.assertIn("Internal failure detail", parsed.values["data-validation"])

    def test_pending_creative_keeps_actionable_missing_material_note(self):
        self.modern_media()
        self.listing["image_plan"][0].update(status="pending", production_notes="需补充本款实拍照片。")
        self.write("07_listing.json", self.listing)
        _, page, _ = self.build()
        self.assertIn('<strong>制作前确认：</strong>需补充本款实拍照片。', page)

    def test_report_binding_keeps_both_copy_fields_and_does_not_invent_missing_binding(self):
        doc = renderer.Document(report_view=True)
        plan = {"variant_bindings": [{"variant_id": "v1", "overlay_text": "Image copy", "native_text": "Native copy"}]}
        renderer.render_binding(doc, plan, "v1", {})
        renderer.render_binding(doc, plan, "v2", {})
        _, content = doc.result()
        self.assertIn("Image copy", content)
        self.assertIn("Native copy", content)
        self.assertIn("缺少该子体的参数与素材绑定", content)
        self.assertNotIn("沿用共用创意及其文案", content)

    def test_alias_conflicts_fail_and_identical_aliases_remain_readable(self):
        self.listing["aplus_plan"] = [{"module": "Conflicting content"}]
        self.write("07_listing.json", self.listing)
        with self.assertRaisesRegex(renderer.ReportError, "内容冲突"):
            self.build()
        self.listing["aplus_plan"] = self.listing["a_plus_plan"]
        self.write("07_listing.json", self.listing)
        self.assertIn("Legacy A+", self.build()[0])
        del self.listing["a_plus_plan"]
        self.write("07_listing.json", self.listing)
        self.assertIn("Legacy A+", self.build()[0])

    def test_missing_image_references_and_orphans_cannot_pass(self):
        self.modern_media()
        self.listing["image_sets"]["shared"]["secondary"][0] = "missing-plan"
        self.write("07_listing.json", self.listing)
        self.passed()
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("缺少图片策划：missing-plan", md)
        self.assertIn("图片创意未分配", page)

    def test_duplicate_plan_or_binding_identifiers_are_rejected(self):
        self.family_media(shared=True)
        self.listing["image_plan"][1]["variant_bindings"].append(self.listing["image_plan"][1]["variant_bindings"][0])
        self.write("07_listing.json", self.listing)
        with self.assertRaisesRegex(renderer.ReportError, "重复绑定"):
            self.build()
        self.family_media(shared=True)
        self.listing["image_plan"].append(self.listing["image_plan"][0])
        self.write("07_listing.json", self.listing)
        with self.assertRaisesRegex(renderer.ReportError, "重复图片编号"):
            self.build()

    def test_legacy_pass_does_not_imply_new_contract_pass(self):
        self.passed(legacy=True)
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("旧版图片策划", page)
        self.assertNotIn("旧版图片策划", md)

    def test_current_local_failure_overrides_old_passing_summary(self):
        self.modern_media()
        self.passed()
        for severity, expected in (("error", "failed"), ("incomplete", "incomplete")):
            with self.subTest(severity=severity):
                self.local_check.return_value = [{"severity": severity, "code": "image_count", "path": "image_sets.shared", "message": "Current rule rejected the image count"}]
                md, page, status = self.build()
                self.assertEqual(status, expected)
                self.assertIn("Current rule rejected the image count", page)
                self.assertNotIn("Current rule rejected the image count", md)
                self.local_check.assert_called_with(self.profile, self.listing, None)

    def test_real_current_checker_runs_when_renderer_is_dynamically_imported(self):
        self.local_check.side_effect = self.real_local_check
        md, page, status = self.build()
        self.assertEqual(status, "incomplete")
        self.assertIn("legacy_schema", page)
        self.assertTrue(md.startswith("## Title"))

    def test_text_aplus_is_labelled_as_non_image_module(self):
        self.modern_media()
        self.listing["a_plus_plan"].append({"plan_id": "faq", "module": "模块6：FAQ", "role": "aplus", "asset_type": "text", "direction": "回答常见问题"})
        self.listing["image_sets"]["shared"]["a_plus"].append("faq")
        self.write("07_listing.json", self.listing)
        md, _, _ = self.build()
        self.assertIn("纯文字模块，不计入 A+ 图片数量", md)

    def test_aplus_module_heading_wins_over_legacy_image_label(self):
        self.modern_media()
        self.listing["a_plus_plan"][0]["image"] = "图2（旧图片标签）"
        self.write("07_listing.json", self.listing)
        md, _, _ = self.build()
        a_plus = md.split("## A+ 整体策划", 1)[1]
        self.assertIn("### 模块1：主题", a_plus)
        self.assertNotIn("### 图2（旧图片标签）", a_plus)

    def test_malformed_nested_cli_input_fails_without_replacing_outputs(self):
        for profile_change, listing_change in (({"variants": None}, {}), ({}, {"image_plan": [{"source_image_ids": None}]})):
            with self.subTest(profile_change=profile_change, listing_change=listing_change):
                self.write("01_product_profile.json", dict(self.profile, **profile_change))
                self.write("07_listing.json", dict(self.listing, **listing_change))
                (self.run / "07_listing.md").write_text("original markdown")
                (self.run / "report.html").write_text("original report")
                proc = subprocess.run([sys.executable, str(ROOT / "scripts/render_listing.py"), "--run-dir", str(self.run)], capture_output=True, text=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("报告生成失败", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertEqual((self.run / "07_listing.md").read_text(), "original markdown")
                self.assertEqual((self.run / "report.html").read_text(), "original report")



if __name__ == "__main__":
    unittest.main()
