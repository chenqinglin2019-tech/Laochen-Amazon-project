"""Synthetic waiting proofs only; no business evidence or source traffic."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import atomic_write_json, sha256_json, sha256_file, load_json
import api_first_planning as ap
from candidate_followup import _append
from assessment_estimate import validate_supplement
import test_api_first_planning as fixtures


def action(kind='user_information'):
    result={'action_id':'WAIT-1','kind':kind,'purpose':'resolve actual hidden structure',
      'question':'What is the real hidden joint construction?',
      'followup_basis':{'missing_fact':'actual hidden joint','decision_effect':'claim mapping remains unknown',
        'evidence_needed':'actual teardown','existing_material_review':'retained exact public claims read',
        'existing_evidence_refs':['LOCAL-CLAIMS'],'obligation_ids':['VERIFY-CLAIMS'],
        'completion_condition':'map actual product elements','new_value':'private actual product structure'}}
    if kind=='user_information': result['user_exclusive_reason']='Only supplier or owner holds teardown facts.'
    return result


class BoundedWaitingTests(unittest.TestCase):
    def setUp(self):
        self.task={'task_id':'SYNTHETIC-WAIT','retrieval_workflow_revision':'api-first-v3',
          'triage_followup_revision':'candidate-followup-v1','triage_scope_revision':'candidate-triage-scope-v1'}
        self.evidence={'source_runs':[], 'collections':{}}
        self.supplement={'evidence':[{'evidence_id':'LOCAL-CLAIMS','sha256':'synthetic-original-hash'}]}
        self.decision={'annotation':{'annotation_id':'ANN1','decision':'needs_info'},'next_actions':[action()]}

    def test_verified_supplement_known_and_missing_refs_fail_closed(self):
        self.assertTrue(ap._bounded_waiting_decision_valid(self.task,self.evidence,self.decision,self.supplement))
        self.assertFalse(ap._bounded_waiting_decision_valid(self.task,self.evidence,self.decision))
        self.assertFalse(ap._bounded_waiting_decision_valid(self.task,self.evidence,self.decision,{'evidence':[]}))
        changed=deepcopy(self.decision);changed['next_actions'][0]['kind']='source_lookup'
        self.assertFalse(ap._bounded_waiting_decision_valid(self.task,self.evidence,changed,self.supplement))

    def test_professional_wait_binding_detects_changed_supplement(self):
        self.decision['next_actions']=[action('professional_review')]
        _append(self.task,{'kind':'result_review','annotation_id':'ANN1','action_id':'WAIT-1',
          'run_id':None,'run_sha256':None,'result_evidence_refs':['LOCAL-CLAIMS'],
          'result_evidence_sha256':{'LOCAL-CLAIMS':sha256_json(self.supplement['evidence'][0])},
          'outcome':'waiting','dependency':'qualified external claim interpretation',
          'resume_condition':'retain professional opinion','reviewer':'synthetic reviewer','reason':'hidden target structure unknown'})
        self.assertTrue(ap._bounded_waiting_decision_valid(self.task,self.evidence,self.decision,self.supplement))
        changed=deepcopy(self.supplement);changed['evidence'][0]['sha256']='changed'
        self.assertFalse(ap._bounded_waiting_decision_valid(self.task,self.evidence,self.decision,changed))

    def test_supplement_loader_never_accepts_changed_or_missing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'exact-claims.txt';original.write_text('synthetic exact claims')
            supplement={'schema':'IPR-EVIDENCE-SUPPLEMENT/1.0','evidence':[{'evidence_id':'LOCAL-CLAIMS',
              'path':str(original),'sha256':sha256_file(original),'bytes':original.stat().st_size,
              'kind':'public_document','checked_at':'2026-09-29T00:00:00Z','source_url':'https://example.invalid/exact-record'}],
              'coverage_notes':[]}
            validate_supplement(supplement,root)
            original.write_text('changed original')
            with self.assertRaises(ValueError): validate_supplement(supplement,root)
            original.unlink()
            with self.assertRaises((OSError,ValueError)): validate_supplement(supplement,root)

    def test_only_v3_refinement_reuses_bounded_waiting_not_old_contract(self):
        fixture=fixtures.ApiFirstPlanningTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        parent=fixture.primary();run=fixture.source(parent);term={'kind':'structural_feature','value':'strap fastener',
          'language':'en','derived_from':parent['derived_from'][0]}
        for revision,expected in [('api-first-v3',True),('api-first-v1',False)]:
            with self.subTest(revision=revision):
                task=deepcopy(fixture.task);task['retrieval_workflow_revision']=revision
                row=ap.make_row(task,'serper_patents',term,parent['jurisdiction'],parent['right_type'],parent['requirement_ids'],
                  parent=parent,role='refinement')
                plan=deepcopy(fixture.plan);plan['queries']['serper_patents'].append(row)
                task.setdefault('discovery_followups',[]).append({'query_id':row['query_id'],
                  'plan_entry_sha256':sha256_json(row),'parent_plan_entry_sha256':sha256_json(parent),
                  'parent_query_id':parent['query_id'],'source_run_id':run['run_id'],'source_run_sha256':sha256_json(run),
                  'term':term,'reason_code':'refine_scope','reviewer':'synthetic','reason':'broader exact concept',
                  'evidence_ids':['EV-'+run['run_id']],
                  'triage_digest':ap.triage_digest(task,fixture.evidence,fixture.candidates,fixture.ledger,query_id=parent['query_id'])})
                with patch('api_first_planning.source_card_state',return_value=(None,[])) as cards, \
                     patch('api_first_planning.retained_discovery_work',return_value=None) as retained:
                    self.assertIsNone(ap.followup_validation(task,plan,fixture.evidence,fixture.candidates,fixture.ledger,row))
                    self.assertEqual(cards.call_args.kwargs['allow_bounded_waiting'],expected)
                    self.assertEqual(retained.call_args.kwargs['allow_bounded_waiting'],expected)
                with patch('api_first_planning.source_card_state',return_value=('API_DISCOVERY_TRIAGE_REQUIRED',[])):
                    self.assertEqual(ap.followup_validation(task,plan,fixture.evidence,fixture.candidates,fixture.ledger,row),
                                     'API_DISCOVERY_TRIAGE_REQUIRED')
                with patch('api_first_planning.source_card_state',return_value=(None,[])), \
                     patch('api_first_planning.retained_discovery_work',return_value={'reason':'UNREAD_SOURCE_LOOKUP'}):
                    self.assertEqual(ap.followup_validation(task,plan,fixture.evidence,fixture.candidates,fixture.ledger,row),
                                     'UNREAD_SOURCE_LOOKUP')

if __name__=='__main__': unittest.main()
