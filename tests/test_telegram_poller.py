"""
Тесты приёма заказов из Telegram (задача 2 финального этапа) — БЕЗ реального
Bot Token и БЕЗ сетевых вызовов. process_update_batch() принимает уже готовые
updates (как их вернул бы Telegram) и не делает никаких HTTP-запросов —
именно поэтому тестируется напрямую, без mock сети.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import db as dbmod
from app import repository as repo
from app import telegram_client as tc
from app import telegram_poller as poller
from app import settings as st


SAMPLE_TEXT = """Заказ №1841848612

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


def make_update(update_id, text=None, non_text=False):
    if non_text:
        return {"update_id": update_id, "message": {"sticker": {"file_id": "abc"}}}
    return {"update_id": update_id, "message": {"text": text, "chat": {"id": 1}}}


@pytest.fixture()
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "test.db")
    dbmod.init_db(c)
    repo.upsert_product_mapping(
        c, "FULL LINE - Y50+мтДНК в единой истории семьи",
        ["Y50", "MTDNA"], includes_report=False,
    )
    yield c
    c.close()


# ---------------------------------------------------------------------
# extract_message_text — не зависит от сети, чистая функция
# ---------------------------------------------------------------------

def test_extract_text_from_message_update():
    upd = make_update(1, text="hello")
    assert tc.extract_message_text(upd) == "hello"


def test_extract_text_returns_none_for_non_text_update():
    upd = make_update(1, non_text=True)
    assert tc.extract_message_text(upd) is None


def test_extract_text_from_channel_post():
    upd = {"update_id": 1, "channel_post": {"text": "canal text"}}
    assert tc.extract_message_text(upd) == "canal text"


# ---------------------------------------------------------------------
# process_update_batch — основная бизнес-логика приёма
# ---------------------------------------------------------------------

def test_batch_creates_order_from_valid_message(conn):
    updates = [make_update(100, text=SAMPLE_TEXT)]
    result = poller.process_update_batch(conn, updates)

    assert result.processed == 1
    assert result.new_orders == 1
    assert result.updated_orders == 0
    assert result.needs_review == 0
    assert result.last_update_id == 100
    assert len(result.errors) == 0

    order = conn.execute("SELECT * FROM orders WHERE order_no='1841848612'").fetchone()
    assert order is not None
    assert order["source"] == "Telegram"


def test_batch_skips_non_text_updates_silently(conn):
    updates = [make_update(1, non_text=True), make_update(2, non_text=True)]
    result = poller.process_update_batch(conn, updates)
    assert result.processed == 0
    assert result.last_update_id == 2  # offset всё равно продвигается, чтобы не залипнуть
    assert len(result.errors) == 0


def test_batch_tracks_needs_review_for_unrecognized_product(conn):
    text = SAMPLE_TEXT.replace(
        "FULL LINE - Y50+мтДНК в единой истории семьи", "Совсем новый неизвестный товар"
    )
    result = poller.process_update_batch(conn, [make_update(5, text=text)])
    assert result.new_orders == 1
    assert result.needs_review == 1


def test_batch_updates_not_creates_duplicate_on_repeat(conn):
    poller.process_update_batch(conn, [make_update(1, text=SAMPLE_TEXT)])
    result2 = poller.process_update_batch(conn, [make_update(2, text=SAMPLE_TEXT)])
    assert result2.new_orders == 0
    assert result2.updated_orders == 1
    all_orders = conn.execute("SELECT * FROM orders WHERE order_no='1841848612'").fetchall()
    assert len(all_orders) == 1


def test_batch_one_bad_message_does_not_block_others(conn, monkeypatch):
    """Одно сообщение, вызвавшее исключение, не должно останавливать приём остальных."""
    from app import telegram_parser as tp

    calls = {"n": 0}
    original = tp.create_or_update_order_from_message

    def flaky(conn_, text, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("симулированный сбой парсинга")
        return original(conn_, text, **kwargs)

    monkeypatch.setattr(poller.tp, "create_or_update_order_from_message", flaky)

    updates = [make_update(1, text=SAMPLE_TEXT), make_update(2, text=SAMPLE_TEXT.replace("1841848612", "999"))]
    result = poller.process_update_batch(conn, updates)

    assert len(result.errors) == 1
    assert result.errors[0][0] == 1
    assert result.new_orders == 1  # второе сообщение всё же обработалось
    assert result.last_update_id == 2


# ---------------------------------------------------------------------
# poll_once — offset сохраняется/читается из settings корректно
# ---------------------------------------------------------------------

def test_poll_once_saves_and_advances_offset(conn, monkeypatch):
    captured_offsets = []

    def fake_get_updates(token, *, offset=None, timeout=25):
        captured_offsets.append(offset)
        if offset is None:
            return [make_update(10, text=SAMPLE_TEXT)]
        return []  # второй вызов — новых сообщений нет

    monkeypatch.setattr(poller.tc, "get_updates", fake_get_updates)

    result1 = poller.poll_once(conn, "fake-token")
    assert result1.new_orders == 1
    assert st.get_setting(conn, poller.SETTING_LAST_UPDATE_ID) == "11"

    poller.poll_once(conn, "fake-token")
    assert captured_offsets == [None, 11]  # второй вызов использует сохранённый offset+1


def test_poll_once_never_sends_token_to_db_or_parser(conn, monkeypatch):
    """Токен используется ТОЛЬКО для сетевого вызова get_updates, никогда не
    попадает в БД (ни в orders, ни в settings, ни куда-либо ещё)."""
    secret = "123456:AAFakeSecretTokenForTest"

    def fake_get_updates(token, *, offset=None, timeout=25):
        assert token == secret
        return [make_update(1, text=SAMPLE_TEXT)]

    monkeypatch.setattr(poller.tc, "get_updates", fake_get_updates)
    poller.poll_once(conn, secret)

    # токен нигде не осел в БД
    for table in ("orders", "tests", "settings", "audit_log"):
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        for row in rows:
            for value in tuple(row):
                assert secret not in str(value)
