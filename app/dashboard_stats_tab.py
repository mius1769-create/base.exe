"""
GENOPOISK CRM — «Дашборд» → подвкладка «Статистика».

KPI месяца (заказы/тесты/выдачи/новые клиенты), продажи по типам тестов
(горизонтальный график), среднее время выполнения по типу теста (клик по
строке — количество/мин/макс), план/факт с прогресс-барами.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QPieSeries, QCategoryAxis, QValueAxis
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QFrame, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QProgressBar,
)

from . import dashboard_repo as drepo
from . import product_catalog as pcat
from . import theme
from .internal_tab import _info_box, _section_title
from .dashboard_tab import month_label, kpi_box, clear_layout, GREEN


class DashboardStatsTab(QWidget):
    def __init__(self, conn: sqlite3.Connection, main_window):
        super().__init__()
        self.conn = conn
        self.main_window = main_window
        self.month = drepo.current_month()
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

        head_row = QHBoxLayout()
        head_row.addWidget(QLabel("Месяц:"))
        self.month_combo = QComboBox()
        for m in drepo.last_n_months(12):
            self.month_combo.addItem(month_label(m), userData=m)
        self.month_combo.setCurrentIndex(self.month_combo.count() - 1)
        self.month_combo.currentIndexChanged.connect(self._on_month_changed)
        head_row.addWidget(self.month_combo)
        head_row.addStretch(1)

        plan_btn = QPushButton("Настроить план")
        plan_btn.clicked.connect(self._on_edit_plan)
        head_row.addWidget(plan_btn)
        root.addLayout(head_row)

        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(10)
        root.addLayout(self.kpi_row)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.revenue_chart_view = QChartView()
        self.revenue_chart_view.setRenderHint(QPainter.Antialiasing)
        self.revenue_chart_view.setMinimumHeight(300)
        charts_row.addWidget(self.revenue_chart_view, stretch=2)
        self.structure_chart_view = QChartView()
        self.structure_chart_view.setRenderHint(QPainter.Antialiasing)
        self.structure_chart_view.setMinimumHeight(300)
        charts_row.addWidget(self.structure_chart_view, stretch=1)
        root.addLayout(charts_row)

        plan_box = _info_box()
        plan_lay = QVBoxLayout(plan_box)
        plan_lay.setContentsMargins(14, 12, 14, 12)
        plan_lay.addWidget(_section_title("План / факт"))
        self.plan_container = QVBoxLayout()
        self.plan_container.setSpacing(8)
        plan_lay.addLayout(self.plan_container)
        plan_lay.addStretch(1)
        root.addWidget(plan_box)

        root.addWidget(_section_title("Среднее время выполнения"))
        self.turnaround_table = QTableWidget(0, 5)
        self.turnaround_table.setHorizontalHeaderLabels(
            ["Тип теста", "Среднее", "Медиана", "Мин", "Макс"]
        )
        self.turnaround_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.turnaround_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.turnaround_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.turnaround_table.verticalHeader().setDefaultSectionSize(26)
        self.turnaround_table.setMinimumHeight(200)
        root.addWidget(self.turnaround_table)

    def _on_month_changed(self, _index: int) -> None:
        self.month = self.month_combo.currentData() or drepo.current_month()
        self.refresh()

    def _on_edit_plan(self) -> None:
        from .dashboard_dialogs import PlanTargetsDialog
        dlg = PlanTargetsDialog(self.conn, self.month, self)
        if dlg.exec():
            self.refresh()

    def refresh(self, *_args) -> None:
        activity = drepo.get_month_activity(self.conn, self.month)
        clear_layout(self.kpi_row)
        self.kpi_row.addWidget(kpi_box("Заказов за месяц", str(activity.orders_count)))
        self.kpi_row.addWidget(kpi_box("Тестов за месяц", str(activity.tests_count)))
        self.kpi_row.addWidget(kpi_box("Выдано результатов", str(activity.issued_count)))
        self.kpi_row.addWidget(kpi_box("Новых клиентов", str(activity.new_clients_count)))

        self._refresh_revenue_chart()
        self._refresh_structure_chart()
        self._refresh_plan_fact()
        self._refresh_turnaround()

    def _refresh_revenue_chart(self) -> None:
        data = drepo.get_revenue_dynamics(self.conn, 12)
        series = QLineSeries()
        for i, (_month, value) in enumerate(data):
            series.append(i, value)
        chart = QChart(); chart.addSeries(series)
        chart.setTitle("Динамика коммерческой выручки")
        chart.legend().hide(); chart.setBackgroundVisible(False)
        axis_x = QCategoryAxis(); axis_x.setRange(0, max(len(data)-1,1))
        for i, (month, _value) in enumerate(data):
            axis_x.append(month[5:], i)
        chart.addAxis(axis_x, Qt.AlignBottom); series.attachAxis(axis_x)
        axis_y = QValueAxis(); axis_y.setLabelFormat("%.0f")
        max_value=max((v for _m,v in data), default=0.0); axis_y.setRange(0, max_value*1.15 if max_value else 1)
        chart.addAxis(axis_y, Qt.AlignLeft); series.attachAxis(axis_y)
        self.revenue_chart_view.setChart(chart)

    def _refresh_structure_chart(self) -> None:
        data = drepo.get_revenue_structure(self.conn, self.month)
        series = QPieSeries(); series.setHoleSize(0.55)
        total=sum(max(v,0) for _c,_n,v in data)
        for _code,name,value in data:
            sl=series.append(name, max(value,0))
            if total: sl.setLabel(f"{name} {value/total*100:.0f}%")
            sl.setLabelVisible(True)
        chart=QChart(); chart.addSeries(series); chart.setTitle(f"Структура выручки — {month_label(self.month)}")
        chart.legend().setVisible(False); chart.setBackgroundVisible(False)
        self.structure_chart_view.setChart(chart)

    def _refresh_plan_fact(self) -> None:
        clear_layout(self.plan_container)
        pf = drepo.get_plan_fact(self.conn, self.month)
        rows = [
            ("Заказы", pf.orders_fact, pf.orders_plan),
            ("Тесты", pf.tests_fact, pf.tests_plan),
            ("Выдачи", pf.issued_fact, pf.issued_plan),
        ]
        for label, fact, plan in rows:
            row_box = QVBoxLayout()
            row_box.setSpacing(3)

            top = QHBoxLayout()
            name = QLabel(label)
            name.setStyleSheet("background:transparent; border:none;")
            top.addWidget(name, stretch=1)
            color = GREEN if plan and fact >= plan else theme.TEXT_PRIMARY
            value = QLabel(f"{fact} / {plan}" if plan else f"{fact} / —")
            value.setStyleSheet(f"background:transparent; border:none; font-weight:600; color:{color};")
            top.addWidget(value)
            row_box.addLayout(top)

            pct = max(0, min(100, round(fact / plan * 100))) if plan else 0
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"QProgressBar {{ background:{theme.BORDER}; border:none; border-radius:4px; }} "
                f"QProgressBar::chunk {{ background:{theme.ACCENT}; border-radius:4px; }}"
            )
            row_box.addWidget(bar)

            self.plan_container.addLayout(row_box)

    def _refresh_turnaround(self) -> None:
        rows = drepo.get_avg_turnaround(self.conn)
        self.turnaround_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.turnaround_table.setItem(i, 0, QTableWidgetItem(r.display_name))
            for col, val in ((1, r.avg_days), (2, r.median_days), (3, r.min_days), (4, r.max_days)):
                item = QTableWidgetItem(f"{val:.0f} дн.")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.turnaround_table.setItem(i, col, item)
