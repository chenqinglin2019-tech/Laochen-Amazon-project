"""Offline host-protocol tests. These do NOT certify desktop hook activation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_guard import bind, handle, read, save, session_dir, run_check, update_bound_paths, with_paths
from install_codex_guard import install, LABEL


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ipr guard 中文 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task = self.root / "task"
        save(self.task / "task.json", {"task_id": "synthetic-guard", "execution_policy_revision": "continuous-work-v2"})
        bind("session-one", self.task, root=self.root)
        self.event = {"hook_event_name": "Stop", "session_id": "session-one", "turn_id": "turn-0",
                      "permission_mode": "default", "stop_hook_active": False}
        self.result = {"status": "continue", "stage": "investigation", "progress_digest": "a",
                       "reasons": ["WORK_REMAINS"], "next_actions": [{"action": "read_original"}]}

    def stop(self, **changes):
        return handle(self.event | changes, root=self.root, checker=lambda binding: self.result)

    def test_limited_paused_and_stopped_states_end_without_resuming_work(self):
        for number,status in enumerate(('limited_round_closed','user_paused','execution_stopped')):
            self.result={'status':status,'stage':status,'progress_digest':status,'business_completion':'incomplete',
                'report':'offline-entry' if status=='limited_round_closed' else None}
            response=self.stop(turn_id=f'terminal-{number}',stop_hook_active=True)
            self.assertNotEqual(response.get('decision'),'block')
            self.assertIn('systemMessage',response)

    def test_repeated_stop_hook_active_does_not_bypass_work(self):
        self.assertEqual(self.stop()["decision"], "block")
        self.assertEqual(self.stop(turn_id="turn-1", stop_hook_active=True)["decision"], "block")

    def test_same_turn_continuation_rechecks_changed_evidence(self):
        self.assertEqual(self.stop()["decision"], "block")
        self.result = {"status": "complete", "report": "/synthetic/report.html"}
        self.assertNotIn("decision", self.stop(stop_hook_active=True))

    def test_same_turn_continuations_are_bounded(self):
        self.stop()
        for _ in range(3):
            self.assertEqual(self.stop(stop_hook_active=True)["decision"], "block")
        self.assertFalse(self.stop(stop_hook_active=True)["continue"])

    def test_unrelated_session_and_plan_are_inert(self):
        with patch("codex_guard.run_check", side_effect=AssertionError("must not check")):
            self.assertEqual(self.stop(session_id="other"), {})
            self.assertEqual(self.stop(permission_mode="plan"), {})

    def test_duplicate_event_is_idempotent(self):
        first = self.stop()
        self.assertEqual(self.stop(), first)
        p = read(session_dir(self.root, "session-one") / "progress.json")
        self.assertEqual(p["unchanged"], 0)

    def test_two_diagnostic_continuations_then_explicit_failure(self):
        results = [self.stop(turn_id="t" + str(i)) for i in range(5)]
        self.assertTrue(all(r.get("decision") == "block" for r in results[:4]))
        self.assertIn("第 1 轮", results[2]["reason"])
        self.assertIn("第 2 轮", results[3]["reason"])
        self.assertFalse(results[-1]["continue"])
        self.assertIn("未完成", results[-1]["systemMessage"])
        self.assertEqual(self.stop(turn_id="t5"), results[-1])

    def test_progress_resets_diagnostics(self):
        for i in range(3):
            self.stop(turn_id=str(i))
        self.result["progress_digest"] = "new-evidence"
        self.assertNotIn("第 2 轮", self.stop(turn_id="3")["reason"])
        self.assertEqual(read(session_dir(self.root, "session-one") / "progress.json")["unchanged"], 0)

    def test_bind_same_task_does_not_reset_no_progress(self):
        self.stop()
        bind("session-one", self.task, root=self.root)
        self.stop(turn_id="next")
        self.assertEqual(read(session_dir(self.root, "session-one") / "progress.json")["unchanged"], 1)

    def test_interrupt_and_explicit_resume(self):
        handle(self.event | {"hook_event_name": "Interrupt"}, root=self.root)
        self.assertEqual(self.stop(), {})
        with self.assertRaisesRegex(ValueError, "EXPLICIT_GUARD_RESUME"):
            bind("session-one", self.task, root=self.root)
        bind("session-one", self.task, root=self.root, resume=True)
        self.assertEqual(self.stop()["decision"], "block")

    def test_interrupt_during_check_wins(self):
        def checker(binding):
            handle(self.event | {"hook_event_name": "Interrupt"}, root=self.root)
            return self.result
        self.assertEqual(handle(self.event, root=self.root, checker=checker), {})
        self.assertEqual(read(session_dir(self.root, "session-one") / "binding.json")["state"], "interrupted")

    def test_new_question_suspends_but_own_continuation_does_not(self):
        reason = self.stop()["reason"]
        self.assertEqual(handle(self.event | {"hook_event_name": "UserPromptSubmit", "prompt": reason}, root=self.root), {})
        self.assertEqual(self.stop(turn_id="continue")["decision"], "block")
        handle(self.event | {"hook_event_name": "UserPromptSubmit", "prompt": "现在进度如何？"}, root=self.root)
        self.assertEqual(self.stop(turn_id="question"), {})

    def test_compaction_restores_binding_not_sources(self):
        response = handle(self.event | {"hook_event_name": "SessionStart", "source": "compact"}, root=self.root)
        self.assertIn(str(self.task), response["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.stop()["decision"], "block")

    def test_new_plan_prompt_suspends_before_plan_shortcut(self):
        handle(self.event | {"hook_event_name": "UserPromptSubmit", "permission_mode": "plan", "prompt": "停止排查，换题"}, root=self.root)
        self.assertEqual(self.stop(permission_mode="default"), {})

    def test_publication_sync_only_updates_existing_matching_binding(self):
        with patch.dict("os.environ", {"CODEX_THREAD_ID": "session-one"}), patch("codex_guard.runtime_root", return_value=self.root):
            update_bound_paths(self.task, output_dir=self.task / "published")
            path = session_dir(self.root, "session-one") / "binding.json"
            self.assertEqual(with_paths(path.parent, read(path))["output_dir"], str(self.task / "published"))
            update_bound_paths(self.root / "unrelated", output_dir=self.root / "other")
            self.assertEqual(with_paths(path.parent, read(path))["output_dir"], str(self.task / "published"))
            handle(self.event | {"hook_event_name": "Interrupt"}, root=self.root)
            update_bound_paths(self.task, output_dir=self.task / "should-not-resume")
            self.assertEqual(read(path)["state"], "interrupted")

    def test_terminal_complete_vs_waiting(self):
        self.result = {"status": "complete", "report": "/synthetic/report.html"}
        self.assertNotIn("decision", self.stop())
        self.result = {"status": "awaiting_user"}
        self.assertIn("未完成", self.stop(turn_id="waiting")["systemMessage"])

    def test_error_is_not_completion(self):
        self.result = {"status": "error", "reasons": ["CHECK_FAILED"]}
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("检查器故障", result["reason"])

    def test_checker_timeout_does_not_leak_output(self):
        with patch("codex_guard.subprocess.run", side_effect=subprocess.TimeoutExpired("secret-value", 40)):
            result = run_check({"task_dir": str(self.task)})
        self.assertEqual(result["status"], "error")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_two_tasks_cannot_replace_active_binding(self):
        other = self.root / "other-task"
        save(other / "task.json", {"task_id": "other", "execution_policy_revision": "continuous-work-v2"})
        with self.assertRaisesRegex(ValueError, "SESSION_ALREADY"):
            bind("session-one", other, root=self.root)

    def test_finished_task_replacement_requires_live_check_not_saved_flag(self):
        other = self.root / "next-task"
        save(other / "task.json", {"task_id": "next", "execution_policy_revision": "continuous-work-v2"})
        save(session_dir(self.root, "session-one") / "progress.json", {"state": "complete"})
        with patch("codex_guard.run_check", return_value={"status": "continue"}):
            with self.assertRaisesRegex(ValueError, "SESSION_ALREADY"):
                bind("session-one", other, root=self.root)
        with patch("codex_guard.run_check", return_value={"status": "complete"}) as checker:
            bind("session-one", other, root=self.root)
            checker.assert_called_once()
        self.assertEqual(read(session_dir(self.root, "session-one") / "binding.json")["task_id"], "next")

    def test_interrupt_during_old_task_check_cancels_replacement(self):
        other = self.root / "next-task"
        save(other / "task.json", {"task_id": "next", "execution_policy_revision": "continuous-work-v2"})
        def interrupt_and_finish(binding):
            handle(self.event | {"hook_event_name": "Interrupt"}, root=self.root)
            return {"status": "complete"}
        with patch("codex_guard.run_check", side_effect=interrupt_and_finish):
            with self.assertRaisesRegex(ValueError, "CONTROL_CHANGED"):
                bind("session-one", other, root=self.root)
        self.assertEqual(read(session_dir(self.root, "session-one") / "binding.json")["state"], "interrupted")

    def test_same_turn_changed_output_never_reuses_old_success(self):
        bind("session-one", self.task, root=self.root, output_dir=self.task / "old")
        self.result = {"status": "complete", "report": str(self.task / "old/report.html")}
        self.assertIn("old/report", self.stop()["systemMessage"])
        bind("session-one", self.task, root=self.root, output_dir=self.task / "new")
        self.result = {"status": "complete", "report": str(self.task / "new/report.html")}
        self.assertIn("new/report", self.stop()["systemMessage"])

    def test_path_change_during_check_never_accepts_old_report(self):
        bind("session-one", self.task, root=self.root, output_dir=self.task / "old-report")
        def checker(binding):
            update_bound_paths(self.task, output_dir=self.task / "new-report")
            return {"status": "complete", "report": str(self.task / "old-report/report.html")}
        with patch.dict("os.environ", {"CODEX_THREAD_ID": "session-one"}), patch("codex_guard.runtime_root", return_value=self.root):
            result = handle(self.event, root=self.root, checker=checker)
        self.assertEqual(result["decision"], "block")
        self.assertIn("binding_changed", result["reason"])

    def test_binding_update_cannot_overwrite_interrupt(self):
        started = threading.Event()
        interrupted = threading.Event()
        failures = []
        def interrupt():
            started.set()
            try:
                handle(self.event | {"hook_event_name": "Interrupt"}, root=self.root)
                interrupted.set()
            except Exception as exc:
                failures.append(type(exc).__name__)
        worker = threading.Thread(target=interrupt)
        def during_save(path, value):
            if path.name == "paths.json" and not started.is_set():
                worker.start()
                self.assertTrue(started.wait(0.5))
            save(path, value)
        with patch("codex_guard.save", side_effect=during_save):
            bind("session-one", self.task, root=self.root, output_dir=self.task / "new")
            worker.join(2)
        self.assertFalse(failures)
        self.assertTrue(interrupted.is_set())
        self.assertEqual(read(session_dir(self.root, "session-one") / "binding.json")["state"], "interrupted")

    def test_cli_protocol_and_invalid_json(self):
        command = [sys.executable, "-B", str(Path(__file__).with_name("codex_guard.py")),
                   "hook", "--runtime-root", str(self.root)]
        proc = subprocess.run(command, input=json.dumps(self.event | {"session_id": "unbound"}),
                              text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(proc.stdout), {})
        proc = subprocess.run(command, input="{", text=True, capture_output=True, check=True)
        self.assertIn("未验证完成", json.loads(proc.stdout)["systemMessage"])


class InstallerTests(unittest.TestCase):
    def test_merge_idempotence_backup_and_scoped_uninstall(self):
        with tempfile.TemporaryDirectory(prefix="ipr hook installer ") as tmp:
            root = Path(tmp)
            original = {"custom": True, "hooks": {"Stop": [{"matcher": "", "hooks": [
                {"type": "command", "command": "existing-command", "statusMessage": "other"}]}]}}
            save(root / "hooks.json", original)
            result = install(root)
            self.assertEqual(read(Path(result["backup"])), original)
            self.assertIn("not_enabled", result["protection"])
            self.assertFalse(install(root)["changed"])
            installed = read(root / "hooks.json")
            self.assertEqual(installed["hooks"]["Stop"][0], original["hooks"]["Stop"][0])
            self.assertEqual(installed["hooks"]["Stop"][1]["hooks"][0]["statusMessage"], LABEL)
            install(root, uninstall=True)
            self.assertEqual(read(root / "hooks.json"), original)

    def test_inline_configuration_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.toml").write_text('[hooks]\nStop = []\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "INLINE_HOOKS_EXIST"):
                install(root)
            self.assertFalse((root / "hooks.json").exists())


if __name__ == "__main__":
    unittest.main()
