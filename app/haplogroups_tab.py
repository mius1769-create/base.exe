"""
GENOPOISK CRM — третья вкладка «Гаплогруппы».

Полностью самостоятельная вкладка: свои фильтры, своя таблица, свой
экспорт. Не переиспользует и не меняет client_tab.py/internal_tab.py —
только общий визуальный слой theme.py (без изменений в нём).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox,
)

from . import haplogroups_repo as hrepo
from . import projects_repo as prepo
from . import haplogroup_logic as hlogic
from . import theme

COLUMNS = [
    ("test_number", "№ теста"),
    ("full_name", "ФИО"),
    ("project", "Проект"),
    ("y_dna", "Y-ДНК"),
    ("mt_dna", "mtDNA"),
    ("nevgen_prediction", "Предикция NevGen"),
    ("semargl_prediction", "Предикция Semargl"),
    ("snp_issued", "SNP клиенту"),
    ("comment", "Комментарий"),
]

# Согласованность NevGen/Semargl -> цвет строки (раздел ТЗ).
_ROW_BG = {
    hlogic.HaploColor.GREEN: "#e9f8ef",
    hlogic.HaploColor.YELLOW: "#fff6df",
    hlogic.HaploColor.RED: "#fee2e2",
}


class HaplogroupsTabWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        self._rows_cache: list[dict] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Проект:"))
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.project_combo, stretch=2)

        self.test_number_edit = QLineEdit()
        self.test_number_edit.setPlaceholderText("№ теста")
        self.test_number_edit.textChanged.connect(self.refresh)
        filter_row.addWidget(self.test_number_edit, stretch=1)

        self.full_name_edit = QLineEdit()
        self.full_name_edit.setPlaceholderText("ФИО")
        self.full_name_edit.textChanged.connect(self.refresh)
        filter_row.addWidget(self.full_name_edit, stretch=1)

        self.y_dna_edit = QLineEdit()
        self.y_dna_edit.setPlaceholderText("Y-ДНК")
        self.y_dna_edit.textChanged.connect(self.refresh)
        filter_row.addWidget(self.y_dna_edit, stretch=1)

        self.mt_dna_edit = QLineEdit()
        self.mt_dna_edit.setPlaceholderText("mtDNA")
        self.mt_dna_edit.textChanged.connect(self.refresh)
        filter_row.addWidget(self.mt_dna_edit, stretch=1)

        self.snp_edit = QLineEdit()
        self.snp_edit.setPlaceholderText("SNP клиенту")
        self.snp_edit.textChanged.connect(self.refresh)
        filter_row.addWidget(self.snp_edit, stretch=1)

        root.addLayout(filter_row)

        toolbar_row = QHBoxLayout()
        add_btn = QPushButton("Добавить запись")
        add_btn.clicked.connect(self._on_add)
        toolbar_row.addWidget(add_btn)

        projects_btn = QPushButton("Управление проектами")
        projects_btn.clicked.connect(self._on_manage_projects)
        toolbar_row.addWidget(projects_btn)

        toolbar_row.addStretch(1)

        export_xlsx_btn = QPushButton("Экспорт Excel")
        export_xlsx_btn.clicked.connect(self._on_export_excel)
        toolbar_row.addWidget(export_xlsx_btn)

        export_csv_btn = QPushButton("Экспорт CSV")
        export_csv_btn.clicked.connect(self._on_export_csv)
        toolbar_row.addWidget(export_csv_btn)

        root.addLayout(toolbar_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _k, label in COLUMNS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        root.addWidget(self.table, stretch=1)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{theme.TEXT_MUTED}; font-size:11px;")
        root.addWidget(self.count_label)

    # ------------------------------------------------------------------
    def _reload_project_filter(self) -> None:
        current = self.project_combo.currentData() if self.project_combo.count() else None
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Все проекты", userData=None)
        tree = prepo.build_tree(self.conn, include_archived=True)
        for pid, name, depth, archived in prepo.flatten_tree(tree):
            label = ("  " * depth) + name + ("  (архив)" if archived else "")
            self.project_combo.addItem(label, userData=pid)
        idx = self.project_combo.findData(current)
        self.project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.project_combo.blockSignals(False)

    def refresh(self, *_args) -> None:
        self._reload_project_filter()
        project_id = self.project_combo.currentData()

        rows = hrepo.list_haplogroups(
            self.conn,
            project_id=project_id,
            test_number=self.test_number_edit.text().strip() or None,
            full_name=self.full_name_edit.text().strip() or None,
            y_dna=self.y_dna_edit.text().strip() or None,
            mt_dna=self.mt_dna_edit.text().strip() or None,
            snp_issued=self.snp_edit.text().strip() or None,
        )

        self._rows_cache = []
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            color = hlogic.calculate_haplo_color(
                row["nevgen_prediction"], row["semargl_prediction"], row["y_dna"]
            )
            project_path = prepo.get_project_path(self.conn, row["project_id"])
            values = {
                "test_number": row["test_number"] or "",
                "full_name": row["display_full_name"] or "",
                "project": project_path,
                "y_dna": row["y_dna"] or "",
                "mt_dna": row["mt_dna"] or "",
                "nevgen_prediction": row["nevgen_prediction"] or "",
                "semargl_prediction": row["semargl_prediction"] or "",
                "snp_issued": row["snp_issued"] or "",
                "comment": row["comment"] or "",
            }
            bg = _ROW_BG.get(color)
            for col_idx, (key, _label) in enumerate(COLUMNS):
                item = QTableWidgetItem(values[key])
                item.setData(Qt.UserRole, row["test_number"])
                if bg:
                    item.setBackground(QColor(bg))
                self.table.setItem(i, col_idx, item)
            self._rows_cache.append({
                "test_number": values["test_number"],
                "full_name": values["full_name"],
                "project_path": project_path,
                "y_dna": values["y_dna"],
                "mt_dna": values["mt_dna"],
                "nevgen_prediction": values["nevgen_prediction"],
                "semargl_prediction": values["semargl_prediction"],
                "snp_issued": values["snp_issued"],
                "comment": values["comment"],
            })
        self.table.setSortingEnabled(True)
        self.count_label.setText(f"Записей: {len(rows)}")

    # ------------------------------------------------------------------
    def _on_row_double_clicked(self, index) -> None:
        item = self.table.item(index.row(), 0)
        if item is None:
            return
        self._open_edit_dialog(item.data(Qt.UserRole))

    def _on_add(self) -> None:
        self._open_edit_dialog(None)

    def _open_edit_dialog(self, test_number: Optional[str]) -> None:
        from .haplogroup_edit_dialog import HaplogroupEditDialog
        dlg = HaplogroupEditDialog(self.conn, self, test_number=test_number)
        if dlg.exec():
            self.refresh()

    def _on_manage_projects(self) -> None:
        from .projects_dialog import ProjectsDialog
        dlg = ProjectsDialog(self.conn, self)
        dlg.exec()
        self.refresh()

    def _on_export_excel(self) -> None:
        from . import exporter
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить экспорт как", "haplogroups_export.xlsx", "Excel файлы (*.xlsx)"
        )
        if not path:
            return
        try:
            count = exporter.export_haplogroups_to_excel(self._rows_cache, path)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))
            return
        QMessageBox.information(self, "Экспорт завершён", f"Выгружено строк: {count}\n{path}")

    def _on_export_csv(self) -> None:
        from . import exporter
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить экспорт как", "haplogroups_export.csv", "CSV файлы (*.csv)"
        )
        if not path:
            return
        try:
            count = exporter.export_haplogroups_to_csv(self._rows_cache, path)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))
            return
        QMessageBox.information(self, "Экспорт завершён", f"Выгружено строк: {count}\n{path}")
