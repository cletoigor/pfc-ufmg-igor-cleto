# CLAUDE.md — TCC Monografia (UFMG)

## Project Overview

UFMG undergraduate thesis (TCC) for Control and Automation Engineering, combining a LaTeX monograph with a Dagster data pipeline that ingests IoT device data from the Tuya Cloud API.

## Repository Layout

```
latex/          — LaTeX monograph (entry point: Monografia.tex)
app/            — Dagster pipeline (entry point: app/assets.py)
  data_ingestion/
    ingestion_utils.py      — helper functions
    device_mapping.json     — device ID → name mapping
  data/
    raw/        — raw JSON files per device/date
    staging/    — partitioned Parquet (event_date=YYYY-MM-DD)
dagster.yaml    — Dagster instance config
workspace.yaml  — points Dagster to app/assets.py
```

## LaTeX Conventions

- Compile: `latexmk -pdf Monografia.tex` (from `latex/` directory)
- Citation style: ABNT
- Figure placement: `[htbp]`
- Table formatting: `booktabs`
- Label prefixes: `sec:`, `fig:`, `tab:`
- Language: formal academic Portuguese

## Data Pipeline Architecture (Dagster)

Two assets in `app/assets.py`:

1. **`raw_tuya_logs`** — fetches Tuya API logs, saves JSON to `app/data/raw/<device_id>/<YYYY-MM-DD>/`; credentials via `TuyaCredentials` Config using `EnvVar` (`ACCESS_ID`, `ACCESS_SECRET`, `API_ENDPOINT`)
2. **`staging_tuya_logs`** — reads raw JSONs, transforms via DuckDB (in-memory `DuckDBResource`), writes partitioned Parquet to `app/data/staging/`

Both are wired into `tuya_processing_job`, triggered by `hourly_schedule` (`0 * * * *`).

Start the UI: `dagster dev` from the project root (requires the Python venv in `app/.venv/` and a `.env` file with API credentials).

## Key Tech Stack

| Layer | Tool |
|---|---|
| Monograph | LaTeX + BibTeX + latexmk |
| Orchestration | Dagster + dagster-webserver |
| Transformation | DuckDB (via dagster-duckdb) |
| Storage | Parquet (staging), JSON (raw) |
| IoT API | tuya-connector-python |
| Python deps | `app/requirements.txt`, venv at `app/.venv/` |

## Files Claude Should Ignore

Generated LaTeX artifacts — do not propose edits to these:

```
latex/*.aux  latex/*.bbl  latex/*.blg  latex/*.fdb_latexmk
latex/*.fls  latex/*.log  latex/*.lof  latex/*.lot
latex/*.out  latex/*.toc  latex/*.synctex.gz  latex/*.ps
latex/Monografia.pdf  latex/**/*-eps-converted-to.pdf
latex/*/*.aux
```
