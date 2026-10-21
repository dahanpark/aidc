import http.client
import socket
import ssl
import unittest
import urllib.error
from unittest.mock import Mock, patch
from backend.network import request_bytes, error_info, network_environment, NoRedirect

URL = 'https://news.google.com/rss/search?q=test'


class NetworkTests(unittest.TestCase):
    def test_unapproved_target_never_resolves_or_connects(self):
        with patch('backend.network.socket.getaddrinfo') as dns:
            for url in ('http://news.google.com/rss', 'https://news.google.com@evil.test/rss', 'https://localhost/rss'):
                with self.assertRaises(ValueError): request_bytes(url, allowed_hosts={'news.google.com'})
            dns.assert_not_called()

    def test_direct_private_dns_is_rejected(self):
        with patch('backend.network.proxy_for', return_value=None), patch('backend.network.socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): request_bytes(URL, allowed_hosts={'news.google.com'})

    def test_proxy_is_used_with_verified_tls_and_no_redirect(self):
        response = Mock()
        response.read.return_value = b'<rss/>'
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch('backend.network.proxy_for', return_value='http://corp-proxy.invalid:8080'), patch('backend.network.urllib.request.build_opener', return_value=opener) as build, patch('backend.network.socket.getaddrinfo') as dns:
            self.assertEqual(request_bytes(URL, allowed_hosts={'news.google.com'}), b'<rss/>')
            dns.assert_not_called()
            handlers = build.call_args.args
            https = next(h for h in handlers if isinstance(h, __import__('urllib.request', fromlist=['HTTPSHandler']).HTTPSHandler))
            self.assertTrue(https._context.check_hostname)
            self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(any(isinstance(h, NoRedirect) for h in handlers))

    def test_post_is_never_replayed_after_uncertain_failure(self):
        connection = Mock()
        connection.getresponse.side_effect = TimeoutError('do not log')
        context = Mock()
        with patch('backend.network.proxy_for', return_value=None), patch('backend.network.tls_context', return_value=context), patch('backend.network.socket.getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('1.1.1.1',443))]), patch('backend.network.socket.create_connection'), patch('backend.network.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(TimeoutError): request_bytes(URL, allowed_hosts={'news.google.com'}, data=b'{}', method='POST')
            connection.request.assert_called_once()

    def test_network_messages_redact_proxy_credentials(self):
        secret = 'http://' + 'private-user:private-key@proxy.internal:8080'
        for error, expected in [(OSError(secret), 'network'), (socket.gaierror(secret), 'dns'),
                                (TimeoutError(secret), 'timeout'), (ssl.SSLCertVerificationError(secret), 'tls_certificate'),
                                (urllib.error.HTTPError(secret, 407, secret, {}, None), 'http_407')]:
            detail = error_info(error)
            self.assertEqual(detail['code'], expected)
            self.assertNotIn('private-', str(detail))
        with patch('backend.network.urllib.request.getproxies', return_value={'https': secret}):
            self.assertNotIn('private-', str(network_environment()))
