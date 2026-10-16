"""New execution boundaries with retained receipts; no provider/model requests."""
from copy import deepcopy
from io import BytesIO
import unittest
from unittest.mock import patch
from common import atomic_write_json, load_json, sha256_file, sha256_json
from execution_efficiency import DEFAULTS, REVISION


def enable(task):
    task.update(execution_efficiency_revision=REVISION, execution_efficiency=deepcopy(DEFAULTS))


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.task = {'primary_scenario_id': 'product_entry', 'product_scope': {
            'objects': [{'object_id': 'towel', 'kind': 'product', 'relation': 'target', 'source_refs': ['E'], 'scope_status': 'included', 'right_types': ['copyright']}],
            'facts': [{'fact_id': 'material', 'status': 'unknown', 'question': '纤维及织造结构未知', 'source_refs': ['E']}],
            'directions': []}}
        enable(self.task)
        self.task['investigation_profile'] = [{'scenario_id': 'product_entry', 'object_id': 'towel', 'right_type': 'patent',
            'intensity': 'baseline', 'reason': '现有资料仅显示普通印花毛巾', 'fact_ids': ['material'], 'evidence_refs': ['E'],
            'questions': ['是否存在材料、织造或功能处理线索'], 'escalation_conditions': ['出现特殊纤维或准确专利声明'],
            'limitations': ['内部资料未提供']}]

    def test_light_is_not_inapplicable_and_unknown_is_stable(self):
        from investigation_policy import resolve_discovery_work_policy
        a = resolve_discovery_work_policy(self.task, scenario_id='product_entry', right_type='patent')
        self.assertEqual(a['intensity'], 'baseline')
        self.assertEqual(a['completion_rule'], 'existing_coverage_only')
        self.assertEqual(a['missing_facts'], resolve_discovery_work_policy(self.task, scenario_id='product_entry', right_type='patent')['missing_facts'])
        self.assertEqual(resolve_discovery_work_policy(self.task, right_type='copyright')['intensity'], 'focused')

    def test_positive_escalates_and_does_not_delete_other_rights(self):
        from investigation_policy import resolve_discovery_work_policy
        from product_scope import RIGHTS
        before = deepcopy(self.task)
        self.assertEqual(resolve_discovery_work_policy(self.task, right_type='patent', positive_candidate=True)['intensity'], 'focused')
        for right in RIGHTS:
            self.assertIsNotNone(resolve_discovery_work_policy(self.task, right_type=right))
        self.assertEqual(self.task, before)

    def test_unknown_reference_rejected_and_old_task_unchanged(self):
        from investigation_policy import validate_profile, resolve_discovery_work_policy
        self.task['investigation_profile'][0]['evidence_refs'] = ['imagined']
        with self.assertRaisesRegex(ValueError, 'NOT_BOUND'):
            validate_profile(self.task, self.task['investigation_profile'])
        self.task.pop('execution_efficiency_revision')
        self.assertIsNone(resolve_discovery_work_policy(self.task, right_type='patent'))


class MediaTests(unittest.TestCase):
    def setUp(self):
        import test_public_identity
        from source_result_processing import make_index
        self.f = test_public_identity.PublicIdentityTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        enable(self.f.task)
        raw = {'visual_matches': [{'title': 'Towel ' + str(i), 'link': 'https://example.test/' + str(i),
                'thumbnail': 'https://images.example.test/shared.png'} for i in range(18)]}
        path = self.f.root / 'lens.json'; atomic_write_json(path, raw)
        run = self.f.evidence['source_runs'][-1]
        run['payload_digest'] = sha256_file(path)
        run['result_processing'] = make_index(self.f.task, provider='serpapi_google_lens', evidence_type='copyright',
            status='success', submission_state='submitted', raw_body=path.read_bytes(), raw_suffix='json', normalized={},
            coverage={'schema_valid': True, 'retrieved_hits': 18}, payload_digest=run['payload_digest'])
        self.ids = ['C' + str(i) for i in range(18)]
        self.f.candidates = {'copyright_assets': [{'candidate_id': cid, 'right_type': 'copyright', 'jurisdiction': 'US',
            'sources': [{'source_run_id': 'LENS-R', 'source_record_sha256': run['result_processing']['rows'][i]['raw_sha256']}]} for i,cid in enumerate(self.ids)]}
        for name, value in [('task.json', self.f.task), ('evidence.json', self.f.evidence), ('normalized-candidates.json', self.f.candidates)]:
            atomic_write_json(self.f.root / name, value)
        from PIL import Image
        stream = BytesIO(); Image.new('RGB', (20, 20), 'red').save(stream, format='PNG'); self.image = stream.getvalue()

    def test_18_candidates_one_download_no_query_or_country_mutation(self):
        from candidate_media import collect
        from visual_triage_host import batches
        before = load_json(self.f.root / 'evidence.json')
        with patch('candidate_media.download', return_value=(self.image, '.png', (20,20), 'https://images.example.test/shared.png')) as fetch:
            result = collect(self.f.root, self.ids)
            self.assertEqual(fetch.call_count, 1)
            again = collect(self.f.root, self.ids)
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result, again)
        self.assertEqual(len(result), 18)
        self.assertEqual(len(batches([{'candidate_id':cid} for cid in self.ids])), 3)
        entries = load_json(self.f.root / 'supplemental-evidence.json')['evidence']
        self.assertEqual(len({row['evidence_id'] for row in entries}), 18)
        self.assertTrue(all(row['thumbnail'] and row['not_full_rights_views'] for row in entries))
        self.assertEqual(before, load_json(self.f.root / 'evidence.json'))

    def test_failed_url_never_becomes_low_similarity_or_auto_retry(self):
        from candidate_media import collect
        with patch('candidate_media.download', side_effect=ValueError('MEDIA_INVALID_IMAGE')) as fetch:
            result = collect(self.f.root, self.ids)
            collect(self.f.root, self.ids)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(all(row['status'] == 'needs_info' and 'decision' not in row for row in result.values()))

    def test_expired_budget_stops_before_dns_and_slow_headers_have_wall_deadline(self):
        from candidate_media import download
        import time, threading
        from urllib.parse import urlsplit
        with patch('candidate_media.public_address') as resolve, self.assertRaises(TimeoutError):
            download('https://example.com/a', deadline=time.time()-1)
        resolve.assert_not_called()
        class Socket:
            def __init__(self): self.closed=threading.Event()
            def settimeout(self, value): pass
            def shutdown(self, how): self.closed.set()
        class Connection:
            def __init__(self, *args): self.sock=Socket()
            def request(self,*args,**kwargs): pass
            def getresponse(self):
                self.sock.closed.wait(1)
                raise OSError('Header stream interrupted')
            def close(self): pass
        started=time.monotonic()
        with patch('candidate_media.public_address',return_value=(urlsplit('https://example.com/a'),'8.8.8.8')), \
             patch('candidate_media.PublicConnection',Connection), self.assertRaises(OSError):
            download('https://example.com/a',timeout=0.02)
        self.assertLess(time.monotonic()-started,0.8)

    def test_dns_wait_is_bounded_by_url_deadline(self):
        from candidate_media import public_address
        import time
        def slow(*args, **kwargs):
            time.sleep(0.05)
            return [(2, 1, 6, '', ('8.8.8.8', 443))]
        with patch('socket.getaddrinfo', side_effect=slow), self.assertRaisesRegex(TimeoutError, 'DNS_TIMEOUT'):
            public_address('https://example.com/a', timeout=0.005)

    def test_changed_receipt_is_rejected_before_request(self):
        from candidate_media import collect
        (self.f.root / 'lens.json').write_text('{}')
        with patch('candidate_media.download') as fetch, self.assertRaises(ValueError):
            collect(self.f.root, self.ids)
        fetch.assert_not_called()

    def test_refusal_names_the_address_class_without_relaxing_the_public_address_rule(self):
        from candidate_media import public_address, address_class
        # r5d4 (F3): 198.18.0.0/15 is admitted only on a machine whose probe confirmed a fake-IP proxy; this machine's
        # probe would be answered by the patched resolver below, so the mode is pinned to "not confirmed"
        import candidate_media
        saved = dict(candidate_media._FAKE_IP_MODE)
        self.addCleanup(lambda: (candidate_media._FAKE_IP_MODE.clear(), candidate_media._FAKE_IP_MODE.update(saved)))
        candidate_media._FAKE_IP_MODE['value'] = False
        cases = (('198.18.0.37', 'benchmarking_198.18.0.0/15'), ('127.0.0.1', 'loopback'),
                 ('169.254.169.254', 'link_local'), ('100.64.3.4', 'shared_100.64.0.0/10'), ('192.168.1.8', 'private'))
        for address, name in cases:
            with self.subTest(address=address):
                self.assertEqual(address_class(address), name)
                with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', (address, 443))]), \
                        self.assertRaisesRegex(ValueError, 'MEDIA_PUBLIC_ADDRESS_REQUIRED:' + name):
                    public_address('https://example.com/a')
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('198.18.0.37', 443)), (2, 1, 6, '', ('8.8.8.8', 443))]), \
                self.assertRaises(ValueError):
            public_address('https://example.com/a')
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]):
            self.assertEqual(public_address('https://example.com/a')[1], '8.8.8.8')

    def test_public_address_and_decode_guards(self):
        from candidate_media import public_address, decode_image
        for url in ('http://example.com/a', 'https://user:password@example.com/a', 'https://example.com/a?api_key=bad'):
            with self.assertRaises(ValueError): public_address(url)
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaisesRegex(ValueError, 'PUBLIC_ADDRESS'): public_address('https://example.com/a')
        with self.assertRaises(Exception): decode_image(b'not an image')


class VisualOutputTests(unittest.TestCase):
    def setUp(self):
        self.packet = {'product_image_ids':['P'], 'units':[{'unit_id':'U', 'candidate_image_ids':['C-image'],
            'evidence_refs':['E'], 'template': {'candidate_id':'C','scenario_id':'S','jurisdiction':'US','right_type':'design'}}]}
        self.row = {'unit_id':'U','read_image_ids':['P','C-image'], 'adequate':True, 'same_points':'两者均为矩形',
            'differences':'边缘构图不同','limitations':'仅代表图', 'decision':'not_selected'}

    def test_missing_wrong_duplicate_units_and_unattached_images_rejected(self):
        from visual_triage_host import decisions_from_output
        for rows in ([], [dict(self.row,unit_id='wrong')], [self.row,self.row], [dict(self.row,read_image_ids=['P','other'])]):
            with self.assertRaises(ValueError): decisions_from_output({'decisions':rows},self.packet,'S')

    def test_technical_and_inadequate_cannot_be_excluded(self):
        from visual_triage_host import decisions_from_output
        self.row['adequate'] = False
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'): decisions_from_output({'decisions':[self.row]},self.packet,'S')
        self.row.update(adequate=True,decision='selected')
        self.packet['units'][0]['template']['right_type'] = 'patent'
        with self.assertRaisesRegex(ValueError,'TECHNICAL'): decisions_from_output({'decisions':[self.row]},self.packet,'S')

    def test_native_parser_does_not_allow_tools_or_assessment_schema_substitution(self):
        from report_review_host import parse_json_trace, parse_agent_trace
        import json
        events = [{'type':'thread.started','thread_id':'S'},{'type':'turn.started'},
            {'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'decisions':[self.row]})}},
            {'type':'turn.completed'}]
        trace = '\n'.join(map(json.dumps,events))
        self.assertEqual(parse_json_trace(trace)[0], 'S')
        with self.assertRaises(ValueError): parse_agent_trace(trace)
        events[2]['item']['type']='command_execution'
        with self.assertRaisesRegex(ValueError,'TOOL_ACTIVITY'): parse_json_trace('\n'.join(map(json.dumps,events)))


class MultiCountryTests(unittest.TestCase):
    def setUp(self):
        import test_public_identity
        self.f = test_public_identity.PublicIdentityTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.task.update(public_identity_execution_revision='public-identity-multicountry-v2',
                           target_jurisdictions=['US','GB','FR','DE','IT','ES','JP'])
        original = deepcopy(self.f.plan['queries']['asset_provenance'])
        self.f.request.pop('shared_query_ids')
        mapping = {'US': [row['query_id'] for row in original]}
        for country in self.f.task['target_jurisdictions'][1:]:
            mapping[country] = []
            for row in original:
                new = {**row, 'jurisdiction':country, 'query_id':country + '-' + row['query_id']}
                self.f.plan['queries']['asset_provenance'].append(new); mapping[country].append(new['query_id'])
                prior = next(e for e in self.f.evidence['collections']['official_verifications'] if e['query_id']==row['query_id'])
                item = deepcopy(prior)
                item.update(evidence_id=country + '-' + prior['evidence_id'],query_id=new['query_id'],source_run_id='RUN-'+new['query_id'],plan_entry_sha256=sha256_json(new))
                self.f.evidence['collections']['official_verifications'].append(item)
                self.f.evidence['source_runs'].append({'run_id':item['source_run_id'],'query_id':new['query_id'],
                    'plan_entry_sha256':sha256_json(new),'status':'success','jurisdiction':country})
        self.f.request['shared_query_ids_by_country'] = mapping
        for name,value in [('task.json',self.f.task),('search-plan.json',self.f.plan),('evidence.json',self.f.evidence)]:
            atomic_write_json(self.f.root/name,value)

    def test_seven_country_bindings_keep_source_and_right_country_separate(self):
        from public_identity import record, current
        event = record(self.f.root,self.f.request)
        self.assertEqual(len(event['binding']['shared_public_packages']),35)
        self.assertEqual(event['binding']['sources'][0]['query_jurisdiction'],'US')
        self.assertEqual(event['binding']['sources'][0]['right_jurisdiction'],'UNLOCATED')
        self.assertEqual(current(self.f.task,load_json(self.f.root/'evidence.json'),self.f.candidates,self.f.ledger,self.f.scope),event)

    def test_us_only_cannot_close_other_countries(self):
        from public_identity import record
        self.f.request['shared_query_ids_by_country']={'US':self.f.request['shared_query_ids_by_country']['US']}
        with self.assertRaisesRegex(ValueError,'ALL_COUNTRIES'): record(self.f.root,self.f.request)


class FollowupIdentityTests(unittest.TestCase):
    def test_renaming_cannot_buy_attempt_and_changed_fact_can_reopen(self):
        from followup_identity import renamed_attempt
        task={};enable(task);task['execution_efficiency_revision']='execution-efficiency-v1'
        action={'action_id':'old','kind':'source_lookup','provider':'p','operation':'candidate_detail','params':{'q':'US1'},
                'followup_basis':{'missing_fact':'claims','existing_evidence_refs':['E']}}
        old={'annotation_id':'A','candidate_id':'C','candidate_content_sha256':'hash','next_actions':[action]}
        prior={'query_id':'Q','triage_decision_id':'A','triage_action_id':'old'}
        evidence={'source_runs':[{'run_id':'R','query_id':'Q','provider':'p','plan_entry_sha256':sha256_json(prior),
                                 'submission_state':'unknown','status':'failed'}]}
        ledger={'annotations':[old]};plan={'queries':{'p':[prior]}}
        new=dict(old,annotation_id='B'); renamed=dict(action,action_id='new',purpose='different label')
        result=renamed_attempt(task,plan,evidence,ledger,'p',{'query_id':'new'},new,renamed)
        self.assertEqual(result['reason'],'TRIAGE_ATTEMPT_STATE_UNKNOWN')
        new['candidate_content_sha256']='changed material'
        self.assertIsNone(renamed_attempt(task,plan,evidence,ledger,'p',{'query_id':'new'},new,renamed))


class TimingTests(unittest.TestCase):
    def test_observation_is_read_only_unless_outer_operation_opts_in(self):
        from runtime_timing import observed_step, timed_step, FILENAME
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with observed_step('work_view'):
                pass
            self.assertEqual(list(root.iterdir()), [])
            with timed_step(root, 'report_publish'):
                with observed_step('work_view'):
                    pass
            import json
            rows = [json.loads(line) for line in (root / FILENAME).read_text().splitlines()]
            self.assertEqual([r['stage'] for r in rows], ['work_view', 'report_publish'])
            self.assertTrue(all(r['elapsed_scope'] == 'step_inclusive' for r in rows))


if __name__ == '__main__':
    unittest.main()
