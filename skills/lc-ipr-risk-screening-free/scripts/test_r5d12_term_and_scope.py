"""r5d12: dead patents leave before the final review; a module gets one text per application and its own events.

B0GLNPC6K8 new task: three of five invention patents in the final review were long dead (an Expired - Fee Related
patent whose record says it expired 2023-05-29; two abandoned 2005 applications of a family claiming a 2000-03-21 US
filing), the kept 2019 patent went in three times, and the technical prompt reached 911k characters. On that run's
frozen input the technical prompt becomes 440k characters with two patents (checked on the run copy).
"""
import unittest
from datetime import date
from unittest import mock

import module_review
import prereview_screen as ps

TODAY = date(2026, 10, 13)
TASK = {'prereview_term_revision': ps.TERM_REVISION}


def record(status, *, own='US11/114,542', filing='2005-04-26', priority='2000-03-21', relatives=(), expiration=None):
    events = [{'type': 'legal-status', 'title': status, 'current': True, 'date': 'Status'}]
    if expiration:
        events.append({'type': 'legal-status', 'title': 'Anticipated expiration', 'date': expiration})
    return {'evidence_id': 'EV-R', 'source_run_id': 'RUN', 'payload': {
        'publication_number': 'US20050268860A1', 'legal_status': status, 'priority_date': priority, 'events': events,
        'worldwide_applications': {'2005': [{'application_number': own, 'filing_date': filing,
                                             'legal_status': status, 'this_app': True}]},
        'applications_claiming_priority': [dict(row) for row in relatives]}}


def verdict(entry, evidence=None):
    with mock.patch.object(ps, '_detail_records', return_value=[entry]):
        return ps.term_verdict(TASK, evidence or {'collections': {}}, {'jurisdiction': 'US'}, today=TODAY)


ROOT = {'application_number': 'US09/531,708', 'filing_date': '2000-03-21', 'priority_date': '2000-03-21'}
CHILD = {'application_number': 'US11/657,861', 'filing_date': '2007-01-25', 'priority_date': '2000-03-21'}


class TermTests(unittest.TestCase):
    def test_the_records_own_expiration_date_ends_a_fee_lapsed_patent(self):
        entry = record('Expired - Fee Related', own='US10/449,160', filing='2003-05-29', priority='2003-05-29',
                       expiration='2023-05-29')
        result = verdict(entry)
        self.assertTrue(result['exclude'])
        self.assertEqual((result['expired_on'], result['term_basis']), ('2023-05-29', 'record_expiration'))
        self.assertIn('届满后不能恢复', ps.status_text(result))
        self.assertFalse(verdict(record('Expired - Fee Related', expiration='2027-01-01'))['exclude'])

    def test_a_family_past_twenty_years_plus_the_margin_is_dead(self):
        result = verdict(record('Abandoned', relatives=(ROOT, CHILD)))
        self.assertTrue(result['exclude'])
        self.assertEqual((result['expired_on'], result['term_basis']), ('2025-03-21', 'filing_ceiling'))
        self.assertEqual(set(result['relative_statuses']), {'US09531708', 'US11657861'})

    def test_live_or_unknown_terms_keep_the_candidate(self):
        self.assertFalse(verdict(record('Active', expiration='2020-01-01'))['exclude'])
        # within 20 years + margin
        self.assertFalse(verdict(record('Abandoned', filing='2008-01-01', priority='2008-01-01'))['exclude'])
        # a priority that is not a US non-provisional filing does not start the term: the child's own filing does
        foreign = dict(CHILD, priority_date='1999-01-01')
        self.assertFalse(verdict(record('Abandoned', relatives=(ROOT, foreign)))['exclude'])
        # a relative whose own record says Active
        evidence = {'collections': {'patents': [{'operation': 'candidate_detail', 'evidence_id': 'EV-C', 'payload': {
            'worldwide_applications': {'2007': [{'application_number': 'US11/657,861', 'this_app': True,
                                                 'legal_status': 'Active'}]},
            'legal_status': 'Active', 'events': [{'type': 'legal-status', 'title': 'Active', 'current': True}]}}]}}
        self.assertEqual(verdict(record('Abandoned', relatives=(ROOT, CHILD)), evidence)['reason'],
                         'relative_live:US11657861:Active')

    def test_only_tasks_with_the_marker_use_the_term(self):
        self.assertTrue(ps.term_enabled(TASK))
        self.assertFalse(ps.term_enabled({}))


def doc(evidence_id, number, cid='C1', pdf=False):
    url = ('https://patentimages.storage.googleapis.com/x/%s.pdf' % number if pdf
           else 'https://patents.google.com/patent/%s/en' % number)
    return {'evidence_id': evidence_id, 'operation': 'retained_document', 'publication_number': number,
            'source_url': url, 'path': '/x/' + evidence_id, 'sha256': evidence_id,
            'payload': {'kind': 'patent_document', 'candidate_id': cid, 'publication_number': number, 'text': 'x' * 50}}


class ScopeDietTests(unittest.TestCase):
    def test_one_text_per_application(self):
        rows = [doc('EV-A1', 'US20190307102A1'), doc('EV-A1PDF', 'US20190307102A1', pdf=True),
                doc('EV-B2', 'US11576350B2'), doc('EV-OTHER', 'US20210000001A1', cid='C2'),
                doc('EV-OTHERPDF', 'US20210000001A1', cid='C2', pdf=True)]
        covered = module_review.superseded_texts({'sources': rows})
        self.assertEqual(covered, {'EV-A1': ('EV-B2', 'pre_grant_publication_of_granted_patent'),
                                   'EV-A1PDF': ('EV-B2', 'pre_grant_publication_of_granted_patent'),
                                   'EV-OTHERPDF': ('EV-OTHER', 'pdf_text_of_retained_page')})

    def test_the_module_packet_keeps_its_own_texts_and_events(self):
        events = [{'event_id': 'P', 'kind': 'fact', 'right_type': 'patent', 'candidate_id': 'C1', 'text': 'p' * 99},
                  {'event_id': 'D', 'kind': 'fact', 'right_type': 'design', 'candidate_id': 'C3', 'text': 'd' * 99},
                  {'event_id': 'N', 'kind': 'product', 'text': 'n'}]
        packet = {'task': {'specialty_analysis_events': events},
                  'evidence': {'collections': {'sources': [doc('EV-A1', 'US20190307102A1'), doc('EV-B2', 'US11576350B2')]}}}
        module_review.scope_diet(packet, module_review.GROUPS['technical'])
        kept = packet['task']['specialty_analysis_events']
        self.assertEqual([row.get('text') is not None for row in kept], [True, False, True])
        self.assertEqual(kept[1]['review_packet_stub']['revision'], module_review.PACKET_SCOPE_REVISION)
        texts = packet['evidence']['collections']['sources']
        self.assertNotIn('path', texts[0])
        self.assertEqual(texts[0]['review_packet_stub']['covered_by_evidence_id'], 'EV-B2')
        self.assertEqual(texts[1]['path'], '/x/EV-B2')
        self.assertEqual(packet['review_packet_diet']['covered_text_evidence_ids'], ['EV-A1'])
        self.assertTrue(module_review.packet_scope_enabled({'review_packet_scope_revision': 'module-scope-v1'}))
        self.assertFalse(module_review.packet_scope_enabled({}))


if __name__ == '__main__':
    unittest.main()
