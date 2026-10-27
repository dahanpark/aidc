"""Loopback routes and durable confirmations against an isolated store."""
import json
from tests import test_rev014_api as base
from tests.test_ai_cleanup import sample

class CleanupApiTests(base.Rev014ApiTests):
    def test_cleanup_routes_confirm_projection_undo_and_bad_request(self):
        data=sample()
        def seed(ds):
            for key in ('articles','companies','ai_runs'):ds.setdefault(key,{}).update(data[key])
        self.app.repo.transact(seed)
        before=self.app.repo.snapshot()['datasets']
        self.assertEqual(self.request('/api/ai/cleanup?period=3y')[0],200)
        self.assertNotEqual(self.request('/api/ai/scope-decision',{'run_id':'class','article_id':'a','confirmed':False})[0],200)
        self.assertEqual(self.request('/api/ai/scope-decision',{'run_id':'class','article_id':'a','confirmed':True})[0],200)
        payload={'run_id':'company','match_id':data['ai_runs']['company']['result']['matches'][0]['id']}
        status,body=self.json_request('/api/company-identity/preview',payload);self.assertEqual(status,200)
        preview=body['data']
        self.assertEqual(self.request('/api/company-identity/confirm',{**payload,'preview_hash':preview['preview_hash'],'confirmed':True})[0],200)
        status,body=self.json_request('/api/state?period=3y&scope=all');self.assertEqual(status,200)
        self.assertEqual(body['data']['company_identity_map'].get('right'),'left')
        self.assertEqual(self.request('/api/company-identity/undo',{'group_id':preview['group_id']})[0],200)
        self.assertEqual(self.request('/api/ai/scope-decision',{'article_id':'a','action':'undo'})[0],200)
        after=self.app.repo.snapshot()['datasets']
        for key in ('articles','companies','projects','bookmarks','read_states','news_read_states'):self.assertEqual(before.get(key),after.get(key),key)
