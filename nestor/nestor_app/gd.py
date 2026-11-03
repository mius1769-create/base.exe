"""Генетическая дистанция (GD) между двумя Y-STR-профилями.

Профиль: {локус: значение}, где значение — кортеж аллелей (корректный вызов),
None (позиция есть в панели, значения нет) или markers.Invalid (не распознано).
Исходный профиль не меняется: GD строится по отдельному представлению.

Правила NeSToR (data/transform_rules.json, решения заказчика 2026-11-03):

T16 DYS389  — исходные DYS389I и DYS389II не меняются. В GD входят DYS389I и
              производный DYS389B = DYS389II − DYS389I (помечается как вычисленный);
              позиция DYS389II заменяется позицией DYS389B. Если DYS389I или
              DYS389II нет / не распознан, DYS389B — без значения / не распознан.
              Опубликованный DYS389B (разность) используется как есть.
T17 копии   — разное число копий не даёт +1; локус не входит ни в GD, ни в compared.
              Порядок копий не фиксирован. DYS385 — пара; у DYF404S1 и DYS527
              допускается разное подтверждённое число значений.
T18 дроби   — без округления; точное совпадение — 0; разные значения, из которых
              хотя бы одно дробное, в шаги не переводятся; GD предварительный.

Классификация позиции из пересечения панелей (panel_overlap) — взаимоисключающая,
в этом порядке:
  1. user_excluded          — исключена настройкой пользователя;
  2. missing_or_invalid     — у одного или обоих профилей нет значения или оно не распознано;
  3. copy_count_differences — корректные вызовы у обоих, разное число копий;
  4. allele_differences     — дробное различие без подтверждённого перевода в шаги;
  5. compared               — вошла в численный GD.
panel_overlap = user_excluded + missing_or_invalid + copy_count_differences
                + allele_differences + compared. Порог минимума маркеров — по compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .markers import Invalid, canonical_name, is_observed

Profile = dict


@dataclass(frozen=True)
class GDResult:
    gd: int                                   # численный GD по compared
    compared: int                             # позиции, вошедшие в численный GD (порог minMarkers)
    panel_overlap: int = 0                    # общие позиции панелей (после алиасов и T16)
    preliminary: bool = False                 # есть дробные различия без перевода в шаги
    user_excluded: tuple = ()                 # локусы, исключённые пользователем
    missing_or_invalid: tuple = ()            # (локус, причина)
    copy_count_differences: tuple = ()        # (локус, копий у a, копий у b)
    allele_differences: tuple = ()            # (локус, значения a, значения b)
    derived_loci: tuple = ()                  # вычисленные правилом позиции (DYS389B)
    per_locus: dict = field(default_factory=dict, compare=False)


def gd_view(profile: Profile) -> tuple[Profile, tuple[str, ...]]:
    """Представление профиля для GD (T16). Исходный профиль не меняется."""
    view = dict(profile)
    derived: list[str] = []
    if "DYS389II" in view:
        ii = view.pop("DYS389II")
        if "DYS389B" not in view:
            i = view.get("DYS389I")
            if is_observed(i) and is_observed(ii) and len(i) == 1 and len(ii) == 1 and ii[0] >= i[0]:
                view["DYS389B"] = (ii[0] - i[0],)
                derived.append("DYS389B")
            elif (ii is None or i is None) and not isinstance(ii, Invalid) and not isinstance(i, Invalid):
                view["DYS389B"] = None
            else:
                view["DYS389B"] = Invalid(f"DYS389II−DYS389I не вычисляется (I={i!s}, II={ii!s})")
    return view, tuple(derived)


def normalize_excluded(names) -> frozenset[str]:
    """Имена исключённых локусов → канонические; DYS389II означает позицию DYS389B (T16)."""
    out = set()
    for raw in names or ():
        raw = str(raw).strip()
        if not raw:
            continue
        name, _ = canonical_name(raw)
        out.add("DYS389B" if name == "DYS389II" else name)
    return frozenset(out)


def _is_int(x: float) -> bool:
    return float(x).is_integer()


def compare_locus(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[str, int]:
    """Для корректных вызовов: ('steps', n) | ('copy_count', 0) | ('fractional', 0)."""
    sa, sb = sorted(a), sorted(b)
    if len(sa) != len(sb):
        return "copy_count", 0
    if sa == sb:
        return "steps", 0
    if not all(_is_int(x) for x in sa + sb):
        return "fractional", 0
    return "steps", int(sum(abs(x - y) for x, y in zip(sa, sb)))


def _missing_reason(va, vb) -> str:
    if isinstance(va, Invalid) or isinstance(vb, Invalid):
        return "не распознано"
    if va is None and vb is None:
        return "нет значения у обоих"
    return "нет значения у одного"


def genetic_distance(a: Profile, b: Profile, excluded=()) -> GDResult:
    va, da = gd_view(a)
    vb, db = gd_view(b)
    excl = normalize_excluded(excluded)
    overlap = sorted(set(va) & set(vb))
    gd, compared = 0, 0
    user, missing, copies, fractional, per = [], [], [], [], {}
    for locus in overlap:
        x, y = va[locus], vb[locus]
        if locus in excl:
            per[locus] = ("user_excluded", 0)
            user.append(locus)
            continue
        if not (is_observed(x) and is_observed(y)):
            per[locus] = ("missing_or_invalid", 0)
            missing.append((locus, _missing_reason(x, y)))
            continue
        kind, steps = compare_locus(x, y)
        if kind == "copy_count":
            per[locus] = ("copy_count", 0)
            copies.append((locus, len(x), len(y)))
        elif kind == "fractional":
            per[locus] = ("fractional", 0)
            fractional.append((locus, x, y))
        else:
            per[locus] = ("compared", steps)
            gd += steps
            compared += 1
    derived = tuple(sorted(set(da) | set(db)))
    return GDResult(gd=gd, compared=compared, panel_overlap=len(overlap), preliminary=bool(fractional),
                    user_excluded=tuple(user), missing_or_invalid=tuple(missing),
                    copy_count_differences=tuple(copies), allele_differences=tuple(fractional),
                    derived_loci=derived, per_locus=per)


def marker_distance(a: tuple[float, ...], b: tuple[float, ...]) -> int | None:
    """Шаги по одному локусу; None — локус не входит в численный GD (T17/T18)."""
    kind, steps = compare_locus(a, b)
    return steps if kind == "steps" else None
