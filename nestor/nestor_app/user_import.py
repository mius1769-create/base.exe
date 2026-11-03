"""Импорт профилей владельца из CSV / XLSX: загрузка → просмотр → сохранение выбранных строк.

Хранение файла:
  * незавершённая загрузка — во временной папке var/staging/ (nestor_app.staging),
    вне пользовательской базы и её резервных копий; срок — staging.TTL_SECONDS,
    затем удаляется автоматически (sweep при запуске, по таймеру и при загрузке);
  * после сохранения в базе остаются только исходные ячейки выбранных строк,
    имя файла, лист, номер строки и SHA-256 всего файла (profile_sources);
    временные файлы загрузки удаляются;
  * полный оригинал записывается в базу только при отдельном согласии keep_original
    (сохранятся и невыбранные строки и листы); удаляется с последним профилем из файла;
  * отмена удаляет временные файлы загрузки.
Повторы только помечаются; записи не объединяются.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import importer as im
from . import profiles as pr
from . import staging
from .db import CheckpointResult, checkpoint_truncate


class UploadError(ValueError):
    pass


@dataclass
class CommitResult:
    profile_ids: list = field(default_factory=list)
    original_kept: bool = False
    checkpoint: CheckpointResult | None = None


def _existing(conn: sqlite3.Connection, owner_user_id: int):
    out = []
    for p in pr.list_owned(conn, owner_user_id):
        src = pr.load_source(conn, p.id)
        out.append((f"ваш профиль {p.public_handle}", (src or {}).get("record_id") or p.kit_id_private or "", p.markers))
    return out


def stage(conn: sqlite3.Connection, staging_root: Path, owner_user_id: int, filename: str, data: bytes,
          panel_choice: str = "AUTO") -> tuple[str, im.Preview]:
    """Проверить файл и положить его во временную папку (в базу ничего не пишется)."""
    staging.sweep(staging_root)
    preview = im.build_preview(filename, data, panel_choice, existing=_existing(conn, owner_user_id))
    st = staging.put(staging_root, owner_user_id, preview.filename, data, panel_choice)
    return st.upload_id, preview


def _load(staging_root: Path, owner_user_id: int, upload_id: str):
    try:
        return staging.get(staging_root, owner_user_id, upload_id)
    except staging.StagingError as e:
        raise UploadError(str(e)) from None


def preview_of(conn, staging_root: Path, owner_user_id: int, upload_id: str) -> im.Preview:
    st, data = _load(staging_root, owner_user_id, upload_id)
    return im.build_preview(st.filename, data, st.panel_choice, existing=_existing(conn, owner_user_id))


def discard(staging_root: Path, owner_user_id: int, upload_id: str) -> None:
    _load(staging_root, owner_user_id, upload_id)   # проверка владельца
    staging.delete(staging_root, upload_id)


def commit(conn, staging_root: Path, owner_user_id: int, upload_id: str, selected: list[tuple[str, int]], *,
           consent_basis: str, consent_confirmed: bool, keep_original: bool = False) -> CommitResult:
    """Сохранить выбранные строки как закрытые профили; временные файлы загрузки удалить."""
    st, data = _load(staging_root, owner_user_id, upload_id)
    if not selected:
        raise UploadError("не выбрано ни одной строки")
    if consent_basis not in pr.CONSENT_BASES or not consent_confirmed:  # до записи первой строки
        raise UploadError("укажите основание загрузки и подтвердите право на загрузку профилей")
    preview = im.build_preview(st.filename, data, st.panel_choice, existing=_existing(conn, owner_user_id))
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
    file_id = None
    if keep_original:  # отдельное согласие: полный файл, включая невыбранные строки и листы
        file_id = conn.execute(
            """INSERT INTO import_files(owner_user_id, filename, sha256, size_bytes, content, panel_choice,
                   status, keep_original, keep_original_at)
               VALUES (?,?,?,?,?,?,'committed',1, strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
            (owner_user_id, st.filename, st.sha256, st.size, data, st.panel_choice)).lastrowid
    result = CommitResult(original_kept=keep_original)
    for rec, sheet in chosen:
        result.profile_ids.append(pr.create_profile(
            conn, owner_user_id, rec.positions, consent_basis=consent_basis,
            consent_confirmed=consent_confirmed, source_format="file", kit_id=rec.record_id or None,
            panel_code=sheet.panel_code or None, panel_basis_override=sheet.panel_basis,
            source={"import_file_id": file_id, "filename": st.filename, "file_sha256": st.sha256,
                    "sheet": rec.sheet, "row_number": rec.row_number, "record_id": rec.record_id or None,
                    "raw_json": im.raw_json(rec)}))
    staging.delete(staging_root, upload_id)
    result.checkpoint = checkpoint_truncate(conn)
    return result
