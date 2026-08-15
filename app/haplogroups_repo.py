"""
GENOPOISK CRM — репозиторий вкладки «Гаплогруппы».

Одна запись haplogroups на тест (test_number = tests.gns_number, UNIQUE).
full_name хранится как снимок ФИО из заказа на момент сохранения, но при
чтении список всегда предпочитает АКТУАЛЬНОЕ ФИО из orders (через JOIN по
test_number -> tests -> orders) — поле "из карточки, не редактируется
здесь" (раздел ТЗ), поэтому пользователь никогда не вводит его вручную.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from . import repository as repo
from . import projects_repo

# Поля, редактируемые из UI вкладки (снип-предикции, проект, комментарий).
EDITABLE_FIELDS = {
    "project_id", "y_dna", "mt_dna", "nevgen_prediction",
    "semargl_prediction", "snp_issued", "comment",
}

# Резервные поля — заложены в БД, но НЕ выводятся в UI этой вкладки.
RESERVED_FIELDS = {"date_prediction", "analyst", "review_status", "date_issued"}

ALL_WRITABLE_FIELDS = EDITABLE_FIELDS | RESERVED_FIELDS


def get_test_by_number(conn: sqlite3.Connection, test_number: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT t.test_id, t.gns_number, o.customer_name
           FROM tests t JOIN orders o ON o.order_id = t.order_id
           WHERE t.gns_number = ?""",
        (test_number,),
    ).fetchone()


def upsert_haplogroup(
    conn: sqlite3.Connection,
    test_number: str,
    fields: dict[str, Any],
    *,
    user_name: Optional[str] = None,
) -> int:
    """Создаёт или обновляет запись гаплогруппы для указанного номера теста."""
    unknown = set(fields) - ALL_WRITABLE_FIELDS
    if unknown:
        raise ValueError(f"Недопустимые поля для записи гаплогруппы: {unknown}")

    conn.execute("BEGIN IMMEDIATE")
    try:
        test_row = get_test_by_number(conn, test_number)
        if test_row is None:
            raise ValueError(f"Тест с номером {test_number!r} не найден")
        full_name = test_row["customer_name"]

        existing = conn.execute(
            "SELECT * FROM haplogroups WHERE test_number = ?", (test_number,)
        ).fetchone()
        ts = repo.now_iso()

        if existing is None:
            cols = ["test_number", "full_name"] + list(fields.keys()) + ["created_at", "updated_at"]
            vals = [test_number, full_name] + [fields[k] for k in fields] + [ts, ts]
            placeholders = ",".join("?" * len(vals))
            cur = conn.execute(
                f"INSERT INTO haplogroups ({','.join(cols)}) VALUES ({placeholders})", vals
            )
            hap_id = cur.lastrowid
            repo.write_audit(conn, user_name=user_name, entity="haplogroup", entity_id=hap_id,
                              field=None, old_value=None, new_value=f"создана запись для {test_number}",
                              reason="создание записи гаплогруппы")
        else:
            hap_id = existing["id"]
            sets: list[str] = []
            vals: list[Any] = []
            for k, v in fields.items():
                old = existing[k]
                if str(old) == str(v):
                    continue
                sets.append(f"{k} = ?")
                vals.append(v)
                repo.write_audit(conn, user_name=user_name, entity="haplogroup", entity_id=hap_id,
                                  field=k, old_value=old, new_value=v,
                                  reason="редактирование записи гаплогруппы")
            if existing["full_name"] != full_name:
                sets.append("full_name = ?")
                vals.append(full_name)
            if sets:
                sets.append("updated_at = ?")
                vals.append(ts)
                vals.append(hap_id)
                conn.execute(f"UPDATE haplogroups SET {', '.join(sets)} WHERE id = ?", vals)

        conn.execute("COMMIT")
        return hap_id
    except Exception:
        conn.execute("ROLLBACK")
        raise


def archive_haplogroup(conn: sqlite3.Connection, haplogroup_id: int, *, user_name: Optional[str] = None) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM haplogroups WHERE id = ?", (haplogroup_id,)).fetchone()
        if row is None:
            raise ValueError(f"Запись гаплогруппы {haplogroup_id} не найдена")
        conn.execute(
            "UPDATE haplogroups SET is_archived = 1, updated_at = ? WHERE id = ?",
            (repo.now_iso(), haplogroup_id),
        )
        repo.write_audit(conn, user_name=user_name, entity="haplogroup", entity_id=haplogroup_id,
                          field="is_archived", old_value=0, new_value=1, reason="архивирование записи")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def list_haplogroups(
    conn: sqlite3.Connection,
    *,
    project_id: Optional[int] = None,
    test_number: Optional[str] = None,
    full_name: Optional[str] = None,
    y_dna: Optional[str] = None,
    mt_dna: Optional[str] = None,
    snp_issued: Optional[str] = None,
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    q = """
        SELECT h.*, COALESCE(o.customer_name, h.full_name) AS display_full_name
        FROM haplogroups h
        LEFT JOIN tests t ON t.gns_number = h.test_number
        LEFT JOIN orders o ON o.order_id = t.order_id
        WHERE 1=1
    """
    params: list[Any] = []

    if not include_archived:
        q += " AND h.is_archived = 0"

    if project_id is not None:
        ids = {project_id} | projects_repo.get_descendant_ids(conn, project_id)
        placeholders = ",".join("?" * len(ids))
        q += f" AND h.project_id IN ({placeholders})"
        params += list(ids)

    if test_number:
        q += " AND h.test_number LIKE ?"
        params.append(f"%{test_number}%")

    if full_name:
        q += " AND COALESCE(o.customer_name, h.full_name) LIKE ?"
        params.append(f"%{full_name}%")

    if y_dna:
        q += " AND h.y_dna LIKE ?"
        params.append(f"%{y_dna}%")

    if mt_dna:
        q += " AND h.mt_dna LIKE ?"
        params.append(f"%{mt_dna}%")

    if snp_issued:
        q += " AND h.snp_issued LIKE ?"
        params.append(f"%{snp_issued}%")

    q += " ORDER BY h.updated_at DESC"
    return conn.execute(q, params).fetchall()


def list_test_numbers_for_picker(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Тесты для выбора в диалоге добавления записи гаплогруппы (номер + ФИО)."""
    return conn.execute(
        """SELECT t.gns_number, o.customer_name
           FROM tests t JOIN orders o ON o.order_id = t.order_id
           WHERE t.is_archived = 0 AND o.is_archived = 0
           ORDER BY t.gns_number"""
    ).fetchall()
