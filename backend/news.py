"""Article workspace: deterministic metadata digests and evidence-linked candidates.

This module never fetches full articles, calls AI, or changes verified project facts.
"""
from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from .attention import recent_article
import hashlib
import re
import shlex

UTC = timezone.utc
ENRICHMENT_VERSION = '0.4.1-project-discovery'
AI_TOKEN = r'(?<![A-Za-z0-9])(?:AIDC|AI)(?![A-Za-z0-9])'
KST = timezone(timedelta(hours=9))
PERIODS = {'3y': (36, None, '최근 3년'), '1y': (12, None, '최근 1년'),
           '6m': (6, None, '최근 6개월'), '3m': (3, None, '최근 3개월'),
           '1m': (1, None, '최근 1개월'), '2w': (None, 14, '최근 2주'),
           '1w': (None, 7, '최근 1주'), '3d': (None, 3, '최근 3일'),
           '1d': (None, 1, '최근 하루'), 'all': (None, None, '저장된 전체 기간')}
ALIASES = [
    ('Oracle', ['Oracle', '오라클']), ('Amazon Web Services', ['Amazon Web Services', 'AWS', '아마존웹서비스', '아마존']),
    ('SK텔레콤', ['SK텔레콤', 'SK Telecom', 'SKT']), ('SK에코플랜트', ['SK에코플랜트', 'SK ecoplant']),
    ('OpenAI', ['OpenAI', '오픈AI', '오픈에이아이']), ('NVIDIA', ['NVIDIA', '엔비디아']),
    ('Microsoft', ['Microsoft', '마이크로소프트']), ('Google', ['Google', '구글']),
    ('Meta', ['Meta Platforms', '메타', 'Meta']), ('G42', ['G42']),
    ('Cisco', ['Cisco', '시스코']), ('SoftBank', ['SoftBank', '소프트뱅크']),
    ('삼성SDS', ['삼성SDS', 'Samsung SDS']), ('LG CNS', ['LG CNS', 'LG씨엔에스']),
    ('KT', ['KT', '케이티']), ('Equinix', ['Equinix', '에퀴닉스']),
    ('Digital Realty', ['Digital Realty', '디지털리얼티']), ('xAI', ['xAI']),
    ('LS일렉트릭', ['LS일렉트릭', 'LS ELECTRIC']), ('LS전선', ['LS전선', 'LS Cable']),
    ('대한전선', ['대한전선', 'Taihan']), ('가온전선', ['가온전선']),
    ('HD현대일렉트릭', ['HD현대일렉트릭', 'HD Hyundai Electric']), ('효성중공업', ['효성중공업', 'Hyosung Heavy Industries']),
    ('현대건설', ['현대건설', 'Hyundai Engineering & Construction']), ('현대엔지니어링', ['현대엔지니어링', 'Hyundai Engineering']),
    ('삼성물산', ['삼성물산', 'Samsung C&T']), ('GS건설', ['GS건설', 'GS E&C']),
    ('대우건설', ['대우건설', 'Daewoo E&C']), ('DL이앤씨', ['DL이앤씨', 'DL E&C']),
    ('포스코이앤씨', ['포스코이앤씨', 'POSCO E&C']), ('포스코', ['포스코', 'POSCO']),
    ('현대제철', ['현대제철', 'Hyundai Steel']), ('한미글로벌', ['한미글로벌', 'HanmiGlobal']),
    ('한화오션', ['한화오션', 'Hanwha Ocean']), ('한화', ['한화', 'Hanwha']),
    ('네이버', ['네이버', 'NAVER']), ('카카오', ['카카오', 'Kakao']),
    ('삼성전자', ['삼성전자', 'Samsung Electronics']), ('SK하이닉스', ['SK하이닉스', 'SK hynix']),
    ('LG전자', ['LG전자', 'LG Electronics']), ('Vertiv', ['Vertiv', '버티브']),
    ('Schneider Electric', ['Schneider Electric', '슈나이더일렉트릭']),
    ('CoreWeave', ['CoreWeave', '코어위브']), ('Vantage Data Centers', ['Vantage Data Centers']),
    ('DigitalBridge', ['DigitalBridge', '디지털브릿지']),
]
CATEGORIES = [
    ('데이터센터', r'data\s*cent(?:er|re)|datacent(?:er|re)|데이터\s*센터|\bDC\b'),
    ('AIDC', AI_TOKEN + r'|인공지능'),
    ('전력', r'power|electric|grid|energy|전력|수전|발전|에너지'),
    ('냉각', r'cooling|liquid|냉각|액침|수랭'),
    ('투자·확장', r'invest|expand|expansion|투자|확장|증설'),
    ('부지·인허가', r'permit|land|site|planning|부지|인허가|입지'),
    ('설계·시공', r'construct|design|groundbreak|시공|건설|설계|기공|착공'),
    ('자금·조달', r'financ|funding|capital|procure|자금|조달|펀드|금융'),
]
COUNTRIES = {
    'KR': ('대한민국', r'대한민국|한국|국내|\bSouth Korea\b|\bKorea\b'),
    'US': ('미국', r'미국|(?<![가-힣A-Za-z])美(?=\s|[·,])|\bUnited States\b|\bU\.S\.|\bUSA\b'),
    'AE': ('아랍에미리트', r'아랍에미리트|\bUAE\b|\bUnited Arab Emirates\b'),
    'JP': ('일본', r'일본|\bJapan\b'), 'CN': ('중국', r'중국|\bChina\b'),
    'SG': ('싱가포르', r'싱가포르|\bSingapore\b'), 'MY': ('말레이시아', r'말레이시아|\bMalaysia\b'),
    'IN': ('인도', r'인도(?!네시아)|\bIndia\b'), 'ID': ('인도네시아', r'인도네시아|\bIndonesia\b'),
    'AU': ('호주', r'호주|\bAustralia\b'), 'GB': ('영국', r'영국|\bUnited Kingdom\b|\bUK\b'),
    'DE': ('독일', r'독일|\bGermany\b'), 'FR': ('프랑스', r'프랑스|\bFrance\b'),
    'SA': ('사우디아라비아', r'사우디|\bSaudi Arabia\b'),
    'CA': ('캐나다', r'캐나다|\bCanada\b'), 'BR': ('브라질', r'브라질|\bBrazil\b'),
    'MX': ('멕시코', r'멕시코|\bMexico\b'), 'CL': ('칠레', r'칠레|\bChile\b'),
    'NL': ('네덜란드', r'네덜란드|\bNetherlands\b'), 'IE': ('아일랜드', r'아일랜드|\bIreland\b'),
    'ES': ('스페인', r'스페인|\bSpain\b'), 'IT': ('이탈리아', r'이탈리아|\bItaly\b'),
    'SE': ('스웨덴', r'스웨덴|\bSweden\b'), 'NO': ('노르웨이', r'노르웨이|\bNorway\b'),
    'FI': ('핀란드', r'핀란드|\bFinland\b'), 'DK': ('덴마크', r'덴마크|\bDenmark\b'),
    'PL': ('폴란드', r'폴란드|\bPoland\b'), 'BE': ('벨기에', r'벨기에|\bBelgium\b'),
    'CH': ('스위스', r'스위스|\bSwitzerland\b'), 'AT': ('오스트리아', r'오스트리아|\bAustria\b'),
    'VN': ('베트남', r'베트남|\bVietnam\b'), 'TH': ('태국', r'태국|\bThailand\b'),
    'TW': ('대만', r'대만|\bTaiwan\b'), 'PH': ('필리핀', r'필리핀|\bPhilippines\b'),
    'NZ': ('뉴질랜드', r'뉴질랜드|\bNew Zealand\b'), 'ZA': ('남아프리카공화국', r'남아공|남아프리카|\bSouth Africa\b'),
    'IL': ('이스라엘', r'이스라엘|\bIsrael\b'), 'QA': ('카타르', r'카타르|\bQatar\b'),
}
CITIES = {
    '서울': ('KR', r'서울|\bSeoul\b'), '울산': ('KR', r'울산|\bUlsan\b'),
    '인천': ('KR', r'인천|\bIncheon\b'), '안산': ('KR', r'안산|\bAnsan\b'),
    '대구': ('KR', r'대구|\bDaegu\b'), '부산': ('KR', r'부산|\bBusan\b'),
    '광주': ('KR', r'광주|\bGwangju\b'), '용인': ('KR', r'용인|\bYongin\b'),
    '성남': ('KR', r'성남|\bSeongnam\b'), '평택': ('KR', r'평택|\bPyeongtaek\b'),
    '아부다비': ('AE', r'아부다비|\bAbu Dhabi\b'), '도쿄': ('JP', r'도쿄|\bTokyo\b'),
    '런던': ('GB', r'런던|\bLondon\b'), '애빌린': ('US', r'애빌린|\bAbilene\b'),
}
# Domestic ontology keys are municipality names, never company headquarters.
# Common English spellings supplement Korean city names found in public metadata.
for _city in ('수원 의정부 안양 부천 광명 동두천 고양 과천 구리 남양주 오산 시흥 군포 의왕 하남 파주 이천 안성 김포 화성 양주 포천 여주 '
              '춘천 원주 강릉 동해 태백 속초 삼척 청주 충주 제천 천안 공주 보령 아산 서산 논산 계룡 당진 '
              '전주 군산 익산 정읍 남원 김제 목포 여수 순천 나주 광양 포항 경주 김천 안동 구미 영주 영천 상주 문경 경산 '
              '창원 진주 통영 사천 김해 밀양 거제 양산 제주 서귀포').split():
    CITIES.setdefault(_city, ('KR', re.escape(_city)))
for _city, _english in {'대전': 'Daejeon', '세종': 'Sejong', '김해': 'Gimhae', '춘천': 'Chuncheon',
                        '수원': 'Suwon', '고양': 'Goyang', '안양': 'Anyang', '화성': 'Hwaseong',
                        '창원': 'Changwon', '전주': 'Jeonju', '청주': 'Cheongju', '제주': 'Jeju'}.items():
    CITIES[_city] = ('KR', re.escape(_city) + r'|\b' + _english + r'\b')
CITIES['해남'] = ('KR', r'해남')
KR_PROVINCE = re.compile(r'(?<![가-힣A-Za-z])(?:강원(?:특별자치도)?|경기(?:도)?|충청[남북]도|충[남북](?:도)?|전라[남북]도|전[남북](?:도)?|경상[남북]도|경[남북](?:도)?|제주특별자치도)(?=\s|[·,]|AI|데이터|$)', re.I)


def _dt(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        value = value.strip()
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('ISO 날짜/시각이 필요합니다.')
    # A publication date without an offset represents local KST, never host timezone.
    return result.replace(tzinfo=KST).astimezone(UTC) if result.tzinfo is None else result.astimezone(UTC)


def _iso(value):
    return value.astimezone(UTC).isoformat()


def _id(prefix, value):
    return prefix + '-' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]


def period_bounds(period, as_of=None):
    period = period or '3y'
    if period not in PERIODS:
        raise ValueError('지원하지 않는 기사 기간입니다.')
    end = _dt(as_of) if as_of is not None else datetime.now(UTC)
    months, days, label = PERIODS[period]
    start = None
    if months:
        local = end.astimezone(KST)
        index = local.year * 12 + local.month - 1 - months
        year, month = index // 12, index % 12 + 1
        start = local.replace(year=year, month=month, day=min(local.day, monthrange(year, month)[1]))
    elif days:
        start = end - timedelta(days=days)
    return {'period': period, 'start': _iso(start) if start else None, 'end': _iso(end),
            'label': label, 'timezone': 'Asia/Seoul'}


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def normalize_filters(request=None, as_of=None):
    request = request or {}
    result = period_bounds(_first(request.get('period')) or '3y', as_of)
    for key in ('q', 'scope', 'company_id', 'project_id', 'country', 'city'):
        value = _first(request.get(key, request.get('query') if key == 'q' else '')) or ''
        if not isinstance(value, str) or len(value) > (500 if key == 'q' else 200):
            raise ValueError('잘못된 기사 검색 조건입니다.')
        result[key] = value.strip()
    result['scope'] = result['scope'] or 'all'
    if result['scope'] not in ('all', 'kr-dc', 'kr-ai', 'global-ai', 'unresolved'):
        raise ValueError('지원하지 않는 수집 범위입니다.')
    result['country'] = _country_code(result['country'])
    result['city'] = _city_name(result['city'])
    sources = request.get('source_ids') or []
    if isinstance(sources, str):
        sources = sources.split(',')
    if not isinstance(sources, list) or any(not isinstance(x, str) for x in sources):
        raise ValueError('매체 ID 목록이 필요합니다.')
    result['source_ids'] = sorted({part.strip() for source in sources for part in source.split(',') if part.strip()})
    try:
        terms = shlex.split(result['q'])
    except ValueError as error:
        raise ValueError('검색어 따옴표를 닫아 주세요. 단어와 인용구 검색을 지원합니다.') from error
    if any(term in ('AND', 'OR', 'NOT', '&&', '||') for term in terms):
        raise ValueError('부울 연산자는 지원하지 않습니다. 공백은 모든 단어 일치, 따옴표는 인용구 검색입니다.')
    result['q_terms'] = list(dict.fromkeys(term.casefold() for term in terms if term.strip()))
    result['query_syntax'] = 'terms_and_quoted_phrases'
    return result


def _text(article):
    publisher = article.get('publisher')
    description, excerpt = article.get('description',''),article.get('feed_excerpt','')
    if publisher:
        if isinstance(description,str):description=description.replace(publisher,'')
        if isinstance(excerpt,str):excerpt=excerpt.replace(publisher,'')
    values = [article.get('title', ''), article.get('summary', ''), description, excerpt]
    # Aggregator descriptions repeat their publisher label. "Data Center Dynamics"
    # and "한국경제" must not supply a topic, company or country absent in content.
    return ' '.join(' '.join(str(x) for x in v) if isinstance(v, list) else str(v or '') for v in values)


def _analysis_stamp(article):
    return hashlib.sha256(repr((_text(article),article.get('publisher'),article.get('project_ids',[]),
                                article.get('candidate_project_ids',[]))).encode('utf-8')).hexdigest()


def _match(text, alias):
    if not alias or len(alias.strip()) < 2:
        return False
    # Latin names must be entire words (AWS is not part of a longer word).
    pattern = re.escape(alias.strip())
    if re.match(r'[A-Za-z0-9]', alias):
        pattern = r'(?<![A-Za-z0-9])' + pattern
    if re.search(r'[A-Za-z0-9]$', alias):
        pattern += r'(?![A-Za-z0-9])'
    return bool(re.search(pattern, text, re.I))


def _country_code(value):
    value = value.strip()
    aliases = {'UAE': 'AE', 'USA': 'US', 'KOREA': 'KR', '대한민국': 'KR', '한국': 'KR'}
    if value.upper() in COUNTRIES:
        return value.upper()
    if value.upper() in aliases:
        return aliases[value.upper()]
    return next((code for code, (name, _) in COUNTRIES.items() if value == name), value)


def _city_name(value):
    return re.sub(r'(특별자치시|특별시|광역시|시)$', '', value.strip())


def _geography(article, projects):
    # The source label repeated in RSS descriptions is not a project location.
    text = _text(article)
    publisher = article.get('publisher')
    if publisher:
        text = text.replace(publisher, '')
    text = re.sub(r'한국(?:경제|전력|수력원자력|가스공사|은행|일보|투자|산업은행|토지주택공사|전기|철강|건설|석유|지역난방|금융|통신)[가-힣]*', '', text)
    countries, cities, evidence = set(), set(), []
    province = KR_PROVINCE.search(text)
    if province:
        countries.add('KR')
        evidence.append({'field': 'country', 'value': 'KR', 'text': province.group(), 'basis': 'explicit_domestic_province'})
    for code, (_, pattern) in COUNTRIES.items():
        found = re.search(pattern, text, re.I)
        if found:
            countries.add(code)
            evidence.append({'field': 'country', 'value': code, 'text': found.group(), 'basis': 'explicit_metadata_place'})
    for city, (country, pattern) in CITIES.items():
        found = re.search(pattern, text, re.I)
        if city == '양산' and found and re.search(r'(?:칩|반도체|제품|GPU|서버)\s*양산|양산\s*(?:돌입|개시|체제|성공)', text, re.I) and not re.search(r'양산(?:시|에|의)|경남\s*양산|경상남도\s*양산', text):
            continue
        if found:
            countries.add(country)
            cities.add(city)
            evidence.append({'field': 'city', 'value': city, 'text': found.group(), 'basis': 'explicit_metadata_place'})
    for pid in article.get('project_ids', []) + article.get('candidate_project_ids', []):
        project = projects.get(pid, {})
        country = _country_code(project.get('country', ''))
        if country:
            countries.add(country)
            evidence.append({'field': 'country', 'value': country, 'project_id': pid, 'basis': 'matched_project_context'})
        location = project.get('location', '')
        for city, (_, pattern) in CITIES.items():
            if re.search(pattern, location, re.I):
                cities.add(city)
    return {'countries': sorted(countries), 'cities': sorted(cities), 'evidence': evidence,
            'classification': 'location_candidate' if evidence else 'unresolved'}


def classify_article(article, projects=None):
    """Separate topical admission from exclusive business scope, without making facts.

    Broad AI/semiconductor news and a publisher's nationality cannot prove a DC.
    An admitted DC article with unclear geography/AI use remains scope-unresolved.
    """
    projects = projects or {}
    text = _text(article)
    dc = re.search(r'data\s*cent(?:er|re)|datacent(?:er|re)|데이터\s*센터|(?<![A-Za-z0-9])AIDC(?![A-Za-z0-9])|서버\s*팜|\bserver\s*farm\b', text, re.I)
    ai = re.search(AI_TOKEN + r'|인공지능|\bHPC\b|고성능\s*컴퓨팅|\bGPU\s*(?:cluster|클러스터)', text, re.I)
    registered = {projects[p].get('scope') for p in _article_projects(article) if p in projects}
    registered &= {'kr-dc','kr-ai','global-ai'}
    if not dc and not registered:
        uncertain = bool(re.search(r'AI\s*(?:인프라|팩토리|공장)|\bAI\s+(?:infrastructure|factory)|컴퓨팅\s*캠퍼스', text, re.I))
        relevance = {'status':'unresolved' if uncertain else 'out_of_scope',
                     'reason':'datacenter_context_unconfirmed' if uncertain else 'no_datacenter_evidence'}
        return {'domain_relevance':relevance, 'scope_classification':{'primary_scope':None,
            'status':'unresolved' if uncertain else 'out_of_scope','reason':relevance['reason']}}
    geo = _geography(article, projects)
    # Prefer locations in the headline to comparative/background places in an excerpt.
    headline_geo = _geography({**article,'title':article.get('title',''),'summary':'','description':'','feed_excerpt':'',
                               'project_ids':[],'candidate_project_ids':[]}, {})
    countries = headline_geo['countries'] or geo['countries']
    primary, reason = None, 'location_unconfirmed'
    if len(registered)==1:
        primary, reason = next(iter(registered)), 'registered_project_context'
    elif len(registered)>1:
        reason = 'multiple_project_scopes'
    elif countries:
        domestic, foreign = 'KR' in countries, any(c!='KR' for c in countries)
        if domestic and foreign:
            reason = 'multiple_regions_in_metadata'
        elif domestic:
            primary, reason = ('kr-ai' if ai else 'kr-dc'), 'explicit_domestic_dc_metadata'
        elif ai:
            primary, reason = 'global-ai', 'explicit_foreign_ai_dc_metadata'
        else:
            reason = 'foreign_dc_ai_use_unconfirmed'
    elif ai and re.search(r'해외|국외|\boverseas\b|\binternational\b',article.get('title',''),re.I):
        primary, reason = 'global-ai', 'explicit_overseas_ai_dc_country_unconfirmed'
    return {'domain_relevance':{'status':'relevant','reason':'registered_project_context' if registered else 'explicit_datacenter_metadata',
                                'evidence':dc.group() if dc else None},
            'scope_classification':{'primary_scope':primary,'status':'classified' if primary else 'unresolved',
                                    'reason':reason,'ai_evidence':ai.group() if ai else None}}


def enrich_articles(datasets, article_ids):
    """Record name-match observations only; preserve all verified facts and IDs."""
    companies = datasets.setdefault('companies', {})
    projects = datasets.setdefault('projects', {})
    updates = datasets.setdefault('news_updates', {})
    processed = []
    # Build alias expansion once per batch, rather than once per company/article.
    # Repeated regex compilation here dominated startup on real article archives.
    def normalize_name(value):
        return re.sub(r'[^a-z0-9가-힣]', '', value.casefold())
    def patterns(aliases):
        result=[]
        for alias in dict.fromkeys(aliases):
            if len(alias.strip())<2:
                continue
            pattern=re.escape(alias.strip())
            if re.match(r'[A-Za-z0-9]',alias):pattern=r'(?<![A-Za-z0-9])'+pattern
            if re.search(r'[A-Za-z0-9]$',alias):pattern+=r'(?![A-Za-z0-9])'
            result.append((alias,re.compile(pattern,re.I)))
        return result
    curated = {canonical:patterns(aliases) for canonical,aliases in ALIASES}
    curated_names = {canonical:{normalize_name(name) for name in aliases+[canonical]} for canonical,aliases in ALIASES}
    known, company_patterns = {}, {}
    for company in companies.values():
        aliases=[company.get('name','')]+list(company.get('aliases') or [])
        names={normalize_name(name) for name in aliases if name}
        for canonical,group in ALIASES:
            if names & curated_names[canonical]:
                aliases+=group
                known[canonical]=company['id']
        company_patterns[company['id']]=patterns(aliases)
    project_patterns={p['id']:patterns([p.get('name','')]+list(p.get('aliases') or [])) for p in projects.values()}
    for aid in dict.fromkeys(article_ids):
        article = datasets.get('articles', {}).get(aid)
        if article is None:
            continue
        text = _text(article)
        matches = []
        observed = set(article.get('company_ids', [])) & set(companies)
        for cid, matchers in company_patterns.items():
            found = next((name for name,pattern in matchers if pattern.search(text)),None)
            if found:
                observed.add(cid)
                matches.append({'entity_type': 'company', 'id': cid, 'matched_text': found,
                                'basis': 'explicit_name_in_metadata', 'confidence': 'name_match_candidate'})
        # Known names first seen in news are observation entities, never asserted participants.
        for canonical, aliases in ALIASES:
            if canonical in known:
                continue
            found = next((name for name,pattern in curated[canonical] if pattern.search(text)),None)
            if not found:
                continue
            cid = _id('co-observed', canonical.casefold())
            companies[cid] = {'id': cid, 'name': canonical, 'aliases': aliases, 'project_ids': [],
                             'classification': 'observed_name_only', 'role': '미확인',
                             'summary': '공개 기사 메타데이터의 이름 등장 관측. 사업 참여·계약·역할 미확인.'}
            known[canonical]=cid
            company_patterns[cid]=curated[canonical]
            observed.add(cid)
            matches.append({'entity_type': 'company', 'id': cid, 'matched_text': found,
                            'basis': 'explicit_name_in_metadata', 'confidence': 'name_match_candidate'})
        candidates = set(article.get('candidate_project_ids', [])) & set(projects)
        for pid, matchers in project_patterns.items():
            found = next((name for name,pattern in matchers if pattern.search(text)),None)
            if found and pid not in article.get('project_ids', []):
                candidates.add(pid)
                matches.append({'entity_type': 'project', 'id': pid, 'matched_text': found,
                                'basis': 'exact_registered_project_name', 'confidence': 'name_match_candidate'})
        article['company_ids'] = sorted(observed)
        article['candidate_project_ids'] = sorted(candidates)
        article['entity_matches'] = matches
        article['business_categories'] = [label for label, pattern in CATEGORIES if re.search(pattern, text, re.I)]
        article['category_basis'] = 'metadata_keywords'
        article['geography'] = _geography(article, projects)
        article.update(classify_article(article, projects))
        article['analysis_version'] = ENRICHMENT_VERSION
        article['analysis_input_hash'] = _analysis_stamp(article)
        if article.get('mode') == 'live_metadata':
            article['summary_method'] = 'metadata_digest'
        uid = _id('news', aid)
        updates.setdefault(uid, {'id': uid, 'article_id': aid, 'company_ids': article['company_ids'],
                                'project_ids': sorted(set(article.get('project_ids', []) + article['candidate_project_ids'])),
                                'kind': 'new_article', 'created_at': article.get('first_seen_at') or article.get('collected_at') or article.get('published_at'),
                                'summary': article.get('title', ''), 'classification': 'metadata_only'})
        processed.append(aid)
    return processed


def _article_projects(article):
    return set(article.get('project_ids', []) + article.get('candidate_project_ids', []))


def _article_companies(article, projects):
    # Verified article -> project -> participants is an explicit contextual path.
    result = set(article.get('company_ids', []))
    for pid in article.get('project_ids', []):
        result.update(projects.get(pid, {}).get('company_ids', []))
    return result


def _scopes(article, projects):
    primary = classify_article(article, projects)['scope_classification']['primary_scope']
    return {primary} if primary else set()


def _digest(articles):
    if not articles:
        return []
    groups = {}
    for article in articles:
        categories = article.get('business_categories') or ['기타 공개 기사']
        # Domain categories DC/AI are broad: prefer a specific common topic.
        topic = next((c for c in categories if c not in ('데이터센터', 'AIDC')), categories[0])
        groups.setdefault(topic, []).append(article)
    result = []
    for topic, items in groups.items():
        publishers = list(dict.fromkeys(a.get('publisher') or '매체 미확인' for a in items))
        observations, company_groups = {}, {}
        for article in items:
            for category in article.get('business_categories', []):
                observations.setdefault(category, []).append(article['id'])
            for company in article.get('matched_companies', []):
                entry = company_groups.setdefault(company['id'], {'id': company['id'], 'name': company['name'], 'article_ids': []})
                entry['article_ids'].append(article['id'])
        common_topics = [name for name, aids in observations.items() if len(aids) > 1]
        common_companies = [entry for entry in company_groups.values() if len(entry['article_ids']) > 1]
        companies = common_companies or list(company_groups.values())
        names = ', '.join(entry['name'] for entry in companies[:6])
        synthesis = (f'공통 관측 분류는 {", ".join(common_topics)}입니다. ' if common_topics else f'{topic} 분류의 기사 메타데이터를 묶었습니다. ')
        if names:
            synthesis += f'이 묶음에서 이름이 관측된 기업은 {names}입니다. '
        synthesis += '기업 이름 등장과 주제 키워드의 연결이며 참여·계약·사업 규모 변화를 확정하지 않습니다. '
        result.append({'topic': topic, 'text': f'{topic} 관련 {len(items)}개 기사({", ".join(publishers[:4])})의 메타데이터 기반 종합. '
                       + synthesis + '원문 본문 미확인 자료는 사실·계약·수치 확정에 사용하지 않습니다.',
                       'article_ids': [a['id'] for a in items], 'basis': 'metadata_digest',
                       'summary_method': 'metadata_digest', 'common_companies': common_companies,
                       'company_observations': list(company_groups.values()),
                       'topic_observations': [{'label': label, 'article_ids': aids, 'basis': 'metadata_keywords'} for label, aids in observations.items()],
                       'evidence_links': [{'article_id': a['id'], 'title': a.get('title', ''), 'url': a.get('url', ''),
                                           'publisher': a.get('publisher', ''), 'published_at': a['published_at']} for a in items],
                       'body_access': 'mixed_metadata_only', 'independent_evidence_count': None})
    return result


def _updates(articles, entities, field, projects):
    groups = {}
    for article in articles:
        ids = _article_companies(article, projects) if field == 'company' else _article_projects(article)
        for eid in ids:
            if eid in entities:
                groups.setdefault(eid, []).append(article)
    result = []
    for eid, items in groups.items():
        explicit = field == 'project' and all(eid in a.get('project_ids', []) for a in items)
        result.append({'id': eid, 'name': entities[eid].get('name', eid), 'article_ids': [a['id'] for a in items],
                       'latest_at': items[0]['published_at'], 'summary': ' '.join(d['text'] for d in _digest(items)),
                       'match_status': 'registered_evidence' if explicit else 'name_match_candidate'})
    return sorted(result, key=lambda item: _dt(item['latest_at']), reverse=True)


def _history_highlights(ds, selected_ids, filters):
    result = []
    for pid, project in ds.get('projects', {}).items():
        if filters['project_id'] and pid != filters['project_id']:
            continue
        if filters['company_id'] and filters['company_id'] not in project.get('company_ids', []):
            continue
        for field, histories in [('capacity', project.get('capacity_history', [])), ('status', project.get('status_history', []))]:
            for history in histories:
                if not history.get('candidate_selected') or history.get('value_changed') is False:
                    continue
                before, after = history.get('previous'), history.get('candidate')
                if before is None or after is None or before == after:
                    continue
                aids = list(history.get('article_ids', []))
                if field == 'capacity':
                    claim_id = after.get('claim_id')
                    claim = ds.get('claims', {}).get(claim_id, {})
                    if claim.get('article_id'):
                        aids.append(claim['article_id'])
                aids = sorted(set(aids) & selected_ids)
                if not aids:
                    continue
                related = [c for c in ds.get('changes', {}).values() if c.get('project_id') == pid and set(c.get('article_ids', [])) & set(aids)]
                change_ids = [c['id'] for c in related]
                unread = not change_ids or any(not ds.get('read_states', {}).get(cid, {}).get('read_at') for cid in change_ids)
                result.append({'id': _id('history', repr((pid, field, before, after))), 'project_id': pid,
                               'field': field, 'label': '용량 변경' if field == 'capacity' else '상태 변경',
                               'before': deepcopy(before), 'after': deepcopy(after), 'article_ids': aids,
                               'changed_at': after.get('event_date') if isinstance(after, dict) else history.get('event_date'),
                               'kind': 'verified_fact_change', 'unread': unread, 'change_ids': change_ids})
    return result


def build_workspace(snapshot, filters=None, as_of=None, *, include_catalog=False):
    normalized = normalize_filters(filters, as_of)
    # Enrichment mutates only these three datasets. Keep the potentially large
    # collection checkpoints read-only instead of cloning the whole archive.
    ds = dict(snapshot.get('datasets', snapshot))
    for name in ('articles', 'companies', 'news_updates'):
        ds[name] = deepcopy(ds.get(name, {}))
    enrich_articles(ds, [aid for aid,article in ds.get('articles',{}).items()
                        if article.get('analysis_version') != ENRICHMENT_VERSION or
                        article.get('analysis_input_hash') != _analysis_stamp(article)])
    projects, companies = ds.get('projects', {}), ds.get('companies', {})
    start = _dt(normalized['start']) if normalized['start'] else None
    end = _dt(normalized['end'])
    articles, invalid, future = [], 0, 0
    catalog_articles = []
    archive_articles, excluded_topic, uncertain_topic = 0, 0, 0
    scope_counts = dict.fromkeys(('all','kr-dc','kr-ai','global-ai','unresolved'),0)
    for article in ds.get('articles', {}).values():
        try:
            published = _dt(article.get('published_at'))
        except (ValueError, TypeError, OverflowError):
            invalid += 1
            continue
        if published >= end:
            future += 1
            continue
        if start and published < start:
            continue
        if normalized['q_terms'] and not all(term in _text(article).casefold() for term in normalized['q_terms']):
            continue
        if normalized['source_ids'] and article.get('source_id') not in normalized['source_ids']:
            continue
        if normalized['project_id'] and normalized['project_id'] not in _article_projects(article):
            continue
        # Reuse this one enrichment/filter pass for the worldwide company picker.
        # Its period/query/source/project constraints remain identical; selecting a
        # company, geographic scope or place must not hide other company choices.
        if include_catalog and article['domain_relevance']['status'] == 'relevant':
            catalog_articles.append(article)
        if normalized['company_id'] and normalized['company_id'] not in _article_companies(article, projects):
            continue
        in_geo = (not normalized['country'] or normalized['country'] in article['geography']['countries']) and (not normalized['city'] or normalized['city'] in article['geography']['cities'])
        relevance = article['domain_relevance']['status']
        if in_geo:
            archive_articles += 1
            excluded_topic += relevance == 'out_of_scope'
            uncertain_topic += relevance == 'unresolved'
        if relevance != 'relevant':
            continue
        scope = article['scope_classification']['primary_scope'] or 'unresolved'
        if in_geo:
            scope_counts['all'] += 1
            scope_counts[scope] += 1
        if normalized['scope'] != 'all' and normalized['scope'] != scope:
            continue
        articles.append(article)
    geography = {'countries': [], 'cities': []}
    for dimension, entity_key in [('countries', 'country'), ('cities', 'city')]:
        values = sorted({place for a in articles for place in a.get('geography', {}).get(dimension, [])})
        for place in values:
            related = [a for a in articles if place in a.get('geography', {}).get(dimension, [])]
            pids = set().union(*[_article_projects(a) for a in related])
            entry = {'id': place, 'name': COUNTRIES.get(place, (place,))[0] if dimension == 'countries' else place,
                     'article_count': len(related), 'project_count': len(pids)}
            if dimension == 'cities':
                entry['country'] = CITIES.get(place, (None,))[0]
            geography[dimension].append(entry)
    geography['domestic_cities'] = [entry for entry in geography['cities'] if entry['country'] == 'KR']
    geography['foreign_countries'] = [entry for entry in geography['countries'] if entry['id'] != 'KR']
    articles = [a for a in articles if (not normalized['country'] or normalized['country'] in a['geography']['countries'])
                and (not normalized['city'] or normalized['city'] in a['geography']['cities'])]
    articles.sort(key=lambda a: (_dt(a['published_at']), a['id']), reverse=True)
    updates_by_article = {u['article_id']: u for u in ds.get('news_updates', {}).values()}
    rows = []
    highlights = []
    for article in articles:
        aid = article['id']
        update = updates_by_article.get(aid)
        unread = bool(update and not ds.get('news_read_states', {}).get(update['id'], {}).get('read_at'))
        article['is_unread'] = unread
        article['is_recent'] = recent_article(article, ds, normalized['end'])
        article['is_new'] = unread and article['is_recent']
        article['news_update_id'] = update['id'] if update else None
        cids, pids = _article_companies(article, projects), _article_projects(article)
        article['matched_companies'] = [{'id': cid, 'name': companies[cid].get('name', cid), 'match_status': 'name_match_candidate'} for cid in sorted(cids) if cid in companies]
        article['matched_projects'] = [{'id': pid, 'name': projects[pid].get('name', pid), 'match_status': 'registered_evidence' if pid in article.get('project_ids', []) else 'name_match_candidate'} for pid in sorted(pids) if pid in projects]
        article['published_at_kst'] = _dt(article['published_at']).astimezone(KST).isoformat()
        rows.append({'article_id': aid, 'published_at': article['published_at'], 'published_at_kst': article['published_at_kst'],
                     'publisher': article.get('publisher', ''), 'source_id': article.get('source_id', ''),
                     'title': article.get('title', ''), 'url': article.get('url', ''),
                     'company_names': [x['name'] for x in article['matched_companies']],
                     'project_names': [x['name'] for x in article['matched_projects']],
                     'categories': article.get('business_categories', []), 'summary': article.get('summary', ''),
                     'summary_method': article.get('summary_method', 'manual_metadata'),
                     'access_status': article.get('access_status', 'unverified'),
                     'change_label': '신규 기사 · 사실 변경 미확인' if unread else '확인한 기사',
                     'country': article['geography']['countries'], 'city': article['geography']['cities']})
        if update:
            highlights.append({'id': update['id'], 'project_id': next(iter(sorted(pids)), None),
                               'project_ids': sorted(pids), 'field': 'article', 'label': '신규 기사 발견', 'before': None,
                               'after': article.get('title', ''), 'article_ids': [aid], 'changed_at': update.get('created_at'),
                               'kind': 'new_article', 'unread': unread})
    selected_ids = {a['id'] for a in articles}
    highlights += _history_highlights(ds, selected_ids, normalized)
    matching_projects = sorted(set().union(*[_article_projects(a) for a in articles])) if articles else []
    jobs = sorted(ds.get('news_jobs', {}).values(), key=lambda j: str(j.get('updated_at') or j.get('created_at') or ''), reverse=True)
    matching_jobs = []
    condition_keys = ('period', 'q', 'scope', 'company_id', 'project_id', 'source_ids', 'country', 'city')
    for job in jobs:
        if not isinstance(job.get('filters'), dict):
            continue
        try:
            job_filters = normalize_filters(job['filters'], normalized['end'])
        except ValueError:
            continue
        if all(job_filters[key] == normalized[key] for key in condition_keys):
            matching_jobs.append(job['id'])
    result = {'filters': normalized, 'articles': articles, 'summary': _digest(articles), 'rows': rows,
            'company_updates': _updates(articles, companies, 'company', projects),
            'project_updates': _updates(articles, projects, 'project', projects), 'highlights': highlights,
            'matching_project_ids': matching_projects, 'geography': geography,
            'coverage': list(ds.get('news_coverage', {}).values()),
            'jobs': jobs, 'jobs_scope': 'all_collection_history', 'matching_job_ids': matching_jobs,
            'latest_matching_job_id': matching_jobs[0] if matching_jobs else None,
            'counts': {'articles': len(articles), 'publishers': len({a.get('publisher') for a in articles}),
                       'scope_counts':scope_counts,'related_articles_all_scopes':scope_counts['all'],'archive_articles':archive_articles,
                       'excluded_out_of_scope':excluded_topic,'topic_unresolved':uncertain_topic,
                       'unread': sum(a['is_unread'] for a in articles), 'companies': len({c['id'] for a in articles for c in a['matched_companies']}),
                       'projects': len(matching_projects), 'excluded_invalid_date': invalid, 'excluded_future': future},
            'limitations': ['본문 미확인 기사는 공개 메타데이터 기반 종합입니다. 사내 AI 요약 품질은 미검증입니다.',
                            '이름 일치는 후보이며 사업 참여·계약·용량·진행 상태를 자동 확정하지 않습니다.',
                            '검색 제공자의 접근·기간·응답 상한이 있어 선택 기간의 모든 기사 확보를 보장하지 않습니다.',
                            '기사량은 시장 성장이나 용량 증가를 뜻하지 않습니다.'],
            'full_coverage_guaranteed': False}
    if include_catalog:
        result['_company_catalog_source'] = {'articles': catalog_articles, 'companies': companies}
    return result
