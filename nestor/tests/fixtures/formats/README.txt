Синтетические файлы форматов импорта NeSToR (не реальные люди, не научные данные).
Значения условные: вычисляются по имени локуса (tests/format_fixtures.py).
Пересоздать: python tests/format_fixtures.py

FTDNA-Y12.csv      FTDNA Y12, CSV ';'          FTDNA-Y25.csv     FTDNA Y25, CSV ','
FTDNA-Y37.tsv      FTDNA Y37, TSV              FTDNA-Y67.xlsx    FTDNA Y67, XLSX
FTDNA-Y111.csv     FTDNA Y111, CSV ';'         Genopoisk-Y37.csv Genopoisk Y37, CSV ';'
Genopoisk-Y50.xlsx Genopoisk Y50, XLSX
Custom-18.csv      пользовательский набор, 18 значений с явными заголовками (DYS385a/b)
Custom-50.csv      пользовательский набор, 50 локусов с явными заголовками
Edge-cases.csv     пропуски, «0»/«-», дроби, копии в колонках a/b/c/d, DYS389B, нераспознанные
Headerless-Y37.csv 37 значений без заголовков — должен отклоняться (состав не угадывается)
