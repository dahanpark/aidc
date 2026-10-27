import copy
import json
import subprocess
from pathlib import Path
import unittest
from backend import strategy


class StrategyEditingTests(unittest.TestCase):
    def test_browser_default_axes_match_backend_and_old_partial_sheet_is_read_only_restored(self):
        root=Path(__file__).resolve().parents[1]
        node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        if node.is_file():
            raw=subprocess.check_output([str(node),'-e',"process.stdout.write(JSON.stringify(require('./frontend/atlas_strategy.js').defaultBoard()))"],cwd=root)
            self.assertEqual(json.loads(raw),strategy.default_board())
        b=strategy.default_board();b['companies']=b['companies'][:1];b['rows']=b['rows'][:1]
        b['companies'][0]['name']='포스코E&C 사용자 표기';ds={'strategy_boards':{'construction':b}};before=copy.deepcopy(ds)
        restored=strategy.boards(ds)[0]
        self.assertEqual(len(restored['companies']),6);self.assertEqual(len(restored['rows']),9)
        self.assertEqual(restored['companies'][0]['name'],'포스코E&C 사용자 표기');self.assertEqual(before,ds)
    def setUp(self):
        self.ds={'articles':{'a':{'id':'a','mode':'live_metadata','title':'한화 건설부문 데이터센터 계획 검토',
                   'url':'https://example.test/a','published_at':'2026-10-27','publisher':'공개 출처'}}}
        self.payload={'company_id':'hanwha-construction','row_ids':['strategy'],'article_ids':['a']}

    def test_restored_presets_do_not_make_full_legacy_sheet_unsaveable(self):
        b=strategy.default_board()
        b['companies']=[{'id':f'custom-company-{i}','name':f'사용자 회사 {i}','aliases':[]} for i in range(40)]
        b['rows']=[{'id':f'custom-row-{i}','label':f'사용자 항목 {i}'} for i in range(30)]
        self.ds['strategy_boards']={'construction':b}
        restored=strategy.boards(self.ds)[0]
        self.assertEqual((len(restored['companies']),len(restored['rows'])),(46,39))
        saved=strategy.save_board(self.ds,restored)
        self.assertEqual(len(saved['companies']),46)
        self.assertEqual(len(saved['rows']),39)

    def store(self):
        p=strategy.prepare_analysis(self.ds,self.payload)
        strategy.validate_and_store(self.ds,p,{'cells':[{'row_id':'strategy','paragraphs':[{
            'text':'계획 검토 후보','quote':'한화 건설부문 데이터센터 계획 검토','article_id':'a'}]}]}, {'provider':'mock'})

    def test_default_user_axes_and_guidance_are_presets_not_fabricated_results(self):
        b=strategy.default_board()
        self.assertEqual(len(b['companies']),6);self.assertEqual(len(b['rows']),9)
        self.assertTrue(all(r['analysis_guidance'] for r in b['rows']))
        self.assertIn('3개',b['analysis_brief'])
        self.assertNotIn('5.8조',str(b));self.assertNotIn('strategy_summaries',self.ds)
        self.assertEqual([r['id'] for r in b['rows']][-2:],['notes','pc-subsidiary'])
        self.assertEqual([c['name'] for c in b['companies']],['포스코이앤씨','DL E&C','현대엔지니어링','SK에코플랜트','IPARK현대산업개발','한화 건설부문'])
        self.assertEqual([r['label'] for r in b['rows']],['조직 형태/현황','핵심전략','강점(차별화)','기술 인증 공법','건립실적(준공)','수주/시공/추진','향후계획','비고(전력단위 표기)','PC 자회사 여부'])
        self.assertIn('MVA',b['rows'][-2]['analysis_guidance'])
        self.assertIn('임의 환산',b['rows'][-2]['analysis_guidance'])

    def test_latest_axes_preserve_saved_extras_custom_instructions_and_old_definition(self):
        b=strategy.default_board();b['companies'][0]['name']='포스코E&C'
        b['companies'].append({'id':'samsung-cnt','name':'삼성물산','aliases':[]})
        b['rows'].extend([{'id':'dc-history','label':'주요 DC·AIDC 시공이력'}, {'id':'target-sites','label':'검토 중인 대상지'}])
        b['rows'][0]['label']='사용자 조직 항목';notes=next(r for r in b['rows'] if r['id']=='notes');notes['label']='비고'
        notes['analysis_guidance']='사용자가 설정한 기준'
        self.ds['strategy_boards']={'construction':b};before=copy.deepcopy(self.ds)
        current=strategy.boards(self.ds)[0]
        self.assertEqual(before,self.ds)
        self.assertEqual(current['companies'][-1]['id'],'samsung-cnt')
        self.assertEqual(current['rows'][0]['label'],'사용자 조직 항목')
        notes=next(r for r in current['rows'] if r['id']=='notes')
        self.assertEqual(notes['label'],'비고(전력단위 표기)')
        self.assertEqual(notes['analysis_guidance'],'사용자가 설정한 기준')
        saved=strategy.save_board(self.ds,current)
        self.assertEqual(saved['history'][-1]['definition']['companies'][0]['name'],'포스코E&C')
        self.assertIn('포스코E&C',saved['companies'][0]['aliases'])

    def test_old_virtual_axes_referenced_by_summary_remain_resolvable_without_writes(self):
        self.ds['strategy_summaries']={'old':{'board_id':'construction','company_id':'samsung-cnt','row_id':'target-sites'}}
        before=copy.deepcopy(self.ds);b=strategy.boards(self.ds)[0]
        self.assertEqual(before,self.ds)
        self.assertIn('samsung-cnt',[c['id'] for c in b['companies']])
        self.assertIn('target-sites',[r['id'] for r in b['rows']])
        self.assertNotIn('dc-history',[r['id'] for r in b['rows']])

    def test_edit_names_retains_ids_summaries_old_alias_and_history(self):
        self.store();before=copy.deepcopy(self.ds['strategy_summaries'])
        b=strategy.default_board();b['title']='건설사 전략 검토'
        b['companies'][-1]['name']='한화 건설부문 사용자 표기';b['rows'][1]['label']='핵심 추진 전략'
        saved=strategy.save_board(self.ds,b)
        self.assertEqual(before,self.ds['strategy_summaries'])
        self.assertEqual(saved['companies'][-1]['id'],'hanwha-construction')
        self.assertIn('한화 건설부문',saved['companies'][-1]['aliases'])
        self.assertEqual(saved['history'][0]['definition']['title'],'국내 DC.AIDC 전략 (건설사)')
        self.assertIn('a',strategy.workspace(self.ds)['company_articles']['hanwha-construction'])

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
