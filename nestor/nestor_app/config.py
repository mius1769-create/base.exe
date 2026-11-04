"""Пути и настройки локального запуска."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

NESTOR_ROOT = Path(__file__).resolve().parent.parent   # код и data/ (в NeSToR.exe — распакованная сборка)
FROZEN = bool(getattr(sys, "frozen", False))           # запущен NeSToR.exe (PyInstaller)


def default_var_dir() -> Path:
    """Папка данных по умолчанию: nestor/var; у NeSToR.exe — %LOCALAPPDATA%\\NeSToR\\var.

    Временная папка распаковки exe удаляется после выхода, поэтому данные exe хранятся
    в локальном профиле пользователя (права администратора не нужны).
    """
    if FROZEN:
        local = windows_local_appdata() or (Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else None)
        return (local or Path(sys.executable).resolve().parent) / "NeSToR" / "var"
    return NESTOR_ROOT / "var"


def catalog_command() -> str:
    """Как вызвать команды тестового каталога в этой установке (для подсказок)."""
    return "NeSToR.exe catalog" if FROZEN else "py -3 tools/build_test_catalog.py"

# Доля совпадений, которую видит гость (только среди профилей с разрешённым поиском).
GUEST_FRACTION = 0.20
# Параметры поиска по умолчанию.
DEFAULT_MAX_GD = 4
DEFAULT_MIN_COMMON = 12
MAX_ALLOWED_GD = 10


@dataclass(frozen=True)
class Settings:
    var_dir: Path
    users_db: Path
    secret_file: Path
    manifest_file: Path
    host: str = "127.0.0.1"
    staging_dir: Path | None = None  # временные загрузки; по умолчанию default_staging_dir()
    port: int = 8765


def windows_local_appdata() -> Path | None:
    """Локальный AppData ТЕКУЩЕГО пользователя по его токену (SHGetKnownFolderPath).

    Переменной LOCALAPPDATA доверять нельзя: процесс, запущенный от другой учётной
    записи (runas, Start-Process -Credential), может унаследовать окружение запустившего.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        folder = GUID(0xF1B32785, 0x6FBA, 0x4FCF, (ctypes.c_ubyte * 8)(0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91))
        shell32, ole32 = ctypes.WinDLL("shell32"), ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ptr = ctypes.c_void_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(ptr)) != 0:
            return None
        try:
            return Path(ctypes.wstring_at(ptr.value))
        finally:
            ole32.CoTaskMemFree(ptr)
    except (OSError, AttributeError):
        return None


def default_staging_dir(var_dir: Path) -> Path:
    """Каталог временных загрузок.

    NESTOR_STAGING_DIR — явное значение. Иначе на Windows — внутри локального
    профиля текущего пользователя (Local AppData по токену, см. windows_local_appdata;
    …/NeSToR/staging), на остальных ОС — var/staging.
    ACL / права задаются и проверяются в nestor_app.secure_dir.
    """
    explicit = os.environ.get("NESTOR_STAGING_DIR")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        local = windows_local_appdata() or (Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else None)
        if local:
            return local / "NeSToR" / "staging"
    return var_dir / "staging"


def load_settings(var_dir: str | os.PathLike | None = None) -> Settings:
    base = Path(var_dir or os.environ.get("NESTOR_VAR_DIR") or default_var_dir())
    base.mkdir(parents=True, exist_ok=True)
    return Settings(
        var_dir=base,
        users_db=base / "nestor_users.db",
        secret_file=base / "server_secret.key",
        manifest_file=NESTOR_ROOT / "data" / "MANIFEST.json",
        staging_dir=default_staging_dir(base),
        port=int(os.environ.get("NESTOR_PORT", "8765")),
    )


def load_or_create_secret(path: Path) -> bytes:
    """Серверный секрет для детерминированной гостевой выборки.

    Создаётся один раз при первом запуске и хранится локально (в git не попадает).
    Смена секрета меняет все гостевые выборки.
    """
    if path.exists():
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    data = secrets.token_bytes(32)
    path.write_bytes(data)
    return data
