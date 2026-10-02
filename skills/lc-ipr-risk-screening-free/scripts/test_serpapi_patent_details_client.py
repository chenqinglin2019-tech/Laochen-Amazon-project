import unittest

from provider_utils import ProviderError
from serpapi_patent_details_client import _normalize


class SerpApiPatentDetailsTests(unittest.TestCase):
    def test_normalizes_content_without_calling_it_official_status(self):
        result = _normalize({"publication_number": "US1234567B2", "claims": ["1. A device"], "images": [{"url": "x"}]},
                            {"q": "US1234567B2", "candidate_id": "C", "right_type": "patent"})
        self.assertEqual(result["source_role"], "published_document_content_only")
        self.assertFalse(result["authoritative_for_final_rating"])
        self.assertEqual(result["satisfied_facts"], ["protection_content", "representative_figures"])

    def test_rejects_wrong_publication(self):
        with self.assertRaisesRegex(ProviderError, "does not match"):
            _normalize({"publication_number": "US1", "claims": []}, {"q": "US2", "candidate_id": "C", "right_type": "patent"})
