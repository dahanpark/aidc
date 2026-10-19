"""Offline geographic projections of evidence-linked businesses and observations.

Representative city/country points are explicitly approximate. They never become
project coordinates or facts, and publisher/company headquarters are never used.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from .news import CITIES
from .security import assert_safe_url

SCOPES = {'kr-dc': '국내 DC', 'kr-ai': '국내 AIDC', 'global-ai': '해외 AIDC'}
ASSETS = Path(__file__).resolve().parents[1] / 'frontend' / 'assets' / 'maps'
ALIASES = {'UAE': 'AE', 'ARE': 'AE', 'USA': 'US', 'KOR': 'KR', '한국': 'KR',
           '대한민국': 'KR', 'South Korea': 'KR', 'United States': 'US'}


def canonical_country(value):
    return ALIASES.get(value, str(value or '').upper())


@lru_cache(maxsize=1)
def _positions():
    return json.loads((ASSETS / 'positions.json').read_text(encoding='utf-8'))


def _finite(value, limit):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and abs(value) <= limit


def _verified_coordinates(project, articles):
    """Accept sourced, explicitly verified site coordinates, not bare lat/lon.

    Contract: coordinates={latitude,longitude,verification_status:'verified',
    precision:'site',source_url,article_ids:[existing source article IDs]}.
    Program coordinates cannot identify an individual physical data-center site.
    """
    coord = project.get('coordinates', {})
    if not isinstance(coord, dict) or project.get('entity_level') == 'program':
        return None
    if coord.get('verification_status') != 'verified' or coord.get('precision') not in ('site', 'exact'):
        return None
    if not _finite(coord.get('latitude'), 90) or not _finite(coord.get('longitude'), 180):
        return None
    evidence = coord.get('article_ids', [])
    if not isinstance(evidence, list) or not evidence or not all(aid in articles for aid in evidence):
        return None
    try:
        assert_safe_url(coord.get('source_url', ''))
    except (ValueError, TypeError):
        return None
    return {'latitude': coord['latitude'], 'longitude': coord['longitude'], 'precision': 'exact',
            'position_label': '근거로 확인한 사업 부지 좌표',
            'position_provenance': {'basis': 'explicit_verified_site_coordinates', 'source_url': coord['source_url'],
                                    'article_ids': list(evidence)}}


def _representative(kind, value, country=None):
    positions = _positions()
    record = positions['cities'].get(value) if kind == 'city' else positions['countries'].get(canonical_country(value))
    if not record or (kind == 'city' and country and record['country'] != canonical_country(country)):
        return None
    return {'latitude': record['latitude'], 'longitude': record['longitude'],
            'precision': 'city_approximate' if kind == 'city' else 'country_approximate',
            'position_label': '도시 대표점 · 개략 위치, 사업 부지 아님' if kind == 'city' else '국가 대표점 · 개략 위치, 사업 부지 아님',
            'position_provenance': {'provider': positions['provider'], 'commit': positions['commit'],
                'source_dataset': record['source_dataset'], 'source_feature': record['source_feature'],
                'basis': record['basis']}}


def _project_position(project, policy, articles):
    exact = _verified_coordinates(project, articles)
    if exact or policy == 'exact_only':
        return exact
    country = canonical_country(project.get('country'))
    location = project.get('location', '')
    # Only explicit location text is matched. A company name/headquarters never
    # supplies a location. Multiple city names do not identify a single parcel.
    cities = [name for name, (code, pattern) in CITIES.items()
              if canonical_country(code) == country and re.search(pattern, location, re.I)]
    if len(cities) == 1:
        point = _representative('city', cities[0], country)
        if point:
            return point
    if country != 'KR':
        return _representative('country', country)
    return None


def build_map_workspace(snapshot, workspace, position_policy='approximate'):
    """Derive three scope layers from exactly the selected article workspace.

    Each layer's article_ids form the same scope partition as the ontology.
    Marker counts overlap across businesses and observation locations. Always use
    unique article IDs for totals; do not sum marker article counts.
    """
    if position_policy not in ('approximate', 'exact_only'):
        raise ValueError('지원하지 않는 지도 위치 표시 정책입니다.')
    from .ontology import build_ontology
    ds = snapshot.get('datasets', snapshot)
    ontology = workspace.get('ontology') or build_ontology(snapshot, workspace)
    articles = {article['id']: article for article in workspace.get('articles', [])}
    source_articles = ds.get('articles', {})
    projects = ds.get('projects', {})
    layers, unlocated = [], []
    located_ids = set()

    def record(entry, scope, kind):
        allowed = set(scopes.get(scope, {}).get('article_ids', []))
        ids = [aid for aid in entry.get('article_ids', []) if aid in articles and aid in allowed]
        return {'id': ('map-project:' if kind == 'project' else 'map-observation:') + entry['id'],
                'kind': kind, 'scope': scope, 'name': entry.get('name') or entry['id'],
                'article_ids': ids, 'article_count': len(ids),
                'unread_count': sum(bool(articles[aid].get('is_new')) for aid in ids),
                'project_id': entry['id'] if kind == 'project' else None,
                'location_group_id': entry['id'] if kind == 'observation' else None,
                'company_ids': list(entry.get('company_ids', [])),
                'match_status': entry.get('match_status') if kind == 'project' else 'article_location_observation',
                'is_confirmed_project': kind == 'project', 'country': canonical_country(entry.get('country')) or None}

    scopes = {item['id']: item for item in ontology.get('scopes', [])}
    for scope_id, label in SCOPES.items():
        scope = scopes.get(scope_id, {})
        layer = {'id': scope_id, 'label': label, 'article_ids': list(scope.get('article_ids', [])),
                 'article_count': len(scope.get('article_ids', [])), 'markers': [], 'unlocated': []}
        for project in ontology.get('projects', []):
            if project.get('scope') != scope_id or not project.get('article_ids'):
                continue
            item = record(project, scope_id, 'project')
            if not item['article_ids']:
                continue
            position = _project_position(projects.get(project['id'], project), position_policy, source_articles)
            item['entity_level'] = project.get('entity_level')
            if position:
                item.update(position)
                located_ids.update(item['article_ids'])
                layer['markers'].append(item)
            else:
                item['unlocated_reason'] = 'verified_site_coordinates_required' if position_policy == 'exact_only' else 'explicit_location_or_reference_point_missing'
                layer['unlocated'].append(item)
        for place in scope.get('location_groups', []):
            item = record(place, scope_id, 'observation')
            item['city'] = place.get('value') if place.get('kind') == 'city' else None
            item['country'] = canonical_country(place.get('country')) or None
            position = None
            if position_policy == 'approximate' and place.get('kind') in ('city', 'country'):
                position = _representative(place['kind'], place['value'], place.get('country'))
            if position:
                item.update(position)
                located_ids.update(item['article_ids'])
                layer['markers'].append(item)
            else:
                item['unlocated_reason'] = 'article_observation_has_no_verified_site_coordinates' if position_policy == 'exact_only' else 'explicit_location_or_reference_point_missing'
                layer['unlocated'].append(item)
        layer['marker_count'] = len(layer['markers'])
        layer['mapped_article_ids'] = sorted({aid for marker in layer['markers'] for aid in marker['article_ids']})
        layer['unlocated_article_ids'] = sorted(set(layer['article_ids']) - set(layer['mapped_article_ids']))
        unlocated.extend(deepcopy(layer['unlocated']))
        layers.append(layer)
    # Unclassified articles remain visible beside the map; never pin at (0,0).
    unresolved = scopes.get('unresolved', {})
    unresolved_ids = [aid for aid in unresolved.get('article_ids', []) if aid in articles]
    for aid in unresolved_ids:
        unlocated.append({'id': 'map-unresolved:' + aid, 'kind': 'article', 'scope': 'unresolved',
            'name': articles[aid].get('title') or aid, 'article_ids': [aid], 'article_count': 1,
            'unlocated_reason': 'scope_or_location_unresolved'})
    return {'version': 1, 'position_policy': position_policy, 'scope_layers': layers,
            'unlocated': unlocated, 'unresolved_article_ids': unresolved_ids,
            'counts': {'articles': len(articles), 'mapped_articles': len(located_ids),
                'unlocated_articles': len(set(articles) - located_ids),
                'registered_project_markers': sum(m['kind'] == 'project' for layer in layers for m in layer['markers']),
                'observation_markers': sum(m['kind'] == 'observation' for layer in layers for m in layer['markers'])},
            'asset_urls': {'world': '/assets/maps/world.geojson', 'korea': '/assets/maps/korea.geojson'},
            'attribution': {'label': 'Made with Natural Earth · public domain',
                            'url': 'https://www.naturalearthdata.com/about/terms-of-use/',
                            'commit': _positions()['commit']},
            'limitations': ['도시·국가 대표점은 사업 부지 좌표가 아닙니다. 정확 좌표와 점선 개략 위치를 구분합니다.',
                '지도에 표시할 위치가 없거나 정책상 제외된 자료도 미배치 목록과 전체 기사 수에 보존합니다.',
                '한 기사가 여러 사업·지역에 연결될 수 있으므로 마커별 기사 수를 더하지 않습니다.',
                '일반화한 국가 경계로 행정·필지 측량과 영토 판정을 대체하지 않습니다.']}
