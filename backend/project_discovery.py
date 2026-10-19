"""Source-span project/company observations, never automatic project facts.

Each article is analysed independently. Exact displayed names may be presented
together, but a shared city/company is never sufficient to merge project identity.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy

from .news import CITIES, ALIASES
from .company_profiles import DESCRIPTORS, descriptor_observations, build_company_profile

VERSION = '0.4.2-company-links'
DC_NAME = re.compile(r'(?<![A-Za-z0-9])(?:AI\s*)?데이터\s*센터|(?<![A-Za-z0-9])AIDC(?![A-Za-z0-9])|(?:AI\s+)?data\s*cent(?:er|re)', re.I)
SUBJECT_STOP = re.compile(r'지사|회장|대표|장관|대통령|기자|의원|시장|도지사|위원회|협회|연합회|정부|산업부|국토부|^충남도$|^경남도$|^전남도$|^강원도$|^경북도$|[시군청]$|데이터\s*센터|^AI$|^AIDC$', re.I)
CORPORATE_END = re.compile(r'건설|전자|에너지|전력|전선|통신|증권|자산운용|투자신탁|캐피탈(?:파트너스)?|파트너스|클라우드|코리아|텔레콤|브로드밴드|일렉트릭|테크놀로지|테크|테크놀로지스|시스템(?:즈)?|솔루션(?:즈)?|인프라|캐리어|씨티에스|그룹|공업|엔지니어링|물산|은행|중공업|기업|개발|제철|철강|케미칼|플랜트|리얼티|홀딩스|Inc\.?|Ltd\.?|Corp\.?|GmbH|PLC|LLC|Cloud|Technologies|Capital|Partners|Construction|Energy|Electric|Group|Networks|Realty|Data\s*Cent(?:er|re)s?$', re.I)
SHORT_CORPORATE_NAMES = {'디딤', '동양', '코람코', '틸론', '효성'}
CORPORATE_END = re.compile('(?:' + CORPORATE_END.pattern + ')$', re.I)
STAGES = [('cancelled', r'무산|취소|철회'), ('funding', r'자금\s*조달|금융|출자|펀드|PEF'),
          ('completed', r'준공|개소|오픈'), ('construction', r'착공|기공|공사\s*착수'),
          ('planning', r'개발|건립|건설|추진|유치|투자|협의|착수'), ('operating', r'운영|가동')]
ROLE_SIGNALS = {'client': r'발주(?:처|사|자|한|했다|한다|계약)',
    'developer': r'시행사|개발사|개발(?:한다|했다|사업|추진|을\s*추진|에\s*나서)',
    'tenant': r'테넌트|임차(?:사|인|계약|한다|했다)|입주(?:사|한다|했다|계약)',
    'operator': r'운영사|운영사업자|운영(?:한다|했다|계약|을\s*담당|할\s*예정)',
    'contractor': r'시공(?:사|한다|했다|계약|을\s*담당|권|\s*수주)|건설공사\s*수주',
    'designer': r'설계(?:사|한다|했다|계약|를\s*담당|\s*수주)|건축사사무소',
    'equipment_supplier': r'(?:전력|냉각|서버|네트워크|GPU|전기)?\s*(?:장비|기자재|설비)\s*(?:공급|납품)|(?:서버|GPU|UPS|변압기|수배전반)\s*(?:공급|납품)|장비사',
    'financier': r'PF\s*(?:주선|주관|대출)|(?:금융|대출|자금조달)\s*(?:주선|주관)|프로젝트\s*파이낸싱\s*(?:주선|주관)'}


def _observed_links(article, project_evidence, observations):
    """Same-title association plus conservative grammatical role signals.

    Signals are proposals; neither co-occurrence nor these rules creates a
    registered relationship. Multiple subjects/sites remain unknown unless an
    attached company descriptor and one project are explicit.
    """
    title = article.get('title') or ''
    links = []
    unique = {item.get('company_id') or item['name'].casefold(): item for item in observations}
    project_count = len(list(DC_NAME.finditer(title)))
    for observation in unique.values():
        cid = observation.get('company_id')
        if not cid:
            continue
        company_span = observation['evidence']
        if company_span.get('field') != 'title':
            continue
        role_evidence = []
        # One headline company and one project makes subject/action attribution
        # reviewable. Generic "착공/투자" alone never means builder/developer.
        if project_count == 1:
            if not re.search(r'[…;；.!?\n]|반면|그러나|부인|아니다|아닌|참여하지|철회|무산|취소', title):
                # A descriptor attached to this company is attributable even
                # when several other company names also appear in the title.
                for item in observation.get('profile_evidence', []):
                    if item['basis'] == 'explicit_company_noun_descriptor':
                        role_evidence.append((item['category'], deepcopy(item['evidence'])))
            if len(unique) == 1 and not re.search(r'[…;；.!?\n]|반면|그러나|부인|아니다|아닌|참여하지|철회|무산|취소', title):
                for role, pattern in ROLE_SIGNALS.items():
                    for found in re.finditer(pattern, title, re.I):
                        # Comma after a headline subject is allowed; separate
                        # semicolon/ellipsis sentences above are not.
                        role_evidence.append((role, _span(article, 'title', title, found.start(), found.end())))
        role_evidence = list({role: (role, signal) for role, signal in role_evidence}.values())
        roles = role_evidence or [('unknown', None)]
        for role, signal in roles:
            spans = [deepcopy(company_span), deepcopy(project_evidence)]
            if signal:
                spans.append(signal)
            links.append({'company_id': cid, 'company_name': observation['name'], 'role': role,
                'label': ('기사 역할 표현 · 검토 필요' if signal else '같은 기사 기업 관측 · 역할 미확인'),
                'basis': 'metadata_subject_role_signal' if signal else 'same_article_name_observations',
                'status': 'role_observation' if signal else 'cooccurrence_observation',
                'article_ids': [article['id']], 'evidence': spans,
                'direct_contract_confirmed': False, 'is_confirmed_participation': False})
    return links


def _add_activity_profiles(article, observations):
    """Activity proposes business nature; it never sets an actual project role."""
    title = article.get('title') or ''
    targets = list(DC_NAME.finditer(title))
    if len(targets) != 1:
        return
    target = targets[0]
    links = _observed_links(article, _span(article, 'title', title, target.start(), target.end()), observations)
    for link in links:
        if link['role'] == 'unknown':
            continue
        for observation in observations:
            if observation.get('company_id') != link['company_id']:
                continue
            evidence = observation.setdefault('profile_evidence', [])
            if any(item['category'] == link['role'] for item in evidence):
                continue
            evidence.append({'category': link['role'], 'basis': 'metadata_activity_type_proposal',
                'status': 'classification_proposal', 'article_ids': [article['id']],
                'evidence': deepcopy(link['evidence'][-1])})


def _id(prefix, value):
    return prefix + '-' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]


def _stamp(article):
    value = repr((article.get('title'), article.get('feed_excerpt'), article.get('url'),
                  article.get('publisher'), article.get('published_at')))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _span(article, field, text, start, end):
    return {'article_id': article['id'], 'field': field, 'text': text[start:end], 'start': start,
            'end': end, 'url': article.get('url'), 'published_at': article.get('published_at'),
            'basis': 'explicit_public_metadata_span'}


def _company_subject(name):
    """Conservative candidate-name grammar; unsupported subjects stay unparsed."""
    if SUBJECT_STOP.search(name) or re.search(r'\s(?:측|정책|업계|관계자|전문가|부?사장|의견|교수)|[!?…$]|[은는이가을를]\s', name):
        return False
    if re.fullmatch(r'(?:AI\s*)?data\s*cent(?:er|re)s?|Manager|Director|President|Chairman|Zero|conditioning|K배터리', name, re.I):
        return False
    if re.search(r'\s(?:tops?\s*out|finances?|expands?|plans?|builds?|launches?|announces?|opens?|says|invests?)\b', name, re.I):
        return False
    if re.search(r'\s', name) and re.search(r'액체|솔루션|수요|테마|클러스터|포럼|사업부|폭증|시대', name):
        return False
    if re.search(r'앞둔|나선|기다릴|없다|메가프로젝트|컨콜|[“”‘’\'\"]', name):
        return False
    if name in SHORT_CORPORATE_NAMES or CORPORATE_END.search(name):
        return True
    # Single brand tokens with Latin letters are common, but sentences/people
    # appended to a brand must not become corporate entities (e.g. SKT 정재헌).
    return bool(re.fullmatch(r'[A-Za-z0-9가-힣&.+_-]{2,45}', name) and re.search(r'[A-Z]', name)
                and not re.fullmatch(r'(?:AI|DC|AIDC|GPU|IT|HPC)', name, re.I))


def _registry_candidate(name):
    # Ambiguous single capitalised words may be people or places. Keep them in
    # the source ledger for resolution instead of making a selectable company.
    return bool(name in SHORT_CORPORATE_NAMES or CORPORATE_END.search(name)
                or re.search(r'[A-Z].*[A-Z]', name)
                or (re.search(r'[가-힣]', name) and re.search(r'[A-Z]', name)))


def analyse_article(article, companies=None):
    """Extract conservative metadata candidates; all returned strings cite spans."""
    title = article.get('title') or ''
    title = title if isinstance(title, str) else ''
    companies = companies or {}
    observations = []
    # A grammatical headline subject is a name observation, not a verified legal
    # entity or participant. Reject public agencies, people and generic subjects.
    cleaned = re.sub(r'^\s*\[[^\]]+\]\s*', '', title)
    offset = title.find(cleaned)
    subject = re.match(r'["“‘\']?([^,，:："“]{2,70})(?:[,，]|\s+["“])', cleaned)
    if subject:
        raw = subject.group(1).strip(' "“‘\'')
        descriptor_prefix = re.compile(r'^(?:(?:AI\s*)?데이터\s*센터\s*)?(?:' + '|'.join(DESCRIPTORS.values()) + r')\s+', re.I)
        has_descriptor_prefix = bool(descriptor_prefix.match(raw))
        raw = descriptor_prefix.sub('', raw).strip()
        quote_person = ',' not in subject.group() and '，' not in subject.group() and bool(re.fullmatch(r'[가-힣]{2,4}', raw))
        if not quote_person and len(raw) <= 55 and not SUBJECT_STOP.search(raw) and not re.search(r'\s(?:AI|투자|관련|성장|대한|위한)|[!?…]', raw):
            for name in re.split(r'\s*[·ㆍ]\s*|(?<=[가-힣A-Za-z0-9])-(?=[가-힣A-Za-z0-9])', raw):
                name = name.strip()
                if len(name) < 2 or len(name) > 45 or (not _company_subject(name) and not
                        (has_descriptor_prefix and re.fullmatch(r'[가-힣A-Za-z0-9&.+_-]{2,45}', name))):
                    continue
                start = title.find(name, max(offset, 0))
                if start >= 0:
                    span = _span(article, 'title', title, start, start + len(name))
                    observations.append({'name': name, 'status': 'name_observation', 'role': 'unknown',
                        'evidence': span, 'profile_evidence': descriptor_observations(article, name, span)})
    # Recognised registry names also remain name observations. This avoids losing
    # familiar firms when the headline has no comma-delimited subject.
    for cid in article.get('company_ids', []):
        company = companies.get(cid)
        if not company:
            continue
        for name in [company.get('name', '')] + list(company.get('aliases') or []):
            if not name or len(name) < 2:
                continue
            found = re.search(r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', title, re.I)
            if found:
                if not any(item['name'].casefold() == name.casefold() for item in observations):
                    observations.append({'name': company.get('name', name), 'company_id': company['id'],
                        'status': 'name_observation', 'role': 'unknown',
                        'evidence': _span(article, 'title', title, found.start(), found.end()),
                        'profile_evidence': descriptor_observations(article, name,
                            _span(article, 'title', title, found.start(), found.end()))})
                else:
                    for observed in observations:
                        if observed['name'].casefold() == name.casefold():
                            observed['company_id'] = company['id']
                break

    _add_activity_profiles(article, observations)

    mentions = []
    # Only explicit continuous title names qualify. General market/supply-chain
    # articles without a nearby named location/site remain analysis pending.
    for match in DC_NAME.finditer(title):
        before = title[max(0, match.start() - 65):match.start()]
        city_hits = []
        for city, (country, pattern) in CITIES.items():
            if country != 'KR':
                continue
            for place in re.finditer(pattern, before, re.I):
                city_hits.append((place.start(), city, place))
        city_hits.sort(key=lambda item: item[0], reverse=True)
        if not city_hits:
            continue
        _, city, place = city_hits[0]
        suffix = before[place.end():]
        # A manufacturing verb, a financial discussion or a different clause
        # between the place and DC cannot become a project name.
        if len(suffix) > 40 or re.search(r'[,，…;；.!?\n]|생산라인|공장|양산|시장|목표가|정조준|칩|전망|전략|앞세워|앞두고|넘어|확보로|피지컬|(?:에너지|신세계)와|^시·', suffix):
            continue
        start = max(0, match.start() - 65) + place.start()
        end = match.end()
        raw = title[start:end]
        if city == '양산' and not re.match(r'양산(?:시|에|\s)', raw):
            continue
        # Remove only an initial locative particle; retain every other original
        # token in the candidate name and record the untouched evidence span.
        name = re.sub(r'^' + re.escape(city) + r'(?:시)?에\s*', city + ' ', raw)
        name = re.sub(r'\s+', ' ', name).strip(' "\'“”‘’')
        scope = article.get('scope_classification', {}).get('primary_scope') or article.get('scope') or 'unresolved'
        if scope not in ('kr-ai', 'kr-dc', 'global-ai'):
            scope = 'unresolved'
        evidence = _span(article, 'title', title, start, end)
        stages = []
        for stage, pattern in STAGES:
            for signal in re.finditer(pattern, title, re.I):
                stages.append({'stage': stage, 'status': 'metadata_signal',
                    'evidence': _span(article, 'title', title, signal.start(), signal.end())})
        capacities = []
        for signal in re.finditer(r'(\d+(?:[.,]\d+)?)\s*(GW|MW|kW|MVA|㎿|㎾)', title, re.I):
            capacities.append({'raw': signal.group(), 'value': float(signal.group(1).replace(',', '')),
                'unit': {'㎿': 'MW', '㎾': 'kW'}.get(signal.group(2), signal.group(2)),
                'metric': 'unspecified', 'basis': 'metadata_observation', 'status': 'unverified',
                'evidence': _span(article, 'title', title, signal.start(), signal.end())})
        mentions.append({'id': _id('project-mention', article['id'] + ':' + str(start) + ':' + str(end)),
            'article_id': article['id'], 'article_ids': [article['id']], 'name': name, 'scope': scope,
            'city': city, 'cities': [city], 'countries': ['KR'], 'status': 'article_project_candidate',
            'identity_status': 'not_verified', 'is_candidate': True, 'is_confirmed_project': False, 'evidence': evidence,
            'company_observations': deepcopy(observations), 'company_links': _observed_links(article, evidence, observations),
            'stage_signals': stages, 'capacity_signals': capacities})
    return {'id': article['id'], 'article_id': article['id'], 'version': VERSION, 'source_hash': _stamp(article),
        'mentions': mentions, 'company_observations': observations,
        'disposition': 'named_project_candidate' if mentions else 'no_explicit_named_project_span',
        'analysis_basis': 'deterministic_public_title_rules', 'full_text_verified': False}


def enrich_discovery(datasets, article_ids):
    """Idempotent durable JSON projection, called only within writer transactions."""
    records = datasets.setdefault('project_mentions', {})
    company_records = datasets.setdefault('company_mentions', {})
    companies = datasets.setdefault('companies', {})
    def normal_name(name):
        return re.sub(r'\s+', ' ', name).strip().casefold()
    known_names = {normal_name(name): company['id'] for company in companies.values()
                   for name in [company.get('name', '')] + list(company.get('aliases') or []) if name}
    for canonical, aliases in ALIASES:
        cid = next((known_names[normal_name(name)] for name in [canonical] + aliases
                    if normal_name(name) in known_names), None)
        if cid:
            for name in [canonical] + aliases:
                known_names[normal_name(name)] = cid
    for aid in dict.fromkeys(article_ids):
        article = datasets.get('articles', {}).get(aid)
        if not article:
            continue
        prior = records.get(aid)
        if prior and prior.get('version') == VERSION and prior.get('source_hash') == _stamp(article):
            continue
        record = analyse_article(article, companies)
        if article.get('domain_relevance', {}).get('status') == 'relevant':
            for observation in record['company_observations']:
                key = normal_name(observation['name'])
                cid = observation.get('company_id') or known_names.get(key)
                if not cid:
                    if not _registry_candidate(observation['name']) and not observation.get('profile_evidence'):
                        continue
                    cid = _id('co-name-observed', key)
                    companies.setdefault(cid, {'id': cid, 'name': observation['name'], 'aliases': [],
                        'project_ids': [], 'classification': 'observed_name_only', 'role': '미확인',
                        'name_evidence': [deepcopy(observation['evidence'])],
                        'summary': '공개 제목의 상호 형태 이름 관측입니다. 법인 실체·동일 기업·사업 참여·역할은 미확인입니다.'})
                    known_names[key] = cid
                observation['company_id'] = cid
                article['company_ids'] = sorted(set(article.get('company_ids', [])) | {cid})
            _add_activity_profiles(article, record['company_observations'])
            for mention in record['mentions']:
                mention['company_observations'] = deepcopy(record['company_observations'])
                mention['company_ids'] = sorted({item['company_id'] for item in record['company_observations'] if item.get('company_id')})
                mention['company_links'] = _observed_links(article, mention['evidence'], record['company_observations'])
        # Registry additions are name observations only. No project membership,
        # relationship or verified role is created from a headline subject.
        records[aid] = record
        if record['company_observations'] or aid in company_records:
            company_records[aid] = {'id': aid, 'article_id': aid, 'version': VERSION,
                'source_hash': record['source_hash'], 'observations': deepcopy(record['company_observations']),
                'classification': 'unverified_name_observations'}
    # Rebuild nature observations independently of project-role records. This
    # also removes stale descriptor conclusions when an article was corrected.
    by_company = {}
    for item in company_records.values():
        for observation in item.get('observations', []):
            if observation.get('company_id') in companies:
                by_company.setdefault(observation['company_id'], []).append(observation)
    for cid, company in companies.items():
        company.update(build_company_profile(company, by_company.get(cid, [])))


def build_project_discovery(snapshot, workspace):
    """Read-only selected-article view; never persists fallback analysis on GET."""
    ds = snapshot.get('datasets', snapshot)
    stored = ds.get('project_mentions', {})
    mentions, company_observations, pending, persisted, registered_links = [], [], [], 0, []
    articles = workspace.get('articles', [])
    for article in articles:
        record = stored.get(article['id'])
        if record and record.get('version') == VERSION and record.get('source_hash') == _stamp(article):
            persisted += 1
        else:
            record = analyse_article(article, ds.get('companies', {}))
        # Scope is a current classification; raw source mentions retain their
        # original recorded provenance and need not be rewritten during GET.
        for item in record['mentions']:
            mention = deepcopy(item)
            mention['scope'] = article.get('scope_classification', {}).get('primary_scope') or 'unresolved'
            mentions.append(mention)
        company_observations.extend(deepcopy(record.get('company_observations', [])))
        # Verified article->registered project association is preserved, while
        # the company link remains a separate observation unless a stored
        # explicit relationship supplies its role.
        for pid in article.get('project_ids', []):
            if pid not in ds.get('projects', {}):
                continue
            base_span = record['mentions'][0]['evidence'] if len(record['mentions']) == 1 and len(article.get('project_ids', [])) == 1 else None
            if base_span:
                links = _observed_links(article, base_span, record.get('company_observations', []))
            else:
                links = []
                for observed in record.get('company_observations', []):
                    if observed.get('company_id'):
                        links.append({'company_id': observed['company_id'], 'company_name': observed['name'],
                            'role': 'unknown', 'label': '등록 사업 기사 내 기업 관측 · 참여 미확인',
                            'basis': 'registered_article_company_observation', 'status': 'cooccurrence_observation',
                            'article_ids': [article['id']], 'evidence': [deepcopy(observed['evidence'])],
                            'direct_contract_confirmed': False, 'is_confirmed_participation': False})
            for item in links:
                item.update(project_id=pid, project_is_candidate=False,
                    id=_id('project-company-observation', pid + ':' + article['id'] + ':' + item['company_id'] + ':' + item['role']))
                registered_links.append(item)
        if not record['mentions']:
            pending.append({'article_id': article['id'], 'reason': record['disposition']})
    groups = {}
    for mention in mentions:
        # Exact normalised full names only. Even these are explicitly name
        # observation groups, not reconciled project/site identities.
        key = re.sub(r'\s+', ' ', mention['name']).strip().casefold()
        group = groups.setdefault(key, {'id': _id('project-name-group', key), 'name': mention['name'],
            'scope': mention['scope'], 'article_ids': [], 'mention_ids': [], 'cities': [], 'countries': [],
            'company_ids': [],
            'status': 'candidate', 'identity_status': 'not_verified', 'is_candidate': True, 'is_confirmed_project': False,
            'name_evidence': [], 'stage_signals': [], 'capacity_signals': [], 'company_observations': [], 'company_links': [],
            'grouping_basis': 'exact_normalized_metadata_name_only'})
        for field, values in (('article_ids', mention['article_ids']), ('cities', mention['cities']), ('countries', mention['countries'])):
            group[field] = list(dict.fromkeys(group[field] + values))
        group['company_ids'] = list(dict.fromkeys(group['company_ids'] + mention.get('company_ids', [])))
        group['mention_ids'].append(mention['id'])
        group['name_evidence'].append(deepcopy(mention['evidence']))
        for field in ('stage_signals', 'capacity_signals', 'company_observations'):
            group[field].extend(deepcopy(mention[field]))
        for item in mention.get('company_links', []):
            link = deepcopy(item)
            link.update(project_id=group['id'], project_is_candidate=True,
                id=_id('project-company-observation', group['id'] + ':' + mention['article_id'] + ':' + item['company_id'] + ':' + item['role']))
            group['company_links'].append(link)
    candidates = list(groups.values())
    for group in candidates:
        group['article_count'] = len(group['article_ids'])
        group['location'] = ' · '.join(group['cities'])
        group['summary'] = '기사 원문 명칭 관측을 묶은 사업 후보입니다. 동일 사업·부지·참여 역할·용량은 미확정입니다.'
    candidates.sort(key=lambda item: (-item['article_count'], item['name']))
    company_links = registered_links + [item for group in candidates for item in group['company_links']]
    # Explicit stored relationships retain their original provenance and are
    # the only entries classified as confirmed participation.
    selected = {item['id']: item for item in articles}
    for relationship in ds.get('relationships', {}).values():
        pid, cid = relationship.get('project_id'), relationship.get('company_id')
        aids = [aid for aid in relationship.get('article_ids', [])
                if aid in selected and pid in selected[aid].get('project_ids', [])]
        if relationship.get('directness') == 'explicit' and aids:
            from .ontology import _roles
            for role in _roles(str(relationship.get('role', ''))):
                company_links.append({'id': relationship['id'] + ':' + role, 'project_id': pid, 'company_id': cid,
                    'project_is_candidate': False, 'role': role, 'label': relationship.get('role', ''),
                    'basis': 'explicit_stored_relationship', 'status': 'registered_evidence',
                    'article_ids': aids, 'evidence': [], 'relationship_id': relationship['id'],
                    'direct_contract_confirmed': False, 'is_confirmed_participation': True})
    return {'mentions': mentions, 'project_candidates': candidates, 'company_observations': company_observations,
        'company_links': company_links,
        'analysis_pending': pending, 'version': VERSION,
        'counts': {'articles': len(articles), 'article_mentions': len(mentions),
            'articles_with_project_mentions': len({item['article_id'] for item in mentions}),
            'candidate_name_groups': len(candidates), 'pending_identity_articles': len(pending),
            'registered_linked_articles': sum(bool(item.get('project_ids')) for item in articles),
            'persisted_article_analyses': persisted, 'derived_article_analyses': len(articles) - persisted,
            'company_name_observations': len(company_observations)},
        'limitations': ['명칭 묶음은 고유 사업 수가 아니며 같은 도시·기업으로 사업을 합치지 않습니다.',
            '공개 제목에 명시된 지명과 연속 사업명만 규칙으로 관측합니다. 본문·사내 AI 분석은 미검증입니다.',
            '기업명·단계·용량은 원문 메타데이터 후보이며 확정 역할·계약·IT/수전 용량이나 합계로 사용하지 않습니다.',
            '일반 동향·도시 미명시·해외 고유 사업명은 분석 보류로 남을 수 있습니다. 원문과 기존 사업은 보존합니다.']}
