from __future__ import annotations
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cvc_sources_test',ROOT/'scripts/consumer_voice_collector.py')
cvc=importlib.util.module_from_spec(spec);spec.loader.exec_module(cvc)
sources=cvc.direct_sources


class Http:
    def __init__(self,responses): self.responses=list(responses);self.calls=[]
    def get_json(self,url,params,timeout,headers):
        self.calls.append((url,dict(params),headers))
        item=self.responses.pop(0)
        if isinstance(item,Exception): raise item
        return item
    post_json=get_json


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        backend_path = self.root / "backend_config.json"
        backend_path.write_text(json.dumps({"backend_url": "https://backend.example.com", "backend_token": "sk-example-test-token"}))
        backend_path.chmod(0o600)
        backend_patch = mock.patch.object(cvc.backend_config, "DEFAULT_CONFIG_PATH", backend_path)
        backend_patch.start()
        self.addCleanup(backend_patch.stop)
        self.store=cvc.CollectorStore(self.root/'collector.sqlite3')
        self.store.create_task('test','seat cushion','quick','2026-09-08T00:00:00Z',[],task_id='task')
    def tearDown(self): self.store.close();self.temp.cleanup()
    def batch(self,platform='tiktok',backend='scrapecreators',**kw):
        args=dict(source=platform,backend=backend,scope='category_30d',video_url='https://www.tiktok.com/@u/video/1',video_id='1',metadata={'operation':'comments'})
        args.update(kw);return self.store.add_batch('task',args)
    def collect(self,batch,http,emit=None):
        adapter=sources.ScrapeCreatorsCollector(self.store,'task',batch['batch_id'],'secret-key',http)
        rows=[]
        adapter.collect(batch,emit or rows.append,lambda *a:None,lambda:60,lambda:None)
        return rows
    def test_paid_mode_without_cap_uses_task_completion_boundary(self):
        batch=self.batch();http=Http([])
        with mock.patch.dict(os.environ,{'SCRAPECREATORS_API_KEY':'existing'}):
            with self.assertRaises(sources.SourceBudgetError): self.collect(batch,http)
        self.assertEqual([],http.calls)
        sources.configure(self.store,'task','scrapecreators')
        account=sources.budget(self.store,'task')
        self.assertIsNone(account['credits_cap'])
        self.assertIsNone(account['remaining_credits'])
        self.assertEqual('task_completion',account['spend_boundary'])
        sources.configure(self.store,'task','free')
        with self.assertRaises(sources.SourceBudgetError): self.collect(batch,http)
        self.assertEqual(0,sources.budget(self.store,'task')['committed_credits'])
    def test_free_service_never_launches_aggregator_or_paid_backend(self):
        for source,backend in [('last30days','last30days'),('reddit','scrapecreators'),('reddit','agent-reach')]:
            self.batch(platform=source,backend=backend)
        sources.configure(self.store,'task','free')
        runner=mock.Mock(side_effect=AssertionError('must not run'))
        http=Http([])
        result=cvc.CollectorService(self.store,runner=runner,http_client=http,scrapecreators_key='secret').run('task')
        self.assertFalse(runner.called);self.assertFalse(http.calls)
        self.assertEqual('free',result['collection_mode'])
        self.assertEqual(0,result['acquisition_budget']['committed_credits'])
    def test_paid_pagination_and_independent_reply_calls(self):
        sources.configure(self.store,'task','scrapecreators',3)
        batch=self.batch()
        http=Http([
            {'success':True,'credits_charged':1,'comments':[{'cid':'a','text':'need stronger padding','reply_comment_total':1}],'cursor':20},
            {'success':True,'credits_charged':1,'comments':[{'cid':'b','text':'I agree'}],'has_more':False},
            {'success':True,'credits_charged':1,'comments':[{'cid':'c','text':'too hot'}],'has_more':False},
        ])
        rows=self.collect(batch,http)
        self.assertEqual({'a','b','c'},{r['content_id'] for r in rows})
        self.assertEqual('a',next(r for r in rows if r['content_id']=='b')['parent_content_id'])
        self.assertTrue(http.calls[1][0].endswith('/comment/replies'))
        self.assertEqual(20,http.calls[2][1]['cursor'])
        self.assertEqual(3,sources.budget(self.store,'task')['committed_credits'])
    def test_instagram_bulk_replies_disabled_and_independent_reply_cost(self):
        sources.configure(self.store,'task','scrapecreators',2)
        batch=self.batch(platform='instagram',video_url='https://www.instagram.com/p/native/')
        http=Http([{'credits_charged':1,'comments':[{'id':'c','text':'bad latch','child_comment_count':1}]},
                   {'credits_charged':1,'comments':[{'id':'r','text':'same','parent_comment_id':'c'}],'has_more':False}])
        rows=self.collect(batch,http)
        self.assertEqual('false',http.calls[0][1]['include_replies'])
        self.assertTrue(http.calls[1][0].endswith('/comment/replies'))
        self.assertEqual(2,len(rows));self.assertEqual(2,sources.budget(self.store,'task')['committed_credits'])
    def test_youtube_continuation_and_replies_tokens(self):
        sources.configure(self.store,'task','scrapecreators',2)
        batch=self.batch(platform='youtube',video_url='https://youtube.com/watch?v=abc')
        http=Http([{'credits_charged':1,'comments':[{'id':'c','content':'does not fit','repliesContinuationToken':'opaque'}]},
                   {'credits_charged':1,'comments':[{'id':'r','content':'same here'}]}])
        self.assertEqual(2,len(self.collect(batch,http)))
        self.assertEqual({'continuationToken':'opaque'},http.calls[1][1])
    def test_reddit_nested_and_long_opaque_cursor(self):
        sources.configure(self.store,'task','scrapecreators',2)
        batch=self.batch(platform='reddit',video_url='https://www.reddit.com/r/a/comments/post/title/')
        token='opaque'*300
        http=Http([{'credits_charged':1,'comments':[{'id':'a','body':'latch broke','replies':{'items':[{'id':'b','body':'same'}],'more':{'cursor':token}}}]},
                   {'credits_charged':1,'comments':[{'id':'c','body':'need repair'}]}])
        rows=self.collect(batch,http)
        self.assertEqual(3,len(rows));self.assertEqual(token,http.calls[1][1]['cursor'])
    def test_search_four_platforms_and_target_identity(self):
        payloads={
            'reddit':{'posts':[{'id':'r','url':'https://reddit.com/r/a/comments/r/name/'}]},
            'tiktok':{'search_item_list':[{'aweme_info':{'aweme_id':'tt','author':{'unique_id':'u'}}}]},
            'instagram':{'reels':[{'id':'ig','url':'https://instagram.com/reel/a/'}]},
            'youtube':{'videos':[{'id':'yt','url':'https://youtube.com/watch?v=yt'}]},
        }
        sources.configure(self.store,'task','scrapecreators',10)
        for platform,payload in payloads.items():
            batch=self.batch(platform,video_url=None,video_id=None,query_text='seat cushion',metadata={'operation':'search'})
            http=Http([dict(payload,credits_charged=1,has_more=False)])
            found=[]
            sources.ScrapeCreatorsCollector(self.store,'task',batch['batch_id'],'secret',http).collect(batch,lambda r:None,lambda *a:found.append(a),lambda:30,lambda:None)
            self.assertEqual(1,len(found));self.assertEqual(platform,found[0][0])
    def test_timeouts_conservatively_consume_budget_and_block_retries(self):
        sources.configure(self.store,'task','scrapecreators',2)
        batch=self.batch();http=Http([TimeoutError(),TimeoutError()])
        with self.assertRaises(sources.SourceError):self.collect(batch,http)
        account=sources.budget(self.store,'task')
        self.assertEqual(2,account['uncertain_credits']);self.assertEqual(0,account['remaining_credits'])
        with self.assertRaises(sources.SourceBudgetError):self.collect(batch,http)
        self.assertEqual(2,len(http.calls))
    def test_cached_charged_page_is_reused_after_interrupted_emission(self):
        sources.configure(self.store,'task','scrapecreators',1)
        batch=self.batch();http=Http([{'credits_charged':1,'comments':[{'cid':'a','text':'bad'},{'cid':'b','text':'good'}]}])
        def fail(row): raise RuntimeError('coding interruption')
        with self.assertRaises(RuntimeError):self.collect(batch,http,fail)
        self.assertEqual(2,len(self.collect(batch,http)))
        self.assertEqual(1,len(http.calls));self.assertEqual(1,sources.budget(self.store,'task')['committed_credits'])
    def test_unknown_geography_and_missing_date_not_filtered_by_adapter(self):
        row=sources.normalize('tiktok',{'cid':'native','text':'padding gets hot'})
        self.assertEqual('not_verified',row['geography_status']);self.assertIsNone(row['published_at'])
        self.assertIsNone(sources.normalize('tiktok',{'text':'no native identity'}))
    def test_payload_and_errors_never_persist_key(self):
        sources.configure(self.store,'task','scrapecreators',2)
        batch=self.batch();http=Http([{'credits_charged':1,'comments':[{'cid':'a','text':'secret-key','api_key':'secret-key'}]}])
        rows=self.collect(batch,http)
        self.assertNotIn('secret-key',json.dumps(rows))
        self.assertNotIn('secret-key',json.dumps(self.store.checkpoint('task',batch['batch_id'],'direct_source')))
    def test_atomic_reservations_across_connections(self):
        sources.configure(self.store,'task','scrapecreators',1)
        batch=self.batch();barrier=threading.Barrier(2)
        def claim(_):
            with cvc.CollectorStore(self.store.path) as other:
                barrier.wait()
                try:sources.reserve(other,'task',batch['batch_id'],'/v1/reddit/search');return True
                except sources.SourceBudgetError:return False
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(claim,range(2)))
        self.assertEqual([False,True],sorted(result));self.assertEqual(1,sources.budget(self.store,'task')['committed_credits'])
    def test_confirmed_zero_charge_releases_reserved_credit(self):
        sources.configure(self.store,'task','scrapecreators',1)
        batch=self.batch();self.collect(batch,Http([{'credits_charged':0,'comments':[]}]))
        self.assertEqual(1,sources.budget(self.store,'task')['remaining_credits'])
    def test_free_opencli_preserves_native_ids_and_exact_arguments(self):
        batch=self.batch('x','opencli',video_url=None,query_text='seat cushion')
        calls=[];rows=[]
        def runner(argv,timeout):
            calls.append(argv);return subprocess.CompletedProcess(argv,0,json.dumps([{'id':'tweet','text':'too hot','author':'user','url':'https://x.com/user/status/tweet'}]),'')
        sources.free_collect(batch,runner,rows.append,lambda *a:None,20,lambda:60)
        self.assertEqual(['opencli','twitter','search'],calls[0][:3]);self.assertEqual('tweet',rows[0]['content_id'])
    def test_paid_budget_exhaustion_continues_free_batches(self):
        sources.configure(self.store,'task','scrapecreators',1)
        self.batch();self.batch('x','opencli',video_url=None,query_text='chair',priority=999)
        http=Http([{'credits_charged':1,'comments':[{'cid':'a','text':'hot'}],'cursor':20}])
        def runner(argv,timeout):return subprocess.CompletedProcess(argv,0,json.dumps([{'id':'tweet','text':'padding failed','author':'u'}]),'')
        result=cvc.CollectorService(self.store,http_client=http,runner=runner,scrapecreators_key='key').run('task')
        self.assertEqual(1,len(http.calls));self.assertEqual(1,result['acquisition_budget']['committed_credits'])
        self.assertTrue(self.store.connection.execute("SELECT 1 FROM comments WHERE source='x'").fetchone())
    def test_mode_routes_resume_without_overwriting_old_batches(self):
        self.batch('x','opencli',video_url=None,video_id=None,query_text='chair')
        before=len(self.store.list_batches('task'))
        cvc._add_mode_routes(self.store,'task','scrapecreators')
        self.assertEqual(before+4,len(self.store.list_batches('task')))
        cvc._add_mode_routes(self.store,'task','scrapecreators')
        self.assertEqual(before+4,len(self.store.list_batches('task')))
    def test_local_review_and_after_sales_imports_are_idempotent(self):
        for kind in ('review','after_sales'):
            path=self.root/(kind+'.json');path.write_text(json.dumps([{'id':'native','text':'too hot'}]))
            args=cvc.build_parser().parse_args(['import-records','--db',str(self.store.path),'--task-id','task','--input',str(path),'--source',kind,'--source-kind',kind])
            self.assertEqual(1,cvc.execute(args)['new_hard_unique_records'])
            self.assertEqual(0,cvc.execute(args)['new_hard_unique_records'])
            raw=self.store.connection.execute('SELECT raw_json FROM comments WHERE source=?',(kind,)).fetchone()[0]
            self.assertIn(kind,raw)
    def test_source_mode_survives_research_level_upgrade(self):
        sources.configure(self.store,'task','scrapecreators',3)
        self.store.upgrade_research_level('task','standard')
        self.assertEqual('scrapecreators',self.store.task_payload('task')['collection_policy']['collection_mode'])
    def test_low_yield_is_not_thematic_saturation(self):
        sources.configure(self.store,'task','free')
        result=cvc.build_receipt(self.store,'task')
        self.assertEqual('pending_analysis',result['evidence_saturation']['status'])
        self.assertTrue(result['counts_are_candidates']);self.assertFalse(result['target_attainment']['target_met'])

    def test_explicit_new_time_window_keeps_time_and_credit_history(self):
        sources.configure(self.store,'task','scrapecreators',2)
        batch=self.batch();sources.reserve(self.store,'task',batch['batch_id'],'/v1/tiktok/video/comments')
        self.store.update_task('task',collection_elapsed_seconds=2200,total_elapsed_seconds=4000)
        self.assertTrue(self.store.timing_gate('task')['deadline_exceeded'])
        self.store.new_collection_window('task')
        self.assertFalse(self.store.timing_gate('task')['deadline_exceeded'])
        usage=self.store.timing_usage('task')
        self.assertEqual(4000,usage['cumulative_total_seconds']);self.assertEqual(0,usage['effective_total_seconds'])
        self.assertEqual(1,sources.budget(self.store,'task')['committed_credits'])
        self.assertEqual(10000,self.store.task_payload('task')['research_plan']['sample_target']['total_valid_max'])
    def test_explicit_cap_increase_resumes_next_unbought_page(self):
        sources.configure(self.store,'task','scrapecreators',1)
        batch=self.batch();http=Http([{'credits_charged':1,'comments':[{'cid':'a','text':'hot'}],'cursor':20}])
        with self.assertRaises(sources.SourceBudgetError):self.collect(batch,http)
        sources.configure(self.store,'task','scrapecreators',2)
        next_http=Http([{'credits_charged':1,'comments':[{'cid':'b','text':'need airflow'}],'has_more':False}])
        rows=self.collect(batch,next_http)
        self.assertEqual(['b'],[r['content_id'] for r in rows]);self.assertEqual(20,next_http.calls[0][1]['cursor'])
        self.assertEqual(2,sources.budget(self.store,'task')['committed_credits'])
    def test_plan_json_cannot_enable_paid_routing(self):
        plan=self.root/'plan.json'
        plan.write_text(json.dumps({'collection_mode':'scrapecreators','credits_cap':200,
            'queues':[{'source':'reddit','backend':'scrapecreators','query_text':'chair'}]}))
        with mock.patch.dict(os.environ,{'LCADMO_TASK_REGISTRY':str(self.root/'registry.json')}):
            args=cvc.build_parser().parse_args(['plan','--db',str(self.root/'other.sqlite3'),'--plan-file',str(plan),'--youtube-config',str(self.root/'youtube.env')])
            result=cvc.execute(args)
        self.assertEqual('free',result['collection_policy']['collection_mode'])
        self.assertEqual(0,result['collection_policy']['credits_cap'])

    def test_tiktok_and_instagram_store_never_merge_shared_post_urls(self):
        sources.configure(self.store,'task','scrapecreators',4)
        for platform,url in [('tiktok','https://www.tiktok.com/@u/video/post'),('instagram','https://www.instagram.com/p/post/')]:
            batch=self.batch(platform,video_url=url,video_id='post',metadata={'operation':'comments','parent_context':'seat cushion creator context'})
            native_key='cid' if platform=='tiktok' else 'id'
            payload={'credits_charged':1,'comments':[{native_key:'first','text':'too hot'},{native_key:'second','text':'padding collapsed'}]}
            def emit(record):self.store.insert_comment('task',batch,record)
            self.collect(batch,Http([payload]),emit)
            rows=self.store.connection.execute('SELECT content_id,parent_content_id,hard_key FROM comments WHERE source=?',(platform,)).fetchall()
            self.assertEqual({'post','first','second'},{r['content_id'] for r in rows})
            self.assertEqual(3,len({r['hard_key'] for r in rows}))
            self.assertEqual({'post'},{r['parent_content_id'] for r in rows if r['content_id']!='post'})
            # The same native comments discovered via a different route merge
            # by comment ID while distinct IDs remain independently retained.
            imported=self.batch(platform,'external',video_url=url,video_id='post')
            for item in payload['comments']:
                normalized=sources.normalize(platform,item,url,context='post')
                self.store.insert_comment('task',imported,normalized)
            self.assertEqual(3,self.store.connection.execute('SELECT COUNT(*) FROM comments WHERE source=?',(platform,)).fetchone()[0])
    def test_reddit_and_youtube_free_paid_routes_share_native_identity(self):
        sources.configure(self.store,'task','scrapecreators',4)
        for platform,url,item in [('reddit','https://www.reddit.com/r/a/comments/post/title/',{'id':'a','body':'too hot','parent_id':'t3_post'}),
                                   ('youtube','https://youtube.com/watch?v=post',{'id':'a','content':'too hot'})]:
            free=self.batch(platform,'external',video_url=url,video_id='post')
            self.store.insert_comment('task',free,sources.normalize(platform,item,url,context='post'))
            paid=self.batch(platform,video_url=url,video_id='post')
            self.collect(paid,Http([{'credits_charged':1,'comments':[item]}]),lambda record:self.store.insert_comment('task',paid,record))
            self.assertEqual(1,self.store.connection.execute('SELECT COUNT(*) FROM comments WHERE source=?',(platform,)).fetchone()[0])
    def test_price_mismatch_halts_task_across_batches_and_resumes(self):
        sources.configure(self.store,'task','scrapecreators',10)
        batch=self.batch();http=Http([{'credits_charged':2,'comments':[]}])
        with self.assertRaises(sources.SourceError):self.collect(batch,http)
        next_batch=self.batch();next_http=Http([])
        with self.assertRaises(sources.SourceBudgetError):self.collect(next_batch,next_http)
        sources.configure(self.store,'task','scrapecreators',20)
        with self.assertRaises(sources.SourceBudgetError):self.collect(next_batch,next_http)
        self.assertEqual([],next_http.calls)
        self.assertEqual('provider_price_exceeded_verified_reservation',sources.budget(self.store,'task')['paid_channel_halt_reason'])
    def test_wrong_platform_url_is_rejected_before_spending(self):
        sources.configure(self.store,'task','scrapecreators',1)
        batch=self.batch(video_url='https://example.com/private')
        http=Http([])
        with self.assertRaises(sources.SourceError):self.collect(batch,http)
        self.assertEqual([],http.calls);self.assertEqual(0,sources.budget(self.store,'task')['committed_credits'])

    def test_imported_reviews_shared_product_url_keep_native_identity_after_reopen(self):
        batch=self.batch('amazon','external')
        for identity in ('review-one','review-two'):
            self.store.insert_comment('task',batch,{'source':'amazon','source_kind':'review','content_id':identity,'text':'need better padding','url':'https://amazon.com/dp/PRODUCT'})
        self.assertEqual(2,self.store.connection.execute("SELECT COUNT(*) FROM comments WHERE source='amazon'").fetchone()[0])
        self.store.close();self.store=cvc.CollectorStore(self.root/'collector.sqlite3')
        self.store.insert_comment('task',batch,{'source':'amazon','source_kind':'review','content_id':'review-one','text':'need better padding','url':'https://amazon.com/dp/PRODUCT'})
        self.assertEqual(2,self.store.connection.execute("SELECT COUNT(*) FROM comments WHERE source='amazon'").fetchone()[0])

    def test_single_line_jsonl_is_one_record_and_unknown_json_is_rejected(self):
        path=self.root/'one.jsonl';path.write_text(json.dumps({'id':'one','text':'need a stronger clamp'})+'\n')
        args=cvc.build_parser().parse_args(['import-records','--db',str(self.store.path),'--task-id','task','--input',str(path),'--source','amazon','--source-kind','review'])
        result=cvc.execute(args)
        self.assertEqual(1,result['records_seen']);self.assertEqual(1,result['new_hard_unique_records'])
        path.write_text(json.dumps({'unexpected':True}))
        with self.assertRaises(cvc.ConfigurationError):cvc.execute(args)

if __name__=='__main__':unittest.main()
