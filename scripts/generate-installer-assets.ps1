param(
  [string]$OutputDir = "build\installer-branding"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$IconPath = Join-Path $Root "aio_downloader_icon_windows.ico"

$Out = Join-Path $Root $OutputDir
New-Item -ItemType Directory -Force -Path $Out | Out-Null

Add-Type -AssemblyName System.Drawing

function New-Brush($Color) {
  return [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml($Color))
}

function New-Pen($Color, [float]$Width = 1) {
  return [System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml($Color), $Width)
}

function Draw-RoundedRect($Graphics, $Pen, $Brush, [float]$X, [float]$Y, [float]$W, [float]$H, [float]$R) {
  $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
  $diameter = $R * 2
  $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
  $path.AddArc($X + $W - $diameter, $Y, $diameter, $diameter, 270, 90)
  $path.AddArc($X + $W - $diameter, $Y + $H - $diameter, $diameter, $diameter, 0, 90)
  $path.AddArc($X, $Y + $H - $diameter, $diameter, $diameter, 90, 90)
  $path.CloseFigure()
  if ($Brush) { $Graphics.FillPath($Brush, $path) }
  if ($Pen) { $Graphics.DrawPath($Pen, $path) }
  $path.Dispose()
}

function Save-Bmp($Bitmap, $Path) {
  $Bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Bmp)
  $Bitmap.Dispose()
}

$fontTitle = [System.Drawing.Font]::new("Segoe UI", 19, [System.Drawing.FontStyle]::Bold)
$fontLogo = [System.Drawing.Font]::new("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$fontBody = [System.Drawing.Font]::new("Segoe UI", 8.5, [System.Drawing.FontStyle]::Regular)
$fontMini = [System.Drawing.Font]::new("Segoe UI", 7.5, [System.Drawing.FontStyle]::Regular)

$sidebar = [System.Drawing.Bitmap]::new(164, 314)
$g = [System.Drawing.Graphics]::FromImage($sidebar)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
$rect = [System.Drawing.Rectangle]::new(0, 0, 164, 314)
$gradient = [System.Drawing.Drawing2D.LinearGradientBrush]::new($rect, [System.Drawing.ColorTranslator]::FromHtml("#06141D"), [System.Drawing.ColorTranslator]::FromHtml("#0D2429"), 75)
$g.FillRectangle($gradient, $rect)
$gradient.Dispose()

for ($i = 0; $i -lt 9; $i++) {
  $alpha = 22 + ($i * 4)
  $pen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb($alpha, 178, 255, 0), 1)
  $g.DrawLine($pen, 12 + ($i * 16), 314, 104 + ($i * 12), 0)
  $pen.Dispose()
}

$glow = New-Brush "#9DFF00"
$muted = New-Brush "#A8B6C3"
$white = New-Brush "#F4F7FA"
$panel = New-Brush "#071721"
$border = New-Pen "#244352" 1
$accentPen = New-Pen "#B2FF00" 2

$g.FillEllipse($glow, 18, 22, 12, 12)
$g.DrawString("AIO", $fontLogo, $glow, 38, 16)
$g.DrawString("Downloader", $fontLogo, $white, 38, 34)

Draw-RoundedRect $g $border $panel 18 78 128 72 14
$g.DrawString("Queue", $fontMini, $muted, 32, 92)
$g.DrawString("Batch", $fontMini, $muted, 32, 112)
$g.DrawString("Tools", $fontMini, $muted, 32, 132)
$g.DrawLine($accentPen, 92, 101, 128, 101)
$g.DrawLine($accentPen, 92, 121, 118, 121)
$g.DrawLine($accentPen, 92, 141, 136, 141)

Draw-RoundedRect $g $null (New-Brush "#B2FF00") 18 178 126 38 12
$g.DrawString("Ready to run", $fontBody, (New-Brush "#061018"), 42, 190)

$g.DrawString("Native window", $fontMini, $muted, 18, 238)
$g.DrawString("Auto tools", $fontMini, $muted, 18, 256)
$g.DrawString("No browser tab", $fontMini, $muted, 18, 274)

$g.Dispose()
Save-Bmp $sidebar (Join-Path $Out "wizard-sidebar.bmp")

$small = [System.Drawing.Bitmap]::new(55, 55)
$g = [System.Drawing.Graphics]::FromImage($small)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
$g.Clear([System.Drawing.Color]::White)
$iconBg = New-Brush "#07131C"
$iconBorder = New-Pen "#1D3542" 1
Draw-RoundedRect $g $iconBorder $iconBg 4 4 47 47 13
$limeGradientPath = [System.Drawing.Drawing2D.GraphicsPath]::new()
$limeGradientPath.AddEllipse(14, 14, 27, 27)
$limeGradient = [System.Drawing.Drawing2D.PathGradientBrush]::new($limeGradientPath)
$limeGradient.CenterColor = [System.Drawing.ColorTranslator]::FromHtml("#B7FF00")
$limeGradient.SurroundColors = @([System.Drawing.ColorTranslator]::FromHtml("#78FF00"))
$g.FillEllipse($limeGradient, 14, 14, 27, 27)
$cutout = New-Brush "#07131C"
$mark = [System.Drawing.Drawing2D.GraphicsPath]::new()
$mark.AddRectangle([System.Drawing.RectangleF]::new(24, 18, 7, 19))
$mark.AddArc(25, 18, 18, 19, -90, 180)
$mark.AddArc(25, 25, 18, 12, 90, -180)
$mark.CloseFigure()
$g.FillPath($cutout, $mark)
$mark.Dispose()
$limeGradient.Dispose()
$limeGradientPath.Dispose()
$iconBg.Dispose()
$iconBorder.Dispose()
$cutout.Dispose()
$g.Dispose()
Save-Bmp $small (Join-Path $Out "wizard-small.bmp")

$fontTitle.Dispose()
$fontLogo.Dispose()
$fontBody.Dispose()
$fontMini.Dispose()
$glow.Dispose()
$muted.Dispose()
$white.Dispose()
$panel.Dispose()
$border.Dispose()
$accentPen.Dispose()

Write-Host "Generated installer branding assets in $Out"
