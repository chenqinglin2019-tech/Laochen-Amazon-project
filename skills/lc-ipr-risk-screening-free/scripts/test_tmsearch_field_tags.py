import unittest
import copy
import json
from pathlib import Path
from record_browser_execution import planned_browser_query, validate_tm_result_binding, compile_ppubs_boolean, compile_ppubs_query

class TmFieldTagTests(unittest.TestCase):
    def test_ppubs_v2_shared_fixtures_and_legacy_semantics(self):
        cases = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/ppubs-boolean-v2.json").read_text())
        for case in cases:
            with self.subTest(q=case["q"]):
                if "error" in case:
                    with self.assertRaisesRegex(ValueError, case["error"]):
                        compile_ppubs_boolean(case["q"], "ppubs-boolean-v2")
                else:
                    self.assertEqual(compile_ppubs_boolean(case["q"], "ppubs-boolean-v2"), case["expected"])
        row = {"q": "ring with openings", "strategy": "boolean", "right_type": "patent"}
        self.assertEqual(compile_ppubs_query(row, "product")["rendered_query"], "ring AND with AND openings")
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_QUERY_SEMANTICS"):
            compile_ppubs_query({**row, "query_compiler_revision": "ppubs-boolean-v2"}, "product")

    def test_headerless_zero_receipt_requires_a_real_result_transition(self):
        query = 'CM:"FUNANYWHERE"'
        baseline = {"url": "https://tmsearch.uspto.gov/", "zero_visible": False, "card_count": 0, "result_query": ""}
        transition = {"submission_id": "attempt-1", "rendered_query": query, "baseline": baseline, "method": "result_route",
                      "final_url": "https://tmsearch.uspto.gov/search/search-results", "zero_visible": True, "observed_loading": False}
        zero = {"status": "no_result", "candidates": [], "query_binding": {"total_hits": 0, "result_query": "", "loading": False,
                "parsed_count": 0, "result_view": "list", "binding_method": "submitted_zero_transition_v1", "zero_result_transition": transition}}
        validate_tm_result_binding(zero, {"observed_count": 0}, query)
        for field, value in (("submission_id", ""), ("rendered_query", "OTHER"), ("final_url", "https://other.example/search/search-results"),
                             ("zero_visible", False), ("method", "input_matches")):
            bad = copy.deepcopy(zero)
            bad["query_binding"]["zero_result_transition"][field] = value
            with self.assertRaises(ValueError):
                validate_tm_result_binding(bad, {"observed_count": 0}, query)
        stale = copy.deepcopy(zero)
        stale["query_binding"]["zero_result_transition"]["baseline"].update(url=transition["final_url"], zero_visible=True)
        with self.assertRaises(ValueError):
            validate_tm_result_binding(stale, {"observed_count": 0}, query)
        stale["query_binding"]["zero_result_transition"].update(method="loading_cycle", observed_loading=True)
        with self.assertRaises(ValueError):  # A global footer spinner does not refresh the result.
            validate_tm_result_binding(stale, {"observed_count": 0}, query)
        cycle = {"prior_zero_disappeared": True, "result_loading_observed": True, "result_zero_reappeared": True}
        stale["query_binding"]["zero_result_transition"]["result_container_transition"] = cycle
        validate_tm_result_binding(stale, {"observed_count": 0}, query)
        for key in cycle:
            bad = copy.deepcopy(stale)
            bad["query_binding"]["zero_result_transition"]["result_container_transition"][key] = False
            with self.assertRaises(ValueError):
                validate_tm_result_binding(bad, {"observed_count": 0}, query)

    def test_compiler_revision_is_per_row_and_keeps_old_rendering(self):
        row={"q":"Lid Latch","right_type":"trademark_word","operation":"trademark_recall","strategy":"phrase","filters":{"field":"ocr","language":"en"}}
        self.assertEqual(planned_browser_query("uspto_tmsearch_browser",row)["rendered_query"],'"Lid Latch"')
        row["query_compiler_revision"]="tm-field-tags-v1"
        actual=planned_browser_query("uspto_tmsearch_browser",row)
        self.assertEqual(actual["rendered_query"],'CM:"Lid Latch"')
        self.assertEqual(actual["search_mode"],"field_tag")
        self.assertEqual(actual["field_code"],"CM")
        row["query_compiler_revision"]="unknown"
        with self.assertRaises(ValueError): planned_browser_query("uspto_tmsearch_browser",row)

    def test_literals_cannot_inject_field_expressions(self):
        for value in ['Lid" OR *','Lid\\Latch','Lid\nLatch']:
            row={"q":value,"right_type":"trademark_word","operation":"trademark_recall","strategy":"phrase","filters":{"field":"ocr","language":"en"},"query_compiler_revision":"tm-field-tags-v1"}
            with self.assertRaises(ValueError): planned_browser_query("uspto_tmsearch_browser",row)

    def test_receipt_rechecks_query_and_count(self):
        query='CM:"Lid Latch"'
        capture={"status":"success","candidates":[{"serial_number":"88418732"}],
                 "query_binding":{"total_hits":1,"result_query":query,"loading":False,"parsed_count":1,"result_view":"detail","result_index":1}}
        validate_tm_result_binding(capture,{"observed_count":1},query)
        for patch in ({"total_hits":0},{"total_hits":True},{"total_hits":None},{"result_query":"OTHER"}, {"loading":True}, {"parsed_count":0}, {"result_index":2}):
            bad={**capture,"query_binding":{**capture["query_binding"],**patch}}
            with self.assertRaises(ValueError): validate_tm_result_binding(bad,{"observed_count":1},query)
        with self.assertRaises(ValueError): validate_tm_result_binding(capture,{"observed_count":0},query)
        with self.assertRaises(ValueError): validate_tm_result_binding({**capture,"status":"no_result"},{"observed_count":1},query)
        zero={"status":"no_result","candidates":[],"query_binding":{"total_hits":0,"result_query":query,"loading":False,"parsed_count":0,"result_view":"list"}}
        validate_tm_result_binding(zero,{"observed_count":0},query)

if __name__=="__main__": unittest.main()
