"""Independent optimization boundary checks; all source/model traffic is mocked."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_bytes, sha256_json


class IndependentOptimizationTests(unittest.TestCase):
    def task(self):
        from execution_efficiency import REVISION, DEFAULTS
        return {'task_id': 'independent-offline', 'target_jurisdictions': ['US'],
            'review_policy_revision': 'final-double-review-v1',
            'final_review_execution_revision': 'adaptive-double-review-v2',
            'execution_efficiency_revision': REVISION, 'execution_efficiency': deepcopy(DEFAULTS),
            'assessment_scenarios': [{'scenario_id': 'S', 'type': 'product_entry'}]}

    def packet(self):
        return {'task': self.task(), 'evidence': {}, 'candidates': {},
            'materiality_ledger': {}, 'search_plan': {}, 'evidence_digest': 'frozen',
            'retained_originals': {'revision': 'public-originals-v2', 'materials': []}}

    def test_new_work_view_hash_binds_projected_investigation_policy(self):
        import test_api_first_v2
        from workflow_v24 import work_view_from_dir
        fixture = test_api_first_v2.ApiFirstV2Tests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.task.update({k:v for k,v in self.task().items() if k.startswith('execution_efficiency')})
        fixture.regenerate()
        view = work_view_from_dir(fixture.path, source_capabilities={})
        self.assertTrue(any('investigation_policy' in row for row in view['entries']))
        expected = sha256_json({k:v for k,v in view.items() if k not in {'work_view_sha256','review_work'}})
        self.assertEqual(view['work_view_sha256'], expected)

    def test_adaptive_count_uses_unicode_and_unique_image_content(self):
        from adaptive_review import measure
        packet = self.packet()
        data = b'actual synthetic image bytes'
        text = '图😀e\u0301'
        packet['retained_originals']['materials'] = [
            {'sha256': 'source-text', 'kind':'original_text', 'text': text},
            {'sha256': sha256_bytes(data), 'kind':'actual_image', 'attachment':'A.png'},
            {'sha256': sha256_bytes(data), 'kind':'actual_image', 'attachment':'B.png'}]
        counts = measure(packet, {'A.png': data, 'B.png': data})
        self.assertEqual(counts['review_text_chars'], 4)
        self.assertEqual(counts['review_images'], 1)
        self.assertEqual(counts['review_json_chars'], len(json.dumps(packet, ensure_ascii=False, separators=(',',':'))))

    def test_integrated_attachment_names_remain_bound_to_their_actual_images(self):
        from adaptive_review import measure
        packet = self.packet()
        front,back=b'synthetic front view',b'synthetic rear view'
        packet['retained_originals']['materials'] = [
            {'kind':'actual_image','sha256':sha256_bytes(front),'attachment':'M1.png'},
            {'kind':'actual_image','sha256':sha256_bytes(back),'attachment':'M2.png'}]
        # Both required byte blobs are present, but attached to the wrong view labels.
        with self.assertRaisesRegex(ValueError,'IMAGE_MANIFEST'):
            measure(packet, {'M1.png':back,'M2.png':front})

    def test_missing_actual_image_fails_measurement(self):
        from adaptive_review import measure
        packet = self.packet()
        packet['retained_originals']['materials'] = [{'kind':'actual_image','sha256':'missing','attachment':'M.png'}]
        with self.assertRaises(ValueError):
            measure(packet, {})

    def test_incomplete_original_manifest_falls_back_without_truncating(self):
        from adaptive_review import prepare
        packet = self.packet()
        packet['evidence'] = {'record': {'path':'missing.txt','sha256':'omitted'}}
        before = deepcopy(packet)
        with patch('module_review.attach_originals', return_value={}):
            self.assertIsNone(prepare(packet, Path('/offline'), [None,None]))
        self.assertEqual(packet, before)

    def test_threshold_equality_and_one_more_unicode_character(self):
        from adaptive_review import prepare
        packet = self.packet()
        def attach(value, directory):
            value['retained_originals']['materials'] = [{'kind':'original_text','sha256':'source','text':'字'*60000}]
            return {}
        with patch('module_review.attach_originals', side_effect=attach):
            self.assertIsNotNone(prepare(packet, Path('/offline'), [None,None]))
        def too_much(value, directory):
            result = attach(value,directory)
            value['retained_originals']['materials'][0]['text'] += '字'
            return result
        with patch('module_review.attach_originals', side_effect=too_much):
            self.assertIsNone(prepare(packet, Path('/offline'), [None,None]))

    def test_legacy_task_does_not_enter_integrated_route(self):
        from adaptive_review import prepare
        packet = self.packet()
        packet['task']['final_review_execution_revision'] = 'module-double-review-v1'
        with patch('module_review.attach_originals') as read:
            self.assertIsNone(prepare(packet, Path('/offline'), [None,None]))
        read.assert_not_called()

    def test_large_decoded_input_falls_back_even_if_highly_compressible(self):
        from adaptive_review import prepare
        packet = self.packet(); packet['evidence']['large_api_field'] = 'A'*120001
        with patch('module_review.attach_originals', return_value={}):
            self.assertIsNone(prepare(packet, Path('/offline'), [None,None]))

    def validated_context(self):
        import test_delivery_validation
        from execution_efficiency import capture_work_view
        f = test_delivery_validation.DeliveryValidationTests()
        f.setUp(); self.addCleanup(f.doCleanups)
        f.task.update({k:v for k,v in self.task().items() if k.startswith('execution_efficiency')})
        atomic_write_json(f.source/'task.json', f.task)
        atomic_write_json(f.output/'task.json', f.task)
        first = load_json(Path(f.reviews['first_review'])); second = load_json(Path(f.reviews['second_review']))
        options = {'browser_status':None,'source_capabilities':None,'first_review':first,'second_review':second}
        view = {'entries': [], 'work_view_sha256': 'independently-computed'}
        def independent(*a,**k):
            capture_work_view(f.source,options,view)
            return []
        ctx=f.begin()
        with patch('report_estimate.validate_run', side_effect=independent) as check:
            self.assertEqual(ctx.validate_staged(f.output),[])
            self.assertEqual(check.call_count,1)
        return f,ctx,first,second,view

    def test_view_cache_is_defensive_and_changed_source_rejects(self):
        f,ctx,first,second,view=self.validated_context()
        def get(): return ctx.work_view(f.output,source=f.source,first_review=first,second_review=second,reviews=f.reviews)
        result=get(); self.assertEqual(result,view)
        result['entries'].append({'state':'fake'})
        self.assertEqual(get(),view)
        task=load_json(f.source/'task.json'); task['execution_efficiency']['review_units'] += 1
        atomic_write_json(f.source/'task.json',task)
        with self.assertRaisesRegex(ValueError,'INPUT_CHANGED'): get()

    def test_view_cache_rejects_new_unknown_submission_receipt(self):
        f,ctx,first,second,_=self.validated_context()
        atomic_write_json(f.source/'browser-execution-status.json', {'queries':[{'submission_state':'unknown'}]})
        with self.assertRaisesRegex(ValueError,'INPUT_CHANGED'):
            ctx.work_view(f.output,source=f.source,first_review=first,second_review=second,reviews=f.reviews)

    def test_view_cache_rejects_modified_delivery_bytes(self):
        f,ctx,first,second,_=self.validated_context()
        (f.output/'report.html').write_text('modified output')
        with self.assertRaises(ValueError):
            ctx.work_view(f.output,source=f.source,first_review=first,second_review=second,reviews=f.reviews)

    def integrated_review(self, chain='1'):
        import test_module_review
        import module_review
        import final_review
        fixture = test_module_review.ModuleReviewTests()
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        fixture.task = self.task()
        fixture.material = final_review.inputs({}, {}, {}, {}, fixture.task)
        fixture.digest = sha256_json(fixture.material)
        scopes = module_review.required_scopes(fixture.task, set().union(*module_review.GROUPS.values()))
        rows = [{**scope, 'assessment_object':'product', 'reasoning':'Offline original review'} for scope in scopes]
        statement = {'overall':'Pending facts', 'scope':'All necessary scopes', 'limitations':'Synthetic only'}
        raw = {'assessments':rows, 'future_applications':[], 'enforcement_signals':[],
               'coverage_confidence_cap':'低','coverage_confidence_reasoning':'Retained limitations',
               'final_review_statement':statement}
        packet = {'task':fixture.task,'evidence_digest':fixture.digest,
                  'retained_originals':{'revision':'public-originals-v2','materials':[]}}
        record = fixture.record(chain,'integrated',raw,packet)
        rows,receipt = final_review.prepare_rows(raw,rows,fixture.material)
        execution = {k:record[k] for k in ('agent_id','run_id','input_digest','host_audit')}
        execution.update(assessment_digest=sha256_json(rows), final_review_digest=sha256_json(receipt),
            integrated_execution={'revision':'adaptive-double-review-v2','chain_id':chain,'record':record})
        review = {'reviewer':chain,'assessments':rows,'future_applications':[],'enforcement_signals':[],
            'coverage_confidence_cap':'低','coverage_confidence_reasoning':'Retained limitations',
            'review_context':{'session_id':record['session_id'],'evidence_digest':fixture.digest,
                'first_review_visible':False,'final_review':receipt,'execution':execution}}
        return review,fixture.material

    def test_integrated_envelopes_validate_and_two_chains_have_distinct_origins(self):
        import final_review
        first,material=self.integrated_review('1'); second,_=self.integrated_review('2')
        final_review.validate_envelope(first,material)
        final_review.validate_envelope(second,material)
        self.assertEqual(final_review.pair_summary(first,second,sha256_json(material))['status'],'complete')
        with self.assertRaisesRegex(ValueError,'NOT_INDEPENDENT'):
            final_review.pair_summary(first,deepcopy(first),sha256_json(material))

    def test_integrated_native_trace_tampering_cannot_keep_valid_envelope(self):
        import final_review
        first,material=self.integrated_review('1')
        record=first['review_context']['execution']['integrated_execution']['record']
        audit=load_json(Path(record['host_audit']['path']))
        Path(audit['trace_path']).write_text('altered trace')
        with self.assertRaisesRegex(ValueError,'TRACE_CHANGED'):
            final_review.validate_envelope(first,material)

    def test_integrated_missing_required_unit_cannot_be_hidden_by_rebinding_receipt(self):
        import final_review
        import module_review
        from common import sha256_file
        first,material=self.integrated_review('1')
        first['assessments'].pop()
        record=first['review_context']['execution']['integrated_execution']['record']
        raw=deepcopy(record['judgment']); raw['assessments']=deepcopy(first['assessments'])
        audit_path=Path(record['host_audit']['path']); audit=load_json(audit_path)
        atomic_write_json(Path(audit['judgment_path']),raw)
        trace=[{'type':'thread.started','thread_id':record['session_id']},{'type':'turn.started'},
               {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(raw)}},{'type':'turn.completed'}]
        Path(audit['trace_path']).write_text('\n'.join(json.dumps(row) for row in trace))
        audit['judgment_sha256']=sha256_file(Path(audit['judgment_path']))
        audit['trace_sha256']=sha256_file(Path(audit['trace_path']))
        atomic_write_json(audit_path,audit)
        record.update(judgment=raw,host_audit={'path':str(audit_path),'sha256':sha256_file(audit_path)})
        rows,receipt=final_review.prepare_rows(raw,first['assessments'],material)
        first['review_context']['final_review']=receipt
        with self.assertRaisesRegex(ValueError,'SCOPE_MISSING'):
            module_review.validate_execution(first,required=True)

if __name__ == '__main__': unittest.main()
