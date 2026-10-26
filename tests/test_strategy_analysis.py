"""In-memory transactions and mocked strategy inference only."""
import copy
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from backend import strategy, strategy_analysis


class Repo:
    def __init__(self,ds):self.ds=ds;self.transactions=[]
    def snapshot(self):return {'datasets':copy.deepcopy(self.ds)}
    def transact(self,edit):
        candidate=copy.deepcopy(self.ds);edit(candidate);self.ds=candidate
        self.transactions.append(copy.deepcopy(candidate))


class Connection:
    def __init__(self):
        self.repo=Repo({'settings':{'app':{'ai':{'provider':'mock','model':'synthetic','enabled':True,
                          'enabled_tasks':['strategy'],'max_input_chars':8000}}},
                       'articles':{'a':{'id':'a','mode':'live_metadata','title':'삼성물산 공개 데이터센터 검토 기사',
                                      'note':'PRIVATE_NOTE','body':'PRIVATE_BODY'}},
                       'projects':{'p':{'name':'원본'}}})
        self.read_snapshot=self.repo.snapshot;self.lock=threading.RLock();self.connected=True;self.key='SYNTHETIC_SECRET'
    def status(self,ds):return {'connected':self.connected}
    def credential(self,profile):return self.key


def result():
    return {'cells':[{'row_id':'strategy','paragraphs':[{'text':'검토 단계의 근거 후보다.',
                      'quote':'삼성물산 공개 데이터센터 검토 기사','article_id':'a'}]}]}


class StrategyAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.connection=Connection();self.payload={'company_id':'samsung-cnt','row_ids':['strategy'],
                                                 'article_ids':['a'],'consent_public_metadata':True}
    def profile(self):return self.connection.repo.ds['settings']['app']['ai']

    def test_preview_exact_full_input_count_and_no_writes_or_calls(self):
        before=copy.deepcopy(self.connection.repo.ds)
        with patch('backend.ai_analysis.infer') as infer:
            preview=strategy_analysis.preview(self.connection,self.payload);infer.assert_not_called()
        expected=len(strategy.SYSTEM)+len(json.dumps(strategy.RESULT_SCHEMA,ensure_ascii=False))+len(json.dumps(preview['input_data'],ensure_ascii=False))
        self.assertEqual(preview['input_chars'],expected);self.assertEqual(preview['limits']['daily_call_limit'],10)
        self.assertEqual(preview['limits']['article_text_chars'],1200)
        self.assertEqual(preview['limits']['max_output_tokens'],1200)
        self.assertEqual(before,self.connection.repo.ds);self.assertEqual(self.connection.repo.transactions,[])
        self.assertNotIn('PRIVATE_',json.dumps(preview));self.assertNotIn(self.connection.key,json.dumps(preview))

    def test_full_prompt_over_limit_blocks_preview_and_run(self):
        count=strategy_analysis.preview(self.connection,self.payload)['input_chars']
        self.profile()['max_input_chars']=count-1
        with patch('backend.ai_analysis.infer') as infer:
            for fn in (strategy_analysis.preview,strategy_analysis.run):
                with self.assertRaises(ValueError):fn(self.connection,self.payload)
            infer.assert_not_called()
        self.assertEqual(self.connection.repo.transactions,[])

    def test_consent_role_connection_and_credentials_gate_before_call(self):
        scenarios=[('consent',False),('role',False),('connection',False),('credential',False)]
        for kind,_ in scenarios:
            connection=Connection();payload=copy.deepcopy(self.payload)
            if kind=='consent':payload.pop('consent_public_metadata')
            if kind=='role':connection.repo.ds['settings']['app']['ai']['enabled_tasks']=[]
            if kind=='connection':connection.connected=False
            if kind=='credential':connection.key=None
            with patch('backend.ai_analysis.infer') as infer:
                with self.assertRaises(ValueError):strategy_analysis.run(connection,payload)
                infer.assert_not_called()
            self.assertEqual(connection.repo.transactions,[])

    def test_running_commit_precedes_single_inference_and_final_summary_transaction(self):
        def provider(profile,key,input_data,**kwargs):
            runs=self.connection.repo.ds['ai_runs'];self.assertEqual(len(runs),1)
            self.assertEqual(next(iter(runs.values()))['status'],'running')
            self.assertEqual(key,self.connection.key);self.assertNotIn('PRIVATE_',json.dumps(input_data))
            self.assertEqual(kwargs['schema'],strategy.RESULT_SCHEMA);self.assertEqual(kwargs['system'],strategy.SYSTEM)
            return result(),{'input_tokens':12,'output_tokens':8,'secret':'PRIVATE','bool':True}
        before=copy.deepcopy(self.connection.repo.ds['projects'])
        with patch('backend.ai_analysis.infer',side_effect=provider) as infer:
            response=strategy_analysis.run(self.connection,self.payload);infer.assert_called_once()
        self.assertEqual(response['status'],'completed');self.assertEqual(response['usage'],{'input_tokens':12,'output_tokens':8})
        self.assertEqual(len(self.connection.repo.transactions),2)
        self.assertIn(response['summary_ids'][0],self.connection.repo.ds['strategy_summaries'])
        self.assertEqual(self.connection.repo.ds['projects'],before)
        self.assertNotIn(self.connection.key,json.dumps(self.connection.repo.ds))
        self.assertNotIn('PRIVATE',json.dumps(self.connection.repo.ds['ai_runs']))

    def test_cache_profile_model_and_input_fingerprint(self):
        with patch('backend.ai_analysis.infer',return_value=(result(),{})) as infer:
            first=strategy_analysis.run(self.connection,self.payload)
            cached=strategy_analysis.run(self.connection,self.payload)
            self.assertEqual(cached['status'],'cached');self.assertEqual(cached['run_id'],first['run_id'])
            self.assertFalse(cached['inference_called']);self.assertEqual(infer.call_count,1)
            self.profile()['model']='other-model'
            self.assertEqual(strategy_analysis.run(self.connection,self.payload)['status'],'completed')
            self.assertEqual(infer.call_count,2)
            self.connection.repo.ds['articles']['a']['title']+=' 변경'
            self.assertEqual(strategy_analysis.run(self.connection,self.payload)['status'],'completed')
            self.assertEqual(infer.call_count,3)

    def test_shared_budget_counts_all_tasks_completed_failed_running_default_ten(self):
        now=datetime.now(timezone.utc).isoformat()
        self.connection.repo.ds['ai_runs']={str(i):{'id':str(i),'created_at':now,'status':['completed','failed','running','interrupted'][i%4],'task':'legacy-extract'} for i in range(10)}
        with patch('backend.ai_analysis.infer') as infer:
            with self.assertRaises(ValueError):strategy_analysis.run(self.connection,self.payload)
            infer.assert_not_called()
        self.assertEqual(self.connection.repo.transactions,[])

    def test_utc_day_normalization_and_previous_day_exclusion(self):
        day=datetime.now(timezone.utc).date()
        just_today=datetime.combine(day,datetime.min.time(),timezone.utc)
        local=(just_today+timedelta(hours=1)).astimezone(timezone(timedelta(hours=9)))
        self.assertTrue(strategy_analysis._today_run({'status':'running','created_at':local.isoformat()},day))
        self.assertFalse(strategy_analysis._today_run({'status':'failed','created_at':(just_today-timedelta(seconds=1)).isoformat()},day))
        self.assertFalse(strategy_analysis._today_run({'status':'completed','created_at':'invalid'},day))

    def test_failed_network_is_sanitized_and_counts_without_retry(self):
        self.profile()['daily_call_limit']=1
        with patch('backend.ai_analysis.infer',side_effect=RuntimeError(self.connection.key+' PRIVATE_BODY')) as infer:
            failed=strategy_analysis.run(self.connection,self.payload)
            self.assertEqual(failed['status'],'failed');infer.assert_called_once()
            with self.assertRaises(ValueError):strategy_analysis.run(self.connection,self.payload)
            infer.assert_called_once()
        self.assertNotIn(self.connection.key,json.dumps(self.connection.repo.ds['ai_runs']))
        self.assertNotIn('PRIVATE_BODY',json.dumps(self.connection.repo.ds['ai_runs']))
        self.assertNotIn('strategy_summaries',self.connection.repo.ds)

    def test_bad_quote_keeps_usage_and_previous_summary_without_partial_writes(self):
        with patch('backend.ai_analysis.infer',return_value=(result(),{'input_tokens':5})):
            strategy_analysis.run(self.connection,self.payload)
        previous=copy.deepcopy(self.connection.repo.ds['strategy_summaries'])
        self.profile()['model']='invalid-model';bad=result();bad['cells'][0]['paragraphs'][0]['quote']='입력에 없는 인용'
        with patch('backend.ai_analysis.infer',return_value=(bad,{'input_tokens':7})) as infer:
            response=strategy_analysis.run(self.connection,self.payload);infer.assert_called_once()
        self.assertEqual(response['status'],'failed');self.assertEqual(response['usage'],{'input_tokens':7})
        self.assertEqual(response['error']['code'],'strategy_validation')
        self.assertEqual(self.connection.repo.ds['strategy_summaries'],previous)
        stored=self.connection.repo.ds['ai_runs'][response['run_id']]
        self.assertNotIn('result',stored)

    def test_cached_request_does_not_consume_more_budget(self):
        self.profile()['daily_call_limit']=1
        with patch('backend.ai_analysis.infer',return_value=(result(),{})) as infer:
            strategy_analysis.run(self.connection,self.payload)
            self.assertEqual(strategy_analysis.run(self.connection,self.payload)['status'],'cached');infer.assert_called_once()

    def test_cached_result_restores_previous_cell_without_new_inference(self):
        with patch('backend.ai_analysis.infer',return_value=(result(),{})) as infer:
            first=strategy_analysis.run(self.connection,self.payload)
            sid=first['summary_ids'][0]
            self.connection.repo.ds['strategy_summaries'][sid]['paragraphs'][0]['text']='다른 입력의 최신 요약'
            response=strategy_analysis.run(self.connection,self.payload)
            self.assertEqual(response['status'],'cached');infer.assert_called_once()
        self.assertEqual(self.connection.repo.ds['strategy_summaries'][sid]['paragraphs'][0]['text'],'검토 단계의 근거 후보다.')
        self.assertEqual(len(self.connection.repo.ds['ai_runs']),1)

    def test_input_changed_during_inference_fails_without_storing_old_summary(self):
        def provider(*args,**kwargs):
            self.connection.repo.ds['articles']['a']['title']+=' 새 관측'
            return result(),{'input_tokens':9}
        with patch('backend.ai_analysis.infer',side_effect=provider) as infer:
            response=strategy_analysis.run(self.connection,self.payload);infer.assert_called_once()
        self.assertEqual(response['status'],'failed');self.assertEqual(response['usage'],{'input_tokens':9})
        self.assertNotIn('strategy_summaries',self.connection.repo.ds)

    def test_three_articles_trimmed_to_configured_default_and_stale_uses_full_source(self):
        self.connection.repo.ds['articles']['a']['feed_excerpt']='공개 문장 '*400
        for aid in ['b','c']:
            self.connection.repo.ds['articles'][aid]={'id':aid,'mode':'live_metadata','title':'삼성물산 공개 기사 '+aid,'feed_excerpt':'공개 문장 '*400}
        payload={**self.payload,'article_ids':['a','b','c']}
        preview=strategy_analysis.preview(self.connection,payload)
        self.assertEqual([len(a['text']) for a in preview['articles']],[1200]*3)
        self.assertLessEqual(preview['input_chars'],8000)
        with patch('backend.ai_analysis.infer',return_value=(result(),{})) as infer:
            response=strategy_analysis.run(self.connection,payload)
            sent=infer.call_args.args[2];self.assertEqual([len(a['text']) for a in sent['articles']],[1200]*3)
        sid=response['summary_ids'][0]
        self.assertFalse(strategy.workspace(self.connection.repo.ds)['summaries'][sid]['stale'])
        original=self.connection.repo.ds['articles']['a']['feed_excerpt']
        self.connection.repo.ds['articles']['a']['feed_excerpt']=original[:1500]+'변경된 끝부분'+original[1510:]
        self.assertTrue(strategy.workspace(self.connection.repo.ds)['summaries'][sid]['stale'])
        current=strategy_analysis.preview(self.connection,payload)
        self.assertEqual(preview['input_hash'],current['input_hash'])
        self.assertNotEqual(preview['source_hash'],current['source_hash'])
        with patch('backend.ai_analysis.infer',return_value=(result(),{})) as infer:
            self.assertEqual(strategy_analysis.run(self.connection,payload)['status'],'completed');infer.assert_called_once()

    def test_changes_outside_truncated_text_detected_during_inference(self):
        self.connection.repo.ds['articles']['a']['feed_excerpt']='공개 문장 '*400
        def provider(*args,**kwargs):
            text=self.connection.repo.ds['articles']['a']['feed_excerpt']
            self.connection.repo.ds['articles']['a']['feed_excerpt']=text[:1500]+'다른 원본'+text[1510:]
            return result(),{}
        with patch('backend.ai_analysis.infer',side_effect=provider):
            response=strategy_analysis.run(self.connection,self.payload)
        self.assertEqual(response['status'],'failed');self.assertNotIn('strategy_summaries',self.connection.repo.ds)

    def test_text_and_output_limits_are_checked_in_preview(self):
        for field,value in [('article_text_chars',199),('max_output_tokens',127)]:
            with self.subTest(field=field):
                connection=Connection();connection.repo.ds['settings']['app']['ai'][field]=value
                with self.assertRaises(ValueError):strategy_analysis.preview(connection,self.payload)


if __name__=='__main__':unittest.main()
