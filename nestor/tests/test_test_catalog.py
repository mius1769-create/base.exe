"""Локальный тестовый научный каталог — на синтетических снимках обеих схем."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from synthetic import BASE_Y37, as_text, new_user  # noqa: F401  (путь к nestor_app)
from test_inspect_reference import make_db

from nestor_app import db
from nestor_app import markers as mk
from nestor_app import profiles as pr
from nestor_app import test_catalog as tc

ROOT = Path(__file__).resolve().parent.parent
HAP = {"DYS393": [13], "DYS390": [24], "DYS19": [14], "DYS391": [11], "DYS385": [11, 14], "DYS389I": [13],
       "DYS389II": [29], "DYS392": [13], "DYS437": [15], "DYS438": [12], "DYS439": [12], "DYS448": [19],
       "DYS456": [16], "DYS458": [17], "DYS635": [23], "Y GATA H4": [11]}


def make_archive(path: Path, purps_rows, extra_since=True):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE sources(source_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);
    CREATE TABLE profiles(id TEXT PRIMARY KEY, source_id TEXT, source_sample_id TEXT, source_file TEXT, source_sheet TEXT,
        source_row INTEGER, panel INTEGER, population TEXT, metapopulation TEXT, country TEXT, haplogroup TEXT,
        haplogroup_status TEXT, marker_scale TEXT, use_status TEXT, comparison_status TEXT, markers_json TEXT,
        metadata_json TEXT, profile_fingerprint TEXT, observed_marker_groups INTEGER, observed_alleles INTEGER);
    CREATE TABLE marker_calls(profile_id TEXT, marker TEXT, raw_json TEXT, alleles_json TEXT, status TEXT,
        annotation TEXT, expected_copies INTEGER);
    CREATE TABLE source_reference_labels(source_id TEXT, reference_label TEXT, profile_count INTEGER,
        reference_kind TEXT, verification_status TEXT);
    """)
    meta = {"purps2014": {"title": "Purps synthetic", "doi": "10.0/purps", "license": "Article CC BY 3.0"},
            "other2026": {"title": "Other synthetic", "license": "Reuse licence requires review"},
            "user_scientific_since_20261008": {"title": "Since", "provided_by_user": True}}
    for sid, m in meta.items():
        c.execute("INSERT INTO sources VALUES (?,?)", (sid, json.dumps(m)))

    def prof(pid, src, sample, markers, md=None, row=1, statuses=None):
        c.execute("INSERT INTO profiles(id, source_id, source_sample_id, source_file, source_sheet, source_row, population,"
                  " country, haplogroup, marker_scale, markers_json, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, src, sample, f"{src}.xlsx", "S1", row, "PopX", "CountryX", None, "publication_as_reported",
                   json.dumps(markers), json.dumps(md or {})))
        for k, v in markers.items():
            st = (statuses or {}).get(k, "observed")
            c.execute("INSERT INTO marker_calls VALUES (?,?,?,?,?,?,?)",
                      (pid, k.replace(" ", ""), json.dumps(v), json.dumps(v if st == "observed" else None), st, None, len(v)))
    for i, (sample, markers, md) in enumerate(purps_rows):
        prof(f"purps2014:{sample}", "purps2014", sample, markers, md, row=i + 1)
    prof("other2026:X1", "other2026", "X1", {**HAP, "DYS19": [15]}, statuses={"DYS448": "zero_requires_review"})
    if extra_since:
        since = {k: v for k, v in HAP.items() if k != "DYS389II"}
        since["DYS389B"] = [16]
        prof("since:1", "user_scientific_since_20261008", "1", since,
             {"source_N": 5, "source_reference": "Roewer 2008"})
        c.execute("INSERT INTO source_reference_labels VALUES (?,?,?,?,?)",
                  ("user_scientific_since_20261008", "Roewer 2008", 1, "citation_as_recorded",
                   "publication_linked_label_and_population_verified"))
    c.commit()
    c.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.var = self.d / "var"
        self.cand = self.d / "cand.db"
        purps = [("A|Pop", HAP, {}), ("A|Pop|record2", {**HAP, "DYS19": [16]}, {"source_identifier_collision_requires_review": True}),
                 ("B|Pop", {**HAP, "DYS390": [23]}, {})]
        make_db(self.cand, [("A|Pop", "Scientific_Purps2014_PPY23", HAP),
                            ("A|Pop|record2", "Scientific_Purps2014_PPY23", {**HAP, "DYS19": [16]}),
                            ("B|Pop", "Scientific_Purps2014_PPY23", {**HAP, "DYS390": [23]}),
                            ("RUS|1", "Scientific_Roewer2008_WesternRussia", HAP),
                            ("RM|1", "Scientific_Ballantyne2014_RM_YSTR", {**HAP, "DYS458": ["19,20"]})],
                [("Scientific_Purps2014_PPY23", "CC BY 3.0", 3), ("Scientific_Roewer2008_WesternRussia", "x", 1),
                 ("Scientific_Ballantyne2014_RM_YSTR", "CC BY 3.0", 1)])
        self.arch = self.d / "arch.db"
        make_archive(self.arch, purps)

    def build(self):
        return tc.build(self.cand, self.arch, tc.catalog_path(self.var), ROOT / "data" / "source_audit.json")


class TestBuild(Base):
    def test_counts_dedup_and_provenance(self):
        stats = self.build()
        self.assertTrue(stats["dedup"]["Scientific_Purps2014_PPY23"]["identical"])
        self.assertEqual(stats["skipped_duplicate_copies"], 3)          # копия кандидата не добавлена повторно
        # архив: purps 3 + other 1 + since 1; кандидат: Roewer 1 + Ballantyne 1
        self.assertEqual((stats["records"], stats["individual_records"], stats["aggregated_records"]), (7, 6, 1))
        self.assertEqual(stats["aggregated_observations"], 5)
        self.assertEqual(stats["id_collisions"], 1)
        self.assertEqual(stats["since_overlaps"], {"Scientific_Roewer2008_WesternRussia": 1})
        con = sqlite3.connect(tc.catalog_path(self.var))
        con.row_factory = sqlite3.Row
        src = {r["source_id"]: dict(r) for r in con.execute("SELECT * FROM sources")}
        self.assertNotIn("Scientific_Purps2014_PPY23", src)
        self.assertIn("совпадает полностью", src["purps2014"]["dedup_note"])
        self.assertTrue(all(s["reuse_note"] == tc.UNVERIFIED_NOTE for s in src.values()))
        self.assertEqual(src["other2026"]["verification_status"], "не проверено")
        self.assertEqual(src["purps2014"]["verification_status"].split(" (")[0], "ждём подтверждения")  # из аудита
        rec = dict(con.execute("SELECT * FROM records WHERE source_sample_id='A|Pop|record2'").fetchone())
        self.assertEqual((rec["source_file"], rec["source_sheet"], rec["source_row"], rec["snapshot"]),
                         ("purps2014.xlsx", "S1", 2, "archive"))
        self.assertIn("коллизия ID", rec["flags_json"])
        since = dict(con.execute("SELECT * FROM records WHERE source_id='user_scientific_since_20261008'").fetchone())
        self.assertEqual((since["record_kind"], since["observed_n"]), ("aggregated", 5))
        self.assertIn("возможное пересечение публикаций", since["flags_json"])
        rm = dict(con.execute("SELECT * FROM records WHERE source_sample_id='RM|1'").fetchone())
        self.assertEqual(json.loads(rm["raw_markers_json"])["DYS458"], ["19,20"])   # исходное значение сохранено
        self.assertEqual(json.loads(rm["positions_json"])["DYS458"][1], "invalid")  # но не сравнивается
        con.close()

    def test_differing_shared_copies_both_kept(self):
        make_archive(self.arch.with_name("arch2.db"), [("A|Pop", HAP, {})])     # в архиве другой состав
        stats = tc.build(self.cand, self.arch.with_name("arch2.db"), tc.catalog_path(self.var))
        self.assertFalse(stats["dedup"]["Scientific_Purps2014_PPY23"]["identical"])
        self.assertEqual(stats["skipped_duplicate_copies"], 0)
        self.assertIn("Scientific_Purps2014_PPY23", stats["by_source"])

    def test_inputs_unchanged_and_separate_from_users(self):
        from inspect_reference import sha256_file
        before = (sha256_file(self.cand), sha256_file(self.arch))
        self.build()
        self.assertEqual(before, (sha256_file(self.cand), sha256_file(self.arch)))
        users = db.connect(self.var / "nestor_users.db")
        self.addCleanup(users.close)
        tables = {r[0] for r in users.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {"records", "sources", "catalog_meta"})
        self.assertNotEqual(tc.catalog_path(self.var), self.var / "nestor_users.db")
        self.assertFalse((ROOT / "data" / "MANIFEST.json").exists())


class TestSwitchAndSearch(Base):
    def test_enable_disable_remove(self):
        self.assertFalse(tc.is_enabled(self.var))
        with self.assertRaises(tc.CatalogError):
            tc.enable(self.var)                                          # не собран
        self.build()
        self.assertFalse(tc.is_enabled(self.var))                         # сборка не включает
        tc.enable(self.var)
        self.assertTrue(tc.is_enabled(self.var))
        self.assertIsNotNone(tc.load_if_enabled(self.var))
        tc.disable(self.var)
        self.assertIsNone(tc.load_if_enabled(self.var))
        tc.enable(self.var)
        tc.remove(self.var)
        self.assertFalse(tc.catalog_dir(self.var).exists())
        self.assertFalse(tc.is_enabled(self.var))

    def test_search_marks_unverified_and_preliminary(self):
        self.build()
        cat = tc.Catalog(tc.catalog_path(self.var))
        q = mk.normalize({k: "-".join(map(str, v)) for k, v in HAP.items()})
        res = cat.search(q, max_gd=1, min_common=10)
        self.assertTrue(res)
        self.assertTrue(all(m.preliminary and m.reuse_note == tc.UNVERIFIED_NOTE for m in res))
        agg = [m for m in res if m.record_kind == "aggregated"]
        self.assertEqual([m.observed_n for m in agg], [5])
        self.assertEqual(agg[0].gd, 0)                                    # DYS389B из источника vs II−I запроса (T16)
        other = next(m for m in res if m.source_id == "other2026")
        self.assertEqual(other.gd, 1)                                     # DYS448 с QC-статусом не сравнивается

    def test_web_shows_catalog_only_when_enabled(self):
        import threading
        import urllib.parse
        import urllib.request
        from nestor_app.config import Settings
        from nestor_app.web import NestorApp
        self.build()
        settings = Settings(var_dir=self.var, users_db=self.var / "u.db", secret_file=self.var / "s.key",
                            manifest_file=self.var / "M.json", port=0, staging_dir=self.var / "staging")
        app = NestorApp(settings)
        self.addCleanup(app.conn.close)
        server = app.make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def guest():
            body = urllib.parse.urlencode({"markers": "\n".join(f"{k}={'-'.join(map(str, v))}" for k, v in HAP.items()),
                                           "max_gd": "1", "min_common": "10", "panel": "CUSTOM"}).encode()
            req = urllib.request.Request(base + "/guest/search", data=body, headers={"Origin": base})
            with urllib.request.urlopen(req) as r:
                return r.read().decode()

        self.assertNotIn("ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ", guest())
        tc.enable(self.var)
        page = guest()
        self.assertIn("ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ", page)
        self.assertIn(tc.UNVERIFIED_NOTE, page)
        self.assertIn("агрегированное наблюдение, N=5", page)
        self.assertIn("(предварительно)", page)
        tc.disable(self.var)
        self.assertNotIn("ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ", guest())               # без перезапуска
        tc.enable(self.var)
        tc.remove(self.var)
        self.assertNotIn("ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ", guest())


if __name__ == "__main__":
    unittest.main()
