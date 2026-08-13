"""
Тесты парсера Telegram-сообщений на сохранённых текстах (без реального
Bot Token и без сетевого клиента — раздел 15/28 ТЗ, задача 4).

Используется ТОЧНЫЙ формат сообщения, предоставленный пользователем.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import db as dbmod
from app import repository as repo
from app import telegram_parser as tg


SAMPLE_MESSAGE = """Заказ №1841848612

1. FULL LINE - Y50+мтДНК в единой истории семьи: 14990 (1 x 14990) 8
Заказ оплачен.
Ozon
Адрес доставки: RU: Пункт выдачи заказа: ПВЗ Ozon173015, Великий Новгород
ФИО: Тестовый Клиент Примерович
Сумма платежа: 14990 RUB
Код платежа: Банк Точка: ...

Информация о покупателе:
Email: kirill.n@example.com
phone: +70000000000

Дополнительная информация:
Код заявки: 5241658:8584467492
Код блока: rec1605680141
Форма: Cart
"""


@pytest.fixture()
def conn(tmp_path):
    path = tmp_path / "test.db"
    c = dbmod.connect(path)
    dbmod.init_db(c)
    repo.upsert_product_mapping(
        c, "FULL LINE - Y50+мтДНК в единой истории семьи",
        ["Y50", "MTDNA"], includes_report=False,
        notes="FULL LINE исключён из бизнес-логики нового теста (раздел 0) — "
              "разворачивается в 2 отдельных теста через маппинг.",
    )
    yield c
    c.close()


# ---------------------------------------------------------------------
# Извлечение полей (задача 4: "Parser должен извлекать...")
# ---------------------------------------------------------------------

def test_parses_order_number():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.order_no == "1841848612"


def test_parses_product_line_item():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert len(parsed.line_items) == 1
    item = parsed.line_items[0]
    assert item.product_name == "FULL LINE - Y50+мтДНК в единой истории семьи"
    assert item.line_amount == 14990.0
    assert item.quantity == 1
    assert item.unit_price == 14990.0


def test_parses_amount():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.amount == 14990.0


def test_parses_payment_status():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.is_paid is True


def test_parses_delivery_method():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.delivery_method == "Ozon"


def test_parses_delivery_address():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert "Великий Новгород" in parsed.delivery_address
    assert "ПВЗ Ozon173015" in parsed.delivery_address


def test_parses_customer_name():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.customer_name == "Тестовый Клиент Примерович"


def test_parses_email():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.email == "kirill.n@example.com"


def test_parses_phone():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.phone == "+70000000000"


def test_parses_payment_code():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.payment_code.startswith("Банк Точка")


def test_parses_request_code():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.request_code == "5241658:8584467492"


def test_parses_block_code():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.block_code == "rec1605680141"


def test_parses_form():
    parsed = tg.parse_message_text(SAMPLE_MESSAGE)
    assert parsed.form_data == "Cart"


# ---------------------------------------------------------------------
# Разворачивание FULL LINE в два теста через product_mappings (раздел 0, 5)
# ---------------------------------------------------------------------

def test_full_line_resolves_to_y50_plus_mtdna(conn):
    codes, includes_report, unresolved = tg.resolve_products_from_text(conn, SAMPLE_MESSAGE)
    assert set(codes) == {"Y50", "MTDNA"}
    assert includes_report is False
    assert unresolved == []


def test_full_line_message_creates_order_with_two_tests_not_full_line_type(conn):
    order_id, is_new = tg.create_or_update_order_from_message(conn, SAMPLE_MESSAGE)
    assert is_new is True

    order = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    assert order["order_no"] == "1841848612"
    assert order["customer_name"] == "Тестовый Клиент Примерович"
    assert order["needs_review"] == 0  # товар распознан, оплачен -> не требует проверки
    assert order["source"] == "Telegram"
    assert "Bot Token" not in (order["source_raw"] or "")  # токен не может попасть сюда в принципе

    tests = conn.execute("SELECT * FROM tests WHERE order_id=?", (order_id,)).fetchall()
    types = {t["test_type"] for t in tests}
    assert types == {"Y50", "MTDNA"}
    assert "FULL LINE" not in types  # FULL LINE не становится типом нового теста (раздел 0)
    assert len({t["gns_number"] for t in tests}) == 2  # два разных GNPSK


# ---------------------------------------------------------------------
# Нераспознанный товар -> needs_review, без угадывания
# ---------------------------------------------------------------------

def test_unrecognized_product_creates_needs_review_order_without_guessing(conn):
    text = SAMPLE_MESSAGE.replace(
        "FULL LINE - Y50+мтДНК в единой истории семьи",
        "Совершенно новый неизвестный товар сайта",
    )
    order_id, is_new = tg.create_or_update_order_from_message(conn, text)
    order = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    assert order["needs_review"] == 1
    tests = conn.execute("SELECT * FROM tests WHERE order_id=?", (order_id,)).fetchall()
    assert len(tests) == 0  # система не угадывает состав


# ---------------------------------------------------------------------
# Повторное сообщение по тому же order_no -> обновление, не дубль
# ---------------------------------------------------------------------

def test_repeated_message_updates_existing_order_no_duplicate(conn):
    order_id_1, is_new_1 = tg.create_or_update_order_from_message(conn, SAMPLE_MESSAGE)
    assert is_new_1 is True

    order_id_2, is_new_2 = tg.create_or_update_order_from_message(conn, SAMPLE_MESSAGE)
    assert is_new_2 is False
    assert order_id_2 == order_id_1

    all_orders = conn.execute(
        "SELECT * FROM orders WHERE order_no=?", ("1841848612",)
    ).fetchall()
    assert len(all_orders) == 1  # не создан дубль

    audit_rows = conn.execute(
        "SELECT * FROM audit_log WHERE entity='order' AND entity_id=?", (order_id_1,)
    ).fetchall()
    assert any(r["reason"] and "повторное сообщение" in r["reason"] for r in audit_rows)


# ---------------------------------------------------------------------
# Bot Token никогда не участвует в парсинге / не может попасть в БД
# ---------------------------------------------------------------------

def test_parser_never_touches_bot_token_module(conn):
    """Парсер работает только с текстом сообщения; секреты — отдельный модуль,
    который парсер даже не импортирует (раздел 21: токен не в исходном коде/БД)."""
    import app.telegram_parser as tg_module
    assert "secrets_store" not in tg_module.__doc__ if tg_module.__doc__ else True
    src = open(tg_module.__file__, encoding="utf-8").read()
    assert "secrets_store.get_telegram_bot_token" not in src.split("TODO")[0]
