"""Защита каталога временных загрузок.

* TestDaclPolicy — логика проверки Windows ACL (на любой ОС, на синтетических ACE).
* TestPosix — права 0700 (только Linux/macOS).
* TestWindows — реальные ACL через icacls и Win32 API (только Windows).
* TestWindowsOtherUser — доступ другого обычного пользователя (только Windows и только
  если заданы NESTOR_PROBE_USER / NESTOR_PROBE_PASSWORD — учётная запись без прав
  администратора, которую создаёт CI; иначе тест пропускается).
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from synthetic import new_conn  # noqa: F401  (путь к nestor_app)

from nestor_app import secure_dir, staging

USER = "S-1-5-21-1111111111-2222222222-3333333333-1001"
ALLOW, DENY = 0x0, 0x1


class TestDaclPolicy(unittest.TestCase):
    def test_only_user_and_system_pass(self):
        aces = [(ALLOW, USER), (ALLOW, secure_dir.SYSTEM_SID)]
        self.assertEqual(secure_dir.evaluate_windows_dacl(aces, True, USER), [])

    def test_foreign_principals_fail(self):
        for sid in ("S-1-5-32-545", "S-1-1-0", "S-1-5-11", "S-1-5-32-544", "S-1-5-21-9-9-9-1002"):
            problems = secure_dir.evaluate_windows_dacl([(ALLOW, USER), (ALLOW, sid)], True, USER)
            self.assertTrue(any(sid in p for p in problems), sid)

    def test_deny_ace_for_others_is_fine(self):
        self.assertEqual(secure_dir.evaluate_windows_dacl([(ALLOW, USER), (DENY, "S-1-1-0")], True, USER), [])

    def test_inherited_null_and_missing_user(self):
        self.assertTrue(secure_dir.evaluate_windows_dacl([(ALLOW, USER)], False, USER))      # наследование
        self.assertTrue(secure_dir.evaluate_windows_dacl(None, True, USER))                  # NULL DACL
        self.assertTrue(secure_dir.evaluate_windows_dacl([(ALLOW, secure_dir.SYSTEM_SID)], True, USER))
        self.assertTrue(secure_dir.evaluate_windows_dacl([(ALLOW, USER), (0x5, "<нестандартный ACE>")], True, USER))

    def test_posix_policy(self):
        self.assertEqual(secure_dir.evaluate_posix_mode(0o700, 1000, 1000), [])
        self.assertTrue(secure_dir.evaluate_posix_mode(0o750, 1000, 1000))
        self.assertTrue(secure_dir.evaluate_posix_mode(0o700, 0, 1000))


@unittest.skipIf(os.name == "nt", "POSIX-права")
class TestPosix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_prepare_sets_0700_and_fixes_open_dir(self):
        d = Path(self.tmp.name) / "staging"
        d.mkdir(mode=0o777)
        os.chmod(d, 0o777)
        self.assertFalse(secure_dir.verify_private_dir(d).ok)
        chk = secure_dir.prepare_private_dir(d)
        self.assertTrue(chk.ok, chk.problems)
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)

    def test_staged_files_are_0600(self):
        d = Path(self.tmp.name) / "staging"
        st = staging.put(d, 1, "a.csv", b"x", "AUTO")
        for p in d.iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600, p.name)
        self.assertTrue(st.upload_id)


class TestPutRefusesUnprotected(unittest.TestCase):
    def test_upload_disabled_when_check_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        real = secure_dir.prepare_private_dir
        secure_dir.prepare_private_dir = lambda p: secure_dir.DirCheck(False, "test", str(p), ["чужой доступ"])
        self.addCleanup(setattr, secure_dir, "prepare_private_dir", real)
        staging._verified.clear()
        self.addCleanup(staging._verified.clear)
        with self.assertRaises(staging.StagingError):
            staging.put(Path(tmp.name) / "s", 1, "a.csv", b"x", "AUTO")


@unittest.skipUnless(os.name == "nt", "только Windows")
class TestWindows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_prepare_restricts_to_user_and_system(self):
        d = Path(self.tmp.name) / "staging"
        chk = secure_dir.prepare_private_dir(d)
        self.assertTrue(chk.ok, chk.problems)
        user = secure_dir._windows_user_sid()
        self.assertTrue(set(chk.principals) <= {user, secure_dir.SYSTEM_SID}, chk.principals)
        self.assertIn(user, chk.principals)
        aces, protected = secure_dir._windows_read_dacl(d)
        self.assertTrue(protected)

    def test_inherited_acl_is_rejected(self):
        d = Path(self.tmp.name) / "plain"
        d.mkdir()
        chk = secure_dir.verify_private_dir(d)                      # без явного ACL — наследование
        self.assertFalse(chk.ok)
        self.assertTrue(any("наследование" in p for p in chk.problems), chk.problems)

    def test_granting_builtin_users_is_detected(self):
        d = Path(self.tmp.name) / "staging"
        self.assertTrue(secure_dir.prepare_private_dir(d).ok)
        subprocess.run(["icacls", str(d), "/grant", "*S-1-5-32-545:(OI)(CI)R"], check=True, capture_output=True)
        chk = secure_dir.verify_private_dir(d)
        self.assertFalse(chk.ok)
        self.assertTrue(any("S-1-5-32-545" in p for p in chk.problems), chk.problems)

    def test_default_staging_inside_local_profile(self):
        from nestor_app.config import default_staging_dir
        if os.environ.get("NESTOR_STAGING_DIR"):
            self.skipTest("задан NESTOR_STAGING_DIR")
        d = default_staging_dir(Path(self.tmp.name))
        self.assertEqual(Path(os.environ["LOCALAPPDATA"]) / "NeSToR" / "staging", d)


@unittest.skipUnless(os.name == "nt" and os.environ.get("NESTOR_PROBE_USER") and os.environ.get("NESTOR_PROBE_PASSWORD"),
                     "только Windows с учётной записью для проверки (NESTOR_PROBE_USER)")
class TestWindowsOtherUser(unittest.TestCase):
    """Другой обычный пользователь не может прочитать файл в каталоге загрузок."""

    def _as_probe(self, fn):
        import ctypes
        from ctypes import wintypes
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        token = wintypes.HANDLE()
        LOGON32_LOGON_NETWORK, LOGON32_PROVIDER_DEFAULT = 3, 0
        if not advapi32.LogonUserW(os.environ["NESTOR_PROBE_USER"], ".", os.environ["NESTOR_PROBE_PASSWORD"],
                                   LOGON32_LOGON_NETWORK, LOGON32_PROVIDER_DEFAULT, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not advapi32.ImpersonateLoggedOnUser(token):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return fn()
            finally:
                advapi32.RevertToSelf()
        finally:
            kernel32.CloseHandle(token)

    def test_probe_user_denied_but_control_readable(self):
        tmp = tempfile.mkdtemp(dir=os.environ.get("PUBLIC") or None)
        root = Path(tmp)
        protected = root / "staging"
        st = staging.put(protected, 1, "a.csv", b"secret-row", "AUTO")
        target = protected / f"{st.upload_id}.bin"
        control = root / "control.txt"                                  # контроль: читаемый всем файл
        control.write_bytes(b"public")
        subprocess.run(["icacls", str(root), "/grant", "*S-1-5-32-545:(OI)(CI)R"], check=True, capture_output=True)
        subprocess.run(["icacls", str(control), "/grant", "*S-1-5-32-545:R"], check=True, capture_output=True)
        self.assertEqual(self._as_probe(control.read_bytes), b"public")  # учётная запись проверки работает
        with self.assertRaises(PermissionError):
            self._as_probe(target.read_bytes)
        with self.assertRaises(PermissionError):
            self._as_probe(lambda: list(protected.iterdir()))


if __name__ == "__main__":
    unittest.main()
