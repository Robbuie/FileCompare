; Inno Setup script for File Compare. Ported from File Manager 0.40.0. Needs Inno Setup 6.3 or newer, for
; ArchitecturesAllowed=x64compatible. Compiled by `packaging/build.py`, which
; passes the version in:
;
;     iscc /DAppVersion=0.7.0 packaging\installer.iss
;
; Two decisions are load bearing and both are about updating.
;
; It installs per user, into %LOCALAPPDATA%\Programs. A per-machine install
; into Program Files would put a UAC prompt in front of every update, and an
; update that needs a password is an update that gets postponed until the
; version gap is wide enough to be frightening. This is a single-user tool on
; a single machine; the registry keys and the shortcut belong to that user.
;
; The output filename has no spaces in it. GitHub replaces spaces in an asset
; name with dots as it takes the upload, so a setup exe called
; "File Compare Setup.exe" arrives as "File.Compare.Setup.exe" and the URL in
; latest.json -- written before the upload -- points at nothing. Redline PDF
; shipped that bug and it only appeared on machines running the older build.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "File Compare"
#define AppExe "FileCompare.exe"
#define Publisher "Robbuie"
#define RepoUrl "https://github.com/Robbuie/FileCompare"

[Setup]
; Never change this GUID. It is how Windows knows an install is an upgrade of
; this application rather than a second copy of it, and how the updater's
; silent run lands on top of what is already there. It is also copied into
; `app/core/updates.py` as APP_ID: the application reads InstallLocation from
; the uninstall key Inno names after it, to tell an installed copy from one
; running out of a build folder. Change it in one place only and updates go
; quiet.
AppId={{309034BD-085E-429A-9174-D349C332D6A9}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
VersionInfoVersion={#AppVersion}

DefaultDirName={autopf}\FileCompare
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\dist
OutputBaseFilename=FileCompare-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; An update runs this installer with /SILENT while the old version may still be
; shutting down. Inno waits for the executable rather than failing on a locked
; file, and does not relaunch anything afterwards -- the application decides
; when it restarts, not the installer.
CloseApplications=yes
RestartApplications=no

; The install folder goes on the user's PATH (see [Registry] and [Code]).
; Windows is told the environment changed, so programs started afterwards --
; File Manager, a new terminal, git -- find FileCompare.exe by name.
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "explorermenu"; Description: "Add ""Compare"" to Explorer's right-click menu (Select left side, then Compare with it)"; GroupDescription: "Explorer:"; Flags: unchecked

[InstallDelete]
; 0.39. Inno copies files over the top of an existing install and never
; removes one the new build no longer ships, so every file a release stopped
; carrying -- the 46 MB trimmed in 0.29.12, a whole Python 3.14 runtime from
; an early build -- stayed on disk through every update after it. The frozen
; folder is replaced whole instead. Nothing the user made lives in {app}:
; settings, history and labels are in %APPDATA%, the staged update in
; %LOCALAPPDATA%. CloseApplications above has already waited for the old
; process to exit, so nothing in the folder is held open when this runs.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\FileCompare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; App Paths is how File Manager -- and Win+R, and anything else that runs a
; program by name -- finds FileCompare.exe without a path written into it.
; File Manager's compare rows name the program, not a folder, precisely so
; that this key is all it takes. Per user, like the install.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"

; On the user's PATH as well. App Paths is what the Run box and ShellExecute
; read, but a program that looks for an executable the way Python's
; `shutil.which` does -- File Manager's command rows, and git's difftool --
; reads only PATH. Added once, and removed again on uninstall.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

; Explorer's two verbs, off unless asked for: "Select left side" remembers a
; file or folder, "Compare to left side" opens the pair. Ordinary per-user
; verbs rather than a shell extension DLL, so there is nothing loaded into
; Explorer. The remembering is done by the application (--select-left), in
; its own settings file.
Root: HKCU; Subkey: "Software\Classes\*\shell\FileCompareLeft"; ValueType: string; ValueName: ""; ValueData: "Select left side to compare"; Flags: uninsdeletekey; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\*\shell\FileCompareLeft"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\*\shell\FileCompareLeft\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --select-left ""%1"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\*\shell\FileCompareWith"; ValueType: string; ValueName: ""; ValueData: "Compare to left side"; Flags: uninsdeletekey; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\*\shell\FileCompareWith"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\*\shell\FileCompareWith\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --with-left ""%1"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileCompareLeft"; ValueType: string; ValueName: ""; ValueData: "Select left side to compare"; Flags: uninsdeletekey; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileCompareLeft"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileCompareLeft\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --select-left ""%1"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileCompareWith"; ValueType: string; ValueName: ""; ValueData: "Compare to left side"; Flags: uninsdeletekey; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileCompareWith"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FileCompareWith\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --with-left ""%1"""; Tasks: explorermenu

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Not shown during a silent run, which is what an update is.
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The staged installer the updater downloads. Settings in %APPDATA% are left
; alone: an uninstall is usually a reinstall, and losing the settings for it
; is a small insult with no benefit.
Type: filesandordirs; Name: "{localappdata}\FileCompare\updates"

[Code]
// Whether the install folder is already on the user's PATH, so an update
// does not add it a second time. Compared without case and with the
// separators round it, so C:\x does not match C:\xy.
function NeedsAddPath(Folder: string): Boolean;
var
  Current: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Current) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Folder) + ';', ';' + Uppercase(Current) + ';') = 0;
end;

// Uninstall takes the folder back off PATH, and nothing else with it.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Current, Folder: string;
  At: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Current) then
    exit;
  Folder := ExpandConstant('{app}');
  Current := ';' + Current + ';';
  At := Pos(';' + Uppercase(Folder) + ';', Uppercase(Current));
  if At = 0 then
    exit;
  Delete(Current, At, Length(Folder) + 1);
  Current := Copy(Current, 2, Length(Current) - 2);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Current);
end;
