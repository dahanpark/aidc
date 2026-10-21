"""Mocked providers; no paid inference or personal credentials are used."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from backend.ai_connection import AIConnection, infer_provider
from backend.ai_analysis import analyse, validate_result, workspace, decide_match, infer, shortlist
from backend.credentials import env_name, delete_environment
from backend.repository import JsonRepository


class Vault:
    def __init__(self): self.values = {}
    def read(self, provider): return self.values.get(provider)
    def write(self, provider, key): self.values[provider] = key
    def delete(self, provider): self.values.pop(provider, None)


KEY = 'sk-proj-' + 'synthetic-test-key-' * 3


def result():
    return {'extractions': [{'article_id': 'a', 'project_name': '서울 AI 데이터센터', 'company_name': '테스트사',
                            'role': 'operator', 'kind': 'participation', 'value': '운영 계획',
                            'quote': '테스트사 서울 AI 데이터센터 운영 계획'}],
            'matches': [], 'briefing': [{'kind': 'check', 'text': '운영 계획의 실행 여부 확인 필요', 'article_ids': ['a']}]}


class AITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JsonRepository(self.temp.name)
        self.vault = Vault()
        self.connection = AIConnection(self.repo, 'unit-test', self.vault)
        self.repo.transact(lambda ds: ds.update(articles={'a': {'id': 'a', 'title': '테스트사 서울 AI 데이터센터 운영 계획',
                        'mode': 'live_metadata', 'published_at': '2026-10-21T00:00:00Z', 'publisher': '테스트매체',
                        'note': 'PRIVATE-SHOULD-NOT-TRANSFER', 'evidence_excerpt': 'PRIVATE-MANUAL-EXCERPT'}},
                        bookmarks={'a': {'id': 'a', 'article_id': 'a', 'note': 'PRIVATE-BOOKMARK'}}))

    def connect(self):
        with patch('backend.ai_connection.request_bytes', return_value=json.dumps({'data': [{'id': 'gpt-6-luna'}]}).encode()) as request:
            response = self.connection.connect({'key': KEY})
            self.assertTrue(response['connected'])
            self.assertEqual(request.call_args.args[0], 'https://api.openai.com/v1/models')
            self.assertNotIn('data', request.call_args.kwargs)
        return response

    def test_ambiguous_key_does_not_probe_any_provider(self):
        with patch('backend.ai_connection.request_bytes') as request:
            self.assertEqual(self.connection.connect({'key': 'sk-' + 'x' * 30})['status'], 'provider_required')
            request.assert_not_called()
        self.assertEqual(infer_provider('sk-ant-secret'), 'anthropic')
        self.assertEqual(infer_provider('AIza-secret'), 'google')

    def test_known_provider_mismatch_never_sends_key(self):
        with patch('backend.ai_connection.request_bytes') as request:
            with self.assertRaises(ValueError): self.connection.connect({'key': KEY, 'provider': 'google'})
            request.assert_not_called()

    def test_key_stays_out_of_json_disconnect_forget(self):
        self.connect()
        self.assertNotIn(KEY, json.dumps(self.repo.snapshot()))
        self.connection.disconnect()
        self.assertFalse(self.connection.status(self.repo.snapshot()['datasets'])['connected'])
        self.assertEqual(self.vault.read('openai'), KEY)
        self.connection.disconnect(forget=True)
        self.assertIsNone(self.vault.read('openai'))
        self.assertFalse(self.connection.status(self.repo.snapshot()['datasets'])['credential_present'])

    def test_analysis_explicit_scope_cache_and_private_fields(self):
        self.connect()
        before = self.repo.snapshot()['datasets']
        with patch('backend.ai_analysis.infer', return_value=(result(), {'input_tokens': 20, 'output_tokens': 10})) as provider:
            with self.assertRaises(ValueError): analyse(self.connection, {'article_ids': ['a']})
            provider.assert_not_called()
            first = analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(first['status'], 'completed')
            self.assertNotIn('PRIVATE-', json.dumps(provider.call_args.args[2]))
            second = analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(second['status'], 'cached')
            self.assertEqual(provider.call_count, 1)
        after = self.repo.snapshot()['datasets']
        self.assertEqual(after['articles'], before['articles'])
        self.assertEqual(after['bookmarks'], before['bookmarks'])
        self.assertNotIn(KEY, json.dumps(after))
        self.assertIsNotNone(workspace(after, ['a'])['latest'])
        self.assertIsNone(workspace(after, [])['latest'])
        # A changed source is not a cache hit.
        self.repo.transact(lambda ds: ds['articles']['a'].update(title='테스트사 서울 AI 데이터센터 운영 계획 · 갱신'))
        with patch('backend.ai_analysis.infer', return_value=(result(), {})) as provider:
            self.assertEqual(analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})['status'], 'completed')
            provider.assert_called_once()

    def test_bad_evidence_fails_without_fabrication_or_automatic_retry(self):
        self.connect()
        invalid = result()
        invalid['extractions'][0]['quote'] = '입력에 없는 근거'
        with patch('backend.ai_analysis.infer', return_value=(invalid, {'input_tokens': 30})) as provider:
            response = analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(response['status'], 'failed')
            provider.assert_called_once()
        run = self.repo.snapshot()['datasets']['ai_runs'][response['run_id']]
        self.assertNotIn('result', run)
        self.assertEqual(run['usage']['input_tokens'], 30)
        self.assertEqual(self.repo.snapshot()['datasets'].get('projects', {}), {})

    def test_private_or_fixture_rejected_before_provider(self):
        self.connect()
        self.repo.transact(lambda ds: ds['articles']['a'].update(mode='manual'))
        with patch('backend.ai_analysis.infer') as provider:
            with self.assertRaises(ValueError): analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            provider.assert_not_called()

    def test_daily_limit_includes_failed_attempts(self):
        self.connect()
        self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(daily_call_limit=1))
        with patch('backend.ai_analysis.infer', side_effect=OSError('PRIVATE-KEY-ERROR')) as provider:
            analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            with self.assertRaises(ValueError): analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(provider.call_count, 1)
        self.assertNotIn('PRIVATE-KEY-ERROR', json.dumps(self.repo.snapshot()))

    def test_same_project_confirmation_is_reversible_candidate_not_merge(self):
        self.repo.transact(lambda ds: ds.update(ai_runs={'run': {'id': 'run', 'status': 'completed',
            'result': {'matches': [{'id': 'match'}]}}}))
        for decision in ('accepted_candidate', 'rejected', 'pending'):
            self.assertFalse(decide_match(self.repo, {'run_id': 'run', 'match_id': 'match', 'decision': decision})['merged'])
        record = self.repo.snapshot()['datasets']['ai_match_decisions']['match']
        self.assertEqual(len(record['history']), 2)
        self.assertEqual(self.repo.snapshot()['datasets'].get('projects', {}), {})

    def test_target_and_briefing_ids_require_input_evidence(self):
        value = result()
        value['briefing'][0]['article_ids'] = ['not-in-input']
        with self.assertRaises(ValueError): validate_result(value, [{'id': 'a', 'text': 'テスト'}], [])

    def test_environment_deletion_is_app_scoped(self):
        for reference in ('env:PATH', 'env:OPENAI_API_KEY', '.env', 'env:ATLAS_AI_UNKNOWN_KEY'):
            with self.assertRaises(ValueError): env_name(reference)
        # No Windows user environment is touched by this test.
        with patch('backend.credentials.os.name', 'posix'), patch.dict(os.environ, {'ATLAS_AI_OPENAI_KEY': 'unit-only'}):
            deleted = delete_environment('env:ATLAS_AI_OPENAI_KEY')
            self.assertTrue(deleted['process_variable_deleted'])
            self.assertFalse(deleted['provider_key_revoked'])

    def test_provider_protocols_and_usage_are_mocked(self):
        values = [('openai', {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(result())}]}], 'usage': {'input_tokens': 12}}, 'gpt-6-luna'),
                  ('anthropic', {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'name': 'atlas_analysis', 'input': result()}], 'usage': {'input_tokens': 13}}, 'claude-haiku-5-5'),
                  ('google', {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(result())}]}}], 'usageMetadata': {'promptTokenCount': 14}}, 'gemini-3.5-flash-lite')]
        for provider, raw, model in values:
            with self.subTest(provider=provider), patch('backend.ai_analysis.request_bytes', return_value=json.dumps(raw).encode()) as request:
                output, usage = infer({'provider': provider, 'model': model}, KEY, {'articles': []})
                self.assertEqual(output, result())
                self.assertTrue(usage)
                self.assertNotIn(KEY, request.call_args.args[0])
                self.assertEqual(request.call_args.kwargs['method'], 'POST')

    def test_comparison_shortlist_deduplicates_mentions_without_merging_records(self):
        ds = {'articles': {'old': {'mode': 'live_metadata'}, 'other': {'mode': 'live_metadata'}},
              'project_mentions': {'m1': {'id': 'm1', 'article_id': 'old', 'name': '용인 테스트 AI 데이터센터'},
                                   'm2': {'id': 'm2', 'article_id': 'other', 'name': '용인 테스트 AI 데이터센터'}}}
        before = copy.deepcopy(ds)
        targets = shortlist(ds, [{'id': 'new', 'text': '용인 테스트 AI 데이터센터 확장'}])
        self.assertEqual(len(targets), 1)
        self.assertEqual(ds, before)

    def test_failed_os_delete_keeps_reference_disabled_for_retry(self):
        self.connect()
        with patch.object(self.vault, 'delete', side_effect=ValueError('OS deletion failed')):
            with self.assertRaises(ValueError): self.connection.disconnect(forget=True)
        profile = self.repo.snapshot()['datasets']['settings']['app']['ai']
        self.assertFalse(profile['enabled'])
        self.assertEqual(profile['secret_ref'], 'credential:openai')
        self.connection.disconnect(forget=True)
