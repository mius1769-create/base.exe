"""
GENOPOISK CRM — визуальная тема v1.1 (раздел 5 ТЗ).

Только QSS/визуальный слой поверх уже существующих виджетов. НЕ меняет:
бизнес-логику, модель test_events, API repository, маршруты, сроки,
структуру исторических данных — только то, как приложение выглядит.

Палитра и пропорции взяты из согласованного эталона two_tabs_v2.html:
светлый фон, белые поверхности, мягкие границы, компактные скругления,
один акцентный цвет (индиго), цвет типа теста ≠ цвет срочности.
"""

BG_PAGE = "#eef0f4"
SURFACE = "#ffffff"
SURFACE_SOFT = "#f7f7f9"
BORDER = "#e4e5eb"
TEXT_PRIMARY = "#14151a"
TEXT_SECONDARY = "#6b6e78"
TEXT_MUTED = "#9a9ca6"
ACCENT = "#4f46e5"
ACCENT_SOFT = "#eeecfd"

QSS = f"""
QMainWindow, QWidget {{
    background: {BG_PAGE};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", "Noto Sans", Arial, sans-serif;
    font-size: 12.5px;
}}

/* ---- тулбар (панель действий) ---- */
QToolBar {{
    background: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 7px 13px;
    font-weight: 500;
}}
QToolBar QToolButton:hover {{
    background: {SURFACE_SOFT};
    color: {TEXT_PRIMARY};
    border-color: {BORDER};
}}

/* ---- вкладки Клиентская / Внутренняя работа ---- */
QTabWidget::pane {{
    border: none;
    background: {SURFACE};
}}
QTabBar {{
    background: {BG_PAGE};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    font-weight: 600;
    padding: 10px 22px;
    margin: 8px 2px 0 8px;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-bottom: none;
}}
QTabBar::tab:!selected:hover {{
    color: {TEXT_PRIMARY};
}}

/* ---- поиск / фильтры ---- */
QLineEdit {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_SOFT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
}}
QComboBox:hover {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT_PRIMARY};
    outline: none;
}}

/* ---- таблица списка тестов ---- */
QTableWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT_PRIMARY};
    alternate-background-color: {SURFACE_SOFT};
}}
QTableWidget::item {{
    padding: 3px 8px;
    border: none;
}}
QHeaderView::section {{
    background: {SURFACE_SOFT};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
}}

/* ---- карточка (правая панель) ---- */
QFrame#cardPanel {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ---- кнопки по умолчанию (не акцентные) ---- */
QPushButton {{
    background: {SURFACE_SOFT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 8px 14px;
    font-weight: 500;
}}
QPushButton:hover:enabled {{
    background: {SURFACE};
    border-color: {ACCENT};
}}
QPushButton:disabled {{
    background: {SURFACE_SOFT};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

/* ---- статус-бар ---- */
QStatusBar {{
    background: {SURFACE};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
}}

/* ---- скролл ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* ---- диалоги ---- */
QDialog {{
    background: {BG_PAGE};
}}
"""


def apply(app) -> None:
    app.setStyleSheet(QSS)
