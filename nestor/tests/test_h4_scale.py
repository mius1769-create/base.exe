"""Предупреждение о шкале Y-GATA-H4: значения и GD не меняются, только пометки."""

import unittest

from nestor_app import compare_ui
from nestor_app import markers as mk
from nestor_app import test_catalog as tc

LOCI = ["DYS19", "DYS388", "DYS390", "DYS391", "DYS392", "DYS393", "DYS437", "DYS438", "DYS439", "DYS448", "DYS456", "DYS458"]
EXCLUDE_H4 = ("Y-GATA-H4",)


def positions(h4):
    pos = {k: mk.from_storage("12", "ok") for k in LOCI}
    if h4 is not None:
        pos["Y-GATA-H4"] = mk.from_storage(str(h4), "ok")
    return pos


def catalog(*h4_values):
    cat = tc.Catalog.__new__(tc.Catalog)
    cat.sources = {"s": {"verification_status": "не проверено", "reuse_note": tc.UNVERIFIED_NOTE, "title": "S"}}
    cat.records = [tc._Rec("s", f"r{v}", None, "individual", 1, positions(v), (), None, None) for v in h4_values]
    return cat


class H4Scale(unittest.TestCase):
    def search(self, cat, query_h4=12, max_gd=10, excluded=()):
        return cat.compare_summary(positions(query_h4), max_gd=max_gd, min_common=10, excluded=excluded)

    def test_values_on_both_sides_of_threshold_get_a_note_and_gd_is_unchanged(self):
        (m,), _ = self.search(catalog(21))
        self.assertEqual(m.gd, 9)
        self.assertIn("у вас 12, в записи 21", m.scale_note)
        page = compare_ui.matches_table([m], {"total": 1, "individual": 1, "aggregated": 0, "aggregated_n": 0})
        self.assertIn("другая шкала H4?", page)
        self.assertIn("GD 9", page)

    def test_same_side_of_threshold_has_no_note(self):
        for query, record in ((12, 13), (17, 12), (21, 22)):
            (m,), _ = self.search(catalog(record), query_h4=query)
            self.assertEqual(m.scale_note, "", (query, record))

    def test_threshold_is_18(self):
        (m,), _ = self.search(catalog(18))
        self.assertTrue(m.scale_note)

    def test_profile_on_the_high_side_also_gets_a_note(self):
        (m,), _ = self.search(catalog(12), query_h4=21)
        self.assertIn("у вас 21, в записи 12", m.scale_note)

    def test_no_note_without_h4_on_one_side_or_when_excluded(self):
        (m,), _ = self.search(catalog(21), query_h4=None)
        self.assertEqual(m.scale_note, "")
        (m,), summary = self.search(catalog(21), excluded=EXCLUDE_H4)
        self.assertEqual((m.gd, m.scale_note, summary["h4_hidden"]), (0, "", 0))

    def test_hidden_counts_only_records_kept_out_by_h4(self):
        cat = catalog(12, 21, 22)
        cat.records.append(tc._Rec("s", "other", None, "individual", 1,
                                   {**positions(21), "DYS19": mk.from_storage("30", "ok")}, (), None, None))
        matches, summary = self.search(cat, max_gd=4)
        self.assertEqual([m.sample_id for m in matches], ["r12"])
        self.assertEqual(summary["h4_hidden"], 2)                      # r21, r22; у «other» различий хватает и без H4
        self.assertIn("только из-за Y-GATA-H4: 2", compare_ui.h4_hidden_note(summary))

    def test_nothing_hidden_means_no_note(self):
        _, summary = self.search(catalog(12), max_gd=4)
        self.assertEqual(compare_ui.h4_hidden_note(summary), "")


if __name__ == "__main__":
    unittest.main()
