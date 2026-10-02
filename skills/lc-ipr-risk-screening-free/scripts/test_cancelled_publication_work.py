"""Cancellation archives execution only after retained work; snapshot is call-local."""
from copy import deepcopy
from unittest.mock import patch
import unittest
from pathlib import Path
from common import sha256_json
import necessary_completion as nc
from decision_workflow import _snapshot_value


class CancelledPublicationWorkTests(unittest.TestCase):
    def setUp(self):
        self.task={'retrieval_workflow_revision':'api-first-v3'}
        self.row={'query_id':'Q','action_purpose':'discovery','jurisdiction':'US','right_type':'design'}
        self.plan={'queries':{'serpapi_google_patents':[self.row]}}
        self.run={'provider':'serpapi_google_patents','query_id':'Q','run_id':'R',
            'plan_entry_sha256':sha256_json(self.row),'submission_state':'submitted','status':'failed',
            'result_processing':{'revision':'source-result-processing-v1'}}
        self.evidence={'source_runs':[self.run]}
        review={'kind':'failure_review','source_run_id':'R','source_run_sha256':sha256_json(self.run),
            **{k:'actual audit' for k in ('receipt_review','material_review','failure_cause','remaining_work',
                'repair_basis','reviewer','reasoning','source_rule_ref')}}
        review['review_id']='REC-REV-'+sha256_json(review)[:24]
        self.evidence['recovery_reviews']=[review]
        self.entry={'kind':'source_lookup','reason':'SCENARIO_ACTION_CANCELLED',
            'provider':'serpapi_google_patents','query_id':'Q','jurisdiction':'US','right_type':'design'}

    def closed(self):
        return nc._cancelled_discovery_execution_closed(self.task,self.entry,self.plan,self.evidence,{}, {},task_dir=Path('/offline'))

    def test_cancelled_processed_known_failure_is_execution_only(self):
        before=deepcopy((self.task,self.evidence,self.plan))
        with patch('workflow_v24.validated_query_cancellation',return_value={'exact':'sha'}), \
             patch('source_result_processing.progress',return_value={'material_processing_complete':True}), \
             patch('api_first_planning.retained_discovery_work',return_value=None):
            self.assertTrue(self.closed())
            self.assertEqual((self.task,self.evidence,self.plan),before)
            self.task['retrieval_workflow_revision']='api-first-v2';self.assertFalse(self.closed())

    def test_unknown_unread_retained_cards_and_invalid_cancel_are_not_closed(self):
        with patch('workflow_v24.validated_query_cancellation',return_value={'exact':'sha'}) as cancel, \
             patch('source_result_processing.progress',return_value={'material_processing_complete':True}) as reading, \
             patch('api_first_planning.retained_discovery_work',return_value=None) as pending:
            cancel.return_value=None;self.assertFalse(self.closed());cancel.return_value={'exact':'sha'}
            self.run['submission_state']='unknown';self.assertFalse(self.closed());self.run['submission_state']='submitted'
            reading.return_value={'material_processing_complete':False};self.assertFalse(self.closed());reading.return_value={'material_processing_complete':True}
            pending.return_value={'state':'awaiting_review','reason':'unread card'};self.assertFalse(self.closed());pending.return_value=None
            self.run.pop('result_processing');self.assertFalse(self.closed())

    def test_historical_missing_body_needs_exact_audit_and_no_retained_cards(self):
        self.run.pop('result_processing');self.run['raw_paths']=[]
        review={'kind':'failure_review','source_run_id':'R','source_run_sha256':sha256_json(self.run),
            **{k:'audited actual absence' for k in ('receipt_absence_reason','receipt_review','material_review',
                'failure_cause','remaining_work','repair_basis','reviewer','reasoning','source_rule_ref')}}
        review['review_id']='REC-REV-'+sha256_json(review)[:24]
        self.evidence['recovery_reviews']=[review]
        with patch('workflow_v24.validated_query_cancellation',return_value={'exact':'sha'}), \
             patch('api_first_planning.retained_discovery_work',return_value=None), \
             patch('assessment_v24._source_records',return_value=[]) as cards:
            self.assertTrue(self.closed())
            cards.return_value=[{'actual':'unread card'}];self.assertFalse(self.closed());cards.return_value=[]
            review['material_review']='tampered';self.assertFalse(self.closed())

    def test_missing_body_is_preserved_as_unknown_delivery_limitation(self):
        self.run.pop('result_processing');self.run['raw_paths']=[]
        review={'kind':'failure_review','source_run_id':'R','source_run_sha256':sha256_json(self.run),
            **{k:'body unavailable; audited run only' for k in ('receipt_absence_reason','receipt_review',
                'material_review','failure_cause','remaining_work','repair_basis','reviewer','reasoning','source_rule_ref')}}
        review['review_id']='REC-REV-'+sha256_json(review)[:24];self.evidence['recovery_reviews']=[review]
        with patch('workflow_v24.validated_query_cancellation',return_value={'exact':'sha'}), \
             patch('api_first_planning.retained_discovery_work',return_value=None), \
             patch('assessment_v24._source_records',return_value=[]):
            limit=nc._cancelled_discovery_limit_entry(self.task,self.entry,self.plan,self.evidence,{}, {},task_dir=Path('/offline'))
            self.assertEqual(limit['coverage_status'],'unknown')
            self.assertEqual(limit['official_verification'],'not_verified')
            self.assertIn('body unavailable',limit['reasoning'])
            self.assertTrue(nc._delivery_limit_valid(limit,self.task,self.evidence,self.plan,{},task_dir=Path('/offline')))
            limit['delivery_limit']['cancellation_sha256']='tampered'
            self.assertFalse(nc._delivery_limit_valid(limit,self.task,self.evidence,self.plan,{},task_dir=Path('/offline')))

    def test_publication_snapshot_reuses_within_call_and_never_across_calls(self):
        count=[];obj={};values=[]
        def compute(*args,**kwargs):
            def read():count.append(1);return len(count)
            values.append((_snapshot_value('test-only',(obj,),read),_snapshot_value('test-only',(obj,),read)))
            return 'context'
        with patch('necessary_completion._publication_context',side_effect=compute):
            self.assertEqual(nc.publication_context(self.task,{}, {},{}, {},{}),'context')
            self.assertEqual(nc.publication_context(self.task,{}, {},{}, {},{}),'context')
        self.assertEqual(values,[(1,1),(2,2)])

    def test_publication_snapshot_rejects_mutation(self):
        def mutate(*args,**kwargs):self.task['changed']=True
        with patch('necessary_completion._publication_context',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'DECISION_SNAPSHOT_INPUT_MUTATED'):
                nc.publication_context(self.task,{}, {},{}, {},{})

if __name__=='__main__':unittest.main()
