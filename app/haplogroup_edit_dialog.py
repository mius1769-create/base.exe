"""
GENOPOISK CRM — диалог добавления/редактирования записи гаплогруппы
(вкладка «Гаплогруппы»). ФИО подтягивается из карточки заказа теста и
здесь не редактируется — только показывается для проверки.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QLabel, QTextEdit, QPushButton, QMessageBox, QCompleter,
)

from . import haplogroups_repo as hrepo
from . import projects_repo as prepo


class HaplogroupEditDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None, test_number: Optional[str] = None):
        super().__init__(parent)
        self.conn = conn
        self._locked_test_number = test_number
        self.setWindowTitle(f"Запись гаплогруппы — {test_number}" if test_number else "Новая запись гаплогруппы")
        self.resize(480, 540)
        self._build_ui()
        if test_number:
            self._load_existing(test_number)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.test_combo = QComboBox()
        self.test_combo.setEditable(True)
        self.test_combo.setInsertPolicy(QComboBox.NoInsert)
        for t in hrepo.list_test_numbers_for_picker(self.conn):
            self.test_combo.addItem(f"{t['gns_number']} — {t['customer_name']}", userData=t["gns_number"])
        completer = QCompleter([self.test_combo.itemText(i) for i in range(self.test_combo.count())], self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.test_combo.setCompleter(completer)
        self.test_combo.currentIndexChanged.connect(self._on_test_changed)
        self.test_combo.editTextChanged.connect(self._on_test_changed)
        form.addRow("№ теста*", self.test_combo)

        if self._locked_test_number:
            idx = self.test_combo.findData(self._locked_test_number)
            if idx >= 0:
                self.test_combo.setCurrentIndex(idx)
            self.test_combo.setEnabled(False)

        self.full_name_label = QLabel("—")
        form.addRow("ФИО (из карточки)", self.full_name_label)

        self.project_combo = QComboBox()
        self.project_combo.addItem("— без проекта —", userData=None)
        tree = prepo.build_tree(self.conn, include_archived=False)
        for pid, name, depth, _archived in prepo.flatten_tree(tree):
            self.project_combo.addItem(("  " * depth) + name, userData=pid)
        form.addRow("Проект", self.project_combo)

        self.y_dna_edit = QLineEdit()
        form.addRow("Y-ДНК", self.y_dna_edit)
        self.mt_dna_edit = QLineEdit()
        form.addRow("mtDNA", self.mt_dna_edit)
        self.nevgen_edit = QLineEdit()
        form.addRow("Предикция NevGen", self.nevgen_edit)
        self.semargl_edit = QLineEdit()
        form.addRow("Предикция Semargl", self.semargl_edit)
        self.snp_edit = QLineEdit()
        form.addRow("SNP клиенту", self.snp_edit)

        layout.addLayout(form)

        layout.addWidget(QLabel("Комментарий"))
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(90)
        layout.addWidget(self.comment_edit)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._on_test_changed()

    # ------------------------------------------------------------------
    def _current_test_number(self) -> Optional[str]:
        idx = self.test_combo.currentIndex()
        data = self.test_combo.itemData(idx) if idx >= 0 else None
        if data:
            return data
        text = self.test_combo.currentText().strip()
        if " — " in text:
            text = text.split(" — ")[0].strip()
        return text or None

    def _on_test_changed(self, *_args) -> None:
        tn = self._current_test_number()
        row = hrepo.get_test_by_number(self.conn, tn) if tn else None
        self.full_name_label.setText(row["customer_name"] if row else "—")

    def _load_existing(self, test_number: str) -> None:
        row = self.conn.execute(
            "SELECT * FROM haplogroups WHERE test_number = ?", (test_number,)
        ).fetchone()
        if row is None:
            return
        idx = self.project_combo.findData(row["project_id"])
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)
        self.y_dna_edit.setText(row["y_dna"] or "")
        self.mt_dna_edit.setText(row["mt_dna"] or "")
        self.nevgen_edit.setText(row["nevgen_prediction"] or "")
        self.semargl_edit.setText(row["semargl_prediction"] or "")
        self.snp_edit.setText(row["snp_issued"] or "")
        self.comment_edit.setPlainText(row["comment"] or "")

    def _on_save(self) -> None:
        test_number = self._current_test_number()
        if not test_number:
            QMessageBox.warning(self, "Проверка", "Выберите номер теста.")
            return
        if hrepo.get_test_by_number(self.conn, test_number) is None:
            QMessageBox.warning(self, "Проверка", f"Тест с номером {test_number!r} не найден.")
            return

        fields = {
            "project_id": self.project_combo.currentData(),
            "y_dna": self.y_dna_edit.text().strip() or None,
            "mt_dna": self.mt_dna_edit.text().strip() or None,
            "nevgen_prediction": self.nevgen_edit.text().strip() or None,
            "semargl_prediction": self.semargl_edit.text().strip() or None,
            "snp_issued": self.snp_edit.text().strip() or None,
            "comment": self.comment_edit.toPlainText().strip() or None,
        }
        try:
            hrepo.upsert_haplogroup(self.conn, test_number, fields)
        except ValueError as exc:
            QMessageBox.warning(self, "Проверка", str(exc))
            return
        self.accept()
