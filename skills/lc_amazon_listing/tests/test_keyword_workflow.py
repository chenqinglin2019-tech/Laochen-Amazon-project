"""Real local command/report integration; backend records are explicit test doubles."""
import contextlib
import copy
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from keyword_fixtures import keywords as k, make_run, classify, write, ROOT
from test_listing_quality import quality, single_fixture
from test_render_listing import renderer, ScriptCollector


def completed_run(root):
    profile, listing, qa = single_fixture()
    _, ledger = make_run(root, profile, ['Pen Holder', 'stationery organizer', 'iron pen holder', 'electronic pet flap'])
    for record in k.all_records(ledger):
        record.update(query_intent='寻找桌面文具收纳用品', reason='测试产品身份为笔筒，支持书写工具收纳意图。',
                      evidence='synthetic product_identity and specification', intent_group='writing-tool-storage')
    for word, decision, code in [('iron pen holder', 'deferred', 'unknown_fact'), ('electronic pet flap', 'excluded', 'product_mismatch')]:
        record=next(r for r in ledger['records'] if r['keyword']==word)
        classify(record,decision,code)
        record.update(intent_group=word,query_intent=word,reason='按完整搜索对象核对：铁材质未知；电子宠物通道与笔筒不同。',evidence='synthetic pen-holder identity and stainless-steel specification')
    write(root,k.DECISIONS,ledger)
    with contextlib.redirect_stdout(io.StringIO()):
        assert k.main(['export','--run-dir',str(root)])==0
    write(root,'07_listing.json',listing);write(root,'06_qa.json',qa)
    write(root,'05_title_keywords.json',{'title_keywords':{'high':['Pen Holder'],'relevant':['stationery organizer']},
          'protected_terms':['Pen Holder'],'placement_plan':[{'keyword':'Pen Holder','target_field':'title','applies_to':['all'],'reason':'Preserve product identity'},
          {'keyword':'stationery organizer','target_field':'search_terms','applies_to':['all'],'reason':'Related storage synonym'}]})
    review=quality.make_review_template(root/k.PROFILE,root/'07_listing.json',root/'06_qa.json')
    for record in review['records']:
        record.update(status='pass',evidence='Explicit synthetic test review against supplied pen-holder fixture; not a real product certification.')
    write(root,'08_semantic_review.json',review)
    backend={'records':[{'target':p['target'],'payload_sha256':p['payload_sha256'],'exit_code':0,'response':{'ok':True,'errors':[]}} for p in quality.build_payloads(profile,listing)]}
    write(root,'08_backend_validation.json',backend)
    return profile,listing,qa,review,backend


class KeywordWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.run=Path(temp.name)
        self.profile,self.listing,self.qa,self.review,self.backend=completed_run(self.run)

    def validate_cli(self):
        args=[sys.executable,str(ROOT/'scripts/listing_quality.py'),'check','--profile',str(self.run/k.PROFILE),'--listing',str(self.run/'07_listing.json'),
              '--qa',str(self.run/'06_qa.json'),'--review',str(self.run/'08_semantic_review.json'),'--backend',str(self.run/'08_backend_validation.json'),'--output',str(self.run/'08_validation.json')]
        result=subprocess.run(args,capture_output=True,text=True)
        return result,k.read_json(self.run/'08_validation.json')

    def test_real_cli_and_report_complete_with_deferred_pool(self):
        result,validation=self.validate_cli()
        self.assertEqual(result.returncode,0,(result.stderr,validation))
        self.assertEqual(validation['keywords']['status'],'passed')
        self.assertFalse((self.run/'03_keyword_review.json').exists())
        self.assertEqual(validation['keywords']['counts']['deferred'],1)
        md,page,status=renderer.build_report(self.run)
        self.assertEqual(status,'passed')
        parsed=ScriptCollector();parsed.feed(page)
        self.assertEqual(json.loads(parsed.values['data-kw-pending'])[0]['keyword'],'iron pen holder')
        self.assertEqual(json.loads(parsed.values['data-keyword-audit'])['status'],'passed')
        self.assertIn('查看待评估词',page)
        self.assertNotIn('iron pen holder',md)
        self.assertEqual(sum(tag=='section' and attrs.get('class')=='chapter' for tag,attrs in parsed.tags),7)
        self.assertFalse(any(tag in ('nav','pre','details') for tag,_ in parsed.tags))

    def test_report_never_trusts_cached_pass_after_ledger_disappears(self):
        self.validate_cli();(self.run/k.DECISIONS).unlink()
        write(self.run,k.VALIDATION,{'status':'passed'})
        _,_,status=renderer.build_report(self.run)
        self.assertEqual(status,'incomplete')
        result,validation=self.validate_cli()
        self.assertEqual(result.returncode,1)
        self.assertEqual(validation['keywords']['status'],'incomplete')

    def test_pool_tampering_invalidates_cli_and_report(self):
        self.validate_cli();write(self.run,k.POOLS['eligible'],['Pen Holder','iron pen holder'])
        _,validation=self.validate_cli()
        self.assertEqual(validation['status'],'failed')
        self.assertEqual(renderer.build_report(self.run)[2],'failed')

    def test_changed_ledger_needs_fresh_keyword_usage_review(self):
        self.validate_cli()
        ledger=k.read_json(self.run/k.DECISIONS);ledger['records'][0]['reason']='Refined supported storage intent.'
        write(self.run,k.DECISIONS,ledger)
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(k.main(['export','--run-dir',str(self.run)]),0)
        _,validation=self.validate_cli()
        self.assertEqual(validation['keywords']['status'],'passed')
        self.assertEqual(validation['status'],'incomplete')
        self.assertIn('review_keywords_stale',{issue['code'] for issue in validation['issues']})

    def test_missing_or_failed_final_keyword_usage_review_cannot_pass(self):
        for status in ('pending', 'fail'):
            review = copy.deepcopy(self.review)
            next(r for r in review['records'] if r['check']=='keyword_usage')['status'] = status
            write(self.run,'08_semantic_review.json',review)
            result, validation = self.validate_cli()
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(validation['keywords']['status'],'passed')
            self.assertNotEqual(renderer.build_report(self.run)[2],'passed')
        review = copy.deepcopy(self.review)
        review['records'] = [r for r in review['records'] if r['check']!='keyword_usage']
        write(self.run,'08_semantic_review.json',review)
        self.assertNotEqual(self.validate_cli()[0].returncode,0)

    def test_archived_rejection_review_does_not_invalidate_final_review_or_report(self):
        self.validate_cli()
        before = quality.current_keyword_stage(self.run)
        (self.run/'03_keyword_review.json').write_text('{invalid legacy archive')
        self.assertEqual(quality.current_keyword_stage(self.run),before)
        self.assertEqual(self.validate_cli()[0].returncode,0)
        self.assertEqual(renderer.build_report(self.run)[2],'passed')

    def test_legacy_semantic_extra_fingerprint_is_ignored(self):
        review = copy.deepcopy(self.review)
        review['keyword_fingerprints']['03_keyword_review.json'] = 'historical-hash'
        write(self.run,'08_semantic_review.json',review)
        self.assertEqual(self.validate_cli()[0].returncode,0)

    def test_title_qa_and_backend_leak_prevent_total_success(self):
        for filename,mutate in [('05_title_keywords.json',lambda x:x['title_keywords']['high'].append('iron pen holder')),
                                ('06_qa.json',lambda x:x['requested_keywords'].append('iron pen holder')),
                                ('07_listing.json',lambda x:x.update(search_terms='iron pen holder'))]:
            original=(self.run/filename).read_bytes();value=k.read_json(self.run/filename);mutate(value);write(self.run,filename,value)
            _,validation=self.validate_cli()
            self.assertEqual(validation['keywords']['status'],'failed',filename)
            self.assertNotEqual(renderer.build_report(self.run)[2],'passed')
            (self.run/filename).write_bytes(original)

    def test_keyword_stage_cannot_be_reused_for_other_listing_inputs(self):
        stage=quality.current_keyword_stage(self.run)
        fp=quality.file_fingerprints(self.run/k.PROFILE,self.run/'07_listing.json',self.run/'06_qa.json')
        fp['listing_sha256']='another-copy'
        result=quality.validate_bundle(self.profile,self.listing,self.qa,self.review,self.backend,fp,keywords=stage)
        self.assertNotEqual(result['status'],'passed')
        self.assertIn('keyword_bundle_mismatch',{issue['code'] for issue in result['issues']})


if __name__=='__main__':unittest.main()
