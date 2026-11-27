; ArtiSync installer (Inno Setup 6).
;
;   python packaging\build.py
;   iscc /DAppVersion=3.0.0 packaging\windows\ArtiSync.iss
;
; Installs the PyInstaller bundle from packaging\dist\ArtiSync. Same AppName
; and folder as the 2.x installer, so it upgrades an existing install in place.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppName=ArtiSync
AppVersion={#AppVersion}
AppVerName=ArtiSync {#AppVersion}
AppPublisher=Spinjitsudoom
AppPublisherURL=https://github.com/Spinjitsudoom/ArtiSync
AppSupportURL=https://github.com/Spinjitsudoom/ArtiSync/issues
AppUpdatesURL=https://github.com/Spinjitsudoom/ArtiSync/releases
DefaultDirName={autopf}\ArtiSync
DefaultGroupName=ArtiSync
AllowNoIcons=yes
OutputDir=..\out
OutputBaseFilename=ArtiSync-Setup
SetupIconFile=..\build\ArtiSync.ico
UninstallDisplayIcon={app}\ArtiSync.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Files left by the 2.x (C++) build in the same folder.
Type: files; Name: "{app}\*.dll"
Type: filesandordirs; Name: "{app}\platforms"
Type: filesandordirs; Name: "{app}\styles"
Type: filesandordirs; Name: "{app}\imageformats"
Type: filesandordirs; Name: "{app}\iconengines"
Type: filesandordirs; Name: "{app}\tls"
Type: filesandordirs; Name: "{app}\networkinformation"
Type: filesandordirs; Name: "{app}\generic"
Type: filesandordirs; Name: "{app}\translations"
; The previous 3.x bundle, so removed modules don't linger.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\ArtiSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ArtiSync"; Filename: "{app}\ArtiSync.exe"
Name: "{group}\{cm:UninstallProgram,ArtiSync}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\ArtiSync"; Filename: "{app}\ArtiSync.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ArtiSync.exe"; Description: "{cm:LaunchProgram,ArtiSync}"; Flags: nowait postinstall skipifsilent
; In-app updates run this installer with /SILENT; reopen the app afterwards.
Filename: "{app}\ArtiSync.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent
