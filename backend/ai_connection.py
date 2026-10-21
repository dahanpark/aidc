"""Explicit per-PC API connection. No inference or cross-provider fallback."""
from __future__ import annotations
import json
import os
import re
import threading
from urllib.parse import urlsplit
from .credentials import WindowsVault, env_name, delete_environment
from .network import request_bytes, error_info
from .repository import now

PROVIDERS = {
    'openai': {'label': 'OpenAI', 'models_url': 'https://api.openai.com/v1/models',
               'recommended': ['gpt-6-luna', 'gpt-5.4-mini']},
    'anthropic': {'label': 'Anthropic · Claude', 'models_url': 'https://api.anthropic.com/v1/models',
                  'recommended': ['claude-haiku-5-5', 'claude-haiku-4-5-20251001']},
    'google': {'label': 'Google · Gemini', 'models_url': 'https://generativelanguage.googleapis.com/v1beta/models',
               'recommended': ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']}}


def infer_provider(secret):
    if secret.startswith('sk-ant-'):
        return 'anthropic'
    if secret.startswith(('sk-proj-', 'sk-svcacct-')):
        return 'openai'
    if secret.startswith('AIza'):
        return 'google'
    return None


def headers_for(provider, key):
    headers = {'Content-Type': 'application/json', 'User-Agent': 'AIDC-ATLAS/0.4'}
    if provider == 'google':
        headers['x-goog-api-key'] = key
    elif provider == 'anthropic':
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
    else:
        headers['Authorization'] = 'Bearer ' + key
    return headers


class AIConnection:
    def __init__(self, repo, namespace, vault=None, reader=None):
        self.repo = repo
        self.vault = vault or WindowsVault(namespace)
        self.read_snapshot = reader or repo.snapshot
        self.lock = threading.RLock()

    def credential(self, profile):
        provider = profile.get('provider')
        if provider not in PROVIDERS:
            return None
        reference = profile.get('secret_ref', '')
        if reference.startswith('env:'):
            name = env_name(reference)
            if name != f'ATLAS_AI_{provider.upper()}_KEY':
                return None
            return os.environ.get(name)
        if reference == 'credential:' + provider:
            return self.vault.read(provider)
        return None

    def status(self, ds):
        profile = ds.get('settings', {}).get('app', {}).get('ai', {})
        try:
            present = bool(self.credential(profile))
        except ValueError:
            present = False
        return {**profile, 'credential_present': present,
                'connected': bool(profile.get('enabled') and profile.get('verified_at') and present),
                'provider_label': PROVIDERS.get(profile.get('provider'), {}).get('label', '미연결'),
                'quality_verified': False,
                'role_without_ai': '공개 RSS 수집·규칙 분류·정확 중복 제거·관계도·기사·스크랩·명시 확인',
                'role_with_ai': '공개 기사 근거 추출·동일 사업 후보 비교·출처 연결 동향/점검 요약 · 확정 병합은 별도 확인'}

    def connect(self, payload):
        with self.lock:
            return self._connect(payload)

    def _connect(self, payload):
        old = self.read_snapshot()['datasets'].get('settings', {}).get('app', {}).get('ai', {})
        key = payload.get('key', '')
        provider = payload.get('provider', '')
        reference = payload.get('secret_ref', '')
        if not isinstance(key, str) or (key and not re.fullmatch(r'[A-Za-z0-9_.-]{20,1200}', key)):
            raise ValueError('API 키 형식을 확인하세요. 공백·URL·헤더를 입력하지 마세요.')
        guess = infer_provider(key)
        if provider and provider not in PROVIDERS:
            raise ValueError('지원하는 AI 제공사를 선택하세요.')
        if guess and provider and guess != provider:
            raise ValueError('키 형식과 선택한 제공사가 다릅니다. 키를 전송하지 않았습니다.')
        provider = provider or guess
        if not provider:
            return {'status': 'provider_required', 'sent_to_provider': False,
                    'message': '키 형식만으로 제공사를 구분할 수 없습니다. 제공사를 하나 선택하세요.'}
        if reference:
            if key:
                raise ValueError('키 입력과 환경변수 참조 중 하나를 선택하세요.')
            name = env_name(reference)
            if name != f'ATLAS_AI_{provider.upper()}_KEY':
                raise ValueError('선택한 제공사의 전용 환경변수 참조를 사용하세요.')
            key = os.environ.get(name, '')
        if not key:
            if old.get('provider') == provider:
                key = self.credential(old) or ''
                reference = old.get('secret_ref', '')
        if not key or not re.fullmatch(r'[A-Za-z0-9_.-]{20,1200}', key):
            raise ValueError('사용 가능한 API 키가 없습니다. 이 PC에서 키를 등록하세요.')
        url = PROVIDERS[provider]['models_url']
        try:
            response = json.loads(request_bytes(url, allowed_hosts={urlsplit(url).hostname},
                                  headers=headers_for(provider, key), max_bytes=1_000_000))
            models = []
            for item in response.get('models' if provider == 'google' else 'data', []):
                model = item.get('name' if provider == 'google' else 'id', '').removeprefix('models/')
                if re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', model):
                    if provider != 'google' or 'generateContent' in item.get('supportedGenerationMethods', []):
                        models.append(model)
        except Exception as exc:
            detail = error_info(exc)
            return {'status': 'failed', 'connected': False, 'provider': provider, **detail,
                    'inference_called': False}
        recommended = next((m for m in PROVIDERS[provider]['recommended'] if m in models), '')
        previous_model = old.get('model') if old.get('provider') == provider and old.get('model') in models else ''
        selected = payload.get('model') or previous_model or recommended
        if selected and selected not in models:
            raise ValueError('해당 키로 확인한 모델 목록에서 모델을 선택하세요.')
        previous_secret = None
        if not reference.startswith('env:'):
            previous_secret = self.vault.read(provider)
            self.vault.write(provider, key)
            reference = 'credential:' + provider
        profile = {'provider': provider, 'model': selected, 'secret_ref': reference,
                   'enabled': bool(selected), 'verified_at': now(), 'available_models': sorted(set(models)),
                   'analysis_mode': 'manual_public_metadata', 'daily_call_limit': old.get('daily_call_limit', 50),
                   'max_articles_per_run': old.get('max_articles_per_run', 5), 'inference_verified_at': None}
        try:
            self.repo.transact(lambda ds: ds.setdefault('settings', {}).setdefault('app', {'id': 'app'}).update(ai=profile))
        except Exception:
            if reference.startswith('credential:'):
                if previous_secret:
                    self.vault.write(provider, previous_secret)
                else:
                    self.vault.delete(provider)
            raise
        return {'status': 'connected' if selected else 'model_required', 'connected': bool(selected),
                'provider': provider, 'model': selected, 'available_models': profile['available_models'],
                'inference_called': False, 'message': '키 인증과 모델 목록을 확인했습니다. 기사 분석은 별도 실행하며 사용량이 발생할 수 있습니다.'}

    def disconnect(self, *, forget=False, delete_env=False):
        with self.lock:
            snapshot = self.read_snapshot()['datasets']
            profile = snapshot.get('settings', {}).get('app', {}).get('ai', {})
            provider = profile.get('provider')
            reference = profile.get('secret_ref', '')
            # Disable first. A failed OS deletion must not leave analysis enabled.
            def disable(ds):
                current = ds.setdefault('settings', {}).setdefault('app', {'id': 'app'}).setdefault('ai', {})
                current['enabled'] = False
            self.repo.transact(disable)
            result = {'status': 'disconnected', 'provider_key_revoked': False}
            if forget and reference.startswith('credential:') and provider in PROVIDERS:
                self.vault.delete(provider)
                result['credential_deleted'] = True
            if delete_env and reference.startswith('env:'):
                result.update(delete_environment(reference))
            if forget:
                self.repo.transact(lambda ds: ds['settings']['app']['ai'].update(
                    secret_ref='', verified_at=None, inference_verified_at=None))
            return result
