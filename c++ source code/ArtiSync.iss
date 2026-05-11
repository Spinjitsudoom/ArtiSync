; ArtiSync Inno Setup installer script

[Setup]
AppName=ArtiSync
AppVersion=2.1.0
AppPublisher=Spinjitsudoom
AppPublisherURL=https://github.com/Spinjitsudoom/ArtiSync
AppSupportURL=https://github.com/Spinjitsudoom/ArtiSync/issues
AppUpdatesURL=https://github.com/Spinjitsudoom/ArtiSync/releases
DefaultDirName={autopf}\ArtiSync
DefaultGroupName=ArtiSync
AllowNoIcons=yes
OutputDir=.
OutputBaseFilename=ArtiSync-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "build\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ArtiSync"; Filename: "{app}\ArtiSync.exe"
Name: "{group}\{cm:UninstallProgram,ArtiSync}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\ArtiSync"; Filename: "{app}\ArtiSync.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ArtiSync.exe"; Description: "{cm:LaunchProgram,ArtiSync}"; Flags: nowait postinstall skipifsilent
