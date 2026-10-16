"""Fake-IP and non-public answers are named before a run depends on them; no network is used."""
import socket
import unittest

import network_diagnostic as nd


def resolver(table):
    def lookup(host, port, type=0):
        value = table[host]
        if isinstance(value, BaseException):
            raise value
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port)) for address in value]
    return lookup


PUBLIC = {'m.media-amazon.com': ['151.101.1.16'], 'images-na.ssl-images-amazon.com': ['151.101.1.17'],
          'encrypted-tbn0.gstatic.com': ['142.251.40.110'], 'patentimages.storage.googleapis.com': ['142.250.1.1'],
          'patents.google.com': ['142.250.1.2'], 'ppubs.uspto.gov': ['151.101.2.2'], 'www.amazon.com': ['52.94.1.1']}


class NetworkDiagnosticTests(unittest.TestCase):
    def test_public_answers_are_ok(self):
        from unittest import mock
        # r9: a machine whose own proxy settings name a proxy reports proxy_without_fake_ip instead (test_r9_portable)
        with mock.patch.object(nd, 'proxy_settings', return_value={'configured': False}):
            result = nd.diagnose(resolver=resolver(PUBLIC))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['advice'], [])
        self.assertEqual(result['source_request'], 'not_run')

    def test_fake_ip_is_named_with_the_hosts_and_the_fix(self):
        table = {**PUBLIC, 'm.media-amazon.com': ['198.18.9.66'], 'www.amazon.com': ['198.19.0.3']}
        result = nd.diagnose(resolver=resolver(table))
        self.assertEqual(result['status'], 'fake_ip_detected')
        self.assertEqual(result['affected_hosts'], ['m.media-amazon.com', 'www.amazon.com'])
        text = ' '.join(result['advice'])
        self.assertIn('fake-ip-filter', text)
        self.assertIn('always-real-ip', text)

    def test_private_and_loopback_answers_are_not_public(self):
        table = {**PUBLIC, 'ppubs.uspto.gov': ['10.1.2.3'], 'patents.google.com': ['127.0.0.1']}
        result = nd.diagnose(resolver=resolver(table))
        self.assertEqual(result['status'], 'non_public_address')
        self.assertEqual(result['affected_hosts'], ['patents.google.com', 'ppubs.uspto.gov'])

    def test_unresolved_hosts_are_reported_without_raising(self):
        table = {name: OSError('no dns') for name in PUBLIC}
        self.assertEqual(nd.diagnose(resolver=resolver(table))['status'], 'unresolved')
        table = {**PUBLIC, 'www.amazon.com': OSError('no dns')}
        result = nd.diagnose(resolver=resolver(table))
        self.assertEqual((result['status'], result['unresolved_hosts']), ('partly_unresolved', ['www.amazon.com']))

    def test_slow_resolver_is_bounded(self):
        import time
        def slow(host, port, type=0):
            time.sleep(1.0)
            return []
        started = time.monotonic()
        result = nd.diagnose(hosts=('a.example',), timeout=0.2, resolver=slow)
        self.assertLess(time.monotonic() - started, 0.9)
        self.assertEqual(result['hosts'][0]['error'], 'DNS_TIMEOUT')

    def test_media_failures_collapse_into_one_advice_block(self):
        candidates = {'C1': {'status': 'needs_info', 'attempted': [
            {'url': 'https://www.rockler.com/a.jpg', 'failure': 'ValueError:MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking_198.18.0.0/15'},
            {'url': 'https://i5.walmartimages.com/b.jpg', 'failure': 'ValueError:MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking_198.18.0.0/15'}]},
            'C2': {'status': 'retained'}}
        lines = nd.media_failure_advice(candidates)
        self.assertIn('2 次', lines[0])
        self.assertIn('2 个域名', lines[0])
        self.assertEqual(nd.media_failure_advice({'C': {'attempted': [{'url': 'https://x.example/a', 'failure': 'timeout'}]}}), [])


if __name__ == '__main__':
    unittest.main()
