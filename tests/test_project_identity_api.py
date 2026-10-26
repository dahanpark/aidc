"""REV015 isolated HTTP integration; synthetic nested mentions and no paid provider."""
import copy
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from backend.server import AtlasApplication, make_server
from backend.project_discovery import _stamp

ROOT = Path(__file__).resolve().parents[1]


class ProjectIdentityApiTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'runtime').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='rev015-api-', dir=ROOT / 'runtime')
        self.root = Path(self.temp.name)
        for folder in ('fixtures','config'):
            shutil.copytree(ROOT / folder,self.root / folder)
        (self.root / 'frontend').mkdir()
        (self.root / 'frontend' / 'index.html').write_text('<html>isolated</html>',encoding='utf-8')
        self.app = AtlasApplication(self.root)
        self.server = make_server(self.app,0)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        current = datetime.now(timezone.utc)-timedelta(days=1)
        self.recent = current.isoformat()
        self.old = (current-timedelta(days=500)).isoformat()
        def seed(ds):
            articles = ds.setdefault('articles',{})
            for aid,title,date,source,pids in [
                ('id-a','서울 알파 데이터센터 AI 전용 건립 계획',self.recent,'reuters',['id-p']),
                ('id-b','서울 알파 센터 데이터센터 건립 추진',self.recent,'google_news',[]),
                ('id-c','서울 알파 센터 데이터센터 기존 검토',self.old,'google_news',[]),
                ('id-unrelated','미국 베타 AI 데이터센터 신규 추진',self.recent,'reuters',[])]:
                articles[aid] = {'id':aid,'mode':'live_metadata','title':title,'feed_excerpt':title,
                    'published_at':date,'source_id':source,'publisher':'Synthetic public source',
                    'url':'https://example.com/'+aid,'project_ids':pids,'note':'PRIVATE-NOTE','body':'PRIVATE-BODY'}
            ds.setdefault('projects',{})['id-p'] = {'id':'id-p','name':'알파 데이터센터','city':'서울','country':'KR',
                'location':'서울','scope':'kr-ai','kind':'ai_data_center','article_ids':['id-a'],
                'company_ids':[],'entity_level':'site','phase':'1','capacity':100,'memo':'PRIVATE-MEMO'}
            ds.setdefault('project_mentions',{})['id-b'] = {'id':'id-b','article_id':'id-b',
                'source_hash':_stamp(articles['id-b']), 'mentions':[{'id':'id-m','name':'알파 센터',
                    'article_id':'id-b','article_ids':['id-b','id-c'],'cities':['서울'],'countries':['KR'],
                    'phase':'1','entity_level':'site','evidence':{'article_id':'id-b','field':'title','text':'알파 센터'}}]}
            ds.setdefault('news_updates',{})['id-update'] = {'id':'id-update','article_id':'id-a','company_ids':[],'project_ids':['id-p']}
            ds.setdefault('news_read_states',{})['id-update'] = {'id':'id-update','article_id':'id-a','read_at':self.recent}
            ds.setdefault('bookmarks',{})['id-bookmark'] = {'id':'id-bookmark','article_id':'id-b','note':'PRIVATE-SCRAP'}
        self.app.repo.transact(seed)
        self.payload = {'canonical_ref':'project:id-p','member_refs':['project:id-p','mention:id-m'],
                        'evidence_article_ids':['id-a','id-b']}

    def tearDown(self):
        self.app.stop.set()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self,path,payload=None):
        req = urllib.request.Request(self.base+path,data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type':'application/json','X-Atlas-Token':self.app.csrf})
        try:
            with self.opener.open(req,timeout=20) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())

    def preview(self,payload=None):
        status,reply = self.request('/api/project-identity/preview',payload or self.payload)
        self.assertEqual(status,200,reply)
        return reply['data']

    def confirm(self):
        preview = self.preview()
        self.assertTrue(preview['applicable'])
        status,reply = self.request('/api/project-identity/confirm',{**self.payload,'input_hash':preview['input_hash'],'consent_user_confirmed':True})
        self.assertEqual(status,200,reply)
        return reply['data']['group']

    def news_ids(self,**filters):
        status,reply = self.request('/api/news?'+urllib.parse.urlencode({'scope':'all','period':'3y',**filters}))
        self.assertEqual(status,200,reply)
        return {a['id'] for a in reply['data']['articles']}

    def test_get_and_preview_readonly_without_private_material_or_ai_calls(self):
        before = self.app.repo.snapshot()
        with patch('backend.ai_analysis.infer') as infer:
            status,reply = self.request('/api/project-identities?include_all=true')
            self.assertEqual(status,200)
            self.assertIn('project:id-p',reply['data']['by_ref'])
            self.assertIn('mention:id-m',reply['data']['by_ref'])
            self.assertNotIn('PRIVATE-',json.dumps(reply))
            preview = self.preview()
            self.assertTrue(preview['applicable'])
            self.assertEqual(set(preview['source_article_ids']),{'id-a','id-b','id-c'})
            self.assertFalse(preview['auto_merge']); self.assertFalse(preview['direct_contract_confirmed'])
            self.assertNotIn('PRIVATE-',json.dumps(preview))
            infer.assert_not_called()
        self.assertEqual(self.app.repo.snapshot(),before)

    def test_confirm_consent_hash_missing_conflicting_and_stale_requests_are_atomic(self):
        preview = self.preview()
        before = self.app.repo.snapshot()
        for extra in ({},{'consent_user_confirmed':True},{'consent_user_confirmed':True,'input_hash':'wrong'}):
            self.assertEqual(self.request('/api/project-identity/confirm',{**self.payload,**extra})[0],400)
            self.assertEqual(self.app.repo.snapshot(),before)
        missing = {**self.payload,'member_refs':['project:id-p','mention:missing']}
        view = self.preview(missing); self.assertFalse(view['applicable'])
        self.assertEqual(self.request('/api/project-identity/confirm',{**missing,'consent_user_confirmed':True,'input_hash':view['input_hash']})[0],400)
        self.assertEqual(self.app.repo.snapshot(),before)
        def conflict(ds): ds['project_mentions']['id-b']['mentions'][0]['cities']=['부산']
        self.app.repo.transact(conflict)
        conflict_before = self.app.repo.snapshot(); view = self.preview()
        self.assertIn('cities_conflict',{c['code'] for c in view['conflicts']})
        self.assertEqual(self.request('/api/project-identity/confirm',{**self.payload,'consent_user_confirmed':True,'input_hash':view['input_hash']})[0],400)
        self.assertEqual(self.app.repo.snapshot(),conflict_before)
        def change_source(ds):
            ds['project_mentions']['id-b']['mentions'][0]['cities']=['서울']
            ds['articles']['id-a']['feed_excerpt']+=' 공개 변경'
        self.app.repo.transact(change_source)
        stale_before = self.app.repo.snapshot()
        self.assertEqual(self.request('/api/project-identity/confirm',{**self.payload,'consent_user_confirmed':True,'input_hash':preview['input_hash']})[0],400)
        self.assertEqual(self.app.repo.snapshot(),stale_before)

    def test_confirm_canonical_state_and_undo_preserve_source_facts_and_user_state(self):
        before = self.app.repo.snapshot()['datasets']
        group = self.confirm()
        after = self.app.repo.snapshot()['datasets']
        for dataset in before:
            self.assertEqual(after[dataset],before[dataset],dataset)
        self.assertEqual(group['state'],'approved'); self.assertEqual(len(group['history']),1)
        status,reply = self.request('/api/state?scope=all&period=3y&project_id=id-p')
        self.assertEqual(status,200,reply)
        contexts = reply['data']['identity_display']['contexts']
        context = next(c for c in contexts if c['identity_group_id']==group['id'])
        self.assertEqual(context['name'],'알파 데이터센터')
        self.assertEqual(set(context['identity_article_ids']),{'id-a','id-b','id-c'})
        self.assertEqual(context['source_project_ids'],['id-p'])
        self.assertFalse(reply['data']['identity_display']['source_records_modified'])
        self.assertEqual(self.request('/api/project-identity/undo',{'group_id':group['id']})[0],400)
        status,reply = self.request('/api/project-identity/undo',{'group_id':group['id'],'consent_user_confirmed':True})
        self.assertEqual(status,200,reply)
        self.assertEqual(reply['data']['group']['state'],'revoked')
        self.assertEqual(len(reply['data']['group']['history']),2)
        status,reply = self.request('/api/state?scope=all&period=3y&project_id=id-p')
        self.assertEqual(status,200,reply)
        self.assertNotIn('identity_display',reply['data'])
        self.assertEqual(self.news_ids(project_id='id-p'),{'id-a'})
        restored = self.app.repo.snapshot()['datasets']
        for dataset in before: self.assertEqual(restored[dataset],before[dataset],dataset)

    def test_approved_group_news_union_retains_scope_period_source_constraints(self):
        group = self.confirm()
        self.assertEqual(self.news_ids(project_id='id-p'),{'id-a','id-b','id-c'})
        self.assertEqual(self.news_ids(project_id='identity:'+group['id']),{'id-a','id-b','id-c'})
        self.assertEqual(self.news_ids(project_id='id-p',period='1m'),{'id-a','id-b'})
        self.assertEqual(self.news_ids(project_id='id-p',scope='kr-ai'),{'id-a'})
        self.assertEqual(self.news_ids(project_id='id-p',source_ids='reuters'),{'id-a'})
        self.assertEqual(self.news_ids(project_id='id-p',scope='global-ai'),set())
        status,filtered = self.request('/api/project-identities?scope=kr-ai&period=1m')
        self.assertEqual(status,200)
        self.assertEqual(filtered['data']['active_groups'][0]['article_ids'],['id-a'])
        status,all_refs = self.request('/api/project-identities?include_all=true&scope=global-ai')
        self.assertEqual(status,200)
        self.assertIn('mention:id-m',all_refs['data']['by_ref'])

    def test_backup_restore_preserves_groups_and_action_history(self):
        group = self.confirm()
        expected = copy.deepcopy(self.app.repo.snapshot()['datasets']['project_identity_groups'])
        status,reply = self.request('/api/backup',{})
        self.assertEqual(status,200)
        filename = reply['data']['filename']
        self.assertEqual(self.request('/api/project-identity/undo',{'group_id':group['id'],'consent_user_confirmed':True})[0],200)
        self.assertEqual(self.request('/api/restore',{'filename':filename})[0],200)
        self.assertEqual(self.app.repo.snapshot()['datasets']['project_identity_groups'],expected)
        self.assertEqual(self.request('/api/project-identities?include_all=true')[1]['data']['active_groups'][0]['id'],group['id'])

    def test_startup_migrates_existing_verified_profile_without_changing_user_limits(self):
        previous = {'provider':'mock','model':'synthetic-verified','enabled':True,'verified_at':self.recent,
                    'max_articles_per_run':5,'daily_call_limit':50}
        self.app.repo.transact(lambda ds:ds['settings']['app'].update(ai=copy.deepcopy(previous)))
        with patch('backend.server.AIConnection') as connection:
            restarted = AtlasApplication(self.root)
            try:
                profile = restarted.repo.snapshot()['datasets']['settings']['app']['ai']
                for key,value in previous.items(): self.assertEqual(profile[key],value)
                self.assertEqual(profile['max_input_chars'],8000)
                self.assertEqual(profile['max_output_tokens'],1200)
                self.assertEqual(profile['article_text_chars'],1200)
                self.assertEqual(profile['enabled_tasks'],['extract','compare','briefing','classify','strategy'])
                connection.return_value.connect.assert_not_called()
                connection.return_value.credential.assert_not_called()
            finally: restarted.stop.set()


if __name__ == '__main__':
    unittest.main()
