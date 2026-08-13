"""
GENOPOISK CRM — приём заказов из Telegram long-polling'ом (раздел 15/28 ТЗ).

Разделено на две части намеренно:
  - process_update_batch(): чистая функция без Qt и без сети — принимает уже
    полученные updates и текущее состояние БД, возвращает результат. Это то,
    что реально тестируется без мока сети/потоков.
  - TelegramPollerThread: тонкая обёртка на QThread, которая крутит цикл
    get_updates -> process_update_batch -> sleep и сигналит в UI-поток через
    Qt-сигналы (никогда не трогает БД/виджеты напрямую из фонового потока
    после обработки — только эмитит сигнал с результатом).
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import repository as repo
from . import settings as st
from . import telegram_client as tc
from . import telegram_parser as tp

SETTING_LAST_UPDATE_ID = "telegram_last_update_id"


@dataclass
class BatchResult:
    processed: int = 0
    new_orders: int = 0
    updated_orders: int = 0
    needs_review: int = 0
    errors: list = field(default_factory=list)  # (update_id, error_text)
    last_update_id: Optional[int] = None


def process_update_batch(conn: sqlite3.Connection, updates: list[dict], *, user_name: str = "telegram-bot") -> BatchResult:
    """Чистая обработка уже полученных updates. Не делает сетевых вызовов."""
    result = BatchResult()

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            result.last_update_id = update_id if result.last_update_id is None else max(result.last_update_id, update_id)

        text = tc.extract_message_text(update)
        if not text:
            continue  # не текстовое сообщение (стикер/фото без подписи и т.п.) — пропускаем молча

        result.processed += 1
        try:
            order_id, is_new = tp.create_or_update_order_from_message(conn, text, user_name=user_name)
            if is_new:
                result.new_orders += 1
                row = conn.execute("SELECT needs_review FROM orders WHERE order_id=?", (order_id,)).fetchone()
                if row and row["needs_review"]:
                    result.needs_review += 1
            else:
                result.updated_orders += 1
        except Exception as exc:  # noqa: BLE001 — одно плохое сообщение не должно рушить приём остальных
            result.errors.append((update_id, str(exc)))

    return result


def poll_once(conn: sqlite3.Connection, token: str, *, timeout: int = 25, user_name: str = "telegram-bot") -> BatchResult:
    """Один цикл: взять сохранённый offset -> получить updates -> обработать -> сохранить новый offset."""
    last_id = st.get_setting(conn, SETTING_LAST_UPDATE_ID)
    offset = int(last_id) if last_id else None

    updates = tc.get_updates(token, offset=offset, timeout=timeout)
    result = process_update_batch(conn, updates, user_name=user_name)

    if result.last_update_id is not None:
        st.set_setting(conn, SETTING_LAST_UPDATE_ID, str(result.last_update_id + 1))

    return result


class TelegramPollerThread(QThread):
    """Фоновый поток long-polling'а. Открывает СВОЁ отдельное соединение с БД
    (sqlite3-соединения нельзя безопасно шарить между потоками), поэтому
    получает путь к файлу БД, а не готовое соединение."""

    batch_processed = Signal(object)   # BatchResult
    error_occurred = Signal(str)

    def __init__(self, db_path, token: str, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.token = token
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        from . import db as dbmod
        conn = dbmod.connect(self.db_path)
        try:
            while not self._stop_requested:
                try:
                    result = poll_once(conn, self.token)
                    if result.processed:
                        self.batch_processed.emit(result)
                except tc.TelegramAPIError as exc:
                    self.error_occurred.emit(str(exc))
                    time.sleep(10)  # не долбить API при ошибке (напр. неверный токен)
                except Exception as exc:  # noqa: BLE001
                    self.error_occurred.emit(f"Неожиданная ошибка приёма Telegram: {exc}")
                    time.sleep(10)
        finally:
            conn.close()
