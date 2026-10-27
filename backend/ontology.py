"""Evidence-linked article ontology, derived without asserting new project facts.

Article counts form a partition. Project/company links are many-to-many and their
counts must never be added to obtain an article or physical-site total.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from .news import CITIES, COUNTRIES
from .attention import build_attention, attention_annotation
from .company_profiles import profile_fields, PROFILE_LABELS


SCOPES = {'kr-dc': '국내 DC', 'kr-ai': '국내 AIDC', 'global-ai': '해외 AIDC',
          'unresolved': '범위 분류 대기'}
MAX_GRAPH_NODES = 250
ROLE_TAXONOMY = {'client': '발주처', 'developer': '사업자', 'tenant': '테넌트', 'contractor': '시공사',
                 'designer': '설계사', 'operator': '운영사', 'equipment_supplier': '장비사',
                 'financier': 'PF사·금융주선사',
                 'unknown': '역할 미확인·기타'}
# Match the role recorded on an explicit relationship, never the article's
# business keywords, a company name, or a company's industry/global role.
ROLE_PATTERNS = {
    'client': r'발주처|발주자|발주사|\bclient\b|\bcommissioning\s+(?:party|client|authority|organization|organisation)\b',
    'developer': r'(?<!운영)(?<!운영\s)사업자|사업주|시행사|개발사|사업개발|\bdeveloper\b|\bowner\b',
    'tenant': r'테넌트|임차인|임차사|입주사|\btenant\b|\blessee\b',
    'contractor': r'시공|건설사|\bcontractor\b|\bEPC\b|\bconstruction contractor\b',
    'designer': r'설계|\barchitect(?:s|ural)?\b|\bdesigner\b|\bdesign engineer\b',
    'operator': r'운영사|운영자|운영사업자|운영\s*사업자|운영\s*담당|\boperator\b',
    'equipment_supplier': r'장비사|장비\s*(?:공급|제조|납품)(?:사|업체|자)?|기자재\s*(?:공급|납품)(?:사|업체|자)?|\bequipment[\s_-]+(?:supplier|vendor|manufacturer)\b',
    'financier': r'PF사|PF\s*(?:주선|주관|대출)|금융\s*(?:주선|주관)|프로젝트\s*파이낸싱|\bfinancier\b|\bfinancial\s+(?:arranger|advisor)\b|\bproject\s+financ(?:e|ing)\b',
}


def _roles(raw_role):
    return [role for role, pattern in ROLE_PATTERNS.items()
            if re.search(pattern, raw_role, re.I)] or ['unknown']


def _id(prefix, *parts):
    return prefix + '-' + hashlib.sha256(repr(parts).encode('utf-8')).hexdigest()[:20]


def _scope(article):
    classification = article.get('scope_classification', {})
    # Once a classification exists its unresolved result overrides legacy fields.
    value = classification.get('primary_scope') if classification else article.get('scope')
    return value if value in SCOPES and value != 'unresolved' else 'unresolved'


def _locations(article, scope):
    geography = article.get('geography', {})
    if scope in ('kr-dc', 'kr-ai'):
        cities = sorted({city for city in geography.get('cities', [])
                         if CITIES.get(city, (None,))[0] == 'KR'})
        return [('city', city, 'KR', city) for city in cities] or [('unknown', 'unknown', 'KR', '도시 미확인')]
    if scope == 'global-ai':
        countries = sorted({code for code in geography.get('countries', []) if code != 'KR'})
        return [('country', code, code, COUNTRIES.get(code, (code,))[0]) for code in countries] or [('unknown', 'unknown', None, '국가 미확인')]
    return [('unknown', 'unknown', None, '지역·범위 미확인')]


def _project_visible(project, filters):
    if filters.get('project_id') and project['id'] != filters['project_id']:
        return False
    if filters.get('company_id') and filters['company_id'] not in project.get('company_ids', []):
        return False
    if filters.get('scope', 'all') not in ('all', project.get('scope')):
        return False
    country = {'UAE': 'AE', 'USA': 'US'}.get(project.get('country'), project.get('country'))
    if filters.get('country') and country != filters['country']:
        return False
    if filters.get('city'):
        city = filters['city']
        if city not in CITIES or not re.search(CITIES[city][1], project.get('location', ''), re.I):
            return False
    return True


def _company_graph(companies, projects, pending_groups, article_refs, ordered, focus_company_id=None, focus_company_ids=None):
    """Company -> topic/project/article-bucket graph with evidence on every edge."""
    nodes, edges, keywords = {}, [], {}
    project_index = {item['id']: item for item in projects}
    pending_index = {item['id']: item for item in pending_groups}
    for company in companies:
        cid = 'company:' + company['id']
        nodes[cid] = {'id': cid, 'type': 'company', 'entity_id': company['id'], 'name': company['name'],
                      'roles': list(company['roles']), 'article_ids': list(company['article_ids']),
                      'article_count': company['article_count']}
        for keyword in company['keywords']:
            kid = keyword['id']
            topic = keywords.setdefault(kid, {'id': kid, 'type': 'keyword', 'entity_id': kid,
                'name': keyword['label'], 'article_ids': set(), 'company_ids': set()})
            topic['article_ids'].update(keyword['article_ids'])
            topic['company_ids'].add(company['id'])
            edges.append({'id': _id('company-edge', cid, kid), 'source': cid, 'target': kid,
                'type': 'keyword_observation', 'article_ids': list(keyword['article_ids']),
                'basis': 'metadata_keywords_in_company_associated_articles', 'status': 'topic_observation',
                'label': '기사 키워드 관측 · 계약 관계 아님'})
        for pid in sorted(set(company['verified_project_ids'] + company['candidate_project_ids'])):
            project = project_index.get(pid)
            if not project:
                continue
            evidence = [item for item in company['role_evidence'] if item['project_id'] == pid]
            confirmed = pid in company['verified_project_ids']
            aids = ordered(aid for item in evidence for aid in item['article_ids']) if evidence else ordered(
                set(company['article_ids']) & set(project['verified_article_ids'] if confirmed else project['candidate_article_ids']))
            if not aids:
                continue
            nid = 'project:' + pid
            nodes.setdefault(nid, {'id': nid, 'type': 'project', 'entity_id': pid,
                'name': project.get('name') or pid, 'article_ids': list(project['article_ids']),
                'article_count': project['article_count'], 'status': project['match_status']})
            edges.append({'id': _id('company-edge', cid, nid), 'source': cid, 'target': nid,
                'type': 'registered_participation' if evidence else ('registered_project_context' if confirmed else 'project_name_candidate'),
                'article_ids': aids, 'basis': 'explicit_stored_relationship' if evidence else
                    ('registered_project_company_context' if confirmed else 'same_article_name_observations'),
                'status': 'registered_evidence' if evidence else 'context_association',
                'roles': list(dict.fromkeys(item['role'] for item in evidence)),
                'raw_roles': list(dict.fromkeys(item['raw_role'] for item in evidence)),
                'label': ' · '.join(dict.fromkeys(item['raw_role'] for item in evidence)) if evidence else '기사·등록 사업 맥락 · 역할 미확인'})
        for gid in company['pending_group_ids']:
            group = pending_index[gid]
            nodes.setdefault(gid, {'id': gid, 'type': 'pending', 'entity_id': gid, 'name': group['name'],
                'article_ids': list(group['article_ids']), 'article_count': group['article_count'],
                'status': 'project_identity_pending'})
            edges.append({'id': _id('company-edge', cid, gid), 'source': cid, 'target': gid,
                'type': 'unidentified_article_group',
                'article_ids': ordered(set(company['direct_article_ids']) & set(group['article_ids'])),
                'basis': 'stored_article_company_association', 'status': 'project_identity_pending',
                'label': '사업 식별 대기 기사 연결 · 동일 사업 미확정'})
    for keyword in keywords.values():
        keyword['article_ids'] = ordered(keyword['article_ids'])
        keyword['article_count'] = len(keyword['article_ids'])
        keyword['company_ids'] = sorted(keyword['company_ids'])
        nodes[keyword['id']] = keyword
    # Every role remains a visible layout slot, including roles with no evidence.
    role_groups = []
    for role, label in ROLE_TAXONOMY.items():
        members = [company for company in companies if role in company['roles']]
        aids = ordered(aid for company in members for aid in company['article_ids'])
        role_aids = ordered(aid for company in members for item in company['role_evidence'] if item['role'] == role for aid in item['article_ids'])
        role_groups.append({'id': role, 'label': label, 'company_ids': [company['id'] for company in members],
            'company_count': len(members), 'article_ids': aids, 'article_count': len(aids),
            'role_evidence_article_ids': role_aids})
        nid = 'role:' + role
        nodes[nid] = {'id': nid, 'type': 'role', 'entity_id': role, 'role': role, 'name': label,
            'company_ids': [company['id'] for company in members], 'company_count': len(members),
            'hubcount': len(members), 'placeholder': not members, 'article_ids': role_aids,
            'article_count': len(role_aids), 'role_evidence_article_ids': role_aids}
        for company in members:
            evidence = [item for item in company['role_evidence'] if item['role'] == role]
            # Unknown companies remain in a filter group, not a fictitious role edge.
            if not evidence:
                continue
            edges.append({'id': _id('company-role', company['id'], role), 'source': 'company:' + company['id'],
                'target': nid, 'type': 'explicit_project_role',
                'article_ids': ordered(aid for item in evidence for aid in item['article_ids']),
                'project_ids': sorted({item['project_id'] for item in evidence}),
                'basis': 'explicit_stored_relationship', 'status': 'registered_evidence',
                'role': role, 'raw_roles': list(dict.fromkeys(item['raw_role'] for item in evidence)),
                'label': label + ' · 명시된 사업 근거에 한정'})
    # Two explicit participants share project context; this is not a direct contract.
    seen_pairs = set()
    for company in companies:
        for counterpart in company.get('counterpart_companies', []):
            pair = tuple(sorted((company['id'], counterpart['company_id']))) + (counterpart['project_id'],)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append({'id': _id('company-context', *pair), 'source': 'company:' + pair[0],
                'target': 'company:' + pair[1], 'type': 'shared_project_context',
                'project_ids': [counterpart['project_id']], 'article_ids': list(counterpart['article_ids']),
                'basis': 'explicit_shared_project_context', 'status': 'context_association',
                'direct_contract_confirmed': False, 'label': '같은 사업의 명시 참여 맥락 · 직접 계약 미확인'})
    all_nodes = list(nodes.values())
    priority = {'role': 0, 'company': 1, 'keyword': 2, 'project': 3, 'pending': 4}
    all_nodes.sort(key=lambda item: (priority[item['type']], -item['article_count'], item['id']))
    focus_id = 'company:' + focus_company_id if focus_company_id else None
    focus_ids={'company:'+cid for cid in (focus_company_ids or ([focus_company_id] if focus_company_id else []))}
    present_focus_ids=focus_ids.intersection(nodes)
    focus_present = bool(present_focus_ids)
    neighbors = set()
    if focus_present:
        for item in edges:
            if item['source'] in present_focus_ids:
                neighbors.add(item['target'])
            if item['target'] in present_focus_ids:
                neighbors.add(item['source'])
        neighbors.difference_update(present_focus_ids)
    # A company picked from the complete catalogue must survive display limits,
    # along with its own one-hop evidence. This changes presentation priority only.
    if focus_id and not focus_present:
        selected_nodes = [{**item, 'company_ids': [], 'company_count': 0, 'hubcount': 0,
            'placeholder': True, 'article_ids': [], 'article_count': 0, 'role_evidence_article_ids': []}
            for item in all_nodes if item['type'] == 'role']
    elif focus_present:
        focus_priority = {'keyword': 0, 'project': 1, 'pending': 2, 'company': 3, 'role': 4}
        selected_nodes = [item for item in all_nodes if item['type'] == 'role'] + [nodes[nid] for nid in sorted(present_focus_ids)]
        selected_ids = {item['id'] for item in selected_nodes}
        focused_nodes = [item for item in all_nodes if item['id'] in neighbors and item['id'] not in selected_ids]
        focused_nodes.sort(key=lambda item: (focus_priority[item['type']], -item['article_count'], item['id']))
        selected_nodes += focused_nodes[:MAX_GRAPH_NODES-len(selected_nodes)]
        selected_ids = {item['id'] for item in selected_nodes}
        selected_nodes += [item for item in all_nodes if item['id'] not in selected_ids][:MAX_GRAPH_NODES-len(selected_nodes)]
    # Reserve space for non-company context even when hundreds of companies match.
    elif len(all_nodes) > MAX_GRAPH_NODES:
        selected_nodes = [item for item in all_nodes if item['type'] == 'role']
        selected_nodes += [item for item in all_nodes if item['type'] == 'company'][:100]
        selected_nodes += [item for item in all_nodes if item['type'] not in ('role', 'company')][:MAX_GRAPH_NODES - len(selected_nodes)]
    else:
        selected_nodes = all_nodes
    visible_ids = {item['id'] for item in selected_nodes}
    selected_edges = [item for item in edges if item['source'] in visible_ids and item['target'] in visible_ids]
    company_article_ids = ordered(aid for company in companies for aid in company['article_ids'])
    return {'nodes': selected_nodes, 'edges': selected_edges, 'role_groups': role_groups,
        'counts': {'companies': len(companies), 'articles': len(company_article_ids),
                   'all_selected_articles': len(article_refs), 'without_company_articles': len(article_refs) - len(company_article_ids),
                   'keywords': len(keywords), 'role_counts': {group['id']: group['company_count'] for group in role_groups},
                   'registered_projects': sum(item['type'] == 'project' for item in all_nodes),
                   'pending_groups': sum(item['type'] == 'pending' for item in all_nodes)},
        'graph': {'total_nodes': len(all_nodes), 'displayed_nodes': len(selected_nodes),
                  'total_edges': len(edges), 'displayed_edges': len(selected_edges),
                  'truncated': len(all_nodes) > len(selected_nodes), 'max_nodes': MAX_GRAPH_NODES,
                  'focus_company_id': focus_company_id, 'focus_node_present': focus_present,
                  'focused_neighbor_count': len(neighbors),
                  'displayed_focused_neighbors': len(neighbors & visible_ids),
                  'focus_truncated': bool(neighbors - visible_ids)},
        'counting_note': '기업별 기사와 역할은 서로 중복될 수 있습니다. 역할은 명시된 사업·근거 기사에 한정되며 키워드 연결은 계약 관계나 기업 전문 분야를 뜻하지 않습니다.'}


def build_ontology(snapshot, workspace, *, focus_company_id=None, focus_company_ids=None):
    """Aggregate exactly the selected relevant articles; never mutate inputs.

    Unidentified article groups are observation buckets, not inferred businesses.
    A bucket can discuss multiple sites. Only explicit stored relationships are
    emitted as participation edges, and only with selected article evidence.
    """
    ds = snapshot.get('datasets', snapshot)
    registered = ds.get('projects', {})
    companies_by_id = dict(ds.get('companies', {}))
    filters = deepcopy(workspace.get('filters', {}))
    articles = list({article['id']: article for article in workspace.get('articles', [])}.values())
    # build_workspace can expose newly observed names without persisting a write.
    for article in articles:
        for company in article.get('matched_companies', []):
            companies_by_id.setdefault(company['id'], {'id': company['id'], 'name': company.get('name', company['id']),
                                                       'classification': 'observed_name_only'})
    articles.sort(key=lambda item: (str(item.get('published_at', '')), item['id']), reverse=True)
    by_id = {article['id']: article for article in articles}
    article_order = {article['id']: index for index, article in enumerate(articles)}

    def ordered(ids):
        return sorted(set(ids), key=lambda aid: article_order.get(aid, len(article_order)))

    scopes = {key: {'id': key, 'name': name, 'article_ids': [], 'project_ids': [],
                    'pending_group_ids': [], 'location_groups': []} for key, name in SCOPES.items()}
    locations, pending, project_articles, company_articles = {}, {}, {}, {}
    explicit_article_ids, candidate_article_ids, pending_article_ids = set(), set(), set()
    article_refs = {}
    for article in articles:
        aid, scope = article['id'], _scope(article)
        scopes[scope]['article_ids'].append(aid)
        article_refs[aid] = {key: deepcopy(article.get(key)) for key in
                             ('id', 'title', 'url', 'publisher', 'published_at', 'summary', 'mode', 'access_status')}
        article_refs[aid]['scope'] = scope
        direct = set(article.get('company_ids', [])) & set(companies_by_id)
        verified = set(article.get('project_ids', [])) & set(registered)
        candidates = (set(article.get('candidate_project_ids', [])) & set(registered)) - verified
        contextual = set().union(*(set(registered[pid].get('company_ids', [])) for pid in verified)) if verified else set()
        company_ids = direct | (contextual & set(companies_by_id))
        for cid in company_ids:
            entry = company_articles.setdefault(cid, {'direct': [], 'context': [], 'verified': set(), 'candidate': set(), 'pending': set()})
            if cid in direct:
                entry['direct'].append(aid)
            if cid in contextual:
                entry['context'].append(aid)
            entry['verified'].update(pid for pid in verified if cid in registered[pid].get('company_ids', []))
            entry['candidate'].update(candidates)
        for pid in verified | candidates:
            entry = project_articles.setdefault(pid, {'verified': [], 'candidate': []})
            entry['verified' if pid in verified else 'candidate'].append(aid)
        if verified:
            explicit_article_ids.add(aid)
        elif candidates:
            candidate_article_ids.add(aid)
        else:
            pending_article_ids.add(aid)

        place_ids = []
        for kind, value, country, name in _locations(article, scope):
            lid = _id('location', scope, kind, value)
            place_ids.append(lid)
            place = locations.setdefault(lid, {'id': lid, 'name': name, 'scope': scope, 'kind': kind,
                                               'value': value, 'country': country, 'article_ids': [],
                                               'project_ids': set(), 'pending_group_ids': set()})
            place['article_ids'].append(aid)
            place['project_ids'].update(verified | candidates)
        if not (verified | candidates):
            # Keep multi-location articles together without guessing a unique site.
            location_key = tuple(sorted(place_ids))
            group_id = _id('pending', scope, location_key, tuple(sorted(direct)))
            names = [locations[lid]['name'] for lid in place_ids]
            location_name = ', '.join(names)
            company_names = [companies_by_id[cid].get('name', cid) for cid in sorted(direct)]
            label = ' · '.join([location_name] + ([', '.join(company_names)] if company_names else ['기업명 미확인']))
            group = pending.setdefault(group_id, {'id': group_id, 'name': '사업 식별 대기 기사 묶음 · ' + label,
                'scope': scope, 'location_group_id': place_ids[0] if len(place_ids) == 1 else None,
                'location_group_ids': place_ids, 'location': location_name, 'company_ids': sorted(direct),
                'article_ids': [], 'status': 'project_identity_pending', 'basis': 'metadata_observation_group',
                'is_confirmed_project': False,
                'summary': '같은 분류·명시 지명·기업명 관측을 취합한 기사 묶음입니다. 동일 사업·동일 부지·참여 관계를 뜻하지 않습니다.'})
            group['article_ids'].append(aid)
            for lid in place_ids:
                locations[lid]['pending_group_ids'].add(group_id)
            for cid in direct:
                company_articles[cid]['pending'].add(group_id)

    projects = []
    for pid, project in registered.items():
        linkage = project_articles.get(pid, {'verified': [], 'candidate': []})
        aids = ordered(linkage['verified'] + linkage['candidate'])
        if not aids and not _project_visible(project, filters):
            continue
        entry = {key: deepcopy(project.get(key)) for key in ('id', 'name', 'scope', 'country', 'location',
                 'entity_level', 'parent_id', 'status', 'classification', 'validation_state', 'summary', 'company_ids')}
        entry.update({'article_ids': aids, 'article_count': len(aids),
                      'verified_article_ids': ordered(linkage['verified']),
                      'candidate_article_ids': ordered(linkage['candidate']),
                      'match_status': 'registered_evidence' if linkage['verified'] else
                          ('name_match_candidate' if linkage['candidate'] else 'no_selected_articles')})
        projects.append(entry)
        if project.get('scope') in scopes:
            scopes[project['scope']]['project_ids'].append(pid)
    projects.sort(key=lambda item: (-item['article_count'], item.get('name') or item['id']))
    for place in locations.values():
        place['article_ids'] = ordered(place['article_ids'])
        place['article_count'] = len(place['article_ids'])
        place['project_ids'] = sorted(place['project_ids'])
        place['pending_group_ids'] = sorted(place['pending_group_ids'])
        scopes[place['scope']]['location_groups'].append(place)
    for group in pending.values():
        group['article_ids'] = ordered(group['article_ids'])
        group['article_count'] = len(group['article_ids'])
        scopes[group['scope']]['pending_group_ids'].append(group['id'])
    pending_groups = sorted(pending.values(), key=lambda item: (-item['article_count'], item['id']))
    role_evidence = {}
    for relationship in ds.get('relationships', {}).values():
        pid, cid = relationship.get('project_id'), relationship.get('company_id')
        if pid not in project_articles or cid not in companies_by_id or relationship.get('directness') != 'explicit':
            continue
        aids = ordered(set(relationship.get('article_ids', [])) & set(project_articles[pid]['verified']) & set(by_id))
        if not aids:
            continue
        linkage = company_articles.setdefault(cid, {'direct': [], 'context': [], 'verified': set(), 'candidate': set(), 'pending': set()})
        linkage['context'].extend(aids)
        linkage['verified'].add(pid)
        raw_role = str(relationship.get('role') or '').strip()
        for role in _roles(raw_role):
            role_evidence.setdefault(cid, []).append({'role': role, 'label': ROLE_TAXONOMY[role],
                'project_id': pid, 'raw_role': raw_role, 'article_ids': aids,
                'relationship_id': relationship['id'], 'basis': 'explicit_stored_relationship'})
    company_entries = []
    for cid, linkage in company_articles.items():
        company = companies_by_id[cid]
        aids = ordered(linkage['direct'] + linkage['context'])
        keywords = {}
        for aid in aids:
            for category in by_id[aid].get('business_categories', []):
                if isinstance(category, str) and category.strip():
                    label = category.strip()
                    keywords.setdefault(label, []).append(aid)
        keyword_entries = [{'id': _id('keyword', label), 'label': label, 'article_ids': ordered(ids),
                            'article_count': len(set(ids)), 'basis': 'metadata_keywords'}
                           for label, ids in keywords.items()]
        keyword_entries.sort(key=lambda item: (-item['article_count'], item['label']))
        evidence = role_evidence.get(cid, [])
        roles = [role for role in ROLE_TAXONOMY if any(item['role'] == role for item in evidence)]
        roles = roles or ['unknown']
        scope_article_ids = {sid: [aid for aid in aids if _scope(by_id[aid]) == sid] for sid in SCOPES}
        scope_text = ', '.join(f'{SCOPES[sid]} {len(ids)}개' for sid, ids in scope_article_ids.items() if ids)
        role_text = ', '.join(ROLE_TAXONOMY[role] for role in roles if role != 'unknown')
        summary_evidence = [
            {'text': f'선택 조건에서 {company.get("name", cid)} 관련 기사 {len(aids)}개를 중복 제거해 취합했습니다.',
             'article_ids': aids, 'basis': 'selected_company_article_aggregation'},
            {'text': f'기사 범위는 {scope_text}입니다.', 'article_ids': aids, 'basis': 'selected_article_scope_partition'},
            {'text': ('관측 키워드는 ' + ', '.join(item['label'] for item in keyword_entries[:6]) + '입니다. 키워드는 계약 관계나 기업 전문 분야를 확정하지 않습니다.')
                     if keyword_entries else '기사 메타데이터에 분류된 관측 키워드는 없습니다.',
             'article_ids': ordered(aid for item in keyword_entries[:6] for aid in item['article_ids']), 'basis': 'metadata_keywords'},
            {'text': ('선택 기사에 근거가 있는 역할은 ' + role_text + '입니다. 역할은 각 사업의 근거에 한정됩니다.')
                     if role_text else '선택 기사 근거에서 발주처·사업자·테넌트·시공사·설계사·운영사·장비사 역할이 확정되지 않았습니다.',
             'article_ids': ordered(aid for item in evidence for aid in item['article_ids']),
             'basis': 'explicit_stored_relationship' if evidence else 'role_unresolved'}]
        company_entries.append({'id': cid, 'name': company.get('name', cid),
            **profile_fields(company, ds.get('company_classifications', {}).get(cid)),
            'classification': company.get('classification', 'registered_company'),
            'article_ids': aids, 'article_count': len(aids), 'direct_article_ids': ordered(linkage['direct']),
            'registered_context_article_ids': ordered(linkage['context']),
            'verified_project_ids': sorted(linkage['verified']), 'candidate_project_ids': sorted(linkage['candidate']),
            'pending_group_ids': sorted(linkage['pending']),
            'roles': roles, 'role_evidence': evidence, 'keywords': keyword_entries, 'keyword_count': len(keyword_entries),
            'summary_lines': [line['text'] for line in summary_evidence], 'summary_evidence': summary_evidence,
            'summary': f'선택 기사 {len(aids)}개. 기사에 직접 연결된 기업 관측 {len(set(linkage["direct"]))}개와 등록 사업 맥락 {len(set(linkage["context"]))}개를 중복 제거했습니다. 기사 연결·이름 등장은 참여·계약 확정이 아닙니다.'})
    company_entries.sort(key=lambda item: (-item['article_count'], item['name']))
    participants = {}
    for company in company_entries:
        company['counterpart_companies'] = []
        for pid in {item['project_id'] for item in company['role_evidence']}:
            participants.setdefault(pid, []).append(company)
    for pid, members in participants.items():
        for company in members:
            own = [item for item in company['role_evidence'] if item['project_id'] == pid]
            for other in members:
                if company['id'] == other['id']:
                    continue
                theirs = [item for item in other['role_evidence'] if item['project_id'] == pid]
                company['counterpart_companies'].append({'company_id': other['id'], 'name': other['name'],
                    'project_id': pid, 'roles': list(dict.fromkeys(item['role'] for item in theirs)),
                    'article_ids': ordered(aid for item in own + theirs for aid in item['article_ids']),
                    'basis': 'explicit_shared_project_context', 'direct_contract_confirmed': False})
    for scope in scopes.values():
        scope['article_count'] = len(scope['article_ids'])
        scope['location_groups'].sort(key=lambda item: (-item['article_count'], item['name']))

    # IDs below belong to the visual graph; entity_id retains the source identity.
    nodes, edges = [], []

    def node(nid, node_type, name, aids, **extra):
        nodes.append({'id': nid, 'type': node_type, 'name': name, 'article_ids': ordered(aids),
                      'article_count': len(set(aids)), **extra})

    def edge(source, target, kind, aids, basis, status, **extra):
        edges.append({'id': _id('edge', source, target, kind), 'source': source, 'target': target,
                      'type': kind, 'article_ids': ordered(aids), 'basis': basis, 'status': status, **extra})

    for sid, scope in scopes.items():
        node('scope:' + sid, 'scope', scope['name'], scope['article_ids'], scope=sid, entity_id=sid)
        for place in scope['location_groups']:
            node(place['id'], 'location', place['name'], place['article_ids'], scope=sid,
                 entity_id=place['id'], kind=place['kind'], country=place['country'])
            edge('scope:' + sid, place['id'], 'geography_observation', place['article_ids'],
                 'explicit_metadata_place_or_registered_project_context', 'location_candidate')
    for project in projects:
        nid = 'project:' + project['id']
        node(nid, 'project', project.get('name') or project['id'], project['article_ids'],
             entity_id=project['id'], scope=project.get('scope'), status=project['match_status'])
        if project.get('scope') in scopes:
            edge('scope:' + project['scope'], nid, 'registered_project', project['article_ids'],
                 'registered_project_record', project['match_status'])
        parent = project.get('parent_id')
        if parent and any(p['id'] == parent for p in projects):
            edge('project:' + parent, nid, 'project_hierarchy', project['verified_article_ids'],
                 'registered_program_site_phase', 'registered_record', role='포함 관계 · 용량 합산 금지')
    for group in pending_groups:
        node(group['id'], 'pending', group['name'], group['article_ids'], entity_id=group['id'],
             scope=group['scope'], status='project_identity_pending')
        for lid in group['location_group_ids']:
            edge(lid, group['id'], 'unidentified_article_group', group['article_ids'],
                 'metadata_observation_group', 'project_identity_pending')
    for company in company_entries:
        node('company:' + company['id'], 'company', company['name'], company['article_ids'],
             entity_id=company['id'], status='name_observation_and_registered_context')
        for gid in company['pending_group_ids']:
            aids = set(company['direct_article_ids']) & set(pending[gid]['article_ids'])
            edge(gid, 'company:' + company['id'], 'name_mention', aids,
                 'stored_article_company_association', 'name_match_candidate', role='기업 연결 관측 · 참여 미확인')
    for relationship in ds.get('relationships', {}).values():
        pid, cid = relationship.get('project_id'), relationship.get('company_id')
        if pid not in project_articles or cid not in company_articles or relationship.get('directness') != 'explicit':
            continue
        aids = set(relationship.get('article_ids', [])) & set(project_articles[pid]['verified']) & set(by_id)
        if aids:
            edge('project:' + pid, 'company:' + cid, 'registered_participation', aids,
                 'explicit_stored_relationship', 'registered_evidence', role=relationship.get('role', '명시 역할'))

    # Preserve hierarchy/context for every displayed node. Full aggregation remains above.
    order = {'scope': 0, 'location': 1, 'project': 2, 'pending': 3, 'company': 4}
    nodes.sort(key=lambda item: (order[item['type']], -item['article_count'], item['id']))
    all_node_count = len(nodes)
    if all_node_count > MAX_GRAPH_NODES:
        # Reserve company context while limiting the costly graph, never article data.
        primary = [n for n in nodes if n['type'] in ('scope', 'location', 'project')]
        companies_nodes = [n for n in nodes if n['type'] == 'company'][:40]
        room = max(0, MAX_GRAPH_NODES - len(primary) - len(companies_nodes))
        nodes = (primary + [n for n in nodes if n['type'] == 'pending'][:room] + companies_nodes)[:MAX_GRAPH_NODES]
    visible_ids = {item['id'] for item in nodes}
    edges = [item for item in edges if item['source'] in visible_ids and item['target'] in visible_ids]
    scope_counts = {sid: scope['article_count'] for sid, scope in scopes.items()}
    counts = {'articles': len(articles), 'scope_articles': scope_counts,
              'registered_projects': len(projects),
              'verified_projects': sum(bool(p['verified_article_ids']) for p in projects),
              'candidate_projects': sum(bool(p['candidate_article_ids']) for p in projects),
              'observed_companies': len(company_entries), 'pending_articles': len(pending_article_ids),
              'pending_groups': len(pending_groups), 'verified_project_articles': len(explicit_article_ids),
              'candidate_project_articles': len(candidate_article_ids)}
    summary = [{'text': f'{SCOPES[sid]} 기사 {count}개를 같은 기간·검색 조건으로 취합했습니다.',
                'article_ids': list(scopes[sid]['article_ids']), 'basis': 'selected_article_scope_partition'}
               for sid, count in scope_counts.items() if count]
    if pending_article_ids:
        summary.append({'text': f'사업명 식별 대기 기사 {len(pending_article_ids)}개는 {len(pending_groups)}개 관측 묶음으로 표시합니다. 묶음 수는 사업 수가 아닙니다.',
                        'article_ids': ordered(pending_article_ids), 'basis': 'project_identity_unresolved'})
    attention = build_attention(snapshot, workspace)
    attention_index = {item['id']: item for item in attention['items']}
    company_ontology = _company_graph(company_entries, projects, pending_groups, article_refs, ordered, focus_company_id, focus_company_ids)

    def annotate(item):
        kind = item.get('type')
        entity = item.get('entity_id')
        if kind == 'company':
            item.update(attention_annotation(attention, company_ids=[entity], item_index=attention_index))
        elif kind == 'project':
            item.update(attention_annotation(attention, project_ids=[entity], item_index=attention_index))
        else:
            edge_projects = set(item.get('project_ids', []))
            if item.get('source') or item.get('target'):
                for endpoint in (item.get('source', ''), item.get('target', '')):
                    if endpoint.startswith('project:'):
                        edge_projects.add(endpoint[len('project:'):])
            item.update(attention_annotation(attention, article_ids=item.get('article_ids', []),
                item_index=attention_index, restrict_project_ids=edge_projects))
        return item

    for company in company_entries:
        company.update(attention_annotation(attention, company_ids=[company['id']], item_index=attention_index))
        for keyword in company['keywords']:
            keyword.update(attention_annotation(attention, article_ids=keyword['article_ids'], item_index=attention_index))
    for project in projects:
        project.update(attention_annotation(attention, project_ids=[project['id']], item_index=attention_index))
    for collection in (pending_groups, list(locations.values()), summary):
        for item in collection:
            annotate(item)
    for collection in (nodes, edges, company_ontology['nodes'], company_ontology['edges']):
        for item in collection:
            annotate(item)
    return {'counts': counts, 'filters': filters, 'scopes': list(scopes.values()), 'projects': projects,
            'pending_groups': pending_groups, 'companies': company_entries, 'article_refs': article_refs,
            'role_taxonomy': [{'id': role, 'label': label} for role, label in ROLE_TAXONOMY.items()],
            'profile_taxonomy': [{'id': category, 'label': label} for category, label in PROFILE_LABELS.items()],
            'company_ontology': company_ontology, 'attention': attention,
            'nodes': nodes, 'edges': edges, 'summary': summary,
            'graph': {'total_nodes': all_node_count, 'displayed_nodes': len(nodes),
                      'truncated': all_node_count > len(nodes), 'max_nodes': MAX_GRAPH_NODES},
            'counting_note': '기사 전체는 국내 DC+국내 AIDC+해외 AIDC+분류 대기의 합입니다. 등록 사업·기업·지역은 여러 기사와 연결되며 합산하지 않습니다.',
            'limitations': ['기사 묶음과 기업 이름 등장은 사업·동일 부지·계약·참여 관계를 확정하지 않습니다.',
                            '등록 사업은 과거 고정 근거를 포함합니다. 기사와 사업의 수는 서로 다른 지표입니다.',
                            '본문·사내 AI 품질·선택 기간의 모든 기사 확보를 보장하지 않습니다.']}
