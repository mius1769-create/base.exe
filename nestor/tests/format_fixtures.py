"""Синтетические файлы форматов импорта (tests/fixtures/formats). Не реальные люди и не научные данные.

  python tests/format_fixtures.py      # пересоздать tests/fixtures/formats

Значения условные и детерминированные: по имени локуса. Состав панелей берётся из
nestor_app.panels.PANELS (data/panels_archive.json), заголовки — явные названия
локусов; состав профиля по числу значений не определяется.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from nestor_app import panels  # noqa: E402
from xlsx_fixture import write_workbook  # noqa: E402

OUT = HERE / "fixtures" / "formats"

# Пользовательский набор на 18 значений (DYS385 — две колонки a/b): не панель NeSToR.
CUSTOM18 = ["DYS19", "DYS389I", "DYS389II", "DYS390", "DYS391", "DYS392", "DYS393", "DYS385a", "DYS385b",
            "DYS437", "DYS438", "DYS439", "DYS448", "DYS456", "DYS458", "DYS635", "Y-GATA-H4", "DYS576"]
# Пользовательский набор на 50 локусов: 30 локусов FTDNA Y37 + DYS635 + 19 локусов из Y67.
_Y37 = list(panels.PANELS["FTDNA_Y37"].marker_names)
_Y67_ONLY = [m for m in panels.PANELS["FTDNA_Y67"].marker_names if m not in _Y37]
CUSTOM50 = _Y37 + ["DYS635"] + _Y67_ONLY[:19]

# файл → (панель или None, формат)
FILES = {
    "FTDNA-Y12.csv": ("FTDNA_Y12", "csv;"),
    "FTDNA-Y25.csv": ("FTDNA_Y25", "csv,"),
    "FTDNA-Y37.tsv": ("FTDNA_Y37", "tsv"),
    "FTDNA-Y67.xlsx": ("FTDNA_Y67", "xlsx"),
    "FTDNA-Y111.csv": ("FTDNA_Y111", "csv;"),
    "Genopoisk-Y37.csv": ("GENOPOISK_Y37", "csv;"),
    "Genopoisk-Y50.xlsx": ("GENOPOISK_Y50", "xlsx"),
    "Custom-18.csv": (None, "csv;"),
    "Custom-50.csv": (None, "csv,"),
}


def value_for(locus: str, copies: int = 1) -> tuple[float, ...]:
    if locus == "DYS389I":
        return (13.0,)
    if locus == "DYS389II":
        return (29.0,)
    base = 10 + sum(map(ord, locus)) % 12
    return tuple(float(base + i // 2) for i in range(copies))


def panel_profile(code: str) -> dict:
    return {m: value_for(m, c) for m, c in panels.PANELS[code].markers}


def cell(v: tuple[float, ...]) -> str:
    return "-".join(str(int(x)) if x.is_integer() else str(x) for x in v)


def header_and_values(code: str | None, name: str) -> tuple[list[str], list[str]]:
    if code:
        prof = panel_profile(code)
        return list(prof), [cell(v) for v in prof.values()]
    loci = CUSTOM18 if name.startswith("Custom-18") else CUSTOM50
    vals = []
    for h in loci:
        if h in ("DYS385a", "DYS385b"):
            vals.append(cell((value_for("DYS385", 2)[0 if h.endswith("a") else 1],)))
        else:
            vals.append(cell(value_for(h)))
    return loci, vals


def expected_profile(name: str) -> dict:
    code, _ = FILES[name]
    if code:
        return panel_profile(code)
    out = {}
    for h in (CUSTOM18 if name.startswith("Custom-18") else CUSTOM50):
        if h in ("DYS385a", "DYS385b"):
            out["DYS385"] = value_for("DYS385", 2)
        else:
            out[panels.canonical_name(h)[0]] = value_for(h)
    return out


def rows_for(name: str) -> list[list[str]]:
    header, values = header_and_values(FILES[name][0], name)
    return [["Kit"] + header, ["SYN-" + name.split(".")[0]] + values]


def file_bytes(name: str) -> bytes:
    fmt = FILES[name][1]
    rows = rows_for(name)
    if fmt == "xlsx":
        raise ValueError("xlsx пишется write_all")
    sep = {"csv;": ";", "csv,": ",", "tsv": "\t"}[fmt]
    return ("﻿" + "\n".join(sep.join(r) for r in rows) + "\n").encode("utf-8")


# Особые случаи: пропуски, дроби, копии в отдельных колонках, DYS389 (опубликованный B,
# нет II, нераспознанное), разное число копий, «0» и «-» как нет значения.
EDGE_HEADER = ["Kit", "DYS393", "DYS390", "DYS19", "DYS391", "DYS385a", "DYS385b", "DYS389I", "DYS389II", "DYS389B",
               "DYS458", "DYS464a", "DYS464b", "DYS464c", "DYS464d", "DYF387S1", "DYS439", "DYS448"]
EDGE_ROWS = [
    ["E-full", "13", "24", "14", "11", "11", "14", "13", "29", "", "17", "15", "15", "17", "17", "35-37", "12", "19"],
    ["E-missing", "13", "", "14", "0", "11", "14", "13", "", "", "-", "15", "15", "17", "17", "35-37", "12", "19"],
    ["E-decimal", "13", "24", "14", "11", "11", "13.2", "13", "29", "", "17.2", "15", "15", "17", "17", "35-37", "12", "19"],
    ["E-copies", "13", "24", "14", "11", "11", "", "13", "29", "", "17", "15", "15", "17", "", "35", "12", "19"],
    ["E-389B", "13", "24", "14", "11", "11", "14", "13", "", "16", "17", "15", "15", "17", "17", "35-37", "12", "19"],
    ["E-invalid", "13", "24", "14", "11", "11", "14", "del", "29", "", "17", "15", "15", "17", "17", "35-37", "12", "x19"],
]


def edge_bytes() -> bytes:
    return ("\n".join(";".join(r) for r in [EDGE_HEADER] + EDGE_ROWS) + "\n").encode("utf-8")


def headerless_bytes() -> bytes:
    """37 значений FTDNA Y37 без строки заголовков — состав не угадывается."""
    _, values = header_and_values("FTDNA_Y37", "")
    return (";".join(values) + "\n").encode("utf-8")


def write_all(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (_, fmt) in FILES.items():
        p = out / name
        if fmt == "xlsx":
            write_workbook(p, {"Profiles": rows_for(name)})
        else:
            p.write_bytes(file_bytes(name))
        written.append(p)
    (out / "Edge-cases.csv").write_bytes(edge_bytes())
    (out / "Headerless-Y37.csv").write_bytes(headerless_bytes())
    written += [out / "Edge-cases.csv", out / "Headerless-Y37.csv"]
    return written


if __name__ == "__main__":
    for p in write_all():
        print(p.relative_to(HERE.parent))
