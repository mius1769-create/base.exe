"""Схема пользовательской SQLite-базы NeSToR (отдельно от научного справочника).

Принципы:
  * профиль создаётся закрытым (searchable = 0); включение поиска — отдельное
    действие владельца, фиксируется в consent_events;
  * kit ID, email и контакты хранятся только для владельца и никогда не
    попадают в результаты поиска и экспорт (сериализация — по белым спискам);
  * наружу профиль виден только по случайному непрозрачному public_handle;
  * гостевые запросы в базу не пишутся;
  * незавершённые загрузки файлов в базу не пишутся (var/staging/, nestor_app.staging).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 6

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
    source_format          TEXT NOT NULL,                  -- manual | table | ...
    panel_code             TEXT,                           -- FTDNA_Y37, GENOPOISK_Y50 …; NULL — пользовательский набор
    panel_basis            TEXT NOT NULL DEFAULT 'custom'
                           CHECK (panel_basis IN ('selected','recognized','custom')),
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

-- Полные исходные файлы импорта — ТОЛЬКО по отдельному согласию владельца
-- (keep_original = 1). Незавершённые загрузки сюда не пишутся (они во временной
-- папке var/staging/, вне базы и её резервных копий). Файл удаляется вместе с
-- последним профилем из него и вместе с аккаунтом.
CREATE TABLE IF NOT EXISTS import_files (
    id             INTEGER PRIMARY KEY,
    owner_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    content        BLOB NOT NULL,
    panel_choice   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged','committed')),
    keep_original  INTEGER NOT NULL DEFAULT 0 CHECK (keep_original IN (0,1)),
    keep_original_at TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Происхождение профиля из файла: лист, строка и исходные ячейки дословно.
CREATE TABLE IF NOT EXISTS profile_sources (
    profile_id      INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    import_file_id  INTEGER REFERENCES import_files(id) ON DELETE SET NULL,
    filename        TEXT NOT NULL,
    file_sha256     TEXT NOT NULL,
    sheet           TEXT NOT NULL,
    row_number      INTEGER NOT NULL,
    record_id       TEXT,
    raw_json        TEXT NOT NULL
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
    # SQLite перезаписывает содержимое удалённых записей в страницах файла базы;
    # это не гарантирует стирание с носителя (SSD, снимки ФС, внешние копии).
    conn.execute("PRAGMA secure_delete = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(profile_markers)")}
    if "status" not in cols:  # миграция v1 → v2: позиции без значения / нераспознанные
        conn.execute("ALTER TABLE profile_markers ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'")
    icols = {r[1] for r in conn.execute("PRAGMA table_info(import_files)")}
    if icols and "keep_original" not in icols:  # миграция v4 → v5: согласие на хранение оригинала
        conn.execute("ALTER TABLE import_files ADD COLUMN keep_original INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE import_files ADD COLUMN keep_original_at TEXT")
        # файлы, сохранённые до v5 без отдельного согласия, удаляются
        conn.execute("DELETE FROM import_files WHERE status = 'committed'")
    if icols:  # миграция v5 → v6: незавершённые загрузки больше не хранятся в базе
        conn.execute("DELETE FROM import_files WHERE status = 'staged'")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(profiles)")}
    if pcols and "panel_code" not in pcols:  # миграция v2 → v3: панель профиля
        conn.execute("ALTER TABLE profiles ADD COLUMN panel_code TEXT")
        conn.execute("ALTER TABLE profiles ADD COLUMN panel_basis TEXT NOT NULL DEFAULT 'custom'")
    conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


@dataclass(frozen=True)
class CheckpointResult:
    """Результат PRAGMA wal_checkpoint(TRUNCATE).

    status: 'complete' — все кадры WAL перенесены и WAL усечён;
            'incomplete' — checkpoint не завершён (например, открыт читатель):
                           в WAL могут оставаться прежние версии страниц;
            'not_wal' — база не в режиме WAL (например, :memory:).
    """

    status: str
    busy: int
    log_frames: int
    checkpointed: int

    @property
    def complete(self) -> bool:
        return self.status == "complete"


def checkpoint_truncate(conn: sqlite3.Connection) -> CheckpointResult:
    """Перенести WAL в основной файл и усечь его; результат проверяется, а не предполагается.

    При PRAGMA secure_delete = ON SQLite перезаписывает содержимое удалённых записей
    в страницах базы; после полного checkpoint(TRUNCATE) прежние версии страниц
    уходят и из файла WAL. Это относится к файлам базы приложения; стирание с
    носителя (SSD, снимки файловой системы, внешние копии) не гарантируется.
    """
    try:
        busy, log, ckpt = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.OperationalError:
        return CheckpointResult("incomplete", 1, -1, -1)
    if log == -1:
        return CheckpointResult("not_wal", busy, log, ckpt)
    if busy == 0 and log == 0 and ckpt == 0:  # TRUNCATE: WAL пуст после переноса
        return CheckpointResult("complete", busy, log, ckpt)
    return CheckpointResult("incomplete", busy, log, ckpt)


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
