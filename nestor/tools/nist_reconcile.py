"""Сверка NIST 1032: кандидат ↔ Table S4 ↔ версия NIST PDR. Только чтение.

  py -3 tools/nist_reconcile.py --candidate Nestor_scientific_YSTR.db \
      --table-s4 TableS4.xlsx [--s4-sheet ЛИСТ] --pdr PDR_file.xlsx [--pdr-sheet ЛИСТ] \
      --id-col "Sample ID" --group-col "Population" [--header-row N] \
      --summary docs/NIST_RECONCILIATION.json --groups var/nist_group_labels.csv

Что делает:
  * сопоставляет записи по идентификатору образца (в кандидате — `NIST1032|<ID>`);
  * по каждому локусу сравнивает значения кандидата с Table S4 и Table S4 с PDR
    как текст, после удаления пробелов; ничего не исправляет;
  * собирает метки групп ТОЛЬКО из первичного файла (PDR, иначе Table S4) —
    как записаны, без объединения и переименования, с файлом, SHA-256 и номером
    строки; результат пишется отдельно (--groups), кандидат не меняется;
  * считает численность групп для сверки с тем, что указано в статье.
Если колонка группы в первичных файлах отсутствует, метки не назначаются.
Обозначения del, * и ** в Table S4 распознаются только для сравнения; сырая запись
(raw_record_from_row) хранит строки ячеек без изменений, смысл кодов — data/value_codes.json.
Численность групп сверяется с подтверждёнными по статье общими числами.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_reference import open_ro, sha256_file  # noqa: E402
from xlsx_read import read_font_colors, read_sheet  # noqa: E402

PREFIX = "NIST1032|"
AUDIT = Path(__file__).resolve().parent.parent / "data" / "source_audit.json"
ALIASES = {"Y GATA H4": "Y-GATA-H4", "GATA H4": "Y-GATA-H4", "YGATAH4": "Y-GATA-H4", "Y-GATA-H4": "Y-GATA-H4"}


def _norm_locus(name: str) -> str:
    n = re.sub(r"\s+a/b$", "", name.strip(), flags=re.I)  # 'DYS385 a/b' -> 'DYS385'
    return ALIASES.get(n, ALIASES.get(n.upper(), n.upper().replace(" ", "")))


CODE_RE = re.compile(r"^(?P<core>.*?)(?P<stars>\*{1,2})?$")
KNOWN_CODES = ("del", "*", "**")


def split_codes(raw: str) -> tuple[str, list[str]]:
    """'23*' -> ('23', ['*']); 'del' -> ('', ['del']); '12' -> ('12', []).

    Только для сравнения: исходная строка сохраняется отдельно (raw_record_from_row).
    Нераспознанный текст возвращается как код '?<текст>'.
    """
    text = raw.strip()
    if not text:
        return "", []
    if text.lower() == "del":
        return "", ["del"]
    m = CODE_RE.match(text)
    core, stars = m.group("core").strip(), m.group("stars")
    codes = [stars] if stars else []
    if core.lower() == "del":
        return "", ["del"] + codes
    if core and not re.fullmatch(r"[\d.,/\- ]+", core):
        return "", [f"?{text}"]
    return _norm_value(core), codes


def raw_record_from_row(rec: dict[str, str], loci_cols: dict[str, str]) -> dict[str, str]:
    """Сырая запись из первичной таблицы: строки ячеек без изменений (del, *, ** сохраняются)."""
    return {h: rec[h] for h in loci_cols if rec.get(h, "") != ""}


def _norm_value(v) -> str:
    if isinstance(v, list):
        return ",".join(_norm_value(x) for x in v)
    if isinstance(v, float):
        v = format(round(v, 6), "g")
    parts = str(v).replace(" ", "").replace("/", ",").replace("-", ",").split(",")
    out = []
    for p in parts:
        try:  # двоичное хранение xlsx: '33.200000000000003' сравнивается как 33.2
            out.append(format(round(float(p), 6), "g"))
        except ValueError:
            out.append(p)
    return ",".join(out)


def load_table(path: Path, sheet: str | None, id_col: str, header_row: int | None):
    rows = read_sheet(path, sheet)
    if header_row is None:
        header_row = next(i for i, r in enumerate(rows) if id_col in [c.strip() for c in r])
    header = [c.strip() for c in rows[header_row]]
    idx = header.index(id_col)
    table = {}
    for n, r in enumerate(rows[header_row + 1:], start=header_row + 2):
        if len(r) <= idx or not r[idx].strip():
            continue
        rec = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header)) if header[i]}
        table[r[idx].strip()] = (n, rec)
    return header, table, header_row


def load_candidate(db: Path) -> dict[str, dict]:
    conn = open_ro(db)
    out = {}
    for rid, markers in conn.execute("SELECT id, markers FROM samples WHERE id LIKE ?", (PREFIX + '%',)):
        out[rid[len(PREFIX):] if rid.startswith(PREFIX) else rid] = json.loads(markers)
    conn.close()
    return out


def compare_values(a: dict[str, str], b: dict[str, str], loci: list[str]):
    diffs = []
    for locus in loci:
        va, vb = a.get(locus, ""), b.get(locus, "")
        if va != vb:
            diffs.append((locus, va, vb))
    return diffs


def reconcile(candidate: Path, s4: Path, pdr: Path | None, id_col: str, group_col: str | None,
              s4_sheet=None, pdr_sheet=None, header_row=None, expected_groups: dict | None = None,
              font_flags: dict[str, str] | None = None):
    cand = load_candidate(candidate)
    s4_header, s4_rows, s4_header_row = load_table(s4, s4_sheet, id_col, header_row)
    loci_cols = {h: _norm_locus(h) for h in s4_header if h and h not in (id_col, group_col)}
    s4_norm, codes_found = {}, collections.Counter()
    for sid, (_, rec) in s4_rows.items():
        s4_norm[sid] = {}
        for h, v in rec.items():
            if h in loci_cols:
                core, codes = split_codes(v)
                s4_norm[sid][loci_cols[h]] = core
                for c in codes:
                    codes_found[(c, loci_cols[h])] += 1
    cand_norm = {sid: {_norm_locus(k): _norm_value(v) for k, v in m.items()} for sid, m in cand.items()}
    loci = sorted(set(loci_cols.values()))
    cand_loci = sorted({k for m in cand_norm.values() for k in m})

    summary: dict = {
        "files": {"candidate": {"name": candidate.name, "sha256": sha256_file(candidate)},
                  "table_s4": {"name": s4.name, "sha256": sha256_file(s4)}},
        "counts": {"candidate": len(cand), "table_s4": len(s4_rows)},
        "ids": {"only_candidate": sorted(set(cand) - set(s4_rows))[:50],
                "only_table_s4": sorted(set(s4_rows) - set(cand))[:50],
                "only_candidate_count": len(set(cand) - set(s4_rows)),
                "only_table_s4_count": len(set(s4_rows) - set(cand))},
        "loci": {"table_s4": loci, "candidate": cand_loci,
                 "only_table_s4": sorted(set(loci) - set(cand_loci)),
                 "only_candidate": sorted(set(cand_loci) - set(loci))},
    }
    diff_by_locus = collections.Counter()
    diff_kinds = collections.Counter()
    for sid in sorted(set(cand) & set(s4_rows)):
        for locus, cv, sv in compare_values(cand_norm[sid], s4_norm[sid], loci):
            diff_by_locus[locus] += 1
            diff_kinds["в S4 есть, в кандидате пусто" if not cv else
                       "в S4 пусто, в кандидате есть" if not sv else "значения различаются"] += 1
    explained = collections.Counter()
    for sid in sorted(set(cand) & set(s4_rows)):
        for h, v in s4_rows[sid][1].items():
            if h in loci_cols and "del" in split_codes(v)[1] and not cand_norm[sid].get(loci_cols[h]):
                explained[loci_cols[h]] += 1
    summary["candidate_vs_s4"] = {"differences_by_locus": dict(sorted(diff_by_locus.items())),
                                  "difference_kinds": dict(diff_kinds.most_common()),
                                  "del_in_s4_absent_in_candidate": dict(sorted(explained.items()))}
    summary["source_codes_in_s4"] = [{"code": c, "locus": l, "count": n}
                                     for (c, l), n in sorted(codes_found.items())]

    group_source, group_rows = "table_s4", s4_rows
    if pdr:
        pdr_header, pdr_rows, _ = load_table(pdr, pdr_sheet, id_col, header_row)
        summary["files"]["pdr"] = {"name": pdr.name, "sha256": sha256_file(pdr)}
        summary["counts"]["pdr"] = len(pdr_rows)
        pdr_loci = {h: _norm_locus(h) for h in pdr_header if h and h not in (id_col, group_col)}
        def full(rows, cols):  # значение + исходные обозначения: первичные файлы сравниваются целиком
            out = {}
            for sid, (_, rec) in rows.items():
                out[sid] = {}
                for h, v in rec.items():
                    if h in cols:
                        core, codes = split_codes(v)
                        out[sid][cols[h]] = core + "|" + "".join(sorted(codes))
            return out

        s4_full, pdr_full = full(s4_rows, loci_cols), full(pdr_rows, pdr_loci)
        d = collections.Counter()
        for sid in sorted(set(pdr_rows) & set(s4_rows)):
            for locus, _, _ in compare_values(s4_full[sid], pdr_full[sid], sorted(set(loci) & set(pdr_loci.values()))):
                d[locus] += 1
        summary["s4_vs_pdr"] = {"only_s4": len(set(s4_rows) - set(pdr_rows)),
                                "only_pdr": len(set(pdr_rows) - set(s4_rows)),
                                "differences_by_locus": dict(sorted(d.items()))}
        if group_col and group_col in pdr_header:
            group_source, group_rows = "pdr", pdr_rows

    flags = []
    if font_flags:
        colors = read_font_colors(s4, s4_sheet)
        id_idx = s4_header.index(id_col)
        sha = sha256_file(s4)
        by_row = {rowno: sid for sid, (rowno, _) in s4_rows.items()}
        for (ri, ci), color in sorted(colors.items()):
            sid = by_row.get(ri + 1)  # rowno в load_table — номер строки Excel (с 1)
            if ci == id_idx and sid and color.upper() in font_flags:
                flags.append({"record_key": PREFIX + sid, "field": font_flags[color.upper()], "value": "true",
                              "origin_file": s4.name, "origin_sha256": sha,
                              "origin_locator": f"row {ri + 1}, column {id_col!r}, font color {color}"})
        summary["font_flags"] = {field: sum(1 for f in flags if f["field"] == field) for field in font_flags.values()}
        summary["font_flags_in_candidate"] = sum(1 for f in flags if f["record_key"][len(PREFIX):] in cand)

    labels = []
    if group_col and any(group_col in rec for _, rec in group_rows.values()):
        src_file = pdr if group_source == "pdr" else s4
        sha = sha256_file(src_file)
        for sid, (rowno, rec) in sorted(group_rows.items()):
            if sid in cand:
                labels.append({"record_key": PREFIX + sid, "field": "population_group",
                               "value": rec.get(group_col, ""), "origin_file": src_file.name,
                               "origin_sha256": sha, "origin_locator": f"row {rowno}, column {group_col!r}"})
        counts = dict(collections.Counter(x["value"] for x in labels).most_common())
        primary_counts = dict(collections.Counter(rec.get(group_col, "") for _, rec in group_rows.values()).most_common())
        summary["groups"] = {"origin": group_source, "column": group_col, "counts": counts,
                             "primary_table_counts": primary_counts,
                             "unlabeled_candidate_records": len(set(cand) - {x["record_key"][len(PREFIX):] for x in labels})}
        if expected_groups:
            summary["groups"]["expected_from_article"] = expected_groups
            summary["groups"]["primary_table_matches_article"] = primary_counts == expected_groups
            summary["groups"]["candidate_labels_match_article"] = counts == expected_groups
    else:
        summary["groups"] = {"origin": None, "note": "колонка группы не найдена в первичных файлах — метки не назначены"}
    return summary, labels + flags


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--table-s4", type=Path, required=True)
    ap.add_argument("--s4-sheet")
    ap.add_argument("--pdr", type=Path)
    ap.add_argument("--pdr-sheet")
    ap.add_argument("--id-col", required=True)
    ap.add_argument("--group-col")
    ap.add_argument("--header-row", type=int, help="номер строки заголовка (0 — первая); по умолчанию ищется по --id-col")
    ap.add_argument("--font-flag", action="append", default=[],
                    help="ЦВЕТ=ПОЛЕ: отметить строки, где ID набран этим цветом шрифта (напр. FF0070C0=father_son_substitution)")
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--groups", type=Path, help="CSV меток групп (отдельно от сырых данных)")
    a = ap.parse_args(argv)
    expected = None
    if AUDIT.exists():
        nist = next((x for x in json.loads(AUDIT.read_text(encoding="utf-8"))["sources"] if "NIST" in x["source"]), {})
        expected = nist.get("provenance", {}).get("group_totals", {}).get("counts")
    summary, labels = reconcile(a.candidate, a.table_s4, a.pdr, a.id_col, a.group_col,
                                a.s4_sheet, a.pdr_sheet, a.header_row, expected,
                                dict(x.upper().split("=", 1)[0:1] + x.split("=", 1)[1:] for x in a.font_flag) or None)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if a.summary:
        a.summary.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if a.groups and labels:
        a.groups.parent.mkdir(parents=True, exist_ok=True)
        with open(a.groups, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(labels[0]))
            w.writeheader()
            w.writerows(labels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
