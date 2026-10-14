; Inno Setup script for YT Playlist Downloader
; Created by Muhammad Farooq. © 2026 Muhammad Farooq. All rights reserved.
;
; Build the app first with PyInstaller (see README), then compile:
;   ISCC.exe installer\setup.iss
; Optional overrides:
;   ISCC.exe /DSourceDir="path\to\YT Playlist Downloader" /DOutputDir="path\to\output" installer\setup.iss
;
; IMPORTANT: never change AppId. Windows uses it to recognise upgrades and the uninstaller.

#define MyAppName "YT Playlist Downloader"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Muhammad Farooq"
#define MyAppURL "https://github.com/farooq831/YT_Playlist_Downloader"
#define MyAppExeName "YT Playlist Downloader.exe"

#ifndef SourceDir
  #define SourceDir "..\dist\YT Playlist Downloader"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{C79515A6-674F-4BD3-9FD4-AED61E28CAE0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases/latest
AppCopyright=© 2026 Muhammad Farooq. All rights reserved.

; Per-user install by default (no admin password); "all users" is offered when possible.
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

OutputDir={#OutputDir}
OutputBaseFilename=YT-Playlist-Downloader-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoCopyright=© 2026 Muhammad Farooq
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Download YouTube playlists as MP4"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Download YouTube playlists as MP4"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove files the app may have created inside its install folder (downloads are never stored there).
Type: filesandordirs; Name: "{app}"
