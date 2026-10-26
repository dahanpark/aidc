"""Selected-scope display grouping is pure and never upgrades evidence."""
import copy
import unittest
from backend import project_identity
from backend.project_identity_view import apply


class IdentityViewTests(unittest.TestCase):
    def setUp(self):
        self.ds = {'articles': {aid: {'id': aid, 'mode': 'live_metadata', 'title': title, 'project_ids': pids}
                    for aid, title, pids in [('a', '서울 알파 데이터센터 추진', ['p1']),
                                             ('b', '서울 알파 IDC 추진', ['p2']),
                                             ('c', '서울 알파 AIDC 추진', []),
                                             ('d', '서울 알파 AIDC 후속 보도', []),
                                             ('z', '서울 알파 데이터센터 과거 기사', ['p1'])]},
                   'projects': {'p1': {'id': 'p1', 'name': '알파 데이터센터', 'city': '서울', 'country': 'KR',
                                        'article_ids': ['a', 'z'], 'capacity': 100, 'capacities': [{'value': 100}],
                                        'parent_id': None, 'phase': '1', 'company_ids': ['co']},
                                'p2': {'id': 'p2', 'name': '알파 IDC', 'city': '서울', 'country': 'KR',
                                        'article_ids': ['b'], 'capacity': 900, 'capacities': [{'value': 900}],
                                        'parent_id': None, 'phase': '1', 'company_ids': ['co2']}},
                   'project_mentions': {}}
        self.mentions = []
        for aid, mid in [('c', 'm1'), ('d', 'm2')]:
            link = {'id': 'obs-' + mid, 'company_id': 'co', 'role': 'operator', 'article_ids': [aid],
                    'basis': 'metadata_activity_type_proposal', 'is_confirmed_participation': False,
                    'direct_contract_confirmed': False, 'status': 'cooccurrence_observation'}
            mention = {'id': mid, 'name': '알파 AIDC', 'article_id': aid, 'article_ids': [aid],
                       'cities': ['서울'], 'countries': ['KR'], 'phase': '1', 'scope': 'kr-ai',
                       'company_links': [link], 'company_ids': ['co'], 'stage_signals': [], 'capacity_signals': []}
            self.mentions.append(mention)
            self.ds['project_mentions'][aid] = {'id': aid, 'article_id': aid, 'mentions': [mention]}
        nodes = [{'id': 'project:' + pid, 'entity_id': pid, 'type': 'project', 'name': self.ds['projects'][pid]['name'],
                  'article_ids': self.ds['projects'][pid]['article_ids'], 'attention_ids': ['alert-' + pid]} for pid in ['p1', 'p2']]
        nodes.append({'id': 'company:co', 'entity_id': 'co', 'type': 'company', 'article_ids': ['a', 'b']})
        edges = [{'id': 'e-' + pid, 'source': 'project:' + pid, 'target': 'company:co', 'type': 'registered_participation',
                  'role': 'operator', 'basis': 'explicit_stored_relationship', 'status': 'registered_evidence',
                  'article_ids': [aid], 'direct_contract_confirmed': False} for pid, aid in [('p1', 'a'), ('p2', 'b')]]
        edges.append({'id': 'self-after-remap', 'source': 'project:p1', 'target': 'project:p2', 'type': 'context', 'article_ids': ['a']})
        candidates = [{'id': 'name-group', 'name': '알파 AIDC', 'mention_ids': ['m1', 'm2'], 'article_ids': ['c', 'd'],
                       'company_links': [{**m['company_links'][0], 'project_id': 'name-group', 'project_is_candidate': True} for m in self.mentions]}]
        self.data = {'projects': list(self.ds['projects'].values()), 'articles': list(self.ds['articles'].values()),
                     'news': {'articles': [self.ds['articles'][aid] for aid in ['a', 'b', 'c', 'd']]},
                     'project_discovery': {'mentions': self.mentions, 'project_candidates': candidates,
                                           'company_links': copy.deepcopy(candidates[0]['company_links'])},
                     'ontology': {'projects': copy.deepcopy(list(self.ds['projects'].values())), 'nodes': nodes, 'edges': edges,
                                  'company_ontology': {'nodes': copy.deepcopy(nodes), 'edges': copy.deepcopy(edges)},
                                  'companies': [{'id': 'co', 'project_ids': ['p1', 'p2'], 'role_evidence': [
                                      {'project_id': 'p2', 'role': 'operator', 'basis': 'explicit_stored_relationship', 'article_ids': ['b']}]}],
                                  'counts': {'registered_projects': 2}, 'attention': {'items': [{'id': 'alert-p2', 'project_ids': ['p2']}]},
                                  'scopes': [{'id': 'kr-ai', 'location_groups': [{'id': 'seoul', 'projects': copy.deepcopy(list(self.ds['projects'].values()))}]}]},
                     'maps': {'variants': {'approximate': {'scope_layers': [{'markers': [
                         {'id': 'marker-p2', 'project_id': 'p2', 'latitude': 37.5, 'longitude': 127.0, 'article_ids': ['b']}]}]}}},
                     'attention': {'items': [{'id': 'alert-p2', 'project_ids': ['p2']}]},
                     'read_states': [{'id': 'alert-p2', 'read': False}],
                     'company_links': [{'id': 'top-link', 'project_id': 'p2', 'role': 'contractor', 'directness': 'explicit'}]}

    def workspace(self, refs=None, canonical='project:p1'):
        refs = refs or ['project:p1', 'project:p2', 'mention:m1']
        payload = {'member_refs': refs, 'canonical_ref': canonical, 'evidence_article_ids': ['a', 'b', 'c', 'd', 'z']}
        view = project_identity.preview(self.ds, payload)
        self.assertTrue(view['applicable'], view['conflicts'])
        project_identity.apply(self.ds, {**payload, 'input_hash': view['input_hash'], 'consent_user_confirmed': True})
        return project_identity.workspace(self.ds, ['a', 'b', 'c', 'd'])

    def test_projection_does_not_modify_original_and_keeps_only_canonical_facts(self):
        ws = self.workspace()
        before = copy.deepcopy(self.data)
        projected = apply(self.data, ws)
        self.assertEqual(self.data, before)
        self.assertEqual(len(projected['projects']), 1)
        canonical = projected['projects'][0]
        self.assertEqual(canonical['id'], 'p1')
        self.assertEqual(canonical['capacity'], 100)
        self.assertEqual(canonical['capacities'], [{'value': 100}])
        self.assertEqual((canonical['parent_id'], canonical['phase']), (None, '1'))
        self.assertEqual(canonical['source_project_ids'], ['p1', 'p2'])
        self.assertIn('알파 IDC', canonical['aliases'])

    def test_identity_articles_unique_and_scope_exact(self):
        projected = apply(self.data, self.workspace())
        canonical = projected['projects'][0]
        self.assertEqual(canonical['identity_article_ids'], ['a', 'b', 'c'])
        self.assertEqual(canonical['article_ids'], ['a', 'b', 'c'])
        self.assertNotIn('z', str(projected['identity_display']['contexts']))
        article = next(a for a in projected['news']['articles'] if a['id'] == 'b')
        self.assertEqual(article['project_ids'], ['p2'])
        self.assertEqual(article['identity_project_ids'], ['p1'])
        self.assertEqual(article['identity_contexts'][0]['id'], 'p1')

    def test_partial_name_group_retains_unapproved_mention_and_own_articles(self):
        projected = apply(self.data, self.workspace())
        remaining = projected['project_discovery']['project_candidates']
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['mention_ids'], ['m2'])
        self.assertEqual(remaining[0]['article_ids'], ['d'])
        self.assertEqual(len(projected['project_discovery']['mentions']), 2)
        links = projected['project_discovery']['company_links']
        approved = next(link for link in links if link['id'] == 'obs-m1')
        unapproved = next(link for link in links if link['id'] == 'obs-m2')
        self.assertEqual((approved['project_id'], unapproved['project_id']), ('p1', 'name-group'))
        self.assertFalse(approved['is_confirmed_participation'])
        self.assertFalse(approved['direct_contract_confirmed'])

    def test_mention_only_group_is_candidate_and_not_registered(self):
        ws = self.workspace(['mention:m1', 'mention:m2'], 'mention:m1')
        self.data['ontology']['nodes'].extend([
            {'id': 'mention:m1', 'entity_id': 'm1', 'type': 'pending', 'article_ids': ['c']},
            {'id': 'mention:m2', 'entity_id': 'm2', 'type': 'pending', 'article_ids': ['d']}])
        projected = apply(self.data, ws)
        self.assertEqual(projected['projects'], self.data['projects'])
        candidate = projected['project_discovery']['project_candidates'][0]
        self.assertEqual(candidate['id'], 'identity:' + ws['active_groups'][0]['id'])
        self.assertTrue(candidate['is_candidate'])
        self.assertFalse(candidate['is_confirmed_project'])
        self.assertTrue(candidate['user_confirmed_identity'])
        self.assertEqual(candidate['article_ids'], ['c', 'd'])
        self.assertEqual({m['id'] for m in candidate['raw_mentions']}, {'m1', 'm2'})
        display_nodes = [node for node in projected['ontology']['nodes'] if node['id'] == 'discovery:' + candidate['id']]
        self.assertEqual(len(display_nodes), 1)
        self.assertEqual(display_nodes[0]['article_ids'], ['c', 'd'])

    def test_mention_canonical_with_registered_member_uses_registered_display_id(self):
        ws = self.workspace(['project:p1', 'mention:m1'], 'mention:m1')
        projected = apply(self.data, ws)
        project = next(p for p in projected['projects'] if p['id'] == 'p1')
        self.assertEqual(project['name'], '알파 AIDC')
        self.assertEqual(project['capacity'], 100)

    def test_graph_endpoints_deduplicate_and_no_self_edges(self):
        projected = apply(self.data, self.workspace())
        for graph in [projected['ontology'], projected['ontology']['company_ontology']]:
            self.assertEqual({n['id'] for n in graph['nodes']}, {'project:p1', 'company:co'})
            self.assertEqual(len(graph['edges']), 1)
            edge = graph['edges'][0]
            self.assertEqual((edge['source'], edge['target']), ('project:p1', 'company:co'))
            self.assertEqual(set(edge['source_edge_ids']), {'e-p1', 'e-p2'})
            self.assertEqual(set(edge['article_ids']), {'a', 'b'})
            self.assertFalse(edge['direct_contract_confirmed'])
        nested = projected['ontology']['scopes'][0]['location_groups'][0]['projects']
        self.assertEqual(len(nested), 1)
        self.assertEqual(projected['ontology']['companies'][0]['project_ids'], ['p1'])

    def test_distinct_roles_and_contract_evidence_are_not_collapsed_or_upgraded(self):
        self.data['ontology']['edges'][1]['role'] = 'contractor'
        projected = apply(self.data, self.workspace())
        edges = projected['ontology']['edges']
        self.assertEqual(len(edges), 2)
        self.assertEqual({edge['role'] for edge in edges}, {'operator', 'contractor'})
        self.assertTrue(all(edge['basis'] == 'explicit_stored_relationship' for edge in edges))

    def test_map_coordinates_attention_items_read_state_and_original_ids_preserved(self):
        projected = apply(self.data, self.workspace())
        marker = projected['maps']['variants']['approximate']['scope_layers'][0]['markers'][0]
        self.assertEqual((marker['id'], marker['latitude'], marker['longitude']), ('marker-p2', 37.5, 127.0))
        self.assertEqual((marker['project_id'], marker['source_project_id']), ('p1', 'p2'))
        self.assertEqual(projected['attention'], self.data['attention'])
        self.assertEqual(projected['ontology']['attention'], self.data['ontology']['attention'])
        self.assertEqual(projected['read_states'], self.data['read_states'])
        self.assertEqual(projected['company_links'][0]['source_project_id'], 'p2')

    def test_unapproved_stale_and_revoked_are_noop_and_undo_restores(self):
        ws = self.workspace()
        group = ws['active_groups'][0]
        for changed in [{'state': 'revoked'}, {'state': 'proposed'}, {'stale': True}, {'active': False}]:
            self.assertIs(apply(self.data, {'active_groups': [{**group, **changed}]}), self.data)
        project_identity.undo(self.ds, {'group_id': group['id'], 'consent_user_confirmed': True})
        undone = project_identity.workspace(self.ds, ['a', 'b', 'c', 'd'])
        self.assertIs(apply(self.data, undone), self.data)

    def test_local_manual_private_selected_source_associations_are_preserved_separately(self):
        ws = self.workspace()
        # These local records are never identity evidence and are never sent
        # to an AI provider by this pure display projection.
        self.data['news']['articles'].extend([
            {'id': 'manual', 'mode': 'manual', 'project_ids': ['p2']},
            {'id': 'private', 'mode': 'manual', 'visibility': 'private', 'project_ids': []},
            {'id': 'unrelated-private', 'mode': 'manual', 'visibility': 'private', 'project_ids': []}])
        self.data['projects'][1]['article_ids'].extend(['private', 'not-selected'])
        before = copy.deepcopy(self.data)
        projected = apply(self.data, ws)
        canonical = projected['projects'][0]
        self.assertEqual(canonical['article_ids'], ['a', 'b', 'c', 'manual', 'private'])
        self.assertEqual(canonical['identity_article_ids'], ['a', 'b', 'c'])
        self.assertEqual(canonical['source_article_ids'], ['a', 'b', 'c'])
        self.assertEqual(canonical['source_association_article_ids'], ['a', 'b', 'manual', 'private'])
        self.assertNotIn('not-selected', canonical['article_ids'])
        self.assertNotIn('z', canonical['article_ids'])
        self.assertNotIn('unrelated-private', canonical['article_ids'])
        manual = next(a for a in projected['news']['articles'] if a['id'] == 'manual')
        self.assertEqual(manual['project_ids'], ['p2'])
        self.assertEqual(manual['identity_project_ids'], ['p1'])
        self.assertEqual(self.data, before)
        self.assertIs(apply(self.data, {'active_groups': []}), self.data)

    def test_original_alias_details_remain_accessible_without_numeric_merging(self):
        projected = apply(self.data, self.workspace())
        originals = {p['id']: p for p in projected['identity_display']['source_projects']}
        self.assertEqual(originals['p1'], self.ds['projects']['p1'])
        self.assertEqual(originals['p2'], self.ds['projects']['p2'])
        self.assertEqual(originals['p2']['capacity'], 900)
        self.assertEqual(originals['p2']['capacities'], [{'value': 900}])
        self.assertEqual(projected['projects'][0]['capacity'], 100)
        originals['p2']['capacities'][0]['value'] = -1
        self.assertEqual(self.ds['projects']['p2']['capacities'][0]['value'], 900)


if __name__ == '__main__': unittest.main()
