"""News endpoint integration tests with isolated JSON and deterministic collection."""
import csv
import io
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from tests import test_api as transport
from backend.news import enrich_articles


class NewsApiTests(transport.ApiTests):
    # Reuse the transport fixture, not the inherited test cases.
    def seed_news(self):
        stamp = datetime.now(timezone.utc)
        def write(ds):
            for aid, age, title in [('recent',2,'Oracle 미국 데이터센터 냉각 확장'),('older',10,'AWS 울산 데이터센터 투자'),('archive',400,'Google 일본 데이터센터 계획')]:
                published = (stamp-timedelta(days=age)).isoformat()
                ds['articles'][aid] = {'id':aid,'title':title,'publisher':'DCD','source_id':'INT-M01','url':'https://public.example/'+aid,'published_at':published,'event_date':published,'collected_at':stamp.isoformat(),'first_seen_at':stamp.isoformat(),'summary':title,'evidence_excerpt':'','project_ids':[],'mode':'live_metadata','access_status':'feed_metadata_only','summary_method':'metadata_digest'}
            enrich_articles(ds,['recent','older','archive'])
        self.app.repo.transact(write)

    def test_news_period_state_export_and_explicit_read_agree(self):
        self.seed_news()
        data = json.loads(self.request('/api/news?period=1w')[1])['data']
        self.assertEqual([a['id'] for a in data['articles']], ['recent'])
        self.assertEqual([row['article_id'] for row in data['rows']], ['recent'])
        self.assertEqual(self.app.repo.snapshot()['datasets'].get('news_read_states',{}), {})
        state = json.loads(self.request('/api/state?period=1w')[1])['data']
        self.assertEqual([a['id'] for a in state['news']['articles']], ['recent'])
        raw = self.request('/api/export?kind=news-csv&period=1w')[1]
        csv_rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(len(csv_rows),2)
        self.assertIn('Oracle',csv_rows[1][2])
        self.assertNotIn('AWS 울산'.encode(),raw)
        report = self.request('/api/export?kind=news-report&period=1w')[1]
        self.assertIn('Oracle'.encode(),report)
        self.assertNotIn('AWS 울산'.encode(),report)
        self.assertEqual(self.request('/api/news/read', {'article_ids':['recent']})[0],200)
        self.assertFalse(json.loads(self.request('/api/news?period=1w')[1])['data']['articles'][0]['is_new'])
        self.assertEqual(len(self.app.repo.snapshot()['datasets'].get('read_states',{})),0)

    def test_country_city_filters_and_invalid_period(self):
        self.seed_news()
        domestic = json.loads(self.request('/api/news?period=1m&country=KR&city=%EC%9A%B8%EC%82%B0')[1])['data']
        self.assertEqual([a['id'] for a in domestic['articles']],['older'])
        foreign = json.loads(self.request('/api/news?period=1m&country=US')[1])['data']
        self.assertEqual([a['id'] for a in foreign['articles']],['recent'])
        self.assertEqual(self.request('/api/news?period=invalid')[0],400)

    def test_background_search_read_cancellation_and_restart_checkpoint(self):
        entered = threading.Event()
        release = threading.Event()
        captured = {}
        def fake(repo, root, request, job_id=None,progress=None):
            captured.update(request)
            entered.set()
            release.wait(5)
            def complete(ds):
                cancelled = ds['news_jobs'][job_id].get('cancel_requested')
                ds['news_jobs'][job_id].update(status='cancelled' if cancelled else 'completed',pending_windows=[{'id':'left'}],complete_coverage=False)
            repo.transact(complete)
            return {'status':'cancelled'}
        with patch('backend.collector.collect_news',fake):
            status, raw, _ = self.request('/api/news/search',{'period':'1w','source_ids':['INT-M01'],'max_requests':1})
            self.assertEqual(status,200)
            job_id = json.loads(raw)['data']['job_id']
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.state()['data']['settings']['collection_enabled'])
            self.assertEqual(self.request('/api/news/cancel',{'job_id':job_id})[0],200)
            release.set()
            self.app.news_thread.join(timeout=5)
        job = self.app.repo.snapshot()['datasets']['news_jobs'][job_id]
        self.assertEqual(job['status'],'cancelled')
        self.assertEqual(captured['period'],'1w')
        self.assertFalse(job['complete_coverage'])

    def test_snapshot_bound_news_references_and_secret_exclusion(self):
        self.seed_news()
        snap = self.app.repo.snapshot()
        def bad(ds):
            ds['news_updates']['bad']={'id':'bad','article_id':'absent','company_ids':[],'project_ids':[]}
        with self.assertRaises(ValueError): self.app.repo.transact(bad)
        self.assertEqual(self.app.repo.snapshot(),snap)

    def test_manual_article_read_persists_on_first_import(self):
        from backend import pipeline
        result = pipeline.import_article(self.app.repo, {'title':'대전 데이터센터 Oracle 투자',
            'url':'https://example.com/new-manual-news','published_at':datetime.now(timezone.utc).isoformat()})
        aid = result['article_id']
        persisted = self.app.repo.snapshot()['datasets']
        self.assertTrue(any(u['article_id']==aid for u in persisted['news_updates'].values()))
        self.assertEqual(self.request('/api/news/read',{'article_ids':[aid]})[0],200)
        work = json.loads(self.request('/api/news?period=1m')[1])['data']
        self.assertFalse(next(a for a in work['articles'] if a['id']==aid)['is_new'])

    def test_company_provider_query_preserves_user_conditions_and_job_match(self):
        captured = []
        def fetch(url):
            captured.append(url)
            return b'<rss><channel></channel></rss>'
        companies = self.app.repo.snapshot()['datasets']['companies']
        cid = next(cid for cid,c in companies.items() if c['name']=='Oracle')
        with patch('backend.collector.fetch_public_feed_bounded',fetch):
            status,raw,_ = self.request('/api/news/search',{'period':'1d','company_id':cid,
                'source_ids':['INT-M06'],'max_requests':1})
            self.assertEqual(status,200)
            jobid=json.loads(raw)['data']['job_id']
            self.app.news_thread.join(timeout=8)
        job=self.app.repo.snapshot()['datasets']['news_jobs'][jobid]
        self.assertEqual(job['filters']['q'],'')
        self.assertEqual(job['request']['provider_query'],'Oracle')
        self.assertTrue(any('Oracle' in url for url in captured))
        work=json.loads(self.request('/api/news?period=1d&company_id='+cid+'&source_ids=INT-M06')[1])['data']
        self.assertIn(jobid,work['matching_job_ids'])

    def test_ontology_and_scope_counts_share_articles_not_fixed_projects(self):
        self.seed_news()
        data=json.loads(self.request('/api/state?period=3y')[1])['data']
        self.assertEqual(data['news']['counts']['articles'],data['ontology']['counts']['articles'])
        counts=data['news']['counts']['scope_counts']
        self.assertEqual(sum(counts[k] for k in ['kr-dc','kr-ai','global-ai','unresolved']),counts['all'])
        self.assertEqual(len(data['ontology']['article_refs']),data['news']['counts']['articles'])
        self.assertGreater(data['ontology']['counts']['pending_articles'],0)
        self.assertEqual(len(data['projects']),4)

    def test_scheduler_baseline_and_latest_are_independent_of_manual_filters(self):
        from copy import deepcopy
        from backend.repository import now
        ds=deepcopy(self.app.repo.snapshot()['datasets'])
        settings=ds['settings']['app']
        settings.update(collection_enabled=True,collection_mode='live_metadata',
                        news_search={'scope':'kr-dc','country':'KR','city':'울산','q':'private-filter'},
                        baseline_backfill_enabled=True)
        first=self.app._next_news_request(ds)
        self.assertEqual(first['period'],'3y')
        self.assertEqual(first['scope'],'all')
        self.assertEqual(first['q'],'')
        settings['baseline_job_id']='baseline'
        ds['news_jobs']={'baseline':{'id':'baseline','status':'partial','can_resume':True,
            'updated_at':now(),'request':{**first}}}
        latest=self.app._next_news_request(ds)
        self.assertEqual(latest['purpose'],'latest_incremental')
        self.assertEqual(latest['period'],'1d')
        self.assertEqual(latest['source_ids'],[])
        ds['news_jobs']['baseline']['updated_at']='2020-01-01T00:00:00+00:00'
        self.assertEqual(self.app._next_news_request(ds),{'resume_job_id':'baseline'})
        settings['collection_enabled']=False
        self.assertIsNone(self.app._next_news_request(ds))


# ApiTests are transport setup helpers here; unittest otherwise repeats inherited cases.
for _name in tuple(name for name in dir(transport.ApiTests) if name.startswith('test_')):
    setattr(NewsApiTests,_name,None)
