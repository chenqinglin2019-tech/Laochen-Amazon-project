"""10E observable frozen-byte delivery, retry and correction behavior; offline."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import atomic_write_json, load_json, sha256_file
import delivery_versions_stage_e as delivery
from test_evidence_delivery_integration import build_evidence_delivery_fixture
import test_stage_delivery_stage_d as stage_fixtures
from stage_delivery_stage_d import create_output

class DeliveryVersionsTests(unittest.TestCase):
    def report(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        source=Path(tmp.name)/'source'
        build_evidence_delivery_fixture(source,report_exports=['csv'],independent_inspection=True,reliable_delivery=True)
        journal=load_json(source/delivery.JOURNAL)
        return source,source/'report',journal['versions'][0]['version_id']

    def stage(self):
        f=stage_fixtures.StageDeliveryTest();f.setUp();self.addCleanup(f.doCleanups)
        f.task.update(delivery_inspection_revision='delivery-inspection-stage-d-v1',delivery_versions_revision=delivery.REVISION)
        f.save();return f

    def test_build_is_not_delivery_and_actual_entry_bytes_are_rechecked(self):
        source,build,version=self.report()
        self.assertEqual(delivery.entry_errors(source,build),['DELIVERY_ACTUAL_ENTRY_NOT_VERIFIED'])
        target=source.parent/'entry'
        result=delivery.deliver(source,version,target)
        self.assertEqual(result['status'],'delivered',result)
        self.assertEqual(delivery.entry_errors(source,target),[])
        self.assertEqual(sha256_file(build/'report.html'),sha256_file(target/'report.html'))
        self.assertEqual(load_json(build/'report-data.json')['business_status_stage_b']['delivery_status'],'not_verified')
        (target/'report.html').write_text('wrong bytes')
        self.assertTrue(delivery.entry_errors(source,target))

    def test_completion_gate_uses_business_projection_after_entry_check(self):
        source,build,version=self.report()
        from completion_check import workflow_stage
        first,second=source/'first-review.json',source/'second-review.json'
        chief=source/'gate-chief.json'
        atomic_write_json(chief,{'review_context':{'session_id':'offline','evidence_digest':'offline'}})
        packet={key:[] for key in ('source','agent','repair','review','waiting')}
        view={'entries':[]}
        # This narrow gate test isolates validated semantic / entry facts; the
        # independent real-byte path and business classifier have separate cases.
        for business,expected in (('continue','validation'),('limited_round_closed','limited_round_closed'),('business_complete','complete')):
            with self.subTest(business=business):
                data=load_json(build/'report-data.json');data['business_status_stage_b']['business_status']=business
                with patch('completion_check.validate_delivery',return_value=[]), \
                     patch('completion_check.load_json',side_effect=lambda path: data if Path(path).name=='report-data.json' else load_json(path)), \
                     patch('delivery_versions_stage_e.entry_errors',return_value=[]):
                    self.assertEqual(workflow_stage(view,packet,first_review=first,second_review=second,
                        adjudication=chief,output_dir=build,task_dir=source),expected)

    def test_failed_build_with_valid_artifacts_can_retry_validation_only(self):
        f=self.stage();build=f.root/'build';version=delivery.begin_build(f.source,build,kind='stage')
        from stage_delivery_stage_d import _create_local_output
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            _create_local_output(f.source,build)
            before={p.name:sha256_file(p) for p in f.source.iterdir() if p.is_file() and p.name!=delivery.JOURNAL}
            delivery.fail_build(f.source,version,OSError('after generation'))
            verified=delivery.finish_build(f.source,version)
        self.assertEqual(verified['delivery_status'],'not_delivered')
        self.assertEqual(before,{p.name:sha256_file(p) for p in f.source.iterdir() if p.is_file() and p.name!=delivery.JOURNAL})

    def test_copy_failure_retry_reuses_build_and_preserves_source(self):
        source,build,version=self.report()
        before={name:sha256_file(source/name) for name in delivery.INPUTS if (source/name).is_file()}
        with patch('delivery_versions_stage_e._copy_files',side_effect=OSError('copy failed')):
            result=delivery.deliver(source,version,source.parent/'failed')
        self.assertEqual(result['failed_step'],'copy');self.assertIsNone(result['entry'])
        result=delivery.deliver(source,version,source.parent/'retry')
        self.assertEqual(result['status'],'delivered',result)
        self.assertEqual(before,{name:sha256_file(source/name) for name in before})
        self.assertFalse(result['automatic_investigation_resume'])

    def test_actual_copy_missing_material_fails_without_success_entry(self):
        source,build,version=self.report(); original=delivery._copy_files
        def missing(b,t,files):
            original(b,t,files)
            material=next(name for name in files if name.startswith('files/'))
            (t/material).unlink()
        with patch('delivery_versions_stage_e._copy_files',side_effect=missing):
            result=delivery.deliver(source,version,source.parent/'bad-entry')
        self.assertEqual(result['failed_step'],'entry_recheck');self.assertIsNone(result['entry'])
        self.assertTrue(result['error'].startswith('ValueError:DELIVERY_ACTUAL_FILE'))

    def test_retained_original_bytes_change_is_not_hidden_by_unchanged_json(self):
        source,build,version=self.report()
        row=load_json(source/delivery.JOURNAL)['versions'][0]
        material=next(Path(name) for name,digest in row['snapshot']['retained_files'].items() if digest is not None)
        material.write_bytes(b'changed original bytes')
        result=delivery.deliver(source,version,source.parent/'entry')
        self.assertEqual(result['failed_step'],'snapshot_check')
        self.assertIsNone(result['entry'])

    def test_actual_local_json_reference_must_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'report.html').write_text('<a href="data.json#/missing">材料</a>')
            atomic_write_json(root/'data.json',{'evidence_index':[]})
            errors=delivery._file_errors(root,{name:sha256_file(root/name) for name in ('report.html','data.json')})
            self.assertTrue(any(error.startswith('DELIVERY_JSON_REFERENCE_UNAVAILABLE:') for error in errors))

    def test_original_html_keeps_source_links_but_report_links_and_all_bytes_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'files').mkdir()
            original = root / 'files' / 'original.html'
            original.write_text('<link href="/themes/source.css"><a href="../source-page">original</a>')
            report = root / 'report.html'
            report.write_text('<a href="files/original.html">retained original</a>')
            hashes = {name: sha256_file(root / name) for name in ('report.html', 'files/original.html')}
            self.assertEqual(delivery._file_errors(root, hashes), [])
            original.write_text('changed original')
            self.assertIn('DELIVERY_ACTUAL_FILE_MISSING_OR_CHANGED:files/original.html',
                          delivery._file_errors(root, hashes))
            report.write_text('<a href="/themes/source.css">outside-root</a><a href="missing.html">missing</a>')
            hashes['report.html'] = sha256_file(report)
            errors = delivery._file_errors(root, hashes)
            self.assertTrue(any(error.startswith('DELIVERY_LOCAL_REFERENCE_OUTSIDE_ROOT:') for error in errors))
            self.assertTrue(any(error.startswith('DELIVERY_LOCAL_REFERENCE_UNAVAILABLE:') for error in errors))

    def test_changed_product_blocks_frozen_build_before_copy(self):
        source,build,version=self.report()
        task=load_json(source/'task.json');task['product']['title']='另一个产品';atomic_write_json(source/'task.json',task)
        result=delivery.deliver(source,version,source.parent/'entry')
        self.assertEqual(result['failed_step'],'snapshot_check');self.assertIsNone(result['entry'])
        self.assertEqual(delivery.status(source)['versions'][0]['applicability'],'pending_recheck')

    def test_shared_build_corruption_requires_build_recheck(self):
        source,build,version=self.report();(build/'report-data.json').write_text('{}')
        result=delivery.deliver(source,version,source.parent/'entry')
        self.assertEqual(result['failed_step'],'build_recheck')

    def test_build_change_after_freeze_fails_and_records_step(self):
        f=self.stage();build=f.root/'build'
        version=delivery.begin_build(f.source,build,kind='stage')
        from stage_delivery_stage_d import _create_local_output
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            _create_local_output(f.source,build)
            f.task['product']['title']='changed';f.save()
            with self.assertRaisesRegex(ValueError,'INPUTS_CHANGED'):
                delivery.finish_build(f.source,version)
        delivery.fail_build(f.source,version,ValueError('DELIVERY_BUILD_INPUTS_CHANGED'))
        self.assertEqual(load_json(f.source/delivery.JOURNAL)['versions'][0]['state'],'build_failed')

    def test_old_entry_survives_new_version_failure(self):
        source,build,version=self.report();old=source.parent/'old'
        self.assertEqual(delivery.deliver(source,version,old)['status'],'delivered')
        digest=sha256_file(old/'report.html')
        # A second build is the same validated source with a new delivery version.
        from publish_report import publish
        result=publish(source,source/'first-review.json',source/'second-review.json',output_dir=source/'build2',mode='auto')
        with patch('delivery_versions_stage_e._copy_files',side_effect=OSError('failed')):
            failed=delivery.deliver(source,result['version_id'],source.parent/'new')
        self.assertEqual(failed['status'],'delivery_failed')
        self.assertEqual(sha256_file(old/'report.html'),digest)
        self.assertEqual(delivery.entry_errors(source,old),[])

    def test_stage_reply_actual_carrier_checked_without_full_pack(self):
        f=self.stage();f.task.update(report_package_revision='report-package-stage-c-v1',report_exports=[],stage_carriers=['reply']);f.save()
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build')
            delivered=delivery.deliver(f.source,built['version_id'],f.root/'entry')
            self.assertEqual(delivered['status'],'delivered',delivered)
            self.assertEqual(Path(delivered['entry']).name,'stage-result.txt')
            self.assertFalse((f.root/'entry'/'report.html').exists())

    def test_progress_only_preserves_frozen_risk_and_discloses_new_cutoff(self):
        f=self.stage()
        f.task.update(target_jurisdictions=['US'],assessment_scenarios=[{'scenario_id':'base'}])
        query={'query_id':'Q1','jurisdiction':'US','right_type':'patent','scenario_id':'base'}
        from common import sha256_json
        f.save();atomic_write_json(f.source/'search-plan.json',{'queries':{'registry':[query]}})
        from review_progress_stage_a import record_event
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            record_event(f.source,{'kind':'initialize','actor':'reviewer','reasoning':'known query',
                'items':[{'item_id':'ITEM-1','kind':'query','query_id':'Q1','module_ids':['utility_patent'],
                    'scope':{k:f.scope[k] for k in ('scenario_id','jurisdiction','right_type','product_version')},
                    'acceptance_condition':'review retained result'}]})
            f.evidence=load_json(f.source/'evidence.json')
            f.evidence['source_runs']=[{'run_id':'R1','provider':'registry','query_id':'Q1',
                'plan_entry_sha256':sha256_json(query),'submission_state':'submitted','status':'no_result'}]
            f.save()
            built=create_output(f.source,f.root/'build')
            record_event(f.source,{'kind':'complete','actor':'reviewer','reasoning':'reviewed existing result',
                'item_id':'ITEM-1','source_run_id':'R1','evidence_refs':['R1']})
            f.view['review_progress']['completed']=61
            delivered=delivery.deliver(f.source,built['version_id'],f.root/'entry')
            self.assertEqual(delivered['status'],'delivered',delivered)
            self.assertEqual(delivered['known_changes']['change_type'],'progress_only')
            self.assertEqual(delivered['known_changes']['current_progress']['completed'],61)
            self.assertEqual(load_json(f.root/'entry'/'stage-result.json')['progress']['completed'],60)
            self.assertEqual(load_json(f.root/'entry'/'stage-result.json')['stage_risk']['overall']['stage_risk'],'高')

    def test_new_source_fact_is_not_guessed_as_harmless_progress(self):
        f=self.stage()
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build')
            f.evidence['source_runs'].append({'run_id':'R2','status':'success','fact':'new conflict'});f.save()
            result=delivery.deliver(f.source,built['version_id'],f.root/'entry')
            self.assertEqual(result['status'],'delivery_failed')

    def test_display_correction_preserves_old_files_and_result_times(self):
        source,build,version=self.report();old=source.parent/'old'
        delivery.deliver(source,version,old)
        note=delivery.record_correction(source,version,{'kind':'display','reason':'CSV 副本恢复','changes':['仅修复 CSV 副本']})
        self.assertFalse(note['downloaded_old_copies_updated'])
        # Repair produces the identical canonical result; a new version records its linkage.
        from delivery_inspection_stage_d import repair
        (build/'report-findings.csv').write_text('bad')
        repaired=source.parent/'repaired';repair(source,build,repaired)
        # Register an existing independently valid repaired build via the CLI.
        import subprocess,sys
        command=[sys.executable,str(Path(delivery.__file__)),'--task-dir',str(source),'--action','adopt',
            '--build-dir',str(repaired),'--correction-id',note['correction_id']]
        run=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        import json
        adopted=json.loads(run.stdout)
        result=delivery.deliver(source,adopted['version_id'],source.parent/'corrected')
        self.assertEqual(result['status'],'delivered',result)
        self.assertEqual(result['correction']['status'],'replaced')
        self.assertEqual(sha256_file(old/'report-data.json'),sha256_file(source.parent/'corrected'/'report-data.json'))
        self.assertEqual(delivery.status(source)['versions'][0]['applicability'],'superseded')

    def test_material_change_suspends_old_overall_before_new_version_and_failure(self):
        import test_stage_risk_stage_b as risk_fixtures
        from stage_risk_stage_b import snapshot
        f=risk_fixtures.StageRiskStageBTests();f.setUp();self.addCleanup(f.doCleanups)
        f.task.update(product={'product_id':'P1','title':'产品'},
            stage_delivery_revision='stage-delivery-stage-d-v1',
            delivery_inspection_revision='delivery-inspection-stage-d-v1',delivery_versions_revision=delivery.REVISION)
        judgment=f.record(f.request())
        view={'status':'incomplete','entries':[],'stage_risk':snapshot(f.task,f.evidence)}
        with patch('workflow_v24.work_view_from_dir',return_value=view):
            built=create_output(f.path,f.path/'build')
            self.assertEqual(delivery.deliver(f.path,built['version_id'],f.path/'old')['status'],'delivered')
            old_hash=sha256_file(f.path/'old'/'stage-result.json')
            f.evidence['product_scope_events']=[{'event_id':'CHANGED-FACT'}]
            f.record({'kind':'invalidate','actor':'reviewer','reasoning':'material fact changed',
                'judgment_id':judgment['event_id'],'upstream_ref':'CHANGED-FACT',
                'impact':'may change overall high','recovery_action':'targeted re-review'})
            view['stage_risk']=snapshot(f.task,f.evidence)
            note=delivery.record_correction(f.path,built['version_id'],{'kind':'material',
                'reason':'关键事实失效','changes':['定向复核当前高风险'],
                'affected_judgment_ids':[judgment['event_id']],'upstream_refs':['CHANGED-FACT']})
            current=delivery.status(f.path)['versions'][0]
            self.assertEqual(current['applicability'],'pending_recheck')
            self.assertIsNone(current['known_changes']['current_stage']['stage_risk']['overall']['stage_risk'])
            interim=create_output(f.path,f.path/'interim',correction_id=note['correction_id'])
            with patch('delivery_versions_stage_e._copy_files',side_effect=OSError('failed')):
                failed=delivery.deliver(f.path,interim['version_id'],f.path/'new-failed')
            self.assertEqual(failed['status'],'delivery_failed')
            self.assertEqual(delivery.status(f.path)['versions'][0]['applicability'],'pending_recheck')
            self.assertEqual(sha256_file(f.path/'old'/'stage-result.json'),old_hash)
            result=delivery.deliver(f.path,interim['version_id'],f.path/'new-stage')
            self.assertEqual(result['status'],'delivered',result)
            self.assertEqual(result['correction']['status'],'interim_stage_delivered')
            self.assertIsNone(load_json(f.path/'new-stage'/'stage-result.json')['stage_risk']['overall']['stage_risk'])
            self.assertEqual(delivery.status(f.path)['versions'][0]['applicability'],'pending_recheck')

    def test_display_correction_cannot_hide_product_change(self):
        f=self.stage()
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build')
            delivery.deliver(f.source,built['version_id'],f.root/'old')
            note=delivery.record_correction(f.source,built['version_id'],{'kind':'display','reason':'声称文字修正','changes':['产品标题改动']})
            f.task['product']['title']='different product';f.save()
            with self.assertRaisesRegex(ValueError,'CHANGED_SUBSTANCE'):
                create_output(f.source,f.root/'new',correction_id=note['correction_id'])

    def test_pause_added_after_build_does_not_resume_investigation(self):
        f=self.stage()
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build')
            f.evidence['continuation_events']=[{'kind':'pause','event_id':'PAUSE','scope':{'level':'task'}}];f.save()
            result=delivery.deliver(f.source,built['version_id'],f.root/'entry')
            self.assertEqual(result['status'],'delivered',result)
            self.assertEqual(result['known_changes']['change_type'],'pause_only')
            self.assertFalse(result['automatic_investigation_resume'])
            self.assertEqual(load_json(f.source/'evidence.json')['continuation_events'][0]['kind'],'pause')

    def test_pause_delivery_remains_valid_across_wall_clock_seconds(self):
        f=self.stage()
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build')
            f.evidence['continuation_events']=[{'kind':'pause','event_id':'PAUSE','scope':{'level':'task'}}];f.save()
            # Crossing the second must not manufacture a material input change.
            with patch('stage_delivery_stage_d.now_iso',side_effect=['2099-01-01T00:00:00Z','2099-01-01T00:00:01Z']):
                result=delivery.deliver(f.source,built['version_id'],f.root/'entry')
            self.assertEqual(result['status'],'delivered',result)
            self.assertEqual(result['known_changes']['change_type'],'pause_only')
            self.assertFalse(result['automatic_investigation_resume'])
            self.assertEqual(load_json(f.source/'evidence.json')['continuation_events'][0]['event_id'],'PAUSE')

    def test_pause_delivery_still_rejects_material_change_during_copy(self):
        f=self.stage();original_copy=delivery._copy_files
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build')
            f.evidence['continuation_events']=[{'kind':'pause','event_id':'PAUSE','scope':{'level':'task'}}];f.save()
            def copy_and_change(build,target,files):
                original_copy(build,target,files)
                f.task['product']['title']='Substantively changed product';f.save()
            with patch('delivery_versions_stage_e._copy_files',side_effect=copy_and_change):
                result=delivery.deliver(f.source,built['version_id'],f.root/'entry')
            self.assertEqual(result['status'],'delivery_failed',result)
            self.assertEqual(result['error'],'ValueError:DELIVERY_CHANGED_DURING_ENTRY_CHECK')
            self.assertIsNone(result['entry']);self.assertFalse(result['automatic_investigation_resume'])
            self.assertEqual(load_json(f.source/'evidence.json')['continuation_events'][0]['event_id'],'PAUSE')

    def test_page_location_does_not_justify_display_classification(self):
        source,build,version=self.report();delivery.deliver(source,version,source.parent/'old')
        with self.assertRaisesRegex(ValueError,'MATERIAL_UPSTREAM_REQUIRED'):
            delivery.record_correction(source,version,{'kind':'material','reason':'引用错权利','changes':['定位到错误权利']})

    def test_pause_and_historical_counts_are_not_changed_by_delivery(self):
        f=self.stage();f.evidence['continuation_events']=[{'kind':'pause','event_id':'PAUSE','scope':{'level':'task'}}];f.save()
        before=deepcopy(f.evidence)
        with patch('workflow_v24.work_view_from_dir',return_value=f.view):
            built=create_output(f.source,f.root/'build');result=delivery.deliver(f.source,built['version_id'],f.root/'entry')
        self.assertEqual(result['status'],'delivered',result)
        self.assertEqual(load_json(f.source/'evidence.json'),before)

if __name__=='__main__':unittest.main()
