"""Lens reuse is an authorized logical binding to one immutable request."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import atomic_write_json, load_json, sha256_file, sha256_json, serper_free_enhancement, serpapi_free_enhancement
from runtime_v24 import _reuse_physical_response, physical_response_source, source_fresh
from serpapi_lens_client import normalize, retained_source_records, execute
from serpapi_patents_client import consumed_queries
from trusted_api import annotate_entry, valid_entry


class LensReuseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.url = 'https://m.media-amazon.com/images/I/main.jpg'
        self.task = {'schema_version':'2.4-free', 'retrieval_workflow_revision':'api-first-v3',
            'decision_workflow_revision':'scenario-triage-v1',
            'workflow_correction_revision':'workflow-correction-v1',
            'retrieval_policy':{'enabled':True},
            'serper_free_enhancement':serper_free_enhancement(True,'api-first-v3'),
            'serpapi_free_enhancement':serpapi_free_enhancement(True,'api-first-v3'),
            'images':[{'source_url':self.url,'sha256':'image-digest'}]}
        self.row = {'query_id':'new', 'operation':'image_search', 'jurisdiction':'US',
            'right_type':'copyright', 'q':self.url, 'image_url':self.url,
            'hl':'en', 'country':'us', 'type':'all', 'requirement_ids':['copyright'],
            'required':False,'required_for':'discovery_only','role':'discovery_only',
            'authoritative_for_final_rating':False}
        self.params = {key:self.row[key] for key in ('q','image_url','hl','country','type','right_type')}
        self.raw = self.root/'source.json'
        atomic_write_json(self.raw, {'search_metadata':{'status':'Success'},
            'visual_matches':[{'title':'same visual work','link':'https://example.test/work','image':'https://example.test/image.jpg'}]})
        self.original = {'run_id':'original','query_id':'old','provider':'serpapi_google_lens',
            'operation':'image_search','jurisdiction':'US','right_type':'design','status':'success',
            'started_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),
            'finished_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),
            'submission_state':'submitted', 'quota':{'network_request_attempted':True},
            'raw_paths':[str(self.raw)], 'payload_digest':sha256_file(self.raw),
            'plan_entry_sha256':'old-plan-digest', 'request_params':{**self.params,'right_type':'design'},
            'metadata':{},'source_environment':'production'}
        self.entry = {'evidence_id':'old-evidence','source_run_id':'original','query_id':'old',
            'provider':'serpapi_google_lens','operation':'image_search','jurisdiction':'US','right_type':'design',
            'plan_entry_sha256':'old-plan-digest','collected_at':self.original['finished_at'],
            'payload':normalize(load_json(self.raw),retrieval_workflow_revision='api-first-v3',investigation_right_type='design')}
        annotate_entry(self.task,self.entry,self.original)
        self.save()

    def save(self):
        atomic_write_json(self.root/'task.json',self.task)
        atomic_write_json(self.root/'search-plan.json',{'queries':{'serpapi_google_lens':[self.row]}})
        atomic_write_json(self.root/'evidence.json',{'source_runs':[self.original],
            'collections':{'copyright_assets':[self.entry]}})

    def reuse(self, row=None):
        return _reuse_physical_response(self.root,'serpapi_google_lens',row or self.row,48,
            authorized_task=self.task,authorized_params=self.params)

    def test_right_metadata_rebinds_without_network_count_or_clock_refresh(self):
        before_run, before_entry = deepcopy(self.original), deepcopy(self.entry)
        reused = self.reuse()
        self.assertIsNotNone(reused)
        evidence = load_json(self.root/'evidence.json')
        self.assertEqual(evidence['source_runs'][0],before_run)
        self.assertEqual(evidence['collections']['copyright_assets'][0],before_entry)
        self.assertEqual(reused['submission_state'],'not_submitted')
        self.assertIs(reused['quota']['network_request_attempted'],False)
        self.assertEqual(consumed_queries(evidence),1)
        self.assertEqual(reused['finished_at'],self.original['finished_at'])
        copied = evidence['collections']['copyright_assets'][-1]
        self.assertEqual(copied['collected_at'],self.entry['collected_at'])
        self.assertEqual(reused['request_params'],self.params)
        self.assertEqual(reused['plan_entry_sha256'],sha256_json(self.row))
        self.assertEqual(copied['payload']['candidates'][0]['investigation_right_type'],'copyright')
        self.assertTrue(valid_entry(self.task,copied,reused))
        self.assertEqual(physical_response_source(self.root,evidence,reused),self.original)
        self.assertEqual(retained_source_records(evidence,reused,self.root),copied['payload']['candidates'])
        self.assertEqual(self.reuse()['run_id'],reused['run_id'])
        self.assertEqual(len(load_json(self.root/'evidence.json')['source_runs']),2)

    def test_client_reuses_after_authorization_without_account_or_search_request(self):
        with patch('serpapi_lens_client.load_action',return_value=(self.task,self.row,self.params)) as authorize, \
                patch('serpapi_lens_client.discovery_plan_scope_valid',return_value=True), \
                patch('serpapi_lens_client.search',side_effect=AssertionError('No search')), \
                patch('serpapi_lens_client.free_account_snapshot',side_effect=AssertionError('No account network')):
            reused = execute(self.root,self.row['query_id'])
        authorize.assert_called_once()
        self.assertEqual(reused['status'],'success')
        self.assertIs(reused['quota']['network_request_attempted'],False)

    def test_foreign_provider_country_changed_parameter_and_unknown_submission_not_reused(self):
        for change in ({'provider':'other'}, {'jurisdiction':'GB'}, {'submission_state':'unknown'},
                       {'request_params':{**self.original['request_params'],'hl':'ja'}},
                       {'request_params':{**self.original['request_params'],'type':'visual_matches'}}):
            original = deepcopy(self.original)
            self.original.update(change)
            self.save()
            self.assertIsNone(self.reuse())
            self.original = original

    def test_expired_or_tampered_material_is_never_reused(self):
        self.original['finished_at']=(datetime.now(timezone.utc)-timedelta(hours=49)).isoformat()
        self.save()
        self.assertIsNone(self.reuse())
        self.original['finished_at']=datetime.now(timezone.utc).isoformat()
        self.save()
        self.raw.write_text('{}')
        self.assertIsNone(self.reuse())

    def test_reuse_cannot_extend_material_lifetime(self):
        reused = self.reuse()
        old = deepcopy(reused)
        old['finished_at']=(datetime.now(timezone.utc)-timedelta(hours=49)).isoformat()
        self.assertFalse(source_fresh(old,48))
        self.original['finished_at']=old['finished_at']
        evidence = load_json(self.root/'evidence.json')
        evidence['source_runs'][0]=self.original
        atomic_write_json(self.root/'evidence.json',evidence)
        self.assertIsNone(self.reuse({**self.row,'query_id':'third','right_type':'trade_dress'}))

    def test_bound_proof_rejects_tampered_source_hash_date_wire_and_current_plan(self):
        reused=self.reuse()
        evidence=load_json(self.root/'evidence.json')
        for change in ({'finished_at':datetime.now(timezone.utc).isoformat()},
                       {'request_params':{**self.params,'country':'jp'}},
                       {'plan_entry_sha256':'wrong'}, {'submission_state':'submitted'},
                       {'quota':{'network_request_attempted':True}}):
            changed={**deepcopy(reused),**change}
            self.assertIsNone(physical_response_source(self.root,evidence,changed))
        bad=deepcopy(evidence)
        bad['source_runs'][0]['query_id']='tampered-original-query'
        self.assertIsNone(physical_response_source(self.root,bad,reused))
        atomic_write_json(self.root/'search-plan.json',{'queries':{'serpapi_google_lens':[{**self.row,'hl':'ja'}]}})
        self.assertIsNone(physical_response_source(self.root,evidence,reused))


if __name__=='__main__':
    unittest.main()
