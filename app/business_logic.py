"""
GENOPOISK CRM — бизнес-логика.

Реализует правила из ТЗ разделов 6-8:
  - расчёт срока (дедлайна) теста;
  - цветовая логика строки списка тестов;
  - транзакционная генерация номеров GNPSK.

Эти функции сознательно не зависят от GUI/БД напрямую (кроме
generate_gnpsk_number, которой нужна транзакция) — чтобы их можно было
покрыть модульными тестами независимо от интерфейса.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------
# Дедлайны (раздел 7 ТЗ)
# ---------------------------------------------------------------------

@dataclass
class DeadlineResult:
    deadline_days: Optional[int]     # итоговый норматив в днях (с учётом отчёта)
    deadline_date: Optional[date]    # дата дедлайна, если есть точка отсчёта


def calculate_deadline(
    *,
    base_deadline_days: int,
    report_option: str,
    report_allowed: bool,
    report_extra_days: int,
    sample_received_at: Optional[date],
) -> DeadlineResult:
    """
    Правила:
      - Точка начала — дата прихода образца (sample_received_at).
      - Если образец ещё не получен — дедлайн НЕ рассчитывается (тест не считается просроченным).
      - report_option == 'С отчётом' добавляет report_extra_days (по умолчанию 15) к нормативу.
      - Для типов, где report_allowed=False (WGS), "С отчётом" запрещено — вызывающий код
        обязан это проверить заранее (см. validate_report_option); здесь мы просто не добавляем дни,
        если report_allowed=False, как защитная мера.
    """
    days = base_deadline_days
    if report_option == "С отчётом" and report_allowed:
        days += report_extra_days

    if sample_received_at is None:
        return DeadlineResult(deadline_days=days, deadline_date=None)

    deadline_date = sample_received_at + timedelta(days=days)
    return DeadlineResult(deadline_days=days, deadline_date=deadline_date)


def validate_report_option(report_option: str, report_allowed: bool) -> None:
    if report_option == "С отчётом" and not report_allowed:
        raise ValueError(
            "Для данного типа теста (например, WGS) добавление отчёта запрещено."
        )


# ---------------------------------------------------------------------
# Цветовая логика (раздел 8 ТЗ)
# ---------------------------------------------------------------------

class RowColor(str, Enum):
    GREEN = "green"       # выдан клиенту — высший приоритет
    RED = "red"           # дедлайн прошёл, тест не выдан
    PURPLE = "purple"     # <= N дней до дедлайна, тест не выдан
    YELLOW = "yellow"     # взято в работу, но не выдан и не под red/purple
    NORMAL = "normal"     # остальное


def calculate_row_color(
    *,
    client_issued_at: Optional[datetime],
    deadline_date: Optional[date],
    operator_started_at: Optional[datetime],
    today: Optional[date] = None,
    soon_threshold_days: int = 5,
) -> RowColor:
    """Приоритет: green(1) > red(2) > purple(3) > yellow(4) > normal(5)."""
    if client_issued_at is not None:
        return RowColor.GREEN

    today = today or date.today()

    if deadline_date is not None:
        if today > deadline_date:
            return RowColor.RED
        days_left = (deadline_date - today).days
        if days_left <= soon_threshold_days:
            return RowColor.PURPLE

    if operator_started_at is not None:
        return RowColor.YELLOW

    return RowColor.NORMAL


# ---------------------------------------------------------------------
# Генерация номеров GNPSK (раздел 4 ТЗ) — транзакционная
# ---------------------------------------------------------------------

def _reserve_next_gnpsk_locked(conn: sqlite3.Connection) -> str:
    """
    Резервирует следующий номер GNPSK. ПРЕДПОЛАГАЕТ, что вызывающий код уже
    открыл транзакцию (BEGIN IMMEDIATE/EXCLUSIVE) на этом соединении — сама
    функция транзакцией не управляет, чтобы её можно было безопасно вызывать
    как из отдельной операции, так и внутри более крупной (создание заказа
    с несколькими тестами должно быть атомарным целиком).
    """
    row = conn.execute(
        "SELECT next_number, prefix FROM gnpsk_counter WHERE id = 1"
    ).fetchone()
    next_number = row["next_number"]
    prefix = row["prefix"]
    conn.execute(
        "UPDATE gnpsk_counter SET next_number = ? WHERE id = 1",
        (next_number + 1,),
    )
    return f"{prefix}{next_number:06d}"


def generate_gnpsk_number(conn: sqlite3.Connection) -> str:
    """
    Атомарно резервирует следующий номер GNPSK как самостоятельную операцию.

    Использует IMMEDIATE-транзакцию SQLite, чтобы два параллельных вызова
    не могли получить один и тот же номер (раздел 4: "Генерация номера
    должна быть транзакционной"). Не вызывать эту функцию, если соединение
    уже находится внутри другой открытой транзакции — SQLite не поддерживает
    вложенные BEGIN; в этом случае используйте _reserve_next_gnpsk_locked
    внутри уже открытой транзакции.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _reserve_next_gnpsk_locked(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def set_gnpsk_start_number(conn: sqlite3.Connection, start_number: int) -> None:
    """Задаёт фактический стартовый номер GNPSK при запуске (раздел 4, 20, 28)."""
    conn.execute("UPDATE gnpsk_counter SET next_number = ? WHERE id = 1", (start_number,))


# ---------------------------------------------------------------------
# Разбор комплекта заказа на отдельные тесты (раздел 5 ТЗ)
# ---------------------------------------------------------------------

def split_order_into_test_types(test_type_codes: list[str]) -> list[str]:
    """
    Заказ и тест — разные сущности; один заказ может содержать несколько тестов.
    Каждый код типа теста в комплекте становится отдельной тестовой записью
    (и, соответственно, получит свой собственный GNPSK).

    FULL LINE не должен становиться типом нового теста — ожидается, что
    вызывающий код (парсер Telegram / импорт / ручной ввод) уже развернул
    его через product_mappings в список кодов вида ["Y50", "MTDNA"].
    """
    return list(test_type_codes)


# ---------------------------------------------------------------------
# Журнал операционных событий (test_events) — v1.0 UX, раздел "Внутренняя работа"
# ---------------------------------------------------------------------

# Порядок этапов — определяет, какое событие "самое дальнее" (текущий этап).
EVENT_ORDER = [
    "order_created", "dispatched", "received", "handed_to_lab",
    "profile_received", "in_progress", "issued",
]

EVENT_LABELS_INTERNAL = {
    "order_created": "Заказ создан",
    "dispatched": "Отправлен",
    "received": "Образец получен",
    "handed_to_lab": "Передано в лабораторию",
    "profile_received": "Профиль получен",
    "in_progress": "Взято в работу",
    "issued": "Выдано клиенту",
}

# Клиентская формулировка — без лабораторий, без имён операторов (раздел ТЗ:
# "клиентская вкладка не показывает внутренние комментарии, лаборатории и
# служебные действия").
EVENT_LABELS_CLIENT = {
    "order_created": "Заказ оформлен",
    "dispatched": "Образец в пути",
    "received": "Образец получен",
    "handed_to_lab": "В обработке",
    "profile_received": "В обработке",
    "in_progress": "В обработке",
    "issued": "Выдан клиенту",
}


def _event_types_present(events) -> set:
    return {e["event_type"] for e in events}


def derive_current_stage(events) -> Optional[str]:
    """Возвращает event_type самого дальнего зафиксированного события, или
    None, если событий ещё нет вовсе."""
    present = _event_types_present(events)
    for et in reversed(EVENT_ORDER):
        if et in present:
            return et
    return None


def is_awaiting_receipt(events) -> bool:
    """'Ожидаем получение' — НЕ событие, а состояние между 'dispatched' и
    'received'. Снимается только ручной фиксацией 'received' оператором
    (раздел ТЗ: "не определять факт доставки автоматически")."""
    present = _event_types_present(events)
    return "dispatched" in present and "received" not in present


def client_status_label(events) -> str:
    """Единственная точка, где определяется, что видит клиент по этапу."""
    if is_awaiting_receipt(events):
        return "Ожидаем получение"
    stage = derive_current_stage(events)
    if stage is None or stage == "order_created":
        return "Ожидаем получение"
    return EVENT_LABELS_CLIENT.get(stage, "—")


def internal_status_label(events) -> str:
    if is_awaiting_receipt(events):
        return "Ожидаем получение"
    stage = derive_current_stage(events)
    if stage is None:
        return "—"
    return EVENT_LABELS_INTERNAL.get(stage, "—")


def next_action_event_type(events) -> Optional[str]:
    """Какое событие оператору логично зафиксировать следующим (кнопка
    основного быстрого действия). None, если маршрут уже полностью пройден."""
    present = _event_types_present(events)
    for et in EVENT_ORDER:
        if et not in present:
            return et
    return None


# ---------------------------------------------------------------------
# Цвета типов тестов — фиксированная система, НЕ связанная со срочностью
# (v1.0 UX, перенесено из HTML-макета two_tabs_v2).
# ---------------------------------------------------------------------

TEST_TYPE_COLORS = {
    "Y50": "#c7d7ff",
    "Y37": "#ddc2fb",
    "MTDNA": "#7fefde",
    "MITOGENOME": "#9ceec1",
    "STRELKA": "#ffcf9e",
    "WGS15": "#a3edb8",
    "WGS30": "#62d98c",
}
