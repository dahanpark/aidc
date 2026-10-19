from copy import deepcopy
import unittest

from backend import news
from backend.project_discovery import analyse_article, enrich_discovery, build_project_discovery
from backend.repository import JsonRepository


class ProjectDiscoveryTests(unittest.TestCase):
    def article(self, aid='a', title='엔에프디코리아, 당진 송산 300MW AI 데이터센터 캠퍼스 본격 착수'):
        return {'id': aid, 'title': title, 'summary': title, 'url': 'https://example.org/' + aid,
                'publisher': '공개 매체', 'published_at': '2026-10-15T03:00:00Z',
                'domain_relevance': {'status': 'relevant'}, 'scope_classification': {'primary_scope': 'kr-ai'},
                'project_ids': [], 'company_ids': []}

    def test_named_project_capacity_and_stage_all_keep_exact_source_spans(self):
        article = self.article()
        result = analyse_article(article)
        self.assertEqual(len(result['mentions']), 1)
        mention = result['mentions'][0]
        self.assertEqual(mention['name'], '당진 송산 300MW AI 데이터센터')
        self.assertEqual(mention['cities'], ['당진'])
        self.assertFalse(mention['is_confirmed_project'])
        self.assertEqual(mention['company_observations'][0]['name'], '엔에프디코리아')
        self.assertEqual(mention['company_observations'][0]['role'], 'unknown')
        self.assertEqual(mention['capacity_signals'][0]['metric'], 'unspecified')
        self.assertEqual(mention['capacity_signals'][0]['value'], 300)
        self.assertTrue(mention['stage_signals'])
        for evidence in [mention['evidence']] + [item['evidence'] for item in mention['capacity_signals'] + mention['stage_signals'] + mention['company_observations']]:
            self.assertEqual(article[evidence['field']][evidence['start']:evidence['end']], evidence['text'])
            self.assertEqual(evidence['url'], article['url'])

    def test_same_city_different_explicit_names_never_merge_project_identity(self):
        articles = [self.article('a', '개발회사, 포항 A지구 AI 데이터센터 착공'),
                    self.article('b', '개발회사, 포항 B지구 AI 데이터센터 개발'),
                    self.article('c', '다른회사, 포항 A지구 AI 데이터센터 투자')]
        workspace = {'articles': articles}
        result = build_project_discovery({'datasets': {}}, workspace)
        self.assertEqual(len(result['mentions']), 3)
        self.assertEqual(len(result['project_candidates']), 2)
        group = next(item for item in result['project_candidates'] if 'A지구' in item['name'])
        self.assertEqual(set(group['article_ids']), {'a', 'c'})
        self.assertFalse(group['is_confirmed_project'])
        self.assertEqual(group['grouping_basis'], 'exact_normalized_metadata_name_only')

    def test_industry_factories_mass_production_and_people_do_not_create_project_names(self):
        for title in ('삼성전자, 광주에 HVAC 생산라인 착공…AI 데이터센터 냉각 시장 정조준',
                      '세미파이브, 데이터센터용 AI 칩 양산…삼성 4나노 첫 적용',
                      'AI 데이터센터 시장 급성장…포항 기업도 투자 검토',
                      '우상호 "AI 데이터센터 업계 지원하겠다"'):
            with self.subTest(title=title):
                result = analyse_article(self.article(title=title))
                self.assertEqual(result['mentions'], [])
                self.assertFalse(any(item['name'] == '우상호' for item in result['company_observations']))
        for title in ('최태원, 울산 SK AI 데이터센터 현장 점검', '우상호 측, 강릉 AI 데이터센터 의혹 해명',
                      'SKT 정재헌, 울산 AI 데이터센터 방문'):
            self.assertEqual(analyse_article(self.article(title=title))['company_observations'], [])

    def test_durable_analysis_is_idempotent_adds_observation_only_and_get_never_writes(self):
        article = self.article()
        ds = {'articles': {'a': article}, 'companies': {}, 'projects': {}, 'read_states': {'read': {'id': 'read'}},
              'bookmarks': {'bookmark': {'id': 'bookmark'}}}
        enrich_discovery(ds, ['a'])
        self.assertIn('a', ds['project_mentions'])
        self.assertIn('a', ds['company_mentions'])
        self.assertEqual(len(ds['companies']), 1)
        company = next(iter(ds['companies'].values()))
        self.assertEqual(company['classification'], 'observed_name_only')
        self.assertEqual(company['project_ids'], [])
        self.assertNotIn('relationships', ds)
        self.assertEqual(ds['projects'], {})
        before = deepcopy(ds)
        enrich_discovery(ds, ['a'])
        self.assertEqual(ds, before)
        result = build_project_discovery(ds, {'articles': [article]})
        self.assertEqual(result['counts']['persisted_article_analyses'], 1)
        self.assertEqual(ds, before)
        self.assertTrue(result['project_candidates'][0]['company_ids'])
        ds['articles']['a']['title'] += ' 준공'
        enrich_discovery(ds, ['a'])
        self.assertNotEqual(ds['project_mentions']['a']['source_hash'], before['project_mentions']['a']['source_hash'])
        self.assertEqual(ds['read_states'], before['read_states'])
        self.assertEqual(ds['bookmarks'], before['bookmarks'])

    def test_get_fallback_and_selected_article_boundary(self):
        a, b = self.article('a'), self.article('b', 'KT, 군산 AI 데이터센터 추진')
        ds = {'articles': {'a': a, 'b': b}, 'companies': {}}
        before = deepcopy(ds)
        result = build_project_discovery(ds, {'articles': [a]})
        self.assertEqual(result['counts']['derived_article_analyses'], 1)
        self.assertEqual({item['article_id'] for item in result['mentions']}, {'a'})
        self.assertEqual(ds, before)

    def test_mention_article_reference_validated(self):
        with self.assertRaisesRegex(ValueError, 'Dangling reference'):
            JsonRepository.validate({'project_mentions': {'ghost': {'id': 'ghost', 'article_id': 'missing'}}})

    def test_attached_ai_and_domestic_regions_classify_without_factory_city_false_positive(self):
        for title in ('SK 7兆 울산 AI데이터센터 지분매각', 'SK 추진 대구 AI데이터센터 무산',
                      'GS 강원 AI데이터센터 추진', '해남 솔라시도 AI데이터센터 착공'):
            with self.subTest(title=title):
                classification = news.classify_article(self.article(title=title))
                self.assertEqual(classification['scope_classification']['primary_scope'], 'kr-ai')
        result = news._geography(self.article(title='세미파이브, 데이터센터용 AI 칩 양산…삼성 4나노 첫 적용'), {})
        self.assertNotIn('양산', result['cities'])
        result = news._geography(self.article(title='경남 양산 AI 데이터센터 착공'), {})
        self.assertIn('양산', result['cities'])

    def test_foreign_dc_korean_company_and_foreign_city_do_not_become_domestic(self):
        for title in ('삼성전자, 미국 AI데이터센터 전력장비 공급', 'LG전자, 일본 AI데이터센터 냉각사업 확대',
                      '한국전력, UAE AI데이터센터 전력 공급'):
            with self.subTest(title=title):
                article = self.article(title=title)
                self.assertEqual(news.classify_article(article)['scope_classification']['primary_scope'], 'global-ai')
                self.assertEqual(analyse_article(article)['mentions'], [])
        article = self.article(title='서울반도체, 미국 AI데이터센터용 광소자 공급')
        self.assertEqual(analyse_article(article)['mentions'], [])


if __name__ == '__main__':
    unittest.main()
