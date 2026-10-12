from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "consumer_evidence_access.py"
SPEC = importlib.util.spec_from_file_location("consumer_evidence_access", SCRIPT_PATH)
assert SPEC and SPEC.loader
ACCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCESS)


class ConsumerEvidenceAccessTests(unittest.TestCase):
    def test_queue_page_is_bounded_and_cursor_is_snapshot_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "queue.jsonl"
            rows = [
                {"record_id": f"record-{index}", "cache_key": f"cache-{index}", "text": "short"}
                for index in range(51)
            ]
            queue.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            page = ACCESS.page_queue(queue, cursor=None, limit=50, max_chars=12_000)
            self.assertEqual(50, len(page["records"]))
            self.assertEqual("record-50", page["next_cursor"]["offset"] and rows[page["next_cursor"]["offset"]]["record_id"])
            queue.write_text(queue.read_text(encoding="utf-8") + json.dumps({"record_id": "changed", "cache_key": "changed"}) + "\n", encoding="utf-8")
            with self.assertRaises(ACCESS.EvidenceAccessError):
                ACCESS.page_queue(queue, cursor=json.dumps(page["next_cursor"]), limit=50, max_chars=12_000)

    def test_oversized_record_requires_segmented_read_then_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "queue.jsonl"
            row = {"record_id": "record-1", "cache_key": "cache-1", "text": "x" * 12_100}
            queue.write_text(json.dumps(row) + "\n", encoding="utf-8")
            page = ACCESS.page_queue(queue, cursor=None, limit=50, max_chars=12_000)
            self.assertEqual("oversized", page["oversized"]["status"])
            segment = ACCESS.read_queue_record(queue, "cache-1", start=0, length=12_000)
            self.assertFalse(segment["complete"])
            with self.assertRaises(ACCESS.EvidenceAccessError):
                ACCESS.read_queue_record(queue, "cache-1", start=0, length=12_001)
            resumed = ACCESS.page_queue(queue, cursor=json.dumps(page["next_cursor"]), limit=50, max_chars=12_000, acknowledge_cache_key="cache-1")
            self.assertFalse(resumed["has_more"])

    def test_index_omits_full_text_and_context_requires_matching_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_db = root / "collector.sqlite3"
            connection = sqlite3.connect(source_db)
            connection.execute("CREATE TABLE comments (record_id TEXT, source TEXT, content_id TEXT, parent_content_id TEXT, text TEXT, raw_json TEXT)")
            connection.execute("INSERT INTO comments VALUES (?, ?, ?, ?, ?, ?)", ("voice-1", "reddit", "child", "parent", "child text", json.dumps({"thread_title": "thread"})))
            connection.execute("INSERT INTO comments VALUES (?, ?, ?, ?, ?, ?)", ("parent-1", "reddit", "parent", "", "parent text", "{}"))
            connection.commit()
            connection.close()
            source_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
            coding = {
                "metadata": {"source_db_sha256": source_hash},
                "voices": [{"voice_id": "voice-1", "cache_key": "cache-1", "full_text": "full original text", "needs": [{"code": "need-a", "stance": "support"}]}],
            }
            analysis = {"evidence_readiness": {"needs": [{"code": "need-a", "support_refs": ["voice-1"], "counter_refs": []}]}}
            coding_path, analysis_path, index_path = root / "coding.json", root / "analysis.json", root / "evidence_index.json"
            coding_path.write_text(json.dumps(coding), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
            ACCESS.build_workshop_index(coding_path, analysis_path, index_path)
            index_text = index_path.read_text(encoding="utf-8")
            self.assertNotIn("full original text", index_text)
            context = ACCESS._readonly_context(coding_path, "voice-1", source_db, start=0, length=20)
            self.assertFalse(context["complete"])
            coding["metadata"]["source_db_sha256"] = "0" * 64
            coding_path.write_text(json.dumps(coding), encoding="utf-8")
            with self.assertRaises(ACCESS.EvidenceAccessError):
                ACCESS._readonly_context(coding_path, "voice-1", source_db, start=0, length=20)

    def test_query_need_paginates_against_a_snapshot_and_batch_read_reuses_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coding = {"voices": [
                {"voice_id": f"voice-{index}", "full_text": "original", "needs": [{"need_id": "need-a", "stance": "support"}]}
                for index in range(3)
            ]}
            path = root / "coding.json"
            path.write_text(json.dumps(coding), encoding="utf-8")
            first = ACCESS.query_need(path, "need-a", stance="all", segment_id=None, limit=2)
            self.assertTrue(first["has_more"])
            second = ACCESS.query_need(path, "need-a", stance="all", segment_id=None, limit=2,
                cursor=json.dumps(first["next_cursor"]))
            self.assertEqual(["voice-2"], [row["voice_id"] for row in second["records"]])
            batch = ACCESS.read_voices(path, ["voice-0", "voice-1"], start=0, length=100)
            self.assertEqual(2, len(batch["records"]))


if __name__ == "__main__":
    unittest.main()
