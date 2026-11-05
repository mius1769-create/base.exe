"""Пользовательские профили: создание (закрытым), согласия, видимость, удаление."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass

from . import markers as mk
from . import panels as pn
from .config import MAX_ALLOWED_GD
from .db import CheckpointResult, Tx, checkpoint_truncate

CONSENT_TEXT_VERSION = "2026-11-mvp1"
CONSENT_BASES = ("own_test", "authorized_other")
VISIBILITY = ("hidden", "registered", "public")
MAX_TEXT = 200


class ProfileError(ValueError):
    pass


class NotFound(ProfileError):
    pass


@dataclass
class OwnerProfileView:
    """Полный вид профиля — только для его владельца."""

    id: int
    public_handle: str
    kit_id_private: str | None
    source_format: str
    consent_basis: str
    searchable: bool
    nickname: str | None
    nickname_visibility: str
    ancestor_text: str | None
    ancestor_visibility: str
    created_at: str
    markers: dict  # {локус: кортеж | None (нет значения) | Invalid (не распознано)}
    panel_code: str | None = None   # None — пользовательский набор
    panel_basis: str = "custom"     # selected | recognized | custom
    contact_allowed: bool = True
    compare_max_gd: int = 4
    compare_multicopy: bool = True


def _clean_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_TEXT:
        raise ProfileError(f"поле «{field}» длиннее {MAX_TEXT} символов")
    return value


def _check_visibility(v: str) -> str:
    if v not in VISIBILITY:
        raise ProfileError(f"недопустимая видимость: {v!r}")
    return v


def _new_handle() -> str:
    return "N-" + secrets.token_hex(6).upper()


def create_profile(
    conn: sqlite3.Connection,
    owner_user_id: int,
    markers: dict[str, tuple[float, ...]],
    *,
    consent_basis: str,
    consent_confirmed: bool,
    source_format: str = "manual",
    kit_id: str | None = None,
    nickname: str | None = None,
    nickname_visibility: str = "hidden",
    ancestor_text: str | None = None,
    ancestor_visibility: str = "hidden",
    panel_code: str | None = None,
    panel_basis_override: str | None = None,
    source: dict | None = None,
) -> int:
    """Создаёт профиль. Он всегда закрыт (searchable = 0) до явного включения владельцем.

    panel_code: код известной панели (позиции = полный состав панели, недостающие —
    «нет значения»), 'AUTO' (распознать надёжно, иначе пользовательский набор)
    или None — пользовательский набор (позиции = только указанные локусы).
    """
    try:
        markers, panel_code, panel_basis = pn.apply_panel(markers, panel_code)
    except (pn.PanelMismatch, pn.UnsupportedPanel) as e:
        raise ProfileError(str(e)) from None
    if panel_basis_override:  # импорт: панель уже распознана по заголовкам файла
        panel_basis = panel_basis_override
    if consent_basis not in CONSENT_BASES:
        raise ProfileError("укажите основание загрузки: свой тест или тест другого человека с его разрешения")
    if not consent_confirmed:
        raise ProfileError("необходимо подтвердить право на загрузку профиля")
    if not any(mk.is_observed(v) for v in markers.values()):
        raise ProfileError("в профиле нет ни одного маркера со значением")
    _check_visibility(nickname_visibility)
    _check_visibility(ancestor_visibility)
    with Tx(conn):
        cur = conn.execute(
            """INSERT INTO profiles(owner_user_id, public_handle, kit_id_private, source_format,
                   panel_code, panel_basis,
                   consent_basis, consent_text_version, consent_confirmed_at, searchable,
                   nickname, nickname_visibility, ancestor_text, ancestor_visibility)
               VALUES (?,?,?,?,?,?,?,?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), 0, ?,?,?,?)""",
            (
                owner_user_id, _new_handle(), _clean_text(kit_id, "kit ID"), source_format,
                panel_code, panel_basis,
                consent_basis, CONSENT_TEXT_VERSION,
                _clean_text(nickname, "никнейм"), nickname_visibility,
                _clean_text(ancestor_text, "дальний предок"), ancestor_visibility,
            ),
        )
        pid = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO profile_markers(profile_id, marker, value, status) VALUES (?,?,?,?)",
            [(pid, name, *mk.to_storage(v)) for name, v in markers.items()],
        )
        if source:
            conn.execute(
                """INSERT INTO profile_sources(profile_id, import_file_id, filename, file_sha256, sheet,
                       row_number, record_id, raw_json) VALUES (?,?,?,?,?,?,?,?)""",
                (pid, source.get("import_file_id"), source["filename"], source["file_sha256"], source["sheet"],
                 source["row_number"], source.get("record_id"), source["raw_json"]),
            )
        conn.execute(
            "INSERT INTO consent_events(profile_id, event, detail) VALUES (?, 'upload', ?)",
            (pid, f"basis={consent_basis}; consent={CONSENT_TEXT_VERSION}; searchable=0; "
                  f"panel={panel_code or 'custom'} ({panel_basis})"),
        )
    return pid


def _owned_row(conn: sqlite3.Connection, owner_user_id: int, profile_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM profiles WHERE id = ? AND owner_user_id = ?", (profile_id, owner_user_id)
    ).fetchone()
    if row is None:
        raise NotFound("профиль не найден")
    return row


def load_source(conn: sqlite3.Connection, profile_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM profile_sources WHERE profile_id = ?", (profile_id,)).fetchone()
    return dict(row) if row else None


def load_markers(conn: sqlite3.Connection, profile_id: int) -> dict:
    rows = conn.execute("SELECT marker, value, status FROM profile_markers WHERE profile_id = ?", (profile_id,))
    return {r["marker"]: mk.from_storage(r["value"], r["status"]) for r in rows}


def get_owned(conn: sqlite3.Connection, owner_user_id: int, profile_id: int) -> OwnerProfileView:
    r = _owned_row(conn, owner_user_id, profile_id)
    return OwnerProfileView(
        id=r["id"], public_handle=r["public_handle"], kit_id_private=r["kit_id_private"],
        source_format=r["source_format"], consent_basis=r["consent_basis"],
        searchable=bool(r["searchable"]), nickname=r["nickname"],
        nickname_visibility=r["nickname_visibility"], ancestor_text=r["ancestor_text"],
        ancestor_visibility=r["ancestor_visibility"], created_at=r["created_at"],
        markers=load_markers(conn, r["id"]),
        panel_code=r["panel_code"], panel_basis=r["panel_basis"],
        contact_allowed=bool(r["contact_allowed"]), compare_max_gd=r["compare_max_gd"],
        compare_multicopy=bool(r["compare_multicopy"]),
    )


def list_owned(conn: sqlite3.Connection, owner_user_id: int) -> list[OwnerProfileView]:
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM profiles WHERE owner_user_id = ? ORDER BY id", (owner_user_id,))]
    return [get_owned(conn, owner_user_id, i) for i in ids]


def set_searchable(conn: sqlite3.Connection, owner_user_id: int, profile_id: int, enabled: bool) -> None:
    _owned_row(conn, owner_user_id, profile_id)
    with Tx(conn):
        conn.execute(
            "UPDATE profiles SET searchable = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
            (1 if enabled else 0, profile_id),
        )
        conn.execute(
            "INSERT INTO consent_events(profile_id, event) VALUES (?, ?)",
            (profile_id, "search_enabled" if enabled else "search_disabled"),
        )


def update_public_fields(
    conn: sqlite3.Connection,
    owner_user_id: int,
    profile_id: int,
    *,
    nickname: str | None,
    nickname_visibility: str,
    ancestor_text: str | None,
    ancestor_visibility: str,
) -> None:
    _owned_row(conn, owner_user_id, profile_id)
    _check_visibility(nickname_visibility)
    _check_visibility(ancestor_visibility)
    with Tx(conn):
        conn.execute(
            """UPDATE profiles SET nickname = ?, nickname_visibility = ?, ancestor_text = ?,
                   ancestor_visibility = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id = ?""",
            (_clean_text(nickname, "никнейм"), nickname_visibility,
             _clean_text(ancestor_text, "дальний предок"), ancestor_visibility, profile_id),
        )
        conn.execute(
            "INSERT INTO consent_events(profile_id, event, detail) VALUES (?, 'visibility_changed', ?)",
            (profile_id, f"nickname={nickname_visibility}; ancestor={ancestor_visibility}"),
        )


def update_settings(
    conn: sqlite3.Connection,
    owner_user_id: int,
    profile_id: int,
    *,
    searchable: bool,
    nickname_visibility: str,
    ancestor_visibility: str,
    contact_allowed: bool,
    compare_max_gd: int,
    compare_multicopy: bool,
) -> None:
    """Настройки одного профиля одной транзакцией. В журнал согласий идут только реальные изменения."""
    row = _owned_row(conn, owner_user_id, profile_id)
    _check_visibility(nickname_visibility)
    _check_visibility(ancestor_visibility)
    if not 0 <= compare_max_gd <= MAX_ALLOWED_GD:
        raise ProfileError(f"порог GD должен быть от 0 до {MAX_ALLOWED_GD}")
    events = []
    if bool(row["searchable"]) != searchable:
        events.append(("search_enabled" if searchable else "search_disabled", None))
    if (row["nickname_visibility"], row["ancestor_visibility"]) != (nickname_visibility, ancestor_visibility):
        events.append(("visibility_changed", f"nickname={nickname_visibility}; ancestor={ancestor_visibility}"))
    if bool(row["contact_allowed"]) != contact_allowed:
        events.append(("contact_enabled" if contact_allowed else "contact_disabled", None))
    with Tx(conn):
        conn.execute(
            """UPDATE profiles SET searchable = ?, nickname_visibility = ?, ancestor_visibility = ?, contact_allowed = ?,
                   compare_max_gd = ?, compare_multicopy = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?""",
            (int(searchable), nickname_visibility, ancestor_visibility, int(contact_allowed), compare_max_gd, int(compare_multicopy), profile_id),
        )
        for event, detail in events:
            conn.execute("INSERT INTO consent_events(profile_id, event, detail) VALUES (?, ?, ?)", (profile_id, event, detail))


def delete_profile(conn: sqlite3.Connection, owner_user_id: int, profile_id: int) -> CheckpointResult:
    """Удаление из активной базы: профиль, маркеры, журнал согласий, запросы на связь,
    происхождение из файла (каскад); сохранённый по согласию оригинал удаляется, если
    в нём не осталось других профилей.

    Возвращает результат checkpoint WAL (complete / incomplete / not_wal). Удаление
    касается файлов приложения; стирание с носителя и из внешних копий не гарантируется.
    """
    _owned_row(conn, owner_user_id, profile_id)
    with Tx(conn):
        src = conn.execute("SELECT import_file_id FROM profile_sources WHERE profile_id = ?", (profile_id,)).fetchone()
        conn.execute("DELETE FROM profiles WHERE id = ? AND owner_user_id = ?", (profile_id, owner_user_id))
        if src and src["import_file_id"] is not None:
            left = conn.execute("SELECT COUNT(*) FROM profile_sources WHERE import_file_id = ?",
                                (src["import_file_id"],)).fetchone()[0]
            if left == 0:  # сохранённый по согласию оригинал больше не нужен ни одному профилю
                conn.execute("DELETE FROM import_files WHERE id = ?", (src["import_file_id"],))
    return checkpoint_truncate(conn)


def iter_searchable(conn: sqlite3.Connection, exclude_owner: int | None = None):
    """Только профили, владельцы которых включили сопоставление."""
    sql = "SELECT * FROM profiles WHERE searchable = 1"
    params: tuple = ()
    if exclude_owner is not None:
        sql += " AND owner_user_id != ?"
        params = (exclude_owner,)
    for row in conn.execute(sql + " ORDER BY id", params).fetchall():
        yield row, load_markers(conn, row["id"])


def visible_field(value: str | None, visibility: str, viewer: str) -> str | None:
    """viewer: 'guest' | 'registered'."""
    if value is None or visibility == "hidden":
        return None
    if visibility == "public":
        return value
    return value if viewer == "registered" else None


def export_owner_profile(conn: sqlite3.Connection, owner_user_id: int, profile_id: int) -> dict:
    """Экспорт собственного профиля владельцем (JSON).

    Массовой выгрузки базы в MVP нет намеренно: она обходила бы гостевое
    ограничение 20% и согласия владельцев. kit ID и email в экспорт не входят.
    """
    p = get_owned(conn, owner_user_id, profile_id)
    return {
        "handle": p.public_handle,
        "source_format": p.source_format,
        "panel": p.panel_code or "custom",
        "panel_basis": p.panel_basis,
        "consent_basis": p.consent_basis,
        "searchable": p.searchable,
        "nickname": p.nickname,
        "nickname_visibility": p.nickname_visibility,
        "ancestor": p.ancestor_text,
        "ancestor_visibility": p.ancestor_visibility,
        "markers": {k: mk.format_value(v) for k, v in sorted(p.markers.items()) if mk.is_observed(v)},
        "markers_without_value": sorted(k for k, v in p.markers.items() if v is None),
        "markers_unrecognized": {k: str(v) for k, v in sorted(p.markers.items()) if isinstance(v, mk.Invalid)},
    }
