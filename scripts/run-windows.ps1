param(
  [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example. Edit it if your tool paths need overrides." -ForegroundColor Yellow
}

if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not $SkipInstall) {
  & $Python -m pip install --upgrade pip
  & $Python -m pip install -r requirements.txt
}

Write-Host "Starting AIO Downloader at http://127.0.0.1:5050" -ForegroundColor Green
& $Python -m app.main
