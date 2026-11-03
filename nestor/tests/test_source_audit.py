import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import render_source_audit  # noqa: E402

AUDIT = json.loads((ROOT / "data" / "source_audit.json").read_text(encoding="utf-8"))
RULES = json.loads((ROOT / "data" / "transform_rules.json").read_text(encoding="utf-8"))
SCENARIOS = {"local_closed_prototype", "genealogical_matching", "public_distribution"}


class TestSourceAudit(unittest.TestCase):
    def test_counts_cover_whole_candidate(self):
        total = sum(s["records"] for s in AUDIT["sources"])
        self.assertEqual(total, AUDIT["candidate"]["records"])
        self.assertEqual(sum(AUDIT["summary"].values()), total)
        for status, n in AUDIT["summary"].items():
            self.assertEqual(n, sum(s["records"] for s in AUDIT["sources"] if s["decision"] == status), status)

    def test_every_source_has_dataset_terms_scenarios_and_attribution(self):
        for s in AUDIT["sources"]:
            with self.subTest(s["source"]):
                self.assertIn(s["decision"], AUDIT["decisions"])
                self.assertEqual(set(s["scenarios"]), SCENARIOS)
                for sc in s["scenarios"].values():
                    self.assertIn(sc["verdict"], AUDIT["verdicts"])
                    self.assertTrue(sc["basis"])
                d = s["dataset"]
                self.assertTrue(d["table"] and d["raw_file"] and d["primary_location"])
                self.assertTrue(d["dataset_terms"]["statement"] and d["dataset_terms"]["to_confirm"])
                self.assertTrue(s["attribution"])
                self.assertTrue(s["quality"])

    def test_article_license_is_not_treated_as_dataset_license(self):
        for s in AUDIT["sources"]:
            if "CC BY" in s["article_terms"]["statement"]:
                self.assertFalse(s["dataset"]["dataset_terms"]["confirmed"], s["source"])
                self.assertNotEqual(s["scenarios"]["public_distribution"]["verdict"], "допустимо")

    def test_nothing_admitted_or_connected(self):
        for s in AUDIT["sources"]:
            self.assertNotEqual(s["decision"], "допущен", s["source"])
            self.assertNotEqual(s["scenarios"]["genealogical_matching"]["verdict"], "допустимо")
        self.assertFalse((ROOT / "data" / "MANIFEST.json").exists())

    def test_nist_names_concrete_dataset_terms(self):
        nist = next(s for s in AUDIT["sources"] if "NIST" in s["source"])
        terms = nist["dataset"]["dataset_terms"]
        self.assertIn("10.18434/t4/1500024", terms["statement"])
        self.assertIn("nist.gov/open/license", terms["statement"])
        self.assertIn("группы", " ".join(nist["quality"]))
        self.assertTrue(nist["provenance"]["confirmed"])
        self.assertEqual(nist["status_detail"],
                         "происхождение и состав подтверждены, использование в NeSToR ожидает проверки условий")
        self.assertFalse(terms["confirmed"])
        self.assertIn("лицензия статьи", terms["statement"])
        self.assertEqual(nist["decision"], "ждём подтверждения")
        g = nist["provenance"]["group_totals"]
        self.assertEqual(g["counts"], {"African American": 341, "Asian": 96, "Caucasian": 359, "Hispanic": 236})
        self.assertEqual(sum(g["counts"].values()), g["total"])
        self.assertEqual(g["total"], nist["records"])
        self.assertIn("1036", nist["catalog_level"]["statement"])
        self.assertEqual(nist["dataset"]["primary_file"]["sha256"],
                         "9996de5d267d79b4eaa61f641303ff5a2b5192a6848694dc3a11f0a0610fd2ed")
        rec = json.loads((ROOT / "docs" / "NIST_RECONCILIATION.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["counts"], {"candidate": 1032, "table_s4": 1032})
        self.assertEqual(rec["candidate_vs_s4"]["differences_by_locus"], {})
        self.assertEqual(sum(rec["candidate_vs_s4"]["del_in_s4_absent_in_candidate"].values()), 6)
        self.assertIsNone(rec["groups"]["origin"])  # групп в Table S4 нет — построчно не назначены
        self.assertEqual(rec["font_flags"], {"father_son_substitution": 52})

    def test_value_codes_documented_separately(self):
        codes = json.loads((ROOT / "data" / "value_codes.json").read_text(encoding="utf-8"))["codes"]
        nist = {c["code"] for c in codes if "NIST" in c["source"]}
        self.assertEqual(nist, {"del", "*", "**", "font:FF0070C0"})
        by_code = {c["code"]: c for c in codes if "NIST" in c["source"]}
        self.assertTrue(by_code["*"]["confirmed_by_primary"] and by_code["**"]["confirmed_by_primary"])
        self.assertFalse(by_code["del"]["confirmed_by_primary"])  # легенда Table S4 не определяет del
        self.assertEqual(sum(by_code["del"]["occurrences"].values()), 6)
        for c in codes:
            self.assertTrue(c["meaning"] and c["basis"])

    def test_transform_rules_have_basis_and_are_not_applied(self):
        ids = [r["rule_id"] for r in RULES["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        for r in RULES["rules"]:
            self.assertTrue(r["basis"], r["rule_id"])
            self.assertIn(r["status"], ("proposed", "approved"), r["rule_id"])
            if r["status"] == "approved":
                self.assertIn("решение заказчика", r["basis"], r["rule_id"])
        approved = {r["rule_id"] for r in RULES["rules"] if r["status"] == "approved"}
        self.assertEqual(approved, {"T08-father-son", "T09-del-excluded", "T10-binary-float"})

    def test_report_is_up_to_date(self):
        self.assertEqual(render_source_audit.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
