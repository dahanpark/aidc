"""Mock-only AI execution and source-preserving display contracts."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import ai_cleanup as cleanup,ai_company_identity as ai,company_identity_view
from backend.ai_connection import AIConnection
from backend.repository import JsonRepository
from tests.test_ai_cleanup import sample
from tests.test_ai_limits import Vault

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.repo=JsonRepository(Path(self.temp.name)/'store');ds=sample()
        ds['settings']['app']['ai'].update(provider='openai',model='synthetic',enabled=True,verified_at='2026-10-26T00:00:00Z',secret_ref='credential:openai',daily_call_limit=10)
        self.repo.transact(lambda records:records.update(ds));self.connection=AIConnection(self.repo,'cleanup-test',Vault())

    def test_preview_private_boundary_consent_cache_and_failed_attempt_limit(self):
        preview=ai.preview(self.connection,{'article_ids':['b']})
        self.assertNotIn('PRIVATE',json.dumps(preview));self.assertNotIn('target_source_stamps',preview)
        result=copy.deepcopy(sample()['ai_runs']['company']['result']);result['matches'][0].pop('id');result['matches'][0].pop('validation_state')
        with patch('backend.ai_company_identity.infer',return_value=(result,{'input_tokens':1,'output_tokens':2})) as infer:
            with self.assertRaises(ValueError):ai.analyse(self.connection,{'article_ids':['b']})
            self.assertFalse(infer.called)
            payload={'article_ids':['b'],'consent_public_metadata':True}
            first=ai.analyse(self.connection,payload);self.assertEqual(first['status'],'completed')
            self.assertEqual(ai.analyse(self.connection,payload)['status'],'cached');self.assertEqual(infer.call_count,1)
            self.assertNotIn('PRIVATE',json.dumps(infer.call_args.args[2]))
        self.repo.transact(lambda ds:ds['articles']['b'].update(url='https://public.example/changed'))
        with patch('backend.ai_company_identity.infer',side_effect=ValueError('synthetic')) as infer:
            self.assertEqual(ai.analyse(self.connection,payload)['status'],'failed');self.assertEqual(infer.call_count,1)
        self.repo.transact(lambda ds:ds['settings']['app']['ai'].update(daily_call_limit=1))
        with patch('backend.ai_company_identity.infer') as infer,self.assertRaises(ValueError):ai.analyse(self.connection,payload)
        self.assertFalse(infer.called)

    def test_company_projection_deduplicates_citations_without_contract_or_read_changes(self):
        ds=sample();payload={'run_id':'company','match_id':ds['ai_runs']['company']['result']['matches'][0]['id']}
        preview=cleanup.company_preview(ds,payload);cleanup.company_confirm(ds,{**payload,'preview_hash':preview['preview_hash'],'confirmed':True})
        data={'companies':[{'id':c,'name':ds['companies'][c]['name'],'article_ids':['b'],'roles':['contractor']} for c in ('left','right')],
              'news':{'articles':[{'id':'b','company_ids':['left','right'],'matched_companies':[{'id':c,'name':c} for c in ('left','right')]}],'counts':{'companies':2}},
              'ontology':{'nodes':[{'id':'company:'+c,'entity_id':c,'name':c,'type':'company','article_ids':['b']} for c in ('left','right')],
                          'edges':[{'id':c,'source':'company:'+c,'target':'project:p','basis':'co_occurrence','directness':'unconfirmed','article_ids':['b']} for c in ('left','right')],
                          'graph':{'total_nodes':2,'displayed_nodes':2}},'read_states':[{'id':'untouched'}]}
        before=copy.deepcopy(data);view=company_identity_view.apply(data,ds)
        self.assertEqual(data,before);self.assertEqual(len(view['companies']),1);self.assertEqual(view['companies'][0]['article_ids'],['b'])
        self.assertEqual(len(view['ontology']['nodes']),1);self.assertEqual(len(view['ontology']['edges']),1)
        self.assertEqual(view['ontology']['edges'][0]['directness'],'unconfirmed');self.assertEqual(view['news']['counts']['companies'],1)
        self.assertEqual(view['read_states'],before['read_states']);self.assertEqual(view['ontology']['graph']['displayed_nodes'],1)

    def test_unknown_project_type_requires_registered_link_exact_quote_and_undo(self):
        ds=sample();a=ds['articles']['a'];a.update(title='서울 테스트센터 AI 데이터센터 신규 사업 계획',project_ids=['p'])
        ds['projects']['p']={'id':'p','name':'테스트센터','scope':'unresolved','country':'KR','article_ids':['a']}
        run=ds['ai_runs']['class'];run['input_snapshots']=[{'id':'a','title':a['title'],'text':a['title']}];run['article_source_stamps']['a']=cleanup.article_stamp(a);run['result']['classifications'][0]['quote']=a['title']
        before=copy.deepcopy(ds['projects']);payload={'run_id':'class','article_id':'a','project_id':'p','confirmed':True}
        cleanup.project_scope_decide(ds,payload);cleanup.validate_records(ds)
        view=cleanup.project_scope_snapshot({'datasets':ds});self.assertEqual(view['datasets']['projects']['p']['scope'],'kr-ai');self.assertEqual(ds['projects'],before)
        ds['projects']['p']['name']='다른 사업';self.assertEqual(cleanup.project_scope_snapshot({'datasets':ds})['datasets']['projects']['p']['scope'],'unresolved')
        cleanup.project_scope_decide(ds,{'project_id':'p','action':'undo'});self.assertFalse(ds['project_scope_decisions']['p']['active'])
        with self.assertRaises(ValueError):cleanup.project_scope_decide(ds,payload)
