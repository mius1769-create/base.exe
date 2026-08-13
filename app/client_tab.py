"""
GENOPOISK CRM — вкладка «Клиентская» (v1.5 UX, header_filters).

Отвечает на любой вопрос клиента о заказе: клиентский статус, доставка,
подтверждённые этапы, ориентировочный срок. НЕ показывает лабораторию,
оператора и внутренние комментарии (раздел ТЗ). Визуально перенесено из
docs/GENOPOISK_CRM_UX_v1_5_header_filters.html. Бизнес-логика, repository.py
и test_events не менялись — вкладка только читает готовые данные.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidget,
    QLineEdit, QComboBox, QHeaderView, QAbstractItemView, QFrame,
    QSplitter, QLabel, QScrollArea,
)

from . import business_logic as bl
from . import repository as repo
from . import product_catalog as pcat
from . import ui_kit
from .internal_tab import QUICK_FILTERS, fmt_date, _info_box, _section_title, _field_row

# Упрощённый клиентский маршрут — 4 стабильные вехи (детали лаборатории/
# внутренние этапы сворачиваются в "В обработке", см. bl.EVENT_LABELS_CLIENT).
CLIENT_TIMELINE_STEPS = [
    ("order_created", "Заказ оформлен"),
    ("received", "Образец получен"),
    ("in_progress", "В обработке"),
    ("issued", "Выдан клиенту"),
]

# (ключ фильтра в шапке, заголовок колонки, режим "поиск"/"опции"/None=без фильтра)
HEADER_COLUMNS = [
    ("rank", "№", None),
    ("gns_number", "Номер теста", "search"),
    ("customer_name", "ФИО клиента", "search"),
    ("test_type", "Тип теста", "options"),
    ("client_status", "Статус клиенту", "options"),
    ("deadline_date", "Дедлайн", "options"),
]


class ClientTabWidget(QWidget, ui_kit.HeaderFilterMixin):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        keys = [key for key, _label, mode in HEADER_COLUMNS if mode is not None]
        self.init_header_filters(keys)
        self._type_options: list[tuple[str, str]] = [("", "Все")]
        self._status_options: list[tuple[str, str]] = [("", "Все")]
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск: номер теста, ФИО, телефон…")
        self.search_edit.textChanged.connect(self.refresh)
        search_row.addWidget(self.search_edit, stretch=2)

        self.filter_combo = QComboBox()
        for code, label in QUICK_FILTERS:
            self.filter_combo.addItem(label, userData=code)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        search_row.addWidget(self.filter_combo, stretch=1)
        root.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)

        self.table = QTableWidget(0, len(HEADER_COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _k, label, _m in HEADER_COLUMNS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 36)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        self.card = ClientCardWidget(self)
        splitter.addWidget(self.card)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)  # карточка ~30% ширины (раздел 5 ТЗ)

        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------
    # Фильтры в шапке таблицы (раздел v1.5 header_filters). Колонка "№" —
    # чисто порядковая, без фильтра (см. HTML-эталон: клик по ней не
    # привязан ни к одному реальному фильтру).
    # ------------------------------------------------------------------
    def _on_header_clicked(self, index: int) -> None:
        key, title, mode = HEADER_COLUMNS[index]
        if mode is None:
            return
        if mode == "search":
            self.open_header_filter(key, title, index, searchable=True)
        elif key == "test_type":
            self.open_header_filter(key, title, index, options=self._type_options)
        elif key == "client_status":
            self.open_header_filter(key, title, index, options=self._status_options)
        elif key == "deadline_date":
            self.open_header_filter(key, title, index, options=ui_kit.DEADLINE_BUCKET_OPTIONS)

    def _refresh_header_labels(self) -> None:
        labels = []
        for key, label, mode in HEADER_COLUMNS:
            if mode is None:
                labels.append(label)
                continue
            marker = " ●" if self.header_filter_active(key) else ""
            labels.append(f"{label} ▾{marker}")
        self.table.setHorizontalHeaderLabels(labels)

    def _apply_header_filters(self, enriched: list[dict], today: date) -> list[dict]:
        hf = self._header_filter_values
        out = enriched
        if hf.get("gns_number"):
            needle = hf["gns_number"].lower()
            out = [e for e in out if needle in (e["row"]["gns_number"] or "").lower()]
        if hf.get("customer_name"):
            needle = hf["customer_name"].lower()
            out = [e for e in out if needle in (e["row"]["customer_name"] or "").lower()]
        if hf.get("test_type"):
            out = [e for e in out if e["row"]["test_type"] == hf["test_type"]]
        if hf.get("client_status"):
            out = [e for e in out if e["status_label"] == hf["client_status"]]
        if hf.get("deadline_date"):
            bucket = hf["deadline_date"]
            out = [e for e in out if ui_kit.deadline_bucket(e["deadline_date"], today) == bucket]
        return out

    # ------------------------------------------------------------------
    def refresh(self, *, keep_selection_test_id: Optional[int] = None) -> None:
        search = self.search_edit.text().strip() or None
        quick_filter = self.filter_combo.currentData() or "all"
        rows = repo.list_tests_with_order(
            self.conn, search=search, quick_filter=quick_filter, include_archived=False
        )

        test_ids = [r["test_id"] for r in rows]
        events_by_test = repo.list_events_for_test_ids(self.conn, test_ids)
        today = date.today()

        enriched = []
        for row in rows:
            events = events_by_test.get(row["test_id"], [])
            urgency = bl.calculate_row_color(
                client_issued_at=repo.parse_iso_dt(row["client_issued_at"]),
                deadline_date=repo.parse_iso_date(row["deadline_date"]),
                operator_started_at=repo.parse_iso_dt(row["operator_started_at"]),
                today=today,
            )
            enriched.append({
                "row": row,
                "urgency": urgency,
                "status_label": bl.client_status_label(events),
                "deadline_date": repo.parse_iso_date(row["deadline_date"]),
            })

        type_pairs = {(e["row"]["test_type"], pcat.get_display_name(e["row"]["test_type"])) for e in enriched}
        self._type_options = [("", "Все")] + sorted(type_pairs, key=lambda p: p[1])
        status_values = sorted({e["status_label"] for e in enriched})
        self._status_options = [("", "Все")] + [(s, s) for s in status_values]

        filtered = self._apply_header_filters(enriched, today)
        self._rows_cache = [e["row"] for e in filtered]

        self._refresh_header_labels()
        self.table.setRowCount(len(filtered))
        select_row_idx = None
        for i, e in enumerate(filtered):
            row = e["row"]
            rank_item = ui_kit.make_table_item(str(i + 1))
            rank_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, rank_item)

            gns_item = ui_kit.make_table_item(row["gns_number"] or "")
            gns_item.setData(Qt.UserRole, row["test_id"])
            self.table.setItem(i, 1, gns_item)
            self.table.setItem(i, 2, ui_kit.make_table_item(row["customer_name"] or ""))

            self.table.setCellWidget(i, 3, ui_kit.make_type_badge(
                pcat.get_display_name(row["test_type"]), pcat.get_color(row["test_type"])
            ))
            self.table.setCellWidget(i, 4, ui_kit.make_status_chip(e["status_label"]))

            self.table.setCellWidget(i, 5, ui_kit.make_deadline_cell(
                fmt_date(row["deadline_date"]) or "—", ui_kit.deadline_text_color(e["urgency"])
            ))

            if keep_selection_test_id is not None and row["test_id"] == keep_selection_test_id:
                select_row_idx = i

        self.main_window.set_footer_count(len(filtered))

        if select_row_idx is not None:
            self.table.selectRow(select_row_idx)
            self.card.show_test(keep_selection_test_id)  # см. internal_tab.py: сигнал может не сработать
        else:
            self.card.clear()

    def _on_row_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.card.clear()
            return
        row_idx = items[0].row()
        gns_item = self.table.item(row_idx, 1)
        if gns_item is None:
            return
        test_id = gns_item.data(Qt.UserRole)
        self.card.show_test(test_id)


class ClientCardWidget(QFrame):
    def __init__(self, tab: ClientTabWidget):
        super().__init__()
        self.tab = tab
        self.conn = tab.conn
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("cardPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.badge_slot = QHBoxLayout()
        head_row.addLayout(self.badge_slot)
        self.header_label = QLabel("Выберите тест в списке слева")
        self.header_label.setObjectName("cardTitle")
        head_row.addWidget(self.header_label, stretch=1)
        layout.addLayout(head_row)

        self.sub_label = QLabel("Клиентская карточка")
        self.sub_label.setObjectName("cardSub")
        layout.addWidget(self.sub_label)

        self.status_pill = QLabel("")
        self.status_pill.setObjectName("cardStatusPill")
        self.status_pill.setVisible(False)
        pill_row = QHBoxLayout()
        pill_row.addWidget(self.status_pill)
        pill_row.addStretch(1)
        layout.addLayout(pill_row)

        two_col = QHBoxLayout()
        two_col.setSpacing(10)
        self.deadline_box = _info_box()
        dl_lay = QVBoxLayout(self.deadline_box)
        dl_lay.setContentsMargins(12, 10, 12, 10)
        dl_lay.addWidget(_section_title("Дедлайн"))
        self.deadline_big = QLabel("")
        self.deadline_big.setStyleSheet("font-size:18px; font-weight:600; background:transparent; border:none;")
        dl_lay.addWidget(self.deadline_big)
        self.deadline_note = QLabel("")
        self.deadline_note.setStyleSheet("color:#7a8498; font-size:11px; background:transparent; border:none;")
        self.deadline_note.setWordWrap(True)
        dl_lay.addWidget(self.deadline_note)
        two_col.addWidget(self.deadline_box, stretch=6)

        self.client_box = _info_box()
        cl_lay = QVBoxLayout(self.client_box)
        cl_lay.setContentsMargins(12, 10, 12, 10)
        cl_lay.addWidget(_section_title("Клиент"))
        self.client_text = QLabel("")
        self.client_text.setWordWrap(True)
        self.client_text.setStyleSheet("background:transparent; border:none;")
        cl_lay.addWidget(self.client_text)
        two_col.addWidget(self.client_box, stretch=5)
        layout.addLayout(two_col)

        # --- заказ · управление (просмотр — клиентская вкладка не редактирует) ---
        layout.addWidget(_section_title("Заказ · управление"))
        self.order_box = _info_box()
        from PySide6.QtWidgets import QGridLayout
        self.order_fields_grid = QGridLayout(self.order_box)
        self.order_fields_grid.setContentsMargins(12, 10, 12, 10)
        self.order_fields_grid.setSpacing(8)
        layout.addWidget(self.order_box)

        # --- заказ · связанные тесты ---
        self.siblings_title = _section_title("Заказ · связанные тесты")
        layout.addWidget(self.siblings_title)
        self.sibling_box = _info_box()
        self.sibling_layout = QVBoxLayout(self.sibling_box)
        self.sibling_layout.setContentsMargins(12, 10, 12, 10)
        self.sibling_layout.setSpacing(6)
        self.sibling_box.setVisible(False)
        self.siblings_title.setVisible(False)
        layout.addWidget(self.sibling_box)

        # --- статус выполнения (упрощённый клиентский чек-лист) ---
        layout.addWidget(_section_title("Статус выполнения"))
        self.timeline_box = _info_box()
        self.timeline_layout = QVBoxLayout(self.timeline_box)
        self.timeline_layout.setContentsMargins(12, 10, 12, 10)
        self.timeline_layout.setSpacing(5)
        layout.addWidget(self.timeline_box)

        layout.addStretch(1)

    def clear(self) -> None:
        self._clear_layout(self.badge_slot)
        self.header_label.setText("Выберите тест в списке слева")
        self.status_pill.setVisible(False)
        self.deadline_big.setText("")
        self.deadline_note.setText("")
        self.client_text.setText("")
        self._clear_grid(self.order_fields_grid)
        self.sibling_box.setVisible(False)
        self.siblings_title.setVisible(False)
        self._clear_layout(self.sibling_layout)
        self._clear_layout(self.timeline_layout)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

    @staticmethod
    def _clear_grid(grid) -> None:
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

    def show_test(self, test_id: int) -> None:
        conn = self.conn
        row = conn.execute(
            """SELECT t.*, o.order_no, o.customer_name, o.contacts, o.delivery_method,
                      o.delivery_address, o.tracking_number, o.order_status,
                      o.created_at AS order_created_at, o.order_id
               FROM tests t JOIN orders o ON o.order_id = t.order_id
               WHERE t.test_id = ?""",
            (test_id,),
        ).fetchone()
        if row is None:
            self.clear()
            return

        events = repo.list_events_for_test(conn, test_id)
        client_status = bl.client_status_label(events)

        self._clear_layout(self.badge_slot)
        self.badge_slot.addWidget(ui_kit.make_type_badge(
            pcat.get_display_name(row["test_type"]), pcat.get_color(row["test_type"])
        ))
        self.header_label.setText(row["gns_number"])
        self.status_pill.setText(client_status)
        self.status_pill.setVisible(True)

        deadline_text = "уточняется"
        dl = repo.parse_iso_date(row["deadline_date"])
        if dl:
            deadline_text = dl.strftime("%d.%m.%Y")
        self.deadline_big.setText(deadline_text)
        self.deadline_note.setText(
            "Ориентировочный срок готовности" if dl else "Рассчитается после получения образца"
        )

        self.client_text.setText(
            f"<b>{row['customer_name']}</b><br>"
            f"Контакты: {row['contacts'] or '—'}<br>"
            f"№ заказа: {row['order_no'] or '—'}"
        )

        self._clear_grid(self.order_fields_grid)
        self.order_fields_grid.addWidget(_field_row("Статус заказа", row["order_status"] or "—"), 0, 0)
        self.order_fields_grid.addWidget(_field_row("Доставка", row["delivery_method"] or "—"), 0, 1)
        self.order_fields_grid.addWidget(_field_row("№ отправления", row["tracking_number"] or "—"), 1, 0)
        self.order_fields_grid.addWidget(_field_row("Дата заказа", fmt_date(row["order_created_at"]) or "—"), 1, 1)
        self.order_fields_grid.addWidget(
            _field_row("Адрес доставки", row["delivery_address"] or "—"), 2, 0, 1, 2
        )

        self._clear_layout(self.sibling_layout)
        siblings = repo.list_sibling_tests_for_order(conn, row["order_id"])
        if len(siblings) > 1:
            sib_events = repo.list_events_for_test_ids(conn, [s["test_id"] for s in siblings])
            header = QLabel(f"<b>Заказ #{row['order_no'] or row['order_id']} · {len(siblings)} теста(ов)</b>")
            header.setStyleSheet("background:transparent; border:none;")
            self.sibling_layout.addWidget(header)
            for s in siblings:
                s_status = bl.client_status_label(sib_events.get(s["test_id"], []))
                marker = "▶ " if s["test_id"] == test_id else ""
                text = f"{marker}{pcat.get_display_name(s['test_type'])} — {s['gns_number']} — {s_status}"
                dot_hex = pcat.get_color(s["test_type"]) or "#a8b0bd"
                self.sibling_layout.addWidget(ui_kit.make_dot_line(dot_hex, text))
            self.sibling_box.setVisible(True)
            self.siblings_title.setVisible(True)
        else:
            self.sibling_box.setVisible(False)
            self.siblings_title.setVisible(False)

        present = {e["event_type"] for e in events}
        stage = bl.derive_current_stage(events)
        rank = {et: i for i, et in enumerate(bl.EVENT_ORDER)}
        current_rank = rank.get(stage, -1) if stage else -1
        awaiting = bl.is_awaiting_receipt(events)

        self._clear_layout(self.timeline_layout)
        for et, label in CLIENT_TIMELINE_STEPS:
            target_rank = rank[et]
            if et == "received" and awaiting:
                mark = "○"
            elif current_rank >= target_rank:
                mark = "✓"
            else:
                mark = "○"
            line = QLabel(f"{mark}  {label}")
            line.setStyleSheet("background:transparent; border:none;")
            self.timeline_layout.addWidget(line)
