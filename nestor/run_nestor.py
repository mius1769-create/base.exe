"""Локальный запуск NeSToR: python run_nestor.py  →  http://127.0.0.1:8765/

Тот же вход у NeSToR.exe: без аргументов — сервер и браузер; `NeSToR.exe catalog …` —
команды локального тестового каталога (как tools/build_test_catalog.py).
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nestor_app.config import load_settings  # noqa: E402
from nestor_app.web import NestorApp  # noqa: E402


def main() -> None:
    from nestor_app.cli import utf8_output
    utf8_output()
    if len(sys.argv) > 1 and sys.argv[1] == "catalog":
        from nestor_app.catalog_cli import main as catalog_main
        raise SystemExit(catalog_main(sys.argv[2:]))
    ap = argparse.ArgumentParser(description="NeSToR — локальный MVP (только 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--var-dir", default=None, help="папка для nestor_users.db и секрета (по умолчанию nestor/var)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--check-staging", action="store_true",
                    help="создать/защитить каталог временных загрузок, проверить ACL и выйти")
    args = ap.parse_args()

    settings = load_settings(args.var_dir)
    if args.check_staging:
        from nestor_app import secure_dir
        chk = secure_dir.prepare_private_dir(settings.staging_dir)
        print(f"Каталог временных загрузок: {chk.path} ({chk.platform})")
        print(f"Доступ разрешён: {', '.join(map(str, chk.principals)) or '—'}")
        print("Проверка пройдена." if chk.ok else "Проблемы: " + "; ".join(chk.problems))
        raise SystemExit(0 if chk.ok else 1)
    if args.port:
        settings = settings.__class__(**{**settings.__dict__, "port": args.port})
    app = NestorApp(settings)
    app.start_maintenance_timer()  # очистка временных загрузок каждый час
    server = app.make_server()
    url = f"http://{settings.host}:{settings.port}/"
    print(f"NeSToR запущен: {url}  (база: {settings.users_db})")
    print(f"Папка данных: {settings.var_dir}")
    if app.staging_check.ok:
        print(f"Временные загрузки: {app.staging_dir} (доступ только текущему пользователю — проверено)")
    else:
        print("ВНИМАНИЕ: загрузка файлов отключена — " + "; ".join(app.staging_check.problems))
    print("Остановить: Ctrl+C")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
