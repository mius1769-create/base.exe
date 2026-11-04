"""Вкладки результатов: глубина у каталога, панели у профилей, 20% гостя не обходятся."""

import unittest

from synthetic import BASE_Y37, SECRET, SINGLE_COPY, new_conn, new_user

from nestor_app import compare_ui
from nestor_app import markers as mk
from nestor_app import profiles as pr
from nestor_app import search
from nestor_app import test_catalog as tc

LOCI = [f"DYS{n}" for n in range(100, 140)]


def values(n, changes=None):
    pos = {k: mk.from_storage("12", "ok") for k in LOCI[:n]}
    pos.update({k: mk.from_storage(v, "ok") for k, v in (changes or {}).items()})
    return pos


def catalog(*sizes):
    cat = tc.Catalog.__new__(tc.Catalog)
    cat.sources = {"s": {"verification_status": "не проверено", "reuse_note": tc.UNVERIFIED_NOTE, "title": "S"}}
    cat.records = [tc._Rec("s", f"r{n}", None, "individual", 1, values(n), (), None, None) for n in sizes]
    return cat


class DepthTabs(unittest.TestCase):
    def search(self, cat, **kw):
        return cat.compare_summary(values(40), max_gd=4, min_common=5, **kw)

    def counts(self, summary):
        return {code: n for code, _, n in summary["tiers"]}

    def test_counts_by_compared_positions(self):
        _, s = self.search(catalog(8, 12, 16, 17, 27, 28, 37, 38, 40))
        self.assertEqual(self.counts(s), {"all": 9, "12-16": 2, "17-27": 2, "28-37": 2, "38+": 2})

    def test_opens_deepest_tab_with_results(self):
        matches, s = self.search(catalog(12, 20))
        self.assertEqual(s["tier"], "17-27")
        self.assertEqual([m.sample_id for m in matches], ["r20"])
        self.assertEqual(s["total"], 1)

    def test_selected_tab_and_all(self):
        cat = catalog(12, 20)
        self.assertEqual([m.sample_id for m in self.search(cat, depth="12-16")[0]], ["r12"])
        self.assertEqual({m.sample_id for m in self.search(cat, depth="all")[0]}, {"r12", "r20"})

    def test_unknown_tab_falls_back_to_default(self):
        self.assertEqual(self.search(catalog(12), depth="<script>")[1]["tier"], "12-16")

    def test_tabs_render_empty_ones_disabled(self):
        _, s = self.search(catalog(12))
        html = compare_ui.depth_tabs(s, action="/compare", method="post", hidden={"markers": "A=1", "depth": "x"})
        self.assertIn('name="markers" value="A=1"', html)
        self.assertNotIn('type="hidden" name="depth"', html)
        self.assertIn('value="12-16" class=on', html)
        self.assertIn('value="38+" disabled', html)


class PanelTabs(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)

    def add(self, n, markers):
        uid = new_user(self.conn, n)
        pid = pr.create_profile(self.conn, uid, markers, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, uid, pid, True)
        return self.conn.execute("SELECT public_handle FROM profiles WHERE id=?", (pid,)).fetchone()[0]

    def test_gd_counts_only_panel_loci_and_short_profile_stays_off_long_tabs(self):
        y12 = search._panel_positions("FTDNA_Y12")
        outside = next(k for k in SINGLE_COPY if k not in y12 and k != "DYS389II")   # DYS389II входит в Y12 через DYS389B
        handle = self.add(1, {**BASE_Y37, outside: (BASE_Y37[outside][0] + 1,)})
        tabs = search.panel_tabs(self.conn, BASE_Y37, max_gd=4, viewer="registered")
        self.assertEqual([(m.handle, m.gd) for m in tabs["FTDNA_Y12"]], [(handle, 0)])
        self.assertEqual([(m.handle, m.gd) for m in tabs["FTDNA_Y37"]], [(handle, 1)])
        self.assertEqual(tabs["FTDNA_Y111"], [])
        self.assertEqual(search.default_panel_tab(tabs), "FTDNA_Y37")

    def test_empty_means_all_tab(self):
        self.assertEqual(search.default_panel_tab(search.panel_tabs(self.conn, BASE_Y37, max_gd=4, viewer="guest")), search.TAB_ALL)

    def test_guest_tabs_never_exceed_guest_sample(self):
        for i in range(20):
            self.add(i, BASE_Y37)
        res = search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=4, min_common=12)
        sample = {m.handle for m in res.matches}
        self.assertEqual(len(sample), 4)
        tabs = search.panel_tabs(self.conn, BASE_Y37, max_gd=4, viewer="guest", only_handles=sample)
        seen = {m.handle for rows in tabs.values() for m in rows}
        self.assertEqual(seen, sample)
        self.assertEqual(len(tabs["FTDNA_Y37"]), 4)

    def test_tabs_keep_private_fields_hidden_from_guest(self):
        uid = new_user(self.conn, 1)
        pid = pr.create_profile(self.conn, uid, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, uid, pid, True)
        pr.update_public_fields(self.conn, uid, pid, nickname="Скрытый", nickname_visibility="registered",
                                ancestor_text=None, ancestor_visibility="hidden")
        tabs = search.panel_tabs(self.conn, BASE_Y37, max_gd=4, viewer="guest")
        self.assertIsNone(tabs["FTDNA_Y37"][0].nickname)


if __name__ == "__main__":
    unittest.main()
