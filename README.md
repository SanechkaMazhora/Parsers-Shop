# project_parser

Парсерный pipeline для `Красное & Белое`, `Монетка` и `Мария-Ра`. Проект выполняет live-сбор, нормализует данные в единую схему, пишет `stores.xlsx`, сохраняет snapshot baseline и считает diff между полными прогонами.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
python main.py run
```

Для Playwright fallback у `Maria-Ra`:

```bash
python -m playwright install chromium
```

## CLI

Полный run:

```bash
python main.py run
```

Одна сеть:

```bash
python main.py run --network kb
python main.py run --network monetka
python main.py run --network maria_ra
```

Свои пути артефактов:

```bash
python main.py run --output output/stores.xlsx --snapshot output/stores_snapshot.json
```

## Output

- `output/stores.xlsx`
- `output/stores_snapshot.json`
- `logs/parser.log`

`stores.xlsx` содержит листы:

- `Актуальные данные`
- `Изменения`
- `Статистика`

Каноническая схема:

`network`, `region`, `city`, `address`, `work_time`, `latitude`, `longitude`, `phone`, `store_format`, `status`, `source_url`, `collected_at`

## Exit codes

- `0` — все выбранные parser-модули завершились успешно
- `1` — хотя бы один parser упал на уровне модуля; partial export может быть создан, но snapshot baseline не обновляется
- `130` — run прерван пользователем

Ожидаемые source-level проблемы внутри parser-а не делают весь run failed, если `parse()` вернул результат.
Если parser падает на frontier/source-discovery этапе, run завершается с `exit code 1`, чтобы не фиксировать ложный baseline.

## Snapshot and diff

Diff считается по `stores_snapshot.json`.

- `added` — новая точка появилась в новом полном snapshot
- `removed` — точка исчезла из нового полного snapshot
- `changed` — точка совпала по `stable_key`, но изменились отслеживаемые поля

Первый полный run только инициализирует baseline и оставляет лист `Изменения` пустым.
При неуспешном parser-level run Excel все еще может быть создан для диагностики, но diff принудительно считается initial, а snapshot baseline сохраняется без изменений.

## Configuration

Настройки можно передавать через `.env` или переменные окружения:

- `STORE_PARSER_OUTPUT`
- `STORE_PARSER_SNAPSHOT`
- `STORE_PARSER_LOG_FILE`
- `STORE_PARSER_LOG_LEVEL`
- `STORE_PARSER_TIMEOUT`
- `STORE_PARSER_RETRIES`
- `STORE_PARSER_KB_BASE_URL`
- `STORE_PARSER_MONETKA_BASE_URL`
- `STORE_PARSER_MARIA_RA_BASE_URL`
- `STORE_PARSER_MARIA_RA_MAP_URL`

По умолчанию используются официальные source URLs. Менять их стоит только осознанно.

## Known limitations

- `Monetka` может не отдавать координаты, `status` и `store_format` на detail pages; такие поля сохраняются как `null`.
- `Monetka` может возвращать ожидаемые `404` для части city/pagination pages; это нормальное поведение источника и логируется как `WARNING`.
- `Monetka` phone заполняется только если detail page явно содержит store-specific контакт. Глобальный phone сайта намеренно не публикуется.
- `Maria-Ra` в live source не дает надежный `region`; поле намеренно остается `null`.
- Часть полей во всех сетях best-effort. Если значение нельзя получить надежно, проект сохраняет `null`, а не выдумывает данные.
- `KB` иногда отдает partial coordinates; проект сохраняет доступную координату и не достраивает вторую искусственно.

## Scheduling

Windows Task Scheduler:

```bash
cmd /c "cd /d C:\path\to\project_parser && .venv\Scripts\python.exe main.py run"
```

cron / WSL:

```bash
0 6 * * * cd /path/to/project_parser && .venv/bin/python main.py run >> cron.log 2>&1
```

## Docs

- [Architecture](docs/architecture.md)
- [Known Issues](docs/known_issues.md)
- [Acceptance Criteria](docs/acceptance_criteria.md)
- [Audit Report](docs/audit_report_20260331.md)
