param(
  [string]$Version = "1.0.0",
  [switch]$RebuildBundle
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Find-Iscc {
  $cmd = Get-Command "iscc" -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
  )

  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }

  throw "Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup -e"
}

$PackageDir = Join-Path $Root "dist\AIO-Downloader-Windows-v$Version"
if ($RebuildBundle -or -not (Test-Path -LiteralPath (Join-Path $PackageDir "AIO Downloader\AIO Downloader.exe"))) {
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\package-windows-bundle.ps1") -Version $Version
  if ($LASTEXITCODE -ne 0) {
    throw "Windows bundle build failed with exit code $LASTEXITCODE"
  }
}

$InstallerBuildDir = Join-Path $Root "build\installer"
New-Item -ItemType Directory -Force -Path $InstallerBuildDir | Out-Null

$WebView2Setup = Join-Path $InstallerBuildDir "MicrosoftEdgeWebView2Setup.exe"
if (-not (Test-Path -LiteralPath $WebView2Setup)) {
  Invoke-WebRequest `
    -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
    -OutFile $WebView2Setup `
    -UseBasicParsing
}

$Iscc = Find-Iscc
$Iss = Join-Path $Root "installer\windows\AIO-Downloader.iss"
$OutputDir = Join-Path $Root "dist"

& $Iscc `
  "/DMyAppVersion=$Version" `
  "/DPackageDir=$PackageDir" `
  "/DOutputDir=$OutputDir" `
  "/DWebView2Setup=$WebView2Setup" `
  $Iss

if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$SetupExe = Join-Path $OutputDir "AIO-Downloader-Setup-v$Version.exe"
if (-not (Test-Path -LiteralPath $SetupExe)) {
  throw "Setup was expected but not found: $SetupExe"
}

Write-Host "Created $SetupExe"
