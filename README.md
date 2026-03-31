# project_parser

Live end-to-end parser suite for collecting store data from official retail sources, normalizing it into one schema, and producing an Excel report plus snapshot-based diff. The project is designed for local runs and scheduled jobs such as cron or Windows Task Scheduler.

## What It Does

- Runs all supported parsers in one command or a single parser by network name
- Collects live data from official retail sources
- Normalizes records into a single `StoreRecord` schema
- Writes `stores.xlsx`, persists a JSON snapshot baseline, and computes diff between full runs
- Returns scheduler-friendly exit codes so automation can distinguish successful and failed runs

## Supported Networks

- `kb` — Красное & Белое, REST API source
- `monetka` — Монетка, HTML crawl with city and detail pages
- `maria_ra` — Мария-Ра, JS payload extraction with Playwright fallback

## Output Schema

`network`, `region`, `city`, `address`, `work_time`, `latitude`, `longitude`, `phone`, `store_format`, `status`, `source_url`, `collected_at`

The schema is stable, but individual fields are network-dependent and best-effort. If a value cannot be recovered reliably, the project stores `null` instead of inventing data.

## Installation

Recommended Python: `3.12.x`

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Optional local config:

```bash
copy .env.example .env
```

Browser setup for Maria-Ra Playwright fallback:

```bash
python -m playwright install chromium
```

Notes:

- `requirements.txt` is pinned to a tested dependency set for reproducible installs on a clean machine.
- The browser install step is only required for the Maria-Ra Playwright fallback path. KB and Monetka do not need it.
- On Linux / CI images that do not already have browser system packages, use `python -m playwright install --with-deps chromium`.

Optional verification after setup:

```bash
python -m pytest -q
```

## Configuration

Defaults can be provided via `.env`, and CLI flags override them.

- `STORE_PARSER_OUTPUT` — Excel report path
- `STORE_PARSER_SNAPSHOT` — snapshot JSON path; if omitted, it is derived from the Excel filename
- `STORE_PARSER_LOG_FILE` — log file path
- `STORE_PARSER_LOG_LEVEL` — log level
- `STORE_PARSER_TIMEOUT` — HTTP timeout in seconds
- `STORE_PARSER_RETRIES` — retry count for temporary HTTP failures

## Run

Full live run:

```bash
python main.py run
```

Single network:

```bash
python main.py run --network kb
python main.py run --network monetka
python main.py run --network maria_ra
```

Custom artifact paths:

```bash
python main.py run --output output/stores.xlsx --snapshot output/stores_snapshot.json
```

`python main.py` without subcommand is also supported for backward compatibility and behaves like a full run.

## Success Semantics

A run is successful only if every selected parser completes without an unhandled parser-level exception.

- `0` — all selected parsers completed; handled source issues may still appear as warnings
- `1` — at least one selected parser failed at module level; partial export from successful parsers may still be written
- `130` — the run was interrupted by the user

Handled source problems inside a parser do not fail the whole run if `parse()` still returns a result. For example, an expected Monetka `404` or a partial record with missing fields can still be part of a successful run.

For cron or Task Scheduler, treat any non-zero exit code as a failed job and inspect `logs/parser.log`. Exit code `1` means the produced Excel file, if present, is incomplete from an orchestration perspective.

## Output Files

Default artifacts:

- `output/stores.xlsx`
- `output/stores_snapshot.json`
- `logs/parser.log`

`stores.xlsx` contains:

- `Актуальные данные` — current canonical dataset
- `Изменения` — diff against the previous snapshot baseline
- `Статистика` — counts by network

## Snapshot And Diff

Diff is computed against `stores_snapshot.json`, not against the previous Excel file.

- `added` — store exists in the new full snapshot and did not exist in the previous one
- `removed` — store existed in the previous full snapshot and is missing in the new one
- `changed` — store matched by `stable_key`, but tracked business fields changed

Snapshot and Excel output are canonicalized by `stable_key` before saving. If multiple rows resolve to the same store identity, the most complete row wins and ties are broken deterministically.

The first full run initializes the snapshot baseline and leaves `Изменения` empty. Re-running on the same data with the same snapshot should produce no diff.

## Data Quality And Source Limitations

- Some fields are best-effort and depend on what each source exposes.
- Missing or contradictory values are stored as `null`; the project prefers incomplete data over confidently false data.
- Monetka can return expected `404` responses for some city, pagination, or detail pages. These are logged and handled; they do not automatically mean the whole run failed.
- Monetka geography is confidence-based. Reliable signals can fill `city` and `region`, but weak hints such as detail titles, breadcrumbs-only hints, city-page paths, or technical URL segments like `shops_map/ekb/...` are not published as facts.
- Monetka `phone` is stored only when the detail page exposes a store-specific contact. Generic site-wide footer phones are ignored to avoid false data.
- If Monetka pages conflict and there is no reliable basis for a location field, `city` and/or `region` remain `null`.
- Maria-Ra often does not provide a reliable `region`. The parser fills it only from explicit source fields or explicit address text; otherwise it remains `null`.
- Maria-Ra can expose duplicate map entries for the same coordinates with conflicting text fields. The parser canonicalizes them by `stable_key` and logs the conflict instead of exporting duplicate identities.
- Some sources may expose partial coordinates or partial metadata. The project keeps the available value and leaves the missing counterpart as `null`.

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

## Scheduling

Windows Task Scheduler:

```bash
cmd /c "cd /d C:\path\to\project_parser && .venv\Scripts\python.exe main.py run"
```

cron / WSL:

```bash
0 6 * * * cd /path/to/project_parser && .venv/bin/python main.py run >> cron.log 2>&1
```

## Documentation

- [Architecture](docs/architecture.md)
- [Known Issues](docs/known_issues.md)
- [Acceptance Criteria](docs/acceptance_criteria.md)
