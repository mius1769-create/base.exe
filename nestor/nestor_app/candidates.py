"""Научные кандидаты: отдельная SQLite-база (var/nestor_science_candidates.db).

Сюда импортируются таблицы публикаций для проверки. База:
  * отделена от пользовательской базы и от научного справочника;
  * не читается поиском NeSToR (nestor_app.search работает только с профилями
    владельцев) — до отдельного решения источник в поиск не попадает;
  * хранит источник, публикацию, лицензию / статус разрешения, исходную ссылку,
    исходный файл (SHA-256), лист, номер строки и исходные ячейки дословно.
Повторный импорт того же файла (по SHA-256) отклоняется; повторы и совпадения
записей только помечаются, записи не объединяются.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import importer as im
from . import markers as mk

DECISION = "кандидат: не в справочнике и не в поиске до отдельного решения"
PERMISSION_STATUSES = ("не проверено", "ждём подтверждения", "разрешено", "запрещено")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cand_sources (
    source_id          TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    publication        TEXT NOT NULL,      -- библиографическая ссылка
    doi                TEXT,
    source_url         TEXT NOT NULL,      -- исходная ссылка на таблицу / набор
    license            TEXT NOT NULL,      -- условия набора, как установлены
    permission_status  TEXT NOT NULL CHECK (permission_status IN ('не проверено','ждём подтверждения','разрешено','запрещено')),
    decision           TEXT NOT NULL,
    notes              TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS cand_files (
    id           INTEGER PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES cand_sources(source_id),
    filename     TEXT NOT NULL,
    sha256       TEXT NOT NULL UNIQUE,
    size_bytes   INTEGER NOT NULL,
    content      BLOB NOT NULL,
    panel_choice TEXT NOT NULL,
    imported_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS cand_records (
    id           INTEGER PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES cand_sources(source_id),
    file_id      INTEGER NOT NULL REFERENCES cand_files(id),
    sheet        TEXT NOT NULL,
    row_number   INTEGER NOT NULL,
    record_id    TEXT,
    raw_json     TEXT NOT NULL,             -- исходные ячейки дословно
    positions_json TEXT NOT NULL,           -- {локус: [значение, статус]} для просмотра и сверки
    panel_code   TEXT,
    panel_basis  TEXT NOT NULL,
    flags_json   TEXT NOT NULL,
    UNIQUE (file_id, sheet, row_number)
);
CREATE TRIGGER IF NOT EXISTS cand_records_no_update BEFORE UPDATE ON cand_records
BEGIN SELECT RAISE(ABORT, 'записи кандидатов неизменяемы'); END;
"""


class CandidateError(ValueError):
    pass


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _existing(conn):
    out = []
    for r in conn.execute("SELECT source_id, sheet, row_number, record_id, positions_json FROM cand_records"):
        positions = {k: mk.from_storage(v, st) for k, (v, st) in json.loads(r["positions_json"]).items()}
        out.append((f"кандидат {r['source_id']} {r['sheet']}:{r['row_number']}", r["record_id"] or "", positions))
    return out


def preview(conn, filename: str, data: bytes, panel_choice: str = "AUTO", sheet: str | None = None) -> im.Preview:
    prev = im.build_preview(filename, data, panel_choice, existing=_existing(conn), sheet=sheet)
    if conn.execute("SELECT 1 FROM cand_files WHERE sha256 = ?", (prev.sha256,)).fetchone():
        for r in prev.records:
            r.flags.append("этот файл уже импортирован (тот же SHA-256)")
    return prev


def commit(conn, filename: str, data: bytes, *, source: dict, panel_choice: str = "AUTO",
           sheet: str | None = None) -> int:
    """Записать все корректные строки файла как кандидатов источника. Возвращает число записей."""
    required = ("source_id", "title", "publication", "source_url", "license", "permission_status")
    missing = [k for k in required if not str(source.get(k) or "").strip()]
    if missing:
        raise CandidateError("не заданы сведения об источнике: " + ", ".join(missing))
    if source["permission_status"] not in PERMISSION_STATUSES:
        raise CandidateError(f"статус разрешения: один из {PERMISSION_STATUSES}")
    prev = preview(conn, filename, data, panel_choice, sheet)
    if conn.execute("SELECT 1 FROM cand_files WHERE sha256 = ?", (prev.sha256,)).fetchone():
        raise CandidateError("этот файл уже импортирован (тот же SHA-256); повторный импорт отклонён")
    bad = [s for s in prev.sheets if s.error and s.records]
    if bad:
        raise CandidateError("; ".join(f"{s.name}: {s.error}" for s in bad))
    conn.execute("BEGIN")
    try:
        conn.execute(
            """INSERT INTO cand_sources(source_id, title, publication, doi, source_url, license,
                   permission_status, decision, notes) VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO NOTHING""",
            (source["source_id"], source["title"], source["publication"], source.get("doi"), source["source_url"],
             source["license"], source["permission_status"], DECISION, source.get("notes")),
        )
        fid = conn.execute(
            "INSERT INTO cand_files(source_id, filename, sha256, size_bytes, content, panel_choice) VALUES (?,?,?,?,?,?)",
            (source["source_id"], prev.filename, prev.sha256, prev.size, data, panel_choice)).lastrowid
        n = 0
        for s in prev.sheets:
            for r in s.records:
                if not r.savable:
                    continue
                positions = {k: list(mk.to_storage(v)) for k, v in r.positions.items()}
                conn.execute(
                    """INSERT INTO cand_records(source_id, file_id, sheet, row_number, record_id, raw_json,
                           positions_json, panel_code, panel_basis, flags_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (source["source_id"], fid, r.sheet, r.row_number, r.record_id or None, im.raw_json(r),
                     json.dumps(positions, ensure_ascii=False), s.panel_code, s.panel_basis,
                     json.dumps(r.flags, ensure_ascii=False)))
                n += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return n
