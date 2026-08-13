"""
GENOPOISK CRM — резервное копирование и восстановление (раздел 19 ТЗ).

Правила:
  - имя файла: genopoisk_YYYY-MM-DD_HH-MM-SS.db;
  - предыдущие копии не перезаписываются;
  - хранится N последних копий (настройка), лишние старые удаляются;
  - перед восстановлением обязательно делается backup текущей базы;
  - папка backup может быть на синхронизируемом облачном диске
    (OneDrive/Google Drive/Dropbox/Яндекс Диск) — мы просто копируем файл
    в указанную пользователем папку, синхронизация — забота клиента облака.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


FILENAME_FMT = "genopoisk_%Y-%m-%d_%H-%M-%S.db"


def create_backup(db_path: Path, backup_folder: Path) -> Path:
    """Создаёт снимок БД в backup_folder. Использует SQLite backup API — безопасно
    даже если приложение сейчас пишет в базу (в отличие от простого copy файла)."""
    backup_folder.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime(FILENAME_FMT)
    dest = backup_folder / filename
    if dest.exists():
        # крайне маловероятно (секундная точность), но на всякий случай не перезаписываем
        i = 1
        while (backup_folder / f"{dest.stem}_{i}{dest.suffix}").exists():
            i += 1
        dest = backup_folder / f"{dest.stem}_{i}{dest.suffix}"

    src_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()
    return dest


def list_backups(backup_folder: Path) -> list[Path]:
    if not backup_folder.exists():
        return []
    files = sorted(backup_folder.glob("genopoisk_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def prune_old_backups(backup_folder: Path, keep_count: int) -> list[Path]:
    """Удаляет старые копии сверх keep_count. Возвращает список удалённых файлов."""
    backups = list_backups(backup_folder)
    to_delete = backups[keep_count:]
    for p in to_delete:
        p.unlink(missing_ok=True)
    return to_delete


def restore_backup(backup_file: Path, db_path: Path, *, pre_restore_backup_folder: Optional[Path] = None) -> Optional[Path]:
    """
    Восстанавливает БД из резервной копии. ОБЯЗАТЕЛЬНО делает backup текущей
    базы перед восстановлением (раздел 19), если pre_restore_backup_folder указана.
    Возвращает путь к backup'у текущей базы (если он был сделан) — для отображения
    пользователю "на случай отмены".
    """
    pre_backup_path = None
    if pre_restore_backup_folder is not None and db_path.exists():
        pre_backup_path = create_backup(db_path, pre_restore_backup_folder)

    shutil.copy2(backup_file, db_path)

    # WAL/SHM-файлы старой сессии могут быть неактуальны после подмены — убираем их,
    # чтобы SQLite не пытался применить устаревший WAL поверх восстановленной базы.
    for suffix in ("-wal", "-shm"):
        stale = Path(str(db_path) + suffix)
        stale.unlink(missing_ok=True)

    return pre_backup_path
