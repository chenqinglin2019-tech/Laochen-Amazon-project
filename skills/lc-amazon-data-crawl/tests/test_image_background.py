"""Offline acceptance for the daily-Chrome image workflow. No live browser/provider."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import csv
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import image_background_crawler as bg
import amazon_image_competitor_crawler as core
import run_outcome
from safety_control import LocalSafetyController


class Clock:
    def __init__(self): self.t = 0
    def now(self): return self.t
    def sleep(self, n): self.t += n


class State:
    def __init__(self): self.data = {}
    def flush(self): pass
    def set_current(self, row): self.data['current'] = row


class Bridge:
    """Evaluates the DOM protocol, with document/URL guards enforced as in Chrome."""
    def __init__(self, snapshots):
        self.session, self.target = 'test', ''
        self.snapshots = snapshots
        self.index, self.doc = 0, ''
        self.actions = []
        self.closed = False
    def bind(self): self.target = 'fixed-target'
    def validate_target(self):
        if self.closed: raise run_outcome.needs_human('closed')
    def dom(self, script, args):
        result = self.evaluate('JSON.stringify((' + script + ')(' + json.dumps(args) + '))')
        if result.get('error'): raise run_outcome.needs_human('DOM changed')
        return result
    def evaluate(self, expr):
        args = json.loads(expr.rsplit(')(', 1)[1][:-2])
        snap = dict(self.snapshots[self.index], document_id=self.doc)
        if args.get('expectedUrl') and args['expectedUrl'] != snap['url']: return {'error': 'url changed'}
        if args.get('documentId') and args['documentId'] != self.doc: return {'error': 'document changed'}
        action = args['action']
        self.actions.append(action)
        if action == 'mark':
            self.doc = args['id']
            return dict(url=snap['url'], document_id=self.doc)
        if action == 'navigate':
            self.index += 1
            self.doc = ''
            return {'navigating': True}
        if action == 'scroll':
            self.index = min(self.index + 1, len(self.snapshots) - 1)
            return {'scrolled': True}
        return snap


def snapshot(**extra):
    return dict(url='https://www.amazon.com/dp/B000000001', ready=True, source_image='https://m.media-amazon.com/images/I/source.jpg',
                asin='B000000001', cards=[], result_page=False, installed=True, busy=False, delivery='New York 10001', **extra)


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / 'products.csv'
        self.input.write_text('ASIN,商品URL,主图URL,本地图片路径\nB000000001,,,\n', encoding='utf-8')
    def tearDown(self): self.temp.cleanup()
    def runtime(self, **kwargs):
        cfg = bg.validate_config(dict(job_id='case', marketplace='美国站', products_file=str(self.input),
            outputs_root=str(self.root), delivery_location_enabled=False,
            doubao_embedding_config_file=str(self.root / 'embedding.json'),
            doubao_mini_config_file=str(self.root / 'mini.json'), **kwargs))
        rt = core.build_image_runtime_config(cfg, False)
        rt.entry_mode, rt.confirm_logout, rt.rebind, rt.migrate_from_job, rt.resume_after_review = cfg['entry_mode'], True, False, '', False
        return rt
    def safety(self, **kwargs): return LocalSafetyController(self.root / 'safety', **kwargs)
    def run_job(self, rt):
        with patch.object(bg, 'cli_command', return_value=['unused']), patch.object(core, 'prepare_vision_provider'), patch.object(bg, 'LocalSafetyController', side_effect=self.safety):
            return bg.run(rt)

    def test_defaults_and_public_cli_rejects_old_cdp_before_connect(self):
        rt = self.runtime()
        self.assertEqual((rt.max_candidates_per_source, rt.max_competitors_per_source, rt.browser_backend), (48, 48, 'opencli'))
        for invalid in [dict(browser_backend='cdp'), dict(search_strategy='amazon_upload'), dict(enrich_accepted_results=True), dict(sellersprite_required=True)]:
            with self.assertRaises(run_outcome.CrawlStop): self.runtime(**invalid)
        cfg = self.root / 'old.json'
        cfg.write_text(json.dumps(dict(job_id='old', browser_backend='cdp')))
        with patch.object(bg, 'OpenCliBridge') as bridge:
            self.assertEqual(core.main(['--config', str(cfg)]), 40)
            bridge.assert_not_called()

    def test_input_errors_are_aggregated(self):
        self.input.write_text('ASIN,商品URL,主图URL,本地图片路径\nB000000001,https://www.amazon.com/dp/B000000002,,\n,,,test.jpg\n,,https://127.0.0.1/x.jpg,\n')
        with self.assertRaises(run_outcome.CrawlStop) as caught: bg.validate_inputs(self.input, 'amazon.com')
        for line in ['第 2 行', '第 3 行', '第 4 行']: self.assertIn(line, str(caught.exception))

    def test_signed_url_preserved_amazon_image_normalized(self):
        signed = 'https://example.com/photo.jpg?signature=a%2Fb&expires=123'
        self.assertEqual(bg.normalize_image_url(signed), signed)
        self.assertEqual(bg.normalize_image_url('https://images-na.ssl-images-amazon.com/images/I/ABC._AC_SX300_.jpg?x=1'), 'https://m.media-amazon.com/images/I/ABC.jpg')

    def test_only_local_image_is_rejected_but_link_with_local_column_is_ok(self):
        self.input.write_text('主图URL,本地图片路径\nhttps://example.com/img.jpg,local.jpg\n')
        self.assertEqual(len(bg.validate_inputs(self.input, 'amazon.com')), 1)

    def test_confirmation_is_per_run_and_noninteractive_exits_30(self):
        rt = self.runtime()
        rt.confirm_logout = False
        with patch('sys.stdin.isatty', return_value=False), patch.object(bg, 'BackgroundPage') as page:
            with self.assertRaises(run_outcome.CrawlStop) as caught: self.run_job(rt)
            self.assertEqual(caught.exception.exit_code, 30)
            page.assert_not_called()
        self.assertFalse((self.root / 'case' / 'state.json').exists())

    def test_unattended_never_prompts(self):
        with patch('builtins.input') as prompt:
            with self.assertRaises(run_outcome.CrawlStop): bg.confirm_logout(False, 'unattended')
            prompt.assert_not_called()

    def test_dry_run_never_constructs_browser_or_calls_model(self):
        with patch.object(bg, 'cli_command'), patch.object(core, 'prepare_vision_provider'), patch.object(bg, 'BackgroundPage') as page, patch.object(core, 'evaluate_competitor_matches') as model:
            bg.run(self.runtime(), dry_run=True)
            page.assert_not_called(); model.assert_not_called()
        self.assertFalse((self.root / 'case').exists())

    def page(self, snapshots):
        rt = self.runtime()
        rt.safety = MagicMock()
        state, clock, bridge = State(), Clock(), Bridge(snapshots)
        page = bg.BackgroundPage(rt, state, bridge=bridge, clock=clock.now, sleep=clock.sleep)
        return page, bridge, state, clock

    def test_closed_changed_refreshed_tabs_stop(self):
        for change in ['closed', 'url', 'doc']:
            page, bridge, _, _ = self.page([snapshot()])
            page.attach()
            if change == 'closed': bridge.closed = True
            elif change == 'url': bridge.snapshots[0]['url'] = 'https://www.amazon.com/s?k=user'
            else: bridge.doc = ''
            with self.assertRaises(run_outcome.CrawlStop): page.snapshot()
            self.assertNotIn('navigate', bridge.actions)

    def test_logged_in_stops_but_guest_login_link_does_not(self):
        page, bridge, _, _ = self.page([snapshot(logged_in=True)])
        with self.assertRaises(run_outcome.CrawlStop): page.attach()
        page, bridge, state, _ = self.page([snapshot(guest=True, messages='登录 Sign in')])
        page.attach()
        self.assertEqual(state.data['logout_observation'], 'guest_dom')

    def test_stability_ignores_plugin_text_but_keeps_latest_card_fields(self):
        page, _, _, clock = self.page([snapshot()])
        def read():
            return dict(snapshot(), result_page=True, cards=[dict(asin='B000000002', candidate_image_url='https://example.com/a.jpg', text=str(clock.t), price=str(clock.t))])
        with patch.object(page, 'snapshot', side_effect=read): result = page.stable('results')
        self.assertEqual(clock.t, 4)
        self.assertEqual(result['cards'][0]['price'], '4')

    def test_stability_resets_for_visual_identity_order_and_loading(self):
        for change in ('asin', 'image', 'order', 'busy', 'ready'):
            page, _, _, clock = self.page([snapshot()])
            def read():
                cards = [dict(asin='B000000002', candidate_image_url='https://example.com/a.jpg'), dict(asin='B000000003', candidate_image_url='https://example.com/b.jpg')]
                if clock.t >= 2:
                    if change == 'asin': cards[0]['asin'] = 'B000000004'
                    elif change == 'image': cards[0]['candidate_image_url'] = 'https://example.com/c.jpg'
                    elif change == 'order': cards.reverse()
                return dict(snapshot(), result_page=True, cards=cards, busy=(change == 'busy' and clock.t == 2), ready=not(change == 'ready' and clock.t == 2))
            with self.subTest(change=change), patch.object(page, 'snapshot', side_effect=read): page.stable('results')
            self.assertEqual(clock.t, 8 if change in ('busy','ready') else 6)

    def test_product_stability_waits_four_seconds_after_main_image_change(self):
        page, _, _, clock = self.page([snapshot()])
        def read(): return dict(snapshot(), source_image='https://example.com/' + ('a' if clock.t < 2 else 'b') + '.jpg')
        with patch.object(page, 'snapshot', side_effect=read): page.stable('product')
        self.assertEqual(clock.t, 6)

    def test_ready_same_url_reuses_verified_document_without_reload(self):
        page, bridge, _, _ = self.page([snapshot()])
        page.attach()
        url = bridge.snapshots[0]['url']
        result = page.navigate(url)
        self.assertEqual(result['url'], url)
        self.assertNotIn('navigate', bridge.actions)
        page.runtime.safety.before_remote_action.assert_not_called()
        bridge.doc = ''
        with self.assertRaises(run_outcome.CrawlStop):
            page.navigate(url)

    def test_navigation_reply_lost_reconciles_original_target_once(self):
        page, bridge, state, _ = self.page([snapshot()])
        page.attach()
        original = page.raw
        url = 'https://www.amazon.com/dp/B000000002'
        calls = []
        def raw(action='snapshot', **kwargs):
            if action == 'navigate':
                calls.append(action)
                bridge.snapshots[0].update(url=url, asin='B000000002')
                bridge.doc = ''
                raise run_outcome.needs_human('DOM reply lost')
            return original(action, **kwargs)
        with patch.object(page, 'raw', raw):
            self.assertEqual(page.navigate(url)['url'], url)
        self.assertEqual(calls, ['navigate'])
        self.assertNotIn('pending_navigation', state.data)

    def test_failed_navigation_does_not_retry_or_accept_original_page(self):
        page, bridge, state, _ = self.page([snapshot()])
        page.attach()
        original = page.raw
        def raw(action='snapshot', **kwargs):
            if action == 'navigate':
                raise run_outcome.needs_human('DOM reply lost')
            return original(action, **kwargs)
        with patch.object(page, 'raw', raw):
            with self.assertRaises(run_outcome.CrawlStop):
                page.navigate('https://www.amazon.com/dp/B000000002')
        self.assertNotIn('navigate', bridge.actions)

    def test_snapshot_retries_coded_transient_on_same_target_only(self):
        page, bridge, _, clock = self.page([snapshot()])
        page.attach()
        original = bridge.dom
        with patch.object(bridge, 'dom', side_effect=[bg.BridgeTransientError('cdp_timeout'),
                bg.BridgeTransientError('target_navigated'), original(bg.DOM, {'action': 'snapshot'})]) as dom:
            self.assertEqual(page.snapshot()['url'], page.url)
        self.assertEqual(dom.call_count, 3)
        self.assertEqual(clock.t, 4)
        self.assertEqual(bridge.target, 'fixed-target')

    def test_transient_read_recovery_is_bounded_and_writes_never_replayed(self):
        page, bridge, _, clock = self.page([snapshot()])
        page.attach()
        for action, count in [('snapshot', 3), ('scroll', 1), ('navigate', 1), ('mark', 1)]:
            with patch.object(bridge, 'dom', side_effect=bg.BridgeTransientError('cdp_timeout')) as dom:
                with self.assertRaises(bg.BridgeTransientError): page.raw(action)
                self.assertEqual(dom.call_count, count)

    def test_coded_read_retry_does_not_ignore_tab_closure_or_document_change(self):
        page, bridge, _, _ = self.page([snapshot()])
        page.attach()
        bridge.closed = True
        with patch.object(bridge, 'dom', side_effect=bg.BridgeTransientError('cdp_timeout')) as dom:
            with self.assertRaises(run_outcome.CrawlStop): page.raw()
            self.assertEqual(dom.call_count, 1)
        bridge.closed = False
        original = bridge.dom
        with patch.object(bridge, 'dom', side_effect=[bg.BridgeTransientError('target_navigated'),
                run_outcome.needs_human('document changed')]) as dom:
            with self.assertRaises(run_outcome.CrawlStop): page.raw()
            self.assertEqual(dom.call_count, 2)

    def test_pending_navigation_waits_for_root_then_resolves_expected_asin(self):
        page, bridge, state, _ = self.page([snapshot()])
        page.attach()
        url = 'https://www.amazon.com/dp/B000000002'
        state.data['pending_navigation'] = url
        bridge.doc = ''
        bridge.snapshots[0].update(ready=False, document_loading=True)
        original_wait = page.wait
        def wait(detail):
            original_wait(detail)
            bridge.snapshots[0].update(url=url, ready=True, document_loading=False)
        with patch.object(page, 'wait', wait): page.recover_navigation()
        self.assertEqual(page.url, url)
        self.assertNotIn('pending_navigation', state.data)
        self.assertNotIn('navigate', bridge.actions)

    def test_bridge_process_timeout_is_coded_without_leaking_expression(self):
        import subprocess
        from opencli_bridge import OpenCliBridge
        bridge = OpenCliBridge('test', 'fixed', command=['opencli'])
        with patch('opencli_bridge.subprocess.run', side_effect=subprocess.TimeoutExpired(['SECRET'], 35)):
            with self.assertRaises(bg.BridgeTransientError) as caught: bridge.dom('', {'action': 'snapshot'})
            self.assertEqual(caught.exception.bridge_code, 'client_timeout')
            self.assertNotIn('SECRET', str(caught.exception))

    def test_bridge_preserves_machine_error_code_without_page_content(self):
        from opencli_bridge import OpenCliBridge
        bridge = OpenCliBridge('test', 'fixed', command=['opencli'])
        for code in ['target_navigated', 'detached_mid_command', 'cdp_timeout', 'attach_failed']:
            with patch.object(bridge, 'evaluate', return_value={'error': {'code': code, 'message': 'SECRET'}}):
                with self.assertRaises(bg.BridgeTransientError) as caught: bridge.dom('', {'action': 'snapshot'})
                self.assertEqual(caught.exception.bridge_code, code)
                self.assertNotIn('SECRET', str(caught.exception))
        with patch.object(bridge, 'evaluate', return_value={'error': {'code': 'tab_gone', 'message': 'SECRET'}}):
            with self.assertRaises(run_outcome.CrawlStop) as caught: bridge.dom('', {'action': 'snapshot'})
            self.assertNotIsInstance(caught.exception, bg.BridgeTransientError)
            self.assertIn('tab_gone', str(caught.exception))
            self.assertNotIn('SECRET', str(caught.exception))

    def test_change_during_throttle_is_caught_before_navigation(self):
        page, bridge, _, _ = self.page([snapshot()])
        page.attach()
        page.runtime.safety.before_remote_action.side_effect = lambda _: bridge.snapshots[0].update(url='https://www.amazon.com/s?k=human')
        with self.assertRaises(run_outcome.CrawlStop): page.navigate('https://www.amazon.com/dp/B000000002')
        self.assertNotIn('navigate', bridge.actions)

    def stream_page(self, first_count=10, second_count=11):
        source = snapshot()
        url = 'https://www.amazon.com/stylesnap?q=' + bg.quote(source['source_image'], safe='')
        def cards(n):
            return [dict(asin=f'B{i:09}', candidate_image_url=f'https://example.com/{i}.jpg') for i in range(2, n + 2)]
        first = dict(source, url=url, result_page=True, cards=cards(first_count))
        second = dict(source, url=url, result_page=True, cards=cards(second_count))
        page, bridge, state, clock = self.page([source, first, second])
        page.runtime.entry_mode = 'current_tab'
        current = bg.validate_inputs(self.input, 'amazon.com')[0]
        return page, bridge, state, current

    def test_stream_stops_before_another_scroll_at_eleventh_hit(self):
        page, bridge, state, current = self.stream_page()
        batches = []
        def observe(rows):
            batches.append(len(rows))
            return len(rows) > 10
        rows = page.collect(current, on_candidates=observe)
        self.assertEqual(batches, [10, 11])
        self.assertEqual(len(rows), 11)
        self.assertEqual(bridge.actions.count('scroll'), 1)
        self.assertEqual(current['collection_stop_reason'], 'prescreen_limit_reached')

    def test_stream_first_batch_exclusion_never_scrolls_and_respects_cap(self):
        page, bridge, state, current = self.stream_page(61, 61)
        batches = []
        rows = page.collect(current, on_candidates=lambda rows: batches.append(len(rows)) or True)
        self.assertEqual(batches, [48])
        self.assertEqual(len(rows), 48)
        self.assertNotIn('scroll', bridge.actions)

    def test_stream_under_limit_keeps_original_no_progress_end_rule(self):
        page, bridge, state, current = self.stream_page(10, 10)
        batches = []
        rows = page.collect(current, on_candidates=lambda rows: batches.append(len(rows)) or False)
        self.assertEqual(batches, [10])
        self.assertEqual(bridge.actions.count('scroll'), 2)
        self.assertEqual(current['collection_stop_reason'], 'no_progress')

    def test_stream_partial_checkpoint_resumes_candidates_before_scrolling(self):
        page, bridge, state, current = self.stream_page()
        page.runtime._source_progress = core.SourceProgressStore(self.root / 'partial', {'source': 'case'})
        def interrupt(rows): raise KeyboardInterrupt('after batch saved')
        with self.assertRaises(KeyboardInterrupt): page.collect(current, on_candidates=interrupt)
        saved = page.runtime._source_progress.get('lens', 'partial_collection')
        self.assertEqual(len(saved['candidate_records']), 10)
        self.assertIsNone(core.load_saved_lens_collection(page.runtime._source_progress))
        # Previously observed cards are no longer in the visible DOM.
        bridge.snapshots[1]['cards'] = bridge.snapshots[2]['cards'][-1:]
        rows = page.collect(current, on_candidates=lambda rows: len(rows) > 10)
        self.assertEqual(len(rows), 11)
        self.assertEqual(len({r['asin'] for r in rows}), 11)
        self.assertNotIn('scroll', bridge.actions)

    def test_stream_workflow_reuses_vectors_and_commits_exclusion_without_mini(self):
        rt = self.runtime()
        def collect(page, current, *, on_candidates):
            current['source_image'] = 'https://example.com/stream-source.jpg'
            current['collection_stop_reason'] = 'prescreen_limit_reached'
            page.state.set_current(current)
            rows = [dict(asin=f'B{i:09}', source_asin=current['source_asin'], candidate_image_url=f'https://example.com/stream-{i}.jpg') for i in range(2, 13)]
            self.assertFalse(on_candidates(rows[:10]))
            self.assertTrue(on_candidates(rows))
            return rows
        def embed(runtime, ref):
            core.add_provider_metric(runtime, 'embedding_api_calls')
            return [1.0, 0.0]
        with patch.dict(core.EMBEDDING_CACHE, {}, clear=True), patch.object(bg.BackgroundPage, 'collect', collect), \
                patch.object(core, 'call_multimodal_embedding', side_effect=embed) as paid, \
                patch.object(core, 'call_doubao_mini_verifier') as mini, patch.object(core, 'evaluate_competitor_matches') as final_model:
            self.run_job(rt)
        self.assertEqual(paid.call_count, 12)  # source + 11 unique candidates
        mini.assert_not_called(); final_model.assert_not_called()
        row = core.read_jsonl(self.root / 'case/counts.jsonl')[0]
        self.assertEqual(row['processing_status'], 'prescreen_excluded')
        self.assertIsNone(row['same_product_count'])
        self.assertEqual(row['prescreen_visual_match_count'], 11)
        self.assertEqual(row['provider_metrics']['embedding_api_calls'], 12)
        self.assertEqual(row['collection_stop_reason'], 'prescreen_limit_reached')

    def test_stream_below_limit_finishes_with_original_mini_verdict_and_cached_vectors(self):
        rt = self.runtime()
        def collect(page, current, *, on_candidates):
            current['source_image'] = 'https://example.com/below-source.jpg'
            current['collection_stop_reason'] = 'no_progress'
            page.state.set_current(current)
            rows = [dict(asin='B000000002', source_asin=current['source_asin'], candidate_image_url='https://example.com/below-positive.jpg'),
                    dict(asin='B000000003', source_asin=current['source_asin'], candidate_image_url='https://example.com/below-negative.jpg')]
            self.assertFalse(on_candidates(rows))
            return rows
        def embed(runtime, ref):
            core.add_provider_metric(runtime, 'embedding_api_calls')
            return [0.0, 1.0] if ref.endswith('negative.jpg') else [1.0, 0.0]
        with patch.dict(core.EMBEDDING_CACHE, {}, clear=True), patch.object(bg.BackgroundPage, 'collect', collect), \
                patch.object(core, 'call_multimodal_embedding', side_effect=embed) as paid, \
                patch.object(core, 'call_doubao_mini_verifier', return_value=[dict(asin='B000000002', is_same_product=True, confidence=0.9, reason='same')]) as mini:
            self.run_job(rt)
        self.assertEqual(paid.call_count, 3)
        mini.assert_called_once()
        self.assertEqual([r['asin'] for r in mini.call_args.args[2]], ['B000000002'])
        row = core.read_jsonl(self.root / 'case/counts.jsonl')[0]
        self.assertEqual(row['processing_status'], 'verified')
        self.assertEqual(row['same_product_count'], 1)
        self.assertEqual(row['provider_metrics']['embedding_api_calls'], 3)

    def test_limit_overshoot_no_repeat_search(self):
        source = snapshot()
        url = 'https://www.amazon.com/stylesnap?q=' + bg.quote(source['source_image'], safe='')
        cards = [dict(asin=f'B{i:09}', candidate_image_url=f'https://example.com/{i}.jpg') for i in range(1, 62)]
        result = dict(source, url=url, result_page=True, cards=cards)
        page, bridge, state, clock = self.page([source, result])
        current = bg.validate_inputs(self.input, 'amazon.com')[0]
        page.runtime.entry_mode = 'current_tab'
        rows = page.collect(current)
        self.assertEqual(len(rows), 48)
        self.assertEqual(bridge.actions.count('navigate'), 1)
        self.assertEqual(bridge.actions.count('scroll'), 0)
        self.assertEqual(current['collection_stop_reason'], 'limit_reached')
        self.assertGreaterEqual(clock.t, 8)  # Product and results each stabilize for 4 seconds.

    def test_no_results_vs_unrecognizable_page(self):
        for empty in [True, False]:
            result = dict(snapshot(), url='https://www.amazon.com/stylesnap?q=x', source_image='', result_page=True, empty=empty)
            page, _, _, _ = self.page([result])
            page.runtime.page_timeout = 10
            if empty: self.assertTrue(page.stable('results')['empty'])
            else:
                with self.assertRaises(core.TransientAmazonPageUnavailable): page.stable('results')

    def test_delivery_checks_exact_postcode(self):
        page, _, _, _ = self.page([snapshot()])
        page.runtime.delivery_location_enabled = True
        page.runtime.delivery_locations = {'amazon.com': {'postal_code': '10001'}}
        page.delivery(snapshot())
        for value in ['New York 100010', 'New York', 'London 10002']:
            with self.assertRaises(run_outcome.CrawlStop): page.delivery(dict(snapshot(), delivery=value))

    def test_plugin_captcha_stops_before_query(self):
        page, bridge, _, _ = self.page([snapshot(plugin_captcha=True)])
        page.runtime.safety.trip.side_effect = run_outcome.needs_human('captcha')
        with self.assertRaises(run_outcome.CrawlStop): page.attach()
        self.assertEqual(page.runtime.safety.trip.call_args.args[0].platform, 'sellersprite')
        self.assertNotIn('navigate', bridge.actions)

    def test_current_tab_preserves_selected_variant_with_parent_url(self):
        rt = self.runtime(entry_mode='current_tab')
        selected = dict(snapshot(), asin='B000000009', source_image='https://example.com/selected.jpg')
        def stable(page, kind):
            page.state.data['browser'] = dict(session='one', target='fixed', url=selected['url'], document_id='document')
            return selected
        def collect(page, current, **kwargs):
            self.assertEqual(current['source_asin'], 'B000000009')
            self.assertEqual(current['source_image'], selected['source_image'])
            page.state.set_current(current)
            return []
        with patch.object(bg.BackgroundPage, 'stable', stable), patch.object(bg.BackgroundPage, 'collect', collect):
            self.run_job(rt)
        rows = bg.validate_inputs(rt.products_file, 'amazon.com')
        self.assertEqual(rows[0]['source_asin'], 'B000000009')
        self.assertEqual(rows[0]['input_image_url'], selected['source_image'])
        with patch.object(bg.BackgroundPage, 'collect') as browser, patch.object(core, 'evaluate_competitor_matches') as model:
            self.run_job(self.runtime(entry_mode='current_tab'))
            browser.assert_not_called(); model.assert_not_called()

    def test_candidate_checkpoint_recovers_without_browser_or_repeat_paid_work(self):
        rt = self.runtime()
        def collect(page, current, **kwargs):
            current['source_image'] = 'https://example.com/source.jpg'
            page.state.set_current(current)
            return [dict(asin='B000000002', source_asin='B000000001', candidate_image_url='https://example.com/a.jpg')]
        evaluation = core.MatchEvaluation([], {}, 0, 'verified_zero', 0, '', 'no match')
        with patch.object(bg.BackgroundPage, 'collect', collect), patch.object(core, 'evaluate_competitor_matches', side_effect=KeyboardInterrupt('interrupted')):
            with self.assertRaises(KeyboardInterrupt): self.run_job(rt)
        with patch.object(bg.BackgroundPage, 'collect') as browser, patch.object(core, 'evaluate_competitor_matches', return_value=evaluation) as model:
            self.run_job(self.runtime())
            browser.assert_not_called(); model.assert_called_once()
        with patch.object(bg.BackgroundPage, 'collect') as browser, patch.object(core, 'evaluate_competitor_matches') as model:
            self.run_job(self.runtime())
            browser.assert_not_called(); model.assert_not_called()
        self.assertTrue((self.root / 'case' / 'products_相似竞品数量.xlsx').is_file())
        counts = core.read_jsonl(self.root / 'case' / 'counts.jsonl')
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts[0]['scope'], 'collected_candidates_only')

    def test_image_transport_does_not_change_mini_cache_identity(self):
        rt = self.runtime()
        ref = core.ImageReference('https://example.com/a.jpg')
        candidates = [{'asin': 'B000000002'}]
        key = core.mini_batch_progress_key(rt, ref, candidates)
        ref.data_url = 'data:image/jpeg;base64,YQ=='
        self.assertEqual(key, core.mini_batch_progress_key(rt, ref, candidates))
        self.assertEqual(core.image_to_data_url(ref), ref.data_url)

    def test_candidate_inline_transport_cached_and_failures_not_cached(self):
        rt = self.runtime()
        url = 'https://example.com/reused.jpg'
        inline = 'data:image/jpeg;base64,YQ=='
        with patch.object(bg, 'read_image_in_memory', return_value=inline) as read:
            self.assertEqual(core.candidate_image_to_data_url(rt, url), inline)
            self.assertEqual(core.candidate_image_to_data_url(rt, url), inline)
            read.assert_called_once()
        self.assertEqual(rt.provider_metrics['image_transcode_reused_from_memory'], 1)
        with patch.object(bg, 'read_image_in_memory', side_effect=core.ImageResolutionError('dns')) as read:
            for _ in range(2):
                with self.assertRaises(core.ImageResolutionError): core.candidate_image_to_data_url(rt, url+'new')
            self.assertEqual(read.call_count, 2)
        self.assertNotIn(url+'new', rt._candidate_inline_cache)

    def test_candidate_inline_cache_is_bounded_lru_and_process_local(self):
        rt = self.runtime()
        inline = 'data:image/jpeg;base64,YQ=='
        with patch.object(core, 'CANDIDATE_INLINE_CACHE_MAX_BYTES', len(inline)*2), patch.object(bg, 'read_image_in_memory', return_value=inline) as read:
            for url in ('a','b','a','c'): core.candidate_image_to_data_url(rt, url)
            self.assertEqual(list(rt._candidate_inline_cache), ['a','c'])
            self.assertEqual(read.call_count, 3)
            core.candidate_image_to_data_url(self.runtime(), 'a')
            self.assertEqual(read.call_count, 4)
        with patch.object(core, 'CANDIDATE_INLINE_CACHE_MAX_BYTES', 1), patch.object(bg, 'read_image_in_memory', return_value=inline):
            fresh = self.runtime()
            core.candidate_image_to_data_url(fresh, 'large')
            self.assertEqual(fresh._candidate_inline_cache, {})

    def test_repeated_cascade_fallback_reads_image_only_once(self):
        rt = self.runtime()
        rt._source_progress = core.SourceProgressStore(self.root/'inline-progress', {'source':'same'})
        url = 'https://example.com/reused.jpg'; inline = 'data:image/jpeg;base64,YQ=='
        record = dict(asin='B000000002', candidate_image_url=url)
        with patch.dict(core.EMBEDDING_CACHE, {}, clear=True), patch.object(bg, 'read_image_in_memory', return_value=inline) as read, patch.object(core, 'call_multimodal_embedding', side_effect=[core.EmbeddingInputRejected('image'), [1.,2.]]) as model:
            first = core.embed_cascade_candidate(rt, record)
            second = core.embed_cascade_candidate(rt, record)
            self.assertEqual(first, second)
            self.assertEqual(first[2], inline)
            self.assertEqual(model.call_count, 2)
            read.assert_called_once()

    def test_identity_error_is_saved_without_retry_or_binding_change(self):
        from opencli_bridge import OpenCliBridge
        page, _, state, _ = self.page([snapshot()]); page.attach()
        before = dict(state.data['browser'])
        real = OpenCliBridge('test', 'fixed-target', command=['unused'])
        page.bridge = real
        identity = dict(expected_url=page.url, actual_url=page.url+'?th=2',
                        expected_document=page.document, actual_document=page.document,
                        dom_asin='B000000001')
        with patch.object(real, 'evaluate', return_value={'error':'工作页网址已变化', 'page_identity':identity}) as evaluate:
            with self.assertRaises(run_outcome.CrawlStop): page.raw()
            evaluate.assert_called_once()
        self.assertEqual(state.data['browser'], before)
        saved = state.data['last_page_identity_error']
        self.assertEqual(saved['actual_url'], identity['actual_url'])
        self.assertEqual(saved['target'], 'fixed-target')
        self.assertEqual(saved['action'], 'snapshot')

    def test_canonical_read_rewrite_updates_binding_before_next_write(self):
        page, bridge, state, _ = self.page([snapshot()]);page.attach()
        canonical = dict(snapshot(), url='https://www.amazon.com/dp/B000000001?th=1', document_id=page.document, adopted_url_rewrite=True)
        with patch.object(bridge, 'dom', return_value=canonical): page.raw()
        self.assertEqual(page.url, canonical['url'])
        self.assertEqual(state.data['browser']['url'], canonical['url'])
        with patch.object(bridge, 'dom', return_value={'scrolled': True}) as dom:
            page.raw('scroll')
            self.assertEqual(dom.call_args.args[1]['expectedUrl'], canonical['url'])

    def test_source_embedding_fallback_cached_across_restart_without_refetch(self):
        rt = self.runtime()
        rt._source_progress = core.SourceProgressStore(self.root / 'progress', {'source': 'one'})
        ref = core.ImageReference('https://example.com/a.jpg')
        with patch.object(core, 'call_multimodal_embedding_cached', side_effect=[core.EmbeddingInputRejected('image'), [1., 2.]]), patch.object(bg, 'read_image_in_memory', return_value='data:image/jpeg;base64,YQ==') as read:
            self.assertEqual(core.resolve_source_embedding(rt, ref, ref.url), [1., 2.])
            read.assert_called_once()
        with patch.object(core, 'call_multimodal_embedding_cached') as model, patch.object(bg, 'read_image_in_memory') as read:
            self.assertEqual(core.resolve_source_embedding(rt, core.ImageReference(ref.url), ref.url), [1., 2.])
            model.assert_not_called(); read.assert_not_called()

    def test_model_rate_limit_does_not_download_source(self):
        rt = self.runtime()
        with patch.object(core, 'call_multimodal_embedding_cached', side_effect=core.EmbeddingProviderError('HTTP 429')), patch.object(bg, 'read_image_in_memory') as read:
            with self.assertRaises(core.EmbeddingProviderError): core.resolve_source_embedding(rt, core.ImageReference('https://example.com/a.jpg'), '')
            read.assert_not_called()

    def test_amazon_fake_ip_uses_configured_local_proxy_with_original_hostname(self):
        response = MagicMock(status_code=200, headers={'content-type': 'image/jpeg'})
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'image']
        url = 'https://m.media-amazon.com/images/I/test.jpg'
        with patch.object(bg.urllib.request, 'getproxies_macosx_sysconf', return_value={'https': 'http://127.0.0.1:6152'}, create=True), patch.object(bg.socket, 'getaddrinfo') as dns, patch.object(bg.requests, 'get', return_value=response) as fetch:
            self.assertTrue(bg.read_image_in_memory(url).startswith('data:image/jpeg;base64,'))
            dns.assert_not_called()
            self.assertEqual(fetch.call_args.args[0], url)
            self.assertEqual(fetch.call_args.kwargs['proxies'], {'https': 'http://127.0.0.1:6152'})
            self.assertNotIn('verify', fetch.call_args.kwargs)  # TLS verification remains default-on.

    def test_proxy_never_exempts_arbitrary_or_private_urls(self):
        with patch.object(bg.urllib.request, 'getproxies_macosx_sysconf', return_value={'https': 'http://127.0.0.1:6152'}, create=True), patch.object(bg.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', ('198.18.9.199', 443))]), patch.object(bg.requests, 'get') as fetch:
            for url in ('https://example.com/a.jpg', 'https://127.0.0.1/a.jpg', 'https://m.media-amazon.com.evil.example/a.jpg'):
                with self.subTest(url=url), self.assertRaises(run_outcome.CrawlStop):
                    bg.read_image_in_memory(url)
            fetch.assert_not_called()

    def test_amazon_proxy_redirect_is_revalidated_and_no_proxy_still_checks_dns(self):
        response = MagicMock(status_code=302, headers={'location': 'https://127.0.0.1/a.jpg'})
        response.__enter__.return_value = response
        url = 'https://m.media-amazon.com/images/I/test.jpg'
        with patch.object(bg.urllib.request, 'getproxies_macosx_sysconf', return_value={'https': 'http://127.0.0.1:6152'}, create=True), patch.object(bg.requests, 'get', return_value=response) as fetch:
            with self.assertRaises(run_outcome.CrawlStop): bg.read_image_in_memory(url)
            fetch.assert_called_once()
        with patch.object(bg.urllib.request, 'getproxies_macosx_sysconf', return_value={}, create=True), patch.object(bg.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', ('198.18.9.199', 443))]), patch.object(bg.requests, 'get') as fetch:
            with self.assertRaises(run_outcome.CrawlStop): bg.read_image_in_memory(url)
            fetch.assert_not_called()

    def test_dns_failure_is_recoverable_without_fetch(self):
        for error in (bg.socket.gaierror(-3, 'temporary failure'), OSError(60, 'timeout')):
            with self.subTest(error=type(error).__name__), patch.object(bg.socket, 'getaddrinfo', side_effect=error), patch.object(bg.requests, 'get') as fetch:
                with self.assertRaises(core.ImageResolutionError):
                    bg.read_image_in_memory('https://example.com/a.jpg')
                fetch.assert_not_called()
        with patch.object(bg.socket, 'getaddrinfo', return_value=[]):
            with self.assertRaises(core.ImageResolutionError):
                bg.public_image_url('https://example.com/a.jpg', resolve=True)

    def test_dns_fix_keeps_private_address_and_url_rejection(self):
        for address in ('127.0.0.1', '10.0.0.1', '::1'):
            with self.subTest(address=address), patch.object(bg.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', (address, 443))]), patch.object(bg.requests, 'get') as fetch:
                with self.assertRaises(run_outcome.CrawlStop) as caught:
                    bg.read_image_in_memory('https://example.com/a.jpg')
                self.assertEqual(caught.exception.exit_code, 40)
                fetch.assert_not_called()
        for url in ('http://example.com/a.jpg', 'https://localhost/a.jpg', 'https://user:pass@example.com/a.jpg'):
            with self.subTest(url=url), self.assertRaises(run_outcome.CrawlStop):
                bg.public_image_url(url)

    def test_candidate_dns_failure_does_not_cache_exclusion(self):
        rt = self.runtime()
        rt._source_progress = core.SourceProgressStore(self.root / 'progress', {'source': 'dns'})
        candidate = dict(asin='B000000002', candidate_image_url='https://example.com/a.jpg')
        with patch.object(core, 'call_multimodal_embedding_cached', side_effect=core.EmbeddingInputRejected('image')), patch.object(bg.socket, 'getaddrinfo', side_effect=bg.socket.gaierror(-3, 'temporary failure')):
            with self.assertRaises(core.ImageResolutionError):
                core.embed_cascade_candidate(rt, candidate)
        self.assertEqual(list((self.root / 'progress').glob('emb-excluded-*')), [])
        with patch.object(bg, 'read_image_in_memory', return_value='data:image/jpeg;base64,YQ=='), patch.object(core, 'call_multimodal_embedding_cached', return_value=[1., 2.]) as model:
            vector, _, _ = core.embed_cascade_candidate(rt, candidate)
            self.assertEqual(vector, [1., 2.])
            model.assert_called_once_with(rt, 'data:image/jpeg;base64,YQ==')

    def test_empty_candidates_do_not_fetch_or_call_models(self):
        rt = self.runtime()
        with patch.object(bg, 'read_image_in_memory') as read, patch.object(core, 'call_multimodal_embedding_cached') as model:
            result = core.evaluate_competitor_matches(rt, core.ImageReference('https://example.com/a.jpg'), '', [])
            self.assertEqual(result.same_product_count, 0)
            read.assert_not_called(); model.assert_not_called()

    def test_old_mini_cache_reused_only_with_verified_legacy_file(self):
        rt = self.runtime()
        rt._source_progress = core.SourceProgressStore(self.root / 'progress', {'source': 'one'})
        old = self.root / 'old.jpg'; old.write_bytes(b'legacy')
        batch = [dict(asin='B000000002', candidate_image_url='https://example.com/b.jpg')]
        matches = [dict(asin='B000000002', is_same_product=True, confidence=.9, reason='same')]
        key = core.mini_batch_progress_key(rt, old, batch)
        rt._source_progress.put('mini', key, {'matches': matches})
        with patch.object(core, 'call_doubao_mini_verifier') as model:
            result = core.verify_mini_batch_with_checkpoint(rt, core.ImageReference('https://example.com/a.jpg', legacy_path=old), batch)
            self.assertEqual(result, matches); model.assert_not_called()


    def test_completed_model_checkpoint_survives_output_commit_interruption(self):
        rt = self.runtime()
        def collect(page, current, **kwargs):
            current['source_image'] = 'https://example.com/source.jpg'
            page.state.set_current(current)
            return []
        original = core.commit_source_result_shard
        with patch.object(bg.BackgroundPage, 'collect', collect), patch.object(core, 'commit_source_result_shard', side_effect=OSError('disk interrupted')):
            with self.assertRaises(OSError): self.run_job(rt)
        with patch.object(bg.BackgroundPage, 'collect') as browser, patch.object(core, 'evaluate_competitor_matches') as model:
            self.run_job(self.runtime())
            browser.assert_not_called(); model.assert_not_called()
        self.assertEqual(len(core.read_jsonl(self.root / 'case/counts.jsonl')), 1)

    def test_changed_inputs_do_not_discard_paid_checkpoint(self):
        rt = self.runtime()
        def collect(page, current, **kwargs):
            current['source_image'] = 'https://example.com/source.jpg'
            page.state.set_current(current)
            return []
        with patch.object(bg.BackgroundPage, 'collect', collect): self.run_job(rt)
        old = (self.root / 'case/state.json').read_bytes()
        self.input.write_text('ASIN\nB000000002\n')
        with self.assertRaises(run_outcome.CrawlStop): self.run_job(self.runtime())
        self.assertEqual((self.root / 'case/state.json').read_bytes(), old)

    def test_detail_csv_has_source_status_even_when_cascade_early_excludes(self):
        rt = self.runtime(result_mode='detail')
        def collect(page, current, **kwargs):
            current['source_image'] = 'https://example.com/source.jpg'; page.state.set_current(current)
            return []
        evaluation = core.MatchEvaluation([], {}, 11, 'prescreen_excluded', None, '', 'over ten')
        with patch.object(bg.BackgroundPage, 'collect', collect), patch.object(core, 'evaluate_competitor_matches', return_value=evaluation): self.run_job(rt)
        wb = core.load_workbook(self.root / 'case/products_同款竞品结果.xlsx')
        self.assertIn('来源状态', wb.sheetnames)
        self.assertEqual(wb['来源状态'].cell(2, 3).value, 'prescreen_excluded')
        self.assertIsNone(wb['来源状态'].cell(2, 4).value)

    def test_migration_imports_verified_shards_without_touching_old_job(self):
        rt = self.runtime()
        def collect(page, current, **kwargs):
            current['source_image'] = 'https://example.com/source.jpg'; page.state.set_current(current)
            return []
        with patch.object(bg.BackgroundPage, 'collect', collect): self.run_job(rt)
        before = {str(p.relative_to(self.root/'case')): p.read_bytes() for p in (self.root/'case').rglob('*') if p.is_file()}
        next_rt = self.runtime(); next_rt.job_id = 'new'; next_rt.migrate_from_job = 'case'
        with patch.object(bg.BackgroundPage, 'collect') as browser, patch.object(core, 'evaluate_competitor_matches') as model:
            self.run_job(next_rt)
            browser.assert_not_called(); model.assert_not_called()
        after = {str(p.relative_to(self.root/'case')): p.read_bytes() for p in (self.root/'case').rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(len(core.read_jsonl(self.root / 'new/counts.jsonl')), 1)
        report = core.load_json(self.root / 'new/migration_report.json')
        self.assertEqual(report['imported_results'], [2])

    def test_migration_rejects_different_candidate_budget_during_dry_run(self):
        rt = self.runtime(); rt.migrate_from_job = '../escape'
        with patch.object(bg, 'cli_command'), patch.object(core, 'prepare_vision_provider'):
            with self.assertRaises(run_outcome.CrawlStop): bg.run(rt, dry_run=True)

    def test_pending_navigation_resolves_original_target_without_requery(self):
        source = snapshot()
        url = 'https://www.amazon.com/stylesnap?q=x'
        page, bridge, state, _ = self.page([source])
        page.attach()
        state.data['pending_navigation'] = url
        page.attached = False
        bridge.snapshots[0] = dict(source, url=url, result_page=True)
        bridge.doc = ''
        page.attach()
        self.assertNotIn('pending_navigation', state.data)
        self.assertEqual(page.url, url)
        self.assertNotIn('navigate', bridge.actions)

    def stalled_page(self):
        original = snapshot()
        url = 'https://www.amazon.com/dp/B000000002'
        stalled = dict(original, url=url, asin='B000000002', ready=False)
        page, bridge, state, clock = self.page([original, dict(stalled, ready=True)])
        page.attach()
        bridge.snapshots[0] = stalled
        bridge.doc = ''
        state.data['pending_navigation'] = url
        page.attached = False
        page.runtime.page_timeout = 4
        return page, bridge, state, clock

    def test_stalled_committed_destination_reloads_once_then_recovers(self):
        page, bridge, state, clock = self.stalled_page()
        page.attach()
        self.assertEqual(bridge.actions.count('navigate'), 1)
        page.runtime.safety.before_remote_action.assert_called_once()
        self.assertEqual(page.url, 'https://www.amazon.com/dp/B000000002')
        self.assertNotIn('pending_navigation', state.data)
        self.assertNotIn('pending_navigation_reload', state.data)
        self.assertGreaterEqual(clock.t, 4)

    def test_stalled_reload_budget_survives_restart(self):
        page, bridge, state, clock = self.stalled_page()
        bridge.snapshots[1]['ready'] = False
        with self.assertRaises(run_outcome.CrawlStop) as caught: page.attach()
        self.assertEqual(caught.exception.exit_code, 20)
        self.assertEqual(bridge.actions.count('navigate'), 1)
        self.assertIn('pending_navigation_reload', state.data)
        restarted = bg.BackgroundPage(page.runtime, state, bridge=bridge, clock=clock.now, sleep=clock.sleep)
        with self.assertRaises(run_outcome.CrawlStop) as caught: restarted.attach()
        self.assertEqual(caught.exception.exit_code, 20)
        self.assertEqual(bridge.actions.count('navigate'), 1)

    def test_stalled_reload_checks_identity_after_throttling(self):
        page, bridge, state, _ = self.stalled_page()
        def changed(*_): bridge.snapshots[0]['url'] = 'https://www.amazon.com/s?k=user'
        page.runtime.safety.before_remote_action.side_effect = changed
        with self.assertRaises(run_outcome.CrawlStop): page.attach()
        self.assertNotIn('navigate', bridge.actions)

    def test_stalled_blank_or_risky_page_never_reloads(self):
        for mode in ('blank', 'captcha', 'unknown'):
            page, bridge, state, _ = self.stalled_page()
            if mode == 'blank': bridge.snapshots[0]['source_image'] = ''
            elif mode == 'unknown': bridge.snapshots[0]['url'] = 'https://www.amazon.com/dp/B000000003'
            else:
                bridge.snapshots[0]['captcha'] = True
                page.runtime.safety.trip.side_effect = run_outcome.needs_human('captcha')
            with self.subTest(mode=mode), self.assertRaises(run_outcome.CrawlStop): page.attach()
            self.assertNotIn('navigate', bridge.actions)

    def test_pending_navigation_changed_by_user_stops(self):
        page, bridge, state, _ = self.page([snapshot()])
        page.attach()
        state.data['pending_navigation'] = 'https://www.amazon.com/stylesnap?q=x'
        page.attached = False
        bridge.snapshots[0]['url'] = 'https://www.amazon.com/s?k=user'
        with self.assertRaises(run_outcome.CrawlStop): page.attach()
        self.assertNotIn('navigate', bridge.actions)

    def test_user_count_pause_commits_then_stops_before_next_source(self):
        self.input.write_text('ASIN\nB000000001\nB000000002\n', encoding='utf-8')
        job = self.root / 'case'
        job.mkdir()
        (job / 'pause_after_count.json').write_text('{"completed_count":1}')
        seen = []
        def collect(page, current, **kwargs):
            seen.append(current['source_asin'])
            current['source_image'] = 'https://example.com/source.jpg'
            page.state.set_current(current)
            return []
        evaluation = core.MatchEvaluation([], {}, 0, 'verified_zero', 0, '', 'empty')
        with patch.object(bg.BackgroundPage, 'collect', collect), patch.object(core, 'evaluate_competitor_matches', return_value=evaluation):
            with self.assertRaises(run_outcome.CrawlStop) as caught: self.run_job(self.runtime())
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertEqual(seen, ['B000000001'])
        self.assertEqual(len(core.read_jsonl(job / 'counts.jsonl')), 1)
        with patch.object(bg.BackgroundPage, 'collect') as browser:
            with self.assertRaises(run_outcome.CrawlStop): self.run_job(self.runtime())
            browser.assert_not_called()
        self.assertTrue((job / 'pause_after_count.json').exists())

    def test_unattended_uses_ten_action_rest_policy(self):
        rt = self.runtime(operation_mode='unattended')
        self.assertEqual((rt.batch_pause_pages_min, rt.batch_pause_seconds_min, rt.batch_pause_seconds_max), (10, 20, 35))
        observed = []
        def factory(**kwargs):
            observed.append(kwargs)
            return self.safety(**kwargs)
        def collect(page, current, **kwargs):
            current['source_image'] = 'https://example.com/source.jpg'; page.state.set_current(current)
            return []
        with patch.object(bg, 'cli_command'), patch.object(core, 'prepare_vision_provider'), patch.object(bg, 'LocalSafetyController', side_effect=factory), patch.object(bg.BackgroundPage, 'collect', collect):
            bg.run(rt)
        self.assertEqual(observed[0]['batch_pause_pages_min'], 10)
        self.assertEqual(observed[0]['batch_pause_seconds_min'], 20)

    def test_clock_counter_survives_new_controller_and_long_rest(self):
        import datetime as dt
        now = [dt.datetime(2026, 1, 1)]
        waits = []
        def setup_controller():
            safety = LocalSafetyController(self.root/'clock', clock=lambda: now[0])
            def wait(deadline, reason):
                waits.append((deadline-now[0]).total_seconds())
                now[0] = max(now[0], deadline)
            safety._wait_until = wait
            return safety
        with patch('safety_control.random.uniform', side_effect=lambda a,b:a):
            first = setup_controller()
            for _ in range(20): first.before_remote_action('source A')
            second = setup_controller()
            for _ in range(81): second.before_remote_action('source B / resumed')
        self.assertEqual(json.loads(second.traffic_path.read_text())['actions_count'], 101)
        self.assertIn(600, waits)
        self.assertIn(180, waits)

    def test_retry_stage_does_not_touch_other_tabs_and_is_counted(self):
        rt = self.runtime()
        rt.amazon_page_unavailable_retry_schedule_seconds = ((0,0),)
        calls = []
        def collect(page, current, **kwargs):
            calls.append('collect')
            current['search_url'] = 'https://www.amazon.com/stylesnap?q=x'
            current['source_image'] = 'https://example.com/source.jpg'
            page.state.set_current(current)
            if len(calls) == 1: raise core.TransientAmazonPageUnavailable('slow', reason='expected_content_missing')
            return []
        with patch.object(bg.BackgroundPage, 'collect', collect), patch.object(bg.BackgroundPage, 'navigate') as navigate:
            self.run_job(rt)
            navigate.assert_called_once_with('https://www.amazon.com/stylesnap?q=x')
        self.assertEqual(len(calls), 2)

    def test_launcher_forwards_all_new_flags_without_starting_browser(self):
        import run_amazon_image_competitor_crawl as launcher
        import subprocess
        script = Path(launcher.__file__)
        result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        for name in ['--confirm-sellersprite-logged-out', '--rebind', '--migrate-from-job']:
            self.assertIn(name, result.stdout)
        command = launcher.build_command(self.root/'config.json', False, False, confirm_logged_out=True, rebind=True, migrate_from_job='old')
        self.assertIn('--confirm-sellersprite-logged-out', command)
        self.assertEqual(command[-2:], ['--migrate-from-job', 'old'])

    def test_image_policy_spacing_and_both_hundred_action_rests(self):
        import datetime as dt
        for mode, spacing, batch, long_rest in [('supervised',(4,6),20,(60,120)), ('unattended',(8,15),10,(120,180))]:
            for endpoint in [0, 1]:
                with self.subTest(mode=mode, endpoint=endpoint):
                    now = [dt.datetime(2026, 1, 1)]
                    root = self.root / (mode + str(endpoint))
                    def controller():
                        c = LocalSafetyController(root, clock=lambda: now[0], mode=mode, traffic_profile='image')
                        c._wait_until = lambda deadline, reason: now.__setitem__(0, deadline)
                        return c
                    c = controller()
                    with patch('safety_control.random.uniform', side_effect=lambda low,high:(low,high)[endpoint]):
                        for index in range(101):
                            if index == 51: c = controller()
                            before = now[0]
                            c.before_remote_action('image')
                            elapsed = (now[0]-before).total_seconds()
                            expected = 0 if index == 0 else long_rest[endpoint] if index == 100 else (20,35)[endpoint] if index % batch == 0 else spacing[endpoint]
                            self.assertEqual(elapsed, expected)
                    self.assertEqual(json.loads(c.traffic_path.read_text())['actions_count'], 101)

    def test_interrupted_image_rest_preserves_original_deadline(self):
        import datetime as dt
        now = [dt.datetime(2026,1,1)]
        c = LocalSafetyController(self.root/'rest', clock=lambda:now[0], traffic_profile='image')
        c._wait_until = lambda deadline,reason: now.__setitem__(0, deadline)
        with patch('safety_control.random.uniform', side_effect=lambda a,b:a):
            for _ in range(20): c.before_remote_action('image')
            c._wait_until = MagicMock(side_effect=KeyboardInterrupt)
            with self.assertRaises(KeyboardInterrupt): c.before_remote_action('image')
            deadline = json.loads(c.traffic_path.read_text())['rest_until']
            now[0] += dt.timedelta(seconds=5)
            c = LocalSafetyController(self.root/'rest', clock=lambda:now[0], traffic_profile='image')
            c._wait_until = lambda until,reason: now.__setitem__(0, until)
            c.before_remote_action('resumed')
        self.assertEqual(now[0].isoformat(), deadline)

    def test_temporary_model_failure_auto_recovers_without_browser_recollection(self):
        calls=[]
        def collect(page,current, **kwargs):
            calls.append(current['source_id'])
            current['source_image']='https://example.com/source.jpg';page.state.set_current(current)
            return []
        evaluation=core.MatchEvaluation([],{},0,'verified_zero',0,'','no match')
        with patch.object(bg.BackgroundPage,'collect',collect), patch.object(bg,'wait_for_recovery') as wait, patch.object(core,'evaluate_competitor_matches',side_effect=[core.EmbeddingProviderError('temporary timeout'),evaluation]) as model:
            self.run_job(self.runtime())
            self.assertEqual(len(calls),1)
            self.assertEqual(model.call_count,2)
            wait.assert_called_once()
        self.assertEqual(core.read_jsonl(self.root/'case/counts.jsonl')[0]['same_product_count'],0)

    def test_repeated_model_failure_skips_source_and_continues_without_false_zero(self):
        self.input.write_text('ASIN\nB000000001\nB000000002\n')
        def collect(page,current, **kwargs):
            current['source_image']='https://example.com/source.jpg';page.state.set_current(current)
            return []
        evaluation=core.MatchEvaluation([],{},0,'verified_zero',0,'','no match')
        with patch.object(bg.BackgroundPage,'collect',collect), patch.object(bg,'wait_for_recovery'), patch.object(core,'evaluate_competitor_matches',side_effect=[core.EmbeddingProviderError('timeout'),core.EmbeddingProviderError('timeout'),evaluation]) as model:
            self.run_job(self.runtime())
            self.assertEqual(model.call_count,3)
        rows=core.read_jsonl(self.root/'case/counts.jsonl')
        self.assertEqual(rows[0]['processing_status'],'skipped')
        self.assertIsNone(rows[0]['same_product_count'])
        self.assertEqual(rows[1]['same_product_count'],0)

    def test_risk_and_human_stop_never_auto_retry(self):
        from safety_control import SafetyPausedError
        for error in [SafetyPausedError('rate limit'),run_outcome.needs_human('changed tab'),core.FatalEmbeddingProviderError('invalid credentials')]:
            rt=self.runtime();rt.job_id=str(type(error).__name__)
            with patch.object(bg.BackgroundPage,'collect',side_effect=error) as collect,patch.object(bg,'wait_for_recovery') as wait:
                with self.assertRaises(type(error)):self.run_job(rt)
                collect.assert_called_once();wait.assert_not_called()

    def test_transient_commit_failure_retries_locally_without_repaying_model(self):
        def collect(page,current, **kwargs):
            current['source_image']='https://example.com/source.jpg';page.state.set_current(current)
            return []
        actual=core.commit_source_result_shard
        failures=[True]
        def commit(*args):
            if failures.pop() if failures else False: raise PermissionError('temporary lock')
            return actual(*args)
        with patch.object(bg.BackgroundPage,'collect',collect),patch.object(core,'commit_source_result_shard',side_effect=commit) as writer,patch.object(bg.time,'sleep'),patch.object(core,'evaluate_competitor_matches',wraps=core.evaluate_competitor_matches) as model:
            self.run_job(self.runtime())
            self.assertEqual(writer.call_count,2);model.assert_called_once()
        self.assertEqual(len(core.read_jsonl(self.root/'case/counts.jsonl')),1)

    def test_recovery_wait_persists_deadline_and_heartbeats(self):
        rt=self.runtime();rt.safety=MagicMock();state=State();clock=Clock()
        with patch.object(bg.time,'time',clock.now),patch.object(bg.time,'sleep',side_effect=clock.sleep),patch.object(bg.random,'uniform',return_value=20):
            bg.wait_for_recovery(rt,state,'temporary')
        self.assertEqual(clock.t,20)
        self.assertEqual(len(state.data['automatic_recovery_events']),1)
        state.data['automatic_recovery']={'reason':'resumed','until':25}
        with patch.object(bg.time,'time',clock.now),patch.object(bg.time,'sleep',side_effect=clock.sleep),patch.object(bg.random,'uniform') as rng:
            bg.wait_for_recovery(rt,state,'')
            rng.assert_not_called()
        self.assertEqual(clock.t,25)


if __name__ == '__main__': unittest.main()
