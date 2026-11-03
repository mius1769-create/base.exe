import json
import unittest
from pathlib import Path

AUDIT = Path(__file__).resolve().parent.parent / "data" / "source_audit.json"
STATUSES = {"propose_include_conditional", "exclude_pending_terms", "exclude_pending_permission"}


class TestSourceAudit(unittest.TestCase):
    def setUp(self):
        self.audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    def test_counts_cover_whole_candidate(self):
        total = sum(s["records"] for s in self.audit["sources"])
        self.assertEqual(total, self.audit["candidate"]["records"])
        p = self.audit["proposal"]
        self.assertEqual(p["include_conditional_records"] + p["exclude_records"], total)
        inc = sum(s["records"] for s in self.audit["sources"] if s["status"] == "propose_include_conditional")
        self.assertEqual(inc, p["include_conditional_records"])

    def test_every_license_claim_has_evidence_and_primary_page(self):
        for s in self.audit["sources"]:
            self.assertIn(s["status"], STATUSES, s["source"])
            self.assertTrue(s["license_evidence"], s["source"])
            self.assertTrue(all(e["url"].startswith("https://") for e in s["license_evidence"]))
            self.assertTrue(s["primary_to_confirm"], s["source"])
            self.assertTrue(s["condition"], s["source"])

    def test_nothing_is_connected_yet(self):
        self.assertFalse((AUDIT.parent / "MANIFEST.json").exists())


if __name__ == "__main__":
    unittest.main()
