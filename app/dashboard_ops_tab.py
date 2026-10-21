"""
GENOPOISK CRM — «Дашборд» → подвкладка «Операционка».

KPI (в работе / в лаборатории / готово к выдаче / просрочено),
производственная воронка, просроченные тесты, зависшие тесты (топ-10
самых старых незавершённых), последние события.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QProgressBar,
)

from . import dashboard_repo as drepo
from . import product_catalog as pcat
from . import theme
from .internal_tab import _info_box, _section_title
from .dashboard_tab import kpi_box, clear_layout, RED


class DashboardOpsTab(QWidget):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(10)
        root.addLayout(self.kpi_row)

        funnel_box = _info_box()
        funnel_lay = QVBoxLayout(funnel_box)
        funnel_lay.setContentsMargins(14, 12, 14, 12)
        funnel_lay.addWidget(_section_title("Производственная воронка"))
        self.funnel_container = QVBoxLayout()
        self.funnel_container.setSpacing(6)
        funnel_lay.addLayout(self.funnel_container)
        root.addWidget(funnel_box)

        tables_row = QHBoxLayout()
        tables_row.setSpacing(10)

        overdue_box = QVBoxLayout()
        overdue_box.addWidget(_section_title("Просроченные тесты"))
        self.overdue_table = QTableWidget(0, 3)
        self.overdue_table.setHorizontalHeaderLabels(["GNS", "Тип теста", "Просрочка"])
        self.overdue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.overdue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.overdue_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.overdue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.overdue_table.verticalHeader().setDefaultSectionSize(26)
        self.overdue_table.setMinimumHeight(220)
        self.overdue_table.doubleClicked.connect(self._on_overdue_double_clicked)
        overdue_box.addWidget(self.overdue_table)
        tables_row.addLayout(overdue_box, stretch=1)

        stuck_box = QVBoxLayout()
        stuck_box.addWidget(_section_title("Зависшие тесты (топ-10 самых старых)"))
        self.stuck_table = QTableWidget(0, 3)
        self.stuck_table.setHorizontalHeaderLabels(["GNS", "Тип", "Дней в работе"])
        self.stuck_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stuck_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stuck_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.stuck_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stuck_table.verticalHeader().setDefaultSectionSize(26)
        self.stuck_table.setMinimumHeight(220)
        self.stuck_table.doubleClicked.connect(self._on_stuck_double_clicked)
        stuck_box.addWidget(self.stuck_table)
        tables_row.addLayout(stuck_box, stretch=1)

        root.addLayout(tables_row)

        events_box = _info_box()
        events_lay = QVBoxLayout(events_box)
        events_lay.setContentsMargins(14, 12, 14, 12)
        events_lay.addWidget(_section_title("Последние события"))
        self.events_container = QVBoxLayout()
        self.events_container.setSpacing(4)
        events_lay.addLayout(self.events_container)
        root.addWidget(events_box)

    # ------------------------------------------------------------------
    def _open_test(self, test_id: int) -> None:
        from .edit_dialog import TestEditDialog
        dlg = TestEditDialog(self.conn, test_id, self.main_window)
        if dlg.exec():
            self.refresh()

    def _on_overdue_double_clicked(self, index) -> None:
        item = self.overdue_table.item(index.row(), 0)
        if item is not None:
            self._open_test(item.data(Qt.UserRole))

    def _on_stuck_double_clicked(self, index) -> None:
        item = self.stuck_table.item(index.row(), 0)
        if item is not None:
            self._open_test(item.data(Qt.UserRole))

    # ------------------------------------------------------------------
    def refresh(self, *_args) -> None:
        kpis = drepo.get_operational_kpis(self.conn)
        clear_layout(self.kpi_row)
        self.kpi_row.addWidget(kpi_box("В работе", str(kpis.in_progress)))
        self.kpi_row.addWidget(kpi_box("В лаборатории", str(kpis.in_lab)))
        self.kpi_row.addWidget(kpi_box("Готово к выдаче", str(kpis.ready_to_issue)))
        overdue_color = RED if kpis.overdue else theme.TEXT_PRIMARY
        self.kpi_row.addWidget(kpi_box("Просрочено", str(kpis.overdue), value_color=overdue_color))

        self._refresh_funnel()
        self._refresh_overdue()
        self._refresh_stuck()
        self._refresh_events()

    def _refresh_funnel(self) -> None:
        clear_layout(self.funnel_container)
        f = drepo.get_production_funnel(self.conn)
        stages = [
            ("Создано", f.created),
            ("Получен образец", f.sample_received),
            ("Отправлено в лабораторию", f.in_lab),
            ("Получен профиль", f.profile_received),
            ("Готово к выдаче", f.ready_to_issue),
            ("Выдано", f.issued),
        ]
        total = f.created or 1
        for label, count in stages:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setStyleSheet("background:transparent; border:none;")
            row.addWidget(name, stretch=2)

            pct = max(0, min(100, round(count / total * 100)))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                f"QProgressBar {{ background:{theme.BORDER}; border:none; border-radius:5px; }} "
                f"QProgressBar::chunk {{ background:{theme.ACCENT}; border-radius:5px; }}"
            )
            row.addWidget(bar, stretch=4)

            count_label = QLabel(str(count))
            count_label.setStyleSheet("background:transparent; border:none; font-weight:600;")
            count_label.setFixedWidth(36)
            count_label.setAlignment(Qt.AlignRight)
            row.addWidget(count_label)

            self.funnel_container.addLayout(row)

    def _refresh_overdue(self) -> None:
        rows = drepo.get_overdue_tests(self.conn)
        today = date.today()
        self.overdue_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            gns_item = QTableWidgetItem(row["gns_number"])
            gns_item.setData(Qt.UserRole, row["test_id"])
            self.overdue_table.setItem(i, 0, gns_item)
            self.overdue_table.setItem(i, 1, QTableWidgetItem(pcat.get_display_name(row["test_type"])))
            try:
                days = (today - date.fromisoformat(row["deadline_date"])).days
            except (TypeError, ValueError):
                days = 0
            days_item = QTableWidgetItem(f"+{days} дн.")
            days_item.setForeground(QColor(RED))
            self.overdue_table.setItem(i, 2, days_item)

    def _refresh_stuck(self) -> None:
        rows = drepo.get_stuck_tests(self.conn, limit=10)
        today = date.today()
        self.stuck_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            gns_item = QTableWidgetItem(row["gns_number"])
            gns_item.setData(Qt.UserRole, row["test_id"])
            self.stuck_table.setItem(i, 0, gns_item)
            self.stuck_table.setItem(i, 1, QTableWidgetItem(pcat.get_display_name(row["test_type"])))
            try:
                created = row["created_at"][:10]
                days = (today - date.fromisoformat(created)).days
            except (TypeError, ValueError):
                days = 0
            days_item = QTableWidgetItem(str(days))
            days_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stuck_table.setItem(i, 2, days_item)

    def _refresh_events(self) -> None:
        clear_layout(self.events_container)
        events = drepo.get_recent_events(self.conn, limit=20)
        if not events:
            lbl = QLabel("Событий пока нет")
            lbl.setStyleSheet(f"background:transparent; border:none; color:{theme.TEXT_MUTED};")
            self.events_container.addWidget(lbl)
            return
        for e in events:
            lbl = QLabel(f"<b>{e['time']}</b>  {e['text']}")
            lbl.setStyleSheet("background:transparent; border:none;")
            self.events_container.addWidget(lbl)
