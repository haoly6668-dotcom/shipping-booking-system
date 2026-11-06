$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot 'logs\server.pid'
if (!(Test-Path -LiteralPath $pidFile)) { Write-Host 'No managed background server PID found. Stop a foreground server with Ctrl+C.'; exit 0 }
$serverProcessId = [int](Get-Content -LiteralPath $pidFile)
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$serverProcessId"
$expectedScript = Join-Path $projectRoot 'run.py'
if ($serverProcess -and $serverProcess.CommandLine.Contains($expectedScript)) {
    Stop-Process -Id $serverProcessId
    Write-Host 'Harbor booking background server stopped.'
} elseif ($serverProcess) {
    throw 'PID is occupied by a different process. No process was stopped.'
}
Remove-Item -LiteralPath $pidFile
