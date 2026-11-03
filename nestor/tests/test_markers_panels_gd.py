import unittest

from synthetic import BASE_Y37

from nestor_app import markers as mk
from nestor_app import panels
from nestor_app.gd import genetic_distance, marker_distance


class TestMarkerParsing(unittest.TestCase):
    def test_manual_text_normalizes_names_and_values(self):
        p = mk.parse_manual_text("dys393 = 13\nDYS385a=14; DYS385b=11\nDYS389-1=13\nYGATAH4=11\nDYS19=0\nDYS390=")
        self.assertEqual(p["DYS393"], (13.0,))
        self.assertEqual(p["DYS385"], (11.0, 14.0))  # копии объединены и отсортированы
        self.assertEqual(p["DYS389I"], (13.0,))
        self.assertEqual(p["Y-GATA-H4"], (11.0,))
        self.assertNotIn("DYS19", p)  # 0 = нет значения
        self.assertNotIn("DYS390", p)  # пусто = нет значения

    def test_combined_multicopy_and_microvariant(self):
        p = mk.parse_manual_text("DYS464=17-15-17-15\nDYS458=17.2")
        self.assertEqual(p["DYS464"], (15.0, 15.0, 17.0, 17.0))
        self.assertEqual(p["DYS458"], (17.2,))

    def test_rejects_garbage_and_duplicates(self):
        with self.assertRaises(mk.MarkerError):
            mk.parse_manual_text("DYS393=abc")
        with self.assertRaises(mk.MarkerError):
            mk.parse_manual_text("DYS393=13\nDYS393=14")
        with self.assertRaises(mk.MarkerError):
            mk.parse_manual_text("DYS393 13")
        with self.assertRaises(mk.MarkerError):
            mk.parse_manual_text("DYS393=0")

    def test_canonical_string_independent_of_input_order(self):
        a = mk.parse_manual_text("DYS393=13\nDYS390=24\nDYS385=14-11")
        b = mk.parse_manual_text("DYS385b=11; DYS390=24; dys393=13; DYS385a=14")
        self.assertEqual(mk.canonical_string(a), mk.canonical_string(b))


class TestPanels(unittest.TestCase):
    def test_ftdna_panel_sizes_and_order(self):
        self.assertEqual(panels.get_panel("FTDNA_Y12").allele_count, 12)
        self.assertEqual(panels.get_panel("FTDNA_Y25").allele_count, 25)
        y37 = panels.get_panel("ftdna_y37")
        self.assertEqual(y37.allele_count, 37)
        self.assertEqual(y37.marker_names[:5], ("DYS393", "DYS390", "DYS19", "DYS391", "DYS385"))
        self.assertEqual(y37.marker_names[-1], "DYS438")
        # Y12 — префикс Y25, Y25 — префикс Y37 (порядок сохраняется)
        y25 = panels.get_panel("FTDNA_Y25")
        self.assertEqual(y37.marker_names[: len(y25.marker_names)], y25.marker_names)
        self.assertTrue(all(p.status == "provisional" for p in panels.PANELS.values()))

    def test_y700_and_unverified_panels_unsupported(self):
        for code in ("Y700", "FTDNA_Y700", "FTDNA_Y111", "GENOPOISK_Y50", "STRELKA"):
            with self.assertRaises(panels.UnsupportedPanel):
                panels.get_panel(code)
        with self.assertRaises(panels.UnsupportedPanel):
            panels.get_panel("whatever")

    def test_ordered_and_missing_markers(self):
        y12 = panels.get_panel("FTDNA_Y12")
        partial = {k: v for k, v in BASE_Y37.items() if k != "DYS439"}
        self.assertEqual(panels.missing_markers(y12, partial), ["DYS439"])
        ordered = panels.ordered_markers(y12, partial)
        self.assertEqual([n for n, _ in ordered], list(y12.marker_names))
        self.assertIsNone(dict(ordered)["DYS439"])
        self.assertEqual(panels.best_complete_panel(BASE_Y37), "FTDNA_Y37")
        self.assertEqual(panels.best_complete_panel(partial), None)


class TestGD(unittest.TestCase):
    def test_identical_profiles(self):
        r = genetic_distance(BASE_Y37, dict(BASE_Y37))
        self.assertEqual((r.gd, r.common), (0, 30))

    def test_single_and_multi_copy_steps(self):
        other = dict(BASE_Y37)
        other["DYS393"] = (15.0,)               # +2
        other["DYS385"] = (11.0, 15.0)          # +1
        other["DYS464"] = (15.0, 16.0, 17.0, 17.0)  # +1
        self.assertEqual(genetic_distance(BASE_Y37, other).gd, 4)

    def test_copy_number_difference_and_microvariant(self):
        self.assertEqual(marker_distance((15.0, 15.0, 17.0, 17.0), (15.0, 15.0, 17.0, 17.0, 18.0)), 1)
        self.assertEqual(marker_distance((12.0,), (12.1,)), 1)
        self.assertEqual(marker_distance((12.0,), (14.0,)), 2)

    def test_only_common_markers_are_compared(self):
        short = {k: BASE_Y37[k] for k in ("DYS393", "DYS390", "DYS19")}
        r = genetic_distance(short, BASE_Y37)
        self.assertEqual((r.gd, r.common), (0, 3))
        self.assertEqual(genetic_distance(short, {"DYS999": (10.0,)}).common, 0)


if __name__ == "__main__":
    unittest.main()
