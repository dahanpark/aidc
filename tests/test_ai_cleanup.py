"""Source-preserving confirmation; no external AI calls or operational data."""
import copy
import tempfile
import unittest
from pathlib import Path
from backend import ai_cleanup as cleanup, ai_company_identity as company_ai, news
from backend.ai_analysis import public_article
from backend.repository import JsonRepository


def sample():
    a={'id':'a','title':'AI 데이터센터 신규 사업 계획','mode':'live_metadata','url':'https://public.example/a','publisher':'공개매체','published_at':'2026-10-26T00:00:00Z','company_ids':[],'project_ids':[]}
    b={'id':'b','title':'알파건설은 Alpha Build로 사명을 변경했다. 서울 AI 데이터센터 준공','mode':'live_metadata','url':'https://public.example/b','publisher':'공개매체','published_at':'2026-10-26T00:00:00Z','company_ids':['left','right'],'project_ids':[],'internal_note':'PRIVATE-NOTE'}
    ds={'articles':{'a':a,'b':b},'companies':{'left':{'id':'left','name':'Alpha Build','aliases':[],'country':'KR','entity_type':'company'},'right':{'id':'right','name':'알파건설','aliases':[],'country':'KR','entity_type':'company'}},'projects':{},'ai_runs':{},'settings':{'app':{'id':'app','ai':{'enabled_tasks':['compare','classify'],'max_articles_per_run':3}}},'read_states':{},'news_read_states':{},'bookmarks':{}}
    ds['ai_runs']['class']={'id':'class','task':'classify','status':'completed','article_ids':['a'],'input_snapshots':[public_article(a)],'article_source_stamps':{'a':cleanup.article_stamp(a)},'result':{'classifications':[{'article_id':'a','scope':'kr-ai','reason':'사용자 검토용 공개 근거 후보','quote':a['title']}]}}
    data,preview=company_ai.prepare(ds,ds['settings']['app']['ai'],{'article_ids':['b']})
    result=company_ai.validate_result({'matches':[{'left_id':'left','right_id':'right','assessment':'same_legal_entity','reason':'사명 변경의 명시 보도','evidence':[{'article_id':'b','quote':b['title']}]}]},data)
    ds['ai_runs']['company']={'id':'company','task':'company_identity','status':'completed','article_ids':['b'],'input_snapshots':data['articles'],'article_source_stamps':{'b':cleanup.article_stamp(b)},'target_snapshots':data['targets'],'target_stamps':preview['target_source_stamps'],'result':result}
    return ds


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.ds=sample()
        self.class_payload={'article_id':'a','run_id':'class','confirmed':True}
        self.company_payload={'run_id':'company','match_id':self.ds['ai_runs']['company']['result']['matches'][0]['id']}

    def confirm_company(self):
        preview=cleanup.company_preview(self.ds,self.company_payload)
        return cleanup.company_confirm(self.ds,{**self.company_payload,'preview_hash':preview['preview_hash'],'confirmed':True})

    def test_classification_changes_effective_scope_counts_and_undo_preserves_source(self):
        before=copy.deepcopy(self.ds)
        cleanup.scope_decide(self.ds,self.class_payload)
        workspace=news.build_workspace({'datasets':self.ds},{'period':'1y','scope':'kr-ai'},'2026-10-27T00:00:00Z')
        self.assertIn('a',[a['id'] for a in workspace['articles']])
        item=next(a for a in workspace['articles'] if a['id']=='a')
        self.assertEqual(item['scope_classification']['status'],'user_confirmed_ai')
        self.assertEqual(self.ds['articles'],before['articles'])
        self.assertEqual(workspace['counts']['scope_counts']['all'],sum(workspace['counts']['scope_counts'][k] for k in ('kr-dc','kr-ai','global-ai','unresolved')))
        cleanup.scope_decide(self.ds,{'article_id':'a','action':'undo'})
        state=copy.deepcopy(self.ds['article_scope_decisions']);cleanup.scope_decide(self.ds,{'article_id':'a','action':'undo'})
        self.assertEqual(state,self.ds['article_scope_decisions'])
        workspace=news.build_workspace({'datasets':self.ds},{'period':'1y','scope':'kr-ai'},'2026-10-27T00:00:00Z')
        self.assertNotIn('a',[a['id'] for a in workspace['articles']])
        for name in ('articles','companies','read_states','news_read_states','bookmarks'):self.assertEqual(before[name],self.ds[name])

    def test_classification_requires_confirmation_fresh_source_and_concrete_scope(self):
        for kind in ('consent','changed','legacy','unresolved'):
            ds=copy.deepcopy(self.ds);payload=dict(self.class_payload)
            if kind=='consent':payload['confirmed']=False
            if kind=='changed':ds['articles']['a']['feed_excerpt']='추가된 정보'
            if kind=='legacy':ds['ai_runs']['class'].pop('article_source_stamps')
            if kind=='unresolved':ds['ai_runs']['class']['result']['classifications'][0]['scope']='unresolved'
            with self.subTest(kind=kind),self.assertRaises(ValueError):cleanup.scope_decide(ds,payload)

    def test_stale_article_suppresses_display_overlay_without_destroying_history(self):
        cleanup.scope_decide(self.ds,self.class_payload)
        self.ds['articles']['a']['url']='https://public.example/changed'
        view=copy.deepcopy(self.ds['articles']);cleanup.apply_scopes(self.ds,view)
        self.assertNotIn('confirmed_ai_classification',view['a'])
        cleanup.validate_records(self.ds)
        self.assertTrue(self.ds['article_scope_decisions']['a']['history'])

    def test_company_preview_confirm_undo_are_local_and_preserve_raw_ids(self):
        before=copy.deepcopy(self.ds)
        preview=cleanup.company_preview(self.ds,self.company_payload)
        self.assertEqual(before,self.ds)
        self.assertEqual(set(preview['member_ids']),{'left','right'})
        for update in ({'confirmed':False,'preview_hash':preview['preview_hash']},{'confirmed':True,'preview_hash':'outdated'}):
            with self.assertRaises(ValueError):cleanup.company_confirm(self.ds,{**self.company_payload,**update})
        saved=self.confirm_company();self.assertEqual(cleanup.company_map(self.ds),{'left':'left','right':'left'})
        cleanup.validate_records(self.ds)
        cleanup.company_undo(self.ds,{'group_id':saved['id']});self.assertEqual(cleanup.company_map(self.ds),{})
        self.assertEqual(saved['state'],'revoked');self.assertEqual(len(saved['history']),2)
        for name in ('articles','companies','read_states','news_read_states','bookmarks'):self.assertEqual(before[name],self.ds[name])

    def test_company_conflicts_stale_inputs_and_subsidiaries_are_held(self):
        for kind in ('country','legal_id','stale_article','stale_company','subsidiary','private'):
            ds=copy.deepcopy(self.ds)
            if kind=='country':ds['companies']['right']['country']='US'
            if kind=='legal_id':ds['companies']['left']['registration_number']='one';ds['companies']['right']['registration_number']='two'
            if kind=='stale_article':ds['articles']['b']['title']+=' 갱신'
            if kind=='stale_company':ds['companies']['right']['aliases']=['다른 별칭']
            if kind=='private':ds['companies']['right']['visibility']='private'
            if kind=='subsidiary':
                ds['articles']['b']['title']='알파건설은 Alpha Build의 자회사다.'
                run=ds['ai_runs']['company'];run['input_snapshots']=[public_article(ds['articles']['b'])]
                run['article_source_stamps']['b']=cleanup.article_stamp(ds['articles']['b'])
                run['result']['matches'][0]['evidence'][0]['quote']=ds['articles']['b']['title']
            with self.subTest(kind=kind),self.assertRaises(ValueError):cleanup.company_preview(ds,self.company_payload)

    def test_stale_company_group_is_disabled_and_can_be_released(self):
        group=self.confirm_company();self.ds['companies']['right']['name']='알파건설 변경'
        self.assertEqual(cleanup.company_map(self.ds),{})
        cleanup.validate_records(self.ds)
        cleanup.company_undo(self.ds,{'group_id':group['id']})

    def test_group_company_filter_includes_both_source_id_articles(self):
        self.confirm_company()
        # The public title names both companies but each original article ID stays unique.
        ws=news.build_workspace({'datasets':self.ds},{'period':'1y','scope':'all','company_id':'left'},'2026-10-27T00:00:00Z')
        self.assertEqual(len({a['id'] for a in ws['articles']}),len(ws['articles']))
        self.assertIn('b',[a['id'] for a in ws['articles']])

    def test_confirmed_records_survive_strict_json_reopen_and_reject_bad_fingerprints(self):
        cleanup.scope_decide(self.ds,self.class_payload);self.confirm_company()
        with tempfile.TemporaryDirectory() as directory:
            repo=JsonRepository(Path(directory)/'store');repo.transact(lambda ds:ds.update(copy.deepcopy(self.ds)))
            reopened=JsonRepository(Path(directory)/'store').snapshot()['datasets']
            self.assertEqual(reopened['companies'],self.ds['companies'])
            self.assertTrue(reopened['article_scope_decisions']['a']['active'])
            before=repo.snapshot()['generation']
            with self.assertRaises(ValueError):repo.transact(lambda ds:ds['article_scope_decisions']['a'].update(source_stamp='z'*64))
            self.assertEqual(repo.snapshot()['generation'],before)

    def test_queue_does_not_expose_private_sources_and_respects_date_and_geography(self):
        self.ds['articles']['secret']={**self.ds['articles']['a'],'id':'secret','visibility':'internal','title':'PRIVATE'}
        ws=cleanup.workspace(self.ds,{'period':'3y'})
        self.assertNotIn('PRIVATE',str(ws));self.assertIn('a',[a['id'] for a in ws['unclassified_articles']])
        self.assertEqual(cleanup.workspace(self.ds,{'period':'3y','country':'US'})['unclassified_articles'],[])
