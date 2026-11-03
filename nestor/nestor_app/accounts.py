"""Локальные учётные записи владельцев профилей и сессии."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

_ITERATIONS = 200_000
SESSION_TTL = timedelta(days=7)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(ValueError):
    pass


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
    return hmac.compare_digest(dk.hex(), dk_hex)


def register(conn: sqlite3.Connection, email: str, password: str, display_name: str | None = None) -> int:
    email = email.strip()
    if not _EMAIL_RE.match(email):
        raise AuthError("некорректный email")
    if len(password) < 8:
        raise AuthError("пароль должен быть не короче 8 символов")
    try:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, display_name) VALUES (?,?,?)",
            (email, hash_password(password), (display_name or "").strip() or None),
        )
    except sqlite3.IntegrityError:
        raise AuthError("пользователь с таким email уже есть") from None
    return int(cur.lastrowid)


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> int:
    row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email.strip(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise AuthError("неверный email или пароль")
    return int(row["id"])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + SESSION_TTL).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at) VALUES (?,?,?,?)",
        (_token_hash(token), user_id, csrf, expires),
    )
    return token, csrf


def resolve_session(conn: sqlite3.Connection, token: str | None) -> tuple[int, str] | None:
    if not token:
        return None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = conn.execute(
        "SELECT user_id, csrf_token FROM sessions WHERE token_hash = ? AND expires_at > ?",
        (_token_hash(token), now),
    ).fetchone()
    return (int(row["user_id"]), row["csrf_token"]) if row else None


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def delete_account(conn: sqlite3.Connection, user_id: int) -> None:
    """Удаляет учётную запись и каскадно все её профили, маркеры, согласия и запросы."""
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
