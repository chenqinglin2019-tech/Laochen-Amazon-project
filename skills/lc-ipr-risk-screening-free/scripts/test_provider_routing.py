import unittest

from provider_routing import priority, source_upstream


class ProviderRoutingTests(unittest.TestCase):
    def test_fr_patent_discovery_uses_official_then_complement_then_google_fallback(self):
        routes = priority("FR", "patent", "discovery")
        self.assertEqual(routes[0], ("inpi_api", "preferred"))
        self.assertIn(("epo_ops", "complement"), routes)
        self.assertEqual(routes[-1], ("serpapi_google_patents", "fallback"))

    def test_ep_content_prefers_publication_server(self):
        self.assertEqual(priority("EP", "patent", "content")[0], ("epo_publication_server", "preferred"))

    def test_jp_status_does_not_claim_keyword_recall(self):
        self.assertEqual(priority("JP", "patent", "status"), [("jpo_api", "preferred")])
        self.assertNotIn("jpo_api", [p for p, _ in priority("JP", "patent", "discovery")])

    def test_google_patents_is_one_upstream(self):
        self.assertEqual(source_upstream("serper_patents"), source_upstream("serpapi_google_patents"))

    def test_eu_design_is_independent_of_national_design(self):
        self.assertIn(("euipo_design", "preferred"), priority("DE", "design", "discovery"))

