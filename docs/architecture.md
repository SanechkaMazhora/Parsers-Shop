# Architecture

Проект реализует систему автоматизированного сбора данных о магазинах.

## Компоненты

### Parsers

Отдельные модули для каждой сети:

- kb_parser
- monetka_parser
- maria_ra_parser

Каждый парсер отвечает за:

- получение данных
- извлечение информации
- преобразование в общую модель

---

### Data Model

Все записи магазинов представлены одной моделью.

Пример:

Store(
    network,
    region,
    city,
    address,
    work_time,
    latitude,
    longitude,
    source_url,
    collected_at
)

---

### Diff Engine

Сравнивает два снапшота данных.

Определяет:

- added
- removed
- changed

---

### Export

Генерирует Excel файл с результатами.

Используются листы:

- Актуальные данные
- Изменения
- Статистика

---

### CLI

Командный интерфейс для запуска:

run
run --network