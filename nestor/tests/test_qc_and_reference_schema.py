import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import qc_reference  # noqa: E402
from inspect_reference import sha256_file  # noqa: E402
from test_inspect_reference import make_db  # noqa: E402

from nestor_app.reference_schema import create_reference  # noqa: E402

FULL = {f"DYS{n}": [14] for n in range(400, 412)}  # 12 синтетических локусов


def prof(**kw):
    p = dict(FULL)
    p.update(kw)
    return p


class TestQC(unittest.TestCase):
    """Синтетический снимок: каждая проверка срабатывает, сырые данные не меняются."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "snap.db"
        rows = [(f"a{i}", "S1", prof(**{"DYS389I": [13], "DYS389II": [29], "Y GATA H4": [12]})) for i in range(25)]
        rows += [
            ("z", "S1", prof(DYS400=[0])),                       # Q01
            ("s", "S1", prof(DYS401=["19,20"])),                 # Q02
            ("m", "S1", prof(DYS402=[14, 15])),                  # Q03
            ("o", "S1", prof(DYS403=[40])),                      # Q04
            ("d", "S1", prof(DYS389I=[14], DYS389II=[17])),      # Q05
            ("p", "S1", {"DYS400": [14]}),                       # Q06
        ]
        rows += [(f"b{i}", "S2", prof(**{"GATA H4": [22], "DYS389I": [13], "DYS389B": [16], "DYS389II": [29]}))
                 for i in range(25)]                              # Q07, Q08, Q09
        make_db(self.db, rows, [("S1", "CC BY", len(rows) - 25), ("S2", "x", 999)])  # Q10 для S2

    def test_all_checks_fire_and_raw_unchanged(self):
        before = sha256_file(self.db)
        summary, findings = qc_reference.run_qc(self.db)
        self.assertEqual(sha256_file(self.db), before)
        s1 = summary["by_source"]["S1"]["findings"]
        for code in ("Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07"):
            self.assertIn(code, s1, code)
        s2_codes = {x["check"] for x in summary["by_source"]["S2"]["source_level"]}
        self.assertTrue({"Q07", "Q08", "Q09", "Q10"} <= s2_codes, s2_codes)
        self.assertNotIn("Q10", {x["check"] for x in summary["by_source"]["S1"]["source_level"]})
        z = next(f for f in findings if f["check"] == "Q01")
        self.assertEqual((z["record"], z["raw_value"]), ("z", 0))  # сырое значение как есть

    def test_details_written_only_where_asked(self):
        out = Path(self.tmp.name) / "var" / "d.csv"
        qc_reference.main([str(self.db), "--summary", str(Path(self.tmp.name) / "s.json"), "--details", str(out)])
        self.assertTrue(out.exists())
        self.assertIn("Q01", out.read_text(encoding="utf-8-sig"))


class TestReferenceSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = create_reference(Path(self.tmp.name) / "ref.db")
        self.addCleanup(self.conn.close)

    def test_created_empty(self):
        for t in ("sources", "raw_records", "derived_values", "qc_findings", "transform_rules"):
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)

    def _seed(self):
        self.conn.execute("INSERT INTO sources VALUES ('SYN','c','d','Table S1','f.xlsx','0'*64,'t','a','ждём подтверждения')")
        self.conn.execute("INSERT INTO raw_records VALUES ('SYN','r1','Pop A',?)", (json.dumps({"DYS19": [0]}),))
        self.conn.commit()

    def test_raw_records_are_immutable(self):
        self._seed()
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE raw_records SET raw_markers_json='{}'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM raw_records")
        self.assertEqual(self.conn.execute("SELECT raw_markers_json FROM raw_records").fetchone()[0], '{"DYS19": [0]}')

    def test_derived_values_require_rule(self):
        self._seed()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO derived_values VALUES ('SYN','r1','DYS19',NULL,'NO-RULE')")
        self.conn.execute("INSERT INTO transform_rules VALUES ('T02','0 → нет значения','QC Q01','proposed')")
        self.conn.execute("INSERT INTO derived_values VALUES ('SYN','r1','DYS19',NULL,'T02')")
        raw = self.conn.execute("SELECT raw_markers_json FROM raw_records").fetchone()[0]
        self.assertEqual(json.loads(raw), {"DYS19": [0]})

    def test_decision_values_restricted(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO sources VALUES ('X','c','d','t','f','h','t','a','условно')")


if __name__ == "__main__":
    unittest.main()
