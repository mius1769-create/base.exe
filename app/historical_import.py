"""
GENOPOISK CRM — импорт реальной исторической базы «Отчеты_2025-2026.xlsx».

Это НЕ универсальный импортёр (см. app/importer.py для одностраничного
случая из ТЗ раздел 16) — это миграционный скрипт под конкретный файл
с 7 листами разной структуры, построенный по итогам ручного анализа и
явных решений пользователя, зафиксированных в диалоге:

  1. GNPKS -> GNPSK: опечатка, исправляется (23 номера на листе «Общий»).
  2. M-1..M-5 (лист SEM): каждый номер встречается дважды — Y50 и мтДНК
     одного человека. Первая (Y50) запись сохраняет номер как есть,
     вторая (мтДНК) получает суффикс "-мтДНК". Оба теста — один заказ.
  3. SE2/SMOL38 (лист SEM) -> переномерован в SEZ, как отдельная,
     независимая запись (не связана с SE2/SML14 в один заказ — нет
     подтверждения, что это один человек).
  4. Y-18, Аутосомы -> удаляются из импорта (не заводятся вовсе).
  5. мито -> MTDNA.
  6. WGS20X -> сохраняется буквально как есть, не приравнивается к
     WGS15X/WGS30X.
  7. Общий, колонка «тип теста» (H) на самом деле означает отчёт, а не
     тип: 'отчет'/'с отчетом'/'Premium' -> report_option='С отчётом';
     '@Siberian_shaman' — утечка тег-хендла из соседней колонки,
     ошибка поля, отчёт не проставляется, но строка не выбрасывается.
  8. Статус 'готов'/'готово' -> смысл «выдан клиенту». Дата выдачи
     проставляется, только если на листе реально есть колонка с датой
     выдачи и там стоит настоящая дата (не строка/число-огрызок);
     иначе client_issued_at остаётся пустым — пользователь донастроит
     вручную позже.
  9. Полностью пустые строки-заготовки (только номер, остальное пусто)
     пропускаются целиком: 21 на «Общий», 9 на Strelka (Strelka12-19),
     8 на ROM.
 10. ROM-44, ROM-45: в поле ФИО стоит цифра ("1"/"2") — сохраняется как
     есть; test_type проставляется как Y50 (решение пользователя).
 11. Любая дата, которая в Excel хранится не как дата (float-огрызок
     вроде 10.04, либо свободный текст вроде "дозаказал 4.02"), не
     разбирается и не угадывается — остаётся NULL, строка попадает в
     список "проблемные даты" для ручной правки пользователем позже.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import openpyxl

from . import repository as repo

SOURCE_FILE_LABEL = "Отчеты_2025-2026.xlsx (историческая миграция)"

# ---------------------------------------------------------------------
# Нормализация типов тестов
# ---------------------------------------------------------------------

_DELETE_TYPES = {"y18", "аутосомы"}

_TYPE_MAP = {
    "y50": "Y50", "y37": "Y37", "мтднк": "MTDNA", "митогеном": "MITOGENOME",
    "мито": "MTDNA",              # решение: мито = мтДНК
    "strelka": "STRELKA",
    "wgs15x": "WGS15", "wgs30x": "WGS30",
    "wgs20x": "WGS20X",           # решение: оставить буквально как есть
    "full": "FULL LINE",          # историческая FULL LINE — раздел 0 ТЗ
}


def normalize_test_type(raw: Any) -> tuple[Optional[str], str]:
    """Возвращает (нормализованный_код, статус), статус из
    {'known','deleted','unknown','missing'}."""
    if raw is None or str(raw).strip() == "":
        return None, "missing"
    s = str(raw).strip().lower().replace("х", "x").replace("-", "").replace(" ", "")
    if s in _DELETE_TYPES:
        return None, "deleted"
    if s in _TYPE_MAP:
        return _TYPE_MAP[s], "known"
    return None, "unknown"


# ---------------------------------------------------------------------
# Нормализация номеров (GNPKS->GNPSK, M-1..M-5, SE2/SEZ)
# ---------------------------------------------------------------------

_GNPKS_RE = re.compile(r"^GNPKS(\s*\d+)$")


def fix_gnpks_typo(raw: str) -> tuple[str, bool]:
    """GNPKS -> GNPSK (опечатка, решение пользователя). Возвращает
    (итоговый_номер, был_ли_исправлен)."""
    m = _GNPKS_RE.match(raw.strip())
    if m:
        return f"GNPSK{m.group(1)}", True
    return raw, False


# ---------------------------------------------------------------------
# Даты: принимаем ТОЛЬКО настоящие datetime/date объекты Excel.
# Float-огрызки и свободный текст -> None + попадает в needs_manual_dates.
# ---------------------------------------------------------------------

def safe_date(raw: Any) -> Optional[datetime.date]:
    if isinstance(raw, datetime.datetime):
        return raw.date()
    if isinstance(raw, datetime.date):
        return raw
    return None


def is_problematic_date(raw: Any) -> bool:
    """True если поле похоже на дату, но не разобралось как настоящая дата."""
    if raw is None:
        return False
    if isinstance(raw, (datetime.datetime, datetime.date)):
        return False
    return True  # float-огрызок или свободный текст


# ---------------------------------------------------------------------
# Отчёт: колонка "тип теста" на листе «Общий» на самом деле про отчёт
# ---------------------------------------------------------------------

def normalize_obshiy_report_flag(raw: Any) -> tuple[str, Optional[str]]:
    """Возвращает (report_option, error_note)."""
    if raw is None:
        return "Обычный", None
    s = str(raw).strip()
    if s in ("отчет", "с отчетом", "Premium"):
        return "С отчётом", None
    if s == "@Siberian_shaman":
        return "Обычный", "поле отчёта содержало утёкший Telegram-хендл (ошибка ввода) — проигнорировано"
    return "Обычный", f"нераспознанное значение поля отчёта: {s!r} — проигнорировано, отчёт не проставлен"


# ---------------------------------------------------------------------
# Результат построчной обработки
# ---------------------------------------------------------------------

@dataclass
class ProcessedRow:
    sheet: str
    excel_row: int
    action: str  # 'import' | 'skip_empty' | 'delete_unsupported_type'
    gns_number: Optional[str] = None
    customer_name: str = ""
    contacts: Optional[str] = None
    delivery_method: Optional[str] = None
    test_type: Optional[str] = None
    report_option: str = "Обычный"
    sample_received_at: Optional[datetime.date] = None
    client_issued_at: Optional[datetime.datetime] = None
    result_y: Optional[str] = None
    result_mt: Optional[str] = None
    comments: Optional[str] = None
    group_key: Optional[str] = None  # для M-1..M-5: общий заказ на пару строк
    notes: list[str] = field(default_factory=list)  # служебные пометки для отчёта (не в БД)
    problematic_dates: int = 0
    gnpks_fixed: bool = False


def _join_comments(*parts: Any) -> Optional[str]:
    vals = [str(p).strip() for p in parts if p is not None and str(p).strip() != ""]
    return "; ".join(vals) if vals else None


def _is_near_empty(row: tuple, number_idx: int) -> bool:
    return all(v is None for idx, v in enumerate(row) if idx != number_idx)


# ---------------------------------------------------------------------
# Построчные обработчики по листам
# ---------------------------------------------------------------------

def _process_obshiy(i: int, r: tuple) -> ProcessedRow:
    number_idx = 0
    if _is_near_empty(r, number_idx):
        return ProcessedRow(sheet="Общий", excel_row=i, action="skip_empty")

    raw_num = str(r[0]).strip()
    gns, fixed = fix_gnpks_typo(raw_num)
    test_type, kind = normalize_test_type(r[6])  # колонка "заказ"
    report_option, report_error = normalize_obshiy_report_flag(r[7])  # колонка "тип теста" (на деле — отчёт)

    if kind == "deleted":
        return ProcessedRow(sheet="Общий", excel_row=i, action="delete_unsupported_type",
                             gns_number=gns, test_type=str(r[6]), comments=repr(r))

    status_raw = r[3]
    is_issued = status_raw in ("готов", "готово")

    notes = []
    if fixed:
        notes.append(f"номер исправлен: {raw_num!r} -> {gns!r} (опечатка GNPKS/GNPSK)")
    if report_error:
        notes.append(report_error)
    if is_issued:
        notes.append("статус 'готов/готово' -> Выдан клиенту, но колонки даты выдачи на листе «Общий» нет — дата не проставлена")
    elif status_raw and status_raw not in ("готов", "готово"):
        notes.append(f"статус в исходнике: {status_raw!r} (не входит в целевой список, сохранён в комментарии)")

    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист Общий, строка {i}",
        f"статус в Excel: {status_raw}" if status_raw and not is_issued else None,
    )

    return ProcessedRow(
        sheet="Общий", excel_row=i, action="import",
        gns_number=gns, customer_name=str(r[1] or ""), contacts=str(r[2] or "") or None,
        delivery_method=str(r[5] or "") or None, test_type=test_type, report_option=report_option,
        result_y=str(r[8]) if r[8] is not None else None,
        result_mt=str(r[9]) if r[9] is not None else None,
        comments=comments, notes=notes,
    )


def _process_strelka(i: int, r: tuple) -> ProcessedRow:
    number_idx = 0
    if _is_near_empty(r, number_idx) or (r[1] is None and r[2] is None and r[3] is None):
        return ProcessedRow(sheet="Strelka", excel_row=i, action="skip_empty")

    gns = str(r[0]).strip()
    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист Strelka, строка {i}",
        f"номер пробирки: {r[2]}" if r[2] else None,
        f"оплата: {r[3]}" if r[3] else None,
        f"логистика: {r[4]}" if r[4] else None,
        f"YFULL: {r[6]}" if r[6] else None,
        f"ссылка: {r[7]}" if r[7] else None,
        f"покрытие: {r[8]}" if r[8] else None,
        f"заметки: {r[9]}" if r[9] else None,
    )
    return ProcessedRow(
        sheet="Strelka", excel_row=i, action="import",
        gns_number=gns, customer_name=str(r[1] or ""), test_type="STRELKA",
        report_option="Обычный", result_y=str(r[5]) if r[5] is not None else None,
        comments=comments,
    )


def _process_wgs(i: int, r: tuple) -> ProcessedRow:
    gns = str(r[0]).strip()
    test_type, kind = normalize_test_type(r[4])
    notes = []
    if kind == "unknown":
        notes.append(f"неизвестный тип теста: {r[4]!r}")

    bad_dates = 0
    sample_dt = safe_date(r[7])
    if is_problematic_date(r[7]):
        bad_dates += 1
        notes.append(f"дата передачи в лабу нераспознана: {r[7]!r} — оставлена пустой")
    issued_dt = None
    if isinstance(r[8], (datetime.datetime, datetime.date)):
        issued_dt = r[8] if isinstance(r[8], datetime.datetime) else datetime.datetime.combine(r[8], datetime.time())
    elif is_problematic_date(r[8]):
        bad_dates += 1
        notes.append(f"дата выдачи нераспознана: {r[8]!r} — оставлена пустой")

    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист WGS, строка {i}",
        f"контакты: {r[3]}" if r[3] else None,
        f"пробирки: {r[2]}" if r[2] else None,
        f"статус в Excel: {r[5]}" if r[5] else None,
        f"обработка ВМ: {r[6]}" if r[6] else None,
        f"ссылка на файлы: {r[9]}" if r[9] else None,
    )
    return ProcessedRow(
        sheet="WGS", excel_row=i, action="import" if kind != "unknown" else "import",
        gns_number=gns, customer_name=str(r[1] or ""), contacts=str(r[3] or "") or None,
        test_type=test_type or str(r[4]), report_option="Обычный",
        sample_received_at=sample_dt, client_issued_at=issued_dt,
        comments=comments, notes=notes, problematic_dates=bad_dates,
    )


# Особые правила SEM: M-1..M-5 (пара Y50+мтДНК одного человека) и SE2/SEZ.
_SEM_MTDNA_SUFFIX_NUMBERS = {"M-1", "M-2", "M-3", "M-4", "M-5"}
_sem_seen_numbers: dict[str, int] = {}


def _process_sem(i: int, r: tuple) -> ProcessedRow:
    global _sem_seen_numbers
    number_idx = 0
    if _is_near_empty(r, number_idx):
        return ProcessedRow(sheet="SEM", excel_row=i, action="skip_empty")

    raw_num = str(r[0]).strip()
    test_type, kind = normalize_test_type(r[4])

    gns = raw_num
    group_key = None
    notes = []

    if raw_num in _SEM_MTDNA_SUFFIX_NUMBERS:
        occurrence = _sem_seen_numbers.get(raw_num, 0) + 1
        _sem_seen_numbers[raw_num] = occurrence
        group_key = f"SEM-pair-{raw_num}"
        if occurrence == 2:
            gns = f"{raw_num}-мтДНК"
            notes.append(f"второе вхождение номера {raw_num!r} -> {gns!r} (мтДНК того же человека, один заказ)")
    elif raw_num == "SE2":
        occurrence = _sem_seen_numbers.get("SE2", 0) + 1
        _sem_seen_numbers["SE2"] = occurrence
        if occurrence == 2:
            gns = "SEZ"
            notes.append("второе вхождение номера 'SE2' (лабораторный код SMOL38) -> переномеровано в 'SEZ', отдельный заказ")

    bad_dates = 0
    sample_dt = safe_date(r[5])
    if is_problematic_date(r[5]):
        bad_dates += 1
        notes.append(f"дата сдачи образца нераспознана: {r[5]!r} — оставлена пустой")
    issued_dt = None
    if isinstance(r[6], (datetime.datetime, datetime.date)):
        issued_dt = r[6] if isinstance(r[6], datetime.datetime) else datetime.datetime.combine(r[6], datetime.time())
    elif is_problematic_date(r[6]):
        bad_dates += 1
        notes.append(f"дата выдачи нераспознана: {r[6]!r} — оставлена пустой")

    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист SEM, строка {i}",
        f"оплата клиентом: {r[2]}" if r[2] else None,
        f"статус в Excel: {r[3]}" if r[3] else None,
    )

    return ProcessedRow(
        sheet="SEM", excel_row=i, action="import",
        gns_number=gns, customer_name=str(r[1] or ""), test_type=test_type or str(r[4]),
        report_option="Обычный", sample_received_at=sample_dt, client_issued_at=issued_dt,
        comments=comments, notes=notes, group_key=group_key, problematic_dates=bad_dates,
    )


def _process_bash(i: int, r: tuple) -> ProcessedRow:
    test_type, kind = normalize_test_type(r[4])
    bad_dates = 0
    sample_dt = safe_date(r[5])
    notes = []
    if is_problematic_date(r[5]):
        bad_dates += 1
        notes.append(f"дата сдачи образца нераспознана: {r[5]!r} — оставлена пустой")
    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист BASH, строка {i}",
        f"оплата клиентом: {r[2]}" if r[2] else None,
        f"статус в Excel: {r[3]}" if r[3] else None,
    )
    return ProcessedRow(
        sheet="BASH", excel_row=i, action="import",
        gns_number=str(r[0]).strip(), customer_name=str(r[1] or ""),
        test_type=test_type or str(r[4]), report_option="Обычный",
        sample_received_at=sample_dt, result_y=str(r[6]) if r[6] is not None else None,
        comments=comments, notes=notes, problematic_dates=bad_dates,
    )


def _process_adg(i: int, r: tuple) -> ProcessedRow:
    test_type, kind = normalize_test_type(r[5])
    bad_dates = 0
    sample_dt = safe_date(r[6])
    notes = []
    if is_problematic_date(r[6]):
        bad_dates += 1
        notes.append(f"дата сдачи образца нераспознана: {r[6]!r} — оставлена пустой")
    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист ADG, строка {i}",
        f"оплата клиентом: {r[2]}" if r[2] else None,
        f"оплата в лабу: {r[3]}" if r[3] else None,
        f"статус в Excel: {r[4]}" if r[4] else None,
    )
    return ProcessedRow(
        sheet="ADG", excel_row=i, action="import",
        gns_number=str(r[0]).strip(), customer_name=str(r[1] or ""),
        test_type=test_type or str(r[5]), report_option="Обычный",
        sample_received_at=sample_dt, result_y=str(r[7]) if r[7] is not None else None,
        comments=comments, notes=notes, problematic_dates=bad_dates,
    )


def _process_rom(i: int, r: tuple) -> ProcessedRow:
    number_idx = 0
    if _is_near_empty(r, number_idx):
        return ProcessedRow(sheet="ROM", excel_row=i, action="skip_empty")

    raw_num = str(r[0]).strip()
    raw_type = r[5]
    name = r[1]
    notes = []

    # ROM-44 / ROM-45: цифра в поле ФИО, тип теста отсутствует -> решение: Y50 обеим
    if raw_type is None and isinstance(name, (int, float)):
        test_type = "Y50"
        notes.append(f"тип теста отсутствовал в исходнике — проставлен Y50 по решению пользователя; ФИО='{name}' (цифра, как в исходнике)")
        kind = "known"
    else:
        test_type, kind = normalize_test_type(raw_type)

    if kind == "deleted":
        return ProcessedRow(sheet="ROM", excel_row=i, action="delete_unsupported_type",
                             gns_number=raw_num, test_type=str(raw_type), comments=repr(r))

    bad_dates = 0
    sample_dt = safe_date(r[6])
    if is_problematic_date(r[6]):
        bad_dates += 1
        notes.append(f"дата сдачи образца нераспознана: {r[6]!r} — оставлена пустой")

    comments = _join_comments(
        f"источник: {SOURCE_FILE_LABEL}, лист ROM, строка {i}",
        f"оплата клиентом: {r[2]}" if r[2] else None,
        f"оплата в лабу: {r[3]}" if r[3] else None,
        f"статус в Excel: {r[4]}" if r[4] else None,
        f"результат Y: {r[7]}" if len(r) > 7 and r[7] else None,
        f"результат мтДНК: {r[8]}" if len(r) > 8 and r[8] else None,
    )
    return ProcessedRow(
        sheet="ROM", excel_row=i, action="import",
        gns_number=raw_num, customer_name=str(name if name is not None else ""),
        test_type=test_type or str(raw_type), report_option="Обычный",
        sample_received_at=sample_dt,
        result_y=str(r[7]) if len(r) > 7 and r[7] is not None else None,
        result_mt=str(r[8]) if len(r) > 8 and r[8] is not None else None,
        comments=comments, notes=notes, problematic_dates=bad_dates,
    )


_SHEET_PROCESSORS = {
    "Общий": _process_obshiy,
    "Strelka": _process_strelka,
    "WGS": _process_wgs,
    "SEM": _process_sem,
    "BASH": _process_bash,
    "ADG": _process_adg,
    "ROM": _process_rom,
}


def process_workbook(file_path: str) -> list[ProcessedRow]:
    """Читает все 7 листов и возвращает список обработанных строк
    (без записи в БД — чистая трансформация)."""
    global _sem_seen_numbers
    _sem_seen_numbers = {}

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    results: list[ProcessedRow] = []
    for sheet_name, processor in _SHEET_PROCESSORS.items():
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        data = [r for r in rows[1:] if not all(c is None for c in r)]
        for i, r in enumerate(data, start=2):
            results.append(processor(i, r))
    wb.close()
    return results


# ---------------------------------------------------------------------
# Фактический импорт обработанных строк в БД
# ---------------------------------------------------------------------

@dataclass
class ImportStats:
    orders_created: int = 0
    tests_created: int = 0
    by_type: dict = field(default_factory=dict)
    with_report: int = 0
    skipped_empty: int = 0
    deleted_unsupported_type: int = 0
    needs_manual_review: list = field(default_factory=list)  # (sheet, row, gns, reason)
    failed: list = field(default_factory=list)  # (sheet, row, gns, error)


def import_processed_rows(conn, processed: list[ProcessedRow], *, user_name: str = "historical-import") -> ImportStats:
    stats = ImportStats()
    groups: dict[str, int] = {}  # group_key -> order_id, для M-1..M-5

    for pr in processed:
        if pr.action == "skip_empty":
            stats.skipped_empty += 1
            continue
        if pr.action == "delete_unsupported_type":
            stats.deleted_unsupported_type += 1
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO legacy_excluded_tests
                   (source_sheet, source_row, original_gns_number, original_test_type,
                    raw_row_data, reason, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pr.sheet, pr.excel_row, pr.gns_number, pr.test_type, pr.comments,
                 "неподдерживаемый исторический тип продукта (решение пользователя при миграции)",
                 repo.now_iso()),
            )
            conn.execute("COMMIT")
            continue

        try:
            conn.execute("BEGIN IMMEDIATE")
            ts = repo.now_iso()

            order_id = groups.get(pr.group_key) if pr.group_key else None
            if order_id is None:
                cur = conn.execute(
                    """INSERT INTO orders
                       (order_no, order_status, customer_name, contacts, delivery_method,
                        source, source_raw, created_at, updated_at)
                       VALUES (?, 'Импортирован (историческая миграция)', ?, ?, ?, 'excel_import', ?, ?, ?)""",
                    (pr.gns_number, pr.customer_name, pr.contacts, pr.delivery_method,
                     f"{pr.sheet}:{pr.excel_row}", ts, ts),
                )
                order_id = cur.lastrowid
                stats.orders_created += 1
                if pr.group_key:
                    groups[pr.group_key] = order_id

            client_issued_iso = pr.client_issued_at.strftime("%Y-%m-%dT%H:%M:%S") if pr.client_issued_at else None
            sample_iso = pr.sample_received_at.isoformat() if pr.sample_received_at else None

            cur = conn.execute(
                """INSERT INTO tests
                   (order_id, gns_number, test_type, report_option, sample_received_at,
                    client_issued_at, result_y, result_mt, comments, is_historical,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (order_id, pr.gns_number, pr.test_type, pr.report_option, sample_iso,
                 client_issued_iso, pr.result_y, pr.result_mt, pr.comments, ts, ts),
            )
            test_id = cur.lastrowid
            repo.write_audit(
                conn, user_name=user_name, entity="test", entity_id=test_id,
                field=None, old_value=None,
                new_value=f"импортирован из {pr.sheet}:{pr.excel_row} ({pr.gns_number})",
                reason="историческая миграция Отчеты_2025-2026.xlsx",
            )
            conn.execute("COMMIT")

            stats.tests_created += 1
            stats.by_type[pr.test_type] = stats.by_type.get(pr.test_type, 0) + 1
            if pr.report_option == "С отчётом":
                stats.with_report += 1
            if pr.notes or pr.problematic_dates:
                stats.needs_manual_review.append((pr.sheet, pr.excel_row, pr.gns_number, "; ".join(pr.notes)))

        except Exception as exc:  # noqa: BLE001
            conn.execute("ROLLBACK")
            stats.failed.append((pr.sheet, pr.excel_row, pr.gns_number, str(exc)))

    return stats
