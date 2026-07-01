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

[Setup]
AppId={{4F21F5D6-3F45-4EA4-9EAF-D656E9D2A0D6}
AppName=AIO Downloader
AppVersion={#MyAppVersion}
AppVerName=AIO Downloader {#MyAppVersion}
AppPublisher=cyanologyst
AppPublisherURL=https://github.com/cyanologyst/AIO-Downloader
AppSupportURL=https://github.com/cyanologyst/AIO-Downloader/issues
AppUpdatesURL=https://github.com/cyanologyst/AIO-Downloader/releases
DefaultDirName={localappdata}\Programs\AIO Downloader
DefaultGroupName=AIO Downloader
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=AIO-Downloader-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\AIO Downloader.exe
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

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
