import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import inspect_reference as ir  # noqa: E402

SCHEMA = """
CREATE TABLE samples(id TEXT NOT NULL, name TEXT DEFAULT '', haplogroup TEXT DEFAULT '', country TEXT DEFAULT '',
                     source TEXT NOT NULL, markers TEXT NOT NULL, PRIMARY KEY(id, source));
CREATE TABLE source_metadata(source TEXT PRIMARY KEY, citation TEXT NOT NULL, doi TEXT NOT NULL, url TEXT NOT NULL,
                             license TEXT NOT NULL, raw_file TEXT NOT NULL, row_count INTEGER NOT NULL, notes TEXT NOT NULL);
"""


def make_db(path: Path, rows, meta):
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO samples(id, source, markers) VALUES (?,?,?)",
                  [(i, s, json.dumps(m)) for i, s, m in rows])
    c.executemany("INSERT INTO source_metadata VALUES (?,?,?,?,?,?,?,?)",
                  [(s, "c", "d", "u", lic, "f", n, "") for s, lic, n in meta])
    c.commit()
    c.close()


class TestInspectReference(unittest.TestCase):
    """Синтетические снимки той же схемы, что у Nestor_scientific_YSTR.db."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.a, self.b = d / "a.db", d / "b.db"
        make_db(self.a, [("1", "S1", {"DYS19": [14]}), ("2", "S1", {"DYS19": [15]}), ("3", "S2", {"DYS19": ["14,15"]})],
                [("S1", "CC BY 3.0", 2), ("S2", "All rights reserved", 5)])
        make_db(self.b, [("1", "S1", {"DYS19": [14]}), ("2", "S1", {"DYS19": [16]}), ("9", "S3", {"DYS19": [13]})],
                [("S1", "CC BY 3.0", 2), ("S3", "CC BY 4.0", 1)])

    def test_passport(self):
        p = ir.passport(self.a)
        self.assertEqual(p["records"], 3)
        self.assertEqual(p["sources_count"], 2)
        self.assertEqual(p["integrity_check"], "ok")
        self.assertEqual(p["sha256"], ir.sha256_file(self.a))
        self.assertEqual(p["nonnumeric_allele_values"], 1)
        mismatch = {s["source"]: s["row_count_matches"] for s in p["sources"]}
        self.assertEqual(mismatch, {"S1": True, "S2": False})

    def test_compare(self):
        r = ir.compare(self.a, self.b)
        self.assertEqual(r["common_records"], 2)
        self.assertEqual(r["common_with_different_markers"], 1)
        self.assertEqual(r["only_in_a_by_source"], {"S2": 1})
        self.assertEqual(r["only_in_b_by_source"], {"S3": 1})

    def test_read_only(self):
        before = ir.sha256_file(self.a)
        ir.passport(self.a)
        ir.compare(self.a, self.b)
        self.assertEqual(ir.sha256_file(self.a), before)


if __name__ == "__main__":
    unittest.main()
