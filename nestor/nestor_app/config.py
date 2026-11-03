"""Пути и настройки локального запуска."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

NESTOR_ROOT = Path(__file__).resolve().parent.parent

# Доля совпадений, которую видит гость (только среди профилей с разрешённым поиском).
GUEST_FRACTION = 0.20
# Параметры поиска по умолчанию.
DEFAULT_MAX_GD = 4
DEFAULT_MIN_COMMON = 12
MAX_ALLOWED_GD = 10


@dataclass(frozen=True)
class Settings:
    var_dir: Path
    users_db: Path
    secret_file: Path
    manifest_file: Path
    host: str = "127.0.0.1"
    staging_dir: Path | None = None  # временные загрузки; по умолчанию var/staging
    port: int = 8765


def load_settings(var_dir: str | os.PathLike | None = None) -> Settings:
    base = Path(var_dir or os.environ.get("NESTOR_VAR_DIR") or NESTOR_ROOT / "var")
    base.mkdir(parents=True, exist_ok=True)
    return Settings(
        var_dir=base,
        users_db=base / "nestor_users.db",
        secret_file=base / "server_secret.key",
        manifest_file=NESTOR_ROOT / "data" / "MANIFEST.json",
        staging_dir=base / "staging",
        port=int(os.environ.get("NESTOR_PORT", "8765")),
    )


def load_or_create_secret(path: Path) -> bytes:
    """Серверный секрет для детерминированной гостевой выборки.

    Создаётся один раз при первом запуске и хранится локально (в git не попадает).
    Смена секрета меняет все гостевые выборки.
    """
    if path.exists():
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    data = secrets.token_bytes(32)
    path.write_bytes(data)
    return data
