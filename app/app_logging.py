"""
GENOPOISK CRM — настройка логирования фоновых процессов (раздел 15/28 ТЗ).

Ошибки сети в Telegram poller не должны ронять приложение (см.
telegram_poller.py), но должны быть видны оператору/разработчику ПОСЛЕ
факта — статус-бар показывает сообщение всего несколько секунд, поэтому
дополнительно ведётся файловый лог в %APPDATA%/GENOPOISK_CRM/logs/app.log.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .db import get_app_data_dir

_configured = False


def setup_logging() -> None:
    """Идемпотентно настраивает файловый handler для логгера приложения.
    Безопасно вызывать многократно (напр. в тестах) — второй вызов ничего не делает."""
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = get_app_data_dir().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    logger = logging.getLogger("genopoisk_crm")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"genopoisk_crm.{name}")
