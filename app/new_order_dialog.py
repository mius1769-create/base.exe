"""
GENOPOISK CRM — диалог создания нового заказа с одним или несколькими тестами
(раздел 5 ТЗ: заказ и тест — разные сущности, один заказ может содержать
несколько тестов).
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QDateEdit, QListWidget,
    QListWidgetItem, QCheckBox, QPushButton, QHBoxLayout, QVBoxLayout,
    QMessageBox, QLabel,
)

from . import repository as repo
from . import business_logic as bl
from . import product_catalog as pcat


class NewOrderDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        repo.ensure_order_promo_column(self.conn)
        self.setWindowTitle("Новый заказ")
        self.resize(480, 560)
        self._build_form()

    def _build_form(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.order_no_edit = QLineEdit()
        form.addRow("№ заказа", self.order_no_edit)

        self.customer_edit = QLineEdit()
        form.addRow("ФИО*", self.customer_edit)

        self.contacts_edit = QLineEdit()
        form.addRow("Контакты", self.contacts_edit)

        self.delivery_combo = QComboBox()
        methods = [m["name"] for m in self.conn.execute(
            "SELECT name FROM delivery_methods WHERE is_active=1 ORDER BY sort_order"
        ).fetchall()]
        self.delivery_combo.addItems([""] + methods)
        form.addRow("Способ доставки", self.delivery_combo)

        self.address_edit = QLineEdit()
        form.addRow("Адрес доставки", self.address_edit)

        self.tracking_edit = QLineEdit()
        form.addRow("Номер отправления", self.tracking_edit)

        self.gns_number_edit = QLineEdit()
        try:
            self._suggested_gns = bl.peek_next_gnpsk_number(self.conn)
        except sqlite3.Error:
            self._suggested_gns = ""
        self.gns_number_edit.setText(self._suggested_gns)
        self.gns_number_edit.setPlaceholderText("Автоматически, при необходимости отредактируйте")
        self.gns_number_edit.setToolTip(
            "Номер теста генерируется автоматически по счётчику. Отредактируйте поле,\n"
            "если нужно проставить конкретный номер вручную (например, для старого\n"
            "теста 2025 года). Доступно только когда в заказе один тест."
        )
        form.addRow("№ теста (GNS)", self.gns_number_edit)

        layout.addLayout(form)

        layout.addWidget(QLabel("<b>Тесты в заказе</b> (выберите один или несколько):"))
        self.type_list = QListWidget()
        self.type_list.setSelectionMode(QListWidget.MultiSelection)
        self._test_types = repo.list_test_types(self.conn)
        for tt in self._test_types:
            item = QListWidgetItem(f"{pcat.get_display_name(tt['code'])} ({tt['base_deadline_days']} дн.)")
            item.setData(1000, tt["code"])
            self.type_list.addItem(item)
        layout.addWidget(self.type_list)

        self.report_checkbox = QCheckBox("Добавить услугу «Отчёт» (+15 дней, недоступно для WGS)")
        layout.addWidget(self.report_checkbox)

        form2 = QFormLayout()
        self.sample_date = QDateEdit(calendarPopup=True)
        self.sample_date.setDisplayFormat("dd.MM.yyyy")
        self.sample_date.setDate(QDate.currentDate())
        self.has_sample_checkbox = QCheckBox("Образец уже получен")
        form2.addRow(self.has_sample_checkbox, self.sample_date)
        layout.addLayout(form2)

        form3 = QFormLayout()
        self.amount_edit = QLineEdit()
        form3.addRow("Сумма заказа", self.amount_edit)
        self.promo_checkbox = QCheckBox("Промо-заказ (бартер / реклама)")
        self.promo_checkbox.setToolTip("Не учитывается в коммерческой финансовой статистике, но остаётся в операционной нагрузке.")
        form3.addRow(self.promo_checkbox)
        layout.addLayout(form3)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Создать заказ")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        if not self.customer_edit.text().strip():
            QMessageBox.warning(self, "Проверка", "ФИО обязательно для заполнения.")
            return

        selected_codes = [item.data(1000) for item in self.type_list.selectedItems()]
        if not selected_codes:
            QMessageBox.warning(self, "Проверка", "Выберите хотя бы один тип теста.")
            return

        report_added = self.report_checkbox.isChecked()
        if report_added:
            for code in selected_codes:
                tt = next(t for t in self._test_types if t["code"] == code)
                if not tt["report_allowed"]:
                    QMessageBox.warning(
                        self, "Недопустимая комплектация",
                        f"Для «{pcat.get_display_name(tt['code'])}» добавление отчёта запрещено.",
                    )
                    return

        amount = None
        if self.amount_edit.text().strip():
            try:
                amount = float(self.amount_edit.text().strip().replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Проверка", "Сумма заказа должна быть числом.")
                return

        sample_date = None
        if self.has_sample_checkbox.isChecked():
            qd = self.sample_date.date()
            sample_date = date(qd.year(), qd.month(), qd.day())

        manual_gns_number = None
        gns_text = self.gns_number_edit.text().strip()
        if gns_text and gns_text != self._suggested_gns:
            if len(selected_codes) != 1:
                QMessageBox.warning(
                    self, "Проверка",
                    "Ручной номер теста можно указать, только когда в заказе один тест.\n"
                    "Для комплекта из нескольких тестов оставьте поле «№ теста» без изменений.",
                )
                return
            manual_gns_number = gns_text

        data = repo.NewOrderInput(
            order_no=self.order_no_edit.text().strip(),
            customer_name=self.customer_edit.text().strip(),
            contacts=self.contacts_edit.text().strip(),
            delivery_method=self.delivery_combo.currentText(),
            delivery_address=self.address_edit.text().strip(),
            tracking_number=self.tracking_edit.text().strip(),
            order_amount=amount,
            is_promo=self.promo_checkbox.isChecked(),
            source="manual",
            test_type_codes=selected_codes,
            report_added=report_added,
            sample_received_at=sample_date,
            user_name="operator",
            manual_gns_number=manual_gns_number,
        )
        try:
            repo.create_order_with_tests(self.conn, data)
        except ValueError as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))
            return

        self.accept()
