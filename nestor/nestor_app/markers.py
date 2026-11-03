"""Нормализация имён и значений Y-STR-маркеров.

Внутреннее представление профиля: dict[str, tuple[float, ...]]
  ключ — каноническое имя маркера (например "DYS385", "DYS389II", "Y-GATA-H4");
  значение — кортеж аллелей (1 элемент для обычного маркера, несколько — для
  многокопийных DYS385/DYS459/DYS464/YCAII/CDY и т.п.), отсортированный.
Пустые, нулевые и нечисловые значения считаются отсутствующими и не хранятся.
"""

from __future__ import annotations

import re

# Многокопийные маркеры: суффиксы a/b/c/d в исходных данных сводятся к одному маркеру.
MULTI_COPY = {
    "DYS385", "DYS459", "DYS464", "YCAII", "CDY", "DYF395S1", "DYS413",
    "DYS527", "DYF385S1", "DYF371X", "DYF399X", "DYF397S1", "DYF387S1",
    "DYF401S1", "DYF404S1", "DYF411S1", "DYS724",
}

ALIASES = {
    "DYS389-1": "DYS389I", "DYS389.1": "DYS389I", "DYS389I": "DYS389I",
    "DYS389-2": "DYS389II", "DYS389.2": "DYS389II", "DYS389II": "DYS389II",
    "YGATAH4": "Y-GATA-H4", "Y-GATA-H4": "Y-GATA-H4", "GATAH4": "Y-GATA-H4",
    "GATA-H4": "Y-GATA-H4", "GATAH4.1": "Y-GATA-H4",
    "YCA-II": "YCAII", "YCAII": "YCAII",
}

_MISSING = {"", "0", "-", "—", "NA", "N/A", "NULL", "NONE", "?", "NAN"}
_SUFFIX_RE = re.compile(r"^(.+?)[-_ ]?([A-D])$")
_NUM_RE = re.compile(r"^\d{1,3}(\.\d)?$")


class MarkerError(ValueError):
    pass


def canonical_name(raw: str) -> tuple[str, str | None]:
    """Возвращает (каноническое имя, суффикс копии или None)."""
    name = raw.strip().upper().replace(" ", "")
    if not name:
        raise MarkerError("пустое имя маркера")
    if name in ALIASES:
        return ALIASES[name], None
    m = _SUFFIX_RE.match(name)
    if m and m.group(1) in MULTI_COPY:
        return m.group(1), m.group(2)
    return name, None


def parse_value(raw: object) -> tuple[float, ...] | None:
    """'13' -> (13,), '11-14' / '11,14' / '11/14' -> (11, 14); пусто/0 -> None."""
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text in _MISSING:
        return None
    parts = [p for p in re.split(r"[-,/;\s]+", text) if p]
    values: list[float] = []
    for p in parts:
        if p in _MISSING:
            continue
        if not _NUM_RE.match(p):
            raise MarkerError(f"недопустимое значение аллеля: {raw!r}")
        v = float(p)
        if v <= 0:
            continue
        values.append(v)
    if not values:
        return None
    return tuple(sorted(values))


def normalize(raw_markers: dict[str, object]) -> dict[str, tuple[float, ...]]:
    """Нормализует словарь {имя: значение} в каноническое представление."""
    result: dict[str, list[float]] = {}
    for raw_name, raw_value in raw_markers.items():
        name, suffix = canonical_name(raw_name)
        value = parse_value(raw_value)
        if value is None:
            continue
        if suffix is not None:
            result.setdefault(name, []).extend(value)
        else:
            if name in result:
                raise MarkerError(f"маркер {name} указан дважды")
            result[name] = list(value)
    return {k: tuple(sorted(v)) for k, v in result.items()}


def parse_manual_text(text: str) -> dict[str, tuple[float, ...]]:
    """Ручной ввод: строки или пары через ';' вида `DYS393=13`, `DYS385 = 11-14`.

    Это не формат импорта файлов (FTDNA CSV / Genopoisk / Strelka XLSX будут
    перенесены из архива вместе с контрольными файлами), а форма ручного ввода.
    """
    raw: dict[str, str] = {}
    for chunk in re.split(r"[;\n]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            name, _, value = chunk.partition("=")
        elif ":" in chunk:
            name, _, value = chunk.partition(":")
        else:
            raise MarkerError(f"ожидается 'МАРКЕР=значение': {chunk!r}")
        name = name.strip()
        if name in raw:
            raise MarkerError(f"маркер {name} указан дважды")
        raw[name] = value.strip()
    markers = normalize(raw)
    if not markers:
        raise MarkerError("в профиле нет ни одного маркера со значением")
    return markers


def format_value(value: tuple[float, ...]) -> str:
    return "-".join(str(int(v)) if v.is_integer() else str(v) for v in value)


def canonical_string(markers: dict[str, tuple[float, ...]]) -> str:
    """Стабильная строка профиля (для ключа гостевой выборки)."""
    return ";".join(f"{k}={format_value(markers[k])}" for k in sorted(markers))


def to_storage(value: tuple[float, ...]) -> str:
    return format_value(value)


def from_storage(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split("-"))
