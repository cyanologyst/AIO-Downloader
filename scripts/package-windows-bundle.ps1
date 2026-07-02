param(
  [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$RootPath = $Root.Path

function Find-Tool($Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $cmd) {
    throw "Required Windows bundle tool not found on PATH: $Name"
  }
  return $cmd.Source
}

$BundleBin = Join-Path $Root "build\bundle-bin"
if (Test-Path $BundleBin) {
  Remove-Item -LiteralPath $BundleBin -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BundleBin | Out-Null

$aria2 = Find-Tool "aria2c"
$ffmpeg = Find-Tool "ffmpeg"
$deno = Find-Tool "deno"
$ffprobe = Join-Path (Split-Path -Parent $ffmpeg) "ffprobe.exe"

Copy-Item -LiteralPath $aria2 -Destination (Join-Path $BundleBin "aria2c.exe") -Force
Copy-Item -LiteralPath $ffmpeg -Destination (Join-Path $BundleBin "ffmpeg.exe") -Force
if (Test-Path -LiteralPath $ffprobe) {
  Copy-Item -LiteralPath $ffprobe -Destination (Join-Path $BundleBin "ffprobe.exe") -Force
}
Copy-Item -LiteralPath $deno -Destination (Join-Path $BundleBin "deno.exe") -Force

$IconPath = Join-Path $Root "aio_downloader_icon_windows.ico"
if (-not (Test-Path -LiteralPath $IconPath)) {
  throw "Windows icon was expected but not found: $IconPath"
}
$WebViewLib = python -c "import pathlib, webview; print(pathlib.Path(webview.__file__).resolve().parent / 'lib')"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $WebViewLib)) {
  throw "Could not locate pywebview lib directory."
}

$PyInstallerArgs = @(
  "--noconfirm",
  "--clean",
  "--windowed",
  "--name", "AIO Downloader",
  "--icon", $IconPath,
  "--distpath", "dist\windows",
  "--workpath", "build\pyinstaller",
  "--specpath", "build\pyinstaller",
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
  "--add-binary", "$BundleBin\aria2c.exe;bin",
  "--add-binary", "$BundleBin\ffmpeg.exe;bin",
  "--add-binary", "$BundleBin\deno.exe;bin",
  "--add-binary", "$WebViewLib\Microsoft.Web.WebView2.Core.dll;.",
  "--add-binary", "$WebViewLib\Microsoft.Web.WebView2.WinForms.dll;.",
  "--add-binary", "$WebViewLib\runtimes\win-x64\native\WebView2Loader.dll;win-x64",
  "--add-binary", "$WebViewLib\runtimes\win-x86\native\WebView2Loader.dll;win-x86",
  "--add-binary", "$WebViewLib\runtimes\win-arm64\native\WebView2Loader.dll;win-arm64"
)

if (Test-Path -LiteralPath (Join-Path $BundleBin "ffprobe.exe")) {
  $PyInstallerArgs += @("--add-binary", "$BundleBin\ffprobe.exe;bin")
}

$PyInstallerArgs += "app\launcher.py"

python -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) {
  throw "pip failed with exit code $LASTEXITCODE"
}
python -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$AppDir = Join-Path $Root "dist\windows\AIO Downloader"
$PackageDir = Join-Path $Root "dist\AIO-Downloader-Windows-v$Version"
$Zip = Join-Path $Root "dist\AIO-Downloader-Windows-v$Version-ready-to-use.zip"

if (Test-Path $PackageDir) {
  Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Copy-Item -LiteralPath $AppDir -Destination $PackageDir -Recurse -Force
$PackagedAppDir = Join-Path $PackageDir "AIO Downloader"
foreach ($runtimeDir in @("Download", "logs", "config", "webview")) {
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
AIO Downloader Windows v$Version
================================

How to run
----------
Double-click "AIO Downloader\AIO Downloader.exe".

Bundled runtime/tools
---------------------
- Python runtime and Python packages used by the app
- yt-dlp launcher
- spotDL launcher
- aria2c
- ffmpeg / ffprobe
- deno

User data location
------------------
The packaged app stores settings, logs, batches, and webview data under:
%LOCALAPPDATA%\AIO Downloader

Known Windows release notes
---------------------------
- Microsoft Edge WebView2 Runtime is required by pywebview. Most Windows 10/11 installs already include it.
- The executable is currently unsigned, so Windows SmartScreen or antivirus software may warn on first launch.
- Some websites still require valid cookies, login access, or network availability.
"@
Set-Content -LiteralPath (Join-Path $PackageDir "RELEASE-NOTES.txt") -Value $ReleaseNotes -Encoding UTF8

if (Test-Path $Zip) {
  Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Created $Zip"
