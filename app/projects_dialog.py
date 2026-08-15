"""
GENOPOISK CRM — CRUD-диалог справочника проектов (вкладка «Гаплогруппы»).

Дерево с произвольной вложенностью (Клиенты / Этнопроекты > Башкирский
проект > ...). Создание / вложение / переименование / архивирование —
без физического удаления, как и у остальных сущностей приложения.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTreeWidget,
    QTreeWidgetItem, QMessageBox, QInputDialog, QComboBox,
)

from . import projects_repo as prepo


class ProjectsDialog(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Справочник проектов")
        self.resize(520, 560)
        self._build_ui()
        self._reload_tree()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Дерево проектов для вкладки «Гаплогруппы» (напр. Клиенты, "
            "Этнопроекты → Башкирский проект). Архивированные проекты "
            "остаются в дереве (серым), но недоступны для выбора при "
            "заполнении новых записей."
        ))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Проект"])
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.tree, stretch=1)

        btn_row = QHBoxLayout()
        self.add_root_btn = QPushButton("Добавить корневой")
        self.add_root_btn.clicked.connect(self._on_add_root)
        self.add_child_btn = QPushButton("Добавить вложенный")
        self.add_child_btn.clicked.connect(self._on_add_child)
        self.add_child_btn.setEnabled(False)
        self.rename_btn = QPushButton("Переименовать")
        self.rename_btn.clicked.connect(self._on_rename)
        self.rename_btn.setEnabled(False)
        self.move_btn = QPushButton("Переместить…")
        self.move_btn.clicked.connect(self._on_move)
        self.move_btn.setEnabled(False)
        self.archive_btn = QPushButton("Архивировать")
        self.archive_btn.clicked.connect(self._on_toggle_archive)
        self.archive_btn.setEnabled(False)

        btn_row.addWidget(self.add_root_btn)
        btn_row.addWidget(self.add_child_btn)
        btn_row.addWidget(self.rename_btn)
        btn_row.addWidget(self.move_btn)
        btn_row.addWidget(self.archive_btn)
        layout.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        close_row.addStretch(1)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ------------------------------------------------------------------
    def _reload_tree(self, *, select_id: Optional[int] = None) -> None:
        self.tree.clear()
        tree = prepo.build_tree(self.conn, include_archived=True)

        def add_nodes(nodes: list[dict], parent_item: Optional[QTreeWidgetItem]) -> None:
            for node in nodes:
                label = node["name"] + ("  (архив)" if node["is_archived"] else "")
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.UserRole, node["id"])
                if node["is_archived"]:
                    item.setForeground(0, Qt.gray)
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                add_nodes(node["children"], item)

        add_nodes(tree, None)
        self.tree.expandAll()

        if select_id is not None:
            self._select_item_by_id(select_id)

    def _select_item_by_id(self, project_id: int) -> None:
        def walk(item: QTreeWidgetItem) -> Optional[QTreeWidgetItem]:
            if item.data(0, Qt.UserRole) == project_id:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found is not None:
                self.tree.setCurrentItem(found)
                return

    def _selected_id(self) -> Optional[int]:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole)

    def _selected_is_archived(self) -> bool:
        row = self.conn.execute(
            "SELECT is_archived FROM projects WHERE id = ?", (self._selected_id(),)
        ).fetchone()
        return bool(row["is_archived"]) if row else False

    def _on_selection_changed(self) -> None:
        has_sel = self._selected_id() is not None
        self.add_child_btn.setEnabled(has_sel)
        self.rename_btn.setEnabled(has_sel)
        self.move_btn.setEnabled(has_sel)
        self.archive_btn.setEnabled(has_sel)
        if has_sel:
            self.archive_btn.setText("Восстановить" if self._selected_is_archived() else "Архивировать")

    # ------------------------------------------------------------------
    def _on_add_root(self) -> None:
        name, ok = QInputDialog.getText(self, "Новый проект", "Название корневого проекта:")
        if not ok or not name.strip():
            return
        new_id = prepo.create_project(self.conn, name.strip(), None)
        self._reload_tree(select_id=new_id)

    def _on_add_child(self) -> None:
        parent_id = self._selected_id()
        if parent_id is None:
            return
        name, ok = QInputDialog.getText(self, "Новый вложенный проект", "Название проекта:")
        if not ok or not name.strip():
            return
        new_id = prepo.create_project(self.conn, name.strip(), parent_id)
        self._reload_tree(select_id=new_id)

    def _on_rename(self) -> None:
        project_id = self._selected_id()
        if project_id is None:
            return
        row = self.conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
        name, ok = QInputDialog.getText(self, "Переименование", "Новое название:", text=row["name"])
        if not ok or not name.strip():
            return
        prepo.rename_project(self.conn, project_id, name.strip())
        self._reload_tree(select_id=project_id)

    def _on_move(self) -> None:
        project_id = self._selected_id()
        if project_id is None:
            return

        candidates = [(None, "— сделать корневым —")]
        forbidden = {project_id} | prepo.get_descendant_ids(self.conn, project_id)
        for pid, name, depth, _archived in prepo.flatten_tree(prepo.build_tree(self.conn, include_archived=True)):
            if pid in forbidden:
                continue
            candidates.append((pid, ("  " * depth) + name))

        labels = [label for _pid, label in candidates]
        choice, ok = QInputDialog.getItem(self, "Переместить проект", "Новый родитель:", labels, 0, False)
        if not ok:
            return
        target_pid = candidates[labels.index(choice)][0]
        try:
            prepo.move_project(self.conn, project_id, target_pid)
        except ValueError as exc:
            QMessageBox.warning(self, "Проверка", str(exc))
            return
        self._reload_tree(select_id=project_id)

    def _on_toggle_archive(self) -> None:
        project_id = self._selected_id()
        if project_id is None:
            return
        if self._selected_is_archived():
            prepo.unarchive_project(self.conn, project_id)
        else:
            confirm = QMessageBox.question(
                self, "Архивирование", "Архивировать этот проект?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            prepo.archive_project(self.conn, project_id)
        self._reload_tree(select_id=project_id)
