"""RSS-only Windows system TLS retry. No certificate overrides or AI credentials."""
import base64
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import getproxies_environment, proxy_bypass_environment
from .network import NetworkError

# A fresh, noninteractive .NET process uses the Windows certificate-chain engine.
# Input stays on stdin; neither URLs nor proxy settings appear in command lines.
SCRIPT=r'''
$ErrorActionPreference='Stop'
$request=$null; $response=$null; $stream=$null; $buffer=$null
try {
  $inputData=[Console]::In.ReadToEnd() | ConvertFrom-Json
  $uri=[Uri]$inputData.url
  if ($uri.Scheme -ne 'https' -or $uri.Port -ne 443 -or $uri.UserInfo -or $uri.Fragment) { throw 'target' }
  $allowed=($uri.Host -eq 'news.google.com' -and $uri.AbsolutePath -eq '/rss/search') -or ($uri.AbsoluteUri -eq 'https://www.datacenterdynamics.com/en/rss/')
  if (-not $allowed) { throw 'target' }
  if ($null -ne [Net.ServicePointManager]::ServerCertificateValidationCallback) { throw 'validation_override' }
  $request=[Net.HttpWebRequest]::Create($uri)
  $request.Method='GET'
  $request.AllowAutoRedirect=$false
  $request.UseDefaultCredentials=$false
  $request.UserAgent='AIDC-ATLAS/0.4'
  $request.Timeout=[int]$inputData.timeout_ms
  $request.ReadWriteTimeout=[int]$inputData.timeout_ms
  $request.AutomaticDecompression=[Net.DecompressionMethods]::GZip -bor [Net.DecompressionMethods]::Deflate
  if ($inputData.proxy_mode -eq 'direct') { $request.Proxy=$null }
  elseif ($inputData.proxy) {
    $proxyUri=[Uri]$inputData.proxy
    if ($proxyUri.Scheme -notin @('http','https') -or -not $proxyUri.Host -or $proxyUri.UserInfo) { throw 'proxy_configuration' }
    $request.Proxy=New-Object Net.WebProxy($proxyUri)
  } else { $request.Proxy=[Net.WebRequest]::GetSystemWebProxy() }
  if ($null -ne $request.Proxy) { $request.Proxy.Credentials=$null }
  $response=$request.GetResponse()
  if ([int]$response.StatusCode -ne 200) { throw ('http_'+[int]$response.StatusCode) }
  $stream=$response.GetResponseStream()
  $buffer=New-Object IO.MemoryStream
  $block=New-Object byte[] 16384
  while (($count=$stream.Read($block,0,$block.Length)) -gt 0) {
    if ($buffer.Length+$count -gt 3000000) { throw 'response_limit' }
    $buffer.Write($block,0,$count)
  }
  $result=@{ok=$true;body=[Convert]::ToBase64String($buffer.ToArray())}
} catch {
  $errorValue=$_.Exception; $code='network'
  for ($i=0;$i -lt 8 -and $null -ne $errorValue;$i++) {
    if ($errorValue -is [Net.WebException]) {
      if ($null -ne $errorValue.Response) { $code='http_'+[int]$errorValue.Response.StatusCode; $errorValue.Response.Close() }
      elseif ($errorValue.Status -eq [Net.WebExceptionStatus]::TrustFailure) { $code='tls_certificate' }
      elseif ($errorValue.Status -eq [Net.WebExceptionStatus]::SecureChannelFailure) { $code='tls' }
      elseif ($errorValue.Status -eq [Net.WebExceptionStatus]::Timeout) { $code='timeout' }
      elseif ($errorValue.Status -in @([Net.WebExceptionStatus]::NameResolutionFailure,[Net.WebExceptionStatus]::ProxyNameResolutionFailure)) { $code='dns' }
      break
    }
    if ($errorValue.Message -in @('response_limit','proxy_configuration')) { $code=$errorValue.Message; break }
    if ($errorValue.Message -match '^http_[1-5][0-9][0-9]$') { $code=$errorValue.Message; break }
    $errorValue=$errorValue.InnerException
  }
  $result=@{ok=$false;code=$code}
} finally {
  if ($null -ne $stream) {$stream.Dispose()}
  if ($null -ne $buffer) {$buffer.Dispose()}
  if ($null -ne $response) {$response.Close()}
  if ($null -ne $request) {$request.Abort()}
}
[Console]::Out.Write(($result | ConvertTo-Json -Compress))
'''


def _proxy_config(url):
    # Environment parsing is local string work. PAC/registry resolution stays
    # inside the killable .NET process, never on the server thread.
    proxies=getproxies_environment()
    if proxies.get('no') and proxy_bypass_environment(urlsplit(url).hostname,proxies):
        return {'mode':'direct','url':None}
    return {'mode':'explicit','url':proxies['https']} if proxies.get('https') else {'mode':'system','url':None}


def fetch(url,timeout):
    from .collector import validate_feed_url
    from .feed_worker import CODES
    validate_feed_url(url)
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    if os.name!='nt' or not executable.is_file():
        raise NetworkError('tls_certificate','Windows 인증서 신뢰 경로를 사용할 수 없습니다. 회사 CA 구성을 확인하세요.',transport='windows_unavailable')
    config=_proxy_config(url)
    proxy=config['url']
    if proxy and '://' not in proxy:proxy='http://'+proxy
    if proxy and urlsplit(proxy).username is not None:
        raise NetworkError('proxy_configuration','인증 프록시 구성을 IT 담당자와 확인하세요. 인증정보를 자동 전송하지 않았습니다.')
    try:
        result=subprocess.run([str(executable),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(SCRIPT.encode('utf-16-le')).decode()],
            input=json.dumps({'url':url,'proxy':proxy,'proxy_mode':config['mode'],'timeout_ms':max(1,int(timeout*1000))}).encode(),
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise NetworkError('feed_deadline','Windows 인증서 경로의 RSS 요청 전체 시간 제한에 도달했습니다.') from None
    except OSError:
        raise NetworkError('feed_worker','Windows 시스템 연결 프로세스를 실행하지 못했습니다.') from None
    try:
        if result.returncode or len(result.stdout)>4_100_000:raise ValueError('protocol')
        value=json.loads(result.stdout)
        if not isinstance(value,dict):raise ValueError('protocol')
        if value.get('ok') is not True:
            code=value.get('code')
            raise NetworkError(code if code in CODES else 'network','Windows 인증서·시스템 프록시 경로도 연결하지 못했습니다. 표시된 오류 코드와 회사 IT 구성을 확인하세요.')
        body=base64.b64decode(value['body'],validate=True)
        if len(body)>3_000_000:raise ValueError('limit')
        return body
    except NetworkError:raise
    except (ValueError,TypeError,KeyError):
        raise NetworkError('feed_worker','Windows RSS 응답 형식을 확인하지 못했습니다.') from None
