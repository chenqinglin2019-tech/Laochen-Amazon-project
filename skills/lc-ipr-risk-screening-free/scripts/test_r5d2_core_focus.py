"""r5d2 fixes from the r5d real run: program defaults for expired / foreign / identity-less cards, the text triage
bar and priority, exact-record requests kept for core candidates, the granted text of a granted application, public
pages when the record budget is used up, and the design kind-code match in Patent Public Search."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

TODAY = date(2026, 10, 12)
PAGE = ('<html><head><meta name="citation_pdf_url" content="https://patentimages.storage.googleapis.com/x/US1.pdf">'
        '</head><body><span itemprop="title">Device for securing a lid</span>'
        '<dd itemprop="publicationNumber">US11401089B2</dd>'
        '<dd itemprop="legalStatusIfi" itemprop="status"> <span itemprop="status">Active</span></dd>'
        '<meta itemprop="full" content="https://patentimages.storage.googleapis.com/a/US1-D00000.png">'
        '<section itemprop="claims" itemscope><h2>Claims (2)</h2><div class="claims">'
        '<div class="claim"> <div id="CLM-00001" num="00001" class="claim"><div class="claim-text">1. In combination:'
        '<div class="claim-text">a food container having a mouth;</div><div class="claim-text">a strap.</div></div></div></div>'
        '<div class="claim-dependent"> <div id="CLM-00002" num="00002" class="claim"><div class="claim-text">2. The '
        'combination of claim 1, wherein the strap is flat.</div></div></div></div></section></body></html>')


class CoreFocusFactsTests(unittest.TestCase):
    def test_expiry_reads_only_the_us_application_year(self):
        import core_focus
        old = {'right_type': 'patent', 'publication_number': 'US6058808A',
               'application_numbers': ['US13603398A', 'US19980136033', '136033']}
        self.assertIn('1998', core_focus.expired_by_age(old, today=TODAY))
        # a foreign priority may precede the US filing: never used to age the document
        foreign = {'right_type': 'patent', 'publication_number': 'US2002026864A1',
                   'application_numbers': ['US77431401A', 'US20010774314'], 'priority_numbers': ['JP20000267968']}
        self.assertIsNone(core_focus.expired_by_age(foreign, today=TODAY))
        # a German application number is not a year
        self.assertIsNone(core_focus.earliest_filing_year({'application_numbers': ['DE19808910A']}))
        recent = {'right_type': 'patent', 'publication_number': 'US2019315539A1',
                  'application_numbers': ['US201916372470A', 'US201916372470']}
        self.assertIsNone(core_focus.expired_by_age(recent, today=TODAY))

    def test_design_term_runs_from_grant(self):
        import core_focus
        self.assertTrue(core_focus.expired_by_age({'right_type': 'design', 'publication_number': 'USD639521S1',
                                                    'publication_date': '2010-06-07'}, today=TODAY))
        self.assertIsNone(core_focus.expired_by_age({'right_type': 'design', 'publication_number': 'USD887770S1',
                                                      'publication_date': '2020-06-23'}, today=TODAY))

    def test_foreign_publication_in_a_us_only_task(self):
        import core_focus
        task = {'target_jurisdictions': ['US']}
        wo = {'candidate_id': 'C1', 'right_type': 'patent', 'publication_number': 'WO2020180319A1', 'family_id': '1'}
        us = {'candidate_id': 'C2', 'right_type': 'patent', 'publication_number': 'US2020281343A1', 'family_id': '1'}
        self.assertEqual(core_focus.foreign_publication(wo, task, [wo, us])[0], 'family_duplicate')
        self.assertEqual(core_focus.foreign_publication(wo, task, [wo])[0], 'foreign_publication')
        self.assertIsNone(core_focus.foreign_publication(us, task, [wo, us]))
        self.assertIsNone(core_focus.foreign_publication(wo, {'target_jurisdictions': ['US', 'EU']}, [wo]))

    def test_granted_publication_of_the_same_application(self):
        import core_focus
        payload = {'publication_number': 'US20190315539A1', 'worldwide_applications': {'2019': [
            {'this_app': True, 'document_id': 'patent/US11401089B2/en', 'legal_status': 'Active'}]}}
        self.assertEqual(core_focus.granted_publication(payload), 'US11401089B2')
        self.assertIsNone(core_focus.granted_publication({'publication_number': 'US11401089B2', 'events': [
            {'type': 'publication', 'document_id': 'patent/US11401089B2/en'}]}))

    def test_public_page_claims_and_facts(self):
        import core_focus
        claims = core_focus.page_claims(PAGE)
        self.assertEqual(claims[0], '1. In combination: a food container having a mouth; a strap.')
        self.assertTrue(claims[1].startswith('2. The combination of claim 1'))
        facts = core_focus.page_facts(PAGE)
        self.assertEqual((facts['publication_number'], facts['legal_status']), ('US11401089B2', 'Active'))
        self.assertEqual(len(facts['images']), 1)
        text = 'Spec text.\n\nClaims\n\n1. A strap comprising: a band;\n\na hole.\n\n2. The strap of claim 1.'
        self.assertEqual(core_focus.document_claims(text), ['1. A strap comprising: a band; a hole.', '2. The strap of claim 1.'])

    def test_priorities_are_kept_beside_the_ledger(self):
        import core_focus
        with tempfile.TemporaryDirectory() as tmp:
            core_focus.save_priorities(tmp, {'C1': 'core', 'C2': 'related', 'C3': 'bogus'})
            core_focus.save_priorities(tmp, {'C2': 'core'})
            self.assertEqual(core_focus.priorities(tmp), {'C1': 'core', 'C2': 'core'})


class TriageDefaultTests(unittest.TestCase):
    def test_focus_rules(self):
        import triage_defaults as td
        task = {'target_jurisdictions': ['US']}
        page = {'candidate_nature': 'web_result', 'right_type': 'unknown', 'title': 'US9392893B2 - Closure for a lid',
                'url': 'https://patents.google.com/patent/US9392893B2/en', 'snippet': 'A closure for an opening in a lid.'}
        self.assertEqual(td.focus_rule(page, task, [])[0], 'patent_page')
        image = {'candidate_nature': 'visual_match', 'right_type': 'unknown', 'title': 'Silicone pot lid straps',
                 'url': 'https://example.com/straps.jpg'}
        self.assertEqual(td.focus_rule(image, task, [])[0], 'no_rights_identity')
        lawsuit = dict(image, title='Lid strap patent infringement lawsuit filed against seller')
        self.assertIsNone(td.focus_rule(lawsuit, task, []))
        old = {'right_type': 'patent', 'publication_number': 'US6058808A', 'application_numbers': ['US19980136033']}
        self.assertEqual(td.focus_rule(old, task, [], today=TODAY)[0], 'expired')
        # a patent database page is a patent document even when its snippet names "intellectual property"
        patsnap = {'candidate_nature': 'web_result', 'right_type': 'unknown',
                   'title': 'Perforated hardboard grommet & fixture securing system',
                   'snippet': 'Expert workflows across engineering, materials and intellectual property.',
                   'url': 'https://eureka.patsnap.com/patent-US20160341232A1'}
        self.assertEqual(td.focus_rule(patsnap, task, [])[0], 'patent_page')


class SharedJsonTests(unittest.TestCase):
    def test_shared_read_follows_every_replacement(self):
        from common import atomic_write_json, load_json_shared
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'task.json'
            atomic_write_json(path, {'v': 1})
            first = load_json_shared(path)
            self.assertIs(load_json_shared(path), first)
            atomic_write_json(path, {'v': 2})
            self.assertEqual(load_json_shared(path), {'v': 2})


class TextTriageTests(unittest.TestCase):
    def test_core_focus_prompt_asks_for_priority_and_the_same_use_bar(self):
        import text_triage_host as host
        packet = {'schema': 'IPR-TEXT-TRIAGE/1.0', 'product': {}, 'objects': [], 'directions': [], 'facts': [],
                  'units': [], 'followup_contract': {}}
        self.assertNotIn('priority', host.prompt(packet))
        text = host.prompt({**packet, 'core_focus': 'core-focus-v1'})
        self.assertIn('同一类物品或同一用途', text)
        self.assertIn('priority', text)

    def test_priorities_saved_for_recorded_selections_only(self):
        import core_focus
        import text_triage_host as host
        packet = {'units': [{'unit_id': 'U1', 'template': {'candidate_id': 'C1'}},
                            {'unit_id': 'U2', 'template': {'candidate_id': 'C2'}},
                            {'unit_id': 'U3', 'template': {'candidate_id': 'C3'}}]}
        raw = {'decisions': [{'unit_id': 'U1', 'decision': 'selected', 'priority': 'core'},
                             {'unit_id': 'U2', 'decision': 'selected'},
                             {'unit_id': 'U3', 'decision': 'selected', 'priority': 'core'}]}
        with tempfile.TemporaryDirectory() as tmp:
            host.save_priorities(tmp, packet, raw, [{'candidate_id': 'C3'}])
            self.assertEqual(core_focus.priorities(tmp), {'C1': 'core', 'C2': 'related'})


class RecordBudgetTests(unittest.TestCase):
    def test_related_candidates_leave_the_requests_core_candidates_need(self):
        import candidate_api_actions as actions
        import core_focus
        task = {'core_focus_revision': core_focus.REVISION}
        with tempfile.TemporaryDirectory() as tmp:
            core_focus.save_priorities(tmp, {'CORE1': 'core', 'CORE2': 'core', 'REL': 'related'})
            queries = {'serpapi_google_patents': [{'operation': 'candidate_detail', 'candidate_id': 'CORE1'}]}
            self.assertEqual(actions._core_reserve(task, {'source_runs': []}, queries, {'candidate_id': 'REL'}, tmp), 1)
            self.assertEqual(actions._core_reserve(task, {'source_runs': []}, queries, {'candidate_id': 'CORE2'}, tmp), 0)
            self.assertEqual(actions._core_reserve({}, {'source_runs': []}, queries, {'candidate_id': 'REL'}, tmp), 0)


class PublicPageClaimsTests(unittest.TestCase):
    def test_comparison_reads_claims_from_the_retained_page(self):
        import comparison_host
        from common import sha256_bytes
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'page.html'
            path.write_text(PAGE, encoding='utf-8')
            entry = {'evidence_id': 'EV-1', 'payload': {'page_role': 'granted_publication', 'path': str(path),
                     'sha256': sha256_bytes(PAGE.encode()), 'publication_number': 'US11401089B2'}}
            record, claims = comparison_host._claims_record({'collections': {'sources': [entry]}}, {'evidence_refs': ['EV-1']})
            self.assertEqual(record['payload']['publication_number'], 'US11401089B2')
            self.assertEqual([row['independent'] for row in claims], [True, False])
            path.write_text(PAGE + ' ', encoding='utf-8')        # a changed file is never read as the retained page
            self.assertEqual(comparison_host._claims_record({'collections': {'sources': [entry]}},
                                                            {'evidence_refs': ['EV-1']}), (None, []))


class ReviewPacketTests(unittest.TestCase):
    def test_related_excerpt_keeps_front_matter_and_claims(self):
        import module_review as mr
        page = 'Title\nAbstract\nA strap.\nDescription\nLong text.\nMore text.\nClaims (2)\n1. A strap.\nLegal Events'
        text, cut = mr.related_excerpt(page)
        self.assertTrue(cut)
        self.assertNotIn('Long text.', text)
        self.assertIn('1. A strap.', text)
        pdf = 'front page abstract\n[page 2]\nbody\n[page 3]\nWhat is claimed is:\n1. A strap.'
        text, cut = mr.related_excerpt(pdf, pdf=True)
        self.assertTrue(cut)
        self.assertEqual(text, 'front page abstract\n[... description omitted ...]\nWhat is claimed is:\n1. A strap.')
        self.assertEqual(mr.related_excerpt('no sections here'), ('no sections here', False))

    def test_focus_diet_stubs_only_not_selected_entries(self):
        import module_review as mr
        excluded = {'C2': {'decision': 'not_selected', 'reason': '用途不同'}}
        packet = {'review_packet_diet': {'meaning': 'm'},
                  'candidates': {'patents': [{'candidate_id': 'C1', 'publication_number': 'US1A1', 'abstract': 'keep'},
                                             {'candidate_id': 'C2', 'publication_number': 'US2A1', 'abstract': 'drop'}]},
                  'evidence': {'collections': {'patents': [{'payload': {'candidates': [
                      {'publication_number': 'US1A1', 'abstract': 'keep'},
                      {'publication_number': 'US2A1', 'abstract': 'drop'}]}}]}},
                  'search_plan': {'terms': [{'value': 'X', '_triage_decision': {'candidate_id': 'C1', 'decision': 'selected',
                                                                                 'annotation': {'annotation_id': 'A1', 'reason': 'r'}}}]}}
        mr.focus_diet(packet, excluded, kept_keys={'US1'}, excluded_keys={'US2': {'C2'}})
        cards = packet['candidates']['patents']
        self.assertEqual(cards[0]['abstract'], 'keep')
        self.assertNotIn('abstract', cards[1])
        self.assertEqual(cards[1]['review_packet_stub']['triage_decision'], 'not_selected')
        entries = packet['evidence']['collections']['patents'][0]['payload']['candidates']
        self.assertEqual(entries[0]['abstract'], 'keep')
        self.assertEqual(entries[1]['review_packet_stub']['candidate_ids'], ['C2'])
        term = packet['search_plan']['terms'][0]['_triage_decision']
        self.assertEqual((term['annotation_id'], term['decision']), ('A1', 'selected'))
        self.assertEqual(packet['review_packet_diet']['projected_result_entries'], 1)


class PublishedDocumentNumberTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_design_kind_code_spellings_name_the_same_document(self):
        cli = Path(__file__).resolve().parents[1] / 'tools' / 'cdp' / 'cdp-cli.mjs'
        script = ("import(%s).then(m => console.log(JSON.stringify([m.sameRecordNumber('US D887770 S', 'USD887770S1'),"
                  "m.sameRecordNumber('USD887770S', 'USD887771S1'), m.sameRecordNumber('US10357433B1', 'US10357433B2'),"
                  "m.sameRecordNumber('US 2010/0326991 A1', 'US20100326991A1')])))" % json.dumps(cli.as_uri()))
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=60)
        if result.returncode != 0 and 'ERR_MODULE_NOT_FOUND' in result.stderr:
            self.skipTest('browser tool dependencies are not installed (setup_skill.py installs them)')
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [True, False, False, True])


if __name__ == '__main__':
    unittest.main()
