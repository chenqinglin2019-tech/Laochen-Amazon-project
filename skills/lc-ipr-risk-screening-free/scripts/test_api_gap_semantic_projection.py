"""API planning advisories are not new M06 judgment inputs."""
from copy import deepcopy
import unittest
from specialty_analysis import _source_gap_proof_matches


class ApiGapSemanticProjectionTests(unittest.TestCase):
    def setUp(self):
        self.task={'retrieval_workflow_revision':'api-first-v3'}
        self.saved={'kind':'api_record_fact_gap','candidate_id':'C','scenario_id':'product_entry',
            'jurisdiction':'US','right_type':'patent','candidate_sha256':'record-v1',
            'annotation_sha256':'annotation-v1','required_facts':['rights_holder'],
            'basis_event_ids':['F1'], 'event_sha256':{'F1':'fact','I1':'exact-intake'},
            'planning_gap_sha256':'advisory-old','capabilities_sha256':'caps-old',
            'followup_sha256':{},'recovery_condition':'pending actual followup'}

    def test_metadata_changes_keep_saved_receipt_immutable(self):
        before=deepcopy(self.saved)
        fresh={**self.saved,'planning_gap_sha256':'advisory-current',
            'capabilities_sha256':'caps-current','candidate_sha256':'accounting-only-current',
            'followup_sha256':{'FOLLOW':'sha'},
            'recovery_condition':'new source becomes available'}
        self.assertTrue(_source_gap_proof_matches(self.task,fresh,self.saved))
        self.assertEqual(self.saved,before)

    def test_fact_record_scope_and_reading_changes_are_substantive(self):
        for key,value in [('required_facts',['current_status']),
            ('candidate_id','other'),('jurisdiction','GB'),('basis_event_ids',['F2']),
            ('event_sha256',{'F1':'fact','I1':'different-exact-record-intake'}),('annotation_sha256','annotation-v2')]:
            with self.subTest(key=key):
                self.assertFalse(_source_gap_proof_matches(self.task,{**self.saved,key:value},self.saved))
        self.assertFalse(_source_gap_proof_matches(self.task,None,self.saved))

    def test_old_versions_and_other_route_proofs_keep_exact_gap_binding(self):
        fresh={**self.saved,'planning_gap_sha256':'different'}
        self.assertFalse(_source_gap_proof_matches({},fresh,self.saved))
        self.assertFalse(_source_gap_proof_matches(self.task,{**fresh,'kind':'status_route'},
            {**self.saved,'kind':'status_route'}))

if __name__=='__main__':unittest.main()
