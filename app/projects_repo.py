"""
GENOPOISK CRM — репозиторий справочника проектов (вкладка «Гаплогруппы»).

Дерево с произвольной вложенностью (напр. Этнопроекты > Башкирский проект).
Как и остальные справочники/сущности приложения — без физического удаления,
только архивирование (см. repository.py: orders/tests).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from . import repository as repo


def create_project(
    conn: sqlite3.Connection,
    name: str,
    parent_id: Optional[int] = None,
    *,
    user_name: Optional[str] = None,
) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Название проекта не может быть пустым")
    if parent_id is not None:
        parent = conn.execute("SELECT id FROM projects WHERE id = ?", (parent_id,)).fetchone()
        if parent is None:
            raise ValueError(f"Родительский проект {parent_id} не найден")

    ts = repo.now_iso()
    cur = conn.execute(
        """INSERT INTO projects (parent_id, name, sort_order, created_at, updated_at)
           VALUES (?, ?, 0, ?, ?)""",
        (parent_id, name, ts, ts),
    )
    project_id = cur.lastrowid
    repo.write_audit(conn, user_name=user_name, entity="project", entity_id=project_id,
                      field=None, old_value=None, new_value=name, reason="создание проекта")
    return project_id


def rename_project(
    conn: sqlite3.Connection, project_id: int, new_name: str, *, user_name: Optional[str] = None
) -> None:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Название проекта не может быть пустым")
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"Проект {project_id} не найден")
    if row["name"] == new_name:
        return
    conn.execute(
        "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
        (new_name, repo.now_iso(), project_id),
    )
    repo.write_audit(conn, user_name=user_name, entity="project", entity_id=project_id,
                      field="name", old_value=row["name"], new_value=new_name, reason="переименование проекта")


def move_project(
    conn: sqlite3.Connection, project_id: int, new_parent_id: Optional[int], *, user_name: Optional[str] = None
) -> None:
    """Вложить проект под другого родителя (или сделать корневым, если None)."""
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"Проект {project_id} не найден")

    if new_parent_id is not None:
        if new_parent_id == project_id:
            raise ValueError("Проект не может быть вложен сам в себя")
        if new_parent_id in get_descendant_ids(conn, project_id):
            raise ValueError("Нельзя вложить проект в собственного потомка (образуется цикл)")
        parent = conn.execute("SELECT id FROM projects WHERE id = ?", (new_parent_id,)).fetchone()
        if parent is None:
            raise ValueError(f"Родительский проект {new_parent_id} не найден")

    old_parent_id = row["parent_id"]
    if old_parent_id == new_parent_id:
        return
    conn.execute(
        "UPDATE projects SET parent_id = ?, updated_at = ? WHERE id = ?",
        (new_parent_id, repo.now_iso(), project_id),
    )
    repo.write_audit(conn, user_name=user_name, entity="project", entity_id=project_id,
                      field="parent_id", old_value=old_parent_id, new_value=new_parent_id,
                      reason="перемещение проекта в дереве")


def set_project_archived(
    conn: sqlite3.Connection, project_id: int, archived: bool, *, user_name: Optional[str] = None
) -> None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"Проект {project_id} не найден")
    new_val = int(archived)
    if row["is_archived"] == new_val:
        return
    conn.execute(
        "UPDATE projects SET is_archived = ?, updated_at = ? WHERE id = ?",
        (new_val, repo.now_iso(), project_id),
    )
    repo.write_audit(conn, user_name=user_name, entity="project", entity_id=project_id,
                      field="is_archived", old_value=row["is_archived"], new_value=new_val,
                      reason="архивирование проекта" if archived else "восстановление проекта")


def archive_project(conn: sqlite3.Connection, project_id: int, *, user_name: Optional[str] = None) -> None:
    set_project_archived(conn, project_id, True, user_name=user_name)


def unarchive_project(conn: sqlite3.Connection, project_id: int, *, user_name: Optional[str] = None) -> None:
    set_project_archived(conn, project_id, False, user_name=user_name)


def list_projects(conn: sqlite3.Connection, *, include_archived: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM projects"
    if not include_archived:
        q += " WHERE is_archived = 0"
    q += " ORDER BY parent_id IS NOT NULL, sort_order, name"
    return conn.execute(q).fetchall()


def build_tree(conn: sqlite3.Connection, *, include_archived: bool = True) -> list[dict]:
    """Вложенная структура: [{"id", "name", "is_archived", "children": [...]}, ...]."""
    rows = list_projects(conn, include_archived=include_archived)
    by_id: dict[int, dict] = {
        r["id"]: {"id": r["id"], "name": r["name"], "parent_id": r["parent_id"],
                   "is_archived": bool(r["is_archived"]), "children": []}
        for r in rows
    }
    roots: list[dict] = []
    for r in rows:
        node = by_id[r["id"]]
        parent_id = r["parent_id"]
        if parent_id is not None and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def flatten_tree(
    tree: list[dict], *, depth: int = 0
) -> list[tuple[int, str, int, bool]]:
    """(project_id, name, depth, is_archived) в порядке обхода дерева — для комбобоксов/списков."""
    out: list[tuple[int, str, int, bool]] = []
    for node in tree:
        out.append((node["id"], node["name"], depth, node["is_archived"]))
        out.extend(flatten_tree(node["children"], depth=depth + 1))
    return out


def get_descendant_ids(conn: sqlite3.Connection, project_id: int) -> set[int]:
    """Все id потомков (без самого project_id), включая архивированные."""
    children_by_parent: dict[Optional[int], list[int]] = {}
    for r in conn.execute("SELECT id, parent_id FROM projects").fetchall():
        children_by_parent.setdefault(r["parent_id"], []).append(r["id"])

    result: set[int] = set()
    stack = list(children_by_parent.get(project_id, []))
    while stack:
        cur = stack.pop()
        if cur in result:
            continue
        result.add(cur)
        stack.extend(children_by_parent.get(cur, []))
    return result


def get_project_path(conn: sqlite3.Connection, project_id: Optional[int]) -> str:
    """Хлебные крошки, напр. 'Этнопроекты › Башкирский проект'.

    Для одиночного project_id. Если нужны пути для многих записей подряд
    (напр. вся таблица вкладки «Гаплогруппы») — используйте
    build_project_paths(), чтобы не делать по отдельному запросу к БД на
    каждую строку."""
    if project_id is None:
        return ""
    rows = {r["id"]: r for r in conn.execute("SELECT id, parent_id, name FROM projects").fetchall()}
    parts: list[str] = []
    cur = rows.get(project_id)
    seen: set[int] = set()
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        parts.append(cur["name"])
        cur = rows.get(cur["parent_id"]) if cur["parent_id"] is not None else None
    return " › ".join(reversed(parts))


def build_project_paths(conn: sqlite3.Connection) -> dict[int, str]:
    """Хлебные крошки для ВСЕХ проектов одним запросом к БД — используется
    при построении списка/таблицы (напр. haplogroups_tab.refresh()), чтобы
    не повторять запрос БД для каждой строки (N+1)."""
    rows = {r["id"]: r for r in conn.execute("SELECT id, parent_id, name FROM projects").fetchall()}
    paths: dict[int, str] = {}

    def resolve(project_id: int, seen: set[int]) -> str:
        if project_id in paths:
            return paths[project_id]
        row = rows.get(project_id)
        if row is None or project_id in seen:
            return ""
        parts: list[str] = [row["name"]]
        parent_id = row["parent_id"]
        if parent_id is not None:
            parent_path = resolve(parent_id, seen | {project_id})
            if parent_path:
                parts.insert(0, parent_path)
        path = " › ".join(parts)
        paths[project_id] = path
        return path

    for pid in rows:
        resolve(pid, set())
    return paths
