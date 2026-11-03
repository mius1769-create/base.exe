"""Приватный каталог для временных загрузок: создание, ограничение доступа и проверка.

POSIX (Linux, macOS): каталог 0700, владелец — текущий пользователь; проверяется
st_uid и отсутствие битов группы/остальных.

Windows: chmod не задаёт ACL, поэтому:
  1. каталог по умолчанию — внутри локального профиля пользователя
     (%LOCALAPPDATA%\\NeSToR\\staging, см. config);
  2. DACL задаётся целиком через Win32 SetNamedSecurityInfoW из SDDL
        D:P(A;OICI;FA;;;<SID пользователя>)(A;OICI;FA;;;SY)
     — защищённый (наследование отключено), только текущий пользователь и SYSTEM.
     icacls /inheritance:r /grant:r для этого не годится: проверка на windows-latest
     показала, что после него остаются разрешения Administrators и OWNER RIGHTS.
     SID используются вместо имён — не зависит от языка Windows;
  3. ACL читается обратно через Win32 API (GetNamedSecurityInfoW) и проверяется:
     DACL не NULL, наследование отключено (SE_DACL_PROTECTED), каждый
     разрешающий ACE выдан только текущему пользователю или SYSTEM.
Если проверка не прошла, загрузка файлов отключается (staging.put отказывает).

Ограничения: администраторы компьютера могут сменить владельца и получить доступ
к любому каталогу — от них ACL не защищает; копии каталога сторонними средствами
(резервное копирование ОС, синхронизация профиля) приложение не контролирует.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_SID = "S-1-5-18"
ACCESS_ALLOWED_ACE_TYPES = {0x0, 0x5, 0x9, 0xB}  # ALLOWED, ALLOWED_OBJECT, ALLOWED_CALLBACK, ALLOWED_CALLBACK_OBJECT
SE_DACL_PROTECTED = 0x1000


@dataclass
class DirCheck:
    ok: bool
    platform: str
    path: str
    problems: list = field(default_factory=list)
    principals: list = field(default_factory=list)   # Windows: SID с разрешающими ACE; POSIX: uid владельца


# ---------- чистая логика (тестируется на любой ОС) ----------

def evaluate_windows_dacl(aces: list[tuple[int, str]] | None, protected: bool, user_sid: str) -> list[str]:
    """Проблемы DACL. aces — [(тип ACE, SID)]; None — NULL DACL (доступ всем)."""
    if aces is None:
        return ["NULL DACL: доступ разрешён всем"]
    problems = []
    if not protected:
        problems.append("наследование разрешений не отключено (SE_DACL_PROTECTED не установлен)")
    allowed = {user_sid, SYSTEM_SID}
    for ace_type, sid in aces:
        if ace_type in ACCESS_ALLOWED_ACE_TYPES and sid not in allowed:
            problems.append(f"разрешение для постороннего субъекта {sid}")
    if not any(sid == user_sid and t in ACCESS_ALLOWED_ACE_TYPES for t, sid in aces):
        problems.append("нет разрешения для текущего пользователя")
    return problems


def evaluate_posix_mode(mode: int, owner_uid: int, current_uid: int) -> list[str]:
    problems = []
    if owner_uid != current_uid:
        problems.append(f"владелец каталога uid={owner_uid}, а не текущий пользователь uid={current_uid}")
    if mode & 0o077:
        problems.append(f"права {oct(mode & 0o777)}: доступ для группы или остальных")
    return problems


# ---------- Windows ----------

def _windows_user_sid() -> str:
    out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True).stdout
    return out.strip().split(",")[-1].strip().strip('"')


def _windows_read_dacl(path: Path) -> tuple[list[tuple[int, str]] | None, bool]:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SE_FILE_OBJECT, DACL_SECURITY_INFORMATION = 1, 0x4

    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    p_dacl, p_sd = ctypes.c_void_p(), ctypes.c_void_p()
    rc = advapi32.GetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                        None, None, ctypes.byref(p_dacl), None, ctypes.byref(p_sd))
    if rc != 0:
        raise OSError(rc, "GetNamedSecurityInfoW")
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(p_sd, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        protected = bool(control.value & SE_DACL_PROTECTED)
        if not p_dacl.value:
            return None, protected

        class ACL_SIZE_INFORMATION(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD), ("AclBytesFree", wintypes.DWORD)]

        class ACE_HEADER(ctypes.Structure):
            _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", wintypes.WORD)]

        info = ACL_SIZE_INFORMATION()
        if not advapi32.GetAclInformation(p_dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
            raise ctypes.WinError(ctypes.get_last_error())
        aces = []
        for i in range(info.AceCount):
            p_ace = ctypes.c_void_p()
            if not advapi32.GetAce(p_dacl, i, ctypes.byref(p_ace)):
                raise ctypes.WinError(ctypes.get_last_error())
            header = ACE_HEADER.from_address(p_ace.value)
            if header.AceType in (0x0, 0x1):   # ACCESS_ALLOWED / ACCESS_DENIED: Header(4) + Mask(4) + SID
                p_sid = ctypes.c_void_p(p_ace.value + 8)
            else:                              # объектные/callback ACE: SID не по фиксированному смещению
                aces.append((header.AceType, "<нестандартный ACE>"))
                continue
            s = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(p_sid, ctypes.byref(s)):
                raise ctypes.WinError(ctypes.get_last_error())
            aces.append((header.AceType, s.value))
            kernel32.LocalFree(ctypes.cast(s, ctypes.c_void_p))
        return aces, protected
    finally:
        kernel32.LocalFree(p_sd)


def _windows_harden(path: Path, user_sid: str) -> None:
    """Записать защищённый DACL: полный доступ только пользователю и SYSTEM, наследование отключено."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    sddl = f"D:P(A;OICI;FA;;;{user_sid})(A;OICI;FA;;;SY)"
    sd = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        SE_FILE_OBJECT = 1
        DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION = 0x4, 0x80000000
        rc = advapi32.SetNamedSecurityInfoW(str(path), SE_FILE_OBJECT,
                                            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                                            None, None, dacl, None)
        if rc != 0:
            raise OSError(rc, "SetNamedSecurityInfoW")
    finally:
        kernel32.LocalFree(sd)


def windows_acl_text(path: Path) -> str:
    """Вывод icacls — только для диагностики в сообщениях об ошибке."""
    try:
        return subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
    except OSError as e:
        return str(e)


# ---------- общий вход ----------

def verify_private_dir(path: Path) -> DirCheck:
    path = Path(path)
    if not path.is_dir():
        return DirCheck(False, sys.platform, str(path), ["каталог не существует"])
    if os.name == "nt":
        user_sid = _windows_user_sid()
        aces, protected = _windows_read_dacl(path)
        problems = evaluate_windows_dacl(aces, protected, user_sid)
        principals = sorted({sid for t, sid in (aces or []) if t in ACCESS_ALLOWED_ACE_TYPES})
        return DirCheck(not problems, "windows", str(path), problems, principals)
    st = path.stat()
    problems = evaluate_posix_mode(stat.S_IMODE(st.st_mode), st.st_uid, os.getuid())
    return DirCheck(not problems, "posix", str(path), problems, [st.st_uid])


def prepare_private_dir(path: Path) -> DirCheck:
    """Создать каталог, ограничить доступ текущим пользователем и проверить результат."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        _windows_harden(path, _windows_user_sid())
    else:
        os.chmod(path, 0o700)
    return verify_private_dir(path)
