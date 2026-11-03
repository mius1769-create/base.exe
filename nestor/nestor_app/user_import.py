"""Импорт профилей владельца из CSV / XLSX: загрузка → просмотр → сохранение выбранных строк.

Файл хранится целиком (import_files) до сохранения или отмены. Сохранённый
профиль создаётся закрытым (как при ручном вводе) и получает происхождение:
файл, SHA-256, лист, номер строки и исходные ячейки дословно (profile_sources).
Повторы и совпадения только помечаются; записи не объединяются.
"""

from __future__ import annotations

import sqlite3

from . import importer as im
from . import profiles as pr


class UploadError(ValueError):
    pass


def _existing(conn: sqlite3.Connection, owner_user_id: int):
    out = []
    for p in pr.list_owned(conn, owner_user_id):
        src = pr.load_source(conn, p.id)
        out.append((f"ваш профиль {p.public_handle}", (src or {}).get("record_id") or p.kit_id_private or "", p.markers))
    return out


def stage(conn: sqlite3.Connection, owner_user_id: int, filename: str, data: bytes,
          panel_choice: str = "AUTO") -> tuple[int, im.Preview]:
    """Проверить файл и сохранить его как «загружен, ждёт подтверждения»."""
    preview = im.build_preview(filename, data, panel_choice, existing=_existing(conn, owner_user_id))
    cur = conn.execute(
        "INSERT INTO import_files(owner_user_id, filename, sha256, size_bytes, content, panel_choice) VALUES (?,?,?,?,?,?)",
        (owner_user_id, preview.filename, preview.sha256, preview.size, data, panel_choice),
    )
    return int(cur.lastrowid), preview


def _staged(conn, owner_user_id: int, upload_id: int):
    row = conn.execute("SELECT * FROM import_files WHERE id = ? AND owner_user_id = ?",
                       (upload_id, owner_user_id)).fetchone()
    if row is None:
        raise UploadError("загрузка не найдена")
    return row


def preview_of(conn, owner_user_id: int, upload_id: int) -> im.Preview:
    row = _staged(conn, owner_user_id, upload_id)
    return im.build_preview(row["filename"], bytes(row["content"]), row["panel_choice"],
                            existing=_existing(conn, owner_user_id))


def discard(conn, owner_user_id: int, upload_id: int) -> None:
    row = _staged(conn, owner_user_id, upload_id)
    if row["status"] != "staged":
        raise UploadError("файл уже сохранён: удалите профили из него, чтобы удалить файл")
    conn.execute("DELETE FROM import_files WHERE id = ?", (upload_id,))


def commit(conn, owner_user_id: int, upload_id: int, selected: list[tuple[str, int]], *,
           consent_basis: str, consent_confirmed: bool) -> list[int]:
    """Сохранить выбранные строки (лист, номер строки) как закрытые профили."""
    row = _staged(conn, owner_user_id, upload_id)
    if row["status"] != "staged":
        raise UploadError("этот файл уже сохранён")
    if not selected:
        raise UploadError("не выбрано ни одной строки")
    if consent_basis not in pr.CONSENT_BASES or not consent_confirmed:  # до записи первой строки
        raise UploadError("укажите основание загрузки и подтвердите право на загрузку профилей")
    preview = preview_of(conn, owner_user_id, upload_id)
    by_key = {(r.sheet, r.row_number): (r, s) for s in preview.sheets for r in s.records}
    chosen = []
    for key in selected:
        if key not in by_key:
            raise UploadError(f"строка {key[0]}:{key[1]} не найдена в файле")
        rec, sheet = by_key[key]
        if not rec.savable:
            raise UploadError(f"строку {key[0]}:{key[1]} нельзя сохранить: {rec.error}")
        if sheet.error:
            raise UploadError(f"лист {sheet.name}: {sheet.error}")
        chosen.append((rec, sheet))
    ids = []
    for rec, sheet in chosen:
        pid = pr.create_profile(
            conn, owner_user_id, rec.positions, consent_basis=consent_basis,
            consent_confirmed=consent_confirmed, source_format="file", kit_id=rec.record_id or None,
            panel_code=sheet.panel_code or None, panel_basis_override=sheet.panel_basis,
            source={"import_file_id": upload_id, "filename": row["filename"], "file_sha256": row["sha256"],
                    "sheet": rec.sheet, "row_number": rec.row_number, "record_id": rec.record_id or None,
                    "raw_json": im.raw_json(rec)})
        ids.append(pid)
    conn.execute("UPDATE import_files SET status = 'committed' WHERE id = ?", (upload_id,))
    return ids
