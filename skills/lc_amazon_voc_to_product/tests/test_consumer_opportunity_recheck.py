from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import consumer_opportunity_recheck as review


class OpportunityReviewTests(unittest.TestCase):
    def _coding(self, root: Path) -> Path:
        path = root / "coding.json"
        path.write_text(json.dumps({"voices": [{
            "voice_id": "voice-1", "platform": "amazon", "full_text": "The desk needs a deeper work surface.",
            "excerpt": "The desk needs a deeper work surface.", "needs": [],
        }]}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_prepare_uses_preserved_full_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = review.prepare(self._coding(root), root / "queue", 20)
            self.assertEqual(result["voice_count"], 1)
            batch = json.loads((root / "queue/batches/opportunity-0001.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["records"][0]["text"], "The desk needs a deeper work surface.")

    def test_import_rejects_missing_or_non_source_evidence_quote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review.prepare(self._coding(root), root / "queue", 20)
            result = root / "results.jsonl"
            result.write_text(json.dumps({
                "voice_id": "voice-1", "decision": "no_specific_opportunity", "desired_outcomes": [],
                "barriers": [], "consequences": [], "workarounds": [], "candidate_mechanism_hints": [],
                "needs": [], "rationale": "只表达现有产品的尺寸偏好", "reviewer_id": "codex-reviewer",
            }) + "\n", encoding="utf-8")
            with self.assertRaises(review.ReviewError):
                review.import_results(root / "queue", result)

    def test_import_requires_the_frozen_record_fingerprint_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review.prepare(self._coding(root), root / "queue", 20)
            batch = json.loads((root / "queue/batches/opportunity-0001.json").read_text(encoding="utf-8"))
            record = batch["records"][0]
            output = {"voice_id": "voice-1", "decision": "specific_need", "desired_outcomes": ["more space"],
                "barriers": ["surface is shallow"], "consequences": [], "workarounds": [],
                "candidate_mechanism_hints": ["extendable surface"],
                "needs": [{"need_id": "deeper_surface", "label": "更深工作面", "stance": "support", "applicability": "current"}],
                "rationale": "明确描述了工作面深度不足", "reviewer_id": "codex-reviewer",
                "evidence_quote": "deeper work surface", "record_source_sha256": record["record_source_sha256"]}
            results = root / "results.jsonl"
            results.write_text(json.dumps(output) + "\n", encoding="utf-8")
            review.import_results(root / "queue", results)
            with self.assertRaises(review.ReviewError):
                review.import_results(root / "queue", results)


if __name__ == "__main__":
    unittest.main()
