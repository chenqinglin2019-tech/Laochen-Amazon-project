"""Completion must follow actual evidence/reviews/report bytes, not saved flags."""
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from advance_work import actionable_packet, execute_sources
from completion_check import check_completion, workflow_stage, validate_delivery
from common import atomic_write_json, load_json, sha256_file, sha256_json
from offline_test_support import isolated_test_environment


class CompletionTests(unittest.TestCase):
    def test_executable_work_blocks_all_claimed_artifacts(self):
        for kind in ("agent_investigation", "agent_read", "triage", "source_lookup", "plan_repair"):
            with self.subTest(kind=kind):
                view = {"entries": [{"kind": kind, "state": "ready"}]}
                self.assertEqual(workflow_stage(view, actionable_packet(view), first_review=Path("f"),
                    second_review=Path("s"), adjudication=Path("a"), output_dir=Path("r")), "investigation")

    def test_verified_evidence_entry_closes_round_without_claiming_business_complete(self):
        import completion_check as completion
        from delivery_versions_stage_e import REVISION
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = {"delivery_versions_revision": REVISION}
            atomic_write_json(root / "task.json", task)
            for name in completion.ARTIFACTS:
                (root / name).write_text('{}')
            data = {"publication": {"mode": "evidence", "delivery_status": "completed"},
                    "business_status_stage_b": {"business_status": "awaiting_dependency"}}
            atomic_write_json(root / "report-data.json", data)
            paths = [root / name for name in ('f.json', 's.json', 'a.json')]
            for path in paths:
                atomic_write_json(path, {"review_context": {"session_id": path.stem, "evidence_digest": "digest"}})
            view = {"entries": []}
            def stage():
                return workflow_stage(view, actionable_packet(view), first_review=paths[0], second_review=paths[1],
                    adjudication=paths[2], output_dir=root, task_dir=root)
            with patch('completion_check.validate_delivery', return_value=[]), \
                    patch('delivery_versions_stage_e.entry_errors', return_value=[]):
                self.assertEqual(stage(), 'limited_round_closed')
                data['publication']['mode'] = 'final'
                atomic_write_json(root / 'report-data.json', data)
                self.assertEqual(stage(), 'validation')
                data['publication']['mode'] = 'evidence'
                data['business_status_stage_b']['business_status'] = 'business_complete'
                atomic_write_json(root / 'report-data.json', data)
                self.assertEqual(stage(), 'complete')
                data['business_status_stage_b']['business_status'] = 'awaiting_dependency'
                atomic_write_json(root / 'report-data.json', data)
                with patch('delivery_versions_stage_e.entry_errors', return_value=['missing-entry']):
                    self.assertEqual(stage(), 'delivery')
                with patch('completion_check.validate_delivery', return_value=['changed-source']):
                    self.assertEqual(stage(), 'validation')
                data['publication']['delivery_status'] = 'not_delivered'
                atomic_write_json(root / 'report-data.json', data)
                self.assertEqual(stage(), 'validation')

    def test_missing_plan_is_setup_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic_write_json(root / "task.json", {"task_id": "synthetic", "execution_policy_revision": "continuous-work-v2"})
            atomic_write_json(root / "evidence.json", {})
            atomic_write_json(root / "continuous-work-status.json", {"stage": "complete"})
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = check_completion(root)
            self.assertEqual((result["status"], result["stage"]), ("continue", "setup"))
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_dispatch_error_paths_are_recorded(self):
        errors = execute_sources(Path("."), {"queries": {"unsupported": [{"query_id": "q"}]}},
                                 [{"query_id": "missing"}, {"query_id": "q"}])
        self.assertEqual([e["error"] for e in errors], ["PLAN_ROW_MISSING", "UNSUPPORTED_EXECUTOR"])

    def test_end_to_end_evidence_delivery_and_tampering(self):
        from test_evidence_delivery_integration import build_evidence_delivery_fixture
        from publish_report import publish
        with tempfile.TemporaryDirectory(prefix="ipr-completion-") as tmp, isolated_test_environment():
            source = Path(tmp) / "fixture"
            build_evidence_delivery_fixture(source)
            first, second, chief = [source / name for name in ("first-review.json", "second-review.json", "adjudication.json")]
            left, right = load_json(first), load_json(second)
            atomic_write_json(chief, {"reviewer": "synthetic-chief", "review_context": {
                "session_id": "synthetic-chief-session", "evidence_digest": left["review_context"]["evidence_digest"]},
                "decisions": [], "review_refs": {"first": sha256_json(left), "second": sha256_json(right)}})
            out = source / "guard-report"
            publish(source, first, second, adjudication=chief, output_dir=out, mode="auto")
            args = dict(first_review=first, second_review=second, adjudication=chief, output_dir=out)
            before = {str(p): p.read_bytes() for p in source.rglob("*") if p.is_file()}
            self.assertEqual(check_completion(source, **args)["status"], "complete")
            # Dispatcher defaults and Stop subprocess must agree with the gate.
            process = subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("advance_work.py")),
                "--task-dir", str(source), "--output-dir", str(out), "--require-complete"],
                capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(process.stdout)["stage"], "complete")
            # Exercise the CLI exit policy after an authoritative limited-round result.
            driver = ("import sys; sys.path.insert(0, " + repr(str(Path(__file__).resolve().parent)) +
                "); import advance_work; advance_work.workflow_stage = lambda *a, **k: 'limited_round_closed'; advance_work.main()")
            process = subprocess.run([sys.executable, "-B", "-c", driver, "--task-dir", str(source),
                "--output-dir", str(out), "--require-complete"], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(process.stdout)["stage"], "limited_round_closed")

            from codex_guard import bind, handle
            runtime = Path(tmp) / "runtime"
            bind("offline-host-protocol", source, root=runtime, output_dir=out)
            event = {"hook_event_name": "Stop", "session_id": "offline-host-protocol", "turn_id": "early"}
            original = (out / "report.html").read_bytes()
            (out / "report.html").unlink()
            try:
                self.assertEqual(handle(event, root=runtime)["decision"], "block")
            finally:
                (out / "report.html").write_bytes(original)
            self.assertNotIn("decision", handle(event | {"turn_id": "after-delivery", "stop_hook_active": True}, root=runtime))
            self.assertEqual(load_json(out / "report-data.json")["publication"]["mode"], "evidence")
            # advance_work intentionally writes its status; the check itself above is read-only.
            self.assertEqual(before, {str(p): p.read_bytes() for p in source.rglob("*") if p.is_file()
                                     and p.name != "continuous-work-status.json"})
            # Every absent component remains incomplete; restoring original bytes recovers.
            for path in (first, second, chief, out / "report.html", out / "delivery-validation.json"):
                with self.subTest(missing=path.name):
                    original = path.read_bytes()
                    path.unlink()
                    try:
                        self.assertNotEqual(check_completion(source, **args)["status"], "complete")
                    finally:
                        path.write_bytes(original)
            # Even forged matching artifact/receipt hashes cannot bypass canonical rendering.
            forged = (out / "report.html", out / "report-manifest.json", out / "delivery-validation.json")
            originals = {p: p.read_bytes() for p in forged}
            try:
                forged[0].write_text("<html>forged complete</html>", encoding="utf-8")
                manifest = load_json(forged[1])
                manifest["artifacts"]["report.html"]["sha256"] = sha256_file(forged[0])
                atomic_write_json(forged[1], manifest)
                receipt = load_json(forged[2])
                receipt["manifest_sha256"] = sha256_file(forged[1])
                atomic_write_json(forged[2], receipt)
                self.assertEqual(check_completion(source, **args)["stage"], "validation")
            finally:
                for path, original in originals.items():
                    path.write_bytes(original)
            for name in ("supplemental-evidence.json", "source-capabilities.json"):
                path = source / name
                original = path.read_bytes() if path.exists() else None
                try:
                    atomic_write_json(path, {"unexpected_change": True})
                    self.assertTrue(validate_delivery(source, out, first_review=first, second_review=second, adjudication=chief))
                finally:
                    if original is None:
                        path.unlink()
                    else:
                        path.write_bytes(original)
            path = source / "public-source.html"
            original = path.read_bytes()
            try:
                path.write_text("changed source bytes", encoding="utf-8")
                self.assertTrue(validate_delivery(source, out, first_review=first, second_review=second, adjudication=chief))
            finally:
                path.write_bytes(original)
            self.assertEqual(check_completion(source, **args)["status"], "complete")


if __name__ == "__main__":
    unittest.main()
