import argparse
import csv
import io
import json
import logging
import sqlite3
import sys
from collections import defaultdict
import os
from pathlib import Path

# Пути и ID таблицы задаются переменными окружения (в репозитории — без реальных значений).
ROOT = Path(os.environ.get("CRM_SYNC_ROOT", Path(__file__).resolve().parent))
APP_ROOT = Path(os.environ.get("CRM_APP_ROOT", Path(__file__).resolve().parents[2]))
DB = Path(os.environ.get(
    "CRM_DB_PATH",
    Path(os.environ.get("APPDATA", "")) / "GENOPOISK_CRM" / "data" / "genopoisk.db",
))
SHEET_ID = os.environ.get("CRM_GOOGLE_SHEET_ID", "")

sys.path.insert(0, str(APP_ROOT))
from app import business_logic as bl

HEADERS_WORK = [
    "Номер теста", "№ заказа", "ФИО", "Тип теста",
    "Рабочий статус", "Статус заказа", "Дедлайн",
    "Образец получен", "Передан в лабораторию",
    "Профиль получен", "Взято в работу",
    "Оператор", "Выдан клиенту"
]
HEADERS_CLIENT = [
    "№", "Номер теста", "№ заказа", "ФИО клиента",
    "Тип теста", "Статус клиенту", "Статус заказа", "Дедлайн"
]

def val(x):
    return "" if x is None else str(x)

def prepare():
    if not DB.is_file():
        raise RuntimeError(f"База не найдена: {DB}")

    uri = DB.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        records = conn.execute("""
            SELECT t.*, o.order_no, o.customer_name, o.order_status
            FROM tests t
            JOIN orders o ON o.order_id = t.order_id
            WHERE COALESCE(t.is_archived, 0) = 0
              AND COALESCE(o.is_archived, 0) = 0
            ORDER BY o.order_id, t.test_id
        """).fetchall()

        events = defaultdict(list)
        ids = [r["test_id"] for r in records]

        # Считываем журнал событий без изменения базы.
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            marks = ",".join("?" for _ in batch)
            for e in conn.execute(
                f"""SELECT * FROM test_events
                    WHERE test_id IN ({marks})
                    ORDER BY event_time, id""", batch
            ):
                events[e["test_id"]].append(dict(e))

        names = {
            r["code"]: r["display_name"]
            for r in conn.execute(
                "SELECT code, display_name FROM test_types"
            )
        }

        work = []
        client = []

        for r in records:
            if val(r["gns_number"]).startswith("SERVICE-") and val(r["test_type"]).upper() == "REPORT":
                continue
            test_no = val(r["gns_number"])
            test_type = names.get(r["test_type"], r["test_type"])
            ev = events[r["test_id"]]

            work.append([
                test_no,
                val(r["order_no"]),
                val(r["customer_name"]),
                val(test_type),
                bl.internal_status_label(ev),
                val(r["order_status"]),
                val(r["deadline_date"]),
                val(r["sample_received_at"]),
                val(r["lab_sent_at"]),
                val(r["lab_profile_received_at"]),
                val(r["operator_started_at"]),
                val(r["operator_name"]),
                val(r["client_issued_at"]),
            ])

            client.append([
                len(client) + 1,
                test_no,
                val(r["order_no"]),
                val(r["customer_name"]),
                val(test_type),
                bl.client_status_label(ev),
                val(r["order_status"]),
                val(r["deadline_date"]),
            ])

        if not records:
            raise RuntimeError(
                "Выгрузка пуста. Google-таблица не будет очищена."
            )
        if any(not r[0] for r in work):
            raise RuntimeError(
                "Есть активные тесты без номера GNPSK. "
                "Требуется проверить данные до синхронизации."
            )

        return work, client
    finally:
        conn.close()


def sync_google(work, client):
    from datetime import datetime
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if not SHEET_ID:
        raise RuntimeError("Не задан CRM_GOOGLE_SHEET_ID")

    token_path = ROOT / "token.json"
    if not token_path.exists():
        raise RuntimeError("Не найден token.json")

    credentials = Credentials.from_authorized_user_file(
        str(token_path),
        ["https://www.googleapis.com/auth/spreadsheets"]
    )
    if not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_path.write_text(
                credentials.to_json(), encoding="utf-8"
            )
        else:
            raise RuntimeError("Требуется повторная авторизация Google")

    service = build("sheets", "v4", credentials=credentials)
    api = service.spreadsheets().values()

    ranges = ["'Рабочая'!A:M", "'Клиентская'!A:H"]
    result = api.batchGet(
        spreadsheetId=SHEET_ID,
        ranges=ranges
    ).execute()

    existing = result.get("valueRanges", [])
    if len(existing) != 2:
        raise RuntimeError("Не удалось прочитать обе вкладки")

    expected = [HEADERS_WORK, HEADERS_CLIENT]
    for index, item in enumerate(existing):
        values = item.get("values", [])
        if not values or values[0] != expected[index]:
            raise RuntimeError(
                "Заголовки Google-таблицы не совпадают. "
                "Обновление отменено."
            )

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"google_before_{stamp}.json"

    backup_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"Резервная копия: {backup_path}")

    # Одним запросом перезаписываем данные и очищаем
    # оставшиеся строки предыдущей выгрузки.
    old_work = max(0, len(existing[0].get("values", [])) - 1)
    old_client = max(0, len(existing[1].get("values", [])) - 1)

    work_count = max(old_work, len(work))
    client_count = max(old_client, len(client))

    work_rows = work + [
        [""] * 13 for _ in range(work_count - len(work))
    ]
    client_rows = client + [
        [""] * 8 for _ in range(client_count - len(client))
    ]

    data = [
        {
            "range": f"'Рабочая'!A2:M{work_count + 1}",
            "values": work_rows
        },
        {
            "range": f"'Клиентская'!A2:H{client_count + 1}",
            "values": client_rows
        }
    ]

    api.batchUpdate(
        spreadsheetId=SHEET_ID,
        body={
            "valueInputOption": "RAW",
            "data": data
        }
    ).execute()

    print("Синхронизация завершена.")
    print(f"Рабочая: {len(work)} строк")
    print(f"Клиентская: {len(client)} строк")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Проверить данные без отправки"
    )
    args = parser.parse_args()

    work, client = prepare()
    print("Проверка завершена.")
    print(f"Рабочая: {len(work)} строк")
    print(f"Клиентская: {len(client)} строк")
    print("Первые 3 записи (без ФИО):")
    for row in work[:3]:
        print(
            f"  {row[0]} | {row[1]} | "
            f"{row[3]} | {row[4]}"
        )

    if args.sync:
        sync_google(work, client)
    elif not args.dry_run:
        print(
            "Отправка пока заблокирована. "
            "Сначала проверяем результаты --dry-run."
        )

def logged_main():
    import contextlib
    import traceback
    from datetime import datetime

    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "sync.log"

    class Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, text):
            for stream in self.streams:
                stream.write(text)
                stream.flush()

        def flush(self):
            for stream in self.streams:
                stream.flush()

    with log_path.open("a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)):
            with contextlib.redirect_stderr(Tee(sys.stderr, log)):
                print(
                    "\\n=== Запуск:",
                    datetime.now().isoformat(timespec="seconds"),
                    "==="
                )
                try:
                    main()
                except Exception:
                    traceback.print_exc()
                    print("Результат: ОШИБКА")
                    raise SystemExit(1)
                else:
                    print("Результат: УСПЕШНО")


if __name__ == "__main__":
    logged_main()
