; Inno Setup script for the Auto-Cut Windows installer.
;
; Build the app first, then compile this:
;     pyinstaller packaging/autocut.spec --noconfirm
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\autocut.iss
;
; Produces packaging/output/AutoCut-Setup-<version>.exe - one file to hand to
; someone, no Python and no ffmpeg needed on their machine.

#define AppName "Wavefield"
#define AppExeName "Wavefield.exe"
#define AppPublisher "Paul Flores"
#define AppURL "https://github.com/pcmflores19-ph/autocut-simple"

; Version comes from packaging/build.py as /DAppVersion=..., which reads it
; out of auto_cut/version.py. The fallback is only for running ISCC by hand.
; (An earlier attempt to read version.py with the Inno preprocessor was left
; half-written and never actually ran, so the version silently drifted.)
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C2A64-5B7E-4D91-A0C3-7E5D9B1A2F48}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE

; Per-user install by default, so no administrator password is needed. That
; matters for the audience here - people on managed university laptops who
; cannot elevate.
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest

OutputDir=output
OutputBaseFilename=Wavefield-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
; The installer's own icon, and the one shown in Add/Remove Programs.
SetupIconFile=autocut.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"

[Files]
; The whole PyInstaller one-folder build, ffmpeg included.
Source: "..\dist\AutoCut\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Start {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Decoded audio and transcripts the app caches next to itself. Regenerated on
; demand, and can run to gigabytes, so leaving it behind would be rude.
Type: filesandordirs; Name: "{app}\.cache"
Type: files; Name: "{app}\autocut_crash.log"
