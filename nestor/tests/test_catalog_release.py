"""Сборка тестового каталога из «исходного архива»: SHA-256, количества, атомарность, интерфейс."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import synthetic_release as sr

from nestor_app import catalog_release as cr
from nestor_app import test_catalog as tc

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "data" / "source_audit.json"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.exp = {**cr.EXPECTED, **sr.write(self.d / "in")}
        self.var = self.d / "var"

    def build(self, release="Synthetic_expert.tar.gz", **kw):
        return cr.build_release(self.d / "in" / release, self.d / "in" / "Synthetic_candidate.db", self.var, AUDIT,
                                expected=kw.pop("expected", self.exp), **kw)

    def leftovers(self):
        return sorted(p.name for p in tc.catalog_dir(self.var).iterdir() if p.name.startswith("_"))


class TestBuildRelease(Base):
    def test_tar_gz(self):
        rep = self.build(enable=True)
        self.assertTrue(rep["ok"], rep.get("error"))
        self.assertEqual(rep["counts"], sr.COUNTS)
        self.assertEqual(rep["sqlite_member"], "genopoisk-expert/reference/scientific.sqlite")
        self.assertTrue(rep["enabled"] and tc.is_enabled(self.var))
        self.assertEqual(self.leftovers(), [])                       # извлечённый sqlite удалён
        saved = json.loads((tc.catalog_dir(self.var) / cr.REPORT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["counts"], sr.COUNTS)
        self.assertEqual(saved["sources_status"]["user_scientific_since_20261008"]["kind"], "aggregated")
        self.assertEqual(rep["catalog_content_sha256"], cr.content_sha256(tc.catalog_path(self.var)))

    def test_zip_with_inner_tar_gz(self):
        rep = self.build("Synthetic_expert.zip")
        self.assertTrue(rep["ok"], rep.get("error"))
        self.assertEqual(rep["inner_archive"], "Synthetic_expert.tar.gz")
        self.assertEqual(rep["release_sha256"], self.exp["release_sha256"])
        self.assertNotEqual(rep["release_file_sha256"], rep["release_sha256"])
        self.assertFalse(rep["enabled"])                             # без --enable не включается

    def test_reproducible_content(self):
        a = self.build()["catalog_content_sha256"]
        b = self.build()["catalog_content_sha256"]
        self.assertEqual(a, b)

    def test_failures_leave_previous_catalog(self):
        self.assertTrue(self.build(enable=True)["ok"])
        before = cr.sha256_file(tc.catalog_path(self.var))
        for change in ({"candidate_sha256": "0" * 64}, {"release_sha256": "0" * 64}, {"sqlite_sha256": "0" * 64},
                       {"records": 60011}, {"aggregated_records": 8026}):
            with self.subTest(change):
                rep = self.build(expected={**self.exp, **change})
                self.assertFalse(rep["ok"])
                self.assertTrue(rep["error"])
                self.assertEqual(cr.sha256_file(tc.catalog_path(self.var)), before)
                self.assertTrue(tc.is_enabled(self.var))
                self.assertEqual(self.leftovers(), [])

    def test_rar_refused(self):
        rar = self.d / "in" / "x.tar.part1.rar"
        rar.write_bytes(b"Rar!")
        rep = cr.build_release(rar, self.d / "in" / "Synthetic_candidate.db", self.var, AUDIT, expected=self.exp)
        self.assertFalse(rep["ok"])
        self.assertIn("RAR", rep["error"])

    def test_cli_exit_codes(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import build_test_catalog as cli
        args = ["build-release", "--release", str(self.d / "in" / "Synthetic_expert.tar.gz"),
                "--candidate", str(self.d / "in" / "Synthetic_candidate.db"), "--var-dir", str(self.var), "--enable"]
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()):
            self.assertEqual(cli.main(args), 1)                         # настоящие SHA-256 не совпадут
            self.assertFalse(tc.catalog_path(self.var).exists())
            self.assertEqual(cli.main(args + ["--expected-file", str(self.d / "in" / "expected.json")]), 0)
        self.assertTrue(tc.is_enabled(self.var))


class TestUi(Base):
    def test_enable_restart_disable(self):
        self.assertTrue(self.build()["ok"])
        res = cr.verify_ui(self.var, ROOT, sys.executable)
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["final_enabled"])
        self.assertTrue(res["runs"]["restarted"]["aggregated"]["aggregate_with_n"])
        import os
        cwd = os.getcwd()
        os.chdir(self.d)
        try:                                                         # относительный путь к данным
            res = cr.verify_ui(Path("var"), ROOT, sys.executable, leave_enabled=False)
        finally:
            os.chdir(cwd)
        self.assertTrue(res["ok"])
        self.assertFalse(tc.is_enabled(self.var))


class TestPowerShellScript(unittest.TestCase):
    def test_constants_and_encoding(self):
        raw = (ROOT / "tools" / "Build-TestCatalog.ps1").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                 # UTF-8 BOM для Windows PowerShell 5.1
        text = raw.decode("utf-8")
        for key in ("release_sha256", "candidate_sha256"):
            m = re.search(rf'{key}\s*=\s*"([0-9a-f]{{64}})"', text)
            self.assertEqual(m.group(1), cr.EXPECTED[key], key)
        self.assertEqual((cr.EXPECTED["records"], cr.EXPECTED["individual_records"], cr.EXPECTED["aggregated_records"]),
                         (60011, 51985, 8026))


if __name__ == "__main__":
    unittest.main()
