import hashlib
import io
import json
import sqlite3
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import audit_archive  # noqa: E402


def make_archive(d: Path, *, tamper=False, evil=False) -> tuple[Path, str]:
    """Синтетический .tar.gz внутри .zip: manifest.json, база SQLite, файл кода."""
    db = d / "src.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE samples(id TEXT, source TEXT, markers TEXT)")
    c.execute("INSERT INTO samples VALUES ('1','S','{}')")
    c.commit()
    c.close()
    files = {"app/reference/scientific.sqlite": db.read_bytes(), "app/server.js": b"console.log(1)\n"}
    manifest = {"files": [{"path": p.removeprefix("app/"), "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
                          for p, b in files.items()]}
    if tamper:
        files["app/server.js"] = b"changed\n"
    files["app/manifest.json"] = json.dumps(manifest).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p, b in files.items():
            ti = tarfile.TarInfo(p)
            ti.size = len(b)
            t.addfile(ti, io.BytesIO(b))
        if evil:
            ti = tarfile.TarInfo("../escape.txt")
            ti.size = 1
            t.addfile(ti, io.BytesIO(b"x"))
    tgz = buf.getvalue()
    z = d / "a.tar.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.tar.gz", tgz)
    return z, hashlib.sha256(tgz).hexdigest()


class TestAuditArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_inner_sha_manifest_and_sqlite(self):
        z, sha = make_archive(self.d)
        before = audit_archive.sha256_file(z)
        res = audit_archive.audit(z, self.d / "work", sha.upper())
        self.assertEqual(audit_archive.sha256_file(z), before)
        self.assertTrue(res["sha256_matches"])
        self.assertEqual(res["manifests"][0]["ok"], 2)
        self.assertEqual(res["manifests"][0]["mismatch"], [])
        db = next(x for x in res["sqlite"] if x["path"].endswith("scientific.sqlite"))
        self.assertEqual((db["integrity_check"], db["tables"]), ("ok", {"samples": 1}))

    def test_wrong_sha_and_tampered_file_reported(self):
        z, _ = make_archive(self.d, tamper=True)
        res = audit_archive.audit(z, self.d / "work", "0" * 64)
        self.assertFalse(res["sha256_matches"])
        self.assertEqual(res["manifests"][0]["mismatch"], ["server.js"])

    def test_unsafe_paths_not_extracted_and_workdir_must_be_empty(self):
        z, sha = make_archive(self.d, evil=True)
        res = audit_archive.audit(z, self.d / "work", sha)
        self.assertFalse((self.d / "escape.txt").exists())
        self.assertTrue(any(x.get("skipped") for x in res["files"]))
        with self.assertRaises(SystemExit):
            audit_archive.audit(z, self.d / "work", sha)


if __name__ == "__main__":
    unittest.main()


class TestRecordedArchiveAudit(unittest.TestCase):
    """Зафиксированные результаты аудита реального архива (docs/ARCHIVE_AUDIT.json)."""

    def test_recorded_results(self):
        d = json.loads((ROOT / "docs" / "ARCHIVE_AUDIT.json").read_text(encoding="utf-8"))
        self.assertEqual(d["archive"]["sha256"], "745ca9cdc715c73ff351adee554a7e6259d92d952cfdd0580ac0356cd624d9b5")
        self.assertTrue(d["sha256_matches"])
        self.assertEqual(d["file_count"], 46)
        m = d["manifests"][0]
        self.assertEqual((m["entries"], m["ok"], m["mismatch"], m["missing"]), (45, 45, [], []))
        sci = next(x for x in d["sqlite"] if x["path"].endswith("scientific.sqlite"))
        self.assertEqual((sci["integrity_check"], sci["tables"]["profiles"]), ("ok", 45389))
        self.assertTrue(all(x["integrity_check"] == "ok" for x in d["sqlite"]))
        self.assertFalse((ROOT / "data" / "MANIFEST.json").exists())  # снимок не выбран

    def test_preliminary_calibration_not_approved(self):
        rules = json.loads((ROOT / "data" / "transform_rules.json").read_text(encoding="utf-8"))["rules"]
        by_id = {r["rule_id"]: r for r in rules}
        for rid in ("T12-genopoisk-y37-gatah4", "T13-genopoisk-y50-offsets", "T15-scientific-other-scale"):
            self.assertEqual(by_id[rid]["calibration"], "preliminary")
            self.assertEqual(by_id[rid]["status"], "proposed")
            self.assertIn("server.js", by_id[rid]["basis"])
