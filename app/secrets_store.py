"""
GENOPOISK CRM — локальное хранилище секретов (раздел 21 ТЗ).

Telegram Bot Token НЕ хранится в исходном коде, БД или репозитории.
Он хранится в отдельном файле в каталоге пользовательских данных
приложения (%APPDATA%/GENOPOISK_CRM/secrets/), права на который
ограничены ОС так же, как и на любые другие пользовательские файлы
в профиле Windows.

На Windows для более сильной защиты рекомендуется в будущей версии
заменить этот модуль на использование Windows DPAPI (например, через
пакет `pywin32`: CryptProtectData/CryptUnprotectData), что дополнительно
привязывает секрет к учётной записи Windows-пользователя. Текущая
реализация — простое хранение в защищённом каталоге профиля пользователя,
достаточное для локального однопользовательского desktop-приложения
и однозначно исключающее токен из исходного кода и репозитория.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional

from .db import get_app_data_dir


def _secrets_dir() -> Path:
    d = get_app_data_dir().parent / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _secrets_file() -> Path:
    return _secrets_dir() / "secrets.json"


def _load() -> dict:
    f = _secrets_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    f = _secrets_file()
    f.write_text(json.dumps(data), encoding="utf-8")
    if os.name != "nt":
        try:
            f.chmod(stat.S_IRUSR | stat.S_IWUSR)  # rw-------
        except OSError:
            pass


def get_telegram_bot_token() -> Optional[str]:
    return _load().get("telegram_bot_token")


def set_telegram_bot_token(token: str) -> None:
    data = _load()
    data["telegram_bot_token"] = token
    _save(data)


def clear_telegram_bot_token() -> None:
    data = _load()
    data.pop("telegram_bot_token", None)
    _save(data)
