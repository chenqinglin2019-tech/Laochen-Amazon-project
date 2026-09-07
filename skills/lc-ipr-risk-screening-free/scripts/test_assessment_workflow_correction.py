"""Corrected review obligations, future eligibility and publication inputs."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
import assessment_estimate as assessment
from decision_workflow import make_annotation
from test_assessment_estimate import fixture
from test_assessment_estimate_scenarios import scenario_fixture, refresh


REVISION = "workflow-correction-v1"


def corrected_fixture(directory):
    values = scenario_fixture(directory)
    task, evidence, candidates, plan, ledger, *_ = values
    task["workflow_correction_revision"] = REVISION
    plan["workflow_correction_revision"] = REVISION
    ledger["annotations"] = [make_annotation(task, "trademarks", candidates["trademarks"][0], row,
                                             evidence=evidence) for row in ledger["annotations"]]
    refresh(values)
    return values


class CorrectedAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ipr-correction-assessment-")
        self.directory = Path(self.temp.name)
        self.values = corrected_fixture(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def scopes(self, extra_trade=False):
        task = self.values[0]
        rows = [{"scenario_id": s["scenario_id"], "scenario_sha256": s["scenario_sha256"],
                 "jurisdiction": "US", "right_type": "trademark_word", "status": "满足已定义要求",
                 "retrieval_status": "complete", "triage_status": "complete", "verification_status": "complete",
                 "queries": [], "gaps": [], "obligations": [], "queues": {}}
                for s in task["assessment_scenarios"]]
        if extra_trade:
            rows.append({**rows[0], "right_type": "trade_dress"})
        return rows

    def calculate(self, *, extra_trade=False):
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes(extra_trade)), \
                patch("workflow_v24.scenario_execution_gaps", return_value=[]):
            return assessment.compute_assessment(*self.values)

    def add_brand(self):
        scenario = self.values[0]["assessment_scenarios"][1]
        for review in self.values[-2:]:
            review["assessments"].append({**deepcopy(review["assessments"][0]),
                "scenario_id": scenario["scenario_id"], "scenario_sha256": scenario["scenario_sha256"]})

    def signal(self, *, state="unknown", qualified=False):
        task, evidence, candidates, plan, ledger, first, second = self.values
        candidate = candidates["trademarks"][0]
        candidate["serial_number"] = "12345678"
        candidate["right_state"] = state
        ledger["annotations"] = [make_annotation(task, "trademarks", candidate, row, evidence=evidence)
                                 for row in ledger["annotations"]]
        signal = {key: first["assessments"][0][key] for key in
                  ("scenario_id", "scenario_sha256", "jurisdiction", "right_type", "candidate_id", "evidence_refs")}
        signal.update(reasoning="Documented application signal.", right_state=state)
        if qualified:
            signal["future_signal_basis"] = {"status": "pending", "application_identity": "12345678",
                "reasoning": "The bound record states the application is pending.", "evidence_refs": ["EV-PROV"]}
            signal["right_state_evidence_refs"] = ["EV-PROV"]
        for review in (first, second):
            review["assessments"] = []
            review["future_applications"] = [deepcopy(signal)]
        refresh(self.values)
        return signal

    def test_omitted_scope_remains_pending_even_when_investigation_complete(self):
        self.add_brand()
        result = self.calculate(extra_trade=True)
        primary = result["scenario_summaries"][0]
        self.assertEqual(primary["risk"], "高")
        self.assertEqual(primary["completion"]["assessment"], "incomplete")
        self.assertIn("SCOPE_ASSESSMENT_MISSING:US:trade_dress", primary["completion"]["gaps"])
        self.assertEqual(primary["completion"]["queues"]["scope_unassessed"][0]["right_type"], "trade_dress")
        self.assertEqual(result["status"], "incomplete")

    def test_explicit_pending_scope_is_not_mislabeled_as_missing(self):
        self.add_brand()
        for review in self.values[-2:]:
            row = deepcopy(review["assessments"][0])
            row.update(right_type="trade_dress", module_id="figurative_trade_dress", candidate_id="",
                       risk=None, assessment_status="pending", pending_reasoning="Source-identifying significance is unknown.")
            review["assessments"].append(row)
        result = self.calculate(extra_trade=True)
        primary = result["scenario_summaries"][0]["completion"]
        self.assertNotIn("SCOPE_ASSESSMENT_MISSING:US:trade_dress", primary["gaps"])
        self.assertIn("ASSESSMENT_PENDING:trade_dress:", primary["gaps"])

    def test_one_independent_scope_review_cannot_be_supplied_by_chief_alone(self):
        self.add_brand()
        self.values[-1]["assessments"] = []
        first, second = self.values[-2:]
        decisions = [{**deepcopy(row), "adjudication_reasoning": "Chief accepts the available first review.",
            "review_refs": {"first": sha256_json(first), "second": sha256_json(second)}} for row in first["assessments"]]
        chief = {"reviewer": "chief", "review_context": {"session_id": "chief-session",
            "evidence_digest": first["review_context"]["evidence_digest"]}, "decisions": decisions}
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes()), \
                patch("workflow_v24.scenario_execution_gaps", return_value=[]):
            result = assessment.compute_assessment(*self.values, chief)
        self.assertEqual(result["overall"]["risk"], "高")
        for scenario in result["scenario_summaries"]:
            missing = scenario["completion"]["queues"]["scope_unassessed"]
            self.assertEqual(missing[0]["missing_reviewers"], [second["reviewer"]])
            self.assertEqual(scenario["completion"]["assessment"], "incomplete")

    def test_verified_current_registration_cannot_move_to_future_array(self):
        self.signal(state="active", qualified=True)
        with self.assertRaisesRegex(ValueError, "FUTURE_SIGNAL_CURRENT_OR_GRANTED_RIGHT_CONFLICT"):
            self.calculate()

    def test_grant_kind_is_not_pending_and_never_infers_active_state(self):
        for state in ("unknown", "expired"):
            with self.subTest(state=state):
                self.values = corrected_fixture(self.directory)
                self.signal(state=state, qualified=True)
                candidate = self.values[2]["trademarks"][0]
                candidate.update(right_type="patent", publication_number="US11401089B2")
                row = self.values[-2]["future_applications"][0]
                row.update(right_type="patent")
                with self.assertRaisesRegex(ValueError, "FUTURE_SIGNAL_CURRENT_OR_GRANTED_RIGHT_CONFLICT"):
                    assessment._future_review_qualified(row, set(row["evidence_refs"]),
                        {"C-ART": ("patents", candidate)}, self.values[0])
                self.assertEqual(candidate["right_state"], state)

    def test_abandoned_ungranted_application_is_not_review_completion(self):
        self.signal(state="abandoned", qualified=True)
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"][0]["candidate_id"], "C-ART")

    def test_unknown_current_state_signal_does_not_close_selected_review(self):
        self.signal(state="unknown", qualified=True)
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"][0]["candidate_id"], "C-ART")
        self.assertEqual(result["overall"]["risk"], None)

    def test_candidate_pending_does_not_override_reviewed_unknown_state(self):
        self.signal(state="pending", qualified=True)
        for review in self.values[-2:]:
            review["future_applications"][0]["right_state"] = "unknown"
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"][0]["candidate_id"], "C-ART")

    def test_qualified_pending_application_needs_no_current_risk_grade(self):
        self.signal(state="pending", qualified=True)
        result = self.calculate()
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["selected_unassessed"], [])
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["scope_unassessed"], [])
        self.assertIsNone(result["overall"]["risk"])

    def test_signal_cannot_close_wrong_candidate_or_right(self):
        self.signal(state="pending", qualified=True)
        for change in ({"candidate_id": "UNKNOWN"}, {"right_type": "design"}):
            with self.subTest(change=change):
                reviews = deepcopy(self.values[-2:])
                for review in self.values[-2:]:
                    review["future_applications"][0].update(change)
                with self.assertRaisesRegex(ValueError, "FUTURE_SIGNAL_CANDIDATE_SCOPE_INVALID"):
                    self.calculate()
                for original, saved in zip(self.values[-2:], reviews):
                    original.clear()
                    original.update(saved)

    def test_full_row_signal_flags_share_eligibility_validation(self):
        for flag in ("future_signal", "signal_only"):
            with self.subTest(flag=flag):
                for review in self.values[-2:]:
                    row = review["assessments"][0]
                    row.update(risk=None, assessment_status="assessed", right_state="active",
                               right_state_evidence_refs=["EV-PROV"], **{flag: True})
                with self.assertRaisesRegex(ValueError, "FUTURE_SIGNAL_CURRENT_OR_GRANTED_RIGHT_CONFLICT"):
                    self.calculate()

    def test_correction_marker_changes_digest_and_requires_matching_plan(self):
        task, evidence, candidates, plan, ledger, *_ = self.values
        corrected = assessment.review_digest(evidence, candidates, ledger, plan, task)
        legacy_task = {key: value for key, value in task.items() if key != "workflow_correction_revision"}
        self.assertNotEqual(corrected, assessment.review_digest(evidence, candidates, ledger, plan, legacy_task))
        plan.pop("workflow_correction_revision")
        with self.assertRaisesRegex(ValueError, "SEARCH_PLAN_WORKFLOW_CORRECTION_REVISION_MISMATCH"):
            self.calculate()


class CorrectedPublicationInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ipr-publish-context-")
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, values):
        for name, value in zip(("task", "evidence", "normalized-candidates", "search-plan",
                                "materiality-annotations", "first-review", "second-review"), values):
            atomic_write_json(self.directory / (name + ".json"), value)

    def test_explicit_supplement_wins_and_default_discovery_is_opt_in(self):
        default = self.directory / "supplemental-evidence.json"
        atomic_write_json(default, {"schema": "test", "evidence": []})
        legacy = {"task_id": "T"}
        corrected = corrected_fixture(self.directory)[0]
        self.assertIsNone(assessment.resolve_estimate_supplement(self.directory, legacy))
        self.assertEqual(assessment.resolve_estimate_supplement(self.directory, corrected), default.resolve())
        explicit = self.directory / "other.json"
        self.assertEqual(assessment.resolve_estimate_supplement(self.directory, corrected, explicit), explicit.resolve())

    def test_present_invalid_default_supplement_is_not_ignored(self):
        values = corrected_fixture(self.directory)
        self.save(values)
        atomic_write_json(self.directory / "supplemental-evidence.json", [])
        with self.assertRaisesRegex(ValueError, "supplement"):
            assessment.finalize(self.directory, values[0], self.directory / "first-review.json",
                                self.directory / "second-review.json", output_dir=self.directory / "out")
        self.assertFalse((self.directory / "out/assessment.json").exists())

    def test_broken_default_supplement_is_not_silent_absence(self):
        values = corrected_fixture(self.directory)
        self.save(values)
        (self.directory / "supplemental-evidence.json").symlink_to(self.directory / "missing.json")
        with self.assertRaises(FileNotFoundError):
            assessment.finalize(self.directory, values[0], self.directory / "first-review.json",
                                self.directory / "second-review.json", output_dir=self.directory / "out")

    def test_new_default_supplement_after_freeze_invalidates_context(self):
        values = corrected_fixture(self.directory)
        self.save(values)
        context = assessment.finalize(self.directory, values[0], self.directory / "first-review.json",
            self.directory / "second-review.json", output_dir=self.directory / "out", return_context=True)
        atomic_write_json(self.directory / "supplemental-evidence.json", {"schema": "test", "evidence": []})
        with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            context.consume()

    def context(self):
        values = fixture(self.directory)
        self.save(values)
        return assessment.finalize(self.directory, values[0], self.directory / "first-review.json",
            self.directory / "second-review.json", output_dir=self.directory / "out", return_context=True)

    def test_context_is_single_use_and_not_constructible_from_json(self):
        with self.assertRaisesRegex(ValueError, "VERIFIED_ASSESSMENT_CONTEXT_REQUIRED"):
            assessment.VerifiedAssessmentContext(None, {}, {}, {}, self.directory, self.directory, {})
        context = self.context()
        self.assertIs(context.consume(task_dir=self.directory, output_dir=self.directory / "out"), context)
        with self.assertRaisesRegex(ValueError, "ALREADY_CONSUMED"):
            context.consume()

    def test_context_rejects_mutated_result_or_source_bytes(self):
        context = self.context()
        original = context.assessment["overall"]["risk"]
        context.assessment["overall"]["risk"] = "极低"
        with self.assertRaisesRegex(ValueError, "CONTEXT_MUTATED"):
            context.consume()
        context.assessment["overall"]["risk"] = original
        atomic_write_json(self.directory / "evidence.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            context.consume()

    def test_publish_computes_twice_and_keeps_standalone_validation(self):
        from publish_report import publish
        from report_estimate import build_bundle, validate_run
        values = fixture(self.directory)
        self.save(values)
        original_task = (self.directory / "task.json").read_bytes()
        with patch("assessment_estimate.compute_assessment", wraps=assessment.compute_assessment) as calculate:
            result = publish(self.directory, self.directory / "first-review.json", self.directory / "second-review.json",
                             output_dir=self.directory / "published")
        self.assertEqual(calculate.call_count, 2)
        self.assertEqual(result["file_integrity"], "valid")
        self.assertEqual((self.directory / "task.json").read_bytes(), original_task)
        for name in ("report.html", "report.md", "report-data.json", "report-findings.csv", "report-manifest.json"):
            self.assertTrue((self.directory / "published" / name).is_file(), name)
        output_task = load_json(self.directory / "published/task.json")
        with patch("assessment_estimate.compute_assessment", wraps=assessment.compute_assessment) as calculate:
            self.assertEqual(validate_run(self.directory, output_task, output_dir=self.directory / "published"), [])
        self.assertEqual(calculate.call_count, 1)
        with patch("assessment_estimate.compute_assessment", wraps=assessment.compute_assessment) as calculate:
            build_bundle(self.directory, output_task, values[1], load_json(self.directory / "published/assessment.json"),
                values[2], {"schema_version": "1.0", "task_id": values[0]["task_id"], "entries": []}, values[3],
                output_dir=self.directory / "standalone")
        self.assertEqual(calculate.call_count, 1)
        with self.assertRaisesRegex(ValueError, "PUBLISH_OUTPUT_ALREADY_EXISTS"):
            publish(self.directory, self.directory / "first-review.json", self.directory / "second-review.json",
                    output_dir=self.directory / "published")

    def test_context_rechecks_input_bytes_before_bundle_write(self):
        from report_estimate import build_bundle_from_verified_context
        context = self.context()
        atomic_write_json(self.directory / "normalized-candidates.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            build_bundle_from_verified_context(context, task_dir=self.directory, output_dir=self.directory / "out")
        self.assertFalse((self.directory / "out/report.html").exists())


if __name__ == "__main__":
    unittest.main()
