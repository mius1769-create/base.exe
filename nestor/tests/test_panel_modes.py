import unittest
from pathlib import Path

from synthetic import BASE_Y37, new_conn, new_user  # noqa: F401  (путь к nestor_app)

from nestor_app import markers as mk
from nestor_app import panels
from nestor_app import profiles as pr
from nestor_app import search
from nestor_app.gd import genetic_distance

FIX = Path(__file__).resolve().parent / "fixtures" / "archive_examples"


def read_fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8-sig")


def drop_column(table: str, locus: str) -> str:
    header, values = [ln for ln in table.splitlines() if ln.strip()]
    h, v = header.split(";"), values.split(";")
    i = h.index(locus)
    return ";".join(h[:i] + h[i + 1:]) + "\n" + ";".join(v[:i] + v[i + 1:])


class TestArchiveControlFiles(unittest.TestCase):
    """Синтетические контрольные CSV архива (examples/README.txt: «synthetic parser controls»)."""

    def test_control_files_parse_and_are_recognized(self):
        for name, code, n in (("FTDNA-Y37.csv", "FTDNA_Y37", 30), ("Genopoisk-Y37.csv", "GENOPOISK_Y37", 33),
                              ("Genopoisk-Y50.csv", "GENOPOISK_Y50", 48)):
            entries = mk.parse_table_entries(read_fixture(name))
            self.assertEqual(len(entries), n, name)
            self.assertEqual(list(entries), list(panels.PANELS[code].marker_names), name)  # порядок панели
            self.assertEqual(panels.recognize_panel(entries), code, name)

    def test_known_panel_file_without_one_header(self):
        text = drop_column(read_fixture("FTDNA-Y37.csv"), "DYS439")
        entries = mk.parse_table_entries(text)
        self.assertEqual(len(entries), 29)
        positions, code, basis = panels.apply_panel(entries, "AUTO")
        self.assertEqual((code, basis), ("FTDNA_Y37", "recognized"))
        self.assertEqual(len(positions), 30)
        self.assertIsNone(positions["DYS439"])                 # позиция панели без значения
        full = mk.parse_table_entries(read_fixture("FTDNA-Y37.csv"))
        r = genetic_distance(positions, full)
        self.assertEqual((r.panel_overlap, r.compared), (30, 29))
        self.assertEqual(r.missing_or_invalid, (("DYS439", "нет значения у одного"),))

    def test_genopoisk_y50_file_without_one_header(self):
        text = drop_column(read_fixture("Genopoisk-Y50.csv"), "DYS520")
        positions, code, basis = panels.apply_panel(mk.parse_table_entries(text), "AUTO")
        self.assertEqual((code, basis, len(positions)), ("GENOPOISK_Y50", "recognized", 48))
        self.assertIsNone(positions["DYS520"])


class TestSelectedPanel(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)

    def _profile(self, user_n, markers, panel_code, searchable=True):
        uid = new_user(self.conn, user_n)
        pid = pr.create_profile(self.conn, uid, markers, consent_basis="own_test", consent_confirmed=True,
                                panel_code=panel_code)
        if searchable:
            pr.set_searchable(self.conn, uid, pid, True)
        return uid, pid

    def test_selected_panel_with_missing_locus(self):
        partial = {k: v for k, v in BASE_Y37.items() if k != "DYS448"}
        uid, pid = self._profile(1, partial, "FTDNA_Y37")
        p = pr.get_owned(self.conn, uid, pid)
        self.assertEqual((p.panel_code, p.panel_basis, len(p.markers)), ("FTDNA_Y37", "selected", 30))
        self.assertIsNone(p.markers["DYS448"])
        owner, own = self._profile(2, dict(BASE_Y37), "FTDNA_Y37")
        [m] = search.owner_search(self.conn, owner, own, min_common=29)
        self.assertEqual((m.panel_overlap, m.compared, m.missing_or_invalid), (30, 29, 1))
        self.assertEqual(search.owner_search(self.conn, owner, own, min_common=30), [])  # порог — только compared

    def test_locus_outside_selected_panel_is_rejected(self):
        with self.assertRaises(pr.ProfileError):
            self._profile(1, {**BASE_Y37, "DYS999": (10.0,)}, "FTDNA_Y37")

    def test_unsupported_panel_rejected(self):
        with self.assertRaises(pr.ProfileError):
            self._profile(1, dict(BASE_Y37), "Y700")

    def test_partial_profile_without_panel(self):
        partial = {k: BASE_Y37[k] for k in list(BASE_Y37)[:12]}
        uid, pid = self._profile(1, partial, "AUTO")             # 12 из 30 — не распознаётся
        p = pr.get_owned(self.conn, uid, pid)
        self.assertEqual((p.panel_code, p.panel_basis, len(p.markers)), (None, "custom", 12))
        self.assertIn("пользовательский набор", panels.panel_label(p.panel_code, p.panel_basis))
        owner, own = self._profile(2, dict(BASE_Y37), "FTDNA_Y37")
        [m] = search.owner_search(self.conn, owner, own, min_common=12)
        self.assertEqual((m.panel_overlap, m.compared, m.missing_or_invalid), (12, 12, 0))
        self.assertEqual(search.owner_search(self.conn, owner, own, min_common=13), [])

    def test_same_partial_input_with_selected_panel_counts_missing(self):
        partial = {k: BASE_Y37[k] for k in list(BASE_Y37)[:12]}
        uid, pid = self._profile(1, partial, "FTDNA_Y37")
        owner, own = self._profile(2, dict(BASE_Y37), "FTDNA_Y37")
        [m] = search.owner_search(self.conn, owner, own, min_common=12)
        self.assertEqual((m.panel_overlap, m.compared, m.missing_or_invalid), (30, 12, 18))

    def test_recognition_requires_reliable_match(self):
        self.assertIsNone(panels.recognize_panel([]))
        self.assertEqual(panels.recognize_panel(list(BASE_Y37)[:20]), "FTDNA_Y25")  # ровно состав Y25
        self.assertIsNone(panels.recognize_panel(list(BASE_Y37)[:17]))           # 17/20 < 90%, 17/30 < 90%
        self.assertEqual(panels.recognize_panel(list(BASE_Y37)[:11]), "FTDNA_Y12")  # ровно Y12
        self.assertIsNone(panels.recognize_panel(list(BASE_Y37) + ["DYS999"]))   # локус вне панелей
        self.assertEqual(panels.recognize_panel(list(BASE_Y37)), "FTDNA_Y37")


if __name__ == "__main__":
    unittest.main()
