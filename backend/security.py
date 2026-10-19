"""Shared URL boundaries: credentials never belong in JSON or public exports."""
import ipaddress
import re
from urllib.parse import parse_qsl, unquote, urlsplit

SECRET_KEYS = {
    'key', 'apikey', 'accesskey', 'accesskeyid', 'accesstoken', 'refreshtoken',
    'idtoken', 'token', 'authtoken', 'oauthtoken', 'oauthcode', 'authorization',
    'auth', 'password', 'passwd', 'pwd', 'secret', 'clientsecret', 'credential',
    'credentials', 'signature', 'sig', 'session', 'sessionid', 'sessiontoken',
}


def credential_parameter(key):
    for _ in range(3):
        decoded = unquote(key)
        if decoded == key:
            break
        key = decoded
    normalized = re.sub(r'[^a-z0-9]', '', key.lower())
    return (normalized in SECRET_KEYS or
            normalized.startswith(('xamz', 'xgoog')) and
            any(word in normalized for word in ('credential', 'signature', 'token')) or
            normalized.endswith(('accesstoken', 'apikey', 'password', 'clientsecret', 'authtoken')))


def assert_safe_url(value, allow_private=False):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('인증정보 없는 HTTP(S) URL을 입력하십시오.')
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError('invalid')
        parsed.port
        if not allow_private:
            host = parsed.hostname.lower().rstrip('.')
            if host in ('localhost', 'localhost.localdomain') or host.endswith(('.local', '.internal', '.localhost')) or ('.' not in host and ':' not in host):
                raise ValueError('private')
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if host.replace('.', '').isdigit() or host.startswith('0x'):
                    raise ValueError('private')
            else:
                if not address.is_global:
                    raise ValueError('private')
        # Fragments may carry OAuth tokens even though HTTP does not send them.
        params = parse_qsl(parsed.query, keep_blank_values=True)
        params += parse_qsl(parsed.fragment.lstrip('?'), keep_blank_values=True)
        if any(credential_parameter(key) for key, _ in params):
            raise ValueError('credential')
    except (ValueError, UnicodeError):
        # Fixed message: never echo the rejected URL or secret value.
        raise ValueError('URL에서 인증 파라미터·비밀값을 제거하십시오. 공개 자료에는 공개 URL만 사용하십시오.') from None
    return value.strip()
