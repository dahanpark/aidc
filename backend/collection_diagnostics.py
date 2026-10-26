"""Read-only, allowlisted collection diagnostics; no queries or private data."""
from collections import Counter
from .network import network_environment, error_info
from .repository import now

COUNTERS = ('request_count', 'completed_windows', 'total_windows', 'new_articles',
            'duplicate_count', 'returned_items', 'parsed_items', 'relevant_items',
            'uncertain_items', 'out_of_scope_items', 'rejected_items')
ERROR_CODES = {'dns','network','timeout','tls','tls_certificate','connection',
               'ca_bundle_invalid','proxy_configuration','response_limit','feed_validation',
               'worker_internal','worker_validation'} | {f'http_{n}' for n in range(100,600)}


def worker_failure(error):
    """Never persist exception text, URLs, credentials or record contents."""
    if isinstance(error, OSError):
        detail = error_info(error)
        if detail['code'] in ERROR_CODES:
            return {'code':detail['code'], 'message':'수집 통신 오류가 발생했습니다. 오류 코드와 사내망 연결 진단을 확인하세요.'}
    if isinstance(error, ValueError):
        return {'code':'worker_validation', 'message':'수집 자료 검증에 실패했습니다. 원본을 보존하고 진단 정보를 확인하세요.'}
    return {'code':'worker_internal', 'message':'수집 처리 중 내부 오류가 발생했습니다. 원본과 작업 조건을 보존했습니다.'}


def workspace(ds, *, worker_alive=False, lock_held=False):
    errors = Counter()
    for coverage in ds.get('news_coverage',{}).values():
        if coverage.get('status') == 'failed':
            code = coverage.get('error_code')
            errors[code if code in ERROR_CODES else 'unknown'] += 1
    jobs=[]
    for j in sorted(ds.get('news_jobs',{}).values(), key=lambda j:j.get('updated_at',''), reverse=True)[:10]:
        job={k:j.get(k) for k in ('id','status','created_at','updated_at','stop_reason','can_resume')}
        job.update({k:j.get(k,0) for k in COUNTERS})
        job['pending_windows']=len(j.get('pending_windows',[]))
        job['failed_windows']=len(j.get('failed_windows',[]))
        job['error_code']=j.get('error_code') if j.get('error_code') in ERROR_CODES else None
        orphan=j.get('status') in ('running','queued') and not worker_alive and not lock_held
        job['worker_missing']=orphan
        if orphan: result='worker_missing'
        elif j.get('status') in ('running','queued'): result='running'
        elif j.get('status')=='failed' or j.get('stop_reason')=='worker_error': result='failed'
        elif j.get('failed_windows'): result='source_errors'
        elif j.get('new_articles',0): result='saved'
        elif j.get('duplicate_count',0): result='duplicates_only'
        elif j.get('returned_items',0): result='no_matching_metadata'
        else: result='no_results'
        job['result_code']=result
        jobs.append(job)
    return {'checked_at':now(),'capability':'collection_diagnostics_v1',
            'worker_alive':bool(worker_alive),'collection_lock_held':bool(lock_held),
            'environment':network_environment(),'jobs':jobs,'coverage_error_counts':dict(errors),
            'note':'상태 조회는 수집·저장·재시작을 실행하지 않습니다. 이 PC의 결과이며 다른 PC/회사망의 결과를 대신하지 않습니다.'}
