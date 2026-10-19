from copy import deepcopy
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.repository import JsonRepository, loads
from backend.server import AtlasApplication, SnapshotIntegrityError

ROOT = Path(__file__).resolve().parents[1]


class ViewCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ('fixtures', 'config'):
            shutil.copytree(ROOT / folder, self.root / folder)
        self.app = AtlasApplication(self.root)

    def tearDown(self):
        self.app.stop.set()
        worker = self.app._view_validator
        if worker:
            worker.join(timeout=3)
        self.temp.cleanup()

    def expire(self):
        self.app._view_checked_at = time.monotonic() - 21

    def test_slow_periodic_validation_never_blocks_get_or_holds_cache_lock(self):
        started, release = threading.Event(), threading.Event()
        strict = self.app.repo.snapshot
        before = self.app.view_snapshot()
        def delayed():
            started.set()
            self.assertTrue(release.wait(5))
            return strict()
        self.expire()
        with patch.object(self.app.repo, 'snapshot', side_effect=delayed) as reader:
            try:
                start = time.monotonic()
                self.assertEqual(self.app.view_snapshot(), before)
                self.assertLess(time.monotonic() - start, 0.5)
                self.assertTrue(started.wait(2))
                worker = self.app._view_validator
                self.assertEqual(self.app.view_snapshot(), before)
                self.assertEqual(reader.call_count, 1)
                self.assertTrue(self.app._view_lock.acquire(timeout=0.2))
                self.app._view_lock.release()
            finally:
                release.set()
                worker.join(timeout=3)

    def test_internal_commit_publishes_exact_generation_and_returns_defensive_copies(self):
        before = self.app.view_snapshot()
        pid = next(iter(before['datasets']['projects']))
        before['datasets']['projects'][pid]['name'] = 'caller mutation'
        self.assertNotEqual(self.app.view_snapshot()['datasets']['projects'][pid]['name'], 'caller mutation')
        committed = self.app.repo.transact(lambda ds: ds['settings']['app'].update(digest_hour=7))
        pointer = (self.app.repo.root / 'CURRENT.json').read_bytes()
        self.assertEqual(self.app._view_pointer, pointer)
        self.assertEqual(self.app._view_snapshot['generation'], committed['generation'])
        with patch.object(self.app.repo, 'snapshot', side_effect=AssertionError('redundant strict read')):
            self.assertEqual(self.app.view_snapshot(), committed)
        committed['datasets']['settings']['app']['digest_hour'] = 99
        self.assertEqual(self.app.view_snapshot()['datasets']['settings']['app']['digest_hour'], 7)

    def test_external_generation_requires_strict_validation_and_rejects_stale_publication(self):
        old = self.app.view_snapshot()
        old_pointer = self.app._view_pointer
        external = JsonRepository(self.app.repo.root)
        changed = external.transact(lambda ds: ds['settings']['app'].update(digest_hour=8))
        with patch.object(self.app.repo, 'snapshot', wraps=self.app.repo.snapshot) as reader:
            self.assertEqual(self.app.view_snapshot()['generation'], changed['generation'])
            self.assertEqual(reader.call_count, 1)
            self.app.view_snapshot()
            self.assertEqual(reader.call_count, 1)
        self.assertFalse(self.app._publish_view_snapshot(old, old_pointer))
        self.assertEqual(self.app.view_snapshot()['generation'], changed['generation'])

    def test_old_background_validation_cannot_overwrite_a_new_commit(self):
        old = self.app.view_snapshot()
        started, release = threading.Event(), threading.Event()
        def delayed():
            started.set()
            self.assertTrue(release.wait(5))
            return deepcopy(old)
        self.expire()
        with patch.object(self.app.repo, 'snapshot', side_effect=delayed):
            try:
                self.app.view_snapshot()
                self.assertTrue(started.wait(2))
                worker = self.app._view_validator
                changed = self.app.repo.transact(lambda ds: ds['settings']['app'].update(digest_hour=9))
            finally:
                release.set()
                worker.join(timeout=3)
        self.assertEqual(self.app.view_snapshot()['generation'], changed['generation'])
        self.assertIsNone(self.app._view_error_pointer)

    def test_old_failed_validation_cannot_poison_a_new_commit(self):
        started, release = threading.Event(), threading.Event()
        def delayed_failure():
            started.set()
            self.assertTrue(release.wait(5))
            raise ValueError('old-generation checksum failure')
        self.expire()
        with patch.object(self.app.repo, 'snapshot', side_effect=delayed_failure):
            try:
                self.app.view_snapshot()
                self.assertTrue(started.wait(2))
                worker = self.app._view_validator
                changed = self.app.repo.transact(lambda ds: ds['settings']['app'].update(digest_hour=10))
            finally:
                release.set()
                worker.join(timeout=3)
        self.assertIsNone(self.app._view_error_pointer)
        self.assertEqual(self.app.view_snapshot()['generation'], changed['generation'])

    def test_background_checksum_failure_is_sticky_and_preserves_last_verified_cache(self):
        before = self.app.view_snapshot()
        pointer = loads(self.app._view_pointer)
        manifest = loads((self.app.repo.root / 'generations' / pointer['generation'] / 'manifest.json').read_bytes())
        record = next(iter(manifest['datasets']['projects'].values()))
        filename = self.app.repo.root / 'generations' / record.get('generation', pointer['generation']) / 'projects' / record['file']
        filename.write_bytes(b'{}')
        self.expire()
        self.assertEqual(self.app.view_snapshot(), before)
        worker = self.app._view_validator
        if worker:
            worker.join(timeout=3)
        with self.assertRaises(SnapshotIntegrityError):
            self.app.view_snapshot()
        self.assertEqual(self.app._view_snapshot, before)
        with self.assertRaises(ValueError):
            self.app.repo.snapshot()


if __name__ == '__main__':
    unittest.main()
