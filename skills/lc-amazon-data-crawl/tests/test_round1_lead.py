from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from amazon_category_rank_crawler import parse_field_from_text, sellersprite_field_status


class SellerSpriteValueParsingTests(unittest.TestCase):
    def test_placeholder_never_borrows_the_next_label_value(self) -> None:
        text = "FBA费用: -- 毛利率: 35% 配送: FBA"
        self.assertEqual(parse_field_from_text("fba_fee", text), "--")
        self.assertEqual(parse_field_from_text("gross_margin", text), "35%")
        self.assertEqual(sellersprite_field_status("fba_fee", "--"), "explicit_unavailable")

    def test_negative_margin_keeps_its_sign(self) -> None:
        text = "FBA费用: $4.20 毛利率: -12% 配送: FBM"
        self.assertEqual(parse_field_from_text("gross_margin", text), "-12%")
        self.assertEqual(parse_field_from_text("fba_fee", text), "$4.20")

    def test_other_currencies_and_placeholders(self) -> None:
        self.assertEqual(parse_field_from_text("fba_fee", "FBA费用: €3,20 毛利率: 20%"), "€3,20")
        self.assertEqual(parse_field_from_text("fba_fee", "FBA费用: 暂无"), "暂无")
        self.assertEqual(parse_field_from_text("gross_margin", "毛利率: - 配送: FBA"), "-")
        self.assertEqual(parse_field_from_text("gross_margin", "毛利率: N/A"), "N/A")

    def test_unparseable_labelled_value_is_missing_not_guessed(self) -> None:
        self.assertEqual(parse_field_from_text("fba_fee", "FBA费用: 计算中 毛利率: 35%"), "")



class PackageNeverOverwritesTests(unittest.TestCase):
    def test_existing_archive_is_not_replaced(self) -> None:
        import tempfile

        import package_skill

        with tempfile.TemporaryDirectory() as temp:
            skill = Path(temp) / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "SKILL.md").write_text("x", encoding="utf-8")
            (skill / "config.json").write_text('{"backend_url": "u", "backend_token": ""}', encoding="utf-8")
            output = Path(temp) / "existing.zip"
            output.write_bytes(b"original upload")
            with self.assertRaises(package_skill.PackageError):
                package_skill.build_package(skill, output)
            self.assertEqual(output.read_bytes(), b"original upload")


if __name__ == "__main__":
    unittest.main()
