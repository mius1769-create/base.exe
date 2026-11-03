"""Синтетический .xlsx с несколькими листами (inline-строки и числа) для тестов импорта."""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(rows) -> str:
    out = []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{_col(ci)}{ri}"
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif isinstance(v, tuple) and v[0] == "num":      # ("num", "33.200000000000003") — как хранит Excel
                cells.append(f'<c r="{ref}"><v>{v[1]}</v></c>')
            elif v not in ("", None):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
        out.append(f'<row r="{ri}">{"".join(cells)}</row>')
    return f'<worksheet xmlns="{M}"><sheetData>{"".join(out)}</sheetData></worksheet>'


def write_workbook(path: Path, sheets: dict) -> bytes:
    names = list(sheets)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{M}" xmlns:r="{R}"><sheets>' + "".join(
            f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
            f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1)) + "</Relationships>")
        for i, n in enumerate(names, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheets[n]))
    return path.read_bytes()
