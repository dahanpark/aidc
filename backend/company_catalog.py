"""Lightweight, evidence-bound worldwide company choices for the active search.

This derives a catalogue, not another ontology, and never writes to the JSON
repository. The caller supplies articles from the news workspace's single pass.
"""
from __future__ import annotations

from copy import deepcopy

from .ontology import ROLE_TAXONOMY, SCOPES, _roles, _scope
from .company_profiles import profile_fields, PROFILE_LABELS


def build_company_catalog(snapshot, workspace, source):
    ds = snapshot.get('datasets', snapshot)
    companies = source.get('companies', ds.get('companies', {}))
    projects = ds.get('projects', {})
    articles = {item['id']: item for item in source.get('articles', [])}
    ordered_ids = sorted(articles, key=lambda aid: (str(articles[aid].get('published_at', '')), aid), reverse=True)
    order = {aid: index for index, aid in enumerate(ordered_ids)}
    selected_ids = {item['id'] for item in workspace.get('articles', [])}
    selected_scope = workspace.get('filters', {}).get('scope', 'all')
    entries = {}

    def entry(cid):
        company = companies[cid]
        return entries.setdefault(cid, {'id': cid, 'name': company.get('name', cid),
            **profile_fields(company, ds.get('company_classifications', {}).get(cid)),
            'classification': company.get('classification', 'registered_company'),
            'article_ids': set(), 'role_evidence': []})

    for aid, article in articles.items():
        company_ids = set(article.get('company_ids', []))
        for pid in article.get('project_ids', []):
            company_ids.update(projects.get(pid, {}).get('company_ids', []))
        for cid in company_ids & companies.keys():
            entry(cid)['article_ids'].add(aid)
    for relationship in ds.get('relationships', {}).values():
        pid, cid = relationship.get('project_id'), relationship.get('company_id')
        if relationship.get('directness') != 'explicit' or cid not in companies or pid not in projects:
            continue
        # Candidate project name matches, an old article or a global company
        # descriptor cannot confer a role in the selected search evidence.
        aids = sorted({aid for aid in relationship.get('article_ids', [])
                       if aid in articles and pid in articles[aid].get('project_ids', [])}, key=order.get)
        if not aids:
            continue
        target = entry(cid)
        target['article_ids'].update(aids)
        raw_role = str(relationship.get('role') or '').strip()
        for role in _roles(raw_role):
            target['role_evidence'].append({'role': role, 'label': ROLE_TAXONOMY[role],
                'project_id': pid, 'raw_role': raw_role, 'article_ids': aids,
                'relationship_id': relationship['id'], 'basis': 'explicit_stored_relationship'})

    result = []
    for company in entries.values():
        aids = sorted(company['article_ids'], key=order.get)
        scope_counts = {scope: sum(_scope(articles[aid]) == scope for aid in aids) for scope in SCOPES}
        evidence = company['role_evidence']
        roles = [role for role in ROLE_TAXONOMY if any(item['role'] == role for item in evidence)] or ['unknown']
        company.update(article_ids=aids, article_count=len(aids), roles=roles,
            scopes=[scope for scope, count in scope_counts.items() if count], scope_article_counts=scope_counts,
            selected_article_count=len(set(aids) & selected_ids),
            in_selected_scope=selected_scope == 'all' or bool(scope_counts.get(selected_scope)),
            latest_published_at=articles[aids[0]].get('published_at') if aids else None)
        result.append(company)
    result.sort(key=lambda item: (-item['article_count'], item['name'], item['id']))
    filters = deepcopy(workspace.get('filters', {}))
    for key in ('scope', 'company_id', 'country', 'city'):
        filters[key] = 'all' if key == 'scope' else ''
    return {'companies': result, 'role_taxonomy': [{'id': role, 'label': label} for role, label in ROLE_TAXONOMY.items()],
        'profile_taxonomy': [{'id': category, 'label': label} for category, label in PROFILE_LABELS.items()],
        'filters': filters, 'ignored_filters': ['scope', 'company_id', 'country', 'city'],
        'counts': {'companies': len(result), 'articles': len(articles),
                   'role_counts': {role: sum(role in item['roles'] for item in result) for role in ROLE_TAXONOMY}},
        'counting_note': '같은 기간·검색어·출처·사업 조건의 국내외 관련 기사에서 관측한 기업 전체입니다. 범위·기업·도시·국가 선택은 목록을 제한하지 않습니다. 기업의 본사 소재지나 계약 관계를 뜻하지 않습니다.'}
