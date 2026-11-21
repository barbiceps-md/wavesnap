; Inno Setup kurulum betiği (Windows). Önce PyInstaller: dist\WaveSnap\ hazır olmalı.
;   iscc /DSurum=0.1.0 paket\wavesnap.iss
; Yönetici izni istemez: kullanıcının kendi klasörüne kurar.

#ifndef Surum
  #define Surum "0.0.0"
#endif

[Setup]
AppId={{8D3F2B6A-5C1E-4E8B-9A7D-2F6C1B0E4A93}
AppName=WaveSnap
AppVersion={#Surum}
AppPublisher=barbiceps-md
AppPublisherURL=https://github.com/barbiceps-md/wavesnap
AppSupportURL=https://github.com/barbiceps-md/wavesnap/issues
DefaultDirName={localappdata}\Programs\WaveSnap
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=WaveSnap-{#Surum}-windows-setup
SetupIconFile=..\web\simge.ico
UninstallDisplayIcon={app}\WaveSnap.exe
UninstallDisplayName=WaveSnap
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\WaveSnap\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; eski sürümün dosyaları yenisine karışmasın
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; Başlat menüsü kısayolu uygulama kimliğini taşır: bildirimlerde "WaveSnap" adı ve simgesi görünür
Name: "{userprograms}\WaveSnap"; Filename: "{app}\WaveSnap.exe"; AppUserModelID: "WaveSnap.App"
Name: "{userdesktop}\WaveSnap"; Filename: "{app}\WaveSnap.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WaveSnap.exe"; Description: "{cm:LaunchProgram,WaveSnap}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\WaveSnap.exe"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "WaveSnapKapat"

[Code]
// Güncellemede arka planda çalışan eski sürümü önce düzgünce kapat (modemdeki oturumu bırakır)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Sonuc: Integer;
begin
  if FileExists(ExpandConstant('{app}\WaveSnap.exe')) then
    Exec(ExpandConstant('{app}\WaveSnap.exe'), '--quit', '', SW_HIDE, ewWaitUntilTerminated, Sonuc);
  Result := '';
end;
