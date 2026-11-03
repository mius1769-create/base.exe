import json
import unittest

from synthetic import BASE_Y37  # noqa: F401  (добавляет путь к nestor_app)

from nestor_app.reference_rules import RawValueError, comparison_profile, split_for_matching


class TestReferenceRules(unittest.TestCase):
    """Синтетические строки в формате Table S4; сырые значения не меняются."""

    def test_del_kept_raw_and_excluded_from_comparison(self):
        raw = {"DYS19": "15", "DYS448": "del", "DYS389I": "DEL"}
        before = json.dumps(raw)
        p = comparison_profile(raw)
        self.assertEqual(json.dumps(raw), before)
        self.assertEqual(p.markers, {"DYS19": (15.0,)})
        self.assertEqual(set(p.excluded_loci), {"DYS448", "DYS389I"})
        self.assertNotIn("DYS448", p.markers)  # не пропуск-ноль и не значение
        self.assertIn("T09-del-excluded", p.rules_applied)

    def test_binary_float_normalized_for_comparison_only(self):
        raw = {"DYS518": "33.200000000000003", "DYS19": "14"}
        p = comparison_profile(raw)
        self.assertEqual(p.markers["DYS518"], (33.2,))
        self.assertEqual(raw["DYS518"], "33.200000000000003")
        self.assertEqual(p.rules_applied, ["T10-binary-float"])
        self.assertEqual(comparison_profile({"DYS456": "16.2"}).rules_applied, [])
        self.assertEqual(comparison_profile({"DYS19": "14"}).rules_applied, [])
        self.assertEqual(comparison_profile({"DYS458": "17.25"}).markers["DYS458"], (17.25,))  # без округления

    def test_annotation_codes_become_flags(self):
        p = comparison_profile({"DYS481": "24*", "DYS456": "16.2**", "DYS385": "15,17"})
        self.assertEqual(p.markers, {"DYS481": (24.0,), "DYS456": (16.2,), "DYS385": (15.0, 17.0)})
        self.assertEqual(p.locus_flags, {"DYS481": ["*"], "DYS456": ["**"]})

    def test_father_son_records_kept_separate(self):
        regular = comparison_profile({"DYS19": "14"})
        flagged = comparison_profile({"DYS19": "14"}, {"father_son_substitution": "true"})
        self.assertTrue(regular.independent_observation)
        self.assertFalse(flagged.independent_observation)
        self.assertEqual(flagged.record_flags, ["father_son_substitution"])
        reg, flg = split_for_matching({"A": regular, "B": flagged})
        self.assertEqual((list(reg), list(flg)), (["A"], ["B"]))

    def test_unknown_text_is_an_error_not_a_guess(self):
        with self.assertRaises(RawValueError):
            comparison_profile({"DYS19": "n/a"})


if __name__ == "__main__":
    unittest.main()
