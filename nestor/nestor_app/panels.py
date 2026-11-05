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
import re
from dataclasses import dataclass
from pathlib import Path

from .markers import canonical_name, is_observed

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "panels_archive.json"

# Число копий для справки (allele_count); на GD не влияет.
_COPIES = {"DYS385": 2, "DYS459": 2, "DYS464": 4, "YCAII": 2, "CDY": 2, "DYF395S1": 2,
           "DYS413": 2, "DYF387S1": 2, "DYS527": 2, "DYF404S1": 1}

MULTICOPY_LOCI = tuple(sorted(k for k, n in _COPIES.items() if n > 1))

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


def _cell_fields(name: str, copies: int) -> list[tuple[str, str]]:
    """Окошки одного локуса: (поле как у копий в плоском списке, подпись): DYS385A → DYS385a."""
    if copies == 1:
        return [(name, name)]
    return [(f"{name}{_COPY_SUFFIXES[i]}", f"{name}{_COPY_SUFFIXES[i].lower()}") for i in range(copies)]


def input_cells() -> list[dict]:
    """Все окошки ручного ввода: сначала порядок FTDNA Y111, затем локусы других панелей."""
    cells: dict[str, dict] = {}
    for code in ("FTDNA_Y111", *PANELS):
        panel = PANELS[code]
        for name, copies in panel.markers:
            for field, label in _cell_fields(name, copies):
                cell = cells.setdefault(field, {"field": field, "label": label, "locus": name, "panels": []})
                if code not in cell["panels"]:
                    cell["panels"].append(code)
    return list(cells.values())


def panel_orders() -> dict[str, list[str]]:
    """Порядок окошек каждой панели: по нему раскладывается список значений."""
    return {code: [f for name, copies in panel.markers for f, _ in _cell_fields(name, copies)] for code, panel in PANELS.items()}


def markers_from_cells(values: dict[str, str]) -> dict:
    """Профиль из окошек ввода. Пустые локусы пропускаются; правила копий те же, что у списка значений."""
    from .markers import normalize_entries
    raw: dict[str, str] = {}
    by_locus: dict[str, list[str]] = {}
    for cell in input_cells():
        by_locus.setdefault(cell["locus"], []).append(cell["field"])
    for fields in by_locus.values():
        entered = {f: (values.get(f) or "").strip() for f in fields}
        if any(v and v != "0" for v in entered.values()):
            raw.update(entered)
    return normalize_entries(raw)


def panel_label(panel_code: str | None, basis: str) -> str:
    if not panel_code:
        return "пользовательский набор (панель неизвестна, позиции — только указанные)"
    title = PANELS[panel_code].title if panel_code in PANELS else panel_code
    return f"{title} ({'выбрана' if basis == 'selected' else 'распознана'})"


# ---------- плоский список аллелей (только при явно выбранной панели) ----------

_FLAT_TOKEN = re.compile(r"^\d{1,3}(\.\d+)?$")
_COPY_SUFFIXES = "ABCD"


def looks_like_flat_list(text: str) -> bool:
    """Только числа, разделённые пробелами / переводами строк (без имён локусов и разделителей таблиц)."""
    tokens = text.split()
    return len(tokens) > 1 and all(_FLAT_TOKEN.match(t) for t in tokens)


def parse_flat_values(text: str, panel_code: str | None) -> dict:
    """Список значений по порядку и числу позиций аллелей выбранной панели.

    Панель должна быть выбрана явно: при AUTO / пользовательском наборе состав по
    числу значений не угадывается. «0» — нет значения. Многокопийный локус берёт
    столько значений, сколько у него копий в реестре панели; неполный набор копий
    обрабатывается общими правилами (все пусто — нет значения; часть — не распознано).
    """
    code = (panel_code or "").strip().upper()
    if code in ("", "AUTO", CUSTOM):
        raise PanelMismatch("значения без названий локусов: выберите панель (например FTDNA Y111) — "
                            "по числу значений панель не определяется")
    panel = get_panel(code)
    tokens = text.split()
    if len(tokens) != panel.allele_count:
        raise PanelMismatch(f"для панели {panel.title} нужно {panel.allele_count} значений по порядку панели, "
                            f"введено {len(tokens)}")
    from .markers import normalize_entries
    raw: dict[str, str] = {}
    pos = 0
    for name, copies in panel.markers:
        chunk = tokens[pos:pos + copies]
        pos += copies
        if copies == 1:
            raw[name] = chunk[0]
        else:
            for i, v in enumerate(chunk):
                raw[f"{name}{_COPY_SUFFIXES[i]}"] = v
    return normalize_entries(raw)
