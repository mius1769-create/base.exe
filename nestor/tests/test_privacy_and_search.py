import dataclasses
import json
import random
import unittest

from synthetic import BASE_Y37, SECRET, mutate, new_conn, new_user, populate

from nestor_app import accounts, contacts
from nestor_app import profiles as pr
from nestor_app import search
from nestor_app.search import PublicMatch, guest_query_key, guest_sample, guest_sample_size


def dump(obj) -> str:
    if isinstance(obj, list):
        return json.dumps([dataclasses.asdict(x) if dataclasses.is_dataclass(x) else x for x in obj], ensure_ascii=False)
    return json.dumps(dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj, ensure_ascii=False, default=str)


class TestProfilesClosedByDefault(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        self.uid = new_user(self.conn, 1)

    def test_new_profile_is_closed_and_consent_logged(self):
        pid = pr.create_profile(self.conn, self.uid, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        p = pr.get_owned(self.conn, self.uid, pid)
        self.assertFalse(p.searchable)
        self.assertEqual(p.nickname_visibility, "hidden")
        self.assertEqual(p.ancestor_visibility, "hidden")
        events = [r["event"] for r in self.conn.execute("SELECT event FROM consent_events WHERE profile_id=?", (pid,))]
        self.assertEqual(events, ["upload"])
        pr.set_searchable(self.conn, self.uid, pid, True)
        pr.set_searchable(self.conn, self.uid, pid, False)
        events = [r["event"] for r in self.conn.execute("SELECT event FROM consent_events WHERE profile_id=? ORDER BY id", (pid,))]
        self.assertEqual(events, ["upload", "search_enabled", "search_disabled"])

    def test_upload_requires_consent_basis_and_confirmation(self):
        with self.assertRaises(pr.ProfileError):
            pr.create_profile(self.conn, self.uid, BASE_Y37, consent_basis="own_test", consent_confirmed=False)
        with self.assertRaises(pr.ProfileError):
            pr.create_profile(self.conn, self.uid, BASE_Y37, consent_basis="", consent_confirmed=True)
        pid = pr.create_profile(self.conn, self.uid, BASE_Y37, consent_basis="authorized_other", consent_confirmed=True)
        self.assertEqual(pr.get_owned(self.conn, self.uid, pid).consent_basis, "authorized_other")

    def test_other_user_cannot_touch_profile(self):
        pid = pr.create_profile(self.conn, self.uid, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        stranger = new_user(self.conn, 2)
        for fn in (lambda: pr.get_owned(self.conn, stranger, pid),
                   lambda: pr.set_searchable(self.conn, stranger, pid, True),
                   lambda: pr.delete_profile(self.conn, stranger, pid),
                   lambda: pr.export_owner_profile(self.conn, stranger, pid)):
            with self.assertRaises(pr.NotFound):
                fn()


class TestClosedProfilesNeverSearched(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        self.closed = populate(self.conn, [0] * 10, searchable=False, user_offset=100)
        self.open = populate(self.conn, [1] * 10, searchable=True, user_offset=200, seed=2)

    def test_closed_profiles_absent_from_guest_and_owner_search(self):
        closed_handles = {r["public_handle"] for r in self.conn.execute(
            "SELECT public_handle FROM profiles WHERE searchable=0")}
        self.assertEqual(len(closed_handles), 10)
        # гость с профилем, идентичным закрытым (GD 0), не должен их увидеть ни в одном запросе
        for gd in range(0, 5):
            res = search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=gd)
            self.assertFalse({m.handle for m in res.matches} & closed_handles)
        owner = new_user(self.conn, 999)
        pid = pr.create_profile(self.conn, owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, owner, pid, True)
        found = {m.handle for m in search.owner_search(self.conn, owner, pid)}
        self.assertEqual(len(found), 10)
        self.assertFalse(found & closed_handles)

    def test_owner_cannot_search_with_closed_profile(self):
        owner = new_user(self.conn, 998)
        pid = pr.create_profile(self.conn, owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        with self.assertRaises(search.SearchError):
            search.owner_search(self.conn, owner, pid)

    def test_disabling_search_hides_profile_again(self):
        owner = new_user(self.conn, 997)
        pid = pr.create_profile(self.conn, owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, owner, pid, True)
        handle = pr.get_owned(self.conn, owner, pid).public_handle
        seeker = new_user(self.conn, 996)
        sp = pr.create_profile(self.conn, seeker, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, seeker, sp, True)
        self.assertIn(handle, {m.handle for m in search.owner_search(self.conn, seeker, sp)})
        pr.set_searchable(self.conn, owner, pid, False)
        self.assertNotIn(handle, {m.handle for m in search.owner_search(self.conn, seeker, sp)})
        with self.assertRaises(contacts.ContactError):
            contacts.send_request(self.conn, seeker, handle, "здравствуйте")


class TestNoPrivateDataInResults(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        self.ids = populate(self.conn, [0, 1, 2, 3] * 10)

    def test_results_and_export_exclude_kit_email_and_internal_ids(self):
        owner = new_user(self.conn, 1, "Искатель")
        pid = pr.create_profile(self.conn, owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True,
                                kit_id="SECRETKIT1")
        pr.set_searchable(self.conn, owner, pid, True)
        owner_res = search.owner_search(self.conn, owner, pid)
        guest_res = search.guest_search(self.conn, SECRET, BASE_Y37).matches
        export = pr.export_owner_profile(self.conn, owner, pid)
        blob = dump(owner_res) + dump(guest_res) + json.dumps(export, ensure_ascii=False)
        self.assertNotIn("KIT", blob)
        self.assertNotIn("@example.test", blob)
        self.assertNotIn("SECRETKIT1", blob)
        self.assertEqual(set(dataclasses.asdict(owner_res[0])), {"handle", "gd", "compared", "panel_overlap", "missing_or_invalid",
                          "copy_count_differences", "allele_differences", "user_excluded",
                          "nickname", "ancestor", "preliminary", "contact_allowed"})
        self.assertNotIn("kit_id_private", export)

    def test_field_visibility_guest_vs_registered(self):
        owner = new_user(self.conn, 1)
        pid = pr.create_profile(self.conn, owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, owner, pid, True)
        # populate(): nickname — public, ancestor — registered
        for m in search.owner_search(self.conn, owner, pid):
            self.assertTrue(m.nickname and m.ancestor)
        own_handle = pr.get_owned(self.conn, owner, pid).public_handle
        guest = [m for m in search.guest_search(self.conn, SECRET, BASE_Y37).matches if m.handle != own_handle]
        self.assertTrue(guest)
        for m in guest:
            self.assertTrue(m.nickname)
            self.assertIsNone(m.ancestor)
        # скрываем никнейм у всех
        for (oid, ppid) in self.conn.execute("SELECT owner_user_id, id FROM profiles WHERE id != ?", (pid,)).fetchall():
            pr.update_public_fields(self.conn, oid, ppid, nickname="n", nickname_visibility="hidden",
                                    ancestor_text="a", ancestor_visibility="hidden")
        for m in search.owner_search(self.conn, owner, pid):
            self.assertIsNone(m.nickname)
            self.assertIsNone(m.ancestor)

    def test_contact_request_does_not_reveal_contacts(self):
        owner_a = new_user(self.conn, 1, "Андрей-искатель")
        pa = pr.create_profile(self.conn, owner_a, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, owner_a, pa, True)
        target = search.owner_search(self.conn, owner_a, pa)[0]
        target_owner = self.conn.execute("SELECT owner_user_id FROM profiles WHERE public_handle=?",
                                         (target.handle,)).fetchone()[0]
        rid = contacts.send_request(self.conn, owner_a, target.handle, "Похоже, у нас общий предок")
        inc = contacts.incoming(self.conn, target_owner)
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["sender"], "Андрей-искатель")
        self.assertNotIn("@", json.dumps(inc, ensure_ascii=False))
        self.assertIsNone(contacts.outgoing(self.conn, owner_a)[0]["owner_reply"])
        contacts.decide(self.conn, target_owner, rid, accept=True, reply="Напишите в чат проекта")
        out = contacts.outgoing(self.conn, owner_a)[0]
        self.assertEqual((out["status"], out["owner_reply"]), ("accepted", "Напишите в чат проекта"))
        with self.assertRaises(contacts.ContactError):
            contacts.decide(self.conn, target_owner, rid, accept=False)
        with self.assertRaises(contacts.ContactError):
            contacts.decide(self.conn, owner_a, rid, accept=True)  # не владелец


class TestGuestSampling(unittest.TestCase):
    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        # 50 открытых совпадений: по 10 на каждый GD 0..4
        self.ids = populate(self.conn, [0, 1, 2, 3, 4] * 10)

    def test_twenty_percent_sorted_by_gd(self):
        res = search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=4)
        self.assertEqual(len(res.matches), 10)  # 20% от 50
        gds = [m.gd for m in res.matches]
        self.assertEqual(gds, sorted(gds))

    def test_repeat_query_returns_same_sample(self):
        a = search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=4)
        b = search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=4)
        # тот же профиль, введённый в другом порядке и с другой записью копий
        reordered = dict(reversed(list(BASE_Y37.items())))
        c = search.guest_search(self.conn, SECRET, reordered, max_gd=4)
        self.assertEqual(a.matches, b.matches)
        self.assertEqual(a.matches, c.matches)

    def test_repeats_cannot_enumerate_hidden_matches(self):
        seen = set()
        for _ in range(50):
            seen |= {m.handle for m in search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=4).matches}
        self.assertEqual(len(seen), 10)

    def test_sample_drawn_from_whole_list_not_only_nearest(self):
        rng = random.Random(7)
        not_nearest = 0
        for i in range(30):
            q = mutate(BASE_Y37, 0, rng)
            q["DYS999"] = (float(10 + i),)  # разные запросы → разные ключи выборки
            res = search.guest_search(self.conn, SECRET, q, max_gd=4)
            self.assertEqual(len(res.matches), 10)
            if max(m.gd for m in res.matches) > 0:
                not_nearest += 1  # 10 ближайших все имеют GD 0
        self.assertGreater(not_nearest, 25)

    def test_guest_search_writes_nothing(self):
        before = self.conn.total_changes
        counts = [self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("users", "profiles", "profile_markers", "consent_events")]
        search.guest_search(self.conn, SECRET, mutate(BASE_Y37, 2, random.Random(3)), max_gd=4)
        self.assertEqual(self.conn.total_changes, before)
        self.assertEqual(counts, [self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                  for t in ("users", "profiles", "profile_markers", "consent_events")])

    def test_sample_size_rounding(self):
        self.assertEqual([guest_sample_size(n) for n in (0, 1, 4, 5, 9, 10, 50, 51)], [0, 0, 0, 1, 1, 2, 10, 10])

    def test_different_secret_changes_sample(self):
        a = search.guest_search(self.conn, SECRET, BASE_Y37, max_gd=4).matches
        b = search.guest_search(self.conn, b"\x22" * 32, BASE_Y37, max_gd=4).matches
        self.assertNotEqual({m.handle for m in a}, {m.handle for m in b})

    def test_portable_vector(self):
        """Фиксированный вектор: алгоритм можно воспроизвести на другом стеке (Node.js)."""
        from pathlib import Path
        vec = json.loads((Path(__file__).parent / "vectors" / "guest_sampling_v1.json").read_text(encoding="utf-8"))
        from nestor_app import markers as mk
        query = mk.normalize(vec["query"])
        key = guest_query_key(bytes.fromhex(vec["secret_hex"]), query, vec["max_gd"], vec["min_common"])
        self.assertEqual(key.hex(), vec["expected_key_hex"])
        matches = [PublicMatch(h, gd, 30, None, None) for h, gd in vec["matches"]]  # preliminary=False
        self.assertEqual([m.handle for m in guest_sample(matches, key)], vec["expected_selection"])


class TestMinMarkersThreshold(unittest.TestCase):
    """Порог min_common считается по фактически сравненным локусам (compared)."""

    def setUp(self):
        self.conn = new_conn()
        self.addCleanup(self.conn.close)
        uid = new_user(self.conn, 1)
        # 12 общих локусов с запросом: 10 сравнимых, 1 с другим числом копий, 1 с дробным различием
        target = {f"DYS{n}": (14.0,) for n in range(500, 510)}
        target["DYS385"] = (11.0, 14.0, 15.0)
        target["DYS458"] = (17.2,)
        pid = pr.create_profile(self.conn, uid, target, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, uid, pid, True)
        self.query = {f"DYS{n}": (14.0,) for n in range(500, 510)}
        self.query["DYS385"] = (11.0, 14.0)
        self.query["DYS458"] = (18.2,)
        self.owner = new_user(self.conn, 2)
        self.own = pr.create_profile(self.conn, self.owner, self.query, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(self.conn, self.owner, self.own, True)

    def test_excluded_loci_do_not_pass_threshold(self):
        self.assertEqual(search.owner_search(self.conn, self.owner, self.own, min_common=11), [])
        self.assertEqual(search.owner_search(self.conn, self.owner, self.own, min_common=12), [])

    def test_threshold_met_by_compared_loci_only(self):
        [m] = search.owner_search(self.conn, self.owner, self.own, min_common=10)
        self.assertEqual((m.gd, m.compared, m.panel_overlap), (0, 10, 12))
        self.assertEqual((m.copy_count_differences, m.allele_differences, m.preliminary), (1, 1, True))


class TestDeletion(unittest.TestCase):
    def test_delete_profile_removes_everything(self):
        conn = new_conn()
        self.addCleanup(conn.close)
        populate(conn, [0, 1] * 5)
        owner = new_user(conn, 1)
        pid = pr.create_profile(conn, owner, BASE_Y37, consent_basis="own_test", consent_confirmed=True, kit_id="K1")
        pr.set_searchable(conn, owner, pid, True)
        handle = pr.get_owned(conn, owner, pid).public_handle
        seeker = new_user(conn, 2)
        sp = pr.create_profile(conn, seeker, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        pr.set_searchable(conn, seeker, sp, True)
        contacts.send_request(conn, seeker, handle, "привет")
        pr.delete_profile(conn, owner, pid)
        for table, col in (("profiles", "id"), ("profile_markers", "profile_id"),
                           ("consent_events", "profile_id"), ("contact_requests", "to_profile_id")):
            self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (pid,)).fetchone()[0], 0, table)
        self.assertNotIn(handle, {m.handle for m in search.owner_search(conn, seeker, sp)})
        with self.assertRaises(pr.NotFound):
            pr.get_owned(conn, owner, pid)
        self.assertEqual(contacts.outgoing(conn, seeker), [])

    def test_delete_account_cascades(self):
        conn = new_conn()
        self.addCleanup(conn.close)
        uid = new_user(conn, 1)
        pr.create_profile(conn, uid, BASE_Y37, consent_basis="own_test", consent_confirmed=True)
        accounts.delete_account(conn, uid)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM profile_markers").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
