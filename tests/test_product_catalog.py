"""Тесты единого master-справочника номенклатуры (v1.1, раздел 6/11)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import product_catalog as pc


def test_all_required_display_names_present():
    expected = {
        "Y50": "Y Базовый",
        "Y37": "Y37",
        "STRELKA": "Strelka",
        "MTDNA": "МитоДНК Базовый",
        "MITOGENOME": "Полный митогеном",
        "WGS15": "Происхождение",
        "WGS30": "Эксперт",
        "REPORT": "Отчёт",
    }
    for code, name in expected.items():
        assert pc.get_display_name(code) == name


def test_y_basic_never_shows_technical_suffix():
    """Явное требование: показывать 'Y Базовый', НЕ 'Y50' и НЕ 'Y Базовый (Y50)'."""
    name = pc.get_display_name("Y50")
    assert name == "Y Базовый"
    assert "Y50" not in name
    assert "(" not in name


def test_unknown_historical_code_returns_as_is_not_crashes():
    """Историческая запись вроде FULL LINE/WGS20X — не в справочнике, но не должна падать."""
    assert pc.get_display_name("FULL LINE") == "FULL LINE"
    assert pc.get_display_name("WGS20X") == "WGS20X"


def test_get_color_returns_distinct_colors_per_type():
    codes = pc.all_technical_codes()
    colors = [pc.get_color(c) for c in codes]
    assert all(c is not None for c in colors)
    assert len(set(colors)) == len(colors), "цвета типов тестов не должны повторяться"


def test_resolve_historical_name_finds_known_variants():
    assert pc.resolve_historical_name("Y-50") == "Y50"
    assert pc.resolve_historical_name("мтДНК") == "MTDNA"
    assert pc.resolve_historical_name("мтДнк") == "MTDNA"  # опечатка из реального файла
    assert pc.resolve_historical_name("WGS 30X") == "WGS30"
    assert pc.resolve_historical_name("совершенно неизвестное") is None


def test_master_codes_match_technical_specification():
    """Сверка с мастер-справочником из задания — master_code для документации,
    technical_code остаётся прежним ради совместимости с историческими данными."""
    expected_master = {
        "Y50": "Y_BASIC", "Y37": "Y37", "STRELKA": "STRELKA",
        "MTDNA": "MTDNA_BASIC", "MITOGENOME": "MITOGENOME",
        "WGS15": "WGS15", "WGS30": "WGS30", "REPORT": "REPORT",
    }
    for tech_code, master in expected_master.items():
        entry = pc.get_entry(tech_code)
        assert entry is not None
        assert entry.master_code == master
