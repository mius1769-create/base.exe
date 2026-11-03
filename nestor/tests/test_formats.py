"""Импорт и сравнение во всех поддержанных форматах и панелях (синтетические файлы)."""

import tempfile
import unittest
from pathlib import Path

import format_fixtures as ff
from synthetic import BASE_Y37  # noqa: F401  (путь к nestor_app)

from nestor_app import gd
from nestor_app import importer as im
from nestor_app import markers as mk
from nestor_app import panels as pn
from nestor_app import test_catalog as tc

ROOT = Path(__file__).resolve().parent.parent
KNOWN = {name: code for name, (code, _) in ff.FILES.items() if code}
CUSTOM = [name for name, (code, _) in ff.FILES.items() if not code]


def preview(name: str, panel: str = "AUTO") -> im.Preview:
    return im.build_preview(name, (ff.OUT / name).read_bytes(), panel)


def only_record(p: im.Preview) -> im.Record:
    recs = p.records
    assert len(recs) == 1, recs
    return recs[0]


class TestFixturesUpToDate(unittest.TestCase):
    def test_text_fixtures_match_generator(self):
        for name, (_, fmt) in ff.FILES.items():
            if fmt != "xlsx":
                self.assertEqual((ff.OUT / name).read_bytes(), ff.file_bytes(name), name)
        self.assertEqual((ff.OUT / "Edge-cases.csv").read_bytes(), ff.edge_bytes())
        self.assertEqual((ff.OUT / "Headerless-Y37.csv").read_bytes(), ff.headerless_bytes())

    def test_all_supported_panels_covered(self):
        self.assertEqual(set(KNOWN.values()), set(pn.PANELS))


class TestKnownPanels(unittest.TestCase):
    def test_recognized_and_values_exact(self):
        for name, code in KNOWN.items():
            with self.subTest(name):
                p = preview(name)
                sp = p.sheets[0]
                self.assertEqual((sp.panel_code, sp.panel_basis), (code, "recognized"))
                r = only_record(p)
                self.assertTrue(r.savable)
                self.assertEqual((r.missing, r.invalid), ([], {}))
                self.assertEqual(r.positions, ff.panel_profile(code))
                panel = pn.PANELS[code]
                self.assertEqual(r.observed, len(panel.marker_names))
                self.assertEqual(sum(len(v) for v in r.positions.values()), panel.allele_count)

    def test_selected_panel_same_result(self):
        for name, code in KNOWN.items():
            with self.subTest(name):
                p = preview(name, code)
                self.assertEqual(p.sheets[0].panel_basis, "selected")
                self.assertEqual(only_record(p).positions, ff.panel_profile(code))

    def test_wrong_smaller_panel_rejected(self):
        # Y111-файл с выбранной панелью Y37: локусы вне панели — ошибка, значения не переносятся молча.
        with self.assertRaises(im.ImportError_):
            preview("FTDNA-Y111.csv", "FTDNA_Y37")
        with self.assertRaises(im.ImportError_):
            preview("Genopoisk-Y50.xlsx", "GENOPOISK_Y37")

    def test_marker_counts(self):
        sizes = {code: pn.PANELS[code].allele_count for code in KNOWN.values()}
        self.assertEqual(sizes, {"FTDNA_Y12": 12, "FTDNA_Y25": 25, "FTDNA_Y37": 37, "FTDNA_Y67": 67,
                                 "FTDNA_Y111": 111, "GENOPOISK_Y37": 36, "GENOPOISK_Y50": 52})

    def test_pasted_two_row_table(self):
        for code in ("FTDNA_Y37", "GENOPOISK_Y37", "GENOPOISK_Y50", "FTDNA_Y111"):
            with self.subTest(code):
                header, values = ff.header_and_values(code, "")
                entries = mk.parse_profile_input(";".join(header) + "\n" + ";".join(values))
                positions, got, basis = pn.apply_panel(entries, "AUTO")
                self.assertEqual((got, basis), (code, "recognized"))
                self.assertEqual(positions, ff.panel_profile(code))


class TestCustomSets(unittest.TestCase):
    def test_custom_18_and_50_not_recognized(self):
        for name, n_loci, n_values in (("Custom-18.csv", 17, 18), ("Custom-50.csv", 50, 50)):
            with self.subTest(name):
                p = preview(name)
                self.assertEqual((p.sheets[0].panel_code, p.sheets[0].panel_basis), (None, "custom"))
                r = only_record(p)
                self.assertEqual(r.positions, ff.expected_profile(name))
                self.assertEqual(len(r.positions), n_loci)                    # DYS385a+b — одна позиция
                self.assertEqual(sum(len(v) for v in r.positions.values()), n_values)
                self.assertEqual(r.missing, [])                               # позиции — только заявленные

    def test_custom_header_count_does_not_pick_panel(self):
        # 18 значений, 50 локусов — по числу значений панель не выбирается.
        self.assertIsNone(pn.recognize_panel(ff.expected_profile("Custom-18.csv")))
        self.assertIsNone(pn.recognize_panel(ff.expected_profile("Custom-50.csv")))

    def test_headerless_values_rejected(self):
        data = (ff.OUT / "Headerless-Y37.csv").read_bytes()
        self.assertEqual(len(data.decode().strip().split(";")), 30)          # 30 ячеек = 37 значений Y37
        for panel in ("AUTO", "FTDNA_Y37", "CUSTOM"):
            with self.subTest(panel), self.assertRaises(im.ImportError_):
                im.build_preview("Headerless-Y37.csv", data, panel)
        _, values = ff.header_and_values("FTDNA_Y37", "")
        with self.assertRaises(mk.MarkerError):
            mk.parse_profile_input(";".join(values))                          # одна строка значений
        with self.assertRaises(mk.MarkerError):
            mk.parse_profile_input(" ".join(values))


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        p = im.build_preview("Edge-cases.csv", ff.edge_bytes(), "AUTO")
        self.assertEqual(p.sheets[0].panel_basis, "custom")
        self.r = {r.record_id: r for r in p.records}

    def test_parsing(self):
        full = self.r["E-full"].positions
        self.assertEqual(full["DYS385"], (11.0, 14.0))
        self.assertEqual(full["DYS464"], (15.0, 15.0, 17.0, 17.0))
        self.assertEqual(full["DYF387S1"], (35.0, 37.0))
        self.assertIsNone(full["DYS389B"])                                   # пустая колонка
        miss = self.r["E-missing"]
        self.assertEqual(miss.missing, ["DYS389B", "DYS389II", "DYS390", "DYS391", "DYS458"])   # пусто, «0», «-»
        dec = self.r["E-decimal"].positions
        self.assertEqual((dec["DYS385"], dec["DYS458"]), ((11.0, 13.2), (17.2,)))
        cop = self.r["E-copies"]
        self.assertIsInstance(cop.positions["DYS385"], mk.Invalid)          # одна копия из пары
        self.assertIsInstance(cop.positions["DYS464"], mk.Invalid)          # три копии из четырёх
        self.assertEqual(cop.positions["DYF387S1"], (35.0,))
        inv = self.r["E-invalid"]
        self.assertEqual(inv.invalid, {"DYS389I": "del", "DYS448": "x19"})
        self.assertEqual(inv.raw["DYS389I"], "del")                          # исходная ячейка дословно

    def test_gd_rules(self):
        full = self.r["E-full"].positions
        # T18: дробные различия не переводятся в шаги — GD предварительный.
        res = gd.genetic_distance(full, self.r["E-decimal"].positions)
        self.assertEqual(res.gd, 0)
        self.assertTrue(res.preliminary)
        self.assertEqual({x[0] for x in res.allele_differences}, {"DYS385", "DYS458"})
        # T17: разное подтверждённое число копий — вне GD и compared.
        res = gd.genetic_distance(full, self.r["E-copies"].positions)
        self.assertEqual(res.copy_count_differences, (("DYF387S1", 2, 1),))
        self.assertEqual({x[0] for x in res.missing_or_invalid} >= {"DYS385", "DYS464"}, True)
        # T16: DYS389B = II − I (29 − 13 = 16) совпадает с опубликованным DYS389B.
        res = gd.genetic_distance({k: v for k, v in full.items() if k != "DYS389B"}, self.r["E-389B"].positions)
        self.assertEqual(res.gd, 0)
        self.assertIn("DYS389B", res.derived_loci)
        self.assertNotIn("DYS389B", [x[0] for x in res.missing_or_invalid])
        # нераспознанные и пропуски — missing_or_invalid, не +1.
        res = gd.genetic_distance(full, self.r["E-invalid"].positions)
        self.assertEqual(res.gd, 0)
        self.assertTrue({"DYS389I", "DYS448"} <= {x[0] for x in res.missing_or_invalid})
        res = gd.genetic_distance(full, self.r["E-missing"].positions)
        self.assertEqual(res.gd, 0)
        self.assertEqual(res.panel_overlap, res.compared + len(res.missing_or_invalid))


class TestComparison(unittest.TestCase):
    def test_identical_and_one_step(self):
        for name in list(KNOWN) + CUSTOM:
            with self.subTest(name):
                a = only_record(preview(name)).positions
                res = gd.genetic_distance(a, ff.expected_profile(name))
                self.assertEqual((res.gd, res.preliminary), (0, False))
                n_positions = len(a)                                         # DYS389II заменён на DYS389B
                self.assertEqual(res.compared, n_positions)
                b = dict(a)
                b["DYS393"] = (b["DYS393"][0] + 1,)
                self.assertEqual(gd.genetic_distance(a, b).gd, 1)
                if "DYS389I" in a and "DYS389II" in a:                       # T16: I+1 меняет I и B
                    c = dict(a)
                    c["DYS389I"] = (14.0,)
                    self.assertEqual(gd.genetic_distance(a, c).gd, 2)

    def test_cross_panel_overlap(self):
        y111 = only_record(preview("FTDNA-Y111.csv")).positions
        g50 = only_record(preview("Genopoisk-Y50.xlsx")).positions
        res = gd.genetic_distance(y111, g50)
        common = set(gd.gd_view(y111)[0]) & set(gd.gd_view(g50)[0])
        self.assertEqual(res.panel_overlap, len(common))
        self.assertEqual(res.compared, len(common))
        self.assertEqual(res.gd, 0)
        y12 = only_record(preview("FTDNA-Y12.csv")).positions
        self.assertEqual(gd.genetic_distance(y12, y111).compared, 11)     # 11 позиций Y12 (II → B)

    def test_against_test_catalog(self):
        import test_test_catalog as ttc
        from test_inspect_reference import make_db
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            rows = []
            for i, name in enumerate(KNOWN):
                prof = {k: list(v) for k, v in ff.panel_profile(KNOWN[name]).items()}
                rows.append((f"S{i}|{name}", prof, {}))
            ttc.make_archive(d / "a.db", rows, extra_since=False)
            make_db(d / "c.db", [("X|1", "Scientific_Underhill2015_R1a_YSTR", {"DYS393": [13]})],
                    [("Scientific_Underhill2015_R1a_YSTR", "x", 1)])
            tc.build(d / "c.db", d / "a.db", tc.catalog_path(d / "var"), ROOT / "data" / "source_audit.json")
            cat = tc.Catalog(tc.catalog_path(d / "var"))
            for name in KNOWN:
                with self.subTest(name):
                    q = only_record(preview(name)).positions
                    hits = {m.sample_id: m for m in cat.search(q, max_gd=0, min_common=10)}
                    exact = hits[f"S{list(KNOWN).index(name)}|{name}"]
                    self.assertEqual(exact.gd, 0)
                    self.assertTrue(exact.preliminary)
                    self.assertEqual(exact.reuse_note, tc.UNVERIFIED_NOTE)


if __name__ == "__main__":
    unittest.main()
