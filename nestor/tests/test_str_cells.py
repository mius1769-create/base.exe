"""Ручной ввод по окошкам: те же правила панелей и копий, что у списка значений."""

import http.client
import re
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

from synthetic import BASE_Y37  # noqa: F401  (путь к nestor_app)

from nestor_app import accounts, panels
from nestor_app import markers as mk
from nestor_app import profiles as pr
from nestor_app.config import Settings
from nestor_app.web import SESSION_COOKIE, NestorApp


class Cells(unittest.TestCase):
    def test_cells_cover_every_panel_in_its_order(self):
        fields = {c["field"] for c in panels.input_cells()}
        for code, panel in panels.PANELS.items():
            order = panels.panel_orders()[code]
            self.assertEqual(len(order), panel.allele_count, code)
            self.assertLessEqual(set(order), fields, code)

    def test_y111_comes_first_and_copies_are_split(self):
        cells = panels.input_cells()
        self.assertEqual(cells[0]["label"], "DYS393")
        labels = [c["label"] for c in cells]
        self.assertIn("DYS385a", labels)
        self.assertIn("DYS464d", labels)
        self.assertEqual(labels[:len(panels.panel_orders()["FTDNA_Y111"])], [c["label"] for c in cells[:len(panels.panel_orders()["FTDNA_Y111"])]])
        self.assertEqual([c["field"] for c in cells][:111], panels.panel_orders()["FTDNA_Y111"][:111])

    def test_same_result_as_flat_list(self):
        panel = panels.PANELS["FTDNA_Y12"]
        order = panels.panel_orders()["FTDNA_Y12"]
        values = [str(10 + i) for i in range(len(order))]
        self.assertEqual(panels.markers_from_cells(dict(zip(order, values))),
                         panels.parse_flat_values(" ".join(values), panel.code))

    def test_empty_and_zero_are_not_entered(self):
        self.assertEqual(panels.markers_from_cells({"DYS19": "", "DYS393": "0", "DYS390": "24"}), {"DYS390": (24,)})

    def test_partial_copies_are_marked_not_invented(self):
        result = panels.markers_from_cells({"DYS385A": "11"})
        self.assertIsInstance(result["DYS385"], mk.Invalid)

    def test_garbage_is_marked_invalid(self):
        self.assertIsInstance(panels.markers_from_cells({"DYS19": "abc"})["DYS19"], mk.Invalid)


class CellForm(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        var = Path(tmp.name)
        self.app = NestorApp(Settings(var_dir=var, users_db=var / "u.db", secret_file=var / "s.key",
                                      manifest_file=var / "M.json", port=0, staging_dir=var / "staging"))
        self.addCleanup(self.app.conn.close)
        server = self.app.make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        self.uid = accounts.register(self.app.conn, "a@example.test", "password-a")
        self.token, self.csrf = accounts.create_session(self.app.conn, self.uid)

    def request(self, method, path, fields=None):
        headers = {"Host": f"127.0.0.1:{self.port}", "Cookie": f"{SESSION_COOKIE}={self.token}"}
        body = None
        if fields is not None:
            body = urllib.parse.urlencode({"csrf": self.csrf, **fields})
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        self.addCleanup(c.close)
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        return r.status, r.getheader("Location"), r.read().decode()

    def save(self, **fields):
        return self.request("POST", "/profiles/new", {"consent_basis": "own_test", "consent_confirmed": "1", "panel": "FTDNA_Y12", **fields})

    def test_page_has_a_cell_for_each_position_and_no_predict(self):
        page = self.request("GET", "/profiles/new")[2]
        self.assertEqual(len(re.findall(r'name="cell_', page)), len(panels.input_cells()))
        self.assertEqual(len(re.findall(r'name="gcell_', page)), len(panels.input_cells(panels.GENOPOISK_PANELS)))
        self.assertEqual(page.count('class="panel str-section"'), 2)
        self.assertEqual(page.count('class="str-load"'), 2)
        self.assertNotRegex(page.split("</style>", 1)[1].lower(), "predict|предикт")

    def test_saving_from_cells(self):
        status, location, _ = self.save(cell_DYS393="13", cell_DYS385A="11", cell_DYS385B="14", cell_DYS19="0")
        self.assertEqual(status, 303)
        pid = int(location.rsplit("/", 1)[1])
        p = pr.get_owned(self.app.conn, self.uid, pid)
        self.assertEqual((p.panel_code, p.markers["DYS393"], p.markers["DYS385"], p.markers["DYS19"]), ("FTDNA_Y12", (13,), (11, 14), None))

    def test_locus_outside_panel_keeps_entered_values(self):
        status, _, page = self.save(cell_DYS393="13", cell_DYS570="17", nickname="Ник")
        self.assertEqual(status, 400)
        self.assertIn('id="new-profile-error"', page)
        self.assertIn("DYS570", page)
        self.assertIn('name="cell_DYS393" data-field="DYS393" value="13"', page)
        self.assertIn('name="nickname" maxlength="200" value="Ник"', page)
        self.assertIn('value="own_test" required checked', page)
        self.assertEqual(pr.list_owned(self.app.conn, self.uid), [])

    def test_genopoisk_window_keeps_its_own_loci(self):
        status, location, _ = self.save(g_panel="GENOPOISK_Y50", gcell_DYS518="38", gcell_DYS627="20", **{"gcell_Y-GATA-H4": "12"})
        self.assertEqual(status, 303)
        p = pr.get_owned(self.app.conn, self.uid, int(location.rsplit("/", 1)[1]))
        self.assertEqual((p.panel_code, p.markers["DYS518"], p.markers["DYS627"], p.markers["Y-GATA-H4"]), ("GENOPOISK_Y50", (38,), (20,), (12,)))

    def test_both_windows_make_two_results_without_mixing_scales(self):
        status, location, _ = self.save(panel="FTDNA_Y37", g_panel="GENOPOISK_Y37", nickname="Ник", **{"cell_Y-GATA-H4": "11", "gcell_Y-GATA-H4": "12", "gcell_DYS518": "38"})
        self.assertEqual((status, location), (303, "/me"))
        ftdna, genopoisk = pr.list_owned(self.app.conn, self.uid)
        self.assertEqual((ftdna.panel_code, ftdna.markers["Y-GATA-H4"]), ("FTDNA_Y37", (11,)))
        self.assertEqual((genopoisk.panel_code, genopoisk.markers["Y-GATA-H4"], genopoisk.markers["DYS518"]), ("GENOPOISK_Y37", (12,), (38,)))
        self.assertNotIn("DYS518", ftdna.markers)
        self.assertEqual({ftdna.nickname, genopoisk.nickname}, {"Ник"})
        self.assertFalse(ftdna.searchable or genopoisk.searchable)

    def test_error_in_one_window_saves_nothing(self):
        status, _, page = self.save(panel="FTDNA_Y12", cell_DYS393="13", g_panel="GENOPOISK_Y37", gcell_DYS622="20")   # DYS622 — только в Y50
        self.assertEqual(status, 400)
        self.assertIn("DYS622", page)
        self.assertIn('name="cell_DYS393" data-field="DYS393" value="13"', page)
        self.assertEqual(pr.list_owned(self.app.conn, self.uid), [])

    def test_both_cells_and_text_are_refused(self):
        status, _, page = self.save(cell_DYS393="13", markers="DYS390=24")
        self.assertEqual(status, 400)
        self.assertIn("оставьте что-то одно", page)
        self.assertEqual(pr.list_owned(self.app.conn, self.uid), [])

    def test_nothing_entered_is_refused(self):
        self.assertEqual(self.save(markers="")[0], 400)

    def test_flat_list_works_without_scripts(self):
        values = " ".join(str(10 + i) for i in range(panels.PANELS["FTDNA_Y12"].allele_count))
        status, location, _ = self.save(markers=values)
        self.assertEqual(status, 303)
        p = pr.get_owned(self.app.conn, self.uid, int(location.rsplit("/", 1)[1]))
        self.assertEqual(p.panel_code, "FTDNA_Y12")

    def test_consent_is_still_required(self):
        status, _, _ = self.request("POST", "/profiles/new", {"cell_DYS393": "13", "panel": "FTDNA_Y12"})
        self.assertEqual(status, 400)
        self.assertEqual(pr.list_owned(self.app.conn, self.uid), [])

    def test_entered_values_are_escaped(self):
        _, _, page = self.save(cell_DYS393='"><script>x', cell_DYS570="17")
        self.assertNotIn('"><script>x', page)


if __name__ == "__main__":
    unittest.main()
