"""GENOPOISK CRM — диалог настроек (раздел 20 ТЗ)."""
from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton, QHBoxLayout,
    QVBoxLayout, QFileDialog, QMessageBox, QTabWidget, QWidget, QListWidget,
    QListWidgetItem, QCheckBox,
)

from . import settings as st
from . import business_logic as bl
from . import secrets_store


class SettingsDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Настройки")
        self.resize(520, 480)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_general_tab(), "Основные")
        tabs.addTab(self._build_backup_tab(), "Резервные копии")
        tabs.addTab(self._build_dictionaries_tab(), "Справочники")
        tabs.addTab(self._build_telegram_tab(), "Telegram")

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.gnpsk_start_edit = QLineEdit()
        self.gnpsk_start_edit.setPlaceholderText(
            "Оставьте пустым, чтобы не менять; например: 109400"
        )
        form.addRow("Стартовый номер GNPSK", self.gnpsk_start_edit)

        self.soon_days_spin = QSpinBox()
        self.soon_days_spin.setRange(1, 60)
        self.soon_days_spin.setValue(st.get_int_setting(self.conn, "deadline_soon_threshold_days", 5))
        form.addRow("Порог «приближается дедлайн» (дней)", self.soon_days_spin)

        return w

    def _build_backup_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()

        row = QHBoxLayout()
        self.backup_folder_edit = QLineEdit(st.get_setting(self.conn, "backup_folder", ""))
        choose_btn = QPushButton("Выбрать…")
        choose_btn.clicked.connect(self._choose_backup_folder)
        row.addWidget(self.backup_folder_edit)
        row.addWidget(choose_btn)
        form.addRow("Папка резервных копий", row)

        self.keep_count_spin = QSpinBox()
        self.keep_count_spin.setRange(1, 365)
        self.keep_count_spin.setValue(st.get_int_setting(self.conn, "backup_keep_count", 30))
        form.addRow("Хранить последних копий", self.keep_count_spin)

        layout.addLayout(form)
        layout.addStretch(1)
        return w

    def _choose_backup_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выбрать папку резервных копий")
        if path:
            self.backup_folder_edit.setText(path)

    def _build_dictionaries_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLineEdit_label("Операторы:"))
        self.operators_list = QListWidget()
        self._reload_operators()
        layout.addWidget(self.operators_list)

        row = QHBoxLayout()
        self.new_operator_edit = QLineEdit()
        self.new_operator_edit.setPlaceholderText("Имя нового оператора")
        add_btn = QPushButton("Добавить")
        add_btn.clicked.connect(self._add_operator)
        row.addWidget(self.new_operator_edit)
        row.addWidget(add_btn)
        layout.addLayout(row)

        return w

    def _reload_operators(self) -> None:
        self.operators_list.clear()
        for row in self.conn.execute("SELECT name FROM operators WHERE is_active=1 ORDER BY name"):
            self.operators_list.addItem(QListWidgetItem(row["name"]))

    def _add_operator(self) -> None:
        name = self.new_operator_edit.text().strip()
        if not name:
            return
        try:
            self.conn.execute("INSERT INTO operators(name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            pass
        self.new_operator_edit.clear()
        self._reload_operators()

    def _build_telegram_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLineEdit_label(
            "Bot Token хранится только локально (вне исходного кода и БД).\n"
            "Приём заказов работает long-polling'ом, пока программа открыта."
        ))
        form = QFormLayout()
        self.token_edit = QLineEdit(secrets_store.get_telegram_bot_token() or "")
        self.token_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Bot Token", self.token_edit)
        layout.addLayout(form)

        test_row = QHBoxLayout()
        self.test_conn_btn = QPushButton("Проверить подключение")
        self.test_conn_btn.clicked.connect(self._test_telegram_connection)
        test_row.addWidget(self.test_conn_btn)
        self.test_conn_result = QLineEdit_label("")
        test_row.addWidget(self.test_conn_result, stretch=1)
        layout.addLayout(test_row)

        self.polling_checkbox = QCheckBox("Автоматически принимать заказы из Telegram при запуске программы")
        self.polling_checkbox.setChecked(st.get_setting(self.conn, "telegram_polling_enabled", "0") == "1")
        layout.addWidget(self.polling_checkbox)

        layout.addStretch(1)
        return w

    def _test_telegram_connection(self) -> None:
        token = self.token_edit.text().strip()
        if not token:
            self.test_conn_result.setText("Введите Bot Token перед проверкой.")
            return
        try:
            from . import telegram_client as tc
            info = tc.get_me(token)
            username = info.get("username", "?")
            self.test_conn_result.setText(f"✓ Подключение успешно: @{username}")
        except Exception as exc:  # noqa: BLE001
            self.test_conn_result.setText(f"✗ Ошибка: {exc}")

    def _on_save(self) -> None:
        if self.gnpsk_start_edit.text().strip():
            try:
                start = int(self.gnpsk_start_edit.text().strip())
            except ValueError:
                QMessageBox.warning(self, "Проверка", "Стартовый номер GNPSK должен быть целым числом.")
                return
            bl.set_gnpsk_start_number(self.conn, start)

        st.set_setting(self.conn, "deadline_soon_threshold_days", str(self.soon_days_spin.value()))
        st.set_setting(self.conn, "backup_folder", self.backup_folder_edit.text().strip())
        st.set_setting(self.conn, "backup_keep_count", str(self.keep_count_spin.value()))

        token = self.token_edit.text().strip()
        if token:
            secrets_store.set_telegram_bot_token(token)

        st.set_setting(self.conn, "telegram_polling_enabled", "1" if self.polling_checkbox.isChecked() else "0")

        self.accept()


def QLineEdit_label(text: str):
    """Небольшой хелпер: многострочная подпись без создания отдельного импорта QLabel в каждом месте."""
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    return lbl
