from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "assets" / "reference-page" / "feiyushentu-page.html"
HARNESS_HTML = ROOT / "assets" / "codex-harness-app" / "web" / "index.html"
HARNESS_CSS = ROOT / "assets" / "codex-harness-app" / "web" / "app.css"
HARNESS_JS = ROOT / "assets" / "codex-harness-app" / "web" / "app.js"
BLUEPRINT = ROOT / "references" / "page-blueprint.md"


class LightboxContractTests(unittest.TestCase):
    def test_baseline_and_harness_expose_accessible_reset_control(self):
        for path in (BASELINE, HARNESS_HTML):
            source = path.read_text(encoding="utf-8")
            self.assertEqual(source.count('id="lb-reset"'), 1, path)
            self.assertIn('aria-label="恢复图片大小"', source, path)
            self.assertIn('aria-keyshortcuts="0"', source, path)

    def test_preview_has_no_packaged_download_action(self):
        for path in (BASELINE, HARNESS_HTML, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("lb-zip", source, path)
            self.assertNotIn("打包下载全部图片", source, path)
        self.assertIn("全部下载 .zip", BASELINE.read_text(encoding="utf-8"))
        self.assertIn("全部下载 .zip", HARNESS_JS.read_text(encoding="utf-8"))

    def test_preview_canvas_has_definite_dynamic_viewport_boundaries(self):
        for path in (BASELINE, HARNESS_CSS):
            source = path.read_text(encoding="utf-8")
            rule = re.search(r"\.lbx-fig\s*\{([^}]+)\}", source)
            self.assertIsNotNone(rule, path)
            compact = re.sub(r"\s+", "", rule.group(1))
            for declaration in (
                "width:calc(100vw-168px)",
                "height:calc(100dvh-92px)",
                "max-width:100%",
                "max-height:100%",
            ):
                self.assertIn(declaration, compact, path)
            self.assertIn("max-height:calc(100dvh - 104px)", source, path)

    def test_loaded_image_gets_pixel_fit_before_zoom(self):
        for path in (BASELINE, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertIn("function fitLBImage()", source, path)
            self.assertIn('visibleHeight - px("paddingTop") - px("paddingBottom")', source, path)
            self.assertIn("availableHeight / img.naturalHeight", source, path)
            self.assertIn('img.style.height = Math.max(1, Math.floor(img.naturalHeight * fit)) + "px";', source, path)
            self.assertIn('window.visualViewport.addEventListener("resize", refitLBViewport)', source, path)

    def test_zoomed_image_remains_pointer_draggable(self):
        for path in (BASELINE, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertIn("if(ZOOMS[state.lb.z] <= 1) return;", source, path)
            self.assertIn('$("lb-img").addEventListener("pointermove"', source, path)
            self.assertIn("state.lb.x = drag.ox + dx; state.lb.y = drag.oy + dy;", source, path)

    def test_reset_restores_zoom_rotation_and_pan(self):
        for path in (BASELINE, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertIn("function resetLB()", source, path)
            self.assertIn("s.z = Z0; s.rot = 0; s.x = 0; s.y = 0;", source, path)
            self.assertIn('$("lb-reset").addEventListener("click", resetLB);', source, path)
            self.assertIn('if(e.key === "0"){ e.preventDefault(); resetLB(); }', source, path)

    def test_blueprint_documents_fit_and_restore(self):
        source = BLUEPRINT.read_text(encoding="utf-8")
        self.assertIn("restore button returns zoom, rotation, and pan", source)
        self.assertIn("oversized preview fits inside the available viewport", source)


if __name__ == "__main__":
    unittest.main()
