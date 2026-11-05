"""Оболочка страниц и кабинеты по макету «Генопоиск», дизайн 02 (пользователь, администратор, мастер).

Заголовки и подписи взяты из макета дословно. Экраны без готовой функции показывают то же расположение,
пометку о разработке и пустое состояние: вымышленных людей, цифр и переписки здесь нет.
"""

from __future__ import annotations

import html

from . import panels

BRAND_MARK = ('<svg class="brand-mark" viewBox="0 0 26 30" fill="none" aria-hidden="true"><path d="M5 2c0 12 16 14 16 26M21 2C21 14 5 16 5 '
              '28M7 7h12M7 23h12M10 12h6M10 18h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>')

ROLE_LABELS = (("client", "Пользователь", "/cabinet"), ("admin", "Администратор", "/admin"), ("master", "Мастер базы", "/master"))
NAV = {
    "client": (("Обзор", "/cabinet"), ("Совпадения", "/cabinet/matches"), ("Мои результаты", "/me"), ("Проекты", "/cabinet/projects"),
               ("Сообщения", "/cabinet/messages"), ("Настройки", "/cabinet/settings")),
    "admin": (("Обзор проекта", "/admin"), ("Участники", "/admin/members"), ("Группы", "/admin/groups"), ("Кластеры", "/admin/clusters"),
              ("Массовый импорт", "/admin/import"), ("Сообщения", "/admin/messages")),
    "master": (("Обзор базы", "/master"), ("Аккаунты и роли", "/master/accounts"), ("Проекты", "/master/projects"),
               ("Научная база", "/master/science"), ("Резервные копии", "/master/backups"), ("Журнал", "/master/audit"),
               ("Сообщения", "/master/messages")),
}
GUEST_NAV = (("Сравнение с научными данными", "/compare"), ("Поиск по профилям", "/"), ("Войти", "/login"), ("Регистрация", "/register"))
STUB_NOTE = ('<div class="info warm" id="in-development">Раздел в разработке: здесь показано расположение из макета. '
             'Настоящих функций пока нет, вымышленных данных тоже.</div>')


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def role_of(path: str) -> str:
    return "master" if path.startswith("/master") else "admin" if path.startswith("/admin") else "client"


def _active_item(path: str, role: str) -> str:
    if role == "client":
        if path in ("/", "/compare", "/guest/search") or path.endswith("/matches"):
            return "/cabinet/matches"
        if path == "/me" or path.startswith(("/profiles", "/import")):
            return "/me"
    return path


def shell(title: str, content: str, *, path: str, theme: str | None, user: dict | None, css: str) -> str:
    """Вся страница: шапка, меню, основная часть и подвал. user: {name, initials, csrf, is_master}."""
    if user:
        role = role_of(path)
        current = _active_item(path, role)
        nav = "".join(f'<a href="{h}"{" class=on" if h == current else ""}>{esc(t)}</a>' for t, h in NAV[role])
        roles = (('<div class="rolebar" aria-label="Режим просмотра">' + "".join(
            f'<a href="{h}"{" class=on" if r == role else ""}>{esc(t)}</a>' for r, t, h in ROLE_LABELS) + "</div>")
            if user["is_master"] else '<span class="top-gap"></span>')
        logout = (f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{esc(user["csrf"])}">'
                  '<button class="quiet">Выйти</button></form>')
        person = f'<div class="avatar">{esc(user["initials"])}</div><span>{esc(user["name"])}</span>{logout}'
    else:
        nav = "".join(f'<a href="{h}"{" class=on" if (path == h or (h == "/" and path == "/guest/search")) else ""}>{esc(t)}</a>'
                      for t, h in GUEST_NAV)
        roles, person = '<span class="top-gap"></span>', ""
    toggle = ('<form method="post" action="/theme"><button class="theme-toggle" id="theme-toggle" type="submit" '
              'aria-label="Переключить светлую или тёмную тему" title="Светлая / тёмная тема">◐</button></form>')
    attr = f' data-theme="{theme}"' if theme else ""
    return (f'<!doctype html><html lang="ru"{attr}><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)} — NeSToR</title><style>{css}</style><script src="/static/nestor.js" defer></script></head><body>'
            '<a class="screenreader" href="#main">К содержимому</a>'
            f'<header class="site-header"><div class="wrap"><div class="topline"><a class="brand" href="/" aria-label="NeSToR — главная">'
            f'{BRAND_MARK}NeSToR<small>Y-ДНК</small></a>{roles}<div class="account">{toggle}{person}</div></div>'
            f'<nav class="navbar" aria-label="Разделы">{nav}</nav></div></header>'
            '<div class="wrap demo-strip"><span><i class="live-dot"></i>ЛОКАЛЬНАЯ УСТАНОВКА · ТОЛЬКО 127.0.0.1</span></div>'
            f'<main class="wrap" id="main" tabindex="-1">{content}</main>'
            '<div class="wrap"><footer class="footer"><span>NESTOR / ДИЗАЙН 02</span><span>Локальная установка</span></footer></div>'
            '</body></html>')


def head(label: str, title: str, sub: str, action: str = "") -> str:
    return (f'<div class="page-head"><div><div class="eyebrow">{esc(label)}</div><h1>{esc(title)}</h1><p class="sub">{esc(sub)}</p></div>'
            f'<div class="head-actions">{action}</div></div>')


def panel(title: str, body: str, action: str = "") -> str:
    return (f'<section class="panel"><div class="panel-title"><h2>{esc(title)}</h2>{action}</div>'
            f'<div class="panel-body">{body}</div></section>')


def table(heads, rows, empty: str = "Пока нет данных.") -> str:
    head_row = "".join(f"<th>{esc(h)}</th>" for h in heads)
    body = "".join(rows) or f'<tr><td colspan="{len(heads)}"><div class="empty">{esc(empty)}</div></td></tr>'
    return f'<div class="tablewrap"><table><thead><tr>{head_row}</tr></thead><tbody>{body}</tbody></table></div>'


def stat(title: str, value, desc: str, href: str = "", trend: str = "") -> str:
    tail = f'<span class="trend">{esc(trend)}</span>' if trend else ('<span class="arrow">↗</span>' if href else "")
    inner = (f'<div class="eyebrow">{esc(title)}</div><span class="value">{esc(value)}</span>'
             f'<div class="desc"><span>{esc(desc)}</span>{tail}</div>')
    return f'<a class="stat" href="{href}">{inner}</a>' if href else f'<div class="stat">{inner}</div>'


def _off_button(text: str, primary: bool = False) -> str:
    return f'<button type="button" class="{"primary" if primary else ""}" disabled title="В разработке">{esc(text)}</button>'


def _off_switch_row(title: str, desc: str) -> str:
    return (f'<div class="settings-row"><div><p>{esc(title)}</p><small>{esc(desc)}</small></div>'
            f'<button type="button" class="switch" role="switch" aria-checked="false" aria-label="{esc(title)}" disabled></button></div>')


def _project_bar() -> str:
    return ('<div class="contextbar"><label for="active-project">Текущий проект</label><select id="active-project" disabled>'
            '<option>Проектов пока нет</option></select></div>')


def _kit_bar_empty() -> str:
    return ('<div class="contextbar"><label for="active-kit">Выбранный образец</label><select id="active-kit" disabled>'
            '<option>Выбор образца появится вместе с разделом</option></select></div>')


def _stats(*items) -> str:
    return '<div class="stats">' + "".join(stat(t, "—", d) for t, d in items) + "</div>"


def _messages(role_label: str, sub: str) -> str:
    return (head(f"{role_label} / сообщения", "Личные сообщения", sub) + STUB_NOTE
            + '<section class="panel inbox"><div class="threads"><div class="empty">Диалогов пока нет</div></div><div class="chat">'
            '<div class="chat-head"><h3>Переписка</h3><small>Запросы на связь пока находятся в разделе «Мои результаты»</small></div>'
            '<div class="chat-body"></div><form class="composer"><input aria-label="Текст сообщения" placeholder="Написать сообщение…" disabled>'
            f'{_off_button("Отправить", True)}</form></div></section>')


def _bulk_import() -> str:
    options = "".join(f"<option>{esc(p)}</option>" for p in ("FTDNA Y37", "FTDNA Y67", "FTDNA Y111", "Genopoisk Y37", "Genopoisk Y50"))
    template = ('<div class="forms"><div class="field full"><label for="test-panel">Тип теста / вкладка шаблона</label>'
                f'<select id="test-panel" disabled>{options}</select></div><p class="caption full">Все панели используют единый формат '
                f'карточки. Меняется набор колонок локусов.</p></div><div class="actions form-note">{_off_button("Скачать CSV-пример")}</div>')
    upload = ('<p class="sub">XLSX, CSV, TSV и TXT.</p><input type="file" disabled aria-label="Выбрать файл результатов" class="form-note">'
              '<div class="info form-note">Оригинал, нормализованные значения и строка предиктора хранятся отдельно. '
              'No call сохраняется как отсутствие измерения.</div>')
    return (head("Администратор / импорт", "Массовая загрузка", "Один лист — один тип теста. Один кит — одна строка.") + STUB_NOTE
            + _project_bar() + f'<div class="grid2">{panel("Типовой шаблон", template)}{panel("Файл с результатами", upload)}</div>'
            + '<section class="panel"><div class="panel-title"><h2>Проверка перед сохранением</h2><span class="pill">Ожидает заполнения</span></div>'
            '<div class="panel-body"><div class="empty">Выберите тип теста и загрузите файл.</div></div></section>')


def _client_settings() -> str:
    privacy = (_off_switch_row("Показывать карточку и ник", "Имя образца и данные генеалогического профиля.")
               + _off_switch_row("Разрешить личные сообщения", "Участники смогут написать владельцу аккаунта.")
               + _off_switch_row("Показывать населённый пункт предка", "Страна и регион могут оставаться видимыми отдельно."))
    compare = ('<div class="settings-row"><div><p>Максимальная дистанция</p><small>Шаги различий на сопоставленных STR</small></div>'
               '<select aria-label="Порог GD в настройках" disabled><option>4</option></select></div>'
               + _off_switch_row("Учитывать мультикопийные локусы", "Все сопоставимые локусы включены по умолчанию.")
               + '<p class="caption">Видимость полей уже настраивается на странице каждого профиля в разделе «Мои результаты».</p>')
    return (head("Личный кабинет / настройки", "Профиль и сравнение", "Настройки приватности применяются к выбранному образцу.",
                 _off_button("Сохранить настройки", True)) + STUB_NOTE + _kit_bar_empty()
            + f'<div class="grid2">{panel("Приватность", privacy)}{panel("Параметры сравнения", compare)}</div>')


def _project_cards(label: str, title: str, sub: str, action: str = "", bar: str = "") -> str:
    return (head(label, title, sub, action) + STUB_NOTE + bar + panel("Проекты", '<div class="empty">Проектов пока нет.</div>'))


def _admin_overview() -> str:
    return (head("Администратор / проект", "Аналитика проекта", "Общая картина результатов и следующие шаги исследования.",
                 _off_button("Кандидаты на апгрейд", True)) + STUB_NOTE + _project_bar()
            + _stats(("Результаты проекта", "китов в проекте"), ("Участники", "человек"), ("Подтверждение SNP", "китов"), ("Заявки", "ожидают решения"))
            + '<div class="chart-grid">' + panel("Источники результатов", '<div class="empty">Пока нет данных.</div>')
            + panel("Новые результаты", '<div class="empty">Пока нет данных.</div>') + "</div>"
            + '<div class="grid2">' + panel("Макрогаплогруппы", '<div class="empty">Пока нет данных.</div>')
            + panel("Требует внимания", '<div class="empty">Пока ничего нет.</div>') + "</div>")


def _admin_members() -> str:
    return (head("Администратор / участники", "Участники и заявки", "Управление составом проекта без доступа к полным STR-профилям.")
            + STUB_NOTE + _project_bar()
            + panel("Заявки на вступление · 0", table(("Участник / образец", "Панель", "Место предка", "Решение"), [], "Заявок нет."))
            + panel("Участники проекта", table(("Образец", "Панель", "Субклад / основание", "Группа", ""), [])))


def _admin_groups() -> str:
    return (head("Администратор / группы", "Группы проекта", "Автоматические макрогаплогруппы и рабочие подборки администратора.",
                 _off_button("+ Создать подборку", True)) + STUB_NOTE + _project_bar()
            + '<div class="section-head"><h2>По макрогаплогруппе</h2><small>Из карточек результатов · обновляются автоматически</small></div>'
            + panel("Макрогаплогруппы", '<div class="empty">Пока нет данных.</div>')
            + '<div class="section-head"><h2>Рабочие подборки</h2><small>Фамилии, местности и другие признаки</small></div>'
            + panel("Подборки", '<div class="empty">Подборок пока нет.</div>'))


def _admin_clusters() -> str:
    return (head("Администратор / кластеры", "Кластеры проекта", "Рабочие подборки близких результатов внутри заявленных субкладов.")
            + STUB_NOTE + _project_bar()
            + '<div class="info">Субклад и STR-дистанция — отдельные признаки. Этот раздел не строит филогенетическое древо и не подтверждает родство.</div>'
            + panel("Кластеры", '<div class="empty">Пока нет данных.</div>')
            + '<p class="caption">Полные исходные STR администратору не показываются.</p>')


def _master_accounts() -> str:
    return (head("Мастер / аккаунты", "Аккаунты и роли", "Подтверждение регистраций, блокировки и назначение ролей.") + STUB_NOTE
            + panel("Аккаунты", table(("Участник", "Роль", "Киты", "Статус", "Действие"), [],
                                      "Управление появится вместе с разделом. Роль мастера пока выдаётся командой на этом компьютере.")))


def _master_science() -> str:
    return (head("Мастер / научная база", "Источники и качество данных", "Связь профилей с публикациями и статусы сопоставимости.",
                 _off_button("Экспорт реестра")) + STUB_NOTE
            + '<div class="info">Источники тестового каталога и их статусы уже показаны на странице «Обзор базы».</div>'
            + panel("Реестр источников", table(("Публикация / набор", "Панель", "Статус", ""), [])))


def _master_audit() -> str:
    return (head("Мастер / журнал", "Журнал событий", "Кто, когда и какое действие выполнил в базе.", _off_button("Экспорт CSV")) + STUB_NOTE
            + panel("События", table(("Время", "Инициатор", "Действие", "Подробности"), [], "Журнал действий пока не ведётся.")))


# Экраны без готовой функции: адрес → вид. Доступ по роли проверяет веб-слой.
STUB_SCREENS = {
    "/cabinet/projects": lambda: _project_cards("Личный кабинет / проекты", "Совместные исследования",
                                                "Вступайте в проекты от имени выбранного образца.", bar=_kit_bar_empty()),
    "/cabinet/messages": lambda: _messages("Личный кабинет", "Переписка по выбранному образцу."),
    "/cabinet/settings": _client_settings,
    "/admin": _admin_overview,
    "/admin/members": _admin_members,
    "/admin/groups": _admin_groups,
    "/admin/clusters": _admin_clusters,
    "/admin/import": _bulk_import,
    "/admin/messages": lambda: _messages("Администратор", "Переписка с участниками проекта и базы."),
    "/master/accounts": _master_accounts,
    "/master/projects": lambda: _project_cards("Мастер / проекты", "Управление проектами",
                                               "Создание проектов, назначение администраторов и контроль активности.",
                                               _off_button("+ Создать проект", True)),
    "/master/science": _master_science,
    "/master/audit": _master_audit,
    "/master/messages": lambda: _messages("Мастер", "Переписка с участниками проекта и базы."),
}
SCREEN_TITLES = {h: t for items in NAV.values() for t, h in items}


def _kit_select(profiles, selected) -> str:
    options = "".join(f'<option value="{p.id}"{" selected" if p.id == selected.id else ""}>{esc(p.nickname or p.public_handle)} · '
                      f'{esc(panel_title(p))}</option>' for p in profiles)
    state = '<span class="pill green">Поиск включён</span>' if selected.searchable else '<span class="pill">Профиль закрыт</span>'
    return (f'<form class="contextbar" method="get"><label for="active-kit">Выбранный образец</label><select id="active-kit" name="kit">{options}</select>'
            f'<button id="kit-apply">Показать</button><div class="contextmeta">{state}</div></form>')


def _add_button() -> str:
    return '<a class="btn-link primary" href="/import">+ Добавить результат</a>'


def panel_title(profile) -> str:
    return panels.panel_label(profile.panel_code, profile.panel_basis)


def overview(profiles, selected, matches, pending: int, events) -> str:
    """Обзор пользователя. matches: None — профиль закрыт, иначе совпадения выбранного образца."""
    top = head("Личный кабинет / Y-ДНК", "Ваше генеалогическое исследование",
               "Совпадения, результаты и проекты — для выбранного образца.", _add_button())
    if not profiles:
        return top + panel("Мои результаты", '<div class="empty">Результатов пока нет. Добавьте первый результат.</div>')
    found = "—" if matches is None else len(matches)
    close = "—" if matches is None else sum(1 for m in matches if m.gd <= 3)
    link = f"/profiles/{selected.id}/matches"
    stats = "".join((stat("Совпадения в базе", found, "профиль закрыт" if matches is None else "среди открытых профилей", link),
                     stat("Близкие совпадения", close, "GD до 3", link),
                     stat("Мои результаты", len(profiles), "образца под управлением", "/me"),
                     stat("Запросы на связь", pending, "ожидают решения", "/me")))
    rows = [f'<tr><td><span class="name">{esc(m.nickname or m.handle)}</span><div class="name-sub mono">{esc(m.handle)}</div></td>'
            f'<td><span class="gd {"far" if m.gd > 4 else "mid" if m.gd > 2 else ""}">GD {m.gd}</span></td>'
            f'<td><b>{m.compared}</b> позиций<div class="name-sub">из {m.panel_overlap} общих</div></td></tr>' for m in (matches or [])[:3]]
    empty = ("Профиль закрыт: включите поиск на странице профиля." if matches is None else "Совпадений пока нет.")
    shown = "" if len(matches or []) <= 3 else " · показаны первые 3"
    left = ('<section class="panel"><div class="panel-title"><h2>Совпадения по Y-ДНК</h2>'
            f'<a class="quiet" href="{link}">Все совпадения →</a></div>'
            f'<div class="tabs" aria-label="Источники совпадений"><a class="active" href="{link}">Профили участников '
            f'<span class="pill">{len(matches or [])}</span></a><a href="{link}#science">Научные данные</a></div>'
            + table(("Участник", "Дистанция", "Сопоставлено"), rows, empty)
            + f'<div class="tablefoot"><span>{len(matches or [])} совпадений{shown}</span><span>GD — шаги различий</span></div></section>'
            + panel("География совпадений", '<div class="empty">Страна предка в профилях пока не хранится.</div>'))
    ancestor = esc(selected.ancestor_text) or "Не указан"
    timeline = "".join(f'<div class="timeline-row"><i class="event-dot"></i><div>{esc(label)}<small>{esc(when)}</small></div></div>' for label, when in events)
    aside = (panel("Моё исследование", f'<div class="mini-label">Ближайший известный предок</div><h3>{ancestor}</h3>'
                                       f'<div class="mini-label form-note">Панель</div><h3>{esc(panel_title(selected))}</h3>'
                                       f'<div class="settings-row"><small>Карточку можно дополнить</small><a class="quiet" href="/profiles/{selected.id}">Изменить</a></div>')
             + panel("Последние события", timeline or '<div class="empty">Событий пока нет.</div>'))
    return top + _kit_select(profiles, selected) + f'<div class="stats">{stats}</div><div class="columns"><div>{left}</div><aside>{aside}</aside></div>'


def matches_page(profiles) -> str:
    top = head("Личный кабинет / совпадения", "Генетические совпадения", "Отдельный поиск среди участников и популяционных научных выборок.")
    rows = [f'<tr><td><span class="name">{esc(p.nickname or p.public_handle)}</span><div class="name-sub mono">{esc(p.public_handle)}</div></td>'
            f'<td>{esc(panel_title(p))}</td><td><span class="pill {"green" if p.searchable else ""}">{"Поиск включён" if p.searchable else "Закрыт"}</span></td>'
            f'<td>{f"""<a href="/profiles/{p.id}/matches">Участники и научные данные →</a>""" if p.searchable else f"""<a href="/profiles/{p.id}">Включить поиск</a>"""}</td></tr>'
            for p in profiles]
    return (top + panel("Мои образцы", table(("Образец", "Панель", "Поиск", ""), rows, "Результатов пока нет."))
            + panel("Разовый поиск без сохранения",
                    '<div class="settings-row"><div><p>Участники</p><small>Профили, владельцы которых разрешили поиск.</small></div><a href="/">Поиск по профилям →</a></div>'
                    '<div class="settings-row"><div><p>Научные данные</p><small>Локальный тестовый каталог.</small></div><a href="/compare">Сравнение →</a></div>'))


def backups_page(state: dict, files, csrf: str) -> str:
    action = (f'<form method="post" action="/master/backup"><input type="hidden" name="csrf" value="{esc(csrf)}">'
              '<input type="hidden" name="back" value="backups"><button class="primary">Создать копию</button></form>')
    rows = [f'<tr><td><b class="mono">{esc(name)}</b></td><td>{esc(when)}</td><td>{esc(size)}</td></tr>' for name, when, size in files]
    return (head("Мастер / обслуживание", "Резервные копии", "Снимки базы пользователей и срок их хранения.", action)
            + f'<div class="info">Копия включает только базу пользователей. Срок при очистке: {state["keep_days"]:g} дн. '
            'По расписанию приложение копии не создаёт; скачивание и восстановление пока не сделаны.</div>'
            + panel("Доступные копии", table(("Резервная копия", "Создана", "Размер"), rows, "Копий ещё нет.")))
