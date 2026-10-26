"""Explicit bounded strategy inference, shared AI budget and JSON run ledger."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from . import ai_analysis, strategy
from .network import error_info
from .repository import now

VERSION = 'strategy-analysis-1'


def _prepare(ds,payload):
    profile=ds.get('settings',{}).get('app',{}).get('ai',{})
    if 'strategy' not in profile.get('enabled_tasks',['extract','compare','briefing','classify','strategy']):
        raise ValueError('SETTINGS에서 전략표 AI 역할을 활성화하세요.')
    maximum=profile.get('max_input_chars',8000)
    if type(maximum) is not int or not 500<=maximum<=100000:
        raise ValueError('AI 입력 문자 한도를 확인하세요.')
    output_limit=profile.get('max_output_tokens',1200)
    if type(output_limit) is not int or not 128<=output_limit<=16000:
        raise ValueError('AI 출력 토큰 한도를 확인하세요.')
    text_limit=profile.get('article_text_chars',1200)
    prepared=strategy.prepare_analysis(ds,payload,{'max_articles_per_run':profile.get('max_articles_per_run',3),
                                                'max_input_chars':maximum,'article_text_chars':text_limit})
    # Matches infer's literal system+schema and JSON payload serialization.
    input_chars=len(strategy.SYSTEM)+len(json.dumps(strategy.RESULT_SCHEMA,ensure_ascii=False))+len(json.dumps(prepared['input_data'],ensure_ascii=False))
    if input_chars>maximum:
        raise ValueError('시스템 지시·결과 스키마를 포함한 AI 입력 문자 한도를 초과했습니다. 기사를 줄이세요.')
    return prepared,profile,{'max_articles_per_run':profile.get('max_articles_per_run',3),
                             'max_input_chars':maximum,'daily_call_limit':profile.get('daily_call_limit',10),
                             'article_text_chars':text_limit,'max_output_tokens':output_limit},input_chars


def preview(connection,payload):
    with connection.lock:
        prepared,_,limits,input_chars=_prepare(connection.read_snapshot()['datasets'],payload)
        return {**deepcopy(prepared),'limits':limits,'input_chars':input_chars,'inference_called':False}


def _today_run(record,day):
    if record.get('status') not in ('completed','failed','running','interrupted'):return False
    try:
        stamp=datetime.fromisoformat(record.get('created_at','').replace('Z','+00:00'))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc).date()==day
    except (ValueError,TypeError):return False


def _safe_usage(usage):
    if not isinstance(usage,dict):return {}
    return {k:v for k,v in usage.items() if isinstance(k,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',k) and type(v) is int and v>=0}


def _failure(exc):
    code=error_info(exc).get('code','network')
    if not isinstance(code,str) or not re.fullmatch(r'[a-z0-9_]{1,40}',code):code='network'
    if isinstance(exc,(ValueError,KeyError,TypeError,StopIteration)):code='strategy_validation'
    return {'code':code,'message':'전략표 AI 응답/근거 검증에 실패했습니다. 자동 재호출과 원본 병합은 하지 않았습니다.'}


def _assert_current(records,prepared):
    current=strategy.prepare_analysis(records,{'board_id':prepared['board_id'],'company_id':prepared['company_id'],
            'row_ids':prepared['row_ids'],'article_ids':prepared['article_ids']},
            {'max_articles_per_run':20,'max_input_chars':100000,
             'article_text_chars':prepared.get('article_text_chars',2400)})
    if current['input_hash']!=prepared['input_hash'] or current['source_hash']!=prepared['source_hash']:
        raise ValueError('전략 분석 중 공개 입력이 바뀌었습니다. 새 입력을 확인한 뒤 명시 실행하세요.')


def run(connection,payload):
    if not isinstance(payload,dict) or payload.get('consent_public_metadata') is not True:
        raise ValueError('공개 기사 표본 전송과 API 사용량 발생을 확인하세요.')
    with connection.lock:
        ds=connection.read_snapshot()['datasets']
        prepared,profile,limits,input_chars=_prepare(ds,payload)
        if not connection.status(ds).get('connected'):
            raise ValueError('이 PC에서 AI를 연결한 뒤 전략표를 분석하세요.')
        key=connection.credential(profile)
        if not key:raise ValueError('이 PC의 AI 인증정보를 찾을 수 없습니다.')
        stamp=hashlib.sha256(json.dumps({'version':VERSION,'strategy_version':strategy.VERSION,
             'provider':profile.get('provider'),'model':profile.get('model'),
             'prepared_hash':prepared['input_hash'],'source_hash':prepared['source_hash'],
             'max_output_tokens':limits['max_output_tokens'],'input':prepared['input_data'],
             'schema':strategy.RESULT_SCHEMA,'system':strategy.SYSTEM},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        cached=next((r for r in ds.get('ai_runs',{}).values() if r.get('task')=='strategy' and r.get('input_hash')==stamp and r.get('status')=='completed'),None)
        if cached:
            restored=[]
            def restore(records):
                _assert_current(records,prepared)
                restored.extend(strategy.validate_and_store(records,prepared,cached['result'],
                            {'provider':cached['provider'],'model':cached['model'],'usage':cached.get('usage',{})}))
            connection.repo.transact(restore)
            return {'status':'cached','run_id':cached['id'],'inference_called':False,
                    'summary_ids':[s['id'] for s in restored],'input_chars':input_chars}
        maximum=limits['daily_call_limit']
        if type(maximum) is not int or not 1<=maximum<=500:raise ValueError('일일 AI 호출 한도를 확인하세요.')
        day=datetime.now(timezone.utc).date()
        if sum(_today_run(r,day) for r in ds.get('ai_runs',{}).values())>=maximum:
            raise ValueError('오늘 AI 호출 한도에 도달했습니다. 기존 분석·실패·실행 중 요청도 포함합니다.')
        ident='ai-'+uuid.uuid4().hex
        record={'id':ident,'task':'strategy','created_at':now(),'status':'running','version':VERSION,
                'input_hash':stamp,'strategy_input_hash':prepared['input_hash'],'provider':profile['provider'],
                'model':profile['model'],'board_id':prepared['board_id'],'company_id':prepared['company_id'],
                'row_ids':prepared['row_ids'],'article_ids':prepared['article_ids'],'input_chars':input_chars,
                'input_scope':'title_and_public_rss_description','input_snapshots':deepcopy(prepared['articles']),
                'full_text_verified':False,'auto_merge':False,'usage':None}
        connection.repo.transact(lambda records:records.setdefault('ai_runs',{}).update({ident:deepcopy(record)}))
        try:
            result,usage=ai_analysis.infer(profile,key,prepared['input_data'],schema=strategy.RESULT_SCHEMA,system=strategy.SYSTEM)
            record['usage']=_safe_usage(usage)
            def finish(records):
                _assert_current(records,prepared)
                summaries=strategy.validate_and_store(records,prepared,result,
                            {'provider':profile['provider'],'model':profile['model'],'usage':record['usage']})
                record.update(status='completed',finished_at=now(),result=result,summary_ids=[s['id'] for s in summaries])
                records.setdefault('ai_runs',{})[ident]=deepcopy(record)
                records.setdefault('settings',{}).setdefault('app',{}).setdefault('ai',{})['inference_verified_at']=record['finished_at']
            connection.repo.transact(finish)
        except Exception as exc:
            # Failed validation is persisted without raw provider output or exception text.
            record.pop('result',None);record.pop('summary_ids',None)
            record.update(status='failed',finished_at=now(),error=_failure(exc))
            connection.repo.transact(lambda records:records.setdefault('ai_runs',{}).update({ident:deepcopy(record)}))
        return {'status':record['status'],'run_id':ident,'inference_called':True,'input_chars':input_chars,
                'summary_ids':record.get('summary_ids',[]),'usage':record.get('usage'),'error':record.get('error')}
