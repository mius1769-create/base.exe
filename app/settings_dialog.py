"""GENOPOISK CRM — диалог настроек (раздел 20 ТЗ)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QPushButton, QHBoxLayout,
    QVBoxLayout, QFileDialog, QMessageBox, QTabWidget, QWidget, QListWidget,
    QListWidgetItem, QCheckBox, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox,
)

from . import settings as st
from . import business_logic as bl
from . import secrets_store
from . import repository as repo


class SettingsDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Настройки")
        self.resize(640, 640)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_general_tab(), "Основные")
        tabs.addTab(self._build_backup_tab(), "Резервные копии")
        tabs.addTab(self._build_dictionaries_tab(), "Справочники")
        tabs.addTab(self._build_products_tab(), "Продукты")
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

        layout.addWidget(_section_title("Операторы"))
        self.operators_list = QListWidget()
        self._reload_operators()
        layout.addWidget(self.operators_list)

        op_row = QHBoxLayout()
        self.new_operator_edit = QLineEdit()
        self.new_operator_edit.setPlaceholderText("Имя нового оператора")
        add_op_btn = QPushButton("Добавить")
        add_op_btn.clicked.connect(self._add_operator)
        op_row.addWidget(self.new_operator_edit)
        op_row.addWidget(add_op_btn)
        layout.addLayout(op_row)

        layout.addStretch(1)
        return w

    def _build_products_tab(self) -> QWidget:
        """«Настройки → Продукты» (раздел 20 ТЗ, релиз 1.1.3) — полноценный
        CRUD справочника test_types: и лабораторные типы теста, и чисто
        сервисные продукты (requires_lab=0, напр. «Отчёт») в одном месте,
        отдельно от простого списка «Операторы»."""
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLineEdit_label(
            "Продукты — и типы тестов, требующие лабораторной обработки, и "
            "чисто сервисные позиции (напр. «Отчёт», requires_lab снят). Новый "
            "продукт сразу доступен при создании заказа, в Product Mapping для "
            "Telegram и в расчётах дашборда — без перезапуска программы."
        ))

        self.test_types_table = QTableWidget(0, 7)
        self.test_types_table.setHorizontalHeaderLabels(
            ["Код", "Название", "Срок, дн.", "Цена", "Себестоимость", "Активен", "Лаб."]
        )
        self.test_types_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.test_types_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.test_types_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.test_types_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.test_types_table.itemSelectionChanged.connect(self._on_test_type_row_selected)
        layout.addWidget(self.test_types_table, stretch=1)

        tt_btn_row = QHBoxLayout()
        add_tt_btn = QPushButton("Добавить продукт")
        add_tt_btn.clicked.connect(self._on_add_test_type)
        self.edit_tt_btn = QPushButton("Редактировать")
        self.edit_tt_btn.setEnabled(False)
        self.edit_tt_btn.clicked.connect(self._on_edit_test_type)
        self.deactivate_tt_btn = QPushButton("Деактивировать")
        self.deactivate_tt_btn.setEnabled(False)
        self.deactivate_tt_btn.clicked.connect(self._on_deactivate_test_type)
        tt_btn_row.addWidget(add_tt_btn)
        tt_btn_row.addStretch(1)
        tt_btn_row.addWidget(self.edit_tt_btn)
        tt_btn_row.addWidget(self.deactivate_tt_btn)
        layout.addLayout(tt_btn_row)

        # После создания edit_tt_btn/deactivate_tt_btn — _reload_test_types()
        # дёргает _on_test_type_row_selected(), которая на них ссылается.
        self._reload_test_types()

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

    def _reload_test_types(self) -> None:
        # active_only=False — в справочнике админ должен видеть и деактивированные
        # записи, чтобы их можно было снова включить через «Редактировать».
        self._test_types_rows = repo.list_test_types(self.conn, active_only=False)
        self.test_types_table.setRowCount(len(self._test_types_rows))
        for i, tt in enumerate(self._test_types_rows):
            self.test_types_table.setItem(i, 0, QTableWidgetItem(tt["code"]))
            self.test_types_table.setItem(i, 1, QTableWidgetItem(tt["display_name"]))
            for col, value in (
                (2, str(tt["base_deadline_days"])),
                (3, f"{tt['price']:.2f}"),
                (4, f"{tt['cost_price']:.2f}"),
            ):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.test_types_table.setItem(i, col, item)
            self.test_types_table.setItem(i, 5, QTableWidgetItem("Да" if tt["is_active"] else "—"))
            self.test_types_table.setItem(i, 6, QTableWidgetItem("Да" if tt["requires_lab"] else "Услуга"))
        self._on_test_type_row_selected()

    def _on_test_type_row_selected(self) -> None:
        has_selection = bool(self.test_types_table.selectedItems())
        self.edit_tt_btn.setEnabled(has_selection)
        self.deactivate_tt_btn.setEnabled(has_selection)

    def _selected_test_type_code(self) -> Optional[str]:
        items = self.test_types_table.selectedItems()
        if not items:
            return None
        return self._test_types_rows[items[0].row()]["code"]

    def _on_add_test_type(self) -> None:
        from .test_type_edit_dialog import TestTypeEditDialog
        dlg = TestTypeEditDialog(self.conn, None, self)
        if dlg.exec():
            self._reload_test_types()

    def _on_edit_test_type(self) -> None:
        code = self._selected_test_type_code()
        if code is None:
            return
        from .test_type_edit_dialog import TestTypeEditDialog
        dlg = TestTypeEditDialog(self.conn, code, self)
        if dlg.exec():
            self._reload_test_types()

    def _on_deactivate_test_type(self) -> None:
        code = self._selected_test_type_code()
        if code is None:
            return
        confirm = QMessageBox.question(
            self, "Деактивация",
            f"Деактивировать продукт «{code}»? Он перестанет предлагаться при "
            "создании заказа и в Product Mapping, но останется в истории "
            "существующих заказов — это можно отменить через «Редактировать».",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            repo.deactivate_test_type(self.conn, code)
        except ValueError as exc:
            QMessageBox.warning(self, "Проверка", str(exc))
            return
        self._reload_test_types()

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

        self.token_hint_label = QLineEdit_label(
            "Токен не задан — введите Bot Token для автоприёма заказов из Telegram"
        )
        self.token_edit.textChanged.connect(self._update_token_hint)
        self._update_token_hint()
        layout.addWidget(self.token_hint_label)

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

        layout.addWidget(_section_title("Прокси для Telegram"))
        layout.addWidget(QLineEdit_label(
            "Нужен, только если обычный VPN/прокси компьютера Telegram напрямую не пускает "
            "(например, если прокси настроен ВНУТРИ самого Telegram, а не на уровне Windows) — "
            "тогда впишите сюда те же адрес/порт/логин/пароль, что указаны в настройках прокси "
            "самого Telegram-клиента. Если всё и так работает — оставьте «Без прокси»."
        ))
        proxy_form = QFormLayout()

        self.proxy_kind_combo = QComboBox()
        self.proxy_kind_combo.addItem("Без прокси (системный/VPN)", userData="")
        self.proxy_kind_combo.addItem("HTTP", userData="http")
        self.proxy_kind_combo.addItem("SOCKS5", userData="socks5")
        saved_kind = st.get_setting(self.conn, "telegram_proxy_kind", "") or ""
        idx = self.proxy_kind_combo.findData(saved_kind)
        self.proxy_kind_combo.setCurrentIndex(idx if idx >= 0 else 0)
        proxy_form.addRow("Тип прокси", self.proxy_kind_combo)

        self.proxy_host_edit = QLineEdit(st.get_setting(self.conn, "telegram_proxy_host", "") or "")
        self.proxy_host_edit.setPlaceholderText("напр. 91.108.4.10")
        proxy_form.addRow("Хост", self.proxy_host_edit)

        self.proxy_port_edit = QLineEdit(st.get_setting(self.conn, "telegram_proxy_port", "") or "")
        self.proxy_port_edit.setPlaceholderText("напр. 1080")
        proxy_form.addRow("Порт", self.proxy_port_edit)

        proxy_user, proxy_pass = secrets_store.get_telegram_proxy_credentials()
        self.proxy_username_edit = QLineEdit(proxy_user or "")
        self.proxy_username_edit.setPlaceholderText("если прокси без логина — оставьте пустым")
        proxy_form.addRow("Логин прокси", self.proxy_username_edit)

        self.proxy_password_edit = QLineEdit(proxy_pass or "")
        self.proxy_password_edit.setEchoMode(QLineEdit.Password)
        proxy_form.addRow("Пароль прокси", self.proxy_password_edit)

        layout.addLayout(proxy_form)

        layout.addStretch(1)
        return w

    def _update_token_hint(self) -> None:
        self.token_hint_label.setVisible(not self.token_edit.text().strip())

    def _current_proxy_config(self):
        """Собирает ProxyConfig прямо из полей диалога (ещё не сохранённых) —
        чтобы «Проверить подключение» проверяла именно то, что сейчас введено."""
        from . import telegram_client as tc

        kind = self.proxy_kind_combo.currentData() or ""
        if kind not in ("http", "socks5"):
            return None
        host = self.proxy_host_edit.text().strip()
        port_text = self.proxy_port_edit.text().strip()
        if not host or not port_text:
            return None
        try:
            port = int(port_text)
        except ValueError:
            raise ValueError("Порт прокси должен быть числом.")
        return tc.ProxyConfig(
            kind=kind, host=host, port=port,
            username=self.proxy_username_edit.text().strip() or None,
            password=self.proxy_password_edit.text().strip() or None,
        )

    def _test_telegram_connection(self) -> None:
        token = self.token_edit.text().strip()
        if not token:
            self.test_conn_result.setText("Введите Bot Token перед проверкой.")
            return
        try:
            proxy = self._current_proxy_config()
        except ValueError as exc:
            self.test_conn_result.setText(f"✗ {exc}")
            return
        try:
            from . import telegram_client as tc
            info = tc.get_me(token, proxy=proxy)
            username = info.get("username", "?")
            via = " (через указанный прокси)" if proxy else ""
            self.test_conn_result.setText(f"✓ Подключение успешно{via}: @{username}")
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

        proxy_kind = self.proxy_kind_combo.currentData() or ""
        port_text = self.proxy_port_edit.text().strip()
        if proxy_kind and port_text:
            try:
                int(port_text)
            except ValueError:
                QMessageBox.warning(self, "Проверка", "Порт прокси должен быть числом.")
                return
        st.set_setting(self.conn, "telegram_proxy_kind", proxy_kind)
        st.set_setting(self.conn, "telegram_proxy_host", self.proxy_host_edit.text().strip())
        st.set_setting(self.conn, "telegram_proxy_port", port_text)
        secrets_store.set_telegram_proxy_credentials(
            self.proxy_username_edit.text().strip(), self.proxy_password_edit.text().strip()
        )

        self.accept()


def QLineEdit_label(text: str):
    """Небольшой хелпер: многострочная подпись без создания отдельного импорта QLabel в каждом месте."""
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    return lbl


def _section_title(text: str) -> QLabel:
    """Жирный заголовок секции внутри вкладки диалога настроек."""
    lbl = QLabel(f"<b>{text}</b>")
    return lbl
