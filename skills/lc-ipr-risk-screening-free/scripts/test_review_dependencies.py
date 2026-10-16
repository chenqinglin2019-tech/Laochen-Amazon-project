"""The observed file set is local, exact and protocol-driven."""
from pathlib import Path
import tempfile
import unittest

from common import load_json, sha256_file
from review_dependencies import checked, collect, errors
from test_review_identity_recovery import recovery_fixture


class ReviewDependencyTests(unittest.TestCase):
    def test_same_bytes_at_distinct_paths_keep_both_existence_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            left, right = Path(tmp) / 'left', Path(tmp) / 'right'
            left.write_bytes(b'same'); right.write_bytes(b'same')
            with collect() as files:
                checked(left, sha256_file(left)); checked(right, sha256_file(right))
                checked(left, sha256_file(left))
                self.assertEqual(len(files), 2)
                with self.assertRaisesRegex(ValueError, 'CHANGED_DURING_CHECK'):
                    checked(left, 'different')
            self.assertEqual(errors(files), [])
            right.unlink()
            self.assertEqual(errors(files), ['DELIVERY_REVIEW_DEPENDENCY_CHANGED'])

    def test_nested_collectors_restore_without_cross_transaction_leaks(self):
        with collect() as outer:
            checked('first', 'a')
            with self.assertRaisesRegex(ValueError, 'stop'):
                with collect() as inner:
                    checked('second', 'b')
                    raise ValueError('stop')
            checked('third', 'c')
        checked('outside', 'd')
        self.assertEqual(len(outer), 2)
        self.assertEqual(len(inner), 1)

    def test_original_symlink_name_remains_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            left, right, link = [Path(tmp) / name for name in ('left', 'right', 'link')]
            left.write_bytes(b'old'); right.write_bytes(b'new')
            try:
                link.symlink_to(left)
            except OSError as exc:
                self.skipTest('Symlink creation unavailable: ' + str(exc))
            with collect() as files:
                checked(link, sha256_file(link))
            self.assertIn(str(link.absolute()), files)
            link.unlink(); link.symlink_to(right)
            self.assertEqual(errors(files), ['DELIVERY_REVIEW_DEPENDENCY_CHANGED'])

    def test_integrated_validation_collects_only_retained_artifacts(self):
        from final_review import validate_envelope
        with recovery_fixture() as fixture:
            reviews = fixture.run()
            fixture.binary.unlink()
            with collect() as files:
                for review in reviews:
                    validate_envelope(review)
            self.assertTrue(files)
            self.assertNotIn(str(fixture.binary), files)
            for chain in ('1', '2'):
                audit = load_json(fixture.output / chain / 'integrated/audit.json')
                for key in ('trace', 'packet', 'prompt', 'judgment', 'profile'):
                    self.assertIn(str(Path(audit[key + '_path']).absolute()), files)
            self.assertEqual(errors(files), [])


if __name__ == '__main__':
    unittest.main()
