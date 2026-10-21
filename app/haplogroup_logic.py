"""
GENOPOISK CRM — вкладка «Гаплогруппы»: чистая логика сравнения предикций.

Не зависит от GUI/БД. Цветовая индикация в CRM НЕ строит филогению и НЕ
пытается определить родство/вложенность субкладов (для этого нет доступа
к YFull/ISOGG, и это отдельная аналитическая работа оператора) — её
единственная задача: быстро подсветить возможную ошибку загрузки
STR-профиля, ошибку ввода или ситуацию, когда разные предикторы относят
образец к разным КРУПНЫМ гаплогруппам.

  GREEN — NevGen и Semargl относятся к одной крупной гаплогруппе (совпадает
          ведущая буква корня первого токена, напр. "R-L1029" и "R-Z93" —
          оба "R"; "Z93" и "Z2103" при этом НЕ сравниваются между собой —
          является ли один субклад предком другого, CRM не определяет).
  RED   — NevGen и Semargl относятся к разным крупным гаплогруппам.
  NONE  — хотя бы одна из предикций (NevGen или Semargl) не заполнена.

Сравнение НЕ анализирует терминальные SNP, их взаимное вложение и не
использует поле Y-ДНК — только ведущую букву корневой гаплогруппы первого
токена каждой предикции.

Формат предикций — цепочка маркеров через дефис/">"/пробел, напр.
"R1a-Z93-Z94" или "R1a > Z93 > Z94": первый токен — корневая гаплогруппа.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

_TOKEN_SPLIT_RE = re.compile(r"[\-,>\s]+")
_LEADING_LETTERS_RE = re.compile(r"[A-Za-z]+")


class HaploColor(str, Enum):
    GREEN = "green"
    RED = "red"
    NONE = "none"


def haplo_major_letter(value: str) -> str:
    """Ведущая буквенная часть корневой (крупной) гаплогруппы первого
    токена цепочки, напр. 'R1a-L1029' -> 'R', 'R-Z93' -> 'R',
    'I-CTS10228' -> 'I', 'N-Y6503' -> 'N'."""
    first_token = next((t for t in _TOKEN_SPLIT_RE.split(value.strip()) if t), "")
    m = _LEADING_LETTERS_RE.match(first_token)
    return m.group(0) if m else ""


def calculate_haplo_color(nevgen: Optional[str], semargl: Optional[str]) -> HaploColor:
    nevgen = (nevgen or "").strip()
    semargl = (semargl or "").strip()
    if not nevgen or not semargl:
        return HaploColor.NONE

    if haplo_major_letter(nevgen).lower() == haplo_major_letter(semargl).lower():
        return HaploColor.GREEN

    return HaploColor.RED
