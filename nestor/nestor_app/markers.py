"""Нормализация имён и значений Y-STR-маркеров.

Внутреннее представление профиля: dict[str, tuple[float, ...]]
  ключ — каноническое имя маркера (например "DYS385", "DYS389II", "Y-GATA-H4");
  значение — кортеж аллелей (1 элемент для обычного маркера, несколько — для
  многокопийных DYS385/DYS459/DYS464/YCAII/CDY и т.п.), отсортированный.
Позиция профиля может быть без значения (None: пусто, 0, «-», NA …) или с
нераспознанным значением (Invalid — исходная строка сохраняется). Такие позиции
остаются в профиле: они входят в пересечение панелей и учитываются в GD
отдельной категорией missing_or_invalid.
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
    "A10": "Y-GATA-A10", "GATAA10": "Y-GATA-A10", "YGATAA10": "Y-GATA-A10", "Y-GATA-A10": "Y-GATA-A10",
    "GGAAT1B07": "Y-GGAAT-1B07", "YGGAAT1B07": "Y-GGAAT-1B07", "Y-GGAAT-1B07": "Y-GGAAT-1B07",
    "DYS385A/B": "DYS385", "DYS385AB": "DYS385",
}

_MISSING = {"", "0", "-", "—", "NA", "N/A", "NULL", "NONE", "?", "NAN"}
_SUFFIX_RE = re.compile(r"^(.+?)[-_ ]?([A-D])$")
_NUM_RE = re.compile(r"^\d{1,3}(\.\d)?$")


class MarkerError(ValueError):
    pass


class Invalid(str):
    """Нераспознанное значение позиции; хранится исходная строка."""


Value = "tuple[float, ...] | None | Invalid"


def is_observed(value) -> bool:
    """Корректный вызов: кортеж чисел (не None и не Invalid)."""
    return isinstance(value, tuple)


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


def parse_entry(raw: object):
    """Значение позиции: кортеж, None (нет значения) или Invalid (не распознано)."""
    try:
        return parse_value(raw)
    except MarkerError:
        return Invalid(str(raw).strip())


def normalize_entries(raw_markers: dict[str, object]) -> dict:
    """Как normalize(), но сохраняет позиции без значения (None) и нераспознанные (Invalid).

    Копии a/b/c/d сводятся к одному локусу; если хотя бы одна копия не распознана
    или часть копий отсутствует, позиция целиком — Invalid с исходными строками.
    """
    singles: dict[str, object] = {}
    copies: dict[str, list[tuple[str, object]]] = {}
    for raw_name, raw_value in raw_markers.items():
        name, suffix = canonical_name(raw_name)
        if suffix is not None:
            copies.setdefault(name, []).append((suffix, raw_value))
            continue
        if name in singles or name in copies:
            raise MarkerError(f"маркер {name} указан дважды")
        singles[name] = parse_entry(raw_value)
    for name, parts in copies.items():
        if name in singles:
            raise MarkerError(f"маркер {name} указан дважды")
        parsed = [parse_entry(v) for _, v in sorted(parts)]
        if all(p is None for p in parsed):
            singles[name] = None
        elif all(is_observed(p) for p in parsed):
            singles[name] = tuple(sorted(x for p in parsed for x in p))
        else:
            singles[name] = Invalid(";".join(f"{sfx}={str(v).strip()}" for sfx, v in sorted(parts)))
    return {k: (tuple(sorted(v)) if is_observed(v) else v) for k, v in singles.items()}


def normalize(raw_markers: dict[str, object]) -> dict[str, tuple[float, ...]]:
    """Нормализует словарь {имя: значение} в каноническое представление (только корректные значения)."""
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


def parse_table_entries(text: str) -> dict:
    """Таблица из двух строк: заголовки локусов и значения; разделитель ';', TAB или ','.

    Формат синтетических контрольных CSV архива (tests/fixtures/archive_examples).
    Пустая ячейка — позиция без значения; нераспознанное значение — Invalid.
    Для пар значений внутри ячейки используется '-' (например 13-13).
    """
    lines = [ln.strip().lstrip("\ufeff") for ln in text.splitlines() if ln.strip()]
    if len(lines) != 2:
        raise MarkerError("ожидается таблица из двух строк: заголовки локусов и значения одного профиля")
    sep = next((c for c in (";", "\t", ",") if c in lines[0]), None)
    if sep is None:
        raise MarkerError("не найден разделитель столбцов (';', TAB или ',')")
    header = [h.strip() for h in lines[0].split(sep)]
    values = [v.strip() for v in lines[1].split(sep)]
    if len(values) > len(header):
        raise MarkerError("значений больше, чем заголовков")
    values += [""] * (len(header) - len(values))
    raw: dict[str, str] = {}
    for h, v in zip(header, values):
        if not h:
            continue
        if h in raw:
            raise MarkerError(f"заголовок {h} повторяется")
        raw[h] = v
    entries = normalize_entries(raw)
    if not any(is_observed(v) for v in entries.values()):
        raise MarkerError("в профиле нет ни одного маркера со значением")
    return entries


def looks_like_table(text: str) -> bool:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return "=" not in first and ":" not in first and any(c in first for c in (";", "\t", ","))


def parse_profile_input(text: str) -> dict:
    """Ручной ввод 'МАРКЕР=значение' или вставленная таблица (заголовки + значения)."""
    return parse_table_entries(text) if looks_like_table(text) else parse_manual_entries(text)


def parse_manual_entries(text: str) -> dict:
    """Ручной ввод с сохранением пропусков и нераспознанных значений.

    Строки или пары через ';' вида `DYS393=13`, `DYS385 = 11-14`, `DYS19=` (нет значения).
    Это не формат импорта файлов (FTDNA CSV / Genopoisk / Strelka XLSX будут
    перенесены из архива вместе с контрольными файлами), а форма ручного ввода.
    """
    entries = normalize_entries(_split_manual(text))
    if not any(is_observed(v) for v in entries.values()):
        raise MarkerError("в профиле нет ни одного маркера со значением")
    return entries


def _split_manual(text: str) -> dict[str, str]:
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
    return raw


def parse_manual_text(text: str) -> dict[str, tuple[float, ...]]:
    """Строгий ручной ввод: только корректные значения; нераспознанное — ошибка."""
    markers = normalize(_split_manual(text))
    if not markers:
        raise MarkerError("в профиле нет ни одного маркера со значением")
    return markers


def format_value(value: tuple[float, ...]) -> str:
    return "-".join(str(int(v)) if v.is_integer() else str(v) for v in value)


def display_value(value) -> str:
    if is_observed(value):
        return format_value(value)
    if value is None:
        return ""
    return "?" + str(value)


def canonical_string(markers: dict) -> str:
    """Стабильная строка профиля (для ключа гостевой выборки); пропуски — 'K=', нераспознанные — 'K=?…'."""
    return ";".join(f"{k}={display_value(markers[k])}" for k in sorted(markers))


def to_storage(value) -> tuple[str, str]:
    """(значение, статус): ('13','ok') | ('','missing') | (исходная строка,'invalid')."""
    if is_observed(value):
        return format_value(value), "ok"
    if value is None:
        return "", "missing"
    return str(value), "invalid"


def from_storage(text: str, status: str = "ok"):
    if status == "missing":
        return None
    if status == "invalid":
        return Invalid(text)
    return tuple(float(x) for x in text.split("-"))
