"""Connection diagnostic failures must remain read-only, safe diagnostic results."""
import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from backend.server import AtlasApplication, make_server

RSS=b'<rss><channel/></rss>'
ENV={'https_proxy_configured':False,'custom_ca_configured':False,'pac_detected':False,'note':'test'}

class NetworkDiagnosticTests(unittest.TestCase):
    def test_failed_system_tls_path_and_backend_capability_are_visible_without_private_details(self):
        from backend.network import NetworkError
        app=AtlasApplication.__new__(AtlasApplication);app.repo=Mock()
        error=NetworkError('tls_certificate','Windows default certificate validation failed',transport='windows_system')
        with patch('backend.collector.fetch_public_feed_bounded',side_effect=error),patch('backend.network.network_environment',return_value=ENV):
            result=app.mutate('network/test',{})
        self.assertEqual(result['capability'],'network_diagnostics_v3')
        self.assertEqual([r['transport'] for r in result['results']],['windows_system']*2)
        self.assertEqual(app.repo.mock_calls,[])
    def test_first_request_failure_does_not_hide_diagnostic_or_skip_second_source(self):
        app=AtlasApplication.__new__(AtlasApplication);app.repo=Mock()
        with patch('backend.collector.fetch_public_feed_bounded',side_effect=[socket.gaierror('PRIVATE'),RSS]) as fetch,patch('backend.network.network_environment',return_value=ENV):
            result=app.mutate('network/test',{})
        self.assertEqual([r['code'] for r in result['results']],['dns','rss_verified'])
        self.assertEqual(fetch.call_count,2)
        self.assertFalse(result['collected_or_modified_articles'])
        self.assertEqual(app.repo.mock_calls,[])
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_both_sources_blocked_return_codes_instead_of_save_failure(self):
        app=AtlasApplication.__new__(AtlasApplication)
        error=urllib.error.HTTPError('https://private.invalid',407,'PRIVATE',{},None)
        with patch('backend.collector.fetch_public_feed_bounded',side_effect=error),patch('backend.network.network_environment',return_value=ENV):
            result=app.mutate('network/test',{})
        self.assertEqual([r['code'] for r in result['results']],['http_407','http_407'])
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('private.invalid',json.dumps(result))

    def test_non_feed_and_broken_xml_report_validation_failure(self):
        app=AtlasApplication.__new__(AtlasApplication)
        with patch('backend.collector.fetch_public_feed_bounded',side_effect=[b'<html/>',b'<rss>']),patch('backend.network.network_environment',return_value=ENV):
            result=app.mutate('network/test',{})
        self.assertEqual([r['code'] for r in result['results']],['feed_validation','feed_validation'])

class NetworkDiagnosticHttpTests(unittest.TestCase):
    def request(self,fail_environment=False):
        app=AtlasApplication.__new__(AtlasApplication);app.csrf='synthetic-csrf';app.repo=Mock()
        app.view_generation=Mock(side_effect=AssertionError('No repository read in network diagnostic'))
        server=make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('backend.collector.fetch_public_feed_bounded',side_effect=TimeoutError('PRIVATE')),patch('backend.network.network_environment',side_effect=RuntimeError('PRIVATE') if fail_environment else None,return_value=ENV):
                request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/network/test',data=b'{}',headers={'Content-Type':'application/json','X-Atlas-Token':app.csrf},method='POST')
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    with opener.open(request,timeout=10) as response:status=response.status;result=json.load(response)
                except urllib.error.HTTPError as error:status=error.code;result=json.load(error)
            app.view_generation.assert_not_called();self.assertEqual(app.repo.mock_calls,[])
            self.assertNotIn('PRIVATE',json.dumps(result))
            return status,result
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)

    def test_post_returns_network_codes_without_store_generation_dependency(self):
        status,result=self.request()
        self.assertEqual(status,200)
        self.assertEqual([r['code'] for r in result['data']['results']],['timeout','timeout'])
        self.assertNotIn('snapshot_id',result)

    def test_unexpected_diagnostic_failure_is_not_reported_as_failed_save(self):
        status,result=self.request(fail_environment=True)
        self.assertEqual(status,500)
        self.assertEqual(result['code'],'network_diagnostic_failed')
        self.assertNotIn('저장에 실패',result['error'])
