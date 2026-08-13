"""
Полный acceptance-тест сценария из раздела 24 ТЗ / задачи 5 финального ТЗ:
  "Y50 + mtDNA + отчёт" -> норматив 45 дней у КАЖДОГО из двух тестов,
  два разных GNPSK, один order_id, независимые статусы/цвета по каждому тесту,
  полный жизненный цикл (раздел 6) с проверкой цветовой логики (раздел 8) на
  каждом шаге для каждого теста отдельно.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import db as dbmod
from app import repository as repo
from app import business_logic as bl


@pytest.fixture()
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "acceptance.db")
    dbmod.init_db(c)
    yield c
    c.close()


def color_of(conn, test_id, today_date, soon_days=5):
    row = conn.execute("SELECT * FROM tests WHERE test_id=?", (test_id,)).fetchone()
    return bl.calculate_row_color(
        client_issued_at=repo.parse_iso_dt(row["client_issued_at"]),
        deadline_date=repo.parse_iso_date(row["deadline_date"]),
        operator_started_at=repo.parse_iso_dt(row["operator_started_at"]),
        today=today_date,
        soon_threshold_days=soon_days,
    )


def test_y50_mtdna_plus_report_full_scenario(conn, capsys):
    SAMPLE_DATE = date(2026, 1, 1)

    order = repo.NewOrderInput(
        order_no="ACC-1001",
        customer_name="Приёмочный Тест Тестович",
        contacts="+7 900 000-11-22",
        test_type_codes=["Y50", "MTDNA"],
        report_added=True,
        sample_received_at=SAMPLE_DATE,
        order_amount=15000.0,
        source="manual",
        user_name="acceptance-test",
    )
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    assert len(test_ids) == 2, "Ожидались ровно 2 теста"

    tests = {conn.execute("SELECT * FROM tests WHERE test_id=?", (tid,)).fetchone()["test_type"]: tid
             for tid in test_ids}
    assert set(tests.keys()) == {"Y50", "MTDNA"}
    y50_id, mtdna_id = tests["Y50"], tests["MTDNA"]

    y50_row = conn.execute("SELECT * FROM tests WHERE test_id=?", (y50_id,)).fetchone()
    mtdna_row = conn.execute("SELECT * FROM tests WHERE test_id=?", (mtdna_id,)).fetchone()

    # --- Проверка 1: два РАЗНЫХ GNPSK, один заказ ---
    assert y50_row["gns_number"] != mtdna_row["gns_number"], "GNPSK должны различаться"
    assert y50_row["order_id"] == mtdna_row["order_id"] == order_id

    # --- Проверка 2: норматив 45 дней у ОБОИХ (30 база + 15 за отчёт) ---
    assert y50_row["deadline_days"] == 45
    assert mtdna_row["deadline_days"] == 45
    expected_deadline = (SAMPLE_DATE + timedelta(days=45)).isoformat()
    assert y50_row["deadline_date"] == expected_deadline
    assert mtdna_row["deadline_date"] == expected_deadline

    # --- Проверка 3: report_option = 'С отчётом' у обоих, report_services для обоих, без GNPSK ---
    assert y50_row["report_option"] == "С отчётом"
    assert mtdna_row["report_option"] == "С отчётом"
    report_rows = conn.execute("SELECT * FROM report_services WHERE order_id=?", (order_id,)).fetchall()
    assert len(report_rows) == 2
    assert {r["test_id"] for r in report_rows} == {y50_id, mtdna_id}
    # отчёт не получил собственный GNPSK — у report_services нет такого поля вообще (см. схему БД)

    # --- Проверка 4: полный жизненный цикл (раздел 6) с независимостью Y50 / mtDNA ---
    soon_days = 5
    today = SAMPLE_DATE

    c_y50 = color_of(conn, y50_id, today, soon_days)
    c_mt = color_of(conn, mtdna_id, today, soon_days)
    assert c_y50 == bl.RowColor.NORMAL and c_mt == bl.RowColor.NORMAL

    conn.execute("UPDATE tests SET lab_sent_at=? WHERE test_id=?", ("2026-01-02T09:00:00", y50_id))
    mt_lab_sent = conn.execute("SELECT lab_sent_at FROM tests WHERE test_id=?", (mtdna_id,)).fetchone()["lab_sent_at"]
    assert mt_lab_sent is None, "Изменение Y50 не должно затронуть mtDNA"

    conn.execute("UPDATE tests SET lab_profile_received_at=? WHERE test_id=?", ("2026-01-10T14:00:00", y50_id))
    y50_after_profile = conn.execute("SELECT operator_started_at FROM tests WHERE test_id=?", (y50_id,)).fetchone()
    assert y50_after_profile["operator_started_at"] is None, "'Профиль получен' не должен автоматически ставить 'В работу'"

    repo.update_test_fields(conn, y50_id, {"operator_started_at": "2026-01-11T10:00:00"}, user_name="operator1")
    c_y50 = color_of(conn, y50_id, today, soon_days)
    c_mt = color_of(conn, mtdna_id, today, soon_days)
    assert c_y50 == bl.RowColor.YELLOW
    assert c_mt == bl.RowColor.NORMAL, "mtDNA должен остаться NORMAL — независимый статус"

    near_deadline_day = date.fromisoformat(y50_row["deadline_date"]) - timedelta(days=5)
    assert color_of(conn, y50_id, near_deadline_day, soon_days) == bl.RowColor.PURPLE
    assert color_of(conn, mtdna_id, near_deadline_day, soon_days) == bl.RowColor.PURPLE

    after_deadline_day = date.fromisoformat(y50_row["deadline_date"]) + timedelta(days=1)
    assert color_of(conn, y50_id, after_deadline_day, soon_days) == bl.RowColor.RED
    assert color_of(conn, mtdna_id, after_deadline_day, soon_days) == bl.RowColor.RED

    repo.update_test_fields(conn, y50_id, {"client_issued_at": "2026-02-20T16:00:00"}, user_name="operator1")
    assert color_of(conn, y50_id, after_deadline_day, soon_days) == bl.RowColor.GREEN
    assert color_of(conn, mtdna_id, after_deadline_day, soon_days) == bl.RowColor.RED, \
        "mtDNA всё ещё просрочен и не выдан — независимый статус"

    repo.update_test_fields(conn, mtdna_id, {"client_issued_at": "2026-02-25T11:00:00"}, user_name="operator1")
    assert color_of(conn, mtdna_id, after_deadline_day, soon_days) == bl.RowColor.GREEN

    # --- Проверка 5: audit log зафиксировал ключевые изменения по обоим тестам независимо ---
    audit_rows = conn.execute(
        "SELECT * FROM audit_log WHERE entity='test' AND entity_id IN (?, ?) ORDER BY id", (y50_id, mtdna_id)
    ).fetchall()
    fields_logged = [r["field"] for r in audit_rows if r["field"]]
    assert "operator_started_at" in fields_logged
    assert "client_issued_at" in fields_logged

    # --- Проверка 6: заказ не архивирован/не удалён ---
    final_order = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    assert final_order["is_archived"] == 0

    print(f"GNPSK Y50={y50_row['gns_number']} (45 дн.), GNPSK mtDNA={mtdna_row['gns_number']} (45 дн.), "
          f"order_id={order_id}, report_services={len(report_rows)} (без GNPSK)")


def test_y50_mtdna_without_report_30_days_each(conn):
    """Задача 6: Y50 + mtDNA БЕЗ отчёта -> оба норматива по 30 дней."""
    order = repo.NewOrderInput(
        customer_name="Без Отчёта Тестович", test_type_codes=["Y50", "MTDNA"],
        report_added=False, sample_received_at=date(2026, 1, 1),
    )
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    rows = conn.execute("SELECT * FROM tests WHERE test_id IN (?, ?)", test_ids).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["deadline_days"] == 30
        assert r["report_option"] == "Обычный"
    assert len({r["gns_number"] for r in rows}) == 2
    assert len({r["order_id"] for r in rows}) == 1
    report_rows = conn.execute("SELECT * FROM report_services WHERE order_id=?", (order_id,)).fetchall()
    assert len(report_rows) == 0  # услуга отчёта не создана вообще


def test_wgs_15x_30x_60_days_report_forbidden(conn):
    """Задача 7: WGS 15X / 30X -> 60 дней; отчёт запрещён и бизнес-логикой, и (проверено
    отдельно в GUI-слое) интерфейсом — см. NewOrderDialog._on_save / edit_dialog валидацию."""
    for code in ("WGS15", "WGS30"):
        order = repo.NewOrderInput(customer_name=f"WGS {code}", test_type_codes=[code],
                                    sample_received_at=date(2026, 1, 1))
        order_id, test_ids = repo.create_order_with_tests(conn, order)
        row = conn.execute("SELECT * FROM tests WHERE test_id=?", (test_ids[0],)).fetchone()
        assert row["deadline_days"] == 60, f"{code}: ожидалось 60 дней"

        order_with_report = repo.NewOrderInput(customer_name=f"WGS {code} + отчёт",
                                                 test_type_codes=[code], report_added=True,
                                                 sample_received_at=date(2026, 1, 1))
        with pytest.raises(ValueError):
            repo.create_order_with_tests(conn, order_with_report)
