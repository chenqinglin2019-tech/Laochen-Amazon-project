import unittest
from record_browser_execution import planned_browser_query, validate_tm_result_binding

class TmFieldTagTests(unittest.TestCase):
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
