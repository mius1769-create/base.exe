"""Схема научного справочника NeSToR (отдельная SQLite, без пользовательских данных).

Принципы:
  * raw_records — значения строго как в первичной таблице; после вставки
    изменять и удалять нельзя (триггеры). Исправления в сырых данных не делаются;
  * transform_rules — каждое преобразование описано правилом со ссылкой на
    основание; derived_values хранит результат отдельно с id правила;
  * qc_findings — ошибки, нули, пропуски, неоднозначности; ничего не исправляют;
  * source_decisions — решение по источнику для каждого сценария использования.
Импорт в справочник выполняется только для источников со статусом «допущен»;
на этапе 1 таких нет, база создаётся пустой.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

REFERENCE_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS sources (
    source_id         TEXT PRIMARY KEY,
    citation          TEXT NOT NULL,
    doi               TEXT NOT NULL,
    dataset_table     TEXT NOT NULL,      -- конкретная таблица/набор, напр. 'Table S6'
    raw_file          TEXT NOT NULL,
    raw_file_sha256   TEXT NOT NULL,
    dataset_terms     TEXT NOT NULL,      -- условия именно набора данных, со ссылкой
    attribution       TEXT NOT NULL,
    decision          TEXT NOT NULL CHECK (decision IN ('допущен','исключён','ждём подтверждения'))
);

CREATE TABLE IF NOT EXISTS raw_records (
    source_id         TEXT NOT NULL REFERENCES sources(source_id),
    record_key        TEXT NOT NULL,      -- идентификатор строки в первичной таблице
    population_label  TEXT NOT NULL,      -- как в первичной таблице, без объединения групп
    raw_markers_json  TEXT NOT NULL,      -- значения как опубликованы
    PRIMARY KEY (source_id, record_key)
);

CREATE TRIGGER IF NOT EXISTS raw_records_no_update BEFORE UPDATE ON raw_records
BEGIN SELECT RAISE(ABORT, 'raw_records неизменяемы: преобразования — в derived_values'); END;
CREATE TRIGGER IF NOT EXISTS raw_records_no_delete BEFORE DELETE ON raw_records
BEGIN SELECT RAISE(ABORT, 'raw_records неизменяемы: исключение источника — через decision'); END;

CREATE TABLE IF NOT EXISTS transform_rules (
    rule_id      TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    basis        TEXT NOT NULL,           -- ссылка на источник правила
    status       TEXT NOT NULL CHECK (status IN ('proposed','approved','rejected'))
);

CREATE TABLE IF NOT EXISTS derived_values (
    source_id   TEXT NOT NULL,
    record_key  TEXT NOT NULL,
    locus       TEXT NOT NULL,
    value_json  TEXT,                     -- NULL = локус исключён правилом
    rule_id     TEXT NOT NULL REFERENCES transform_rules(rule_id),
    PRIMARY KEY (source_id, record_key, locus, rule_id),
    FOREIGN KEY (source_id, record_key) REFERENCES raw_records(source_id, record_key)
);

-- Сведения из первичных таблиц, которых нет в сырой записи кандидата
-- (например, популяционная группа NIST). Значение — как в первичном файле.
CREATE TABLE IF NOT EXISTS record_annotations (
    source_id       TEXT NOT NULL,
    record_key      TEXT NOT NULL,
    field           TEXT NOT NULL,
    value           TEXT NOT NULL,
    origin_file     TEXT NOT NULL,
    origin_sha256   TEXT NOT NULL,
    origin_locator  TEXT NOT NULL,        -- лист/строка/колонка в первичном файле
    PRIMARY KEY (source_id, record_key, field),
    FOREIGN KEY (source_id, record_key) REFERENCES raw_records(source_id, record_key)
);

-- Смысл обозначений первичных таблиц (del, *, ** и т.п.); сами обозначения
-- остаются в raw_records как есть.
CREATE TABLE IF NOT EXISTS value_codes (
    source_id   TEXT NOT NULL,
    code        TEXT NOT NULL,
    meaning     TEXT NOT NULL,
    basis       TEXT NOT NULL,
    confirmed_by_primary INTEGER NOT NULL DEFAULT 0 CHECK (confirmed_by_primary IN (0,1)),
    PRIMARY KEY (source_id, code)
);

CREATE TABLE IF NOT EXISTS qc_findings (
    id          INTEGER PRIMARY KEY,
    check_code  TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    record_key  TEXT,
    locus       TEXT,
    raw_value   TEXT,
    note        TEXT
);
"""


def create_reference(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO reference_meta VALUES ('schema_version', ?)", (str(REFERENCE_SCHEMA_VERSION),))
    conn.execute("INSERT OR IGNORE INTO reference_meta VALUES ('content', 'empty: ни один источник не допущен')")
    conn.commit()
    return conn
