"""A bound failed detail receipt is not every candidate's new material."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import atomic_write_json,sha256_json
from source_result_processing import _specific_record_scope,work_entries

class SpecificFailureScopeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.row={'query_id':'Q1','candidate_id':'B1','scenario_id':'product_entry',
            'operation':'candidate_detail','jurisdiction':'US','right_type':'patent'}
        self.plan={'queries':{'serpapi_google_patents':[self.row]}}
        atomic_write_json(self.root/'search-plan.json',self.plan)
        self.run={'run_id':'FAILED','provider':'serpapi_google_patents','query_id':'Q1',
            'operation':'candidate_detail','jurisdiction':'US','right_type':'patent','status':'failed',
            'plan_entry_sha256':sha256_json(self.row),'request_params':{'candidate_id':'B1'},'result_processing':{}}
    def test_failed_run_exact_scope_keeps_failure_pending_and_original_unchanged(self):
        before=deepcopy(self.run)
        self.assertEqual(_specific_record_scope(self.root,self.run),{'candidate_id':'B1','scenario_id':'product_entry'})
        with patch('source_result_processing.enabled',return_value=True),patch('source_result_processing.progress',return_value={
                'material_processing_complete':False,'pending_positions':[],'pending_parse_positions':[]}):
            work=work_entries({}, {'source_runs':[self.run]},self.root)
        self.assertEqual(work[0]['candidate_id'],'B1');self.assertEqual(work[0]['reason'],'SOURCE_RESULTS_PENDING_PROCESSING')
        self.assertEqual(work[0]['state'],'awaiting_review');self.assertEqual(self.run,before)
    def test_wrong_plan_candidate_country_and_broad_search_have_no_specific_scope(self):
        original=deepcopy(self.run)
        for change in ({'plan_entry_sha256':'wrong'},{'jurisdiction':'GB'},{'operation':'search'},
                {'request_params':{'candidate_id':'OTHER'}}):
            self.run.update(change);self.assertEqual(_specific_record_scope(self.root,self.run),{});self.run=deepcopy(original)
        self.assertEqual(_specific_record_scope(None,self.run),{})

if __name__=='__main__':unittest.main()
