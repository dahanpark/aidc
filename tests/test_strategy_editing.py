import copy
import unittest
from backend import strategy


class StrategyEditingTests(unittest.TestCase):
    def setUp(self):
        self.ds={'articles':{'a':{'id':'a','mode':'live_metadata','title':'삼성물산 데이터센터 계획 검토',
                   'url':'https://example.test/a','published_at':'2026-10-27','publisher':'공개 출처'}}}
        self.payload={'company_id':'samsung-cnt','row_ids':['strategy'],'article_ids':['a']}

    def store(self):
        p=strategy.prepare_analysis(self.ds,self.payload)
        strategy.validate_and_store(self.ds,p,{'cells':[{'row_id':'strategy','paragraphs':[{
            'text':'계획 검토 후보','quote':'삼성물산 데이터센터 계획 검토','article_id':'a'}]}]}, {'provider':'mock'})

    def test_default_user_axes_and_guidance_are_presets_not_fabricated_results(self):
        b=strategy.default_board()
        self.assertEqual(len(b['companies']),7);self.assertEqual(len(b['rows']),11)
        self.assertTrue(all(r['analysis_guidance'] for r in b['rows']))
        self.assertIn('3개',b['analysis_brief'])
        self.assertNotIn('5.8조',str(b));self.assertNotIn('strategy_summaries',self.ds)
        self.assertEqual([r['id'] for r in b['rows']][-2:],['target-sites','pc-subsidiary'])

    def test_edit_names_retains_ids_summaries_old_alias_and_history(self):
        self.store();before=copy.deepcopy(self.ds['strategy_summaries'])
        b=strategy.default_board();b['title']='건설사 전략 검토'
        b['companies'][-1]['name']='삼성물산 건설부문';b['rows'][1]['label']='핵심 추진 전략'
        saved=strategy.save_board(self.ds,b)
        self.assertEqual(before,self.ds['strategy_summaries'])
        self.assertEqual(saved['companies'][-1]['id'],'samsung-cnt')
        self.assertIn('삼성물산',saved['companies'][-1]['aliases'])
        self.assertEqual(saved['history'][0]['definition']['title'],'국내 DC.AIDC 전략 (건설사)')
        self.assertIn('a',strategy.workspace(self.ds)['company_articles']['samsung-cnt'])

    def test_guidance_is_in_actual_preview_and_invalidates_old_summary(self):
        self.store();old=strategy.prepare_analysis(self.ds,self.payload)
        b=strategy.default_board();b['analysis_brief']='출처를 연결해 검토한다.';b['rows'][1]['analysis_guidance']='시장 협력을\n명시 근거로 점검한다.'
        strategy.save_board(self.ds,b);new=strategy.prepare_analysis(self.ds,self.payload)
        self.assertNotEqual(old['input_hash'],new['input_hash'])
        self.assertEqual(new['input_data']['analysis_brief'],b['analysis_brief'])
        self.assertEqual(new['input_data']['rows'][0]['analysis_guidance'],b['rows'][1]['analysis_guidance'])
        self.assertTrue(next(iter(strategy.workspace(self.ds)['summaries'].values()))['stale'])

    def test_legacy_defaults_fill_only_missing_fields_and_do_not_write(self):
        b=strategy.default_board();b.pop('analysis_brief')
        for r in b['rows']:r.pop('analysis_guidance')
        b['rows'][0]['analysis_guidance']='사용자 기준 보존';self.ds['strategy_boards']={'construction':b}
        before=copy.deepcopy(self.ds);current=strategy.boards(self.ds)[0]
        self.assertEqual(current['rows'][0]['analysis_guidance'],'사용자 기준 보존')
        self.assertTrue(current['rows'][1]['analysis_guidance']);self.assertTrue(current['analysis_brief'])
        self.assertEqual(before,self.ds)

    def test_invalid_guide_is_atomic_and_id_deletion_is_rejected(self):
        for mutate in [lambda b:b.update(analysis_brief='a'*1001),
                       lambda b:b['rows'][0].update(analysis_guidance='a'*601),
                       lambda b:b['rows'].pop()]:
            b=strategy.default_board();mutate(b);before=copy.deepcopy(self.ds)
            with self.assertRaises(ValueError):strategy.save_board(self.ds,b)
            self.assertEqual(before,self.ds)

    def test_repeated_save_does_not_repeat_edit_history(self):
        b=strategy.default_board();b['title']='편집한 표';saved=strategy.save_board(self.ds,b)
        n=len(saved['history']);saved['history']=[{'forged':True}]
        next_board=strategy.save_board(self.ds,saved)
        self.assertEqual(len(next_board['history']),n)
        self.assertNotIn('forged',str(next_board['history']))

    def test_custom_category_is_independent_and_report_uses_edited_axes(self):
        b=strategy.default_board();b['id']='owners';b['title']='발주처 전략';b['rows'][0]['label']='담당 조직'
        strategy.save_board(self.ds,b)
        self.assertEqual(strategy.boards(self.ds)[0]['title'],'발주처 전략')
        self.assertEqual(strategy._board(self.ds,'construction')['title'],'국내 DC.AIDC 전략 (건설사)')
        html=strategy.render_report(strategy.workspace(self.ds,board_id='owners'),self.ds['articles'],'2026-10-27')
        self.assertIn('발주처 전략',html);self.assertIn('담당 조직',html);self.assertIn('A3 landscape',html)
