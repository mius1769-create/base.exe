"""
Тесты журнала операционных событий (test_events) — v1.0 UX.

Покрывает:
  - запись событий и зеркалирование в старые колонки (обратная совместимость);
  - производные статусы (client_status_label / internal_status_label);
  - 'Ожидаем получение' как автоматическое, не-событийное состояние;
  - разовую идемпотентную миграцию исторических данных;
  - acceptance-сценарий логистического маршрута;
  - acceptance-сценарий Y50 + мтДНК с независимыми событиями внутри одного заказа.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import business_logic as bl
from app import db as dbmod
from app import repository as repo


@pytest.fixture()
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "test.db")
    dbmod.init_db(c)
    yield c
    c.close()


def _make_test(conn, **kwargs):
    order = repo.NewOrderInput(customer_name="Событийный Тест", test_type_codes=["Y50"], **kwargs)
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    return order_id, test_ids[0]


# ---------------------------------------------------------------------
# Базовая запись событий
# ---------------------------------------------------------------------

def test_order_created_event_recorded_automatically(conn):
    order_id, test_id = _make_test(conn)
    events = repo.list_events_for_test(conn, test_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "order_created"


def test_record_event_appends_and_mirrors_old_column(conn):
    order_id, test_id = _make_test(conn)
    repo.record_event(conn, test_id, "dispatched", operator="operator1")
    repo.record_event(conn, test_id, "received", event_time="2026-09-01T10:00:00", operator="operator1")

    events = repo.list_events_for_test(conn, test_id)
    types = [e["event_type"] for e in events]
    assert types == ["order_created", "dispatched", "received"]

    row = conn.execute("SELECT sample_received_at, deadline_date FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert row["sample_received_at"] == "2026-09-01"
    assert row["deadline_date"] == "2026-10-01"  # 30 дней норматив Y50, отсчёт от received


def test_record_event_unknown_type_rejected(conn):
    order_id, test_id = _make_test(conn)
    with pytest.raises(ValueError):
        repo.record_event(conn, test_id, "телепортирован")


def test_record_event_writes_audit_log(conn):
    order_id, test_id = _make_test(conn)
    repo.record_event(conn, test_id, "dispatched", operator="operator1", note="передали курьеру")
    audit = conn.execute(
        "SELECT * FROM audit_log WHERE entity='test' AND entity_id=? AND field='event:dispatched'", (test_id,)
    ).fetchall()
    assert len(audit) == 1
    assert audit[0]["reason"] == "передали курьеру"


def test_in_progress_event_sets_operator_name(conn):
    order_id, test_id = _make_test(conn)
    repo.record_event(conn, test_id, "in_progress", operator="operator7")
    row = conn.execute("SELECT operator_name FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert row["operator_name"] == "operator7"


# ---------------------------------------------------------------------
# 'Ожидаем получение' — производное состояние, не событие
# ---------------------------------------------------------------------

def test_awaiting_receipt_before_dispatch_and_after():
    assert bl.is_awaiting_receipt([]) is False  # заказ только создан — это отдельно (order_created), не "ожидание в пути"
    assert bl.is_awaiting_receipt([{"event_type": "order_created"}]) is False
    assert bl.is_awaiting_receipt([{"event_type": "order_created"}, {"event_type": "dispatched"}]) is True
    assert bl.is_awaiting_receipt([
        {"event_type": "order_created"}, {"event_type": "dispatched"}, {"event_type": "received"},
    ]) is False


def test_client_status_label_matches_stage():
    assert bl.client_status_label([{"event_type": "order_created"}]) == "Ожидаем получение"
    assert bl.client_status_label([
        {"event_type": "order_created"}, {"event_type": "dispatched"},
    ]) == "Ожидаем получение"
    assert bl.client_status_label([
        {"event_type": "order_created"}, {"event_type": "dispatched"}, {"event_type": "received"},
    ]) == "Образец получен"
    assert bl.client_status_label([
        {"event_type": "order_created"}, {"event_type": "dispatched"}, {"event_type": "received"},
        {"event_type": "handed_to_lab"}, {"event_type": "profile_received"}, {"event_type": "in_progress"},
    ]) == "В обработке"
    assert bl.client_status_label([
        {"event_type": "order_created"}, {"event_type": "dispatched"}, {"event_type": "received"},
        {"event_type": "handed_to_lab"}, {"event_type": "profile_received"}, {"event_type": "in_progress"},
        {"event_type": "issued"},
    ]) == "Выдан клиенту"


def test_receiving_does_not_happen_automatically_from_dispatch_alone(conn):
    """Ключевое требование ТЗ: доставка НИКОГДА не подтверждается автоматически."""
    order_id, test_id = _make_test(conn)
    repo.record_event(conn, test_id, "dispatched", operator="operator1")

    events = [dict(e) for e in repo.list_events_for_test(conn, test_id)]
    assert bl.is_awaiting_receipt(events) is True
    assert bl.client_status_label(events) == "Ожидаем получение"

    # даже если проходит время, без явного record_event('received', ...) статус не меняется
    events_again = [dict(e) for e in repo.list_events_for_test(conn, test_id)]
    assert bl.client_status_label(events_again) == "Ожидаем получение"

    row = conn.execute("SELECT sample_received_at FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert row["sample_received_at"] is None  # ничего не зеркалировано, пока нет 'received'


def test_next_action_event_type_progression(conn):
    order_id, test_id = _make_test(conn)
    assert bl.next_action_event_type([dict(e) for e in repo.list_events_for_test(conn, test_id)]) == "dispatched"

    repo.record_event(conn, test_id, "dispatched")
    assert bl.next_action_event_type([dict(e) for e in repo.list_events_for_test(conn, test_id)]) == "received"

    repo.record_event(conn, test_id, "received")
    assert bl.next_action_event_type([dict(e) for e in repo.list_events_for_test(conn, test_id)]) == "handed_to_lab"


# ---------------------------------------------------------------------
# Ручная корректировка времени
# ---------------------------------------------------------------------

def test_manual_time_correction_is_flagged(conn):
    order_id, test_id = _make_test(conn)
    repo.record_event(conn, test_id, "dispatched", event_time="2026-01-01T08:00:00", is_manual_correction=True,
                       operator="operator1", note="забыли отметить вовремя, восстановили по накладной")
    events = repo.list_events_for_test(conn, test_id)
    dispatched = [e for e in events if e["event_type"] == "dispatched"][0]
    assert dispatched["is_manual_correction"] == 1
    assert dispatched["event_time"] == "2026-01-01T08:00:00"


# ---------------------------------------------------------------------
# Миграция исторических данных — идемпотентная, ничего не теряет
# ---------------------------------------------------------------------

def test_migration_backfills_events_from_old_columns(conn):
    order = repo.NewOrderInput(customer_name="Исторический Клиент", test_type_codes=["Y50"])
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    test_id = test_ids[0]

    # удаляем автоматически созданное order_created событие, чтобы имитировать
    # "старую" запись, которая существовала ДО появления test_events
    conn.execute("DELETE FROM test_events WHERE test_id=?", (test_id,))
    conn.execute(
        """UPDATE tests SET sample_received_at=?, lab_sent_at=?, lab_profile_received_at=?,
                             operator_started_at=?, operator_name=?, client_issued_at=?
           WHERE test_id=?""",
        ("2026-01-01", "2026-01-03T10:00:00", "2026-01-10T12:00:00",
         "2026-01-11T09:00:00", "operator5", "2026-02-01T15:00:00", test_id),
    )

    migrated = repo.migrate_existing_tests_to_events(conn)
    assert migrated == 1

    events = repo.list_events_for_test(conn, test_id)
    types = {e["event_type"] for e in events}
    assert types == {"order_created", "received", "handed_to_lab", "profile_received", "in_progress", "issued"}

    in_progress = [e for e in events if e["event_type"] == "in_progress"][0]
    assert in_progress["recorded_by"] == "operator5"

    # старые колонки не тронуты
    row = conn.execute("SELECT sample_received_at FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert row["sample_received_at"] == "2026-01-01"


def test_migration_is_idempotent_and_skips_already_migrated(conn):
    order_id, test_id = _make_test(conn)
    first = repo.migrate_existing_tests_to_events(conn)
    assert first == 0  # у теста уже есть order_created (создан через create_order_with_tests)

    events_before = len(repo.list_events_for_test(conn, test_id))
    second = repo.migrate_existing_tests_to_events(conn)
    assert second == 0
    assert len(repo.list_events_for_test(conn, test_id)) == events_before  # не задвоилось


# ---------------------------------------------------------------------
# Acceptance: полный логистический маршрут
# ---------------------------------------------------------------------

def test_acceptance_full_logistics_route(conn):
    order_id, test_id = _make_test(conn)

    def status():
        evs = [dict(e) for e in repo.list_events_for_test(conn, test_id)]
        return bl.client_status_label(evs), bl.internal_status_label(evs)

    assert status() == ("Ожидаем получение", "Заказ создан")

    repo.record_event(conn, test_id, "dispatched", operator="operator1")
    assert status() == ("Ожидаем получение", "Ожидаем получение")

    repo.record_event(conn, test_id, "received", operator="operator1")
    assert status()[0] == "Образец получен"

    repo.record_event(conn, test_id, "handed_to_lab", operator="operator1")
    repo.record_event(conn, test_id, "profile_received", operator="operator1")
    repo.record_event(conn, test_id, "in_progress", operator="operator1")
    assert status()[0] == "В обработке"
    assert status()[1] == "Взято в работу"

    repo.record_event(conn, test_id, "issued", operator="operator1")
    assert status() == ("Выдан клиенту", "Выдано клиенту")

    # дедлайн считается от 'received', не от 'dispatched' и не от 'order_created'
    row = conn.execute("SELECT sample_received_at, deadline_days FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert row["sample_received_at"] is not None
    assert row["deadline_days"] == 30


# ---------------------------------------------------------------------
# Acceptance: Y50 + мтДНК — независимые внутренние события
# ---------------------------------------------------------------------

def test_acceptance_y50_mtdna_independent_events(conn):
    order = repo.NewOrderInput(customer_name="Комплектный Тест Заказович", order_no="OZ-3480",
                                test_type_codes=["Y50", "MTDNA"], report_added=True)
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    y50_id, mtdna_id = test_ids

    siblings = repo.list_sibling_tests_for_order(conn, order_id)
    assert len(siblings) == 2
    assert {s["test_type"] for s in siblings} == {"Y50", "MTDNA"}

    # события Y50 продвигаются, mtDNA — нет
    repo.record_event(conn, y50_id, "dispatched", operator="operator1")
    repo.record_event(conn, y50_id, "received", operator="operator1")
    repo.record_event(conn, y50_id, "handed_to_lab", operator="operator1")
    repo.record_event(conn, y50_id, "profile_received", operator="operator1")
    repo.record_event(conn, y50_id, "in_progress", operator="operator1")

    y50_events = [dict(e) for e in repo.list_events_for_test(conn, y50_id)]
    mtdna_events = [dict(e) for e in repo.list_events_for_test(conn, mtdna_id)]

    assert bl.internal_status_label(y50_events) == "Взято в работу"
    assert bl.internal_status_label(mtdna_events) == "Заказ создан"  # не затронут событиями Y50

    # выдача одного теста не выдаёт автоматически второй
    repo.record_event(conn, y50_id, "issued", operator="operator1")
    y50_events = [dict(e) for e in repo.list_events_for_test(conn, y50_id)]
    mtdna_events = [dict(e) for e in repo.list_events_for_test(conn, mtdna_id)]
    assert bl.client_status_label(y50_events) == "Выдан клиенту"
    assert bl.client_status_label(mtdna_events) == "Ожидаем получение"

    # оба теста — один заказ
    y50_row = conn.execute("SELECT order_id FROM tests WHERE test_id=?", (y50_id,)).fetchone()
    mtdna_row = conn.execute("SELECT order_id FROM tests WHERE test_id=?", (mtdna_id,)).fetchone()
    assert y50_row["order_id"] == mtdna_row["order_id"] == order_id
