"""
GENOPOISK CRM — вкладка «Дашборд» (первая слева): обзор бизнеса для
владельца/руководителя. Три независимые подвкладки — Финансы, Статистика,
Операционка (раздел ТЗ v1: "Три независимые подвкладки", "стиль варианта Б",
"без перегруженных графиков"). Только чтение — никакие действия здесь не
меняют tests/orders напрямую (кроме открытия готовых диалогов: карточка
просроченного/зависшего теста, настройка цен/плана).

Общие визуальные и форматирующие хелперы для всех трёх подвкладок живут
здесь и импортируются ими, чтобы не дублироваться в три раза.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QLabel, QFrame

from . import theme
from .internal_tab import _info_box, _section_title

_MONTH_ABBR = {
    "01": "янв", "02": "фев", "03": "мар", "04": "апр", "05": "май", "06": "июн",
    "07": "июл", "08": "авг", "09": "сен", "10": "окт", "11": "ноя", "12": "дек",
}

RED = "#dc2626"
GREEN = "#16a34a"


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{_MONTH_ABBR.get(m, m)} {y[2:]}"


def fmt_money(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def kpi_box(title: str, value_text: str, *, value_color: str = theme.TEXT_PRIMARY) -> QFrame:
    box = _info_box()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.addWidget(_section_title(title))
    value_label = QLabel(value_text)
    value_label.setStyleSheet(
        f"font-size:22px; font-weight:700; background:transparent; border:none; color:{value_color};"
    )
    lay.addWidget(value_label)
    return box


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class DashboardTabWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window

        from .dashboard_finance_tab import DashboardFinanceTab
        from .dashboard_stats_tab import DashboardStatsTab
        from .dashboard_ops_tab import DashboardOpsTab

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sub_tabs = QTabWidget()
        self.finance_tab = DashboardFinanceTab(conn, main_window)
        self.stats_tab = DashboardStatsTab(conn, main_window)
        self.ops_tab = DashboardOpsTab(conn, main_window)
        self.sub_tabs.addTab(self.finance_tab, "Финансы")
        self.sub_tabs.addTab(self.stats_tab, "Статистика")
        self.sub_tabs.addTab(self.ops_tab, "Операционка")
        layout.addWidget(self.sub_tabs)

    def refresh(self, *_args) -> None:
        self.finance_tab.refresh()
        self.stats_tab.refresh()
        self.ops_tab.refresh()
