"""Общие настройки консольных инструментов."""

import sys


def utf8_output() -> None:
    """Вывод в UTF-8: на Windows при выводе в канал/файл по умолчанию cp1252 и кириллица падает."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
