import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from synthetic import BASE_Y37, new_conn, new_user  # noqa: F401  (путь к nestor_app)
from xlsx_fixture import write_workbook

from nestor_app import candidates
from nestor_app import importer as im
from nestor_app import markers as mk
from nestor_app import panels
from nestor_app import profiles as pr
from nestor_app import search
from nestor_app import user_import as ui

FIX = Path(__file__).resolve().parent / "fixtures" / "archive_examples"
Y12 = list(panels.PANELS["FTDNA_Y12"].marker_names)
Y12_VALUES = ["13", "24", "14", "11", "11-14", "12", "12", "12", "13", "13", "29"]


def y12_row(**over):
    vals = dict(zip(Y12, Y12_VALUES))
    vals.update(over)
    return [vals[k] for k in Y12]


class TestCsv(unittest.TestCase):
    def test_archive_control_csv_preserves_raw_cells(self):
        data = (FIX / "FTDNA-Y37.csv").read_bytes()
        prev = im.build_preview("FTDNA-Y37.csv", data)
        [sheet] = prev.sheets
        self.assertEqual((sheet.name, sheet.panel_code, sheet.panel_basis, sheet.header_row), ("CSV", "FTDNA_Y37", "recognized", 1))
        [rec] = prev.records
        header, values = data.decode("utf-8-sig").splitlines()[:2]
        self.assertEqual(rec.raw, dict(zip(header.split(";"), values.split(";"))))   # дословно
        self.assertEqual((rec.row_number, rec.observed, rec.missing, rec.invalid), (2, 30, [], {}))
        self.assertEqual(len(prev.sha256), 64)

    def test_empty_cells_and_unrecognized(self):
        text = "Kit;" + ";".join(Y12) + "\n" + "K1;" + ";".join(y12_row(DYS19="", DYS390="24?")) + "\n"
        prev = im.build_preview("p.csv", text.encode(), "FTDNA_Y12")
        [rec] = prev.records
        self.assertEqual((rec.record_id, rec.missing, rec.invalid), ("K1", ["DYS19"], {"DYS390": "24?"}))
        self.assertIsNone(rec.positions["DYS19"])
        self.assertEqual(rec.raw["DYS390"], "24?")

    def test_cp1251_and_comma_delimiter(self):
        text = "Образец," + ",".join(Y12) + "\n" + "Иванов," + ",".join(v.replace("-", "-") for v in y12_row()) + "\n"
        prev = im.build_preview("p.csv", text.encode("cp1251"))
        self.assertEqual(prev.records[0].record_id, "Иванов")
        self.assertEqual(prev.sheets[0].panel_code, "FTDNA_Y12")

    def test_wrong_panel(self):
        data = (FIX / "FTDNA-Y37.csv").read_bytes()
        with self.assertRaises(im.ImportError_) as ctx:
            im.build_preview("FTDNA-Y37.csv", data, "FTDNA_Y12")
        self.assertIn("ошибочная панель", str(ctx.exception))
        with self.assertRaises(im.ImportError_):
            im.build_preview("FTDNA-Y37.csv", data, "Y700")

    def test_database_files_refused(self):
        for name in ("Nestor_scientific_YSTR.db", "scientific.sqlite"):
            with self.assertRaises(im.ImportError_):
                im.build_preview(name, b"SQLite format 3\x00")


class TestXlsx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def book(self, sheets):
        return write_workbook(Path(self.tmp.name) / "b.xlsx", sheets)

    def test_multiple_sheets_repeats_and_empty_rows(self):
        data = self.book({
            "Профили": [["Таблица 1. Синтетические профили"], ["Sample"] + Y12,
                        ["A1"] + y12_row(), ["A2"] + y12_row(DYS19="15"), [""] * 3, ["A1"] + y12_row(DYS391="")],
            "Ещё": [["Sample"] + Y12, ["B1"] + y12_row()],                 # тот же гаплотип, что A1
            "Заметки": [["Комментарий"], ["здесь нет профилей"]],
        })
        prev = im.build_preview("b.xlsx", data)
        names = [s.name for s in prev.sheets]
        self.assertEqual(names, ["Профили", "Ещё", "Заметки"])
        p1, p2, notes = prev.sheets
        self.assertEqual((p1.header_row, len(p1.records), p1.panel_code), (2, 3, "FTDNA_Y12"))
        self.assertIn("не найдена строка заголовков", notes.error)
        a1, a2, a1b = p1.records
        self.assertEqual([a1.row_number, a2.row_number, a1b.row_number], [3, 4, 6])
        self.assertTrue(any("повтор значений" in f and "Ещё:2" in f for f in a1.flags))
        self.assertTrue(any("повтор ID «A1»" in f for f in a1b.flags))
        self.assertEqual(a1b.missing, ["DYS391"])
        self.assertEqual(a2.flags, [])
        self.assertEqual(prev.summary()["records"], 4)

    def test_binary_float_cell_preserved(self):
        loci = list(panels.PANELS["GENOPOISK_Y37"].marker_names)
        row = ["13"] * len(loci)
        row[loci.index("DYS518")] = ("num", "33.200000000000003")
        row[loci.index("DYS385")] = "11-14"
        data = self.book({"S": [loci, row]})
        [rec] = im.build_preview("g.xlsx", data).records
        self.assertEqual(rec.raw["DYS518"], "33.200000000000003")     # исходная строка ячейки
        self.assertEqual(rec.positions["DYS518"], (33.2,))            # то же число, без округления


class TestUserImport(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        self.uid = new_user(self.conn, 1)
        self.csv = ("Kit;" + ";".join(Y12) + "\n" + "K1;" + ";".join(y12_row()) + "\n"
                    + "K2;" + ";".join(y12_row(DYS19="")) + "\n" + "K1;" + ";".join(y12_row()) + "\n").encode()

    def test_stage_preview_commit_selected_rows(self):
        upload_id, prev = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        self.assertEqual(len(prev.records), 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)  # до подтверждения ничего
        f = self.conn.execute("SELECT * FROM import_files WHERE id=?", (upload_id,)).fetchone()
        self.assertEqual((f["status"], bytes(f["content"])), ("staged", self.csv))
        ids = ui.commit(self.conn, self.uid, upload_id, [("CSV", 2), ("CSV", 3)],
                        consent_basis="own_test", consent_confirmed=True)
        self.assertEqual(len(ids), 2)
        p = pr.get_owned(self.conn, self.uid, ids[1])
        self.assertFalse(p.searchable)                                      # закрыт по умолчанию
        self.assertEqual((p.panel_code, p.panel_basis, p.kit_id_private), ("FTDNA_Y12", "recognized", "K2"))
        self.assertIsNone(p.markers["DYS19"])
        src = pr.load_source(self.conn, ids[1])
        self.assertEqual((src["sheet"], src["row_number"], src["file_sha256"]), ("CSV", 3, prev.sha256))
        self.assertEqual(json.loads(src["raw_json"])["DYS19"], "")
        with self.assertRaises(ui.UploadError):                             # повторное сохранение того же файла
            ui.commit(self.conn, self.uid, upload_id, [("CSV", 4)], consent_basis="own_test", consent_confirmed=True)

    def test_consent_required_before_any_write(self):
        upload_id, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        with self.assertRaises(ui.UploadError):
            ui.commit(self.conn, self.uid, upload_id, [("CSV", 2)], consent_basis="own_test", consent_confirmed=False)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)

    def test_second_upload_flags_existing_and_does_not_merge(self):
        u1, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        ui.commit(self.conn, self.uid, u1, [("CSV", 2)], consent_basis="own_test", consent_confirmed=True)
        u2, prev = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        k1 = prev.records[0]
        self.assertTrue(any("те же значения, что у сохранённой записи" in f for f in k1.flags))
        self.assertTrue(any("ID «K1» уже есть" in f for f in k1.flags))
        ui.commit(self.conn, self.uid, u2, [("CSV", 2)], consent_basis="own_test", consent_confirmed=True)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 2)  # не объединены

    def test_default_commit_deletes_full_file(self):
        u1, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        [pid] = ui.commit(self.conn, self.uid, u1, [("CSV", 2)], consent_basis="own_test", consent_confirmed=True)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 0)
        src = pr.load_source(self.conn, pid)
        self.assertIsNone(src["import_file_id"])
        self.assertEqual((src["filename"], src["sheet"], src["row_number"]), ("kits.csv", "CSV", 2))
        self.assertEqual(src["file_sha256"], im.build_preview("kits.csv", self.csv).sha256)  # SHA-256 всего файла

    def test_discard_and_keep_original_lifecycle(self):
        u1, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        ui.discard(self.conn, self.uid, u1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 0)
        u2, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        a, b = ui.commit(self.conn, self.uid, u2, [("CSV", 2), ("CSV", 3)], consent_basis="own_test",
                         consent_confirmed=True, keep_original=True)
        f = self.conn.execute("SELECT keep_original, keep_original_at, content FROM import_files").fetchone()
        self.assertEqual((f["keep_original"], bytes(f["content"])), (1, self.csv))
        self.assertIsNotNone(f["keep_original_at"])
        pr.delete_profile(self.conn, self.uid, a)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 1)  # нужен профилю b
        pr.delete_profile(self.conn, self.uid, b)                          # последняя выбранная запись
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM profile_sources").fetchone()[0], 0)

    def test_new_upload_replaces_unfinished_one(self):
        u1, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        u2, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        ids = [r[0] for r in self.conn.execute("SELECT id FROM import_files")]
        self.assertEqual(ids, [u2])

    def test_other_user_cannot_see_upload(self):
        u1, _ = ui.stage(self.conn, self.uid, "kits.csv", self.csv)
        stranger = new_user(self.conn, 2)
        with self.assertRaises(ui.UploadError):
            ui.preview_of(self.conn, stranger, u1)


class TestUnselectedProfileNotStored(unittest.TestCase):
    """Книга с двумя персональными профилями; пользователь сохраняет один."""

    SECRET_B = "PERSON-B-ZX9Q"
    NOTE_B = "Петров-Пётр-отец-1931"

    def setUp(self):
        from nestor_app import db
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "users.db"
        self.conn = db.connect(self.path)
        self.addCleanup(self.conn.close)
        self.uid = new_user(self.conn, 1)
        self.book = write_workbook(Path(self.tmp.name) / "family.xlsx", {
            "Семья": [["Sample", "Заметка"] + Y12,
                      ["PERSON-A-7Q1", "мой тест"] + y12_row(),
                      [self.SECRET_B, self.NOTE_B] + y12_row(DYS19="16", DYS390="23")]})

    def db_bytes(self) -> bytes:
        out = b""
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(self.path) + suffix)
            if f.exists():
                out += f.read_bytes()
        return out

    def assert_b_absent(self):
        blob = self.db_bytes()
        for text in (self.SECRET_B, self.NOTE_B):
            self.assertNotIn(text.encode("utf-8"), blob, text)
        self.assertNotIn(self.book, blob)

    def test_only_selected_row_kept(self):
        upload, prev = ui.stage(self.conn, self.uid, "family.xlsx", self.book)
        self.assertEqual(len(prev.records), 2)
        self.assertIn(self.SECRET_B.encode(), self.db_bytes())             # временно — пока ждёт решения
        [pid] = ui.commit(self.conn, self.uid, upload, [("Семья", 2)], consent_basis="own_test", consent_confirmed=True)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_files").fetchone()[0], 0)
        src = pr.load_source(self.conn, pid)
        self.assertEqual(json.loads(src["raw_json"])["Sample"], "PERSON-A-7Q1")
        self.assertEqual(src["file_sha256"], prev.sha256)
        self.assert_b_absent()

    def test_cancel_removes_temporary_file(self):
        upload, _ = ui.stage(self.conn, self.uid, "family.xlsx", self.book)
        ui.discard(self.conn, self.uid, upload)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)
        self.assert_b_absent()

    def test_reimport_after_commit_and_delete_last(self):
        u1, _ = ui.stage(self.conn, self.uid, "family.xlsx", self.book)
        [pid] = ui.commit(self.conn, self.uid, u1, [("Семья", 2)], consent_basis="own_test", consent_confirmed=True)
        u2, prev = ui.stage(self.conn, self.uid, "family.xlsx", self.book)   # повторный импорт того же файла
        a, b = prev.records
        self.assertTrue(any("ID «PERSON-A-7Q1» уже есть" in f for f in a.flags))
        self.assertFalse(any("уже есть" in f for f in b.flags))
        ui.discard(self.conn, self.uid, u2)
        self.assert_b_absent()
        pr.delete_profile(self.conn, self.uid, pid)                          # последняя выбранная запись
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM profile_sources").fetchone()[0], 0)
        self.assertNotIn(b"PERSON-A-7Q1", self.db_bytes())

    def test_keep_original_requires_explicit_consent(self):
        u1, _ = ui.stage(self.conn, self.uid, "family.xlsx", self.book)
        ui.commit(self.conn, self.uid, u1, [("Семья", 2)], consent_basis="own_test", consent_confirmed=True,
                  keep_original=True)
        self.assertIn(self.SECRET_B.encode(), self.db_bytes())             # по согласию — полный файл со строкой B


class TestCandidates(unittest.TestCase):
    SOURCE = {"source_id": "synthetic_controls", "title": "Синтетические контрольные строки",
              "publication": "нет (синтетика)", "source_url": "tests/fixtures", "license": "синтетика",
              "permission_status": "не проверено"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "cand.db"
        self.conn = candidates.connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.data = (FIX / "Genopoisk-Y50.csv").read_bytes()

    def test_preview_writes_nothing_commit_writes_separately(self):
        prev = candidates.preview(self.conn, "Genopoisk-Y50.csv", self.data)
        self.assertEqual(prev.sheets[0].panel_code, "GENOPOISK_Y50")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cand_records").fetchone()[0], 0)
        n = candidates.commit(self.conn, "Genopoisk-Y50.csv", self.data, source=self.SOURCE)
        self.assertEqual(n, 1)
        src = self.conn.execute("SELECT * FROM cand_sources").fetchone()
        self.assertEqual((src["permission_status"], src["decision"]), ("не проверено", candidates.DECISION))
        rec = self.conn.execute("SELECT * FROM cand_records").fetchone()
        self.assertEqual(rec["row_number"], 2)
        self.assertEqual(json.loads(rec["raw_json"])["DYS389II"], "26")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE cand_records SET raw_json='{}'")

    def test_reimport_and_missing_metadata_rejected(self):
        candidates.commit(self.conn, "Genopoisk-Y50.csv", self.data, source=self.SOURCE)
        with self.assertRaises(candidates.CandidateError):
            candidates.commit(self.conn, "copy.csv", self.data, source=self.SOURCE)
        with self.assertRaises(candidates.CandidateError):
            candidates.commit(self.conn, "other.csv", (FIX / "FTDNA-Y37.csv").read_bytes(),
                              source={**self.SOURCE, "license": ""})

    def test_candidates_never_reach_search(self):
        candidates.commit(self.conn, "Genopoisk-Y50.csv", self.data, source=self.SOURCE)
        users = new_conn()
        self.addCleanup(users.close)
        tables = {r[0] for r in users.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(any(t.startswith("cand_") for t in tables))       # другая база
        uid = new_user(users, 1)
        q = mk.parse_table_entries((FIX / "Genopoisk-Y50.csv").read_text(encoding="utf-8-sig"))
        pid = pr.create_profile(users, uid, q, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(users, uid, pid, True)
        self.assertEqual(search.owner_search(users, uid, pid, min_common=1), [])

    def test_cli_dry_run_then_commit(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import import_scientific
        csv_path = FIX / "FTDNA-Y37.csv"
        db = Path(self.tmp.name) / "cli.db"
        args = [str(csv_path), "--db", str(db), "--source-id", "s1", "--title", "t", "--publication", "p",
                "--url", "u", "--license", "l", "--permission-status", "не проверено"]
        self.assertEqual(import_scientific.main(args), 0)
        c = candidates.connect(db)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM cand_records").fetchone()[0], 0)
        c.close()
        self.assertEqual(import_scientific.main(args + ["--commit"]), 0)
        c = candidates.connect(db)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM cand_records").fetchone()[0], 1)
        c.close()
        self.assertEqual(import_scientific.main([str(db), "--db", str(Path(self.tmp.name) / "x.db"), "--source-id", "s",
                                                 "--title", "t", "--publication", "p", "--url", "u", "--license", "l",
                                                 "--permission-status", "не проверено"]), 2)  # .db отклонён


if __name__ == "__main__":
    unittest.main()
