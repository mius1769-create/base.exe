"""
GENOPOISK CRM — полная форма редактирования теста/заказа (раздел 11 ТЗ).

Открывается отдельным диалогом, не занимает основной экран постоянно.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from PySide6.QtCore import QDate, QDateTime
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QDateEdit, QDateTimeEdit,
    QTextEdit, QDoubleSpinBox, QPushButton, QHBoxLayout, QVBoxLayout,
    QMessageBox, QCheckBox, QLabel, QWidget,
)

from . import repository as repo
from . import business_logic as bl


def _qdate_to_iso(qd: QDate) -> str | None:
    if not qd or not qd.isValid() or qd == QDate(2000, 1, 1):
        return None
    return qd.toString("yyyy-MM-dd")


def _qdatetime_to_iso(qdt: QDateTime) -> str | None:
    if not qdt or not qdt.isValid():
        return None
    return qdt.toString("yyyy-MM-ddTHH:mm:ss")


def _iso_to_qdatetime(value: str | None) -> QDateTime:
    if not value:
        return QDateTime()
    dt = repo.parse_iso_dt(value)
    return QDateTime(dt) if dt else QDateTime()


class OptionalDateTimeField(QWidget):
    """Дата/время этапа + чекбокс 'заполнено'. Пустой этап должен оставаться
    ПУСТЫМ маркером (раздел 10), а не молча подставлять текущее время."""

    def __init__(self, existing_iso: str | None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.checkbox = QCheckBox("заполнено")
        self.datetime_edit = QDateTimeEdit(calendarPopup=True)
        self.datetime_edit.setDisplayFormat("dd.MM.yyyy HH:mm")

        existing_qdt = _iso_to_qdatetime(existing_iso)
        if existing_qdt.isValid():
            self.checkbox.setChecked(True)
            self.datetime_edit.setDateTime(existing_qdt)
        else:
            self.checkbox.setChecked(False)
            self.datetime_edit.setDateTime(QDateTime.currentDateTime())
        self.datetime_edit.setEnabled(self.checkbox.isChecked())
        self.checkbox.toggled.connect(self.datetime_edit.setEnabled)

        layout.addWidget(self.datetime_edit, stretch=1)
        layout.addWidget(self.checkbox)

    def value_iso(self) -> str | None:
        if not self.checkbox.isChecked():
            return None
        return _qdatetime_to_iso(self.datetime_edit.dateTime())


class TestEditDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, test_id: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.test_id = test_id
        self.setWindowTitle("Редактирование теста")
        self.resize(520, 700)

        self.row = conn.execute(
            """SELECT t.*, o.order_no, o.customer_name, o.contacts, o.delivery_address,
                      o.delivery_method, o.tracking_number, o.order_amount, o.extra_payment,
                      o.refund_amount, o.order_status, o.order_id
               FROM tests t JOIN orders o ON o.order_id = t.order_id
               WHERE t.test_id = ?""",
            (test_id,),
        ).fetchone()

        self._build_form()

    def _build_form(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        r = self.row

        self.order_no_edit = QLineEdit(r["order_no"] or "")
        form.addRow("№ заказа", self.order_no_edit)

        self.gns_label = QLabel(r["gns_number"])
        form.addRow("GNS", self.gns_label)

        self.customer_edit = QLineEdit(r["customer_name"] or "")
        form.addRow("ФИО*", self.customer_edit)

        self.contacts_edit = QLineEdit(r["contacts"] or "")
        form.addRow("Контакты", self.contacts_edit)

        self.address_edit = QTextEdit(r["delivery_address"] or "")
        self.address_edit.setMaximumHeight(50)
        form.addRow("Адрес доставки", self.address_edit)

        self.delivery_combo = QComboBox()
        methods = [m["name"] for m in self.conn.execute(
            "SELECT name FROM delivery_methods WHERE is_active=1 ORDER BY sort_order"
        ).fetchall()]
        self.delivery_combo.addItems([""] + methods)
        if r["delivery_method"] in methods:
            self.delivery_combo.setCurrentText(r["delivery_method"])
        form.addRow("Способ доставки", self.delivery_combo)

        self.tracking_edit = QLineEdit(r["tracking_number"] or "")
        form.addRow("Номер отправления", self.tracking_edit)

        self.test_type_combo = QComboBox()
        self._test_types = repo.list_test_types(self.conn)
        for tt in self._test_types:
            self.test_type_combo.addItem(tt["display_name"], userData=tt["code"])
        idx = next((i for i, tt in enumerate(self._test_types) if tt["code"] == r["test_type"]), 0)
        self.test_type_combo.setCurrentIndex(idx)
        form.addRow("Тип теста*", self.test_type_combo)

        self.report_combo = QComboBox()
        self.report_combo.addItems(["Обычный", "С отчётом"])
        self.report_combo.setCurrentText(r["report_option"])
        form.addRow("Комплектация*", self.report_combo)

        self.sample_date = QDateEdit(calendarPopup=True)
        self.sample_date.setDisplayFormat("dd.MM.yyyy")
        self.sample_date.setSpecialValueText(" ")
        self.sample_date.setMinimumDate(QDate(2000, 1, 1))
        if r["sample_received_at"]:
            d = repo.parse_iso_date(r["sample_received_at"])
            self.sample_date.setDate(QDate(d.year, d.month, d.day))
        else:
            self.sample_date.setDate(QDate(2000, 1, 1))
        form.addRow("Дата прихода образца", self.sample_date)

        self.lab_sent_dt = OptionalDateTimeField(r["lab_sent_at"])
        form.addRow("Дата передачи в лабораторию", self.lab_sent_dt)

        self.lab_profile_dt = OptionalDateTimeField(r["lab_profile_received_at"])
        form.addRow("Дата профиля лаборатории", self.lab_profile_dt)

        self.operator_started_dt = OptionalDateTimeField(r["operator_started_at"])
        form.addRow("Взято в работу", self.operator_started_dt)

        self.operator_combo = QComboBox()
        self.operator_combo.setEditable(True)
        ops = [o["name"] for o in self.conn.execute(
            "SELECT name FROM operators WHERE is_active=1"
        ).fetchall()]
        self.operator_combo.addItems(ops)
        if r["operator_name"]:
            self.operator_combo.setCurrentText(r["operator_name"])
        form.addRow("Оператор", self.operator_combo)

        self.client_issued_dt = OptionalDateTimeField(r["client_issued_at"])
        form.addRow("Выдан клиенту", self.client_issued_dt)

        self.result_y_edit = QLineEdit(r["result_y"] or "")
        form.addRow("Результат Y", self.result_y_edit)

        self.result_mt_edit = QLineEdit(r["result_mt"] or "")
        form.addRow("Результат mt", self.result_mt_edit)

        self.comments_edit = QTextEdit(r["comments"] or "")
        self.comments_edit.setMaximumHeight(60)
        form.addRow("Комментарий", self.comments_edit)

        self.amount_spin = QDoubleSpinBox(); self.amount_spin.setMaximum(10_000_000)
        self.amount_spin.setValue(r["order_amount"] or 0)
        form.addRow("Сумма заказа", self.amount_spin)

        self.extra_spin = QDoubleSpinBox(); self.extra_spin.setMaximum(10_000_000)
        self.extra_spin.setValue(r["extra_payment"] or 0)
        form.addRow("Доплата", self.extra_spin)

        self.refund_spin = QDoubleSpinBox(); self.refund_spin.setMaximum(10_000_000)
        self.refund_spin.setValue(r["refund_amount"] or 0)
        form.addRow("Возврат", self.refund_spin)

        self.status_combo = QComboBox()
        self.status_combo.addItems(
            ["Оплачен", "В работе", "Выполнен", "Отменён", "Возврат", "Частичный возврат"]
        )
        if r["order_status"] in [self.status_combo.itemText(i) for i in range(self.status_combo.count())]:
            self.status_combo.setCurrentText(r["order_status"])
        form.addRow("Статус заказа*", self.status_combo)

        self._include_flags = {}  # чекбоксы "поле было изменено" не нужны — сравниваем со старым значением

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
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

        new_test_type = self.test_type_combo.currentData()
        new_report_option = self.report_combo.currentText()

        tt_row = next(tt for tt in self._test_types if tt["code"] == new_test_type)
        try:
            bl.validate_report_option(new_report_option, bool(tt_row["report_allowed"]))
        except ValueError as exc:
            QMessageBox.warning(self, "Недопустимая комплектация", str(exc))
            return

        changes = {}
        r = self.row

        def maybe(field, new_value):
            if str(r[field]) != str(new_value):
                changes[field] = new_value

        maybe("test_type", new_test_type)
        maybe("report_option", new_report_option)
        maybe("sample_received_at", _qdate_to_iso(self.sample_date.date()))
        maybe("lab_sent_at", self.lab_sent_dt.value_iso())
        maybe("lab_profile_received_at", self.lab_profile_dt.value_iso())
        maybe("operator_started_at", self.operator_started_dt.value_iso())
        maybe("operator_name", self.operator_combo.currentText().strip() or None)
        maybe("client_issued_at", self.client_issued_dt.value_iso())
        maybe("result_y", self.result_y_edit.text().strip() or None)
        maybe("result_mt", self.result_mt_edit.text().strip() or None)
        maybe("comments", self.comments_edit.toPlainText().strip() or None)

        try:
            if changes:
                repo.update_test_fields(self.conn, self.test_id, changes, user_name="operator")

            # заказ: имя/контакты/доставка + финансы/статус
            self.conn.execute(
                """UPDATE orders SET order_no=?, customer_name=?, contacts=?, delivery_address=?,
                       delivery_method=?, tracking_number=?, updated_at=? WHERE order_id=?""",
                (
                    self.order_no_edit.text().strip() or None,
                    self.customer_edit.text().strip(),
                    self.contacts_edit.text().strip() or None,
                    self.address_edit.toPlainText().strip() or None,
                    self.delivery_combo.currentText() or None,
                    self.tracking_edit.text().strip() or None,
                    repo.now_iso(),
                    r["order_id"],
                ),
            )
            repo.apply_order_financial_change(
                self.conn, r["order_id"],
                extra_payment=self.extra_spin.value(),
                refund_amount=self.refund_spin.value(),
                new_status=self.status_combo.currentText(),
                comment="ручное редактирование через полную форму",
                user_name="operator",
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return

        self.accept()
