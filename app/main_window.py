"""
GENOPOISK CRM — главное окно (v1.0 UX).

Две основные рабочие вкладки:
  - «Клиентская» — отвечает на любой вопрос клиента о заказе;
  - «Внутренняя работа» — операционная панель оператора.

Зафиксировано как эталон в two_tabs_v2.html. Панель действий (тулбар) и
глобальные диалоги (настройки, backup, товары, Telegram) общие для обеих
вкладок.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QToolBar, QStatusBar, QFileDialog,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
)

from . import settings as st
from .client_tab import ClientTabWidget
from .internal_tab import InternalTabWidget
from .new_order_dialog import NewOrderDialog
from .settings_dialog import SettingsDialog
from .backup_dialog import BackupDialog
from .import_dialog import ImportDialog


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setWindowTitle("GENOPOISK CRM")
        self.resize(1400, 800)

        self._build_toolbar()
        self._build_status_bar()
        self._build_tabs()

        self._telegram_thread = None
        self._maybe_start_telegram_polling()

        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._maybe_auto_backup)
        self._backup_timer.start(60_000)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Действия")
        tb.setMovable(False)
        self.addToolBar(tb)

        act_new = QAction("Новый заказ", self)
        act_new.triggered.connect(self.on_new_order)
        tb.addAction(act_new)
        # акцентная кнопка (раздел v1.5 header_filters: .topbtn.primary)
        tb.widgetForAction(act_new).setObjectName("primaryToolButton")

        act_import = QAction("Импорт Excel", self)
        act_import.triggered.connect(self.on_import_excel)
        tb.addAction(act_import)

        act_export = QAction("Экспорт в Excel", self)
        act_export.triggered.connect(self.on_export_excel)
        tb.addAction(act_export)

        act_products = QAction("Товары (Telegram)", self)
        act_products.triggered.connect(self.on_product_mappings)
        tb.addAction(act_products)

        act_backup = QAction("Резервные копии", self)
        act_backup.triggered.connect(self.on_backup)
        tb.addAction(act_backup)

        act_settings = QAction("Настройки", self)
        act_settings.triggered.connect(self.on_settings)
        tb.addAction(act_settings)

    def _build_tabs(self) -> None:
        # Футер строится ДО вкладок: конструктор *TabWidget сразу вызывает
        # refresh(), а тот обращается к self.footer_count_label — иначе
        # AttributeError на первом же refresh() ещё до появления окна.
        footer = self._build_footer_bar()

        self.tabs = QTabWidget()
        self.client_tab = ClientTabWidget(self.conn, self)
        self.internal_tab = InternalTabWidget(self.conn, self)
        self.tabs.addTab(self.client_tab, "Клиентская")
        self.tabs.addTab(self.internal_tab, "Внутренняя работа")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(footer)
        self.setCentralWidget(container)

    def _build_footer_bar(self) -> QWidget:
        """Строка со счётчиком тестов под вкладками (раздел v1.5
        header_filters: .footer). Отдельно от QStatusBar — тот остаётся для
        служебных сообщений (Telegram, backup)."""
        bar = QWidget()
        bar.setObjectName("footerBar")
        bar.setFixedHeight(30)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        self.footer_count_label = QLabel("Тестов в списке: 0")
        lay.addWidget(self.footer_count_label)
        lay.addStretch(1)
        return bar

    def set_footer_count(self, count: int) -> None:
        self.footer_count_label.setText(f"Тестов в списке: {count}")

    def _build_status_bar(self) -> None:
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Готово")

    def _on_tab_changed(self, index: int) -> None:
        # при переключении вкладки данные могли устареть (правки во внутренней
        # вкладке должны быть видны, если тут же переключиться на клиентскую)
        if index == 0:
            self.client_tab.refresh()
        else:
            self.internal_tab.refresh()

    def refresh_all(self) -> None:
        self.client_tab.refresh()
        self.internal_tab.refresh()

    def on_event_saved(self, test_id: int) -> None:
        """
        Единая точка синхронизации после record_event() (баг-репорт
        "Синхронизация вкладок"): обновляет ОБЕ вкладки и карточку сразу,
        без переключения вкладок / повторного поиска / ручного обновления.

            record_event() -> event_saved -> refresh internal tab
                                           -> refresh client tab
                                           -> refresh selected card
                                           -> refresh list row
        """
        self.internal_tab.refresh(keep_selection_test_id=test_id)
        self.client_tab.refresh(keep_selection_test_id=test_id)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def on_new_order(self) -> None:
        dlg = NewOrderDialog(self.conn, self)
        if dlg.exec():
            self.refresh_all()

    def on_import_excel(self) -> None:
        dlg = ImportDialog(self.conn, self)
        dlg.exec()
        self.refresh_all()

    def on_export_excel(self) -> None:
        from . import exporter

        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить экспорт как", "genopoisk_export.xlsx", "Excel файлы (*.xlsx)"
        )
        if not path:
            return
        search = self.internal_tab.search_edit.text().strip() or None
        quick_filter = self.internal_tab.filter_combo.currentData() or "all"
        try:
            count = exporter.export_orders_to_excel(self.conn, path, search=search, quick_filter=quick_filter)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", str(exc))
            return
        QMessageBox.information(self, "Экспорт завершён", f"Выгружено строк: {count}\n{path}")

    def on_product_mappings(self) -> None:
        from .product_mappings_dialog import ProductMappingsDialog
        dlg = ProductMappingsDialog(self.conn, self)
        dlg.exec()

    def on_backup(self) -> None:
        dlg = BackupDialog(self.conn, self)
        dlg.exec()

    def on_settings(self) -> None:
        dlg = SettingsDialog(self.conn, self)
        if dlg.exec():
            self.refresh_all()
            self._maybe_start_telegram_polling()

    # ------------------------------------------------------------------
    # Telegram long-polling
    # ------------------------------------------------------------------

    def _maybe_start_telegram_polling(self) -> None:
        from . import secrets_store
        from .telegram_poller import TelegramPollerThread
        from .db import get_db_path

        enabled = st.get_setting(self.conn, "telegram_polling_enabled", "0") == "1"
        token = secrets_store.get_telegram_bot_token()

        if self._telegram_thread is not None:
            self._telegram_thread.request_stop()
            self._telegram_thread.wait(2000)
            self._telegram_thread = None

        if not enabled or not token:
            return

        self._telegram_thread = TelegramPollerThread(get_db_path(), token, parent=self)
        self._telegram_thread.batch_processed.connect(self._on_telegram_batch)
        self._telegram_thread.error_occurred.connect(self._on_telegram_error)
        self._telegram_thread.start()

    def _on_telegram_batch(self, result) -> None:
        self.refresh_all()
        msg = f"Telegram: получено заказов {result.processed} (новых {result.new_orders}"
        if result.needs_review:
            msg += f", требуют проверки {result.needs_review}"
        msg += ")"
        self.statusBar().showMessage(msg, 8000)

    def _on_telegram_error(self, error_text: str) -> None:
        self.statusBar().showMessage(f"Telegram: ошибка приёма — {error_text}", 8000)

    def closeEvent(self, event) -> None:
        if self._telegram_thread is not None:
            self._telegram_thread.request_stop()
            self._telegram_thread.wait(2000)
        super().closeEvent(event)

    def _maybe_auto_backup(self) -> None:
        from . import backup as bk
        from pathlib import Path
        from .db import get_db_path

        folder = st.get_setting(self.conn, "backup_folder", "")
        if not folder:
            return
        last = st.get_setting(self.conn, "last_auto_backup_date", "")
        today_str = date.today().isoformat()
        if last == today_str:
            return
        try:
            bk.create_backup(get_db_path(), Path(folder))
            keep = st.get_int_setting(self.conn, "backup_keep_count", 30)
            bk.prune_old_backups(Path(folder), keep)
            st.set_setting(self.conn, "last_auto_backup_date", today_str)
            self.statusBar().showMessage("Автоматическая резервная копия создана", 5000)
        except OSError as exc:
            self.statusBar().showMessage(f"Ошибка автоматического backup: {exc}", 8000)
