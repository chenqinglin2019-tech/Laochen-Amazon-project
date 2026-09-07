import unittest
from unittest.mock import patch
from pathlib import Path
from record_tsdr_browser_verification import candidate_request_params

class TsdrRequestContractTests(unittest.TestCase):
    def test_strict_request_preserves_exact_planned_inputs(self):
        planned={'q':'97876463','candidate_id':'C1','serial_number':'97876463','mode':'agent',
                 'strategy':'record_number','query_id':'Q1','operation':'candidate_verification',
                 'right_type':'trademark_word','jurisdiction':'US','wave':2,'required':False}
        with patch('record_tsdr_browser_verification.bind_candidate_plan',return_value=('Q1','C1')), patch('record_tsdr_browser_verification.planned_query_metadata',return_value=planned):
            strict=candidate_request_params(Path('/unused'),{'schema_version':'2.4-free','screening_revision':'recall-integrity-v1'},{},'97876463','trademark_word')
            self.assertEqual(strict,{'q':'97876463','candidate_id':'C1','serial_number':'97876463','mode':'agent','strategy':'record_number','right_type':'trademark_word'})
            legacy=candidate_request_params(Path('/unused'),{'schema_version':'2.3-free'},{},'97876463','trademark_word')
            self.assertEqual(legacy['mode'],'user_assisted')
            self.assertNotIn('strategy',legacy)

if __name__=='__main__': unittest.main()
