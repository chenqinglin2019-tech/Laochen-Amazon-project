"""Snapshot memo changes computation cost, never business evidence or semantics."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import decision_workflow as workflow
import test_scenario_planning
import test_historical_evidence
import historical_evidence


class DecisionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f = test_scenario_planning.ScenarioPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.annotate()

    def snapshot(self):
        f = self.f
        return workflow.decision_snapshot(f.task, f.evidence, f.candidates, f.plan, f.ledger)

    def decision(self):
        f = self.f
        return workflow.effective_decision(f.task, f.ledger, "trademarks", f.candidate,
            "product_entry", "US", evidence=f.evidence)

    def test_identical_semantics_one_computation_and_caller_cannot_poison_memo(self):
        expected = self.decision()
        with patch.object(workflow, "_effective_decision", wraps=workflow._effective_decision) as calculate:
            with self.snapshot() as context:
                first = self.decision()
                first["decision"] = "not_selected"
                first["annotation"]["reason"] = "caller changed returned copy"
                self.assertEqual(self.decision(), expected)
                self.assertEqual(calculate.call_count, 1)
                self.assertGreater(context["hits"], 0)
            self.assertEqual(context["memo"], {})
            self.assertEqual(context["retained"], {})
            self.assertEqual(self.decision(), expected)
            self.assertEqual(calculate.call_count, 2)

    def test_in_place_input_change_rejected_and_new_call_reopens(self):
        with self.assertRaisesRegex(ValueError, "DECISION_SNAPSHOT_INPUT_MUTATED"):
            with self.snapshot():
                self.decision()
                self.f.candidate["goods_services"] = ["different protected goods"]
                self.decision()
        self.assertEqual(self.decision()["decision"], "unreviewed")
        with self.snapshot():
            self.assertEqual(self.decision()["decision"], "unreviewed")

    def test_exception_clears_context_and_next_scope_cannot_reuse_it(self):
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with self.snapshot() as old:
                self.decision()
                raise RuntimeError("fixture")
        self.assertIsNone(workflow._SNAPSHOT.get())
        with self.snapshot() as new:
            self.assertIsNot(old, new)
            self.assertEqual(new["memo"], {})

    def test_nested_same_context_shares_and_other_context_restores(self):
        with self.snapshot() as outer:
            with self.snapshot() as inner:
                self.assertIs(inner, outer)
            f = self.f
            with workflow.decision_snapshot(deepcopy(f.task), f.evidence, f.candidates, f.plan, f.ledger) as other:
                self.assertIsNot(other, outer)
            self.assertIs(workflow._SNAPSHOT.get(), outer)

    def test_no_context_leaks_to_parallel_worker(self):
        with self.snapshot():
            self.decision()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertIsNone(pool.submit(workflow._SNAPSHOT.get).result())

    def test_changed_unrelated_content_does_not_reopen_existing_candidate(self):
        expected = self.decision()
        with self.snapshot():
            self.assertEqual(self.decision(), expected)
        self.f.evidence["collections"]["unrelated"] = [{"evidence_id": "UNRELATED", "payload": {"title": "other record"}}]
        with self.snapshot():
            self.assertEqual(self.decision(), expected)


class HistoricalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f = test_historical_evidence.HistoricalEvidenceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_unrelated_scope_does_not_read_files_but_exact_match_still_validates(self):
        f = self.f
        other = deepcopy(f.row)
        other["action_purpose"] = "needs_info:only abstract"
        with patch("assessment_estimate.validate_supplement") as validate:
            self.assertIsNone(historical_evidence.historical_action_reuse(
                f.task, f.provider, other, f.candidates, f.supplement, f.root))
            validate.assert_not_called()
        self.assertIsNotNone(f.reuse())

    def test_source_file_tamper_is_rechecked_even_inside_same_snapshot(self):
        f = self.f
        with workflow.decision_snapshot(f.task, {}, f.candidates, {}, {}, f.supplement):
            self.assertIsNotNone(f.reuse())
            (f.old / "response.json").write_bytes(b"changed exact source")
            self.assertIsNone(f.reuse())




class CompleteWorkViewSnapshotTests(unittest.TestCase):
    """Coverage and all later projections share a single read-only view memo."""
    def setUp(self):
        from contextlib import ExitStack
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from common import atomic_write_json
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        atomic_write_json(self.root/'task.json',{'task_id':'ONE-VIEW'})
        atomic_write_json(self.root/'search-plan.json',{'queries':{}})
        self.evidence={'source_runs':[],'collections':{}}
        self.candidates={'patents':[]};self.ledger={'annotations':[]};self.supplement={}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,kwargs in (
                ('workflow_v24._scenario_context',{'return_value':(self.candidates,self.ledger,self.evidence)}),
                ('workflow_v24.scenario_supplement',{'return_value':self.supplement}),
                ('necessary_completion.enabled',{'return_value':True}),
                ('workflow_v24.evidence_delivery_enabled',{'return_value':True}),
                ('necessary_completion.review_work',{'return_value':{}})):
            self.stack.enter_context(patch(name,**kwargs))
        for name in ('continuation_stage_c.project','continuous_progress_stage_d.project',
                     'review_progress_stage_a.project','stage_risk_stage_b.project'):
            self.stack.enter_context(patch(name,side_effect=lambda task,view,*args,**kwargs:view))
        self.contexts=[];self.computations=0

    def evaluate(self,task,evidence,candidates,plan,ledger,**kwargs):
        context=workflow._SNAPSHOT.get();self.assertIsNotNone(context)
        self.contexts.append(context)
        def compute():self.computations+=1;return {'value':self.computations}
        return workflow._snapshot_value('single-view-proof',(task,evidence,candidates,plan,ledger,self.supplement),compute,copy_result=True)

    def run_view(self,coverage=None,resolved=None):
        from workflow_v24 import work_view_from_dir
        def default_coverage(*args,**kwargs):self.evaluate(*args,**kwargs);return []
        def default_resolved(*args,**kwargs):
            self.evaluate(*args,**kwargs)
            return {'entries':[],'unresolved_scopes':[],'status':'complete'}
        with patch('assessment_v24.scenario_coverage_by_scope',side_effect=coverage or default_coverage), \
                patch('workflow_v24.resolved_work_view',side_effect=resolved or default_resolved):
            return work_view_from_dir(self.root,source_capabilities={})

    def test_coverage_and_resolved_share_memo_but_next_view_does_not(self):
        self.run_view()
        self.assertEqual(self.computations,1)
        self.assertIs(self.contexts[0],self.contexts[1])
        self.assertEqual(self.contexts[0]['memo'],{})
        self.assertIsNone(workflow._SNAPSHOT.get())
        self.run_view()
        self.assertEqual(self.computations,2)
        self.assertIsNot(self.contexts[0],self.contexts[2])

    def test_in_place_evidence_mutation_is_rejected_and_context_cleared(self):
        def changed(*args,**kwargs):
            self.evaluate(*args,**kwargs);self.evidence['changed']='material change'
            return {'entries':[]}
        with self.assertRaisesRegex(ValueError,'DECISION_SNAPSHOT_INPUT_MUTATED'):
            self.run_view(resolved=changed)
        self.assertIsNone(workflow._SNAPSHOT.get())
        self.assertEqual(self.contexts[0]['memo'],{})

    def test_exception_clears_view_memo(self):
        def failed(*args,**kwargs):self.evaluate(*args,**kwargs);raise RuntimeError('read failed')
        with self.assertRaisesRegex(RuntimeError,'read failed'):
            self.run_view(resolved=failed)
        self.assertIsNone(workflow._SNAPSHOT.get())
        self.assertEqual(self.contexts[0]['memo'],{})

    def test_actual_file_hash_is_checked_again_within_same_view(self):
        from common import sha256_file,resolve_retained_path
        original=self.root/'source.txt';original.write_text('original source')
        digest=sha256_file(original)
        def coverage(*args,**kwargs):
            self.evaluate(*args,**kwargs)
            resolve_retained_path(self.root,str(original),expected_sha256=digest)
            original.write_text('changed source bytes')
            return []
        def resolved(*args,**kwargs):
            self.evaluate(*args,**kwargs)
            resolve_retained_path(self.root,str(original),expected_sha256=digest)
            return {'entries':[]}
        with self.assertRaisesRegex(ValueError,'RETAINED_PATH_HASH_MISMATCH'):
            self.run_view(coverage,resolved)
        self.assertEqual(self.computations,1)
        self.assertIsNone(workflow._SNAPSHOT.get())

    def test_public_file_mutation_cannot_return_a_ready_work_view(self):
        import public_identity as public
        from common import atomic_write_json,sha256_file
        atomic_write_json(self.root/'task.json',{'task_id':'ONE-VIEW',
            'retrieval_workflow_revision':'api-first-v3','public_discovery_routing_revision':'public-discovery-v1'})
        path=self.root/'public-original.txt';path.write_text('retained original')
        digest=sha256_file(path)
        def coverage(*args,**kwargs):
            self.evaluate(*args,**kwargs)
            public._guard_file(public._VALIDATION.get(),path,digest)
            return []
        def resolved(*args,**kwargs):
            self.evaluate(*args,**kwargs)
            path.write_text('changed after cached public verification')
            return {'entries':[{'state':'ready'}],'status':'complete'}
        result=None
        with self.assertRaisesRegex(ValueError,'PUBLIC_IDENTITY_VIEW_FILE_CHANGED'):
            result=self.run_view(coverage,resolved)
        self.assertIsNone(result)
        self.assertIsNone(public._VALIDATION.get())
        self.assertIsNone(workflow._SNAPSHOT.get())


if __name__ == "__main__":
    unittest.main()
