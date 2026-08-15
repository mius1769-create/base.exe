"""
GENOPOISK CRM — вкладка «Гаплогруппы»: чистая логика сравнения предикций.

Не зависит от GUI/БД — сравнивает предикции NevGen и Semargl (плюс
подтверждённое поле Y-ДНК как независимый якорь) и определяет цветовую
индикацию строки таблицы:

  GREEN  — терминальный SNP из предикции NevGen встречается в строке
           Semargl (предикции согласованы на уровне конкретного SNP).
  YELLOW — терминальный SNP не найден в Semargl, но корневая (базовая)
           гаплогруппа поля Y-ДНК совпадает с корневой гаплогруппой
           Semargl (разница в глубине ветви, не в самой ветви).
  RED    — терминальный SNP не найден, и корневая гаплогруппа Y-ДНК не
           совпадает с корневой гаплогруппой Semargl (разные ветви,
           нужна проверка).
  NONE   — недостаточно данных для сравнения (NevGen, Semargl или
           Y-ДНК не заполнены).

ВАЖНО: корень (major-гаплогруппа) для сравнения берётся из поля Y-ДНК —
подтверждённого значения, а НЕ путём сравнения первого токена самих
предикций NevGen/Semargl друг с другом. Прямое сравнение root(NevGen) и
root(Semargl) даёт ложные совпадения: разные записи используют разную
глубину нотации (напр. "R-M458" против "R1a-M458"), из-за чего два
предиктора могут случайно разделить один и тот же терсовый префикс,
указывая на совершенно разные субклады. Y-ДНК — независимый якорь, не
подверженный этой проблеме нотации.

Формат предикций — цепочка маркеров через дефис/">"/пробел, напр.
"R1a-Z93-Z94" или "R1a > Z93 > Z94": первый токен — корневая гаплогруппа,
последний — терминальный (самый глубокий) SNP.

Поиск терминального SNP в строке Semargl — по границе слова (\\b), а не
сырой substring: иначе короткое имя SNP (напр. "M17") ложно совпадало бы
внутри более длинного имени другого SNP (напр. "M170").
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

_TOKEN_SPLIT_RE = re.compile(r"[\-,>\s]+")
_LEADING_LETTERS_RE = re.compile(r"[A-Za-z]+")


class HaploColor(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    NONE = "none"


def _tokens(value: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT_RE.split(value.strip()) if t]


def haplo_terminal_snp(value: str) -> str:
    """Последний токен цепочки — терминальный (самый глубокий) SNP."""
    toks = _tokens(value)
    return toks[-1] if toks else ""


def haplo_major_letter(value: str) -> str:
    """Ведущая буквенная часть корневой гаплогруппы первого токена цепочки,
    напр. 'R1a' -> 'R', 'R-M458' -> 'R', 'I2a' -> 'I', 'I-CTS10228' -> 'I'."""
    toks = _tokens(value)
    if not toks:
        return ""
    m = _LEADING_LETTERS_RE.match(toks[0])
    return m.group(0) if m else ""


def calculate_haplo_color(
    nevgen: Optional[str], semargl: Optional[str], y_dna: Optional[str]
) -> HaploColor:
    nevgen = (nevgen or "").strip()
    semargl = (semargl or "").strip()
    y_dna = (y_dna or "").strip()
    if not nevgen or not semargl or not y_dna:
        return HaploColor.NONE

    snp = haplo_terminal_snp(nevgen)
    if snp and re.search(rf"\b{re.escape(snp)}\b", semargl, re.IGNORECASE):
        return HaploColor.GREEN

    if haplo_major_letter(y_dna).lower() == haplo_major_letter(semargl).lower():
        return HaploColor.YELLOW

    return HaploColor.RED
