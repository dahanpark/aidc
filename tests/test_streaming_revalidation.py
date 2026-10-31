import copy
import gc
import json
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.repository import JsonRepository, loads


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = JsonRepository(self.tmp.name)
        self.snap = self.repo.transact(lambda ds: ds.update(companies={'c': {'id': 'c', 'name': 'A'}}))
    def tearDown(self): self.tmp.cleanup()

    def test_revalidation_preserves_identity_but_rereads_and_checks_every_record(self):
        seen = []
        read = Path.read_bytes
        def track(path):
            if path.name != 'manifest.json': seen.append(path.name)
            return read(path)
        with patch.object(Path, 'read_bytes', track):
            checked = self.repo.revalidate_snapshot(self.snap)
        self.assertIs(checked['datasets'], self.snap['datasets'])
        self.assertGreaterEqual(len(seen), 1)

    def test_corrupt_disk_and_changed_memory_are_both_rejected(self):
        changed = copy.deepcopy(self.snap)
        changed['datasets']['companies']['c']['name'] = 'not the verified payload'
        with self.assertRaises(ValueError): self.repo.revalidate_snapshot(changed)
        pointer = loads((self.repo.root/'CURRENT.json').read_bytes())
        manifest = loads((self.repo.root/'generations'/pointer['generation']/'manifest.json').read_bytes())
        ref = manifest['datasets']['companies']['c']
        file = self.repo.root/'generations'/ref.get('generation',pointer['generation'])/'companies'/ref['file']
        file.write_bytes(b'{}')
        with self.assertRaises(ValueError): self.repo.revalidate_snapshot(self.snap)
        self.assertEqual(self.snap['datasets']['companies']['c']['name'], 'A')

    def test_external_generation_cannot_reuse_old_payloads(self):
        new = self.repo.transact(lambda ds: ds['companies']['c'].update(name='B'))
        checked = self.repo.revalidate_snapshot(self.snap)
        self.assertEqual(checked, new)
        self.assertIsNot(checked['datasets'], self.snap['datasets'])

    def test_strict_json_still_rejects_nested_nonfinite_and_non_json(self):
        for value in (float('nan'), {1, 2}):
            with self.assertRaises((ValueError, TypeError)):
                JsonRepository.validate({'companies': {'c': {'id': 'c', 'nested': {'value': value}}}})

    def test_synthetic_peak_allocations_are_lower_without_weakening_full_read(self):
        large = self.repo.transact(lambda ds: ds.update(notes={str(i): {'id':str(i),'text':str(i)+'x'*24000} for i in range(150)}))
        gc.collect();tracemalloc.start()
        ordinary = self.repo.snapshot()
        full_peak = tracemalloc.get_traced_memory()[1];tracemalloc.stop()
        del ordinary;gc.collect();tracemalloc.start()
        checked = self.repo.revalidate_snapshot(large)
        reuse_peak = tracemalloc.get_traced_memory()[1];tracemalloc.stop()
        self.assertEqual(checked, large)
        self.assertIs(checked['datasets'], large['datasets'])
        self.assertLess(reuse_peak, full_peak * 0.5)
