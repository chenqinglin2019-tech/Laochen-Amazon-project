"""r10 (eu-scope-v1, owner decisions 2026-11-17): the German marketplace runs of 2026-11-12 and 2026-11-17.

EP publications belong to the EU scope, European documents get the deep-check rules, a selected candidate left
unplaced is disclosed instead of refusing the report, the review packet is kept within the host limit and German
listing text is not used as an English search term. Offline only."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import eu_scope
import review_budget

EU = {eu_scope.TASK_FIELD: eu_scope.REVISION}


def task(targets, marked=True):
    return {**(EU if marked else {}), 'target_jurisdictions': list(targets)}


class ScopeOriginTests(unittest.TestCase):
    def test_ep_belongs_to_the_eu_scope_of_a_marked_task(self):
        self.assertEqual(eu_scope.scope_origin(task(['EU', 'DE']), {'jurisdiction': 'EP'}), 'EU')
        self.assertEqual(eu_scope.scope_origin(task(['EU', 'DE']), {'office': 'ep'}), 'EU')
        self.assertEqual(eu_scope.scope_origin(task(['EU', 'DE']), {'jurisdiction': 'DE'}), 'DE')
        self.assertEqual(eu_scope.scope_origin(task(['EU', 'DE']), {'jurisdiction': 'WO'}), 'WO')

    def test_a_single_epc_country_without_eu_takes_the_ep_publication(self):
        self.assertEqual(eu_scope.scope_origin(task(['GB']), None, 'EP'), 'GB')
        self.assertEqual(eu_scope.scope_origin(task(['FR', 'DE']), None, 'EP'), 'EP')    # ambiguous: unchanged

    def test_us_and_old_tasks_are_unchanged(self):
        self.assertEqual(eu_scope.scope_origin(task(['US']), {'jurisdiction': 'EP'}), 'EP')
        self.assertEqual(eu_scope.scope_origin(task(['EU', 'DE'], marked=False), {'jurisdiction': 'EP'}), 'EP')

    def test_new_tasks_carry_the_marker(self):
        text = (Path(__file__).resolve().parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn('task[EU_SCOPE_FIELD] = EU_SCOPE_REVISION', text)


class TriageScopeTests(unittest.TestCase):
    """Rehearsal of the 11-17 run: targets EU + DE, a selected EP publication."""

    def setUp(self):
        import test_triage_scope
        self.case = test_triage_scope.TriageScopeTests()
        self.case.setUp()
        self.case.task['target_jurisdictions'] = ['EU', 'DE']
        self.case.candidate.update(jurisdiction='EP', publication_number='EP1234567B1')

    def records(self):
        import decision_workflow as workflow
        summary = workflow.triage_summary(self.case.task, self.case.candidates, self.case.ledger,
                                          evidence=self.case.evidence)
        return sorted({record['jurisdiction'] for record in summary['records']})

    def test_old_tasks_keep_the_unlocated_scope(self):
        self.assertEqual(self.records(), ['UNLOCATED'])

    def test_marked_tasks_triage_the_ep_publication_in_the_eu_scope(self):
        self.case.task.update(EU)
        self.assertEqual(self.records(), ['EU'])
        annotation = self.case.annotation()          # no identity gap: EP is the EU scope's own office
        self.assertEqual(annotation['jurisdiction'], 'EU')
        self.case.ledger['annotations'].append(annotation)
        self.assertEqual(self.records(), ['EU'])

    def test_the_handoff_requires_the_eu_scope(self):
        import candidate_handoff
        self.case.task.update(EU)
        self.case.task['assessment_scenarios'] = self.case.task.get('assessment_scenarios') or []
        scopes = candidate_handoff._required_scopes(self.case.task, self.case.candidate)
        self.assertTrue(scopes)
        self.assertEqual({country for _, country in scopes}, {'EU'})

    def test_the_mechanical_handoff_finds_the_scope_applicable(self):
        import mechanical_ledger
        self.case.task.update(EU)
        sid = self.case.task['assessment_scenarios'][0]['scenario_id']
        view = {'rows': [{'candidate_id': self.case.candidate['candidate_id'], 'handoff_state': 'ready',
                          'remaining_scopes': [{'scenario_id': sid, 'jurisdiction': 'EU'}],
                          'ready_sources': [{'evidence_id': 'E1'}]}]}
        candidates = {'patents': [self.case.candidate]}
        _, reviews = mechanical_ledger.plan_handoff(self.case.task, view, candidates)
        self.assertEqual([row['applicability'] for row in reviews if row['jurisdiction'] == 'EU'], ['applicable'])


class ComparisonFeedbackTests(unittest.TestCase):
    """11-17: the comparison host's structure requests were refused 15 times and nothing was recorded."""

    def setUp(self):
        import test_product_feedback
        self.case = test_product_feedback.ProductFeedbackTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        from common import atomic_write_json, load_json
        self.load, self.write = load_json, atomic_write_json

    def prepare(self, office, marked=True):
        run = self.case.run
        task = self.load(run / 'task.json')
        task['target_jurisdictions'] = ['EU', 'DE']
        if marked:
            task.update(EU)
        else:
            task.pop(eu_scope.TASK_FIELD, None)      # the fixture task is created by the current create_task
        from product_delivery import project
        task['product_delivery'] = project(task)
        self.write(run / 'task.json', task)
        candidates = self.load(run / 'normalized-candidates.json')
        candidates['patents'][0]['jurisdiction'] = office
        self.write(run / 'normalized-candidates.json', candidates)

    def test_an_ep_candidate_is_recorded_in_the_eu_scope(self):
        self.prepare('EP')
        self.case.request['jurisdiction'] = 'EU'
        self.assertEqual(self.case.save_request(), 'success')

    def test_an_unplaced_candidate_is_recorded_in_the_unlocated_scope(self):
        self.prepare('WO')
        self.case.request['jurisdiction'] = 'UNLOCATED'
        self.assertEqual(self.case.save_request(), 'success')

    def test_an_ep_candidate_cannot_claim_the_unlocated_scope(self):
        self.prepare('EP')
        self.case.request['jurisdiction'] = 'UNLOCATED'
        with self.assertRaisesRegex(ValueError, 'CANDIDATE_MISMATCH'):
            self.case.save_request()

    def test_old_tasks_keep_the_old_contract(self):
        self.prepare('EP', marked=False)
        self.case.request['jurisdiction'] = 'EU'
        with self.assertRaisesRegex(ValueError, 'CANDIDATE_MISMATCH'):
            self.case.save_request()
        self.case.request['jurisdiction'] = 'UNLOCATED'
        with self.assertRaisesRegex(ValueError, 'REQUEST_INVALID'):
            self.case.save_request()


class PublicationGateTests(unittest.TestCase):
    def test_an_unplaced_selection_is_a_disclosed_limitation(self):
        row = {'scenario_id': 'product_entry', 'jurisdiction': 'UNLOCATED', 'right_type': 'patent',
               'candidate_id': 'C1', 'annotation': {'evidence_refs': ['E2', 'E1']}}
        limitation = eu_scope.unlocated_selected_limitation(task(['EU', 'DE']), row)
        self.assertEqual((limitation['reason'], limitation['candidate_id'], limitation['evidence_refs']),
                         ('SELECTED_CANDIDATE_UNLOCATED', 'C1', ['E1', 'E2']))
        self.assertIn('风险待定', limitation['reasoning'])
        self.assertIsNone(eu_scope.unlocated_selected_limitation(task(['EU', 'DE']), dict(row, jurisdiction='EU')))
        self.assertIsNone(eu_scope.unlocated_selected_limitation(task(['EU'], marked=False), row))

    def test_the_gate_uses_it(self):
        text = (Path(__file__).resolve().parent / 'necessary_completion.py').read_text(encoding='utf-8')
        self.assertIn('eu_scope.unlocated_selected_limitation(task, row)', text)


class DeepCheckRuleTests(unittest.TestCase):
    TODAY = date(2026, 11, 17)

    def rule(self, candidate, targets=('EU', 'DE'), others=(), marked=True):
        import triage_defaults
        candidate = {'candidate_id': 'C1', 'right_type': 'patent', **candidate}
        return triage_defaults.focus_rule(candidate, task(targets, marked), list(others), today=self.TODAY)

    def test_an_old_ep_patent_is_expired(self):
        rule, detail = self.rule({'publication_number': 'EP1100000B1', 'filing_date': '2001-03-02'})
        self.assertEqual(rule, 'expired_ep')
        self.assertIn('2001', detail)
        self.assertIsNone(self.rule({'publication_number': 'EP3100000B1', 'filing_date': '2016-03-02'}))
        # a priority date alone never proves the term is over
        self.assertIsNone(self.rule({'publication_number': 'EP1100000B1', 'priority_date': '2001-03-02'}))

    def test_publications_outside_the_scope_are_not_deep_checked(self):
        self.assertEqual(self.rule({'publication_number': 'WO2020123456A1'})[0], 'foreign_publication_eu')
        self.assertEqual(self.rule({'publication_number': 'CN112345678A', 'family_id': 'F1'},
                                   others=[{'candidate_id': 'C2', 'publication_number': 'EP3999999A1', 'family_id': 'F1'}])[0],
                         'family_duplicate_eu')
        self.assertIsNone(self.rule({'publication_number': 'EP3999999A1'}))
        self.assertIsNone(self.rule({'publication_number': 'DE102020123456A1'}))

    def test_us_and_old_tasks_keep_their_rules(self):
        self.assertEqual(self.rule({'publication_number': 'WO2020123456A1'}, targets=('US',))[0], 'foreign_publication')
        self.assertIsNone(self.rule({'publication_number': 'WO2020123456A1'}, marked=False))

    def test_an_ep_card_reported_not_active_is_set_aside(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'raw' / 'serpapi_google_patents'
            folder.mkdir(parents=True)
            (folder / 'raw-1.json').write_text(json.dumps({'organic_results': [
                {'publication_number': 'EP3000001A1', 'country_status': {'EP': 'NOT_ACTIVE', 'DE': 'ACTIVE'}},
                {'publication_number': 'EP3000002B1', 'country_status': {'EP': 'ACTIVE'}}]}), encoding='utf-8')
            statuses = eu_scope.card_statuses(root)
        marked = task(['EU', 'DE'])
        self.assertIn('NOT_ACTIVE', eu_scope.inactive_status(
            {'right_type': 'patent', 'publication_number': 'EP3000001A1'}, statuses, marked))
        self.assertIsNone(eu_scope.inactive_status(
            {'right_type': 'patent', 'publication_number': 'EP3000002B1'}, statuses, marked))
        self.assertIsNone(eu_scope.inactive_status(
            {'right_type': 'patent', 'publication_number': 'EP3000001A1'}, statuses, task(['US'])))

    def test_every_rule_has_its_report_texts(self):
        self.assertEqual(set(eu_scope.TEXTS), {'expired_ep', 'inactive_ep_status', 'foreign_publication_eu',
                                               'family_duplicate_eu'})
        for reason, difference, reopen, label in eu_scope.TEXTS.values():
            self.assertTrue(reason and difference and reopen and label)
            self.assertNotIn('美国', reason + difference + label)


class DeepCheckCapTests(unittest.TestCase):
    def test_selections_are_counted_per_scope(self):
        import recall_screen
        rows = [{'candidate_id': 'C%d' % i, 'scenario_id': 'product_entry', 'jurisdiction': country,
                 'right_type': 'patent', 'decision': 'selected'} for i, country in enumerate(['EU'] * 4 + ['US'] * 2)]
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'materiality-annotations.json').write_text(json.dumps({'annotations': rows}), encoding='utf-8')
            self.assertEqual(recall_screen.selected_count(root, {'patent'}), 2)
            self.assertEqual(recall_screen.selected_count(root, {'patent'}, 'EU'), 4)


EP_XML = ('<?xml version="1.0" encoding="UTF-8"?><ep-patent-document country="EP" doc-number="1234567" kind="B1" '
          'lang="de"><SDOBI><B540><B541>de</B541><B542>Steckdosenleiste</B542></B540></SDOBI>'
          '<description lang="de"><p>' + 'Beschreibung ' * 4000 + '</p></description>'
          '<claims lang="de"><claim num="1"><claim-text>Steckdosenleiste mit Nachtlicht.</claim-text></claim></claims>'
          '<claims lang="en"><claim num="1"><claim-text>A power strip with a night light.</claim-text></claim></claims>'
          '</ep-patent-document>')
PAGE = '\n'.join(['EP1234567B1 - Power strip', 'Abstract', 'A power strip.', 'Description'] + ['text'] * 5000
                 + ['Claims (1)', '1. A power strip with a night light.'])


class ReviewBudgetTests(unittest.TestCase):
    def test_patent_texts_keep_front_matter_and_claims(self):
        text, method = review_budget.condense(EP_XML)
        self.assertEqual(method, 'xml_claims')
        self.assertIn('A power strip with a night light.', text)
        self.assertIn('Steckdosenleiste mit Nachtlicht.', text)
        self.assertNotIn('Beschreibung', text)
        text, method = review_budget.condense(PAGE)
        self.assertEqual(method, 'description_omitted')
        self.assertIn('Claims (1)', text)
        self.assertLess(len(text), 400)
        self.assertEqual(review_budget.condense('short product listing'), ('short product listing', None))

    def packet(self, marked=True):
        materials = [{'material_id': 'M%d' % i, 'kind': 'original_text', 'text': text, 'source_refs': ['E%d' % i]}
                     for i, text in enumerate([EP_XML, PAGE, 'x' * 300000, 'small'])]
        return {'task': {**task(['EU', 'DE'], marked), 'product_scope': {'objects': [
                    {'object_id': 'o1', 'description': '产品本体描述' * 1000}]}},
                'evidence': {'collections': {'api': [{'evidence_id': 'E9', 'payload': {
                    'publication_number': 'EP1234567B1', 'claims': ['1. ...'], 'description': 'd' * 200000}}]}},
                'retained_originals': {'materials': materials}}

    def size(self, packet):
        return len(json.dumps(packet, ensure_ascii=True))

    def test_a_packet_over_budget_is_brought_within_it(self):
        packet = self.packet()
        with mock.patch.object(review_budget, 'prompt_chars', side_effect=self.size):
            record = review_budget.fit(packet, budget=60000, trigger=60000)
        self.assertLessEqual(record['prompt_chars_after'], 60000)
        self.assertEqual([step['step'] for step in record['steps']][:2], ['inline_descriptions', 'claims_only'])
        self.assertEqual(packet['evidence']['collections']['api'][0]['payload']['description'], review_budget.NOTE)
        self.assertIn('产品本体描述', packet['task']['product_scope']['objects'][0]['description'])
        ep = packet['retained_originals']['materials'][0]
        self.assertEqual(ep['omitted_sections'], ['Description'])
        self.assertIn('Review budget (r10)', ep['limitations'])
        self.assertEqual(packet['retained_originals']['materials'][3]['text'], 'small')
        self.assertIs(packet['review_packet_budget'], record)

    def test_a_packet_within_budget_and_old_tasks_are_untouched(self):
        with mock.patch.object(review_budget, 'prompt_chars', side_effect=self.size):
            packet = self.packet()
            self.assertIsNone(review_budget.fit(packet, budget=1000))     # under the host limit: untouched
            self.assertNotIn('review_packet_budget', packet)
            old = self.packet(marked=False)
            self.assertIsNone(review_budget.fit(old, budget=1000, trigger=1000))
            self.assertEqual(old, self.packet(marked=False))

    def test_the_host_paths_use_the_budget(self):
        root = Path(__file__).resolve().parent
        self.assertIn('attach_originals(packet, task_dir, budget=True)', (root / 'module_review.py').read_text(encoding='utf-8'))
        self.assertIn('attach_originals(packet, task_dir, budget=True)', (root / 'review_preflight.py').read_text(encoding='utf-8'))


class GermanTermTests(unittest.TestCase):
    def test_us_tasks_keep_their_rules(self):
        self.assertFalse(eu_scope.non_us(task(['US'])))
        self.assertFalse(eu_scope.non_us(task(['EU', 'DE'], marked=False)))
        self.assertTrue(eu_scope.non_us(task(['EU', 'DE'])))

    def test_german_listing_text_is_recognised(self):
        for value in ('schalter und nachtlicht', 'Steckdosenleiste mit Nachtlicht', 'Mehrfachsteckdose für Küche'):
            self.assertTrue(eu_scope.looks_german(value), value)
        for value in ('power strip', 'night light', 'socket outlet with switch', 'die cast housing'):
            self.assertFalse(eu_scope.looks_german(value), value)


if __name__ == '__main__':
    unittest.main()
