"""
GENOPOISK CRM — единый master-справочник номенклатуры (v1.1, раздел 11).

Единственный источник правды для отображаемых названий тестов. Ничего,
кроме этого файла, не должно хардкодить пользовательские названия — GUI,
Excel import/export, Telegram parser, product mappings, фильтры и отчёты
обязаны брать название отсюда. Если коммерческое название на сайте
поменяется — правится одна запись здесь, а не код в разных местах.

Важное архитектурное решение: technical_code здесь — это СУЩЕСТВУЮЩИЙ
внутренний код, уже хранящийся в БД (tests.test_type, test_types.code,
product_mappings и т.д. — напр. "Y50", "MTDNA"). Он НЕ переименован в
"Y_BASIC"/"MTDNA_BASIC" и т.п., как можно было бы прочитать из ТЗ буквально,
потому что переименование самого хранимого кода потребовало бы миграции
520+ исторических записей и правки бизнес-логики/repository API — а это
прямо запрещено ("не менять структуру исторических данных", "не менять
API repository"). Вместо этого master_code — это просто метка соответствия
коду из ТЗ, для документации; технический код для всех реальных операций
(БД, business_logic, repository) остаётся прежним.

    technical_code   — реальный код в БД (не менять, историческая совместимость)
    master_code      — код из мастер-справочника ТЗ (Y_BASIC, MTDNA_BASIC и т.д.)
    display_name     — то, что видит пользователь в GUI
    commercial_name  — коммерческое название (сейчас совпадает с display_name,
                        разделено на случай будущего расхождения "как в CRM"
                        vs "как на сайте")
    historical_names — варианты названий из старых Excel/Telegram-сообщений,
                        распознаются как этот же тест при импорте/разборе
    color            — цвет badge типа теста (не связан с цветом срочности)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProductEntry:
    technical_code: str
    master_code: str
    display_name: str
    commercial_name: str
    historical_names: list[str] = field(default_factory=list)
    color: str = "#e5e5ea"


CATALOG: list[ProductEntry] = [
    ProductEntry(
        technical_code="Y50", master_code="Y_BASIC",
        display_name="Y Базовый", commercial_name="Y Базовый",
        historical_names=["Y50", "Y-50", "Y Базовый (Y50)", "y50", " Y50"],
        color="#c7d7ff",
    ),
    ProductEntry(
        technical_code="Y37", master_code="Y37",
        display_name="Y37", commercial_name="Y37",
        historical_names=["Y37", "Y-37", "Y Base (Y37)", "y37"],
        color="#ddc2fb",
    ),
    ProductEntry(
        technical_code="STRELKA", master_code="STRELKA",
        display_name="Strelka", commercial_name="Strelka",
        historical_names=["STRELKA", "Strelka", "strelka"],
        color="#ffcf9e",
    ),
    ProductEntry(
        technical_code="MTDNA", master_code="MTDNA_BASIC",
        display_name="МитоДНК Базовый", commercial_name="МитоДНК Базовый",
        historical_names=["MTDNA", "мтДНК", "мтДНК Базовый", "мтДнк", "мито"],
        color="#7fefde",
    ),
    ProductEntry(
        technical_code="MITOGENOME", master_code="MITOGENOME",
        display_name="Полный митогеном", commercial_name="Полный митогеном",
        historical_names=["MITOGENOME", "Митогеном"],
        color="#9ceec1",
    ),
    ProductEntry(
        technical_code="WGS15", master_code="WGS15",
        display_name="Происхождение", commercial_name="Происхождение",
        historical_names=["WGS15", "WGS 15X", "WGS15X"],
        color="#a3edb8",
    ),
    ProductEntry(
        technical_code="WGS30", master_code="WGS30",
        display_name="Эксперт", commercial_name="Эксперт",
        historical_names=["WGS30", "WGS 30X", "WGS30X"],
        color="#62d98c",
    ),
    ProductEntry(
        technical_code="REPORT", master_code="REPORT",
        display_name="Отчёт", commercial_name="Отчёт",
        historical_names=["Отчёт", "report", "С отчётом", "отчет"],
        color="#fde68a",
    ),
]

_BY_TECHNICAL_CODE = {e.technical_code: e for e in CATALOG}


def get_entry(technical_code: str) -> Optional[ProductEntry]:
    return _BY_TECHNICAL_CODE.get(technical_code)


def get_display_name(technical_code: str) -> str:
    """
    Коммерческое название для показа пользователю. Если код неизвестен
    справочнику (историческая запись вроде 'FULL LINE' или 'WGS20X',
    сохранённая как есть при миграции — раздел 14 ТЗ) — возвращает код
    без изменений, а не падает и не подставляет технический код молча.
    """
    entry = _BY_TECHNICAL_CODE.get(technical_code)
    return entry.display_name if entry else technical_code


def get_color(technical_code: str) -> Optional[str]:
    entry = _BY_TECHNICAL_CODE.get(technical_code)
    return entry.color if entry else None


def resolve_historical_name(raw_name: str) -> Optional[str]:
    """Ищет technical_code по историческому/альтернативному названию —
    используется при импорте Excel и разборе сообщений Telegram, чтобы не
    хардкодить отдельную мапу синонимов там же."""
    raw_norm = raw_name.strip().lower()
    for entry in CATALOG:
        if raw_norm == entry.technical_code.lower():
            return entry.technical_code
        if any(raw_norm == h.lower() for h in entry.historical_names):
            return entry.technical_code
    return None


def all_technical_codes() -> list[str]:
    return [e.technical_code for e in CATALOG]
