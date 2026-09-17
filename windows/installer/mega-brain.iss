; Mega Brain Windows installer (Inno Setup 6)
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
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "runnow"; Description: "Abrir o Mega Brain agora"; GroupDescription: "Continuacao:"; Flags: checkedonce

[Files]
Source: "staging\*"; DestDir: "{app}\mega-brain"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Mega-Brain.cmd"; DestDir: "{app}"; DestName: "mega-brain.cmd"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\mega-brain.cmd"; WorkingDir: "{app}\mega-brain"; Comment: "Abrir Mega Brain com Claude Code"
Name: "{group}\{#MyAppName} - Interface"; Filename: "{app}\mega-brain.cmd"; Parameters: "gui"; WorkingDir: "{app}\mega-brain"; Comment: "Abrir interface grafica do Mega Brain"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\mega-brain.cmd"; WorkingDir: "{app}\mega-brain"; Tasks: desktopicon; Comment: "Abrir Mega Brain"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Flags: preservestringtype

[Run]
Filename: "{app}\mega-brain.cmd"; Description: "Abrir o Mega Brain agora"; Flags: nowait postinstall skipifsilent; Tasks: runnow

[Code]
function IsBootstrapSkipped: Boolean;
begin
  Result := (GetEnv('MB_INSTALLER_SKIP_BOOTSTRAP') = '1');
end;

procedure RunBootstrapAfterInstall;
var
  ResultCode: Integer;
  AppArg: String;
begin
  if IsBootstrapSkipped then
    Exit;

  AppArg := ExpandConstant('{app}\mega-brain');
  if not Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\mega-brain\windows\installer\bootstrap.ps1') +
    '" -AppDir "' + AppArg + '"',
    '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('Nao foi possivel executar a preparacao do Mega Brain. Verifique Node.js, Python e sua conexao.', mbCriticalError, MB_OK);
    Abort();
  end;
  if ResultCode <> 0 then
  begin
    MsgBox('A preparacao do Mega Brain falhou (codigo ' + IntToStr(ResultCode) + '). Rode o instalador novamente.', mbCriticalError, MB_OK);
    Abort();
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunBootstrapAfterInstall;
end;
