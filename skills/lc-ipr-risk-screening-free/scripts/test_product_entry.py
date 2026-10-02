"""01A observable CLI/recording contracts; synthetic files, mocked auth, no network."""
from __future__ import annotations
import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json
from offline_test_support import isolated_test_environment, offline_environment
from product_entry import assert_frozen, evidence_errors, load_materials
from record_user_product import record
from runtime_v24 import preflight_credentials, preflight_evidence
from workflow_v24 import generate_plan

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII=')
SCRIPTS = Path(__file__).parent


class ProductEntryTests(unittest.TestCase):
    def setUp(self):
        self.env = isolated_test_environment(); self.env.__enter__(); self.addCleanup(self.env.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.run = self.root/'run'
        (self.root/'product.png').write_bytes(PNG)
        self.input = self.root/'input.json'
        self.data = {'schema_version':'product-input-v1',
            'product':{'title':'Folding stand', 'purpose':'Supports a phone', 'structure':['hinged support']},
            'sources':[{'source_id':'image-1','kind':'image','path':'product.png'},
                       {'source_id':'statement-1','kind':'description','text':'One folding phone stand; no variant options.'}],
            'identity_review':{'status':'confirmed','single_product':True,'reviewer':'offline-agent',
                               'reasoning':'One supplied stand and its stated use match.', 'conflicts':[], 'source_ids':['image-1','statement-1']},
            'readiness':{'status':'ready','reasoning':'Visible outline and stated hinge suffice for this initial analysis.',
                         'nonblocking_gaps':['Unspecified colour; not material to initial directions.']}}
        self.write_input()

    def write_input(self): atomic_write_json(self.input, self.data)

    def cli(self, name, *args, ok=True):
        out = subprocess.run([sys.executable, str(SCRIPTS/name), *map(str,args)], capture_output=True, text=True, env=offline_environment())
        if ok: self.assertEqual(out.returncode,0,out.stdout+out.stderr)
        else: self.assertNotEqual(out.returncode,0)
        return out

    def create(self, amazon=False, country='US'):
        args = ['--url','https://www.amazon.com/dp/B000000001'] if amazon else ['--product-input',self.input]
        if country is not None: args += ['--jurisdictions',country]
        self.cli('create_task.py',*args,'--output-dir',self.run)
        task=load_json(self.run/'task.json')
        task.pop('product_scope_required',None)  # Historical 01A fixture.
        task.pop('discovery_semantics_revision',None)  # Historical fixture; 03B has its own opt-in tests.
        atomic_write_json(self.run/'task.json',task)
        return task

    def preflight(self):
        with patch('auth_gate.require_auth') as auth:
            self.assertEqual(preflight_credentials(self.run),'awaiting_browser')
            auth.assert_called_once()

    def ready(self):
        self.create(); self.preflight(); record(self.run)
        self.assertEqual(preflight_evidence(self.run),'collecting')
        return load_json(self.run/'task.json')

    def test_default_new_entry_country_and_no_fabricated_amazon_fields(self):
        task=self.create(country='DE')
        self.assertEqual(task['product_entry_revision'],'dual-entry-v1')
        self.assertEqual(task['target_jurisdictions'],['EU','DE'])
        self.assertEqual(task['request']['jurisdiction_source'],'user')
        self.assertEqual(task['product_identity']['status'],'pending')
        for key in ('requested_asin','actual_asin'): self.assertFalse(task['product'][key])
        self.assertFalse(task['request']['marketplace'])
        self.assertEqual(task['product']['input_role_source'],'default')

    def test_missing_country_does_not_create_task_and_not_inferred_from_text(self):
        result=self.cli('create_task.py','--product-input',self.input,'--output-dir',self.run,ok=False)
        self.assertIn('TARGET_COUNTRY_REQUIRED',result.stderr)
        self.assertFalse(self.run.exists())

    def test_conflicting_multiple_product_or_unready_input_leaves_no_task(self):
        variants=[{'single_product':False}, {'conflicts':['Two different models']}, {'status':'unknown'}]
        for changes in variants:
            with self.subTest(changes=changes):
                original=deepcopy(self.data); self.data['identity_review'].update(changes); self.write_input()
                self.cli('create_task.py','--product-input',self.input,'--jurisdictions','US','--output-dir',self.run,ok=False)
                self.assertFalse(self.run.exists()); self.data=original
        self.data['readiness']['status']='needs_info'; self.write_input()
        self.cli('create_task.py','--product-input',self.input,'--jurisdictions','US','--output-dir',self.run,ok=False)
        self.assertFalse(self.run.exists())

    def test_no_fixed_specification_or_variant_checklist_and_idempotent_retention(self):
        task=self.ready(); assert_frozen(task)
        self.assertEqual(task['product']['variant'],{})
        self.assertEqual(task['product']['specifications'],{})
        ev=load_json(self.run/'evidence.json')
        self.assertEqual(ev['source_runs'][0]['provider'],'user_materials')
        self.assertTrue(Path(task['images'][0]['path']).is_relative_to(self.run.resolve()))
        before={name:(self.run/name).read_bytes() for name in ('task.json','evidence.json')}
        self.input.unlink(); (self.root/'product.png').unlink()
        self.assertEqual(record(self.run),'success')
        self.assertEqual(before,{name:(self.run/name).read_bytes() for name in before})

    def test_credentials_failure_does_not_retain_materials(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'PREFLIGHT'): record(self.run)
        with patch('auth_gate.require_auth',side_effect=SystemExit('private-token-body')):
            with self.assertRaises(SystemExit) as failure: preflight_credentials(self.run)
        self.assertNotIn('private-token-body',str(failure.exception))
        self.assertEqual(load_json(self.run/'evidence.json')['collections']['product'],[])

    def test_source_change_before_or_after_retention_rejected(self):
        self.create(); self.preflight()
        (self.root/'product.png').write_bytes(PNG+b'changed')
        with self.assertRaisesRegex(ValueError,'CHANGED_BEFORE'): record(self.run)
        self.assertEqual(load_json(self.run/'task.json')['product_identity']['status'],'pending')
        (self.root/'product.png').write_bytes(PNG); record(self.run)
        task=load_json(self.run/'task.json'); image=Path(task['images'][0]['path']); image.write_bytes(b'bad')
        self.assertEqual(preflight_evidence(self.run),'incomplete')
        with self.assertRaisesRegex(ValueError,'CHANGED|MEDIA_BINDING_MISMATCH'): record(self.run)

    def test_identity_tampering_and_missing_receipt_fail(self):
        task=self.ready(); task['product']['product_id']='different'
        with self.assertRaisesRegex(ValueError,'FROZEN_OR_CHANGED'): assert_frozen(task)
        task=load_json(self.run/'task.json'); ev=load_json(self.run/'evidence.json'); ev['source_runs']=[]
        self.assertIn('PRODUCT_SOURCE_RECEIPT_MISSING',evidence_errors(task,ev,self.run))

    def test_user_materials_reach_analysis_plan_and_next_work(self):
        self.ready()
        payload={'product':{'structure':['hinged support']},
                 'query_terms':[{'kind':'structural_feature','value':'hinged support','language':'en','derived_from':'product.structure[0]'}],
                 'analysis':{'reviewer':'offline-agent','reasoning':'Hinge and supporting plate documented.'}}
        payload['analysis']['clue_dispositions']=[{'source_path':'product.structure[0]','source_sha256':sha256_json('hinged support'),'disposition':'mapped','query_term_sha256':[sha256_json(payload['query_terms'][0])],'reason':'Visible hinge maps to the structural query.'}]
        analysis=self.root/'analysis.json'; atomic_write_json(analysis,payload)
        self.cli('record_product_analysis.py','--task-dir',self.run,'--input',analysis)
        plan=generate_plan(self.run)
        self.assertTrue(any(plan['queries'].values()))
        self.cli('next_work.py','--task-dir',self.run)
        from assessment_estimate import validate_inputs
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        self.cli('merge_candidates.py','--task-dir',self.run)
        candidates=load_json(self.run/'normalized-candidates.json')
        validate_inputs(task,evidence,candidates,plan,load_json(self.run/'materiality-annotations.json'),task_dir=self.run)
        before=deepcopy(plan['queries']); self.assertEqual(generate_plan(self.run)['queries'],before)

    def test_media_replacement_after_preflight_blocks_plan_and_assessment(self):
        self.test_user_materials_reach_analysis_plan_and_next_work()
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        replacement=self.run/'images'/'other.png'; replacement.write_bytes(PNG+b'other')
        task['images'][0].update(path=str(replacement),sha256=sha256_file(replacement),bytes=replacement.stat().st_size)
        atomic_write_json(self.run/'task.json',task)
        with self.assertRaisesRegex(ValueError,'MEDIA_BINDING_MISMATCH'): generate_plan(self.run)
        from assessment_estimate import validate_inputs
        with self.assertRaisesRegex(ValueError,'MEDIA_BINDING_MISMATCH'):
            validate_inputs(task,evidence,load_json(self.run/'normalized-candidates.json'),
                load_json(self.run/'search-plan.json'),load_json(self.run/'materiality-annotations.json'),task_dir=self.run)

    def test_interrupted_evidence_task_write_resumes_without_duplicate_or_original_inputs(self):
        import record_user_product as recorder
        self.create(); self.preflight()
        original=recorder.atomic_write_json
        def interrupted(path, payload):
            if path.name == 'task.json': raise OSError('simulated interrupted task write')
            return original(path,payload)
        with patch.object(recorder,'atomic_write_json',side_effect=interrupted):
            with self.assertRaises(OSError): record(self.run)
        ev_before=(self.run/'evidence.json').read_bytes()
        raw=Path(load_json(self.run/'evidence.json')['source_runs'][0]['raw_paths'][0])
        raw_before=raw.read_bytes()
        self.input.unlink(); (self.root/'product.png').unlink()
        record(self.run)
        self.assertEqual(ev_before,(self.run/'evidence.json').read_bytes())
        self.assertEqual(raw_before,raw.read_bytes())
        self.assertEqual(preflight_evidence(self.run),'collecting')

    def test_replacing_current_image_without_source_binding_is_rejected(self):
        task=self.ready(); replacement=self.run/'images'/'other.png'; replacement.write_bytes(PNG+b'other')
        task['images'][0].update(path=str(replacement),sha256=sha256_file(replacement),bytes=replacement.stat().st_size)
        atomic_write_json(self.run/'task.json',task)
        self.assertEqual(preflight_evidence(self.run),'incomplete')
        self.assertIn('PRODUCT_CURRENT_MEDIA_BINDING_MISMATCH',[v['detail'] for v in load_json(self.run/'task.json')['errors']])

    def test_recovery_uses_retained_copy_after_original_directory_is_removed(self):
        self.ready()
        recovery=self.root/'recovery'
        self.cli('resume_continuous_work.py','--task-dir',self.run,'--output-dir',recovery)
        self.run.rename(self.root/'unavailable-original')
        self.input.unlink(); (self.root/'product.png').unlink()
        self.assertEqual(record(recovery),'success')
        self.assertEqual(preflight_evidence(recovery),'collecting')
        task=load_json(recovery/'task.json'); evidence=load_json(recovery/'evidence.json')
        self.assertEqual(evidence_errors(task,evidence,recovery),[])

    def test_render_user_material_source_without_empty_amazon_link(self):
        from report_estimate import build_report_data, render_html
        task=self.ready(); evidence=load_json(self.run/'evidence.json')
        # This rendering-only fixture predates the 09 work view and exercises
        # the historical product-entry report contract.
        task.pop('report_presentation_revision', None)
        task.pop('presentation_policy_revision', None)
        assessment={'assessment_policy':'evidence-estimate-v1','task_id':task['task_id'],
            'generated_at':now_iso(),'status':'incomplete','assessments':[],
            'overall':{'scenario_id':'product_entry','scenario_sha256':'synthetic-display','business_completion':'incomplete','assessment_status':'pending','risk':None,'confidence':'低','reasons':['离线合成展示样例，未开展权利检索。']},
            'publication':{'mode':'stage','delivery_status':'incomplete','stop_reason':'离线合成展示样例'},
            'coverage':{'scopes':[]},'scenario_summaries':[{'primary':True,'conditional':False,'scenario_id':'product_entry','scenario_sha256':'synthetic-display','assessment_status':'pending','title':'合成展示',
                'completion':{'status':'incomplete','queues':{},'triage_counts':{'selected':0,'not_selected':0,'needs_info':0,'unreviewed':0},
                              'retrieval':'incomplete','triage':'incomplete','verification':'incomplete','assessment':'incomplete'},
                'risk':None,'confidence':'低','assumptions':[]}]}
        # Rendering-only check: no fabricated review is used as business validation.
        data=build_report_data(self.run,task,evidence,assessment,{}, {'entries':[]},{},
                               verify_assessment=False)
        html=render_html(data,self.run)
        self.assertIn('用户提供的产品资料',html)
        self.assertIn(task['product']['product_id'],html)
        self.assertNotIn('<span>ASIN</span>',html)
        self.assertNotIn('href=""',html)
        self.assertIn('data:image/',html)

    def capture(self, asin='B000000002', value='Black'):
        task=load_json(self.run/'task.json'); image=self.run/'images'/'main.png'; image.write_bytes(PNG)
        shots={}
        for role in ('product_core','product_details'):
            p=self.run/'screenshots'/(role+'.png');p.write_bytes(PNG);shots[role]=str(p)
        capture={'browser':'chrome_desktop','capture_transport':'cdp','browser_version':'offline-fixture','protocol_version':'1.3',
          'cdp_session_id':'offline-test-session','status':'success','requested_url':task['request']['url'],
          'final_url':task['request']['url'],'actual_asin':asin,'variant':{'label':'Selected option','value':value,'confirmed':True},
          'title':'Folding stand','category':'Accessories','collected_at':now_iso(),'screenshots':shots,
          'main_image':{'path':str(image),'source_url':'https://m.media-amazon.com/images/I/fixture.png',
          'sha256':sha256_file(image),'width':1,'height':1,'format':'PNG'}}
        p=self.root/'capture.json';atomic_write_json(p,capture);return p

    def test_first_actual_child_freezes_and_resume_cannot_switch(self):
        self.create(amazon=True,country=None);self.preflight()
        p=self.capture();self.cli('record_browser_product.py','--task-dir',self.run,'--capture',p)
        task=load_json(self.run/'task.json');assert_frozen(task)
        self.assertEqual(task['product']['actual_asin'],'B000000002')
        self.assertEqual(task['request']['jurisdiction_source'],'marketplace')
        self.assertEqual(preflight_evidence(self.run),'collecting')
        before=deepcopy(task['product_identity']); product=deepcopy(task['product'])
        p=self.capture('B000000003','White');self.cli('record_browser_product.py','--task-dir',self.run,'--capture',p)
        after=load_json(self.run/'task.json')
        self.assertEqual(after['product_identity'],before);self.assertEqual(after['product'],product)
        self.assertEqual(after['errors'][-1]['code'],'PRODUCT_TARGET_MISMATCH')

    def test_no_marker_keeps_legacy_asin_equality(self):
        self.create(amazon=True); self.preflight()
        task=load_json(self.run/'task.json');task.pop('product_entry_revision');atomic_write_json(self.run/'task.json',task)
        p=self.capture();self.cli('record_browser_product.py','--task-dir',self.run,'--capture',p)
        self.assertEqual(load_json(self.run/'task.json')['errors'][-1]['code'],'AMAZON_ASIN_MISMATCH')


if __name__=='__main__': unittest.main()
