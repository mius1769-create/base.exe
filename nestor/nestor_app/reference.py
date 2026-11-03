"""Научный справочник Y-STR — отдельная SQLite-база только для чтения.

Справочник НЕ подключён: он подключается только после сверки снимков
(45 389 профилей по RELEASE_VALIDATION.json против 35 284 в локальном
Nestor_scientific_YSTR.db) и фиксации выбранного снимка в data/MANIFEST.json
с SHA-256. Этот модуль реализует только «замок»: без манифеста или при
несовпадении контрольной суммы база не открывается; открывается в режиме ro.
Схема запросов к справочнику будет написана после аудита архива.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

REQUIRED_MANIFEST_FIELDS = ("file", "sha256", "profiles", "source", "selected_reason")


class ReferenceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ReferenceStatus:
    connected: bool
    reason: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        raise ReferenceUnavailable(
            "научный справочник не подключён: нет data/MANIFEST.json (ждёт сверки версий 45 389 / 35 284)"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_MANIFEST_FIELDS if f not in manifest]
    if missing:
        raise ReferenceUnavailable(f"в манифесте нет полей: {', '.join(missing)}")
    return manifest


def open_reference(manifest_path: Path) -> sqlite3.Connection:
    manifest = load_manifest(manifest_path)
    db_path = (manifest_path.parent / manifest["file"]).resolve()
    if not db_path.exists():
        raise ReferenceUnavailable(f"файл справочника не найден: {manifest['file']}")
    actual = sha256_file(db_path)
    if actual != manifest["sha256"].lower():
        raise ReferenceUnavailable(
            f"SHA-256 справочника не совпадает с манифестом ({actual[:12]}… ≠ {manifest['sha256'][:12]}…)"
        )
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def status(manifest_path: Path) -> ReferenceStatus:
    try:
        open_reference(manifest_path).close()
    except ReferenceUnavailable as e:
        return ReferenceStatus(False, str(e))
    return ReferenceStatus(True, "справочник подключён (только чтение, SHA-256 сверен)")
