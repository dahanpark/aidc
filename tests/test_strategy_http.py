"""Strategy editing through an isolated local HTTP server, never the live store."""
import copy
import json
import unittest
from tests import test_api
from backend.repository import JsonRepository


class StrategyHttpTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    request = test_api.ApiTests.request

    def test_public_download_exports_do_not_require_private_product_definition(self):
        definition = self.root / 'config/product_charter.json'
        if definition.exists():
            definition.unlink()  # This is the isolated test copy only.
        before = self.app.repo.snapshot()['datasets']
        for kind in ('report', 'newsletter', 'csv', 'news-report', 'news-csv'):
            status, raw, _ = self.request('/api/export?kind=' + kind)
            self.assertEqual(status, 200, kind)
            self.assertTrue(raw)
        self.assertEqual(self.request('/api/export?kind=charter')[0], 404)
        self.assertEqual(before, self.app.repo.snapshot()['datasets'])

    def test_default_axes_add_edit_and_reopen_preserve_source_records(self):
        before = self.app.repo.snapshot()['datasets']
        status, raw, _ = self.request('/api/strategy')
        self.assertEqual(status, 200)
        board = json.loads(raw)['data']['active_board']
        self.assertEqual((len(board['companies']), len(board['rows'])), (6, 9))
        board['companies'].append({'id': 'added-company', 'name': '추가 건설사', 'aliases': []})
        board['rows'].append({'id': 'added-row', 'label': '추가 분석 항목', 'analysis_guidance': '공개 근거와 날짜를 연결한다.'})
        board['analysis_brief'] = '확정 사실과 계획을 구분해 최대 3단락으로 요약한다.'
        self.assertEqual(self.request('/api/strategy/save', board)[0], 200)
        other = copy.deepcopy(board)
        other.update(id='owners', title='발주처 전략')
        self.assertEqual(self.request('/api/strategy/save', other)[0], 200)
        status, raw, _ = self.request('/api/strategy?board_id=owners')
        self.assertEqual(status, 200)
        current = json.loads(raw)['data']['active_board']
        self.assertEqual(current['title'], '발주처 전략')
        self.assertEqual((len(current['companies']), len(current['rows'])), (7, 10))
        self.assertEqual(current['analysis_brief'], other['analysis_brief'])
        reopened = JsonRepository(self.app.repo.root).snapshot()['datasets']
        self.assertEqual(reopened['strategy_boards']['owners']['rows'][-1]['analysis_guidance'], '공개 근거와 날짜를 연결한다.')
        for key in ('articles', 'companies', 'projects', 'bookmarks', 'read_states', 'news_read_states'):
            self.assertEqual(before.get(key), reopened.get(key), key)
        status, raw, _ = self.request('/api/strategy/report?board_id=owners')
        self.assertEqual(status, 200)
        self.assertIn('A3 landscape', raw.decode())
        self.assertIn('추가 분석 항목', raw.decode())
