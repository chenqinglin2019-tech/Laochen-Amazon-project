"""Read exact API requests remain finished while missing facts stay explicit limitations."""
import copy
import unittest
from common import atomic_write_json, load_json, sha256_json
from trusted_api import annotate_entry
from necessary_completion import _reviewed_api_gap_queries,_duplicate_reviewed_api_gap_work
import test_patent_detail_record_processing as fixtures

class CompletedApiGapRequestTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DetailRecordTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.scope={'candidate_id':'C1','scenario_id':'product_entry','jurisdiction':'US','right_type':'design'}
        self.row={**self.scope,'query_id':'Q1','operation':'candidate_detail','q':'USD1127104S1','api_gap_revision':'api-first-v3','missing_facts':['current_status','rights_holder']}
        self.plan={'queries':{'serpapi_google_patents':[self.row]}}
        self.run=self.f.run;self.run.update(query_id='Q1',right_type='design',plan_entry_sha256=sha256_json(self.row),requirement_ids=[],finished_at='2026-09-29T00:00:00Z')
        self.entry=self.f.entry
        for key in ('query_id','jurisdiction','right_type','plan_entry_sha256'):self.entry[key]=self.run[key]
        annotate_entry(self.f.task,self.entry,self.run)
        atomic_write_json(self.f.root/'evidence.json',self.f.evidence)
        self.gap={**self.scope,'code':'API_RECORD_FACT_GAP','required_facts':['rights_holder'],'attempted_query_ids':['Q1']}
    def finished(self):
        return _reviewed_api_gap_queries(self.f.task,self.f.evidence,self.plan,self.gap,self.scope,self.f.root)
    def test_only_bound_successful_actual_read_record_is_finished(self):
        self.assertEqual(self.finished(),set());self.f.review();self.f.evidence=load_json(self.f.root/'evidence.json')
        self.assertEqual(self.finished(),{'Q1'})
        self.assertEqual(self.gap['required_facts'],['rights_holder'])
    def test_wrong_plan_country_candidate_or_missing_original_rejected(self):
        self.f.review();self.f.evidence=load_json(self.f.root/'evidence.json')
        original=copy.deepcopy(self.plan)
        for field,value in [('q','USD999S1'),('jurisdiction','GB'),('candidate_id','C999')]:
            self.row[field]=value;self.assertEqual(self.finished(),set())
            self.row.update(original['queries']['serpapi_google_patents'][0])
        from pathlib import Path
        Path(self.run['raw_paths'][0]).write_bytes(b'Changed original')
        self.assertEqual(self.finished(),set())
    def test_failed_unread_or_not_submitted_does_not_finish(self):
        self.f.review();self.f.evidence=load_json(self.f.root/'evidence.json')
        run=self.f.evidence['source_runs'][0]
        for field,value in [('status','failed'),('submission_state','not_submitted')]:
            old=run[field];run[field]=value;self.assertEqual(self.finished(),set());run[field]=old
        self.f.evidence['record_content_reviews'][0]['reading_units']=['identity']
        self.assertEqual(self.finished(),set())
    def test_other_query_uncovered_fact_and_legacy_stay_pending(self):
        self.f.review();self.f.evidence=load_json(self.f.root/'evidence.json')
        self.gap['attempted_query_ids']=['QOTHER'];self.assertEqual(self.finished(),set())
        self.gap['attempted_query_ids']=['Q1'];self.gap['required_facts']=['representative_figures'];self.assertEqual(self.finished(),set())
        self.gap['required_facts']=['rights_holder'];self.f.task['retrieval_workflow_revision']='api-first-v2';self.assertEqual(self.finished(),set())
    def test_only_duplicate_request_and_derived_source_pending_are_removed(self):
        source={**self.scope,'query_id':'Q1','kind':'source_lookup','state':'ready','reason':'NECESSARY_ACTION_PENDING'}
        derived={**self.scope,'query_id':'Q1','kind':'agent_investigation','state':'awaiting_review','reason':'SPECIALTY_SOURCE_PENDING'}
        self.assertTrue(_duplicate_reviewed_api_gap_work(source,self.scope,{'Q1'}));self.assertTrue(_duplicate_reviewed_api_gap_work(derived,self.scope,{'Q1'}))
        for entry in [{**source,'query_id':'Q2'},{**source,'jurisdiction':'GB'},{**source,'reason':'BROWSER_PARTIAL_RESUME'},
            {**source,'state':'blocked'},{**source,'reason':'API_RECORD_FACT_GAP'},{**derived,'reason':'RETAINED_ORIGINAL_REQUIRES_READING'},
            {**derived,'kind':'user_information','state':'awaiting_user'},{**derived,'reason':'SPECIALTY_MATERIAL_UNACCOUNTED'}]:
            self.assertFalse(_duplicate_reviewed_api_gap_work(entry,self.scope,{'Q1'}))
        self.assertFalse(_duplicate_reviewed_api_gap_work(source,self.scope,set()))

if __name__=='__main__':unittest.main()
