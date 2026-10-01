; Inno Setup script for OSINT Hub.
; Compiled by build.bat:  ISCC.exe build\installer.iss
; Input:  dist\OSINTHub\  (PyInstaller output + tools\)
; Output: dist\installer\OSINTHub-Setup-<version>.exe

#define AppName "OSINT Hub"
#define AppVersion "1.0.0"
#define AppExe "OSINTHub.exe"

[Setup]
AppId={{6E1C2F7A-3B9D-4C5E-9A71-0F4D2B8C1E93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=OSINT Hub
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin rights); the user can choose "for all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=OSINTHub-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
; ISCC itself is 32-bit: run the compressor as a separate 64-bit process to avoid "Out of memory".
LZMAUseSeparateProcess=yes
WizardStyle=modern
InfoBeforeFile=disclaimer.txt
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\OSINTHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
; Licence texts are part of dist\OSINTHub (LICENSE.txt, THIRD_PARTY_NOTICES.md, licenses\).

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Runtime artefacts that may appear inside the install folder.
Type: filesandordirs; Name: "{app}\tools\spiderfoot\spiderfoot\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\OSINTHub');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Удалить историю сканов, настройки и журналы OSINT Hub?' + #13#10 + DataDir + #13#10#13#10 +
                'API-ключи в Диспетчере учётных данных Windows и экспортированные отчёты останутся.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
