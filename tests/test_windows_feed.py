import base64
import json
import os
import subprocess
import unittest
from unittest.mock import Mock,patch
from backend import feed_worker,windows_feed
from backend.network import NetworkError

URL='https://news.google.com/rss/search?q=AIDC'

@unittest.skipUnless(os.name=='nt','Windows certificate-chain transport')
class WindowsFeedTests(unittest.TestCase):
    def test_proxy_choice_has_no_dns_or_pac_work_on_parent_thread(self):
        with patch('backend.windows_feed.getproxies_environment',return_value={'https':'http://proxy.invalid','no':'news.google.com'}):
            self.assertEqual(windows_feed._proxy_config(URL),{'mode':'direct','url':None})
        with patch('backend.windows_feed.getproxies_environment',return_value={}):
            self.assertEqual(windows_feed._proxy_config(URL),{'mode':'system','url':None})
    def test_tls_retry_is_once_and_shares_original_total_deadline(self):
        failed=Mock(returncode=0,stdout=b'{"ok":false,"code":"tls_certificate"}')
        with patch('backend.feed_worker.subprocess.run',return_value=failed),patch('backend.feed_worker.time.monotonic',side_effect=[10,12]),patch('backend.windows_feed.fetch',return_value=b'<rss/>') as native:
            self.assertEqual(feed_worker.fetch(URL),b'<rss/>')
        native.assert_called_once_with(URL,18)

    def test_no_new_attempt_after_total_deadline(self):
        failed=Mock(returncode=0,stdout=b'{"ok":false,"code":"tls_certificate"}')
        with patch('backend.feed_worker.subprocess.run',return_value=failed),patch('backend.feed_worker.time.monotonic',side_effect=[10,31]),patch('backend.windows_feed.fetch') as native:
            with self.assertRaises(NetworkError) as result:feed_worker.fetch(URL)
        self.assertEqual(result.exception.code,'feed_deadline');native.assert_not_called()

    def test_non_certificate_failures_are_not_retried(self):
        with patch('backend.feed_worker.subprocess.run',return_value=Mock(returncode=0,stdout=b'{"ok":false,"code":"http_407"}')),patch('backend.windows_feed.fetch') as native:
            with self.assertRaises(NetworkError):feed_worker.fetch(URL)
        native.assert_not_called()

    def test_native_rejects_unapproved_targets_without_starting_process(self):
        with patch('backend.windows_feed.subprocess.run') as run:
            with self.assertRaises(ValueError):windows_feed.fetch('https://example.test/rss',10)
        run.assert_not_called()

    def test_verified_native_protocol_and_no_url_on_commandline(self):
        result=Mock(returncode=0,stdout=json.dumps({'ok':True,'body':base64.b64encode(b'<rss/>').decode()}).encode())
        with patch('backend.windows_feed._proxy_config',return_value={'mode':'system','url':None}),patch('backend.windows_feed.subprocess.run',return_value=result) as run:
            self.assertEqual(windows_feed.fetch(URL,8),b'<rss/>')
        self.assertEqual(run.call_args.kwargs['timeout'],8)
        self.assertNotIn(URL,' '.join(run.call_args.args[0]))
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['url'],URL)
        self.assertIn('$request.AllowAutoRedirect=$false',windows_feed.SCRIPT)
        self.assertIn('$request.UseDefaultCredentials=$false',windows_feed.SCRIPT)
        self.assertIn('$response.StatusCode -ne 200',windows_feed.SCRIPT)
        self.assertNotIn('ServerCertificateValidationCallback=',windows_feed.SCRIPT)
        self.assertNotIn('SkipCertificateCheck',windows_feed.SCRIPT)

    def test_native_failure_does_not_emit_response_text_or_replay(self):
        result=Mock(returncode=0,stdout=b'{"ok":false,"code":"tls_certificate","message":"PRIVATE"}')
        with patch('backend.windows_feed._proxy_config',return_value={'mode':'system','url':None}),patch('backend.windows_feed.subprocess.run',return_value=result) as run:
            with self.assertRaises(NetworkError) as error:windows_feed.fetch(URL,8)
        self.assertEqual(error.exception.code,'tls_certificate');self.assertNotIn('PRIVATE',str(error.exception));run.assert_called_once()

    def test_native_child_timeout_remains_bounded(self):
        with patch('backend.windows_feed._proxy_config',return_value={'mode':'system','url':None}),patch('backend.windows_feed.subprocess.run',side_effect=subprocess.TimeoutExpired('PRIVATE',3)):
            with self.assertRaises(NetworkError) as error:windows_feed.fetch(URL,3)
        self.assertEqual(error.exception.code,'feed_deadline');self.assertNotIn('PRIVATE',str(error.exception))

    def test_proxy_credentials_are_not_implicitly_transmitted(self):
        with patch('backend.windows_feed._proxy_config',return_value={'mode':'explicit','url':'http://' + 'private:secret@proxy.invalid:8080'}),patch('backend.windows_feed.subprocess.run') as run:
            with self.assertRaises(NetworkError) as error:windows_feed.fetch(URL,3)
        self.assertEqual(error.exception.code,'proxy_configuration');run.assert_not_called()

    def test_redirect_status_is_reported_without_following(self):
        result=Mock(returncode=0,stdout=b'{"ok":false,"code":"http_302"}')
        with patch('backend.windows_feed._proxy_config',return_value={'mode':'system','url':None}),patch('backend.windows_feed.subprocess.run',return_value=result) as run:
            with self.assertRaises(NetworkError) as error:windows_feed.fetch(URL,3)
        self.assertEqual(error.exception.code,'http_302');run.assert_called_once()
