"""Company business-nature observations, deliberately separate from project roles.

No profile establishes participation in any particular project or a contract.
Descriptors and name-grammar proposals retain their own provenance and status.
"""
from copy import deepcopy
import json
from functools import lru_cache
from pathlib import Path
import re

PROFILE_VERSION = '0.4.3-company-nature'
PROFILE_LABELS = {'client': '발주처', 'developer': '사업자', 'tenant': '테넌트',
    'contractor': '시공사', 'designer': '설계사', 'operator': '운영사',
    'equipment_supplier': '장비사', 'financier': 'PF사·금융주선사', 'unknown': '성격 미확인'}
DESCRIPTORS = {
    'client': r'발주처|발주사|발주자', 'developer': r'시행사|개발사|(?<!운영)(?<!운영\s)사업자',
    'tenant': r'테넌트|임차사|입주사', 'operator': r'운영사|운영사업자',
    'contractor': r'시공사|건설사|종합건설업체', 'designer': r'설계사|건축사사무소|설계업체',
    'equipment_supplier': r'장비사|장비\s*(?:제조|공급)업체|기자재\s*공급사',
    'financier': r'PF사|PF\s*주선사|금융주선사|금융주관사|프로젝트\s*금융사',
}
NAME_PROPOSALS = {'contractor': r'건설$|Construction$',
    'designer': r'건축사사무소$|설계사무소$|Architects?$',
    'equipment_supplier': r'전선$|일렉트릭$|Electric$',
    'financier': r'은행$|증권$|자산운용$|캐피탈$|Bank$|Capital$'}


def _normalized_name(value):
    # Exact aliases only; a parent's name cannot classify a subsidiary.
    return re.sub(r'[\s·.,()㈜]+', '', str(value)).casefold()


@lru_cache(maxsize=1)
def profile_registry():
    path = Path(__file__).resolve().parents[1] / 'config' / 'company_profile_registry.json'
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding='utf-8'))
    result = {}
    for entry in payload.get('companies', []):
        for alias in [entry['name']] + entry.get('aliases', []):
            key = _normalized_name(alias)
            if key in result and result[key]['name'] != entry['name']:
                raise ValueError('Ambiguous company profile registry alias')
            result[key] = entry
    return result


def descriptor_observations(article, company_name, name_evidence):
    """Only an immediately attached noun descriptor describes a company nature.

    A verb elsewhere in a project headline cannot become a static descriptor.
    """
    text = article.get(name_evidence.get('field', 'title')) or ''
    if not isinstance(text, str):
        return []
    start, end = name_evidence.get('start', 0), name_evidence.get('end', 0)
    before, after = text[max(0, start - 32):start], text[end:end + 32]
    result = []
    for category, pattern in DESCRIPTORS.items():
        # Permit "데이터센터 운영사 한빛" and "한빛(운영사)" only.
        left = re.search('(?:' + pattern + r')[\s\"“‘\']*$', before, re.I)
        right = re.match(r'[\s(（]+(' + pattern + r')[)）]?', after, re.I)
        if not left and not right:
            continue
        lo = max(0, start - 32) + left.start() if left else start
        hi = end if left else end + right.end()
        evidence = {**deepcopy(name_evidence), 'text': text[lo:hi], 'start': lo, 'end': hi}
        result.append({'category': category, 'basis': 'explicit_company_noun_descriptor',
            'status': 'metadata_descriptor', 'article_ids': [article['id']], 'evidence': evidence})
    return result


def build_company_profile(company, observations=()):
    evidence = []
    # A stored company-level descriptor is not a project-level relationship.
    raw_role = str(company.get('role') or '').strip()
    for category, pattern in DESCRIPTORS.items():
        if re.search(r'(?<!\w)' + re.escape(category) + r'(?!\w)', raw_role, re.I) or re.search(pattern, raw_role, re.I):
            evidence.append({'category': category, 'basis': 'registered_company_descriptor',
                'status': 'registered_metadata', 'raw_role': raw_role, 'article_ids': [],
                'evidence': {'field': 'companies.role', 'text': raw_role, 'company_id': company['id']}})
    # Existing company metadata can state an explicit nature, independently of
    # headline participation. Ignore generated article-observation summaries.
    for field in ('descriptor', 'business_description', 'summary'):
        text = company.get(field)
        if (not isinstance(text, str) or company.get('classification') == 'observed_name_only'
                or re.search(r'아니|아닌|부인|미확인|추정|후보|unverified|not\b', text, re.I)):
            continue
        for category, pattern in DESCRIPTORS.items():
            # A company record can describe its customers too. A bare mention
            # ("운영사에 장비 공급") does not describe the supplier as operator.
            matches = list(re.finditer(pattern, text, re.I))
            owns_descriptor = any(
                not re.match(r'\s*(?:에게|에|와|과|를|을|의|용)', text[match.end():])
                and (field != 'summary' or re.search(r'(?:^|입니다[.。]?\s*|[.;。]\s*|이며\s*|및\s*)[^.;。]{0,90}$', text[:match.start()]))
                for match in matches)
            if owns_descriptor:
                evidence.append({'category': category, 'basis': 'registered_company_description',
                    'status': 'registered_metadata', 'article_ids': [],
                    'evidence': {'field': 'companies.' + field, 'text': text, 'company_id': company['id']}})
    registry = profile_registry().get(_normalized_name(company.get('name', '')))
    if registry:
        for category in registry['categories']:
            evidence.append({'category': category, 'basis': 'official_company_profile_registry',
                'status': 'official_business_nature', 'article_ids': [],
                'evidence': {'field': 'company_profile_registry', 'text': registry['description'],
                    'source_url': registry['source_url'], 'checked_at': registry['checked_at'],
                    'company_name': registry['name'], 'company_id': company['id']}})
    for observation in observations:
        evidence.extend(deepcopy(observation.get('profile_evidence', [])))
    if not evidence:
        for category, pattern in NAME_PROPOSALS.items():
            if re.search(pattern, company.get('name', ''), re.I):
                name_sources = company.get('name_evidence') or []
                evidence.append({'category': category, 'basis': 'company_name_grammar_proposal',
                    'status': 'classification_proposal',
                    'article_ids': sorted({item['article_id'] for item in name_sources if item.get('article_id')}),
                    'evidence': deepcopy(name_sources[0]) if name_sources else
                        {'field': 'companies.name', 'text': company.get('name', ''), 'company_id': company['id']}})
    unique = {}
    for item in evidence:
        span = item.get('evidence', {})
        key = (item['category'], item['basis'], tuple(item.get('article_ids', [])), span.get('field'), span.get('start'), span.get('text'))
        unique[key] = item
    evidence = list(unique.values())
    categories = [category for category in PROFILE_LABELS if any(item['category'] == category for item in evidence)] or ['unknown']
    profile = {'version': PROFILE_VERSION, 'categories': categories, 'evidence': evidence,
        'classification_status': 'metadata_profile' if evidence else 'unresolved',
        'project_role_separate': True,
        'note': '기업 성격 분류입니다. 상호 추론은 후보이며 개별 사업의 참여 역할·계약을 확정하지 않습니다.'}
    return {'profile_categories': categories, 'profile_evidence': evidence, 'company_profile': profile}


def profile_fields(company, manual_classification=None):
    profile = company.get('company_profile')
    if profile and profile.get('version') == PROFILE_VERSION:
        automatic = {key: deepcopy(company[key]) for key in ('profile_categories', 'profile_evidence', 'company_profile')}
    else:
        automatic = build_company_profile(company)
    automatic['company_profile']['manual_override'] = False
    automatic['manual_classification'] = None
    if manual_classification is None:
        return automatic
    manual = deepcopy(manual_classification)
    categories = deepcopy(manual['categories'])
    evidence = [{'category': category, 'basis': 'user_company_nature',
        'status': 'user_classification', 'article_ids': [],
        'evidence': {'field': 'company_classifications.categories', 'company_id': company['id'],
            'history_id': manual['history_id'], 'updated_at': manual['updated_at']}}
        for category in categories]
    return {'profile_categories': categories, 'profile_evidence': evidence,
        'manual_classification': manual,
        'company_profile': {'version': PROFILE_VERSION, 'categories': categories, 'evidence': evidence,
            'classification_status': 'user_classified', 'manual_override': True,
            'automatic_profile': automatic['company_profile'], 'project_role_separate': True,
            'note': '사용자가 지정한 기업 성격입니다. 개별 사업 참여·계약을 확정하지 않습니다.'}}
