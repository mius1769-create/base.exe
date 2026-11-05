"""Настройки профиля: сохранение, журнал согласий, влияние на поиск и запросы на связь."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from synthetic import BASE_Y37, new_conn, new_user

from nestor_app import accounts, cabinet_ui, contacts, db, panels
from nestor_app import profiles as pr
from nestor_app import search

DEFAULTS = dict(searchable=True, nickname_visibility="hidden", ancestor_visibility="hidden", contact_allowed=True,
                compare_max_gd=4, compare_multicopy=True)


class Settings(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        self.uid = new_user(self.conn, 1)
        self.pid = pr.create_profile(self.conn, self.uid, BASE_Y37, consent_basis="own_test", consent_confirmed=True)

    def save(self, **changes):
        pr.update_settings(self.conn, self.uid, self.pid, **{**DEFAULTS, **changes})

    def events(self):
        return [r["event"] for r in self.conn.execute("SELECT event FROM consent_events WHERE profile_id=? ORDER BY id", (self.pid,))]

    def test_defaults_keep_previous_behaviour(self):
        p = pr.get_owned(self.conn, self.uid, self.pid)
        self.assertEqual((p.searchable, p.contact_allowed, p.compare_max_gd, p.compare_multicopy), (False, True, 4, True))

    def test_only_real_changes_reach_consent_log(self):
        self.save()
        self.assertEqual(self.events(), ["upload", "search_enabled"])
        self.save()
        self.assertEqual(self.events(), ["upload", "search_enabled"])
        self.save(contact_allowed=False, nickname_visibility="public")
        self.assertEqual(self.events()[2:], ["visibility_changed", "contact_disabled"])

    def test_values_are_saved(self):
        self.save(contact_allowed=False, compare_max_gd=7, compare_multicopy=False, ancestor_visibility="registered")
        p = pr.get_owned(self.conn, self.uid, self.pid)
        self.assertEqual((p.contact_allowed, p.compare_max_gd, p.compare_multicopy, p.ancestor_visibility), (False, 7, False, "registered"))

    def test_invalid_values_change_nothing(self):
        for bad in ({"compare_max_gd": 11}, {"compare_max_gd": -1}, {"nickname_visibility": "everyone"}):
            with self.subTest(bad), self.assertRaises(pr.ProfileError):
                self.save(**bad)
        self.assertEqual(self.events(), ["upload"])

    def test_other_owner_cannot_change_settings(self):
        other = new_user(self.conn, 2)
        with self.assertRaises(pr.NotFound):
            pr.update_settings(self.conn, other, self.pid, **DEFAULTS)
        self.assertFalse(pr.get_owned(self.conn, self.uid, self.pid).searchable)

    def test_contact_is_refused_in_core_when_disabled(self):
        self.save(contact_allowed=False)
        sender = new_user(self.conn, 3)
        handle = pr.get_owned(self.conn, self.uid, self.pid).public_handle
        with self.assertRaisesRegex(contacts.ContactError, "не принимает"):
            contacts.send_request(self.conn, sender, handle, "здравствуйте")
        self.save(contact_allowed=True)
        self.assertTrue(contacts.send_request(self.conn, sender, handle, "здравствуйте"))

    def test_search_shows_contact_flag_without_other_data(self):
        self.save(contact_allowed=False)
        seeker = new_user(self.conn, 4)
        spid = pr.create_profile(self.conn, seeker, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, seeker, spid, True)
        match, = search.owner_search(self.conn, seeker, spid)
        self.assertFalse(match.contact_allowed)
        self.assertIsNone(match.nickname)

    def test_multicopy_setting_excludes_those_loci(self):
        self.save(compare_multicopy=False, compare_max_gd=2)
        p = pr.get_owned(self.conn, self.uid, self.pid)
        max_gd, excluded = search.owner_defaults(p)
        self.assertEqual(max_gd, 2)
        self.assertEqual(excluded, list(panels.MULTICOPY_LOCI))
        self.assertIn("DYS464", excluded)
        other = new_user(self.conn, 5)
        changed = {**BASE_Y37, "DYS464": (11.0, 15.0, 17.0, 17.0)}
        opid = pr.create_profile(self.conn, other, changed, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, other, opid, True)
        with_all, = search.owner_search(self.conn, self.uid, self.pid)
        without, = search.owner_search(self.conn, self.uid, self.pid, excluded_loci=excluded)
        self.assertGreater(with_all.gd, without.gd)
        self.assertEqual(without.gd, 0)

    def test_page_renders_real_values_as_checkboxes(self):
        self.save(contact_allowed=False)
        p = pr.get_owned(self.conn, self.uid, self.pid)
        page = cabinet_ui.settings_page([p], p, "TOKEN", True, "<select></select>", "<select></select>", "<select></select>")
        self.assertIn('name="searchable" value="1" checked', page)
        self.assertNotIn('name="contact_allowed" value="1" checked', page)
        self.assertIn('name="compare_multicopy" value="1" checked', page)
        self.assertIn('id="settings-saved"', page)
        self.assertIn('form="settings-form"', page)
        self.assertNotIn('id="in-development"', page)


class Migration(unittest.TestCase):
    def test_v7_profiles_keep_data_and_allow_contact(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "old.db"
            conn = db.connect(path)
            uid = accounts.register(conn, "a@example.test", "password-a")
            pid = pr.create_profile(conn, uid, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
            conn.close()
            raw = sqlite3.connect(path)
            for col in ("contact_allowed", "compare_max_gd", "compare_multicopy"):
                raw.execute(f"ALTER TABLE profiles DROP COLUMN {col}")
            raw.commit()
            raw.close()
            conn = db.connect(path)
            p = pr.get_owned(conn, uid, pid)
            self.assertEqual((p.contact_allowed, p.compare_max_gd, p.compare_multicopy, len(p.markers)), (True, 4, True, len(BASE_Y37)))
            conn.close()


if __name__ == "__main__":
    unittest.main()
