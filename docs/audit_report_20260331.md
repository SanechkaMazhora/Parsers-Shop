# Audit Report 2026-03-31

## 1. Executive Summary

- Проект реально работает: полный live end-to-end run после исправлений успешно выполнен дважды.
- Текущее соответствие ТЗ: частичное. Базовый pipeline, CLI, Excel, snapshot/diff, unit-tests и live parsing работают, но часть функционала из ТЗ не реализована или реализована упрощенно.
- Итоговая оценка: **78/100**.
- Показывать работодателю прямо сейчас как рабочий прототип можно. Показывать как полностью завершенную работу строго по ТЗ — **нет**.

## 2. Audit by Area

- Architecture: модульная структура, хороший разнос по `parsers/`, `core/`, `tests/`, понятный orchestration в `main.py`. Слабые места: парсеры запускаются последовательно, parser URLs не конфигурируются, часть source-specific логики держится на эвристиках.
- KB: рабочий REST API parser, хорошие city/region/address/work_time, 3 source-level partial coordinates сохранены честно, без выдумывания второй координаты. Нет дополнительных атрибутов уровня услуг/круглосуточности.
- Monetka: live parser устойчив, 404 обрабатываются корректно как warning, geography ведет себя консервативно, false geography не обнаружена. Ограничения: координаты отсутствуют у всех 1789 записей, `status` и `store_format` не заполнены, `work_time` отсутствует у 27 точек. В ходе аудита исправлена публикация ложного телефона: общий телефон сайта больше не экспортируется как телефон магазина.
- Maria-Ra: inline JS extraction работает быстро и стабильно, координаты есть у 1308/1308 записей. В ходе аудита исправлена потеря городов с явными locality-prefix (`с.`, `п.`, `р.п.` и т.п.). `region` остается `null` у 1308/1308 записей, потому что источник отдает только технические теги (`SELECTION_WINES`, `COFFEE_FRAME`, `ROUND_CLOCK_SERVICES`, `OPENING_SOON`), а не регион.
- Diff/snapshot: реализовано хорошо. `stable_key` детерминирован, duplicate rows не портят snapshot, повторный полный run дал нулевой business diff.
- Excel/export: три листа есть, заголовки корректны, snapshot и Excel согласованы, duplicate `stable_key` не попадают в финальный export.
- Tests: сильное покрытие на diff/export/models/parser edge cases. После аудита 96/96 тестов проходят. Нет live integration tests и нет проверки документации/инструкций как executable acceptance.
- Docs: README, architecture, known issues, acceptance criteria есть и достаточно честно описывают ограничения. Но системный анализ из ТЗ лежит в `analys_*.txt`, а не в unified Markdown-пакете, и не все пункты по защите/обходу ограничений раскрыты глубоко.
- CLI/logging/scheduler: `run` и `run --network` работают, exit codes для automation корректны, логирование по severity в целом здоровое. Scheduler integration сделана на уровне documented commands, а не отдельного scheduler-модуля.
- Config/reproducibility: `requirements.txt` pinned, `.env.example` есть, output/log/snapshot/timeout/retries конфигурируются. Parser source URLs остаются hardcoded; явной конфигурации URL/proxy per parser нет.

## 3. Полная проверка по ТЗ

### 1. Общие положения

- 1.1 Наименование проекта — **выполнено**. Проект собирает данные по `Красное & Белое`, `Монетка`, `Мария-Ра`.
- 1.2 Основание для разработки — **не проверяется как кодовая функциональность**.
- 1.3 Назначение системы — **выполнено частично**: автоматический сбор, diff и Excel работают; часть полей/feature scope по отдельным сетям не закрыта.

### 2.1 Проведение системного анализа

- Реверс-инжиниринг трех сайтов — **выполнено частично**. Есть `[analys_KB.txt]`, `[analys_monetka.txt]`, `[analys_maria_ra.txt]`.
- API endpoints / структура данных / базовые механизмы — **выполнено частично**. Для KB это сделано хорошо; для Monetka/Maria-Ra описаны HTML/JS подходы.
- Аутентификация / авторизация / headers / cookies / tokens — **выполнено частично**. Maria-Ra age gate и cookies учтены; глубокого анализа headers/tokens/rate limits нет.
- CAPTCHA / rate limiting / блокировки / стратегия обхода — **не выполнено полноценно**. В docs нет глубокой стратегии обхода, ротации IP, throttling plan и formal anti-bot analysis.
- Результат этапа как техническая пояснительная записка — **выполнено частично**. Аналитические файлы есть, но пакет не собран в единый Markdown deliverable.

### 2.2 KB parser

- Работа с 18+ / раздел магазинов — **выполнено частично**. Parser обходит UI и работает напрямую через API; возрастной gate интерфейса не автоматизируется.
- Последовательный перебор регионов/городов — **выполнено**. Загружается список городов и для каждого города — shops API.
- Извлечение названия/адреса/режима/координат — **выполнено частично**. Адрес, city, region, work_time есть; координаты есть почти всегда, но 3 записи имеют только longitude, что честно сохранено как partial source data.
- Дополнительные атрибуты (круглосуточный, услуги) — **не выполнено**.
- Пагинация / dynamic loading — **не применимо / не реализуется** через выбранный API pathway.
- Логирование ошибок и пропусков — **выполнено**.

### 2.3 Monetka parser

- Логика раздела магазинов / обход регионов / городов — **выполнено**.
- Работа с интерактивной картой / кластеризацией / popup markers — **не выполнено в заявленном виде**. Реализация обходит HTML city/detail pages без headless map interaction.
- Извлечение address / work_time / phone / status — **выполнено частично**. `address` есть у 1789/1789, `work_time` у 1762/1789, `phone` теперь честно `null`, `status` не получается.
- Фильтрация по типам точек (магазины/партнеры) — **не выполнено**.
- Headless browser / скроллинг / клики / JS rendering — **не выполнено**.
- Обработка динамической подгрузки — **выполнено частично**. Есть pagination/crawl logic, но не browser-side rendering.

### 2.4 Maria-Ra parser

- Логика раздела `Карта сети` — **выполнено**.
- Обход карты с зумированием / обнаружение всех маркеров — **не выполнено в заявленном виде**. Реализация берет inline JS / external JS / data attributes / Playwright fallback вместо map zoom traversal.
- Адрес / город / режим / координаты — **выполнено частично**. После фикса `city` теперь у 1308/1308, `work_time` у 1307/1308, координаты у 1308/1308. `region` не извлекается из-за ограничения источника.
- Особенности / типы магазина / режим / статус открытия — **не выполнено**. `store_format` и `status` не получаются, фильтры не реализованы.
- Устойчивость и fallback — **выполнено**: multi-strategy extraction + Playwright fallback.

### 2.5 Постобработка данных

- Нормализация адресов — **выполнено частично**.
- Стандартизация времени — **выполнено частично**.
- Геокодирование адресов — **не выполнено**.
- Удаление дубликатов — **выполнено**.
- Excel: `Актуальные данные`, `Изменения`, `Статистика` — **выполнено**.
- Метаданные обмена в логе (дата обновления, количество магазинов, примечания об изменениях) — **выполнено частично** через runtime logging, но нет отдельного мета-слоя/журнала обмена.

### 2.6 Тестирование

- Функциональные тесты — **выполнено частично**: 96 unit/integration-like tests.
- Граничные случаи / ошибки сети / исключения — **выполнено** на unit level.
- Регрессионное тестирование — **выполнено частично**: regression tests есть на diff, schema, duplicate stable_key, Monetka 404, contradictory geography, Maria-Ra city parsing. Нет live regression against source changes.
- Уведомления об ошибках — **не выполнено** как отдельный механизм.

### 2.7 Документация

- Установка / запуск / config / examples — **выполнено**.
- Scheduler instructions — **выполнено**.
- Monitoring / logging / recovery — **выполнено частично**. Logging описан хорошо; recovery после сбоев описан ограниченно.
- Спецификация полей по сетям / known issues / действия при изменении сайтов — **выполнено частично**.

### 2.8 Производительность и совместимость

- Полная синхронизация ≤ 2 суток — **выполнено**: около 15 минут на полный run.
- Python 3.12+ — **выполнено**.
- Headless mode — **выполнено**.
- Windows / Linux — **выполнено частично**. Windows подтвержден в аудите; Linux заявлен, но не перепроверен здесь.
- Параллельный запуск parser-ов — **не выполнено**. Реализация последовательная.

### 3. Работа с данными

- 3.1 Входные данные (URLs configurable, auth, proxy) — **выполнено частично**. Output/log/timeouts/retries конфигурируются; parser URLs hardcoded; auth не нужен; proxy явно не документирован как parser setting.
- 3.2 Выходные данные (Excel, logs) — **выполнено**.

### 4. Интерфейс

- 4.1 CLI `run` / `run --network <name>` — **выполнено**.
- 4.2 Logging levels — **выполнено**. `INFO/WARNING/ERROR/DEBUG` поддерживаются.
- 4.3 Планировщик задач — **выполнено частично**. Есть documented integration examples для cron/Task Scheduler; отдельного scheduler layer нет.

### 6. Этапы и сроки разработки

- **Не является кодовым acceptance item**. Структура модулей по этапам в целом соответствует.

### 7. Состав приемо-сдаточной документации

- Исходный код — **выполнено**.
- Markdown-документация — **выполнено частично**. Основные docs в Markdown, но системный анализ по сетям лежит в `.txt`.
- Файлы конфигурации / примеры — **выполнено** (`.env.example`).

### 8. Порядок приемки работ

- Демонстрация работающей системы — **выполнено технически**: live runs успешны, артефакты созданы. Формальная презентация не относится к репозиторию.

## 4. Live Run Results

- Post-fix full run #1: `907.59s` (~15m 08s), exit code `0`, `24543` stores.
- Post-fix full run #2: `916.15s` (~15m 16s), exit code `0`, `24543` stores.
- Сети:
  - KB: `21446`
  - Monetka: `1789`
  - Maria-Ra: `1308`
- Артефакты:
  - `output/audit_postfix_run1.xlsx`
  - `output/audit_postfix_run1_snapshot.json`
  - `logs/audit_postfix_run1.log`
  - `output/audit_postfix_run2.xlsx`
  - `logs/audit_postfix_run2.log`
- Warnings/errors:
  - run #1: `8 warnings`, `0 errors`
  - `7` warnings — expected Monetka city-page `404`
  - `1` warning — Maria-Ra source duplicate normalized by stable key
- Повторный run: `added=0`, `removed=0`, `changed=0`.

## 5. Data Quality Findings

### KB

- Сильные стороны: city/region/address/work_time заполнены у `21446/21446`.
- Ограничения: `3` записи с partial coordinates; это limitation источника, не баг parser-а.
- Замечание: часть KB addresses в источнике — только номер дома (`103`, `62Б` и т.п.). Это source limitation.

### Monetka

- Geography reliability: хорошая после консервативной логики; false geography по URL slug не публикуется.
- Coordinates: `0/1789`, limitation источника/доступной HTML detail page.
- Work time: отсутствует у `27/1789`.
- Phone: после фикса `0/1789` store-specific телефонов; общий footer phone больше не экспортируется.
- Status / store_format: `0/1789`, не извлекаются из live source.
- 404 handling: корректная, не ломает run и не поднимает ложный `ERROR`.

### Maria-Ra

- City: после фикса `1308/1308`.
- Region: `0/1308`; raw source отдает только технические tokens вместо региона, поэтому `null` честный.
- Coordinates: `1308/1308`.
- Work time: отсутствует у `1/1308`.
- Duplicate markers: найден 1 конфликтный дубликат одной точки по тем же координатам, но с разным address/work_time; теперь canonicalized до export.

## 6. Diff Findings

- `stable_key` работает корректно.
- Duplicate `stable_key` в финальном snapshot: `0`.
- До исправления Maria-Ra возвращала `1309` normalized rows, но export canonicalized их до `1308`; после исправления parser сам возвращает `1308`, то есть raw/export counts согласованы.
- Повторный post-fix run дал нулевой business diff и идентичный snapshot при исключении `collected_at`.

## 7. Test Findings

- Итог: **96 passed / 96 total**.
- Сильные зоны:
  - diff identical / added / removed / changed
  - duplicate stable_key / snapshot integrity
  - schema consistency / canonical field aliases
  - Monetka 404 / contradictory geography / partial record semantics
  - KB partial coordinates
  - parser failure -> non-zero exit code
- Добавленные в ходе аудита тесты:
  - Monetka не берет глобальный footer phone как store phone
  - Monetka сохраняет только explicit store phone
  - Maria-Ra сохраняет explicit locality-prefixed city
  - Maria-Ra deduplicates conflicting duplicate stable_key
- Чего не хватает:
  - live integration tests against real sources
  - documentation acceptance tests
  - Linux compatibility smoke tests

## 8. Remaining Risks

- Строгая защита ТЗ может выявить, что Monetka и Maria-Ra реализованы не через те механики, которые описаны в ТЗ (нет headless map traversal / filters / browser interaction в required объеме).
- Maria-Ra `region` отсутствует у всех записей из-за источника; это нужно честно проговаривать на защите.
- Monetka coordinates/status/store_format отсутствуют в live dataset; это может выглядеть как недореализация, если не объяснить limitation источника.
- Parser URLs не конфигурируются из `.env`, хотя ТЗ это подразумевает.
- System analysis deliverables не собраны в единый Markdown package.

## 9. Must Fix Before Submission

- Либо реализовать, либо формально согласовать отклонения от ТЗ по Monetka и Maria-Ra:
  - отсутствие headless browser interaction / cluster traversal / filters
  - отсутствие части извлекаемых полей (`status`, `store_format`, `coordinates` у Monetka, `region` у Maria-Ra)
- Привести системный анализ и parser field specs к единому Markdown deliverable.
- Явно закрыть вопрос конфигурируемости source URLs / parser settings или задокументировать, что scope ограничен фиксированными official endpoints.

## 10. Nice to Have

- Live smoke tests по одной-двум точкам на сеть.
- Явная config support для parser source URLs.
- Export отдельного QA sheet с data-quality counters.
- Раздельные statistics по warnings/errors/source limitations.

## 11. Final Verdict

- **NOT READY FOR SUBMISSION**
- Почему: проект уже рабочий и заметно улучшен по reliability/data quality, но при строгой приемке против исходного ТЗ остаются существенные scope gaps по Monetka, Maria-Ra, системному анализу и конфигурируемости входных данных.

=== REPORT FOR CHATGPT ===

## 1. EXECUTION SUMMARY

- Полный live end-to-end run: **да**
- Собрано магазинов:
  - KB: `21446`
  - Monetka: `1789`
  - Maria-Ra: `1308`
- Ошибки:
  - `0` errors
  - `8` warnings on post-fix run #1
  - `7` expected Monetka city-page `404`
  - `1` Maria-Ra duplicate-source conflict
- Повторный run: **успешен**, diff = `0/0/0`

## 2. PROJECT STATUS

- Проект работает полностью: **да, как рабочий pipeline**
- Все парсеры работают:
  - KB: **да**
  - Monetka: **да**
  - Maria-Ra: **да**
- Критические падения: **нет**

## 3. CRITICAL ISSUES (БЛОКЕРЫ)

- Неполное соответствие ТЗ по Monetka: нет headless browser / JS interaction / cluster traversal / filters / coordinates/status/store_format. Это **scope gap**, не runtime bug. **Не исправлено**.
- Неполное соответствие ТЗ по Maria-Ra: нет map zoom traversal / filters, `region` не извлекается из live source. Это **частично limitation источника, частично scope gap**. **Не исправлено полностью**.
- Входные parser URLs не конфигурируются из настроек, хотя ТЗ ожидает configurable input URLs. Это **bug/omission относительно ТЗ**. **Не исправлено**.

## 4. MAJOR ISSUES (ВАЖНЫЕ, НО НЕ БЛОКЕРЫ)

- До аудита Monetka публиковала общий footer phone сайта как телефон магазина. Это был **data-quality bug** в `parsers/monetka_parser.py`. **Исправлено**.
- До аудита Maria-Ra теряла явные города вида `с. Первомайское`. Это был **normalization bug** в `parsers/maria_ra_parser.py`. **Исправлено**.
- До аудита Maria-Ra возвращала конфликтный duplicate stable_key и export тихо canonicalized его уже после парсера. Это был **integrity/reliability bug**. **Исправлено**.
- System analysis docs есть, но не собраны в единый Markdown package и не закрывают весь anti-bot/rate-limit scope. Это **documentation gap**. **Не исправлено**.

## 5. DATA QUALITY

### KB

- Заполненность: city/region/address/work_time у `21446/21446`
- Ошибки:
  - `3` записи с partial coordinates (`latitude=null`, `longitude!=null`)
  - это **limitation источника**, подтверждается live API payload

### Monetka

- География: **надежна условно/консервативна**
- Координаты: `0/1789`
- Статус: `0/1789`
- Проблемы:
  - source detail pages не дали store-specific coordinates/status/store_format
  - общий footer phone раньше ложноположительно публиковался; теперь `phone=null` у `1789/1789`
  - `work_time=null` у `27/1789`

### Maria-Ra

- Region: `0/1308`
- City: `1308/1308` после фикса
- Coordinates: `1308/1308`
- Проблемы:
  - источник отдает технические `region` tokens (`SELECTION_WINES`, `COFFEE_FRAME`, etc.), поэтому `region=null`
  - найден `1` конфликтный duplicate marker по тем же координатам, canonicalized parser-ом

## 6. DIFF STATUS

- Diff работает корректно: **да**
- Duplicate stable_key в snapshot: **нет**
- Дрейф данных на идентичном повторном run: **нет**

## 7. TEST STATUS

- Прошло тестов: **96/96**
- Критичные кейсы покрыты:
  - Monetka 404
  - Monetka contradictory geography
  - Maria-Ra missing fields / locality parsing
  - diff identical / added / removed / changed
  - duplicate stable_key
  - KB partial coordinates
  - parser failure -> non-zero exit code
  - schema consistency
- Не хватает:
  - live integration tests
  - Linux smoke tests
  - docs/install acceptance tests

## 8. ТЗ COMPLIANCE

- Статус: **частично соответствует**
- Не выполнены или выполнены частично:
  - 2.1 deep anti-bot / rate-limit / обход ограничений
  - 2.3 headless/browser-side Monetka scope, filters, status/coords
  - 2.4 map zoom traversal / filters / full attribute scope for Maria-Ra
  - 2.5 geocoding
  - 2.7 часть документации и recovery/system-analysis packaging
  - 2.8 parallel parser execution / Linux verification
  - 3.1 configurable source URLs in parser settings

## 9. CHANGES MADE DURING AUDIT

- Изменения:
  - убран ложный Monetka phone fallback из global page text
  - исправлена Maria-Ra city normalization для locality-prefix values
  - добавлен parser-level dedupe normalized Maria-Ra duplicates by stable_key + warning log
  - добавлены regression tests
  - обновлены README / known_issues
- Измененные файлы:
  - `parsers/monetka_parser.py`
  - `parsers/maria_ra_parser.py`
  - `tests/test_monetka_parser.py`
  - `tests/test_maria_ra_parser.py`
  - `README.md`
  - `docs/known_issues.md`

## 10. REMAINING RISKS

- На защите могут спросить, почему Monetka/Maria-Ra не реализованы через browser/map mechanics из ТЗ.
- На защите могут считать `region=null` у Maria-Ra и `coordinates/status/store_format=null` у Monetka недореализацией, если не объяснить limitation источника.
- Будущие изменения HTML/JS на сайтах могут сломать parser-ы, live regression harness нет.

## 11. FINAL SCORE

- **78/100**

## 12. FINAL VERDICT

- **NOT READY FOR SUBMISSION**
- Причина: рабочий pipeline и data quality теперь заметно лучше, но при строгой оценке против исходного ТЗ остаются существенные незакрытые scope-требования по Monetka, Maria-Ra, system analysis и configurability.
