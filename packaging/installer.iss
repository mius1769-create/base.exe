; Inno Setup script — GENOPOISK_CRM_Setup.exe (раздел 22 ТЗ)
;
; Требования из ТЗ, реализованные здесь:
;  - установка в Program Files ИЛИ выбранный пользователем каталог (DefaultDirName +
;    стандартный шаг выбора папки мастера Inno Setup, usepreviousappdir не форсирует Program Files);
;  - пользовательские данные и БД НЕ хранятся внутри Program Files — приложение само
;    пишет в %APPDATA%/GENOPOISK_CRM/, инсталлятор туда ничего не копирует;
;  - ярлык на рабочем столе — по выбору пользователя (необязательная задача tasks);
;  - удаление приложения НЕ удаляет %APPDATA%/GENOPOISK_CRM (БД и backups) —
;    Inno Setup по умолчанию удаляет только то, что сам установил в {app},
;    и мы явно НЕ добавляем AppData в [UninstallDelete].
;
; Сборка (на Windows-раннере, см. .github/workflows/build-windows.yml):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss

#define MyAppName "GENOPOISK CRM"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "GENOPOISK"
#define MyAppExeName "GENOPOISK_CRM.exe"

[Setup]
AppId={{8F2C1B4E-6A3D-4E2F-9C7A-1B2C3D4E5F60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Позволяем пользователю выбрать другой каталог, не форсируем Program Files:
DisableDirPage=no
OutputBaseFilename=GENOPOISK_CRM_Setup
OutputDir=..\dist_installer
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; Не запускать инсталлятор от имени администратора принудительно — установка в Program Files
; всё равно потребует прав, Inno Setup сам предложит повышение при необходимости.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные значки:"; Flags: unchecked

[Files]
; Ожидается, что PyInstaller уже собрал приложение в dist\GENOPOISK_CRM (onedir-режим)
Source: "..\dist\GENOPOISK_CRM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

; ВАЖНО: секция [UninstallDelete] намеренно НЕ включает %APPDATA%\GENOPOISK_CRM —
; удаление приложения не должно автоматически стирать БД и резервные копии (раздел 22 ТЗ).
; Если пользователь захочет удалить и данные — это отдельное, осознанное действие
; (удалить папку %APPDATA%\GENOPOISK_CRM вручную), не часть стандартного uninstall.
