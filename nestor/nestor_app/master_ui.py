"""Страница мастера «Состояние базы» (макет «Генопоиск», дизайн 02, master/overview).

Только настоящие данные этой установки и только сводно: без email, kit ID, никнеймов,
предков и маркеров конкретных людей. Роль проверяет веб-слой. Скриптов нет: страница
работает при той же политике безопасности, что и остальные.
"""

from __future__ import annotations

import collections
import html
from datetime import datetime, timezone
from pathlib import Path

from . import backups, reference
from .test_catalog import H4_SCALE_THRESHOLD

SOURCES_SHOWN = 8
EVENTS_SHOWN = 8
EVENT_LABELS = {"upload": "Загружен профиль, согласие подтверждено", "search_enabled": "Владелец включил поиск по профилю",
                "search_disabled": "Владелец выключил поиск по профилю", "visibility_changed": "Владелец изменил видимость полей"}
STATUS_CLASSES = (("допущен", "green"), ("ждём", "amber"), ("исключён", "red"))
KIND_LABELS = {"individual": "индивидуальные", "aggregated": "агрегированные"}


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _local_time(ts: datetime) -> str:
    return ts.astimezone().strftime("%d.%m.%Y %H:%M")


def _db_time(text: str) -> str:
    return _local_time(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc))


def _scalar(conn, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def _backup_state(backup_dir: Path) -> dict:
    files = sorted(backup_dir.glob(f"{backups.PREFIX}*.db"), key=lambda f: f.stat().st_mtime) if backup_dir.exists() else []
    last = datetime.fromtimestamp(files[-1].stat().st_mtime, tz=timezone.utc) if files else None
    return {"count": len(files), "bytes": sum(f.stat().st_size for f in files), "last": last,
            "keep_days": backups.keep_days_from_env()}


def collect(app) -> dict:
    """Сводка для страницы. Сюда не читаются поля, по которым можно узнать человека."""
    conn = app.conn
    markers = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM profile_markers GROUP BY status")}
    state = {
        "users": _scalar(conn, "SELECT COUNT(*) FROM users"),
        "users_week": _scalar(conn, "SELECT COUNT(*) FROM users WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-7 days')"),
        "masters": _scalar(conn, "SELECT COUNT(*) FROM users WHERE is_master = 1"),
        "profiles": _scalar(conn, "SELECT COUNT(*) FROM profiles"),
        "searchable": _scalar(conn, "SELECT COUNT(*) FROM profiles WHERE searchable = 1"),
        "markers": markers,
        "events": [(r["at"], r["event"]) for r in conn.execute(
            "SELECT event, at FROM consent_events ORDER BY id DESC LIMIT ?", (EVENTS_SHOWN,))],
        "reference": reference.status(app.settings.manifest_file),
        "backup": _backup_state(app.settings.var_dir / "backups"),
        "staging_ok": app.staging_check.ok,
        "checkpoint": app.last_maintenance.get("checkpoint"),
        "catalog": None,
    }
    cat = app.test_catalog()
    if cat is not None:
        sources = sorted(cat.sources.values(), key=lambda s: (-int(s.get("records") or 0), s["source_id"]))
        state["catalog"] = {"counts": cat.counts, "sources": sources, "h4_high": len(cat.h4_high_records()),
                            "statuses": collections.Counter(_short_status(s) for s in sources)}
    return state


def _short_status(source: dict) -> str:
    return (source.get("verification_status") or "не проверено").split(" (")[0]


def _status_pill(status: str) -> str:
    cls = next((c for prefix, c in STATUS_CLASSES if status.startswith(prefix)), "")
    return f'<span class="state {cls}">{esc(status)}</span>'


def _stat(title: str, value: str, desc: str, trend: str = "") -> str:
    tail = f'<span class="trend">{esc(trend)}</span>' if trend else ""
    return (f'<div class="stat"><div class="eyebrow">{esc(title)}</div><span class="value">{esc(value)}</span>'
            f'<div class="desc"><span>{esc(desc)}</span>{tail}</div></div>')


def _panel(title: str, body: str, note: str = "") -> str:
    aside = f"<small>{esc(note)}</small>" if note else ""
    return f'<section class="panel"><div class="panel-title"><h2>{esc(title)}</h2>{aside}</div><div class="panel-body">{body}</div></section>'


def _row(title: str, pill: str) -> str:
    return f'<div class="settings-row"><p>{esc(title)}</p>{pill}</div>'


def _sources_table(sources: list[dict], header: bool = True) -> str:
    rows = "".join(
        f'<tr><td><b>{esc(s.get("title") or s["source_id"])}</b></td><td class="num">{_num(int(s.get("records") or 0))}</td>'
        f'<td>{esc(KIND_LABELS.get(s.get("record_kind"), s.get("record_kind") or "—"))}</td><td>{_status_pill(_short_status(s))}</td></tr>'
        for s in sources)
    head = "<tr><th>Источник</th><th>Записей</th><th>Вид</th><th>Статус</th></tr>" if header else ""
    return f'<div class="scroll"><table class="sources">{head}{rows}</table></div>'


def _sources_panel(catalog: dict | None) -> str:
    if catalog is None:
        return _panel("Источники тестового каталога", '<p class="muted">Каталог выключен, источники не показываются.</p>')
    sources = catalog["sources"]
    rest = sources[SOURCES_SHOWN:]
    more = (f'<details class="more"><summary>Ещё источники: {len(rest)}</summary>{_sources_table(rest, header=False)}</details>'
            if rest else "")
    summary = "".join(f'{_status_pill(k)}<span class="count">{v}</span>' for k, v in catalog["statuses"].most_common())
    return _panel("Источники тестового каталога",
                  f'<div class="status-line">{summary}</div>{_sources_table(sources[:SOURCES_SHOWN])}{more}'
                  '<p class="caption">Только локальное тестирование: право на повторное использование не подтверждено.</p>')


def _events_panel(events: list) -> str:
    rows = "".join(f'<tr><td class="time">{esc(_db_time(at))}</td><td>{esc(EVENT_LABELS.get(ev, ev))}</td></tr>' for at, ev in events)
    body = (f'<div class="scroll"><table><tr><th>Время</th><th>Событие</th></tr>{rows}</table></div>' if rows
            else '<p class="muted">Событий пока нет.</p>')
    return _panel("Последние события", body + '<p class="caption">Журнал согласий, обезличенно. Действия мастера пока не журналируются.</p>')


def _backup_panel(b: dict) -> str:
    last = _local_time(b["last"]) if b["last"] else "Копий ещё нет"
    size = f'{b["bytes"] / (1024 * 1024):.1f}'.replace(".", ",")
    return _panel("Резервное копирование",
                  f'<div class="mini-label">Последняя копия</div><h3>{esc(last)}</h3>'
                  f'<p class="sub">Всего копий: {b["count"]} · {size} МБ · срок при очистке {b["keep_days"]:g} дн.</p>'
                  '<p class="caption">Только база пользователей. По расписанию приложение копии не создаёт.</p>')


def _quality_panel(state: dict) -> str:
    m = state["markers"]
    rows = (_row("Измеренные значения", f'<span class="state green">{_num(m.get("ok", 0))}</span>')
            + _row("Без значения", f'<span class="state">{_num(m.get("missing", 0))}</span>')
            + _row("Не распознано", f'<span class="state {"amber" if m.get("invalid") else ""}">{_num(m.get("invalid", 0))}</span>'))
    if state["catalog"]:
        rows += _row(f"Каталог: Y-GATA-H4 от {H4_SCALE_THRESHOLD}", f'<span class="state amber">{_num(state["catalog"]["h4_high"])}</span>')
    return _panel("Качество данных", rows + '<p class="caption">Пустое значение хранится отдельно и не становится измеренным нулём.</p>')


def _service_panel(state: dict) -> str:
    done = state["checkpoint"] == "complete"
    return _panel("Обслуживание",
                  _row("Временные загрузки", f'<span class="state {"green" if state["staging_ok"] else "red"}">'
                                            f'{"доступ проверен" if state["staging_ok"] else "отключены"}</span>')
                  + _row("Сброс журнала базы", f'<span class="state {"green" if done else "amber"}">{"завершён" if done else "не завершён"}</span>'))


def page_html(state: dict, csrf: str) -> str:
    catalog = state["catalog"]
    head = ('<div class="page-head"><div><div class="eyebrow">Мастер / управление базой</div><h1>Состояние базы</h1>'
            '<p class="lead">Аккаунты, профили, источники данных и обслуживание этой установки.</p></div>'
            f'<form class="head-actions" method="post" action="/master/backup"><input type="hidden" name="csrf" value="{esc(csrf)}">'
            '<button class="primary">Создать резервную копию</button></form></div>')
    week = f'+{state["users_week"]} за неделю' if state["users_week"] else ""
    ref = state["reference"]
    stats = "".join((
        _stat("Аккаунты", _num(state["users"]), f'мастеров: {state["masters"]}', week),
        _stat("Профили пользователей", _num(state["profiles"]), f'открыто для поиска: {state["searchable"]}'),
        _stat("Тестовый каталог", _num(catalog["counts"]["records"]), f'записей · источников: {catalog["counts"]["sources"]}')
        if catalog else _stat("Тестовый каталог", "Выключен", "поиск его не использует"),
        _stat("Научный справочник", "Подключён" if ref.connected else "Не подключён",
              "только чтение" if ref.connected else "причина ниже"),
    ))
    note = "" if ref.connected else f'<p class="note" id="reference-status">{esc(ref.reason)}</p>'
    return (f'{head}<div class="stats">{stats}</div>{note}<div class="columns"><div>{_sources_panel(catalog)}'
            f'{_events_panel(state["events"])}</div><aside>{_backup_panel(state["backup"])}{_quality_panel(state)}'
            f'{_service_panel(state)}</aside></div>')
