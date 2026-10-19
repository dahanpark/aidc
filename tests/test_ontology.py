from copy import deepcopy
import json
from pathlib import Path
import unittest

from backend.ontology import build_ontology, MAX_GRAPH_NODES


class OntologyTests(unittest.TestCase):
    def ds(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/official_manual_gold.json').read_text(encoding='utf-8'))
        return {kind: {item['id']: item for item in fixture[kind]}
                for kind in ('articles', 'projects', 'companies', 'claims', 'relationships')}

    def article(self, aid, primary_scope='kr-dc', companies=None, countries=None, cities=None, **extra):
        result = {'id': aid, 'title': '공개 데이터센터 기사 ' + aid, 'url': 'https://example.org/' + aid,
                  'published_at': '2026-10-15T12:00:00Z', 'publisher': 'Public media',
                  'summary': '공개 메타데이터', 'mode': 'live_metadata', 'project_ids': [], 'candidate_project_ids': [],
                  'company_ids': companies or [], 'geography': {'countries': countries or [], 'cities': cities or []},
                  'scope_classification': {'primary_scope': primary_scope, 'status': 'classified' if primary_scope else 'unresolved'}}
        result.update(extra)
        return result

    def ontology(self, articles, ds=None, **filters):
        return build_ontology({'datasets': ds or self.ds()}, {'articles': articles, 'filters': {'scope': 'all', **filters}})

    def test_mutually_exclusive_scope_counts_and_unknown(self):
        articles = [self.article('a', 'kr-dc'), self.article('b', 'kr-ai'),
                    self.article('c', 'global-ai'), self.article('d', None, scope='kr-dc')]
        # A classification's unresolved result wins over a legacy scope.
        result = self.ontology(articles)
        self.assertEqual(result['counts']['scope_articles'], {'kr-dc': 1, 'kr-ai': 1, 'global-ai': 1, 'unresolved': 1})
        self.assertEqual(sum(result['counts']['scope_articles'].values()), result['counts']['articles'])
        self.assertEqual(set(result['article_refs']), {'a', 'b', 'c', 'd'})

    def test_real_article_count_never_becomes_four_fixture_projects(self):
        articles = [self.article(f'a{i}', 'kr-ai', companies=['co-skt'], cities=['울산'], countries=['KR']) for i in range(768)]
        result = self.ontology(articles)
        self.assertEqual(result['counts']['articles'], 768)
        self.assertEqual(result['counts']['registered_projects'], 4)
        self.assertEqual(result['counts']['verified_projects'], 0)
        self.assertEqual(result['counts']['pending_articles'], 768)
        self.assertEqual(result['pending_groups'][0]['article_count'], 768)
        self.assertFalse(result['pending_groups'][0]['is_confirmed_project'])
        self.assertEqual(result['companies'][0]['article_count'], 768)
        self.assertEqual(len(result['companies'][0]['article_ids']), 768)
        self.assertFalse(any(edge['type'] == 'registered_participation' for edge in result['edges']))

    def test_registered_program_phase_and_selected_evidence_roles(self):
        ds = self.ds()
        articles = deepcopy(list(ds['articles'].values()))
        for article in articles:
            project = ds['projects'][article['project_ids'][0]]
            article['scope_classification'] = {'primary_scope': project['scope']}
            article['geography'] = {'countries': [project['country']], 'cities': []}
        result = self.ontology(articles, ds)
        self.assertEqual(result['counts']['articles'], 3)
        self.assertEqual(result['counts']['verified_projects'], 4)
        self.assertEqual(result['counts']['verified_project_articles'], 3)
        self.assertEqual(result['counts']['pending_articles'], 0)
        hierarchy = [edge for edge in result['edges'] if edge['type'] == 'project_hierarchy']
        self.assertEqual(len(hierarchy), 1)
        self.assertEqual(hierarchy[0]['target'], 'project:prj-stargate-uae-phase1')
        roles = [edge for edge in result['edges'] if edge['type'] == 'registered_participation']
        self.assertEqual(len(roles), 11)
        self.assertTrue(all(set(edge['article_ids']) <= set(result['article_refs']) for edge in roles))
        self.assertNotIn('capacity_total', result['counts'])

    def test_name_candidate_never_inherits_registered_participation(self):
        article = self.article('candidate', 'kr-ai', companies=['co-skt'], cities=['울산'],
                               candidate_project_ids=['prj-ulsan'])
        result = self.ontology([article])
        project = next(project for project in result['projects'] if project['id'] == 'prj-ulsan')
        self.assertEqual(project['candidate_article_ids'], ['candidate'])
        self.assertEqual(project['verified_article_ids'], [])
        self.assertEqual(result['counts']['candidate_project_articles'], 1)
        self.assertEqual(result['counts']['pending_articles'], 0)
        self.assertFalse(any(edge['type'] == 'registered_participation' for edge in result['edges']))
        self.assertEqual([company['id'] for company in result['companies']], ['co-skt'])

    def test_foreign_countries_domestic_cities_and_unknown_locations(self):
        articles = [self.article('kr', 'kr-dc', countries=['KR', 'US'], cities=['서울', '도쿄']),
                    self.article('overseas', 'global-ai', countries=['KR', 'JP'], cities=['서울', '도쿄']),
                    self.article('unknown', 'kr-ai', companies=['co-openai'])]
        result = self.ontology(articles)
        scopes = {scope['id']: scope for scope in result['scopes']}
        kr = scopes['kr-dc']['location_groups']
        self.assertEqual([(place['kind'], place['name']) for place in kr], [('city', '서울')])
        foreign = scopes['global-ai']['location_groups']
        self.assertEqual([(place['kind'], place['country']) for place in foreign], [('country', 'JP')])
        unknown = scopes['kr-ai']['location_groups']
        self.assertEqual(unknown[0]['kind'], 'unknown')
        self.assertEqual(unknown[0]['name'], '도시 미확인')

    def test_multilocation_observation_is_one_article_and_one_pending_group(self):
        article = self.article('multi', 'kr-ai', cities=['서울', '울산'], companies=['co-skt'])
        result = self.ontology([article])
        self.assertEqual(result['counts']['articles'], 1)
        self.assertEqual(result['counts']['pending_groups'], 1)
        self.assertIsNone(result['pending_groups'][0]['location_group_id'])
        self.assertEqual(len(result['pending_groups'][0]['location_group_ids']), 2)
        self.assertEqual(len(next(scope for scope in result['scopes'] if scope['id'] == 'kr-ai')['location_groups']), 2)
        self.assertIn('동일 사업', result['pending_groups'][0]['summary'])

    def test_unknown_project_ids_not_promoted_and_duplicate_articles_deduplicated(self):
        article = self.article('a', project_ids=['unknown-project'], candidate_project_ids=['unknown-project'])
        result = self.ontology([article, deepcopy(article)])
        self.assertEqual(result['counts']['articles'], 1)
        self.assertEqual(result['counts']['verified_projects'], 0)
        self.assertEqual(result['counts']['pending_articles'], 1)
        self.assertFalse(any(project['id'] == 'unknown-project' for project in result['projects']))

    def test_filtered_zero_article_registered_projects_and_source_immutability(self):
        ds = self.ds()
        workspace = {'articles': [self.article('a', 'global-ai', countries=['US'])],
                     'filters': {'scope': 'global-ai', 'country': 'US'}}
        original = deepcopy((ds, workspace))
        result = build_ontology({'datasets': ds}, workspace)
        self.assertEqual([project['id'] for project in result['projects']], ['prj-stargate-us-oracle'])
        self.assertEqual(result['projects'][0]['article_count'], 0)
        self.assertEqual(result['projects'][0]['match_status'], 'no_selected_articles')
        result['projects'][0]['summary'].append('local mutation')
        self.assertEqual((ds, workspace), original)

    def test_new_workspace_company_observation_included_without_repository_write(self):
        article = self.article('new', 'global-ai', companies=['co-new'], countries=['US'],
                               matched_companies=[{'id': 'co-new', 'name': 'New observed name'}])
        result = self.ontology([article])
        self.assertEqual(result['companies'][0]['id'], 'co-new')
        self.assertEqual(result['companies'][0]['classification'], 'observed_name_only')
        self.assertEqual(result['companies'][0]['direct_article_ids'], ['new'])

    def test_graph_limit_keeps_complete_aggregation_and_valid_edges(self):
        ds = self.ds()
        articles = []
        for index in range(600):
            cid = 'observed-' + str(index)
            ds['companies'][cid] = {'id': cid, 'name': cid, 'classification': 'observed_name_only'}
            articles.append(self.article('a' + str(index), 'kr-dc', companies=[cid], cities=['서울']))
        result = self.ontology(articles, ds)
        self.assertEqual(result['counts']['articles'], 600)
        self.assertEqual(result['counts']['observed_companies'], 600)
        self.assertEqual(result['counts']['pending_groups'], 600)
        self.assertEqual(len(result['article_refs']), 600)
        self.assertEqual(sum(group['article_count'] for group in result['pending_groups']), 600)
        self.assertTrue(result['graph']['truncated'])
        self.assertLessEqual(len(result['nodes']), MAX_GRAPH_NODES)
        ids = {node['id'] for node in result['nodes']}
        self.assertTrue(all(edge['source'] in ids and edge['target'] in ids for edge in result['edges']))

    def test_all_five_roles_are_explicit_and_project_scoped(self):
        ds = self.ds()
        ds['relationships']['rel-prj-ulsan-co-skt']['role'] = '시공사 · 설계사 · 운영사'
        ds['relationships']['rel-prj-ulsan-co-skt']['article_ids'] = ['domestic']
        ds['relationships']['second-role'] = {'id': 'second-role', 'project_id': 'prj-stargate-us-oracle',
            'company_id': 'co-skt', 'role': '사업자 · 테넌트', 'directness': 'explicit', 'article_ids': ['foreign']}
        articles = [self.article('domestic', 'kr-ai', project_ids=['prj-ulsan']),
                    self.article('foreign', 'global-ai', project_ids=['prj-stargate-us-oracle'])]
        result = self.ontology(articles, ds)
        company = next(company for company in result['companies'] if company['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['developer', 'tenant', 'contractor', 'designer', 'operator'])
        self.assertEqual(len(company['role_evidence']), 5)
        for evidence in company['role_evidence']:
            self.assertEqual(evidence['basis'], 'explicit_stored_relationship')
            if evidence['role'] in ('developer', 'tenant'):
                self.assertEqual(evidence['project_id'], 'prj-stargate-us-oracle')
                self.assertEqual(evidence['article_ids'], ['foreign'])
            else:
                self.assertEqual(evidence['project_id'], 'prj-ulsan')
                self.assertEqual(evidence['article_ids'], ['domestic'])
        self.assertEqual(company['article_count'], 2)
        groups = {item['id']: item for item in result['company_ontology']['role_groups']}
        self.assertTrue(all('co-skt' in groups[role]['company_ids'] for role in company['roles']))
        self.assertEqual(len(result['role_taxonomy']), 9)

    def test_role_not_inferred_from_company_industry_article_keywords_or_old_evidence(self):
        ds = self.ds()
        ds['companies']['co-skt']['role'] = 'developer · tenant · contractor · operator'
        ds['relationships']['rel-prj-ulsan-co-skt']['role'] = '시공사'
        article = self.article('new-only', 'kr-ai', companies=['co-skt'], project_ids=['prj-ulsan'],
                               title='SK텔레콤 developer tenant design contractor operator data center',
                               business_categories=['설계·시공', '데이터센터'])
        result = self.ontology([article], ds)
        company = next(company for company in result['companies'] if company['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['unknown'])
        self.assertEqual(company['role_evidence'], [])
        self.assertEqual(company['keyword_count'], 2)
        self.assertFalse(any(edge['type'] == 'registered_participation' for edge in result['company_ontology']['edges']))

    def test_unknown_cm_and_nonexplicit_relationship_do_not_become_designer(self):
        ds = self.ds()
        relationship = ds['relationships']['rel-prj-ulsan-co-skt']
        relationship.update(role='CM', article_ids=['cm'])
        ds['relationships']['inferred'] = {'id': 'inferred', 'project_id': 'prj-ulsan', 'company_id': 'co-skt',
            'role': '설계사', 'directness': 'inferred', 'article_ids': ['cm']}
        result = self.ontology([self.article('cm', 'kr-ai', project_ids=['prj-ulsan'])], ds)
        company = next(company for company in result['companies'] if company['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['unknown'])
        self.assertEqual(len(company['role_evidence']), 1)
        self.assertEqual(company['role_evidence'][0]['raw_role'], 'CM')
        self.assertEqual(company['role_evidence'][0]['role'], 'unknown')

    def test_keywords_center_company_without_asserting_contract_or_specialty(self):
        articles = [self.article('a', companies=['co-skt', 'co-aws'], business_categories=['냉각', '냉각', '전력']),
                    self.article('b', companies=['co-skt'], business_categories=['냉각']),
                    self.article('unnamed', business_categories=['자금·조달'])]
        result = self.ontology(articles)
        company = next(company for company in result['companies'] if company['id'] == 'co-skt')
        keywords = {item['label']: item for item in company['keywords']}
        self.assertEqual(keywords['냉각']['article_count'], 2)
        self.assertEqual(set(keywords['냉각']['article_ids']), {'a', 'b'})
        self.assertEqual(keywords['전력']['article_count'], 1)
        self.assertEqual(len(company['summary_lines']), 4)
        self.assertEqual(len(company['summary_evidence']), 4)
        graph = result['company_ontology']
        self.assertEqual(graph['counts']['all_selected_articles'], 3)
        self.assertEqual(graph['counts']['articles'], 2)
        self.assertEqual(graph['counts']['without_company_articles'], 1)
        self.assertEqual(graph['counts']['keywords'], 2)
        keyword_edges = [edge for edge in graph['edges'] if edge['type'] == 'keyword_observation']
        self.assertTrue(keyword_edges)
        self.assertTrue(all(edge['source'].startswith('company:') for edge in keyword_edges))
        self.assertTrue(all(edge['status'] == 'topic_observation' and edge['article_ids'] for edge in keyword_edges))

    def test_role_groups_always_include_five_and_unknown_even_empty(self):
        result = self.ontology([])
        groups = result['company_ontology']['role_groups']
        self.assertEqual([group['id'] for group in groups], ['client', 'developer', 'tenant', 'contractor', 'designer', 'operator', 'equipment_supplier', 'financier', 'unknown'])
        self.assertTrue(all(group['company_count'] == 0 and group['article_ids'] == [] for group in groups))

    def test_company_graph_limit_keeps_all_role_and_keyword_counts(self):
        ds = self.ds()
        articles = []
        for index in range(300):
            cid = 'observation-' + str(index)
            ds['companies'][cid] = {'id': cid, 'name': cid}
            articles.append(self.article('n' + str(index), companies=[cid], business_categories=['전력']))
        result = self.ontology(articles, ds)
        graph = result['company_ontology']
        self.assertEqual(graph['counts']['companies'], 300)
        self.assertEqual(graph['counts']['articles'], 300)
        self.assertEqual(graph['counts']['role_counts']['unknown'], 300)
        self.assertEqual(graph['counts']['keywords'], 1)
        self.assertTrue(graph['graph']['truncated'])
        self.assertLessEqual(len(graph['nodes']), MAX_GRAPH_NODES)
        node_ids = {node['id'] for node in graph['nodes']}
        self.assertTrue(any(node['type'] == 'keyword' for node in graph['nodes']))
        self.assertTrue(all(edge['source'] in node_ids and edge['target'] in node_ids for edge in graph['edges']))

    def test_client_requires_explicit_client_role_owner_does_not_become_client(self):
        ds = self.ds()
        relation = ds['relationships']['rel-prj-ulsan-co-skt']
        relation.update(role='owner', article_ids=['a'])
        result = self.ontology([self.article('a', 'kr-ai', project_ids=['prj-ulsan'])], ds)
        company = next(item for item in result['companies'] if item['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['developer'])
        relation['role'] = '발주처 / commissioning client'
        result = self.ontology([self.article('a', 'kr-ai', project_ids=['prj-ulsan'])], ds)
        company = next(item for item in result['companies'] if item['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['client'])
        self.assertEqual(company['role_evidence'][0]['raw_role'], '발주처 / commissioning client')
        role_node = next(node for node in result['company_ontology']['nodes'] if node['id'] == 'role:client')
        self.assertFalse(role_node['placeholder'])
        role_edges = [edge for edge in result['company_ontology']['edges'] if edge['type'] == 'explicit_project_role']
        self.assertEqual(len(role_edges), 1)
        self.assertEqual(role_edges[0]['article_ids'], ['a'])

    def test_empty_role_slots_have_no_invented_edges(self):
        result = self.ontology([])
        nodes = result['company_ontology']['nodes']
        self.assertEqual(len(nodes), 9)
        self.assertTrue(all(node['type'] == 'role' and node['placeholder'] for node in nodes))
        self.assertEqual(result['company_ontology']['edges'], [])

    def test_counterpart_links_require_explicit_same_project_evidence(self):
        ds = self.ds()
        ds['relationships']['rel-prj-ulsan-co-skt'].update(role='발주처', article_ids=['a'])
        ds['relationships']['rel-prj-ulsan-co-skecoplant'].update(role='시공사', article_ids=['a'])
        article = self.article('a', 'kr-ai', project_ids=['prj-ulsan'], companies=['co-openai'])
        result = self.ontology([article], ds)
        counterpart_edges = [edge for edge in result['company_ontology']['edges'] if edge['type'] == 'shared_project_context']
        self.assertEqual(len(counterpart_edges), 1)
        self.assertFalse(counterpart_edges[0]['direct_contract_confirmed'])
        self.assertEqual(counterpart_edges[0]['project_ids'], ['prj-ulsan'])
        company = next(item for item in result['companies'] if item['id'] == 'co-openai')
        self.assertEqual(company['counterpart_companies'], [])

    def test_equipment_supplier_requires_explicit_selected_project_evidence(self):
        ds = self.ds()
        relation = ds['relationships']['rel-prj-ulsan-co-skt']
        relation.update(role='장비 공급사 / equipment supplier', article_ids=['equipment'])
        article = self.article('equipment', 'kr-ai', project_ids=['prj-ulsan'])
        result = self.ontology([article], ds)
        company = next(item for item in result['companies'] if item['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['equipment_supplier'])
        group = next(item for item in result['company_ontology']['role_groups'] if item['id'] == 'equipment_supplier')
        self.assertEqual(group['role_evidence_article_ids'], ['equipment'])
        relation.update(directness='inferred')
        result = self.ontology([article], ds)
        company = next(item for item in result['companies'] if item['id'] == 'co-skt')
        self.assertEqual(company['roles'], ['unknown'])

    def test_focused_company_beyond_default_display_limit_keeps_one_hop_evidence(self):
        ds = self.ds()
        articles = []
        for index in range(300):
            cid = f'observed-{index:03}'
            ds['companies'][cid] = {'id': cid, 'name': cid}
            articles.append(self.article(f'focused-{index}', 'kr-ai', companies=[cid],
                                         business_categories=[f'keyword-{index}']))
        workspace = {'articles': articles, 'filters': {'scope': 'kr-ai'}}
        normal = build_ontology(ds, workspace)
        focused = build_ontology(ds, workspace, focus_company_id='observed-299')
        graph = focused['company_ontology']
        self.assertNotIn('company:observed-299', {node['id'] for node in normal['company_ontology']['nodes']})
        self.assertIn('company:observed-299', {node['id'] for node in graph['nodes']})
        self.assertEqual(focused['counts'], normal['counts'])
        self.assertEqual(graph['counts'], normal['company_ontology']['counts'])
        self.assertEqual(graph['graph']['total_nodes'], normal['company_ontology']['graph']['total_nodes'])
        self.assertEqual(len([node for node in graph['nodes'] if node['type'] == 'role']), 9)
        self.assertTrue(any(edge['type'] == 'keyword_observation' and edge['source'] == 'company:observed-299'
                            and edge['article_ids'] == ['focused-299'] for edge in graph['edges']))
        self.assertEqual(graph['graph']['focused_neighbor_count'], 2)
        self.assertFalse(graph['graph']['focus_truncated'])
        self.assertLessEqual(len(graph['nodes']), MAX_GRAPH_NODES)

    def test_focus_without_selected_article_has_only_empty_role_slots(self):
        result = build_ontology(self.ds(), {'articles': [self.article('a', 'kr-ai', companies=['co-skt'])],
            'filters': {'scope': 'kr-ai'}}, focus_company_id='co-openai')
        graph = result['company_ontology']
        self.assertEqual(len(graph['nodes']), 9)
        self.assertTrue(all(node['type'] == 'role' and node['placeholder'] and node['article_count'] == 0
                            and not node['article_ids'] and node['unread_count'] == 0 for node in graph['nodes']))
        self.assertEqual(graph['edges'], [])
        self.assertEqual(graph['counts']['companies'], 1)
        self.assertFalse(graph['graph']['focus_node_present'])

    def test_focused_one_hop_truncation_reports_actual_missing_neighbors(self):
        article = self.article('a', 'kr-ai', companies=['co-skt'], business_categories=[f'topic-{index}' for index in range(300)])
        result = build_ontology(self.ds(), {'articles': [article], 'filters': {'scope': 'kr-ai'}}, focus_company_id='co-skt')
        graph = result['company_ontology']
        self.assertEqual(len(graph['nodes']), MAX_GRAPH_NODES)
        self.assertEqual(graph['graph']['focused_neighbor_count'], 301)
        self.assertEqual(graph['graph']['displayed_focused_neighbors'], 240)
        self.assertTrue(graph['graph']['focus_truncated'])
        company = next(item for item in result['companies'] if item['id'] == 'co-skt')
        self.assertEqual(company['keyword_count'], 300)



if __name__ == '__main__':
    unittest.main()
