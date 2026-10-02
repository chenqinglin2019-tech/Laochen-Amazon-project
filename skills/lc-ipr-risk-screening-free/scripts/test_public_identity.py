"""Offline receipt/shared-reading integration; scoped triage is supplied by its tested contract."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import atomic_write_json, load_json, sha256_file, sha256_json
from public_identity import record, current, binding, limitation
from source_result_processing import make_index
from record_asset_provenance import asset_scope, INVESTIGATION_STEPS
import test_asset_scope


class PublicIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        f = test_asset_scope.AssetScopeTests(); f.setUp(); self.task = f.task
        self.task.update(task_id='PUBLIC-ID-TEST',retrieval_workflow_revision='api-first-v3',
            public_discovery_routing_revision='public-discovery-v1',completion_policy_revision='necessary-work-v3',
            target_jurisdictions=['US'],result_processing_revision='source-result-processing-v1')
        self.evidence = {'collections':{},'source_runs':[]}
        for eid, name, kind in [('EV-PRODUCT','source.txt','provenance_document'),('EV-IMAGE','image.png','source_image')]:
            path = self.root/name; path.write_bytes(b'offline original reading fixture')
            self.evidence['collections'].setdefault('source_materials',[]).append({'evidence_id':eid,'path':str(path),
                'sha256':sha256_file(path),'kind':kind,'source_url':'https://example.test/source'})
        self.plan = {'queries':{'asset_provenance':[]}}
        for right in ('copyright','trade_dress'):
            scope = asset_scope(self.task,'product_entry',right)
            for step in INVESTIGATION_STEPS[right]:
                qid = right+'-'+step
                row = {'query_id':qid,'right_type':right,'search_dimension':step,'scenario_id':'product_entry',
                    'jurisdiction':'US','asset_scope_sha256':scope['scope_sha256']}
                self.plan['queries']['asset_provenance'].append(row)
                arts = [{'path':e['path'],'sha256':e['sha256'],'role':'actual original',
                    'bytes':Path(e['path']).stat().st_size} for e in self.evidence['collections']['source_materials']]
                payload = {'scenario_id':'product_entry','asset_scope_sha256':scope['scope_sha256'],
                    'coverage_attestation':{'inventory_complete':True,'asset_ids':scope['asset_ids'],'reviewed_asset_ids':scope['asset_ids']},
                    'artifacts':arts,'unresolved':['Actual author and licence unknown'],
                    'investigation_steps':[{'step':step,'status':'completed','reasoning':'Read original text and compared actual retained image',
                        'artifact_sha256':[a['sha256'] for a in arts],'evidence_refs':['EV-PRODUCT','EV-IMAGE']}],
                    'outstanding_actions':[{'action_id':'PRIVATE-'+right,'kind':'user_information','owner':'supplier',
                        'purpose':'Obtain actual supply chain authority','question':'Provide licence/original records',
                        'reasoning':'Public facts cannot establish private authorisation',
                        'evidence_needed':['supply_chain_authorization'],'evidence_refs':['EV-PRODUCT','EV-IMAGE']}]}
                run = {'run_id':'RUN-'+qid,'query_id':qid,'plan_entry_sha256':sha256_json(row),'status':'success'}
                self.evidence['source_runs'].append(run)
                self.evidence['collections'].setdefault('official_verifications',[]).append({'evidence_id':'EV-'+qid,
                    'provider':'asset_provenance','query_id':qid,'source_run_id':run['run_id'],
                    'plan_entry_sha256':sha256_json(row),'payload':payload})
        raw = {'search_metadata':{'status':'Success'},'visual_matches':[{'title':'Public toy sale','link':'https://example.test/sale'}]}
        rawpath = self.root/'lens.json'; atomic_write_json(rawpath,raw)
        index = make_index(self.task,provider='serpapi_google_lens',evidence_type='copyright',status='success',
            submission_state='submitted',raw_body=rawpath.read_bytes(),raw_suffix='json',normalized={},
            coverage={'schema_valid':True,'retrieved_hits':1},payload_digest=sha256_file(rawpath))
        digest = index['rows'][0]['raw_sha256']
        run = {'run_id':'LENS-R','provider':'serpapi_google_lens','status':'success','submission_state':'submitted',
            'jurisdiction':'US','raw_paths':[str(rawpath)],'payload_digest':sha256_file(rawpath),'result_processing':index}
        self.evidence['source_runs'].append(run)
        self.evidence['result_dispositions'] = [{'source_run_id':'LENS-R','position':1,'raw_sha256':digest,
            'payload_digest':run['payload_digest'],'outcome':'candidate','candidate_ids':['C1'],'reviewer':'agent','reason':'Read exact acquired card'}]
        self.candidate = {'candidate_id':'C1','right_type':'unknown','source_index':'google_lens','match_type':'visual_matches',
            'title':'Public toy sale','sources':[{'provider':'serpapi_google_lens','source_collection':'visual_matches',
                'source_run_id':'LENS-R','source_record_sha256':digest,'record_fields':{'title':'Public toy sale','url':'https://example.test/sale'}}]}
        self.candidates = {'copyright_assets':[self.candidate]}
        self.ledger = {'annotations':[]}
        self.scope = {'candidate_id':'C1','scenario_id':'product_entry','jurisdiction':'UNLOCATED','right_type':'unknown'}
        self.annotation = {'annotation_id':'ANN-1','candidate_relation':{'identity_gaps':['right_type'],
            'direction_ids':['actual-shape'],'product_object_ids':['shape']}}
        self.decision = {**self.scope,'current':True,'decision':'selected','annotation':self.annotation,'next_actions':[]}
        self.request = {**self.scope,'reading_purpose':'source_association',
            'shared_query_ids':[q['query_id'] for q in self.plan['queries']['asset_provenance']],
            'individual_image_use':'not_used_for_expression_or_authorship',
            'unresolved_facts':['right_type','rights_holder','first_publication','supply_chain_authorization'],
            'reviewer':'offline-agent','reason':'Read retained sale card as product/source association; no individual right established',
            'resume_condition':'Actual supplier authorisation, first-publication and right identity material becomes available'}
        for name,value in [('task.json',self.task),('evidence.json',self.evidence),('search-plan.json',self.plan),
                           ('normalized-candidates.json',self.candidates),('materiality-annotations.json',self.ledger)]:
            atomic_write_json(self.root/name,value)
        self.triage = patch('decision_workflow.triage_summary',side_effect=lambda *a,**kw:{'records':[self.decision]})
        self.triage.start(); self.addCleanup(self.triage.stop)
        self.supplement = patch('workflow_v24.scenario_supplement',return_value=None)
        self.supplement.start(); self.addCleanup(self.supplement.stop)

    def append(self):
        event = record(self.root,self.request)
        self.evidence = load_json(self.root/'evidence.json')
        return event

    def test_record_reuses_exact_scope_without_inventing_identity(self):
        before = copy.deepcopy(self.evidence)
        event = self.append()
        self.assertEqual(record(self.root,self.request),event)
        self.assertEqual(current(self.task,self.evidence,self.candidates,self.ledger,self.scope),event)
        self.assertEqual(self.evidence['source_runs'],before['source_runs'])
        self.assertEqual(self.evidence['collections'],before['collections'])
        self.assertEqual(self.candidate['right_type'],'unknown')
        projected = limitation(event,{**self.scope,'kind':'agent_investigation'})
        from necessary_completion import _delivery_limit_valid
        self.assertTrue(_delivery_limit_valid(projected,self.task,self.evidence,self.plan,{},candidates=self.candidates,
            ledger=self.ledger,task_dir=self.root))
        self.assertEqual(projected['state'],'blocked')

    def test_tamper_material_change_and_scope_change_invalidate(self):
        self.append()
        for mutate in (lambda e:e['public_identity_investigations'][0].update(reason='changed'),
                       lambda e:e['source_runs'][0].update(status='failed')):
            e = copy.deepcopy(self.evidence); mutate(e)
            self.assertIsNone(current(self.task,e,self.candidates,self.ledger,self.scope))
        c = copy.deepcopy(self.candidates); c['copyright_assets'][0]['title']='different product'
        self.assertIsNone(current(self.task,self.evidence,c,self.ledger,self.scope))
        self.assertIsNone(current(self.task,self.evidence,self.candidates,self.ledger,{**self.scope,'jurisdiction':'US'}))
        (self.root/'image.png').write_bytes(b'changed actual image')
        self.assertIsNone(current(self.task,self.evidence,self.candidates,self.ledger,self.scope))

    def test_unread_images_explicit_next_actions_and_unknown_patents_remain_pending(self):
        self.decision['decision']='needs_info'
        self.decision['next_actions']=[{'kind':'agent_read','purpose':'Read missing figure'}]
        with self.assertRaisesRegex(ValueError,'CURRENT_ASSOCIATION'):
            self.append()
        self.decision.update(decision='selected',next_actions=[])
        self.candidate['publication_number']='US1234567B2'
        with self.assertRaisesRegex(ValueError,'NOT_PUBLIC_SALES_LEAD'):
            binding(self.root,self.task,self.evidence,self.candidates,self.ledger,self.request)
        self.candidate.pop('publication_number')
        self.candidates = {'patents':[self.candidate]}
        with self.assertRaisesRegex(ValueError,'CANDIDATE_INVALID'):
            binding(self.root,self.task,self.evidence,self.candidates,self.ledger,self.request)

    def test_failed_cross_country_unreviewed_and_incomplete_public_material_refuse(self):
        for mutate in (lambda e:e['source_runs'][-1].update(status='failed'),
                       lambda e:e['source_runs'][-1].update(jurisdiction='GB'),
                       lambda e:e.update(result_dispositions=[]),
                       lambda e:e['collections']['official_verifications'][0]['payload']['investigation_steps'][0].update(status='pending')):
            e = copy.deepcopy(self.evidence); mutate(e)
            with self.assertRaises(ValueError):
                binding(self.root,self.task,e,self.candidates,self.ledger,self.request)

    def test_old_tasks_and_image_expression_claims_cannot_use_exception(self):
        t = copy.deepcopy(self.task); t['retrieval_workflow_revision']='api-first-v2'
        with self.assertRaisesRegex(ValueError,'SCOPE_INVALID'):
            binding(self.root,t,self.evidence,self.candidates,self.ledger,self.request)
        self.request['individual_image_use']='all_expressions_read'
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):
            self.append()

    def test_source_card_consumer_accepts_bound_association_but_tamper_reopens(self):
        from api_first_planning import source_card_state
        row = {'query_id':'LENS-Q'}
        self.candidate['sources'][0]['plan_entry_sha256'] = sha256_json(row)
        atomic_write_json(self.root/'normalized-candidates.json',self.candidates)
        self.append()
        run = next(r for r in self.evidence['source_runs'] if r['run_id']=='LENS-R')
        cards = [{'source_record_sha256':self.candidate['sources'][0]['source_record_sha256']}]
        with patch('serpapi_lens_client.retained_source_records',return_value=cards), \
             patch('decision_workflow.triage_scope_enabled',return_value=True), \
             patch('assessment_v24._query_candidates',return_value=[self.candidate]):
            self.assertIsNone(source_card_state(self.task,self.evidence,self.candidates,self.ledger,row,run)[0])
            (self.root/'image.png').write_bytes(b'changed actual file')
            self.assertEqual(source_card_state(self.task,self.evidence,self.candidates,self.ledger,row,run)[0],
                'API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED')

    def test_scoped_excluded_public_context_does_not_require_fabricated_type(self):
        from api_first_planning import source_card_state
        row = {'query_id':'PUBLIC-Q'}
        self.candidate['sources'][0].update(provider='serper_web',plan_entry_sha256=sha256_json(row))
        candidates = {'enforcement':[self.candidate]}
        self.decision.update(decision='not_selected')
        self.annotation['comparison'] = {'difference':'The acquired article concerns an unrelated charger recall',
            'applicability_limit':'Only this article is excluded; no clearance for the target toy'}
        run = next(r for r in self.evidence['source_runs'] if r['run_id']=='LENS-R')
        run = {**run,'provider':'serper_web'}
        cards = [{'source_record_sha256':self.candidate['sources'][0]['source_record_sha256']}]
        with patch('assessment_v24._source_records',return_value=cards), \
             patch('decision_workflow.triage_scope_enabled',return_value=True), \
             patch('assessment_v24._query_candidates',return_value=[self.candidate]):
            self.assertIsNone(source_card_state(self.task,self.evidence,candidates,self.ledger,row,run)[0])
            self.annotation['comparison'].pop('difference')
            self.assertEqual(source_card_state(self.task,self.evidence,candidates,self.ledger,row,run)[0],
                'API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED')
            self.annotation['comparison']['difference']='Different article subject'
            self.decision['current']=False
            self.assertEqual(source_card_state(self.task,self.evidence,candidates,self.ledger,row,run)[0],
                'API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED')




class PublicIdentitySnapshotTests(unittest.TestCase):
    setUp = PublicIdentityTests.setUp
    append = PublicIdentityTests.append

    def snapshot(self):
        from public_identity import validation_snapshot
        return validation_snapshot(self.root,self.task,self.evidence,self.candidates,self.plan,self.ledger)

    def read(self, scope=None):
        return current(self.task,self.evidence,self.candidates,self.ledger,scope or self.scope)

    def test_one_binding_and_shared_validation_per_view_preserve_original_event(self):
        import public_identity as public
        event = self.append()
        frozen = copy.deepcopy(self.evidence)
        with patch('public_identity.binding',wraps=public.binding) as verified, \
             patch('public_identity._shared_packages',wraps=public._shared_packages) as shared:
            with self.snapshot() as first:
                for _ in range(8):
                    self.assertEqual(self.read(),event)
                self.assertEqual(verified.call_count,1)
                self.assertEqual(shared.call_count,1)
                self.assertGreater(len(first['files']),0)
            self.assertEqual(first['memo'],{})
            self.assertEqual(first['files'],{})
            with self.snapshot() as second:
                self.assertIsNot(first,second)
                self.assertEqual(self.read(),event)
            self.assertEqual(verified.call_count,2)
            self.assertEqual(shared.call_count,2)
        self.assertEqual(self.evidence,frozen)

    def test_two_candidate_bindings_share_exact_source_package_validation(self):
        import public_identity as public
        second = copy.deepcopy(self.candidate); second['candidate_id']='C2'
        self.candidates['copyright_assets'].append(second)
        self.evidence['result_dispositions'][0]['candidate_ids'].append('C2')
        d2 = copy.deepcopy(self.decision); d2['candidate_id']='C2'; d2['annotation']['annotation_id']='ANN-2'
        for name,value in [('evidence.json',self.evidence),('normalized-candidates.json',self.candidates)]:
            atomic_write_json(self.root/name,value)
        with patch('decision_workflow.triage_summary',return_value={'records':[self.decision,d2]}):
            e1=self.append()
            e2=record(self.root,{**self.request,'candidate_id':'C2'})
            self.evidence=load_json(self.root/'evidence.json')
            with patch('public_identity._shared_packages',wraps=public._shared_packages) as shared:
                with self.snapshot():
                    self.assertEqual(self.read(),e1)
                    self.assertEqual(self.read({**self.scope,'candidate_id':'C2'}),e2)
                    self.assertEqual(shared.call_count,1)

    def test_every_unique_dependency_hashed_at_start_and_exit(self):
        import public_identity as public
        self.append()
        with patch('public_identity.sha256_file',wraps=public.sha256_file) as hashed:
            with self.snapshot() as state:
                self.assertIsNotNone(self.read())
                for _ in range(4): self.assertIsNotNone(self.read())
                paths=set(state['files'])
                counts={path:sum(call.args[0] == path for call in hashed.call_args_list) for path in paths}
                self.assertTrue(all(count == 1 for count in counts.values()))
            for path in paths:
                self.assertEqual(sum(call.args[0] == path for call in hashed.call_args_list),2)

    def test_same_length_same_mtime_file_change_rejects_entire_view(self):
        import os
        self.append()
        path=self.root/'image.png'; before=path.stat(); original=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_CHANGED'):
            with self.snapshot():
                self.assertIsNotNone(self.read())
                path.write_bytes(b'x'*len(original))
                os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
                self.assertIsNotNone(self.read())  # Pending until the boundary validates bytes.
        self.assertIsNone(self.read())

    def test_deleted_file_rejects_even_after_a_cached_positive(self):
        self.append()
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_CHANGED'):
            with self.snapshot():
                self.assertIsNotNone(self.read())
                (self.root/'source.txt').unlink()
                self.assertIsNotNone(self.read())

    def test_missing_initial_file_cannot_be_swallowed_by_current(self):
        self.append(); (self.root/'lens.json').unlink()
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_BINDING_CHANGED'):
            with self.snapshot():
                self.assertIsNone(self.read())

    def test_plan_change_rejects_cached_proof(self):
        self.append()
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_CHANGED'):
            with self.snapshot():
                self.assertIsNotNone(self.read())
                altered=copy.deepcopy(self.plan)
                altered['queries']['asset_provenance'][0]['jurisdiction']='GB'
                atomic_write_json(self.root/'search-plan.json',altered)
                self.assertIsNotNone(self.read())
        self.assertIsNone(self.read())

    def test_same_path_different_expected_digest_is_poisoned_even_if_caught(self):
        import public_identity as public
        self.append()
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_BINDING_CHANGED'):
            with self.snapshot() as state:
                self.assertIsNotNone(self.read())
                with self.assertRaisesRegex(ValueError,'VIEW_FILE_BINDING_CHANGED'):
                    public._guard_file(state,self.root/'image.png','0'*64)

    def test_inputs_mutation_rejects_scope_receipt_and_permission_changes(self):
        self.append()
        original=copy.deepcopy(self.evidence)
        for field in ('jurisdiction','status','fixture'):
            with self.subTest(field=field):
                self.evidence=copy.deepcopy(original)
                with self.assertRaisesRegex(ValueError,'VIEW_INPUT_CHANGED'):
                    with self.snapshot():
                        self.assertIsNotNone(self.read())
                        self.evidence['source_runs'][-1][field]={'jurisdiction':'GB','status':'failed','fixture':True}[field]
                        self.assertIsNotNone(self.read())
                self.assertIsNone(self.read())

    def test_exception_always_clears_and_new_view_checks_files_again(self):
        import public_identity as public
        self.append()
        with self.assertRaisesRegex(RuntimeError,'abort'):
            with self.snapshot() as state:
                self.assertIsNotNone(self.read())
                raise RuntimeError('abort')
        self.assertEqual(state['memo'],{})
        self.assertEqual(state['files'],{})
        self.assertIsNone(public._VALIDATION.get())
        (self.root/'image.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_BINDING_CHANGED'):
            with self.snapshot(): self.assertIsNone(self.read())

    def test_other_input_objects_and_task_paths_do_not_borrow_validation(self):
        import public_identity as public
        self.append()
        with self.snapshot():
            self.assertIsNotNone(self.read())
            changed=copy.deepcopy(self.evidence); changed['source_runs'][-1]['jurisdiction']='GB'
            self.assertIsNone(current(self.task,changed,self.candidates,self.ledger,self.scope))
            self.assertIsNone(current(self.task,self.evidence,self.candidates,self.ledger,self.scope,
                task_dir=self.root/'different-task'))
            with public.validation_snapshot(self.root,self.task,changed,self.candidates,self.plan,self.ledger):
                self.assertIsNone(current(self.task,changed,self.candidates,self.ledger,self.scope))
            self.assertIsNotNone(self.read())

    def test_symlink_retarget_to_same_bytes_is_rejected(self):
        self.append()
        original=self.root/'image.png'; saved=self.root/'original.png'
        original.rename(saved); original.symlink_to(saved)
        other=self.root/'other.png'; other.write_bytes(saved.read_bytes())
        with self.assertRaisesRegex(ValueError,'VIEW_FILE_CHANGED'):
            with self.snapshot():
                self.assertIsNotNone(self.read())
                original.unlink(); original.symlink_to(other)
                self.assertIsNotNone(self.read())


if __name__ == '__main__': unittest.main()
