$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskInstance = Join-Path $taskRoot 'runtime\instance.json'
if (-not (Test-Path -LiteralPath $taskInstance)) { Write-Output 'AIDC ATLAS is not running.'; exit 0 }
$taskInfo = Get-Content -LiteralPath $taskInstance -Raw | ConvertFrom-Json
$taskState = Invoke-RestMethod -Uri ($taskInfo.url + 'api/session') -TimeoutSec 5 -Proxy $null
Invoke-RestMethod -Method Post -Uri ($taskInfo.url + 'api/shutdown') -Headers @{'X-Atlas-Token'=$taskState.csrf_token} -ContentType 'application/json' -Body '{}' -Proxy $null | Out-Null
Write-Output 'AIDC ATLAS stopped.'
