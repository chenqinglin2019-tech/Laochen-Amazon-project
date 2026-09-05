from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "assets" / "reference-page" / "feiyushentu-page.html"
HARNESS_HTML = ROOT / "assets" / "codex-harness-app" / "web" / "index.html"
HARNESS_CSS = ROOT / "assets" / "codex-harness-app" / "web" / "app.css"
HARNESS_JS = ROOT / "assets" / "codex-harness-app" / "web" / "app.js"
SKILL = ROOT / "SKILL.md"
BLUEPRINT = ROOT / "references" / "page-blueprint.md"


class HistoryTooltipContractTests(unittest.TestCase):
    def test_history_title_and_description_are_one_line_ellipsis_controls(self):
        for path in (BASELINE, HARNESS_CSS):
            source = path.read_text(encoding="utf-8")
            rule = re.search(r"\.htext\s*\{([^}]+)\}", source)
            self.assertIsNotNone(rule, path)
            compact = re.sub(r"\s+", "", rule.group(1))
            for declaration in (
                "display:block",
                "width:100%",
                "white-space:nowrap",
                "overflow:hidden",
                "text-overflow:ellipsis",
            ):
                self.assertIn(declaration, compact, path)
        for path in (BASELINE, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertIn('class="htext ttl"', source, path)
            self.assertIn('class="htext dsc"', source, path)
            self.assertGreaterEqual(source.count('data-his-tip="'), 2, path)

    def test_shared_tooltip_is_bounded_wrapping_and_scrollable(self):
        for path in (BASELINE, HARNESS_HTML):
            source = path.read_text(encoding="utf-8")
            self.assertEqual(source.count('id="his-tip"'), 1, path)
            self.assertIn('role="tooltip" hidden', source, path)
        for path in (BASELINE, HARNESS_CSS):
            source = path.read_text(encoding="utf-8")
            rule = re.search(r"\.his-tip\s*\{([^}]+)\}", source)
            self.assertIsNotNone(rule, path)
            compact = re.sub(r"\s+", "", rule.group(1))
            for declaration in (
                "position:fixed",
                "max-width:min(420px,calc(100vw-24px))",
                "max-height:min(240px,calc(100dvh-24px))",
                "overflow:auto",
                "white-space:pre-wrap",
                "overflow-wrap:anywhere",
            ):
                self.assertIn(declaration, compact, path)

    def test_tooltip_supports_hover_focus_touch_click_and_escape(self):
        for path in (BASELINE, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertIn('el.addEventListener("pointerenter"', source, path)
            self.assertIn('el.addEventListener("focus"', source, path)
            self.assertIn('el.addEventListener("click"', source, path)
            self.assertIn('e.pointerType !== "touch"', source, path)
            self.assertIn('e.key === "Escape"', source, path)
            self.assertIn("vw - width - pad", source, path)
            self.assertIn("vh - height - pad", source, path)

    def test_skill_documents_history_tooltip_contract(self):
        skill = SKILL.read_text(encoding="utf-8")
        blueprint = BLUEPRINT.read_text(encoding="utf-8")
        self.assertIn("one-line\n  ellipsized controls", skill)
        self.assertIn('shared `role="tooltip"`', blueprint)
        self.assertIn("max-height: min(240px, 100dvh - 24px)", blueprint)


if __name__ == "__main__":
    unittest.main()
