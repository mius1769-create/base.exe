"""GENOPOISK CRM — диалог резервного копирования и восстановления (раздел 19 ТЗ)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QApplication,
)

from . import backup as bk
from . import settings as st
from .db import get_db_path


class BackupDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Резервное копирование")
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        folder = st.get_setting(conn, "backup_folder", "") or "(папка не выбрана — задайте в Настройках)"
        self.folder_label = QLabel(f"Папка резервных копий: {folder}")
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)

        btn_row = QHBoxLayout()
        self.backup_now_btn = QPushButton("Создать резервную копию сейчас")
        self.backup_now_btn.clicked.connect(self._backup_now)
        btn_row.addWidget(self.backup_now_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Доступные резервные копии:"))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)
        self._reload_list()

        restore_row = QHBoxLayout()
        self.restore_btn = QPushButton("Восстановить из выбранной копии…")
        self.restore_btn.clicked.connect(self._restore_selected)
        restore_row.addStretch(1)
        restore_row.addWidget(self.restore_btn)
        layout.addLayout(restore_row)

        close_row = QHBoxLayout()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_row.addStretch(1)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _folder(self) -> Path | None:
        folder = st.get_setting(self.conn, "backup_folder", "")
        return Path(folder) if folder else None

    def _reload_list(self) -> None:
        self.list_widget.clear()
        folder = self._folder()
        if not folder:
            return
        for p in bk.list_backups(folder):
            item = QListWidgetItem(p.name)
            item.setData(1000, str(p))
            self.list_widget.addItem(item)

    def _backup_now(self) -> None:
        folder = self._folder()
        if not folder:
            QMessageBox.information(
                self, "Папка не выбрана",
                "Сначала выберите папку резервных копий в Настройках.",
            )
            return
        try:
            dest = bk.create_backup(get_db_path(), folder)
            keep = st.get_int_setting(self.conn, "backup_keep_count", 30)
            bk.prune_old_backups(folder, keep)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка backup", str(exc))
            return
        QMessageBox.information(self, "Готово", f"Резервная копия создана:\n{dest.name}")
        self._reload_list()

    def _restore_selected(self) -> None:
        items = self.list_widget.selectedItems()
        if not items:
            QMessageBox.information(self, "Восстановление", "Выберите резервную копию из списка.")
            return
        backup_path = Path(items[0].data(1000))

        confirm = QMessageBox.warning(
            self, "Подтверждение восстановления",
            f"Текущая база будет заменена содержимым:\n{backup_path.name}\n\n"
            "Перед восстановлением будет автоматически создана резервная копия текущей базы.\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            self.conn.close()
        except sqlite3.Error:
            pass

        pre_backup = bk.restore_backup(
            backup_path, get_db_path(), pre_restore_backup_folder=self._folder()
        )
        msg = "База восстановлена. Приложение сейчас закроется — запустите его заново."
        if pre_backup:
            msg += f"\n\nРезервная копия базы до восстановления сохранена как:\n{pre_backup.name}"
        QMessageBox.information(self, "Восстановлено", msg)
        self.accept()
        QApplication.quit()  # соединение уже закрыто выше; безопаснее перезапустить процесс целиком
