"""Синтетические Y-STR-профили для тестов. Не реальные люди и не научные данные."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nestor_app import accounts, db, panels  # noqa: E402
from nestor_app import profiles as pr  # noqa: E402

# Синтетический модальный гаплотип на маркерах FTDNA Y37 (значения условные).
BASE_Y37: dict[str, tuple[float, ...]] = {
    "DYS393": (13.0,), "DYS390": (24.0,), "DYS19": (14.0,), "DYS391": (11.0,),
    "DYS385": (11.0, 14.0), "DYS426": (12.0,), "DYS388": (12.0,), "DYS439": (12.0,),
    "DYS389I": (13.0,), "DYS392": (13.0,), "DYS389II": (29.0,), "DYS458": (17.0,),
    "DYS459": (9.0, 10.0), "DYS455": (11.0,), "DYS454": (11.0,), "DYS447": (25.0,),
    "DYS437": (15.0,), "DYS448": (19.0,), "DYS449": (29.0,), "DYS464": (15.0, 15.0, 17.0, 17.0),
    "DYS460": (11.0,), "Y-GATA-H4": (11.0,), "YCAII": (19.0, 23.0), "DYS456": (16.0,),
    "DYS607": (15.0,), "DYS576": (18.0,), "DYS570": (17.0,), "CDY": (37.0, 38.0),
    "DYS442": (12.0,), "DYS438": (12.0,),
}
assert set(BASE_Y37) == set(panels.PANELS["FTDNA_Y37"].marker_names)

# DYS389I исключён: по T16 его изменение меняет и производный DYS389B (2 шага за одну мутацию).
SINGLE_COPY = [m for m, v in BASE_Y37.items() if len(v) == 1 and m != "DYS389I"]


def mutate(base: dict, steps: int, rng: random.Random) -> dict:
    """Профиль ровно на `steps` шагов GD от base (меняются разные одиночные маркеры на ±1)."""
    out = dict(base)
    for name in rng.sample(SINGLE_COPY, steps):
        out[name] = (out[name][0] + rng.choice((-1.0, 1.0)),)
    return out


def as_text(markers: dict) -> str:
    from nestor_app.markers import format_value
    return "\n".join(f"{k}={format_value(v)}" for k, v in markers.items())


def new_conn():
    return db.connect(":memory:")


def new_user(conn, n: int, display_name: str | None = None) -> int:
    return accounts.register(conn, f"user{n}@example.test", "password-123", display_name)


def populate(conn, gds: list[int], *, searchable=True, seed=1, user_offset=100) -> list[int]:
    """Создаёт по одному владельцу на профиль с заданными GD от BASE_Y37."""
    rng = random.Random(seed)
    ids = []
    for i, gd in enumerate(gds):
        uid = new_user(conn, user_offset + i)
        pid = pr.create_profile(conn, uid, mutate(BASE_Y37, gd, rng),
                                consent_basis="own_test", consent_confirmed=True,
                                kit_id=f"KIT{user_offset + i:06d}",
                                nickname=f"nick{i}", nickname_visibility="public",
                                ancestor_text=f"предок {i}", ancestor_visibility="registered")
        if searchable:
            pr.set_searchable(conn, uid, pid, True)
        ids.append(pid)
    return ids


SECRET = bytes.fromhex(os.environ.get("NESTOR_TEST_SECRET", "11" * 32))
