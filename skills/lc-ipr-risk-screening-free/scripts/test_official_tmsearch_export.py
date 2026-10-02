"""Offline acceptance checks for retained official TMsearch result batches."""
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, sha256_file
from merge_candidates import merge
from necessary_completion import collect_publication_issues
from official_tmsearch_export import candidate_entries, parse_export, publication_issues


def _sheet_row(number, values):
    cells = ''.join('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (chr(65 + index), number, value)
                    for index, value in enumerate(values) if value)
    return '<row r="%d">%s</row>' % (number, cells)


class TMsearchExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'batch.xlsx'
        from official_tmsearch_export import HEADERS
        rows = [_sheet_row(1, ['Search results from 1 to 2']),
            _sheet_row(2, ['Search term', '', 'CM:TEST']),
            _sheet_row(4, HEADERS),
            _sheet_row(5, ['12345678', 'TEST', 'Image for 12345678', 'Live', 'IC 020: Toy bells', '', '', '020']),
            _sheet_row(6, ['87654321', 'OTHER', '', 'Dead', 'IC 025: Clothing', '', '', '025'])]
        sheet = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % ''.join(rows)
        with zipfile.ZipFile(self.path, 'w') as workbook:
            workbook.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
            workbook.writestr('xl/worksheets/sheet1.xml', sheet)
        self.entry = {'provider': 'public_source', 'kind': 'official_record',
            'evidence_id': 'EV-BATCH', 'source_run_id': 'RUN-BATCH', 'jurisdiction': 'US',
            'right_type': 'trademark', 'source_url': 'https://tmsearch.uspto.gov/search/search-results',
            'path': str(self.path), 'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'bytes': self.path.stat().st_size}
        self.evidence = {'collections': {'sources': [self.entry]}}

    def test_all_rows_merge_with_source_positions_and_triage_gate(self):
        parsed = parse_export(self.root, self.entry)
        self.assertEqual([row['fields']['SerialNumber'] for row in parsed['rows']], ['12345678', '87654321'])
        entries = candidate_entries(self.root, self.evidence)
        candidates = merge('trademark', entries, {'RUN-BATCH': {'run_id': 'RUN-BATCH', 'status': 'success'}},
                           task_dir=self.root, evidence=self.evidence)
        self.assertEqual(len(candidates), 2)
        self.assertEqual({row['right_type'] for row in candidates}, {'trademark_word'})
        self.assertEqual(len(publication_issues(self.root, self.evidence, {'trademarks': candidates})), 2)
        for row in candidates:
            row['triage_status'] = 'not_selected'
        self.assertEqual(publication_issues(self.root, self.evidence, {'trademarks': candidates}), [])
        candidates[0]['sources'][0]['source_record_sha256'] = '0' * 64
        self.assertIn('OFFICIAL_EXPORT_ROW_UNACCOUNTED', publication_issues(
            self.root, self.evidence, {'trademarks': candidates})[0])

    def test_publication_gate_fails_before_review_when_export_unaccounted(self):
        with patch('necessary_completion._publication_context', return_value=None):
            result = collect_publication_issues({'schema_version': '2.4-free'}, self.evidence,
                {'trademarks': []}, {}, {}, {'coverage': {'scopes': []}, 'review': {'input_reviews': {}}},
                task_dir=self.root, preparation=True)
        self.assertFalse(result['ready'])
        self.assertEqual(sum('OFFICIAL_EXPORT_ROW_UNACCOUNTED' in x for x in result['errors']), 2)

    def test_changed_export_bytes_fail_hash_binding(self):
        self.path.write_bytes(self.path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'RETAINED_PATH_HASH_MISMATCH'):
            parse_export(self.root, self.entry)

    def test_declared_oversize_never_downgrades_source_integrity(self):
        original = self.path.read_bytes()
        cases = [('missing', 'RETAINED_PATH_MISSING'),
                 ('hash', 'RETAINED_PATH_HASH_MISMATCH'),
                 ('length', 'RETAINED_PATH_BYTES_MISMATCH')]
        for fault, code in cases:
            with self.subTest(fault=fault):
                self.path.write_bytes(original)
                entry = {**self.entry, 'bytes': 16 * 1024 * 1024 + 1}
                if fault == 'missing':
                    self.path.unlink()
                elif fault == 'hash':
                    entry['sha256'] = '0' * 64
                issues = []
                evidence = {'collections': {'sources': [entry]}}
                with self.assertRaisesRegex(ValueError, code):
                    candidate_entries(self.root, evidence, issues=issues)
                self.assertEqual(issues, [])
                self.assertTrue(publication_issues(self.root, evidence,
                    {'trademarks': [], 'official_export_issues': issues}, mode='evidence'))

    def test_bound_oversize_is_disclosed_without_loading_workbook(self):
        data = b'X' * (16 * 1024 * 1024 + 1)
        self.path.write_bytes(data)
        entry = {**self.entry, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('oversize read')):
            issues = []
            evidence = {'collections': {'sources': [entry]}}
            self.assertEqual(candidate_entries(self.root, evidence, issues=issues), [])
            self.assertEqual(issues[0]['error_code'], 'TMSEARCH_EXPORT_TOO_LARGE')
            self.assertEqual(publication_issues(self.root, evidence,
                {'trademarks': [], 'official_export_issues': issues}, mode='evidence'), [])
        for change, code in [({'sha256': '0' * 64}, 'RETAINED_PATH_HASH_MISMATCH'),
                             ({'bytes': len(data) + 1}, 'RETAINED_PATH_BYTES_MISMATCH')]:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, code):
                parse_export(self.root, {**entry, **change}, source_bytes=data)
        with self.assertRaisesRegex(ValueError, 'TMSEARCH_EXPORT_TOO_LARGE'):
            parse_export(self.root, entry, source_bytes=data)

    def test_parser_uses_one_verified_workbook_buffer(self):
        data = self.path.read_bytes()
        expected = parse_export(self.root, self.entry)
        # Once captured, parsing never reopens the mutable source path.
        self.path.unlink()
        self.assertEqual(parse_export(self.root, self.entry, source_bytes=data), expected)
        with self.assertRaisesRegex(ValueError, 'RETAINED_PATH_HASH_MISMATCH'):
            parse_export(self.root, self.entry, source_bytes=data + b'foreign')

    def test_workbook_swapped_after_path_verification_rejects(self):
        read = Path.read_bytes
        hits = []
        def changed(path):
            data = read(path)
            if path.resolve() == self.path.resolve():
                hits.append(str(path))
                return data + b'foreign'
            return data
        with patch.object(Path, 'read_bytes', changed):
            with self.assertRaisesRegex(ValueError, 'RETAINED_PATH_HASH_MISMATCH'):
                parse_export(self.root, self.entry)
        self.assertEqual(len(hits), 1)

    def test_malformed_export_preserves_good_rows_and_binds_partial_gap(self):
        broken = self.root / 'broken.xlsx'
        broken.write_bytes(b'not an XLSX archive')
        source = {**self.entry, 'evidence_id': 'EV-BROKEN', 'path': str(broken),
            'sha256': hashlib.sha256(broken.read_bytes()).hexdigest(), 'bytes': broken.stat().st_size,
            'right_type': 'trademark_figurative'}
        evidence = {'collections': {'sources': [self.entry, source]}}
        issues = []
        entries = candidate_entries(self.root, evidence, issues=issues)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0]['payload']['candidates']), 2)
        self.assertEqual([(item['evidence_id'], item['affected_right_types'], item['error_code']) for item in issues],
            [('EV-BROKEN', ['trademark_figurative'], 'TMSEARCH_EXPORT_INVALID')])
        candidates = merge('trademark', entries, {'RUN-BATCH': {'run_id': 'RUN-BATCH', 'status': 'success'}},
            task_dir=self.root, evidence=evidence)
        for item in candidates:
            item['triage_status'] = 'not_selected'
        result = {'trademarks': candidates, 'official_export_issues': issues}
        self.assertEqual(publication_issues(self.root, evidence, result, mode='evidence'), [])
        self.assertTrue(any('OFFICIAL_EXPORT_UNREADABLE' in error for error in
            publication_issues(self.root, evidence, result, mode='final')))
        self.assertIn('OFFICIAL_EXPORT_LIMIT_BINDING_INVALID',
            publication_issues(self.root, evidence, {'trademarks': candidates}, mode='evidence'))
        from workflow_v24 import scenario_execution_gaps
        scopes = [{'scenario_id': 'product_entry', 'scenario_sha256': 'S', 'jurisdiction': 'US',
            'right_type': right, 'gaps': []} for right in ('trademark_word', 'trademark_figurative', 'patent')]
        with patch('workflow_v24.scenario_workflow_enabled', return_value=True):
            gaps = scenario_execution_gaps({}, {}, evidence, candidates=result, ledger={}, coverage=scopes)
        self.assertEqual([(gap['right_type'], gap['evidence_id']) for gap in gaps],
            [('trademark_figurative', 'EV-BROKEN')])
        from module_review import attach_originals, module_packet
        packet = module_packet({'task': {'assessment_scenarios': [], 'target_jurisdictions': []},
            'evidence_digest': 'OFFLINE', 'evidence': evidence, 'candidates': result}, 'expression')
        self.assertEqual(attach_originals(packet, self.root), {})
        materials = packet['retained_originals']['materials']
        self.assertEqual([row['kind'] for row in materials], ['original_text', 'unreadable_original'])
        self.assertEqual(materials[1]['error_code'], 'TMSEARCH_EXPORT_INVALID')
        self.assertNotIn('rows', materials[1]['text'])
        broken.write_bytes(b'changed after binding')
        with self.assertRaisesRegex(ValueError, 'RETAINED_PATH_HASH_MISMATCH'):
            candidate_entries(self.root, evidence, issues=[])

    def test_review_packet_receives_original_export_rows(self):
        from module_review import attach_originals, module_packet
        candidates = merge('trademark', candidate_entries(self.root, self.evidence),
            {'RUN-BATCH': {'run_id': 'RUN-BATCH', 'status': 'success'}},
            task_dir=self.root, evidence=self.evidence)
        frozen = {'task': {'assessment_scenarios': [], 'target_jurisdictions': []},
            'evidence_digest': 'OFFLINE', 'evidence': self.evidence,
            'candidates': {'trademarks': candidates}}
        packet = module_packet(frozen, 'expression')
        self.assertEqual([row['evidence_id'] for row in packet['evidence']['collections']['sources']], ['EV-BATCH'])
        self.assertTrue(all(row['sources'] for row in packet['candidates']['trademarks']))
        for foreign in ('technical', 'appearance'):
            self.assertEqual(module_packet(frozen, foreign)['evidence']['collections']['sources'], [])
        images = attach_originals(packet, self.root)
        self.assertEqual(images, {})
        materials = packet['retained_originals']['materials']
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]['kind'], 'original_text')
        self.assertIn('12345678', materials[0]['text'])
        self.assertIn('87654321', materials[0]['text'])

    def test_damaged_source_allows_evidence_delivery_without_erasing_known_high(self):
        from common import load_json
        from test_evidence_delivery_integration import build_evidence_delivery_fixture
        directory = self.root / 'delivery'
        outcome = build_evidence_delivery_fixture(directory, scenario='mixed_high',
            operator_policy=True, official_export_fixture=True)
        assessment = load_json(directory / 'report' / 'assessment.json')
        data = load_json(directory / 'report' / 'report-data.json')
        self.assertEqual((outcome['publication_mode'], outcome['delivery_status'], assessment['status']),
            ('evidence', 'completed', 'incomplete'))
        self.assertEqual(assessment['overall']['risk'], '高')
        self.assertTrue(any(row.get('reason') == 'OFFICIAL_EXPORT_UNREADABLE'
            and row.get('right_type') == 'trademark_figurative'
            for row in assessment['publication']['limitations']))
        self.assertTrue(any('OFFICIAL_EXPORT_UNREADABLE' in gap
            for item in assessment['coverage']['completion_gaps'] for gap in item['gaps']))
        figurative = next(row for row in data['operator_view']['modules']
            if row['right_type'] == 'trademark_figurative')
        self.assertEqual(figurative['risk_label'], '待定')
        self.assertTrue(any('格式损坏' in text for text in figurative['unfinished']))
        self.assertIn('高', (directory / 'report' / 'report.html').read_text())

    def test_all_damaged_exports_never_become_low_risk_or_final(self):
        from common import load_json
        from test_evidence_delivery_integration import build_evidence_delivery_fixture
        directory = self.root / 'all-broken'
        outcome = build_evidence_delivery_fixture(directory, operator_policy=True,
            official_export_fixture='all_broken')
        assessment = load_json(directory / 'report' / 'assessment.json')
        data = load_json(directory / 'report' / 'report-data.json')
        self.assertEqual((outcome['publication_mode'], assessment['status']), ('evidence', 'incomplete'))
        self.assertIsNone(assessment['overall']['risk'])
        self.assertEqual(data['overall']['listing_recommendation'], '暂缓上架')
        self.assertEqual(next(row for row in data['operator_view']['modules']
            if row['right_type'] == 'trademark_figurative')['risk_label'], '待定')

    def test_merge_entrypoint_keeps_other_rights_when_one_export_is_damaged(self):
        from test_candidate_leads import CandidateLeadTests
        fixture = CandidateLeadTests('test_valid_import_is_bound_unreviewed_not_official_and_idempotent')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.register()
        broken = fixture.root / 'broken.xlsx'
        broken.write_bytes(b'not an XLSX archive')
        evidence = fixture.current_evidence()
        evidence['collections'].setdefault('sources', []).append({
            'provider': 'public_source', 'kind': 'official_record', 'evidence_id': 'EV-BROKEN',
            'jurisdiction': 'US', 'right_type': 'trademark_figurative',
            'source_url': 'https://tmsearch.uspto.gov/search/search-results', 'path': str(broken),
            'sha256': sha256_file(broken), 'bytes': broken.stat().st_size})
        atomic_write_json(fixture.root / 'evidence.json', evidence)
        result = fixture.merge_cli()
        self.assertEqual(len(result['patents']), 1)
        self.assertEqual(len(result['official_export_issues']), 1)
        self.assertEqual(result['official_export_issues'][0]['evidence_id'], 'EV-BROKEN')
