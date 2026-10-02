import unittest
from epo_query import compile_ops_query, validate_compiled_query
from epo_ops_client import classify_ops_failure, normalize_search, search_response
from provider_utils import ProviderError
from workflow_v24 import _api_params

class EpoQueryTests(unittest.TestCase):
    def test_country_scope_has_no_illegal_wildcard(self):
        query = compile_ops_query(countries=["US", "WO"], field="ta", value="pimple AND popping", strategy="boolean")
        self.assertEqual(query, '(pn=US or pn=WO) and ((ta="pimple" and ta="popping"))')
        self.assertNotIn("US*", query)

    def test_phrase_and_fields(self):
        for field in ("ta", "pa", "in", "ipc", "cpc"):
            self.assertIn(f'{field}="nose shaped toy"', compile_ops_query(
                countries=["GB", "EP", "WO"], field=field, value="nose shaped toy", strategy="phrase"))

    def test_boolean_precedence_and_not(self):
        query = compile_ops_query(countries=["JP"], field="ta",
            value='(pimple OR blackhead) AND popping AND NOT medical', strategy="boolean")
        self.assertIn('((ta="pimple" or ta="blackhead") and ta="popping")', query)
        self.assertIn('and not ta="medical"', query)

    def test_quoted_operator_is_text(self):
        query = compile_ops_query(countries=["EP"], field="ta", value='"salt AND pepper"', strategy="boolean")
        self.assertIn('ta="salt AND pepper"', query)

    def test_rejects_unsafe_or_unsupported_syntax(self):
        for value in ("US*", "ab?", "ab#", "pimple prox popping", "NOT pimple", "(pimple OR)", "x;drop"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_ops_query(countries=["US"], field="ta", value=value, strategy="boolean")
        with self.assertRaises(ValueError):
            validate_compiled_query('(pn=US*) and ta="toy"')

    def test_planner_uses_revision_without_changing_legacy(self):
        term = {"kind": "function", "value": "pimple OR blackhead", "strategy": "boolean"}
        revised = _api_params("epo_ops", term, "US", "patent", query_compiler_revision="ops-cql-v1")["q"]
        legacy = _api_params("epo_ops", term, "US", "patent")["q"]
        self.assertIn("pn=US or pn=WO", revised)
        self.assertNotIn("pn=US*", revised)
        self.assertIn("pn=US*", legacy)

    def test_error_chain_distinguishes_syntax_auth_and_unknown(self):
        body = b'<fault><code>CLIENT.MinimumCharsBeforeTruncation</code><message>bad query</message></fault>'
        syntax, state = classify_ops_failure(ProviderError("PROVIDER_HTTP_ERROR", "failed", "HTTP 413", 413, body), "search")
        self.assertEqual((syntax.code, state, syntax.response_body), ("EPO_QUERY_SYNTAX_REJECTED", "submitted", body))
        auth, state = classify_ops_failure(ProviderError("AUTH_FAILED", "access_limited", "bad auth", 401), "search")
        self.assertEqual((auth.code, state), ("AUTH_FAILED", "not_submitted"))
        timeout, state = classify_ops_failure(ProviderError("PROVIDER_TIMEOUT", "failed", "timeout"), "search")
        self.assertEqual((timeout.code, state), ("PROVIDER_TIMEOUT", "unknown"))

    def test_search_empty_fault_is_a_submitted_zero_but_detail_404_is_not(self):
        empty = b'<?xml version="1.0"?><fault xmlns="http://ops.epo.org"><code>SERVER.EntityNotFound</code><message>No results found</message></fault>'
        result, state = classify_ops_failure(ProviderError("PROVIDER_HTTP_ERROR", "failed", "HTTP 404", 404, empty), "search")
        self.assertEqual((result.code, result.source_status, state), ("EPO_SEARCH_NO_RESULTS", "no_result", "submitted"))
        self.assertEqual(normalize_search(empty), [])
        response = search_response(empty, "1-25", require_range=True)
        self.assertEqual(response["search_metadata"]["total_hits"], 0)
        self.assertTrue(response["search_metadata"]["empty_fault_receipt"])
        detail, detail_state = classify_ops_failure(ProviderError("PROVIDER_HTTP_ERROR", "failed", "HTTP 404", 404, empty), "biblio")
        self.assertEqual((detail.code, detail_state), ("PROVIDER_HTTP_ERROR", "submitted"))

    def test_similar_or_gateway_fault_is_not_a_zero(self):
        altered = b'<fault><code>SERVER.EntityNotFound</code><message>No result found</message></fault>'
        result, state = classify_ops_failure(ProviderError("PROVIDER_HTTP_ERROR", "failed", "HTTP 404", 404, altered), "search")
        self.assertEqual((result.code, state), ("PROVIDER_HTTP_ERROR", "submitted"))
        with self.assertRaises(ProviderError):
            normalize_search(altered)

if __name__ == "__main__": unittest.main()
