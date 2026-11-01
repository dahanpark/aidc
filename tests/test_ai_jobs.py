"""Mock-only jobs, isolated journals, no paid provider or operational store."""
import copy,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from backend.ai_jobs import AIJobs,digest
from backend.repository import encoded,loads
from tests.test_strategy_analysis import Connection,result as strategy_result
from tests.test_ai_cleanup import sample

class JobsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.c=Connection();self.c.repo.ds.update(sample())
  self.c.repo.ds['articles']['s']={'id':'s','mode':'live_metadata','title':'한화 건설부문 공개 데이터센터 검토 기사'}
  self.c.repo.ds['settings']['app']['ai'].update(provider='mock',model='synthetic',enabled_tasks=['extract','compare','briefing','classify','strategy'],max_output_tokens=1200,max_input_chars=20000)
  self.root=Path(self.tmp.name)/'jobs';self.jobs=AIJobs(self.root,self.c)
  self.gate=threading.Event();self.addCleanup(self.gate.set)
 def preview(self,task='analysis',selection=None):return self.jobs.preview(task,selection or {'article_ids':['a']})
 def submit(self,p):return self.jobs.submit({'preview_id':p['preview_id'],'consent_digest':p['consent_digest'],'consent_public_metadata':True})
 def finish(self,j):
  self.jobs.threads[j['id']].join(5);self.assertFalse(self.jobs.threads[j['id']].is_alive());return self.jobs.status(j['id'])
 def test_four_previews_exact_contract_no_private_or_writes(self):
  before=copy.deepcopy(self.c.repo.ds)
  for t,s in [('analysis',{'article_ids':['a']}),('classify',{'article_ids':['a']}),('company_identity',{'article_ids':['b']}),('strategy',{'article_ids':['s'],'company_id':'hanwha-construction','row_ids':['strategy']})]:
   p=self.preview(t,s);self.assertIn('system',p);self.assertIn('response_schema',p);self.assertEqual(p['expected_calls'],1)
   self.assertNotIn('PRIVATE',json.dumps(p));self.assertNotIn(self.c.key,json.dumps(p))
  self.assertEqual(before,self.c.repo.ds);self.assertFalse(self.root.exists())
 def test_fast_id_readonly_status_duplicate_and_reconnect(self):
  entered=threading.Event();calls=[]
  def infer(*args,**kw):
   calls.append(1);entered.set();self.gate.wait(4);return {'extractions':[],'matches':[],'briefing':[]},{}
  p=self.preview()
  with patch('backend.ai_analysis.infer',side_effect=infer):
   start=time.monotonic();j=self.submit(p);self.assertLess(time.monotonic()-start,1);self.assertTrue(entered.wait(2))
   raw=(self.root/(j['id']+'.json')).read_bytes()
   for _ in range(5):self.assertEqual(self.submit(p)['id'],j['id']);self.assertEqual(self.jobs.status(j['id'])['status'],'submitted')
   self.assertEqual(raw,(self.root/(j['id']+'.json')).read_bytes());self.gate.set();done=self.finish(j)
   self.assertEqual(done['status'],'completed');self.assertEqual(len(calls),1)
   self.assertEqual(AIJobs(self.root,self.c).status(j['id'])['run_id'],done['run_id']);self.assertEqual(self.submit(p)['id'],j['id'])
  self.assertNotIn(self.c.key,(self.root/(j['id']+'.json')).read_text())
 def test_restart_never_resends_pending_or_failed(self):
  for st in ['queued','submitted','running','failed','uncertain']:
   ident='job-'+digest(st)[:32];r={'id':ident,'status':st,'consent_digest':digest(st),'created_at':'2026','history':[{'status':st}]}
   self.root.mkdir(exist_ok=True);(self.root/(ident+'.json')).write_bytes(encoded({'record':r,'sha256':digest(r)}))
  with patch('backend.ai_analysis.infer') as infer:
   reopened=AIJobs(self.root,self.c);self.assertEqual({r['status'] for r in reopened.status()['jobs']},{'failed','uncertain'});self.assertEqual(reopened.threads,{});infer.assert_not_called()
  self.assertTrue(all(loads(p.read_bytes())['record']['history'] for p in self.root.glob('*.json')))
 def test_tamper_fail_closed(self):
  self.root.mkdir();(self.root/('job-'+'a'*32+'.json')).write_text('{"record":{},"sha256":"bad"}')
  reopened=AIJobs(self.root,self.c);self.assertEqual(reopened.status()['issue']['code'],'ai_job_journal_unavailable')
  with self.assertRaises(ValueError):reopened.preview('analysis',{'article_ids':['a']})
  with self.assertRaises(ValueError):reopened.submit({})
 def test_consent_expiry_and_extra_fields_rejected(self):
  p=self.preview()
  for raw in [{},{'preview_id':p['preview_id'],'consent_public_metadata':True},{'preview_id':p['preview_id'],'consent_digest':p['consent_digest']}]:
   with self.assertRaises(ValueError):self.jobs.submit(raw)
  self.jobs.previews[p['preview_id']]['expires']=0
  with self.assertRaises(ValueError):self.submit(p)
  with self.assertRaises(ValueError):self.preview(selection={'article_ids':['a'],'key':'secret'})
  self.assertFalse(self.root.exists())
 def test_changed_inputs_model_budget_roles_block_before_provider(self):
  for change in ['article','model','budget','roles']:
   p=self.preview();before=copy.deepcopy(self.c.repo.ds)
   if change=='article':self.c.repo.ds['articles']['a']['title']+=' 변경'
   elif change=='model':self.c.repo.ds['settings']['app']['ai']['model']='other'
   elif change=='budget':self.c.repo.ds['settings']['app']['ai']['daily_call_limit']=1
   else:self.c.repo.ds['settings']['app']['ai']['enabled_tasks']=['classify']
   with patch('backend.ai_analysis.infer') as infer:
    j=self.submit(p);self.assertEqual(self.finish(j)['status'],'blocked');infer.assert_not_called()
   self.c.repo.ds=before;self.root=Path(self.tmp.name)/change;self.jobs=AIJobs(self.root,self.c)
 def test_failed_attempt_duplicate_no_retry_or_raw_secret(self):
  with patch('backend.ai_analysis.infer',side_effect=ValueError('SYNTHETIC_SECRET')) as infer:
   p=self.preview();j=self.submit(p);self.assertEqual(self.finish(j)['status'],'failed')
   self.assertEqual(self.submit(self.preview())['id'],j['id']);infer.assert_called_once()
  self.assertNotIn('SYNTHETIC_SECRET',(self.root/(j['id']+'.json')).read_text())
 def test_strategy_results_stay_in_versioned_business_source(self):
  before=copy.deepcopy(self.c.repo.ds['articles']);p=self.preview('strategy',{'article_ids':['s'],'company_id':'hanwha-construction','row_ids':['strategy']})
  result=strategy_result();result['cells'][0]['paragraphs'][0]['article_id']='s'
  with patch('backend.ai_analysis.infer',return_value=(result,{'output_tokens':8})):
   done=self.finish(self.submit(p))
  self.assertEqual(done['status'],'completed');self.assertTrue(self.c.repo.ds['ai_runs'][done['run_id']]['summary_ids']);self.assertEqual(before,self.c.repo.ds['articles'])
 def test_classify_and_company_use_existing_evidence_validation_and_keep_sources(self):
  before=copy.deepcopy(self.c.repo.ds['articles'])
  scenarios=[('classify','a','backend.ai_classification.infer',{'classifications':[{'article_id':'a','scope':'unresolved','reason':'근거 부족','quote':''}]}),('company_identity','b','backend.ai_company_identity.infer',{'matches':[]})]
  for task,aid,target,result in scenarios:
   with patch(target,return_value=(result,{})) as infer:
    done=self.finish(self.submit(self.preview(task,{'article_ids':[aid]})));self.assertEqual(done['status'],'completed');infer.assert_called_once()
   self.assertEqual(self.c.repo.ds['ai_runs'][done['run_id']]['task'],task)
  self.assertEqual(before,self.c.repo.ds['articles'])
 def test_thread_start_failure_is_durable_and_never_resubmitted(self):
  p=self.preview()
  with patch('threading.Thread.start',side_effect=RuntimeError('secret')):
   with self.assertRaises(ValueError):self.submit(p)
  record=self.jobs.status()['jobs'][0];self.assertEqual(record['status'],'blocked')
  self.assertEqual(self.submit(self.preview())['id'],record['id'])
 def test_status_does_not_copy_repo_and_shutdown_prevents_submit(self):
  with patch.object(self.c,'read_snapshot',side_effect=AssertionError('must not copy')):self.assertEqual(self.jobs.status()['jobs'],[])
  p=self.preview();self.jobs.stop.set()
  with self.assertRaises(ValueError):self.submit(p)
  self.assertFalse(self.root.exists())

if __name__=='__main__':unittest.main()
