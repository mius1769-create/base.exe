"""Запросы на связь: контакты не раскрываются, владелец принимает или отклоняет.

Отправитель видит только статус и ответ владельца (если тот принял запрос и
написал ответ). Владелец видит сообщение и псевдоним отправителя, но не email.
Обмен контактами — по решению самих людей в тексте сообщения/ответа.
"""

from __future__ import annotations

import sqlite3

from .db import Tx

MAX_MESSAGE = 1000


class ContactError(ValueError):
    pass


def send_request(conn: sqlite3.Connection, from_user_id: int, to_handle: str, message: str) -> int:
    message = (message or "").strip()
    if not message:
        raise ContactError("напишите сообщение владельцу профиля")
    if len(message) > MAX_MESSAGE:
        raise ContactError(f"сообщение длиннее {MAX_MESSAGE} символов")
    row = conn.execute(
        "SELECT id, owner_user_id, contact_allowed FROM profiles WHERE public_handle = ? AND searchable = 1",
        (to_handle,),
    ).fetchone()
    if row is None:
        raise ContactError("профиль не найден или закрыт")
    if row["owner_user_id"] == from_user_id:
        raise ContactError("нельзя отправить запрос своему профилю")
    if not row["contact_allowed"]:
        raise ContactError("владелец этого профиля не принимает запросы на связь")
    try:
        cur = conn.execute(
            "INSERT INTO contact_requests(from_user_id, to_profile_id, message) VALUES (?,?,?)",
            (from_user_id, row["id"], message),
        )
    except sqlite3.IntegrityError:
        raise ContactError("вы уже отправляли запрос этому профилю") from None
    return int(cur.lastrowid)


def incoming(conn: sqlite3.Connection, owner_user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT cr.id, cr.message, cr.status, cr.created_at, p.public_handle,
                  COALESCE(u.display_name, 'пользователь без псевдонима') AS sender
           FROM contact_requests cr
           JOIN profiles p ON p.id = cr.to_profile_id
           JOIN users u ON u.id = cr.from_user_id
           WHERE p.owner_user_id = ? ORDER BY cr.id DESC""",
        (owner_user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def outgoing(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT cr.id, cr.status, cr.created_at, p.public_handle,
                  CASE WHEN cr.status = 'accepted' THEN cr.owner_reply END AS owner_reply
           FROM contact_requests cr JOIN profiles p ON p.id = cr.to_profile_id
           WHERE cr.from_user_id = ? ORDER BY cr.id DESC""",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def decide(conn: sqlite3.Connection, owner_user_id: int, request_id: int, accept: bool, reply: str | None = None) -> None:
    reply = (reply or "").strip() or None
    if reply and len(reply) > MAX_MESSAGE:
        raise ContactError(f"ответ длиннее {MAX_MESSAGE} символов")
    with Tx(conn):
        row = conn.execute(
            """SELECT cr.id, cr.status FROM contact_requests cr JOIN profiles p ON p.id = cr.to_profile_id
               WHERE cr.id = ? AND p.owner_user_id = ?""",
            (request_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise ContactError("запрос не найден")
        if row["status"] != "pending":
            raise ContactError("решение по запросу уже принято")
        conn.execute(
            """UPDATE contact_requests SET status = ?, owner_reply = ?,
                   decided_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?""",
            ("accepted" if accept else "declined", reply if accept else None, request_id),
        )
