"""
GENOPOISK CRM — переиспользуемые визуальные виджеты (v1.5 UX).

Чистый презентационный слой поверх theme.py: бейджи типов тестов, чипы
статусов, точка срочности, попап фильтра в шапке таблицы, визуальный
таймлайн маршрута теста. Ничего здесь не читает и не пишет в БД напрямую —
всё принимает уже готовые данные (строки, метки, события) от вызывающего
кода (client_tab.py / internal_tab.py), которые сами берут их из
repository.py / business_logic.py без изменений.

Перенесено из согласованного эталона docs/GENOPOISK_CRM_UX_v1_5_header_filters.html.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QSizePolicy, QTableWidgetItem,
)

from . import business_logic as bl
from . import theme


def make_table_item(text: str) -> QTableWidgetItem:
    return QTableWidgetItem(text)

# ---------------------------------------------------------------------
# Цвета срочности — единая точка соответствия bl.RowColor -> hex
# (тот же смысл, что .dot.red/.purple/.yellow/.green/.gray в HTML-эталоне).
# ---------------------------------------------------------------------
URGENCY_HEX = {
    bl.RowColor.GREEN: "#16a34a",
    bl.RowColor.RED: "#dc2626",
    bl.RowColor.PURPLE: "#9333ea",
    bl.RowColor.YELLOW: "#f59e0b",
    bl.RowColor.NORMAL: "#a8b0bd",
}

URGENCY_FILTER_OPTIONS = [
    ("", "Все"),
    (bl.RowColor.NORMAL.value, "Нормальный срок"),
    (bl.RowColor.PURPLE.value, "Приближается дедлайн"),
    (bl.RowColor.RED.value, "Просрочен"),
    (bl.RowColor.GREEN.value, "Выдан клиенту"),
    (bl.RowColor.YELLOW.value, "Взято в работу"),
]

DEADLINE_BUCKET_OPTIONS = [
    ("", "Все"),
    ("today", "Сегодня"),
    ("1_3", "1–3 дня"),
    ("4_7", "4–7 дней"),
    ("gt7", "Больше 7 дней"),
    ("late", "Просрочено"),
    ("none", "Без дедлайна"),
]


def deadline_bucket(deadline_date, today) -> str:
    """Категория дедлайна для фильтра в шапке (раздел v1.5 header_filters)."""
    if deadline_date is None:
        return "none"
    days = (deadline_date - today).days
    if days < 0:
        return "late"
    if days == 0:
        return "today"
    if 1 <= days <= 3:
        return "1_3"
    if 4 <= days <= 7:
        return "4_7"
    return "gt7"


# ---------------------------------------------------------------------
# Чип статуса — соответствие меткам EVENT_LABELS_INTERNAL/EVENT_LABELS_CLIENT
# ---------------------------------------------------------------------
_DONE = ("#e9f8ef", "#b7e3c7", "#16803d", "#16a34a")
_WORK = ("#fff6df", "#f1d89a", "#9a6700", "#f59e0b")
_PROFILE = ("#eef0ff", "#cfd2ff", "#4f46e5", "#4f46e5")
_LAB = ("#f5eaff", "#ddc1ff", "#7e22ce", "#9333ea")
_RECEIVED = ("#e8fbf8", "#b8ebe5", "#0f766e", "#4f46e5")
_WAITING = ("#eef5ff", "#cbdcff", "#315eb8", "#4f46e5")
_NEUTRAL = ("#f5f6f8", "#dfe3ea", "#596273", "#a8b0bd")


def status_chip_style(label: str) -> tuple[str, str, str, str]:
    """Возвращает (bg, border, text, dot) hex-цвета для метки статуса."""
    if label.startswith("Выдан"):
        return _DONE
    if label in ("Взято в работу", "В обработке"):
        return _WORK
    if label == "Профиль получен":
        return _PROFILE
    if "лаборатор" in label:
        return _LAB
    if label == "Образец получен":
        return _RECEIVED
    if label in ("Ожидаем получение", "Образец в пути"):
        return _WAITING
    return _NEUTRAL


def _click_through(widget: QWidget) -> QWidget:
    """Строки таблицы должны выделяться кликом в любом месте (как <tr onclick>
    в HTML-эталоне). QTableWidget.setCellWidget() иначе перехватывает клик на
    себя раньше, чем он доходит до view — пробрасываем событие мыши насквозь."""
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    for child in widget.findChildren(QWidget):
        child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return widget


def make_status_chip(label: str) -> QWidget:
    bg, border, text, dot = status_chip_style(label)
    box = QWidget()
    box.setStyleSheet(
        f"background:{bg}; border:1px solid {border}; border-radius:5px;"
    )
    lay = QHBoxLayout(box)
    lay.setContentsMargins(9, 4, 9, 4)
    lay.setSpacing(7)
    dot_lbl = QLabel()
    dot_lbl.setFixedSize(8, 8)
    dot_lbl.setStyleSheet(f"background:{dot}; border-radius:4px;")
    lay.addWidget(dot_lbl)
    text_lbl = QLabel(label)
    text_lbl.setStyleSheet(f"color:{text}; font-weight:500; background:transparent; border:none;")
    lay.addWidget(text_lbl)
    lay.addStretch(1)
    box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return _click_through(box)


def make_type_badge(display_name: str, hex_color: Optional[str]) -> QWidget:
    bg = hex_color or "#e5e7eb"
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(display_name)
    lbl.setStyleSheet(
        f"background:{bg}; border:1px solid rgba(80,90,110,.35); border-radius:5px;"
        f"padding:4px 9px; font-weight:500; color:#1d2433;"
    )
    lay.addWidget(lbl)
    lay.addStretch(1)
    return _click_through(wrap)


def make_urgency_dot(color: bl.RowColor) -> QWidget:
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignCenter)
    dot = QLabel()
    dot.setFixedSize(9, 9)
    dot.setStyleSheet(f"background:{URGENCY_HEX[color]}; border-radius:4px;")
    lay.addWidget(dot)
    return _click_through(wrap)


def make_dot_line(hex_color: str, text: str) -> QWidget:
    """Строка "цветная точка + текст" — перенос .order-item из HTML-эталона
    (используется в блоке "Заказ · связанные тесты")."""
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    dot = QLabel()
    dot.setFixedSize(9, 9)
    dot.setStyleSheet(f"background:{hex_color}; border-radius:4px; margin-top:2px;")
    lay.addWidget(dot, 0, Qt.AlignTop)
    text_lbl = QLabel(text)
    text_lbl.setWordWrap(True)
    text_lbl.setStyleSheet("background:transparent; border:none;")
    lay.addWidget(text_lbl, 1)
    return wrap


def deadline_text_color(color: bl.RowColor) -> Optional[str]:
    if color == bl.RowColor.RED:
        return "#dc2626"
    if color == bl.RowColor.PURPLE:
        return "#9333ea"
    if color == bl.RowColor.GREEN:
        return "#16a34a"
    return None


def make_deadline_cell(text: str, color_hex: Optional[str]) -> QWidget:
    """Ячейка дедлайна как виджет, а не QTableWidgetItem.

    Qt/QSS красит текст ВЫДЕЛЕННОЙ строки через QPalette::HighlightedText
    независимо от Qt::ForegroundRole конкретного элемента (известное
    ограничение стилей на QAbstractItemView) — собственный цвет "просрочено"/
    "скоро дедлайн" при клике по строке сбрасывался бы в обычный чёрный.
    cellWidget не участвует в этой отрисовке вообще (как и бейдж/чип рядом),
    поэтому цвет остаётся стабильным при выделении — как .deadline.late в
    HTML-эталоне, не зависящий от .selected."""
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(10, 0, 10, 0)
    lbl = QLabel(text)
    color = color_hex or theme.TEXT_PRIMARY
    weight = 600 if color_hex else 400
    lbl.setStyleSheet(f"color:{color}; font-weight:{weight}; background:transparent; border:none;")
    lay.addWidget(lbl)
    lay.addStretch(1)
    return _click_through(wrap)


# ---------------------------------------------------------------------
# Попап фильтра колонки (клик по заголовку "Колонка ▾")
# ---------------------------------------------------------------------
class HeaderFilterPopup(QFrame):
    """Всплывающее меню фильтра одной колонки — перенос .filter-menu из
    HTML-эталона: либо список опций с отметкой выбранной, либо строка
    поиска. Закрывается кликом вне себя (Qt.Popup) — то же поведение, что
    document click-outside-close в JS-прототипе."""

    option_chosen = Signal(str)
    search_changed = Signal(str)

    def __init__(
        self,
        title: str,
        *,
        options: Optional[list[tuple[str, str]]] = None,
        searchable: bool = False,
        current_value: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("headerFilterMenu")
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(220)
        self.setMaximumWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        title_lbl = QLabel(title.upper())
        title_lbl.setObjectName("filterMenuTitle")
        layout.addWidget(title_lbl)

        self._search_edit: Optional[QLineEdit] = None
        if searchable:
            edit = QLineEdit()
            edit.setObjectName("filterSearch")
            edit.setPlaceholderText("Поиск…")
            edit.setText(current_value)
            edit.textChanged.connect(self.search_changed.emit)
            layout.addWidget(edit)
            self._search_edit = edit
        else:
            for value, label in options or []:
                btn = QPushButton(label)
                btn.setObjectName("filterOption")
                btn.setProperty("selected", value == current_value)
                btn.setCursor(QCursor(Qt.PointingHandCursor))
                btn.clicked.connect(lambda checked=False, v=value: self._choose(v))
                layout.addWidget(btn)

        divider = QFrame()
        divider.setObjectName("filterClearDivider")
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)

        reset_btn = QPushButton("Сбросить фильтр")
        reset_btn.setObjectName("filterOption")
        reset_btn.clicked.connect(lambda: self._choose(""))
        layout.addWidget(reset_btn)

    def _choose(self, value: str) -> None:
        self.option_chosen.emit(value)
        self.close()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._search_edit is not None:
            self._search_edit.setFocus()


class HeaderFilterMixin:
    """Подмешивается в *TabWidget: даёт open_header_filter()/сброс/учёт
    активных фильтров колонок. Ожидает атрибуты self.table, self.refresh()."""

    def init_header_filters(self, keys: list[str]) -> None:
        self._header_filter_values: dict[str, str] = {k: "" for k in keys}
        self._active_popup: Optional[HeaderFilterPopup] = None

    def header_filter_value(self, key: str) -> str:
        return self._header_filter_values.get(key, "")

    def header_filter_active(self, key: str) -> bool:
        return bool(self._header_filter_values.get(key))

    def open_header_filter(
        self,
        key: str,
        title: str,
        section_index: int,
        *,
        searchable: bool = False,
        options: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        header = self.table.horizontalHeader()
        pos = header.mapToGlobal(QPoint(header.sectionViewportPosition(section_index), header.height()))
        popup = HeaderFilterPopup(
            title,
            options=options,
            searchable=searchable,
            current_value=self.header_filter_value(key),
            parent=self.table,
        )
        popup.option_chosen.connect(lambda v, k=key: self._set_header_filter(k, v))
        if searchable:
            popup.search_changed.connect(lambda v, k=key: self._set_header_filter(k, v))
        popup.move(pos)
        popup.show()
        self._active_popup = popup

    def _set_header_filter(self, key: str, value: str) -> None:
        self._header_filter_values[key] = value
        self.refresh()


# ---------------------------------------------------------------------
# Визуальный таймлайн маршрута теста (только внутренняя вкладка)
# ---------------------------------------------------------------------
_TIMELINE_COLORS = {
    "done": QColor("#16a34a"),
    "current": QColor("#4f46e5"),
    "wait": QColor("#cfd5df"),
    "warn": QColor("#f59e0b"),
}


class TestTimelineWidget(QWidget):
    """Вертикальный таймлайн с точками и соединительной линией — перенос
    .timeline/.step/.step-dot из HTML-эталона. Принимает уже готовый список
    шагов (title/time/note/state), сам не знает про test_events/repository."""

    LINE_X = 15

    def __init__(self, steps: list[dict], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._steps = steps
        self._row_widgets: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.LINE_X + 12, 2, 4, 2)
        layout.setSpacing(16)

        for step in steps:
            row = QVBoxLayout()
            row.setSpacing(2)
            title = QLabel(step["title"])
            title.setObjectName("timelineStepTitle")
            row.addWidget(title)
            if step.get("time"):
                t = QLabel(step["time"])
                t.setObjectName("timelineStepTime")
                row.addWidget(t)
            if step.get("note"):
                n = QLabel(step["note"])
                n.setObjectName("timelineStepNote")
                n.setWordWrap(True)
                row.addWidget(n)
            wrap = QWidget()
            wrap.setLayout(row)
            layout.addWidget(wrap)
            self._row_widgets.append(wrap)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._row_widgets:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        centers = [w.geometry().top() + 8 for w in self._row_widgets]

        if len(centers) >= 2:
            pen = QPen(QColor("#dfe4ec"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(self.LINE_X, centers[0], self.LINE_X, centers[-1])

        for step, cy in zip(self._steps, centers):
            color = _TIMELINE_COLORS.get(step.get("state"), _TIMELINE_COLORS["wait"])
            painter.setPen(QPen(QColor("#ffffff"), 3))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPoint(self.LINE_X, cy), 6, 6)
        painter.end()
