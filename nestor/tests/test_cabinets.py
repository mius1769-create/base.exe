"""Кабинеты по макету: оболочка, доступ по ролям, тема, отсутствие вымышленных данных."""

import http.client
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

from synthetic import BASE_Y37

from nestor_app import accounts, cabinet_ui, theme
from nestor_app import profiles as pr
from nestor_app.config import Settings
from nestor_app.web import SESSION_COOKIE, NestorApp

ALL_SCREENS = sorted({h for items in cabinet_ui.NAV.values() for _, h in items})
ADMIN_OR_MASTER = [h for h in ALL_SCREENS if h.startswith(("/admin", "/master"))]
CLIENT = [h for h in ALL_SCREENS if h.startswith("/cabinet") or h == "/me"]
DEMO_DATA = ("Алексей", "Петров", "Иванов", "Сидоров", "Соколов", "Волкова", "GP-10", "GP-41", "R-L1029", "1 284", "МАКЕТ ДЛЯ ОБСУЖДЕНИЯ",
             "генопоиск", "Генопоиск ·")


class Cabinets(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.app = NestorApp(Settings(var_dir=self.var, users_db=self.var / "u.db", secret_file=self.var / "s.key",
                                      manifest_file=self.var / "M.json", port=0, staging_dir=self.var / "staging"))
        self.addCleanup(self.app.conn.close)
        server = self.app.make_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        self.conn = self.app.conn
        self.user = accounts.register(self.conn, "user@example.test", "password-user", "Тест")
        self.boss = accounts.register(self.conn, "boss@example.test", "password-boss")
        accounts.set_master(self.conn, "boss@example.test", True)

    def request(self, method, path, user=None, cookie=None, referer=None):
        headers = {"Host": f"127.0.0.1:{self.port}"}
        cookies = [cookie] if cookie else []
        if user is not None:
            cookies.append(f"{SESSION_COOKIE}={accounts.create_session(self.conn, user)[0]}")
        if cookies:
            headers["Cookie"] = "; ".join(cookies)
        if referer:
            headers["Referer"] = referer
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        self.addCleanup(c.close)
        c.request(method, path, body="" if method == "POST" else None, headers=headers)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read().decode()

    def test_guest_goes_to_login_everywhere(self):
        for path in ALL_SCREENS:
            status, headers, _ = self.request("GET", path)
            self.assertEqual((status, headers.get("Location")), (303, "/login"), path)

    def test_regular_user_gets_client_screens_only(self):
        for path in CLIENT:
            self.assertEqual(self.request("GET", path, self.user)[0], 200, path)
        for path in ADMIN_OR_MASTER:
            self.assertEqual(self.request("GET", path, self.user)[0], 404, path)
        page = self.request("GET", "/cabinet", self.user)[2]
        self.assertNotIn('class="rolebar"', page)

    def test_master_opens_every_screen_with_design_shell(self):
        for path in ALL_SCREENS:
            status, _, page = self.request("GET", path, self.boss)
            self.assertEqual(status, 200, path)
            for part in ('class="site-header"', 'class="navbar"', 'class="rolebar"', 'class="footer"', "brand-mark", 'id="theme-toggle"'):
                self.assertIn(part, page, path)

    def test_no_demo_data_from_the_design_file(self):
        for path in ALL_SCREENS:
            page = self.request("GET", path, self.boss)[2].split("</style>", 1)[1]
            for text in DEMO_DATA:
                self.assertNotIn(text, page, path)

    def test_screens_without_function_say_so(self):
        for path in cabinet_ui.STUB_SCREENS:
            self.assertIn('id="in-development"', self.request("GET", path, self.boss)[2], path)
        self.assertNotIn('id="in-development"', self.request("GET", "/cabinet", self.user)[2])

    def test_overview_uses_real_profiles_of_this_user_only(self):
        pid = pr.create_profile(self.conn, self.user, BASE_Y37, consent_basis="own_test", consent_confirmed=True, nickname="МойНик")
        page = self.request("GET", "/cabinet", self.user)[2]
        self.assertIn("МойНик", page)
        self.assertIn("Профиль закрыт", page)
        self.assertNotIn("МойНик", self.request("GET", "/cabinet", self.boss)[2])
        self.assertNotIn("МойНик", self.request("GET", f"/cabinet?kit={pid}", self.boss)[2])

    def test_forms_keep_consent_and_design_markup(self):
        login = self.request("GET", "/login")[2]
        self.assertIn('class="forms one"', login)
        self.assertIn('name="password"', login)
        new = self.request("GET", "/profiles/new", self.user)[2]
        for part in ('name="consent_basis"', 'name="consent_confirmed"', 'name="markers"', 'name="panel"', 'name="csrf"',
                     'name="kit_id"', 'name="nickname_visibility"', 'name="ancestor_visibility"', "<h1>Новый результат</h1>"):
            self.assertIn(part, new)
        upload = self.request("GET", "/import", self.user)[2]
        self.assertIn('enctype="multipart/form-data"', upload)
        self.assertIn('name="file"', upload)

    def test_profile_page_keeps_actions_and_hides_nothing_from_owner(self):
        pid = pr.create_profile(self.conn, self.user, BASE_Y37, consent_basis="own_test", consent_confirmed=True, kit_id="KIT-1")
        page = self.request("GET", f"/profiles/{pid}", self.user)[2]
        for part in (f'action="/profiles/{pid}/searchable"', f'action="/profiles/{pid}/visibility"', f'action="/profiles/{pid}/delete"',
                     f'/profiles/{pid}/export.json', "KIT-1", 'name="confirm"', 'class="loci"', "DYS393"):
            self.assertIn(part, page)
        self.assertEqual(self.request("GET", f"/profiles/{pid}", self.boss)[0], 404)

    def test_error_page_has_no_blocked_script_link(self):
        page = self.request("GET", "/no-such-page")[2]
        self.assertNotIn("javascript:", page.split("</style>", 1)[1])

    def test_guest_keeps_public_menu(self):
        page = self.request("GET", "/")[2]
        self.assertIn('href="/compare"', page)
        self.assertIn('href="/register"', page)
        self.assertNotIn("/cabinet", page)

    def test_theme_attribute_comes_only_from_valid_cookie(self):
        self.assertNotIn("data-theme=", self.request("GET", "/")[2].split("<head>")[0])
        self.assertIn('<html lang="ru" data-theme="dark">', self.request("GET", "/", cookie=f"{theme.THEME_COOKIE}=dark")[2])
        self.assertIn('<html lang="ru" data-theme="light">', self.request("GET", "/", cookie=f"{theme.THEME_COOKIE}=light")[2])
        bad = urllib.parse.quote('"><script>')
        self.assertNotIn("data-theme=", self.request("GET", "/", cookie=f"{theme.THEME_COOKIE}={bad}")[2].split("<head>")[0])

    def test_theme_toggle_without_scripts(self):
        base = f"http://127.0.0.1:{self.port}"
        status, headers, _ = self.request("POST", "/theme", referer=f"{base}/compare")
        self.assertEqual((status, headers["Location"]), (303, "/compare"))
        self.assertIn(f"{theme.THEME_COOKIE}=dark", headers["Set-Cookie"])
        _, headers, _ = self.request("POST", "/theme", cookie=f"{theme.THEME_COOKIE}=dark", referer=f"{base}/guest/search")
        self.assertEqual(headers["Location"], "/")
        self.assertIn(f"{theme.THEME_COOKIE}=light", headers["Set-Cookie"])
        self.assertEqual(self.request("POST", "/theme", referer=f"{base}//evil.example/x")[1]["Location"], "/")

    def test_theme_toggle_rejects_foreign_origin(self):
        status, headers, _ = self.request("POST", "/theme", referer="http://evil.example/")
        self.assertEqual(status, 400)
        self.assertNotIn("Set-Cookie", headers)

    def test_script_is_local_and_allowed_by_policy(self):
        status, headers, body = self.request("GET", "/static/nestor.js")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))
        self.assertIn("theme-toggle", body)
        page_headers = self.request("GET", "/")[1]
        self.assertIn("default-src 'self'", page_headers["Content-Security-Policy"])
        page = self.request("GET", "/")[2]
        self.assertIn('<script src="/static/nestor.js" defer></script>', page)
        self.assertEqual(page.count("<script"), 1)                        # встроенных скриптов нет
        self.assertNotIn('href="data:', page)                             # политика безопасности блокирует data:
        self.assertNotIn("http://", body + page.split("</style>", 1)[1].replace("127.0.0.1", ""))

    def test_dark_theme_covers_both_cookie_and_system(self):
        self.assertIn(":root[data-theme=dark]{color-scheme:dark", theme.THEME_CSS)
        self.assertIn("@media (prefers-color-scheme:dark){\n:root:not([data-theme=light]){color-scheme:dark", theme.THEME_CSS)
        self.assertNotIn("@ ", theme.THEME_CSS)


if __name__ == "__main__":
    unittest.main()
