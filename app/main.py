"""GENOPOISK CRM — точка входа приложения."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import db as dbmod
from . import repository as repo
from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GENOPOISK CRM")
    app.setOrganizationName("GENOPOISK")

    db_path = dbmod.get_db_path()
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)
    repo.migrate_existing_tests_to_events(conn)  # идемпотентно, безопасно на каждом запуске

    window = MainWindow(conn)
    window.show()

    exit_code = app.exec()
    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
