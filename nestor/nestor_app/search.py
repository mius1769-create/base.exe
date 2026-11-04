"""Поиск совпадений по пользовательским профилям.

Гостевой поиск (без аккаунта):
  1. загруженный гостем профиль никуда не сохраняется;
  2. кандидаты — только профили с разрешённым поиском (searchable = 1);
  3. подходящие совпадения = GD <= max_gd и compared >= min_common, где compared —
     позиции, вошедшие в численный GD (без исключённых пользователем, без значения /
     нераспознанных, с разным числом копий и с дробными различиями — см. gd.py);
  4. из ВСЕГО списка подходящих выбирается floor(n * 20%) совпадений случайно,
     но детерминированно: ключ = HMAC-SHA256(секрет сервера, канонический
     запрос), вес совпадения = HMAC-SHA256(ключ, public_handle); берутся k
     совпадений с наименьшим весом. Повтор того же запроса даёт ту же выборку;
  5. выбранные сортируются по GD (затем по числу сравненных локусов, затем по handle).

Поиск владельца: только по собственному профилю с включённым сопоставлением
(взаимность), возвращает полный список совпадений среди открытых профилей
других владельцев.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import sqlite3
from dataclasses import dataclass

from . import markers as mk
from . import panels
from . import profiles as pr
from .config import DEFAULT_MAX_GD, DEFAULT_MIN_COMMON, GUEST_FRACTION, MAX_ALLOWED_GD
from .gd import gd_view, genetic_distance, normalize_excluded

SAMPLING_VERSION = "guest-v1"

TAB_ALL = "all"
PANEL_TABS = ("FTDNA_Y12", "FTDNA_Y25", "FTDNA_Y37", "FTDNA_Y67", "FTDNA_Y111", "GENOPOISK_Y37", "GENOPOISK_Y50")
PANEL_MIN_SHARE = 0.9   # доля позиций панели, которая должна войти в GD: у реальных профилей бывают пропуски


class SearchError(ValueError):
    pass


@dataclass(frozen=True)
class PublicMatch:
    """Строка результата. Белый список полей: никаких kit ID, email, id из базы."""

    handle: str
    gd: int
    compared: int              # позиции, вошедшие в численный GD (по ним — порог min_common)
    nickname: str | None
    ancestor: str | None
    preliminary: bool = False  # есть дробные различия без перевода в шаги (T18)
    panel_overlap: int = 0     # общие позиции панелей
    missing_or_invalid: int = 0       # нет значения / не распознано (вне GD)
    copy_count_differences: int = 0   # разное число копий (вне GD)
    allele_differences: int = 0       # дробные различия без перевода в шаги (вне GD)
    user_excluded: int = 0            # исключены пользователем (вне GD)


@dataclass(frozen=True)
class GuestResult:
    matches: list[PublicMatch]
    shown_fraction: float


def _check_params(max_gd: int, min_common: int) -> None:
    if not (0 <= max_gd <= MAX_ALLOWED_GD):
        raise SearchError(f"порог GD должен быть от 0 до {MAX_ALLOWED_GD}")
    if min_common < 1:
        raise SearchError("минимум общих маркеров должен быть не меньше 1")


def _public(row, res, viewer) -> PublicMatch:
    return PublicMatch(
        handle=row["public_handle"], gd=res.gd, compared=res.compared,
        nickname=pr.visible_field(row["nickname"], row["nickname_visibility"], viewer),
        ancestor=pr.visible_field(row["ancestor_text"], row["ancestor_visibility"], viewer),
        preliminary=res.preliminary, panel_overlap=res.panel_overlap,
        missing_or_invalid=len(res.missing_or_invalid),
        copy_count_differences=len(res.copy_count_differences),
        allele_differences=len(res.allele_differences),
        user_excluded=len(res.user_excluded),
    )


def _candidates(conn, query, max_gd, min_common, viewer, exclude_owner=None, excluded_loci=()):
    out: list[PublicMatch] = []
    for row, markers in pr.iter_searchable(conn, exclude_owner=exclude_owner):
        res = genetic_distance(query, markers, excluded=excluded_loci)
        if res.compared >= min_common and res.gd <= max_gd:
            out.append(_public(row, res, viewer))
    return out


def _panel_positions(code: str) -> set[str]:
    names = set(panels.get_panel(code).marker_names)
    if "DYS389II" in names:  # T16: в GD вместо DYS389II идёт DYS389B
        names.discard("DYS389II")
        names.add("DYS389B")
    return names


def panel_tabs(conn, query, *, max_gd: int, viewer: str, exclude_owner=None, excluded_loci=(),
               only_handles=None) -> dict[str, list[PublicMatch]]:
    """Совпадения по вкладкам панелей: GD считается только по локусам панели.

    На вкладку попадает профиль, у которого сравнено не меньше PANEL_MIN_SHARE позиций панели;
    общий порог «сравнено» здесь не действует, панель сама задаёт глубину. only_handles для гостя:
    вкладки показывают только его основную выборку, иначе переключением можно увидеть больше 20%.
    """
    qview = gd_view(query)[0]
    loci = {code: _panel_positions(code) for code in PANEL_TABS}
    out: dict[str, list[PublicMatch]] = {code: [] for code in PANEL_TABS}
    for row, markers in pr.iter_searchable(conn, exclude_owner=exclude_owner):
        if only_handles is not None and row["public_handle"] not in only_handles:
            continue
        mview = gd_view(markers)[0]
        for code, names in loci.items():
            res = genetic_distance({k: v for k, v in qview.items() if k in names},
                                   {k: v for k, v in mview.items() if k in names}, excluded=excluded_loci)
            if res.compared >= math.ceil(PANEL_MIN_SHARE * len(names)) and res.gd <= max_gd:
                out[code].append(_public(row, res, viewer))
    return {code: _sort(v) for code, v in out.items()}


def default_panel_tab(tabs: dict[str, list[PublicMatch]]) -> str:
    """Самая глубокая панель с результатами, иначе общая вкладка."""
    filled = [c for c, v in tabs.items() if v]
    return max(filled, key=lambda c: len(_panel_positions(c))) if filled else TAB_ALL


def _sort(matches: list[PublicMatch]) -> list[PublicMatch]:
    return sorted(matches, key=lambda m: (m.gd, -m.compared, m.handle))


def guest_query_key(secret: bytes, query: dict, max_gd: int, min_common: int, excluded_loci=()) -> bytes:
    canon = f"{SAMPLING_VERSION}|gd<={max_gd}|common>={min_common}|{mk.canonical_string(query)}"
    excl = sorted(normalize_excluded(excluded_loci))
    if excl:  # без исключений ключ совпадает с guest-v1 (переносимый тест-вектор не меняется)
        canon += "|excluded=" + ",".join(excl)
    return hmac.new(secret, canon.encode(), hashlib.sha256).digest()


def guest_sample_size(n: int, fraction: float = GUEST_FRACTION) -> int:
    return math.floor(n * fraction + 1e-9)


def guest_sample(matches: list[PublicMatch], key: bytes, fraction: float = GUEST_FRACTION) -> list[PublicMatch]:
    k = guest_sample_size(len(matches), fraction)
    weighted = sorted(
        matches, key=lambda m: hmac.new(key, m.handle.encode(), hashlib.sha256).digest()
    )
    return _sort(weighted[:k])


def guest_search(
    conn: sqlite3.Connection,
    secret: bytes,
    query: dict[str, tuple[float, ...]],
    *,
    max_gd: int = DEFAULT_MAX_GD,
    min_common: int = DEFAULT_MIN_COMMON,
    excluded_loci=(),
) -> GuestResult:
    """Гостевой поиск. Ничего не пишет в базу."""
    _check_params(max_gd, min_common)
    if not any(mk.is_observed(v) for v in query.values()):
        raise SearchError("пустой профиль")
    matches = _candidates(conn, query, max_gd, min_common, viewer="guest", excluded_loci=excluded_loci)
    key = guest_query_key(secret, query, max_gd, min_common, excluded_loci)
    return GuestResult(matches=guest_sample(matches, key), shown_fraction=GUEST_FRACTION)


def owner_search(
    conn: sqlite3.Connection,
    owner_user_id: int,
    profile_id: int,
    *,
    max_gd: int = DEFAULT_MAX_GD,
    min_common: int = DEFAULT_MIN_COMMON,
    excluded_loci=(),
) -> list[PublicMatch]:
    _check_params(max_gd, min_common)
    own = pr.get_owned(conn, owner_user_id, profile_id)
    if not own.searchable:
        raise SearchError(
            "профиль закрыт: включите сопоставление для этого профиля, чтобы искать совпадения "
            "(закрытые профили не участвуют в поиске ни с какой стороны)"
        )
    return _sort(_candidates(conn, own.markers, max_gd, min_common, viewer="registered",
                             exclude_owner=owner_user_id, excluded_loci=excluded_loci))
