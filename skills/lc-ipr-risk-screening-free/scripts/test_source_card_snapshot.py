"""One card validation shares pure calculations and never persists a decision cache."""
import unittest
from unittest.mock import patch
from api_first_planning import source_card_state
from decision_workflow import _snapshot_value

class SourceCardSnapshotTests(unittest.TestCase):
    def test_request_scoped_pure_reuse_and_no_cross_call_cache(self):
        task,evidence,candidates,ledger,row,run=[{} for _ in range(6)]
        calls=[]
        def pure():calls.append(1);return len(calls)
        def validate(*args,**kwargs):
            a=_snapshot_value('snapshot_test',(task,evidence),pure)
            b=_snapshot_value('snapshot_test',(task,evidence),pure)
            self.assertEqual(a,b);return None,[]
        with patch('api_first_planning._source_card_state',side_effect=validate):
            source_card_state(task,evidence,candidates,ledger,row,run)
            self.assertEqual(len(calls),1)
            source_card_state(task,evidence,candidates,ledger,row,run)
            self.assertEqual(len(calls),2)
    def test_in_call_mutation_is_rejected(self):
        task={};evidence={};candidates={};ledger={};row={};run={}
        def validate(*args,**kwargs):evidence['changed']=True;return None,[]
        with patch('api_first_planning._source_card_state',side_effect=validate):
            with self.assertRaisesRegex(ValueError,'DECISION_SNAPSHOT_INPUT_MUTATED'):
                source_card_state(task,evidence,candidates,ledger,row,run)

if __name__=='__main__':unittest.main()
