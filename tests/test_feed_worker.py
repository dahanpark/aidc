import base64
import copy
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from datetime import datetime,timedelta,timezone
from email.utils import format_datetime
from backend import feed_worker
from backend.collector import collect_news
from backend.network import NetworkError
from backend.repository import JsonRepository

ROOT=Path(__file__).resolve().parents[1]
URL='https://news.google.com/rss/search?q=data+center'


class FeedWorkerTests(unittest.TestCase):
    def test_unapproved_url_does_not_start_child(self):
        with patch('backend.feed_worker.subprocess.run') as run:
            with self.assertRaises(ValueError):feed_worker.fetch('https://example.test/rss')
        run.assert_not_called()

    def test_real_hanging_child_is_killed_within_total_deadline(self):
        real_run=subprocess.run
        def hang(args,**kwargs):return real_run([sys.executable,'-c','import time; time.sleep(5)'],**kwargs)
        started=time.monotonic()
        with patch('backend.feed_worker.subprocess.run',side_effect=hang):
            with self.assertRaises(NetworkError) as result:feed_worker.fetch(URL,timeout=.25)
        self.assertEqual(result.exception.code,'feed_deadline')
        self.assertLess(time.monotonic()-started,3)

    def test_protocol_is_bounded_and_redacts_child_errors(self):
        for value,expected in [({'ok':True,'body':base64.b64encode(b'<rss/>').decode()},None),
                               ({'ok':False,'code':'http_407','message':'PRIVATE'},'http_407'),
                               ({'ok':False,'code':'PRIVATE'},'feed_worker'),
                               ({'ok':True,'body':'not base64'},'feed_worker')]:
            with patch('backend.feed_worker.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps(value).encode())) as run:
                if expected:
                    with self.assertRaises(NetworkError) as error:feed_worker.fetch(URL)
                    self.assertEqual(error.exception.code,expected);self.assertNotIn('PRIVATE',str(error.exception))
                else:self.assertEqual(feed_worker.fetch(URL),b'<rss/>')
                self.assertEqual(run.call_args.kwargs['timeout'],20)
                self.assertTrue(run.call_args.kwargs['close_fds'])
                self.assertNotIn(URL,' '.join(run.call_args.args[0]))

    def test_child_error_output_has_no_exception_or_credentials(self):
        source=Mock();source.buffer=io.BytesIO(json.dumps({'url':URL}).encode())
        target=Mock();target.buffer=io.BytesIO()
        with patch('backend.feed_worker.sys.stdin',source),patch('backend.feed_worker.sys.stdout',target),patch('backend.collector.fetch_public_feed',side_effect=TimeoutError('PRIVATE')):
            feed_worker.main()
        output=target.buffer.getvalue();self.assertNotIn(b'PRIVATE',output)
        self.assertEqual(json.loads(output),{'ok':False,'code':'timeout'})

    def test_blocked_network_pauses_after_three_and_can_accumulate_after_resume(self):
        (ROOT/'runtime').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as temp:
            repo=JsonRepository(Path(temp)/'store')
            request={'period':'1y','source_ids':['INT-M02'],'max_requests':8}
            events=[]
            blocked=Mock(side_effect=NetworkError('feed_deadline','fixed'))
            first=collect_news(repo,ROOT,request,fetcher=blocked,progress=events.append)
            self.assertEqual(blocked.call_count,3);self.assertEqual(first['stop_reason'],'network_blocked')
            self.assertEqual(first['status'],'failed');self.assertTrue(first['can_resume'])
            self.assertGreater(len(first['pending_windows']),0);self.assertEqual(first['new_articles'],0)
            stamp=format_datetime(datetime.now(timezone.utc)-timedelta(hours=1))
            raw=('<rss><channel><item><title>Data center construction project</title><link>https://www.datacenterknowledge.com/test-worker</link><pubDate>'+stamp+'</pubDate></item></channel></rss>').encode()
            next_job=collect_news(repo,ROOT,request,first['id'],fetcher=lambda _:raw,progress=events.append)
            self.assertEqual(next_job['id'],first['id']);self.assertEqual(next_job['new_articles'],1)
            self.assertEqual(next_job['coverage_end'],first['coverage_end'])
            self.assertTrue(any(e['stage']=='requesting' for e in events))
            self.assertTrue(any(e['stage']=='saving' for e in events))
            self.assertNotIn('query_url',json.dumps(events));self.assertNotIn(URL,json.dumps(events))
