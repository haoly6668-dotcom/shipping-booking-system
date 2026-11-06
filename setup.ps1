param([string]$Server = 'localhost', [string]$Database = 'HarborBooking')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($Database -eq 'HarborBooking' -and (Test-Path -LiteralPath '.env')) {
    Write-Host 'Existing configuration found. No database changes made. Run start.cmd.'
    exit 0
}
& '.\.venv\Scripts\python.exe' scripts/setup_database.py --server $Server --database $Database
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed; review the message above.' }
