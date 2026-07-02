param(
  [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$RootPath = $Root.Path

$IconPath = Join-Path $Root "aio_downloader_icon_windows.ico"
if (-not (Test-Path -LiteralPath $IconPath)) {
  throw "Windows icon was expected but not found: $IconPath"
}

$DistPath = "dist\windows-portable-lite"
$WorkPath = "build\pyinstaller-portable-lite"

$PyInstallerArgs = @(
  "--noconfirm",
  "--clean",
  "--windowed",
  "--name", "AIO Downloader",
  "--icon", $IconPath,
  "--distpath", $DistPath,
  "--workpath", $WorkPath,
  "--specpath", $WorkPath,
  "--collect-all", "webview",
  "--collect-all", "yt_dlp",
  "--collect-all", "hanime_plugin",
  "--collect-all", "spotdl",
  "--collect-all", "tls_client",
  "--collect-all", "pykakasi",
  "--collect-all", "curl_cffi",
  "--collect-all", "certifi",
  "--collect-all", "clr_loader",
  "--collect-all", "pythonnet",
  "--hidden-import", "bottle",
  "--hidden-import", "proxy_tools",
  "--add-data", "$RootPath\app\web\templates;app\web\templates",
  "--add-data", "$RootPath\app\web\static;app\web\static",
  "--add-data", "$RootPath\assets;assets",
  "app\launcher.py"
)

python -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) {
  throw "pip failed with exit code $LASTEXITCODE"
}

python -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$AppDir = Join-Path $Root "$DistPath\AIO Downloader"
$PackageDir = Join-Path $Root "dist\AIO-Downloader-Windows-Portable-Lite-v$Version"
$Zip = Join-Path $Root "dist\AIO-Downloader-Windows-Portable-Lite-v$Version.zip"

if (Test-Path $PackageDir) {
  Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Copy-Item -LiteralPath $AppDir -Destination $PackageDir -Recurse -Force

$PackagedAppDir = Join-Path $PackageDir "AIO Downloader"
Set-Content -LiteralPath (Join-Path $PackagedAppDir "PORTABLE_LITE") -Value "AIO Downloader portable-lite build. Missing external tools are installed into tools\bin on first launch." -Encoding UTF8

foreach ($runtimeDir in @("Download", "logs", "config", "webview", "tools")) {
  $candidate = Join-Path $PackagedAppDir $runtimeDir
  if (Test-Path -LiteralPath $candidate) {
    Remove-Item -LiteralPath $candidate -Recurse -Force
  }
}

Get-ChildItem -LiteralPath $PackagedAppDir -Recurse -Force -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "*.rpc-secret" -or $_.Name -like "*.session" } |
  Remove-Item -Force

Copy-Item -LiteralPath ".env.example" -Destination (Join-Path $PackageDir ".env.example") -Force
Copy-Item -LiteralPath "README.md" -Destination (Join-Path $PackageDir "README.md") -Force

$ReleaseNotes = @"
AIO Downloader Windows Portable Lite v$Version
==============================================

How to run
----------
1. Extract this zip to any normal writable folder.
2. Double-click "AIO Downloader\AIO Downloader.exe".

What is bundled
---------------
- The native Windows app shell
- Python runtime and Python packages used by AIO Downloader
- Built-in yt-dlp and spotDL launchers

What is installed automatically on first launch
-----------------------------------------------
If missing, the app downloads these tools into:
AIO Downloader\tools\bin

- aria2c
- ffmpeg / ffprobe
- deno

The app prepends that portable tools folder to its own process PATH and saves the tool paths in app settings.
It does not modify the user's global Windows PATH.

User data location
------------------
Settings, logs, batches, and webview data are stored under:
%LOCALAPPDATA%\AIO Downloader

Known Windows release notes
---------------------------
- Microsoft Edge WebView2 Runtime is required by pywebview. Most Windows 10/11 installs already include it.
- The executable is currently unsigned, so Windows SmartScreen or antivirus software may warn on first launch.
- First launch needs internet access if aria2c, ffmpeg, or deno are not already available.
- Some websites still require valid cookies, login access, or network availability.
"@
Set-Content -LiteralPath (Join-Path $PackageDir "RELEASE-NOTES.txt") -Value $ReleaseNotes -Encoding UTF8

if (Test-Path $Zip) {
  Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Created $Zip"
