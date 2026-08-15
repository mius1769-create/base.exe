"""
GENOPOISK CRM — слой базы данных (SQLite).

Схема версионируется через таблицу schema_version, чтобы будущие
обновления могли применять миграции без потери данных.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

SCHEMA_VERSION = 1


def get_app_data_dir() -> Path:
    """%APPDATA%/GENOPOISK_CRM/data на Windows; аналог на других ОС для разработки/теста."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        # для разработки/тестирования на Linux/Mac
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    data_dir = Path(base) / "GENOPOISK_CRM" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    override = os.environ.get("GENOPOISK_CRM_DB")
    if override:
        return Path(override)
    return get_app_data_dir() / "genopoisk.db"


def connect(db_path: "Path | str | None" = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit off, we control BEGIN
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- ---------------------------------------------------------------------
-- Справочники
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS test_types (
    code TEXT PRIMARY KEY,           -- внутренний код, напр. 'Y50'
    display_name TEXT NOT NULL,      -- отображаемое имя
    base_deadline_days INTEGER NOT NULL,
    report_allowed INTEGER NOT NULL DEFAULT 1,  -- 0/1
    report_extra_days INTEGER NOT NULL DEFAULT 15,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- Маппинг коммерческих названий (сайт/Ozon/старые названия) -> набор внутренних типов теста.
-- Один коммерческий товар может разворачиваться в несколько тестов (напр. FULL LINE -> Y50 + мтДНК).
CREATE TABLE IF NOT EXISTS product_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commercial_name TEXT NOT NULL UNIQUE,
    test_type_codes TEXT NOT NULL,      -- JSON-массив кодов test_types, напр. '["Y50","MTDNA"]'
    includes_report INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS operators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS delivery_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- Заказы и тесты
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT,                      -- номер заказа сайта/Ozon/источника
    order_status TEXT NOT NULL DEFAULT 'Оплачен',
    customer_name TEXT NOT NULL DEFAULT '',
    contacts TEXT,                      -- телефон / email / TG и т.п.
    delivery_method TEXT,
    delivery_address TEXT,
    tracking_number TEXT,
    order_amount REAL,
    extra_payment REAL,
    refund_amount REAL,
    source TEXT,                        -- Telegram / site / manual / import
    source_raw TEXT,                    -- исходное сообщение (для аудита; без токена)
    needs_review INTEGER NOT NULL DEFAULT 0,  -- 1 = "Требует проверки" (нераспознанный товар)
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tests (
    test_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    gns_number TEXT NOT NULL UNIQUE,     -- уникальный номер теста, напр. GNPSK010940
    test_type TEXT NOT NULL,             -- код из test_types
    report_option TEXT NOT NULL DEFAULT 'Обычный',  -- 'Обычный' | 'С отчётом'
    deadline_days INTEGER,               -- вычисленный норматив (дни)
    deadline_date TEXT,                  -- вычисленная дата дедлайна (ISO), если известна точка отсчёта
    sample_received_at TEXT,             -- ISO datetime
    lab_sent_at TEXT,
    lab_profile_received_at TEXT,
    operator_started_at TEXT,
    operator_name TEXT,
    client_issued_at TEXT,
    result_y TEXT,
    result_mt TEXT,
    comments TEXT,
    is_historical INTEGER NOT NULL DEFAULT 0,   -- импортирован из старой базы (GNS/WGS/Strelka/FULL LINE)
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tests_order ON tests(order_id);
CREATE INDEX IF NOT EXISTS idx_tests_gns ON tests(gns_number);
CREATE INDEX IF NOT EXISTS idx_orders_order_no ON orders(order_no);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_name);

-- Услуга «Отчёт» — не получает GNPSK, привязана к заказу (и опционально к конкретному тесту/комплекту).
CREATE TABLE IF NOT EXISTS report_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    test_id INTEGER REFERENCES tests(test_id),  -- NULL = относится ко всему заказу/комплекту
    added_at TEXT NOT NULL,
    notes TEXT
);

-- ---------------------------------------------------------------------
-- Счётчик GNPSK (транзакционная генерация номеров)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS gnpsk_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    next_number INTEGER NOT NULL,
    prefix TEXT NOT NULL DEFAULT 'GNPSK'
);

-- ---------------------------------------------------------------------
-- Журнал изменений (audit log) — только добавление, без редактирования/удаления
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_name TEXT,
    entity TEXT NOT NULL,          -- 'order' | 'test' | 'report_service' | 'settings' | ...
    entity_id INTEGER,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);

-- Удалённые при импорте записи (нераспознанный/неподдерживаемый исторический тип,
-- напр. "Y-18", "Аутосомы") — НЕ теряются безвозвратно, хранятся здесь как есть.
CREATE TABLE IF NOT EXISTS legacy_excluded_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sheet TEXT,
    source_row INTEGER,
    original_gns_number TEXT,
    original_test_type TEXT,
    raw_row_data TEXT,           -- полное содержимое исходной строки Excel (для аудита)
    reason TEXT,                 -- почему исключена (напр. "неподдерживаемый тип продукта")
    imported_at TEXT NOT NULL
);

-- Журнал операционных событий теста (v1.0 UX: этап "Внутренняя работа").
-- Заменяет собой смысловую роль отдельных колонок tests.lab_sent_at и т.д.,
-- но САМИ эти колонки не удаляются (раздел "не выбрасывать сразу") — при
-- записи события они автоматически зеркалируются, чтобы весь код, который
-- уже на них полагается (расчёт дедлайна, цветовая логика, экспорт),
-- продолжал работать без изменений.
--
-- "Ожидаем получение" НЕ хранится как событие — это производное состояние
-- между 'dispatched' и 'received', вычисляется на лету (раздел ТЗ: "не
-- определять факт доставки автоматически").
CREATE TABLE IF NOT EXISTS test_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL REFERENCES tests(test_id),
    event_type TEXT NOT NULL,        -- order_created/dispatched/received/handed_to_lab/profile_received/in_progress/issued
    event_time TEXT NOT NULL,        -- ISO datetime, может быть скорректировано вручную
    is_manual_correction INTEGER NOT NULL DEFAULT 0,
    recorded_by TEXT,                -- оператор/логин, кто зафиксировал
    recorded_at TEXT NOT NULL,       -- когда фактически нажали кнопку (для аудита, не путать с event_time)
    internal_note TEXT               -- НИКОГДА не показывается клиенту
);

CREATE INDEX IF NOT EXISTS idx_test_events_test ON test_events(test_id);

-- ---------------------------------------------------------------------
-- Настройки (key-value)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------
-- Импорт Excel: ошибочные/неразобранные строки не теряются
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS import_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_batch TEXT NOT NULL,
    row_number INTEGER,
    raw_row TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- Гаплогруппы (вкладка №3): справочник проектов (с вложенностью) и
-- сами записи по тестам. Обе таблицы — только добавление к схеме,
-- существующие таблицы выше не менялись.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES projects(id),
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_parent ON projects(parent_id);

-- Одна запись гаплогруппы на тест (test_number = tests.gns_number).
-- full_name — снимок ФИО из карточки заказа на момент сохранения (не
-- редактируется в этой вкладке напрямую, см. haplogroups_repo.py).
--
-- Резервные поля (заложены в БД, НЕ выводятся в UI вкладки, раздел ТЗ):
--   date_prediction, analyst, review_status, date_issued.
CREATE TABLE IF NOT EXISTS haplogroups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_number TEXT NOT NULL REFERENCES tests(gns_number),
    full_name TEXT,
    project_id INTEGER REFERENCES projects(id),
    y_dna TEXT,
    mt_dna TEXT,
    nevgen_prediction TEXT,
    semargl_prediction TEXT,
    snp_issued TEXT,
    comment TEXT,
    date_prediction TEXT,
    analyst TEXT,
    review_status TEXT,
    date_issued TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_haplogroups_test_number ON haplogroups(test_number);
CREATE INDEX IF NOT EXISTS idx_haplogroups_project ON haplogroups(project_id);
"""

DEFAULT_PROJECTS = [
    # (name, parent_name или None)
    ("Клиенты", None),
    ("Этнопроекты", None),
    ("Башкирский проект", "Этнопроекты"),
    ("Татарский проект", "Этнопроекты"),
]

DEFAULT_TEST_TYPES = [
    # code,        display_name,        base_days, report_allowed, report_extra_days, sort
    ("Y50", "Y Базовый (Y50)", 30, 1, 15, 10),
    ("Y37", "Y Base (Y37)", 30, 1, 15, 20),
    ("MTDNA", "мтДНК", 30, 1, 15, 30),
    ("MITOGENOME", "Митогеном", 30, 1, 15, 40),
    ("STRELKA", "STRELKA", 45, 1, 15, 50),
    ("WGS15", "WGS 15X", 60, 0, 0, 60),
    ("WGS30", "WGS 30X", 60, 0, 0, 70),
]

DEFAULT_DELIVERY_METHODS = ["Ozon", "Почта России", "Курьер", "Яндекс", "СДЭК"]

DEFAULT_SETTINGS = {
    "gnpsk_prefix": "GNPSK",
    "deadline_soon_threshold_days": "5",
    "backup_folder": "",
    "backup_keep_count": "30",
}


def init_db(conn: sqlite3.Connection) -> None:
    """Создаёт схему при первом запуске и заполняет справочники по умолчанию.

    executescript() в sqlite3 сам управляет транзакцией (неявный commit перед
    выполнением скрипта), поэтому DDL выполняется отдельно от последующего
    заполнения справочников, которое оборачивается в свою транзакцию.
    """
    from datetime import datetime

    conn.executescript(SCHEMA_SQL)

    conn.execute("BEGIN")
    try:
        cur = conn.execute("SELECT version FROM schema_version")
        row = cur.fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))

        cur = conn.execute("SELECT COUNT(*) AS c FROM test_types")
        if cur.fetchone()["c"] == 0:
            conn.executemany(
                """INSERT INTO test_types
                   (code, display_name, base_deadline_days, report_allowed, report_extra_days, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                DEFAULT_TEST_TYPES,
            )

        cur = conn.execute("SELECT COUNT(*) AS c FROM delivery_methods")
        if cur.fetchone()["c"] == 0:
            for i, name in enumerate(DEFAULT_DELIVERY_METHODS):
                conn.execute(
                    "INSERT INTO delivery_methods(name, sort_order) VALUES (?, ?)", (name, i)
                )

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value)
            )

        cur = conn.execute("SELECT COUNT(*) AS c FROM gnpsk_counter")
        if cur.fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO gnpsk_counter(id, next_number, prefix) VALUES (1, 1, 'GNPSK')"
            )

        cur = conn.execute("SELECT COUNT(*) AS c FROM projects")
        if cur.fetchone()["c"] == 0:
            now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            name_to_id: dict[str, int] = {}
            for name, parent_name in DEFAULT_PROJECTS:
                parent_id = name_to_id.get(parent_name) if parent_name else None
                cur2 = conn.execute(
                    """INSERT INTO projects (parent_id, name, sort_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (parent_id, name, len(name_to_id), now, now),
                )
                name_to_id[name] = cur2.lastrowid

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    _dedupe_test_events_and_create_unique_index(conn)


def _dedupe_test_events_and_create_unique_index(conn: sqlite3.Connection) -> None:
    """
    Один раз при каждом запуске: если на диске уже есть дубли test_events
    (напр. с версии до исправления бага двойного клика — см. баг-репорт
    "Повторное нажатие кнопки"), сначала подчищает их (оставляя самую
    раннюю запись на каждую пару test_id+event_type), и только потом
    накладывает UNIQUE-индекс. Без этой очистки CREATE UNIQUE INDEX упал
    бы с ошибкой на уже испорченных данных. Идемпотентно — на чистой базе
    ничего не удаляет и не падает при повторных запусках.
    """
    from datetime import datetime

    conn.execute("BEGIN IMMEDIATE")
    try:
        dup_groups = conn.execute(
            """SELECT test_id, event_type, COUNT(*) c, MIN(id) keep_id
               FROM test_events GROUP BY test_id, event_type HAVING c > 1"""
        ).fetchall()
        removed = 0
        for g in dup_groups:
            cur = conn.execute(
                "DELETE FROM test_events WHERE test_id = ? AND event_type = ? AND id != ?",
                (g["test_id"], g["event_type"], g["keep_id"]),
            )
            removed += cur.rowcount
        if removed:
            conn.execute(
                """INSERT INTO audit_log (timestamp, user_name, entity, entity_id, field, old_value, new_value, reason)
                   VALUES (?, 'schema-migration', 'system', NULL, 'test_events_dedup', NULL, ?, ?)""",
                (datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), str(removed),
                 "автоматическая очистка дублей событий перед наложением UNIQUE-индекса (баг двойного клика)"),
            )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_test_events_unique_stage ON test_events(test_id, event_type)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_schema_version(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT version FROM schema_version")
    row = cur.fetchone()
    return row["version"] if row else 0
