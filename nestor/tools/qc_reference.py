"""QC-отчёт по снимку научного справочника. Только чтение: сырые значения не меняются.

  py -3 tools/qc_reference.py SNAPSHOT.db --summary docs/QC_SUMMARY.json --details var/qc_details.csv

summary — агрегаты по источникам и проверкам (можно хранить в git);
details — построчные находки с исходными значениями (содержат данные источников,
поэтому пишутся только локально, в git не кладутся).

Проверки (код — смысл; ни одна ничего не исправляет):
  Q01 zero_allele          аллель 0 (в источнике может означать null/не определён)
  Q02 nonnumeric_value     строковое значение аллеля (напр. "19,20")
  Q03 multi_value_single   несколько значений у однокопийного локуса
  Q04 outlier              значение отстоит от медианы локуса (по всем источникам) более чем на 8
  Q05 dys389_inconsistent  DYS389II − DYS389I < 9: значение похоже на DYS389II−I, а не на сумму
  Q06 sparse_profile       в профиле меньше 12 локусов
  Q07 locus_alias          разные написания одного локуса (Y GATA H4 / GATA H4)
  Q08 scale_shift          медиана локуса в источнике отличается от медианы остальных источников на ≥ 5
  Q09 derived_locus        значение совпадает с суммой других локусов (DYS389II = DYS389I + DYS389B)
  Q10 metadata_count       число записей источника не совпадает с row_count метаданных
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_reference import open_ro, sha256_file  # noqa: E402

MULTI_COPY = {"DYS385", "DYS459", "YCAII", "CDY", "DYS464", "DYF387S1", "DYF399S1", "DYF403S1A", "DYF404S1"}
ALIASES = {"Y GATA H4": "Y-GATA-H4", "GATA H4": "Y-GATA-H4", "YGATAH4": "Y-GATA-H4"}
CHECKS = {
    "Q01": "zero_allele", "Q02": "nonnumeric_value", "Q03": "multi_value_single", "Q04": "outlier",
    "Q05": "dys389_inconsistent", "Q06": "sparse_profile", "Q07": "locus_alias", "Q08": "scale_shift",
    "Q09": "derived_locus", "Q10": "metadata_count",
}


def _numbers(values) -> list[float]:
    out = []
    for x in values:
        if isinstance(x, (int, float)):
            out.append(float(x))
        else:
            for part in str(x).split(","):
                try:
                    out.append(float(part))
                except ValueError:
                    pass
    return out


def run_qc(path: Path) -> tuple[dict, list[dict]]:
    conn = open_ro(path)
    rows = conn.execute("SELECT source, id, markers FROM samples").fetchall()
    meta = {r["source"]: r["row_count"] for r in conn.execute("SELECT source, row_count FROM source_metadata")}
    conn.close()

    findings: list[dict] = []

    def add(code, source, record, locus, raw, note=""):
        findings.append({"check": code, "name": CHECKS[code], "source": source, "record": record,
                         "locus": locus, "raw_value": raw, "note": note})

    parsed = []
    by_locus_source = collections.defaultdict(lambda: collections.defaultdict(list))
    alias_seen = collections.defaultdict(set)
    per_source = collections.Counter()
    for r in rows:
        src, rid = r["source"], r["id"]
        per_source[src] += 1
        markers = json.loads(r["markers"])
        parsed.append((src, rid, markers))
        if len(markers) < 12:
            add("Q06", src, rid, "", len(markers), "локусов в профиле")
        for locus, values in markers.items():
            canon = ALIASES.get(locus, locus)
            if canon != locus:
                alias_seen[(src, canon)].add(locus)
            vals = values if isinstance(values, list) else [values]
            for v in vals:
                if isinstance(v, (int, float)) and v == 0:
                    add("Q01", src, rid, locus, v)
                elif not isinstance(v, (int, float)):
                    add("Q02", src, rid, locus, v)
            if canon not in MULTI_COPY and len(vals) > 1:
                add("Q03", src, rid, locus, vals)
            for n in _numbers(vals):
                if n > 0:
                    by_locus_source[canon][src].append(n)

    medians = {}
    for locus, srcs in by_locus_source.items():
        allv = [v for vs in srcs.values() for v in vs]
        medians[locus] = statistics.median(allv)
        for src, vs in srcs.items():
            others = [v for s, vv in srcs.items() if s != src for v in vv]
            if others and len(vs) >= 20:
                m_src, m_oth = statistics.median(vs), statistics.median(others)
                if abs(m_src - m_oth) >= 5:
                    add("Q08", src, "", locus, m_src, f"медиана в источнике {m_src}, в остальных {m_oth}")

    for (src, canon), names in alias_seen.items():
        add("Q07", src, "", canon, sorted(names), "написание в источнике")

    derived = collections.Counter()
    with_b = collections.Counter()
    for src, rid, markers in parsed:
        for locus, values in markers.items():
            canon = ALIASES.get(locus, locus)
            for n in _numbers(values if isinstance(values, list) else [values]):
                if n > 0 and abs(n - medians[canon]) > 8:
                    add("Q04", src, rid, locus, n, f"медиана локуса {medians[canon]}")
        a, b = markers.get("DYS389I"), markers.get("DYS389II")
        if a and b and all(isinstance(x, (int, float)) for x in a + b) and a[0] > 0 and b[0] > 0:
            if b[0] - a[0] < 9:
                add("Q05", src, rid, "DYS389II", b, f"DYS389I={a}")
        bb = markers.get("DYS389B")
        if a and b and bb:
            with_b[src] += 1
            if all(isinstance(x, (int, float)) for x in a + b + bb) and b[0] == a[0] + bb[0]:
                derived[src] += 1
    for src, n in derived.items():
        if n == with_b[src]:
            add("Q09", src, "", "DYS389II", n, "DYS389II = DYS389I + DYS389B во всех записях с тремя значениями")

    for src, n in per_source.items():
        if meta.get(src) != n:
            add("Q10", src, "", "", n, f"row_count в метаданных: {meta.get(src)}")

    summary = {
        "snapshot": path.name,
        "sha256": sha256_file(path),
        "records": len(rows),
        "checks": CHECKS,
        "by_source": {},
    }
    for src in sorted(per_source):
        c = collections.Counter(f["check"] for f in findings if f["source"] == src)
        recs = collections.defaultdict(set)
        for f in findings:
            if f["source"] == src and f["record"]:
                recs[f["check"]].add(f["record"])
        summary["by_source"][src] = {
            "records": per_source[src],
            "findings": dict(sorted(c.items())),
            "records_affected": {k: len(v) for k, v in sorted(recs.items())},
            "source_level": [
                {k: f[k] for k in ("check", "locus", "raw_value", "note")}
                for f in findings if f["source"] == src and not f["record"]
            ],
        }
    return summary, findings


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--details", type=Path, help="CSV построчных находок (только локально, не в git)")
    args = ap.parse_args(argv)
    summary, findings = run_qc(args.snapshot)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.summary:
        args.summary.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.details:
        args.details.parent.mkdir(parents=True, exist_ok=True)
        with open(args.details, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["check", "name", "source", "record", "locus", "raw_value", "note"])
            w.writeheader()
            for row in findings:
                w.writerow({**row, "raw_value": json.dumps(row["raw_value"], ensure_ascii=False)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
