"""Isolated JSON-only strategy contract tests. No provider or server calls."""
import copy
import unittest
from urllib.parse import urlunsplit
from backend import strategy


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.ds={'articles':{
            'a':{'id':'a','mode':'live_metadata','title':'삼성물산 데이터센터 계획 검토',
                 'feed_excerpt':'삼성물산은 데이터센터 사업을 검토 중이라고 밝혔다.',
                 'publisher':'공개 출처','published_at':'2026-10-26','url':'https://example.test/a',
                 'body':'SECRET_BODY','internal_note':'SECRET_NOTE','internal_links':['https://intranet.test']},
            'b':{'id':'b','mode':'live_metadata','title':'삼성 데이터센터 산업 기사','description':'삼성 그룹 정보'},
            'c':{'id':'c','mode':'live_metadata','visibility':'private','title':'삼성물산 비공개'},
            'd':{'id':'d','mode':'manual','title':'삼성물산 수동 비공개'},
            'e':{'id':'e','mode':'live_metadata','title':'DL이앤씨 공개 검토 기사'},
        },'projects':{'original':{'name':'원본 보존'}}}
        self.payload={'company_id':'samsung-cnt','row_ids':['strategy'],'article_ids':['a']}

    def prepared(self):
        return strategy.prepare_analysis(self.ds,self.payload)

    def result(self):
        return {'cells':[{'row_id':'strategy','paragraphs':[{'text':'계획 검토 후보다.',
               'quote':'삼성물산 데이터센터 계획 검토','article_id':'a'}]}]}

    def store(self):
        return strategy.validate_and_store(self.ds,self.prepared(),self.result(),
                    {'provider':'mock','model':'synthetic','usage':{'input_tokens':10,'secret':'SECRET','bool':True}})

    def test_defaults_and_read_purity(self):
        before=copy.deepcopy(self.ds); board=strategy.default_board(); ws=strategy.workspace(self.ds)
        self.assertEqual(board['id'],'construction');self.assertEqual(board['title'],'국내 DC.AIDC 전략 (건설사)')
        self.assertEqual(len(board['companies']),7);self.assertEqual(len(board['rows']),11)
        self.assertEqual(ws['company_articles']['samsung-cnt'],['a'])
        self.assertEqual(ws['company_articles']['dl-enc'],['e'])
        self.assertEqual(before,self.ds);board['rows'].clear();self.assertEqual(len(strategy.default_board()['rows']),11)

    def test_upsert_add_only_and_custom_board(self):
        board=strategy.default_board();board['companies'].append({'id':'new','name':'새회사','aliases':[]})
        saved=strategy.save_board(self.ds,board);self.assertEqual(len(saved['companies']),8)
        board['companies'].pop()
        with self.assertRaises(ValueError):strategy.save_board(self.ds,board)
        other={'id':'owners','title':'발주처','companies':[{'id':'owner','name':'공개발주처'}],'rows':[{'id':'plans','label':'계획'}]}
        strategy.save_board(self.ds,other);self.assertEqual(len(strategy.boards(self.ds)),2)

    def test_board_limits_invalid_ids_and_alias_arrays(self):
        for mutate in [lambda b:b.update(id='../unsafe'),lambda b:b.update(title='x'*161),
                       lambda b:b.update(companies=[]),lambda b:b['companies'][0].update(aliases='wrong'),
                       lambda b:b['companies'].append(copy.deepcopy(b['companies'][0])),
                       lambda b:b.update(rows=[{'id':'r'+str(i),'label':'r'} for i in range(31)]),
                       lambda b:b.update(companies=[{'id':'c'+str(i),'name':'회사'} for i in range(41)])]:
            board=strategy.default_board();mutate(board)
            with self.assertRaises(ValueError):strategy.save_board(self.ds,board)
        self.assertNotIn('strategy_boards',self.ds)

    def test_orphan_summary_rejected(self):
        self.ds['strategy_summaries']={'orphan':{'board_id':'custom','company_id':'missing','row_id':'r'}}
        with self.assertRaises(ValueError):strategy.save_board(self.ds,{'id':'custom','title':'표','companies':[{'id':'c','name':'회사'}],'rows':[{'id':'r','label':'행'}]})

    def test_prepare_bounds_public_fields_and_stable_hash(self):
        before=copy.deepcopy(self.ds);p=self.prepared();self.assertEqual(p['article_ids'],['a'])
        self.assertEqual(p['input_hash'],self.prepared()['input_hash']);self.assertEqual(self.ds,before)
        rendered=str(p);self.assertNotIn('SECRET',rendered);self.assertNotIn('intranet',rendered)
        self.assertEqual(set(p['input_data']),{'company','rows','articles','analysis_brief'})
        self.assertLessEqual(len(p['articles'][0]['text']),2400)
        for update in [{'article_ids':['b']},{'article_ids':['c']},{'article_ids':['d']},{'article_ids':['missing']},
                       {'article_ids':['a','a']},{'row_ids':['strategy']*4},{'row_ids':[{}]},
                       {'row_ids':['unknown']},{'company_id':'unknown'}]:
            with self.assertRaises(ValueError):strategy.prepare_analysis(self.ds,{**self.payload,**update})

    def test_article_default_three_and_configured_limits(self):
        for i in range(6):self.ds['articles']['s'+str(i)]={'id':'s'+str(i),'mode':'live_metadata','title':'삼성물산 공개 기사 '+str(i)}
        payload={k:v for k,v in self.payload.items() if k!='article_ids'}
        self.assertEqual(len(strategy.prepare_analysis(self.ds,payload)['articles']),3)
        with self.assertRaises(ValueError):strategy.prepare_analysis(self.ds,{**payload,'article_ids':['a','s0']},{'max_articles_per_run':1})
        with self.assertRaises(ValueError):strategy.prepare_analysis(self.ds,self.payload,{'max_articles_per_run':21})
        self.ds['articles']['a']['feed_excerpt']='삼성물산 '+('문자'*1000)
        with self.assertRaises(ValueError):strategy.prepare_analysis(self.ds,self.payload,{'max_input_chars':500})

    def test_hash_ignores_selection_order_and_changes_with_public_input(self):
        self.ds['articles']['z']={'id':'z','mode':'live_metadata','title':'삼성물산 두 번째 공개 기사'}
        payload={**self.payload,'article_ids':['a','z'],'row_ids':['strategy','strengths']}
        first=strategy.prepare_analysis(self.ds,payload)
        second=strategy.prepare_analysis(self.ds,{**payload,'article_ids':['z','a'],'row_ids':['strengths','strategy']})
        self.assertEqual(first['input_hash'],second['input_hash'])
        self.ds['articles']['a']['internal_note']='changed secret'
        self.assertEqual(first['input_hash'],strategy.prepare_analysis(self.ds,payload)['input_hash'])
        self.ds['articles']['a']['title']+=' 새 공개 변경'
        self.assertNotEqual(first['input_hash'],strategy.prepare_analysis(self.ds,payload)['input_hash'])

    def test_store_stable_id_candidate_and_no_fact_merge(self):
        facts=copy.deepcopy(self.ds['projects']);stored=self.store();item=stored[0]
        self.assertEqual(item['id'],'construction:samsung-cnt:strategy');self.assertEqual(item['state'],'candidate')
        self.assertIn('미검증',item['validation_label']);self.assertEqual(item['usage'],{'input_tokens':10})
        self.store();self.assertEqual(len(self.ds['strategy_summaries']),1);self.assertEqual(self.ds['projects'],facts)
        self.assertEqual(len(item['paragraphs']),1);self.assertEqual(item['paragraphs'][0]['basis'],'public_metadata_ai_candidate')

    def test_all_results_validated_before_write(self):
        p=strategy.prepare_analysis(self.ds,{**self.payload,'row_ids':['strategy','strengths']})
        result=self.result();result['cells'].append({'row_id':'strengths','paragraphs':[{'text':'bad','quote':'없는 인용','article_id':'a'}]})
        with self.assertRaises(ValueError):strategy.validate_and_store(self.ds,p,result,{})
        self.assertNotIn('strategy_summaries',self.ds)

    def test_result_rejects_wrong_source_row_count_quote_and_length(self):
        for mutate in [lambda r:r['cells'][0]['paragraphs'][0].update(article_id='b'),
                       lambda r:r['cells'][0]['paragraphs'][0].update(quote='없음'),
                       lambda r:r['cells'][0].update(row_id='unknown'),
                       lambda r:r['cells'][0].update(paragraphs=r['cells'][0]['paragraphs']*4),
                       lambda r:r['cells'][0]['paragraphs'][0].update(text='x'*1201),
                       lambda r:r['cells'].append(copy.deepcopy(r['cells'][0]))]:
            result=self.result();mutate(result)
            with self.assertRaises(ValueError):strategy.validate_and_store(self.ds,self.prepared(),result,{})

    def test_empty_cell_preserves_insufficient_evidence(self):
        items=strategy.validate_and_store(self.ds,self.prepared(),{'cells':[{'row_id':'strategy','paragraphs':[]}]},{})
        self.assertEqual(items[0]['state'],'insufficient_evidence');self.assertEqual(items[0]['paragraphs'],[])

    def test_stale_and_selected_scope_without_writes(self):
        item=self.store()[0];before=copy.deepcopy(self.ds);ws=strategy.workspace(self.ds,['a'])
        self.assertFalse(ws['summaries'][item['id']]['stale']);self.assertTrue(ws['summaries'][item['id']]['in_selected_scope'])
        self.assertEqual(self.ds,before)
        ws=strategy.workspace(self.ds,[]);self.assertFalse(ws['summaries'][item['id']]['in_selected_scope'])
        self.ds['articles']['a']['feed_excerpt']='새 공개 메타데이터'
        self.assertTrue(strategy.workspace(self.ds)['summaries'][item['id']]['stale'])

    def test_report_escape_sources_and_no_internal_content(self):
        self.store();ws=strategy.workspace(self.ds);ws['active_board']['title']='<script>alert(1)</script>'
        report=strategy.render_report(ws,self.ds['articles'],'2026-10-26')
        self.assertIn('size:A3 landscape',report);self.assertIn('display:table-header-group',report)
        self.assertIn('&lt;script&gt;',report);self.assertNotIn('<script>',report)
        self.assertIn('공개 출처',report);self.assertIn('2026-10-26',report);self.assertIn('blockquote',report)
        self.assertIn('https://example.test/a',report);self.assertNotIn('SECRET',report);self.assertNotIn('intranet',report)
        for url in ['javascript:alert(1)',urlunsplit(('https','user:secret@example.test','','','')),'http://127.0.0.1','https://office.internal','https://localhost']:
            self.ds['articles']['a']['url']=url
            output=strategy.render_report(ws,self.ds['articles'],'date')
            self.assertNotIn('href=',output)

    def test_report_splits_company_groups_and_caps_paragraphs(self):
        board=strategy.default_board();board['companies'].append({'id':'extra','name':'추가','aliases':[]})
        strategy.save_board(self.ds,board);self.store();ws=strategy.workspace(self.ds)
        report=strategy.render_report(ws,self.ds['articles'],'date')
        self.assertEqual(report.count('<section>'),2);self.assertIn('section+section{break-before:page}',report)
        self.assertIn('자료 부족 / 확인 필요',report)


if __name__=='__main__':unittest.main()
