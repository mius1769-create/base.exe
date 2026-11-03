"""Временное хранение загруженных файлов — вне пользовательской базы.

Незавершённая загрузка (между загрузкой файла и решением владельца) хранится
в отдельной папке var/staging/ двумя файлами: <id>.bin (содержимое) и <id>.json
(владелец, имя файла, SHA-256, выбранная панель, время). В пользовательскую
SQLite-базу она не пишется, поэтому не попадает в её резервные копии
(tools/backup_users.py копирует только базу).

Удаление без ручного вмешательства (sweep):
  * при запуске приложения, затем каждый SWEEP_INTERVAL_SECONDS и при каждой новой загрузке;
  * удаляются загрузки старше TTL, «осиротевшие» .bin/.json после сбоя процесса
    (нет пары, нечитаемые метаданные, недописанные .tmp);
  * новая загрузка владельца заменяет его прежнюю незавершённую.
Отмена и сохранение удаляют файлы загрузки сразу.

Удаление здесь — удаление файлов в файловой системе. Стирание с SSD, из снимков
файловой системы и внешних копий приложение не гарантирует.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

TTL_SECONDS = 24 * 3600
SWEEP_INTERVAL_SECONDS = 3600
_ID_LEN = 32


class StagingError(ValueError):
    pass


@dataclass(frozen=True)
class Staged:
    upload_id: str
    owner_user_id: int
    filename: str
    sha256: str
    size: int
    panel_choice: str
    created_at: float


def _valid_id(upload_id: str) -> bool:
    return len(upload_id) == _ID_LEN and all(c in "0123456789abcdef" for c in upload_id)


def _paths(root: Path, upload_id: str) -> tuple[Path, Path]:
    if not _valid_id(upload_id):
        raise StagingError("загрузка не найдена")
    return root / f"{upload_id}.bin", root / f"{upload_id}.json"


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _remove(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def put(root: Path, owner_user_id: int, filename: str, data: bytes, panel_choice: str) -> Staged:
    root.mkdir(parents=True, exist_ok=True)
    for s in list_for(root, owner_user_id):  # одна незавершённая загрузка на владельца
        delete(root, s.upload_id)
    upload_id = secrets.token_hex(_ID_LEN // 2)
    bin_path, meta_path = _paths(root, upload_id)
    st = Staged(upload_id, owner_user_id, filename, hashlib.sha256(data).hexdigest(), len(data), panel_choice, time.time())
    _write_atomic(bin_path, data)          # сначала содержимое, затем метаданные:
    _write_atomic(meta_path, json.dumps(st.__dict__, ensure_ascii=False).encode())  # сбой между ними → sweep
    return st


def _read_meta(meta_path: Path) -> Staged | None:
    try:
        d = json.loads(meta_path.read_text(encoding="utf-8"))
        return Staged(**d)
    except (OSError, ValueError, TypeError):
        return None


def get(root: Path, owner_user_id: int, upload_id: str) -> tuple[Staged, bytes]:
    bin_path, meta_path = _paths(root, upload_id)
    st = _read_meta(meta_path)
    if st is None or st.owner_user_id != owner_user_id or not bin_path.exists():
        raise StagingError("загрузка не найдена или устарела")
    if time.time() - st.created_at > TTL_SECONDS:
        delete(root, upload_id)
        raise StagingError("загрузка устарела и удалена — загрузите файл заново")
    return st, bin_path.read_bytes()


def list_for(root: Path, owner_user_id: int) -> list[Staged]:
    if not root.exists():
        return []
    out = []
    for meta in root.glob("*.json"):
        st = _read_meta(meta)
        if st and st.owner_user_id == owner_user_id:
            out.append(st)
    return out


def delete(root: Path, upload_id: str) -> None:
    for p in _paths(root, upload_id):
        _remove(p)


def sweep(root: Path, now: float | None = None) -> dict:
    """Удалить устаревшие и осиротевшие файлы временной папки. Возвращает счётчики."""
    stats = {"expired": 0, "orphaned": 0, "partial": 0}
    if not root.exists():
        return stats
    now = time.time() if now is None else now
    for tmp in root.glob("*.tmp"):            # недописанный файл после сбоя
        if _remove(tmp):
            stats["partial"] += 1
    metas = {p.stem: p for p in root.glob("*.json")}
    bins = {p.stem: p for p in root.glob("*.bin")}
    for uid in set(metas) | set(bins):
        meta, binf = metas.get(uid), bins.get(uid)
        st = _read_meta(meta) if meta else None
        if st is None or binf is None or not _valid_id(uid):
            for p in (meta, binf):
                if p is not None:
                    _remove(p)
            stats["orphaned"] += 1
        elif now - st.created_at > TTL_SECONDS:
            delete(root, uid)
            stats["expired"] += 1
    return stats
