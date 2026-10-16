"""Independent visual-host behavior: real packets, media receipts and batch recorder."""
from copy import deepcopy
from io import BytesIO, StringIO
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import json
import threading
import unittest
from unittest.mock import patch

from common import atomic_write_json,load_json,sha256_file
from offline_test_support import isolated_test_environment


class VisualHostTests(unittest.TestCase):
    def setUp(self):
        import test_execution_efficiency
        import test_decision_workflow
        self.environment=isolated_test_environment(); self.environment.__enter__()
        self.addCleanup(self.environment.__exit__,None,None,None)
        media=test_execution_efficiency.MediaTests(); media.setUp(); self.addCleanup(media.doCleanups)
        media.f.triage.stop(); media.f.supplement.stop()
        self.media=media; self.root=media.f.root; self.image=media.image
        base=test_decision_workflow.DecisionWorkflowTests(); base.setUp()
        task=base.task
        task['task_id']=media.f.task['task_id']; task['target_jurisdictions']=['US']
        task['workflow_correction_revision']='workflow-correction-v1'
        from workflow_v24 import build_coverage_requirements_v24
        task['coverage_requirements']=build_coverage_requirements_v24(['US'])
        test_execution_efficiency.enable(task)
        product=self.root/'actual-product.png'; product.write_bytes(self.image)
        task['images']=[{'image_id':'P1','path':str(product),'sha256':sha256_file(product),'bytes':product.stat().st_size}]
        atomic_write_json(self.root/'task.json',task)
        from annotate_materiality import empty_materiality_ledger
        atomic_write_json(self.root/'materiality-annotations.json',empty_materiality_ledger(task['task_id'],task=task))
        atomic_write_json(self.root/'search-plan.json',{'queries':{}})
        self.binary=self.root/'native-dummy'; self.binary.write_text('never executed')
        self.calls=[]; self.fail_ids=set(); self.failed=False; self.lock=threading.Lock()

    def download(self,*args,**kwargs):
        return self.image,'.png',(20,20),'https://images.example.test/shared.png'

    def entries(self):
        from workflow_v24 import work_view_from_dir
        return [e for e in work_view_from_dir(self.root)['entries'] if e.get('kind')=='triage' and e.get('candidate_id')]

    def raw(self,packet):
        rows=[]
        for unit in packet['units']:
            scoped=unit['guide'].get('included_product_objects')
            object_ids=list(scoped) if scoped is not None else ['product']
            directions=sorted({d for values in (scoped or {}).values() for d in values})
            gaps=unit['guide'].get('identity_gaps_prefilled_are_the_minimum',[])
            rows.append({'unit_id':unit['unit_id'],'read_image_ids':packet['product_image_ids']+unit['candidate_image_ids'],
                'adequate':True,'same_points':'The supplied motif contour is comparable','differences':'The secondary corner detail differs',
                'limitations':'Representative thumbnail does not establish the full protected work',
                'decision':'selected','reason':'Specific motif correspondence requires investigation',
                'basis_summary':'Compared the actual supplied motif images','reopen_conditions':['A different complete view is retained'],
                'comparison':{'candidate_content':'Visible circular motif','product_content':'Visible circular motif',
                    'relationship':'Specific visible expression may correspond','investigation_question':'What work and licence does this image represent?'},
                'candidate_relation':{'product_object_ids':object_ids,'direction_ids':directions,
                    'scope_reason':'Visible adopted product expression','evidence_refs':[],'identity_gaps':gaps}})
        return {'decisions':rows}

    def native(self,command,prompt,workspace,trace_path,stderr_path,timeout):
        packet=load_json(trace_path.parent/'packet.json')
        ids={u['template']['candidate_id'] for u in packet['units']}
        with self.lock:
            number=len(self.calls)+1; self.calls.append(ids)
            fail=bool(ids & self.fail_ids) and not self.failed
            if fail:self.failed=True
        stderr_path.write_text('synthetic native output only')
        if fail:
            trace_path.write_text('{"type":"turn.started"}\n')
            return SimpleNamespace(returncode=1,pid=4000+number),trace_path.read_text(),''
        raw=self.raw(packet)
        events=[{'type':'thread.started','thread_id':'visual-'+str(number)},{'type':'turn.started'},
            {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(raw)}},{'type':'turn.completed'}]
        text='\n'.join(map(json.dumps,events));trace_path.write_text(text)
        return SimpleNamespace(returncode=0,pid=4000+number),text,''

    def run_host(self):
        from visual_triage_host import run
        with patch('candidate_media.download',side_effect=self.download), \
             patch('report_review_host.run_native_logged',side_effect=self.native), \
             patch('native_review_jobs._probe',return_value=[]), \
             patch('macos_review_host.require_chatgpt_auth'),redirect_stdout(StringIO()):
            return run(self.root,binary=self.binary,isolation='macos-sandbox')

    def collected_packet(self,count=6):
        from candidate_media import collect
        from visual_triage_host import prepare_packet
        entries=self.entries()[:count]
        with patch('candidate_media.download',side_effect=self.download):
            collect(self.root,list(dict.fromkeys(e['candidate_id'] for e in entries)))
        packet,images=prepare_packet(self.root,entries)
        return entries,packet,images

    def scoped_packet(self):
        import test_product_scope
        import test_product_entry
        from candidate_media import collect
        from visual_triage_host import prepare_packet,commit
        scope=test_product_scope.ScopeTests()
        with patch.object(test_product_entry,'PNG',self.image),redirect_stdout(StringIO()):
            scope.setUp()
        self.addCleanup(scope.doCleanups)
        candidates=load_json(self.root/'normalized-candidates.json')
        candidates['copyright_assets']=candidates['copyright_assets'][:6]
        atomic_write_json(scope.run/'normalized-candidates.json',candidates)
        ev=load_json(scope.run/'evidence.json')
        retained=next(r for r in load_json(self.root/'evidence.json')['source_runs'] if r['run_id']=='LENS-R')
        copied=scope.run/'lens.json';copied.write_bytes(Path(retained['raw_paths'][0]).read_bytes())
        retained['raw_paths']=[str(copied)]
        ev['source_runs'].append(retained)
        atomic_write_json(scope.run/'evidence.json',ev)
        source=load_json(scope.run/'task.json')['product_identity']['evidence_id']
        scope.data['scope']['candidate_links']=[{'candidate_id':r['candidate_id'],'object_ids':['pattern'],
            'reason':'Retained candidate depicts the incorporated motif','source_refs':[source]}
            for r in candidates['copyright_assets']]
        with redirect_stdout(StringIO()):task=scope.save()
        self.assertEqual(task['triage_scope_revision'],'candidate-triage-scope-v1')
        from workflow_v24 import generate_plan
        with redirect_stdout(StringIO()):generate_plan(scope.run)
        from visual_triage_host import pending_entries
        entries=pending_entries(scope.run)
        with patch('candidate_media.download',side_effect=self.download):
            collect(scope.run,[r['candidate_id'] for r in candidates['copyright_assets']])
        packet,_=prepare_packet(scope.run,entries)
        return scope,entries,packet

    def test_recorded_object_scope_binds_actual_candidate_decisions(self):
        from visual_triage_host import commit
        scope,entries,packet=self.scoped_packet()
        self.assertTrue(all(u['guide']['included_product_objects']=={'pattern':['pattern']} for u in packet['units']))
        directory=scope.run/'commit';directory.mkdir()
        commit(scope.run,entries,packet,self.raw(packet),'synthetic',directory)
        rows=load_json(scope.run/'materiality-annotations.json')['annotations']
        self.assertEqual(len(rows),6)
        self.assertTrue(all(r['candidate_relation']['product_object_ids']==['pattern'] for r in rows))
        self.assertTrue(all(r['candidate_relation']['direction_ids']==['pattern'] for r in rows))
        self.assertTrue(all(r['candidate_relation']['evidence_refs'] for r in rows))

    def test_all_18_candidates_register_directly_in_three_batches(self):
        self.assertEqual(len(self.entries()),18)
        result=self.run_host()
        self.assertEqual([r['status'] for r in result['batches']],['recorded']*3,result)
        ledger=load_json(self.root/'materiality-annotations.json')
        self.assertEqual(len(ledger['annotations']),18)
        self.assertEqual({r['candidate_id'] for r in ledger['annotations']},set(self.media.ids))
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.entries(),[])

    def test_successful_batches_are_not_repeated_after_one_failure(self):
        self.fail_ids={'C0'}
        first=self.run_host()
        self.assertEqual(sorted(r['status'] for r in first['batches']),['needs_info','recorded','recorded'],first)
        prior=deepcopy(load_json(self.root/'materiality-annotations.json')['annotations'])
        self.assertEqual(len(prior),12)
        missing=set(self.media.ids)-{r['candidate_id'] for r in prior}
        second=self.run_host()
        self.assertEqual([r['status'] for r in second['batches']],['recorded'],second)
        self.assertEqual(self.calls[3:],[missing])
        ledger=load_json(self.root/'materiality-annotations.json')['annotations']
        self.assertEqual(ledger[:12],prior)
        self.assertEqual(len(ledger),18)

    def test_changed_product_input_rejects_commit_without_partial_annotations(self):
        from visual_triage_host import commit
        entries,packet,_=self.collected_packet()
        task=load_json(self.root/'task.json');task['product']['structure'].append('new actual feature')
        atomic_write_json(self.root/'task.json',task)
        before=(self.root/'materiality-annotations.json').read_bytes()
        directory=self.root/'commit';directory.mkdir()
        with self.assertRaisesRegex(ValueError,'VISUAL_INPUT_CHANGED'):
            commit(self.root,entries,packet,self.raw(packet),'synthetic',directory)
        self.assertEqual((self.root/'materiality-annotations.json').read_bytes(),before)

    def test_changed_candidate_image_bytes_rejects_commit(self):
        from visual_triage_host import commit
        entries,packet,_=self.collected_packet()
        candidate_image=next(i for i in packet['images'] if i['role']=='candidate')
        Path(candidate_image['path']).write_bytes(b'corrupt original')
        directory=self.root/'commit';directory.mkdir()
        with self.assertRaises(ValueError): commit(self.root,entries,packet,self.raw(packet),'synthetic',directory)
        self.assertEqual(load_json(self.root/'materiality-annotations.json')['annotations'],[])

    def test_pause_during_native_work_rejects_commit_and_preserves_pending_work(self):
        from visual_triage_host import commit
        from continuation_stage_c import REVISION,record_event
        task=load_json(self.root/'task.json');task['continuous_continuation_revision']=REVISION
        atomic_write_json(self.root/'task.json',task)
        evidence=load_json(self.root/'evidence.json');evidence['task_id']=task['task_id']
        atomic_write_json(self.root/'evidence.json',evidence)
        entries,packet,_=self.collected_packet()
        record_event(self.root,{'kind':'pause','actor':'user','reasoning':'Explicit pause received',
            'intent':'pause','scope':{'level':'task'},'reason':'User stopped the task'})
        directory=self.root/'pause-commit';directory.mkdir()
        with self.assertRaisesRegex(ValueError,'USER_ACTIVE_PAUSE'):
            commit(self.root,entries,packet,self.raw(packet),'synthetic',directory)
        self.assertEqual(load_json(self.root/'materiality-annotations.json')['annotations'],[])

    def test_invalid_last_unit_does_not_partially_register_first_five(self):
        from visual_triage_host import commit
        entries,packet,_=self.collected_packet();raw=self.raw(packet)
        raw['decisions'][-1]['reopen_conditions']=[]
        directory=self.root/'commit';directory.mkdir()
        with self.assertRaises(ValueError): commit(self.root,entries,packet,raw,'synthetic',directory)
        self.assertEqual(load_json(self.root/'materiality-annotations.json')['annotations'],[])

    def test_single_batch_uses_isolation_control_without_peer_batch(self):
        candidates=load_json(self.root/'normalized-candidates.json')
        candidates['copyright_assets']=candidates['copyright_assets'][:6]
        atomic_write_json(self.root/'normalized-candidates.json',candidates)
        result=self.run_host()
        self.assertEqual([r['status'] for r in result['batches']],['recorded'],result)
        self.assertEqual(len(self.calls),1)

    def test_three_unbound_product_views_do_not_silently_lose_a_view(self):
        from PIL import Image
        task=load_json(self.root/'task.json')
        for number,color in enumerate(('blue','green'),2):
            stream=BytesIO();Image.new('RGB',(20,20),color).save(stream,format='PNG')
            path=self.root/('product-'+str(number)+'.png');path.write_bytes(stream.getvalue())
            task['images'].append({'image_id':'P'+str(number),'path':str(path),
                'sha256':sha256_file(path),'bytes':path.stat().st_size})
        atomic_write_json(self.root/'task.json',task)
        result=self.run_host()
        self.assertEqual(len(result['batches']),18)
        self.assertTrue(all(r['status']=='needs_info' and 'PRODUCT_VIEWS' in r['reason'] for r in result['batches']))
        self.assertEqual(len(self.entries()),18)
        self.assertEqual(self.calls,[])
        self.assertEqual(load_json(self.root/'materiality-annotations.json')['annotations'],[])

    def add_views(self):
        from PIL import Image
        task=load_json(self.root/'task.json')
        for number,color in enumerate(('blue','green'),2):
            stream=BytesIO();Image.new('RGB',(20,20),color).save(stream,format='PNG')
            path=self.root/('product-'+str(number)+'.png');path.write_bytes(stream.getvalue())
            task['images'].append({'image_id':'P'+str(number),'path':str(path),
                'sha256':sha256_file(path),'bytes':path.stat().st_size})
        return task

    def test_object_uses_bound_view_instead_of_source_ref_or_other_product_views(self):
        from visual_triage_host import prepare_packet
        task=self.add_views()
        task['product_scope']={'objects':[{'object_id':'pattern','source_refs':['P3'],
            'visual_evidence':{'image_ids':['P2']}}]}
        atomic_write_json(self.root/'task.json',task)
        scope={'objects':[{'object_id':'pattern','scope_status':'included'}]}
        with patch('decision_workflow.candidate_scope_details',return_value=scope):
            _,packet,_=self.collected_packet()
        self.assertEqual(packet['product_image_ids'],['P2'])
        self.assertEqual([i['image_id'] for i in packet['images'] if i['role']=='product'],['P2'])
        task['product_scope']['objects'][0]['visual_evidence']['image_ids']=['missing-view']
        atomic_write_json(self.root/'task.json',task)
        with patch('decision_workflow.candidate_scope_details',return_value=scope), \
             self.assertRaisesRegex(ValueError,'IMAGE_BINDING_UNAVAILABLE'):
            prepare_packet(self.root,self.entries()[:6])

    def test_bad_candidate_preparation_does_not_block_other_candidates(self):
        from visual_triage_host import prepare_packet
        def prepare(root,entries):
            if any(e['candidate_id']=='C6' for e in entries):
                raise ValueError('VISUAL_SPLIT_REQUIRED_FOR_PRODUCT_VIEWS')
            return prepare_packet(root,entries)
        with patch('visual_triage_host.prepare_packet',side_effect=prepare):
            result=self.run_host()
        failed=[r for r in result['batches'] if r['status']=='needs_info']
        self.assertEqual(len(failed),1,result)
        self.assertEqual(failed[0]['candidate_ids'],['C6'])
        self.assertEqual(len(load_json(self.root/'materiality-annotations.json')['annotations']),17)
        self.assertEqual({e['candidate_id'] for e in self.entries()},{'C6'})

    def test_packets_are_prepared_only_when_one_of_two_execution_slots_is_free(self):
        from visual_triage_host import prepare_packet
        native=self.native
        started=set(); guard=threading.Lock(); barrier=threading.Barrier(2)
        def blocked_native(*args,**kwargs):
            packet=load_json(args[3].parent/'packet.json')
            ids={u['template']['candidate_id'] for u in packet['units']}
            with guard:
                started.update(ids)
                first=len(started)<=12
            if first: barrier.wait(timeout=5)
            return native(*args,**kwargs)
        def prepare(root,entries):
            if any(e['candidate_id']=='C12' for e in entries):
                self.assertGreaterEqual(len(started),12,'Third batch was prepared before the first two started')
            return prepare_packet(root,entries)
        self.native=blocked_native
        with patch('visual_triage_host.prepare_packet',side_effect=prepare):
            result=self.run_host()
        self.assertEqual([r['status'] for r in result['batches']],['recorded']*3,result)

    def test_needs_info_contract_registers_full_followup_through_existing_validator(self):
        from visual_triage_host import prepare_packet,commit
        from candidate_followup import action_errors
        scope,entries,_=self.scoped_packet()
        task=load_json(scope.run/'task.json')
        task['triage_followup_revision']='candidate-followup-v1'
        atomic_write_json(scope.run/'task.json',task)
        packet,_=prepare_packet(scope.run,entries)
        raw=self.raw(packet)
        for row,unit in zip(raw['decisions'],packet['units']):
            row.update(decision='needs_info',adequate=False,
                missing_information=['Full protected expression is not visible in the thumbnail'])
            row['comparison'].update(missing_fact_effect='Cannot establish whether the corner difference is material',
                completion_condition='Full image and expert comparison identify protected expression',
                existing_material_review='Thumbnail comparison leaves the fine contour unresolved')
            basis={key:'The retained thumbnail does not show the complete expression' for key in
                packet['followup_contract']['all_actions']['followup_basis']}
            basis['existing_evidence_refs']=unit['candidate_image_ids']
            row['next_actions']=[{'kind':'professional_review','purpose':'Resolve the protected expression comparison',
                'question':'Can the full design clarify the corner detail?', 'followup_basis':basis}]
        directory=scope.run/'needs-info-commit';directory.mkdir()
        with redirect_stdout(StringIO()):commit(scope.run,entries,packet,raw,'synthetic-needs-info',directory)
        rows=load_json(scope.run/'materiality-annotations.json')['annotations']
        self.assertEqual(len(rows),6)
        self.assertTrue(all(r['decision']=='needs_info' for r in rows))
        for row in rows:
            action=row['next_actions'][0]
            self.assertTrue(action['action_id'].startswith('VISUAL-ACTION-'))
            self.assertTrue(action['followup_basis']['obligation_ids'][0].startswith('VISUAL-'))
            self.assertEqual(action_errors(action,known_evidence=set(row['evidence_refs'])),[])

    def test_advertised_followup_kinds_satisfy_existing_full_action_validators(self):
        from visual_triage_host import followup_contract
        from decision_workflow import next_action_errors
        contract=followup_contract()
        basis={key:'Specific retained image cannot resolve the missing expression' for key in
            contract['all_actions']['followup_basis']}
        basis.update(obligation_ids=['VISUAL-unit'],existing_evidence_refs=['E1'])
        actions={
            'professional_review':{'question':'Which protected expression is visible?'},
            'user_information':{'question':'Who supplied this artwork?',
                'user_exclusive_reason':'Only the user knows their artwork supplier'},
            'agent_read':{'evidence_refs':['E1'],'max_attempts':1,
                'required_facts':['representative_figures'],
                'reading_scope':{'level':'representative_figures','page_numbers':[1]}},
            'source_lookup':{'provider':'epo_ops','operation':'number_lookup','params':{'publication_number':'US1234567B2'},
                'max_attempts':1,'required_facts':['current_status'],'reading_scope':{'level':'current_status'},
                'target_locator':{'kind':'publication_number','value':'US1234567B2',
                    'evidence_refs':['E1'],'unique_reason':'Exact publication ID in retained receipt'}}}
        task=load_json(self.root/'task.json')
        task.update(triage_scope_revision='candidate-triage-scope-v1',triage_followup_revision='candidate-followup-v1')
        self.assertEqual(set(actions),set(contract['kinds']))
        for kind,fields in actions.items():
            action={'action_id':'A1','kind':kind,'purpose':'Resolve the named missing fact',
                'followup_basis':deepcopy(basis),**fields}
            self.assertEqual(next_action_errors([action],task=task,known_evidence={'E1'}),[],kind)

    def test_unattached_image_reference_rejects_whole_batch(self):
        from visual_triage_host import commit
        entries,packet,_=self.collected_packet();raw=self.raw(packet)
        raw['decisions'][-1]['read_image_ids'].append('not-attached')
        directory=self.root/'commit';directory.mkdir()
        with self.assertRaisesRegex(ValueError,'IMAGE_READING'):
            commit(self.root,entries,packet,raw,'synthetic',directory)
        self.assertEqual(load_json(self.root/'materiality-annotations.json')['annotations'],[])

if __name__=='__main__':unittest.main()
