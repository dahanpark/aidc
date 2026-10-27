"""Bounded HTTPS transport: verified TLS, system proxies, redacted diagnostics.

Callers supply a fixed endpoint allowlist, never a URL received from an article.
Direct connections pin validated public DNS; a configured proxy resolves the
fixed destination. Redirects (including credential-bearing redirects) are denied.
"""
from __future__ import annotations
import http.client
import ipaddress
import os
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NetworkError(OSError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tls_context():
    context = ssl.create_default_context()
    bundle = os.environ.get('ATLAS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE')
    if bundle:
        try:
            context.load_verify_locations(cafile=bundle)
        except (OSError, ssl.SSLError) as exc:
            raise NetworkError('ca_bundle_invalid', '회사 CA 인증서 파일을 읽거나 검증하지 못했습니다.') from exc
    return context


def proxy_for(host):
    proxies = urllib.request.getproxies()
    # proxy_bypass honors NO_PROXY and Windows bypass lists.
    return None if urllib.request.proxy_bypass(host) else proxies.get('https')


def error_info(error):
    """Fixed diagnostics only: exception messages may contain credentials."""
    current = error
    for _ in range(6):
        if isinstance(current, NetworkError):
            return {'code': current.code, 'message': str(current)}
        if isinstance(current, ssl.SSLCertVerificationError):
            return {'code': 'tls_certificate', 'message': 'TLS 인증서 검증 실패 · 회사 루트 인증서/ATLAS_CA_BUNDLE을 확인하세요.'}
        if isinstance(current, urllib.error.HTTPError):
            code = current.code
            return {'code': f'http_{code}', 'message': {
                407: '프록시 인증 필요 · 회사 IT 부서의 인증 프록시 구성을 확인하세요.',
                403: '접근 차단 · 회사 방화벽 또는 제공사 허용 정책을 확인하세요.',
                429: '제공사 요청 한도 초과 · 잠시 후 재개하세요.',
                401: 'API 인증 실패 · 키와 제공사를 확인하세요.'}.get(code, f'제공사 HTTP {code} 응답')}
        if isinstance(current, socket.gaierror):
            return {'code': 'dns', 'message': 'DNS 이름 확인 실패 · 회사 DNS/프록시 설정을 확인하세요.'}
        if isinstance(current, (TimeoutError, socket.timeout)):
            return {'code': 'timeout', 'message': '접속 시간 초과 · 프록시/방화벽과 대상 도메인 허용을 확인하세요.'}
        if isinstance(current, ssl.SSLError):
            return {'code': 'tls', 'message': 'TLS 연결 실패 · 회사 프록시와 인증서 설정을 확인하세요.'}
        if isinstance(current, (ConnectionError, http.client.HTTPException)):
            return {'code': 'connection', 'message': '연결이 끊기거나 응답이 중단되었습니다. 회사 네트워크와 제공사 상태를 확인하세요.'}
        current = getattr(current, 'reason', None) or current.__cause__
        if not isinstance(current, BaseException):
            break
    return {'code': 'network', 'message': '연결 실패 · 회사 프록시·방화벽·인증서 설정을 확인하세요.'}


def request_bytes(url, *, allowed_hosts, headers=None, data=None, method='GET', timeout=15, max_bytes=3_000_000):
    target = urlsplit(url)
    if (target.scheme != 'https' or target.hostname not in allowed_hosts or
            target.port not in (None, 443) or target.username or target.password or target.fragment):
        raise ValueError('허용된 HTTPS 제공자만 요청할 수 있습니다.')
    context = tls_context()
    proxy = proxy_for(target.hostname)
    if proxy:
        # A proxy explicitly configured by this PC may have a private address.
        # TLS still authenticates the fixed public destination through CONNECT.
        address = urlsplit(proxy if '://' in proxy else 'http://' + proxy)
        if address.scheme not in ('http', 'https') or not address.hostname:
            raise NetworkError('proxy_configuration', 'HTTP/HTTPS 회사 프록시 설정을 확인하세요.')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy}),
                    urllib.request.HTTPSHandler(context=context), NoRedirect())
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        with opener.open(request, timeout=timeout) as response:
            content = response.read(max_bytes + 1)
    else:
        addresses = socket.getaddrinfo(target.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('공개 DNS 주소만 허용합니다.')
        last = None
        for address in addresses[:3]:
            conn = http.client.HTTPSConnection(target.hostname, timeout=timeout, context=context)
            try:
                sock = socket.create_connection(address[4][:2], timeout=timeout)
                try:
                    conn.sock = context.wrap_socket(sock, server_hostname=target.hostname)
                except BaseException:
                    sock.close()
                    raise
                path = target.path or '/'
                if target.query:
                    path += '?' + target.query
                conn.request(method, path, body=data, headers=headers or {})
                response = conn.getresponse()
                if response.status != 200:
                    raise urllib.error.HTTPError(url, response.status, 'Provider response', {}, None)
                content = response.read(max_bytes + 1)
                break
            except (OSError, http.client.HTTPException) as exc:
                last = exc
                # Never replay paid inference after an uncertain POST outcome.
                if method != 'GET' or isinstance(exc, urllib.error.HTTPError):
                    raise
            finally:
                conn.close()
        else:
            raise last or OSError('Connection failed')
    if len(content) > max_bytes:
        raise NetworkError('response_limit', '제공사 응답 크기가 허용 범위를 초과했습니다.')
    return content


def network_environment():
    proxies = urllib.request.getproxies()
    pac = False
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
                pac = bool(winreg.QueryValueEx(key, 'AutoConfigURL')[0])
        except OSError:
            pass
    return {'https_proxy_configured': bool(proxies.get('https')),
            'custom_ca_configured': bool(os.environ.get('ATLAS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE')),
            'pac_detected': pac, 'tls_verification': True,
            'windows_system_tls_retry': os.name == 'nt',
            'note': '시스템/환경 HTTPS 프록시 사용. Windows에서는 Python 인증서 실패 시 Windows 기본 인증서·시스템 프록시 경로로 한 번 재시도합니다. 두 경로 합계 RSS 제한20초·TLS 검증 유지. Windows도 실패하면 PC 날짜·시간과 회사 CA/프록시를 IT 부서와 확인하세요. 통합인증을 자동 전송하지 않습니다.'}
