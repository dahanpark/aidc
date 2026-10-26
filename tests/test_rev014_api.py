"""REV014 isolated loopback HTTP contracts; synthetic public metadata + mocked inference."""
import copy
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from backend.server import AtlasApplication, make_server
from backend import strategy

ROOT = Path(__file__).resolve().parents[1]


class Rev014ApiTests(unittest.TestCase):
    def setUp(self):
        # Keep disposable snapshots within the authorized workspace on Windows.
        (ROOT / 'runtime').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='rev014-api-', dir=ROOT / 'runtime')
        self.root = Path(self.temp.name)
        for folder in ('fixtures', 'config'):
            shutil.copytree(ROOT / folder, self.root / folder)
        (self.root / 'frontend').mkdir()
        (self.root / 'frontend' / 'index.html').write_text('<html>isolated</html>', encoding='utf-8')
        self.app = AtlasApplication(self.root)
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.title = '삼성물산 국내 AI 데이터센터 검토 공개 기사'
        def seed(ds):
            ds.setdefault('articles', {})['rev014-public'] = {
                'id': 'rev014-public', 'title': self.title, 'mode': 'live_metadata',
                'feed_excerpt': '삼성물산은 국내 AI 데이터센터 건설을 검토한다.',
                'published_at': '2026-10-26T00:00:00Z', 'scope': 'kr-ai',
                'url': 'https://example.com/public', 'note': 'PRIVATE-NOTE', 'body': 'PRIVATE-BODY'}
            ds.setdefault('settings', {}).setdefault('app', {}).setdefault('ai', {}).update({
                'provider': 'mock', 'model': 'synthetic', 'enabled': True,
                'enabled_tasks': ['extract', 'compare', 'briefing', 'classify', 'strategy'],
                'max_articles_per_run': 3, 'max_input_chars': 8000, 'max_output_tokens': 1200,
                'article_text_chars': 1200, 'daily_call_limit': 10})
        self.app.repo.transact(seed)

    def tearDown(self):
        self.app.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, payload=None):
        headers = {'Content-Type': 'application/json', 'X-Atlas-Token': self.app.csrf}
        request = urllib.request.Request(self.base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def json_request(self, path, payload=None):
        status, raw, _ = self.request(path, payload)
        return status, json.loads(raw)

    def test_settings_six_fields_and_invalid_values_are_atomic(self):
        valid = {'max_articles_per_run': 3, 'daily_call_limit': 10, 'max_input_chars': 8000,
                 'max_output_tokens': 1200, 'article_text_chars': 1200,
                 'enabled_tasks': ['extract', 'compare', 'briefing', 'classify', 'strategy']}
        self.assertEqual(self.request('/api/settings', {'ai_limits': valid})[0], 200)
        ai = self.app.repo.snapshot()['datasets']['settings']['app']['ai']
        self.assertEqual({key: ai[key] for key in valid}, valid)
        bounds = {'max_articles_per_run': (1,20), 'daily_call_limit': (1,500), 'max_input_chars': (4000,40000), 'max_output_tokens': (300,4000), 'article_text_chars': (200,2400)}
        malformed = [[], None, {'unknown': 3}, {'enabled_tasks': []}, {'enabled_tasks': ['invented']}, {'enabled_tasks': 'strategy'}, {'enabled_tasks': [False]}]
        for key, (lo, hi) in bounds.items():
            malformed.extend({key: value} for value in [lo-1, hi+1, True, '3', 3.5])
        before = self.app.repo.snapshot()
        for limits in malformed:
            with self.subTest(limits=limits):
                self.assertEqual(self.request('/api/settings', {'ai_limits': limits})[0], 400)
                self.assertEqual(self.app.repo.snapshot(), before)

    def test_strategy_get_and_report_are_virtual_read_only_and_public(self):
        before = self.app.repo.snapshot()
        status, reply = self.json_request('/api/strategy?scope=all&period=all')
        self.assertEqual(status, 200)
        board = reply['data']['active_board']
        self.assertEqual(len(board['companies']), 7)
        self.assertEqual(len(board['rows']), 11)
        self.assertEqual(board['id'], 'construction')
        self.assertNotIn('construction', before['datasets'].get('strategy_boards', {}))
        status, raw, headers = self.request('/api/strategy/report?scope=all&period=all')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn('A3', raw.decode())
        self.assertNotIn(b'PRIVATE-', raw)
        self.assertEqual(self.app.repo.snapshot(), before)

    def test_strategy_save_append_preserves_default_and_rejects_deletion(self):
        board = strategy.default_board()
        board['companies'].append({'id':'new-co','name':'추가 회사','aliases':['추가사']})
        board['rows'].append({'id':'new-row','label':'추가 행'})
        self.assertEqual(self.request('/api/strategy/save', board)[0], 200)
        self.assertEqual(len(self.app.repo.snapshot()['datasets']['strategy_boards']['construction']['companies']), 8)
        before = self.app.repo.snapshot()
        self.assertEqual(self.request('/api/strategy/save', strategy.default_board())[0], 400)
        self.assertEqual(self.app.repo.snapshot(), before)
        another = copy.deepcopy(board); another.update(id='owners',title='발주처')
        self.assertEqual(self.request('/api/strategy/save', another)[0], 200)
        self.assertEqual(self.json_request('/api/strategy?board_id=owners')[1]['data']['active_board']['title'], '발주처')

    def test_strategy_preview_consent_single_mocked_call_and_cached_result(self):
        payload = {'board_id':'construction','company_id':'samsung-cnt','row_ids':['strategy'],'article_ids':['rev014-public']}
        before = self.app.repo.snapshot()
        with patch('backend.ai_analysis.infer') as infer:
            status, reply = self.json_request('/api/strategy/preview', payload)
            self.assertEqual(status, 200)
            self.assertEqual(reply['data']['articles'][0]['title'], self.title)
            self.assertNotIn('PRIVATE-', json.dumps(reply))
            self.assertFalse(reply['data']['inference_called'])
            self.assertEqual(self.request('/api/strategy/analyse', payload)[0], 400)
            infer.assert_not_called()
        self.assertEqual(self.app.repo.snapshot(), before)
        result = {'cells':[{'row_id':'strategy','paragraphs':[{'text':'건설 검토 단계의 근거 후보다.','quote':self.title,'article_id':'rev014-public'}]}]}
        with patch.object(self.app.ai, 'status', return_value={'connected':True}), patch.object(self.app.ai, 'credential', return_value='SYNTHETIC-ONLY'), patch('backend.ai_analysis.infer', return_value=(result, {'input_tokens':12,'output_tokens':8})) as infer:
            status, reply = self.json_request('/api/strategy/analyse', {**payload,'consent_public_metadata':True})
            self.assertEqual(status, 200)
            self.assertEqual(reply['data']['status'], 'completed')
            status, cached = self.json_request('/api/strategy/analyse', {**payload,'consent_public_metadata':True})
            self.assertEqual(status, 200)
            self.assertEqual(cached['data']['status'], 'cached')
            infer.assert_called_once()
        ds = self.app.repo.snapshot()['datasets']
        self.assertEqual(len(ds['strategy_summaries']),1)
        self.assertEqual(len(ds['ai_runs']),1)
        for dataset in ('articles','projects','relationships','read_states','news_read_states'):
            self.assertEqual(ds.get(dataset), before['datasets'].get(dataset))
        self.assertNotIn('SYNTHETIC-ONLY',json.dumps(ds))

    def test_ai_preview_uses_public_metadata_and_does_not_call_or_write(self):
        before = self.app.repo.snapshot()
        with patch('backend.ai_analysis.infer') as infer:
            status, reply = self.json_request('/api/ai/preview', {'article_ids':['rev014-public']})
            self.assertEqual(status,200)
            self.assertEqual(reply['data']['articles'][0]['id'],'rev014-public')
            self.assertIn('max_output_tokens',reply['data'])
            self.assertNotIn('PRIVATE-',json.dumps(reply))
            for invalid in ([], ['missing'], 'rev014-public', [False]):
                self.assertEqual(self.request('/api/ai/preview',{'article_ids':invalid})[0],400)
            infer.assert_not_called()
        self.assertEqual(self.app.repo.snapshot(),before)

    def strategy_summary(self):
        return {'id':'rev014-summary','board_id':'construction','company_id':'samsung-cnt',
                'row_id':'strategy','article_ids':['rev014-public'],
                'paragraphs':[{'text':'공개 검토 근거 후보','quote':self.title,'article_id':'rev014-public'}]}

    def test_repository_strategy_references_reject_atomically(self):
        before = self.app.repo.snapshot()
        malformed = []
        for field in ('board_id','company_id','row_id'):
            summary = self.strategy_summary(); summary[field] = 'missing'
            malformed.append(summary)
        summary = self.strategy_summary(); summary['article_ids'] = ['missing']; summary['paragraphs'][0]['article_id'] = 'missing'
        malformed.append(summary)
        summary = self.strategy_summary(); summary['paragraphs'][0]['article_id'] = 'not-in-summary-sources'
        malformed.append(summary)
        summary = self.strategy_summary(); summary['paragraphs'] = ['malformed paragraph']
        malformed.append(summary)
        for summary in malformed:
            with self.subTest(summary=summary):
                with self.assertRaises(ValueError):
                    self.app.repo.transact(lambda ds: ds.setdefault('strategy_summaries',{}).update({summary['id']:summary}))
                self.assertEqual(self.app.repo.snapshot(),before)
        bad_board = strategy.default_board(); bad_board['companies'] = []
        with self.assertRaises(ValueError):
            self.app.repo.transact(lambda ds: ds.setdefault('strategy_boards',{}).update({'construction':bad_board}))
        self.assertEqual(self.app.repo.snapshot(),before)

    def test_valid_strategy_summary_backup_restore_preserves_evidence(self):
        summary = self.strategy_summary()
        board = strategy.default_board()
        board['companies'].append({'id':'additional','name':'추가 회사','aliases':[]})
        def save(ds):
            strategy.save_board(ds,board)
            ds.setdefault('strategy_summaries',{})[summary['id']] = copy.deepcopy(summary)
        self.app.repo.transact(save)
        expected = self.app.repo.snapshot()['datasets']
        status, reply = self.json_request('/api/backup',{})
        self.assertEqual(status,200)
        filename = reply['data']['filename']
        self.app.repo.transact(lambda ds: ds['strategy_summaries'][summary['id']]['paragraphs'][0].update(text='후속 변경'))
        self.assertEqual(self.request('/api/restore',{'filename':filename})[0],200)
        restored = self.app.repo.snapshot()['datasets']
        self.assertEqual(restored['strategy_summaries'],expected['strategy_summaries'])
        self.assertEqual(restored['strategy_boards'],expected['strategy_boards'])
        self.assertEqual(restored['articles'],expected['articles'])
        self.assertEqual(restored.get('read_states'),expected.get('read_states'))


if __name__ == '__main__':
    unittest.main()
