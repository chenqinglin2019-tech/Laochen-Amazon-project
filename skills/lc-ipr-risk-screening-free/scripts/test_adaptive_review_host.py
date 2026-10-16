"""Independent real host scheduling with synthetic native logs; no model/network.

Only native execution, ChatGPT login and the platform isolation probe are replaced.
Preparation, freezing, packet construction, dispatch, recording and validation are real.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file, sha256_json
from execution_efficiency import REVISION, DEFAULTS
from offline_test_support import isolated_test_environment


class HostFixture:
    def __init__(self, root, *, adaptive=True, kind='visual', fail_slot=None, count_revision=True):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.source=self.root/'task'; self.source.mkdir()
        self.output=self.root/'review'; self.output.mkdir()
        self.fail_slot=fail_slot; self.failed=False; self.calls=[]; self.lock=threading.Lock()
        countries=['US','GB','FR','DE','IT','ES','JP'] if kind=='seven-country-large' else ['US']
        self.task={'schema_version':'2.4-free','task_id':'OFFLINE-HOST','product':{'title':'Offline '+kind},
            'target_jurisdictions':countries,'images':[], 'review_policy_revision':'final-double-review-v1', 'screening_revision':'recall-integrity-v1',
            'final_review_execution_revision':'adaptive-double-review-v2' if adaptive else 'module-double-review-v1',
            'assessment_scenarios':[{'scenario_id':'S','type':'product_entry'}]}
        if adaptive:
            self.task.update(execution_efficiency_revision=REVISION,execution_efficiency=deepcopy(DEFAULTS))
            if count_revision:
                self.task['review_unit_count_revision']='selected-scope-units-v1'
        from test_report_estimate import PNG
        image=self.source/'product-pattern.png'; image.write_bytes(PNG)
        originals=[{'evidence_id':'E-IMAGE','path':str(image),'sha256':sha256_file(image),
            'source_url':'https://example.org/offline-pattern.png','bytes':image.stat().st_size}]
        if kind!='visual':
            text=self.source/'claim-text.txt'
            text.write_text(('Synthetic claim 1: shaft, guard and cutting disc.\n'*400)
                           if kind=='technical' else ('Synthetic seven-country retained text.\n'*2000))
            originals.append({'evidence_id':'E-TEXT','path':str(text),'sha256':sha256_file(text),
                'source_url':'https://example.org/offline-claims','bytes':text.stat().st_size})
        for name,value in [('task',self.task),('evidence',{'collections':{'originals':originals}}),
                           ('search-plan',{'queries':{}}),('normalized-candidates',{})]:
            atomic_write_json(self.source/(name+'.json'),value)
        self.binary=self.root/'fake-native'; self.binary.write_text('offline dummy never executed')
        from review_readiness import prepare_review_context, freeze_input
        self.context=prepare_review_context(self.source)
        self.meta=freeze_input(self.source,self.output/'frozen.json',prepared_context=self.context)
        self.frozen=load_json(self.output/'frozen.json')

    def native(self,command,prompt,workspace,trace_path,stderr_path,timeout):
        slot=(trace_path.parent.parent.name,trace_path.parent.name)
        with self.lock:
            number=len(self.calls)+1; self.calls.append(slot)
            fail=slot==self.fail_slot and not self.failed
            if fail:self.failed=True
        stderr_path.write_text('offline synthetic model fixture')
        if fail:
            trace_path.write_text('{"type":"turn.started"}\n')
            return SimpleNamespace(returncode=1,pid=10000+number),trace_path.read_text(),''
        packet=load_json(trace_path.parent/'packet.json')
        statement={'overall':'No conclusion beyond retained limitations',
            'scope':'Every supplied necessary scope','limitations':'Offline synthetic judgments; no legal conclusion'}
        raw={'reviewer':'synthetic-'+slot[0],'assessments':[], 'future_applications':[], 'enforcement_signals':[],
             'coverage_confidence_cap':'低','coverage_confidence_reasoning':'Synthetic evidence limits',
             'final_review_statement':statement}
        if slot[1]=='summary':
            raw['module_review_digests']=[sha256_json(row) for row in packet['modules']]
        else:
            from module_review import required_scopes,GROUPS
            from record_independent_review import expand_pending
            rights=(packet.get('module_scope') or {}).get('right_types') or set().union(*GROUPS.values())
            raw['assessments']=[expand_pending({**scope,'assessment_object':'product','risk':None,
                'assessment_status':'pending','pending_reasoning':'The synthetic original cannot establish legal status',
                'evidence_refs':['E-IMAGE']},packet['task']) for scope in required_scopes(packet['task'],rights)]
            raw['material_observations']={row['material_id']:{'source_refs':row['source_refs'],
                'observation':'Read the supplied synthetic material', 'limitations':'Synthetic fixture only'}
                for row in packet.get('retained_originals',{}).get('materials',[])}
        trace=[{'type':'thread.started','thread_id':'synthetic-session-'+str(number)}, {'type':'turn.started'},
            {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(raw)}}, {'type':'turn.completed'}]
        output='\n'.join(json.dumps(row) for row in trace)+'\n'; trace_path.write_text(output)
        return SimpleNamespace(returncode=0,pid=10000+number),output,''

    def run(self,*,resume=False):
        from module_review import run_module_pair
        with patch('report_review_host.run_native_logged',side_effect=self.native), \
             patch('native_review_jobs._probe',return_value=[]), \
             patch('report_review_host._probe',return_value=[]), \
             patch('macos_review_host.require_chatgpt_auth'):
            paths=run_module_pair(self.source,self.output,self.binary,self.frozen,self.meta,self.context,
                timeout=10,max_parallel=2,resume_existing=resume,isolation='macos-sandbox')
        return [load_json(path) for path in paths]


class AdaptiveHostSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.isolation=isolated_test_environment(); self.isolation.__enter__()
        self.addCleanup(self.isolation.__exit__,None,None,None)

    def test_small_package_dispatches_exactly_two_real_host_slots(self):
        fixture=HostFixture(self.root/'small')
        reviews=fixture.run()
        self.assertEqual(sorted(fixture.calls),[('1','integrated'),('2','integrated')])
        self.assertEqual(len(reviews),2)
        self.assertTrue(all('integrated_execution' in r['review_context']['execution'] for r in reviews))
        self.assertEqual(load_json(fixture.output/'freeze-receipt.json')['native_session_count'],2)

    def test_large_seven_country_package_dispatches_six_modules_and_two_summaries(self):
        fixture=HostFixture(self.root/'large',kind='seven-country-large')
        reviews=fixture.run()
        self.assertEqual(len(fixture.calls),8)
        self.assertEqual(len(set(fixture.calls)),8)
        self.assertTrue(all('module_execution' in r['review_context']['execution'] for r in reviews))
        self.assertEqual(load_json(fixture.output/'freeze-receipt.json')['native_session_count'],8)

    def test_failed_integrated_slot_only_is_dispatched_on_resume(self):
        fixture=HostFixture(self.root/'resume',fail_slot=('2','integrated'))
        with self.assertRaisesRegex(ValueError,'EXECUTION_FAILED'): fixture.run()
        before=list(fixture.calls)
        first_trace=(fixture.output/'1/integrated/events.jsonl').read_bytes()
        fixture.run(resume=True)
        self.assertEqual(len(before),2)
        self.assertEqual(fixture.calls[2:],[('2','integrated')])
        self.assertEqual((fixture.output/'1/integrated/events.jsonl').read_bytes(),first_trace)
        self.assertTrue((fixture.output/'2/integrated.attempt-1/events.jsonl').is_file())

    def test_failed_first_slot_recovers_already_finished_second_trace(self):
        fixture=HostFixture(self.root/'resume-first',fail_slot=('1','integrated'))
        with self.assertRaisesRegex(ValueError,'EXECUTION_FAILED'): fixture.run()
        second_trace=(fixture.output/'2/integrated/events.jsonl').read_bytes()
        fixture.run(resume=True)
        self.assertEqual(fixture.calls[2:],[('1','integrated')])
        self.assertEqual((fixture.output/'2/integrated/events.jsonl').read_bytes(),second_trace)

    def test_old_execution_protocol_still_dispatches_eight_slots(self):
        fixture=HostFixture(self.root/'old',adaptive=False)
        fixture.run()
        self.assertEqual(len(fixture.calls),8)

    def test_historical_adaptive_packet_without_new_marker_still_validates(self):
        fixture=HostFixture(self.root/'historical-adaptive',count_revision=False)
        reviews=fixture.run()
        self.assertEqual(sorted(fixture.calls),[('1','integrated'),('2','integrated')])
        self.assertNotIn('review_unit_count_revision', fixture.frozen['task'])
        self.assertEqual(len(reviews),2)


if __name__=='__main__': unittest.main()
