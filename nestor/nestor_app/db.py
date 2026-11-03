"""Схема пользовательской SQLite-базы NeSToR (отдельно от научного справочника).

Принципы:
  * профиль создаётся закрытым (searchable = 0); включение поиска — отдельное
    действие владельца, фиксируется в consent_events;
  * kit ID, email и контакты хранятся только для владельца и никогда не
    попадают в результаты поиска и экспорт (сериализация — по белым спискам);
  * наружу профиль виден только по случайному непрозрачному public_handle;
  * гостевые запросы в базу не пишутся.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- приватно, наружу не выводится
    password_hash  TEXT NOT NULL,
    display_name   TEXT,                                   -- псевдоним для запросов на связь
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    id                     INTEGER PRIMARY KEY,
    owner_user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    public_handle          TEXT NOT NULL UNIQUE,           -- случайный, без связи с kit ID
    kit_id_private         TEXT,                           -- приватно
    source_format          TEXT NOT NULL,                  -- manual | ftdna_csv | genopoisk_y37 | ...
    consent_basis          TEXT NOT NULL CHECK (consent_basis IN ('own_test','authorized_other')),
    consent_text_version   TEXT NOT NULL,
    consent_confirmed_at   TEXT NOT NULL,
    searchable             INTEGER NOT NULL DEFAULT 0 CHECK (searchable IN (0,1)),
    nickname               TEXT,
    nickname_visibility    TEXT NOT NULL DEFAULT 'hidden'
                           CHECK (nickname_visibility IN ('hidden','registered','public')),
    ancestor_text          TEXT,
    ancestor_visibility    TEXT NOT NULL DEFAULT 'hidden'
                           CHECK (ancestor_visibility IN ('hidden','registered','public')),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_profiles_owner ON profiles(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_profiles_searchable ON profiles(searchable);

CREATE TABLE IF NOT EXISTS profile_markers (
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    marker      TEXT NOT NULL,
    value       TEXT NOT NULL,                             -- '13', '11-14'; '' (нет значения); исходная строка (не распознано)
    status      TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','missing','invalid')),
    PRIMARY KEY (profile_id, marker)
);

-- Журнал согласий: загрузка, включение/выключение поиска, смена видимости.
CREATE TABLE IF NOT EXISTS consent_events (
    id          INTEGER PRIMARY KEY,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    detail      TEXT,
    at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Связь через запрос: контакты не раскрываются, владелец принимает или отклоняет.
CREATE TABLE IF NOT EXISTS contact_requests (
    id                 INTEGER PRIMARY KEY,
    from_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_profile_id      INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    message            TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','accepted','declined')),
    owner_reply        TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    decided_at         TEXT,
    UNIQUE (from_user_id, to_profile_id)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA secure_delete = ON")  # удалённые данные затираются в файле
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(profile_markers)")}
    if "status" not in cols:  # миграция v1 → v2: позиции без значения / нераспознанные
        conn.execute("ALTER TABLE profile_markers ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'")
    conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


class Tx:
    """Явная транзакция (connect() открывает базу в autocommit-режиме)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
