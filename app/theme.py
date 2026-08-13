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

/* ---- тулбар: акцентная кнопка "Новый заказ" (раздел v1.5 header_filters) ---- */
QToolBar QToolButton#primaryToolButton {{
    background: {ACCENT};
    color: #ffffff;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QToolBar QToolButton#primaryToolButton:hover {{
    background: #4338ca;
    border-color: #4338ca;
    color: #ffffff;
}}

/* ---- вкладки: индикатор активной вкладки снизу ---- */
QTabBar::tab:selected {{
    border-bottom: 3px solid {ACCENT};
}}

/* ---- подвал со счётчиком тестов ---- */
QWidget#footerBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
}}
QWidget#footerBar QLabel {{
    color: {TEXT_MUTED};
    font-size: 11.5px;
}}
QLabel#footerPill {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
}}

/* ---- карточка: подложки-боксы (дедлайн/клиент/заказ/связанные тесты) ---- */
QFrame#infoBox {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#infoBox QLabel#sectionTitle {{
    color: #8b94a5;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .06em;
    background: transparent;
    border: none;
}}
QLabel#cardTitle {{
    font-size: 19px;
    font-weight: 600;
    background: transparent;
    border: none;
}}
QLabel#cardSub {{
    color: {TEXT_MUTED};
    background: transparent;
    border: none;
}}
QLabel#cardStatusPill {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    border-radius: 9px;
    padding: 6px 10px;
    font-weight: 600;
}}

/* ---- поля заказа "Заказ · управление" (только для чтения, раздел v1.5) ---- */
QFrame#fieldBox {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 7px;
}}
QFrame#fieldBox QLabel#fieldLabel {{
    color: #929bad;
    font-size: 9.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .05em;
    background: transparent;
    border: none;
}}
QFrame#fieldBox QLabel#fieldValue {{
    color: {TEXT_PRIMARY};
    background: transparent;
    border: none;
}}

/* ---- быстрые действия / кнопки заказа ---- */
QPushButton#actionPrimary {{
    background: {ACCENT};
    color: #ffffff;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton#actionPrimary:hover:enabled {{
    background: #4338ca;
}}
QPushButton#actionDone {{
    background: #ecfdf3;
    color: #15803d;
    border: 1px solid #b9ebcb;
}}

/* ---- таймлайн маршрута теста ---- */
QLabel#timelineStepTitle {{
    font-weight: 600;
    background: transparent;
    border: none;
}}
QLabel#timelineStepTime {{
    color: {TEXT_MUTED};
    font-size: 11px;
    background: transparent;
    border: none;
}}
QLabel#timelineStepNote {{
    color: #606a7a;
    font-size: 11px;
    background: transparent;
    border: none;
}}

/* ---- попап фильтра колонки шапки таблицы (раздел v1.5 header_filters) ---- */
QFrame#headerFilterMenu {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 9px;
}}
QFrame#headerFilterMenu QLabel#filterMenuTitle {{
    color: #929bad;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .06em;
    padding: 2px 4px 4px;
    background: transparent;
    border: none;
}}
QFrame#headerFilterMenu QPushButton#filterOption {{
    background: #ffffff;
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 6px;
    padding: 8px 9px;
    text-align: left;
    font-weight: 400;
}}
QFrame#headerFilterMenu QPushButton#filterOption:hover {{
    background: #f7f8fb;
}}
QFrame#headerFilterMenu QPushButton#filterOption[selected="true"] {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    font-weight: 600;
}}
QFrame#headerFilterMenu QFrame#filterClearDivider {{
    background: {BORDER};
    max-height: 1px;
    margin: 4px 0;
}}
QFrame#headerFilterMenu QLineEdit#filterSearch {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 9px;
}}
QFrame#headerFilterMenu QLineEdit#filterSearch:focus {{
    border-color: #b8bbff;
}}

/* ---- заголовок таблицы: колонка с активным фильтром выделяется акцентом ---- */
QHeaderView::section:hover {{
    background: #f1f3f8;
    color: {TEXT_PRIMARY};
}}
"""


def apply(app) -> None:
    """
    ВАЖНО (найденная причина, почему тема не применялась на Windows):
    Qt по умолчанию на Windows использует НАТИВНЫЙ стиль ('windowsvista'/
    'windows11'), который рисует часть виджетов (границы кнопок, вкладки,
    заголовки таблиц) через API темизации самой ОС и частично ИГНОРИРУЕТ
    QSS для этих элементов — даже если сам stylesheet технически применён
    без ошибок. На Linux/Xvfb это не проявлялось, т.к. там Qt по умолчанию
    и так использует кросс-платформенный стиль, который полностью
    подчиняется QSS.

    Fusion — единственный штатный стиль Qt, который гарантированно и
    полностью следует QSS на любой ОС, поэтому ставим его явно ДО
    applyStyleSheet. Без этой строки светлая тема на Windows выглядела
    как стандартный Qt, хотя styleSheet() не был пустым.
    """
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
