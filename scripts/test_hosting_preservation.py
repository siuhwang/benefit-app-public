import importlib.util
from pathlib import Path
import unittest

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


if __name__ == '__main__':
    unittest.main()
