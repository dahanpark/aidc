"""Deterministic RSS/collection tests; real network probes are recorded separately."""
import copy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.collector import collect_news, parse_feed, fetch_public_feed, load_sources, _query
from backend.repository import JsonRepository

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)
SOURCE = next(s for s in load_sources(ROOT)['sources'] if s['source_id']=='INT-M01')


def feed(items=1, age=1, domain='www.datacenterdynamics.com', opaque=True):
    values=[]
    for i in range(items):
        url=f'https://news.google.com/rss/articles/id{i}' if opaque else f'https://{domain}/en/news/story-{i}/'
        values.append(f'<item><title>Data center expansion {i} - Data Center Dynamics</title><link>{url}</link><pubDate>{format_datetime(NOW-timedelta(hours=age))}</pubDate><description>Short public feed description</description><source url="https://{domain}">Data Center Dynamics</source></item>')
    return ('<rss><channel>'+''.join(values)+'</channel></rss>').encode()


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JsonRepository(self.temp.name)
        self.window={'start':(NOW-timedelta(days=7)).isoformat(),'end':NOW.isoformat()}

    def test_metadata_and_unresolved_redirect(self):
        articles, counts=parse_feed(feed(),SOURCE,self.window,NOW.isoformat())
        self.assertEqual(counts['returned'],1)
        self.assertEqual(articles[0]['mode'],'live_metadata')
        self.assertEqual(articles[0]['access_status'],'feed_metadata_only')
        self.assertEqual(articles[0]['original_url_status'],'aggregator_redirect_unresolved')
        self.assertEqual(articles[0]['project_ids'],[])
        self.assertLessEqual(len(articles[0]['feed_excerpt'].split()),25)

    def test_direct_feed_original_url(self):
        articles,_=parse_feed(feed(opaque=False),SOURCE,self.window,NOW.isoformat())
        self.assertEqual(articles[0]['original_url_status'],'publisher_url_from_feed')

    def test_future_and_outside_excluded(self):
        for age in (-1, 200):
            articles,counts=parse_feed(feed(age=age),SOURCE,self.window,NOW.isoformat())
            self.assertFalse(articles)
            self.assertEqual(counts['outside_period'],1)

    def test_mismatched_source_excluded(self):
        articles,counts=parse_feed(feed(domain='unregistered.example'),SOURCE,self.window,NOW.isoformat())
        self.assertFalse(articles)
        self.assertEqual(counts['source_mismatch'],1)

    def test_secret_article_url_rejected(self):
        raw=feed(opaque=False).replace(b'/story-0/',b'/story-0/?api_key=redacted')
        articles,counts=parse_feed(raw,SOURCE,self.window,NOW.isoformat())
        self.assertFalse(articles)
        self.assertEqual(counts['invalid'],1)

    def test_xml_entity_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY a "value">]><rss/>',SOURCE,self.window)

    def test_query_exact_days_expanded_and_geo(self):
        from urllib.parse import parse_qs,urlsplit
        query=parse_qs(urlsplit(_query(SOURCE,{'q':'Oracle','country':'US','city':''},self.window)).query)['q'][0]
        self.assertIn('United States',query)
        self.assertIn('site:datacenterdynamics.com',query)

    def test_unapproved_network_endpoint_rejected_without_dns(self):
        with patch('backend.collector.socket.getaddrinfo') as dns:
            with self.assertRaises(ValueError): fetch_public_feed('https://example.com/rss')
            dns.assert_not_called()

    def test_private_dns_rejected(self):
        with patch('backend.collector.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): fetch_public_feed('https://news.google.com/rss/search?q=x')

    def test_save_duplicate_and_resume(self):
        request={'period':'1w','source_ids':['INT-M01'],'max_requests':1}
        job=collect_news(self.repo,ROOT,request,fetcher=lambda _:feed(opaque=False))
        self.assertEqual(job['status'],'partial')
        self.assertEqual(job['new_articles'],1)
        first_filters=copy.deepcopy(job['filters'])
        job=collect_news(self.repo,ROOT,request,job_id=job['id'],fetcher=lambda _:feed(opaque=False))
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['new_articles'],1)
        self.assertEqual(job['duplicate_count'],1)
        self.assertEqual(job['filters'],first_filters)
        self.assertFalse(job['complete_coverage'])
        self.assertEqual(len(self.repo.snapshot()['datasets']['articles']),1)

    def test_resume_condition_change_rejected(self):
        job=collect_news(self.repo,ROOT,{'period':'1w','source_ids':['INT-M01'],'max_requests':1},fetcher=lambda _:feed())
        with self.assertRaises(ValueError):
            collect_news(self.repo,ROOT,{'period':'1m','source_ids':['INT-M01']},job_id=job['id'],fetcher=lambda _:feed())

    def test_cap_splits_historical_windows(self):
        job=collect_news(self.repo,ROOT,{'period':'1m','source_ids':['INT-M02'],'max_requests':1},fetcher=lambda _:feed(100,domain='www.datacenterknowledge.com'))
        self.assertEqual(job['status'],'partial')
        self.assertEqual(job['provider_caps'],1)
        self.assertEqual(len(job['pending_windows']),2)
        self.assertFalse(job['complete_coverage'])

    def test_failure_checkpoint_and_retry(self):
        def fail(_): raise OSError('no network')
        req={'period':'1w','source_ids':['INT-M02'],'max_requests':1}
        job=collect_news(self.repo,ROOT,req,fetcher=fail)
        self.assertEqual(job['status'],'failed')
        self.assertTrue(job['can_resume'])
        job=collect_news(self.repo,ROOT,req,job_id=job['id'],fetcher=lambda _:feed(domain='www.datacenterknowledge.com'))
        self.assertEqual(job['status'],'completed')
        self.assertEqual(len(job['failed_windows']),0)

    def test_cancel_checkpoint(self):
        def cancel(_):
            current=self.repo.snapshot()['datasets']['news_jobs']
            ident=next(iter(current))
            self.repo.transact(lambda ds:ds['news_jobs'][ident].update(cancel_requested=True))
            return feed()
        job=collect_news(self.repo,ROOT,{'period':'1m','source_ids':['INT-M01'],'max_requests':3},fetcher=cancel)
        self.assertEqual(job['status'],'cancelled')
        self.assertTrue(job['pending_windows'])
        self.assertTrue(job['can_resume'])

    def test_registry_101_and_defaults(self):
        config=load_sources(ROOT)
        sources=config['sources']
        self.assertEqual(len(sources),101)
        self.assertEqual(len({s['source_id'] for s in sources}),101)
        self.assertTrue(all(s['priority']=='P1' for s in sources if s['default_selected']))
        self.assertEqual(config['defaults']['period'],'3y')

    def test_three_year_default_is_checkpointed_without_claiming_archive_complete(self):
        request={'source_ids':['INT-M02'],'max_requests':1}
        job=collect_news(self.repo,ROOT,request,fetcher=lambda _:feed(domain='www.datacenterknowledge.com'))
        self.assertEqual(job['filters']['period'],'3y')
        self.assertEqual(job['request']['period'],'3y')
        self.assertGreaterEqual(job['total_windows'],35)
        self.assertGreater((_dt_test(job['coverage_end'])-_dt_test(job['coverage_start'])).days,1094)
        self.assertEqual(job['status'],'partial')
        self.assertTrue(job['can_resume'])
        self.assertFalse(job['complete_coverage'])
        original=(job['coverage_start'],job['coverage_end'])
        resumed=collect_news(self.repo,ROOT,request,job_id=job['id'],fetcher=lambda _:feed(domain='www.datacenterknowledge.com'))
        self.assertEqual(original,(resumed['coverage_start'],resumed['coverage_end']))

    def test_generic_ai_and_unrelated_news_are_rejected_locally(self):
        raw=feed(3,domain='www.datacenterknowledge.com')
        raw=raw.replace(b'Data center expansion 1',b'AI chip revenue is rising')
        raw=raw.replace(b'Data center expansion 2',b'City park art show opens today')
        job=collect_news(self.repo,ROOT,{'period':'1w','source_ids':['INT-M02'],'max_requests':1},fetcher=lambda _:raw)
        self.assertEqual(job['returned_items'],3)
        self.assertEqual(job['parsed_items'],3)
        self.assertEqual(job['relevant_items'],1)
        self.assertEqual(job['out_of_scope_items'],2)
        self.assertEqual(job['article_count'],1)
        self.assertEqual(job['new_articles'],1)
        snapshot=self.repo.snapshot()['datasets']
        self.assertEqual(len(snapshot['articles']),1)
        coverage=next(iter(snapshot['news_coverage'].values()))
        self.assertEqual(coverage['returned'],coverage['accepted']+coverage['out_of_scope'])
        self.assertEqual(coverage['out_of_scope'],2)

    def test_unresolved_metadata_retained_and_counted_separately(self):
        classification={'domain_relevance':{'status':'unresolved','reason':'insufficient_metadata'},
                        'scope_classification':{'primary_scope':None,'status':'unresolved','reason':'unknown'}}
        with patch('backend.news.classify_article',return_value=classification):
            job=collect_news(self.repo,ROOT,{'period':'1w','source_ids':['INT-M02'],'max_requests':1},fetcher=lambda _:feed(domain='www.datacenterknowledge.com'))
        self.assertEqual(job['uncertain_items'],1)
        self.assertEqual(job['out_of_scope_items'],0)
        self.assertEqual(job['new_articles'],1)
        coverage=next(iter(self.repo.snapshot()['datasets']['news_coverage'].values()))
        self.assertEqual(coverage['uncertain'],1)
        self.assertEqual(coverage['relevant'],0)


def _dt_test(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


if __name__ == '__main__': unittest.main()
