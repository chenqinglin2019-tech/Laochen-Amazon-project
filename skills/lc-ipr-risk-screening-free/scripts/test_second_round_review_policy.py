"""Real recorders and dispatch gates, isolated synthetic files; no external calls."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
from common import atomic_write_json, load_json, sha256_file, sha256_json
from execution_efficiency import REVISION, DEFAULTS
from review_material_policy import REVISION as MATERIAL_REVISION


class MaterialPolicyTests(unittest.TestCase):
    def setUp(self):
        from test_product_scope import ScopeTests
        self.fixture = ScopeTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        document = f.f.root / 'provided-structure.txt'
        document.write_text('LOCAL-ORIGINAL-NOT-FOR-TRANSMISSION-unique structure fact', encoding='utf-8')
        f.data['sources'].append({'source_id':'document', 'kind':'document', 'path':str(document)})
        f.data['scope']['facts'][0]['source_refs'].append('document')
        f.save()
        self.packet = {'task': {'task_id':'SYNTHETIC-MATERIALS', 'images':[],
            'assessment_scenarios':[{'scenario_id':'product_entry','type':'product_entry'}],
            'target_jurisdictions':['US'], 'review_policy_revision':'final-double-review-v1',
            'execution_efficiency_revision':REVISION, 'execution_efficiency':deepcopy(DEFAULTS),
            'review_material_policy_revision':MATERIAL_REVISION,
            'final_review_execution_revision':'adaptive-double-review-v2'},
            'evidence':load_json(f.run/'evidence.json'), 'candidates':{},
            'materiality_ledger':{}, 'search_plan':{'queries':{}}}

    def attach(self, packet=None):
        from module_review import attach_originals
        packet = self.packet if packet is None else packet
        return attach_originals(packet, self.fixture.run)

    def test_real_scope_receipt_is_inline_and_local_document_not_sent(self):
        from adaptive_review import measure, prepare
        from report_review_host import review_payload_view
        images = self.attach()
        originals = self.packet['retained_originals']
        self.assertTrue(originals['inline_internal_receipts'])
        self.assertTrue(originals['not_transmitted'])
        self.assertEqual(images, {})
        serialized = json.dumps(review_payload_view(self.packet), ensure_ascii=False)
        self.assertNotIn('LOCAL-ORIGINAL-NOT-FOR-TRANSMISSION', serialized)
        counts = measure(self.packet, images)
        self.assertEqual(counts['review_units'], 9)
        self.assertEqual(counts['review_text_chars'], 0)
        self.assertIsNotNone(prepare(self.packet, self.fixture.run, []))

    def test_old_material_contract_keeps_original_fallback_without_mutation(self):
        from adaptive_review import prepare
        old = deepcopy(self.packet); old['task'].pop('review_material_policy_revision')
        before = deepcopy(old)
        self.assertIsNone(prepare(old, self.fixture.run, []))
        self.assertEqual(old, before)

    def test_internal_receipt_tamper_is_rejected(self):
        row = self.packet['evidence']['collections']['product_scope'][0]
        Path(row['path']).write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH|RECEIPT_CHANGED'):
            self.attach()

    def test_local_original_tamper_is_rejected_without_transmitting(self):
        document = next(row for row in self.packet['evidence']['collections']['scope_sources'] if row.get('kind')=='document')
        Path(document['path']).write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH|BYTES_MISMATCH'):
            self.attach()

    def test_internal_inline_mutation_and_missing_payload_are_rejected(self):
        for mode in ('changed', 'missing'):
            packet=deepcopy(self.packet)
            receipt=packet['evidence']['collections']['product_scope'][0]
            if mode=='changed':receipt['payload']['scope']['reasoning']='Rewritten inline facts'
            else:receipt.pop('payload')
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,'INLINE_MISMATCH'):
                self.attach(packet)

    def test_unknown_local_file_is_preparation_problem_not_implicit_exclusion(self):
        file=self.fixture.run/'unknown.txt';file.write_text('Unregistered local original',encoding='utf-8')
        self.packet['evidence']['collections']['untrusted']=[{'kind':'internal','evidence_id':'OTHER',
            'path':str(file),'sha256':sha256_file(file)}]
        with self.assertRaisesRegex(ValueError,'CLASSIFICATION_REQUIRED'):
            self.attach()

    def test_actual_module_projection_preserves_valid_inline_receipt(self):
        from module_review import module_packet
        self.packet['evidence_digest']='synthetic-material-digest'
        for group in ('technical','appearance','expression'):
            packet=module_packet(self.packet,group)
            self.attach(packet)
            self.assertTrue(packet['retained_originals']['inline_internal_receipts'])

    def test_self_declared_internal_kind_cannot_exempt_public_original(self):
        from adaptive_review import measure
        file = self.fixture.run / 'not-supported.bin';file.write_bytes(b'Public unsupported source')
        self.packet['evidence']['collections']['untrusted']=[{'kind':'internal','evidence_id':'OTHER',
            'path':str(file),'sha256':sha256_file(file),'source_url':'https://example.org/source.bin'}]
        images = self.attach()
        with self.assertRaisesRegex(ValueError, 'MANIFEST_INCOMPLETE'):
            measure(self.packet, images)

    def test_not_transmitted_requires_ack_and_existing_statement_limit(self):
        from module_review import validate_original_observations
        self.attach()
        hashes = {row['sha256'] for row in self.packet['retained_originals']['not_transmitted']}
        raw = {'final_review_statement':{'limitations':'Original local document was not transmitted or read.'},
            'untransmitted_material_acknowledgements':{h:{'original_read':False,
                'limitations':'Original local document was not transmitted or read.'} for h in hashes}}
        validate_original_observations(raw, self.packet)
        bad=deepcopy(raw);next(iter(bad['untransmitted_material_acknowledgements'].values()))['original_read']=True
        with self.assertRaisesRegex(ValueError,'READING_CLAIM_INVALID'):validate_original_observations(bad,self.packet)
        bad=deepcopy(raw);bad['final_review_statement']['limitations']='Other limits only'
        with self.assertRaisesRegex(ValueError,'LIMITATION_DROPPED'):validate_original_observations(bad,self.packet)
        summary={'task':self.packet['task'],'modules':[{'judgment':raw}]}
        validate_original_observations(raw,summary)
        with self.assertRaisesRegex(ValueError,'LIMITATION_DROPPED'):validate_original_observations(bad,summary)

    def test_inventory_missing_or_falsely_reclassified_rejected(self):
        from adaptive_review import measure
        images=self.attach()
        broken=deepcopy(self.packet);broken['retained_originals']['file_inventory'].pop()
        with self.assertRaisesRegex(ValueError,'MANIFEST_INCOMPLETE|CLASSIFICATION_MISMATCH'):measure(broken,images)
        broken=deepcopy(self.packet);broken['retained_originals']['not_transmitted']=[]
        with self.assertRaisesRegex(ValueError,'CLASSIFICATION_MISMATCH'):measure(broken,images)


class FollowupContentTests(unittest.TestCase):
    def setUp(self):
        from offline_test_support import isolated_test_environment
        from test_scenario_planning import ScenarioPlanningTests
        self.environment=isolated_test_environment();self.environment.__enter__()
        self.addCleanup(self.environment.__exit__,None,None,None)
        self.f=ScenarioPlanningTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        f=self.f
        self.action={'action_id':'N1','kind':'source_lookup','purpose':'read_goods','provider':'uspto_tsdr',
            'operation':'candidate_verification','params':{'q':'88418732','serial_number':'88418732',
                'candidate_id':f.candidate['candidate_id'],'mode':'agent','strategy':'record_number'},
            'max_attempts':1,'required_facts':['goods_services'],'reading_scope':{'level':'goods_services'},
            'followup_basis':{'missing_fact':'Goods scope', 'existing_evidence_refs':['E1']}}
        self.old=f.annotate('needs_info',missing_information=['Goods scope'],next_actions=[self.action])
        from workflow_v24 import append_candidate_actions
        append_candidate_actions(f.path,f.task,f.candidates)
        self.old_row=load_json(f.path/'search-plan.json')['queries']['uspto_tsdr'][0]
        self.run={'run_id':'OLD-UNKNOWN','provider':'uspto_tsdr','query_id':self.old_row['query_id'],
            'plan_entry_sha256':sha256_json(self.old_row),'status':'failed','submission_state':'unknown'}
        f.evidence['source_runs'].append(self.run)

    def revise(self, *, new_content=False, refs=None, retained_path=None):
        f=self.f
        duplicate=deepcopy(f.evidence['collections']['trademarks'][0]);duplicate['evidence_id']='E2'
        if new_content:duplicate['payload']['goods_services']=['New genuine supporting source detail']
        if retained_path is not None:duplicate.update(path=str(retained_path),sha256=sha256_file(retained_path))
        f.evidence['collections']['trademarks'].append(duplicate)
        action=deepcopy(self.action);action['action_id']='N2';action['followup_basis']['existing_evidence_refs']=refs or ['E2']
        new=f.annotate('needs_info',evidence_refs=['E1','E2'],missing_information=['Goods scope'],next_actions=[action])
        from workflow_v24 import append_candidate_actions
        append_candidate_actions(f.path,f.task,f.candidates)
        return new,load_json(f.path/'search-plan.json')['queries']['uspto_tsdr'][-1]

    def gate(self,row):
        from workflow_v24 import scenario_dispatch_block_from_dir
        return scenario_dispatch_block_from_dir(self.f.path,'uspto_tsdr',row)

    def test_same_content_different_id_blocked_by_complete_dispatch_gate(self):
        new,row=self.revise()
        self.assertEqual(self.old['annotation']['basis_sha256'],new['annotation']['basis_sha256'])
        self.assertNotEqual(self.old_row['query_id'],row['query_id'])
        self.assertEqual(self.gate(row)['code'],'TRIAGE_ATTEMPT_STATE_UNKNOWN')

    def test_new_material_does_not_clear_unknown_wire_submission(self):
        new,row=self.revise(new_content=True)
        self.assertNotEqual(self.old['annotation']['basis_sha256'],new['annotation']['basis_sha256'])
        self.assertEqual(self.gate(row)['code'],'TRIAGE_ATTEMPT_STATE_UNKNOWN')

    def test_duplicate_unordered_refs_do_not_create_another_submitted_attempt(self):
        from followup_identity import CONTENT_FIELD
        self.run.update(submission_state='submitted',status='success')
        old_bytes=json.dumps(self.old['annotation'],ensure_ascii=False,sort_keys=True)
        new,row=self.revise(refs=['E2','E1','E2'])
        old_basis=self.old['annotation']['next_actions'][0]['followup_basis']
        new_basis=new['annotation']['next_actions'][0]['followup_basis']
        self.assertEqual(old_basis[CONTENT_FIELD],new_basis[CONTENT_FIELD])
        self.assertEqual(self.gate(row)['code'],'TRIAGE_REVIEW_REQUIRED')
        self.assertEqual(json.dumps(self.f.ledger['annotations'][0],ensure_ascii=False,sort_keys=True),old_bytes)

    def test_same_retained_hash_at_different_paths_does_not_create_attempt(self):
        first=self.f.path/'same-original-one.txt';second=self.f.path/'same-original-two.txt'
        first.write_bytes(b'Identical source original');second.write_bytes(first.read_bytes())
        self.f.evidence['collections']['trademarks'][0].update(path=str(first),sha256=sha256_file(first))
        self.run.update(submission_state='submitted',status='success')
        _,row=self.revise(retained_path=second)
        self.assertNotEqual(str(first),str(second))
        self.assertEqual(sha256_file(first),sha256_file(second))
        self.assertEqual(self.gate(row)['code'],'TRIAGE_REVIEW_REQUIRED')

    def unsigned_history(self):
        """Construct an old receipt fixture; the production gate must not rewrite it."""
        from followup_identity import CONTENT_FIELD
        from workflow_v24 import append_candidate_actions
        f=self.f
        legacy=deepcopy(self.old['annotation'])
        legacy['next_actions'][0]['followup_basis'].pop(CONTENT_FIELD)
        f.ledger['annotations']=[legacy]
        f.evidence['source_runs']=[]
        f.save()
        plan=load_json(f.path/'search-plan.json');plan['queries']['uspto_tsdr']=[]
        atomic_write_json(f.path/'search-plan.json',plan)
        append_candidate_actions(f.path,f.task,f.candidates)
        self.old_row=load_json(f.path/'search-plan.json')['queries']['uspto_tsdr'][0]
        self.run.update(query_id=self.old_row['query_id'],plan_entry_sha256=sha256_json(self.old_row))
        f.evidence['source_runs'].append(self.run)
        f.save()
        return deepcopy(legacy)

    def test_unverifiable_legacy_content_explicitly_blocks_without_rewriting_history(self):
        self.run.update(submission_state='submitted',status='failed')
        legacy=self.unsigned_history()
        self.f.evidence['collections']['trademarks'][0]['payload']['goods_services']=['Later changed retained facts']
        _,row=self.revise()
        files={path:path.read_bytes() for path in self.f.path.iterdir() if path.is_file()}
        self.assertEqual(self.gate(row)['code'],'FOLLOWUP_IDENTITY_HISTORY_REVIEW_REQUIRED')
        self.assertEqual(self.f.ledger['annotations'][0],legacy)
        for path,raw in files.items():self.assertEqual(path.read_bytes(),raw)

    def test_confirmed_not_submitted_recovery_is_not_stuck_on_raw_unknown(self):
        from recovery_stage_b import record_review
        f=self.f;f.save()
        record_review(f.path,{'kind':'unknown_check','source_run_id':self.run['run_id'],
            'source_run_sha256':sha256_json(self.run),'reviewer':'offline-reviewer','reasoning':'Retained source confirms no submit.',
            'outcome':'not_submitted','original_receipt_review':'Inspected original request receipt',
            'basis':'Explicit original receipt says not submitted','check_method':'existing_receipt'})
        f.evidence=load_json(f.path/'evidence.json')
        _,row=self.revise()
        self.assertEqual(self.run['submission_state'],'unknown')
        self.assertIsNone(self.gate(row))

    def test_confirmed_running_blocks_same_request_even_with_new_material(self):
        from recovery_stage_b import record_review
        f=self.f;f.save()
        record_review(f.path,{'kind':'unknown_check','source_run_id':self.run['run_id'],
            'source_run_sha256':sha256_json(self.run),'reviewer':'offline-reviewer','reasoning':'Retained source confirms running.',
            'outcome':'submitted_running','original_receipt_review':'Inspected original request receipt',
            'basis':'Original source receipt says running','check_method':'existing_receipt'})
        f.evidence=load_json(f.path/'evidence.json')
        _,row=self.revise(new_content=True)
        self.assertEqual(self.run['submission_state'],'unknown')
        self.assertEqual(self.gate(row)['code'],'SOURCE_RESULT_PENDING')

    def test_submitted_same_content_still_needs_original_result_review(self):
        self.run.update(submission_state='submitted',status='success')
        _,row=self.revise()
        self.assertEqual(self.gate(row)['code'],'TRIAGE_REVIEW_REQUIRED')

    def test_action_digest_is_program_derived_without_mutating_input(self):
        from followup_identity import CONTENT_FIELD
        self.assertNotIn(CONTENT_FIELD,self.action['followup_basis'])
        stored=self.old['annotation']['next_actions'][0]['followup_basis'][CONTENT_FIELD]
        self.assertEqual(len(stored),64)
        bad=deepcopy(self.action);bad['followup_basis'][CONTENT_FIELD]='0'*64
        with self.assertRaisesRegex(ValueError,'CONTENT_MISMATCH'):
            self.f.annotate('needs_info',missing_information=['Goods'],next_actions=[bad])


if __name__=='__main__':unittest.main()
