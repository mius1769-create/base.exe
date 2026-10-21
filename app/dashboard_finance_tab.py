"""
GENOPOISK CRM — «Дашборд» → подвкладка «Финансы».

KPI (выручка/себестоимость/прибыль/маржа/средний чек за месяц), блок
«Прогноз месяца», «Экономика по типам тестов», кнопка «Настроить цены».
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtCharts import QChart, QChartView, QPieSeries
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QFrame, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)

from . import dashboard_repo as drepo
from . import theme
from .internal_tab import _info_box, _section_title
from .dashboard_tab import month_label, fmt_money, kpi_box, clear_layout, RED, GREEN


class DashboardFinanceTab(QWidget):
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

        pricing_btn = QPushButton("Настроить цены")
        pricing_btn.clicked.connect(self._on_edit_pricing)
        head_row.addWidget(pricing_btn)
        root.addLayout(head_row)

        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(10)
        root.addLayout(self.kpi_row)

        forecast_box = _info_box()
        forecast_lay = QVBoxLayout(forecast_box)
        forecast_lay.setContentsMargins(14, 12, 14, 12)
        forecast_lay.addWidget(_section_title("Прогноз месяца"))
        self.forecast_container = QVBoxLayout()
        self.forecast_container.setSpacing(4)
        forecast_lay.addLayout(self.forecast_container)
        root.addWidget(forecast_box)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.structure_chart_view = QChartView()
        self.structure_chart_view.setRenderHint(QPainter.Antialiasing)
        self.structure_chart_view.setMinimumHeight(280)
        charts_row.addWidget(self.structure_chart_view, stretch=1)
        self.promo_label = QLabel()
        self.promo_label.setWordWrap(True)
        self.promo_label.setStyleSheet(f"background:transparent; border:none; color:{theme.TEXT_MUTED}; padding:12px;")
        charts_row.addWidget(self.promo_label, stretch=1)
        root.addLayout(charts_row)

        root.addWidget(_section_title("Экономика по типам тестов"))
        self.economics_table = QTableWidget(0, 6)
        self.economics_table.setHorizontalHeaderLabels(
            ["Тип", "Продано", "Цена", "Себестоимость", "Выручка (распр.)", "Прибыль"]
        )
        self.economics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.economics_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.economics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.economics_table.verticalHeader().setDefaultSectionSize(26)
        self.economics_table.setMinimumHeight(260)
        root.addWidget(self.economics_table, stretch=1)

    def _on_month_changed(self, _index: int) -> None:
        self.month = self.month_combo.currentData() or drepo.current_month()
        self.refresh()

    def _on_edit_pricing(self) -> None:
        from .dashboard_dialogs import TestPricingDialog
        dlg = TestPricingDialog(self.conn, self)
        if dlg.exec():
            self.refresh()

    def refresh(self, *_args) -> None:
        kpi = drepo.get_kpis(self.conn, self.month)

        clear_layout(self.kpi_row)
        self.kpi_row.addWidget(kpi_box("Выручка месяца", fmt_money(kpi.revenue)))
        self.kpi_row.addWidget(kpi_box("Себестоимость месяца", fmt_money(kpi.cost)))
        profit_color = GREEN if kpi.profit >= 0 else RED
        self.kpi_row.addWidget(kpi_box("Валовая прибыль", fmt_money(kpi.profit), value_color=profit_color))
        self.kpi_row.addWidget(kpi_box("Маржинальность", f"{kpi.margin_pct:.1f}%", value_color=profit_color))
        self.kpi_row.addWidget(kpi_box("Средний чек", fmt_money(kpi.avg_check)))

        self._refresh_forecast()
        self._refresh_structure_chart()
        self._refresh_promo_summary()

        rows = drepo.get_test_economics(self.conn, self.month)
        self.economics_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.economics_table.setItem(i, 0, QTableWidgetItem(r.display_name))
            count_item = QTableWidgetItem(str(r.sold))
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.economics_table.setItem(i, 1, count_item)
            for col, val in ((2, r.price), (3, r.cost_price), (4, r.revenue), (5, r.profit)):
                item = QTableWidgetItem(fmt_money(val))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 5 and val < 0:
                    item.setForeground(QColor(RED))
                self.economics_table.setItem(i, col, item)

    def _refresh_structure_chart(self) -> None:
        data = drepo.get_revenue_structure(self.conn, self.month)
        series = QPieSeries(); series.setHoleSize(0.55)
        total=sum(max(v,0) for _c,_n,v in data)
        for _code,name,value in data:
            sl=series.append(name, max(value,0))
            if total: sl.setLabel(f"{name} {value/total*100:.0f}%")
            sl.setLabelVisible(True)
        chart=QChart(); chart.addSeries(series); chart.setTitle("Структура коммерческой выручки")
        chart.legend().setVisible(False); chart.setBackgroundVisible(False)
        self.structure_chart_view.setChart(chart)

    def _refresh_promo_summary(self) -> None:
        p = drepo.get_promo_summary(self.conn, self.month)
        self.promo_label.setText(
            f"<b>Промо / бартер</b><br><br>"
            f"Заказов: <b>{p['orders']}</b><br>"
            f"Тестов: <b>{p['tests']}</b><br>"
            f"Стоимость по прайсу: <b>{fmt_money(p['catalog_value'])}</b><br><br>"
            f"Промо не входит в коммерческую выручку, но остаётся в операционной нагрузке."
        )

    def _refresh_forecast(self) -> None:
        clear_layout(self.forecast_container)
        f = drepo.get_revenue_forecast(self.conn, self.month)
        rows = [
            ("План", fmt_money(f.plan) if f.plan else "не задан"),
            ("Факт", fmt_money(f.fact)),
            ("Прогноз", fmt_money(f.forecast)),
            (
                "Выполнение плана",
                f"{f.completion_pct:.0f}%" if f.plan else "—",
            ),
        ]
        for label, value in rows:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setStyleSheet("background:transparent; border:none;")
            row.addWidget(name, stretch=1)
            color = theme.TEXT_PRIMARY
            if label == "Выполнение плана" and f.plan:
                color = GREEN if f.completion_pct >= 100 else theme.TEXT_PRIMARY
            value_label = QLabel(value)
            value_label.setStyleSheet(f"background:transparent; border:none; font-weight:600; color:{color};")
            row.addWidget(value_label)
            self.forecast_container.addLayout(row)
