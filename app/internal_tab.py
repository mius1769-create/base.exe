"""
GENOPOISK CRM — вкладка «Внутренняя работа» (v1.0 UX).

Полный операционный вид: логистика, лаборатория, оператор, внутренние
комментарии, журнал событий с быстрыми действиями, история изменений.
Зафиксировано как эталон в two_tabs_v2.html.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QPushButton, QLabel, QHeaderView,
    QAbstractItemView, QFrame, QSplitter, QGridLayout, QSizePolicy,
)

from . import business_logic as bl
from . import repository as repo
from . import settings as st
from . import product_catalog as pcat

URGENCY_COLOR_MAP = {
    bl.RowColor.GREEN: QColor("#d7f5d7"),
    bl.RowColor.RED: QColor("#f8d0d0"),
    bl.RowColor.PURPLE: QColor("#e6d0f5"),
    bl.RowColor.YELLOW: QColor("#faf3c0"),
    bl.RowColor.NORMAL: QColor("#ffffff"),
}

QUICK_FILTERS = [
    ("all", "Все"),
    ("in_progress", "В работе"),
    ("profile_received", "Профиль получен"),
    ("in_lab", "В лаборатории"),
    ("urgent", "Срочные"),
    ("overdue", "Просроченные"),
    ("issued", "Выданные"),
]

COLUMNS = [
    ("gns_number", "GNS"),
    ("order_no", "№ заказа"),
    ("customer_name", "ФИО"),
    ("test_type", "Тип теста"),
    ("internal_status", "Статус"),
    ("deadline_date", "Дедлайн"),
]


def fmt_date(value: Optional[str]) -> str:
    if not value:
        return ""
    d = repo.parse_iso_date(value)
    return d.strftime("%d.%m.%Y") if d else value


def fmt_dt(value: Optional[str]) -> str:
    if not value:
        return ""
    dt = repo.parse_iso_dt(value)
    return dt.strftime("%d.%m.%Y %H:%M") if dt else value


class InternalTabWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по GNS, № заказа, ФИО, телефону/email, типу теста…")
        self.search_edit.textChanged.connect(self.refresh)
        search_row.addWidget(self.search_edit, stretch=2)

        self.filter_combo = QComboBox()
        for code, label in QUICK_FILTERS:
            self.filter_combo.addItem(label, userData=code)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        search_row.addWidget(self.filter_combo, stretch=1)
        root.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        self.card = InternalCardWidget(self)
        splitter.addWidget(self.card)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)  # карточка ~30% ширины (раздел 5 ТЗ)

        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------
    def refresh(self, *, keep_selection_test_id: Optional[int] = None) -> None:
        search = self.search_edit.text().strip() or None
        quick_filter = self.filter_combo.currentData() or "all"
        rows = repo.list_tests_with_order(self.conn, search=search, quick_filter=quick_filter)
        self._rows_cache = rows

        test_ids = [r["test_id"] for r in rows]
        events_by_test = repo.list_events_for_test_ids(self.conn, test_ids)
        soon_days = st.get_int_setting(self.conn, "deadline_soon_threshold_days", 5)

        self.table.setRowCount(len(rows))
        select_row_idx = None
        for i, row in enumerate(rows):
            urgency = bl.calculate_row_color(
                client_issued_at=repo.parse_iso_dt(row["client_issued_at"]),
                deadline_date=repo.parse_iso_date(row["deadline_date"]),
                operator_started_at=repo.parse_iso_dt(row["operator_started_at"]),
                soon_threshold_days=soon_days,
            )
            events = events_by_test.get(row["test_id"], [])
            internal_status = bl.internal_status_label(events)

            for col_i, (field_name, _label) in enumerate(COLUMNS):
                if field_name == "internal_status":
                    text = internal_status
                elif field_name == "deadline_date":
                    text = fmt_date(row["deadline_date"])
                elif field_name == "test_type":
                    text = pcat.get_display_name(row["test_type"])
                else:
                    text = str(row[field_name] or "")
                item = QTableWidgetItem(text)
                item.setBackground(URGENCY_COLOR_MAP[urgency])
                if field_name == "test_type":
                    type_hex = pcat.get_color(row["test_type"])
                    if type_hex:
                        item.setBackground(QColor(type_hex))
                        item.setForeground(QColor("#14151a"))
                if field_name == "gns_number":
                    item.setData(Qt.UserRole, row["test_id"])
                self.table.setItem(i, col_i, item)

            if keep_selection_test_id is not None and row["test_id"] == keep_selection_test_id:
                select_row_idx = i

        self.main_window.statusBar().showMessage(f"Тестов в списке: {len(rows)}")

        if select_row_idx is not None:
            # ВАЖНО: если выбранная строка не меняет индекс (напр. единственная
            # строка в списке, или клик по уже выбранной), Qt не переотправляет
            # itemSelectionChanged — карточка тогда НЕ обновилась бы сама,
            # несмотря на то, что данные в БД уже новые. Обновляем карточку
            # напрямую, не полагаясь только на сигнал выбора (найденный баг:
            # событие писалось в БД, но карточка оставалась старой).
            self.table.selectRow(select_row_idx)
            self.card.show_test(keep_selection_test_id)
        else:
            self.card.clear()

    def select_test(self, test_id: int) -> None:
        """Переключить карточку на конкретный тест (используется, когда
        оператор кликает по тесту-«соседу» в блоке заказа)."""
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item and item.data(Qt.UserRole) == test_id:
                self.table.selectRow(i)
                self.card.show_test(test_id)  # та же причина — сигнал может не сработать
                return
        # тест не попадает под текущий фильтр/поиск — просто открываем карточку напрямую
        self.card.show_test(test_id)

    def _on_row_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.card.clear()
            return
        row_idx = items[0].row()
        test_id = self.table.item(row_idx, 0).data(Qt.UserRole)
        self.card.show_test(test_id)


class InternalCardWidget(QFrame):
    def __init__(self, tab: InternalTabWidget):
        super().__init__()
        self.tab = tab
        self.conn = tab.conn
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("cardPanel")
        self._test_id: Optional[int] = None
        self._order_id: Optional[int] = None
        self._action_in_flight = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.header_label = QLabel("Выберите тест в списке слева")
        self.header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.header_label)

        self.deadline_label = QLabel("")
        layout.addWidget(self.deadline_label)

        self.sibling_box = QLabel("")
        self.sibling_box.setWordWrap(True)
        self.sibling_box.setStyleSheet("background: #f7f7f9; border: 1px solid #e4e5eb; border-radius: 6px; padding: 6px;")
        self.sibling_box.setVisible(False)
        layout.addWidget(self.sibling_box)

        self.client_block = QLabel("")
        self.client_block.setWordWrap(True)
        layout.addWidget(self.client_block)

        self.route_block = QLabel("")
        self.route_block.setWordWrap(True)
        layout.addWidget(self.route_block)

        self.actions_grid = QGridLayout()
        layout.addLayout(self.actions_grid)
        self._action_buttons: list[QPushButton] = []

        self.comment_block = QLabel("")
        self.comment_block.setWordWrap(True)
        layout.addWidget(self.comment_block)

        layout.addStretch(1)

        self.edit_button = QPushButton("Редактировать")
        self.edit_button.clicked.connect(self._on_edit_clicked)
        self.edit_button.setEnabled(False)
        layout.addWidget(self.edit_button)

        self.history_button = QPushButton("История изменений")
        self.history_button.clicked.connect(self._on_history_clicked)
        self.history_button.setEnabled(False)
        layout.addWidget(self.history_button)

    def clear(self) -> None:
        self._test_id = None
        self._order_id = None
        self.header_label.setText("Выберите тест в списке слева")
        self.deadline_label.setText("")
        self.sibling_box.setVisible(False)
        self.client_block.setText("")
        self.route_block.setText("")
        self.comment_block.setText("")
        self.edit_button.setEnabled(False)
        self.history_button.setEnabled(False)
        self._clear_action_buttons()

    def _clear_action_buttons(self) -> None:
        while self.actions_grid.count():
            item = self.actions_grid.takeAt(0)
            w = item.widget()
            if w:
                w.hide()  # немедленно скрыть, не дожидаясь фактического deleteLater()
                w.deleteLater()
        self._action_buttons = []

    def show_test(self, test_id: int) -> None:
        conn = self.conn
        row = conn.execute(
            """SELECT t.*, o.order_no, o.customer_name, o.contacts, o.delivery_method,
                      o.tracking_number, o.order_status, o.order_id
               FROM tests t JOIN orders o ON o.order_id = t.order_id
               WHERE t.test_id = ?""",
            (test_id,),
        ).fetchone()
        if row is None:
            self.clear()
            return

        self._test_id = test_id
        self._order_id = row["order_id"]
        self.edit_button.setEnabled(True)
        self.history_button.setEnabled(True)

        events = repo.list_events_for_test(conn, test_id)
        internal_status = bl.internal_status_label(events)
        operator_tag = f" · {row['operator_name']}" if row["operator_name"] else ""

        self.header_label.setText(
            f"{row['gns_number']}{operator_tag} · {internal_status}"
        )

        if row["client_issued_at"]:
            self.deadline_label.setText("Завершено")
        else:
            dl = repo.parse_iso_date(row["deadline_date"])
            if dl:
                days_left = (dl - date.today()).days
                if days_left < 0:
                    self.deadline_label.setText(f"Просрочено на {-days_left} дн.")
                else:
                    self.deadline_label.setText(f"До дедлайна {days_left} дн.")
            else:
                self.deadline_label.setText("Дедлайн не рассчитан (нет события «Образец получен»)")

        # --- блок «остальные тесты этого заказа» ---
        siblings = repo.list_sibling_tests_for_order(conn, row["order_id"])
        if len(siblings) > 1:
            sib_events = repo.list_events_for_test_ids(conn, [s["test_id"] for s in siblings])
            lines = [f"<b>Заказ #{row['order_no'] or row['order_id']} · {len(siblings)} теста(ов)</b>"]
            for s in siblings:
                marker = "▶" if s["test_id"] == test_id else "•"
                s_status = bl.internal_status_label(sib_events.get(s["test_id"], []))
                lines.append(f"{marker} {pcat.get_display_name(s['test_type'])} — {s['gns_number']} — {s_status}")
            self.sibling_box.setText("<br>".join(lines))
            self.sibling_box.setVisible(True)
        else:
            self.sibling_box.setVisible(False)

        self.client_block.setText(
            f"<b>Клиент:</b> {row['customer_name']}<br>"
            f"Контакты: {row['contacts'] or '—'}<br>"
            f"№ заказа: {row['order_no'] or '—'}<br>"
            f"Доставка: {row['delivery_method'] or '—'} / {row['tracking_number'] or '—'}"
        )

        # --- маршрут: полный журнал событий ---
        route_lines = ["<b>Внутренние события:</b>"]
        for ev in events:
            label = bl.EVENT_LABELS_INTERNAL.get(ev["event_type"], ev["event_type"])
            mark = " (вручную скорректировано)" if ev["is_manual_correction"] else ""
            route_lines.append(f"✓ {label} — {fmt_dt(ev['event_time'])}{mark}")
        if bl.is_awaiting_receipt(events):
            route_lines.append("○ <i>Ожидаем получение — автоматически, до подтверждения</i>")
        next_et = bl.next_action_event_type(events)
        if next_et and not bl.is_awaiting_receipt(events):
            route_lines.append(f"○ {bl.EVENT_LABELS_INTERNAL[next_et]} — ещё не зафиксировано")
        self.route_block.setText("<br>".join(route_lines))

        # --- быстрые действия ---
        self._build_action_buttons(events)

        self.comment_block.setText(f"<i>{row['comments'] or ''}</i>")

        # Пересборка QGridLayout с быстрыми действиями в рантайме (после
        # record_event) может сбить пересчёт геометрии родительского
        # QVBoxLayout в headless/Xvfb-рендере — верхние лейблы визуально
        # "пропадают", хотя их текст на самом деле корректно установлен.
        # Форсируем полную инвалидацию и пересчёт layout.
        self.layout().invalidate()
        self.layout().activate()
        self.updateGeometry()
        self.update()

    def _build_action_buttons(self, events) -> None:
        self._clear_action_buttons()
        present = {e["event_type"] for e in events}
        next_et = bl.next_action_event_type(events)

        col = 0
        row_idx = 0
        for et in bl.EVENT_ORDER:
            if et == "order_created":
                continue  # уже произошло при создании, кнопка не нужна
            btn = QPushButton()
            btn.setMinimumHeight(32)
            if et in present:
                btn.setText(f"✓ {bl.EVENT_LABELS_INTERNAL[et]}")
                btn.setEnabled(False)
                btn.setStyleSheet("color: #4b4d57;")
            elif et == next_et:
                btn.setText(bl.ACTION_BUTTON_LABELS[et])
                btn.setStyleSheet(
                    "background-color: #4f46e5; color: white; font-weight: 600; "
                    "border: none; border-radius: 7px; padding: 8px 10px;"
                )
                btn.clicked.connect(lambda checked=False, e=et, b=btn: self._on_quick_action(e, b))
            else:
                btn.setText(bl.ACTION_BUTTON_LABELS[et])
                btn.setEnabled(False)
            self.actions_grid.addWidget(btn, row_idx, col)
            self._action_buttons.append(btn)
            col += 1
            if col >= 2:
                col = 0
                row_idx += 1

    def _on_quick_action(self, event_type: str, button: QPushButton) -> None:
        """
        Баг-репорт "Повторное нажатие кнопки" — защита на уровне UI:
        кнопка немедленно блокируется и показывает 'Сохраняем...' СРАЗУ по
        клику, до обращения к БД, так что даже очень быстрый второй клик
        физически не попадает на уже отключённую кнопку. Вторая линия
        защиты (идемпотентность record_event() + UNIQUE-индекс в БД)
        подстраховывает на случай гонки на уровне самого Qt/ОС.
        """
        if self._test_id is None or self._action_in_flight:
            return
        self._action_in_flight = True
        button.setEnabled(False)
        button.setText("Сохраняем…")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()  # немедленно перерисовать кнопку до записи в БД

        try:
            operator = st.get_setting(self.conn, "current_operator_name", "") or "оператор"
            repo.record_event(self.conn, self._test_id, event_type, operator=operator, user_name=operator)
            # единая точка синхронизации: обновляет обе вкладки + карточку + строку списка
            self.tab.main_window.on_event_saved(self._test_id)
        finally:
            self._action_in_flight = False

    def _on_edit_clicked(self) -> None:
        if self._test_id is None:
            return
        from .edit_dialog import TestEditDialog
        dlg = TestEditDialog(self.conn, self._test_id, self.tab.main_window)
        if dlg.exec():
            self.tab.refresh(keep_selection_test_id=self._test_id)

    def _on_history_clicked(self) -> None:
        if self._order_id is None:
            return
        from .audit_history_dialog import OrderAuditHistoryDialog
        dlg = OrderAuditHistoryDialog(self.conn, self._order_id, self.tab.main_window)
        dlg.exec()
