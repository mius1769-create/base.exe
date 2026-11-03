import http.cookiejar
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from synthetic import BASE_Y37, as_text

from nestor_app import reference
from nestor_app.config import Settings
from nestor_app.web import NestorApp


class TestReferenceLock(unittest.TestCase):
    """Справочник не открывается без манифеста и при несовпадении SHA-256; открывается только на чтение."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "synthetic_reference.db"
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE t(x)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        c.close()
        self.manifest = self.dir / "MANIFEST.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_manifest(self, sha):
        self.manifest.write_text(json.dumps({
            "file": self.db.name, "sha256": sha, "profiles": 1,
            "source": "synthetic", "selected_reason": "test"}), encoding="utf-8")

    def test_no_manifest(self):
        self.assertFalse(reference.status(self.manifest).connected)
        with self.assertRaises(reference.ReferenceUnavailable):
            reference.open_reference(self.manifest)

    def test_sha_mismatch_refuses(self):
        self._write_manifest("0" * 64)
        with self.assertRaises(reference.ReferenceUnavailable):
            reference.open_reference(self.manifest)

    def test_manifest_missing_fields(self):
        self.manifest.write_text(json.dumps({"file": self.db.name, "sha256": "x"}), encoding="utf-8")
        with self.assertRaises(reference.ReferenceUnavailable):
            reference.open_reference(self.manifest)

    def test_verified_db_is_read_only(self):
        self._write_manifest(reference.sha256_file(self.db))
        conn = reference.open_reference(self.manifest)
        self.assertEqual(conn.execute("SELECT x FROM t").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (2)")
        conn.close()

    def test_repository_has_no_connected_reference_yet(self):
        repo_manifest = Path(__file__).resolve().parent.parent / "data" / "MANIFEST.json"
        self.assertFalse(repo_manifest.exists(), "справочник подключается только после сверки версий")


class TestWebSmoke(unittest.TestCase):
    """Сквозной сценарий через локальный HTTP-сервер (127.0.0.1, случайный порт)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        var = Path(cls.tmp.name)
        settings = Settings(var_dir=var, users_db=var / "u.db", secret_file=var / "s.key",
                            manifest_file=var / "MANIFEST.json", port=0)
        cls.app = NestorApp(settings)
        cls.server = cls.app.make_server()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.app.conn.close()
        cls.tmp.cleanup()

    def client(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(self, opener, path, data):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(self.base + path, data=body, headers={"Origin": self.base})
        with opener.open(req) as r:
            return r.geturl(), r.read().decode()

    def get(self, opener, path):
        with opener.open(self.base + path) as r:
            return r.geturl(), r.read().decode()

    @staticmethod
    def csrf(page):
        import re
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    def test_end_to_end(self):
        guest = self.client()
        _, home = self.get(guest, "/")
        self.assertIn("Гостевой поиск", home)
        self.assertIn("не подключён", home)

        owner = self.client()
        url, page = self.post(owner, "/register", {"email": "w@example.test", "password": "password-123"})
        self.assertTrue(url.endswith("/me"))
        _, form = self.get(owner, "/profiles/new")
        url, page = self.post(owner, "/profiles/new", {
            "csrf": self.csrf(form), "markers": as_text(BASE_Y37), "kit_id": "WEBKIT77",
            "consent_basis": "own_test", "consent_confirmed": "1",
            "nickname": "Иван", "nickname_visibility": "public"})
        self.assertIn("закрыт", page)
        self.assertIn("WEBKIT77", page)  # владельцу kit ID виден
        pid = url.rstrip("/").split("/")[-1]

        # закрытый профиль гостю не виден даже при 5 одинаковых открытых профилях… их пока нет
        _, res = self.post(guest, "/guest/search", {"markers": as_text(BASE_Y37), "max_gd": "0"})
        self.assertNotIn("Иван", res)

        # включаем поиск; гость с одним совпадением получает floor(1*0.2)=0
        self.post(owner, f"/profiles/{pid}/searchable", {"csrf": self.csrf(page), "enabled": "1"})
        _, res = self.post(guest, "/guest/search", {"markers": as_text(BASE_Y37), "max_gd": "0"})
        self.assertIn("В выборке нет совпадений", res)
        self.assertNotIn("WEBKIT77", res)
        self.assertNotIn("w@example.test", res)

        # CSRF и чужой источник
        with self.assertRaises(urllib.error.HTTPError):
            self.post(owner, f"/profiles/{pid}/searchable", {"csrf": "wrong", "enabled": "0"})
        bad = urllib.request.Request(self.base + "/guest/search", data=b"markers=DYS393%3D13",
                                     headers={"Origin": "http://evil.example"})
        with self.assertRaises(urllib.error.HTTPError):
            guest.open(bad)

        # экспорт без kit ID и email
        _, exported = self.get(owner, f"/profiles/{pid}/export.json")
        self.assertNotIn("WEBKIT77", exported)
        self.assertNotIn("@", exported)

        # удаление
        _, page = self.get(owner, f"/profiles/{pid}")
        url, _ = self.post(owner, f"/profiles/{pid}/delete", {"csrf": self.csrf(page), "confirm": "1"})
        self.assertTrue(url.endswith("/me"))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get(owner, f"/profiles/{pid}")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
