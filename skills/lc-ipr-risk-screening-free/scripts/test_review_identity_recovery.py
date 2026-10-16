"""Identity-preserving final-host recovery; synthetic native turns, real validators."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import load_json, sha256_json
from offline_test_support import isolated_test_environment
from test_adaptive_review_host import HostFixture


@contextmanager
def recovery_fixture(*, kind='visual', fail_slot=None):
    """Reusable offline benchmark fixture; every workspace stays inside its owned temp root."""
    with tempfile.TemporaryDirectory(prefix='ipr-identity-recovery-') as parent:
        with patch('tempfile.tempdir', parent), isolated_test_environment():
            yield HostFixture(Path(parent).resolve() / 'fixture', kind=kind, fail_slot=fail_slot)


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob('*') if path.is_file()}


class IdentityRecoveryTests(unittest.TestCase):
    def test_small_complete_resume_preserves_review_and_adjudication(self):
        from prepare_adjudication import build
        with recovery_fixture() as f:
            f.run()
            original = snapshot(f.output)
            chief, _ = build(f.source, f.output/'1/review.json', f.output/'2/review.json')
            f.binary.unlink()
            with patch('native_review_jobs.tempfile.mkdtemp', side_effect=AssertionError('no workspaces')):
                f.run(resume=True)
            self.assertEqual(len(f.calls), 2)
            self.assertEqual(snapshot(f.output), original)
            self.assertEqual(chief['review_refs']['first'], sha256_json(load_json(f.output/'1/review.json')))

    def test_large_complete_resume_has_no_calls_workspaces_or_writes(self):
        with recovery_fixture(kind='seven-country-large') as f:
            f.run(); original=snapshot(f.output)
            f.binary.unlink()
            with patch('native_review_jobs.tempfile.mkdtemp', side_effect=AssertionError('no workspaces')):
                f.run(resume=True)
            self.assertEqual(len(f.calls), 8)
            self.assertEqual(snapshot(f.output), original)

    def test_failed_second_summary_does_not_repeat_successful_first(self):
        with recovery_fixture(kind='seven-country-large', fail_slot=('2','summary')) as f:
            with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'): f.run()
            original=snapshot(f.output/'1'); count=len(f.calls)
            f.run(resume=True)
            self.assertEqual(f.calls[count:], [('2','summary')])
            self.assertEqual(snapshot(f.output/'1'), original)

    def test_later_corruption_does_not_archive_earlier_failed_slot(self):
        with recovery_fixture(fail_slot=('1','integrated')) as f:
            with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'): f.run()
            # The peer turn completed; its retained packet is part of the immutable input.
            (f.output/'2/integrated/packet.json').write_text('{}', encoding='utf-8')
            original=snapshot(f.output); count=len(f.calls)
            with self.assertRaisesRegex(ValueError, 'PACKET_OR_PROMPT_CHANGED'):
                f.run(resume=True)
            self.assertEqual(snapshot(f.output), original)
            self.assertEqual(len(f.calls), count)

    def test_completed_summary_with_invalid_model_digest_retries_only_that_slot(self):
        import json
        with recovery_fixture(kind='seven-country-large') as f:
            native=f.native;invalid=[True]
            def wrong_summary(command,prompt,workspace,trace_path,stderr_path,timeout):
                proc,text,stderr=native(command,prompt,workspace,trace_path,stderr_path,timeout)
                if trace_path.parent.parent.name=='2' and trace_path.parent.name=='summary' and invalid[0]:
                    invalid[0]=False
                    events=[json.loads(line) for line in text.splitlines()]
                    for event in events:
                        if event.get('type')=='item.completed':
                            raw=json.loads(event['item']['text']);raw['module_review_digests']=['wrong-model-digest']
                            event['item']['text']=json.dumps(raw)
                    text='\n'.join(json.dumps(row) for row in events)+'\n'
                    trace_path.write_text(text,encoding='utf-8')
                return proc,text,stderr
            f.native=wrong_summary
            with self.assertRaisesRegex(ValueError,'SUMMARY_CANNOT_REWRITE_MODULES'):f.run()
            original=snapshot(f.output/'1');count=len(f.calls)
            f.run(resume=True)
            self.assertEqual(f.calls[count:],[('2','summary')])
            self.assertEqual(snapshot(f.output/'1'),original)

    def test_missing_peer_host_file_rejects_before_archiving_failed_slot(self):
        for name in ('stderr.log','sandbox.sb'):
            with self.subTest(name=name), recovery_fixture(fail_slot=('1','integrated')) as f:
                with self.assertRaisesRegex(ValueError,'EXECUTION_FAILED'):f.run()
                (f.output/'2/integrated'/name).unlink()
                original=snapshot(f.output);count=len(f.calls)
                # A peer captured with its real audit reports a missing signed file through the audit check.
                with self.assertRaisesRegex(ValueError,'HOST_FILES_MISSING|RETAINED_AUDIT_CHANGED'):f.run(resume=True)
                self.assertEqual(snapshot(f.output),original);self.assertEqual(len(f.calls),count)

    def test_missing_completed_summary_stderr_rejects_before_failed_peer_archive(self):
        with recovery_fixture(kind='seven-country-large',fail_slot=('1','summary')) as f:
            with self.assertRaisesRegex(ValueError,'EXECUTION_FAILED'):f.run()
            (f.output/'2/summary/stderr.log').unlink()
            original=snapshot(f.output);count=len(f.calls)
            with self.assertRaisesRegex(ValueError,'HOST_FILES_MISSING'):f.run(resume=True)
            self.assertEqual(snapshot(f.output),original);self.assertEqual(len(f.calls),count)

    def test_completed_pair_still_requires_the_original_host_files(self):
        with recovery_fixture() as f:
            f.run();(f.output/'2/integrated/stderr.log').unlink()
            original=snapshot(f.output)
            with self.assertRaisesRegex(ValueError,'HOST_FILES_MISSING'):f.run(resume=True)
            self.assertEqual(snapshot(f.output),original);self.assertEqual(len(f.calls),2)

    def test_new_audit_persists_the_actual_execution_identity(self):
        with recovery_fixture() as f:
            reviews=f.run()
            for chain, review in enumerate(reviews,1):
                record=review['review_context']['execution']['integrated_execution']['record']
                audit=load_json(f.output/str(chain)/'integrated/audit.json')
                self.assertEqual(audit.get('execution_identity_revision'), 'stable-native-run-id-v1')
                self.assertEqual(audit.get('run_id'), record['run_id'])


    def test_public_host_resume_keeps_successful_output_without_native_activity(self):
        from report_review_host import run_pair
        with recovery_fixture(kind='seven-country-large') as f:
            (f.output/'frozen-input.json').write_bytes((f.output/'frozen.json').read_bytes())
            f.run();original=snapshot(f.output);f.binary.unlink()
            with patch('report_review_host.run_native_logged',side_effect=AssertionError('no native turn')), \
                 patch('macos_review_host.require_chatgpt_auth',side_effect=AssertionError('no login')), \
                 patch('review_isolation.resolve_codex_binary',side_effect=AssertionError('no CLI discovery')), \
                 patch('native_review_jobs.tempfile.mkdtemp',side_effect=AssertionError('no workspace')):
                paths=run_pair(f.source,f.output,f.binary,resume_existing=True,isolation='macos-sandbox')
            self.assertEqual(paths,[f.output/'1/review.json',f.output/'2/review.json'])
            self.assertEqual(snapshot(f.output),original)

    def test_legacy_completed_pair_recovers_original_ids_without_audit_changes(self):
        with recovery_fixture(kind='seven-country-large') as f:
            with patch('review_execution_identity.identity_fields', return_value={}):
                f.run()
            original=snapshot(f.output)
            f.binary.unlink()
            f.run(resume=True)
            self.assertEqual(len(f.calls),8)
            self.assertEqual(snapshot(f.output),original)

    def test_legacy_module_before_any_consumer_uses_deterministic_identity(self):
        with recovery_fixture(kind='seven-country-large', fail_slot=('2','technical')) as f:
            with patch('review_execution_identity.identity_fields', return_value={}):
                with self.assertRaisesRegex(ValueError,'EXECUTION_FAILED'):f.run()
            original={p:p.read_bytes() for p in f.output.glob('1/*/audit.json')}
            count=len(f.calls)
            reviews=f.run(resume=True)
            self.assertEqual(len(f.calls)-count,3)  # One failed module and two first-time summaries.
            for p,data in original.items():self.assertEqual(p.read_bytes(),data)
            records=reviews[0]['review_context']['execution']['module_execution']['modules']
            self.assertTrue(all(r['run_id']=='retained-trace-'+r['session_id'] for r in records))
            stable=snapshot(f.output);f.run(resume=True)
            self.assertEqual(snapshot(f.output),stable)

    def test_legacy_incomplete_consumer_is_not_evidence_for_an_original_identity(self):
        with recovery_fixture(kind='seven-country-large', fail_slot=('1','summary')) as f:
            with patch('review_execution_identity.identity_fields', return_value={}):
                with self.assertRaisesRegex(ValueError,'EXECUTION_FAILED'):f.run()
            original=snapshot(f.output);count=len(f.calls)
            with self.assertRaisesRegex(ValueError,'IDENTITY_UNCONFIRMED'):f.run(resume=True)
            self.assertEqual(snapshot(f.output),original)
            self.assertEqual(len(f.calls),count)

    def test_legacy_complete_summary_trace_without_audit_binds_module_identities(self):
        import module_review
        capture=module_review._capture
        def interrupted(job,*args,**kwargs):
            if job['module_id']=='summary':raise RuntimeError('host stopped before summary capture')
            return capture(job,*args,**kwargs)
        with recovery_fixture(kind='seven-country-large') as f:
            with patch('review_execution_identity.identity_fields',return_value={}), \
                 patch('module_review._capture',side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError,'host stopped'):f.run()
            original={p:p.read_bytes() for p in f.output.glob('*/*/audit.json')}
            count=len(f.calls)
            f.run(resume=True)
            self.assertEqual(len(f.calls),count)
            for p,data in original.items():self.assertEqual(p.read_bytes(),data)
            for chain in ('1','2'):
                audit=load_json(f.output/chain/'summary/audit.json')
                self.assertEqual(audit['execution_identity_revision'],'stable-native-run-id-v1')
                self.assertIsNone(audit['process_id']);self.assertIsNone(audit['exit_code'])
                self.assertTrue(audit['recovered_from_retained_trace'])

    def test_after_audit_commit_interruption_reuses_persisted_identity(self):
        import module_review
        capture=module_review._capture
        def interrupted(job,*args,**kwargs):
            value=capture(job,*args,**kwargs)
            raise RuntimeError('host stopped after audit commit')
        with recovery_fixture() as f:
            with patch('module_review._capture',side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError,'after audit commit'):f.run()
            audit_path=f.output/'1/integrated/audit.json'
            audit=load_json(audit_path);original=audit_path.read_bytes()
            reviews=f.run(resume=True)
            self.assertEqual(len(f.calls),2)
            self.assertEqual(audit_path.read_bytes(),original)
            self.assertEqual(reviews[0]['review_context']['execution']['run_id'],audit['run_id'])

    def test_conflicting_valid_archived_consumer_is_rejected_without_mutation(self):
        import json,shutil
        from common import atomic_write_json,sha256_file
        from module_review import summary_prompt
        with recovery_fixture(kind='seven-country-large') as f:
            with patch('review_execution_identity.identity_fields',return_value={}):f.run()
            archive=f.output/'1/summary.attempt-1'
            shutil.copytree(f.output/'1/summary',archive)
            packet=load_json(archive/'packet.json')
            packet['modules'][0]['run_id']='old-alternative-consumed-identity'
            atomic_write_json(archive/'packet.json',packet)
            (archive/'prompt.txt').write_text(summary_prompt(packet),encoding='utf-8')
            raw=load_json(archive/'agent-judgment.json')
            raw['module_review_digests']=[sha256_json(row) for row in packet['modules']]
            atomic_write_json(archive/'agent-judgment.json',raw)
            events=[json.loads(line) for line in (archive/'events.jsonl').read_text(encoding='utf-8').splitlines()]
            for event in events:
                if event.get('type')=='item.completed':event['item']['text']=json.dumps(raw)
            (archive/'events.jsonl').write_text('\n'.join(json.dumps(row) for row in events)+'\n',encoding='utf-8')
            audit=load_json(archive/'audit.json')
            for key,name in [('packet','packet.json'),('prompt','prompt.txt'),('judgment','agent-judgment.json'),('trace','events.jsonl')]:
                audit[key+'_sha256']=sha256_file(archive/name)
            atomic_write_json(archive/'audit.json',audit)
            original=snapshot(f.output);count=len(f.calls)
            with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):f.run(resume=True)
            self.assertEqual(snapshot(f.output),original);self.assertEqual(len(f.calls),count)


if __name__=='__main__': unittest.main()
