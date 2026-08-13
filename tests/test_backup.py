"""Тесты резервного копирования и восстановления (раздел 19 ТЗ)."""
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import backup as bk
from app import db as dbmod
from app import repository as repo


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "db" / "genopoisk.db"
    conn = dbmod.connect(p)
    dbmod.init_db(conn)
    order = repo.NewOrderInput(customer_name="Тестовый клиент", test_type_codes=["Y50"],
                                sample_received_at=date(2026, 1, 1))
    repo.create_order_with_tests(conn, order)
    conn.close()
    return p


def test_backup_filename_format(db_path, tmp_path):
    backup_folder = tmp_path / "backups"
    dest = bk.create_backup(db_path, backup_folder)
    assert dest.exists()
    assert dest.name.startswith("genopoisk_")
    assert dest.suffix == ".db"


def test_backup_does_not_overwrite_previous(db_path, tmp_path):
    backup_folder = tmp_path / "backups"
    b1 = bk.create_backup(db_path, backup_folder)
    b2 = bk.create_backup(db_path, backup_folder)
    assert b1 != b2
    assert b1.exists() and b2.exists()


def test_backup_content_is_valid_and_readable(db_path, tmp_path):
    backup_folder = tmp_path / "backups"
    dest = bk.create_backup(db_path, backup_folder)
    conn = dbmod.connect(dest)
    rows = conn.execute("SELECT * FROM tests").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["gns_number"] == "GNPSK000001"


def test_prune_keeps_only_n_most_recent(db_path, tmp_path):
    backup_folder = tmp_path / "backups"
    for _ in range(5):
        bk.create_backup(db_path, backup_folder)
        time.sleep(1.1)  # уникальные имена файлов (секундная точность)

    assert len(bk.list_backups(backup_folder)) == 5
    bk.prune_old_backups(backup_folder, keep_count=2)
    remaining = bk.list_backups(backup_folder)
    assert len(remaining) == 2


def test_restore_replaces_db_and_makes_pre_restore_snapshot(db_path, tmp_path):
    backup_folder = tmp_path / "backups"
    pre_restore_folder = tmp_path / "pre_restore"

    good_backup = bk.create_backup(db_path, backup_folder)  # состояние: 1 тест

    # "портим" текущую базу
    conn = dbmod.connect(db_path)
    order2 = repo.NewOrderInput(customer_name="Второй клиент", test_type_codes=["MTDNA"],
                                 sample_received_at=date(2026, 2, 1))
    repo.create_order_with_tests(conn, order2)
    assert conn.execute("SELECT COUNT(*) c FROM tests").fetchone()["c"] == 2
    conn.close()

    pre_backup = bk.restore_backup(good_backup, db_path, pre_restore_backup_folder=pre_restore_folder)

    # pre-restore backup сохранил "испорченное" состояние — ничего не потеряно
    assert pre_backup is not None
    pre_conn = dbmod.connect(pre_backup)
    assert pre_conn.execute("SELECT COUNT(*) c FROM tests").fetchone()["c"] == 2
    pre_conn.close()

    # база теперь соответствует восстановленному backup'у (1 тест)
    restored_conn = dbmod.connect(db_path)
    assert restored_conn.execute("SELECT COUNT(*) c FROM tests").fetchone()["c"] == 1
    restored_conn.close()


# ---------------------------------------------------------------------
# Задача 2: полноценный round-trip тест с реальными сущностями
# (заказы, несколько тестов одного заказа, GNPSK, даты, результаты,
# комментарии, audit log) + проверка, что backup НЕ содержит Bot Token.
# ---------------------------------------------------------------------

def test_full_round_trip_orders_tests_gnpsk_dates_results_comments_audit(tmp_path):
    """Рабочая БД -> backup -> изменение данных -> restore -> проверка полного восстановления."""
    db_path = tmp_path / "db" / "genopoisk.db"
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)

    # Заказ с двумя тестами (комплект), с результатами и комментарием
    order = repo.NewOrderInput(
        order_no="RT-2001", customer_name="Раунд Трипов Тест",
        contacts="+7 900 777-77-77", test_type_codes=["Y50", "MTDNA"],
        report_added=True, sample_received_at=date(2026, 3, 1),
        order_amount=20000.0, user_name="operator1",
    )
    order_id, test_ids = repo.create_order_with_tests(conn, order)
    y50_id, mtdna_id = test_ids

    repo.update_test_fields(
        conn, y50_id,
        {"result_y": "R1b-M269", "comments": "Особые пометки по Y50", "client_issued_at": "2026-04-10T12:00:00"},
        user_name="operator1", reason="выдача результата",
    )
    repo.update_test_fields(
        conn, mtdna_id,
        {"result_mt": "H1a1", "comments": "Особые пометки по mtDNA"},
        user_name="operator1",
    )

    gns_before = {r["gns_number"] for r in conn.execute("SELECT gns_number FROM tests").fetchall()}
    audit_count_before = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    # --- backup рабочей БД ---
    backup_folder = tmp_path / "backups"
    good_backup = bk.create_backup(db_path, backup_folder)

    # --- меняем/"портим" данные после backup ---
    repo.update_test_fields(conn, y50_id, {"comments": "ИСПОРЧЕНО ПОСЛЕ BACKUP"}, user_name="operator1")
    extra_order = repo.NewOrderInput(customer_name="Случайный лишний заказ", test_type_codes=["STRELKA"],
                                      sample_received_at=date(2026, 5, 1))
    repo.create_order_with_tests(conn, extra_order)
    conn.close()

    # --- restore из backup (с обязательным pre-restore backup'ом) ---
    pre_restore_folder = tmp_path / "pre_restore"
    pre_backup = bk.restore_backup(good_backup, db_path, pre_restore_backup_folder=pre_restore_folder)
    assert pre_backup is not None  # backup текущей (испорченной) базы сделан автоматически

    # --- проверка: восстановленная база идентична состоянию на момент backup ---
    restored = dbmod.connect(db_path)

    orders = restored.execute("SELECT * FROM orders WHERE order_no='RT-2001'").fetchall()
    assert len(orders) == 1
    assert orders[0]["customer_name"] == "Раунд Трипов Тест"

    tests = restored.execute("SELECT * FROM tests WHERE order_id=?", (order_id,)).fetchall()
    assert len(tests) == 2  # оба теста заказа восстановлены
    gns_after = {r["gns_number"] for r in tests}
    assert gns_after == gns_before  # GNPSK не изменились

    y50_restored = next(r for r in tests if r["test_type"] == "Y50")
    mtdna_restored = next(r for r in tests if r["test_type"] == "MTDNA")
    assert y50_restored["result_y"] == "R1b-M269"
    assert y50_restored["comments"] == "Особые пометки по Y50"  # НЕ "ИСПОРЧЕНО" — восстановлено к моменту backup
    assert y50_restored["client_issued_at"] == "2026-04-10T12:00:00"
    assert mtdna_restored["result_mt"] == "H1a1"
    assert mtdna_restored["comments"] == "Особые пометки по mtDNA"

    # "лишний" заказ, созданный ПОСЛЕ backup, не должен присутствовать
    extra = restored.execute("SELECT * FROM orders WHERE customer_name='Случайный лишний заказ'").fetchall()
    assert len(extra) == 0

    # audit log тоже восстановлен на момент backup (без записей, сделанных после)
    audit_count_restored = restored.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
    assert audit_count_restored == audit_count_before

    restored.close()

    # pre-restore snapshot сохранил "испорченное" состояние (ничего не потеряно безвозвратно)
    pre_conn = dbmod.connect(pre_backup)
    pre_y50 = pre_conn.execute("SELECT comments FROM tests WHERE test_id=?", (y50_id,)).fetchone()
    assert pre_y50["comments"] == "ИСПОРЧЕНО ПОСЛЕ BACKUP"
    pre_extra = pre_conn.execute("SELECT COUNT(*) c FROM orders WHERE customer_name='Случайный лишний заказ'").fetchone()
    assert pre_extra["c"] == 1
    pre_conn.close()


def test_backup_file_does_not_contain_bot_token_in_plaintext(tmp_path, monkeypatch):
    """Задача 2: backup не должен содержать Telegram Bot Token в открытом виде.

    Токен хранится ПОЛНОСТЬЮ отдельно от БД (см. app/secrets_store.py — отдельный
    JSON-файл в %APPDATA%/GENOPOISK_CRM/secrets/), поэтому backup БД (который
    является снимком только *.db через SQLite backup API) физически не может
    его содержать — секрет никогда не попадает ни в одну таблицу SQLite."""
    from app import secrets_store

    # подменяем каталог секретов на временный, чтобы не трогать реальный профиль пользователя
    fake_app_data = tmp_path / "appdata"
    monkeypatch.setattr(dbmod, "get_app_data_dir", lambda: fake_app_data / "GENOPOISK_CRM" / "data")
    monkeypatch.setattr(secrets_store, "get_app_data_dir", lambda: fake_app_data / "GENOPOISK_CRM" / "data")

    secret_token = "123456:AAFakeSuperSecretTelegramBotTokenValue"
    secrets_store.set_telegram_bot_token(secret_token)

    db_path = tmp_path / "db" / "genopoisk.db"
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)
    order = repo.NewOrderInput(customer_name="Проверка токена", test_type_codes=["Y50"],
                                sample_received_at=date(2026, 1, 1))
    repo.create_order_with_tests(conn, order)
    conn.close()

    backup_folder = tmp_path / "backups"
    dest = bk.create_backup(db_path, backup_folder)

    backup_bytes = dest.read_bytes()
    assert secret_token.encode() not in backup_bytes  # токен физически не мог попасть в backup БД

    # секрет остался в отдельном файле, не рядом с backup'ами БД
    secret_file_bytes = secrets_store._secrets_file().read_bytes()
    assert secret_token.encode() in secret_file_bytes
    assert secrets_store._secrets_file().parent != backup_folder
