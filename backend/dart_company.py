"""Bounded official DART facts for COMPANY. No LLM and no parent substitution."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlencode
from .credentials import WindowsVault
from .repository import encoded, now
from .network import request_bytes

REPORTS = {'11011': '사업보고서', '11013': '1분기보고서', '11012': '반기보고서', '11014': '3분기보고서'}
ACCOUNTS = {'매출액', '영업수익', '수익(매출액)', '영업이익', '영업이익(손실)', '당기순이익', '당기순이익(손실)', '자산총계', '부채총계', '자본총계'}
LIMIT_NOTE = '기업 전체 재무정보이며 DC/AIDC 부문 실적·사업 참여·계약·신용등급을 뜻하지 않습니다. 누적·당기 구분과 단위는 공시 원문을 확인하세요.'


@lru_cache(maxsize=1)
def registry():
    path = Path(__file__).resolve().parents[1] / 'fixtures' / 'dart_company_registry.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'companies': [], 'generated_at': None}


def registry_candidates(query):
    data = registry()
    def norm(value):
        return re.sub(r'[^a-z0-9가-힣]', '', value.lower().replace('주식회사', '').replace('(주)', ''))
    needle = norm(query)
    matches = []
    if len(needle) >= 2:
        for item in data['companies']:
            names = [item['name'], item['english_name'], *item['aliases']]
            exact = any(norm(name) == needle for name in names)
            if exact or any(needle in norm(name) for name in names):
                matches.append({**item, 'match': 'exact_name_or_alias' if exact else 'name_candidate'})
    matches.sort(key=lambda item: (item['match'] != 'exact_name_or_alias', item['name']))
    return {'candidates': copy.deepcopy(matches[:20]), 'registry_as_of': data['generated_at'],
            'registry_note': '기존 DART 스킬 기업 목록의 시점 보존본입니다. 후보 선택 후 공식 법인명을 확인하세요. 현재 상장 여부를 보증하지 않습니다.'}


class DartVault(WindowsVault):
    def _target(self, provider):
        if provider != 'dart':
            raise ValueError('DART 인증키만 지원합니다.')
        return f'AIDC-ATLAS:{self.namespace}:dart'


def official_request(endpoint, params, key):
    if endpoint not in ('company.json', 'fnlttSinglAcnt.json'):
        raise ValueError('허용하지 않은 DART 요청입니다.')
    url = 'https://opendart.fss.or.kr/api/' + endpoint + '?' + urlencode({**params, 'crtfc_key': key})
    try:
        raw = request_bytes(url, allowed_hosts={'opendart.fss.or.kr'}, timeout=15, max_bytes=2_000_000)
        result = json.loads(raw)
    except Exception:
        # Never echo the credential-bearing URL, response body or exception.
        raise ValueError('DART 연결 실패: 인증서·프록시·네트워크를 확인하세요. 인증서 검증은 유지합니다.') from None
    if not isinstance(result, dict):
        raise ValueError('DART 응답 형식이 올바르지 않습니다.')
    code = result.get('status')
    if code != '000':
        descriptions = {'010': '인증키를 확인하세요.', '011': '사용할 수 없는 인증키입니다.',
                        '013': '해당 기간 공시 자료가 없습니다.', '020': 'DART 요청 한도에 도달했습니다.'}
        raise ValueError('DART: ' + descriptions.get(code, '공식 서비스 응답을 확인하세요.'))
    return result


def validate_report(record):
    if not isinstance(record, dict) or record.get('basis') != 'official_dart_selected_period':
        raise ValueError('DART 저장 근거가 올바르지 않습니다.')
    if not re.fullmatch(r'\d{8}', str(record.get('corp_code', ''))):
        raise ValueError('DART 법인 식별자가 올바르지 않습니다.')
    if record.get('report_code') not in REPORTS or record.get('fs_div') not in ('CFS', 'OFS'):
        raise ValueError('DART 기간·재무제표 구분을 확인하세요.')
    if not re.fullmatch(r'20\d{2}', str(record.get('year', ''))) or int(record['year']) < 2015:
        raise ValueError('DART 사업연도를 확인하세요.')
    if not isinstance(record.get('accounts'), list) or not 1 <= len(record['accounts']) <= 30:
        raise ValueError('DART 재무계정 근거가 없습니다.')
    for row in record['accounts']:
        if not isinstance(row, dict) or row.get('account_nm') not in ACCOUNTS or not re.fullmatch(r'\d{14}', str(row.get('rcept_no', ''))):
            raise ValueError('DART 계정·접수번호를 확인하세요.')
        if row.get('source_url') != 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + row['rcept_no']:
            raise ValueError('DART 원문 링크를 확인하세요.')


class DartCompany:
    def __init__(self, repo, namespace, reader, vault=None, fetch=None, clock=None):
        self.repo, self.reader = repo, reader
        self.vault = vault or DartVault(namespace)
        self.fetch, self.clock = fetch or official_request, clock or time.monotonic
        self.lock = threading.Lock()
        self.previews = {}

    def key(self):
        # A DART key is independent of all personal/corporate AI keys.
        try:
            registered = self.vault.read('dart')
        except ValueError:
            if os.environ.get('DART_API_KEY'):
                return os.environ['DART_API_KEY']
            raise
        return registered or os.environ.get('DART_API_KEY')

    def workspace(self, ds, cid, query=None):
        company = ds.get('companies', {}).get(cid)
        if not company:
            raise ValueError('선택한 기업을 찾을 수 없습니다.')
        try:
            present, error = bool(self.key()), None
        except ValueError:
            present, error = False, 'credential_unavailable'
        history = sorted((copy.deepcopy(r) for r in ds.get('dart_reports', {}).values()
                          if r['company_id'] == cid), key=lambda r: r['saved_at'], reverse=True)
        reports = [r for r in history if not r.get('withdrawn_at')]
        return {'company_id': cid, 'company_name': company['name'], 'reports': reports[:20],
                'withdrawn_reports': [r for r in history if r.get('withdrawn_at')][:20],
                'credential_present': present, 'credential_error': error, 'ai_tokens': 0,
                'note': LIMIT_NOTE, 'latest_available_period_verified': False,
                **registry_candidates((query if isinstance(query, str) else company['name'])[:100])}

    def connect(self, payload):
        if set(payload) != {'api_key'} or not isinstance(payload['api_key'], str) or not re.fullmatch(r'[a-zA-Z0-9]{40}', payload['api_key']):
            raise ValueError('DART에서 발급한 40자리 인증키를 입력하세요. AI 키와 다릅니다.')
        self.vault.write('dart', payload['api_key'])
        return {'status': 'registered', 'authentication_verified': False, 'ai_tokens': 0}

    def preview(self, payload):
        if set(payload) != {'company_id', 'corp_code', 'year', 'report_code', 'fs_div'}:
            raise ValueError('DART 조회 항목을 확인하세요.')
        cid, corp = payload['company_id'], payload['corp_code']
        ds = self.reader()['datasets']
        company = ds.get('companies', {}).get(cid)
        if not company or not isinstance(corp, str) or not re.fullmatch(r'\d{8}', corp):
            raise ValueError('선택 기업과 DART 8자리 법인 고유번호를 확인하세요.')
        year, report, basis = str(payload['year']), payload['report_code'], payload['fs_div']
        if not re.fullmatch(r'20\d{2}', year) or not 2015 <= int(year) <= int(now()[:4]) or report not in REPORTS or basis not in ('CFS', 'OFS'):
            raise ValueError('사업연도·보고서·연결/별도를 선택하세요.')
        if not self.lock.acquire(blocking=False):
            raise ValueError('DART 조회가 진행 중입니다. 중복 조회하지 않습니다.')
        try:
            key = self.key()
            if not key:
                raise ValueError('이 PC의 DART 인증키를 먼저 등록하세요.')
            identity = self.fetch('company.json', {'corp_code': corp}, key)
            if not identity.get('corp_name') or identity.get('corp_code', corp) != corp:
                raise ValueError('DART 법인 응답이 일치하지 않습니다.')
            financials = self.fetch('fnlttSinglAcnt.json', {'corp_code': corp, 'bsns_year': year, 'reprt_code': report}, key)
            accounts = []
            for row in financials.get('list', []):
                if (row.get('corp_code') != corp or str(row.get('bsns_year')) != year or row.get('reprt_code') != report
                        or row.get('fs_div') != basis or row.get('account_nm') not in ACCOUNTS):
                    continue
                item = {k: str(row.get(k) or '')[:300] for k in ('account_nm', 'sj_div', 'thstrm_nm', 'thstrm_amount',
                        'thstrm_add_amount', 'frmtrm_nm', 'frmtrm_amount', 'frmtrm_add_amount', 'currency', 'rcept_no')}
                item['source_url'] = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + item['rcept_no']
                accounts.append(item)
            record = {'company_id': cid, 'atlas_company_name': company['name'], 'corp_code': corp,
                      'corp_name': str(identity['corp_name'])[:200], 'stock_code': str(identity.get('stock_code') or '')[:10],
                      'year': year, 'report_code': report, 'report_label': REPORTS[report], 'fs_div': basis,
                      'accounts': accounts, 'fetched_at': now(), 'basis': 'official_dart_selected_period'}
            validate_report(record)
            token = uuid.uuid4().hex
            self.previews = {k: v for k, v in self.previews.items() if self.clock() - v['at'] < 600}
            if len(self.previews) >= 20:
                self.previews.pop(next(iter(self.previews)))
            self.previews[token] = {'at': self.clock(), 'record': record}
            return {'preview_id': token, 'report': copy.deepcopy(record), 'requires_identity_confirmation': True,
                    'note': LIMIT_NOTE, 'ai_tokens': 0, 'official_requests': 2}
        finally:
            self.lock.release()

    def save(self, payload):
        if set(payload) != {'preview_id', 'confirm_same_legal_entity'} or payload['confirm_same_legal_entity'] is not True:
            raise ValueError('선택 기업과 공시 법인이 동일한지 명시적으로 확인하세요.')
        prepared = self.previews.get(payload.get('preview_id'))
        if not prepared or self.clock() - prepared['at'] >= 600:
            raise ValueError('DART 미리보기가 만료되었습니다. 다시 조회하세요.')
        report = copy.deepcopy(prepared['record'])
        report.update(id='dart-' + hashlib.sha256(encoded(report)).hexdigest()[:24], saved_at=now(), identity_confirmed=True)
        def edit(ds):
            company = ds.get('companies', {}).get(report['company_id'])
            if not company or company['name'] != report['atlas_company_name']:
                raise ValueError('선택 기업 정보가 바뀌었습니다. 다시 조회하세요.')
            for old in ds.get('dart_reports', {}).values():
                if old['company_id'] == report['company_id'] and not old.get('withdrawn_at') and old['corp_code'] != report['corp_code']:
                    raise ValueError('기존 공시 법인과 다릅니다. 모회사·자회사를 자동 대체하지 않습니다.')
            if ds.get('dart_reports', {}).get(report['id'], {}).get('withdrawn_at'):
                raise ValueError('해제한 미리보기는 재사용하지 않습니다. 새로 조회하세요.')
            ds.setdefault('dart_reports', {}).setdefault(report['id'], report)
        snap = self.repo.transact(edit)
        return {'status': 'saved', 'report_id': report['id'], 'snapshot_id': snap['generation'], 'ai_tokens': 0}

    def withdraw(self, payload):
        if set(payload) != {'company_id', 'report_id', 'confirm_withdraw'} or payload['confirm_withdraw'] is not True:
            raise ValueError('공시 연결 해제 대상을 확인하세요.')
        def edit(ds):
            record = ds.get('dart_reports', {}).get(payload['report_id'])
            if not record or record['company_id'] != payload['company_id']:
                raise ValueError('선택 기업의 공시 근거를 찾을 수 없습니다.')
            record.setdefault('withdrawn_at', now())
        snap = self.repo.transact(edit)
        return {'status': 'withdrawn_original_preserved', 'snapshot_id': snap['generation']}
