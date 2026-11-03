"""Импорт CSV / XLSX: чтение таблиц, разбор строк и предварительный просмотр.

Модуль ничего не записывает. Запись выполняют user_import (профили владельца)
и candidates (научные кандидаты в отдельной базе) только после просмотра.

Принципы:
  * исходный файл хранится целиком (SHA-256), у каждой записи — лист, номер
    строки и исходные ячейки дословно (как прочитаны из файла);
  * панель: выбранная (локусы вне неё — ошибка листа) или надёжно распознанная
    по заголовкам; иначе — пользовательский набор;
  * пустые ячейки — позиции без значения, нераспознанные — Invalid;
  * повторы внутри файла и совпадения с уже сохранёнными записями только
    помечаются — записи не объединяются;
  * файлы баз (.db, .sqlite) не принимаются: снимки научных баз и локальные
    базы не импортируются этим путём.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import PurePath

from . import markers as mk
from . import panels as pn
from .xlsx import read_sheet, sheet_names

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
HEADER_SCAN_ROWS = 30
MIN_MARKER_HEADERS = 5
ID_HEADERS = {"SAMPLE", "SAMPLEID", "SAMPLE ID", "KIT", "KITNUMBER", "KIT NUMBER", "KIT ID", "KITID", "ID",
              "NAME", "НОМЕР", "ОБРАЗЕЦ", "КИТ", "PRIMARY ID", "PRIMARYID"}
REFUSED_SUFFIXES = {".db", ".sqlite", ".sqlite3"}

KNOWN_LOCI = ({n for p in pn.PANELS.values() for n in p.marker_names}
              | mk.MULTI_COPY | set(mk.ALIASES.values()) | {"DYS389B"})


class ImportError_(ValueError):
    pass


@dataclass
class Record:
    sheet: str
    row_number: int                    # номер строки в файле (с 1, как в Excel / текстовом редакторе)
    record_id: str
    raw: dict                          # {заголовок: ячейка} — дословно
    positions: dict                    # профиль после панели: {локус: кортеж | None | Invalid}
    observed: int = 0
    missing: list = field(default_factory=list)
    invalid: dict = field(default_factory=dict)     # {локус: исходная строка}
    flags: list = field(default_factory=list)
    error: str = ""

    @property
    def savable(self) -> bool:
        return not self.error

    def fingerprint(self) -> str:
        return mk.canonical_string(self.positions)


@dataclass
class SheetPreview:
    name: str
    header_row: int | None = None
    marker_columns: list = field(default_factory=list)
    id_column: str | None = None
    other_columns: list = field(default_factory=list)
    panel_code: str | None = None
    panel_basis: str = "custom"
    error: str = ""
    empty_rows: int = 0
    records: list = field(default_factory=list)


@dataclass
class Preview:
    filename: str
    sha256: str
    size: int
    panel_choice: str
    sheets: list

    @property
    def records(self) -> list:
        return [r for s in self.sheets for r in s.records]

    def summary(self) -> dict:
        recs = self.records
        return {
            "file": self.filename, "sha256": self.sha256, "size": self.size,
            "sheets": [{"name": s.name, "panel": s.panel_code or "custom", "panel_basis": s.panel_basis,
                        "header_row": s.header_row, "records": len(s.records), "empty_rows": s.empty_rows,
                        "error": s.error} for s in self.sheets],
            "records": len(recs),
            "savable": sum(1 for r in recs if r.savable),
            "with_missing": sum(1 for r in recs if r.missing),
            "with_invalid": sum(1 for r in recs if r.invalid),
            "flagged": sum(1 for r in recs if r.flags),
        }


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_("не удалось определить кодировку CSV (ожидается UTF-8 или Windows-1251)")


def read_tables(filename: str, data: bytes) -> list[tuple[str, list[list[str]]]]:
    """[(имя листа, строки)]; ячейки — строки как в файле."""
    suffix = PurePath(filename).suffix.lower()
    if suffix in REFUSED_SUFFIXES:
        raise ImportError_("файлы баз (.db/.sqlite) не импортируются: снимки и локальные базы этим путём не переносятся")
    if len(data) > MAX_FILE_BYTES:
        raise ImportError_(f"файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ")
    if suffix == ".xlsx" or data[:2] == b"PK":
        try:
            return [(name, read_sheet(data, name)) for name in sheet_names(data)]
        except Exception as e:  # noqa: BLE001 — повреждённый или не-xlsx zip
            raise ImportError_(f"не удалось прочитать XLSX: {e}") from None
    if suffix not in (".csv", ".txt", ".tsv", ""):
        raise ImportError_("поддерживаются CSV и XLSX")
    text = _decode(data)
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max((";", "\t", ","), key=first.count)
    rows = [[c for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]
    return [("CSV", rows)]


def _header_name(cell: str) -> tuple[str, str | None] | None:
    text = str(cell).strip().lstrip("﻿")
    if not text:
        return None
    try:
        name, suffix = mk.canonical_name(text)
    except mk.MarkerError:
        return None
    return (name, suffix) if name in KNOWN_LOCI else None


def _find_header(rows: list[list[str]]) -> int | None:
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if sum(1 for c in row if _header_name(c)) >= MIN_MARKER_HEADERS:
            return i
    return None


def parse_sheet(name: str, rows: list[list[str]], panel_choice: str = "AUTO") -> SheetPreview:
    sp = SheetPreview(name=name)
    hi = _find_header(rows)
    if hi is None:
        sp.error = f"не найдена строка заголовков (нужно не меньше {MIN_MARKER_HEADERS} названий локусов)"
        return sp
    header = [str(c).strip().lstrip("﻿") for c in rows[hi]]
    sp.header_row = hi + 1
    marker_idx, declared = [], set()
    for j, h in enumerate(header):
        hn = _header_name(h)
        if hn:
            marker_idx.append(j)
            declared.add(hn[0])
            sp.marker_columns.append(h)
        elif h:
            if sp.id_column is None and h.upper().replace("_", " ") in ID_HEADERS:
                sp.id_column = h
            else:
                sp.other_columns.append(h)
    if len({header[j] for j in marker_idx}) != len(marker_idx):
        sp.error = "повторяющиеся заголовки локусов"
        return sp
    choice = (panel_choice or "AUTO").upper()
    if choice in ("AUTO",):
        code = pn.recognize_panel(declared)
        sp.panel_code, sp.panel_basis = (code, "recognized") if code else (None, "custom")
    elif choice in ("", pn.CUSTOM):
        sp.panel_code, sp.panel_basis = None, "custom"
    else:
        try:
            panel = pn.get_panel(choice)
        except pn.UnsupportedPanel as e:
            sp.error = str(e)
            return sp
        extra = sorted(declared - set(panel.marker_names))
        if extra:
            sp.error = (f"ошибочная панель: в файле есть локусы вне {panel.title} ({', '.join(extra)}); "
                        f"выберите другую панель или «определить автоматически»")
            return sp
        sp.panel_code, sp.panel_basis = panel.code, "selected"
    id_idx = header.index(sp.id_column) if sp.id_column else None
    for k, row in enumerate(rows[hi + 1:], start=hi + 2):
        cells = [str(c) for c in row] + [""] * (len(header) - len(row))
        marker_cells = {header[j]: cells[j] for j in marker_idx}
        if not any(v.strip() for v in marker_cells.values()):
            if any(c.strip() for c in cells):
                sp.empty_rows += 1
            continue
        if len(sp.records) >= MAX_ROWS:
            sp.error = f"больше {MAX_ROWS} строк — разделите файл"
            break
        raw = {header[j]: cells[j] for j in range(len(header)) if header[j]}
        rec = Record(sheet=name, row_number=k, record_id=(cells[id_idx].strip() if id_idx is not None else ""),
                     raw=raw, positions={})
        try:
            entries = mk.normalize_entries(marker_cells)
            rec.positions, _, _ = pn.apply_panel(entries, sp.panel_code or pn.CUSTOM)
        except (mk.MarkerError, pn.PanelMismatch) as e:
            rec.error = str(e)
        rec.observed = sum(1 for v in rec.positions.values() if mk.is_observed(v))
        rec.missing = sorted(k2 for k2, v in rec.positions.items() if v is None)
        rec.invalid = {k2: str(v) for k2, v in rec.positions.items() if isinstance(v, mk.Invalid)}
        if not rec.error and rec.observed == 0:
            rec.error = "в строке нет ни одного корректного значения"
        sp.records.append(rec)
    return sp


def _mark_duplicates(records: list[Record], existing: list[tuple[str, str, dict]]):
    """existing: [(метка, record_id, позиции)] уже сохранённых записей."""
    by_fp: dict[str, list[Record]] = {}
    by_id: dict[str, list[Record]] = {}
    for r in records:
        if r.error:
            continue
        by_fp.setdefault(r.fingerprint(), []).append(r)
        if r.record_id:
            by_id.setdefault(r.record_id, []).append(r)
    for group in by_fp.values():
        if len(group) > 1:
            for r in group:
                others = [f"{o.sheet}:{o.row_number}" for o in group if o is not r]
                r.flags.append("повтор значений внутри файла: " + ", ".join(others))
    for rid, group in by_id.items():
        if len(group) > 1:
            for r in group:
                others = [f"{o.sheet}:{o.row_number}" for o in group if o is not r]
                r.flags.append(f"повтор ID «{rid}» внутри файла: " + ", ".join(others))
    ex_fp = {}
    ex_id = {}
    for label, rid, positions in existing:
        ex_fp.setdefault(mk.canonical_string(positions), []).append(label)
        if rid:
            ex_id.setdefault(rid, []).append(label)
    for r in records:
        if r.error:
            continue
        if r.fingerprint() in ex_fp:
            r.flags.append("те же значения, что у сохранённой записи: " + ", ".join(ex_fp[r.fingerprint()]))
        if r.record_id and r.record_id in ex_id:
            r.flags.append(f"ID «{r.record_id}» уже есть: " + ", ".join(ex_id[r.record_id]))


def build_preview(filename: str, data: bytes, panel_choice: str = "AUTO", existing=(), sheet: str | None = None) -> Preview:
    tables = read_tables(filename, data)
    if sheet is not None:
        tables = [t for t in tables if t[0] == sheet]
        if not tables:
            raise ImportError_(f"лист {sheet!r} не найден")
    sheets = [parse_sheet(name, rows, panel_choice) for name, rows in tables]
    prev = Preview(filename=PurePath(filename).name, sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                   panel_choice=panel_choice, sheets=sheets)
    if not any(s.records for s in sheets):
        errors = "; ".join(f"{s.name}: {s.error}" for s in sheets if s.error)
        raise ImportError_("в файле не найдено профилей" + (f" ({errors})" if errors else ""))
    _mark_duplicates(prev.records, list(existing))
    return prev


def raw_json(record: Record) -> str:
    return json.dumps(record.raw, ensure_ascii=False)
