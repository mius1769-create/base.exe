"""Панели Y-STR: состав и порядок.

Статусы:
  provisional — порядок FTDNA Y12/Y25/Y37 из открытых описаний; ДОЛЖЕН быть
                сверен с архивом и контрольными файлами до включения импорта;
  unsupported — панель не поддерживается (Y67/Y111 ждут сверки, Y700 вне
                поддержки до появления проверенного формата импорта и сверки).
Genopoisk Y37/Y50 и Strelka появятся после аудита архива.
"""

from __future__ import annotations

from dataclasses import dataclass

# (маркер, число копий) в порядке FTDNA.
_Y12 = [
    ("DYS393", 1), ("DYS390", 1), ("DYS19", 1), ("DYS391", 1), ("DYS385", 2),
    ("DYS426", 1), ("DYS388", 1), ("DYS439", 1), ("DYS389I", 1), ("DYS392", 1),
    ("DYS389II", 1),
]
_Y25_ADD = [
    ("DYS458", 1), ("DYS459", 2), ("DYS455", 1), ("DYS454", 1), ("DYS447", 1),
    ("DYS437", 1), ("DYS448", 1), ("DYS449", 1), ("DYS464", 4),
]
_Y37_ADD = [
    ("DYS460", 1), ("Y-GATA-H4", 1), ("YCAII", 2), ("DYS456", 1), ("DYS607", 1),
    ("DYS576", 1), ("DYS570", 1), ("CDY", 2), ("DYS442", 1), ("DYS438", 1),
]


class UnsupportedPanel(ValueError):
    pass


@dataclass(frozen=True)
class Panel:
    code: str
    vendor: str
    markers: tuple[tuple[str, int], ...]
    status: str  # provisional | verified

    @property
    def allele_count(self) -> int:
        return sum(c for _, c in self.markers)

    @property
    def marker_names(self) -> tuple[str, ...]:
        return tuple(m for m, _ in self.markers)


PANELS: dict[str, Panel] = {
    "FTDNA_Y12": Panel("FTDNA_Y12", "FTDNA", tuple(_Y12), "provisional"),
    "FTDNA_Y25": Panel("FTDNA_Y25", "FTDNA", tuple(_Y12 + _Y25_ADD), "provisional"),
    "FTDNA_Y37": Panel("FTDNA_Y37", "FTDNA", tuple(_Y12 + _Y25_ADD + _Y37_ADD), "provisional"),
}

UNSUPPORTED = {
    "FTDNA_Y67": "ждёт сверки состава с архивом",
    "FTDNA_Y111": "ждёт сверки состава с архивом",
    "Y700": "вне поддержки до появления проверенного формата импорта и сверки",
    "FTDNA_Y700": "вне поддержки до появления проверенного формата импорта и сверки",
    "GENOPOISK_Y37": "состав и порядок будут взяты из архива",
    "GENOPOISK_Y50": "состав и порядок будут взяты из архива",
    "STRELKA": "состав и порядок будут взяты из архива",
}


def get_panel(code: str) -> Panel:
    key = code.strip().upper()
    if key in PANELS:
        return PANELS[key]
    if key in UNSUPPORTED:
        raise UnsupportedPanel(f"панель {key} не поддерживается: {UNSUPPORTED[key]}")
    raise UnsupportedPanel(f"неизвестная панель {code!r}")


def ordered_markers(panel: Panel, markers: dict[str, tuple[float, ...]]) -> list[tuple[str, tuple[float, ...] | None]]:
    """Маркеры профиля в порядке панели; отсутствующие — None."""
    return [(name, markers.get(name)) for name in panel.marker_names]


def missing_markers(panel: Panel, markers: dict) -> list[str]:
    """Позиции панели без корректного значения (нет в профиле, пусто или не распознано)."""
    return [name for name in panel.marker_names if not isinstance(markers.get(name), tuple)]


def best_complete_panel(markers: dict[str, tuple[float, ...]]) -> str | None:
    """Наибольшая поддержанная панель, полностью покрытая профилем."""
    best = None
    for code, panel in PANELS.items():
        if not missing_markers(panel, markers):
            if best is None or panel.allele_count > PANELS[best].allele_count:
                best = code
    return best
