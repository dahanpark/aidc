"""Read-only attention projection and exact-ID acknowledgements.

New articles, registered fact changes, and their delivery notifications remain
different source records. A notification never creates another fact change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def recent_article(article, datasets, reference=None):
    """Publication recency is independent of collection time and read state."""
    days = datasets.get('settings', {}).get('app', {}).get('new_article_days', 30)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365:
        days = 30
    try:
        published = datetime.fromisoformat(article.get('published_at', '').replace('Z', '+00:00'))
        end = datetime.fromisoformat(reference.replace('Z', '+00:00')) if reference else datetime.now(timezone.utc)
        if published.tzinfo is None or end.tzinfo is None:
            return False
        return end - timedelta(days=days) <= published <= end
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


def _article_companies(article, datasets):
    companies = set(article.get('company_ids', []))
    companies.update(item['id'] for item in article.get('matched_companies', []))
    for pid in article.get('project_ids', []):
        companies.update(datasets.get('projects', {}).get(pid, {}).get('company_ids', []))
    for relationship in datasets.get('relationships', {}).values():
        if (relationship.get('directness') == 'explicit'
                and relationship.get('project_id') in article.get('project_ids', [])
                and article['id'] in relationship.get('article_ids', [])):
            companies.add(relationship['company_id'])
    return companies


def _metric(items):
    unread = [item for item in items if item['unread'] and
              (item['type'] != 'new_article' or item.get('is_recent', True))]
    return {'attention_ids': [item['id'] for item in items],
            'unread_attention_ids': [item['id'] for item in unread],
            'unread_count': len(unread),
            'new_article_count': sum(item['type'] == 'new_article' for item in unread),
            'fact_change_count': sum(item['type'] == 'fact_change' for item in unread),
            'has_unread': bool(unread)}


def build_attention(snapshot, workspace):
    """Return attention for the workspace's selected relevant articles only."""
    ds = snapshot.get('datasets', snapshot)
    articles = {item['id']: item for item in workspace.get('articles', [])}
    selected = set(articles)
    notices = {}
    orphan_notices = []
    for notice in ds.get('notifications', {}).values():
        if notice.get('change_id') in ds.get('changes', {}):
            notices.setdefault(notice['change_id'], []).append(notice)
        else:
            orphan_notices.append(notice['id'])
    updates = {}
    for update in ds.get('news_updates', {}).values():
        if update.get('article_id') in selected:
            updates.setdefault(update['article_id'], []).append(update)
    items = []
    for aid, sources in updates.items():
        article = articles[aid]
        pids = set(article.get('project_ids', [])) | set(article.get('candidate_project_ids', []))
        cids = _article_companies(article, ds)
        # Original update references may include an explicit candidate association.
        for update in sources:
            pids.update(update.get('project_ids', []))
            cids.update(update.get('company_ids', []))
        items.append({'id': 'new_article:' + aid, 'type': 'new_article', 'label': '신규 기사',
            'title': article.get('title', ''), 'article_ids': [aid], 'project_ids': sorted(pids),
            'company_ids': sorted(cids), 'created_at': min(str(update.get('created_at') or article.get('collected_at') or article.get('published_at') or '') for update in sources),
            'unread': any(not ds.get('news_read_states', {}).get(update['id'], {}).get('read_at') for update in sources),
            'source_update_ids': sorted(update['id'] for update in sources), 'change_ids': [], 'notification_ids': [],
            'mode': article.get('mode', 'unverified'), 'is_verified_fact_change': False})
        items[-1]['is_recent'] = recent_article(article, ds, workspace.get('filters', {}).get('end'))
        items[-1]['published_at'] = article.get('published_at')
        items[-1]['url'] = article.get('url')
    for change in ds.get('changes', {}).values():
        aids = sorted(set(change.get('article_ids', [])) & selected)
        if not aids:
            continue
        pid = change.get('project_id')
        project = ds.get('projects', {}).get(pid, {})
        cids = set(project.get('company_ids', []))
        for aid in aids:
            cids.update(_article_companies(articles[aid], ds))
        linked_notices = notices.get(change['id'], [])
        # An unread delivery and an unread change are one pending attention item.
        unread = not ds.get('read_states', {}).get(change['id'], {}).get('read_at') or any(not notice.get('read_at') for notice in linked_notices)
        items.append({'id': 'fact_change:' + change['id'], 'type': 'fact_change',
            'label': '등록 근거 변화' + (' · 고정 사례' if change.get('mode') == 'fixture_mock' else ''),
            'title': project.get('name', pid or '등록 사업 변화'), 'summary': change.get('summary', []),
            'article_ids': aids, 'project_ids': [pid] if pid else [], 'company_ids': sorted(cids),
            'created_at': change.get('created_at') or change.get('meaningful_at'), 'unread': unread,
            'source_update_ids': [], 'change_ids': [change['id']],
            'notification_ids': sorted(notice['id'] for notice in linked_notices),
            'mode': change.get('mode', 'unverified'), 'change_kind': change.get('kind'),
            'is_verified_fact_change': True})
    items.sort(key=lambda item: (str(item.get('created_at') or ''), item['id']), reverse=True)
    graph = {}
    for dimension, field in [('articles', 'article_ids'), ('projects', 'project_ids'), ('companies', 'company_ids')]:
        groups = {}
        for item in items:
            for entity_id in item[field]:
                groups.setdefault(entity_id, []).append(item)
        graph[dimension] = {entity_id: _metric(members) for entity_id, members in groups.items()}
    return {'items': items, 'counts': {'total': len(items), 'unread': sum(item['unread'] for item in items),
        'new_articles': sum(item['type'] == 'new_article' for item in items),
        'fact_changes': sum(item['type'] == 'fact_change' for item in items),
        'unread_new_articles': sum(item['type'] == 'new_article' and item['unread'] for item in items),
        'unread_fact_changes': sum(item['type'] == 'fact_change' and item['unread'] for item in items)},
        'graph': graph, 'orphan_notification_ids': sorted(orphan_notices),
        'read_on_get': False,
        'counting_note': '신규 기사와 등록 근거 변화는 별개 항목입니다. 같은 변화의 알림은 중복 집계하지 않으며 고정 사례는 현재 사실 검증을 뜻하지 않습니다.'}


def attention_annotation(attention, article_ids=(), project_ids=(), company_ids=(), item_index=None, restrict_project_ids=()):
    """Deduplicate the attention records represented by a graph entity or edge."""
    ids = set()
    for dimension, values in [('articles', article_ids), ('projects', project_ids), ('companies', company_ids)]:
        for entity_id in values:
            ids.update(attention.get('graph', {}).get(dimension, {}).get(entity_id, {}).get('attention_ids', []))
    index = item_index if item_index is not None else {item['id']: item for item in attention.get('items', [])}
    relevant = [index[item_id] for item_id in sorted(ids) if item_id in index]
    if restrict_project_ids:
        relevant = [item for item in relevant if set(item['project_ids']) & set(restrict_project_ids)]
    return _metric(relevant)


def apply_acknowledgement(datasets, ids, stamp, allowed_ids=None):
    """Acknowledge exact attention IDs inside the caller's one transaction.

    Resolve and validate the entire request before changing any original record.
    This does not mark other articles on the same company/project as read.
    """
    if not isinstance(ids, list) or len(ids) > 20000 or any(not isinstance(item, str) for item in ids):
        raise ValueError('확인할 알림 ID 목록이 필요합니다.')
    if not isinstance(stamp, str) or not stamp:
        raise ValueError('확인 시각이 필요합니다.')
    try:
        datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('유효한 확인 시각이 필요합니다.') from exc
    ids = list(dict.fromkeys(ids))
    allowed = set(allowed_ids) if allowed_ids is not None else None
    resolved = []
    for item_id in ids:
        if allowed is not None and item_id not in allowed:
            raise ValueError('현재 확인 범위를 벗어난 알림 ID입니다.')
        if item_id.startswith('new_article:'):
            aid = item_id[len('new_article:'):]
            sources = [item for item in datasets.get('news_updates', {}).values() if item.get('article_id') == aid]
            if aid not in datasets.get('articles', {}) or not sources:
                raise ValueError('존재하지 않는 기사 알림 ID입니다.')
            resolved.append(('new_article', aid, [item['id'] for item in sources]))
        elif item_id.startswith('fact_change:'):
            change_id = item_id[len('fact_change:'):]
            if change_id not in datasets.get('changes', {}):
                raise ValueError('존재하지 않는 변화 알림 ID입니다.')
            notices = [item['id'] for item in datasets.get('notifications', {}).values() if item.get('change_id') == change_id]
            resolved.append(('fact_change', change_id, notices))
        else:
            raise ValueError('지원하지 않는 알림 ID입니다.')
    update_ids, change_ids, notice_ids = [], [], []
    for kind, source_id, related in resolved:
        if kind == 'new_article':
            for update_id in related:
                record = datasets.setdefault('news_read_states', {}).setdefault(update_id, {'id': update_id, 'article_id': source_id})
                record.setdefault('read_at', stamp)
                if not record['read_at']:
                    record['read_at'] = stamp
                update_ids.append(update_id)
        else:
            record = datasets.setdefault('read_states', {}).setdefault(source_id, {'id': source_id})
            if not record.get('read_at'):
                record['read_at'] = stamp
            change_ids.append(source_id)
            for notice_id in related:
                if not datasets['notifications'][notice_id].get('read_at'):
                    datasets['notifications'][notice_id]['read_at'] = stamp
                notice_ids.append(notice_id)
    return {'acknowledged_ids': ids, 'acknowledged_count': len(ids),
            'news_update_ids': update_ids, 'change_ids': change_ids, 'notification_ids': notice_ids,
            'read_at': stamp}
