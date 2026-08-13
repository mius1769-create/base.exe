"""
GENOPOISK CRM — вкладка «Клиентская» (v1.0 UX).

Отвечает на любой вопрос клиента о заказе: клиентский статус, доставка,
подтверждённые этапы, ориентировочный срок. НЕ показывает лабораторию,
оператора и внутренние комментарии (раздел ТЗ).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLineEdit, QHeaderView, QAbstractItemView, QFrame, QSplitter, QLabel,
)

from . import business_logic as bl
from . import repository as repo

COLUMNS = [
    ("gns_number", "Номер"),
    ("customer_name", "ФИО клиента"),
    ("test_type", "Тип теста"),
    ("client_status", "Статус клиенту"),
]

# Упрощённый клиентский маршрут — 4 стабильные вехи (детали лаборатории/
# внутренние этапы сворачиваются в "В обработке", см. bl.EVENT_LABELS_CLIENT).
CLIENT_TIMELINE_STEPS = [
    ("order_created", "Заказ оформлен"),
    ("received", "Образец получен"),
    ("in_progress", "В обработке"),
    ("issued", "Выдан клиенту"),
]


def fmt_date(value: Optional[str]) -> str:
    if not value:
        return ""
    d = repo.parse_iso_date(value)
    return d.strftime("%d.%m.%Y") if d else value


class ClientTabWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск: номер теста, ФИО, телефон…")
        self.search_edit.textChanged.connect(self.refresh)
        search_row.addWidget(self.search_edit)
        root.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        self.card = ClientCardWidget(self)
        splitter.addWidget(self.card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, stretch=1)

    def refresh(self) -> None:
        search = self.search_edit.text().strip() or None
        rows = repo.list_tests_with_order(self.conn, search=search, quick_filter="all", include_archived=False)
        self._rows_cache = rows

        test_ids = [r["test_id"] for r in rows]
        events_by_test = repo.list_events_for_test_ids(self.conn, test_ids)

        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            events = events_by_test.get(row["test_id"], [])
            client_status = bl.client_status_label(events)

            for col_i, (field_name, _label) in enumerate(COLUMNS):
                text = client_status if field_name == "client_status" else str(row[field_name] or "")
                item = QTableWidgetItem(text)
                if field_name == "test_type":
                    type_hex = bl.TEST_TYPE_COLORS.get(row["test_type"])
                    if type_hex:
                        item.setBackground(QColor(type_hex))
                        item.setForeground(QColor("#14151a"))
                if field_name == "gns_number":
                    item.setData(Qt.UserRole, row["test_id"])
                self.table.setItem(i, col_i, item)

        self.card.clear()

    def _on_row_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.card.clear()
            return
        row_idx = items[0].row()
        test_id = self.table.item(row_idx, 0).data(Qt.UserRole)
        self.card.show_test(test_id)


class ClientCardWidget(QFrame):
    def __init__(self, tab: ClientTabWidget):
        super().__init__()
        self.tab = tab
        self.conn = tab.conn
        self.setFrameShape(QFrame.StyledPanel)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.header_label = QLabel("Выберите тест в списке слева")
        self.header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.header_label)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.info_block = QLabel("")
        self.info_block.setWordWrap(True)
        layout.addWidget(self.info_block)

        self.timeline_block = QLabel("")
        self.timeline_block.setWordWrap(True)
        layout.addWidget(self.timeline_block)

        layout.addStretch(1)

    def clear(self) -> None:
        self.header_label.setText("Выберите тест в списке слева")
        self.status_label.setText("")
        self.info_block.setText("")
        self.timeline_block.setText("")

    def show_test(self, test_id: int) -> None:
        conn = self.conn
        row = conn.execute(
            """SELECT t.*, o.order_no, o.customer_name, o.contacts, o.created_at AS order_created_at
               FROM tests t JOIN orders o ON o.order_id = t.order_id
               WHERE t.test_id = ?""",
            (test_id,),
        ).fetchone()
        if row is None:
            self.clear()
            return

        events = repo.list_events_for_test(conn, test_id)
        client_status = bl.client_status_label(events)

        self.header_label.setText(f"{row['gns_number']} · {row['test_type']}")
        self.status_label.setText(client_status)

        deadline_text = "уточняется"
        dl = repo.parse_iso_date(row["deadline_date"])
        if dl:
            deadline_text = dl.strftime("%d.%m.%Y")

        self.info_block.setText(
            f"<b>Клиент:</b> {row['customer_name']}<br>"
            f"Контакты: {row['contacts'] or '—'}<br>"
            f"№ заказа: {row['order_no'] or '—'}<br>"
            f"<b>Ориентировочный срок готовности:</b> {deadline_text}"
        )

        present = {e["event_type"] for e in events}
        stage = bl.derive_current_stage(events)
        rank = {et: i for i, et in enumerate(bl.EVENT_ORDER)}
        current_rank = rank.get(stage, -1) if stage else -1
        awaiting = bl.is_awaiting_receipt(events)

        lines = ["<b>Статус выполнения:</b>"]
        for et, label in CLIENT_TIMELINE_STEPS:
            target_rank = rank[et]
            if et == "received" and awaiting:
                mark = "○"
            elif current_rank >= target_rank:
                mark = "✓"
            else:
                mark = "○"
            lines.append(f"{mark} {label}")
        self.timeline_block.setText("<br>".join(lines))
