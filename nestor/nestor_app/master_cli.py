"""Роль мастера базы: выдаётся только из командной строки на этом компьютере.

  NeSToR.exe master grant EMAIL    # пользователь уже должен быть зарегистрирован
  NeSToR.exe master revoke EMAIL
  NeSToR.exe master list

Из исходников: py -3 run_nestor.py master grant EMAIL. Перезапуск не нужен: роль
проверяется при каждом запросе.
"""

from __future__ import annotations

import argparse

from . import accounts
from .config import load_settings
from .db import connect


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["grant", "revoke", "list"])
    ap.add_argument("email", nargs="?")
    ap.add_argument("--var-dir", default=None)
    a = ap.parse_args(argv)
    if a.action != "list" and not a.email:
        ap.error(f"{a.action} требует EMAIL")
    conn = connect(load_settings(a.var_dir).users_db)
    try:
        if a.action != "list":
            try:
                accounts.set_master(conn, a.email, a.action == "grant")
            except accounts.AuthError as e:
                print(f"ОШИБКА: {e}")
                return 1
            print(f"Роль мастера {'выдана' if a.action == 'grant' else 'снята'}: {a.email.strip()}")
        masters = accounts.list_masters(conn)
        print("Мастера базы: " + (", ".join(masters) if masters else "нет"))
        return 0
    finally:
        conn.close()
