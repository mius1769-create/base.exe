"""Локальный тестовый научный каталог NeSToR: сборка, включение, отключение, удаление.

  py -3 tools/build_test_catalog.py build --candidate Nestor_scientific_YSTR.db --archive scientific.sqlite
  py -3 tools/build_test_catalog.py enable
  py -3 tools/build_test_catalog.py disable      # поиск перестаёт использовать каталог
  py -3 tools/build_test_catalog.py remove       # удалить базу каталога и флаг
  py -3 tools/build_test_catalog.py status

Каталог — отдельная база var/test_catalog/nestor_test_catalog.db, только для локального
тестирования: не научный справочник, не публикуется, в git не попадает. build только
собирает и печатает сводку; включение — отдельная команда enable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nestor_app import test_catalog as tc  # noqa: E402


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "enable", "disable", "remove", "status"])
    ap.add_argument("--var-dir", type=Path, default=ROOT / "var")
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--archive", type=Path)
    ap.add_argument("--summary", type=Path, help="записать сводку (без записей) в JSON")
    a = ap.parse_args(argv)
    if a.action == "build":
        if not (a.candidate and a.archive):
            ap.error("build требует --candidate и --archive")
        tc.disable(a.var_dir)   # пересборка не включает каталог автоматически
        stats = tc.build(a.candidate, a.archive, tc.catalog_path(a.var_dir), ROOT / "data" / "source_audit.json")
        text = json.dumps(stats, ensure_ascii=False, indent=2)
        if a.summary:
            a.summary.write_text(text + "\n", encoding="utf-8")
        print(text)
        print("Каталог собран и ВЫКЛЮЧЕН. Включить: tools/build_test_catalog.py enable", file=sys.stderr)
    elif a.action == "enable":
        tc.enable(a.var_dir)
        print("Тестовый каталог включён (только локально).")
    elif a.action == "disable":
        tc.disable(a.var_dir)
        print("Тестовый каталог выключен.")
    elif a.action == "remove":
        tc.remove(a.var_dir)
        print("Тестовый каталог удалён из папки приложения.")
    else:
        p = tc.catalog_path(a.var_dir)
        print(json.dumps({"built": p.exists(), "enabled": tc.is_enabled(a.var_dir), "path": str(p)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
