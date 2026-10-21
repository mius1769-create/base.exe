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


def get_telegram_proxy_config(conn: sqlite3.Connection):
    """Собирает ProxyConfig из settings (тип/хост/порт — не секретны) и
    secrets_store (логин/пароль — секретны) для telegram_client. Возвращает
    None, если прокси явно не настроен (тогда клиент сам возьмёт системный
    прокси/VPN — см. telegram_client._build_opener)."""
    kind = get_setting(conn, "telegram_proxy_kind", "") or ""
    if kind not in ("http", "socks5"):
        return None
    host = get_setting(conn, "telegram_proxy_host", "") or ""
    port = get_int_setting(conn, "telegram_proxy_port", 0)
    if not host or not port:
        return None

    from . import secrets_store
    from .telegram_client import ProxyConfig

    username, password = secrets_store.get_telegram_proxy_credentials()
    return ProxyConfig(kind=kind, host=host, port=port, username=username, password=password)
