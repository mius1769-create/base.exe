"""
GENOPOISK CRM — вкладка «Дашборд»: вспомогательные диалоги настройки.

Отдельный файл, тот же паттерн, что haplogroup_edit_dialog.py/
projects_dialog.py — небольшие модальные диалоги, не разрастающие
dashboard_tab.py.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QSpinBox, QLabel,
    QDialogButtonBox, QMessageBox,
)

from . import dashboard_repo as drepo


class TestPricingDialog(QDialog):
    """Справочник цены продажи / себестоимости по каждому типу теста
    (используется подвкладкой «Финансы» — KPI и «Экономика по тестам»)."""

    _COLUMNS = [("code", "Код"), ("display_name", "Тип теста"), ("price", "Цена продажи"), ("cost_price", "Себестоимость")]

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Себестоимость и цены по типам теста")
        self.resize(520, 420)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Цена продажи и себестоимость на один тест — используются в "
            "блоках «Финансы» и «Экономика по тестам» дашборда."
        ))

        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _k, label in self._COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self) -> None:
        rows = drepo.list_test_type_pricing(self.conn)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            code_item = QTableWidgetItem(row["code"])
            code_item.setFlags(code_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, code_item)

            name_item = QTableWidgetItem(row["display_name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 1, name_item)

            self.table.setItem(i, 2, QTableWidgetItem(f"{row['price']:g}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{row['cost_price']:g}"))

    def _on_save(self) -> None:
        for i in range(self.table.rowCount()):
            code = self.table.item(i, 0).text()
            try:
                price = float((self.table.item(i, 2).text() or "0").replace(",", "."))
                cost_price = float((self.table.item(i, 3).text() or "0").replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Проверка", f"Цена/себестоимость для {code} должна быть числом.")
                return
            drepo.update_test_type_pricing(self.conn, code, price=price, cost_price=cost_price)
        self.accept()


class PlanTargetsDialog(QDialog):
    """Плановые показатели на месяц (подвкладка «Статистика» → «План/факт»)."""

    def __init__(self, conn: sqlite3.Connection, month: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.month = month
        self.setWindowTitle(f"План на {month}")
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.orders_spin = QSpinBox()
        self.orders_spin.setRange(0, 100000)
        form.addRow("План по заказам", self.orders_spin)

        self.tests_spin = QSpinBox()
        self.tests_spin.setRange(0, 100000)
        form.addRow("План по тестам", self.tests_spin)

        self.issued_spin = QSpinBox()
        self.issued_spin.setRange(0, 100000)
        form.addRow("План по выдачам", self.issued_spin)

        self.revenue_spin = QSpinBox()
        self.revenue_spin.setRange(0, 100_000_000)
        self.revenue_spin.setSingleStep(10000)
        self.revenue_spin.setSuffix(" ₽")
        form.addRow("План по выручке", self.revenue_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self) -> None:
        targets = drepo.get_targets(self.conn, self.month)
        self.orders_spin.setValue(targets["target_orders"])
        self.tests_spin.setValue(targets["target_tests"])
        self.issued_spin.setValue(targets["target_issued"])
        self.revenue_spin.setValue(targets["target_revenue"])

    def _on_save(self) -> None:
        drepo.upsert_targets(
            self.conn, self.month,
            target_orders=self.orders_spin.value(),
            target_tests=self.tests_spin.value(),
            target_issued=self.issued_spin.value(),
            target_revenue=self.revenue_spin.value(),
        )
        self.accept()
