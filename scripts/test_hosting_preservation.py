import importlib.util
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error
import urllib.parse

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('publish-firebase-feeds.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class LiveSitePreservation(unittest.TestCase):
    def test_accepts_canonical_and_project_qualified_live_versions_for_the_same_site(self):
        self.assertEqual(publisher.version_path('projects/757082150706/sites/paran-5dcac/versions/live1'),
                         'sites/paran-5dcac/versions/live1')
        self.assertEqual(publisher.version_path('sites/paran-5dcac/versions/live1'),
                         'sites/paran-5dcac/versions/live1')
        with self.assertRaises(ValueError):
            publisher.version_path('sites/unrelated-site/versions/live1')

    def setUp(self):
        self.targets = {name: 'new-' + str(i) for i, name in enumerate(publisher.TARGETS)}
        self.before = {'/index.html': 'home', '/apps-in-toss-admin/admin-data.json': 'private-stub',
                       **{name: 'old' for name in publisher.TARGETS}}
        self.after = {**self.before, **self.targets}

    def test_home_and_private_stub_remain_byte_identical(self):
        publisher.validate_inventory(self.before, self.after, self.targets)
        for path in ['/index.html', '/apps-in-toss-admin/admin-data.json']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                publisher.validate_inventory(self.before, {**self.after, path: 'unexpected'}, self.targets)

    def test_rejects_unrelated_addition_or_deletion(self):
        with self.assertRaises(ValueError):
            publisher.validate_inventory(self.before, {**self.after, '/admin-export.json': 'unexpected'}, self.targets)
        missing = dict(self.after)
        missing.pop('/index.html')
        with self.assertRaises(ValueError):
            publisher.validate_inventory(self.before, missing, self.targets)

    def test_rejects_target_expansion_and_wrong_feed_bytes(self):
        with self.assertRaises(ValueError):
            publisher.validate_inventory(self.before, self.after, {**self.targets, '/index.html': 'home'})
        target = next(iter(self.targets))
        with self.assertRaises(ValueError):
            publisher.validate_inventory(self.before, {**self.after, target: 'wrong'}, self.targets)


class PublicFeedVerification(unittest.TestCase):
    version = 'sites/paran-5dcac/versions/confirmed-release'

    def response(self, body):
        response = MagicMock()
        response.status = 200
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    def test_stale_edge_then_exact_bytes_succeeds_with_fresh_read_only_requests(self):
        target = next(iter(publisher.TARGETS))
        opener = Mock(side_effect=[self.response(b'old'), self.response(b'new')])
        sleep = Mock()
        publisher.verify_public_feeds({target: b'new'}, self.version, opener=opener, sleep=sleep)
        self.assertEqual(opener.call_count, 2)
        requests = [call.args[0] for call in opener.call_args_list]
        self.assertNotEqual(requests[0].full_url, requests[1].full_url)
        for request in requests:
            self.assertEqual(request.get_method(), 'GET')
            self.assertIsNone(request.get_header('Authorization'))
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            self.assertEqual(query['hosting_version'], ['confirmed-release'])
        sleep.assert_called_once_with(1)

    def test_permanent_wrong_bytes_still_fail_after_bounded_reads(self):
        target = next(iter(publisher.TARGETS))
        opener = Mock(side_effect=lambda *args, **kwargs: self.response(b'wrong'))
        with self.assertRaisesRegex(ValueError, 'confirmed-release.*5 read attempts'):
            publisher.verify_public_feeds({target: b'new'}, self.version, opener=opener, sleep=Mock())
        self.assertEqual(opener.call_count, 5)

    def test_transient_server_failure_retries_only_the_read(self):
        target = next(iter(publisher.TARGETS))
        opener = Mock(side_effect=[
            urllib.error.HTTPError('https://paran-5dcac.web.app', 503, 'Unavailable', {}, None),
            self.response(b'new'),
        ])
        publisher.verify_public_feeds({target: b'new'}, self.version, opener=opener, sleep=Mock())
        self.assertEqual(opener.call_count, 2)

    def test_permission_failure_is_not_silently_retried(self):
        target = next(iter(publisher.TARGETS))
        opener = Mock(side_effect=urllib.error.HTTPError(
            'https://paran-5dcac.web.app', 403, 'Forbidden', {}, None))
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            publisher.verify_public_feeds({target: b'new'}, self.version, opener=opener, sleep=Mock())
        self.assertEqual(opener.call_count, 1)

    def test_already_published_release_verifies_public_bytes_without_another_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {}
            for target, relative in publisher.TARGETS.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = json.dumps({'generatedAt': '2026-10-22T21:46:00Z', 'notices': []}).encode()
                path.write_bytes(raw)
                expected[target] = raw
            hashes = {target: publisher.digest(gzip.compress(raw, compresslevel=9, mtime=0))
                      for target, raw in expected.items()}
            client = Mock()
            client.live.return_value = {'name': self.version, 'status': 'FINALIZED', 'fileCount': 3}
            client.files.return_value = {'/index.html': 'unchanged-home', **hashes}
            with patch.object(publisher, 'ROOT', root), patch.object(publisher, 'verify_public_feeds') as verify:
                result = publisher.publish(client)
            verify.assert_called_once_with(expected, self.version)
            self.assertEqual(result['mode'], 'already-current')
            self.assertFalse(result['released'])
            self.assertTrue(result['publicBytesVerified'])
            client.clone.assert_not_called()
            client.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
