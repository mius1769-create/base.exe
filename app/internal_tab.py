"""
GENOPOISK CRM — вкладка «Внутренняя работа» (v1.5 UX, header_filters).

Полный операционный вид: логистика, лаборатория, оператор, внутренние
комментарии, журнал событий с быстрыми действиями, история изменений.
Визуально перенесено из docs/GENOPOISK_CRM_UX_v1_5_header_filters.html —
колонка-индикатор срочности, бейджи типов, чипы статусов, фильтры в шапке
таблицы, визуальный таймлайн маршрута. Бизнес-логика, repository.py и
test_events НЕ менялись — эта вкладка только читает готовые данные.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QPushButton, QLabel, QHeaderView,
    QAbstractItemView, QFrame, QSplitter, QGridLayout, QScrollArea,
)

from . import business_logic as bl
from . import repository as repo
from . import settings as st
from . import product_catalog as pcat
from . import ui_kit

# Значения совпадают с ключами repository.QUICK_FILTERS — репозиторий не
# менялся, здесь только текстовые подписи для выпадающего списка.
QUICK_FILTERS = [
    ("all", "Все"),
    ("in_progress", "В работе"),
    ("profile_received", "Профиль получен"),
    ("in_lab", "В лаборатории"),
    ("urgent", "Срочные"),
    ("overdue", "Просроченные"),
    ("issued", "Выданные"),
]

# (ключ фильтра в шапке, заголовок колонки, режим "поиск"/"опции")
HEADER_COLUMNS = [
    ("urgency", "•", "options"),
    ("gns_number", "GNS", "search"),
    ("order_no", "№ заказа", "search"),
    ("customer_name", "ФИО", "search"),
    ("test_type", "Тип теста", "options"),
    ("internal_status", "Статус", "options"),
    ("deadline_date", "Дедлайн", "options"),
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


class InternalTabWidget(QWidget, ui_kit.HeaderFilterMixin):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        self.init_header_filters([key for key, _label, _mode in HEADER_COLUMNS])
        self._type_options: list[tuple[str, str]] = [("", "Все")]
        self._status_options: list[tuple[str, str]] = [("", "Все")]
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

        self.table = QTableWidget(0, len(HEADER_COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _k, label, _m in HEADER_COLUMNS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 32)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        self.card = InternalCardWidget(self)
        splitter.addWidget(self.card)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)  # карточка ~30% ширины (раздел 5 ТЗ)

        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------
    # Фильтры в шапке таблицы (раздел v1.5 header_filters)
    # ------------------------------------------------------------------
    def _on_header_clicked(self, index: int) -> None:
        key, title, mode = HEADER_COLUMNS[index]
        if mode == "search":
            self.open_header_filter(key, title, index, searchable=True)
        elif key == "urgency":
            self.open_header_filter(key, title, index, options=ui_kit.URGENCY_FILTER_OPTIONS)
        elif key == "test_type":
            self.open_header_filter(key, title, index, options=self._type_options)
        elif key == "internal_status":
            self.open_header_filter(key, title, index, options=self._status_options)
        elif key == "deadline_date":
            self.open_header_filter(key, title, index, options=ui_kit.DEADLINE_BUCKET_OPTIONS)

    def _refresh_header_labels(self) -> None:
        labels = []
        for key, label, _mode in HEADER_COLUMNS:
            marker = " ●" if self.header_filter_active(key) else ""
            labels.append(f"{label} ▾{marker}" if key != "urgency" else f"{label}{marker} ▾")
        self.table.setHorizontalHeaderLabels(labels)

    def _apply_header_filters(self, enriched: list[dict], today: date) -> list[dict]:
        hf = self._header_filter_values
        out = enriched
        if hf.get("urgency"):
            out = [e for e in out if e["urgency"].value == hf["urgency"]]
        if hf.get("gns_number"):
            needle = hf["gns_number"].lower()
            out = [e for e in out if needle in (e["row"]["gns_number"] or "").lower()]
        if hf.get("order_no"):
            needle = hf["order_no"].lower()
            out = [e for e in out if needle in (e["row"]["order_no"] or "").lower()]
        if hf.get("customer_name"):
            needle = hf["customer_name"].lower()
            out = [e for e in out if needle in (e["row"]["customer_name"] or "").lower()]
        if hf.get("test_type"):
            out = [e for e in out if e["row"]["test_type"] == hf["test_type"]]
        if hf.get("internal_status"):
            out = [e for e in out if e["status_label"] == hf["internal_status"]]
        if hf.get("deadline_date"):
            bucket = hf["deadline_date"]
            out = [e for e in out if ui_kit.deadline_bucket(e["deadline_date"], today) == bucket]
        return out

    # ------------------------------------------------------------------
    def refresh(self, *, keep_selection_test_id: Optional[int] = None) -> None:
        search = self.search_edit.text().strip() or None
        quick_filter = self.filter_combo.currentData() or "all"
        rows = repo.list_tests_with_order(self.conn, search=search, quick_filter=quick_filter)

        test_ids = [r["test_id"] for r in rows]
        events_by_test = repo.list_events_for_test_ids(self.conn, test_ids)
        soon_days = st.get_int_setting(self.conn, "deadline_soon_threshold_days", 5)
        today = date.today()

        enriched = []
        for row in rows:
            events = events_by_test.get(row["test_id"], [])
            urgency = bl.calculate_row_color(
                client_issued_at=repo.parse_iso_dt(row["client_issued_at"]),
                deadline_date=repo.parse_iso_date(row["deadline_date"]),
                operator_started_at=repo.parse_iso_dt(row["operator_started_at"]),
                soon_threshold_days=soon_days,
                today=today,
            )
            enriched.append({
                "row": row,
                "urgency": urgency,
                "status_label": bl.internal_status_label(events),
                "deadline_date": repo.parse_iso_date(row["deadline_date"]),
            })

        # Динамические опции фильтров "Тип теста"/"Статус" — только то, что
        # реально есть в текущей выборке (поиск + быстрый фильтр), а не весь
        # каталог/весь список меток (иначе в списке были бы пункты, которые
        # ничего не находят).
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
            self.table.setCellWidget(i, 0, ui_kit.make_urgency_dot(e["urgency"]))

            gns_item = ui_kit.make_table_item(row["gns_number"] or "")
            gns_item.setData(Qt.UserRole, row["test_id"])
            self.table.setItem(i, 1, gns_item)
            self.table.setItem(i, 2, ui_kit.make_table_item(row["order_no"] or ""))
            self.table.setItem(i, 3, ui_kit.make_table_item(row["customer_name"] or ""))

            self.table.setCellWidget(i, 4, ui_kit.make_type_badge(
                pcat.get_display_name(row["test_type"]), pcat.get_color(row["test_type"])
            ))
            self.table.setCellWidget(i, 5, ui_kit.make_status_chip(e["status_label"]))

            self.table.setCellWidget(i, 6, ui_kit.make_deadline_cell(
                fmt_date(row["deadline_date"]) or "—", ui_kit.deadline_text_color(e["urgency"])
            ))

            if keep_selection_test_id is not None and row["test_id"] == keep_selection_test_id:
                select_row_idx = i

        self.main_window.set_footer_count(len(filtered))

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
            item = self.table.item(i, 1)
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
        gns_item = self.table.item(row_idx, 1)
        if gns_item is None:
            return
        test_id = gns_item.data(Qt.UserRole)
        self.card.show_test(test_id)


# ---------------------------------------------------------------------
# Мелкие переиспользуемые блоки карточки
# ---------------------------------------------------------------------

def _info_box() -> QFrame:
    box = QFrame()
    box.setObjectName("infoBox")
    return box


def _section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


def _field_row(label: str, value: str) -> QFrame:
    box = QFrame()
    box.setObjectName("fieldBox")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(3)
    lbl = QLabel(label)
    lbl.setObjectName("fieldLabel")
    lay.addWidget(lbl)
    val = QLabel(value or "—")
    val.setObjectName("fieldValue")
    val.setWordWrap(True)
    lay.addWidget(val)
    return box


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

        # --- заголовок ---
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.badge_slot = QHBoxLayout()
        head_row.addLayout(self.badge_slot)
        self.header_label = QLabel("Выберите тест в списке слева")
        self.header_label.setObjectName("cardTitle")
        head_row.addWidget(self.header_label, stretch=1)
        layout.addLayout(head_row)

        self.sub_label = QLabel("Операторская карточка")
        self.sub_label.setObjectName("cardSub")
        layout.addWidget(self.sub_label)

        self.status_pill = QLabel("")
        self.status_pill.setObjectName("cardStatusPill")
        self.status_pill.setVisible(False)
        pill_row = QHBoxLayout()
        pill_row.addWidget(self.status_pill)
        pill_row.addStretch(1)
        layout.addLayout(pill_row)

        # --- дедлайн / клиент ---
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

        # --- заказ · управление (только просмотр — редактирование через
        # существующий диалог TestEditDialog, repository.py не дублируем) ---
        layout.addWidget(_section_title("Заказ · управление"))
        self.order_box = _info_box()
        order_lay = QVBoxLayout(self.order_box)
        order_lay.setContentsMargins(12, 10, 12, 10)
        order_lay.setSpacing(8)
        self.order_fields_grid = QGridLayout()
        self.order_fields_grid.setSpacing(8)
        order_lay.addLayout(self.order_fields_grid)

        order_btn_row = QHBoxLayout()
        order_btn_row.setSpacing(8)
        self.edit_button = QPushButton("Редактировать заказ")
        self.edit_button.clicked.connect(self._on_edit_clicked)
        self.edit_button.setEnabled(False)
        order_btn_row.addWidget(self.edit_button)
        self.history_button = QPushButton("История изменений")
        self.history_button.clicked.connect(self._on_history_clicked)
        self.history_button.setEnabled(False)
        order_btn_row.addWidget(self.history_button)
        order_lay.addLayout(order_btn_row)
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

        # --- маршрут теста (таймлайн) ---
        layout.addWidget(_section_title("Маршрут теста"))
        self.timeline_container = QVBoxLayout()
        layout.addLayout(self.timeline_container)
        self._timeline_widget: Optional[ui_kit.TestTimelineWidget] = None

        # --- действия ---
        layout.addWidget(_section_title("Действия"))
        self.actions_grid = QGridLayout()
        self.actions_grid.setSpacing(8)
        layout.addLayout(self.actions_grid)
        self._action_buttons: list[QPushButton] = []

        # --- внутренний комментарий ---
        layout.addWidget(_section_title("Комментарий"))
        self.comment_block = QLabel("")
        self.comment_block.setWordWrap(True)
        layout.addWidget(self.comment_block)

        layout.addStretch(1)

    def clear(self) -> None:
        self._test_id = None
        self._order_id = None
        self.header_label.setText("Выберите тест в списке слева")
        self._clear_layout(self.badge_slot)
        self.status_pill.setVisible(False)
        self.deadline_big.setText("")
        self.deadline_note.setText("")
        self.client_text.setText("")
        self._clear_grid(self.order_fields_grid)
        self.sibling_box.setVisible(False)
        self.siblings_title.setVisible(False)
        self._clear_layout(self.sibling_layout)
        self._set_timeline(None)
        self.comment_block.setText("")
        self.edit_button.setEnabled(False)
        self.history_button.setEnabled(False)
        self._clear_action_buttons()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

    def _clear_action_buttons(self) -> None:
        self._clear_grid(self.actions_grid)
        self._action_buttons = []

    def _set_timeline(self, steps: Optional[list[dict]]) -> None:
        if self._timeline_widget is not None:
            self.timeline_container.removeWidget(self._timeline_widget)
            self._timeline_widget.deleteLater()
            self._timeline_widget = None
        if steps:
            self._timeline_widget = ui_kit.TestTimelineWidget(steps)
            self.timeline_container.addWidget(self._timeline_widget)

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

        self._test_id = test_id
        self._order_id = row["order_id"]
        self.edit_button.setEnabled(True)
        self.history_button.setEnabled(True)

        events = repo.list_events_for_test(conn, test_id)
        internal_status = bl.internal_status_label(events)
        operator_tag = f" · {row['operator_name']}" if row["operator_name"] else ""

        self._clear_layout(self.badge_slot)
        self.badge_slot.addWidget(ui_kit.make_type_badge(
            pcat.get_display_name(row["test_type"]), pcat.get_color(row["test_type"])
        ))
        self.header_label.setText(f"{row['gns_number']}{operator_tag}")
        self.sub_label.setText("Операторская карточка")

        self.status_pill.setText(internal_status)
        self.status_pill.setVisible(True)

        if row["client_issued_at"]:
            self.deadline_big.setText("Завершено")
            self.deadline_note.setText("Тест выдан клиенту")
        else:
            dl = repo.parse_iso_date(row["deadline_date"])
            if dl:
                self.deadline_big.setText(dl.strftime("%d.%m.%Y"))
                days_left = (dl - date.today()).days
                if days_left < 0:
                    self.deadline_note.setText(f"Просрочено на {-days_left} дн.")
                else:
                    self.deadline_note.setText(f"До дедлайна {days_left} дн.")
            else:
                self.deadline_big.setText("Уточняется")
                self.deadline_note.setText("Рассчитается после получения образца")

        self.client_text.setText(
            f"<b>{row['customer_name']}</b><br>"
            f"Контакты: {row['contacts'] or '—'}<br>"
            f"№ заказа: {row['order_no'] or '—'}"
        )

        # --- заказ · управление (только просмотр) ---
        self._clear_grid(self.order_fields_grid)
        self.order_fields_grid.addWidget(_field_row("Статус заказа", row["order_status"] or "—"), 0, 0)
        self.order_fields_grid.addWidget(_field_row("Доставка", row["delivery_method"] or "—"), 0, 1)
        self.order_fields_grid.addWidget(_field_row("№ отправления", row["tracking_number"] or "—"), 1, 0)
        self.order_fields_grid.addWidget(_field_row("Дата заказа", fmt_date(row["order_created_at"]) or "—"), 1, 1)
        addr_box = _field_row("Адрес доставки", row["delivery_address"] or "—")
        self.order_fields_grid.addWidget(addr_box, 2, 0, 1, 2)

        # --- блок «остальные тесты этого заказа» ---
        self._clear_layout(self.sibling_layout)
        siblings = repo.list_sibling_tests_for_order(conn, row["order_id"])
        if len(siblings) > 1:
            sib_events = repo.list_events_for_test_ids(conn, [s["test_id"] for s in siblings])
            header = QLabel(f"<b>Заказ #{row['order_no'] or row['order_id']} · {len(siblings)} теста(ов)</b>")
            header.setStyleSheet("background:transparent; border:none;")
            self.sibling_layout.addWidget(header)
            for s in siblings:
                s_status = bl.internal_status_label(sib_events.get(s["test_id"], []))
                marker = "▶ " if s["test_id"] == test_id else ""
                text = f"{marker}{pcat.get_display_name(s['test_type'])} — {s['gns_number']} — {s_status}"
                dot_hex = pcat.get_color(s["test_type"]) or "#a8b0bd"
                self.sibling_layout.addWidget(ui_kit.make_dot_line(dot_hex, text))
            self.sibling_box.setVisible(True)
            self.siblings_title.setVisible(True)
        else:
            self.sibling_box.setVisible(False)
            self.siblings_title.setVisible(False)

        # --- визуальный таймлайн маршрута ---
        self._set_timeline(self._build_timeline_steps(events))

        # --- быстрые действия ---
        self._build_action_buttons(events)

        self.comment_block.setText(f"<i>{row['comments'] or 'нет комментария'}</i>")

        # Пересборка layout'ов с быстрыми действиями в рантайме (после
        # record_event) может сбить пересчёт геометрии родительского layout в
        # headless/Xvfb-рендере. Форсируем полную инвалидацию и пересчёт.
        self.layout().invalidate()
        self.layout().activate()
        self.updateGeometry()
        self.update()

    @staticmethod
    def _build_timeline_steps(events) -> list[dict]:
        present = {e["event_type"]: e for e in events}
        next_et = bl.next_action_event_type(events)
        current_notes = {
            "received": "Оператор должен подтвердить получение образца",
            "handed_to_lab": "Передать конкретный тест в лабораторию",
        }
        steps = []
        for et in bl.EVENT_ORDER:
            label = bl.EVENT_LABELS_INTERNAL[et]
            if et in present:
                ev = present[et]
                note = "(вручную скорректировано)" if ev["is_manual_correction"] else ""
                steps.append({
                    "title": label, "state": "done",
                    "time": fmt_dt(ev["event_time"]), "note": note,
                })
            elif et == next_et:
                steps.append({
                    "title": label, "state": "current",
                    "time": "", "note": current_notes.get(et, "Следующее действие"),
                })
            else:
                steps.append({"title": label, "state": "wait", "time": "", "note": ""})
        return steps

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
            btn.setMinimumHeight(34)
            if et in present:
                btn.setText(f"✓ {bl.EVENT_LABELS_INTERNAL[et]}")
                btn.setEnabled(False)
                btn.setObjectName("actionDone")
            elif et == next_et:
                btn.setText(bl.ACTION_BUTTON_LABELS[et])
                btn.setObjectName("actionPrimary")
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
