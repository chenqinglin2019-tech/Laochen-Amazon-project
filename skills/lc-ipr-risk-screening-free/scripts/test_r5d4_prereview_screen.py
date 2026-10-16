"""r5d4 pre-review screen (owner decisions F1/F2): before the final review a selected US invention patent is set aside
only by a program legal-status rule (S1: abandoned two years and never granted, or lifetime-expired, every US
relative terminal) or when two blind judgments agree that the product lacks a necessary feature of every independent
claim (S2: the recorded element comparison A and an independent exclusion check B quoting the claims). Any doubt,
failure or disagreement keeps the candidate in the final review."""
import os
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

TODAY = date(2026, 10, 13)
SCOPE = {'candidate_id': 'C1', 'scenario_id': 'S1', 'jurisdiction': 'US', 'right_type': 'patent'}


def record(status='Abandoned', *, stcb='2019-05-01', granted=False, relatives=(), expiry=None, legal_status=None):
    apps = [{'application_number': 'US15/900,001', 'this_app': True, 'legal_status': status}]
    apps += [{'application_number': number, 'this_app': False, 'legal_status': value} for number, value in relatives]
    events = [{'type': 'legal-status', 'current': True, 'title': status, 'date': '2019-05-01'}]
    if expiry:
        events.append({'type': 'legal-status', 'title': 'Anticipated expiration', 'date': expiry})
    if granted:
        events.append({'type': 'granted', 'date': '2018-01-01'})
    legal = [{'code': 'STCB', 'date': stcb, 'title': 'ABANDONMENT'}] if stcb else []
    return {'evidence_id': 'EV-rec', 'payload': {'publication_number': 'US20180201441A1', 'legal_status': legal_status,
            'worldwide_applications': {'2018': apps}, 'events': events, 'legal_events': legal}}


class StatusVerdictTests(unittest.TestCase):
    def verdict(self, *records, candidate=None):
        import prereview_screen as ps
        with mock.patch.object(ps, '_detail_records', return_value=list(records)):
            return ps.status_verdict({}, {'collections': {}}, candidate or {'candidate_id': 'C1', 'jurisdiction': 'US'},
                                     today=TODAY)

    def test_old_abandonment_without_relatives_is_excluded(self):
        result = self.verdict(record())
        self.assertTrue(result['exclude'])
        self.assertEqual(result['abandoned_on'], '2019-05-01')
        self.assertEqual(result['evidence_refs'], ['EV-rec'])
        import prereview_screen as ps
        self.assertIn('从未授权', ps.status_text(result))

    def test_doubt_keeps_the_candidate(self):
        cases = {
            'abandonment_recent': record(stcb='2025-06-01'),
            'granted_event': record(granted=True),
            'no_dated_abandonment': record(stcb=None),
            'status_not_terminal': record('Active'),
            'status_sources_disagree': record(legal_status='Active'),
        }
        for reason, row in cases.items():
            with self.subTest(reason=reason):
                result = self.verdict(row)
                self.assertFalse(result['exclude'])
                self.assertTrue(result['reason'].startswith(reason), result)
        self.assertEqual(self.verdict()['reason'], 'no_exact_record')
        self.assertEqual(self.verdict(record(), candidate={'candidate_id': 'C1', 'jurisdiction': 'EP'})['reason'], 'not_us')

    def test_every_us_relative_must_be_terminal(self):
        alive = self.verdict(record(relatives=[('US16/100,002', 'Active')]))
        self.assertFalse(alive['exclude'])
        self.assertTrue(alive['reason'].startswith('relative_not_terminal'))
        unknown = self.verdict(record(relatives=[('US16/100,002', None)]))
        self.assertFalse(unknown['exclude'])
        done = self.verdict(record(relatives=[('US16/100,002', 'Abandoned'), ('US62/500,000', None)]))
        self.assertTrue(done['exclude'])                          # a provisional is not a relative that can mature
        self.assertEqual(done['relative_statuses'], {'US16100002': 'Abandoned'})

    def test_lifetime_expiry_needs_a_past_date(self):
        self.assertTrue(self.verdict(record('Expired - Lifetime', stcb=None, expiry='2024-02-01'))['exclude'])
        self.assertFalse(self.verdict(record('Expired - Lifetime', stcb=None, expiry='2027-02-01'))['exclude'])
        self.assertFalse(self.verdict(record('Expired - Lifetime', stcb=None))['exclude'])


PACKET = {'product_images': [{'image_id': 'IMG-001'}, {'image_id': 'IMG-002'}],
          'units': [{'unit_id': 'SCR-1', 'independent_claims': [
              {'number': 1, 'text': 'A lid retainer comprising a rigid frame and a spring clip engaging the rim.'},
              {'number': 9, 'text': 'A kit comprising a pot, a lid and a hinged arm locking the lid.'}]},
              {'unit_id': 'SCR-2', 'independent_claims': [{'number': 1, 'text': 'A strap having apertures.'}]}]}


def exclude_row(**override):
    row = {'unit_id': 'SCR-1', 'decision': 'exclude',
           'missing': [{'claim': 1, 'quote': 'a rigid frame and a spring clip', 'image_ids': ['IMG-001'],
                        'product_feature': '产品是一条柔性带，没有刚性框架。'},
                       {'claim': 9, 'quote': 'a hinged arm locking the lid', 'image_ids': ['IMG-002'],
                        'product_feature': '产品没有铰接臂。'}],
           'relationship': '产品是柔性带，与刚性框架结构不同。', 'difference': '产品没有刚性框架和铰接臂。'}
    row.update(override)
    return row


class IndependentCheckOutputTests(unittest.TestCase):
    def parse(self, rows):
        import prereview_screen as ps
        return ps.decisions_from_output({'decisions': rows}, PACKET, 's1')

    def test_a_checked_exclusion_and_a_keep(self):
        result = self.parse([exclude_row(), {'unit_id': 'SCR-2', 'decision': 'keep'}])
        self.assertEqual([row['decision'] for row in result], ['exclude', 'keep'])
        self.assertEqual({item['claim'] for item in result[0]['missing']}, {1, 9})

    def test_the_whole_output_is_refused_on_any_defect(self):
        keep = {'unit_id': 'SCR-2', 'decision': 'keep'}
        bad_quote = exclude_row()
        bad_quote['missing'][0]['quote'] = 'a rigid frame with two springs'
        one_claim = exclude_row()
        one_claim['missing'] = one_claim['missing'][:1]
        bad_image = exclude_row()
        bad_image['missing'][1]['image_ids'] = ['IMG-404']
        short = exclude_row()
        short['missing'][0]['quote'] = 'frame'
        scored = exclude_row(relationship='相似度 20%，结构不同。')
        cases = {'PREREVIEW_QUOTE_NOT_IN_CLAIM': [bad_quote, keep],
                 'PREREVIEW_EVERY_INDEPENDENT_CLAIM_REQUIRED': [one_claim, keep],
                 'PREREVIEW_MISSING_FEATURE_INVALID': [bad_image, keep],
                 'PREREVIEW_MISSING_FEATURE_INVALID ': [short, keep],
                 'PREREVIEW_NUMERIC_SCORE_IS_NOT_A_BASIS': [scored, keep],
                 'PREREVIEW_OUTPUT_UNIT_COVERAGE_INVALID': [exclude_row()],
                 'PREREVIEW_DECISION_INVALID': [exclude_row(decision='maybe'), keep],
                 'PREREVIEW_CONCRETE_COMPARISON_REQUIRED': [exclude_row(difference=' '), keep]}
        for code, rows in cases.items():
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code.strip()):
                self.parse(rows)

    def test_prompt_defaults_to_keep(self):
        import prereview_screen as ps
        packet = {**PACKET, 'schema': 'IPR-PREREVIEW-SCREEN/1.0', 'product': {}, 'objects': [],
                  'product_images': [{'image_id': 'IMG-001', 'attachment': 'IMG-001.jpg'}],
                  'units': [{**unit, 'publication_number': 'US1', 'title': 't'} for unit in PACKET['units']]}
        text = ps.prompt(packet)
        self.assertIn('keep：默认选项', text)
        self.assertIn('只是缺少配套物品', text)


def inventory_events(results, *, quote='a rigid frame and a spring clip', claims=(1,)):
    head = {**SCOPE, 'intake_event_id': 'INT'}
    rows = [{**SCOPE, 'kind': 'intake', 'event_id': 'INT'},
            {**head, 'kind': 'inventory', 'event_id': 'INV', 'reviewer': 'native-comparison-x',
             'material_event_ids': ['MAT'], 'document_version': 'v1',
             'units': [{'unit_id': 'U-claim%d' % n, 'kind': 'independent_claim', 'implementation_id': 'illustrated',
                        'necessary_elements': ['E1', 'E2']} for n in claims]}]
    for n in claims:
        rows.append({**head, 'kind': 'comparison', 'inventory_event_id': 'INV', 'unit_id': 'U-claim%d' % n,
                     'disposition': 'compared',
                     'elements': [{'element_id': 'E1', 'result': results[0], 'claim_quote': quote},
                                  {'element_id': 'E2', 'result': results[1], 'claim_quote': 'spring clip engaging'}]})
    return rows


class ComparisonVerdictTests(unittest.TestCase):
    TEXTS = {1: PACKET['units'][0]['independent_claims'][0]['text']}

    def verdict(self, rows, texts=None):
        import prereview_screen as ps
        import specialty_analysis as sa
        with mock.patch.object(sa, 'events', return_value=rows):
            return ps.comparison_verdict({}, SCOPE, {'event_id': 'MAT', 'document_version': 'v1'}, texts or self.TEXTS)

    def test_a_quoted_differing_element_in_every_claim_agrees(self):
        result = self.verdict(inventory_events(['differs', 'corresponds']))
        self.assertTrue(result['exclude'])
        self.assertEqual(result['inventory_event_id'], 'INV')

    def test_otherwise_judgment_a_does_not_agree(self):
        self.assertFalse(self.verdict(inventory_events(['corresponds', 'unknown']))['exclude'])
        self.assertFalse(self.verdict(inventory_events(['differs', 'unknown'], quote='a wooden frame'))['exclude'])
        two = {**self.TEXTS, 9: PACKET['units'][0]['independent_claims'][1]['text']}
        self.assertEqual(self.verdict(inventory_events(['differs', 'unknown']), two)['reason'], 'claim_set_mismatch')
        self.assertIsNone(self.verdict(inventory_events(['differs', 'unknown'])[:1]))
        rows = inventory_events(['differs', 'unknown'])
        rows[-1]['disposition'] = 'not_compared'
        self.assertTrue(self.verdict(rows)['reason'].startswith('unit_not_compared'))


class PacketTests(unittest.TestCase):
    def test_screened_candidates_and_event_stubs(self):
        import prereview_screen as ps
        ledger = {'annotations': [
            {**SCOPE, 'decision': 'selected', 'reviewer': 'native-text-1'},
            {**SCOPE, 'decision': 'not_selected', 'reviewer': 'program:prereview-status'},
            {**SCOPE, 'candidate_id': 'C2', 'decision': 'not_selected', 'reviewer': 'native-text-1'},
            {**SCOPE, 'candidate_id': 'C3', 'decision': 'not_selected', 'reviewer': 'native-screen-abc'},
            {**SCOPE, 'candidate_id': 'C3', 'decision': 'selected', 'reviewer': 'native-text-2'}]}
        self.assertEqual(ps.screened_candidate_ids(ledger), {'C1'})
        task = {'specialty_analysis_events': [{'event_id': 'E1', 'candidate_id': 'C1', 'kind': 'inventory',
                                               'units': ['long']}, {'event_id': 'E2', 'candidate_id': 'C5'}]}
        self.assertEqual(ps.stub_specialty_events(task, {'C1'}), 1)
        stub, kept = task['specialty_analysis_events']
        self.assertNotIn('units', stub)
        self.assertIn('review_packet_stub', stub)
        self.assertEqual(kept, {'event_id': 'E2', 'candidate_id': 'C5'})
        self.assertTrue(ps.screened_reviewer('program:prereview-status'))
        self.assertTrue(ps.screened_reviewer('native-screen-abc'))
        self.assertFalse(ps.screened_reviewer('native-text-1'))

    def test_records_of_status_screened_candidates_are_read(self):
        # r5d4 rehearsal: three applications set aside before their dossier left their records "pending processing"
        import json
        import tempfile
        from pathlib import Path
        import prereview_screen as ps
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'materiality-annotations.json').write_text(json.dumps({'annotations': [
                {**SCOPE, 'decision': 'selected', 'reviewer': 'native-text-1'},
                {**SCOPE, 'decision': 'not_selected', 'reviewer': ps.STATUS_REVIEWER},
                {**SCOPE, 'candidate_id': 'C2', 'decision': 'not_selected', 'reviewer': 'native-screen-x'},
                {**SCOPE, 'candidate_id': 'C3', 'decision': 'selected', 'reviewer': 'native-text-1'}]}), encoding='utf-8')
            (root / 'evidence.json').write_text(json.dumps({'source_runs': [], 'record_content_reviews': []}), encoding='utf-8')
            index = {cid: ('patents', {'candidate_id': cid}) for cid in ('C1', 'C2', 'C3')}
            records = {'C1': [{'source_run_id': 'R-old'}, {'source_run_id': 'R1'}], 'C2': [{'source_run_id': 'R2'}],
                       'C3': [{'source_run_id': 'R3'}]}
            with mock.patch.object(ps, '_detail_records', side_effect=lambda task, evidence, c: records[c['candidate_id']]):
                self.assertEqual(ps._status_screened_runs(root, {}, index), ['R1'])
            (root / 'evidence.json').write_text(json.dumps({'source_runs': [],
                'record_content_reviews': [{'source_run_id': 'R1'}]}), encoding='utf-8')
            self.assertEqual(ps.read_status_records(root, ['R1', 'R1', None]), ([], []))     # already read: nothing to do
            done, failed = ps.read_status_records(root, ['R9'])
            self.assertEqual((done, failed[0]['run_id']), ([], 'R9'))                        # unknown run: reported, not raised

    def test_only_new_tasks_are_screened(self):
        import prereview_screen as ps
        self.assertTrue(ps.enabled({'prereview_screen_revision': ps.REVISION}))
        self.assertFalse(ps.enabled({}))


if __name__ == '__main__':
    unittest.main()
