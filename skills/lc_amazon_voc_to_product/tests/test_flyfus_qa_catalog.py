from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("flyfus_qa_catalog", SKILL_ROOT / "scripts" / "flyfus_qa_catalog.py")
assert SPEC and SPEC.loader
CATALOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG)


def _receipt(request: dict[str, object], count: int) -> dict[str, object]:
    return {
        "provider": "flyfus", "operation": "recommended_qa", "status": "complete",
        "request": request, "points_cap": None, "points_reserved": 1,
        "spend_boundary": "task_completion", "returned_question_count": count,
        "response": {"data": {"items": [{"question": f"q{index}", "answer": {"text": "a"}} for index in range(count)]}},
    }


class FlyfusQaCatalogTests(unittest.TestCase):
    def test_builds_count_only_catalog_and_syncs_missing_ledger_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keyword = root / "flyfus" / "keyword_qa" / "01.json"
            product = root / "flyfus" / "product_qa" / "page_02" / "01-A1.json"
            keyword.parent.mkdir(parents=True)
            product.parent.mkdir(parents=True)
            keyword.write_text(json.dumps(_receipt({"keyword": "small desk", "market": "US", "withAnswer": True}, 2)), encoding="utf-8")
            product.write_text(json.dumps(_receipt({"asin": "A1", "market": "US", "withAnswer": True, "page": 2}, 3)), encoding="utf-8")
            catalog = CATALOG.build_catalog(root)
            summary = catalog["summary"]
            self.assertEqual(5, summary["returned_question_records"])
            self.assertEqual(5, summary["answered_question_records"])
            self.assertEqual(1, summary["keyword_query_count"])
            self.assertEqual(1, summary["product_asin_count"])
            self.assertEqual(1, summary["product_page_count"])
            self.assertEqual(2, CATALOG.sync_ledger(root, catalog))
            self.assertEqual(0, CATALOG.sync_ledger(root, catalog))
            rows = [json.loads(line) for line in (root / "flyfus_receipts.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(rows))
            self.assertEqual(0o600, (root / "flyfus_receipts.jsonl").stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
