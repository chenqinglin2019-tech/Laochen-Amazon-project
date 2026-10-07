"""Keep one front crawl moving, with bounded browser calls and safe recovery."""
from __future__ import annotations

import argparse
import hashlib
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from run_outcome import CrawlStop, EXIT_CONFIG_ERROR, EXIT_LOCK_HELD, EXIT_NEEDS_HUMAN, EXIT_RETRY_LATER
from runtime_watchdog import write_json
from safety_control import LocalSafetyController, SafetyPausedError, default_safety_root

ROOT = Path(__file__).resolve().parent.parent


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def command_expired(value, attempt_id, now=None):
    return bool(value.get("attempt_id") == attempt_id and value.get("active") is True
                and (time.monotonic() if now is None else now) > float(value.get("deadline_monotonic") or float("inf")))


def phase_budget(heartbeat, runtime, now=None):
    now = now or dt.datetime.now()
    if heartbeat.get("until"):
        return max(0, (dt.datetime.fromisoformat(heartbeat["until"]) - now).total_seconds()) + 30
    phase = heartbeat.get("phase")
    if phase in {"manual_wait", "waiting", "retry_wait"}:
        return max(runtime.manual_pause_timeout, 1200) + 30
    if phase == "plugin_wait":
        return 200 if runtime.operation_mode == "unattended" else 90
    return max(300, runtime.page_timeout + 30)


def bounded_recovery(config_path, action):
    """Recovery owns another process, so even Playwright cleanup can be stopped."""
    command = [sys.executable, str(ROOT / "scripts/browser_recovery.py"), "--config", str(config_path), "--action", action]
    environment = {k: v for k, v in os.environ.items() if k not in {"LC_CRAWL_WATCHDOG_DIR", "LC_CRAWL_ATTEMPT_ID"}}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, env=environment)
    try:
        stdout, _ = process.communicate(timeout=30 if action == "probe" else 120)
        value = json.loads(stdout.strip().splitlines()[-1])
        return value if isinstance(value, dict) else {"status": "unknown", "reason": "invalid_recovery_result"}
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        stop_child(process)
        return {"status": "unknown", "reason": "recovery_deadline_or_invalid_result"}


def committed_pages(job):
    state = read_json(job / "state.json")
    total = 0
    for key in state.get("completed_page_order") or state.get("completed_pages") or []:
        path = job / "page_results" / (hashlib.sha256(str(key).encode()).hexdigest() + ".json")
        payload = read_json(path)
        if payload and payload.get("plugin_status") != "skipped":
            total += 1
    return total


def stop_child(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def repair_exports(config):
    """Only after the child and all job/safety locks have been released."""
    import amazon_front_crawler as front
    from amazon_category_rank_crawler import JobRunLock, write_quality_report
    runtime = front.build_front_runtime_config(config, False, False)
    if runtime.mode == "bsr_category":
        raise RuntimeError("bsr_repair_requires_normal_resume")
    job = runtime.outputs_root / runtime.job_id
    if not (job / "state.json").exists():
        return
    lock = JobRunLock(job / ".run.lock")
    lock.acquire()
    try:
        state = front.FrontStateStore(job / "state.json", runtime, front.build_initial_queue(runtime))
        state.load_or_create()
        front.materialize_front_records(state, job / "records.jsonl")
        records = front.read_jsonl(job / "records.jsonl")
        write_quality_report(job / "records.jsonl", job / "quality_report.json", front.build_front_dedup_rows(records))
        front.write_front_workbook(job / "records.jsonl", job / "failures.jsonl", job / "dedup_total.xlsx")
        quality = read_json(job / "quality_report.json")
        quality["export_succeeded"] = True
        write_json(job / "quality_report.json", quality)
    finally:
        lock.release()


def child_command(config_path, mode="", review=False):
    if os.name == "nt":
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "lc-amazon-data-crawl.ps1")]
    else:
        command = ["bash", str(ROOT / "lc-amazon-data-crawl.sh")]
    command += ["amazon-front-run", "--config", str(config_path)]
    if mode:
        command += ["--operation-mode", mode]
    if review:
        command += ["--resume-after-review"]
    return command


def supervise(config_path, mode="", review=False):
    from start_cdp_browser import load_config
    config = load_config(config_path)
    import amazon_front_crawler as front
    runtime = front.build_front_runtime_config(config, False, review)
    if mode:
        config["operation_mode"] = mode
        runtime = front.build_front_runtime_config(config, False, review)
    if runtime.mode == "bsr_category":
        raise ValueError("amazon-front-supervise 当前支持店铺与关键词；类目仍使用 amazon-front-run。")
    job = runtime.outputs_root / runtime.job_id
    job.mkdir(parents=True, exist_ok=True)
    controller = LocalSafetyController(default_safety_root() / "supervisor")
    controller.job_label = runtime.job_id
    controller.acquire()
    session = uuid.uuid4().hex
    status = {"session_id": session, "pid": os.getpid(), "job_id": runtime.job_id,
              "phase": "starting", "browser_restarts_without_commit": 0}
    process = None
    power_assertion = None
    last_count = committed_pages(job)
    local_recoveries = 0
    def event(action, **values):
        status.update(values, phase=action, updated_at=dt.datetime.now().isoformat(timespec="seconds"))
        write_json(job / "supervisor.json", status)
        with (job / "supervisor_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"session_id": session, "at": status["updated_at"], "action": action, **values}, ensure_ascii=False) + "\n")
    def wait_for_resume(deadline, reason="retry_later"):
        event("retry_wait", resume_at=deadline.isoformat(timespec="seconds"), reason=reason)
        while dt.datetime.now() < deadline:
            time.sleep(min(2, (deadline - dt.datetime.now()).total_seconds()))
    try:
        from desktop_runtime import start_foreground_power_assertion
        try:
            power_assertion = start_foreground_power_assertion(runtime)
        except OSError:
            event("needs_human", reason="foreground_power_assertion_unavailable", exit_code=EXIT_NEEDS_HUMAN)
            return EXIT_NEEDS_HUMAN
        if power_assertion is not None:
            event("foreground_awake", power_assertion_pid=power_assertion.pid)
        # A fresh supervisor still honors the preceding attempt's cooldown;
        # that summary is a safety deadline, never evidence of this session's success.
        saved_resume = read_json(job / "run_summary.json").get("resume_at")
        if saved_resume:
            saved_deadline = dt.datetime.fromisoformat(saved_resume)
            if dt.datetime.now() < saved_deadline:
                wait_for_resume(saved_deadline, "persisted_cooldown")
        while True:
            attempt = uuid.uuid4().hex
            environment = {**os.environ, "LC_CRAWL_WATCHDOG_DIR": str(job), "LC_CRAWL_ATTEMPT_ID": attempt}
            kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            process = subprocess.Popen(child_command(config_path, mode, review), cwd=ROOT, env=environment, **kwargs)
            review = False  # The caller's manual review authorizes one attempt.
            event("running", attempt_id=attempt, child_pid=process.pid)
            timed_out = None
            heartbeat_seen = False
            started = time.monotonic()
            phase_key = None
            phase_deadline = started + 180
            observed_heartbeat = None
            heartbeat_deadline = started + 180
            while process.poll() is None:
                heartbeat = read_json(job / "run_heartbeat.json")
                heartbeat_seen |= heartbeat.get("attempt_id") == attempt
                if heartbeat.get("attempt_id") == attempt:
                    current_phase = (heartbeat.get("phase"), heartbeat.get("until"))
                    if current_phase != phase_key:
                        phase_key = current_phase
                        phase_deadline = time.monotonic() + phase_budget(heartbeat, runtime)
                        event("running", stage=heartbeat.get("phase"), phase_deadline_monotonic=phase_deadline)
                    if heartbeat.get("updated_at") != observed_heartbeat:
                        observed_heartbeat = heartbeat.get("updated_at")
                        heartbeat_deadline = time.monotonic() + max(300, phase_budget(heartbeat, runtime))
                watchdog = read_json(job / "runtime_watchdog.json")
                if command_expired(watchdog, attempt):
                    timed_out = watchdog
                    event("command_timeout", operation=watchdog.get("operation"))
                    stop_child(process)
                    break
                if not heartbeat_seen and time.monotonic() - started > 180:
                    timed_out = {"operation": "startup"}
                    event("startup_timeout")
                    stop_child(process)
                    break
                if heartbeat_seen and time.monotonic() > min(phase_deadline, heartbeat_deadline):
                    timed_out = {"operation": "phase:" + str(heartbeat.get("phase"))}
                    event("phase_timeout", stage=heartbeat.get("phase"))
                    stop_child(process)
                    break
                time.sleep(0.5)
            code = process.wait()
            event("child_exited", exit_code=code, child_exit_code=code, heartbeat_seen=heartbeat_seen)
            completion = read_json(job / "run_summary.json")
            final_heartbeat = read_json(job / "run_heartbeat.json")
            if code in {0, 10} and (completion.get("attempt_id") != attempt or
                                   final_heartbeat.get("attempt_id") != attempt or final_heartbeat.get("phase") != "exited"):
                event("needs_human", reason="child_completion_unconfirmed", exit_code=EXIT_NEEDS_HUMAN)
                return EXIT_NEEDS_HUMAN
            count = committed_pages(job)
            if count > last_count:
                status["browser_restarts_without_commit"] = 0
                local_recoveries = 0
                last_count = count
            issue = read_json(job / "runtime_issue.json")
            local_issue = issue.get("attempt_id") == attempt
            if timed_out or local_issue:
                if os.name == "nt":
                    event("needs_human", reason="native_recovery_not_supported", exit_code=EXIT_NEEDS_HUMAN)
                    return EXIT_NEEDS_HUMAN
                safety = LocalSafetyController()
                try:
                    safety.acquire()
                except SafetyPausedError:
                    event("needs_human", reason="another_crawl_owns_browser", exit_code=EXIT_LOCK_HELD)
                    return EXIT_LOCK_HELD
                try:
                    if safety._load_pause():
                        event("risk_pause", exit_code=21)
                        return 21
                    repair_exports(config)
                    from desktop_runtime import wait_for_desktop, DesktopUnavailable
                    try:
                        event("manual_wait", reason="desktop_check")
                        safety.status_path = job / "run_heartbeat.json"
                        wait_for_desktop(SimpleNamespace(manual_pause_timeout=runtime.manual_pause_timeout, safety=safety))
                    except DesktopUnavailable as exc:
                        event("needs_human", reason=exc.reason, exit_code=EXIT_NEEDS_HUMAN)
                        return EXIT_NEEDS_HUMAN
                    probe = bounded_recovery(config_path, "probe")
                    event("browser_probe", probe=probe)
                    if probe["status"] == "browser_unresponsive":
                        if status["browser_restarts_without_commit"] >= 2:
                            event("needs_human", reason="browser_recovery_limit", exit_code=EXIT_NEEDS_HUMAN)
                            return EXIT_NEEDS_HUMAN
                        recovery = bounded_recovery(config_path, "restart")
                        status["browser_restarts_without_commit"] += 1
                        event("browser_restarted", recovery=recovery)
                        if recovery.get("status") == "unknown" or bounded_recovery(config_path, "probe")["status"] != "healthy":
                            event("needs_human", reason="browser_restart_unconfirmed", exit_code=EXIT_NEEDS_HUMAN)
                            return EXIT_NEEDS_HUMAN
                    elif probe["status"] != "healthy":
                        event("needs_human", reason=probe.get("reason"), exit_code=EXIT_NEEDS_HUMAN)
                        return EXIT_NEEDS_HUMAN
                    else:
                        local_recoveries += 1
                        if local_recoveries > 2:
                            event("needs_human", reason="page_recovery_limit", exit_code=EXIT_NEEDS_HUMAN)
                            return EXIT_NEEDS_HUMAN
                    # Next child cleans only stale owned tabs and recreates its worker.
                    code = EXIT_RETRY_LATER
                finally:
                    safety.release()
            if code == EXIT_LOCK_HELD:
                event("waiting_for_lock")
                time.sleep(5)
                continue
            if code != EXIT_RETRY_LATER:
                event("finished", exit_code=code)
                return code
            summary = read_json(job / "run_summary.json")
            resume = summary.get("resume_at") if summary.get("attempt_id") == attempt else None
            deadline = dt.datetime.now() + dt.timedelta(minutes=10) if timed_out else dt.datetime.now()
            if resume:
                deadline = max(deadline, dt.datetime.fromisoformat(resume))
            wait_for_resume(deadline)
    except KeyboardInterrupt:
        if process:
            stop_child(process)
        event("interrupted", exit_code=EXIT_RETRY_LATER)
        return EXIT_RETRY_LATER
    finally:
        try:
            if process and process.poll() is None:
                stop_child(process)
        finally:
            try:
                from desktop_runtime import stop_foreground_power_assertion
                stop_foreground_power_assertion(power_assertion)
            finally:
                controller.release()


def main():
    from amazon_category_rank_crawler import UserFacingError
    from start_cdp_browser import BrowserStartError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--operation-mode", choices=("supervised", "unattended"), default="")
    parser.add_argument("--resume-after-review", action="store_true")
    args = parser.parse_args()
    path = Path(args.config).expanduser()
    path = path if path.is_absolute() else ROOT / path
    try:
        return supervise(path, args.operation_mode, args.resume_after_review)
    except SafetyPausedError:
        return EXIT_LOCK_HELD
    except CrawlStop as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except (ValueError, UserFacingError, BrowserStartError) as exc:
        print(f"监督配置错误：{exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except Exception as exc:
        print(f"监督运行停止：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
