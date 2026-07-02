#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif

#ifndef PackageDir
#define PackageDir "..\..\dist\AIO-Downloader-Windows-v" + MyAppVersion
#endif

#ifndef OutputDir
#define OutputDir "..\..\dist"
#endif

#ifndef WebView2Setup
#define WebView2Setup "..\..\build\installer\MicrosoftEdgeWebView2Setup.exe"
#endif

#ifndef IconFile
#define IconFile "..\..\aio_downloader_icon_windows.ico"
#endif

#ifndef WizardImageFile
#define WizardImageFile "..\..\build\installer-branding\wizard-sidebar.bmp"
#endif

#ifndef WizardSmallImageFile
#define WizardSmallImageFile "..\..\build\installer-branding\wizard-small.bmp"
#endif

[Setup]
AppId={{4F21F5D6-3F45-4EA4-9EAF-D656E9D2A0D6}
AppName=AIO Downloader
AppVersion={#MyAppVersion}
AppVerName=AIO Downloader {#MyAppVersion}
AppPublisher=cyanologyst
AppPublisherURL=https://github.com/cyanologyst/AIO-Downloader
AppSupportURL=https://github.com/cyanologyst/AIO-Downloader/issues
AppUpdatesURL=https://github.com/cyanologyst/AIO-Downloader/releases
AppContact=https://github.com/cyanologyst/AIO-Downloader/issues
AppComments=Native local downloader dashboard for authorized videos, playlists, torrents, Spotify, manga, galleries, and batch collections.
DefaultDirName={localappdata}\Programs\AIO Downloader
DefaultGroupName=AIO Downloader
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=AIO-Downloader-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile={#WizardImageFile}
WizardSmallImageFile={#WizardSmallImageFile}
WizardImageStretch=no
WizardImageBackColor=$00141006
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\AIO Downloader.exe
SetupIconFile={#IconFile}
SetupLogging=yes
VersionInfoCompany=cyanologyst
VersionInfoDescription=AIO Downloader Setup
VersionInfoProductName=AIO Downloader
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to AIO Downloader
WelcomeLabel2=Install the native local dashboard for authorized videos, playlists, torrents, Spotify, manga, galleries, and batch collections.%n%nAIO Downloader runs locally, opens as a real Windows app window, and keeps settings under your user profile.
FinishedHeadingLabel=AIO Downloader is ready
FinishedLabel=Setup has finished installing AIO Downloader.%n%nYou can launch it now, or find it later in the Start Menu.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PackageDir}\AIO Downloader\*"; DestDir: "{app}"; Excludes: "Download\*,logs\*,config\*,webview\*,*.rpc-secret,*.session"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PackageDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PackageDir}\RELEASE-NOTES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#WebView2Setup}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2Setup.exe"; Flags: ignoreversion deleteafterinstall

[Icons]
Name: "{autoprograms}\AIO Downloader"; Filename: "{app}\AIO Downloader.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AIO Downloader"; Filename: "{app}\AIO Downloader.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Check: not IsWebView2Installed; Flags: runhidden waituntilterminated
Filename: "{app}\AIO Downloader.exe"; Description: "Launch AIO Downloader"; Flags: nowait postinstall skipifsilent

[Code]
var
  ProductPage: TWizardPage;

function IsWebView2Installed: Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

procedure AddInfoLine(Page: TWizardPage; Top: Integer; Icon: String; Title: String; Body: String);
var
  TitleLabel: TNewStaticText;
  BodyLabel: TNewStaticText;
begin
  TitleLabel := TNewStaticText.Create(Page);
  TitleLabel.Parent := Page.Surface;
  TitleLabel.Left := ScaleX(8);
  TitleLabel.Top := ScaleY(Top);
  TitleLabel.Width := Page.SurfaceWidth - ScaleX(16);
  TitleLabel.Height := ScaleY(18);
  TitleLabel.Caption := Icon + '  ' + Title;
  TitleLabel.Font.Style := [fsBold];

  BodyLabel := TNewStaticText.Create(Page);
  BodyLabel.Parent := Page.Surface;
  BodyLabel.Left := ScaleX(29);
  BodyLabel.Top := ScaleY(Top + 21);
  BodyLabel.Width := Page.SurfaceWidth - ScaleX(40);
  BodyLabel.Height := ScaleY(34);
  BodyLabel.AutoSize := False;
  BodyLabel.WordWrap := True;
  BodyLabel.Caption := Body;
end;

procedure InitializeWizard;
begin
  ProductPage :=
    CreateCustomPage(
      wpSelectDir,
      'What this installer prepares',
      'AIO Downloader is packaged to feel native while keeping the downloader engine local.'
    );

  AddInfoLine(
    ProductPage,
    4,
    '✓',
    'App runtime included',
    'Installs the Windows app, Python runtime, app libraries, and built-in yt-dlp / spotDL launchers.'
  );
  AddInfoLine(
    ProductPage,
    68,
    '✓',
    'Tools install themselves',
    'If aria2c, ffmpeg/ffprobe, or Deno are missing, AIO Downloader downloads them into its own tools folder on first launch.'
  );
  AddInfoLine(
    ProductPage,
    132,
    '✓',
    'Native desktop shell',
    'AIO Downloader opens as its own app window with custom controls instead of a browser tab.'
  );
  AddInfoLine(
    ProductPage,
    196,
    '✓',
    'Local user data',
    'Settings, logs, queue history, and WebView data stay under your Windows user profile.'
  );
  AddInfoLine(
    ProductPage,
    260,
    '!',
    'First-launch trust note',
    'This build is currently unsigned, so Windows SmartScreen may warn until a code-signing certificate is added.'
  );
end;
