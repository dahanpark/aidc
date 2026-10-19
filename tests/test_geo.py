"""Geographic placement is derived and never asserts an unverified site."""
import copy
import json
from pathlib import Path
import unittest

from backend.geo import build_map_workspace, canonical_country


def article(aid='a', scope='kr-ai', cities=None, countries=None, project_ids=None):
    return {'id': aid, 'title': 'Data center public metadata ' + aid,
            'url': 'https://example.com/' + aid, 'published_at': '2026-10-17T00:00:00+00:00',
            'scope_classification': {'primary_scope': scope, 'status': 'classified'},
            'geography': {'cities': cities or [], 'countries': countries or []},
            'project_ids': project_ids or [], 'company_ids': [], 'is_new': True}


def inputs(articles, projects=None, companies=None):
    snapshot = {'datasets': {'articles': {a['id']: copy.deepcopy(a) for a in articles},
        'projects': projects or {}, 'companies': companies or {}, 'relationships': {}}}
    return snapshot, {'articles': copy.deepcopy(articles), 'filters': {'scope': 'all'}}


def project(country='KR', location='울산광역시', scope='kr-ai', **extra):
    return {'id': 'p', 'name': 'Registered data center', 'scope': scope, 'country': country,
            'location': location, 'entity_level': 'site', 'company_ids': [], **extra}


class GeographicWorkspaceTests(unittest.TestCase):
    def markers(self, result):
        return [marker for layer in result['scope_layers'] for marker in layer['markers']]

    def test_packaged_primary_boundaries_and_reference_points(self):
        assets = Path(__file__).resolve().parents[1] / 'frontend/assets/maps'
        world = json.loads((assets / 'world.geojson').read_text(encoding='utf-8'))
        korea = json.loads((assets / 'korea.geojson').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(world['features']), 170)
        self.assertEqual({feature['id'] for feature in korea['features']}, {'KR', 'KP'})
        self.assertTrue(all(feature['geometry']['type'] in ('Polygon', 'MultiPolygon') for feature in world['features']))
        self.assertEqual(world['source_commit'], 'ca96624a56bd078437bca8184e78163e5039ad19')

    def test_domestic_observation_is_city_representative_not_project(self):
        snap, workspace = inputs([article(cities=['울산'], countries=['KR'])])
        result = build_map_workspace(snap, workspace, 'approximate')
        marker = self.markers(result)[0]
        self.assertEqual(marker['kind'], 'observation')
        self.assertEqual(marker['precision'], 'city_approximate')
        self.assertFalse(marker['is_confirmed_project'])
        self.assertIsNone(marker['project_id'])
        self.assertTrue(35 < marker['latitude'] < 36)
        self.assertIn('부지 아님', marker['position_label'])
        self.assertEqual(marker['position_provenance']['provider'], 'Natural Earth')
        self.assertEqual(marker['unread_count'], 1)

    def test_country_aliases_use_same_reference_without_hq_inference(self):
        self.assertEqual(canonical_country('UAE'), 'AE')
        snap, workspace = inputs([article(scope='global-ai', countries=['AE'])],
                                 companies={'c': {'id': 'c', 'country': 'US', 'headquarters': 'New York'}})
        result = build_map_workspace(snap, workspace, 'approximate')
        marker = self.markers(result)[0]
        self.assertEqual(marker['country'], 'AE')
        self.assertEqual(marker['precision'], 'country_approximate')
        self.assertTrue(50 < marker['longitude'] < 57)
        snap['datasets']['projects']['p'] = project(country='UAE', location='아부다비', scope='global-ai')
        workspace['articles'][0]['project_ids'] = ['p']
        result = build_map_workspace(snap, workspace, 'approximate')
        self.assertEqual(next(m for m in self.markers(result) if m['kind'] == 'project')['country'], 'AE')

    def test_exact_only_keeps_unlocated_observations_and_same_totals(self):
        snap, workspace = inputs([article(cities=['대전'], countries=['KR'])])
        result = build_map_workspace(snap, workspace, 'exact_only')
        self.assertEqual(self.markers(result), [])
        self.assertEqual(result['counts']['articles'], 1)
        self.assertEqual(result['counts']['unlocated_articles'], 1)
        self.assertEqual(result['scope_layers'][1]['article_ids'], ['a'])
        self.assertTrue(result['unlocated'])
        self.assertTrue(all('latitude' not in entry for entry in result['unlocated']))

    def test_bare_latitude_or_company_address_is_not_verified_site(self):
        a = article(countries=['KR'], project_ids=['p'])
        p = project(location='입지 미확인', latitude=35.5, longitude=129.3,
                    coordinates={'latitude': 35.5, 'longitude': 129.3})
        snap, workspace = inputs([a], {'p': p}, {'c': {'id': 'c', 'headquarters': '서울'}})
        for policy in ('approximate', 'exact_only'):
            result = build_map_workspace(snap, workspace, policy)
            self.assertEqual(self.markers(result), [])
            self.assertEqual(result['counts']['unlocated_articles'], 1)

    def test_verified_site_coordinates_require_safe_source_and_existing_evidence(self):
        a = article(project_ids=['p'])
        coordinate = {'latitude': 35.55, 'longitude': 129.31, 'verification_status': 'verified',
                      'precision': 'site', 'source_url': a['url'], 'article_ids': ['a']}
        snap, workspace = inputs([a], {'p': project(coordinates=coordinate)})
        result = build_map_workspace(snap, workspace, 'exact_only')
        marker = self.markers(result)[0]
        self.assertEqual(marker['precision'], 'exact')
        self.assertEqual(marker['latitude'], 35.55)
        self.assertEqual(result['counts']['mapped_articles'], 1)
        self.assertEqual(result['counts']['unlocated_articles'], 0)
        for invalid in ({'article_ids': ['missing']}, {'source_url': 'https://example.com/?api_key=hidden'}, {'latitude': float('nan')}):
            broken = copy.deepcopy(snap)
            broken['datasets']['projects']['p']['coordinates'].update(invalid)
            self.assertEqual(self.markers(build_map_workspace(broken, workspace, 'exact_only')), [])

    def test_program_coordinate_does_not_become_physical_site(self):
        a = article(scope='global-ai', countries=['US'], project_ids=['p'])
        coordinate = {'latitude': 32, 'longitude': -99, 'verification_status': 'verified',
                      'precision': 'site', 'source_url': a['url'], 'article_ids': ['a']}
        snap, workspace = inputs([a], {'p': project(country='US', location='미국 · 부지 미확정',
            scope='global-ai', entity_level='program', coordinates=coordinate)})
        self.assertEqual(self.markers(build_map_workspace(snap, workspace, 'exact_only')), [])
        approx = next(m for m in self.markers(build_map_workspace(snap, workspace, 'approximate')) if m['kind'] == 'project')
        self.assertEqual(approx['precision'], 'country_approximate')

    def test_company_headquarters_and_publisher_region_never_supply_location(self):
        a = article(countries=[], cities=[])
        a.update(company_ids=['c'], publisher='Korean newspaper', source_region='KR')
        snap, workspace = inputs([a], companies={'c': {'id': 'c', 'name': 'Company', 'country': 'KR', 'headquarters': '서울'}})
        result = build_map_workspace(snap, workspace, 'approximate')
        self.assertEqual(self.markers(result), [])
        self.assertEqual(result['counts']['unlocated_articles'], 1)

    def test_same_filtered_article_set_and_multi_location_counts(self):
        a = article(cities=['서울', '울산'], countries=['KR'])
        b = article('b', 'global-ai', countries=['US'])
        snap, workspace = inputs([a, b])
        workspace['articles'] = [a]
        result = build_map_workspace(snap, workspace, 'approximate')
        self.assertEqual(result['counts']['articles'], 1)
        self.assertEqual(result['counts']['mapped_articles'], 1)
        self.assertEqual(len(self.markers(result)), 2)
        self.assertEqual({aid for marker in self.markers(result) for aid in marker['article_ids']}, {'a'})

    def test_unresolved_scope_never_pinned_into_registered_project_scope(self):
        a = article(scope=None, countries=['KR','US'], project_ids=['p'])
        snap, workspace = inputs([a], {'p': project(country='US', location='미국', scope='global-ai')})
        result = build_map_workspace(snap, workspace, 'approximate')
        self.assertEqual(self.markers(result), [])
        self.assertEqual(result['unresolved_article_ids'], ['a'])
        self.assertEqual(result['counts']['articles'], 1)
        self.assertEqual(result['counts']['unlocated_articles'], 1)

    def test_unknown_reference_city_remains_unlocated(self):
        snap, workspace = inputs([article(cities=['세종'], countries=['KR'])])
        self.assertEqual(self.markers(build_map_workspace(snap, workspace, 'approximate')), [])

    def test_policy_is_explicitly_validated(self):
        snap, workspace = inputs([])
        with self.assertRaises(ValueError):
            build_map_workspace(snap, workspace, 'guess')


if __name__ == '__main__':
    unittest.main()
