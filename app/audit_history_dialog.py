"""
GENOPOISK CRM — история изменений заказа (задача 5 финального этапа).

Показывает записи audit_log и по заказу, и по всем его тестам вместе,
в хронологическом порядке — как единую ленту событий, потому что оператору
интересна история заказа в целом, а не отдельно по каждой таблице.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from . import repository as repo


def _fmt_ts(iso_ts: str) -> str:
    dt = repo.parse_iso_dt(iso_ts)
    return dt.strftime("%d.%m.%Y %H:%M") if dt else iso_ts


FIELD_LABELS = {
    "test_type": "Тип теста", "report_option": "Комплектация",
    "sample_received_at": "Дата образца", "lab_sent_at": "Передан в лабораторию",
    "lab_profile_received_at": "Профиль лаборатории", "operator_started_at": "Взято в работу",
    "operator_name": "Оператор", "client_issued_at": "Выдан клиенту",
    "result_y": "Результат Y", "result_mt": "Результат мтДНК", "comments": "Комментарий",
    "extra_payment": "Доплата", "refund_amount": "Возврат", "order_status": "Статус заказа",
    "is_archived": "Архивация", "deadline_date": "Дедлайн", "source_raw": "Сообщение Telegram",
}


class OrderAuditHistoryDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, order_id: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.order_id = order_id

        order = conn.execute("SELECT order_no, customer_name FROM orders WHERE order_id=?", (order_id,)).fetchone()
        title_bits = [b for b in [order["order_no"] if order else None, order["customer_name"] if order else None] if b]
        self.setWindowTitle(f"История изменений — {' / '.join(title_bits) or f'заказ {order_id}'}")
        self.resize(900, 500)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Все изменения заказа и всех его тестов, в хронологическом порядке. "
            "Записи не редактируются и не удаляются."
        ))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Дата/время", "Тест (GNS)", "Поле", "Было", "Стало", "Причина / кто"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        close_row = QHBoxLayout()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_row.addStretch(1)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._reload()

    def _reload(self) -> None:
        rows = repo.list_audit_for_order(self.conn, self.order_id)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            field_label = FIELD_LABELS.get(r["field"], r["field"] or "—")
            who_reason = " / ".join(x for x in [r["reason"], r["user_name"]] if x)
            values = [
                _fmt_ts(r["timestamp"]),
                r["test_gns_number"] or "(заказ целиком)",
                field_label,
                r["old_value"] or "",
                r["new_value"] or "",
                who_reason,
            ]
            for col, val in enumerate(values):
                self.table.setItem(i, col, QTableWidgetItem(str(val)))

        if not rows:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("История пуста"))
