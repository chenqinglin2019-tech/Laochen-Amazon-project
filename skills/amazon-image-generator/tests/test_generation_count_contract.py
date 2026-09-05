from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "assets" / "reference-page" / "feiyushentu-page.html"
HARNESS_JS = ROOT / "assets" / "codex-harness-app" / "web" / "app.js"
SERVER = ROOT / "assets" / "codex-harness-app" / "backend" / "server.py"
SKILL = ROOT / "SKILL.md"
BLUEPRINT = ROOT / "references" / "page-blueprint.md"


class GenerationCountContractTests(unittest.TestCase):
    def test_pages_offer_all_counts_with_labels_but_numeric_values(self):
        for path in (BASELINE, HARNESS_JS):
            source = path.read_text(encoding="utf-8")
            self.assertIn("Array.from({length:15}", source, path)
            self.assertIn('value:String(n), label:"生成 " + n + " 张"', source, path)
            self.assertIn('total:String(totalSel.value||"")', source, path)
            self.assertNotIn("[1,2,3,4,6,8]", source, path)

    def test_backend_accepts_the_same_upper_bound(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("MAX_GENERATION_COUNT = 15", source)
        self.assertIn("total > MAX_GENERATION_COUNT", source)

    def test_skill_documents_display_and_wire_contract(self):
        skill = SKILL.read_text(encoding="utf-8")
        blueprint = BLUEPRINT.read_text(encoding="utf-8")
        self.assertIn("display each option as `生成 N 张`", skill)
        self.assertIn("submit only the numeric string `N`", skill)
        self.assertIn("every integer from 1 through 15", blueprint)


if __name__ == "__main__":
    unittest.main()
