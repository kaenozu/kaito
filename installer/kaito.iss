; kaito installer script for Inno Setup
; Build: ISCC.exe installer\kaito.iss

#define MyAppName "kaito"
#define MyAppVersion "0.9.0"
#define MyAppPublisher "kaenozu"
#define MyAppURL "https://github.com/kaenozu/kaito"
#define MyAppExeName "kaito.exe"

[Setup]
AppId={{B8F4C3D2-E1A0-4F6B-9C8D-7E5A3B2C1D0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=kaito-installer-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ChangesEnvironment=no
CloseApplications=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\kaito.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Registry]
; kaitoで解凍 (ZIP)
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
; kaitoで解凍 (RAR)
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.rar\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
; kaitoで解凍 (7z)
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.7z\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
; kaitoで解凍 フォールバック (全ファイル – カスタムProgID対策)
Root: HKCU; Subkey: "Software\Classes\*\shell\kaito_extract"; ValueType: string; ValueName: ""; ValueData: "kaitoで解凍"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\kaito_extract\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" ""%1"""; Flags: uninsdeletekey
; kaitoで圧縮 (ファイル)
Root: HKCU; Subkey: "Software\Classes\*\shell\kaito_compress"; ValueType: string; ValueName: ""; ValueData: "kaitoで圧縮"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\kaito_compress\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" --compress ""%1"""; Flags: uninsdeletekey
; kaitoで圧縮 (フォルダ)
Root: HKCU; Subkey: "Software\Classes\Directory\shell\kaito_compress"; ValueType: string; ValueName: ""; ValueData: "kaitoで圧縮"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\kaito_compress\command"; ValueType: string; ValueName: ""; ValueData: """{app}\kaito.exe"" --compress ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\kaito.exe"; Parameters: "--install-context-menu"; Flags: runhidden

[UninstallRun]
Filename: "{app}\kaito.exe"; Parameters: "--uninstall-context-menu"; Flags: runhidden
