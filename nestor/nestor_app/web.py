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

import email.parser
import email.policy

from . import compare_ui, master_ui
from . import accounts, contacts, panels
from . import importer as im
from . import backups, staging
from . import test_catalog as tc
from . import user_import as ui
from .db import checkpoint_truncate
from . import markers as mk
from . import profiles as pr
from . import reference, search
from .config import catalog_command, default_staging_dir
from .config import DEFAULT_MAX_GD, DEFAULT_MIN_COMMON, GUEST_FRACTION, Settings, load_or_create_secret
from .db import connect

SESSION_COOKIE = "nestor_session"
MAX_BODY = 256 * 1024
MAX_UPLOAD_BODY = im.MAX_FILE_BYTES + 256 * 1024

VIS_LABELS = {"hidden": "скрыто", "registered": "только зарегистрированным", "public": "всем, включая гостей"}
BASIS_LABELS = {"own_test": "мой собственный тест", "authorized_other": "тест другого человека, с его разрешения"}

CSS = """
:root{--bg:#f3f5f6;--paper:#fff;--ink:#202d37;--muted:#74808a;--line:#dfe5e9;--blue:#307aa2;--pale:#eaf3f8;
--green:#397e65;--amber:#986a29;--red:#b55555;--radius:9px;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
a{color:var(--blue);text-decoration:none} a:hover{text-decoration:underline}
header{background:var(--paper);border-bottom:1px solid var(--line)}
.top{max-width:1180px;margin:0 auto;padding:14px 24px 0;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.brand{font-size:20px;font-weight:700;letter-spacing:-.01em;color:var(--ink)} .brand small{font:500 10px var(--mono);color:var(--muted);
letter-spacing:.12em;margin-left:10px;border-left:1px solid var(--line);padding-left:10px}
.top .right{margin-left:auto;display:flex;gap:10px;align-items:center}
nav{max-width:1180px;margin:0 auto;padding:0 24px;display:flex;gap:26px;flex-wrap:wrap}
nav a{color:#4b5963;padding:14px 0 12px;border-bottom:2px solid transparent;font-size:14px}
nav a.on{color:var(--blue);border-bottom-color:var(--blue)} nav a:hover{text-decoration:none;color:var(--blue)}
main{max-width:1180px;margin:0 auto;padding:18px 24px 40px}
.crumb{font:500 10px var(--mono);letter-spacing:.14em;color:var(--muted);text-transform:uppercase;margin:16px 0 6px}
h1{font-size:30px;line-height:1.15;margin:0 0 6px;letter-spacing:-.02em} h2{font-size:18px;margin:0 0 10px}
.lead{color:var(--muted);margin:0 0 18px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);padding:18px;margin:0 0 16px}
.card.flush{padding:0} .card.flush>p,.card.flush>.card-head{padding:0 18px} .card-head{display:flex;align-items:center;gap:12px;padding-top:18px!important}
.eyebrow{font:500 10px var(--mono);letter-spacing:.14em;color:var(--muted);text-transform:uppercase;margin-bottom:8px}
textarea{width:100%;min-height:110px;font:13px/1.45 var(--mono);border:1px solid var(--line);border-radius:7px;padding:10px;background:#fbfcfc}
input[type=text],input[type=email],input[type=password],select{border:1px solid var(--line);border-radius:7px;padding:8px 10px;background:#fff;font:inherit;max-width:100%}
input[type=text]:not([size]),input[type=email],input[type=password]{width:100%} input[size]{width:auto}
button{cursor:pointer;font:inherit;border:1px solid var(--line);background:#fff;border-radius:7px;padding:8px 14px}
button.primary,.primary{background:var(--blue);color:#fff;border-color:var(--blue);font-weight:600}
.row{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin:10px 0}
.row label,.filters label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:#6b7781}
.hint{flex:1;min-width:260px;font-size:12px}
.filters{display:grid;grid-template-columns:2fr repeat(2,minmax(110px,.7fr)) repeat(2,minmax(150px,1.3fr)) minmax(130px,1fr) minmax(130px,1fr) auto;
gap:10px;align-items:end;border-top:1px solid var(--line);margin:14px -18px -18px;padding:14px 18px;background:#fbfcfc;border-radius:0 0 var(--radius) var(--radius)}
@media (max-width:900px){.filters{grid-template-columns:1fr 1fr}}
table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}
th{font-size:11px;font-weight:500;color:#7a8790;background:#f7f9fa;padding:10px 14px;white-space:nowrap}
td{padding:12px 14px;border-top:1px solid var(--line);vertical-align:top}
table.results td{padding:14px 18px} table.results th{padding:10px 18px}
table.mini{font-size:12px;margin:6px 0} table.mini td,table.mini th{padding:5px 8px} table.kv th{width:42%;background:none;white-space:normal;vertical-align:top}
.sub{font-size:11px;color:var(--muted);margin-top:2px}
.gd{font-size:12px;font-weight:650;padding:5px 9px;border-radius:5px;display:inline-block;white-space:nowrap}
.g-near{background:#e9f4ec;color:#3c7e5a} .g-mid{background:#f8efdf;color:var(--amber)} .g-far{background:#f6e7e7;color:var(--red)}
.tag{display:inline-block;font-size:10px;color:#5d6a74;background:#f0f3f5;border-radius:4px;padding:2px 6px;margin-top:5px}
.tag-agg{background:var(--pale);color:var(--blue)} .tag-warn{background:#f8efdf;color:var(--amber)}
.pill{font:600 10px var(--mono);letter-spacing:.08em;padding:4px 8px;border-radius:5px} .warn-pill{background:#f8efdf;color:var(--amber)}
details summary{cursor:pointer;color:var(--blue);font-size:12px;margin-top:6px;list-style:none} details summary::-webkit-details-marker{display:none}
summary.btn{display:inline-block;border:1px solid var(--line);border-radius:7px;padding:7px 12px;color:var(--ink);font-size:13px;margin:0}
.drop{background:#fbfcfc;border:1px solid var(--line);border-radius:7px;padding:10px 12px;margin-top:8px;min-width:260px;max-width:380px}
.scroll{overflow-x:auto}
.tabs{display:flex;flex-wrap:wrap;gap:0 20px;border-bottom:1px solid var(--line);margin:10px 0 0} .card.flush .tabs{padding:0 18px}
.tabs button{border:0;border-radius:0;background:none;padding:9px 0;color:var(--muted);font-size:12px;white-space:nowrap} .tabs button:hover:not(:disabled){color:var(--blue)}
.tabs button.on{color:var(--blue);font-weight:600;box-shadow:inset 0 -2px 0 var(--blue)} .tabs button:disabled{opacity:.5;cursor:default}
.tabs .n{font-size:10px;font-weight:500;background:#edf2f4;border-radius:4px;padding:1px 4px;margin-left:5px;color:#637581}
.tab-note{font-size:11px;color:var(--muted);margin:8px 0}
.page-head{display:flex;align-items:center;justify-content:space-between;gap:22px;margin:14px 0 18px} .page-head .lead{margin:0}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.stat{padding:12px 16px;background:var(--paper);border:1px solid var(--line);border-radius:var(--radius)} .stat .eyebrow{margin:0 0 6px}
.stat .value{display:block;font-size:28px;letter-spacing:-.04em;line-height:1.25;font-weight:660;font-variant-numeric:tabular-nums}
.stat .desc{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:6px;font-size:11px;color:var(--muted)} .trend{color:var(--green);font-weight:500}
.columns{display:grid;grid-template-columns:minmax(0,1fr) 282px;gap:20px;margin-top:16px} .columns>*{min-width:0}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;margin-bottom:18px}
.panel-title{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px 18px 12px} .panel-title h2{font-size:17px;margin:0;letter-spacing:-.02em}
.panel-body{padding:0 18px 18px} .panel h3{font-size:14px;margin:0} .panel .sub{font-size:12px;margin-top:6px}
.panel table{font-size:12px} .panel th{font-size:10px} .panel td,.panel th{padding-left:10px;padding-right:10px} .panel .time{white-space:nowrap;font:11px var(--mono)}
table.sources{table-layout:fixed;min-width:480px} table.sources td{overflow-wrap:anywhere} table.sources th:nth-child(1),table.sources td:nth-child(1){width:46%} table.sources th:nth-child(2),table.sources td:nth-child(2){width:13%} table.sources th:nth-child(3),table.sources td:nth-child(3){width:19%} table.sources .num{font-variant-numeric:tabular-nums}
.state{display:inline-block;padding:3px 7px;background:#edf1f4;border-radius:4px;font-size:10px;color:#637581;white-space:nowrap}
.state.green{background:#eaf4ee;color:var(--green)} .state.amber{background:#fbf2e3;color:var(--amber)} .state.red{background:#faeded;color:var(--red)}
.status-line{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:12px} .status-line .count{font-size:12px;font-weight:600;margin-right:10px}
.more{margin-top:4px} .mini-label{font:9px var(--mono);text-transform:uppercase;letter-spacing:.13em;color:#98a2a9;margin:0 0 8px}
.settings-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 0;border-bottom:1px solid #edf1f3} .settings-row p{margin:0;font-size:12px;font-weight:550}
.caption{font-size:11px;color:#8a969f;margin:12px 0 0;line-height:1.6}
@media (max-width:1050px){.columns{grid-template-columns:minmax(0,1fr) 245px}}
@media (max-width:760px){nav{gap:0 18px}nav a{padding:9px 0 8px}.page-head{flex-direction:column;align-items:flex-start;gap:12px}.stats{grid-template-columns:repeat(2,1fr);gap:9px}.stat .value{font-size:24px}.columns{grid-template-columns:minmax(0,1fr);gap:0}}
.foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);padding:12px 18px;border-top:1px solid var(--line)}
.accepted{color:var(--green);font-size:13px} .note{font-size:12px;color:var(--amber)} .empty{padding:18px!important;color:var(--muted)}
.footnote{font-size:12px;color:var(--muted);margin-top:4px}
pre{white-space:pre-wrap;background:#f7f9fa;border:1px solid var(--line);border-radius:7px;padding:10px;font:12px var(--mono)}
.muted{color:var(--muted)} .err{color:var(--red);font-weight:600} .warn{color:var(--amber)}
form.inline{display:inline} code{font:12px var(--mono);background:#f0f3f5;padding:1px 4px;border-radius:3px}
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}


def _loopback_netloc(netloc: str | None, port: int) -> bool:
    """`localhost:PORT` или `127.0.0.1:PORT` ровно на порту этого сервера."""
    if not netloc:
        return False
    try:
        u = urlsplit("//" + netloc)
        return (u.hostname or "").lower() in LOOPBACK_HOSTS and u.port == port and not u.username and not u.password
    except ValueError:
        return False


class NestorApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = connect(settings.users_db)
        self.secret = load_or_create_secret(settings.secret_file)
        self.lock = threading.Lock()
        self.staging_dir = settings.staging_dir or default_staging_dir(settings.var_dir)
        self.staging_check = staging.ensure_private(self.staging_dir)   # проверка при запуске
        self.last_maintenance: dict = {}
        self._catalog = None   # локальный тестовый научный каталог (если включён)
        self._timer: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.maintenance()  # при запуске: очистка временных загрузок после сбоя / по сроку

    def test_catalog(self):
        """Тестовый каталог, только пока он включён; выключение и удаление действуют без перезапуска."""
        if not tc.is_enabled(self.settings.var_dir):
            self._catalog = None
            return None
        if self._catalog is None:
            self._catalog = tc.Catalog(tc.catalog_path(self.settings.var_dir))
        return self._catalog

    def maintenance(self) -> dict:
        """Очистка временных загрузок, старых резервных копий и повторный checkpoint WAL."""
        with self.lock:
            stats = staging.sweep(self.staging_dir)
            ck = checkpoint_truncate(self.conn)
        pruned = backups.prune(self.settings.var_dir / "backups", backups.keep_days_from_env())
        self.last_maintenance = {**stats, "checkpoint": ck.status, "backups_pruned": len(pruned)}
        return self.last_maintenance

    def start_maintenance_timer(self, interval: float = staging.SWEEP_INTERVAL_SECONDS) -> None:
        """Фоновая очистка в одном потоке до stop_maintenance_timer() (без цепочки таймеров)."""
        self._stop_event = threading.Event()

        def loop():
            while not self._stop_event.wait(interval):
                try:
                    self.maintenance()
                except Exception as e:  # noqa: BLE001 — сбой очистки не должен останавливать поток
                    self.last_maintenance = {"error": type(e).__name__}

        self._timer = threading.Thread(target=loop, name="nestor-maintenance", daemon=True)
        self._timer.start()

    def stop_maintenance_timer(self) -> None:
        if self._timer is not None:
            self._stop_event.set()
            self._timer.join(timeout=5)
            self._timer = None

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
        """Поля формы (первое значение). Все значения — self.form_lists, файлы — self.files."""
        self.form_lists, self.files = {}, {}
        length = int(self.headers.get("Content-Length") or 0)
        ctype = self.headers.get("Content-Type") or ""
        if ctype.startswith("multipart/form-data"):
            if length > MAX_UPLOAD_BODY:
                raise ValueError(f"файл больше {im.MAX_FILE_BYTES // (1024 * 1024)} МБ")
            body = self.rfile.read(length)
            msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                filename = part.get_filename()
                if filename is not None:
                    self.files[name] = (filename, part.get_payload(decode=True) or b"")
                else:
                    value = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
                    self.form_lists.setdefault(name, []).append(value)
        else:
            if length > MAX_BODY:
                raise ValueError("слишком большой запрос")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            self.form_lists = parse_qs(body, keep_blank_values=True)
        return {k: v[0] for k, v in self.form_lists.items()}

    def _same_origin(self) -> bool:
        """Запрос из этого же приложения: loopback-адрес и тот же порт, что у сервера.

        NeSToR слушает только 127.0.0.1, поэтому http://localhost:PORT и
        http://127.0.0.1:PORT — один и тот же сервер; другой порт, другое имя,
        https, `Origin: null` и внешние источники отклоняются. Host тоже проверяется
        (защита от DNS rebinding). Без Origin и Referer (не браузер) — как раньше,
        запрос пропускается; действия с аккаунтом дополнительно защищены CSRF-токеном.
        """
        port = self.server.server_address[1]
        if not _loopback_netloc(self.headers.get("Host"), port):
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            referer = self.headers.get("Referer")
            if referer is None:
                return True
            origin = referer
        if origin == "null":
            return False
        u = urlsplit(origin)
        return u.scheme == "http" and _loopback_netloc(u.netloc, port)

    def _send(self, status: int, body: str, ctype="text/html; charset=utf-8", extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")   # no-referrer давал Origin: null у POST формы
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
        path = urlsplit(self.path).path
        links = [("/compare", "Сравнение с научными данными"), ("/", "Поиск по профилям")]
        links += [("/me", "Мои профили")] if sess else [("/login", "Войти"), ("/register", "Регистрация")]
        if sess and accounts.is_master(self.nestor.conn, sess[0]):
            links.append(("/master", "Состояние базы"))
        nav = "".join(f'<a href="{h}"{" class=on" if (path == h or (h == "/" and path == "/guest/search")) else ""}>{esc(t)}</a>'
                      for h, t in links)
        right = (f'<form class="inline" method="post" action="/logout"><input type="hidden" name="csrf" '
                 f'value="{esc(sess[1])}"><button>Выйти</button></form>') if sess else ""
        body = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{esc(title)} — NeSToR</title><style>{CSS}</style></head><body>'
                f'<header><div class="top"><span class="brand">NeSToR<small>Y-ДНК · ЛОКАЛЬНО</small></span>'
                f'<span class="right">{right}</span></div><nav>{nav}</nav></header>'
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
        if path == "/compare":
            return self._compare(sess, None)
        if path == "/register":
            return self._register_form(sess)
        if path == "/login":
            return self._login_form(sess)
        if path == "/me":
            return self._me(sess)
        if path == "/master":
            return self._master(sess)
        if path == "/profiles/new":
            return self._new_profile_form(sess)
        if path == "/import":
            return self._import_form(sess)
        m = re.fullmatch(r"/import/([0-9a-f]{32})", path)
        if m:
            return self._import_preview(sess, m.group(1))
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
        if path == "/compare":
            return self._compare(sess, form)
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
        if path == "/master/backup":
            return self._master_backup(sess)
        if path == "/profiles/new":
            return self._create_profile(uid, form)
        if path == "/import":
            if "file" not in self.files:
                raise ValueError("выберите файл CSV или XLSX")
            filename, data = self.files["file"]
            upload_id, _ = ui.stage(self.nestor.conn, self.nestor.staging_dir, uid, filename, data,
                                    form.get("panel", "AUTO"))
            return self._redirect(f"/import/{upload_id}")
        m = re.fullmatch(r"/import/([0-9a-f]{32})/(commit|discard)", path)
        if m:
            upload_id = m.group(1)
            if m.group(2) == "discard":
                ui.discard(self.nestor.staging_dir, uid, upload_id)
                return self._redirect("/me")
            rows = []
            for v in self.form_lists.get("row", []):
                sheet, _, num = v.rpartition("|")
                rows.append((sheet, int(num)))
            ui.commit(self.nestor.conn, self.nestor.staging_dir, uid, upload_id, rows, consent_basis=form.get("consent_basis", ""),
                      consent_confirmed=form.get("consent_confirmed") == "1",
                      keep_original=form.get("keep_original") == "1")
            return self._redirect("/me")
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

    def _master_allowed(self, sess) -> bool:
        """Гостя — ко входу; вошедшему без роли — как несуществующий адрес, чтобы страница себя не выдавала."""
        if not sess:
            self._redirect("/login")
            return False
        if not accounts.is_master(self.nestor.conn, sess[0]):
            self._error("страница не найдена", sess, 404)
            return False
        return True

    def _master(self, sess):
        if self._master_allowed(sess):
            self._page("Состояние базы", master_ui.page_html(master_ui.collect(self.nestor), sess[1]), sess)

    def _master_backup(self, sess):
        if not self._master_allowed(sess):
            return
        try:
            backups.make_backup(self.nestor.settings.users_db, self.nestor.settings.var_dir / "backups")
        except FileExistsError:
            raise ValueError("копия только что создана, повторите через секунду") from None
        self._redirect("/master")

    def _login_redirect(self, uid: int):
        token, _ = accounts.create_session(self.nestor.conn, uid)
        self._redirect("/me", [("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict")])

    # ---------- страницы ----------
    def _ref_note(self) -> str:
        st = reference.status(self.nestor.settings.manifest_file)
        return f'<p class="{"muted" if st.connected else "warn"}">Научный справочник: {esc(st.reason)}.</p>'

    @staticmethod
    def _panel_select(current="AUTO") -> str:
        opts = [("AUTO", "определить автоматически (только при надёжном совпадении)"),
                (panels.CUSTOM, "пользовательский набор — без панели")]
        opts += [(code, p.title) for code, p in panels.PANELS.items()]
        return '<select name="panel">' + "".join(
            f'<option value="{esc(c)}"{" selected" if c == current else ""}>{esc(t)}</option>' for c, t in opts) + "</select>"

    def _search_form(self, text="", max_gd=DEFAULT_MAX_GD, min_common=DEFAULT_MIN_COMMON, excluded="", panel="AUTO") -> str:
        return f"""<div class="card"><h2>Гостевой поиск</h2>
<p>Вставьте Y-STR-профиль строками <code>МАРКЕР=значение</code> (например <code>DYS393=13</code>,
<code>DYS385=11-14</code>; пустое значение <code>DYS19=</code> — позиция без значения) или таблицу из двух строк
(заголовки локусов и значения через <code>;</code>), или только значения через пробел по порядку панели —
тогда <b>выберите панель</b> (например, для 111 чисел из FTDNA — FTDNA Y111; <code>0</code> — нет значения).
Файлы CSV / XLSX загружаются отдельно, в разделе «Мои профили». Профиль <b>не сохраняется</b> и не публикуется.
Гостю показываются случайные {int(GUEST_FRACTION*100)}% подходящих совпадений среди профилей,
владельцы которых разрешили поиск; повтор запроса даёт ту же выборку.</p>
<form method="post" action="/guest/search">
<textarea name="markers" required>{esc(text)}</textarea>
<p>Панель {self._panel_select(panel)}</p>
<p>GD не больше <input type="text" name="max_gd" value="{esc(max_gd)}" size="3">,
сравненных локусов (вошедших в GD) не меньше <input type="text" name="min_common" value="{esc(min_common)}" size="3"><br>
исключить локусы (через запятую) <input type="text" name="excluded" value="{esc(excluded)}" size="30">
<button>Искать</button></p></form>{self._legend()}{self._ref_note()}{self._catalog_status()}
<p class="muted">Импорт таблиц CSV / XLSX (строка заголовков локусов + строки профилей) — отдельный режим
после входа: «Мои профили» → импорт. Strelka и Y700 не поддерживаются.</p></div>"""

    @staticmethod
    def _legend() -> str:
        return ('<p class="muted">«Сравнено N из M»: M — общие позиции панелей двух профилей '
                '(DYS389II учитывается как DYS389B = II − I), N — позиции, вошедшие в GD; порог '
                'минимума считается по N. Остальные позиции не входят в GD по одной причине: '
                'исключены вами, нет значения или не распознано, разное число копий, '
                'дробное различие без перевода в шаги (GD «предварительно»). Позиции профиля с известной '
                'панелью — весь её состав (неуказанные — «нет значения»); у пользовательского набора — '
                'только указанные локусы.</p>')

    @staticmethod
    def _excluded_list(text: str) -> list[str]:
        return [x.strip() for x in (text or "").replace(";", ",").split(",") if x.strip()]

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
            extra = []
            for n, label in ((m.user_excluded, "исключено вами"),
                             (m.missing_or_invalid, "нет значения / не распознано"),
                             (m.copy_count_differences, "разное число копий"),
                             (m.allele_differences, "дробное различие")):
                if n:
                    extra.append(f"{label}: {n}")
            cmp_cell = f"сравнено {m.compared} из {m.panel_overlap}" + (f" ({'; '.join(extra)})" if extra else "")
            rows.append(f"<tr><td>{esc(m.handle)}</td><td>{gd}</td><td>{esc(cmp_cell)}</td>"
                        f"<td>{esc(m.nickname) or '—'}</td><td>{esc(m.ancestor) or '—'}</td><td>{contact}</td></tr>")
        return ("<table><tr><th>Профиль</th><th>GD</th><th>Локусы: сравнено из общих позиций панелей</th><th>Никнейм</th>"
                "<th>Дальний предок</th><th></th></tr>" + "".join(rows) + "</table>")

    def _panel_section(self, base, tabs, tab, *, action, method, hidden, contact_csrf=None) -> str:
        """Вкладки профилей: «Все» по общему порогу и панели FTDNA / Генопоиска с GD только по локусам панели."""
        active = tab if tab == search.TAB_ALL or tab in tabs else search.default_panel_tab(tabs)
        items = [(search.TAB_ALL, "Все", len(base))]
        items += [(c, panels.get_panel(c).title.replace("Genopoisk", "Генопоиск"), len(tabs[c])) for c in search.PANEL_TABS]
        note = ('<p class="tab-note">На вкладке панели GD считается только по её локусам, нужно не меньше '
                f'{int(search.PANEL_MIN_SHARE * 100)}% позиций панели. Значения разных лабораторий '
                'сравниваются без поправок шкалы.</p>')
        shown = base if active == search.TAB_ALL else tabs[active]
        return (compare_ui.tabs_html("tab", items, active, action=action, method=method, hidden=hidden)
                + note + self._match_table(shown, contact_csrf=contact_csrf))

    def _guest_search(self, sess, form):
        text = form.get("markers", "")
        try:
            max_gd = int(form.get("max_gd") or DEFAULT_MAX_GD)
            min_common = int(form.get("min_common") or DEFAULT_MIN_COMMON)
        except ValueError:
            raise ValueError("порог GD и минимум маркеров должны быть числами") from None
        excluded = form.get("excluded", "")
        panel = form.get("panel", "AUTO")
        query, code, basis = self._parse_query(text, panel)
        res = search.guest_search(self.nestor.conn, self.nestor.secret, query,
                                  max_gd=max_gd, min_common=min_common,
                                  excluded_loci=self._excluded_list(excluded))
        tabs = search.panel_tabs(self.nestor.conn, query, max_gd=max_gd, viewer="guest",
                                 excluded_loci=self._excluded_list(excluded),
                                 only_handles={m.handle for m in res.matches})
        hidden = {"markers": text, "panel": panel, "max_gd": max_gd, "min_common": min_common, "excluded": excluded,
                  "tab": form.get("tab", ""), "depth": form.get("depth", "")}
        content = (f'<div class="card"><h2>Гостевая выборка</h2>'
                   f'<p class="muted">Показаны случайные {int(res.shown_fraction*100)}% подходящих совпадений, '
                   f'отсортированные по GD. Ваш профиль не сохранён. Зарегистрируйтесь, загрузите профиль и '
                   f'включите сопоставление, чтобы видеть полный список и отправлять запросы на связь.</p>'
                   f'{self._accepted_note(query, code, basis, max_gd, min_common, len(res.matches))}'
                   f'{self._panel_section(res.matches, tabs, form.get("tab"), action="/guest/search", method="post", hidden=hidden)}</div>'
                   + self._catalog_block(query, max_gd, min_common, excluded, depth=form.get("depth"),
                                         action="/guest/search", method="post", hidden=hidden)
                   + self._search_form(text, max_gd, min_common, excluded, panel))
        self._page("Результаты", content, sess)

    @staticmethod
    def _parse_query(text: str, panel: str):
        """Профиль из формы: плоский список — только по выбранной панели; иначе МАРКЕР=значение / таблица."""
        try:
            if panels.looks_like_flat_list(text):     # «14 23 14 11 …» — только по выбранной панели
                return panels.apply_panel(panels.parse_flat_values(text, panel), panel)
            return panels.apply_panel(mk.parse_profile_input(text), panel)
        except (panels.PanelMismatch, panels.UnsupportedPanel, mk.MarkerError) as e:
            raise ValueError(str(e)) from None

    def _compare(self, sess, form):
        """Один профиль → локальный тестовый научный каталог (профиль не сохраняется)."""
        cat = self.nestor.test_catalog()
        head = ('<div class="crumb">Сравнение / научные данные</div><h1>Генетические совпадения</h1>'
                '<p class="lead">Сравнение одного профиля с научными популяционными выборками локального '
                'тестового каталога. Профиль не сохраняется.</p>')
        if cat is None:
            return self._page("Сравнение", head + compare_ui.catalog_off_html(catalog_command()), sess)
        f = dict(compare_ui.DEFAULTS)
        f.update({k: v for k, v in (form or {}).items() if k != "csrf"})
        panel = f.get("panel", "AUTO")
        facets = cat.facets()
        content, error = "", ""
        if form is not None:
            try:
                max_gd, min_common = int(f["max_gd"]), int(f["min_common"])
                if not (0 <= max_gd <= 10) or min_common < 1:
                    raise ValueError("Макс. GD — от 0 до 10, общих позиций — не меньше 1")
                query, code, basis = self._parse_query(f.get("markers", ""), panel)
                matches, summary = cat.compare_summary(query, max_gd=max_gd, min_common=min_common,
                                             excluded=self._excluded_list(f.get("excluded", "")),
                                             country=f.get("country") or None, source=f.get("source") or None,
                                             kind=f.get("kind") or None, text=f.get("text") or None,
                                             depth=f.get("depth") or None)
                content = compare_ui.results_html(matches, summary, query, code, basis,
                                                  {"max_gd": max_gd, "min_common": min_common}, hidden=f)
            except ValueError as e:
                error = str(e)
        page = head + compare_ui.form_html(f, facets, self._panel_select(panel), error) + content + compare_ui.FOOTNOTE
        self._page("Сравнение", page, sess, 400 if error else 200)

    @staticmethod
    def _accepted_note(query, code, basis, max_gd, min_common, shown) -> str:
        observed = sum(1 for v in query.values() if mk.is_observed(v))
        missing = sum(1 for v in query.values() if v is None)
        invalid = sum(1 for v in query.values() if isinstance(v, mk.Invalid))
        found = (f"показано совпадений: {shown}" if shown else
                 f"совпадений при GD ≤ {max_gd} и не меньше {min_common} сравненных локусов в выборке нет")
        return (f'<p id="query-accepted">Профиль принят: {esc(panels.panel_label(code, basis))}; '
                f'позиций со значением {observed}, без значения {missing}, не распознано {invalid}. '
                f'{esc(found)}.</p>')

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
        content = (f'<div class="card"><h2>Мои профили</h2>{table}<p><a href="/profiles/new">Ввести профиль вручную</a> · <a href="/import">Импорт из файла CSV / XLSX</a></p></div>'
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

    def _import_form(self, sess):
        if not sess:
            return self._redirect("/login")
        chk = self.nestor.staging_check
        if not chk.ok:
            return self._error("Загрузка файлов отключена: временный каталог не защищён — "
                               + "; ".join(chk.problems) + ". Проверка: py -3 run_nestor.py --check-staging", sess, 503)
        self._page("Импорт из файла", f"""<div class="card"><h2>Импорт профилей из файла</h2>
<form method="post" action="/import" enctype="multipart/form-data">
<input type="hidden" name="csrf" value="{esc(sess[1])}">
<p>Файл CSV (разделитель <code>;</code>, <code>,</code> или TAB) или XLSX (все листы)<br>
<input type="file" name="file" accept=".csv,.txt,.tsv,.xlsx" required></p>
<p>Панель {self._panel_select()}<br><span class="muted">Выбранная панель: локусы файла вне неё — ошибка листа.
«Определить автоматически» — по заголовкам, только при надёжном совпадении; иначе — пользовательский набор.</span></p>
<p class="muted">До вашего решения файл лежит во временной папке приложения (не в базе и не в её резервных
копиях) и автоматически удаляется через сутки, при отмене или после сохранения. После подтверждения в базе
остаются только выбранные строки (исходные ячейки), имя файла, лист, номера строк и SHA-256; полный файл —
только если вы отдельно попросите его сохранить. Профили создаются закрытыми; записи не объединяются.
Удаление относится к файлам приложения: стирание с диска (SSD), из снимков системы и ваших собственных
копий приложение не гарантирует.
Не более {im.MAX_FILE_BYTES // (1024 * 1024)} МБ и {im.MAX_ROWS} строк.</p>
<button>Загрузить и проверить</button></form></div>""", sess)

    def _import_preview(self, sess, upload_id):
        if not sess:
            return self._redirect("/login")
        uid, csrf = sess
        prev = ui.preview_of(self.nestor.conn, self.nestor.staging_dir, uid, upload_id)
        summ = prev.summary()
        sheet_rows = "".join(
            f"<tr><td>{esc(sh['name'])}</td><td>{esc(panels.panel_label(sh['panel'] if sh['panel'] != 'custom' else None, sh['panel_basis']))}</td>"
            f"<td>{esc(sh['header_row'])}</td><td>{sh['records']}</td><td>{sh['empty_rows']}</td>"
            f"<td class='err'>{esc(sh['error'])}</td></tr>" for sh in summ["sheets"])
        rows = []
        for r in prev.records:
            key = f"{r.sheet}|{r.row_number}"
            chk = "" if not r.savable else " checked"
            dis = " disabled" if not r.savable else ""
            invalid = "; ".join(f"{k}: {v}" for k, v in r.invalid.items())
            raw = "; ".join(f"{k}={v}" for k, v in r.raw.items())
            rows.append(
                f"<tr><td><input type='checkbox' name='row' value='{esc(key)}'{chk}{dis}></td>"
                f"<td>{esc(r.sheet)}:{r.row_number}</td><td>{esc(r.record_id) or '—'}</td>"
                f"<td>{r.observed} из {len(r.positions)}</td>"
                f"<td>{len(r.missing)}{(': ' + esc(', '.join(r.missing))) if r.missing else ''}</td>"
                f"<td>{esc(invalid) or '—'}</td>"
                f"<td class='warn'>{esc('; '.join(r.flags)) or '—'}</td><td class='err'>{esc(r.error)}</td>"
                f"<td><details><summary>ячейки</summary><code>{esc(raw)}</code></details></td></tr>")
        basis = "".join(f'<label><input type="radio" name="consent_basis" value="{k}" required> {v}</label><br>'
                        for k, v in BASIS_LABELS.items())
        content = f"""<div class="card"><h2>Проверка файла {esc(prev.filename)}</h2>
<p>SHA-256 <code>{esc(prev.sha256)}</code>, {prev.size} байт. Профилей: <b>{summ['records']}</b>,
можно сохранить: {summ['savable']}, с пропусками: {summ['with_missing']}, с нераспознанными значениями:
{summ['with_invalid']}, с пометками (повторы / совпадения): {summ['flagged']}.</p>
<table><tr><th>Лист</th><th>Панель</th><th>Строка заголовков</th><th>Профилей</th><th>Пустых строк</th><th>Ошибка</th></tr>{sheet_rows}</table>
<p class="muted">Повторы и совпадения только помечены: записи не объединяются, решаете вы.</p></div>
<div class="card"><form method="post" action="/import/{upload_id}/commit">
<input type="hidden" name="csrf" value="{esc(csrf)}">
<table><tr><th></th><th>Лист:строка</th><th>ID</th><th>Значения</th><th>Без значения</th><th>Не распознано</th>
<th>Пометки</th><th>Ошибка</th><th>Исходные ячейки</th></tr>{''.join(rows)}</table>
<p><b>Чьи это тесты?</b><br>{basis}<label><input type="checkbox" name="consent_confirmed" value="1" required>
Подтверждаю право загрузить выбранные профили.</label></p>
<p class="muted">Профили будут созданы закрытыми; ID из файла сохранится как kit ID (виден только вам).
После сохранения остаются только исходные ячейки выбранных строк, имя файла, лист, номера строк и SHA-256
файла; сам файл удаляется.</p>
<p><label><input type="checkbox" name="keep_original" value="1"> Дополнительно сохранить полный исходный файл
для локального аудита (необязательно).</label><br><span class="warn">Внимание: вместе с файлом сохранятся
<b>все</b> его строки и листы, включая профили, которые вы не выбрали. Из активной базы файл удаляется вместе
с последним сохранённым из него профилем; в уже сделанных резервных копиях базы он остаётся до их очистки (срок хранения копий
применяется, когда запускается очистка, и не является гарантированным максимумом).</span></p>
<button>Сохранить выбранные</button></form>
<form method="post" action="/import/{upload_id}/discard"><input type="hidden" name="csrf" value="{esc(csrf)}">
<button>Отменить и удалить файл</button></form></div>"""
        self._page("Проверка импорта", content, sess)

    def _new_profile_form(self, sess):
        if not sess:
            return self._redirect("/login")
        basis = "".join(f'<label><input type="radio" name="consent_basis" value="{k}" required> {v}</label><br>'
                        for k, v in BASIS_LABELS.items())
        self._page("Новый профиль", f"""<div class="card"><h2>Загрузка профиля</h2>
<form method="post" action="/profiles/new"><input type="hidden" name="csrf" value="{esc(sess[1])}">
<p>Маркеры (<code>МАРКЕР=значение</code>, по одному в строке; <code>МАРКЕР=</code> — позиция без значения;
или таблица из двух строк: заголовки и значения через <code>;</code>)<br><textarea name="markers" required></textarea></p>
<p>Панель {self._panel_select()}<br><span class="muted">Известная панель: позиции профиля — весь её состав, неуказанные
сохраняются как «нет значения». Пользовательский набор: позиции — только указанные локусы.</span></p>
<p>Kit ID (необязательно; виден только вам)<br><input type="text" name="kit_id" maxlength="60"></p>
<p><b>Чей это тест?</b><br>{basis}
<label><input type="checkbox" name="consent_confirmed" value="1" required>
Подтверждаю, что имею право загрузить этот профиль.</label></p>
<p>Никнейм владельца (необязательно) <input type="text" name="nickname" maxlength="200"> видимость {self._vis_select("nickname_visibility")}</p>
<p>Дальний предок (необязательно) <input type="text" name="ancestor_text" maxlength="200"> видимость {self._vis_select("ancestor_visibility")}</p>
<p class="muted">Профиль будет создан <b>закрытым</b> и не будет участвовать в поиске, пока вы сами не включите сопоставление.</p>
<button>Сохранить</button></form></div>""", sess)

    def _create_profile(self, uid, form):
        text = form.get("markers", "")
        markers = mk.parse_profile_input(text)
        pid = pr.create_profile(
            self.nestor.conn, uid, markers,
            consent_basis=form.get("consent_basis", ""),
            consent_confirmed=form.get("consent_confirmed") == "1",
            kit_id=form.get("kit_id"),
            panel_code=form.get("panel", "AUTO"),
            source_format="table" if mk.looks_like_table(text) else "manual",
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
        def cell(v):
            if mk.is_observed(v):
                return esc(mk.format_value(v))
            return '<span class="muted">нет значения</span>' if v is None else f'<span class="warn">не распознано: {esc(v)}</span>'
        marker_rows = "".join(f"<tr><td>{esc(k)}</td><td>{cell(v)}</td></tr>" for k, v in sorted(p.markers.items()))
        n_ok = sum(1 for v in p.markers.values() if mk.is_observed(v))
        toggle = (f'<form method="post" action="/profiles/{pid}/searchable"><input type="hidden" name="csrf" value="{esc(csrf)}">'
                  f'<input type="hidden" name="enabled" value="{0 if p.searchable else 1}">'
                  f'<button>{"Выключить сопоставление" if p.searchable else "Включить сопоставление"}</button></form>')
        content = f"""<div class="card"><h2>Профиль {esc(p.public_handle)}</h2>
<p>Статус: <b>{"поиск включён" if p.searchable else "закрыт — не участвует в поиске"}</b></p>{toggle}
<p>Kit ID (только для вас): {esc(p.kit_id_private) or "—"}<br>
Основание загрузки: {esc(BASIS_LABELS.get(p.consent_basis))}<br>
Панель: {esc(panels.panel_label(p.panel_code, p.panel_basis))}{"" if p.panel_code else (" · полностью покрыта: " + esc(best) if best else "")}</p>
<p>{"<a href='/profiles/%d/matches'>Совпадения</a> · " % pid if p.searchable else ""}<a href="/profiles/{pid}/export.json">Экспорт JSON</a></p></div>
<div class="card"><h3>Видимость необязательных полей</h3>
<form method="post" action="/profiles/{pid}/visibility"><input type="hidden" name="csrf" value="{esc(csrf)}">
<p>Никнейм <input type="text" name="nickname" value="{esc(p.nickname)}" maxlength="200"> {self._vis_select("nickname_visibility", p.nickname_visibility)}</p>
<p>Дальний предок <input type="text" name="ancestor_text" value="{esc(p.ancestor_text)}" maxlength="200"> {self._vis_select("ancestor_visibility", p.ancestor_visibility)}</p>
<button>Сохранить</button></form></div>
{self._source_block(pid)}
<div class="card"><h3>Позиции профиля: {len(p.markers)}, со значением {n_ok}</h3><table>{marker_rows}</table></div>
<div class="card"><h3>Удаление</h3><form method="post" action="/profiles/{pid}/delete">
<input type="hidden" name="csrf" value="{esc(csrf)}"><label><input type="checkbox" name="confirm" value="1" required>
Удалить профиль, маркеры, журнал согласий и запросы на связь без возможности восстановления</label>
<button>Удалить</button></form></div>"""
        self._page(p.public_handle, content, sess)

    def _source_block(self, pid) -> str:
        src = pr.load_source(self.nestor.conn, pid)
        if not src:
            return ""
        raw = json.loads(src["raw_json"])
        cells = "".join(f"<tr><td>{esc(k)}</td><td><code>{esc(v)}</code></td></tr>" for k, v in raw.items())
        return (f'<div class="card"><h3>Происхождение</h3><p>Файл {esc(src["filename"])}, SHA-256 '
                f'<code>{esc(src["file_sha256"])}</code>, лист {esc(src["sheet"])}, строка {src["row_number"]}'
                f'{", ID " + esc(src["record_id"]) if src["record_id"] else ""}. '
                f'{"Полный исходный файл сохранён по вашему согласию." if src["import_file_id"] else "Полный файл не хранится — только ячейки этой строки."}</p>'
                f'<details><summary>Исходные ячейки (дословно)</summary><table>{cells}</table></details></div>')

    def _catalog_status(self) -> str:
        cat = self.nestor.test_catalog()
        if cat is None:
            return ('<p class="muted" id="test-catalog-status">Научный тестовый каталог: <b>выключен</b>. '
                    f'Включить: <code>{esc(catalog_command())} enable</code>.</p>')
        c = cat.counts
        return ('<p class="warn" id="test-catalog-status">Научный тестовый каталог: <b>включён</b> — '
                f'ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ, непроверенные данные. Записей {c["records"]}: индивидуальных '
                f'{c["individual_records"]}, агрегированных наблюдений {c["aggregated_records"]} '
                f'(сумма N = {c["aggregated_observations"]}; это гаплотипы с численностью, а не люди); '
                f'источников {c["sources"]}. Выключить: <code>{esc(catalog_command())} disable</code>.</p>')

    def _catalog_block(self, query, max_gd, min_common, excluded, *, depth=None, action, method, hidden) -> str:
        cat = self.nestor.test_catalog()
        if cat is None:
            return ""
        matches, summary = cat.compare_summary(query, max_gd=max_gd, min_common=min_common,
                                               excluded=self._excluded_list(excluded), depth=depth or None)
        body = ((compare_ui.depth_tabs(summary, action=action, method=method, hidden=hidden)
                 + (compare_ui.matches_table(matches, summary) if matches else '<p class="empty">На этой вкладке совпадений нет.</p>'))
                if summary["tiers"][0][2] else '<p class="empty">Совпадений в тестовом каталоге нет.</p>')
        return ('<div class="card flush"><div class="card-head"><h2>Научный тестовый каталог</h2>'
                '<span class="pill warn-pill">ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ</span></div>'
                '<p class="note">Непроверенные данные: каталог собран из двух научных снимков только для '
                'локального тестирования, источники не допущены в справочник NeSToR, право на повторное '
                'использование не подтверждено, шкалы аллелей источников не откалиброваны — все GD предварительные. '
                'Агрегированные наблюдения — гаплотипы с численностью N, а не отдельные люди. Отключение: '
                f'<code>{esc(catalog_command())} disable</code>.</p>' + compare_ui.h4_hidden_note(summary) + body + '</div>')

    def _owner_matches(self, sess, pid):
        if not sess:
            return self._redirect("/login")
        q = parse_qs(urlsplit(self.path).query)
        try:
            max_gd = int(q.get("max_gd", [DEFAULT_MAX_GD])[0])
            min_common = int(q.get("min_common", [DEFAULT_MIN_COMMON])[0])
            excluded = q.get("excluded", [""])[0]
            matches = search.owner_search(self.nestor.conn, sess[0], pid, max_gd=max_gd, min_common=min_common,
                                          excluded_loci=self._excluded_list(excluded))
        except (ValueError, search.SearchError) as e:
            return self._error(str(e), sess)
        own = pr.get_owned(self.nestor.conn, sess[0], pid)
        tabs = search.panel_tabs(self.nestor.conn, own.markers, max_gd=max_gd, viewer="registered",
                                 exclude_owner=sess[0], excluded_loci=self._excluded_list(excluded))
        depth, tab = q.get("depth", [""])[0], q.get("tab", [""])[0]
        hidden = {"max_gd": max_gd, "min_common": min_common, "excluded": excluded, "tab": tab, "depth": depth}
        action = f"/profiles/{pid}/matches"
        content = (f'<div class="card"><h2>Совпадения</h2>'
                   f'<form method="get"><p>GD ≤ <input type="text" name="max_gd" value="{max_gd}" size="3"> '
                   f'сравнено (вошло в GD) ≥ <input type="text" name="min_common" value="{min_common}" size="3"> '
                   f'исключить локусы <input type="text" name="excluded" value="{esc(excluded)}" size="25"> '
                   f'<button>Обновить</button></p></form>{self._legend()}'
                   f'{self._panel_section(matches, tabs, tab, action=action, method="get", hidden=hidden, contact_csrf=sess[1])}</div>'
                   + self._catalog_block(own.markers, max_gd, min_common, excluded, depth=depth,
                                         action=action, method="get", hidden=hidden))
        self._page("Совпадения", content, sess)
