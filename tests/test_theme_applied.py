"""
GENOPOISK CRM — regression-тест на баг «тема v1.1 не применилась на Windows».

Диагноз (см. app/theme.py): Qt на Windows по умолчанию использует нативный
стиль ('windowsvista'/'windows11'), который частично игнорирует QSS для
части виджетов, даже когда сам stylesheet технически применён без ошибок.
Fix — явный app.setStyle("Fusion") ДО setStyleSheet().

Часть тестов идёт ЧЕРЕЗ РЕАЛЬНЫЙ app.main.main() (не вызывает theme.apply()
напрямую в обход, как в более ранних ручных смоук-тестах) — перехватывает
только блокирующий QApplication.exec(), чтобы не виснуть на event loop.
Это единственный способ поймать регрессию именно в точке входа: если кто-то
в будущем уберёт вызов theme.apply() из main.py, этот тест упадёт — в
отличие от прямого теста theme.apply(), который такую регрессию не заметит.

Примечание по методу: после app.setStyleSheet() Qt оборачивает текущий
стиль в прокси QStyleSheetStyle, и style().objectName() становится пустым —
это штатное поведение Qt, а не баг (сам Fusion остаётся base style под
прокси). Поэтому проверяем факт и порядок вызова setStyle('Fusion') прямо
по исходнику theme.py, а не хрупкой интроспекцией рантайм-объекта стиля.

Требует QT_QPA_PLATFORM=offscreen (или реальный дисплей/Xvfb).
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GENOPOISK_CRM_DB", str(tmp_path / "theme_test.db"))
    yield


def test_theme_apply_calls_set_style_fusion_before_set_stylesheet():
    """
    Статическая проверка исходника theme.apply(): app.setStyle('Fusion')
    обязан вызываться РАНЬШЕ app.setStyleSheet(...). Порядок важен — именно
    его отсутствие было причиной бага на Windows.
    """
    from app import theme

    source = inspect.getsource(theme.apply)
    assert 'setStyle("Fusion")' in source or "setStyle('Fusion')" in source, (
        "theme.apply() не вызывает app.setStyle('Fusion') — на Windows нативный "
        "стиль будет частично игнорировать QSS, даже если styleSheet() не пуст"
    )
    idx_set_style = source.find("setStyle(")
    idx_set_stylesheet = source.find("setStyleSheet(")
    assert 0 <= idx_set_style < idx_set_stylesheet, (
        "setStyle('Fusion') должен вызываться ДО setStyleSheet(), иначе порядок "
        "теряет смысл (setStyleSheet должен применяться поверх уже выставленного Fusion)"
    )


def test_theme_module_qss_is_nonempty_and_has_expected_rules():
    """Сам модуль theme.py содержит ожидаемые правила темы v1.1."""
    from app import theme

    assert theme.QSS.strip(), "app.theme.QSS пуст"
    assert "QTabBar" in theme.QSS
    assert "QPushButton" in theme.QSS
    assert "QTableWidget" in theme.QSS


def test_theme_apply_sets_nonempty_stylesheet_on_real_qapplication():
    """Прямой вызов theme.apply() на реальном QApplication — styleSheet() не пуст."""
    from PySide6.QtWidgets import QApplication
    from app import theme

    app = QApplication.instance() or QApplication([])
    theme.apply(app)

    assert app.styleSheet() == theme.QSS
    assert app.styleSheet(), "styleSheet() пуст после theme.apply()"


def test_theme_applied_through_real_main_entry_point(isolated_db, tmp_path):
    """
    Идёт через app.main.main() — тот же путь, что run_app.py и упакованный
    Windows EXE. Запускается в ОТДЕЛЬНОМ процессе (QApplication — синглтон
    на процесс, конфликтует с другими тестами этого файла в общем pytest-
    прогоне; отдельный процесс к тому же честнее моделирует реальный старт
    EXE, где никакого предыдущего QApplication в принципе не существует).
    Если theme.apply() перестанет вызываться из main.py — тест упадёт.
    """
    import subprocess

    script = f'''
import sys, os
sys.path.insert(0, {str(os.path.join(os.path.dirname(__file__), "..")) !r})
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["GENOPOISK_CRM_DB"] = {str(tmp_path / "theme_subprocess_test.db")!r}

from PySide6.QtWidgets import QApplication
QApplication.exec = lambda self: 0

from app import main as app_main
exit_code = app_main.main()
assert exit_code == 0

app = QApplication.instance()
assert app is not None
qss = app.styleSheet()
print("QSS_LENGTH=" + str(len(qss)))
assert qss, "styleSheet() пуст после реального прохода через main.py"
assert "background" in qss
print("THEME_OK")
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert "THEME_OK" in result.stdout, (
        f"Реальный запуск через main.py не подтвердил применение темы.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
