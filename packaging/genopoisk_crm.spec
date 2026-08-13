# PyInstaller spec — сборка GENOPOISK CRM в один портативный EXE (раздел 22, 23 ТЗ).
# Запускается на Windows-раннере GitHub Actions (см. .github/workflows/build-windows.yml).
#
# Локально на Windows: pyinstaller packaging/genopoisk_crm.spec

# -*- mode: python ; coding: utf-8 -*-
import os

# SPECPATH — переменная, которую PyInstaller подставляет автоматически:
# абсолютный путь к каталогу, где лежит этот .spec файл (packaging/).
# Используем её, чтобы сборка работала независимо от того, из какого
# рабочего каталога был запущен pyinstaller.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

block_cipher = None

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'run_app.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'openpyxl',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GENOPOISK_CRM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # обычный desktop-режим, без консольного окна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,        # TODO: указать путь к .ico, если появится иконка приложения
)

# onedir-сборка (не onefile): устанавливаемая программа — это папка со всеми
# зависимостями, что и ожидает packaging/installer.iss (Source: dist\GENOPOISK_CRM\*).
# onedir выбран вместо onefile, т.к. запускается быстрее (без распаковки во
# временную папку при каждом старте) — важно для повседневной desktop-работы.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GENOPOISK_CRM',
)
