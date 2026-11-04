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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nestor_app.catalog_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
