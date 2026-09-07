"""Offline counterexamples for the estimate policy's hardened boundaries."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from assessment_estimate import compute_assessment, review_digest
from assessment_v24 import query_coverage, coverage_by_scope
from annotate_materiality import candidate_identity_fingerprint, apply_materiality_annotations, empty_materiality_ledger
from common import now_iso, sha256_file, sha256_json
from test_assessment_estimate import fixture
import test_assessment_v24 as legacy_tests


class EstimateHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.values = fixture(self.root)

    def refresh(self, supplement=None):
        t, e, c, p, ledger, first, second = self.values
        for review in (first, second):
            review['review_context']['evidence_digest'] = review_digest(e, c, ledger, p, t, supplement)

    def calculate(self, **kwargs):
        return compute_assessment(*self.values, **kwargs)

    def rows(self, **changes):
        for review in self.values[-2:]:
            review['assessments'][0].update(deepcopy(changes))

    def patent(self):
        t, _, c, _, ledger, _, _ = self.values
        item = c['copyright_assets'].pop()
        item.update(right_type='patent', publication_number='US1234567B1', application_number='US17/123456', family_members=[])
        c['patents'] = [item]
        ledger['annotations'][0]['candidate_identity_fingerprint'] = candidate_identity_fingerprint('patents', item)
        apply_materiality_annotations(ledger, t['task_id'], c)
        self.rows(right_type='patent', module_id='utility_patent', right_state='active', right_state_evidence_refs=['EV-PROV'])
        for review in self.values[-2:]:
            review['assessments'][0].pop('comparison', None)
            review['assessments'][0].pop('confidence_basis', None)
        self.refresh()

    def chief(self, decision=True, **values):
        first, second = self.values[-2:]
        refs = {'first': sha256_json(first), 'second': sha256_json(second)}
        row = deepcopy(first['assessments'][0])
        row.update(adjudication_reasoning='Compared both reviews and retained evidence.', review_refs=refs)
        return {'reviewer': 'chief', 'review_context': {'session_id': 'chief-session', 'evidence_digest': first['review_context']['evidence_digest']}, 'decisions': [row] if decision else [], 'review_refs': refs, **values}

    def supplement(self):
        path = self.root / 'retained.txt'
        path.write_text('retained original')
        return {'schema': 'retained/1', 'evidence': [{'evidence_id': 'SUP', 'path': str(path), 'sha256': sha256_file(path), 'bytes': path.stat().st_size, 'kind': 'official_record', 'source_url': 'https://example.org/record', 'checked_at': now_iso()}], 'coverage_notes': []}

    def test_strict_flags(self):
        for flag in ('out_of_scope', 'future_signal', 'signal_only', 'aggregation_included'):
            for value in ('false', 0, 1, None):
                with self.subTest(flag=flag, value=value):
                    self.rows(**{flag: value})
                    with self.assertRaisesRegex(ValueError, 'FLAG_MUST_BE_BOOLEAN'):
                        self.calculate()
                    for review in self.values[-2:]:
                        review['assessments'][0].pop(flag)

    def test_mock_supplement_blocked_across_published_reference_trees(self):
        supplement = self.supplement()
        supplement['evidence'][0]['source_environment'] = 'test'
        self.refresh(supplement)
        for name in ('future_applications', 'enforcement_signals'):
            self.values[-2][name] = [{'reasoning': 'Supplemental assertion', 'evidence_refs': ['SUP']}]
            with self.assertRaisesRegex(ValueError, 'NON_PRODUCTION_EVIDENCE'):
                self.calculate(supplement=supplement, evidence_root=self.root)
            del self.values[-2][name]
        chief = self.chief(overall_decisive_exclusion={'scope': 'specific', 'reasoning': 'Claimed exclusion', 'evidence_refs': ['SUP']})
        with self.assertRaisesRegex(ValueError, 'NON_PRODUCTION_EVIDENCE'):
            self.calculate(adjudication=chief, supplement=supplement, evidence_root=self.root)
        self.assertEqual(self.calculate(supplement=supplement, evidence_root=self.root)['overall']['risk'], '高')
        supplement['evidence'][0].pop('source_environment')
        supplement['evidence'][0]['kind'] = 'mock'
        self.rows(supporting_evidence=[{'reasoning': 'Mock sole support', 'evidence_refs': ['SUP']}], evidence_refs=['EV-PROV', 'EV-PRODUCT', 'SUP'])
        self.refresh(supplement)
        with self.assertRaisesRegex(ValueError, 'NON_PRODUCTION_EVIDENCE'):
            self.calculate(supplement=supplement, evidence_root=self.root)

    def test_all_original_screenshot_bindings_and_missing_hash(self):
        image = self.root / 'retained.png'
        image.write_bytes(b'original')
        digest = sha256_file(image)
        shapes = [({'screenshot_path': str(image), 'screenshot_sha256': digest}, 'HASH_OR_SIZE_MISMATCH'),
                  ({'screenshots': {'front': str(image)}, 'screenshot_hashes': {'front': digest}}, 'HASH_OR_SIZE_MISMATCH'),
                  ({'screenshots': [str(image)], 'screenshot_hashes': [digest]}, 'HASH_OR_SIZE_MISMATCH'),
                  ({'screenshot_paths': [str(image)], 'screenshot_hashes': {str(image): digest}}, 'HASH_OR_SIZE_MISMATCH'),
                  ({'screenshot_path': str(image)}, 'ARTIFACT_INVALID')]
        image.write_bytes(b'changed')
        for shape, error in shapes:
            with self.subTest(shape=shape):
                self.values[1]['collections']['asset_provenance'][0]['browser_evidence'] = shape
                self.refresh()
                with self.assertRaisesRegex(ValueError, error):
                    self.calculate()

    def test_foreign_right_requires_chief_bound_local_effect(self):
        self.patent()
        self.rows(jurisdiction='GB')
        with self.assertRaisesRegex(ValueError, 'TERRITORIAL_EFFECT_CONFLICT'):
            self.calculate()
        self.rows(applicability_exception={'kind': 'territorial_effect', 'reasoning': 'Identified target-country right and documented effect', 'evidence_refs': ['EV-PROV']})
        with self.assertRaisesRegex(ValueError, 'REQUIRES_CHIEF'):
            self.calculate()
        self.assertEqual(self.calculate(adjudication=self.chief())['overall']['risk'], '高')

    def test_copyright_is_not_excluded_by_author_geography(self):
        self.rows(jurisdiction='GB')
        self.assertEqual(self.calculate()['overall']['risk'], '高')

    def test_ep_family_does_not_establish_current_country_effect(self):
        self.patent()
        candidate = self.values[2]['patents'][0]
        candidate.update(jurisdiction='WO', publication_number='WO2026123456A1', family_members=['EP1234567A1'])
        self.values[4]['annotations'][0]['candidate_identity_fingerprint'] = candidate_identity_fingerprint('patents', candidate)
        apply_materiality_annotations(self.values[4], self.values[0]['task_id'], self.values[2])
        self.rows(jurisdiction='GB')
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'TERRITORIAL_EFFECT_CONFLICT'):
            self.calculate()

    def test_known_inactive_state_and_documented_exception(self):
        self.patent()
        for state in ('pending', 'expired', 'abandoned'):
            self.rows(right_state=state)
            with self.assertRaisesRegex(ValueError, 'CURRENT_RISK_CONTRADICTS'):
                self.calculate()
        self.rows(applicability_exception={'kind': 'current_enforceability', 'reasoning': 'Evidence of restoration affecting evaluated conduct', 'evidence_refs': ['EV-PROV']})
        with self.assertRaisesRegex(ValueError, 'REQUIRES_CHIEF'):
            self.calculate()
        self.assertEqual(self.calculate(adjudication=self.chief())['overall']['risk'], '高')

    def test_unknown_keeps_grade_and_expiry_supports_scoped_exclusion(self):
        self.patent()
        self.rows(right_state='unknown')
        result = self.calculate()
        self.assertEqual((result['overall']['risk'], result['overall']['confidence']), ('高', '低'))
        self.rows(right_state='expired', risk='极低', decisive_exclusion={'reasoning': 'Documented expiry of this candidate', 'evidence_refs': ['EV-PROV']})
        result = self.calculate()
        self.assertEqual((result['assessments'][0]['risk'], result['assessments'][0]['evidence_confidence']), ('极低', '高'))
        self.assertEqual(result['overall']['risk'], '低')

    def test_structured_disagreement_and_agreed_missing_basis(self):
        self.values[-1]['assessments'][0]['confidence_basis']['identity'].update(satisfied=False, evidence_refs=[])
        with self.assertRaisesRegex(ValueError, 'ADJUDICATION_REQUIRED.*confidence_basis:identity'):
            self.calculate()
        self.assertEqual(self.calculate(adjudication=self.chief())['overall']['risk'], '高')
        self.values[-2]['assessments'][0]['confidence_basis']['identity'].update(satisfied=False, evidence_refs=[])
        result = self.calculate()
        self.assertEqual((result['overall']['risk'], result['overall']['confidence']), ('高', '低'))
        self.rows(risk='极低', decisive_exclusion={'reasoning': 'Claimed exclusion', 'evidence_refs': ['EV-PROV']})
        self.assertEqual(self.calculate()['assessments'][0]['evidence_confidence'], '低')

    def test_scope_exclusion_frozen_and_does_not_hide_known_candidate(self):
        row = {'jurisdiction': 'GB', 'right_type': 'copyright', 'candidate_id': '', 'module_id': 'copyright_ip', 'title': 'GB excluded', 'out_of_scope': True, 'risk': None, 'scope_reasoning': 'Declared task boundary'}
        for review in self.values[-2:]:
            review['assessments'].append(deepcopy(row))
        with self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_NOT_BOUND'):
            self.calculate()
        self.values[0]['assessment_scope_exclusions'] = [{'jurisdiction': 'GB', 'right_type': 'copyright', 'candidate_id': '', 'reasoning': 'Only US artwork evaluated'}]
        with self.assertRaisesRegex(ValueError, 'REVIEW_CONTEXT_INVALID'):
            self.calculate()
        self.refresh()
        result = self.calculate()
        gb = next(scope for scope in result['coverage']['scopes'] if (scope['jurisdiction'], scope['right_type']) == ('GB', 'copyright'))
        self.assertIn('CANDIDATE_ASSESSMENT_MISSING:C-ART', gb['gaps'])
        self.assertNotIn('SCOPE_ASSESSMENT_MISSING', gb['gaps'])

    def test_unknown_brand_semantics_reject_known_brand(self):
        row = {'jurisdiction': 'US', 'right_type': 'trademark_word', 'candidate_id': '', 'module_id': 'word_mark', 'title': 'Own brand', 'out_of_scope': True, 'risk': None, 'scope_exclusion_basis': 'unknown_own_brand', 'scope_reasoning': 'Name not supplied'}
        for review in self.values[-2:]:
            review['assessments'].append(deepcopy(row))
        for supplied in ({'own_brand_name': 'Known name'}, {'own_logo': 'retained logo'}, {'brand_role': 'own', 'brand': 'Known'}, {'brand_role': 'own', 'logo': 'Known'}):
            with self.subTest(supplied=supplied):
                self.values[0]['product'].update(supplied)
                self.refresh()
                with self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_NOT_BOUND'):
                    self.calculate()
                for key in supplied:
                    self.values[0]['product'].pop(key)
        self.values[0]['product'].update(brand_role='reference', brand='Competitor')
        self.refresh()
        self.assertEqual(self.calculate()['overall']['risk'], '高')

    def test_zero_complete_queries_limit_negative_scope_confidence(self):
        modules = {'patent': 'utility_patent', 'utility_model': 'utility_patent', 'design': 'appearance_patent', 'unregistered_design': 'appearance_patent', 'copyright': 'copyright_ip', 'trade_dress': 'figurative_trade_dress', 'trademark_word': 'word_mark', 'trademark_figurative': 'figurative_trade_dress'}
        scopes = {(q['jurisdiction'], q['right_type']) for q in self.values[0]['coverage_requirements'] if q['right_type'] != 'enforcement'}
        rows = []
        for jur, right in scopes:
            row = deepcopy(self.values[-2]['assessments'][0])
            row.update(jurisdiction=jur, right_type=right, candidate_id='C-ART' if right == 'copyright' else '', module_id=modules[right], risk='低', evidence_confidence='高', supporting_evidence=[], no_supporting_evidence_reasoning='No specific threat found')
            row.pop('confidence_basis'); row.pop('comparison')
            rows.append(row)
        for review in self.values[-2:]:
            review.update(assessments=deepcopy(rows), coverage_confidence_cap='高')
        result = self.calculate()
        self.assertEqual((result['overall']['risk'], result['overall']['confidence']), ('低', '低'))
        self.assertTrue(all(row['evidence_confidence'] == '低' for row in result['assessments'] if not row['candidate_id']))

    def test_module_caps_are_canonical_optional_and_review_bound(self):
        self.assertNotIn('module_confidence_caps', self.calculate())
        caps = {'copyright_ip': {'confidence': '低', 'reasoning': 'Ownership ambiguity affects module'}}
        chief = self.chief(decision=False, module_confidence_caps=caps)
        del chief['review_refs']
        with self.assertRaisesRegex(ValueError, 'GLOBAL_ADJUDICATION_REVIEW_BINDING'):
            self.calculate(adjudication=chief)
        result = self.calculate(adjudication=self.chief(decision=False, module_confidence_caps=caps))
        self.assertEqual(result['module_confidence_caps'], caps)
        self.assertEqual(result['overall']['confidence'], '低')
        self.assertEqual(result['overall']['report_lead'], '高风险／低置信度')
        self.assertEqual(result['overall']['report_summary'], ' '.join(result['overall']['reasons']))

    def complete_product_text_fixture(self):
        task, evidence, candidates, plan, _, first, second = self.values
        scopes = {(q['jurisdiction'], q['right_type']) for q in task['coverage_requirements'] if q['right_type'] != 'enforcement'}
        task['assessment_scope_exclusions'] = [
            {'jurisdiction': jur, 'right_type': right, 'candidate_id': '', 'reasoning': 'This test explicitly evaluates only retained US artwork and product text'}
            for jur, right in scopes - {('US', 'copyright'), ('US', 'trademark_word')}]
        task['assessment_scope_exclusions'].append({'jurisdiction': 'GB', 'right_type': 'copyright', 'candidate_id': 'C-ART', 'reasoning': 'Only US use is evaluated'})
        provider = 'uspto_tmsearch_browser'
        plan['queries'][provider] = []
        evidence['collections']['trademarks'] = []
        for axis in ('text', 'phonetic'):
            query = {'query_id': 'TM-' + axis, 'q': 'retained product words', 'operation': 'trademark_recall', 'jurisdiction': 'US', 'right_type': 'trademark_word',
                     'requirement_ids': ['COV-US-TRADEMARK_WORD-RECALL'], 'search_dimension': axis, 'search_language': 'en', 'execution_phase': 'initial'}
            run = {'run_id': 'RUN-' + axis, 'provider': provider, 'status': 'no_result', **query, 'source_environment': 'production', 'authoritative_for_final_rating': True,
                   'plan_entry_sha256': sha256_json(query), 'metadata': {'search_coverage': {'schema_valid': True, 'total_hits': 0, 'retrieved_hits': 0, 'truncated': False, 'stop_reason': 'explicit_zero'}}}
            entry = {'evidence_id': 'EV-' + axis, 'source_run_id': run['run_id'], 'payload': {'candidates': []},
                     **{key: run[key] for key in ('provider', 'query_id', 'operation', 'jurisdiction', 'right_type', 'requirement_ids', 'plan_entry_sha256')}}
            plan['queries'][provider].append(query)
            evidence['source_runs'].append(run)
            evidence['collections']['trademarks'].append(entry)
        product = deepcopy(first['assessments'][0])
        product.update(candidate_id='', right_type='trademark_word', module_id='word_mark', title='Already reviewed product words', scope='Visible product words only', risk='低',
                       supporting_evidence=[], no_supporting_evidence_reasoning='Completed text and phonetic searches found no specific threat', evidence_refs=['EV-text', 'EV-phonetic', 'EV-PRODUCT'])
        for key in ('comparison', 'confidence_basis', 'findings'):
            product.pop(key, None)
        for review in (first, second):
            review['assessments'][0]['risk'] = '低'
            review['assessments'].append(deepcopy(product))
            review['coverage_confidence_cap'] = '高'
        self.refresh()
        self.assertEqual((self.calculate()['overall']['risk'], self.calculate()['overall']['confidence']), ('低', '高'))

    def add_unknown_own_brand(self):
        unknown = {'jurisdiction': 'US', 'right_type': 'trademark_word', 'candidate_id': '', 'module_id': 'word_mark', 'title': 'Own brand not supplied',
                   'out_of_scope': True, 'risk': None, 'scope_exclusion_basis': 'unknown_own_brand', 'scope_reasoning': 'Future own brand name is outside reviewed product text'}
        for review in self.values[-2:]:
            review['assessments'].append(deepcopy(unknown))

    def test_unknown_brand_coexists_without_lowering_reviewed_product_confidence(self):
        self.complete_product_text_fixture()
        self.add_unknown_own_brand()
        result = self.calculate()
        self.assertEqual((result['overall']['risk'], result['overall']['confidence']), ('低', '高'))
        tm = [row for row in result['assessments'] if row['right_type'] == 'trademark_word']
        self.assertEqual({row['assessment_object'] for row in tm}, {'product', 'own_brand'})
        self.assertEqual(len(tm), 2)

    def test_unknown_brand_does_not_replace_product_text_review(self):
        self.complete_product_text_fixture()
        for review in self.values[-2:]:
            review['assessments'] = [row for row in review['assessments'] if row['right_type'] != 'trademark_word']
        self.add_unknown_own_brand()
        result = self.calculate()
        self.assertEqual((result['overall']['risk'], result['overall']['confidence']), ('低', '低'))
        tm = next(scope for scope in result['coverage']['scopes'] if (scope['jurisdiction'], scope['right_type']) == ('US', 'trademark_word'))
        self.assertIn('SCOPE_ASSESSMENT_MISSING', tm['gaps'])


class StrictSourceLineageTests(unittest.TestCase):
    def setUp(self):
        helper = legacy_tests.SearchCoverageTests()
        helper.setUp()
        self.evidence, self.plan, self.query = helper.evidence, helper.plan, helper.query
        run = self.evidence['source_runs'][0]
        run['status'] = 'success'
        run['metadata']['search_coverage'].update(total_hits=1, retrieved_hits=1, truncated=False, stop_reason='all_results_read')
        self.raw = {'publication_number': 'US1111111B1', 'application_number': 'US/123', 'jurisdiction': 'US', 'right_type': 'patent'}
        self.evidence['collections']['patents'][0]['payload']['candidates'] = [self.raw]
        self.candidate = {'candidate_id': 'NORMALIZED', 'publication_number': 'US9999999B1', 'application_number': 'US/123', 'jurisdiction': 'US', 'right_type': 'patent', 'query_id': 'Q', 'material': False}
        self.candidates = {'patents': [self.candidate]}
        self.annotate()

    def annotate(self):
        ledger = empty_materiality_ledger('T')
        ledger['annotations'] = [{'annotation_id': 'MAT', 'candidate_id': 'NORMALIZED', 'candidate_identity_fingerprint': candidate_identity_fingerprint('patents', self.candidate), 'material': False, 'decision': 'excluded', 'material_reason': 'Compared specific source document', 'reviewer': 'reviewer', 'annotated_at': now_iso()}]
        apply_materiality_annotations(ledger, 'T', self.candidates)

    def test_publication_identity_not_query_or_application(self):
        legacy = query_coverage(self.evidence, self.candidates, self.plan, 'epo_ops', self.query)
        strict = query_coverage(self.evidence, self.candidates, self.plan, 'epo_ops', self.query, strict_lineage=True)
        self.assertTrue(legacy['complete'])
        self.assertFalse(strict['complete'])
        self.assertEqual(strict['gap'], 'SOURCE_RECORD_IDENTITY_NOT_ACCOUNTED_FOR')

    def test_exact_identity_survives_formatting_and_deduplication(self):
        self.candidate['publication_number'] = 'US 1111111 B1'
        self.annotate()
        self.evidence['collections']['patents'][0]['payload']['candidates'].append(deepcopy(self.raw))
        self.evidence['source_runs'][0]['metadata']['search_coverage'].update(total_hits=2, retrieved_hits=2)
        strict = query_coverage(self.evidence, self.candidates, self.plan, 'epo_ops', self.query, strict_lineage=True)
        self.assertTrue(strict['complete'])
        self.assertEqual(strict['reviewed_candidates'], 1)

    def test_pagination_cannot_complete_with_wrong_reviewed_records(self):
        task = {'coverage_requirements': [{'requirement_id': 'COV', 'jurisdiction': 'US', 'right_type': 'patent', 'phase': 'official_recall',
                'required_axes': ['text'], 'routes': [{'provider': 'epo_ops', 'operation': 'search'}]}]}
        plan, evidence, candidates = {'queries': {'epo_ops': []}}, {'source_runs': [], 'collections': {'patents': []}}, {'patents': []}
        ledger = empty_materiality_ledger('T')
        for page in (1, 2):
            query = {**self.query, 'q': 'hinged device', 'query_id': 'Q' + str(page), 'range': f'{page}-{page}'}
            run = {'run_id': 'R' + str(page), 'provider': 'epo_ops', 'status': 'success', **query, 'plan_entry_sha256': sha256_json(query),
                   'source_environment': 'production', 'authoritative_for_final_rating': True,
                   'metadata': {'search_coverage': {'schema_valid': True, 'total_hits': 2, 'retrieved_hits': 1, 'truncated': True, 'stop_reason': 'page_limit'}}}
            candidate = {'candidate_id': 'C' + str(page), 'publication_number': 'US100' + str(page) + 'B1', 'jurisdiction': 'US', 'right_type': 'patent', 'material': False, 'evidence_refs': ['E' + str(page)]}
            entry = {'evidence_id': 'E' + str(page), 'source_run_id': run['run_id'], 'payload': {'candidates': [deepcopy(candidate)]},
                     **{key: run[key] for key in ('provider', 'query_id', 'operation', 'jurisdiction', 'right_type', 'requirement_ids', 'plan_entry_sha256')}}
            plan['queries']['epo_ops'].append(query)
            evidence['source_runs'].append(run)
            evidence['collections']['patents'].append(entry)
            candidates['patents'].append(candidate)
            ledger['annotations'].append({'annotation_id': 'M' + str(page), 'candidate_id': candidate['candidate_id'], 'candidate_identity_fingerprint': candidate_identity_fingerprint('patents', candidate), 'material': False, 'decision': 'excluded', 'material_reason': 'Different structure', 'reviewer': 'agent', 'annotated_at': now_iso()})
        apply_materiality_annotations(ledger, 'T', candidates)
        self.assertEqual(coverage_by_scope(task, evidence, candidates, plan, strict_lineage=True)[0]['status'], '满足已定义要求')
        evidence['collections']['patents'][1]['payload']['candidates'][0]['publication_number'] = 'US9999B1'
        self.assertEqual(coverage_by_scope(task, evidence, candidates, plan)[0]['status'], '满足已定义要求')
        strict = coverage_by_scope(task, evidence, candidates, plan, strict_lineage=True)[0]
        self.assertNotEqual(strict['status'], '满足已定义要求')
        self.assertTrue(any(query['gap'] == 'SOURCE_RECORD_IDENTITY_NOT_ACCOUNTED_FOR' for query in strict['queries']))
