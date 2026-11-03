"""Генетическая дистанция (GD) между двумя Y-STR-профилями.

Правила NeSToR (data/transform_rules.json, утверждены заказчиком 2026-11-03):

T16 DYS389  — исходные DYS389I и DYS389II не меняются. В GD входят DYS389I и
              производный DYS389B = DYS389II − DYS389I (помечается как вычисленный);
              DYS389II сам в GD не входит, чтобы участок I не считался дважды.
              Если профиль уже содержит DYS389B (опубликован как разность), он
              используется как есть.
T17 копии   — при разном числе копий локус НЕ даёт +1 и не входит в численный GD;
              различие числа копий показывается отдельно (copy_count_differences);
              в число фактически сравненных локусов (compared) такой локус НЕ входит. Порядок копий не фиксирован (сравнение по
              отсортированным значениям — оптимальное сопоставление копий).
              DYS385 — пара; у DYF404S1 и DYS527 допускается разное подтверждённое
              число значений.
T18 дроби   — дробная часть не округляется и не отбрасывается. Точное совпадение
              даёт 0. Разные значения, из которых хотя бы одно дробное, не
              переводятся в шаги (нет подтверждённого способа для локуса): разница
              показывается как аллельное различие (allele_differences), в численный
              GD и в compared не входит, результат помечается как предварительный.

Счётчики результата раздельны:
  overlap  — локусы в пересечении профилей (после T16);
  compared — локусы с корректно сравненными значениями, вошедшие в GD;
             именно он используется для порога минимума маркеров;
  copy_count_differences / allele_differences — отдельно, в compared не входят.
Обычные целые значения: |a − b| шагов на копию.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Profile = dict[str, tuple[float, ...]]

@dataclass(frozen=True)
class GDResult:
    gd: int                                   # численный GD по сравненным локусам
    compared: int                             # локусы, фактически вошедшие в GD (порог minMarkers)
    overlap: int = 0                          # локусы в пересечении профилей
    preliminary: bool = False                 # есть дробные различия без перевода в шаги
    copy_count_differences: tuple = ()        # (локус, копий у a, копий у b)
    allele_differences: tuple = ()            # (локус, значения a, значения b) — дробные, без шагов
    derived_loci: tuple = ()                  # локусы, вычисленные правилом (DYS389B)
    per_locus: dict = field(default_factory=dict, compare=False)


def gd_view(profile: Profile) -> tuple[Profile, tuple[str, ...]]:
    """Представление профиля для GD (T16). Исходный профиль не меняется."""
    view = dict(profile)
    derived = []
    if "DYS389B" not in view and "DYS389I" in view and "DYS389II" in view:
        i, ii = view["DYS389I"], view["DYS389II"]
        if len(i) == 1 and len(ii) == 1 and ii[0] >= i[0]:
            view["DYS389B"] = (ii[0] - i[0],)
            derived.append("DYS389B")
    view.pop("DYS389II", None)
    return view, tuple(derived)


def _is_int(x: float) -> bool:
    return float(x).is_integer()


def compare_locus(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[str, int]:
    """('steps', n) | ('copy_count', 0) | ('fractional', 0)."""
    sa, sb = sorted(a), sorted(b)
    if len(sa) != len(sb):
        return "copy_count", 0
    if sa == sb:
        return "steps", 0
    if not all(_is_int(x) for x in sa + sb):
        return "fractional", 0
    return "steps", int(sum(abs(x - y) for x, y in zip(sa, sb)))


def genetic_distance(a: Profile, b: Profile) -> GDResult:
    va, da = gd_view(a)
    vb, db = gd_view(b)
    overlap = sorted(set(va) & set(vb))
    gd, compared, copies, fractional, per = 0, 0, [], [], {}
    for locus in overlap:
        kind, steps = compare_locus(va[locus], vb[locus])
        per[locus] = (kind, steps)
        if kind == "steps":
            gd += steps
            compared += 1
        elif kind == "copy_count":
            copies.append((locus, len(va[locus]), len(vb[locus])))
        else:
            fractional.append((locus, va[locus], vb[locus]))
    derived = tuple(sorted(set(da) | set(db)))
    return GDResult(gd=gd, compared=compared, overlap=len(overlap), preliminary=bool(fractional),
                    copy_count_differences=tuple(copies), allele_differences=tuple(fractional),
                    derived_loci=derived, per_locus=per)


def marker_distance(a: tuple[float, ...], b: tuple[float, ...]) -> int | None:
    """Шаги по одному локусу; None — локус не входит в численный GD (T17/T18)."""
    kind, steps = compare_locus(a, b)
    return steps if kind == "steps" else None
