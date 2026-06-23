param(
  [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dist = Join-Path $Root "dist"
$Stage = Join-Path $Dist "AIO-Downloader-v$Version"
$Zip = Join-Path $Dist "AIO-Downloader-v$Version-portable-source.zip"

if (Test-Path $Stage) {
  Remove-Item -LiteralPath $Stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

$include = @(
  "app",
  "assets",
  "scripts",
  "tests",
  ".env.example",
  ".gitignore",
  "README.md",
  "pyproject.toml",
  "requirements.txt",
  "requirements-dev.txt"
)

foreach ($item in $include) {
  $source = Join-Path $Root $item
  if (Test-Path -LiteralPath $source) {
    Copy-Item -LiteralPath $source -Destination $Stage -Recurse -Force
  }
}

if (Test-Path $Zip) {
  Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Created $Zip"
