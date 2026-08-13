# GENOPOISK CRM — Acceptance Report

Дата прогона: см. дату последнего запуска `pytest`. Автоматических тестов: **62/62 PASSED**.

Команда для воспроизведения:
```
cd genopoisk_crm
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Таблица приёмочных сценариев (раздел 24 ТЗ)

| № | Тест (раздел 24 ТЗ) | Ожидаемый результат | Автотест(ы) | Результат |
|---|---|---|---|---|
| 1 | Создание Y50 | Один тест, новый GNPSK, норматив 30 дней | `test_business_logic.py::test_y50_creates_one_test` | **PASS** |
| 2 | Создание Y50 + mtDNA | Два разных GNPSK, один order_id | `test_business_logic.py::test_y50_plus_mtdna_creates_two_tests_two_gnpsk_one_order` | **PASS** |
| 3 | Y50 + отчёт | Норматив 45 дней | `test_business_logic.py::test_y50_with_report_45_days` | **PASS** |
| 4 | mtDNA + отчёт | Норматив 45 дней | `test_business_logic.py::test_mtdna_plus_report_45_days` | **PASS** |
| 5 | STRELKA + отчёт | Норматив 60 дней | `test_business_logic.py::test_strelka_plus_report_60_days` | **PASS** |
| 6 | WGS 15X | Норматив 60 дней | `test_acceptance_y50_mtdna_report.py::test_wgs_15x_30x_60_days_report_forbidden` | **PASS** |
| 7 | WGS 30X | Норматив 60 дней | `test_acceptance_y50_mtdna_report.py::test_wgs_15x_30x_60_days_report_forbidden` | **PASS** |
| 8 | WGS + отчёт | Операция запрещена | `test_business_logic.py::test_wgs_plus_report_is_forbidden`, `test_acceptance_y50_mtdna_report.py::test_wgs_15x_30x_60_days_report_forbidden` (бизнес-логика) + `NewOrderDialog._on_save`/`TestEditDialog._on_save` (интерфейс, см. ниже) | **PASS** |
| 9 | Профиль получен | Дата профиля НЕ устанавливает автоматически «В работе» | `test_acceptance_y50_mtdna_report.py::test_y50_mtdna_plus_report_full_scenario` | **PASS** |
| 10 | Взято в работу | Строка жёлтая, если не действует более высокий приоритет | `test_business_logic.py::test_color_yellow_when_started_not_urgent` + acceptance-сценарий | **PASS** |
| 11 | 5 дней до дедлайна | Строка пурпурная | `test_business_logic.py::test_color_purple_5_days_before` + acceptance-сценарий | **PASS** |
| 12 | После дедлайна | Строка красная | `test_business_logic.py::test_color_red_after_deadline` + acceptance-сценарий | **PASS** |
| 13 | Выдан клиенту | Строка зелёная независимо от предыдущего цвета | `test_business_logic.py::test_color_green_when_issued_regardless_of_deadline` + acceptance-сценарий | **PASS** |
| 14 | Изменение типа | Дедлайн пересчитывается; запись в audit log | `test_business_logic.py::test_type_change_recalculates_deadline_and_logs_audit` | **PASS** |
| 15 | Доплата | Сумма и комментарий сохраняются | `test_business_logic.py::test_extra_payment_amount_and_comment_saved` | **PASS** |
| 16 | Возврат | Запись не исчезает | `test_business_logic.py::test_refund_does_not_delete_order` | **PASS** |
| 17 | Импорт Excel | Старые номера сохраняются | `test_excel_import.py` (12 тестов — GNS/WGS/Strelka/FULL LINE/даты/пустые ячейки/дубли) | **PASS** |
| 18 | Backup | Создаётся отдельный файл, который можно восстановить | `test_backup.py` (7 тестов, включая полный round-trip) | **PASS** |
| 19 | Два теста одного заказа | Общие данные клиента, независимые даты/статусы | `test_business_logic.py::test_two_tests_share_client_data_independent_dates`, `test_acceptance_y50_mtdna_report.py::test_y50_mtdna_plus_report_full_scenario` | **PASS** |
| 20 | Поиск | Находит по GNS, заказу, ФИО, контактам | `test_business_logic.py::test_search_finds_by_gns_order_customer` | **PASS** |
| 21 | 10+ строк | Основной экран пригоден для контроля большого числа тестов | Визуально подтверждено: 15 строк отображены без прокрутки на разрешении 1366×768 (типичный ноутбук), см. `packaging/screenshots/` | **PASS** (визуальная проверка, не unit-тест по природе требования) |

## Дополнительные критические сценарии (задачи 5-7 финального задания)

| Сценарий | Ожидаемый результат | Автотест | Результат |
|---|---|---|---|
| Y50 + mtDNA + отчёт | 2×GNPSK, 45 дней у каждого, 1 order_id, независимые даты/статусы/лаборатории/результаты, report_services без GNPSK | `test_acceptance_y50_mtdna_report.py::test_y50_mtdna_plus_report_full_scenario` | **PASS** |
| Y50 + mtDNA без отчёта | 2×GNPSK, 30 дней у каждого | `test_acceptance_y50_mtdna_report.py::test_y50_mtdna_without_report_30_days_each` | **PASS** |
| WGS 15X / WGS 30X | 60 дней; отчёт запрещён бизнес-логикой и интерфейсом | `test_acceptance_y50_mtdna_report.py::test_wgs_15x_30x_60_days_report_forbidden` (логика); `NewOrderDialog`/`TestEditDialog` вызывают `bl.validate_report_option` перед сохранением и показывают `QMessageBox.warning`, не давая сохранить (интерфейс, проверено вручную через GUI-смоук-тест) | **PASS** |

## Telegram-парсер (задача 4) — на реальном формате сообщения

| Проверка | Автотест | Результат |
|---|---|---|
| Номер заказа | `test_parses_order_number` | **PASS** |
| Название товара + сумма/кол-во строки | `test_parses_product_line_item` | **PASS** |
| Сумма платежа | `test_parses_amount` | **PASS** |
| Статус оплаты | `test_parses_payment_status` | **PASS** |
| Способ доставки | `test_parses_delivery_method` | **PASS** |
| Адрес доставки | `test_parses_delivery_address` | **PASS** |
| ФИО | `test_parses_customer_name` | **PASS** |
| Email | `test_parses_email` | **PASS** |
| Телефон | `test_parses_phone` | **PASS** |
| Код платежа | `test_parses_payment_code` | **PASS** |
| Код заявки | `test_parses_request_code` | **PASS** |
| Код блока | `test_parses_block_code` | **PASS** |
| Форма | `test_parses_form` | **PASS** |
| FULL LINE → Y50+мтДНК (2 теста, не тип "FULL LINE") | `test_full_line_message_creates_order_with_two_tests_not_full_line_type` | **PASS** |
| Нераспознанный товар → needs_review, без угадывания | `test_unrecognized_product_creates_needs_review_order_without_guessing` | **PASS** |
| Повторное сообщение → обновление, не дубль | `test_repeated_message_updates_existing_order_no_duplicate` | **PASS** |
| Bot Token не участвует в парсере | `test_parser_never_touches_bot_token_module` | **PASS** |

**Реальный Bot Token НЕ подключён** — парсер протестирован только на сохранённом тексте сообщения, сетевой клиент Telegram не реализован (см. TODO в `app/telegram_parser.py`).

## Excel-импорт (задача 1) — статус

Полное синтетическое покрытие (12 тестов в `test_excel_import.py`) всех пунктов задачи:
старые GNS, старые WGS, Strelka, исторический FULL LINE, три формата дат (текст ДД.ММ.ГГГГ,
datetime-объект Excel, ISO-текст), пустые ячейки, дубли (внутри файла и между запусками
импорта), несколько тестов одного заказа, сохранение исходных номеров без перенумерации,
предпросмотр без изменения исходного файла, ошибочные строки не теряются.

⚠️ **Реальный Excel-файл пользователя ещё не был предоставлен.** Когда файл появится —
прогнать `importer.preview_excel()` → показать пользователю предпросмотр (всего строк /
будет импортировано / дубли / ошибки / нераспознанные строки) → затем `importer.import_excel()`
и сверить статистику. Синтетические тесты гарантируют, что механизм работает корректно на
всех перечисленных пользователем случаях; они не заменяют прогон на реальных данных.

## Backup / Restore (задача 2) — статус

Полный round-trip тест: рабочая БД (заказ с 2 тестами, результатами, комментариями,
audit log) → backup → «порча» данных → restore (с автоматическим pre-restore backup) →
проверка, что восстановленная БД идентична состоянию на момент backup, а pre-restore
snapshot сохранил «испорченное» состояние. Отдельно подтверждено: backup-файл БД физически
не может содержать Telegram Bot Token, так как токен хранится в полностью отдельном файле
вне БД (`app/secrets_store.py`).

## Windows EXE (задача 3) — статус

- `.github/workflows/build-windows.yml` — воркфлоу на `windows-latest`, прогоняет `pytest`,
  собирает onedir-бандл через PyInstaller, **запускает собранный EXE и проверяет, что он не
  падает сразу** (smoke-test), собирает `GENOPOISK_CRM_Setup.exe` через Inno Setup 6
  (предустановлен на раннере), выкладывает оба артефакта.
- Конфигурация PyInstaller (`packaging/genopoisk_crm.spec`) **реально проверена сборкой под
  Linux** в этой песочнице: бинарник собрался, запустился под Xvfb, корректно создал и
  проинициализировал БД (7 типов тестов в справочнике, счётчик GNPSK). Это не заменяет
  сборку под Windows, но ловит большинство ошибок конфигурации (hidden imports, точка входа,
  onedir/onefile).
- **Не проверено**: реальная сборка на `windows-latest` (случится при первом запуске workflow
  на GitHub — среда разработки физически не может собрать нативный Windows EXE) и запуск на
  чистой Windows-машине без Python/PySide6 — это нужно проверить пользователю после первого
  прогона workflow.

## Известные ограничения на данный момент

1. Реальный Excel-файл пользователя не тестировался (только синтетический, покрывающий все
   заявленные случаи) — ждём файл.
2. Реальный Telegram Bot Token не подключён и не будет подключён до отдельного предоставления
   пользователем; сетевой клиент (polling/webhook) не реализован — только разбор текста.
3. Список коммерческих названий товаров сайта для `product_mappings` заполнен только примером
   из предоставленного сообщения (FULL LINE); полный список нужно получить от пользователя
   (раздел 28 ТЗ) и занести через `repo.upsert_product_mapping()` или будущий UI-справочник.
4. Реальная сборка и установка на чистой Windows-машине не проверена (см. выше) — первый
   прогон `windows-latest` workflow и ручная проверка пользователем обязательны.
5. Пароль на запуск приложения (раздел 21: «рекомендуется... в будущей версии») не реализован —
   явно вне первой версии по самому ТЗ.
