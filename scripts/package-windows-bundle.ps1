param(
  [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

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

$PyInstallerArgs = @(
  "--noconfirm",
  "--clean",
  "--windowed",
  "--name", "AIO Downloader",
  "--distpath", "dist\windows",
  "--workpath", "build\pyinstaller",
  "--specpath", "build\pyinstaller",
  "--collect-all", "webview",
  "--collect-all", "yt_dlp",
  "--collect-all", "hanime_plugin",
  "--collect-all", "spotdl",
  "--collect-all", "curl_cffi",
  "--collect-all", "certifi",
  "--collect-all", "clr_loader",
  "--collect-all", "pythonnet",
  "--hidden-import", "bottle",
  "--hidden-import", "proxy_tools",
  "--add-data", "app\web\templates;app\web\templates",
  "--add-data", "app\web\static;app\web\static",
  "--add-data", "assets;assets",
  "--add-binary", "$BundleBin\aria2c.exe;bin",
  "--add-binary", "$BundleBin\ffmpeg.exe;bin",
  "--add-binary", "$BundleBin\deno.exe;bin"
)

if (Test-Path -LiteralPath (Join-Path $BundleBin "ffprobe.exe")) {
  $PyInstallerArgs += @("--add-binary", "$BundleBin\ffprobe.exe;bin")
}

$PyInstallerArgs += "app\launcher.py"

python -m pip install --upgrade pyinstaller
python -m PyInstaller @PyInstallerArgs

$AppDir = Join-Path $Root "dist\windows\AIO Downloader"
$PackageDir = Join-Path $Root "dist\AIO-Downloader-Windows-v$Version"
$Zip = Join-Path $Root "dist\AIO-Downloader-Windows-v$Version-ready-to-use.zip"

if (Test-Path $PackageDir) {
  Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Copy-Item -LiteralPath $AppDir -Destination $PackageDir -Recurse -Force
Copy-Item -LiteralPath ".env.example" -Destination (Join-Path $PackageDir ".env.example") -Force
Copy-Item -LiteralPath "README.md" -Destination (Join-Path $PackageDir "README.md") -Force

if (Test-Path $Zip) {
  Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Created $Zip"
