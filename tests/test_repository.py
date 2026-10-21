import json
import copy
import hashlib
import zipfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.repository import JsonRepository, ConflictError, loads, encoded


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = JsonRepository(self.root / 'store')

    def tearDown(self):
        self.temp.cleanup()

    def add(self):
        return self.repo.transact(lambda ds: ds.update(projects={'p': {'id': 'p', 'name': '사업'}}))

    def test_persistence_and_noop(self):
        snap = self.add()
        self.assertEqual(JsonRepository(self.root / 'store').snapshot(), snap)
        self.assertEqual(self.repo.transact(lambda ds: None)['generation'], snap['generation'])

    def test_startup_initializer_uses_one_strict_read_and_preserves_record_versions(self):
        original = self.add()
        pointer = loads((self.repo.root / 'CURRENT.json').read_bytes())
        old_manifest = loads((self.repo.root / 'generations' / pointer['generation'] / 'manifest.json').read_bytes())
        strict_read = JsonRepository._read
        with patch.object(JsonRepository, '_read', autospec=True, side_effect=strict_read) as reads:
            initialized = JsonRepository(self.repo.root, initializer=lambda ds: ds.update(settings={'app': {'id': 'app', 'initialized': True}}))
            # One active-generation read plus the unchanged strict verification
            # of the newly staged generation when initialization changes data.
            self.assertEqual(reads.call_count, 2)
            self.assertEqual(sum(not call.args[1:] for call in reads.call_args_list), 1)
        self.assertEqual(initialized.initial_snapshot['datasets']['projects'], original['datasets']['projects'])
        self.assertEqual(initialized.snapshot(), initialized.initial_snapshot)
        pointer = loads((self.repo.root / 'CURRENT.json').read_bytes())
        new_manifest = loads((self.repo.root / 'generations' / pointer['generation'] / 'manifest.json').read_bytes())
        self.assertEqual(new_manifest['datasets']['projects']['p']['sha256'], old_manifest['datasets']['projects']['p']['sha256'])
        with patch.object(JsonRepository, '_read', autospec=True, side_effect=strict_read) as reads:
            JsonRepository(self.repo.root, initializer=lambda ds: None)
            self.assertEqual(reads.call_count, 1)

    def test_invalid_initializer_does_not_activate_partial_data(self):
        self.add()
        pointer = (self.repo.root / 'CURRENT.json').read_bytes()
        def invalid(ds):
            ds['claims'] = {'bad': {'id': 'bad', 'project_id': 'missing'}}
        with self.assertRaises(ValueError): JsonRepository(self.repo.root, initializer=invalid)
        self.assertEqual((self.repo.root / 'CURRENT.json').read_bytes(), pointer)
        self.assertNotIn('claims', self.repo.snapshot()['datasets'])

    def test_concurrent_initializers_read_inside_the_same_writer_lock(self):
        errors = []
        def initialize():
            def increment(ds):
                app = ds.setdefault('settings', {}).setdefault('app', {'id': 'app', 'count': 0})
                app['count'] += 1
            try: JsonRepository(self.repo.root, initializer=increment)
            except Exception as error: errors.append(type(error).__name__)
        workers = [threading.Thread(target=initialize) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(10)
        self.assertEqual(errors, [])
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(self.repo.snapshot()['datasets']['settings']['app']['count'], 2)

    def test_verified_callback_runs_after_activation_and_cannot_mutate_returned_snapshot(self):
        events = []
        def published(snapshot, pointer):
            self.assertEqual((self.repo.root / 'CURRENT.json').read_bytes(), pointer)
            self.assertEqual(loads(pointer)['generation'], snapshot['generation'])
            events.append(snapshot['generation'])
            snapshot['datasets'].clear()
        self.repo.publish_callback = published
        result = self.add()
        self.assertIn('p', result['datasets']['projects'])
        self.assertEqual(events, [result['generation']])
        self.repo.transact(lambda ds: None)
        self.assertEqual(events, [result['generation'], result['generation']])
        self.assertEqual(self.repo.snapshot(), result)

    def test_cache_callback_failure_does_not_report_a_committed_transaction_as_failed(self):
        self.repo.publish_callback = lambda *_: (_ for _ in ()).throw(RuntimeError('cache unavailable'))
        result = self.add()
        self.assertEqual(self.repo.snapshot(), result)
        self.assertTrue(self.repo.publish_error)

    def test_immutable_records_are_reused_without_copying_on_each_news_checkpoint(self):
        first = self.add()
        second = self.repo.transact(lambda ds: ds.update(settings={'app':{'id':'app','enabled':True}}))
        folder = self.root/'store'/'generations'/second['generation']
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['datasets']['projects']['p']['generation'], first['generation'])
        self.assertFalse((folder/'projects').exists())
        self.assertEqual(JsonRepository(self.root/'store').snapshot()['datasets']['projects']['p']['name'], '사업')
        third = self.repo.transact(lambda ds: ds['projects']['p'].update(name='새값'))
        self.assertEqual(third['datasets']['projects']['p']['name'], '새값')

    def test_dangling_batch_never_published(self):
        before = self.repo.snapshot()
        with self.assertRaises(ValueError):
            self.repo.transact(lambda ds: ds.update(changes={'c': {'id': 'c', 'project_id': 'absent'}}))
        self.assertEqual(self.repo.snapshot(), before)

    def test_pointer_failure_keeps_complete_old_generation(self):
        before = self.add()
        import backend.repository as module
        original = module.atomic_write
        def interrupted(path, raw):
            if Path(path).name == 'CURRENT.json':
                raise OSError('simulated interruption at commit')
            return original(path, raw)
        with patch.object(module, 'atomic_write', interrupted):
            with self.assertRaises(OSError):
                self.repo.transact(lambda ds: ds['projects']['p'].update(name='새값'))
        self.assertEqual(JsonRepository(self.root / 'store').snapshot(), before)

    def test_corrupt_current_restores_verified_previous(self):
        before = self.add()
        self.repo.transact(lambda ds: ds['projects']['p'].update(name='새값'))
        (self.root / 'store' / 'CURRENT.json').write_text('broken', encoding='utf-8')
        recovered = JsonRepository(self.root / 'store')
        self.assertEqual(recovered.snapshot(), before)
        self.assertTrue(recovered.recovery_notice)

    def test_corrupt_record_not_silently_used(self):
        self.add()
        generation = self.repo.snapshot()['generation']
        record = next((self.root / 'store' / 'generations' / generation / 'projects').glob('*.json'))
        record.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.repo.snapshot()

    def test_conflict(self):
        old = self.repo.snapshot()['generation']
        self.add()
        with self.assertRaises(ConflictError):
            self.repo.transact(lambda ds: None, old)

    def test_two_repository_instances_do_not_lose_updates(self):
        self.repo.transact(lambda ds: ds.update(counters={'n': {'id': 'n', 'value': 0}}))
        other = JsonRepository(self.root / 'store')
        errors = []
        def increment(repo):
            try:
                for _ in range(8):
                    repo.transact(lambda ds: ds['counters']['n'].update(value=ds['counters']['n']['value'] + 1))
            except Exception as error:
                errors.append(str(error))
        threads = [threading.Thread(target=increment, args=(repo,)) for repo in (self.repo, other)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.repo.snapshot()['datasets']['counters']['n']['value'], 16)

    def test_backup_restore_and_validation(self):
        self.add()
        archive = self.repo.backup(self.root / 'backup.zip')
        self.repo.transact(lambda ds: ds['projects']['p'].update(name='변경'))
        self.repo.restore(archive)
        self.assertEqual(self.repo.snapshot()['datasets']['projects']['p']['name'], '사업')

    def test_invalid_numbers_keys_and_cycle(self):
        with self.assertRaises(ValueError): loads('{"id":1,"id":2}')
        with self.assertRaises(ValueError): loads('{"value":NaN}')
        with self.assertRaises(ValueError):
            self.repo.transact(lambda ds: ds.update(projects={'p': {'id': 'p', 'parent_id': 'p'}}))
        with self.assertRaises(ValueError):
            self.repo.transact(lambda ds: ds.update(values={'v': {'id': 'v', 'value': float('inf')}}))

    def test_reference_lists_rejected_in_transaction_and_backup_restore(self):
        good = {
            'projects': {'p': {'id':'p','company_ids':['co'],'article_ids':['a'],'capacities':[{'claim_id':'cl'}],'milestones':[{'article_id':'a'}]}},
            'companies': {'co': {'id':'co','project_ids':['p']}},
            'articles': {'a': {'id':'a','project_ids':['p'],'url':'https://public.example/release'}},
            'claims': {'cl': {'id':'cl','project_id':'p','article_id':'a'}},
            'relationships': {'r': {'id':'r','project_id':'p','company_id':'co','article_ids':['a'],'claim_ids':['cl']}},
            'changes': {'ch': {'id':'ch','project_id':'p','article_ids':['a']}},
            'internal_links': {'i': {'id':'i','company_id':'co','project_ids':['p']}},
            'notifications': {'n': {'id':'n','change_id':'ch','project_id':'p'}}}
        self.repo.transact(lambda ds: ds.update(good))
        before = self.repo.snapshot()
        cases = [
            ('projects','p','company_ids',['absent']), ('projects','p','article_ids',['absent']),
            ('companies','co','project_ids',['absent']), ('articles','a','project_ids',['absent']),
            ('relationships','r','article_ids',['absent']), ('relationships','r','claim_ids',['absent']),
            ('changes','ch','article_ids',['absent']), ('internal_links','i','project_ids',['absent']),
            ('notifications','n','project_id','absent'),
            ('projects','p','capacities',[{'claim_id':'absent'}]),
            ('projects','p','milestones',[{'article_id':'absent'}]),
            ('projects','p','milestones',[{'article_ids':['absent']}]),
            ('projects','p','capacity_history',[{'previous':{'claim_id':'cl'},'candidate':{'claim_id':'absent'}}]),
            ('projects','p','article_ids','a'), ('projects','p','capacities',['not-an-object'])]
        for index, (dataset, item, field, value) in enumerate(cases):
            with self.subTest(reference=dataset+'.'+field):
                bad = copy.deepcopy(good)
                bad[dataset][item][field] = value
                def mutate(ds): ds.clear(); ds.update(bad)
                with self.assertRaises(ValueError): self.repo.transact(mutate)
                self.assertEqual(self.repo.snapshot(), before)
                raw = encoded({'schema_version':1,'snapshot':{'datasets':bad}})
                backup = self.root / f'invalid-{index}.zip'
                with zipfile.ZipFile(backup, 'w') as archive:
                    archive.writestr('snapshot.json', raw)
                    archive.writestr('sha256.txt', hashlib.sha256(raw).hexdigest())
                with self.assertRaises(ValueError): self.repo.restore(backup)
                self.assertEqual(self.repo.snapshot(), before)

    def test_url_credentials_cannot_enter_json_repository(self):
        before = self.repo.snapshot()
        with self.assertRaises(ValueError):
            self.repo.transact(lambda ds: ds.update(articles={'a':{'id':'a','url':'https://public.example/release?api_key=ATLAS-TEST-SENTINEL'}}))
        self.assertEqual(self.repo.snapshot(), before)
        self.assertNotIn('ATLAS-TEST-SENTINEL', json.dumps(JsonRepository(self.root/'store').snapshot()))


if __name__ == '__main__':
    unittest.main()
