"""best-estimate-risk-v2 review-packet diet: not_selected candidate material becomes a stub, selected material stays
whole, administrative task logs and duplicated task snapshots are left out, legacy packets are unchanged, and a
refused module turn leaves a rejection log line."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import module_review as mod
from common import sha256_file, sha256_json

V2_TASK = {'task_id': 'T', 'assessment_revision': 'known-findings-risk-v1',
           'best_estimate_revision': 'best-estimate-risk-v2', 'target_jurisdictions': ['US'],
           'history': [{'at': 'x', 'event': 'log'}], 'checkpoints': [{'id': 1}], 'product_delivery': {'a': 1},
           'discovery_semantic_reviews': [{'id': 'D'}], 'source_operation_reviews': [{'id': 'S'}],
           'specialty_transaction_receipts': [{'id': 'R'}], 'product': {'title': 'strap'}}


def triage(cid, decision, reason='reason ' + 'x'):
    return {'product_entry': [{'candidate_id': cid, 'scenario_id': 'product_entry', 'jurisdiction': 'US',
                               'right_type': 'patent', 'decision': decision, 'current': True,
                               'annotation': {'decision': decision, 'reason': reason}}]}


def frozen(task):
    selected = {'candidate_id': 'CAND-SEL', 'publication_number': 'US11401089B2', 'right_type': 'patent',
                'jurisdiction': 'US', 'triage_by_scenario': triage('CAND-SEL', 'selected')}
    rejected = {'candidate_id': 'CAND-NO', 'publication_number': 'US20250318691A1', 'right_type': 'patent',
                'jurisdiction': 'US', 'triage_by_scenario': triage('CAND-NO', 'not_selected', 'glass jar lid')}
    design_no = {'candidate_id': 'CAND-D', 'publication_number': 'USD887770S1', 'right_type': 'design',
                 'jurisdiction': 'US', 'triage_by_scenario': triage('CAND-D', 'not_selected', 'crossed straps')}
    untriaged = {'candidate_id': 'CAND-LEAD', 'publication_number': 'US20220348389A1', 'right_type': 'patent',
                 'jurisdiction': 'US'}
    detail = lambda eid, cid, number: {'evidence_id': eid, 'provider': 'serpapi_google_patents',
        'operation': 'candidate_detail', 'jurisdiction': 'US', 'right_type': 'patent',
        'payload': {'candidate_id': cid, 'publication_number': number, 'title': 'T ' + number,
                    'claims': ['1. A long claim ' * 50], 'description_link': 'https://x'}}
    return {'task': deepcopy(task), 'evidence_digest': 'D' * 64,
            'candidates': {'patents': [selected, rejected, design_no, untriaged]},
            'evidence': {'collections': {
                'patents': [detail('EV-SEL', 'CAND-SEL', 'US11401089B2'), detail('EV-NO', 'CAND-NO', 'US20250318691A1'),
                            {'evidence_id': 'EV-SEARCH', 'provider': 'epo_ops', 'operation': 'search',
                             'jurisdiction': 'US', 'right_type': 'patent',
                             'payload': {'candidates': [{'publication_number': 'US20250318691A1'}]}}],
                'sources': [
                    {'evidence_id': 'EV-PDF-SEL', 'kind': 'patent_document', 'publication_number': 'US11401089B2',
                     'path': '/r/US11401089.pdf', 'sha256': 'A' * 64, 'right_type': 'patent', 'jurisdiction': 'US',
                     'source_url': 'https://patentimages.storage.googleapis.com/7a/US11401089.pdf'},
                    {'evidence_id': 'EV-DRAW-NO', 'kind': 'design_document', 'path': '/r/d.png', 'sha256': 'B' * 64,
                     'right_type': 'design', 'jurisdiction': 'US',
                     'source_url': 'https://patentimages.storage.googleapis.com/f0/USD0887770-20200623-D00006.png'},
                    {'evidence_id': 'EV-LEAD-DOC', 'kind': 'patent_document', 'publication_number': 'US20220348389A1',
                     'path': '/r/lead.html', 'sha256': 'C' * 64, 'right_type': 'patent', 'jurisdiction': 'US',
                     'source_url': 'https://patents.google.com/patent/US20220348389A1/en'}],
                'product_scope': [{'evidence_id': 'EV-SCOPE', 'scope': {'status': 'reviewed'},
                                   'result_task': {'big': 'snapshot'},
                                   'payload': {'scope': {'status': 'reviewed'}, 'result_task': {'big': 'snapshot'}}}],
                'institution_references': [{'evidence_id': 'EV-INST-US-UTILITY_MODEL', 'right_type': 'utility_model',
                                            'jurisdiction': 'US', 'payload': {'applicable': False}}]}},
            'supplement': {'evidence': [{'evidence_id': 'MEDIA-NO', 'candidate_id': 'CAND-D', 'kind': 'candidate_image',
                                         'path': '/r/m.png', 'sha256': 'E' * 64, 'right_type': 'design',
                                         'source_url': 'https://patentimages.storage.googleapis.com/x.png'}]}}


def ids(packet, collection):
    return {row['evidence_id']: row for row in packet['evidence']['collections'].get(collection, [])}


class PacketDietTests(unittest.TestCase):
    def test_v2_stubs_only_not_selected_material_and_keeps_selected_whole(self):
        source = frozen(V2_TASK)
        packet = mod.module_packet(source, 'technical')
        patents = ids(packet, 'patents')
        self.assertEqual(patents['EV-SEL'], source['evidence']['collections']['patents'][0])
        self.assertEqual(patents['EV-SEARCH'], source['evidence']['collections']['patents'][2])
        stub = patents['EV-NO']
        self.assertNotIn('payload', stub)
        self.assertEqual(stub['candidate_id'], 'CAND-NO')
        self.assertEqual(stub['publication_number'], 'US20250318691A1')
        self.assertEqual(stub['review_packet_stub']['triage_decision'], 'not_selected')
        self.assertEqual(stub['review_packet_stub']['triage_reason'], 'glass jar lid')
        self.assertEqual(stub['review_packet_stub']['record_sha256'],
                         sha256_json(source['evidence']['collections']['patents'][1]))
        sources = ids(packet, 'sources')
        self.assertIn('path', sources['EV-PDF-SEL'])
        self.assertIn('path', sources['EV-LEAD-DOC'])        # untriaged lead: never stubbed
        self.assertIn('EV-NO', packet['review_packet_diet']['stubbed_evidence_ids'])

    def test_v2_design_drawing_file_name_and_supplement_media_follow_the_triage(self):
        packet = mod.module_packet(frozen(V2_TASK), 'appearance')
        drawing = ids(packet, 'sources')['EV-DRAW-NO']
        self.assertNotIn('path', drawing)
        self.assertEqual(drawing['review_packet_stub']['triage_reason'], 'crossed straps')
        media = packet['supplement']['evidence'][0]
        self.assertNotIn('path', media)
        self.assertEqual(media['candidate_id'], 'CAND-D')
        from review_material_policy import file_inventory
        self.assertEqual([row['path'] for row in file_inventory(packet)], [])

    def test_v2_drops_admin_task_logs_and_task_snapshots_but_keeps_scope_and_institutions(self):
        packet = mod.module_packet(frozen(V2_TASK), 'technical')
        for name in mod.DIET_TASK_FIELDS:
            self.assertNotIn(name, packet['task'])
        self.assertEqual(packet['task']['product'], {'title': 'strap'})
        scope = ids(packet, 'product_scope')['EV-SCOPE']
        self.assertNotIn('result_task', scope)
        self.assertNotIn('result_task', scope['payload'])
        self.assertEqual(scope['scope'], {'status': 'reviewed'})
        self.assertIn('EV-INST-US-UTILITY_MODEL', ids(packet, 'institution_references'))

    def test_diet_is_deterministic(self):
        self.assertEqual(mod.module_packet(frozen(V2_TASK), 'technical'), mod.module_packet(frozen(V2_TASK), 'technical'))

    def test_legacy_and_v1_packets_are_unchanged(self):
        for revision in (None, 'best-estimate-risk-v1'):
            task = deepcopy(V2_TASK)
            if revision is None:
                task.pop('best_estimate_revision')
            else:
                task['best_estimate_revision'] = revision
            packet = mod.module_packet(frozen(task), 'technical')
            self.assertNotIn('review_packet_diet', packet)
            self.assertIn('checkpoints', packet['task'])        # history is already an admin collection for all tasks
            self.assertIn('payload', ids(packet, 'patents')['EV-NO'])
            self.assertIn('result_task', ids(packet, 'product_scope')['EV-SCOPE'])

    def test_every_selected_candidate_citation_stays_whole(self):
        """The guarantee the run7 golden checks on real data: what a selected candidate row cites is never stubbed."""
        source = frozen(V2_TASK)
        packet = mod.module_packet(source, 'technical')
        cited = {'EV-SEL', 'EV-PDF-SEL', 'EV-SEARCH', 'EV-SCOPE', 'EV-INST-US-UTILITY_MODEL'}
        rows = {row['evidence_id']: row for rows in packet['evidence']['collections'].values() for row in rows}
        for ref in cited & set(rows):
            self.assertNotIn('review_packet_stub', rows[ref], ref)


class PatentPageTrimTests(unittest.TestCase):
    PAGE = '\n'.join(['Title', 'Info', 'Classifications', 'B65D45/00 lids', 'B65D63/10 straps', 'Abstract',
                      'A strap.', 'Description', 'Long text.', 'Claims (8)', '1. A strap comprising holes.',
                      'Priority Applications (1)', 'US16/372,470', 'Cited By (1)', 'US20220348389A1',
                      'Similar Documents', 'US1234567A', 'Legal Events', 'FEPP fee payment'])

    def test_lists_are_omitted_and_claims_and_legal_events_kept(self):
        text, omitted = mod.trim_patent_page_text(self.PAGE, 'https://patents.google.com/patent/US11401089B2/en')
        self.assertEqual(omitted, ['Classifications', 'Cited By (1)', 'Similar Documents'])
        for kept in ('Abstract', 'A strap.', 'Long text.', '1. A strap comprising holes.', 'US16/372,470',
                     'Legal Events', 'FEPP fee payment'):
            self.assertIn(kept, text)
        for gone in ('B65D63/10 straps', 'US1234567A', 'US20220348389A1'):
            self.assertNotIn(gone, text)

    def test_other_hosts_untouched(self):
        self.assertEqual(mod.trim_patent_page_text(self.PAGE, 'https://example.com/x'), (self.PAGE, []))

    def test_attach_trims_only_for_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / 'US1.html'
            page.write_text('<html><body>' + ''.join('<p>%s</p>' % line for line in self.PAGE.split('\n'))
                            + '</body></html>', encoding='utf-8')
            row = {'evidence_id': 'E1', 'path': str(page), 'sha256': sha256_file(page), 'bytes': page.stat().st_size,
                   'source_url': 'https://patents.google.com/patent/US1/en'}
            for task, trimmed in ((deepcopy(V2_TASK), True), ({'task_id': 'T'}, False)):
                packet = {'task': task, 'supplement': {'evidence': [deepcopy(row)]}}
                mod.attach_originals(packet, root)
                material = packet['retained_originals']['materials'][0]
                self.assertEqual('US1234567A' not in material['text'], trimmed)
                self.assertEqual('omitted_sections' in material, trimmed)


class RejectionLogTests(unittest.TestCase):
    def test_v2_appends_one_line_per_refusal_and_legacy_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / '2' / 'appearance.attempt-1').mkdir(parents=True)
            error = mod.ModelJudgmentError('FINAL_REVIEW_ORIGINAL_OBSERVATION_INVALID: M11')
            mod.log_rejection(out, V2_TASK, 2, 'appearance', error, phase='fresh_turn')
            mod.log_rejection(out, {'task_id': 'T'}, 1, 'technical', error, phase='fresh_turn')
            lines = (out / mod.REJECTION_LOG).read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual((row['chain'], row['module'], row['attempt'], row['error_code']),
                             ('2', 'appearance', 2, 'FINAL_REVIEW_ORIGINAL_OBSERVATION_INVALID'))
            self.assertEqual(row['detail'], 'FINAL_REVIEW_ORIGINAL_OBSERVATION_INVALID: M11')


if __name__ == '__main__':
    unittest.main()
