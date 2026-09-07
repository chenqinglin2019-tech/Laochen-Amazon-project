#!/usr/bin/env python3
"""V3 regressions using known synthetic fixtures, never a live image model."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import lc_image_pipeline as p
import lc_quality as q
from lc_assets import xmp_keywords, SYNTHETIC_KEYWORD
from pipeline_test_support import (create_v3_fixture, prepare_fixture, ready_fixture, simulate_secondary_output,
                                   bind_source_reviews, bind_ai_disclosure, bind_output_reviews, finish_fixture, P0_ID, P2_ID)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.m = create_v3_fixture(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def ready(self):
        self.m = ready_fixture(self.base)
        return self.m['jobs']

    def test_legacy_global_pixel_mode_is_not_required(self):
        for key in ('source_quality','master_asset_mode','master_confirmed'):
            self.m['product_truth'].pop(key,None)
        self.assertEqual(p.validate_manifest(self.m,self.base),[])
        prepare_fixture(self.m,self.base)
        self.assertEqual(self.m['jobs'][1]['render_mode'],'reference_generate')

    def test_prepare_local_decision_and_detail_crop(self):
        prepare_fixture(self.m, self.base)
        a,b=self.m['jobs']
        self.assertEqual(a['render_mode'],'pixel_composite')
        self.assertEqual(b['render_mode'],'reference_generate')
        self.assertTrue(b['new_view'])
        self.assertTrue((self.base/self.m['critical_details'][0]['reference_crops'][0]['path']).is_file())
        self.assertIn('Natural perspective', (self.base/b['prompt_file']).read_text())
        self.assertIn('preserve', (self.base/a['prompt_file']).read_text().lower())

    def test_full_delivery_and_repeat_cache_without_model(self):
        a,b=self.ready()
        before=[j.get('metrics',{}).get('model_dispatches',0) for j in self.m['jobs']]
        hashes=[j['final_sha256'] for j in self.m['jobs']]
        p.prepare(self.m,self.base)
        p.aspect_safe_postprocess(self.m,self.base)
        p.quality_assurance(self.m,self.base)
        self.assertTrue(p.delivery_check(self.m,self.base)['ready'])
        self.assertEqual(before,[0,1])
        self.assertEqual(before,[j.get('metrics',{}).get('model_dispatches',0) for j in self.m['jobs']])
        self.assertEqual(hashes,[j['final_sha256'] for j in self.m['jobs']])
        self.assertGreater(a['metrics']['cache_hits']['qa'],0)
        self.assertGreater(b['metrics']['cache_hits']['export'],0)

    def test_missing_reviews_dont_spend_repair_budget(self):
        a,b=self.ready()
        a['detail_qa_results'].pop(P0_ID)
        report=p.quality_assurance(self.m,self.base)
        self.assertEqual(a['status'],'review_pending')
        self.assertEqual(a['quality_repairs'],0)
        self.assertIn('detail:'+P0_ID,report['jobs'][0]['missing_reviews'])

    def test_p2_cannot_overwrite_p0_or_semantic_failure(self):
        for primary in ('detail','semantic'):
            with self.subTest(primary=primary):
                a,b=self.ready()
                a['detail_qa_results'][P2_ID]={'verdict':'fail'}
                if primary=='detail':a['detail_qa_results'][P0_ID]={'verdict':'fail'}
                else:a['semantic_qa_results']['clarity']={'verdict':'fail'}
                report=p.quality_assurance(self.m,self.base)
                self.assertEqual(a['status'],'generation_repair_needed')
                self.assertTrue(report['jobs'][0]['image_failures'])
                repair=self.base/report['jobs'][0]['semantic_repair_prompt']
                text=repair.read_text()
                self.assertIn(a['raw_output'],text)
                self.assertNotIn(a['final_output'],text)

    def test_unverifiable_local_detail_blocks_only_related_job(self):
        detail=self.m['critical_details'][0]
        detail['visibility']['02_secondary']='hidden'
        detail['locations'][0]['visual_confirmation']='unverifiable'
        bind_source_reviews(self.m,self.base)
        p.prepare(self.m,self.base)
        self.assertEqual(self.m['jobs'][0]['status'],'blocked')
        self.assertEqual(self.m['jobs'][1]['status'],'pending')
        self.assertEqual(self.m['generation_gate']['status'],'open')
        self.assertFalse(detail['reference_crops'][0]['verifiable'])

    def test_unreadable_crop_does_not_shadow_confirmed_closeup(self):
        detail=self.m['critical_details'][0]
        ref=copy.deepcopy(self.m['references'][0]);ref.update(id='detail_closeup',role='critical_detail_reference')
        self.m['references'].append(ref)
        location=copy.deepcopy(detail['locations'][0]);location['reference_id']='detail_closeup'
        detail['locations'][0]['visual_confirmation']='unverifiable'
        detail['locations'].append(location)
        bind_source_reviews(self.m,self.base)
        p.prepare(self.m,self.base)
        _,crop=p.evidence_for_job(detail,self.m['jobs'][0])
        self.assertEqual(crop['reference_id'],'detail_closeup')

    def test_new_view_requires_new_detail_coordinates(self):
        a,b=self.ready()
        b['detail_output_bbox_norms']={}
        p.quality_assurance(self.m,self.base)
        self.assertEqual(b['status'],'review_pending')
        self.assertEqual(b['quality_repairs'],0)

    def test_coordinates_change_invalidates_previous_detail_verdict(self):
        a,b=self.ready()
        a['detail_output_bbox_norms']={P0_ID:[.1,.1,.1,.1]}
        p.quality_assurance(self.m,self.base)
        self.assertEqual(a['status'],'review_pending')
        self.assertNotIn(P0_ID,a['detail_qa_results'])

    def test_actual_final_tamper_is_not_admitted(self):
        a,b=self.ready()
        path=self.base/a['final_output']
        with Image.open(path) as src:image=src.convert('RGB')
        image.putpixel((0,0),(1,2,3));image.save(path)
        p.quality_assurance(self.m,self.base)
        self.assertEqual(a['status'],'failed')

    def test_provenance_change_invalidates_qa_and_delivery(self):
        self.ready()
        self.m['references'][0]['provenance']={'kind':'generated','qa_verdict':'unknown','source_reference_ids':[]}
        with self.assertRaises(p.PipelineError):p.delivery_check(self.m,self.base)
        p.quality_assurance(self.m,self.base)
        self.assertEqual(self.m['jobs'][0]['status'],'blocked')
        self.assertEqual(self.m['jobs'][1]['status'],'blocked')

    def test_raw_change_requires_generation_transition(self):
        a,b=self.ready()
        Image.new('RGB',(1600,1600),'red').save(self.base/b['raw_output'])
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertEqual(b['status'],'failed')
        self.assertEqual(b['failed_reason'],'RAW_CHANGED_WITHOUT_GENERATION_TRANSITION')

    def test_delivery_rejects_source_copy_review_fact_and_artifact_changes(self):
        for changed in ('source','copy','review','fact','contact','qa_report','font'):
            with self.subTest(changed=changed):
                a,b=self.ready()
                if changed=='source':
                    path=self.base/self.m['references'][0]['path']
                    with Image.open(path) as im:im=im.convert('RGB')
                    im.putpixel((0,0),(1,2,3));im.save(path)
                elif changed=='copy':b['layout']={'template':'scene','headline':'Changed copy'}
                elif changed=='review':a['semantic_qa_results']['clarity']={'verdict':'fail'}
                elif changed=='fact':self.m['facts'][0]['text']='changed evidence claim'
                elif changed=='contact':Image.new('RGB',(20,20),'red').save(self.base/'final/contact_sheet.png')
                elif changed=='qa_report':p.write_json(self.base/'qa_report.json',{'jobs':[]})
                else:
                    b['layout']={'template':'scene','font_sizes':{'headline':150}}
                with self.assertRaises(p.PipelineError):p.delivery_check(self.m,self.base)

    def test_metadata_only_edit_preserves_layout_and_calls(self):
        a,b=self.ready()
        raw=b['bound_raw_sha256'];layout=b['layout_output_sha256'];calls=b['metrics']['model_dispatches']
        b['ai_disclosure']['human_source']='synthetic'
        b['ai_disclosure']['notes']='Test-only synthetic person classification'
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertEqual(b['bound_raw_sha256'],raw)
        self.assertEqual(b['layout_output_sha256'],layout)
        self.assertEqual(b['metrics']['model_dispatches'],calls)
        with Image.open(self.base/b['final_output']) as im:self.assertIn(SYNTHETIC_KEYWORD,xmp_keywords(im))
        p.quality_assurance(self.m,self.base)
        p.create_final_contact_sheet(self.m,self.base)
        self.assertTrue(p.delivery_check(self.m,self.base)['ready'])

    def test_layout_result_cannot_redirect_export(self):
        a,b=self.ready()
        original=b['final_sha256']
        Image.new('RGB',(1600,1600),'red').save(self.base/'source/red.png')
        b['layout_result']['output_path']='source/red.png'
        b['export']['keywords']=['metadata change']
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertEqual(b['status'],'layout_repair_needed')
        self.assertEqual(b['final_sha256'],original)
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertEqual(b['status'],'generated')
        self.assertNotEqual(b['layout_result']['output_path'],'source/red.png')

    def test_failed_layout_cache_recovers(self):
        a,b=self.ready()
        b['status']='layout_repair_needed';b['layout_result']={'passed':False,'checks':[{'code':'RUNTIME_FAILURE','passed':False}]}
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertTrue(b['layout_result']['passed'])
        self.assertEqual(b['status'],'generated')

    def test_intermediate_mutation_rebuilds(self):
        a,b=self.ready()
        expected=b['layout_output_sha256'];raw=b['bound_raw_sha256']
        Image.new('RGB',(1600,1600),'red').save(self.base/'review/layouts/02_secondary.png')
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertEqual(p.sha256_file(self.base/'review/layouts/02_secondary.png'),expected)
        self.assertEqual(b['bound_raw_sha256'],raw)

    def test_padding_change_invalidates_local_image_not_model(self):
        a,b=self.ready()
        old=p.current_fingerprints(self.m,b,self.base)
        b['padding_color']='#eeeeee'
        new=p.current_fingerprints(self.m,b,self.base)
        self.assertEqual(old['generation'],new['generation'])
        self.assertNotEqual(old['layout'],new['layout'])
        old_image_input=b['image_input_hash']
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertNotEqual(old_image_input,b['image_input_hash'])
        self.assertEqual(b['metrics']['model_dispatches'],1)
        old=p.current_fingerprints(self.m,a,self.base)
        a['padding_color']='#eeeeee'
        self.assertNotEqual(old['generation'],p.current_fingerprints(self.m,a,self.base)['generation'])

    def test_retry_limits_and_rate_limit_reduce_concurrency(self):
        prepare_fixture(self.m,self.base);job=self.m['jobs'][1]
        for expected in (1,2,3):
            p.transition_job(self.m,job['id'],'generating',None,self.base)
            self.assertEqual(job['attempts'],expected)
            p.transition_job(self.m,job['id'],'pending','timeout',self.base)
        p.transition_job(self.m,job['id'],'generating',None,self.base)
        self.assertEqual(job['status'],'failed');self.assertEqual(self.m['concurrency'],1)
        job['status']='generation_repair_needed'
        p.transition_job(self.m,job['id'],'generating',None,self.base)
        self.assertEqual(job['quality_repairs'],1)
        job['status']='generation_repair_needed'
        p.transition_job(self.m,job['id'],'generating',None,self.base)
        self.assertEqual(job['status'],'blocked')

    def test_generation_rechecks_source_review_after_prepare(self):
        prepare_fixture(self.m,self.base)
        self.m['references'][0]['quality_review']['clarity']='unknown'
        with self.assertRaisesRegex(p.PipelineError,'Current source evidence'):
            p.transition_job(self.m,'02_secondary','generating',None,self.base)
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertEqual(self.m['jobs'][0]['status'],'blocked')
        self.assertFalse((self.base/self.m['jobs'][0]['raw_output']).exists())

    def test_pixel_composite_never_dispatches_model(self):
        prepare_fixture(self.m,self.base)
        with self.assertRaisesRegex(p.PipelineError,'local compose'):
            p.transition_job(self.m,'01_main','generating',None,self.base)

    def test_anchor_reselected_when_it_becomes_blocked(self):
        prepare_fixture(self.m,self.base)
        self.assertEqual(p.execution_plan(self.m)['anchor'],'02_secondary')
        self.m['jobs'][1]['status']='blocked'
        self.assertEqual(p.execution_plan(self.m)['anchor'],'01_main')

    def test_scheduler_counts_inflight_jobs_against_concurrency(self):
        prepare_fixture(self.m,self.base)
        self.m['jobs'][0]['status']='qa_passed'
        self.m['anchor_job_id']='01_main'
        for index in range(3,6):
            extra=copy.deepcopy(self.m['jobs'][1]);extra['id']=f'image_{index}'
            extra['status']='generating' if index==3 else 'pending'
            self.m['jobs'].append(extra)
        self.assertEqual(len(p.execution_plan(self.m)['dispatch']),1)
        self.m['concurrency']=1
        self.assertEqual(p.execution_plan(self.m)['dispatch'],[])

    def test_single_timeout_retains_parallelism_but_repeated_timeout_backs_off(self):
        prepare_fixture(self.m,self.base)
        job=self.m['jobs'][1]
        p.transition_job(self.m,job['id'],'generating',None,self.base)
        p.transition_job(self.m,job['id'],'pending','timeout',self.base)
        self.assertEqual(self.m['concurrency'],2)
        p.transition_job(self.m,job['id'],'generating',None,self.base)
        p.transition_job(self.m,job['id'],'pending','timeout',self.base)
        self.assertEqual(self.m['concurrency'],1)

    def test_shared_census_closes_all_generation(self):
        self.m['critical_detail_census_completed']=False
        bind_source_reviews(self.m,self.base);p.prepare(self.m,self.base)
        self.assertEqual(p.execution_plan(self.m)['dispatch'],[])
        with self.assertRaisesRegex(p.PipelineError,'Generation gate is closed'):
            p.transition_job(self.m,'02_secondary','generating',None,self.base)

    def test_listing_profiles_and_optional_aplus(self):
        for aspect,canvas in [('1:1',[2000,2000]),('1:1.3',[2000,2600])]:
            root=self.base/aspect.replace(':','-')
            path=p.init_project(root,'profile-test',listing_aspect=aspect,marketplace='US',language='en')
            m=p.read_json(path)
            self.assertEqual(len(m['jobs']),7)
            self.assertTrue(all(j['canvas']==canvas for j in m['jobs']))
        self.m['jobs'][1]['canvas']=[1600,2080]
        self.assertEqual(p.validate_manifest(self.m,self.base),[])
        self.m['jobs'][1]['canvas']=[1590,2067]
        self.assertTrue(any('>=1600' in e for e in p.validate_manifest(self.m,self.base)))

    def test_migration_preserves_raw_and_history_requires_new_review(self):
        self.ready();path=self.base/'project_manifest.json';self.m['schema_version']=2
        p.write_json(path,self.m);prior=path.read_bytes();raw=p.sha256_file(self.base/self.m['jobs'][1]['raw_output'])
        p.migrate_project(path)
        migrated=p.read_json(path)
        backup=self.base/migrated['migration']['backup']
        self.assertEqual(backup.read_bytes(),prior)
        self.assertEqual(raw,p.sha256_file(self.base/self.m['jobs'][1]['raw_output']))
        self.assertEqual(migrated['schema_version'],3)
        self.assertTrue(all(j['status']=='pending' for j in migrated['jobs']))

    def test_claims_require_actual_fact_ids(self):
        job=self.m['jobs'][1];job['layout']={'headline':'20 cm wide'}
        self.assertIn('NUMERIC_COPY_REQUIRES_FACT_BINDING',p.claim_issues(self.m,job))
        job['claim_ids']=['missing']
        self.assertIn('CLAIM_EVIDENCE_MISSING:missing',p.claim_issues(self.m,job))

    def test_readable_reference_cannot_bless_other_actual_layer(self):
        prepare_fixture(self.m,self.base)
        bad=copy.deepcopy(self.m['references'][0]);bad.update(id='unreviewed_back',view='back',quality_review={})
        self.m['references'].append(bad)
        self.m['jobs'][0]['product_layers'][0]['reference_id']='unreviewed_back'
        p.prepare(self.m,self.base)
        self.assertEqual(self.m['jobs'][0]['status'],'blocked')
        self.assertIn('SOURCE_',self.m['jobs'][0]['blocked_reason'])


if __name__=='__main__':unittest.main()
