"""Страница «Сравнение с научными данными»: один профиль → локальный тестовый каталог.

Компоновка — по макету «Генетические совпадения» (дизайн 02, 15.10.2026): карточка
ввода, строка фильтров, таблица «Найденные совпадения» с бейджем GD, раскрытием
«Различия» и «Источник». Без JavaScript (политика страницы запрещает скрипты):
раскрытие — элементами <details>. Профиль не сохраняется.
"""

from __future__ import annotations

import html

from . import markers as mk
from . import panels

GD_CHOICES = list(range(0, 11))
MIN_COMMON_CHOICES = [6, 8, 10, 12, 15, 18, 20, 25, 30, 37, 50, 67]
KINDS = [("", "все записи"), ("individual", "индивидуальные"), ("aggregated", "агрегаты (N)")]
DEFAULTS = {"max_gd": 4, "min_common": 12}


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _select(name: str, options, current) -> str:
    return (f'<select name="{name}">' + "".join(
        f'<option value="{esc(v)}"{" selected" if str(v) == str(current) else ""}>{esc(t)}</option>'
        for v, t in options) + "</select>")


def gd_class(gd: int) -> str:
    return "gd g-near" if gd <= 1 else ("gd g-mid" if gd <= 3 else "gd g-far")


def form_html(f: dict, facets: dict | None, panel_select: str, error: str = "") -> str:
    countries = [("", "все страны")] + [(c, f"{c} · {n}") for c, n in (facets or {}).get("countries", [])]
    sources = [("", "все источники")] + [(s, f"{t[:70]} · {n}") for s, t, n in (facets or {}).get("sources", [])]
    err = f'<p class="err" id="compare-error">{esc(error)}</p>' if error else ""
    return f"""<form method="post" action="/compare" class="card compare-form">
<div class="eyebrow">Ваш профиль</div>
<textarea name="markers" required placeholder="Например, 111 чисел из FTDNA / Strelka через пробел (0 — нет значения), строки DYS393=13 или таблица «заголовки + значения»">{esc(f.get("markers", ""))}</textarea>
<div class="row">
<label>Панель{panel_select}</label>
<span class="muted hint">Для 111 чисел подряд выберите <b>FTDNA Y111</b> (порядок FTDNA; так же выгружает Strelka).
Значения со статусом REVIEW лучше заменить на <code>0</code> — они не будут сравниваться.</span>
</div>{err}
<div class="filters">
<label>Найти в совпадениях<input type="text" name="text" value="{esc(f.get("text", ""))}" placeholder="популяция, субклад, источник, ID"></label>
<label>Макс. GD{_select("max_gd", [(g, g) for g in GD_CHOICES], f.get("max_gd", DEFAULTS["max_gd"]))}</label>
<label>Общих позиций от{_select("min_common", [(m, m) for m in MIN_COMMON_CHOICES], f.get("min_common", DEFAULTS["min_common"]))}</label>
<label>Страна / популяция{_select("country", countries, f.get("country", ""))}</label>
<label>Источник{_select("source", sources, f.get("source", ""))}</label>
<label>Тип записи{_select("kind", KINDS, f.get("kind", ""))}</label>
<label>Исключить локусы<input type="text" name="excluded" value="{esc(f.get("excluded", ""))}" placeholder="DYS464, CDY"></label>
<button class="primary">Сравнить</button>
</div>
</form>"""


def _steps(s) -> str:
    if not isinstance(s, int):
        return s
    return f"{s} шаг" if s % 10 == 1 and s % 100 != 11 else (
        f"{s} шага" if s % 10 in (2, 3, 4) and s % 100 not in (12, 13, 14) else f"{s} шагов")


def _differences(m) -> str:
    rows = "".join(f"<tr><td>{esc(locus)}</td><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(_steps(s))}</td></tr>"
                   for locus, a, b, s in m.differences)
    table = (f'<table class="mini"><tr><th>Локус</th><th>Ваш профиль</th><th>Запись</th><th>Вклад</th></tr>{rows}</table>'
             if rows else '<p class="muted">Все сопоставленные позиции совпадают.</p>')
    nc = "; ".join(f"{k}: {v}" for k, v in m.not_compared.items())
    return (f"<details><summary>Различия</summary><div class=\"drop\">{table}"
            f"<p class=\"muted\">Сопоставлено {m.compared} из {m.panel_overlap} общих позиций."
            f"{' Не вошли в GD — ' + esc(nc) + '.' if nc else ''} Опубликованные значения источника показаны как есть; "
            "шкалы источников не откалиброваны, GD предварительный.</p></div></details>")


def _source(m) -> str:
    title = m.source_title or m.source_id
    rows = [("Публикация", m.publication), ("DOI", m.doi), ("Лицензия (как в источнике)", m.license),
            ("Статус проверки", m.verification_status), ("Право на повторное использование", m.reuse_note),
            ("Качество записи", "; ".join(f"{k}: {v}" for k, v in m.quality)),
            ("Пометки", "; ".join(m.flags))]
    body = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows if v)
    return (f'<details><summary class="btn">Источник ↗</summary><div class="drop"><p><b>{esc(title)}</b>'
            f'<br><span class="muted">{esc(m.source_id)}</span></p><table class="mini kv">{body}</table></div></details>')


def results_html(matches, summary: dict, query: dict, code, basis, f: dict) -> str:
    observed = sum(1 for v in query.values() if mk.is_observed(v))
    missing = sum(1 for v in query.values() if v is None)
    invalid = sum(1 for v in query.values() if isinstance(v, mk.Invalid))
    total = summary["total"]
    accepted = (f'<p id="query-accepted" class="accepted">Профиль принят: {esc(panels.panel_label(code, basis))}; '
                f'позиций со значением {observed}, без значения {missing}, не распознано {invalid}.</p>')
    if not matches:
        body = (f'<p class="empty" id="no-matches">Совпадений при GD ≤ {esc(f["max_gd"])} и не меньше '
                f'{esc(f["min_common"])} общих позиций нет. Попробуйте увеличить «Макс. GD» или уменьшить '
                '«Общих позиций от»: научные записи часто короче Y111.</p>')
    else:
        rows = []
        for m in matches:
            kind = ("индивидуальная запись" if m.record_kind != "aggregated"
                    else f"агрегированное наблюдение, N={m.observed_n}")
            place = " · ".join(x for x in (m.country, m.population) if x and x != m.country) or (m.country or "—")
            rows.append(
                f'<tr><td><b>{esc(m.sample_id)}</b><div class="sub">{esc(place)}</div>'
                f'<span class="tag{" tag-agg" if m.record_kind == "aggregated" else ""}">{esc(kind)}</span></td>'
                f'<td><span class="{gd_class(m.gd)}">GD {m.gd}</span><div class="sub">предварительно</div>{_differences(m)}</td>'
                f'<td><b>{m.compared}</b> позиций<div class="sub">из {m.panel_overlap} общих</div></td>'
                f'<td>{esc(m.haplogroup) or "Не указан"}<div><span class="tag">{esc(m.verification_status.split(" (")[0])}</span></div></td>'
                f'<td>{_source(m)}</td></tr>')
        more = f" · показаны первые {len(matches)}" if total > len(matches) else ""
        body = ('<div class="scroll"><table class="results"><tr><th>Образец / популяция</th><th>Дистанция</th><th>Сопоставлено</th>'
                '<th>Субклад / статус</th><th></th></tr>' + "".join(rows) + "</table></div>"
                f'<div class="foot"><span id="found">Найдено {total}: индивидуальных записей {summary["individual"]}, '
                f'агрегированных наблюдений {summary["aggregated"]} (сумма N = {summary["aggregated_n"]}){more}; '
                'порядок — по GD, затем по числу сопоставленных позиций</span><span>GD — шаги различий</span></div>')
    return (f'<div class="card flush"><div class="card-head"><h2>Найденные совпадения</h2>'
            f'<span class="pill warn-pill">ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ</span></div>{accepted}'
            '<p class="note">Непроверенные данные: источники не допущены в справочник NeSToR, право на повторное '
            'использование не подтверждено, шкалы аллелей не откалиброваны — все GD предварительные. Агрегированные '
            'наблюдения — гаплотипы с численностью N, а не отдельные люди.</p>' + body + "</div>")


def catalog_off_html(cmd: str) -> str:
    return (f'<div class="card"><h2>Научный каталог не включён</h2><p>Сравнивать пока не с чем. Соберите и включите '
            f'локальный тестовый каталог из исходных файлов:</p><pre>{esc(cmd)} build-release --release '
            f'"C:\\Data\\Genopoisk_expert_linux_2026-10-14.tar.gz" --candidate "C:\\Data\\Nestor_scientific_YSTR.db" '
            '--enable</pre><p class="muted">Затем перезапустите NeSToR. Каталог только для локального тестирования и '
            'никуда не отправляется.</p></div>')


FOOTNOTE = ('<p class="footnote">Общие позиции — фактически сопоставленные значения, а не номинальный размер панели. '
            'Полное совпадение на коротком наборе не доказывает недавнее родство. GD не равен числу поколений.</p>')
