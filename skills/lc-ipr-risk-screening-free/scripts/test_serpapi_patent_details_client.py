import unittest

from provider_utils import ProviderError
from serpapi_patent_details_client import _normalize, _payload_error, NOT_FOUND_MESSAGE


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

    def test_exact_not_found_under_a_success_envelope_is_distinguished_from_provider_errors(self):
        found = _payload_error({"error": NOT_FOUND_MESSAGE, "search_metadata": {"status": "Success"}})
        self.assertEqual((found.code, found.source_status), ("PROVIDER_RECORD_NOT_FOUND", "failed"))
        for payload in ({"error": NOT_FOUND_MESSAGE},
                        {"error": NOT_FOUND_MESSAGE, "search_metadata": {"status": "Error"}},
                        {"error": NOT_FOUND_MESSAGE + " timeout", "search_metadata": {"status": "Success"}},
                        {"error": "Invalid API key", "search_metadata": {"status": "Success"}}):
            with self.subTest(payload=payload):
                self.assertEqual(_payload_error(payload).code, "PROVIDER_HTTP_ERROR")
