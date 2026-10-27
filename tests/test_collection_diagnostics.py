import copy
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch
from backend.collection_diagnostics import workspace, worker_failure
from backend.ai_connection import AIConnection
from backend.network import NetworkError
from backend.server import AtlasApplication, make_server

ROOT=Path(__file__).resolve().parents[1]


class CollectionDiagnosticsTests(unittest.TestCase):
    def test_read_only_and_no_secret_query_or_content(self):
        ds={'news_jobs':{'j':{'id':'j','status':'running','request':{'q':'PRIVATE'},'error':'SECRET',
              'message':'PRIVATE','pending_windows':[{'query_url':'PRIVATE'}]}},
            'news_coverage':{'c':{'status':'failed','error_code':'dns','query_url':'PRIVATE'}}}
        before=copy.deepcopy(ds)
        d=workspace(ds)
        self.assertEqual(ds,before)
        self.assertTrue(d['jobs'][0]['worker_missing'])
        self.assertEqual(d['jobs'][0]['result_code'],'worker_missing')
        self.assertEqual(d['coverage_error_counts'],{'dns':1})
        self.assertNotIn('PRIVATE',json.dumps(d));self.assertNotIn('SECRET',json.dumps(d))

    def test_zero_new_is_not_always_network_failure(self):
        for extra,expected in [({'duplicate_count':4},'duplicates_only'),
                               ({'returned_items':4},'no_matching_metadata'),
                               ({},'no_results'),({'new_articles':1},'saved'),
                               ({'failed_windows':[{}]},'source_errors')]:
            d=workspace({'news_jobs':{'j':{'id':'j','status':'partial',**extra}}})
            self.assertEqual(d['jobs'][0]['result_code'],expected)

    def test_error_messages_never_persist_exception_text(self):
        for error,code in [(TimeoutError('PRIVATE'),'timeout'),(ValueError('PRIVATE'),'worker_validation'),
                           (RuntimeError('PRIVATE'),'worker_internal'),(NetworkError('dns','PRIVATE'),'dns')]:
            d=worker_failure(error);self.assertEqual(d['code'],code)
            self.assertNotIn('PRIVATE',json.dumps(d))

    def test_active_worker_is_not_marked_missing(self):
        ds={'news_jobs':{'j':{'id':'j','status':'running'}}}
        for kwargs in [{'worker_alive':True},{'lock_held':True}]:
            self.assertFalse(workspace(ds,**kwargs)['jobs'][0]['worker_missing'])

    def test_corporate_key_never_sent_to_public_provider_or_stored(self):
        repo=Mock();vault=Mock();c=AIConnection(repo,'mock',vault)
        with patch('backend.ai_connection.request_bytes') as transport:
            result=c.connect({'provider':'corporate','key':'PRIVATE+CORP/KEY='})
        self.assertEqual(result['status'],'protocol_required')
        self.assertFalse(result['sent_to_provider'])
        transport.assert_not_called();repo.snapshot.assert_not_called();repo.transact.assert_not_called()
        vault.write.assert_not_called()

    def test_orphan_resume_uses_same_job_and_errors_remain_resumable(self):
        app=AtlasApplication.__new__(AtlasApplication)
        app.news_thread=None;app.collection_lock=threading.Lock();app.root=ROOT
        ds={'news_jobs':{'j':{'id':'j','status':'running','signature':'saved-signature',
                             'request':{'period':'1w','scope':'all','max_requests':1,'max_articles':5}}}}
        app.repo=Mock();app.repo.snapshot.side_effect=lambda:{'datasets':copy.deepcopy(ds)}
        app.repo.transact.side_effect=lambda fn:fn(ds)
        with patch('backend.collector.collect_news',side_effect=RuntimeError('PRIVATE')) as collect:
            result=app.search_news({'resume_job_id':'j'})
            app.news_thread.join(timeout=3)
        self.assertEqual(result['job_id'],'j');collect.assert_called_once()
        self.assertEqual(ds['news_jobs']['j']['error_code'],'worker_internal')
        self.assertEqual(ds['news_jobs']['j']['stop_reason'],'worker_error')
        self.assertTrue(ds['news_jobs']['j']['can_resume'])
        self.assertNotIn('PRIVATE',json.dumps(ds));self.assertFalse(app.collection_lock.locked())


class CollectionDiagnosticsHttpTests(unittest.TestCase):
    def test_diagnostic_endpoint_is_read_only_and_does_not_build_graphs(self):
        (ROOT/'runtime').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as temp:
            root=Path(temp)
            for folder in ('fixtures','config'):shutil.copytree(ROOT/folder,root/folder)
            app=AtlasApplication(root);server=make_server(app,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                before=(app.repo.root/'CURRENT.json').read_bytes()
                with patch.object(app,'state',side_effect=AssertionError('graph should not build')),patch.object(app,'view_snapshot',side_effect=AssertionError('whole snapshot should not copy')):
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f'http://127.0.0.1:{server.server_port}/api/collection/status',timeout=10) as f:d=json.load(f)['data']
                self.assertEqual(d['capability'],'collection_diagnostics_v2')
                self.assertEqual(before,(app.repo.root/'CURRENT.json').read_bytes())
            finally:
                app.stop.set();server.shutdown();server.server_close();thread.join(timeout=3)
