# project_parser

Парсер торговых сетей (MVP), который собирает данные о магазинах:

- Красное & Белое
- Монетка
- Мария-Ра

Система приводит данные к единой модели, сохраняет Excel-отчет и пишет логи выполнения.

## Цель проекта

Автоматизировать сбор адресов и атрибутов магазинов из разных источников (REST API, HTML, встроенный JS) в единый формат:

- `network`
- `region`
- `city`
- `address`
- `work_time`
- `lat`
- `lng`
- `phone`
- `store_format`
- `status`
- `source_url`
- `parsed_at`

## Архитектура

```text
project_parser/
  parsers/
    kb_parser.py
    monetka_parser.py
    maria_ra_parser.py
  core/
    http_client.py
    models.py
    excel_export.py
    logging_config.py
  tests/
  logs/
  output/
  main.py
  requirements.txt
  implementation_plan.md
```

## Parser Strategies

- `KBParser` uses `/api/cities/list/` for city+region metadata and then loads stores via `/api/cities/{id}/shops/`.
- `MonetkaParser` uses HTML parsing flow (`seed -> city pages -> store pages`) and extracts city/region per individual store page.
- `MariaRaParser` is requests-first (inline JS, external JS, HTML-embedded map payloads) with optional Playwright fallback.
- In some Linux environments, Playwright may require additional system libraries (for example `libnspr4` and related dependencies). If unavailable, fallback is skipped with a warning.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Для fallback в `MariaRaParser`:

```bash
playwright install chromium
```

## Запуск

Запуск всех парсеров:

```bash
python main.py
python main.py run
```

Запуск отдельной сети:

```bash
python main.py run --network kb
python main.py run --network monetka
python main.py run --network maria_ra
```

Если один парсер падает, остальные продолжают работу.

## Excel-результат

Файл: `output/stores.xlsx`

Листы:

1. `Актуальные данные` — полный актуальный срез.
2. `Изменения` — сравнение с предыдущим файлом по ключу `(network, city, address)`.
3. `Статистика` — агрегаты по количеству магазинов.

Лист `Изменения` содержит:

- `network`
- `city`
- `address`
- `change_type` (`added`, `removed`, `updated:<field>`)
- `old_value`
- `new_value`
- `detected_at`

Отслеживаемые поля обновлений: `work_time`, `phone`, `store_format`, `status`.

## Логирование

- Файл: `logs/parser.log`
- Уровни: `INFO`, `WARNING`, `ERROR`
- Есть вывод в консоль и timestamp в каждой записи.

## Тесты

```bash
python -m pytest -q
```

Базово покрыто:

- модель `StoreRecord`
- формирование Excel и листов
- часть нормализации в парсерах

## Известные ограничения

- Внешние сайты могут менять структуру HTML/JS и endpoint-ы.
- Для некоторых магазинов часть полей недоступна в источнике и сохраняется как `None`.
- `Мария-Ра` использует многоступенчатый подход; fallback на Playwright требует установленный браузер.
