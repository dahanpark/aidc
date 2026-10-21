import json
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from pathlib import Path
from backend.server import AtlasApplication, make_server
from backend.repository import JsonRepository
from backend import reports

ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ('fixtures', 'config'):
            shutil.copytree(ROOT / folder, self.root / folder)
        (self.root / 'frontend').mkdir()
        (self.root / 'frontend' / 'index.html').write_text('<html lang="ko">ATLAS</html>', encoding='utf-8')
        self.app = AtlasApplication(self.root)
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token = self.app.csrf

    def tearDown(self):
        self.app.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, payload=None, headers=None, method=None, raw=None):
        data = (json.dumps(payload).encode() if payload is not None else raw)
        h = {'Content-Type': 'application/json', 'X-Atlas-Token': self.token}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=10) as response:
                body = response.read()
                return response.status, body, response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def state(self):
        return json.loads(self.request('/api/state')[1])

    def test_company_classification_http_persists_without_changing_roles_or_ack(self):
        before = self.app.repo.snapshot()['datasets']
        cid = next(iter(before['companies']))
        self.assertEqual(self.request('/api/company-classification', {'company_id': cid, 'categories': ['operator']}, {'X-Atlas-Token': ''})[0], 403)
        status, raw, _ = self.request('/api/company-classification', {'company_id': cid, 'categories': ['tenant', 'operator'], 'note': 'LOCAL-CLASSIFICATION-NOTE'})
        self.assertEqual(status, 200)
        response = json.loads(raw)['data']
        self.assertEqual(response['profile_categories'], ['tenant', 'operator'])
        self.assertTrue(response['company_profile']['manual_override'])
        state = self.state()['data']
        company = next(item for item in state['companies'] if item['id'] == cid)
        self.assertEqual(company['manual_classification']['categories'], ['tenant', 'operator'])
        current = self.app.repo.snapshot()['datasets']
        for key in ('relationships', 'projects', 'read_states', 'news_read_states', 'bookmarks'):
            self.assertEqual(before.get(key, {}), current.get(key, {}))
        self.assertEqual(self.request('/api/company-classification', {'company_id': cid, 'categories': ['unknown', 'operator']})[0], 400)
        self.assertEqual(self.app.repo.snapshot()['datasets'], current)
        for kind in ('report', 'newsletter', 'csv', 'charter'):
            self.assertNotIn(b'LOCAL-CLASSIFICATION-NOTE', self.request('/api/export?kind=' + kind)[1])
        self.assertEqual(self.request('/api/company-classification', {'company_id': cid, 'reset': True})[0], 200)
        self.assertEqual(len(self.app.repo.snapshot()['datasets']['company_classification_history']), 2)

    def test_get_is_read_only_and_exact_ids_mark_read(self):
        before = self.app.repo.snapshot()
        state = self.state()
        self.assertEqual(self.app.repo.snapshot(), before)
        ids = [c['id'] for c in state['data']['changes']]
        self.assertTrue(ids)
        self.assertEqual(self.request('/api/read', {'change_ids': [ids[0]]})[0], 200)
        self.assertEqual([r['id'] for r in self.state()['data']['read_states']], [ids[0]])
        self.assertEqual(self.request('/api/read', {'change_ids': ['unknown']})[0], 400)
        restarted = JsonRepository(self.root / 'store')
        self.assertIn(ids[0], restarted.snapshot()['datasets']['read_states'])

    def test_company_catalog_keeps_worldwide_choices_and_hides_internal_source(self):
        before = self.app.repo.snapshot()
        status, raw, _ = self.request('/api/state?scope=kr-ai&period=3y&country=KR&city=%EC%9A%B8%EC%82%B0')
        self.assertEqual(status, 200)
        data = json.loads(raw)['data']
        catalog = data['company_catalog']
        self.assertNotIn('_company_catalog_source', data['news'])
        self.assertEqual(catalog['filters']['scope'], 'all')
        self.assertEqual(catalog['filters']['country'], '')
        self.assertEqual(catalog['filters']['city'], '')
        self.assertTrue(any('global-ai' in item['scopes'] for item in catalog['companies']))
        self.assertTrue(any(item['article_count'] > 0 and item['selected_article_count'] == 0 for item in catalog['companies']))
        self.assertIn('equipment_supplier', {item['id'] for item in catalog['role_taxonomy']})
        self.assertEqual(self.app.repo.snapshot(), before)

    def test_graph_company_focus_is_presentation_only_and_unknown_is_ignored(self):
        before = self.app.repo.snapshot()
        status, raw, _ = self.request('/api/state?scope=all&graph_company_id=co-openai')
        self.assertEqual(status, 200)
        data = json.loads(raw)['data']
        self.assertEqual(data['ontology']['company_ontology']['graph']['focus_company_id'], 'co-openai')
        self.assertTrue(data['ontology']['company_ontology']['graph']['focus_node_present'])
        self.assertEqual(data['news']['counts']['articles'], self.state()['data']['news']['counts']['articles'])
        unknown = json.loads(self.request('/api/state?graph_company_id=nonexistent')[1])['data']
        self.assertIsNone(unknown['ontology']['company_ontology']['graph']['focus_company_id'])
        self.assertEqual(self.request('/api/state?graph_company_id=' + 'x' * 201)[0], 400)
        self.assertEqual(self.app.repo.snapshot(), before)

    def test_csrf_origin_host_and_private_file_blocked(self):
        self.assertEqual(self.request('/api/collect', {}, {'X-Atlas-Token': ''})[0], 403)
        self.assertEqual(self.request('/api/collect', {}, {'Origin': 'https://evil.invalid'})[0], 403)
        self.assertEqual(self.request('/api/state', headers={'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(self.request('/%2e%2e/config/brainstorm_decisions.json')[0], 404)
        self.assertEqual(self.request('/store/CURRENT.json')[0], 404)

    def test_bookmarks_internal_notes_do_not_leak_to_export(self):
        state = self.state()['data']
        aid = state['articles'][0]['id']
        company = state['companies'][0]['id']
        self.assertEqual(self.request('/api/bookmarks', {'article_id': aid, 'tags': ['중요'], 'folder': '시장', 'note': 'PRIVATE-BOOKMARK-SECRET'})[0], 200)
        self.assertEqual(self.request('/api/internal-links', {'company_id': company, 'project_ids': [], 'title': 'PRIVATE-TITLE', 'url': 'https://intranet.example/document/1', 'user_note': 'PRIVATE-COMPANY-SECRET'})[0], 200)
        for kind in ('report', 'newsletter', 'csv', 'charter'):
            status, raw, headers = self.request('/api/export?kind=' + kind)
            self.assertEqual(status, 200)
            self.assertNotIn(b'PRIVATE-', raw)
            self.assertNotIn(b'intranet.example', raw)
            if kind != 'charter': self.assertNotIn(b'<script', raw)
        self.assertEqual(self.request('/api/bookmarks/' + aid, {}, method='DELETE')[0], 200)
        self.assertEqual(self.state()['data']['bookmarks'], [])

    def test_one_click_scrap_preserves_notes_and_survives_news_filters(self):
        aid = self.state()['data']['articles'][0]['id']
        self.assertEqual(self.request('/api/bookmarks', {'article_id': aid})[0], 200)
        self.assertEqual(self.request('/api/bookmarks', {'article_id': aid, 'note': 'KEEP-NOTE', 'tags': ['중요'], 'folder': '보관'})[0], 200)
        created = self.state()['data']['bookmarks'][0]['created_at']
        # A stale NEWS tab clicking add must not erase existing user metadata.
        self.assertEqual(self.request('/api/bookmarks', {'article_id': aid})[0], 200)
        data = json.loads(self.request('/api/state?period=1d&scope=global-ai&q=never-matches')[1])['data']
        saved = next(b for b in data['bookmarks'] if b['article_id'] == aid)
        self.assertEqual(saved['note'], 'KEEP-NOTE')
        self.assertEqual(saved['tags'], ['중요'])
        self.assertEqual(saved['created_at'], created)
        self.assertIn(aid, [a['id'] for a in data['articles']])

    def test_recent_news_period_validation_and_get_preserves_reads(self):
        for value in (0, 366, True, '30'):
            self.assertEqual(self.request('/api/settings', {'new_article_days': value})[0], 400)
        self.assertEqual(self.request('/api/settings', {'new_article_days': 14})[0], 200)
        before = self.app.repo.snapshot()['datasets'].get('news_read_states', {})
        self.assertEqual(self.state()['data']['settings']['new_article_days'], 14)
        self.assertEqual(self.app.repo.snapshot()['datasets'].get('news_read_states', {}), before)

    def test_ai_http_connect_status_disconnect_are_mocked_and_readonly_get(self):
        from tests.test_ai import Vault, KEY
        self.app.ai.vault = Vault()
        with patch('backend.ai_connection.request_bytes', return_value=b'{"data":[{"id":"gpt-6-luna"}]}'):
            status, raw, _ = self.request('/api/ai/connect', {'key': KEY})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)['data']['connected'])
            self.assertNotIn(KEY.encode(), raw)
        before = self.app.repo.snapshot()['generation']
        status, raw, _ = self.request('/api/ai/status')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)['data']['connected'])
        self.assertEqual(self.app.repo.snapshot()['generation'], before)
        self.assertNotIn(KEY.encode(), raw)
        self.assertEqual(self.request('/api/ai/disconnect', {})[0], 200)
        self.assertFalse(json.loads(self.request('/api/ai/status')[1])['data']['connected'])
        self.assertEqual(self.request('/api/ai/forget', {})[0], 200)
        self.assertFalse(json.loads(self.request('/api/ai/status')[1])['data']['credential_present'])

    def test_backup_restore_rebuild_and_collection_idempotent(self):
        status, raw, _ = self.request('/api/backup', {})
        self.assertEqual(status, 200)
        filename = json.loads(raw)['data']['filename']
        self.assertEqual(self.request('/api/settings', {'digest_hour': 9})[0], 200)
        self.assertEqual(self.request('/api/restore', {'filename': filename})[0], 200)
        self.assertEqual(self.state()['data']['settings']['digest_hour'], 18)
        self.assertEqual(self.request('/api/index/rebuild', {})[0], 200)
        (self.root / 'derived_index' / 'search.json').unlink()
        self.assertEqual(self.request('/api/index/rebuild', {})[0], 200)
        self.assertTrue((self.root / 'derived_index' / 'search.json').is_file())
        before = len(self.state()['data']['changes'])
        self.assertEqual(self.request('/api/collect', {})[0], 200)
        self.assertEqual(len(self.state()['data']['changes']), before)
        self.assertEqual(self.request('/api/restore', {'filename': '../outside.zip'})[0], 400)

    def test_secrets_rejected_and_no_fake_ai_connection(self):
        before = self.app.repo.snapshot()
        self.assertEqual(self.request('/api/settings', {'api': {'api_key': 'DONT-PERSIST-ME'}})[0], 400)
        self.assertEqual(self.app.repo.snapshot(), before)
        self.assertEqual(self.request('/api/settings', {'api': {'endpoint': 'https://api.example/path?key=secret'}})[0], 400)
        status, raw, _ = self.request('/api/connection/test', {})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(raw)['data']['connected'])
        self.assertNotIn(b'DONT-PERSIST-ME', json.dumps(self.state()).encode())

    def test_invalid_json_and_metadata_xss_are_not_executed(self):
        self.assertEqual(self.request('/api/read', raw=b'{"change_ids":[],"change_ids":[]}')[0], 400)
        self.assertEqual(self.request('/api/read', raw=b'{"value":NaN}')[0], 400)
        self.assertEqual(self.request('/api/internal-links', {'company_id': self.state()['data']['companies'][0]['id'], 'url': 'javascript:alert(1)'})[0], 400)
        status, _, _ = self.request('/api/import', {'title': '<script>alert(1)</script>', 'url': 'https://public.example/entry', 'publisher': 'manual', 'published_at': '2026-10-16', 'summary': '사용자 메타데이터', 'evidence_excerpt': ''})
        self.assertEqual(status, 200)
        raw = self.request('/api/export?kind=newsletter')[1]
        self.assertNotIn(b'<script>alert(1)</script>', raw)
        self.assertIn(b'&lt;script&gt;', raw)

    def test_empty_filter_exports_no_projects_and_explicit_article_is_respected(self):
        status, raw, _ = self.request('/api/export?kind=csv&project_ids=')
        self.assertEqual(status, 200)
        self.assertEqual(len(raw.decode('utf-8-sig').splitlines()), 1)
        self.request('/api/import', {'title': '수동 독립 자료', 'url': 'https://public.example/unbound', 'publisher': 'manual', 'published_at': '2026-10-16', 'summary': '직접 입력'})
        article = next(a for a in self.state()['data']['articles'] if a['title'] == '수동 독립 자료')
        raw = self.request('/api/export?kind=newsletter&project_ids=&article_ids=' + article['id'])[1]
        self.assertIn('수동 독립 자료'.encode(), raw)

    def test_visual_attention_exact_ack_is_atomic_and_survives_repository_reload(self):
        state = self.state()
        items = state['data']['attention']['items']
        self.assertTrue(items)
        before = self.app.repo.snapshot()
        self.assertEqual(self.request('/api/attention/read', {'ids':[items[0]['id'],'unknown']})[0],400)
        self.assertEqual(before, self.app.repo.snapshot())
        target = next(item for item in items if item['unread'])
        self.assertEqual(self.request('/api/attention/read', {'ids':[target['id']]})[0],200)
        after = self.state()['data']
        remaining = {item['id']:item['unread'] for item in after['attention']['items']}
        self.assertFalse(remaining[target['id']])
        self.assertEqual(sum(remaining.values()),sum(item['unread'] for item in items)-1)
        persisted = JsonRepository(self.root/'store').snapshot()['datasets']
        self.assertTrue(all(persisted['read_states'][cid]['read_at'] for cid in target['change_ids']))
        self.assertTrue(all(persisted['notifications'][nid]['read_at'] for nid in target['notification_ids']))
        before_get = self.app.repo.snapshot()
        self.request('/api/state?period=3y&scope=kr-ai')
        self.request('/api/updates')
        self.assertEqual(before_get,self.app.repo.snapshot())

    def test_generation_poll_is_lightweight_and_detects_new_generation(self):
        from unittest.mock import patch
        before=json.loads(self.request('/api/updates')[1])
        with patch.object(self.app,'view_snapshot',side_effect=AssertionError('heavy snapshot read')):
            status,raw,_=self.request('/api/updates')
            self.assertEqual(status,200)
            self.assertEqual(json.loads(raw),before)
        self.request('/api/settings',{'digest_hour':7})
        self.assertNotEqual(json.loads(self.request('/api/updates')[1])['snapshot_id'],before['snapshot_id'])
        self.assertEqual(set(before),{'snapshot_id','version'})

    def test_known_integrity_failure_is_visible_on_state_and_lightweight_poll(self):
        self.app._view_error_pointer = self.app._view_pointer
        for path in ('/api/state', '/api/updates'):
            status, raw, _ = self.request(path)
            self.assertEqual(status, 503)
            result = json.loads(raw)
            self.assertEqual(result['code'], 'store_integrity_error')
            self.assertTrue(result['preserve_last_view'])
        self.assertEqual(self.request('/api/session')[0], 200)

    def test_visual_preferences_are_explicit_validated_and_maps_preserve_scope_counts(self):
        data=self.state()['data']
        self.assertNotIn('visualization',data['settings'])
        self.assertTrue(data['maps']['requires_position_policy'])
        self.assertEqual(set(data['maps']['variants']),{'approximate','exact_only'})
        for policy,workspace in data['maps']['variants'].items():
            self.assertEqual(workspace['counts']['articles'],len(data['news']['articles']))
            self.assertEqual(workspace['counts']['mapped_articles']+workspace['counts']['unlocated_articles'],workspace['counts']['articles'])
            for layer in workspace['scope_layers']:
                self.assertEqual(layer['article_count'],data['ontology']['counts']['scope_articles'][layer['id']])
                if policy=='exact_only': self.assertTrue(all(m['precision']=='exact' for m in layer['markers']))
        before=self.app.repo.snapshot()
        for bad in ({'map_mode':'guess'},{'position_policy':'headquarters'},{'ack_scope':'everything'},{'extra':'value'}):
            self.assertEqual(self.request('/api/settings',{'visualization':bad})[0],400)
            self.assertEqual(self.app.repo.snapshot(),before)
        chosen={'map_mode':'world-inset','position_policy':'exact_only','ack_scope':'items'}
        self.assertEqual(self.request('/api/settings',{'visualization':chosen})[0],200)
        self.assertEqual(self.state()['data']['settings']['visualization'],chosen)

    def test_only_packaged_map_json_is_public(self):
        shutil.copytree(ROOT/'frontend/assets', self.root/'frontend/assets')
        status,raw,headers=self.request('/assets/maps/world.geojson')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['type'],'FeatureCollection')
        self.assertIn('application/geo+json',headers['Content-Type'])
        self.assertEqual(self.request('/assets/maps/positions.json')[0],200)
        for path in ('/config/product_charter.json','/assets/maps/%2e%2e/%2e%2e/%2e%2e/store/CURRENT.json','/assets/maps/attribution.md'):
            self.assertEqual(self.request(path)[0],404)

    def test_lightweight_session_does_not_build_state_and_keeps_origin_guard(self):
        from unittest.mock import patch
        before = self.app.repo.snapshot()
        with patch.object(self.app, 'state', side_effect=AssertionError('heavy state must not run')):
            status, raw, _ = self.request('/api/session')
            self.assertEqual(status, 200)
            session = json.loads(raw)
            self.assertEqual(session['csrf_token'], self.app.csrf)
            self.assertEqual(session['identity'], self.app.identity)
            self.assertNotIn('data', session)
            self.assertEqual(self.request('/api/session', headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.app.repo.snapshot(), before)

    def test_credential_urls_rejected_and_never_exported(self):
        sentinel = 'ATLAS-TEST-SENTINEL'
        fields = ['api_key','access_token','password','authorization','X-Amz-Signature',
                  'X-Goog-Credential','sig','refresh_token','API-Key','%61pi_key']
        company = self.state()['data']['companies'][0]['id']
        for field in fields:
            with self.subTest(parameter=field):
                url = 'https://public.example/release?' + field + '=' + sentinel
                status, raw, _ = self.request('/api/import', {'title':'공개 자료','url':url,'publisher':'manual','published_at':'2026-10-16','summary':'입력'})
                self.assertEqual(status, 400)
                self.assertNotIn(sentinel.encode(), raw)
                self.assertEqual(self.request('/api/internal-links', {'company_id':company,'url':url})[0], 400)
        self.assertEqual(self.request('/api/import', {'title':'자료','url':'https://public.example/release#access_token='+sentinel,'published_at':'2026-10-16','summary':'입력'})[0], 400)
        snapshot = JsonRepository(self.root/'store').snapshot()
        self.assertNotIn(sentinel, json.dumps(snapshot))
        for kind in ('report','newsletter','csv'):
            self.assertNotIn(sentinel.encode(), self.request('/api/export?kind='+kind)[1])
        # Defense in depth for untrusted legacy snapshots that bypass today's ingress.
        legacy = self.app.repo.snapshot()
        aid = next(iter(legacy['datasets']['articles']))
        legacy['datasets']['articles'][aid]['url'] = 'https://public.example/release?access_token='+sentinel
        for kind in ('report','newsletter','csv'):
            raw, _, _ = reports.export(legacy, kind)
            self.assertNotIn(sentinel.encode(), raw)


if __name__ == '__main__':
    unittest.main()
