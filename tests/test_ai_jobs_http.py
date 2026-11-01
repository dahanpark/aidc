"""Real loopback HTTP, isolated fixture JSON, mocked inference only."""
import json,threading,unittest
from unittest.mock import patch
from tests import test_api

class JobsHttpTests(unittest.TestCase):
 setUp=test_api.ApiTests.setUp
 tearDown=test_api.ApiTests.tearDown
 request=test_api.ApiTests.request
 def configure(self):
  def edit(ds):
   ds['settings']['app']['ai']={'provider':'openai','model':'synthetic','enabled':True,'enabled_tasks':['extract','compare','briefing'],'max_input_chars':20000,'max_output_tokens':1200,'max_articles_per_run':3}
   ds.setdefault('articles',{})['job-article']={'id':'job-article','title':'서울 AI 데이터센터 공개 계획','mode':'live_metadata'}
  self.app.repo.transact(edit)
 def test_submit_returns_before_slow_provider_and_GET_is_readonly(self):
  self.configure();gate=threading.Event();entered=threading.Event()
  self.addCleanup(gate.set)
  def infer(*a,**k):entered.set();gate.wait(4);return {'extractions':[],'matches':[],'briefing':[]},{}
  with patch.object(self.app.ai,'status',return_value={'connected':True}),patch.object(self.app.ai,'credential',return_value='synthetic'),patch('backend.ai_analysis.infer',side_effect=infer) as inference:
   raw={'task':'analysis','selection':{'article_ids':['job-article']}}
   self.assertEqual(self.request('/api/ai/jobs/preview',raw,{'X-Atlas-Token':''})[0],403)
   status,body,_=self.request('/api/ai/jobs/preview',raw);self.assertEqual(status,200);p=json.loads(body)['data']
   payload={'preview_id':p['preview_id'],'consent_digest':p['consent_digest'],'consent_public_metadata':True}
   with patch.object(self.app,'view_generation',side_effect=AssertionError('submit must not copy whole store')):
    status,body,_=self.request('/api/ai/jobs/submit',payload)
   self.assertEqual(status,200);job=json.loads(body)['data'];self.assertTrue(entered.wait(2))
   query='/api/ai/jobs?job_id='+job['id'];path=self.app.root/'runtime/ai-jobs'/(job['id']+'.json');before=path.read_bytes()
   for _ in range(3):self.assertEqual(self.request(query)[0],200)
   self.assertEqual(before,path.read_bytes())
   status,body,_=self.request('/api/ai/jobs/submit',payload);self.assertEqual(json.loads(body)['data']['id'],job['id'])
   gate.set();self.app.ai_jobs.threads[job['id']].join(5);inference.assert_called_once()
   done=json.loads(self.request(query)[1])['data'];self.assertEqual(done['status'],'completed')
   self.assertEqual(self.request('/api/ai/run?run_id='+done['run_id'])[0],200)
 def test_bad_job_id_and_consent_do_not_create_jobs(self):
  self.assertEqual(self.request('/api/ai/jobs?job_id=../../x')[0],400)
  self.assertEqual(self.request('/api/ai/jobs/submit',{})[0],400)
  self.assertEqual(json.loads(self.request('/api/ai/jobs')[1])['data']['jobs'],[])

if __name__=='__main__':unittest.main()
