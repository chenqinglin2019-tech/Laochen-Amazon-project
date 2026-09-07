"""Template/pipeline integration tests; synthetic fixtures, never real QA."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_design_templates as lib
from lc_reference_design import prepare_design_briefs
from lc_template_workflow import validate_template_inputs
from lc_design import design_reference_issue, design_generation_payload
from test_lc_design_templates import fixture


class TemplateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.catalog = fixture()
        self.path = self.base / 'templates.json'
        self.path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.job = {'id': 'scene', 'kind': 'listing', 'canvas': [2000, 2000],
                    'text_mode': 'local_overlay', 'selling_job': 'Lifestyle scene',
                    'scene': 'a wood shelf', 'layout': {'version': 3, 'text_groups': [
                        {'id': 'title', 'headline': 'Exact approved copy', 'body': 'Keep every approved word.'}]}}
        self.m = {'design_template_policy': {'version': 1, 'mode': 'auto'},
                  'design_template_library_path': str(self.path),
                  'design_template_user_library_path': str(self.base / 'empty-user.json'),
                  'product_truth': {'product': 'Wood shelf decor'}, 'category': 'home_decor',
                  'jobs': [self.job]}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, selected=None):
        return prepare_design_briefs(self.m, self.base, selected or [j['id'] for j in self.m['jobs']])

    def test_new_route_never_reads_legacy_sources_and_keeps_copy(self):
        original = copy.deepcopy(self.job['layout'])
        with patch('lc_reference_design._prepare_external_design_briefs', side_effect=AssertionError('legacy source read')):
            self.assertEqual(self.prepare()['changed'], ['scene'])
        self.assertEqual(original, self.job['layout'])
        self.assertIsNone(design_reference_issue(self.job))
        self.assertEqual(self.job['design_resolution']['source'], 'template_library')

    def test_adopted_snapshot_replays_without_any_files(self):
        self.prepare()
        before = copy.deepcopy(self.m)
        with patch.object(Path, 'open', side_effect=AssertionError('file access during pinned replay')):
            self.assertEqual(self.prepare()['cached'], ['scene'])
            self.assertIsNone(design_reference_issue(self.job))
        self.assertEqual(before, self.m)

    def test_library_revision_and_unrelated_additions_do_not_reselect(self):
        self.prepare()
        before = copy.deepcopy(self.m)
        changed = copy.deepcopy(self.catalog['templates'][0])
        changed['revision'] = 2
        changed['generation']['lighting'] = 'New dramatic backlight.'
        self.catalog['templates'].append(changed)
        self.path.write_text(json.dumps(self.catalog))
        self.prepare()
        self.assertEqual(before, self.m)
        self.job.update(design_template_id=changed['id'], design_template_revision=2)
        self.prepare()
        self.assertEqual(self.job['design_resolution']['binding']['template']['revision'], 2)

    def test_layout_override_does_not_change_generation(self):
        self.prepare()
        old_generation = design_generation_payload(self.job)
        self.job['design_overrides'] = {'layout': {'headline_weight': 600, 'text_color': '#FFFFFF'}}
        self.prepare()
        self.assertEqual(old_generation, design_generation_payload(self.job))
        self.assertEqual(self.job['design_brief']['layout']['headline_weight'], 600)

    def test_generation_override_changes_only_chosen_image(self):
        sibling = copy.deepcopy(self.job); sibling['id'] = 'second'
        self.m['jobs'].append(sibling)
        self.prepare()
        before = copy.deepcopy(sibling)
        self.job['design_overrides'] = {'generation': {'lighting': 'Stronger side light.'}}
        self.prepare(['scene'])
        self.assertEqual(before, sibling)
        self.assertEqual(self.job['design_brief']['generation']['lighting'], 'Stronger side light.')

    def test_explicit_geometry_is_shared_with_model_and_dispatch_lock_wins(self):
        from lc_image_pipeline import generation_geometry
        product, text = [.55, .3, .35, .6], [.06, .1, .4, .15]
        self.job['design_overrides'] = {'layout': {'product_region_norm': product, 'text_group_box': text}}
        self.prepare()
        composition = self.job['design_brief']['generation']['canvas_composition']
        self.assertEqual(composition['product_region_norm'], product)
        self.assertEqual(composition['text_region_norm'], text)
        self.job['generation_geometry_lock'] = generation_geometry(self.job)
        before = copy.deepcopy(self.job['design_brief']['generation'])
        self.job['layout']['text_groups'][0]['box'] = [.08, .12, .35, .18]
        self.prepare()
        self.assertEqual(before, self.job['design_brief']['generation'])
        self.job['generation_geometry_lock']['text_regions_norm'] = [[.08, .12, .35, .18]]
        self.prepare()
        self.assertNotEqual(before, self.job['design_brief']['generation'])

    def test_authored_layout_geometry_precedes_template_and_brief_override(self):
        self.job['layout']['product_region_norm'] = [.6, .3, .3, .6]
        self.job['layout']['text_groups'][0]['box'] = [.06, .12, .4, .3]
        self.prepare()
        composition = self.job['design_brief']['generation']['canvas_composition']
        self.assertEqual(composition['product_region_norm'], [.6, .3, .3, .6])
        self.assertEqual(composition['text_region_norm'], [.06, .12, .4, .3])

    def test_corrupted_snapshot_is_not_rebound_as_valid(self):
        self.prepare()
        self.job['design_resolution']['binding']['template']['snapshot']['name'] = 'Tampered'
        self.assertIsNotNone(design_reference_issue(self.job))
        self.assertEqual(self.prepare()['needs_input'], ['scene'])
        self.assertIsNotNone(design_reference_issue(self.job))

    def test_changed_brief_needs_prepare_but_override_is_authoritative(self):
        self.prepare()
        self.job['design_brief']['generation']['lighting'] = 'Hand edited derived value'
        self.assertIsNotNone(design_reference_issue(self.job))
        self.prepare()
        self.assertIsNone(design_reference_issue(self.job))
        self.assertNotEqual(self.job['design_brief']['generation']['lighting'], 'Hand edited derived value')

    def test_no_fit_is_resolved_by_explicit_project_only_original(self):
        self.m['category'] = 'unknown-specialty'
        self.m['product_truth']['product'] = 'Unknown specialty object'
        self.assertEqual(self.prepare()['needs_input'], ['scene'])
        self.job['design_brief'] = {'version': 1, 'generation': {'composition': 'Original neutral arrangement'}, 'layout': {}}
        self.job['design_template_original_reason'] = 'No suitable library design for this specialty product.'
        self.prepare()
        self.assertEqual(self.job['design_resolution']['source'], 'original_design')
        self.assertFalse(self.job['design_resolution']['matched'])
        self.assertIsNone(design_reference_issue(self.job))
        self.assertFalse((self.base / 'empty-user.json').exists())

    def test_original_image_can_keep_the_explicit_project_family(self):
        self.m['design_template_set_id'] = 'warm-editorial'
        self.job['design_brief'] = {'version': 1, 'generation': {'composition': 'Original warm arrangement'}, 'layout': {}}
        self.job['design_template_original_reason'] = 'No suitable dimension module in this family.'
        self.prepare()
        self.assertEqual(self.m['design_template_set_id'], 'warm-editorial')
        self.assertEqual(self.job['design_resolution']['source'], 'original_design')

    def test_main_bypasses_marketing_templates(self):
        self.job.update(kind='main', text_mode='none')
        with patch('lc_design_templates.load_library', side_effect=AssertionError('main reads template')):
            self.assertEqual(self.prepare(), {'changed': [], 'cached': [], 'needs_input': []})
        self.assertNotIn('design_brief', self.job)

    def test_unknown_explicit_template_is_required_not_generic_fallback(self):
        self.job['design_template_id'] = 'missing-template'
        self.assertEqual(self.prepare()['needs_input'], ['scene'])
        self.assertTrue(self.job['design_resolution']['required'])

    def test_current_external_reference_keeps_original_routing(self):
        self.job['design_reference_id'] = 'external-current'
        expected = {'changed': [], 'cached': [], 'needs_input': ['scene']}
        with patch('lc_reference_design._prepare_external_design_briefs', return_value=expected) as legacy:
            self.assertEqual(self.prepare(), expected)
            legacy.assert_called_once()

    def test_single_image_override_does_not_seed_unrelated_project_family(self):
        self.m.pop('design_template_library_path')
        self.job['design_template_id'] = 'beauty-close-use'
        sibling = copy.deepcopy(self.job); sibling['id'] = 'second'; sibling.pop('design_template_id')
        self.m['jobs'].append(sibling)
        self.prepare(['scene'])
        self.assertNotIn('design_template_selection', self.m)
        self.prepare(['second'])
        self.assertNotEqual(sibling['design_resolution']['binding']['family']['id'], 'soft-beauty')
        self.assertEqual(self.job['design_resolution']['binding']['family']['id'], 'soft-beauty')

    def test_native_route_retains_separate_approved_copy(self):
        self.job.update(text_mode='model_native', copy={'headline': 'Quiet Moments'}, layout={})
        self.prepare()
        self.assertEqual(self.job['copy'], {'headline': 'Quiet Moments'})
        self.assertNotIn('Quiet Moments', json.dumps(self.job['design_brief']))
        self.assertIsNone(design_reference_issue(self.job))

    def test_new_init_opts_in_without_pin_and_legacy_manifest_stays_out(self):
        import lc_image_pipeline as pipeline
        path = pipeline.init_project(self.base / 'new-project', 'new-project', marketplace='US', language='en')
        manifest = pipeline.read_json(path)
        self.assertEqual(manifest['design_template_policy'], {'version': 1, 'mode': 'auto'})
        self.assertTrue(all('recipe' not in j.get('layout', {}) for j in manifest['jobs']))
        errors = pipeline.validate_manifest(manifest, self.base / 'new-project', check_files=False)
        self.assertFalse(any('layout.recipe' in error for error in errors), errors)
        self.m.pop('design_template_policy')
        with patch('lc_reference_design._prepare_external_design_briefs', return_value={'changed': [], 'cached': [], 'needs_input': []}) as legacy:
            self.prepare()
            legacy.assert_called_once()

    def test_malformed_controls_fail_validation(self):
        for policy in (None, [], {'version': True, 'mode': 'auto'}, {'version': 1, 'mode': 'unknown'}):
            with self.subTest(policy=policy):
                self.assertTrue(validate_template_inputs({'design_template_policy': policy}))
        self.job.update(design_template_id='some-template', design_reference_id='other')
        self.assertTrue(validate_template_inputs(self.m))

    def test_full_pipeline_prepare_uses_template_without_legacy_style_io(self):
        import lc_image_pipeline as pipeline
        from pipeline_test_support import create_v3_fixture
        manifest = create_v3_fixture(self.base / 'synthetic-project')
        manifest.update(design_template_policy={'version': 1, 'mode': 'auto'}, category='home_decor',
                        design_template_library_path=str(self.path),
                        design_template_user_library_path=str(self.base / 'empty-user.json'))
        job = manifest['jobs'][1]
        job.update(text_mode='local_overlay', selling_job='Lifestyle scene',
                   layout={'version': 3, 'text_groups': [{'id': 'title', 'headline': 'Design'}]})
        with patch('lc_reference_design._prepare_external_design_briefs', side_effect=AssertionError('legacy style IO')):
            pipeline.prepare(manifest, self.base / 'synthetic-project')
        self.assertEqual(job['design_resolution']['status'], 'selected')
        self.assertEqual(job['target_product_bbox_norm'], pipeline.generation_geometry(job)['product_region_norm'])
        self.assertEqual(job['attempts'], 0)

    def test_all_builtin_canvas_geometries_match_compiled_reservations(self):
        from lc_layout import layout_geometry
        catalog = lib.load_library()
        for template in catalog['templates']:
            family = lib.get_family(catalog, template['family_id'])
            for canvas in ([2000, 2000], [2000, 2600], [1464, 600]):
                with self.subTest(template=template['id'], canvas=canvas):
                    job = copy.deepcopy(self.job); job['canvas'] = canvas
                    job['design_brief'] = lib.compile_template(family, template,
                        {'product': 'Known test product'}, job)['brief']
                    geometry = layout_geometry(job)
                    expected = job['design_brief']['generation']['canvas_composition']
                    self.assertEqual(geometry['product_region_norm'], expected['product_region_norm'])
                    self.assertEqual(geometry['text_regions_norm'][0], expected['text_region_norm'])
                    product, text = geometry['product_region_norm'], geometry['text_regions_norm'][0]
                    overlap = max(0, min(product[0]+product[2], text[0]+text[2])-max(product[0], text[0])) * max(
                        0, min(product[1]+product[3], text[1]+text[3])-max(product[1], text[1]))
                    self.assertEqual(overlap, 0)

    @unittest.skipUnless(os.environ.get('LC_LAYOUT_BROWSER_TEST') == '1', 'opt-in Chromium regression')
    def test_real_template_rendering_and_long_copy_gate(self):
        from PIL import Image, ImageDraw
        import lc_layout as renderer
        catalog, jobs = lib.load_library(), []
        for template in catalog['templates']:
            identifier = template['id']
            family = lib.get_family(catalog, template['family_id'])
            for index, canvas in enumerate(([1000, 1000], [1000, 1300], [1464, 600])):
                job = {'id': f'{identifier}-{index}', 'kind': 'listing', 'canvas': canvas,
                       'text_mode': 'local_overlay', 'selling_job': 'Design details',
                       # Some source-derived title bands intentionally hold a
                       # heading only; body copy belongs in another planned
                       # group. Smoke-test their documented minimal slot.
                       'layout': {'version': 3, 'text_groups': [{'id': 'copy', 'headline': 'Design'}]}}
                job['design_brief'] = lib.compile_template(family, template, {'product': 'Synthetic test block'}, job)['brief']
                geom = renderer.layout_geometry(job)
                job['output_product_bbox_norm'] = geom['product_region_norm']
                ink = job['design_brief']['layout']['text_color']
                background = '#171717' if int(ink[1:3], 16) > 128 else '#F8F8F8'
                pixels = Image.new('RGB', canvas, background)
                x, y, width, height = geom['product_region_norm']
                ImageDraw.Draw(pixels).rectangle((round(x*canvas[0]), round(y*canvas[1]),
                    round((x+width)*canvas[0]), round((y+height)*canvas[1])), fill='#9BA3A5')
                job['layout_input'] = f"{job['id']}.png"
                pixels.save(self.base / job['layout_input'])
                jobs.append(job)
        long = copy.deepcopy(jobs[0]); long['id'] = 'long-copy'
        long['layout']['text_groups'][0]['body'] = 'Keep all of these approved words. ' * 12
        long['layout']['text_groups'][0]['box'] = [.02, .02, .1, .04]
        jobs.append(long)
        before = [copy.deepcopy(j['layout']) for j in jobs]
        results = renderer.render_batch({'test_fixture': True, 'language': 'en'}, self.base, jobs)
        failures = {job['id']: [c for c in results[job['id']]['checks'] if not c['passed']]
                    for job in jobs[:-1] if not results[job['id']]['passed']}
        self.assertEqual(failures, {})
        self.assertFalse(results['long-copy']['passed'])
        self.assertEqual(before, [j['layout'] for j in jobs])


if __name__ == '__main__':
    unittest.main()
