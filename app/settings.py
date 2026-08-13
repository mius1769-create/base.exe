"""
GENOPOISK CRM — настройки приложения (раздел 20 ТЗ), хранятся в таблице settings.

Telegram Bot Token НЕ хранится в этой таблице в открытом виде и НЕ хранится
в исходном коде — см. secrets.py, который использует отдельный защищённый
файл вне репозитория/каталога установки (раздел 21).
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def get_setting(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_int_setting(conn: sqlite3.Connection, key: str, default: int) -> int:
    val = get_setting(conn, key)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default
