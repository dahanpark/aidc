from copy import deepcopy
import unittest

from backend import news
from backend.company_catalog import build_company_catalog


class CompanyCatalogTests(unittest.TestCase):
    def source(self):
        companies = {'domestic': {'id': 'domestic', 'name': '국내 관측 기업'},
                     'foreign': {'id': 'foreign', 'name': '해외 관측 기업', 'role': 'operator'},
                     'unused': {'id': 'unused', 'name': '선택 기간 기사 없는 등록기업'}}
        projects = {'project': {'id': 'project', 'name': '울산 AIDC', 'scope': 'kr-ai', 'company_ids': ['domestic']}}
        articles = [{'id': 'kr', 'title': '국내 울산 AI 데이터센터 건설', 'company_ids': ['domestic'],
                     'project_ids': ['project'], 'published_at': '2026-10-15T02:00:00Z',
                     'scope_classification': {'primary_scope': 'kr-ai'}},
                    {'id': 'global', 'title': '미국 AI 데이터센터 건설', 'company_ids': ['foreign'],
                     'project_ids': [], 'published_at': '2026-10-14T02:00:00Z',
                     'scope_classification': {'primary_scope': 'global-ai'}}]
        ds = {'companies': companies, 'projects': projects, 'relationships': {}}
        source = {'companies': companies, 'articles': articles}
        workspace = {'articles': [articles[0]], 'filters': {'period': '3y', 'q': 'AI', 'source_ids': ['reuters'],
            'scope': 'kr-ai', 'company_id': 'domestic', 'country': 'KR', 'city': '울산'}}
        return ds, source, workspace

    def test_global_choices_survive_domestic_selected_scope_and_company(self):
        ds, source, workspace = self.source()
        before = deepcopy((ds, source, workspace))
        catalog = build_company_catalog(ds, workspace, source)
        companies = {item['id']: item for item in catalog['companies']}
        self.assertEqual(set(companies), {'domestic', 'foreign'})
        self.assertEqual(companies['foreign']['scopes'], ['global-ai'])
        self.assertEqual(companies['foreign']['selected_article_count'], 0)
        self.assertFalse(companies['foreign']['in_selected_scope'])
        self.assertEqual(companies['foreign']['roles'], ['unknown'])
        self.assertEqual(catalog['filters']['q'], 'AI')
        self.assertEqual(catalog['filters']['source_ids'], ['reuters'])
        self.assertEqual(catalog['filters']['country'], '')
        self.assertEqual(catalog['filters']['city'], '')
        self.assertEqual(catalog['filters']['scope'], 'all')
        self.assertEqual((ds, source, workspace), before)

    def test_explicit_equipment_role_needs_same_verified_project_and_article(self):
        ds, source, workspace = self.source()
        ds['relationships']['equipment'] = {'id': 'equipment', 'project_id': 'project', 'company_id': 'domestic',
            'role': 'equipment_supplier', 'directness': 'explicit', 'article_ids': ['kr']}
        catalog = build_company_catalog(ds, workspace, source)
        company = next(item for item in catalog['companies'] if item['id'] == 'domestic')
        self.assertEqual(company['roles'], ['equipment_supplier'])
        self.assertEqual(company['role_evidence'][0]['article_ids'], ['kr'])
        source['articles'][0].update(project_ids=[], candidate_project_ids=['project'])
        catalog = build_company_catalog(ds, workspace, source)
        company = next(item for item in catalog['companies'] if item['id'] == 'domestic')
        self.assertEqual(company['roles'], ['unknown'])
        self.assertEqual(company['role_evidence'], [])

    def test_duplicate_articles_count_once_and_newly_observed_names_resolve(self):
        ds, source, workspace = self.source()
        source['articles'].append(deepcopy(source['articles'][1]))
        source['companies'] = {**source['companies'], 'new': {'id': 'new', 'name': '신규 기사 기업'}}
        source['articles'][1]['company_ids'].append('new')
        source['articles'][2]['company_ids'].append('new')
        catalog = build_company_catalog(ds, workspace, source)
        self.assertEqual(catalog['counts']['articles'], 2)
        company = next(item for item in catalog['companies'] if item['id'] == 'new')
        self.assertEqual(company['name'], '신규 기사 기업')
        self.assertEqual(company['article_count'], 1)

    def test_workspace_catalog_pass_keeps_search_constraints_without_scope_place_company(self):
        ds, source, workspace = self.source()
        ds['articles'] = {}
        for article in source['articles']:
            article.update(url='https://www.reuters.com/' + article['id'], publisher='Reuters', source_id='reuters',
                           summary='공개 메타데이터', mode='live_metadata')
            ds['articles'][article['id']] = article
        ds['articles']['wrong-source'] = {**deepcopy(source['articles'][1]), 'id': 'wrong-source', 'source_id': 'other'}
        ds['articles']['old'] = {**deepcopy(source['articles'][1]), 'id': 'old', 'published_at': '2020-01-01T00:00:00Z'}
        result = news.build_workspace(ds, workspace['filters'], '2026-10-16T03:00:00Z', include_catalog=True)
        self.assertEqual({item['id'] for item in result['articles']}, {'kr'})
        catalog_source = result.pop('_company_catalog_source')
        self.assertEqual({item['id'] for item in catalog_source['articles']}, {'kr', 'global'})
        self.assertNotIn('_company_catalog_source', news.build_workspace(ds, workspace['filters'], '2026-10-16T03:00:00Z'))
        result = news.build_workspace(ds, {**workspace['filters'], 'project_id': 'project'}, '2026-10-16T03:00:00Z', include_catalog=True)
        self.assertEqual({item['id'] for item in result['_company_catalog_source']['articles']}, {'kr'})


if __name__ == '__main__':
    unittest.main()
