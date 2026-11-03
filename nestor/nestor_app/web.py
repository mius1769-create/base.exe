"""Локальный веб-интерфейс NeSToR на стандартной библиотеке (http.server).

Слушает только 127.0.0.1. Веб-слой тонкий: вся логика — в модулях ядра,
поэтому его можно заменить (FastAPI / стек архива) без переписывания ядра.
"""

from __future__ import annotations

import html
import json
import re
import threading
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import accounts, contacts, panels
from . import markers as mk
from . import profiles as pr
from . import reference, search
from .config import DEFAULT_MAX_GD, DEFAULT_MIN_COMMON, GUEST_FRACTION, Settings, load_or_create_secret
from .db import connect

SESSION_COOKIE = "nestor_session"
MAX_BODY = 256 * 1024

VIS_LABELS = {"hidden": "скрыто", "registered": "только зарегистрированным", "public": "всем, включая гостей"}
BASIS_LABELS = {"own_test": "мой собственный тест", "authorized_other": "тест другого человека, с его разрешения"}

CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#666;--line:#ddd;--accent:#2f5d8a;--card:#fff;--warn:#8a4b00}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a1a;--fg:#eee;--muted:#aaa;--line:#333;--accent:#7fb0e0;--card:#232323;--warn:#e0a060}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0}
main{max-width:920px;margin:0 auto;padding:16px}
header{display:flex;gap:16px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:12px 16px}
header b{font-size:18px} a{color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin:12px 0}
textarea{width:100%;min-height:140px;font-family:ui-monospace,monospace;box-sizing:border-box}
input[type=text],input[type=email],input[type=password],select{padding:4px;max-width:100%}
table{border-collapse:collapse;width:100%} th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}
.muted{color:var(--muted)} .err{color:#b00020;font-weight:600} .warn{color:var(--warn)}
form.inline{display:inline} button{cursor:pointer}
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


class NestorApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = connect(settings.users_db)
        self.secret = load_or_create_secret(settings.secret_file)
        self.lock = threading.Lock()

    def make_server(self) -> ThreadingHTTPServer:
        app = self

        class Handler(_Handler):
            nestor = app

        return ThreadingHTTPServer((self.settings.host, self.settings.port), Handler)


class _Handler(BaseHTTPRequestHandler):
    nestor: NestorApp
    server_version = "NeSToR-local"
    sys_version = ""

    # Не пишем в лог тела запросов и query-строки (профили гостей не сохраняются).
    def log_message(self, fmt, *args):
        pass

    # ---------- инфраструктура ----------
    def _session(self):
        raw = self.headers.get("Cookie")
        token = None
        if raw:
            c = cookies.SimpleCookie()
            try:
                c.load(raw)
            except cookies.CookieError:
                c = cookies.SimpleCookie()
            if SESSION_COOKIE in c:
                token = c[SESSION_COOKIE].value
        sess = accounts.resolve_session(self.nestor.conn, token)
        return token, sess

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("слишком большой запрос")
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin or origin == "null":
            return origin is None
        return urlsplit(origin).netloc == self.headers.get("Host")

    def _send(self, status: int, body: str, ctype="text/html; charset=utf-8", extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'")
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str, extra_headers=None):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()

    def _page(self, title: str, content: str, sess=None, status=200):
        if sess:
            nav = (f'<a href="/">Поиск</a><a href="/me">Мои профили</a>'
                   f'<form class="inline" method="post" action="/logout">'
                   f'<input type="hidden" name="csrf" value="{esc(sess[1])}"><button>Выйти</button></form>')
        else:
            nav = '<a href="/">Поиск</a><a href="/login">Войти</a><a href="/register">Регистрация</a>'
        body = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{esc(title)} — NeSToR</title><style>{CSS}</style></head><body>'
                f'<header><b>NeSToR</b>{nav}<span class="muted">локальный MVP</span></header>'
                f'<main>{content}</main></body></html>')
        self._send(status, body)

    def _error(self, msg: str, sess=None, status=400):
        self._page("Ошибка", f'<div class="card"><p class="err">{esc(msg)}</p>'
                             f'<p><a href="javascript:history.back()">Назад</a></p></div>', sess, status)

    # ---------- маршрутизация ----------
    def do_GET(self):
        with self.nestor.lock:
            try:
                self._route_get()
            except pr.NotFound as e:
                self._error(str(e), self._session()[1], 404)
            except ValueError as e:
                self._error(str(e), self._session()[1])
            except Exception:  # noqa: BLE001
                self._error("внутренняя ошибка", status=500)

    def do_POST(self):
        with self.nestor.lock:
            try:
                self._route_post()
            except (ValueError, mk.MarkerError) as e:
                self._error(str(e), self._session()[1])
            except Exception:  # noqa: BLE001
                self._error("внутренняя ошибка", status=500)

    def _route_get(self):
        path = urlsplit(self.path).path
        _, sess = self._session()
        if path == "/":
            return self._home(sess)
        if path == "/register":
            return self._register_form(sess)
        if path == "/login":
            return self._login_form(sess)
        if path == "/me":
            return self._me(sess)
        if path == "/profiles/new":
            return self._new_profile_form(sess)
        m = re.fullmatch(r"/profiles/(\d+)", path)
        if m:
            return self._profile_page(sess, int(m.group(1)))
        m = re.fullmatch(r"/profiles/(\d+)/matches", path)
        if m:
            return self._owner_matches(sess, int(m.group(1)))
        m = re.fullmatch(r"/profiles/(\d+)/export\.json", path)
        if m:
            if not sess:
                return self._redirect("/login")
            data = pr.export_owner_profile(self.nestor.conn, sess[0], int(m.group(1)))
            return self._send(200, json.dumps(data, ensure_ascii=False, indent=2),
                              "application/json; charset=utf-8",
                              [("Content-Disposition", f'attachment; filename="{data["handle"]}.json"')])
        self._error("страница не найдена", sess, 404)

    def _route_post(self):
        if not self._same_origin():
            raise ValueError("запрос с чужого источника отклонён")
        path = urlsplit(self.path).path
        token, sess = self._session()
        form = self._form()
        if path == "/guest/search":
            return self._guest_search(sess, form)
        if path == "/register":
            uid = accounts.register(self.nestor.conn, form.get("email", ""), form.get("password", ""),
                                    form.get("display_name"))
            return self._login_redirect(uid)
        if path == "/login":
            uid = accounts.authenticate(self.nestor.conn, form.get("email", ""), form.get("password", ""))
            return self._login_redirect(uid)
        # дальше — только для вошедших, с CSRF-токеном
        if not sess:
            return self._redirect("/login")
        if form.get("csrf") != sess[1]:
            raise ValueError("устаревшая форма, обновите страницу")
        uid = sess[0]
        if path == "/logout":
            accounts.end_session(self.nestor.conn, token)
            return self._redirect("/", [("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")])
        if path == "/profiles/new":
            return self._create_profile(uid, form)
        m = re.fullmatch(r"/profiles/(\d+)/(searchable|visibility|delete)", path)
        if m:
            pid, action = int(m.group(1)), m.group(2)
            if action == "searchable":
                pr.set_searchable(self.nestor.conn, uid, pid, form.get("enabled") == "1")
            elif action == "visibility":
                pr.update_public_fields(self.nestor.conn, uid, pid,
                                        nickname=form.get("nickname"),
                                        nickname_visibility=form.get("nickname_visibility", "hidden"),
                                        ancestor_text=form.get("ancestor_text"),
                                        ancestor_visibility=form.get("ancestor_visibility", "hidden"))
            else:
                if form.get("confirm") != "1":
                    raise ValueError("подтвердите удаление")
                pr.delete_profile(self.nestor.conn, uid, pid)
                return self._redirect("/me")
            return self._redirect(f"/profiles/{pid}")
        if path == "/contact":
            contacts.send_request(self.nestor.conn, uid, form.get("handle", ""), form.get("message", ""))
            return self._redirect("/me")
        m = re.fullmatch(r"/requests/(\d+)/(accept|decline)", path)
        if m:
            contacts.decide(self.nestor.conn, uid, int(m.group(1)), m.group(2) == "accept", form.get("reply"))
            return self._redirect("/me")
        self._error("страница не найдена", sess, 404)

    def _login_redirect(self, uid: int):
        token, _ = accounts.create_session(self.nestor.conn, uid)
        self._redirect("/me", [("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict")])

    # ---------- страницы ----------
    def _ref_note(self) -> str:
        st = reference.status(self.nestor.settings.manifest_file)
        return f'<p class="{"muted" if st.connected else "warn"}">Научный справочник: {esc(st.reason)}.</p>'

    def _search_form(self, text="", max_gd=DEFAULT_MAX_GD, min_common=DEFAULT_MIN_COMMON) -> str:
        return f"""<div class="card"><h2>Гостевой поиск</h2>
<p>Вставьте Y-STR-профиль строками <code>МАРКЕР=значение</code> (например <code>DYS393=13</code>,
<code>DYS385=11-14</code>). Профиль <b>не сохраняется</b> и не публикуется.
Гостю показываются случайные {int(GUEST_FRACTION*100)}% подходящих совпадений среди профилей,
владельцы которых разрешили поиск; повтор запроса даёт ту же выборку.</p>
<form method="post" action="/guest/search">
<textarea name="markers" required>{esc(text)}</textarea>
<p>GD не больше <input type="text" name="max_gd" value="{esc(max_gd)}" size="3">,
общих маркеров не меньше <input type="text" name="min_common" value="{esc(min_common)}" size="3">
<button>Искать</button></p></form>{self._ref_note()}
<p class="muted">Импорт файлов FTDNA CSV, Genopoisk Y37/Y50 и Strelka XLSX будет добавлен после аудита архива.
Y700 не поддерживается.</p></div>"""

    def _home(self, sess):
        self._page("Поиск", self._search_form(), sess)

    def _match_table(self, matches, *, contact_csrf=None) -> str:
        if not matches:
            return '<p class="muted">В выборке нет совпадений.</p>'
        rows = []
        for m in matches:
            contact = ""
            if contact_csrf:
                contact = (f'<form method="post" action="/contact"><input type="hidden" name="csrf" value="{esc(contact_csrf)}">'
                           f'<input type="hidden" name="handle" value="{esc(m.handle)}">'
                           f'<input type="text" name="message" placeholder="сообщение владельцу" required>'
                           f'<button>Запросить связь</button></form>')
            gd = f"{m.gd} (предварительно)" if m.preliminary else str(m.gd)
            rows.append(f"<tr><td>{esc(m.handle)}</td><td>{gd}</td><td>{m.common}</td>"
                        f"<td>{esc(m.nickname) or '—'}</td><td>{esc(m.ancestor) or '—'}</td><td>{contact}</td></tr>")
        return ("<table><tr><th>Профиль</th><th>GD</th><th>Общих маркеров</th><th>Никнейм</th>"
                "<th>Дальний предок</th><th></th></tr>" + "".join(rows) + "</table>")

    def _guest_search(self, sess, form):
        text = form.get("markers", "")
        try:
            max_gd = int(form.get("max_gd") or DEFAULT_MAX_GD)
            min_common = int(form.get("min_common") or DEFAULT_MIN_COMMON)
        except ValueError:
            raise ValueError("порог GD и минимум маркеров должны быть числами") from None
        query = mk.parse_manual_text(text)
        res = search.guest_search(self.nestor.conn, self.nestor.secret, query,
                                  max_gd=max_gd, min_common=min_common)
        content = (f'<div class="card"><h2>Гостевая выборка</h2>'
                   f'<p class="muted">Показаны случайные {int(res.shown_fraction*100)}% подходящих совпадений, '
                   f'отсортированные по GD. Ваш профиль не сохранён. Зарегистрируйтесь, загрузите профиль и '
                   f'включите сопоставление, чтобы видеть полный список и отправлять запросы на связь.</p>'
                   f'{self._match_table(res.matches)}</div>' + self._search_form(text, max_gd, min_common))
        self._page("Результаты", content, sess)

    def _register_form(self, sess):
        self._page("Регистрация", """<div class="card"><h2>Регистрация</h2>
<form method="post" action="/register">
<p>Email (виден только вам, в поиске не показывается)<br><input type="email" name="email" required></p>
<p>Пароль (не короче 8 символов)<br><input type="password" name="password" required minlength="8"></p>
<p>Псевдоним для запросов на связь (необязательно)<br><input type="text" name="display_name" maxlength="60"></p>
<button>Создать аккаунт</button></form></div>""", sess)

    def _login_form(self, sess):
        self._page("Вход", """<div class="card"><h2>Вход</h2><form method="post" action="/login">
<p>Email<br><input type="email" name="email" required></p>
<p>Пароль<br><input type="password" name="password" required></p>
<button>Войти</button></form></div>""", sess)

    def _me(self, sess):
        if not sess:
            return self._redirect("/login")
        uid, csrf = sess
        items = []
        for p in pr.list_owned(self.nestor.conn, uid):
            state = "поиск включён" if p.searchable else "закрыт"
            items.append(f'<tr><td><a href="/profiles/{p.id}">{esc(p.public_handle)}</a></td>'
                         f'<td>{len(p.markers)}</td><td>{state}</td><td>{esc(p.created_at)}</td></tr>')
        table = ("<table><tr><th>Профиль</th><th>Маркеров</th><th>Статус</th><th>Создан</th></tr>"
                 + "".join(items) + "</table>") if items else '<p class="muted">Профилей пока нет.</p>'
        inc = []
        for r in contacts.incoming(self.nestor.conn, uid):
            actions = ""
            if r["status"] == "pending":
                actions = (f'<form method="post" action="/requests/{r["id"]}/accept"><input type="hidden" name="csrf" value="{esc(csrf)}">'
                           f'<input type="text" name="reply" placeholder="ответ (необязательно)"><button>Принять</button></form>'
                           f'<form method="post" action="/requests/{r["id"]}/decline"><input type="hidden" name="csrf" value="{esc(csrf)}">'
                           f'<button>Отклонить</button></form>')
            inc.append(f'<tr><td>{esc(r["public_handle"])}</td><td>{esc(r["sender"])}</td>'
                       f'<td>{esc(r["message"])}</td><td>{esc(r["status"])}</td><td>{actions}</td></tr>')
        out = []
        for r in contacts.outgoing(self.nestor.conn, uid):
            out.append(f'<tr><td>{esc(r["public_handle"])}</td><td>{esc(r["status"])}</td>'
                       f'<td>{esc(r["owner_reply"]) or "—"}</td></tr>')
        content = (f'<div class="card"><h2>Мои профили</h2>{table}<p><a href="/profiles/new">Загрузить профиль</a></p></div>'
                   f'<div class="card"><h2>Входящие запросы на связь</h2>'
                   + (("<table><tr><th>Профиль</th><th>От</th><th>Сообщение</th><th>Статус</th><th></th></tr>"
                       + "".join(inc) + "</table>") if inc else '<p class="muted">Нет запросов.</p>')
                   + '</div><div class="card"><h2>Мои запросы</h2>'
                   + (("<table><tr><th>Профиль</th><th>Статус</th><th>Ответ владельца</th></tr>"
                       + "".join(out) + "</table>") if out else '<p class="muted">Нет запросов.</p>') + "</div>")
        self._page("Мои профили", content, sess)

    @staticmethod
    def _vis_select(name, current="hidden") -> str:
        opts = "".join(f'<option value="{k}"{" selected" if k == current else ""}>{v}</option>'
                       for k, v in VIS_LABELS.items())
        return f'<select name="{name}">{opts}</select>'

    def _new_profile_form(self, sess):
        if not sess:
            return self._redirect("/login")
        basis = "".join(f'<label><input type="radio" name="consent_basis" value="{k}" required> {v}</label><br>'
                        for k, v in BASIS_LABELS.items())
        self._page("Новый профиль", f"""<div class="card"><h2>Загрузка профиля</h2>
<form method="post" action="/profiles/new"><input type="hidden" name="csrf" value="{esc(sess[1])}">
<p>Маркеры (<code>МАРКЕР=значение</code>, по одному в строке)<br><textarea name="markers" required></textarea></p>
<p>Kit ID (необязательно; виден только вам)<br><input type="text" name="kit_id" maxlength="60"></p>
<p><b>Чей это тест?</b><br>{basis}
<label><input type="checkbox" name="consent_confirmed" value="1" required>
Подтверждаю, что имею право загрузить этот профиль.</label></p>
<p>Никнейм владельца (необязательно) <input type="text" name="nickname" maxlength="200"> видимость {self._vis_select("nickname_visibility")}</p>
<p>Дальний предок (необязательно) <input type="text" name="ancestor_text" maxlength="200"> видимость {self._vis_select("ancestor_visibility")}</p>
<p class="muted">Профиль будет создан <b>закрытым</b> и не будет участвовать в поиске, пока вы сами не включите сопоставление.</p>
<button>Сохранить</button></form></div>""", sess)

    def _create_profile(self, uid, form):
        markers = mk.parse_manual_text(form.get("markers", ""))
        pid = pr.create_profile(
            self.nestor.conn, uid, markers,
            consent_basis=form.get("consent_basis", ""),
            consent_confirmed=form.get("consent_confirmed") == "1",
            kit_id=form.get("kit_id"),
            nickname=form.get("nickname"), nickname_visibility=form.get("nickname_visibility", "hidden"),
            ancestor_text=form.get("ancestor_text"), ancestor_visibility=form.get("ancestor_visibility", "hidden"),
        )
        self._redirect(f"/profiles/{pid}")

    def _profile_page(self, sess, pid):
        if not sess:
            return self._redirect("/login")
        uid, csrf = sess
        p = pr.get_owned(self.nestor.conn, uid, pid)
        best = panels.best_complete_panel(p.markers)
        marker_rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(mk.format_value(v))}</td></tr>"
                              for k, v in sorted(p.markers.items()))
        toggle = (f'<form method="post" action="/profiles/{pid}/searchable"><input type="hidden" name="csrf" value="{esc(csrf)}">'
                  f'<input type="hidden" name="enabled" value="{0 if p.searchable else 1}">'
                  f'<button>{"Выключить сопоставление" if p.searchable else "Включить сопоставление"}</button></form>')
        content = f"""<div class="card"><h2>Профиль {esc(p.public_handle)}</h2>
<p>Статус: <b>{"поиск включён" if p.searchable else "закрыт — не участвует в поиске"}</b></p>{toggle}
<p>Kit ID (только для вас): {esc(p.kit_id_private) or "—"}<br>
Основание загрузки: {esc(BASIS_LABELS.get(p.consent_basis))}<br>
Панель: {esc(best) + " (порядок предварительный, сверка с архивом)" if best else "полная поддержанная панель не распознана"}</p>
<p>{"<a href='/profiles/%d/matches'>Совпадения</a> · " % pid if p.searchable else ""}<a href="/profiles/{pid}/export.json">Экспорт JSON</a></p></div>
<div class="card"><h3>Видимость необязательных полей</h3>
<form method="post" action="/profiles/{pid}/visibility"><input type="hidden" name="csrf" value="{esc(csrf)}">
<p>Никнейм <input type="text" name="nickname" value="{esc(p.nickname)}" maxlength="200"> {self._vis_select("nickname_visibility", p.nickname_visibility)}</p>
<p>Дальний предок <input type="text" name="ancestor_text" value="{esc(p.ancestor_text)}" maxlength="200"> {self._vis_select("ancestor_visibility", p.ancestor_visibility)}</p>
<button>Сохранить</button></form></div>
<div class="card"><h3>Маркеры ({len(p.markers)})</h3><table>{marker_rows}</table></div>
<div class="card"><h3>Удаление</h3><form method="post" action="/profiles/{pid}/delete">
<input type="hidden" name="csrf" value="{esc(csrf)}"><label><input type="checkbox" name="confirm" value="1" required>
Удалить профиль, маркеры, журнал согласий и запросы на связь без возможности восстановления</label>
<button>Удалить</button></form></div>"""
        self._page(p.public_handle, content, sess)

    def _owner_matches(self, sess, pid):
        if not sess:
            return self._redirect("/login")
        q = parse_qs(urlsplit(self.path).query)
        try:
            max_gd = int(q.get("max_gd", [DEFAULT_MAX_GD])[0])
            min_common = int(q.get("min_common", [DEFAULT_MIN_COMMON])[0])
            matches = search.owner_search(self.nestor.conn, sess[0], pid, max_gd=max_gd, min_common=min_common)
        except (ValueError, search.SearchError) as e:
            return self._error(str(e), sess)
        content = (f'<div class="card"><h2>Совпадения</h2>'
                   f'<form method="get"><p>GD ≤ <input type="text" name="max_gd" value="{max_gd}" size="3"> '
                   f'общих ≥ <input type="text" name="min_common" value="{min_common}" size="3"> <button>Обновить</button></p></form>'
                   f'{self._match_table(matches, contact_csrf=sess[1])}</div>')
        self._page("Совпадения", content, sess)
