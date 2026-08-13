import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import business_logic as bl
from app import db as dbmod
from app import repository as repo


# ---------------------------------------------------------------------
# Дедлайны
# ---------------------------------------------------------------------

def test_y50_no_report_30_days():
    r = bl.calculate_deadline(
        base_deadline_days=30, report_option="Обычный", report_allowed=True,
        report_extra_days=15, sample_received_at=date(2026, 1, 1),
    )
    assert r.deadline_days == 30
    assert r.deadline_date == date(2026, 1, 31)


def test_y50_with_report_45_days():
    r = bl.calculate_deadline(
        base_deadline_days=30, report_option="С отчётом", report_allowed=True,
        report_extra_days=15, sample_received_at=date(2026, 1, 1),
    )
    assert r.deadline_days == 45


def test_strelka_with_report_60_days():
    r = bl.calculate_deadline(
        base_deadline_days=45, report_option="С отчётом", report_allowed=True,
        report_extra_days=15, sample_received_at=date(2026, 1, 1),
    )
    assert r.deadline_days == 60


def test_wgs_report_forbidden():
    with pytest.raises(ValueError):
        bl.validate_report_option("С отчётом", report_allowed=False)


def test_no_sample_received_no_deadline():
    r = bl.calculate_deadline(
        base_deadline_days=30, report_option="Обычный", report_allowed=True,
        report_extra_days=15, sample_received_at=None,
    )
    assert r.deadline_date is None  # тест не считается просроченным


# ---------------------------------------------------------------------
# Цветовая логика
# ---------------------------------------------------------------------

def test_color_green_when_issued_regardless_of_deadline():
    color = bl.calculate_row_color(
        client_issued_at=datetime(2026, 1, 1),
        deadline_date=date(2020, 1, 1),  # давно просрочен, но выдан -> зелёный
        operator_started_at=None,
        today=date(2026, 1, 2),
    )
    assert color == bl.RowColor.GREEN


def test_color_red_after_deadline():
    color = bl.calculate_row_color(
        client_issued_at=None, deadline_date=date(2026, 1, 1),
        operator_started_at=None, today=date(2026, 1, 5),
    )
    assert color == bl.RowColor.RED


def test_color_purple_5_days_before():
    color = bl.calculate_row_color(
        client_issued_at=None, deadline_date=date(2026, 1, 10),
        operator_started_at=None, today=date(2026, 1, 5),
    )
    assert color == bl.RowColor.PURPLE


def test_color_yellow_when_started_not_urgent():
    color = bl.calculate_row_color(
        client_issued_at=None, deadline_date=date(2026, 3, 1),
        operator_started_at=datetime(2026, 1, 5), today=date(2026, 1, 6),
    )
    assert color == bl.RowColor.YELLOW


def test_color_normal_otherwise():
    color = bl.calculate_row_color(
        client_issued_at=None, deadline_date=date(2026, 3, 1),
        operator_started_at=None, today=date(2026, 1, 6),
    )
    assert color == bl.RowColor.NORMAL


# ---------------------------------------------------------------------
# GNPSK номера — уникальность и транзакционность
# ---------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    path = tmp_path / "test.db"
    c = dbmod.connect(path)
    dbmod.init_db(c)
    yield c
    c.close()


def test_gnpsk_numbers_are_sequential_and_unique(conn):
    n1 = bl.generate_gnpsk_number(conn)
    n2 = bl.generate_gnpsk_number(conn)
    assert n1 != n2
    assert n1.startswith("GNPSK")


def test_gnpsk_start_number_setting(conn):
    bl.set_gnpsk_start_number(conn, 109400)
    n = bl.generate_gnpsk_number(conn)
    assert n == "GNPSK109400"


# ---------------------------------------------------------------------
# Заказ -> тесты (раздел 5, 24)
# ---------------------------------------------------------------------

def test_y50_creates_one_test(conn):
    order = repo.NewOrderInput(customer_name="Иванов", test_type_codes=["Y50"],
                                sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    assert len(test_ids) == 1
    row = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_ids[0],)).fetchone()
    assert row["deadline_days"] == 30


def test_y50_plus_mtdna_creates_two_tests_two_gnpsk_one_order(conn):
    order = repo.NewOrderInput(customer_name="Петров", test_type_codes=["Y50", "MTDNA"],
                                sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    assert len(test_ids) == 2
    rows = conn.execute("SELECT * FROM tests WHERE test_id IN (?, ?)", test_ids).fetchall()
    gns_numbers = {r["gns_number"] for r in rows}
    assert len(gns_numbers) == 2  # два разных GNPSK
    assert all(r["order_id"] == order_id for r in rows)  # один заказ


def test_wgs_plus_report_is_forbidden(conn):
    order = repo.NewOrderInput(customer_name="Сидоров", test_type_codes=["WGS15"],
                                report_added=True, sample_received_at=date(2026, 1, 1))
    with pytest.raises(ValueError):
        repo.create_order_with_tests(conn, order)


def test_wgs_60_days_no_report(conn):
    order = repo.NewOrderInput(customer_name="Кузнецов", test_type_codes=["WGS30"],
                                sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    row = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_ids[0],)).fetchone()
    assert row["deadline_days"] == 60


def test_type_change_recalculates_deadline_and_logs_audit(conn):
    order = repo.NewOrderInput(customer_name="Смирнов", test_type_codes=["Y50"],
                                sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    test_id = test_ids[0]

    before = conn.execute("SELECT deadline_days FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert before["deadline_days"] == 30

    repo.update_test_fields(conn, test_id, {"test_type": "STRELKA"}, user_name="operator1",
                             reason="изменение типа теста")

    after = conn.execute("SELECT deadline_days FROM tests WHERE test_id=?", (test_id,)).fetchone()
    assert after["deadline_days"] == 45

    audit_rows = conn.execute(
        "SELECT * FROM audit_log WHERE entity='test' AND entity_id=?", (test_id,)
    ).fetchall()
    fields_changed = {r["field"] for r in audit_rows}
    assert "test_type" in fields_changed
    assert "deadline_date" in fields_changed


def test_mtdna_plus_report_45_days(conn):
    order = repo.NewOrderInput(customer_name="МтДНК Клиент", test_type_codes=["MTDNA"],
                                report_added=True, sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    row = conn.execute("SELECT * FROM tests WHERE test_id=?", (test_ids[0],)).fetchone()
    assert row["deadline_days"] == 45


def test_strelka_plus_report_60_days(conn):
    order = repo.NewOrderInput(customer_name="Стрелка Клиент", test_type_codes=["STRELKA"],
                                report_added=True, sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    row = conn.execute("SELECT * FROM tests WHERE test_id=?", (test_ids[0],)).fetchone()
    assert row["deadline_days"] == 60


def test_extra_payment_amount_and_comment_saved(conn):
    order = repo.NewOrderInput(customer_name="Доплата Клиент", test_type_codes=["Y50"],
                                sample_received_at=date(2026, 1, 1))
    order_id, _ = repo.create_order_with_tests(conn, order)
    repo.apply_order_financial_change(
        conn, order_id, extra_payment=2500.0,
        comment="доплата за срочность", user_name="operator1",
    )
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    assert row["extra_payment"] == 2500.0

    audit_rows = conn.execute(
        "SELECT * FROM audit_log WHERE entity='order' AND entity_id=? AND field='extra_payment'",
        (order_id,),
    ).fetchall()
    assert len(audit_rows) == 1
    assert audit_rows[0]["reason"] == "доплата за срочность"
    assert audit_rows[0]["new_value"] == "2500.0"
    order = repo.NewOrderInput(customer_name="Волков", test_type_codes=["Y50"],
                                sample_received_at=date(2026, 1, 1))
    order_id, _ = repo.create_order_with_tests(conn, order)
    repo.apply_order_financial_change(conn, order_id, refund_amount=1500.0,
                                       new_status="Возврат", comment="клиент отказался",
                                       user_name="operator1")
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    assert row is not None
    assert row["refund_amount"] == 1500.0
    assert row["order_status"] == "Возврат"
    assert row["is_archived"] == 0


def test_search_finds_by_gns_order_customer(conn):
    order = repo.NewOrderInput(order_no="OZ-100", customer_name="Тестов Тест Тестович",
                                test_type_codes=["Y50"], sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    gns = conn.execute("SELECT gns_number FROM tests WHERE test_id=?", (test_ids[0],)).fetchone()[0]

    assert len(repo.list_tests_with_order(conn, search=gns)) == 1
    assert len(repo.list_tests_with_order(conn, search="OZ-100")) == 1
    assert len(repo.list_tests_with_order(conn, search="Тестов")) == 1
    assert len(repo.list_tests_with_order(conn, search="нет такого")) == 0


def test_two_tests_share_client_data_independent_dates(conn):
    order = repo.NewOrderInput(customer_name="Общий Клиент", test_type_codes=["Y50", "MTDNA"],
                                sample_received_at=date(2026, 1, 1))
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    repo.update_test_fields(conn, test_ids[0], {"client_issued_at": "2026-02-01T10:00:00"})

    t0 = conn.execute("SELECT * FROM tests WHERE test_id=?", (test_ids[0],)).fetchone()
    t1 = conn.execute("SELECT * FROM tests WHERE test_id=?", (test_ids[1],)).fetchone()
    assert t0["order_id"] == t1["order_id"]
    assert t0["client_issued_at"] is not None
    assert t1["client_issued_at"] is None  # независимый статус
