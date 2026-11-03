"""Генетическая дистанция (GD) между двумя Y-STR-профилями.

Модель MVP — пошаговая (stepwise), только по общим маркерам:
  * обычный маркер: |a - b| шагов;
  * микровариант (например 12.1 против 12): разница округляется, но не меньше 1;
  * многокопийный маркер с одинаковым числом копий: сумма разниц отсортированных копий;
  * разное число копий (например DYS464 из 4 и 5 копий): сравниваются общие
    копии по порядку + 1 шаг за каждую лишнюю копию.
Правила (в т.ч. infinite-allele для DYS464/CDY/YCAII, DYS389II-I, порог
сравнимости) должны быть сверены с архивом; модель изолирована в этом модуле.
"""

from __future__ import annotations

from dataclasses import dataclass

Profile = dict[str, tuple[float, ...]]


@dataclass(frozen=True)
class GDResult:
    gd: int
    common: int  # число общих маркеров, по которым выполнено сравнение


def _step(a: float, b: float) -> int:
    if a == b:
        return 0
    return max(1, round(abs(a - b)))


def marker_distance(a: tuple[float, ...], b: tuple[float, ...]) -> int:
    sa, sb = sorted(a), sorted(b)
    shared = min(len(sa), len(sb))
    dist = sum(_step(x, y) for x, y in zip(sa[:shared], sb[:shared]))
    return dist + abs(len(sa) - len(sb))


def genetic_distance(a: Profile, b: Profile) -> GDResult:
    common = sorted(set(a) & set(b))
    return GDResult(gd=sum(marker_distance(a[m], b[m]) for m in common), common=len(common))
