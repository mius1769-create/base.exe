"""
GENOPOISK CRM — репозиторий: операции с БД поверх сырых SQL-запросов.

Все существенные ручные изменения (раздел 13) пишутся в audit_log
(раздел 14). Записи не удаляются физически (раздел 13, 25) — только
архивируются (is_archived) с обязательной записью в журнал.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from . import business_logic as bl

ISO = "%Y-%m-%dT%H:%M:%S"


def now_iso() -> str:
    return datetime.now().strftime(ISO)


def parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    """Разбирает ISO datetime ('YYYY-MM-DDTHH:MM:SS') либо просто ISO date
    ('YYYY-MM-DD', полночь) — оба формата встречаются в БД в зависимости от поля."""
    if not value:
        return None
    try:
        return datetime.strptime(value, ISO)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    dt = parse_iso_dt(value)
    return dt.date() if dt else None


# ---------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------

def write_audit(
    conn: sqlite3.Connection,
    *,
    user_name: Optional[str],
    entity: str,
    entity_id: Optional[int],
    field: Optional[str],
    old_value: Any,
    new_value: Any,
    reason: Optional[str] = None,
) -> None:
    conn.execute(
        """INSERT INTO audit_log
           (timestamp, user_name, entity, entity_id, field, old_value, new_value, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            now_iso(),
            user_name,
            entity,
            entity_id,
            field,
            None if old_value is None else str(old_value),
            None if new_value is None else str(new_value),
            reason,
        ),
    )


# ---------------------------------------------------------------------
# Справочник типов тестов
# ---------------------------------------------------------------------

def get_test_type(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM test_types WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ValueError(f"Неизвестный тип теста: {code}")
    return row


def list_test_types(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM test_types"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY sort_order"
    return conn.execute(q).fetchall()


# ---------------------------------------------------------------------
# Создание заказа и разбор на тесты (раздел 5)
# ---------------------------------------------------------------------

@dataclass
class NewOrderInput:
    order_no: str = ""
    order_status: str = "Оплачен"
    customer_name: str = ""
    contacts: str = ""
    delivery_method: str = ""
    delivery_address: str = ""
    tracking_number: str = ""
    order_amount: Optional[float] = None
    extra_payment: Optional[float] = None
    refund_amount: Optional[float] = None
    source: str = "manual"
    source_raw: Optional[str] = None
    needs_review: bool = False
    test_type_codes: list[str] = field(default_factory=list)  # напр. ["Y50", "MTDNA"]
    report_added: bool = False
    sample_received_at: Optional[date] = None
    user_name: Optional[str] = None


def create_order_with_tests(conn: sqlite3.Connection, data: NewOrderInput) -> tuple[int, list[int]]:
    """
    Создаёт заказ и один тест на каждый код в test_type_codes (раздел 5:
    "Y50 + mtDNA -> два теста"). Если report_added=True — создаёт запись
    report_services (без собственного GNPSK, раздел 2.3).

    Возвращает (order_id, [test_id, ...]).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO orders
               (order_no, order_status, customer_name, contacts, delivery_method,
                delivery_address, tracking_number, order_amount, extra_payment,
                refund_amount, source, source_raw, needs_review, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.order_no, data.order_status, data.customer_name, data.contacts,
                data.delivery_method, data.delivery_address, data.tracking_number,
                data.order_amount, data.extra_payment, data.refund_amount,
                data.source, data.source_raw, int(data.needs_review), ts, ts,
            ),
        )
        order_id = cur.lastrowid
        write_audit(conn, user_name=data.user_name, entity="order", entity_id=order_id,
                    field=None, old_value=None, new_value="создан", reason="создание заказа")

        test_ids: list[int] = []
        report_option = "С отчётом" if data.report_added else "Обычный"

        for code in bl.split_order_into_test_types(data.test_type_codes):
            tt = get_test_type(conn, code)
            if data.report_added:
                bl.validate_report_option(report_option, bool(tt["report_allowed"]))

            deadline = bl.calculate_deadline(
                base_deadline_days=tt["base_deadline_days"],
                report_option=report_option,
                report_allowed=bool(tt["report_allowed"]),
                report_extra_days=tt["report_extra_days"],
                sample_received_at=data.sample_received_at,
            )

            gns = bl._reserve_next_gnpsk_locked(conn)  # мы уже внутри BEGIN IMMEDIATE этой функции

            cur = conn.execute(
                """INSERT INTO tests
                   (order_id, gns_number, test_type, report_option, deadline_days, deadline_date,
                    sample_received_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    order_id, gns, code, report_option, deadline.deadline_days,
                    deadline.deadline_date.isoformat() if deadline.deadline_date else None,
                    data.sample_received_at.isoformat() if data.sample_received_at else None,
                    ts, ts,
                ),
            )
            test_id = cur.lastrowid
            test_ids.append(test_id)
            write_audit(conn, user_name=data.user_name, entity="test", entity_id=test_id,
                        field=None, old_value=None, new_value=f"создан ({code}, {gns})",
                        reason="создание теста из заказа")
            # событие order_created — сразу, в этой же транзакции (без вложенного
            # BEGIN — record_event() тут не используем именно поэтому)
            conn.execute(
                """INSERT INTO test_events (test_id, event_type, event_time, is_manual_correction,
                                             recorded_by, recorded_at, internal_note)
                   VALUES (?, 'order_created', ?, 0, ?, ?, NULL)""",
                (test_id, ts, data.user_name, ts),
            )
            if data.sample_received_at:
                # если дата образца известна уже при создании (напр. импорт/ручной ввод
                # "образец уже получен") — сразу фиксируем и событие 'received'
                conn.execute(
                    """INSERT INTO test_events (test_id, event_type, event_time, is_manual_correction,
                                                 recorded_by, recorded_at, internal_note)
                       VALUES (?, 'received', ?, 0, ?, ?, NULL)""",
                    (test_id, f"{data.sample_received_at.isoformat()}T00:00:00", data.user_name, ts),
                )

        if data.report_added:
            for test_id in test_ids:
                conn.execute(
                    """INSERT INTO report_services (order_id, test_id, added_at, notes)
                       VALUES (?, ?, ?, ?)""",
                    (order_id, test_id, ts, None),
                )

        conn.execute("COMMIT")
        return order_id, test_ids
    except Exception:
        conn.execute("ROLLBACK")
        raise





# ---------------------------------------------------------------------
# Обновление теста (раздел 11, 13) — с пересчётом дедлайна и audit log
# ---------------------------------------------------------------------

EDITABLE_TEST_FIELDS = {
    "test_type", "report_option", "sample_received_at", "lab_sent_at",
    "lab_profile_received_at", "operator_started_at", "operator_name",
    "client_issued_at", "result_y", "result_mt", "comments",
}

DEADLINE_AFFECTING_FIELDS = {"test_type", "report_option", "sample_received_at"}


def _update_test_fields_locked(
    conn: sqlite3.Connection,
    test_id: int,
    changes: dict[str, Any],
    *,
    user_name: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Тело update_test_fields БЕЗ управления транзакцией — вызывающий код
    уже обязан быть внутри BEGIN IMMEDIATE. Нужно, чтобы record_event() мог
    переиспользовать пересчёт дедлайна в своей собственной транзакции,
    не открывая вложенный BEGIN (SQLite их не поддерживает)."""
    unknown = set(changes) - EDITABLE_TEST_FIELDS
    if unknown:
        raise ValueError(f"Недопустимые поля для редактирования: {unknown}")

    row = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_id,)).fetchone()
    if row is None:
        raise ValueError(f"Тест {test_id} не найден")

    for field_name, new_value in changes.items():
        old_value = row[field_name]
        if str(old_value) == str(new_value):
            continue
        conn.execute(f"UPDATE tests SET {field_name} = ? WHERE test_id = ?", (new_value, test_id))
        write_audit(conn, user_name=user_name, entity="test", entity_id=test_id,
                    field=field_name, old_value=old_value, new_value=new_value, reason=reason)

    if DEADLINE_AFFECTING_FIELDS & set(changes):
        row2 = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_id,)).fetchone()
        tt = get_test_type(conn, row2["test_type"])
        sample_date = parse_iso_date(row2["sample_received_at"])
        deadline = bl.calculate_deadline(
            base_deadline_days=tt["base_deadline_days"],
            report_option=row2["report_option"],
            report_allowed=bool(tt["report_allowed"]),
            report_extra_days=tt["report_extra_days"],
            sample_received_at=sample_date,
        )
        old_days, old_date = row2["deadline_days"], row2["deadline_date"]
        new_date = deadline.deadline_date.isoformat() if deadline.deadline_date else None
        conn.execute(
            "UPDATE tests SET deadline_days = ?, deadline_date = ? WHERE test_id = ?",
            (deadline.deadline_days, new_date, test_id),
        )
        if old_days != deadline.deadline_days or old_date != new_date:
            write_audit(conn, user_name=user_name, entity="test", entity_id=test_id,
                        field="deadline_date", old_value=old_date, new_value=new_date,
                        reason="пересчёт срока")

    conn.execute("UPDATE tests SET updated_at = ? WHERE test_id = ?", (now_iso(), test_id))


def update_test_fields(
    conn: sqlite3.Connection,
    test_id: int,
    changes: dict[str, Any],
    *,
    user_name: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """
    Обновляет поля теста. Если меняется тип/комплектация/дата образца —
    дедлайн пересчитывается автоматически (раздел 7), а само изменение
    попадает в audit log с old/new значением (раздел 7, 13, 14).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        _update_test_fields_locked(conn, test_id, changes, user_name=user_name, reason=reason)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise



# ---------------------------------------------------------------------
# Финансовые изменения заказа: доплата, возврат, отмена (раздел 13)
# ---------------------------------------------------------------------

def apply_order_financial_change(
    conn: sqlite3.Connection,
    order_id: int,
    *,
    extra_payment: Optional[float] = None,
    refund_amount: Optional[float] = None,
    new_status: Optional[str] = None,
    comment: str,
    user_name: Optional[str] = None,
) -> None:
    """Заказ никогда не удаляется физически — только меняется статус/суммы, с записью причины."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            raise ValueError(f"Заказ {order_id} не найден")

        if extra_payment is not None and extra_payment != row["extra_payment"]:
            conn.execute("UPDATE orders SET extra_payment = ? WHERE order_id = ?", (extra_payment, order_id))
            write_audit(conn, user_name=user_name, entity="order", entity_id=order_id,
                        field="extra_payment", old_value=row["extra_payment"], new_value=extra_payment,
                        reason=comment)

        if refund_amount is not None and refund_amount != row["refund_amount"]:
            conn.execute("UPDATE orders SET refund_amount = ? WHERE order_id = ?", (refund_amount, order_id))
            write_audit(conn, user_name=user_name, entity="order", entity_id=order_id,
                        field="refund_amount", old_value=row["refund_amount"], new_value=refund_amount,
                        reason=comment)

        if new_status is not None and new_status != row["order_status"]:
            conn.execute("UPDATE orders SET order_status = ? WHERE order_id = ?", (new_status, order_id))
            write_audit(conn, user_name=user_name, entity="order", entity_id=order_id,
                        field="order_status", old_value=row["order_status"], new_value=new_status,
                        reason=comment)

        conn.execute("UPDATE orders SET updated_at = ? WHERE order_id = ?", (now_iso(), order_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def archive_order(conn: sqlite3.Connection, order_id: int, *, reason: str, user_name: Optional[str] = None) -> None:
    """Логическое удаление заказа (раздел 14: удаление либо запрещено, либо только логическое)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE orders SET is_archived = 1, updated_at = ? WHERE order_id = ?",
                     (now_iso(), order_id))
        write_audit(conn, user_name=user_name, entity="order", entity_id=order_id,
                    field="is_archived", old_value=0, new_value=1, reason=reason)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------
# Поиск / фильтры (раздел 17)
# ---------------------------------------------------------------------

QUICK_FILTERS = {
    "all": None,
    "in_progress": "operator_started_at IS NOT NULL AND client_issued_at IS NULL",
    "profile_received": "lab_profile_received_at IS NOT NULL AND operator_started_at IS NULL",
    "in_lab": "lab_sent_at IS NOT NULL AND lab_profile_received_at IS NULL",
    "urgent": None,     # обрабатывается в Python (нужен расчёт дней до дедлайна)
    "overdue": None,    # аналогично
    "issued": "client_issued_at IS NOT NULL",
}


def list_tests_with_order(
    conn: sqlite3.Connection,
    *,
    search: Optional[str] = None,
    quick_filter: str = "all",
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    q = """
        SELECT t.*, o.order_no, o.customer_name, o.contacts, o.order_status
        FROM tests t
        JOIN orders o ON o.order_id = t.order_id
        WHERE 1=1
    """
    params: list[Any] = []

    if not include_archived:
        q += " AND t.is_archived = 0 AND o.is_archived = 0"

    if search:
        like = f"%{search}%"
        q += """ AND (
            t.gns_number LIKE ? OR o.order_no LIKE ? OR o.customer_name LIKE ?
            OR o.contacts LIKE ? OR t.test_type LIKE ?
        )"""
        params += [like, like, like, like, like]

    cond = QUICK_FILTERS.get(quick_filter)
    if cond:
        q += f" AND {cond}"

    q += " ORDER BY t.updated_at DESC"
    rows = conn.execute(q, params).fetchall()

    if quick_filter in ("urgent", "overdue"):
        today = date.today()
        filtered = []
        for r in rows:
            if r["client_issued_at"]:
                continue
            dl = parse_iso_date(r["deadline_date"])
            if dl is None:
                continue
            days_left = (dl - today).days
            if quick_filter == "overdue" and days_left < 0:
                filtered.append(r)
            elif quick_filter == "urgent" and 0 <= days_left <= 5:
                filtered.append(r)
        rows = filtered

    return rows


# ---------------------------------------------------------------------
# Продукт -> тип теста маппинг (раздел 3, 15)
# ---------------------------------------------------------------------

def resolve_commercial_name(conn: sqlite3.Connection, commercial_name: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM product_mappings WHERE commercial_name = ?", (commercial_name,)
    ).fetchone()
    if row is None:
        return None
    return {
        "test_type_codes": json.loads(row["test_type_codes"]),
        "includes_report": bool(row["includes_report"]),
    }


# ---------------------------------------------------------------------
# Журнал операционных событий (test_events) — v1.0 UX
# ---------------------------------------------------------------------

# Событие -> какую старую колонку зеркалировать (обратная совместимость:
# дедлайн/цветовая логика/экспорт продолжают читать старые колонки как есть).
_EVENT_MIRROR_FIELD = {
    "received": "sample_received_at",
    "handed_to_lab": "lab_sent_at",
    "profile_received": "lab_profile_received_at",
    "in_progress": "operator_started_at",
    "issued": "client_issued_at",
}


def record_event(
    conn: sqlite3.Connection,
    test_id: int,
    event_type: str,
    *,
    event_time: Optional[str] = None,
    operator: Optional[str] = None,
    is_manual_correction: bool = False,
    note: Optional[str] = None,
    user_name: Optional[str] = None,
) -> int:
    """
    Фиксирует операционное событие теста (раздел ТЗ: "все действия
    фиксируются как события с автоматической датой/временем и возможностью
    ручной корректировки"). event_time по умолчанию — текущий момент;
    передайте свой ISO-datetime для ручной корректировки задним числом
    (is_manual_correction=True тогда стоит проставить явно).

    Автоматически зеркалирует событие в соответствующую старую колонку
    tests (см. _EVENT_MIRROR_FIELD), включая пересчёт дедлайна для
    'received' — так что вся существующая бизнес-логика (calculate_deadline,
    calculate_row_color, exporter) продолжает работать без изменений.

    Возвращает id созданной записи test_events.
    """
    if event_type not in bl.EVENT_ORDER:
        raise ValueError(f"Неизвестный тип события: {event_type!r}. Допустимые: {bl.EVENT_ORDER}")

    ts = now_iso()
    event_time_iso = event_time or ts

    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            """INSERT INTO test_events
               (test_id, event_type, event_time, is_manual_correction, recorded_by, recorded_at, internal_note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (test_id, event_type, event_time_iso, int(is_manual_correction), operator, ts, note),
        )
        event_id = cur.lastrowid

        write_audit(
            conn, user_name=user_name or operator, entity="test", entity_id=test_id,
            field=f"event:{event_type}", old_value=None, new_value=event_time_iso,
            reason=note or ("ручная корректировка" if is_manual_correction else "внутреннее событие"),
        )

        mirror_field = _EVENT_MIRROR_FIELD.get(event_type)
        if mirror_field:
            changes: dict[str, Any] = {}
            if mirror_field == "sample_received_at":
                changes[mirror_field] = event_time_iso[:10]  # эта колонка хранит только дату
            else:
                changes[mirror_field] = event_time_iso
            if event_type == "in_progress" and operator:
                changes["operator_name"] = operator
            _update_test_fields_locked(conn, test_id, changes, user_name=user_name or operator,
                                        reason="зеркалирование из test_events")

        conn.execute("COMMIT")
        return event_id
    except Exception:
        conn.execute("ROLLBACK")
        raise


def list_events_for_test(conn: sqlite3.Connection, test_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM test_events WHERE test_id = ? ORDER BY event_time ASC, id ASC",
        (test_id,),
    ).fetchall()


def list_events_for_test_ids(conn: sqlite3.Connection, test_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    """Пакетная загрузка событий сразу для многих тестов (список тестов на
    главном экране) — чтобы не делать по отдельному запросу на каждую строку."""
    if not test_ids:
        return {}
    placeholders = ",".join("?" * len(test_ids))
    rows = conn.execute(
        f"SELECT * FROM test_events WHERE test_id IN ({placeholders}) ORDER BY event_time ASC, id ASC",
        test_ids,
    ).fetchall()
    result: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        result.setdefault(r["test_id"], []).append(r)
    return result


def list_sibling_tests_for_order(conn: sqlite3.Connection, order_id: int) -> list[sqlite3.Row]:
    """Все тесты того же заказа (для блока 'Y50 + мтДНК — 2 теста' в карточке)."""
    return conn.execute(
        "SELECT * FROM tests WHERE order_id = ? ORDER BY test_id ASC", (order_id,)
    ).fetchall()


def migrate_existing_tests_to_events(conn: sqlite3.Connection, *, user_name: str = "schema-migration") -> int:
    """
    Разовая, идемпотентная миграция: для тестов, у которых ещё нет НИ ОДНОЙ
    записи в test_events, создаёт события на основе уже существующих
    колонок дат. Старые колонки НЕ трогает и НЕ удаляет (раздел ТЗ:
    "старые поля можно не выбрасывать сразу... миграция схемы, а не
    пересоздание данных"). Безопасно вызывать при каждом запуске приложения —
    уже мигрированные тесты просто пропускаются.

    Возвращает число тестов, для которых были созданы события.
    """
    rows = conn.execute(
        """SELECT t.test_id, t.created_at, t.sample_received_at, t.lab_sent_at,
                  t.lab_profile_received_at, t.operator_started_at, t.operator_name,
                  t.client_issued_at
           FROM tests t
           WHERE NOT EXISTS (SELECT 1 FROM test_events e WHERE e.test_id = t.test_id)"""
    ).fetchall()

    migrated = 0
    for r in rows:
        conn.execute("BEGIN IMMEDIATE")
        try:
            ts = now_iso()

            def add(event_type: str, dt: Optional[str], operator: Optional[str] = None) -> None:
                if not dt:
                    return
                # старые даты вида YYYY-MM-DD дополняем временем полуночи, чтобы
                # хранить единый формат ISO datetime в test_events
                event_time = dt if "T" in dt else f"{dt}T00:00:00"
                conn.execute(
                    """INSERT INTO test_events
                       (test_id, event_type, event_time, is_manual_correction, recorded_by, recorded_at, internal_note)
                       VALUES (?, ?, ?, 0, ?, ?, ?)""",
                    (r["test_id"], event_type, event_time, operator, ts, "миграция из старых колонок tests"),
                )

            add("order_created", r["created_at"])
            add("received", r["sample_received_at"])
            add("handed_to_lab", r["lab_sent_at"])
            add("profile_received", r["lab_profile_received_at"])
            add("in_progress", r["operator_started_at"], r["operator_name"])
            add("issued", r["client_issued_at"])

            write_audit(conn, user_name=user_name, entity="test", entity_id=r["test_id"],
                        field=None, old_value=None, new_value="test_events заполнены из старых колонок",
                        reason="разовая миграция схемы на test_events")

            conn.execute("COMMIT")
            migrated += 1
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return migrated


def list_audit_for_order(conn: sqlite3.Connection, order_id: int) -> list[sqlite3.Row]:
    """
    История изменений для карточки заказа (задача 5 финального этапа):
    все записи audit_log, относящиеся к самому заказу И к любому из его
    тестов, в хронологическом порядке. Возвращает 'сырые' строки audit_log
    плюс test_gns_number (NULL для записей самого заказа), чтобы в UI можно
    было показать, к какому именно тесту относится изменение.
    """
    return conn.execute(
        """
        SELECT a.*, NULL AS test_gns_number
        FROM audit_log a
        WHERE a.entity = 'order' AND a.entity_id = ?

        UNION ALL

        SELECT a.*, t.gns_number AS test_gns_number
        FROM audit_log a
        JOIN tests t ON t.test_id = a.entity_id
        WHERE a.entity = 'test' AND t.order_id = ?

        ORDER BY timestamp ASC
        """,
        (order_id, order_id),
    ).fetchall()


def upsert_product_mapping(
    conn: sqlite3.Connection,
    commercial_name: str,
    test_type_codes: list[str],
    includes_report: bool,
    notes: Optional[str] = None,
) -> None:
    conn.execute(
        """INSERT INTO product_mappings (commercial_name, test_type_codes, includes_report, notes)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(commercial_name) DO UPDATE SET
             test_type_codes = excluded.test_type_codes,
             includes_report = excluded.includes_report,
             notes = excluded.notes""",
        (commercial_name, json.dumps(test_type_codes, ensure_ascii=False), int(includes_report), notes),
    )


def list_product_mappings(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM product_mappings ORDER BY commercial_name").fetchall()
    return [
        {
            "id": r["id"],
            "commercial_name": r["commercial_name"],
            "test_type_codes": json.loads(r["test_type_codes"]),
            "includes_report": bool(r["includes_report"]),
            "notes": r["notes"],
        }
        for r in rows
    ]


def delete_product_mapping(conn: sqlite3.Connection, mapping_id: int) -> None:
    conn.execute("DELETE FROM product_mappings WHERE id = ?", (mapping_id,))
