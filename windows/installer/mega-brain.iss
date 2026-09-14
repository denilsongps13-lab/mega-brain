; -------------------------------------------------------------------------------
;  Mega Brain – Windows installer (Inno Setup 6)
;
;  Build with:  npm run build:installer
;  Sources:
;    - windows/installer/staging/*        clean tracked snapshot (built by the script)
;    - windows/installer/Mega-Brain.cmd   launcher (placed at {app})
;    - windows/installer/bootstrap.ps1    post-install preparation
; -------------------------------------------------------------------------------

#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "Mega Brain"
#endif
#define MyAppName "Mega Brain"
#define MyAppId "{{8E1F6A52-3B7C-4D90-9A54-1C2D3E4F5A6B}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Mega Brain
DefaultGroupName=Mega Brain
DisableProgramGroupPage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Mega-Brain-Setup-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
SetupLogging=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoDescription={#MyAppName} installer
VersionInfoProductName={#MyAppName}
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "runnow"; Description: "Abrir o Mega Brain agora"; GroupDescription: "Continuacao:"; Flags: checkedonce

[Files]
Source: "staging\*"; DestDir: "{app}\mega-brain"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Mega-Brain.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.ps1"; DestDir: "{app}\mega-brain\windows\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Mega-Brain.cmd"; WorkingDir: "{app}\mega-brain"; Comment: "Abrir o Mega Brain"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Mega-Brain.cmd"; WorkingDir: "{app}\mega-brain"; Tasks: desktopicon; Comment: "Abrir o Mega Brain"

[Run]
Filename: "{app}\Mega-Brain.cmd"; Description: "Abrir o Mega Brain agora"; Flags: nowait postinstall skipifsilent; Tasks: runnow

[Code]
function IsBootstrapSkipped: Boolean;
begin
  Result := (GetEnv('MB_INSTALLER_SKIP_BOOTSTRAP') = '1');
end;

procedure RunBootstrapAfterInstall;
var
  ResultCode: Integer;
  AppArg: String;
  LogDir: String;
begin
  if IsBootstrapSkipped then
    Exit;

  AppArg := ExpandConstant('{app}\mega-brain');
  LogDir := ExpandConstant('{tmp}');
  if not Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\mega-brain\windows\installer\bootstrap.ps1') +
    '" -AppDir "' + AppArg + '"',
    '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('Nao foi possivel executar a preparacao do Mega Brain. Instale Node.js e Python 3 e rode o instalador novamente.',
      mbCriticalError, MB_OK);
    Abort();
  end;
  if ResultCode <> 0 then
  begin
    MsgBox('A preparacao do Mega Brain falhou (codigo ' + IntToStr(ResultCode) +
      '). Verifique a janela de texto do instalador para detalhes.',
      mbCriticalError, MB_OK);
    Abort();
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunBootstrapAfterInstall;
end;