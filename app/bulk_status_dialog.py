"""
GENOPOISK CRM — массовое редактирование статуса сразу для нескольких
выделенных тестов (вкладка «Внутренняя работа»).

Нужно, когда в базу заведена пачка старых тестов (импорт истории) и по
факту часть из них уже прошла более поздние этапы (образец получен,
выдано клиенту), хотя в системе у всех стоит самый первый статус.

Работает через тот же repo.record_event(), что и обычные кнопки быстрых
действий в карточке — так статус, зеркалируемые колонки tests и журнал
событий остаются согласованы. Событие идемпотентно: если у теста уже стоит
выбранный статус, повторная запись — no-op.

Проставление "дальнего" статуса (напр. "Выдано клиенту") без более ранних
этапов сделало бы маршрут в карточке нелогичным (следующим действием
предлагалось бы "Отправлен"), поэтому заодно доставляются все пропущенные
более ранние этапы той же датой.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QDateEdit, QLabel,
    QPushButton, QHBoxLayout, QMessageBox,
)

from . import business_logic as bl
from . import repository as repo
from . import settings as st

# order_created выставляется автоматически при создании заказа — вручную
# массово проставлять его незачем.
BULK_EVENT_CHOICES = [et for et in bl.EVENT_ORDER if et != "order_created"]


class BulkStatusEditDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, test_ids: list[int], parent=None):
        super().__init__(parent)
        self.conn = conn
        self.test_ids = test_ids
        self.setWindowTitle(f"Массовое изменение статуса — {len(test_ids)} тест(ов)")
        self.resize(440, 220)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Выбрано тестов: {len(self.test_ids)}"))

        form = QFormLayout()
        self.status_combo = QComboBox()
        for et in BULK_EVENT_CHOICES:
            self.status_combo.addItem(bl.EVENT_LABELS_INTERNAL[et], userData=et)
        self.status_combo.setCurrentIndex(len(BULK_EVENT_CHOICES) - 1)  # по умолчанию "Выдано клиенту"
        form.addRow("Новый статус", self.status_combo)

        self.date_edit = QDateEdit(calendarPopup=True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        form.addRow("Дата события", self.date_edit)
        layout.addLayout(form)

        hint = QLabel(
            "Событие проставляется как ручная корректировка (напр. для внесения\n"
            "старых тестов, выданных до перехода на систему). Если у теста ещё\n"
            "не было более ранних этапов — они автоматически проставляются той\n"
            "же датой, чтобы маршрут в карточке остался согласованным. Тесты,\n"
            "у которых выбранный статус уже стоит, пропускаются."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7a8498; font-size:11px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        apply_btn = QPushButton("Применить")
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

    def _on_apply(self) -> None:
        target_event = self.status_combo.currentData()
        qd = self.date_edit.date()
        event_time = f"{date(qd.year(), qd.month(), qd.day()).isoformat()}T00:00:00"
        operator = st.get_setting(self.conn, "current_operator_name", "") or "оператор"

        target_idx = bl.EVENT_ORDER.index(target_event)
        stages_to_ensure = bl.EVENT_ORDER[1:target_idx + 1]  # без order_created

        changed_tests = 0
        already_had_status = 0
        for test_id in self.test_ids:
            existing = {e["event_type"] for e in repo.list_events_for_test(self.conn, test_id)}
            if target_event in existing:
                already_had_status += 1
                continue
            for stage in stages_to_ensure:
                repo.record_event(
                    self.conn, test_id, stage,
                    event_time=event_time, operator=operator,
                    is_manual_correction=True,
                    note="массовое редактирование статуса",
                    user_name=operator,
                )
            changed_tests += 1

        summary = f"Статус обновлён у {changed_tests} тест(ов)."
        if already_had_status:
            summary += f" Пропущено (уже был такой статус): {already_had_status}."
        QMessageBox.information(self, "Готово", summary)
        self.accept()
