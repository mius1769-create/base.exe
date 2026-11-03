"""Локальный запуск NeSToR: python run_nestor.py  →  http://127.0.0.1:8765/"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nestor_app.config import load_settings  # noqa: E402
from nestor_app.web import NestorApp  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="NeSToR — локальный MVP (только 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--var-dir", default=None, help="папка для nestor_users.db и секрета (по умолчанию nestor/var)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    settings = load_settings(args.var_dir)
    if args.port:
        settings = settings.__class__(**{**settings.__dict__, "port": args.port})
    app = NestorApp(settings)
    app.start_maintenance_timer()  # очистка временных загрузок каждый час
    server = app.make_server()
    url = f"http://{settings.host}:{settings.port}/"
    print(f"NeSToR запущен: {url}  (база: {settings.users_db})")
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
