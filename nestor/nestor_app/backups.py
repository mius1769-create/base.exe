"""Резервные копии пользовательской базы и их срок хранения.

Срок (keep_days) применяется, когда выполняется очистка: при каждом запуске
tools/backup_users.py, при запуске приложения NeSToR и каждый час, пока оно
работает (NestorApp.maintenance), либо по расписанию ОС (backup_users.py
--prune-only). Если ничего из этого не запускается, копии остаются дольше:
keep_days — не гарантированный максимум, а срок, применяемый при очистке.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "nestor_users-"
DEFAULT_KEEP_DAYS = 14.0


def keep_days_from_env() -> float:
    try:
        return float(os.environ.get("NESTOR_BACKUP_KEEP_DAYS", DEFAULT_KEEP_DAYS))
    except ValueError:
        return DEFAULT_KEEP_DAYS


def make_backup(users_db: Path, backup_dir: Path, now: float | None = None) -> Path:
    """Согласованная копия только пользовательской базы (VACUUM INTO, без свободных страниц)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now or time.time(), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{PREFIX}{stamp}.db"
    if target.exists():
        raise FileExistsError(f"копия {target.name} уже существует")
    src = sqlite3.connect(f"{users_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        src.execute("VACUUM INTO ?", (str(target),))
    finally:
        src.close()
    return target


def prune(backup_dir: Path, keep_days: float, now: float | None = None) -> list[Path]:
    """Удалить копии старше keep_days (по времени изменения файла)."""
    if not backup_dir.exists():
        return []
    now = now or time.time()
    removed = []
    for f in sorted(backup_dir.glob(f"{PREFIX}*.db")):
        if now - f.stat().st_mtime > keep_days * 86400:
            f.unlink()
            removed.append(f)
    return removed
