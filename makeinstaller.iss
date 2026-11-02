; http://www.jrsoftware.org/ishelp/index.php

[Setup]
AppName="PyWinSystem"
AppVerName="PyWinSystem 0.1.0"
DefaultDirName="{autopf}\PyWinSystem"
DefaultGroupName="PyWinSystem"
AppVersion="0.1.0"
AppCopyright="Taehong Kim"
AppPublisher="Taehong Kim"
UninstallDisplayIcon="{app}\PyWinSystem.exe"
Compression=lzma2/max
SolidCompression=yes
OutputDir=".dist"
OutputBaseFilename="PyWinSystem-0.1.0-Setup"
; VersionInfoVersion="0.1.0"
VersionInfoProductVersion="0.1.0"
VersionInfoCompany="Taehong Kim"
VersionInfoCopyright="Taehong Kim"
ArchitecturesInstallIn64BitMode="x64compatible"
CloseApplications=yes
RestartApplications=no

[Files]
Source: ".dist\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\PyWinSystem"; Filename: "{app}\PyWinSystem.exe"
Name: "{commondesktop}\PyWinSystem"; Filename: "{app}\PyWinSystem.exe"

[Run]
Filename: "{app}\PyWinSystem.exe"; Description: "Launch PyWinSystem"; Flags: nowait postinstall skipifsilent
