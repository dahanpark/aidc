"""One-shot AI jobs. JSON receipts survive reconnects, never restart inference.

Business results remain in the existing versioned ai_runs/strategy datasets.
This local execution journal contains no keys, prompts, article text or notes.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import threading
import time
import uuid
from . import ai_analysis, ai_classification, ai_company_identity, strategy_analysis, strategy
from .repository import atomic_write, encoded, loads, now

TASKS = {'analysis': ai_analysis.analyse, 'classify': ai_classification.analyse,
         'company_identity': ai_company_identity.analyse, 'strategy': strategy_analysis.run}
ACTIVE = {'queued', 'submitted', 'running'}
TERMINAL = {'completed', 'cached', 'failed', 'uncertain', 'blocked'}
LIMIT_FIELDS = ('provider', 'model', 'max_articles_per_run', 'daily_call_limit',
                'max_input_chars', 'max_output_tokens', 'article_text_chars', 'enabled_tasks')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def prepare(ds, task, selection):
    """Exact bounded provider input, system/schema and budget contract."""
    if task not in TASKS:
        raise ValueError('지원하지 않는 AI 작업입니다.')
    profile = ds.get('settings', {}).get('app', {}).get('ai', {})
    if task == 'analysis':
        p = ai_analysis.prepare_analysis(ds, profile, selection.get('article_ids'))
        data, system, schema = p['input_data'], p['system'], ai_analysis.SCHEMA
        preview = {**p['preview'], **data}
        version = ai_analysis.VERSION
        provenance = p['source_hashes']
    elif task == 'strategy':
        p, _, limits, chars = strategy_analysis._prepare(ds, selection)
        data, system, schema = p['input_data'], strategy.SYSTEM, strategy.RESULT_SCHEMA
        preview = {**deepcopy(p), 'limits': limits, 'input_chars': chars}
        version = [strategy_analysis.VERSION, strategy.VERSION]
        provenance = [p['input_hash'], p['source_hash']]
    else:
        module = ai_classification if task == 'classify' else ai_company_identity
        data, preview = (module._prepare if task == 'classify' else module.prepare)(ds, profile, selection)
        system, schema, version = module.SYSTEM, module.SCHEMA, module.VERSION
        from .ai_cleanup import article_stamp
        provenance = {aid: article_stamp(ds['articles'][aid]) for aid in preview['article_ids']}
    contract = {'task': task, 'version': version, 'input_data': data, 'system': system, 'schema': schema,
                'limits': {key: profile.get(key) for key in LIMIT_FIELDS}, 'provenance': provenance, 'target_source_stamps': preview.get('target_source_stamps')}
    # The preview shows all bytes of the logical prompt and response contract.
    preview = {**preview, 'provider': profile.get('provider'), 'model': profile.get('model'),
               'system': system, 'response_schema': schema, 'expected_calls': 1,
               'max_output_tokens': profile.get('max_output_tokens', 1200),
               'automatic_retry': False, 'inference_called': False}
    return digest(contract), preview


def selection_for(task, raw):
    fields = ('article_ids', 'board_id', 'company_id', 'row_ids') if task == 'strategy' else ('article_ids',)
    if not isinstance(raw, dict) or set(raw) - set(fields):
        raise ValueError('AI 작업 선택 형식을 확인하세요.')
    if len(encoded(raw)) > 16000:
        raise ValueError('AI 작업 선택이 너무 큽니다.')
    return deepcopy(raw)


class GuardedConnection:
    """Recheck the exact consent against the snapshot used by existing inference."""
    def __init__(self, connection, task, selection, expected):
        self.connection, self.task, self.selection, self.expected = connection, task, selection, expected
        self.lock, self.repo = connection.lock, connection.repo

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def read_snapshot(self):
        snapshot = self.connection.read_snapshot()
        actual, _ = prepare(snapshot['datasets'], self.task, self.selection)
        if actual != self.expected:
            raise ValueError('전송 표본·제공사·모델·한도가 변경되었습니다. 새 미리보기에 동의하세요.')
        return snapshot


class AIJobs:
    def __init__(self, directory, connection, *, stop=None):
        self.directory = Path(directory)
        self.connection = connection
        self.stop = stop or threading.Event()
        self.lock = threading.RLock()
        self.previews, self.records, self.threads = {}, {}, {}
        self.issue = None
        # Journal failures disable inference, not article/read/scrap features.
        try:
            for path in self.directory.glob('job-*.json'):
                record = self._read(path)
                if record['id'] in self.records:
                    raise ValueError('Duplicate AI execution receipt')
                if record['status'] in ACTIVE:
                    self._persist(record, 'uncertain', reason='restart_no_resend')
                self.records[record['id']] = record
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.issue = {'code': 'ai_job_journal_unavailable',
                          'message': 'AI 작업 영수증을 검증할 수 없습니다. 원본을 보존하고 AI 새 실행만 중단합니다.'}

    def _read(self, path):
        envelope = loads(path.read_bytes())
        record = envelope.get('record', {})
        if envelope.get('sha256') != digest(record) or str(record.get('id')) + '.json' != path.name:
            raise ValueError('AI 작업 영수증 무결성을 확인하세요. 자동 복구·재전송하지 않습니다.')
        if record.get('status') not in ACTIVE | TERMINAL or not re.fullmatch(r'job-[a-f0-9]{32}', record.get('id', '')):
            raise ValueError('AI 작업 영수증 형식을 확인하세요.')
        return record

    def _persist(self, record, status, **fields):
        updated = deepcopy(record)
        updated.update(fields, status=status, updated_at=now())
        updated.setdefault('history', []).append({'status': status, 'at': updated['updated_at']})
        atomic_write(self.directory / (record['id'] + '.json'),
                     encoded({'record': updated, 'sha256': digest(updated)}))
        record.clear()
        record.update(updated)

    def preview(self, task, raw):
        if self.issue:
            raise ValueError(self.issue['message'])
        selection = selection_for(task, raw)
        # Never acquire the AI serialization lock here: another request may be
        # awaiting network/disk. A consistent verified snapshot is sufficient.
        ds = self.connection.read_snapshot()['datasets']
        if not self.connection.status(ds).get('connected'):
            raise ValueError('이 PC에서 AI를 연결하세요.')
        fingerprint, sample = prepare(ds, task, selection)
        ident = uuid.uuid4().hex
        with self.lock:
            self.previews = {k: v for k, v in self.previews.items() if v['expires'] > time.monotonic()}
            if len(self.previews) >= 32:
                raise ValueError('열린 AI 미리보기가 많습니다. 10분 뒤 다시 준비하세요.')
            self.previews[ident] = {'selection': selection, 'task': task, 'fingerprint': fingerprint,
                                    'expires': time.monotonic() + 600, 'sample': deepcopy(sample)}
        return {**sample, 'preview_id': ident, 'consent_digest': fingerprint}

    def submit(self, payload):
        if self.issue:
            raise ValueError(self.issue['message'])
        if payload.get('consent_public_metadata') is not True:
            raise ValueError('정확한 전송 표본과 API 사용량 발생을 확인하세요.')
        preview_id = payload.get('preview_id')
        if not isinstance(preview_id, str):
            raise ValueError('AI 미리보기를 먼저 준비하세요.')
        with self.lock:
            ticket = self.previews.get(preview_id)
            if not ticket or ticket['expires'] <= time.monotonic() or payload.get('consent_digest') != ticket['fingerprint']:
                raise ValueError('미리보기 유효기간·동의를 다시 확인하세요.')
            duplicate = next((r for r in self.records.values() if r['consent_digest'] == ticket['fingerprint']), None)
            if duplicate:
                # Failure/uncertain are deliberately not permission to retry.
                return {**self._public(duplicate), 'duplicate': True}
            if self.stop.is_set():
                raise ValueError('서버 종료 중입니다. AI를 실행하지 않았습니다.')
            if any(r['status'] in ACTIVE for r in self.records.values()):
                raise ValueError('이미 AI 작업이 진행 중입니다. 기존 작업 상태를 확인하세요.')
            ident = 'job-' + uuid.uuid4().hex
            r = {'id': ident, 'task': ticket['task'], 'consent_digest': ticket['fingerprint'],
                 'created_at': now(), 'provider': ticket['sample']['provider'], 'model': ticket['sample']['model'],
                 'max_output_tokens': ticket['sample']['max_output_tokens'], 'expected_calls': 1,
                 'automatic_retry': False, 'run_id': None, 'history': []}
            self._persist(r, 'queued')  # durable ID before thread/provider invocation
            self.records[ident] = r
            worker = threading.Thread(target=self._execute, args=(ident, deepcopy(ticket)),
                                      name='atlas-ai-job', daemon=True)
            self.threads[ident] = worker
            try:
                worker.start()
            except Exception:
                self._persist(r, 'blocked', reason='worker_start_failed')
                raise ValueError('작업 시작 실패. 자동 재전송하지 않습니다.') from None
            return self._public(r)

    def _execute(self, ident, ticket):
        try:
            with self.connection.lock:
                guard = GuardedConnection(self.connection, ticket['task'], ticket['selection'], ticket['fingerprint'])
                snapshot = guard.read_snapshot()  # before marking attempt, and again inside legacy function
                if not self.connection.status(snapshot['datasets']).get('connected') or self.stop.is_set():
                    raise ValueError('AI 연결 또는 서버 실행 상태가 바뀌었습니다.')
                with self.lock:
                    self._persist(self.records[ident], 'submitted', reason='may_be_saving_or_contacting_provider')
                # Legacy code records ai_runs before sending and enforces the
                # daily budget and evidence checks. No raw response goes here.
                result = TASKS[ticket['task']](guard, {**ticket['selection'], 'consent_public_metadata': True})
                status = result.get('status')
                if status not in ('completed', 'cached', 'failed'):
                    status = 'uncertain'
                with self.lock:
                    self._persist(self.records[ident], status, run_id=result.get('run_id'),
                                  inference_called=result.get('inference_called'),
                                  reason='see_saved_ai_run' if result.get('run_id') else 'result_unavailable')
        except Exception:
            # Exception text may contain credentials/provider messages. A
            # failure after submitted is uncertain, never eligible for resend.
            with self.lock:
                record = self.records[ident]
                self._persist(record, 'uncertain' if record['status'] in ('submitted', 'running') else 'blocked',
                              reason='execution_not_confirmed_no_retry')

    def _public(self, record):
        return {k: deepcopy(v) for k, v in record.items() if k not in ('history',)}

    def status(self, ident=None):
        with self.lock:
            if ident is not None:
                if not isinstance(ident, str) or ident not in self.records:
                    raise ValueError('AI 작업을 찾을 수 없습니다.')
                return self._public(self.records[ident])
            return {'jobs': [self._public(r) for r in sorted(self.records.values(),
                        key=lambda r: r['created_at'], reverse=True)[:50]], 'automatic_retry': False, 'issue': deepcopy(self.issue)}
