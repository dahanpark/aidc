from copy import deepcopy
import unittest

from backend.company_profiles import build_company_profile, descriptor_observations
from backend.project_discovery import analyse_article, enrich_discovery, build_project_discovery
from backend.ontology import build_ontology, _roles
from backend.company_catalog import build_company_catalog


class CompanyProfileAndLinkTests(unittest.TestCase):
    def article(self, title, cid='builder'):
        return {'id': 'a', 'title': title, 'url': 'https://example.org/a', 'publisher': '공개 매체',
            'published_at': '2026-10-18T01:00:00Z', 'company_ids': [cid] if cid else [], 'project_ids': [],
            'domain_relevance': {'status': 'relevant'}, 'scope_classification': {'primary_scope': 'kr-ai'}}

    def datasets(self, article):
        return {'articles': {'a': article}, 'companies': {'builder': {'id': 'builder', 'name': '한빛건설'}},
            'projects': {}, 'relationships': {}, 'bookmarks': {'b': {'id': 'b'}},
            'news_read_states': {'r': {'id': 'r'}}}

    def test_company_profile_never_establishes_project_role(self):
        article = self.article('한빛건설, 울산 AI 데이터센터 현장 점검')
        ds = self.datasets(article)
        ds['companies']['builder']['role'] = 'operator'
        enrich_discovery(ds, ['a'])
        self.assertEqual(ds['companies']['builder']['profile_categories'], ['operator'])
        self.assertEqual(ds['companies']['builder']['profile_evidence'][0]['status'], 'registered_metadata')
        result = build_ontology(ds, {'articles': [article], 'filters': {}})
        self.assertEqual(result['companies'][0]['roles'], ['unknown'])
        self.assertEqual(result['companies'][0]['profile_categories'], ['operator'])
        catalog = build_company_catalog(ds, {'articles': [article]}, {'companies': ds['companies'], 'articles': [article]})
        self.assertEqual(catalog['companies'][0]['roles'], ['unknown'])
        self.assertEqual(catalog['companies'][0]['profile_categories'], ['operator'])

    def test_new_company_name_classification_is_a_proposal_with_provenance(self):
        article = self.article('새별건설, 군산 AI 데이터센터 착공', cid=None)
        ds = self.datasets(article)
        original = deepcopy((ds['projects'], ds['relationships'], ds['bookmarks'], ds['news_read_states']))
        enrich_discovery(ds, ['a'])
        company = next(item for item in ds['companies'].values() if item['name'] == '새별건설')
        self.assertEqual(company['profile_categories'], ['contractor'])
        self.assertEqual(company['profile_evidence'][0]['status'], 'classification_proposal')
        self.assertEqual(company['profile_evidence'][0]['article_ids'], ['a'])
        self.assertEqual(company['role'], '미확인')
        self.assertEqual((ds['projects'], ds['relationships'], ds['bookmarks'], ds['news_read_states']), original)
        link = build_project_discovery(ds, {'articles': [article]})['company_links'][0]
        self.assertEqual(link['role'], 'unknown')  # Groundbreaking alone is not builder attribution.
        self.assertEqual(link['status'], 'cooccurrence_observation')
        self.assertFalse(link['is_confirmed_participation'])

    def test_attached_descriptor_and_source_correction_refresh_static_nature(self):
        article = self.article('운영사 한빛건설, 울산 AI 데이터센터 현장 점검')
        ds = self.datasets(article)
        enrich_discovery(ds, ['a'])
        self.assertEqual(ds['companies']['builder']['profile_categories'], ['operator'])
        evidence = ds['companies']['builder']['profile_evidence'][0]
        self.assertEqual(evidence['status'], 'metadata_descriptor')
        self.assertEqual(article['title'][evidence['evidence']['start']:evidence['evidence']['end']], evidence['evidence']['text'])
        ds['articles']['a']['title'] = '한빛건설, 울산 AI 데이터센터 현장 점검'
        enrich_discovery(ds, ['a'])
        self.assertEqual(ds['companies']['builder']['profile_categories'], ['contractor'])
        self.assertTrue(all(item['status'] == 'classification_proposal' for item in ds['companies']['builder']['profile_evidence']))
        before = deepcopy(ds)
        enrich_discovery(ds, ['a'])
        self.assertEqual(ds, before)

    def test_single_subject_role_signal_is_reviewable_and_not_registered(self):
        article = self.article('한빛건설, 울산 AI 데이터센터 시공 수주')
        ds = self.datasets(article)
        enrich_discovery(ds, ['a'])
        view = build_project_discovery(ds, {'articles': [article]})
        candidate = view['project_candidates'][0]
        link = candidate['company_links'][0]
        self.assertEqual(link['project_id'], candidate['id'])
        self.assertEqual(link['role'], 'contractor')
        self.assertEqual(link['status'], 'role_observation')
        self.assertFalse(link['direct_contract_confirmed'])
        self.assertFalse(link['is_confirmed_participation'])
        self.assertEqual(link['article_ids'], ['a'])
        for span in link['evidence']:
            self.assertEqual(article[span['field']][span['start']:span['end']], span['text'])
        self.assertEqual(ds['relationships'], {})

    def test_explicit_descriptor_can_discover_a_new_name_without_industry_suffix(self):
        article = self.article('데이터센터 운영사 메가존, 울산 AI 데이터센터 현장 점검', cid=None)
        ds = self.datasets(article)
        enrich_discovery(ds, ['a'])
        company = next(item for item in ds['companies'].values() if item['name'] == '메가존')
        self.assertEqual(company['profile_categories'], ['operator'])
        self.assertEqual(company['profile_evidence'][0]['basis'], 'explicit_company_noun_descriptor')
        self.assertEqual(company['classification'], 'observed_name_only')

    def test_ambiguous_activity_does_not_create_nature_proposal_or_participation(self):
        for title in ('한빛건설, 울산 AI 데이터센터 시공 참여 부인',
                      '한빛건설, 울산 AI 데이터센터 시공 취소',
                      '한빛건설, 울산 AI 데이터센터 착공…군산 시공 수주'):
            article = self.article(title)
            ds = self.datasets(article)
            enrich_discovery(ds, ['a'])
            links = build_project_discovery(ds, {'articles': [article]})['company_links']
            self.assertTrue(all(item['role'] == 'unknown' for item in links))
            evidence = ds['companies']['builder']['profile_evidence']
            self.assertFalse(any(item['basis'] == 'metadata_activity_type_proposal' for item in evidence))

    def test_multicompany_and_multisite_headlines_do_not_assign_a_shared_verb(self):
        article = self.article('한빛건설·새봄증권, 울산 AI 데이터센터 시공 수주')
        article['company_ids'].append('bank')
        ds = self.datasets(article)
        ds['companies']['bank'] = {'id': 'bank', 'name': '새봄증권'}
        enrich_discovery(ds, ['a'])
        links = build_project_discovery(ds, {'articles': [article]})['company_links']
        self.assertEqual({item['role'] for item in links}, {'unknown'})
        self.assertEqual({item['company_id'] for item in links}, {'builder', 'bank'})
        article['title'] = '한빛건설, 울산 AI 데이터센터 및 군산 AI 데이터센터 시공 수주'
        article['company_ids'] = ['builder']
        enrich_discovery(ds, ['a'])
        links = build_project_discovery(ds, {'articles': [article]})['company_links']
        self.assertEqual({item['role'] for item in links}, {'unknown'})

    def test_pf_role_signal_is_distinct_from_bank_nature(self):
        self.assertEqual(_roles('PF 주선사'), ['financier'])
        self.assertEqual(_roles('financial arranger'), ['financier'])
        company = {'id': 'bank', 'name': '새봄증권'}
        self.assertEqual(build_company_profile(company)['profile_categories'], ['financier'])
        article = self.article('새봄증권, 울산 AI 데이터센터 PF 주선', 'bank')
        ds = self.datasets(article)
        ds['companies']['bank'] = company
        enrich_discovery(ds, ['a'])
        self.assertEqual(build_project_discovery(ds, {'articles': [article]})['company_links'][0]['role'], 'financier')

    def test_multiple_registered_projects_do_not_receive_one_sites_role(self):
        article = self.article('한빛건설, 울산 AI 데이터센터 시공 수주')
        article['project_ids'] = ['p', 'q']
        ds = self.datasets(article)
        ds['projects'] = {'p': {'id': 'p', 'name': '울산'}, 'q': {'id': 'q', 'name': '다른사업'}}
        enrich_discovery(ds, ['a'])
        before = deepcopy(ds)
        links = build_project_discovery(ds, {'articles': [article]})['company_links']
        registered = [item for item in links if not item['project_is_candidate']]
        self.assertEqual({item['role'] for item in registered}, {'unknown'})
        self.assertEqual(ds, before)


if __name__ == '__main__':
    unittest.main()
