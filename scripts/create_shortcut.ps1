$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskLauncher = Join-Path $PSScriptRoot 'start_atlas.ps1'
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'run_atlas.py'))) { throw 'Application entry point missing.' }
$taskShortcutPath = Join-Path $taskRoot 'AIDC ATLAS.lnk'
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcut = $taskShell.CreateShortcut($taskShortcutPath)
$taskShortcut.TargetPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskShortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $taskLauncher + '"'
$taskShortcut.WorkingDirectory = $taskRoot
$taskShortcut.Description = 'AIDC ATLAS - local intelligence pilot'
$taskShortcut.WindowStyle = 7
$taskShortcut.Save()
Write-Output $taskShortcutPath
