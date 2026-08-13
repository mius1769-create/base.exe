"""
GENOPOISK CRM — UI для product_mappings (задача 3 финального этапа).

Раньше сопоставление "коммерческое название товара -> набор типов теста"
можно было завести только кодом (repo.upsert_product_mapping). Этот диалог
даёт то же самое из интерфейса — нужен, чтобы заполнить полный список
товаров сайта под Telegram-парсер (раздел 28 ТЗ) без правки кода.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QLineEdit, QListWidget, QListWidgetItem, QCheckBox,
    QMessageBox, QHeaderView, QAbstractItemView,
)

from . import repository as repo
from . import product_catalog as pcat


class ProductMappingsDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Товары сайта → типы тестов (для Telegram)")
        self.resize(760, 560)
        self._editing_id: int | None = None
        self._build_ui()
        self._reload_table()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Сопоставление коммерческих названий товаров сайта с внутренними типами "
            "тестов. Используется парсером Telegram-сообщений — если товар не найден "
            "здесь, заказ уходит на ручную проверку, а не угадывается."
        ))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Название товара", "Типы теста", "Отчёт", "Заметки"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table, stretch=1)

        form_label = QLabel("<b>Добавить / изменить</b>")
        layout.addWidget(form_label)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Название товара точно как в сообщении Telegram / на сайте")
        layout.addWidget(self.name_edit)

        types_row = QHBoxLayout()
        types_row.addWidget(QLabel("Типы теста в комплекте:"))
        self.types_list = QListWidget()
        self.types_list.setSelectionMode(QListWidget.MultiSelection)
        self.types_list.setMaximumHeight(140)
        for tt in repo.list_test_types(self.conn):
            item = QListWidgetItem(f"{pcat.get_display_name(tt['code'])} ({tt['code']})")
            item.setData(1000, tt["code"])
            self.types_list.addItem(item)
        types_row.addWidget(self.types_list, stretch=1)
        layout.addLayout(types_row)

        self.report_checkbox = QCheckBox("Комплект включает услугу «Отчёт»")
        layout.addWidget(self.report_checkbox)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Заметки (необязательно)")
        layout.addWidget(self.notes_edit)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self._on_save)
        self.new_btn = QPushButton("Новая запись")
        self.new_btn.clicked.connect(self._clear_form)
        self.delete_btn = QPushButton("Удалить выбранную")
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setEnabled(False)
        btn_row.addWidget(self.new_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_row.addStretch(1)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _reload_table(self) -> None:
        self._mappings = repo.list_product_mappings(self.conn)
        self.table.setRowCount(len(self._mappings))
        for i, m in enumerate(self._mappings):
            self.table.setItem(i, 0, QTableWidgetItem(m["commercial_name"]))
            self.table.setItem(i, 1, QTableWidgetItem(", ".join(m["test_type_codes"])))
            self.table.setItem(i, 2, QTableWidgetItem("Да" if m["includes_report"] else "—"))
            self.table.setItem(i, 3, QTableWidgetItem(m["notes"] or ""))
            self.table.item(i, 0).setData(1000, m["id"])

    def _on_row_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.delete_btn.setEnabled(False)
            return
        row_idx = items[0].row()
        m = self._mappings[row_idx]
        self._editing_id = m["id"]
        self.name_edit.setText(m["commercial_name"])
        for i in range(self.types_list.count()):
            item = self.types_list.item(i)
            item.setSelected(item.data(1000) in m["test_type_codes"])
        self.report_checkbox.setChecked(m["includes_report"])
        self.notes_edit.setText(m["notes"] or "")
        self.delete_btn.setEnabled(True)

    def _clear_form(self) -> None:
        self._editing_id = None
        self.name_edit.clear()
        self.types_list.clearSelection()
        self.report_checkbox.setChecked(False)
        self.notes_edit.clear()
        self.table.clearSelection()
        self.delete_btn.setEnabled(False)

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Проверка", "Укажите название товара.")
            return
        codes = [self.types_list.item(i).data(1000) for i in range(self.types_list.count())
                 if self.types_list.item(i).isSelected()]
        if not codes:
            QMessageBox.warning(self, "Проверка", "Выберите хотя бы один тип теста.")
            return

        # переименование: если редактируем существующую запись под другим именем,
        # старую нужно удалить, т.к. upsert работает по commercial_name (уникальный ключ)
        if self._editing_id is not None:
            old = next((m for m in self._mappings if m["id"] == self._editing_id), None)
            if old and old["commercial_name"] != name:
                repo.delete_product_mapping(self.conn, self._editing_id)

        repo.upsert_product_mapping(
            self.conn, name, codes, self.report_checkbox.isChecked(),
            self.notes_edit.text().strip() or None,
        )
        self._reload_table()
        self._clear_form()

    def _on_delete(self) -> None:
        if self._editing_id is None:
            return
        confirm = QMessageBox.question(
            self, "Удаление", "Удалить это сопоставление товара?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        repo.delete_product_mapping(self.conn, self._editing_id)
        self._reload_table()
        self._clear_form()
