from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import amazon_front_crawler as front
import amazon_category_rank_crawler as shared
import browser_recovery as recovery
import desktop_runtime as desktop
import result_pagination as pagination
import runtime_watchdog as watchdog
import supervise_amazon_front as supervisor
import verify_front_output as verification
from safety_control import LocalSafetyController, SafetyWaitCancelled, SafetyPausedError


class ForegroundTests(unittest.TestCase):
    def test_power_assertion_is_mac_foreground_only_and_scoped_to_supervisor(self):
        runtime=SimpleNamespace(sellersprite_required=True)
        with patch.object(desktop.sys,'platform','darwin'), patch.object(desktop.os,'getpid',return_value=123), patch.object(desktop.subprocess,'Popen') as spawn:
            self.assertIs(desktop.start_foreground_power_assertion(runtime),spawn.return_value)
            self.assertEqual(spawn.call_args.args[0],['/usr/bin/caffeinate','-di','-w','123'])
            runtime.sellersprite_required=False
            self.assertIsNone(desktop.start_foreground_power_assertion(runtime))
            self.assertEqual(spawn.call_count,1)
        with patch.object(desktop.sys,'platform','win32'), patch.object(desktop.subprocess,'Popen') as spawn:
            self.assertIsNone(desktop.start_foreground_power_assertion(SimpleNamespace(sellersprite_required=True)))
            spawn.assert_not_called()

    def test_power_assertion_cleanup_is_bounded_even_when_terminate_hangs(self):
        process=Mock();process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('caffeinate',2),None]
        desktop.stop_foreground_power_assertion(process)
        process.terminate.assert_called_once();process.kill.assert_called_once()
        self.assertEqual([call.kwargs['timeout'] for call in process.wait.call_args_list],[2,2])

    def test_actual_rest_precedes_activation_and_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            current = [dt.datetime(2026, 10, 6, 12)]
            safety = LocalSafetyController(Path(tmp), clock=lambda: current[0])
            safety._write_traffic({'actions_count':20, 'rest_for':20, 'rest_until':(current[0]+dt.timedelta(seconds=60)).isoformat()})
            class Event:
                def is_set(self): return False
                def wait(self, seconds):
                    events.append('wait')
                    current[0] += dt.timedelta(seconds=seconds)
                    return False
            driver = SimpleNamespace(set_foreground_runtime=lambda *_: None,
                prepare_foreground=lambda: events.append('activate'), get=lambda *_: events.append('navigate'))
            with patch.object(shared, 'observe_amazon_risk'), patch.object(shared, 'handle_amazon_verification'):
                shared.open_amazon_page(driver, 'https://www.amazon.com/s', SimpleNamespace(safety=safety), stop_event=Event(), defer_delivery=True)
            self.assertEqual(events, ['wait','wait','activate','navigate'])
            self.assertEqual(safety._load_traffic()['actions_count'], 21)

    def test_cancel_preserves_rest_and_does_not_navigate(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = dt.datetime(2026, 10, 6, 12)
            safety = LocalSafetyController(Path(tmp), clock=lambda: now)
            traffic = {'actions_count':20,'rest_for':20,'rest_until':(now+dt.timedelta(seconds=60)).isoformat()}
            safety._write_traffic(traffic)
            event = SimpleNamespace(is_set=lambda:False, wait=lambda *_:True)
            with self.assertRaises(SafetyWaitCancelled):
                safety.before_remote_action('test', event)
            self.assertEqual(safety._load_traffic(), traffic)

    def test_locked_then_unlocked_and_unknown_are_distinct(self):
        runtime = SimpleNamespace(manual_pause_timeout=1, safety=Mock())
        with patch.object(desktop, 'desktop_state', side_effect=['locked','unlocked']), patch.object(desktop.time,'sleep'):
            desktop.wait_for_desktop(runtime)
        runtime.safety.heartbeat.assert_called_once()
        with patch.object(desktop,'desktop_state',return_value='unknown'):
            with self.assertRaises(desktop.DesktopUnavailable): desktop.wait_for_desktop(runtime)

    def test_mid_load_lock_pauses_before_foreground_and_preserves_active_budget(self):
        events=[]
        driver=SimpleNamespace(is_cdp_driver=True, set_foreground_runtime=lambda *_:None, prepare_foreground=lambda:events.append('activate'))
        runtime=SimpleNamespace(sellersprite_required=True)
        with patch.object(desktop,'desktop_state',return_value='locked'), patch.object(desktop,'wait_for_desktop',side_effect=lambda *_:events.append('unlock')), patch.object(desktop.time,'monotonic',side_effect=[10,17]):
            self.assertEqual(desktop.ensure_page_desktop(driver,runtime),7)
        self.assertEqual(events,['unlock','activate'])

    def test_system_sleep_cannot_extend_manual_wait_past_wall_deadline(self):
        runtime=SimpleNamespace(manual_pause_timeout=900,safety=None)
        with patch.object(desktop,'desktop_state',return_value='locked'),patch.object(desktop.time,'monotonic',return_value=10),patch.object(desktop.time,'time',side_effect=[1000,1000,2000]),patch.object(desktop.time,'sleep'):
            with self.assertRaises(desktop.DesktopUnavailable) as caught:
                desktop.wait_for_desktop(runtime)
        self.assertEqual(caught.exception.reason,'desktop_wait_timeout')

    def test_expired_plugin_budget_performs_no_browser_read(self):
        driver = SimpleNamespace()
        with patch.object(front,'inspect_storefront_plugin_page') as observe, patch.object(front,'inspect_sellersprite_block') as block:
            self.assertEqual(front.wait_for_storefront_plugin_page(driver, SimpleNamespace(), time.monotonic()-1), 'timeout')
            observe.assert_not_called(); block.assert_not_called()
            self.assertEqual(shared.get_sellersprite_readiness(driver)['timeout_reason'], 'budget_expired')

    def test_shared_parser_boundaries(self):
        self.assertEqual(shared.parse_field_from_text('sales_30_days_child','近30天销量(子体): < 5 毛利率: 32%'), '< 5')
        self.assertEqual(shared.parse_field_from_text('launch_date','上架时间: 自然搜索词: 300'), '')
        for token in ('NA','–'):
            self.assertEqual(shared.sellersprite_field_status('fba_fee',token),'explicit_unavailable')


class WatchdogTests(unittest.TestCase):
    def test_stalled_page_creation_and_opener_reads_have_external_ten_second_budget(self):
        setup = "from browser_runtime import CdpWebDriver; from types import SimpleNamespace; import time\ndriver=object.__new__(CdpWebDriver)\ndriver._ensure_ownership_state=lambda:None\ndriver._closed=False\ndriver._worker_page=None\ndriver._owned_pages={}\ndriver._action_page_captures={}\npage=SimpleNamespace(opener=lambda:time.sleep(300))\n"
        cases = (
            ('create_worker_page',"driver._context=SimpleNamespace(new_page=lambda:time.sleep(300))\ndriver.ensure_worker_page()"),
            ('read_opener',"driver._on_context_page(page)"),
            ('read_opener',"driver._context=SimpleNamespace(pages=[page])\ndriver._discover_owned_opener_descendants()"),
            ('read_opener',"driver._page_opener_depth(page,{id(page):page})"),
        )
        for operation,action in cases:
            with self.subTest(operation=operation,action=action), tempfile.TemporaryDirectory() as tmp:
                env={**os.environ,'LC_CRAWL_WATCHDOG_DIR':tmp,'LC_CRAWL_ATTEMPT_ID':'management'}
                process=subprocess.Popen([sys.executable,'-c',setup+action],cwd=Path(watchdog.__file__).parent,env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                started=time.monotonic()
                try:
                    while time.monotonic()-started<12:
                        value=supervisor.read_json(Path(tmp)/'runtime_watchdog.json')
                        if supervisor.command_expired(value,'management'):break
                        time.sleep(.02)
                    else:self.fail('management call did not publish a bounded external deadline')
                    self.assertEqual(value['operation'],operation)
                    supervisor.stop_child(process)
                    self.assertLess(time.monotonic()-started,12)
                    self.assertIsNotNone(process.poll())
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=2)

    def test_nested_calls_preserve_outer_deadline_and_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LC_CRAWL_WATCHDOG_DIR':tmp,'LC_CRAWL_ATTEMPT_ID':'new'}):
            path=Path(tmp)/'runtime_watchdog.json'
            with watchdog.browser_call('outer',3):
                outer=json.loads(path.read_text())
                with watchdog.browser_call('inner',10):
                    inner=json.loads(path.read_text())
                    self.assertEqual(inner['deadline_monotonic'],outer['deadline_monotonic'])
                self.assertEqual(json.loads(path.read_text())['operation'],'outer')
            self.assertFalse(json.loads(path.read_text())['active'])
            self.assertFalse(supervisor.command_expired(inner,'old',now=inner['deadline_monotonic']+1))
            self.assertTrue(supervisor.command_expired(inner,'new',now=inner['deadline_monotonic']+1))

    def test_nonreturning_child_group_is_stopped(self):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'],start_new_session=True)
        try:
            started=time.monotonic(); supervisor.stop_child(child)
            self.assertIsNotNone(child.poll()); self.assertLess(time.monotonic()-started,3)
        finally:
            if child.poll() is None: child.kill()

    def test_double_supervisor_lock_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=LocalSafetyController(Path(tmp)); second=LocalSafetyController(Path(tmp))
            first.acquire()
            try:
                with self.assertRaises(SafetyPausedError): second.acquire()
            finally: first.release(); second.release()

    def test_planned_long_rest_keeps_original_until(self):
        runtime=SimpleNamespace(manual_pause_timeout=900,page_timeout=90,operation_mode='supervised')
        now=dt.datetime(2026,10,6,12)
        self.assertEqual(supervisor.phase_budget({'phase':'waiting','until':(now+dt.timedelta(seconds=660)).isoformat()},runtime,now),690)

    def test_successful_empty_or_filtered_page_counts_as_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp); (job/'state.json').write_text(json.dumps({'records_count':0,'completed_page_order':['a','b']}))
            (job/'page_results').mkdir()
            for key in ('a','b'):
                (job/'page_results'/(hashlib.sha256(key.encode()).hexdigest()+'.json')).write_text(json.dumps({'plugin_status':'ok','scanned_count':0}))
            self.assertEqual(supervisor.committed_pages(job),2)
            (job/'page_results'/(hashlib.sha256(b'b').hexdigest()+'.json')).write_text(json.dumps({'plugin_status':'skipped'}))
            self.assertEqual(supervisor.committed_pages(job),1)


    def test_external_watchdog_stops_nonreturning_calls(self):
        for operation in ('evaluate','screenshot','close_page'):
            with tempfile.TemporaryDirectory() as tmp:
                env={**os.environ,'LC_CRAWL_WATCHDOG_DIR':tmp,'LC_CRAWL_ATTEMPT_ID':'attempt'}
                source="from runtime_watchdog import browser_call; import time\nwith browser_call("+repr(operation)+", .2): time.sleep(300)"
                process=subprocess.Popen([sys.executable,'-c',source],cwd=Path(watchdog.__file__).parent,env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                start=time.monotonic()
                try:
                    while time.monotonic()-start<3:
                        value=supervisor.read_json(Path(tmp)/'runtime_watchdog.json')
                        if supervisor.command_expired(value,'attempt'): break
                        time.sleep(.02)
                    else: self.fail('external deadline not observed')
                    supervisor.stop_child(process)
                    self.assertLess(time.monotonic()-start,3)
                    self.assertIsNotNone(process.poll())
                finally:
                    if process.poll() is None: process.kill()

    def test_auth_failure_stops_and_old_completion_cannot_succeed(self):
        for code,expected in ((2,2),(0,30)):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); cfg=root/'config.json';cfg.write_text('{}')
                runtime=SimpleNamespace(outputs_root=root,job_id='job',mode='storefront',manual_pause_timeout=900,page_timeout=90,operation_mode='supervised')
                process=Mock();process.pid=222;process.poll.return_value=code;process.wait.return_value=code
                with patch.object(front,'build_front_runtime_config',return_value=runtime), patch.object(supervisor,'default_safety_root',return_value=root/'safe'),patch.object(supervisor.subprocess,'Popen',return_value=process),patch.object(supervisor,'bounded_recovery') as recover:
                    self.assertEqual(supervisor.supervise(cfg),expected)
                    status=json.loads((root/'job'/'supervisor.json').read_text())
                    self.assertEqual(status['exit_code'],expected)
                    self.assertEqual(status['child_exit_code'],code)
                    recover.assert_not_called()


    def test_new_supervisor_honors_prior_resume_deadline_before_spawning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=root/'cfg.json';cfg.write_text('{}');job=root/'job';job.mkdir()
            until=dt.datetime.now()+dt.timedelta(seconds=.06)
            (job/'run_summary.json').write_text(json.dumps({'attempt_id':'old','resume_at':until.isoformat()}))
            runtime=SimpleNamespace(outputs_root=root,job_id='job',mode='storefront',manual_pause_timeout=900,page_timeout=90,operation_mode='supervised')
            process=Mock();process.pid=222;process.poll.return_value=2;process.wait.return_value=2
            def spawn(*a,**k):
                self.assertGreaterEqual(dt.datetime.now(),until)
                self.assertEqual(json.loads((job/'supervisor.json').read_text())['reason'],'persisted_cooldown')
                return process
            with patch.object(front,'build_front_runtime_config',return_value=runtime),patch.object(supervisor,'default_safety_root',return_value=root/'safe'),patch.object(supervisor.subprocess,'Popen',side_effect=spawn):
                self.assertEqual(supervisor.supervise(cfg),2)



class RecoveryTests(unittest.TestCase):
    def test_locked_state_does_not_probe_or_restart(self):
        with patch.object(recovery,'desktop_state',return_value='locked'), patch.object(recovery,'dedicated_processes') as processes:
            self.assertEqual(recovery.probe_browser({})['reason'],'desktop_locked')
            with self.assertRaises(RuntimeError): recovery.restart_dedicated_browser({})
            processes.assert_not_called()

    def test_no_frames_is_inconclusive_and_probe_always_closed(self):
        cdp=Mock()
        cdp.call.side_effect=lambda method,*a,**k: {'targetId':'ours'} if method=='Target.createTarget' else ({'sessionId':'s'} if method=='Target.attachToTarget' else ({'result':{'value':{'frames':0,'hidden':False}}} if method=='Runtime.evaluate' else ({'processInfo':[{'type':'browser','id':10}]} if method=='SystemInfo.getProcessInfo' else {})))
        with patch.object(recovery,'desktop_state',return_value='unlocked'), patch.object(recovery,'dedicated_processes',return_value={10:(1,'browser','created')}), patch.object(recovery,'activate_browser',return_value=True), patch.object(recovery,'browser_settings',return_value=(Path('/tmp/profile'),'Default','127.0.0.1:9222',90)), patch.object(recovery,'browser_version_info',return_value=None), patch.object(recovery,'LocalCdp',return_value=cdp):
            self.assertEqual(recovery.probe_browser({})['status'],'unknown')
        self.assertTrue(any(call.args[:2]==('Target.closeTarget',{'targetId':'ours'}) for call in cdp.call.call_args_list))

    def test_two_browser_level_failures_are_required(self):
        with patch.object(recovery,'desktop_state',return_value='unlocked'), patch.object(recovery,'dedicated_processes',return_value={10:(1,'browser','created')}), patch.object(recovery,'activate_browser',return_value=True), patch.object(recovery,'browser_settings',return_value=(Path('/tmp/profile'),'Default','127.0.0.1:9222',90)), patch.object(recovery,'browser_version_info',return_value=None), patch.object(recovery,'LocalCdp',side_effect=TimeoutError) as probe:
            self.assertEqual(recovery.probe_browser({})['status'],'browser_unresponsive'); self.assertEqual(probe.call_count,2)

    def test_restart_only_kills_matching_identity_even_after_reparent(self):
        original={10:(1,'/binary --user-data-dir=/owned','date'),11:(10,'helper','date')}
        tables=[{11:(1,'helper','date'),10:(1,'unrelated reused pid','newdate')}, {}]
        with patch.object(recovery,'desktop_state',return_value='unlocked'), patch.object(recovery,'dedicated_processes',return_value=original), patch.object(recovery,'process_table',side_effect=tables), patch.object(recovery.time,'monotonic',side_effect=[0,6]), patch.object(recovery.time,'sleep'), patch.object(recovery.os,'kill') as kill, patch.object(recovery,'start_browser'):
            result=recovery.restart_dedicated_browser({})
        self.assertEqual(kill.call_args_list[0].args,(10,signal.SIGTERM))
        self.assertEqual(result['forced_pids'],[11]); self.assertEqual(kill.call_count,2)


class MoreTests(unittest.TestCase):
    def task(self,kind='storefront'):
        return {'source_type':kind,'source_id':'store','page_number':1,'page_url':'https://www.amazon.com/s?me=A'}
    def test_more_continuation_same_url_distinct_commit_and_seen_asins(self):
        current=self.task(); driver=SimpleNamespace(current_url=current['page_url'], execute_script=lambda *_:{'selector':'#more'})
        with patch.object(front,'find_next_page_url',return_value=None):
            next_task,reason=front.build_next_front_task(driver,SimpleNamespace(store_page_limit=None),current,[{'asin':'B000000001'}])
            self.assertFalse(reason); self.assertEqual(next_task['load_more_step'],1)
            self.assertEqual(next_task['seen_load_asins'],['B000000001'])
            self.assertNotEqual(front.front_page_key(current,driver.current_url),front.front_page_key(next_task,driver.current_url))
            last,reason=front.build_next_front_task(driver,SimpleNamespace(store_page_limit=2),next_task,[{'asin':'B000000002'}])
            self.assertIsNone(last); self.assertEqual(reason,'store_page_limit')

    def test_keyword_more_respects_batch_limit(self):
        current=self.task('keyword_search'); driver=SimpleNamespace(current_url=current['page_url'],execute_script=lambda *_:{'selector':'#more','disabled':True})
        with patch.object(front,'find_next_page_url',return_value=None):
            task,reason=front.build_next_front_task(driver,SimpleNamespace(max_pages_per_keyword=2),current,[{'asin':'B000000001'}])
        self.assertTrue(task); self.assertFalse(reason)

    def test_restart_replays_batches_and_only_extracts_new_asins(self):
        worker=object.__new__(front.FrontWorker)
        driver=SimpleNamespace(current_url='https://www.amazon.com/s?me=A')
        worker.runtime=SimpleNamespace(); worker.stop_event=threading.Event(); worker._ensure_driver=lambda:driver
        opened=[]; worker._open_page=opened.append; worker._wait_for_page_or_manual=lambda *_:None
        task={**self.task(),'continuation_kind':'load_more','load_more_step':2,'seen_load_asins':['B000000001','B000000002']}
        with patch.object(pagination,'click_and_wait_more') as click,patch.object(pagination,'result_asins',return_value={'B000000001','B000000002','B000000003'}):
            worker._open_result_batch(task)
        self.assertEqual(click.call_count,2); self.assertEqual(len(opened),1)
        self.assertEqual(driver._lc_batch_asins,['B000000003'])

    def test_no_growth_is_failure_not_natural_end(self):
        driver=SimpleNamespace(execute_script=lambda *_:[],click_result_control=Mock())
        with patch.object(pagination,'find_load_more_control',return_value={'selector':'#more'}), patch.object(shared,'safety_before_remote_action'), patch.object(shared,'prepare_navigation'):
            with self.assertRaises(shared.WebDriverException): pagination.click_and_wait_more(driver,SimpleNamespace(page_timeout=0))

    def test_cached_country_and_bsr_reach_export_only_for_same_batch_and_epoch(self):
        driver=SimpleNamespace(current_url='https://www.amazon.com/s',page_epoch=1,_lc_seen_batch_asins=['B000000002'])
        driver._lc_storefront_cards={'identity':front.storefront_cache_identity(driver),
            'cards':{'B000000001':{'seller_country_flag_code':'cn','bsr_text':'#123 in Tools & Home Improvement'}},
            'htmls':{'B000000001':'<span class="flag-icon-cn"></span>'}}
        runtime=SimpleNamespace(page_extraction_engine='browser',field_selectors={},sellersprite_required=True,save_page_evidence=True)
        with patch.object(front,'extract_front_product_cards',side_effect=lambda *_a,**_k:[{'asin':'B000000001','text':'Product'}]), patch.object(front,'extract_table_rows',return_value=[]), patch.object(front,'extract_by_selectors',return_value={}):
            row=front.merge_front_product_data(driver,runtime,{},'ok',plugin_texts={'B000000001':'FBA费用: N/A'})[0]
            self.assertEqual(row['seller_country'],shared.country_from_flag_code_or_text('cn'))
            self.assertEqual(row['_source_country_flag_code'],'cn')
            self.assertTrue(row['subcategory_bsr_ranks'])
            for field,value in (('page_epoch',2),('_lc_seen_batch_asins',['B000000003'])):
                setattr(driver,field,value)
                row=front.merge_front_product_data(driver,runtime,{},'ok',plugin_texts={'B000000001':'FBA费用: N/A'})[0]
                self.assertEqual(row['_source_country_flag_code'],'')
                self.assertEqual(row['subcategory_bsr_ranks'],[])
                self.assertNotIn('_source_plugin_html',row)
                driver.page_epoch=1


    def test_debug_evidence_directory_is_created_on_first_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker=object.__new__(front.FrontWorker);worker.runtime=SimpleNamespace(save_debug_snapshots=True)
            worker.driver=object();worker.debug_dir=Path(tmp)/'absent';worker.worker_id='tab'
            worker._readiness={'page_render':{'frame_callbacks':1}}
            with patch.object(front,'save_debug_snapshot'):
                worker._save_debug(self.task(),'plugin_data_timeout')
            self.assertTrue((worker.debug_dir/'render_evidence.jsonl').is_file())


class OutputTests(unittest.TestCase):
    def fixture(self,root):
        (root/'page_results').mkdir()
        row={'asin':'B000000001','fba_fee':'N/A','_source_card_text':'FBA费用: N/A'}
        (root/'state.json').write_text(json.dumps({'completed_page_order':['one'],'records_count':1}))
        (root/'page_results'/'one.json').write_text(json.dumps({'page_key':'one','records':[row]}))
        return row
    def test_country_flag_html_needs_extracted_evidence_and_matches_country(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);row=self.fixture(root)
            row['_source_plugin_html']='<span class="flag-icon-cn"></span>'
            def save(): (root/'page_results'/'one.json').write_text(json.dumps({'page_key':'one','records':[row]}))
            save();self.assertEqual(verification.verify(root,True)['status'],'not_evaluated')
            row['_source_country_flag_code']='us';row['seller_country']=shared.country_from_flag_code_or_text('us')
            save();self.assertEqual(verification.verify(root,True)['status'],'failed')
            row['_source_country_flag_code']='cn';row['seller_country']=shared.country_from_flag_code_or_text('cn')
            save();self.assertEqual(verification.verify(root,True)['status'],'passed')
    def test_live_manifest_snapshot_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); row=self.fixture(root)
            (root/'page_results'/'two.json').write_text(json.dumps({'page_key':'two','records':[]}))
            self.assertEqual(verification.verify(root,True)['status'],'passed')
            row['_source_card_text']=''
            (root/'page_results'/'one.json').write_text(json.dumps({'page_key':'one','records':[row]}))
            self.assertEqual(verification.verify(root,True)['status'],'not_evaluated')
    def test_duplicate_commit_rows_and_field_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); row=self.fixture(root); row['fba_fee']='$3'
            (root/'page_results'/'one.json').write_text(json.dumps({'page_key':'one','records':[row,row]}))
            result=verification.verify(root,True)
            fields={v['field'] for v in result['mismatches']}
            self.assertTrue({'duplicate_asin_in_batch','state_record_count','fba_fee'}<=fields)
    def test_final_jsonl_and_excel_reject_extra_and_duplicate_rows(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); row=self.fixture(root)
            (root/'records.jsonl').write_text(json.dumps(row)+'\n')
            front.write_front_workbook(root/'records.jsonl',root/'failures.jsonl',root/'dedup_total.xlsx')
            self.assertEqual(verification.verify(root)['status'],'passed')
            workbook=load_workbook(root/'dedup_total.xlsx');sheet=workbook.worksheets[0]
            cells=[c.value for c in sheet[2]];sheet.append(cells)
            extra=list(cells);headers=[c.value for c in sheet[1]];extra[headers.index('ASIN')]='B000000002';sheet.append(extra)
            workbook.save(root/'dedup_total.xlsx');workbook.close()
            (root/'records.jsonl').write_text((json.dumps(row)+'\n')*2)
            fields={x['field'] for x in verification.verify(root)['mismatches']}
            self.assertTrue({'commits_vs_jsonl','Excel_duplicate_ASIN','Excel_ASIN_set_or_count'}<=fields)

    def test_final_verifier_rejects_active_supervisor_between_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.fixture(root)
            (root/'supervisor.json').write_text(json.dumps({'pid':os.getpid(),'phase':'retry_wait'}))
            with self.assertRaises(ValueError): verification.verify(root)

if __name__=='__main__': unittest.main()
