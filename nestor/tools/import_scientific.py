"""Импорт научной таблицы (CSV / XLSX) в отдельную базу кандидатов — только для оператора.

Без --commit выполняется только предварительный просмотр (ничего не пишется):
  py -3 tools/import_scientific.py TABLE.xlsx --source-id purps2014_mmc1 --title "…" \
      --publication "Purps J, et al. 2014 …" --doi 10.1016/… --url https://… \
      --license "CC BY 3.0 (статья); условия supplementary не подтверждены" \
      --permission-status "ждём подтверждения" [--panel AUTO] [--sheet ЛИСТ] [--commit]

Кандидаты не попадают в научный справочник и в поиск NeSToR до отдельного решения.
Снимки научных баз (.db/.sqlite) этим путём не принимаются.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nestor_app import candidates, importer  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--db", type=Path, default=ROOT / "var" / "nestor_science_candidates.db")
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--publication", required=True)
    ap.add_argument("--doi")
    ap.add_argument("--url", required=True, help="исходная ссылка на таблицу / набор данных")
    ap.add_argument("--license", required=True, help="условия использования набора, как установлены")
    ap.add_argument("--permission-status", required=True, choices=candidates.PERMISSION_STATUSES)
    ap.add_argument("--notes")
    ap.add_argument("--panel", default="AUTO")
    ap.add_argument("--sheet")
    ap.add_argument("--commit", action="store_true", help="записать после просмотра")
    a = ap.parse_args(argv)
    data = a.file.read_bytes()
    a.db.parent.mkdir(parents=True, exist_ok=True)
    conn = candidates.connect(a.db)
    try:
        prev = candidates.preview(conn, a.file.name, data, a.panel, a.sheet)
        report = prev.summary()
        report["rows"] = [{"sheet": r.sheet, "row": r.row_number, "id": r.record_id, "observed": r.observed,
                           "missing": r.missing, "invalid": r.invalid, "flags": r.flags, "error": r.error}
                          for r in prev.records]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not a.commit:
            print("Просмотр. Для записи повторите с --commit.", file=sys.stderr)
            return 0
        n = candidates.commit(conn, a.file.name, data, panel_choice=a.panel, sheet=a.sheet, source={
            "source_id": a.source_id, "title": a.title, "publication": a.publication, "doi": a.doi,
            "source_url": a.url, "license": a.license, "permission_status": a.permission_status, "notes": a.notes})
        print(f"Записано кандидатов: {n}. В справочник и поиск не включены: {candidates.DECISION}.", file=sys.stderr)
        return 0
    except (importer.ImportError_, candidates.CandidateError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
