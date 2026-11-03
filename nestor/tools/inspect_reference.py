"""Инспекция и сверка снимков научного Y-STR-справочника (только чтение).

Использование:
  py -3 tools/inspect_reference.py SNAPSHOT.db                 # паспорт снимка (JSON)
  py -3 tools/inspect_reference.py A.db --compare B.db         # сверка двух снимков

Ожидаемая схема (как в Nestor_scientific_YSTR.db / reference/scientific.sqlite):
  samples(id, name, haplogroup, country, source, markers JSON)
  source_metadata(source, citation, doi, url, license, raw_file, row_count, notes)
Ничего не пишет в базы.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def table_names(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def passport(path: Path) -> dict:
    conn = open_ro(path)
    try:
        return _passport(conn, path)
    finally:
        conn.close()


def _passport(conn, path: Path) -> dict:
    tables = table_names(conn)
    out: dict = {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "tables": {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables},
    }
    if "samples" not in tables:
        out["error"] = "нет таблицы samples — схема отличается, сверка вручную"
        return out
    meta = {}
    if "source_metadata" in tables:
        meta = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM source_metadata")}
    keys = collections.Counter()
    nonnumeric = 0
    profiles = collections.Counter()
    per_source = collections.Counter()
    for src, markers in conn.execute("SELECT source, markers FROM samples"):
        per_source[src] += 1
        profiles[markers] += 1
        for k, v in json.loads(markers).items():
            keys[k] += 1
            for x in (v if isinstance(v, list) else [v]):
                if not isinstance(x, (int, float)):
                    nonnumeric += 1
    sources = []
    for src in sorted(set(per_source) | set(meta)):
        m = meta.get(src, {})
        sources.append({
            "source": src,
            "records": per_source.get(src, 0),
            "metadata_row_count": m.get("row_count"),
            "row_count_matches": m.get("row_count") == per_source.get(src, 0),
            "license": m.get("license"),
            "doi": m.get("doi"),
        })
    out.update({
        "records": sum(per_source.values()),
        "sources_count": len(per_source),
        "distinct_marker_profiles": len(profiles),
        "marker_keys": dict(sorted(keys.items())),
        "nonnumeric_allele_values": nonnumeric,
        "sources": sources,
    })
    return out


def compare(a: Path, b: Path) -> dict:
    ca, cb = open_ro(a), open_ro(b)

    def load(conn):
        return {(r["source"], r["id"]): r["markers"] for r in conn.execute("SELECT source, id, markers FROM samples")}

    try:
        da, db = load(ca), load(cb)
    finally:
        ca.close()
        cb.close()
    only_a = set(da) - set(db)
    only_b = set(db) - set(da)
    common = set(da) & set(db)
    changed = [k for k in common if json.loads(da[k]) != json.loads(db[k])]

    def by_source(keys):
        return dict(sorted(collections.Counter(s for s, _ in keys).items()))

    return {
        "a": {"file": a.name, "sha256": sha256_file(a), "records": len(da)},
        "b": {"file": b.name, "sha256": sha256_file(b), "records": len(db)},
        "common_records": len(common),
        "common_with_different_markers": len(changed),
        "changed_examples": [list(k) for k in sorted(changed)[:20]],
        "only_in_a_by_source": by_source(only_a),
        "only_in_b_by_source": by_source(only_b),
    }


def main(argv=None) -> int:
    from nestor_app.cli import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("--compare", type=Path)
    args = ap.parse_args(argv)
    result = compare(args.snapshot, args.compare) if args.compare else passport(args.snapshot)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
