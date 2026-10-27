"""Bounded public news metadata collection; JSON checkpoints are the source of truth.

Never fetch publisher article bodies. Google search RSS is an unofficial public
feed, not a documented API; completed queries cannot guarantee complete coverage.
"""
from __future__ import annotations
import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit, parse_qsl
from .security import assert_safe_url
from .network import request_bytes, error_info

UTC = timezone.utc
GOOGLE = 'https://news.google.com/rss/search'
DIRECT_FEEDS = {'https://www.datacenterdynamics.com/en/rss/'}
MAX_BYTES = 3_000_000


def _dt(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(UTC)


def _iso(value):
    return value.astimezone(UTC).isoformat()


def _now():
    return datetime.now(UTC).isoformat()


def load_sources(root):
    return json.loads((Path(root) / 'config/news_sources.json').read_text(encoding='utf-8'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def validate_feed_url(url):
    assert_safe_url(url)
    parsed = urlsplit(url)
    if not (parsed.scheme == 'https' and parsed.port in (None, 443) and
            ((parsed.hostname == 'news.google.com' and parsed.path == '/rss/search') or
             url in DIRECT_FEEDS)):
        raise ValueError('수집 제공자 허용목록 밖의 요청입니다.')


def fetch_public_feed_bounded(url):
    from .feed_worker import fetch
    return fetch(url)


def fetch_public_feed(url):
    """Fixed endpoints only; DNS validated and connection pinned, no redirects.

    HTTPS SNI and certificate verification retain the original provider hostname.
    A private answer among DNS records rejects the entire request. The socket uses
    the checked address, so a second DNS resolution cannot rebind the request.
    """
    validate_feed_url(url)
    return request_bytes(url, allowed_hosts={'news.google.com', 'www.datacenterdynamics.com'},
                         headers={'User-Agent':'AIDC-ATLAS/0.4 (local public RSS metadata reader)',
                                  'Accept':'application/rss+xml, application/xml;q=0.9'}, max_bytes=MAX_BYTES)


def _plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()


def _domain(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')


def _same_domain(host, wanted):
    return host == wanted or host.endswith('.' + wanted)


def _canonical(url):
    assert_safe_url(url)
    parsed = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid','oc')]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, urlencode(pairs), ''))


def parse_feed(raw, source, window, collected_at=None):
    """Return metadata and diagnostics; future/out-of-window items are excluded."""
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_BYTES or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported feed XML')
    tree = ET.fromstring(raw)
    if tree.tag.rsplit('}', 1)[-1] not in ('rss', 'RDF'):
        raise ValueError('Expected RSS XML')
    items = tree.findall('.//item')
    diagnostics = {'returned':len(items),'outside_period':0,'invalid':0,'source_mismatch':0}
    result = []
    lower, upper = _dt(window['start']), _dt(window['end'])
    observed = _dt(collected_at or _now())
    for item in items:
        try:
            title = _plain(item.findtext('title'))
            link = (item.findtext('link') or '').strip()
            published = parsedate_to_datetime(item.findtext('pubDate') or '')
            if published.tzinfo is None:
                raise ValueError('Missing publication timezone')
            published = published.astimezone(UTC)
            if not lower <= published < upper or published > observed:
                diagnostics['outside_period'] += 1
                continue
            if not title or len(title) > 2000:
                raise ValueError('Missing title')
            # Bing redirects expose the original URL as metadata; no HTTP redirect
            # resolution is performed. Google opaque links remain clearly labeled.
            if _domain(link) == 'bing.com':
                link = parse_qs(urlsplit(link).query).get('url', [link])[0]
            assert_safe_url(link)
            host = _domain(link)
            source_node = item.find('source')
            publisher = _plain(source_node.text if source_node is not None else '')
            source_url = source_node.get('url', '') if source_node is not None else ''
            if not publisher:
                publisher = next((_plain(n.text) for n in item if n.tag.rsplit('}', 1)[-1].lower() == 'source'), source['name'])
            if host == 'news.google.com' and not source_url:
                diagnostics['source_mismatch'] += 1
                continue
            if source_url and not _same_domain(_domain(source_url), source['domain']):
                diagnostics['source_mismatch'] += 1
                continue
            if host != 'news.google.com' and not _same_domain(host, source['domain']):
                diagnostics['source_mismatch'] += 1
                continue
            canonical = _canonical(link)
            if title.endswith(' - ' + publisher):
                title = title[:-(len(publisher) + 3)]
            # Store only a short feed excerpt, never the entire description/body.
            excerpt = ' '.join(_plain(item.findtext('description')).split()[:25])[:240]
            stamp = collected_at or _now()
            fingerprint = _hash(source['source_id'] + '|' + re.sub(r'\W+', '', title).casefold() + '|' + published.date().isoformat())
            result.append({'id':'article-' + _hash(canonical)[:24], 'url':link,'canonical_url':canonical,
                'title':title,'publisher':publisher or source['name'],'published_at':_iso(published),'collected_at':stamp,
                'first_seen_at':stamp,'summary':title,'feed_excerpt':excerpt,'source_id':source['source_id'],
                'source_domain':source['domain'],'language':source['language'],'mode':'live_metadata',
                'access_status':'feed_metadata_only','summary_method':'metadata_digest',
                'discovered_via':'google_news_search_rss' if host == 'news.google.com' else 'public_rss',
                'original_url_status':'aggregator_redirect_unresolved' if host == 'news.google.com' else 'publisher_url_from_feed',
                'project_ids':[],'company_ids':[],'candidate_project_ids':[],'business_categories':[],
                'news_fingerprint':fingerprint,'syndication_cluster':_hash(re.sub(r'\W+', '', title).casefold()),
                'classification':'metadata_only','event_date':None})
        except (ValueError, TypeError, OverflowError):
            diagnostics['invalid'] += 1
    return result, diagnostics


def _query(source, filters, window):
    # Every language uses the same explicit facility topic. Generic AI/chips or
    # publisher location cannot substitute for a data-center mention; provider
    # search is advisory and the shared local classifier remains authoritative.
    base = '("데이터센터" OR "데이터 센터" OR "data center" OR "data centre" OR datacenter OR AIDC)'
    country_names = {'KR':'Korea','US':'United States','AE':'United Arab Emirates','JP':'Japan','CN':'China','SG':'Singapore','MY':'Malaysia','IN':'India','ID':'Indonesia','AU':'Australia','GB':'United Kingdom','DE':'Germany','FR':'France','SA':'Saudi Arabia',
        'CA':'Canada','BR':'Brazil','MX':'Mexico','CL':'Chile','NL':'Netherlands','IE':'Ireland','ES':'Spain','IT':'Italy',
        'SE':'Sweden','NO':'Norway','FI':'Finland','DK':'Denmark','PL':'Poland','BE':'Belgium','CH':'Switzerland','AT':'Austria',
        'VN':'Vietnam','TH':'Thailand','TW':'Taiwan','PH':'Philippines','NZ':'New Zealand','ZA':'South Africa','IL':'Israel','QA':'Qatar'}
    scope_terms = {'kr-dc':'(한국 OR Korea)', 'kr-ai':'(한국 OR Korea) (AI OR 인공지능 OR AIDC)', 'global-ai':'(AI OR artificial intelligence OR AIDC)'}
    base += ' ' + scope_terms.get(filters.get('scope'), '')
    extra = ' '.join([filters.get('provider_query', filters.get('q')) or '',country_names.get(filters.get('country'),filters.get('country') or ''),filters.get('city') or '']).strip()
    # Provider date operators have day granularity. Expand outward then apply
    # the exact UTC bounds locally; otherwise the lower boundary loses a day.
    lower = (_dt(window['start']) - timedelta(days=1)).date().isoformat()
    upper = (_dt(window['end']) + timedelta(days=1)).date().isoformat()
    query = f'{base} {extra} site:{source["domain"]} after:{lower} before:{upper}'
    locale = {'hl':'ko','gl':'KR','ceid':'KR:ko'} if source['language']=='ko' else {'hl':'en-US','gl':'US','ceid':'US:en'}
    return GOOGLE + '?' + urlencode({'q':query, **locale})


def _window(source_id, start, end, provider='google_news_search_rss', depth=0):
    value = {'source_id':source_id,'start':_iso(start),'end':_iso(end),'provider':provider,'depth':depth,'attempts':0}
    value['id'] = 'window-' + _hash(json.dumps(value, sort_keys=True))[:24]
    return value


def collect_news(repo, root, request, job_id=None, fetcher=None, progress=None):
    from .news import normalize_filters, enrich_articles, classify_article
    fetcher = fetcher or fetch_public_feed_bounded
    config = load_sources(root)
    request = dict(request)
    request.setdefault('period', config['defaults'].get('period', '3y'))
    filters = normalize_filters(request)
    sources = [s for s in config['sources'] if s.get('enabled')]
    requested = filters.get('source_ids') or []
    if requested:
        unknown = set(requested) - {s['source_id'] for s in sources}
        if unknown:
            raise ValueError('알 수 없거나 비활성 소스입니다.')
        sources = [s for s in sources if s['source_id'] in requested]
    else:
        sources = [s for s in sources if s.get('default_selected')]
    if not sources:
        raise ValueError('선택한 범위에 연결 소스가 없습니다.')
    # Round-robin domestic/international media and official channels, so a
    # bounded first batch does not silently spend its budget on one geography.
    groups = [[s for s in sources if (s['region']=='KR')==domestic and (s['kind']=='media')==media]
              for domestic,media in [(True,True),(False,True),(True,False),(False,False)]]
    sources = [group[index] for index in range(max(map(len,groups))) for group in groups if index<len(group)]
    # Avoid guessing an unbounded archive beginning. "all" explicitly queries
    # the supported historical collection horizon and records that boundary.
    lower = _dt(filters['start']) if filters.get('start') else _dt(filters['end']) - timedelta(days=1096)
    upper = _dt(filters['end'])
    signature_fields = {k:filters.get(k) for k in ('period','q','scope','company_id','project_id','source_ids','country','city')}
    signature = _hash(json.dumps(signature_fields, sort_keys=True, ensure_ascii=False))
    job_id = job_id or 'news-job-' + uuid.uuid4().hex
    initial_datasets = repo.snapshot()['datasets']
    old = initial_datasets.get('news_jobs', {}).get(job_id, {})
    projects = initial_datasets.get('projects', {})
    if old.get('signature') and old['signature'] != signature:
        raise ValueError('같은 기간·검색·소스·지역 조건만 이어서 수집할 수 있습니다.')
    if old.get('signature'):
        job = dict(old)
        filters = job['filters']  # Resume at the original immutable as-of bounds.
        pending = list(job.get('pending_windows', []))
        failed = list(job.get('failed_windows', []))
        pending = [w for w in failed if w.get('attempts',0) < 3] + pending
        job['failed_windows'] = [w for w in failed if w.get('attempts',0) >= 3]
    else:
        pending = []
        cursor = upper
        # Window-major order obtains latest metadata across all selected media
        # before consuming the next historical slice.
        while cursor > lower:
            start = max(lower, cursor - timedelta(days=31))
            for source in sources:
                if cursor == upper and source.get('direct_feed') and not any(filters.get(k) for k in ('q','country','city')) and filters['scope']=='all':
                    pending.append(_window(source['source_id'], start, cursor, 'direct_rss'))
                pending.append(_window(source['source_id'], start, cursor))
            cursor = start
        job = {**old,'id':job_id,'request':dict(request),'filters':filters,'signature':signature,
               'created_at':old.get('created_at',_now()),'completed_windows':0,'total_windows':len(pending),
               'request_count':0,'article_count':0,'new_articles':0,'duplicate_count':0,'failed_windows':[],
               'provider_caps':0,'rejected_items':0,'coverage_start':_iso(lower),'coverage_end':_iso(upper)}
    # Cumulative diagnostics survive resumed batches and pre-v0.3 checkpoints.
    for key in ('returned_items','parsed_items','relevant_items','uncertain_items','out_of_scope_items'):
        job.setdefault(key, 0)
    source_map = {s['source_id']:s for s in config['sources']}
    job.pop('error_code',None)
    job.pop('cancel_requested', None)
    job.update(status='running', pending_windows=pending, updated_at=_now(), complete_coverage=False,
               limitations=['공개 검색 RSS는 비공식 제공자입니다. 모든 기사와 과거 확보율을 보장하지 않습니다.',
                            '본문 미확인: 제목·매체·시각·최대 25단어 설명만 수집하며 수치·참여역할을 확정하지 않습니다.',
                            '공식 최신 RSS는 보완자료이며 요청한 과거 전체를 포괄하지 않습니다.',
                            '기본 3년은 요청 범위입니다. 남은 조회 구간·실패·제공자 상한이 있으면 전체 수집 완료가 아닙니다.',
                            '데이터센터 관련성은 제목·공개 설명으로 판별합니다. 무관 기사는 제외하고 판별 불가는 별도 미확인으로 보관합니다.'])
    max_requests = max(1, min(40, int(request.get('max_requests',config['defaults']['max_requests']))))
    max_articles = max(1, min(1000, int(request.get('max_articles',config['defaults']['max_articles']))))
    job['batch_limits'] = {'max_requests':max_requests,'max_articles':max_articles,'max_items_per_response':100,
                           'article_limit_semantics':'response_atomic; may exceed article budget by up to 99'}

    def save(articles=None, coverage=None):
        def mutate(ds):
            new_ids = []
            catalog = ds.setdefault('articles', {})
            by_fingerprint = {a.get('news_fingerprint') for a in catalog.values() if a.get('news_fingerprint')}
            canonicals = {a.get('canonical_url',a.get('url')) for a in catalog.values()}
            for article in articles or []:
                if article['id'] in catalog or article['news_fingerprint'] in by_fingerprint or article['canonical_url'] in canonicals:
                    job['duplicate_count'] += 1
                    continue
                catalog[article['id']] = article
                new_ids.append(article['id'])
                by_fingerprint.add(article['news_fingerprint'])
                canonicals.add(article['canonical_url'])
            if new_ids:
                enrich_articles(ds, new_ids)
                from .project_discovery import enrich_discovery
                enrich_discovery(ds, new_ids)
            job['new_articles'] += len(new_ids)
            job['pending_windows'] = list(pending)
            job['updated_at'] = _now()
            job['progress_percent'] = round(100 * job['completed_windows'] / max(job['total_windows'],1), 1)
            existing_job = ds.setdefault('news_jobs', {}).get(job_id, {})
            if existing_job.get('cancel_requested'):
                job['cancel_requested'] = True
            ds['news_jobs'][job_id] = dict(job)
            if coverage:
                ds.setdefault('news_coverage', {})[coverage['id']] = coverage
        repo.transact(mutate)

    if old.get('signature'):
        repo.transact(lambda ds: ds.setdefault('news_jobs',{}).get(job_id,{}).pop('cancel_requested',None))
    save()
    calls, received, consecutive_errors = 0, 0, 0
    network_blocked=False
    def emit(stage,source=None):
        if progress:progress({'job_id':job_id,'stage':stage,'updated_at':_now(),
            'source_name':source.get('name') if source else None,
            **{k:job.get(k,0) for k in ('request_count','new_articles','completed_windows','total_windows')},
            'request_deadline_seconds':20})
    while pending and calls < max_requests and received < max_articles:
        if repo.snapshot()['datasets'].get('news_jobs', {}).get(job_id, {}).get('cancel_requested'):
            job['status'] = 'cancelled'
            break
        window = pending[0]
        source = source_map[window['source_id']]
        provider_filters = {**filters, 'provider_query':request.get('provider_query',filters.get('q',''))}
        url = source['direct_feed'] if window['provider']=='direct_rss' else _query(source, provider_filters, window)
        calls += 1
        job['request_count'] += 1
        window = {**window,'attempts':window.get('attempts',0)+1}
        coverage = {**window,'id':job_id + '-' + window['id'],'job_id':job_id,'checked_at':_now(),
                    'complete_coverage':False,'query_url':url,'source_name':source['name'],
                    'source_domain':source['domain'],'language':source['language']}
        try:
            emit('requesting',source)
            raw = fetcher(url)
            emit('parsing',source)
            articles, diagnostics = parse_feed(raw, source, window, _now())
            diagnostics.update(parsed=len(articles), relevant=0, uncertain=0, out_of_scope=0)
            accepted = []
            for article in articles:
                article.update(classify_article(article, projects))
                relevance = article['domain_relevance']['status']
                if relevance == 'out_of_scope':
                    diagnostics['out_of_scope'] += 1
                    continue
                diagnostics['relevant' if relevance == 'relevant' else 'uncertain'] += 1
                accepted.append(article)
            # The response budget counts all valid parsed metadata, including
            # out-of-scope results, so poor provider precision cannot cause an
            # unbounded download while waiting for relevant articles.
            received += len(articles)
            job['returned_items'] += diagnostics['returned']
            job['parsed_items'] += diagnostics['parsed']
            job['relevant_items'] += diagnostics['relevant']
            job['uncertain_items'] += diagnostics['uncertain']
            job['out_of_scope_items'] += diagnostics['out_of_scope']
            job['article_count'] += len(accepted)
            job['rejected_items'] += diagnostics['invalid'] + diagnostics['source_mismatch'] + diagnostics['outside_period'] + diagnostics['out_of_scope']
            pending.pop(0)
            capped = window['provider']!='direct_rss' and diagnostics['returned'] >= 100
            if capped:
                job['provider_caps'] += 1
                start, end = _dt(window['start']), _dt(window['end'])
                if end-start > timedelta(days=1):
                    middle = start+(end-start)/2
                    # Keep other latest-source windows ahead of deeper retries.
                    pending.extend([_window(source['source_id'],middle,end,depth=window['depth']+1),
                                    _window(source['source_id'],start,middle,depth=window['depth']+1)])
                    job['total_windows'] += 2
                    status = 'provider_cap_split'
                else:
                    status = 'provider_cap_unresolved'
            else:
                status = 'supplemental_latest_feed' if window['provider']=='direct_rss' else 'queried'
            job['completed_windows'] += 1
            coverage.update(status=status, **diagnostics, accepted=len(accepted), provider_cap=capped)
            articles = accepted
            consecutive_errors=0
        except (OSError, ValueError, ET.ParseError, http.client.HTTPException) as error:
            detail = error_info(error) if not isinstance(error, (ValueError, ET.ParseError)) else {
                'code': 'feed_validation', 'message': '공개 RSS 형식·제공사 허용목록 검증 실패'}
            pending.pop(0)
            job['failed_windows'].append({**window,'error':type(error).__name__,'error_code':detail['code']})
            coverage.update(status='failed',error=type(error).__name__,error_code=detail['code'],error_message=detail['message'],accepted=0)
            if detail.get('transport'):
                coverage['error_transport']=detail['transport']
                job['error_transport']=detail['transport']
            else:
                job.pop('error_transport',None)
            save(coverage=coverage)
            consecutive_errors+=1
            job['error_code']=detail['code']
            emit('source_error',source)
            if consecutive_errors>=3 and detail['code'] in {'dns','timeout','feed_deadline','feed_worker','network','tls','tls_certificate','proxy_configuration','ca_bundle_invalid','http_403','http_407','http_429','feed_validation'}:
                network_blocked=True
                break
            continue
        emit('saving',source)
        save(articles, coverage)
    # A stop may arrive while the last request is in flight. Keep that action
    # visible even when the response exhausted the queue in the same instant.
    if job.get('cancel_requested'):
        job['status'] = 'cancelled'
    if job['status'] == 'cancelled':
        pass
    elif network_blocked:
        job['status']='partial' if job['completed_windows'] else 'failed'
    elif pending:
        job['status'] = 'partial'
    elif job['failed_windows']:
        job['status'] = 'partial' if job['completed_windows'] else 'failed'
    else:
        job['status'] = 'completed'
    job['can_resume'] = bool(pending or any(w.get('attempts',0)<3 for w in job['failed_windows']))
    job['batch_request_count'] = calls
    job['batch_parsed_items'] = received
    job['remaining_windows'] = len(pending)
    job['retryable_failed_windows'] = sum(w.get('attempts', 0) < 3 for w in job['failed_windows'])
    if job['status'] == 'cancelled':
        job['stop_reason'] = 'user_cancelled'
    elif network_blocked:
        job['stop_reason']='network_blocked'
        job['message']='연속 3회 수집 연결/응답 검증 실패로 일시 중지했습니다. 원본과 남은 구간을 보존했습니다. 네트워크 진단 후 재개하세요.'
    elif pending:
        job['stop_reason'] = 'article_limit' if received >= max_articles else 'request_limit'
    elif job['failed_windows']:
        job['stop_reason'] = 'source_errors'
    else:
        job['stop_reason'] = 'queue_exhausted'
    job['finished_at'] = _now()
    save()
    emit(job['status'])
    return job
