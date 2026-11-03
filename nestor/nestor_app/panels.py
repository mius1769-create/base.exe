"""Панели Y-STR: состав, порядок, распознавание и приведение профиля к панели.

Источник составов: data/panels_archive.json — копия config/panels.json из
проверенного архива экспертного приложения (SHA-256 .tar.gz 745ca9cd…, файл
822f890e…). FTDNA Y12/Y25/Y37 совпали по составу и порядку с ранее заданными
по открытому описанию FTDNA.

Два режима профиля:
  * известная панель (выбрана пользователем или надёжно распознана) — позиции
    профиля = полный состав панели; не указанные / пустые позиции хранятся как
    «нет значения» и в GD попадают в missing_or_invalid;
  * пользовательский набор (панель неизвестна) — позиции = только заявленные
    локусы; панель показывается как пользовательская/неполная.

Не поддерживаются: Y700 (нет проверенного формата и сверки), Strelka и прочие
панели без утверждённого состава.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .markers import canonical_name, is_observed

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "panels_archive.json"

# Число копий для справки (allele_count); на GD не влияет.
_COPIES = {"DYS385": 2, "DYS459": 2, "DYS464": 4, "YCAII": 2, "CDY": 2, "DYF395S1": 2,
           "DYS413": 2, "DYF387S1": 2, "DYS527": 2, "DYF404S1": 1}

CUSTOM = "CUSTOM"  # пользовательский набор без известной панели
RECOGNITION_MIN_COVERAGE = 0.9


class UnsupportedPanel(ValueError):
    pass


class PanelMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Panel:
    code: str
    title: str
    vendor: str
    markers: tuple[tuple[str, int], ...]
    status: str  # archive_verified | archive

    @property
    def allele_count(self) -> int:
        return sum(c for _, c in self.markers)

    @property
    def marker_names(self) -> tuple[str, ...]:
        return tuple(m for m, _ in self.markers)


def _load() -> dict[str, Panel]:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    out = {}
    for title, names in data["panels"].items():
        vendor, _, size = title.partition(" ")
        code = f"{vendor.upper()}_{size.upper()}"
        canon = tuple(canonical_name(n)[0] for n in names)
        status = "archive_verified" if code in ("FTDNA_Y12", "FTDNA_Y25", "FTDNA_Y37") else "archive"
        out[code] = Panel(code, title, vendor, tuple((n, _COPIES.get(n, 1)) for n in canon), status)
    return out


PANELS: dict[str, Panel] = _load()

UNSUPPORTED = {
    "Y700": "вне поддержки до появления проверенного формата импорта и сверки",
    "FTDNA_Y700": "вне поддержки до появления проверенного формата импорта и сверки",
    "STRELKA": "состав и правила панели Strelka не утверждены",
    "STRELKA_Y111": "состав и правила панели Strelka не утверждены",
}


def get_panel(code: str) -> Panel:
    key = code.strip().upper().replace(" ", "_")
    if key in PANELS:
        return PANELS[key]
    if key in UNSUPPORTED:
        raise UnsupportedPanel(f"панель {key} не поддерживается: {UNSUPPORTED[key]}")
    raise UnsupportedPanel(f"неизвестная панель {code!r}")


def ordered_markers(panel: Panel, markers: dict) -> list[tuple[str, object]]:
    """Маркеры профиля в порядке панели; отсутствующие — None."""
    return [(name, markers.get(name)) for name in panel.marker_names]


def missing_markers(panel: Panel, markers: dict) -> list[str]:
    """Позиции панели без корректного значения (нет в профиле, пусто или не распознано)."""
    return [name for name in panel.marker_names if not is_observed(markers.get(name))]


def best_complete_panel(markers: dict) -> str | None:
    """Наибольшая поддержанная панель, полностью покрытая корректными значениями."""
    best = None
    for code, panel in PANELS.items():
        if not missing_markers(panel, markers):
            if best is None or panel.allele_count > PANELS[best].allele_count:
                best = code
    return best


def recognize_panel(loci) -> str | None:
    """Надёжное распознавание по заявленным локусам (значения не важны).

    Панель считается распознанной, если все заявленные локусы входят в неё и
    покрывают не меньше 90% её позиций; из подходящих берётся наименьшая
    (FTDNA Y12 ⊂ Y25 ⊂ Y37 ⊂ Y67 ⊂ Y111). Если подходят несколько панелей
    одного размера, распознавание не выполняется.
    """
    declared = set(loci)
    if not declared:
        return None
    fits = []
    for code, panel in PANELS.items():
        names = set(panel.marker_names)
        if declared <= names and len(declared) / len(names) >= RECOGNITION_MIN_COVERAGE:
            fits.append((len(names), code))
    if not fits:
        return None
    fits.sort()
    if len(fits) > 1 and fits[0][0] == fits[1][0]:
        return None
    return fits[0][1]


def apply_panel(markers: dict, panel_code: str | None) -> tuple[dict, str | None, str]:
    """Привести профиль к режиму панели.

    panel_code: код панели, 'AUTO' (распознать) или None/CUSTOM (пользовательский набор).
    Возвращает (позиции профиля, код панели или None, основание: selected | recognized | custom).
    Для известной панели недостающие позиции добавляются как None; локус вне
    выбранной панели — ошибка (значения не переносятся молча).
    """
    code = (panel_code or "").strip().upper()
    basis = "selected"
    if code in ("", CUSTOM):
        return dict(markers), None, "custom"
    if code == "AUTO":
        code = recognize_panel(markers.keys())
        if code is None:
            return dict(markers), None, "custom"
        basis = "recognized"
    panel = get_panel(code)
    extra = sorted(set(markers) - set(panel.marker_names))
    if extra:
        raise PanelMismatch(f"локусы вне панели {panel.title}: {', '.join(extra)} — выберите другую панель "
                            f"или «пользовательский набор»")
    out = {name: markers.get(name) for name in panel.marker_names}
    return out, panel.code, basis


def panel_label(panel_code: str | None, basis: str) -> str:
    if not panel_code:
        return "пользовательский набор (панель неизвестна, позиции — только указанные)"
    title = PANELS[panel_code].title if panel_code in PANELS else panel_code
    return f"{title} ({'выбрана' if basis == 'selected' else 'распознана'})"
