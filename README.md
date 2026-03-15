# project_parser

Проект собирает данные о магазинах из официальных источников трёх сетей:

- Красное & Белое
- Монетка
- Мария-Ра

Все парсеры приводят результат к единой модели `StoreRecord`, сохраняют Excel-отчёт и поддерживают diff относительно предыдущего запуска.

## Что собирается

Базовые поля записи:

- `network`
- `region`
- `city`
- `address`
- `work_time`
- `latitude`
- `longitude`
- `source_url`
- `collected_at`

Дополнительно, если источник отдаёт данные, сохраняются:

- `phone`
- `store_format`
- `status`

Если поле отсутствует на сайте, в итоговой модели сохраняется `None`.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

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

Дополнительные параметры CLI:

```bash
python main.py run --output output/stores.xlsx
python main.py run --snapshot output/stores_snapshot.json
```

`python main.py` без подкоманды тоже запускает полный сбор для обратной совместимости.

## Выходные файлы

После запуска проект создаёт:

- `output/stores.xlsx`
- `output/stores_snapshot.json`
- `logs/parser.log`

### Листы Excel

`Актуальные данные`

- полный текущий срез магазинов

`Изменения`

- `added` — новые магазины
- `removed` — исчезнувшие магазины
- `changed` — магазины, у которых изменились поля

`Статистика`

- количество магазинов по сетям

Diff строится по стабильному ключу и использует отдельный snapshot JSON, а не предыдущий Excel-файл.

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
  main.py
  requirements.txt
  pytest.ini
```

## Тесты

```bash
python -m pytest -q
```

Покрыты как минимум:

- модель данных
- diff-механизм
- Excel-генерация
- критичные части нормализации парсеров

## Ограничения парсинга

- внешние сайты могут менять HTML, JS и внутренние endpoint-ы без предупреждения
- `Мария-Ра` использует многоступенчатое извлечение и Playwright fallback не гарантирован без установленного браузера
- `Монетка` публикует данные в HTML-структуре, поэтому часть логики опирается на эвристику
- корректность diff зависит от того, что сеть продолжает отдавать стабильные URL/координаты магазинов
