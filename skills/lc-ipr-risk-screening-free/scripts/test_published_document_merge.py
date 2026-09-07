import unittest

from merge_candidates import better_verification


class PublishedDocumentMergeTests(unittest.TestCase):
    def setUp(self):
        self.document = {"status": "incomplete", "authority_scope": "published_document_only",
                         "identity_match": True, "legal_status": "", "owner": [],
                         "checked_at": "2026-09-06T11:00:00Z"}
        self.recall = {"status": "not_checked", "identity_match": None,
                       "checked_at": "2026-09-06T12:00:00Z"}

    def test_new_recall_keeps_original_incomplete_document_check(self):
        for left, right in ((self.document, self.recall), (self.recall, self.document)):
            selected = better_verification(left, right)
            self.assertEqual(selected, self.document)
            self.assertNotEqual(selected["status"], "verified")
            self.assertEqual(selected["legal_status"], "")

    def test_later_actual_identity_mismatch_still_overrides_document(self):
        mismatch = {**self.recall, "status": "identity_mismatch", "identity_match": False}
        self.assertEqual(better_verification(self.document, mismatch), mismatch)

    def test_historical_non_document_recency_is_unchanged(self):
        previous = {"status": "partial", "checked_at": "2026-09-06T11:00:00Z"}
        self.assertEqual(better_verification(previous, self.recall), self.recall)


if __name__ == "__main__":
    unittest.main()
