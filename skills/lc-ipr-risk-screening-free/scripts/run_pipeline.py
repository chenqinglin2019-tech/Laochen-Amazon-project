#!/usr/bin/env python3
"""One-command screening pipeline (best-estimate-risk-v2 tasks): every stage in a fixed order, three checkpoints.

The pipeline only sequences the skill's existing command-line tools (each is still the authority for its own
validation); it never writes ledgers itself. Stages:

  1 auth -> create -> credentials -> capture                       (auth_gate, create_task, preflight, CDP capture)
  2 understanding -> [checkpoint 1] -> scope                        (product_understanding_host, record_product_scope,
                                                                     record_product_analysis, preflight evidence)
  3 plan                                                            (generate_search_plan, mechanical_ledger)
  4 sources (rounds)                                                (mechanical_ledger, advance_work --execute-sources,
                                                                     discovery_review_host, merge_candidates,
                                                                     triage_defaults, text/visual hosts, auto_refine,
                                                                     --expand)
  5 core -> marking [checkpoint 1b] -> readiness [checkpoint 2]     (core_dossier, comparison_host; a PATENTED page
                                                                     is resolved from the compared candidates, or the
                                                                     Agent searches by hand; readiness)
  6 review -> adjudication -> [checkpoint 3] -> publish             (report_review_host, prepare_adjudication
                                                                     --auto-agree, publish_report --require-complete)

Exit codes: 0 report delivered; 3 a checkpoint needs the Agent (the message names the file to edit and the resume
command); 1 a stage failed (error code and the exact resume command are printed). Re-run with --resume.

Tasks created with ``pipeline_robust_revision`` (r5d4) also: keep the computer awake for the whole run; count rounds
per invocation and never call a round whose review session failed idle; leave out rows the runner's gate holds before
the dispatch cap; run the source-provenance review beside the triage hosts; screen patents before the final review
(``prereview_screen.py``); flush dispatchable discovery rows before ``core`` ends; and run one program catch-up round
before (and on every resume at) checkpoint 2.

Tasks created with ``prereview_design_revision`` / ``pipeline_speed_revision`` (r5d17) also screen designs whose overall
visual impression is plainly different (``design_screen.py``, beside the comparison), and skip a source round that only
read candidate details and a second core round once the run is ready. Every invocation first drops the skill's
compiled caches when the installed release changed (``clear_stale_bytecode``).

State: RUN/pipeline-state.json (stage, status, input_sha256, outputs, seconds); log: RUN/pipeline-log.jsonl.
Nothing runs a shell; every call is [python -X utf8 script ...] or [node cdp-cli.mjs ...], so macOS and Windows
behave the same.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
CDP = ROOT / 'tools' / 'cdp' / 'cdp-cli.mjs'
EXIT_OK, EXIT_FAILED, EXIT_CHECKPOINT = 0, 1, 3
STATE_FILE, LOG_FILE = 'pipeline-state.json', 'pipeline-log.jsonl'
CHECKPOINT_DIR = 'checkpoints'
# The marking stage follows discovery (r5d): a bounded structural search finds an individually owned patent that a
# brand search never can, and the compared candidates are what the Agent needs to see when it must search by hand.
STAGES = ('auth', 'create', 'credentials', 'capture', 'understanding', 'scope', 'plan', 'sources',
          'core', 'marking', 'readiness', 'review', 'adjudication', 'publish')
INPUT_FILES = ('task.json', 'evidence.json', 'search-plan.json', 'normalized-candidates.json',
               'materiality-annotations.json')
# The progress signature counts candidates, decisions, semantic reviews, progress events, provenance records and
# attempts, so one unchanged round means the source loop can do nothing more on its own.
MAX_ROUNDS, MAX_IDLE_ROUNDS = 6, 1
# r5d21 (precision-v1): the first search round plus one round for the reviewers' rewrites; one core pass plus one for a
# late selection; one catch-up before the readiness decision (B0GLNPC6K8: four idle source rounds of 3.5 minutes each)
PRECISE_SOURCE_ROUNDS, PRECISE_CORE_ROUNDS, PRECISE_CATCH_UP_ROUNDS = 2, 2, 1
ERROR_CODE = re.compile(r'\b([A-Z][A-Z0-9]+(?:_[A-Z0-9]+){1,})\b')


class Checkpoint(Exception):
    def __init__(self, number, message, path):
        super().__init__(message)
        self.number, self.message, self.path = number, message, path


class StageFailed(Exception):
    def __init__(self, stage, code, detail):
        super().__init__(code)
        self.stage, self.code, self.detail = stage, code, detail


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def py(script, *args):
    return [sys.executable, '-X', 'utf8', str(SCRIPTS / script), *[str(arg) for arg in args]]


def node(*args):
    return ['node', str(CDP), *[str(arg) for arg in args]]


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    from common import replace_file
    replace_file(temporary, path)                    # r9: retried briefly on Windows when a reader holds the file


def inputs_sha256(run):
    digest = hashlib.sha256()
    for name in INPUT_FILES:
        path = Path(run) / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.is_file() else b'-')
    return digest.hexdigest()


def error_code(text):
    codes = ERROR_CODE.findall(text or '')
    return codes[-1] if codes else 'STAGE_COMMAND_FAILED'


class Pipeline:
    def __init__(self, args):
        self.args = args
        self.run = Path(args.task_dir).expanduser().resolve()
        self.state = read_json(self.run / STATE_FILE, None) or {
            'schema': 'IPR-PIPELINE/1.0', 'task_dir': str(self.run), 'stages': {}, 'checkpoints': {}, 'rounds': []}
        self.session = (args.guard_session_id or os.environ.get('CODEX_THREAD_ID') or
                        'pipeline-' + hashlib.sha256(str(self.run).encode()).hexdigest()[:12])
        self.lock = threading.Lock()

    # ----- bookkeeping ----------------------------------------------------------------------------------------
    def save(self):
        if self.run.is_dir():
            write_json(self.run / STATE_FILE, self.state)

    def log(self, **row):
        if not self.run.is_dir():
            return
        with self.lock, (self.run / LOG_FILE).open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at': now(), **row}, ensure_ascii=False) + '\n')

    def precise(self):
        """r5d21: new tasks with candidate_precision_revision (capped deep checks, shorter rounds)."""
        try:
            import precision
        except ImportError:
            return False
        return precision.enabled(read_json(self.run / 'task.json', {}) or {})

    def r6(self):
        """r6 (report-always-v1): the run degrades instead of stopping wherever the program can act."""
        try:
            import report_always
        except ImportError:
            return False
        return report_always.enabled(read_json(self.run / 'task.json', {}) or {})

    def robust(self):
        """r5d4 behaviour (pipeline_robust.py) for tasks created with it; older tasks keep their frozen flow."""
        import pipeline_robust
        return pipeline_robust.enabled(read_json(self.run / 'task.json', {}) or {})

    def run_parallel(self, stage, commands):
        """Run independent tool calls side by side (each still validates and records on its own); [(code, out, err)]."""
        with ThreadPoolExecutor(max_workers=max(1, len(commands))) as pool:
            futures = [pool.submit(self.call, stage, command, allow_fail=True) for command in commands]
            return [future.result() for future in futures]

    @staticmethod
    def summary(out):
        """The JSON summary a host prints as its last line, or {}."""
        try:
            value = json.loads((out or '').strip().splitlines()[-1]) if (out or '').strip() else {}
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def review_failed(code, out):
        """A discovery-review call whose session itself failed (network, sleep): the round is not idle."""
        if code != 0:
            return True
        unresolved = Pipeline.summary(out).get('unresolved') or []
        return any(str((row or {}).get('reason') or '').startswith(('execution:', 'job_setup:'))
                   for row in unresolved if isinstance(row, dict))

    def done(self, stage):
        return self.state['stages'].get(stage, {}).get('status') == 'completed'

    # r5d8 (B0GLNPC6K8, new task): three steps took 33 minutes of wall clock but 4 minutes of process clock - the
    # Mac slept although the run held a keep-awake request (a closed lid or battery power still forces sleep). The
    # process clock stops while the computer sleeps, so the difference is logged and reported, never guessed.
    SLEEP_NOTICE_SECONDS = 60

    def note_sleep(self, stage, command, wall, process):
        slept = wall - process
        if slept < self.SLEEP_NOTICE_SECONDS:
            return
        with self.lock:
            self.state['slept_seconds'] = round(float(self.state.get('slept_seconds') or 0) + slept, 1)
        self.log(stage=stage, note='system_sleep', seconds=round(slept, 1), during=command)

    def sleep_notice(self):
        minutes = round(float(self.state.get('slept_seconds') or 0) / 60)
        if minutes < 1:
            return {}
        return {'slept_minutes': minutes,
                'sleep_warning': '运行期间电脑睡眠约 %d 分钟，模型会话因此中断或变慢。合上盖子或只用电池时系统会强制睡眠：'
                                 '跑任务时请接上电源、不要合盖。' % minutes}

    # r6: the program's own bookkeeping steps inside the search and comparison rounds; one failing used to stop the run
    PLUMBING = ('mechanical_ledger.py', 'advance_work.py', 'merge_candidates.py', 'generate_search_plan.py')
    PLUMBING_STAGES = ('sources', 'core', 'readiness', 'marking')
    INTEGRITY_MARKERS = ('INTEGRITY', 'HASH_MISMATCH', '_CHANGED', 'CORRUPT', 'TAMPER', 'LOCK_HELD')

    def call(self, stage, command, *, allow_fail=False, timeout=None, _plumbing_retry=False):
        started = time.time()
        clock = time.perf_counter()
        env = {**os.environ, 'PYTHONUTF8': '1'}
        try:
            result = subprocess.run(command, cwd=str(SCRIPTS), capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', env=env, timeout=timeout)
            code, out, err = result.returncode, result.stdout, result.stderr
        except FileNotFoundError as exc:
            code, out, err = 127, '', str(exc)
        except subprocess.TimeoutExpired as exc:
            code, out, err = 124, str(exc.stdout or ''), 'PIPELINE_COMMAND_TIMEOUT'
        shown = command[3:] if command[:1] == [sys.executable] else command[1:]
        self.note_sleep(stage, Path(shown[0]).name if shown else '', time.time() - started, time.perf_counter() - clock)
        self.log(stage=stage, command=[Path(shown[0]).name, *map(str, shown[1:])] if shown else [],
                 returncode=code, seconds=round(time.time() - started, 1), stdout_tail=(out or '')[-600:],
                 stderr_tail=(err or '')[-600:])
        if code != 0 and not allow_fail:
            script = Path(shown[0]).name if shown else ''
            code_name = error_code(err + '\n' + out)
            if (not _plumbing_retry and script in self.PLUMBING and stage in self.PLUMBING_STAGES and self.r6()
                    and not any(marker in code_name for marker in self.INTEGRITY_MARKERS)):
                # r6: retried once; still failing, the round goes on and the step is disclosed (the readiness check
                # and the time-box closure list what it left open). File-integrity faults still stop the run.
                code, out, err = self.call(stage, command, allow_fail=True, timeout=timeout, _plumbing_retry=True)
                if code != 0:
                    with self.lock:
                        self.state.setdefault('degraded_steps', []).append(
                            {'at': now(), 'stage': stage, 'script': script, 'error_code': error_code(err + '\n' + out)})
                    self.log(stage=stage, note='plumbing_degraded', script=script, error_code=error_code(err + '\n' + out))
                return code, out, err
            raise StageFailed(stage, code_name, (err or out)[-1200:])
        return code, out, err

    def stage(self, name, function):
        if self.done(name) and name not in (self.args.redo or []):
            return
        record = self.state['stages'].setdefault(name, {})
        record.update(status='running', started_at=now(), input_sha256=inputs_sha256(self.run) if self.run.is_dir() else None)
        started = time.time()
        self._stage_started = started
        self.save()

        def account():
            # r5d21: the time box counts machine time only (stage time; never the owner's wait at a checkpoint)
            self.state['active_seconds'] = round(float(self.state.get('active_seconds') or 0) + time.time() - started, 1)
            self._stage_started = None
        try:
            outputs = function() or {}
        except Checkpoint:
            account()
            record.update(status='checkpoint', seconds=round(time.time() - started, 1))
            self.save()
            raise
        except StageFailed:
            account()
            record.update(status='failed', seconds=round(time.time() - started, 1))
            self.save()
            raise
        except Exception as exc:
            if not self.r6():
                raise
            # r6: an unexpected fault ends the stage cleanly - its code, the traceback tail and the resume command
            # are printed, instead of a bare traceback and a stage left "running"
            import traceback
            account()
            record.update(status='failed', seconds=round(time.time() - started, 1))
            self.save()
            raise StageFailed(name, 'PIPELINE_UNEXPECTED_' + type(exc).__name__.upper(),
                              traceback.format_exc()[-1200:]) from exc
        account()
        record.update(status='completed', finished_at=now(), seconds=round(time.time() - started, 1), outputs=outputs)
        self.save()

    def active(self):
        """Machine seconds of this task's pipeline so far (finished stages plus the running one)."""
        running = getattr(self, '_stage_started', None)
        return float(self.state.get('active_seconds') or 0) + (time.time() - running if running else 0.0)

    def box(self):
        """The time-box policy of a time-box-v1 task, else None."""
        try:
            import time_box
        except ImportError:
            return None
        return time_box.policy(read_json(self.run / 'task.json', {}) or {})

    def boxed(self, key):
        """Whether the time box's ``key`` limit (sources_seconds / core_seconds) has been reached."""
        policy = self.box()
        return bool(policy) and self.active() >= policy[key]

    def resume_command(self):
        # r9: the interpreter and the script that actually ran (a fresh Mac has no `python`; the skill's .venv has the
        # dependencies), as absolute paths that work from any directory
        command = [sys.executable, '-X', 'utf8', str(SCRIPTS / 'run_pipeline.py'), '--task-dir', str(self.run), '--resume']
        if self.args.chief:
            command += ['--chief', self.args.chief]
        return ' '.join('"%s"' % part if ' ' in part else part for part in command)

    def host_flags(self):
        flags = []
        if self.args.codex_binary:
            flags += ['--codex-binary', self.args.codex_binary]
        if self.args.isolation:
            flags += ['--isolation', self.args.isolation]
        return flags

    # ----- stages ---------------------------------------------------------------------------------------------
    SANDBOX_HINT = ('检测到 Codex 沙箱禁止联网（CODEX_SANDBOX_NETWORK_DISABLED）。本技能的流水线要联网鉴权和检索：请在 Codex '
                    '请求授权时允许这条命令联网，或改用可联网的权限后，用同一条命令重跑。')

    def s_auth(self):
        try:
            self.call('auth', py('auth_gate.py'))
        except StageFailed:
            # r9: the auth gate's own reason is printed unchanged; a sandbox without network is named beside it
            if os.environ.get('CODEX_SANDBOX_NETWORK_DISABLED') == '1':
                with self.lock:
                    self.state['network_notice'] = self.SANDBOX_HINT
            raise

    def dependency_check(self):
        """r9: a fresh machine running the system Python fails mid-run on its first image or PDF; say it up front."""
        missing = []
        for module in ('PIL', 'pypdf'):
            try:
                __import__(module)
            except ImportError:
                missing.append(module)
        if missing:
            raise StageFailed('create', 'PIPELINE_PYTHON_DEPENDENCIES_MISSING',
                '当前 Python（%s）缺少 %s。请在技能目录运行：%s -X utf8 scripts/setup_skill.py --install-deps，'
                '然后改用技能自带的虚拟环境重跑（Mac：.venv/bin/python，Windows：.venv\\Scripts\\python.exe）。'
                % (sys.executable, '、'.join(missing), sys.executable))

    def reach_check(self):
        """r9: before a new task uses any account, the Google patent hosts must answer through the download channel
        (DNS, fake-IP rule, the user's proxy); a run that can read no drawing or page stops here with the fix."""
        try:
            from network_diagnostic import diagnose, notice
            result = diagnose(timeout=3.0, reach=True)
        except Exception:                        # diagnostics never stop a run on their own failure
            return
        text = notice(result)
        if text:
            with self.lock:
                self.state['network_notice'] = text
        if result.get('status') == 'google_unreachable':
            raise StageFailed('create', 'PIPELINE_GOOGLE_UNREACHABLE', text)

    def s_create(self):
        if (self.run / 'task.json').is_file():
            return {'skipped': 'task.json exists'}
        if not (self.args.url or self.args.product_input):
            raise StageFailed('create', 'PIPELINE_URL_OR_PRODUCT_INPUT_REQUIRED', 'pass --url or --product-input')
        self.dependency_check()
        self.reach_check()
        # r9: without --jurisdictions an Amazon link is screened for its own marketplace (amazon.de -> EU+DE,
        # amazon.co.jp -> JP, amazon.com -> US as before); user materials keep the old US default
        jurisdictions = self.args.jurisdictions or (None if self.args.url else 'US')
        command = py('create_task.py', *(['--url', self.args.url] if self.args.url else
                                         ['--product-input', self.args.product_input]),
                     *(['--jurisdictions', jurisdictions] if jurisdictions else []), '--output-dir', self.run)
        # r9: PowerShell expands "$CODEX_THREAD_ID" to an empty string; the session's own variable is the same value
        session = self.args.guard_session_id or os.environ.get('CODEX_THREAD_ID') or ''
        if session:
            command += ['--guard-session-id', session]
        command += self.source_flags()
        self.call('create', command)
        self.require_discovery_sources('create')
        self.market_check()
        return {'task_dir': str(self.run), 'sources': self.enabled_sources()}

    def note_model(self, text):
        """r9: a failed review that says the pinned review model is unavailable to this account gets a Chinese hint."""
        import portable
        if portable.model_unavailable(text):
            with self.lock:
                self.state['model_notice'] = portable.model_notice()

    def market_check(self):
        """r9 (portable-v1): the countries named for the run do not include the listing's own marketplace."""
        task = read_json(self.run / 'task.json', {}) or {}
        import portable
        if not portable.enabled(task):
            return
        text = portable.market_notice((task.get('request') or {}).get('marketplace'), task.get('target_jurisdictions'))
        if text:
            with self.lock:
                self.state['market_notice'] = text

    def scope_check(self):
        """r9 (portable-v1): national scopes this skill cannot search (no local-language terms) are named before
        the run spends anything on the others."""
        task = read_json(self.run / 'task.json', {}) or {}
        import portable
        if not portable.enabled(task):
            return
        text = portable.scope_notice(task, read_json(self.run / 'search-plan.json', None))
        with self.lock:
            if text:
                self.state['scope_notice'] = text
            else:
                self.state.pop('scope_notice', None)

    def source_flags(self):
        flags = []
        if self.args.enable_serper_free or self.args.all_sources:
            flags.append('--enable-serper-free')
        if self.args.use_serper_existing_balance:
            flags.append('--use-serper-existing-balance')
        if self.args.enable_serpapi_free or self.args.all_sources:
            flags.append('--enable-serpapi-free')
        if self.args.enable_signa_free or self.args.all_sources:
            flags.append('--enable-signa-free')
        return flags

    def enabled_sources(self):
        task = read_json(self.run / 'task.json', {}) or {}
        return sorted(name for name in ('serper', 'serpapi', 'signa')
                      if (task.get(name + '_free_enhancement') or {}).get('enabled'))

    def require_discovery_sources(self, stage):
        """Without Serper or SerpApi the plan has no web, image, Google Patents or design discovery at all."""
        if self.args.allow_limited_sources:
            return
        enabled = self.enabled_sources()
        if not {'serper', 'serpapi'} & set(enabled):
            raise StageFailed(stage, 'PIPELINE_DISCOVERY_SOURCES_DISABLED',
                '这个任务没有启用 Serper 或 SerpApi（已启用：%s），检索计划里没有网页、图片、Google Patents 和外观设计发现，'
                '跑下去只会得到空报告。请用新目录重新建任务，并在命令里加 --all-sources --use-serper-existing-balance'
                '（已有额度的使用授权）；确实只想用 EPO 时加 --allow-limited-sources。' % ('、'.join(enabled) or '无'))

    def s_credentials(self):
        self.call('credentials', py('preflight.py', '--task', self.run / 'task.json', '--phase', 'credentials'))
        result = self.capacity_check('credentials')
        self.scope_check()
        return result

    # r7 (search-guard-v1, runs B0GLNPC6K8 / B0H16FDSD8 of 2026-10-16): the SerpApi account had no searches left, the
    # four US patent and design searches were never sent, EPO was never tried and both reports led with 低. The balance
    # is read (free Account API) before the run and again before planning; short -> EPO, nothing usable -> stop here.
    def capacity_check(self, stage):
        task = read_json(self.run / 'task.json', {}) or {}
        import search_guard
        if not search_guard.enabled(task):
            return {}
        self.call(stage, py('search_guard.py', '--task-dir', self.run, '--check-capacity'), allow_fail=True)
        record = search_guard.capacity(self.run) or {}
        search_guard.apply_slot(record)   # r8: the SerpApi account the check chose, for every later script
        text = search_guard.notice(record)
        if text:
            with self.lock:
                self.state['search_notice'] = text
        route = search_guard.route_for(record)
        if route == 'none':
            raise StageFailed(stage, 'PIPELINE_PATENT_SEARCH_UNAVAILABLE', text)
        return {'serpapi_route': route, **({'serpapi_available': record.get('available'),
                                            'serpapi_renewal_date': record.get('renewal_date')}
                                           if record.get('state') == 'known' else {})}

    def recorded_key_slot(self):
        """r8: a resumed run keeps the SerpApi account (main or backup key) its capacity check chose."""
        task = read_json(self.run / 'task.json', {}) or {}
        import search_guard
        if search_guard.enabled(task):
            search_guard.apply_slot(search_guard.capacity(self.run) or {})

    def search_notice(self):
        # r9: the network, marketplace and unsearched-scope notices travel with the SerpApi notice in every output
        return {key: self.state[key] for key in ('search_notice', 'scope_notice', 'market_notice', 'network_notice',
                                                  'model_notice') if self.state.get(key)}

    def patent_search_check(self):
        """r7 (search-guard-v1): when no US patent or design discovery search succeeded, the run stops before the
        comparison instead of publishing a report whose patent sections were never searched."""
        task = read_json(self.run / 'task.json', {}) or {}
        import search_guard
        if not search_guard.enabled(task) or self.args.allow_limited_sources:
            return
        planned, succeeded, codes = search_guard.patent_discovery_outcome(
            task, read_json(self.run / 'evidence.json', {}) or {}, read_json(self.run / 'search-plan.json', {}) or {})
        if planned and not succeeded:
            record = search_guard.capacity(self.run) or {}
            balance = ('SerpApi 本期可用 %s 次，%s 恢复。' % (record.get('available'), record.get('renewal_date') or '恢复日期未载明')
                       if record.get('state') == 'known' else '')
            raise StageFailed('sources', 'PIPELINE_PATENT_SEARCH_NOT_EXECUTED',
                '本次 %d 条美国专利与外观检索一条都没有成功（原因代码：%s）。%s不进入比较与终审，以免报告把没有检索过的专利写成低风险。'
                '请在额度恢复后新建任务重跑；新任务开跑前会先查余额，余额不够时自动改用 EPO。'
                % (planned, '、'.join(codes) or '未知', balance))

    def s_capture(self):
        task = read_json(self.run / 'task.json', {})
        if not (task.get('request') or {}).get('url'):
            self.call('capture', py('record_user_product.py', '--task-dir', self.run))
            return {'entry': 'user_materials'}
        self.call('capture', node('doctor'))
        self.call('capture', node('capture-amazon', '--task-dir', self.run), timeout=600)
        captures = sorted(self.run.glob('*browser-capture.json'), key=lambda path: path.stat().st_mtime)
        if not captures:
            raise StageFailed('capture', 'PIPELINE_BROWSER_CAPTURE_MISSING', 'capture-amazon wrote no *browser-capture.json')
        self.call('capture', py('record_browser_product.py', '--task-dir', self.run, '--capture', captures[-1]))
        return {'capture': str(captures[-1])}

    def s_understanding(self):
        checkpoints = self.run / CHECKPOINT_DIR
        scope = checkpoints / '1-scope.json'
        drafted = not scope.is_file()
        if drafted:
            self.state.pop('understanding_fallback', None)
            command = py('product_understanding_host.py', '--task-dir', self.run, '--output-dir', checkpoints,
                         '--driver', self.args.understanding_driver, *self.host_flags_for_understanding())
            code, out, _ = self.call('understanding', command, allow_fail=True)
            if code != 0:
                # the model route is optional; the program draft is always available
                self.call('understanding', py('product_understanding_host.py', '--task-dir', self.run,
                                              '--output-dir', checkpoints, '--driver', 'program'))
            summary = self.summary(out) if code == 0 else {'driver': 'program', 'fallback_reason': 'host_exit_%d' % code}
            if self.args.understanding_driver == 'native' and summary.get('driver') != 'native':
                # r5d21: say it at checkpoint 1 - the search then uses only the listing's own phrase (run B0GLNPC6K8)
                self.state['understanding_fallback'] = {'reason': str(summary.get('fallback_reason') or '')[:200],
                                                        'attempts': summary.get('native_attempts')}
                # r9: the first model session of the run tells whether this account can use the review model at all
                import portable
                if portable.model_unavailable(str(summary.get('fallback_reason') or '') + '\n' + str(out or '')[-4000:]):
                    with self.lock:
                        self.state['model_notice'] = portable.model_notice()
        mark = self.state['checkpoints'].get('1')
        # r5d22: a draft written by this invocation (the first run, or a re-draft after the owner deleted 1-*.json)
        # is always shown once; before, a re-draft under --resume went straight on unseen
        released = not drafted and (mark == 'released' or (mark == 'waiting' and self.args.resume))
        if not (self.args.trust_host or released):
            self.state['checkpoints']['1'] = 'waiting'
            fallback = self.state.get('understanding_fallback')
            notice = ('\n注意：产品理解会话没有成功（%s），本次检索词只是程序从标题取的商品短语，召回会偏少。'
                      '建议先删除 %s 下的 1-*.json，再运行上面的命令重跑产品理解，程序会带着新草稿再停在这里；'
                      '确认要继续再按上面的步骤。'
                      % (fallback.get('reason') or '原因未知', checkpoints)) if fallback else ''
            raise Checkpoint(1, '检查点 1：请核对 %s 中的产品范围草稿，只修改 scope.objects[0].description（本体描述）、'
                             'scope.objects[0].visual_evidence.limitation_reason（主图呈现限制）和 scope.reasoning（备注），'
                             '然后运行：%s%s' % (scope, self.resume_command(), notice), scope)
        self.state['checkpoints']['1'] = 'released'
        return {'scope_draft': str(scope)}

    def host_flags_for_understanding(self):
        return self.host_flags() if self.args.understanding_driver == 'native' else []

    def s_scope(self):
        checkpoints = self.run / CHECKPOINT_DIR
        task = read_json(self.run / 'task.json', {})
        if not task.get('product_scope', {}).get('scope_sha256'):
            self.call('scope', py('record_product_scope.py', '--task-dir', self.run, '--input', checkpoints / '1-scope.json'))
        task = read_json(self.run / 'task.json', {})
        if (task.get('product', {}).get('analysis') or {}).get('status') != 'confirmed':
            self.call('scope', py('record_product_analysis.py', '--task-dir', self.run, '--input', checkpoints / '1-analysis.json'))
        self.call('scope', py('preflight.py', '--task', self.run / 'task.json', '--phase', 'evidence'))
        self.inventory('scope')
        self.call('scope', py('product_change.py', '--task-dir', self.run, '--rebase-progress'), allow_fail=True)

    def inventory(self, stage):
        """Asset and mark inventory for the source investigations (copyright / trade dress), once, from scope objects."""
        task = read_json(self.run / 'task.json', {}) or {}
        if (task.get('product') or {}).get('asset_scope_review'):
            return
        target = self.run / CHECKPOINT_DIR / '1-inventory.json'
        self.call(stage, py('product_understanding_host.py', '--task-dir', self.run, '--complete-inventory',
                            self.run / CHECKPOINT_DIR / '1-analysis.json', '--inventory-output', target))
        revise = ['--revise'] if (self.run / 'search-plan.json').is_file() else []
        self.call(stage, py('record_product_analysis.py', '--task-dir', self.run, '--input', target, *revise))

    def s_plan(self):
        if not (self.run / 'search-plan.json').is_file():
            # r7: the latest balance decides the US discovery route (the owner may have waited at checkpoint 1)
            self.capacity_check('plan')
            self.call('plan', py('generate_search_plan.py', '--task-dir', self.run))
        if not (self.run / 'normalized-candidates.json').is_file():
            # later tools read the candidate file unconditionally; an empty merge creates it
            self.call('plan', py('merge_candidates.py', '--task-dir', self.run))
        self.call('plan', py('mechanical_ledger.py', '--task-dir', self.run, '--steps', 'progress'))
        self.scope_check()          # r9: the plan's own gaps replace the checkpoint-1 prediction
        self.nothing_searchable()

    def nothing_searchable(self):
        """r9 (portable-v1): a task whose every target needs local-language terms the program does not generate (a
        Japan-only task: the rehearsal planned no row at all) stops here with the reason, instead of idling to
        PIPELINE_NO_SOURCE_EXECUTED after the discovery rounds."""
        task = read_json(self.run / 'task.json', {}) or {}
        import portable
        if not portable.enabled(task):
            return
        plan = read_json(self.run / 'search-plan.json', {}) or {}
        rows = [row for provider, values in (plan.get('queries') or {}).items() if provider != 'asset_provenance'
                for row in values or [] if isinstance(row, dict)]
        if rows or not portable.unsearched_scopes(task, plan):
            return
        raise StageFailed('plan', 'PIPELINE_NOTHING_SEARCHABLE',
            (self.state.get('scope_notice') or '') + '本任务没有任何可以执行的检索，不出报告，也没有消耗检索额度。'
            '如果要查的是美国市场，请用新目录、在命令里加 --jurisdictions US 重新建任务。')

    def marking_entry(self):
        from workflow_v24 import work_view_from_dir
        return next((entry for entry in work_view_from_dir(self.run).get('entries', [])
                     if entry.get('reason') == 'PATENT_MARKING_RESOLUTION_REQUIRED'), None)

    def compared_patents(self):
        """Selected target-country patent candidates with an exact detail record and their comparison counts."""
        task = read_json(self.run / 'task.json', {}) or {}
        evidence = read_json(self.run / 'evidence.json', {}) or {}
        dossier = read_json(self.run / 'core-dossier.json', {}) or {}
        targets = set(task.get('target_jurisdictions') or [])
        records = {entry.get('evidence_id'): entry for values in (evidence.get('collections') or {}).values()
                   if isinstance(values, list) for entry in values if isinstance(entry, dict)}
        current = None
        import pipeline_robust
        if pipeline_robust.enabled(task):
            # r5d4: the dossier file keeps every candidate it ever saw; a candidate set aside since (an abandoned
            # application, a pre-review exclusion) must not be named as the patent the marking points to.
            try:
                current = pipeline_robust.selected_candidate_ids(self.run)
            except (OSError, ValueError, KeyError, TypeError):
                current = None
        result = []
        for row in dossier.get('candidates', []):
            if row.get('right_type') not in {'patent', 'utility_model'} or row.get('jurisdiction') not in targets:
                continue
            if current is not None and row.get('candidate_id') not in current:
                continue
            reference = row.get('detail_evidence_id') or (row.get('public_page') or {}).get('evidence_id')
            record = records.get(reference)
            if not record:
                continue
            payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
            granted = (row.get('granted') or {}) if (row.get('granted') or {}).get('evidence_id') else {}
            units = {}
            for event in task.get('specialty_analysis_events', []):
                if (isinstance(event, dict) and event.get('kind') == 'comparison'
                        and event.get('candidate_id') == row['candidate_id'] and isinstance(event.get('elements'), list)):
                    units[event.get('unit_id')] = [element.get('result') for element in event['elements']]
            # A claim reads on the product when no element differs and at least one visibly corresponds.
            reads = sorted(unit for unit, results in units.items()
                           if results and 'differs' not in results and 'corresponds' in results)
            number = payload.get('publication_number')
            result.append({'candidate_id': row['candidate_id'], 'evidence_id': reference,
                           'publication_number': ('%s（授权公告；申请公布 %s）' % (granted['number'], number)) if granted else number,
                           'granted_number': granted.get('number'), 'title': payload.get('title'),
                           'compared_units': len(units), 'units_without_difference': reads})
        # a granted text first, then the share of claim units without a differing element
        result.sort(key=lambda item: (not item['granted_number'],
                                      -len(item['units_without_difference']) / max(1, item['compared_units'])))
        return result

    def s_marking(self):
        entry = self.marking_entry()
        if entry is None:
            return {'marking': 'resolved_or_not_required'}
        if self.args.skip_marking:
            self.log(stage='marking', note='PATENT_MARKING_RESOLUTION_SKIPPED_BY_FLAG')
            return {'marking': 'skipped_by_flag'}
        compared = self.compared_patents()
        reading = [row for row in compared if row['units_without_difference']]
        if reading:
            return self.record_marking_followup(reading)
        if self.r6():
            return self.record_marking_unresolved(compared)
        import advance_work
        card = advance_work.action_card(self.run, entry)
        path = self.run / CHECKPOINT_DIR / '1b-marking.json'
        write_json(path, {'checkpoint': 1, 'part': 'patent_marking_resolution', 'marking':
                          read_json(self.run / CHECKPOINT_DIR / '1-marking.json', {}), 'action_card': card,
                          'compared_patent_candidates': compared,
                          'note': '有界发现检索没有找到独立权利要求与产品逐要素无差异的美国专利；请按动作卡用结构词手工检索。'})
        self.state['checkpoints']['1b'] = 'waiting'
        raise Checkpoint(1, '检查点 1b（专利标注解析）：页面标注了专利，自动检索没有找到逐要素对应的专利。按 %s 的动作卡解析专利号'
                         '（官网虚拟标记页；Google Patents 用产品结构的通用名词检索——个人持有的专利用品牌搜不到；'
                         'record_candidate_lead.py 登记、record_product_analysis.py --revise 记入 patent_claim_followup；'
                         '找不到也如实记录），然后运行：%s' % (path, self.resume_command()), path)

    def record_marking_unresolved(self, compared):
        """r6 (report-always-v1): the page says PATENTED without a number and no compared US patent reads on the
        product. The run no longer stops for a hand search (checkpoint 1b): the executed US patent searches are recorded
        as the follow-up and the report names the marking as unresolved."""
        task = read_json(self.run / 'task.json', {}) or {}
        evidence = read_json(self.run / 'evidence.json', {}) or {}
        runs = {run.get('run_id'): run for run in evidence.get('source_runs', []) if isinstance(run, dict)}
        searches = [entry.get('evidence_id') for values in (evidence.get('collections') or {}).values()
                    if isinstance(values, list) for entry in values
                    if isinstance(entry, dict) and entry.get('evidence_id') and entry.get('operation') == 'search'
                    and entry.get('jurisdiction') == 'US' and entry.get('right_type') in ('patent', 'design')
                    and (runs.get(entry.get('source_run_id')) or {}).get('status') == 'success'
                    and isinstance((entry.get('payload') or {}).get('candidates'), list)]
        if not searches:
            self.log(stage='marking', note='PATENT_MARKING_UNRESOLVED_WITHOUT_SEARCH')
            return {'marking': 'unresolved_no_search'}
        names = '；'.join('%s（%d 个比对单元）' % (row['publication_number'], row['compared_units']) for row in compared) or '无'
        payload = {'query_terms': task.get('query_terms') or [],
                   'product': {'patent_claim_followup': {
                       'status': 'completed', 'evidence_ids': sorted(set(searches))[:6],
                       'findings': ('页面标注 PATENTED 但未列专利号。本轮有界的美国专利与外观检索，以及入选专利的逐要素比对，'
                                    '都没有找到与产品逐要素无差异的美国专利（已比对：%s）。该标注对应的专利未能解析，'
                                    '列为上架前需向供应商或卖家核实的事项；不据此认定风险高低。' % names)}},
                   'analysis': {'reviewer': 'program:marking-followup',
                                'reasoning': '按已执行的美国专利检索与逐要素比对记录专利标注未能解析；不改变产品范围、事实或检索词。'}}
        path = self.run / CHECKPOINT_DIR / '1b-marking-auto.json'
        write_json(path, payload)
        self.call('marking', py('record_product_analysis.py', '--task-dir', self.run, '--input', path, '--revise'))
        self.call('marking', py('mechanical_ledger.py', '--task-dir', self.run))
        self.state['checkpoints']['1b'] = 'unresolved_recorded_by_program'
        return {'marking': 'unresolved_recorded', 'compared': [row['publication_number'] for row in compared]}

    def record_marking_followup(self, reading):
        """The marking follow-up from the discovery itself: what was found and compared, never an identity claim."""
        task = read_json(self.run / 'task.json', {}) or {}
        names = '；'.join('%s（%s，%d 个比对单元中 %d 个无差异要素）' % (row['publication_number'], row['title'] or '标题未记录',
                                                         row['compared_units'], len(row['units_without_difference']))
                         for row in reading)
        payload = {'query_terms': task.get('query_terms') or [],
                   'product': {'patent_claim_followup': {
                       'status': 'completed', 'evidence_ids': [row['evidence_id'] for row in reading],
                       'findings': ('页面标注 PATENTED 但未列专利号。有界结构检索入选并取得准确记录或公开文本的美国专利中，'
                                    '独立权利要求与产品图片逐要素比对没有不同要素的有：%s。页面标注最可能指向其中之一或其同族，'
                                    '但标注与号码的对应未经权利人或官网确认；评级以这些候选的专项比对为准。' % names)}},
                   'analysis': {'reviewer': 'program:marking-followup',
                                'reasoning': '按有界发现检索与逐要素比对结果记录专利标注的解析情况；不改变产品范围、事实或检索词。'}}
        path = self.run / CHECKPOINT_DIR / '1b-marking-auto.json'
        write_json(path, payload)
        self.call('marking', py('record_product_analysis.py', '--task-dir', self.run, '--input', path, '--revise'))
        self.call('marking', py('mechanical_ledger.py', '--task-dir', self.run))
        self.state['checkpoints']['1b'] = 'resolved_by_program'
        return {'marking': 'recorded_from_compared_candidates',
                'candidates': [row['publication_number'] for row in reading]}

    def progress_signature(self):
        evidence = read_json(self.run / 'evidence.json', {})
        ledger = read_json(self.run / 'materiality-annotations.json', {})
        plan = read_json(self.run / 'search-plan.json', {})
        queries = sum(len(rows) for rows in (plan.get('queries') or {}).values() if isinstance(rows, list))
        task = read_json(self.run / 'task.json', {}) or {}
        attempts = self.run / 'api-attempts.jsonl'
        return [len(evidence.get('source_runs', [])), len(ledger.get('annotations', [])), queries,
                len(task.get('specialty_analysis_events', [])), len(task.get('discovery_semantic_reviews', [])),
                len(evidence.get('review_progress_events', [])),
                len((evidence.get('collections') or {}).get('asset_provenance', [])),
                attempts.stat().st_size if attempts.is_file() else 0]

    def speed(self):
        import pipeline_robust
        return pipeline_robust.speed_enabled(read_json(self.run / 'task.json', {}) or {})

    def design_screen(self):
        """r5d17 (owner decision): designs plainly different in overall impression leave before the final review."""
        if not (SCRIPTS / 'design_screen.py').is_file():
            return False
        import design_screen
        return design_screen.enabled(read_json(self.run / 'task.json', {}) or {})

    def discovery_signature(self):
        """r5d17: the part of the progress signature a further discovery round can act on - without the selected
        candidates' exact detail reads (they feed the core stage), the attempt log and the progress events. Run
        B0HF19R4YF: round 2 only read nine candidate details, so round 3 ran thirteen steps in 43 s and found nothing."""
        evidence = read_json(self.run / 'evidence.json', {}) or {}
        details = sum(1 for run in evidence.get('source_runs', []) if run.get('operation') == 'candidate_detail')
        signature = self.progress_signature()
        return [signature[0] - details, *signature[1:5], signature[6]]

    def ready_sources(self):
        """Exact planned rows the scheduler would submit now (no call when nothing is ready)."""
        from workflow_v24 import work_view_from_dir
        try:
            entries = work_view_from_dir(self.run).get('entries', [])
        except (OSError, ValueError, KeyError, TypeError):
            return 1      # cannot tell: let the scheduler decide
        # advance_work.actionable_packet submits exactly the ready source_lookup rows. A row whose query already
        # returned (its result review is what is still open) is not dispatched again: re-dispatching it changes
        # nothing and two such rounds make the progress rule cancel the query.
        evidence = read_json(self.run / 'evidence.json', {}) or {}
        answered = {run.get('query_id') for run in evidence.get('source_runs', [])
                    if run.get('status') in {'success', 'no_result', 'hit', 'truncated'}}
        ready = [entry for entry in entries if entry.get('state') == 'ready' and entry.get('kind') == 'source_lookup'
                 and entry.get('query_id') not in answered]
        if ready and self.robust():
            # r5d4: rows the runner's own gate holds are not dispatchable yet (sending them only books a deferral)
            import pipeline_robust
            try:
                ready, _ = pipeline_robust.dispatchable(self.run, read_json(self.run / 'search-plan.json', {}) or {}, ready)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return len(ready)

    def ready_source_ids(self):
        """Query ids of dispatchable ready rows (for the exit check and its message)."""
        from workflow_v24 import work_view_from_dir
        try:
            entries = work_view_from_dir(self.run).get('entries', [])
        except (OSError, ValueError, KeyError, TypeError):
            return []
        evidence = read_json(self.run / 'evidence.json', {}) or {}
        answered = {run.get('query_id') for run in evidence.get('source_runs', [])
                    if run.get('status') in {'success', 'no_result', 'hit', 'truncated'}}
        ready = [entry for entry in entries if entry.get('state') == 'ready' and entry.get('kind') == 'source_lookup'
                 and entry.get('query_id') not in answered]
        import pipeline_robust
        try:
            ready, _ = pipeline_robust.dispatchable(self.run, read_json(self.run / 'search-plan.json', {}) or {}, ready)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return sorted({str(entry.get('query_id')) for entry in ready})

    def external_runs(self):
        evidence = read_json(self.run / 'evidence.json', {}) or {}
        local = {'public_source', 'asset_provenance', 'local_agent_review', 'amazon_browser'}
        return [run for run in evidence.get('source_runs', []) if run.get('provider') not in local
                and run.get('status') in {'success', 'no_result', 'hit', 'truncated'}
                and run.get('submission_state') != 'not_submitted']

    def deferral_summary(self):
        counts = {}
        path = self.run / 'api-attempts.jsonl'
        for line in (path.read_text(encoding='utf-8').splitlines() if path.is_file() else []):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('status') != 'success':
                key = '%s:%s' % (row.get('provider'), row.get('reason') or row.get('error_code') or row.get('status'))
                counts[key] = counts.get(key, 0) + 1
        return counts

    def ready(self):
        from review_readiness import readiness
        try:
            return readiness(self.run)
        except ValueError as exc:
            return {'ready': False, 'error': str(exc)[:300], 'blockers': []}
        except Exception as exc:
            if not self.r6():
                raise
            return {'ready': False, 'error': ('PIPELINE_READINESS_UNEXPECTED_' + type(exc).__name__.upper()
                                              + ': ' + str(exc))[:300], 'blockers': []}

    def s_sources(self):
        """Each round follows the gates in their real order: direction and pre-submission reviews first, then the
        progress registration and the submission of exactly-ready rows, then the post-result review and triage.
        The scheduler is only called when a row is ready, so empty dispatch rounds never accumulate the
        no-progress count that cancels planned queries."""
        self.require_discovery_sources('sources')
        idle, rounds = 0, self.state.setdefault('rounds', [])
        robust, speed = self.robust(), self.speed()
        limit = PRECISE_SOURCE_ROUNDS if self.precise() else MAX_ROUNDS
        # r5d4: rounds count per invocation (a resumed stage used to inherit the earlier rounds and run none)
        numbers = range(len(rounds) + 1, len(rounds) + limit + 1) if robust else range(len(rounds) + 1, limit + 1)
        for number in numbers:
            before = self.progress_signature()
            found_before = self.discovery_signature() if speed else None
            started = time.time()
            failed = self.source_round('sources', robust)
            after = self.progress_signature()
            found_after = self.discovery_signature() if speed else None
            gate = self.ready()
            rounds.append({'round': number, 'seconds': round(time.time() - started, 1), 'before': before,
                           'after': after, 'ready': bool(gate.get('ready')), **({'review_failed': True} if failed else {}),
                           **({'discovery_idle': True} if speed and after != before and found_after == found_before else {})})
            self.save()
            if gate.get('ready'):
                break
            if self.boxed('sources_seconds'):
                # r5d21: the time box stops starting discovery rounds; open work is closed at the readiness check
                rounds[-1]['time_box'] = 'sources_seconds'
                break
            # a round whose review session itself failed (network, sleep) is not idle: the next round runs it again
            unchanged = after == before or (speed and found_after == found_before)
            idle = idle + 1 if unchanged and not (failed and robust) else 0
            if idle >= MAX_IDLE_ROUNDS:
                break
        if robust and not self.boxed('sources_seconds'):
            self.flush_sources('sources')
        external = self.external_runs()
        if not external and not self.args.allow_limited_sources and self.r6():
            # r6: one more round before giving up (a network drop at the very start of the run)
            self.source_round('sources', robust)
            external = self.external_runs()
        if not external and not self.args.allow_limited_sources:
            raise StageFailed('sources', 'PIPELINE_NO_SOURCE_EXECUTED',
                '本轮没有任何外部检索真正提交（未提交原因：%s）。不会进入比较与终审；请把本错误和 pipeline-log.jsonl 发给维护者。'
                % json.dumps(self.deferral_summary(), ensure_ascii=False))
        self.patent_search_check()
        return {'rounds': len(rounds), 'external_runs': len(external)}

    def source_round(self, stage, robust):
        """One discovery round in the gates' real order; True when a review session itself failed."""
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))
        code, out, _ = self.call(stage, py('discovery_review_host.py', '--task-dir', self.run, '--stages', 'direction,before',
                                           *self.host_flags()), allow_fail=True)
        failed = self.review_failed(code, out)
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run, '--steps', 'progress'))
        if self.ready_sources():
            self.call(stage, py('advance_work.py', '--task-dir', self.run, '--execute-sources',
                                '--output-format', 'compact'))
            if robust:
                self.closeouts(stage)
        # Returned cards are triaged before the result review: the ledger's bounded-stop step can then close a
        # single-page search exactly (every position has a decision), and the host reviews only what is left.
        self.call(stage, py('merge_candidates.py', '--task-dir', self.run))
        self.call(stage, py('triage_defaults.py', '--task-dir', self.run), allow_fail=True)
        if robust:
            # r5d4: the source-provenance review does not depend on triage results; it runs beside the hosts
            self.parallel_hosts(stage, provenance=True)
        else:
            self.parallel_hosts()
            self.call(stage, py('provenance_host.py', '--task-dir', self.run, *self.host_flags()), allow_fail=True)
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))
        code, out, _ = self.call(stage, py('discovery_review_host.py', '--task-dir', self.run, '--stages', 'after',
                                           *self.host_flags()), allow_fail=True)
        failed = failed or self.review_failed(code, out)
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))
        self.refine(stage)
        self.call(stage, py('generate_search_plan.py', '--task-dir', self.run, '--expand'))
        return failed

    def screen_recorded(self, stage):
        """After a pre-review exclusion: refresh the candidate projection, then re-bind the bounded discovery stops
        whose triage digest the exclusion changed (otherwise the round plans a needless refinement search)."""
        self.call(stage, py('merge_candidates.py', '--task-dir', self.run))
        self.call(stage, py('prereview_screen.py', '--task-dir', self.run, '--rebind'), allow_fail=True)

    def closeouts(self, stage):
        """r5d4: an exact read the source answered with "no such record" is closed by the program at once."""
        self.call(stage, py('pipeline_robust.py', '--task-dir', self.run, '--closeouts'), allow_fail=True)

    def flush_sources(self, stage, rounds=2):
        """r5d4: never leave a stage with dispatchable discovery rows (B0FSJBDTF2 entered checkpoint 2 with seven
        ready queries, two of them the ones that find the decisive design patents)."""
        for _ in range(rounds):
            if not self.ready_sources():
                return []
            self.source_round(stage, True)
        return self.ready_source_ids()

    def refine(self, stage):
        """The reviewer's 'search again' verdicts become follow-up rows (or bounded stops), then the ledger."""
        if not (SCRIPTS / 'auto_refine.py').is_file():
            return
        code, out, _ = self.call(stage, py('auto_refine.py', '--task-dir', self.run), allow_fail=True)
        try:
            summary = json.loads((out or '').strip().splitlines()[-1]) if code == 0 and out and out.strip() else {}
        except ValueError:
            summary = {}
        if summary.get('refined') or summary.get('stopped') or summary.get('parents_closed'):
            self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))

    def recall_task(self):
        if not (SCRIPTS / 'recall_screen.py').is_file():
            return False
        import recall
        return recall.enabled(read_json(self.run / 'task.json', {}) or {})

    def parallel_hosts(self, stage='sources', provenance=False):
        """Text and visual triage hosts work on disjoint candidates; run them side by side (r5d4 tasks: with the
        source-provenance review, which does not depend on triage results). r5d20 recall tasks: large result sets get
        the list screen first (recall_screen.py, titles and first drawings), so the hosts judge only what is left."""
        if self.recall_task():
            outcomes = self.run_parallel(stage, [py('recall_screen.py', '--task-dir', self.run, '--mode', mode,
                                                    *self.host_flags()) for mode in ('text', 'image')])
            self.state['recall_screen'] = [self.summary(out) for _, out, _ in outcomes]
        scripts = ('text_triage_host.py', 'visual_triage_host.py') + (('provenance_host.py',) if provenance else ())
        results = self.run_parallel(stage, [py(script, '--task-dir', self.run, *self.host_flags()) for script in scripts])
        summaries = {script: self.summary(out) for script, (_, out, _) in zip(scripts, results)}
        self.state['host_summaries'] = {key: value for key, value in summaries.items() if key != 'provenance_host.py'}
        return summaries

    def core_round(self, stage, robust, ran, number):
        """One core round: exact reads, the pre-review status screen, dossier, element comparison beside the
        independent exclusion check, then the screen's commit."""
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))
        # A refinement planned in this stage still passes the direction and pre-submission reviews before it is
        # sent (r5d real run: two refinements stayed unreviewed and open at checkpoint 2).
        self.call(stage, py('discovery_review_host.py', '--task-dir', self.run, '--stages', 'direction,before',
                            *self.host_flags()), allow_fail=True)
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run, '--steps', 'progress'))
        if self.ready_sources():
            self.call(stage, py('advance_work.py', '--task-dir', self.run, '--execute-sources', '--output-format', 'compact'))
            if robust:
                self.closeouts(stage)
            # r5d25: the returned cards are merged and triaged before the result review, as in a discovery round (run
            # B0GLNPC6K8: the review ran first, saw "result_count: 0" for searches that returned 2 and 4 cards, called
            # them zero-hit and asked for a needless rewrite; both final reviews flagged the contradiction)
            self.call(stage, py('merge_candidates.py', '--task-dir', self.run))
            self.call(stage, py('triage_defaults.py', '--task-dir', self.run), allow_fail=True)
            if robust:
                self.parallel_hosts(stage, provenance=True)
            else:
                self.parallel_hosts()
            self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))
            self.call(stage, py('discovery_review_host.py', '--task-dir', self.run, '--stages', 'after',
                                *self.host_flags()), allow_fail=True)
        elif robust:
            # r5d7: a result review goes stale when a triage changes (a reopen, the pre-review screen) without any new
            # dispatch; it is reviewed again here instead of waiting at checkpoint 2 (B0GLNPC6K8: API_DISCOVERY_REVIEW_REQUIRED)
            self.call(stage, py('discovery_review_host.py', '--task-dir', self.run, '--stages', 'after',
                                *self.host_flags()), allow_fail=True)
        if not robust:
            for script in ('core_dossier.py', 'comparison_host.py'):
                extra = self.host_flags() if script == 'comparison_host.py' else []
                code, _, _ = self.call(stage, py(script, '--task-dir', self.run, *extra), allow_fail=True)
                ran.append({'round': number, 'script': script, 'returncode': code})
        else:
            # r5d4: an abandoned or lifetime-expired US application leaves before any dossier or comparison work
            code, out, _ = self.call(stage, py('prereview_screen.py', '--task-dir', self.run, '--status'), allow_fail=True)
            ran.append({'round': number, 'script': 'prereview_screen.py --status', 'returncode': code})
            if self.summary(out).get('recorded'):
                self.screen_recorded(stage)
            code, _, _ = self.call(stage, py('core_dossier.py', '--task-dir', self.run), allow_fail=True)
            ran.append({'round': number, 'script': 'core_dossier.py', 'returncode': code})
            # the element comparison and the independent exclusion checks never see each other's answer
            design = self.design_screen()
            comparison = py('comparison_host.py', '--task-dir', self.run, *self.host_flags())
            checks = ([py('prereview_screen.py', '--task-dir', self.run, '--claims', *self.host_flags())]
                      + ([py('design_screen.py', '--task-dir', self.run, '--check', *self.host_flags())] if design else []))
            if self.precise():
                # r5d21: the independent checks only run where the comparison (A) already proposes an exclusion, so
                # they follow it instead of running beside it for every selected candidate (they still never see A)
                code, _, _ = self.call(stage, comparison, allow_fail=True)
                outcomes = [(code, '', '')] + self.run_parallel(stage, checks)
            else:
                outcomes = self.run_parallel(stage, [comparison] + checks)
            ran.append({'round': number, 'script': 'comparison_host.py', 'returncode': outcomes[0][0]})
            ran.append({'round': number, 'script': 'prereview_screen.py --claims', 'returncode': outcomes[1][0]})
            if design:
                ran.append({'round': number, 'script': 'design_screen.py --check', 'returncode': outcomes[2][0]})
            code, out, _ = self.call(stage, py('prereview_screen.py', '--task-dir', self.run, '--commit'), allow_fail=True)
            ran.append({'round': number, 'script': 'prereview_screen.py --commit', 'returncode': code})
            if self.summary(out).get('recorded'):
                self.screen_recorded(stage)
            if design:
                code, out, _ = self.call(stage, py('design_screen.py', '--task-dir', self.run, '--commit'), allow_fail=True)
                ran.append({'round': number, 'script': 'design_screen.py --commit', 'returncode': code})
                if self.summary(out).get('recorded'):
                    self.screen_recorded(stage)
        self.call(stage, py('mechanical_ledger.py', '--task-dir', self.run))
        self.refine(stage)
        self.call(stage, py('generate_search_plan.py', '--task-dir', self.run, '--expand'))

    def s_core(self):
        """Selected candidates: exact detail reads, dossier, element comparison; repeated until nothing changes
        (a detail read or a comparison can hand off a further exact read)."""
        ran = []
        robust, speed = self.robust(), self.speed()
        for number in range(1, (PRECISE_CORE_ROUNDS if self.precise() else 3) + 1):
            if number > 1 and self.boxed('core_seconds'):
                ran.append({'round': number, 'script': 'time_box', 'returncode': 0, 'skipped': 'core_seconds'})
                break
            before = self.progress_signature()
            self.core_round('core', robust, ran, number)
            if self.progress_signature() == before:
                break
            # r5d17: a stage that is already ready for the final review has nothing left for another round (run
            # B0HF19R4YF: round 2 ran fourteen steps in 62 s and changed nothing)
            if speed and self.ready().get('ready'):
                ran.append({'round': number, 'script': 'readiness', 'returncode': 0, 'ready': True})
                break
        if robust and not self.boxed('core_seconds'):
            # r5d4: dispatchable discovery rows are sent here; a stage never ends with them silently unsent
            # (r5d21: once the time box is reached they are closed at the readiness check instead)
            left = self.flush_sources('core')
            if left and self.box():
                # r5d23: a time-box task never fails here; the readiness check sends what it can and the closure lists
                # the rest as work this round did not complete (B0GLNPC6K8: the core stage failed on rows a single
                # unresolved card held back, after the core limit had already passed)
                self.state['undispatched_at_core_exit'] = left[:20]
                self.save()
            elif left:
                status = read_json(self.run / 'continuous-work-status.json', {}) or {}
                raise StageFailed('core', 'PIPELINE_READY_SOURCES_UNDISPATCHED',
                    '核心阶段结束时仍有 %d 个可派发的检索没有发出（%s）。派发状态：%s。请把本错误和 pipeline-log.jsonl 发给维护者。'
                    % (len(left), '、'.join(left[:12]), json.dumps({key: status.get(key) for key in (
                        'source_dispatch_deferred', 'source_dispatch_gated', 'stage') if status.get(key)},
                        ensure_ascii=False)[:600]))
        self.call('core', py('advance_work.py', '--task-dir', self.run, '--write-agent-packet', '--output-format', 'compact'))
        return {'ran': ran}

    def visual_refusals(self):
        """Visual-host batches refused before any judgment in its last run (no picture, unpreparable views)."""
        summary = read_json(self.run / 'visual-triage' / 'last-run.json', {}) or {}
        return [{key: row.get(key) for key in ('status', 'phase', 'reason', 'candidate_ids', 'work_ids', 'next_action')
                 if row.get(key) is not None}
                for row in summary.get('batches', []) if isinstance(row, dict) and row.get('status') == 'needs_info']

    def s_readiness(self):
        gate = self.ready()
        if gate.get('ready'):
            return {'ready': True}
        if self.robust():
            # r5d4: before stopping (and again on every --resume after checkpoint 2) the program runs one more core
            # round itself, so work it can do - a dispatch, a triage, a dossier, a comparison - is never left to hand
            # work (B0FSJBDTF2: about 50 minutes by hand after checkpoint 2).
            # r5d7: repeated while it changes something - a rewrite planned at the end of one round is reviewed and sent
            # in the next (B0GLNPC6K8: the catch-up planned 'butterfly attachment' last, then stopped at checkpoint 2)
            ran = []
            # r5d21: time-box tasks use the time left before the core limit; other precision tasks one round
            limit = 3 if self.box() else (PRECISE_CATCH_UP_ROUNDS if self.precise() else 3)
            for number in range(1, limit + 1):
                if self.boxed('core_seconds'):
                    ran.append({'round': number, 'script': 'time_box', 'returncode': 0, 'skipped': 'core_seconds'})
                    break
                before = self.progress_signature()
                self.core_round('readiness', True, ran, number)
                if self.progress_signature() == before:
                    break
            if not self.boxed('core_seconds'):
                self.flush_sources('readiness', rounds=1)
            self.state.setdefault('catch_up', []).append({'at': now(), 'ran': ran})
            self.save()
            gate = self.ready()
            if gate.get('ready'):
                return {'ready': True, 'catch_up': True}
            closed = self.close_time_box(gate)
            if closed is not None:
                gate = self.ready()
                if gate.get('ready'):
                    return {'ready': True, 'time_box': closed}
            if self.r6():
                gate = self.settle_readiness(gate)
                if gate.get('ready'):
                    return {'ready': True, 'settled': True, **({'time_box': self.state['time_box']}
                                                                if self.state.get('time_box') else {})}
        rejected = []
        for summary in (self.state.get('host_summaries') or {}).values():
            if isinstance(summary, dict):
                rejected += summary.get('rejected', []) + summary.get('unresolved', [])
        if self.robust():
            rejected += self.visual_refusals()
        budget = self.analysis_budget_notice()
        path = self.run / CHECKPOINT_DIR / '2-triage.json'
        write_json(path, {'checkpoint': 2, 'error': gate.get('error'), **budget,
                          'blockers': [{key: row.get(key) for key in ('kind', 'state', 'reason', 'candidate_id', 'query_id',
                                                                     'work_id', 'next_action') if row.get(key) is not None}
                                       for row in gate.get('blockers', [])],
                          'stale_progress_items': gate.get('stale_progress_items', []),
                          'publication_preparation_errors': (gate.get('publication_preparation') or {}).get('errors', []),
                          'host_rejected_or_unresolved': rejected,
                          'how': '对每项按 advance_work.py --output-format compact 的动作卡处理（入选／不入选的例外改判、'
                                 '补读原件），程序未登记的项不会被当作排除。'})
        if self.r6():
            # r6: never a hand-work checkpoint; what is left is a fault of the program's own records - named, not queued
            self.state['checkpoints']['2'] = 'not_used'
            raise StageFailed('readiness', 'PIPELINE_READINESS_NOT_SETTLED',
                              '时间收口与进度登记后仍未就绪（清单见 %s）。这是程序记录本身的问题，不需要也不要手工处理；'
                              '请把运行目录打包交给维护者。' % path)
        self.state['checkpoints']['2'] = 'waiting'
        raise Checkpoint(2, '检查点 2：仍有 %d 项分流或准备工作需要人工判断，清单见 %s；处理后运行：%s%s'
                         % (len(gate.get('blockers', [])) + len(gate.get('stale_progress_items', [])) + len(rejected),
                            path, self.resume_command(),
                            ('。' + budget['analysis_budget']['message']) if budget else ''), path)

    def settle_readiness(self, gate):
        """r6: after the catch-up and the closure, refresh the progress registration and close the time box again over
        whatever is still open (merged with the first closure), at most twice; returns the last readiness gate."""
        for _ in range(2):
            self.call('readiness', py('mechanical_ledger.py', '--task-dir', self.run, '--steps', 'progress'), allow_fail=True)
            self.call('readiness', py('product_change.py', '--task-dir', self.run, '--rebase-progress'), allow_fail=True)
            gate = self.ready()
            if gate.get('ready'):
                return gate
            if self.close_time_box(gate, merge=True) is None:
                return gate
            gate = self.ready()
            if gate.get('ready'):
                return gate
        return gate

    def close_time_box(self, gate, merge=False):
        """r5d21 (time-box-v1, owner decision 2026-10-15): instead of stopping at checkpoint 2, every still-open work
        entry becomes a disclosed limitation of this round (time_box.py) and the run goes on to the final review."""
        if not self.box():
            return None
        import time_box
        from workflow_v24 import work_view_from_dir
        task = read_json(self.run / 'task.json', {}) or {}
        existing = time_box.record(self.run)
        if existing is not None and not merge:
            return None                       # one closure per task; work that appears after it is not covered
        view = work_view_from_dir(self.run)
        why = 'time_box' if self.boxed('core_seconds') else 'round_closed'
        errors = (gate.get('publication_preparation') or {}).get('errors', [])
        unestablished = [work.strip() for error in errors if str(error).startswith('EVIDENCE_LIMITATION_NOT_ESTABLISHED:')
                         for work in str(error).split(':', 1)[1].split(',')]
        data = time_box.close(self.run, task, view.get('entries', []), active_seconds=self.active(), why=why,
                              unestablished=unestablished, keep=(existing or {}).get('work_ids', []) if merge else ())
        self.call('readiness', py('mechanical_ledger.py', '--task-dir', self.run, '--steps', 'progress'), allow_fail=True)
        summary = {'closed_work': len(data['work_ids']), 'active_minutes': round(data['active_seconds'] / 60, 1),
                   'why': why, 'blockers_before': len(gate.get('blockers', []))}
        self.state['time_box'] = summary
        self.save()
        return summary

    def analysis_budget_notice(self):
        """r5d9: name an exhausted model-analysis allowance at checkpoint 2; the hosts that need it cannot run, so
        the listed items are its consequence (B0GLNPC6K8: a sleep-drained allowance read as 'inventory pending')."""
        try:
            import host_triage
            task = read_json(self.run / 'task.json', {}) or {}
            if host_triage.policy(task) is None:
                return {}
            left = host_triage.remaining_seconds(self.run, task)
            limit = host_triage.policy(task)['analysis_seconds']
        except (ValueError, OSError, KeyError, TypeError):
            return {}
        if left >= 120:
            return {}
        return {'analysis_budget': {'remaining_seconds': round(left), 'limit_seconds': limit,
                'message': '本任务的模型分析时长额度（%d 分钟，不含电脑睡眠时间）只剩 %d 秒，比对和分流会话已无法运行，'
                           '上面各项是它的后果；请把运行目录打包交给维护者，不要手工补做。' % (limit // 60, round(left))}}

    def review_dir(self):
        return self.run / 'final-review'

    STALE_REVIEW_CODES = ('REPORT_REVIEW_HOST_RETAINED_FREEZE_CHANGED', 'REPORT_REVIEW_HOST_RETAINED_FREEZE_REQUIRED',
                          'FINAL_REVIEW_RETAINED_PACKET_OR_PROMPT_CHANGED', 'FINAL_REVIEW_RETAINED_RUNTIME_CHANGED',
                          'FINAL_REVIEW_RETAINED_RUNTIME_UNAVAILABLE', 'FINAL_REVIEW_RETAINED_RUNTIME_UNCONFIRMED',
                          'FINAL_REVIEW_RETAINED_SUCCESS_CHANGED', 'FINAL_REVIEW_RETAINED_IDENTITY_CONFLICT')

    def set_aside_review(self, target):
        """r6: a final-review directory that no longer matches the inputs is kept as final-review.stale-N and the
        review starts again (it used to stop the run until someone removed the directory by hand)."""
        if not target.exists():
            return None
        number = 1
        while target.with_name(target.name + '.stale-%d' % number).exists():
            number += 1
        aside = target.with_name(target.name + '.stale-%d' % number)
        for attempt in range(5):
            try:
                target.rename(aside)
                break
            except OSError:                       # Windows: a file still held open for a moment
                if attempt == 4:
                    raise
                time.sleep(1 + attempt)
        for name in ('adjudication.json', 'adjudication-worksheet.json'):
            if (self.run / name).is_file():
                os.replace(self.run / name, aside / name)
        self.log(stage='review', note='final_review_set_aside', directory=str(aside))
        return aside

    def s_review(self):
        target = self.review_dir()
        if (target / '1' / 'review.json').is_file() and (target / '2' / 'review.json').is_file():
            return {'review_dir': str(target), 'reused': True}
        if self.r6():
            return self.review_r6(target)
        flags = self.host_flags()
        resume = ['--resume-existing'] if target.exists() else []
        code, out, err = self.call('review', py('report_review_host.py', '--task-dir', self.run, '--output-dir', target,
                                                '--preflight', *resume, *flags), allow_fail=True)
        if code != 0:
            # the preflight prints its report; name its first problem, not a warning that happens to come last
            try:
                report = json.loads(out[out.index('{'):out.rindex('}') + 1])
            except ValueError:
                report = {}
            problems = report.get('problems') or []
            first = problems[0] if problems else {}
            hint = {'REPORT_REVIEW_HOST_INPUT_TOO_LARGE_AFTER_LOSSLESS_ENCODING':
                    '终审材料包超过单次审阅上限（%s 模块 %s 字符，上限 %s）。入选并完成比对的候选过多：请在检查点 2 的动作卡中'
                    '对明显不同用途的入选候选按变更流程改判，再 --resume。' % (first.get('module'), first.get('chars'),
                                                                        first.get('limit')),
                    'EXECUTION_REVIEW_BUDGET_INSUFFICIENT': self.review_budget_hint(first)}.get(first.get('code'), '')
            failure = StageFailed('review', first.get('code') or error_code(err + '\n' + out),
                                  (hint + '\n' if hint else '') + (err or out)[-1200:])
            if first.get('code') == 'EXECUTION_REVIEW_BUDGET_INSUFFICIENT':
                failure.owner_action = hint     # printed whole: the detail keeps only its tail
            self.note_model(err + '\n' + out)
            raise failure
        box = self.box()
        session = str(box['review_session_seconds']) if box else '1800'      # r5d21: time-box tasks 15 minutes
        self.call('review', py('report_review_host.py', '--task-dir', self.run, '--output-dir', target,
                               '--max-parallel', '6', '--timeout', session, *resume, *flags), timeout=7200)
        return {'review_dir': str(target)}

    def review_r6(self, target):
        """r6: preflight, then the pass with the run's deadline; a review directory that no longer fits the inputs is
        set aside once and the review starts again. No owner action: a short allowance leaves modules pending."""
        import report_always
        flags = self.host_flags()
        for attempt in (1, 2):
            resume = ['--resume-existing'] if target.exists() else []
            code, out, err = self.call('review', py('report_review_host.py', '--task-dir', self.run, '--output-dir', target,
                                                    '--preflight', *resume, *flags), allow_fail=True)
            if code != 0:
                try:
                    report = json.loads(out[out.index('{'):out.rindex('}') + 1])
                except ValueError:
                    report = {}
                problems = report.get('problems') or []
                first = problems[0] if problems else {}
                if attempt == 1 and first.get('code') in self.STALE_REVIEW_CODES:
                    self.set_aside_review(target)
                    continue
                self.note_model(err + '\n' + out)
                raise StageFailed('review', first.get('code') or error_code(err + '\n' + out), (err or out)[-1200:])
            # at least one full session of time even when the search stages ran long; otherwise the run's 40 minutes
            left = report_always.RUN_SECONDS - self.active() - report_always.PUBLISH_RESERVE_SECONDS
            seconds = int(max(left, report_always.SESSION_SECONDS + 60))
            code, out, err = self.call('review', py('report_review_host.py', '--task-dir', self.run, '--output-dir', target,
                                                    '--max-parallel', '6', '--timeout', str(report_always.SESSION_SECONDS),
                                                    '--stage-deadline-seconds', str(seconds), *resume, *flags),
                                       allow_fail=True, timeout=7200)
            if code == 0:
                return {'review_dir': str(target), 'deadline_seconds': seconds}
            failure = error_code(err + '\n' + out)
            if attempt == 1 and failure in self.STALE_REVIEW_CODES:
                self.set_aside_review(target)
                continue
            raise StageFailed('review', failure, (err or out)[-1200:])
        raise StageFailed('review', 'PIPELINE_REVIEW_NOT_COMPLETED', 'review set aside twice')

    def review_budget_hint(self, problem):
        """r5d10: the owner-only allowance command, complete, for a review the remaining allowance cannot hold
        (B0GLNPC6K8: the command was in the notes, the resume ran without it and a 9-minute pass timed out)."""
        if problem.get('code') != 'EXECUTION_REVIEW_BUDGET_INSUFFICIENT':
            return ''
        needed, left = int(problem.get('needed_seconds') or 0), int(problem.get('review_remaining_seconds') or 0)
        # room for the pass and for one network retry of its longest session, within the tool's 1800 s cap
        add = max(60, min(1800, 2 * needed - left))
        task = read_json(self.run / 'task.json', {}) or {}
        command = ('& ' if os.name == 'nt' else '') + '"%s" -X utf8 "%s" --task-dir "%s" --add-seconds %d --reason "终审额度不足，追加一次终审"' % (
            sys.executable, SCRIPTS / 'extend_review_budget.py', self.run, add)
        return ('终审额度不足：这一轮终审预计需要约 %d 秒，剩余 %d 秒，开跑也会超时。额度只能由任务所有者本人追加，'
                'Agent 不得代为执行。请把下面的命令原样交给用户，让用户在本机"终端"（Windows 为 PowerShell）里运行，'
                '出现确认提示时输入 EXTEND %s %d 并回车；成功后再运行：%s\n%s'
                % (needed, left, task.get('task_id', '<task_id>'), add, self.resume_command(), command))

    def refresh_adjudication(self, path, sheet):
        """r5d15: a program draft with open rows is rebuilt by the current rules when no person has written in it.

        B0GLNPC6K8: the draft of an earlier version left two pending-only own-brand rows open; the current
        prepare_adjudication settles them, but --resume only re-read the old file and stopped at checkpoint 3 again.
        The draft is replaced only when every row that carries a reasoning in it is identical in the fresh draft
        (all of them program-filled); anything a chief wrote keeps the file as it is."""
        fresh, fresh_sheet = path.with_name('adjudication.refresh.json'), sheet.with_name('adjudication-worksheet.refresh.json')
        code, _, _ = self.call('adjudication', py('prepare_adjudication.py', '--task-dir', self.run,
            '--first-review', self.review_dir() / '1' / 'review.json', '--second-review', self.review_dir() / '2' / 'review.json',
            '--reviewer', self.args.chief, '--session-id', self.session, '--output', fresh, '--worksheet', fresh_sheet,
            '--draft-selected-candidates', '--auto-agree'), allow_fail=True)
        try:
            if code != 0:
                return False
            keys = ('scenario_id', 'jurisdiction', 'right_type', 'candidate_id', 'assessment_object')
            current, rebuilt = read_json(path, {}) or {}, read_json(fresh, {}) or {}
            by_key = {tuple(row.get(k) for k in keys): row for row in rebuilt.get('decisions', [])}
            written = [row for row in current.get('decisions', []) if str(row.get('adjudication_reasoning') or '').strip()]
            if (len(current.get('decisions', [])) != len(rebuilt.get('decisions', []))
                    or any(by_key.get(tuple(row.get(k) for k in keys)) != row for row in written)
                    or len(self.open_decisions(fresh)[0]) >= len(self.open_decisions(path)[0])):
                return False
            os.replace(fresh, path)
            os.replace(fresh_sheet, sheet)
            self.log(stage='adjudication', note='adjudication_draft_refreshed')
            return True
        finally:
            for leftover in (fresh, fresh_sheet):
                if leftover.exists():
                    leftover.unlink()

    def open_decisions(self, path):
        adjudication = read_json(path, {}) or {}
        rows = [row for row in adjudication.get('decisions', []) if not str(row.get('adjudication_reasoning') or '').strip()]
        missing = [key for key in ('reviewer',) if not str(adjudication.get(key) or '').strip()]
        if not str((adjudication.get('review_context') or {}).get('session_id') or '').strip():
            missing.append('review_context.session_id')
        return rows, missing

    def s_adjudication(self):
        path, sheet = self.run / 'adjudication.json', self.run / 'adjudication-worksheet.json'
        if not path.is_file():
            if not self.args.chief:
                raise StageFailed('adjudication', 'PIPELINE_CHIEF_REQUIRED', 'pass --chief <主审姓名>')
            base = py('prepare_adjudication.py', '--task-dir', self.run, '--first-review', self.review_dir() / '1' / 'review.json',
                      '--second-review', self.review_dir() / '2' / 'review.json', '--reviewer', self.args.chief,
                      '--session-id', self.session, '--output', path, '--worksheet', sheet, '--draft-selected-candidates')
            code, _, err = self.call('adjudication', base + ['--auto-agree'], allow_fail=True)
            if code != 0 and 'auto-agree' in (err or ''):
                self.call('adjudication', base)          # an older prepare_adjudication without --auto-agree
            elif code != 0 and self.r6() and 'PREPARE_ADJUDICATION_REVIEW_STALE' in (err or '') \
                    and not getattr(self, '_stale_review_redone', False):
                # r6: the reviews were frozen on inputs that have changed since; review again instead of looping
                self._stale_review_redone = True
                self.set_aside_review(self.review_dir())
                self.s_review()
                return self.s_adjudication()
            elif code != 0:
                raise StageFailed('adjudication', error_code(err), err[-1200:])
        elif self.robust() and self.args.chief and self.open_decisions(path)[0]:
            self.refresh_adjudication(path, sheet)
        rows, missing = self.open_decisions(path)
        if rows or missing:
            target = self.run / CHECKPOINT_DIR / '3-adjudication.json'
            write_json(target, {'checkpoint': 3, 'adjudication': str(path), 'worksheet': str(sheet),
                                'missing_fields': missing,
                                'open_decisions': [{key: row.get(key) for key in ('scenario_id', 'jurisdiction', 'right_type',
                                                                                  'candidate_id', 'assessment_object', 'risk')}
                                                   for row in rows]})
            self.state['checkpoints']['3'] = 'waiting'
            raise Checkpoint(3, '检查点 3：主审需对 %d 个分歧单元填写 risk／assessment_status／adjudication_reasoning（%s，'
                             '对照 %s），然后运行：%s' % (len(rows), path, sheet, self.resume_command()), target)
        self.state['checkpoints']['3'] = 'released'
        return {'adjudication': str(path)}

    def s_publish(self):
        build, entry = self.run / 'report-build', self.run / 'report-entry'
        suffix = 1
        while build.exists() or entry.exists():
            suffix += 1
            build, entry = self.run / ('report-build-%d' % suffix), self.run / ('report-entry-%d' % suffix)
        _, out, _ = self.call('publish', py('publish_report.py', '--task-dir', self.run, '--first-review', self.review_dir() / '1' / 'review.json',
                                '--second-review', self.review_dir() / '2' / 'review.json',
                                '--adjudication', self.run / 'adjudication.json', '--mode', 'auto',
                                '--output-dir', build, '--deliver-to', entry, '--require-complete'), timeout=3600)
        found = re.search(r'completion_status:\s*([a-z_]+)', out or '')
        return {'report_entry': str(entry), 'report': str(entry / 'report.html'),
                **({'completion_status': found.group(1)} if found else {})}

    # ----- driver ---------------------------------------------------------------------------------------------
    def plan_lines(self):
        """Dry run: what each stage would do now, without running or writing anything."""
        task = read_json(self.run / 'task.json', None)
        rows = []
        for name in STAGES:
            status = self.state['stages'].get(name, {}).get('status', 'pending')
            reason = None
            if status == 'completed':
                reason = 'completed earlier (use --redo %s to repeat)' % name
            elif name == 'create' and task is not None:
                reason = 'task.json exists'
            elif name == 'capture' and task is not None and task.get('product', {}).get('raw_capture'):
                reason = 'product already captured'
            elif name == 'understanding' and (self.run / CHECKPOINT_DIR / '1-scope.json').is_file():
                reason = 'draft exists; checkpoint 1 ' + self.state['checkpoints'].get('1', 'not yet released')
            elif name == 'scope' and task is not None and task.get('product_scope', {}).get('scope_sha256'):
                reason = 'scope recorded'
            elif name == 'plan' and (self.run / 'search-plan.json').is_file():
                reason = 'plan exists (progress registration still runs)'
            elif name == 'review' and (self.review_dir() / '2' / 'review.json').is_file():
                reason = 'both reviews retained'
            elif name == 'adjudication' and (self.run / 'adjudication.json').is_file():
                reason = 'adjudication exists; open decisions are checked'
            elif name == 'core':
                missing = [s for s in ('core_dossier.py', 'comparison_host.py', 'prereview_screen.py')
                           if not (SCRIPTS / s).is_file()]
                reason = ('not installed: ' + ', '.join(missing)) if missing else None
            rows.append({'stage': name, 'status': status, 'skip_reason': reason, 'commands': COMMANDS[name]})
        return rows

    def network_check(self):
        """r5d4: name a local fake-IP proxy once per invocation (DNS only); public downloads follow owner decision F3."""
        if not self.run.is_dir() or not self.robust():
            return
        try:
            from network_diagnostic import diagnose
            result = diagnose(timeout=3.0)
        except Exception as exc:                 # diagnostics never stop a run
            result = {'status': 'not_checked', 'error': type(exc).__name__}
        write_json(self.run / 'network-check.json', {**result, 'checked_at': now(),
            'public_download_rule': ('fake-IP block 198.18.0.0/15 allowed for public files (owner decision F3)'
                                     if result.get('status') == 'fake_ip_detected' else 'public addresses only')})
        if result.get('status') not in ('ok', 'not_checked'):
            self.log(stage='pipeline', note='network_check:' + str(result.get('status')))
        try:
            from network_diagnostic import notice
            text = notice(result)
        except Exception:
            text = ''
        if text:
            with self.lock:
                self.state['network_notice'] = text

    def execute(self):
        functions = {name: getattr(self, 's_' + name) for name in STAGES}
        self.recorded_key_slot()
        for name in STAGES:
            if name == 'auth' and self.args.skip_auth:
                continue
            if name == 'sources':
                self.network_check()
            self.stage(name, functions[name])
        return self.state['stages'].get('publish', {}).get('outputs', {})


COMMANDS = {
    'auth': ['auth_gate.py'], 'create': ['create_task.py --url|--product-input --jurisdictions --output-dir RUN'],
    'credentials': ['preflight.py --phase credentials'],
    'capture': ['cdp-cli.mjs doctor', 'cdp-cli.mjs capture-amazon', 'record_browser_product.py | record_user_product.py'],
    'understanding': ['product_understanding_host.py --output-dir RUN/checkpoints', '[checkpoint 1]'],
    'scope': ['record_product_scope.py', 'record_product_analysis.py', 'preflight.py --phase evidence',
              'product_change.py --rebase-progress'],
    'plan': ['generate_search_plan.py', 'mechanical_ledger.py --steps progress'],
    'marking': ['compared patent candidates -> record_product_analysis.py --revise (patent_claim_followup)',
                'else PATENT_MARKING_RESOLUTION_REQUIRED action card -> [checkpoint 1b]'],
    'sources': ['(rounds <= %d) mechanical_ledger.py, advance_work.py --execute-sources, discovery_review_host.py, '
                'merge_candidates.py, triage_defaults.py, (recall-v1 tasks) recall_screen.py --mode text || --mode image, '
                'text_triage_host.py || visual_triage_host.py, '
                'mechanical_ledger.py, auto_refine.py, generate_search_plan.py --expand' % MAX_ROUNDS],
    'core': ['core_dossier.py', 'comparison_host.py', 'mechanical_ledger.py', 'advance_work.py --execute-sources',
             '(r5d4 tasks) prereview_screen.py --status, core_dossier.py, comparison_host.py || prereview_screen.py '
             '--claims (|| design_screen.py --check, r5d17 tasks), prereview_screen.py --commit (, design_screen.py '
             '--commit); ready discovery rows are flushed before the stage ends'],
    'readiness': ['review_readiness.readiness -> (r5d4 tasks: one program catch-up core round) -> [checkpoint 2]'],
    'review': ['report_review_host.py --preflight', 'report_review_host.py --max-parallel 6'],
    'adjudication': ['prepare_adjudication.py --draft-selected-candidates --auto-agree -> [checkpoint 3]'],
    'publish': ['publish_report.py --deliver-to RUN/report-entry --require-complete'],
}


def parser():
    value = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    value.add_argument('--task-dir', type=Path, required=True, help='Run directory (new and empty for a new task)')
    value.add_argument('--url', help='Amazon product URL (new task)')
    value.add_argument('--product-input', type=Path, help='product-input-v2 JSON (new task, user materials)')
    value.add_argument('--jurisdictions', default=None,
                       help='Target countries; default: the Amazon link\'s own marketplace (US for user materials)')
    value.add_argument('--guard-session-id', help='Actual Codex session id ($CODEX_THREAD_ID)')
    value.add_argument('--chief', help='Chief reviewer name signing the adjudication')
    value.add_argument('--resume', action='store_true', help='Continue after a checkpoint or a fixed failure')
    value.add_argument('--trust-host', action='store_true', help='Do not stop at checkpoint 1 (scope draft)')
    value.add_argument('--skip-marking', action='store_true', help='Continue without resolving the patent marking (recorded)')
    value.add_argument('--dry-run', action='store_true', help='Print the stage plan; run and write nothing')
    value.add_argument('--redo', action='append', choices=STAGES, help='Repeat a completed stage (repeatable)')
    value.add_argument('--all-sources', action='store_true',
                       help='Enable Serper, SerpApi and Signa discovery for the new task (each needs its API key)')
    value.add_argument('--enable-serper-free', action='store_true')
    value.add_argument('--enable-serpapi-free', action='store_true')
    value.add_argument('--enable-signa-free', action='store_true')
    value.add_argument('--use-serper-existing-balance', action='store_true',
                       help='Only with the owner\'s authorisation: use existing Serper credits; never purchase or recharge')
    value.add_argument('--allow-limited-sources', action='store_true',
                       help='Run even when Serper and SerpApi are both disabled (EPO only); the report will be thin')
    value.add_argument('--allow-legacy', action='store_true',
                       help='Continue a task created before best-estimate-risk-v2 (only when the user explicitly asks)')
    value.add_argument('--skip-auth', action='store_true', help=argparse.SUPPRESS)
    value.add_argument('--understanding-driver', choices=('native', 'program'), default='native')
    value.add_argument('--codex-binary')
    value.add_argument('--isolation', default='auto')
    return value


BUILD_STAMP = 'lc-ipr-build.txt'


def clear_stale_bytecode(root=ROOT):
    """r5d17: drop the skill's compiled caches once per installed release, before any skill module is imported.

    Run B0HF19R4YF: r5d16 changed one constant in api_first_planning.py without changing the file's size, and every
    file of the release zip carried the same date as r5d15's; Python found its r5d15 cache "current" (it compares
    the source's size and modification time), ran the old limit and the plan stage failed with
    API_FIRST_RETRIEVAL_POLICY_INVALID. The release is named by the hash of its DISTRIBUTION-MANIFEST.json."""
    root = Path(root)
    try:
        stamp = hashlib.sha256((root / 'DISTRIBUTION-MANIFEST.json').read_bytes()).hexdigest()
    except OSError:
        return False
    marker = root / 'scripts' / '__pycache__' / BUILD_STAMP
    try:
        if marker.read_text(encoding='utf-8').strip() == stamp:
            return False
    except OSError:
        pass
    for folder in ('scripts', 'tests'):
        cache = root / folder / '__pycache__'
        for compiled in (cache.glob('*.pyc') if cache.is_dir() else []):
            try:
                compiled.unlink()
            except OSError:          # in use (Windows) or read-only: Python recompiles a source it cannot match
                pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(stamp + '\n', encoding='utf-8')
    except OSError:
        pass
    return True


def main(argv=None):
    clear_stale_bytecode()
    args = parser().parse_args(argv)
    pipeline = Pipeline(args)
    legacy = None
    if (pipeline.run / 'task.json').is_file():
        from legacy_task import notice as legacy_notice
        legacy = legacy_notice(read_json(pipeline.run / 'task.json', None))
    if args.dry_run:
        print(json.dumps({'task_dir': str(pipeline.run), **({'legacy_task': legacy} if legacy else {}),
                          'stages': pipeline.plan_lines()}, ensure_ascii=False, indent=2))
        return EXIT_OK
    if legacy and not args.allow_legacy:
        print(json.dumps({'status': 'failed', 'stage': 'create', 'error_code': legacy['code'],
                          'detail': legacy['message'], 'recommended_command': legacy['recommended_command'],
                          'resume': 'only if the user explicitly asks to continue this old task: add --allow-legacy'},
                         ensure_ascii=False))
        return EXIT_FAILED
    if pipeline.run.exists() and (pipeline.run / 'task.json').is_file() and not args.resume and pipeline.state['stages']:
        print('PIPELINE_RESUME_REQUIRED: this run already has pipeline state; add --resume', file=sys.stderr)
        return EXIT_FAILED
    try:
        # r5d4: the computer must not sleep while sessions run (B0FSJBDTF2: four sessions lost to a sleeping Mac)
        from keep_awake import KeepAwake
        with KeepAwake() as awake:
            if awake.mode != 'none':
                pipeline.log(stage='pipeline', note='keep_awake:' + awake.mode)
            outputs = pipeline.execute()
    except Checkpoint as point:
        pipeline.save()
        pipeline.log(stage='checkpoint', number=point.number, path=str(point.path))
        print(json.dumps({'status': 'checkpoint', 'checkpoint': point.number, 'file': str(point.path),
                          'message': point.message, 'resume': pipeline.resume_command(), **pipeline.sleep_notice(),
                          **pipeline.search_notice()},
                         ensure_ascii=False))
        return EXIT_CHECKPOINT
    except StageFailed as failure:
        pipeline.save()
        print(json.dumps({'status': 'failed', 'stage': failure.stage, 'error_code': failure.code,
                          'detail': failure.detail[-800:], 'resume': pipeline.resume_command(),
                          **({'owner_action': failure.owner_action} if getattr(failure, 'owner_action', '') else {}),
                          **pipeline.sleep_notice(), **pipeline.search_notice()}, ensure_ascii=False))
        return EXIT_FAILED
    # r5d17 (run B0HF19R4YF): the Agent built and checked the report a second time (output-build, about 3 minutes)
    # because nothing here said that the delivery transaction had already run the completion check.
    print(json.dumps({'status': 'delivered', **outputs, 'seconds': round(sum(
        row.get('seconds') or 0 for row in pipeline.state['stages'].values()), 1), **pipeline.sleep_notice(),
        **pipeline.search_notice(),
        'next': ('报告已发布，交付事务内已完成真实入口检查与完成检查。直接读取 report 与 report-data.json 向用户汇报；'
                 '不要再运行 publish_report.py 或 completion_check.py，也不要另建输出目录。')},
        ensure_ascii=False))
    return EXIT_OK


if __name__ == '__main__':
    sys.path.insert(0, str(SCRIPTS))
    raise SystemExit(main())
