"""Pure display projection of explicitly approved logical project identities.

Source JSON, facts, roles, coordinates, notification IDs and read states retain
their original meaning. Only the selected article context is combined here.
"""
from copy import deepcopy
import json


def _unique(values):
    result, seen = [], set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def apply(data, identity_workspace):
    groups = [group for group in identity_workspace.get('active_groups', [])
              if group.get('state') == 'approved' and group.get('active', True)
              and not group.get('stale') and not group.get('conflicts')]
    if not groups:
        return data
    selected = {a['id'] for a in data.get('news', {}).get('articles', [])}
    projects = {p['id']: p for p in data.get('projects', [])}
    project_map, mention_map, contexts = {}, {}, []
    for group in groups:
        members = group.get('members', [])
        registered = [m['id'] for m in members if m.get('kind') == 'project']
        canonical_ref = group.get('canonical_ref', '')
        display = canonical_ref[8:] if canonical_ref.startswith('project:') else (
            registered[0] if registered else 'identity:' + group['id'])
        aids = selected.intersection(group.get('article_ids', group.get('source_article_ids', [])))
        if not aids:
            continue
        # Local display associations include selected manual/private records.
        # These are source links, never additional public identity evidence or
        # provider inputs. The explicitly confirmed evidence stays separate.
        source_associations = selected.intersection(aid for pid in registered
            for aid in projects.get(pid, {}).get('article_ids', []))
        source_associations.update(article['id'] for article in data.get('news', {}).get('articles', [])
            if set(registered).intersection(article.get('project_ids', [])))
        context = {'id': display, 'name': group.get('canonical_title', display),
                   'identity_group_id': group['id'], 'source_project_ids': registered,
                   'identity_article_ids': sorted(aids), 'article_ids': sorted(aids | source_associations),
                   'source_article_ids': sorted(aids), 'source_association_article_ids': sorted(source_associations),
                   'aliases': _unique(group.get('aliases', []) + [m['name'] for m in members if m.get('name')]),
                   'user_confirmed_identity': True, 'is_candidate': not registered}
        contexts.append(context)
        for member in members:
            if member.get('kind') == 'project':
                project_map[member['id']] = display
            elif member.get('kind') == 'mention':
                mention_map[member['id']] = display
    if not contexts:
        return data
    by_display = {item['id']: item for item in contexts}
    result = dict(data)

    def context_fields(context):
        return {key: deepcopy(value) for key, value in context.items() if key not in ('id', 'name', 'article_ids', 'is_candidate')}

    def project_rows(rows):
        output, seen = [], set()
        index = {row['id']: row for row in rows}
        for row in rows:
            ident = project_map.get(row['id'], row['id'])
            if ident in seen:
                continue
            seen.add(ident)
            context = by_display.get(ident)
            if context is None or context['is_candidate']:
                output.append(row)
                continue
            # Facts, capacities, parent, phase and every scalar come exclusively
            # from the chosen registered record, never from alias records.
            canonical = deepcopy(index.get(ident, projects.get(ident, row)))
            canonical.update(id=ident, name=context['name'], **context_fields(context))
            canonical['article_ids'] = list(context['article_ids'])
            canonical['article_count'] = len(canonical['article_ids'])
            for field in ('verified_article_ids', 'candidate_article_ids', 'company_ids'):
                if any(field in item for item in rows if project_map.get(item['id'], item['id']) == ident):
                    values = [value for item in rows if project_map.get(item['id'], item['id']) == ident for value in item.get(field, [])]
                    canonical[field] = _unique(value for value in values if field == 'company_ids' or value in selected)
            output.append(canonical)
        return output

    result['projects'] = project_rows(data.get('projects', []))
    discovery = deepcopy(data.get('project_discovery', {}))
    raw_mentions = discovery.get('mentions', [])
    selected_mentions = {m['id']: m for m in raw_mentions if selected.intersection(m.get('article_ids', []) + ([m['article_id']] if m.get('article_id') else []))}
    candidate_map = {}

    def aggregate(template, mentions, ident, name):
        entry = deepcopy(template)
        entry.update(id=ident, name=name, mention_ids=[m['id'] for m in mentions])
        entry['article_ids'] = sorted(selected.intersection(aid for m in mentions for aid in m.get('article_ids', []) + ([m['article_id']] if m.get('article_id') else [])))
        entry['article_count'] = len(entry['article_ids'])
        for field in ('cities', 'countries', 'company_ids', 'stage_signals', 'capacity_signals', 'company_observations'):
            entry[field] = _unique(deepcopy(value) for m in mentions for value in m.get(field, []))
        entry['name_evidence'] = [deepcopy(m['evidence']) for m in mentions if m.get('evidence')]
        entry['company_links'] = []
        for mention in mentions:
            for raw in mention.get('company_links', []):
                link = deepcopy(raw)
                if raw.get('project_id'):
                    link['source_project_id'] = raw['project_id']
                link['project_id'] = ident
                if 'article_ids' in link:
                    link['article_ids'] = [aid for aid in link['article_ids'] if aid in selected]
                entry['company_links'].append(link)
        entry['location'] = ' · '.join(entry['cities'])
        return entry

    candidates = []
    for candidate in discovery.get('project_candidates', []):
        ids = candidate.get('mention_ids', [])
        approved = [mid for mid in ids if mid in mention_map]
        if not approved:
            candidates.append(candidate)
            continue
        remaining = [selected_mentions[mid] for mid in ids if mid not in mention_map and mid in selected_mentions]
        if remaining:
            candidates.append(aggregate(candidate, remaining, candidate['id'], candidate['name']))
        elif len({mention_map[mid] for mid in approved}) == 1:
            candidate_map[candidate['id']] = mention_map[approved[0]]
    for context in contexts:
        mentions = [m for mid, m in selected_mentions.items() if mention_map.get(mid) == context['id']]
        if context['is_candidate']:
            template = {'scope': mentions[0].get('scope', 'unresolved') if mentions else 'unresolved',
                        'is_candidate': True, 'is_confirmed_project': False,
                        'identity_status': 'user_confirmed_display_only', 'status': 'candidate',
                        'summary': '사용자가 확인한 표시 연결입니다. 등록 사업·직접 계약은 미확인입니다.'}
            candidate = aggregate(template, mentions, context['id'], context['name'])
            candidate.update(context_fields(context), article_ids=list(context['article_ids']), article_count=len(context['article_ids']))
            candidate['raw_mentions'] = deepcopy(mentions)
            candidates.append(candidate)
    discovery['project_candidates'] = candidates
    if isinstance(discovery.get('counts'), dict):
        discovery['counts']['source_candidate_name_groups'] = discovery['counts'].get('candidate_name_groups')
        discovery['counts']['candidate_name_groups'] = len(candidates)
    # Keep raw mention observations and their IDs as evidence. Only the candidate
    # grouping above changes; partial groups retain their unapproved members.
    projection = {**project_map, **candidate_map, **mention_map,
                  **{'mention:' + mid: display for mid, display in mention_map.items()}}

    def remap(item):
        if isinstance(item, list):
            return [remap(value) for value in item]
        if not isinstance(item, dict):
            return item
        output = {}
        for key, value in item.items():
            if key in ('attention', 'read_states', 'news_read_states', 'attention_ids', 'source_project_ids', 'source_project_id'):
                output[key] = deepcopy(value)
            elif key == 'project_id' and isinstance(value, str):
                output[key] = projection.get(value, value)
                if output[key] != value:
                    output['source_project_id'] = value
            elif key in ('project_ids', 'verified_project_ids', 'candidate_project_ids') and isinstance(value, list):
                output[key] = _unique(projection.get(pid, pid) for pid in value)
                if output[key] != value:
                    output['source_' + key] = deepcopy(value)
            elif key == 'projects' and isinstance(value, list) and all(isinstance(row, dict) and 'id' in row for row in value):
                output[key] = project_rows(value)
            else:
                output[key] = remap(value)
        if item.get('project_id') in projection and 'article_ids' in output:
            output['article_ids'] = [aid for aid in output['article_ids'] if aid in selected]
        return output

    links = []
    rebuilt_ids = {candidate['id'] for candidate in data.get('project_discovery', {}).get('project_candidates', [])
                   if any(mid in mention_map for mid in candidate.get('mention_ids', []))}
    for link in discovery.get('company_links', []):
        # Old name groups may contain both approved and unapproved observations.
        # Rebuild those from the selected raw mentions instead of projecting the
        # entire old group to the canonical display identity.
        if link.get('project_is_candidate') and link.get('project_id') in rebuilt_ids:
            continue
        links.append(remap(link))
    for candidate in candidates:
        links.extend(deepcopy(candidate.get('company_links', [])))
    # Approved mentions attached to a registered identity remain observations;
    # their role/directness flags are copied without upgrading participation.
    for mid, display in mention_map.items():
        if display in by_display and not by_display[display]['is_candidate'] and mid in selected_mentions:
            for raw in selected_mentions[mid].get('company_links', []):
                link = deepcopy(raw)
                link.update(project_id=display)
                if raw.get('project_id'):
                    link['source_project_id'] = raw['project_id']
                link['article_ids'] = [aid for aid in link.get('article_ids', []) if aid in selected]
                links.append(link)
    discovery['company_links'] = _unique(links)
    result['project_discovery'] = discovery

    def node_id(ident):
        if not isinstance(ident, str):
            return ident
        if ident.startswith('mention:') and ident in projection:
            target = projection[ident]
            return ('discovery:' if by_display[target]['is_candidate'] else 'project:') + target
        if ident.startswith('project:'):
            return 'project:' + projection.get(ident[8:], ident[8:])
        if ident.startswith('discovery:'):
            value = ident[10:]
            target = projection.get(value, value)
            return ('discovery:' if by_display.get(target, {}).get('is_candidate', True) else 'project:') + target
        return projection.get(ident, ident)

    def graph(graph_data):
        output = remap(graph_data)
        if isinstance(graph_data.get('projects'), list):
            output['projects'] = project_rows(graph_data['projects'])
        nodes, index = [], {}
        raw_nodes = sorted(graph_data.get('nodes', []), key=lambda row: 0 if row.get('entity_id') in by_display else 1)
        for raw in raw_nodes:
            node = remap(raw)
            original = raw['id']
            node['id'] = node_id(original)
            entity = raw.get('entity_id')
            if isinstance(entity, str) and entity in projection:
                node['entity_id'] = projection[entity]
            context = by_display.get(node.get('entity_id'))
            if context:
                node.update(name=context['name'], **context_fields(context))
                node['article_ids'] = list(context['article_ids'])
                node['article_count'] = len(node['article_ids'])
            node['source_node_ids'] = _unique(raw.get('source_node_ids', []) + [original])
            if entity is not None:
                node['source_entity_ids'] = _unique(raw.get('source_entity_ids', []) + [entity])
            if node['id'] in index:
                prior = index[node['id']]
                for field in ('article_ids', 'attention_ids', 'source_node_ids', 'source_entity_ids'):
                    prior[field] = _unique(prior.get(field, []) + node.get(field, []))
                prior['article_count'] = len(prior.get('article_ids', []))
            else:
                if context:
                    node['article_ids'] = list(context['article_ids'])
                    node['article_count'] = len(node['article_ids'])
                index[node['id']] = node
                nodes.append(node)
        edges, edge_index = [], {}
        identity_endpoints = {prefix + context['id'] for context in contexts for prefix in ('', 'project:', 'discovery:')}
        for raw in graph_data.get('edges', []):
            edge = remap(raw)
            edge['source'], edge['target'] = node_id(raw.get('source')), node_id(raw.get('target'))
            if edge['source'] == edge['target']:
                continue
            if edge['source'] in identity_endpoints or edge['target'] in identity_endpoints:
                edge['article_ids'] = [aid for aid in edge.get('article_ids', []) if aid in selected]
                if 'article_count' in edge:
                    edge['article_count'] = len(edge['article_ids'])
            marker = json.dumps([edge.get(field) for field in ('source', 'target', 'type', 'role', 'roles', 'raw_roles', 'basis', 'status', 'directness', 'is_confirmed_participation', 'direct_contract_confirmed')], sort_keys=True, ensure_ascii=False)
            edge['source_edge_ids'] = _unique(raw.get('source_edge_ids', []) + ([raw['id']] if raw.get('id') else []))
            edge['source_endpoints'] = deepcopy(raw.get('source_endpoints', [])) + [{'source': raw.get('source'), 'target': raw.get('target')}]
            if marker in edge_index:
                previous = edge_index[marker]
                for field in ('article_ids', 'attention_ids', 'source_edge_ids', 'source_endpoints'):
                    previous[field] = _unique(previous.get(field, []) + edge.get(field, []))
            else:
                edge_index[marker] = edge
                edges.append(edge)
        if 'nodes' in graph_data:
            output['nodes'] = nodes
        if 'edges' in graph_data:
            output['edges'] = edges
        if isinstance(graph_data.get('company_ontology'), dict):
            output['company_ontology'] = graph(graph_data['company_ontology'])
        if isinstance(output.get('counts'), dict) and 'projects' in output:
            output['counts']['source_registered_projects'] = graph_data.get('counts', {}).get('registered_projects')
            output['counts']['registered_projects'] = len(output['projects'])
            if 'verified_projects' in output['counts']:
                output['counts']['verified_projects'] = sum(bool(p.get('verified_article_ids')) for p in output['projects'])
        if isinstance(output.get('graph'), dict):
            output['graph']['source_displayed_nodes'] = graph_data.get('graph', {}).get('displayed_nodes')
            output['graph']['displayed_nodes'] = len(nodes)
        return output

    if isinstance(data.get('ontology'), dict):
        result['ontology'] = graph(data['ontology'])
    for key in ('companies', 'company_catalog', 'company_links', 'relationships'):
        if key in data:
            result[key] = remap(data[key])
    if isinstance(data.get('company_ontology'), dict):
        result['company_ontology'] = graph(data['company_ontology'])
    if 'maps' in data:
        result['maps'] = remap(data['maps'])  # coordinates and marker IDs unchanged
    news = dict(data.get('news', {}))
    news['articles'] = []
    for raw in data.get('news', {}).get('articles', []):
        article = dict(raw)
        matches = [context for context in contexts if raw['id'] in context['article_ids']]
        if matches or any(pid in project_map for pid in raw.get('project_ids', [])):
            article['identity_project_ids'] = _unique([project_map.get(pid, pid) for pid in raw.get('project_ids', [])] + [c['id'] for c in matches])
            article['identity_contexts'] = [deepcopy(c) for c in matches]
        news['articles'].append(article)
    result['news'] = news
    result['identity_display'] = {'contexts': deepcopy(contexts), 'project_id_map': dict(project_map),
                                  'mention_id_map': dict(mention_map),
                                  'source_projects': [deepcopy(projects[pid]) for pid in project_map if pid in projects],
                                  'source_records_modified': False}
    return result
