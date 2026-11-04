"""Страница «Сравнение с научными данными» (/compare) на синтетическом каталоге."""

import threading
import urllib.error
import urllib.parse
import urllib.request

import test_test_catalog as ttc

from nestor_app import markers as mk
from nestor_app import test_catalog as tc
from nestor_app.config import Settings
from nestor_app.web import NestorApp


def hap_text(changes=None):
    hap = {**ttc.HAP, **(changes or {})}
    return "\n".join(f"{k}={'-'.join(map(str, v))}" for k, v in hap.items())


class ComparePage(ttc.Base):
    def setUp(self):
        super().setUp()
        settings = Settings(var_dir=self.var, users_db=self.var / "u.db", secret_file=self.var / "s.key",
                            manifest_file=self.var / "M.json", port=0, staging_dir=self.var / "staging")
        self.var.mkdir(parents=True, exist_ok=True)
        self.app = NestorApp(settings)
        self.addCleanup(self.app.conn.close)
        server = self.app.make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(self, path="/compare"):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read().decode()

    def post(self, fields, origin=None):
        data = {"panel": "CUSTOM", "max_gd": "4", "min_common": "10", **fields}
        req = urllib.request.Request(self.base + "/compare", data=urllib.parse.urlencode(data).encode(),
                                     headers={"Origin": origin or self.base})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def enable(self):
        self.build()
        tc.enable(self.var)


class TestComparePage(ComparePage):
    def test_catalog_off_explains_how_to_enable(self):
        page = self.get()
        self.assertIn("Научный каталог не включён", page)
        self.assertIn("build-release", page)
        self.assertIn('href="/compare" class=on', page)

    def test_results_layout_and_marks(self):
        self.enable()
        page = self.get()
        self.assertIn("Генетические совпадения", page)
        self.assertIn('name="max_gd"', page)
        self.assertIn("FTDNA Y111", page)
        status, page = self.post({"markers": hap_text()})
        self.assertEqual(status, 200)
        self.assertIn('id="query-accepted"', page)
        self.assertIn("Найденные совпадения", page)
        self.assertIn("ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ", page)
        self.assertIn('class="gd g-near">GD 0', page)
        self.assertIn("<summary>Различия</summary>", page)
        self.assertIn("Источник ↗", page)
        self.assertIn("Purps synthetic", page)                         # название источника
        self.assertIn("10.0/purps", page)                              # DOI
        self.assertIn(tc.UNVERIFIED_NOTE, page)
        self.assertIn("агрегированное наблюдение, N=5", page)
        self.assertIn("индивидуальная запись", page)
        self.assertIn('id="found">Найдено', page)

    def test_differences_show_values_and_steps(self):
        self.enable()
        status, page = self.post({"markers": hap_text({"DYS19": [15]}), "max_gd": "1", "kind": "individual",
                                  "source": "purps2014"})
        self.assertEqual(status, 200)
        self.assertIn("<td>DYS19</td><td>15</td><td>14</td><td>1 шаг</td>", page)

    def test_filters(self):
        self.enable()
        _, page = self.post({"markers": hap_text(), "kind": "aggregated"})
        self.assertIn("агрегированное наблюдение, N=5", page)
        self.assertNotIn("индивидуальная запись", page)
        _, page = self.post({"markers": hap_text(), "source": "other2026", "max_gd": "4"})
        self.assertNotIn("<p><b>Purps synthetic</b>", page)                # нет строк этого источника
        self.assertIn("<p><b>Other synthetic</b>", page)
        _, page = self.post({"markers": hap_text(), "text": "нет-такого"})
        self.assertIn('id="no-matches"', page)
        self.assertIn("Попробуйте увеличить «Макс. GD»", page)

    def test_flat_list_requires_panel_and_keeps_input(self):
        self.enable()
        text = " ".join(["13"] * 111)
        status, page = self.post({"markers": text, "panel": "AUTO"})
        self.assertEqual(status, 400)
        self.assertIn('id="compare-error"', page)
        self.assertIn("выберите панель", page)
        self.assertIn(text, page)                                      # введённое не теряется
        status, page = self.post({"markers": text, "panel": "FTDNA_Y111", "min_common": "10"})
        self.assertEqual(status, 200)
        self.assertIn("Профиль принят: FTDNA Y111 (выбрана)", page)

    def test_foreign_origin_rejected(self):
        self.enable()
        status, page = self.post({"markers": hap_text()}, origin="http://evil.example")
        self.assertEqual(status, 400)
        self.assertIn("чужого источника", page)

    def test_summary_counts_all_matches_not_only_shown(self):
        self.enable()
        cat = tc.Catalog(tc.catalog_path(self.var))
        q = mk.normalize({k: "-".join(map(str, v)) for k, v in ttc.HAP.items()})
        shown, summary = cat.compare_summary(q, max_gd=4, min_common=10, limit=1)
        self.assertEqual(len(shown), 1)
        self.assertGreater(summary["total"], 1)
        self.assertEqual(summary["individual"] + summary["aggregated"], summary["total"])
        self.assertEqual(summary["aggregated_n"], 5)
        self.assertIn("countries", cat.facets())


if __name__ == "__main__":
    import unittest
    unittest.main()
