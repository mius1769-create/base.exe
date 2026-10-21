"""
GENOPOISK CRM — диалог добавления/редактирования одной записи справочника
test_types («Настройки → Справочники → Типы тестов и услуг», релиз 1.1.1).

Тот же паттерн, что haplogroup_edit_dialog.py/projects_dialog.py — отдельный
модальный диалог на одну запись, не разрастающий settings_dialog.py.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QDialogButtonBox, QMessageBox,
)

from . import repository as repo


class TestTypeEditDialog(QDialog):
    """code=None — добавление новой записи; code задан — редактирование
    существующей (поле «Код» в этом случае недоступно для правки, т.к. это
    PRIMARY KEY и на него ссылаются существующие тесты/сопоставления
    товаров)."""

    def __init__(self, conn: sqlite3.Connection, code: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.editing_code = code
        self.setWindowTitle("Новый тип теста/услуги" if code is None else f"Редактирование: {code}")
        self.resize(420, 380)
        self._build_ui()
        if code is not None:
            self._load(code)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Напр. REPORT — латиница, цифры, «_», без пробелов")
        if self.editing_code is not None:
            self.code_edit.setText(self.editing_code)
            self.code_edit.setEnabled(False)
        form.addRow("Код*", self.code_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Название, которое видит оператор, напр. «Отчёт»")
        form.addRow("Название*", self.name_edit)

        self.deadline_spin = QSpinBox()
        self.deadline_spin.setRange(0, 365)
        self.deadline_spin.setSuffix(" дн.")
        form.addRow("Норматив срока", self.deadline_spin)

        self.report_allowed_check = QCheckBox("Можно добавить услугу «Отчёт» поверх этого теста")
        self.report_allowed_check.setChecked(True)
        form.addRow("", self.report_allowed_check)

        self.report_extra_spin = QSpinBox()
        self.report_extra_spin.setRange(0, 365)
        self.report_extra_spin.setSuffix(" дн.")
        self.report_extra_spin.setValue(15)
        form.addRow("Доп. дни за отчёт", self.report_extra_spin)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 10_000_000)
        self.price_spin.setDecimals(2)
        self.price_spin.setSuffix(" ₽")
        form.addRow("Цена продажи*", self.price_spin)

        self.cost_price_spin = QDoubleSpinBox()
        self.cost_price_spin.setRange(0, 10_000_000)
        self.cost_price_spin.setDecimals(2)
        self.cost_price_spin.setSuffix(" ₽")
        form.addRow("Себестоимость*", self.cost_price_spin)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 100000)
        form.addRow("Порядок сортировки", self.sort_spin)

        self.active_check = QCheckBox("Активен (виден при создании заказа и в Product Mapping)")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)

        self.requires_lab_check = QCheckBox(
            "Требует лабораторной обработки (снимите для чисто сервисного продукта, напр. «Отчёт»)"
        )
        self.requires_lab_check.setChecked(True)
        self.requires_lab_check.setToolTip(
            "Если снято — продукт не участвует в гаплогруппах, лабораторной воронке,\n"
            "просрочках и расчёте сроков выполнения, но остаётся полноценной строкой\n"
            "справочника с ценой/себестоимостью и доступен при создании заказа."
        )
        form.addRow("", self.requires_lab_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self, code: str) -> None:
        row = repo.get_test_type(self.conn, code)
        self.name_edit.setText(row["display_name"])
        self.deadline_spin.setValue(row["base_deadline_days"])
        self.report_allowed_check.setChecked(bool(row["report_allowed"]))
        self.report_extra_spin.setValue(row["report_extra_days"])
        self.price_spin.setValue(row["price"])
        self.cost_price_spin.setValue(row["cost_price"])
        self.sort_spin.setValue(row["sort_order"])
        self.active_check.setChecked(bool(row["is_active"]))
        self.requires_lab_check.setChecked(bool(row["requires_lab"]))

    def _on_save(self) -> None:
        code = self.code_edit.text().strip().upper()
        name = self.name_edit.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Проверка", "Код и название обязательны для заполнения.")
            return
        if self.editing_code is None and (not code.isascii() or not code.replace("_", "").isalnum()):
            QMessageBox.warning(
                self, "Проверка",
                "Код может содержать только латинские буквы, цифры и «_» (напр. REPORT, WGS45).",
            )
            return

        kwargs = dict(
            display_name=name,
            base_deadline_days=self.deadline_spin.value(),
            report_allowed=self.report_allowed_check.isChecked(),
            report_extra_days=self.report_extra_spin.value(),
            price=self.price_spin.value(),
            cost_price=self.cost_price_spin.value(),
            is_active=self.active_check.isChecked(),
            sort_order=self.sort_spin.value(),
            requires_lab=self.requires_lab_check.isChecked(),
        )
        try:
            if self.editing_code is None:
                repo.insert_test_type(self.conn, code=code, **kwargs)
            else:
                repo.update_test_type(self.conn, self.editing_code, **kwargs)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Проверка", f"Тип теста с кодом «{code}» уже существует.")
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Проверка", str(exc))
            return

        self.accept()
