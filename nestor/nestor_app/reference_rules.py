"""Профиль для сравнения из сырой записи научного справочника.

Сырая запись (строки ячеек первичной таблицы) не меняется: функция строит
отдельное представление для сравнения и перечисляет применённые правила.
Модуль не подключён к пользовательскому поиску.

Правила (data/transform_rules.json):
  T09-del-excluded       'del' хранится как есть; локус не участвует в сравнении,
                         пока смысл обозначения не подтверждён первично;
  T10-binary-float       '33.200000000000003' → 33.2 только для сравнения
                         (то же двоичное число; дробная часть не округляется, T18);
  T11-annotation-codes   пометки '*' и '**' снимаются для сравнения числа,
                         но сохраняются как флаги локуса;
  T08-father-son         запись с father_son_substitution — не независимое
                         наблюдение сына: помечается и по умолчанию отделяется
                         от обычных профилей.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UNCONFIRMED_CODES = {"del"}            # смысл не подтверждён первичным источником
ANNOTATION_CODES = ("**", "*")         # порядок важен: сначала '**'
_NUM = re.compile(r"^\d+(\.\d+)?$")


class RawValueError(ValueError):
    pass


@dataclass
class ComparisonProfile:
    markers: dict[str, tuple[float, ...]]
    excluded_loci: dict[str, str] = field(default_factory=dict)      # локус → причина
    locus_flags: dict[str, list[str]] = field(default_factory=dict)  # локус → ['*'] и т.п.
    independent_observation: bool = True
    record_flags: list[str] = field(default_factory=list)
    rules_applied: list[str] = field(default_factory=list)


def _number(text: str) -> tuple[float, bool]:
    """Число для сравнения; второй элемент — была ли нормализована двоичная дробь."""
    if not _NUM.match(text):
        raise RawValueError(f"нечисловое значение: {text!r}")
    # Нормализуется только техническое представление (T18): float('33.200000000000003')
    # — то же двоичное число, что 33.2; округления нет, дробная часть сохраняется.
    value = float(text)
    return value, "." in text and repr(value) != text


def comparison_profile(raw: dict[str, str], annotations: dict[str, str] | None = None) -> ComparisonProfile:
    """raw: {локус: строка ячейки как в первичной таблице}; annotations: {поле: значение}."""
    annotations = annotations or {}
    prof = ComparisonProfile(markers={})
    rules: set[str] = set()
    for locus, cell in raw.items():
        text = str(cell).strip()
        if not text:
            continue
        if text.lower() in UNCONFIRMED_CODES:
            prof.excluded_loci[locus] = f"обозначение {text!r}: смысл не подтверждён"
            rules.add("T09-del-excluded")
            continue
        flags = []
        for code in ANNOTATION_CODES:
            if text.endswith(code):
                flags.append(code)
                text = text[: -len(code)].strip()
                rules.add("T11-annotation-codes")
                break
        values = []
        for part in re.split(r"[,/]", text):
            num, normalized = _number(part.strip())
            if normalized:
                rules.add("T10-binary-float")
            values.append(num)
        prof.markers[locus] = tuple(sorted(values))
        if flags:
            prof.locus_flags[locus] = flags
    if annotations.get("father_son_substitution") == "true":
        prof.independent_observation = False
        prof.record_flags.append("father_son_substitution")
        rules.add("T08-father-son")
    prof.rules_applied = sorted(rules)
    return prof


def split_for_matching(profiles: dict[str, ComparisonProfile]) -> tuple[dict, dict]:
    """Обычные профили и помеченные (не независимые наблюдения) — раздельно, без смешивания."""
    regular = {k: p for k, p in profiles.items() if p.independent_observation}
    flagged = {k: p for k, p in profiles.items() if not p.independent_observation}
    return regular, flagged
