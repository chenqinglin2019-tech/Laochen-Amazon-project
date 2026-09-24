from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scrapling_adapter import extract_card_fields, scrapling_available


@unittest.skipUnless(scrapling_available(), "Scrapling is not installed in this Python environment")
class ScraplingAdapterTests(unittest.TestCase):
    def test_extracts_first_matching_card_field_without_browser(self) -> None:
        values = extract_card_fields(
            """
            <article>
              <span class='price' title='$19.99'>ignored</span>
              <span class='rating' aria-label='4.8 out of 5'>4.8</span>
              <span class='title'>  Example\n Product  </span>
            </article>
            """,
            {
                "price": [".price"],
                "rating": [".rating"],
                "title": [".title"],
                "missing": [".missing"],
            },
        )
        self.assertEqual(values["price"], "$19.99")
        self.assertEqual(values["rating"], "4.8 out of 5")
        self.assertEqual(values["title"], "Example Product")
        self.assertNotIn("missing", values)


if __name__ == "__main__":
    unittest.main()
