"""Offline prompt regressions. All products, pixels and verdicts are fixtures."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import lc_design_templates as templates
import lc_image_pipeline as pipeline
import lc_workflow as workflow
from PIL import Image
from lc_prompting import PROFILE
from pipeline_test_support import (create_v3_fixture, SECONDARY_ID, NOTE,
                                   prepare_fixture, simulate_secondary_output, finish_fixture, bind_source_reviews)


class PromptProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.manifest = create_v3_fixture(self.base)
        self.job = self.manifest['jobs'][1]
        for detail in self.manifest['critical_details']:
            detail['status'] = 'confirmed'
            detail['reference_crops'] = [{'path': 'detail_refs/' + detail['id'] + '.png',
                'view': 'front', 'reference_id': 'product_front', 'verifiable': True}]

    def tearDown(self):
        self.tmp.cleanup()

    def prompt(self, job=None):
        return pipeline.compile_job_prompt(self.manifest, job or self.job, self.base)[0]

    def test_legacy_prompt_and_generation_hashes_match_prechange_baseline(self):
        # Captured with the unmodified compiler before this implementation.
        baseline = {
            'none': ('273ce56c55740e4c7c896359b76bf24c7e861856f70ba2c0376f7eea3591b5f1',
                     '460fdad055c2e35911840252b45b870455b7b94e9d717a1ce9be3636fb299541'),
            'local_overlay': ('73adf3d19fba77fde0715ea95c17f3f5c0cf0f2b9924ad5025d08e6c97681bcd',
                              '05e7b9057e0f15b0390bba442b0b1ea36a5d1e62feaa2952b81a48aa914c6cc0'),
            'model_native': ('be88aa373ff13916f95d6d8fcaa872a899f8727ae833881ee6660b0b49b388cf',
                             '49d689c1c4b0967ea3d99a219dda0f4c597afa4dac521c6cff921a9552cf2b9b'),
        }
        for mode, (prompt_hash, generation_hash) in baseline.items():
            job = copy.deepcopy(self.job)
            job['text_mode'] = mode
            if mode == 'model_native':
                job.update(copy={'headline': 'Fixture Accent', 'body': 'For the test scene'},
                           design_brief={'generation': {'lighting': 'Gentle side light.'},
                                         'layout': {'headline_tone': 'clean bold sans'}})
            for profile in (None, 'legacy'):
                if profile:
                    job['prompt_profile'] = profile
                with self.subTest(mode=mode, profile=profile):
                    self.assertEqual(hashlib.sha256(self.prompt(job).encode()).hexdigest(), prompt_hash)
                    self.assertEqual(pipeline.generation_fingerprint(self.manifest, job, self.base), generation_hash)
        self.assertEqual(pipeline.PIPELINE_VERSION, '3.0.0')

    def test_new_prompt_labels_actual_attachment_order_and_four_constraints(self):
        self.job.update(prompt_profile=PROFILE, text_mode='local_overlay')
        prompt, required, hidden, paths = pipeline.compile_job_prompt(self.manifest, self.job, self.base)
        self.assertTrue(prompt.startswith('Use case: product-mockup'))
        for index, path in enumerate(paths, 1):
            self.assertIn(f'Image {index}: {path}', prompt)
        for name in ('Geometry /', 'Material /', 'Scene scale /', 'Critical detail /'):
            self.assertIn(name, prompt)
        self.assertIn('natural perspective', prompt)
        self.assertIn('Preserve authentic product labels', prompt)
        self.assertIn('usb_c_port', required)
        self.assertEqual(hidden, [])
        self.assertNotIn('resolved_prompt', prompt)

    def test_edit_target_and_style_evidence_have_different_roles(self):
        self.job.update(prompt_profile=PROFILE, render_mode='reference_edit')
        self.manifest['references'].append({'id': 'style', 'path': 'style.png', 'role': 'style_reference'})
        self.job['source_reference_ids'].insert(0, 'style')
        prompt = self.prompt()
        self.assertIn('Use case: precise-object-edit', prompt)
        self.assertIn('Image 1: source/product_front.png — edit target', prompt)
        self.assertIn('Image 2: style.png — design reference only', prompt)

    def test_ambiguous_edit_target_blocks_until_explicit_whole_source_is_selected(self):
        self.job.update(prompt_profile=PROFILE, render_mode='reference_edit')
        second = {**self.manifest['references'][0], 'id': 'second', 'path': 'second.png'}
        self.manifest['references'].append(second)
        self.job['source_reference_ids'].insert(0, 'second')
        self.assertIn('Prompt preparation blocked', self.prompt())
        self.job['pixel_source_reference_id'] = 'product_front'
        self.assertIn('Image 1: source/product_front.png — edit target', self.prompt())

    def test_material_reference_is_local_evidence_not_edit_target(self):
        self.job.update(prompt_profile=PROFILE, render_mode='reference_edit')
        self.manifest['references'].append({'id': 'material', 'path': 'material.png', 'role': 'material_reference'})
        self.job['source_reference_ids'].insert(0, 'material')
        prompt = self.prompt()
        self.assertIn('Image 1: source/product_front.png — edit target', prompt)
        self.assertIn('Image 2: material.png — material reference; evidence only for its visible detail', prompt)

    def test_composite_prompt_requests_background_without_drawing_product_details(self):
        main = self.manifest['jobs'][0]
        main.update(prompt_profile=PROFILE, text_mode='none')
        prompt = self.prompt(main)
        self.assertIn('only the compatible empty photographic background', prompt)
        self.assertIn('Do not paint a substitute product', prompt)
        self.assertNotIn('Critical detail /', prompt)
        self.assertNotIn('USB-C fixture opening', prompt)
        self.assertNotIn('Subject:', prompt)
        main['design_brief'] = {'generation': {
            'composition': 'Make the product fill the frame.',
            'focus': 'Show every product detail.', 'background': 'Neutral wall.',
            'resolved_prompt': 'Make the product fill the frame. Extra product closeup.'}}
        prompt = self.prompt(main)
        self.assertIn('Neutral wall.', prompt)
        self.assertNotIn('Show every product detail', prompt)
        self.assertNotIn('Extra product closeup', prompt)

    def test_native_copy_is_verbatim_once_and_local_copy_never_enters_generation(self):
        self.job.update(prompt_profile=PROFILE, text_mode='model_native',
                        copy={'headline': "L'été à la maison", 'body': 'An everyday accent.'})
        prompt = self.prompt()
        for text in self.job['copy'].values():
            self.assertEqual(prompt.count(text), 1)
        self.assertNotIn('Text policy: no added marketing text', prompt)
        self.assertIn('no extra marketing text', prompt)
        self.job.pop('copy')
        self.job.update(text_mode='local_overlay', layout={'headline': 'Local wording'})
        self.job['generation_geometry_lock'] = {'image_region_norm': [0, 0, 1, 1],
            'product_region_norm': self.job['target_product_bbox_norm'], 'text_regions_norm': [[.05, .05, .8, .1]]}
        before = pipeline.generation_fingerprint(self.manifest, self.job, self.base)
        self.job['layout']['headline'] = 'Changed locally'
        self.job['layout']['text_color'] = '#123456'
        self.assertEqual(before, pipeline.generation_fingerprint(self.manifest, self.job, self.base))
        self.assertNotIn('Changed locally', self.prompt())

    def test_required_and_hidden_details_keep_existing_evidence_gates(self):
        self.job['prompt_profile'] = PROFILE
        detail = self.manifest['critical_details'][0]
        detail['reference_crops'] = []
        self.prompt()
        self.assertEqual(self.job['status'], 'blocked')
        self.assertEqual(self.job['blocked_reason'], 'DETAIL_UNVERIFIABLE:usb_c_port')
        detail['visibility'][SECONDARY_ID] = 'hidden'
        prompt = self.prompt()
        self.assertIn('hidden in the target view', prompt)
        self.assertIn('Do not reveal it, relocate it', prompt)

    def test_all_builtin_templates_keep_active_canvas_and_unique_photography(self):
        library = json.loads((Path(pipeline.SCRIPT_DIR).parent / 'assets/layouts/design_templates.json').read_text())
        families = {(f['id'], f['revision']): f for f in library['families']}
        self.assertEqual(len(library['templates']), 27)
        dimensions = {'square': [2000, 2000], 'portrait': [2000, 2600], 'wide': [1800, 900]}
        adapted_backgrounds = {'editorial-tactile-sidebar': 'darker quiet area inside the planned information container',
                               'warm-offset-intimate': 'quiet field inside the planned information container',
                               'warm-compact-footer': 'deliberate quiet gap or pale surface inside the planned information container'}
        for template in library['templates']:
            family = next(f for (name, _), f in families.items() if name == template['family_id'])
            for shape in template['canvas_shapes']:
                for mode in ('local_overlay', 'model_native'):
                    with self.subTest(template=template['id'], shape=shape, mode=mode):
                        job = copy.deepcopy(self.job)
                        job.update(prompt_profile=PROFILE, text_mode=mode, canvas=dimensions[shape],
                                   composition='', lighting='', kind='a_plus' if shape == 'wide' else 'listing')
                        if mode == 'model_native':
                            job['copy'] = {'headline': 'Approved Fixture Headline'}
                        result = templates.compile_template(family, template,
                            {'product': self.manifest['product_truth']['product']}, job)
                        job['design_brief'] = result['brief']
                        job['design_resolution'] = {'binding': result['binding']}
                        variant = template['layout']['canvas_variants'][shape]
                        prompt = self.prompt(job)
                        self.assertIn(variant['composition_note'], prompt)
                        for field in ('background', 'lighting', 'focus'):
                            if field == 'background' and template['id'] in adapted_backgrounds:
                                self.assertEqual(prompt.count(adapted_backgrounds[template['id']]), 1)
                                self.assertNotIn(template['generation'][field], prompt)
                            else:
                                self.assertEqual(prompt.count(template['generation'][field]), 1, field)
                        self.assertNotIn(template['generation']['composition'], prompt)
                        self.assertNotIn(template['generation']['reserved_space'], prompt)
                        self.assertNotIn('resolved_prompt', prompt)
                        self.assertNotIn('canvas_adaptation', prompt)
                        for safeguard in template['generation']['product_safeguards']:
                            self.assertEqual(prompt.count(safeguard), 1)
                        if mode == 'local_overlay':
                            self.assertNotIn(family['style']['graphics'], prompt)
                            self.assertEqual(job['design_brief']['generation']['family_visual_style']['graphics'],
                                             family['style']['graphics'])
                        if mode == 'model_native':
                            self.assertEqual(pipeline.generation_geometry(job)['product_region_norm'],
                                             variant['product_region_norm'])
                            self.assertEqual(pipeline.generation_geometry(job)['text_regions_norm'],
                                             [variant['text_group_box']])
                            self.assertEqual(prompt.count('Approved Fixture Headline'), 1)
                            self.assertNotIn('Generate no marketing text', prompt)
                            self.assertNotIn(family['style']['rhythm'], prompt)
                            reading = next(line for line in prompt.splitlines() if '/ reading order:' in line)
                            self.assertNotRegex(reading, r'(?i)\b(upper|footer|header band|right-side|left-weighted|lower|beside|above)\b')

    def test_overrides_do_not_resurrect_original_template_text(self):
        self.job.update(prompt_profile=PROFILE, composition='Product at the approved center.', lighting='Warm light.')
        old = {'composition': 'Put it on the left.', 'lighting': 'Cold light.', 'background': 'Neutral room.'}
        self.job['design_brief'] = {'generation': {**old, 'lighting': 'Warm light.',
            'resolved_prompt': 'Put it on the left. Cold light. Neutral room. Retain this unique styling detail.'}}
        self.job['design_resolution'] = {'binding': {'template': {'snapshot': {'generation': old}}}}
        prompt = self.prompt()
        self.assertNotIn('Put it on the left.', prompt)
        self.assertNotIn('Cold light.', prompt)
        self.assertEqual(prompt.count('Neutral room.'), 1)
        self.assertEqual(prompt.count('Warm light.'), 1)
        self.assertIn('Retain this unique styling detail.', prompt)

    def test_native_prepare_resolves_canvas_before_source_review_and_dispatch(self):
        self.manifest = create_v3_fixture(self.base)
        self.job = self.manifest['jobs'][1]
        library = json.loads((Path(pipeline.SCRIPT_DIR).parent / 'assets/layouts/design_templates.json').read_text())
        template = library['templates'][0]
        family = next(f for f in library['families'] if f['id'] == template['family_id'])
        self.job.update(prompt_profile=PROFILE, text_mode='model_native', canvas=[2000, 2600],
                        copy={'headline': 'Everyday Accent'}, composition='', lighting='',
                        model_native_reason={'kind': 'native_poster', 'notes': NOTE})
        result = templates.compile_template(family, template,
            {'product': self.manifest['product_truth']['product']}, self.job)
        self.job.update(design_brief=result['brief'], design_resolution={'binding': result['binding']})
        bind_source_reviews(self.manifest, self.base)
        pipeline.prepare(self.manifest, self.base, [SECONDARY_ID])
        variant = template['layout']['canvas_variants']['portrait']
        self.assertEqual(self.job['target_product_bbox_norm'], variant['product_region_norm'])
        # A changed composition still requires the existing source-context review.
        self.assertIn('SOURCE_ASSESSMENT_CONTEXT_STALE', self.job['blocked_reason'])
        bind_source_reviews(self.manifest, self.base)
        pipeline.prepare(self.manifest, self.base, [SECONDARY_ID])
        bound = self.job['prompt_hash']
        pipeline.transition_job(self.manifest, SECONDARY_ID, 'generating', NOTE, self.base)
        self.assertEqual(self.job['status'], 'generating')
        self.assertEqual(bound, pipeline.generation_fingerprint(self.manifest, self.job, self.base))

    def test_repair_context_rejects_invalid_shape_paths_and_missing_failures(self):
        from lc_design import validate_design
        for edit in (None, {}, [], {'target_path': '/tmp/out.png', 'failures': ['geometry']},
                     {'target_path': '../out.png', 'failures': ['geometry']},
                     {'target_path': 'raw/out.png', 'failures': []},
                     {'target_path': 'raw/out.png', 'failures': [None]}):
            with self.subTest(edit=edit):
                self.assertIn('prompt_edit requires', ' '.join(validate_design(
                    {'prompt_profile': PROFILE, 'text_mode': 'none', 'prompt_edit': edit})))

    def test_only_explicitly_upgraded_job_invalidates_and_repair_budget_remains(self):
        pipeline.compile_prompts(self.manifest, self.base)
        sibling = copy.deepcopy(self.manifest['jobs'][0])
        self.job.update(status='qa_passed', quality_repairs=1,
                        generated_prompt_hash=self.job['prompt_hash'], semantic_qa_results={'geometry': 'pass'})
        before = self.job['prompt_hash']
        self.job['prompt_profile'] = PROFILE
        pipeline.compile_prompts(self.manifest, self.base, [SECONDARY_ID])
        self.assertEqual(sibling, self.manifest['jobs'][0])
        self.assertNotEqual(before, self.job['prompt_hash'])
        self.assertEqual(self.job['status'], 'pending')
        self.assertEqual(self.job['semantic_qa_results'], {})
        self.assertEqual(self.job['quality_repairs'], 1)

    def test_detail_repair_uses_explicit_cross_view_evidence_and_rejects_missing(self):
        self.job['prompt_profile'] = PROFILE
        detail = self.manifest['critical_details'][0]
        self.job['detail_evidence_reference_ids'] = {detail['id']: ['product_front']}
        relative = pipeline.create_repair_prompt(self.manifest, self.job, detail, self.base)
        prompt = (self.base / relative).read_text()
        self.assertIn('Image 2: detail_refs/usb_c_port.png', prompt)
        self.assertIn('known fixture coordinates', prompt)
        self.assertIn('Evidence view: front;', prompt)
        self.assertNotIn('pixel-for-pixel unchanged', prompt)
        detail['reference_crops'] = []
        with self.assertRaisesRegex(pipeline.PipelineError, 'DETAIL_UNVERIFIABLE'):
            pipeline.create_repair_prompt(self.manifest, self.job, detail, self.base)

    def test_semantic_repair_corrects_only_failures_and_preserves_copy(self):
        self.job.update(prompt_profile=PROFILE, text_mode='model_native', copy={'headline': 'A Simple Accent'})
        path = pipeline.create_semantic_repair_prompt(self.job, ['text:spelling', 'text:spelling'], self.base)
        prompt = (self.base / path).read_text()
        self.assertEqual(prompt.count('text:spelling'), 1)
        self.assertEqual(prompt.count('A Simple Accent'), 1)
        self.assertIn('Correct lettering only when a text check failed', prompt)

    def test_init_enables_new_profile_without_changing_output_contract(self):
        path = pipeline.init_project(self.base / 'new', 'prompt-fixture', include_a_plus=True,
                                     marketplace='US', language='en-US',
                                     a_plus_canvas=[1800, 900], a_plus_module='fixture-wide')
        manifest = pipeline.read_json(path)
        self.assertEqual(len(manifest['jobs']), 13)
        self.assertEqual(manifest['delivery_profile'], {'name': 'compact_jpg', 'jpeg_quality': 92})
        self.assertEqual(manifest['generation_backend'], 'built_in_image_gen')
        for job in manifest['jobs']:
            self.assertEqual(job['prompt_profile'], PROFILE)
            self.assertTrue(job['final_output'].startswith('final/'))
            self.assertTrue(job['final_output'].endswith('.jpg'))

    def test_repair_plan_binds_actual_prompt_target_and_survives_ingest(self):
        self.manifest = create_v3_fixture(self.base)
        self.job = self.manifest['jobs'][1]
        self.job['prompt_profile'] = PROFILE
        prepare_fixture(self.manifest, self.base)
        simulate_secondary_output(self.manifest, self.base)
        finish_fixture(self.manifest, self.base, delivery=False)
        self.job['semantic_qa_results']['geometry'] = {'verdict': 'fail', 'notes': NOTE}
        report = pipeline.quality_assurance(self.manifest, self.base)
        result = next(item for item in report['jobs'] if item['id'] == SECONDARY_ID)
        self.assertEqual(self.job['status'], 'generation_repair_needed')
        self.assertTrue(result['image_failures'])
        old_target = self.job['raw_output']
        old_bytes = (self.base / old_target).read_bytes()
        # Direct dispatch must not silently bind the original generation prompt.
        with self.assertRaisesRegex(pipeline.PipelineError, 'run plan before dispatch'):
            pipeline.transition_job(self.manifest, SECONDARY_ID, 'generating', NOTE, self.base)
        # A failed review must not itself alter the image generation identity.
        self.assertEqual(self.job['prompt_hash'], pipeline.generation_fingerprint(self.manifest, self.job, self.base))
        repeated = pipeline.quality_assurance(self.manifest, self.base)
        self.assertEqual(next(item for item in repeated['jobs'] if item['id'] == SECONDARY_ID)['status'],
                         'generation_repair_needed')
        pipeline.prepare(self.manifest, self.base, [SECONDARY_ID])
        prompt = (self.base / self.job['prompt_file']).read_text()
        for failure in result['image_failures']:
            self.assertIn(failure, prompt)
        self.assertEqual(self.job['generation_reference_paths'][0], old_target)
        self.assertIn(f'Image 1: {old_target} — edit target', prompt)
        bound = self.job['prompt_hash']
        self.assertEqual(bound, pipeline.generation_fingerprint(self.manifest, self.job, self.base))
        pipeline.transition_job(self.manifest, SECONDARY_ID, 'generating', NOTE, self.base)
        attempt = self.job['active_attempt_id']
        artifact = self.base / 'fixture-repaired.png'
        Image.new('RGB', (1600, 1600), '#dddddd').save(artifact)
        workflow.ingest(self.manifest, self.base, SECONDARY_ID, artifact, attempt)
        self.assertNotEqual(self.job['raw_output'], old_target)
        self.assertEqual((self.base / old_target).read_bytes(), old_bytes)
        self.assertEqual(self.job['prompt_edit']['target_path'], old_target)
        self.assertEqual(bound, pipeline.generation_fingerprint(self.manifest, self.job, self.base))
        self.assertEqual(self.job['quality_repairs'], 1)
        self.assertTrue(workflow.ingest(self.manifest, self.base, SECONDARY_ID, artifact, attempt)['idempotent'])
        (self.base / old_target).write_bytes(b'changed fixture target')
        with self.assertRaisesRegex(pipeline.PipelineError, 'STALE_PROMPT'):
            workflow.ingest(self.manifest, self.base, SECONDARY_ID, artifact, attempt)

    def test_missing_repair_target_is_not_a_dispatchable_prompt(self):
        self.job.update(prompt_profile=PROFILE,
                        prompt_edit={'target_path': 'raw/missing.png', 'failures': ['geometry']})
        self.assertIn('Prompt preparation blocked', self.prompt())
        self.assertEqual(self.job['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
