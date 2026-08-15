"""
GENOPOISK CRM — вкладка «Гаплогруппы»: чистая логика сравнения предикций.

Не зависит от GUI/БД — сравнивает две строки предикции (NevGen и Semargl)
и определяет цветовую индикацию строки таблицы:

  GREEN  — терминальный SNP из предикции NevGen встречается в строке Semargl
           (предикции согласованы).
  YELLOW — совпадает корневая (базовая) гаплогруппа, но SNP не найден
           (различие в глубине ветви).
  RED    — корневые гаплогруппы разные (разные ветви, нужна проверка).
  NONE   — недостаточно данных для сравнения (одно из полей пустое).

Формат предикций — цепочка маркеров через дефис/">"/пробел, напр.
"R1a-Z93-Z94" или "R1a > Z93 > Z94": первый токен — корневая гаплогруппа,
последний — терминальный (самый глубокий) SNP.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

_TOKEN_SPLIT_RE = re.compile(r"[\-,>\s]+")


class HaploColor(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    NONE = "none"


def _tokens(value: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT_RE.split(value.strip()) if t]


def haplo_root(value: str) -> str:
    """Первый токен цепочки — корневая (базовая) гаплогруппа."""
    toks = _tokens(value)
    return toks[0] if toks else ""


def haplo_terminal_snp(value: str) -> str:
    """Последний токен цепочки — терминальный (самый глубокий) SNP."""
    toks = _tokens(value)
    return toks[-1] if toks else ""


def calculate_haplo_color(nevgen: Optional[str], semargl: Optional[str]) -> HaploColor:
    nevgen = (nevgen or "").strip()
    semargl = (semargl or "").strip()
    if not nevgen or not semargl:
        return HaploColor.NONE

    snp = haplo_terminal_snp(nevgen)
    if snp and snp.lower() in semargl.lower():
        return HaploColor.GREEN

    if haplo_root(nevgen).lower() == haplo_root(semargl).lower():
        return HaploColor.YELLOW

    return HaploColor.RED
