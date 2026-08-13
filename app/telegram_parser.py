"""
GENOPOISK CRM — парсер сообщений Telegram-бота об оплаченных заказах (раздел 15 ТЗ).

СТАТУС: задел на этап 6 (раздел 26: "Telegram подключается после готовности
локального ядра"). Здесь реализована логика РАЗБОРА уже готового текста
сообщения и логика подключения к существующему заказу/созданию нового —
то есть всё, что не требует сетевого клиента Telegram. Сам сетевой клиент
подключается отдельно, когда пользователь предоставит Bot Token (раздел 28,
см. TODO внизу файла). Реальный Bot Token НЕ подключается до отдельного
предоставления пользователем.

Формат сообщения (предоставлен пользователем, пример):

    Заказ №1841848612

    1. FULL LINE - Y50+мтДНК в единой истории семьи: 14990 (1 x 14990) 8
    Заказ оплачен.
    Ozon
    Адрес доставки: RU: Пункт выдачи заказа: ПВЗ Ozon173015, Великий Новгород
    ФИО: Тестовый Клиент Примерович
    Сумма платежа: 14990 RUB
    Код платежа: Банк Точка: ...

    Информация о покупателе:
    Email: ...
    phone: +70000000000

    Дополнительная информация:
    Код заявки: 5241658:8584467492
    Код блока: rec1605680141
    Форма: Cart

Правила:
  - бот получает уже ОПЛАЧЕННЫЕ заказы — сценарий ожидания оплаты не нужен;
  - если товар не распознан однозначно — заказ создаётся со статусом
    "Требует проверки", система не угадывает;
  - если сообщение относится к существующему order_no — обновляем заказ,
    а не создаём дубль;
  - исходное сообщение сохраняется как source_raw для аудита (без токена);
  - изменение товара/комплектации по новому сообщению — через audit log
    (обеспечивается repository.update_test_fields / create_order_with_tests,
    которые сами пишут в audit_log).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from . import repository as repo


@dataclass
class OrderLineItem:
    raw_line: str
    product_name: str            # напр. "FULL LINE - Y50+мтДНК в единой истории семьи"
    line_amount: Optional[float] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None


@dataclass
class ParsedOrderMessage:
    order_no: Optional[str] = None
    line_items: list[OrderLineItem] = field(default_factory=list)
    is_paid: bool = False
    amount: Optional[float] = None          # "Сумма платежа"
    delivery_method: Optional[str] = None   # напр. "Ozon"
    delivery_address: Optional[str] = None
    customer_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    payment_code: Optional[str] = None
    request_code: Optional[str] = None
    block_code: Optional[str] = None
    form_data: Optional[str] = None
    raw_text: str = ""


# Известные способы доставки — строка сообщения, точно совпадающая с одним из них
# (после строки товара / статуса оплаты), распознаётся как способ доставки.
KNOWN_DELIVERY_METHODS = ["Ozon", "Почта России", "Курьер", "Яндекс", "СДЭК"]

_LINE_ITEM_RE = re.compile(
    r"^\s*\d+\.\s*(?P<name>.+?):\s*(?P<amount>[\d\s]+(?:[.,]\d+)?)\s*"
    r"\(\s*(?P<qty>\d+)\s*x\s*(?P<unit>[\d\s]+(?:[.,]\d+)?)\s*\)",
    re.MULTILINE,
)

_FIELD_PATTERNS = {
    "order_no": r"Заказ\s*№\s*([A-ZА-Я0-9\-]+)",
    "amount": r"Сумма\s+платежа[:\s]+([\d\s]+(?:[.,]\d+)?)\s*(?:RUB|руб|₽)?",
    "delivery_address": r"Адрес\s+доставки[:\s]+([^\n]+)",
    "customer_name": r"ФИО[:\s]+([^\n]+)",
    "email": r"Email[:\s]+([^\s\n]+)",
    "phone": r"phone[:\s]+(\+?\d[\d\-\s()]{8,}\d)",
    "payment_code": r"Код\s+платежа[:\s]+([^\n]+)",
    "request_code": r"Код\s+заявки[:\s]+([^\n]+)",
    "block_code": r"Код\s+блока[:\s]+([^\n]+)",
    "form_data": r"Форма[:\s]+([^\n]+)",
}


def _parse_number(value: str) -> Optional[float]:
    value = value.strip().replace(" ", "").replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_message_text(text: str) -> ParsedOrderMessage:
    """Извлекает поля из текста сообщения о заказе (см. формат в docstring модуля)."""
    result = ParsedOrderMessage(raw_text=text)

    for field_name, pattern in _FIELD_PATTERNS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        value = m.group(1).strip()
        if field_name == "amount":
            result.amount = _parse_number(value)
        else:
            setattr(result, field_name, value)

    result.is_paid = bool(re.search(r"заказ\s+оплачен", text, re.IGNORECASE))

    for m in _LINE_ITEM_RE.finditer(text):
        result.line_items.append(
            OrderLineItem(
                raw_line=m.group(0).strip(),
                product_name=m.group("name").strip(" -"),
                line_amount=_parse_number(m.group("amount")),
                quantity=int(m.group("qty")),
                unit_price=_parse_number(m.group("unit")),
            )
        )

    for line in text.splitlines():
        stripped = line.strip()
        if stripped in KNOWN_DELIVERY_METHODS:
            result.delivery_method = stripped
            break

    return result


def resolve_products_from_text(conn: sqlite3.Connection, text: str) -> tuple[list[str], bool, list[str]]:
    """
    Ищет в тексте сообщения известные коммерческие названия (из product_mappings)
    и возвращает (test_type_codes, includes_report, unresolved_fragments).

    Сопоставление идёт по каждой строке товара отдельно (а не по всему тексту
    целиком), чтобы заказ с несколькими позициями разбирался корректно, и чтобы
    частичное совпадение одного товара не маскировало нераспознанный второй.

    Если хотя бы один товар не распознан — unresolved_fragments будет непустым,
    и вызывающий код обязан пометить ВЕСЬ заказ needs_review=True, а НЕ пытаться
    угадать состав частично (раздел 15: "система не должна угадывать").
    """
    rows = conn.execute(
        "SELECT commercial_name, test_type_codes, includes_report FROM product_mappings"
    ).fetchall()
    mappings = [(r["commercial_name"], json.loads(r["test_type_codes"]), bool(r["includes_report"])) for r in rows]

    parsed = parse_message_text(text)
    line_names = [li.product_name for li in parsed.line_items]
    if not line_names:
        # Не нашли ни одной строки товара распознаваемого формата — весь текст
        # уходит на ручную проверку целиком.
        return [], False, [text]

    all_codes: list[str] = []
    includes_report = False
    unresolved: list[str] = []

    for name in line_names:
        match = next((m for m in mappings if m[0].strip().lower() == name.strip().lower()), None)
        if match is None:
            # запасной вариант: частичное совпадение (напр. лишние пробелы/регистр в реальных данных)
            match = next((m for m in mappings if m[0].strip().lower() in name.strip().lower()
                          or name.strip().lower() in m[0].strip().lower()), None)
        if match is None:
            unresolved.append(name)
            continue
        _commercial_name, codes, report_flag = match
        all_codes.extend(codes)
        includes_report = includes_report or report_flag

    return all_codes, includes_report, unresolved


def find_order_by_order_no(conn: sqlite3.Connection, order_no: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM orders WHERE order_no = ? AND is_archived = 0", (order_no,)
    ).fetchone()


def create_or_update_order_from_message(
    conn: sqlite3.Connection,
    text: str,
    *,
    user_name: str = "telegram-bot",
) -> tuple[int, bool]:
    """
    Главная точка входа парсера. Возвращает (order_id, is_new_order).

    - Если order_no уже существует — обновляет существующий заказ (не создаёт дубль),
      изменение состава товаров проходит через audit log.
    - Если товар не распознан однозначно — создаёт заказ со статусом
      needs_review=True и НЕ создаёт тестов, чтобы оператор разобрался вручную.
    - Бот присылает уже оплаченные заказы (раздел 0); если сообщение почему-то
      неоплачено, заказ всё равно создаётся, но также уходит needs_review=True,
      чтобы оператор не пропустил аномалию.
    """
    parsed = parse_message_text(text)
    codes, includes_report, unresolved = resolve_products_from_text(conn, text)

    existing = find_order_by_order_no(conn, parsed.order_no) if parsed.order_no else None

    if existing:
        repo.write_audit(
            conn, user_name=user_name, entity="order", entity_id=existing["order_id"],
            field="source_raw", old_value=existing["source_raw"], new_value=text,
            reason="повторное сообщение Telegram для существующего заказа",
        )
        conn.execute(
            "UPDATE orders SET source_raw = ?, updated_at = ? WHERE order_id = ?",
            (text, repo.now_iso(), existing["order_id"]),
        )
        return existing["order_id"], False

    needs_review = bool(unresolved) or not codes or not parsed.is_paid

    order_data = repo.NewOrderInput(
        order_no=parsed.order_no or "",
        customer_name=parsed.customer_name or "",
        contacts=", ".join(filter(None, [parsed.phone, parsed.email])),
        delivery_method=parsed.delivery_method or "",
        delivery_address=parsed.delivery_address or "",
        order_amount=parsed.amount,
        source="Telegram",
        source_raw=text,
        needs_review=needs_review,
        test_type_codes=[] if needs_review else codes,
        report_added=includes_report,
        user_name=user_name,
    )
    order_id, _test_ids = repo.create_order_with_tests(conn, order_data)
    return order_id, True


# ---------------------------------------------------------------------
# TODO (этап 6, после получения Bot Token от пользователя — раздел 28):
#   1. Добавить сетевой клиент (напр. через `python-telegram-bot` или прямой
#      polling/webhook по Bot API) — токен читать ТОЛЬКО через
#      app.secrets_store.get_telegram_bot_token(), никогда не хардкодить.
#   2. На каждое входящее сообщение вызывать create_or_update_order_from_message.
#   3. Заполнить product_mappings реальным списком коммерческих названий с сайта
#      (раздел 28) — сейчас есть только пример "FULL LINE - Y50+мтДНК ..." из
#      сообщения, предоставленного пользователем для тестирования парсера.
# ---------------------------------------------------------------------
