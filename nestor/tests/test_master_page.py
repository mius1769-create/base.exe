"""Страница мастера: доступ только по роли, в сводке нет данных конкретных людей."""

import http.client
import sqlite3
import tempfile
import threading
import unittest
import urllib.parse
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from synthetic import BASE_Y37

from nestor_app import accounts, db, master_cli
from nestor_app import profiles as pr
from nestor_app.config import Settings
from nestor_app.web import SESSION_COOKIE, NestorApp

EMAIL = "owner.secret@example.test"
KIT = "KIT-SECRET-777"
NICK = "Ник-секрет"


class MasterPage(unittest.TestCase):
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
        self.owner = accounts.register(self.conn, EMAIL, "password-owner")
        self.master = accounts.register(self.conn, "boss@example.test", "password-boss")

    def request(self, method, path, user=None, fields=None, csrf=None):
        headers, body = {"Host": f"127.0.0.1:{self.port}"}, None
        if user is not None:
            token, session_csrf = accounts.create_session(self.conn, user)
            headers["Cookie"] = f"{SESSION_COOKIE}={token}"
            if method == "POST":
                fields = {**(fields or {}), "csrf": session_csrf if csrf is None else csrf}
        if method == "POST":
            body = urllib.parse.urlencode(fields or {})
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        self.addCleanup(c.close)
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        return r.status, r.getheader("Location"), r.read().decode()

    def backups(self):
        d = self.var / "backups"
        return list(d.glob("*.db")) if d.exists() else []

    def test_nobody_is_master_by_default(self):
        self.assertEqual(accounts.list_masters(self.conn), [])

    def test_guest_goes_to_login(self):
        status, location, _ = self.request("GET", "/master")
        self.assertEqual((status, location), (303, "/login"))

    def test_regular_user_sees_not_found_and_no_link(self):
        status, _, page = self.request("GET", "/master", self.owner)
        self.assertEqual(status, 404)
        self.assertNotIn("Состояние базы", page)
        _, _, home = self.request("GET", "/", self.owner)
        self.assertNotIn('href="/master"', home)

    def test_master_sees_page_and_link(self):
        accounts.set_master(self.conn, "boss@example.test", True)
        status, _, page = self.request("GET", "/master", self.master)
        self.assertEqual(status, 200)
        self.assertIn("<h1>Состояние базы</h1>", page)
        self.assertIn('href="/master"', page)
        self.assertIn("мастеров: 1", page)
        self.assertIn("Выключен", page)                                   # каталог не собран
        self.assertIn('id="reference-status"', page)

    def test_revoke_works_without_restart(self):
        accounts.set_master(self.conn, "boss@example.test", True)
        accounts.set_master(self.conn, "boss@example.test", False)
        self.assertEqual(self.request("GET", "/master", self.master)[0], 404)

    def test_page_shows_counts_but_no_personal_data(self):
        accounts.set_master(self.conn, "boss@example.test", True)
        pid = pr.create_profile(self.conn, self.owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True, kit_id=KIT)
        pr.set_searchable(self.conn, self.owner, pid, True)
        pr.update_public_fields(self.conn, self.owner, pid, nickname=NICK, nickname_visibility="public",
                                ancestor_text="Предок-секрет", ancestor_visibility="public")
        handle = self.conn.execute("SELECT public_handle FROM profiles WHERE id=?", (pid,)).fetchone()[0]
        _, _, page = self.request("GET", "/master", self.master)
        self.assertIn("открыто для поиска: 1", page)
        self.assertIn("Владелец включил поиск", page)
        for secret in (EMAIL, "boss@example.test", KIT, NICK, "Предок-секрет", handle):
            self.assertNotIn(secret, page)

    def test_backup_is_for_master_with_csrf_only(self):
        self.assertEqual(self.request("POST", "/master/backup")[1], "/login")
        self.assertEqual(self.request("POST", "/master/backup", self.owner)[0], 404)
        self.assertEqual(self.backups(), [])
        accounts.set_master(self.conn, "boss@example.test", True)
        self.assertEqual(self.request("POST", "/master/backup", self.master, csrf="wrong")[0], 400)
        self.assertEqual(self.backups(), [])
        status, location, _ = self.request("POST", "/master/backup", self.master)
        self.assertEqual((status, location), (303, "/master"))
        self.assertEqual(len(self.backups()), 1)
        _, _, page = self.request("GET", "/master", self.master)
        self.assertIn("Всего копий: 1", page)
        self.assertNotIn("Копий ещё нет", page)

    def test_registration_cannot_grant_the_role(self):
        status, _, _ = self.request("POST", "/register", fields={"email": "evil@example.test", "password": "password-evil",
                                                                 "is_master": "1", "role": "master"})
        self.assertEqual(status, 303)
        self.assertEqual(accounts.list_masters(self.conn), [])


class MasterCli(unittest.TestCase):
    def run_cli(self, var, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = master_cli.main([*args, "--var-dir", str(var)])
        return code, out.getvalue()

    def test_grant_list_revoke(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            conn = db.connect(Path(tmp) / "nestor_users.db")
            accounts.register(conn, "a@example.test", "password-a")
            self.assertEqual(self.run_cli(tmp, "grant", "A@example.test")[0], 0)
            self.assertEqual(accounts.list_masters(conn), ["a@example.test"])
            self.assertIn("a@example.test", self.run_cli(tmp, "list")[1])
            self.assertEqual(self.run_cli(tmp, "revoke", "a@example.test")[0], 0)
            self.assertEqual(accounts.list_masters(conn), [])
            code, out = self.run_cli(tmp, "grant", "nobody@example.test")
            self.assertEqual(code, 1)
            self.assertIn("не найден", out)
            conn.close()


class Migration(unittest.TestCase):
    def test_v6_database_gets_the_column_and_no_masters(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "old.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, "
                        "password_hash TEXT NOT NULL, display_name TEXT, "
                        "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))")
            old.execute("INSERT INTO users(email, password_hash) VALUES ('old@example.test', 'x')")
            old.commit()
            old.close()
            conn = db.connect(path)
            self.assertEqual(accounts.list_masters(conn), [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            conn.close()


if __name__ == "__main__":
    unittest.main()
