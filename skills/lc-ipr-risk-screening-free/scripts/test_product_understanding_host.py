"""Product understanding drafts: recorder-valid scope/analysis from captured facts, model refinement with fallback."""
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
import sys
import unittest

from common import atomic_write_json, load_json
import test_product_delivery as delivery_fixture


class ProductUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.f = delivery_fixture.ProductDeliveryTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.run = self.f.run
        task = load_json(self.run / 'task.json')
        task['product'].update(title='Folding Stand with a hinged support arm for phones', brand='Acme',
                               bullets=['PATENTED folding stand, US 11,401,089 B2, keeps phones upright.'])
        atomic_write_json(self.run / 'task.json', task)
        self.out = self.f.f.root / 'checkpoints'

    def record_drafts(self):
        from record_product_scope import record as record_scope
        import record_product_analysis
        record_scope(self.run, self.out / '1-scope.json')
        with patch.object(sys, 'argv', ['record_product_analysis.py', '--task-dir', str(self.run),
                                        '--input', str(self.out / '1-analysis.json')]), redirect_stdout(StringIO()):
            record_product_analysis.main()
        return load_json(self.run / 'task.json')

    def test_program_drafts_record_through_the_ordinary_recorders(self):
        import product_understanding_host as host
        summary = host.run(self.run, self.out)
        self.assertEqual(summary['driver'], 'program')
        self.assertIn('enforcement', summary['right_types'])
        self.assertTrue(summary['marked'])
        self.assertIn('US11401089B2', summary['patent_numbers'])
        task = self.record_drafts()
        rights = {d['right_type'] for d in task['product_scope']['directions']}
        self.assertIn('enforcement', rights)
        states = {o['object_id']: o['scope_status'] for o in task['product_scope']['objects']}
        self.assertEqual(states, {'PRODUCT': 'included', 'REF-BRAND': 'default_excluded', 'REF-PHOTO': 'default_excluded'})
        self.assertEqual(task['product']['analysis']['status'], 'confirmed')
        # user materials entry: the claims are user statements, never page claims
        natures = {f['fact_id']: f['nature'] for f in task['product_scope']['facts']}
        self.assertEqual(natures['F-TITLE'], 'user_statement')

    def test_valid_model_refinement_is_merged(self):
        import product_understanding_host as host
        raw = {'product_description': '可折叠手机支架，铰接支撑臂', 'structure': ['铰接支撑臂与底座'],
               'query_terms': [{'value': 'hinged phone stand', 'kind': 'structural_feature', 'derived_from': 'product.title'}],
               'patent_numbers': []}
        summary = host.run(self.run, self.out, native=lambda task: raw)
        self.assertEqual((summary['driver'], summary['fallback_reason']), ('native', None))
        scope = load_json(self.out / '1-scope.json')
        self.assertEqual(scope['scope']['objects'][0]['description'], '可折叠手机支架，铰接支撑臂')
        analysis = load_json(self.out / '1-analysis.json')
        self.assertIn('hinged phone stand', [t['value'] for t in analysis['query_terms']])
        self.record_drafts()

    def test_invalid_model_output_falls_back_to_the_program_draft(self):
        import product_understanding_host as host
        raw = {'query_terms': [{'value': '中文词', 'kind': 'function', 'derived_from': 'product.title'}]}
        summary = host.run(self.run, self.out, native=lambda task: raw)
        self.assertEqual(summary['driver'], 'program')
        self.assertIn('TERM_INVALID', summary['fallback_reason'])
        self.record_drafts()

    def test_listing_numbers_never_leave_a_dangling_hyphen(self):
        # B0GLNPC6K8 real run: '2-in-1' became 'in-' and the draft failed 'Invalid or empty Boolean query'.
        import product_understanding_host as host
        task = load_json(self.run / 'task.json')
        task['product'].update(
            title="Yaruiguang Automatic Butterfly Cat Toy, Interactive Wand with Suction Base | Rechargeable 2-in-1 wand",
            bullets=['2-in-1 Dual Design Interactive & Self-Play Effortlessly Switchable: '
                     'This Mode Simple Freely 2-in-1 interactive cat toy',
                     'Smart Dual Rotation Modes 3-Minute Auto Sleep for Power Saving: This automatic butterfly cat teaser',
                     "360 Bionic Flying Unleashes Your Cat's Hunting Instincts: The built-in motor drives a 55cm Kids'"])
        atomic_write_json(self.run / 'task.json', task)
        self.assertEqual(host.structural_phrase(task['product']['bullets'][0]), 'this mode simple freely interactive')
        self.assertEqual(host.structural_phrase('Fun for Kids: soft plush toy for kids\''), 'soft plush toy')
        self.assertEqual(host._english_words('Anti- Slip Mat', 3), 'Anti Slip Mat')
        for value in ('in-', "kids'", 'pet toy.', 'a & b', ''):
            self.assertFalse(host.boolean_term_ok(value), value)
        host.run(self.run, self.out)
        analysis = load_json(self.out / '1-analysis.json')
        self.assertTrue(all(host.boolean_term_ok(t['value']) for t in analysis['query_terms'] if t['kind'] != 'brand'))
        self.assertIn('structural_feature', {t['kind'] for t in analysis['query_terms']})
        self.record_drafts()

    def test_one_unplannable_model_term_is_dropped_not_the_refinement(self):
        import product_understanding_host as host
        raw = {'product_description': '可折叠手机支架', 'query_terms': [
            {'value': 'phone stand & holder', 'kind': 'design', 'derived_from': 'product.title'},
            {'value': 'hinged phone stand', 'kind': 'structural_feature', 'derived_from': 'product.title'}]}
        summary = host.run(self.run, self.out, native=lambda task: raw)
        self.assertEqual((summary['driver'], summary['fallback_reason']), ('native', None))
        values = [t['value'] for t in load_json(self.out / '1-analysis.json')['query_terms']]
        self.assertIn('hinged phone stand', values)
        self.assertNotIn('phone stand & holder', values)
        self.record_drafts()

    def test_marking_clues(self):
        import product_understanding_host as host
        clues = host.marking_clues({'product': {'title': 'Lid Latch strap', 'bullets': ['PATENTED UNIVERSAL FIT LID LATCH'],
                                                'visible_ip_claims': []}})
        self.assertTrue(clues['marked'])
        self.assertEqual(clues['numbers'], [])
        self.assertFalse(host.marking_clues({'product': {'title': 'Plain strap'}})['marked'])


if __name__ == '__main__':
    unittest.main()
