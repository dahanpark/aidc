"""Disposable RSS-only process; no repository, credentials or inference access."""
import base64
import json
import subprocess
import sys
from pathlib import Path
from .network import NetworkError, error_info

DEADLINE_SECONDS=20
CODES={'dns','network','timeout','tls','tls_certificate','connection','ca_bundle_invalid',
       'proxy_configuration','response_limit','feed_validation'}|{f'http_{n}' for n in range(100,600)}


def fetch(url,timeout=DEADLINE_SECONDS):
    from .collector import validate_feed_url,MAX_BYTES
    validate_feed_url(url)
    try:
        result=subprocess.run([sys.executable,'-B','-m','backend.feed_worker'],
            input=json.dumps({'url':url}).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            timeout=timeout,cwd=Path(__file__).resolve().parents[1],close_fds=True)
    except subprocess.TimeoutExpired as exc:
        # run() kills and waits for the child; no stuck DNS/read thread survives.
        raise NetworkError('feed_deadline','RSS 요청 전체 시간 제한에 도달했습니다. 회사 DNS·프록시·방화벽을 확인하세요.') from None
    if result.returncode or len(result.stdout)>4_100_000:
        raise NetworkError('feed_worker','RSS 통신 프로세스가 정상 응답하지 못했습니다.')
    try:
        response=json.loads(result.stdout)
        if not isinstance(response,dict):raise ValueError('invalid')
        if response.get('ok') is not True:
            code=response.get('code')
            raise NetworkError(code if code in CODES else 'feed_worker','RSS 연결을 확인하지 못했습니다. 오류 코드와 네트워크 진단을 확인하세요.')
        raw=base64.b64decode(response['body'],validate=True)
        if len(raw)>MAX_BYTES:raise ValueError('limit')
        return raw
    except NetworkError:raise
    except (ValueError,TypeError,KeyError):
        raise NetworkError('feed_worker','RSS 통신 프로세스 응답 형식을 확인하지 못했습니다.') from None


def main():
    from .collector import fetch_public_feed
    try:
        request=json.loads(sys.stdin.buffer.read(20_000))
        raw=fetch_public_feed(request['url'])
        response={'ok':True,'body':base64.b64encode(raw).decode('ascii')}
    except Exception as error:
        code=error_info(error)['code'] if isinstance(error,OSError) else 'feed_validation'
        response={'ok':False,'code':code if code in CODES else 'network'}
    sys.stdout.buffer.write(json.dumps(response).encode())


if __name__=='__main__':main()
