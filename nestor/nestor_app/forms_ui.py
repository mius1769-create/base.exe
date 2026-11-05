"""Формы по макету «Генопоиск», дизайн 02: вход, регистрация, новый результат, импорт, карточка профиля.

Только разметка. Поля, согласия и условия хранения те же, что и раньше: проверки остаются в ядре.
"""

from __future__ import annotations

import json

from .cabinet_ui import esc, head, panel, stat, table


def _field(label: str, control: str, full: bool = False) -> str:
    return f'<div class="field{" full" if full else ""}"><label>{esc(label)}{control}</label></div>'


def _csrf(token: str) -> str:
    return f'<input type="hidden" name="csrf" value="{esc(token)}">'


def _choices(labels: dict, current: str | None = None) -> str:
    return '<div class="choices">' + "".join(
        f'<label><input type="radio" name="consent_basis" value="{k}" required{" checked" if k == current else ""}> {esc(v)}</label>'
        for k, v in labels.items()) + "</div>"


def _upload_tabs(active: str) -> str:
    items = (("/import", "Из файла"), ("/profiles/new", "Вручную"))
    return '<div class="tabs page-tabs">' + "".join(
        f'<a{" class=active" if h == active else ""} href="{h}">{t}</a>' for h, t in items) + "</div>"


def login_page() -> str:
    return ('<div class="auth"><div class="eyebrow">Личный кабинет</div><h1>Вход</h1><p class="sub">Аккаунт хранится только на этом компьютере.</p>'
            + panel("Данные для входа", '<form method="post" action="/login" class="forms one">'
                    + _field("Email", '<input type="email" name="email" required autocomplete="username">', True)
                    + _field("Пароль", '<input type="password" name="password" required autocomplete="current-password">', True)
                    + '<div class="form-actions full"><button class="primary">Войти</button></div></form>')
            + '<p class="caption">Нет аккаунта? <a href="/register">Регистрация</a></p></div>')


def register_page() -> str:
    return ('<div class="auth"><div class="eyebrow">Личный кабинет</div><h1>Регистрация</h1><p class="sub">Аккаунт хранится только на этом компьютере.</p>'
            + panel("Новый аккаунт", '<form method="post" action="/register" class="forms one">'
                    + _field("Email (виден только вам, в поиске не показывается)", '<input type="email" name="email" required autocomplete="username">', True)
                    + _field("Пароль (не короче 8 символов)", '<input type="password" name="password" required minlength="8" autocomplete="new-password">', True)
                    + _field("Псевдоним для запросов на связь (необязательно)", '<input type="text" name="display_name" maxlength="60">', True)
                    + '<div class="form-actions full"><button class="primary">Создать аккаунт</button></div></form>')
            + '<p class="caption">Восстановления пароля нет: запишите его. Уже есть аккаунт? <a href="/login">Войти</a></p></div>')


def _str_cells(prefix: str, cells, values: dict) -> str:
    out = []
    for c in cells:
        field = f'{prefix}{c["field"]}'
        out.append(f'<div class="locus" data-panels="{esc(" ".join(c["panels"]))}"><label for="{esc(field)}">{esc(c["label"])}</label>'
                   f'<input id="{esc(field)}" name="{esc(field)}" data-field="{esc(c["field"])}" value="{esc(values.get(field, ""))}" '
                   'inputmode="decimal" autocomplete="off" maxlength="16"></div>')
    return "".join(out)


def _str_section(window: dict, values: dict) -> str:
    """Окно STR: своя панель, свой список значений и своя сетка окошек."""
    orders_json = esc(json.dumps(window["orders"], ensure_ascii=False))
    return (f'<section class="panel str-section" id="{window["id"]}"><div class="panel-title"><h2>{esc(window["title"])}</h2><small class="str-count"></small></div>'
            f'<div class="panel-body"><p class="sub">{esc(window["note"])}</p><div class="forms form-note">'
            + _field("Тип теста", window["select"], True) + '</div>'
            '<p class="sub form-note">Список значений: через пробел по порядку выбранной панели (<code>0</code> — нет значения) или строки <code>МАРКЕР=значение</code>.</p>'
            f'<textarea name="{window["text_name"]}" class="str-text form-note" rows="3" aria-label="Список значений: {esc(window["title"])}">{esc(values.get(window["text_name"], ""))}</textarea>'
            '<div class="actions form-note"><button type="button" class="str-load" hidden>Загрузить в окошки</button>'
            '<button type="button" class="str-clear quiet" hidden>Очистить окошки</button><small class="str-message" role="status"></small></div>'
            f'<div class="loci str-grid form-note" data-orders="{orders_json}">{_str_cells(window["prefix"], window["cells"], values)}</div></div></section>')


def new_profile_page(csrf: str, nickname_vis: str, ancestor_vis: str, basis_labels: dict, *,
                     windows, values: dict | None = None, error: str = "") -> str:
    """Новый результат вручную: два окна STR. values — введённое ранее, если сохранить не удалось."""
    values = values or {}
    card = ('<div class="forms">'
            + _field("Kit ID (необязательно; виден только вам)", f'<input type="text" name="kit_id" maxlength="60" value="{esc(values.get("kit_id", ""))}">', True)
            + _field("Никнейм владельца (необязательно)", f'<input type="text" name="nickname" maxlength="200" value="{esc(values.get("nickname", ""))}">')
            + _field("Видимость никнейма", nickname_vis)
            + _field("Дальний предок (необязательно)", f'<input type="text" name="ancestor_text" maxlength="200" value="{esc(values.get("ancestor_text", ""))}">')
            + _field("Видимость предка", ancestor_vis) + "</div>")
    guide = ('<div class="info">Заполните одно окно или оба. Каждое заполненное окно сохранится <b>отдельным результатом</b> со своей панелью: '
             'у Генопоиска и FTDNA одинаковые названия локусов могут быть записаны в разных шкалах, поэтому значения не смешиваются.</div>'
             '<p class="caption">Пустое окошко — нет значения. No call сохраняется как отсутствие измерения, а не как ноль. Для мультикопийного локуса заполните все его '
             'окошки, иначе он сохранится как нераспознанный.</p>')
    consent = (f'<p><b>Чей это тест?</b></p>{_choices(basis_labels, values.get("consent_basis"))}'
               f'<label class="choice"><input type="checkbox" name="consent_confirmed" value="1" required{" checked" if values.get("consent_confirmed") == "1" else ""}> '
               'Подтверждаю, что имею право загрузить этот профиль.</label>'
               '<p class="caption">Профиль будет создан <b>закрытым</b> и не будет участвовать в поиске, пока вы сами не включите сопоставление.</p>')
    alert = f'<div class="info warm" id="new-profile-error" role="alert">{esc(error)}</div>' if error else ""
    return (head("Личный кабинет / загрузка", "Новый результат", "Карточка образца, загрузка файла и проверка локусов.") + _upload_tabs("/profiles/new") + alert
            + f'<form method="post" action="/profiles/new">{_csrf(csrf)}<div class="grid2">{panel("Карточка образца", card)}{panel("Как заполнять", guide)}</div>'
            + "".join(_str_section(w, values) for w in windows)
            + panel("Право на загрузку", consent) + '<div class="form-actions"><button class="primary">Сохранить результат</button></div></form>')


def import_page(csrf: str, panel_select: str, max_mb: int, max_rows: int) -> str:
    template = ('<div class="forms">' + _field("Тип теста / панель", panel_select, True)
                + '<p class="caption full">Выбранная панель: локусы файла вне неё — ошибка листа. «Определить автоматически» — по заголовкам, '
                  'только при надёжном совпадении; иначе — пользовательский набор.</p></div>')
    upload = ('<p class="sub">Файл CSV (разделитель <code>;</code>, <code>,</code> или TAB) или XLSX (все листы). '
              f'Не более {max_mb} МБ и {max_rows} строк.</p>'
              '<input type="file" name="file" accept=".csv,.txt,.tsv,.xlsx" required class="form-note" aria-label="Выбрать файл результатов">'
              '<div class="info form-note">Профили создаются закрытыми; записи не объединяются.</div>')
    storage = ('<p class="caption">До вашего решения файл лежит во временной папке приложения (не в базе и не в её резервных копиях) и автоматически '
               'удаляется через сутки, при отмене или после сохранения. После подтверждения в базе остаются только выбранные строки (исходные ячейки), '
               'имя файла, лист, номера строк и SHA-256; полный файл — только если вы отдельно попросите его сохранить. Удаление относится к файлам '
               'приложения: стирание с диска (SSD), из снимков системы и ваших собственных копий приложение не гарантирует.</p>')
    return (head("Личный кабинет / загрузка", "Новый результат", "Карточка образца, загрузка файла и проверка локусов.") + _upload_tabs("/import")
            + f'<form method="post" action="/import" enctype="multipart/form-data">{_csrf(csrf)}'
            + f'<div class="grid2">{panel("Панель", template)}{panel("Файл с результатами", upload)}</div>' + storage
            + '<div class="form-actions"><button class="primary">Загрузить и проверить</button></div></form>')


def import_preview_page(prev, summ: dict, upload_id: str, csrf: str, sheet_rows: str, rows: str, basis_labels: dict) -> str:
    stats = "".join((stat("Профилей", summ["records"], "в файле"), stat("Можно сохранить", summ["savable"], "без ошибок"),
                     stat("С пропусками", summ["with_missing"], f'нераспознанных: {summ["with_invalid"]}'),
                     stat("С пометками", summ["flagged"], "повторы / совпадения")))
    sheets = ('<div class="tablewrap"><table><thead><tr><th>Лист</th><th>Панель</th><th>Строка заголовков</th><th>Профилей</th><th>Пустых строк</th><th>Ошибка</th></tr></thead>'
              f'<tbody>{sheet_rows}</tbody></table></div><p class="caption">Повторы и совпадения только помечены: записи не объединяются, решаете вы.</p>')
    records = ('<div class="tablewrap"><table><thead><tr><th></th><th>Лист:строка</th><th>ID</th><th>Значения</th><th>Без значения</th><th>Не распознано</th>'
               f'<th>Пометки</th><th>Ошибка</th><th>Исходные ячейки</th></tr></thead><tbody>{rows}</tbody></table></div>')
    consent = (f'<p><b>Чьи это тесты?</b></p>{_choices(basis_labels)}'
               '<label class="choice"><input type="checkbox" name="consent_confirmed" value="1" required> Подтверждаю право загрузить выбранные профили.</label>'
               '<p class="caption">Профили будут созданы закрытыми; ID из файла сохранится как kit ID (виден только вам). После сохранения остаются только исходные '
               'ячейки выбранных строк, имя файла, лист, номера строк и SHA-256 файла; сам файл удаляется.</p>'
               '<label class="choice form-note"><input type="checkbox" name="keep_original" value="1"> Дополнительно сохранить полный исходный файл для локального аудита (необязательно).</label>'
               '<div class="info warm form-note">Внимание: вместе с файлом сохранятся <b>все</b> его строки и листы, включая профили, которые вы не выбрали. Из активной базы файл '
               'удаляется вместе с последним сохранённым из него профилем; в уже сделанных резервных копиях базы он остаётся до их очистки (срок хранения копий '
               'применяется, когда запускается очистка, и не является гарантированным максимумом).</div>')
    return (head("Личный кабинет / загрузка", "Проверка перед сохранением", f"Файл {prev.filename}, {prev.size} байт.")
            + f'<div class="stats">{stats}</div><p class="caption">SHA-256 <code>{esc(prev.sha256)}</code></p>'
            + panel("Листы файла", sheets)
            + f'<form method="post" action="/import/{upload_id}/commit" id="commit-form">{_csrf(csrf)}' + panel("Профили", records) + panel("Право на загрузку", consent) + "</form>"
            + f'<div class="form-actions"><form method="post" action="/import/{upload_id}/discard">{_csrf(csrf)}<button>Отменить и удалить файл</button></form>'
              '<button class="primary" form="commit-form">Сохранить выбранные</button></div>')


def profile_page(p, pid: int, csrf: str, *, panel_text: str, basis_text: str, best: str | None, cells, observed: int,
                 nickname_vis: str, ancestor_vis: str, source: str) -> str:
    state = "поиск включён" if p.searchable else "закрыт — не участвует в поиске"
    action = (f'<a class="btn-link primary" href="/profiles/{pid}/matches">Совпадения</a>' if p.searchable else "")
    toggle = (f'<form method="post" action="/profiles/{pid}/searchable">{_csrf(csrf)}<input type="hidden" name="enabled" value="{0 if p.searchable else 1}">'
              f'<button>{"Выключить сопоставление" if p.searchable else "Включить сопоставление"}</button></form>')
    covered = f" · полностью покрыта: {best}" if best else ""
    card = (f'<div class="settings-row"><div><p>Статус</p><small><b>{esc(state)}</b></small></div>{toggle}</div>'
            f'<div class="settings-row"><p>Kit ID (только для вас)</p><small>{esc(p.kit_id_private) or "—"}</small></div>'
            f'<div class="settings-row"><p>Основание загрузки</p><small>{esc(basis_text)}</small></div>'
            f'<div class="settings-row"><p>Панель</p><small>{esc(panel_text)}{esc(covered)}</small></div>'
            f'<div class="settings-row"><p>Данные профиля</p><a class="quiet" href="/profiles/{pid}/export.json">Экспорт JSON</a></div>')
    visibility = (f'<form method="post" action="/profiles/{pid}/visibility" class="forms">{_csrf(csrf)}'
                  + _field("Никнейм", f'<input type="text" name="nickname" value="{esc(p.nickname)}" maxlength="200">')
                  + _field("Кому виден", nickname_vis)
                  + _field("Дальний предок", f'<input type="text" name="ancestor_text" value="{esc(p.ancestor_text)}" maxlength="200">')
                  + _field("Кому виден", ancestor_vis)
                  + '<div class="form-actions full"><button class="primary">Сохранить</button></div></form>')
    loci = '<div class="loci">' + "".join(
        f'<div class="locus{" review" if status != "ok" else ""}"><label>{esc(name)}</label><span class="mono">{text}</span></div>' for name, text, status in cells) + "</div>"
    delete = (f'<form method="post" action="/profiles/{pid}/delete">{_csrf(csrf)}<label class="choice"><input type="checkbox" name="confirm" value="1" required> '
              'Удалить профиль, маркеры, журнал согласий и запросы на связь без возможности восстановления</label>'
              '<div class="form-actions"><button class="danger">Удалить</button></div></form>')
    return (head("Личный кабинет / результаты", f"Профиль {p.public_handle}", "Карточка образца, видимость полей и значения маркеров.", action)
            + f'<div class="grid2">{panel("Карточка образца", card)}{panel("Видимость необязательных полей", visibility)}</div>'
            + source + panel(f"Позиции профиля: {len(cells)}, со значением {observed}", loci) + panel("Удаление", delete))


def me_tables(profile_rows, incoming, outgoing) -> str:
    return (panel("Мои профили", table(("Профиль", "Маркеров", "Статус", "Создан"), profile_rows, "Профилей пока нет.")
                  + '<p class="caption"><a href="/profiles/new">Ввести профиль вручную</a> · <a href="/import">Импорт из файла CSV / XLSX</a></p>')
            + panel("Входящие запросы на связь", table(("Профиль", "От", "Сообщение", "Статус", ""), incoming, "Нет запросов."))
            + panel("Мои запросы", table(("Профиль", "Статус", "Ответ владельца"), outgoing, "Нет запросов.")))
