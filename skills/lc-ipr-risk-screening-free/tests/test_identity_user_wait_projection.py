"""User-only target prerequisites defer location without establishing identity."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workflow_v24 import _identity_user_actions

class IdentityUserWaitTests(unittest.TestCase):
    def setUp(self):
        self.task={'schema_version':'2.4-free','decision_workflow_revision':'scenario-triage-v1',
            'triage_scope_revision':'candidate-triage-scope-v1','retrieval_workflow_revision':'api-first-v3',
            'triage_followup_revision':'candidate-followup-v1'}
        self.evidence={'collections':{'patents':[{'evidence_id':'E1'}]}}
        self.action={'action_id':'A1','kind':'user_information','question':'Actual hidden target component?',
            'user_exclusive_reason':'Only the user/manufacturer has the target structure.',
            'followup_basis':{**{k:'Concrete target component and judgment condition' for k in
                ['missing_fact','decision_effect','evidence_needed','existing_material_review','completion_condition','new_value']},
                'obligation_ids':['target-component'],'existing_evidence_refs':['E1']}}
        self.record={'current':True,'decision':'needs_info','jurisdiction':'UNLOCATED','right_type':'patent',
            'annotation':{'annotation_id':'ANN','reading_level':'abstract','evidence_refs':['E1'],
                'candidate_relation':{'identity_gaps':['target_jurisdiction']}},'next_actions':[self.action]}
    def check(self):return _identity_user_actions(self.task,self.evidence,self.record)
    def test_valid_current_user_only_basis_waits_and_unknown_identity_stays(self):
        before=deepcopy(self.record)
        self.assertEqual(self.check(),[self.action]);self.assertEqual(self.record,before)
        self.assertEqual(self.record['jurisdiction'],'UNLOCATED')
    def test_mixed_source_unread_unregistered_and_malformed_stay_open(self):
        for change in ({'current':False},{'decision':'selected'},{'next_actions':[]},
                {'next_actions':[self.action,{'kind':'source_lookup'}]}):
            old=deepcopy(self.record);self.record.update(change);self.assertEqual(self.check(),[]);self.record=old
        self.record['annotation']['reading_level']='unread';self.assertEqual(self.check(),[])
        self.record['annotation']['reading_level']='abstract';self.evidence['collections']={};self.assertEqual(self.check(),[])
        self.evidence={'collections':{'patents':[{'evidence_id':'E1'}]}}
        self.record['next_actions'][0]['user_exclusive_reason']='';self.assertEqual(self.check(),[])
    def test_completed_or_continuing_result_does_not_silently_wait_again(self):
        for outcome in ['continue','limited','resolved']:
            with patch('candidate_followup.latest_event',return_value={'outcome':outcome}):self.assertEqual(self.check(),[])
        with patch('candidate_followup.latest_event',return_value={'outcome':'waiting'}):self.assertEqual(self.check(),[self.action])
    def test_legacy_version_keeps_original_identity_gate(self):
        self.task['retrieval_workflow_revision']='api-first-v2';self.assertEqual(self.check(),[])

if __name__=='__main__':unittest.main()
