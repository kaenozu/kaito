; kaito installer script for Inno Setup 6
; Build: ISCC.exe installer\kaito.iss
; Override version: ISCC.exe /DMyAppVersion=0.10.1 installer\kaito.iss

#define MyAppName "kaito"
#ifndef MyAppVersion
  #define MyAppVersion "0.10.1"
#endif
#define MyAppPublisher "kaenozu"
#define MyAppURL "https://github.com/kaenozu/kaito"
#define MyAppExeName "kaito.exe"

[Setup]
AppId={{B8F4C3D2-E1A0-4F6B-9C8D-7E5A3B2C1D0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=kaito-installer-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=no
CloseApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\kaito.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\bundled\7-ZIP-LICENSE.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\bundled\SHA256SUMS"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\bundled\SOURCE-PACKAGE.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\kaito_compress"; ValueType: string; ValueName: ""; ValueData: "kaitoで圧縮"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\kaito_compress\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" --compress ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\kaito_compress"; ValueType: string; ValueName: ""; ValueData: "kaitoで圧縮"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\kaito_compress\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" --compress ""%1"""; Flags: uninsdeletekey
