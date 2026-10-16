"""Generated UTF-8 report data survives a non-UTF-8 Windows default codec."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import load_json
from test_evidence_delivery_integration import build_evidence_delivery_fixture
from verify_skill import verify_operator_fixture


@contextmanager
def legacy_default_codec():
    original = Path.open
    def open_with_cp936(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and 'r' in mode and encoding in (None, 'locale'):
            encoding = 'cp936'
        return original(path, mode, buffering=buffering, encoding=encoding, errors=errors, newline=newline)
    with patch.object(Path, 'open', open_with_cp936):
        yield


class Utf8ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ipr 中文 release ')
        cls.addClassCleanup(cls.temp.cleanup)
        with legacy_default_codec():
            cls.result = build_evidence_delivery_fixture(Path(cls.temp.name) / '中文 商品',
                operator_policy=True, transaction=True)
            cls.report = Path(verify_operator_fixture(cls.result))
        cls.data = load_json(cls.report.parent / 'report-data.json')

    def test_build_validate_and_delivery_under_cp936(self):
        self.assertEqual(self.result['transaction']['completion']['status'], 'limited_round_closed')
        self.assertEqual(self.result['transaction']['completion']['validation_errors'], [])
        self.assertEqual(len(self.data['section_order']),7)
        self.assertEqual(len(self.data['operator_view']['modules']),9)

    def test_same_input_rendered_bytes_are_encoding_independent(self):
        from report_estimate import bundle_bytes
        normal = bundle_bytes(deepcopy(self.data), self.report.parent)
        with legacy_default_codec():
            legacy = bundle_bytes(deepcopy(self.data), self.report.parent)
        self.assertEqual(normal,legacy)
        for name,payload in normal.items():
            self.assertEqual(payload,(self.report.parent/name).read_bytes(),name)

    def test_release_refuses_legacy_policy_or_missing_file(self):
        missing = deepcopy(self.result); missing['delivered'] = str(Path(self.temp.name)/'missing')
        with self.assertRaisesRegex(ValueError,'FILE_MISSING'): verify_operator_fixture(missing)
        wrong = deepcopy(self.data); wrong['presentation_policy_revision']='old'
        with patch('common.load_json',return_value=wrong),self.assertRaisesRegex(ValueError,'POLICY_OR_MODULES'):
            verify_operator_fixture(self.result)
        incomplete=deepcopy(self.result); incomplete['transaction']['completion']['status']='continue'
        with self.assertRaisesRegex(ValueError,'DELIVERY_INCOMPLETE'): verify_operator_fixture(incomplete)


if __name__=='__main__': unittest.main()
