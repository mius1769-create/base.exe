"""Жизненный цикл временных загрузок, checkpoint WAL и резервные копии.

Побайтовые проверки здесь касаются файлов приложения (база, WAL, временная
папка, копии в var/backups); это не доказательство стирания с носителя.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

from synthetic import new_user  # noqa: F401  (путь к nestor_app)

from nestor_app import db, staging
from nestor_app import profiles as pr
from nestor_app import user_import as ui
from nestor_app.config import Settings
from nestor_app.web import NestorApp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import backup_users  # noqa: E402

Y12 = ["DYS393", "DYS390", "DYS19", "DYS391", "DYS385", "DYS426", "DYS388", "DYS439", "DYS389I", "DYS392", "DYS389II"]
VALS = ["13", "24", "14", "11", "11-14", "12", "12", "12", "13", "13", "29"]
SECRET = "STAGED-ONLY-K7X2"


def csv_bytes(*rows):
    return ("Kit;" + ";".join(Y12) + "\n" + "".join(f"{rid};" + ";".join(VALS) + "\n" for rid in rows)).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name)
        self.stg = self.var / "staging"
        self.db_path = self.var / "nestor_users.db"
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.uid = new_user(self.conn, 1)


class TestStagingLifecycle(Base):
    def test_ttl_expiry_on_access_and_sweep(self):
        upload, _ = ui.stage(self.conn, self.stg, self.uid, "k.csv", csv_bytes(SECRET))
        meta = self.stg / f"{upload}.json"
        d = json.loads(meta.read_text(encoding="utf-8"))
        d["created_at"] -= staging.TTL_SECONDS + 1
        meta.write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaises(ui.UploadError):                       # просрочена → удаляется при обращении
            ui.preview_of(self.conn, self.stg, self.uid, upload)
        self.assertEqual(list(self.stg.iterdir()), [])

    def test_sweep_removes_expired_without_access(self):
        st = staging.put(self.stg, self.uid, "k.csv", b"x", "AUTO")
        stats = staging.sweep(self.stg, now=time.time() + staging.TTL_SECONDS + 1)
        self.assertEqual(stats["expired"], 1)
        self.assertFalse((self.stg / f"{st.upload_id}.bin").exists())

    def test_crash_leftovers_are_removed(self):
        self.stg.mkdir()
        good = staging.put(self.stg, 2, "ok.csv", b"ok", "AUTO")
        (self.stg / ("a" * 32 + ".bin")).write_bytes(b"content without metadata")      # сбой до записи .json
        (self.stg / ("b" * 32 + ".json")).write_text('{"broken": ', encoding="utf-8")  # .json без .bin, битый
        (self.stg / ("c" * 32 + ".bin.tmp")).write_bytes(b"half")                      # сбой во время записи
        stats = staging.sweep(self.stg)
        self.assertEqual((stats["orphaned"], stats["partial"]), (2, 1))
        self.assertEqual(sorted(p.name for p in self.stg.iterdir()),
                         sorted([f"{good.upload_id}.bin", f"{good.upload_id}.json"]))  # свежая загрузка цела

    def test_app_startup_and_timer_clean_without_manual_action(self):
        staging.put(self.stg, self.uid, "old.csv", SECRET.encode(), "AUTO")
        for meta in self.stg.glob("*.json"):
            d = json.loads(meta.read_text(encoding="utf-8"))
            d["created_at"] -= staging.TTL_SECONDS + 1
            meta.write_text(json.dumps(d), encoding="utf-8")
        (self.stg / ("d" * 32 + ".bin")).write_bytes(b"orphan")
        self.conn.close()
        settings = Settings(var_dir=self.var, users_db=self.db_path, secret_file=self.var / "s.key",
                            manifest_file=self.var / "M.json", port=0, staging_dir=self.stg)
        app = NestorApp(settings)                                     # очистка при запуске
        self.addCleanup(app.conn.close)
        self.assertEqual(list(self.stg.iterdir()), [])
        self.assertEqual((app.last_maintenance["expired"], app.last_maintenance["orphaned"]), (1, 1))
        staging.put(self.stg, self.uid, "x.csv", b"x", "AUTO")
        for meta in self.stg.glob("*.json"):
            d = json.loads(meta.read_text(encoding="utf-8"))
            d["created_at"] -= staging.TTL_SECONDS + 1
            meta.write_text(json.dumps(d), encoding="utf-8")
        app.start_maintenance_timer(interval=0.05)                    # периодическая очистка
        self.addCleanup(app.stop_maintenance_timer)
        deadline = time.time() + 5
        while any(self.stg.iterdir()) and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(list(self.stg.iterdir()), [])


class TestBackupRetentionInApp(Base):
    def test_app_maintenance_prunes_old_backups(self):
        old = backup_users.make_backup(self.db_path, self.var / "backups", now=time.time() - 30 * 86400)
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        fresh = backup_users.make_backup(self.db_path, self.var / "backups")
        self.conn.close()
        settings = Settings(var_dir=self.var, users_db=self.db_path, secret_file=self.var / "s.key",
                            manifest_file=self.var / "M.json", port=0, staging_dir=self.stg)
        app = NestorApp(settings)                                     # очистка при запуске приложения
        self.addCleanup(app.conn.close)
        self.assertEqual(app.last_maintenance["backups_pruned"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_prune_only_cli(self):
        old = backup_users.make_backup(self.db_path, self.var / "backups", now=time.time() - 30 * 86400)
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        self.assertEqual(backup_users.main(["--var-dir", str(self.var), "--prune-only", "--keep-days", "14"]), 0)
        self.assertEqual(list((self.var / "backups").iterdir()), [])     # новая копия не создавалась


class TestCheckpointResult(Base):
    def test_incomplete_checkpoint_is_reported(self):
        upload, _ = ui.stage(self.conn, self.stg, self.uid, "k.csv", csv_bytes("A1"))
        reader = sqlite3.connect(self.db_path)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM users").fetchone()        # открытый читатель держит снимок WAL
        res = ui.commit(self.conn, self.stg, self.uid, upload, [("CSV", 2)], consent_basis="own_test",
                        consent_confirmed=True)
        self.assertEqual(res.checkpoint.status, "incomplete")          # не сообщаем, что WAL очищен
        self.assertFalse(res.checkpoint.complete)
        reader.rollback()
        self.assertEqual(db.checkpoint_truncate(self.conn).status, "complete")  # повтор после освобождения

    def test_not_wal_database(self):
        mem = db.connect(":memory:")
        self.addCleanup(mem.close)
        self.assertEqual(db.checkpoint_truncate(mem).status, "not_wal")


class TestBackups(Base):
    def backup_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def test_unfinished_upload_not_in_backup(self):
        ui.stage(self.conn, self.stg, self.uid, "k.csv", csv_bytes(SECRET))
        self.assertTrue(any(SECRET.encode() in f.read_bytes() for f in self.stg.iterdir()))
        copy = backup_users.make_backup(self.db_path, self.var / "backups")
        self.assertNotIn(SECRET.encode(), self.backup_bytes(copy))
        c = sqlite3.connect(copy)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 0)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        c.close()

    def test_kept_original_in_backup_until_retention(self):
        upload, _ = ui.stage(self.conn, self.stg, self.uid, "k.csv", csv_bytes("A1", SECRET))
        res = ui.commit(self.conn, self.stg, self.uid, upload, [("CSV", 2)], consent_basis="own_test",
                        consent_confirmed=True, keep_original=True)
        old = backup_users.make_backup(self.db_path, self.var / "backups", now=time.time() - 30 * 86400)
        self.assertIn(SECRET.encode(), self.backup_bytes(old))        # по согласию оригинал попадает в копию
        pr.delete_profile(self.conn, self.uid, res.profile_ids[0])     # из активной базы удалён
        new = backup_users.make_backup(self.db_path, self.var / "backups")
        self.assertNotIn(SECRET.encode(), self.backup_bytes(new))
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        removed = backup_users.prune(self.var / "backups", keep_days=14)
        self.assertEqual(removed, [old])                               # старая копия удалена по сроку
        self.assertTrue(new.exists())

    def test_backup_excludes_staging_and_secret(self):
        ui.stage(self.conn, self.stg, self.uid, "k.csv", csv_bytes(SECRET))
        self.assertEqual(backup_users.main(["--var-dir", str(self.var)]), 0)
        copies = list((self.var / "backups").glob("nestor_users-*.db"))
        self.assertEqual(len(copies), 1)
        self.assertEqual([p.name for p in (self.var / "backups").iterdir()], [copies[0].name])


if __name__ == "__main__":
    unittest.main()
