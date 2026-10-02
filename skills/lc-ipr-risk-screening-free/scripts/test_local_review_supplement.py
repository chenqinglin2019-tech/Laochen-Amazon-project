"""Public provenance uses validated supplement references, without closing private gaps."""
import copy
import unittest
from common import atomic_write_json,sha256_json
import test_public_identity as fixtures
from review_progress_stage_a import _local_asset_review_complete

class LocalSupplementTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PublicIdentityTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.supplement.stop()
        self.row=next(q for q in self.f.plan['queries']['asset_provenance'] if q['right_type']=='copyright' and q['search_dimension']=='provenance')
        self.row.update(operation='provenance_review')
        self.run=next(r for r in self.f.evidence['source_runs'] if r['query_id']==self.row['query_id'])
        self.run.update(provider='asset_provenance',operation='provenance_review',source_environment='local_agent_review',submission_state='not_submitted',
            jurisdiction='US',right_type='copyright',plan_entry_sha256=sha256_json(self.row))
        self.entry=next(e for e in self.f.evidence['collections']['official_verifications'] if e['source_run_id']==self.run['run_id'])
        for key in ('provider','operation','jurisdiction','right_type','plan_entry_sha256'):self.entry[key]=self.run[key]
        self.supplement={'evidence':self.f.evidence['collections'].pop('source_materials')}
        atomic_write_json(self.f.root/'supplemental-evidence.json',self.supplement)
        self.item={'scope':{'scenario_id':'product_entry'}}
    def complete(self,path=True):
        return _local_asset_review_complete(self.f.task,self.f.evidence,self.row,self.item,self.run,self.f.root if path else None)
    def test_actual_public_steps_and_private_request_resolve_supplement_refs(self):
        before=copy.deepcopy(self.entry['payload'])
        self.assertFalse(self.complete(path=False));self.assertTrue(self.complete())
        self.assertEqual(self.entry['payload'],before)
        self.assertTrue(self.entry['payload']['outstanding_actions']);self.assertTrue(self.entry['payload']['unresolved'])
    def test_missing_reference_or_changed_original_does_not_promote(self):
        self.supplement['evidence'].pop(0);atomic_write_json(self.f.root/'supplemental-evidence.json',self.supplement)
        self.assertFalse(self.complete())
    def test_corrupt_supplement_is_rejected(self):
        (self.f.root/'supplemental-evidence.json').write_text('not json')
        self.assertFalse(self.complete())
    def test_unfinished_public_step_or_malformed_private_action_stays_open(self):
        step=self.entry['payload']['investigation_steps'][0];step['status']='pending'
        self.assertFalse(self.complete());step['status']='completed'
        self.entry['payload']['outstanding_actions'][0]['kind']='public_investigation'
        self.assertFalse(self.complete())
    def test_stage_outcome_consumer_passes_same_validated_supplement_path(self):
        from stage_risk_stage_b import _completed_outcome,_version
        atomic_write_json(self.f.root/'search-plan.json',self.f.plan)
        scope={'scenario_id':'product_entry','jurisdiction':'US','right_type':'copyright',
            'module_id':'copyright_ip','product_version':_version(self.f.task)}
        registry={'RUN-REF':{'origin':'run','row':self.run}}
        self.assertIsNone(_completed_outcome(self.f.root,self.f.task,self.f.evidence,registry,['RUN-REF'],scope))

    def test_material_hash_change_is_rejected(self):
        from pathlib import Path
        Path(self.supplement['evidence'][0]['path']).write_bytes(b'Changed original')
        self.assertFalse(self.complete())

if __name__=='__main__':unittest.main()
