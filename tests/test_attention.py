from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from backend.attention import build_attention, apply_acknowledgement, attention_annotation, recent_article
from backend.ontology import build_ontology
from backend.repository import JsonRepository


STAMP = '2026-10-17T01:00:00+00:00'


class AttentionTests(unittest.TestCase):
    def test_recency_is_publication_based_and_does_not_erase_old_unread(self):
        ds = self.ds()
        ds['articles']['a']['published_at'] = '2026-07-01T00:00:00Z'
        ds['articles']['a']['collected_at'] = STAMP
        workspace = self.workspace(ds)
        workspace['filters'] = {'end': STAMP}
        attention = build_attention(ds, workspace)
        old = next(a for a in attention['items'] if a['id'] == 'new_article:a')
        self.assertTrue(old['unread'])
        self.assertFalse(old['is_recent'])
        self.assertEqual(attention['counts']['unread_new_articles'], 2)
        self.assertEqual(attention['graph']['companies']['c']['new_article_count'], 1)
        self.assertEqual(ds['news_read_states'], {})
        ds['settings'] = {'app': {'id': 'app', 'new_article_days': 150}}
        self.assertTrue(recent_article(ds['articles']['a'], ds, STAMP))
        self.assertFalse(recent_article({'published_at': '2027-01-01T00:00:00Z'}, ds, STAMP))

    def ds(self):
        articles = {aid: {'id': aid, 'title': 'AI 데이터센터 ' + aid, 'url': 'https://example.org/' + aid,
            'published_at': '2026-10-16T01:00:00+00:00', 'mode': 'live_metadata', 'project_ids': ['p'],
            'company_ids': ['c'], 'candidate_project_ids': [], 'business_categories': ['냉각'],
            'scope_classification': {'primary_scope': 'kr-ai'}, 'geography': {'countries': ['KR'], 'cities': ['서울']}}
            for aid in ('a', 'b')}
        return {'articles': articles,
            'projects': {'p': {'id': 'p', 'name': '등록 사업', 'scope': 'kr-ai', 'country': 'KR', 'location': '서울',
                'company_ids': ['c'], 'article_ids': ['a', 'b'], 'parent_id': None}},
            'companies': {'c': {'id': 'c', 'name': '관측 기업', 'project_ids': ['p']}},
            'relationships': {},
            'news_updates': {f'u-{aid}': {'id': f'u-{aid}', 'article_id': aid, 'company_ids': ['c'],
                'project_ids': ['p'], 'created_at': '2026-10-16T02:00:00+00:00'} for aid in articles},
            'news_read_states': {}, 'read_states': {},
            'changes': {'ch': {'id': 'ch', 'project_id': 'p', 'article_ids': ['a'],
                'summary': ['등록된 용량 변경'], 'kind': 'capacity_change', 'created_at': '2026-10-16T03:00:00+00:00'}},
            'notifications': {nid: {'id': nid, 'change_id': 'ch', 'project_id': 'p', 'read_at': None}
                for nid in ('notice-one', 'notice-two')}}

    def workspace(self, ds, aids=('a', 'b')):
        return {'articles': [deepcopy(ds['articles'][aid]) for aid in aids], 'filters': {'scope': 'all'}}

    def test_unified_counts_do_not_duplicate_notifications_or_call_news_fact_changes(self):
        ds = self.ds()
        before = deepcopy(ds)
        attention = build_attention({'datasets': ds}, self.workspace(ds))
        self.assertEqual(attention['counts'], {'total': 3, 'unread': 3, 'new_articles': 2,
            'fact_changes': 1, 'unread_new_articles': 2, 'unread_fact_changes': 1})
        new = next(item for item in attention['items'] if item['type'] == 'new_article')
        self.assertFalse(new['is_verified_fact_change'])
        change = next(item for item in attention['items'] if item['type'] == 'fact_change')
        self.assertEqual(change['notification_ids'], ['notice-one', 'notice-two'])
        self.assertEqual(ds, before)
        self.assertFalse(attention['read_on_get'])

    def test_attention_uses_exact_same_filtered_article_set(self):
        ds = self.ds()
        attention = build_attention(ds, self.workspace(ds, ('b',)))
        self.assertEqual(attention['counts']['total'], 1)
        self.assertEqual(attention['counts']['fact_changes'], 0)
        self.assertEqual(attention['items'][0]['id'], 'new_article:b')
        self.assertNotIn('a', attention['graph']['articles'])

    def test_ack_exact_article_does_not_ack_company_other_article_or_fact_change(self):
        ds = self.ds()
        result = apply_acknowledgement(ds, ['new_article:a'], STAMP)
        self.assertEqual(result['news_update_ids'], ['u-a'])
        self.assertEqual(ds['news_read_states']['u-a']['read_at'], STAMP)
        self.assertNotIn('u-b', ds['news_read_states'])
        self.assertEqual(ds['read_states'], {})
        self.assertIsNone(ds['notifications']['notice-one']['read_at'])
        attention = build_attention(ds, self.workspace(ds))
        self.assertEqual(attention['counts']['unread_new_articles'], 1)
        self.assertEqual(attention['counts']['unread_fact_changes'], 1)

    def test_ack_change_updates_original_change_and_all_deliveries_only(self):
        ds = self.ds()
        result = apply_acknowledgement(ds, ['fact_change:ch'], STAMP)
        self.assertEqual(result['change_ids'], ['ch'])
        self.assertEqual(ds['read_states']['ch']['read_at'], STAMP)
        self.assertTrue(all(notice['read_at'] == STAMP for notice in ds['notifications'].values()))
        self.assertEqual(ds['news_read_states'], {})
        attention = build_attention(ds, self.workspace(ds))
        self.assertEqual(attention['counts']['unread'], 2)
        self.assertEqual(attention['counts']['unread_fact_changes'], 0)

    def test_invalid_or_outside_allowed_ids_never_partially_write(self):
        for ids, allowed in [(['new_article:a', 'not-valid'], None),
                             (['new_article:a', 'fact_change:missing'], None),
                             (['new_article:a'], ['new_article:b'])]:
            ds = self.ds()
            before = deepcopy(ds)
            with self.assertRaises(ValueError):
                apply_acknowledgement(ds, ids, STAMP, allowed)
            self.assertEqual(ds, before)

    def test_article_id_is_stable_with_duplicate_update_sources_and_ack_is_idempotent(self):
        ds = self.ds()
        ds['news_updates']['extra'] = {**ds['news_updates']['u-a'], 'id': 'extra'}
        attention = build_attention(ds, self.workspace(ds))
        self.assertEqual(attention['counts']['new_articles'], 2)
        apply_acknowledgement(ds, ['new_article:a', 'new_article:a'], STAMP)
        self.assertEqual(set(ds['news_read_states']), {'u-a', 'extra'})
        before = deepcopy(ds)
        apply_acknowledgement(ds, ['new_article:a'], '2026-10-18T01:00:00+00:00')
        self.assertEqual(ds, before)

    def test_read_change_and_unread_delivery_remain_one_pending_item(self):
        ds = self.ds()
        ds['read_states']['ch'] = {'id': 'ch', 'read_at': STAMP}
        attention = build_attention(ds, self.workspace(ds))
        change = next(item for item in attention['items'] if item['type'] == 'fact_change')
        self.assertTrue(change['unread'])
        ds['notifications']['notice-one']['read_at'] = STAMP
        ds['notifications']['notice-two']['read_at'] = STAMP
        attention = build_attention(ds, self.workspace(ds))
        self.assertFalse(next(item for item in attention['items'] if item['type'] == 'fact_change')['unread'])

    def test_orphan_notification_does_not_invent_a_fact_change(self):
        ds = self.ds()
        ds['notifications']['orphan'] = {'id': 'orphan', 'change_id': 'absent', 'read_at': None}
        attention = build_attention(ds, self.workspace(ds))
        self.assertEqual(attention['counts']['fact_changes'], 1)
        self.assertEqual(attention['orphan_notification_ids'], ['orphan'])

    def test_graph_annotations_clear_only_after_exact_ack_and_never_on_get(self):
        ds = self.ds()
        before = deepcopy(ds)
        ontology = build_ontology(ds, self.workspace(ds))
        company = next(node for node in ontology['company_ontology']['nodes'] if node['id'] == 'company:c')
        self.assertEqual(company['unread_count'], 3)
        self.assertEqual(company['new_article_count'], 2)
        self.assertEqual(company['fact_change_count'], 1)
        self.assertEqual(ds, before)
        apply_acknowledgement(ds, company['unread_attention_ids'], STAMP)
        ontology = build_ontology(ds, self.workspace(ds))
        self.assertTrue(all(not node['has_unread'] for node in ontology['company_ontology']['nodes']))
        self.assertTrue(all(not edge['has_unread'] for edge in ontology['company_ontology']['edges']))

    def test_ack_persists_in_original_json_datasets_across_repository_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'store'
            repo = JsonRepository(root)
            repo.transact(lambda ds: ds.update(deepcopy(self.ds())))
            repo.transact(lambda ds: apply_acknowledgement(ds, ['new_article:a', 'fact_change:ch'], STAMP))
            snapshot = JsonRepository(root).snapshot()
            ds = snapshot['datasets']
            self.assertEqual(ds['news_read_states']['u-a']['read_at'], STAMP)
            self.assertEqual(ds['read_states']['ch']['read_at'], STAMP)
            self.assertEqual(ds['notifications']['notice-one']['read_at'], STAMP)
            self.assertEqual(build_attention(snapshot, self.workspace(ds))['counts']['unread'], 1)

    def test_project_attention_does_not_borrow_other_project_changes_from_shared_article(self):
        ds = self.ds()
        ds['projects']['other'] = {**ds['projects']['p'], 'id': 'other', 'name': '별도 사업'}
        ds['articles']['a']['project_ids'].append('other')
        ds['changes']['other-change'] = {**ds['changes']['ch'], 'id': 'other-change', 'project_id': 'other'}
        workspace = self.workspace(ds, ('a',))
        ontology = build_ontology(ds, workspace)
        project = next(node for node in ontology['company_ontology']['nodes'] if node['id'] == 'project:p')
        self.assertEqual(project['new_article_count'], 1)
        self.assertEqual(project['fact_change_count'], 1)
        self.assertNotIn('fact_change:other-change', project['attention_ids'])
        attention = ontology['attention']
        annotation = attention_annotation(attention, article_ids=['a'], restrict_project_ids=['p'])
        self.assertEqual(annotation['fact_change_count'], 1)


if __name__ == '__main__':
    unittest.main()
