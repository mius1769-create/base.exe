"""
GENOPOISK CRM — «Заказы, требуют проверки».

Заказы из Telegram, у которых товар не удалось однозначно сопоставить со
справочником product_mappings (раздел 15 ТЗ: "система не угадывает
состав"), создаются со статусом needs_review=1 и БЕЗ единого теста. Обе
основные вкладки строятся через tests JOIN orders, поэтому такие заказы
физически невидимы нигде — этот экран единственное место, где их можно
найти и дозавести вручную.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QTextEdit, QLabel, QCheckBox, QPushButton, QMessageBox, QSplitter, QWidget,
)

from . import repository as repo
from . import product_catalog as pcat


class NeedsReviewDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Заказы, требуют проверки")
        self.resize(780, 540)
        self._orders: list[sqlite3.Row] = []
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        self.order_list = QListWidget()
        self.order_list.currentItemChanged.connect(self._on_order_selected)
        splitter.addWidget(self.order_list)

        right = QWidget()
        right_lay = QVBoxLayout(right)

        right_lay.addWidget(QLabel("<b>Данные заказа / исходное сообщение</b>"))
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        right_lay.addWidget(self.detail_text, stretch=1)

        right_lay.addWidget(QLabel("<b>Определите тип(ы) теста</b> (выберите один или несколько):"))
        self.type_list = QListWidget()
        self.type_list.setSelectionMode(QListWidget.MultiSelection)
        self._test_types = repo.list_test_types(self.conn)
        for tt in self._test_types:
            item = QListWidgetItem(pcat.get_display_name(tt["code"]))
            item.setData(Qt.UserRole, tt["code"])
            self.type_list.addItem(item)
        right_lay.addWidget(self.type_list)

        self.report_checkbox = QCheckBox("Добавить услугу «Отчёт»")
        right_lay.addWidget(self.report_checkbox)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.assign_btn = QPushButton("Дозавести тесты и снять пометку")
        self.assign_btn.clicked.connect(self._on_assign)
        self.assign_btn.setEnabled(False)
        btn_row.addWidget(self.assign_btn)
        right_lay.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        layout.addWidget(splitter, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _reload(self, *, keep_order_id: int | None = None) -> None:
        self.order_list.clear()
        self._orders = repo.list_orders_needing_review(self.conn)

        select_idx = None
        for i, o in enumerate(self._orders):
            label = f"№{o['order_no'] or o['order_id']} — {o['customer_name'] or '(без ФИО)'}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, o["order_id"])
            self.order_list.addItem(item)
            if keep_order_id is not None and o["order_id"] == keep_order_id:
                select_idx = i

        if not self._orders:
            self.detail_text.setPlainText("Заказов, требующих проверки, нет.")
            self.assign_btn.setEnabled(False)
            return

        self.order_list.setCurrentRow(select_idx if select_idx is not None else 0)

    def _on_order_selected(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        if current is None:
            self.detail_text.clear()
            self.assign_btn.setEnabled(False)
            return
        order_id = current.data(Qt.UserRole)
        row = self.conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return
        info = (
            f"№ заказа: {row['order_no'] or '—'}\n"
            f"ФИО: {row['customer_name'] or '—'}\n"
            f"Контакты: {row['contacts'] or '—'}\n"
            f"Доставка: {row['delivery_method'] or '—'}\n"
            f"Адрес: {row['delivery_address'] or '—'}\n"
            f"Сумма: {row['order_amount'] if row['order_amount'] is not None else '—'}\n"
            f"Источник: {row['source'] or '—'}\n\n"
            f"--- Исходное сообщение ---\n{row['source_raw'] or '(нет)'}"
        )
        self.detail_text.setPlainText(info)
        self.type_list.clearSelection()
        self.report_checkbox.setChecked(False)
        self.assign_btn.setEnabled(True)

    def _on_assign(self) -> None:
        current = self.order_list.currentItem()
        if current is None:
            return
        order_id = current.data(Qt.UserRole)
        codes = [item.data(Qt.UserRole) for item in self.type_list.selectedItems()]
        if not codes:
            QMessageBox.warning(self, "Проверка", "Выберите хотя бы один тип теста.")
            return

        try:
            repo.add_tests_to_order(
                self.conn, order_id, codes,
                report_added=self.report_checkbox.isChecked(),
                user_name="operator",
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))
            return

        QMessageBox.information(self, "Готово", "Тесты добавлены, заказ снят с проверки.")
        self._reload()
