"""core_dossier: program-recorded specialty intake/material/facts/accounting through the real validators."""
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from common import load_json
import core_dossier
import specialty_analysis as sa
import trusted_api


def dossier_fixture(test, *, claims=None, **record):
    """The specialty fixture (selected C1 with a current handoff) plus one exact SerpApi detail record, v2 marker."""
    import test_specialty_analysis as m06
    from test_api_v3_specialty_integration import SpecialtyApiIntegrationTests
    fixture = m06.SpecialtyAnalysisTests()
    fixture.setUp()
    test.addCleanup(fixture.doCleanups)
    fixture.task.update(retrieval_workflow_revision=trusted_api.REVISION, assessment_revision='known-findings-risk-v1',
                        best_estimate_revision='best-estimate-risk-v2')
    fixture.save()
    helper = SpecialtyApiIntegrationTests()
    values = {'claims': claims or ['1. In combination: a container having a mouth; a lid on the mouth; and a strap '
                                   'having openings receiving a handle of the lid.',
                                   '2. The combination of claim 1, wherein the strap is silicone.'],
              'current_assignee': [], 'assignees': ['Individual'],
              'images': ['https://patentimages.storage.googleapis.com/aa/US11111111-20220802-D00000.png',
                         'https://patentimages.storage.googleapis.com/bb/US11111111-20220802-D00001.png'],
              'pdf': 'https://patentimages.storage.googleapis.com/cc/US11111111.pdf'}
    values.update(record)
    helper.retain(fixture, helper.patent(fixture, **values))
    return fixture


def blockers(fixture):
    fixture.refresh()
    view = sa.project(fixture.task, load_json(fixture.path / 'evidence.json'),
                      load_json(fixture.path / 'normalized-candidates.json'),
                      load_json(fixture.path / 'materiality-annotations.json'))
    return [(row['reason'], row.get('fact_kind') or row.get('handoff_gap')) for scope in view['scopes']
            for row in scope['blockers']]


def png(seed):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (30 + seed, 20), (seed * 40 % 255, 20, 20)).save(buffer, 'PNG')
    return buffer.getvalue()


class GapMappingTests(unittest.TestCase):
    def test_program_handoff_sentences_and_keywords(self):
        self.assertEqual(core_dossier.gap_kinds('当前法律状态与权利人尚未核验'), ['status', 'rights_holder'])
        self.assertEqual(core_dossier.gap_kinds('完整权利要求与保护范围尚未读取'), ['protection'])
        self.assertEqual(core_dossier.gap_kinds('target_jurisdiction'), ['territory'])
        self.assertEqual(core_dossier.gap_kinds('current_status'), ['status'])
        self.assertEqual(core_dossier.gap_kinds('供应商合同'), [])

    def test_detail_entry_prefers_newest_exact_record(self):
        def entry(eid, at, **payload):
            return {'evidence_id': eid, 'provider': 'serpapi_google_patents', 'operation': 'candidate_detail',
                    'collected_at': at, 'payload': payload}
        evidence = {'collections': {'patents': [
            entry('A', '2026-10-01T00:00:00Z', candidate_id='C1', publication_number='US1B2'),
            entry('B', '2026-10-02T00:00:00Z', candidate_id='OTHER', publication_number='US1B2'),
            entry('C', '2026-10-03T00:00:00Z', candidate_id='OTHER', publication_number='US9B2'),
            {**entry('D', '2026-10-04T00:00:00Z', candidate_id='C1'), 'operation': 'search'}]}}
        self.assertEqual(core_dossier.detail_entry(evidence, {'candidate_id': 'C1', 'publication_number': 'US1B2'})['evidence_id'], 'B')
        self.assertIsNone(core_dossier.detail_entry(evidence, {'candidate_id': 'C2', 'publication_number': 'US5B2'}))


class RecordedDossierTests(unittest.TestCase):
    def test_records_facts_and_accounting_through_real_validators(self):
        fixture = dossier_fixture(self)
        summary = core_dossier.run(fixture.path, download=False, today='2026-10-11')
        item = summary['candidates'][0]
        self.assertEqual((item['status'], item['base']), ('done', 'recorded'), item)
        self.assertEqual(item['supported_facts'], ['identity', 'territory', 'status', 'protection'])
        fixture.refresh()
        rows = sa.events(fixture.task)
        self.assertTrue(all(row['reviewer'] == core_dossier.REVIEWER for row in rows))
        facts = {row['fact_kind']: row for row in rows if row['kind'] == 'fact'}
        self.assertEqual(facts['rights_holder']['outcome'], 'unknown')   # "Individual" is not a named current holder
        self.assertEqual(facts['status']['resolves_handoff_gaps'], ['current_status'])
        self.assertEqual(facts['product']['outcome'], 'supported')
        # Only the comparison work is left; every source is accounted for.
        self.assertEqual(blockers(fixture), [('SPECIALTY_INVENTORY_PENDING', None)])
        again = core_dossier.run(fixture.path, download=False, today='2026-10-11')
        self.assertEqual(again['candidates'][0]['base'], 'already_recorded')
        fixture.refresh()
        self.assertEqual(len(sa.events(fixture.task)), len(rows))

    def test_agent_specialty_work_is_left_alone(self):
        fixture = dossier_fixture(self)
        fixture.intake()
        fixture.material()
        summary = core_dossier.run(fixture.path, download=False, today='2026-09-24')
        self.assertEqual(summary['candidates'][0]['base'], 'agent_specialty_present')

    def test_inert_without_best_estimate_v2(self):
        fixture = dossier_fixture(self)
        fixture.task['best_estimate_revision'] = 'best-estimate-risk-v1'
        fixture.save()
        self.assertEqual(core_dossier.run(fixture.path, download=False)['status'], 'not_applicable')
        fixture.refresh()
        self.assertEqual(sa.events(fixture.task), [])


class RetainedFileTests(unittest.TestCase):
    def test_drawings_and_pdf_are_bound_to_the_candidate_and_refusals_reported(self):
        fixture = dossier_fixture(self)
        calls = []

        def fetch_image(url):
            calls.append(url)
            if url.endswith('D00001.png'):
                raise ValueError('MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking_198.18.0.0/15')
            return png(len(calls)), '.png', url
        # The fixture's candidate id is not a CAND- id, which record_public_source requires for drawings; register
        # into the same evidence collection the recorder writes (the real recorder is exercised on the run copy).
        registered = []

        def register(task_dir, payload):
            from common import atomic_write_json, sha256_json
            evidence = load_json(Path(task_dir) / 'evidence.json')
            evidence['collections'].setdefault('sources', []).append(
                {'evidence_id': 'EV-' + sha256_json(payload)[:12], 'kind': payload['kind'], 'payload': payload})
            atomic_write_json(Path(task_dir) / 'evidence.json', evidence)
            registered.append(payload)
        patcher = mock.patch.object(core_dossier, '_register', side_effect=register)
        patcher.start()
        self.addCleanup(patcher.stop)
        summary = core_dossier.run(fixture.path, fetch_image=fetch_image,
                                   fetch_document=lambda url: (b'%PDF-1.4 body', url), today='2026-10-11')
        files = summary['candidates'][0]['files']
        self.assertEqual([row['figure_label'] for row in files['drawings']], ['D00000'])
        self.assertIn('MEDIA_PUBLIC_ADDRESS_REQUIRED', files['failures'][0]['reason'])
        self.assertTrue(files['document']['evidence_id'])
        sources = load_json(fixture.path / 'evidence.json')['collections']['sources']
        drawing = next(row['payload'] for row in sources if row['payload'].get('kind') == 'patent_drawing_image')
        self.assertEqual((drawing['visual_role'], drawing['candidate_id'], drawing['figure_label']),
                         ('patent_drawings', 'C1', 'D00000'))
        self.assertEqual(drawing['source_record_evidence_id'], 'API-E')
        self.assertTrue(Path(drawing['path']).is_file())
        self.assertTrue(json.loads((fixture.path / core_dossier.OUTPUT).read_text(encoding='utf-8'))['candidates'])
        # A rerun reuses retained files by their public address and retries only the refused one.
        before = len(calls)
        core_dossier.run(fixture.path, fetch_image=fetch_image, fetch_document=lambda url: self.fail('refetched pdf'))
        self.assertEqual(calls[before:], ['https://patentimages.storage.googleapis.com/bb/US11111111-20220802-D00001.png'])


if __name__ == '__main__':
    unittest.main()
