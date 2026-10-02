"""01B business contracts using a retained 01A product; offline, no live calls."""
from copy import deepcopy
from pathlib import Path
import unittest
from common import atomic_write_json,load_json,sha256_json
import test_product_entry as entry_fixture
from record_product_scope import record
import product_scope as ps
from workflow_v24 import generate_plan,work_view_from_dir,term_records,bind_scenario_action,scenario_dispatch_block

class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.f=entry_fixture.ProductEntryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.ready();self.run=self.f.run
        task=load_json(self.run/'task.json')
        # This fixture exercises the historical browser-routing contract.
        # create_task now defaults to api-first-v3, so pin its protocol explicitly.
        task['retrieval_workflow_revision']='api-first-v2'
        task.pop('product_structure_policy',None)
        task['source_operation_revision']='source-operation-v1'
        task['product_scope_required']=True
        from workflow_v24 import build_coverage_requirements_v24
        task['coverage_requirements']=build_coverage_requirements_v24(
            task['target_jurisdictions'],screening_revision=task.get('screening_revision'),
            specialty_workflow_revision=task.get('specialty_workflow_revision'))
        from common import serper_free_enhancement, serpapi_free_enhancement
        task['serper_free_enhancement']=serper_free_enhancement(False,'api-first-v2')
        task['serpapi_free_enhancement']=serpapi_free_enhancement(False,'api-first-v2')
        atomic_write_json(self.run/'task.json',task)
        ev=task['product_identity']['evidence_id']
        def obj(oid,kind,relation,intent='default',rights=None):
            return {'object_id':oid,'kind':kind,'relation':relation,'intent':intent,'description':oid,
              'location':'supplied product image','reason':'Source review supports this relationship.',
              'right_types':rights or ['copyright'],'source_refs':[ev],
              **({'statement_refs':['user']} if intent!='default' else {})}
        self.data={'schema_version':'product-scope-input-v1','expected_scope_sha256':'',
          'sources':[{'source_id':'user','kind':'user_statement','text':'Use own brand OWN. Locking method is unclear.'}],
          'scope':{'status':'reviewed','reviewer':'offline-agent','reasoning':'Separate visible outline from uncertain locking mechanism.',
            'objects':[obj('reference','brand','reference',rights=['trademark_word']),obj('pattern','pattern','integrated'),
                       obj('photo','photograph','reference'),obj('box','packaging','ancillary'),
                       obj('own','brand','own','use',['trademark_word'])],
            'facts':[{'fact_id':'lock','source_path':'product.structure[0]','value':'hinged support','status':'conflict',
                      'source_refs':[ev,'user'],'reason':'Locking mechanism not confirmed.','question':'How does the locking mechanism work?'},
                     {'fact_id':'shape','source_path':'product.title','value':'Folding stand','status':'confirmed',
                      'source_refs':[ev],'reason':'Overall outline is visible.'}],
            'directions':[{'direction_id':'locking','scenario_id':'product_entry','right_type':'patent','fact_ids':['lock'],'object_ids':[],'reason':'Depends on locking mechanism.'},
              {'direction_id':'outline','scenario_id':'product_entry','right_type':'design','fact_ids':['shape'],'object_ids':[],'reason':'Visible outline is independent of hidden lock.'},
              {'direction_id':'pattern','scenario_id':'product_entry','right_type':'copyright','fact_ids':['shape'],'object_ids':['pattern'],'reason':'Pattern is part of the product.'},
              {'direction_id':'own-mark','scenario_id':'product_entry','right_type':'trademark_word','fact_ids':[],'object_ids':['own'],'reason':'User will use OWN.'}]},
          'query_terms':[{'kind':'design','value':'folding stand','language':'en','derived_from':'product.title'}]}
        self.data['scope']['objects'][0].update(text='REFERENCE',language='en')
        self.data['scope']['objects'][4].update(text='OWN',language='en')
        self.input=self.f.root/'scope.json'
    def save(self):
        atomic_write_json(self.input,self.data);record(self.run,self.input)
        return load_json(self.run/'task.json')
    def update(self):
        self.data['expected_scope_sha256']=load_json(self.run/'task.json')['product_scope']['scope_sha256'];return self.save()
    def test_default_four_states_and_target_exceptions(self):
        task=self.save(); states={o['object_id']:o['scope_status'] for o in task['product_scope']['objects']}
        self.assertEqual(states,{'reference':'default_excluded','pattern':'included','photo':'default_excluded','box':'default_excluded','own':'included'})
        self.data['scope']['objects'][3]['relation']='target';task=self.update()
        self.assertEqual(task['product_scope']['objects'][3]['scope_status'],'included')
        self.data['scope']['objects'][2]['relation']='target';task=self.update()
        self.assertEqual(task['product_scope']['objects'][2]['scope_status'],'included')
    def test_explicit_use_exclusion_and_pending(self):
        self.data['scope']['objects'][0].update(intent='use',statement_refs=['user'])
        self.data['scope']['objects'][1].update(intent='do_not_use',statement_refs=['user'])
        task=self.save();self.assertIn('brand_reuse',task['execution_scenario_ids'])
        self.assertEqual(task['product_scope']['objects'][1]['scope_status'],'user_excluded')
        self.data['scope']['objects'][0].update(intent='uncertain',question='Keep the reference mark?',checked_information='Own brand instruction conflicts with reference mark instruction.')
        self.data['scope']['directions'].append({'direction_id':'reference-mark','scenario_id':'brand_reuse','right_type':'trademark_word','fact_ids':[],'object_ids':['reference'],'reason':'Conflicting user intent.'})
        task=self.update();work=ps.work_entries(task)
        self.assertTrue(any(v['question']=='Keep the reference mark?' for v in work))
        self.assertEqual(ps.work_entries(task),work)
    def test_own_reference_brand_bindings_and_provider_metadata(self):
        task=self.save();terms=[t for t in term_records(task) if t['kind']=='brand']
        self.assertEqual({v['value'] for v in terms},{'OWN','REFERENCE'})
        from api_first_planning import make_row
        own=next(t for t in terms if t['value']=='OWN')
        ref=next(t for t in terms if t['value']=='REFERENCE')
        self.assertTrue(ps.term_allowed(task,own,'trademark_word'));self.assertFalse(ps.term_allowed(task,ref,'trademark_word'))
        row=make_row(task,'serper_web',own,'US','trademark_word',[])
        self.assertEqual([v['scenario_id'] for v in row['scenario_bindings']],['product_entry'])
        from provider_utils import PLAN_META_KEYS
        params={k:v for k,v in row.items() if k not in PLAN_META_KEYS}
        self.assertNotIn('product_dependencies',params)
        self.assertNotIn('product_scope_revision',params)
    def test_plan_and_waiting_work_can_coexist(self):
        task=self.save();plan=generate_plan(self.run)
        self.assertTrue(any(plan['queries'].values()))
        view=work_view_from_dir(self.run)
        self.assertTrue(any(v.get('direction_id')=='locking' and v['state']=='awaiting_user' for v in view['entries']))
        from advance_work import actionable_packet
        self.assertTrue(actionable_packet(view)['waiting'])
    def test_no_plan_all_waiting_and_advance_completion(self):
        self.data['scope']['directions']=self.data['scope']['directions'][:1]
        self.data['scope']['objects']=[o for o in self.data['scope']['objects'] if o['object_id'] in {'reference','photo','box'}]
        self.save()
        from completion_check import check_completion
        result=check_completion(self.run)
        self.assertEqual(result['status'],'awaiting_user')
        self.f.cli('advance_work.py','--task-dir',self.run)
        self.assertFalse((self.run/'search-plan.json').exists())
    def test_supplement_reopens_only_dependency_and_keeps_plan(self):
        task=self.save();plan=generate_plan(self.run);before=(self.run/'search-plan.json').read_bytes()
        outline=ps.direction_digest(task,ps.directions(task)[1])
        self.data['scope']['facts'][0].update(status='confirmed',reason='User supplied locking mechanism.')
        task=self.update()
        self.assertEqual(ps.direction_digest(task,ps.directions(task)[1]),outline)
        self.assertEqual(before,(self.run/'search-plan.json').read_bytes())
        self.assertEqual(ps.direction_state(task,ps.directions(task)[0]),'ready')
        self.assertEqual(len(load_json(self.run/'evidence.json')['collections']['product_scope']),2)
    def test_scope_tampering_rejected_at_plan(self):
        task=self.save();task['product_scope']['facts'][0]['status']='confirmed';atomic_write_json(self.run/'task.json',task)
        with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):generate_plan(self.run)
    def test_source_statement_and_scope_are_retained_idempotently(self):
        task=self.save();before=(self.run/'evidence.json').read_bytes()
        self.save();self.assertEqual(before,(self.run/'evidence.json').read_bytes())
        self.assertEqual(task['product_scope'],load_json(self.run/'task.json')['product_scope'])
        self.assertTrue(load_json(self.run/'evidence.json')['collections']['scope_sources'])
    def test_unknown_revision_rejected(self):
        task=self.save();task['product_scope_revision']='future'
        with self.assertRaisesRegex(ValueError,'REVISION'):ps.enabled(task)

    def add_lock_term(self):
        self.data['query_terms'].append({'kind':'structural_feature','value':'hinged support','language':'en','derived_from':'product.structure[0]'})
    def test_source_self_hash_cannot_replace_retained_statement(self):
        task=self.save();ev=load_json(self.run/'evidence.json')
        source=ev['collections']['scope_sources'][0];source['text']='Do not use OWN';source['sha256']=sha256_json(source['text'])
        atomic_write_json(self.run/'evidence.json',ev)
        with self.assertRaisesRegex(ValueError,'SOURCE_RECEIPT_CHANGED'):generate_plan(self.run)
    def test_term_only_update_and_interrupted_task_write_recovery(self):
        old=self.save();self.data['query_terms'][0]['value']='folding phone stand';new=self.update()
        self.assertNotEqual(old['product_scope']['evidence_id'],new['product_scope']['evidence_id'])
        self.assertEqual(old['product_scope']['scope_sha256'],new['product_scope']['scope_sha256'])
        atomic_write_json(self.run/'task.json',old)
        self.save();self.assertEqual(load_json(self.run/'task.json')['query_terms'],new['query_terms'])
        before=(self.run/'evidence.json').read_bytes();self.save();self.assertEqual(before,(self.run/'evidence.json').read_bytes())
    def test_orphan_pending_object_and_question_asked_persist_in_copy(self):
        import shutil
        obj=self.data['scope']['objects'][0];obj.update(intent='uncertain',statement_refs=['user'],question='Keep reference logo?',checked_information='Two conflicting user statements.')
        task=self.save();work=next(v for v in ps.work_entries(task) if v['object_ids']==['reference'])
        self.f.cli('record_product_scope.py','--task-dir',self.run,'--mark-question-asked',work['work_id'])
        copied=self.f.root/'recovered';self.f.cli('resume_continuous_work.py','--task-dir',self.run,'--output-dir',copied)
        self.run.rename(self.f.root/'original-unavailable')
        view=work_view_from_dir(copied)
        waiting=next(v for v in view['entries'] if v['work_id']==work['work_id'])
        self.assertTrue(waiting['question_asked']);self.assertEqual(waiting['state'],'awaiting_user')
        self.assertEqual(waiting['jurisdiction'],'US')
    def test_mixed_object_states_must_split_direction(self):
        self.data['scope']['directions'][2]['object_ids'].append('photo')
        with self.assertRaisesRegex(ValueError,'MIXED_SCOPE'):self.save()
    def test_fact_confirmation_resumes_same_immutable_query(self):
        self.add_lock_term();task=self.save();plan=generate_plan(self.run)
        rows=[r for values in plan['queries'].values() for r in values if any(d['direction_id']=='locking' for d in r.get('product_dependencies',[]))]
        self.assertTrue(rows);row=rows[0];self.assertEqual(ps.binding_state(task,row),'awaiting_user')
        self.data['scope']['facts'][0]['status']='confirmed';task=self.update()
        after=generate_plan(self.run,expand=True)
        retained=next(r for values in after['queries'].values() for r in values if r['query_id']==row['query_id'])
        self.assertEqual(row,retained);self.assertEqual(ps.binding_state(task,retained),'ready')
    def test_query_fact_conjunction_and_same_right_independence(self):
        self.data['scope']['directions'][1]['right_type']='patent';task=self.save()
        row={'right_type':'patent','derived_from':['product.title','product.structure[0]']}
        ps.bind(task,row,[{'scenario_id':'product_entry'}]);self.assertEqual(ps.binding_state(task,row),'awaiting_user')
        independent={'right_type':'patent','derived_from':['product.title']}
        ps.bind(task,independent,[{'scenario_id':'product_entry'}]);self.assertEqual(ps.binding_state(task,independent),'ready')
    def test_shared_query_keeps_ready_binding_without_clearing_other_gap(self):
        self.data['scope']['directions'].append({'direction_id':'shared-reuse','scenario_id':'brand_reuse','right_type':'design',
          'fact_ids':['shape','lock'],'object_ids':[],'reason':'This scenario also requires the disputed lock.'})
        task=self.save();row={'right_type':'design','derived_from':['product.title']}
        ps.bind(task,row,[{'scenario_id':'product_entry'},{'scenario_id':'brand_reuse'}])
        self.assertEqual(ps.binding_state(task,row),'ready')
        self.assertEqual(ps.binding_state(task,row,'brand_reuse'),'awaiting_user')
        self.assertTrue(ps.coverage_gaps(task,'brand_reuse','design'))
    def test_candidate_scope_is_separate_from_relevance_and_local_to_object(self):
        task=self.save();data=ps.scope(task)
        data['candidate_links']=[{'candidate_id':'C-OWN','object_ids':['own'],'source_refs':['test'],'reason':'Observed mark'},
          {'candidate_id':'C-REF','object_ids':['reference'],'source_refs':['test'],'reason':'Observed reference mark'}]
        self.assertEqual(ps.candidate_scope(task,'product_entry','trademark_word',{'candidate_id':'C-OWN'}),'included')
        self.assertEqual(ps.candidate_scope(task,'brand_reuse','trademark_word',{'candidate_id':'C-REF'}),'default_excluded')
        self.assertEqual(ps.candidate_scope(task,'product_entry','trademark_word',{'candidate_id':'C-UNKNOWN'}),'pending')
        from decision_workflow import product_identity_sha256
        before=product_identity_sha256(task,scenario_id='product_entry',right_type='trademark_word',candidate_id='C-OWN')
        data['facts'][0]['status']='confirmed'
        self.assertEqual(before,product_identity_sha256(task,scenario_id='product_entry',right_type='trademark_word',candidate_id='C-OWN'))
    def test_pending_candidate_generates_agent_work_and_scope_gap(self):
        task=self.save();plan=generate_plan(self.run)
        atomic_write_json(self.run/'normalized-candidates.json',{'patents':[{'candidate_id':'C-UNKNOWN','right_type':'patent','jurisdiction':'US','evidence_refs':[]}]})
        view=work_view_from_dir(self.run)
        self.assertTrue(any(v['reason']=='CANDIDATE_OBJECT_SCOPE_REVIEW_REQUIRED' for v in view['entries']))
    def test_scope_receipt_loss_blocks_real_dispatch_boundary(self):
        self.add_lock_term();task=self.save();plan=generate_plan(self.run)
        provider,row=next((p,r) for p,rows in plan['queries'].items() for r in rows if r.get('product_dependencies'))
        ev=load_json(self.run/'evidence.json');Path(ev['collections']['product_scope'][-1]['path']).unlink()
        from run_browser_plan import _BatchInputs
        with self.assertRaises((ValueError,FileNotFoundError)):_BatchInputs(self.run).disposition(provider,row)
    def test_post_plan_conflict_defers_api_and_browser_without_submission(self):
        from unittest.mock import patch
        from api_first_planning import make_row
        from common import serper_free_enhancement
        base=load_json(self.run/'task.json');base['serper_free_enhancement']=serper_free_enhancement(True,base['retrieval_workflow_revision']);atomic_write_json(self.run/'task.json',base)
        self.data['scope']['facts'][0]['status']='confirmed';self.add_lock_term();task=self.save();plan=generate_plan(self.run)
        term=next(t for t in term_records(task) if t['kind']=='structural_feature')
        api=make_row(task,'serper_patents',term,'US','patent',[])
        if not any(r['query_id']==api['query_id'] for rows in plan['queries'].values() for r in rows): plan['queries'].setdefault('serper_patents',[]).append(api)
        atomic_write_json(self.run/'search-plan.json',plan)
        self.data['scope']['facts'][0]['status']='conflict';task=self.update()
        from run_browser_plan import _BatchInputs
        from runtime_v24 import execute_api_plan
        before=(self.run/'evidence.json').read_bytes()
        with patch('subprocess.run',side_effect=AssertionError('Provider must not run')):
            result=execute_api_plan(self.run,query_ids_filter=[api['query_id']],include_optional=True,phase='discovery')
        self.assertEqual(result['results'][0]['dispatch'],'deferred')
        self.assertEqual(result['results'][0]['submission_state'],'not_submitted')
        self.assertEqual(before,(self.run/'evidence.json').read_bytes())
    def test_browser_post_plan_conflict_never_calls_runner(self):
        from unittest.mock import Mock
        from run_browser_plan import execute_plan
        self.data['scope']['facts'][0]['status']='confirmed';self.add_lock_term();task=self.save();plan=generate_plan(self.run)
        provider,row=next((p,r) for p,rows in plan['queries'].items() for r in rows if 'browser' in p and any(d['direction_id']=='locking' for d in r.get('product_dependencies',[])))
        self.data['scope']['facts'][0]['status']='conflict';self.update()
        runner=Mock(side_effect=AssertionError('Browser must not run'))
        before=(self.run/'evidence.json').read_bytes()
        result=execute_plan(self.run,query_id_filter=row['query_id'],runner=runner,phase='fallback')
        runner.assert_not_called()
        self.assertEqual(result['queries'][0]['dispatch'],'deferred')
        self.assertEqual(before,(self.run/'evidence.json').read_bytes())
    def test_replaying_old_term_request_cannot_rewind_history(self):
        self.save();self.data['query_terms'][0]['value']='folding phone stand';self.update();old=deepcopy(self.data)
        self.data['query_terms'][0]['value']='folding tablet stand';self.update();before=(self.run/'task.json').read_bytes()
        self.data=old
        with self.assertRaisesRegex(ValueError,'STALE_REQUEST'):self.save()
        self.assertEqual(before,(self.run/'task.json').read_bytes())
    def test_candidate_link_injection_breaks_scope_receipt(self):
        task=self.save();task['product_scope']['candidate_links']=[{'candidate_id':'C-INJECT','object_ids':['reference'],
          'source_refs':[task['product_identity']['evidence_id']],'reason':'Unrecorded injected association'}]
        atomic_write_json(self.run/'task.json',task)
        with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):generate_plan(self.run)
    def test_explicit_reference_brand_reaches_browser_execution(self):
        from unittest.mock import Mock
        from run_browser_plan import execute_plan
        self.data['scope']['objects'][0].update(intent='use',statement_refs=['user'])
        self.data['scope']['directions'].append({'direction_id':'reference-mark','scenario_id':'brand_reuse','right_type':'trademark_word',
          'fact_ids':[],'object_ids':['reference'],'reason':'Explicit reference reuse.'})
        task=self.save()
        # Exercise a declared zero-cost browser fallback after API routes are
        # unavailable; no browser is started by this planning fixture.
        atomic_write_json(self.run/'source-capabilities.json',{'task_id':task['task_id'],'sources':[
            {'provider':'uspto_tmsearch_browser','executable':True,'state':'available'}]})
        plan=generate_plan(self.run)
        provider,row=next((p,r) for p,rows in plan['queries'].items() for r in rows if 'browser' in p and r['right_type']=='trademark_word' and any(d['direction_id']=='reference-mark' for d in r.get('product_dependencies',[])))
        self.assertEqual([b['scenario_id'] for b in row['scenario_bindings']],['brand_reuse'])
        # Fake transport acknowledges a submission failure: proves reachability,
        # never a successful business search or production authorization.
        runner=Mock(side_effect=[{'executor_available':True},{'status':'failed','error_code':'OFFLINE_TRANSPORT_PROBE','submission_state':'submitted'}])
        result=execute_plan(self.run,query_id_filter=row['query_id'],runner=runner,phase='fallback')
        self.assertEqual(runner.call_count,2);self.assertIn('run-planned-query',runner.call_args.args[0])
        self.assertEqual(result['queries'][0]['submission_state'],'submitted')
    def test_genuine_resale_requires_request_and_allows_mark_object(self):
        self.data['scope']['directions'].append({'direction_id':'resale-mark','scenario_id':'genuine_resale','right_type':'trademark_word',
          'fact_ids':[],'object_ids':['reference'],'reason':'Explicit resale scenario.'})
        with self.assertRaisesRegex(ValueError,'EXPLICIT_REQUEST'):self.save()
        task=load_json(self.run/'task.json');task['request']['genuine_resale']=True
        from decision_workflow import default_assessment_scenarios
        task['assessment_scenarios']=default_assessment_scenarios(genuine_resale=True)
        atomic_write_json(self.run/'task.json',task);task=self.save()
        self.assertIn('genuine_resale',task['execution_scenario_ids'])
    def test_candidate_ready_object_survives_other_pending_object(self):
        task=self.save();data=ps.scope(task)
        pending=deepcopy(data['objects'][1]);pending.update(object_id='pending-pattern',scope_status='pending',intent='uncertain')
        data['objects'].append(pending)
        data['directions'].append({'direction_id':'pending-pattern','scenario_id':'product_entry','right_type':'copyright','object_ids':['pending-pattern'],'fact_ids':[]})
        data['candidate_links']=[{'candidate_id':'C-MULTI','object_ids':['pattern','pending-pattern']}]
        self.assertEqual(ps.candidate_scope(task,'product_entry','copyright',{'candidate_id':'C-MULTI'}),'included')
        self.assertTrue(ps.coverage_gaps(task,'product_entry','copyright'))
    def test_valid_cancelled_query_does_not_reopen_scope_work(self):
        self.data['scope']['facts'][0]['source_path']='evidence:locking-mechanism'
        self.data['query_terms'].append({'kind':'structural_feature','value':'hinged support',
                                       'language':'en','derived_from':'evidence:locking-mechanism'})
        task=self.save();plan=generate_plan(self.run)
        row=next(r for rows in plan['queries'].values() for r in rows
                 if any(d['direction_id']=='locking' for d in r.get('product_dependencies',[])))
        self.data['scope']['facts'][0].update(value='different mechanism',status='confirmed')
        task=self.update()
        self.assertEqual(ps.binding_state(task,row),'awaiting_review')
        plan.setdefault('execution_dispositions',[]).append({'query_id':row['query_id'],
            'plan_entry_sha256':sha256_json(row),'status':'cancelled','reason':'Obsolete action'})
        view=ps.project_work(task,{'entries':[]},plan)
        self.assertFalse(any(e.get('query_id')==row['query_id'] for e in view['entries']))
        plan['execution_dispositions'][-1]['plan_entry_sha256']='0'*64
        view=ps.project_work(task,{'entries':[]},plan)
        self.assertTrue(any(e.get('query_id')==row['query_id'] for e in view['entries']))

    def test_changed_fact_requires_explicit_query_revalidation_without_rewriting_plan(self):
        self.data['scope']['facts'][0]['source_path']='evidence:locking-mechanism'
        self.data['query_terms'].append({'kind':'structural_feature','value':'hinged support','language':'en','derived_from':'evidence:locking-mechanism'})
        task=self.save();plan=generate_plan(self.run)
        row=next(r for rows in plan['queries'].values() for r in rows if any(d['direction_id']=='locking' for d in r.get('product_dependencies',[])))
        before=(self.run/'search-plan.json').read_bytes()
        self.data['sources'].append({'source_id':'answer','kind':'user_statement','text':'The locking mechanism is a spring loaded hinge.'})
        self.data['scope']['facts'][0].update(value='spring loaded hinge',status='confirmed',source_refs=['answer'])
        task=self.update();self.assertEqual(ps.binding_state(task,row),'awaiting_review')
        self.data['scope']['query_revalidations']=[{'review_id':'lock-review-1','query_id':row['query_id'],'plan_entry_sha256':sha256_json(row),
          'source_refs':['answer'],'reason':'Hinged support remains a supported broad recall term after this clarification.'}]
        task=self.update();self.assertEqual(ps.binding_state(task,row),'ready')
        self.assertEqual(before,(self.run/'search-plan.json').read_bytes())
        self.assertFalse(load_json(self.run/'evidence.json')['collections'].get('serper_patents'))
        self.data['scope']['facts'][0]['value']='magnetic clamp without hinge'
        task=self.update();self.assertEqual(ps.binding_state(task,row),'awaiting_review')
        self.data['scope']['facts'][0]['status']='conflict'
        self.data['scope']['query_revalidations'][0]['review_id']='lock-review-2'
        self.data['expected_scope_sha256']=task['product_scope']['scope_sha256']
        with self.assertRaisesRegex(ValueError,'DEPENDENCY_NOT_READY'):self.save()
    def test_scope_report_html_markdown_disclose_all_four_states(self):
        from unittest.mock import patch
        import report_estimate
        self.data['scope']['objects'][0].update(intent='uncertain',statement_refs=['user'],question='Keep reference?',checked_information='Conflicting explicit statements.')
        self.data['scope']['objects'][2].update(intent='do_not_use',statement_refs=['user'])
        task=self.save();ev=load_json(self.run/'evidence.json')
        original=report_estimate.build_report_data
        captured=[]
        def build(*args,**kwargs):
            data=original(self.run,task,ev,*args[3:],**kwargs);captured.append(data);return data
        # Reuse only the rendering-only assessment fixture; real scope comes
        # from the normal retained recorder above, not direct injected fields.
        with patch.object(report_estimate,'build_report_data',side_effect=build), patch.object(self.f,'ready',return_value=task):
            self.f.test_render_user_material_source_without_empty_amazon_link()
        data=captured[0]
        for text in (report_estimate.render_html(data,self.run),report_estimate.render_markdown(data)):
            for label in ps.LABELS.values():self.assertIn(label,text)
            self.assertIn(ps.DEFAULT_ASSUMPTION,text);self.assertIn('Keep reference?',text)
            self.assertIn('角色及来源',text);self.assertIn('局部限制',text)
            self.assertIn('系统默认',text)
    def test_partial_readiness_still_requires_identity_confirmation(self):
        from product_entry import load_materials
        payload=load_json(self.f.input)
        payload['readiness'].update(revision='directional-readiness-v1',status='partial')
        atomic_write_json(self.f.input,payload);load_materials(self.f.input)
        payload['identity_review']['status']='pending';atomic_write_json(self.f.input,payload)
        with self.assertRaisesRegex(ValueError,'IDENTITY_REVIEW_REQUIRED'):load_materials(self.f.input)
    def test_query_revalidation_cannot_change_scenario_right_or_dependency_identity(self):
        task=self.save();plan=generate_plan(self.run)
        row=next(r for rows in plan['queries'].values() for r in rows if any(d['direction_id']=='outline' for d in r.get('product_dependencies',[])))
        self.data['scope']['directions'][1]['scenario_id']='brand_reuse'
        self.data['scope']['query_revalidations']=[{'review_id':'wrong-scenario','query_id':row['query_id'],
          'plan_entry_sha256':sha256_json(row),'source_refs':['user'],'reason':'Must not reassign historical coverage to a different scenario.'}]
        self.data['expected_scope_sha256']=task['product_scope']['scope_sha256']
        with self.assertRaisesRegex(ValueError,'IDENTITY_CHANGED'):self.save()
    def test_unmodelled_captured_clue_remains_agent_work(self):
        task=self.save();task['product']['structure'].append('visible screw joint')
        self.assertTrue(any(g['code']=='PRODUCT_CLUE_UNACCOUNTED' for g in ps.readiness(task)['gaps']))
        self.assertTrue(any(w['reason']=='PRODUCT_CLUE_UNACCOUNTED' for w in ps.work_entries(task)))
        self.assertTrue(ps.readiness(task)['ready'])
    def test_patent_claim_obligation_preserved(self):
        task=self.save();task['product']['visible_ip_claims']=['patent pending']
        self.assertTrue(ps.readiness(task)['patent_claim_followup']['required'])


class EmptyDirectionCoverageTests(unittest.TestCase):
    def task(self,objects):
        return {'retrieval_workflow_revision':'api-first-v3','product_scope':{
            'status':'reviewed','objects':objects,'facts':[],'directions':[]}}

    def obj(self,state='default_excluded',relation='reference'):
        return {'object_id':'mark','kind':'brand','relation':relation,
            'scope_status':state,'right_types':['trademark_word']}

    def test_no_applicable_or_all_excluded_objects_have_no_product_dependency(self):
        task=self.task([self.obj()]);before=deepcopy(task)
        self.assertEqual(ps.coverage_gaps(task,'product_entry','trademark_word'),[])
        self.assertEqual(ps.coverage_gaps(task,'brand_reuse','trademark_word'),[])
        self.assertEqual(ps.coverage_gaps(task,'product_entry','utility_model'),[])
        self.assertEqual(task,before)
        for state in ('user_excluded','default_excluded'):
            self.assertEqual(ps.coverage_gaps(self.task([self.obj(state,'own')]),
                'product_entry','trademark_word'),[])

    def test_included_and_pending_missing_directions_remain_blocking(self):
        for state in ('included','pending'):
            with self.subTest(state=state):
                task=self.task([self.obj(state,'own')])
                self.assertEqual(ps.coverage_gaps(task,'product_entry','trademark_word'),
                    ['PRODUCT_DIRECTION_UNREVIEWED'])
                # Reference objects also apply to explicitly requested resale.
                task=self.task([self.obj(state)])
                self.assertEqual(ps.coverage_gaps(task,'genuine_resale','trademark_word'),
                    ['PRODUCT_DIRECTION_UNREVIEWED'])

    def test_old_versions_keep_original_empty_direction_semantics(self):
        for version in (None,'api-first-v2'):
            task=self.task([]);task['retrieval_workflow_revision']=version
            self.assertEqual(ps.coverage_gaps(task,'product_entry','utility_model'),
                ['PRODUCT_DIRECTION_UNREVIEWED'])

if __name__=='__main__':unittest.main()
