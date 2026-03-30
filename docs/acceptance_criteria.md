# Acceptance Criteria — Store Parsers Project

Проект считается соответствующим текущему scope, если выполняются следующие условия.

## 1. Live Run

Проект поддерживает live end-to-end run:

- запуск всех parser-ов одной командой
- запуск одного parser-а через `--network`
- сбор данных из официальных источников без ручной подготовки входных файлов

## 2. Parsers

В проекте реализованы 3 независимых parser-модуля:

- Красное & Белое
- Монетка
- Мария-Ра

Каждый parser должен:

- получать данные из своего источника
- возвращать данные в единой структуре
- корректно различать обработанные source-level проблемы и parser-level failure

## 3. Unified Schema

Каноническая схема записи магазина:

- `network`
- `region`
- `city`
- `address`
- `work_time`
- `latitude`
- `longitude`
- `phone`
- `store_format`
- `status`
- `source_url`
- `collected_at`

Требования:

- названия полей едины для всех сетей
- типы данных нормализованы
- пустые, отсутствующие или ненадежные значения сохраняются как `None` / `null`
- проект не выдумывает geography, coordinates или другие поля без надежного основания

## 4. Excel And Snapshot

Проект должен генерировать:

- Excel файл `stores.xlsx`
- snapshot JSON для baseline и diff

Excel должен содержать листы:

- `Актуальные данные`
- `Изменения`
- `Статистика`

## 5. Diff

Diff должен работать по snapshot baseline и корректно определять:

- `added`
- `removed`
- `changed`

Дополнительно:

- первый полный запуск только инициализирует baseline
- сопоставление записей должно быть детерминированным через `stable_key`
- дубликаты одной store identity не должны ухудшать snapshot или финальный export

## 6. Run Status

Семантика завершения должна быть понятной для automation:

- successful run — все выбранные parser-ы завершились без необработанного исключения
- handled warnings внутри parser-а не делают весь run failed, если `parse()` вернул результат
- если хотя бы один parser упал как модуль, весь run должен завершаться non-zero exit code

## 7. Logging

Логи должны содержать:

- начало run
- количество собранных записей
- warning и error события с корректной severity
- итог run и его статус

Ожидаемые обработанные source-level кейсы не должны логироваться так, как будто весь run аварийно завершился.

## 8. Documentation

README.md и `docs/*.md` должны честно отражать:

- как запустить live run
- как работает snapshot/diff
- что означают `added` / `removed` / `changed`
- какие поля являются best-effort
- какие ограничения есть у Monetka и Maria-Ra
- что отсутствующие или ненадежные значения сохраняются как `null`
- как интерпретировать successful и failed run в cron / Task Scheduler
