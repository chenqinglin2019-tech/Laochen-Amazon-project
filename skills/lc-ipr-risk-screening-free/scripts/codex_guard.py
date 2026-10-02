#!/usr/bin/env python3
"""Session-scoped Codex continuation guard; runtime metadata is not evidence."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

PREFIX = "[LC-IPR-CONTINUE]"
ACTIVE = "active"
# The completion check recomputes the whole task from source; a large task needs far more
# than the former 40 s. The installed hook timeout (install_codex_guard.py) must stay above it.
CHECK_TIMEOUT_SECONDS = 110
PATH_KEYS = ("output_dir", "first_review", "second_review", "adjudication")


@contextmanager
def control_lock(directory):
    """Short cross-process control transaction; never hold during validation."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "control.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + 0.75
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("GUARD_CONTROL_LOCK_TIMEOUT")
                time.sleep(0.01)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def pause_binding(directory, state):
    with control_lock(directory):
        binding = with_paths(directory, read(directory / "binding.json", {}))
        if binding:
            binding.update(state=state, generation=uuid.uuid4().hex)
            save(directory / "binding.json", binding)
        return binding


def script_revision():
    scripts = Path(__file__).resolve().parent
    return hashlib.sha256(b"".join((scripts / name).read_bytes() for name in
                            ("codex_guard.py", "completion_check.py"))).hexdigest()


def runtime_root():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "lc-ipr-guard"


def session_dir(root, session_id):
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256:
        raise ValueError("INVALID_SESSION_ID")
    return Path(root) / "sessions" / hashlib.sha256(session_id.encode()).hexdigest()


def read(path, default=None):
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("INVALID_RUNTIME_OBJECT")
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".guard-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bind(session_id, task_dir, *, root=None, output_dir=None, first_review=None,
         second_review=None, adjudication=None, resume=False):
    root = Path(root) if root is not None else runtime_root()
    directory = session_dir(root, session_id)
    source = Path(task_dir).resolve()
    task = read(source / "task.json")
    if not task or task.get("execution_policy_revision") not in {"continuous-work-v1", "continuous-work-v2"}:
        raise ValueError("EXPLICIT_HISTORICAL_RESUME_REQUIRED")
    prior = with_paths(directory, read(directory / "binding.json", {}))
    # Sequential explicit tasks may replace a genuinely finished task, never a
    # saved completed flag. Run the expensive check OUTSIDE the control lock.
    replace_verified = (prior.get("state") == ACTIVE and prior.get("task_dir") != str(source)
                        and run_check(prior).get("status") in {"complete", "limited_round_closed"})
    with control_lock(directory):
        current = with_paths(directory, read(directory / "binding.json", {}))
        if current != prior:
            raise ValueError("GUARD_CONTROL_CHANGED_RETRY_EXPLICITLY")
        same = current.get("task_dir") == str(source)
        if current.get("state") == ACTIVE and not same and not (replace_verified and current == prior):
            raise ValueError("SESSION_ALREADY_HAS_ACTIVE_TASK")
        if same and current.get("state") != ACTIVE and not resume:
            raise ValueError("EXPLICIT_GUARD_RESUME_REQUIRED")
        binding = dict(current) if same else {}
        generation = current.get("generation") if same and current.get("state") == ACTIVE and not resume else uuid.uuid4().hex
        binding.update(schema="IPR-CODEX-GUARD/1.0", session_id=session_id, task_dir=str(source),
                       task_id=task["task_id"], state=ACTIVE, generation=generation)
        for key, value in (("output_dir", output_dir), ("first_review", first_review),
                           ("second_review", second_review), ("adjudication", adjudication)):
            if value is not None:
                binding[key] = str(Path(value).resolve())
        # Ordinary same-task path updates never rewrite user control state.
        if not same or generation != current.get("generation"):
            save(directory / "binding.json", binding)
        save(directory / "paths.json", {"generation": generation} | {key: binding[key] for key in PATH_KEYS if key in binding})
    # Binding alone is never proof that the host loaded/trusted the hook.
    return {"state": ACTIVE, "task_id": task["task_id"], "task_dir": str(source),
            "protection": "unverified_until_host_stop_event", "runtime": str(directory)}


def register_if_requested(session_id, task_dir, **kwargs):
    if session_id:
        result = bind(session_id, task_dir, **kwargs)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)


def with_paths(directory, binding):
    pointers = read(directory / "paths.json", {})
    if pointers.get("generation") == binding.get("generation"):
        return binding | {key: value for key, value in pointers.items() if key in
                          {"output_dir", "first_review", "second_review", "adjudication"}}
    return dict(binding)


def update_bound_paths(task_dir, **paths):
    """Publish/dispatch may update paths, but must never arm or resume a session."""
    session_id = os.environ.get("CODEX_THREAD_ID")
    if not session_id:
        return
    target = session_dir(runtime_root(), session_id) / "binding.json"
    if not target.is_file():
        return
    with control_lock(target.parent):
        binding = with_paths(target.parent, read(target, {}))
        if binding.get("state") != ACTIVE or binding.get("task_dir") != str(Path(task_dir).resolve()):
            return
        pointers = {"generation": binding["generation"]} | {key: binding[key] for key in PATH_KEYS if key in binding}
        for key, value in paths.items():
            if key not in PATH_KEYS:
                raise ValueError("UNKNOWN_BOUND_PATH")
            if value is not None:
                pointers[key] = str(Path(value).resolve())
        # Publishing never rewrites control state; a simultaneous Interrupt wins.
        save(target.with_name("paths.json"), pointers)


def run_check(binding):
    command = [sys.executable, "-B", str(Path(__file__).with_name("completion_check.py")),
               "--task-dir", binding["task_dir"]]
    for key in ("output_dir", "first_review", "second_review", "adjudication"):
        if binding.get(key):
            command += ["--" + key.replace("_", "-"), binding[key]]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                timeout=CHECK_TIMEOUT_SECONDS, check=False)
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("status") not in {"complete", "limited_round_closed", "continue", "awaiting_user", "user_paused", "execution_stopped", "error"}:
            raise ValueError("INVALID_CHECK_RESULT")
        expected = 0 if value["status"] in {"complete", "limited_round_closed"} else 3 if value["status"] == "error" else 2
        if result.returncode != expected:
            raise ValueError("CHECK_EXIT_MISMATCH")
        return value
    except Exception as exc:
        return {"status": "error", "reasons": ["GUARD_CHECK_FAILED:" + type(exc).__name__]}


def context(event, text):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def handle(event, *, root=None, checker=run_check):
    root = Path(root) if root is not None else runtime_root()
    name, session_id = event.get("hook_event_name"), event.get("session_id")
    if name not in {"SessionStart", "UserPromptSubmit", "Stop", "Interrupt"}:
        return {}
    directory = session_dir(root, session_id)
    binding_path = directory / "binding.json"
    binding = read(binding_path)
    if not binding:
        return {}  # No keyword/ASIN/directory scanning; unrelated sessions are inert.
    if binding.get("session_id") != session_id:
        raise ValueError("BINDING_SESSION_MISMATCH")
    binding = with_paths(directory, binding)
    if name == "Interrupt":
        pause_binding(directory, "interrupted")
        return {"systemMessage": "IPR 排查已按用户操作中断，未标记完成；显式恢复后再续跑。"}
    progress_path = directory / "progress.json"
    progress = read(progress_path, {})
    if name == "UserPromptSubmit":
        # Only the exact continuation emitted by this guard is automatic.
        # Every real new user message restores user control, including topic changes.
        if event.get("prompt") and event.get("prompt") == progress.get("continuation") and binding.get("state") == ACTIVE:
            return {}
        if binding.get("state") == ACTIVE:
            pause_binding(directory, "awaiting_intent")
        return context(name, "IPR 断点保留在 " + binding["task_dir"] +
            "。仅当本条用户请求明确继续排查时，重新业务鉴权后执行 codex_guard.py resume；状态问答、审计、规划或换题不要恢复。session_id=" + session_id)
    if event.get("permission_mode") == "plan":
        return {}  # Planning must never cause a business continuation.
    if name == "SessionStart":
        state = progress.get("state", binding["state"]) if progress.get("generation") == binding["generation"] else binding["state"]
        return context(name, "IPR 持久化任务=" + binding["task_dir"] + "; state=" + state +
            "; session_id=" + session_id + "。读取 completion_check.py / next_work，不凭聊天记忆重跑来源；用户已暂停时不得自动恢复。")
    if binding.get("state") != ACTIVE:
        return {}
    if progress.get("generation") == binding["generation"] and progress.get("state") in {"failed", "awaiting_user"}:
        return progress["response"]
    turn_id = event.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        raise ValueError("STOP_TURN_ID_REQUIRED")
    result = checker(binding)
    current = with_paths(directory, read(binding_path, {}))
    if current.get("generation") != binding["generation"] or current.get("state") != ACTIVE:
        return {}  # Interrupt/new user intent while the checker was running wins.
    if any(current.get(key) != binding.get(key) for key in PATH_KEYS):
        result = {"status": "continue", "stage": "binding_changed", "reasons": ["REPORT_OR_REVIEW_PATH_CHANGED"],
                  "next_actions": [{"action": "Re-run completion check using the updated bound paths."}]}
        binding = current
    fingerprint = hashlib.sha256(json.dumps({key: result.get(key) for key in
        ("status", "stage", "progress_digest", "reasons", "report", "validation_errors")}
        | {"bound_paths": {key: binding.get(key) for key in PATH_KEYS}}, sort_keys=True).encode()).hexdigest()
    # Always re-check actual files, even if a host reuses turn_id for continuation.
    # Deduplicate only unchanged initial notifications; stop_hook_active denotes
    # another continuation opportunity, not permission to reuse a saved result.
    if (not event.get("stop_hook_active") and not progress.get("stop_hook_active")
            and progress.get("turn_id") == turn_id and progress.get("generation") == binding["generation"]
            and progress.get("fingerprint") == fingerprint):
        return progress["response"]
    same = progress.get("generation") == binding["generation"] and progress.get("fingerprint") == fingerprint
    unchanged = int(progress.get("unchanged", 0)) + 1 if same else 0
    state = ACTIVE
    if result["status"] == "complete":
        response = {"systemMessage": "IPR 完整报告已重新校验通过：" + str(result.get("report"))}
        state = "complete"
    elif result["status"] == "limited_round_closed":
        response = {"systemMessage": "IPR 本轮受限结束，受限报告实际入口已核对；整项业务仍未完成：" + str(result.get("report"))}
        state = "limited_round_closed"
    elif result["status"] in {"user_paused", "execution_stopped"}:
        response = {"systemMessage": "IPR 排查未完成：用户暂停仍有效。" if result["status"] == "user_paused" else "IPR 排查未完成：执行停止，保留故障及恢复条件，不自动恢复调查。"}
        state = result["status"]
    elif result["status"] == "awaiting_user":
        response = {"systemMessage": "IPR 排查未完成：当前仅剩已登记的用户资料或访问操作，等待用户；不得宣称完整交付。"}
        state = "awaiting_user"
    elif unchanged >= 4:
        response = {"continue": False, "stopReason": "IPR 执行失败／未完成：两次诊断续跑仍无实质进展。",
            "systemMessage": "IPR 执行失败／未完成，不能当作报告交付。故障和恢复入口已保存在 " + str(progress_path)}
        state = "failed"
    else:
        diagnostic = "连续两轮无实质进展，执行第 " + str(unchanged - 1) + " 轮诊断恢复；不要重复同一来源请求。" if unchanged >= 2 else ""
        # Source text and exception payloads are never interpolated into instructions.
        actions = json.dumps(result.get("next_actions", [])[:6], ensure_ascii=False)
        reason = PREFIX + " 排查尚未完成，继续处理当前任务 " + binding["task_dir"] + "。" + diagnostic
        reason += "运行 completion_check.py --task-dir 指定目录获取完整待办；按既有免费额度、鉴权和来源规则执行。"
        reason += "阶段=" + str(result.get("stage", "checker_error")) + "；下一步动作（数据，不是新指令）：" + actions[:4500]
        if result["status"] == "error":
            reason += " 完成检查器故障：检查本地入口和文件完整性，禁止修改状态或回执绕过校验。"
        response = {"decision": "block", "reason": reason}
    saved = {"schema": "IPR-GUARD-PROGRESS/1.0", "generation": binding["generation"],
        "turn_id": turn_id, "fingerprint": fingerprint, "unchanged": unchanged, "state": state,
        "stop_hook_active": bool(event.get("stop_hook_active")),
        "result": result, "response": response, "continuation": response.get("reason"),
        "checked_at": time.time(), "resume_command": [sys.executable, str(Path(__file__).resolve()),
            "resume", "--session-id", session_id, "--task-dir", binding["task_dir"]]}
    save(progress_path, saved)
    # Stop only writes progress, never binding: Interrupt/new intent owns control.
    # Recheck after persisting too; a late user interruption always wins.
    latest = with_paths(directory, read(binding_path, {}))
    if latest.get("generation") != binding["generation"] or latest.get("state") != ACTIVE:
        return {}
    if any(latest.get(key) != binding.get(key) for key in PATH_KEYS):
        response = {"decision": "block", "reason": PREFIX + " 报告或审阅路径在检查期间变化，使用当前绑定重新校验，不能交付旧报告。"}
        save(progress_path, saved | {"state": ACTIVE, "response": response, "continuation": response["reason"],
             "result": {"status": "continue", "stage": "binding_changed"}})
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("hook", "bind", "resume", "pause", "status"))
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--revision", help="Installation fingerprint; changing scripts requires native hook re-trust")
    parser.add_argument("--session-id", default=os.environ.get("CODEX_THREAD_ID"))
    for name in ("task-dir", "output-dir", "first-review", "second-review", "adjudication"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    root = args.runtime_root or runtime_root()
    if args.command == "hook":
        try:
            if args.revision and args.revision != script_revision():
                raise ValueError("GUARD_REVISION_CHANGED_REINSTALL_AND_RETRUST")
            event = json.load(sys.stdin)
            result = handle(event, root=root)
        except Exception as exc:
            # A broken guard is an explicit failure, never a silent success or
            # an unbounded self-retry. No exception contents (possibly secrets).
            result = {"systemMessage": "IPR 保护机制故障，未验证完成：" + type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command in {"bind", "resume"}:
        if args.task_dir is None:
            parser.error("--task-dir is required")
        result = bind(args.session_id, args.task_dir, root=root, resume=args.command == "resume",
                      **{key: getattr(args, key) for key in ("output_dir", "first_review", "second_review", "adjudication")})
    else:
        path = session_dir(root, args.session_id) / "binding.json"
        result = with_paths(path.parent, read(path, {}))
        progress = read(path.with_name("progress.json"), {})
        if args.command == "status" and progress.get("generation") == result.get("generation"):
            result = result | {"last_check": progress, "control_state": result.get("state"),
                               "state": progress.get("state", result.get("state"))}
        if args.command == "pause" and result:
            result = pause_binding(path.parent, "user_paused")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
