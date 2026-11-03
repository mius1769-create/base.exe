"""Поиск совпадений по пользовательским профилям.

Гостевой поиск (без аккаунта):
  1. загруженный гостем профиль никуда не сохраняется;
  2. кандидаты — только профили с разрешённым поиском (searchable = 1);
  3. подходящие совпадения = GD <= max_gd и фактически сравненных локусов
     (compared, без локусов с разным числом копий и дробными различиями) >= min_common;
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
from . import profiles as pr
from .config import DEFAULT_MAX_GD, DEFAULT_MIN_COMMON, GUEST_FRACTION, MAX_ALLOWED_GD
from .gd import genetic_distance

SAMPLING_VERSION = "guest-v1"


class SearchError(ValueError):
    pass


@dataclass(frozen=True)
class PublicMatch:
    """Строка результата. Белый список полей: никаких kit ID, email, id из базы."""

    handle: str
    gd: int
    compared: int              # локусы, фактически вошедшие в GD (по ним — порог min_common)
    nickname: str | None
    ancestor: str | None
    preliminary: bool = False  # есть дробные различия без перевода в шаги (T18)
    overlap: int = 0           # локусы в пересечении профилей
    copy_count_differences: int = 0   # локусы с разным числом копий (вне GD и compared)
    fractional_differences: int = 0   # локусы с неподтверждёнными дробными различиями (вне GD и compared)


@dataclass(frozen=True)
class GuestResult:
    matches: list[PublicMatch]
    shown_fraction: float


def _check_params(max_gd: int, min_common: int) -> None:
    if not (0 <= max_gd <= MAX_ALLOWED_GD):
        raise SearchError(f"порог GD должен быть от 0 до {MAX_ALLOWED_GD}")
    if min_common < 1:
        raise SearchError("минимум общих маркеров должен быть не меньше 1")


def _candidates(conn, query, max_gd, min_common, viewer, exclude_owner=None):
    out: list[PublicMatch] = []
    for row, markers in pr.iter_searchable(conn, exclude_owner=exclude_owner):
        res = genetic_distance(query, markers)
        if res.compared >= min_common and res.gd <= max_gd:
            out.append(PublicMatch(
                handle=row["public_handle"], gd=res.gd, compared=res.compared,
                nickname=pr.visible_field(row["nickname"], row["nickname_visibility"], viewer),
                ancestor=pr.visible_field(row["ancestor_text"], row["ancestor_visibility"], viewer),
                preliminary=res.preliminary, overlap=res.overlap,
                copy_count_differences=len(res.copy_count_differences),
                fractional_differences=len(res.allele_differences),
            ))
    return out


def _sort(matches: list[PublicMatch]) -> list[PublicMatch]:
    return sorted(matches, key=lambda m: (m.gd, -m.compared, m.handle))


def guest_query_key(secret: bytes, query: dict[str, tuple[float, ...]], max_gd: int, min_common: int) -> bytes:
    canon = f"{SAMPLING_VERSION}|gd<={max_gd}|common>={min_common}|{mk.canonical_string(query)}"
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
) -> GuestResult:
    """Гостевой поиск. Ничего не пишет в базу."""
    _check_params(max_gd, min_common)
    if not query:
        raise SearchError("пустой профиль")
    matches = _candidates(conn, query, max_gd, min_common, viewer="guest")
    key = guest_query_key(secret, query, max_gd, min_common)
    return GuestResult(matches=guest_sample(matches, key), shown_fraction=GUEST_FRACTION)


def owner_search(
    conn: sqlite3.Connection,
    owner_user_id: int,
    profile_id: int,
    *,
    max_gd: int = DEFAULT_MAX_GD,
    min_common: int = DEFAULT_MIN_COMMON,
) -> list[PublicMatch]:
    _check_params(max_gd, min_common)
    own = pr.get_owned(conn, owner_user_id, profile_id)
    if not own.searchable:
        raise SearchError(
            "профиль закрыт: включите сопоставление для этого профиля, чтобы искать совпадения "
            "(закрытые профили не участвуют в поиске ни с какой стороны)"
        )
    return _sort(_candidates(conn, own.markers, max_gd, min_common, viewer="registered",
                             exclude_owner=owner_user_id))
