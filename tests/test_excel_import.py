"""
Тесты импорта Excel (раздел 16 ТЗ) — предпросмотр, дубли, ошибки, сохранение
исторических номеров без перенумерации.

Явно покрывает все пункты задачи 1 из финального ТЗ:
  - старые GNS, старые WGS, Strelka, исторический FULL LINE;
  - разные форматы дат (ДД.ММ.ГГГГ, datetime-объект Excel, ISO-текст);
  - пустые ячейки;
  - дубли (внутри файла и при повторном импорте);
  - несколько тестов одного заказа (общий order_no у двух строк);
  - сохранение исходных номеров без автоматической перенумерации.

ВАЖНО: реальный Excel-файл пользователя ещё не предоставлен. Ниже —
синтетический файл, построенный по формату, описанному в ТЗ (раздел 16),
воспроизводящий все требуемые случаи. Когда пользователь предоставит
реальный файл, его нужно прогнать через preview_excel()/import_excel()
и свериться со статистикой (см. инструкцию импорта в финальном пакете).
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openpyxl
import pytest

from app import db as dbmod
from app import importer


@pytest.fixture()
def conn(tmp_path):
    path = tmp_path / "test.db"
    c = dbmod.connect(path)
    dbmod.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def sample_xlsx(tmp_path):
    path = tmp_path / "historical.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["GNS", "№ заказа", "ФИО", "Контакты", "Тип теста", "Комплектация",
               "Дата образца", "Дата выдачи", "Комментарий"])

    # 1. Старый GNS, дата текстом ДД.ММ.ГГГГ
    ws.append(["GNS010001", "OLD-001", "Петров Пётр Петрович", "+7 900 111-11-11",
               "Y50", "Обычный", "05.03.2024", "10.04.2024", "старая база"])

    # 2. Strelka, дата выдачи пустая (тест не выдан), формат даты ДД.ММ.ГГГГ
    ws.append(["GNS010002", "OLD-002", "Сидорова Анна", "anna@example.com",
               "STRELKA", "С отчётом", "01.02.2024", "", ""])

    # 3. Старый WGS-номер (не GNS-формат — сохраняется как есть)
    ws.append(["WGS-0007", "OLD-003", "Кузнецов Олег", "+7 900 222-22-22",
               "WGS 30X", "Обычный", "10.01.2024", "01.03.2024", ""])

    # 4. Дубль строки 1 (тот же GNS) — должен быть пропущен как дубль, не ошибка
    ws.append(["GNS010001", "OLD-001", "Петров Пётр Петрович", "+7 900 111-11-11",
               "Y50", "Обычный", "05.03.2024", "10.04.2024", "дубль в исходнике"])

    # 5. Пустой GNS -> ошибка, строка не теряется, уходит в отчёт об ошибках
    ws.append(["", "OLD-005", "Без номера", "", "Y37", "Обычный", "01.01.2024", "", "нет GNS"])

    # 6. Исторический FULL LINE — импортируется как историческая запись "как есть"
    #    (раздел 0: "Исторические FULL LINE можно импортировать как исторические записи")
    ws.append(["FL-000123", "OLD-006", "Волкова Мария", "+7 900 333-33-33",
               "FULL LINE", "Обычный", "15.05.2023", "20.06.2023", "исторический FULL LINE"])

    # 7-8. Несколько тестов ОДНОГО заказа (общий № заказа, разные GNS) — Y50 + mtDNA
    ws.append(["GNS010010", "OLD-010", "Общий Клиент", "+7 900 444-44-44",
               "Y50", "С отчётом", "01.06.2024", "", ""])
    ws.append(["GNS010011", "OLD-010", "Общий Клиент", "+7 900 444-44-44",
               "MTDNA", "С отчётом", "01.06.2024", "", ""])

    # 9. Дата образца как реальный datetime-объект Excel (не текст)
    ws.append(["GNS010020", "OLD-020", "Дата Датовна", "", "Y50", "Обычный",
               datetime(2024, 7, 15), "", "дата как объект datetime Excel"])

    # 10. Дата в формате ISO-текст (альтернативный формат, встречается в выгрузках)
    ws.append(["GNS010021", "OLD-021", "Исо Датова", "", "MTDNA", "Обычный",
               "2024-08-01", "", "дата в ISO-текстовом формате"])

    wb.save(path)
    return path


def test_preview_shows_total_rows_before_import(sample_xlsx):
    """Задача 1: предпросмотр должен показывать 'всего строк' ДО фактического импорта."""
    before_mtime = sample_xlsx.stat().st_mtime
    before_size = sample_xlsx.stat().st_size
    preview = importer.preview_excel(str(sample_xlsx))
    assert preview.total_rows == 10
    assert preview.column_mapping["gns_number"] == "GNS"
    # предпросмотр не должен изменять исходный файл
    assert sample_xlsx.stat().st_mtime == before_mtime
    assert sample_xlsx.stat().st_size == before_size


def test_import_counts_imported_duplicates_and_errors(conn, sample_xlsx):
    """Задача 1: статистика после импорта — импортировано/дубли/ошибки."""
    preview = importer.preview_excel(str(sample_xlsx))
    result = importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)

    assert result.total_rows == 10
    assert result.errors == 1          # строка 5 — без GNS
    assert result.skipped_duplicates == 1  # строка 4 — дубль GNS010001
    assert result.imported == 8        # все остальные валидные строки


def test_old_gns_numbers_preserved_exactly(conn, sample_xlsx):
    """Старые GNS сохраняются как есть, без изменений формата."""
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    row = conn.execute("SELECT * FROM tests WHERE gns_number='GNS010001'").fetchone()
    assert row is not None
    assert row["is_historical"] == 1
    assert row["test_type"] == "Y50"


def test_old_wgs_number_preserved_exactly(conn, sample_xlsx):
    """Старые номера WGS (не в формате GNS) сохраняются как есть — не GNS-формат допустим,
    т.к. хранится в свободном текстовом поле gns_number."""
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    row = conn.execute("SELECT * FROM tests WHERE gns_number='WGS-0007'").fetchone()
    assert row is not None
    assert row["test_type"] == "WGS 30X"
    assert row["is_historical"] == 1


def test_strelka_imported_with_report_option(conn, sample_xlsx):
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    row = conn.execute("SELECT * FROM tests WHERE gns_number='GNS010002'").fetchone()
    assert row is not None
    assert row["test_type"] == "STRELKA"
    assert row["report_option"] == "С отчётом"
    assert row["client_issued_at"] is None  # дата выдачи пустая -> не выдан


def test_historical_full_line_imported_as_is_not_split(conn, sample_xlsx):
    """Раздел 0: исторический FULL LINE импортируется КАК ЕСТЬ (одна запись),
    в отличие от НОВЫХ заказов, где FULL LINE разворачивается в 2 теста через
    product_mappings. Импорт истории не должен пытаться разбирать комплект."""
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    row = conn.execute("SELECT * FROM tests WHERE gns_number='FL-000123'").fetchone()
    assert row is not None
    assert row["test_type"] == "FULL LINE"
    assert row["is_historical"] == 1
    # это ОДНА тестовая запись (историческая), а не две
    count = conn.execute(
        "SELECT COUNT(*) c FROM tests WHERE order_id=?", (row["order_id"],)
    ).fetchone()["c"]
    assert count == 1


def test_multiple_tests_same_order_no_get_separate_gns(conn, sample_xlsx):
    """Несколько тестов одного заказа (общий № заказа OLD-010) — раздельные GNS."""
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    rows = conn.execute(
        """SELECT t.* FROM tests t JOIN orders o ON o.order_id = t.order_id
           WHERE o.order_no = 'OLD-010'"""
    ).fetchall()
    assert len(rows) == 2
    types = {r["test_type"] for r in rows}
    assert types == {"Y50", "MTDNA"}
    assert len({r["gns_number"] for r in rows}) == 2


def test_date_formats_all_parsed_correctly(conn, sample_xlsx):
    """Разные форматы дат: текст ДД.ММ.ГГГГ, объект datetime Excel, текст ISO."""
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)

    row_text_date = conn.execute("SELECT * FROM tests WHERE gns_number='GNS010001'").fetchone()
    assert row_text_date["sample_received_at"] == "2024-03-05"

    row_datetime_obj = conn.execute("SELECT * FROM tests WHERE gns_number='GNS010020'").fetchone()
    assert row_datetime_obj["sample_received_at"] == "2024-07-15"

    row_iso_text = conn.execute("SELECT * FROM tests WHERE gns_number='GNS010021'").fetchone()
    assert row_iso_text["sample_received_at"] == "2024-08-01"


def test_empty_cells_do_not_break_import(conn, sample_xlsx):
    """Пустые ячейки (контакты, комментарий, дата выдачи) не должны приводить к ошибке."""
    preview = importer.preview_excel(str(sample_xlsx))
    result = importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    row = conn.execute("SELECT * FROM tests WHERE gns_number='GNS010002'").fetchone()
    assert row is not None  # импортировалась несмотря на пустые контакты/дату выдачи/комментарий
    assert result.errors == 1  # ошибка только там, где реально нет GNS


def test_import_error_rows_are_not_lost(conn, sample_xlsx):
    """Задача 1: 'Ошибочные строки не терять' — уходят в import_errors, доступны для отчёта."""
    preview = importer.preview_excel(str(sample_xlsx))
    result = importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)

    assert len(result.error_details) == 1
    db_errors = conn.execute("SELECT * FROM import_errors").fetchall()
    assert len(db_errors) == 1
    assert "GNS" in db_errors[0]["error_message"]
    assert "OLD-005" in db_errors[0]["raw_row"]  # исходные данные строки сохранены


def test_reimporting_same_file_creates_no_duplicates_and_no_renumbering(conn, sample_xlsx):
    """Повторный импорт того же файла: 0 новых записей, номера не меняются
    (задача 1: 'отсутствие автоматической перенумерации исторических тестов')."""
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    gns_before = {r["gns_number"] for r in conn.execute("SELECT gns_number FROM tests").fetchall()}

    result2 = importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)

    gns_after = {r["gns_number"] for r in conn.execute("SELECT gns_number FROM tests").fetchall()}
    assert gns_before == gns_after  # номера не изменились и не перегенерировались
    assert result2.imported == 0
    assert result2.skipped_duplicates == 9  # все 9 строк с GNS теперь дубли (включая дубль внутри файла)
    total_tests = conn.execute("SELECT COUNT(*) c FROM tests").fetchone()["c"]
    assert total_tests == 8  # не выросло после повторного импорта


def test_source_excel_file_not_modified_by_import(conn, sample_xlsx):
    """Задача 1 / раздел 16: 'Импорт не должен менять исходный Excel'."""
    before_bytes = sample_xlsx.read_bytes()
    preview = importer.preview_excel(str(sample_xlsx))
    importer.import_excel(conn, str(sample_xlsx), preview.column_mapping)
    after_bytes = sample_xlsx.read_bytes()
    assert before_bytes == after_bytes
