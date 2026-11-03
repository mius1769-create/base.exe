"""Минимальное чтение .xlsx на стандартной библиотеке (значения ячеек как текст, без формул).

Источник: путь к файлу или байты (bytes / file-like). Значения ячеек возвращаются
так, как записаны в файле (например '33.200000000000003'), без интерпретации.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
import io
from pathlib import Path

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _open(src):
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    return zipfile.ZipFile(src)


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def sheet_names(path: Path) -> list[str]:
    with _open(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        return [s.get("name") for s in wb.find("m:sheets", NS)]


def read_sheet(path: Path, sheet: str | None = None) -> list[list[str]]:
    """Строки листа как списки строк; пустые ячейки — ''. Значения не интерпретируются."""
    with _open(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sst.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = wb.find("m:sheets", NS)
        chosen = sheets[0] if sheet is None else next((s for s in sheets if s.get("name") == sheet), None)
        if chosen is None:
            raise KeyError(f"лист {sheet!r} не найден; есть: {[s.get('name') for s in sheets]}")
        rid = chosen.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(z.read(target))
    rows: list[list[str]] = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", NS):
            t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
            else:
                v = c.find("m:v", NS)
                val = "" if v is None else (v.text or "")
                if t == "s" and val != "":
                    val = shared[int(val)]
            cells[_col_index(c.get("r"))] = val
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
        else:
            rows.append([])
    return rows


def read_font_colors(path: Path, sheet: str | None = None) -> dict[tuple[int, int], str]:
    """Цвет шрифта ячеек {(строка, колонка): 'FF0070C0' | 'theme1' | ...} (индексы с 0, как в read_sheet)."""
    with _open(path) as z:
        styles = ET.fromstring(z.read("xl/styles.xml"))
        fonts = styles.find("m:fonts", NS)
        xfs = styles.find("m:cellXfs", NS)
        font_color = []
        for f in fonts:
            c = f.find("m:color", NS)
            if c is None:
                font_color.append("")
            elif c.get("rgb"):
                font_color.append(c.get("rgb").upper())
            elif c.get("theme") is not None:
                font_color.append("theme" + c.get("theme"))
            else:
                font_color.append("indexed" + str(c.get("indexed")))
        xf_font = [int(x.get("fontId", 0)) for x in xfs]
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = wb.find("m:sheets", NS)
        chosen = sheets[0] if sheet is None else next(s for s in sheets if s.get("name") == sheet)
        rid = chosen.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rid).lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(z.read(target))
    out = {}
    for ri, row in enumerate(root.iter(f"{{{NS['m']}}}row")):
        for c in row.findall("m:c", NS):
            s = c.get("s")
            if s is not None:
                out[(ri, _col_index(c.get("r")))] = font_color[xf_font[int(s)]]
    return out
