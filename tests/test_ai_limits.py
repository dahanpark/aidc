"""Bounded provider payloads and explicit task permissions; mocked calls only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.ai_analysis import (SCHEMA, SYSTEM, analyse, infer, input_chars,
                                 prepare_analysis, public_article, validate_result, workspace)
from backend.ai_connection import AIConnection
from backend.repository import JsonRepository


class Vault:
    def read(self, provider): return 'synthetic-test-key'
    def write(self, provider, value): pass
    def delete(self, provider): pass


def article(ident='a', long=False):
    return {'id': ident, 'title': 'TestCo Seoul AI data center expansion',
            'feed_excerpt': ('Public metadata sample ' * 180) if long else 'TestCo expands Seoul data center',
            'mode': 'live_metadata', 'publisher': 'Test publisher', 'published_at': '2026-10-26T00:00:00Z',
            'note': 'PRIVATE-DO-NOT-TRANSFER'}


def result():
    return {'extractions': [], 'matches': [], 'briefing': []}


class AILimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JsonRepository(Path(self.temp.name) / 'isolated')
        self.connection = AIConnection(self.repo, 'isolated-limits', Vault())
        self.profile = {'provider': 'openai', 'model': 'gpt-test', 'enabled': True,
                        'verified_at': '2026-10-26T00:00:00Z', 'secret_ref': 'credential:openai'}
        self.repo.transact(lambda ds: ds.update(settings={'app': {'id': 'app', 'ai': self.profile}},
                                               articles={ident: article(ident, True) for ident in ['a', 'b', 'c', 'd']}))

    def test_public_metadata_default_limit_and_private_exclusion(self):
        public = public_article(article(long=True))
        self.assertEqual(len(public['text']), 1200)
        self.assertNotIn('PRIVATE', json.dumps(public))
        self.assertEqual(len(public_article(article(long=True), 700)['text']), 700)

    def test_total_counts_system_schema_and_serialized_sample(self):
        ds = self.repo.snapshot()['datasets']
        prepared = prepare_analysis(ds, self.profile, ['a', 'b', 'c'])
        total = input_chars(prepared['system'], SCHEMA, prepared['input_data'])
        self.assertEqual(total, prepared['preview']['input_chars'])
        self.assertLessEqual(total, 8000)
        self.assertLessEqual(max(len(a['text']) for a in prepared['input_data']['articles']), 1200)
        self.assertNotIn('PRIVATE', json.dumps(prepared))

    def test_targets_shrink_before_article_text(self):
        ds = self.repo.snapshot()['datasets']
        targets = [{'id': str(i), 'name': 'Seoul data center ' * 90} for i in range(5)]
        with patch('backend.ai_analysis.shortlist', return_value=copy.deepcopy(targets)):
            prepared = prepare_analysis(ds, self.profile, ['a'])
        self.assertGreater(prepared['preview']['removed_targets'], 0)
        self.assertEqual(len(prepared['input_data']['articles'][0]['text']), 1200)

    def test_text_shortens_to_budget_and_keeps_minimum_and_all_articles(self):
        ds = self.repo.snapshot()['datasets']
        base = prepare_analysis(ds, self.profile, ['a', 'b', 'c'])
        overhead = input_chars(base['system'], SCHEMA, {'articles': [dict(a, text='') for a in base['input_data']['articles']], 'targets': []})
        cap = overhead + 1050
        prepared = prepare_analysis(ds, {**self.profile, 'max_input_chars': cap}, ['a', 'b', 'c'])
        self.assertTrue(prepared['preview']['truncated'])
        self.assertLessEqual(prepared['preview']['input_chars'], cap)
        self.assertEqual(len(prepared['input_data']['articles']), 3)
        self.assertTrue(all(200 <= len(a['text']) < 1200 for a in prepared['input_data']['articles']))

    def test_impossible_budget_refuses_before_paid_request_or_ledger(self):
        self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(max_input_chars=200))
        with patch('backend.ai_analysis.infer') as call:
            with self.assertRaisesRegex(ValueError, '유료 호출하지 않았습니다'):
                analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            call.assert_not_called()
        self.assertFalse(self.repo.snapshot()['datasets'].get('ai_runs'))

    def test_default_three_article_cap_and_explicit_override(self):
        ds = self.repo.snapshot()['datasets']
        with self.assertRaisesRegex(ValueError, '기사 한도'):
            prepare_analysis(ds, self.profile, ['a', 'b', 'c', 'd'])
        prepared = prepare_analysis(ds, {**self.profile, 'max_articles_per_run': 4}, ['a', 'b', 'c', 'd'])
        self.assertEqual(len(prepared['input_data']['articles']), 4)

    def test_tasks_are_in_system_and_disabled_outputs_rejected(self):
        ds = self.repo.snapshot()['datasets']
        prepared = prepare_analysis(ds, {**self.profile, 'enabled_tasks': ['extract', 'strategy']}, ['a'])
        self.assertEqual(prepared['enabled_tasks'], ['extract'])
        self.assertIn('matches는 허용하지 않으므로 반드시 빈 배열', prepared['system'])
        self.assertIn('briefing는 허용하지 않으므로 반드시 빈 배열', prepared['system'])
        value = result()
        value['briefing'] = [{'kind': 'check', 'text': 'check', 'article_ids': ['a']}]
        with self.assertRaisesRegex(ValueError, '허용하지 않은'):
            validate_result(value, prepared['input_data']['articles'], [], ['extract'])
        with self.assertRaisesRegex(ValueError, '허용할 작업'):
            prepare_analysis(ds, {**self.profile, 'enabled_tasks': ['strategy']}, ['a'])

    def test_disabled_result_fails_once_counts_usage_and_failed_budget(self):
        self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(enabled_tasks=['extract'], daily_call_limit=1))
        value = result()
        value['briefing'] = [{'kind': 'check', 'text': 'check', 'article_ids': ['a']}]
        with patch('backend.ai_analysis.infer', return_value=(value, {'output_tokens': 25})) as call:
            response = analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(response['status'], 'failed')
            with self.assertRaisesRegex(ValueError, '오늘 AI 호출 한도'):
                analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            call.assert_called_once()
        run = self.repo.snapshot()['datasets']['ai_runs'][response['run_id']]
        self.assertEqual(run['usage']['output_tokens'], 25)
        self.assertNotIn('result', run)

    def test_default_daily_budget_counts_all_tasks(self):
        from backend.repository import now
        self.repo.transact(lambda ds: ds.update(ai_runs={str(i): {'id': str(i), 'created_at': now(), 'task': 'strategy', 'status': 'failed'} for i in range(10)}))
        with patch('backend.ai_analysis.infer') as call:
            with self.assertRaisesRegex(ValueError, '오늘 AI 호출 한도'):
                analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            call.assert_not_called()

    def test_compressed_input_cache_and_workspace_source_comparison(self):
        self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(max_input_chars=5000))
        request = {'article_ids': ['a', 'b', 'c'], 'consent_public_metadata': True}
        with patch('backend.ai_analysis.infer', return_value=(result(), {})) as call:
            first = analyse(self.connection, request)
            second = analyse(self.connection, request)
            self.assertEqual((first['status'], second['status']), ('completed', 'cached'))
            call.assert_called_once()
        ds = self.repo.snapshot()['datasets']
        self.assertFalse(workspace(ds, request['article_ids'])['source_changed'])
        self.repo.transact(lambda ds: ds['articles']['a'].update(title='Changed public headline'))
        self.assertTrue(workspace(self.repo.snapshot()['datasets'], request['article_ids'])['source_changed'])

    def test_workspace_hides_other_task_runs_and_keeps_total_usage(self):
        from backend.repository import now
        ds = {'ai_runs': {task: {'id': task, 'task': task, 'status': 'completed', 'article_ids': ['a'], 'created_at': now()}
                          for task in ('strategy', 'classify')}}
        view = workspace(ds, ['a'])
        self.assertIsNone(view['latest'])
        self.assertIsNone(view['last_attempt'])
        self.assertEqual(view['today_calls'], 2)

    def test_all_providers_honor_output_limit_and_custom_schema_system(self):
        schema = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
        cases = [('openai', {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': '{}'}]}]}, 'max_output_tokens'),
                 ('anthropic', {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'name': 'custom', 'input': {}}]}, 'max_tokens'),
                 ('google', {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{}'}]}}]}, 'maxOutputTokens')]
        for provider, response, field in cases:
            for limit in (None, 700):
                profile = {'provider': provider, 'model': 'test-model'}
                if limit is not None: profile['max_output_tokens'] = limit
                with self.subTest(provider=provider, limit=limit), patch('backend.ai_analysis.request_bytes', return_value=json.dumps(response).encode()) as call:
                    output, usage = infer(profile, 'synthetic', {'articles': []}, schema=schema, system='CUSTOM-SYSTEM', schema_name='custom')
                    body = json.loads(call.call_args.kwargs['data'])
                    config = body['generationConfig'] if provider == 'google' else body
                    self.assertEqual(config[field], limit or 1200)
                    self.assertIn('CUSTOM-SYSTEM', json.dumps(body))
                    self.assertEqual(output, {})
                    if provider == 'anthropic': self.assertEqual(body['tools'][0]['input_schema'], schema)
                    if provider == 'openai': self.assertEqual(body['text']['format']['schema'], schema)


class AIClassificationTests(unittest.TestCase):
    setUp = AILimitTests.setUp
    def classifications(self, scope='kr-ai', quote='TestCo Seoul AI data center'):
        return {'classifications': [{'article_id': 'a', 'scope': scope,
                                    'reason': '공개 메타데이터에 명시된 후보', 'quote': quote}]}

    def test_classification_preview_contains_exact_sample_and_no_secrets(self):
        from backend.ai_classification import preview
        with patch('backend.ai_classification.infer') as call:
            sample = preview(self.connection, {'article_ids': ['a']})
            call.assert_not_called()
        self.assertEqual(sample['task'], 'classify')
        self.assertFalse(sample['inference_called'])
        self.assertLessEqual(sample['input_chars'], 8000)
        self.assertNotIn('PRIVATE', json.dumps(sample))
        self.assertFalse(self.repo.snapshot()['datasets'].get('ai_runs'))

    def test_classification_writes_candidate_run_without_mutating_article_and_caches(self):
        from backend.ai_classification import analyse as classify, preview
        before = self.repo.snapshot()['datasets']['articles']
        sample = preview(self.connection, {'article_ids': ['a']})
        with patch('backend.ai_classification.infer', return_value=(self.classifications(), {'input_tokens': 12})) as call:
            response = classify(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(response['status'], 'completed')
            self.assertEqual(call.call_args.args[2]['articles'], sample['articles'])
            again = classify(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(again['status'], 'cached')
            call.assert_called_once()
        after = self.repo.snapshot()['datasets']
        self.assertEqual(after['articles'], before)
        run = after['ai_runs'][response['run_id']]
        self.assertEqual(run['task'], 'classify')
        self.assertFalse(run['auto_apply'])
        self.assertEqual(run['result']['classifications'][0]['validation_state'], 'unverified_ai_classification_candidate')

    def test_classification_invalid_quote_fails_and_consumes_shared_budget(self):
        from backend.ai_classification import analyse as classify
        self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(daily_call_limit=1))
        with patch('backend.ai_classification.infer', return_value=(self.classifications(quote='not in public article'), {'input_tokens': 5})) as call:
            response = classify(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.assertEqual(response['status'], 'failed')
            call.assert_called_once()
        with patch('backend.ai_analysis.infer') as general:
            with self.assertRaisesRegex(ValueError, '오늘 AI 호출 한도'):
                analyse(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            general.assert_not_called()

    def test_unresolved_can_omit_quote_but_resolved_must_quote(self):
        from backend.ai_classification import validate_result as validate_classification
        sample = [public_article(article())]
        self.assertEqual(validate_classification(self.classifications('unresolved', ''), sample)['classifications'][0]['scope'], 'unresolved')
        for scope, quote in [('kr-dc', ''), ('kr-ai', 'AI'), ('global-ai', 'invented exact quote')]:
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                validate_classification(self.classifications(scope, quote), sample)

    def test_classification_rejects_wrong_article_duplicate_and_scope(self):
        from backend.ai_classification import validate_result as validate_classification
        sample = [public_article(article())]
        bad = self.classifications()
        bad['classifications'][0]['article_id'] = 'other'
        duplicate = self.classifications()
        duplicate['classifications'] *= 2
        for value in (bad, duplicate, self.classifications(scope='guessed')):
            with self.assertRaises(ValueError): validate_classification(value, sample)

    def test_classification_permission_consent_private_and_input_limits_before_call(self):
        from backend.ai_classification import analyse as classify
        with patch('backend.ai_classification.infer') as call:
            with self.assertRaises(ValueError): classify(self.connection, {'article_ids': ['a']})
            self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(enabled_tasks=['extract']))
            with self.assertRaises(ValueError): classify(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(enabled_tasks=['classify'], max_input_chars=200))
            with self.assertRaisesRegex(ValueError, '유료 호출하지 않았습니다'):
                classify(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(max_input_chars=8000))
            self.repo.transact(lambda ds: ds['articles']['a'].update(visibility='private'))
            with self.assertRaises(ValueError): classify(self.connection, {'article_ids': ['a'], 'consent_public_metadata': True})
            call.assert_not_called()
        self.assertFalse(self.repo.snapshot()['datasets'].get('ai_runs'))


if __name__ == '__main__': unittest.main()
