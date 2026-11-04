"""Проверка источника POST (loopback, тот же порт) и плоский список аллелей по выбранной панели."""

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from synthetic import BASE_Y37  # noqa: F401  (путь к nestor_app)

from nestor_app import markers as mk
from nestor_app import panels as pn
from nestor_app.config import Settings
from nestor_app.web import NestorApp, _loopback_netloc

Y111 = pn.PANELS["FTDNA_Y111"]


def flat_values(panel=Y111, zeros=()):
    vals = [str(10 + (i * 7) % 9) for i in range(panel.allele_count)]
    vals[:6] = ["14", "23", "14", "11", "11", "13"]
    vals[-3:] = ["8", "12", "11"]
    for i in zeros:
        vals[i] = "0"
    return vals


def slot_index(panel, locus):
    pos = 0
    for name, copies in panel.markers:
        if name == locus:
            return pos
        pos += copies
    raise KeyError(locus)


class TestLoopbackNetloc(unittest.TestCase):
    def test_rules(self):
        for ok in ("127.0.0.1:8765", "localhost:8765", "LOCALHOST:8765"):
            self.assertTrue(_loopback_netloc(ok, 8765), ok)
        for bad in (None, "", "127.0.0.1", "localhost:8766", "evil.example:8765", "127.0.0.2:8765",
                    "localhost.evil.example:8765", "user@localhost:8765", "[::1]:8765", "127.0.0.1:abc"):
            self.assertFalse(_loopback_netloc(bad, 8765), bad)


class TestFlatList(unittest.TestCase):
    def test_y111_by_order_and_slots(self):
        vals = flat_values()
        self.assertEqual(len(vals), 111)
        self.assertTrue(pn.looks_like_flat_list(" ".join(vals)))
        prof = pn.parse_flat_values(" ".join(vals), "FTDNA_Y111")
        positions, code, basis = pn.apply_panel(prof, "FTDNA_Y111")
        self.assertEqual((code, basis), ("FTDNA_Y111", "selected"))
        self.assertEqual(list(positions), list(Y111.marker_names))
        self.assertEqual(len(positions), 102)
        self.assertEqual(sum(len(v) for v in positions.values()), 111)
        # порядок FTDNA: DYS393 DYS390 DYS19 DYS391 DYS385(2) DYS426 …
        self.assertEqual(positions["DYS393"], (14.0,))
        self.assertEqual(positions["DYS390"], (23.0,))
        self.assertEqual(positions["DYS385"], (11.0, 13.0))
        i464 = slot_index(Y111, "DYS464")
        self.assertEqual(positions["DYS464"], tuple(sorted(float(v) for v in vals[i464:i464 + 4])))
        self.assertEqual(positions["DYS435"], (11.0,))                     # последний локус Y111
        self.assertEqual(positions["DYS461"], (12.0,))

    def test_zero_is_missing_and_partial_copies_invalid(self):
        i426 = slot_index(Y111, "DYS426")
        i459 = slot_index(Y111, "DYS459")
        i464 = slot_index(Y111, "DYS464")
        prof = pn.parse_flat_values(" ".join(flat_values(zeros=[i426, i459, i464, i464 + 1, i464 + 2, i464 + 3])),
                                    "FTDNA_Y111")
        self.assertIsNone(prof["DYS426"])                                  # 0 — нет значения
        self.assertIsInstance(prof["DYS459"], mk.Invalid)                  # одна копия из двух — не придумываем
        self.assertIsNone(prof["DYS464"])                                  # все копии пусты — нет значения

    def test_other_panels(self):
        for code in ("FTDNA_Y12", "FTDNA_Y37", "FTDNA_Y67", "GENOPOISK_Y37", "GENOPOISK_Y50"):
            p = pn.PANELS[code]
            with self.subTest(code):
                prof = pn.parse_flat_values(" ".join(flat_values(p)), code)
                self.assertEqual(sum(len(v) for v in prof.values()), p.allele_count)

    def test_auto_custom_and_wrong_count(self):
        text = " ".join(flat_values())
        for panel in ("AUTO", "CUSTOM", ""):
            with self.subTest(panel), self.assertRaisesRegex(pn.PanelMismatch, "выберите панель"):
                pn.parse_flat_values(text, panel)
        with self.assertRaisesRegex(pn.PanelMismatch, "нужно 111 значений.*введено 110"):
            pn.parse_flat_values(" ".join(flat_values()[:110]), "FTDNA_Y111")
        with self.assertRaisesRegex(pn.PanelMismatch, "нужно 37 значений.*введено 111"):
            pn.parse_flat_values(text, "FTDNA_Y37")

    def test_not_flat(self):
        for text in ("DYS393=13", "DYS393;DYS390\n13;24", "13", "13 x 14", "13 -1 14"):
            self.assertFalse(pn.looks_like_flat_list(text), text)


class WebBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        var = Path(self.tmp.name)
        settings = Settings(var_dir=var, users_db=var / "u.db", secret_file=var / "s.key",
                            manifest_file=var / "M.json", port=0, staging_dir=var / "staging")
        self.app = NestorApp(settings)
        self.addCleanup(self.app.conn.close)
        server = self.app.make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def post(self, fields, headers):
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(self.base + "/guest/search", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def search(self, headers, text=None, panel="FTDNA_Y111"):
        return self.post({"markers": text or " ".join(flat_values()), "panel": panel,
                          "max_gd": "4", "min_common": "12"}, headers)


class TestOrigin(WebBase):
    def test_same_origin_and_loopback_equivalent_accepted(self):
        for origin in (self.base, f"http://localhost:{self.port}"):
            with self.subTest(origin):
                status, page, _ = self.search({"Origin": origin})
                self.assertEqual(status, 200)
                self.assertIn("Гостевая выборка", page)
                self.assertNotIn("чужого источника", page)
        # Host: localhost (страница открыта как localhost), Origin — тот же
        status, page, _ = self.search({"Origin": f"http://localhost:{self.port}", "Host": f"localhost:{self.port}"})
        self.assertEqual(status, 200)
        # только Referer (без Origin) того же приложения
        status, _, _ = self.search({"Referer": f"http://localhost:{self.port}/"})
        self.assertEqual(status, 200)

    def test_foreign_rejected(self):
        p = self.port
        for headers in ({"Origin": "http://evil.example"}, {"Origin": f"http://evil.example:{p}"},
                        {"Origin": f"http://127.0.0.1:{p + 1}"}, {"Origin": f"http://localhost:{p + 1}"},
                        {"Origin": "null"}, {"Origin": f"https://localhost:{p}"},
                        {"Origin": f"http://localhost.evil.example:{p}"},
                        {"Referer": "http://evil.example/page"},
                        {"Origin": self.base, "Host": f"evil.example:{p}"},           # DNS rebinding
                        {"Origin": self.base, "Host": f"127.0.0.1:{p + 1}"}):
            with self.subTest(headers):
                status, page, _ = self.search(headers)
                self.assertEqual(status, 400)
                self.assertIn("запрос с чужого источника отклонён", page)
                self.assertNotIn("Гостевая выборка", page)

    def test_referrer_policy_keeps_origin_for_same_origin_forms(self):
        # Причина отказа в браузере: Referrer-Policy: no-referrer → форма отправлялась с Origin: null.
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertEqual(r.headers["Referrer-Policy"], "same-origin")


class TestGuestSearchFlat(WebBase):
    def test_flat_y111_accepted_and_reported(self):
        status, page, _ = self.search({"Origin": self.base})
        self.assertEqual(status, 200)
        self.assertIn("Профиль принят: FTDNA Y111 (выбрана)", page)
        self.assertIn("позиций со значением 102", page)
        self.assertIn("совпадений при GD ≤ 4 и не меньше 12 сравненных локусов в выборке нет", page)

    def test_flat_auto_and_wrong_count_messages(self):
        status, page, _ = self.search({"Origin": self.base}, panel="AUTO")
        self.assertEqual(status, 400)
        self.assertIn("выберите панель (например FTDNA Y111)", page)
        status, page, _ = self.search({"Origin": self.base}, text=" ".join(flat_values()[:110]))
        self.assertEqual(status, 400)
        self.assertIn("нужно 111 значений по порядку панели, введено 110", page)

    def test_page_hint(self):
        with urllib.request.urlopen(self.base + "/") as r:
            page = r.read().decode()
        self.assertIn("для 111 чисел из FTDNA — FTDNA Y111", page)
        self.assertIn("CSV / XLSX", page)


@unittest.skipUnless(shutil.which("node") and subprocess.run(["node", "-e", "require('playwright')"],
                                                             capture_output=True).returncode == 0,
                     "нужен Node.js с Playwright и Chromium")
class TestRealBrowserForm(WebBase):
    """Настоящая форма в Chromium: браузер сам ставит Origin / Referer."""

    SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [base, text, panel] = process.argv.slice(1);
  const b = await chromium.launch();
  const p = await b.newPage();
  let origin = null;
  p.on('request', r => { if (r.method() === 'POST') origin = r.headers()['origin'] ?? '(нет)'; });
  await p.goto(base + '/');
  await p.fill('textarea[name=markers]', text);
  await p.selectOption('select[name=panel]', panel);
  await Promise.all([p.waitForNavigation(), p.click('form[action="/guest/search"] button')]);
  console.log(JSON.stringify({origin, main: await p.innerText('main')}));
  await b.close();
})();
"""

    def run_browser(self, base, panel="FTDNA_Y111"):
        out = subprocess.run(["node", "-e", self.SCRIPT, base, " ".join(flat_values(zeros=[40, 70])), panel],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_form_post_from_both_loopback_names(self):
        for base in (self.base, f"http://localhost:{self.port}"):
            with self.subTest(base):
                res = self.run_browser(base)
                self.assertEqual(res["origin"], base)
                self.assertNotIn("чужого источника", res["main"])
                self.assertIn("Гостевая выборка", res["main"])
                self.assertIn("Профиль принят: FTDNA Y111", res["main"])

    def test_form_auto_shows_panel_message(self):
        res = self.run_browser(self.base, "AUTO")
        self.assertIn("выберите панель", res["main"])


if __name__ == "__main__":
    unittest.main()
