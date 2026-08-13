"""
GENOPOISK CRM — импорт исторической базы из Excel (раздел 16 ТЗ).

Правила:
  - исторические номера GNS/WGS/Strelka сохраняются как есть, без перенумерации;
  - ошибочные/неразобранные строки не теряются — уходят в import_errors;
  - показывается предпросмотр и статистика (импортировано/пропущено/дубли/ошибки);
  - исходный Excel-файл не изменяется (мы только читаем его).
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import openpyxl

from . import repository as repo

# Ожидаемые (гибко сопоставляемые) заголовки колонок исторического Excel.
# Ключ — внутреннее имя поля, значение — варианты заголовков в файле пользователя.
COLUMN_ALIASES: dict[str, list[str]] = {
    "gns_number": ["GNS", "GNPSK", "Номер", "№ GNS", "GNS/WGS/Strelka"],
    "order_no": ["№ заказа", "Order", "Номер заказа"],
    "customer_name": ["ФИО", "Клиент", "Имя"],
    "contacts": ["Контакты", "Телефон", "Email"],
    "test_type": ["Тип теста", "Тип", "Продукт"],
    "report_option": ["Комплектация", "Отчёт"],
    "sample_received_at": ["Дата образца", "Дата прихода образца"],
    "client_issued_at": ["Дата выдачи", "Выдан клиенту"],
    "comments": ["Комментарий", "Примечание"],
}


@dataclass
class ImportPreview:
    headers: list[str]
    sample_rows: list[dict[str, Any]]
    total_rows: int
    column_mapping: dict[str, Optional[str]]  # internal field -> matched header (or None)


@dataclass
class ImportResult:
    batch_id: str
    imported: int = 0
    skipped_duplicates: int = 0
    errors: int = 0
    total_rows: int = 0
    error_details: list[dict[str, Any]] = field(default_factory=list)


def _build_column_mapping(headers: list[str]) -> dict[str, Optional[str]]:
    mapping: dict[str, Optional[str]] = {}
    normalized = {h.strip().lower(): h for h in headers if h}
    for field_name, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            if alias.strip().lower() in normalized:
                found = normalized[alias.strip().lower()]
                break
        mapping[field_name] = found
    return mapping


def preview_excel(file_path: str, sheet_name: Optional[str] = None, max_rows: int = 20) -> ImportPreview:
    """Открывает Excel только для чтения — файл пользователя не изменяется."""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h) if h is not None else "" for h in next(rows_iter, [])]

    sample_rows = []
    total = 0
    for row in rows_iter:
        total += 1
        if len(sample_rows) < max_rows:
            sample_rows.append(dict(zip(headers, row)))

    wb.close()
    mapping = _build_column_mapping(headers)
    return ImportPreview(headers=headers, sample_rows=sample_rows, total_rows=total, column_mapping=mapping)


def _to_iso_date_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # попытка распарсить текстовую дату в формате ДД.ММ.ГГГГ
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def import_excel(
    conn: sqlite3.Connection,
    file_path: str,
    column_mapping: dict[str, Optional[str]],
    *,
    sheet_name: Optional[str] = None,
    user_name: Optional[str] = None,
) -> ImportResult:
    """
    Импортирует строки как исторические тесты (is_historical=1), под общим
    "историческим" заказом на каждую уникальную комбинацию (order_no, customer_name),
    либо отдельным заказом на строку, если order_no отсутствует.

    Дубли определяются по gns_number (уникальный номер) — если такой GNS уже
    есть в БД, строка пропускается и считается дублем, а не ошибкой.
    """
    batch_id = f"import-{uuid.uuid4().hex[:10]}"
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h) if h is not None else "" for h in next(rows_iter, [])]
    header_idx = {h: i for i, h in enumerate(headers)}

    result = ImportResult(batch_id=batch_id)

    for row_number, raw_row in enumerate(rows_iter, start=2):  # строка 1 — заголовки
        result.total_rows += 1
        try:
            def get(field_name: str) -> Any:
                header = column_mapping.get(field_name)
                if header is None or header not in header_idx:
                    return None
                idx = header_idx[header]
                return raw_row[idx] if idx < len(raw_row) else None

            gns_number = get("gns_number")
            if not gns_number:
                raise ValueError("Отсутствует номер GNS/GNPSK — строка не может быть импортирована")
            gns_number = str(gns_number).strip()

            existing = conn.execute(
                "SELECT test_id FROM tests WHERE gns_number = ?", (gns_number,)
            ).fetchone()
            if existing:
                result.skipped_duplicates += 1
                continue

            order_no = str(get("order_no") or "") or None
            customer_name = str(get("customer_name") or "")
            contacts = str(get("contacts") or "") or None
            test_type_raw = str(get("test_type") or "").strip()
            report_option_raw = str(get("report_option") or "Обычный").strip()
            report_option = "С отчётом" if "отчёт" in report_option_raw.lower() else "Обычный"
            sample_received_at = _to_iso_date_str(get("sample_received_at"))
            client_issued_at_date = _to_iso_date_str(get("client_issued_at"))
            comments = str(get("comments") or "") or None

            conn.execute("BEGIN IMMEDIATE")
            try:
                ts = repo.now_iso()
                cur = conn.execute(
                    """INSERT INTO orders
                       (order_no, order_status, customer_name, contacts, source,
                        created_at, updated_at)
                       VALUES (?, 'Импортирован', ?, ?, 'excel_import', ?, ?)""",
                    (order_no, customer_name, contacts, ts, ts),
                )
                order_id = cur.lastrowid

                cur = conn.execute(
                    """INSERT INTO tests
                       (order_id, gns_number, test_type, report_option, sample_received_at,
                        client_issued_at, comments, is_historical, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        order_id, gns_number, test_type_raw or "ИСТОРИЧЕСКИЙ", report_option,
                        sample_received_at,
                        f"{client_issued_at_date}T00:00:00" if client_issued_at_date else None,
                        comments, ts, ts,
                    ),
                )
                test_id = cur.lastrowid
                repo.write_audit(
                    conn, user_name=user_name, entity="test", entity_id=test_id,
                    field=None, old_value=None, new_value=f"импортирован ({gns_number})",
                    reason=f"импорт Excel batch={batch_id}",
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            result.imported += 1

        except Exception as exc:  # noqa: BLE001 — строка не должна прерывать весь импорт
            result.errors += 1
            error_row = {
                "row_number": row_number,
                "raw_row": repr(raw_row),
                "error_message": str(exc),
            }
            result.error_details.append(error_row)
            conn.execute(
                """INSERT INTO import_errors (import_batch, row_number, raw_row, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (batch_id, row_number, repr(raw_row), str(exc), repo.now_iso()),
            )

    wb.close()
    return result
