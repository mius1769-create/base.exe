"""Локальный тестовый научный каталог NeSToR: сборка, включение, отключение, удаление.

  py -3 tools/build_test_catalog.py build-release --release Genopoisk_expert_linux_2026-10-14.tar.gz --candidate Nestor_scientific_YSTR.db --enable
  py -3 tools/build_test_catalog.py verify-ui    # запуск NeSToR: включён → перезапуск → выключение
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

from nestor_app import catalog_release as cr  # noqa: E402
from nestor_app import test_catalog as tc  # noqa: E402


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build-release", "verify-ui", "build", "enable", "disable", "remove", "status"])
    ap.add_argument("--var-dir", type=Path, default=ROOT / "var")
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--archive", type=Path)
    ap.add_argument("--summary", type=Path, help="записать сводку (без записей) в JSON")
    ap.add_argument("--release", type=Path, help="исходный .tar.gz (или .tar / .zip с ним внутри)")
    ap.add_argument("--enable", action="store_true", help="build-release: включить каталог после успешной сборки")
    ap.add_argument("--expected-file", type=Path, help="только для проверок на синтетических данных (CI)")
    ap.add_argument("--leave-disabled", action="store_true", help="verify-ui: оставить каталог выключенным")
    a = ap.parse_args(argv)
    if a.action == "build-release":
        if not (a.release and a.candidate):
            ap.error("build-release требует --release и --candidate")
        rep = cr.build_release(a.release, a.candidate, a.var_dir, ROOT / "data" / "source_audit.json",
                               expected=cr.load_expected(a.expected_file), enable=a.enable)
        short = {k: v for k, v in rep.items() if k != "sources_status"}
        print(json.dumps(short, ensure_ascii=False, indent=2))
        if not rep["ok"]:
            print("ОШИБКА: каталог не изменён — " + rep["error"])
            return 1
        c = rep["counts"]
        print(f"ПРОВЕРЕНО: SHA-256 входов совпали; записей {c['records']}, индивидуальных {c['individual_records']}, "
              f"агрегированных {c['aggregated_records']} (N={c['aggregated_observations']}). "
              f"Каталог {'ВКЛЮЧЁН' if rep['enabled'] else 'выключен'}. "
              f"Отчёт: {tc.catalog_dir(a.var_dir) / cr.REPORT_FILE}")
        return 0
    if a.action == "verify-ui":
        res = cr.verify_ui(a.var_dir, ROOT, sys.executable, leave_enabled=not a.leave_disabled)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        print(("ПРОВЕРЕНО: " if res["ok"] else "ОШИБКА: ") + ", ".join(f"{k}={v}" for k, v in res["checks"].items())
              + f"; каталог сейчас {'включён' if res['final_enabled'] else 'выключен'}")
        return 0 if res["ok"] else 1
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
