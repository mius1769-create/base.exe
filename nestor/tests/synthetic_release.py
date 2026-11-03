"""Синтетические входы для проверки сборки каталога из «исходного архива» (тесты и CI).

  python tests/synthetic_release.py OUT_DIR

Создаёт в OUT_DIR: Synthetic_expert.tar.gz (внутри genopoisk-expert/reference/scientific.sqlite),
Synthetic_expert.zip (с этим .tar.gz внутри), Synthetic_candidate.db и expected.json с их
SHA-256 и ожидаемыми количествами. Не реальные данные.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from nestor_app.catalog_release import sha256_file  # noqa: E402
from test_inspect_reference import make_db  # noqa: E402
from test_test_catalog import HAP, make_archive  # noqa: E402

COUNTS = {"records": 7, "individual_records": 6, "aggregated_records": 1, "aggregated_observations": 5,
          "sources": 5, "skipped_duplicate_copies": 3}


def write(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sqlite = out / "_scientific.sqlite"
    purps = [("A|Pop", HAP, {}), ("A|Pop|record2", {**HAP, "DYS19": [16]}, {"source_identifier_collision_requires_review": True}),
             ("B|Pop", {**HAP, "DYS390": [23]}, {})]
    for p in (sqlite, out / "Synthetic_candidate.db"):
        if p.exists():
            p.unlink()
    make_archive(sqlite, purps)
    make_db(out / "Synthetic_candidate.db",
            [("A|Pop", "Scientific_Purps2014_PPY23", HAP),
             ("A|Pop|record2", "Scientific_Purps2014_PPY23", {**HAP, "DYS19": [16]}),
             ("B|Pop", "Scientific_Purps2014_PPY23", {**HAP, "DYS390": [23]}),
             ("RUS|1", "Scientific_Roewer2008_WesternRussia", HAP),
             ("RM|1", "Scientific_Ballantyne2014_RM_YSTR", {**HAP, "DYS458": ["19,20"]})],
            [("Scientific_Purps2014_PPY23", "CC BY 3.0", 3), ("Scientific_Roewer2008_WesternRussia", "x", 1),
             ("Scientific_Ballantyne2014_RM_YSTR", "CC BY 3.0", 1)])
    tgz = out / "Synthetic_expert.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(HERE / "fixtures" / "archive_examples" / "README.txt", arcname="genopoisk-expert/README.txt")
        tar.add(sqlite, arcname="genopoisk-expert/reference/scientific.sqlite")
    with zipfile.ZipFile(out / "Synthetic_expert.zip", "w", zipfile.ZIP_STORED) as z:
        z.write(tgz, "Synthetic_expert.tar.gz")
    expected = {"release_sha256": sha256_file(tgz), "candidate_sha256": sha256_file(out / "Synthetic_candidate.db"),
                "sqlite_sha256": sha256_file(sqlite), "catalog_content_sha256": "", **COUNTS}
    sqlite.unlink()
    (out / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    return expected


if __name__ == "__main__":
    print(json.dumps(write(Path(sys.argv[1])), indent=2))
