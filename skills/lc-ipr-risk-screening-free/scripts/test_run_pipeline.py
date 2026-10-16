"""One-command pipeline: stage order, checkpoints, resume, dry run; every command is an argument list."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import shutil
import sys
import tempfile
import unittest

import run_pipeline as rp


class FakeRun:
    """Stands in for the skill's command-line tools; writes the files each real tool would leave behind."""

    def __init__(self, run, *, open_decisions=1, ready=True, marking=False, auto_agree=True, sources=True, searches=True):
        self.run, self.commands = run, []
        self.sources, self.searches = sources, searches
        self.open_decisions, self.ready_value, self.marking, self.auto_agree = open_decisions, ready, marking, auto_agree

    def __call__(self, pipeline, stage, command, *, allow_fail=False, timeout=None):
        assert isinstance(command, list) and all(isinstance(part, str) for part in command), command
        assert command[0] in (sys.executable, 'node'), command
        name = Path(command[3]).name if command[0] == sys.executable else 'cdp:' + command[2]
        self.commands.append((stage, name, command))
        run = self.run
        if name == 'create_task.py':
            run.mkdir(parents=True, exist_ok=True)
            enabled = {'enabled': self.sources and '--enable-serper-free' in command}
            (run / 'task.json').write_text(json.dumps({'task_id': 'T', 'best_estimate_revision': 'best-estimate-risk-v2', 'request': {'url': 'https://www.amazon.com/dp/B000000001'},
                                                       'product': {}, 'serper_free_enhancement': enabled,
                                                       'serpapi_free_enhancement': enabled}), encoding='utf-8')
        elif name == 'cdp:capture-amazon':
            (run / 'amazon-x-browser-capture.json').write_text('{}', encoding='utf-8')
        elif name == 'product_understanding_host.py' and '--complete-inventory' in command:
            Path(command[command.index('--inventory-output') + 1]).write_text('{}', encoding='utf-8')
        elif name == 'advance_work.py' and '--execute-sources' in command and self.searches:
            (run / 'evidence.json').write_text(json.dumps({'source_runs': [
                {'run_id': 'ATT-1', 'query_id': 'Q1', 'provider': 'serper_images', 'status': 'success',
                 'submission_state': 'submitted'}]}), encoding='utf-8')
        elif name == 'product_understanding_host.py':
            out = Path(command[command.index('--output-dir') + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / '1-scope.json').write_text('{}', encoding='utf-8')
            (out / '1-analysis.json').write_text('{}', encoding='utf-8')
        elif name == 'record_product_scope.py':
            task = json.loads((run / 'task.json').read_text(encoding='utf-8'))
            task['product_scope'] = {'scope_sha256': 'x'}
            (run / 'task.json').write_text(json.dumps(task), encoding='utf-8')
        elif name == 'record_product_analysis.py':
            task = json.loads((run / 'task.json').read_text(encoding='utf-8'))
            task['product']['analysis'] = {'status': 'confirmed'}
            if '1-inventory.json' in command[-1] or any('1-inventory.json' in part for part in command):
                task['product']['asset_scope_review'] = {'status': 'reviewed'}
            (run / 'task.json').write_text(json.dumps(task), encoding='utf-8')
        elif name == 'generate_search_plan.py' and '--expand' not in command:
            (run / 'search-plan.json').write_text('{"queries": {}}', encoding='utf-8')
        elif name == 'report_review_host.py' and '--preflight' not in command:
            target = Path(command[command.index('--output-dir') + 1])
            for slot in ('1', '2'):
                (target / slot).mkdir(parents=True, exist_ok=True)
                (target / slot / 'review.json').write_text('{}', encoding='utf-8')
        elif name == 'prepare_adjudication.py':
            if '--auto-agree' in command and not self.auto_agree:
                return 2, '', 'error: unrecognized arguments: --auto-agree'
            path = Path(command[command.index('--output') + 1])
            decisions = [{'right_type': 'patent', 'candidate_id': 'C1', 'adjudication_reasoning': ''}
                         for _ in range(self.open_decisions)]
            path.write_text(json.dumps({'reviewer': 'Chief', 'review_context': {'session_id': 's'},
                                        'decisions': decisions}), encoding='utf-8')
        elif name == 'publish_report.py':
            entry = Path(command[command.index('--deliver-to') + 1])
            entry.mkdir(parents=True)
            (entry / 'report.html').write_text('<html></html>', encoding='utf-8')
        return 0, '{}', ''


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='pipeline-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.run_dir = self.base / 'RUN dir'                     # a space in the path, as on Windows profiles
        self.scripts = self.base / 'scripts'

    def main(self, fake, *extra, ready=True, marking=None):
        argv = ['--task-dir', str(self.run_dir), '--url', 'https://www.amazon.com/dp/B000000001',
                '--chief', 'Chief', '--skip-auth', '--all-sources', *extra]
        stdout = StringIO()
        with patch.object(rp.Pipeline, 'call', lambda self, *a, **k: fake(self, *a, **k)), \
                patch.object(rp.Pipeline, 'ready_sources', lambda self: 1), \
                patch.object(rp.Pipeline, 'ready', lambda self: {'ready': ready, 'blockers': []}), \
                patch.object(rp.Pipeline, 'marking_entry', lambda self: marking), \
                patch.object(rp.Pipeline, 'parallel_hosts', lambda self: {}), redirect_stdout(stdout):
            code = rp.main(argv)
        return code, json.loads(stdout.getvalue().strip().splitlines()[-1])

    def test_checkpoints_then_delivery_on_resume(self):
        fake = FakeRun(self.run_dir, open_decisions=1)
        code, out = self.main(fake)
        self.assertEqual((code, out['checkpoint']), (rp.EXIT_CHECKPOINT, 1))
        self.assertIn('--resume', out['resume'])
        names = [name for _, name, _ in fake.commands]
        self.assertEqual(names[:6], ['create_task.py', 'preflight.py', 'cdp:doctor', 'cdp:capture-amazon',
                                     'record_browser_product.py', 'product_understanding_host.py'])
        code, out = self.main(fake, '--resume')
        self.assertEqual((code, out['checkpoint']), (rp.EXIT_CHECKPOINT, 3))
        names = [name for _, name, _ in fake.commands]
        for script in ('record_product_scope.py', 'record_product_analysis.py', 'generate_search_plan.py',
                       'triage_defaults.py', 'report_review_host.py', 'prepare_adjudication.py'):
            self.assertIn(script, names)
        self.assertNotIn('publish_report.py', names)
        prepare = next(command for _, name, command in fake.commands if name == 'prepare_adjudication.py')
        self.assertIn('--auto-agree', prepare)
        self.assertEqual(prepare[prepare.index('--reviewer') + 1], 'Chief')
        # the chief fills the open decision, then the run resumes to delivery
        path = self.run_dir / 'adjudication.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['decisions'][0]['adjudication_reasoning'] = 'Chief decided.'
        path.write_text(json.dumps(data), encoding='utf-8')
        code, out = self.main(fake, '--resume')
        self.assertEqual((code, out['status']), (rp.EXIT_OK, 'delivered'))
        self.assertTrue(Path(out['report']).is_file())
        state = json.loads((self.run_dir / rp.STATE_FILE).read_text(encoding='utf-8'))
        self.assertTrue(all(state['stages'][name]['status'] == 'completed' for name in rp.STAGES if name != 'auth'))
        # completed stages are not repeated on another resume
        before = len(fake.commands)
        self.main(fake, '--resume')
        self.assertEqual(len(fake.commands), before)

    def test_trust_host_and_no_open_decisions_run_straight_through(self):
        fake = FakeRun(self.run_dir, open_decisions=0)
        code, out = self.main(fake, '--trust-host')
        self.assertEqual((code, out['status']), (rp.EXIT_OK, 'delivered'))

    def test_not_ready_stops_at_checkpoint_2_with_a_list(self):
        fake = FakeRun(self.run_dir, open_decisions=0)
        code, out = self.main(fake, '--trust-host', ready=False)
        self.assertEqual((code, out['checkpoint']), (rp.EXIT_CHECKPOINT, 2))
        self.assertTrue(Path(out['file']).is_file())
        self.assertNotIn('report_review_host.py', [name for _, name, _ in fake.commands])

    def test_marking_card_stops_at_checkpoint_1(self):
        fake = FakeRun(self.run_dir, open_decisions=0)
        with patch('advance_work.action_card', lambda root, entry: {'action': 'resolve_patent_marking_before_discovery'}):
            code, out = self.main(fake, '--trust-host', marking={'reason': 'PATENT_MARKING_RESOLUTION_REQUIRED'})
        self.assertEqual((code, out['checkpoint']), (rp.EXIT_CHECKPOINT, 1))
        self.assertTrue(out['file'].endswith('1b-marking.json'))

    def test_older_prepare_adjudication_without_auto_agree_is_retried(self):
        fake = FakeRun(self.run_dir, open_decisions=0, auto_agree=False)
        code, out = self.main(fake, '--trust-host')
        self.assertEqual(code, rp.EXIT_OK)
        calls = [command for _, name, command in fake.commands if name == 'prepare_adjudication.py']
        self.assertEqual(['--auto-agree' in command for command in calls], [True, False])

    def test_failed_stage_prints_code_and_resume_command(self):
        def failing(pipeline, stage, command, *, allow_fail=False, timeout=None):
            if Path(command[3]).name == 'create_task.py':
                raise rp.StageFailed(stage, 'CREATE_FAILED_FOR_TEST', 'detail')
            return 0, '', ''
        code, out = self.main(failing)
        self.assertEqual((code, out['status'], out['error_code']), (rp.EXIT_FAILED, 'failed', 'CREATE_FAILED_FOR_TEST'))

    def test_dry_run_writes_nothing(self):
        with redirect_stdout(StringIO()) as stdout:
            code = rp.main(['--task-dir', str(self.run_dir), '--dry-run'])
        self.assertEqual(code, rp.EXIT_OK)
        stages = json.loads(stdout.getvalue())['stages']
        self.assertEqual([row['stage'] for row in stages], list(rp.STAGES))
        self.assertFalse(self.run_dir.exists())

    def test_create_passes_the_source_authorisations(self):
        fake = FakeRun(self.run_dir, open_decisions=0)
        self.main(fake, '--trust-host', '--use-serper-existing-balance')
        create = next(command for _, name, command in fake.commands if name == 'create_task.py')
        for flag in ('--enable-serper-free', '--enable-serpapi-free', '--enable-signa-free', '--use-serper-existing-balance'):
            self.assertIn(flag, create)

    def test_a_task_without_serper_or_serpapi_fails_at_creation(self):
        fake = FakeRun(self.run_dir, open_decisions=0, sources=False)
        code, out = self.main(fake, '--trust-host')
        self.assertEqual((code, out['error_code']), (rp.EXIT_FAILED, 'PIPELINE_DISCOVERY_SOURCES_DISABLED'))
        self.assertIn('--all-sources', out['detail'])

    def test_no_submitted_search_stops_before_comparison(self):
        fake = FakeRun(self.run_dir, open_decisions=0, searches=False)
        code, out = self.main(fake, '--trust-host')
        self.assertEqual((code, out['error_code']), (rp.EXIT_FAILED, 'PIPELINE_NO_SOURCE_EXECUTED'))
        self.assertNotIn('core_dossier.py', [name for _, name, _ in fake.commands])

    def test_round_order_reviews_before_dispatch_and_triage_before_result_review(self):
        fake = FakeRun(self.run_dir, open_decisions=0)
        self.main(fake, '--trust-host')
        sources = [(name, command) for stage, name, command in fake.commands if stage == 'sources']
        names = [name for name, _ in sources]
        first_advance = names.index('advance_work.py')
        before = next(i for i, (name, command) in enumerate(sources) if name == 'discovery_review_host.py'
                      and command[command.index('--stages') + 1] == 'direction,before')
        after = next(i for i, (name, command) in enumerate(sources) if name == 'discovery_review_host.py'
                     and command[command.index('--stages') + 1] == 'after')
        self.assertLess(before, first_advance)
        self.assertLess(names.index('triage_defaults.py'), after)
        self.assertLess(names.index('provenance_host.py'), after)

    def test_ready_sources_skips_queries_that_already_returned(self):
        pipeline = rp.Pipeline(rp.parser().parse_args(['--task-dir', str(self.run_dir)]))
        self.run_dir.mkdir(parents=True)
        (self.run_dir / 'evidence.json').write_text(json.dumps({'source_runs': [
            {'query_id': 'Q1', 'status': 'success'}]}), encoding='utf-8')
        entries = [{'state': 'ready', 'kind': 'source_lookup', 'query_id': 'Q1'},
                   {'state': 'ready', 'kind': 'source_lookup', 'query_id': 'Q2'},
                   {'state': 'ready', 'kind': 'triage', 'query_id': 'Q3'}]
        with patch('workflow_v24.work_view_from_dir', lambda run: {'entries': entries}):
            self.assertEqual(pipeline.ready_sources(), 1)

    def test_error_code_extraction(self):
        self.assertEqual(rp.error_code('Traceback...\nValueError: PRODUCT_SCOPE_BASE_CHANGED'), 'PRODUCT_SCOPE_BASE_CHANGED')
        self.assertEqual(rp.error_code(''), 'STAGE_COMMAND_FAILED')


if __name__ == '__main__':
    unittest.main()
