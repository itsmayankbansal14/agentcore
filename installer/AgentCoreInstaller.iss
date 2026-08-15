; ============================================================
;  AgentCore — Windows Installer (Inno Setup)
;  Build with Inno Setup 6:   ISCC.exe AgentCoreInstaller.iss
;  Produces AgentCoreInstaller.exe
;
;  What it does:
;    - installs the runtime (bundled Python exe OR python source + venv)
;    - creates Start Menu + Desktop shortcuts to AgentCore.exe
;    - registers an uninstall entry
;    - initializes the workspace (via bootstrap on first run)
;    - runs bootstrap automatically on first launch
; ============================================================

#define MyAppName "AgentCore"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "AgentCore"
#define MyAppExeName "AgentCore.exe"

[Setup]
AppId={{8E4F2C1A-5A3B-4D6E-9F0C-1B2A3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AgentCore
DefaultGroupName=AgentCore
OutputBaseFilename=AgentCoreInstaller
OutputDir=..\dist
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=AgentCore
UninstallDisplayIcon={app}\AgentCore.exe
PrivilegesRequired=lowest          ; per-user install, no admin needed

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; the built launcher + bundled runtime (from dist/)
Source: "..\dist\AgentCore.exe"; DestDir: "{app}"; Flags: ignoreversion
; source distribution (used for bootstrap when not bundled)
Source: "..\*.py"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs
Source: "..\core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs
Source: "..\devices\*"; DestDir: "{app}\devices"; Flags: ignoreversion recursesubdirs
Source: "..\executor\*"; DestDir: "{app}\executor"; Flags: ignoreversion recursesubdirs
Source: "..\memory\*"; DestDir: "{app}\memory"; Flags: ignoreversion recursesubdirs
Source: "..\observer\*"; DestDir: "{app}\observer"; Flags: ignoreversion recursesubdirs
Source: "..\planner\*"; DestDir: "{app}\planner"; Flags: ignoreversion recursesubdirs
Source: "..\planning\*"; DestDir: "{app}\planning"; Flags: ignoreversion recursesubdirs
Source: "..\reasoning\*"; DestDir: "{app}\reasoning"; Flags: ignoreversion recursesubdirs
Source: "..\llm\*"; DestDir: "{app}\llm"; Flags: ignoreversion recursesubdirs
Source: "..\database\*"; DestDir: "{app}\database"; Flags: ignoreversion recursesubdirs
Source: "..\dashboard\*"; DestDir: "{app}\dashboard"; Flags: ignoreversion recursesubdirs
Source: "..\api\*"; DestDir: "{app}\api"; Flags: ignoreversion recursesubdirs
Source: "..\ui\*"; DestDir: "{app}\ui"; Flags: ignoreversion recursesubdirs
Source: "..\vision\*"; DestDir: "{app}\vision"; Flags: ignoreversion recursesubdirs
Source: "..\plugins\*"; DestDir: "{app}\plugins"; Flags: ignoreversion recursesubdirs
Source: "..\bootstrap.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion

[Icons]
Name: "{group}\AgentCore"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\AgentCore (Dev Console)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--no-reload"
Name: "{autodesktop}\AgentCore"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; bootstrap runs automatically on first launch (creates .venv, deps, workspace, db)
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AgentCore (runs bootstrap)"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"
