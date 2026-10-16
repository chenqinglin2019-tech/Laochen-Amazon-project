"""comparison_host: verbatim claim elements, strict model-output contract and recorded comparisons."""
import json
import unittest
from pathlib import Path
from unittest import mock

from common import load_json, sha256_file
import comparison_host as ch
import core_dossier
import specialty_analysis as sa
from test_core_dossier import blockers, dossier_fixture, png

CLAIM = ('In combination: a container having a mouth; a lid on the mouth; and a strap having openings '
         'receiving a handle of the lid.')


def packet_fixture():
    unit = {'unit_id': 'CMP-1', 'candidate_id': 'C1', 'scenario_id': 'product_entry', 'jurisdiction': 'US',
            'right_type': 'patent', 'claims_evidence_ref': 'API-E', 'product_evidence_ref': 'E2',
            'claims_material_event_id': 'M1', 'document_version': 'api-v1', 'publication_number': 'US11111111B2',
            'claims': [{'number': 1, 'text': CLAIM, 'elements': ch.split_elements(1, CLAIM)}]}
    return {'schema': 'IPR-COMPARISON-HOST/1.0', 'product_images': [{'image_id': 'IMG-001', 'attachment': 'a.png'}],
            'units': [unit]}


def answer(packet, results, implementations=(('illustrated_use', '按图示使用'),), **extra):
    unit = packet['units'][0]
    rows = []
    for impl, _ in implementations:
        for claim in unit['claims']:
            rows.append({'implementation_id': impl, 'claim': claim['number'], 'elements': [
                {'element_id': element['element_id'], 'result': results.get((impl, element['element_id']), 'corresponds'),
                 'product_fact': '图示可见对应结构', 'image_ids': [] if results.get((impl, element['element_id'])) == 'unknown'
                 else ['IMG-001'], 'reasoning': '图一可见'} for element in claim['elements']]})
    value = {'unit_id': unit['unit_id'], 'implementations': [{'implementation_id': i, 'description': d}
                                                             for i, d in implementations],
             'comparisons': rows, 'assumptions': ['遮挡部位按已见结构推定一致'], 'lower_if': ['实际不同则降级']}
    value.update(extra)
    return {'units': [value]}


class ElementTests(unittest.TestCase):
    def test_elements_are_verbatim_fragments_at_claim_boundaries(self):
        elements = ch.split_elements(1, CLAIM)
        self.assertEqual([e['element_id'] for e in elements], ['c1-e1', 'c1-e2', 'c1-e3', 'c1-e4'])
        self.assertEqual(elements[3]['quote'], 'a strap having openings receiving a handle of the lid')
        self.assertTrue(all(ch.quote_verified(e['quote'], CLAIM) for e in elements))
        self.assertFalse(ch.quote_verified('a strap having a buckle', CLAIM))


class OutputContractTests(unittest.TestCase):
    def setUp(self):
        self.packet = packet_fixture()

    def test_valid_output_normalizes_quotes_and_images(self):
        decision = ch.decisions_from_output(answer(self.packet, {('illustrated_use', 'c1-e2'): 'unknown'}), self.packet, 'S1')[0]
        element = decision['comparisons'][0]['elements'][1]
        self.assertEqual((element['result'], element['quote']), ('unknown', 'a container having a mouth'))
        self.assertEqual(decision['assumptions'], ['遮挡部位按已见结构推定一致'])

    def test_rejections(self):
        cases = {
            'COMPARISON_ELEMENT_COVERAGE_INVALID': lambda raw: raw['units'][0]['comparisons'][0]['elements'].pop(),
            'COMPARISON_VISIBLE_BASIS_REQUIRED': lambda raw: raw['units'][0]['comparisons'][0]['elements'][0].update(image_ids=[]),
            'COMPARISON_IMAGE_REFERENCE_INVALID': lambda raw: raw['units'][0]['comparisons'][0]['elements'][0].update(image_ids=['IMG-9']),
            'COMPARISON_NUMERIC_SCORE_IS_NOT_A_BASIS': lambda raw: raw['units'][0]['comparisons'][0]['elements'][0].update(reasoning='相似度 90%'),
            'COMPARISON_IMPLEMENTATION_INVALID': lambda raw: raw['units'][0]['implementations'][0].update(implementation_id='Bad Id'),
            'COMPARISON_IMPLEMENTATION_CLAIM_COVERAGE_INVALID': lambda raw: raw['units'][0]['comparisons'].pop(),
            'COMPARISON_ELEMENT_INVALID': lambda raw: raw['units'][0]['comparisons'][0]['elements'][0].update(result='likely'),
            'COMPARISON_OUTPUT_UNIT_COVERAGE_INVALID': lambda raw: raw['units'][0].update(unit_id='OTHER'),
        }
        for code, change in cases.items():
            with self.subTest(code=code):
                raw = answer(self.packet, {})
                change(raw)
                with self.assertRaisesRegex(ValueError, code):
                    ch.decisions_from_output(raw, self.packet, 'S1')

    def test_unknown_element_requires_a_feedback_request_and_screening_is_only_a_suggestion(self):
        decision = ch.decisions_from_output(answer(self.packet, {('illustrated_use', 'c1-e2'): 'unknown'}), self.packet, 'S1')[0]
        with self.assertRaisesRegex(ValueError, 'COMPARISON_FEEDBACK_REQUEST_REQUIRED'):
            ch.transaction_request(decision, 'native-comparison-S1')
        request = ch.transaction_request(decision, 'native-comparison-S1', 'FDB-1')
        close = request['events'][1]
        self.assertEqual(close['gap']['product_feedback_request_id'], 'FDB-1')
        self.assertEqual(close['followup']['outcome'], 'waiting')
        self.assertFalse(ch.screening(decision))
        differs = ch.decisions_from_output(answer(self.packet, {('illustrated_use', 'c1-e2'): 'differs'}), self.packet, 'S1')[0]
        self.assertTrue(ch.screening(differs))


class RecordedComparisonTests(unittest.TestCase):
    def fixture(self):
        fixture = dossier_fixture(self)
        image = fixture.path / 'images' / 'main.png'
        image.parent.mkdir()
        image.write_bytes(png(1))
        fixture.task['images'] = [{'image_id': 'IMG-001', 'role': 'main', 'path': str(image),
                                   'sha256': sha256_file(image), 'bytes': image.stat().st_size}]
        fixture.save()
        core_dossier.run(fixture.path, download=False, today='2026-10-11')
        return fixture

    def test_commit_records_inventory_and_comparisons_through_real_validators(self):
        fixture = self.fixture()
        entries = ch.pending_entries(fixture.path)
        self.assertEqual([e['candidate_id'] for e in entries], ['C1'])
        packet, images = ch.prepare_packet(fixture.path, entries)
        self.assertEqual([row['image_id'] for row in packet['product_images']], ['IMG-001'])
        self.assertEqual(len(images), 1)
        self.assertEqual([c['number'] for c in packet['units'][0]['claims']], [1])      # claim 2 is dependent
        raw = answer(packet, {('as_sold', 'c1-e2'): 'differs', ('as_sold', 'c1-e3'): 'differs'},
                     implementations=(('illustrated_use', '按页面图示绕容器固定'), ('as_sold', '单独销售的条带')))
        outcome = ch.commit(fixture.path, entries, packet, raw, 'S1', None)
        self.assertEqual(outcome, {'recorded': 1, 'rejected': []})
        fixture.refresh()
        rows = sa.events(fixture.task)
        self.assertTrue(all(row['reviewer'] == 'native-comparison-S1' for row in rows if row['kind'] in {'inventory', 'comparison'}))
        projection = sa.claims_projection(fixture.task, entries[0])
        self.assertEqual(sorted((c['implementation_id'], c['conclusion']) for c in projection['claims']),
                         [('as_sold', 'excludes_risk'), ('illustrated_use', 'supports_risk')])
        self.assertEqual(blockers(fixture), [])
        draft = json.loads((fixture.path / ch.OUTPUT_DIR / 'C1.json').read_text(encoding='utf-8'))
        self.assertEqual(draft['lower_if'], ['实际不同则降级'])
        self.assertNotIn('screening_suggestion', draft)
        self.assertEqual(ch.pending_entries(fixture.path), [])

    def test_stub_driver_records_nothing(self):
        fixture = self.fixture()
        before = len(sa.events(load_json(fixture.path / 'task.json')))
        result = ch.stub_run(fixture.path)
        self.assertEqual((result['recorded'], result['candidates'][0]['claims']), (0, [1]))
        self.assertEqual(len(sa.events(load_json(fixture.path / 'task.json'))), before)
        saved = json.loads((fixture.path / ch.OUTPUT_DIR / 'stub' / 'C1.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['would_record']['events'][0]['kind'], 'inventory')

    def test_changed_input_is_not_committed(self):
        fixture = self.fixture()
        entries = ch.pending_entries(fixture.path)
        packet, _ = ch.prepare_packet(fixture.path, entries)
        stale = json.loads(json.dumps(packet))
        stale['units'][0]['claims'][0]['text'] += ' extra'
        with self.assertRaisesRegex(ValueError, 'COMPARISON_INPUT_CHANGED_BEFORE_COMMIT'):
            ch.commit(fixture.path, entries, stale, answer(packet, {}), 'S1', None)


if __name__ == '__main__':
    unittest.main()
