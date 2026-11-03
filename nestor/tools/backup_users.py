"""Резервная копия пользовательской базы NeSToR и очистка старых копий.

  py -3 tools/backup_users.py [--var-dir nestor/var] [--keep-days 14]
  py -3 tools/backup_users.py --prune-only [--keep-days 14]      # только очистка (для планировщика)

* Копируется ТОЛЬКО nestor_users.db — через VACUUM INTO (согласованная копия без
  свободных страниц). Временные загрузки, секрет и база научных кандидатов не входят.
* Копии в var/backups/ старше --keep-days удаляются, когда выполняется очистка:
  при запуске этого инструмента, при запуске приложения и каждый час, пока оно
  работает, или по расписанию ОС (--prune-only). Это срок, применяемый при
  очистке, а не гарантированный максимум: если не запускается ни приложение, ни
  инструмент, ни задание планировщика, копии остаются дольше.
* Копии вне var/backups/ (облако, внешние диски, снимки ФС) приложение не видит
  и не удаляет.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nestor_app.backups import PREFIX, keep_days_from_env, make_backup, prune  # noqa: E402,F401


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--var-dir", type=Path, default=ROOT / "var")
    ap.add_argument("--keep-days", type=float, default=keep_days_from_env())
    ap.add_argument("--prune-only", action="store_true", help="только удалить старые копии")
    a = ap.parse_args(argv)
    backup_dir = a.var_dir / "backups"
    if not a.prune_only:
        users_db = a.var_dir / "nestor_users.db"
        if not users_db.exists():
            print(f"нет базы {users_db}", file=sys.stderr)
            return 2
        print(f"Копия: {make_backup(users_db, backup_dir)}")
    removed = prune(backup_dir, a.keep_days)
    print(f"Удалено копий старше {a.keep_days:g} дн.: {len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
