"""Fresh public checkout and bounded collection/connection regressions; no network."""
import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import Mock, patch

from backend.ai_connection import AIConnection, list_models
from backend.collector import collect_news
from backend.credentials import WindowsVault
from backend.repository import JsonRepository

ROOT = Path(__file__).resolve().parents[1]
KEY = 'sk-proj-' + 'synthetic-test-key-' * 3


def rss(count=1):
    stamp = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1))
    return ('<rss><channel>' + ''.join(
        f'<item><title>Data center expansion {i}</title><link>https://www.datacenterknowledge.com/story-{i}</link>'
        f'<pubDate>{stamp}</pubDate></item>' for i in range(count)) + '</channel></rss>').encode()


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JsonRepository(Path(self.temp.name) / 'store')
        self.request = {'period': '3y', 'source_ids': ['INT-M02'], 'max_requests': 1}
        self.vault = Mock()
        self.vault.read.return_value = None
        self.connection = AIConnection(self.repo, 'isolated-unit', self.vault)

    def test_request_cap_is_partial_and_resumes_original_bounds(self):
        first = collect_news(self.repo, ROOT, self.request, fetcher=lambda _: rss())
        self.assertEqual((first['status'], first['stop_reason']), ('partial', 'request_limit'))
        self.assertEqual(first['batch_request_count'], 1)
        self.assertGreater(first['remaining_windows'], 0)
        second = collect_news(self.repo, ROOT, self.request, first['id'], fetcher=lambda _: rss())
        self.assertEqual(second['request_count'], 2)
        self.assertEqual(first['coverage_end'], second['coverage_end'])
        self.assertFalse(second['complete_coverage'])

    def test_article_cap_reason(self):
        job = collect_news(self.repo, ROOT, {**self.request, 'max_requests': 3, 'max_articles': 1}, fetcher=lambda _: rss(2))
        self.assertEqual(job['stop_reason'], 'article_limit')
        self.assertEqual(job['batch_parsed_items'], 2)

    def test_source_errors_are_not_success_and_are_redacted(self):
        def fail(_):
            raise TimeoutError('secret-error-never-persist')
        job = collect_news(self.repo, ROOT, {**self.request, 'period': '1w'}, fetcher=fail)
        self.assertEqual((job['status'], job['stop_reason']), ('failed', 'source_errors'))
        self.assertEqual(job['retryable_failed_windows'], 1)
        self.assertNotIn('secret-error-never-persist', json.dumps(self.repo.snapshot()))
        retried = collect_news(self.repo, ROOT, {**self.request, 'period': '1w'}, job['id'], fetcher=lambda _: rss())
        self.assertEqual((retried['status'], retried['stop_reason']), ('completed', 'queue_exhausted'))

    def test_cancel_during_last_response_is_preserved(self):
        def cancel(_):
            ident = next(iter(self.repo.snapshot()['datasets']['news_jobs']))
            self.repo.transact(lambda ds: ds['news_jobs'][ident].update(cancel_requested=True))
            return rss()
        job = collect_news(self.repo, ROOT, {**self.request, 'period': '1w'}, fetcher=cancel)
        self.assertEqual((job['status'], job['stop_reason']), ('cancelled', 'user_cancelled'))
        self.assertFalse(job['can_resume'])
        self.assertEqual(job['new_articles'], 1)

    def test_malformed_and_empty_model_response_dont_save_or_call_inference(self):
        for raw, code in [(b'<html>blocked</html>', 'models_response_invalid'),
                          (b'[]', 'models_response_invalid'), (b'{"data":{}}', 'models_response_invalid'),
                          (b'{"data":[]}', 'models_empty')]:
            with self.subTest(code=code), patch('backend.ai_connection.request_bytes', return_value=raw) as request:
                response = self.connection.connect({'key': KEY})
                self.assertEqual(response['code'], code)
                self.assertEqual(response['stage'], 'models')
                self.assertFalse(response['inference_called'])
                request.assert_called_once()
                self.vault.write.assert_not_called()
                self.assertNotIn(KEY, json.dumps(self.repo.snapshot()))

    def test_http_failure_preserves_previous_connection(self):
        self.repo.transact(lambda ds: ds.update(settings={'app': {'id': 'app', 'ai': {'provider': 'openai', 'model': 'previous'}}}))
        before = self.repo.snapshot()['datasets']
        error = urllib.error.HTTPError('https://api.openai.com/v1/models', 401, 'secret-not-logged', {}, None)
        with patch('backend.ai_connection.request_bytes', side_effect=error):
            response = self.connection.connect({'key': KEY})
        self.assertEqual(response['code'], 'http_401')
        self.assertEqual(self.repo.snapshot()['datasets'], before)
        self.assertNotIn('secret-not-logged', json.dumps(response))

    def test_reconnection_preserves_analysis_limits(self):
        limits = {'daily_call_limit': 4, 'max_articles_per_run': 2, 'max_input_chars': 6000,
                  'max_output_tokens': 900, 'article_text_chars': 700, 'enabled_tasks': ['extract']}
        self.repo.transact(lambda ds: ds.update(settings={'app': {'id': 'app', 'ai': limits}}))
        with patch('backend.ai_connection.request_bytes', return_value=b'{"data":[{"id":"gpt-6-luna"}]}'):
            self.assertTrue(self.connection.connect({'key': KEY})['connected'])
        profile = self.repo.snapshot()['datasets']['settings']['app']['ai']
        for name, value in limits.items():
            self.assertEqual(profile[name], value)

    def test_new_connection_uses_bounded_defaults(self):
        with patch('backend.ai_connection.request_bytes', return_value=b'{"data":[{"id":"gpt-6-luna"}]}'):
            self.connection.connect({'key': KEY})
        profile = self.repo.snapshot()['datasets']['settings']['app']['ai']
        for name, value in {'daily_call_limit': 10, 'max_articles_per_run': 3, 'max_input_chars': 8000,
                            'max_output_tokens': 1200, 'article_text_chars': 1200}.items():
            self.assertEqual(profile[name], value)
        self.assertEqual(profile['enabled_tasks'], ['extract', 'compare', 'briefing', 'classify', 'strategy'])

    def test_limits_changed_while_model_request_in_flight_are_preserved(self):
        def reply(*args, **kwargs):
            self.repo.transact(lambda ds: ds.setdefault('settings', {}).setdefault('app', {'id': 'app'}).update(
                ai={'daily_call_limit': 2, 'enabled_tasks': ['classify']}))
            return b'{"data":[{"id":"gpt-6-luna"}]}'
        with patch('backend.ai_connection.request_bytes', side_effect=reply):
            self.connection.connect({'key': KEY})
        profile = self.repo.snapshot()['datasets']['settings']['app']['ai']
        self.assertEqual(profile['daily_call_limit'], 2)
        self.assertEqual(profile['enabled_tasks'], ['classify'])

    def test_model_selection_requires_verified_list_and_no_arbitrary_fallback(self):
        with patch('backend.ai_connection.request_bytes', return_value=b'{"data":[{"id":"other-model"}]}'):
            response = self.connection.connect({'key': KEY})
            self.assertEqual(response['status'], 'model_required')
            self.assertEqual(response['model'], '')
            with self.assertRaisesRegex(ValueError, '모델 목록'):
                self.connection.connect({'key': KEY, 'model': 'unlisted-model'})

    def test_saved_credential_read_error_is_visible_without_details(self):
        self.vault.read.side_effect = ValueError('private-os-details')
        status = self.connection.status({'settings': {'app': {'ai': {'provider': 'openai', 'secret_ref': 'credential:openai'}}}})
        self.assertFalse(status['connected'])
        self.assertEqual(status['credential_error'], 'credential_unavailable')
        self.assertNotIn('private-os-details', json.dumps(status))

    def test_google_pagination_only_selected_host_and_supported_models(self):
        pages = [{'models': [{'name': 'models/embed', 'supportedGenerationMethods': ['embedContent']}], 'nextPageToken': 'opaque+token'},
                 {'models': [{'name': 'models/gemini-test', 'supportedGenerationMethods': ['generateContent']}]}]
        with patch('backend.ai_connection.request_bytes', side_effect=[json.dumps(p).encode() for p in pages]) as request:
            self.assertEqual(list_models('google', 'synthetic'), ['gemini-test'])
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.kwargs['allowed_hosts'], {'generativelanguage.googleapis.com'})
            self.assertNotIn('synthetic', call.args[0])
        self.assertIn('pageToken=opaque%2Btoken', request.call_args.args[0])

    def test_claude_pages_and_bounded_repeated_cursor(self):
        pages = [{'data': [{'id': 'claude-test-a'}], 'has_more': True, 'last_id': 'claude-test-a'},
                 {'data': [{'id': 'claude-test-b'}], 'has_more': False}]
        with patch('backend.ai_connection.request_bytes', side_effect=[json.dumps(p).encode() for p in pages]) as request:
            self.assertEqual(list_models('anthropic', 'synthetic'), ['claude-test-a', 'claude-test-b'])
            self.assertIn('after_id=claude-test-a', request.call_args.args[0])
        with patch('backend.ai_connection.request_bytes', return_value=json.dumps(pages[0]).encode()) as request:
            response = self.connection.connect({'provider': 'anthropic', 'key': 'sk-ant-' + 'synthetic-' * 4})
            self.assertEqual(response['code'], 'models_page_limit')
            self.assertEqual(request.call_count, 2)
            self.vault.write.assert_not_called()

    def test_credential_read_distinguishes_missing_and_policy_failure(self):
        api = Mock()
        api.CredReadW.return_value = False
        vault = WindowsVault('isolated-test')
        with patch.object(vault, '_api', return_value=(api, ctypes.c_int)):
            with patch('backend.credentials.ctypes.get_last_error', return_value=1168, create=True):
                self.assertIsNone(vault.read('openai'))
            with patch('backend.credentials.ctypes.get_last_error', return_value=5, create=True):
                with self.assertRaisesRegex(ValueError, '보안 정책'):
                    vault.read('openai')

    def test_fresh_allowlisted_checkout_collects_without_private_configs_or_data(self):
        exported = Path(self.temp.name) / 'exported'
        exported.mkdir()
        policy = json.loads((ROOT / 'config/publication.json').read_text(encoding='utf-8'))
        # Copy exactly allowlisted public runtime sources, never operational data.
        for folder in policy['include_directories']:
            if folder == 'backend':
                shutil.copytree(ROOT / folder, exported / folder, ignore=shutil.ignore_patterns('__pycache__'))
        for filename in policy['include_files']:
            if filename.startswith('config/'):
                target = exported / filename
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(ROOT / filename, target)
        self.assertFalse((exported / 'config/brainstorm_decisions.json').exists())
        self.assertFalse((exported / 'data').exists())
        script = '''from pathlib import Path
from backend.collector import collect_news
from backend.repository import JsonRepository
import json
root = Path.cwd()
job = collect_news(JsonRepository(root / 'isolated-store'), root,
    {'period':'1w', 'source_ids':['INT-M02'], 'max_requests':1}, fetcher=lambda _: RAW)
assert job['status'] == 'completed', job['status']
assert job['stop_reason'] == 'queue_exhausted'
assert job['new_articles'] == 1
print('fresh-public-collector-ok')
'''
        script = 'RAW = ' + repr(rss()) + '\n' + script
        result = subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, ' + repr(str(exported)) + ');\n' + script],
                                cwd=exported, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn('fresh-public-collector-ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
