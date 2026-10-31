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

    def test_warm_state_cache_avoids_archive_copy_but_remains_defensive_and_fail_closed(self):
        expected = self.app.state({'period': '1y'})
        owned = self.app._view_snapshot
        import copy
        actual_copy = copy.deepcopy
        with patch('backend.server.copy.deepcopy', wraps=actual_copy) as copies:
            received = self.app.state({'period': '1y'})
        self.assertEqual(received, expected)
        self.assertFalse(any(c.args[0] is owned for c in copies.call_args_list))
        received['data']['companies'][0]['name'] = 'caller mutation'
        self.assertEqual(self.app.state({'period': '1y'}), expected)
        self.app._record_view_failure(self.app._view_pointer, MemoryError())
        with self.assertRaises(SnapshotIntegrityError):
            self.app.state({'period': '1y'})

    def test_idle_scheduler_reads_owned_view_without_archive_copy_or_store_write(self):
        pointer = (self.app.repo.root / 'CURRENT.json').read_bytes()
        with patch.object(self.app.stop, 'wait', side_effect=[False, True]), \
             patch.object(self.app, 'view_snapshot', side_effect=AssertionError('archive copy')), \
             patch.object(self.app, '_verified_view', wraps=self.app._verified_view) as reads:
            self.app._schedule()
        self.assertEqual(reads.call_count, 1)
        self.assertEqual((self.app.repo.root / 'CURRENT.json').read_bytes(), pointer)
        self.assertFalse((self.root / 'runtime/scheduler_error.json').exists())

    def test_generation_metadata_avoids_record_copy_and_honors_integrity_error(self):
        expected = self.app.view_snapshot()['generation']
        with patch('backend.server.copy.deepcopy', side_effect=AssertionError('unnecessary record copy')), \
             patch.object(self.app.repo, 'snapshot', side_effect=AssertionError('unnecessary archive scan')):
            self.assertEqual(self.app.view_generation(), expected)
            self.app._view_error_pointer = self.app._view_pointer
            with self.assertRaises(SnapshotIntegrityError):
                self.app.view_generation()

    def test_generation_metadata_strictly_recovers_after_cache_publication_failure(self):
        old = self.app.view_generation()
        def unavailable(*_):
            raise RuntimeError('cache publication unavailable')
        self.app.repo.publish_callback = unavailable
        committed = self.app.repo.transact(lambda ds: ds['settings']['app'].update(digest_hour=6))
        self.assertNotEqual(old, committed['generation'])
        self.assertIsNotNone(self.app.repo.publish_error)
        with patch.object(self.app.repo, 'snapshot', wraps=self.app.repo.snapshot) as reader:
            self.assertEqual(self.app.view_generation(), committed['generation'])
            self.assertEqual(reader.call_count, 1)
            self.assertEqual(self.app.view_snapshot(), committed)
            self.assertEqual(reader.call_count, 1)

    def test_slow_periodic_validation_never_blocks_get_or_holds_cache_lock(self):
        started, release = threading.Event(), threading.Event()
        strict = self.app.repo.snapshot
        before = self.app.view_snapshot()
        def delayed(*_):
            started.set()
            self.assertTrue(release.wait(5))
            return strict()
        self.expire()
        with patch.object(self.app.repo, 'revalidate_snapshot', side_effect=delayed) as reader:
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
            self.assertEqual(self.app.view_generation(), changed['generation'])
            self.assertEqual(reader.call_count, 1)
            self.app.view_snapshot()
            self.assertEqual(reader.call_count, 1)
        self.assertFalse(self.app._publish_view_snapshot(old, old_pointer))
        self.assertEqual(self.app.view_snapshot()['generation'], changed['generation'])

    def test_old_background_validation_cannot_overwrite_a_new_commit(self):
        old = self.app.view_snapshot()
        started, release = threading.Event(), threading.Event()
        def delayed(*_):
            started.set()
            self.assertTrue(release.wait(5))
            return deepcopy(old)
        self.expire()
        with patch.object(self.app.repo, 'revalidate_snapshot', side_effect=delayed):
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
        def delayed_failure(*_):
            started.set()
            self.assertTrue(release.wait(5))
            raise ValueError('old-generation checksum failure')
        self.expire()
        with patch.object(self.app.repo, 'revalidate_snapshot', side_effect=delayed_failure):
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
        with self.assertRaises(SnapshotIntegrityError):
            self.app.view_generation()
        self.assertEqual(self.app._view_snapshot, before)
        with self.assertRaises(ValueError):
            self.app.repo.snapshot()

    def test_io_failure_is_fail_closed_without_claiming_json_corruption_or_leaking_details(self):
        pointer=self.app._view_pointer
        self.app._record_view_failure(pointer, PermissionError('PRIVATE secret record details'))
        with self.assertRaises(SnapshotIntegrityError) as result:
            self.app.view_snapshot()
        self.assertEqual(result.exception.code,'store_read_unavailable')
        self.assertNotIn('PRIVATE',str(self.app.integrity_status()))
        self.assertEqual(self.app.integrity_status()['issue']['error_type'],'PermissionError')

    def test_resource_failure_is_not_mislabeled_as_checksum_failure(self):
        self.app._record_view_failure(self.app._view_pointer,MemoryError('PRIVATE'))
        with self.assertRaises(SnapshotIntegrityError) as result:self.app.view_generation()
        self.assertEqual(result.exception.code,'store_validation_unavailable')

    def test_explicit_recheck_recovers_only_after_full_strict_read_without_writing_store(self):
        pointer=(self.app.repo.root/'CURRENT.json').read_bytes()
        self.app._record_view_failure(pointer,PermissionError('temporary'))
        with patch.object(self.app.repo,'revalidate_snapshot',wraps=self.app.repo.revalidate_snapshot) as strict:
            response=self.app.recheck_integrity();worker=self.app._view_validator
            if worker:worker.join(timeout=4)
            self.assertEqual(strict.call_count,1)
        self.assertEqual(response['status'],'checking')
        self.assertEqual(self.app.integrity_status()['status'],'verified')
        self.assertEqual((self.app.repo.root/'CURRENT.json').read_bytes(),pointer)
        self.assertIsNone(self.app._view_error_pointer)

    def test_recheck_cannot_hide_real_corruption(self):
        pointer=loads(self.app._view_pointer)
        manifest=loads((self.app.repo.root/'generations'/pointer['generation']/'manifest.json').read_bytes())
        record=next(iter(manifest['datasets']['projects'].values()))
        filename=self.app.repo.root/'generations'/record.get('generation',pointer['generation'])/'projects'/record['file']
        original=filename.read_bytes();filename.write_bytes(b'{}')
        try:
            self.app.recheck_integrity();worker=self.app._view_validator
            if worker:worker.join(timeout=4)
            self.assertEqual(self.app.integrity_status()['status'],'failed')
            self.assertEqual(self.app.integrity_status()['issue']['code'],'store_integrity_error')
            with self.assertRaises(SnapshotIntegrityError):self.app.view_snapshot()
            self.assertEqual(filename.read_bytes(),b'{}')
        finally:filename.write_bytes(original)

    def test_double_recheck_joins_existing_worker_and_never_repeats_archive_read(self):
        started,release=threading.Event(),threading.Event();strict=self.app.repo.snapshot
        def delayed(*_):
            started.set();self.assertTrue(release.wait(5));return strict()
        with patch.object(self.app.repo,'revalidate_snapshot',side_effect=delayed) as reader:
            try:
                self.app.recheck_integrity();self.assertTrue(started.wait(2))
                self.assertTrue(self.app.recheck_integrity()['already_running'])
                self.assertEqual(self.app.integrity_status()['status'],'checking')
                self.assertEqual(reader.call_count,1)
            finally:
                release.set();worker=self.app._view_validator
                if worker:worker.join(timeout=4)

    def test_recheck_status_does_not_scan_or_copy_the_archive(self):
        self.app._record_view_failure(self.app._view_pointer,ValueError('PRIVATE'))
        with patch.object(self.app.repo,'snapshot',side_effect=AssertionError('No status scan')):
            self.assertEqual(self.app.integrity_status()['status'],'failed')

    def test_external_generation_is_not_reported_verified_before_strict_read(self):
        external=JsonRepository(self.app.repo.root)
        external.transact(lambda ds:ds['settings']['app'].update(digest_hour=11))
        self.assertEqual(self.app.integrity_status()['status'],'unverified')
        self.app.recheck_integrity();worker=self.app._view_validator
        if worker:worker.join(timeout=4)
        self.assertEqual(self.app.integrity_status()['status'],'verified')


if __name__ == '__main__':
    unittest.main()
