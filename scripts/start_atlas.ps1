param([switch]$NoBrowser, [ValidateRange(10,1800)][int]$ReadyTimeoutSeconds = 600)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskRuntime = Join-Path $taskRoot 'runtime'
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
try {
    $taskExisting = Join-Path $taskRuntime 'instance.json'
    if (Test-Path -LiteralPath $taskExisting) {
        try {
            $taskInfo = Get-Content -LiteralPath $taskExisting -Raw | ConvertFrom-Json
            $taskHealth = Invoke-RestMethod -Uri ($taskInfo.url + 'api/health') -TimeoutSec 1 -Proxy $null
            if ($taskHealth.app -eq 'aidc-atlas' -and $taskHealth.identity -eq $taskInfo.identity) {
                if (-not $NoBrowser) { Start-Process $taskInfo.url | Out-Null }
                Write-Output $taskInfo.url
                exit 0
            }
        } catch { }
    }
    $taskBundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $taskPython = $null
    if (Test-Path -LiteralPath $taskBundled) { $taskPython = $taskBundled }
    if (-not $taskPython) {
        $taskCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($taskCommand -and $taskCommand.Source -notlike '*\WindowsApps\*') { $taskPython = $taskCommand.Source }
    }
    if (-not $taskPython) { throw 'Python 3.10 or newer is required. Install Python and retry.' }
    $taskScript = Join-Path $taskRoot 'run_atlas.py'
    # Quote each argument for Windows paths containing spaces; no shell interpolation.
    $taskArguments = @(('"' + $taskScript + '"'), '--no-browser')
    Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRuntime 'startup.log') -RedirectStandardError (Join-Path $taskRuntime 'startup-error.log') | Out-Null
    $taskUrl = $null
    # The first archive-analysis migration verifies thousands of new JSON files.
    # A ready server is still reused immediately; allow OneDrive's first pass to finish.
    $taskDeadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $taskDeadline) {
        Start-Sleep -Milliseconds 150
        $taskInstance = Join-Path $taskRuntime 'instance.json'
        if (Test-Path -LiteralPath $taskInstance) {
            $taskInfo = Get-Content -LiteralPath $taskInstance -Raw | ConvertFrom-Json
            try {
                $taskHealth = Invoke-RestMethod -Uri ($taskInfo.url + 'api/health') -TimeoutSec 1 -Proxy $null
                if ($taskHealth.app -eq 'aidc-atlas' -and $taskHealth.identity -eq $taskInfo.identity) { $taskUrl = $taskInfo.url; break }
            } catch { }
        }
    }
    if (-not $taskUrl) { throw 'AIDC ATLAS did not become ready. See runtime/startup-error.log.' }
    Remove-Item -LiteralPath (Join-Path $taskRuntime 'launcher-error.txt') -Force -ErrorAction SilentlyContinue
    if (-not $NoBrowser) { Start-Process $taskUrl | Out-Null }
    Write-Output $taskUrl
} catch {
    $taskMessage = 'AIDC ATLAS start failed. Check Python 3.10+ and runtime/startup-error.log.'
    Set-Content -LiteralPath (Join-Path $taskRuntime 'launcher-error.txt') -Value $taskMessage -Encoding UTF8
    if (-not $NoBrowser) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($taskMessage, 'AIDC ATLAS') | Out-Null
    } else { Write-Error $taskMessage -ErrorAction Continue }
    exit 1
}
