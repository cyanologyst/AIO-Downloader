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

  $winget = Get-Command "winget" -ErrorAction SilentlyContinue
  if ($winget) {
    Write-Host "Inno Setup 6 was not found. Installing it with winget..."
    & $winget.Source install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
      throw "winget failed to install Inno Setup 6 with exit code $LASTEXITCODE"
    }
    foreach ($candidate in $candidates) {
      if (Test-Path -LiteralPath $candidate) {
        return $candidate
      }
    }
    $cmd = Get-Command "iscc" -ErrorAction SilentlyContinue
    if ($cmd) {
      return $cmd.Source
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

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\generate-installer-assets.ps1")
if ($LASTEXITCODE -ne 0) {
  throw "Installer branding asset generation failed with exit code $LASTEXITCODE"
}

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
$IconFile = Join-Path $Root "aio_downloader_icon_windows.ico"
if (-not (Test-Path -LiteralPath $IconFile)) {
  throw "Windows icon was expected but not found: $IconFile"
}
$WizardImageFile = Join-Path $Root "build\installer-branding\wizard-sidebar.bmp"
$WizardSmallImageFile = Join-Path $Root "build\installer-branding\wizard-small.bmp"
if (-not (Test-Path -LiteralPath $WizardImageFile) -or -not (Test-Path -LiteralPath $WizardSmallImageFile)) {
  throw "Installer branding assets were expected but not found."
}

& $Iscc `
  "/DMyAppVersion=$Version" `
  "/DPackageDir=$PackageDir" `
  "/DOutputDir=$OutputDir" `
  "/DWebView2Setup=$WebView2Setup" `
  "/DIconFile=$IconFile" `
  "/DWizardImageFile=$WizardImageFile" `
  "/DWizardSmallImageFile=$WizardSmallImageFile" `
  $Iss

if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$SetupExe = Join-Path $OutputDir "AIO-Downloader-Setup-v$Version.exe"
if (-not (Test-Path -LiteralPath $SetupExe)) {
  throw "Setup was expected but not found: $SetupExe"
}

Write-Host "Created $SetupExe"
