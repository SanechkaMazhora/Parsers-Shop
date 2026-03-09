# project_parser

MVP-проект для сбора данных о магазинах трех торговых сетей:

- Красное & Белое
- Монетка
- Мария-Ра

Парсеры приводят данные к единому формату и сохраняют результат в Excel.

## Назначение

Система запускает один или несколько парсеров, собирает магазины в структуру:

- network
- region
- city
- address
- work_time
- lat
- lng
- phone
- store_format
- status
- source_url
- parsed_at

Если поле недоступно в источнике, сохраняется `None`.

## Требования

- Python 3.11+ (рекомендуется 3.12)
- Доступ в интернет для загрузки данных сайтов
- Для fallback Мария-Ра: установленный Playwright браузер Chromium (опционально)

## Установка

```bash
pip install -r requirements.txt
```

## Запуск

Запуск всех парсеров:

```bash
python main.py run
```

Запуск одного парсера:

```bash
python main.py run --network kb
python main.py run --network monetka
python main.py run --network maria_ra
```

Также поддержан запуск без подкоманды (эквивалент `run`):

```bash
python main.py
```

## Результаты

- Excel: `output/stores.xlsx`
- Логи: `logs/parser.log`

Файл Excel содержит листы:

- `Актуальные данные`
- `Статистика`

