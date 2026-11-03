"""Резервная копия пользовательской базы NeSToR со сроком хранения копий.

  py -3 tools/backup_users.py [--var-dir nestor/var] [--keep-days 14]

* Копируется ТОЛЬКО база nestor_users.db — через VACUUM INTO (согласованная
  копия без свободных страниц, в которых могли остаться удалённые данные).
  Временная папка var/staging/ (незавершённые загрузки), секрет и база научных
  кандидатов в копию не входят.
* Копии в var/backups/ старше --keep-days удаляются при каждом запуске. Данные,
  удалённые из активной базы (профиль, сохранённый по согласию оригинал файла),
  остаются в уже сделанных копиях до их удаления по сроку — не дольше keep-days
  после удаления, если копии не переносились за пределы var/backups/.
* Копии вне var/backups/ (облако, внешние диски, снимки ФС) приложение не видит
  и не удаляет.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "nestor_users-"


def make_backup(users_db: Path, backup_dir: Path, now: float | None = None) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now or time.time(), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{PREFIX}{stamp}.db"
    if target.exists():
        raise SystemExit(f"копия {target.name} уже существует")
    src = sqlite3.connect(f"{users_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        src.execute("VACUUM INTO ?", (str(target),))
    finally:
        src.close()
    return target


def prune(backup_dir: Path, keep_days: float, now: float | None = None) -> list[Path]:
    now = now or time.time()
    removed = []
    for f in sorted(backup_dir.glob(f"{PREFIX}*.db")):
        if now - f.stat().st_mtime > keep_days * 86400:
            f.unlink()
            removed.append(f)
    return removed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--var-dir", type=Path, default=ROOT / "var")
    ap.add_argument("--keep-days", type=float, default=14)
    a = ap.parse_args(argv)
    users_db = a.var_dir / "nestor_users.db"
    if not users_db.exists():
        print(f"нет базы {users_db}", file=sys.stderr)
        return 2
    target = make_backup(users_db, a.var_dir / "backups")
    removed = prune(a.var_dir / "backups", a.keep_days)
    print(f"Копия: {target}")
    print(f"Удалено копий старше {a.keep_days:g} дн.: {len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
