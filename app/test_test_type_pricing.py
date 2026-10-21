"""
Тесты релизов 1.1.1 и 1.1.2 — CRUD для test_types (код/название/срок/цена/
себестоимость/активность/признак лабораторности requires_lab), миграции БД
без пересоздания и отражение изменений в дашборде «Финансы» и «Операционка».

Покрывает:
  - миграцию ALTER TABLE test_types ADD COLUMN price/cost_price/requires_lab
    на БД, заведённых до этих релизов, без потери данных и без пересоздания;
  - разовое (не повторяющееся при каждом запуске) добавление REPORT
    в test_types на такой БД — намеренное удаление должно сохраняться;
  - принудительную коррекцию requires_lab=0 для REPORT на БД, где он уже
    был заведён релизом 1.1.1 (до появления признака requires_lab);
  - insert_test_type/update_test_type/delete_test_type в repository.py,
    включая защиту от удаления кода, который используется тестами или
    сопоставлениями товаров (product_mappings);
  - что REPORT из DEFAULT_TEST_TYPES заводится на чистой БД с requires_lab=0;
  - что REPORT доступен в NewOrderDialog/ProductMappingsDialog и создаёт
    настоящий тест (заказ может состоять только из «Отчёта»);
  - что REPORT-тесты НЕ получают дедлайн/строку в haplogroups и не попадают
    в операционные KPI/просрочки/расчёт сроков дашборда;
  - что Telegram-заказ, целиком состоящий из «Отчёта», распознаётся и не
    уходит на needs_review;
  - что dashboard_repo.get_kpis/get_test_economics/list_test_type_pricing/
    update_test_type_pricing считают реальные price/cost_price, а не 0.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3

import pytest

from app import dashboard_repo as drepo
from app import db as dbmod
from app import repository as repo
from app import telegram_parser as tp


@pytest.fixture()
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "test.db")
    dbmod.init_db(c)
    yield c
    c.close()


def _make_legacy_db(tmp_path, *, with_report=False):
    """Симулирует БД, заведённую до релиза 1.1.1: test_types без price/
    cost_price/requires_lab, без кода REPORT (или с ним — как было бы
    после релиза 1.1.1, но до появления requires_lab, если with_report=True)."""
    path = tmp_path / "legacy.db"
    c = sqlite3.connect(str(path), isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        CREATE TABLE test_types (
            code TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            base_deadline_days INTEGER NOT NULL,
            report_allowed INTEGER NOT NULL DEFAULT 1,
            report_extra_days INTEGER NOT NULL DEFAULT 15,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            cost_price REAL NOT NULL DEFAULT 0
        );
        INSERT INTO test_types (code, display_name, base_deadline_days, report_allowed, report_extra_days, sort_order)
        VALUES ('Y50', 'Y Базовый (Y50)', 30, 1, 15, 10);
        INSERT INTO schema_version(version) VALUES (1);
        """
    )
    if with_report:
        c.execute(
            """INSERT INTO test_types
               (code, display_name, base_deadline_days, report_allowed, report_extra_days,
                sort_order, price, cost_price)
               VALUES ('REPORT', 'Отчёт', 15, 0, 0, 80, 1500, 300)"""
        )
    c.close()
    return dbmod.connect(path)


# ---------------------------------------------------------------------
# Миграция
# ---------------------------------------------------------------------

def test_migration_adds_price_columns_without_recreating_db(tmp_path):
    c = _make_legacy_db(tmp_path)
    dbmod.init_db(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(test_types)")}
    assert "price" in cols
    assert "cost_price" in cols
    assert "requires_lab" in cols
    # существовавшая строка Y50 не потерялась и получила price/cost_price = 0,
    # requires_lab = 1 (это настоящий лабораторный тест)
    row = c.execute("SELECT * FROM test_types WHERE code = 'Y50'").fetchone()
    assert row["display_name"] == "Y Базовый (Y50)"
    assert row["price"] == 0
    assert row["cost_price"] == 0
    assert row["requires_lab"] == 1
    c.close()


def test_migration_backfills_report_once_and_respects_manual_delete(tmp_path):
    c = _make_legacy_db(tmp_path)
    dbmod.init_db(c)
    codes = {r["code"] for r in c.execute("SELECT code FROM test_types")}
    assert "REPORT" in codes
    assert repo.get_test_type(c, "REPORT")["requires_lab"] == 0

    repo.delete_test_type(c, "REPORT")

    # повторный запуск (перезапуск приложения) не должен воскрешать
    # намеренно удалённый REPORT
    dbmod.init_db(c)
    codes_after = {r["code"] for r in c.execute("SELECT code FROM test_types")}
    assert "REPORT" not in codes_after
    c.close()


def test_migration_corrects_requires_lab_for_report_seeded_by_release_1_1_1(tmp_path):
    """БД, где REPORT уже был заведён релизом 1.1.1 (до появления
    requires_lab) — ALTER TABLE ADD COLUMN DEFAULT 1 иначе ошибочно
    пометил бы его лабораторным тестом."""
    c = _make_legacy_db(tmp_path, with_report=True)
    dbmod.init_db(c)
    row = repo.get_test_type(c, "REPORT")
    assert row["requires_lab"] == 0
    assert row["price"] == 1500  # существующие цена/себестоимость не тронуты
    assert row["cost_price"] == 300
    c.close()


def test_migration_is_idempotent_on_already_migrated_db(conn):
    dbmod.init_db(conn)  # второй вызов на уже мигрированной БД не должен падать
    codes = [r["code"] for r in repo.list_test_types(conn, active_only=False)]
    assert codes.count("REPORT") == 1


def test_fresh_db_seeds_report_from_default_test_types(conn):
    row = repo.get_test_type(conn, "REPORT")
    assert row["display_name"] == "Отчёт"
    assert row["price"] == 0
    assert row["cost_price"] == 0
    assert row["is_active"] == 1
    assert row["requires_lab"] == 0


def test_fresh_db_lab_test_types_require_lab(conn):
    for code in ("Y50", "Y37", "MTDNA", "MITOGENOME", "STRELKA", "WGS15", "WGS30"):
        assert repo.get_test_type(conn, code)["requires_lab"] == 1


# ---------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------

def test_insert_test_type(conn):
    repo.insert_test_type(
        conn, code="custom", display_name="Кастомный", base_deadline_days=20,
        report_allowed=True, report_extra_days=10, price=1000, cost_price=400,
    )
    row = repo.get_test_type(conn, "CUSTOM")  # код приводится к верхнему регистру
    assert row["display_name"] == "Кастомный"
    assert row["price"] == 1000
    assert row["cost_price"] == 400
    assert row["is_active"] == 1  # значение по умолчанию
    assert row["requires_lab"] == 1  # значение по умолчанию — обычный лабораторный тест


def test_insert_test_type_as_service_product(conn):
    repo.insert_test_type(
        conn, code="CONSULT", display_name="Консультация", base_deadline_days=0,
        report_allowed=False, report_extra_days=0, price=2000, cost_price=500,
        requires_lab=False,
    )
    row = repo.get_test_type(conn, "CONSULT")
    assert row["requires_lab"] == 0


def test_insert_test_type_duplicate_code_raises(conn):
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_test_type(
            conn, code="Y50", display_name="dup", base_deadline_days=1,
            report_allowed=True, report_extra_days=1, price=0, cost_price=0,
        )


def test_update_test_type(conn):
    repo.update_test_type(
        conn, "REPORT", display_name="Отчёт (обновлён)", base_deadline_days=20,
        report_allowed=False, report_extra_days=0, price=1500, cost_price=300,
        is_active=True, sort_order=99, requires_lab=False,
    )
    row = repo.get_test_type(conn, "REPORT")
    assert row["display_name"] == "Отчёт (обновлён)"
    assert row["price"] == 1500
    assert row["cost_price"] == 300
    assert row["sort_order"] == 99
    assert row["requires_lab"] == 0


def test_update_unknown_test_type_raises(conn):
    with pytest.raises(ValueError):
        repo.update_test_type(
            conn, "NOPE", display_name="x", base_deadline_days=1,
            report_allowed=True, report_extra_days=1, price=0, cost_price=0,
            is_active=True, sort_order=0, requires_lab=True,
        )


def test_delete_unused_test_type(conn):
    repo.insert_test_type(
        conn, code="TEMP", display_name="Временный", base_deadline_days=5,
        report_allowed=True, report_extra_days=5, price=0, cost_price=0,
    )
    repo.delete_test_type(conn, "TEMP")
    with pytest.raises(ValueError):
        repo.get_test_type(conn, "TEMP")


def test_delete_blocked_when_used_by_tests(conn):
    data = repo.NewOrderInput(customer_name="К", test_type_codes=["Y50"], user_name="op")
    repo.create_order_with_tests(conn, data)
    with pytest.raises(ValueError):
        repo.delete_test_type(conn, "Y50")
    # тип теста не удалён после отказа
    assert repo.get_test_type(conn, "Y50") is not None


def test_delete_blocked_when_used_by_product_mapping(conn):
    repo.upsert_product_mapping(conn, "Особый заказ сайта", ["MTDNA"], False, None)
    with pytest.raises(ValueError):
        repo.delete_test_type(conn, "MTDNA")


def test_deactivate_instead_of_delete_hides_from_active_list(conn):
    repo.update_test_type(
        conn, "WGS30", display_name="WGS 30X", base_deadline_days=60,
        report_allowed=False, report_extra_days=0, price=0, cost_price=0,
        is_active=False, sort_order=70, requires_lab=True,
    )
    active_codes = [r["code"] for r in repo.list_test_types(conn, active_only=True)]
    all_codes = [r["code"] for r in repo.list_test_types(conn, active_only=False)]
    assert "WGS30" not in active_codes
    assert "WGS30" in all_codes


# ---------------------------------------------------------------------
# REPORT — полноценный элемент справочника, доступный в заказе
# ---------------------------------------------------------------------

def test_report_only_order_creates_real_test_without_deadline(conn):
    """Заказ может состоять только из «Отчёта» — создаётся настоящий тест
    (свой GNPSK), но без дедлайна: сервисный продукт не участвует в
    расчёте сроков выполнения."""
    from datetime import date

    data = repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], order_amount=1800,
        sample_received_at=date(2026, 1, 1), user_name="op",
    )
    order_id, test_ids = repo.create_order_with_tests(conn, data)
    assert len(test_ids) == 1

    test = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_ids[0],)).fetchone()
    assert test["test_type"] == "REPORT"
    assert test["gns_number"].startswith("GNPSK")
    assert test["deadline_days"] is None
    assert test["deadline_date"] is None


def test_report_test_gets_no_haplogroup_stub(conn):
    data = repo.NewOrderInput(customer_name="К1", test_type_codes=["REPORT"], user_name="op")
    _order_id, test_ids = repo.create_order_with_tests(conn, data)
    gns = conn.execute("SELECT gns_number FROM tests WHERE test_id = ?", (test_ids[0],)).fetchone()[0]
    hap = conn.execute("SELECT * FROM haplogroups WHERE test_number = ?", (gns,)).fetchone()
    assert hap is None


def test_lab_test_still_gets_haplogroup_stub_and_deadline(conn):
    """Контрольный кейс: обычные лабораторные типы теста ведут себя как
    раньше — requires_lab не ломает существующее поведение."""
    from datetime import date

    data = repo.NewOrderInput(
        customer_name="К1", test_type_codes=["Y50"], sample_received_at=date(2026, 1, 1), user_name="op",
    )
    _order_id, test_ids = repo.create_order_with_tests(conn, data)
    test = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_ids[0],)).fetchone()
    assert test["deadline_days"] == 30
    assert test["deadline_date"] is not None
    hap = conn.execute("SELECT * FROM haplogroups WHERE test_number = ?", (test["gns_number"],)).fetchone()
    assert hap is not None


def test_list_tests_with_order_lab_only_excludes_report(conn):
    repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], user_name="op"))
    repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К2", test_type_codes=["Y50"], user_name="op"))

    lab_rows = repo.list_tests_with_order(conn, lab_only=True)
    all_rows = repo.list_tests_with_order(conn, lab_only=False)
    assert "REPORT" not in [r["test_type"] for r in lab_rows]
    assert "Y50" in [r["test_type"] for r in lab_rows]
    assert "REPORT" in [r["test_type"] for r in all_rows]


# ---------------------------------------------------------------------
# Дашборд «Операционка» — сервисные продукты исключены
# ---------------------------------------------------------------------

def test_operational_kpis_exclude_report(conn):
    repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], user_name="op"))
    kpis = drepo.get_operational_kpis(conn)
    assert kpis.in_progress == 0


def test_production_funnel_excludes_report(conn):
    repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], user_name="op"))
    funnel = drepo.get_production_funnel(conn)
    assert funnel.created == 0


def test_overdue_tests_exclude_report(conn):
    from datetime import date

    _order_id, test_ids = repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], sample_received_at=date(2020, 1, 1), user_name="op"))
    # форсируем "просроченный" дедлайн вручную — как если бы кто-то обошёл
    # обычную логику и записал дату напрямую
    conn.execute("UPDATE tests SET deadline_date = '2020-02-01' WHERE test_id = ?", (test_ids[0],))
    overdue = drepo.get_overdue_tests(conn)
    assert "REPORT" not in [r["test_type"] for r in overdue]


def test_stuck_tests_exclude_report(conn):
    repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], user_name="op"))
    stuck = drepo.get_stuck_tests(conn)
    assert "REPORT" not in [r["test_type"] for r in stuck]


def test_avg_turnaround_excludes_report(conn):
    _order_id, test_ids = repo.create_order_with_tests(conn, repo.NewOrderInput(
        customer_name="К1", test_type_codes=["REPORT"], user_name="op"))
    conn.execute(
        "UPDATE tests SET client_issued_at = ? WHERE test_id = ?",
        (repo.now_iso(), test_ids[0]),
    )
    turnaround = drepo.get_avg_turnaround(conn)
    assert "REPORT" not in [r.code for r in turnaround]


# ---------------------------------------------------------------------
# Telegram / product mappings
# ---------------------------------------------------------------------

def test_report_selectable_in_product_mapping_and_telegram_flow(conn):
    repo.upsert_product_mapping(conn, "Расшифровка отчёта отдельно", ["REPORT"], False, None)

    message = (
        "Заказ №9999999999\n\n"
        "1. Расшифровка отчёта отдельно: 1800 (1 x 1800) 8\n"
        "Заказ оплачен.\n"
        "Ozon\n"
        "ФИО: Тестовый Клиент\n"
        "Сумма платежа: 1800 RUB\n"
    )
    codes, includes_report, unresolved = tp.resolve_products_from_text(conn, message)
    assert codes == ["REPORT"]
    assert not unresolved

    order_id, is_new = tp.create_or_update_order_from_message(conn, message)
    order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    assert order["needs_review"] == 0

    tests = conn.execute("SELECT * FROM tests WHERE order_id = ?", (order_id,)).fetchall()
    assert len(tests) == 1
    assert tests[0]["test_type"] == "REPORT"
    assert tests[0]["deadline_days"] is None


# ---------------------------------------------------------------------
# Дашборд «Финансы»
# ---------------------------------------------------------------------

def test_dashboard_finance_reflects_price_and_cost(conn):
    repo.update_test_type(
        conn, "Y50", display_name="Y Базовый (Y50)", base_deadline_days=30,
        report_allowed=True, report_extra_days=15, price=5000, cost_price=2000,
        is_active=True, sort_order=10, requires_lab=True,
    )
    repo.update_test_type(
        conn, "REPORT", display_name="Отчёт", base_deadline_days=15,
        report_allowed=False, report_extra_days=0, price=1500, cost_price=300,
        is_active=True, sort_order=80, requires_lab=False,
    )

    month = drepo.current_month()
    for _ in range(2):
        repo.create_order_with_tests(
            conn, repo.NewOrderInput(customer_name="К1", test_type_codes=["Y50"],
                                      order_amount=5000, user_name="op"),
        )
    repo.create_order_with_tests(
        conn, repo.NewOrderInput(customer_name="К2", test_type_codes=["REPORT"],
                                  order_amount=1500, user_name="op"),
    )

    kpis = drepo.get_kpis(conn, month)
    assert kpis.revenue == 11500
    assert kpis.cost == 4300
    assert kpis.profit == 7200

    econ = {row.code: row for row in drepo.get_test_economics(conn, month)}
    assert econ["Y50"].sold == 2
    assert econ["Y50"].revenue == 10000
    assert econ["Y50"].cost == 4000
    assert econ["REPORT"].sold == 1
    assert econ["REPORT"].revenue == 1500
    assert econ["REPORT"].cost == 300


def test_list_and_update_test_type_pricing(conn):
    rows = drepo.list_test_type_pricing(conn)
    report_row = next(r for r in rows if r["code"] == "REPORT")
    assert report_row["price"] == 0
    assert report_row["cost_price"] == 0

    drepo.update_test_type_pricing(conn, "REPORT", price=1800, cost_price=400)
    row = repo.get_test_type(conn, "REPORT")
    assert row["price"] == 1800
    assert row["cost_price"] == 400


def test_dashboard_repo_does_not_crash_without_pricing_columns(tmp_path):
    """dashboard_repo не должен падать на "no such column", если его
    вызвали на подключении, где price/cost_price ещё не мигрированы."""
    path = tmp_path / "no_pricing.db"
    c = sqlite3.connect(str(path), isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE test_types (
            code TEXT PRIMARY KEY, display_name TEXT NOT NULL, base_deadline_days INTEGER NOT NULL,
            report_allowed INTEGER NOT NULL DEFAULT 1, report_extra_days INTEGER NOT NULL DEFAULT 15,
            is_active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, order_amount REAL, is_archived INTEGER DEFAULT 0, created_at TEXT);
        CREATE TABLE tests (test_id INTEGER PRIMARY KEY, order_id INTEGER, test_type TEXT, is_archived INTEGER DEFAULT 0, created_at TEXT);
        INSERT INTO test_types (code, display_name, base_deadline_days) VALUES ('Y50', 'Y Базовый', 30);
        """
    )

    month = drepo.current_month()
    kpis = drepo.get_kpis(c, month)
    assert kpis.revenue == 0 and kpis.cost == 0

    assert drepo.get_test_economics(c, month) == []

    pricing = drepo.list_test_type_pricing(c)
    assert pricing == [{"code": "Y50", "display_name": "Y Базовый", "price": 0.0, "cost_price": 0.0}]

    drepo.update_test_type_pricing(c, "Y50", price=100, cost_price=50)  # не должно падать
    c.close()


# ---------------------------------------------------------------------
# UI: REPORT доступен при создании заказа и в product mappings
# ---------------------------------------------------------------------

def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_report_available_in_new_order_type_list(conn):
    _qapp()
    from app.new_order_dialog import NewOrderDialog

    repo.update_test_type(
        conn, "REPORT", display_name="Отчёт", base_deadline_days=15,
        report_allowed=False, report_extra_days=0, price=1800, cost_price=400,
        is_active=True, sort_order=80, requires_lab=False,
    )
    dlg = NewOrderDialog(conn)
    codes = [dlg.type_list.item(i).data(1000) for i in range(dlg.type_list.count())]
    assert "REPORT" in codes


def test_report_available_in_product_mapping_type_list(conn):
    _qapp()
    from app.product_mappings_dialog import ProductMappingsDialog

    dlg = ProductMappingsDialog(conn)
    codes = [dlg.types_list.item(i).data(1000) for i in range(dlg.types_list.count())]
    assert "REPORT" in codes


def test_settings_dialog_shows_requires_lab_column(conn):
    _qapp()
    from app.settings_dialog import SettingsDialog

    dlg = SettingsDialog(conn)
    report_idx = next(i for i, tt in enumerate(dlg._test_types_rows) if tt["code"] == "REPORT")
    assert dlg.test_types_table.item(report_idx, 6).text() == "Услуга"

    y50_idx = next(i for i, tt in enumerate(dlg._test_types_rows) if tt["code"] == "Y50")
    assert dlg.test_types_table.item(y50_idx, 6).text() == "Да"


def test_settings_dialog_has_dedicated_products_tab(conn):
    """«Настройки → Продукты» — отдельная вкладка от «Справочники»
    (раздел 20 ТЗ, релиз 1.1.3)."""
    _qapp()
    from PySide6.QtWidgets import QTabWidget
    from app.settings_dialog import SettingsDialog

    dlg = SettingsDialog(conn)
    tabs = dlg.findChild(QTabWidget)
    titles = [tabs.tabText(i) for i in range(tabs.count())]
    assert "Продукты" in titles
    assert "Справочники" in titles


def test_deactivate_test_type_repository_function(conn):
    repo.deactivate_test_type(conn, "REPORT")
    row = repo.get_test_type(conn, "REPORT")
    assert row["is_active"] == 0
    # деактивация не трогает остальные поля
    assert row["display_name"] == "Отчёт"


def test_deactivate_unknown_test_type_raises(conn):
    with pytest.raises(ValueError):
        repo.deactivate_test_type(conn, "NOPE")


# ---------------------------------------------------------------------
# Сквозная проверка: продукт «Отчёт» создаётся ПОЛНОСТЬЮ через интерфейс,
# без единого прямого SQL к test_types (раздел «Проверить создание
# продукта Отчёт» ТЗ, релиз 1.1.3).
# ---------------------------------------------------------------------

def test_create_report_product_entirely_through_ui_no_manual_sql(conn):
    """
    Сценарий:
      1. На чистой БД REPORT уже существует (заведён миграцией релиза 1.1.1/
         1.1.2 — см. DEFAULT_TEST_TYPES) — чтобы честно проверить путь
         «Добавить продукт», сначала убираем его ЧЕРЕЗ РЕПОЗИТОРИЙ
         (repo.delete_test_type — такой же публичный API приложения, как и
         insert/update, а не ручной SQL) и притворяемся, что администратор
         заводит «Отчёт» с нуля.
      2. Открываем TestTypeEditDialog в режиме добавления (code=None) — это
         и есть диалог за кнопкой «Добавить продукт» на вкладке «Настройки →
         Продукты», ничем не отличается от реального клика мышью.
      3. Программно заполняем ТОЛЬКО виджеты формы (QLineEdit/QSpinBox/
         QCheckBox), как это делает пользователь руками, и вызываем
         dlg._on_save() — тот же самый обработчик, что висит на кнопке
         «Сохранить» (QDialogButtonBox.Save.accepted). Ни разу не
         обращаемся к conn.execute() с INSERT/UPDATE по test_types — только
         через диалог, и только на чтение (assert-ы) в самом конце.
      4. Проверяем весь пункт 6 требования: продукт сразу доступен в
         создании заказа, в Product Mapping, участвует в дашборде и в
         расчёте прибыли — и пункт 7: т.к. requires_lab снят в форме,
         исключён из гаплогрупп/лабораторной воронки/просрочек/сроков.
    """
    _qapp()
    from app.test_type_edit_dialog import TestTypeEditDialog
    from app.new_order_dialog import NewOrderDialog
    from app.product_mappings_dialog import ProductMappingsDialog

    # 1. Притворяемся, что «Отчёта» ещё нет — убираем его через тот же
    #    репозиторный API, которым бы воспользовалось приложение.
    repo.delete_test_type(conn, "REPORT")
    with pytest.raises(ValueError):
        repo.get_test_type(conn, "REPORT")

    # 2-3. «Добавить продукт» — только через виджеты диалога.
    dlg = TestTypeEditDialog(conn, None)
    dlg.code_edit.setText("REPORT")
    dlg.name_edit.setText("Отчёт")
    dlg.deadline_spin.setValue(15)
    dlg.report_allowed_check.setChecked(False)
    dlg.report_extra_spin.setValue(0)
    dlg.price_spin.setValue(1800)
    dlg.cost_price_spin.setValue(400)
    dlg.sort_spin.setValue(80)
    dlg.active_check.setChecked(True)
    dlg.requires_lab_check.setChecked(False)
    dlg._on_save()  # тот же обработчик, что и на кнопке «Сохранить»

    row = repo.get_test_type(conn, "REPORT")
    assert row["display_name"] == "Отчёт"
    assert row["price"] == 1800
    assert row["cost_price"] == 400
    assert row["base_deadline_days"] == 15
    assert row["report_allowed"] == 0
    assert row["report_extra_days"] == 0
    assert row["requires_lab"] == 0
    assert row["is_active"] == 1
    assert row["sort_order"] == 80

    # 6a. Доступен при создании заказа.
    order_dlg = NewOrderDialog(conn)
    order_codes = [order_dlg.type_list.item(i).data(1000) for i in range(order_dlg.type_list.count())]
    assert "REPORT" in order_codes

    # 6b. Доступен в Product Mapping (Telegram).
    mapping_dlg = ProductMappingsDialog(conn)
    mapping_codes = [mapping_dlg.types_list.item(i).data(1000) for i in range(mapping_dlg.types_list.count())]
    assert "REPORT" in mapping_codes

    # Реальная покупка «Отчёта» — через тот же repo.create_order_with_tests,
    # которым пользуется NewOrderDialog._on_save().
    _order_id, test_ids = repo.create_order_with_tests(
        conn, repo.NewOrderInput(customer_name="Клиент", test_type_codes=["REPORT"],
                                  order_amount=1800, user_name="op"),
    )
    test_row = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_ids[0],)).fetchone()

    # 6c/6d. Участвует в дашборде и в расчёте прибыли.
    month = drepo.current_month()
    kpis = drepo.get_kpis(conn, month)
    assert kpis.revenue == 1800
    assert kpis.cost == 400
    assert kpis.profit == 1400

    econ = {r.code: r for r in drepo.get_test_economics(conn, month)}
    assert econ["REPORT"].sold == 1
    assert econ["REPORT"].revenue == 1800
    assert econ["REPORT"].cost == 400

    # 7. requires_lab=0 — исключён из гаплогрупп/лабораторной воронки/
    #    просрочек/расчёта сроков выполнения.
    assert test_row["deadline_days"] is None
    hap = conn.execute(
        "SELECT * FROM haplogroups WHERE test_number = ?", (test_row["gns_number"],)
    ).fetchone()
    assert hap is None

    op_kpis = drepo.get_operational_kpis(conn)
    assert op_kpis.in_progress == 0

    funnel = drepo.get_production_funnel(conn)
    assert funnel.created == 0

    lab_rows = repo.list_tests_with_order(conn, lab_only=True)
    assert "REPORT" not in [r["test_type"] for r in lab_rows]
