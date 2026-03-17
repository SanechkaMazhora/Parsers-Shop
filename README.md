# project_parser

Проект собирает данные о магазинах из официальных источников трех сетей:

- Красное & Белое
- Монетка
- Мария-Ра

Все парсеры приводят результат к единой модели `StoreRecord`, сохраняют Excel-отчет и поддерживают diff между двумя полными снапшотами.

## Что собирается

Обязательные поля записи:

- `network`
- `region`
- `city`
- `address`
- `work_time`
- `latitude`
- `longitude`
- `source_url`
- `collected_at`

Дополнительные поля сохраняются, если их отдает источник:

- `phone`
- `store_format`
- `status`

Если источник не отдает поле стабильно или вообще не публикует его, в итоговой записи остается `None`.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Для локальной конфигурации можно создать `.env` на основе `.env.example`:

```bash
copy .env.example .env
```

Поддерживаемые env-переменные:

- `STORE_PARSER_OUTPUT` — путь к Excel-файлу
- `STORE_PARSER_SNAPSHOT` — путь к snapshot JSON
- `STORE_PARSER_LOG_FILE` — путь к лог-файлу
- `STORE_PARSER_LOG_LEVEL` — уровень логирования
- `STORE_PARSER_TIMEOUT` — HTTP timeout в секундах

Для fallback в `MariaRaParser` при необходимости можно установить браузер Playwright:

```bash
playwright install chromium
```

## Запуск

Запуск всех парсеров:

```bash
python main.py run
```

Запуск одной сети:

```bash
python main.py run --network kb
python main.py run --network monetka
python main.py run --network maria_ra
```

Переопределение путей:

```bash
python main.py run --output output/stores.xlsx
python main.py run --snapshot output/stores_snapshot.json
```

`python main.py` без подкоманды тоже запускает полный сбор для обратной совместимости.

## Что создается на выходе

После запуска проект формирует:

- `output/stores.xlsx`
- `output/stores_snapshot.json`
- `logs/parser.log`

## Как работает diff

Diff строится не по предыдущему Excel, а по отдельному snapshot JSON.

1. При запуске проект читает предыдущий snapshot.
2. Текущие записи приводятся к детерминированному виду и получают stable key.
3. Сравнение выполняется по stable key и отслеживаемым полям.
4. После успешной выгрузки snapshot перезаписывается новым полным срезом.

Важно:

- На самом первом запуске, когда baseline еще нет, лист `Изменения` остается пустым. Это нормальное поведение: первый запуск только инициализирует baseline.
- Начиная со второго полного запуска по тому же `snapshot` будут появляться `added`, `removed` и `changed`.
- Stable key опирается на сеть, store-specific URL, координаты и fallback по локации/адресу, поэтому изменения адреса при стабильном URL попадают в `changed`, а не в `added+removed`.

## Как читать Excel

### Актуальные данные

Полный текущий срез магазинов.

### Изменения

Изменения относительно предыдущего полного snapshot:

- `added` — новая запись
- `removed` — запись исчезла из нового полного среза
- `changed` — запись осталась той же, но изменились поля

Поля `old_value` и `new_value` содержат только изменившиеся значения для `changed`.

### Статистика

Количество магазинов по сетям для текущего Excel-среза.

Excel форматируется автоматически:

- заморожена строка заголовка
- включен autofilter
- ширины колонок подбираются автоматически

## Обработка ошибок и частичных отказов

### Монетка и HTTP 404

У Монетки встречаются `404` как на city pages, так и на detail pages.

Текущее поведение проекта:

- `404` на detail page не валит общий процесс
- если магазин уже виден на city page, запись сохраняется частично из city list
- для частично восстановленной записи сохраняются хотя бы `city`, `region`, `address`, `work_time`, `source_url`, если эти поля были доступны
- проблема логируется в `logs/parser.log`
- обработка остальных магазинов продолжается

Ограничение:

- если `404` возвращает сама city page и оттуда нельзя получить список магазинов, проект не выдумывает записи и только логирует пропуск города

### Maria-Ra

- источник не всегда отдает `region`, поэтому `region=None` — ожидаемое поведение для части записей
- `city` извлекается только из реально доступных данных, без геокодинга и угадывания

### Сетевые ошибки

- HTTP-запросы идут через `requests.Session` с retry на временные ошибки
- падение одного парсера не должно останавливать остальные
- все ошибки попадают в лог

## Восстановление после ошибок

Если запуск оборвался или дал частичный результат:

1. Проверьте `logs/parser.log` и найдите первый массовый сбой.
2. Не удаляйте snapshot без причины: это baseline для diff.
3. Если snapshot поврежден или baseline нужно собрать заново, удалите только `stores_snapshot.json` и выполните полный запуск еще раз.
4. Если проблема была сетевой, повторите запуск тем же `--snapshot`, чтобы diff продолжил строиться от прежнего baseline.

## Запуск по расписанию

### Windows Task Scheduler

Пример команды:

```bash
cmd /c "cd /d C:\path\to\project_parser && .venv\Scripts\python.exe main.py run"
```

### cron / WSL

Пример:

```bash
0 6 * * * cd /path/to/project_parser && .venv/bin/python main.py run >> cron.log 2>&1
```

Для WSL в репозитории есть вспомогательный скрипт:

```bash
./run_wsl.sh setup
./run_wsl.sh test
./run_wsl.sh run
```

## Тесты

Полный прогон:

```bash
python -m pytest -q
```

Покрыты как минимум:

- модель данных
- diff/snapshot логика
- Excel-выгрузка
- критичные части нормализации парсеров
- 404/fallback сценарии у Монетки

## Структура проекта

```text
project_parser/
  core/
    diff.py
    excel_export.py
    http_client.py
    logging_config.py
    models.py
  parsers/
    kb_parser.py
    maria_ra_parser.py
    monetka_parser.py
  tests/
  docs/
  .env.example
  main.py
  requirements.txt
  pytest.ini
```

## Известные ограничения

- внешние сайты могут менять HTML, JS и внутренние endpoint-ы без предупреждения
- `Maria-Ra` не всегда публикует `region`; в таких случаях проект сохраняет `None`
- `Monetka` не всегда публикует координаты и формат магазина на detail page; проект не выдумывает эти поля
- корректность diff зависит от того, что сравниваются два полных среза и используется один и тот же snapshot baseline
