"""The claims-level host is an explicit opt-in at task creation; a default task never carries its marker."""
import unittest

from common import load_json
import test_product_entry as fixture_module


class ClaimsMarkerTests(fixture_module.ProductEntryTests):
    def make(self, *extra):
        args = ['--product-input', self.input, '--jurisdictions', 'US', '--output-dir', self.run, *extra]
        self.cli('create_task.py', *args)
        return load_json(self.run / 'task.json')

    def test_default_task_has_the_host_family_but_not_the_claims_marker(self):
        task = self.make()
        self.assertEqual(task['host_triage_revision'], 'host-triage-v1')
        self.assertNotIn('claims_triage_revision', task)

    def test_opt_in_flag_sets_only_the_marker(self):
        task = self.make('--claims-triage-host')
        self.assertEqual(task['claims_triage_revision'], 'claims-triage-v1')
        import claims_triage_host
        self.assertTrue(claims_triage_host.enabled(task))


# The inherited product-entry cases are run by their own module; only the cases defined above run here.
for _name in [n for n in dir(fixture_module.ProductEntryTests) if n.startswith('test_') and n not in vars(ClaimsMarkerTests)]:
    setattr(ClaimsMarkerTests, _name, None)

if __name__ == '__main__':
    unittest.main()
