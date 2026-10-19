"""Cache correctness matters more than a timing assertion."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from backend.projection_cache import ProjectionCache
from backend.server import AtlasApplication, SnapshotIntegrityError

ROOT = Path(__file__).resolve().parents[1]


class ProjectionCacheTests(unittest.TestCase):
    def test_cached_values_are_defensive_in_both_directions(self):
        cache = ProjectionCache()
        original = {'data': {'items': [1]}}
        cache.put('a', original)
        original['data']['items'].append(2)
        result = cache.get('a')
        result['data']['items'].append(3)
        self.assertEqual(cache.get('a'), {'data': {'items': [1]}})

    def test_expiry_lru_and_size_bound(self):
        clock = [0]
        cache = ProjectionCache(capacity=2, max_bytes=100, ttl=20, clock=lambda: clock[0])
        cache.put('a', {'x': 1}); cache.put('b', {'x': 2})
        cache.get('a'); cache.put('c', {'x': 3})
        self.assertIsNone(cache.get('b'))
        self.assertFalse(cache.put('huge', {'x': 'z' * 1000}))
        self.assertLessEqual(cache._bytes, 100)
        clock[0] = 20
        self.assertIsNone(cache.get('a'))

    def test_workspace_hit_generation_invalidation_and_integrity_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            app = AtlasApplication(ROOT, Path(directory) / 'store')
            try:
                filters = {'period': '3y', 'scope': 'all'}
                self.assertEqual(app.repo.snapshot()['datasets']['settings']['app']['news_default_period'], '1y')
                from backend import server
                with patch.object(server.news, 'build_workspace', wraps=server.news.build_workspace) as build:
                    before = app.repo.snapshot()['generation']
                    first = app.state(filters)
                    second = app.state(dict(filters))
                    self.assertEqual(build.call_count, 1)
                    self.assertEqual(first, second)
                    second['data']['projects'].clear()
                    self.assertTrue(app.state(filters)['data']['projects'])
                    self.assertEqual(app.repo.snapshot()['generation'], before)
                    app.repo.transact(lambda ds: ds['settings']['app'].update(digest_hour=17))
                    self.assertEqual(app.state(filters)['data']['settings']['digest_hour'], 17)
                    self.assertEqual(build.call_count, 2)
                with patch.object(app, 'view_snapshot', side_effect=SnapshotIntegrityError('corrupt')):
                    with self.assertRaises(SnapshotIntegrityError):
                        app.state(filters)
            finally:
                app.stop.set()


if __name__ == '__main__':
    unittest.main()
