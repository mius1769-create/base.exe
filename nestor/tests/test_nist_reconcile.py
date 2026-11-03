import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import nist_reconcile  # noqa: E402
from inspect_reference import sha256_file  # noqa: E402
from test_inspect_reference import make_db  # noqa: E402
from xlsx_read import read_sheet, sheet_names  # noqa: E402


def col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path: Path, rows: list[list], sheet="Table S4"):
    """Минимальный синтетический .xlsx (inline-строки и числа)."""
    xml_rows = []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{col(ci)}{ri}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            elif v != "":
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
        xml_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{m}" xmlns:r="{r}"><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{m}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')


class TestXlsxRead(unittest.TestCase):
    def test_reads_values_as_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.xlsx"
            write_xlsx(p, [["Title row"], ["Sample", "DYS19"], ["A1", 14], ["A2", "del"]])
            self.assertEqual(sheet_names(p), ["Table S4"])
            rows = read_sheet(p)
            self.assertEqual(rows[2], ["A1", "14"])
            self.assertEqual(rows[3], ["A2", "del"])


class TestNistReconcile(unittest.TestCase):
    """Синтетические файлы: кандидат, Table S4 и PDR с колонкой групп."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.cand = d / "cand.db"
        make_db(self.cand, [
            ("NIST1032|S1", "NIST", {"DYS19": [14], "DYS385": [11, 14], "Y GATA H4": [12]}),
            ("NIST1032|S2", "NIST", {"DYS19": [15], "DYS385": [12, 13]}),          # del в S4 → пусто в кандидате
            ("NIST1032|S3", "NIST", {"DYS19": [16], "DYS385": [13, 13], "Y GATA H4": [11]}),
            ("NIST1032|S9", "NIST", {"DYS19": [13]}),                              # нет в S4
            ("x", "Other", {"DYS19": [1]}),
        ], [("NIST", "t", 4), ("Other", "t", 1)])
        self.s4 = d / "s4.xlsx"
        write_xlsx(self.s4, [["Table S4. Allele calls"],
                             ["Sample ID", "DYS19", "DYS385", "Y-GATA-H4"],
                             ["S1", 14, "11,14", 12],
                             ["S2", 15, "12,13", "del"],
                             ["S3", 17, "13,13", 11],      # расхождение с кандидатом
                             ["S4", 14, "11,14", 12]])     # нет в кандидате
        self.pdr = d / "pdr.xlsx"
        write_xlsx(self.pdr, [["Sample ID", "Population", "DYS19", "DYS385", "Y-GATA-H4"],
                              ["S1", "African American", 14, "11,14", 12],
                              ["S2", "Caucasian", 15, "12,13", "del"],
                              ["S3", "Hispanic", 17, "13,13", 11],
                              ["S4", "Asian", 14, "11,14", 12]], sheet="Y-STR")

    def test_reconcile_and_group_labels(self):
        before = sha256_file(self.cand)
        summary, labels = nist_reconcile.reconcile(self.cand, self.s4, self.pdr, "Sample ID", "Population")
        self.assertEqual(sha256_file(self.cand), before)
        self.assertEqual(summary["counts"], {"candidate": 4, "table_s4": 4, "pdr": 4})
        self.assertEqual(summary["ids"]["only_candidate"], ["S9"])
        self.assertEqual(summary["ids"]["only_table_s4"], ["S4"])
        diffs = summary["candidate_vs_s4"]["differences_by_locus"]
        self.assertEqual(diffs, {"DYS19": 1})  # del в S4 ≠ расхождение значения
        self.assertEqual(summary["candidate_vs_s4"]["del_in_s4_absent_in_candidate"], {"Y-GATA-H4": 1})
        self.assertEqual(summary["s4_vs_pdr"]["differences_by_locus"], {})
        # метки — из PDR как записаны, с происхождением, только для записей кандидата
        self.assertEqual(summary["groups"]["origin"], "pdr")
        self.assertEqual(summary["groups"]["counts"], {"African American": 1, "Caucasian": 1, "Hispanic": 1})
        self.assertEqual(summary["groups"]["unlabeled_candidate_records"], 1)
        l1 = next(x for x in labels if x["record_key"] == "NIST1032|S1")
        self.assertEqual(l1["origin_sha256"], sha256_file(self.pdr))
        self.assertIn("row", l1["origin_locator"])

    def test_no_group_column_means_no_labels(self):
        summary, labels = nist_reconcile.reconcile(self.cand, self.s4, None, "Sample ID", "Population")
        self.assertEqual(labels, [])
        self.assertIsNone(summary["groups"]["origin"])

    def test_cli_writes_separate_files(self):
        d = Path(self.tmp.name)
        nist_reconcile.main(["--candidate", str(self.cand), "--table-s4", str(self.s4), "--pdr", str(self.pdr),
                             "--pdr-sheet", "Y-STR", "--id-col", "Sample ID", "--group-col", "Population",
                             "--summary", str(d / "sum.json"), "--groups", str(d / "var" / "g.csv")])
        self.assertEqual(json.loads((d / "sum.json").read_text(encoding="utf-8"))["counts"]["pdr"], 4)
        self.assertIn("African American", (d / "var" / "g.csv").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()


class TestSourceCodes(unittest.TestCase):
    def test_split_codes_for_comparison_only(self):
        self.assertEqual(nist_reconcile.split_codes("23*"), ("23", ["*"]))
        self.assertEqual(nist_reconcile.split_codes("16**"), ("16", ["**"]))
        self.assertEqual(nist_reconcile.split_codes("del"), ("", ["del"]))
        self.assertEqual(nist_reconcile.split_codes("DEL"), ("", ["del"]))
        self.assertEqual(nist_reconcile.split_codes("12"), ("12", []))
        self.assertEqual(nist_reconcile.split_codes("11,14"), ("11,14", []))
        self.assertEqual(nist_reconcile.split_codes("n/a"), ("", ["?n/a"]))

    def test_raw_record_keeps_codes_verbatim(self):
        rec = {"Sample ID": "S1", "DYS481": "23*", "DYS456": "16**", "DYS19": "del", "DYS390": ""}
        cols = {"DYS481": "DYS481", "DYS456": "DYS456", "DYS19": "DYS19", "DYS390": "DYS390"}
        self.assertEqual(nist_reconcile.raw_record_from_row(rec, cols),
                         {"DYS481": "23*", "DYS456": "16**", "DYS19": "del"})

    def test_codes_reported_and_del_explained(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cand = d / "c.db"
            make_db(cand, [("NIST1032|A", "NIST", {"DYS481": [23], "DYS456": [16]}),
                           ("NIST1032|B", "NIST", {"DYS481": [22]})], [("NIST", "t", 2)])
            s4 = d / "s4.xlsx"
            write_xlsx(s4, [["Sample ID", "Group", "DYS481", "DYS456"],
                            ["A", "Asian", "23*", "16**"],
                            ["B", "Hispanic", 22, "del"]])
            before = sha256_file(s4)
            summary, labels = nist_reconcile.reconcile(cand, s4, None, "Sample ID", "Group",
                                                       expected_groups={"Asian": 1, "Hispanic": 1})
            self.assertEqual(sha256_file(s4), before)
            self.assertEqual(summary["candidate_vs_s4"]["differences_by_locus"], {})
            codes = {(x["code"], x["locus"]): x["count"] for x in summary["source_codes_in_s4"]}
            self.assertEqual(codes, {("*", "DYS481"): 1, ("**", "DYS456"): 1, ("del", "DYS456"): 1})
            self.assertEqual(summary["candidate_vs_s4"]["del_in_s4_absent_in_candidate"], {"DYS456": 1})
            self.assertTrue(summary["groups"]["primary_table_matches_article"])
            self.assertTrue(summary["groups"]["candidate_labels_match_article"])

    def test_group_mismatch_is_reported_not_forced(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cand = d / "c.db"
            make_db(cand, [("NIST1032|A", "NIST", {"DYS19": [14]})], [("NIST", "t", 1)])
            s4 = d / "s4.xlsx"
            write_xlsx(s4, [["Sample ID", "Group", "DYS19"], ["A", "Asian", 14], ["Z", "Asian", 15]])
            summary, labels = nist_reconcile.reconcile(cand, s4, None, "Sample ID", "Group",
                                                       expected_groups={"Asian": 1})
            self.assertFalse(summary["groups"]["primary_table_matches_article"])
            self.assertEqual([x["record_key"] for x in labels], ["NIST1032|A"])  # только сопоставленные по ID
