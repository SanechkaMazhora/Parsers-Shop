# project_parser

Parser suite for collecting store data from official retail sources, normalizing it into a single schema, and exporting the result as Excel plus snapshot-based diff.

## Supported Networks

- Красное & Белое
- Монетка
- Мария-Ра

## Core Features

- Collects store data into a unified `StoreRecord` schema
- Saves the current full dataset to Excel
- Persists a JSON snapshot and computes diff between full runs
- Exposes a simple CLI for full or per-network execution

Unified output fields:

`network`, `region`, `city`, `address`, `work_time`, `latitude`, `longitude`, `phone`, `store_format`, `status`, `source_url`, `collected_at`

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Optional local config:

```bash
copy .env.example .env
```

Optional Playwright install for Maria-Ra fallback:

```bash
playwright install chromium
```

## Configuration

Project configuration is intentionally minimal. Defaults can be overridden via `.env`, and `--output` / `--snapshot` CLI flags override env values.

Supported env variables:

- `STORE_PARSER_OUTPUT` — Excel report path
- `STORE_PARSER_SNAPSHOT` — snapshot JSON path; if omitted, it is derived from the Excel filename
- `STORE_PARSER_LOG_FILE` — log file path
- `STORE_PARSER_LOG_LEVEL` — log level
- `STORE_PARSER_TIMEOUT` — HTTP timeout in seconds
- `STORE_PARSER_RETRIES` — HTTP retry count for temporary failures

Example:

```bash
copy .env.example .env
```

## Run

Full run:

```bash
python main.py run
```

Single network:

```bash
python main.py run --network kb
python main.py run --network monetka
python main.py run --network maria_ra
```

Custom output paths:

```bash
python main.py run --output output/stores.xlsx --snapshot output/stores_snapshot.json
```

`python main.py` without subcommand is also supported for backward compatibility.

## Output

Default artifacts:

- `output/stores.xlsx`
- `output/stores_snapshot.json`
- `logs/parser.log`

`stores.xlsx` contains:

- `Актуальные данные`
- `Изменения`
- `Статистика`

## Diff

Diff is built against `stores_snapshot.json`, not against the previous Excel file.

- `added` — store exists in the new full snapshot and did not exist in the previous one
- `removed` — store existed in the previous full snapshot and is missing in the new one
- `changed` — store is matched by stable key, but tracked fields changed

First run initializes the baseline snapshot and keeps the `Изменения` sheet empty. Re-running on the same data with the same snapshot should produce zero changes.

## Project Structure

```text
project_parser/
  core/
  parsers/
  tests/
  docs/
  main.py
  requirements.txt
```

## Limitations / Known Issues

- Source websites can change HTML, JS, or internal endpoints without notice.
- Some fields are not consistently available from source systems. In that case the project stores `null` instead of inventing values.
- Monetka may return `404` for some city pages and detail pages. These errors are logged, the full run continues, and partial store data is kept when it is already available.
- Diff quality depends on comparing full runs against the same snapshot baseline.

## Scheduled Execution

Windows Task Scheduler:

```bash
cmd /c "cd /d C:\path\to\project_parser && .venv\Scripts\python.exe main.py run"
```

cron / WSL:

```bash
0 6 * * * cd /path/to/project_parser && .venv/bin/python main.py run >> cron.log 2>&1
```
