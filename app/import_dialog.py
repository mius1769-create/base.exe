"""GENOPOISK CRM — диалог импорта Excel (раздел 16 ТЗ): предпросмотр + статистика."""
from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QTextEdit,
)

from . import importer


class ImportDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Импорт исторической базы из Excel")
        self.resize(900, 600)
        self.file_path: str | None = None
        self.preview: importer.ImportPreview | None = None

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.choose_btn = QPushButton("Выбрать файл Excel…")
        self.choose_btn.clicked.connect(self._choose_file)
        top_row.addWidget(self.choose_btn)
        self.file_label = QLabel("Файл не выбран")
        top_row.addWidget(self.file_label, stretch=1)
        layout.addLayout(top_row)

        self.mapping_label = QLabel("")
        self.mapping_label.setWordWrap(True)
        layout.addWidget(self.mapping_label)

        self.preview_table = QTableWidget(0, 0)
        layout.addWidget(self.preview_table, stretch=1)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(120)
        self.result_text.setVisible(False)
        layout.addWidget(self.result_text)

        btn_row = QHBoxLayout()
        self.import_btn = QPushButton("Импортировать")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._do_import)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(self.import_btn)
        layout.addLayout(btn_row)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать Excel файл", "", "Excel файлы (*.xlsx *.xlsm)")
        if not path:
            return
        self.file_path = path
        self.file_label.setText(path)
        try:
            self.preview = importer.preview_excel(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка чтения файла", str(exc))
            return

        unmapped = [f for f, h in self.preview.column_mapping.items() if h is None]
        mapping_text = "Найдено соответствие колонок: " + ", ".join(
            f"{f} → {h}" for f, h in self.preview.column_mapping.items() if h
        )
        if unmapped:
            mapping_text += f"\nНе найдены (будут пустыми): {', '.join(unmapped)}"
        if "gns_number" in unmapped:
            mapping_text += "\n\n⚠ Не найдена колонка с номером GNS/GNPSK — импорт невозможен без неё."
            self.import_btn.setEnabled(False)
        else:
            self.import_btn.setEnabled(True)
        self.mapping_label.setText(mapping_text)

        self.preview_table.setColumnCount(len(self.preview.headers))
        self.preview_table.setHorizontalHeaderLabels(self.preview.headers)
        self.preview_table.setRowCount(len(self.preview.sample_rows))
        for i, row_dict in enumerate(self.preview.sample_rows):
            for j, h in enumerate(self.preview.headers):
                self.preview_table.setItem(i, j, QTableWidgetItem(str(row_dict.get(h, "") or "")))

        self.file_label.setText(f"{path}  ·  строк данных: {self.preview.total_rows}")

    def _do_import(self) -> None:
        if not self.file_path or not self.preview:
            return
        result = importer.import_excel(self.conn, self.file_path, self.preview.column_mapping)
        self.conn.commit() if hasattr(self.conn, "commit") else None

        summary = (
            f"Импортировано: {result.imported}\n"
            f"Пропущено дублей (GNS уже существует): {result.skipped_duplicates}\n"
            f"Ошибок: {result.errors}\n"
            f"Всего строк обработано: {result.total_rows}\n"
        )
        if result.error_details:
            summary += "\nПервые ошибки:\n" + "\n".join(
                f"  строка {e['row_number']}: {e['error_message']}" for e in result.error_details[:10]
            )
        self.result_text.setPlainText(summary)
        self.result_text.setVisible(True)
        self.import_btn.setEnabled(False)
        QMessageBox.information(self, "Импорт завершён", summary.split("\n\n")[0])
