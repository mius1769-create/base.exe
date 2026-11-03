import sqlite3
import tempfile
import unittest
from pathlib import Path

from synthetic import BASE_Y37, SECRET, new_conn, new_user  # noqa: F401  (путь к nestor_app)

from nestor_app import db, search
from nestor_app import markers as mk
from nestor_app import profiles as pr
from nestor_app.gd import genetic_distance
from nestor_app.markers import Invalid

CATS = ("user_excluded", "missing_or_invalid", "copy_count_differences", "allele_differences")


def assert_partition(tc, r):
    """Категории взаимоисключающие и в сумме объясняют panel_overlap."""
    names = [x if isinstance(x, str) else x[0] for c in CATS for x in getattr(r, c)]
    compared = [k for k, (kind, _) in r.per_locus.items() if kind == "compared"]
    tc.assertEqual(len(compared), r.compared)
    tc.assertEqual(len(names) + r.compared, r.panel_overlap)
    tc.assertEqual(len(set(names) | set(compared)), r.panel_overlap)  # ни один локус не в двух категориях


class TestCategories(unittest.TestCase):
    def test_missing_in_one_profile(self):
        r = genetic_distance({"DYS19": (14.0,), "DYS390": None}, {"DYS19": (15.0,), "DYS390": (24.0,)})
        self.assertEqual((r.gd, r.compared, r.panel_overlap), (1, 1, 2))
        self.assertEqual(r.missing_or_invalid, (("DYS390", "нет значения у одного"),))
        assert_partition(self, r)

    def test_missing_in_both(self):
        r = genetic_distance({"DYS19": (14.0,), "DYS390": None}, {"DYS19": (14.0,), "DYS390": None})
        self.assertEqual((r.compared, r.panel_overlap), (1, 2))
        self.assertEqual(r.missing_or_invalid, (("DYS390", "нет значения у обоих"),))
        assert_partition(self, r)

    def test_unrecognized_value(self):
        a = mk.parse_manual_entries("DYS19=14\nDYS390=24?\nDYS391=n/a")
        self.assertIsInstance(a["DYS390"], Invalid)
        self.assertEqual(str(a["DYS390"]), "24?")          # исходная строка сохранена
        self.assertIsNone(a["DYS391"])                      # n/a — нет значения
        r = genetic_distance(a, {"DYS19": (14.0,), "DYS390": (24.0,), "DYS391": (10.0,)})
        self.assertEqual((r.gd, r.compared, r.panel_overlap), (0, 1, 3))
        self.assertEqual(dict(r.missing_or_invalid), {"DYS390": "не распознано", "DYS391": "нет значения у одного"})
        assert_partition(self, r)

    def test_user_excluded_takes_precedence(self):
        a = {"DYS19": (14.0,), "DYS390": None, "DYS464": (15.0, 15.0, 17.0, 17.0)}
        b = {"DYS19": (16.0,), "DYS390": (24.0,), "DYS464": (15.0, 17.0, 17.0)}
        r = genetic_distance(a, b, excluded=["dys19", "DYS390", "DYS464"])
        self.assertEqual(r.user_excluded, ("DYS19", "DYS390", "DYS464"))   # раньше пропуска и копий
        self.assertEqual((r.gd, r.compared, r.panel_overlap), (0, 0, 3))
        self.assertEqual((r.missing_or_invalid, r.copy_count_differences), ((), ()))
        assert_partition(self, r)

    def test_excluding_dys389ii_means_derived_b(self):
        a = {"DYS389I": (13.0,), "DYS389II": (29.0,)}
        b = {"DYS389I": (13.0,), "DYS389II": (31.0,)}
        r = genetic_distance(a, b, excluded=["DYS389II"])
        self.assertEqual((r.gd, r.user_excluded), (0, ("DYS389B",)))

    def test_copy_count_with_other_categories(self):
        a = {"DYS385": (11.0, 14.0), "DYS19": (14.0,), "DYS458": (17.2,), "DYS390": None, "DYS391": (10.0,)}
        b = {"DYS385": (11.0, 14.0, 15.0), "DYS19": (14.0,), "DYS458": (18.2,), "DYS390": (24.0,), "DYS391": (11.0,)}
        r = genetic_distance(a, b, excluded=["DYS391"])
        self.assertEqual(r.copy_count_differences, (("DYS385", 2, 3),))
        self.assertEqual([x[0] for x in r.allele_differences], ["DYS458"])
        self.assertEqual([x[0] for x in r.missing_or_invalid], ["DYS390"])
        self.assertEqual(r.user_excluded, ("DYS391",))
        self.assertEqual((r.gd, r.compared, r.panel_overlap, r.preliminary), (0, 1, 5, True))
        assert_partition(self, r)

    def test_dys389_with_missing_component(self):
        a = {"DYS389I": (13.0,), "DYS389II": None}
        b = {"DYS389I": (13.0,), "DYS389II": (29.0,)}
        r = genetic_distance(a, b)
        self.assertEqual(r.panel_overlap, 2)                       # DYS389I и DYS389B
        self.assertEqual(r.missing_or_invalid, (("DYS389B", "нет значения у одного"),))
        self.assertEqual(a, {"DYS389I": (13.0,), "DYS389II": None})  # исходный профиль не тронут
        bad = genetic_distance({"DYS389I": (13.0,), "DYS389II": Invalid("x")}, b)
        self.assertEqual(bad.missing_or_invalid, (("DYS389B", "не распознано"),))

    def test_full_identical_profile_partition(self):
        assert_partition(self, genetic_distance(BASE_Y37, dict(BASE_Y37)))


class TestStorageAndSearch(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)

    def test_statuses_persist(self):
        uid = new_user(self.conn, 1)
        entries = mk.parse_manual_entries("DYS19=14\nDYS390=\nDYS391=1x\nDYS385a=11\nDYS385b=")
        self.assertIsInstance(entries["DYS385"], Invalid)    # часть копий отсутствует
        pid = pr.create_profile(self.conn, uid, entries, consent_basis="own_test", consent_confirmed=True)
        stored = pr.get_owned(self.conn, uid, pid).markers
        self.assertEqual(stored["DYS19"], (14.0,))
        self.assertIsNone(stored["DYS390"])
        self.assertEqual((type(stored["DYS391"]), str(stored["DYS391"])), (Invalid, "1x"))
        exp = pr.export_owner_profile(self.conn, uid, pid)
        self.assertEqual(exp["markers"], {"DYS19": "14"})
        self.assertEqual(exp["markers_without_value"], ["DYS390"])
        self.assertEqual(exp["markers_unrecognized"]["DYS391"], "1x")

    def test_profile_needs_at_least_one_value(self):
        uid = new_user(self.conn, 1)
        with self.assertRaises(pr.ProfileError):
            pr.create_profile(self.conn, uid, {"DYS19": None}, consent_basis="own_test", consent_confirmed=True)
        with self.assertRaises(mk.MarkerError):
            mk.parse_manual_entries("DYS19=\nDYS390=abc")

    def test_threshold_counts_only_compared(self):
        target = dict(BASE_Y37)
        uid = new_user(self.conn, 1)
        pid = pr.create_profile(self.conn, uid, target, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, uid, pid, True)
        q = dict(BASE_Y37)
        for k in ("DYS393", "DYS390", "DYS19"):
            q[k] = None
        q["DYS391"] = Invalid("10?")
        owner = new_user(self.conn, 2)
        own = pr.create_profile(self.conn, owner, q, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, owner, own, True)
        [m] = search.owner_search(self.conn, owner, own, min_common=24, excluded_loci=["DYS438", "DYS442"])
        self.assertEqual((m.panel_overlap, m.missing_or_invalid, m.user_excluded, m.compared), (30, 4, 2, 24))
        self.assertEqual(search.owner_search(self.conn, owner, own, min_common=25, excluded_loci=["DYS438", "DYS442"]), [])

    def test_guest_key_and_excluded(self):
        q = dict(BASE_Y37)
        k0 = search.guest_query_key(SECRET, q, 4, 12)
        self.assertEqual(k0, search.guest_query_key(SECRET, q, 4, 12, excluded_loci=[]))       # как guest-v1
        self.assertNotEqual(k0, search.guest_query_key(SECRET, q, 4, 12, excluded_loci=["DYS19"]))
        self.assertEqual(search.guest_query_key(SECRET, q, 4, 12, ["dys19", "DYS390"]),
                         search.guest_query_key(SECRET, q, 4, 12, ["DYS390", "DYS19"]))


class TestMigration(unittest.TestCase):
    def test_v1_database_gets_status_column(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            c = sqlite3.connect(path)
            c.executescript("""CREATE TABLE profile_markers(profile_id INTEGER, marker TEXT, value TEXT,
                               PRIMARY KEY(profile_id, marker));
                               INSERT INTO profile_markers VALUES (1, 'DYS19', '14');""")
            c.commit()
            c.close()
            conn = db.connect(path)
            row = conn.execute("SELECT value, status FROM profile_markers").fetchone()
            self.assertEqual(tuple(row), ("14", "ok"))
            self.assertEqual(conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], str(db.SCHEMA_VERSION))
            conn.close()


if __name__ == "__main__":
    unittest.main()


class TestMigrationV5(unittest.TestCase):
    def test_committed_files_without_consent_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "v4.db"
            c = sqlite3.connect(path)
            c.executescript("""CREATE TABLE import_files(id INTEGER PRIMARY KEY, owner_user_id INTEGER, filename TEXT,
                               sha256 TEXT, size_bytes INTEGER, content BLOB, panel_choice TEXT,
                               status TEXT NOT NULL DEFAULT 'staged', created_at TEXT);
                               INSERT INTO import_files(owner_user_id, filename, sha256, size_bytes, content, panel_choice, status)
                               VALUES (1,'old.csv','x',3,X'414243','AUTO','committed'),
                                      (1,'pending.csv','y',3,X'444546','AUTO','staged');""")
            c.commit()
            c.close()
            conn = db.connect(path)
            rows = [tuple(r) for r in conn.execute("SELECT filename, status, keep_original FROM import_files")]
            self.assertEqual(rows, [("pending.csv", "staged", 0)])
            conn.close()
