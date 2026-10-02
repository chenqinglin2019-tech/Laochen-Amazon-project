"""Explicit no-retry audits do not establish rights facts or publication permission."""
import hashlib
import unittest
from copy import deepcopy
from unittest.mock import patch
import test_recovery_stage_b as recovery_tests
from common import sha256_json
from recovery_stage_b import no_retry_audit, task_limit_no_retry_proof, recovery_state
from trusted_api import _registered_original_protection


class NoRetryTests(unittest.TestCase):
    save = recovery_tests.RecoveryStageBTests.save
    add_run = recovery_tests.RecoveryStageBTests.add_run
    review = recovery_tests.RecoveryStageBTests.review
    def setUp(self):
        recovery_tests.RecoveryStageBTests.setUp(self)
        self.task.update(retrieval_workflow_revision='api-first-v3',
            serpapi_free_enhancement={'max_queries_per_task':1})
        self.provider = 'serpapi_google_patents'
        self.row.update(operation='candidate_detail',candidate_id='C')
        self.save()

    def audit(self):
        body=b'{"error":"confirmed failure"}'
        (self.path/'raw.json').write_bytes(body)
        run=self.add_run(raw_paths=['raw.json'],payload_digest=hashlib.sha256(body).hexdigest(),
            quota={'network_request_attempted':True})
        constraint={'kind':'task_request_limit','provider':self.provider,
            'plan_entry_sha256':sha256_json(self.row),'max_queries_per_task':1,'consumed_queries':1}
        self.review(run,receipt_paths=['raw.json'],source_allows_retry=False,
            retry_disposition='not_requested',no_retry_reason='Task cap exhausted; fields remain unknown',
            retry_constraint=constraint)
        return run

    def test_explicit_audit_blocks_dispatch_without_delivery_permission(self):
        self.audit()
        state=recovery_state(self.task,self.evidence,self.provider,self.row)
        self.assertEqual(state['reason'],'SOURCE_RETRY_NOT_REQUESTED')
        self.assertNotIn('delivery_limit',state)
        with patch('source_result_processing.progress',return_value={'material_processing_complete':True}):
            self.assertIsNotNone(task_limit_no_retry_proof(self.task,self.evidence,self.provider,self.row,self.path))
            self.task['serpapi_free_enhancement']['max_queries_per_task']=2
            self.assertIsNone(task_limit_no_retry_proof(self.task,self.evidence,self.provider,self.row,self.path))

    def test_tamper_raw_review_unknown_and_unprocessed_rejected(self):
        run=self.audit()
        with patch('source_result_processing.progress',return_value={'material_processing_complete':False}):
            self.assertIsNone(task_limit_no_retry_proof(self.task,self.evidence,self.provider,self.row,self.path))
        (self.path/'raw.json').write_bytes(b'changed')
        self.assertIsNone(no_retry_audit(self.task,self.evidence,self.provider,self.row,self.path))
        self.evidence['recovery_reviews'][-1]['no_retry_reason']='changed'
        self.assertIsNone(no_retry_audit(self.task,self.evidence,self.provider,self.row))
        run['submission_state']='unknown'
        self.assertIsNone(no_retry_audit(self.task,self.evidence,self.provider,self.row))

    def test_plain_false_and_legacy_false_do_not_pass(self):
        run=self.add_run()
        with self.assertRaisesRegex(ValueError,'RECOVERY_SOURCE_RETRY_NOT_ALLOWED'):
            self.review(run,source_allows_retry=False)
        self.task.pop('retrieval_workflow_revision');self.save()
        with self.assertRaisesRegex(ValueError,'RECOVERY_SOURCE_RETRY_NOT_ALLOWED'):
            self.review(run,source_allows_retry=False,retry_disposition='not_requested',no_retry_reason='cap')

    def test_delivery_requires_both_current_field_gap_and_original_audit(self):
        from necessary_completion import _delivery_limit_valid
        entry={'kind':'source_lookup','provider':self.provider,'query_id':'Q1','state':'blocked',
            'reason':'SOURCE_RETRY_NOT_REQUESTED','coverage_status':'unknown','official_verification':'not_verified',
            'resume_condition':'new current record', 'delivery_limit':{'kind':'source_failure_no_retry',
                'audit':{'bound':'original'},'field_gap':{'bound':'current'}}}
        expected={'delivery_limit':{'bound':'current'},'resume_condition':'new current record'}
        plan={'queries':{self.provider:[self.row]}}
        with patch('necessary_completion.api_record_gap_entry',return_value=expected) as gap, \
             patch('recovery_stage_b.task_limit_no_retry_proof',return_value={'bound':'original'}) as audit:
            def valid():return _delivery_limit_valid(entry,self.task,self.evidence,plan,{},task_dir=self.path)
            self.assertTrue(valid())
            gap.return_value=None;self.assertFalse(valid());gap.return_value=expected
            audit.return_value=None;self.assertFalse(valid());audit.return_value={'bound':'original'}
            entry['delivery_limit']['field_gap']={'bound':'stale'};self.assertFalse(valid())


class OriginalCreditTests(unittest.TestCase):
    def test_exact_current_read_original_credit_only(self):
        task={'retrieval_workflow_revision':'api-first-v3'}
        candidate={'candidate_id':'C','publication_number':'US123B1'}
        scope={'candidate_id':'C','scenario_id':'product_entry','jurisdiction':'US','right_type':'patent'}
        lead={'evidence_id':'LEAD','provider':'external_document_lead','right_type':'patent',
            'lead':{'publication_number':'US123B1'},'source_registration':{'evidence_id':'EV'},
            'document':{'sha256':'abc','source_url':'https://example.test/exact'}}
        evidence={'collections':{'candidate_leads':[lead]}}
        base={**scope,'intake_event_id':'I'}
        material={**base,'kind':'material','event_id':'M','source_form':'original_document',
            'document_id':'US123B1','document_version':'v1','status':'sufficient_for_listed_purposes',
            'supported_facts':['protection'],'evidence_refs':['EV']}
        fact={**base,'kind':'fact','event_id':'F','fact_kind':'protection','outcome':'supported',
            'material_event_ids':['M'],'document_version':'v1','evidence_refs':['EV'],
            'raw_statement':'Read full claims','recorded_at':'2026-09-29'}
        batch={**base,'kind':'batch','processed_material_event_ids':['M'],'received_evidence_refs':['EV']}
        history=[material,fact,batch]
        with patch('specialty_analysis._current',return_value={'annotation':{'annotation_id':'A'}}), \
             patch('specialty_analysis._intake',return_value={'annotation_id':'A','event_id':'I'}), \
             patch('specialty_analysis._validate_intake'),patch('specialty_analysis.events',return_value=history), \
             patch('specialty_analysis._fact'),patch('specialty_analysis._material'),patch('specialty_analysis._batch'), \
             patch('decision_workflow.evidence_index',return_value={}), \
             patch('record_candidate_lead.validated_candidate_lead_entries',return_value=[lead]) as retained:
            def credit():
                return _registered_original_protection(task,evidence,candidate,'US','patent',scope=scope,
                    candidates={},ledger={},supplement={},task_dir='/unused')
            value=credit();self.assertEqual(value['source_form'],'reviewed_original_document')
            self.assertEqual(value['source_run_ids'],[])
            self.assertEqual(value['record_identity'],{'publication_number':'US123B1'})
            material['document_id']='US124B1';self.assertIsNone(credit());material['document_id']='US123B1'
            material['status']='acquired';self.assertIsNone(credit());material['status']='sufficient_for_listed_purposes'
            fact['outcome']='unknown';self.assertIsNone(credit());fact['outcome']='supported'
            fact['document_version']='v2';self.assertIsNone(credit());fact['document_version']='v1'
            batch['processed_material_event_ids']=[];self.assertIsNone(credit());batch['processed_material_event_ids']=['M']
            retained.side_effect=ValueError('original bytes changed');self.assertIsNone(credit())
            scope['jurisdiction']='GB';self.assertIsNone(credit())

if __name__=='__main__':unittest.main()
