"""Regression checks for keyword intent review and quarantine, without network."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from keyword_fixtures import keywords as k, make_run, classify, write, ROOT


class KeywordQualityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.run = Path(temp.name)
        self.profile, self.ledger = make_run(self.run)

    def save(self):
        write(self.run, k.DECISIONS, self.ledger)

    def result(self, export=False, downstream=False):
        self.save()
        return k.check_run(self.run, require_exports=export, downstream=downstream)

    def codes(self):
        return {i['code'] for i in self.result()['issues']}

    def find(self, text):
        return next(r for r in self.ledger['records'] if r['keyword'] == text)

    def export(self):
        self.save()
        self.assertEqual(k.main(['export', '--run-dir', str(self.run)]), 0)

    def test_word_boundaries_and_full_phrase_signal(self):
        for word, phrase in [('bathroom', 'bat'), ('lightweight', 'light'), ('design', 'sign'), ('category', 'cat')]:
            self.assertFalse(k.contains_phrase(word, phrase))
        self.assertTrue(k.contains_phrase('black cat door corner', 'cat door'))  # A signal, not a rejection.
        self.assertTrue(k.contains_phrase('bat wall decor', 'bat'))
        self.assertTrue(k.contains_phrase('猫咪门角装饰', '门角'))

    def test_normalization_preserves_meaning_and_deduplicates_only_safe_forms(self):
        self.assertEqual(k.norm(' Cat’s  Topper '), k.norm("cat's topper"))
        self.assertNotEqual(k.norm('cat door corner'), k.norm('corner door cat'))
        self.assertNotEqual(k.norm('7.5 in'), k.norm('75 in'))
        self.assertNotEqual(k.norm('not waterproof'), k.norm('waterproof'))
        self.assertNotEqual(k.norm('café'), k.norm('cafe'))
        result = self.result()
        self.assertEqual(result['status'], 'passed', result)
        counts = result['counts']
        self.assertEqual(counts['duplicates'], 2)
        self.assertEqual(counts['raw_records'], counts['unique'] + counts['duplicates'])
        self.assertEqual(counts['unique'], sum(counts[x] for x in k.DECISION_CODES))

    def test_prepare_is_unreviewed_and_does_not_overwrite(self):
        with self.assertRaises(ValueError):
            k.prepare(self.run)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, k.PROFILE, self.profile); write(root, k.RAW, {'keywords': ['bathroom']})
            ledger = k.prepare(root)
            self.assertTrue(all(r['decision'] is None for r in k.all_records(ledger)))
            self.assertEqual(k.check_run(root)['status'], 'incomplete')
            self.assertTrue(ledger['supplemental_terms'])

    def test_cannot_use_substrings_or_closed_allowlist_as_reason(self):
        record = self.find('nosy black cat bathroom door topper')
        record['matched_terms'] = ['bat']
        self.assertIn('keyword_substring_match', self.codes())
        record['matched_terms'] = []
        record['initial_decision'] = record['decision'] = 'excluded'
        record['reason_code'] = 'not_in_whitelist'
        self.assertIn('keyword_reason_code', self.codes())

    def test_missing_duplicate_extra_and_reordered_words_are_errors(self):
        original = copy.deepcopy(self.ledger)
        for mutate in (lambda: self.ledger['records'].pop(),
                       lambda: self.ledger['records'].append(copy.deepcopy(self.ledger['records'][0])),
                       lambda: self.ledger['records'].reverse(),
                       lambda: self.ledger['records'][0].update(keyword='invented keyword')):
            self.ledger = copy.deepcopy(original); mutate()
            self.assertIn('keyword_coverage', self.codes())

    def test_original_and_supplemental_cannot_duplicate_to_bypass_quarantine(self):
        item = copy.deepcopy(self.find('cat iron wall decoration'))
        item.update(origin='product', source_ref='unverified invented source', keyword_id='product-'+k.digest(k.norm(item['keyword']))[:20])
        classify(item)
        self.ledger['supplemental_terms'].append(item)
        self.assertIn('keyword_duplicate', self.codes())

    def test_excluded_words_pass_without_second_review_file(self):
        self.assertFalse((self.run/'03_keyword_review.json').exists())
        self.assertEqual(self.result()['status'], 'passed')
        self.export()
        result = self.result(export=True)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['counts']['excluded'], 2)
        self.assertNotIn('reviewed_exclusions', result['counts'])
        self.assertEqual(result['review_policy'], 'final_usage_only')

    def test_legacy_review_neither_blocks_nor_changes_classification(self):
        self.export()
        before = self.result(export=True)
        (self.run/'03_keyword_review.json').write_text('{broken archived json')
        self.assertEqual(self.result(export=True), before)
        write(self.run, '03_keyword_review.json', {'records':[{'keyword_id':self.find('microchip cat door')['keyword_id'], 'conclusion':'eligible', 'reason':'old or invalid decision'}]})
        self.assertEqual(self.result(export=True), before)
        self.assertNotIn('microchip cat door', k.read_json(self.run/k.POOLS['eligible']))

    def test_changed_classification_uses_current_reason_and_resolution(self):
        record = self.find('microchip cat door')
        record.update(decision='deferred', reason_code='ambiguous_intent',
                      reason='Retain the exact compatibility ambiguity for later evaluation.',
                      resolution='Reclassified after checking the complete query.')
        self.assertEqual(self.result()['status'], 'passed')
        self.export()
        pending = next(r for r in k.read_json(self.run/k.POOLS['deferred']) if r['keyword']=='microchip cat door')
        self.assertEqual(pending['reason'], record['reason'])
        self.assertEqual(pending['reason_code'], 'ambiguous_intent')
        record['reason_code'] = 'product_mismatch'
        self.assertIn('keyword_reason_code', self.codes())
        record['reason_code'] = 'ambiguous_intent'
        record['resolution'] = ''
        self.assertIn('keyword_resolution', self.codes())

    def test_legacy_ledger_requires_current_reason_not_a_review_file(self):
        self.ledger['keyword_schema_version'] = '1.0'
        self.assertEqual(self.result()['status'], 'passed')
        record = self.find('microchip cat door')
        record.update(decision='deferred', resolution='Changed intent classification.')
        self.assertIn('keyword_reason_code', self.codes())
        record['reason_code'] = 'ambiguous_intent'
        self.assertEqual(self.result()['status'], 'passed')

    def test_unknown_material_and_seasonal_use_stay_deferred_without_blocking(self):
        self.assertEqual(self.result()['status'], 'passed')
        record = self.find('cat iron wall decoration')
        record['initial_decision'] = record['decision'] = 'eligible'; record['reason_code'] = 'attribute'
        self.assertIn('keyword_unknown_fact', self.codes())

    def test_confirmed_seasonal_context_can_be_eligible(self):
        self.profile['facts'].append({'fact_id': 'season', 'value': 'Halloween', 'status': 'confirmed', 'source_ref': 'synthetic seasonal design'})
        write(self.run, k.PROFILE, self.profile)
        self.ledger['source_fingerprints'] = k.fingerprints(self.run, (k.PROFILE, k.RAW))
        classify(self.find('halloween black cat decor'), 'eligible', 'intent', ['season'])
        self.save()
        self.assertEqual(self.result()['status'], 'passed')

    def test_same_intent_different_disposition_needs_explanation(self):
        self.find('black cat door sign')['intent_group'] = 'door-frame-cat'
        self.assertIn('keyword_intent_conflict', self.codes())
        for r in k.all_records(self.ledger):
            if r['intent_group'] == 'door-frame-cat':
                r['group_difference'] = 'Sign may imply a printed plaque; the other queries describe a silhouette topper.'
        self.assertEqual(self.result()['status'], 'passed')

    def test_core_name_missing_or_dropped_cannot_pass(self):
        self.ledger['supplemental_terms'] = []
        self.assertIn('keyword_protected_missing', self.codes())

    def test_unknown_fact_cannot_be_used_as_confirmed_counterevidence(self):
        record=self.find('cat iron wall decoration')
        record.update(initial_decision='excluded',decision='excluded',reason_code='fact_conflict')
        self.assertIn('keyword_unknown_is_not_conflict',self.codes())

    def test_non_ascii_query_and_invented_user_ban_cannot_be_hard_deleted(self):
        record=self.find('猫咪门角装饰')
        record.update(initial_decision='excluded',decision='excluded',reason_code='unusable_query')
        self.assertIn('keyword_unusable_query',self.codes())
        record['reason_code']='user_restriction'
        self.assertIn('keyword_restriction_basis',self.codes())

    def test_empty_exclusion_reason_still_blocks_classification(self):
        self.find('microchip cat door')['reason'] = ''
        self.assertIn('keyword_basis_missing', self.codes())

    def test_missing_scope_and_invalid_variant_in_placement_are_rejected(self):
        entry={'keyword':'black cat door corner','target_field':'search_terms','reason':'test'}
        self.assertTrue(k.check_usage(self.profile,self.ledger,{'placement_plan':[entry]}))
        entry['applies_to']=['made-up-variant']
        self.assertTrue(k.check_usage(self.profile,self.ledger,{'placement_plan':[entry]}))

    def test_attribute_needs_fact_not_only_name(self):
        self.find('metal black cat silhouette')['role']='attribute'
        self.assertIn('keyword_attribute_evidence',self.codes())
        self.find('metal black cat silhouette')['fact_ids']=['metal']
        self.assertEqual(self.result()['status'],'passed')

    def test_variant_evidence_cannot_be_promoted_or_crossed(self):
        self.profile.update(listing_mode='family', variants=[{'variant_id': 'blue', 'facts': [{'fact_id': 'blue', 'value': 'Blue', 'status': 'confirmed', 'source_ref': 'SKU blue'}]}, {'variant_id': 'red', 'facts': []}])
        write(self.run, k.PROFILE, self.profile)
        self.ledger['source_fingerprints'] = k.fingerprints(self.run, (k.PROFILE, k.RAW))
        self.find('metal black cat silhouette').update(fact_ids=['blue'], applies_to=['all'])
        self.save()
        self.assertIn('keyword_fact_scope', self.codes())
        self.find('metal black cat silhouette')['applies_to'] = ['red']
        self.assertIn('keyword_fact_scope', self.codes())
        self.find('metal black cat silhouette')['applies_to'] = ['blue']
        self.assertEqual(self.result()['status'], 'passed')
        entry = {'keyword': 'metal black cat silhouette', 'target_field': 'shared_content.search_terms', 'applies_to': ['all'], 'reason': 'test'}
        self.assertTrue(k.check_usage(self.profile, self.ledger, {'placement_plan': [entry]}))

    def test_export_is_the_only_source_of_pools_and_metrics_are_not_invented(self):
        self.export()
        result = self.result(export=True)
        self.assertEqual(result['status'], 'passed', result)
        tags = k.read_json(self.run/'04_kw_tagged.json')
        self.assertEqual(tags[0]['searches'], 0)
        self.assertTrue(all(x['searches'] is None for x in tags if x['origin'] == 'product'))
        self.assertIn('猫咪门角装饰', k.read_json(self.run/k.POOLS['eligible']))
        write(self.run, k.POOLS['eligible'], ['invented'])
        self.assertEqual(self.result(export=True)['status'], 'failed')

    def test_failed_export_preserves_existing_pools(self):
        self.export(); before = (self.run/k.POOLS['eligible']).read_bytes()
        self.ledger['records'].pop(); self.save()
        self.assertEqual(k.main(['export', '--run-dir', str(self.run)]), 1)
        self.assertEqual(before, (self.run/k.POOLS['eligible']).read_bytes())

    def test_deferred_and_excluded_cannot_enter_candidates_qa_or_placements(self):
        for word in ('cat iron wall decoration', 'microchip cat door', 'not in ledger'):
            for kwargs in ({'title_keywords': {'title_keywords': {'high': [word]}}},
                           {'qa': {'requested_keywords': [word]}},
                           {'title_keywords': {'placement_plan': [{'keyword': word, 'target_field': 'search_terms', 'applies_to': ['all'], 'reason': 'test'}]}}):
                self.assertTrue(k.check_usage(self.profile, self.ledger, **kwargs))

    def test_backend_terms_cannot_leak_quarantined_phrases(self):
        for word in ('cat iron wall decoration', 'microchip cat door'):
            self.assertTrue(k.check_usage(self.profile, self.ledger, listing={'search_terms': 'decor '+word+' shelf'}))
        # Do not recreate the fragment error: a reviewed complete query covers its shorter ambiguous substring.
        record = k.draft({'keyword_id':'product-'+k.digest('cat door')[:20], 'keyword':'cat door', 'normalized':'cat door', 'source_ref':'test ambiguous phrase'}, 'product')
        classify(record, 'deferred', 'ambiguous_intent'); record['intent_group']='ambiguous-cat-door'
        self.ledger['supplemental_terms'].append(record)
        self.assertFalse(k.check_usage(self.profile, self.ledger, listing={'search_terms': 'black cat door corner'}))

    def test_missing_legacy_audit_and_cached_pass_cannot_pass(self):
        (self.run/k.DECISIONS).unlink()
        write(self.run, k.VALIDATION, {'status':'passed'})
        self.assertEqual(k.check_run(self.run)['status'], 'incomplete')

    def test_profile_raw_and_downstream_changes_are_checked_again(self):
        self.export()
        write(self.run, '05_title_keywords.json', {'title_keywords': {'high': ['cat iron wall decoration']}})
        self.assertEqual(self.result(export=True, downstream=True)['status'], 'failed')
        (self.run/k.RAW).write_text((self.run/k.RAW).read_text()+'\n')
        self.assertIn('keyword_source_stale', self.codes())

    def test_cli_malformed_input_returns_nonzero_without_traceback(self):
        write(self.run, k.DECISIONS, {'records':None})
        process=subprocess.run([sys.executable,str(ROOT/'scripts/keyword_quality.py'),'check','--run-dir',str(self.run)],capture_output=True,text=True)
        self.assertEqual(process.returncode,1)
        self.assertNotIn('Traceback',process.stderr)
        self.assertNotEqual(k.read_json(self.run/k.VALIDATION)['status'],'passed')


if __name__ == '__main__':
    unittest.main()
